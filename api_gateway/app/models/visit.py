"""Visits and every movement inside them.

One visit = one arrival to one final departure.
Cafeteria/lunch/restroom trips are movements INSIDE that visit, not new visits.
"""
from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utcnow():
    return datetime.now(timezone.utc)


class Visit(Base):
    __tablename__ = "visits"
    id: Mapped[int] = mapped_column(primary_key=True)
    visitor_id: Mapped[int] = mapped_column(ForeignKey("visitors.id"), index=True)
    invite_id: Mapped[int | None] = mapped_column(ForeignKey("invites.id"))
    visitor_type_id: Mapped[int] = mapped_column(ForeignKey("visitor_types.id"))
    host_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id"), index=True)

    # pending_approval = walk-in submitted, waiting on a host/security decision
    # approved  = authorized but not yet physically checked in (walk-in only -
    #             the visitor still has to identify themselves at a
    #             Check-In/Out kiosk; see checkin_service.check_in's
    #             resume_visit)
    # open      = inside or stepped out, visit still running
    # closed    = visitor checked out properly
    # auto_closed = end-of-day job closed it, nobody scanned out
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)
    # waiting (pending approval) / arrived (checked in, not yet through the
    # internal Step-In door) / inside / stepped_out / departed (on close)
    presence: Mapped[str] = mapped_column(String(20), default="inside")

    badge_number: Mapped[str | None] = mapped_column(String(30))
    purpose: Mapped[str | None] = mapped_column(String(300))
    additional_visitors: Mapped[int] = mapped_column(Integer, default=0)
    visitor_message: Mapped[str | None] = mapped_column(Text)  # visitor -> host, optional

    # Same shape as Invite's pair - minted once a walk-in is approved (walk-ins
    # have no Invite row, so they need their own pass credentials).
    pass_token_hash: Mapped[str | None] = mapped_column(String(80), index=True)
    access_code: Mapped[str | None] = mapped_column(String(10), index=True)

    first_entry_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_exit_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class VisitMovement(Base):
    __tablename__ = "visit_movements"
    id: Mapped[int] = mapped_column(primary_key=True)
    visit_id: Mapped[int] = mapped_column(ForeignKey("visits.id", ondelete="CASCADE"), index=True)
    # entry / step_out / step_in / exit
    type: Mapped[str] = mapped_column(String(20))
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    device_id: Mapped[int | None] = mapped_column(ForeignKey("devices.id"))
    # face / qr / otp / manual
    method: Mapped[str] = mapped_column(String(20), default="face")
    match_score: Mapped[float | None] = mapped_column(Float)
    recorded_by_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id"))
    note: Mapped[str | None] = mapped_column(Text)
    is_correction: Mapped[bool] = mapped_column(default=False)
