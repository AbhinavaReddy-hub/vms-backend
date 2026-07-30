from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_current_employee
from app.core.permissions import require_permission
from app.db.session import get_db
from app.models import Employee, Visit, Visitor, VisitorType
from app.services import analytics_service, settings_service

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


@router.get("/summary")
def summary(db: Session = Depends(get_db), user=Depends(get_current_employee)):
    data = analytics_service.dashboard_summary(db)
    data["company_name"] = settings_service.get_setting(db, "company.name")
    cap = settings_service.get_setting(db, "capacity.max_expected_per_day") or 10
    expected = data["expected_later_today"] + data["currently_on_site"]
    data["capacity"] = {
        "expected": expected, "limit": cap,
        "band": "low" if expected < cap * 0.5 else ("medium" if expected < cap else "full"),
    }
    return data


@router.get("/on-site")
def on_site(db: Session = Depends(get_db),
            user=Depends(require_permission("visitors.entries.view_all"))):
    """The live 'who is inside right now' board."""
    rows = db.query(Visit).filter(Visit.status == "open").order_by(Visit.first_entry_at.desc()).all()
    out = []
    now = datetime.now(timezone.utc)
    for v in rows:
        visitor = db.get(Visitor, v.visitor_id)
        vt = db.get(VisitorType, v.visitor_type_id)
        host = db.get(Employee, v.host_id) if v.host_id else None
        mins = int((now - v.first_entry_at.replace(tzinfo=timezone.utc)).total_seconds() // 60) \
            if v.first_entry_at else None
        out.append({
            "visit_id": v.id, "visitor_id": v.visitor_id,
            "visitor_name": visitor.full_name if visitor else "?",
            "company": visitor.company if visitor else None,
            "visitor_type": vt.name if vt else None,
            "badge_color": vt.badge_color if vt else None,
            "host_name": host.full_name if host else None,
            "badge_number": v.badge_number,
            "presence": v.presence,
            "entry_at": v.first_entry_at,
            "minutes_inside": mins,
            "additional_visitors": v.additional_visitors,
        })
    return {"items": out, "total": len(out)}


@router.get("/evacuation-list")
def evacuation_list(db: Session = Depends(get_db),
                    user=Depends(require_permission("visitors.entries.view_all"))):
    """Everyone currently in the building, grouped by host. For a fire drill.
    Includes "arrived" (checked in at reception, not yet through the internal
    Step-In door) since they are still physically in the building - excluding
    them would undercount a real evacuation headcount."""
    rows = db.query(Visit).filter(Visit.status == "open",
                                  Visit.presence.in_(["inside", "arrived"])).all()
    grouped: dict[str, list] = {}
    total = 0
    for v in rows:
        visitor = db.get(Visitor, v.visitor_id)
        host = db.get(Employee, v.host_id) if v.host_id else None
        key = host.full_name if host else "Unassigned"
        grouped.setdefault(key, []).append({
            "visitor_name": visitor.full_name if visitor else "?",
            "badge_number": v.badge_number,
            "entry_at": v.first_entry_at,
            "party_size": 1 + v.additional_visitors,
        })
        total += 1 + v.additional_visitors
    return {"generated_at": datetime.now(timezone.utc), "total_people": total, "by_host": grouped}
