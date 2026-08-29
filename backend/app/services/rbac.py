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


def ticket_visibility_scopes(current_user: AuthUserResponse) -> frozenset[str]:
    if is_saas_root(current_user):
        return frozenset({"all"})
    scopes = {
        scope
        for scope in ("all", "assigned", "requester")
        if has_permission(current_user, f"tickets.scope.{scope}")
    }
    if has_permission(current_user, "tickets.assign"):
        scopes.add("all")
    elif has_permission(current_user, "tickets.self_assign"):
        scopes.add("assigned")
    return frozenset(scopes)


def is_ticket_requester_only(current_user: AuthUserResponse) -> bool:
    scopes = ticket_visibility_scopes(current_user)
    return "requester" in scopes and not scopes.intersection({"all", "assigned"})


def is_ticket_assigned_only(current_user: AuthUserResponse) -> bool:
    scopes = ticket_visibility_scopes(current_user)
    return "assigned" in scopes and "all" not in scopes


def ticket_requested_by_current(
    current_user: AuthUserResponse,
    ticket: Ticket,
) -> bool:
    return bool(
        ticket.requester_id == current_user.id
        or ticket.requester_email.lower() == current_user.email.lower()
    )


def ticket_assigned_to_current(
    current_user: AuthUserResponse,
    ticket: Ticket,
) -> bool:
    return bool(
        ticket.assignee_id == current_user.id
        or (
            ticket.assignee_name
            and ticket.assignee_name.lower() == current_user.full_name.lower()
        )
    )


def ticket_is_unassigned(ticket: Ticket) -> bool:
    return ticket.assignee_id is None and not (ticket.assignee_name or "").strip()


def can_read_ticket(current_user: AuthUserResponse, ticket: Ticket) -> bool:
    if not is_saas_root(current_user) and current_user.tenant_id != ticket.tenant_id:
        return False
    scopes = ticket_visibility_scopes(current_user)
    return bool(
        "all" in scopes
        or (
            "requester" in scopes
            and ticket_requested_by_current(current_user, ticket)
        )
        or (
            "assigned" in scopes
            and (
                ticket_assigned_to_current(current_user, ticket)
                or ticket_is_unassigned(ticket)
            )
        )
    )
