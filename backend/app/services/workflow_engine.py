from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
import hashlib
import json
import re
import uuid
from typing import Any

from sqlalchemy import and_, delete, func, or_, select, text
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models.ticket import Ticket
from app.models.ticket_comment import TicketComment
from app.models.ticket_history import TicketHistory
from app.models.workflow_engine import (
    WorkflowApproval,
    WorkflowDefinition,
    WorkflowExecution,
    WorkflowExecutionEvent,
    WorkflowStepExecution,
    WorkflowVersion,
)
from app.services.audit import log_audit
from app.services.cmdb_schema import canonical_json
from app.services.integration_platform import queue_outbound_webhook_event
from app.services.notifications import create_notification
from app.services.ticket_lifecycle import (
    CANONICAL_TICKET_STATUSES,
    TicketLifecycleError,
    canonical_ticket_status,
    transition_ticket_status,
)


WORKFLOW_SCHEMA_VERSION = "1.0"
WORKFLOW_NODE_TYPES = {
    "CONDITION",
    "ACTION",
    "WAIT",
    "APPROVAL",
    "SUBFLOW",
    "END",
}
WORKFLOW_ACTION_CATALOG: dict[str, dict[str, Any]] = {
    "ticket.add_comment": {
        "description": "Add an auditable ticket comment",
        "required": ["ticket_id", "message"],
        "compensatable": False,
    },
    "ticket.set_priority": {
        "description": "Set ticket priority and retain previous value",
        "required": ["ticket_id", "priority"],
        "compensatable": True,
    },
    "ticket.assign": {
        "description": "Assign a ticket by display name",
        "required": ["ticket_id", "assignee_name"],
        "compensatable": True,
    },
    "ticket.transition": {
        "description": "Transition a ticket to an allowed lifecycle status",
        "required": ["ticket_id", "status"],
        "compensatable": True,
    },
    "notification.create": {
        "description": "Create an in-app notification and governed outboxes",
        "required": ["recipient_email", "title", "message"],
        "compensatable": False,
    },
    "integration.emit": {
        "description": "Queue a signed outbound integration event",
        "required": ["event_type", "data"],
        "compensatable": False,
    },
    "context.set_variable": {
        "description": "Set a workflow-local variable",
        "required": ["name", "value"],
        "compensatable": True,
    },
    "workflow.fail": {
        "description": "Fail deliberately for governed exception paths",
        "required": ["message"],
        "compensatable": False,
    },
}
WORKFLOW_TRIGGER_CATALOG = [
    "ticket_created",
    "ticket_assigned",
    "ticket_status_changed",
    "ticket_priority_changed",
    "ticket_comment_added",
    "asset_moved",
    "asset_verified",
    "asset_disposed",
    "knowledge_article_published",
    "report_exported",
    "integration_health_down",
    "webhook_received",
    "integration_event_failed",
    "import_job_completed",
    "manual",
]
_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]{2,119}$")
_NODE_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{1,79}$")
_VARIABLE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
_TEMPLATE_PATTERN = re.compile(r"\$\{([a-zA-Z0-9_.-]+)\}")
_SENSITIVE_PARTS = {
    "authorization",
    "api_key",
    "apikey",
    "client_secret",
    "credential",
    "password",
    "private_key",
    "secret",
    "token",
}
_NONTERMINAL_EXECUTION_STATUSES = {
    "QUEUED",
    "RUNNING",
    "WAITING_TIMER",
    "WAITING_APPROVAL",
    "WAITING_SUBFLOW",
    "RETRY",
    "COMPENSATING",
}
_TERMINAL_EXECUTION_STATUSES = {
    "SUCCEEDED",
    "FAILED",
    "CANCELLED",
    "DEAD_LETTER",
    "DROPPED",
}
_TICKET_PRIORITIES = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
_TICKET_STATUSES = CANONICAL_TICKET_STATUSES


class WorkflowEngineError(RuntimeError):
    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


def utcnow() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _safe_json_value(value: Any) -> Any:
    return json.loads(
        json.dumps(
            value,
            ensure_ascii=False,
            default=lambda item: item.isoformat()
            if isinstance(item, (date, datetime))
            else str(item),
        )
    )


def _json_object(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _definition_hash(definition: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(definition).encode("utf-8")).hexdigest()


def _assert_secret_safe(value: Any, *, path: str = "value", depth: int = 0) -> None:
    if depth > 16:
        raise ValueError(f"{path} exceeds the maximum nesting depth")
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).strip().lower().replace("-", "_")
            if any(part in normalized for part in _SENSITIVE_PARTS):
                raise ValueError(
                    f"secret-like field {path}.{key} is not allowed"
                )
            _assert_secret_safe(child, path=f"{path}.{key}", depth=depth + 1)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _assert_secret_safe(
                child,
                path=f"{path}[{index}]",
                depth=depth + 1,
            )


def _path_value(root: dict[str, Any], path: str) -> Any:
    def walk(start: Any, parts: list[str]) -> Any:
        current = start
        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return None
        return current

    parts = [part for part in path.split(".") if part]
    direct = walk(root, parts)
    if direct is not None:
        return direct
    if parts and parts[0] not in {"context", "variables", "steps"}:
        return walk(root.get("context", {}), parts)
    return None


def _resolve_value(value: Any, runtime: dict[str, Any]) -> Any:
    if isinstance(value, dict):
        return {str(key): _resolve_value(child, runtime) for key, child in value.items()}
    if isinstance(value, list):
        return [_resolve_value(child, runtime) for child in value]
    if not isinstance(value, str):
        return value
    full = _TEMPLATE_PATTERN.fullmatch(value.strip())
    if full:
        return _path_value(runtime, full.group(1))

    def replace(match: re.Match[str]) -> str:
        resolved = _path_value(runtime, match.group(1))
        return "" if resolved is None else str(resolved)

    return _TEMPLATE_PATTERN.sub(replace, value)


def _condition_result(config: dict[str, Any], runtime: dict[str, Any]) -> bool:
    path = str(config.get("path", "")).strip()
    operator = str(config.get("operator", "eq")).strip().lower()
    expected = _resolve_value(config.get("value"), runtime)
    actual = _path_value(runtime, path)
    if operator in {"eq", "=="}:
        return actual == expected
    if operator in {"ne", "!="}:
        return actual != expected
    if operator == "contains":
        if isinstance(actual, (list, tuple, set, dict, str)):
            return expected in actual
        return False
    if operator == "in":
        return isinstance(expected, list) and actual in expected
    if operator == "exists":
        return actual is not None
    if operator == "not_exists":
        return actual is None
    if operator in {"gt", "gte", "lt", "lte"}:
        try:
            left = float(actual)
            right = float(expected)
        except (TypeError, ValueError):
            return False
        return {
            "gt": left > right,
            "gte": left >= right,
            "lt": left < right,
            "lte": left <= right,
        }[operator]
    return False


def _node_edges(node: dict[str, Any]) -> list[str]:
    node_type = str(node.get("type", "")).upper()
    next_value = node.get("next")
    if node_type == "CONDITION":
        if not isinstance(next_value, dict):
            return []
        return [
            str(next_value[key])
            for key in ("true", "false")
            if next_value.get(key)
        ]
    if node_type == "APPROVAL":
        if not isinstance(next_value, dict):
            return []
        return [
            str(next_value[key])
            for key in ("approved", "rejected", "timeout")
            if next_value.get(key)
        ]
    if isinstance(next_value, str) and next_value:
        return [next_value]
    return []


