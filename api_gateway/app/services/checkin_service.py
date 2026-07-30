"""All movement rules live here: entry, step-out, step-in, exit.

The key design rule: ONE visit from arrival to final departure.
Cafeteria / lunch / restroom trips are movements INSIDE that visit.
They never need re-approval and never re-notify the host.
"""
import json
from datetime import datetime, time, timedelta, timezone

from sqlalchemy.orm import Session

from app.clients.face_client import face_client
from app.models import (Device, Employee, Invite, InviteHost, Visit, VisitMovement,
                        Visitor, VisitorFaceData, VisitorType)
from app.services import blocklist_service, settings_service
from app.services.approval_service import create as create_approval
from app.services.audit_service import log_action
from app.services.notification_service import notify_employee


class CheckinError(Exception):
    pass


def _now():
    return datetime.now(timezone.utc)


# ---------------- identification ----------------
def identify(db: Session, *, image_b64: str | None = None, qr_token: str | None = None,
             access_code: str | None = None) -> dict:
    """One endpoint the kiosk calls for everything. On a Check-In/Out or
    Step-In/Out device, the device's own `direction` (not this function)
    decides what happens next - this just resolves WHO it is, by face, by
    scanning their pass QR, or by a typed access code."""
    from app.services.pass_service import find_pass_entity

    visitor = None
    score = None
    face_detected = False
    bbox = None
    inference_ms = None

    if qr_token:
        found = find_pass_entity(db, qr_token)
        if found:
            _, entity = found
            if entity.visitor_id:
                visitor = db.get(Visitor, entity.visitor_id)

    if not visitor and access_code:
        entity = (db.query(Invite).filter(Invite.access_code == access_code).first()
                 or db.query(Visit).filter(Visit.access_code == access_code).first())
        if entity and entity.visitor_id:
            visitor = db.get(Visitor, entity.visitor_id)

    if not visitor and image_b64:
        result = face_client.embed(image_b64)
        face_detected = bool(result.get("face_detected"))
        bbox = result.get("bbox")
        inference_ms = result.get("inference_ms")
        if not face_detected:
            return {"found": False, "face_detected": False, "suggested_action": "retry",
                    "bbox": bbox, "inference_ms": inference_ms,
                    "message": result.get("error") or "No face detected. Move a little closer."}

        threshold = settings_service.get_setting(db, "face.match_threshold") or 0.70
        rows = db.query(VisitorFaceData.visitor_id, VisitorFaceData.embedding).all()
        vid, score = face_client.match_against(result["embedding"],
                                               [(r[0], r[1]) for r in rows],
                                               threshold=float(threshold))
        if vid:
            visitor = db.get(Visitor, vid)

    if not visitor:
        return {"found": False, "face_detected": face_detected, "match_score": score,
                "bbox": bbox, "inference_ms": inference_ms,
                "suggested_action": "register",
                "message": "Let's get you registered."}

    if visitor.is_blocked or blocklist_service.check(
            db, full_name=visitor.full_name, email=visitor.email, phone=visitor.phone):
        # Neutral message on a public screen. Security is alerted separately.
        return {"found": True, "blocked": True, "visitor_id": visitor.id,
                "face_detected": face_detected, "match_score": score,
                "bbox": bbox, "inference_ms": inference_ms,
                "suggested_action": "see_reception",
                "message": "Please see reception."}

    open_visit = _open_visit(db, visitor.id)
    # An "approved" visit (walk-in authorized but not yet physically checked
    # in) is NOT the same as an "open" one - stepping in/out or checking out
    # only make sense once check_in() has actually opened it. Treating the
    # two the same here is what caused "No active visit found" at a
    # Step-In/Out door: identify() would say "heading out?" for someone who
    # had never checked in at all.
    truly_open = open_visit if (open_visit and open_visit.status == "open") else None
    last_visit = (db.query(Visit).filter(Visit.visitor_id == visitor.id)
                  .order_by(Visit.id.desc()).first())
    last_host = db.get(Employee, last_visit.host_id) if last_visit and last_visit.host_id else None

    if truly_open:
        # "arrived": checked in at reception but hasn't passed the internal
        # Step-In door yet - needs "step_in", same as someone back from a
        # cafeteria trip. Only genuinely "inside" suggests heading out.
        if truly_open.presence in ("stepped_out", "arrived"):
            action = "step_in"
            msg = (f"Welcome back, {visitor.full_name}!" if truly_open.presence == "stepped_out"
                   else f"Hi {visitor.full_name}, let's get you in!")
        else:
            action = "step_out_or_checkout"
            msg = f"Hi {visitor.full_name}, heading out?"
    else:
        action = "check_in"
        msg = (f"You're approved - let's get you checked in, {visitor.full_name}!" if open_visit
               else f"Welcome back, {visitor.full_name}!" if last_visit
               else f"Welcome, {visitor.full_name}!")

    return {
        "found": True, "face_detected": face_detected, "match_score": score,
        "bbox": bbox, "inference_ms": inference_ms,
        "visitor_id": visitor.id, "visitor_name": visitor.full_name,
        "is_returning": last_visit is not None,
        "open_visit_id": truly_open.id if truly_open else None,
        "presence": truly_open.presence if truly_open else None,
        "suggested_action": action,
        "last_visit_at": last_visit.first_entry_at if last_visit else None,
        "last_host_name": last_host.full_name if last_host else None,
        "blocked": False, "message": msg,
    }


