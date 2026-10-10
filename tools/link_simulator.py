"""回線障害を再現する、試験用のHTTP中継サーバー(標準ライブラリのみ)。

Outboxのワーカー → このモック → クラウドAPI の間に挟み、遅延・帯域・欠落・瞬断を再現する。

    python tools/link_simulator.py --upstream https://example.invalid \\
        --listen 127.0.0.1:8090 --control 127.0.0.1:8091 [--seed N] [--config file.json] [--preset NAME]

注意:
- 設定値とプリセットは試験用の例であり、実際の衛星回線などの実測性能ではない。実衛星では検証していない
- 転送先は起動時の --upstream だけ。リクエスト行の絶対URLや Host ヘッダーは無視し、パスとクエリだけを転送する
- ログ・統計・例外メッセージに、ヘッダー(X-Gateway-Key を含む)、本文、クエリを出さない
- パケットの中身は改変しない

詳しくは docs/link-simulator.md。
"""

import argparse
import http.client
import json
import random
import select
import socket
import ssl
import struct
import sys
import threading
import time
from collections import deque
from dataclasses import asdict, dataclass, fields, replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable
from urllib.parse import parse_qs, urlsplit

MAX_BODY_BYTES = 64 * 1024
# 413 を返す前に読み捨てる本文の上限。読まずに閉じると、OSが接続をリセットし、クライアントが413を読めないことがある。
DRAIN_LIMIT_BYTES = 1024 * 1024
# 受け付けた接続のソケットのタイムアウト(読み込みや keep-alive の待ちに上限を付ける)。
CLIENT_SOCKET_TIMEOUT_SECONDS = 30.0
# hang 中に、クライアントの切断と停止要求を確かめる間隔。
HANG_POLL_SECONDS = 0.1
# 停止のときに、serve_forever のスレッドを待つ上限。
SHUTDOWN_JOIN_SECONDS = 5.0
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
UPSTREAM_TIMEOUT_SECONDS = 60.0
RECENT_DELAY_WINDOW = 100
LOOPBACK = "127.0.0.1"
# 接続を即座に切る(RST)ための SO_LINGER(有効、0秒)。構造体の形は OS で違う。
_LINGER_RESET = struct.pack("HH", 1, 0) if sys.platform == "win32" else struct.pack("ii", 1, 0)

# 上流へ転送するヘッダー(許可したものだけ)。Connection や Transfer-Encoding などの hop-by-hop は転送しない。
FORWARDED_REQUEST_HEADERS = (
    "Content-Type",
    "Accept",
    "Accept-Encoding",
    "Accept-Language",
    "User-Agent",
    "X-Gateway-Key",
)
# 応答から取り除くヘッダー(hop-by-hop と、こちらで付け直す Content-Length)。
HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "content-length",
}

DROP_MODES = ("reset", "hang")

# 結果
FORWARDED = "forwarded"
DELAYED = "delayed"
DROPPED_REQUEST = "dropped_request"
DROPPED_RESPONSE = "dropped_response"
DOWN = "down"
UPSTREAM_ERROR = "upstream_error"
TOO_LARGE = "too_large"
LENGTH_REQUIRED = "length_required"


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class SimConfig:
    delay_ms: float = 0.0
    jitter_ms: float = 0.0
    drop_request_rate: float = 0.0
    drop_response_rate: float = 0.0
    drop_mode: str = "reset"
    hang_seconds: float = 30.0
    bandwidth_kbps: float = 0.0
    down: bool = False
    # 指定すると、その秒数だけ down にして自動で復旧する(設定の更新時・起動時に一度だけ効く)。
    down_for_seconds: float | None = None


# 設定値の範囲(試験用の上限)。
_NUMBER_RANGES = {
    "delay_ms": (0.0, 600_000.0),
    "jitter_ms": (0.0, 600_000.0),
    "drop_request_rate": (0.0, 1.0),
    "drop_response_rate": (0.0, 1.0),
    "hang_seconds": (0.0, 3600.0),
    "bandwidth_kbps": (0.0, 10_000_000.0),
    "down_for_seconds": (0.0, 86_400.0),
}
_CONFIG_KEYS = {item.name for item in fields(SimConfig)}


