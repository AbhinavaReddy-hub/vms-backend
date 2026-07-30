"""Notifications, audit log, settings, legal documents."""
from datetime import datetime, timezone

from sqlalchemy import (Boolean, DateTime, ForeignKey, Integer, String, Text)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utcnow():
    return datetime.now(timezone.utc)


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), index=True)
    type: Mapped[str] = mapped_column(String(50))
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str | None] = mapped_column(Text)
    entity_type: Mapped[str | None] = mapped_column(String(50))
    entity_id: Mapped[int | None] = mapped_column(Integer)
    severity: Mapped[str] = mapped_column(String(20), default="info")
    read_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class AuditLog(Base):
    """Append-only. Nothing in the API can edit or delete a row here.
    Corrections are written as new rows."""
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    actor_id: Mapped[int | None] = mapped_column(Integer)
    actor_type: Mapped[str] = mapped_column(String(20), default="employee")
    actor_name: Mapped[str | None] = mapped_column(String(150))
    action: Mapped[str] = mapped_column(String(80), index=True)
    entity_type: Mapped[str | None] = mapped_column(String(50))
    entity_id: Mapped[int | None] = mapped_column(Integer)
    detail: Mapped[str | None] = mapped_column(Text)
    ip: Mapped[str | None] = mapped_column(String(60))
    user_agent: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class AppSetting(Base):
    """One flexible key/value table instead of a dozen tiny settings tables."""
    __tablename__ = "app_settings"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    updated_by_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id"))


class LegalDocument(Base):
    __tablename__ = "legal_documents"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150))
    version: Mapped[str] = mapped_column(String(20), default="1.0")
    content: Mapped[str] = mapped_column(Text)
    visitor_type_id: Mapped[int | None] = mapped_column(ForeignKey("visitor_types.id"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class LegalSignature(Base):
    __tablename__ = "legal_signatures"
    id: Mapped[int] = mapped_column(primary_key=True)
    visitor_id: Mapped[int] = mapped_column(ForeignKey("visitors.id"))
    invite_id: Mapped[int | None] = mapped_column(ForeignKey("invites.id"))
    document_id: Mapped[int] = mapped_column(ForeignKey("legal_documents.id"))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    signed_at: Mapped[datetime | None] = mapped_column(DateTime)
    signature_ref: Mapped[str | None] = mapped_column(String(200))
