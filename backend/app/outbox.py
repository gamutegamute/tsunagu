"""クラウドへの配送(Outbox)の設定・登録・状態判定。

配送はローカルからクラウドへの一方向のみ。クラウドからローカルへの書き戻しはしない。
送信そのものは app/outbox_worker.py が行う。仕様は docs/outbox.md。

宛先ごとのGateway Keyは、OUTBOX_DESTINATIONS の key_env が指す環境変数から、ワーカーだけが読む。
鍵の値は、DB・ログ・例外メッセージ・APIのレスポンスに出さないこと。
"""

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from re import fullmatch
from urllib.parse import urlsplit
from uuid import uuid4

logger = logging.getLogger(__name__)

# 配送できるのは、ローカルで署名を検証できた v2 の報告だけ(v1 はクラウドが拒否する)。
FORWARDABLE_SIGNATURE_STATUS = "SIGNATURE_VALID"

OUTBOX_STATES = ("PENDING", "SENDING", "ACCEPTED", "QUARANTINED", "STOPPED")


class OutboxConfigError(RuntimeError):
    pass


def redact_url(url: str) -> str:
    """ログ・出力用に、URLのクレデンシャル(user:pass@)とクエリ・フラグメントを伏せる。"""
    try:
        parts = urlsplit(url)
        host = parts.hostname or ""
        port = f":{parts.port}" if parts.port else ""
    except ValueError:
        return "<invalid url>"
    credentials = "<redacted>@" if parts.username or parts.password else ""
    query = "?<redacted>" if parts.query else ""
    fragment = "#<redacted>" if parts.fragment else ""
    return f"{parts.scheme}://{credentials}{host}{port}{parts.path}{query}{fragment}"


@dataclass(frozen=True)
class OutboxDestination:
    id: str
    base_url: str = field(repr=False)
    key_env: str

    @property
    def display_url(self) -> str:
        return redact_url(self.base_url)

    def load_key(self) -> str:
        return os.getenv(self.key_env, "")

    def __repr__(self) -> str:
        return f"OutboxDestination(id={self.id!r}, base_url={self.display_url!r}, key_env={self.key_env!r})"


@dataclass(frozen=True)
class OutboxSettings:
    enabled: bool
    destinations: tuple[OutboxDestination, ...]
    # 以下のデフォルトは、デモ用の暫定値(docs/outbox.md)。実運用では回線に合わせて見直す。
    batch_size: int = 10
    http_timeout_seconds: float = 10.0
    lease_seconds: int = 60
    probe_interval_seconds: int = 30
    poll_interval_seconds: float = 2.0
    backoff_base_seconds: float = 5.0
    backoff_max_seconds: float = 300.0
    status_down_seconds: int = 120
    status_delayed_latency_ms: int = 5000
    status_delayed_pending_seconds: int = 60

    @property
    def active(self) -> bool:
        return self.enabled and bool(self.destinations)


def _positive_number(name: str, default: str, cast=float):
    raw = os.getenv(name, default).strip()
    try:
        value = cast(raw)
    except ValueError:
        raise OutboxConfigError(f"{name} must be a positive number") from None
    if value <= 0:
        raise OutboxConfigError(f"{name} must be a positive number")
    return value


def _parse_destinations(raw: str) -> tuple[OutboxDestination, ...]:
    if not raw.strip():
        return ()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        raise OutboxConfigError("OUTBOX_DESTINATIONS is not valid JSON") from None
    if not isinstance(data, list):
        raise OutboxConfigError("OUTBOX_DESTINATIONS must be a JSON array")

    destinations: list[OutboxDestination] = []
    seen: set[str] = set()
    for index, item in enumerate(data):
        if not isinstance(item, dict) or set(item) != {"id", "base_url", "key_env"}:
            raise OutboxConfigError(
                f"OUTBOX_DESTINATIONS[{index}] must be an object with id, base_url and key_env only"
            )
        destination_id, base_url, key_env = item["id"], item["base_url"], item["key_env"]
        if not isinstance(destination_id, str) or not fullmatch(r"[a-z0-9][a-z0-9_-]{0,62}", destination_id):
            raise OutboxConfigError(f"OUTBOX_DESTINATIONS[{index}].id is invalid")
        if destination_id in seen:
            raise OutboxConfigError(f"OUTBOX_DESTINATIONS has a duplicate id: {destination_id}")
        if not isinstance(key_env, str) or not fullmatch(r"[A-Z_][A-Z0-9_]{0,127}", key_env):
            raise OutboxConfigError(f"OUTBOX_DESTINATIONS[{index}].key_env is invalid")
        if not isinstance(base_url, str):
            raise OutboxConfigError(f"OUTBOX_DESTINATIONS[{index}].base_url is invalid")
        try:
            parts = urlsplit(base_url)
            valid_url = parts.scheme in {"http", "https"} and bool(parts.hostname)
        except ValueError:
            valid_url = False
        if not valid_url:
            # URLにクレデンシャルが含まれ得るので、値はメッセージに出さない。
            raise OutboxConfigError(f"OUTBOX_DESTINATIONS[{index}].base_url must be an http(s) URL")
        seen.add(destination_id)
        destinations.append(OutboxDestination(id=destination_id, base_url=base_url, key_env=key_env))
    return tuple(destinations)


