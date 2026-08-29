from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
import math
import time

from redis import Redis
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import engine
from app.models.ai_runtime_controls import AiProviderCircuit, AiUsageLedger
from app.models.audit_log import AuditLog
from app.models.email_channel import EmailAttachment
from app.models.email_message_log import EmailMessageLog
from app.models.integration_platform import OutboundWebhookDelivery
from app.models.job_queue_outbox import JobQueueOutbox
from app.models.job_run import JobRun
from app.models.sla import TicketSlaTarget
from app.models.teams_collaboration import TeamsDelivery
from app.models.ticket import Ticket


_WORKER_HEARTBEAT_KEY = "sbs:jobs:worker:heartbeat"
_SCHEDULER_HEARTBEAT_KEY = "sbs:jobs:scheduler:heartbeat"
_WINDOW_MINUTES = 5
_AUTH_ACTIONS = (
    "login_success",
    "login_failed",
    "login_mfa_challenge",
    "login_mfa_failed",
    "oidc_login_success",
    "oidc_login_failed",
)
_ATTACHMENT_SCAN_STATUSES = ("NOT_REQUIRED", "PENDING", "CLEAN", "INFECTED", "ERROR")


def _escape(value: object) -> str:
    return (
        str(value)
        .replace("\\", "\\\\")
        .replace("\n", "\\n")
        .replace('"', '\\"')
    )


def _labels(values: dict[str, object]) -> str:
    if not values:
        return ""
    encoded = ",".join(
        f'{key}="{_escape(value)}"' for key, value in sorted(values.items())
    )
    return f"{{{encoded}}}"


class _PrometheusSnapshot:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def family(self, name: str, help_text: str, metric_type: str = "gauge") -> None:
        self.lines.extend(
            [
                f"# HELP {name} {help_text}",
                f"# TYPE {name} {metric_type}",
            ]
        )

    def sample(
        self,
        name: str,
        value: int | float,
        **labels: object,
    ) -> None:
        safe_value = float(value)
        if not math.isfinite(safe_value):
            safe_value = 0.0
        rendered = str(int(safe_value)) if safe_value.is_integer() else f"{safe_value:.6f}"
        self.lines.append(f"{name}{_labels(labels)} {rendered}")

    def render(self) -> str:
        return "\n".join(self.lines) + "\n"


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _age_seconds(value: datetime | None, now: datetime) -> float:
    aware = _aware(value)
    return max(0.0, (now - aware).total_seconds()) if aware is not None else 0.0


def _timestamp_age_seconds(value: str | None, now: datetime) -> float:
    if value is None:
        return 0.0
    try:
        return max(0.0, now.timestamp() - float(value))
    except (TypeError, ValueError):
        return 0.0


def _group_counts(
    db: Session,
    model: type,
    status_column,
    *,
    where: Iterable | None = None,
) -> dict[str, int]:
    statement = select(status_column, func.count()).select_from(model)
    if where:
        statement = statement.where(*where)
    statement = statement.group_by(status_column)
    return {
        str(status): int(count)
        for status, count in db.execute(statement).all()
        if status is not None
    }


