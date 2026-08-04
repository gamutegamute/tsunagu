import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    app_env: str
    auth_mode: str
    public_base_url: str
    session_secret: str
    session_hours: int
    cognito_domain: str
    cognito_client_id: str
    cognito_issuer: str
    hq_emails: frozenset[str]
    field_emails: frozenset[str]
    gateway_api_key: str


def _email_set(name: str) -> frozenset[str]:
    return frozenset(
        email.strip().lower()
        for email in os.getenv(name, "").split(",")
        if email.strip()
    )


def get_settings() -> Settings:
    return Settings(
        app_env=os.getenv("APP_ENV", "development").lower(),
        auth_mode=os.getenv("AUTH_MODE", "dev").lower(),
        public_base_url=os.getenv("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/"),
        session_secret=os.getenv("SESSION_SECRET", "local-development-session-secret"),
        session_hours=int(os.getenv("SESSION_HOURS", "24")),
        cognito_domain=os.getenv("COGNITO_DOMAIN", "").rstrip("/"),
        cognito_client_id=os.getenv("COGNITO_CLIENT_ID", ""),
        cognito_issuer=os.getenv("COGNITO_ISSUER", "").rstrip("/"),
        hq_emails=_email_set("AUTH_HQ_EMAILS"),
        field_emails=_email_set("AUTH_FIELD_EMAILS"),
        gateway_api_key=os.getenv("GATEWAY_API_KEY", ""),
    )


def validate_runtime_settings() -> None:
    settings = get_settings()
    if settings.app_env != "production":
        return

    missing = []
    if settings.auth_mode not in {"cognito", "setup"}:
        missing.append("AUTH_MODE=cognito")
    if len(settings.session_secret) < 32:
        missing.append("SESSION_SECRET (32 characters or more)")
    if not settings.gateway_api_key:
        missing.append("GATEWAY_API_KEY")
    if settings.auth_mode == "cognito" and not settings.cognito_domain:
        missing.append("COGNITO_DOMAIN")
    if settings.auth_mode == "cognito" and not settings.cognito_client_id:
        missing.append("COGNITO_CLIENT_ID")
    if settings.auth_mode == "cognito" and not settings.cognito_issuer:
        missing.append("COGNITO_ISSUER")
    if settings.auth_mode == "cognito" and not settings.hq_emails:
        missing.append("AUTH_HQ_EMAILS")

    if missing:
        raise RuntimeError(f"Production configuration is incomplete: {', '.join(missing)}")