def validate_update(update: dict) -> dict:
    """設定の部分更新を検証する。範囲外・不明なキー・型違いは ConfigError。"""
    if not isinstance(update, dict):
        raise ConfigError("config must be a JSON object")
    unknown = sorted(set(update) - _CONFIG_KEYS)
    if unknown:
        raise ConfigError(f"unknown config keys: {', '.join(unknown)}")
    cleaned: dict = {}
    for key, value in update.items():
        if key == "drop_mode":
            if value not in DROP_MODES:
                raise ConfigError("drop_mode must be 'reset' or 'hang'")
            cleaned[key] = value
        elif key == "down":
            if not isinstance(value, bool):
                raise ConfigError("down must be true or false")
            cleaned[key] = value
        else:
            if key == "down_for_seconds" and value is None:
                cleaned[key] = None
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ConfigError(f"{key} must be a number")
            low, high = _NUMBER_RANGES[key]
            if not (low <= float(value) <= high):
                raise ConfigError(f"{key} must be between {low:g} and {high:g}")
            cleaned[key] = float(value)
    return cleaned


# プリセット(設定のひな形)。
# 数値は、これまでの試験条件(帯域 256 kbps〜1 Mbps、遅延 500〜2,000 ms、欠落 3〜10%、瞬断 30秒〜数分)の例であり、
# 実際の衛星回線などの実測性能ではない。
PRESETS: dict[str, dict] = {
    "clean": {},
    "slow-link": {"bandwidth_kbps": 256, "delay_ms": 500, "jitter_ms": 200},
    "lossy-link": {"delay_ms": 1000, "jitter_ms": 500, "drop_request_rate": 0.05, "drop_response_rate": 0.05},
    "very-poor-link": {
        "bandwidth_kbps": 256,
        "delay_ms": 2000,
        "jitter_ms": 500,
        "drop_request_rate": 0.10,
        "drop_response_rate": 0.10,
    },
    "outage-30s": {"down_for_seconds": 30},
}


def preset_config(name: str) -> SimConfig:
    if name not in PRESETS:
        raise ConfigError(f"unknown preset: {name} (available: {', '.join(PRESETS)})")
    return replace(SimConfig(), **validate_update(PRESETS[name]))


@dataclass(frozen=True)
class Upstream:
    scheme: str
    host: str
    port: int
    base_path: str

    @property
    def display(self) -> str:
        return f"{self.scheme}://{self.host}:{self.port}{self.base_path}"


def parse_upstream(url: str) -> Upstream:
    """--upstream を検証する。クレデンシャル・クエリ・フラグメントを含むURLは受け付けない(値はメッセージに出さない)。"""
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        raise ConfigError("--upstream must be an http(s) URL") from None
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ConfigError("--upstream must be an http(s) URL")
    if parts.username or parts.password:
        raise ConfigError("--upstream must not contain credentials (user:pass@)")
    if parts.query or parts.fragment:
        raise ConfigError("--upstream must not contain a query or fragment")
    default_port = 443 if parts.scheme == "https" else 80
    return Upstream(parts.scheme, parts.hostname, port or default_port, parts.path.rstrip("/"))


def parse_host_port(value: str, option: str) -> tuple[str, int]:
    host, separator, port_text = value.rpartition(":")
    if not separator or not host or not port_text.isdigit() or not (0 <= int(port_text) <= 65535):
        raise ConfigError(f"{option} must be HOST:PORT")
    return host, int(port_text)


# ---- 判断と状態 ----


@dataclass(frozen=True)
class Plan:
    """1件のリクエストの扱い。"""

    outcome: str  # FORWARDED / DROPPED_REQUEST / DOWN
    delay_seconds: float = 0.0
    drop_response: bool = False
    drop_mode: str = "reset"
    hang_seconds: float = 0.0


