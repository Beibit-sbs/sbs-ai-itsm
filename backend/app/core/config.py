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
    demo_mode: bool = True
    run_startup_ddl: bool = True
    demo_root_email: str = "root@sbs.local"
    demo_root_password: str = "Root!2026"
    demo_admin_email: str = "admin@sbs.local"
    demo_admin_password: str = "Sbs!2026"
    database_url: str = "postgresql+psycopg://sbs_itsm:sbs_itsm@localhost:5432/sbs_itsm"
    redis_url: str = "redis://localhost:6379/0"

    @field_validator("backend_cors_origins", mode="before")
    @classmethod
    def parse_cors(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
