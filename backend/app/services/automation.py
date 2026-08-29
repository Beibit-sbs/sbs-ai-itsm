from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.models.approval_request import ApprovalRequest
from app.models.automation_action_log import AutomationActionLog
from app.models.automation_rule import AutomationRule
from app.models.automation_run import AutomationRun
from app.models.email_message_log import EmailMessageLog
from app.models.knowledge_article import KnowledgeArticle
from app.models.notification import Notification
from app.models.runbook import Runbook
from app.models.runbook_execution import RunbookExecution
from app.models.ticket import Ticket
from app.models.ticket_comment import TicketComment
from app.models.ticket_history import TicketHistory
from app.models.user import User
from app.services.audit import log_audit
from app.services.integrations.providers import create_integration_event
from app.services.ticket_lifecycle import (
    TicketLifecycleError,
    canonical_ticket_status,
    transition_ticket_status,
)


logger = logging.getLogger("app.services.automation")


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(UTC)


def _json_dump(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, default=str)


def _json_load_object(payload: str | None, fallback: Any) -> Any:
    if not payload:
        return fallback
    try:
        value = json.loads(payload)
    except json.JSONDecodeError:
        return fallback
    return value


def _ci_text(value: Any) -> str:
    return str(value or "").lower()


def _bounded_text(value: Any, default: str, max_length: int) -> str:
    normalized = str(value if value is not None else default).strip()
    return (normalized or default)[:max_length]


SAFE_ACTION_TYPES = {
    "assign_ticket",
    "change_ticket_priority",
    "add_ticket_comment",
    "transition_ticket_status",
    "notify_assignee",
    "notify_sla_risk",
    "escalate_ticket",
    "create_manager_notification",
    "assign_asset_responsible",
    "request_asset_verification",
    "notify_asset_owner",
    "suggest_knowledge_article",
    "create_draft_article_from_ticket",
    "create_notification",
    "send_mock_email",
    "notify_role",
    "run_saved_report",
    "export_report_mock",
    "create_security_notification",
    "require_admin_review",
}

DANGEROUS_ACTION_TYPES = {
    "close_ticket",
    "dispose_asset",
    "change_priority_critical",
    "bulk_update",
    "retry_failed_integration",
    "security_action",
}


def _get_context_value(context: dict[str, Any], path: str) -> Any:
    current: Any = context
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
            continue
        return None
    return current


def _rule_scope(statement: Select, tenant_id: str | None) -> Select:
    if tenant_id is None:
        return statement
    return statement.where((AutomationRule.tenant_id == tenant_id) | (AutomationRule.tenant_id.is_(None)))


def _as_user(db: Session, actor_email: str | None, tenant_id: str | None) -> User | None:
    if not actor_email:
        return None
    statement = select(User).where(User.email == actor_email)
    if tenant_id is not None:
        statement = statement.where((User.tenant_id == tenant_id) | (User.tenant_id.is_(None)))
    return db.scalar(statement)


def build_ticket_context(ticket: Ticket) -> dict[str, Any]:
    return {
        "ticket": {
            "id": ticket.id,
            "title": ticket.title,
            "description": ticket.description,
            "category": ticket.category,
            "priority": ticket.priority,
            "status": ticket.status,
            "sla_status": ticket.sla_status,
            "assignee_name": ticket.assignee_name,
            "requester_email": ticket.requester_email,
            "requester_name": ticket.requester_name,
        },
        "entity_type": "ticket",
        "entity_id": ticket.id,
    }


class AutomationEngine:
    @staticmethod
    def create_run(
        db: Session,
        *,
        rule: AutomationRule,
        trigger_type: str,
        trigger_entity_type: str | None,
        trigger_entity_id: str | None,
    ) -> AutomationRun:
        run = AutomationRun(
            id=_uuid(),
            tenant_id=rule.tenant_id,
            rule_id=rule.id,
            trigger_type=trigger_type,
            trigger_entity_type=trigger_entity_type,
            trigger_entity_id=trigger_entity_id,
            status="running",
            started_at=_now(),
            created_at=_now(),
        )
        db.add(run)
        db.flush()
        return run

    @staticmethod
    def log_action(
        db: Session,
        *,
        run: AutomationRun,
        action_type: str,
        status: str,
        input_payload: dict[str, Any] | None,
        output_payload: dict[str, Any] | None,
        error_message: str | None = None,
    ) -> AutomationActionLog:
        item = AutomationActionLog(
            id=_uuid(),
            tenant_id=run.tenant_id,
            automation_run_id=run.id,
            execution_id=run.id,
            action_type=action_type,
            action_payload_json=_json_dump(input_payload or {}),
            status=status,
            result_payload_json=_json_dump(output_payload or {}),
            input_json=_json_dump(input_payload or {}),
            output_json=_json_dump(output_payload or {}),
            error_message=error_message,
            created_at=_now(),
        )
        db.add(item)
        return item

    @staticmethod
    def evaluate_conditions(rule: AutomationRule, context: dict[str, Any]) -> bool:
        return evaluate_conditions(rule, context)

    @staticmethod
    def dry_run_rule(rule: AutomationRule, context: dict[str, Any]) -> dict[str, Any]:
        actions = _json_load_object(rule.actions_json, [])
        if not isinstance(actions, list):
            actions = []
        return {
            "rule_id": rule.id,
            "rule_code": rule.code,
            "rule_name": rule.name,
            "trigger_type": rule.trigger_type,
            "matched": evaluate_conditions(rule, context),
            "planned_actions": actions,
            "mode": "dry_run",
        }

    @staticmethod
    def evaluate_rules(
        db: Session,
        *,
        tenant_id: str | None,
        trigger_type: str,
        context: dict[str, Any],
        actor_email: str | None = None,
    ) -> list[AutomationRun]:
        return evaluate_rules(db, tenant_id=tenant_id, trigger_type=trigger_type, context=context, actor_email=actor_email)

    @staticmethod
    def suggest_runbooks_for_ticket(db: Session, ticket: Ticket, tenant_id: str | None) -> dict[str, Any]:
        return suggest_runbooks_for_ticket(db, ticket, tenant_id)


def evaluate_conditions(rule: AutomationRule, context: dict[str, Any]) -> bool:
    raw_conditions = _json_load_object(rule.conditions_json, [])
    if raw_conditions in (None, {}, []):
        return True

    mode = "all"
    conditions: list[dict[str, Any]]
    if isinstance(raw_conditions, dict):
        mode = str(raw_conditions.get("mode", "all")).lower()
        conditions = raw_conditions.get("conditions", [])
        if "any" in raw_conditions:
            mode = "any"
            conditions = raw_conditions.get("any", [])
        if "all" in raw_conditions:
            mode = "all"
            conditions = raw_conditions.get("all", [])
    elif isinstance(raw_conditions, list):
        conditions = raw_conditions
    else:
        return False

    if not isinstance(conditions, list):
        return False
    if not conditions:
        return True

    results: list[bool] = []
    for item in conditions:
        if not isinstance(item, dict):
            results.append(False)
            continue
        path = str(item.get("path", "")).strip()
        op = str(item.get("operator", "eq")).lower().strip()
        expected = item.get("value")
        if not path:
            results.append(False)
            continue
        actual = _get_context_value(context, path)
        if op in {"eq", "=="}:
            passed = _ci_text(actual) == _ci_text(expected)
        elif op in {"contains", "includes"}:
            passed = _ci_text(expected) in _ci_text(actual)
        elif op in {"gte", ">="}:
            try:
                passed = float(actual) >= float(expected)
            except (TypeError, ValueError):
                passed = False
        elif op in {"lte", "<="}:
            try:
                passed = float(actual) <= float(expected)
            except (TypeError, ValueError):
                passed = False
        elif op == "in":
            if not isinstance(expected, list):
                passed = False
            else:
                passed = _ci_text(actual) in {_ci_text(value) for value in expected}
        else:
            passed = False
        results.append(passed)

    return any(results) if mode == "any" else all(results)


def _status(value: str) -> str:
    return value.strip().lower()


def _context_ticket(
    db: Session,
    context: dict[str, Any],
    tenant_id: str | None,
) -> Ticket | None:
    ticket_id = _get_context_value(context, "ticket.id") or context.get("ticket_id")
    if not ticket_id:
        return None
    statement = select(Ticket).where(Ticket.id == str(ticket_id))
    if tenant_id is not None:
        statement = statement.where(Ticket.tenant_id == tenant_id)
    return db.scalar(statement.with_for_update())


