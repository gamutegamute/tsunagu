from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def authenticated_hq_client():
    client.cookies.clear()
    login = client.post("/api/auth/dev-login", json={"role": "hq", "name": "Test HQ"})
    assert login.status_code == 204
    client.headers["X-CSRF-Token"] = client.cookies.get("tsunagu_csrf")
    client.headers["X-Gateway-Key"] = "test-gateway-key"
    yield
    client.headers.pop("X-CSRF-Token", None)
    client.headers.pop("X-Gateway-Key", None)
    client.cookies.clear()


def observation_payload(**overrides):
    payload = {
        "shelter_id": "AIT001",
        "client_event_id": str(uuid4()),
        "people_count": 120,
        "water_stock": 50,
        "urgency": "NORMAL",
        "memo": "Test memo",
        "reporter_name": "Test Reporter",
        "source": "web",
    }
    payload.update(overrides)
    return payload


def create_observation(**overrides) -> dict:
    response = client.post("/api/observations", json=observation_payload(**overrides))
    assert response.status_code == 201
    return response.json()


def login_as(role: str, name: str = "Test User") -> None:
    client.cookies.clear()
    login = client.post("/api/auth/dev-login", json={"role": role, "name": name})
    assert login.status_code == 204
    client.headers["X-CSRF-Token"] = client.cookies.get("tsunagu_csrf")


def test_list_incidents_requires_hq_auth():
    client.cookies.clear()
    response = client.get("/api/incidents")
    assert response.status_code == 401


def test_list_incidents_includes_observations_with_memo():
    observation = create_observation(memo="水が足りません")

    response = client.get("/api/incidents")

    assert response.status_code == 200
    incident_ids = [item["id"] for item in response.json()]
    assert observation["id"] in incident_ids


def test_list_incidents_excludes_observations_without_memo():
    observation = create_observation(memo="")

    response = client.get("/api/incidents")

    incident_ids = [item["id"] for item in response.json()]
    assert observation["id"] not in incident_ids


def test_list_incidents_excludes_emergency_packet_source():
    packet = "v1|AIT001|21:04|170|18|WARNING|REQ_WATER"
    packet_response = client.post("/api/emergency-packets", json={"packet": packet})
    assert packet_response.status_code == 201

    response = client.get("/api/incidents")

    # LoRa Emergency Packet由来のobservationは、合成memoが入っていても除外されること
    memos = [item["memo"] for item in response.json()]
    assert not any("LoRa" in memo for memo in memos)


def test_list_incidents_does_not_collapse_to_latest_per_shelter():
    """決定事項34-a: 同じ避難所で複数のメモ入り報告があっても、両方とも一覧に残ること。

    GET /api/dashboardは避難所ごとの最新1件のみを返すため、2件目の報告が来た瞬間に
    1件目のIncidentが一覧から消えてしまう問題があった。GET /api/incidentsではその
    問題を解消し、メモがある限り両方とも返す。
    """
    first = create_observation(memo="1件目のインシデント", observed_at="2026-08-06T01:00:00Z")
    second = create_observation(memo="2件目のインシデント(同じ避難所)", observed_at="2026-08-06T02:00:00Z")

    response = client.get("/api/incidents")

    incident_ids = [item["id"] for item in response.json()]
    assert first["id"] in incident_ids
    assert second["id"] in incident_ids


def test_list_incidents_excludes_from_incidents_when_latest_report_has_no_memo():
    """メモなしの新しい報告が来ても、以前のメモ入りIncident自体は一覧に残り続けること
    (GET /api/dashboardの「最新1件のみ」ロジックとは独立していることの確認)。"""
    incident = create_observation(memo="対応が必要な状況", observed_at="2026-08-06T01:00:00Z")
    create_observation(memo="", observed_at="2026-08-06T02:00:00Z")

    response = client.get("/api/incidents")

    incident_ids = [item["id"] for item in response.json()]
    assert incident["id"] in incident_ids


def test_list_incidents_orders_by_observed_at_descending():
    first = create_observation(memo="古い方", observed_at="2026-08-06T01:00:00Z")
    second = create_observation(memo="新しい方", observed_at="2026-08-06T03:00:00Z")

    response = client.get("/api/incidents")

    incident_ids = [item["id"] for item in response.json()]
    assert incident_ids.index(second["id"]) < incident_ids.index(first["id"])


def test_list_incidents_defaults_state_when_no_incident_state_row_exists():
    observation = create_observation(memo="状態未設定のインシデント")

    response = client.get("/api/incidents")

    incident = next(item for item in response.json() if item["id"] == observation["id"])
    assert incident["state"]["confirm_status"] == "UNCONFIRMED"
    assert incident["state"]["confirmed_by"] is None
    assert incident["state"]["resolution_memo"] is None


