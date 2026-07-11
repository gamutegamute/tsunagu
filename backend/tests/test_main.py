from uuid import uuid4
from fastapi.testclient import TestClient
import app.main as main_module
from app.main import app
from app.db import get_conn

client = TestClient(app)

def test_frontend_routes_return_index_html(tmp_path, monkeypatch):
    (tmp_path / "index.html").write_text("<html><body>ShelterOS</body></html>", encoding="utf-8")
    monkeypatch.setattr(main_module, "FRONTEND_DIR", tmp_path)

    for path in ["/", "/field-report", "/dashboard", "/dev-preview"]:
        response = client.get(path)
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]


def test_create_observation_success():
    client_event_id = str(uuid4())
    payload = {
        "shelter_id": "AIT001",
        "client_event_id": client_event_id,
        "people_count": 120,
        "water_stock": 50,
        "urgency": "NORMAL",
        "memo": "Test memo",
        "reporter_name": "Test Reporter",
        "source": "web"
    }
    response = client.post("/api/observations", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["reporter_name"] == "Test Reporter"
    assert data["source"] == "web"
    assert data["shelter_id"] == "AIT001"

    # 冪等性の検証 (同じ client_event_id で再送信)
    payload2 = payload.copy()
    payload2["people_count"] = 999
    response2 = client.post("/api/observations", json=payload2)
    assert response2.status_code == 201
    data2 = response2.json()
    assert data2["people_count"] == 120  # 更新されず元の値のまま

def test_create_observation_with_shelter_code():
    client_event_id = str(uuid4())
    payload = {
        "shelter_code": "AIT002",
        "client_event_id": client_event_id,
        "people_count": 80,
        "water_stock": 25,
        "urgency": "WARNING",
        "memo": "",
        "reporter_name": "Offline Reporter",
        "source": "offline"
    }
    response = client.post("/api/observations", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["reporter_name"] == "Offline Reporter"
    assert data["source"] == "offline"
    assert data["shelter_id"] == "AIT002"

def test_create_emergency_packet_syncs_to_observations():
    # packet 形式: version|shelter_code|packet_time|people_count|water_stock|status|request_code
    packet_data = "v1|AIT003|14:35|210|45|WARNING|REQ_WATER"
    payload = {"packet": packet_data}
    response = client.post("/api/emergency-packets", json=payload)
    assert response.status_code == 201

    # observations に同期されたか検証
    with get_conn() as conn:
        obs = conn.execute(
            """
            SELECT * FROM observations
            WHERE shelter_id = 'AIT003' AND source = 'emergency_packet'
            ORDER BY created_at DESC LIMIT 1;
            """
        ).fetchone()
        assert obs is not None
        assert obs["people_count"] == 210
        assert obs["water_stock"] == 45
        assert obs["urgency"] == "WARNING"
        assert obs["reporter_name"] == "LoRa Packet"
        assert "[LoRa]" in obs["memo"]
        assert obs["client_event_id"].startswith("LORA-")


def test_seed_data_exists():
    # 日本語コメント: シードデータがDBに存在しているか直接検証
    with get_conn() as conn:
        obs1 = conn.execute("SELECT * FROM observations WHERE id = 'OBS-demo-seed-1';").fetchone()
        assert obs1 is not None
        assert obs1["reporter_name"] == "デモ報告者A"

        obs2 = conn.execute("SELECT * FROM observations WHERE id = 'OBS-demo-seed-2';").fetchone()
        assert obs2 is not None
        assert obs2["source"] == "emergency_packet"

        ep = conn.execute("SELECT * FROM emergency_packets WHERE id = 'EP-demo-seed-2';").fetchone()
        assert ep is not None


def test_create_observation_shelter_not_found_error():
    # 日本語コメント: 存在しない避難所コードによる404詳細エラー検証
    payload = {
        "shelter_id": "AIT999",
        "client_event_id": str(uuid4()),
        "people_count": 10,
        "water_stock": 10,
        "urgency": "NORMAL",
        "memo": "",
        "reporter_name": "Test",
        "source": "web"
    }
    response = client.post("/api/observations", json=payload)
    assert response.status_code == 404
    data = response.json()
    assert "detail" in data
    assert data["detail"]["error"] == "Shelter not found"
    assert "AIT999" in data["detail"]["message"]
    assert "hint" in data["detail"]


def test_create_emergency_packet_invalid_format_error():
    # 日本語コメント: 不正なLoRaパケット送信による400詳細エラー検証
    payload = {"packet": "invalid_packet_format"}
    response = client.post("/api/emergency-packets", json=payload)
    assert response.status_code == 400
    data = response.json()
    assert "detail" in data
    assert data["detail"]["error"] == "Invalid LoRa packet format"
    assert "expected_format" in data["detail"]
    assert "example" in data["detail"]
