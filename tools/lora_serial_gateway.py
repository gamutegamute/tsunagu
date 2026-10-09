"""T-Beam受信機のシリアル出力を、ローカルのTSUNAGU API(1つ)へ送るゲートウェイ。

- 受信した行のうち、Emergency Packet の形(v1: 区切り6個、v2: 区切り11個)のものだけをキューへ入れる
- キュー(SQLite)は、緊急度順 → hub_received_at 順 → id 順に送る
- 応答に応じて、削除・隔離・バックオフ・送信停止を行う(docs/lora-gateway-prep.md)
- HMACの検証はサーバーの役割なので、ここではしない。raw packet は改変しない

ログには、Packet の内容(特に v2 の最後の hmac 欄)と、Gateway Key を出さない。
"""

import argparse
import hashlib
import http.client
import json
import os
import random
import re
import sqlite3
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

ALLOWED_STATUSES = ("NORMAL", "WARNING", "ALERT", "CRITICAL")
# 許可された4つ以外の status は、最も低い優先度として扱う。
UNKNOWN_STATUS = "UNKNOWN"

# version: (区切りの数, 最大長, status の位置)
PACKET_SHAPES = {
    "v1": (6, 160, 5),
    "v2": (11, 131, 9),
}

REQUEST_TIMEOUT_SECONDS = 5
RETRY_INTERVAL_SECONDS = 5
BACKOFF_BASE_SECONDS = 5.0
BACKOFF_MAX_SECONDS = 300.0
# 同じ周回で 429・5xx がこの件数続いたら、その周回の送信を止める(落ちているサーバーに連打しない)。
MAX_CONSECUTIVE_SERVER_ERRORS = 3
# 送信停止中のログは、この間隔で間引く。
STOPPED_LOG_INTERVAL_SECONDS = 300
RESPONSE_SUMMARY_MAX_LENGTH = 200
RESPONSE_READ_LIMIT = 4096

# 応答に対する扱い
SENT = "SENT"
QUARANTINE = "QUARANTINE"
RETRY = "RETRY"
STOP = "STOP"


def log(message: str) -> None:
    print(message, flush=True)


def format_hub_time(epoch_seconds: float) -> str:
    """APIへ送る hub_received_at の形式(UTC、ミリ秒、末尾Z)。SQLiteの strftime('%Y-%m-%dT%H:%M:%fZ') と同じ形。"""
    moment = datetime.fromtimestamp(epoch_seconds, tz=timezone.utc)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


# ---- Packet の形 ----


def packet_shape_error(packet: str) -> str | None:
    """形が正しければ None、正しくなければ理由(ログ用の短いコード)を返す。内容は見ない。"""
    version = packet.split("|", 1)[0]
    shape = PACKET_SHAPES.get(version)
    if shape is None:
        return "unknown_version"
    delimiters, max_length, _status_index = shape
    if len(packet) > max_length:
        return "too_long"
    if any(not (0x20 <= ord(character) <= 0x7E) for character in packet):
        return "non_printable"
    if packet.count("|") != delimiters:
        return "delimiter_count"
    return None


def extract_status(packet: str) -> str:
    """status を、| で分けた位置から取り出す(v1は6番目、v2は10番目)。"""
    parts = packet.split("|")
    shape = PACKET_SHAPES.get(parts[0])
    if shape is None or len(parts) != shape[0] + 1:
        return UNKNOWN_STATUS
    status = parts[shape[2]]
    return status if status in ALLOWED_STATUSES else UNKNOWN_STATUS


def packet_hmac_field(packet: str) -> str | None:
    """v2 の最後の hmac 欄(ログ・要約から伏せるため)。"""
    if packet.startswith("v2|"):
        return packet.rsplit("|", 1)[-1]
    return None


def packet_key(packet: str) -> str:
    """重複判定のキー(raw packet の SHA-256)。キューの id と隔離テーブルの packet_hash に使う。"""
    return hashlib.sha256(packet.encode("utf-8")).hexdigest()


def packet_label(packet_id: str, packet: str, status: str | None = None) -> str:
    """ログ用の識別情報。Packetの内容(hmac欄を含む)は出さない。"""
    version = packet.split("|", 1)[0] if packet.split("|", 1)[0] in PACKET_SHAPES else "?"
    return f"id={packet_id[:12]} version={version} status={status or extract_status(packet)} length={len(packet)}"


# ---- キュー ----


@dataclass(frozen=True)
class QueuedPacket:
    id: str
    packet: str
    queued_at: float
    status: str | None
    hub_received_at: str
    attempts: int


