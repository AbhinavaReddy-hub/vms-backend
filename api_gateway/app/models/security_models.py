"""Approvals, blocklist, OTP challenges, devices."""
from datetime import datetime, timezone

from sqlalchemy import (Boolean, DateTime, Float, ForeignKey, Integer, String, Text)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utcnow():
    return datetime.now(timezone.utc)


class Approval(Base):
    __tablename__ = "approvals"
    id: Mapped[int] = mapped_column(primary_key=True)
    # walk_in / invite / blocklist_match / screening_match
    approval_type: Mapped[str] = mapped_column(String(30), index=True)
    invite_id: Mapped[int | None] = mapped_column(ForeignKey("invites.id"))
    visit_id: Mapped[int | None] = mapped_column(ForeignKey("visits.id"))
    visitor_id: Mapped[int | None] = mapped_column(ForeignKey("visitors.id"))
    visitor_name: Mapped[str] = mapped_column(String(150))
    visitor_type_id: Mapped[int | None] = mapped_column(ForeignKey("visitor_types.id"))

    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    assigned_to_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id"), index=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime)
    decided_by_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime)
    deny_reason: Mapped[str | None] = mapped_column(Text)
    escalated_at: Mapped[datetime | None] = mapped_column(DateTime)
    match_detail: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class BlocklistEntry(Base):
    __tablename__ = "blocklist"
    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str | None] = mapped_column(String(150))
    email: Mapped[str | None] = mapped_column(String(200), index=True)
    phone: Mapped[str | None] = mapped_column(String(30), index=True)
    reason: Mapped[str] = mapped_column(Text)
    added_by_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class OtpChallenge(Base):
    __tablename__ = "otp_challenges"
    id: Mapped[int] = mapped_column(primary_key=True)
    destination: Mapped[str] = mapped_column(String(200), index=True)
    code_hash: Mapped[str] = mapped_column(String(80))
    purpose: Mapped[str] = mapped_column(String(40))
    ref: Mapped[str | None] = mapped_column(String(120), index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Device(Base):
    """A kiosk tablet. Only registered devices can call /kiosk/* endpoints.

    Three roles (`mode`): registration_kiosk (visitor self-registration, one
    device = one pairing code), checkinout (face/QR/code identify -> check-in
    or check-out), stepinout (same identify, but for roaming - cafeteria,
    washroom - step-out/step-in). checkinout and stepinout are always created
    as a linked ENTRY + EXIT pair (see `paired_device_id`) - each physical
    tablet does exactly one fixed action (`direction`), so the visitor is
    never asked to choose one.
    """
    __tablename__ = "devices"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    location_label: Mapped[str | None] = mapped_column(String(120))
    pairing_code: Mapped[str | None] = mapped_column(String(20), index=True)
    token_hash: Mapped[str | None] = mapped_column(String(80), index=True)
    mode: Mapped[str] = mapped_column(String(20), default="registration_kiosk")
    direction: Mapped[str | None] = mapped_column(String(10))  # entry / exit / None
    paired_device_id: Mapped[int | None] = mapped_column(ForeignKey("devices.id"))
    status: Mapped[str] = mapped_column(String(20), default="unpaired")
    app_version: Mapped[str | None] = mapped_column(String(30))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class WalkInSession(Base):
    """A walk-in registration started by scanning the QR on the kiosk screen.

    The kiosk creates a session and shows its QR. The visitor scans it and
    finishes registration on their OWN phone - no typing on a shared tablet,
    and no personal details left on a public screen. The kiosk polls the
    session so it can show live progress.
    """
    __tablename__ = "walkin_sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(80), index=True)
    device_id: Mapped[int | None] = mapped_column(ForeignKey("devices.id"))

    # waiting -> scanned -> registering -> submitted -> approved / denied / expired
    status: Mapped[str] = mapped_column(String(20), default="waiting", index=True)

    visitor_id: Mapped[int | None] = mapped_column(ForeignKey("visitors.id"))
    visit_id: Mapped[int | None] = mapped_column(ForeignKey("visits.id"))
    approval_id: Mapped[int | None] = mapped_column(ForeignKey("approvals.id"))
    visitor_name: Mapped[str | None] = mapped_column(String(150))
    phone: Mapped[str | None] = mapped_column(String(30))

    expires_at: Mapped[datetime] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