def _open_visit(db: Session, visitor_id: int) -> Visit | None:
    return (db.query(Visit)
            .filter(Visit.visitor_id == visitor_id,
                   Visit.status.in_(["open", "pending_approval", "approved"]))
            .order_by(Visit.id.desc()).first())


# ---------------- movements ----------------
def check_in(db: Session, *, visitor: Visitor, visitor_type_id: int, host_id: int | None,
             invite: Invite | None = None, device: Device | None = None,
             method: str = "face", match_score: float | None = None,
             purpose: str | None = None, additional_visitors: int = 0,
             resume_visit: Visit | None = None) -> Visit:
    """resume_visit: a walk-in already authorized by a host (Visit.status ==
    "approved") but not yet physically checked in - flips that SAME row to
    open instead of creating a second Visit."""
    now = _now()

    if resume_visit:
        visit = resume_visit
        visit.status = "open"
        visit.presence = "arrived"
        visit.first_entry_at = now
        db.add(VisitMovement(visit_id=visit.id, type="entry", occurred_at=now,
                             device_id=device.id if device else None,
                             method=method, match_score=match_score))
    else:
        if _open_visit(db, visitor.id):
            raise CheckinError("This visitor is already checked in.")
        visit = Visit(
            visitor_id=visitor.id,
            invite_id=invite.id if invite else None,
            visitor_type_id=visitor_type_id,
            host_id=host_id,
            status="open",
            presence="arrived",
            purpose=purpose or (invite.purpose if invite else None),
            additional_visitors=additional_visitors or (invite.additional_visitors if invite else 0),
            visitor_message=invite.visitor_message if invite else None,
            first_entry_at=now,
            badge_number=f"V{now:%y%m%d}-{visitor.id:04d}",
        )
        db.add(visit)
        db.flush()
        db.add(VisitMovement(visit_id=visit.id, type="entry", occurred_at=now,
                             device_id=device.id if device else None,
                             method=method, match_score=match_score))
        if invite:
            invite.status = "used"
            invite.used_at = now

    visitor.last_seen_at = now
    db.commit()
    db.refresh(visit)

    host = db.get(Employee, visit.host_id) if visit.host_id else None
    facts = {"Visitor": visitor.full_name, "Badge": visit.badge_number}
    if visit.visitor_message:
        facts["Message"] = visit.visitor_message
    notify_employee(db, host, type="visitor_arrived",
                    title=f"{visitor.full_name} has arrived",
                    body=f"{visitor.full_name} has checked in and is waiting for you at reception.",
                    entity_type="visit", entity_id=visit.id, facts=facts)

    log_action(db, action="visit.entry", actor=device, actor_type="device",
               entity_type="visit", entity_id=visit.id, detail={"visitor": visitor.full_name})
    return visit


