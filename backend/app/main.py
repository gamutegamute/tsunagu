import hashlib
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import Cookie, Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.auth import (
    OAUTH_COOKIE,
    AuthUser,
    DevLoginRequest,
    auth_callback,
    auth_config,
    clear_session,
    dev_login,
    get_optional_user,
    login_redirect,
    logout_url,
    require_authenticated_user,
    require_csrf,
    require_demo_admin,
    require_gateway_key,
    require_hq,
)
from app.config import get_settings, validate_runtime_settings
from app.db import get_conn, get_demo_data_counts, reset_demo_dataset, seed_demo_data
from app.emergency_packet import (
    ParsedEmergencyPacketV2,
    packet_version,
    parse_emergency_packet,
    parse_emergency_packet_v2,
    verify_packet_hmac,
)
from app.models import (
    DemoResetRequest,
    EmergencyPacket,
    EmergencyPacketCreate,
    Incident,
    IncidentConfirmRequest,
    IncidentResolutionApproveRequest,
    IncidentResolutionRequestCreate,
    IncidentResolveRequest,
    IncidentState,
    Observation,
    ObservationCreate,
    ObservationVerificationUpdate,
    Shelter,
    ShelterCreate,
    ShelterStatus,
)
from app.packet_keys import KeyLookupFailure, PacketKeyConfigError, load_device_key_registry
from app.status import decide_request_code, decide_status
from app.rate_limit import SlidingWindowRateLimiter

logger = logging.getLogger(__name__)
DEMO_RESET_CONFIRMATION = "TSUNAGUをリセット"


@asynccontextmanager
async def lifespan(_: FastAPI):
    validate_runtime_settings()
    log_packet_settings()
    seed_demo_data()
    yield


def log_packet_settings() -> None:
    """起動時に、Emergency Packet の受け付けの設定をログに出す(鍵の値は出さない)。

    v1 を許可しているか、端末台帳の端末数(と鍵の数・無効化した端末の数)を出す。
    台帳が空のとき(v2 はすべて 403 になる)と、本番で v1 を許可しているときは WARNING にする。
    """
    settings = get_settings()
    v1_mode = "allowed" if settings.allow_v1_packets else "rejected"
    logger.info("Emergency Packet v1: %s (ALLOW_V1_PACKETS)", v1_mode)
    if settings.allow_v1_packets and settings.app_env == "production":
        logger.warning(
            "Emergency Packet v1 is allowed in production (ALLOW_V1_PACKETS=true); "
            "unsigned v1 reports are accepted. Set it to false after all senders run v2 firmware."
        )
    registry = load_device_key_registry()
    device_count = len(registry.keys)
    key_count = sum(len(keys) for keys in registry.keys.values())
    logger.info(
        "Emergency Packet device ledger: devices=%d keys=%d disabled=%d",
        device_count,
        key_count,
        len(registry.disabled_devices),
    )
    if device_count == 0:
        logger.warning(
            "Emergency Packet device ledger is empty; every v2 packet will be rejected with 403 PACKET_AUTH_FAILED. "
            "Set PACKET_DEVICE_KEYS or PACKET_DEVICE_KEYS_FILE."
        )


app = FastAPI(title="TSUNAGU", version="0.9.0", lifespan=lifespan)
anonymous_report_limiter = SlidingWindowRateLimiter(limit=30, window_seconds=60)


@app.middleware("http")
async def block_requests_during_cloud_setup(request: Request, call_next):
    from app.config import get_settings

    if get_settings().auth_mode == "setup" and request.url.path not in {"/health", "/ready"}:
        return JSONResponse({"detail": "Cloud authentication setup is in progress"}, status_code=503)
    return await call_next(request)

APP_FILE = Path(__file__).resolve()
FRONTEND_CANDIDATES = [
    APP_FILE.parents[1] / "frontend",
    APP_FILE.parents[2] / "frontend" / "dist",
    APP_FILE.parents[2] / "frontend",
]
FRONTEND_DIR = next(
    (path for path in FRONTEND_CANDIDATES if (path / "index.html").exists()),
    FRONTEND_CANDIDATES[0],
)


if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


@app.get("/service-worker.js", include_in_schema=False)
def service_worker() -> FileResponse:
    return FileResponse(
        FRONTEND_DIR / "service-worker.js",
        media_type="application/javascript",
        headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"},
    )


@app.get("/manifest.webmanifest", include_in_schema=False)
def web_manifest() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "manifest.webmanifest", media_type="application/manifest+json")


@app.get("/workbox-{filename}.js", include_in_schema=False)
def workbox_runtime(filename: str) -> FileResponse:
    """Serve Workbox beside the root-scoped service worker."""
    file_path = FRONTEND_DIR / f"workbox-{filename}.js"
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="Workbox runtime not found")
    return FileResponse(file_path, media_type="application/javascript")


