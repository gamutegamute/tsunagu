import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import asdict, dataclass
from typing import Literal
from urllib.parse import urlencode

import httpx
import jwt
from fastapi import Cookie, Depends, Header, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from app.config import get_settings

SESSION_COOKIE = "tsunagu_session"
CSRF_COOKIE = "tsunagu_csrf"
OAUTH_COOKIE = "tsunagu_oauth"


@dataclass(frozen=True)
class AuthUser:
    email: str
    name: str
    role: Literal["field", "hq"]


class DevLoginRequest(BaseModel):
    role: Literal["field", "hq"]
    name: str = "Local User"


def _encode_signed(payload: dict, purpose: str) -> str:
    settings = get_settings()
    body = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    ).decode().rstrip("=")
    signature = hmac.new(
        settings.session_secret.encode(), f"{purpose}.{body}".encode(), hashlib.sha256
    ).digest()
    encoded_signature = base64.urlsafe_b64encode(signature).decode().rstrip("=")
    return f"{body}.{encoded_signature}"


def _decode_signed(token: str, purpose: str) -> dict:
    try:
        body, encoded_signature = token.split(".", 1)
        expected = hmac.new(
            get_settings().session_secret.encode(),
            f"{purpose}.{body}".encode(),
            hashlib.sha256,
        ).digest()
        supplied = base64.urlsafe_b64decode(encoded_signature + "=" * (-len(encoded_signature) % 4))
        if not hmac.compare_digest(expected, supplied):
            raise ValueError("signature mismatch")
        payload = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        if int(payload["exp"]) < int(time.time()):
            raise ValueError("token expired")
        return payload
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=401, detail="Authentication is required") from exc


def _role_for_email(email: str) -> Literal["field", "hq"] | None:
    normalized = email.strip().lower()
    settings = get_settings()
    if normalized in settings.hq_emails:
        return "hq"
    if normalized in settings.field_emails:
        return "field"
    return None


def _set_session(response: Response, user: AuthUser) -> None:
    settings = get_settings()
    expires_at = int(time.time()) + settings.session_hours * 60 * 60
    token = _encode_signed({**asdict(user), "exp": expires_at}, "session")
    csrf_token = secrets.token_urlsafe(32)
    secure = settings.app_env == "production"
    max_age = settings.session_hours * 60 * 60
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=max_age,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
    )
    response.set_cookie(
        CSRF_COOKIE,
        csrf_token,
        max_age=max_age,
        httponly=False,
        secure=secure,
        samesite="lax",
        path="/",
    )


