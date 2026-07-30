from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr


class VisitorOut(BaseModel):
    id: int
    full_name: str
    email: str | None = None
    phone: str | None = None
    company: str | None = None
    total_visits: int = 0
    last_seen_at: datetime | None = None
    face_registered: bool = False
    face_registered_at: datetime | None = None
    consent_given_at: datetime | None = None
    is_blocked: bool = False
    notes: str | None = None

    class Config:
        from_attributes = True


class VisitorUpdate(BaseModel):
    full_name: str | None = None
    email: EmailStr | None = None
    phone: str | None = None
    company: str | None = None
    notes: str | None = None


class MovementOut(BaseModel):
    id: int
    type: str
    occurred_at: datetime
    method: str
    match_score: float | None = None
    device_name: str | None = None
    is_correction: bool = False
    note: str | None = None


class VisitOut(BaseModel):
    id: int
    visitor_id: int
    visitor_name: str
    visitor_type_name: str | None = None
    badge_color: str | None = None
    host_id: int | None = None
    host_name: str | None = None
    status: str
    presence: str
    purpose: str | None = None
    additional_visitors: int = 0
    first_entry_at: datetime | None = None
    last_exit_at: datetime | None = None
    minutes_inside: int | None = None
    movements: list[MovementOut] = []


class VisitorTypeIn(BaseModel):
    name: str
    badge_color: str = "#2563EB"
    requires_approval: bool = True
    requires_face: bool = True
    requires_legal_docs: bool = False
    auto_approve_default: bool = False
    default_validity_hours: int = 12


class VisitorTypeOut(VisitorTypeIn):
    id: int
    is_active: bool

    class Config:
        from_attributes = True


class BlocklistIn(BaseModel):
    full_name: str | None = None
    email: EmailStr | None = None
    phone: str | None = None
    reason: str


class BlocklistOut(BaseModel):
    id: int
    full_name: str | None = None
    email: str | None = None
    phone: str | None = None
    reason: str
    added_by_name: str | None = None
    is_active: bool
    created_at: datetime


class ApprovalOut(BaseModel):
    id: int
    approval_type: str
    visitor_name: str
    visitor_type_name: str | None = None
    host_name: str | None = None
    status: str
    due_at: datetime | None = None
    created_at: datetime
    decided_at: datetime | None = None
    decided_by_name: str | None = None
    deny_reason: str | None = None
    match_detail: str | None = None
    invite_id: int | None = None
    visit_id: int | None = None


class DenyIn(BaseModel):
    reason: str | None = None


class DeviceIn(BaseModel):
    name: str
    location_label: str | None = None
    mode: Literal["registration_kiosk", "checkinout", "stepinout"] = "registration_kiosk"


class DeviceOut(BaseModel):
    id: int
    name: str
    location_label: str | None = None
    mode: str
    direction: str | None = None
    paired_device_id: int | None = None
    paired_device_name: str | None = None
    status: str
    app_version: str | None = None
    last_seen_at: datetime | None = None
    online: bool = False
    pairing_code: str | None = None