def execute_action(
    db: Session,
    action: dict[str, Any],
    context: dict[str, Any],
    dry_run: bool = False,
    *,
    tenant_id: str | None = None,
    current_user: User | None = None,
) -> dict[str, Any]:
    action_type = _bounded_text(action.get("type"), "", 80)
    ticket = _context_ticket(db, context, tenant_id)

    def outcome(
        status: str,
        result: dict[str, Any],
        *,
        error: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "action_type": action_type,
            "status": status,
            "result": result,
        }
        if error:
            payload["error"] = error
        return payload

    if action_type in DANGEROUS_ACTION_TYPES:
        return outcome(
            "dry_run" if dry_run else "skipped",
            {"reason": "dangerous_action_requires_approval"},
        )

    if action_type not in SAFE_ACTION_TYPES and action_type not in {
        "change_priority",
        "add_comment",
        "create_mock_email_log",
        "create_audit_log",
        "attach_runbook",
        "create_approval_request",
        "create_task_note",
        "create_integration_event_log",
    }:
        return outcome("skipped", {"reason": "unsupported_action"})

    if dry_run:
        return outcome(
            "dry_run",
            {"planned": True, "payload": action},
        )

    result: dict[str, Any] = {"mode": "internal_safe"}

    if action_type == "assign_ticket":
        if ticket is None:
            return outcome("skipped", {"reason": "tenant_scoped_ticket_required"})
        assignee = _bounded_text(
            action.get("assignee") or action.get("value"),
            "agent.support@sbs.local",
            255,
        )
        ticket.assignee_name = assignee
        ticket.updated_at = _now()
        result["assigned_to"] = assignee

    elif action_type in {"change_ticket_priority", "change_priority"}:
        if ticket is None:
            return outcome("skipped", {"reason": "tenant_scoped_ticket_required"})
        priority = _bounded_text(
            action.get("priority") or action.get("value"),
            "HIGH",
            20,
        ).upper()
        if priority not in {"LOW", "MEDIUM", "HIGH", "CRITICAL"}:
            return outcome("skipped", {"reason": "invalid_ticket_priority"})
        ticket.priority = priority
        ticket.updated_at = _now()
        result["priority"] = priority

    elif action_type in {"add_ticket_comment", "add_comment"}:
        if ticket is None:
            return outcome("skipped", {"reason": "tenant_scoped_ticket_required"})
        comment_body = _bounded_text(
            action.get("comment") or action.get("message"),
            "Automation comment",
            4000,
        )
        db.add(
            TicketComment(
                id=_uuid(),
                ticket_id=ticket.id,
                author_name="Automation Engine",
                author_role="automation",
                body=comment_body,
                created_at=_now(),
            )
        )
        result["comment"] = comment_body

    elif action_type == "transition_ticket_status":
        if ticket is None:
            return outcome("skipped", {"reason": "tenant_scoped_ticket_required"})
        next_status = canonical_ticket_status(_bounded_text(
            action.get("status"),
            "IN_PROGRESS",
            32,
        ))
        if next_status is None:
            return outcome("skipped", {"reason": "invalid_ticket_status"})
        try:
            lifecycle_result = transition_ticket_status(
                db,
                ticket,
                next_status,
                actor_name="Automation Engine",
                actor_kind="SYSTEM",
                actor_user=current_user,
                actor_email=(
                    current_user.email
                    if current_user is not None
                    else "automation-engine@sbs.local"
                ),
                allow_cross_tenant_actor=bool(
                    current_user is not None and current_user.is_root
                ),
                expected_version=(
                    int(action["expected_version"])
                    if action.get("expected_version") not in (None, "")
                    else None
                ),
                idempotency_key=(
                    str(action.get("idempotency_key") or "").strip() or None
                ),
                source="automation_engine",
                reason="Automation rule transitioned the ticket.",
            )
        except (TicketLifecycleError, TypeError, ValueError) as error:
            return outcome(
                "skipped",
                {"reason": getattr(error, "code", "invalid_ticket_transition")},
                error=str(error),
            )
        result["status"] = lifecycle_result.target_status
        result["previous_status"] = lifecycle_result.previous_status
        result["governance_version"] = lifecycle_result.governance_version
        result["already_applied"] = lifecycle_result.already_applied

    elif action_type in {
        "create_notification",
        "notify_assignee",
        "notify_role",
        "create_manager_notification",
        "create_security_notification",
        "require_admin_review",
        "notify_sla_risk",
        "notify_asset_owner",
    }:
        recipient_email = _bounded_text(
            action.get("recipient_email")
            or action.get("to_email")
            or (ticket.assignee_name if ticket else None),
            "manager@sbs.local",
            255,
        )
        db.add(
            Notification(
                id=_uuid(),
                tenant_id=tenant_id,
                type="automation",
                title=_bounded_text(
                    action.get("title"),
                    f"Automation {action_type}",
                    255,
                ),
                message=_bounded_text(
                    action.get("message"),
                    "Automation generated notification.",
                    4000,
                ),
                recipient_name=_bounded_text(
                    action.get("recipient_name"),
                    recipient_email,
                    200,
                ),
                recipient_email=recipient_email,
                channel="in_app",
                status="UNREAD",
                related_ticket_id=ticket.id if ticket else None,
                created_at=_now(),
            )
        )
        result["recipient"] = recipient_email

    elif action_type in {"send_mock_email", "create_mock_email_log"}:
        to_email = _bounded_text(
            action.get("to_email")
            or (ticket.requester_email if ticket else None),
            "demo@sbs.local",
            255,
        )
        db.add(
            EmailMessageLog(
                id=_uuid(),
                tenant_id=tenant_id,
                provider="mock_automation",
                to_email=to_email,
                subject=_bounded_text(
                    action.get("subject"),
                    "Automation mock email",
                    255,
                ),
                body=_bounded_text(
                    action.get("body"),
                    "Mock-safe email preview; no external email was sent.",
                    10000,
                ),
                status="SIMULATED",
                payload_json=_json_dump(
                    {
                        "simulation": True,
                        "delivery_confirmed": False,
                    }
                ),
                error_message="No external email was sent",
                related_ticket_id=ticket.id if ticket else None,
                created_at=_now(),
                sent_at=None,
            )
        )
        return outcome(
            "simulated",
            {
                "to_email": to_email,
                "delivery_confirmed": False,
            },
        )

    elif action_type == "export_report_mock":
        return outcome(
            "simulated",
            {
                "exported": False,
                "preview": True,
            },
        )

    elif action_type == "suggest_knowledge_article":
        article = db.scalar(select(KnowledgeArticle).order_by(KnowledgeArticle.helpful_count.desc()))
        if article is None:
            return outcome("skipped", {"reason": "knowledge_article_unavailable"})
        result["article_id"] = article.id if article else None
        result["article_title"] = article.title if article else None

    elif action_type == "escalate_ticket":
        if ticket is None:
            return outcome("skipped", {"reason": "tenant_scoped_ticket_required"})
        previous_priority = ticket.priority
        ticket.priority = "CRITICAL"
        ticket.updated_at = _now()
        db.add(
            TicketHistory(
                id=_uuid(),
                ticket_id=ticket.id,
                actor_name="Automation Engine",
                event_type="automation_escalation",
                field_name="priority",
                old_value=previous_priority,
                new_value="CRITICAL",
                message="Ticket escalated by an automation rule.",
                created_at=_now(),
            )
        )
        result["priority"] = "CRITICAL"

    elif action_type == "attach_runbook":
        if ticket is None:
            return outcome("skipped", {"reason": "tenant_scoped_ticket_required"})
        selector = _bounded_text(
            action.get("runbook") or action.get("runbook_title"),
            "",
            255,
        )
        statement = select(Runbook).where(
            (Runbook.code == selector) | (Runbook.title == selector),
            Runbook.is_active.is_(True),
        )
        if tenant_id is not None:
            statement = statement.where(
                (Runbook.tenant_id == tenant_id)
                | (Runbook.tenant_id.is_(None))
            )
        runbook = db.scalar(statement)
        if runbook is None:
            return outcome("skipped", {"reason": "runbook_unavailable"})
        db.add(
            TicketHistory(
                id=_uuid(),
                ticket_id=ticket.id,
                actor_name="Automation Engine",
                event_type="runbook_attached",
                field_name="runbook",
                old_value=None,
                new_value=runbook.title,
                message=f"Runbook attached: {runbook.title}",
                created_at=_now(),
            )
        )
        result["runbook_id"] = runbook.id
        result["runbook_title"] = runbook.title

    elif action_type == "create_approval_request":
        approval = ApprovalRequest(
            id=_uuid(),
            tenant_id=tenant_id,
            title=_bounded_text(
                action.get("title"),
                "Automation approval request",
                255,
            ),
            description=_bounded_text(
                action.get("description"),
                "Approval requested by automation.",
                4000,
            ),
            entity_type=_bounded_text(
                action.get("entity_type"),
                "ticket" if ticket else "automation",
                80,
            ),
            entity_id=_bounded_text(
                action.get("entity_id"),
                ticket.id if ticket else "automation",
                120,
            ),
            requested_by_id=current_user.id if current_user else None,
            requested_by=current_user.email if current_user else "automation@sbs.local",
            approver_name=_bounded_text(
                action.get("approver_name"),
                "IT Manager",
                255,
            ),
            status="pending",
            reason="automation_action",
            requested_at=_now(),
            created_at=_now(),
        )
        db.add(approval)
        result["approval_request_id"] = approval.id

    elif action_type == "create_task_note":
        if ticket is None:
            return outcome("skipped", {"reason": "tenant_scoped_ticket_required"})
        note = _bounded_text(
            action.get("message"),
            "Automation task note.",
            4000,
        )
        db.add(
            TicketHistory(
                id=_uuid(),
                ticket_id=ticket.id,
                actor_name="Automation Engine",
                event_type="automation_note",
                field_name="note",
                old_value=None,
                new_value=note,
                message=note,
                created_at=_now(),
            )
        )
        result["note"] = note

    elif action_type == "create_integration_event_log":
        event = create_integration_event(
            db,
            tenant_id=tenant_id,
            external_system_id=None,
            direction="outbound",
            event_type="automation_demo_event",
            status="logged_only",
            request_summary={"action_type": action_type},
            response_summary={"message": "Safe event"},
        )
        result["integration_event_id"] = event.id

    elif action_type == "create_audit_log":
        audit = log_audit(
            db,
            action="automation_action_executed",
            entity_type="automation_rule",
            entity_id=_bounded_text(context.get("rule_id"), "unknown", 120),
            actor_user=current_user,
            actor_email=current_user.email if current_user else None,
            tenant_id=tenant_id,
            metadata={"action_type": action_type},
        )
        result["audit_log_id"] = audit.id

    else:
        return outcome(
            "skipped",
            {"reason": "action_not_implemented"},
        )

    return outcome("success", result)