@app.get("/", include_in_schema=False)
@app.get("/field-report", include_in_schema=False)
@app.get("/dashboard", include_in_schema=False)
@app.get("/demo-control", include_in_schema=False)
@app.get("/dev-preview", include_in_schema=False)
@app.get("/login", include_in_schema=False)
@app.get("/incident", include_in_schema=False)
@app.get("/history", include_in_schema=False)
@app.get("/dashboard/timeline", include_in_schema=False)
@app.get("/dashboard/shelters/{shelter_id}", include_in_schema=False)
def index(shelter_id: str | None = None) -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready")
def ready(response: Response) -> dict[str, str]:
    try:
        with get_conn() as conn:
            conn.execute("SELECT 1;").fetchone()
    except Exception:
        response.status_code = 503
        return {"status": "error", "database": "error"}
    return {"status": "ok", "database": "ok"}


@app.get("/api/auth/config")
def get_auth_config() -> dict[str, str | bool]:
    return auth_config()


@app.get("/api/auth/login", include_in_schema=False)
def begin_login(next: str = "/dashboard") -> RedirectResponse:
    return login_redirect(next)


@app.get("/api/auth/callback", include_in_schema=False)
def finish_login(
    code: str,
    state: str,
    oauth_cookie: str | None = Cookie(default=None, alias=OAUTH_COOKIE),
) -> RedirectResponse:
    return auth_callback(code, state, oauth_cookie)


@app.post("/api/auth/dev-login", status_code=204)
def local_login(payload: DevLoginRequest) -> Response:
    return dev_login(payload)


@app.get("/api/auth/me")
def current_user(user: AuthUser = Depends(require_authenticated_user)) -> dict[str, str]:
    return {"email": user.email, "name": user.name, "role": user.role}


@app.post("/api/auth/logout", dependencies=[Depends(require_csrf)])
def logout(
    response: Response,
    _: AuthUser = Depends(require_authenticated_user),
) -> dict[str, str]:
    clear_session(response)
    return {"logout_url": logout_url()}


@app.get("/api/admin/demo")
def get_demo_control_status(
    _: AuthUser = Depends(require_demo_admin),
) -> dict:
    return {
        "confirmation_phrase": DEMO_RESET_CONFIRMATION,
        "counts": get_demo_data_counts(),
    }


@app.post(
    "/api/admin/demo/reset",
    dependencies=[Depends(require_csrf)],
)
def reset_demo_data(
    payload: DemoResetRequest,
    user: AuthUser = Depends(require_demo_admin),
) -> dict:
    if payload.confirmation != DEMO_RESET_CONFIRMATION:
        raise HTTPException(status_code=400, detail="確認文が一致しません")

    logger.warning("Demo reset requested by %s", user.email)
    try:
        counts = reset_demo_dataset()
    except Exception:
        logger.exception("Demo reset failed for %s", user.email)
        raise HTTPException(status_code=500, detail="デモデータの初期化に失敗しました")

    reset_at = datetime.now(timezone.utc).isoformat()
    logger.warning("Demo reset completed by %s at %s: %s", user.email, reset_at, counts)
    return {"reset_at": reset_at, "counts": counts}


@app.get("/api/shelters", response_model=list[Shelter])
def list_shelters() -> list[dict]:
    with get_conn() as conn:
        return list(conn.execute("SELECT * FROM shelters ORDER BY id;"))


@app.post(
    "/api/shelters",
    response_model=Shelter,
    status_code=201,
    dependencies=[Depends(require_csrf)],
)
def create_shelter(payload: ShelterCreate, _: AuthUser = Depends(require_hq)) -> dict:
    shelter_id = payload.id or f"SH-{uuid4().hex[:8].upper()}"
    with get_conn() as conn:
        row = conn.execute(
            """
            INSERT INTO shelters (id, name, location, capacity)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (id) DO NOTHING
            RETURNING *;
            """,
            (shelter_id, payload.name, payload.location, payload.capacity),
        ).fetchone()
        if row is None:
            raise HTTPException(
                status_code=400,
                detail={"error": "Shelter already exists", "message": f"Shelter ID '{shelter_id}' is already registered"},
            )
        conn.commit()
        return row


def _reporter_identity(user: AuthUser | None) -> tuple[str, str | None]:
    if user is None:
        return "ANONYMOUS", None
    if user.role == "hq":
        return "AUTHENTICATED_HQ", user.email
    return "AUTHENTICATED_FIELD", user.email


def _client_ip(request: Request) -> str:
    forwarded_for = request.headers.get("X-Forwarded-For", "")
    if forwarded_for:
        # The ALB appends the address it observed to the right side of the chain.
        return forwarded_for.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"


