"""クラウドへの配送(Outbox)のテスト。

クラウドへの送信は httpx.MockTransport で模擬し、実ネットワークは使わない。
鍵はすべてテスト専用のダミー値。
"""

import json
import logging
import random
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

import app.outbox as outbox_module
from app import outbox_worker
from app.config import validate_runtime_settings
from app.db import get_conn
from app.emergency_packet import compute_packet_hmac
from app.main import app
from app.outbox import OutboxConfigError, destination_statuses, load_outbox_settings, redact_url

DEVICE_KEY = bytes(range(0, 32))  # テスト専用のダミー端末鍵
client = TestClient(app)


class Env:
    def __init__(self, monkeypatch):
        self.monkeypatch = monkeypatch
        self.destinations: list[dict] = []
        self.keys: dict[str, str] = {}

    def add_destination(self, base_url: str = "https://cloud.invalid") -> str:
        destination_id = f"t-{uuid4().hex[:12]}"
        key_env = f"OUTBOX_KEY_{destination_id.upper().replace('-', '_')}"
        key = f"dummy-outbox-key-{uuid4().hex}"
        self.destinations.append({"id": destination_id, "base_url": base_url, "key_env": key_env})
        self.keys[destination_id] = key
        self.monkeypatch.setenv(key_env, key)
        self.monkeypatch.setenv("OUTBOX_DESTINATIONS", json.dumps(self.destinations))
        return destination_id


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("PACKET_DEVICE_KEYS", json.dumps({"TB001": {"01": DEVICE_KEY.hex()}}))
    monkeypatch.delenv("PACKET_DEVICE_KEYS_FILE", raising=False)
    monkeypatch.delenv("PACKET_DISABLED_DEVICES", raising=False)
    monkeypatch.setenv("ALLOW_V1_PACKETS", "true")
    monkeypatch.setenv("OUTBOX_ENABLED", "true")
    monkeypatch.setenv("OUTBOX_DESTINATIONS", "[]")
    for name in ("OUTBOX_BATCH_SIZE", "OUTBOX_PROBE_INTERVAL_SECONDS", "OUTBOX_LEASE_SECONDS"):
        monkeypatch.delenv(name, raising=False)
    client.cookies.clear()
    client.headers["X-Gateway-Key"] = "test-gateway-key"
    yield Env(monkeypatch)
    client.headers.pop("X-Gateway-Key", None)
    client.headers.pop("X-CSRF-Token", None)
    client.cookies.clear()


class FakeCloud:
    """クラウドの受信APIの模擬。responder で応答を決める。"""

    def __init__(self, responder=None):
        self.requests: list[httpx.Request] = []
        self.responder = responder or (lambda request: httpx.Response(201, json={"id": "EP-cloud"}))

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/health"):
            self.requests.append(request)
            return httpx.Response(200, json={"status": "ok"})
        self.requests.append(request)
        return self.responder(request)

    @property
    def deliveries(self) -> list[httpx.Request]:
        return [request for request in self.requests if request.method == "POST"]

    @property
    def probes(self) -> list[httpx.Request]:
        return [request for request in self.requests if request.method == "GET"]

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handler))


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def make_packet(status: str = "WARNING", people_count: int = 170, reported_at: int | None = None) -> str:
    install_id = uuid4().hex[:16].upper()
    reported_at = reported_at or int(utc_now().timestamp())
    payload = f"v2|TB001|01|{install_id}|0000002A|{reported_at}|AIT001|{people_count}|18|{status}|REQ_WATER"
    return f"{payload}|{compute_packet_hmac(DEVICE_KEY, payload)}"


def post_packet(packet: str, hub_received_at: datetime | None = None) -> dict:
    body = {"packet": packet}
    if hub_received_at is not None:
        body["hub_received_at"] = hub_received_at.isoformat()
    response = client.post("/api/emergency-packets", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def outbox_rows(packet_id: str | None = None, destination_id: str | None = None) -> list[dict]:
    conditions, params = [], []
    if packet_id:
        conditions.append("emergency_packet_id = %s")
        params.append(packet_id)
    if destination_id:
        conditions.append("destination_id = %s")
        params.append(destination_id)
    with get_conn() as conn:
        return conn.execute(
            f"SELECT * FROM delivery_outbox WHERE {' AND '.join(conditions)} ORDER BY created_at, id;", params
        ).fetchall()


def attempts_for(destination_id: str, kind: str | None = None) -> list[dict]:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM delivery_attempts WHERE destination_id = %s AND (%s::text IS NULL OR kind = %s) "
            "ORDER BY attempted_at, id;",
            (destination_id, kind, kind),
        ).fetchall()


def run(cloud: FakeCloud, now: datetime, seed: int = 0) -> outbox_worker.RunSummary:
    with cloud.client() as http_client:
        return outbox_worker.run_once(now, http_client=http_client, rng=random.Random(seed))


def due() -> datetime:
    # 登録時刻はDBの now()。DBとこのPCの時計の差を見込んで、少し先の時刻で実行する。
    return utc_now() + timedelta(seconds=5)


def login(role: str = "hq") -> None:
    response = client.post("/api/auth/dev-login", json={"role": role, "name": "Test User"})
    assert response.status_code == 204
    client.headers["X-CSRF-Token"] = client.cookies.get("tsunagu_csrf")


# ---- 登録 ----


def test_only_signed_v2_reports_are_registered_once_per_destination(env):
    first = env.add_destination()
    second = env.add_destination()

    v2 = post_packet(make_packet())
    v2_again = post_packet(v2["raw_packet"])
    v1 = post_packet(f"v1|AIT001|10:{uuid4().int % 60:02d}|{900_000 + uuid4().int % 1000}|1|NORMAL|NONE")

    assert v2_again["id"] == v2["id"]
    rows = outbox_rows(packet_id=v2["id"])
    assert sorted(row["destination_id"] for row in rows) == sorted([first, second])
    assert all(row["state"] == "PENDING" and row["attempts"] == 0 for row in rows)
    assert v1["signature_status"] == "UNSIGNED_V1"
    assert outbox_rows(packet_id=v1["id"]) == []


