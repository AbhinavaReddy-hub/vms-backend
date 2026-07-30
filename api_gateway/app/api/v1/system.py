"""Devices, settings, visitor types, analytics, audit log, notifications."""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.deps import get_current_employee, get_request_context
from app.core.pagination import PageParams
from app.core.permissions import require_permission
from app.core.security import generate_numeric_code
from app.db.session import get_db
from app.models import (AuditLog, Device, Notification, VisitorType)
from app.schemas.common import Msg
from app.schemas.visitor import DeviceIn, DeviceOut, VisitorTypeIn, VisitorTypeOut
from app.services import analytics_service, settings_service
from app.services.audit_service import log_action

router = APIRouter(tags=["System"])


# ---------------- devices ----------------
@router.get("/devices")
def list_devices(db: Session = Depends(get_db),
                 user=Depends(require_permission("devices.view"))):
    now = datetime.now(timezone.utc)
    rows = db.query(Device).order_by(Device.id).all()
    names_by_id = {d.id: d.name for d in rows}
    out = []
    for d in rows:
        online = bool(d.last_seen_at and
                      (now - d.last_seen_at.replace(tzinfo=timezone.utc)) < timedelta(minutes=5))
        out.append(DeviceOut(id=d.id, name=d.name, location_label=d.location_label,
                             mode=d.mode, direction=d.direction,
                             paired_device_id=d.paired_device_id,
                             paired_device_name=names_by_id.get(d.paired_device_id),
                             status=d.status, app_version=d.app_version,
                             last_seen_at=d.last_seen_at, online=online,
                             pairing_code=d.pairing_code))
    needs_attention = sum(1 for d in out if not d.online and d.status == "active")
    return {"items": out, "total": len(out), "needs_attention": needs_attention}


@router.post("/devices", status_code=201)
def create_device(data: DeviceIn, db: Session = Depends(get_db),
                  user=Depends(require_permission("devices.edit")),
                  ctx: dict = Depends(get_request_context)):
    """Registration Kiosk -> one device, one pairing code. Check-In/Out and
    Step-In/Out -> a linked ENTRY + EXIT pair, each its own device and its
    own code, since each is a separate physical tablet doing one fixed job."""
    if data.mode == "registration_kiosk":
        code = generate_numeric_code(6)
        device = Device(name=data.name, location_label=data.location_label,
                        mode=data.mode, pairing_code=code, status="unpaired")
        db.add(device)
        db.commit()
        db.refresh(device)
        log_action(db, action="device.created", actor=user, entity_type="device",
                   entity_id=device.id, detail={"name": device.name}, ctx=ctx)
        return {"id": device.id, "name": device.name, "pairing_code": code,
                "message": "Enter this code on the tablet to pair it."}

    entry_code = generate_numeric_code(6)
    exit_code = generate_numeric_code(6)
    entry = Device(name=f"{data.name} - Entry", location_label=data.location_label,
                   mode=data.mode, direction="entry", pairing_code=entry_code, status="unpaired")
    exit_ = Device(name=f"{data.name} - Exit", location_label=data.location_label,
                   mode=data.mode, direction="exit", pairing_code=exit_code, status="unpaired")
    db.add(entry)
    db.add(exit_)
    db.flush()
    entry.paired_device_id = exit_.id
    exit_.paired_device_id = entry.id
    db.commit()
    db.refresh(entry)
    db.refresh(exit_)
    log_action(db, action="device.created", actor=user, entity_type="device",
               entity_id=entry.id, detail={"name": data.name, "paired_with": exit_.id}, ctx=ctx)
    return {
        "entry_device_id": entry.id, "exit_device_id": exit_.id, "name": data.name,
        "entry_pairing_code": entry_code, "exit_pairing_code": exit_code,
        "message": "Enter the Entry code on the entry tablet, and the Exit code on the exit tablet.",
    }


