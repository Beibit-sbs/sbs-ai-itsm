from __future__ import annotations

from datetime import UTC, datetime, timedelta
import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field, HttpUrl
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.v1.routes.auth import AuthUserResponse, get_current_user
from app.db.session import get_db
from app.models.major_incident import (
    MajorIncident,
    MajorIncidentAction,
    MajorIncidentChildTicket,
    MajorIncidentPIR,
    MajorIncidentParticipant,
    MajorIncidentUpdate,
)
from app.models.ticket import Ticket
from app.models.user import User
from app.services.audit import log_audit
from app.services.rbac import is_saas_root, require_permissions
from app.services.teams_collaboration import queue_major_incident_event


router = APIRouter(prefix="/major-incidents")


class MajorIncidentDeclare(BaseModel):
    ticket_id: str
    severity: Literal["SEV1", "SEV2"]
    title: str = Field(min_length=3, max_length=255)
    executive_summary: str = Field(min_length=10, max_length=10_000)
    impact_statement: str = Field(min_length=10, max_length=10_000)
    affected_service: str = Field(min_length=2, max_length=200)
    customer_impact: str = Field(min_length=10, max_length=10_000)
    commander_user_id: str
    communications_lead_user_id: str
    war_room_url: HttpUrl | None = None
    conference_details: str | None = Field(default=None, max_length=5_000)
    child_ticket_ids: list[str] = Field(default_factory=list, max_length=500)


class MajorIncidentTimelineCreate(BaseModel):
    update_type: Literal[
        "STATUS_UPDATE",
        "STAKEHOLDER_COMMUNICATION",
        "TECHNICAL_EVENT",
        "DECISION",
        "MILESTONE",
    ]
    audience: Literal["INTERNAL", "STAKEHOLDERS", "PUBLIC"]
    message: str = Field(min_length=3, max_length=20_000)
    service_status: Literal[
        "MAJOR_OUTAGE",
        "PARTIAL_OUTAGE",
        "DEGRADED",
        "OPERATIONAL",
        "UNKNOWN",
    ] | None = None
    channel: str | None = Field(default=None, max_length=80)


class MajorIncidentTransition(BaseModel):
    expected_version: int = Field(ge=1)
    action: Literal[
        "START_MITIGATION",
        "MONITOR",
        "RESUME_MITIGATION",
        "RESOLVE",
        "CLOSE",
        "CANCEL",
    ]
    comment: str = Field(min_length=3, max_length=10_000)


class ParticipantCreate(BaseModel):
    role: Literal["TECHNICAL_LEAD", "SME", "SCRIBE", "STAKEHOLDER"]
    user_id: str | None = None
    display_name: str = Field(min_length=2, max_length=200)
    contact: str | None = Field(default=None, max_length=255)


class ChildTicketCreate(BaseModel):
    ticket_id: str


class PIRUpsert(BaseModel):
    expected_version: int | None = Field(default=None, ge=1)
    summary: str = Field(min_length=10, max_length=20_000)
    root_cause: str = Field(min_length=10, max_length=20_000)
    contributing_factors: str = Field(min_length=3, max_length=20_000)
    lessons_learned: str = Field(min_length=3, max_length=20_000)
    prevention_plan: str = Field(min_length=10, max_length=20_000)


class VersionRequest(BaseModel):
    expected_version: int = Field(ge=1)


class ActionCreate(BaseModel):
    title: str = Field(min_length=3, max_length=255)
    description: str = Field(min_length=3, max_length=10_000)
    owner_user_id: str
    due_at: datetime


class ActionUpdate(BaseModel):
    expected_version: int = Field(ge=1)
    action_status: Literal["OPEN", "IN_PROGRESS", "DONE", "CANCELLED"]
    completion_evidence: str | None = Field(default=None, max_length=10_000)


class ResponderResponse(BaseModel):
    id: str
    full_name: str
    position: str | None
    department: str | None


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _user(db: Session, user_id: str, tenant_id: str) -> User:
    user = db.get(User, user_id)
    if user is None or user.tenant_id != tenant_id or not user.is_active:
        raise HTTPException(status_code=422, detail="Incident role user is unavailable")
    return user


