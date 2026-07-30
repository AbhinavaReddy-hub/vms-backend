from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.deps import get_request_context
from app.core.pagination import PageParams
from app.core.permissions import require_permission
from app.db.session import get_db
from app.models import BlocklistEntry, Employee
from app.schemas.common import Msg
from app.schemas.visitor import BlocklistIn, BlocklistOut
from app.services import blocklist_service
from app.services.audit_service import log_action

router = APIRouter(prefix="/blocklist", tags=["Blocklist"])


@router.get("")
def list_blocklist(page: PageParams = Depends(), db: Session = Depends(get_db),
                   user=Depends(require_permission("blocklist.view"))):
    q = db.query(BlocklistEntry).filter(BlocklistEntry.is_active.is_(True))
    total = q.count()
    rows = q.order_by(BlocklistEntry.id.desc()).offset(page.offset).limit(page.page_size).all()
    return {"items": [BlocklistOut(
        id=r.id, full_name=r.full_name, email=r.email, phone=r.phone, reason=r.reason,
        added_by_name=(db.get(Employee, r.added_by_id).full_name if r.added_by_id else None),
        is_active=r.is_active, created_at=r.created_at,
    ) for r in rows], "total": total, "page": page.page, "page_size": page.page_size}


@router.post("", status_code=201)
def add_entry(data: BlocklistIn, db: Session = Depends(get_db),
              user=Depends(require_permission("blocklist.edit")),
              ctx: dict = Depends(get_request_context)):
    if not any([data.full_name, data.email, data.phone]):
        raise HTTPException(400, "Provide at least a name, email, or phone")
    entry = BlocklistEntry(full_name=data.full_name, email=data.email, phone=data.phone,
                           reason=data.reason, added_by_id=user.id)
    db.add(entry)
    db.commit()
    db.refresh(entry)
    log_action(db, action="blocklist.added", actor=user, entity_type="blocklist",
               entity_id=entry.id,
               detail={"name": data.full_name or data.email or data.phone, "reason": data.reason},
               ctx=ctx)
    return {"id": entry.id, "success": True}


@router.post("/check")
def check_entry(payload: dict, db: Session = Depends(get_db),
                user=Depends(require_permission("blocklist.view"))):
    hit = blocklist_service.check(db, full_name=payload.get("full_name"),
                                  email=payload.get("email"), phone=payload.get("phone"))
    return {"match": hit is not None,
            "message": "No match was found on your block list" if not hit else f"Match: {hit.reason}",
            "entry_id": hit.id if hit else None}


@router.delete("/{entry_id}", response_model=Msg)
def remove_entry(entry_id: int, payload: dict | None = None, db: Session = Depends(get_db),
                 user=Depends(require_permission("blocklist.edit")),
                 ctx: dict = Depends(get_request_context)):
    entry = db.get(BlocklistEntry, entry_id)
    if not entry:
        raise HTTPException(404, "Entry not found")
    name = entry.full_name or entry.email or entry.phone
    entry.is_active = False
    db.commit()
    log_action(db, action="blocklist.removed", actor=user, entity_type="blocklist",
               entity_id=entry_id,
               detail={"name": name, "reason": (payload or {}).get("reason")}, ctx=ctx)
    return Msg(message="Removed from blocklist")