class LinkSimulator:
    def __init__(
        self,
        initial: SimConfig,
        *,
        seed: int | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] | None = None,
        log: Callable[[str], None] | None = None,
    ):
        self.initial = initial
        self.seed = seed
        self.clock = clock
        # 停止要求。遅延や hang の待ちは、これが立つとすぐに終わる。
        self.stopping = threading.Event()
        # 遅延・帯域の待ち。既定は、停止要求で中断できる実際の待ち。テストでは時計と一緒に差し替える。
        self.sleep = sleep or (lambda seconds: self.stopping.wait(max(seconds, 0.0)))
        self.log = log or (lambda line: print(line, flush=True))
        self._lock = threading.Lock()
        self._rng = random.Random(seed)
        self._config = initial
        self._down_until: float | None = None
        self._reset_stats()
        self._apply_down_settings(initial)

    # 状態

    def _reset_stats(self) -> None:
        self._stats = {
            FORWARDED: 0,
            DROPPED_REQUEST: 0,
            DROPPED_RESPONSE: 0,
            "down_rejected": 0,
            DELAYED: 0,
            UPSTREAM_ERROR: 0,
            TOO_LARGE: 0,
            LENGTH_REQUIRED: 0,
        }
        self._recent_delays: deque[float] = deque(maxlen=RECENT_DELAY_WINDOW)

    def _apply_down_settings(self, config: SimConfig) -> None:
        if config.down_for_seconds is not None:
            self._down_until = self.clock() + config.down_for_seconds
            self._config = replace(config, down=True, down_for_seconds=None)
        elif not config.down:
            self._down_until = None

    def _refresh_down(self) -> None:
        if self._down_until is not None and self.clock() >= self._down_until:
            # 一定時間の down が終わったので、自動で復旧する。
            self._down_until = None
            self._config = replace(self._config, down=False)
            self.log("event=auto_up")

    def config_snapshot(self) -> dict:
        with self._lock:
            self._refresh_down()
            snapshot = asdict(self._config)
            snapshot.pop("down_for_seconds")
            remaining = None if self._down_until is None else max(0.0, self._down_until - self.clock())
            snapshot["down_remaining_seconds"] = remaining
            return snapshot

    def update_config(self, update: dict) -> dict:
        cleaned = validate_update(update)
        with self._lock:
            new_config = replace(self._config, **cleaned)
            if "down" in cleaned and cleaned.get("down_for_seconds") is None:
                # down を直接指定したときは、一定時間の down の予定を消す(true なら up するまで down)。
                self._down_until = None
            self._config = new_config
            self._apply_down_settings(new_config)
        return self.config_snapshot()

    def apply_preset(self, name: str) -> dict:
        config = preset_config(name)
        with self._lock:
            self._config = config
            self._down_until = None
            self._apply_down_settings(config)
        self.log(f"event=preset name={name}")
        return self.config_snapshot()

    def set_down(self, seconds: float | None) -> dict:
        if seconds is not None:
            validate_update({"down_for_seconds": seconds})
        with self._lock:
            if seconds is None:
                self._down_until = None
                self._config = replace(self._config, down=True)
            else:
                self._apply_down_settings(replace(self._config, down_for_seconds=float(seconds)))
        self.log("event=down" + ("" if seconds is None else f" seconds={float(seconds):g}"))
        return self.config_snapshot()

    def set_up(self) -> dict:
        with self._lock:
            self._down_until = None
            self._config = replace(self._config, down=False)
        self.log("event=up")
        return self.config_snapshot()

    def reset(self) -> dict:
        with self._lock:
            # 起動時の設定に戻し、カウンターを0にする。起動時の down_for_seconds(outage-30s)は再開しない。
            self._config = replace(self.initial, down_for_seconds=None)
            self._down_until = None
            self._rng = random.Random(self.seed)
            self._reset_stats()
        self.log("event=reset")
        return self.config_snapshot()

    def stats(self) -> dict:
        with self._lock:
            delays = list(self._recent_delays)
            result = dict(self._stats)
        result["recent_delay_ms_avg"] = round(sum(delays) / len(delays), 1) if delays else None
        result["recent_delay_ms_max"] = round(max(delays), 1) if delays else None
        result["recent_delay_window"] = len(delays)
        return result

    def count(self, key: str) -> None:
        with self._lock:
            self._stats[key] += 1

    def hang(self, connection: socket.socket, seconds: float) -> str:
        """応答せずに待つ。上限は seconds。クライアントの切断か停止要求で、すぐに終わる。終わった理由を返す。

        この待ちは、テストでも実際の時間を使う(クライアントのタイムアウトを起こすため)。
        """
        deadline = time.monotonic() + max(seconds, 0.0)
        while True:
            if self.stopping.is_set():
                return "shutdown"
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return "timeout"
            try:
                readable, _, _ = select.select([connection], [], [], min(HANG_POLL_SECONDS, remaining))
                if readable and not connection.recv(1, socket.MSG_PEEK):
                    return "client_closed"
            except (OSError, ValueError):
                return "client_closed"

    # 判断

    def plan(self) -> Plan:
        """設定と乱数から、1件の扱いを決める。乱数は毎回同じ順で3つ引く(同じ seed なら同じ結果)。"""
        with self._lock:
            self._refresh_down()
            config = self._config
            drop_request_roll = self._rng.random()
            jitter_roll = self._rng.uniform(-1.0, 1.0)
            drop_response_roll = self._rng.random()
        if config.down:
            return Plan(DOWN, drop_mode=config.drop_mode, hang_seconds=config.hang_seconds)
        if drop_request_roll < config.drop_request_rate:
            return Plan(DROPPED_REQUEST, drop_mode=config.drop_mode, hang_seconds=config.hang_seconds)
        delay_ms = max(0.0, config.delay_ms + jitter_roll * config.jitter_ms)
        return Plan(
            FORWARDED,
            delay_seconds=delay_ms / 1000.0,
            drop_response=drop_response_roll < config.drop_response_rate,
        )

    def transfer_seconds(self, byte_count: int) -> float:
        """帯域の上限から、本文の転送にかかる時間を求める(0 kbps は無制限)。"""
        with self._lock:
            bandwidth = self._config.bandwidth_kbps
        if bandwidth <= 0 or byte_count <= 0:
            return 0.0
        return byte_count * 8 / (bandwidth * 1000.0)

    def record_delay(self, delay_ms: float) -> None:
        with self._lock:
            self._recent_delays.append(delay_ms)
            if delay_ms > 0:
                self._stats[DELAYED] += 1