def _ticket(db: Session, ticket_id: str, tenant_id: str | None = None) -> Ticket:
    ticket = db.get(Ticket, ticket_id)
    if ticket is None or not ticket.tenant_id or (
        tenant_id and ticket.tenant_id != tenant_id
    ):
        raise HTTPException(status_code=404, detail="Ticket not found")
    return ticket


def _incident(
    db: Session,
    incident_id: str,
    current_user: AuthUserResponse,
    *,
    lock: bool = False,
) -> MajorIncident:
    statement = select(MajorIncident).where(MajorIncident.id == incident_id)
    if lock and db.get_bind().dialect.name == "postgresql":
        statement = statement.with_for_update()
    incident = db.scalar(statement)
    if incident is None or (
        not is_saas_root(current_user)
        and incident.tenant_id != current_user.tenant_id
    ):
        raise HTTPException(status_code=404, detail="Major incident not found")
    return incident


def _assert_version(actual: int, expected: int, subject: str) -> None:
    if actual != expected:
        raise HTTPException(
            status_code=409,
            detail=f"{subject} was updated; current version is {actual}",
        )


def _timeline(
    db: Session,
    incident: MajorIncident,
    current_user: AuthUserResponse,
    *,
    update_type: str,
    audience: str,
    message: str,
    service_status: str | None = None,
    channel: str | None = None,
) -> MajorIncidentUpdate:
    item = MajorIncidentUpdate(
        id=str(uuid.uuid4()),
        tenant_id=incident.tenant_id,
        major_incident_id=incident.id,
        update_type=update_type,
        audience=audience,
        message=message.strip(),
        service_status=service_status,
        channel=channel,
        actor_user_id=current_user.id,
        actor_name=current_user.full_name,
        created_at=_now(),
    )
    db.add(item)
    return item


def _audit(
    db: Session,
    request: Request,
    current_user: AuthUserResponse,
    incident: MajorIncident,
    action: str,
    metadata: dict[str, object],
) -> None:
    log_audit(
        db,
        action=action,
        entity_type="major_incident",
        entity_id=incident.id,
        actor_user=db.get(User, current_user.id),
        actor_email=current_user.email,
        tenant_id=incident.tenant_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        metadata={"major_number": incident.major_number, **metadata},
    )


