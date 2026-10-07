"""link_simulator のテスト。

上流には 127.0.0.1 で動くテスト用の小さなHTTPサーバーを使う。時間と乱数は注入し、実際には待たない。
鍵・本文・クエリはテスト専用のダミー値。
"""

import faulthandler
import http.client
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

import link_simulator as sim

GATEWAY_KEY = "dummy-gateway-key-for-link-sim"
# 1件のテストの上限時間(保険)。超えたら、全スレッドのスタックを出してプロセスを終了する。
TEST_TIME_LIMIT_SECONDS = 30
SECRET_QUERY = "token=dummy-query-secret"
SECRET_BODY = '{"packet": "dummy-body-secret"}'


class FakeClock:
    """注入用の時計。sleep は実際には待たず、時刻を進めて記録する。"""

    def __init__(self):
        self.now = 1000.0
        self.sleeps: list[float] = []
        self._lock = threading.Lock()

    def clock(self) -> float:
        with self._lock:
            return self.now

    def sleep(self, seconds: float) -> None:
        with self._lock:
            self.sleeps.append(seconds)
            self.now += max(seconds, 0.0)

    def advance(self, seconds: float) -> None:
        with self._lock:
            self.now += seconds


class Upstream:
    """テスト用の上流。responder(method, path, headers, body) -> (status, headers, body)。"""

    def __init__(self):
        self.requests: list[dict] = []
        self.responder = lambda method, path, headers, body: (201, {"Content-Type": "application/json"}, b'{"id":"EP-x"}')
        upstream = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"
            timeout = 10

            def _handle(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length) if length else b""
                upstream.requests.append(
                    {"method": self.command, "path": self.path, "headers": dict(self.headers.items()), "body": body}
                )
                status, headers, data = upstream.responder(self.command, self.path, self.headers, body)
                self.send_response(status)
                for name, value in headers.items():
                    self.send_header(name, value)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            do_GET = do_POST = do_PUT = do_DELETE = _handle

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        self.thread.start()

    @property
    def port(self) -> int:
        return self.server.server_address[1]

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(5)
        assert not self.thread.is_alive()


@pytest.fixture(autouse=True)
def test_time_limit():
    faulthandler.dump_traceback_later(TEST_TIME_LIMIT_SECONDS, exit=True, file=sys.stderr)
    yield
    faulthandler.cancel_dump_traceback_later()


