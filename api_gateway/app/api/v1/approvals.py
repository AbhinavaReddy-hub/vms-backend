from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.deps import get_current_employee, get_request_context
from app.core.pagination import PageParams
from app.core.permissions import require_permission
from app.db.session import get_db
from app.models import Approval, Employee, VisitorType
from app.schemas.common import Msg
from app.schemas.visitor import ApprovalOut, DenyIn
from app.services import approval_service

router = APIRouter(prefix="/approvals", tags=["Approvals"])


def _out(db: Session, a: Approval) -> ApprovalOut:
    host = db.get(Employee, a.assigned_to_id) if a.assigned_to_id else None
    decider = db.get(Employee, a.decided_by_id) if a.decided_by_id else None
    vt = db.get(VisitorType, a.visitor_type_id) if a.visitor_type_id else None
    return ApprovalOut(
        id=a.id, approval_type=a.approval_type, visitor_name=a.visitor_name,
        visitor_type_name=vt.name if vt else None,
        host_name=host.full_name if host else None,
        status=a.status, due_at=a.due_at, created_at=a.created_at,
        decided_at=a.decided_at, decided_by_name=decider.full_name if decider else None,
        deny_reason=a.deny_reason, match_detail=a.match_detail,
        invite_id=a.invite_id, visit_id=a.visit_id,
    )


@router.get("")
def list_approvals(page: PageParams = Depends(),
                   approval_status: str | None = "pending",
                   date_from: str | None = None, date_to: str | None = None,
                   db: Session = Depends(get_db), user=Depends(get_current_employee)):
    q = db.query(Approval)

    # A host without approval permissions only sees their own queue.
    can_see_all = bool({"approvals.decide_invites", "approvals.decide_blocklist",
                        "approvals.decide_screening"} & user._permissions)
    if not can_see_all:
        q = q.filter(Approval.assigned_to_id == user.id)

    if approval_status and approval_status != "all":
        q = q.filter(Approval.status == approval_status)
    if date_from:
        q = q.filter(Approval.created_at >= datetime.fromisoformat(date_from).replace(tzinfo=timezone.utc))
    if date_to:
        end = datetime.fromisoformat(date_to).replace(tzinfo=timezone.utc) + timedelta(days=1)
        q = q.filter(Approval.created_at < end)
    if page.q:
        q = q.filter(Approval.visitor_name.ilike(f"%{page.q}%"))

    total = q.count()
    rows = q.order_by(Approval.created_at.desc()).offset(page.offset).limit(page.page_size).all()
    return {"items": [_out(db, a) for a in rows], "total": total,
            "page": page.page, "page_size": page.page_size}


@router.get("/{approval_id}")
def get_approval(approval_id: int, db: Session = Depends(get_db),
                 user=Depends(get_current_employee)):
    a = db.get(Approval, approval_id)
    if not a:
        raise HTTPException(404, "Approval not found")
    return _out(db, a)


@router.get("/{approval_id}/match-details")
def match_details(approval_id: int, db: Session = Depends(get_db),
                  user=Depends(require_permission("approvals.view_match_details"))):
    """Why this was flagged. Gated behind its own permission because it
    exposes blocklist reasons."""
    a = db.get(Approval, approval_id)
    if not a:
        raise HTTPException(404, "Approval not found")
    return {"approval_id": a.id, "approval_type": a.approval_type,
            "detail": a.match_detail or "No additional detail recorded."}


@router.post("/{approval_id}/approve")
def approve(approval_id: int, db: Session = Depends(get_db),
            user=Depends(get_current_employee), ctx: dict = Depends(get_request_context)):
    a = db.get(Approval, approval_id)
    if not a:
        raise HTTPException(404, "Approval not found")
    _check_can_decide(a, user)
    try:
        a = approval_service.decide(db, approval_id, approve=True, actor=user, ctx=ctx)
    except approval_service.ApprovalError as e:
        raise HTTPException(400, str(e))
    return _out(db, a)


@router.post("/{approval_id}/deny")
def deny(approval_id: int, data: DenyIn, db: Session = Depends(get_db),
         user=Depends(get_current_employee), ctx: dict = Depends(get_request_context)):
    a = db.get(Approval, approval_id)
    if not a:
        raise HTTPException(404, "Approval not found")
    _check_can_decide(a, user)
    try:
        a = approval_service.decide(db, approval_id, approve=False, actor=user,
                                    reason=data.reason, ctx=ctx)
    except approval_service.ApprovalError as e:
        raise HTTPException(400, str(e))
    return _out(db, a)


@router.post("/bulk-decide", response_model=Msg)
def bulk_decide(payload: dict, db: Session = Depends(get_db),
                user=Depends(get_current_employee), ctx: dict = Depends(get_request_context)):
    ids = payload.get("approval_ids", [])
    approve_flag = bool(payload.get("approve", True))
    done = 0
    for aid in ids:
        a = db.get(Approval, aid)
        if not a or a.status != "pending":
            continue
        try:
            _check_can_decide(a, user)
            approval_service.decide(db, aid, approve=approve_flag, actor=user,
                                    reason=payload.get("reason"), ctx=ctx)
            done += 1
        except Exception:
            continue
    return Msg(message=f"{done} approval(s) {'approved' if approve_flag else 'denied'}")


def _check_can_decide(a: Approval, user):
    """The host it is assigned to can always decide. Otherwise you need the
    matching permission for that approval type."""
    if a.assigned_to_id == user.id:
        return
    needed = {
        "walk_in": "approvals.decide_invites",
        "invite": "approvals.decide_invites",
        "blocklist_match": "approvals.decide_blocklist",
        "screening_match": "approvals.decide_screening",
    }.get(a.approval_type, "approvals.decide_invites")
    if needed not in user._permissions:
        raise HTTPException(403, f"Missing permission: {needed}")
