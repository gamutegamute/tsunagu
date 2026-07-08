import pytest

from app.emergency_packet import parse_emergency_packet


def test_parse_emergency_packet() -> None:
    packet = parse_emergency_packet("v1|AIT001|21:04|170|18|WARNING|REQ_WATER")

    assert packet.version == "v1"
    assert packet.shelter_code == "AIT001"
    assert packet.packet_time == "21:04"
    assert packet.people_count == 170
    assert packet.water_stock == 18
    assert packet.status == "WARNING"
    assert packet.request_code == "REQ_WATER"


def test_parse_emergency_packet_rejects_invalid_format() -> None:
    with pytest.raises(ValueError):
        parse_emergency_packet("AIT001|21:04|170|18|WARNING|REQ_WATER")


def test_parse_emergency_packet_rejects_unknown_request_code() -> None:
    with pytest.raises(ValueError):
        parse_emergency_packet("v1|AIT001|21:04|170|18|WARNING|REQ_UNKNOWN")


def test_parse_emergency_packet_rejects_invalid_time() -> None:
    with pytest.raises(ValueError):
        parse_emergency_packet("v1|AIT001|29:04|170|18|WARNING|REQ_WATER")
