from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import AuthUser, create_token, decode_token, verify_password
from app.db.session import get_db
from app.models.user import User
from app.services.audit import log_audit

router = APIRouter(prefix="/auth")
settings = get_settings()


class LoginRequest(BaseModel):
    email: str
    password: str


class AuthUserResponse(BaseModel):
    id: str
    email: str
    full_name: str
    tenant_id: str | None
    role: str
    permissions: list[str] = Field(default_factory=list)


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: AuthUserResponse


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str | None = None


def _to_response(user: AuthUser, permissions: list[str] | None = None) -> AuthUserResponse:
    return AuthUserResponse(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        tenant_id=user.tenant_id,
        role=user.role,
        permissions=permissions or [],
    )


def _issue_tokens(user: AuthUser, permissions: list[str] | None = None) -> TokenPair:
    subject = {"sub": user.id, "email": user.email, "tenant_id": user.tenant_id, "role": user.role}
    access_token = create_token(subject, expires_in_seconds=settings.access_token_ttl_minutes * 60, token_type="access")
    refresh_token = create_token(subject, expires_in_seconds=settings.refresh_token_ttl_minutes * 60, token_type="refresh")
    return TokenPair(access_token=access_token, refresh_token=refresh_token, user=_to_response(user, permissions))


def get_current_user(authorization: str | None = Header(default=None), db: Session = Depends(get_db)) -> AuthUserResponse:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")

    payload = decode_token(authorization.removeprefix("Bearer ").strip(), expected_type="access")
    user_id = str(payload.get("sub"))
    user = db.scalar(select(User).where(User.id == user_id))
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unknown account")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is deactivated")

    permission_codes = set()
    if user.role is not None:
        permission_codes.update(permission.code for permission in user.role.permissions)
    for role in user.roles:
        permission_codes.update(permission.code for permission in role.permissions)
    return _to_response(
        AuthUser(
            id=user.id,
            email=user.email,
            full_name=user.full_name,
            tenant_id=user.tenant_id,
            role=user.role.code if user.role is not None else "member",
        ),
        sorted(permission_codes),
    )


def _load_user(db: Session, email: str) -> User | None:
    statement = select(User).where(User.email == email)
    return db.scalar(statement)


@router.post("/login", response_model=TokenPair)
def login(request: LoginRequest, db: Session = Depends(get_db)) -> TokenPair:
    user = _load_user(db, request.email)
    if user is None or not verify_password(request.password, user.password_hash):
        log_audit(
            db,
            action="login_failed",
            entity_type="auth",
            entity_id=None,
            actor_email=request.email,
            metadata={"reason": "invalid_credentials"},
        )
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if not user.is_active:
        log_audit(
            db,
            action="login_failed",
            entity_type="auth",
            entity_id=user.id,
            actor_user=user,
            metadata={"reason": "inactive_user"},
        )
        db.commit()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is deactivated")

    user.last_login_at = datetime.now(UTC)

    auth_user = AuthUser(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        tenant_id=user.tenant_id,
        role=user.role.code if user.role is not None else "member",
    )
    permission_codes = set()
    if user.role is not None:
        permission_codes.update(permission.code for permission in user.role.permissions)
    for role in user.roles:
        permission_codes.update(permission.code for permission in role.permissions)
    log_audit(
        db,
        action="login_success",
        entity_type="auth",
        entity_id=user.id,
        actor_user=user,
        metadata={"role": auth_user.role},
    )
    db.commit()
    return _issue_tokens(auth_user, sorted(permission_codes))


@router.post("/refresh", response_model=TokenPair)
def refresh(request: RefreshRequest, db: Session = Depends(get_db)) -> TokenPair:
    payload = decode_token(request.refresh_token, expected_type="refresh")
    email = str(payload.get("email"))
    user = _load_user(db, email)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unknown account")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is deactivated")

    auth_user = AuthUser(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        tenant_id=user.tenant_id,
        role=user.role.code if user.role is not None else "member",
    )
    permission_codes = set()
    if user.role is not None:
        permission_codes.update(permission.code for permission in user.role.permissions)
    for role in user.roles:
        permission_codes.update(permission.code for permission in role.permissions)
    return _issue_tokens(auth_user, sorted(permission_codes))


@router.get("/me", response_model=AuthUserResponse)
def me(current_user: AuthUserResponse = Depends(get_current_user)) -> AuthUserResponse:
    return current_user


@router.post("/logout")
def logout(
    request: LogoutRequest,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> dict[str, bool]:
    actor: User | None = None
    actor_email = "unknown@sbs.local"

    if authorization and authorization.startswith("Bearer "):
        try:
            payload = decode_token(authorization.removeprefix("Bearer ").strip(), expected_type="access")
            actor = db.scalar(select(User).where(User.id == str(payload.get("sub"))))
        except HTTPException:
            actor = None

    if actor is not None:
        actor_email = actor.email

    refresh_jti = None
    if request.refresh_token:
        try:
            refresh_payload = decode_token(request.refresh_token, expected_type="refresh")
            refresh_jti = str(refresh_payload.get("jti"))
            if actor is None:
                actor = _load_user(db, str(refresh_payload.get("email")))
                if actor is not None:
                    actor_email = actor.email
        except HTTPException:
            refresh_jti = None

    log_audit(
        db,
        action="logout_success",
        entity_type="auth",
        entity_id=actor.id if actor is not None else None,
        actor_user=actor,
        actor_email=actor_email,
        metadata={"refresh_jti": refresh_jti},
    )
    db.commit()
    return {"ok": True}
