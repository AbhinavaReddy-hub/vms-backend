"""Visitors, their face data, visitor types, and groups."""
from datetime import datetime, timezone

from sqlalchemy import (Boolean, DateTime, Float, ForeignKey, Integer, String, Text)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utcnow():
    return datetime.now(timezone.utc)


class VisitorType(Base):
    """Types are database rows, not a hardcoded list, because Settings lets
    an admin add or change them (Guest, Candidate, Vendor, VIP...)."""
    __tablename__ = "visitor_types"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    badge_color: Mapped[str] = mapped_column(String(20), default="#2563EB")
    requires_approval: Mapped[bool] = mapped_column(Boolean, default=True)
    requires_face: Mapped[bool] = mapped_column(Boolean, default=True)
    requires_legal_docs: Mapped[bool] = mapped_column(Boolean, default=False)
    auto_approve_default: Mapped[bool] = mapped_column(Boolean, default=False)
    default_validity_hours: Mapped[int] = mapped_column(Integer, default=12)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Visitor(Base):
    __tablename__ = "visitors"
    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str] = mapped_column(String(150))
    email: Mapped[str | None] = mapped_column(String(200), index=True)
    phone: Mapped[str | None] = mapped_column(String(30), index=True)
    company: Mapped[str | None] = mapped_column(String(150))
    notes: Mapped[str | None] = mapped_column(Text)

    first_seen_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime)
    consent_given_at: Mapped[datetime | None] = mapped_column(DateTime)
    face_registered_at: Mapped[datetime | None] = mapped_column(DateTime)
    retention_delete_at: Mapped[datetime | None] = mapped_column(DateTime)

    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class VisitorFaceData(Base):
    """Kept in its own table so face data can be deleted on its own,
    without touching the visitor's visit history."""
    __tablename__ = "visitor_face_data"
    id: Mapped[int] = mapped_column(primary_key=True)
    visitor_id: Mapped[int] = mapped_column(ForeignKey("visitors.id", ondelete="CASCADE"), index=True)
    embedding: Mapped[str] = mapped_column(Text)  # JSON list of 512 floats
    photo_path: Mapped[str | None] = mapped_column(String(300))
    quality_score: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime)


class VisitorGroup(Base):
    __tablename__ = "visitor_groups"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150))
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
