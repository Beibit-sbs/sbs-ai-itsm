from __future__ import annotations

import hashlib
import ipaddress
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from app.models.approval_request import ApprovalRequest
from app.models.asset import Asset
from app.models.auth_session import AuthSession
from app.models.change_governance import ChangeImplementationTask
from app.models.change_request import ChangeRequest
from app.models.identity_provisioning import (
    IdentityOwnershipTransfer,
    IdentityProvisioningConnector,
    ProvisionedGroup,
    ProvisionedGroupMember,
    ProvisionedIdentity,
)
from app.models.major_incident import MajorIncident
from app.models.problem import Problem
from app.models.problem_governance import ProblemCorrectiveAction
from app.models.release_governance import ReleaseRecord
from app.models.role import Role
from app.models.service_request import FulfillmentTask, RequestApproval
from app.models.ticket import Ticket
from app.models.user import User
from app.services.audit import log_audit


class IdentityLifecycleError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class OwnershipSummary:
    counts: dict[str, int]

    @property
    def total(self) -> int:
        return sum(self.counts.values())

    def as_dict(self) -> dict[str, object]:
        return {"counts": self.counts, "total": self.total}


def utcnow() -> datetime:
    return datetime.now(UTC)


def generate_connector_token() -> tuple[str, str, str]:
    token = f"sbs_scim_{secrets.token_urlsafe(40)}"
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return token, digest, token[-8:]


def hash_connector_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def connector_allows_ip(
    connector: IdentityProvisioningConnector,
    remote_ip: str | None,
) -> bool:
    configured = connector.allowed_ip_cidrs_json or []
    if not configured:
        return True
    if not remote_ip:
        return False
    try:
        address = ipaddress.ip_address(remote_ip)
    except ValueError:
        return False
    for raw_network in configured:
        try:
            if address in ipaddress.ip_network(raw_network, strict=False):
                return True
        except ValueError:
            continue
    return False


def _count(db: Session, model: type, *conditions: object) -> int:
    return int(
        db.scalar(select(func.count()).select_from(model).where(*conditions)) or 0
    )


def ownership_summary(db: Session, *, tenant_id: str, user: User) -> OwnershipSummary:
    if user.tenant_id != tenant_id:
        raise IdentityLifecycleError(
            "TENANT_MISMATCH",
            "Source user does not belong to the connector tenant",
        )
    active_major_statuses = {
        "DECLARED",
        "MITIGATING",
        "MONITORING",
        "RESOLVED",
    }
    counts = {
        "ticket_assignments": _count(
            db,
            Ticket,
            Ticket.tenant_id == tenant_id,
            Ticket.assignee_id == user.id,
        ),
        "problems": _count(
            db,
            Problem,
            Problem.tenant_id == tenant_id,
            Problem.owner_id == user.id,
        ),
        "changes": _count(
            db,
            ChangeRequest,
            ChangeRequest.tenant_id == tenant_id,
            ChangeRequest.owner_id == user.id,
        ),
        "releases": _count(
            db,
            ReleaseRecord,
            ReleaseRecord.tenant_id == tenant_id,
            ReleaseRecord.owner_id == user.id,
        ),
        "corrective_actions": _count(
            db,
            ProblemCorrectiveAction,
            ProblemCorrectiveAction.tenant_id == tenant_id,
            ProblemCorrectiveAction.owner_id == user.id,
        ),
        "implementation_tasks": _count(
            db,
            ChangeImplementationTask,
            ChangeImplementationTask.tenant_id == tenant_id,
            ChangeImplementationTask.owner_id == user.id,
        ),
        "fulfillment_tasks": _count(
            db,
            FulfillmentTask,
            FulfillmentTask.tenant_id == tenant_id,
            FulfillmentTask.assignee_id == user.id,
        ),
        "pending_approvals": _count(
            db,
            ApprovalRequest,
            ApprovalRequest.tenant_id == tenant_id,
            ApprovalRequest.approver_id == user.id,
            ApprovalRequest.status.in_(("PENDING", "REQUESTED")),
        ),
        "request_approvals": _count(
            db,
            RequestApproval,
            RequestApproval.tenant_id == tenant_id,
            RequestApproval.approver_id == user.id,
            RequestApproval.status == "PENDING",
        ),
        "asset_ownership": _count(
            db,
            Asset,
            Asset.tenant_id == tenant_id,
            Asset.owner_user_id == user.id,
        ),
        "asset_assignments": _count(
            db,
            Asset,
            Asset.tenant_id == tenant_id,
            func.lower(Asset.assigned_to_email) == user.email.lower(),
        ),
        "direct_reports": _count(
            db,
            User,
            User.tenant_id == tenant_id,
            User.manager_id == user.id,
            User.is_active.is_(True),
        ),
        "major_incident_commander": _count(
            db,
            MajorIncident,
            MajorIncident.tenant_id == tenant_id,
            MajorIncident.commander_user_id == user.id,
            MajorIncident.status.in_(active_major_statuses),
        ),
        "major_incident_comms_lead": _count(
            db,
            MajorIncident,
            MajorIncident.tenant_id == tenant_id,
            MajorIncident.communications_lead_user_id == user.id,
            MajorIncident.status.in_(active_major_statuses),
        ),
    }
    return OwnershipSummary(counts=counts)


