"""クラウドへの配送ワーカー(Outbox)。

    python -m app.outbox_worker                       # ループ(OUTBOX_POLL_INTERVAL_SECONDS ごとに run_once)
    python -m app.outbox_worker once                  # 1周だけ
    python -m app.outbox_worker requeue --destination <id> --error-code <コード>
    python -m app.outbox_worker resume --destination <id>
    python -m app.outbox_worker backfill --destination <id> (--since <ISO8601> | --all) [--dry-run]

衛星回線のような細い回線を想定し、宛先ごとに1件ずつ(同時送信なし)送る。
宛先のGateway Keyはログ・DBに出さない。宛先のURLはログでは redact_url() で伏せる。
仕様は docs/outbox.md。
"""

import argparse
import logging
import random
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from re import fullmatch
from uuid import uuid4

import httpx

from app.db import get_conn
from app.outbox import OutboxConfigError, OutboxDestination, OutboxSettings, load_outbox_settings

logger = logging.getLogger("app.outbox_worker")
# httpx/httpcore は INFO/DEBUG で送信先のURLをそのまま出す(URLのクレデンシャルやクエリを含む)。
# 宛先のURLは redact_url() で伏せたものだけをログに出すため、これらは WARNING 以上に絞る。
for _noisy_logger in ("httpx", "httpcore"):
    logging.getLogger(_noisy_logger).setLevel(logging.WARNING)

# 応答に対する扱い。
ACCEPT = "ACCEPT"
QUARANTINE = "QUARANTINE"
STOP_DESTINATION = "STOP_DESTINATION"
RETRY = "RETRY"
RETRY_END_CYCLE = "RETRY_END_CYCLE"

EMERGENCY_PACKET_PATH = "/api/emergency-packets"
HEALTH_PATH = "/health"


@dataclass
class DeliveryResult:
    action: str
    error_code: str | None
    http_status: int | None
    latency_ms: int
    summary: str


@dataclass
class RunSummary:
    released_leases: int = 0
    probes: int = 0
    delivered: int = 0
    quarantined: int = 0
    retried: int = 0
    stopped_destinations: list[str] = field(default_factory=list)
    skipped_stopped_destinations: list[str] = field(default_factory=list)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _response_error_code(response: httpx.Response) -> str | None:
    """APIのエラーコード(detail.code)を取り出す。本文そのものはログ・DBに残さない。"""
    try:
        body = response.json()
    except ValueError:
        return None
    detail = body.get("detail") if isinstance(body, dict) else None
    code = detail.get("code") if isinstance(detail, dict) else None
    if isinstance(code, str) and fullmatch(r"[A-Z][A-Z0-9_]{0,63}", code):
        return code
    return None


def classify_response(response: httpx.Response) -> tuple[str, str | None]:
    status = response.status_code
    api_code = _response_error_code(response)
    if 200 <= status < 300:
        return ACCEPT, None
    if status in (400, 422):
        return QUARANTINE, api_code or f"HTTP_{status}"
    if status == 401:
        return STOP_DESTINATION, f"HTTP_{status}"
    if status == 403:
        if api_code == "PACKET_AUTH_FAILED":
            # この報告だけの問題(クラウド側の端末台帳など)。宛先は止めない。
            return QUARANTINE, "PACKET_AUTH_FAILED"
        return STOP_DESTINATION, f"HTTP_{status}"
    if status == 409:
        return QUARANTINE, api_code or f"HTTP_{status}"
    if status == 429 or 500 <= status < 600:
        return RETRY, f"HTTP_{status}"
    # 仕様に無い応答(リダイレクト、404など)は、宛先の設定異常とみなして止める(行は保持する)。
    return STOP_DESTINATION, f"HTTP_{status}"


def backoff_seconds(attempts: int, settings: OutboxSettings, rng: random.Random) -> float:
    """5秒から倍々で上限5分。ジッタは、その半分から全体の間でばらつかせる。"""
    exponent = max(attempts - 1, 0)
    ceiling = min(settings.backoff_max_seconds, settings.backoff_base_seconds * (2 ** min(exponent, 20)))
    return ceiling / 2 + rng.uniform(0, ceiling / 2)


def _attempt_id() -> str:
    # 同じ時刻(同じ周回)の試行でも、作った順に並ぶように、先頭に時刻(ns)を入れる。
    return f"ATT-{time.time_ns():020d}-{uuid4().hex[:8]}"


