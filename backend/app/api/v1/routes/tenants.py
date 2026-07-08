from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import decode_token
from app.db.session import get_db
from app.models.tenant import Tenant
from app.models.user import User

router = APIRouter(prefix="/tenants")


class TenantResponse(BaseModel):
    id: str
    name: str
    slug: str
    status: str
    description: str | None


@router.get("", response_model=list[TenantResponse])
def list_tenants(authorization: str | None = Header(default=None), db: Session = Depends(get_db)) -> list[TenantResponse]:
    token = decode_token(authorization.removeprefix("Bearer ").strip(), expected_type="access") if authorization and authorization.startswith("Bearer ") else None
    if token is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")

    user = db.scalar(select(User).where(User.id == str(token.get("sub"))))
    permission_codes = set()
    if user is not None and user.role is not None:
        permission_codes.update(permission.code for permission in user.role.permissions)
    if user is not None:
        for role in user.roles:
            permission_codes.update(permission.code for permission in role.permissions)

    if user is None or (not user.is_root and "tenant.read" not in permission_codes):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Root access required")

    tenants = db.scalars(select(Tenant).order_by(Tenant.name.asc())).all()
    return [
        TenantResponse(id=tenant.id, name=tenant.name, slug=tenant.slug, status=tenant.status, description=tenant.description)
        for tenant in tenants
    ]
