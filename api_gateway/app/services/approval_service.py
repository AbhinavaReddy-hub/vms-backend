"""Approval creation, decisions, and escalation."""
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.tokens import admin_link
from app.models import Approval, Employee, Visit
from app.services import settings_service
from app.services.audit_service import log_action
from app.services.notification_service import notify_employee


class ApprovalError(Exception):
    pass


def create(db: Session, *, approval_type: str, visitor_name: str, assigned_to_id: int | None,
           invite_id: int | None = None, visit_id: int | None = None,
           visitor_id: int | None = None, visitor_type_id: int | None = None,
           match_detail: str | None = None, message: str | None = None) -> Approval:
    timeout = settings_service.get_setting(db, "approval.timeout_minutes") or 3
    approval = Approval(
        approval_type=approval_type,
        visitor_name=visitor_name,
        assigned_to_id=assigned_to_id,
        invite_id=invite_id,
        visit_id=visit_id,
        visitor_id=visitor_id,
        visitor_type_id=visitor_type_id,
        match_detail=match_detail,
        due_at=datetime.now(timezone.utc) + timedelta(minutes=timeout),
    )
    db.add(approval)
    db.commit()
    db.refresh(approval)

    host = db.get(Employee, assigned_to_id) if assigned_to_id else None
    facts = {"Visitor": visitor_name, "Type": approval_type.replace("_", " ").title()}
    if message:
        facts["Message"] = message
    notify_employee(
        db, host,
        type="approval_request",
        title=f"Approval needed for {visitor_name}",
        body=f"{visitor_name} is waiting at reception for your approval before they can come in.",
        entity_type="approval", entity_id=approval.id,
        severity="action_required",
        facts=facts,
        actions=[
            {"title": "Approve", "url": admin_link(f"/visitors/approvals?id={approval.id}&action=approve")},
            {"title": "Deny", "url": admin_link(f"/visitors/approvals?id={approval.id}&action=deny")},
        ],
    )
    return approval


def decide(db: Session, approval_id: int, *, approve: bool, actor: Employee,
           reason: str | None = None, ctx: dict | None = None) -> Approval:
    from app.models import Invite, Visitor
    from app.services import pass_service
    from app.services.notification_service import notify_visitor_welcome

    approval = db.get(Approval, approval_id)
    if not approval:
        raise ApprovalError("Approval not found")
    if approval.status != "pending":
        raise ApprovalError(f"Already {approval.status}")

    approval.status = "approved" if approve else "denied"
    approval.decided_by_id = actor.id
    approval.decided_at = datetime.now(timezone.utc)
    approval.deny_reason = reason if not approve else None

    # Who to send the "you're approved" welcome SMS/email to, and with which
    # freshly-minted pass credentials - set below, sent after commit.
    to_notify: tuple[object, str, str] | None = None  # (entity, raw_pass_token, access_code)

    # A walk-in approval AUTHORIZES the visit - it does not open it. The
    # visitor still has to identify themselves at a Check-In/Out kiosk
    # (face/QR/code); see checkin_service.check_in's resume_visit.
    if approve and approval.visit_id:
        visit = db.get(Visit, approval.visit_id)
        if visit and visit.status == "pending_approval":
            visit.status = "approved"
            raw_token, code = pass_service.mint_credentials(visit)
            to_notify = (visit, raw_token, code)

    # An invite approval updates the invite itself, so the list screen and
    # the kiosk both see the real state.
    if approval.invite_id:
        invite = db.get(Invite, approval.invite_id)
        if invite and invite.status not in ("used", "revoked", "expired"):
            invite.status = "approved" if approve else "declined"
            if approve and invite.visitor_id:
                raw_token, code = pass_service.mint_credentials(invite)
                to_notify = (invite, raw_token, code)

    db.commit()
    db.refresh(approval)

    if to_notify:
        entity, raw_token, code = to_notify
        visitor = db.get(Visitor, entity.visitor_id)
        host = db.get(Employee, approval.assigned_to_id) if approval.assigned_to_id else None
        if visitor:
            notify_visitor_welcome(db, visitor=visitor, pass_token_raw=raw_token, access_code=code,
                                   host_name=host.full_name if host else None,
                                   company_name=settings_service.get_setting(db, "company.name"))

    log_action(db, action="approval.approved" if approve else "approval.denied",
               actor=actor, entity_type="approval", entity_id=approval.id,
               detail={"visitor": approval.visitor_name, "reason": reason}, ctx=ctx)
    return approval


def escalate_overdue(db: Session) -> int:
    """Background job: approvals nobody answered move to the security desk."""
    now = datetime.now(timezone.utc)
    overdue = db.query(Approval).filter(
        Approval.status == "pending",
        Approval.escalated_at.is_(None),
        Approval.due_at < now,
    ).all()
    for a in overdue:
        a.escalated_at = now
    db.commit()
    return len(overdue)
