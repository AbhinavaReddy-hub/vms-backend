"""Employees, admins, and roles/permissions."""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.deps import get_current_employee, get_request_context
from app.core.pagination import PageParams
from app.core.permissions import PERMISSION_CATALOG, require_permission
from app.core.security import hash_password
from app.core.tokens import admin_invite_link
from app.db.session import get_db
from app.models import Employee, Invite, InviteHost, Role, RolePermission, Visit, Visitor
from app.schemas.common import Msg
from app.schemas.people import (AdminInviteIn, EmployeeIn, EmployeeOut, EmployeeUpdate,
                                NotificationPrefsIn, PermissionOut, RoleIn, RoleOut)
from app.services import auth_service
from app.services.audit_service import log_action

router = APIRouter(tags=["People & Access"])


# ---------------- employees ----------------
@router.get("/employees")
def list_employees(page: PageParams = Depends(), db: Session = Depends(get_db),
                   user=Depends(require_permission("employees.view"))):
    q = db.query(Employee)
    if page.q:
        q = q.filter(Employee.full_name.ilike(f"%{page.q}%"))
    total = q.count()
    rows = q.order_by(Employee.full_name).offset(page.offset).limit(page.page_size).all()
    return {"items": [EmployeeOut(
        id=e.id, full_name=e.full_name, work_email=e.work_email, phone=e.phone,
        department=e.department, floor=e.floor, role_id=e.role_id,
        role_name=e.role.name if e.role else None, is_active=e.is_active,
        last_seen_at=e.last_seen_at, is_admin=e.role_id is not None,
    ) for e in rows], "total": total, "page": page.page, "page_size": page.page_size}


@router.get("/employees/search")
def search_employees(q: str = "", db: Session = Depends(get_db),
                     user=Depends(get_current_employee)):
    """Host picker. Any logged-in employee can use this - they need it to
    create an invite - but it returns only name and department."""
    query = db.query(Employee).filter(Employee.is_active.is_(True))
    if q:
        query = query.filter(Employee.full_name.ilike(f"%{q}%"))
    rows = query.order_by(Employee.full_name).limit(25).all()
    return {"items": [{"id": e.id, "full_name": e.full_name,
                       "department": e.department} for e in rows]}


@router.post("/employees", status_code=201)
def create_employee(data: EmployeeIn, db: Session = Depends(get_db),
                    user=Depends(require_permission("employees.edit")),
                    ctx: dict = Depends(get_request_context)):
    if db.query(Employee).filter(Employee.work_email == data.work_email.lower()).first():
        raise HTTPException(400, "An employee with this email already exists")
    emp = Employee(**{**data.model_dump(), "work_email": data.work_email.lower()})
    db.add(emp)
    db.commit()
    db.refresh(emp)
    log_action(db, action="employee.created", actor=user, entity_type="employee",
               entity_id=emp.id, detail={"name": emp.full_name}, ctx=ctx)
    return {"id": emp.id, "success": True}


@router.patch("/employees/{employee_id}")
def update_employee(employee_id: int, data: EmployeeUpdate, db: Session = Depends(get_db),
                    user=Depends(require_permission("employees.edit")),
                    ctx: dict = Depends(get_request_context)):
    emp = db.get(Employee, employee_id)
    if not emp:
        raise HTTPException(404, "Employee not found")
    payload = data.model_dump(exclude_unset=True)
    for k, v in payload.items():
        setattr(emp, k, v)
    db.commit()
    log_action(db, action="employee.updated", actor=user, entity_type="employee",
               entity_id=emp.id, detail=payload, ctx=ctx)
    return {"success": True}


@router.delete("/employees/{employee_id}", response_model=Msg)
def deactivate_employee(employee_id: int, db: Session = Depends(get_db),
                        user=Depends(require_permission("employees.delete")),
                        ctx: dict = Depends(get_request_context)):
    emp = db.get(Employee, employee_id)
    if not emp:
        raise HTTPException(404, "Employee not found")
    # Deactivate, never hard delete - their past visits must stay intact.
    emp.is_active = False
    db.commit()
    log_action(db, action="employee.deactivated", actor=user, entity_type="employee",
               entity_id=employee_id, detail={"name": emp.full_name}, ctx=ctx)
    return Msg(message="Employee deactivated")