def _database_metrics(
    snapshot: _PrometheusSnapshot,
    db: Session,
    *,
    now: datetime,
) -> None:
    started = time.perf_counter()
    db.execute(select(1)).scalar_one()
    snapshot.sample("sbs_dependency_ready", 1, dependency="postgres")
    snapshot.sample(
        "sbs_dependency_probe_duration_seconds",
        time.perf_counter() - started,
        dependency="postgres",
    )

    pool = engine.pool
    snapshot.family(
        "sbs_database_pool_connections",
        "SQLAlchemy database pool connection state.",
    )
    for state, getter in (
        ("checked_out", getattr(pool, "checkedout", None)),
        ("checked_in", getattr(pool, "checkedin", None)),
        ("overflow", getattr(pool, "overflow", None)),
        ("size", getattr(pool, "size", None)),
    ):
        if callable(getter):
            snapshot.sample(
                "sbs_database_pool_connections",
                max(0, int(getter())),
                state=state,
            )

    job_counts = _group_counts(db, JobRun, JobRun.status)
    snapshot.family("sbs_jobs", "Persisted jobs by lifecycle status.")
    for job_status, count in sorted(job_counts.items()):
        snapshot.sample("sbs_jobs", count, status=job_status)

    oldest_queued = db.scalar(
        select(func.min(JobRun.queued_at)).where(JobRun.status == "queued")
    )
    snapshot.family(
        "sbs_job_queue_oldest_age_seconds",
        "Age of the oldest persisted queued job.",
    )
    snapshot.sample(
        "sbs_job_queue_oldest_age_seconds",
        _age_seconds(oldest_queued, now),
    )

    pending_outbox = int(
        db.scalar(
            select(func.count())
            .select_from(JobQueueOutbox)
            .where(JobQueueOutbox.published_at.is_(None))
        )
        or 0
    )
    oldest_outbox = db.scalar(
        select(func.min(JobQueueOutbox.created_at)).where(
            JobQueueOutbox.published_at.is_(None)
        )
    )
    snapshot.family(
        "sbs_job_outbox_pending",
        "Job outbox records not yet published to Redis.",
    )
    snapshot.sample("sbs_job_outbox_pending", pending_outbox)
    snapshot.family(
        "sbs_job_outbox_oldest_age_seconds",
        "Age of the oldest unpublished job outbox record.",
    )
    snapshot.sample(
        "sbs_job_outbox_oldest_age_seconds",
        _age_seconds(oldest_outbox, now),
    )

    snapshot.family(
        "sbs_delivery_items",
        "Notification and integration delivery items by channel and status.",
    )
    delivery_specs = (
        (
            "email",
            EmailMessageLog,
            EmailMessageLog.status,
            [EmailMessageLog.direction == "OUTBOUND"],
        ),
        ("teams", TeamsDelivery, TeamsDelivery.status, []),
        (
            "webhook",
            OutboundWebhookDelivery,
            OutboundWebhookDelivery.status,
            [],
        ),
    )
    for channel, model, status_column, conditions in delivery_specs:
        for delivery_status, count in sorted(
            _group_counts(
                db,
                model,
                status_column,
                where=conditions,
            ).items()
        ):
            snapshot.sample(
                "sbs_delivery_items",
                count,
                channel=channel,
                status=delivery_status,
            )

    snapshot.family(
        "sbs_delivery_queue_oldest_age_seconds",
        "Age of the oldest item waiting for a channel delivery attempt.",
    )
    email_oldest = db.scalar(
        select(func.min(EmailMessageLog.created_at)).where(
            EmailMessageLog.direction == "OUTBOUND",
            EmailMessageLog.status.in_(["QUEUED", "RETRY"]),
        )
    )
    teams_oldest = db.scalar(
        select(func.min(TeamsDelivery.created_at)).where(
            TeamsDelivery.status.in_(["QUEUED", "RETRY"])
        )
    )
    webhook_oldest = db.scalar(
        select(func.min(OutboundWebhookDelivery.created_at)).where(
            OutboundWebhookDelivery.status.in_(["PENDING", "RETRY"])
        )
    )
    for channel, oldest in (
        ("email", email_oldest),
        ("teams", teams_oldest),
        ("webhook", webhook_oldest),
    ):
        snapshot.sample(
            "sbs_delivery_queue_oldest_age_seconds",
            _age_seconds(oldest, now),
            channel=channel,
        )

    snapshot.family(
        "sbs_delivery_failures_window",
        f"Terminal delivery failures created during the latest {_WINDOW_MINUTES}-minute window.",
    )
    failure_specs = (
        (
            "email",
            EmailMessageLog,
            EmailMessageLog.status.in_(["FAILED", "BOUNCED"]),
            EmailMessageLog.created_at,
        ),
        (
            "teams",
            TeamsDelivery,
            TeamsDelivery.status.in_(["FAILED", "DEAD_LETTER"]),
            TeamsDelivery.created_at,
        ),
        (
            "webhook",
            OutboundWebhookDelivery,
            OutboundWebhookDelivery.status.in_(["FAILED", "DEAD_LETTER"]),
            OutboundWebhookDelivery.created_at,
        ),
    )
    cutoff = now - timedelta(minutes=_WINDOW_MINUTES)
    for channel, model, failure_condition, created_column in failure_specs:
        failures = int(
            db.scalar(
                select(func.count())
                .select_from(model)
                .where(failure_condition, created_column >= cutoff)
            )
            or 0
        )
        snapshot.sample(
            "sbs_delivery_failures_window",
            failures,
            channel=channel,
        )

    snapshot.family(
        "sbs_auth_events_window",
        f"Authentication events during the latest {_WINDOW_MINUTES}-minute window.",
    )
    auth_counts = _group_counts(
        db,
        AuditLog,
        AuditLog.action,
        where=[AuditLog.action.in_(_AUTH_ACTIONS), AuditLog.created_at >= cutoff],
    )
    for action in _AUTH_ACTIONS:
        snapshot.sample(
            "sbs_auth_events_window",
            auth_counts.get(action, 0),
            event=action,
        )

    snapshot.family(
        "sbs_attachment_scan_items",
        "Stored email attachments by malware scan status.",
    )
    scan_counts = _group_counts(
        db,
        EmailAttachment,
        EmailAttachment.scan_status,
    )
    for scan_status in _ATTACHMENT_SCAN_STATUSES:
        snapshot.sample(
            "sbs_attachment_scan_items",
            scan_counts.get(scan_status, 0),
            status=scan_status,
        )
    oldest_quarantined = db.scalar(
        select(func.min(EmailAttachment.created_at)).where(
            EmailAttachment.status == "QUARANTINED",
            EmailAttachment.scan_status.in_(["PENDING", "ERROR"]),
        )
    )
    snapshot.family(
        "sbs_attachment_quarantine_oldest_age_seconds",
        "Age of the oldest attachment awaiting a clean malware scan.",
    )
    snapshot.sample(
        "sbs_attachment_quarantine_oldest_age_seconds",
        _age_seconds(oldest_quarantined, now),
    )

    snapshot.family(
        "sbs_ai_requests_window",
        f"AI requests observed during the latest {_WINDOW_MINUTES}-minute window.",
    )
    ai_rows = db.execute(
        select(
            AiUsageLedger.provider,
            AiUsageLedger.outcome,
            func.count(),
            func.avg(AiUsageLedger.latency_ms),
        )
        .where(AiUsageLedger.created_at >= cutoff)
        .group_by(AiUsageLedger.provider, AiUsageLedger.outcome)
    ).all()
    snapshot.family(
        "sbs_ai_latency_milliseconds_window_average",
        f"Average AI provider latency during the latest {_WINDOW_MINUTES}-minute window.",
    )
    for provider, outcome, count, average_latency in ai_rows:
        snapshot.sample(
            "sbs_ai_requests_window",
            int(count),
            provider=provider,
            outcome=outcome,
        )
        snapshot.sample(
            "sbs_ai_latency_milliseconds_window_average",
            float(average_latency or 0),
            provider=provider,
            outcome=outcome,
        )

    snapshot.family(
        "sbs_ai_provider_circuits",
        "AI provider circuit breakers by state.",
    )
    for state, count in sorted(
        _group_counts(db, AiProviderCircuit, AiProviderCircuit.state).items()
    ):
        snapshot.sample("sbs_ai_provider_circuits", count, state=state)

    snapshot.family(
        "sbs_sla_targets",
        "Current ticket SLA targets by state.",
    )
    for target_status, count in sorted(
        _group_counts(db, TicketSlaTarget, TicketSlaTarget.status).items()
    ):
        snapshot.sample("sbs_sla_targets", count, status=target_status)
    recent_sla_breaches = int(
        db.scalar(
            select(func.count())
            .select_from(TicketSlaTarget)
            .where(
                TicketSlaTarget.breached_at.is_not(None),
                TicketSlaTarget.breached_at >= cutoff,
            )
        )
        or 0
    )
    snapshot.family(
        "sbs_sla_breaches_window",
        f"Ticket SLA breaches during the latest {_WINDOW_MINUTES}-minute window.",
    )
    snapshot.sample("sbs_sla_breaches_window", recent_sla_breaches)

    created_tickets = int(
        db.scalar(
            select(func.count())
            .select_from(Ticket)
            .where(Ticket.created_at >= cutoff)
        )
        or 0
    )
    closed_tickets = int(
        db.scalar(
            select(func.count())
            .select_from(Ticket)
            .where(Ticket.closed_at.is_not(None), Ticket.closed_at >= cutoff)
        )
        or 0
    )
    snapshot.family(
        "sbs_business_transactions_window",
        f"Core business transactions during the latest {_WINDOW_MINUTES}-minute window.",
    )
    snapshot.sample(
        "sbs_business_transactions_window",
        created_tickets,
        transaction="ticket_created",
    )
    snapshot.sample(
        "sbs_business_transactions_window",
        closed_tickets,
        transaction="ticket_closed",
    )


