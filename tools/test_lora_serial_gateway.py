"""lora_serial_gateway のテスト。

実際のAPIは使わず、127.0.0.1 で動くテスト用の小さなHTTPサーバーへ送る。
Gateway Key と hmac はテスト専用のダミー値。
"""

import json
import random
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

import lora_serial_gateway as gateway

API_KEY = "dummy-gateway-key-for-tests"
HMAC = "0123456789abcdef0123456789abcdef"  # ダミーの hmac 欄
NOW = 1_800_000_000.0

NORMAL_V1 = "v1|AIT001|21:02|170|30|NORMAL|NONE"
WARNING_V1 = "v1|AIT004|21:07|150|15|WARNING|REQ_WATER"
ALERT_V1 = "v1|AIT003|21:06|120|10|ALERT|REQ_MEDICAL"
CRITICAL_V1 = "v1|AIT002|21:05|90|5|CRITICAL|REQ_RESCUE"


def v2_packet(status: str = "WARNING", sequence: str = "0000002A", shelter: str = "AIT001",
              hmac: str = HMAC) -> str:
    return f"v2|TB001|01|A1B2C3D4E5F60718|{sequence}|1791234567|{shelter}|170|18|{status}|REQ_WATER|{hmac}"


class FakeApi:
    """テスト用のHTTPサーバー。responder(packet) -> (status, body, headers) で応答を決める。"""

    def __init__(self):
        self.requests: list[dict] = []
        self.responder = lambda body: (201, {"id": "EP-x"}, {})
        api = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(length))
                api.requests.append({"path": self.path, "body": body, "headers": dict(self.headers)})
                status, payload, headers = api.responder(body)
                data = json.dumps(payload).encode("utf-8")
                self.send_response(status)
                for name, value in headers.items():
                    self.send_header(name, value)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}/api/emergency-packets"

    @property
    def packets(self) -> list[str]:
        return [request["body"]["packet"] for request in self.requests]

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def api():
    server = FakeApi()
    yield server
    server.close()


def make_gateway(tmp_path, api_url: str, seed: int = 0) -> gateway.Gateway:
    queue = gateway.PacketQueue(tmp_path / "queue.db")
    return gateway.Gateway(queue, gateway.ApiSender(api_url, API_KEY, timeout=2), rng=random.Random(seed))


def enqueue_all(gw: gateway.Gateway, packets: list[str], start: float = NOW) -> None:
    for offset, packet in enumerate(packets):
        assert gw.queue.enqueue(packet, start + offset) is not None


def quarantined_rows(gw: gateway.Gateway) -> list[tuple]:
    return list(gw.queue.connection.execute(
        "SELECT packet, hub_received_at, reason_code, http_status, response_summary FROM quarantined_packets ORDER BY id"
    ))


def unused_url() -> str:
    server = ThreadingHTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
    port = server.server_address[1]
    server.server_close()
    return f"http://127.0.0.1:{port}/api/emergency-packets"


# ---- 形の判定 ----


@pytest.mark.parametrize(
    ("packet", "reason"),
    [
        (NORMAL_V1, None),
        (v2_packet(), None),
        ("v1|AIT001|21:02|170|30|NORMAL", "delimiter_count"),
        ("v1|AIT001|21:02|170|30|NORMAL|NONE|X", "delimiter_count"),
        (v2_packet() + "|extra", "delimiter_count"),
        (v2_packet().rsplit("|", 1)[0], "delimiter_count"),
        ("v3|a|b|c|d|e|f", "unknown_version"),
        ("hello world", "unknown_version"),
        ("v2|" + "A" * 120 + "|" * 11, "too_long"),
        ("v1|" + "A" * 160 + "|1|2|3|4|5", "too_long"),
        ("v1|AIT001|21:02|170|30|NORMAL|NONÉ", "non_printable"),
        ("v1|AIT001|21:02|170|30|NORMAL|NO\tE", "non_printable"),
    ],
)
def test_packet_shape(packet, reason):
    assert gateway.packet_shape_error(packet) == reason


