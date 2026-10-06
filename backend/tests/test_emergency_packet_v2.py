"""Emergency Packet v2 の受信API(署名検証・重複判定・時刻・v1切り替え)のテスト。

鍵はすべてテスト専用のダミー値。実際の端末鍵は使わない。
"""

import concurrent.futures
import json
import logging
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

import app.main as main_module
from app.db import get_conn
from app.emergency_packet import compute_packet_hmac
from app.main import app

# テスト専用のダミー鍵(32バイト)。
TB001_KEY = bytes(range(0, 32))
TB002_KEY = bytes(range(32, 64))
TB003_KEY = bytes(range(64, 96))
ALL_TEST_KEYS = [TB001_KEY, TB002_KEY, TB003_KEY]

client = TestClient(app)


@pytest.fixture(autouse=True)
def packet_environment(monkeypatch):
    monkeypatch.setenv(
        "PACKET_DEVICE_KEYS",
        json.dumps(
            {
                "TB001": {"01": TB001_KEY.hex()},
                "TB002": {"01": TB002_KEY.hex()},
                "TB003": {"01": TB003_KEY.hex()},
            }
        ),
    )
    monkeypatch.delenv("PACKET_DEVICE_KEYS_FILE", raising=False)
    monkeypatch.setenv("PACKET_DISABLED_DEVICES", "TB003")
    monkeypatch.setenv("ALLOW_V1_PACKETS", "true")
    client.cookies.clear()
    client.headers["X-Gateway-Key"] = "test-gateway-key"
    yield
    client.headers.pop("X-Gateway-Key", None)
    client.headers.pop("X-CSRF-Token", None)
    client.cookies.clear()


def new_install_id() -> str:
    # 実行ごとにinstall_idを変えて、DBに残った過去のテストの行と衝突しないようにする。
    return uuid4().hex[:16].upper()


def make_packet(
    *,
    device_id: str = "TB001",
    key_id: str = "01",
    install_id: str | None = None,
    sequence: str = "0000002A",
    reported_at: int | None = None,
    shelter_code: str = "AIT001",
    people_count: int = 170,
    water_stock: int = 18,
    status: str = "WARNING",
    request_code: str = "REQ_WATER",
    key: bytes = TB001_KEY,
) -> str:
    if install_id is None:
        install_id = new_install_id()
    if reported_at is None:
        reported_at = int(datetime.now(timezone.utc).timestamp())
    payload = "|".join(
        [
            "v2",
            device_id,
            key_id,
            install_id,
            sequence,
            str(reported_at),
            shelter_code,
            str(people_count),
            str(water_stock),
            status,
            request_code,
        ]
    )
    return f"{payload}|{compute_packet_hmac(key, payload)}"


def install_id_of(packet: str) -> str:
    return packet.split("|")[3]


def post_packet(packet: str, hub_received_at: datetime | None = None):
    body = {"packet": packet}
    if hub_received_at is not None:
        body["hub_received_at"] = hub_received_at.isoformat()
    return client.post("/api/emergency-packets", json=body)


def packets_for(install_id: str) -> list[dict]:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM emergency_packets WHERE install_id = %s ORDER BY sequence, device_id;",
            (install_id,),
        ).fetchall()


def observations_for(install_id: str) -> list[dict]:
    with get_conn() as conn:
        return conn.execute(
            """
            SELECT o.* FROM observations o
            JOIN emergency_packets p ON p.observation_id = o.id
            WHERE p.install_id = %s;
            """,
            (install_id,),
        ).fetchall()


def report_counts() -> tuple[int, int]:
    with get_conn() as conn:
        return (
            conn.execute("SELECT count(*) AS count FROM emergency_packets;").fetchone()["count"],
            conn.execute("SELECT count(*) AS count FROM observations;").fetchone()["count"],
        )


def security_events_for(install_id: str) -> list[dict]:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM packet_security_events WHERE install_id = %s ORDER BY created_at;",
            (install_id,),
        ).fetchall()