class PacketQueue:
    # 既存のキューのファイルに足りない列だけを足す(データは壊さない)。
    _ADDED_COLUMNS = {
        "status": "TEXT",
        "hub_received_at": "TEXT",
        "attempts": "INTEGER NOT NULL DEFAULT 0",
        "next_attempt_at": "REAL NOT NULL DEFAULT 0",
    }

    def __init__(self, database_path: Path):
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(database_path)
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS pending_packets (
                id TEXT PRIMARY KEY,
                packet TEXT NOT NULL,
                queued_at REAL NOT NULL
            )
            """
        )
        existing = {row[1] for row in self.connection.execute("PRAGMA table_info(pending_packets)")}
        for column, definition in self._ADDED_COLUMNS.items():
            if column not in existing:
                self.connection.execute(f"ALTER TABLE pending_packets ADD COLUMN {column} {definition}")
        # 隔離した Packet は、再送しない。packet 列は署名つきの raw packet をそのまま保存する。
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS quarantined_packets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                packet TEXT NOT NULL,
                hub_received_at TEXT,
                reason_code TEXT NOT NULL,
                http_status INTEGER,
                response_summary TEXT,
                quarantined_at REAL NOT NULL,
                packet_hash TEXT
            )
            """
        )
        self.connection.commit()
        self._migrate_quarantine(database_path)

    def _migrate_quarantine(self, database_path: Path) -> None:
        """隔離テーブルに packet_hash と、その一意制約を足す。

        既存の行には packet_hash を埋め、同じ Packet の行が複数あれば、最も新しい行(id が最大)だけを残す。
        1つのトランザクションで行い、失敗したときは元に戻して(ファイルは変えずに)起動を止める。
        """
        connection = self.connection
        try:
            connection.execute("BEGIN IMMEDIATE")
            columns = {row[1] for row in connection.execute("PRAGMA table_info(quarantined_packets)")}
            if "packet_hash" not in columns:
                connection.execute("ALTER TABLE quarantined_packets ADD COLUMN packet_hash TEXT")
            missing = connection.execute(
                "SELECT id, packet FROM quarantined_packets WHERE packet_hash IS NULL"
            ).fetchall()
            connection.executemany(
                "UPDATE quarantined_packets SET packet_hash = ? WHERE id = ?",
                [(packet_key(packet), row_id) for row_id, packet in missing],
            )
            removed = connection.execute(
                """
                DELETE FROM quarantined_packets
                WHERE id NOT IN (SELECT max(id) FROM quarantined_packets GROUP BY packet_hash)
                """
            ).rowcount
            connection.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS quarantined_packets_packet_hash"
                " ON quarantined_packets (packet_hash)"
            )
            connection.commit()
        except sqlite3.Error as exc:
            connection.rollback()
            connection.close()
            raise SystemExit(
                f"could not add the unique constraint to quarantined_packets ({exc.__class__.__name__}: {exc}). "
                f"The queue file was not changed: {database_path}. "
                "Stop any other gateway using this file, back it up, and check it before restarting."
            ) from exc
        if removed:
            log(f"quarantine migration: removed {removed} duplicate rows (kept the newest row per packet)")

    def enqueue(self, packet: str, received_at: float) -> str | None:
        """キューへ入れて id を返す。同じ Packet がキューか隔離テーブルにあれば入れない(None)。"""
        packet_id = packet_key(packet)
        cursor = self.connection.execute(
            """
            INSERT OR IGNORE INTO pending_packets
                (id, packet, queued_at, status, hub_received_at, attempts, next_attempt_at)
            SELECT ?, ?, ?, ?, ?, 0, 0
            WHERE NOT EXISTS (SELECT 1 FROM quarantined_packets WHERE packet_hash = ?)
            """,
            (packet_id, packet, received_at, extract_status(packet), format_hub_time(received_at), packet_id),
        )
        self.connection.commit()
        return packet_id if cursor.rowcount else None

    def is_quarantined(self, packet_id: str) -> bool:
        return self.connection.execute(
            "SELECT 1 FROM quarantined_packets WHERE packet_hash = ? LIMIT 1", (packet_id,)
        ).fetchone() is not None

    def due(self, now: float) -> list[QueuedPacket]:
        """送ってよい行を、緊急度順 → hub_received_at 順 → id 順に返す。"""
        rows = self.connection.execute(
            """
            SELECT id, packet, queued_at, status,
                   coalesce(hub_received_at, strftime('%Y-%m-%dT%H:%M:%fZ', queued_at, 'unixepoch')),
                   attempts
            FROM pending_packets
            WHERE next_attempt_at <= ?
            ORDER BY CASE
                       WHEN status IS NOT NULL THEN
                         CASE status WHEN 'CRITICAL' THEN 0 WHEN 'ALERT' THEN 1 WHEN 'WARNING' THEN 2 ELSE 3 END
                       -- status を持たない既存の行だけ、従来の LIKE で判定する
                       WHEN packet LIKE '%|CRITICAL|%' THEN 0
                       WHEN packet LIKE '%|ALERT|%' THEN 1
                       WHEN packet LIKE '%|WARNING|%' THEN 2
                       ELSE 3
                     END,
                     coalesce(hub_received_at, strftime('%Y-%m-%dT%H:%M:%fZ', queued_at, 'unixepoch')),
                     id
            """,
            (now,),
        )
        return [QueuedPacket(*row) for row in rows]

    def has_due(self, now: float) -> bool:
        return self.connection.execute(
            "SELECT 1 FROM pending_packets WHERE next_attempt_at <= ? LIMIT 1", (now,)
        ).fetchone() is not None

    def remove(self, packet_id: str) -> None:
        self.connection.execute("DELETE FROM pending_packets WHERE id = ?", (packet_id,))
        self.connection.commit()

    def schedule_retry(self, packet_id: str, attempts: int, next_attempt_at: float) -> None:
        self.connection.execute(
            "UPDATE pending_packets SET attempts = ?, next_attempt_at = ? WHERE id = ?",
            (attempts, next_attempt_at, packet_id),
        )
        self.connection.commit()

    def quarantine(self, item: QueuedPacket, reason_code: str, http_status: int, summary: str, now: float) -> None:
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO quarantined_packets
                    (packet, hub_received_at, reason_code, http_status, response_summary, quarantined_at, packet_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (packet_hash) DO UPDATE SET
                    hub_received_at = excluded.hub_received_at,
                    reason_code = excluded.reason_code,
                    http_status = excluded.http_status,
                    response_summary = excluded.response_summary,
                    quarantined_at = excluded.quarantined_at
                """,
                (item.packet, item.hub_received_at, reason_code, http_status, summary, now, packet_key(item.packet)),
            )
            self.connection.execute("DELETE FROM pending_packets WHERE id = ?", (item.id,))

    def count(self) -> int:
        return self.connection.execute("SELECT count(*) FROM pending_packets").fetchone()[0]

    def quarantined_count(self) -> int:
        return self.connection.execute("SELECT count(*) FROM quarantined_packets").fetchone()[0]


# ---- 送信 ----


class _NoRedirectHandler(HTTPRedirectHandler):
    # リダイレクトは追わない。3xx はそのまま HTTPError として受け取り、設定異常として扱う。
    def redirect_request(self, *args, **kwargs):
        return None


@dataclass(frozen=True)
class ApiResponse:
    status: int
    body: bytes


class ApiSender:
    def __init__(self, api_url: str, api_key: str, timeout: float = REQUEST_TIMEOUT_SECONDS):
        self.api_url = api_url
        self.api_key = api_key
        self.timeout = timeout
        self._opener = build_opener(_NoRedirectHandler())

    def __repr__(self) -> str:
        return f"ApiSender(api_url={self.api_url!r})"

    def post(self, packet: str, hub_received_at: str) -> ApiResponse:
        """APIの形(raw packet と hub_received_at)で送る。通信できなかったときは例外(OSError など)。"""
        body = json.dumps({"packet": packet, "hub_received_at": hub_received_at}).encode("utf-8")
        request = Request(
            self.api_url,
            data=body,
            headers={"Content-Type": "application/json", "X-Gateway-Key": self.api_key},
            method="POST",
        )
        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                return ApiResponse(response.status, response.read(RESPONSE_READ_LIMIT))
        except HTTPError as exc:
            # サーバーは応答した(4xx・5xx・3xx)。本文を読んで分類する。
            try:
                error_body = exc.read(RESPONSE_READ_LIMIT)
            except OSError:
                error_body = b""
            finally:
                exc.close()
            return ApiResponse(exc.code, error_body)


CONNECTION_ERRORS = (URLError, TimeoutError, ConnectionError, OSError, http.client.HTTPException)


def response_error_code(body: bytes) -> str | None:
    """APIのエラーコード(detail.code)を取り出す。"""
    try:
        parsed = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    detail = parsed.get("detail") if isinstance(parsed, dict) else None
    code = detail.get("code") if isinstance(detail, dict) else None
    if isinstance(code, str) and re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", code):
        return code
    return None


def summarize_response(body: bytes, packet: str, api_key: str) -> str:
    """隔離テーブル用の応答の要約。長さを制限し、鍵と hmac(32桁の16進)を含めない。"""
    text = ""
    try:
        parsed = json.loads(body.decode("utf-8"))
        detail = parsed.get("detail") if isinstance(parsed, dict) else None
        if isinstance(detail, dict):
            text = " ".join(str(detail.get(key, "")) for key in ("code", "error", "message") if detail.get(key))
        elif isinstance(detail, str):
            text = detail
        elif isinstance(detail, list):
            text = "validation error"
    except (UnicodeDecodeError, json.JSONDecodeError):
        text = body.decode("utf-8", errors="replace")
    secrets = [value for value in (api_key, packet_hmac_field(packet)) if value]
    for secret in secrets:
        text = text.replace(secret, "<redacted>")
    text = re.sub(r"[0-9a-fA-F]{32,}", "<redacted>", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:RESPONSE_SUMMARY_MAX_LENGTH]


def classify_response(status: int, body: bytes) -> tuple[str, str]:
    code = response_error_code(body)
    if 200 <= status < 300:
        return SENT, ""
    if status in (400, 422):
        return QUARANTINE, code or f"HTTP_{status}"
    if status == 403 and code == "PACKET_AUTH_FAILED":
        # この Packet だけの問題。後続は送る。
        return QUARANTINE, "PACKET_AUTH_FAILED"
    if status == 409:
        return QUARANTINE, code or f"HTTP_{status}"
    if status == 429 or 500 <= status < 600:
        return RETRY, f"HTTP_{status}"
    # 401、403(PACKET_AUTH_FAILED 以外)、3xx、その他の想定外の応答は、設定異常として送信を止める。
    return STOP, f"HTTP_{status}"


def backoff_seconds(attempts: int, rng: random.Random) -> float:
    """5秒から倍々で上限5分。ジッタは、その半分から全体の間でばらつかせる。"""
    ceiling = min(BACKOFF_MAX_SECONDS, BACKOFF_BASE_SECONDS * (2 ** min(max(attempts - 1, 0), 20)))
    return ceiling / 2 + rng.uniform(0, ceiling / 2)


@dataclass
class FlushResult:
    sent: int = 0
    quarantined: int = 0
    retried: int = 0
    stopped: bool = False
    interrupted: str | None = None
    attempted_ids: list[str] = field(default_factory=list)


class Gateway:
    def __init__(self, queue: PacketQueue, sender: ApiSender, rng: random.Random | None = None):
        self.queue = queue
        self.sender = sender
        self.rng = rng or random.Random()
        # 設定異常で止めた理由。再開は再起動のときだけ(メモリ上にだけ持つ)。
        self.stopped_reason: str | None = None
        self._last_stopped_log: float | None = None

    def accept_line(self, line: str, now: float | None = None) -> str | None:
        """シリアル(または標準入力)の1行を受け取り、形が正しければキューへ入れて送る。"""
        now = time.time() if now is None else now
        packet = line.rstrip("\r\n")
        if not packet:
            return None
        reason = packet_shape_error(packet)
        if reason is not None:
            # 内容(hmac欄を含む)は出さない。
            log(f"discarded: length={len(packet)} reason={reason}")
            return None
        packet_id = self.queue.enqueue(packet, now)
        if packet_id is None:
            existing_id = packet_key(packet)
            if self.queue.is_quarantined(existing_id):
                # 隔離済みの Packet の再受信。再送しない(再投入は docs/lora-gateway-prep.md の手順で)。
                log(f"already quarantined (not requeued): {packet_label(existing_id, packet)}")
            else:
                log(f"already queued: {packet_label(existing_id, packet)}")
        else:
            log(f"queued: {packet_label(packet_id, packet)}")
        self.flush(now)
        return packet_id

    def _log_stopped(self, now: float) -> None:
        if self._last_stopped_log is None or now - self._last_stopped_log >= STOPPED_LOG_INTERVAL_SECONDS:
            log(
                f"sending is STOPPED (configuration error: {self.stopped_reason}). "
                f"queued={self.queue.count()} packets are kept and serial receiving continues. "
                "Fix the API URL / TSUNAGU_GATEWAY_API_KEY, then restart the gateway."
            )
            self._last_stopped_log = now

    def flush(self, now: float | None = None) -> FlushResult:
        now = time.time() if now is None else now
        result = FlushResult()
        if self.stopped_reason is not None:
            # 停止中は送信を試みない。
            result.stopped = True
            self._log_stopped(now)
            return result

        consecutive_server_errors = 0
        for item in self.queue.due(now):
            result.attempted_ids.append(item.id)
            label = packet_label(item.id, item.packet, item.status)
            try:
                response = self.sender.post(item.packet, item.hub_received_at)
            except CONNECTION_ERRORS as exc:
                # APIに届かない。後続も同じなので、この周回は止めて、次の周回で再開する。
                log(f"api unreachable ({exc.__class__.__name__}); keeping {self.queue.count()} queued")
                result.interrupted = "connection"
                return result

            action, reason_code = classify_response(response.status, response.body)
            if action == SENT:
                self.queue.remove(item.id)
                result.sent += 1
                consecutive_server_errors = 0
                log(f"posted: {label} http={response.status}")
            elif action == QUARANTINE:
                summary = summarize_response(response.body, item.packet, self.sender.api_key)
                self.queue.quarantine(item, reason_code, response.status, summary, now)
                result.quarantined += 1
                consecutive_server_errors = 0
                log(f"quarantined: {label} http={response.status} reason={reason_code} (not retried)")
            elif action == RETRY:
                attempts = item.attempts + 1
                delay = backoff_seconds(attempts, self.rng)
                self.queue.schedule_retry(item.id, attempts, now + delay)
                result.retried += 1
                consecutive_server_errors += 1
                log(f"retry later: {label} http={response.status} attempts={attempts} in={delay:.1f}s")
                if consecutive_server_errors >= MAX_CONSECUTIVE_SERVER_ERRORS:
                    log(f"{consecutive_server_errors} server errors in a row; pausing until the next cycle")
                    result.interrupted = "server_errors"
                    return result
            else:
                self.stopped_reason = f"{reason_code} from {self.sender.api_url}"
                result.stopped = True
                self._log_stopped(now)
                return result
        return result


# ---- 実行 ----


def run_stdin(gateway: Gateway) -> None:
    gateway.flush()
    for line in sys.stdin:
        gateway.accept_line(line)


def run_serial(gateway: Gateway, port: str, baud: int) -> None:
    try:
        import serial
    except ImportError as exc:
        raise SystemExit("pyserial is required. Install it with: python -m pip install pyserial") from exc

    while True:
        try:
            log(f"connecting: {port} ({baud} baud)")
            with serial.Serial(port, baud, timeout=1) as serial_port:
                log(f"connected: {port}")
                gateway.flush()
                last_retry = time.monotonic()
                while True:
                    # 不正なバイトは置換文字にして、形の判定で捨てる(黙って取り除くと内容が変わるため)。
                    line = serial_port.readline().decode("utf-8", errors="replace")
                    if line.strip():
                        gateway.accept_line(line)
                    elif time.monotonic() - last_retry >= RETRY_INTERVAL_SECONDS:
                        if gateway.stopped_reason is not None or gateway.queue.has_due(time.time()):
                            gateway.flush()
                        last_retry = time.monotonic()
        except serial.SerialException as exc:
            log(f"serial disconnected: {exc.__class__.__name__}; retrying in 3 seconds")
            time.sleep(3)


def _environment_value(new_name: str, legacy_name: str, default: str = "") -> str:
    return os.getenv(new_name) or os.getenv(legacy_name) or default


def _default_queue_path() -> Path:
    configured = _environment_value("TSUNAGU_QUEUE_DB", "SHELTEROS_QUEUE_DB")
    if configured:
        return Path(configured)
    legacy_path = Path(".shelteros/lora_gateway_queue.db")
    new_path = Path(".tsunagu/lora_gateway_queue.db")
    return legacy_path if legacy_path.exists() and not new_path.exists() else new_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Forward T-Beam Emergency Packets to the local TSUNAGU API.")
    parser.add_argument(
        "--api-url",
        default=_environment_value(
            "TSUNAGU_API_URL",
            "SHELTEROS_API_URL",
            "http://localhost:8000/api/emergency-packets",
        ),
    )
    parser.add_argument("--port", help="Windows COM port such as COM3. If omitted, read from stdin.")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument(
        "--queue-db",
        type=Path,
        default=_default_queue_path(),
    )
    args = parser.parse_args()

    api_key = _environment_value("TSUNAGU_GATEWAY_API_KEY", "SHELTEROS_GATEWAY_API_KEY")
    if not api_key:
        raise SystemExit("TSUNAGU_GATEWAY_API_KEY is required")

    queue = PacketQueue(args.queue_db)
    log(f"queue: {args.queue_db} pending={queue.count()} quarantined={queue.quarantined_count()}")
    gateway = Gateway(queue, ApiSender(args.api_url, api_key))
    if args.port:
        run_serial(gateway, args.port, args.baud)
    else:
        run_stdin(gateway)


if __name__ == "__main__":
    main()