def test_malformed_lines_are_discarded_without_content(tmp_path, api, capsys):
    gw = make_gateway(tmp_path, api.url)
    secret_line = "v2|TB001|01|A1B2C3D4E5F60718|0000002A|1791234567|AIT001|170|18|WARNING|" + HMAC  # 区切り10個

    assert gw.accept_line(secret_line + "\n", now=NOW) is None
    assert gw.accept_line("garbage\r\n", now=NOW) is None

    out = capsys.readouterr().out
    assert f"discarded: length={len(secret_line)} reason=delimiter_count" in out
    assert "discarded: length=7 reason=unknown_version" in out
    assert HMAC not in out and "A1B2C3D4E5F60718" not in out and "garbage" not in out
    assert gw.queue.count() == 0
    assert api.requests == []


def test_status_is_taken_from_its_field():
    assert gateway.extract_status(CRITICAL_V1) == "CRITICAL"
    assert gateway.extract_status(v2_packet("ALERT")) == "ALERT"
    # 避難所コードが CRITICAL でも、status の欄で判定する
    assert gateway.extract_status("v1|CRITICAL|21:02|1|1|NORMAL|NONE") == "NORMAL"
    assert gateway.extract_status(v2_packet("NORMAL", shelter="CRITICAL")) == "NORMAL"
    assert gateway.extract_status("v1|AIT001|21:02|1|1|URGENT|NONE") == "UNKNOWN"


# ---- 送信と順序 ----


def test_request_carries_raw_packet_hub_time_and_key(tmp_path, api):
    gw = make_gateway(tmp_path, api.url)
    packet = v2_packet()

    gw.accept_line(packet + "\r\n", now=NOW)

    assert gw.queue.count() == 0
    request = api.requests[0]
    assert request["path"] == "/api/emergency-packets"
    assert request["body"] == {"packet": packet, "hub_received_at": gateway.format_hub_time(NOW)}
    assert request["body"]["hub_received_at"] == "2027-01-15T08:00:00.000Z"
    assert request["headers"]["X-Gateway-Key"] == API_KEY


def test_mixed_v1_v2_priority_and_hub_time_order(tmp_path, api):
    gw = make_gateway(tmp_path, api.url)
    critical_shelter_normal = v2_packet("NORMAL", sequence="00000001", shelter="CRITICAL")
    later_critical_v2 = v2_packet("CRITICAL", sequence="00000002")
    enqueue_all(gw, [
        NORMAL_V1,               # NOW+0
        critical_shelter_normal, # NOW+1 避難所コードが CRITICAL の NORMAL
        CRITICAL_V1,             # NOW+2
        WARNING_V1,              # NOW+3
        later_critical_v2,       # NOW+4
        v2_packet("ALERT", sequence="00000003"),  # NOW+5
        ALERT_V1,                # NOW+6
    ])

    gw.flush(NOW + 10)

    assert api.packets == [
        CRITICAL_V1,
        later_critical_v2,
        v2_packet("ALERT", sequence="00000003"),
        ALERT_V1,
        WARNING_V1,
        NORMAL_V1,
        critical_shelter_normal,
    ]


# ---- 応答の分類 ----


def _respond(status, payload=None, headers=None):
    return lambda body: (status, payload if payload is not None else {}, headers or {})


@pytest.mark.parametrize(
    ("status", "payload", "reason_code"),
    [
        (400, {"detail": {"error": "Invalid LoRa packet format", "code": "PACKET_FORMAT_INVALID"}},
         "PACKET_FORMAT_INVALID"),
        (422, {"detail": [{"loc": ["body", "packet"], "msg": "too long"}]}, "HTTP_422"),
        (403, {"detail": {"error": "Emergency Packet authentication failed", "code": "PACKET_AUTH_FAILED"}},
         "PACKET_AUTH_FAILED"),
        (409, {"detail": {"code": "PACKET_DUPLICATE_CONFLICT", "packet_id": "EP-1"}}, "PACKET_DUPLICATE_CONFLICT"),
    ],
    ids=["400", "422", "403-auth", "409"],
)
def test_rejected_packet_is_quarantined_and_following_packets_are_sent(tmp_path, api, status, payload, reason_code):
    gw = make_gateway(tmp_path, api.url)
    bad = v2_packet("CRITICAL", sequence="00000001")
    good = v2_packet("NORMAL", sequence="00000002")
    enqueue_all(gw, [bad, good])
    api.responder = lambda body: (status, payload, {}) if body["packet"] == bad else (201, {"id": "EP-x"}, {})

    result = gw.flush(NOW + 1)

    assert api.packets == [bad, good]
    assert result.quarantined == 1 and result.sent == 1 and not result.stopped
    assert gw.queue.count() == 0
    rows = quarantined_rows(gw)
    assert [(row[0], row[2], row[3]) for row in rows] == [(bad, reason_code, status)]
    assert rows[0][1] == gateway.format_hub_time(NOW)
    # 隔離した Packet は再送しない(4xx が5秒ごとに再送され続けない)
    for later in (6, 11, 600):
        gw.flush(NOW + later)
    assert api.packets == [bad, good]


