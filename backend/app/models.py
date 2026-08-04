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


class ShelterCreate(BaseModel):
    id: str | None = Field(default=None, min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=120)
    location: str = Field(default="", max_length=240)


class Shelter(BaseModel):
    id: str
    name: str
    location: str
    created_at: datetime


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


class ObservationVerificationUpdate(BaseModel):
    status: Literal["VERIFIED", "REJECTED"]


class ShelterStatus(BaseModel):
    shelter: Shelter
    latest_observation: Observation | None
    status: str
    request_code: str | None


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


class EmergencyPacketCreate(BaseModel):
    packet: str = Field(min_length=1, max_length=240)