def create_approval_for_execution(db: Session, execution: AutomationRun, approver_role: str | None) -> ApprovalRequest:
    approver = approver_role or "it_manager"
    request_item = ApprovalRequest(
        id=_uuid(),
        tenant_id=execution.tenant_id,
        title="Automation approval required",
        description="Approval required for automation execution.",
        entity_type="automation_execution",
        entity_id=execution.id,
        requested_by=execution.executed_by_id or "automation@sbs.local",
        approver_name=approver,
        status="pending",
        reason="dangerous_or_approval_required_action",
        requested_at=_now(),
        created_at=_now(),
        metadata_json=_json_dump({"execution_id": execution.id, "rule_id": execution.rule_id}),
    )
    db.add(request_item)
    db.flush()
    execution.approval_request_id = request_item.id
    execution.status = "waiting_approval"
    return request_item


def execute_rule(db: Session, rule: AutomationRule, context: dict[str, Any], current_user: User | None = None, dry_run: bool = False) -> AutomationRun:
    now = _now()
    if (
        current_user is not None
        and not current_user.is_root
        and rule.tenant_id not in {None, current_user.tenant_id}
    ):
        raise ValueError("Rule not found")
    effective_tenant_id = (
        rule.tenant_id
        or (current_user.tenant_id if current_user else None)
        or context.get("tenant_id")
    )
    execution_context = dict(context)
    execution_context["rule_id"] = rule.id
    if effective_tenant_id is not None:
        execution_context["tenant_id"] = effective_tenant_id
    if not rule.is_active and not dry_run:
        raise ValueError("Rule is inactive")

    if not dry_run and rule.cooldown_minutes > 0 and rule.last_run_at is not None:
        elapsed = (now - rule.last_run_at).total_seconds() / 60.0
        if elapsed < rule.cooldown_minutes:
            run = AutomationRun(
                id=_uuid(),
                tenant_id=effective_tenant_id,
                rule_id=rule.id,
                runbook_id=None,
                trigger_type=str(context.get("trigger_type") or rule.trigger_type),
                trigger_entity_type=context.get("entity_type"),
                trigger_entity_id=context.get("entity_id"),
                status="skipped",
                input_payload_json=_json_dump(execution_context),
                output_payload_json=_json_dump({"reason": "cooldown"}),
                started_at=now,
                finished_at=now,
                executed_by_id=current_user.id if current_user else None,
                result_summary=_json_dump({"reason": "cooldown"}),
                error_message=None,
                created_at=now,
            )
            db.add(run)
            return run

    run = AutomationRun(
        id=_uuid(),
        tenant_id=effective_tenant_id,
        rule_id=rule.id,
        runbook_id=None,
        trigger_type=str(context.get("trigger_type") or rule.trigger_type),
        trigger_entity_type=context.get("entity_type"),
        trigger_entity_id=context.get("entity_id"),
        status="dry_run" if dry_run else "running",
        input_payload_json=_json_dump(execution_context),
        output_payload_json=None,
        started_at=now,
        finished_at=None,
        executed_by_id=current_user.id if current_user else None,
        result_summary=None,
        error_message=None,
        created_at=now,
    )
    db.add(run)
    db.flush()

    actions = _json_load_object(rule.actions_json, [])
    if not isinstance(actions, list):
        raise ValueError("Rule actions must be a list")
    if any(not isinstance(action, dict) for action in actions):
        raise ValueError("Rule actions must contain only objects")

    requires_approval = bool(rule.requires_approval)
    if not requires_approval:
        requires_approval = any(str(action.get("type", "")).strip() in DANGEROUS_ACTION_TYPES for action in actions)

    if requires_approval and not dry_run:
        create_approval_for_execution(db, run, rule.approval_role)
        run.output_payload_json = _json_dump({"approval_required": True})
        run.finished_at = now
        run.result_summary = _json_dump({"status": "waiting_approval"})
        if current_user is not None:
            log_audit(
                db,
                action="approval_requested",
                entity_type="automation_execution",
                entity_id=run.id,
                actor_user=current_user,
                tenant_id=effective_tenant_id,
                metadata={"rule_id": rule.id},
            )
        return run

    status_counts = {
        "success": 0,
        "simulated": 0,
        "skipped": 0,
        "failed": 0,
        "dry_run": 0,
    }
    outputs: list[dict[str, Any]] = []
    for action_index, action in enumerate(actions):
        action_input = dict(action)
        action_input.setdefault(
            "idempotency_key",
            f"automation:{run.id}:{action_index}",
        )
        try:
            result = execute_action(
                db,
                action_input,
                execution_context,
                dry_run=dry_run,
                tenant_id=effective_tenant_id,
                current_user=current_user,
            )
        except Exception as exc:  # noqa: BLE001
            action_type = _bounded_text(action_input.get("type"), "unknown", 80)
            error_message = (
                f"Automation action failed: {exc.__class__.__name__}"
            )
            logger.exception(
                "automation_action_failed",
                extra={
                    "rule_id": rule.id,
                    "run_id": run.id,
                    "action_type": action_type,
                },
            )
            result = {
                "action_type": action_type,
                "status": "failed",
                "result": {},
                "error": error_message,
            }
        outputs.append(result)
        result_status = str(result["status"])
        status_counts[result_status] = status_counts.get(result_status, 0) + 1
        AutomationEngine.log_action(
            db,
            run=run,
            action_type=result["action_type"],
            status=result["status"],
            input_payload=action_input,
            output_payload=result.get("result", {}),
            error_message=result.get("error"),
        )

    failures = status_counts["failed"]
    if dry_run:
        run.status = "dry_run"
    elif failures:
        run.status = "failed"
    elif status_counts["success"] and not (
        status_counts["simulated"] or status_counts["skipped"]
    ):
        run.status = "success"
    elif status_counts["success"]:
        run.status = "partial"
    elif status_counts["simulated"]:
        run.status = "simulated"
    else:
        run.status = "skipped"
    run.finished_at = _now()
    run.output_payload_json = _json_dump({"actions": outputs})
    run.result_summary = _json_dump(
        {
            "actions": outputs,
            "status_counts": status_counts,
        }
    )
    run.error_message = f"{failures} action(s) failed" if failures else None

    if not dry_run:
        rule.last_run_at = run.finished_at
        rule.run_count = int(rule.run_count or 0) + 1
        if failures:
            rule.failure_count = int(rule.failure_count or 0) + 1

    if current_user is not None:
        log_audit(
            db,
            action="automation_rule_dry_run" if dry_run else "automation_rule_executed",
            entity_type="automation_rule",
            entity_id=rule.id,
            actor_user=current_user,
            tenant_id=effective_tenant_id,
            metadata={"execution_id": run.id, "status": run.status},
        )
        if run.status == "failed":
            log_audit(
                db,
                action="automation_execution_failed",
                entity_type="automation_execution",
                entity_id=run.id,
                actor_user=current_user,
                tenant_id=effective_tenant_id,
                metadata={"rule_id": rule.id},
            )

    return run