def _redis_metrics(
    snapshot: _PrometheusSnapshot,
    *,
    now: datetime,
) -> None:
    settings = get_settings()
    started = time.perf_counter()
    client = Redis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=1,
        socket_timeout=1,
    )
    try:
        client.ping()
        snapshot.sample("sbs_dependency_ready", 1, dependency="redis")
        snapshot.sample(
            "sbs_dependency_probe_duration_seconds",
            time.perf_counter() - started,
            dependency="redis",
        )

        snapshot.family(
            "sbs_job_queue_depth",
            "Redis job queue depth by queue state.",
        )
        snapshot.sample(
            "sbs_job_queue_depth",
            int(client.llen(settings.jobs_queue_name)),
            queue="ready",
        )
        snapshot.sample(
            "sbs_job_queue_depth",
            int(client.zcard(f"{settings.jobs_queue_name}:scheduled")),
            queue="scheduled",
        )
        snapshot.sample(
            "sbs_job_queue_depth",
            int(client.llen(settings.jobs_dead_letter_queue_name)),
            queue="dead_letter",
        )

        heartbeat_raw = client.get(_WORKER_HEARTBEAT_KEY)
        heartbeat_age = _timestamp_age_seconds(heartbeat_raw, now)
        snapshot.family(
            "sbs_worker_ready",
            "Whether a jobs worker heartbeat was observed recently.",
        )
        snapshot.family(
            "sbs_worker_heartbeat_age_seconds",
            "Age of the latest jobs worker heartbeat.",
        )
        snapshot.sample(
            "sbs_worker_ready",
            int(heartbeat_raw is not None and heartbeat_age <= 30),
            worker="jobs",
        )
        snapshot.sample(
            "sbs_worker_heartbeat_age_seconds",
            heartbeat_age,
            worker="jobs",
        )

        scheduler_heartbeat_raw = client.get(_SCHEDULER_HEARTBEAT_KEY)
        scheduler_heartbeat_age = _timestamp_age_seconds(
            scheduler_heartbeat_raw,
            now,
        )
        snapshot.family(
            "sbs_scheduler_ready",
            "Whether the leader-elected periodic scheduler heartbeat is current.",
        )
        snapshot.family(
            "sbs_scheduler_heartbeat_age_seconds",
            "Age of the latest leader scheduler heartbeat.",
        )
        snapshot.sample(
            "sbs_scheduler_ready",
            int(
                scheduler_heartbeat_raw is not None
                and scheduler_heartbeat_age
                <= settings.scheduler_heartbeat_max_age_seconds
            ),
        )
        snapshot.sample(
            "sbs_scheduler_heartbeat_age_seconds",
            scheduler_heartbeat_age,
        )
    finally:
        client.close()