@app.post("/api/observations", response_model=Observation, status_code=201)
def create_observation(
    payload: ObservationCreate,
    request: Request,
    user: AuthUser | None = Depends(get_optional_user),
) -> dict:
    observed_at = payload.observed_at or datetime.now(timezone.utc)
    shelter_id = payload.shelter_id or payload.shelter_code
    reporter_type, reporter_email = _reporter_identity(user)
    if user is None and not anonymous_report_limiter.allow(_client_ip(request)):
        raise HTTPException(status_code=429, detail="Too many anonymous reports; try again shortly")

    with get_conn() as conn:
        shelter = conn.execute("SELECT id FROM shelters WHERE id = %s;", (shelter_id,)).fetchone()
        if shelter is None:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "Shelter not found",
                    "message": f"Shelter '{shelter_id}' is not registered",
                    "hint": "Use GET /api/shelters to check registered shelter IDs",
                },
            )

        row = conn.execute(
            """
            INSERT INTO observations (
                id, shelter_id, client_event_id, people_count, water_stock,
                urgency, memo, observed_at, reporter_name, reporter_email,
                reporter_type, verification_status, source
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'UNVERIFIED', %s)
            ON CONFLICT (client_event_id) DO UPDATE
            SET client_event_id = EXCLUDED.client_event_id
            RETURNING *;
            """,
            (
                f"OBS-{uuid4().hex}",
                shelter["id"],
                payload.client_event_id,
                payload.people_count,
                payload.water_stock,
                payload.urgency,
                payload.memo,
                observed_at,
                payload.reporter_name,
                reporter_email,
                reporter_type,
                payload.source,
            ),
        ).fetchone()
        conn.commit()
        return row