def _response(db: Session, incident: MajorIncident) -> dict[str, Any]:
    ticket = db.get(Ticket, incident.ticket_id)
    commander = db.get(User, incident.commander_user_id)
    comms = db.get(User, incident.communications_lead_user_id)
    participants = db.scalars(
        select(MajorIncidentParticipant)
        .where(MajorIncidentParticipant.major_incident_id == incident.id)
        .order_by(MajorIncidentParticipant.created_at)
    ).all()
    child_links = db.scalars(
        select(MajorIncidentChildTicket).where(
            MajorIncidentChildTicket.major_incident_id == incident.id
        )
    ).all()
    children = [
        db.get(Ticket, link.ticket_id)
        for link in child_links
        if db.get(Ticket, link.ticket_id) is not None
    ]
    updates = db.scalars(
        select(MajorIncidentUpdate)
        .where(MajorIncidentUpdate.major_incident_id == incident.id)
        .order_by(MajorIncidentUpdate.created_at)
    ).all()
    pir = db.scalar(
        select(MajorIncidentPIR).where(
            MajorIncidentPIR.major_incident_id == incident.id
        )
    )
    actions = db.scalars(
        select(MajorIncidentAction)
        .where(MajorIncidentAction.major_incident_id == incident.id)
        .order_by(MajorIncidentAction.due_at)
    ).all()
    now = _now()
    return {
        "id": incident.id,
        "tenant_id": incident.tenant_id,
        "ticket_id": incident.ticket_id,
        "ticket_number": ticket.ticket_number if ticket else None,
        "major_number": incident.major_number,
        "severity": incident.severity,
        "status": incident.status,
        "title": incident.title,
        "executive_summary": incident.executive_summary,
        "impact_statement": incident.impact_statement,
        "affected_service": incident.affected_service,
        "service_status": incident.service_status,
        "customer_impact": incident.customer_impact,
        "war_room_url": incident.war_room_url,
        "conference_details": incident.conference_details,
        "commander_user_id": incident.commander_user_id,
        "commander_name": commander.full_name if commander else None,
        "communications_lead_user_id": incident.communications_lead_user_id,
        "communications_lead_name": comms.full_name if comms else None,
        "declared_by_id": incident.declared_by_id,
        "declared_at": incident.declared_at,
        "next_update_due_at": incident.next_update_due_at,
        "communication_overdue": (
            incident.status not in {"RESOLVED", "CLOSED", "CANCELLED"}
            and _aware(incident.next_update_due_at) < now
        ),
        "resolved_at": incident.resolved_at,
        "closed_at": incident.closed_at,
        "cancelled_at": incident.cancelled_at,
        "version": incident.version,
        "participants": [
            {
                "id": item.id,
                "role": item.role,
                "user_id": item.user_id,
                "display_name": item.display_name,
                "contact": item.contact,
                "created_at": item.created_at,
            }
            for item in participants
        ],
        "child_tickets": [
            {
                "id": item.id,
                "ticket_number": item.ticket_number,
                "title": item.title,
                "status": item.status,
                "priority": item.priority,
            }
            for item in children
        ],
        "updates": [
            {
                "id": item.id,
                "update_type": item.update_type,
                "audience": item.audience,
                "message": item.message,
                "service_status": item.service_status,
                "channel": item.channel,
                "actor_name": item.actor_name,
                "created_at": item.created_at,
            }
            for item in updates
        ],
        "pir": (
            {
                "id": pir.id,
                "status": pir.status,
                "summary": pir.summary,
                "root_cause": pir.root_cause,
                "contributing_factors": pir.contributing_factors,
                "lessons_learned": pir.lessons_learned,
                "prevention_plan": pir.prevention_plan,
                "prepared_by_id": pir.prepared_by_id,
                "approved_by_id": pir.approved_by_id,
                "approved_at": pir.approved_at,
                "version": pir.version,
            }
            if pir
            else None
        ),
        "actions": [
            {
                "id": item.id,
                "title": item.title,
                "description": item.description,
                "owner_user_id": item.owner_user_id,
                "owner_name": (
                    db.get(User, item.owner_user_id).full_name
                    if db.get(User, item.owner_user_id)
                    else None
                ),
                "due_at": item.due_at,
                "status": item.status,
                "completion_evidence": item.completion_evidence,
                "completed_at": item.completed_at,
                "overdue": (
                    item.status in {"OPEN", "IN_PROGRESS"}
                    and _aware(item.due_at) < now
                ),
                "version": item.version,
            }
            for item in actions
        ],
        "created_at": incident.created_at,
        "updated_at": incident.updated_at,
    }


@router.get("")
def list_major_incidents(
    incident_status: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: AuthUserResponse = Depends(get_current_user),
) -> list[dict[str, Any]]:
    require_permissions(current_user, "major_incidents.read")
    statement = select(MajorIncident)
    if not is_saas_root(current_user):
        statement = statement.where(
            MajorIncident.tenant_id == current_user.tenant_id
        )
    if incident_status and incident_status != "ALL":
        statement = statement.where(MajorIncident.status == incident_status)
    incidents = db.scalars(
        statement.order_by(MajorIncident.declared_at.desc()).limit(limit)
    ).all()
    return [_response(db, item) for item in incidents]


@router.get("/summary")
def major_incident_summary(
    db: Session = Depends(get_db),
    current_user: AuthUserResponse = Depends(get_current_user),
) -> dict[str, int]:
    require_permissions(current_user, "major_incidents.read")
    statement = select(MajorIncident)
    if not is_saas_root(current_user):
        statement = statement.where(
            MajorIncident.tenant_id == current_user.tenant_id
        )
    rows = db.scalars(statement).all()
    now = _now()
    return {
        "active": sum(
            item.status not in {"RESOLVED", "CLOSED", "CANCELLED"}
            for item in rows
        ),
        "sev1_active": sum(
            item.severity == "SEV1"
            and item.status not in {"RESOLVED", "CLOSED", "CANCELLED"}
            for item in rows
        ),
        "communications_overdue": sum(
            item.status not in {"RESOLVED", "CLOSED", "CANCELLED"}
            and _aware(item.next_update_due_at) < now
            for item in rows
        ),
        "resolved_awaiting_pir": sum(
            item.status == "RESOLVED"
            and db.scalar(
                select(func.count(MajorIncidentPIR.id)).where(
                    MajorIncidentPIR.major_incident_id == item.id,
                    MajorIncidentPIR.status == "APPROVED",
                )
            )
            == 0
            for item in rows
        ),
    }


