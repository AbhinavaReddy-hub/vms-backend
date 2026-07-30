"""Employees, roles, permissions, admin invitations, refresh tokens."""
from datetime import datetime, timezone

from sqlalchemy import (Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def utcnow():
    return datetime.now(timezone.utc)


class Role(Base):
    __tablename__ = "roles"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    permissions: Mapped[list["RolePermission"]] = relationship(
        back_populates="role", cascade="all, delete-orphan")

    @property
    def permission_keys(self) -> list[str]:
        return [p.permission_key for p in self.permissions]


class RolePermission(Base):
    __tablename__ = "role_permissions"
    __table_args__ = (UniqueConstraint("role_id", "permission_key"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id", ondelete="CASCADE"))
    permission_key: Mapped[str] = mapped_column(String(100))
    role: Mapped[Role] = relationship(back_populates="permissions")


class Employee(Base):
    __tablename__ = "employees"
    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str] = mapped_column(String(150))
    work_email: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    phone: Mapped[str | None] = mapped_column(String(30))
    department: Mapped[str | None] = mapped_column(String(100))
    floor: Mapped[str | None] = mapped_column(String(50))

    # Auth lives here rather than a separate table: it is strictly 1-to-1 and
    # always loaded with the employee, so splitting it would only add a join.
    password_hash: Mapped[str | None] = mapped_column(String(200))
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime)

    role_id: Mapped[int | None] = mapped_column(ForeignKey("roles.id"))
    role: Mapped[Role | None] = relationship(lazy="joined")

    delegate_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id"))
    notify_email: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_teams: Mapped[bool] = mapped_column(Boolean, default=False)
    notify_sms: Mapped[bool] = mapped_column(Boolean, default=False)
    teams_webhook_url: Mapped[str | None] = mapped_column(Text)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    directory_source: Mapped[str] = mapped_column(String(30), default="manual")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AdminInvitation(Base):
    __tablename__ = "admin_invitations"
    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"))
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id"))
    token_hash: Mapped[str] = mapped_column(String(80), index=True)
    invited_by_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id"))
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending/accepted/expired/revoked
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"
    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"))
    token_hash: Mapped[str] = mapped_column(String(80), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime)
    user_agent: Mapped[str | None] = mapped_column(String(300))
    ip: Mapped[str | None] = mapped_column(String(60))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
