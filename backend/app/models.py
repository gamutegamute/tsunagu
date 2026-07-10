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


class ShelterCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    location: str = Field(default="", max_length=240)


class Shelter(BaseModel):
    id: str
    name: str
    location: str
    created_at: datetime


class ObservationCreate(BaseModel):
    shelter_id: str | None = None
    shelter_code: str | None = None
    client_event_id: str = Field(default_factory=lambda: str(uuid4()))
    people_count: int = Field(ge=0)
    water_stock: int = Field(ge=0)
    urgency: Urgency = Urgency.NORMAL
    memo: str = Field(default="", max_length=1000)
    observed_at: datetime | None = None
    reporter_name: str = Field(default="")
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
    source: str


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
