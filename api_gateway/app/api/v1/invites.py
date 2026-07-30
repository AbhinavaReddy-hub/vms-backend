from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.deps import get_current_employee, get_request_context
from app.core.permissions import require_permission
from app.core.pagination import PageParams
from app.core.security import generate_token, hash_token
from app.core.tokens import invite_link
from app.db.session import get_db
from app.models import (Employee, Invite, InviteHost, InviteNotification,
                        Visit, VisitorGroup, VisitorType)
from app.schemas.common import Msg
from app.schemas.invite import (BulkActionIn, GroupInviteIn, InviteIn, InviteOut, InviteUpdate)
from app.services import blocklist_service, export_service, invite_service
from app.services.audit_service import log_action

router = APIRouter(prefix="/invites", tags=["Invites"])


def _to_out(db: Session, inv: Invite, link: str | None = None) -> InviteOut:
    vt = db.get(VisitorType, inv.visitor_type_id)
    grp = db.get(VisitorGroup, inv.group_id) if inv.group_id else None
    creator = db.get(Employee, inv.created_by_id) if inv.created_by_id else None
    hosts, primary_name = [], None
    for h in inv.hosts:
        emp = db.get(Employee, h.employee_id)
        if emp:
            hosts.append({"id": emp.id, "full_name": emp.full_name, "is_primary": h.is_primary})
            if h.is_primary:
                primary_name = emp.full_name
    signed_in = None
    if inv.visitor_id:
        v = db.query(Visit).filter(Visit.invite_id == inv.id).first()
        signed_in = v.first_entry_at if v else None
    return InviteOut(
        id=inv.id, visitor_type_id=inv.visitor_type_id,
        visitor_type_name=vt.name if vt else None,
        group_id=inv.group_id, group_name=grp.name if grp else None,
        full_name=inv.full_name, email=inv.email, phone=inv.phone, company=inv.company,
        additional_visitors=inv.additional_visitors,
        arrival_at=inv.arrival_at, valid_until=inv.valid_until, purpose=inv.purpose,
        private_notes=inv.private_notes, public_notes=inv.public_notes,
        custom_message=inv.custom_message, auto_approve=inv.auto_approve,
        status=inv.status, legal_docs_status=inv.legal_docs_status,
        is_returning_visitor=invite_service.is_returning_visitor(db, inv.email, inv.phone),
        signed_in_at=signed_in, hosts=hosts, primary_host_name=primary_name,
        created_by_id=inv.created_by_id,
        created_by_name=creator.full_name if creator else None,
        created_at=inv.created_at, sent_at=inv.sent_at, opened_at=inv.opened_at,
        submitted_at=inv.submitted_at, registration_link=link,
    )


@router.get("")
def list_invites(
    page: PageParams = Depends(),
    date: str | None = Query(None, description="YYYY-MM-DD, filters by arrival day"),
    visitor_type_id: int | None = None,
    invite_status: str | None = Query(None, alias="status"),
    db: Session = Depends(get_db),
    user=Depends(require_permission("invites.view_all", "employees.view")),
):
    q = db.query(Invite)

    # Row-level rule: a plain Host only sees invites they are a host on.
    if "invites.view_all" not in user._permissions:
        q = q.join(InviteHost).filter(InviteHost.employee_id == user.id)

    if date:
        day = datetime.fromisoformat(date).replace(tzinfo=timezone.utc)
        q = q.filter(Invite.arrival_at >= day, Invite.arrival_at < day + timedelta(days=1))
    if visitor_type_id:
        q = q.filter(Invite.visitor_type_id == visitor_type_id)
    if invite_status:
        q = q.filter(Invite.status == invite_status)
    if page.q:
        like = f"%{page.q}%"
        q = q.filter(or_(Invite.full_name.ilike(like), Invite.email.ilike(like),
                         Invite.company.ilike(like)))

    sortable = {"name": Invite.full_name, "due_at": Invite.arrival_at,
                "created_at": Invite.created_at, "status": Invite.status}
    col = sortable.get(page.sort_by or "due_at", Invite.arrival_at)
    q = q.order_by(col.desc() if page.sort_dir == "desc" else col.asc())

    total = q.count()
    rows = q.offset(page.offset).limit(page.page_size).all()
    return {"items": [_to_out(db, r) for r in rows], "total": total,
            "page": page.page, "page_size": page.page_size}


