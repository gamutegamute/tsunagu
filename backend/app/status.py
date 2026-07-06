from datetime import datetime, timezone

STALE_HOURS = 24
LOW_WATER_THRESHOLD = 20


def decide_status(
    *,
    observed_at: datetime | None,
    water_stock: int | None,
    urgency: str | None,
    now: datetime | None = None,
) -> str:
    if observed_at is None:
        return "UNKNOWN"

    current = now or datetime.now(timezone.utc)
    observed = observed_at
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=timezone.utc)

    age_hours = (current - observed).total_seconds() / 3600
    if age_hours > STALE_HOURS:
        return "ALERT"
    if urgency == "CRITICAL":
        return "ALERT"
    if urgency == "HIGH":
        return "WARNING"
    if water_stock is not None and water_stock < LOW_WATER_THRESHOLD:
        return "WARNING"
    return "NORMAL"


def decide_request_code(*, water_stock: int | None, status: str) -> str | None:
    if water_stock is not None and water_stock < LOW_WATER_THRESHOLD:
        return "REQ_WATER"
    if status == "ALERT":
        return "REQ_CONFIRM"
    return None
