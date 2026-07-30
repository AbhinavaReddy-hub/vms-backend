"""OTP generate / verify. Codes are stored hashed and expire quickly."""
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import generate_numeric_code, hash_token, rate_limit
from app.clients.sms_client import sms_client
from app.models import OtpChallenge


class OtpError(Exception):
    pass


def send_otp(db: Session, destination: str, purpose: str, ref: str | None = None) -> dict:
    if not rate_limit(f"otp:{destination}", max_calls=5, per_seconds=600):
        raise OtpError("Too many OTP requests. Please wait a few minutes.")

    code = generate_numeric_code(settings.OTP_LENGTH)
    challenge = OtpChallenge(
        destination=destination,
        code_hash=hash_token(code),
        purpose=purpose,
        ref=ref,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=settings.OTP_EXPIRY_MINUTES),
    )
    db.add(challenge)
    db.commit()
    db.refresh(challenge)

    sms_client.send(destination, f"Your verification code is {code}. Valid for {settings.OTP_EXPIRY_MINUTES} minutes.")

    out = {"challenge_id": challenge.id, "expires_in": settings.OTP_EXPIRY_MINUTES * 60}
    # In dev (no Twilio key) we return the code so the flow is testable end to end.
    if not settings.TWILIO_SID:
        out["dev_code"] = code
    return out


def verify_otp(db: Session, destination: str, code: str, purpose: str) -> bool:
    now = datetime.now(timezone.utc)
    challenge = (
        db.query(OtpChallenge)
        .filter(
            OtpChallenge.destination == destination,
            OtpChallenge.purpose == purpose,
            OtpChallenge.consumed_at.is_(None),
        )
        .order_by(OtpChallenge.id.desc())
        .first()
    )
    if not challenge:
        raise OtpError("No verification code was requested for this number.")
    if challenge.expires_at.replace(tzinfo=timezone.utc) < now:
        raise OtpError("This code has expired. Request a new one.")
    if challenge.attempts >= settings.OTP_MAX_ATTEMPTS:
        raise OtpError("Too many wrong attempts. Please see reception.")

    challenge.attempts += 1
    if challenge.code_hash != hash_token(code):
        db.commit()
        left = settings.OTP_MAX_ATTEMPTS - challenge.attempts
        raise OtpError(f"Incorrect code. {left} attempt(s) left.")

    challenge.verified = True
    challenge.consumed_at = now
    db.commit()
    return True