def wait_until(predicate, timeout: float = 3.0) -> bool:
    """条件が満たされるまで、上限つきで待つ。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


@pytest.fixture
def upstream():
    server = Upstream()
    yield server
    server.close()


@pytest.fixture
def fake_clock():
    return FakeClock()


@pytest.fixture
def logs():
    return []


@pytest.fixture
def running(upstream, fake_clock, logs):
    instances = []

    def factory(config: sim.SimConfig | None = None, seed: int | None = 1, sleep=None, upstream_url=None):
        simulator = sim.LinkSimulator(
            config or sim.SimConfig(),
            seed=seed,
            clock=fake_clock.clock,
            sleep=sleep or fake_clock.sleep,
            log=logs.append,
        )
        instance = sim.start(
            simulator,
            sim.parse_upstream(upstream_url or upstream.url),
            ("127.0.0.1", 0),
            ("127.0.0.1", 0),
            upstream_timeout=5,
        )
        instances.append(instance)
        return instance

    yield factory
    for instance in instances:
        instance.shutdown()
        assert not any(thread.is_alive() for thread in instance.threads)


def proxy_request(instance, method="POST", path="/api/emergency-packets", body=None, headers=None, timeout=5.0):
    host, port = instance.proxy.server_address[:2]
    connection = http.client.HTTPConnection(host, port, timeout=timeout)
    try:
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        connection.close()


def control(instance, method, path, payload=None):
    host, port = instance.control.server_address[:2]
    connection = http.client.HTTPConnection(host, port, timeout=5)
    try:
        body = json.dumps(payload).encode() if payload is not None else None
        connection.request(method, path, body=body, headers={"Content-Type": "application/json"} if body else {})
        response = connection.getresponse()
        return response.status, json.loads(response.read() or b"{}")
    finally:
        connection.close()


# ---- 中継 ----


def test_relays_method_path_body_and_allowed_headers(running, upstream):
    upstream.responder = lambda m, p, h, b: (202, {"Content-Type": "application/json", "X-Upstream": "yes"}, b'{"ok":1}')
    instance = running()

    status, headers, body = proxy_request(
        instance,
        path=f"/api/emergency-packets?{SECRET_QUERY}",
        body=SECRET_BODY,
        headers={
            "Content-Type": "application/json",
            "X-Gateway-Key": GATEWAY_KEY,
            "Accept": "application/json",
            "Cookie": "session=should-not-be-forwarded",
            "X-Unlisted": "should-not-be-forwarded",
        },
    )

    assert (status, body) == (202, b'{"ok":1}')
    assert headers["X-Upstream"] == "yes"
    request = upstream.requests[0]
    assert request["method"] == "POST"
    assert request["path"] == f"/api/emergency-packets?{SECRET_QUERY}"
    assert request["body"] == SECRET_BODY.encode()
    assert request["headers"]["Content-Type"] == "application/json"
    assert request["headers"]["X-Gateway-Key"] == GATEWAY_KEY
    assert request["headers"]["Accept"] == "application/json"
    assert "Cookie" not in request["headers"] and "X-Unlisted" not in request["headers"]
    assert request["headers"]["Host"] == f"127.0.0.1:{upstream.port}"


@pytest.mark.parametrize("method", ["GET", "PUT", "DELETE"])
def test_relays_other_methods(running, upstream, method):
    instance = running()
    status, _, _ = proxy_request(instance, method=method, path="/health")
    assert status == 201
    assert (upstream.requests[0]["method"], upstream.requests[0]["path"]) == (method, "/health")


def test_upstream_base_path_is_prefixed(running, upstream):
    instance = running(upstream_url=upstream.url + "/base/")
    proxy_request(instance, path="/api/emergency-packets")
    assert upstream.requests[0]["path"] == "/base/api/emergency-packets"


def test_hop_by_hop_headers_are_not_forwarded(running, upstream):
    upstream.responder = lambda m, p, h, b: (200, {"Upgrade": "h2c", "Keep-Alive": "timeout=5", "X-Kept": "1"}, b"ok")
    instance = running()

    status, headers, _ = proxy_request(
        instance,
        headers={"Upgrade": "websocket", "TE": "trailers", "Keep-Alive": "timeout=5", "Proxy-Authorization": "x",
                 "Content-Type": "text/plain"},
        body="x",
    )

    assert status == 200
    forwarded = {name.lower() for name in upstream.requests[0]["headers"]}
    assert not forwarded & {"upgrade", "te", "keep-alive", "proxy-authorization"}
    assert "Upgrade" not in headers and "Keep-Alive" not in headers
    assert headers["X-Kept"] == "1"


def test_redirect_is_returned_not_followed(running, upstream):
    other = Upstream()
    try:
        upstream.responder = lambda m, p, h, b: (302, {"Location": other.url + "/elsewhere"}, b"")
        instance = running()
        status, headers, _ = proxy_request(instance, headers={"X-Gateway-Key": GATEWAY_KEY})
        assert status == 302
        assert headers["Location"] == other.url + "/elsewhere"
        assert other.requests == []
    finally:
        other.close()


def test_destination_is_fixed_to_upstream(running, upstream):
    other = Upstream()
    try:
        instance = running()
        host, port = instance.proxy.server_address[:2]
        connection = http.client.HTTPConnection(host, port, timeout=5)
        # リクエスト行に絶対URL、Host ヘッダーに別のホストを書く
        connection.putrequest("POST", f"{other.url}/stolen?x=1", skip_host=True)
        connection.putheader("Host", f"127.0.0.1:{other.port}")
        connection.putheader("X-Gateway-Key", GATEWAY_KEY)
        connection.putheader("Content-Length", "2")
        connection.endheaders(b"{}")
        response = connection.getresponse()
        response.read()
        connection.close()

        assert response.status == 201
        assert other.requests == []
        assert upstream.requests[0]["path"] == "/stolen?x=1"
        assert upstream.requests[0]["headers"]["Host"] == f"127.0.0.1:{upstream.port}"
    finally:
        other.close()


def test_body_size_limit(running, upstream):
    instance = running()
    # 本文を読まずに閉じると、OSが接続をリセットして413が届かないことがあった。繰り返して確認する。
    for _ in range(20):
        status, _, _ = proxy_request(instance, body=b"x" * (sim.MAX_BODY_BYTES + 1))
        assert status == 413
    assert upstream.requests == []
    status, _, _ = proxy_request(instance, body=b"x" * sim.MAX_BODY_BYTES)
    assert status == 201
    assert len(upstream.requests[0]["body"]) == sim.MAX_BODY_BYTES
    assert instance.simulator.stats()["too_large"] == 20


def test_upstream_unreachable_returns_502(running):
    closed = ThreadingHTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
    url = f"http://127.0.0.1:{closed.server_address[1]}"
    closed.server_close()
    instance = running(upstream_url=url)
    status, _, _ = proxy_request(instance)
    assert status == 502
    assert instance.simulator.stats()["upstream_error"] == 1


# ---- 遅延と帯域 ----


def test_delay_and_bandwidth_time_are_computed(running, upstream, fake_clock):
    upstream.responder = lambda m, p, h, b: (200, {}, b"r" * 500)
    instance = running(sim.SimConfig(delay_ms=500, bandwidth_kbps=8))

    proxy_request(instance, body=b"q" * 1000)

    # 遅延 0.5秒 + リクエスト本文 1000バイト / 8kbps = 1.0秒、応答本文 500バイト / 8kbps = 0.5秒
    assert fake_clock.sleeps == [pytest.approx(1.5), pytest.approx(0.5)]
    stats = instance.simulator.stats()
    assert stats["delayed"] == 1 and stats["forwarded"] == 1
    assert stats["recent_delay_ms_avg"] == 500.0 and stats["recent_delay_ms_max"] == 500.0


def test_unlimited_bandwidth_and_jitter_range():
    simulator = sim.LinkSimulator(sim.SimConfig(delay_ms=1000, jitter_ms=500), seed=7, log=lambda line: None)
    assert simulator.transfer_seconds(10_000) == 0.0
    delays = [simulator.plan().delay_seconds for _ in range(500)]
    assert all(0.5 <= delay <= 1.5 for delay in delays)
    assert min(delays) < 0.6 and max(delays) > 1.4
    clamped = sim.LinkSimulator(sim.SimConfig(delay_ms=100, jitter_ms=500), seed=7, log=lambda line: None)
    assert all(clamped.plan().delay_seconds >= 0 for _ in range(200))


# ---- 欠落と瞬断 ----


def test_drop_request_reset(running, upstream):
    instance = running(sim.SimConfig(drop_request_rate=1.0, drop_mode="reset"))
    with pytest.raises((ConnectionError, http.client.HTTPException)):
        proxy_request(instance)
    assert upstream.requests == []
    assert instance.simulator.stats()["dropped_request"] == 1


def test_drop_request_hang_causes_client_timeout(running, upstream, logs):
    instance = running(sim.SimConfig(drop_request_rate=1.0, drop_mode="hang", hang_seconds=30))
    with pytest.raises(TimeoutError):
        proxy_request(instance, timeout=0.3)
    # クライアントが切断したら、hang_seconds(30秒)を待たずに終わる
    assert wait_until(lambda: "event=hang_end reason=client_closed" in logs, timeout=3)
    assert upstream.requests == []
    assert instance.simulator.stats()["dropped_request"] == 1


def test_hang_ends_at_hang_seconds(running, upstream, logs):
    instance = running(sim.SimConfig(drop_request_rate=1.0, drop_mode="hang", hang_seconds=0.5))
    started = time.monotonic()
    with pytest.raises((ConnectionError, http.client.HTTPException)):
        proxy_request(instance, timeout=10)
    assert 0.4 <= time.monotonic() - started < 5
    assert "event=hang_end reason=timeout" in logs


def test_hang_ends_promptly_on_shutdown(running, upstream, logs):
    instance = running(sim.SimConfig(drop_request_rate=1.0, drop_mode="hang", hang_seconds=30))
    errors = []

    def client():
        try:
            proxy_request(instance, timeout=20)
        except Exception as exc:  # noqa: BLE001 - 切断されたことだけを確認する
            errors.append(exc)

    thread = threading.Thread(target=client, daemon=True)
    thread.start()
    assert wait_until(lambda: instance.simulator.stats()["dropped_request"] == 1)
    started = time.monotonic()
    instance.shutdown()
    assert time.monotonic() - started < 3
    assert wait_until(lambda: "event=hang_end reason=shutdown" in logs)
    thread.join(5)
    assert not thread.is_alive()
    assert errors


def test_drop_response_reaches_upstream_but_not_client(running, upstream):
    instance = running(sim.SimConfig(drop_response_rate=1.0))
    with pytest.raises((ConnectionError, http.client.HTTPException)):
        proxy_request(instance, body=SECRET_BODY, headers={"Content-Type": "application/json"})
    # 上流は受け取って処理した
    assert len(upstream.requests) == 1
    assert upstream.requests[0]["body"] == SECRET_BODY.encode()
    assert instance.simulator.stats()["dropped_response"] == 1


def test_down_for_seconds_recovers_automatically(running, upstream, fake_clock):
    instance = running()
    status, config = control(instance, "POST", "/sim/down?seconds=30")
    assert status == 200 and config["down"] is True and config["down_remaining_seconds"] == 30

    with pytest.raises((ConnectionError, http.client.HTTPException)):
        proxy_request(instance)
    fake_clock.advance(29)
    with pytest.raises((ConnectionError, http.client.HTTPException)):
        proxy_request(instance)
    fake_clock.advance(1)
    assert proxy_request(instance)[0] == 201

    assert control(instance, "GET", "/sim/config")[1]["down"] is False
    stats = instance.simulator.stats()
    assert stats["down_rejected"] == 2 and stats["forwarded"] == 1
    assert len(upstream.requests) == 1


def test_manual_down_and_up(running, upstream):
    instance = running()
    assert control(instance, "POST", "/sim/down")[1]["down_remaining_seconds"] is None
    with pytest.raises((ConnectionError, http.client.HTTPException)):
        proxy_request(instance)
    assert control(instance, "POST", "/sim/up")[1]["down"] is False
    assert proxy_request(instance)[0] == 201


def test_down_with_hang_mode(running, upstream, logs):
    instance = running(sim.SimConfig(down=True, drop_mode="hang", hang_seconds=30))
    with pytest.raises(TimeoutError):
        proxy_request(instance, timeout=0.3)
    assert wait_until(lambda: "event=hang_end reason=client_closed" in logs, timeout=3)
    assert upstream.requests == []


def test_default_sleep_is_interrupted_by_shutdown():
    simulator = sim.LinkSimulator(sim.SimConfig(), log=lambda line: None)
    threading.Timer(0.2, simulator.stopping.set).start()
    started = time.monotonic()
    simulator.sleep(30)
    assert time.monotonic() - started < 3


def test_outage_preset_starts_down_and_recovers(running, upstream, fake_clock):
    instance = running(sim.preset_config("outage-30s"))
    with pytest.raises((ConnectionError, http.client.HTTPException)):
        proxy_request(instance)
    fake_clock.advance(30)
    assert proxy_request(instance)[0] == 201


# ---- 設定と制御 ----


@pytest.mark.parametrize(
    "update",
    [
        {"drop_request_rate": 1.5},
        {"drop_response_rate": -0.1},
        {"delay_ms": -1},
        {"bandwidth_kbps": "fast"},
        {"drop_mode": "explode"},
        {"down": "yes"},
        {"hang_seconds": 99999},
        {"unknown_key": 1},
        {"jitter_ms": True},
    ],
)
def test_config_validation_rejects_out_of_range(running, update):
    instance = running()
    status, body = control(instance, "POST", "/sim/config", update)
    assert status == 400
    assert body["error"]
    assert control(instance, "GET", "/sim/config")[1]["drop_request_rate"] == 0.0


def test_partial_update_preset_reset_and_stats(running, upstream, fake_clock):
    instance = running(sim.SimConfig(delay_ms=100))
    status, config = control(instance, "POST", "/sim/config", {"drop_response_rate": 0.25})
    assert status == 200
    assert config["drop_response_rate"] == 0.25 and config["delay_ms"] == 100

    status, config = control(instance, "POST", "/sim/preset?name=slow-link")
    assert status == 200
    assert (config["bandwidth_kbps"], config["delay_ms"], config["jitter_ms"]) == (256, 500, 200)
    assert config["drop_response_rate"] == 0.0
    assert control(instance, "POST", "/sim/preset?name=unknown")[0] == 400

    control(instance, "POST", "/sim/config", {"drop_response_rate": 0})
    proxy_request(instance)
    stats = control(instance, "GET", "/sim/stats")[1]
    assert stats["forwarded"] == 1 and stats["delayed"] == 1

    status, config = control(instance, "POST", "/sim/reset")
    assert status == 200
    assert config["delay_ms"] == 100 and config["bandwidth_kbps"] == 0 and config["drop_response_rate"] == 0
    stats = control(instance, "GET", "/sim/stats")[1]
    assert all(stats[key] == 0 for key in ("forwarded", "dropped_request", "dropped_response", "down_rejected",
                                           "delayed"))
    assert stats["recent_delay_ms_avg"] is None


def test_config_change_applies_to_next_request(running, upstream):
    instance = running()
    assert proxy_request(instance)[0] == 201
    control(instance, "POST", "/sim/config", {"drop_request_rate": 1})
    with pytest.raises((ConnectionError, http.client.HTTPException)):
        proxy_request(instance)
    control(instance, "POST", "/sim/config", {"drop_request_rate": 0})
    assert proxy_request(instance)[0] == 201


def test_all_presets_are_valid():
    assert set(sim.PRESETS) == {"clean", "slow-link", "lossy-link", "very-poor-link", "outage-30s"}
    for name in sim.PRESETS:
        sim.preset_config(name)
    assert sim.preset_config("very-poor-link").drop_request_rate == 0.10
    assert sim.preset_config("lossy-link").drop_response_rate == 0.05


def test_control_must_bind_loopback(upstream, logs, capsys):
    simulator = sim.LinkSimulator(sim.SimConfig(), log=logs.append)
    with pytest.raises(sim.ConfigError, match="127.0.0.1"):
        sim.start(simulator, sim.parse_upstream(upstream.url), ("127.0.0.1", 0), ("0.0.0.0", 0))
    assert sim.main(["--upstream", upstream.url, "--listen", "127.0.0.1:0", "--control", "0.0.0.0:0"]) == 2
    assert "--control must bind to 127.0.0.1" in capsys.readouterr().err


def test_shutdown_is_idempotent_and_bounded(running):
    instance = running()
    started = time.monotonic()
    instance.shutdown()
    instance.shutdown()
    assert time.monotonic() - started < 3


def test_non_loopback_listen_warns(upstream, logs):
    warnings = []
    simulator = sim.LinkSimulator(sim.SimConfig(), log=logs.append)
    instance = sim.start(simulator, sim.parse_upstream(upstream.url), ("localhost", 0), ("127.0.0.1", 0),
                         warn=warnings.append)
    instance.shutdown()
    assert warnings and "reachable from other machines" in warnings[0]


def test_upstream_is_required_and_validated(capsys):
    with pytest.raises(SystemExit) as missing:
        sim.main(["--listen", "127.0.0.1:0"])
    assert missing.value.code == 2
    for url in ("ftp://example.invalid", "https://user:pw-secret@example.invalid", "https://example.invalid/?k=q-secret"):
        assert sim.main(["--upstream", url, "--listen", "127.0.0.1:0", "--control", "127.0.0.1:0"]) == 2
    err = capsys.readouterr().err
    assert "pw-secret" not in err and "q-secret" not in err


def test_config_file_is_applied_on_top_of_preset(tmp_path):
    path = tmp_path / "sim.json"
    path.write_text(json.dumps({"drop_request_rate": 0.2}), encoding="utf-8")
    config = sim.load_initial_config("slow-link", str(path))
    assert config.drop_request_rate == 0.2 and config.bandwidth_kbps == 256
    path.write_text(json.dumps({"drop_request_rate": 2}), encoding="utf-8")
    with pytest.raises(sim.ConfigError):
        sim.load_initial_config(None, str(path))


# ---- 再現性 ----


def _outcomes(seed: int) -> list[tuple]:
    simulator = sim.LinkSimulator(
        sim.SimConfig(delay_ms=1000, jitter_ms=500, drop_request_rate=0.3, drop_response_rate=0.3),
        seed=seed,
        log=lambda line: None,
    )
    return [(plan.outcome, round(plan.delay_seconds, 6), plan.drop_response)
            for plan in (simulator.plan() for _ in range(200))]


def test_same_seed_gives_same_results():
    assert _outcomes(42) == _outcomes(42)
    assert _outcomes(42) != _outcomes(43)
    outcomes = _outcomes(42)
    assert any(item[0] == sim.DROPPED_REQUEST for item in outcomes)
    assert any(item[2] for item in outcomes)


def test_reset_restarts_the_random_sequence(running, upstream):
    instance = running(sim.SimConfig(jitter_ms=100, delay_ms=200), seed=5)
    first = [instance.simulator.plan().delay_seconds for _ in range(5)]
    control(instance, "POST", "/sim/reset")
    assert [instance.simulator.plan().delay_seconds for _ in range(5)] == first


# ---- 秘密 ----


def test_logs_and_stats_do_not_contain_key_body_or_query(running, upstream, logs):
    instance = running(sim.SimConfig(delay_ms=10))
    headers = {"Content-Type": "application/json", "X-Gateway-Key": GATEWAY_KEY}
    proxy_request(instance, path=f"/api/emergency-packets?{SECRET_QUERY}", body=SECRET_BODY, headers=headers)
    control(instance, "POST", "/sim/config", {"drop_response_rate": 1})
    with pytest.raises((ConnectionError, http.client.HTTPException)):
        proxy_request(instance, path=f"/x?{SECRET_QUERY}", body=SECRET_BODY, headers=headers)
    control(instance, "POST", "/sim/config", {"drop_response_rate": 0, "drop_request_rate": 1})
    with pytest.raises((ConnectionError, http.client.HTTPException)):
        proxy_request(instance, path=f"/x?{SECRET_QUERY}", body=SECRET_BODY, headers=headers)

    texts = [
        "\n".join(logs),
        json.dumps(control(instance, "GET", "/sim/stats")[1]),
        json.dumps(control(instance, "GET", "/sim/config")[1]),
    ]
    for text in texts:
        for secret in (GATEWAY_KEY, "dummy-query-secret", "dummy-body-secret", "/api/emergency-packets"):
            assert secret not in text
    assert any(line.startswith("result=delayed delay_ms=10 upstream_status=201") for line in logs)
    assert any(line.startswith("result=dropped_response") for line in logs)
    assert any(line.startswith("result=dropped_request") for line in logs)
