"""Invite creation (single + group), token handling, and list queries."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.core.security import generate_token, hash_token
from app.core.tokens import invite_link
from app.models import (Employee, Invite, InviteHost, Visit, Visitor, VisitorGroup, VisitorType)
from app.services import settings_service
from app.services.audit_service import log_action
from app.services.notification_service import notify_visitor_invite
from app.services.qr_service import qr_data_url


class InviteError(Exception):
    pass


def _ensure_aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _reject_if_past(arrival: datetime):
    """Backend backstop behind the admin UI's date/time picker - a 1 minute
    grace window absorbs normal request lag around "right now", not clock
    skew across machines."""
    if arrival < datetime.now(timezone.utc) - timedelta(minutes=1):
        raise ValueError("Arrival time can't be in the past")


def create_invite(db: Session, data, actor: Employee, ctx: dict | None = None) -> tuple[Invite, str]:
    vtype = db.get(VisitorType, data.visitor_type_id)
    if not vtype or not vtype.is_active:
        raise InviteError("Unknown visitor type")

    host = db.get(Employee, data.primary_host_id)
    if not host or not host.is_active:
        raise InviteError("Unknown host")

    arrival = _ensure_aware(data.arrival_at)
    try:
        _reject_if_past(arrival)
    except ValueError as e:
        raise InviteError(str(e))
    valid_until = _ensure_aware(data.valid_until) if data.valid_until else \
        arrival + timedelta(hours=vtype.default_validity_hours)

    raw_token = generate_token()

    invite = Invite(
        visitor_type_id=vtype.id,
        full_name=data.full_name,
        email=data.email,
        phone=data.phone,
        company=data.company,
        additional_visitors=data.additional_visitors,
        arrival_at=arrival,
        valid_from=arrival - timedelta(hours=2),
        valid_until=valid_until,
        purpose=data.purpose,
        private_notes=data.private_notes,
        public_notes=data.public_notes,
        custom_message=data.custom_message,
        auto_approve=data.auto_approve or vtype.auto_approve_default,
        send_invite_email=data.send_invite_email,
        token_hash=hash_token(raw_token),
        legal_docs_status="pending" if vtype.requires_legal_docs else "not_required",
        created_by_id=actor.id,
        status="not_sent",
    )
    db.add(invite)
    db.flush()

    db.add(InviteHost(invite_id=invite.id, employee_id=host.id, is_primary=True))
    for hid in (data.additional_host_ids or []):
        if hid != host.id and db.get(Employee, hid):
            db.add(InviteHost(invite_id=invite.id, employee_id=hid, is_primary=False))
    db.commit()
    db.refresh(invite)

    if data.send_invite_email and data.email:
        send_invite(db, invite, raw_token, host.full_name)

    log_action(db, action="invite.created", actor=actor, entity_type="invite",
               entity_id=invite.id, detail={"name": invite.full_name, "host": host.full_name}, ctx=ctx)
    return invite, raw_token


def send_invite(db: Session, invite: Invite, raw_token: str, host_name: str | None):
    company = settings_service.get_setting(db, "company.name")
    link = invite_link(raw_token)
    try:
        qr = qr_data_url(link)
    except Exception:
        qr = None
    invite.sent_at = datetime.now(timezone.utc)
    invite.status = "sent"
    db.commit()
    notify_visitor_invite(db, invite, raw_token, host_name, company, qr)


def create_group(db: Session, data, actor: Employee, ctx: dict | None = None) -> dict:
    """One admin action, but a SEPARATE token per person.

    A single shared link would let anyone with it register as anyone else,
    which defeats the point of tying an invite to one email.
    """
    vtype = db.get(VisitorType, data.visitor_type_id)
    if not vtype:
        raise InviteError("Unknown visitor type")

    group = VisitorGroup(name=data.group_name, created_by_id=actor.id)
    db.add(group)
    db.flush()

    created, failed, seen_emails = [], [], set()

    for idx, row in enumerate(data.rows, start=1):
        try:
            if not row.full_name.strip():
                raise ValueError("Full name is required")
            if row.email:
                key = row.email.lower()
                if key in seen_emails:
                    raise ValueError("Duplicate email in this batch")
                seen_emails.add(key)

            host_id = row.host_id or data.default_host_id
            host = db.get(Employee, host_id)
            if not host:
                raise ValueError("Unknown host")

            arrival = _ensure_aware(row.arrival_at)
            _reject_if_past(arrival)
            raw_token = generate_token()

            inv = Invite(
                visitor_type_id=vtype.id,
                group_id=group.id,
                full_name=row.full_name,
                email=row.email,
                phone=row.phone,
                arrival_at=arrival,
                valid_from=arrival - timedelta(hours=2),
                valid_until=arrival + timedelta(hours=vtype.default_validity_hours),
                private_notes=row.private_notes,
                public_notes=row.public_notes,
                auto_approve=data.auto_approve or vtype.auto_approve_default,
                send_invite_email=data.send_invite_emails,
                token_hash=hash_token(raw_token),
                legal_docs_status="pending" if vtype.requires_legal_docs else "not_required",
                created_by_id=actor.id,
                status="not_sent",
            )
            db.add(inv)
            db.flush()
            db.add(InviteHost(invite_id=inv.id, employee_id=host.id, is_primary=True))
            db.commit()
            db.refresh(inv)

            if data.send_invite_emails and row.email:
                send_invite(db, inv, raw_token, host.full_name)

            created.append({"row": idx, "invite_id": inv.id, "full_name": inv.full_name,
                            "registration_link": invite_link(raw_token)})
        except Exception as e:
            db.rollback()
            failed.append({"row": idx, "full_name": row.full_name, "error": str(e)})

    log_action(db, action="invite.group_created", actor=actor, entity_type="visitor_group",
               entity_id=group.id, detail={"name": group.name, "created": len(created),
                                           "failed": len(failed)}, ctx=ctx)
    return {"group_id": group.id, "group_name": group.name, "created": len(created),
            "failed": failed, "invites": created}


def find_by_token(db: Session, raw_token: str) -> Invite | None:
    return db.query(Invite).filter(Invite.token_hash == hash_token(raw_token)).first()


def validate_for_registration(db: Session, invite: Invite | None) -> Invite:
    if not invite:
        raise InviteError("This link is not valid.")
    if invite.revoked_at:
        raise InviteError("This invite was cancelled. Please ask your host to resend it.")
    now = datetime.now(timezone.utc)
    if _ensure_aware(invite.valid_until) < now:
        raise InviteError("This link has expired. Please ask your host to resend it.")
    return invite


def is_returning_visitor(db: Session, email: str | None, phone: str | None) -> bool:
    if not email and not phone:
        return False
    conds = []
    if email:
        conds.append(Visitor.email == email)
    if phone:
        conds.append(Visitor.phone == phone)
    visitor = db.query(Visitor).filter(or_(*conds)).first()
    if not visitor:
        return False
    return db.query(func.count(Visit.id)).filter(Visit.visitor_id == visitor.id).scalar() > 0