@router.post("", status_code=status.HTTP_201_CREATED)
def create_invite(data: InviteIn, db: Session = Depends(get_db),
                  user=Depends(get_current_employee), ctx: dict = Depends(get_request_context)):
    try:
        inv, raw = invite_service.create_invite(db, data, user, ctx)
    except invite_service.InviteError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    return _to_out(db, inv, invite_link(raw))


@router.post("/bulk", status_code=status.HTTP_201_CREATED)
def create_group_invite(data: GroupInviteIn, db: Session = Depends(get_db),
                        user=Depends(get_current_employee),
                        ctx: dict = Depends(get_request_context)):
    try:
        return invite_service.create_group(db, data, user, ctx)
    except invite_service.InviteError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))


@router.get("/export")
def export_invites(db: Session = Depends(get_db),
                   user=Depends(require_permission("invites.export_all"))):
    rows = db.query(Invite).order_by(Invite.arrival_at.desc()).limit(5000).all()
    data = [{
        "id": r.id, "full_name": r.full_name, "email": r.email, "phone": r.phone,
        "arrival_at": r.arrival_at, "status": r.status,
        "host": next((db.get(Employee, h.employee_id).full_name
                      for h in r.hosts if h.is_primary), ""),
    } for r in rows]
    csv_text = export_service.to_csv(data)
    log_action(db, action="invite.exported", actor=user, detail={"count": len(rows)})
    return Response(csv_text, media_type="text/csv",
                    headers={"Content-Disposition": "attachment; filename=invites.csv"})


@router.get("/{invite_id}")
def get_invite(invite_id: int, db: Session = Depends(get_db),
               user=Depends(get_current_employee)):
    inv = db.get(Invite, invite_id)
    if not inv:
        raise HTTPException(404, "Invite not found")
    out = _to_out(db, inv)
    # Private notes are staff-only; hide from anyone without invite view rights.
    if "invites.view_all" not in user._permissions and \
            not any(h.employee_id == user.id for h in inv.hosts):
        raise HTTPException(403, "Not your invite")
    return out


@router.get("/{invite_id}/blocklist-check")
def blocklist_check(invite_id: int, db: Session = Depends(get_db),
                    user=Depends(require_permission("blocklist.view"))):
    inv = db.get(Invite, invite_id)
    if not inv:
        raise HTTPException(404, "Invite not found")
    hit = blocklist_service.check(db, full_name=inv.full_name, email=inv.email, phone=inv.phone)
    return {"match": hit is not None,
            "message": "No match was found on your block list" if not hit
                       else f"Match found: {hit.reason}",
            "entry_id": hit.id if hit else None}


@router.get("/{invite_id}/notifications")
def invite_notifications(invite_id: int, db: Session = Depends(get_db),
                         user=Depends(get_current_employee)):
    rows = db.query(InviteNotification).filter(
        InviteNotification.invite_id == invite_id).all()
    if not rows:
        return {"items": [{"channel": "email", "status": "not_sent", "sent_at": None}]}
    return {"items": [{"channel": r.channel, "status": r.status,
                       "sent_at": r.sent_at, "error": r.error} for r in rows]}


