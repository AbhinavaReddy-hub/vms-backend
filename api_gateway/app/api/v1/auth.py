from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.deps import get_current_employee, get_request_context
from app.db.session import get_db
from app.schemas.auth import (AcceptAdminInviteIn, LoginIn, MeOut, RefreshIn, TokenOut)
from app.schemas.common import Msg
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["Auth"])


@router.post("/login", response_model=TokenOut)
def login(data: LoginIn, db: Session = Depends(get_db), ctx: dict = Depends(get_request_context)):
    try:
        return auth_service.login(db, data.email.lower(), data.password, ctx)
    except auth_service.AuthError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(e))


@router.post("/refresh", response_model=TokenOut)
def refresh(data: RefreshIn, db: Session = Depends(get_db)):
    try:
        return auth_service.refresh(db, data.refresh_token)
    except auth_service.AuthError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(e))


@router.post("/logout", response_model=Msg)
def logout(data: RefreshIn, db: Session = Depends(get_db),
           user=Depends(get_current_employee), ctx: dict = Depends(get_request_context)):
    auth_service.logout(db, data.refresh_token, user, ctx)
    return Msg(message="Signed out")


@router.post("/logout-everywhere", response_model=Msg)
def logout_everywhere(db: Session = Depends(get_db), user=Depends(get_current_employee)):
    auth_service.logout_everywhere(db, user.id)
    return Msg(message="Signed out on all devices")


@router.get("/me", response_model=MeOut)
def me(user=Depends(get_current_employee)):
    return MeOut(
        id=user.id, full_name=user.full_name, work_email=user.work_email,
        department=user.department,
        role_name=user.role.name if user.role else None,
        permissions=sorted(user._permissions),
        last_seen_at=user.last_seen_at,
    )


@router.post("/accept-admin-invite", response_model=Msg)
def accept_admin_invite(data: AcceptAdminInviteIn, db: Session = Depends(get_db)):
    try:
        emp = auth_service.accept_admin_invitation(db, data.token, data.password)
        return Msg(message=f"Welcome, {emp.full_name}. You can now sign in.")
    except auth_service.AuthError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