# ---- HTTP ----


def _forward_to_upstream(upstream: Upstream, method: str, path_and_query: str, headers: dict, body: bytes,
                         timeout: float) -> tuple[int, str, list[tuple[str, str]], bytes]:
    if upstream.scheme == "https":
        connection = http.client.HTTPSConnection(
            upstream.host, upstream.port, timeout=timeout, context=ssl.create_default_context()
        )
    else:
        connection = http.client.HTTPConnection(upstream.host, upstream.port, timeout=timeout)
    try:
        # http.client はリダイレクトを追わない。応答はそのまま返す。
        connection.request(method, upstream.base_path + path_and_query, body=body or None, headers=headers)
        response = connection.getresponse()
        data = response.read(MAX_RESPONSE_BYTES + 1)
        if len(data) > MAX_RESPONSE_BYTES:
            raise http.client.HTTPException("upstream response too large")
        return response.status, response.reason, response.getheaders(), data
    finally:
        connection.close()


def make_proxy_handler(simulator: LinkSimulator, upstream: Upstream,
                       upstream_timeout: float = UPSTREAM_TIMEOUT_SECONDS):
    class ProxyHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "link-simulator"
        sys_version = ""
        # 読み込みと keep-alive の待ちに上限を付ける。
        timeout = CLIENT_SOCKET_TIMEOUT_SECONDS

        def log_message(self, *args):
            # 既定のアクセスログ(パスやクエリを含む)は出さない。
            pass

        def _log(self, outcome: str, started: float, delay_ms: float = 0.0, status: int | None = None,
                 request_bytes: int = 0, response_bytes: int = 0) -> None:
            elapsed_ms = (simulator.clock() - started) * 1000.0
            simulator.log(
                f"result={outcome} delay_ms={delay_ms:.0f} upstream_status={status if status is not None else '-'} "
                f"request_bytes={request_bytes} response_bytes={response_bytes} elapsed_ms={elapsed_ms:.0f}"
            )

        def _send_simple(self, status: int, message: str) -> None:
            data = json.dumps({"error": message}).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(data)
            self.close_connection = True

        def _fail(self, plan: Plan) -> None:
            self.close_connection = True
            if plan.drop_mode == "hang":
                # 応答せずに待ち、クライアントのタイムアウトを起こす。上限は hang_seconds。
                # クライアントが切断したら、またはモックを止めたら、すぐに終わる。
                reason = simulator.hang(self.connection, plan.hang_seconds)
                simulator.log(f"event=hang_end reason={reason}")
                return
            # 接続を即座に切る(RST)。
            try:
                self.connection.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, _LINGER_RESET)
            except OSError:
                pass

        def _drop_connection(self) -> None:
            self.close_connection = True
            try:
                self.connection.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, _LINGER_RESET)
            except OSError:
                pass

        def _read_body(self) -> bytes | None:
            if "chunked" in self.headers.get("Transfer-Encoding", "").lower():
                return None
            length_text = self.headers.get("Content-Length")
            if length_text is None:
                return b""
            try:
                length = int(length_text)
            except ValueError:
                return None
            if length < 0:
                return None
            if length > MAX_BODY_BYTES:
                self._drain(length)
                raise OverflowError
            return self.rfile.read(length)

        def _drain(self, length: int) -> None:
            # 413 を返す前に、本文を上限まで読み捨てる(未読のまま閉じると、接続がリセットされることがある)。
            remaining = min(length, DRAIN_LIMIT_BYTES)
            try:
                while remaining > 0:
                    chunk = self.rfile.read(min(remaining, 64 * 1024))
                    if not chunk:
                        break
                    remaining -= len(chunk)
            except OSError:
                pass

        def _handle(self) -> None:
            started = simulator.clock()
            try:
                body = self._read_body()
            except OverflowError:
                simulator.count(TOO_LARGE)
                self._send_simple(413, "request body too large")
                self._log(TOO_LARGE, started)
                return
            if body is None:
                simulator.count(LENGTH_REQUIRED)
                self._send_simple(411, "Content-Length is required")
                self._log(LENGTH_REQUIRED, started)
                return

            plan = simulator.plan()
            if plan.outcome == DOWN:
                simulator.count("down_rejected")
                self._log(DOWN, started, request_bytes=len(body))
                self._fail(plan)
                return
            if plan.outcome == DROPPED_REQUEST:
                simulator.count(DROPPED_REQUEST)
                self._log(DROPPED_REQUEST, started, request_bytes=len(body))
                self._fail(plan)
                return

            delay_ms = plan.delay_seconds * 1000.0
            simulator.record_delay(delay_ms)
            simulator.sleep(plan.delay_seconds + simulator.transfer_seconds(len(body)))

            # 転送先は --upstream だけ。リクエスト行の絶対URLや Host ヘッダーは使わず、パスとクエリだけを使う。
            target = urlsplit(self.path)
            path_and_query = (target.path or "/") + (f"?{target.query}" if target.query else "")
            headers = {name: self.headers[name] for name in FORWARDED_REQUEST_HEADERS if self.headers.get(name)}
            try:
                status, reason, response_headers, data = _forward_to_upstream(
                    upstream, self.command, path_and_query, headers, body, upstream_timeout
                )
            except (OSError, http.client.HTTPException) as exc:
                simulator.count(UPSTREAM_ERROR)
                self._send_simple(502, f"upstream error: {exc.__class__.__name__}")
                self._log(UPSTREAM_ERROR, started, delay_ms, request_bytes=len(body))
                return

            simulator.sleep(simulator.transfer_seconds(len(data)))
            if plan.drop_response:
                # 上流は処理済み。応答だけを破棄して接続を切る。
                simulator.count(DROPPED_RESPONSE)
                self._log(DROPPED_RESPONSE, started, delay_ms, status, len(body), len(data))
                self._drop_connection()
                return

            simulator.count(FORWARDED)
            self.send_response(status, reason)
            for name, value in response_headers:
                if name.lower() not in HOP_BY_HOP_HEADERS:
                    self.send_header(name, value)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(data)
            self._log(DELAYED if delay_ms > 0 else FORWARDED, started, delay_ms, status, len(body), len(data))

        do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_HEAD = do_OPTIONS = _handle

    return ProxyHandler


