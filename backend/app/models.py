from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator


class Urgency(StrEnum):
    NORMAL = "NORMAL"
    WARNING = "WARNING"
    ALERT = "ALERT"
    CRITICAL = "CRITICAL"


class ReporterType(StrEnum):
    ANONYMOUS = "ANONYMOUS"
    AUTHENTICATED_FIELD = "AUTHENTICATED_FIELD"
    AUTHENTICATED_HQ = "AUTHENTICATED_HQ"
    LORA_GATEWAY = "LORA_GATEWAY"


class VerificationStatus(StrEnum):
    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class SignatureStatus(StrEnum):
    # Emergency Packetの署名検証の結果。本部職員による確認(VerificationStatus)とは別物。
    SIGNATURE_VALID = "SIGNATURE_VALID"
    UNSIGNED_V1 = "UNSIGNED_V1"


class TimeTrust(StrEnum):
    TRUSTED = "TRUSTED"
    UNTRUSTED = "UNTRUSTED"


class ShelterCreate(BaseModel):
    id: str | None = Field(default=None, min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=120)
    location: str = Field(default="", max_length=240)
    capacity: int | None = Field(default=None, ge=0)


class Shelter(BaseModel):
    id: str
    name: str
    location: str
    created_at: datetime
    capacity: int | None = None


class ObservationCreate(BaseModel):
    shelter_id: str | None = Field(default=None, max_length=50)
    shelter_code: str | None = Field(default=None, max_length=50)
    client_event_id: str = Field(default_factory=lambda: str(uuid4()), min_length=1, max_length=120)
    people_count: int = Field(ge=0, le=1_000_000)
    water_stock: int = Field(ge=0, le=1_000_000)
    urgency: Urgency = Urgency.NORMAL
    memo: str = Field(default="", max_length=1000)
    observed_at: datetime | None = None
    reporter_name: str = Field(default="", max_length=120)
    source: Literal["web", "offline"] = "web"

    @model_validator(mode="after")
    def validate_shelter_identifiers(self) -> "ObservationCreate":
        if not self.shelter_id and not self.shelter_code:
            raise ValueError("Either shelter_id or shelter_code must be provided")
        return self


class Observation(BaseModel):
    id: str
    shelter_id: str
    client_event_id: str
    people_count: int
    water_stock: int
    urgency: Urgency
    memo: str
    observed_at: datetime
    created_at: datetime
    reporter_name: str
    reporter_email: str | None = None
    reporter_type: ReporterType
    verification_status: VerificationStatus
    verified_by: str | None = None
    verified_at: datetime | None = None
    source: str
    signature_status: SignatureStatus | None = None


class ObservationVerificationUpdate(BaseModel):
    status: Literal["VERIFIED", "REJECTED"]


class ShelterStatus(BaseModel):
    shelter: Shelter
    latest_observation: Observation | None
    status: str
    request_code: str | None


class IncidentState(BaseModel):
    confirm_status: Literal["UNCONFIRMED", "CONFIRMED"] = "UNCONFIRMED"
    confirmed_by: str | None = None
    confirmed_at: datetime | None = None
    confirm_memo: str | None = None
    resolution_request_memo: str | None = None
    resolution_request_staff_name: str | None = None
    resolution_request_active_shelter_id: str | None = None
    resolution_request_at: datetime | None = None
    resolution_memo: str | None = None
    resolution_staff_name: str | None = None
    resolution_approver_name: str | None = None
    resolution_approved_at: datetime | None = None


class Incident(BaseModel):
    id: str
    shelter: Shelter
    urgency: str
    memo: str
    observed_at: datetime
    state: IncidentState


class IncidentConfirmRequest(BaseModel):
    approver_name: str = Field(min_length=1, max_length=120)
    memo: str = Field(default="", max_length=1000)


class IncidentResolveRequest(BaseModel):
    approver_name: str = Field(min_length=1, max_length=120)
    staff_name: str = Field(min_length=1, max_length=120)
    memo: str = Field(default="", max_length=1000)


class IncidentResolutionRequestCreate(BaseModel):
    staff_name: str = Field(min_length=1, max_length=120)
    memo: str = Field(default="", max_length=1000)
    active_shelter_id: str | None = Field(default=None, max_length=50)


class IncidentResolutionApproveRequest(BaseModel):
    approver_name: str = Field(min_length=1, max_length=120)


class EmergencyPacket(BaseModel):
    id: str
    version: str
    shelter_code: str
    shelter_id: str | None = None
    packet_time: str
    people_count: int
    water_stock: int
    status: str
    request_code: str
    raw_packet: str
    received_at: datetime
    # 以下はv2で追加した列。v2以前の行はNULL(v1はsignature_status/hub_received_atのみ入る)。
    device_id: str | None = None
    key_id: str | None = None
    install_id: str | None = None
    sequence: str | None = None
    reported_at: datetime | None = None
    hub_received_at: datetime | None = None
    cloud_synced_at: datetime | None = None
    time_trust: TimeTrust | None = None
    signature_status: SignatureStatus | None = None
    observation_id: str | None = None
    # 避難所コードが登録済みの避難所に紐付いたか(shelter_id が NULL でないか)。
    # 未登録なら観測(observations)が作られず、通常の本部画面の集計に入らない。
    shelter_registered: bool | None = None


class EmergencyPacketAccepted(EmergencyPacket):
    """POST /api/emergency-packets の応答。v2 では警告と観測の有無を返す(v1 では null)。"""

    # 例: ["SHELTER_NOT_REGISTERED"](未登録の避難所コード。報告は保存したが観測は作っていない)
    warnings: list[str] | None = None
    observation_created: bool | None = None


class EmergencyPacketCreate(BaseModel):
    packet: str = Field(min_length=1, max_length=240)
    # ゲートウェイ(Hub)がPacketを受信した時刻。省略時はサーバーの受信時刻を使う。
    hub_received_at: datetime | None = None


class DestinationStatus(BaseModel):
    destination_id: str
    configured: bool
    state: Literal["NORMAL", "DELAYED", "DOWN", "AUTH_ERROR", "UNKNOWN"]
    last_success_at: datetime | None = None
    last_reachable_at: datetime | None = None
    last_latency_ms: int | None = None
    queue_depth: int
    sending_count: int
    stopped_count: int
    oldest_pending_at: datetime | None = None
    accepted_count: int
    quarantined_count: int
    quarantined_by_error_code: dict[str, int]
    last_error_code: str | None = None
    last_error_at: datetime | None = None


class DestinationStatusResponse(BaseModel):
    enabled: bool
    generated_at: datetime
    destinations: list[DestinationStatus]


class DeliveryAttempt(BaseModel):
    attempted_at: datetime
    outcome: str
    http_status: int | None = None
    latency_ms: int | None = None
    error_code: str | None = None


class PacketDelivery(BaseModel):
    destination_id: str
    state: Literal["PENDING", "SENDING", "ACCEPTED", "QUARANTINED", "STOPPED"]
    attempts: int
    next_attempt_at: datetime
    last_attempt_at: datetime | None = None
    last_error_code: str | None = None
    last_error_summary: str | None = None
    accepted_at: datetime | None = None
    created_at: datetime
    history: list[DeliveryAttempt]


class EmergencyPacketDeliveries(BaseModel):
    emergency_packet_id: str
    version: str
    signature_status: SignatureStatus | None = None
    forwardable: bool
    deliveries: list[PacketDelivery]


class DemoResetRequest(BaseModel):
    confirmation: str = Field(min_length=1, max_length=50)
