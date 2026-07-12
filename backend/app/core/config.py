from functools import lru_cache
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


@lru_cache
def get_settings() -> Settings:
    return Settings()
