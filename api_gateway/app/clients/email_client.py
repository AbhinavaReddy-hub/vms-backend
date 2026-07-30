"""Email sending. Swap SendGrid for SES by changing only this file.

With no API key configured (dev), it logs instead of sending - so the whole
flow is testable without any external account.
"""
import logging

from app.core.config import settings

log = logging.getLogger(__name__)


class EmailClient:
    def send(self, to: str, subject: str, html: str, reply_to: str | None = None) -> dict:
        if not settings.SENDGRID_API_KEY:
            log.info("[EMAIL - dev mode, not sent] to=%s subject=%s", to, subject)
            print(f"\n--- EMAIL to {to} ---\nSubject: {subject}\n{_text(html)}\n---\n")
            return {"status": "logged", "sent": False}
        try:
            import httpx
            r = httpx.post(
                "https://api.sendgrid.com/v3/mail/send",
                headers={"Authorization": f"Bearer {settings.SENDGRID_API_KEY}"},
                json={
                    "personalizations": [{"to": [{"email": to}]}],
                    "from": {"email": settings.FROM_EMAIL},
                    "reply_to": {"email": reply_to} if reply_to else None,
                    "subject": subject,
                    "content": [{"type": "text/html", "value": html}],
                },
                timeout=10.0,
            )
            r.raise_for_status()
            return {"status": "sent", "sent": True}
        except Exception as e:
            log.error("Email send failed: %s", e)
            return {"status": "failed", "sent": False, "error": str(e)}


def _text(html: str) -> str:
    import re
    return re.sub(r"<[^>]+>", " ", html).strip()[:600]


email_client = EmailClient()
