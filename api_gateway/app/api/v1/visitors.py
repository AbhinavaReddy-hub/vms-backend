from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.core.deps import get_request_context
from app.core.pagination import PageParams
from app.core.permissions import require_permission
from app.db.session import get_db
from app.models import (Employee, Visit, VisitMovement, Visitor, VisitorFaceData, VisitorType, Device)
from app.schemas.common import Msg
from app.schemas.visitor import MovementOut, VisitorOut, VisitorUpdate, VisitOut
from app.services import export_service
from app.services.audit_service import log_action

router = APIRouter(prefix="/visitors", tags=["Visitors"])


def _visit_count(db: Session, visitor_id: int) -> int:
    return db.query(func.count(Visit.id)).filter(Visit.visitor_id == visitor_id).scalar() or 0


@router.get("")
def list_visitors(page: PageParams = Depends(), db: Session = Depends(get_db),
                  user=Depends(require_permission("visitors.entries.view_all"))):
    q = db.query(Visitor).filter(Visitor.is_active.is_(True))
    if page.q:
        like = f"%{page.q}%"
        q = q.filter(or_(Visitor.full_name.ilike(like), Visitor.email.ilike(like),
                         Visitor.phone.ilike(like), Visitor.company.ilike(like)))
    total = q.count()
    rows = q.order_by(Visitor.last_seen_at.desc().nullslast()).offset(page.offset).limit(page.page_size).all()
    return {"items": [VisitorOut(
        id=v.id, full_name=v.full_name, email=v.email, phone=v.phone, company=v.company,
        total_visits=_visit_count(db, v.id), last_seen_at=v.last_seen_at,
        face_registered=v.face_registered_at is not None,
        face_registered_at=v.face_registered_at, consent_given_at=v.consent_given_at,
        is_blocked=v.is_blocked, notes=v.notes,
    ) for v in rows], "total": total, "page": page.page, "page_size": page.page_size}


@router.get("/{visitor_id}")
def get_visitor(visitor_id: int, db: Session = Depends(get_db),
                user=Depends(require_permission("visitors.entries.view_all"))):
    v = db.get(Visitor, visitor_id)
    if not v:
        raise HTTPException(404, "Visitor not found")
    return VisitorOut(
        id=v.id, full_name=v.full_name, email=v.email, phone=v.phone, company=v.company,
        total_visits=_visit_count(db, v.id), last_seen_at=v.last_seen_at,
        face_registered=v.face_registered_at is not None,
        face_registered_at=v.face_registered_at, consent_given_at=v.consent_given_at,
        is_blocked=v.is_blocked, notes=v.notes,
    )


@router.get("/{visitor_id}/visits")
def visitor_visits(visitor_id: int, db: Session = Depends(get_db),
                   user=Depends(require_permission("visitor_history.view_full",
                                                   "visitors.entries.view_all"))):
    """Full history: every visit, and every movement inside each visit."""
    visits = db.query(Visit).filter(Visit.visitor_id == visitor_id).order_by(Visit.id.desc()).all()
    out = []
    for v in visits:
        movements = db.query(VisitMovement).filter(
            VisitMovement.visit_id == v.id).order_by(VisitMovement.occurred_at).all()
        host = db.get(Employee, v.host_id) if v.host_id else None
        vt = db.get(VisitorType, v.visitor_type_id)
        out.append({
            "id": v.id, "status": v.status, "presence": v.presence,
            "visitor_type": vt.name if vt else None,
            "host_name": host.full_name if host else None,
            "first_entry_at": v.first_entry_at, "last_exit_at": v.last_exit_at,
            "badge_number": v.badge_number,
            "movements": [{
                "id": m.id, "type": m.type, "occurred_at": m.occurred_at,
                "method": m.method, "match_score": m.match_score,
                "is_correction": m.is_correction, "note": m.note,
                "device_name": (db.get(Device, m.device_id).name if m.device_id else None),
            } for m in movements],
        })
    return {"items": out, "total": len(out)}


