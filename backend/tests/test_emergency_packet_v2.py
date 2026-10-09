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
from app.config import validate_runtime_settings
from app.main import app
from app.packet_keys import PacketKeyConfigError, load_device_key_registry

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
    # 1件目と2件目は同じ報告の再送なので、reported_at を1つに固定する。
    # 別々に現在時刻から作ると、その間に秒が切り替わったときに内容が変わり、409 になってしまう。
    reported_at = int(datetime.now(timezone.utc).timestamp())
    responses = [
        post_packet(make_packet(install_id=install_id, reported_at=reported_at)),
        post_packet(make_packet(install_id=install_id, reported_at=reported_at)),
        post_packet(make_packet(install_id=install_id, reported_at=reported_at, people_count=1)),
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


# ---- 鍵の長さ(機器ごとの32バイトの乱数鍵) ----


def _ledger_with_key(length: int) -> tuple[str, str]:
    # テスト専用のダミー鍵。長さだけを変える。
    key_hex = bytes((100 + index) % 256 for index in range(length)).hex()
    return json.dumps({"TB001": {"01": key_hex}}), key_hex


def test_32_byte_key_is_accepted(monkeypatch):
    ledger, key_hex = _ledger_with_key(32)
    monkeypatch.setenv("PACKET_DEVICE_KEYS", ledger)

    validate_runtime_settings()
    assert load_device_key_registry().lookup("TB001", "01") == bytes.fromhex(key_hex)


@pytest.mark.parametrize("length", [16, 31, 33])
def test_key_that_is_not_32_bytes_fails_at_startup(monkeypatch, caplog, length):
    ledger, key_hex = _ledger_with_key(length)
    monkeypatch.setenv("PACKET_DEVICE_KEYS", ledger)
    caplog.set_level(logging.DEBUG)

    with pytest.raises(PacketKeyConfigError) as excinfo:
        validate_runtime_settings()

    message = str(excinfo.value)
    assert message == "Key TB001/01 must be exactly 32 bytes (64 hex characters)"
    assert key_hex not in message
    assert key_hex not in caplog.text


@pytest.mark.parametrize("length", [16, 31, 33])
def test_key_that_is_not_32_bytes_is_rejected_at_runtime_without_leaking(monkeypatch, caplog, length):
    ledger, key_hex = _ledger_with_key(length)
    monkeypatch.setenv("PACKET_DEVICE_KEYS", ledger)
    # テストの準備で alembic の fileConfig が app.main のロガーを無効にするので、このテストの間だけ有効にする
    # (空のログを調べるだけのテストにしないため)。
    monkeypatch.setattr(logging.getLogger("app.main"), "disabled", False)
    caplog.set_level(logging.DEBUG)

    response = post_packet(make_packet(key=bytes.fromhex(key_hex)))

    assert response.status_code == 503
    assert key_hex not in response.text
    assert "Emergency Packet device key ledger is misconfigured" in caplog.text
    assert key_hex not in caplog.text


# ---- 同時再送(主キーの衝突) ----

CONCURRENT_THREADS = 8
CONCURRENT_ROUNDS = 25


def test_simultaneous_resends_return_existing_row_without_500():
    """同じ v2 Packet を複数のスレッドから同時に送っても、すべて 201 で同じ行を返し、1件だけ保存される。"""
    import hashlib
    import threading

    # サーバー側の例外を 500 の応答として受け取る(テストのスレッドで例外にしない)。
    concurrent_client = TestClient(app, raise_server_exceptions=False)
    concurrent_client.headers["X-Gateway-Key"] = "test-gateway-key"
    install_id = new_install_id()
    reported_at = int(datetime.now(timezone.utc).timestamp())
    barrier = threading.Barrier(CONCURRENT_THREADS)
    results: list[list[tuple[int, str]]] = []

    for round_index in range(CONCURRENT_ROUNDS):
        packet = make_packet(install_id=install_id, sequence=f"{round_index:08X}", reported_at=reported_at)
        round_results: list[tuple[int, str]] = []
        lock = threading.Lock()

        def send(packet=packet, round_results=round_results, lock=lock):
            barrier.wait(timeout=10)  # 全スレッドを同時に始める
            response = concurrent_client.post("/api/emergency-packets", json={"packet": packet})
            body = response.json() if response.status_code == 201 else {}
            with lock:
                round_results.append((response.status_code, body.get("id", "")))

        threads = [threading.Thread(target=send) for _ in range(CONCURRENT_THREADS)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
        # Barrier が壊れたり、スレッドが終わらなかったりしたときに、黙って通らないようにする。
        assert not any(thread.is_alive() for thread in threads)
        assert len(round_results) == CONCURRENT_THREADS
        results.append(round_results)

    statuses = [status for round_results in results for status, _ in round_results]
    assert statuses.count(500) == 0
    assert set(statuses) == {201}
    for round_index, round_results in enumerate(results):
        dedup_key = f"v2|TB001|{install_id}|{round_index:08X}"
        expected_id = f"EP-{hashlib.sha256(dedup_key.encode()).hexdigest()[:16]}"
        assert {packet_id for _, packet_id in round_results} == {expected_id}

    rows = packets_for(install_id)
    assert len(rows) == CONCURRENT_ROUNDS
    with get_conn() as conn:
        observation_count = conn.execute(
            "SELECT count(*) AS count FROM observations WHERE client_event_id = ANY(%s);",
            ([f"LORA-{row['id']}" for row in rows],),
        ).fetchone()["count"]
    # 余分な観測が無い(1件の報告に1件の観測)
    assert observation_count == CONCURRENT_ROUNDS
    assert len(observations_for(install_id)) == CONCURRENT_ROUNDS


def test_conflict_without_existing_row_is_500_and_logged(monkeypatch, caplog):
    """衝突を吸収したのに既存の行が見つからないときは、黙って捨てずに 500 にしてログを残す。"""
    import hashlib

    # テストの準備で alembic の fileConfig が app.main のロガーを無効にするので、このテストの間だけ有効にする。
    monkeypatch.setattr(logging.getLogger("app.main"), "disabled", False)
    caplog.set_level(logging.DEBUG)
    error_client = TestClient(app, raise_server_exceptions=False)
    error_client.headers["X-Gateway-Key"] = "test-gateway-key"
    install_id = new_install_id()
    packet = make_packet(install_id=install_id, sequence="0000ABCD")
    packet_id = f"EP-{hashlib.sha256(f'v2|TB001|{install_id}|0000ABCD'.encode()).hexdigest()[:16]}"
    # 同じ id の、別の行(重複判定キーは NULL)を先に入れて、id だけが重なる状態を作る。
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO emergency_packets (id, version, shelter_code, packet_time, people_count, water_stock,
                                           status, request_code, raw_packet)
            VALUES (%s, 'v1', 'AIT001', '00:00', 0, 0, 'NORMAL', 'NONE', 'placeholder-row');
            """,
            (packet_id,),
        )
        conn.commit()
    observations_before = len(observations_for(install_id))

    response = error_client.post("/api/emergency-packets", json={"packet": packet})

    assert response.status_code == 500
    assert packets_for(install_id) == []
    assert len(observations_for(install_id)) == observations_before
    assert "insert conflicted but no existing row was found" in caplog.text
    assert f"packet_id={packet_id}" in caplog.text
    # ログと応答に、鍵や本文(raw packet)は出さない
    for text in (caplog.text, response.text):
        assert packet not in text
        assert TB001_KEY.hex() not in text


# ---- ログを確かめるテストの準備 ----


def _enable_app_logs(monkeypatch, caplog):
    # テストの準備で alembic の fileConfig が app.main のロガーを無効にするので、このテストの間だけ有効にする。
    monkeypatch.setattr(logging.getLogger("app.main"), "disabled", False)
    caplog.set_level(logging.DEBUG)


# ---- 未登録の避難所コード ----


def test_unregistered_shelter_is_accepted_with_warning(monkeypatch, caplog):
    _enable_app_logs(monkeypatch, caplog)
    packet = make_packet(shelter_code="ZZZ999")

    first = post_packet(packet)
    resent = post_packet(packet)

    for response in (first, resent):
        assert response.status_code == 201
        body = response.json()
        assert body["warnings"] == ["SHELTER_NOT_REGISTERED"]
        assert body["observation_created"] is False
        assert body["shelter_registered"] is False
        assert body["shelter_id"] is None and body["observation_id"] is None
    assert first.json()["id"] == resent.json()["id"]

    # 受理したときに WARNING を1回だけ出す(再送では出さない)。鍵と本文は出さない。
    warnings = [r for r in caplog.records if "unregistered shelter" in r.getMessage()]
    assert len(warnings) == 1 and warnings[0].levelno == logging.WARNING
    message = warnings[0].getMessage()
    assert "shelter_code=ZZZ999" in message and "device_id=TB001" in message
    assert f"packet_id={first.json()['id']}" in message
    for key in ALL_TEST_KEYS:
        assert key.hex() not in caplog.text
    assert packet not in caplog.text


def test_registered_shelter_has_no_warning():
    packet = make_packet(shelter_code="AIT001")

    for response in (post_packet(packet), post_packet(packet)):
        assert response.status_code == 201
        body = response.json()
        assert body["warnings"] == []
        assert body["observation_created"] is True
        assert body["shelter_registered"] is True


def test_v1_response_has_no_v2_flags():
    response = post_packet(f"v1|ZZZ999|08:{uuid4().int % 60:02d}|{930_000 + uuid4().int % 1000}|1|NORMAL|NONE")
    assert response.status_code == 201
    body = response.json()
    # v1 の経路は変えていない(警告の項目は null)
    assert body["warnings"] is None and body["observation_created"] is None


def test_packet_list_flags_unregistered_shelter():
    unregistered = post_packet(make_packet(shelter_code="ZZZ998")).json()
    registered = post_packet(make_packet(shelter_code="AIT002")).json()
    login = client.post("/api/auth/dev-login", json={"role": "hq", "name": "Test HQ"})
    assert login.status_code == 204

    listing = client.get("/api/emergency-packets")

    assert listing.status_code == 200
    by_id = {item["id"]: item for item in listing.json()}
    assert by_id[unregistered["id"]]["shelter_registered"] is False
    assert by_id[registered["id"]]["shelter_registered"] is True
    # 一覧の応答は、POST 用の警告の項目を持たない(既存の項目は変えない)
    assert "warnings" not in by_id[registered["id"]]


# ---- 起動時のログ ----


@pytest.mark.parametrize(
    ("allow_v1", "app_env", "ledger", "expected_info", "expected_warnings"),
    [
        ("true", "development", {"TB001": {"01": TB001_KEY.hex(), "02": TB002_KEY.hex()}},
         ["Emergency Packet v1: allowed", "devices=1 keys=2 disabled=0"], []),
        (None, "development", {"TB001": {"01": TB001_KEY.hex()}},
         ["Emergency Packet v1: rejected", "devices=1 keys=1"], []),
        ("false", "development", {}, ["Emergency Packet v1: rejected", "devices=0 keys=0"],
         ["device ledger is empty"]),
        ("true", "production", {"TB001": {"01": TB001_KEY.hex()}}, ["Emergency Packet v1: allowed"],
         ["v1 is allowed in production"]),
    ],
    ids=["dev-v1-allowed", "default-v1-rejected", "empty-ledger", "production-v1-allowed"],
)
def test_startup_logs_packet_settings(monkeypatch, caplog, allow_v1, app_env, ledger, expected_info, expected_warnings):
    _enable_app_logs(monkeypatch, caplog)
    if allow_v1 is None:
        monkeypatch.delenv("ALLOW_V1_PACKETS", raising=False)
    else:
        monkeypatch.setenv("ALLOW_V1_PACKETS", allow_v1)
    monkeypatch.setenv("APP_ENV", app_env)
    monkeypatch.setenv("PACKET_DEVICE_KEYS", json.dumps(ledger))
    monkeypatch.setenv("PACKET_DISABLED_DEVICES", "")

    main_module.log_packet_settings()

    infos = " | ".join(r.getMessage() for r in caplog.records if r.levelno == logging.INFO)
    warnings = " | ".join(r.getMessage() for r in caplog.records if r.levelno == logging.WARNING)
    for text in expected_info:
        assert text in infos
    for text in expected_warnings:
        assert text in warnings
    if not expected_warnings:
        assert warnings == ""
    for key in ALL_TEST_KEYS:
        assert key.hex() not in caplog.text
