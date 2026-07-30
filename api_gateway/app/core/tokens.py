"""Helpers for building the visitor-facing links and QR payloads."""
from app.core.config import settings


def invite_link(raw_token: str) -> str:
    return f"{settings.PUBLIC_BASE_URL}/register/{raw_token}"


def pass_link(raw_token: str) -> str:
    return f"{settings.PUBLIC_BASE_URL}/pass/{raw_token}"


def admin_invite_link(raw_token: str) -> str:
    return f"{settings.PUBLIC_BASE_URL}/admin-accept/{raw_token}"


def admin_link(path: str) -> str:
    """A link into the admin dashboard (vms-frontend), e.g. for Approve/Deny
    buttons in a Teams card or email - a DIFFERENT app/origin than the
    visitor-facing links above, so it needs its own base URL."""
    return f"{settings.FRONTEND_ORIGIN}{path}"