def step_out(db: Session, *, visitor: Visitor, device: Device | None = None,
             method: str = "face", match_score: float | None = None) -> Visit:
    """Cafeteria / lunch / restroom. The visit stays OPEN and the pass stays
    valid. No approval, and deliberately NO host notification - pinging a host
    for a bathroom break is how people learn to ignore notifications."""
    visit = _open_visit(db, visitor.id)
    if not visit or visit.status != "open":
        raise CheckinError("No active visit found for this visitor.")
    if visit.presence == "arrived":
        raise CheckinError("Please step in first before stepping out.")
    if visit.presence == "stepped_out":
        raise CheckinError("This visitor is already marked as stepped out.")

    now = _now()
    visit.presence = "stepped_out"
    db.add(VisitMovement(visit_id=visit.id, type="step_out", occurred_at=now,
                         device_id=device.id if device else None,
                         method=method, match_score=match_score))
    db.commit()
    db.refresh(visit)
    return visit


def step_in(db: Session, *, visitor: Visitor, device: Device | None = None,
            method: str = "face", match_score: float | None = None) -> dict:
    """Coming back from the cafeteria, OR the first pass through the internal
    Step-In door after check-in ("arrived" -> "inside" - the guard below only
    blocks when already "inside", so both starting states are allowed here
    without any extra branching)."""
    visit = _open_visit(db, visitor.id)
    if not visit or visit.status != "open":
        raise CheckinError("No active visit found. Please check in at reception.")
    if visit.presence == "inside":
        raise CheckinError("This visitor is already marked inside.")

    now = _now()
    visit.presence = "inside"
    db.add(VisitMovement(visit_id=visit.id, type="step_in", occurred_at=now,
                         device_id=device.id if device else None,
                         method=method, match_score=match_score))
    db.commit()

    # If they were gone a long time, flag it so the kiosk can ask
    # "still visiting <host>?" instead of silently assuming.
    last_out = (db.query(VisitMovement)
                .filter(VisitMovement.visit_id == visit.id, VisitMovement.type == "step_out")
                .order_by(VisitMovement.id.desc()).first())
    away_minutes = 0
    if last_out:
        away_minutes = int((now - last_out.occurred_at.replace(tzinfo=timezone.utc)).total_seconds() // 60)

    return {"visit_id": visit.id, "away_minutes": away_minutes,
            "confirm_still_visiting": away_minutes > 120,
            "message": f"Welcome back, {visitor.full_name}!"}


def check_out(db: Session, *, visitor: Visitor, device: Device | None = None,
              method: str = "face", match_score: float | None = None,
              actor: Employee | None = None) -> Visit:
    """Leaving for the day. This is a DIFFERENT action from step-out and
    closes the visit for good."""
    visit = _open_visit(db, visitor.id)
    if not visit or visit.status != "open":
        # Matches step_in/step_out's guard - an "approved but not yet
        # checked in" visit must never be closeable, or a visitor could
        # "check out" of a visit they never actually opened.
        raise CheckinError("No active visit found for this visitor.")

    now = _now()
    visit.status = "closed"
    visit.presence = "departed"
    visit.last_exit_at = now
    db.add(VisitMovement(visit_id=visit.id, type="exit", occurred_at=now,
                         device_id=device.id if device else None,
                         method=method, match_score=match_score,
                         recorded_by_id=actor.id if actor else None))
    visitor.last_seen_at = now
    db.commit()
    db.refresh(visit)

    host = db.get(Employee, visit.host_id) if visit.host_id else None
    minutes = _minutes_inside(visit)
    notify_employee(db, host, type="visitor_left",
                    title=f"{visitor.full_name} has checked out",
                    body=f"Thanks for hosting {visitor.full_name} - they spent {minutes} minutes on site.",
                    entity_type="visit", entity_id=visit.id)

    log_action(db, action="visit.exit", actor=actor or device,
               actor_type="employee" if actor else "device",
               entity_type="visit", entity_id=visit.id,
               detail={"visitor": visitor.full_name, "minutes_inside": minutes})
    return visit


def _minutes_inside(visit: Visit) -> int | None:
    if not visit.first_entry_at:
        return None
    end = visit.last_exit_at or _now()
    start = visit.first_entry_at.replace(tzinfo=timezone.utc)
    end = end.replace(tzinfo=timezone.utc) if end.tzinfo is None else end
    return int((end - start).total_seconds() // 60)


# ---------------- walk-in ----------------
def walk_in_submit(db: Session, data, device: Device | None = None) -> dict:
    """Unexpected visitor at the kiosk. Creates the visitor, opens a visit in
    'pending_approval', and asks the host to decide."""
    vtype = db.get(VisitorType, data.visitor_type_id)
    if not vtype:
        raise CheckinError("Unknown visitor type")
    host = db.get(Employee, data.host_id)
    if not host:
        raise CheckinError("Unknown host")

    from app.services.registration_service import get_or_create_visitor, register_face

    visitor = get_or_create_visitor(db, full_name=data.full_name, email=data.email,
                                    phone=data.phone, company=data.company)

    if data.consent_given:
        visitor.consent_given_at = _now()
        db.commit()
        if data.image_b64:
            try:
                register_face(db, visitor, data.image_b64)
            except Exception:
                pass  # face is a convenience here, never a blocker

    hit = blocklist_service.check(db, full_name=visitor.full_name,
                                  email=visitor.email, phone=visitor.phone)

    now = _now()
    visitor_message = getattr(data, "message", None)
    visit = Visit(visitor_id=visitor.id, visitor_type_id=vtype.id, host_id=host.id,
                  status="pending_approval", presence="waiting", purpose=data.purpose,
                  visitor_message=visitor_message,
                  badge_number=f"V{now:%y%m%d}-{visitor.id:04d}")
    db.add(visit)
    db.commit()
    db.refresh(visit)

    # Auto-approve types (e.g. VIP) skip the pending-approval wait entirely -
    # mirrors what registration_service.submit() already does for invites.
    if not hit and vtype.auto_approve_default:
        from app.services import pass_service
        from app.services.notification_service import notify_visitor_welcome

        visit.status = "approved"
        raw_token, code = pass_service.mint_credentials(visit)
        db.commit()
        notify_visitor_welcome(db, visitor=visitor, pass_token_raw=raw_token, access_code=code,
                               host_name=host.full_name,
                               company_name=settings_service.get_setting(db, "company.name"))
        log_action(db, action="visit.auto_approved", actor=device, actor_type="device",
                  entity_type="visit", entity_id=visit.id, detail={"visitor": visitor.full_name})
        return {"visit_id": visit.id, "visitor_id": visitor.id, "status": "approved",
                "message": f"You're all set, {visitor.full_name}. Check your phone for your entry pass."}

    approval = create_approval(
        db,
        approval_type="blocklist_match" if hit else "walk_in",
        visitor_name=visitor.full_name,
        assigned_to_id=host.id,
        visit_id=visit.id,
        visitor_id=visitor.id,
        visitor_type_id=vtype.id,
        match_detail=(f"Matched blocklist entry #{hit.id}: {hit.reason}") if hit else None,
        message=visitor_message,
    )

    return {"approval_id": approval.id, "visit_id": visit.id, "visitor_id": visitor.id,
            "status": "pending",
            "message": f"We've notified {host.full_name}. Please wait."}


# ---------------- background jobs ----------------
def auto_close_stale_visits(db: Session) -> int:
    """End of day safety net. Visits nobody scanned out of are closed and
    flagged honestly as auto_closed, rather than silently faking an exit time."""
    hours = settings_service.get_setting(db, "visit.presume_departed_after_hours") or 4
    cutoff = _now() - timedelta(hours=int(hours))
    stale = db.query(Visit).filter(Visit.status == "open").all()
    closed = 0
    for v in stale:
        last = (db.query(VisitMovement).filter(VisitMovement.visit_id == v.id)
                .order_by(VisitMovement.id.desc()).first())
        last_at = last.occurred_at.replace(tzinfo=timezone.utc) if last else None
        if last_at and last_at < cutoff:
            v.status = "auto_closed"
            v.presence = "departed"
            v.last_exit_at = last_at
            db.add(VisitMovement(visit_id=v.id, type="exit", occurred_at=last_at,
                                 method="manual", note="Auto-closed - not verified"))
            closed += 1
    db.commit()
    return closed