def _execute_transfer(
    db: Session,
    *,
    model: type,
    tenant_column: object,
    tenant_id: str,
    source_column: object,
    source_value: object,
    values: dict[str, object],
    extra_conditions: tuple[object, ...] = (),
) -> int:
    result = db.execute(
        update(model)
        .where(
            tenant_column == tenant_id,
            source_column == source_value,
            *extra_conditions,
        )
        .values(**values)
    )
    return int(result.rowcount or 0)


def revoke_user_sessions(db: Session, user_id: str) -> int:
    now = utcnow()
    result = db.execute(
        update(AuthSession)
        .where(
            AuthSession.user_id == user_id,
            AuthSession.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )
    return int(result.rowcount or 0)


def synchronize_user_display_references(
    db: Session,
    *,
    user: User,
    previous_email: str | None = None,
) -> dict[str, int]:
    if user.tenant_id is None:
        return {}
    tenant_id = user.tenant_id
    counts = {
        "ticket_assignments": _execute_transfer(
            db,
            model=Ticket,
            tenant_column=Ticket.tenant_id,
            tenant_id=tenant_id,
            source_column=Ticket.assignee_id,
            source_value=user.id,
            values={"assignee_name": user.full_name},
        ),
        "problems": _execute_transfer(
            db,
            model=Problem,
            tenant_column=Problem.tenant_id,
            tenant_id=tenant_id,
            source_column=Problem.owner_id,
            source_value=user.id,
            values={"owner_name": user.full_name},
        ),
        "changes": _execute_transfer(
            db,
            model=ChangeRequest,
            tenant_column=ChangeRequest.tenant_id,
            tenant_id=tenant_id,
            source_column=ChangeRequest.owner_id,
            source_value=user.id,
            values={"owner_name": user.full_name},
        ),
        "releases": _execute_transfer(
            db,
            model=ReleaseRecord,
            tenant_column=ReleaseRecord.tenant_id,
            tenant_id=tenant_id,
            source_column=ReleaseRecord.owner_id,
            source_value=user.id,
            values={"owner_name": user.full_name},
        ),
        "corrective_actions": _execute_transfer(
            db,
            model=ProblemCorrectiveAction,
            tenant_column=ProblemCorrectiveAction.tenant_id,
            tenant_id=tenant_id,
            source_column=ProblemCorrectiveAction.owner_id,
            source_value=user.id,
            values={"owner_name": user.full_name},
        ),
        "implementation_tasks": _execute_transfer(
            db,
            model=ChangeImplementationTask,
            tenant_column=ChangeImplementationTask.tenant_id,
            tenant_id=tenant_id,
            source_column=ChangeImplementationTask.owner_id,
            source_value=user.id,
            values={"owner_name": user.full_name},
        ),
        "fulfillment_tasks": _execute_transfer(
            db,
            model=FulfillmentTask,
            tenant_column=FulfillmentTask.tenant_id,
            tenant_id=tenant_id,
            source_column=FulfillmentTask.assignee_id,
            source_value=user.id,
            values={"assignee_name": user.full_name},
        ),
        "pending_approvals": _execute_transfer(
            db,
            model=ApprovalRequest,
            tenant_column=ApprovalRequest.tenant_id,
            tenant_id=tenant_id,
            source_column=ApprovalRequest.approver_id,
            source_value=user.id,
            values={"approver_name": user.full_name},
            extra_conditions=(ApprovalRequest.status.in_(("PENDING", "REQUESTED")),),
        ),
        "request_approvals": _execute_transfer(
            db,
            model=RequestApproval,
            tenant_column=RequestApproval.tenant_id,
            tenant_id=tenant_id,
            source_column=RequestApproval.approver_id,
            source_value=user.id,
            values={
                "approver_name": user.full_name,
                "approver_email": user.email,
            },
            extra_conditions=(RequestApproval.status == "PENDING",),
        ),
        "asset_ownership": _execute_transfer(
            db,
            model=Asset,
            tenant_column=Asset.tenant_id,
            tenant_id=tenant_id,
            source_column=Asset.owner_user_id,
            source_value=user.id,
            values={"owner_name": user.full_name},
        ),
    }
    if previous_email:
        counts["asset_assignments"] = _execute_transfer(
            db,
            model=Asset,
            tenant_column=Asset.tenant_id,
            tenant_id=tenant_id,
            source_column=func.lower(Asset.assigned_to_email),
            source_value=previous_email.lower(),
            values={
                "assigned_to_email": user.email,
                "assigned_to_name": user.full_name,
            },
        )
    return counts


def transfer_user_ownership(
    db: Session,
    *,
    tenant_id: str,
    from_user: User,
    to_user: User,
    reason: str,
    initiated_by: User | None = None,
    provisioning_event_id: str | None = None,
    revoke_sessions: bool = True,
) -> IdentityOwnershipTransfer:
    if from_user.id == to_user.id:
        raise IdentityLifecycleError(
            "INVALID_FALLBACK_OWNER",
            "Fallback owner must be different from the departing user",
        )
    if from_user.tenant_id != tenant_id or to_user.tenant_id != tenant_id:
        raise IdentityLifecycleError(
            "TENANT_MISMATCH",
            "Both users must belong to the same tenant",
        )
    if not to_user.is_active:
        raise IdentityLifecycleError(
            "INACTIVE_FALLBACK_OWNER",
            "Fallback owner must be active",
        )
    if to_user.is_root:
        raise IdentityLifecycleError(
            "INVALID_FALLBACK_OWNER",
            "A tenant resource cannot be reassigned to a SaaS root user",
        )

    active_major_statuses = (
        "DECLARED",
        "MITIGATING",
        "MONITORING",
        "RESOLVED",
    )
    counts = {
        "ticket_assignments": _execute_transfer(
            db,
            model=Ticket,
            tenant_column=Ticket.tenant_id,
            tenant_id=tenant_id,
            source_column=Ticket.assignee_id,
            source_value=from_user.id,
            values={"assignee_id": to_user.id, "assignee_name": to_user.full_name},
        ),
        "problems": _execute_transfer(
            db,
            model=Problem,
            tenant_column=Problem.tenant_id,
            tenant_id=tenant_id,
            source_column=Problem.owner_id,
            source_value=from_user.id,
            values={"owner_id": to_user.id, "owner_name": to_user.full_name},
        ),
        "changes": _execute_transfer(
            db,
            model=ChangeRequest,
            tenant_column=ChangeRequest.tenant_id,
            tenant_id=tenant_id,
            source_column=ChangeRequest.owner_id,
            source_value=from_user.id,
            values={"owner_id": to_user.id, "owner_name": to_user.full_name},
        ),
        "releases": _execute_transfer(
            db,
            model=ReleaseRecord,
            tenant_column=ReleaseRecord.tenant_id,
            tenant_id=tenant_id,
            source_column=ReleaseRecord.owner_id,
            source_value=from_user.id,
            values={"owner_id": to_user.id, "owner_name": to_user.full_name},
        ),
        "corrective_actions": _execute_transfer(
            db,
            model=ProblemCorrectiveAction,
            tenant_column=ProblemCorrectiveAction.tenant_id,
            tenant_id=tenant_id,
            source_column=ProblemCorrectiveAction.owner_id,
            source_value=from_user.id,
            values={"owner_id": to_user.id, "owner_name": to_user.full_name},
        ),
        "implementation_tasks": _execute_transfer(
            db,
            model=ChangeImplementationTask,
            tenant_column=ChangeImplementationTask.tenant_id,
            tenant_id=tenant_id,
            source_column=ChangeImplementationTask.owner_id,
            source_value=from_user.id,
            values={"owner_id": to_user.id, "owner_name": to_user.full_name},
        ),
        "fulfillment_tasks": _execute_transfer(
            db,
            model=FulfillmentTask,
            tenant_column=FulfillmentTask.tenant_id,
            tenant_id=tenant_id,
            source_column=FulfillmentTask.assignee_id,
            source_value=from_user.id,
            values={"assignee_id": to_user.id, "assignee_name": to_user.full_name},
        ),
        "pending_approvals": _execute_transfer(
            db,
            model=ApprovalRequest,
            tenant_column=ApprovalRequest.tenant_id,
            tenant_id=tenant_id,
            source_column=ApprovalRequest.approver_id,
            source_value=from_user.id,
            values={"approver_id": to_user.id, "approver_name": to_user.full_name},
            extra_conditions=(ApprovalRequest.status.in_(("PENDING", "REQUESTED")),),
        ),
        "request_approvals": _execute_transfer(
            db,
            model=RequestApproval,
            tenant_column=RequestApproval.tenant_id,
            tenant_id=tenant_id,
            source_column=RequestApproval.approver_id,
            source_value=from_user.id,
            values={
                "approver_id": to_user.id,
                "approver_name": to_user.full_name,
                "approver_email": to_user.email,
            },
            extra_conditions=(RequestApproval.status == "PENDING",),
        ),
        "asset_ownership": _execute_transfer(
            db,
            model=Asset,
            tenant_column=Asset.tenant_id,
            tenant_id=tenant_id,
            source_column=Asset.owner_user_id,
            source_value=from_user.id,
            values={"owner_user_id": to_user.id, "owner_name": to_user.full_name},
        ),
        "asset_assignments": _execute_transfer(
            db,
            model=Asset,
            tenant_column=Asset.tenant_id,
            tenant_id=tenant_id,
            source_column=func.lower(Asset.assigned_to_email),
            source_value=from_user.email.lower(),
            values={
                "assigned_to_email": to_user.email,
                "assigned_to_name": to_user.full_name,
            },
        ),
        "direct_reports": _execute_transfer(
            db,
            model=User,
            tenant_column=User.tenant_id,
            tenant_id=tenant_id,
            source_column=User.manager_id,
            source_value=from_user.id,
            values={"manager_id": to_user.id},
            extra_conditions=(User.is_active.is_(True),),
        ),
        "major_incident_commander": _execute_transfer(
            db,
            model=MajorIncident,
            tenant_column=MajorIncident.tenant_id,
            tenant_id=tenant_id,
            source_column=MajorIncident.commander_user_id,
            source_value=from_user.id,
            values={"commander_user_id": to_user.id},
            extra_conditions=(MajorIncident.status.in_(active_major_statuses),),
        ),
        "major_incident_comms_lead": _execute_transfer(
            db,
            model=MajorIncident,
            tenant_column=MajorIncident.tenant_id,
            tenant_id=tenant_id,
            source_column=MajorIncident.communications_lead_user_id,
            source_value=from_user.id,
            values={"communications_lead_user_id": to_user.id},
            extra_conditions=(MajorIncident.status.in_(active_major_statuses),),
        ),
    }
    sessions_revoked = revoke_user_sessions(db, from_user.id) if revoke_sessions else 0
    transfer = IdentityOwnershipTransfer(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        from_user_id=from_user.id,
        to_user_id=to_user.id,
        provisioning_event_id=provisioning_event_id,
        reason=reason,
        transferred_counts_json=counts,
        sessions_revoked=sessions_revoked,
        status="COMPLETED",
        initiated_by_id=initiated_by.id if initiated_by else None,
        created_at=utcnow(),
    )
    db.add(transfer)
    log_audit(
        db,
        action="identity_ownership_transferred",
        entity_type="user",
        entity_id=from_user.id,
        actor_user=initiated_by,
        actor_email=initiated_by.email if initiated_by else "scim@sbs.local",
        tenant_id=tenant_id,
        metadata={
            "to_user_id": to_user.id,
            "reason": reason,
            "counts": counts,
            "sessions_revoked": sessions_revoked,
            "provisioning_event_id": provisioning_event_id,
        },
    )
    return transfer


def ensure_tenant_admin_continuity(
    db: Session,
    user: User,
    *,
    replacement_roles: list[Role] | None = None,
    deactivating: bool = False,
) -> None:
    if user.tenant_id is None or not user.is_active:
        return
    current_roles = list(user.roles)
    if user.role is not None and user.role not in current_roles:
        current_roles.append(user.role)
    if not any(role.code == "organization_admin" for role in current_roles):
        return
    if (
        not deactivating
        and replacement_roles is not None
        and any(role.code == "organization_admin" for role in replacement_roles)
    ):
        return

    admin_role = db.scalar(
        select(Role).where(
            Role.tenant_id == user.tenant_id,
            Role.code == "organization_admin",
        )
    )
    if admin_role is None:
        raise IdentityLifecycleError(
            "TENANT_ADMIN_ROLE_MISSING",
            "The tenant administrator system role is unavailable",
        )
    other_admin_id = db.scalar(
        select(User.id)
        .where(
            User.tenant_id == user.tenant_id,
            User.is_active.is_(True),
            User.id != user.id,
            or_(
                User.role_id == admin_role.id,
                User.roles.any(Role.id == admin_role.id),
            ),
        )
        .limit(1)
    )
    if other_admin_id is None:
        raise IdentityLifecycleError(
            "LAST_TENANT_ADMIN",
            (
                "At least one active organization administrator must remain; "
                "create or assign a replacement first"
            ),
        )


def deactivate_provisioned_user(
    db: Session,
    *,
    connector: IdentityProvisioningConnector,
    identity: ProvisionedIdentity,
    fallback_owner: User | None = None,
    reason: str,
    initiated_by: User | None = None,
    provisioning_event_id: str | None = None,
) -> IdentityOwnershipTransfer:
    user = db.get(User, identity.user_id)
    if user is None or user.tenant_id != connector.tenant_id:
        raise IdentityLifecycleError(
            "IDENTITY_USER_NOT_FOUND",
            "Provisioned identity is not linked to a valid tenant user",
        )
    if user.is_root or user.is_superuser:
        raise IdentityLifecycleError(
            "PROTECTED_USER",
            "Root and superuser accounts cannot be deprovisioned through SCIM",
        )
    ensure_tenant_admin_continuity(db, user, deactivating=True)
    target = fallback_owner or db.get(User, connector.fallback_owner_id)
    if target is None:
        raise IdentityLifecycleError(
            "FALLBACK_OWNER_NOT_FOUND",
            "Connector fallback owner was not found",
        )
    transfer = transfer_user_ownership(
        db,
        tenant_id=connector.tenant_id,
        from_user=user,
        to_user=target,
        reason=reason,
        initiated_by=initiated_by,
        provisioning_event_id=provisioning_event_id,
        revoke_sessions=True,
    )
    now = utcnow()
    user.is_active = False
    user.provisioning_state = "DEPROVISIONED"
    user.deactivated_at = now
    user.updated_at = now
    user.roles = []
    user.role_id = None
    identity.lifecycle_state = "DEPROVISIONED"
    identity.deprovisioned_at = now
    identity.last_synced_at = now
    identity.scim_version += 1
    log_audit(
        db,
        action="identity_deprovisioned",
        entity_type="provisioned_identity",
        entity_id=identity.id,
        actor_user=initiated_by,
        actor_email=initiated_by.email if initiated_by else "scim@sbs.local",
        tenant_id=connector.tenant_id,
        metadata={
            "external_id": identity.external_id,
            "user_id": user.id,
            "fallback_owner_id": target.id,
            "ownership_transfer_id": transfer.id,
        },
    )
    return transfer


def resolve_identity_manager(
    db: Session,
    *,
    connector: IdentityProvisioningConnector,
    identity: ProvisionedIdentity,
) -> None:
    user = db.get(User, identity.user_id)
    if user is None:
        return
    if not identity.manager_external_id:
        user.manager_id = None
        return
    manager_identity = db.scalar(
        select(ProvisionedIdentity).where(
            ProvisionedIdentity.connector_id == connector.id,
            or_(
                ProvisionedIdentity.external_id == identity.manager_external_id,
                ProvisionedIdentity.id == identity.manager_external_id,
            ),
            ProvisionedIdentity.lifecycle_state == "ACTIVE",
        )
    )
    if manager_identity is None or manager_identity.user_id == user.id:
        user.manager_id = None
        return
    user.manager_id = manager_identity.user_id


def resolve_pending_reports(
    db: Session,
    *,
    connector: IdentityProvisioningConnector,
    manager_identity: ProvisionedIdentity,
) -> int:
    reports = db.scalars(
        select(ProvisionedIdentity).where(
            ProvisionedIdentity.connector_id == connector.id,
            or_(
                ProvisionedIdentity.manager_external_id
                == manager_identity.external_id,
                ProvisionedIdentity.manager_external_id == manager_identity.id,
            ),
            ProvisionedIdentity.lifecycle_state == "ACTIVE",
        )
    ).all()
    changed = 0
    for report in reports:
        report_user = db.get(User, report.user_id)
        if report_user is not None and report_user.id != manager_identity.user_id:
            report_user.manager_id = manager_identity.user_id
            changed += 1
    return changed


def apply_identity_roles(
    db: Session,
    *,
    connector: IdentityProvisioningConnector,
    identity: ProvisionedIdentity,
) -> list[Role]:
    user = db.get(User, identity.user_id)
    if user is None:
        raise IdentityLifecycleError(
            "IDENTITY_USER_NOT_FOUND",
            "Provisioned identity user was not found",
        )
    mapped_role_ids = list(
        db.scalars(
            select(ProvisionedGroup.mapped_role_id)
            .join(
                ProvisionedGroupMember,
                ProvisionedGroupMember.group_id == ProvisionedGroup.id,
            )
            .where(
                ProvisionedGroupMember.identity_id == identity.id,
                ProvisionedGroup.is_active.is_(True),
                ProvisionedGroup.mapped_role_id.is_not(None),
            )
            .distinct()
        ).all()
    )
    role_ids = mapped_role_ids or [connector.default_role_id]
    roles = db.scalars(
        select(Role).where(
            Role.id.in_(role_ids),
            Role.tenant_id == connector.tenant_id,
        )
    ).all()
    if not roles:
        raise IdentityLifecycleError(
            "ROLE_MAPPING_INVALID",
            "No tenant role is available for the provisioned identity",
        )
    user.roles = roles
    user.role_id = roles[0].id
    return roles