@pytest.mark.parametrize(
    ("status", "payload", "headers"),
    [
        (401, {"detail": "Invalid gateway API key"}, {}),
        (403, {"detail": "Headquarters role is required"}, {}),
        (302, {}, {"Location": "https://other.invalid/api/emergency-packets"}),
        (404, {"detail": "Not Found"}, {}),
        (405, {"detail": "Method Not Allowed"}, {}),
    ],
    ids=["401", "403-other", "302", "404", "405"],
)
def test_configuration_error_stops_sending_but_keeps_queue(tmp_path, api, capsys, status, payload, headers):
    gw = make_gateway(tmp_path, api.url)
    enqueue_all(gw, [CRITICAL_V1, NORMAL_V1])
    api.responder = _respond(status, payload, headers)

    result = gw.flush(NOW + 1)

    assert result.stopped
    assert api.packets == [CRITICAL_V1]  # 後続は送らない
    assert gw.queue.count() == 2  # キューは保持
    assert quarantined_rows(gw) == []
    assert gw.stopped_reason.startswith(f"HTTP_{status}")
    out = capsys.readouterr().out
    assert f"sending is STOPPED (configuration error: HTTP_{status}" in out

    # 停止中も受信とキューへの保存は続け、送信は試みない
    api.responder = _respond(201, {"id": "EP-x"})
    gw.accept_line(WARNING_V1, now=NOW + 2)
    gw.flush(NOW + 3)
    gw.flush(NOW + 400)
    assert gw.queue.count() == 3
    assert api.packets == [CRITICAL_V1]
    out = capsys.readouterr().out
    # 停止のログは間引く(NOW+2 と NOW+3 は出さず、5分後に1回)
    assert out.count("sending is STOPPED") == 1


def test_redirect_is_not_followed(tmp_path, api):
    other = FakeApi()
    try:
        api.responder = _respond(307, {}, {"Location": other.url})
        gw = make_gateway(tmp_path, api.url)
        gw.accept_line(CRITICAL_V1, now=NOW)
        assert other.requests == []
        assert gw.stopped_reason.startswith("HTTP_307")
    finally:
        other.close()


@pytest.mark.parametrize("status", [429, 500, 503])
def test_server_error_backs_off_and_moves_to_next_packet(tmp_path, api, status):
    gw = make_gateway(tmp_path, api.url)
    enqueue_all(gw, [CRITICAL_V1, NORMAL_V1])
    api.responder = lambda body: (status, {}, {}) if body["packet"] == CRITICAL_V1 else (201, {"id": "EP-x"}, {})

    result = gw.flush(NOW + 1)

    assert api.packets == [CRITICAL_V1, NORMAL_V1]
    assert result.retried == 1 and result.sent == 1
    row = gw.queue.connection.execute(
        "SELECT attempts, next_attempt_at FROM pending_packets WHERE packet = ?", (CRITICAL_V1,)
    ).fetchone()
    assert row[0] == 1
    assert NOW + 1 + 2.5 <= row[1] <= NOW + 1 + 5

    gw.flush(NOW + 2)  # バックオフ中は送らない
    assert len(api.requests) == 2
    api.responder = _respond(201, {"id": "EP-x"})
    gw.flush(row[1])
    assert api.packets[-1] == CRITICAL_V1
    assert gw.queue.count() == 0


def test_backoff_grows_exponentially_with_cap():
    rng = random.Random(3)
    for attempts, ceiling in [(1, 5), (2, 10), (3, 20), (4, 40), (5, 80), (6, 160), (7, 300), (12, 300)]:
        for _ in range(20):
            delay = gateway.backoff_seconds(attempts, rng)
            assert ceiling / 2 <= delay <= ceiling