def _record_attempt(
    conn,
    *,
    outbox_id: str | None,
    destination_id: str,
    kind: str,
    attempted_at: datetime,
    outcome: str,
    http_status: int | None,
    latency_ms: int | None,
    error_code: str | None,
) -> None:
    conn.execute(
        """
        INSERT INTO delivery_attempts (
            id, outbox_id, destination_id, kind, attempted_at, outcome, http_status, latency_ms, error_code
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s);
        """,
        (_attempt_id(), outbox_id, destination_id, kind, attempted_at, outcome, http_status, latency_ms,
         error_code),
    )


def release_expired_leases(conn, now: datetime) -> int:
    """ワーカーが落ちて SENDING のまま残った行を、lease_until を過ぎたら PENDING に戻す。

    送信済みかどうかは分からないが、クラウドは同じ報告の再送を冪等に受理するので、送り直してよい。
    """
    rows = conn.execute(
        """
        UPDATE delivery_outbox
        SET state = 'PENDING', lease_until = NULL, next_attempt_at = %s,
            last_error_code = 'LEASE_EXPIRED', last_error_summary = 'lease expired while sending'
        WHERE state = 'SENDING' AND lease_until < %s
        RETURNING id, destination_id;
        """,
        (now, now),
    ).fetchall()
    for row in rows:
        logger.warning("Outbox lease expired; returned to PENDING: outbox_id=%s destination=%s",
                       row["id"], row["destination_id"])
    return len(rows)


def destination_is_stopped(conn, destination_id: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM delivery_outbox WHERE destination_id = %s AND state = 'STOPPED' LIMIT 1;",
        (destination_id,),
    ).fetchone()
    return row is not None


def claim_next(conn, destination_id: str, now: datetime, lease_seconds: int) -> dict | None:
    """期限の来た PENDING を、緊急度順 → hub_received_at 順に1件取り、SENDING にする。"""
    row = conn.execute(
        """
        SELECT o.id
        FROM delivery_outbox o
        JOIN emergency_packets p ON p.id = o.emergency_packet_id
        WHERE o.destination_id = %s AND o.state = 'PENDING' AND o.next_attempt_at <= %s
        ORDER BY CASE p.status
                   WHEN 'CRITICAL' THEN 0
                   WHEN 'ALERT' THEN 1
                   WHEN 'WARNING' THEN 2
                   ELSE 3
                 END,
                 p.hub_received_at NULLS LAST, o.created_at, o.id
        LIMIT 1
        FOR UPDATE OF o SKIP LOCKED;
        """,
        (destination_id, now),
    ).fetchone()
    if row is None:
        conn.commit()
        return None
    claimed = conn.execute(
        """
        UPDATE delivery_outbox o
        SET state = 'SENDING', lease_until = %s, attempts = o.attempts + 1, last_attempt_at = %s
        FROM emergency_packets p
        WHERE o.id = %s AND p.id = o.emergency_packet_id
        RETURNING o.id, o.emergency_packet_id, o.attempts, p.raw_packet, p.hub_received_at;
        """,
        (now + timedelta(seconds=lease_seconds), now, row["id"]),
    ).fetchone()
    conn.commit()
    return claimed


def send_packet(client: httpx.Client, destination: OutboxDestination, row: dict) -> DeliveryResult:
    """受け取った文字列(raw packet)をそのまま、hub_received_at と一緒に送る。"""
    body: dict[str, str] = {"packet": row["raw_packet"]}
    if row["hub_received_at"] is not None:
        body["hub_received_at"] = row["hub_received_at"].isoformat()
    url = destination.base_url.rstrip("/") + EMERGENCY_PACKET_PATH
    started = time.monotonic()
    try:
        # リダイレクトは追わない(別のホストへ鍵を送らないため)。
        response = client.post(
            url, json=body, headers={"X-Gateway-Key": destination.load_key()}, follow_redirects=False
        )
    except httpx.TimeoutException:
        latency = int((time.monotonic() - started) * 1000)
        return DeliveryResult(RETRY_END_CYCLE, "TIMEOUT", None, latency, "request timed out")
    except httpx.HTTPError as exc:
        latency = int((time.monotonic() - started) * 1000)
        return DeliveryResult(RETRY_END_CYCLE, "NETWORK_ERROR", None, latency, exc.__class__.__name__)
    latency = int((time.monotonic() - started) * 1000)
    action, error_code = classify_response(response)
    summary = f"HTTP {response.status_code}" + (f" {error_code}" if error_code else "")
    return DeliveryResult(action, error_code, response.status_code, latency, summary)


