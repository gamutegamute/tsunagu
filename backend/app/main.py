from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.db import get_conn, init_db
from app.emergency_packet import parse_emergency_packet
from app.models import (
    EmergencyPacket,
    EmergencyPacketCreate,
    Observation,
    ObservationCreate,
    Shelter,
    ShelterCreate,
    ShelterStatus,
)
from app.status import decide_request_code, decide_status

app = FastAPI(title="ShelterOS", version="0.8.0")

APP_FILE = Path(__file__).resolve()
FRONTEND_CANDIDATES = [
    APP_FILE.parents[1] / "frontend",
    APP_FILE.parents[2] / "frontend" / "dist",
    APP_FILE.parents[2] / "frontend",
]

# Docker実行時とローカル実行時でfrontendの配置が違うため、存在するindex.htmlを優先して使う。
FRONTEND_DIR = next(
    (path for path in FRONTEND_CANDIDATES if (path / "index.html").exists()),
    FRONTEND_CANDIDATES[0],
)


@app.on_event("startup")
def startup() -> None:
    init_db()


if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/shelters", response_model=list[Shelter])
def list_shelters() -> list[dict]:
    with get_conn() as conn:
        return list(conn.execute("SELECT * FROM shelters ORDER BY id;"))


@app.post("/api/shelters", response_model=Shelter, status_code=201)
def create_shelter(payload: ShelterCreate) -> dict:
    shelter_id = f"SH-{uuid4().hex[:8].upper()}"
    with get_conn() as conn:
        row = conn.execute(
            """
            INSERT INTO shelters (id, name, location)
            VALUES (%s, %s, %s)
            RETURNING *;
            """,
            (shelter_id, payload.name, payload.location),
        ).fetchone()
        conn.commit()
        return row


@app.post("/api/observations", response_model=Observation, status_code=201)
def create_observation(payload: ObservationCreate) -> dict:
    observed_at = payload.observed_at or datetime.now(timezone.utc)
    observation_id = f"OBS-{uuid4().hex}"
    with get_conn() as conn:
        shelter = conn.execute("SELECT id FROM shelters WHERE id = %s;", (payload.shelter_id,)).fetchone()
        if shelter is None:
            raise HTTPException(status_code=404, detail="Shelter not found")

        existing = conn.execute(
            "SELECT * FROM observations WHERE client_event_id = %s;",
            (payload.client_event_id,),
        ).fetchone()
        if existing is not None:
            return existing

        row = conn.execute(
            """
            INSERT INTO observations (
                id, shelter_id, client_event_id, people_count, water_stock,
                urgency, memo, observed_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING *;
            """,
            (
                observation_id,
                payload.shelter_id,
                payload.client_event_id,
                payload.people_count,
                payload.water_stock,
                payload.urgency,
                payload.memo,
                observed_at,
            ),
        ).fetchone()
        conn.commit()
        return row


@app.get("/api/observations/latest", response_model=list[Observation])
def latest_observations() -> list[dict]:
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
def dashboard() -> list[dict]:
    with get_conn() as conn:
        rows = list(
            conn.execute(
                """
                SELECT
                    s.id AS shelter_id,
                    s.name,
                    s.location,
                    s.created_at AS shelter_created_at,
                    o.id AS observation_id,
                    o.client_event_id,
                    o.people_count,
                    o.water_stock,
                    o.urgency,
                    o.memo,
                    o.observed_at,
                    o.created_at AS observation_created_at
                FROM shelters s
                LEFT JOIN LATERAL (
                    SELECT *
                    FROM observations
                    WHERE shelter_id = s.id
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
                },
                "latest_observation": observation,
                "status": status,
                "request_code": decide_request_code(water_stock=row["water_stock"], status=status),
            }
        )
    return items


@app.post("/api/emergency-packets", response_model=EmergencyPacket, status_code=201)
def create_emergency_packet(payload: EmergencyPacketCreate) -> dict:
    try:
        packet = parse_emergency_packet(payload.packet)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    packet_id = f"EP-{uuid4().hex}"
    with get_conn() as conn:
        shelter = conn.execute("SELECT id FROM shelters WHERE id = %s;", (packet.shelter_code,)).fetchone()
        shelter_id = shelter["id"] if shelter is not None else None

        # LoRa親機から届いた最低限の情報を、通常報告とは別の受信ログとして残す。
        row = conn.execute(
            """
            INSERT INTO emergency_packets (
                id, version, shelter_code, shelter_id, packet_time,
                people_count, water_stock, status, request_code, raw_packet
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
        conn.commit()
        return row


@app.get("/api/emergency-packets", response_model=list[EmergencyPacket])
def emergency_packets() -> list[dict]:
    with get_conn() as conn:
        return list(conn.execute("SELECT * FROM emergency_packets ORDER BY received_at DESC LIMIT 50;"))