@router.patch("/devices/{device_id}")
def update_device(device_id: int, payload: dict, db: Session = Depends(get_db),
                  user=Depends(require_permission("devices.edit")),
                  ctx: dict = Depends(get_request_context)):
    d = db.get(Device, device_id)
    if not d:
        raise HTTPException(404, "Device not found")
    for k in ("name", "location_label", "mode"):
        if k in payload:
            setattr(d, k, payload[k])
    db.commit()
    log_action(db, action="device.updated", actor=user, entity_type="device",
               entity_id=device_id, detail=payload, ctx=ctx)
    return {"success": True}


@router.delete("/devices/{device_id}", response_model=Msg)
def revoke_device(device_id: int, db: Session = Depends(get_db),
                  user=Depends(require_permission("devices.edit")),
                  ctx: dict = Depends(get_request_context)):
    """Instantly kills a lost or stolen tablet's access. Keeps the row (and
    its history) around - use the permanent-delete endpoint to remove it
    from the list entirely."""
    d = db.get(Device, device_id)
    if not d:
        raise HTTPException(404, "Device not found")
    d.token_hash = None
    d.status = "revoked"
    db.commit()
    log_action(db, action="device.revoked", actor=user, entity_type="device",
               entity_id=device_id, ctx=ctx)
    return Msg(message="Device revoked. It can no longer call the API.")


@router.delete("/devices/{device_id}/permanent", response_model=Msg)
def delete_device_permanent(device_id: int, db: Session = Depends(get_db),
                            user=Depends(require_permission("devices.edit")),
                            ctx: dict = Depends(get_request_context)):
    """Removes the device from the list entirely. If it was half of an
    entry/exit pair, un-links the other half rather than leaving it pointed
    at a row that no longer exists."""
    d = db.get(Device, device_id)
    if not d:
        raise HTTPException(404, "Device not found")
    name = d.name
    db.query(Device).filter(Device.paired_device_id == device_id).update({"paired_device_id": None})
    db.delete(d)
    db.commit()
    log_action(db, action="device.deleted", actor=user, entity_type="device",
               entity_id=device_id, detail={"name": name}, ctx=ctx)
    return Msg(message=f"{name} deleted.")


# ---------------- visitor types ----------------
@router.get("/visitor-types")
def list_types(db: Session = Depends(get_db), user=Depends(get_current_employee)):
    rows = db.query(VisitorType).filter(VisitorType.is_active.is_(True)).all()
    return {"items": [VisitorTypeOut.model_validate(r) for r in rows], "total": len(rows)}


@router.post("/visitor-types", status_code=201)
def create_type(data: VisitorTypeIn, db: Session = Depends(get_db),
                user=Depends(require_permission("settings.edit")),
                ctx: dict = Depends(get_request_context)):
    vt = VisitorType(**data.model_dump())
    db.add(vt)
    db.commit()
    db.refresh(vt)
    log_action(db, action="visitor_type.created", actor=user, entity_type="visitor_type",
               entity_id=vt.id, ctx=ctx)
    return VisitorTypeOut.model_validate(vt)


@router.patch("/visitor-types/{type_id}")
def update_type(type_id: int, payload: dict, db: Session = Depends(get_db),
                user=Depends(require_permission("settings.edit")),
                ctx: dict = Depends(get_request_context)):
    vt = db.get(VisitorType, type_id)
    if not vt:
        raise HTTPException(404, "Visitor type not found")
    for k, v in payload.items():
        if hasattr(vt, k):
            setattr(vt, k, v)
    db.commit()
    log_action(db, action="visitor_type.updated", actor=user, entity_type="visitor_type",
               entity_id=type_id, detail=payload, ctx=ctx)
    return {"success": True}


# ---------------- settings ----------------
@router.get("/settings")
def get_settings(db: Session = Depends(get_db),
                 user=Depends(require_permission("settings.view"))):
    return settings_service.all_settings(db)


@router.patch("/settings")
def update_settings(payload: dict, db: Session = Depends(get_db),
                    user=Depends(require_permission("settings.edit")),
                    ctx: dict = Depends(get_request_context)):
    """Includes the face match threshold - the one number worth tuning."""
    updated = {}
    for key, value in payload.items():
        if key not in settings_service.DEFAULTS:
            raise HTTPException(400, f"Unknown setting: {key}")
        settings_service.set_setting(db, key, value, user.id)
        updated[key] = value
    log_action(db, action="settings.updated", actor=user, detail=updated, ctx=ctx)
    return {"updated": updated}


