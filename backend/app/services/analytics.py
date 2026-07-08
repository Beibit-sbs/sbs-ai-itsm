from __future__ import annotations

import json
import uuid
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from statistics import mean
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.ai_suggestion import AiSuggestion
from app.models.asset import Asset
from app.models.audit_log import AuditLog
from app.models.email_message_log import EmailMessageLog
from app.models.external_system import ExternalSystem
from app.models.import_job import ImportJob
from app.models.integration_event_log import IntegrationEventLog
from app.models.knowledge_article import KnowledgeArticle
from app.models.knowledge_category import KnowledgeCategory
from app.models.notification import Notification
from app.models.report_snapshot import ReportSnapshot
from app.models.saved_report import SavedReport
from app.models.sla_event import SlaEvent
from app.models.system_setting import SystemSetting
from app.models.ticket import Ticket
from app.models.ticket_history import TicketHistory
from app.models.user import User
from app.services.automation import collect_automation_overview
from app.services.audit import parse_metadata, summarize_security
from app.services.service_desk import calculate_response_minutes


CLOSED_STATUSES = {"RESOLVED", "CLOSED"}
PROBLEM_ASSET_STATUSES = {"broken", "in_repair", "maintenance"}
EXECUTIVE_REPORT_TYPES = {
    "daily_it_overview",
    "weekly_sla_report",
    "monthly_asset_report",
    "ai_usage_report",
    "security_overview_report",
}


def _uuid() -> str:
    return str(uuid.uuid4())


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _scoped_rows(db: Session, model: type[Any], tenant_id: str | None, column_name: str = "tenant_id") -> list[Any]:
    statement = select(model)
    if tenant_id is not None and hasattr(model, column_name):
        statement = statement.where(getattr(model, column_name) == tenant_id)
    return db.scalars(statement).all()


def _count_map(values: list[str | None], *, top: int | None = None, label_key: str = "name") -> list[dict[str, Any]]:
    counter = Counter(value or "unknown" for value in values)
    items = counter.most_common(top)
    return [{label_key: name, "count": count} for name, count in items]