@router.get("/responders", response_model=list[ResponderResponse])
def list_major_incident_responders(
    ticket_id: str | None = None,
    db: Session = Depends(get_db),
    current_user: AuthUserResponse = Depends(get_current_user),
) -> list[ResponderResponse]:
    require_permissions(current_user, "major_incidents.read")
    tenant_id = current_user.tenant_id
    if is_saas_root(current_user) and ticket_id:
        tenant_id = _ticket(db, ticket_id).tenant_id
    if not tenant_id:
        return []
    users = db.scalars(
        select(User)
        .where(
            User.tenant_id == tenant_id,
            User.is_active.is_(True),
        )
        .order_by(User.full_name)
        .limit(1_000)
    ).all()
    return [
        ResponderResponse(
            id=item.id,
            full_name=item.full_name,
            position=item.position,
            department=item.department,
        )
        for item in users
    ]


@router.post("", status_code=status.HTTP_201_CREATED)
def declare_major_incident(
    payload: MajorIncidentDeclare,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AuthUserResponse = Depends(get_current_user),
) -> dict[str, Any]:
    require_permissions(current_user, "major_incidents.read", "major_incidents.manage")
    ticket = _ticket(db, payload.ticket_id)
    if not is_saas_root(current_user) and ticket.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="Ticket not found")
    if db.scalar(
        select(MajorIncident.id).where(MajorIncident.ticket_id == ticket.id)
    ):
        raise HTTPException(status_code=409, detail="Ticket is already a major incident")
    commander = _user(db, payload.commander_user_id, ticket.tenant_id)
    comms = _user(db, payload.communications_lead_user_id, ticket.tenant_id)
    children = list(dict.fromkeys(payload.child_ticket_ids))
    for child_id in children:
        if child_id == ticket.id:
            raise HTTPException(status_code=422, detail="Parent ticket cannot be a child")
        _ticket(db, child_id, ticket.tenant_id)
    now = _now()
    incident = MajorIncident(
        id=str(uuid.uuid4()),
        tenant_id=ticket.tenant_id,
        ticket_id=ticket.id,
        major_number=f"MI-{now.year}-{uuid.uuid4().hex[:8].upper()}",
        severity=payload.severity,
        status="DECLARED",
        title=payload.title.strip(),
        executive_summary=payload.executive_summary.strip(),
        impact_statement=payload.impact_statement.strip(),
        affected_service=payload.affected_service.strip(),
        service_status="MAJOR_OUTAGE",
        customer_impact=payload.customer_impact.strip(),
        war_room_url=str(payload.war_room_url) if payload.war_room_url else None,
        conference_details=(
            payload.conference_details.strip()
            if payload.conference_details
            else None
        ),
        commander_user_id=commander.id,
        communications_lead_user_id=comms.id,
        declared_by_id=current_user.id,
        declared_at=now,
        next_update_due_at=now + timedelta(
            minutes=30 if payload.severity == "SEV1" else 60
        ),
        version=1,
        created_at=now,
        updated_at=now,
    )
    db.add(incident)
    db.flush()
    for child_id in children:
        db.add(
            MajorIncidentChildTicket(
                id=str(uuid.uuid4()),
                tenant_id=incident.tenant_id,
                major_incident_id=incident.id,
                ticket_id=child_id,
                linked_by_id=current_user.id,
                created_at=now,
            )
        )
    _timeline(
        db,
        incident,
        current_user,
        update_type="MILESTONE",
        audience="INTERNAL",
        message=(
            f"{payload.severity} major incident declared. "
            f"Commander: {commander.full_name}; communications: {comms.full_name}."
        ),
        service_status=incident.service_status,
    )
    _audit(
        db,
        request,
        current_user,
        incident,
        "major_incident.declared",
        {"ticket_id": ticket.id, "severity": incident.severity},
    )
    queue_major_incident_event(
        db,
        incident=incident,
        event_type="major_incident.declared",
        detail="Major incident response room opened.",
        actor_user_id=current_user.id,
    )
    db.commit()
    db.refresh(incident)
    return _response(db, incident)