def run_manual_rule(db: Session, rule_id: str, payload: dict[str, Any], current_user: User, dry_run: bool = False) -> AutomationRun:
    rule = db.get(AutomationRule, rule_id)
    if rule is None or (
        not current_user.is_root
        and rule.tenant_id not in {None, current_user.tenant_id}
    ):
        raise ValueError("Rule not found")
    context = dict(payload or {})
    context.setdefault("trigger_type", "manual")
    context.setdefault("entity_type", context.get("entity_type", "manual"))
    if current_user.tenant_id is not None:
        context["tenant_id"] = current_user.tenant_id
    return execute_rule(db, rule, context, current_user=current_user, dry_run=dry_run)


def evaluate_rules(
    db: Session,
    *,
    tenant_id: str | None,
    trigger_type: str,
    context: dict[str, Any],
    actor_email: str | None = None,
) -> list[AutomationRun]:
    statement = select(AutomationRule).where(AutomationRule.is_active == True, AutomationRule.trigger_type == trigger_type)  # noqa: E712
    statement = _rule_scope(statement, tenant_id).order_by(AutomationRule.priority.asc(), AutomationRule.created_at.asc())
    actor = _as_user(db, actor_email, tenant_id)
    runs: list[AutomationRun] = []
    for rule in db.scalars(statement).all():
        execution_context = dict(context)
        if tenant_id is not None:
            execution_context["tenant_id"] = tenant_id
        if not evaluate_conditions(rule, execution_context):
            continue
        runs.append(
            execute_rule(
                db,
                rule,
                execution_context,
                current_user=actor,
                dry_run=False,
            )
        )
    return runs


def suggest_runbooks_for_ticket(db: Session, ticket: Ticket, tenant_id: str | None) -> dict[str, Any]:
    text = f"{ticket.title or ''} {ticket.description or ''}".lower()

    statement = select(Runbook).where(Runbook.is_active == True)  # noqa: E712
    if tenant_id is not None:
        statement = statement.where((Runbook.tenant_id == tenant_id) | (Runbook.tenant_id.is_(None)))
    runbooks = db.scalars(statement.order_by(Runbook.severity.desc(), Runbook.title.asc())).all()

    keywords = {
        "интернет": "Проверка отсутствия интернета в кабинете",
        "wi-fi": "Массовый сбой Wi-Fi",
        "wifi": "Массовый сбой Wi-Fi",
        "принтер": "Не работает принтер",
        "парол": "Сброс пароля пользователя",
        "platonus": "Нет доступа к Platonus",
        "moodle": "Нет доступа к Moodle",
        "фишинг": "Подозрение на фишинговое письмо",
        "компьютер": "Не включается компьютер",
        "проектор": "Проверка проектора",
        "почта": "Сбой корпоративной почты",
        "zimbra": "Проверка Zimbra mock health",
        "ldap": "Проверка LDAP mock sync",
        "сеть": "Проверка коммутатора",
        "сервер": "Проверка сервера",
        "critical": "Обработка критичной заявки",
    }

    matched_titles = {title for key, title in keywords.items() if key in text}
    suggested = [rb for rb in runbooks if rb.title in matched_titles]
    if not suggested:
        suggested = runbooks[:3]

    context = build_ticket_context(ticket)
    dry_runs = []
    rules_statement = select(AutomationRule).where(AutomationRule.is_active == True, AutomationRule.trigger_type == "ticket_created")  # noqa: E712
    rules_statement = _rule_scope(rules_statement, tenant_id)
    for rule in db.scalars(rules_statement).all():
        result = AutomationEngine.dry_run_rule(rule, context)
        if result["matched"]:
            dry_runs.append(result)

    return {
        "ticket_id": ticket.id,
        "suggested_runbooks": [
            {
                "id": item.id,
                "code": item.code,
                "title": item.title,
                "category": item.category,
                "severity": item.severity,
                "estimated_minutes": item.estimated_minutes,
            }
            for item in suggested
        ],
        "matched_rules": dry_runs,
    }


def run_runbook(db: Session, runbook_id: str, payload: dict[str, Any], current_user: User, dry_run: bool = False) -> AutomationRun:
    runbook = db.get(Runbook, runbook_id)
    if runbook is None or (
        not current_user.is_root
        and runbook.tenant_id not in {None, current_user.tenant_id}
    ):
        raise ValueError("Runbook not found")
    effective_tenant_id = runbook.tenant_id or current_user.tenant_id

    fallback_rule_id = payload.get("rule_id")
    if fallback_rule_id is None:
        fallback_rule = db.scalar(
            select(AutomationRule)
            .where(
                (AutomationRule.tenant_id == effective_tenant_id)
                | (AutomationRule.tenant_id.is_(None))
            )
            .order_by(AutomationRule.priority.asc(), AutomationRule.created_at.asc())
        )
        if fallback_rule is None:
            raise ValueError("No automation rule available for runbook execution")
        fallback_rule_id = fallback_rule.id

    execution = AutomationRun(
        id=_uuid(),
        tenant_id=effective_tenant_id,
        rule_id=str(fallback_rule_id),
        runbook_id=runbook.id,
        trigger_type="manual",
        trigger_entity_type="runbook",
        trigger_entity_id=runbook.id,
        status="dry_run" if dry_run else "running",
        input_payload_json=_json_dump(payload or {}),
        output_payload_json=None,
        started_at=_now(),
        finished_at=None,
        executed_by_id=current_user.id,
        approval_request_id=None,
        result_summary=None,
        error_message=None,
        created_at=_now(),
    )
    db.add(execution)
    db.flush()

    if runbook.requires_approval and not dry_run:
        create_approval_for_execution(db, execution, "it_manager")
        execution.finished_at = _now()
        execution.result_summary = _json_dump({"status": "waiting_approval"})
        log_audit(
            db,
            action="approval_requested",
            entity_type="runbook",
            entity_id=runbook.id,
            actor_user=current_user,
            tenant_id=effective_tenant_id,
            metadata={"execution_id": execution.id},
        )
        return execution

    execution.status = "dry_run" if dry_run else "manual_pending"
    execution.finished_at = _now()
    execution.output_payload_json = _json_dump(
        {
            "runbook": runbook.title,
            "steps": _json_load_object(runbook.steps_json, []),
        }
    )
    execution.result_summary = _json_dump(
        {
            "runbook": runbook.title,
            "dry_run": dry_run,
            "execution_mode": "manual_checklist",
            "completion_confirmed": False,
        }
    )
    log_audit(
        db,
        action="runbook_dry_run" if dry_run else "runbook_started",
        entity_type="runbook",
        entity_id=runbook.id,
        actor_user=current_user,
        tenant_id=effective_tenant_id,
        metadata={
            "execution_id": execution.id,
            "completion_confirmed": False,
        },
    )
    return execution


def approve_request(db: Session, approval_id: str, current_user: User, comment: str | None) -> ApprovalRequest:
    request = db.get(ApprovalRequest, approval_id)
    if request is None:
        raise ValueError("Approval request not found")
    request.status = "approved"
    request.approver_id = current_user.id
    request.approver_name = current_user.full_name
    request.decision_comment = comment
    request.decided_at = _now()
    log_audit(
        db,
        action="approval_approved",
        entity_type="approval_request",
        entity_id=request.id,
        actor_user=current_user,
        tenant_id=request.tenant_id,
        metadata={"entity_type": request.entity_type, "entity_id": request.entity_id},
    )
    return request


def reject_request(db: Session, approval_id: str, current_user: User, comment: str | None) -> ApprovalRequest:
    request = db.get(ApprovalRequest, approval_id)
    if request is None:
        raise ValueError("Approval request not found")
    request.status = "rejected"
    request.approver_id = current_user.id
    request.approver_name = current_user.full_name
    request.decision_comment = comment
    request.decided_at = _now()
    log_audit(
        db,
        action="approval_rejected",
        entity_type="approval_request",
        entity_id=request.id,
        actor_user=current_user,
        tenant_id=request.tenant_id,
        metadata={"entity_type": request.entity_type, "entity_id": request.entity_id},
    )
    return request