def test_backoff_time_increases_on_repeated_failures(tmp_path, api):
    gw = make_gateway(tmp_path, api.url)
    enqueue_all(gw, [CRITICAL_V1])
    api.responder = _respond(503)
    now = NOW + 1
    for attempts, ceiling in [(1, 5), (2, 10), (3, 20)]:
        gw.flush(now)
        next_attempt = gw.queue.connection.execute(
            "SELECT next_attempt_at FROM pending_packets"
        ).fetchone()[0]
        assert now + ceiling / 2 <= next_attempt <= now + ceiling
        now = next_attempt
    assert len(api.requests) == 3


def test_three_consecutive_server_errors_end_the_cycle(tmp_path, api, capsys):
    gw = make_gateway(tmp_path, api.url)
    packets = [v2_packet("CRITICAL", sequence=f"0000000{i}") for i in range(1, 6)]
    enqueue_all(gw, packets)
    api.responder = _respond(503)

    result = gw.flush(NOW + 10)

    assert result.interrupted == "server_errors"
    assert len(api.requests) == 3
    assert "3 server errors in a row" in capsys.readouterr().out


def test_server_error_count_resets_after_success(tmp_path, api):
    gw = make_gateway(tmp_path, api.url)
    packets = [v2_packet("CRITICAL", sequence=f"0000000{i}") for i in range(1, 6)]
    enqueue_all(gw, packets)
    outcomes = iter([503, 503, 201, 503, 503])
    api.responder = lambda body: (next(outcomes), {}, {})

    result = gw.flush(NOW + 10)

    assert result.interrupted is None
    assert len(api.requests) == 5


def test_connection_error_ends_the_cycle_and_keeps_queue(tmp_path):
    gw = make_gateway(tmp_path, unused_url())
    enqueue_all(gw, [CRITICAL_V1, NORMAL_V1])

    result = gw.flush(NOW + 1)

    assert result.interrupted == "connection"
    assert result.attempted_ids == [gw.queue.due(NOW + 1)[0].id]  # 1件目で止まる
    assert gw.queue.count() == 2
    # バックオフは付けない(次の周回で再開する)
    assert {row[0] for row in gw.queue.connection.execute("SELECT next_attempt_at FROM pending_packets")} == {0}


def test_timeout_ends_the_cycle(tmp_path):
    import socket

    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)  # 接続は受けるが、応答しない
    try:
        url = f"http://127.0.0.1:{listener.getsockname()[1]}/api/emergency-packets"
        queue = gateway.PacketQueue(tmp_path / "queue.db")
        gw = gateway.Gateway(queue, gateway.ApiSender(url, API_KEY, timeout=0.3), rng=random.Random(0))
        enqueue_all(gw, [CRITICAL_V1, NORMAL_V1])
        result = gw.flush(NOW + 1)
        assert result.interrupted == "connection"
        assert len(result.attempted_ids) == 1
        assert gw.queue.count() == 2
    finally:
        listener.close()


# ---- 永続化と移行 ----


def test_queue_and_quarantine_survive_restart(tmp_path, api):
    gw = make_gateway(tmp_path, api.url)
    enqueue_all(gw, [CRITICAL_V1, NORMAL_V1])
    api.responder = lambda body: (
        (400, {"detail": {"code": "PACKET_FORMAT_INVALID"}}, {}) if body["packet"] == CRITICAL_V1 else (503, {}, {})
    )
    gw.flush(NOW + 1)
    gw.queue.connection.close()

    restarted = make_gateway(tmp_path, api.url)
    assert restarted.queue.count() == 1
    assert restarted.queue.quarantined_count() == 1
    assert quarantined_rows(restarted)[0][0] == CRITICAL_V1
    row = restarted.queue.connection.execute("SELECT packet, attempts FROM pending_packets").fetchone()
    assert row == (NORMAL_V1, 1)