def load_outbox_settings(*, require_keys: bool = False) -> OutboxSettings:
    """設定を読む。require_keys=True(ワーカー)のときは、有効な宛先の鍵が設定されているかも確認する。"""
    enabled = os.getenv("OUTBOX_ENABLED", "false").strip().lower() == "true"
    settings = OutboxSettings(
        enabled=enabled,
        destinations=_parse_destinations(os.getenv("OUTBOX_DESTINATIONS", "")),
        batch_size=_positive_number("OUTBOX_BATCH_SIZE", "10", int),
        http_timeout_seconds=_positive_number("OUTBOX_HTTP_TIMEOUT_SECONDS", "10"),
        lease_seconds=_positive_number("OUTBOX_LEASE_SECONDS", "60", int),
        probe_interval_seconds=_positive_number("OUTBOX_PROBE_INTERVAL_SECONDS", "30", int),
        poll_interval_seconds=_positive_number("OUTBOX_POLL_INTERVAL_SECONDS", "2"),
        status_down_seconds=_positive_number("OUTBOX_STATUS_DOWN_SECONDS", "120", int),
        status_delayed_latency_ms=_positive_number("OUTBOX_STATUS_DELAYED_LATENCY_MS", "5000", int),
        status_delayed_pending_seconds=_positive_number("OUTBOX_STATUS_DELAYED_PENDING_SECONDS", "60", int),
    )
    if require_keys and settings.active:
        missing = [destination.key_env for destination in settings.destinations if not destination.load_key()]
        if missing:
            # 環境変数の名前だけを出す(値は出さない)。
            raise OutboxConfigError(f"Gateway key environment variable is not set: {', '.join(missing)}")
    return settings


def register_packet_for_delivery(conn, emergency_packet_id: str, settings: OutboxSettings) -> int:
    """宛先ごとに delivery_outbox へ登録する。既にある組は作らない。登録した件数を返す。"""
    created = 0
    for destination in settings.destinations:
        row = conn.execute(
            """
            INSERT INTO delivery_outbox (id, emergency_packet_id, destination_id, state, next_attempt_at)
            VALUES (%s, %s, %s, 'PENDING', now())
            ON CONFLICT (emergency_packet_id, destination_id) DO NOTHING
            RETURNING id;
            """,
            (f"OUT-{uuid4().hex}", emergency_packet_id, destination.id),
        ).fetchone()
        created += 1 if row else 0
    return created


def register_packet_safely(conn, packet_row: dict) -> None:
    """報告の受理と同じトランザクションで登録する。失敗しても報告の受理は失敗させない。

    SAVEPOINT の中で登録するので、失敗したときは登録だけが取り消される。
    失敗はログ(`Outbox registration failed`)に残す。検知方法は docs/outbox.md。
    """
    if packet_row.get("signature_status") != FORWARDABLE_SIGNATURE_STATUS:
        return
    try:
        settings = load_outbox_settings()
    except OutboxConfigError as exc:
        logger.error("Outbox registration failed for packet_id=%s: %s", packet_row["id"], exc)
        return
    if not settings.active:
        return
    try:
        with conn.transaction():
            register_packet_for_delivery(conn, packet_row["id"], settings)
    except Exception as exc:  # noqa: BLE001 - 報告の受理を優先する
        logger.error(
            "Outbox registration failed for packet_id=%s: %s", packet_row["id"], exc.__class__.__name__
        )


# ---- 状態の判定(GET /api/destinations/status) ----


def _destination_status_row(conn, destination_id: str) -> dict:
    return conn.execute(
        """
        SELECT
            count(*) FILTER (WHERE state = 'PENDING') AS queue_depth,
            count(*) FILTER (WHERE state = 'SENDING') AS sending_count,
            count(*) FILTER (WHERE state = 'STOPPED') AS stopped_count,
            count(*) FILTER (WHERE state = 'QUARANTINED') AS quarantined_count,
            count(*) FILTER (WHERE state = 'ACCEPTED') AS accepted_count,
            min(created_at) FILTER (WHERE state IN ('PENDING', 'SENDING')) AS oldest_pending_at
        FROM delivery_outbox
        WHERE destination_id = %s;
        """,
        (destination_id,),
    ).fetchone()


