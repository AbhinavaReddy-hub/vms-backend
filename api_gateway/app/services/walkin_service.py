"""Walk-in registration started by scanning the QR shown on the kiosk.

Why this exists: typing your name, phone and purpose on a shared lobby tablet
is slow and leaves your details on a public screen. Scanning a QR and filling
the form on your own phone is faster and more private, and it is what the
building's existing system already does - so it is familiar to visitors.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import generate_token, hash_token
from app.models import Approval, Device, Visit, Visitor, WalkInSession

SESSION_MINUTES = 15


class WalkInError(Exception):
    pass


def create_session(db: Session, device: Device | None) -> tuple[WalkInSession, str]:
    raw = generate_token()
    session = WalkInSession(
        token_hash=hash_token(raw),
        device_id=device.id if device else None,
        status="waiting",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=SESSION_MINUTES),
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session, raw


def walkin_url(raw_token: str) -> str:
    return f"{settings.PUBLIC_BASE_URL}/walkin/{raw_token}"


def find(db: Session, raw_token: str) -> WalkInSession:
    session = db.query(WalkInSession).filter(
        WalkInSession.token_hash == hash_token(raw_token)).first()
    if not session:
        raise WalkInError("This code is not valid. Please ask reception for a new one.")
    if session.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
        if session.status in ("waiting", "scanned", "registering"):
            session.status = "expired"
            db.commit()
        raise WalkInError("This code has expired. Scan the QR on the screen again.")
    return session


def mark(db: Session, session: WalkInSession, status: str, **fields):
    session.status = status
    for k, v in fields.items():
        setattr(session, k, v)
    db.commit()
    db.refresh(session)
    return session


def public_status(db: Session, session: WalkInSession) -> dict:
    """Shared by the kiosk poll and the visitor's own phone."""
    approval = db.get(Approval, session.approval_id) if session.approval_id else None
    visitor = db.get(Visitor, session.visitor_id) if session.visitor_id else None

    # Keep the kiosk in step with the real approval decision
    if approval and approval.status != "pending" and session.status not in ("approved", "denied"):
        session.status = "approved" if approval.status == "approved" else "denied"
        db.commit()

    messages = {
        "waiting": "Scan the QR code with your phone camera to check in.",
        "scanned": "Great - carry on with the steps on your phone.",
        "registering": "Almost there. Finish the steps on your phone.",
        "submitted": "Thanks. Your host has been notified - please wait here.",
        "approved": "You're approved! Check your phone for your pass, then scan in at a Check-In kiosk.",
        "denied": "Please speak to reception.",
        "expired": "That code expired. Tap the screen to start again.",
    }
    return {
        "session_id": session.id,
        "status": session.status,
        "visitor_name": session.visitor_name or (visitor.full_name if visitor else None),
        "approval_id": session.approval_id,
        "message": messages.get(session.status, ""),
    }