def test_outbox_disabled_does_nothing(env, monkeypatch):
    destination = env.add_destination()
    monkeypatch.setenv("OUTBOX_ENABLED", "false")
    packet = post_packet(make_packet())
    cloud = FakeCloud()

    summary = run(cloud, due())

    assert outbox_rows(packet_id=packet["id"]) == []
    assert cloud.requests == []
    assert summary == outbox_worker.RunSummary()
    assert attempts_for(destination) == []


def test_registration_failure_keeps_report_and_is_logged(env, monkeypatch, caplog):
    env.add_destination()

    def broken(*args, **kwargs):
        raise RuntimeError("simulated outbox failure")

    monkeypatch.setattr(outbox_module, "register_packet_for_delivery", broken)
    caplog.set_level(logging.ERROR)
    packet = post_packet(make_packet(status="CRITICAL"))

    assert packet["signature_status"] == "SIGNATURE_VALID"
    assert packet["observation_id"] is not None
    assert outbox_rows(packet_id=packet["id"]) == []
    assert "Outbox registration failed" in caplog.text

    # 登録が直れば、同じ報告の再送で登録される(重複はしない)。
    monkeypatch.undo()
    monkeypatch.setenv("OUTBOX_ENABLED", "true")
    monkeypatch.setenv("OUTBOX_DESTINATIONS", json.dumps(env.destinations))
    monkeypatch.setenv("PACKET_DEVICE_KEYS", json.dumps({"TB001": {"01": DEVICE_KEY.hex()}}))
    post_packet(packet["raw_packet"])
    post_packet(packet["raw_packet"])
    assert len(outbox_rows(packet_id=packet["id"])) == 1


# ---- 応答の分類 ----


def _json_response(status: int, body) -> callable:
    return lambda request: httpx.Response(status, json=body)


def _raise(exc_type):
    def responder(request):
        raise exc_type("simulated", request=request)

    return responder


@pytest.mark.parametrize(
    ("responder", "expected_state", "expected_error", "expected_http"),
    [
        (_json_response(201, {"id": "EP-x"}), "ACCEPTED", None, 201),
        (_json_response(200, {"id": "EP-x"}), "ACCEPTED", None, 200),
        (_json_response(400, {"detail": {"code": "PACKET_FORMAT_INVALID"}}), "QUARANTINED", "PACKET_FORMAT_INVALID", 400),
        (_json_response(422, {"detail": [{"msg": "invalid"}]}), "QUARANTINED", "HTTP_422", 422),
        (_json_response(401, {"detail": "Invalid gateway API key"}), "STOPPED", "HTTP_401", 401),
        (_json_response(403, {"detail": {"code": "PACKET_AUTH_FAILED"}}), "QUARANTINED", "PACKET_AUTH_FAILED", 403),
        (_json_response(403, {"detail": "Forbidden"}), "STOPPED", "HTTP_403", 403),
        (_json_response(409, {"detail": {"code": "PACKET_DUPLICATE_CONFLICT"}}), "QUARANTINED",
         "PACKET_DUPLICATE_CONFLICT", 409),
        (_json_response(429, {"detail": "slow down"}), "PENDING", "HTTP_429", 429),
        (_json_response(500, {"detail": "error"}), "PENDING", "HTTP_500", 500),
        (_json_response(503, {"detail": "error"}), "PENDING", "HTTP_503", 503),
        (lambda request: httpx.Response(302, headers={"Location": "https://other.invalid/"}), "STOPPED", "HTTP_302",
         302),
        (_raise(httpx.ConnectError), "PENDING", "NETWORK_ERROR", None),
        (_raise(httpx.ReadTimeout), "PENDING", "TIMEOUT", None),
    ],
    ids=["201", "200", "400", "422", "401", "403-auth", "403-other", "409", "429", "500", "503", "302", "network",
         "timeout"],
)
def test_response_classification(env, responder, expected_state, expected_error, expected_http):
    destination = env.add_destination()
    packet = post_packet(make_packet())
    cloud = FakeCloud(responder)
    now = due()

    run(cloud, now)

    row = outbox_rows(packet_id=packet["id"])[0]
    assert row["state"] == expected_state
    assert row["last_error_code"] == expected_error
    assert row["attempts"] == 1
    assert row["lease_until"] is None
    attempt = attempts_for(destination, "DELIVERY")[0]
    assert attempt["outbox_id"] == row["id"]
    assert attempt["http_status"] == expected_http
    assert attempt["error_code"] == expected_error
    assert attempt["latency_ms"] is not None and attempt["latency_ms"] >= 0
    assert len(cloud.deliveries) == 1
    if expected_state == "PENDING":
        assert row["next_attempt_at"] > now
    if expected_state == "ACCEPTED":
        assert row["accepted_at"] == now


def test_stopped_destination_keeps_rows_and_others_continue(env):
    stopped = env.add_destination("https://stopped.invalid")
    healthy = env.add_destination("https://healthy.invalid")
    packets = [post_packet(make_packet()) for _ in range(2)]

    def responder(request):
        if request.url.host == "stopped.invalid":
            return httpx.Response(401, json={"detail": "Invalid gateway API key"})
        return httpx.Response(201, json={"id": "EP-x"})

    cloud = FakeCloud(responder)
    run(cloud, due())
    run(cloud, due() + timedelta(seconds=600))

    stopped_rows = outbox_rows(destination_id=stopped)
    assert sorted(row["state"] for row in stopped_rows) == ["PENDING", "STOPPED"]
    assert [row["state"] for row in outbox_rows(destination_id=healthy)] == ["ACCEPTED", "ACCEPTED"]
    # 止まった宛先へは、最初の1件のあと送っていない(行は保持されている)。
    assert len([r for r in cloud.deliveries if r.url.host == "stopped.invalid"]) == 1
    assert {row["emergency_packet_id"] for row in stopped_rows} == {packet["id"] for packet in packets}


