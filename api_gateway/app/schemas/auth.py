from datetime import datetime
from pydantic import BaseModel, EmailStr, Field


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)


class TokenOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class RefreshIn(BaseModel):
    refresh_token: str


class MeOut(BaseModel):
    id: int
    full_name: str
    work_email: str
    department: str | None = None
    role_name: str | None = None
    permissions: list[str]
    last_seen_at: datetime | None = None


class ForgotPasswordIn(BaseModel):
    email: EmailStr


class ResetPasswordIn(BaseModel):
    token: str
    new_password: str = Field(min_length=8)


class AcceptAdminInviteIn(BaseModel):
    token: str
    password: str | None = Field(None, min_length=8)
