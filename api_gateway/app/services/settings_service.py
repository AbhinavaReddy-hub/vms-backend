"""Key/value settings with sensible defaults, so a missing row never breaks anything."""
import json
from sqlalchemy.orm import Session

from app.core.config import settings as cfg
from app.models import AppSetting

DEFAULTS = {
    "face.match_threshold": cfg.FACE_MATCH_THRESHOLD,
    "face.liveness_required": False,
    "face.max_retries": 3,
    "face.reregister_after_days": 180,
    "privacy.face_retention_days": cfg.FACE_RETENTION_DAYS,
    "privacy.visit_log_retention_days": 365,
    "privacy.store_photos": False,
    "privacy.consent_text": (
        "We use your photo only to verify you at the door during this visit. "
        "It is deleted automatically after the retention period. "
        "You can decline and use OTP verification instead."
    ),
    "capacity.max_expected_per_day": 10,
    "approval.timeout_minutes": cfg.APPROVAL_TIMEOUT_MINUTES,
    "visit.auto_close_hour": cfg.AUTO_CLOSE_HOUR,
    "visit.presume_departed_after_hours": 4,
    "company.name": cfg.COMPANY_NAME,
}


def get_setting(db: Session, key: str):
    row = db.get(AppSetting, key)
    if row is None:
        return DEFAULTS.get(key)
    try:
        return json.loads(row.value)
    except Exception:
        return row.value


def set_setting(db: Session, key: str, value, employee_id: int | None = None):
    row = db.get(AppSetting, key)
    payload = json.dumps(value)
    if row:
        row.value = payload
        row.updated_by_id = employee_id
    else:
        db.add(AppSetting(key=key, value=payload, updated_by_id=employee_id))
    db.commit()
    return value


def all_settings(db: Session) -> dict:
    out = dict(DEFAULTS)
    for row in db.query(AppSetting).all():
        try:
            out[row.key] = json.loads(row.value)
        except Exception:
            out[row.key] = row.value
    return out
