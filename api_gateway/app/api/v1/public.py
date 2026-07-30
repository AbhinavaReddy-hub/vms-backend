"""Visitor-facing endpoints. NO login - the invite token IS the credential.

These routes are the most exposed surface in the system, so:
  - every route validates the token first
  - rate limited
  - private_notes are never returned here
  - a visitor token can never reach an admin route (different dependency)
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.security import rate_limit
from app.core.tokens import pass_link
from app.db.session import get_db
from app.models import Employee, InviteHost, Visit, Visitor, VisitorType
from app.schemas.common import Msg
from app.schemas.public import (ConsentIn, InviteDetailsIn, InvitePublicOut, OtpSendIn,
                                OtpVerifyIn, PassOut, SubmitRegistrationIn)
from app.services import (invite_service, otp_service, pass_service, registration_service,
                          settings_service)
from app.services.qr_service import qr_data_url

router = APIRouter(prefix="/public", tags=["Public (visitor)"])


def _load(db: Session, token: str):
    inv = invite_service.find_by_token(db, token)
    try:
        return invite_service.validate_for_registration(db, inv)
    except invite_service.InviteError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))


def _guard(request: Request, token: str, calls: int = 30, per: int = 60):
    ip = request.client.host if request.client else "unknown"
    if not rate_limit(f"public:{ip}:{token[:8]}", calls, per):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many requests. Please slow down.")


@router.get("/invite/{token}", response_model=InvitePublicOut)
def open_invite(token: str, request: Request, db: Session = Depends(get_db)):
    _guard(request, token)
    inv = _load(db, token)

    if not inv.opened_at:
        inv.opened_at = datetime.now(timezone.utc)
        if inv.status in ("not_sent", "sent"):
            inv.status = "opened"
        db.commit()

    vt = db.get(VisitorType, inv.visitor_type_id)
    primary = db.query(InviteHost).filter(
        InviteHost.invite_id == inv.id, InviteHost.is_primary.is_(True)).first()
    host = db.get(Employee, primary.employee_id) if primary else None

    return InvitePublicOut(
        full_name=inv.full_name,
        company_name=settings_service.get_setting(db, "company.name"),
        visitor_type=vt.name if vt else "Visitor",
        arrival_at=inv.arrival_at, valid_until=inv.valid_until,
        host_name=host.full_name if host else None,
        purpose=inv.purpose,
        public_notes=inv.public_notes,        # visitor CAN see this
        custom_message=inv.custom_message,
        requires_face=vt.requires_face if vt else True,
        requires_legal_docs=vt.requires_legal_docs if vt else False,
        status=inv.status,
        steps_done=registration_service.steps_done(db, inv),
    )


@router.get("/consent-text")
def consent_text(db: Session = Depends(get_db)):
    return {"text": settings_service.get_setting(db, "privacy.consent_text"),
            "retention_days": settings_service.get_setting(db, "privacy.face_retention_days")}


@router.post("/invite/{token}/otp/send")
def send_otp(token: str, data: OtpSendIn, request: Request, db: Session = Depends(get_db)):
    _guard(request, token, calls=6, per=600)
    inv = _load(db, token)
    try:
        return otp_service.send_otp(db, data.phone, purpose="visitor_registration", ref=str(inv.id))
    except otp_service.OtpError as e:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, str(e))


@router.post("/invite/{token}/otp/verify")
def verify_otp(token: str, data: OtpVerifyIn, request: Request, db: Session = Depends(get_db)):
    _guard(request, token, calls=10, per=600)
    inv = _load(db, token)
    try:
        otp_service.verify_otp(db, data.phone, data.code, purpose="visitor_registration")
    except otp_service.OtpError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))

    visitor = registration_service.get_or_create_visitor(
        db, full_name=inv.full_name, email=inv.email, phone=data.phone, company=inv.company)
    inv.visitor_id = visitor.id
    inv.phone = data.phone
    db.commit()
    return {"success": True, "visitor_id": visitor.id, "message": "Phone verified"}


@router.post("/invite/{token}/details")
def submit_details(token: str, data: InviteDetailsIn, request: Request,
                   db: Session = Depends(get_db)):
    """Replaces phone-OTP send+verify as the trigger for creating the visitor
    record - no phone-ownership check, just the submitted details."""
    _guard(request, token)
    inv = _load(db, token)
    visitor = registration_service.get_or_create_visitor(
        db, full_name=inv.full_name, email=data.email or inv.email, phone=data.phone,
        company=data.company or inv.company)
    inv.visitor_id = visitor.id
    inv.phone = data.phone
    inv.visitor_message = data.message
    db.commit()
    return {"success": True, "visitor_id": visitor.id, "message": "Details saved"}


@router.post("/invite/{token}/consent", response_model=Msg)
def consent(token: str, data: ConsentIn, db: Session = Depends(get_db)):
    inv = _load(db, token)
    if not inv.visitor_id:
        raise HTTPException(400, "Verify your phone number first.")
    visitor = db.get(Visitor, inv.visitor_id)
    registration_service.record_consent(db, visitor, data.accepted)
    return Msg(message="Consent recorded" if data.accepted
               else "Noted - you can verify with OTP at the door instead")


@router.post("/invite/{token}/face")
def register_face(token: str, payload: dict, request: Request, db: Session = Depends(get_db)):
    """Body: {"image_b64": "..."} - accepts a raw base64 string or a data URL."""
    _guard(request, token, calls=20, per=300)
    inv = _load(db, token)
    if not inv.visitor_id:
        raise HTTPException(400, "Verify your phone number first.")
    image = payload.get("image_b64")
    if not image:
        raise HTTPException(400, "image_b64 is required")

    visitor = db.get(Visitor, inv.visitor_id)
    try:
        return registration_service.register_face(db, visitor, image)
    except registration_service.RegistrationError as e:
        raise HTTPException(400, str(e))


@router.post("/invite/{token}/submit")
def submit(token: str, data: SubmitRegistrationIn, request: Request,
           db: Session = Depends(get_db)):
    _guard(request, token)
    inv = _load(db, token)
    if inv.submitted_at:
        raise HTTPException(400, "This registration was already submitted. Scan your face at the door.")
    if not inv.visitor_id:
        raise HTTPException(400, "Verify your phone number first.")

    visitor = db.get(Visitor, inv.visitor_id)
    if data.email:
        visitor.email = data.email
    if data.company:
        visitor.company = data.company
    if data.purpose:
        inv.purpose = data.purpose
    inv.additional_visitors = data.additional_visitors
    db.commit()

    result = registration_service.submit(db, inv, visitor)
    result["pass_url"] = pass_link(token)
    return result


@router.get("/pass/{token}", response_model=PassOut)
def get_pass(token: str, db: Session = Depends(get_db)):
    """Serves three different token flavors behind one link: an invite's
    original registration token (pre-approval "submitted" screen), an
    invite's pass_token_hash (post-approval), or a walk-in Visit's
    pass_token_hash (no Invite row at all) - see pass_service.find_pass_entity."""
    found = pass_service.find_pass_entity(db, token)
    if not found:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This link is not valid.")
    kind, entity = found

    if kind == "invite":
        inv = entity
        vt = db.get(VisitorType, inv.visitor_type_id)
        primary = db.query(InviteHost).filter(
            InviteHost.invite_id == inv.id, InviteHost.is_primary.is_(True)).first()
        host = db.get(Employee, primary.employee_id) if primary else None
        presence = None
        if inv.visitor_id:
            v = db.query(Visit).filter(Visit.visitor_id == inv.visitor_id,
                                       Visit.status.in_(["open", "approved"])).first()
            presence = v.presence if v else None
        return PassOut(
            visitor_name=inv.full_name,
            company_name=settings_service.get_setting(db, "company.name"),
            visitor_type=vt.name if vt else "Visitor",
            badge_color=vt.badge_color if vt else "#2563EB",
            host_name=host.full_name if host else None,
            valid_until=inv.valid_until, status=inv.status, presence=presence,
            qr_payload=token, access_code=inv.access_code,
        )

    visit = entity
    visitor = db.get(Visitor, visit.visitor_id)
    vt = db.get(VisitorType, visit.visitor_type_id)
    host = db.get(Employee, visit.host_id) if visit.host_id else None
    hours = vt.default_validity_hours if vt else 24
    valid_until = visit.created_at.replace(tzinfo=timezone.utc) + timedelta(hours=hours)
    return PassOut(
        visitor_name=visitor.full_name if visitor else "Visitor",
        company_name=settings_service.get_setting(db, "company.name"),
        visitor_type=vt.name if vt else "Visitor",
        badge_color=vt.badge_color if vt else "#2563EB",
        host_name=host.full_name if host else None,
        valid_until=valid_until, status=visit.status, presence=visit.presence,
        qr_payload=token, access_code=visit.access_code,
    )


@router.get("/pass/{token}/qr")
def get_pass_qr(token: str, db: Session = Depends(get_db)):
    if not pass_service.find_pass_entity(db, token):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This link is not valid.")
    return {"qr_data_url": qr_data_url(pass_link(token))}


# ---------------------------------------------------------------------------
# Walk-in registration on the visitor's OWN phone, started by scanning the
# QR on the kiosk screen. No login, no invite - the session token is the
# credential, and it dies after 15 minutes.
# ---------------------------------------------------------------------------
from app.schemas.public import WalkInSubmitIn  # noqa: E402
from app.services import walkin_service  # noqa: E402


def _walkin(db: Session, token: str):
    try:
        return walkin_service.find(db, token)
    except walkin_service.WalkInError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))


@router.get("/walkin/{token}")
def open_walkin(token: str, request: Request, db: Session = Depends(get_db)):
    """What the visitor sees the moment they scan the QR."""
    _guard(request, token)
    session = _walkin(db, token)
    if session.status == "waiting":
        walkin_service.mark(db, session, "scanned")

    types = db.query(VisitorType).filter(VisitorType.is_active.is_(True)).all()
    return {
        "company_name": settings_service.get_setting(db, "company.name"),
        "status": session.status,
        "expires_at": session.expires_at,
        "consent_text": settings_service.get_setting(db, "privacy.consent_text"),
        "visitor_types": [
            {"id": t.id, "name": t.name, "badge_color": t.badge_color,
             "requires_face": t.requires_face}
            for t in types
        ],
        "steps": ["Your details", "Verify phone", "Photo", "Done"],
    }


@router.get("/walkin/{token}/hosts")
def walkin_hosts(token: str, q: str = "", db: Session = Depends(get_db)):
    """Employee picker on the visitor's phone. Returns only a name and
    department - never emails, phone numbers or roles."""
    _walkin(db, token)
    query = db.query(Employee).filter(Employee.is_active.is_(True))
    if q:
        query = query.filter(Employee.full_name.ilike(f"%{q}%"))
    rows = query.order_by(Employee.full_name).limit(25).all()
    return {"items": [{"id": e.id, "full_name": e.full_name,
                       "department": e.department} for e in rows]}


@router.post("/walkin/{token}/otp/send")
def walkin_otp_send(token: str, data: OtpSendIn, request: Request,
                    db: Session = Depends(get_db)):
    _guard(request, token, calls=6, per=600)
    session = _walkin(db, token)
    walkin_service.mark(db, session, "registering", phone=data.phone)
    try:
        return otp_service.send_otp(db, data.phone, purpose="walk_in", ref=str(session.id))
    except otp_service.OtpError as e:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, str(e))


@router.post("/walkin/{token}/otp/verify")
def walkin_otp_verify(token: str, data: OtpVerifyIn, request: Request,
                      db: Session = Depends(get_db)):
    _guard(request, token, calls=10, per=600)
    _walkin(db, token)
    try:
        otp_service.verify_otp(db, data.phone, data.code, purpose="walk_in")
    except otp_service.OtpError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    return {"success": True, "message": "Phone verified"}


@router.post("/walkin/{token}/face")
def walkin_face(token: str, payload: dict, request: Request,
                db: Session = Depends(get_db)):
    """Optional. Registering a face here is what makes the cafeteria
    step-out and step-in work later without any typing."""
    _guard(request, token, calls=20, per=300)
    session = _walkin(db, token)
    if not session.visitor_id:
        raise HTTPException(400, "Submit your details first.")
    image = payload.get("image_b64")
    if not image:
        raise HTTPException(400, "image_b64 is required")
    visitor = db.get(Visitor, session.visitor_id)
    try:
        return registration_service.register_face(db, visitor, image)
    except registration_service.RegistrationError as e:
        raise HTTPException(400, str(e))


@router.post("/walkin/{token}/submit")
def walkin_submit(token: str, data: WalkInSubmitIn, request: Request,
                  db: Session = Depends(get_db)):
    """Creates the visitor, opens a visit waiting on approval, and notifies
    the host. The kiosk sees this through its poll a second later."""
    _guard(request, token)
    session = _walkin(db, token)
    if session.status in ("submitted", "approved", "denied"):
        raise HTTPException(400, "This registration was already submitted.")

    from app.services import checkin_service

    class _Payload:
        full_name = data.full_name
        phone = data.phone
        email = data.email
        company = data.company
        purpose = data.purpose
        host_id = data.host_id
        visitor_type_id = data.visitor_type_id
        consent_given = data.consent_given
        image_b64 = None
        message = data.message

    try:
        result = checkin_service.walk_in_submit(db, _Payload())
    except checkin_service.CheckinError as e:
        raise HTTPException(400, str(e))

    # Auto-approve types skip the pending Approval entirely - reflect that
    # straight in the session status, since public_status()'s poll only
    # flips waiting->approved by watching an Approval row, and there isn't one.
    session_status = "approved" if result.get("status") == "approved" else "submitted"
    walkin_service.mark(
        db, session, session_status,
        visitor_id=result["visitor_id"], visit_id=result["visit_id"],
        approval_id=result.get("approval_id"), visitor_name=data.full_name,
    )
    return {**result, "session_status": session_status}


@router.get("/walkin/{token}/status")
def walkin_status(token: str, db: Session = Depends(get_db)):
    """The visitor's phone polls this to see the host's decision."""
    session = _walkin(db, token)
    return walkin_service.public_status(db, session)


@router.get("/visitor-types")
def public_visitor_types(db: Session = Depends(get_db)):
    """Types for the walk-in form. Only what a form needs - no internal flags."""
    rows = db.query(VisitorType).filter(VisitorType.is_active.is_(True)).all()
    return {"items": [{"id": t.id, "name": t.name, "badge_color": t.badge_color,
                       "requires_face": t.requires_face} for t in rows]}


@router.get("/company")
def public_company(db: Session = Depends(get_db)):
    """Branding + consent text for the visitor website."""
    return {
        "company_name": settings_service.get_setting(db, "company.name"),
        "consent_text": settings_service.get_setting(db, "privacy.consent_text"),
        "retention_days": settings_service.get_setting(db, "privacy.face_retention_days"),
    }