def _bounded_integer(
    value: Any,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> tuple[int, bool]:
    if isinstance(value, bool):
        return default, False
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default, False
    return parsed, minimum <= parsed <= maximum


def validate_workflow_definition(
    definition: dict[str, Any],
    *,
    expected_trigger_type: str | None = None,
) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(definition, dict):
        return {
            "valid": False,
            "errors": ["definition must be an object"],
            "warnings": [],
            "stats": {},
        }
    try:
        _assert_secret_safe(definition, path="definition")
    except ValueError as exc:
        errors.append(str(exc))
    if definition.get("schema_version") != WORKFLOW_SCHEMA_VERSION:
        errors.append(f"schema_version must be {WORKFLOW_SCHEMA_VERSION}")
    trigger = definition.get("trigger")
    trigger_type = (
        str(trigger.get("type", "")).strip()
        if isinstance(trigger, dict)
        else ""
    )
    if not _CODE_PATTERN.fullmatch(trigger_type):
        errors.append("trigger.type must be a valid workflow event code")
    if expected_trigger_type and trigger_type != expected_trigger_type:
        errors.append("trigger.type must match the workflow trigger_type")
    entrypoint = str(definition.get("entrypoint", "")).strip()
    nodes = definition.get("nodes")
    if not isinstance(nodes, list) or not 1 <= len(nodes) <= 100:
        errors.append("nodes must contain 1-100 objects")
        nodes = []
    node_map: dict[str, dict[str, Any]] = {}
    action_count = approval_count = wait_count = subflow_count = 0
    for index, raw_node in enumerate(nodes):
        if not isinstance(raw_node, dict):
            errors.append(f"nodes[{index}] must be an object")
            continue
        key = str(raw_node.get("key", "")).strip()
        node_type = str(raw_node.get("type", "")).strip().upper()
        if not _NODE_KEY_PATTERN.fullmatch(key):
            errors.append(f"nodes[{index}].key is invalid")
            continue
        if key in node_map:
            errors.append(f"duplicate node key: {key}")
            continue
        node_map[key] = raw_node
        if node_type not in WORKFLOW_NODE_TYPES:
            errors.append(f"node {key} has unsupported type {node_type}")
            continue
        config = raw_node.get("config", {})
        if not isinstance(config, dict):
            errors.append(f"node {key}.config must be an object")
            config = {}
        retry = raw_node.get("retry", {})
        if retry is not None and not isinstance(retry, dict):
            errors.append(f"node {key}.retry must be an object")
            retry = {}
        max_attempts, max_attempts_valid = _bounded_integer(
            retry.get("max_attempts", 1) if retry else 1,
            default=1,
            minimum=1,
            maximum=10,
        )
        backoff_seconds, backoff_valid = _bounded_integer(
            retry.get("backoff_seconds", 30) if retry else 30,
            default=30,
            minimum=1,
            maximum=3_600,
        )
        if not max_attempts_valid:
            errors.append(f"node {key} retry.max_attempts must be 1-10")
        if not backoff_valid:
            errors.append(f"node {key} retry.backoff_seconds must be 1-3600")

        if node_type == "ACTION":
            action_count += 1
            action = str(config.get("action", "")).strip()
            contract = WORKFLOW_ACTION_CATALOG.get(action)
            if contract is None:
                errors.append(f"node {key} has unsupported action {action}")
            else:
                for required in contract["required"]:
                    if required not in config:
                        errors.append(f"node {key}.config.{required} is required")
                if action == "ticket.transition" and "status" in config:
                    configured_status = str(config.get("status", "")).strip()
                    if (
                        not _TEMPLATE_PATTERN.search(configured_status)
                        and canonical_ticket_status(configured_status) is None
                    ):
                        errors.append(
                            f"node {key}.config.status is an unknown ticket status"
                        )
            compensation = raw_node.get("compensation")
            if compensation is not None:
                if not isinstance(compensation, dict):
                    errors.append(f"node {key}.compensation must be an object")
                else:
                    if contract is not None and not contract["compensatable"]:
                        errors.append(
                            f"node {key} action {action} does not support compensation"
                        )
                    compensation_action = str(
                        compensation.get("action", "")
                    ).strip()
                    compensation_contract = WORKFLOW_ACTION_CATALOG.get(
                        compensation_action
                    )
                    if compensation_contract is None:
                        errors.append(
                            f"node {key} has unsupported compensation action"
                        )
                    else:
                        for required in compensation_contract["required"]:
                            if required not in compensation:
                                errors.append(
                                    f"node {key}.compensation.{required} is required"
                                )
        elif node_type == "WAIT":
            wait_count += 1
            seconds = config.get("seconds")
            if not isinstance(seconds, int) or not 1 <= seconds <= 2_592_000:
                errors.append(f"node {key}.config.seconds must be 1-2592000")
        elif node_type == "APPROVAL":
            approval_count += 1
            role = str(config.get("approver_role", "")).strip()
            timeout = config.get("timeout_minutes", 1_440)
            if not _NODE_KEY_PATTERN.fullmatch(role):
                errors.append(f"node {key}.config.approver_role is invalid")
            if not isinstance(timeout, int) or not 1 <= timeout <= 43_200:
                errors.append(
                    f"node {key}.config.timeout_minutes must be 1-43200"
                )
        elif node_type == "SUBFLOW":
            subflow_count += 1
            workflow_code = str(config.get("workflow_code", "")).strip()
            child_context = config.get("context", {})
            max_wait_seconds = config.get("max_wait_seconds", 86_400)
            failure_policy = str(
                config.get("failure_policy", "FAIL")
            ).upper()
            if not _CODE_PATTERN.fullmatch(workflow_code):
                errors.append(
                    f"node {key}.config.workflow_code is invalid"
                )
            if not isinstance(child_context, dict):
                errors.append(f"node {key}.config.context must be an object")
            if (
                not isinstance(max_wait_seconds, int)
                or isinstance(max_wait_seconds, bool)
                or not 60 <= max_wait_seconds <= 2_592_000
            ):
                errors.append(
                    f"node {key}.config.max_wait_seconds must be 60-2592000"
                )
            if failure_policy not in {"FAIL", "CONTINUE"}:
                errors.append(
                    f"node {key}.config.failure_policy must be FAIL or CONTINUE"
                )
        elif node_type == "CONDITION":
            path = str(config.get("path", "")).strip()
            operator = str(config.get("operator", "")).strip().lower()
            if not path:
                errors.append(f"node {key}.config.path is required")
            if operator not in {
                "eq",
                "ne",
                "contains",
                "in",
                "exists",
                "not_exists",
                "gt",
                "gte",
                "lt",
                "lte",
            }:
                errors.append(f"node {key}.config.operator is unsupported")

    if entrypoint not in node_map:
        errors.append("entrypoint must reference an existing node")
    for key, node in node_map.items():
        node_type = str(node.get("type", "")).upper()
        edges = _node_edges(node)
        if node_type == "END" and edges:
            errors.append(f"END node {key} cannot have next")
        elif node_type == "CONDITION":
            next_value = node.get("next")
            if not isinstance(next_value, dict) or not all(
                next_value.get(branch) for branch in ("true", "false")
            ):
                errors.append(f"CONDITION node {key} requires true/false branches")
        elif node_type == "APPROVAL":
            next_value = node.get("next")
            if not isinstance(next_value, dict) or not all(
                next_value.get(branch)
                for branch in ("approved", "rejected", "timeout")
            ):
                errors.append(
                    f"APPROVAL node {key} requires approved/rejected/timeout branches"
                )
        elif node_type != "END" and len(edges) != 1:
            errors.append(f"node {key} requires exactly one next node")
        for target in edges:
            if target not in node_map:
                errors.append(f"node {key} references missing node {target}")

    reachable: set[str] = set()
    visiting: set[str] = set()
    visited: set[str] = set()
    cycle_detected = False

    def visit(key: str) -> None:
        nonlocal cycle_detected
        if key in visiting:
            cycle_detected = True
            return
        if key in visited or key not in node_map:
            return
        visiting.add(key)
        reachable.add(key)
        for target in _node_edges(node_map[key]):
            visit(target)
        visiting.remove(key)
        visited.add(key)

    if entrypoint in node_map:
        visit(entrypoint)
    if cycle_detected:
        errors.append("workflow graph contains a cycle")
    unreachable = sorted(set(node_map) - reachable)
    if unreachable:
        warnings.append("unreachable nodes: " + ", ".join(unreachable))
    if not any(
        str(node.get("type", "")).upper() == "END"
        for key, node in node_map.items()
        if key in reachable
    ):
        errors.append("workflow requires a reachable END node")
    on_failure = str(definition.get("on_failure", "FAIL")).upper()
    if on_failure not in {"FAIL", "COMPENSATE"}:
        errors.append("on_failure must be FAIL or COMPENSATE")
    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "stats": {
            "nodes": len(node_map),
            "reachable_nodes": len(reachable),
            "actions": action_count,
            "approvals": approval_count,
            "waits": wait_count,
            "subflows": subflow_count,
        },
    }


def default_workflow_definition(trigger_type: str) -> dict[str, Any]:
    return {
        "schema_version": WORKFLOW_SCHEMA_VERSION,
        "trigger": {"type": trigger_type},
        "entrypoint": "end",
        "on_failure": "FAIL",
        "nodes": [
            {
                "key": "end",
                "type": "END",
                "name": "Complete workflow",
                "config": {},
            }
        ],
    }


def create_workflow(
    db: Session,
    *,
    tenant_id: str,
    code: str,
    name: str,
    description: str | None,
    trigger_type: str,
    concurrency_policy: str,
    max_active_executions: int,
    actor_id: str | None,
    publish_approval_required: bool = False,
) -> tuple[WorkflowDefinition, WorkflowVersion]:
    code = code.strip().lower()
    trigger_type = trigger_type.strip().lower()
    workflow_name = name.strip()
    if not _CODE_PATTERN.fullmatch(code):
        raise ValueError("Workflow code is invalid")
    if not _CODE_PATTERN.fullmatch(trigger_type):
        raise ValueError("Workflow trigger type is invalid")
    if len(workflow_name) < 2:
        raise ValueError("Workflow name must contain at least 2 characters")
    concurrency_policy = concurrency_policy.strip().upper()
    if concurrency_policy not in {"ALLOW", "SERIALIZE"}:
        raise ValueError("Unsupported concurrency policy")
    if not 1 <= max_active_executions <= 1_000:
        raise ValueError("max_active_executions must be 1-1000")
    now = utcnow()
    workflow = WorkflowDefinition(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        code=code,
        name=workflow_name,
        description=description.strip() if description else None,
        status="PAUSED",
        trigger_type=trigger_type,
        concurrency_policy=concurrency_policy,
        max_active_executions=max_active_executions,
        publish_approval_required=publish_approval_required,
        latest_version_number=1,
        draft_version_number=1,
        published_version_number=None,
        revision=1,
        total_executions=0,
        failed_executions=0,
        created_by_id=actor_id,
        updated_by_id=actor_id,
        created_at=now,
        updated_at=now,
    )
    definition = default_workflow_definition(trigger_type)
    validation = validate_workflow_definition(
        definition,
        expected_trigger_type=trigger_type,
    )
    version = WorkflowVersion(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        workflow_id=workflow.id,
        version_number=1,
        status="DRAFT",
        definition_json=canonical_json(definition),
        definition_sha256=_definition_hash(definition),
        validation_status="VALID",
        validation_json=canonical_json(validation),
        revision=1,
        based_on_version_number=None,
        rollback_from_version_number=None,
        change_summary="Initial draft",
        review_status=(
            "PENDING" if publish_approval_required else "NOT_REQUIRED"
        ),
        created_by_id=actor_id,
        updated_by_id=actor_id,
        created_at=now,
        updated_at=now,
    )
    db.add_all([workflow, version])
    db.flush()
    return workflow, version


def create_workflow_draft(
    db: Session,
    workflow: WorkflowDefinition,
    *,
    actor_id: str | None,
    change_summary: str,
) -> WorkflowVersion:
    if workflow.status == "ARCHIVED":
        raise ValueError("Archived workflow cannot create drafts")
    if workflow.draft_version_number is not None:
        raise ValueError("Workflow already has an editable draft")
    source: WorkflowVersion | None = None
    if workflow.published_version_number is not None:
        source = db.scalar(
            select(WorkflowVersion).where(
                WorkflowVersion.workflow_id == workflow.id,
                WorkflowVersion.version_number
                == workflow.published_version_number,
            )
        )
    definition = (
        _json_object(source.definition_json)
        if source is not None
        else default_workflow_definition(workflow.trigger_type)
    )
    number = workflow.latest_version_number + 1
    validation = validate_workflow_definition(
        definition,
        expected_trigger_type=workflow.trigger_type,
    )
    now = utcnow()
    version = WorkflowVersion(
        id=str(uuid.uuid4()),
        tenant_id=workflow.tenant_id,
        workflow_id=workflow.id,
        version_number=number,
        status="DRAFT",
        definition_json=canonical_json(definition),
        definition_sha256=_definition_hash(definition),
        validation_status="VALID" if validation["valid"] else "INVALID",
        validation_json=canonical_json(validation),
        revision=1,
        based_on_version_number=(
            source.version_number if source is not None else None
        ),
        rollback_from_version_number=None,
        change_summary=change_summary.strip(),
        review_status=(
            "PENDING" if workflow.publish_approval_required else "NOT_REQUIRED"
        ),
        created_by_id=actor_id,
        updated_by_id=actor_id,
        created_at=now,
        updated_at=now,
    )
    workflow.latest_version_number = number
    workflow.draft_version_number = number
    workflow.revision += 1
    workflow.updated_by_id = actor_id
    workflow.updated_at = now
    db.add(version)
    db.flush()
    return version