def apply_result(
    conn,
    destination: OutboxDestination,
    row: dict,
    result: DeliveryResult,
    now: datetime,
    settings: OutboxSettings,
    rng: random.Random,
) -> None:
    outcome_by_action = {
        ACCEPT: "ACCEPTED",
        QUARANTINE: "QUARANTINED",
        STOP_DESTINATION: "STOPPED",
        RETRY: "RETRY",
        RETRY_END_CYCLE: "RETRY",
    }
    if result.action == ACCEPT:
        conn.execute(
            """
            UPDATE delivery_outbox
            SET state = 'ACCEPTED', accepted_at = %s, lease_until = NULL,
                last_error_code = NULL, last_error_summary = NULL
            WHERE id = %s;
            """,
            (now, row["id"]),
        )
        # 複数の宛先がある場合は、最初にクラウドへ届いた時刻を残す。
        conn.execute(
            "UPDATE emergency_packets SET cloud_synced_at = coalesce(cloud_synced_at, %s) WHERE id = %s;",
            (now, row["emergency_packet_id"]),
        )
    elif result.action in (QUARANTINE, STOP_DESTINATION):
        state = "QUARANTINED" if result.action == QUARANTINE else "STOPPED"
        conn.execute(
            """
            UPDATE delivery_outbox
            SET state = %s, lease_until = NULL, last_error_code = %s, last_error_summary = %s
            WHERE id = %s;
            """,
            (state, result.error_code, result.summary, row["id"]),
        )
    else:
        delay = backoff_seconds(row["attempts"], settings, rng)
        conn.execute(
            """
            UPDATE delivery_outbox
            SET state = 'PENDING', lease_until = NULL, next_attempt_at = %s,
                last_error_code = %s, last_error_summary = %s
            WHERE id = %s;
            """,
            (now + timedelta(seconds=delay), result.error_code, result.summary, row["id"]),
        )
    _record_attempt(
        conn,
        outbox_id=row["id"],
        destination_id=destination.id,
        kind="DELIVERY",
        attempted_at=now,
        outcome=outcome_by_action[result.action],
        http_status=result.http_status,
        latency_ms=result.latency_ms,
        error_code=result.error_code,
    )
    conn.commit()

    if result.action == QUARANTINE:
        logger.warning("Outbox delivery quarantined: outbox_id=%s destination=%s error=%s",
                       row["id"], destination.id, result.error_code)
    elif result.action == STOP_DESTINATION:
        logger.error(
            "Outbox destination STOPPED (configuration error: gateway key or URL): destination=%s url=%s "
            "error=%s. Pending deliveries are kept. Fix the configuration, then run "
            "`python -m app.outbox_worker resume --destination %s`.",
            destination.id, destination.display_url, result.error_code, destination.id,
        )
    elif result.action in (RETRY, RETRY_END_CYCLE):
        logger.info("Outbox delivery will be retried: outbox_id=%s destination=%s error=%s",
                    row["id"], destination.id, result.error_code)


def probe_if_due(conn, client: httpx.Client, destination: OutboxDestination, now: datetime,
                 settings: OutboxSettings) -> bool:
    """GET {base_url}/health を鍵なしで呼び、kind=PROBE で記録する。STOPPED の宛先でも続ける。"""
    last = conn.execute(
        "SELECT max(attempted_at) AS last FROM delivery_attempts WHERE destination_id = %s AND kind = 'PROBE';",
        (destination.id,),
    ).fetchone()["last"]
    if last is not None and now - last < timedelta(seconds=settings.probe_interval_seconds):
        conn.commit()
        return False

    url = destination.base_url.rstrip("/") + HEALTH_PATH
    started = time.monotonic()
    http_status = None
    error_code = None
    try:
        response = client.get(url, follow_redirects=False)
        http_status = response.status_code
        outcome = "PROBE_OK" if 200 <= response.status_code < 300 else "PROBE_FAILED"
        if outcome == "PROBE_FAILED":
            error_code = f"HTTP_{response.status_code}"
    except httpx.TimeoutException:
        outcome, error_code = "PROBE_FAILED", "TIMEOUT"
    except httpx.HTTPError:
        outcome, error_code = "PROBE_FAILED", "NETWORK_ERROR"
    latency = int((time.monotonic() - started) * 1000)
    _record_attempt(
        conn,
        outbox_id=None,
        destination_id=destination.id,
        kind="PROBE",
        attempted_at=now,
        outcome=outcome,
        http_status=http_status,
        latency_ms=latency,
        error_code=error_code,
    )
    conn.commit()
    return True


