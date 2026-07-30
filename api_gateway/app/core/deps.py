"""Shared FastAPI dependencies.

There are THREE separate ways to authenticate, and they are deliberately
separate functions. A visitor token can never reach an admin route, and a
kiosk token can never reach an admin route - not because of a flag check,
but because those routes use a different dependency entirely.
"""
from datetime import datetime, timezone

from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.security import decode_access_token, hash_token
from app.db.session import get_db
from app.models import Device, Employee

bearer = HTTPBearer(auto_error=False)


# ---------- 1. staff (admin website) ----------
def get_current_employee(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> Employee:
    if not creds:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")

    employee_id = decode_access_token(creds.credentials)
    if not employee_id:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")

    emp = db.get(Employee, employee_id)
    if not emp or not emp.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account inactive")

    # attach the resolved permission set for require_permission() to read
    emp._permissions = set(emp.role.permission_keys) if emp.role else set()

    # last_seen powers the Admins table column. Throttled to once a minute
    # so we are not writing on every single request.
    now = datetime.now(timezone.utc)
    if not emp.last_seen_at or (now - emp.last_seen_at.replace(tzinfo=timezone.utc)).seconds > 60:
        emp.last_seen_at = now
        db.commit()
    return emp


# ---------- 2. kiosk device ----------
def get_current_device(
    x_device_token: str | None = Header(None, alias="X-Device-Token"),
    db: Session = Depends(get_db),
) -> Device:
    if not x_device_token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Device token required")

    device = db.query(Device).filter(
        Device.token_hash == hash_token(x_device_token),
        Device.status == "active",
    ).first()
    if not device:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unknown or revoked device")

    device.last_seen_at = datetime.now(timezone.utc)
    db.commit()
    return device


# ---------- 3. request context (for the audit log) ----------
def get_request_context(request: Request) -> dict:
    return {
        "ip": request.client.host if request.client else None,
        "user_agent": request.headers.get("user-agent"),
    }