def update_workflow_draft(
    version: WorkflowVersion,
    workflow: WorkflowDefinition,
    *,
    definition: dict[str, Any],
    expected_revision: int,
    change_summary: str,
    actor_id: str | None,
) -> dict[str, Any]:
    if version.status != "DRAFT":
        raise ValueError("Published workflow versions are immutable")
    if version.revision != expected_revision:
        raise ValueError(
            f"Draft changed; current revision is {version.revision}"
        )
    safe_definition = _safe_json_value(definition)
    validation = validate_workflow_definition(
        safe_definition,
        expected_trigger_type=workflow.trigger_type,
    )
    version.definition_json = canonical_json(safe_definition)
    version.definition_sha256 = _definition_hash(safe_definition)
    version.validation_status = "VALID" if validation["valid"] else "INVALID"
    version.validation_json = canonical_json(validation)
    version.change_summary = change_summary.strip()
    version.updated_by_id = actor_id
    version.review_status = (
        "PENDING" if workflow.publish_approval_required else "NOT_REQUIRED"
    )
    version.review_requested_by_id = None
    version.reviewed_by_id = None
    version.review_comment = None
    version.review_requested_at = None
    version.reviewed_at = None
    version.revision += 1
    version.updated_at = utcnow()
    workflow.updated_by_id = actor_id
    workflow.updated_at = utcnow()
    return validation


def request_workflow_review(
    version: WorkflowVersion,
    workflow: WorkflowDefinition,
    *,
    expected_revision: int,
    actor_id: str,
    comment: str,
) -> WorkflowVersion:
    if not workflow.publish_approval_required:
        raise ValueError("Workflow does not require publish approval")
    if version.status != "DRAFT":
        raise ValueError("Only a draft version can be reviewed")
    if version.revision != expected_revision:
        raise ValueError(f"Draft changed; current revision is {version.revision}")
    definition = _json_object(version.definition_json)
    if _definition_hash(definition) != version.definition_sha256:
        raise ValueError("Workflow draft integrity check failed")
    validation = validate_workflow_definition(
        definition,
        expected_trigger_type=workflow.trigger_type,
    )
    if not validation["valid"]:
        raise ValueError("Workflow draft must be valid before review")
    now = utcnow()
    version.review_status = "PENDING"
    version.review_requested_by_id = actor_id
    version.reviewed_by_id = None
    version.review_comment = comment.strip()
    version.review_requested_at = now
    version.reviewed_at = None
    version.revision += 1
    version.updated_at = now
    return version


def decide_workflow_review(
    version: WorkflowVersion,
    workflow: WorkflowDefinition,
    *,
    expected_revision: int,
    actor_id: str,
    decision: str,
    comment: str,
) -> WorkflowVersion:
    if not workflow.publish_approval_required:
        raise ValueError("Workflow does not require publish approval")
    if version.status != "DRAFT":
        raise ValueError("Only a draft version can be reviewed")
    if version.revision != expected_revision:
        raise ValueError(f"Draft changed; current revision is {version.revision}")
    if version.review_status != "PENDING" or not version.review_requested_at:
        raise ValueError("Workflow review is not pending")
    if actor_id in {
        version.review_requested_by_id,
        version.created_by_id,
        version.updated_by_id,
    }:
        raise ValueError(
            "Workflow author or last editor cannot approve their own review"
        )
    normalized_decision = decision.strip().upper()
    if normalized_decision not in {"APPROVED", "REJECTED"}:
        raise ValueError("Review decision must be APPROVED or REJECTED")
    now = utcnow()
    version.review_status = normalized_decision
    version.reviewed_by_id = actor_id
    version.review_comment = comment.strip()
    version.reviewed_at = now
    version.revision += 1
    version.updated_at = now
    return version


def _flatten_definition(
    value: Any,
    *,
    path: str = "",
    output: dict[str, Any] | None = None,
) -> dict[str, Any]:
    flattened = output if output is not None else {}
    if len(flattened) >= 5_000:
        raise ValueError("Workflow diff exceeds the safety limit")
    if isinstance(value, dict):
        if not value:
            flattened[path or "/"] = {}
        for key in sorted(value):
            escaped = str(key).replace("~", "~0").replace("/", "~1")
            _flatten_definition(
                value[key],
                path=f"{path}/{escaped}",
                output=flattened,
            )
    elif isinstance(value, list):
        if not value:
            flattened[path or "/"] = []
        for index, item in enumerate(value):
            _flatten_definition(
                item,
                path=f"{path}/{index}",
                output=flattened,
            )
    else:
        flattened[path or "/"] = value
    return flattened


def compare_workflow_versions(
    source: WorkflowVersion,
    target: WorkflowVersion,
) -> dict[str, Any]:
    if source.workflow_id != target.workflow_id:
        raise ValueError("Workflow versions must belong to the same workflow")
    source_definition = _json_object(source.definition_json)
    target_definition = _json_object(target.definition_json)
    if _definition_hash(source_definition) != source.definition_sha256:
        raise ValueError("Source workflow version integrity check failed")
    if _definition_hash(target_definition) != target.definition_sha256:
        raise ValueError("Target workflow version integrity check failed")
    before = _flatten_definition(source_definition)
    after = _flatten_definition(target_definition)
    added = [
        {"path": path, "value": after[path]}
        for path in sorted(after.keys() - before.keys())
    ]
    removed = [
        {"path": path, "value": before[path]}
        for path in sorted(before.keys() - after.keys())
    ]
    changed = [
        {
            "path": path,
            "before": before[path],
            "after": after[path],
        }
        for path in sorted(before.keys() & after.keys())
        if before[path] != after[path]
    ]
    return {
        "workflow_id": source.workflow_id,
        "from_version": source.version_number,
        "to_version": target.version_number,
        "from_sha256": source.definition_sha256,
        "to_sha256": target.definition_sha256,
        "summary": {
            "added": len(added),
            "removed": len(removed),
            "changed": len(changed),
            "total": len(added) + len(removed) + len(changed),
        },
        "added": added,
        "removed": removed,
        "changed": changed,
    }


def publish_workflow_version(
    db: Session,
    workflow: WorkflowDefinition,
    version: WorkflowVersion,
    *,
    expected_workflow_revision: int,
    expected_version_revision: int,
    actor_id: str | None,
    activate: bool,
) -> WorkflowVersion:
    if workflow.status == "ARCHIVED":
        raise ValueError("Archived workflow cannot publish")
    if workflow.revision != expected_workflow_revision:
        raise ValueError(
            f"Workflow changed; current revision is {workflow.revision}"
        )
    if version.status != "DRAFT":
        raise ValueError("Only a draft version can publish")
    if version.revision != expected_version_revision:
        raise ValueError(f"Draft changed; current revision is {version.revision}")
    if (
        workflow.publish_approval_required
        and version.review_status != "APPROVED"
    ):
        raise ValueError("Workflow draft requires an approved review")
    definition = _json_object(version.definition_json)
    if _definition_hash(definition) != version.definition_sha256:
        raise ValueError("Workflow draft integrity check failed")
    validation = validate_workflow_definition(
        definition,
        expected_trigger_type=workflow.trigger_type,
    )
    if not validation["valid"]:
        raise ValueError(
            "Workflow draft is invalid: " + "; ".join(validation["errors"])
        )
    now = utcnow()
    if workflow.published_version_number is not None:
        previous = db.scalar(
            select(WorkflowVersion).where(
                WorkflowVersion.workflow_id == workflow.id,
                WorkflowVersion.version_number
                == workflow.published_version_number,
            )
        )
        if previous is not None and previous.status == "PUBLISHED":
            previous.status = "RETIRED"
            previous.updated_at = now
    version.status = "PUBLISHED"
    version.validation_status = "VALID"
    version.validation_json = canonical_json(validation)
    version.published_by_id = actor_id
    version.published_at = now
    version.updated_at = now
    workflow.published_version_number = version.version_number
    workflow.draft_version_number = None
    workflow.status = "ACTIVE" if activate else "PAUSED"
    workflow.revision += 1
    workflow.updated_by_id = actor_id
    workflow.updated_at = now
    db.flush()
    return version


def rollback_workflow(
    db: Session,
    workflow: WorkflowDefinition,
    target: WorkflowVersion,
    *,
    expected_workflow_revision: int,
    actor_id: str | None,
    reason: str,
) -> WorkflowVersion:
    if workflow.revision != expected_workflow_revision:
        raise ValueError(
            f"Workflow changed; current revision is {workflow.revision}"
        )
    if workflow.status == "ARCHIVED":
        raise ValueError("Archived workflow cannot rollback")
    if target.workflow_id != workflow.id or target.status not in {
        "PUBLISHED",
        "RETIRED",
    }:
        raise ValueError("Rollback target must be a published workflow version")
    if workflow.draft_version_number is not None:
        raise ValueError("Resolve the current draft before rollback")
    definition = _json_object(target.definition_json)
    if _definition_hash(definition) != target.definition_sha256:
        raise ValueError("Rollback target integrity check failed")
    validation = validate_workflow_definition(
        definition,
        expected_trigger_type=workflow.trigger_type,
    )
    if not validation["valid"]:
        raise ValueError("Rollback target no longer validates")
    now = utcnow()
    if workflow.published_version_number is not None:
        current = db.scalar(
            select(WorkflowVersion).where(
                WorkflowVersion.workflow_id == workflow.id,
                WorkflowVersion.version_number
                == workflow.published_version_number,
            )
        )
        if current is not None and current.status == "PUBLISHED":
            current.status = "RETIRED"
            current.updated_at = now
    number = workflow.latest_version_number + 1
    restored = WorkflowVersion(
        id=str(uuid.uuid4()),
        tenant_id=workflow.tenant_id,
        workflow_id=workflow.id,
        version_number=number,
        status="PUBLISHED",
        definition_json=canonical_json(definition),
        definition_sha256=_definition_hash(definition),
        validation_status="VALID",
        validation_json=canonical_json(validation),
        revision=1,
        based_on_version_number=target.version_number,
        rollback_from_version_number=target.version_number,
        change_summary=reason.strip(),
        review_status="APPROVED",
        review_requested_by_id=actor_id,
        reviewed_by_id=actor_id,
        review_comment=f"Governed rollback: {reason.strip()}",
        review_requested_at=now,
        reviewed_at=now,
        created_by_id=actor_id,
        updated_by_id=actor_id,
        published_by_id=actor_id,
        published_at=now,
        created_at=now,
        updated_at=now,
    )
    workflow.latest_version_number = number
    workflow.published_version_number = number
    workflow.status = "ACTIVE"
    workflow.revision += 1
    workflow.updated_by_id = actor_id
    workflow.updated_at = now
    db.add(restored)
    db.flush()
    return restored