@router.get("/{incident_id}")
def get_major_incident(
    incident_id: str,
    db: Session = Depends(get_db),
    current_user: AuthUserResponse = Depends(get_current_user),
) -> dict[str, Any]:
    require_permissions(current_user, "major_incidents.read")
    return _response(db, _incident(db, incident_id, current_user))


@router.post("/{incident_id}/updates")
def add_major_incident_update(
    incident_id: str,
    payload: MajorIncidentTimelineCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AuthUserResponse = Depends(get_current_user),
) -> dict[str, Any]:
    require_permissions(current_user, "tickets.comment")
    incident = _incident(db, incident_id, current_user, lock=True)
    if incident.status in {"CLOSED", "CANCELLED"}:
        raise HTTPException(status_code=409, detail="Major incident is closed")
    if payload.audience != "INTERNAL" and not payload.channel:
        raise HTTPException(
            status_code=422,
            detail="channel is required for stakeholder/public communications",
        )
    _timeline(
        db,
        incident,
        current_user,
        update_type=payload.update_type,
        audience=payload.audience,
        message=payload.message,
        service_status=payload.service_status,
        channel=payload.channel,
    )
    if payload.service_status:
        incident.service_status = payload.service_status
    if payload.update_type in {"STATUS_UPDATE", "STAKEHOLDER_COMMUNICATION"}:
        incident.next_update_due_at = _now() + timedelta(
            minutes=30 if incident.severity == "SEV1" else 60
        )
    incident.version += 1
    incident.updated_at = _now()
    _audit(
        db,
        request,
        current_user,
        incident,
        "major_incident.update_published",
        {"audience": payload.audience, "channel": payload.channel or "internal"},
    )
    queue_major_incident_event(
        db,
        incident=incident,
        event_type="major_incident.update",
        detail=(
            f"Published {payload.update_type.lower()} update "
            f"for {payload.audience.lower()} audience."
        ),
        actor_user_id=current_user.id,
    )
    db.commit()
    db.refresh(incident)
    return _response(db, incident)


@router.post("/{incident_id}/transitions")
def transition_major_incident(
    incident_id: str,
    payload: MajorIncidentTransition,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AuthUserResponse = Depends(get_current_user),
) -> dict[str, Any]:
    require_permissions(current_user, "tickets.close")
    incident = _incident(db, incident_id, current_user, lock=True)
    _assert_version(incident.version, payload.expected_version, "Major incident")
    transitions = {
        ("DECLARED", "START_MITIGATION"): "MITIGATING",
        ("MITIGATING", "MONITOR"): "MONITORING",
        ("MONITORING", "RESUME_MITIGATION"): "MITIGATING",
        ("MONITORING", "RESOLVE"): "RESOLVED",
        ("MITIGATING", "RESOLVE"): "RESOLVED",
        ("RESOLVED", "CLOSE"): "CLOSED",
    }
    if payload.action == "CANCEL" and incident.status not in {
        "RESOLVED",
        "CLOSED",
        "CANCELLED",
    }:
        next_status = "CANCELLED"
    else:
        next_status = transitions.get((incident.status, payload.action))
    if not next_status:
        raise HTTPException(status_code=409, detail="Invalid major incident transition")
    if next_status == "CLOSED":
        pir = db.scalar(
            select(MajorIncidentPIR).where(
                MajorIncidentPIR.major_incident_id == incident.id,
                MajorIncidentPIR.status == "APPROVED",
            )
        )
        if pir is None:
            raise HTTPException(
                status_code=409,
                detail="Approved post-incident review is required before closure",
            )
    previous = incident.status
    incident.status = next_status
    incident.version += 1
    incident.updated_at = _now()
    if next_status == "RESOLVED":
        incident.resolved_at = _now()
        incident.service_status = "OPERATIONAL"
    elif next_status == "CLOSED":
        incident.closed_at = _now()
    elif next_status == "CANCELLED":
        incident.cancelled_at = _now()
    _timeline(
        db,
        incident,
        current_user,
        update_type="MILESTONE",
        audience="INTERNAL",
        message=payload.comment,
        service_status=incident.service_status,
    )
    _audit(
        db,
        request,
        current_user,
        incident,
        "major_incident.transitioned",
        {"from": previous, "to": next_status, "action": payload.action},
    )
    queue_major_incident_event(
        db,
        incident=incident,
        event_type="major_incident.transitioned",
        detail=f"State changed from {previous} to {next_status}.",
        actor_user_id=current_user.id,
    )
    db.commit()
    db.refresh(incident)
    return _response(db, incident)


