from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from app.core.deps import get_request_context
from app.core.pagination import PageParams
from app.core.permissions import require_permission
from app.db.session import get_db
from app.models import Device, Employee, Visit, VisitMovement, Visitor, VisitorType
from app.schemas.common import Msg
from app.services import checkin_service, export_service
from app.services.audit_service import log_action

router = APIRouter(prefix="/visits", tags=["Visits & Logs"])


def _row(db: Session, v: Visit, with_movements: bool = False):
    visitor = db.get(Visitor, v.visitor_id)
    host = db.get(Employee, v.host_id) if v.host_id else None
    vt = db.get(VisitorType, v.visitor_type_id)
    movements = []
    if with_movements:
        movements = [{
            "id": m.id, "type": m.type, "occurred_at": m.occurred_at, "method": m.method,
            "match_score": m.match_score, "is_correction": m.is_correction, "note": m.note,
            "device_name": (db.get(Device, m.device_id).name if m.device_id else None),
        } for m in db.query(VisitMovement).filter(VisitMovement.visit_id == v.id)
            .order_by(VisitMovement.occurred_at).all()]
    step_outs = db.query(VisitMovement).filter(
        VisitMovement.visit_id == v.id, VisitMovement.type == "step_out").count()
    return {
        "id": v.id, "visitor_id": v.visitor_id,
        "visitor_name": visitor.full_name if visitor else "?",
        "visitor_type_name": vt.name if vt else None,
        "badge_color": vt.badge_color if vt else None,
        "host_id": v.host_id, "host_name": host.full_name if host else None,
        "status": v.status, "presence": v.presence, "purpose": v.purpose,
        "badge_number": v.badge_number, "additional_visitors": v.additional_visitors,
        "first_entry_at": v.first_entry_at, "last_exit_at": v.last_exit_at,
        "minutes_inside": checkin_service._minutes_inside(v),
        "step_out_count": step_outs,
        "movements": movements,
    }


@router.get("")
def list_visits(page: PageParams = Depends(),
                date_from: str | None = None, date_to: str | None = None,
                visit_status: str | None = Query(None, alias="status"),
                host_id: int | None = None, visitor_type_id: int | None = None,
                db: Session = Depends(get_db),
                user=Depends(require_permission("visitors.entries.view_all"))):
    q = db.query(Visit)
    if date_from:
        q = q.filter(Visit.first_entry_at >= datetime.fromisoformat(date_from).replace(tzinfo=timezone.utc))
    if date_to:
        end = datetime.fromisoformat(date_to).replace(tzinfo=timezone.utc) + timedelta(days=1)
        q = q.filter(Visit.first_entry_at < end)
    if visit_status:
        q = q.filter(Visit.status == visit_status)
    if host_id:
        q = q.filter(Visit.host_id == host_id)
    if visitor_type_id:
        q = q.filter(Visit.visitor_type_id == visitor_type_id)

    total = q.count()
    rows = q.order_by(Visit.id.desc()).offset(page.offset).limit(page.page_size).all()
    return {"items": [_row(db, v) for v in rows], "total": total,
            "page": page.page, "page_size": page.page_size}


@router.get("/export")
def export_visits(db: Session = Depends(get_db),
                  user=Depends(require_permission("visitors.entries.export_all"))):
    rows = db.query(Visit).order_by(Visit.id.desc()).limit(5000).all()
    data = [_row(db, v) for v in rows]
    csv_text = export_service.to_csv(data, columns=[
        "id", "visitor_name", "visitor_type_name", "host_name", "status", "presence",
        "first_entry_at", "last_exit_at", "minutes_inside", "step_out_count"])
    log_action(db, action="visit.exported", actor=user, detail={"count": len(rows)})
    return Response(csv_text, media_type="text/csv",
                    headers={"Content-Disposition": "attachment; filename=visits.csv"})


@router.get("/{visit_id}")
def get_visit(visit_id: int, db: Session = Depends(get_db),
              user=Depends(require_permission("visitors.entries.view_all"))):
    v = db.get(Visit, visit_id)
    if not v:
        raise HTTPException(404, "Visit not found")
    return _row(db, v, with_movements=True)


@router.post("/{visit_id}/force-close", response_model=Msg)
def force_close(visit_id: int, db: Session = Depends(get_db),
                user=Depends(require_permission("visitors.entries.edit")),
                ctx: dict = Depends(get_request_context)):
    """Someone forgot to scan out. Recorded as a manual action, not a fake face scan."""
    v = db.get(Visit, visit_id)
    if not v:
        raise HTTPException(404, "Visit not found")
    if v.status != "open":
        raise HTTPException(400, f"Visit is already {v.status}")
    visitor = db.get(Visitor, v.visitor_id)
    checkin_service.check_out(db, visitor=visitor, method="manual", actor=user)
    log_action(db, action="visit.force_closed", actor=user, entity_type="visit",
               entity_id=visit_id, detail={"visitor": visitor.full_name}, ctx=ctx)
    return Msg(message="Visit closed manually")


@router.post("/{visit_id}/correct", response_model=Msg)
def correct_movement(visit_id: int, payload: dict, db: Session = Depends(get_db),
                     user=Depends(require_permission("visitors.entries.edit")),
                     ctx: dict = Depends(get_request_context)):
    """Corrections create a NEW row. The original is never overwritten -
    that is what makes the log trustworthy."""
    v = db.get(Visit, visit_id)
    if not v:
        raise HTTPException(404, "Visit not found")
    mtype = payload.get("type")
    when = payload.get("occurred_at")
    if not mtype or not when:
        raise HTTPException(400, "type and occurred_at are required")
    db.add(VisitMovement(
        visit_id=visit_id, type=mtype,
        occurred_at=datetime.fromisoformat(when).replace(tzinfo=timezone.utc),
        method="manual", recorded_by_id=user.id, is_correction=True,
        note=payload.get("note", "Manual correction"),
    ))
    db.commit()
    log_action(db, action="visit.movement_corrected", actor=user, entity_type="visit",
               entity_id=visit_id, detail=payload, ctx=ctx)
    return Msg(message="Correction recorded as a new entry")
