from datetime import datetime
from pydantic import BaseModel, EmailStr, Field


class EmployeeIn(BaseModel):
    full_name: str
    work_email: EmailStr
    phone: str | None = None
    department: str | None = None
    floor: str | None = None
    role_id: int | None = None
    delegate_id: int | None = None


class EmployeeUpdate(BaseModel):
    full_name: str | None = None
    phone: str | None = None
    department: str | None = None
    floor: str | None = None
    role_id: int | None = None
    delegate_id: int | None = None
    is_active: bool | None = None


class EmployeeOut(BaseModel):
    id: int
    full_name: str
    work_email: str
    phone: str | None = None
    department: str | None = None
    floor: str | None = None
    role_id: int | None = None
    role_name: str | None = None
    is_active: bool
    last_seen_at: datetime | None = None
    is_admin: bool = False

    class Config:
        from_attributes = True


class NotificationPrefsIn(BaseModel):
    notify_email: bool | None = None
    notify_teams: bool | None = None
    notify_sms: bool | None = None
    teams_webhook_url: str | None = None


class RoleIn(BaseModel):
    name: str
    description: str = ""
    permissions: list[str] = []


class RoleOut(BaseModel):
    id: int
    name: str
    description: str
    is_system: bool
    permissions: list[str]


class PermissionOut(BaseModel):
    key: str
    module: str
    sub_category: str
    label: str


class AdminInviteIn(BaseModel):
    employee_id: int
    role_id: int