def make_control_handler(simulator: LinkSimulator):
    class ControlHandler(BaseHTTPRequestHandler):
        server_version = "link-simulator-control"
        sys_version = ""
        timeout = CLIENT_SOCKET_TIMEOUT_SECONDS

        def log_message(self, *args):
            pass

        def _reply(self, status: int, payload: dict) -> None:
            data = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            path = urlsplit(self.path).path
            if path == "/sim/config":
                self._reply(200, simulator.config_snapshot())
            elif path == "/sim/stats":
                self._reply(200, simulator.stats())
            else:
                self._reply(404, {"error": "not found"})

        def do_POST(self):
            parts = urlsplit(self.path)
            query = parse_qs(parts.query)
            try:
                if parts.path == "/sim/config":
                    try:
                        length = int(self.headers.get("Content-Length") or 0)
                    except ValueError:
                        raise ConfigError("Content-Length must be a number") from None
                    if length > MAX_BODY_BYTES:
                        self._reply(413, {"error": "config too large"})
                        return
                    try:
                        update = json.loads(self.rfile.read(length) or b"{}")
                    except json.JSONDecodeError:
                        raise ConfigError("config must be valid JSON") from None
                    self._reply(200, simulator.update_config(update))
                elif parts.path == "/sim/down":
                    seconds = query.get("seconds", [None])[0]
                    if seconds is not None:
                        try:
                            seconds = float(seconds)
                        except ValueError:
                            raise ConfigError("seconds must be a number") from None
                    self._reply(200, simulator.set_down(seconds))
                elif parts.path == "/sim/up":
                    self._reply(200, simulator.set_up())
                elif parts.path == "/sim/reset":
                    self._reply(200, simulator.reset())
                elif parts.path == "/sim/preset":
                    self._reply(200, simulator.apply_preset(query.get("name", [""])[0]))
                else:
                    self._reply(404, {"error": "not found"})
            except ConfigError as exc:
                self._reply(400, {"error": str(exc)})

    return ControlHandler