def retry_execution(db: Session, execution_id: str, current_user: User) -> AutomationRun:
    execution = db.get(AutomationRun, execution_id)
    if execution is None or (
        not current_user.is_root
        and execution.tenant_id != current_user.tenant_id
    ):
        raise ValueError("Execution not found")
    if _status(execution.status) not in {"failed", "skipped"}:
        raise ValueError("Only failed/skipped executions can be retried")
    if execution.rule_id and execution.rule_id != "manual_runbook":
        rule = db.get(AutomationRule, execution.rule_id)
        if rule is None:
            raise ValueError("Rule not found")
        context = _json_load_object(execution.input_payload_json, {})
        retried = execute_rule(db, rule, context, current_user=current_user, dry_run=False)
    else:
        if not execution.runbook_id:
            raise ValueError("Execution cannot be retried")
        payload = _json_load_object(execution.input_payload_json, {})
        retried = run_runbook(db, execution.runbook_id, payload, current_user=current_user, dry_run=False)
    log_audit(
        db,
        action="automation_execution_retried",
        entity_type="automation_execution",
        entity_id=retried.id,
        actor_user=current_user,
        tenant_id=retried.tenant_id,
        metadata={"source_execution_id": execution.id},
    )
    return retried

    @staticmethod
    def evaluate_conditions(rule: AutomationRule, context: dict[str, Any]) -> bool:
        raw_conditions = _json_load_object(rule.conditions_json, [])
        if raw_conditions in (None, {}, []):
            return True

        mode = "all"
        conditions: list[dict[str, Any]]
        if isinstance(raw_conditions, dict):
            mode = str(raw_conditions.get("mode", "all")).lower()
            conditions = raw_conditions.get("conditions", [])
            if "any" in raw_conditions:
                mode = "any"
                conditions = raw_conditions.get("any", [])
            if "all" in raw_conditions:
                mode = "all"
                conditions = raw_conditions.get("all", [])
        elif isinstance(raw_conditions, list):
            conditions = raw_conditions
        else:
            return True

        if not conditions:
            return True

        results: list[bool] = []
        for item in conditions:
            path = str(item.get("path", "")).strip()
            op = str(item.get("operator", "eq")).lower().strip()
            expected = item.get("value")
            if not path:
                results.append(True)
                continue
            actual = _get_context_value(context, path)
            if op in {"eq", "=="}:
                passed = _ci_text(actual) == _ci_text(expected)
            elif op in {"contains", "includes"}:
                passed = _ci_text(expected) in _ci_text(actual)
            elif op in {"gte", ">="}:
                try:
                    passed = float(actual) >= float(expected)
                except (TypeError, ValueError):
                    passed = False
            elif op in {"lte", "<="}:
                try:
                    passed = float(actual) <= float(expected)
                except (TypeError, ValueError):
                    passed = False
            elif op == "in":
                if not isinstance(expected, list):
                    passed = False
                else:
                    passed = _ci_text(actual) in {_ci_text(value) for value in expected}
            else:
                passed = False
            results.append(passed)

        return any(results) if mode == "any" else all(results)

    @staticmethod
    def _attach_runbook_if_exists(db: Session, tenant_id: str | None, selector: str) -> Runbook | None:
        statement = select(Runbook).where((Runbook.code == selector) | (Runbook.title == selector))
        if tenant_id is not None:
            statement = statement.where((Runbook.tenant_id == tenant_id) | (Runbook.tenant_id.is_(None)))
        return db.scalar(statement)

    @staticmethod
    def execute_actions(
        db: Session,
        *,
        run: AutomationRun,
        rule: AutomationRule,
        context: dict[str, Any],
        actor_email: str | None,
    ) -> dict[str, Any]:
        actions = _json_load_object(rule.actions_json, [])
        if not isinstance(actions, list):
            actions = []
        actor = _as_user(db, actor_email, run.tenant_id)
        ticket_id = _get_context_value(context, "ticket.id")
        ticket = db.scalar(select(Ticket).where(Ticket.id == ticket_id)) if ticket_id else None

        success_count = 0
        failed_count = 0
        outputs: list[dict[str, Any]] = []

        for action in actions:
            action_type = str(action.get("type", "unknown"))
            input_payload = dict(action)
            try:
                output_payload: dict[str, Any] = {"mode": "demo"}

                if action_type == "assign_ticket" and ticket is not None:
                    assignee = str(action.get("assignee", action.get("value", "agent.support@sbs.local")))
                    ticket.assignee_name = assignee
                    ticket.updated_at = _now()
                    output_payload.update({"assigned_to": assignee})

                elif action_type == "change_priority" and ticket is not None:
                    priority = str(action.get("priority", action.get("value", "HIGH"))).upper()
                    ticket.priority = priority
                    ticket.updated_at = _now()
                    output_payload.update({"priority": priority})

                elif action_type == "add_comment" and ticket is not None:
                    comment_body = str(action.get("comment", "Demo automation comment."))
                    db.add(
                        TicketComment(
                            id=_uuid(),
                            ticket_id=ticket.id,
                            author_name="Automation Engine",
                            author_role="automation",
                            body=comment_body,
                            created_at=_now(),
                        )
                    )
                    db.add(
                        TicketHistory(
                            id=_uuid(),
                            ticket_id=ticket.id,
                            actor_name="Automation Engine",
                            event_type="automation_comment",
                            field_name="comment",
                            old_value=None,
                            new_value=comment_body,
                            message="Добавлен demo-комментарий автоматизацией.",
                            created_at=_now(),
                        )
                    )
                    output_payload.update({"comment": comment_body})

                elif action_type == "create_notification":
                    recipient_email = str(action.get("recipient_email") or (ticket.assignee_name if ticket else "manager@sbs.local"))
                    db.add(
                        Notification(
                            id=_uuid(),
                            type="automation",
                            title=str(action.get("title", f"Automation rule {rule.name}")),
                            message=str(action.get("message", "Demo automation notification.")),
                            recipient_name=str(action.get("recipient_name", recipient_email)),
                            recipient_email=recipient_email,
                            channel="in_app",
                            status="UNREAD",
                            related_ticket_id=ticket.id if ticket else None,
                            created_at=_now(),
                        )
                    )
                    output_payload.update({"recipient": recipient_email})

                elif action_type == "create_mock_email_log":
                    to_email = str(action.get("to_email", ticket.requester_email if ticket else "demo@sbs.local"))
                    db.add(
                        EmailMessageLog(
                            id=_uuid(),
                            provider="mock_automation",
                            to_email=to_email,
                            subject=str(action.get("subject", "Demo automation email")),
                            body=str(action.get("body", "This is a safe demo email log.")),
                            status="SIMULATED",
                            error_message="No external email was sent",
                            related_ticket_id=ticket.id if ticket else None,
                            created_at=_now(),
                            sent_at=None,
                        )
                    )
                    output_payload.update({"to_email": to_email})

                elif action_type == "suggest_knowledge_article":
                    article = None
                    if ticket is not None:
                        article = db.scalar(select(KnowledgeArticle).where(KnowledgeArticle.ticket_category == ticket.category).order_by(KnowledgeArticle.helpful_count.desc()))
                    if article is None:
                        article = db.scalar(select(KnowledgeArticle).order_by(KnowledgeArticle.helpful_count.desc()))
                    output_payload.update({
                        "article_id": article.id if article else None,
                        "article_title": article.title if article else None,
                    })

                elif action_type == "attach_runbook":
                    selector = str(action.get("runbook", action.get("runbook_title", "Обработка критичной заявки")))
                    runbook = AutomationEngine._attach_runbook_if_exists(db, run.tenant_id, selector)
                    if ticket is not None and runbook is not None:
                        db.add(
                            TicketHistory(
                                id=_uuid(),
                                ticket_id=ticket.id,
                                actor_name="Automation Engine",
                                event_type="runbook_attached",
                                field_name="runbook",
                                old_value=None,
                                new_value=runbook.title,
                                message=f"Привязан runbook: {runbook.title}",
                                created_at=_now(),
                            )
                        )
                    output_payload.update({"runbook_id": runbook.id if runbook else None, "runbook_title": runbook.title if runbook else selector})

                elif action_type == "create_approval_request":
                    request_item = ApprovalRequest(
                        id=_uuid(),
                        tenant_id=run.tenant_id,
                        title=str(action.get("title", "Automation approval request")),
                        description=str(action.get("description", "Demo approval request created by automation.")),
                        entity_type=str(action.get("entity_type", "ticket" if ticket else "automation")),
                        entity_id=str(action.get("entity_id", ticket.id if ticket else rule.id)),
                        requested_by=actor_email or "automation@sbs.local",
                        approver_name=str(action.get("approver_name", "IT Manager")),
                        status="pending",
                        decision_comment=None,
                        created_at=_now(),
                    )
                    db.add(request_item)
                    output_payload.update({"approval_request_id": request_item.id})

                elif action_type == "create_audit_log":
                    audit = log_audit(
                        db,
                        action="automation_action_executed",
                        entity_type="automation_rule",
                        entity_id=rule.id,
                        actor_user=actor,
                        actor_email=actor_email,
                        tenant_id=run.tenant_id,
                        metadata={"action_type": action_type, "run_id": run.id},
                    )
                    output_payload.update({"audit_log_id": audit.id})

                elif action_type == "create_integration_event_log":
                    event = create_integration_event(
                        db,
                        tenant_id=run.tenant_id,
                        external_system_id=None,
                        direction="outbound",
                        event_type="automation_demo_event",
                        status="logged_only",
                        request_summary={"rule_code": rule.code, "run_id": run.id},
                        response_summary={"message": "Safe demo integration event."},
                    )
                    output_payload.update({"integration_event_id": event.id})

                elif action_type == "create_task_note" and ticket is not None:
                    message = str(action.get("message", "Создана demo заметка по автоматизации."))
                    history = TicketHistory(
                        id=_uuid(),
                        ticket_id=ticket.id,
                        actor_name="Automation Engine",
                        event_type="automation_note",
                        field_name="note",
                        old_value=None,
                        new_value=message,
                        message=message,
                        created_at=_now(),
                    )
                    db.add(history)
                    output_payload.update({"note": message})

                else:
                    output_payload.update({"message": "Unsupported action in demo mode."})

                AutomationEngine.log_action(
                    db,
                    run=run,
                    action_type=action_type,
                    status=(
                        "simulated"
                        if action_type == "create_mock_email_log"
                        else "success"
                    ),
                    input_payload=input_payload,
                    output_payload=output_payload,
                )
                outputs.append(
                    {
                        "action": action_type,
                        "status": (
                            "simulated"
                            if action_type == "create_mock_email_log"
                            else "success"
                        ),
                        "output": output_payload,
                    }
                )
                success_count += 1

            except Exception as exc:  # noqa: BLE001
                AutomationEngine.log_action(
                    db,
                    run=run,
                    action_type=action_type,
                    status="failed",
                    input_payload=input_payload,
                    output_payload={},
                    error_message=str(exc),
                )
                outputs.append({"action": action_type, "status": "failed", "error": str(exc)})
                failed_count += 1

        summary = {
            "rule": rule.name,
            "success_actions": success_count,
            "failed_actions": failed_count,
            "actions": outputs,
            "mode": "safe_demo",
        }
        run.status = "success" if failed_count == 0 else "failed"
        run.finished_at = _now()
        run.result_summary = _json_dump(summary)
        run.error_message = None if failed_count == 0 else f"{failed_count} action(s) failed"
        return summary

    @staticmethod
    def dry_run_rule(rule: AutomationRule, context: dict[str, Any]) -> dict[str, Any]:
        matched = AutomationEngine.evaluate_conditions(rule, context)
        actions = _json_load_object(rule.actions_json, [])
        if not isinstance(actions, list):
            actions = []
        return {
            "rule_id": rule.id,
            "rule_code": rule.code,
            "rule_name": rule.name,
            "trigger_type": rule.trigger_type,
            "matched": matched,
            "planned_actions": actions,
            "mode": "safe_demo",
        }

    @staticmethod
    def evaluate_rules(
        db: Session,
        *,
        tenant_id: str | None,
        trigger_type: str,
        context: dict[str, Any],
        actor_email: str | None = None,
    ) -> list[AutomationRun]:
        statement = select(AutomationRule).where(AutomationRule.is_active == True, AutomationRule.trigger_type == trigger_type)  # noqa: E712
        statement = _rule_scope(statement, tenant_id).order_by(AutomationRule.priority.asc(), AutomationRule.created_at.asc())
        rules = db.scalars(statement).all()
        runs: list[AutomationRun] = []

        for rule in rules:
            if not AutomationEngine.evaluate_conditions(rule, context):
                continue
            run = AutomationEngine.create_run(
                db,
                rule=rule,
                trigger_type=trigger_type,
                trigger_entity_type=str(context.get("entity_type", "ticket")),
                trigger_entity_id=str(context.get("entity_id")) if context.get("entity_id") is not None else None,
            )
            try:
                AutomationEngine.execute_actions(db, run=run, rule=rule, context=context, actor_email=actor_email)
            except Exception as exc:  # noqa: BLE001
                run.status = "failed"
                run.finished_at = _now()
                run.error_message = str(exc)
                run.result_summary = _json_dump({"error": str(exc), "mode": "safe_demo"})
            runs.append(run)
            log_audit(
                db,
                action="automation_run_completed",
                entity_type="automation_rule",
                entity_id=rule.id,
                actor_user=_as_user(db, actor_email, tenant_id),
                actor_email=actor_email,
                tenant_id=tenant_id,
                metadata={"trigger_type": trigger_type, "run_id": run.id, "status": run.status},
            )
        return runs

    @staticmethod
    def suggest_runbooks_for_ticket(db: Session, ticket: Ticket, tenant_id: str | None = None) -> dict[str, Any]:
        text = f"{ticket.title} {ticket.description or ''} {ticket.category}".lower()
        statement = select(Runbook).where(Runbook.is_active == True)  # noqa: E712
        if tenant_id is not None:
            statement = statement.where((Runbook.tenant_id == tenant_id) | (Runbook.tenant_id.is_(None)))
        runbooks = db.scalars(statement.order_by(Runbook.severity.desc(), Runbook.title.asc())).all()

        keywords = {
            "интернет": "Проверка отсутствия интернета в кабинете",
            "wi-fi": "Массовый сбой Wi-Fi",
            "wifi": "Массовый сбой Wi-Fi",
            "принтер": "Не работает принтер",
            "парол": "Сброс пароля пользователя",
            "platonus": "Нет доступа к Platonus",
            "moodle": "Нет доступа к Moodle",
            "фишинг": "Подозрение на фишинговое письмо",
            "компьютер": "Не включается компьютер",
            "проектор": "Проверка проектора",
            "почта": "Сбой корпоративной почты",
            "zimbra": "Проверка Zimbra mock health",
            "ldap": "Проверка LDAP mock sync",
            "сеть": "Проверка коммутатора",
            "сервер": "Проверка сервера",
            "critical": "Обработка критичной заявки",
        }

        matched_titles = {title for key, title in keywords.items() if key in text}
        suggested = [rb for rb in runbooks if rb.title in matched_titles]
        if not suggested:
            suggested = runbooks[:3]

        context = build_ticket_context(ticket)
        dry_runs = []
        rules_statement = select(AutomationRule).where(AutomationRule.is_active == True, AutomationRule.trigger_type == "ticket_created")  # noqa: E712
        rules_statement = _rule_scope(rules_statement, tenant_id)
        for rule in db.scalars(rules_statement).all():
            result = AutomationEngine.dry_run_rule(rule, context)
            if result["matched"]:
                dry_runs.append(result)

        return {
            "ticket_id": ticket.id,
            "suggested_runbooks": [
                {
                    "id": item.id,
                    "code": item.code,
                    "title": item.title,
                    "category": item.category,
                    "severity": item.severity,
                    "estimated_minutes": item.estimated_minutes,
                }
                for item in suggested
            ],
            "matched_rules": dry_runs,
        }


