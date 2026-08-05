import concurrent.futures
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

import app.main as main_module
from app.config import validate_runtime_settings
from app.db import get_conn
from app.main import app
from app.rate_limit import SlidingWindowRateLimiter

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


def test_rate_limiter_rejects_requests_over_limit():
    limiter = SlidingWindowRateLimiter(limit=2, window_seconds=60)

    assert limiter.allow("same-client") is True
    assert limiter.allow("same-client") is True
    assert limiter.allow("same-client") is False
    assert limiter.allow("another-client") is True


def test_production_rejects_development_auth_mode(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("AUTH_MODE", "dev")
    monkeypatch.setenv("SESSION_SECRET", "x" * 32)
    monkeypatch.setenv("GATEWAY_API_KEY", "test-key")

    with pytest.raises(RuntimeError, match="AUTH_MODE=cognito"):
        validate_runtime_settings()


def test_frontend_routes_return_index_html(tmp_path, monkeypatch):
    (tmp_path / "index.html").write_text("<html><body>TSUNAGU</body></html>", encoding="utf-8")
    monkeypatch.setattr(main_module, "FRONTEND_DIR", tmp_path)
    routes = [
        "/",
        "/field-report",
        "/dashboard",
        "/dev-preview",
        "/login",
        "/incident",
        "/history",
        "/dashboard/timeline",
        "/dashboard/shelters/AIT001",
    ]
    for path in routes:
        response = client.get(path)
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]


def test_health_and_readiness():
    assert client.get("/health").json() == {"status": "ok"}
    ready = client.get("/ready")
    assert ready.status_code == 200
    assert ready.json() == {"status": "ok", "database": "ok"}


def test_dashboard_requires_hq_login():
    client.cookies.clear()
    assert client.get("/api/dashboard").status_code == 401


def test_removed_allowlist_user_loses_access(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "cognito")
    monkeypatch.setenv("AUTH_HQ_EMAILS", "local-hq@tsunagu.local")
    assert client.get("/api/auth/me").status_code == 200

    monkeypatch.setenv("AUTH_HQ_EMAILS", "")
    assert client.get("/api/auth/me").status_code == 401


def test_google_login_prompts_for_account_selection(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "cognito")
    monkeypatch.setenv("COGNITO_DOMAIN", "https://example.auth.ap-northeast-1.amazoncognito.com")
    monkeypatch.setenv("COGNITO_CLIENT_ID", "test-client-id")

    response = client.get("/api/auth/login", follow_redirects=False)

    assert response.status_code == 302
    query = parse_qs(urlparse(response.headers["location"]).query)
    assert query["identity_provider"] == ["Google"]
    assert query["prompt"] == ["select_account"]


def test_logout_clears_cognito_session(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "cognito")
    monkeypatch.setenv("AUTH_HQ_EMAILS", "local-hq@tsunagu.local")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://tsunagu.example.com")
    monkeypatch.setenv("COGNITO_DOMAIN", "https://example.auth.ap-northeast-1.amazoncognito.com")
    monkeypatch.setenv("COGNITO_CLIENT_ID", "test-client-id")

    response = client.post("/api/auth/logout")

    assert response.status_code == 200
    logout = urlparse(response.json()["logout_url"])
    assert logout.path == "/logout"
    query = parse_qs(logout.query)
    assert query["client_id"] == ["test-client-id"]
    assert query["logout_uri"] == ["https://tsunagu.example.com/login"]
    assert "tsunagu_session=\"\"" in response.headers["set-cookie"]


def test_field_user_cannot_create_shelter():
    client.cookies.clear()
    login = client.post("/api/auth/dev-login", json={"role": "field", "name": "Field User"})
    client.headers["X-CSRF-Token"] = login.cookies.get("tsunagu_csrf")
    assert client.post("/api/shelters", json={"name": "Forbidden Shelter"}).status_code == 403
    assert client.get("/api/dashboard").status_code == 403


def test_create_observation_is_idempotent():
    payload = observation_payload()
    first = client.post("/api/observations", json=payload)
    assert first.status_code == 201
    assert first.json()["reporter_type"] == "AUTHENTICATED_HQ"
    assert first.json()["verification_status"] == "UNVERIFIED"

    duplicate = client.post("/api/observations", json={**payload, "people_count": 999})
    assert duplicate.status_code == 201
    assert duplicate.json()["id"] == first.json()["id"]
    assert duplicate.json()["people_count"] == 120