@app.patch(
    "/api/observations/{observation_id}/verification",
    response_model=Observation,
    dependencies=[Depends(require_csrf)],
)
def update_observation_verification(
    observation_id: str,
    payload: ObservationVerificationUpdate,
    user: AuthUser = Depends(require_hq),
) -> dict:
    with get_conn() as conn:
        row = conn.execute(
            """
            UPDATE observations
            SET verification_status = %s, verified_by = %s, verified_at = now()
            WHERE id = %s
            RETURNING *;
            """,
            (payload.status, user.email, observation_id),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Observation not found")
        conn.commit()
        return row


@app.get("/api/observations/latest", response_model=list[Observation])
def latest_observations(_: AuthUser = Depends(require_hq)) -> list[dict]:
    with get_conn() as conn:
        return list(
            conn.execute(
                """
                SELECT DISTINCT ON (shelter_id) *
                FROM observations
                ORDER BY shelter_id, observed_at DESC, created_at DESC;
                """
            )
        )


SHELTER_OBSERVATIONS_DEFAULT_LIMIT = 100
SHELTER_OBSERVATIONS_MAX_LIMIT = 500


@app.get("/api/shelters/{shelter_id}/observations", response_model=list[Observation])
def shelter_observations(
    shelter_id: str,
    limit: int = SHELTER_OBSERVATIONS_DEFAULT_LIMIT,
    _: AuthUser = Depends(require_hq),
) -> list[dict]:
    """
    Timeline画面の「過去の報告履歴を遡って見る」機能向け。GET /api/dashboardは
    各避難所の最新1件しか返さないため、対象避難所のobservationsを
    observed_at降順(古い順ではなく新しい順)で返す専用エンドポイントを用意する。
    件数上限を設け、報告が積み重なっても無限にレスポンスが増え続けないようにする。
    """
    limit = max(1, min(limit, SHELTER_OBSERVATIONS_MAX_LIMIT))
    with get_conn() as conn:
        shelter = conn.execute("SELECT id FROM shelters WHERE id = %s;", (shelter_id,)).fetchone()
        if shelter is None:
            raise HTTPException(status_code=404, detail="Shelter not found")

        return list(
            conn.execute(
                """
                SELECT *
                FROM observations
                WHERE shelter_id = %s
                ORDER BY observed_at DESC, created_at DESC
                LIMIT %s;
                """,
                (shelter_id, limit),
            )
        )


@app.get("/api/dashboard", response_model=list[ShelterStatus])
def dashboard(_: AuthUser = Depends(require_hq)) -> list[dict]:
    with get_conn() as conn:
        rows = list(
            conn.execute(
                """
                SELECT
                    s.id AS shelter_id,
                    s.name,
                    s.location,
                    s.created_at AS shelter_created_at,
                    s.capacity AS shelter_capacity,
                    o.id AS observation_id,
                    o.client_event_id,
                    o.people_count,
                    o.water_stock,
                    o.urgency,
                    o.memo,
                    o.observed_at,
                    o.created_at AS observation_created_at,
                    o.reporter_name,
                    o.reporter_email,
                    o.reporter_type,
                    o.verification_status,
                    o.verified_by,
                    o.verified_at,
                    o.source
                FROM shelters s
                LEFT JOIN LATERAL (
                    SELECT *
                    FROM observations
                    WHERE shelter_id = s.id AND verification_status != 'REJECTED'
                    ORDER BY observed_at DESC, created_at DESC
                    LIMIT 1
                ) o ON TRUE
                ORDER BY s.id;
                """
            )
        )

    items = []
    for row in rows:
        observation = None
        if row["observation_id"] is not None:
            observation = {
                "id": row["observation_id"],
                "shelter_id": row["shelter_id"],
                "client_event_id": row["client_event_id"],
                "people_count": row["people_count"],
                "water_stock": row["water_stock"],
                "urgency": row["urgency"],
                "memo": row["memo"],
                "observed_at": row["observed_at"],
                "created_at": row["observation_created_at"],
                "reporter_name": row["reporter_name"],
                "reporter_email": row["reporter_email"],
                "reporter_type": row["reporter_type"],
                "verification_status": row["verification_status"],
                "verified_by": row["verified_by"],
                "verified_at": row["verified_at"],
                "source": row["source"],
            }
        status = decide_status(
            observed_at=row["observed_at"],
            water_stock=row["water_stock"],
            urgency=row["urgency"],
        )
        items.append(
            {
                "shelter": {
                    "id": row["shelter_id"],
                    "name": row["name"],
                    "location": row["location"],
                    "created_at": row["shelter_created_at"],
                    "capacity": row["shelter_capacity"],
                },
                "latest_observation": observation,
                "status": status,
                "request_code": decide_request_code(water_stock=row["water_stock"], status=status),
            }
        )
    return items


def _incident_state_from_row(row: dict) -> dict:
    return {
        "confirm_status": row["confirm_status"] or "UNCONFIRMED",
        "confirmed_by": row["confirmed_by"],
        "confirmed_at": row["confirmed_at"],
        "confirm_memo": row["confirm_memo"],
        "resolution_request_memo": row["resolution_request_memo"],
        "resolution_request_staff_name": row["resolution_request_staff_name"],
        "resolution_request_active_shelter_id": row["resolution_request_active_shelter_id"],
        "resolution_request_at": row["resolution_request_at"],
        "resolution_memo": row["resolution_memo"],
        "resolution_staff_name": row["resolution_staff_name"],
        "resolution_approver_name": row["resolution_approver_name"],
        "resolution_approved_at": row["resolution_approved_at"],
    }


@app.get("/api/incidents", response_model=list[Incident])
def list_incidents(_: AuthUser = Depends(require_hq)) -> list[dict]:
    """
    決定事項34-a: メモが入っている全observationsを(避難所ごとの最新1件に絞らず)
    observed_at降順で返す。GET /api/dashboardは「最新1件のみ」しか返さないため、
    新しい報告が来た瞬間に古いIncidentが一覧から消えてしまう問題があった。
    observationsは常にINSERTのみで過去分も保持されているため、ここでは絞り込まずに
    全件返すことでこの問題を解消する。
    """
    with get_conn() as conn:
        rows = list(
            conn.execute(
                """
                SELECT
                    o.id AS observation_id,
                    o.urgency,
                    o.water_stock,
                    o.memo,
                    o.observed_at,
                    s.id AS shelter_id,
                    s.name AS shelter_name,
                    s.location AS shelter_location,
                    s.created_at AS shelter_created_at,
                    ist.confirm_status,
                    ist.confirmed_by,
                    ist.confirmed_at,
                    ist.confirm_memo,
                    ist.resolution_request_memo,
                    ist.resolution_request_staff_name,
                    ist.resolution_request_active_shelter_id,
                    ist.resolution_request_at,
                    ist.resolution_memo,
                    ist.resolution_staff_name,
                    ist.resolution_approver_name,
                    ist.resolution_approved_at
                FROM observations o
                JOIN shelters s ON s.id = o.shelter_id
                LEFT JOIN incident_states ist ON ist.observation_id = o.id
                WHERE o.memo IS NOT NULL
                    AND trim(o.memo) != ''
                    AND o.source != 'emergency_packet'
                ORDER BY o.observed_at DESC, o.created_at DESC;
                """
            )
        )

    incidents = []
    for row in rows:
        status = decide_status(observed_at=row["observed_at"], water_stock=row["water_stock"], urgency=row["urgency"])
        incidents.append(
            {
                "id": row["observation_id"],
                "shelter": {
                    "id": row["shelter_id"],
                    "name": row["shelter_name"],
                    "location": row["shelter_location"],
                    "created_at": row["shelter_created_at"],
                },
                "urgency": status,
                "memo": row["memo"],
                "observed_at": row["observed_at"],
                "state": _incident_state_from_row(row),
            }
        )
    return incidents


def _fetch_incident(conn, observation_id: str) -> dict | None:
    row = conn.execute(
        """
        SELECT
            o.id AS observation_id,
            o.urgency,
            o.water_stock,
            o.memo,
            o.observed_at,
            s.id AS shelter_id,
            s.name AS shelter_name,
            s.location AS shelter_location,
            s.created_at AS shelter_created_at,
            ist.confirm_status,
            ist.confirmed_by,
            ist.confirmed_at,
            ist.confirm_memo,
            ist.resolution_request_memo,
            ist.resolution_request_staff_name,
            ist.resolution_request_active_shelter_id,
            ist.resolution_request_at,
            ist.resolution_memo,
            ist.resolution_staff_name,
            ist.resolution_approver_name,
            ist.resolution_approved_at
        FROM observations o
        JOIN shelters s ON s.id = o.shelter_id
        LEFT JOIN incident_states ist ON ist.observation_id = o.id
        WHERE o.id = %s;
        """,
        (observation_id,),
    ).fetchone()
    if row is None:
        return None

    status = decide_status(observed_at=row["observed_at"], water_stock=row["water_stock"], urgency=row["urgency"])
    return {
        "id": row["observation_id"],
        "shelter": {
            "id": row["shelter_id"],
            "name": row["shelter_name"],
            "location": row["shelter_location"],
            "created_at": row["shelter_created_at"],
        },
        "urgency": status,
        "memo": row["memo"],
        "observed_at": row["observed_at"],
        "state": _incident_state_from_row(row),
    }


def _require_observation_exists(conn, observation_id: str) -> None:
    row = conn.execute("SELECT id FROM observations WHERE id = %s;", (observation_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Observation not found")


@app.post(
    "/api/incidents/{observation_id}/confirm",
    response_model=Incident,
    dependencies=[Depends(require_csrf)],
)
def confirm_incident(
    observation_id: str,
    payload: IncidentConfirmRequest,
    _: AuthUser = Depends(require_hq),
) -> dict:
    """決定事項14: 「確認済みにする」は本部(PC)専用の操作。"""
    with get_conn() as conn:
        _require_observation_exists(conn, observation_id)
        conn.execute(
            """
            INSERT INTO incident_states (observation_id, confirm_status, confirmed_by, confirmed_at, confirm_memo)
            VALUES (%s, 'CONFIRMED', %s, now(), %s)
            ON CONFLICT (observation_id) DO UPDATE SET
                confirm_status = EXCLUDED.confirm_status,
                confirmed_by = EXCLUDED.confirmed_by,
                confirmed_at = EXCLUDED.confirmed_at,
                confirm_memo = EXCLUDED.confirm_memo;
            """,
            (observation_id, payload.approver_name, payload.memo),
        )
        conn.commit()
        return _fetch_incident(conn, observation_id)


@app.post(
    "/api/incidents/{observation_id}/resolve",
    response_model=Incident,
    dependencies=[Depends(require_csrf)],
)
def resolve_incident(
    observation_id: str,
    payload: IncidentResolveRequest,
    _: AuthUser = Depends(require_hq),
) -> dict:
    """
    決定事項14: 申請を経由せず本部(PC)が直接「対応済みにする」場合。
    承認者本人がその場で対応内容を記録するため、承認待ちを経由せず即確定する。
    """
    with get_conn() as conn:
        _require_observation_exists(conn, observation_id)
        conn.execute(
            """
            INSERT INTO incident_states (
                observation_id, resolution_memo, resolution_staff_name,
                resolution_approver_name, resolution_approved_at
            )
            VALUES (%s, %s, %s, %s, now())
            ON CONFLICT (observation_id) DO UPDATE SET
                resolution_memo = EXCLUDED.resolution_memo,
                resolution_staff_name = EXCLUDED.resolution_staff_name,
                resolution_approver_name = EXCLUDED.resolution_approver_name,
                resolution_approved_at = EXCLUDED.resolution_approved_at;
            """,
            (observation_id, payload.memo, payload.staff_name, payload.approver_name),
        )
        conn.commit()
        return _fetch_incident(conn, observation_id)


@app.post("/api/incidents/{observation_id}/resolution-requests", response_model=Incident)
def request_incident_resolution(
    observation_id: str,
    payload: IncidentResolutionRequestCreate,
    _: AuthUser | None = Depends(get_optional_user),
) -> dict:
    """
    決定事項7・12・14: モバイル(現場)からの「対応済みにする」申請。
    ログイン不要(決定事項7)なため、認証は必須にしない。承認はPC専用(resolution-requests/approve)。
    """
    with get_conn() as conn:
        _require_observation_exists(conn, observation_id)
        conn.execute(
            """
            INSERT INTO incident_states (
                observation_id, resolution_request_memo, resolution_request_staff_name,
                resolution_request_active_shelter_id, resolution_request_at
            )
            VALUES (%s, %s, %s, %s, now())
            ON CONFLICT (observation_id) DO UPDATE SET
                resolution_request_memo = EXCLUDED.resolution_request_memo,
                resolution_request_staff_name = EXCLUDED.resolution_request_staff_name,
                resolution_request_active_shelter_id = EXCLUDED.resolution_request_active_shelter_id,
                resolution_request_at = EXCLUDED.resolution_request_at;
            """,
            (observation_id, payload.memo, payload.staff_name, payload.active_shelter_id),
        )
        conn.commit()
        return _fetch_incident(conn, observation_id)


@app.post(
    "/api/incidents/{observation_id}/resolution-requests/approve",
    response_model=Incident,
    dependencies=[Depends(require_csrf)],
)
def approve_incident_resolution_request(
    observation_id: str,
    payload: IncidentResolutionApproveRequest,
    _: AuthUser = Depends(require_hq),
) -> dict:
    """決定事項2・7・12: モバイルからの申請を、本部(PC)が承認して確定する。"""
    with get_conn() as conn:
        _require_observation_exists(conn, observation_id)
        row = conn.execute(
            """
            UPDATE incident_states
            SET resolution_memo = resolution_request_memo,
                resolution_staff_name = resolution_request_staff_name,
                resolution_approver_name = %s,
                resolution_approved_at = now()
            WHERE observation_id = %s AND resolution_request_at IS NOT NULL
            RETURNING observation_id;
            """,
            (payload.approver_name, observation_id),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=400, detail="No pending resolution request for this incident")
        conn.commit()
        return _fetch_incident(conn, observation_id)


def _packet_observed_at(packet_time: str, received_at: datetime) -> datetime:
    try:
        hour, minute = map(int, packet_time.split(":"))
        jst = timezone(timedelta(hours=9))
        received_jst = received_at.astimezone(jst)
        observed_jst = received_jst.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if observed_jst > received_jst:
            observed_jst -= timedelta(days=1)
        return observed_jst.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return received_at


def _current_utc_time() -> datetime:
    return datetime.now(timezone.utc)


# v1の重複判定(従来どおり): v1には (device_id, install_id, sequence) のような端末側の
# 識別子が無いため、サーバーの受信時刻を10秒ウィンドウに丸めたものとraw_packetで判定する。
# v2はこの仕組みを使わず、(device_id, install_id, sequence) の一意制約で判定する。
#
# tools/lora_serial_gateway.py re-sends a queued packet every >=5s until it is
# accepted, and the T-Beam itself may re-transmit the same button press over
# unreliable LoRa. Both are genuine retries of the *same* report and must
# still collapse to one observation. A window a little wider than that retry
# cadence absorbs those retries, while two separately-triggered reports that
# happen to carry identical field values (e.g. two REQ_WATER presses minutes
# apart with unchanged counts) fall in different windows and are both kept.
EMERGENCY_PACKET_DEDUP_WINDOW_SECONDS = 10

# reported_at(端末時計)と hub_received_at の差がこれを超えたら端末時計を信用しない。
PACKET_TIME_TRUST_MAX_SKEW_SECONDS = 600

JST = timezone(timedelta(hours=9))
V1_PACKET_FORMAT = "version|shelter_code|packet_time|people_count|water_stock|status|request_code"
V1_PACKET_EXAMPLE = "v1|AIT001|21:04|170|18|WARNING|REQ_WATER"
V2_PACKET_FORMAT = (
    "v2|device_id|key_id|install_id|sequence|reported_at|shelter_code|"
    "people_count|water_stock|status|request_code|hmac"
)


def _emergency_packet_observation_digest(raw_packet: str, dedup_time: datetime) -> str:
    # 以前はraw_packet+日付(日単位)でハッシュ化していたため、packet_timeが同じ分に
    # 収まっただけの別々の正当な報告まで衝突していた。受信時刻を秒単位の短いウィンドウに
    # 丸めてハッシュに含めることで、短時間の再送・連打だけを対象にする。
    dedup_bucket = int(dedup_time.timestamp() // EMERGENCY_PACKET_DEDUP_WINDOW_SECONDS)
    return hashlib.sha256(f"{raw_packet}:{dedup_bucket}".encode()).hexdigest()


def _packet_format_error(exc: ValueError, expected_format: str) -> HTTPException:
    detail = {
        "error": "Invalid LoRa packet format",
        "code": "PACKET_FORMAT_INVALID",
        "message": str(exc),
        "expected_format": expected_format,
    }
    if expected_format == V1_PACKET_FORMAT:
        detail["example"] = V1_PACKET_EXAMPLE
    return HTTPException(status_code=400, detail=detail)


def _hub_received_at(value: datetime | None, now_utc: datetime) -> datetime:
    if value is None:
        return now_utc
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


@app.post(
    "/api/emergency-packets",
    response_model=EmergencyPacket,
    status_code=201,
    dependencies=[Depends(require_gateway_key)],
)
def create_emergency_packet(payload: EmergencyPacketCreate) -> dict:
    now_utc = _current_utc_time()
    hub_received_at = _hub_received_at(payload.hub_received_at, now_utc)
    version = packet_version(payload.packet)
    if version == "v2":
        return _create_emergency_packet_v2(payload.packet, hub_received_at)
    if version == "v1" and not get_settings().allow_v1_packets:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "Emergency Packet v1 is disabled",
                "code": "PACKET_VERSION_DISABLED",
                "expected_format": V2_PACKET_FORMAT,
            },
        )
    return _create_emergency_packet_v1(payload.packet, now_utc, hub_received_at)


def _create_emergency_packet_v1(raw: str, now_utc: datetime, hub_received_at: datetime) -> dict:
    try:
        packet = parse_emergency_packet(raw)
    except ValueError as exc:
        raise _packet_format_error(exc, V1_PACKET_FORMAT) from exc

    received_date_jst = now_utc.astimezone(JST).strftime("%Y-%m-%d")
    digest = hashlib.sha256(f"{packet.raw_packet}{received_date_jst}".encode()).hexdigest()
    packet_id = f"EP-{digest[:16]}"

    with get_conn() as conn:
        shelter = conn.execute("SELECT id FROM shelters WHERE id = %s;", (packet.shelter_code,)).fetchone()
        shelter_id = shelter["id"] if shelter else None
        row = conn.execute(
            """
            INSERT INTO emergency_packets (
                id, version, shelter_code, shelter_id, packet_time,
                people_count, water_stock, status, request_code, raw_packet,
                hub_received_at, signature_status
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'UNSIGNED_V1')
            ON CONFLICT (id) DO UPDATE SET raw_packet = EXCLUDED.raw_packet
            RETURNING *;
            """,
            (
                packet_id,
                packet.version,
                packet.shelter_code,
                shelter_id,
                packet.packet_time,
                packet.people_count,
                packet.water_stock,
                packet.status,
                packet.request_code,
                packet.raw_packet,
                hub_received_at,
            ),
        ).fetchone()

        if shelter_id is not None:
            observed_at = _packet_observed_at(packet.packet_time, row["received_at"])
            # v1の重複判定はサーバー受信時刻(now_utc)の10秒ウィンドウ。hub_received_atは使わない。
            event_digest = _emergency_packet_observation_digest(packet.raw_packet, now_utc)
            conn.execute(
                """
                INSERT INTO observations (
                    id, shelter_id, client_event_id, people_count, water_stock,
                    urgency, memo, observed_at, reporter_name, reporter_type,
                    verification_status, source, signature_status
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'LoRa Packet',
                        'LORA_GATEWAY', 'UNVERIFIED', 'emergency_packet', 'UNSIGNED_V1')
                ON CONFLICT (client_event_id) DO NOTHING;
                """,
                (
                    f"OBS-{uuid4().hex}",
                    shelter_id,
                    f"LORA-{event_digest[:16]}",
                    packet.people_count,
                    packet.water_stock,
                    packet.status,
                    f"[LoRa] Status: {packet.status}, Req: {packet.request_code}",
                    observed_at,
                ),
            )
        conn.commit()
        return row


def _record_packet_security_event(
    conn,
    event_type: str,
    reason: str,
    packet: ParsedEmergencyPacketV2,
    hub_received_at: datetime,
    existing_packet_id: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO packet_security_events (
            id, event_type, reason, device_id, key_id, install_id, sequence,
            raw_packet, existing_packet_id, hub_received_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s);
        """,
        (
            f"PSE-{uuid4().hex}",
            event_type,
            reason,
            packet.device_id,
            packet.key_id,
            packet.install_id,
            packet.sequence,
            packet.raw_packet,
            existing_packet_id,
            hub_received_at,
        ),
    )
    # 鍵やHMACの期待値はログに出さない。識別子と理由だけを残す。
    logger.warning(
        "Emergency Packet security event %s reason=%s device_id=%s key_id=%s install_id=%s sequence=%s",
        event_type,
        reason,
        packet.device_id,
        packet.key_id,
        packet.install_id,
        packet.sequence,
    )


def _authenticate_packet_v2(packet: ParsedEmergencyPacketV2) -> str | None:
    """認証失敗の理由を返す(成功ならNone)。理由は監査ログ用で、レスポンスには出さない。"""
    try:
        registry = load_device_key_registry()
    except PacketKeyConfigError:
        logger.error("Emergency Packet device key ledger is misconfigured")
        raise HTTPException(status_code=503, detail="Emergency Packet device key ledger is unavailable") from None
    key = registry.lookup(packet.device_id, packet.key_id)
    if isinstance(key, KeyLookupFailure):
        return key.value
    if not verify_packet_hmac(key, packet):
        return "HMAC_MISMATCH"
    return None


def _create_emergency_packet_v2(raw: str, hub_received_at: datetime) -> dict:
    # 形式検証はHMAC検証より前に行う(形式が不正な入力では鍵を引かない)。
    try:
        packet = parse_emergency_packet_v2(raw)
    except ValueError as exc:
        raise _packet_format_error(exc, V2_PACKET_FORMAT) from exc

    auth_failure = _authenticate_packet_v2(packet)
    if auth_failure is not None:
        # 認証に失敗したPacketは、CRITICALでも emergency_packets / observations に入れない。
        with get_conn() as conn:
            _record_packet_security_event(conn, "PACKET_AUTH_FAILED", auth_failure, packet, hub_received_at)
            conn.commit()
        # Gateway Key不正(401)と区別する。ゲートウェイは403を「このPacketだけ破棄」と扱える。
        raise HTTPException(
            status_code=403,
            detail={"error": "Emergency Packet authentication failed", "code": "PACKET_AUTH_FAILED"},
        )

    skew = abs((packet.reported_at - hub_received_at).total_seconds())
    time_trust = "UNTRUSTED" if skew > PACKET_TIME_TRUST_MAX_SKEW_SECONDS else "TRUSTED"
    observed_at = hub_received_at if time_trust == "UNTRUSTED" else packet.reported_at
    dedup_key = f"v2|{packet.device_id}|{packet.install_id}|{packet.sequence}"
    packet_id = f"EP-{hashlib.sha256(dedup_key.encode()).hexdigest()[:16]}"

    with get_conn() as conn:
        shelter = conn.execute("SELECT id FROM shelters WHERE id = %s;", (packet.shelter_code,)).fetchone()
        shelter_id = shelter["id"] if shelter else None
        # 同じキーが同時に来ても、片方だけが入る(もう片方は既存行の確認へ進む)。
        # id は重複判定キーから作るので、同時に来ると主キー(id)の衝突が先に起きることがある。
        # 対象を指定しない ON CONFLICT DO NOTHING で、主キーと (device_id, install_id, sequence) の両方の衝突を吸収する。
        row = conn.execute(
            """
            INSERT INTO emergency_packets (
                id, version, shelter_code, shelter_id, packet_time,
                people_count, water_stock, status, request_code, raw_packet,
                device_id, key_id, install_id, sequence,
                reported_at, hub_received_at, time_trust, signature_status
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, 'SIGNATURE_VALID')
            ON CONFLICT DO NOTHING
            RETURNING *;
            """,
            (
                packet_id,
                packet.version,
                packet.shelter_code,
                shelter_id,
                # 既存のpacket_time(HH:MM, JST)列との互換のため、reported_atから埋める。
                packet.reported_at.astimezone(JST).strftime("%H:%M"),
                packet.people_count,
                packet.water_stock,
                packet.status,
                packet.request_code,
                packet.raw_packet,
                packet.device_id,
                packet.key_id,
                packet.install_id,
                packet.sequence,
                packet.reported_at,
                hub_received_at,
                time_trust,
            ),
        ).fetchone()

        if row is None:
            existing = conn.execute(
                """
                SELECT * FROM emergency_packets
                WHERE device_id = %s AND install_id = %s AND sequence = %s;
                """,
                (packet.device_id, packet.install_id, packet.sequence),
            ).fetchone()
            if existing is None:
                # 衝突を吸収したのに既存の行が見つからない(id だけが別の行と重なった、など)。黙って捨てない。
                conn.rollback()
                logger.error(
                    "Emergency Packet insert conflicted but no existing row was found: "
                    "packet_id=%s device_id=%s install_id=%s sequence=%s",
                    packet_id,
                    packet.device_id,
                    packet.install_id,
                    packet.sequence,
                )
                raise HTTPException(status_code=500, detail="Emergency Packet could not be stored")
            if existing["raw_packet"] == packet.raw_packet:
                # 同一キー・同一内容は再送。v1の再送と同じく既存の行を201で返す。
                conn.commit()
                return existing
            _record_packet_security_event(
                conn, "PACKET_DUPLICATE_CONFLICT", "CONTENT_MISMATCH", packet, hub_received_at, existing["id"]
            )
            conn.commit()
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "Emergency Packet sequence already used with different content",
                    "code": "PACKET_DUPLICATE_CONFLICT",
                    "packet_id": existing["id"],
                },
            )

        if shelter_id is not None:
            # 署名が正しくても verification_status(本部職員による確認)は従来どおり UNVERIFIED。
            observation_id = f"OBS-{uuid4().hex}"
            conn.execute(
                """
                INSERT INTO observations (
                    id, shelter_id, client_event_id, people_count, water_stock,
                    urgency, memo, observed_at, reporter_name, reporter_type,
                    verification_status, source, signature_status
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'LoRa Packet',
                        'LORA_GATEWAY', 'UNVERIFIED', 'emergency_packet', 'SIGNATURE_VALID');
                """,
                (
                    observation_id,
                    shelter_id,
                    f"LORA-{packet_id}",
                    packet.people_count,
                    packet.water_stock,
                    packet.status,
                    f"[LoRa] Status: {packet.status}, Req: {packet.request_code}",
                    observed_at,
                ),
            )
            row = conn.execute(
                "UPDATE emergency_packets SET observation_id = %s WHERE id = %s RETURNING *;",
                (observation_id, row["id"]),
            ).fetchone()
        conn.commit()
        return row


@app.get("/api/emergency-packets", response_model=list[EmergencyPacket])
def emergency_packets(_: AuthUser = Depends(require_hq)) -> list[dict]:
    with get_conn() as conn:
        return list(conn.execute("SELECT * FROM emergency_packets ORDER BY received_at DESC LIMIT 50;"))
