"""Mints and looks up the credentials behind the post-approval "welcome" link.

Every bearer token elsewhere in this codebase (Invite.token_hash,
Device.token_hash, WalkInSession.token_hash) is stored hash-only, so the raw
value can never be recovered after the moment it's generated. Approval
happens in a separate request from registration, so the pass link has to be
minted fresh, right when approval happens - it can't be pre-generated at
registration time and just revealed later.

The access_code is different in kind: it's meant to be re-displayed on the
pass page and re-typed at a kiosk, so it's plaintext, mirroring the existing
Device.pairing_code / Visit.badge_number precedent - not a secret bearer
token, just a human-facing reference code.
"""
from sqlalchemy.orm import Session

from app.core.security import generate_numeric_code, generate_token, hash_token
from app.models import Invite, Visit


def mint_credentials(entity: Invite | Visit) -> tuple[str, str]:
    """Sets pass_token_hash + access_code on the given Invite/Visit and
    returns (raw_pass_token, access_code). Caller commits."""
    raw_token = generate_token()
    code = generate_numeric_code(6)
    entity.pass_token_hash = hash_token(raw_token)
    entity.access_code = code
    return raw_token, code


def find_pass_entity(db: Session, token: str) -> tuple[str, Invite | Visit] | None:
    """Resolves a pass-page token to whichever entity it belongs to.

    Tries, in order: Invite.token_hash (pre-approval "submitted" screen,
    unchanged from today), Invite.pass_token_hash (invite-based, post
    approval), Visit.pass_token_hash (walk-in - no Invite row at all).
    """
    hashed = hash_token(token)

    invite = db.query(Invite).filter(Invite.token_hash == hashed).first()
    if invite:
        return "invite", invite

    invite = db.query(Invite).filter(Invite.pass_token_hash == hashed).first()
    if invite:
        return "invite", invite

    visit = db.query(Visit).filter(Visit.pass_token_hash == hashed).first()
    if visit:
        return "visit", visit

    return None