# ---- バックオフ・周回 ----


def test_backoff_is_exponential_with_jitter_and_capped():
    settings = load_outbox_settings()
    rng = random.Random(1)
    for attempts, ceiling in [(1, 5), (2, 10), (3, 20), (4, 40), (5, 80), (6, 160), (7, 300), (8, 300), (30, 300)]:
        for _ in range(20):
            delay = outbox_worker.backoff_seconds(attempts, settings, rng)
            assert ceiling / 2 <= delay <= ceiling


def test_retry_waits_for_backoff_before_next_attempt(env):
    destination = env.add_destination()
    packet = post_packet(make_packet())
    cloud = FakeCloud(_json_response(503, {"detail": "error"}))
    t0 = due()

    run(cloud, t0)
    first = outbox_rows(packet_id=packet["id"])[0]
    assert t0 + timedelta(seconds=2.5) <= first["next_attempt_at"] <= t0 + timedelta(seconds=5)

    run(cloud, t0 + timedelta(seconds=2))  # まだ期限前
    assert len(cloud.deliveries) == 1

    run(cloud, first["next_attempt_at"])
    second = outbox_rows(packet_id=packet["id"])[0]
    assert second["attempts"] == 2
    assert first["next_attempt_at"] + timedelta(seconds=5) <= second["next_attempt_at"]
    assert second["next_attempt_at"] <= first["next_attempt_at"] + timedelta(seconds=10)
    assert len(attempts_for(destination, "DELIVERY")) == 2


@pytest.mark.parametrize("exc_type", [httpx.ConnectError, httpx.ReadTimeout])
def test_network_failure_ends_the_cycle(env, exc_type):
    destination = env.add_destination()
    for _ in range(3):
        post_packet(make_packet())
    cloud = FakeCloud(_raise(exc_type))

    run(cloud, due())

    assert len(cloud.deliveries) == 1
    states = sorted((row["state"], row["attempts"]) for row in outbox_rows(destination_id=destination))
    assert states == [("PENDING", 0), ("PENDING", 0), ("PENDING", 1)]


def test_server_errors_continue_with_next_row(env):
    destination = env.add_destination()
    for _ in range(3):
        post_packet(make_packet())
    cloud = FakeCloud(_json_response(503, {"detail": "error"}))

    run(cloud, due())

    assert len(cloud.deliveries) == 3
    assert all(row["attempts"] == 1 for row in outbox_rows(destination_id=destination))


def test_priority_then_hub_received_at_order_and_batch_size(env, monkeypatch):
    env.add_destination()
    base = utc_now().replace(microsecond=0)
    plan = [
        ("NORMAL", 1),
        ("CRITICAL", 3),
        ("WARNING", 0),
        ("CRITICAL", 2),
        ("ALERT", 4),
    ]
    packets = {}
    for status, offset in plan:
        packet = post_packet(make_packet(status=status, reported_at=int(base.timestamp())),
                             hub_received_at=base + timedelta(seconds=offset))
        packets[packet["raw_packet"]] = (status, offset)
    cloud = FakeCloud()

    monkeypatch.setenv("OUTBOX_BATCH_SIZE", "3")
    run(cloud, due())
    assert len(cloud.deliveries) == 3
    monkeypatch.setenv("OUTBOX_BATCH_SIZE", "10")
    run(cloud, due())

    order = [packets[json.loads(request.content)["packet"]] for request in cloud.deliveries]
    assert order == [("CRITICAL", 2), ("CRITICAL", 3), ("ALERT", 4), ("WARNING", 0), ("NORMAL", 1)]


# ---- リース・再実行・冪等 ----


def test_expired_lease_returns_to_pending_and_reruns_are_stable(env):
    destination = env.add_destination()
    packet = post_packet(make_packet())
    t0 = due()
    # ワーカーが SENDING にしたまま落ちた状態を作る。
    with get_conn() as conn:
        claimed = outbox_worker.claim_next(conn, destination, t0, 60)
    assert claimed["emergency_packet_id"] == packet["id"]
    assert outbox_rows(packet_id=packet["id"])[0]["state"] == "SENDING"
    cloud = FakeCloud()

    run(cloud, t0 + timedelta(seconds=30))  # リース中
    assert outbox_rows(packet_id=packet["id"])[0]["state"] == "SENDING"
    assert cloud.deliveries == []

    summary = run(cloud, t0 + timedelta(seconds=61))
    assert summary.released_leases >= 1
    row = outbox_rows(packet_id=packet["id"])[0]
    assert row["state"] == "ACCEPTED"
    assert row["attempts"] == 2

    for offset in (62, 63, 200):
        run(cloud, t0 + timedelta(seconds=offset))
    assert len(cloud.deliveries) == 1
    after = outbox_rows(packet_id=packet["id"])[0]
    assert after["state"] == "ACCEPTED" and after["attempts"] == 2


