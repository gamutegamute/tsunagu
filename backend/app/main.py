from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Response
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
@app.get("/field-report", include_in_schema=False)
@app.get("/dashboard", include_in_schema=False)
@app.get("/dev-preview", include_in_schema=False)
@app.get("/incident", include_in_schema=False)
@app.get("/history", include_in_schema=False)
@app.get("/dashboard/timeline", include_in_schema=False)
@app.get("/dashboard/shelters/{shelter_id}", include_in_schema=False)
def index(shelter_id: str | None = None) -> FileResponse:
    # 日本語コメント: SPAの各画面用ルートに対して index.html を返す
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/health")
def health(response: Response) -> dict[str, str]:
    # 日本語コメント: データベースへの疎通確認を行うヘルスチェック
    db_status = "ok"
    try:
        with get_conn() as conn:
            conn.execute("SELECT 1;").fetchone()
    except Exception:
        db_status = "error"

    if db_status == "error":
        response.status_code = 500
        return {"status": "error", "database": "error"}

    return {"status": "ok", "database": "ok"}


@app.get("/api/shelters", response_model=list[Shelter])
def list_shelters() -> list[dict]:
    with get_conn() as conn:
        return list(conn.execute("SELECT * FROM shelters ORDER BY id;"))


@app.post("/api/shelters", response_model=Shelter, status_code=201)
def create_shelter(payload: ShelterCreate) -> dict:
    with get_conn() as conn:
        shelter_id = payload.id
        if not shelter_id:
            # 日本語コメント: ID指定がない場合は自動生成する
            shelter_id = f"SH-{uuid4().hex[:8].upper()}"
        else:
            # 日本語コメント: 重複する避難所IDがあるかチェックする
            existing = conn.execute("SELECT id FROM shelters WHERE id = %s;", (shelter_id,)).fetchone()
            if existing is not None:
                raise HTTPException(
                    status_code=400,
                    detail={
                        "error": "Shelter already exists",
                        "message": f"避難所ID '{shelter_id}' はすでに登録されています。"
                    }
                )

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
        shelter_id_val = payload.shelter_id or payload.shelter_code
        shelter = conn.execute("SELECT id FROM shelters WHERE id = %s;", (shelter_id_val,)).fetchone()
        if shelter is None:
            # 日本語コメント: 避難所が見つからない場合の詳細エラーレスポンス
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "Shelter not found",
                    "message": f"避難所 '{shelter_id_val}' はデータベースに登録されていません。",
                    "hint": "登録済みの避難所IDは GET /api/shelters から確認できます。"
                }
            )

        resolved_shelter_id = shelter["id"]

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
                urgency, memo, observed_at, reporter_name, source
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING *;
            """,
            (
                observation_id,
                resolved_shelter_id,
                payload.client_event_id,
                payload.people_count,
                payload.water_stock,
                payload.urgency,
                payload.memo,
                observed_at,
                payload.reporter_name,
                payload.source,
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
                    o.created_at AS observation_created_at,
                    o.reporter_name,
                    o.source
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
                "reporter_name": row["reporter_name"],
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
        # 日本語コメント: 不正なLoRaパケットフォーマットに対する詳細エラー
        raise HTTPException(
            status_code=400,
            detail={
                "error": "Invalid LoRa packet format",
                "message": str(exc),
                "expected_format": "version|shelter_code|packet_time|people_count|water_stock|status|request_code",
                "example": "v1|AIT001|21:04|170|18|WARNING|REQ_WATER"
            }
        ) from exc

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

        # shelter_id が特定できた場合、observations テーブルにも同期する
        if shelter_id is not None:
            # タイムスタンプの組み立て (日本時間 JST 想定)
            # LoRaパケットには時刻のみが含まれているため、受信した日(JST)の時刻として補完する。
            # 日をまたいだ遅延などで、作成した日時が受信日時より未来になった場合は1日前として処理する。
            try:
                h, m = map(int, packet.packet_time.split(":"))
                from datetime import timedelta
                # Postgresから取得した TIMESTAMPTZ (received_at) を JST (UTC+9) に変換
                jst = timezone(timedelta(hours=9))
                received_jst = row["received_at"].astimezone(jst)
                observed_jst = received_jst.replace(hour=h, minute=m, second=0, microsecond=0)
                if observed_jst > received_jst:
                    # 未来の日時になった場合は前日とみなす
                    observed_jst -= timedelta(days=1)
                observed_at = observed_jst.astimezone(timezone.utc)
            except Exception:
                observed_at = row["received_at"]

            # LoRa status と通常報告の urgency は同じ4段階で扱う。
            urgency_map = {
                "NORMAL": "NORMAL",
                "WARNING": "WARNING",
                "ALERT": "ALERT",
                "CRITICAL": "CRITICAL",
            }
            urgency = urgency_map.get(packet.status, "NORMAL")

            # client_event_id の生成 (LORA-<sha256の先頭16文字>)
            # 重複挿入を防ぐための冪等キー。パケット情報と算出日付からハッシュ化する。
            import hashlib
            observed_date_str = observed_at.date().isoformat()
            packet_data_str = f"{packet.shelter_code}:{packet.packet_time}:{packet.people_count}:{packet.water_stock}:{packet.status}:{packet.request_code}:{observed_date_str}"
            packet_hash = hashlib.sha256(packet_data_str.encode("utf-8")).hexdigest()
            client_event_id = f"LORA-{packet_hash[:16]}"

            # 重複チェック
            existing_obs = conn.execute(
                "SELECT id FROM observations WHERE client_event_id = %s;", (client_event_id,)
            ).fetchone()

            if existing_obs is None:
                observation_id = f"OBS-{uuid4().hex}"
                memo = f"[LoRa] Status: {packet.status}, Req: {packet.request_code}"
                conn.execute(
                    """
                    INSERT INTO observations (
                        id, shelter_id, client_event_id, people_count, water_stock,
                        urgency, memo, observed_at, reporter_name, source
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        observation_id,
                        shelter_id,
                        client_event_id,
                        packet.people_count,
                        packet.water_stock,
                        urgency,
                        memo,
                        observed_at,
                        "LoRa Packet",
                        "emergency_packet",
                    ),
                )

        conn.commit()
        return row


@app.get("/api/emergency-packets", response_model=list[EmergencyPacket])
def emergency_packets() -> list[dict]:
    with get_conn() as conn:
        return list(conn.execute("SELECT * FROM emergency_packets ORDER BY received_at DESC LIMIT 50;"))
