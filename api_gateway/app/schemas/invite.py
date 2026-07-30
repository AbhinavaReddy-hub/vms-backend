from datetime import datetime
from pydantic import BaseModel, EmailStr, Field


class InviteIn(BaseModel):
    visitor_type_id: int
    full_name: str = Field(min_length=1, max_length=150)
    email: EmailStr | None = None
    phone: str | None = None
    company: str | None = None
    additional_visitors: int = Field(0, ge=0, le=50)
    arrival_at: datetime
    valid_until: datetime | None = None
    purpose: str | None = None
    primary_host_id: int
    additional_host_ids: list[int] = []
    private_notes: str | None = None
    public_notes: str | None = None
    custom_message: str | None = None
    auto_approve: bool = False
    send_invite_email: bool = True


class InviteUpdate(BaseModel):
    visitor_type_id: int | None = None
    full_name: str | None = None
    email: EmailStr | None = None
    phone: str | None = None
    company: str | None = None
    additional_visitors: int | None = None
    arrival_at: datetime | None = None
    valid_until: datetime | None = None
    purpose: str | None = None
    primary_host_id: int | None = None
    additional_host_ids: list[int] | None = None
    private_notes: str | None = None
    public_notes: str | None = None
    custom_message: str | None = None
    auto_approve: bool | None = None


class GroupInviteRow(BaseModel):
    arrival_at: datetime
    full_name: str
    email: EmailStr | None = None
    phone: str | None = None
    host_id: int | None = None
    private_notes: str | None = None
    public_notes: str | None = None


class GroupInviteIn(BaseModel):
    group_name: str
    visitor_type_id: int
    default_host_id: int
    auto_approve: bool = False
    send_invite_emails: bool = True
    include_group_name_in_email: bool = True
    rows: list[GroupInviteRow] = Field(min_length=1, max_length=500)


class GroupInviteResult(BaseModel):
    group_id: int
    group_name: str
    created: int
    failed: list[dict]
    invites: list[dict]


class HostOut(BaseModel):
    id: int
    full_name: str
    is_primary: bool


class InviteOut(BaseModel):
    id: int
    visitor_type_id: int
    visitor_type_name: str | None = None
    group_id: int | None = None
    group_name: str | None = None
    full_name: str
    email: str | None = None
    phone: str | None = None
    company: str | None = None
    additional_visitors: int
    arrival_at: datetime
    valid_until: datetime
    purpose: str | None = None
    private_notes: str | None = None
    public_notes: str | None = None
    custom_message: str | None = None
    auto_approve: bool
    status: str
    legal_docs_status: str
    is_returning_visitor: bool = False
    signed_in_at: datetime | None = None
    hosts: list[HostOut] = []
    primary_host_name: str | None = None
    created_by_id: int | None = None
    created_by_name: str | None = None
    created_at: datetime
    sent_at: datetime | None = None
    opened_at: datetime | None = None
    submitted_at: datetime | None = None
    registration_link: str | None = None


class BulkActionIn(BaseModel):
    invite_ids: list[int]
    action: str  # revoke / delete / resend