def collect_automation_overview(db: Session, tenant_id: str | None = None) -> dict[str, Any]:
    rules_statement = select(AutomationRule)
    runs_statement = select(AutomationRun)
    action_logs_statement = select(AutomationActionLog)
    approvals_statement = select(ApprovalRequest)
    runbooks_statement = select(Runbook)
    executions_statement = select(RunbookExecution)

    if tenant_id is not None:
        rules_statement = rules_statement.where((AutomationRule.tenant_id == tenant_id) | (AutomationRule.tenant_id.is_(None)))
        runs_statement = runs_statement.where((AutomationRun.tenant_id == tenant_id) | (AutomationRun.tenant_id.is_(None)))
        action_logs_statement = action_logs_statement.where((AutomationActionLog.tenant_id == tenant_id) | (AutomationActionLog.tenant_id.is_(None)))
        approvals_statement = approvals_statement.where((ApprovalRequest.tenant_id == tenant_id) | (ApprovalRequest.tenant_id.is_(None)))
        runbooks_statement = runbooks_statement.where((Runbook.tenant_id == tenant_id) | (Runbook.tenant_id.is_(None)))
        executions_statement = executions_statement.where((RunbookExecution.tenant_id == tenant_id) | (RunbookExecution.tenant_id.is_(None)))

    rules = db.scalars(rules_statement).all()
    runs = db.scalars(runs_statement).all()
    action_logs = db.scalars(action_logs_statement.order_by(AutomationActionLog.created_at.desc())).all()
    approvals = db.scalars(approvals_statement).all()
    runbooks = db.scalars(runbooks_statement).all()
    executions = db.scalars(executions_statement).all()

    today = datetime.now(UTC).date()
    runs_today = [item for item in runs if item.created_at.date() == today]
    failed_runs = [item for item in runs if item.status in {"failed", "completed_with_errors"}]
    successful_runs = [item for item in runs if item.status in {"completed", "success"}]
    success_rate = round((len(successful_runs) / len(runs) * 100), 1) if runs else 100.0
    pending_approvals = [item for item in approvals if item.status.lower() == "pending"]

    trigger_counter: dict[str, int] = {}
    for run in runs:
        trigger_counter[run.trigger_type] = trigger_counter.get(run.trigger_type, 0) + 1

    top_rule_counter: dict[str, int] = {}
    for run in runs:
        top_rule_counter[run.rule_id] = top_rule_counter.get(run.rule_id, 0) + 1
    rule_map = {rule.id: rule.name for rule in rules}

    return {
        "active_rules": sum(1 for item in rules if item.is_active),
        "runs_today": len(runs_today),
        "failed_runs": len(failed_runs),
        "pending_approvals": len(pending_approvals),
        "runbooks_available": sum(1 for item in runbooks if item.is_active),
        "automation_success_rate": success_rate,
        "automation_runs_count": len(runs),
        "runbook_execution_count": len(executions),
        "last_actions": [
            {
                "id": item.id,
                "action_type": item.action_type,
                "status": item.status,
                "created_at": item.created_at,
                "error_message": item.error_message,
            }
            for item in action_logs[:8]
        ],
        "top_triggered_rules": [
            {
                "rule_id": rule_id,
                "rule_name": rule_map.get(rule_id, "Unknown"),
                "count": count,
            }
            for rule_id, count in sorted(top_rule_counter.items(), key=lambda value: value[1], reverse=True)[:5]
        ],
        "triggers": [{"trigger_type": key, "count": value} for key, value in sorted(trigger_counter.items(), key=lambda value: value[1], reverse=True)],
    }


