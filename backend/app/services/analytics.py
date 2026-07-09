from __future__ import annotations

import json
import uuid
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from statistics import mean
from typing import Any

from sqlalchemy import Select, and_, func, select
from sqlalchemy.orm import Session

from app.models.ai_suggestion import AiSuggestion
from app.models.approval_request import ApprovalRequest
from app.models.asset import Asset
from app.models.audit_log import AuditLog
from app.models.external_system import ExternalSystem
from app.models.import_job import ImportJob
from app.models.integration_event_log import IntegrationEventLog
from app.models.knowledge_article import KnowledgeArticle
from app.models.knowledge_article_feedback import KnowledgeArticleFeedback
from app.models.knowledge_usage_log import KnowledgeUsageLog
from app.models.report_snapshot import ReportSnapshot
from app.models.saved_report import SavedReport
from app.models.system_setting import SystemSetting
from app.models.ticket import Ticket
from app.models.ticket_knowledge_link import TicketKnowledgeLink
from app.models.user import User
from app.services.automation import collect_automation_overview


CLOSED_STATUSES = {"RESOLVED", "CLOSED", "CANCELLED"}
RISK_SLA_STATUSES = {"at_risk", "warning", "risk"}
HIGH_RISK_AUDIT_ACTIONS = {"security.alert", "security.incident", "security.high_risk"}


def _uuid() -> str:
    return str(uuid.uuid4())


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _tenant_id(current_user: Any) -> str | None:
    if getattr(current_user, "role", None) == "saas_root":
        return None
    return getattr(current_user, "tenant_id", None)


def _tenant_scoped(statement: Select, model: type[Any], tenant_id: str | None) -> Select:
    if tenant_id is None:
        return statement
    if hasattr(model, "tenant_id"):
        return statement.where(getattr(model, "tenant_id") == tenant_id)
    return statement


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _legacy_user_context(tenant_id: str | None) -> Any:
    return type(
        "LegacyUserContext",
        (),
        {"role": "saas_root" if tenant_id is None else "organization_admin", "tenant_id": tenant_id},
    )()


def _range_filter(column: Any, filters: dict[str, Any], clauses: list[Any]) -> None:
    date_from = filters.get("date_from")
    date_to = filters.get("date_to")
    if date_from:
        clauses.append(column >= date_from)
    if date_to:
        clauses.append(column <= date_to)