@router.post("/{incident_id}/participants", status_code=status.HTTP_201_CREATED)
def add_major_incident_participant(
    incident_id: str,
    payload: ParticipantCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AuthUserResponse = Depends(get_current_user),
) -> dict[str, Any]:
    require_permissions(current_user, "major_incidents.read", "major_incidents.manage")
    incident = _incident(db, incident_id, current_user)
    user = _user(db, payload.user_id, incident.tenant_id) if payload.user_id else None
    db.add(
        MajorIncidentParticipant(
            id=str(uuid.uuid4()),
            tenant_id=incident.tenant_id,
            major_incident_id=incident.id,
            role=payload.role,
            user_id=user.id if user else None,
            display_name=user.full_name if user else payload.display_name.strip(),
            contact=payload.contact.strip() if payload.contact else None,
            added_by_id=current_user.id,
            created_at=_now(),
        )
    )
    _audit(
        db,
        request,
        current_user,
        incident,
        "major_incident.participant_added",
        {"role": payload.role, "user_id": payload.user_id},
    )
    db.commit()
    db.refresh(incident)
    return _response(db, incident)


@router.post("/{incident_id}/children", status_code=status.HTTP_201_CREATED)
def link_major_incident_child(
    incident_id: str,
    payload: ChildTicketCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AuthUserResponse = Depends(get_current_user),
) -> dict[str, Any]:
    require_permissions(current_user, "major_incidents.read", "major_incidents.manage")
    incident = _incident(db, incident_id, current_user)
    if payload.ticket_id == incident.ticket_id:
        raise HTTPException(status_code=422, detail="Parent ticket cannot be a child")
    _ticket(db, payload.ticket_id, incident.tenant_id)
    db.add(
        MajorIncidentChildTicket(
            id=str(uuid.uuid4()),
            tenant_id=incident.tenant_id,
            major_incident_id=incident.id,
            ticket_id=payload.ticket_id,
            linked_by_id=current_user.id,
            created_at=_now(),
        )
    )
    _audit(
        db,
        request,
        current_user,
        incident,
        "major_incident.child_linked",
        {"ticket_id": payload.ticket_id},
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Ticket is already linked to a major incident",
        ) from exc
    db.refresh(incident)
    return _response(db, incident)


@router.put("/{incident_id}/pir")
def upsert_major_incident_pir(
    incident_id: str,
    payload: PIRUpsert,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AuthUserResponse = Depends(get_current_user),
) -> dict[str, Any]:
    require_permissions(current_user, "major_incidents.read", "major_incidents.manage")
    incident = _incident(db, incident_id, current_user)
    pir = db.scalar(
        select(MajorIncidentPIR).where(
            MajorIncidentPIR.major_incident_id == incident.id
        )
    )
    now = _now()
    if pir is None:
        if payload.expected_version is not None:
            raise HTTPException(status_code=409, detail="PIR does not exist")
        pir = MajorIncidentPIR(
            id=str(uuid.uuid4()),
            tenant_id=incident.tenant_id,
            major_incident_id=incident.id,
            status="DRAFT",
            prepared_by_id=current_user.id,
            version=1,
            created_at=now,
            updated_at=now,
            **payload.model_dump(exclude={"expected_version"}),
        )
        db.add(pir)
    else:
        if pir.status == "APPROVED":
            raise HTTPException(status_code=409, detail="Approved PIR is immutable")
        if payload.expected_version is None:
            raise HTTPException(status_code=422, detail="expected_version is required")
        _assert_version(pir.version, payload.expected_version, "PIR")
        for key, value in payload.model_dump(
            exclude={"expected_version"}
        ).items():
            setattr(pir, key, value.strip())
        pir.prepared_by_id = current_user.id
        pir.version += 1
        pir.updated_at = now
    _audit(db, request, current_user, incident, "major_incident.pir_saved", {})
    db.commit()
    db.refresh(incident)
    return _response(db, incident)


