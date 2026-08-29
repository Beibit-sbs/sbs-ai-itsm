from functools import lru_cache
import ipaddress
import json
import os
import re
from urllib.parse import urlsplit

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


_SECRET_PLACEHOLDER_MARKERS = (
    "CHANGE-ME",
    "CHANGEME",
    "DISABLED-",
    "GENERATE-",
    "REPLACE",
)


def _is_placeholder_secret(value: str | None) -> bool:
    if not value:
        return True
    normalized = value.strip().upper()
    return any(marker in normalized for marker in _SECRET_PLACEHOLDER_MARKERS)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "SBS AI ITSM"
    app_env: str = "development"
    app_version: str = "0.1.0"
    log_level: str = "INFO"
    api_v1_prefix: str = "/api/v1"
    backend_cors_origins: list[str] | str = ["http://localhost:5173", "http://localhost:5174"]
    trusted_hosts: list[str] | str = ["localhost", "127.0.0.1", "testserver", "backend"]
    forwarded_allow_ips: list[str] | str = ["127.0.0.1"]
    jwt_secret_key: str = "change-me-in-production"
    access_token_ttl_minutes: int = 30
    refresh_token_ttl_minutes: int = 10080
    login_rate_limit_attempts: int = 5
    login_ip_rate_limit_attempts: int = 25
    login_rate_limit_window_seconds: int = 300
    api_max_request_body_bytes: int = 6_291_456
    database_pool_size: int = 10
    database_max_overflow: int = 5
    database_pool_timeout_seconds: int = 30
    database_pool_recycle_seconds: int = 1800
    demo_mode: bool = True
    seed_demo_catalog: bool = False
    run_startup_ddl: bool = True
    demo_root_email: str = "root@sbs.local"
    demo_root_password: str = "Root!2026"
    demo_admin_email: str = "admin@sbs.local"
    demo_admin_password: str = "Sbs!2026"
    bootstrap_root_email: str | None = None
    bootstrap_root_password: str | None = None
    metrics_auth_token: str | None = None
    prometheus_url: str = "http://localhost:9090"
    prometheus_timeout_seconds: int = 10
    cloudwatch_region: str = "us-east-1"
    cloudwatch_namespace: str = "SBS-AI-ITSM"
    alertmanager_webhook_token: str | None = None
    jobs_alert_smtp_host: str | None = None
    jobs_alert_smtp_port: int = 587
    jobs_alert_smtp_from_address: str | None = None
    jobs_alert_smtp_username: str | None = None
    jobs_alert_smtp_password: str | None = None
    jobs_alert_smtp_starttls: bool = True
    jobs_alert_email_recipients: list[str] | str = []
    jobs_alert_slack_webhook_url: str | None = None
    jobs_alert_pagerduty_routing_key: str | None = None
    jobs_alert_webhook_url: str | None = None
    jobs_alert_timeout_seconds: int = 10
    oidc_enabled: bool = False
    oidc_provider_name: str = "corporate"
    oidc_button_label: str = "Войти через корпоративный SSO"
    oidc_issuer_url: str | None = None
    oidc_client_id: str | None = None
    oidc_client_secret: str | None = None
    oidc_client_auth_method: str = "client_secret_basic"
    oidc_redirect_uri: str | None = None
    oidc_scopes: list[str] | str = ["openid", "profile", "email"]
    oidc_allowed_algorithms: list[str] | str = ["RS256"]
    oidc_allowed_email_domains: list[str] | str = []
    oidc_auto_provision: bool = False
    oidc_allow_email_linking: bool = False
    oidc_default_tenant_id: str | None = None
    oidc_default_role_code: str = "requester"
    oidc_state_ttl_seconds: int = 300
    oidc_metadata_cache_seconds: int = 3600
    mfa_enforcement_enabled: bool = False
    mfa_issuer_name: str = "SBS AI ITSM"
    mfa_encryption_key: str | None = None
    mfa_required_role_codes: list[str] | str = [
        "saas_root",
        "organization_admin",
        "security_officer",
    ]
    mfa_challenge_ttl_seconds: int = 300
    mfa_max_attempts: int = 5
    mfa_lockout_seconds: int = 300
    credential_encryption_key: str | None = None
    email_public_base_url: str | None = None
    email_attachment_storage_path: str = "./data/email-attachments"
    email_graph_timeout_seconds: float = 20.0
    email_poll_interval_seconds: int = 30
    email_worker_batch_size: int = 50
    email_clamav_host: str | None = None
    email_clamav_port: int = 3310
    email_attachment_manual_release_without_clean_scan: bool = False
    email_attachment_download_token_ttl_seconds: int = 60
    teams_public_base_url: str | None = None
    teams_webhook_allowed_hosts: list[str] | str = [
        ".logic.azure.com",
        ".webhook.office.com",
        ".environment.api.powerplatform.com",
        ".api.powerplatform.com",
    ]
    teams_request_timeout_seconds: float = 15.0
    teams_worker_batch_size: int = 50
    monitoring_worker_batch_size: int = 100
    monitoring_receipt_retention_days: int = 30
    monitoring_global_max_payload_bytes: int = 2_097_152
    asset_discovery_worker_batch_size: int = 10
    asset_discovery_request_timeout_seconds: float = 30.0
    asset_discovery_sccm_allowed_hosts: list[str] | str = ["localhost"]
    integration_platform_worker_batch_size: int = 50
    integration_platform_max_active_tokens_per_account: int = 10
    integration_platform_request_log_retention_days: int = 90
    integration_platform_delivery_retention_days: int = 90
    integration_outbound_webhook_timeout_seconds: float = 15.0
    integration_outbound_webhook_max_payload_bytes: int = 262_144
    integration_outbound_webhook_allowed_hosts: list[str] | str = []
    workflow_worker_batch_size: int = 50
    workflow_max_context_bytes: int = 262_144
    workflow_execution_retention_days: int = 180
    configuration_package_signing_key: str | None = None
    configuration_package_max_bytes: int = 4_194_304
    configuration_package_max_components: int = 500
    database_url: str = "postgresql+psycopg://sbs_itsm:sbs_itsm@localhost:5432/sbs_itsm"
    redis_url: str = "redis://localhost:6379/0"
    dashboard_realtime_transport: str = "local"
    dashboard_pubsub_channel: str = "sbs:dashboard:events"
    dashboard_socket_token_ttl_seconds: int = 60
    dashboard_ws_session_ttl_seconds: int = 3600
    dashboard_ws_max_connections_per_tenant: int = 200
    jobs_executor_mode: str = "inline"
    jobs_queue_name: str = "jobs:queue"
    jobs_dead_letter_queue_name: str = "jobs:dead-letter"
    jobs_event_stream_name: str = "jobs:lifecycle"
    jobs_event_consumer_name: str = "notifications-consumer"
    jobs_event_automation_consumer_name: str = "automation-consumer"
    jobs_event_consumer_max_attempts: int = 3
    jobs_event_consumer_lag_alert_threshold: int = 25
    jobs_event_consumer_stale_offset_seconds: int = 300
    jobs_event_recovery_cooldown_seconds: int = 60
    jobs_event_recovery_max_exec_per_hour: int = 6
    jobs_event_recovery_require_change_ticket: bool = True
    jobs_event_recovery_dual_control_required: bool = False
    jobs_event_runbook_allowed_codes: list[str] | str = []
    jobs_event_runbook_denied_codes: list[str] | str = []
    jobs_event_runbook_high_impact_codes: list[str] | str = [
        "jobs.consumer.repeated_failures_requeue",
        "jobs.consumer.emergency_brake_reset",
    ]
    jobs_event_runbook_cooldown_seconds_map: dict[str, object] | str = {}
    jobs_event_runbook_require_change_ticket: bool = True
    jobs_event_runbook_dual_control_required: bool = False
    jobs_event_autoremediation_enabled: bool = False
    jobs_event_autoremediation_consumers: list[str] | str = ["notifications-consumer"]
    jobs_event_autoremediation_allowed_event_types: list[str] | str = ["failed", "dead_letter"]
    jobs_event_autoremediation_min_failed_age_seconds: int = 120
    jobs_event_autoremediation_max_requeued_per_cycle: int = 5
    jobs_event_autoremediation_cooldown_seconds: int = 300
    jobs_event_autoremediation_max_per_hour: int = 20
    jobs_event_autoremediation_canary_mode: bool = False
    jobs_event_autoremediation_canary_limit_per_cycle: int = 1
    jobs_event_autoremediation_burst_max_per_10m: int = 5
    jobs_event_autoremediation_brake_error_threshold: int = 3
    jobs_event_autoremediation_braked_consumers: list[str] | str = []
    jobs_event_autoremediation_policy_profiles: dict[str, object] | str = {}
    jobs_event_autoremediation_suppression_windows_utc: list[str] | str = []
    jobs_event_autoremediation_error_denylist: list[str] | str = []
    jobs_retry_base_seconds: float = 0.5
    jobs_retry_max_seconds: float = 15.0
    jobs_periodic_cycles_enabled: bool = True
    scheduler_poll_interval_seconds: int = 5
    scheduler_lease_seconds: int = 120
    scheduler_heartbeat_max_age_seconds: int = 30

    # AI provider configuration. Defaults keep the system in mock mode so no
    # external calls are performed unless an API key is explicitly provided.
    ai_provider: str = "mock"
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"
    openai_base_url: str = "https://api.openai.com/v1"
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-2.0-flash-exp"
    ai_pii_redaction: bool = True
    ai_request_timeout_seconds: float = 15.0
    ai_rag_embedding_dimensions: int = 256
    ai_rag_chunk_chars: int = 1_200
    ai_rag_chunk_overlap_chars: int = 160
    ai_rag_document_max_chars: int = 200_000
    ai_rag_max_candidate_chunks: int = 1_000
    ai_rag_max_citations: int = 8
    ai_rag_max_context_chars: int = 16_000
    ai_rag_query_log_retention_days: int = 180

    @field_validator("backend_cors_origins", mode="before")
    @classmethod
    def parse_cors(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator(
        "jobs_event_autoremediation_consumers",
        "jobs_event_autoremediation_allowed_event_types",
        "jobs_event_autoremediation_suppression_windows_utc",
        "jobs_event_autoremediation_error_denylist",
        "jobs_event_autoremediation_braked_consumers",
        "jobs_event_runbook_allowed_codes",
        "jobs_event_runbook_denied_codes",
        "jobs_event_runbook_high_impact_codes",
        "oidc_scopes",
        "oidc_allowed_algorithms",
        "oidc_allowed_email_domains",
        "mfa_required_role_codes",
        "jobs_alert_email_recipients",
        "teams_webhook_allowed_hosts",
        "asset_discovery_sccm_allowed_hosts",
        "integration_outbound_webhook_allowed_hosts",
        "trusted_hosts",
        "forwarded_allow_ips",
        mode="before",
    )
    @classmethod
    def parse_csv_lists(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator(
        "jobs_alert_smtp_host",
        "jobs_alert_smtp_from_address",
        "jobs_alert_smtp_username",
        "jobs_alert_smtp_password",
        "jobs_alert_slack_webhook_url",
        "jobs_alert_pagerduty_routing_key",
        "jobs_alert_webhook_url",
        mode="before",
    )
    @classmethod
    def disabled_optional_alert_values_become_none(cls, value: object) -> object:
        if value is None:
            return None
        normalized = str(value).strip()
        return None if _is_placeholder_secret(normalized) else normalized

    @field_validator("trusted_hosts")
    @classmethod
    def trusted_hosts_must_be_valid(cls, value: list[str]) -> list[str]:
        normalized = list(
            dict.fromkeys(item.strip().lower().rstrip(".") for item in value if item.strip())
        )
        hostname_pattern = re.compile(
            r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)"
            r"(?:\.(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?))*$"
        )
        invalid = [
            item
            for item in normalized
            if item != "*" and not hostname_pattern.fullmatch(item)
        ]
        if not normalized or invalid:
            raise ValueError("TRUSTED_HOSTS must contain valid exact hostnames")
        return normalized

    @field_validator("forwarded_allow_ips")
    @classmethod
    def forwarded_allow_ips_must_be_valid(cls, value: list[str]) -> list[str]:
        normalized = list(dict.fromkeys(item.strip() for item in value if item.strip()))
        if not normalized:
            raise ValueError("FORWARDED_ALLOW_IPS must not be empty")
        for item in normalized:
            if item == "*":
                continue
            try:
                ipaddress.ip_network(item, strict=False)
            except ValueError as exc:
                raise ValueError(
                    "FORWARDED_ALLOW_IPS must contain only IP addresses or CIDR networks"
                ) from exc
        return normalized

    @field_validator("jobs_event_autoremediation_policy_profiles", "jobs_event_runbook_cooldown_seconds_map", mode="before")
    @classmethod
    def parse_json_object(cls, value: object) -> object:
        if isinstance(value, str):
            raw = value.strip()
            if not raw:
                return {}
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValueError("JOBS_EVENT_AUTOREMEDIATION_POLICY_PROFILES must be valid JSON object") from exc
            if not isinstance(parsed, dict):
                raise ValueError("JOBS_EVENT_AUTOREMEDIATION_POLICY_PROFILES must be a JSON object")
            return parsed
        return value

    @field_validator(
        "access_token_ttl_minutes",
        "refresh_token_ttl_minutes",
        "login_rate_limit_attempts",
        "login_ip_rate_limit_attempts",
        "login_rate_limit_window_seconds",
        "api_max_request_body_bytes",
        "database_pool_size",
        "database_pool_timeout_seconds",
        "database_pool_recycle_seconds",
        "dashboard_socket_token_ttl_seconds",
        "dashboard_ws_session_ttl_seconds",
        "dashboard_ws_max_connections_per_tenant",
        "oidc_state_ttl_seconds",
        "oidc_metadata_cache_seconds",
        "mfa_challenge_ttl_seconds",
        "mfa_max_attempts",
        "mfa_lockout_seconds",
        "prometheus_timeout_seconds",
        "email_attachment_download_token_ttl_seconds",
    )
    @classmethod
    def ttl_must_be_positive(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("Token TTL must be positive")
        return value

    @model_validator(mode="after")
    def validate_login_rate_limits(self) -> "Settings":
        if self.login_rate_limit_attempts > 100:
            raise ValueError("LOGIN_RATE_LIMIT_ATTEMPTS must not exceed 100")
        if self.login_ip_rate_limit_attempts < self.login_rate_limit_attempts:
            raise ValueError(
                "LOGIN_IP_RATE_LIMIT_ATTEMPTS must be greater than or equal to "
                "LOGIN_RATE_LIMIT_ATTEMPTS"
            )
        if self.login_ip_rate_limit_attempts > 1000:
            raise ValueError("LOGIN_IP_RATE_LIMIT_ATTEMPTS must not exceed 1000")
        if self.login_rate_limit_window_seconds > 3600:
            raise ValueError(
                "LOGIN_RATE_LIMIT_WINDOW_SECONDS must not exceed 3600"
            )
        return self

    @model_validator(mode="after")
    def validate_metrics_backends(self) -> "Settings":
        prometheus = urlsplit(self.prometheus_url)
        if (
            prometheus.scheme not in {"http", "https"}
            or not prometheus.hostname
            or prometheus.username
            or prometheus.password
            or prometheus.query
            or prometheus.fragment
        ):
            raise ValueError(
                "PROMETHEUS_URL must be an explicit HTTP(S) service URL "
                "without credentials, query, or fragment"
            )
        if self.prometheus_timeout_seconds > 30:
            raise ValueError("PROMETHEUS_TIMEOUT_SECONDS must not exceed 30")
        if not re.fullmatch(r"[a-z]{2}(?:-gov)?-[a-z]+-\d", self.cloudwatch_region):
            raise ValueError("CLOUDWATCH_REGION is invalid")
        if not 1 <= len(self.cloudwatch_namespace.strip()) <= 120:
            raise ValueError("CLOUDWATCH_NAMESPACE must contain 1 to 120 characters")
        return self

    @model_validator(mode="after")
    def validate_jobs_alert_delivery(self) -> "Settings":
        email_pattern = re.compile(
            r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@"
            r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
            r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+"
        )
        recipients = [
            item.strip().lower()
            for item in self.jobs_alert_email_recipients
            if item.strip()
        ]
        if any(
            len(item) > 254 or not email_pattern.fullmatch(item)
            for item in recipients
        ):
            raise ValueError("JOBS_ALERT_EMAIL_RECIPIENTS contains an invalid address")
        self.jobs_alert_email_recipients = list(dict.fromkeys(recipients))

        smtp_configured = bool(self.jobs_alert_smtp_host)
        smtp_dependents = (
            self.jobs_alert_smtp_from_address,
            self.jobs_alert_smtp_username,
            self.jobs_alert_smtp_password,
            *self.jobs_alert_email_recipients,
        )
        if not smtp_configured and any(smtp_dependents):
            raise ValueError(
                "JOBS_ALERT_SMTP_HOST is required when SMTP alert delivery is configured"
            )
        if smtp_configured:
            if not self.jobs_alert_smtp_from_address or not email_pattern.fullmatch(
                self.jobs_alert_smtp_from_address.strip().lower()
            ):
                raise ValueError(
                    "JOBS_ALERT_SMTP_FROM_ADDRESS must be a valid email address"
                )
            if not self.jobs_alert_email_recipients:
                raise ValueError(
                    "JOBS_ALERT_EMAIL_RECIPIENTS is required for SMTP alert delivery"
                )
            if bool(self.jobs_alert_smtp_username) != bool(
                self.jobs_alert_smtp_password
            ):
                raise ValueError(
                    "JOBS_ALERT_SMTP_USERNAME and its password secret must be "
                    "configured together"
                )
        if not 1 <= self.jobs_alert_smtp_port <= 65_535:
            raise ValueError("JOBS_ALERT_SMTP_PORT must be between 1 and 65535")

        for field_name, raw_url, allowed_hosts in (
            (
                "JOBS_ALERT_SLACK_WEBHOOK_URL",
                self.jobs_alert_slack_webhook_url,
                {"hooks.slack.com", "hooks.slack-gov.com"},
            ),
            ("JOBS_ALERT_WEBHOOK_URL", self.jobs_alert_webhook_url, None),
        ):
            if not raw_url:
                continue
            parsed = urlsplit(raw_url)
            hostname = (parsed.hostname or "").lower().rstrip(".")
            if (
                parsed.scheme != "https"
                or not hostname
                or parsed.username
                or parsed.password
                or parsed.fragment
                or parsed.port not in {None, 443}
                or (allowed_hosts is not None and hostname not in allowed_hosts)
            ):
                raise ValueError(f"{field_name} must be an approved HTTPS URL")
        if (
            self.jobs_alert_pagerduty_routing_key
            and len(self.jobs_alert_pagerduty_routing_key) < 20
        ):
            raise ValueError("JOBS_ALERT_PAGERDUTY_ROUTING_KEY is too short")
        if (
            self.app_env.strip().lower() == "production"
            and smtp_configured
            and (
                not self.jobs_alert_smtp_starttls
                or self.jobs_alert_smtp_host.strip().lower()
                in {"localhost", "127.0.0.1", "::1"}
            )
        ):
            raise ValueError(
                "Production SMTP alert delivery requires STARTTLS and a non-loopback host"
            )
        return self

    @field_validator("database_max_overflow")
    @classmethod
    def database_overflow_must_be_bounded(cls, value: int) -> int:
        if value < 0 or value > 100:
            raise ValueError("DATABASE_MAX_OVERFLOW must be between 0 and 100")
        return value

    @field_validator("api_max_request_body_bytes")
    @classmethod
    def api_body_limit_must_be_bounded(cls, value: int) -> int:
        if value < 65_536 or value > 67_108_864:
            raise ValueError(
                "API_MAX_REQUEST_BODY_BYTES must be between 65536 and 67108864"
            )
        return value

    @field_validator("database_pool_size")
    @classmethod
    def database_pool_size_must_be_bounded(cls, value: int) -> int:
        if value > 100:
            raise ValueError("DATABASE_POOL_SIZE must not exceed 100")
        return value

    @field_validator("database_pool_timeout_seconds")
    @classmethod
    def database_pool_timeout_must_be_bounded(cls, value: int) -> int:
        if value > 120:
            raise ValueError("DATABASE_POOL_TIMEOUT_SECONDS must not exceed 120")
        return value

    @field_validator("database_pool_recycle_seconds")
    @classmethod
    def database_pool_recycle_must_be_bounded(cls, value: int) -> int:
        if value > 86_400:
            raise ValueError("DATABASE_POOL_RECYCLE_SECONDS must not exceed 86400")
        return value

    @field_validator(
        "email_worker_batch_size",
        "teams_worker_batch_size",
        "monitoring_worker_batch_size",
        "monitoring_receipt_retention_days",
        "monitoring_global_max_payload_bytes",
        "asset_discovery_worker_batch_size",
        "integration_platform_worker_batch_size",
        "integration_platform_max_active_tokens_per_account",
        "integration_platform_request_log_retention_days",
        "integration_platform_delivery_retention_days",
        "integration_outbound_webhook_max_payload_bytes",
        "workflow_worker_batch_size",
        "workflow_max_context_bytes",
        "workflow_execution_retention_days",
        "configuration_package_max_bytes",
        "configuration_package_max_components",
        "ai_rag_embedding_dimensions",
        "ai_rag_chunk_chars",
        "ai_rag_document_max_chars",
        "ai_rag_max_candidate_chunks",
        "ai_rag_max_citations",
        "ai_rag_max_context_chars",
        "ai_rag_query_log_retention_days",
    )
    @classmethod
    def operational_limit_must_be_positive(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("Operational limits must be positive")
        return value

    @field_validator("configuration_package_max_bytes")
    @classmethod
    def configuration_package_size_must_be_bounded(cls, value: int) -> int:
        if value > 16_777_216:
            raise ValueError("CONFIGURATION_PACKAGE_MAX_BYTES must not exceed 16777216")
        return value

    @field_validator("configuration_package_max_components")
    @classmethod
    def configuration_package_count_must_be_bounded(cls, value: int) -> int:
        if value > 2_000:
            raise ValueError("CONFIGURATION_PACKAGE_MAX_COMPONENTS must not exceed 2000")
        return value

    @field_validator("ai_rag_chunk_overlap_chars")
    @classmethod
    def rag_overlap_must_be_non_negative(cls, value: int) -> int:
        if value < 0 or value > 2_000:
            raise ValueError("AI_RAG_CHUNK_OVERLAP_CHARS must be between 0 and 2000")
        return value

    @model_validator(mode="after")
    def validate_rag_limits(self) -> "Settings":
        if self.ai_rag_chunk_overlap_chars >= self.ai_rag_chunk_chars:
            raise ValueError("AI_RAG_CHUNK_OVERLAP_CHARS must be smaller than AI_RAG_CHUNK_CHARS")
        if not 64 <= self.ai_rag_embedding_dimensions <= 2_048:
            raise ValueError("AI_RAG_EMBEDDING_DIMENSIONS must be between 64 and 2048")
        if self.ai_rag_chunk_chars > 8_000:
            raise ValueError("AI_RAG_CHUNK_CHARS must not exceed 8000")
        if self.ai_rag_document_max_chars > 2_000_000:
            raise ValueError("AI_RAG_DOCUMENT_MAX_CHARS must not exceed 2000000")
        if self.ai_rag_max_candidate_chunks > 10_000:
            raise ValueError("AI_RAG_MAX_CANDIDATE_CHUNKS must not exceed 10000")
        if self.ai_rag_max_citations > 20:
            raise ValueError("AI_RAG_MAX_CITATIONS must not exceed 20")
        if self.ai_rag_max_context_chars > 100_000:
            raise ValueError("AI_RAG_MAX_CONTEXT_CHARS must not exceed 100000")
        return self

    @field_validator(
        "email_graph_timeout_seconds",
        "teams_request_timeout_seconds",
        "asset_discovery_request_timeout_seconds",
        "integration_outbound_webhook_timeout_seconds",
        "jobs_alert_timeout_seconds",
        "ai_request_timeout_seconds",
    )
    @classmethod
    def request_timeout_must_be_positive(cls, value: float) -> float:
        if value <= 0 or value > 120:
            raise ValueError("External request timeouts must be between 0 and 120 seconds")
        return value

    @field_validator("jobs_executor_mode")
    @classmethod
    def jobs_executor_mode_must_be_supported(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"inline", "redis"}:
            raise ValueError("JOBS_EXECUTOR_MODE must be either 'inline' or 'redis'")
        return normalized

    @field_validator("dashboard_realtime_transport")
    @classmethod
    def dashboard_transport_must_be_supported(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"local", "redis"}:
            raise ValueError("DASHBOARD_REALTIME_TRANSPORT must be either 'local' or 'redis'")
        return normalized

    @field_validator("dashboard_pubsub_channel")
    @classmethod
    def dashboard_channel_must_be_safe(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized or len(normalized) > 128 or any(char.isspace() for char in normalized):
            raise ValueError("DASHBOARD_PUBSUB_CHANNEL must be a non-empty channel without whitespace")
        return normalized

    @field_validator("oidc_provider_name", "oidc_default_role_code")
    @classmethod
    def oidc_identifiers_must_be_safe(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not normalized or len(normalized) > 64 or not all(
            char.isalnum() or char in {"-", "_", "."} for char in normalized
        ):
            raise ValueError("OIDC identifiers may contain only letters, numbers, dots, dashes and underscores")
        return normalized

    @field_validator("oidc_client_auth_method")
    @classmethod
    def oidc_client_auth_method_must_be_supported(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"client_secret_basic", "client_secret_post"}:
            raise ValueError(
                "OIDC_CLIENT_AUTH_METHOD must be client_secret_basic or client_secret_post"
            )
        return normalized

    @field_validator("oidc_allowed_email_domains")
    @classmethod
    def oidc_domains_must_be_safe(cls, value: list[str]) -> list[str]:
        normalized = sorted({item.strip().lower().lstrip("@") for item in value if item.strip()})
        if any("." not in item or "/" in item or ":" in item or "@" in item for item in normalized):
            raise ValueError("OIDC_ALLOWED_EMAIL_DOMAINS contains an invalid domain")
        return normalized

    @field_validator("oidc_allowed_algorithms")
    @classmethod
    def oidc_algorithms_must_be_asymmetric(cls, value: list[str]) -> list[str]:
        allowed = {"RS256", "RS384", "RS512", "PS256", "PS384", "PS512", "ES256", "ES384", "ES512"}
        normalized = list(dict.fromkeys(item.strip().upper() for item in value if item.strip()))
        if not normalized or any(item not in allowed for item in normalized):
            raise ValueError("OIDC_ALLOWED_ALGORITHMS must contain only approved asymmetric algorithms")
        return normalized

    @field_validator("log_level")
    @classmethod
    def log_level_must_be_supported(cls, value: str) -> str:
        normalized = value.strip().upper()
        if normalized not in {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}:
            raise ValueError("LOG_LEVEL must be CRITICAL, ERROR, WARNING, INFO or DEBUG")
        return normalized

    @field_validator("jobs_retry_base_seconds", "jobs_retry_max_seconds")
    @classmethod
    def jobs_retry_values_must_be_positive(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("JOBS retry values must be positive")
        return value

    @model_validator(mode="after")
    def validate_scheduler_timing(self) -> "Settings":
        if not 1 <= self.scheduler_poll_interval_seconds <= 60:
            raise ValueError("SCHEDULER_POLL_INTERVAL_SECONDS must be between 1 and 60")
        if not 15 <= self.scheduler_lease_seconds <= 900:
            raise ValueError("SCHEDULER_LEASE_SECONDS must be between 15 and 900")
        if self.scheduler_lease_seconds < self.scheduler_poll_interval_seconds * 3:
            raise ValueError(
                "SCHEDULER_LEASE_SECONDS must be at least three times the poll interval"
            )
        if not 5 <= self.scheduler_heartbeat_max_age_seconds <= self.scheduler_lease_seconds:
            raise ValueError(
                "SCHEDULER_HEARTBEAT_MAX_AGE_SECONDS must be between 5 and the lease duration"
            )
        return self

    @field_validator(
        "jobs_event_consumer_lag_alert_threshold",
        "jobs_event_consumer_stale_offset_seconds",
        "jobs_event_recovery_cooldown_seconds",
        "jobs_event_recovery_max_exec_per_hour",
        "jobs_event_autoremediation_min_failed_age_seconds",
        "jobs_event_autoremediation_max_requeued_per_cycle",
        "jobs_event_autoremediation_cooldown_seconds",
        "jobs_event_autoremediation_max_per_hour",
        "jobs_event_autoremediation_canary_limit_per_cycle",
        "jobs_event_autoremediation_burst_max_per_10m",
        "jobs_event_autoremediation_brake_error_threshold",
    )
    @classmethod
    def jobs_event_limits_must_be_non_negative(cls, value: int) -> int:
        if value < 0:
            raise ValueError("JOBS event limits must be >= 0")
        return value

    @field_validator("jobs_event_autoremediation_policy_profiles")
    @classmethod
    def jobs_event_policy_profiles_must_be_object(cls, value: object) -> object:
        if not isinstance(value, dict):
            raise ValueError("JOBS_EVENT_AUTOREMEDIATION_POLICY_PROFILES must be an object")
        return value

    @field_validator("jobs_event_runbook_cooldown_seconds_map")
    @classmethod
    def jobs_event_runbook_cooldowns_must_be_non_negative(cls, value: object) -> object:
        if not isinstance(value, dict):
            raise ValueError("JOBS_EVENT_RUNBOOK_COOLDOWN_SECONDS_MAP must be an object")
        for key, raw in value.items():
            try:
                seconds = int(raw)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Cooldown for runbook '{key}' must be an integer") from exc
            if seconds < 0:
                raise ValueError(f"Cooldown for runbook '{key}' must be >= 0")
        return value

    @model_validator(mode="after")
    def validate_production_safety(self) -> "Settings":
        if self.app_env.strip().lower() != "production":
            return self

        errors: list[str] = []
        if self.demo_mode:
            errors.append("DEMO_MODE must be false")
        if self.run_startup_ddl:
            errors.append("RUN_STARTUP_DDL must be false; use Alembic migrations")
        if self.dashboard_realtime_transport != "redis":
            errors.append("DASHBOARD_REALTIME_TRANSPORT must be redis")
        if self.dashboard_socket_token_ttl_seconds > 300:
            errors.append("DASHBOARD_SOCKET_TOKEN_TTL_SECONDS must not exceed 300")
        if len(self.jwt_secret_key) < 32 or _is_placeholder_secret(self.jwt_secret_key):
            errors.append("JWT_SECRET_KEY must be a non-placeholder secret of at least 32 characters")
        if bool(self.bootstrap_root_email) != bool(self.bootstrap_root_password):
            errors.append("BOOTSTRAP_ROOT_EMAIL and BOOTSTRAP_ROOT_PASSWORD must be configured together")
        if self.bootstrap_root_email and "@" not in self.bootstrap_root_email:
            errors.append("BOOTSTRAP_ROOT_EMAIL must be a valid email")
        if self.bootstrap_root_password:
            password = self.bootstrap_root_password
            if (
                len(password) < 14
                or _is_placeholder_secret(password)
                or not any(char.isalpha() for char in password)
                or not any(char.isdigit() for char in password)
                or not any(not char.isalnum() for char in password)
            ):
                errors.append(
                    "BOOTSTRAP_ROOT_PASSWORD must be at least 14 characters and include letters, numbers, and symbols"
                )
        if (
            not self.metrics_auth_token
            or len(self.metrics_auth_token) < 24
            or _is_placeholder_secret(self.metrics_auth_token)
        ):
            errors.append("METRICS_AUTH_TOKEN must be a non-placeholder secret of at least 24 characters")
        if (
            not self.alertmanager_webhook_token
            or len(self.alertmanager_webhook_token) < 24
            or _is_placeholder_secret(self.alertmanager_webhook_token)
        ):
            errors.append(
                "ALERTMANAGER_WEBHOOK_TOKEN must be a non-placeholder secret of at least 24 characters"
            )

        if self.oidc_enabled:
            issuer = urlsplit(self.oidc_issuer_url or "")
            redirect = urlsplit(self.oidc_redirect_uri or "")
            if issuer.scheme != "https" or not issuer.hostname or issuer.query or issuer.fragment:
                errors.append("OIDC_ISSUER_URL must be an explicit HTTPS issuer URL")
            if redirect.scheme != "https" or not redirect.hostname or not redirect.path:
                errors.append("OIDC_REDIRECT_URI must be an explicit HTTPS callback URL")
            if not self.oidc_client_id or len(self.oidc_client_id.strip()) < 3:
                errors.append("OIDC_CLIENT_ID must be configured when OIDC is enabled")
            if (
                not self.oidc_client_secret
                or len(self.oidc_client_secret) < 12
                or _is_placeholder_secret(self.oidc_client_secret)
            ):
                errors.append("OIDC_CLIENT_SECRET must be a non-placeholder secret of at least 12 characters")
            if "openid" not in self.oidc_scopes or "email" not in self.oidc_scopes:
                errors.append("OIDC_SCOPES must include openid and email")
            if self.oidc_state_ttl_seconds > 600:
                errors.append("OIDC_STATE_TTL_SECONDS must not exceed 600")
            if self.oidc_auto_provision and (
                not self.oidc_default_tenant_id or not self.oidc_allowed_email_domains
            ):
                errors.append(
                    "OIDC auto-provisioning requires OIDC_DEFAULT_TENANT_ID and OIDC_ALLOWED_EMAIL_DOMAINS"
                )
            if self.oidc_allow_email_linking and not self.oidc_allowed_email_domains:
                errors.append("OIDC email linking requires OIDC_ALLOWED_EMAIL_DOMAINS")

        if self.mfa_enforcement_enabled and (
            not self.mfa_encryption_key
            or len(self.mfa_encryption_key) < 32
            or _is_placeholder_secret(self.mfa_encryption_key)
        ):
            errors.append(
                "MFA_ENCRYPTION_KEY must be a non-placeholder secret of at least 32 characters "
                "when MFA enforcement is enabled"
            )
        if self.mfa_enforcement_enabled and not self.mfa_required_role_codes:
            errors.append("MFA_REQUIRED_ROLE_CODES must not be empty when MFA enforcement is enabled")
        if (
            not self.credential_encryption_key
            or len(self.credential_encryption_key) < 32
            or _is_placeholder_secret(self.credential_encryption_key)
        ):
            errors.append(
                "CREDENTIAL_ENCRYPTION_KEY must be a non-placeholder secret of at least 32 characters"
            )
        if (
            not self.configuration_package_signing_key
            or len(self.configuration_package_signing_key) < 32
            or _is_placeholder_secret(self.configuration_package_signing_key)
        ):
            errors.append(
                "CONFIGURATION_PACKAGE_SIGNING_KEY must be a non-placeholder secret "
                "of at least 32 characters"
            )
        if self.email_public_base_url:
            email_base = urlsplit(self.email_public_base_url)
            if (
                email_base.scheme != "https"
                or not email_base.hostname
                or email_base.query
                or email_base.fragment
            ):
                errors.append("EMAIL_PUBLIC_BASE_URL must be an explicit HTTPS base URL")
        if self.email_attachment_download_token_ttl_seconds > 300:
            errors.append(
                "EMAIL_ATTACHMENT_DOWNLOAD_TOKEN_TTL_SECONDS must not exceed 300"
            )
        if self.teams_public_base_url:
            teams_base = urlsplit(self.teams_public_base_url)
            if (
                teams_base.scheme != "https"
                or not teams_base.hostname
                or teams_base.username
                or teams_base.password
                or teams_base.query
                or teams_base.fragment
            ):
                errors.append("TEAMS_PUBLIC_BASE_URL must be an explicit HTTPS base URL")
        if not self.teams_webhook_allowed_hosts:
            errors.append("TEAMS_WEBHOOK_ALLOWED_HOSTS must not be empty")

        database = urlsplit(self.database_url)
        if not database.scheme.startswith("postgresql") or not database.hostname or not database.username:
            errors.append("DATABASE_URL must be a PostgreSQL URL with a hostname and username")
        if (
            not database.password
            or len(database.password) < 16
            or _is_placeholder_secret(database.password)
        ):
            errors.append("DATABASE_URL must include a non-placeholder password of at least 16 characters")

        redis = urlsplit(self.redis_url)
        if redis.scheme not in {"redis", "rediss"} or not redis.hostname:
            errors.append("REDIS_URL must be a Redis URL with a hostname")
        if not redis.password or len(redis.password) < 16 or _is_placeholder_secret(redis.password):
            errors.append("REDIS_URL must include a non-placeholder password of at least 16 characters")

        invalid_origins = []
        for origin in self.backend_cors_origins:
            parsed_origin = urlsplit(origin)
            if (
                origin == "*"
                or parsed_origin.scheme != "https"
                or not parsed_origin.hostname
                or parsed_origin.hostname in {"localhost", "127.0.0.1", "::1"}
                or bool(parsed_origin.username)
                or bool(parsed_origin.path)
                or bool(parsed_origin.query)
                or bool(parsed_origin.fragment)
            ):
                invalid_origins.append(origin)
        if not self.backend_cors_origins or invalid_origins:
            errors.append("BACKEND_CORS_ORIGINS must contain only explicit HTTPS production origins")

        cors_hosts = {
            str(urlsplit(origin).hostname).lower()
            for origin in self.backend_cors_origins
            if urlsplit(origin).hostname
        }
        if (
            not self.trusted_hosts
            or "*" in self.trusted_hosts
            or not cors_hosts.issubset(set(self.trusted_hosts))
        ):
            errors.append(
                "TRUSTED_HOSTS must explicitly include every production CORS hostname"
            )

        unsafe_forwarded_networks = []
        for raw_network in self.forwarded_allow_ips:
            if raw_network == "*":
                unsafe_forwarded_networks.append(raw_network)
                continue
            network = ipaddress.ip_network(raw_network, strict=False)
            if network.prefixlen == 0:
                unsafe_forwarded_networks.append(raw_network)
        if unsafe_forwarded_networks:
            errors.append(
                "FORWARDED_ALLOW_IPS must contain only bounded trusted proxy addresses"
            )

        configured_secrets = [
            self.jwt_secret_key,
            self.bootstrap_root_password,
            self.metrics_auth_token,
            self.alertmanager_webhook_token,
            self.jobs_alert_smtp_password,
            self.jobs_alert_slack_webhook_url,
            self.jobs_alert_pagerduty_routing_key,
            self.jobs_alert_webhook_url,
            self.oidc_client_secret if self.oidc_enabled else None,
            self.mfa_encryption_key if self.mfa_enforcement_enabled else None,
            self.credential_encryption_key,
            self.configuration_package_signing_key,
            database.password,
            redis.password,
        ]
        normalized_secrets = [secret for secret in configured_secrets if secret]
        if len(normalized_secrets) != len(set(normalized_secrets)):
            errors.append("production credentials must use distinct secrets")

        if errors:
            raise ValueError("Unsafe production configuration: " + "; ".join(errors))
        return self


@lru_cache
def get_settings() -> Settings:
    secrets_dir = os.getenv("SECRETS_DIR")
    if secrets_dir:
        return Settings(_secrets_dir=secrets_dir)
    return Settings()