def _attempt_summary(conn, destination_id: str) -> dict:
    return conn.execute(
        """
        SELECT
            count(*) AS attempt_count,
            max(attempted_at) FILTER (WHERE kind = 'DELIVERY' AND outcome = 'ACCEPTED') AS last_success_at,
            max(attempted_at) FILTER (WHERE outcome IN ('ACCEPTED', 'PROBE_OK')) AS last_reachable_at,
            (SELECT latency_ms FROM delivery_attempts
              WHERE destination_id = %s AND latency_ms IS NOT NULL
              ORDER BY attempted_at DESC, id DESC LIMIT 1) AS last_latency_ms,
            (SELECT error_code FROM delivery_attempts
              WHERE destination_id = %s AND kind = 'DELIVERY' AND error_code IS NOT NULL
              ORDER BY attempted_at DESC, id DESC LIMIT 1) AS last_error_code,
            max(attempted_at) FILTER (WHERE kind = 'DELIVERY' AND error_code IS NOT NULL) AS last_error_at
        FROM delivery_attempts
        WHERE destination_id = %s;
        """,
        (destination_id, destination_id, destination_id),
    ).fetchone()


def decide_destination_state(summary: dict, settings: OutboxSettings, now: datetime) -> str:
    if summary["stopped_count"] > 0:
        return "AUTH_ERROR"
    if summary["attempt_count"] == 0:
        return "UNKNOWN"
    last_reachable_at = summary["last_reachable_at"]
    if last_reachable_at is None or now - last_reachable_at > timedelta(seconds=settings.status_down_seconds):
        return "DOWN"
    latency = summary["last_latency_ms"]
    oldest = summary["oldest_pending_at"]
    if (latency is not None and latency > settings.status_delayed_latency_ms) or (
        oldest is not None and now - oldest > timedelta(seconds=settings.status_delayed_pending_seconds)
    ):
        return "DELAYED"
    return "NORMAL"


def destination_statuses(conn, settings: OutboxSettings, now: datetime) -> list[dict]:
    configured = [destination.id for destination in settings.destinations]
    # 設定から外した宛先にも行が残っていれば、configured=false で表示する(保持している行を見えなくしない)。
    leftover = [
        row["destination_id"]
        for row in conn.execute("SELECT DISTINCT destination_id FROM delivery_outbox ORDER BY destination_id;")
        if row["destination_id"] not in configured
    ]
    results = []
    for destination_id in configured + leftover:
        summary = {**_destination_status_row(conn, destination_id), **_attempt_summary(conn, destination_id)}
        quarantined_by_error = {
            row["error_code"]: row["count"]
            for row in conn.execute(
                """
                SELECT coalesce(last_error_code, 'UNKNOWN') AS error_code, count(*) AS count
                FROM delivery_outbox
                WHERE destination_id = %s AND state = 'QUARANTINED'
                GROUP BY 1 ORDER BY 1;
                """,
                (destination_id,),
            )
        }
        results.append(
            {
                "destination_id": destination_id,
                "configured": destination_id in configured,
                "state": decide_destination_state(summary, settings, now),
                "last_success_at": summary["last_success_at"],
                "last_reachable_at": summary["last_reachable_at"],
                "last_latency_ms": summary["last_latency_ms"],
                "queue_depth": summary["queue_depth"],
                "sending_count": summary["sending_count"],
                "stopped_count": summary["stopped_count"],
                "oldest_pending_at": summary["oldest_pending_at"],
                "accepted_count": summary["accepted_count"],
                "quarantined_count": summary["quarantined_count"],
                "quarantined_by_error_code": quarantined_by_error,
                "last_error_code": summary["last_error_code"],
                "last_error_at": summary["last_error_at"],
            }
        )
    return results


def packet_deliveries(conn, emergency_packet_id: str) -> list[dict]:
    rows = conn.execute(
        """
        SELECT id, destination_id, state, attempts, next_attempt_at, last_attempt_at,
               last_error_code, last_error_summary, accepted_at, created_at
        FROM delivery_outbox
        WHERE emergency_packet_id = %s
        ORDER BY destination_id;
        """,
        (emergency_packet_id,),
    ).fetchall()
    deliveries = []
    for row in rows:
        history = conn.execute(
            """
            SELECT attempted_at, outcome, http_status, latency_ms, error_code
            FROM delivery_attempts
            WHERE outbox_id = %s
            ORDER BY attempted_at, id;
            """,
            (row["id"],),
        ).fetchall()
        deliveries.append({**{key: value for key, value in row.items() if key != "id"}, "history": history})
    return deliveries