def trigger_automation_event(
    db: Session,
    *,
    tenant_id: str | None,
    trigger_type: str,
    context: dict[str, Any],
    actor_email: str | None,
) -> list[AutomationRun]:
    legacy_runs: list[AutomationRun] = []
    try:
        with db.begin_nested():
            legacy_runs = AutomationEngine.evaluate_rules(
                db,
                tenant_id=tenant_id,
                trigger_type=trigger_type,
                context=context,
                actor_email=actor_email,
            )
    except Exception:  # noqa: BLE001
        # Event hooks must never break core business operations.
        logger.exception(
            "legacy_automation_event_failed",
            extra={"tenant_id": tenant_id, "trigger_type": trigger_type},
        )
    try:
        from app.services.workflow_engine import enqueue_matching_workflows

        with db.begin_nested():
            actor = _as_user(db, actor_email, tenant_id)
            enqueue_matching_workflows(
                db,
                tenant_id=tenant_id,
                trigger_type=trigger_type,
                context=context,
                actor_id=actor.id if actor else None,
                correlation_id=str(
                    context.get("correlation_id")
                    or context.get("event_id")
                    or ""
                )
                or None,
            )
    except Exception:  # noqa: BLE001
        logger.exception(
            "workflow_engine_event_enqueue_failed",
            extra={"tenant_id": tenant_id, "trigger_type": trigger_type},
        )
    return legacy_runs