def simulate_workflow(
    definition: dict[str, Any],
    context: dict[str, Any],
    *,
    expected_trigger_type: str | None = None,
) -> dict[str, Any]:
    validation = validate_workflow_definition(
        definition,
        expected_trigger_type=expected_trigger_type,
    )
    if not validation["valid"]:
        return {
            "valid": False,
            "validation": validation,
            "trace": [],
            "completed": False,
        }
    safe_context = _safe_json_value(context)
    _assert_secret_safe(safe_context, path="context")
    runtime: dict[str, Any] = {
        "context": safe_context,
        "variables": {},
        "steps": {},
    }
    node_map = {
        str(node["key"]): node for node in definition["nodes"]
    }
    current = str(definition["entrypoint"])
    trace: list[dict[str, Any]] = []
    simulation = (
        safe_context.get("_simulation", {})
        if isinstance(safe_context.get("_simulation"), dict)
        else {}
    )
    approval_outcomes = (
        simulation.get("approvals", {})
        if isinstance(simulation.get("approvals"), dict)
        else {}
    )
    for sequence in range(1, 102):
        node = node_map[current]
        node_type = str(node["type"]).upper()
        config = node.get("config", {})
        entry: dict[str, Any] = {
            "sequence": sequence,
            "node_key": current,
            "node_type": node_type,
        }
        if node_type == "END":
            entry["outcome"] = "completed"
            trace.append(entry)
            return {
                "valid": True,
                "validation": validation,
                "trace": trace,
                "completed": True,
                "variables": runtime["variables"],
            }
        if node_type == "CONDITION":
            outcome = _condition_result(config, runtime)
            entry["outcome"] = outcome
            current = str(node["next"]["true" if outcome else "false"])
        elif node_type == "ACTION":
            resolved = _resolve_value(config, runtime)
            entry["outcome"] = "planned"
            entry["resolved_config"] = resolved
            if resolved.get("action") == "context.set_variable":
                name = str(resolved.get("name", ""))
                runtime["variables"][name] = resolved.get("value")
            runtime["steps"][str(node["key"])] = {
                "output": {"simulated": True},
            }
            current = str(node["next"])
        elif node_type == "WAIT":
            entry["outcome"] = "timer_skipped"
            entry["seconds"] = config["seconds"]
            current = str(node["next"])
        elif node_type == "SUBFLOW":
            entry["outcome"] = "subflow_planned"
            entry["workflow_code"] = config["workflow_code"]
            entry["resolved_context"] = _resolve_value(
                config.get("context", {}),
                runtime,
            )
            current = str(node["next"])
        elif node_type == "APPROVAL":
            outcome = str(
                approval_outcomes.get(current, "approved")
            ).lower()
            if outcome not in {"approved", "rejected", "timeout"}:
                outcome = "approved"
            entry["outcome"] = outcome
            current = str(node["next"][outcome])
        trace.append(entry)
    return {
        "valid": False,
        "validation": validation,
        "trace": trace,
        "completed": False,
        "error": "Simulation exceeded the node safety limit",
    }


def _published_version(
    db: Session,
    workflow: WorkflowDefinition,
) -> WorkflowVersion:
    if workflow.published_version_number is None:
        raise ValueError("Workflow has no published version")
    version = db.scalar(
        select(WorkflowVersion).where(
            WorkflowVersion.workflow_id == workflow.id,
            WorkflowVersion.version_number == workflow.published_version_number,
            WorkflowVersion.status == "PUBLISHED",
        )
    )
    if version is None:
        raise ValueError("Published workflow version is unavailable")
    return version


def _append_execution_event(
    db: Session,
    execution: WorkflowExecution,
    *,
    event_type: str,
    node_key: str | None,
    status: str | None,
    details: dict[str, Any] | None = None,
) -> WorkflowExecutionEvent:
    previous = db.scalar(
        select(WorkflowExecutionEvent)
        .where(WorkflowExecutionEvent.execution_id == execution.id)
        .order_by(WorkflowExecutionEvent.sequence_number.desc())
        .limit(1)
    )
    sequence = (previous.sequence_number if previous else 0) + 1
    previous_hash = previous.event_hash if previous else "0" * 64
    created_at = utcnow()
    safe_details = _safe_json_value(details or {})
    _assert_secret_safe(safe_details, path="event.details")
    material = canonical_json(
        {
            "execution_id": execution.id,
            "sequence": sequence,
            "event_type": event_type,
            "node_key": node_key,
            "status": status,
            "details": safe_details,
            "created_at": created_at.isoformat(),
            "previous_hash": previous_hash,
        }
    )
    event = WorkflowExecutionEvent(
        id=str(uuid.uuid4()),
        tenant_id=execution.tenant_id,
        execution_id=execution.id,
        sequence_number=sequence,
        event_type=event_type,
        node_key=node_key,
        status=status,
        details_json=canonical_json(safe_details),
        previous_hash=previous_hash,
        event_hash=hashlib.sha256(material.encode("utf-8")).hexdigest(),
        created_at=created_at,
    )
    db.add(event)
    db.flush()
    return event


def verify_workflow_event_chain(
    db: Session,
    execution_id: str,
) -> dict[str, Any]:
    events = db.scalars(
        select(WorkflowExecutionEvent)
        .where(WorkflowExecutionEvent.execution_id == execution_id)
        .order_by(WorkflowExecutionEvent.sequence_number)
    ).all()
    expected_previous_hash = "0" * 64
    for expected_sequence, event in enumerate(events, start=1):
        details = _json_object(event.details_json)
        material = canonical_json(
            {
                "execution_id": execution_id,
                "sequence": event.sequence_number,
                "event_type": event.event_type,
                "node_key": event.node_key,
                "status": event.status,
                "details": details,
                "created_at": _aware(event.created_at).isoformat(),
                "previous_hash": event.previous_hash,
            }
        )
        expected_hash = hashlib.sha256(material.encode("utf-8")).hexdigest()
        if (
            event.sequence_number != expected_sequence
            or event.previous_hash != expected_previous_hash
            or event.event_hash != expected_hash
        ):
            return {
                "valid": False,
                "checked_events": expected_sequence,
                "first_invalid_sequence": event.sequence_number,
                "expected_previous_hash": expected_previous_hash,
                "recorded_previous_hash": event.previous_hash,
                "expected_event_hash": expected_hash,
                "recorded_event_hash": event.event_hash,
            }
        expected_previous_hash = event.event_hash
    return {
        "valid": True,
        "checked_events": len(events),
        "first_invalid_sequence": None,
        "head_hash": expected_previous_hash,
    }


def _normalize_idempotency_key(value: str) -> str:
    normalized = value.strip()
    if not 8 <= len(normalized) <= 200:
        raise ValueError("Idempotency key must contain 8-200 characters")
    return normalized


def enqueue_workflow_execution(
    db: Session,
    workflow: WorkflowDefinition,
    *,
    context: dict[str, Any],
    idempotency_key: str,
    source: str,
    actor_id: str | None,
    correlation_id: str | None = None,
    replay_of_id: str | None = None,
    version: WorkflowVersion | None = None,
    settings: Settings | None = None,
) -> tuple[WorkflowExecution, bool]:
    runtime = settings or get_settings()
    if workflow.status == "ARCHIVED":
        raise ValueError("Archived workflow cannot execute")
    if source == "AUTOMATIC" and workflow.status != "ACTIVE":
        raise ValueError("Automatic workflow must be active")
    source = source.upper()
    if source not in {"AUTOMATIC", "MANUAL", "REPLAY"}:
        raise ValueError("Unsupported workflow execution source")
    key = _normalize_idempotency_key(idempotency_key)
    safe_context = _safe_json_value(context)
    _assert_secret_safe(safe_context, path="context")
    serialized_context = canonical_json(safe_context)
    if len(serialized_context.encode("utf-8")) > runtime.workflow_max_context_bytes:
        raise ValueError("Workflow context exceeds the configured limit")
    if db.get_bind().dialect.name == "postgresql":
        db.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:lock_key))"),
            {"lock_key": f"workflow:{workflow.id}:{key}"},
        )
    existing = db.scalar(
        select(WorkflowExecution).where(
            WorkflowExecution.workflow_id == workflow.id,
            WorkflowExecution.idempotency_key == key,
        )
    )
    if existing is not None:
        return existing, True
    selected_version = version or _published_version(db, workflow)
    definition = _json_object(selected_version.definition_json)
    if _definition_hash(definition) != selected_version.definition_sha256:
        raise ValueError("Published workflow version integrity check failed")
    entrypoint = str(definition.get("entrypoint", ""))
    active_count = int(
        db.scalar(
            select(func.count())
            .select_from(WorkflowExecution)
            .where(
                WorkflowExecution.workflow_id == workflow.id,
                WorkflowExecution.status.in_(_NONTERMINAL_EXECUTION_STATUSES),
            )
        )
        or 0
    )
    now = utcnow()
    dropped = active_count >= workflow.max_active_executions
    execution = WorkflowExecution(
        id=str(uuid.uuid4()),
        tenant_id=workflow.tenant_id,
        workflow_id=workflow.id,
        workflow_version_id=selected_version.id,
        workflow_version_number=selected_version.version_number,
        replay_of_id=replay_of_id,
        idempotency_key=key,
        source=source,
        trigger_type=workflow.trigger_type,
        trigger_entity_type=(
            str(safe_context.get("entity_type"))[:80]
            if safe_context.get("entity_type") is not None
            else None
        ),
        trigger_entity_id=(
            str(safe_context.get("entity_id"))[:120]
            if safe_context.get("entity_id") is not None
            else None
        ),
        status="DROPPED" if dropped else "QUEUED",
        current_node_key=entrypoint,
        context_json=serialized_context,
        variables_json="{}",
        output_json=(
            canonical_json({"reason": "max_active_executions"})
            if dropped
            else "{}"
        ),
        attempts=0,
        max_attempts=5,
        next_run_at=now,
        started_by_id=actor_id,
        correlation_id=correlation_id[:120] if correlation_id else None,
        last_error=(
            "Workflow active-execution limit reached" if dropped else None
        ),
        completed_at=now if dropped else None,
        created_at=now,
        updated_at=now,
    )
    db.add(execution)
    db.flush()
    workflow.total_executions += 1
    workflow.last_execution_at = now
    workflow.updated_at = now
    _append_execution_event(
        db,
        execution,
        event_type="execution_dropped" if dropped else "execution_queued",
        node_key=entrypoint,
        status=execution.status,
        details={
            "source": source,
            "version_number": selected_version.version_number,
            "reason": execution.last_error,
        },
    )
    return execution, False


