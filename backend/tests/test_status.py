from datetime import datetime, timedelta, timezone

from app.status import decide_request_code, decide_status


def test_status_unknown_without_observation() -> None:
    assert decide_status(observed_at=None, water_stock=None, urgency=None) == "UNKNOWN"


def test_status_alert_when_stale() -> None:
    now = datetime(2026, 7, 5, tzinfo=timezone.utc)
    observed_at = now - timedelta(hours=25)

    assert decide_status(observed_at=observed_at, water_stock=100, urgency="NORMAL", now=now) == "ALERT"


def test_status_warning_when_water_is_low() -> None:
    now = datetime(2026, 7, 5, tzinfo=timezone.utc)

    assert decide_status(observed_at=now, water_stock=10, urgency="NORMAL", now=now) == "WARNING"


def test_request_code_for_low_water() -> None:
    assert decide_request_code(water_stock=10, status="WARNING") == "REQ_WATER"