@dataclass
class RunningSimulator:
    simulator: LinkSimulator
    proxy: ThreadingHTTPServer
    control: ThreadingHTTPServer
    threads: list
    closed: bool = False

    @property
    def proxy_url(self) -> str:
        host, port = self.proxy.server_address[:2]
        return f"http://{host}:{port}"

    @property
    def control_url(self) -> str:
        host, port = self.control.server_address[:2]
        return f"http://{host}:{port}"

    def shutdown(self) -> None:
        # 2回目以降は何もしない。先に停止要求を立てて、遅延や hang の待ちを終わらせる。
        if self.closed:
            return
        self.closed = True
        self.simulator.stopping.set()
        for server in (self.proxy, self.control):
            server.shutdown()
            server.server_close()
        for thread in self.threads:
            thread.join(SHUTDOWN_JOIN_SECONDS)


def start(
    simulator: LinkSimulator,
    upstream: Upstream,
    listen: tuple[str, int],
    control: tuple[str, int],
    *,
    upstream_timeout: float = UPSTREAM_TIMEOUT_SECONDS,
    warn: Callable[[str], None] | None = None,
) -> RunningSimulator:
    warn = warn or (lambda line: print(line, file=sys.stderr, flush=True))
    if control[0] != LOOPBACK:
        raise ConfigError("--control must bind to 127.0.0.1")
    if listen[0] != LOOPBACK:
        warn(f"WARNING: --listen {listen[0]} is reachable from other machines on the network")
    proxy_server = ThreadingHTTPServer(listen, make_proxy_handler(simulator, upstream, upstream_timeout))
    proxy_server.daemon_threads = True
    control_server = ThreadingHTTPServer(control, make_control_handler(simulator))
    control_server.daemon_threads = True
    threads = []
    for server in (proxy_server, control_server):
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True)
        thread.start()
        threads.append(thread)
    return RunningSimulator(simulator, proxy_server, control_server, threads)


def load_initial_config(preset: str | None, config_path: str | None) -> SimConfig:
    config = preset_config(preset or "clean")
    if config_path:
        try:
            with open(config_path, encoding="utf-8") as config_file:
                update = json.load(config_file)
        except (OSError, json.JSONDecodeError):
            raise ConfigError("--config could not be read as JSON") from None
        config = replace(config, **validate_update(update))
    return config


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Test-only HTTP relay that reproduces link faults (values are test examples, not measurements)."
    )
    parser.add_argument("--upstream", required=True, help="the only destination, e.g. https://example.invalid")
    parser.add_argument("--listen", default="127.0.0.1:8090")
    parser.add_argument("--control", default="127.0.0.1:8091")
    parser.add_argument("--seed", type=int)
    parser.add_argument("--config", help="JSON file with config values (applied on top of --preset)")
    parser.add_argument("--preset", choices=sorted(PRESETS), help="config template")
    args = parser.parse_args(argv)

    try:
        upstream = parse_upstream(args.upstream)
        listen = parse_host_port(args.listen, "--listen")
        control = parse_host_port(args.control, "--control")
        simulator = LinkSimulator(load_initial_config(args.preset, args.config), seed=args.seed)
        running = start(simulator, upstream, listen, control)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(
        f"link simulator: upstream={upstream.display} listen={running.proxy_url} control={running.control_url} "
        f"preset={args.preset or 'clean'} seed={args.seed}",
        flush=True,
    )
    print("NOTE: settings are test examples, not measured performance of any real link.", flush=True)
    try:
        while not simulator.stopping.wait(1.0):
            pass
    except KeyboardInterrupt:
        print("stopping...", flush=True)
    finally:
        running.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
