from datetime import datetime
from pydantic import BaseModel, EmailStr, Field


class IdentifyIn(BaseModel):
    """A face image (base64), a QR token, or a typed access code. Face is
    preferred; QR and access_code are the fallback options at a kiosk."""
    image_b64: str | None = None
    qr_token: str | None = None
    access_code: str | None = None


class IdentifyOut(BaseModel):
    found: bool
    face_detected: bool = False
    match_score: float | None = None
    bbox: list[int] | None = None
    inference_ms: float | None = None
    visitor_id: int | None = None
    visitor_name: str | None = None
    is_returning: bool = False
    open_visit_id: int | None = None
    presence: str | None = None
    suggested_action: str  # check_in / step_out / step_in / check_out / register
    last_visit_at: datetime | None = None
    last_host_name: str | None = None
    blocked: bool = False
    message: str = ""


class CheckInIn(BaseModel):
    visitor_id: int | None = None
    invite_token: str | None = None
    host_id: int | None = None
    method: str = "face"
    match_score: float | None = None


class MovementIn(BaseModel):
    visitor_id: int
    method: str = "face"
    match_score: float | None = None


class WalkInStartIn(BaseModel):
    image_b64: str | None = None


class WalkInSubmitIn(BaseModel):
    full_name: str = Field(min_length=1)
    phone: str
    email: EmailStr | None = None
    company: str | None = None
    purpose: str
    host_id: int
    visitor_type_id: int
    consent_given: bool = False
    image_b64: str | None = None
    message: str | None = Field(None, max_length=500)


class WalkInStatusOut(BaseModel):
    approval_id: int
    status: str
    visitor_name: str
    host_name: str | None = None
    seconds_waiting: int
    seconds_remaining: int
    message: str


class DevicePairIn(BaseModel):
    pairing_code: str
    app_version: str | None = None


class DevicePairOut(BaseModel):
    device_id: int
    device_name: str
    device_token: str
    mode: str


class HeartbeatIn(BaseModel):
    app_version: str | None = None