# ---------------- analytics ----------------
@router.get("/analytics/overview")
def analytics_overview(days: int = 30, db: Session = Depends(get_db),
                       user=Depends(require_permission("analytics.view"))):
    return {
        "range_days": days,
        "visits_over_time": analytics_service.visits_over_time(db, days),
        "peak_hours": analytics_service.peak_hours(db, days),
        "visitor_types": analytics_service.visitor_type_breakdown(db, days),
        "top_hosts": analytics_service.top_hosts(db, days),
        "average_time_inside": analytics_service.average_time_inside(db, days),
        "invite_funnel": analytics_service.invite_funnel(db, days),
        "face_performance": analytics_service.face_performance(db, days),
    }


@router.get("/analytics/face-performance")
def face_perf(days: int = 30, db: Session = Depends(get_db),
              user=Depends(require_permission("analytics.view"))):
    """Monitoring our own model: match rate, average score, fallback usage."""
    return analytics_service.face_performance(db, days)


# ---------------- audit log ----------------
@router.get("/audit-log")
def audit_log(page: PageParams = Depends(), action: str | None = None,
              actor_id: int | None = None, db: Session = Depends(get_db),
              user=Depends(require_permission("audit.view"))):
    """Append-only. There is deliberately no PATCH or DELETE here."""
    q = db.query(AuditLog)
    if action:
        q = q.filter(AuditLog.action == action)
    if actor_id:
        q = q.filter(AuditLog.actor_id == actor_id)
    if page.q:
        q = q.filter(AuditLog.action.ilike(f"%{page.q}%"))
    total = q.count()
    rows = q.order_by(AuditLog.id.desc()).offset(page.offset).limit(page.page_size).all()
    return {"items": [{
        "id": r.id, "action": r.action, "actor_id": r.actor_id,
        "actor_name": r.actor_name, "actor_type": r.actor_type,
        "entity_type": r.entity_type, "entity_id": r.entity_id,
        "detail": r.detail, "ip": r.ip, "created_at": r.created_at,
    } for r in rows], "total": total, "page": page.page, "page_size": page.page_size}


# ---------------- notifications ----------------
@router.get("/notifications")
def list_notifications(unread_only: bool = False, db: Session = Depends(get_db),
                       user=Depends(get_current_employee)):
    q = db.query(Notification).filter(Notification.employee_id == user.id)
    if unread_only:
        q = q.filter(Notification.read_at.is_(None))
    rows = q.order_by(Notification.id.desc()).limit(50).all()
    unread = db.query(Notification).filter(Notification.employee_id == user.id,
                                           Notification.read_at.is_(None)).count()
    return {"items": [{
        "id": n.id, "type": n.type, "title": n.title, "body": n.body,
        "severity": n.severity, "entity_type": n.entity_type, "entity_id": n.entity_id,
        "read": n.read_at is not None, "created_at": n.created_at,
    } for n in rows], "unread_count": unread}


@router.post("/notifications/{notification_id}/read", response_model=Msg)
def mark_read(notification_id: int, db: Session = Depends(get_db),
              user=Depends(get_current_employee)):
    n = db.get(Notification, notification_id)
    if not n or n.employee_id != user.id:
        raise HTTPException(404, "Notification not found")
    n.read_at = datetime.now(timezone.utc)
    db.commit()
    return Msg(message="Marked as read")


@router.post("/notifications/read-all", response_model=Msg)
def mark_all_read(db: Session = Depends(get_db), user=Depends(get_current_employee)):
    now = datetime.now(timezone.utc)
    n = db.query(Notification).filter(Notification.employee_id == user.id,
                                      Notification.read_at.is_(None)).update({"read_at": now})
    db.commit()
    return Msg(message=f"{n} notification(s) marked as read")


# ---------------- maintenance jobs (manual trigger for the demo) ----------------
@router.post("/jobs/run")
def run_jobs(db: Session = Depends(get_db),
             user=Depends(require_permission("settings.edit"))):
    from app.jobs.scheduler import run_all
    return run_all(db)