def test_lost_response_is_resent_without_duplicate(env):
    destination = env.add_destination()
    packet = post_packet(make_packet())
    stored: dict[str, str] = {}

    def cloud_responder(request):
        raw = json.loads(request.content)["packet"]
        parts = raw.split("|")
        key = "|".join([parts[1], parts[3], parts[4]])  # (device_id, install_id, sequence)
        first_time = key not in stored
        stored.setdefault(key, f"EP-cloud-{len(stored)}")
        if first_time:
            # 受理したが、応答がローカルに届かなかった。
            raise httpx.ReadTimeout("response lost", request=request)
        return httpx.Response(201, json={"id": stored[key]})

    cloud = FakeCloud(cloud_responder)
    t0 = due()
    run(cloud, t0)
    assert outbox_rows(packet_id=packet["id"])[0]["state"] == "PENDING"
    run(cloud, t0 + timedelta(seconds=10))

    row = outbox_rows(packet_id=packet["id"])[0]
    assert row["state"] == "ACCEPTED"
    assert row["attempts"] == 2
    assert len(stored) == 1
    assert len(cloud.deliveries) == 2
    assert [a["error_code"] for a in attempts_for(destination, "DELIVERY")] == ["TIMEOUT", None]


def test_payload_carries_raw_packet_hub_time_and_key(env):
    destination = env.add_destination()
    hub_received_at = utc_now().replace(microsecond=0)
    packet = post_packet(make_packet(reported_at=int(hub_received_at.timestamp())), hub_received_at)
    cloud = FakeCloud()
    now = due()

    run(cloud, now)

    request = cloud.deliveries[0]
    assert request.url.path == "/api/emergency-packets"
    body = json.loads(request.content)
    assert body["packet"] == packet["raw_packet"]
    assert datetime.fromisoformat(body["hub_received_at"]) == hub_received_at
    assert request.headers["X-Gateway-Key"] == env.keys[destination]
    with get_conn() as conn:
        synced = conn.execute(
            "SELECT cloud_synced_at FROM emergency_packets WHERE id = %s;", (packet["id"],)
        ).fetchone()["cloud_synced_at"]
    assert synced == now


# ---- プローブと状態 ----


def test_probe_is_recorded_without_key_and_continues_when_stopped(env):
    destination = env.add_destination()
    post_packet(make_packet())
    cloud = FakeCloud(_json_response(401, {"detail": "Invalid gateway API key"}))
    t0 = due()

    run(cloud, t0)
    run(cloud, t0 + timedelta(seconds=10))  # 間隔内
    run(cloud, t0 + timedelta(seconds=31))  # STOPPED でもプローブは続ける

    probes = attempts_for(destination, "PROBE")
    assert [probe["outcome"] for probe in probes] == ["PROBE_OK", "PROBE_OK"]
    assert all(probe["outbox_id"] is None for probe in probes)
    assert len(cloud.probes) == 2
    assert all("X-Gateway-Key" not in request.headers for request in cloud.probes)
    assert cloud.probes[0].url.path == "/health"


def _status(destination_id: str, now: datetime) -> dict:
    with get_conn() as conn:
        statuses = destination_statuses(conn, load_outbox_settings(), now)
    return next(status for status in statuses if status["destination_id"] == destination_id)