def clear_session(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
    response.delete_cookie(OAUTH_COOKIE, path="/")


def get_optional_user(session: str | None = Cookie(default=None, alias=SESSION_COOKIE)) -> AuthUser | None:
    if not session:
        return None
    try:
        payload = _decode_signed(session, "session")
    except HTTPException:
        return None
    user = AuthUser(email=payload["email"], name=payload["name"], role=payload["role"])
    if get_settings().auth_mode == "cognito" and _role_for_email(user.email) != user.role:
        return None
    return user


def require_authenticated_user(user: AuthUser | None = Depends(get_optional_user)) -> AuthUser:
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication is required")
    return user


def require_hq(user: AuthUser = Depends(require_authenticated_user)) -> AuthUser:
    if user.role != "hq":
        raise HTTPException(status_code=403, detail="Headquarters role is required")
    return user


def require_demo_admin(user: AuthUser = Depends(require_hq)) -> AuthUser:
    settings = get_settings()
    if not settings.demo_reset_enabled or user.email.lower() not in settings.demo_admin_emails:
        raise HTTPException(status_code=404, detail="Not found")
    return user


def require_csrf(
    csrf_cookie: str | None = Cookie(default=None, alias=CSRF_COOKIE),
    csrf_header: str | None = Header(default=None, alias="X-CSRF-Token"),
) -> None:
    if not csrf_cookie or not csrf_header or not secrets.compare_digest(csrf_cookie, csrf_header):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")


def require_gateway_key(key: str | None = Header(default=None, alias="X-Gateway-Key")) -> None:
    expected = get_settings().gateway_api_key
    if not expected or not key or not secrets.compare_digest(expected, key):
        raise HTTPException(status_code=401, detail="Invalid gateway API key")


def auth_config() -> dict[str, str | bool]:
    settings = get_settings()
    return {
        "mode": settings.auth_mode,
        "google_enabled": settings.auth_mode == "cognito",
    }


def login_redirect(next_path: str = "/dashboard") -> RedirectResponse:
    settings = get_settings()
    if settings.auth_mode != "cognito":
        return RedirectResponse("/login?development=1", status_code=302)
    if not next_path.startswith("/") or next_path.startswith("//"):
        next_path = "/dashboard"

    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    oauth_token = _encode_signed(
        {"state": state, "verifier": verifier, "next": next_path, "exp": int(time.time()) + 600},
        "oauth",
    )
    callback_url = f"{settings.public_base_url}/api/auth/callback"
    query = urlencode(
        {
            "response_type": "code",
            "client_id": settings.cognito_client_id,
            "redirect_uri": callback_url,
            "scope": "openid email profile",
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "identity_provider": "Google",
            "prompt": "select_account",
        }
    )
    response = RedirectResponse(f"{settings.cognito_domain}/oauth2/authorize?{query}", status_code=302)
    response.set_cookie(
        OAUTH_COOKIE,
        oauth_token,
        max_age=600,
        httponly=True,
        secure=settings.app_env == "production",
        samesite="lax",
        path="/api/auth",
    )
    return response


def auth_callback(code: str, state: str, oauth_cookie: str | None) -> RedirectResponse:
    if not oauth_cookie:
        raise HTTPException(status_code=400, detail="Login state is missing")
    oauth = _decode_signed(oauth_cookie, "oauth")
    if not secrets.compare_digest(oauth["state"], state):
        raise HTTPException(status_code=400, detail="Login state is invalid")

    settings = get_settings()
    callback_url = f"{settings.public_base_url}/api/auth/callback"
    try:
        token_response = httpx.post(
            f"{settings.cognito_domain}/oauth2/token",
            data={
                "grant_type": "authorization_code",
                "client_id": settings.cognito_client_id,
                "code": code,
                "redirect_uri": callback_url,
                "code_verifier": oauth["verifier"],
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=10,
        )
    except httpx.RequestError as exc:
        raise HTTPException(status_code=503, detail="Cognito is temporarily unavailable") from exc
    if token_response.is_error:
        raise HTTPException(status_code=401, detail="Cognito token exchange failed")

    try:
        id_token = token_response.json().get("id_token")
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Cognito token response is invalid") from exc
    if not id_token:
        raise HTTPException(status_code=401, detail="Cognito ID token is missing")
    try:
        signing_key = jwt.PyJWKClient(
            f"{settings.cognito_issuer}/.well-known/jwks.json"
        ).get_signing_key_from_jwt(id_token)
        claims = jwt.decode(
            id_token,
            signing_key.key,
            algorithms=["RS256"],
            audience=settings.cognito_client_id,
            issuer=settings.cognito_issuer,
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="Cognito ID token is invalid") from exc
    email = str(claims.get("email", "")).strip().lower()
    if not email or claims.get("email_verified") is not True:
        raise HTTPException(status_code=403, detail="A verified Google email is required")
    role = _role_for_email(email)
    if role is None:
        raise HTTPException(status_code=403, detail="This Google account is not allowed")

    user = AuthUser(email=email, name=str(claims.get("name") or email), role=role)
    destination = oauth["next"]
    if role == "field" and destination.startswith("/dashboard"):
        destination = "/field-report"
    response = RedirectResponse(destination, status_code=302)
    _set_session(response, user)
    response.delete_cookie(OAUTH_COOKIE, path="/api/auth")
    return response


def dev_login(payload: DevLoginRequest) -> Response:
    if get_settings().auth_mode != "dev":
        raise HTTPException(status_code=404, detail="Not found")
    response = Response(status_code=204)
    _set_session(
        response,
        AuthUser(
            email=f"local-{payload.role}@tsunagu.local",
            name=payload.name.strip() or "Local User",
            role=payload.role,
        ),
    )
    return response
