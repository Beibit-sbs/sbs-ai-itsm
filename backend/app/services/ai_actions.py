from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
import re
from typing import Any
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.ai_actions import (
    AiActionExecution,
    AiActionProposal,
)
from app.models.knowledge_article import KnowledgeArticle
from app.models.knowledge_category import KnowledgeCategory
from app.models.runbook import Runbook
from app.models.ticket import Ticket
from app.models.ticket_history import TicketHistory
from app.services.ai_retrieval import detects_prompt_injection
from app.services.knowledge_ai import next_article_number


ACTION_SPECS = {
    "ticket.update": {
        "risk": "HIGH",
        "target_type": "ticket",
        "fields": {"category", "priority"},
    },
    "ticket.classify": {
        "risk": "MEDIUM",
        "target_type": "ticket",
        "fields": {"category", "priority"},
    },
    "knowledge.draft": {
        "risk": "MEDIUM",
        "target_type": "knowledge_article",
        "fields": {
            "title",
            "summary",
            "content",
            "category_id",
            "tags",
        },
    },
    "runbook.draft": {
        "risk": "MEDIUM",
        "target_type": "runbook",
        "fields": {
            "code",
            "title",
            "description",
            "category",
            "severity",
            "steps",
            "estimated_minutes",
        },
    },
}
_PRIORITIES = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
_SEVERITIES = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
_CODE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{2,119}$")
_CREDENTIAL_MARKERS = ("api_key", "password", "bearer ", "private key", "secret")


class AiActionError(ValueError):
    pass


def utcnow() -> datetime:
    return datetime.now(UTC)


def aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def digest(value: object) -> str:
    payload = value if isinstance(value, str) else canonical_json(value)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def json_value(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return fallback


def _all_strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [
            item
            for key, child in value.items()
            for item in [str(key), *_all_strings(child)]
        ]
    if isinstance(value, list):
        return [item for child in value for item in _all_strings(child)]
    return []


def validate_parameters(action_type: str, parameters: dict[str, Any]) -> dict[str, Any]:
    spec = ACTION_SPECS.get(action_type)
    if spec is None:
        raise AiActionError("Action type is not in the server allowlist")
    unexpected = set(parameters) - set(spec["fields"])
    if unexpected:
        raise AiActionError(
            "Parameters are not allowlisted: " + ", ".join(sorted(unexpected))
        )
    strings = _all_strings(parameters)
    if any(detects_prompt_injection(value) for value in strings):
        raise AiActionError("Action parameters contain prompt-injection instructions")
    serialized = canonical_json(parameters)
    if any(marker in serialized.lower() for marker in _CREDENTIAL_MARKERS):
        raise AiActionError("Action parameters contain credential-like data")
    if len(serialized) > 100_000:
        raise AiActionError("Action parameters exceed the size limit")
    if action_type in {"ticket.update", "ticket.classify"}:
        if not parameters or not set(parameters) <= {"category", "priority"}:
            raise AiActionError("Ticket proposal requires category and/or priority")
        if "category" in parameters:
            category = str(parameters["category"]).strip()
            if not 2 <= len(category) <= 120:
                raise AiActionError("Ticket category is invalid")
            parameters["category"] = category
        if "priority" in parameters:
            priority = str(parameters["priority"]).upper()
            if priority not in _PRIORITIES:
                raise AiActionError("Ticket priority is invalid")
            parameters["priority"] = priority
    elif action_type == "knowledge.draft":
        required = {"title", "summary", "content", "category_id"}
        if required - set(parameters):
            raise AiActionError("Knowledge draft is missing required fields")
        limits = {"title": 255, "summary": 2_000, "content": 50_000}
        for field, maximum in limits.items():
            value = str(parameters[field]).strip()
            if len(value) < 3 or len(value) > maximum:
                raise AiActionError(f"Knowledge {field} is invalid")
            parameters[field] = value
        tags = parameters.get("tags", [])
        if not isinstance(tags, list) or len(tags) > 30:
            raise AiActionError("Knowledge tags must be a list with at most 30 items")
        parameters["tags"] = [str(item).strip()[:80] for item in tags if str(item).strip()]
    else:
        required = {"code", "title", "category", "severity", "steps"}
        if required - set(parameters):
            raise AiActionError("Runbook draft is missing required fields")
        if not _CODE_RE.fullmatch(str(parameters["code"])):
            raise AiActionError("Runbook code is invalid")
        if str(parameters["severity"]).upper() not in _SEVERITIES:
            raise AiActionError("Runbook severity is invalid")
        steps = parameters["steps"]
        if not isinstance(steps, list) or not 1 <= len(steps) <= 50:
            raise AiActionError("Runbook requires 1 to 50 steps")
        normalized_steps = []
        for index, step in enumerate(steps, start=1):
            if not isinstance(step, dict) or set(step) - {"title", "instruction"}:
                raise AiActionError(f"Runbook step {index} schema is invalid")
            title = str(step.get("title") or "").strip()
            instruction = str(step.get("instruction") or "").strip()
            if not title or not instruction or len(instruction) > 4_000:
                raise AiActionError(f"Runbook step {index} content is invalid")
            normalized_steps.append({"title": title[:200], "instruction": instruction})
        parameters["steps"] = normalized_steps
        parameters["severity"] = str(parameters["severity"]).upper()
        minutes = int(parameters.get("estimated_minutes", 15))
        if not 1 <= minutes <= 1_440:
            raise AiActionError("Runbook estimated minutes are invalid")
        parameters["estimated_minutes"] = minutes
    return parameters


def ticket_state(ticket: Ticket) -> dict[str, Any]:
    return {
        "id": ticket.id,
        "tenant_id": ticket.tenant_id,
        "category": ticket.category,
        "priority": ticket.priority,
        "status": ticket.status,
        "updated_at": (
            ticket.updated_at.replace(tzinfo=UTC).isoformat()
            if ticket.updated_at and ticket.updated_at.tzinfo is None
            else ticket.updated_at.isoformat()
            if ticket.updated_at
            else None
        ),
    }


def target_fingerprint(db: Session, tenant_id: str, action_type: str, target_id: str | None) -> str | None:
    if action_type not in {"ticket.update", "ticket.classify"}:
        return None
    if not target_id:
        raise AiActionError("Ticket target_id is required")
    ticket = db.scalar(
        select(Ticket).where(Ticket.id == target_id, Ticket.tenant_id == tenant_id)
    )
    if ticket is None:
        raise AiActionError("Ticket target is unavailable")
    return digest(ticket_state(ticket))


def safe_citation_evidence(citations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(citations) > 20:
        raise AiActionError("At most 20 citations may support a proposal")
    result = []
    for citation in citations:
        required = {
            "citation_id",
            "source_type",
            "source_id",
            "content_sha256",
            "source_updated_at",
        }
        if required - set(citation):
            raise AiActionError("Citation evidence is incomplete")
        result.append({key: str(citation[key])[:200] for key in sorted(required)})
    return result


def execute_proposal(
    db: Session,
    proposal: AiActionProposal,
    *,
    actor_id: str,
    actor_name: str,
) -> AiActionExecution:
    existing = db.scalar(
        select(AiActionExecution).where(AiActionExecution.proposal_id == proposal.id)
    )
    if existing is not None:
        return existing
    if proposal.status != "APPROVED":
        raise AiActionError("Only approved proposals can be executed")
    if aware(proposal.expires_at) <= utcnow():
        proposal.status = "EXPIRED"
        raise AiActionError("Proposal has expired")
    parameters = json_value(proposal.parameters_json, {})
    if digest(parameters) != proposal.parameters_sha256:
        raise AiActionError("Proposal parameter integrity failed")
    parameters = validate_parameters(proposal.action_type, parameters)
    before: dict[str, Any] = {}
    after: dict[str, Any] = {}
    result: dict[str, Any] = {}
    target_id = proposal.target_id
    if proposal.action_type in {"ticket.update", "ticket.classify"}:
        statement = select(Ticket).where(
            Ticket.id == proposal.target_id,
            Ticket.tenant_id == proposal.tenant_id,
        )
        if db.get_bind().dialect.name == "postgresql":
            statement = statement.with_for_update()
        ticket = db.scalar(statement)
        if ticket is None:
            raise AiActionError("Ticket target is unavailable")
        before = ticket_state(ticket)
        if digest(before) != proposal.target_fingerprint:
            raise AiActionError("Ticket changed after proposal creation")
        for field in ("category", "priority"):
            if field in parameters:
                old_value = str(getattr(ticket, field))
                new_value = str(parameters[field])
                setattr(ticket, field, new_value)
                db.add(
                    TicketHistory(
                        id=str(uuid.uuid4()),
                        ticket_id=ticket.id,
                        actor_name=actor_name,
                        event_type="ai_guarded_action",
                        field_name=field,
                        old_value=old_value,
                        new_value=new_value,
                        message=f"Guarded AI proposal {proposal.proposal_number} applied.",
                    )
                )
        ticket.updated_at = utcnow()
        db.flush()
        after = ticket_state(ticket)
        result = {"ticket_id": ticket.id, "changed_fields": sorted(parameters)}
    elif proposal.action_type == "knowledge.draft":
        category = db.get(KnowledgeCategory, str(parameters["category_id"]))
        if category is None:
            raise AiActionError("Knowledge category is unavailable")
        article = KnowledgeArticle(
            id=str(uuid.uuid4()),
            tenant_id=proposal.tenant_id,
            article_number=next_article_number(db),
            title=parameters["title"],
            summary=parameters["summary"],
            content=parameters["content"],
            category_id=category.id,
            tags=", ".join(parameters["tags"]),
            tags_json=parameters["tags"],
            status="draft",
            visibility="internal",
            author_name=actor_name,
            created_by_id=actor_id,
            updated_by_id=actor_id,
            view_count=0,
            helpful_count=0,
            not_helpful_count=0,
        )
        db.add(article)
        db.flush()
        target_id = article.id
        after = {
            "id": article.id,
            "status": article.status,
            "content_sha256": digest(
                {
                    "title": article.title,
                    "summary": article.summary,
                    "content": article.content,
                }
            ),
        }
        result = {"article_id": article.id, "article_number": article.article_number}
    else:
        duplicate = db.scalar(
            select(Runbook.id).where(
                Runbook.tenant_id == proposal.tenant_id,
                Runbook.code == parameters["code"],
            )
        )
        if duplicate:
            raise AiActionError("Runbook code already exists")
        runbook = Runbook(
            id=str(uuid.uuid4()),
            tenant_id=proposal.tenant_id,
            name=parameters["title"],
            code=parameters["code"],
            title=parameters["title"],
            description=parameters.get("description"),
            category=parameters["category"],
            severity=parameters["severity"],
            steps_json=canonical_json(parameters["steps"]),
            estimated_minutes=parameters["estimated_minutes"],
            is_active=False,
            requires_approval=True,
            created_by_id=actor_id,
            updated_by_id=actor_id,
        )
        db.add(runbook)
        db.flush()
        target_id = runbook.id
        after = {
            "id": runbook.id,
            "code": runbook.code,
            "is_active": runbook.is_active,
            "content_sha256": digest(
                {
                    "title": runbook.title,
                    "description": runbook.description,
                    "steps_json": runbook.steps_json,
                }
            ),
        }
        result = {"runbook_id": runbook.id, "code": runbook.code}
    execution = AiActionExecution(
        id=str(uuid.uuid4()),
        tenant_id=proposal.tenant_id,
        proposal_id=proposal.id,
        action_type=proposal.action_type,
        status="SUCCEEDED",
        target_type=proposal.target_type,
        target_id=target_id,
        before_state_json=canonical_json(before),
        before_sha256=digest(before),
        after_state_json=canonical_json(after),
        after_sha256=digest(after),
        result_json=canonical_json(result),
    )
    db.add(execution)
    proposal.status = "EXECUTED"
    proposal.executed_by_id = actor_id
    proposal.executed_at = utcnow()
    return execution


def rollback_execution(
    db: Session,
    execution: AiActionExecution,
    proposal: AiActionProposal,
    *,
    actor_id: str,
    actor_name: str,
    reason: str,
) -> None:
    if execution.status != "SUCCEEDED" or proposal.status != "EXECUTED":
        raise AiActionError("Execution cannot be rolled back")
    before = json_value(execution.before_state_json, {})
    after = json_value(execution.after_state_json, {})
    if proposal.action_type in {"ticket.update", "ticket.classify"}:
        ticket = db.get(Ticket, execution.target_id)
        if ticket is None or ticket.tenant_id != proposal.tenant_id:
            raise AiActionError("Ticket target is unavailable")
        if digest(ticket_state(ticket)) != execution.after_sha256:
            raise AiActionError("Ticket changed after AI execution; automatic rollback refused")
        for field in ("category", "priority"):
            if field in before and getattr(ticket, field) != before[field]:
                old_value = str(getattr(ticket, field))
                setattr(ticket, field, before[field])
                db.add(
                    TicketHistory(
                        id=str(uuid.uuid4()),
                        ticket_id=ticket.id,
                        actor_name=actor_name,
                        event_type="ai_guarded_action_rollback",
                        field_name=field,
                        old_value=old_value,
                        new_value=str(before[field]),
                        message=f"Guarded AI proposal {proposal.proposal_number} rolled back.",
                    )
                )
        ticket.updated_at = utcnow()
    elif proposal.action_type == "knowledge.draft":
        article = db.get(KnowledgeArticle, execution.target_id)
        if article is None or article.tenant_id != proposal.tenant_id:
            raise AiActionError("Knowledge draft is unavailable")
        live_hash = digest(
            {"title": article.title, "summary": article.summary, "content": article.content}
        )
        if live_hash != after.get("content_sha256") or article.status != "draft":
            raise AiActionError("Knowledge draft changed; automatic rollback refused")
        article.status = "archived"
        article.archived_at = utcnow()
        article.updated_by_id = actor_id
    else:
        runbook = db.get(Runbook, execution.target_id)
        if runbook is None or runbook.tenant_id != proposal.tenant_id:
            raise AiActionError("Runbook draft is unavailable")
        live_hash = digest(
            {
                "title": runbook.title,
                "description": runbook.description,
                "steps_json": runbook.steps_json,
            }
        )
        if live_hash != after.get("content_sha256") or runbook.is_active:
            raise AiActionError("Runbook draft changed; automatic rollback refused")
        runbook.is_active = False
        runbook.updated_by_id = actor_id
    execution.status = "ROLLED_BACK"
    execution.rollback_reason = reason
    execution.rolled_back_by_id = actor_id
    execution.rolled_back_at = utcnow()
    proposal.status = "ROLLED_BACK"
