from functools import lru_cache
import json
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "SBS AI ITSM"
    app_env: str = "development"
    app_version: str = "0.1.0"
    api_v1_prefix: str = "/api/v1"
    backend_cors_origins: list[str] | str = ["http://localhost:5173", "http://localhost:5174"]
    jwt_secret_key: str = "change-me-in-production"
    access_token_ttl_minutes: int = 30
    refresh_token_ttl_minutes: int = 10080
    demo_mode: bool = True
    run_startup_ddl: bool = True
    demo_root_email: str = "root@sbs.local"
    demo_root_password: str = "Root!2026"
    demo_admin_email: str = "admin@sbs.local"
    demo_admin_password: str = "Sbs!2026"
    database_url: str = "postgresql+psycopg://sbs_itsm:sbs_itsm@localhost:5432/sbs_itsm"
    redis_url: str = "redis://localhost:6379/0"
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
        mode="before",
    )
    @classmethod
    def parse_csv_lists(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

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

    @field_validator("access_token_ttl_minutes", "refresh_token_ttl_minutes")
    @classmethod
    def ttl_must_be_positive(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("Token TTL must be positive")
        return value

    @field_validator("jobs_executor_mode")
    @classmethod
    def jobs_executor_mode_must_be_supported(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"inline", "redis"}:
            raise ValueError("JOBS_EXECUTOR_MODE must be either 'inline' or 'redis'")
        return normalized

    @field_validator("jobs_retry_base_seconds", "jobs_retry_max_seconds")
    @classmethod
    def jobs_retry_values_must_be_positive(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("JOBS retry values must be positive")
        return value

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


@lru_cache
def get_settings() -> Settings:
    return Settings()