def render_operational_metrics(db: Session) -> str:
    """Render bounded, low-cardinality operational metrics for Prometheus.

    A failed database or Redis probe is represented as a metric instead of
    failing the scrape, so monitoring remains useful during dependency outages.
    """

    snapshot = _PrometheusSnapshot()
    now = datetime.now(UTC)
    snapshot.family(
        "sbs_operational_snapshot_success",
        "Whether the latest operational metric family collection succeeded.",
    )
    snapshot.family(
        "sbs_dependency_ready",
        "Whether a required platform dependency is reachable.",
    )
    snapshot.family(
        "sbs_dependency_probe_duration_seconds",
        "Duration of the latest dependency probe.",
    )

    database_ok = True
    try:
        database_snapshot = _PrometheusSnapshot()
        _database_metrics(database_snapshot, db, now=now)
        snapshot.lines.extend(database_snapshot.lines)
    except Exception:
        database_ok = False
        db.rollback()
        snapshot.sample("sbs_dependency_ready", 0, dependency="postgres")

    redis_ok = True
    try:
        redis_snapshot = _PrometheusSnapshot()
        _redis_metrics(redis_snapshot, now=now)
        snapshot.lines.extend(redis_snapshot.lines)
    except Exception:
        redis_ok = False
        snapshot.sample("sbs_dependency_ready", 0, dependency="redis")

    snapshot.sample(
        "sbs_operational_snapshot_success",
        int(database_ok),
        collector="database",
    )
    snapshot.sample(
        "sbs_operational_snapshot_success",
        int(redis_ok),
        collector="redis",
    )
    return snapshot.render()


__all__ = [
    "_WORKER_HEARTBEAT_KEY",
    "render_operational_metrics",
]
