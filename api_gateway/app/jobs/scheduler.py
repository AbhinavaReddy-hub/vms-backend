"""Background maintenance. Runs on a timer, and can also be triggered
manually from POST /api/v1/jobs/run for the demo.
"""
import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models import Invite, VisitorFaceData, Visitor
from app.services import approval_service, checkin_service

log = logging.getLogger(__name__)


def expire_invites(db: Session) -> int:
    now = datetime.now(timezone.utc)
    rows = db.query(Invite).filter(
        Invite.valid_until < now,
        Invite.status.notin_(["used", "expired", "revoked"]),
    ).all()
    for r in rows:
        r.status = "expired"
    db.commit()
    return len(rows)


def purge_face_data(db: Session) -> int:
    """Deletes biometric data past its retention date. This is the job that
    makes the privacy promise real rather than just text on a screen."""
    now = datetime.now(timezone.utc)
    rows = db.query(VisitorFaceData).filter(
        VisitorFaceData.expires_at.isnot(None),
        VisitorFaceData.expires_at < now,
    ).all()
    count = 0
    for r in rows:
        visitor = db.get(Visitor, r.visitor_id)
        if visitor:
            visitor.face_registered_at = None
            visitor.retention_delete_at = None
        db.delete(r)
        count += 1
    db.commit()
    return count


def run_all(db: Session | None = None) -> dict:
    own = db is None
    db = db or SessionLocal()
    try:
        result = {
            "invites_expired": expire_invites(db),
            "visits_auto_closed": checkin_service.auto_close_stale_visits(db),
            "approvals_escalated": approval_service.escalate_overdue(db),
            "face_records_purged": purge_face_data(db),
            "ran_at": datetime.now(timezone.utc).isoformat(),
        }
        log.info("Maintenance jobs: %s", result)
        return result
    finally:
        if own:
            db.close()