def enqueue_matching_workflows(
    db: Session,
    *,
    tenant_id: str | None,
    trigger_type: str,
    context: dict[str, Any],
    actor_id: str | None,
    correlation_id: str | None = None,
) -> list[WorkflowExecution]:
    if not tenant_id:
        return []
    trigger_type = trigger_type.strip().lower()
    workflows = db.scalars(
        select(WorkflowDefinition)
        .where(
            WorkflowDefinition.tenant_id == tenant_id,
            WorkflowDefinition.trigger_type == trigger_type,
            WorkflowDefinition.status == "ACTIVE",
            WorkflowDefinition.published_version_number.is_not(None),
        )
        .order_by(WorkflowDefinition.created_at)
    ).all()
    safe_context = _safe_json_value(context)
    base_key = (
        str(safe_context.get("event_id") or safe_context.get("correlation_id"))
        if safe_context.get("event_id") or safe_context.get("correlation_id")
        else hashlib.sha256(canonical_json(safe_context).encode("utf-8")).hexdigest()
    )
    queued: list[WorkflowExecution] = []
    for workflow in workflows:
        execution, _ = enqueue_workflow_execution(
            db,
            workflow,
            context=safe_context,
            idempotency_key=f"event:{trigger_type}:{base_key}"[:200],
            source="AUTOMATIC",
            actor_id=actor_id,
            correlation_id=correlation_id,
        )
        queued.append(execution)
    return queued


def _definition_for_execution(
    db: Session,
    execution: WorkflowExecution,
) -> tuple[WorkflowVersion, dict[str, Any]]:
    version = db.get(WorkflowVersion, execution.workflow_version_id)
    if version is None:
        raise WorkflowEngineError("Workflow version is unavailable")
    definition = _json_object(version.definition_json)
    if _definition_hash(definition) != version.definition_sha256:
        raise WorkflowEngineError("Workflow version integrity check failed")
    return version, definition


def _runtime_context(
    db: Session,
    execution: WorkflowExecution,
) -> dict[str, Any]:
    steps = db.scalars(
        select(WorkflowStepExecution)
        .where(WorkflowStepExecution.execution_id == execution.id)
        .order_by(WorkflowStepExecution.sequence_number)
    ).all()
    return {
        "context": _json_object(execution.context_json),
        "variables": _json_object(execution.variables_json),
        "steps": {
            item.node_key: {
                "status": item.status,
                "output": _json_object(item.output_json),
                "compensation_output": _json_object(
                    item.compensation_output_json
                ),
            }
            for item in steps
        },
    }


