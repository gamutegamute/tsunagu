from datetime import datetime, timezone

import pytest

from app.emergency_packet import (
    compute_packet_hmac,
    packet_version,
    parse_emergency_packet,
    parse_emergency_packet_v2,
    verify_packet_hmac,
)


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


def test_parse_emergency_packet_v1_rejects_extra_field() -> None:
    with pytest.raises(ValueError):
        parse_emergency_packet("v1|AIT001|21:04|170|18|WARNING|REQ_WATER|NONE")


# --- Emergency Packet v2 ---

# HMACテストベクトル(docs/emergency-packet-v2.md にも同じ値を載せる)。
# 鍵はテスト専用のダミー値 00 01 02 ... 1f(32バイト)。実際の端末鍵ではない。
HMAC_TEST_KEY = bytes(range(32))
HMAC_TEST_SIGNED_PAYLOAD = "v2|TB001|01|A1B2C3D4E5F60718|0000002A|1791234567|AIT001|170|18|WARNING|REQ_WATER"
HMAC_TEST_EXPECTED = "c23c0c17326995159c0cc9dfafe7fd8c"
HMAC_TEST_PACKET = f"{HMAC_TEST_SIGNED_PAYLOAD}|{HMAC_TEST_EXPECTED}"


def _v2_with(index: int, value: str) -> str:
    parts = HMAC_TEST_PACKET.split("|")
    parts[index] = value
    return "|".join(parts)


def test_hmac_test_vector() -> None:
    assert HMAC_TEST_KEY.hex() == "000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f"
    assert compute_packet_hmac(HMAC_TEST_KEY, HMAC_TEST_SIGNED_PAYLOAD) == HMAC_TEST_EXPECTED
    assert verify_packet_hmac(HMAC_TEST_KEY, parse_emergency_packet_v2(HMAC_TEST_PACKET))


def test_hmac_verification_fails_for_other_key_or_tampered_packet() -> None:
    assert not verify_packet_hmac(bytes(range(1, 33)), parse_emergency_packet_v2(HMAC_TEST_PACKET))
    assert not verify_packet_hmac(HMAC_TEST_KEY, parse_emergency_packet_v2(_v2_with(7, "171")))


def test_parse_emergency_packet_v2() -> None:
    packet = parse_emergency_packet_v2(HMAC_TEST_PACKET)

    assert packet.version == "v2"
    assert packet.device_id == "TB001"
    assert packet.key_id == "01"
    assert packet.install_id == "A1B2C3D4E5F60718"
    assert packet.sequence == "0000002A"
    assert packet.reported_at == datetime(2026, 10, 5, 21, 9, 27, tzinfo=timezone.utc)
    assert packet.shelter_code == "AIT001"
    assert packet.people_count == 170
    assert packet.water_stock == 18
    assert packet.status == "WARNING"
    assert packet.request_code == "REQ_WATER"
    assert packet.hmac == HMAC_TEST_EXPECTED
    # 署名対象は最後の"|"より前の全体。末尾の"|"とhmacは含まない。
    assert packet.signed_payload == HMAC_TEST_SIGNED_PAYLOAD
    assert packet_version(HMAC_TEST_PACKET) == "v2"


@pytest.mark.parametrize(
    "packet",
    [
        HMAC_TEST_SIGNED_PAYLOAD,  # 11 fields
        HMAC_TEST_PACKET + "|extra",  # 13 fields
        HMAC_TEST_PACKET + "|",  # trailing separator
        HMAC_TEST_PACKET.replace("|AIT001|", "|AIT001||"),
    ],
)
def test_parse_emergency_packet_v2_rejects_wrong_field_count(packet: str) -> None:
    with pytest.raises(ValueError):
        parse_emergency_packet_v2(packet)


@pytest.mark.parametrize(
    ("index", "value"),
    [
        (0, "v3"),
        (1, "TB01"),  # device_id: 5文字ちょうど
        (1, "TB0011"),
        (1, "tb001"),
        (1, "TB-01"),
        (2, "1"),  # key_id: 16進2文字
        (2, "0a"),
        (2, "0G"),
        (3, "A1B2C3D4E5F6071"),  # install_id: 16進16文字
        (3, "A1B2C3D4E5F607189"),
        (3, "a1b2c3d4e5f60718"),
        (3, "A1B2C3D4E5F6071G"),
        (4, "000002A"),  # sequence: 16進8文字
        (4, "00000002A"),
        (4, "0000002a"),
        (5, ""),  # reported_at: 10進のUnix秒
        (5, "-1791234567"),
        (5, "1791234567.5"),
        (5, "0x6AC37C47"),
        (5, "17912345670"),
        (6, "AI"),  # shelter_code: 3〜12文字
        (6, "AIT0010000000"),
        (6, "ait001"),
        (6, "AIT 01"),
        (7, "1000001"),  # people_count: 0〜1,000,000
        (7, "-1"),
        (7, "+1"),
        (7, " 1"),
        (7, "1_0"),
        (7, ""),
        (8, "1000001"),  # water_stock: 0〜1,000,000
        (8, "-1"),
        (8, "1.5"),
        (9, "warning"),
        (9, "UNKNOWN"),
        (10, "REQ_UNKNOWN"),
        (10, "none"),
        (11, HMAC_TEST_EXPECTED.upper()),  # hmac: 小文字16進32文字
        (11, HMAC_TEST_EXPECTED[:-1]),
        (11, HMAC_TEST_EXPECTED + "0"),
        (11, HMAC_TEST_EXPECTED[:-1] + "g"),
    ],
)
def test_parse_emergency_packet_v2_rejects_invalid_field(index: int, value: str) -> None:
    with pytest.raises(ValueError):
        parse_emergency_packet_v2(_v2_with(index, value))


@pytest.mark.parametrize(
    ("index", "value"),
    [
        (6, "AIT"),
        (6, "AIT_00-12345"),
        (7, "0"),
        (7, "1000000"),
        (8, "0"),
        (8, "1000000"),
        (5, "0"),
    ],
)
def test_parse_emergency_packet_v2_accepts_boundary_values(index: int, value: str) -> None:
    parse_emergency_packet_v2(_v2_with(index, value))
