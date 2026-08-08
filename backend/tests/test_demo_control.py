import pytest
from fastapi.testclient import TestClient

import app.db as db_module
from app.db import get_demo_data_counts, reset_demo_dataset
from app.main import DEMO_RESET_CONFIRMATION, app

client = TestClient(app)


@pytest.fixture(autouse=True)
def authenticated_demo_admin(monkeypatch):
    monkeypatch.setenv("DEMO_RESET_ENABLED", "true")
    monkeypatch.setenv("DEMO_ADMIN_EMAILS", "local-hq@tsunagu.local")
    client.cookies.clear()
    response = client.post("/api/auth/dev-login", json={"role": "hq", "name": "Demo Admin"})
    assert response.status_code == 204
    client.headers["X-CSRF-Token"] = client.cookies.get("tsunagu_csrf")
    yield
    client.headers.pop("X-CSRF-Token", None)
    client.cookies.clear()


def test_demo_admin_can_read_status():
    response = client.get("/api/admin/demo")

    assert response.status_code == 200
    assert response.json()["confirmation_phrase"] == DEMO_RESET_CONFIRMATION
    assert set(response.json()["counts"]) == {"shelters", "observations", "emergency_packets"}


def test_demo_reset_requires_exact_confirmation():
    response = client.post("/api/admin/demo/reset", json={"confirmation": "リセット"})

    assert response.status_code == 400


def test_demo_reset_requires_csrf():
    client.headers.pop("X-CSRF-Token")

    response = client.post(
        "/api/admin/demo/reset",
        json={"confirmation": DEMO_RESET_CONFIRMATION},
    )

    assert response.status_code == 403


def test_demo_reset_restores_fixed_dataset():
    response = client.post(
        "/api/admin/demo/reset",
        json={"confirmation": DEMO_RESET_CONFIRMATION},
    )

    assert response.status_code == 200
    assert response.json()["counts"] == {
        "shelters": 3,
        "observations": 3,
        "emergency_packets": 1,
    }
    dashboard = client.get("/api/dashboard").json()
    ait003 = next(item for item in dashboard if item["shelter"]["id"] == "AIT003")
    assert ait003["latest_observation"]["memo"] == "負傷者の搬送支援が必要です"


def test_hq_outside_allowlist_cannot_discover_demo_control(monkeypatch):
    monkeypatch.setenv("DEMO_ADMIN_EMAILS", "another-hq@example.com")

    assert client.get("/api/admin/demo").status_code == 404


def test_disabled_demo_control_returns_not_found(monkeypatch):
    monkeypatch.setenv("DEMO_RESET_ENABLED", "false")

    assert client.get("/api/admin/demo").status_code == 404


def test_field_user_cannot_access_demo_control():
    client.cookies.clear()
    response = client.post("/api/auth/dev-login", json={"role": "field", "name": "Field User"})
    assert response.status_code == 204

    assert client.get("/api/admin/demo").status_code == 403


def test_reset_rolls_back_if_seeding_fails(monkeypatch):
    before = get_demo_data_counts()

    def fail_to_seed(_):
        raise RuntimeError("seed failure")

    monkeypatch.setattr(db_module, "_insert_demo_data", fail_to_seed)
    with pytest.raises(RuntimeError, match="seed failure"):
        reset_demo_dataset()

    assert get_demo_data_counts() == before