@router.post("/employees/import")
def import_employees(payload: dict, db: Session = Depends(get_db),
                     user=Depends(require_permission("employees.edit")),
                     ctx: dict = Depends(get_request_context)):
    """Bulk add from a parsed CSV. Per-row errors are returned, not a whole-batch failure."""
    created, failed = 0, []
    for i, row in enumerate(payload.get("rows", []), start=1):
        try:
            email = (row.get("work_email") or "").lower()
            if not email or not row.get("full_name"):
                raise ValueError("full_name and work_email are required")
            if db.query(Employee).filter(Employee.work_email == email).first():
                raise ValueError("Email already exists")
            db.add(Employee(full_name=row["full_name"], work_email=email,
                            department=row.get("department"), phone=row.get("phone")))
            db.commit()
            created += 1
        except Exception as e:
            db.rollback()
            failed.append({"row": i, "error": str(e)})
    log_action(db, action="employee.imported", actor=user,
               detail={"created": created, "failed": len(failed)}, ctx=ctx)
    return {"created": created, "failed": failed}


# ---------------- my account ----------------
@router.get("/me/schedule")
def my_schedule(date: str | None = None, db: Session = Depends(get_db),
                user=Depends(get_current_employee)):
    day = datetime.fromisoformat(date).replace(tzinfo=timezone.utc) if date else \
        datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    invites = (db.query(Invite).join(InviteHost)
               .filter(InviteHost.employee_id == user.id,
                       Invite.arrival_at >= day, Invite.arrival_at < day + timedelta(days=1))
               .order_by(Invite.arrival_at).all())
    visits = db.query(Visit).filter(Visit.host_id == user.id, Visit.status == "open").all()
    visitors = {v.id: v for v in db.query(Visitor).filter(
        Visitor.id.in_([v.visitor_id for v in visits])).all()} if visits else {}
    return {
        "date": day.date().isoformat(),
        "expected": [{"invite_id": i.id, "name": i.full_name, "arrival_at": i.arrival_at,
                      "status": i.status} for i in invites],
        "currently_here": [{"visit_id": v.id, "visitor_id": v.visitor_id,
                            "name": visitors[v.visitor_id].full_name if v.visitor_id in visitors else "?",
                            "company": visitors[v.visitor_id].company if v.visitor_id in visitors else None,
                            "badge_number": v.badge_number,
                            "presence": v.presence, "entry_at": v.first_entry_at}
                           for v in visits],
    }


@router.get("/me/notification-preferences")
def get_prefs(user=Depends(get_current_employee)):
    return {"notify_email": user.notify_email, "notify_teams": user.notify_teams,
            "notify_sms": user.notify_sms, "teams_webhook_url": user.teams_webhook_url}


@router.patch("/me/notification-preferences")
def set_prefs(data: NotificationPrefsIn, db: Session = Depends(get_db),
              user=Depends(get_current_employee)):
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(user, k, v)
    db.commit()
    return {"success": True}


# ---------------- admins ----------------
@router.get("/admins")
def list_admins(page: PageParams = Depends(), role_id: int | None = None,
                db: Session = Depends(get_db),
                user=Depends(require_permission("admins.view"))):
    q = db.query(Employee).filter(Employee.role_id.isnot(None))
    if role_id:
        q = q.filter(Employee.role_id == role_id)
    if page.q:
        q = q.filter(Employee.full_name.ilike(f"%{page.q}%"))
    total = q.count()
    rows = q.order_by(Employee.full_name).offset(page.offset).limit(page.page_size).all()
    return {"items": [{
        "id": e.id, "full_name": e.full_name + (" (You)" if e.id == user.id else ""),
        "work_email": e.work_email, "role_id": e.role_id,
        "role_name": e.role.name if e.role else None,
        "last_seen_at": e.last_seen_at, "is_active": e.is_active,
        "is_you": e.id == user.id,
    } for e in rows], "total": total, "page": page.page, "page_size": page.page_size}


@router.post("/admin-invitations", status_code=201)
def invite_admin(data: AdminInviteIn, db: Session = Depends(get_db),
                 user=Depends(require_permission("admins.edit")),
                 ctx: dict = Depends(get_request_context)):
    try:
        inv, raw = auth_service.create_admin_invitation(db, data.employee_id, data.role_id, user, ctx)
    except auth_service.AuthError as e:
        raise HTTPException(400, str(e))
    return {"invitation_id": inv.id, "accept_link": admin_invite_link(raw),
            "expires_at": inv.expires_at}


@router.patch("/admins/{employee_id}")
def change_admin_role(employee_id: int, payload: dict, db: Session = Depends(get_db),
                      user=Depends(require_permission("admins.edit")),
                      ctx: dict = Depends(get_request_context)):
    emp = db.get(Employee, employee_id)
    if not emp:
        raise HTTPException(404, "Employee not found")
    emp.role_id = payload.get("role_id")
    db.commit()
    log_action(db, action="admin.role_changed", actor=user, entity_type="employee",
               entity_id=employee_id, detail=payload, ctx=ctx)
    return {"success": True}