def test_valid_v2_packet_is_accepted_with_signature_valid():
    reported_at = int(datetime.now(timezone.utc).timestamp())
    packet = make_packet(reported_at=reported_at, status="CRITICAL", request_code="REQ_RESCUE")
    hub_received_at = datetime.fromtimestamp(reported_at + 30, tz=timezone.utc)

    response = post_packet(packet, hub_received_at)

    assert response.status_code == 201
    body = response.json()
    assert body["signature_status"] == "SIGNATURE_VALID"
    assert body["time_trust"] == "TRUSTED"
    assert body["device_id"] == "TB001"
    assert body["key_id"] == "01"
    assert body["install_id"] == install_id_of(packet)
    assert body["sequence"] == "0000002A"
    assert body["raw_packet"] == packet
    assert body["cloud_synced_at"] is None
    assert datetime.fromisoformat(body["reported_at"]).timestamp() == reported_at
    assert datetime.fromisoformat(body["hub_received_at"]) == hub_received_at

    observations = observations_for(install_id_of(packet))
    assert len(observations) == 1
    observation = observations[0]
    assert observation["id"] == body["observation_id"]
    assert observation["signature_status"] == "SIGNATURE_VALID"
    # 署名が正しくても、本部職員による確認状態は自動で VERIFIED にしない。
    assert observation["verification_status"] == "UNVERIFIED"
    assert observation["urgency"] == "CRITICAL"
    assert observation["observed_at"].timestamp() == reported_at


def test_hub_received_at_defaults_to_server_receive_time(monkeypatch):
    server_now = datetime.now(timezone.utc).replace(microsecond=0)
    monkeypatch.setattr(main_module, "_current_utc_time", lambda: server_now)
    packet = make_packet(reported_at=int(server_now.timestamp()))

    response = post_packet(packet)

    assert response.status_code == 201
    assert datetime.fromisoformat(response.json()["hub_received_at"]) == server_now


def _tamper_people_count(packet: str) -> str:
    parts = packet.split("|")
    parts[7] = str(int(parts[7]) + 1)
    return "|".join(parts)


def _tamper_hmac(packet: str) -> str:
    last = packet[-1]
    return packet[:-1] + ("0" if last != "0" else "1")


@pytest.mark.parametrize(
    ("build", "reason"),
    [
        (lambda: _tamper_people_count(make_packet(status="CRITICAL")), "HMAC_MISMATCH"),
        (lambda: _tamper_hmac(make_packet(status="CRITICAL")), "HMAC_MISMATCH"),
        (lambda: make_packet(device_id="TB999", status="CRITICAL"), "UNKNOWN_DEVICE"),
        (lambda: make_packet(device_id="TB003", key=TB003_KEY, status="CRITICAL"), "DEVICE_DISABLED"),
        (lambda: make_packet(key_id="02", status="CRITICAL"), "UNKNOWN_KEY_ID"),
        (lambda: make_packet(device_id="TB001", key=TB002_KEY, status="CRITICAL"), "HMAC_MISMATCH"),
    ],
    ids=["tampered-body", "tampered-hmac", "unknown-device", "disabled-device", "unknown-key-id", "other-device-key"],
)
def test_unauthenticated_v2_packet_is_rejected_and_not_reported(build, reason):
    packet = build()
    install_id = install_id_of(packet)
    counts_before = report_counts()

    response = post_packet(packet)

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "PACKET_AUTH_FAILED"
    # 失敗理由はレスポンスに出さない(監査ログでだけ区別する)。
    assert reason not in response.text
    assert packets_for(install_id) == []
    assert report_counts() == counts_before
    events = security_events_for(install_id)
    assert len(events) == 1
    assert events[0]["event_type"] == "PACKET_AUTH_FAILED"
    assert events[0]["reason"] == reason
    assert events[0]["raw_packet"] == packet


def test_invalid_gateway_key_is_401_not_packet_auth_failure():
    client.headers["X-Gateway-Key"] = "wrong-gateway-key"
    response = post_packet(make_packet())
    assert response.status_code == 401
    assert "PACKET_AUTH_FAILED" not in response.text


