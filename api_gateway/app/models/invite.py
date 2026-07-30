"""Invites, their hosts, and the per-channel notification log."""
from datetime import datetime, timezone

from sqlalchemy import (Boolean, DateTime, ForeignKey, Integer, String, Text)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def utcnow():
    return datetime.now(timezone.utc)


class Invite(Base):
    __tablename__ = "invites"
    id: Mapped[int] = mapped_column(primary_key=True)
    visitor_type_id: Mapped[int] = mapped_column(ForeignKey("visitor_types.id"))
    group_id: Mapped[int | None] = mapped_column(ForeignKey("visitor_groups.id"))
    visitor_id: Mapped[int | None] = mapped_column(ForeignKey("visitors.id"))

    full_name: Mapped[str] = mapped_column(String(150))
    email: Mapped[str | None] = mapped_column(String(200), index=True)
    phone: Mapped[str | None] = mapped_column(String(30))
    company: Mapped[str | None] = mapped_column(String(150))
    additional_visitors: Mapped[int] = mapped_column(Integer, default=0)

    arrival_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime)
    valid_until: Mapped[datetime] = mapped_column(DateTime)

    purpose: Mapped[str | None] = mapped_column(String(300))
    private_notes: Mapped[str | None] = mapped_column(Text)   # staff only
    public_notes: Mapped[str | None] = mapped_column(Text)    # visitor can see
    custom_message: Mapped[str | None] = mapped_column(Text)  # goes into the email
    visitor_message: Mapped[str | None] = mapped_column(Text)  # visitor -> host, optional

    auto_approve: Mapped[bool] = mapped_column(Boolean, default=False)
    send_invite_email: Mapped[bool] = mapped_column(Boolean, default=True)

    # not_sent -> sent -> opened -> submitted -> approved -> used
    #             also: declined / expired / revoked
    status: Mapped[str] = mapped_column(String(20), default="not_sent", index=True)
    token_hash: Mapped[str] = mapped_column(String(80), index=True)

    # Minted only once approved (or auto-approved) - powers the "welcome" SMS/
    # email link. pass_token_hash is hash-only like every other bearer token
    # here; access_code is deliberately PLAINTEXT (like Device.pairing_code)
    # since it must be re-displayed on the pass page and re-typed at a kiosk.
    pass_token_hash: Mapped[str | None] = mapped_column(String(80), index=True)
    access_code: Mapped[str | None] = mapped_column(String(10), index=True)

    legal_docs_status: Mapped[str] = mapped_column(String(20), default="not_required")

    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime)
    opened_at: Mapped[datetime | None] = mapped_column(DateTime)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime)
    used_at: Mapped[datetime | None] = mapped_column(DateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime)

    hosts: Mapped[list["InviteHost"]] = relationship(
        back_populates="invite", cascade="all, delete-orphan", lazy="selectin")


class InviteHost(Base):
    """Many-to-many: an invite can have a primary host plus additional hosts."""
    __tablename__ = "invite_hosts"
    id: Mapped[int] = mapped_column(primary_key=True)
    invite_id: Mapped[int] = mapped_column(ForeignKey("invites.id", ondelete="CASCADE"))
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"))
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    invite: Mapped[Invite] = relationship(back_populates="hosts")


class InviteNotification(Base):
    """Powers the 'Connect Notifications - Not sent' panel on the invite screen.
    A log per channel, not a single boolean."""
    __tablename__ = "invite_notifications"
    id: Mapped[int] = mapped_column(primary_key=True)
    invite_id: Mapped[int] = mapped_column(ForeignKey("invites.id", ondelete="CASCADE"), index=True)
    channel: Mapped[str] = mapped_column(String(20))   # email / sms / teams
    status: Mapped[str] = mapped_column(String(20), default="not_sent")
    sent_at: Mapped[datetime | None] = mapped_column(DateTime)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
