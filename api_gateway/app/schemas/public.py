"""Schemas for the visitor-facing registration flow (no login)."""
from datetime import datetime
from pydantic import BaseModel, EmailStr, Field


class InvitePublicOut(BaseModel):
    """What the visitor sees when they open their link. Deliberately
    does NOT include private_notes - that is staff-only."""
    full_name: str
    company_name: str
    visitor_type: str
    arrival_at: datetime
    valid_until: datetime
    host_name: str | None = None
    purpose: str | None = None
    public_notes: str | None = None
    custom_message: str | None = None
    requires_face: bool
    requires_legal_docs: bool
    status: str
    steps_done: dict


class OtpSendIn(BaseModel):
    phone: str = Field(min_length=6, max_length=20)


class OtpVerifyIn(BaseModel):
    phone: str
    code: str = Field(min_length=4, max_length=8)


class ConsentIn(BaseModel):
    accepted: bool
    consent_text_version: str = "1.0"


class SubmitRegistrationIn(BaseModel):
    email: EmailStr | None = None
    company: str | None = None
    purpose: str | None = None
    additional_visitors: int = Field(0, ge=0, le=50)


class InviteDetailsIn(BaseModel):
    """Replaces the old OTP send+verify pair as the trigger for creating the
    visitor record - no phone-ownership verification, just the details."""
    phone: str = Field(min_length=6, max_length=20)
    email: EmailStr | None = None
    company: str | None = None
    message: str | None = Field(None, max_length=500)


class PassOut(BaseModel):
    visitor_name: str
    company_name: str
    visitor_type: str
    badge_color: str
    host_name: str | None = None
    valid_until: datetime
    status: str
    presence: str | None = None
    qr_payload: str
    access_code: str | None = None


class WalkInSubmitIn(BaseModel):
    """Walk-in registration submitted from the visitor's own phone."""
    full_name: str = Field(min_length=1, max_length=150)
    phone: str = Field(min_length=6, max_length=20)
    email: EmailStr | None = None
    company: str | None = None
    purpose: str = Field(min_length=1, max_length=300)
    host_id: int
    visitor_type_id: int
    consent_given: bool = False
    message: str | None = Field(None, max_length=500)