def test_legacy_queue_file_is_migrated_without_data_loss(tmp_path, api):
    path = tmp_path / "queue.db"
    legacy = sqlite3.connect(path)
    legacy.execute("CREATE TABLE pending_packets (id TEXT PRIMARY KEY, packet TEXT NOT NULL, queued_at REAL NOT NULL)")
    legacy.executemany(
        "INSERT INTO pending_packets (id, packet, queued_at) VALUES (?, ?, ?)",
        [("old-normal", NORMAL_V1, NOW), ("old-critical", CRITICAL_V1, NOW + 5.25)],
    )
    legacy.commit()
    legacy.close()

    queue = gateway.PacketQueue(path)
    columns = {row[1] for row in queue.connection.execute("PRAGMA table_info(pending_packets)")}
    assert {"status", "hub_received_at", "attempts", "next_attempt_at"} <= columns
    assert queue.count() == 2
    # 2回目の起動でも壊れない
    queue.connection.close()
    queue = gateway.PacketQueue(path)

    gw = gateway.Gateway(queue, gateway.ApiSender(api.url, API_KEY, timeout=2), rng=random.Random(0))
    gw.queue.enqueue(WARNING_V1, NOW + 1)
    gw.flush(NOW + 10)

    # status の無い古い行は LIKE で判定し、hub_received_at の代わりに queued_at を使う
    assert api.packets == [CRITICAL_V1, WARNING_V1, NORMAL_V1]
    sent_times = {request["body"]["packet"]: request["body"]["hub_received_at"] for request in api.requests}
    assert sent_times[NORMAL_V1] == gateway.format_hub_time(NOW)
    assert sent_times[CRITICAL_V1] == gateway.format_hub_time(NOW + 5.25)


# ---- 秘密 ----


def test_key_and_hmac_do_not_leak(tmp_path, api, capsys):
    gw = make_gateway(tmp_path, api.url)
    auth_failed = v2_packet("CRITICAL", sequence="00000001")
    conflict = v2_packet("ALERT", sequence="00000002")
    ok = v2_packet("WARNING", sequence="00000003")
    enqueue_all(gw, [auth_failed, conflict, ok])

    def responder(body):
        if body["packet"] == auth_failed:
            # 応答に鍵や hmac が混ざっていても、要約に残さない
            return 403, {"detail": {"code": "PACKET_AUTH_FAILED", "error": f"bad {HMAC} {API_KEY}"}}, {}
        if body["packet"] == conflict:
            return 409, {"detail": {"code": "PACKET_DUPLICATE_CONFLICT", "message": "x" * 1000}}, {}
        return 201, {"id": "EP-x"}, {}

    api.responder = responder
    gw.flush(NOW + 1)
    gw.accept_line(v2_packet("NORMAL", sequence="00000004", hmac="f" * 32), now=NOW + 2)
    api.responder = _respond(401, {"detail": "Invalid gateway API key"})
    gw.accept_line(v2_packet("NORMAL", sequence="00000005", hmac="e" * 32), now=NOW + 3)

    out = capsys.readouterr().out
    rows = quarantined_rows(gw)
    assert len(rows) == 2
    summaries = " ".join(str(row[4]) for row in rows)
    reason_codes = " ".join(str(row[2]) for row in rows)
    for secret in (API_KEY, HMAC, "f" * 32, "e" * 32):
        assert secret not in out
        assert secret not in summaries
        assert secret not in reason_codes
    assert all(len(row[4]) <= gateway.RESPONSE_SUMMARY_MAX_LENGTH for row in rows)
    assert "PACKET_AUTH_FAILED" in rows[0][4]
    # packet 列は、署名つきの raw packet をそのまま保存する(改変しない)
    assert rows[0][0] == auth_failed
    assert API_KEY not in repr(gw.sender)


def test_missing_api_key_exits(monkeypatch):
    monkeypatch.delenv("TSUNAGU_GATEWAY_API_KEY", raising=False)
    monkeypatch.delenv("SHELTEROS_GATEWAY_API_KEY", raising=False)
    monkeypatch.setattr("sys.argv", ["lora_serial_gateway.py"])
    with pytest.raises(SystemExit, match="TSUNAGU_GATEWAY_API_KEY is required"):
        gateway.main()