def _average_resolution_minutes(tickets: list[Ticket]) -> int | None:
    values: list[int] = []
    for ticket in tickets:
        created_at = _as_utc(ticket.created_at)
        resolved_at = _as_utc(ticket.resolved_at)
        if created_at and resolved_at:
            values.append(max(0, int((resolved_at - created_at).total_seconds() // 60)))
    return round(mean(values)) if values else None


def collect_ticket_metrics(db: Session, tenant_id: str | None = None) -> dict[str, Any]:
    tickets = _scoped_rows(db, Ticket, tenant_id)
    histories = db.scalars(select(TicketHistory)).all()
    if tenant_id is not None:
        ticket_ids = {item.id for item in tickets}
        histories = [entry for entry in histories if entry.ticket_id in ticket_ids]
    history_map: dict[str, list[TicketHistory]] = defaultdict(list)
    for entry in histories:
        history_map[entry.ticket_id].append(entry)

    now = datetime.now(UTC)
    today_count = sum(1 for item in tickets if _as_utc(item.created_at) and _as_utc(item.created_at).date() == now.date())
    response_values = [calculate_response_minutes(ticket, history_map.get(ticket.id, [])) for ticket in tickets]
    normalized_response_values = [value for value in response_values if value is not None]

    return {
        "total_tickets": len(tickets),
        "open_tickets": sum(1 for item in tickets if item.status not in CLOSED_STATUSES),
        "closed_tickets": sum(1 for item in tickets if item.status in CLOSED_STATUSES),
        "tickets_today": today_count,
        "by_status": _count_map([item.status for item in tickets]),
        "by_priority": _count_map([item.priority for item in tickets]),
        "by_category": _count_map([item.category for item in tickets]),
        "average_response_minutes": round(mean(normalized_response_values)) if normalized_response_values else None,
        "average_resolution_minutes": _average_resolution_minutes(tickets),
        "top_requesters": _count_map([item.requester_name for item in tickets], top=5, label_key="name"),
        "top_assignees": _count_map([item.assignee_name or "Unassigned" for item in tickets], top=5, label_key="name"),
        "open_critical_tickets": sum(1 for item in tickets if item.priority == "CRITICAL" and item.status not in CLOSED_STATUSES),
    }


def collect_sla_metrics(db: Session, tenant_id: str | None = None) -> dict[str, Any]:
    tickets = _scoped_rows(db, Ticket, tenant_id)
    events = _scoped_rows(db, SlaEvent, tenant_id, column_name="ticket_id")
    ticket_map = {item.id: item for item in tickets}
    now = datetime.now(UTC)

    response_breaches = 0
    resolution_breaches = 0
    critical_breaches = 0
    violations_by_priority: Counter[str] = Counter()
    for event in events:
        ticket = ticket_map.get(event.ticket_id)
        if ticket is None:
            continue
        response_due_at = _as_utc(event.response_due_at)
        resolution_due_at = _as_utc(event.resolution_due_at)
        response_breached = bool(event.response_breached) or (response_due_at is not None and response_due_at < now and ticket.status in {"NEW", "TRIAGED"})
        resolution_breached = bool(event.resolution_breached) or (resolution_due_at is not None and resolution_due_at < now and ticket.status not in CLOSED_STATUSES)
        if response_breached:
            response_breaches += 1
            violations_by_priority[ticket.priority] += 1
        if resolution_breached:
            resolution_breaches += 1
            violations_by_priority[ticket.priority] += 1
        if ticket.priority == "CRITICAL" and (response_breached or resolution_breached):
            critical_breaches += 1

    at_risk = 0
    for ticket in tickets:
        due_at = _as_utc(ticket.resolution_due_at)
        if due_at and ticket.status not in CLOSED_STATUSES:
            minutes_left = (due_at - now).total_seconds() / 60
            if 0 <= minutes_left <= 60:
                at_risk += 1

    tracked_total = max(len(events), len([item for item in tickets if item.sla_policy_id]))
    total_breaches = response_breaches + resolution_breaches
    compliance = round(max(0.0, (1 - (total_breaches / tracked_total)) * 100), 1) if tracked_total else 100.0
    return {
        "sla_compliance_percent": compliance,
        "response_breaches": response_breaches,
        "resolution_breaches": resolution_breaches,
        "tickets_at_risk": at_risk,
        "critical_sla_breaches": critical_breaches,
        "violations_by_priority": [{"priority": key, "count": value} for key, value in violations_by_priority.most_common()],
    }


def collect_asset_metrics(db: Session, tenant_id: str | None = None) -> dict[str, Any]:
    assets = _scoped_rows(db, Asset, tenant_id)
    tickets = _scoped_rows(db, Ticket, tenant_id)
    ticket_counter: Counter[str] = Counter(ticket.asset_id for ticket in tickets if ticket.asset_id)
    asset_map = {item.id: item for item in assets}
    now = datetime.now(UTC)
    warranty_threshold = now + timedelta(days=45)
    problem_assets = [item for item in assets if item.status in PROBLEM_ASSET_STATUSES]
    unassigned_assets = [item for item in assets if not item.assigned_to_name or item.assigned_to_name.lower() in {"warehouse", "unassigned"}]

    top_assets = []
    for asset_id, count in ticket_counter.most_common(5):
        asset = asset_map.get(asset_id)
        if asset is None:
            continue
        top_assets.append({"asset_tag": asset.asset_tag, "name": asset.name, "count": count})

    source_counts = _count_map([item.source or "manual" for item in assets], label_key="source")
    by_purchase_year_counter: Counter[str] = Counter(str(item.purchase_year) for item in assets if item.purchase_year is not None)
    by_purchase_year = [{"year": key, "count": value} for key, value in by_purchase_year_counter.most_common()]
    missing_location_assets = [item for item in assets if item.verification_status == "needs_location"]
    disposed_assets = [item for item in assets if item.status == "disposed"]
    imported_assets = [item for item in assets if item.source == "excel_import"]
    responsible_counter = Counter(item.assigned_to_name or "Unassigned" for item in assets)
    inventory_counter = Counter(item.inventory_number for item in assets if item.inventory_number)
    duplicate_inventory_numbers = [
        {"inventory_number": number, "count": count}
        for number, count in inventory_counter.items()
        if count > 1
    ]

    return {
        "total_assets": len(assets),
        "assets_by_type": _count_map([item.asset_type for item in assets], label_key="type"),
        "assets_by_status": _count_map([item.status for item in assets], label_key="status"),
        "problem_assets": [{"asset_tag": item.asset_tag, "name": item.name, "status": item.status} for item in problem_assets[:10]],
        "problem_assets_count": len(problem_assets),
        "top_assets_by_ticket_count": top_assets,
        "warranty_expiring_soon": [
            {"asset_tag": item.asset_tag, "name": item.name, "warranty_until": item.warranty_until}
            for item in assets
            if _as_utc(item.warranty_until) and _as_utc(item.warranty_until) <= warranty_threshold
        ][:10],
        "unassigned_assets": [{"asset_tag": item.asset_tag, "name": item.name} for item in unassigned_assets[:10]],
        "unassigned_assets_count": len(unassigned_assets),
        "imported_assets_count": len(imported_assets),
        "assets_missing_location_count": len(missing_location_assets),
        "disposed_assets_count": len(disposed_assets),
        "assets_by_source": source_counts,
        "assets_by_purchase_year": by_purchase_year,
        "top_responsible_persons": [{"name": key, "count": value} for key, value in responsible_counter.most_common(10)],
        "duplicate_inventory_numbers": duplicate_inventory_numbers,
    }


def _confidence_to_score(confidence: str) -> float:
    mapping = {"high": 0.92, "medium": 0.78, "low": 0.61}
    return mapping.get(confidence.lower(), 0.65)


def collect_ai_metrics(db: Session, tenant_id: str | None = None) -> dict[str, Any]:
    suggestions = db.scalars(select(AiSuggestion).join(Ticket, Ticket.id == AiSuggestion.ticket_id, isouter=True)).all()
    if tenant_id is not None:
        suggestions = [item for item in suggestions if item.ticket is None or item.ticket.tenant_id == tenant_id]
    tickets = _scoped_rows(db, Ticket, tenant_id)
    category_counter = Counter(item.recommended_category for item in suggestions)
    priority_counter = Counter(item.recommended_priority for item in suggestions)
    confidence_values = [_confidence_to_score(item.confidence) for item in suggestions]
    applied_demo = sum(1 for item in suggestions if item.recommended_article_id or item.recommended_assignee)
    frequent_topics = Counter(item.category for item in tickets)
    return {
        "total_ai_analyses": len(suggestions),
        "average_confidence_percent": round(mean(confidence_values) * 100, 1) if confidence_values else 0.0,
        "recommendations_by_category": [{"category": key, "count": value} for key, value in category_counter.most_common()],
        "recommendations_by_priority": [{"priority": key, "count": value} for key, value in priority_counter.most_common()],
        "ai_suggestions_applied_demo": applied_demo,
        "frequent_request_topics": [{"topic": key, "count": value} for key, value in frequent_topics.most_common(5)],
    }


def collect_knowledge_metrics(db: Session, tenant_id: str | None = None) -> dict[str, Any]:
    articles = db.scalars(select(KnowledgeArticle)).all()
    categories = db.scalars(select(KnowledgeCategory)).all()
    tickets = _scoped_rows(db, Ticket, tenant_id)
    article_category_codes = {item.ticket_category for item in articles if item.ticket_category}
    top_articles = sorted(articles, key=lambda item: (item.helpful_count, item.created_at), reverse=True)[:5]
    negative_feedback = [item for item in articles if item.not_helpful_count > 0]
    resolved_via_knowledge = sum(1 for ticket in tickets if ticket.status in CLOSED_STATUSES and ticket.category in article_category_codes)
    return {
        "total_articles": len(articles),
        "published_articles": sum(1 for item in articles if item.status == "published"),
        "top_helpful_articles": [
            {
                "article_number": item.article_number,
                "title": item.title,
                "helpful_count": item.helpful_count,
            }
            for item in top_articles
        ],
        "articles_with_negative_feedback": [
            {
                "article_number": item.article_number,
                "title": item.title,
                "not_helpful_count": item.not_helpful_count,
            }
            for item in negative_feedback[:10]
        ],
        "categories_without_articles": [
            {"code": item.code, "name": item.name}
            for item in categories
            if item.code not in article_category_codes
        ],
        "tickets_resolved_via_knowledge_demo": resolved_via_knowledge,
    }


def collect_notification_metrics(db: Session, tenant_id: str | None = None) -> dict[str, Any]:
    notifications = db.scalars(select(Notification)).all()
    if tenant_id is not None:
        users = _scoped_rows(db, User, tenant_id)
        emails = {item.email for item in users}
        notifications = [item for item in notifications if item.recipient_email in emails]
    email_logs = db.scalars(select(EmailMessageLog)).all()
    if tenant_id is not None:
        tickets = _scoped_rows(db, Ticket, tenant_id)
        ticket_ids = {item.id for item in tickets}
        email_logs = [item for item in email_logs if item.related_ticket_id in ticket_ids or item.related_ticket_id is None]
    return {
        "total_notifications": len(notifications),
        "unread_notifications": sum(1 for item in notifications if item.status == "UNREAD"),
        "email_log_count": len(email_logs),
        "mock_email_success": sum(1 for item in email_logs if item.status == "SENT"),
        "mock_email_failed": sum(1 for item in email_logs if item.status == "FAILED"),
        "events_by_type": _count_map([item.type for item in notifications], label_key="type"),
    }


def collect_security_metrics(db: Session, tenant_id: str | None = None) -> dict[str, Any]:
    summary = summarize_security(db)
    logs = _scoped_rows(db, AuditLog, tenant_id)
    settings = _scoped_rows(db, SystemSetting, tenant_id)
    if tenant_id is not None:
        summary["failed_logins_24h"] = sum(1 for item in logs if item.action == "login_failed" and _as_utc(item.created_at) and _as_utc(item.created_at) >= datetime.now(UTC) - timedelta(hours=24))
        summary["success_logins_24h"] = sum(1 for item in logs if item.action == "login_success" and _as_utc(item.created_at) and _as_utc(item.created_at) >= datetime.now(UTC) - timedelta(hours=24))
        summary["active_users"] = sum(1 for item in _scoped_rows(db, User, tenant_id) if item.is_active)
        summary["recent_security_events"] = [
            {
                "id": item.id,
                "action": item.action,
                "actor_email": item.actor_email,
                "created_at": item.created_at,
                "metadata": parse_metadata(item.metadata_json),
            }
            for item in sorted(logs, key=lambda entry: _as_utc(entry.created_at) or datetime.now(UTC), reverse=True)
            if item.action.startswith("security.")
        ][:10]
    admin_changes_today = 0
    now = datetime.now(UTC)
    for log in logs:
        created_at = _as_utc(log.created_at)
        if created_at and created_at.date() == now.date() and (
            log.action.startswith("user_") or log.action.startswith("role_") or log.action.startswith("setting_")
        ):
            admin_changes_today += 1
    return {
        "login_success": summary["success_logins_24h"],
        "login_failed": summary["failed_logins_24h"],
        "audit_events_count": len(logs),
        "admin_changes_today": admin_changes_today,
        "risk_summary": summary,
        "sensitive_settings_count": sum(1 for item in settings if item.is_sensitive),
    }


def collect_integration_metrics(db: Session, tenant_id: str | None = None) -> dict[str, Any]:
    systems = _scoped_rows(db, ExternalSystem, tenant_id)
    events = _scoped_rows(db, IntegrationEventLog, tenant_id)
    jobs = _scoped_rows(db, ImportJob, tenant_id)
    enabled_systems = [item for item in systems if item.is_enabled]
    systems_with_errors = [item for item in systems if item.last_health_status in {"error", "failed", "degraded"}]
    last_health_check = max((_as_utc(item.last_health_checked_at) for item in systems if item.last_health_checked_at), default=None)
    failed_events = [item for item in events if item.status in {"failed", "error"}]
    active_jobs = [item for item in jobs if item.status in {"queued", "running", "in_progress"}]
    total_success = sum(item.records_success for item in jobs)
    total_records = sum(item.records_total for item in jobs)
    import_success_rate = round((total_success / total_records) * 100, 1) if total_records else 100.0
    health_score = max(0, 100 - len(systems_with_errors) * 15 - len(failed_events) * 2)
    return {
        "total_systems": len(systems),
        "enabled_systems": len(enabled_systems),
        "systems_by_status": _count_map([item.status for item in systems], label_key="status"),
        "systems_with_errors": len(systems_with_errors),
        "last_health_check": last_health_check,
        "active_import_jobs": len(active_jobs),
        "integration_events_count": len(events),
        "failed_integration_events": len(failed_events),
        "import_success_rate": import_success_rate,
        "integrations_health_score": health_score,
        "recent_integration_events": [
            {
                "id": item.id,
                "event_type": item.event_type,
                "status": item.status,
                "correlation_id": item.correlation_id,
                "created_at": item.created_at,
            }
            for item in sorted(events, key=lambda entry: _as_utc(entry.created_at) or datetime.now(UTC), reverse=True)[:5]
        ],
    }


def collect_executive_summary(db: Session, tenant_id: str | None = None) -> dict[str, Any]:
    ticket_metrics = collect_ticket_metrics(db, tenant_id)
    sla_metrics = collect_sla_metrics(db, tenant_id)
    asset_metrics = collect_asset_metrics(db, tenant_id)
    ai_metrics = collect_ai_metrics(db, tenant_id)
    security_metrics = collect_security_metrics(db, tenant_id)
    knowledge_metrics = collect_knowledge_metrics(db, tenant_id)
    integration_metrics = collect_integration_metrics(db, tenant_id)
    automation_metrics = collect_automation_overview(db, tenant_id)

    workload_score = max(0, 100 - ticket_metrics["open_tickets"] * 4 - ticket_metrics["open_critical_tickets"] * 7)
    sla_risk_score = max(0, int(sla_metrics["sla_compliance_percent"] - sla_metrics["critical_sla_breaches"] * 8))
    asset_risk_score = max(0, 100 - asset_metrics["problem_assets_count"] * 10 - asset_metrics["unassigned_assets_count"] * 4)
    security_risk_score = max(0, 100 - security_metrics["login_failed"] * 6 - security_metrics["admin_changes_today"] * 2)
    ai_maturity_score = min(100, int(ai_metrics["average_confidence_percent"] * 0.7 + ai_metrics["total_ai_analyses"] * 4))
    integrations_health_score = integration_metrics["integrations_health_score"]
    workflow_automation_score = int(
        max(
            0,
            min(
                100,
                automation_metrics["automation_success_rate"] * 0.6
                + min(30, automation_metrics["active_rules"] * 2)
                + min(20, automation_metrics["runbooks_available"]),
            ),
        )
    )
    health_score = round(
        mean(
            [
                workload_score,
                sla_risk_score,
                asset_risk_score,
                security_risk_score,
                ai_maturity_score,
                integrations_health_score,
                workflow_automation_score,
            ]
        )
    )

    problems = [
        {"title": "Открытые критические заявки", "value": ticket_metrics["open_critical_tickets"]},
        {"title": "SLA breaches", "value": sla_metrics["response_breaches"] + sla_metrics["resolution_breaches"]},
        {"title": "Проблемные активы", "value": asset_metrics["problem_assets_count"]},
        {"title": "Failed logins", "value": security_metrics["login_failed"]},
        {"title": "Категории без статей", "value": len(knowledge_metrics["categories_without_articles"])},
    ]
    recommendations = [
        "Ускорить triage критических и high-priority заявок с SLA risk.",
        "Закрыть пробелы в knowledge base по категориям без статей.",
        "Снизить число проблемных активов через плановую замену и ремонт.",
        "Проверить причины failed logins и усилить security awareness.",
        "Расширить использование AI Copilot в повторяющихся категориях обращений.",
        "Стабилизировать integration health по системам с degraded/failed checks.",
    ]
    return {
        "health_score": health_score,
        "it_workload_score": workload_score,
        "sla_risk_score": sla_risk_score,
        "asset_risk_score": asset_risk_score,
        "security_risk_score": security_risk_score,
        "ai_maturity_score": ai_maturity_score,
        "integrations_health_score": integrations_health_score,
        "workflow_automation_score": workflow_automation_score,
        "top_5_problems": problems[:5],
        "top_5_recommendations": recommendations[:5],
    }


def collect_overview(db: Session, tenant_id: str | None = None) -> dict[str, Any]:
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
    }


def report_payload_for_type(db: Session, report_type: str, tenant_id: str | None = None) -> dict[str, Any]:
    mapping = {
        "overview": lambda: collect_overview(db, tenant_id),
        "tickets": lambda: collect_ticket_metrics(db, tenant_id),
        "sla": lambda: collect_sla_metrics(db, tenant_id),
        "assets": lambda: collect_asset_metrics(db, tenant_id),
        "ai": lambda: collect_ai_metrics(db, tenant_id),
        "knowledge": lambda: collect_knowledge_metrics(db, tenant_id),
        "notifications": lambda: collect_notification_metrics(db, tenant_id),
        "security": lambda: collect_security_metrics(db, tenant_id),
        "automation": lambda: collect_automation_overview(db, tenant_id),
        "executive-summary": lambda: collect_executive_summary(db, tenant_id),
        "daily_it_overview": lambda: collect_overview(db, tenant_id),
        "weekly_sla_report": lambda: collect_sla_metrics(db, tenant_id),
        "monthly_asset_report": lambda: collect_asset_metrics(db, tenant_id),
        "ai_usage_report": lambda: collect_ai_metrics(db, tenant_id),
        "security_overview_report": lambda: collect_security_metrics(db, tenant_id),
    }
    resolver = mapping.get(report_type)
    if resolver is None:
        return collect_overview(db, tenant_id)
    return resolver()


def seed_reporting_demo_data(db: Session, tenant_id: str | None, created_by: str) -> None:
    saved_defs = [
        ("Ежедневный отчёт ИТ-службы", "daily_it_overview"),
        ("Отчёт по SLA", "weekly_sla_report"),
        ("Проблемные активы", "monthly_asset_report"),
        ("Использование AI Copilot", "ai_usage_report"),
        ("Security Overview", "security_overview_report"),
    ]
    saved_reports = _scoped_rows(db, SavedReport, tenant_id)
    existing_saved = {(item.tenant_id, item.name) for item in saved_reports}
    now = datetime.now(UTC)
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
                filters_json=json.dumps({"scope": report_type}, ensure_ascii=False),
                created_by=created_by,
                created_at=now,
                updated_at=now,
            )
        )

    snapshot_reports = _scoped_rows(db, ReportSnapshot, tenant_id)
    existing_types = {(item.tenant_id, item.report_type) for item in snapshot_reports}
    for report_type in EXECUTIVE_REPORT_TYPES:
        key = (tenant_id, report_type)
        if key in existing_types:
            continue
        payload = report_payload_for_type(db, report_type, tenant_id)
        db.add(
            ReportSnapshot(
                id=_uuid(),
                tenant_id=tenant_id,
                report_type=report_type,
                period_from=now - timedelta(days=30),
                period_to=now,
                payload_json=json.dumps(payload, ensure_ascii=False, default=str),
                created_at=now,
                created_by=created_by,
            )
        )