def _insert_probe(destination_id: str, at: datetime, latency_ms: int, outcome: str = "PROBE_OK") -> None:
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO delivery_attempts (id, outbox_id, destination_id, kind, attempted_at, outcome, http_status,
                                           latency_ms, error_code)
            VALUES (%s, NULL, %s, 'PROBE', %s, %s, 200, %s, NULL);
            """,
            (f"ATT-{uuid4().hex}", destination_id, at, outcome, latency_ms),
        )
        conn.commit()


def test_status_unknown_normal_down(env):
    destination = env.add_destination()
    now = due()
    assert _status(destination, now)["state"] == "UNKNOWN"

    post_packet(make_packet())
    run(FakeCloud(), now)
    status = _status(destination, now + timedelta(seconds=1))
    assert status["state"] == "NORMAL"
    assert status["last_success_at"] == now
    assert status["last_reachable_at"] == now
    assert status["queue_depth"] == 0

    assert _status(destination, now + timedelta(seconds=120))["state"] == "NORMAL"
    assert _status(destination, now + timedelta(seconds=121))["state"] == "DOWN"


def test_status_down_when_attempted_but_never_reached(env):
    destination = env.add_destination()
    post_packet(make_packet())
    cloud = FakeCloud(_raise(httpx.ConnectError))
    cloud.handler = lambda request: (_ for _ in ()).throw(httpx.ConnectError("down", request=request))
    now = due()
    run(cloud, now)
    status = _status(destination, now + timedelta(seconds=1))
    assert status["state"] == "DOWN"
    assert status["last_reachable_at"] is None
    assert status["last_error_code"] == "NETWORK_ERROR"


def test_status_delayed_by_latency_or_old_pending(env):
    slow = env.add_destination()
    now = due()
    _insert_probe(slow, now, latency_ms=5001)
    assert _status(slow, now + timedelta(seconds=1))["state"] == "DELAYED"
    _insert_probe(slow, now + timedelta(seconds=2), latency_ms=5000)
    assert _status(slow, now + timedelta(seconds=3))["state"] == "NORMAL"

    backlog = env.add_destination()
    packet = post_packet(make_packet())
    created_at = outbox_rows(packet_id=packet["id"], destination_id=backlog)[0]["created_at"]
    _insert_probe(backlog, created_at + timedelta(seconds=60), latency_ms=10)
    assert _status(backlog, created_at + timedelta(seconds=60))["state"] == "NORMAL"
    status = _status(backlog, created_at + timedelta(seconds=61))
    assert status["state"] == "DELAYED"
    assert status["queue_depth"] == 1
    assert status["oldest_pending_at"] == created_at


def test_status_auth_error_and_quarantine_counts(env):
    destination = env.add_destination()
    for _ in range(2):
        post_packet(make_packet())
    responses = iter([
        httpx.Response(403, json={"detail": {"code": "PACKET_AUTH_FAILED"}}),
        httpx.Response(401, json={"detail": "Invalid gateway API key"}),
    ])
    run(FakeCloud(lambda request: next(responses)), due())

    status = _status(destination, due())
    assert status["state"] == "AUTH_ERROR"
    assert status["quarantined_count"] == 1
    assert status["quarantined_by_error_code"] == {"PACKET_AUTH_FAILED": 1}
    assert status["stopped_count"] == 1
    assert status["last_error_code"] == "HTTP_401"


# ---- requeue / resume ----


def test_requeue_and_resume(env, caplog):
    destination = env.add_destination()
    quarantined = post_packet(make_packet(status="CRITICAL"))
    stopped = post_packet(make_packet(status="NORMAL"))
    responses = iter([
        httpx.Response(403, json={"detail": {"code": "PACKET_AUTH_FAILED"}}),
        httpx.Response(401, json={"detail": "Invalid gateway API key"}),
    ])
    t0 = due()
    run(FakeCloud(lambda request: next(responses)), t0)
    assert outbox_rows(packet_id=quarantined["id"], destination_id=destination)[0]["state"] == "QUARANTINED"
    assert outbox_rows(packet_id=stopped["id"], destination_id=destination)[0]["state"] == "STOPPED"

    caplog.set_level(logging.WARNING)
    assert outbox_worker.requeue(destination, "HTTP_409") == 0
    assert outbox_worker.main(["requeue", "--destination", destination, "--error-code", "PACKET_AUTH_FAILED"]) == 0
    assert outbox_rows(packet_id=quarantined["id"], destination_id=destination)[0]["state"] == "PENDING"
    assert f"Outbox requeue: destination={destination} error_code=PACKET_AUTH_FAILED requeued=1" in caplog.text

    # STOPPED が残っている間は、戻した行も送らない。
    cloud = FakeCloud()
    run(cloud, t0 + timedelta(seconds=1))
    assert cloud.deliveries == []

    assert outbox_worker.resume(destination) == 1
    assert f"Outbox resume: destination={destination} resumed=1" in caplog.text
    run(cloud, due() + timedelta(seconds=2))
    assert len(cloud.deliveries) == 2
    assert {row["state"] for row in outbox_rows(destination_id=destination)} == {"ACCEPTED"}


# ---- API ----


def test_status_and_deliveries_api(env):
    destination = env.add_destination()
    v2 = post_packet(make_packet())
    v1 = post_packet(f"v1|AIT001|11:{uuid4().int % 60:02d}|{910_000 + uuid4().int % 1000}|1|NORMAL|NONE")
    responses = iter([httpx.Response(503, json={}), httpx.Response(201, json={"id": "EP-x"})])
    cloud = FakeCloud(lambda request: next(responses))
    t0 = due()
    run(cloud, t0)
    run(cloud, t0 + timedelta(seconds=10))

    login("hq")
    status = client.get("/api/destinations/status")
    assert status.status_code == 200
    body = status.json()
    assert body["enabled"] is True
    entry = next(item for item in body["destinations"] if item["destination_id"] == destination)
    assert entry["configured"] is True
    assert entry["queue_depth"] == 0
    assert entry["accepted_count"] == 1

    deliveries = client.get(f"/api/emergency-packets/{v2['id']}/deliveries")
    assert deliveries.status_code == 200
    data = deliveries.json()
    assert data["forwardable"] is True
    assert data["signature_status"] == "SIGNATURE_VALID"
    delivery = data["deliveries"][0]
    assert delivery["destination_id"] == destination
    assert delivery["state"] == "ACCEPTED"
    assert delivery["attempts"] == 2
    assert [item["outcome"] for item in delivery["history"]] == ["RETRY", "ACCEPTED"]
    assert [item["http_status"] for item in delivery["history"]] == [503, 201]

    v1_deliveries = client.get(f"/api/emergency-packets/{v1['id']}/deliveries").json()
    assert v1_deliveries["forwardable"] is False
    assert v1_deliveries["signature_status"] == "UNSIGNED_V1"
    assert v1_deliveries["deliveries"] == []

    assert client.get("/api/emergency-packets/EP-does-not-exist/deliveries").status_code == 404


@pytest.mark.parametrize("path", ["/api/destinations/status", "/api/emergency-packets/EP-demo-seed-2/deliveries"])
def test_delivery_apis_require_hq(env, path):
    client.cookies.clear()
    assert client.get(path).status_code == 401
    login("field")
    assert client.get(path).status_code == 403


# ---- 秘密 ----


def test_keys_and_url_credentials_do_not_leak(env, caplog):
    # 設定の検証は、認証情報・クエリ付きのURLを拒否する。ここでは検証をすり抜けた場合でも漏れないこと(多層防御)を確かめる。
    env.monkeypatch.setattr(outbox_module, "_validate_base_url", lambda base_url, index: base_url)
    destination = env.add_destination("https://user:url-secret@cloud.invalid/base?token=query-secret")
    key = env.keys[destination]
    packet = post_packet(make_packet())
    caplog.set_level(logging.DEBUG)
    cloud = FakeCloud(_json_response(401, {"detail": "Invalid gateway API key"}))

    run(cloud, due())
    outbox_worker.resume(destination)
    settings = load_outbox_settings(require_keys=True)
    logging.getLogger("test").info("%r", settings)

    login("hq")
    api_texts = [
        client.get("/api/destinations/status").text,
        client.get(f"/api/emergency-packets/{packet['id']}/deliveries").text,
    ]
    with get_conn() as conn:
        db_text = str(conn.execute("SELECT * FROM delivery_outbox WHERE destination_id = %s;", (destination,)).fetchall())
        db_text += str(attempts_for(destination))

    assert "STOPPED (configuration error" in caplog.text
    assert "cloud.invalid" in caplog.text
    for secret in (key, "url-secret", "query-secret"):
        assert secret not in caplog.text
        assert secret not in db_text
        for text in api_texts:
            assert secret not in text
    assert redact_url("https://user:pw@h.invalid:8443/p?q=1#f") == "https://<redacted>@h.invalid:8443/p?<redacted>#<redacted>"


# ---- 設定 ----


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ("not json", "not valid JSON"),
        ('{"id": "x"}', "JSON array"),
        ('[{"id": "Bad Id", "base_url": "https://x.invalid", "key_env": "K"}]', "id is invalid"),
        ('[{"id": "a", "base_url": "ftp://user:pw-secret@x.invalid", "key_env": "K"}]', "http(s) URL"),
        ('[{"id": "a", "base_url": "https://x.invalid", "key_env": "lower"}]', "key_env is invalid"),
        ('[{"id": "a", "base_url": "https://x.invalid", "key_env": "K", "key": "inline"}]', "only"),
        ('[{"id": "a", "base_url": "https://x.invalid", "key_env": "K"},'
         ' {"id": "a", "base_url": "https://y.invalid", "key_env": "K"}]', "duplicate"),
    ],
)
def test_invalid_destination_config_fails_at_startup(monkeypatch, raw, message):
    monkeypatch.setenv("OUTBOX_DESTINATIONS", raw)
    with pytest.raises(OutboxConfigError) as excinfo:
        validate_runtime_settings()
    assert message in str(excinfo.value)
    assert "pw-secret" not in str(excinfo.value)


def test_worker_requires_key_without_revealing_values(monkeypatch):
    monkeypatch.setenv("OUTBOX_ENABLED", "true")
    monkeypatch.setenv(
        "OUTBOX_DESTINATIONS", '[{"id": "a", "base_url": "https://x.invalid", "key_env": "OUTBOX_KEY_MISSING_TEST"}]'
    )
    monkeypatch.delenv("OUTBOX_KEY_MISSING_TEST", raising=False)
    load_outbox_settings()  # APIは鍵を持たないので、書式だけ確認する
    with pytest.raises(OutboxConfigError, match="OUTBOX_KEY_MISSING_TEST"):
        load_outbox_settings(require_keys=True)
    monkeypatch.setenv("OUTBOX_BATCH_SIZE", "0")
    with pytest.raises(OutboxConfigError, match="OUTBOX_BATCH_SIZE"):
        load_outbox_settings()


# ---- backfill ----


def _unique_window() -> datetime:
    # --since は「指定時刻以降」なので、DBにある報告より後の時間帯を使って、ほかのテストの報告と重ならないようにする。
    with get_conn() as conn:
        latest = conn.execute("SELECT max(hub_received_at) AS latest FROM emergency_packets;").fetchone()["latest"]
    return max(latest or utc_now(), utc_now()).replace(microsecond=0) + timedelta(days=1)


def test_backfill_registers_only_missing_signed_v2(env, monkeypatch, caplog):
    destination = env.add_destination()
    base = _unique_window()

    # Outboxが無効の間に受理した報告(登録されない)
    monkeypatch.setenv("OUTBOX_ENABLED", "false")
    missing = post_packet(make_packet(status="CRITICAL"), hub_received_at=base + timedelta(seconds=10))
    before_window = post_packet(make_packet(), hub_received_at=base - timedelta(seconds=1))
    v1 = client.post(
        "/api/emergency-packets",
        json={
            "packet": f"v1|AIT001|12:{uuid4().int % 60:02d}|{920_000 + uuid4().int % 1000}|1|ALERT|NONE",
            "hub_received_at": (base + timedelta(seconds=11)).isoformat(),
        },
    ).json()
    assert outbox_rows(packet_id=missing["id"]) == []

    # 有効にしたあとに受理し、配送済みになった報告
    monkeypatch.setenv("OUTBOX_ENABLED", "true")
    registered = post_packet(make_packet(), hub_received_at=base + timedelta(seconds=20))
    run(FakeCloud(), due())
    accepted_before = outbox_rows(packet_id=registered["id"], destination_id=destination)
    assert accepted_before[0]["state"] == "ACCEPTED"

    # --since の境界: hub_received_at が指定時刻ちょうどなら対象、1ミリ秒後からなら対象外
    exact = base + timedelta(seconds=10)
    assert outbox_worker.backfill(destination, since=exact, dry_run=True) == 1
    assert outbox_worker.backfill(destination, since=exact + timedelta(milliseconds=1), dry_run=True) == 0

    # dry-run は登録しない
    caplog.set_level(logging.WARNING)
    assert outbox_worker.backfill(destination, since=base, dry_run=True) == 1
    assert outbox_rows(packet_id=missing["id"]) == []

    now = due()
    assert outbox_worker.backfill(destination, since=base, now=now) == 1
    rows = outbox_rows(packet_id=missing["id"], destination_id=destination)
    assert [(row["state"], row["attempts"], row["next_attempt_at"]) for row in rows] == [("PENDING", 0, now)]
    assert outbox_rows(packet_id=before_window["id"]) == []
    assert outbox_rows(packet_id=v1["id"]) == []
    # 既存の行(ACCEPTED)は変更しない
    assert outbox_rows(packet_id=registered["id"], destination_id=destination) == accepted_before

    # 冪等: 2回目は0件
    assert outbox_worker.backfill(destination, since=base) == 0
    assert len(outbox_rows(packet_id=missing["id"])) == 1

    # ログには件数だけ(Packetの内容は出さない)
    assert f"destination={destination}" in caplog.text
    assert "targets=1" in caplog.text and "registered=1" in caplog.text
    for packet in (missing, registered, before_window):
        assert packet["raw_packet"] not in caplog.text
        assert packet["install_id"] not in caplog.text

    # 登録した行は、ワーカーで配送される
    cloud = FakeCloud()
    run(cloud, now + timedelta(seconds=1))
    assert outbox_rows(packet_id=missing["id"], destination_id=destination)[0]["state"] == "ACCEPTED"


def test_backfill_all_targets_every_missing_signed_v2_report(env):
    first = env.add_destination()
    post_packet(make_packet())
    # 宛先を後から追加した: 既存の報告には、この宛先の行が無い
    added = env.add_destination()
    first_rows = outbox_rows(destination_id=first)
    with get_conn() as conn:
        expected = conn.execute(
            """
            SELECT count(*) AS count FROM emergency_packets p
            WHERE p.version = 'v2' AND p.signature_status = 'SIGNATURE_VALID'
              AND NOT EXISTS (SELECT 1 FROM delivery_outbox o
                              WHERE o.emergency_packet_id = p.id AND o.destination_id = %s);
            """,
            (added,),
        ).fetchone()["count"]
    assert expected >= 1

    assert outbox_worker.backfill(added, all_packets=True, dry_run=True) == expected
    assert outbox_worker.backfill(added, all_packets=True) == expected
    assert outbox_worker.backfill(added, all_packets=True) == 0
    with get_conn() as conn:
        v1_rows = conn.execute(
            """
            SELECT count(*) AS count FROM delivery_outbox o JOIN emergency_packets p ON p.id = o.emergency_packet_id
            WHERE o.destination_id = %s AND (p.version <> 'v2' OR p.signature_status IS DISTINCT FROM 'SIGNATURE_VALID');
            """,
            (added,),
        ).fetchone()["count"]
    assert v1_rows == 0
    # 追加した宛先への登録で、最初の宛先の行は変わらない
    assert first_rows == outbox_rows(destination_id=first)


def test_backfill_argument_errors(env, capsys):
    destination = env.add_destination()

    with pytest.raises(OutboxConfigError, match="not in OUTBOX_DESTINATIONS"):
        outbox_worker.backfill("not-configured", all_packets=True)
    assert outbox_worker.main(["backfill", "--destination", "not-configured", "--all"]) == 2

    with pytest.raises(OutboxConfigError, match="exactly one"):
        outbox_worker.backfill(destination)
    with pytest.raises(SystemExit) as no_scope:
        outbox_worker.main(["backfill", "--destination", destination])
    assert no_scope.value.code == 2
    with pytest.raises(SystemExit) as both_scopes:
        outbox_worker.main(["backfill", "--destination", destination, "--all", "--since", "2026-10-06T00:00:00Z"])
    assert both_scopes.value.code == 2

    # タイムゾーンの無い時刻は受け付けない
    assert outbox_worker.main(["backfill", "--destination", destination, "--since", "2026-10-06T00:00:00"]) == 2
    assert outbox_worker.main(["backfill", "--destination", destination, "--since", "yesterday"]) == 2

    capsys.readouterr()
    window = _unique_window().isoformat()
    assert outbox_worker.main(["backfill", "--destination", destination, "--since", window, "--dry-run"]) == 0
    assert capsys.readouterr().out.strip() == "targets: 0"


# ---- 時刻は使う時点で取り直す(レビュー対応) ----


class AdvancingClock:
    """テスト用の時計。advance() を呼ぶまで進まない(HTTPが遅い状況を、応答の中で進めて再現する)。"""

    def __init__(self, start: datetime):
        self.current = start

    def __call__(self) -> datetime:
        return self.current

    def advance(self, seconds: float) -> None:
        self.current += timedelta(seconds=seconds)


def run_with_clock(cloud: FakeCloud, clock: AdvancingClock, seed: int = 0) -> outbox_worker.RunSummary:
    with cloud.client() as http_client:
        return outbox_worker.run_once(clock=clock, http_client=http_client, rng=random.Random(seed))


def test_times_are_taken_when_used_and_not_at_the_start_of_the_cycle(env):
    destination = env.add_destination()
    for _ in range(3):
        post_packet(make_packet())
    t0 = due()
    clock = AdvancingClock(t0)
    seen = []

    def slow_cloud(request):
        # 送信中の行(SENDING)の取得時刻を記録してから、通信に20秒かかったことにする。
        sending = [row for row in outbox_rows(destination_id=destination) if row["state"] == "SENDING"]
        assert len(sending) == 1
        seen.append((clock(), sending[0]["last_attempt_at"], sending[0]["lease_until"]))
        clock.advance(20)
        return httpx.Response(201, json={"id": "EP-cloud"})

    run_with_clock(FakeCloud(slow_cloud), clock)

    assert len(seen) == 3
    for k, (claimed_at, last_attempt_at, lease_until) in enumerate(seen):
        assert claimed_at == t0 + timedelta(seconds=20 * k)
        assert last_attempt_at == claimed_at  # 送信の開始時
        assert lease_until == claimed_at + timedelta(seconds=60)  # 取得時から OUTBOX_LEASE_SECONDS(60)
    rows = sorted(outbox_rows(destination_id=destination), key=lambda row: row["last_attempt_at"])
    assert [row["accepted_at"] for row in rows] == [t0 + timedelta(seconds=20 * (k + 1)) for k in range(3)]
    assert all(row["lease_until"] is None for row in rows)
    attempted = [attempt["attempted_at"] for attempt in attempts_for(destination, "DELIVERY")]
    assert attempted == [t0 + timedelta(seconds=20 * k) for k in range(3)]  # 試行の時刻は送信の開始時
    with get_conn() as conn:
        synced = conn.execute(
            "SELECT cloud_synced_at FROM emergency_packets WHERE id = ANY(%s) ORDER BY cloud_synced_at;",
            ([row["emergency_packet_id"] for row in rows],),
        ).fetchall()
    assert [row["cloud_synced_at"] for row in synced] == [t0 + timedelta(seconds=20 * (k + 1)) for k in range(3)]


def test_next_attempt_at_is_counted_from_the_response_time(env):
    destination = env.add_destination()
    packet = post_packet(make_packet())
    t0 = due()
    clock = AdvancingClock(t0)

    def slow_failure(request):
        clock.advance(20)
        return httpx.Response(503, json={"detail": "error"})

    run_with_clock(FakeCloud(slow_failure), clock)

    row = outbox_rows(packet_id=packet["id"])[0]
    assert row["last_attempt_at"] == t0
    responded_at = t0 + timedelta(seconds=20)
    # 1回目のバックオフは 2.5〜5 秒。応答を受けた時刻から数える。
    assert responded_at + timedelta(seconds=2.5) <= row["next_attempt_at"] <= responded_at + timedelta(seconds=5)
    assert len(attempts_for(destination, "DELIVERY")) == 1


def test_fixed_now_still_means_a_fixed_clock(env):
    destination = env.add_destination()
    packet = post_packet(make_packet())
    t0 = due()

    run(FakeCloud(), t0)

    row = outbox_rows(packet_id=packet["id"])[0]
    assert row["accepted_at"] == row["last_attempt_at"] == t0
    assert attempts_for(destination, "DELIVERY")[0]["attempted_at"] == t0


# ---- 宛先URLの検証(レビュー対応) ----


@pytest.mark.parametrize(
    ("base_url", "expected"),
    [
        ("https://x.invalid", "https://x.invalid"),
        ("https://x.invalid/", "https://x.invalid"),
        ("http://127.0.0.1:8000", "http://127.0.0.1:8000"),
        ("https://x.invalid/tsunagu", "https://x.invalid/tsunagu"),
        ("https://x.invalid/tsunagu/", "https://x.invalid/tsunagu"),
        ("https://x.invalid/a/b-c_d.e~f/", "https://x.invalid/a/b-c_d.e~f"),
        ("https://[::1]:8443/base", "https://[::1]:8443/base"),
        ("HTTPS://x.invalid:443/base", "https://x.invalid:443/base"),
    ],
)
def test_valid_destination_urls_are_accepted_and_normalized(env, base_url, expected):
    env.add_destination(base_url)

    settings = load_outbox_settings()

    assert settings.destinations[0].base_url == expected


@pytest.mark.parametrize(
    ("base_url", "message"),
    [
        ("https://user:pw-secret@x.invalid", "username or password"),
        ("https://:pw-secret@x.invalid", "username or password"),
        ("https://user-secret@x.invalid/base", "username or password"),
        ("https://x.invalid?token=query-secret", "query or fragment"),
        ("https://x.invalid/base?token=query-secret", "query or fragment"),
        ("https://x.invalid/base?", "query or fragment"),
        ("https://x.invalid/base#frag-secret", "query or fragment"),
        ("https://x.invalid#", "query or fragment"),
        ("ftp://x.invalid/base", "http(s) URL"),
        ("file:///etc/passwd", "http(s) URL"),
        ("javascript:alert(1)", "http(s) URL"),
        ("x.invalid/base", "http(s) URL"),
        ("https:///base", "http(s) URL"),
        ("https://x.invalid:port-secret/", "http(s) URL"),
        ("https://x.invalid:99999/", "http(s) URL"),
        ("https://x.invalid/ba se", "http(s) URL"),
        ("https://x.invalid/ba\\se", "http(s) URL"),
        ("https://x.invalid/ba\tse", "http(s) URL"),
        ("https://x.invalid/ベース", "http(s) URL"),
        ("https://x.invalid/../admin", "path must be a plain base path"),
        ("https://x.invalid/base/../admin", "path must be a plain base path"),
        ("https://x.invalid/base/./x", "path must be a plain base path"),
        ("https://x.invalid/base/..", "path must be a plain base path"),
        ("https://x.invalid/base//x", "path must be a plain base path"),
        ("https://x.invalid//", "path must be a plain base path"),
        ("https://x.invalid//base", "path must be a plain base path"),
        ("https://x.invalid/%2e%2e/admin", "path must be a plain base path"),
        ("https://x.invalid/a%2Fb", "path must be a plain base path"),
        ("https://x.invalid/a;b", "path must be a plain base path"),
    ],
)
def test_invalid_destination_urls_are_rejected_without_echoing_the_value(env, base_url, message):
    import traceback

    env.add_destination(base_url)

    with pytest.raises(OutboxConfigError) as excinfo:
        load_outbox_settings()

    assert "OUTBOX_DESTINATIONS[0].base_url" in str(excinfo.value)
    assert message in str(excinfo.value)
    # エラーのメッセージにも、例外のつながり(原因)にも、URLの値を出さない
    texts = [str(excinfo.value), repr(excinfo.value), "".join(traceback.format_exception(excinfo.value))]
    for text in texts:
        for secret in ("pw-secret", "query-secret", "frag-secret", "user-secret", "port-secret", base_url):
            assert secret not in text


def test_base_path_is_kept_in_requests_without_double_slashes(env):
    destination = env.add_destination("https://cloud.invalid/tsunagu/")
    post_packet(make_packet())
    cloud = FakeCloud()

    run(cloud, due())

    assert [request.url.path for request in cloud.deliveries] == ["/tsunagu/api/emergency-packets"]
    assert [request.url.path for request in cloud.probes] == ["/tsunagu/health"]
    assert attempts_for(destination, "DELIVERY")[0]["outcome"] == "ACCEPTED"