@router.delete("/admins/{employee_id}", response_model=Msg)
def remove_admin(employee_id: int, db: Session = Depends(get_db),
                 user=Depends(require_permission("admins.delete")),
                 ctx: dict = Depends(get_request_context)):
    if employee_id == user.id:
        raise HTTPException(400, "You cannot remove your own admin access")
    emp = db.get(Employee, employee_id)
    if not emp:
        raise HTTPException(404, "Employee not found")
    emp.role_id = None
    db.commit()
    auth_service.logout_everywhere(db, employee_id)
    log_action(db, action="admin.removed", actor=user, entity_type="employee",
               entity_id=employee_id, detail={"name": emp.full_name}, ctx=ctx)
    return Msg(message="Admin access removed")


# ---------------- roles & permissions ----------------
@router.get("/permissions")
def list_permissions(user=Depends(require_permission("roles.view"))):
    """The catalog the Roles screen renders its checkboxes from."""
    grouped: dict = {}
    for key, (module, sub, label) in PERMISSION_CATALOG.items():
        grouped.setdefault(module, {}).setdefault(sub, []).append(
            {"key": key, "label": label})
    return {"modules": grouped, "total": len(PERMISSION_CATALOG)}


@router.get("/roles")
def list_roles(db: Session = Depends(get_db),
               user=Depends(require_permission("roles.view", "admins.view"))):
    rows = db.query(Role).order_by(Role.name).all()
    return {"items": [RoleOut(id=r.id, name=r.name, description=r.description,
                              is_system=r.is_system, permissions=r.permission_keys)
                      for r in rows], "total": len(rows)}


@router.post("/roles", status_code=201)
def create_role(data: RoleIn, db: Session = Depends(get_db),
                user=Depends(require_permission("roles.edit")),
                ctx: dict = Depends(get_request_context)):
    if db.query(Role).filter(Role.name == data.name).first():
        raise HTTPException(400, "A role with this name already exists")
    unknown = [p for p in data.permissions if p not in PERMISSION_CATALOG]
    if unknown:
        raise HTTPException(400, f"Unknown permissions: {unknown}")

    role = Role(name=data.name, description=data.description, is_system=False)
    db.add(role)
    db.flush()
    for p in data.permissions:
        db.add(RolePermission(role_id=role.id, permission_key=p))
    db.commit()
    db.refresh(role)
    log_action(db, action="role.created", actor=user, entity_type="role",
               entity_id=role.id, detail={"name": role.name,
                                          "permissions": len(data.permissions)}, ctx=ctx)
    return RoleOut(id=role.id, name=role.name, description=role.description,
                   is_system=role.is_system, permissions=role.permission_keys)


@router.get("/roles/{role_id}")
def get_role(role_id: int, db: Session = Depends(get_db),
             user=Depends(require_permission("roles.view"))):
    r = db.get(Role, role_id)
    if not r:
        raise HTTPException(404, "Role not found")
    return RoleOut(id=r.id, name=r.name, description=r.description,
                   is_system=r.is_system, permissions=r.permission_keys)


@router.patch("/roles/{role_id}")
def update_role(role_id: int, data: RoleIn, db: Session = Depends(get_db),
                user=Depends(require_permission("roles.edit")),
                ctx: dict = Depends(get_request_context)):
    role = db.get(Role, role_id)
    if not role:
        raise HTTPException(404, "Role not found")
    if role.is_system:
        raise HTTPException(400, "System roles cannot be edited")
    role.name = data.name
    role.description = data.description
    db.query(RolePermission).filter(RolePermission.role_id == role_id).delete()
    for p in data.permissions:
        if p in PERMISSION_CATALOG:
            db.add(RolePermission(role_id=role_id, permission_key=p))
    db.commit()
    db.refresh(role)
    log_action(db, action="role.updated", actor=user, entity_type="role",
               entity_id=role_id, ctx=ctx)
    return RoleOut(id=role.id, name=role.name, description=role.description,
                   is_system=role.is_system, permissions=role.permission_keys)


@router.delete("/roles/{role_id}", response_model=Msg)
def delete_role(role_id: int, db: Session = Depends(get_db),
                user=Depends(require_permission("roles.delete")),
                ctx: dict = Depends(get_request_context)):
    role = db.get(Role, role_id)
    if not role:
        raise HTTPException(404, "Role not found")
    if role.is_system:
        raise HTTPException(400, "System roles cannot be deleted")
    if db.query(Employee).filter(Employee.role_id == role_id).count():
        raise HTTPException(400, "This role is still assigned to people")
    name = role.name
    db.delete(role)
    db.commit()
    log_action(db, action="role.deleted", actor=user, entity_type="role",
               entity_id=role_id, detail={"name": name}, ctx=ctx)
    return Msg(message="Role deleted")
