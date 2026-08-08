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
from app.config import validate_runtime_settings
from app.db import get_conn, get_demo_data_counts, reset_demo_dataset, seed_demo_data
from app.emergency_packet import parse_emergency_packet
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
from app.status import decide_request_code, decide_status
from app.rate_limit import SlidingWindowRateLimiter

logger = logging.getLogger(__name__)
DEMO_RESET_CONFIRMATION = "TSUNAGUをリセット"


@asynccontextmanager
async def lifespan(_: FastAPI):
    validate_runtime_settings()
    seed_demo_data()
    yield


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


@app.post(
    "/api/emergency-packets",
    response_model=EmergencyPacket,
    status_code=201,
    dependencies=[Depends(require_gateway_key)],
)
def create_emergency_packet(payload: EmergencyPacketCreate) -> dict:
    try:
        packet = parse_emergency_packet(payload.packet)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "Invalid LoRa packet format",
                "message": str(exc),
                "expected_format": "version|shelter_code|packet_time|people_count|water_stock|status|request_code",
                "example": "v1|AIT001|21:04|170|18|WARNING|REQ_WATER",
            },
        ) from exc

    received_date_jst = datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d")
    digest = hashlib.sha256(f"{packet.raw_packet}{received_date_jst}".encode()).hexdigest()
    packet_id = f"EP-{digest[:16]}"

    with get_conn() as conn:
        shelter = conn.execute("SELECT id FROM shelters WHERE id = %s;", (packet.shelter_code,)).fetchone()
        shelter_id = shelter["id"] if shelter else None
        row = conn.execute(
            """
            INSERT INTO emergency_packets (
                id, version, shelter_code, shelter_id, packet_time,
                people_count, water_stock, status, request_code, raw_packet
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
            ),
        ).fetchone()

        if shelter_id is not None:
            observed_at = _packet_observed_at(packet.packet_time, row["received_at"])
            event_digest = hashlib.sha256(
                f"{packet.raw_packet}:{observed_at.date().isoformat()}".encode()
            ).hexdigest()
            conn.execute(
                """
                INSERT INTO observations (
                    id, shelter_id, client_event_id, people_count, water_stock,
                    urgency, memo, observed_at, reporter_name, reporter_type,
                    verification_status, source
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'LoRa Packet',
                        'LORA_GATEWAY', 'UNVERIFIED', 'emergency_packet')
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


@app.get("/api/emergency-packets", response_model=list[EmergencyPacket])
def emergency_packets(_: AuthUser = Depends(require_hq)) -> list[dict]:
    with get_conn() as conn:
        return list(conn.execute("SELECT * FROM emergency_packets ORDER BY received_at DESC LIMIT 50;"))