@router.post("/{incident_id}/pir/approve")
def approve_major_incident_pir(
    incident_id: str,
    payload: VersionRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AuthUserResponse = Depends(get_current_user),
) -> dict[str, Any]:
    require_permissions(current_user, "tickets.close")
    incident = _incident(db, incident_id, current_user)
    if incident.status != "RESOLVED":
        raise HTTPException(status_code=409, detail="Incident must be resolved first")
    pir = db.scalar(
        select(MajorIncidentPIR).where(
            MajorIncidentPIR.major_incident_id == incident.id
        )
    )
    if pir is None:
        raise HTTPException(status_code=404, detail="PIR not found")
    _assert_version(pir.version, payload.expected_version, "PIR")
    if pir.prepared_by_id == current_user.id:
        raise HTTPException(status_code=403, detail="PIR requires independent approval")
    pir.status = "APPROVED"
    pir.approved_by_id = current_user.id
    pir.approved_at = _now()
    pir.version += 1
    pir.updated_at = _now()
    _audit(db, request, current_user, incident, "major_incident.pir_approved", {})
    db.commit()
    db.refresh(incident)
    return _response(db, incident)


@router.post("/{incident_id}/actions", status_code=status.HTTP_201_CREATED)
def create_major_incident_action(
    incident_id: str,
    payload: ActionCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AuthUserResponse = Depends(get_current_user),
) -> dict[str, Any]:
    require_permissions(current_user, "major_incidents.read", "major_incidents.manage")
    incident = _incident(db, incident_id, current_user)
    owner = _user(db, payload.owner_user_id, incident.tenant_id)
    if _aware(payload.due_at) <= _now():
        raise HTTPException(status_code=422, detail="Action due date must be future")
    db.add(
        MajorIncidentAction(
            id=str(uuid.uuid4()),
            tenant_id=incident.tenant_id,
            major_incident_id=incident.id,
            title=payload.title.strip(),
            description=payload.description.strip(),
            owner_user_id=owner.id,
            due_at=_aware(payload.due_at),
            status="OPEN",
            version=1,
            created_at=_now(),
            updated_at=_now(),
        )
    )
    _audit(
        db,
        request,
        current_user,
        incident,
        "major_incident.action_created",
        {"owner_user_id": owner.id, "title": payload.title.strip()},
    )
    db.commit()
    db.refresh(incident)
    return _response(db, incident)


@router.patch("/{incident_id}/actions/{action_id}")
def update_major_incident_action(
    incident_id: str,
    action_id: str,
    payload: ActionUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AuthUserResponse = Depends(get_current_user),
) -> dict[str, Any]:
    require_permissions(current_user, "major_incidents.read", "major_incidents.manage")
    incident = _incident(db, incident_id, current_user)
    action = db.scalar(
        select(MajorIncidentAction).where(
            MajorIncidentAction.id == action_id,
            MajorIncidentAction.major_incident_id == incident.id,
        )
    )
    if action is None:
        raise HTTPException(status_code=404, detail="Action not found")
    _assert_version(action.version, payload.expected_version, "Action")
    evidence = (payload.completion_evidence or "").strip()
    if payload.action_status == "DONE" and len(evidence) < 3:
        raise HTTPException(
            status_code=422,
            detail="completion_evidence is required",
        )
    action.status = payload.action_status
    action.completion_evidence = evidence or None
    action.completed_at = _now() if payload.action_status == "DONE" else None
    action.version += 1
    action.updated_at = _now()
    _audit(
        db,
        request,
        current_user,
        incident,
        "major_incident.action_updated",
        {"action_id": action.id, "status": action.status},
    )
    db.commit()
    db.refresh(incident)
    return _response(db, incident)
