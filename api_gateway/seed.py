"""Seeds roles, permissions, visitor types, employees, and one kiosk device
on first run, so the API is testable immediately.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.permissions import SYSTEM_ROLES
from app.core.security import generate_numeric_code, hash_password
from app.models import Device, Employee, Role, RolePermission, VisitorType

DEFAULT_TYPES = [
    dict(name="Guest",     badge_color="#2563EB", requires_approval=True,  requires_face=True,
         requires_legal_docs=False, auto_approve_default=False, default_validity_hours=12),
    dict(name="Candidate", badge_color="#16A34A", requires_approval=True,  requires_face=True,
         requires_legal_docs=True,  auto_approve_default=False, default_validity_hours=24),
    dict(name="Vendor/Contractor", badge_color="#EA580C", requires_approval=True, requires_face=True,
         requires_legal_docs=True,  auto_approve_default=False, default_validity_hours=72),
    dict(name="VIP",       badge_color="#CA8A04", requires_approval=False, requires_face=True,
         requires_legal_docs=False, auto_approve_default=True,  default_validity_hours=24),
]

DEFAULT_EMPLOYEES = [
    ("Abhinav Reddy",   "abhinav@company.com",  "Engineering", "Global Admin",   "Admin@12345"),
    ("Priya Sharma",    "priya@company.com",    "Security",    "Security Desk",  "Security@123"),
    ("Suresh Kumar",    "suresh@company.com",   "Engineering", "Host",           "Host@12345"),
    ("Meera Nair",      "meera@company.com",    "HR",          "Approvals Admin", "Approve@123"),
    ("Rahul Verma",     "rahul@company.com",    "Sales",       None,             None),
]


def seed_if_empty(db: Session) -> dict:
    created = {}

    if db.query(Role).count() == 0:
        for name, perms in SYSTEM_ROLES.items():
            role = Role(name=name, description=f"{name} (built in)", is_system=True)
            db.add(role)
            db.flush()
            for p in perms:
                db.add(RolePermission(role_id=role.id, permission_key=p))
        db.commit()
        created["roles"] = len(SYSTEM_ROLES)

    if db.query(VisitorType).count() == 0:
        for t in DEFAULT_TYPES:
            db.add(VisitorType(**t))
        db.commit()
        created["visitor_types"] = len(DEFAULT_TYPES)

    if db.query(Employee).count() == 0:
        for full_name, email, dept, role_name, password in DEFAULT_EMPLOYEES:
            role = db.query(Role).filter(Role.name == role_name).first() if role_name else None
            db.add(Employee(
                full_name=full_name, work_email=email, department=dept,
                role_id=role.id if role else None,
                password_hash=hash_password(password) if password else None,
                notify_email=True, notify_teams=False,
            ))
        db.commit()
        created["employees"] = len(DEFAULT_EMPLOYEES)

    if db.query(Device).count() == 0:
        # Fixed codes in seed so the demo is repeatable. One of each mode,
        # so a fresh install has a working example of all three device roles.
        reg = Device(name="Reception Registration Kiosk", location_label="Main lobby",
                    mode="registration_kiosk", pairing_code="111111", status="unpaired")
        db.add(reg)

        entry = Device(name="Main Entrance - Entry", location_label="Main entrance",
                       mode="checkinout", direction="entry", pairing_code="222221",
                       status="unpaired")
        exit_ = Device(name="Main Entrance - Exit", location_label="Main entrance",
                       mode="checkinout", direction="exit", pairing_code="222222",
                       status="unpaired")
        db.add(entry)
        db.add(exit_)
        db.flush()
        entry.paired_device_id = exit_.id
        exit_.paired_device_id = entry.id

        db.commit()
        created["devices"] = 3
        created["pairing_codes"] = {"registration_kiosk": "111111",
                                    "checkinout_entry": "222221", "checkinout_exit": "222222"}

    if created:
        print(f"[seed] created: {created}")
    return created


if __name__ == "__main__":
    from app.db.base import Base
    from app.db.session import SessionLocal, engine
    import app.models  # noqa
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed_if_empty(db)
    finally:
        db.close()