def _get_or_create_step(
    db: Session,
    execution: WorkflowExecution,
    version: WorkflowVersion,
    node: dict[str, Any],
) -> WorkflowStepExecution:
    key = str(node["key"])
    existing = db.scalar(
        select(WorkflowStepExecution).where(
            WorkflowStepExecution.execution_id == execution.id,
            WorkflowStepExecution.node_key == key,
        )
    )
    if existing is not None:
        return existing
    sequence = int(
        db.scalar(
            select(func.max(WorkflowStepExecution.sequence_number)).where(
                WorkflowStepExecution.execution_id == execution.id
            )
        )
        or 0
    ) + 1
    retry = node.get("retry", {})
    max_attempts, _ = _bounded_integer(
        retry.get("max_attempts", 1) if isinstance(retry, dict) else 1,
        default=1,
        minimum=1,
        maximum=10,
    )
    step = WorkflowStepExecution(
        id=str(uuid.uuid4()),
        tenant_id=execution.tenant_id,
        execution_id=execution.id,
        workflow_version_id=version.id,
        node_key=key,
        node_type=str(node["type"]).upper(),
        sequence_number=sequence,
        status="PENDING",
        attempts=0,
        max_attempts=max_attempts,
        input_json="{}",
        output_json="{}",
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    db.add(step)
    db.flush()
    return step


def _ticket_for_action(
    db: Session,
    tenant_id: str,
    config: dict[str, Any],
    runtime: dict[str, Any],
) -> Ticket:
    ticket_id = config.get("ticket_id")
    if not ticket_id:
        ticket_id = _path_value(runtime, "context.ticket.id")
    if not ticket_id:
        ticket_id = _path_value(runtime, "context.entity_id")
    ticket = db.scalar(
        select(Ticket).where(
            Ticket.id == str(ticket_id),
            Ticket.tenant_id == tenant_id,
        ).with_for_update()
    )
    if ticket is None:
        raise WorkflowEngineError("Tenant-scoped ticket was not found")
    return ticket


def _execute_action_config(
    db: Session,
    execution: WorkflowExecution,
    *,
    node_key: str,
    config: dict[str, Any],
    runtime: dict[str, Any],
) -> dict[str, Any]:
    resolved = _resolve_value(config, runtime)
    action = str(resolved.get("action", "")).strip()
    if action not in WORKFLOW_ACTION_CATALOG:
        raise WorkflowEngineError(f"Unsupported workflow action: {action}")
    now = utcnow()
    if action == "workflow.fail":
        raise WorkflowEngineError(
            str(resolved.get("message") or "Workflow requested failure"),
            retryable=bool(resolved.get("retryable", False)),
        )
    if action == "context.set_variable":
        name = str(resolved.get("name", "")).strip()
        if not _VARIABLE_PATTERN.fullmatch(name):
            raise WorkflowEngineError("Workflow variable name is invalid")
        variables = _json_object(execution.variables_json)
        previous = variables.get(name)
        variables[name] = _safe_json_value(resolved.get("value"))
        execution.variables_json = canonical_json(variables)
        return {"name": name, "previous_value": previous, "value": variables[name]}
    if action.startswith("ticket."):
        ticket = _ticket_for_action(
            db,
            execution.tenant_id,
            resolved,
            runtime,
        )
        if action == "ticket.add_comment":
            message = str(resolved.get("message", "")).strip()
            if not message:
                raise WorkflowEngineError("Ticket comment cannot be empty")
            db.add(
                TicketComment(
                    id=str(uuid.uuid4()),
                    ticket_id=ticket.id,
                    author_name="Workflow Engine",
                    author_role="automation",
                    body=message[:10_000],
                    created_at=now,
                )
            )
            db.add(
                TicketHistory(
                    id=str(uuid.uuid4()),
                    ticket_id=ticket.id,
                    actor_name="Workflow Engine",
                    event_type="workflow_comment",
                    field_name="comment",
                    old_value=None,
                    new_value=message[:2_000],
                    message=f"Workflow {execution.id} added a comment.",
                    created_at=now,
                )
            )
            return {"ticket_id": ticket.id, "comment_added": True}
        if action == "ticket.set_priority":
            priority = str(resolved.get("priority", "")).upper()
            if priority not in _TICKET_PRIORITIES:
                raise WorkflowEngineError("Ticket priority is invalid")
            previous = ticket.priority
            ticket.priority = priority
            field = "priority"
            value = priority
        elif action == "ticket.assign":
            assignee = str(resolved.get("assignee_name", "")).strip()
            if not assignee:
                raise WorkflowEngineError("Ticket assignee_name is required")
            previous = ticket.assignee_name
            ticket.assignee_name = assignee[:200]
            field = "assignee_name"
            value = ticket.assignee_name
        elif action == "ticket.transition":
            target = canonical_ticket_status(str(resolved.get("status", "")))
            if target is None or target not in _TICKET_STATUSES:
                raise WorkflowEngineError(
                    "unknown_status: ticket target status is not canonical"
                )
            expected_version_raw = resolved.get("expected_version")
            expected_version = (
                int(expected_version_raw)
                if expected_version_raw not in (None, "")
                else None
            )
            try:
                lifecycle_result = transition_ticket_status(
                    db,
                    ticket,
                    target,
                    actor_name="Workflow Engine",
                    actor_kind="SYSTEM",
                    actor_email="workflow-engine@sbs.local",
                    expected_version=expected_version,
                    idempotency_key=f"workflow:{execution.id}:{node_key}"[-120:],
                    at=now,
                    source="workflow_engine",
                    reason=f"Workflow {execution.id} transitioned the ticket.",
                )
            except (TicketLifecycleError, TypeError, ValueError) as error:
                raise WorkflowEngineError(str(error)) from error
            return {
                "ticket_id": ticket.id,
                "field": "status",
                "previous_value": lifecycle_result.previous_status,
                "value": lifecycle_result.target_status,
                "governance_version": lifecycle_result.governance_version,
                "already_applied": lifecycle_result.already_applied,
            }
        else:
            raise WorkflowEngineError(f"Unsupported ticket action: {action}")
        ticket.updated_at = now
        db.add(
            TicketHistory(
                id=str(uuid.uuid4()),
                ticket_id=ticket.id,
                actor_name="Workflow Engine",
                event_type="workflow_field_update",
                field_name=field,
                old_value=str(previous) if previous is not None else None,
                new_value=str(value),
                message=f"Workflow {execution.id} updated {field}.",
                created_at=now,
            )
        )
        return {
            "ticket_id": ticket.id,
            "field": field,
            "previous_value": previous,
            "value": value,
        }
    if action == "notification.create":
        recipient_email = str(resolved.get("recipient_email", "")).strip()
        if not recipient_email or "@" not in recipient_email:
            raise WorkflowEngineError("Notification recipient_email is invalid")
        notification = create_notification(
            db,
            type="workflow",
            title=str(resolved.get("title", "Workflow notification"))[:255],
            message=str(resolved.get("message", ""))[:10_000],
            recipient_name=str(
                resolved.get("recipient_name") or recipient_email
            )[:255],
            recipient_email=recipient_email[:255],
            channel="in_app",
            tenant_id=execution.tenant_id,
            event_type=str(
                resolved.get("event_type") or "workflow.notification"
            )[:120],
            severity=str(resolved.get("severity") or "info")[:32],
            entity_type=execution.trigger_entity_type,
            entity_id=execution.trigger_entity_id,
            metadata={
                "workflow_execution_id": execution.id,
                "workflow_node_key": node_key,
            },
        )
        return {"notification_id": notification.id}
    if action == "integration.emit":
        event_type = str(resolved.get("event_type", "")).strip().lower()
        data = resolved.get("data")
        if not isinstance(data, dict):
            raise WorkflowEngineError("integration.emit data must be an object")
        _assert_secret_safe(data, path="integration.emit.data")
        queued = queue_outbound_webhook_event(
            db,
            tenant_id=execution.tenant_id,
            event_id=f"{execution.id}:{node_key}",
            event_type=event_type,
            entity_type=execution.trigger_entity_type,
            entity_id=execution.trigger_entity_id,
            data=data,
            idempotency_key=f"workflow:{execution.id}:{node_key}",
        )
        return {
            "queued_deliveries": len(queued),
            "delivery_ids": [item.id for item in queued],
        }
    raise WorkflowEngineError(f"Unsupported workflow action: {action}")


def _compensate_execution(
    db: Session,
    execution: WorkflowExecution,
    *,
    definition: dict[str, Any],
) -> dict[str, Any]:
    node_map = {str(node["key"]): node for node in definition["nodes"]}
    completed_steps = db.scalars(
        select(WorkflowStepExecution)
        .where(
            WorkflowStepExecution.execution_id == execution.id,
            WorkflowStepExecution.node_type == "ACTION",
            WorkflowStepExecution.status == "SUCCEEDED",
        )
        .order_by(WorkflowStepExecution.sequence_number.desc())
    ).all()
    results: list[dict[str, Any]] = []
    execution.status = "COMPENSATING"
    _append_execution_event(
        db,
        execution,
        event_type="compensation_started",
        node_key=None,
        status=execution.status,
    )
    for step in completed_steps:
        node = node_map.get(step.node_key, {})
        compensation = node.get("compensation")
        if not isinstance(compensation, dict):
            continue
        runtime = _runtime_context(db, execution)
        try:
            with db.begin_nested():
                output = _execute_action_config(
                    db,
                    execution,
                    node_key=step.node_key,
                    config=compensation,
                    runtime=runtime,
                )
            step.compensation_status = "SUCCEEDED"
            step.compensation_output_json = canonical_json(output)
            result = {
                "node_key": step.node_key,
                "status": "SUCCEEDED",
                "output": output,
            }
        except Exception as exc:  # noqa: BLE001
            step.compensation_status = "FAILED"
            step.compensation_output_json = canonical_json(
                {"error": str(exc)[:2_000]}
            )
            result = {
                "node_key": step.node_key,
                "status": "FAILED",
                "error": str(exc)[:2_000],
            }
        step.updated_at = utcnow()
        results.append(result)
        _append_execution_event(
            db,
            execution,
            event_type="compensation_completed",
            node_key=step.node_key,
            status=step.compensation_status,
            details=result,
        )
    return {
        "attempted": len(results),
        "failed": sum(1 for item in results if item["status"] == "FAILED"),
        "results": results,
    }


def _finish_execution_failure(
    db: Session,
    execution: WorkflowExecution,
    workflow: WorkflowDefinition,
    *,
    definition: dict[str, Any],
    error: str,
    dead_letter: bool,
) -> None:
    compensation: dict[str, Any] | None = None
    if str(definition.get("on_failure", "FAIL")).upper() == "COMPENSATE":
        compensation = _compensate_execution(
            db,
            execution,
            definition=definition,
        )
    now = utcnow()
    execution.status = "DEAD_LETTER" if dead_letter else "FAILED"
    execution.last_error = error[:2_000]
    execution.completed_at = now
    execution.updated_at = now
    execution.output_json = canonical_json(
        {
            "error": execution.last_error,
            "compensation": compensation,
        }
    )
    workflow.failed_executions += 1
    workflow.updated_at = now
    _append_execution_event(
        db,
        execution,
        event_type="execution_failed",
        node_key=execution.current_node_key,
        status=execution.status,
        details={
            "error": execution.last_error,
            "compensation": compensation,
        },
    )
    log_audit(
        db,
        action="workflow_execution_failed",
        entity_type="workflow_execution",
        entity_id=execution.id,
        actor_email="workflow-engine@sbs.local",
        tenant_id=execution.tenant_id,
        metadata={
            "workflow_id": workflow.id,
            "version": execution.workflow_version_number,
            "status": execution.status,
        },
    )


def _complete_execution(
    db: Session,
    execution: WorkflowExecution,
    workflow: WorkflowDefinition,
) -> None:
    now = utcnow()
    runtime = _runtime_context(db, execution)
    execution.status = "SUCCEEDED"
    execution.output_json = canonical_json(
        {
            "variables": runtime["variables"],
            "steps": runtime["steps"],
        }
    )
    execution.last_error = None
    execution.completed_at = now
    execution.updated_at = now
    workflow.updated_at = now
    _append_execution_event(
        db,
        execution,
        event_type="execution_succeeded",
        node_key=execution.current_node_key,
        status=execution.status,
        details={"version": execution.workflow_version_number},
    )
    log_audit(
        db,
        action="workflow_execution_succeeded",
        entity_type="workflow_execution",
        entity_id=execution.id,
        actor_email="workflow-engine@sbs.local",
        tenant_id=execution.tenant_id,
        metadata={
            "workflow_id": workflow.id,
            "version": execution.workflow_version_number,
        },
    )


def _handle_action_node(
    db: Session,
    execution: WorkflowExecution,
    workflow: WorkflowDefinition,
    version: WorkflowVersion,
    definition: dict[str, Any],
    node: dict[str, Any],
) -> bool:
    step = _get_or_create_step(db, execution, version, node)
    runtime = _runtime_context(db, execution)
    resolved_config = _resolve_value(node.get("config", {}), runtime)
    step.status = "RUNNING"
    step.attempts += 1
    step.input_json = canonical_json(_safe_json_value(resolved_config))
    step.started_at = step.started_at or utcnow()
    step.updated_at = utcnow()
    _append_execution_event(
        db,
        execution,
        event_type="step_started",
        node_key=step.node_key,
        status=step.status,
        details={"attempt": step.attempts},
    )
    try:
        with db.begin_nested():
            output = _execute_action_config(
                db,
                execution,
                node_key=step.node_key,
                config=node.get("config", {}),
                runtime=runtime,
            )
    except Exception as exc:  # noqa: BLE001
        retryable = isinstance(exc, WorkflowEngineError) and exc.retryable
        message = str(exc)[:2_000]
        step.last_error = message
        step.updated_at = utcnow()
        if retryable and step.attempts < step.max_attempts:
            retry = node.get("retry", {})
            base = (
                int(retry.get("backoff_seconds", 30))
                if isinstance(retry, dict)
                else 30
            )
            delay = min(3_600, base * (2 ** (step.attempts - 1)))
            step.status = "PENDING"
            step.next_retry_at = utcnow() + timedelta(seconds=delay)
            execution.status = "RETRY"
            execution.next_run_at = step.next_retry_at
            execution.last_error = message
            execution.updated_at = utcnow()
            _append_execution_event(
                db,
                execution,
                event_type="step_retry_scheduled",
                node_key=step.node_key,
                status=execution.status,
                details={
                    "attempt": step.attempts,
                    "next_retry_at": step.next_retry_at.isoformat(),
                    "error": message,
                },
            )
            return False
        step.status = "FAILED"
        step.completed_at = utcnow()
        _append_execution_event(
            db,
            execution,
            event_type="step_failed",
            node_key=step.node_key,
            status=step.status,
            details={"attempt": step.attempts, "error": message},
        )
        _finish_execution_failure(
            db,
            execution,
            workflow,
            definition=definition,
            error=message,
            dead_letter=retryable and step.attempts >= step.max_attempts,
        )
        return False
    step.status = "SUCCEEDED"
    step.output_json = canonical_json(_safe_json_value(output))
    step.last_error = None
    step.next_retry_at = None
    step.completed_at = utcnow()
    step.updated_at = utcnow()
    execution.current_node_key = str(node["next"])
    execution.status = "RUNNING"
    execution.last_error = None
    execution.updated_at = utcnow()
    _append_execution_event(
        db,
        execution,
        event_type="step_succeeded",
        node_key=step.node_key,
        status=step.status,
        details={"attempt": step.attempts},
    )
    return True


def _resume_timer(
    db: Session,
    execution: WorkflowExecution,
    node: dict[str, Any],
) -> bool:
    step = db.scalar(
        select(WorkflowStepExecution).where(
            WorkflowStepExecution.execution_id == execution.id,
            WorkflowStepExecution.node_key == str(node["key"]),
        )
    )
    if step is None or step.wait_until is None:
        raise WorkflowEngineError("Workflow timer state is unavailable")
    if _aware(step.wait_until) > utcnow():
        execution.next_run_at = _aware(step.wait_until)
        return False
    now = utcnow()
    step.status = "SUCCEEDED"
    step.output_json = canonical_json({"waited_until": now.isoformat()})
    step.completed_at = now
    step.updated_at = now
    execution.current_node_key = str(node["next"])
    execution.status = "RUNNING"
    execution.next_run_at = now
    execution.updated_at = now
    _append_execution_event(
        db,
        execution,
        event_type="timer_elapsed",
        node_key=step.node_key,
        status=step.status,
        details={"wait_until": step.wait_until.isoformat()},
    )
    return True


def _resume_approval_timeout(
    db: Session,
    execution: WorkflowExecution,
    node: dict[str, Any],
) -> bool:
    approval = db.scalar(
        select(WorkflowApproval).where(
            WorkflowApproval.execution_id == execution.id,
            WorkflowApproval.node_key == str(node["key"]),
        )
    )
    if approval is None:
        raise WorkflowEngineError("Workflow approval state is unavailable")
    if approval.status != "PENDING":
        return execution.status != "WAITING_APPROVAL"
    if _aware(approval.expires_at) > utcnow():
        execution.next_run_at = _aware(approval.expires_at)
        return False
    step = db.get(WorkflowStepExecution, approval.step_execution_id)
    if step is None:
        raise WorkflowEngineError("Workflow approval step is unavailable")
    now = utcnow()
    approval.status = "EXPIRED"
    approval.version += 1
    approval.decided_at = now
    approval.updated_at = now
    step.status = "SUCCEEDED"
    step.output_json = canonical_json({"decision": "timeout"})
    step.completed_at = now
    step.updated_at = now
    execution.current_node_key = str(node["next"]["timeout"])
    execution.status = "RUNNING"
    execution.next_run_at = now
    execution.updated_at = now
    _append_execution_event(
        db,
        execution,
        event_type="approval_expired",
        node_key=step.node_key,
        status=approval.status,
    )
    return True


def _resume_subflow(
    db: Session,
    execution: WorkflowExecution,
    node: dict[str, Any],
) -> tuple[bool, str | None]:
    step = db.scalar(
        select(WorkflowStepExecution).where(
            WorkflowStepExecution.execution_id == execution.id,
            WorkflowStepExecution.node_key == str(node["key"]),
        )
    )
    if step is None or step.wait_until is None:
        raise WorkflowEngineError("Workflow subflow state is unavailable")
    state = _json_object(step.output_json)
    child_execution_id = str(state.get("child_execution_id", ""))
    child = db.scalar(
        select(WorkflowExecution).where(
            WorkflowExecution.id == child_execution_id,
            WorkflowExecution.tenant_id == execution.tenant_id,
        )
    )
    if child is None:
        return False, "Workflow subflow execution is unavailable"
    now = utcnow()
    if child.status in _NONTERMINAL_EXECUTION_STATUSES:
        if _aware(step.wait_until) <= now:
            return False, "Workflow subflow exceeded max_wait_seconds"
        execution.next_run_at = min(
            _aware(step.wait_until),
            now + timedelta(seconds=5),
        )
        execution.updated_at = now
        return False, None
    failure_policy = str(
        node.get("config", {}).get("failure_policy", "FAIL")
    ).upper()
    if child.status != "SUCCEEDED" and failure_policy != "CONTINUE":
        return (
            False,
            f"Workflow subflow ended with status {child.status}",
        )
    step.status = "SUCCEEDED"
    step.output_json = canonical_json(
        {
            "child_execution_id": child.id,
            "child_status": child.status,
            "child_output": _json_object(child.output_json),
        }
    )
    step.completed_at = now
    step.updated_at = now
    execution.current_node_key = str(node["next"])
    execution.status = "RUNNING"
    execution.next_run_at = now
    execution.updated_at = now
    _append_execution_event(
        db,
        execution,
        event_type="subflow_completed",
        node_key=step.node_key,
        status=child.status,
        details={
            "child_execution_id": child.id,
            "child_status": child.status,
            "failure_policy": failure_policy,
        },
    )
    return True, None


def process_workflow_execution(
    db: Session,
    execution: WorkflowExecution,
) -> WorkflowExecution:
    if execution.status in _TERMINAL_EXECUTION_STATUSES:
        return execution
    workflow = db.get(WorkflowDefinition, execution.workflow_id)
    if workflow is None:
        execution.status = "FAILED"
        execution.last_error = "Workflow definition is unavailable"
        execution.completed_at = utcnow()
        execution.updated_at = utcnow()
        return execution
    version, definition = _definition_for_execution(db, execution)
    node_map = {str(node["key"]): node for node in definition["nodes"]}
    if workflow.concurrency_policy == "SERIALIZE":
        earlier = db.scalar(
            select(WorkflowExecution.id)
            .where(
                WorkflowExecution.workflow_id == workflow.id,
                WorkflowExecution.id != execution.id,
                WorkflowExecution.status.in_(
                    _NONTERMINAL_EXECUTION_STATUSES
                ),
                or_(
                    WorkflowExecution.created_at < execution.created_at,
                    and_(
                        WorkflowExecution.created_at == execution.created_at,
                        WorkflowExecution.id < execution.id,
                    ),
                ),
            )
            .limit(1)
        )
        if earlier is not None:
            execution.next_run_at = utcnow() + timedelta(seconds=5)
            execution.updated_at = utcnow()
            return execution
    current = execution.current_node_key
    if not current or current not in node_map:
        _finish_execution_failure(
            db,
            execution,
            workflow,
            definition=definition,
            error="Current workflow node is unavailable",
            dead_letter=False,
        )
        return execution
    if execution.status == "WAITING_TIMER":
        if not _resume_timer(db, execution, node_map[current]):
            return execution
        current = execution.current_node_key
    elif execution.status == "WAITING_APPROVAL":
        if not _resume_approval_timeout(db, execution, node_map[current]):
            return execution
        current = execution.current_node_key
    elif execution.status == "WAITING_SUBFLOW":
        resumed, error = _resume_subflow(db, execution, node_map[current])
        if error:
            _finish_execution_failure(
                db,
                execution,
                workflow,
                definition=definition,
                error=error,
                dead_letter=False,
            )
            return execution
        if not resumed:
            return execution
        current = execution.current_node_key
    execution.status = "RUNNING"
    execution.started_at = execution.started_at or utcnow()
    execution.attempts += 1
    execution.updated_at = utcnow()
    for _ in range(100):
        if not current or current not in node_map:
            _finish_execution_failure(
                db,
                execution,
                workflow,
                definition=definition,
                error="Workflow branch points to an unavailable node",
                dead_letter=False,
            )
            return execution
        node = node_map[current]
        node_type = str(node["type"]).upper()
        execution.current_node_key = current
        runtime = _runtime_context(db, execution)
        if node_type == "END":
            step = _get_or_create_step(db, execution, version, node)
            now = utcnow()
            step.status = "SUCCEEDED"
            step.attempts = 1
            step.started_at = now
            step.completed_at = now
            step.updated_at = now
            _complete_execution(db, execution, workflow)
            return execution
        if node_type == "CONDITION":
            step = _get_or_create_step(db, execution, version, node)
            outcome = _condition_result(node.get("config", {}), runtime)
            now = utcnow()
            step.status = "SUCCEEDED"
            step.attempts = 1
            step.input_json = canonical_json(node.get("config", {}))
            step.output_json = canonical_json({"result": outcome})
            step.started_at = now
            step.completed_at = now
            step.updated_at = now
            current = str(node["next"]["true" if outcome else "false"])
            execution.current_node_key = current
            _append_execution_event(
                db,
                execution,
                event_type="condition_evaluated",
                node_key=step.node_key,
                status=step.status,
                details={"result": outcome, "next": current},
            )
            continue
        if node_type == "ACTION":
            if not _handle_action_node(
                db,
                execution,
                workflow,
                version,
                definition,
                node,
            ):
                return execution
            current = execution.current_node_key
            continue
        if node_type == "WAIT":
            step = _get_or_create_step(db, execution, version, node)
            now = utcnow()
            wait_until = now + timedelta(
                seconds=int(node["config"]["seconds"])
            )
            step.status = "WAITING"
            step.attempts = 1
            step.input_json = canonical_json(node["config"])
            step.wait_until = wait_until
            step.started_at = now
            step.updated_at = now
            execution.status = "WAITING_TIMER"
            execution.next_run_at = wait_until
            execution.updated_at = now
            _append_execution_event(
                db,
                execution,
                event_type="timer_started",
                node_key=step.node_key,
                status=execution.status,
                details={"wait_until": wait_until.isoformat()},
            )
            return execution
        if node_type == "SUBFLOW":
            step = _get_or_create_step(db, execution, version, node)
            runtime = _runtime_context(db, execution)
            config = node.get("config", {})
            target_code = str(config.get("workflow_code", "")).strip().lower()
            target = db.scalar(
                select(WorkflowDefinition).where(
                    WorkflowDefinition.tenant_id == execution.tenant_id,
                    WorkflowDefinition.code == target_code,
                    WorkflowDefinition.status == "ACTIVE",
                    WorkflowDefinition.published_version_number.is_not(None),
                )
            )
            if target is None:
                _finish_execution_failure(
                    db,
                    execution,
                    workflow,
                    definition=definition,
                    error=f"Active subflow {target_code} is unavailable",
                    dead_letter=False,
                )
                return execution
            if target.id == execution.workflow_id:
                _finish_execution_failure(
                    db,
                    execution,
                    workflow,
                    definition=definition,
                    error="Workflow cannot invoke itself as a subflow",
                    dead_letter=False,
                )
                return execution
            parent_context = _json_object(execution.context_json)
            depth, depth_valid = _bounded_integer(
                parent_context.get("_workflow_depth", 0),
                default=0,
                minimum=0,
                maximum=4,
            )
            if not depth_valid:
                _finish_execution_failure(
                    db,
                    execution,
                    workflow,
                    definition=definition,
                    error="Workflow subflow depth limit reached",
                    dead_letter=False,
                )
                return execution
            resolved_context = _resolve_value(
                config.get("context", {}),
                runtime,
            )
            if not isinstance(resolved_context, dict):
                _finish_execution_failure(
                    db,
                    execution,
                    workflow,
                    definition=definition,
                    error="Workflow subflow context is invalid",
                    dead_letter=False,
                )
                return execution
            child_context = {
                **resolved_context,
                "_workflow_parent_execution_id": execution.id,
                "_workflow_depth": depth + 1,
            }
            if execution.trigger_entity_type and "entity_type" not in child_context:
                child_context["entity_type"] = execution.trigger_entity_type
            if execution.trigger_entity_id and "entity_id" not in child_context:
                child_context["entity_id"] = execution.trigger_entity_id
            child, _ = enqueue_workflow_execution(
                db,
                target,
                context=child_context,
                idempotency_key=f"subflow:{execution.id}:{node['key']}",
                source="AUTOMATIC",
                actor_id=execution.started_by_id,
                correlation_id=execution.correlation_id,
            )
            now = utcnow()
            wait_until = now + timedelta(
                seconds=int(config.get("max_wait_seconds", 86_400))
            )
            step.status = "WAITING"
            step.attempts = 1
            step.input_json = canonical_json(
                {
                    "workflow_code": target_code,
                    "context": resolved_context,
                }
            )
            step.output_json = canonical_json(
                {"child_execution_id": child.id}
            )
            step.wait_until = wait_until
            step.started_at = now
            step.updated_at = now
            execution.status = "WAITING_SUBFLOW"
            execution.next_run_at = min(
                wait_until,
                now + timedelta(seconds=5),
            )
            execution.updated_at = now
            _append_execution_event(
                db,
                execution,
                event_type="subflow_started",
                node_key=step.node_key,
                status=execution.status,
                details={
                    "child_execution_id": child.id,
                    "child_workflow_id": target.id,
                    "child_workflow_code": target.code,
                    "max_wait_seconds": int(
                        config.get("max_wait_seconds", 86_400)
                    ),
                },
            )
            return execution
        if node_type == "APPROVAL":
            step = _get_or_create_step(db, execution, version, node)
            now = utcnow()
            timeout = int(node["config"].get("timeout_minutes", 1_440))
            expires_at = now + timedelta(minutes=timeout)
            approval = WorkflowApproval(
                id=str(uuid.uuid4()),
                tenant_id=execution.tenant_id,
                execution_id=execution.id,
                step_execution_id=step.id,
                node_key=step.node_key,
                approver_role=str(node["config"]["approver_role"]),
                allow_self_approval=bool(
                    node["config"].get("allow_self_approval", False)
                ),
                status="PENDING",
                version=1,
                requested_by_id=execution.started_by_id,
                requested_at=now,
                expires_at=expires_at,
                created_at=now,
                updated_at=now,
            )
            db.add(approval)
            step.status = "WAITING"
            step.attempts = 1
            step.input_json = canonical_json(node["config"])
            step.started_at = now
            step.updated_at = now
            execution.status = "WAITING_APPROVAL"
            execution.next_run_at = expires_at
            execution.updated_at = now
            db.flush()
            _append_execution_event(
                db,
                execution,
                event_type="approval_requested",
                node_key=step.node_key,
                status=execution.status,
                details={
                    "approval_id": approval.id,
                    "approver_role": approval.approver_role,
                    "expires_at": expires_at.isoformat(),
                },
            )
            return execution
    _finish_execution_failure(
        db,
        execution,
        workflow,
        definition=definition,
        error="Workflow exceeded the node execution safety limit",
        dead_letter=False,
    )
    return execution


def decide_workflow_approval(
    db: Session,
    approval: WorkflowApproval,
    *,
    decision: str,
    comment: str,
    actor_id: str,
) -> WorkflowApproval:
    decision = decision.strip().upper()
    if decision not in {"APPROVED", "REJECTED"}:
        raise ValueError("Decision must be APPROVED or REJECTED")
    if approval.status != "PENDING":
        raise ValueError("Workflow approval is no longer pending")
    if _aware(approval.expires_at) <= utcnow():
        approval.status = "EXPIRED"
        approval.version += 1
        approval.decided_at = utcnow()
        approval.updated_at = utcnow()
        raise ValueError("Workflow approval has expired")
    if (
        not approval.allow_self_approval
        and approval.requested_by_id
        and approval.requested_by_id == actor_id
    ):
        raise ValueError("Self-approval is not permitted")
    execution = db.get(WorkflowExecution, approval.execution_id)
    step = db.get(WorkflowStepExecution, approval.step_execution_id)
    if execution is None or step is None:
        raise ValueError("Workflow approval execution is unavailable")
    _, definition = _definition_for_execution(db, execution)
    node_map = {str(node["key"]): node for node in definition["nodes"]}
    node = node_map.get(approval.node_key)
    if node is None or str(node.get("type")).upper() != "APPROVAL":
        raise ValueError("Workflow approval node is unavailable")
    now = utcnow()
    approval.status = decision
    approval.version += 1
    approval.decided_by_id = actor_id
    approval.decision_comment = comment.strip()
    approval.decided_at = now
    approval.updated_at = now
    outcome = "approved" if decision == "APPROVED" else "rejected"
    step.status = "SUCCEEDED"
    step.output_json = canonical_json(
        {"decision": outcome, "comment": comment.strip()}
    )
    step.completed_at = now
    step.updated_at = now
    execution.current_node_key = str(node["next"][outcome])
    execution.status = "QUEUED"
    execution.next_run_at = now
    execution.updated_at = now
    _append_execution_event(
        db,
        execution,
        event_type="approval_decided",
        node_key=approval.node_key,
        status=decision,
        details={"decision": outcome, "comment": comment.strip()},
    )
    return approval


def cancel_workflow_execution(
    db: Session,
    execution: WorkflowExecution,
    *,
    actor_id: str,
    reason: str,
) -> WorkflowExecution:
    if execution.status not in _NONTERMINAL_EXECUTION_STATUSES:
        raise ValueError("Only a pending workflow execution can be cancelled")
    if execution.status == "WAITING_SUBFLOW":
        step = db.scalar(
            select(WorkflowStepExecution).where(
                WorkflowStepExecution.execution_id == execution.id,
                WorkflowStepExecution.node_key == execution.current_node_key,
            )
        )
        state = _json_object(step.output_json) if step is not None else {}
        child_id = str(state.get("child_execution_id", ""))
        child = db.scalar(
            select(WorkflowExecution).where(
                WorkflowExecution.id == child_id,
                WorkflowExecution.tenant_id == execution.tenant_id,
            )
        )
        if child is not None and child.status in _NONTERMINAL_EXECUTION_STATUSES:
            cancel_workflow_execution(
                db,
                child,
                actor_id=actor_id,
                reason=f"Parent execution {execution.id} was cancelled",
            )
    now = utcnow()
    execution.status = "CANCELLED"
    execution.last_error = reason.strip()
    execution.cancelled_at = now
    execution.cancelled_by_id = actor_id
    execution.completed_at = now
    execution.updated_at = now
    approvals = db.scalars(
        select(WorkflowApproval).where(
            WorkflowApproval.execution_id == execution.id,
            WorkflowApproval.status == "PENDING",
        )
    ).all()
    for approval in approvals:
        approval.status = "CANCELLED"
        approval.version += 1
        approval.decided_at = now
        approval.updated_at = now
    _append_execution_event(
        db,
        execution,
        event_type="execution_cancelled",
        node_key=execution.current_node_key,
        status=execution.status,
        details={"reason": reason.strip()},
    )
    return execution


def replay_workflow_execution(
    db: Session,
    execution: WorkflowExecution,
    workflow: WorkflowDefinition,
    *,
    actor_id: str,
    reason: str,
) -> WorkflowExecution:
    if execution.status not in {
        "FAILED",
        "DEAD_LETTER",
        "CANCELLED",
        "DROPPED",
    }:
        raise ValueError("Only failed, cancelled, dead-letter, or dropped runs replay")
    version = db.get(WorkflowVersion, execution.workflow_version_id)
    if version is None:
        raise ValueError("Original workflow version is unavailable")
    replay, _ = enqueue_workflow_execution(
        db,
        workflow,
        context=_json_object(execution.context_json),
        idempotency_key=f"replay:{execution.id}:{uuid.uuid4().hex}",
        source="REPLAY",
        actor_id=actor_id,
        correlation_id=execution.correlation_id,
        replay_of_id=execution.id,
        version=version,
    )
    _append_execution_event(
        db,
        replay,
        event_type="execution_replayed",
        node_key=replay.current_node_key,
        status=replay.status,
        details={"original_execution_id": execution.id, "reason": reason.strip()},
    )
    return replay


def run_workflow_cycle(
    db: Session,
    *,
    settings: Settings | None = None,
) -> dict[str, int]:
    runtime = settings or get_settings()
    now = utcnow()
    ids = db.scalars(
        select(WorkflowExecution.id)
        .where(
            WorkflowExecution.status.in_(
                {
                    "QUEUED",
                    "RETRY",
                    "WAITING_TIMER",
                    "WAITING_APPROVAL",
                    "WAITING_SUBFLOW",
                }
            ),
            WorkflowExecution.next_run_at <= now,
        )
        .order_by(WorkflowExecution.next_run_at, WorkflowExecution.created_at)
        .limit(runtime.workflow_worker_batch_size)
    ).all()
    db.commit()
    result = {
        "processed": 0,
        "succeeded": 0,
        "waiting": 0,
        "retried": 0,
        "failed": 0,
        "dead_lettered": 0,
        "deferred": 0,
    }
    for execution_id in ids:
        statement = select(WorkflowExecution).where(
            WorkflowExecution.id == execution_id,
            WorkflowExecution.status.in_(
                {
                    "QUEUED",
                    "RETRY",
                    "WAITING_TIMER",
                    "WAITING_APPROVAL",
                    "WAITING_SUBFLOW",
                }
            ),
            WorkflowExecution.next_run_at <= utcnow(),
        )
        if db.get_bind().dialect.name == "postgresql":
            statement = statement.with_for_update(skip_locked=True)
        execution = db.scalar(statement)
        if execution is None:
            db.rollback()
            continue
        before_status = execution.status
        try:
            process_workflow_execution(db, execution)
            after_status = execution.status
            db.commit()
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            retry_statement = select(WorkflowExecution).where(
                WorkflowExecution.id == execution_id
            )
            if db.get_bind().dialect.name == "postgresql":
                retry_statement = retry_statement.with_for_update()
            retry_item = db.scalar(retry_statement)
            if retry_item is None:
                db.rollback()
                continue
            retry_item.attempts += 1
            retry_item.last_error = (
                f"{exc.__class__.__name__}: workflow worker failure"
            )
            if retry_item.attempts >= retry_item.max_attempts:
                retry_item.status = "DEAD_LETTER"
                retry_item.completed_at = utcnow()
                retry_item.next_run_at = utcnow()
            else:
                retry_item.status = "RETRY"
                retry_item.next_run_at = utcnow() + timedelta(seconds=30)
            retry_item.updated_at = utcnow()
            db.commit()
            after_status = retry_item.status
        result["processed"] += 1
        result["succeeded"] += int(after_status == "SUCCEEDED")
        result["waiting"] += int(
            after_status
            in {"WAITING_TIMER", "WAITING_APPROVAL", "WAITING_SUBFLOW"}
        )
        result["retried"] += int(after_status == "RETRY")
        result["failed"] += int(after_status == "FAILED")
        result["dead_lettered"] += int(after_status == "DEAD_LETTER")
        result["deferred"] += int(
            after_status == before_status
            and after_status
            in {
                "QUEUED",
                "WAITING_TIMER",
                "WAITING_APPROVAL",
                "WAITING_SUBFLOW",
            }
        )
    return result


def cleanup_workflow_executions(
    db: Session,
    *,
    settings: Settings | None = None,
) -> int:
    runtime = settings or get_settings()
    cutoff = utcnow() - timedelta(days=runtime.workflow_execution_retention_days)
    result = db.execute(
        delete(WorkflowExecution).where(
            WorkflowExecution.status.in_(_TERMINAL_EXECUTION_STATUSES),
            WorkflowExecution.completed_at.is_not(None),
            WorkflowExecution.completed_at < cutoff,
        )
    )
    db.commit()
    return int(result.rowcount or 0)
