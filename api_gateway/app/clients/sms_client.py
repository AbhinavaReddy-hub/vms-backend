"""SMS / OTP delivery. Twilio today, anything else tomorrow - one file."""
import logging

from app.core.config import settings

log = logging.getLogger(__name__)


class SmsClient:
    def send(self, to: str, body: str) -> dict:
        if not settings.TWILIO_SID:
            log.info("[SMS - dev mode, not sent] to=%s", to)
            print(f"\n--- SMS to {to} ---\n{body}\n---\n")
            return {"status": "logged", "sent": False}
        try:
            import httpx
            r = httpx.post(
                f"https://api.twilio.com/2010-04-01/Accounts/{settings.TWILIO_SID}/Messages.json",
                auth=(settings.TWILIO_SID, settings.TWILIO_TOKEN),
                data={"To": to, "From": settings.TWILIO_FROM, "Body": body},
                timeout=10.0,
            )
            if r.is_error:
                # Twilio puts the useful part in the JSON body - a bare
                # raise_for_status() throws it away and leaves you with only
                # "400 Bad Request", which says nothing about what to fix.
                try:
                    err = r.json()
                    code, msg = err.get("code"), err.get("message", "")
                except Exception:
                    code, msg = None, r.text[:200]
                hint = _HINTS.get(code, "")
                log.error("SMS to %s failed: Twilio %s - %s%s", to, code, msg, hint)
                return {"status": "failed", "sent": False,
                        "error": f"Twilio {code}: {msg}", "twilio_code": code}
            return {"status": "sent", "sent": True}
        except Exception as e:
            log.error("SMS to %s failed: %s", to, e)
            return {"status": "failed", "sent": False, "error": str(e)}


# The handful of Twilio errors worth explaining inline, so the log tells you
# what to do instead of just what broke.
_HINTS = {
    21608: ("  -> Trial accounts can only text VERIFIED numbers. Verify this "
            "number in Twilio Console > Phone Numbers > Verified Caller IDs, "
            "or upgrade the account. (Leave TWILIO_SID blank in .env to make "
            "the app print SMS to the console instead of sending.)"),
    21211: "  -> 'To' is not a valid E.164 number (needs the +country prefix).",
    21606: "  -> TWILIO_FROM is not an SMS-capable number on this account.",
    21610: "  -> That number replied STOP and is unsubscribed.",
    20003: "  -> Auth failed: check TWILIO_SID / TWILIO_TOKEN.",
}


sms_client = SmsClient()