def process_destination(conn, client: httpx.Client, destination: OutboxDestination, now: datetime,
                        settings: OutboxSettings, rng: random.Random, summary: RunSummary) -> None:
    if destination_is_stopped(conn, destination.id):
        conn.commit()
        summary.skipped_stopped_destinations.append(destination.id)
        return
    for _ in range(settings.batch_size):
        row = claim_next(conn, destination.id, now, settings.lease_seconds)
        if row is None:
            return
        result = send_packet(client, destination, row)
        apply_result(conn, destination, row, result, now, settings, rng)
        if result.action == ACCEPT:
            summary.delivered += 1
        elif result.action == QUARANTINE:
            summary.quarantined += 1
        elif result.action == STOP_DESTINATION:
            summary.stopped_destinations.append(destination.id)
            return
        else:
            summary.retried += 1
            if result.action == RETRY_END_CYCLE:
                # 通信断・タイムアウト: この宛先の今回の周回はここで止める(1件ごとにタイムアウトを待たない)。
                return


def run_once(
    now: datetime | None = None,
    *,
    http_client: httpx.Client | None = None,
    rng: random.Random | None = None,
    settings: OutboxSettings | None = None,
) -> RunSummary:
    """1周分の処理。時刻・HTTPクライアント・乱数を外から渡せる(テスト用)。"""
    now = now or utc_now()
    rng = rng or random.Random()
    settings = settings or load_outbox_settings(require_keys=True)
    summary = RunSummary()
    if not settings.active:
        return summary

    client = http_client or httpx.Client(timeout=settings.http_timeout_seconds, follow_redirects=False)
    try:
        with get_conn() as conn:
            summary.released_leases = release_expired_leases(conn, now)
            conn.commit()
            for destination in settings.destinations:
                if probe_if_due(conn, client, destination, now, settings):
                    summary.probes += 1
                # 宛先は1つずつ順に処理する(同時送信なし)。
                process_destination(conn, client, destination, now, settings, rng, summary)
    finally:
        if http_client is None:
            client.close()
    return summary


def requeue(destination_id: str, error_code: str, now: datetime | None = None) -> int:
    """指定した宛先・エラーコードの QUARANTINED を PENDING に戻す(クラウド側の鍵台帳を直したあとの復旧用)。"""
    now = now or utc_now()
    with get_conn() as conn:
        count = len(
            conn.execute(
                """
                UPDATE delivery_outbox
                SET state = 'PENDING', next_attempt_at = %s, lease_until = NULL
                WHERE destination_id = %s AND state = 'QUARANTINED' AND last_error_code = %s
                RETURNING id;
                """,
                (now, destination_id, error_code),
            ).fetchall()
        )
        conn.commit()
    logger.warning("Outbox requeue: destination=%s error_code=%s requeued=%d", destination_id, error_code, count)
    return count


def resume(destination_id: str, now: datetime | None = None) -> int:
    """STOPPED の宛先を再開する(STOPPED の行を PENDING に戻す)。"""
    now = now or utc_now()
    with get_conn() as conn:
        count = len(
            conn.execute(
                """
                UPDATE delivery_outbox
                SET state = 'PENDING', next_attempt_at = %s, lease_until = NULL
                WHERE destination_id = %s AND state = 'STOPPED'
                RETURNING id;
                """,
                (now, destination_id),
            ).fetchall()
        )
        conn.commit()
    logger.warning("Outbox resume: destination=%s resumed=%d", destination_id, count)
    return count


_BACKFILL_TARGETS = """
    FROM emergency_packets p
    WHERE p.version = 'v2'
      AND p.signature_status = 'SIGNATURE_VALID'
      AND (%(since)s::timestamptz IS NULL OR p.hub_received_at >= %(since)s::timestamptz)
      AND NOT EXISTS (
        SELECT 1 FROM delivery_outbox o
        WHERE o.emergency_packet_id = p.id AND o.destination_id = %(destination_id)s
      )
"""


def parse_since(value: str) -> datetime:
    """--since の値。タイムゾーンの無い時刻は、解釈がずれるので受け付けない。"""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise OutboxConfigError("--since must be an ISO 8601 time with a timezone (e.g. 2026-10-06T12:00:00+09:00)") from None
    if parsed.tzinfo is None:
        raise OutboxConfigError("--since must include a timezone (e.g. Z or +09:00)")
    return parsed