@router.patch("/{visitor_id}")
def update_visitor(visitor_id: int, data: VisitorUpdate, db: Session = Depends(get_db),
                   user=Depends(require_permission("visitors.entries.edit")),
                   ctx: dict = Depends(get_request_context)):
    v = db.get(Visitor, visitor_id)
    if not v:
        raise HTTPException(404, "Visitor not found")
    payload = data.model_dump(exclude_unset=True)
    for k, val in payload.items():
        setattr(v, k, val)
    db.commit()
    log_action(db, action="visitor.updated", actor=user, entity_type="visitor",
               entity_id=v.id, detail=payload, ctx=ctx)
    return {"success": True}


@router.delete("/{visitor_id}/face-data", response_model=Msg)
def delete_face_data(visitor_id: int, db: Session = Depends(get_db),
                     user=Depends(require_permission("face.data.delete")),
                     ctx: dict = Depends(get_request_context)):
    """Privacy control: remove biometric data without touching visit history."""
    v = db.get(Visitor, visitor_id)
    if not v:
        raise HTTPException(404, "Visitor not found")
    n = db.query(VisitorFaceData).filter(VisitorFaceData.visitor_id == visitor_id).delete()
    v.face_registered_at = None
    v.retention_delete_at = None
    db.commit()
    log_action(db, action="visitor.face_data_deleted", actor=user, entity_type="visitor",
               entity_id=visitor_id, detail={"rows_deleted": n}, ctx=ctx)
    return Msg(message=f"Face data deleted ({n} record(s))")


@router.get("/{visitor_id}/export")
def export_visitor_data(visitor_id: int, db: Session = Depends(get_db),
                        user=Depends(require_permission("privacy.manage")),
                        ctx: dict = Depends(get_request_context)):
    """Everything held about one person - a data subject access request."""
    v = db.get(Visitor, visitor_id)
    if not v:
        raise HTTPException(404, "Visitor not found")
    visits = db.query(Visit).filter(Visit.visitor_id == visitor_id).all()
    log_action(db, action="visitor.data_exported", actor=user, entity_type="visitor",
               entity_id=visitor_id, detail={"name": v.full_name}, ctx=ctx)
    return {
        "visitor": {"id": v.id, "full_name": v.full_name, "email": v.email,
                    "phone": v.phone, "company": v.company,
                    "consent_given_at": v.consent_given_at,
                    "face_registered": v.face_registered_at is not None},
        "visits": [{"id": x.id, "entry": x.first_entry_at, "exit": x.last_exit_at,
                    "status": x.status} for x in visits],
        "note": "Face embeddings are not exported in readable form by design.",
    }


@router.post("/{visitor_id}/block", response_model=Msg)
def block_visitor(visitor_id: int, payload: dict, db: Session = Depends(get_db),
                  user=Depends(require_permission("blocklist.edit")),
                  ctx: dict = Depends(get_request_context)):
    from app.models import BlocklistEntry
    v = db.get(Visitor, visitor_id)
    if not v:
        raise HTTPException(404, "Visitor not found")
    v.is_blocked = True
    db.add(BlocklistEntry(full_name=v.full_name, email=v.email, phone=v.phone,
                          reason=payload.get("reason", "Blocked by admin"),
                          added_by_id=user.id))
    db.commit()
    log_action(db, action="visitor.blocked", actor=user, entity_type="visitor",
               entity_id=visitor_id,
               detail={"name": v.full_name, "reason": payload.get("reason")}, ctx=ctx)
    return Msg(message="Visitor added to blocklist")


@router.delete("/{visitor_id}", response_model=Msg)
def delete_visitor(visitor_id: int, db: Session = Depends(get_db),
                   user=Depends(require_permission("visitors.entries.delete")),
                   ctx: dict = Depends(get_request_context)):
    v = db.get(Visitor, visitor_id)
    if not v:
        raise HTTPException(404, "Visitor not found")
    v.is_active = False   # soft delete - keeps the audit trail honest
    db.query(VisitorFaceData).filter(VisitorFaceData.visitor_id == visitor_id).delete()
    v.face_registered_at = None
    db.commit()
    log_action(db, action="visitor.deleted", actor=user, entity_type="visitor",
               entity_id=visitor_id, detail={"name": v.full_name}, ctx=ctx)
    return Msg(message="Visitor removed and face data deleted")
