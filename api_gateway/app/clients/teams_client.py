"""Microsoft Teams notifications via incoming webhook + Adaptive Card.

Approve/Deny are Action.OpenUrl links pointing at a signed URL in our app.
A full Teams bot would give in-card buttons, but needs app registration and
admin consent - not worth the setup cost for this scope. Documented as a
deliberate tradeoff.
"""
import logging

from app.core.config import settings

log = logging.getLogger(__name__)


class TeamsClient:
    def send_card(self, webhook_url: str | None, title: str, text: str,
                  facts: dict | None = None, actions: list[dict] | None = None) -> dict:
        card = {
            "type": "message",
            "attachments": [{
                "contentType": "application/vnd.microsoft.card.adaptive",
                "content": {
                    "type": "AdaptiveCard",
                    "version": "1.4",
                    "body": [
                        {"type": "TextBlock", "text": title, "weight": "Bolder", "size": "Medium"},
                        {"type": "TextBlock", "text": text, "wrap": True},
                        {"type": "FactSet", "facts": [
                            {"title": k, "value": str(v)} for k, v in (facts or {}).items()
                        ]},
                    ],
                    "actions": [
                        {"type": "Action.OpenUrl", "title": a["title"], "url": a["url"]}
                        for a in (actions or [])
                    ],
                },
            }],
        }

        if not webhook_url:
            log.info("[TEAMS - no webhook configured] %s", title)
            print(f"\n--- TEAMS CARD ---\n{title}\n{text}\n{facts}\n---\n")
            return {"status": "logged", "sent": False}
        try:
            import httpx
            r = httpx.post(webhook_url, json=card, timeout=10.0)
            r.raise_for_status()
            return {"status": "sent", "sent": True}
        except Exception as e:
            log.error("Teams send failed: %s", e)
            return {"status": "failed", "sent": False, "error": str(e)}


teams_client = TeamsClient()