def backfill(
    destination_id: str,
    *,
    since: datetime | None = None,
    all_packets: bool = False,
    dry_run: bool = False,
    now: datetime | None = None,
) -> int:
    """登録が欠けている報告を、指定の宛先の delivery_outbox に PENDING で登録する。

    対象は signature_status=SIGNATURE_VALID の v2 の報告のうち、その宛先の行が無いもの。
    Outboxが無効だった間や、宛先を追加する前に受理した報告、登録に失敗した報告を拾うために使う。
    古いデモデータを誤って送らないよう、--since か --all のどちらかを必須にする。
    既にある行(ACCEPTED など)は変更しない(ON CONFLICT DO NOTHING)。2回目の実行は0件になる。
    戻り値は、dry_run なら対象の件数、それ以外は登録した件数。ログには件数だけを出す。
    """
    if (since is None) == (not all_packets):
        raise OutboxConfigError("backfill requires exactly one of --since or --all")
    settings = load_outbox_settings()
    if destination_id not in {destination.id for destination in settings.destinations}:
        raise OutboxConfigError(f"destination is not in OUTBOX_DESTINATIONS: {destination_id}")
    if not settings.enabled:
        logger.warning("Outbox backfill: OUTBOX_ENABLED is not true; registered rows are sent after it is enabled")

    now = now or utc_now()
    params = {"since": since, "destination_id": destination_id, "now": now}
    scope = "all" if all_packets else f"since={since.isoformat()}"
    with get_conn() as conn:
        if dry_run:
            count = conn.execute(f"SELECT count(*) AS count {_BACKFILL_TARGETS};", params).fetchone()["count"]
            conn.rollback()
            logger.warning("Outbox backfill (dry run): destination=%s %s targets=%d", destination_id, scope, count)
            return count
        count = len(
            conn.execute(
                f"""
                INSERT INTO delivery_outbox (id, emergency_packet_id, destination_id, state, next_attempt_at)
                SELECT 'OUT-' || replace(gen_random_uuid()::text, '-', ''), p.id, %(destination_id)s,
                       'PENDING', %(now)s
                {_BACKFILL_TARGETS}
                ON CONFLICT (emergency_packet_id, destination_id) DO NOTHING
                RETURNING id;
                """,
                params,
            ).fetchall()
        )
        conn.commit()
    logger.warning("Outbox backfill: destination=%s %s registered=%d", destination_id, scope, count)
    return count


def run_forever() -> None:
    settings = load_outbox_settings(require_keys=True)
    if not settings.active:
        logger.warning("Outbox is disabled (OUTBOX_ENABLED is not true or no destinations); worker is idle")
    for destination in settings.destinations:
        logger.info("Outbox destination: id=%s url=%s key_env=%s",
                    destination.id, destination.display_url, destination.key_env)
    while True:
        try:
            if settings.active:
                run_once(settings=settings)
        except Exception as exc:  # noqa: BLE001 - ループは止めない
            logger.error("Outbox run failed: %s", exc.__class__.__name__)
        time.sleep(settings.poll_interval_seconds)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(prog="python -m app.outbox_worker")
    subcommands = parser.add_subparsers(dest="command")
    subcommands.add_parser("once", help="run one cycle and exit")
    requeue_parser = subcommands.add_parser("requeue", help="move QUARANTINED deliveries back to PENDING")
    requeue_parser.add_argument("--destination", required=True)
    requeue_parser.add_argument("--error-code", required=True)
    resume_parser = subcommands.add_parser("resume", help="resume a STOPPED destination")
    resume_parser.add_argument("--destination", required=True)
    backfill_parser = subcommands.add_parser(
        "backfill", help="register signed v2 reports that have no delivery row for a destination"
    )
    backfill_parser.add_argument("--destination", required=True)
    scope = backfill_parser.add_mutually_exclusive_group(required=True)
    scope.add_argument("--since", help="only reports with hub_received_at at or after this ISO 8601 time")
    scope.add_argument("--all", action="store_true", help="all reports (no time limit)")
    backfill_parser.add_argument("--dry-run", action="store_true", help="only count the targets")
    args = parser.parse_args(argv)

    try:
        if args.command == "requeue":
            requeue(args.destination, args.error_code)
        elif args.command == "resume":
            resume(args.destination)
        elif args.command == "backfill":
            count = backfill(
                args.destination,
                since=parse_since(args.since) if args.since else None,
                all_packets=args.all,
                dry_run=args.dry_run,
            )
            print(f"{'targets' if args.dry_run else 'registered'}: {count}")
        elif args.command == "once":
            summary = run_once()
            logger.info("Outbox run: %s", summary)
        else:
            run_forever()
    except OutboxConfigError as exc:
        logger.error("Outbox configuration error: %s", exc)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
