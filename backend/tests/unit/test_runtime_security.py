from pathlib import Path

import pytest
from starlette.requests import Request

from app.config import DEVELOPMENT_SESSION_SECRET, validate_runtime_settings
from app.main import _client_ip
from app.rate_limit import SlidingWindowRateLimiter


def request(peer, forwarded):
    return Request({"type": "http", "client": (peer, 1234), "headers": [(b"x-forwarded-for", forwarded.encode())]})


@pytest.mark.parametrize("secret", [None, "", "short", DEVELOPMENT_SESSION_SECRET])
def test_production_requires_explicit_non_development_session_key(monkeypatch, secret):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("AUTH_MODE", "cognito")
    monkeypatch.setenv("COGNITO_DOMAIN", "https://example.invalid")
    monkeypatch.setenv("COGNITO_CLIENT_ID", "dummy")
    monkeypatch.setenv("COGNITO_ISSUER", "https://example.invalid/pool")
    monkeypatch.setenv("AUTH_HQ_EMAILS", "hq@example.invalid")
    monkeypatch.setenv("GATEWAY_API_KEY", "dummy")
    monkeypatch.setenv("DEMO_RESET_ENABLED", "false")
    if secret is None:
        monkeypatch.delenv("SESSION_SECRET", raising=False)
    else:
        monkeypatch.setenv("SESSION_SECRET", secret)
    with pytest.raises(RuntimeError, match="SESSION_SECRET"):
        validate_runtime_settings()
    monkeypatch.setenv("SESSION_SECRET", "unit-test-random-key-" + "a" * 48)
    validate_runtime_settings()


def test_direct_connection_cannot_change_rate_limit_key_with_headers(monkeypatch):
    monkeypatch.delenv("TRUSTED_PROXY_CIDRS", raising=False)
    limiter = SlidingWindowRateLimiter(2, 60)
    keys = [_client_ip(request("192.0.2.10", f"198.51.100.{i}")) for i in range(3)]
    assert keys == ["192.0.2.10"] * 3
    assert [limiter.allow(key) for key in keys] == [True, True, False]


def test_trusted_chain_selects_nearest_untrusted_client_and_ignores_spoofed_prefix(monkeypatch):
    monkeypatch.setenv("TRUSTED_PROXY_CIDRS", "10.0.0.0/24,2001:db8:1::/64")
    assert _client_ip(request("10.0.0.2", "203.0.113.9, 198.51.100.5, 10.0.0.3")) == "198.51.100.5"
    assert _client_ip(request("2001:db8:1::2", "2001:db8:2::1")) == "2001:db8:2::1"
    assert _client_ip(request("192.0.2.1", "198.51.100.1")) == "192.0.2.1"


@pytest.mark.parametrize("header", ["not-an-ip", "a" * 2049, ",".join(["192.0.2.1"] * 33)])
def test_invalid_forwarded_header_falls_back_to_peer(monkeypatch, header):
    monkeypatch.setenv("TRUSTED_PROXY_CIDRS", "10.0.0.0/24")
    assert _client_ip(request("10.0.0.2", header)) == "10.0.0.2"


def test_rate_limiter_bounds_keys_and_collects_expired_senders(monkeypatch):
    now = [0.0]
    monkeypatch.setattr("app.rate_limit.time.monotonic", lambda: now[0])
    limiter = SlidingWindowRateLimiter(1, 60, max_keys=2)
    assert limiter.allow("A") and limiter.allow("B")
    assert not limiter.allow("C")
    assert not limiter.allow("A")  # Saturation must not evict a sender and reset its limit.
    assert len(limiter._events) == 2
    now[0] = 60.0
    assert limiter.allow("C")
    assert list(limiter._events) == ["C"]


def test_development_compose_binds_to_loopback_and_disables_implicit_proxy_trust():
    root = Path(__file__).resolve().parents[3]
    compose = (root / "docker-compose.yml").read_text(encoding="utf-8")
    assert '"127.0.0.1:8000:8000"' in compose
    assert '"127.0.0.1:5432:5432"' in compose
    assert "--no-proxy-headers" in (root / "backend/Dockerfile").read_text(encoding="utf-8")
