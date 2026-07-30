"""Kiosk tablet endpoints. Device-token gated, NOT JWT.

A device token can only reach these routes - it can never touch an admin
endpoint, because those use a completely different dependency.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.deps import get_current_device
from app.core.security import generate_token, hash_token
from app.db.session import get_db
from app.models import (Approval, Device, Employee, Invite, InviteHost, Visit, Visitor, VisitorType)
from app.schemas.kiosk import (CheckInIn, DevicePairIn, DevicePairOut, HeartbeatIn,
                               IdentifyIn, IdentifyOut, MovementIn, WalkInSubmitIn,
                               WalkInStatusOut)
from app.schemas.common import Msg
from app.services import checkin_service, invite_service, otp_service, settings_service

router = APIRouter(prefix="/kiosk", tags=["Kiosk (device)"])


# ---------- pairing (no device token yet - pairing code is the credential) ----------
@router.post("/pair", response_model=DevicePairOut)
def pair(data: DevicePairIn, db: Session = Depends(get_db)):
    device = db.query(Device).filter(Device.pairing_code == data.pairing_code,
                                     Device.status == "unpaired").first()
    if not device:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid or already-used pairing code")

    raw = generate_token()
    device.token_hash = hash_token(raw)
    device.status = "active"
    device.pairing_code = None          # one-time use
    device.app_version = data.app_version
    device.last_seen_at = datetime.now(timezone.utc)
    db.commit()
    return DevicePairOut(device_id=device.id, device_name=device.name,
                         device_token=raw, mode=device.mode)


@router.post("/heartbeat", response_model=Msg)
def heartbeat(data: HeartbeatIn, db: Session = Depends(get_db),
              device: Device = Depends(get_current_device)):
    device.app_version = data.app_version or device.app_version
    db.commit()
    return Msg(message="ok")


@router.get("/config")
def kiosk_config(db: Session = Depends(get_db), device: Device = Depends(get_current_device)):
    """What the tablet needs to render itself."""
    types = db.query(VisitorType).filter(VisitorType.is_active.is_(True)).all()
    return {
        "device_name": device.name,
        "mode": device.mode,
        "direction": device.direction,
        "company_name": settings_service.get_setting(db, "company.name"),
        "consent_text": settings_service.get_setting(db, "privacy.consent_text"),
        "liveness_required": settings_service.get_setting(db, "face.liveness_required"),
        "visitor_types": [{"id": t.id, "name": t.name, "badge_color": t.badge_color,
                           "requires_face": t.requires_face} for t in types],
    }


@router.get("/hosts")
def searchable_hosts(q: str = "", db: Session = Depends(get_db),
                     device: Device = Depends(get_current_device)):
    """Employee picker on the walk-in form. Returns only what a kiosk needs -
    no emails, no phone numbers, no roles."""
    query = db.query(Employee).filter(Employee.is_active.is_(True))
    if q:
        query = query.filter(Employee.full_name.ilike(f"%{q}%"))
    rows = query.order_by(Employee.full_name).limit(25).all()
    return {"items": [{"id": e.id, "full_name": e.full_name,
                       "department": e.department} for e in rows]}


# ---------- the one identify endpoint ----------
@router.post("/identify", response_model=IdentifyOut)
def identify(data: IdentifyIn, db: Session = Depends(get_db),
             device: Device = Depends(get_current_device)):
    """Face, QR, or a typed access code in. The backend works out who this is;
    on Check-In/Out and Step-In/Out devices, the device's own `direction`
    (not the visitor) decides what happens next."""
    if not (data.image_b64 or data.qr_token or data.access_code):
        raise HTTPException(400, "Send image_b64, qr_token, or access_code")
    result = checkin_service.identify(db, image_b64=data.image_b64, qr_token=data.qr_token,
                                      access_code=data.access_code)
    return IdentifyOut(**result)


# ---------- movements ----------
@router.post("/checkin")
def check_in(data: CheckInIn, db: Session = Depends(get_db),
             device: Device = Depends(get_current_device)):
    invite = None
    visitor = None
    host_id = data.host_id
    vtype_id = None
    resume_visit = None

    if data.invite_token:
        invite = invite_service.find_by_token(db, data.invite_token)
        try:
            invite = invite_service.validate_for_registration(db, invite)
        except invite_service.InviteError as e:
            raise HTTPException(400, str(e))
        if invite.status not in ("approved", "submitted", "used"):
            raise HTTPException(400, "This invite is not approved yet.")
        visitor = db.get(Visitor, invite.visitor_id) if invite.visitor_id else None
        vtype_id = invite.visitor_type_id
        primary = db.query(InviteHost).filter(
            InviteHost.invite_id == invite.id, InviteHost.is_primary.is_(True)).first()
        host_id = host_id or (primary.employee_id if primary else None)
    elif data.visitor_id:
        visitor = db.get(Visitor, data.visitor_id)
        last = (db.query(Visit).filter(Visit.visitor_id == data.visitor_id)
                .order_by(Visit.id.desc()).first())
        vtype_id = last.visitor_type_id if last else None
        host_id = host_id or (last.host_id if last else None)
        # Walk-in already authorized (approved but not yet physically checked
        # in) - resume that same Visit row instead of creating a new one.
        if last and last.status == "approved":
            resume_visit = last

    if not visitor:
        raise HTTPException(400, "Visitor not found. Please register first.")
    if not vtype_id:
        default = db.query(VisitorType).filter(VisitorType.is_active.is_(True)).first()
        vtype_id = default.id if default else None

    try:
        visit = checkin_service.check_in(db, visitor=visitor, visitor_type_id=vtype_id,
                                         host_id=host_id, invite=invite, device=device,
                                         method=data.method, match_score=data.match_score,
                                         resume_visit=resume_visit)
    except checkin_service.CheckinError as e:
        raise HTTPException(400, str(e))

    host = db.get(Employee, visit.host_id) if visit.host_id else None
    return {"visit_id": visit.id, "badge_number": visit.badge_number,
            "visitor_name": visitor.full_name, "host_name": host.full_name if host else None,
            "message": f"Welcome, {visitor.full_name}. "
                       f"{host.full_name + ' has been notified.' if host else ''}"}


@router.post("/step-out")
def step_out(data: MovementIn, db: Session = Depends(get_db),
             device: Device = Depends(get_current_device)):
    """Cafeteria / lunch / restroom. Visit stays open, pass stays valid,
    host is deliberately NOT notified."""
    visitor = db.get(Visitor, data.visitor_id)
    if not visitor:
        raise HTTPException(404, "Visitor not found")
    try:
        visit = checkin_service.step_out(db, visitor=visitor, device=device,
                                         method=data.method, match_score=data.match_score)
    except checkin_service.CheckinError as e:
        raise HTTPException(400, str(e))
    return {"visit_id": visit.id, "presence": visit.presence,
            "message": f"See you soon, {visitor.full_name}."}


@router.post("/step-in")
def step_in(data: MovementIn, db: Session = Depends(get_db),
            device: Device = Depends(get_current_device)):
    visitor = db.get(Visitor, data.visitor_id)
    if not visitor:
        raise HTTPException(404, "Visitor not found")
    try:
        return checkin_service.step_in(db, visitor=visitor, device=device,
                                       method=data.method, match_score=data.match_score)
    except checkin_service.CheckinError as e:
        raise HTTPException(400, str(e))


@router.post("/checkout")
def check_out(data: MovementIn, db: Session = Depends(get_db),
              device: Device = Depends(get_current_device)):
    """Leaving for the day. Different action from step-out - closes the visit."""
    visitor = db.get(Visitor, data.visitor_id)
    if not visitor:
        raise HTTPException(404, "Visitor not found")
    try:
        visit = checkin_service.check_out(db, visitor=visitor, device=device,
                                          method=data.method, match_score=data.match_score)
    except checkin_service.CheckinError as e:
        raise HTTPException(400, str(e))
    mins = checkin_service._minutes_inside(visit)
    return {"visit_id": visit.id, "minutes_inside": mins,
            "message": f"Thank you for visiting, {visitor.full_name}."}


# ---------- walk-in ----------
@router.post("/walkin/otp/send")
def walkin_otp_send(payload: dict, db: Session = Depends(get_db),
                    device: Device = Depends(get_current_device)):
    phone = payload.get("phone")
    if not phone:
        raise HTTPException(400, "phone is required")
    try:
        return otp_service.send_otp(db, phone, purpose="walk_in")
    except otp_service.OtpError as e:
        raise HTTPException(429, str(e))


@router.post("/walkin/otp/verify")
def walkin_otp_verify(payload: dict, db: Session = Depends(get_db),
                      device: Device = Depends(get_current_device)):
    try:
        otp_service.verify_otp(db, payload.get("phone", ""), payload.get("code", ""),
                               purpose="walk_in")
    except otp_service.OtpError as e:
        raise HTTPException(400, str(e))
    return {"success": True, "message": "Phone verified"}


@router.post("/walkin/submit")
def walkin_submit(data: WalkInSubmitIn, db: Session = Depends(get_db),
                  device: Device = Depends(get_current_device)):
    try:
        return checkin_service.walk_in_submit(db, data, device)
    except checkin_service.CheckinError as e:
        raise HTTPException(400, str(e))


@router.get("/walkin/{approval_id}/status", response_model=WalkInStatusOut)
def walkin_status(approval_id: int, db: Session = Depends(get_db),
                  device: Device = Depends(get_current_device)):
    """The 'waiting for approval' screen polls this."""
    a = db.get(Approval, approval_id)
    if not a:
        raise HTTPException(404, "Not found")
    host = db.get(Employee, a.assigned_to_id) if a.assigned_to_id else None
    now = datetime.now(timezone.utc)
    waiting = int((now - a.created_at.replace(tzinfo=timezone.utc)).total_seconds())
    remaining = 0
    if a.due_at:
        remaining = max(0, int((a.due_at.replace(tzinfo=timezone.utc) - now).total_seconds()))

    if a.status == "approved":
        msg = "You're approved! Check the SMS/email we just sent, then scan in at a Check-In kiosk."
    elif a.status == "denied":
        msg = "Please speak to reception."       # never show the reason publicly
    elif remaining == 0:
        msg = "Please speak to reception."
    else:
        msg = f"We've notified {host.full_name if host else 'your host'}. Please wait."

    return WalkInStatusOut(approval_id=a.id, status=a.status, visitor_name=a.visitor_name,
                           host_name=host.full_name if host else None,
                           seconds_waiting=waiting, seconds_remaining=remaining, message=msg)


# ---------- QR walk-in: visitor registers on their OWN phone ----------
@router.post("/walkin/session")
def create_walkin_session(db: Session = Depends(get_db),
                          device: Device = Depends(get_current_device)):
    """The kiosk calls this, then shows the returned QR on its idle screen.
    The visitor scans it and finishes registration on their own phone."""
    from app.services import walkin_service
    from app.services.qr_service import qr_data_url

    session, raw = walkin_service.create_session(db, device)
    url = walkin_service.walkin_url(raw)
    return {
        "session_id": session.id,
        "session_token": raw,
        "url": url,
        "qr_data_url": qr_data_url(url),
        "expires_at": session.expires_at,
    }


@router.get("/walkin/session/{session_id}")
def poll_walkin_session(session_id: int, db: Session = Depends(get_db),
                        device: Device = Depends(get_current_device)):
    """The kiosk polls this so it can show live progress while the visitor
    fills the form on their phone."""
    from app.models import WalkInSession
    from app.services import walkin_service

    session = db.get(WalkInSession, session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    return walkin_service.public_status(db, session)