def test_anonymous_observation_is_unverified():
    anonymous_client = TestClient(app)
    response = anonymous_client.post("/api/observations", json=observation_payload())
    assert response.status_code == 201
    assert response.json()["reporter_type"] == "ANONYMOUS"
    assert response.json()["reporter_email"] is None
    assert response.json()["verification_status"] == "UNVERIFIED"


def test_create_observation_accepts_shelter_code():
    response = client.post(
        "/api/observations",
        json=observation_payload(shelter_id=None, shelter_code="AIT002", source="offline"),
    )
    assert response.status_code == 201
    assert response.json()["shelter_id"] == "AIT002"
    assert response.json()["source"] == "offline"


def test_create_observation_rejects_unknown_shelter():
    response = client.post("/api/observations", json=observation_payload(shelter_id="AIT999"))
    assert response.status_code == 404
    assert response.json()["detail"]["error"] == "Shelter not found"


def test_hq_can_verify_observation():
    created = client.post("/api/observations", json=observation_payload()).json()
    response = client.patch(
        f"/api/observations/{created['id']}/verification",
        json={"status": "VERIFIED"},
    )
    assert response.status_code == 200
    assert response.json()["verification_status"] == "VERIFIED"
    assert response.json()["verified_by"] == "local-hq@tsunagu.local"


def test_create_shelter_with_custom_id():
    shelter_id = f"AIT-TEST-{uuid4().hex[:8].upper()}"
    payload = {"id": shelter_id, "name": "Test Shelter", "location": "Test Location"}
    assert client.post("/api/shelters", json=payload).status_code == 201
    duplicate = client.post("/api/shelters", json=payload)
    assert duplicate.status_code == 400
    assert duplicate.json()["detail"]["error"] == "Shelter already exists"


def test_emergency_packet_requires_gateway_key():
    client.headers.pop("X-Gateway-Key")
    response = client.post(
        "/api/emergency-packets",
        json={"packet": "v1|AIT001|21:04|170|18|WARNING|REQ_WATER"},
    )
    assert response.status_code == 401


def test_emergency_packet_rejects_invalid_format():
    response = client.post("/api/emergency-packets", json={"packet": "invalid"})
    assert response.status_code == 400
    assert response.json()["detail"]["error"] == "Invalid LoRa packet format"


def test_emergency_packet_syncs_and_deduplicates_observation():
    people_count = 200_000 + uuid4().int % 100_000
    packet = f"v1|AIT003|14:{uuid4().int % 60:02d}|{people_count}|45|WARNING|REQ_WATER"
    first = client.post("/api/emergency-packets", json={"packet": packet})
    second = client.post("/api/emergency-packets", json={"packet": packet})
    assert first.status_code == second.status_code == 201
    assert first.json()["id"] == second.json()["id"]

    with get_conn() as conn:
        observations = conn.execute(
            """
            SELECT * FROM observations
            WHERE shelter_id = 'AIT003' AND people_count = %s AND water_stock = 45
              AND source = 'emergency_packet';
            """,
            (people_count,),
        ).fetchall()
        assert len(observations) == 1
        assert observations[0]["reporter_type"] == "LORA_GATEWAY"


def test_emergency_packet_deduplication_is_concurrent():
    packet = f"v1|AIT001|11:{uuid4().int % 60:02d}|90|15|WARNING|REQ_WATER"

    def send_request():
        return client.post("/api/emergency-packets", json={"packet": packet})

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        responses = list(executor.map(lambda _: send_request(), range(5)))

    assert all(response.status_code == 201 for response in responses)
    assert len({response.json()["id"] for response in responses}) == 1


def test_demo_seed_data_exists():
    with get_conn() as conn:
        observation = conn.execute("SELECT * FROM observations WHERE id = 'OBS-demo-seed-1';").fetchone()
        packet = conn.execute("SELECT * FROM emergency_packets WHERE id = 'EP-demo-seed-2';").fetchone()
    assert observation is not None
    assert packet is not None
