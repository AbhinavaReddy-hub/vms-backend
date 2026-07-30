"""Password hashing, JWT creation/verification, and a small rate limiter.

Nothing here talks to the database or to FastAPI - it is pure functions,
so it can be tested on its own.
"""
import hashlib
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
import jwt

from app.core.config import settings


# ---------- passwords ----------
def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except Exception:
        return False


# ---------- JWT ----------
def create_access_token(employee_id: int) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(employee_id),
        "type": "access",
        "iat": now,
        "exp": now + timedelta(minutes=settings.ACCESS_TOKEN_MINUTES),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> Optional[int]:
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
        if payload.get("type") != "access":
            return None
        return int(payload["sub"])
    except Exception:
        return None


# ---------- opaque tokens (invites, devices, refresh, admin invitations) ----------
def generate_token() -> str:
    """Long random string. Not guessable, not sequential."""
    return secrets.token_urlsafe(32)


def hash_token(raw: str) -> str:
    """Only the hash is ever stored. If the DB leaks, the tokens in it are useless."""
    return hashlib.sha256(raw.encode()).hexdigest()


def generate_numeric_code(length: int = 6) -> str:
    return "".join(secrets.choice("0123456789") for _ in range(length))


# ---------- rate limiting ----------
# In-memory on purpose: no Redis needed for a single-process demo.
# For production behind multiple workers, swap this one file for a Redis counter.
_hits: dict[str, list[float]] = {}


def rate_limit(key: str, max_calls: int, per_seconds: int) -> bool:
    """Returns True if the call is allowed, False if the caller is over the limit."""
    now = time.time()
    window = _hits.setdefault(key, [])
    window[:] = [t for t in window if now - t < per_seconds]
    if len(window) >= max_calls:
        return False
    window.append(now)
    return True