@router.patch("/{invite_id}")
def update_invite(invite_id: int, data: InviteUpdate, db: Session = Depends(get_db),
                  user=Depends(require_permission("invites.edit_all", "employees.view")),
                  ctx: dict = Depends(get_request_context)):
    inv = db.get(Invite, invite_id)
    if not inv:
        raise HTTPException(404, "Invite not found")
    if "invites.edit_all" not in user._permissions and \
            not any(h.employee_id == user.id for h in inv.hosts):
        raise HTTPException(403, "Not your invite")

    payload = data.model_dump(exclude_unset=True)
    host_ids = payload.pop("additional_host_ids", None)
    primary = payload.pop("primary_host_id", None)
    for k, v in payload.items():
        setattr(inv, k, v)

    if primary or host_ids is not None:
        db.query(InviteHost).filter(InviteHost.invite_id == inv.id).delete()
        pid = primary or (inv.hosts[0].employee_id if inv.hosts else None)
        if pid:
            db.add(InviteHost(invite_id=inv.id, employee_id=pid, is_primary=True))
        for hid in (host_ids or []):
            if hid != pid:
                db.add(InviteHost(invite_id=inv.id, employee_id=hid, is_primary=False))
    db.commit()
    db.refresh(inv)
    log_action(db, action="invite.updated", actor=user, entity_type="invite",
               entity_id=inv.id, detail=payload, ctx=ctx)
    return _to_out(db, inv)


@router.post("/{invite_id}/resend", response_model=Msg)
def resend(invite_id: int, db: Session = Depends(get_db),
           user=Depends(get_current_employee), ctx: dict = Depends(get_request_context)):
    inv = db.get(Invite, invite_id)
    if not inv:
        raise HTTPException(404, "Invite not found")
    # Old token is replaced - a resend invalidates the previous link.
    raw = generate_token()
    inv.token_hash = hash_token(raw)
    db.commit()
    host = next((db.get(Employee, h.employee_id) for h in inv.hosts if h.is_primary), None)
    invite_service.send_invite(db, inv, raw, host.full_name if host else None)
    log_action(db, action="invite.resent", actor=user, entity_type="invite",
               entity_id=inv.id, detail={"name": inv.full_name, "email": inv.email}, ctx=ctx)
    return Msg(message=f"Invite resent to {inv.email}")


@router.post("/{invite_id}/revoke", response_model=Msg)
def revoke(invite_id: int, db: Session = Depends(get_db),
           user=Depends(get_current_employee), ctx: dict = Depends(get_request_context)):
    inv = db.get(Invite, invite_id)
    if not inv:
        raise HTTPException(404, "Invite not found")
    inv.revoked_at = datetime.now(timezone.utc)
    inv.status = "revoked"
    db.commit()
    log_action(db, action="invite.revoked", actor=user, entity_type="invite",
               entity_id=inv.id, detail={"name": inv.full_name}, ctx=ctx)
    return Msg(message="Invite revoked")


@router.delete("/{invite_id}", response_model=Msg)
def delete_invite(invite_id: int, db: Session = Depends(get_db),
                  user=Depends(require_permission("invites.delete_all")),
                  ctx: dict = Depends(get_request_context)):
    inv = db.get(Invite, invite_id)
    if not inv:
        raise HTTPException(404, "Invite not found")
    log_action(db, action="invite.deleted", actor=user, entity_type="invite",
               entity_id=inv.id, detail={"name": inv.full_name}, ctx=ctx)
    db.delete(inv)
    db.commit()
    return Msg(message="Invite deleted")


@router.post("/bulk-action", response_model=Msg)
def bulk_action(data: BulkActionIn, db: Session = Depends(get_db),
                user=Depends(get_current_employee), ctx: dict = Depends(get_request_context)):
    count = 0
    for iid in data.invite_ids:
        inv = db.get(Invite, iid)
        if not inv:
            continue
        if data.action == "revoke":
            inv.revoked_at = datetime.now(timezone.utc)
            inv.status = "revoked"
            count += 1
        elif data.action == "delete":
            if "invites.delete_all" not in user._permissions:
                raise HTTPException(403, "Missing permission: invites.delete_all")
            db.delete(inv)
            count += 1
    db.commit()
    log_action(db, action=f"invite.bulk_{data.action}", actor=user,
               detail={"count": count}, ctx=ctx)
    return Msg(message=f"{data.action} applied to {count} invite(s)")
