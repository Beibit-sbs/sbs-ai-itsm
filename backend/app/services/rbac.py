from __future__ import annotations

from fastapi import HTTPException, status

from app.api.v1.routes.auth import AuthUserResponse
from app.models.ticket import Ticket


def is_saas_root(current_user: AuthUserResponse) -> bool:
    return current_user.role == "saas_root"


def has_permission(current_user: AuthUserResponse, permission: str) -> bool:
    return is_saas_root(current_user) or permission in set(current_user.permissions)


def require_permissions(current_user: AuthUserResponse, *permissions: str) -> None:
    missing = [item for item in permissions if not has_permission(current_user, item)]
    if missing:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Missing permissions: {', '.join(missing)}")


def ensure_same_tenant_or_root(current_user: AuthUserResponse, tenant_id: str | None) -> None:
    if is_saas_root(current_user):
        return
    if current_user.tenant_id is None or tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tenant access denied")


def can_read_ticket(current_user: AuthUserResponse, ticket: Ticket) -> bool:
    if is_saas_root(current_user):
        return True
    if current_user.tenant_id != ticket.tenant_id:
        return False
    if current_user.role == "requester":
        return current_user.email.lower() == ticket.requester_email.lower()
    if current_user.role == "it_agent":
        if ticket.assignee_name and current_user.full_name.lower() == ticket.assignee_name.lower():
            return True
    return True
