from dataclasses import dataclass
from re import fullmatch


ALLOWED_PACKET_VERSIONS = {"v1"}
ALLOWED_PACKET_STATUSES = {"NORMAL", "WARNING", "ALERT", "CRITICAL"}
ALLOWED_REQUEST_CODES = {
    "REQ_WATER",
    "REQ_MEDICAL",
    "REQ_FOOD",
    "REQ_RESCUE",
    "REQ_CONFIRM",
    "NONE",
}


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


def parse_emergency_packet(packet: str) -> ParsedEmergencyPacket:
    raw_packet = packet.strip()
    parts = raw_packet.split("|")
    if len(parts) != 7:
        raise ValueError("Emergency Packet must have 7 fields")

    version, shelter_code, packet_time, people_count, water_stock, status, request_code = parts
    if version not in ALLOWED_PACKET_VERSIONS:
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