@pytest.mark.parametrize(
    "packet",
    [
        "v2|TB001|01|A1B2C3D4E5F60718|0000002A|1791234567|AIT001|170|18|WARNING|REQ_WATER",
        "v2|tb001|01|A1B2C3D4E5F60718|0000002A|1791234567|AIT001|170|18|WARNING|REQ_WATER|" + "0" * 32,
        "v2|TB001|01|A1B2C3D4E5F60718|0000002A|1791234567|AIT001|1000001|18|WARNING|REQ_WATER|" + "0" * 32,
    ],
    ids=["missing-field", "lowercase-device", "people-out-of-range"],
)
def test_malformed_v2_packet_is_400_before_hmac_check(packet):
    response = post_packet(packet)

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "PACKET_FORMAT_INVALID"
    # 形式検証で止まるので、認証失敗としては記録されない。
    assert security_events_for("A1B2C3D4E5F60718") == []


def test_resent_v2_packet_is_stored_once():
    packet = make_packet()

    first = post_packet(packet)
    second = post_packet(packet, datetime.now(timezone.utc) + timedelta(seconds=40))

    assert first.status_code == second.status_code == 201
    assert first.json() == second.json()
    assert len(packets_for(install_id_of(packet))) == 1
    assert len(observations_for(install_id_of(packet))) == 1


def test_concurrent_resend_of_v2_packet_is_stored_once():
    packet = make_packet()

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        responses = list(executor.map(lambda _: post_packet(packet), range(5)))

    assert all(response.status_code == 201 for response in responses)
    assert len({response.json()["id"] for response in responses}) == 1
    assert len(packets_for(install_id_of(packet))) == 1
    assert len(observations_for(install_id_of(packet))) == 1


def test_same_content_with_different_sequence_is_stored_twice():
    install_id = new_install_id()
    reported_at = int(datetime.now(timezone.utc).timestamp())

    first = post_packet(make_packet(install_id=install_id, sequence="00000001", reported_at=reported_at))
    second = post_packet(make_packet(install_id=install_id, sequence="00000002", reported_at=reported_at))

    assert first.status_code == second.status_code == 201
    assert first.json()["id"] != second.json()["id"]
    assert len(packets_for(install_id)) == 2
    assert len(observations_for(install_id)) == 2


def test_same_sequence_from_different_devices_are_separate_reports():
    install_id = new_install_id()

    first = post_packet(make_packet(device_id="TB001", key=TB001_KEY, install_id=install_id))
    second = post_packet(make_packet(device_id="TB002", key=TB002_KEY, install_id=install_id))

    assert first.status_code == second.status_code == 201
    assert first.json()["id"] != second.json()["id"]
    assert [row["device_id"] for row in packets_for(install_id)] == ["TB001", "TB002"]
    assert len(observations_for(install_id)) == 2


def test_same_key_with_different_content_is_409_and_not_overwritten():
    install_id = new_install_id()
    original = make_packet(install_id=install_id, people_count=170)
    conflicting = make_packet(install_id=install_id, people_count=999, status="CRITICAL")

    first = post_packet(original)
    second = post_packet(conflicting)

    assert first.status_code == 201
    assert second.status_code == 409
    assert second.json()["detail"]["code"] == "PACKET_DUPLICATE_CONFLICT"
    rows = packets_for(install_id)
    assert len(rows) == 1
    assert rows[0]["raw_packet"] == original
    assert rows[0]["people_count"] == 170
    observations = observations_for(install_id)
    assert len(observations) == 1
    assert observations[0]["people_count"] == 170
    events = security_events_for(install_id)
    assert len(events) == 1
    assert events[0]["event_type"] == "PACKET_DUPLICATE_CONFLICT"
    assert events[0]["raw_packet"] == conflicting
    assert events[0]["existing_packet_id"] == first.json()["id"]


def test_out_of_order_arrival_is_stored():
    install_id = new_install_id()
    base = int(datetime.now(timezone.utc).timestamp())

    later = post_packet(make_packet(install_id=install_id, sequence="0000002B", reported_at=base + 60))
    earlier = post_packet(make_packet(install_id=install_id, sequence="0000002A", reported_at=base))

    assert later.status_code == earlier.status_code == 201
    assert [row["sequence"] for row in packets_for(install_id)] == ["0000002A", "0000002B"]