def _status_priority_category_distributions(rows: list[Ticket]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    status = Counter(item.status for item in rows)
    priority = Counter(item.priority for item in rows)
    category = Counter(item.category for item in rows)
    return (
        [{"status": key, "count": value} for key, value in status.most_common()],
        [{"priority": key, "count": value} for key, value in priority.most_common()],
        [{"category": key, "count": value} for key, value in category.most_common()],
    )


def _group_key(value: datetime | None, group_by: str) -> str:
    if value is None:
        return "unknown"
    v = _as_utc(value) or value
    if group_by == "week":
        year, week, _ = v.isocalendar()
        return f"{year}-W{week:02d}"
    if group_by == "month":
        return f"{v.year}-{v.month:02d}"
    return v.date().isoformat()


def _filtered_tickets(db: Session, current_user: Any, filters: dict[str, Any]) -> list[Ticket]:
    tenant_id = _tenant_id(current_user)
    statement = _tenant_scoped(select(Ticket), Ticket, tenant_id)
    clauses: list[Any] = []
    _range_filter(Ticket.created_at, filters, clauses)
    if filters.get("category"):
        clauses.append(Ticket.category == filters["category"])
    if filters.get("priority"):
        clauses.append(Ticket.priority == filters["priority"])
    if filters.get("status"):
        clauses.append(Ticket.status == filters["status"])
    if filters.get("assignee_id"):
        clauses.append(Ticket.assignee_id == filters["assignee_id"])
    if clauses:
        statement = statement.where(and_(*clauses))
    return db.scalars(statement).all()


def get_ticket_analytics(db: Session, filters: dict[str, Any], current_user: Any) -> dict[str, Any]:
    rows = _filtered_tickets(db, current_user, filters)
    group_by = str(filters.get("group_by") or "day").lower()
    trend_counter: Counter[str] = Counter(_group_key(item.created_at, group_by) for item in rows)
    status_distribution, priority_distribution, category_distribution = _status_priority_category_distributions(rows)

    workload_counter = Counter((item.assignee_name or "Unassigned") for item in rows)
    resolution_values = []
    first_response_values = []
    reopened_count = 0
    closed_count = 0
    for item in rows:
        if item.reopened_at is not None:
            reopened_count += 1
        if item.status in CLOSED_STATUSES:
            closed_count += 1
        created_at = _as_utc(item.created_at)
        resolved_at = _as_utc(item.resolved_at)
        response_at = _as_utc(item.response_due_at)
        if created_at and resolved_at:
            resolution_values.append(max(0, int((resolved_at - created_at).total_seconds() // 60)))
        if created_at and response_at:
            first_response_values.append(max(0, int((response_at - created_at).total_seconds() // 60)))

    return {
        "ticket_trend": [{"period": key, "count": value} for key, value in sorted(trend_counter.items())],
        "status_distribution": status_distribution,
        "priority_distribution": priority_distribution,
        "category_distribution": category_distribution,
        "assignee_workload": [{"assignee": key, "count": value} for key, value in workload_counter.most_common()],
        "average_resolution_time_minutes": round(mean(resolution_values)) if resolution_values else None,
        "average_first_response_minutes": round(mean(first_response_values)) if first_response_values else None,
        "reopened_count": reopened_count,
        "closed_count": closed_count,
        "total_tickets": len(rows),
    }


def get_sla_analytics(db: Session, filters: dict[str, Any], current_user: Any) -> dict[str, Any]:
    rows = _filtered_tickets(db, current_user, filters)
    now = datetime.now(UTC)
    breached = []
    at_risk = []
    first_response_values = []
    resolution_values = []
    by_priority = Counter()
    by_category = Counter()

    for item in rows:
        due = _as_utc(item.resolution_due_at)
        if due and item.status not in CLOSED_STATUSES and due < now:
            breached.append(item)
            by_priority[item.priority] += 1
            by_category[item.category] += 1
        elif due and item.status not in CLOSED_STATUSES and (due - now).total_seconds() <= 3600:
            at_risk.append(item)

        created_at = _as_utc(item.created_at)
        resolved_at = _as_utc(item.resolved_at)
        response_due_at = _as_utc(item.response_due_at)
        if created_at and response_due_at:
            first_response_values.append(max(0, int((response_due_at - created_at).total_seconds() // 60)))
        if created_at and resolved_at:
            resolution_values.append(max(0, int((resolved_at - created_at).total_seconds() // 60)))

    total = len(rows)
    compliance = round(((total - len(breached)) / total) * 100, 2) if total else 100.0
    return {
        "compliance_percent": compliance,
        "breached_tickets": len(breached),
        "at_risk_tickets": len(at_risk),
        "by_priority": [{"priority": key, "count": value} for key, value in by_priority.most_common()],
        "by_category": [{"category": key, "count": value} for key, value in by_category.most_common()],
        "first_response_stats": {
            "average_minutes": round(mean(first_response_values)) if first_response_values else None,
            "count": len(first_response_values),
        },
        "resolution_stats": {
            "average_minutes": round(mean(resolution_values)) if resolution_values else None,
            "count": len(resolution_values),
        },
    }


def get_asset_analytics(db: Session, filters: dict[str, Any], current_user: Any) -> dict[str, Any]:
    tenant_id = _tenant_id(current_user)
    statement = _tenant_scoped(select(Asset), Asset, tenant_id)
    rows = db.scalars(statement).all()

    by_type = Counter(item.asset_type or "unknown" for item in rows)
    by_status = Counter(item.status or "unknown" for item in rows)
    by_room = Counter((item.room or "unknown") for item in rows)
    by_responsible = Counter((item.responsible_person_name or "Unassigned") for item in rows)
    verification = Counter((item.verification_status or "unknown") for item in rows)

    missing_room = [item for item in rows if not (item.room or "").strip()]
    missing_mol = [item for item in rows if not (item.mol_name or "").strip()]
    disposed = [item for item in rows if item.status == "disposed"]
    total_residual_cost = round(sum(_safe_float(item.residual_cost) for item in rows), 2)

    disposed_counter = Counter(_group_key(item.disposed_at or item.updated_at, str(filters.get("group_by") or "month")) for item in disposed)

    return {
        "assets_by_type": [{"type": key, "count": value} for key, value in by_type.most_common()],
        "assets_by_status": [{"status": key, "count": value} for key, value in by_status.most_common()],
        "assets_by_room": [{"room": key, "count": value} for key, value in by_room.most_common()],
        "assets_by_responsible": [{"responsible": key, "count": value} for key, value in by_responsible.most_common()],
        "missing_location": len(missing_room),
        "missing_mol": len(missing_mol),
        "disposed_trend": [{"period": key, "count": value} for key, value in sorted(disposed_counter.items())],
        "residual_cost_summary": {
            "total_residual_cost": total_residual_cost,
            "average_residual_cost": round(total_residual_cost / len(rows), 2) if rows else 0.0,
        },
        "inventory_verification_summary": [{"status": key, "count": value} for key, value in verification.most_common()],
        "total_assets": len(rows),
    }


def get_knowledge_analytics(db: Session, filters: dict[str, Any], current_user: Any) -> dict[str, Any]:
    _ = filters
    _ = current_user
    articles = db.scalars(select(KnowledgeArticle)).all()
    feedback = db.scalars(select(KnowledgeArticleFeedback)).all()
    usage = db.scalars(select(KnowledgeUsageLog)).all()

    by_status = Counter(item.status for item in articles)
    total_views = sum(int(item.view_count or 0) for item in articles)
    helpful = sum(1 for item in feedback if item.is_helpful)
    not_helpful = sum(1 for item in feedback if not item.is_helpful)
    usage_by_ticket = Counter((item.ticket_id or "unknown") for item in usage)
    usage_by_article = Counter(item.article_id for item in usage)
    article_map = {item.id: item for item in articles}

    return {
        "articles_by_status": [{"status": key, "count": value} for key, value in by_status.most_common()],
        "views": total_views,
        "helpful_feedback": helpful,
        "not_helpful_feedback": not_helpful,
        "usage_by_ticket": [{"ticket_id": key, "count": value} for key, value in usage_by_ticket.most_common(20)],
        "most_used_articles": [
            {
                "article_id": article_id,
                "article_number": article_map[article_id].article_number if article_id in article_map else None,
                "title": article_map[article_id].title if article_id in article_map else "Unknown",
                "count": count,
            }
            for article_id, count in usage_by_article.most_common(10)
        ],
        "articles_created_from_tickets": sum(1 for item in articles if item.source_ticket_id is not None),
        "total_articles": len(articles),
        "published_articles": by_status.get("published", 0),
        "draft_articles": by_status.get("draft", 0),
        "article_views": total_views,
        "helpful_feedback_count": helpful,
        "not_helpful_feedback_count": not_helpful,
    }


def get_ai_analytics(db: Session, filters: dict[str, Any], current_user: Any) -> dict[str, Any]:
    _ = filters
    tenant_id = _tenant_id(current_user)
    statement = select(AiSuggestion)
    if tenant_id is not None:
        statement = statement.join(Ticket, Ticket.id == AiSuggestion.ticket_id).where(Ticket.tenant_id == tenant_id)
    suggestions = db.scalars(statement).all()

    by_type = Counter(item.suggestion_type or "resolution" for item in suggestions)
    by_status = Counter(item.status or "proposed" for item in suggestions)
    by_ticket = Counter((item.ticket_id or "unknown") for item in suggestions)
    confidence_values = [float(item.confidence_value) for item in suggestions if item.confidence_value is not None]

    links_statement = select(TicketKnowledgeLink)
    usage_statement = select(KnowledgeUsageLog).where(KnowledgeUsageLog.action == "used_for_resolution")
    if tenant_id is not None:
        links_statement = links_statement.join(Ticket, Ticket.id == TicketKnowledgeLink.ticket_id).where(Ticket.tenant_id == tenant_id)
        usage_statement = usage_statement.join(Ticket, Ticket.id == KnowledgeUsageLog.ticket_id).where(Ticket.tenant_id == tenant_id)
    attached_count = len(db.scalars(links_statement).all())
    used_count = len(db.scalars(usage_statement).all())

    total = len(suggestions)
    accepted = by_status.get("accepted", 0)
    rejected = by_status.get("rejected", 0)
    return {
        "suggestions_total": total,
        "accepted": accepted,
        "rejected": rejected,
        "proposed": by_status.get("proposed", 0),
        "average_confidence": round(mean(confidence_values), 4) if confidence_values else 0.0,
        "suggestions_by_type": [{"suggestion_type": key, "count": value} for key, value in by_type.most_common()],
        "ai_usage_by_ticket": [{"ticket_id": key, "count": value} for key, value in by_ticket.most_common(20)],
        "attach_article_count": attached_count,
        "use_article_count": used_count,
        "ai_suggestions_total": total,
        "ai_suggestions_accepted": accepted,
        "ai_suggestions_rejected": rejected,
        "ai_acceptance_rate": round((accepted / total) * 100, 2) if total else 0.0,
    }


def get_security_analytics(db: Session, filters: dict[str, Any], current_user: Any) -> dict[str, Any]:
    _ = filters
    tenant_id = _tenant_id(current_user)
    logs_statement = _tenant_scoped(select(AuditLog), AuditLog, tenant_id)
    logs = db.scalars(logs_statement).all()
    users_statement = _tenant_scoped(select(User), User, tenant_id)
    users = db.scalars(users_statement).all()

    today = datetime.now(UTC).date()
    failed_logins = sum(1 for item in logs if item.action == "login_failed")
    admin_actions = sum(1 for item in logs if item.action.startswith("user_") or item.action.startswith("role_") or item.action.startswith("setting_"))
    denied = sum(1 for item in logs if item.action in {"rbac_denied", "permission_denied"})
    high_risk = sum(1 for item in logs if item.action in HIGH_RISK_AUDIT_ACTIONS or item.action.startswith("security."))
    sensitive_changes = sum(1 for item in logs if item.action.startswith("setting_"))
    audit_today = sum(1 for item in logs if (_as_utc(item.created_at) or datetime.now(UTC)).date() == today)

    return {
        "failed_logins": failed_logins,
        "admin_actions": admin_actions,
        "rbac_denied_events": denied,
        "high_risk_audit_events": high_risk,
        "sensitive_settings_changes": sensitive_changes,
        "inactive_users": sum(1 for item in users if not item.is_active),
        "audit_events_today": audit_today,
        "admin_changes": admin_actions,
        "high_risk_events": high_risk,
    }


def get_automation_analytics(db: Session, filters: dict[str, Any], current_user: Any) -> dict[str, Any]:
    _ = filters
    tenant_id = _tenant_id(current_user)
    overview = collect_automation_overview(db, tenant_id)
    return {
        "runs": overview.get("automation_runs_count", 0),
        "success_rate": overview.get("automation_success_rate", 0),
        "failed_actions": overview.get("failed_runs", 0),
        "pending_approvals": overview.get("pending_approvals", 0),
        "runbook_executions": overview.get("runbook_execution_count", 0),
        "automation_runs_total": overview.get("automation_runs_count", 0),
        "automation_success_rate": overview.get("automation_success_rate", 0),
        "failed_runs": overview.get("failed_runs", 0),
    }


def get_integration_analytics(db: Session, current_user: Any) -> dict[str, Any]:
    tenant_id = _tenant_id(current_user)
    systems = db.scalars(_tenant_scoped(select(ExternalSystem), ExternalSystem, tenant_id)).all()
    events = db.scalars(_tenant_scoped(select(IntegrationEventLog), IntegrationEventLog, tenant_id)).all()
    jobs = db.scalars(_tenant_scoped(select(ImportJob), ImportJob, tenant_id)).all()

    healthy = sum(1 for item in systems if item.last_health_status in {"healthy", "ok"})
    failed_events = sum(1 for item in events if item.status in {"failed", "error"})
    return {
        "external_systems_total": len(systems),
        "healthy_integrations": healthy,
        "failed_integration_events": failed_events,
        "import_jobs_total": len(jobs),
    }


def get_executive_analytics(db: Session, current_user: Any, filters: dict[str, Any] | None = None) -> dict[str, Any]:
    filters = filters or {}
    tenant_id = _tenant_id(current_user)
    tickets = _filtered_tickets(db, current_user, filters)
    ticket_metrics = get_ticket_analytics(db, filters, current_user)
    sla_metrics = get_sla_analytics(db, filters, current_user)
    asset_metrics = get_asset_analytics(db, filters, current_user)
    knowledge_metrics = get_knowledge_analytics(db, filters, current_user)
    ai_metrics = get_ai_analytics(db, filters, current_user)
    security_metrics = get_security_analytics(db, filters, current_user)
    automation_metrics = get_automation_analytics(db, filters, current_user)
    integration_metrics = get_integration_analytics(db, current_user)

    status_distribution, priority_distribution, category_distribution = _status_priority_category_distributions(tickets)
    open_tickets = sum(1 for item in tickets if item.status not in CLOSED_STATUSES)
    critical_tickets = sum(1 for item in tickets if item.priority == "CRITICAL" and item.status not in CLOSED_STATUSES)
    overdue_tickets = sla_metrics["breached_tickets"]
    today = datetime.now(UTC).date()
    resolved_today = sum(1 for item in tickets if item.resolved_at is not None and (_as_utc(item.resolved_at) or datetime.now(UTC)).date() == today)

    assets = db.scalars(_tenant_scoped(select(Asset), Asset, tenant_id)).all()
    active_assets = sum(1 for item in assets if item.status not in {"disposed", "retired"})
    disposed_assets = sum(1 for item in assets if item.status in {"disposed", "retired"})
    assets_without_room = asset_metrics["missing_location"]
    assets_without_mol = asset_metrics["missing_mol"]
    assets_needing_verification = sum(1 for item in assets if (item.verification_status or "") in {"pending", "needs_location", "required"})

    score_parts = [
        100 - min(100, open_tickets * 2),
        sla_metrics["compliance_percent"],
        100 - min(100, security_metrics["failed_logins"] * 3),
        min(100, automation_metrics["success_rate"]),
        100 - min(100, assets_without_room + assets_without_mol),
        ai_metrics["ai_acceptance_rate"],
    ]
    itsm_health_score = round(sum(score_parts) / len(score_parts), 2) if score_parts else 0.0
    helpful_rate = 0.0
    if knowledge_metrics["helpful_feedback_count"] + knowledge_metrics["not_helpful_feedback_count"]:
        helpful_rate = round(
            (knowledge_metrics["helpful_feedback_count"] / (knowledge_metrics["helpful_feedback_count"] + knowledge_metrics["not_helpful_feedback_count"]))
            * 100,
            2,
        )

    return {
        "itsm_health_score": itsm_health_score,
        "total_tickets": len(tickets),
        "open_tickets": open_tickets,
        "critical_tickets": critical_tickets,
        "overdue_tickets": overdue_tickets,
        "resolved_today": resolved_today,
        "average_resolution_time_minutes": ticket_metrics["average_resolution_time_minutes"],
        "tickets_by_status": status_distribution,
        "tickets_by_priority": priority_distribution,
        "tickets_by_category": category_distribution,
        "sla_compliance_percent": sla_metrics["compliance_percent"],
        "breached_sla_count": sla_metrics["breached_tickets"],
        "at_risk_sla_count": sla_metrics["at_risk_tickets"],
        "average_first_response_minutes": sla_metrics["first_response_stats"]["average_minutes"],
        "average_resolution_minutes": sla_metrics["resolution_stats"]["average_minutes"],
        "total_assets": len(assets),
        "active_assets": active_assets,
        "disposed_assets": disposed_assets,
        "assets_without_room": assets_without_room,
        "assets_without_mol": assets_without_mol,
        "assets_needing_verification": assets_needing_verification,
        "assets_by_type": asset_metrics["assets_by_type"],
        "assets_by_room_top": asset_metrics["assets_by_room"][:10],
        "assets_by_responsible_top": asset_metrics["assets_by_responsible"][:10],
        "total_residual_cost": asset_metrics["residual_cost_summary"]["total_residual_cost"],
        "total_articles": knowledge_metrics["total_articles"],
        "published_articles": knowledge_metrics["published_articles"],
        "draft_articles": knowledge_metrics["draft_articles"],
        "article_views": knowledge_metrics["article_views"],
        "helpful_feedback_count": knowledge_metrics["helpful_feedback_count"],
        "not_helpful_feedback_count": knowledge_metrics["not_helpful_feedback_count"],
        "knowledge_helpful_rate": helpful_rate,
        "most_used_articles": knowledge_metrics["most_used_articles"],
        "ai_suggestions_total": ai_metrics["ai_suggestions_total"],
        "ai_suggestions_accepted": ai_metrics["ai_suggestions_accepted"],
        "ai_suggestions_rejected": ai_metrics["ai_suggestions_rejected"],
        "ai_acceptance_rate": ai_metrics["ai_acceptance_rate"],
        "average_confidence": ai_metrics["average_confidence"],
        "suggestions_by_type": ai_metrics["suggestions_by_type"],
        "failed_logins": security_metrics["failed_logins"],
        "admin_changes": security_metrics["admin_actions"],
        "high_risk_events": security_metrics["high_risk_audit_events"],
        "inactive_users": security_metrics["inactive_users"],
        "audit_events_today": security_metrics["audit_events_today"],
        "automation_runs_total": automation_metrics["automation_runs_total"],
        "automation_success_rate": automation_metrics["automation_success_rate"],
        "failed_runs": automation_metrics["failed_runs"],
        "pending_approvals": automation_metrics["pending_approvals"],
        "external_systems_total": integration_metrics["external_systems_total"],
        "healthy_integrations": integration_metrics["healthy_integrations"],
        "failed_integration_events": integration_metrics["failed_integration_events"],
        "import_jobs_total": integration_metrics["import_jobs_total"],
    }


# Legacy wrappers kept for backward compatibility in existing frontend modules.
def collect_ticket_metrics(db: Session, tenant_id: str | None = None) -> dict[str, Any]:
    data = get_ticket_analytics(db, {}, _legacy_user_context(tenant_id))
    return {
        "total_tickets": data["total_tickets"],
        "open_tickets": data["total_tickets"] - data["closed_count"],
        "closed_tickets": data["closed_count"],
        "tickets_today": 0,
        "by_status": data["status_distribution"],
        "by_priority": data["priority_distribution"],
        "by_category": data["category_distribution"],
        "average_response_minutes": data["average_first_response_minutes"],
        "average_resolution_minutes": data["average_resolution_time_minutes"],
        "top_requesters": [],
        "top_assignees": data["assignee_workload"],
        "open_critical_tickets": sum(1 for x in data["priority_distribution"] if x["priority"] == "CRITICAL"),
    }


def collect_sla_metrics(db: Session, tenant_id: str | None = None) -> dict[str, Any]:
    data = get_sla_analytics(db, {}, _legacy_user_context(tenant_id))
    return {
        "sla_compliance_percent": data["compliance_percent"],
        "response_breaches": data["breached_tickets"],
        "resolution_breaches": data["breached_tickets"],
        "tickets_at_risk": data["at_risk_tickets"],
        "critical_sla_breaches": 0,
        "violations_by_priority": data["by_priority"],
    }


def collect_asset_metrics(db: Session, tenant_id: str | None = None) -> dict[str, Any]:
    data = get_asset_analytics(db, {}, _legacy_user_context(tenant_id))
    return {
        "total_assets": data["total_assets"],
        "assets_by_type": data["assets_by_type"],
        "assets_by_status": data["assets_by_status"],
        "problem_assets": [],
        "problem_assets_count": 0,
        "top_assets_by_ticket_count": [],
        "warranty_expiring_soon": [],
        "unassigned_assets": [],
        "unassigned_assets_count": 0,
        "imported_assets_count": 0,
        "assets_missing_location_count": data["missing_location"],
        "disposed_assets_count": sum(item["count"] for item in data["assets_by_status"] if item["status"] == "disposed"),
        "assets_by_source": [],
        "assets_by_purchase_year": [],
        "top_responsible_persons": data["assets_by_responsible"],
        "duplicate_inventory_numbers": [],
    }


def collect_ai_metrics(db: Session, tenant_id: str | None = None) -> dict[str, Any]:
    data = get_ai_analytics(db, {}, _legacy_user_context(tenant_id))
    return {
        "total_ai_analyses": data["suggestions_total"],
        "average_confidence_percent": round(data["average_confidence"] * 100, 2),
        "recommendations_by_category": [],
        "recommendations_by_priority": [],
        "ai_suggestions_applied_demo": data["attach_article_count"],
        "frequent_request_topics": [],
    }


def collect_knowledge_metrics(db: Session, tenant_id: str | None = None) -> dict[str, Any]:
    data = get_knowledge_analytics(db, {}, _legacy_user_context(tenant_id))
    return {
        "total_articles": data["total_articles"],
        "published_articles": data["published_articles"],
        "top_helpful_articles": data["most_used_articles"][:5],
        "articles_with_negative_feedback": [],
        "categories_without_articles": [],
        "tickets_resolved_via_knowledge_demo": 0,
    }


def collect_security_metrics(db: Session, tenant_id: str | None = None) -> dict[str, Any]:
    data = get_security_analytics(db, {}, _legacy_user_context(tenant_id))
    return {
        "login_success": 0,
        "login_failed": data["failed_logins"],
        "audit_events_count": data["audit_events_today"],
        "admin_changes_today": data["admin_actions"],
        "risk_summary": {"risk_level": "medium", "recent_security_events": []},
        "sensitive_settings_count": data["sensitive_settings_changes"],
    }


def collect_notification_metrics(db: Session, tenant_id: str | None = None) -> dict[str, Any]:
    _ = db
    _ = tenant_id
    return {"total_notifications": 0, "unread_notifications": 0, "email_log_count": 0, "mock_email_success": 0, "mock_email_failed": 0, "events_by_type": []}


def collect_integration_metrics(db: Session, tenant_id: str | None = None) -> dict[str, Any]:
    base = get_integration_analytics(db, _legacy_user_context(tenant_id))
    return {
        **base,
        "total_systems": base["external_systems_total"],
        "enabled_systems": base["healthy_integrations"],
        "systems_by_status": [],
        "systems_with_errors": base["failed_integration_events"],
        "last_health_check": None,
        "active_import_jobs": base["import_jobs_total"],
        "integration_events_count": base["failed_integration_events"],
        "import_success_rate": 100.0,
        "integrations_health_score": 100,
        "recent_integration_events": [],
    }


def collect_executive_summary(db: Session, tenant_id: str | None = None) -> dict[str, Any]:
    data = get_executive_analytics(db, _legacy_user_context(tenant_id), {})
    return {
        "health_score": data["itsm_health_score"],
        "it_workload_score": max(0, 100 - data["open_tickets"]),
        "sla_risk_score": data["sla_compliance_percent"],
        "asset_risk_score": max(0, 100 - data["assets_without_room"] - data["assets_without_mol"]),
        "security_risk_score": max(0, 100 - data["failed_logins"]),
        "ai_maturity_score": data["ai_acceptance_rate"],
        "integrations_health_score": data["healthy_integrations"],
        "workflow_automation_score": data["automation_success_rate"],
        "top_5_problems": [
            {"title": "Open tickets", "value": data["open_tickets"]},
            {"title": "Critical tickets", "value": data["critical_tickets"]},
            {"title": "SLA breaches", "value": data["breached_sla_count"]},
            {"title": "Assets without room", "value": data["assets_without_room"]},
            {"title": "Failed logins", "value": data["failed_logins"]},
        ],
        "top_5_recommendations": [
            "Reduce open critical tickets and overdue queue.",
            "Stabilize SLA risk for high priority tickets.",
            "Close asset location and MOL gaps.",
            "Increase AI acceptance with better article linking.",
            "Review high-risk security and admin actions.",
        ],
    }


def collect_overview(db: Session, tenant_id: str | None = None) -> dict[str, Any]:
    context = _legacy_user_context(tenant_id)
    return {
        "tickets": collect_ticket_metrics(db, tenant_id),
        "sla": collect_sla_metrics(db, tenant_id),
        "assets": collect_asset_metrics(db, tenant_id),
        "ai": collect_ai_metrics(db, tenant_id),
        "knowledge": collect_knowledge_metrics(db, tenant_id),
        "notifications": collect_notification_metrics(db, tenant_id),
        "security": collect_security_metrics(db, tenant_id),
        "integrations": collect_integration_metrics(db, tenant_id),
        "automation": collect_automation_overview(db, tenant_id),
        "executive_summary": collect_executive_summary(db, tenant_id),
        "executive": get_executive_analytics(db, context, {}),
    }


def report_payload_for_type(db: Session, report_type: str, current_user: Any, filters: dict[str, Any] | None = None) -> dict[str, Any]:
    filters = filters or {}
    key = (report_type or "").lower()
    mapping = {
        "executive": lambda: get_executive_analytics(db, current_user, filters),
        "tickets": lambda: get_ticket_analytics(db, filters, current_user),
        "sla": lambda: get_sla_analytics(db, filters, current_user),
        "assets": lambda: get_asset_analytics(db, filters, current_user),
        "knowledge": lambda: get_knowledge_analytics(db, filters, current_user),
        "ai": lambda: get_ai_analytics(db, filters, current_user),
        "security": lambda: get_security_analytics(db, filters, current_user),
        "automation": lambda: get_automation_analytics(db, filters, current_user),
        "overview": lambda: collect_overview(db, _tenant_id(current_user)),
        "executive-summary": lambda: collect_executive_summary(db, _tenant_id(current_user)),
    }
    return mapping.get(key, mapping["executive"])()


def seed_reporting_demo_data(db: Session, tenant_id: str | None, created_by: str) -> None:
    saved_defs = [
        ("Executive daily", "executive"),
        ("Tickets weekly", "tickets"),
        ("SLA weekly", "sla"),
        ("Assets monthly", "assets"),
    ]
    now = datetime.now(UTC)

    existing_saved = {(item.tenant_id, item.name) for item in db.scalars(select(SavedReport)).all()}
    for name, report_type in saved_defs:
        key = (tenant_id, name)
        if key in existing_saved:
            continue
        db.add(
            SavedReport(
                id=_uuid(),
                tenant_id=tenant_id,
                name=name,
                report_type=report_type,
                filters_json=json.dumps({}, ensure_ascii=False),
                visibility="tenant",
                schedule_enabled=False,
                created_by=created_by,
                created_at=now,
                updated_at=now,
            )
        )

    snapshots = db.scalars(select(ReportSnapshot)).all()
    existing_types = {(item.tenant_id, item.report_type) for item in snapshots}
    for report_type in {"executive", "tickets", "sla", "assets"}:
        if (tenant_id, report_type) in existing_types:
            continue
        payload = {"seed": True, "report_type": report_type, "generated_at": now.isoformat()}
        db.add(
            ReportSnapshot(
                id=_uuid(),
                tenant_id=tenant_id,
                report_type=report_type,
                period_from=now - timedelta(days=30),
                period_to=now,
                filters_json="{}",
                payload_json=json.dumps(payload, ensure_ascii=False),
                generated_at=now,
                created_at=now,
                created_by=created_by,
            )
        )