def test_new_environment_variable_takes_priority(monkeypatch):
    monkeypatch.setenv("TSUNAGU_API_URL", "https://new.example")
    monkeypatch.setenv("SHELTEROS_API_URL", "https://legacy.example")

    assert gateway._environment_value("TSUNAGU_API_URL", "SHELTEROS_API_URL") == "https://new.example"


# ---- 隔離済みの Packet の重複防止 ----


def test_quarantined_packet_is_not_requeued_when_received_again(tmp_path, api, capsys):
    gw = make_gateway(tmp_path, api.url)
    bad = v2_packet("CRITICAL", sequence="00000001")
    api.responder = lambda body: (
        (400, {"detail": {"code": "PACKET_FORMAT_INVALID"}}, {}) if body["packet"] == bad else (201, {"id": "EP-x"}, {})
    )
    gw.accept_line(bad, now=NOW)
    assert gw.queue.quarantined_count() == 1
    capsys.readouterr()

    # 同じ Packet を再受信しても、キューへ入れず、送らない
    assert gw.accept_line(bad + "\r\n", now=NOW + 10) is None
    assert gw.queue.count() == 0
    assert api.packets == [bad]
    out = capsys.readouterr().out
    assert "already quarantined (not requeued): id=" in out
    assert HMAC not in out

    # 再起動しても同じ。ほかの Packet は送る
    gw.queue.connection.close()
    restarted = make_gateway(tmp_path, api.url)
    assert restarted.queue.enqueue(bad, NOW + 20) is None
    restarted.accept_line(NORMAL_V1, now=NOW + 30)
    assert api.packets == [bad, NORMAL_V1]
    assert restarted.queue.quarantined_count() == 1


def _create_legacy_quarantine(path, rows):
    """packet_hash 列と一意制約が無い、以前の形の隔離テーブルを作る。"""
    legacy = sqlite3.connect(path)
    legacy.execute("CREATE TABLE pending_packets (id TEXT PRIMARY KEY, packet TEXT NOT NULL, queued_at REAL NOT NULL)")
    legacy.execute(
        """
        CREATE TABLE quarantined_packets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            packet TEXT NOT NULL,
            hub_received_at TEXT,
            reason_code TEXT NOT NULL,
            http_status INTEGER,
            response_summary TEXT,
            quarantined_at REAL NOT NULL
        )
        """
    )
    legacy.executemany(
        "INSERT INTO quarantined_packets (packet, hub_received_at, reason_code, http_status, response_summary,"
        " quarantined_at) VALUES (?, ?, ?, ?, ?, ?)",
        rows,
    )
    legacy.commit()
    legacy.close()


def test_quarantine_unique_constraint_and_legacy_duplicates(tmp_path, capsys):
    path = tmp_path / "queue.db"
    bad = v2_packet("CRITICAL", sequence="00000001")
    other = v2_packet("ALERT", sequence="00000002")
    _create_legacy_quarantine(path, [
        (bad, "t1", "PACKET_AUTH_FAILED", 403, "first", NOW),
        (other, "t2", "PACKET_FORMAT_INVALID", 400, "other", NOW + 1),
        (bad, "t3", "PACKET_AUTH_FAILED", 403, "second", NOW + 2),
        (bad, "t4", "PACKET_DUPLICATE_CONFLICT", 409, "newest", NOW + 3),
    ])

    queue = gateway.PacketQueue(path)

    # 重複は、Packet ごとに最も新しい行だけを残す
    rows = list(queue.connection.execute(
        "SELECT packet, hub_received_at, reason_code, response_summary, packet_hash FROM quarantined_packets ORDER BY id"
    ))
    assert [row[:4] for row in rows] == [
        (other, "t2", "PACKET_FORMAT_INVALID", "other"),
        (bad, "t4", "PACKET_DUPLICATE_CONFLICT", "newest"),
    ]
    assert [row[4] for row in rows] == [gateway.packet_key(other), gateway.packet_key(bad)]
    assert "quarantine migration: removed 2 duplicate rows" in capsys.readouterr().out

    # 重複の挿入は、一意制約で防がれる
    with pytest.raises(sqlite3.IntegrityError):
        queue.connection.execute(
            "INSERT INTO quarantined_packets (packet, reason_code, quarantined_at, packet_hash) VALUES (?, ?, ?, ?)",
            (bad, "HTTP_400", NOW, gateway.packet_key(bad)),
        )
    queue.connection.rollback()
    assert queue.enqueue(bad, NOW + 10) is None

    # 2回目の起動では、何も消さない
    queue.connection.close()
    queue = gateway.PacketQueue(path)
    assert queue.quarantined_count() == 2
    assert "quarantine migration" not in capsys.readouterr().out
    queue.connection.close()


