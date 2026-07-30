"""Append-only audit trail. Every mutating action calls this."""
import json
from sqlalchemy.orm import Session

from app.models import AuditLog


def log_action(db: Session, *, action: str, actor=None, actor_type: str = "employee",
               entity_type: str | None = None, entity_id: int | None = None,
               detail: dict | None = None, ctx: dict | None = None, commit: bool = True):
    row = AuditLog(
        actor_id=getattr(actor, "id", None),
        actor_type=actor_type,
        actor_name=getattr(actor, "full_name", None) or getattr(actor, "name", None),
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        detail=json.dumps(detail, default=str) if detail else None,
        ip=(ctx or {}).get("ip"),
        user_agent=(ctx or {}).get("user_agent"),
    )
    db.add(row)
    if commit:
        db.commit()
    return row
