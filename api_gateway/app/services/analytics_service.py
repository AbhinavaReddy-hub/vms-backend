"""Reporting queries. Kept out of the routers so they can be tested alone."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import (Employee, Invite, Visit, VisitMovement, Visitor, VisitorType)


def _range(days: int):
    end = datetime.now(timezone.utc)
    return end - timedelta(days=days), end


def visits_over_time(db: Session, days: int = 30):
    start, end = _range(days)
    rows = (db.query(func.date(Visit.first_entry_at).label("day"), func.count(Visit.id))
            .filter(Visit.first_entry_at >= start)
            .group_by("day").order_by("day").all())
    return [{"date": str(r[0]), "visits": r[1]} for r in rows]


def peak_hours(db: Session, days: int = 30):
    start, _ = _range(days)
    rows = (db.query(Visit.first_entry_at).filter(Visit.first_entry_at >= start).all())
    buckets = {h: 0 for h in range(24)}
    for (dt,) in rows:
        if dt:
            buckets[dt.hour] += 1
    return [{"hour": h, "visits": c} for h, c in buckets.items()]


def visitor_type_breakdown(db: Session, days: int = 30):
    start, _ = _range(days)
    rows = (db.query(VisitorType.name, func.count(Visit.id))
            .join(Visit, Visit.visitor_type_id == VisitorType.id)
            .filter(Visit.first_entry_at >= start)
            .group_by(VisitorType.name).all())
    return [{"visitor_type": r[0], "visits": r[1]} for r in rows]


def top_hosts(db: Session, days: int = 30, limit: int = 10):
    start, _ = _range(days)
    rows = (db.query(Employee.full_name, func.count(Visit.id).label("c"))
            .join(Visit, Visit.host_id == Employee.id)
            .filter(Visit.first_entry_at >= start)
            .group_by(Employee.full_name).order_by(func.count(Visit.id).desc())
            .limit(limit).all())
    return [{"host": r[0], "visits": r[1]} for r in rows]


def average_time_inside(db: Session, days: int = 30):
    start, _ = _range(days)
    visits = (db.query(Visit).filter(Visit.first_entry_at >= start,
                                     Visit.last_exit_at.isnot(None)).all())
    by_type: dict[int, list[int]] = {}
    for v in visits:
        mins = int((v.last_exit_at - v.first_entry_at).total_seconds() // 60)
        by_type.setdefault(v.visitor_type_id, []).append(mins)
    out = []
    for tid, vals in by_type.items():
        vt = db.get(VisitorType, tid)
        out.append({"visitor_type": vt.name if vt else str(tid),
                    "average_minutes": round(sum(vals) / len(vals), 1),
                    "sample_size": len(vals)})
    return out


def invite_funnel(db: Session, days: int = 30):
    start, _ = _range(days)
    q = db.query(Invite).filter(Invite.created_at >= start)
    total = q.count()
    return {
        "created": total,
        "sent": q.filter(Invite.sent_at.isnot(None)).count(),
        "opened": q.filter(Invite.opened_at.isnot(None)).count(),
        "submitted": q.filter(Invite.submitted_at.isnot(None)).count(),
        "used": q.filter(Invite.used_at.isnot(None)).count(),
        "no_show": q.filter(Invite.submitted_at.isnot(None), Invite.used_at.is_(None)).count(),
    }


def face_performance(db: Session, days: int = 30):
    """Monitoring our own model - how often face matching actually worked."""
    start, _ = _range(days)
    rows = db.query(VisitMovement).filter(VisitMovement.occurred_at >= start).all()
    face = [r for r in rows if r.method == "face" and r.match_score is not None]
    fallback = [r for r in rows if r.method in ("otp", "qr", "manual")]
    return {
        "face_movements": len(face),
        "fallback_movements": len(fallback),
        "face_success_rate": round(len(face) / max(len(rows), 1) * 100, 1),
        "average_match_score": round(sum(r.match_score for r in face) / len(face), 3) if face else None,
    }


def dashboard_summary(db: Session):
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    on_site = db.query(func.count(Visit.id)).filter(
        Visit.status == "open", Visit.presence.in_(["inside", "arrived"])).scalar()
    stepped_out = db.query(func.count(Visit.id)).filter(
        Visit.status == "open", Visit.presence == "stepped_out").scalar()
    expected = db.query(func.count(Invite.id)).filter(
        Invite.arrival_at >= today_start,
        Invite.arrival_at < today_start + timedelta(days=1),
        Invite.used_at.is_(None),
        Invite.revoked_at.is_(None),
    ).scalar()
    checked_out = db.query(func.count(Visit.id)).filter(
        Visit.last_exit_at >= today_start).scalar()
    from app.models import Approval
    pending = db.query(func.count(Approval.id)).filter(Approval.status == "pending").scalar()
    return {
        "currently_on_site": on_site or 0,
        "stepped_out": stepped_out or 0,
        "expected_later_today": expected or 0,
        "checked_out_today": checked_out or 0,
        "pending_approvals": pending or 0,
    }