def test_confirm_incident_sets_confirmed_state():
    observation = create_observation(memo="確認対象のインシデント")

    response = client.post(
        f"/api/incidents/{observation['id']}/confirm",
        json={"approver_name": "本部 太郎", "memo": "現場に確認済み"},
    )

    assert response.status_code == 200
    state = response.json()["state"]
    assert state["confirm_status"] == "CONFIRMED"
    assert state["confirmed_by"] == "本部 太郎"
    assert state["confirm_memo"] == "現場に確認済み"
    assert state["confirmed_at"] is not None


def test_confirm_incident_requires_hq():
    observation = create_observation(memo="権限確認用")
    login_as("field")

    response = client.post(
        f"/api/incidents/{observation['id']}/confirm",
        json={"approver_name": "現場 花子", "memo": ""},
    )

    assert response.status_code == 403


def test_confirm_incident_404_for_unknown_observation():
    response = client.post(
        "/api/incidents/OBS-does-not-exist/confirm",
        json={"approver_name": "本部 太郎", "memo": ""},
    )

    assert response.status_code == 404


def test_resolve_incident_directly_sets_resolution():
    observation = create_observation(memo="直接対応済みにするインシデント")

    response = client.post(
        f"/api/incidents/{observation['id']}/resolve",
        json={"approver_name": "本部 太郎", "staff_name": "現場 次郎", "memo": "給水対応完了"},
    )

    assert response.status_code == 200
    state = response.json()["state"]
    assert state["resolution_memo"] == "給水対応完了"
    assert state["resolution_staff_name"] == "現場 次郎"
    assert state["resolution_approver_name"] == "本部 太郎"
    assert state["resolution_approved_at"] is not None


def test_resolve_incident_requires_hq():
    observation = create_observation(memo="権限確認用2")
    login_as("field")

    response = client.post(
        f"/api/incidents/{observation['id']}/resolve",
        json={"approver_name": "現場 花子", "staff_name": "現場 花子", "memo": ""},
    )

    assert response.status_code == 403


def test_request_incident_resolution_allows_anonymous_mobile_client():
    """決定事項7: モバイル(現場)はログイン不要のため、未ログインでも申請できること。"""
    observation = create_observation(memo="モバイルからの申請対象")
    client.cookies.clear()
    client.headers.pop("X-CSRF-Token", None)

    response = client.post(
        f"/api/incidents/{observation['id']}/resolution-requests",
        json={"staff_name": "現場 三郎", "memo": "給水完了、対応済みにしてください", "active_shelter_id": "AIT001"},
    )

    assert response.status_code == 200
    state = response.json()["state"]
    assert state["resolution_request_staff_name"] == "現場 三郎"
    assert state["resolution_request_active_shelter_id"] == "AIT001"
    assert state["resolution_request_at"] is not None
    # 申請段階では、まだ確定(resolution)にはならない
    assert state["resolution_memo"] is None


def test_request_incident_resolution_404_for_unknown_observation():
    response = client.post(
        "/api/incidents/OBS-does-not-exist/resolution-requests",
        json={"staff_name": "現場 三郎", "memo": "", "active_shelter_id": None},
    )

    assert response.status_code == 404


def test_approve_resolution_request_copies_request_into_resolution():
    observation = create_observation(memo="承認フロー対象")
    client.post(
        f"/api/incidents/{observation['id']}/resolution-requests",
        json={"staff_name": "現場 三郎", "memo": "対応完了しました", "active_shelter_id": "AIT001"},
    )

    response = client.post(
        f"/api/incidents/{observation['id']}/resolution-requests/approve",
        json={"approver_name": "本部 太郎"},
    )

    assert response.status_code == 200
    state = response.json()["state"]
    assert state["resolution_memo"] == "対応完了しました"
    assert state["resolution_staff_name"] == "現場 三郎"
    assert state["resolution_approver_name"] == "本部 太郎"
    assert state["resolution_approved_at"] is not None


def test_approve_resolution_request_fails_when_no_pending_request():
    observation = create_observation(memo="申請なしで承認しようとするケース")

    response = client.post(
        f"/api/incidents/{observation['id']}/resolution-requests/approve",
        json={"approver_name": "本部 太郎"},
    )

    assert response.status_code == 400


def test_approve_resolution_request_requires_hq():
    observation = create_observation(memo="権限確認用3")
    client.post(
        f"/api/incidents/{observation['id']}/resolution-requests",
        json={"staff_name": "現場 三郎", "memo": "対応済み", "active_shelter_id": None},
    )
    login_as("field")

    response = client.post(
        f"/api/incidents/{observation['id']}/resolution-requests/approve",
        json={"approver_name": "現場 花子"},
    )

    assert response.status_code == 403