def test_time_skew_over_600_seconds_is_untrusted_and_uses_hub_time():
    hub_received_at = datetime.now(timezone.utc).replace(microsecond=0)
    packet = make_packet(reported_at=int(hub_received_at.timestamp()) - 601)

    response = post_packet(packet, hub_received_at)

    assert response.status_code == 201
    assert response.json()["time_trust"] == "UNTRUSTED"
    observation = observations_for(install_id_of(packet))[0]
    assert observation["observed_at"] == hub_received_at


def test_time_skew_of_exactly_600_seconds_is_trusted():
    hub_received_at = datetime.now(timezone.utc).replace(microsecond=0)
    reported_at = int(hub_received_at.timestamp()) + 600
    packet = make_packet(reported_at=reported_at)

    response = post_packet(packet, hub_received_at)

    assert response.status_code == 201
    assert response.json()["time_trust"] == "TRUSTED"
    assert observations_for(install_id_of(packet))[0]["observed_at"].timestamp() == reported_at


def test_v2_packet_for_unknown_shelter_is_stored_without_observation():
    packet = make_packet(shelter_code="ZZZ999")

    response = post_packet(packet)

    assert response.status_code == 201
    assert response.json()["shelter_id"] is None
    assert response.json()["observation_id"] is None


def test_v1_packet_is_rejected_when_disabled(monkeypatch):
    monkeypatch.setenv("ALLOW_V1_PACKETS", "false")
    packet = f"v1|AIT001|09:{uuid4().int % 60:02d}|{700_000 + uuid4().int % 1000}|11|ALERT|REQ_FOOD"

    response = post_packet(packet)

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "PACKET_VERSION_DISABLED"
    with get_conn() as conn:
        assert conn.execute(
            "SELECT count(*) AS count FROM emergency_packets WHERE raw_packet = %s;", (packet,)
        ).fetchone()["count"] == 0


def test_v1_packet_is_disabled_by_default(monkeypatch):
    monkeypatch.delenv("ALLOW_V1_PACKETS", raising=False)
    response = post_packet("v1|AIT001|21:04|170|18|WARNING|REQ_WATER")
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "PACKET_VERSION_DISABLED"


def test_v1_packet_is_accepted_as_unsigned_when_enabled():
    people_count = 800_000 + uuid4().int % 100_000
    packet = f"v1|AIT001|09:{uuid4().int % 60:02d}|{people_count}|11|ALERT|REQ_FOOD"

    response = post_packet(packet)

    assert response.status_code == 201
    assert response.json()["signature_status"] == "UNSIGNED_V1"
    assert response.json()["hub_received_at"] is not None
    with get_conn() as conn:
        observation = conn.execute(
            "SELECT * FROM observations WHERE people_count = %s AND source = 'emergency_packet';",
            (people_count,),
        ).fetchone()
    assert observation["signature_status"] == "UNSIGNED_V1"
    assert observation["verification_status"] == "UNVERIFIED"


def test_keys_do_not_appear_in_logs_or_responses(caplog):
    caplog.set_level(logging.DEBUG)
    install_id = new_install_id()
    responses = [
        post_packet(make_packet(install_id=install_id)),
        post_packet(make_packet(install_id=install_id)),
        post_packet(make_packet(install_id=install_id, people_count=1)),
        post_packet(make_packet(install_id=install_id, sequence="00000001", key=TB002_KEY)),
        post_packet(make_packet(device_id="TB003", key=TB003_KEY)),
    ]
    assert [response.status_code for response in responses] == [201, 201, 409, 403, 403]

    login = client.post("/api/auth/dev-login", json={"role": "hq", "name": "Test HQ"})
    assert login.status_code == 204
    listing = client.get("/api/emergency-packets")
    assert listing.status_code == 200

    texts = [caplog.text, listing.text, *(response.text for response in responses)]
    for key in ALL_TEST_KEYS:
        for text in texts:
            assert key.hex() not in text
            assert key.hex().upper() not in text


def test_misconfigured_key_ledger_does_not_leak_key(monkeypatch, caplog):
    broken_key = "ab" * 16 + "zz"  # 16進でない文字を含む
    monkeypatch.setenv("PACKET_DEVICE_KEYS", json.dumps({"TB001": {"01": broken_key}}))
    caplog.set_level(logging.DEBUG)

    response = post_packet(make_packet())

    assert response.status_code == 503
    assert broken_key not in response.text
    assert broken_key not in caplog.text
