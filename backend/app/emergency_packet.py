import hashlib
import hmac
from dataclasses import dataclass
from datetime import datetime, timezone
from re import fullmatch


ALLOWED_PACKET_STATUSES = {"NORMAL", "WARNING", "ALERT", "CRITICAL"}
ALLOWED_REQUEST_CODES = {
    "REQ_WATER",
    "REQ_MEDICAL",
    "REQ_FOOD",
    "REQ_RESCUE",
    "REQ_CONFIRM",
    "NONE",
}

V2_FIELD_COUNT = 12
V2_MAX_COUNT_VALUE = 1_000_000
PACKET_HMAC_BYTES = 16


@dataclass(frozen=True)
class ParsedEmergencyPacket:
    version: str
    shelter_code: str
    packet_time: str
    people_count: int
    water_stock: int
    status: str
    request_code: str
    raw_packet: str


@dataclass(frozen=True)
class ParsedEmergencyPacketV2:
    version: str
    device_id: str
    key_id: str
    install_id: str
    sequence: str
    reported_at: datetime
    shelter_code: str
    people_count: int
    water_stock: int
    status: str
    request_code: str
    hmac: str
    signed_payload: str
    raw_packet: str


def packet_version(packet: str) -> str:
    return packet.strip().split("|", 1)[0]


def parse_emergency_packet(packet: str) -> ParsedEmergencyPacket:
    raw_packet = packet.strip()
    parts = raw_packet.split("|")
    if len(parts) != 7:
        raise ValueError("Emergency Packet must have 7 fields")

    version, shelter_code, packet_time, people_count, water_stock, status, request_code = parts
    if version != "v1":
        raise ValueError("Unsupported Emergency Packet version")
    if not fullmatch(r"[A-Z0-9_-]{3,32}", shelter_code):
        raise ValueError("Invalid shelter_code")
    if not fullmatch(r"([01][0-9]|2[0-3]):[0-5][0-9]", packet_time):
        raise ValueError("Invalid packet time")
    if status not in ALLOWED_PACKET_STATUSES:
        raise ValueError("Invalid status")
    if request_code not in ALLOWED_REQUEST_CODES:
        raise ValueError("Invalid request_code")

    try:
        people_count_value = int(people_count)
        water_stock_value = int(water_stock)
    except ValueError as exc:
        raise ValueError("people_count and water_stock must be integers") from exc
    if people_count_value < 0 or water_stock_value < 0:
        raise ValueError("people_count and water_stock must be greater than or equal to 0")

    return ParsedEmergencyPacket(
        version=version,
        shelter_code=shelter_code,
        packet_time=packet_time,
        people_count=people_count_value,
        water_stock=water_stock_value,
        status=status,
        request_code=request_code,
        raw_packet=raw_packet,
    )


def _parse_count(name: str, value: str) -> int:
    # 数字のみ。int()が受け付ける符号・空白・"_"区切りは弾く。
    if not fullmatch(r"[0-9]{1,7}", value):
        raise ValueError(f"Invalid {name}")
    number = int(value)
    if number > V2_MAX_COUNT_VALUE:
        raise ValueError(f"{name} must be between 0 and {V2_MAX_COUNT_VALUE}")
    return number


def parse_emergency_packet_v2(packet: str) -> ParsedEmergencyPacketV2:
    """v2の形式(区切り数・長さ・文字・範囲)を検証する。HMAC検証より前に必ず呼ぶ。"""
    raw_packet = packet.strip()
    parts = raw_packet.split("|")
    if len(parts) != V2_FIELD_COUNT:
        raise ValueError(f"Emergency Packet v2 must have {V2_FIELD_COUNT} fields")

    (
        version,
        device_id,
        key_id,
        install_id,
        sequence,
        reported_at,
        shelter_code,
        people_count,
        water_stock,
        status,
        request_code,
        packet_hmac,
    ) = parts
    if version != "v2":
        raise ValueError("Unsupported Emergency Packet version")
    if not fullmatch(r"[A-Z0-9]{5}", device_id):
        raise ValueError("Invalid device_id")
    if not fullmatch(r"[0-9A-F]{2}", key_id):
        raise ValueError("Invalid key_id")
    if not fullmatch(r"[0-9A-F]{16}", install_id):
        raise ValueError("Invalid install_id")
    if not fullmatch(r"[0-9A-F]{8}", sequence):
        raise ValueError("Invalid sequence")
    if not fullmatch(r"[0-9]{1,10}", reported_at):
        raise ValueError("Invalid reported_at")
    if not fullmatch(r"[A-Z0-9_-]{3,12}", shelter_code):
        raise ValueError("Invalid shelter_code")
    people_count_value = _parse_count("people_count", people_count)
    water_stock_value = _parse_count("water_stock", water_stock)
    if status not in ALLOWED_PACKET_STATUSES:
        raise ValueError("Invalid status")
    if request_code not in ALLOWED_REQUEST_CODES:
        raise ValueError("Invalid request_code")
    if not fullmatch(r"[0-9a-f]{32}", packet_hmac):
        raise ValueError("Invalid hmac")

    return ParsedEmergencyPacketV2(
        version=version,
        device_id=device_id,
        key_id=key_id,
        install_id=install_id,
        sequence=sequence,
        reported_at=datetime.fromtimestamp(int(reported_at), tz=timezone.utc),
        shelter_code=shelter_code,
        people_count=people_count_value,
        water_stock=water_stock_value,
        status=status,
        request_code=request_code,
        hmac=packet_hmac,
        # 署名対象は最後の"|"より前の全体("v2|"〜request_code)。
        signed_payload=raw_packet.rsplit("|", 1)[0],
        raw_packet=raw_packet,
    )


def compute_packet_hmac(key: bytes, signed_payload: str) -> str:
    """HMAC-SHA256の先頭16バイトを小文字16進32文字にしたもの。"""
    digest = hmac.new(key, signed_payload.encode("ascii"), hashlib.sha256).digest()
    return digest[:PACKET_HMAC_BYTES].hex()


def verify_packet_hmac(key: bytes, packet: ParsedEmergencyPacketV2) -> bool:
    expected = compute_packet_hmac(key, packet.signed_payload)
    return hmac.compare_digest(expected, packet.hmac)
