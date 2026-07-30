"""Login, refresh, logout, and admin invitation acceptance."""
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import (create_access_token, generate_token, hash_password,
                               hash_token, rate_limit, verify_password)
from app.models import AdminInvitation, Employee, RefreshToken
from app.services.audit_service import log_action


class AuthError(Exception):
    pass


def login(db: Session, email: str, password: str, ctx: dict | None = None) -> dict:
    if not rate_limit(f"login:{(ctx or {}).get('ip', 'unknown')}", 10, 300):
        raise AuthError("Too many attempts. Please try again shortly.")

    emp = db.query(Employee).filter(Employee.work_email == email.lower()).first()
    now = datetime.now(timezone.utc)

    # Generic message on purpose - never reveal whether the email exists.
    generic = "Invalid email or password"

    if emp and emp.locked_until and emp.locked_until.replace(tzinfo=timezone.utc) > now:
        raise AuthError("Account temporarily locked. Try again later.")

    if not emp or not emp.password_hash or not verify_password(password, emp.password_hash):
        if emp:
            emp.failed_attempts += 1
            if emp.failed_attempts >= settings.LOGIN_MAX_ATTEMPTS:
                emp.locked_until = now + timedelta(minutes=settings.LOGIN_LOCKOUT_MINUTES)
                emp.failed_attempts = 0
            db.commit()
            log_action(db, action="auth.login_failed", actor=emp, ctx=ctx)
        raise AuthError(generic)

    if not emp.is_active:
        raise AuthError(generic)

    emp.failed_attempts = 0
    emp.locked_until = None
    emp.last_seen_at = now
    db.commit()

    raw_refresh = generate_token()
    db.add(RefreshToken(
        employee_id=emp.id,
        token_hash=hash_token(raw_refresh),
        expires_at=now + timedelta(days=settings.REFRESH_TOKEN_DAYS),
        user_agent=(ctx or {}).get("user_agent"),
        ip=(ctx or {}).get("ip"),
    ))
    db.commit()

    log_action(db, action="auth.login", actor=emp, ctx=ctx)
    return {
        "access_token": create_access_token(emp.id),
        "refresh_token": raw_refresh,
        "expires_in": settings.ACCESS_TOKEN_MINUTES * 60,
    }


def refresh(db: Session, raw_refresh: str) -> dict:
    now = datetime.now(timezone.utc)
    row = db.query(RefreshToken).filter(
        RefreshToken.token_hash == hash_token(raw_refresh),
        RefreshToken.revoked_at.is_(None),
    ).first()
    if not row or row.expires_at.replace(tzinfo=timezone.utc) < now:
        raise AuthError("Session expired. Please sign in again.")

    return {
        "access_token": create_access_token(row.employee_id),
        "refresh_token": raw_refresh,
        "expires_in": settings.ACCESS_TOKEN_MINUTES * 60,
    }


def logout(db: Session, raw_refresh: str, actor: Employee, ctx: dict | None = None):
    row = db.query(RefreshToken).filter(
        RefreshToken.token_hash == hash_token(raw_refresh)).first()
    if row:
        row.revoked_at = datetime.now(timezone.utc)
        db.commit()
    log_action(db, action="auth.logout", actor=actor, ctx=ctx)


def logout_everywhere(db: Session, employee_id: int):
    now = datetime.now(timezone.utc)
    db.query(RefreshToken).filter(
        RefreshToken.employee_id == employee_id,
        RefreshToken.revoked_at.is_(None),
    ).update({"revoked_at": now})
    db.commit()


def create_admin_invitation(db: Session, employee_id: int, role_id: int,
                            invited_by: Employee, ctx: dict | None = None) -> tuple[AdminInvitation, str]:
    emp = db.get(Employee, employee_id)
    if not emp:
        raise AuthError("Employee not found")

    raw = generate_token()
    inv = AdminInvitation(
        employee_id=employee_id, role_id=role_id, token_hash=hash_token(raw),
        invited_by_id=invited_by.id,
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
    )
    db.add(inv)
    db.commit()
    db.refresh(inv)

    from app.clients.email_client import email_client
    from app.core.tokens import admin_invite_link
    from app.services.notification_service import _email_shell, _BRAND, _INK, _MUTED
    from app.models import Role
    role = db.get(Role, role_id)
    body_html = f"""
      <h2 style="margin:0 0 10px;color:{_INK};font-size:20px;">You're invited to join the team</h2>
      <p style="margin:0 0 16px;color:{_MUTED};font-size:15px;line-height:1.6;">
        Hi {emp.full_name}, {invited_by.full_name} has invited you to help manage the
        Visitor Management System as <b style="color:{_INK};">{role.name if role else 'Admin'}</b>.
      </p>
      <a href="{admin_invite_link(raw)}"
         style="display:inline-block;background:{_BRAND};color:#fff;padding:12px 24px;
                border-radius:8px;text-decoration:none;font-weight:600;font-size:14px;">
        Accept invitation
      </a>
    """
    email_client.send(
        emp.work_email,
        "You've been invited to manage the Visitor Management System",
        _email_shell("Admin Invitation", body_html),
    )

    log_action(db, action="admin.invited", actor=invited_by, entity_type="employee",
               entity_id=employee_id, detail={"role_id": role_id}, ctx=ctx)
    return inv, raw


def accept_admin_invitation(db: Session, raw_token: str, password: str | None) -> Employee:
    inv = db.query(AdminInvitation).filter(
        AdminInvitation.token_hash == hash_token(raw_token),
        AdminInvitation.status == "pending",
    ).first()
    if not inv:
        raise AuthError("This invitation is not valid.")
    if inv.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
        inv.status = "expired"
        db.commit()
        raise AuthError("This invitation has expired.")

    emp = db.get(Employee, inv.employee_id)
    emp.role_id = inv.role_id
    if not emp.password_hash:
        if not password:
            raise AuthError("Please set a password to finish setting up your account.")
        emp.password_hash = hash_password(password)

    inv.status = "accepted"
    inv.accepted_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(emp)
    log_action(db, action="admin.invitation_accepted", actor=emp,
               entity_type="employee", entity_id=emp.id)
    return emp