def seed_workflow_automation_data(db: Session, tenant_id: str, actor_email: str) -> None:
    now = _now()

    runbook_titles = [
        "Проверка отсутствия интернета в кабинете",
        "Массовый сбой Wi-Fi",
        "Не работает принтер",
        "Сброс пароля пользователя",
        "Нет доступа к Platonus",
        "Нет доступа к Moodle",
        "Подозрение на фишинговое письмо",
        "Не включается компьютер",
        "Проверка проектора",
        "Сбой корпоративной почты",
        "Проверка сервера",
        "Проверка коммутатора",
        "Проверка Zimbra mock health",
        "Проверка LDAP mock sync",
        "Обработка критичной заявки",
    ]

    def runbook_steps(title: str) -> list[dict[str, Any]]:
        return [
            {
                "step_number": 1,
                "title": f"Подтверждение инцидента: {title}",
                "instruction": "Проверить входные данные заявки и уточнить влияние.",
                "expected_result": "Инцидент подтвержден и классифицирован.",
                "is_manual": True,
                "safety_note": "Только анализ, без изменений в продакшене.",
            },
            {
                "step_number": 2,
                "title": "Demo диагностика",
                "instruction": "Выполнить mock-check через безопасный режим.",
                "expected_result": "Получен диагностический результат в demo mode.",
                "is_manual": False,
                "safety_note": "Запрещены реальные внешние вызовы.",
            },
            {
                "step_number": 3,
                "title": "Фиксация результата",
                "instruction": "Добавить заметку и уведомить заинтересованных.",
                "expected_result": "История инцидента и уведомления обновлены.",
                "is_manual": True,
                "safety_note": "Не закрывать заявку автоматически без решения оператора.",
            },
        ]

    runbook_map = {item.code: item for item in db.scalars(select(Runbook).where(Runbook.tenant_id == tenant_id)).all()}
    for index, title in enumerate(runbook_titles, start=1):
        code = f"runbook_{index:02d}"
        item = runbook_map.get(code)
        payload_steps = runbook_steps(title)
        category = "security" if "фишинг" in title.lower() else ("network" if "интернет" in title.lower() or "wi-fi" in title.lower() or "коммутатор" in title.lower() else "service")
        severity = "CRITICAL" if "критич" in title.lower() or "фишинг" in title.lower() else ("HIGH" if "сбой" in title.lower() else "MEDIUM")
        if item is None:
            item = Runbook(
                id=_uuid(),
                tenant_id=tenant_id,
                code=code,
                title=title,
                description=f"Demo runbook: {title}",
                category=category,
                severity=severity,
                steps_json=_json_dump(payload_steps),
                estimated_minutes=20 if severity == "CRITICAL" else 15,
                is_active=True,
                created_at=now,
                updated_at=now,
            )
            db.add(item)
            db.flush()
            runbook_map[code] = item
        else:
            item.title = title
            item.description = f"Demo runbook: {title}"
            item.category = category
            item.severity = severity
            item.steps_json = _json_dump(payload_steps)
            item.is_active = True
            item.updated_at = now

    rules = [
        {
            "code": "critical_network_ticket_auto_assign",
            "name": "Critical network ticket auto-assign",
            "trigger_type": "ticket_created",
            "priority": 10,
            "conditions": {"mode": "any", "conditions": [{"path": "ticket.priority", "operator": "eq", "value": "CRITICAL"}, {"path": "ticket.category", "operator": "contains", "value": "Сеть"}]},
            "actions": [
                {"type": "assign_ticket", "assignee": "agent.network@sbs.local"},
                {"type": "create_notification", "recipient_email": "agent.network@sbs.local", "title": "Critical network ticket"},
                {"type": "attach_runbook", "runbook_title": "Проверка отсутствия интернета в кабинете"},
                {"type": "create_audit_log"},
            ],
        },
        {
            "code": "phishing_ticket_escalation",
            "name": "Phishing ticket escalation",
            "trigger_type": "ticket_created",
            "priority": 15,
            "conditions": {"mode": "any", "conditions": [{"path": "ticket.title", "operator": "contains", "value": "фишинг"}, {"path": "ticket.description", "operator": "contains", "value": "фишинг"}]},
            "actions": [
                {"type": "change_priority", "priority": "CRITICAL"},
                {"type": "assign_ticket", "assignee": "security@sbs.local"},
                {"type": "create_notification", "recipient_email": "security@sbs.local"},
                {"type": "attach_runbook", "runbook_title": "Подозрение на фишинговое письмо"},
            ],
        },
        {
            "code": "printer_issue_runbook",
            "name": "Printer issue runbook",
            "trigger_type": "ticket_created",
            "priority": 30,
            "conditions": {"mode": "any", "conditions": [{"path": "ticket.category", "operator": "contains", "value": "Принтер"}]},
            "actions": [
                {"type": "attach_runbook", "runbook_title": "Не работает принтер"},
                {"type": "suggest_knowledge_article"},
            ],
        },
        {
            "code": "sla_breached_escalation",
            "name": "SLA breached escalation",
            "trigger_type": "sla_breached",
            "priority": 20,
            "conditions": {},
            "actions": [
                {"type": "create_notification", "recipient_email": "manager@sbs.local", "title": "SLA breached"},
                {"type": "create_audit_log"},
                {"type": "create_task_note", "message": "SLA breached escalation created."},
            ],
        },
        {
            "code": "ai_confidence_high_suggestion",
            "name": "AI confidence high suggestion",
            "trigger_type": "ai_suggestion_created",
            "priority": 40,
            "conditions": {"mode": "all", "conditions": [{"path": "ai.confidence", "operator": "gte", "value": 0.85}]},
            "actions": [
                {"type": "suggest_knowledge_article"},
                {"type": "create_notification", "recipient_email": "agent.support@sbs.local"},
            ],
        },
        {
            "code": "integration_failed_event",
            "name": "Integration failed event",
            "trigger_type": "integration_event_received",
            "priority": 25,
            "conditions": {"mode": "all", "conditions": [{"path": "integration_event.status", "operator": "eq", "value": "failed"}]},
            "actions": [
                {"type": "create_task_note", "message": "Integration failed event captured."},
                {"type": "create_notification", "recipient_email": "manager@sbs.local"},
                {"type": "attach_runbook", "runbook_title": "Проверка сервера"},
            ],
        },
        {
            "code": "new_user_access_request",
            "name": "New user access request",
            "trigger_type": "ticket_created",
            "priority": 45,
            "conditions": {"mode": "all", "conditions": [{"path": "ticket.category", "operator": "contains", "value": "Доступ"}]},
            "actions": [
                {"type": "create_approval_request", "title": "Access approval", "approver_name": "IT Manager"},
                {"type": "attach_runbook", "runbook_title": "Сброс пароля пользователя"},
            ],
        },
        {
            "code": "moodle_issue",
            "name": "Moodle issue",
            "trigger_type": "ticket_created",
            "priority": 50,
            "conditions": {"mode": "all", "conditions": [{"path": "ticket.description", "operator": "contains", "value": "moodle"}]},
            "actions": [
                {"type": "attach_runbook", "runbook_title": "Нет доступа к Moodle"},
                {"type": "assign_ticket", "assignee": "agent.support@sbs.local"},
            ],
        },
        {
            "code": "platonus_issue",
            "name": "Platonus issue",
            "trigger_type": "ticket_created",
            "priority": 55,
            "conditions": {"mode": "all", "conditions": [{"path": "ticket.description", "operator": "contains", "value": "platonus"}]},
            "actions": [
                {"type": "attach_runbook", "runbook_title": "Нет доступа к Platonus"},
                {"type": "assign_ticket", "assignee": "agent.support@sbs.local"},
            ],
        },
        {
            "code": "mail_issue",
            "name": "Mail issue",
            "trigger_type": "ticket_created",
            "priority": 60,
            "conditions": {"mode": "any", "conditions": [{"path": "ticket.description", "operator": "contains", "value": "почта"}, {"path": "ticket.description", "operator": "contains", "value": "zimbra"}]},
            "actions": [
                {"type": "attach_runbook", "runbook_title": "Сбой корпоративной почты"},
                {"type": "create_mock_email_log"},
            ],
        },
        {
            "code": "hardware_issue",
            "name": "Hardware issue",
            "trigger_type": "ticket_created",
            "priority": 65,
            "conditions": {"mode": "all", "conditions": [{"path": "ticket.category", "operator": "contains", "value": "Оборудование"}]},
            "actions": [
                {"type": "attach_runbook", "runbook_title": "Не включается компьютер"},
                {"type": "suggest_knowledge_article"},
            ],
        },
        {
            "code": "manual_executive_check",
            "name": "Manual executive check",
            "trigger_type": "manual_run",
            "priority": 5,
            "conditions": {},
            "actions": [
                {"type": "create_audit_log"},
                {"type": "create_notification", "recipient_email": "manager@sbs.local", "title": "Manual executive automation run"},
                {"type": "create_task_note", "message": "Manual executive check executed in demo mode."},
            ],
        },
    ]

    rule_map = {item.code: item for item in db.scalars(select(AutomationRule).where(AutomationRule.tenant_id == tenant_id)).all()}
    for item in rules:
        existing = rule_map.get(item["code"])
        if existing is None:
            existing = AutomationRule(
                id=_uuid(),
                tenant_id=tenant_id,
                code=item["code"],
                name=item["name"],
                description=f"Demo automation rule: {item['name']}",
                trigger_type=item["trigger_type"],
                conditions_json=_json_dump(item["conditions"]),
                actions_json=_json_dump(item["actions"]),
                is_active=True,
                priority=item["priority"],
                created_at=now,
                updated_at=now,
            )
            db.add(existing)
            db.flush()
            rule_map[item["code"]] = existing
        else:
            existing.name = item["name"]
            existing.description = f"Demo automation rule: {item['name']}"
            existing.trigger_type = item["trigger_type"]
            existing.conditions_json = _json_dump(item["conditions"])
            existing.actions_json = _json_dump(item["actions"])
            existing.is_active = True
            existing.priority = item["priority"]
            existing.updated_at = now

    if int(db.scalar(select(func.count(AutomationRun.id)).where(AutomationRun.tenant_id == tenant_id)) or 0) < 20:
        rule_items = list(rule_map.values())
        for index in range(20):
            rule = rule_items[index % len(rule_items)]
            status = "simulated" if index % 5 else "failed"
            run = AutomationRun(
                id=_uuid(),
                tenant_id=tenant_id,
                rule_id=rule.id,
                trigger_type=rule.trigger_type,
                trigger_entity_type="ticket",
                trigger_entity_id=f"demo-ticket-{index + 1}",
                status=status,
                started_at=now,
                finished_at=now,
                result_summary=_json_dump({"seed": True, "index": index + 1, "status": status}),
                error_message=None if status == "simulated" else "Demo warning",
                created_at=now,
            )
            db.add(run)

    db.flush()
    run_ids = list(db.scalars(select(AutomationRun.id).where(AutomationRun.tenant_id == tenant_id)).all())
    if int(db.scalar(select(func.count(AutomationActionLog.id)).where(AutomationActionLog.tenant_id == tenant_id)) or 0) < 30 and run_ids:
        for index in range(30):
            db.add(
                AutomationActionLog(
                    id=_uuid(),
                    tenant_id=tenant_id,
                    automation_run_id=run_ids[index % len(run_ids)],
                    action_type=["assign_ticket", "create_notification", "attach_runbook", "create_audit_log", "create_task_note"][index % 5],
                    status="simulated" if index % 6 else "failed",
                    input_json=_json_dump({"index": index + 1}),
                    output_json=_json_dump({"result": "demo"}),
                    error_message=None if index % 6 else "Demo action error",
                    created_at=now,
                )
            )

    if int(db.scalar(select(func.count(ApprovalRequest.id)).where(ApprovalRequest.tenant_id == tenant_id)) or 0) < 8:
        for index in range(8):
            db.add(
                ApprovalRequest(
                    id=_uuid(),
                    tenant_id=tenant_id,
                    title=f"Approval #{index + 1}",
                    description="Demo approval for workflow automation.",
                    entity_type="ticket",
                    entity_id=f"demo-ticket-{index + 1}",
                    requested_by=actor_email,
                    approver_name="IT Manager",
                    status="pending" if index % 3 else "approved",
                    decision_comment="Approved in demo" if index % 3 == 0 else None,
                    created_at=now,
                    decided_at=now if index % 3 == 0 else None,
                )
            )

    runbook_ids = list(db.scalars(select(Runbook.id).where(Runbook.tenant_id == tenant_id)).all())
    if int(db.scalar(select(func.count(RunbookExecution.id)).where(RunbookExecution.tenant_id == tenant_id)) or 0) < 8 and runbook_ids:
        for index in range(8):
            db.add(
                RunbookExecution(
                    id=_uuid(),
                    tenant_id=tenant_id,
                    runbook_id=runbook_ids[index % len(runbook_ids)],
                    ticket_id=None,
                    status="simulated" if index % 3 else "running",
                    current_step=3 if index % 3 else 2,
                    started_by=actor_email,
                    started_at=now,
                    completed_at=None,
                    result_summary="Demo execution preview; completion was not confirmed.",
                    created_at=now,
                )
            )
