"""Visitor self-registration: the flow behind the emailed link.

Order: open link -> confirm details -> OTP -> consent -> face -> submit.
"""
import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.clients.face_client import face_client
from app.models import (Employee, Invite, InviteHost, Visitor, VisitorFaceData, VisitorType)
from app.services import blocklist_service, settings_service
from app.services.approval_service import create as create_approval
from app.services.audit_service import log_action


class RegistrationError(Exception):
    pass


def get_or_create_visitor(db: Session, *, full_name: str, email: str | None,
                          phone: str | None, company: str | None = None) -> Visitor:
    """Match an existing visitor by email or phone so returning people keep
    their history and their registered face."""
    visitor = None
    conds = []
    if email:
        conds.append(Visitor.email == email)
    if phone:
        conds.append(Visitor.phone == phone)
    if conds:
        visitor = db.query(Visitor).filter(or_(*conds)).first()

    if visitor:
        visitor.full_name = full_name or visitor.full_name
        visitor.email = email or visitor.email
        visitor.phone = phone or visitor.phone
        visitor.company = company or visitor.company
    else:
        visitor = Visitor(full_name=full_name, email=email, phone=phone, company=company,
                          first_seen_at=datetime.now(timezone.utc))
        db.add(visitor)
    db.commit()
    db.refresh(visitor)
    return visitor


def record_consent(db: Session, visitor: Visitor, accepted: bool):
    visitor.consent_given_at = datetime.now(timezone.utc) if accepted else None
    db.commit()


def register_face(db: Session, visitor: Visitor, image_b64: str) -> dict:
    """Consent must already be recorded before this is ever called."""
    if not visitor.consent_given_at:
        raise RegistrationError("Consent is required before capturing a photo.")

    result = face_client.embed(image_b64)
    if not result.get("face_detected"):
        if result.get("error") == "face_service_unavailable":
            raise RegistrationError("Face service is not running.")
        return {"success": False, "message": "No face detected. Move closer and face the camera."}

    retention_days = settings_service.get_setting(db, "privacy.face_retention_days") or 30
    expires = datetime.now(timezone.utc) + timedelta(days=int(retention_days))

    db.query(VisitorFaceData).filter(VisitorFaceData.visitor_id == visitor.id).delete()
    db.add(VisitorFaceData(
        visitor_id=visitor.id,
        embedding=json.dumps(result["embedding"]),
        expires_at=expires,
    ))
    visitor.face_registered_at = datetime.now(timezone.utc)
    visitor.retention_delete_at = expires
    db.commit()
    return {"success": True, "message": "Face registered", "bbox": result.get("bbox")}


def submit(db: Session, invite: Invite, visitor: Visitor, ctx: dict | None = None) -> dict:
    """Final step. Creates an approval unless the invite is auto-approved."""
    now = datetime.now(timezone.utc)

    hit = blocklist_service.check(db, full_name=visitor.full_name,
                                  email=visitor.email, phone=visitor.phone)

    invite.visitor_id = visitor.id
    invite.submitted_at = now
    invite.status = "submitted"

    primary = db.query(InviteHost).filter(
        InviteHost.invite_id == invite.id, InviteHost.is_primary.is_(True)).first()
    host_id = primary.employee_id if primary else None

    if hit:
        # Never tell the visitor. Raise it quietly for security instead.
        visitor.is_blocked = True
        db.commit()
        create_approval(db, approval_type="blocklist_match", visitor_name=visitor.full_name,
                        assigned_to_id=host_id, invite_id=invite.id, visitor_id=visitor.id,
                        visitor_type_id=invite.visitor_type_id,
                        match_detail=f"Matched blocklist entry #{hit.id}: {hit.reason}")
        log_action(db, action="blocklist.hit", actor=None, actor_type="visitor",
                   entity_type="invite", entity_id=invite.id,
                   detail={"visitor": visitor.full_name}, ctx=ctx)
        return {"status": "pending", "message": "Please see reception to complete your check-in."}

    if invite.auto_approve:
        from app.services import pass_service
        from app.services.notification_service import notify_visitor_welcome

        invite.status = "approved"
        raw_token, code = pass_service.mint_credentials(invite)
        db.commit()
        host = db.get(Employee, host_id) if host_id else None
        notify_visitor_welcome(db, visitor=visitor, pass_token_raw=raw_token, access_code=code,
                               host_name=host.full_name if host else None,
                               company_name=settings_service.get_setting(db, "company.name"))
        return {"status": "approved", "message": "You're all set. Check your phone for your entry pass."}

    db.commit()
    create_approval(db, approval_type="invite", visitor_name=visitor.full_name,
                    assigned_to_id=host_id, invite_id=invite.id, visitor_id=visitor.id,
                    visitor_type_id=invite.visitor_type_id, message=invite.visitor_message)
    return {"status": "pending_approval", "message": "Registration received. Your host will confirm shortly."}


def steps_done(db: Session, invite: Invite) -> dict:
    visitor = db.get(Visitor, invite.visitor_id) if invite.visitor_id else None
    return {
        "opened": invite.opened_at is not None,
        "otp_verified": bool(visitor and visitor.phone),
        "consent": bool(visitor and visitor.consent_given_at),
        "face_registered": bool(visitor and visitor.face_registered_at),
        "submitted": invite.submitted_at is not None,
    }