def test_legacy_quarantine_migration_failure_leaves_file_unchanged(tmp_path):
    path = tmp_path / "queue.db"
    bad = v2_packet("CRITICAL", sequence="00000001")
    _create_legacy_quarantine(path, [
        (bad, "t1", "PACKET_AUTH_FAILED", 403, "first", NOW),
        (bad, "t2", "PACKET_AUTH_FAILED", 403, "second", NOW + 1),
    ])
    # 重複を整理できない状況の代わりに、削除を拒むトリガーを置く
    blocker = sqlite3.connect(path)
    blocker.execute(
        "CREATE TRIGGER block_delete BEFORE DELETE ON quarantined_packets BEGIN SELECT RAISE(ABORT, 'blocked'); END"
    )
    blocker.commit()
    blocker.close()

    with pytest.raises(SystemExit, match="The queue file was not changed"):
        gateway.PacketQueue(path)

    check = sqlite3.connect(path)
    try:
        columns = {row[1] for row in check.execute("PRAGMA table_info(quarantined_packets)")}
        assert "packet_hash" not in columns
        assert check.execute("SELECT count(*) FROM quarantined_packets").fetchone()[0] == 2
        assert check.execute(
            "SELECT count(*) FROM sqlite_master WHERE name = 'quarantined_packets_packet_hash'"
        ).fetchone()[0] == 0
    finally:
        check.close()


# ---- APIのURLの秘密 ----


URL_USER = "gw-user-secret"
URL_PASSWORD = "gw-password-secret"
URL_TOKEN = "query-token-secret"
URL_FRAGMENT = "fragment-secret"


def test_api_url_credentials_and_query_do_not_leak(tmp_path, api, capsys):
    port = api.server.server_address[1]
    expected = f"http://127.0.0.1:{port}"

    # クエリとフラグメント: 実際にテスト用のサーバーへ送り、401 で停止させる
    query_url = f"{expected}/api/emergency-packets?token={URL_TOKEN}#{URL_FRAGMENT}"
    api.responder = _respond(401, {"detail": "Invalid gateway API key"})
    gw = make_gateway(tmp_path, query_url)
    gw.accept_line(CRITICAL_V1, now=NOW)
    assert api.requests[0]["path"] == f"/api/emergency-packets?token={URL_TOKEN}"  # 送信先は変えない

    # 認証情報(userinfo): urllib はホストの一部として扱うので、応答だけを差し替えて停止させる
    class UnauthorizedSender(gateway.ApiSender):
        def post(self, packet, hub_received_at):
            return gateway.ApiResponse(401, b"{}")

    userinfo_url = f"http://{URL_USER}:{URL_PASSWORD}@127.0.0.1:{port}/api/emergency-packets?token={URL_TOKEN}#{URL_FRAGMENT}"
    userinfo_gw = gateway.Gateway(
        gateway.PacketQueue(tmp_path / "userinfo.db"), UnauthorizedSender(userinfo_url, API_KEY), rng=random.Random(0)
    )
    userinfo_gw.accept_line(CRITICAL_V1, now=NOW)

    texts = {
        "repr": repr(gw.sender),
        "stopped_reason": gw.stopped_reason,
        "userinfo repr": repr(userinfo_gw.sender),
        "userinfo stopped_reason": userinfo_gw.stopped_reason,
        "log": capsys.readouterr().out,
    }
    for name, text in texts.items():
        for secret in (URL_USER, URL_PASSWORD, URL_TOKEN, URL_FRAGMENT, "/api/emergency-packets"):
            assert secret not in text, f"{secret} in {name}"
    assert gw.stopped_reason == userinfo_gw.stopped_reason == f"HTTP_401 from {expected}"
    assert texts["userinfo repr"] == f"ApiSender(api_url='{expected}')"
    assert f"sending is STOPPED (configuration error: HTTP_401 from {expected})" in texts["log"]
