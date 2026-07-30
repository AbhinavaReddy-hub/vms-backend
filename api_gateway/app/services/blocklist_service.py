"""Blocklist checking. Matches on email, phone, or exact name."""
from sqlalchemy.orm import Session

from app.models import BlocklistEntry


def check(db: Session, *, full_name: str | None = None, email: str | None = None,
          phone: str | None = None) -> BlocklistEntry | None:
    q = db.query(BlocklistEntry).filter(BlocklistEntry.is_active.is_(True))
    for entry in q.all():
        if email and entry.email and entry.email.lower() == email.lower():
            return entry
        if phone and entry.phone and _digits(entry.phone) == _digits(phone):
            return entry
        if full_name and entry.full_name and entry.full_name.strip().lower() == full_name.strip().lower():
            return entry
    return None


def _digits(s: str) -> str:
    return "".join(c for c in s if c.isdigit())[-10:]
