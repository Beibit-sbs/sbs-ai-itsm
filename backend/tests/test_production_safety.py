import importlib
import json
import logging
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select

from app.core.config import Settings
from app.core.observability import JsonLogFormatter
from app.models.role import Role
from app.models.system_setting import SystemSetting
from app.models.tenant import Tenant
from app.models.ticket import Ticket
from app.models.ticket_category import TicketCategory
from app.models.ticket_priority import TicketPriority
from app.models.ticket_status import TicketStatus
from app.models.user import User
from app.ops.provision_smoke_user import provision_smoke_user


def _production_settings(**overrides) -> Settings:
    values = {
        "app_env": "production",
        "demo_mode": False,
        "run_startup_ddl": False,
        "jwt_secret_key": "jwt-secret-with-more-than-thirty-two-characters!",
        "bootstrap_root_email": "root@example.com",
        "bootstrap_root_password": "Unique-Root-Password-2026!",
        "metrics_auth_token": "metrics-token-with-32-characters!",
        "alertmanager_webhook_token": "alertmanager-token-with-32-characters!",
        "credential_encryption_key": "credential-encryption-key-with-more-than-32-characters!",
        "configuration_package_signing_key": "configuration-package-signing-key-with-more-than-32-characters!",
        "database_url": "postgresql+psycopg://user:database-password@postgres/db",
        "redis_url": "redis://:different-redis-password@redis:6379/0",
        "dashboard_realtime_transport": "redis",
        "backend_cors_origins": ["https://itsm.example.com"],
        "trusted_hosts": ["itsm.example.com", "backend"],
        "forwarded_allow_ips": ["172.30.250.10"],
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_safe_production_configuration_is_accepted() -> None:
    settings = _production_settings()
    assert settings.app_env == "production"


def test_safe_production_mfa_enforcement_is_accepted() -> None:
    settings = _production_settings(
        mfa_enforcement_enabled=True,
        mfa_encryption_key="unique-mfa-encryption-key-with-more-than-32-characters!",
    )
    assert settings.mfa_enforcement_enabled is True


def test_production_mfa_enforcement_requires_dedicated_secret() -> None:
    with pytest.raises(ValidationError, match="MFA_ENCRYPTION_KEY"):
        _production_settings(mfa_enforcement_enabled=True, mfa_encryption_key=None)


def test_production_configuration_allows_removing_completed_bootstrap_secret() -> None:
    settings = _production_settings(bootstrap_root_email=None, bootstrap_root_password=None)
    assert settings.bootstrap_root_password is None


def test_safe_production_oidc_configuration_is_accepted() -> None:
    settings = _production_settings(
        oidc_enabled=True,
        oidc_issuer_url="https://login.example.com/realms/company",
        oidc_client_id="sbs-ai-itsm",
        oidc_client_secret="unique-oidc-client-secret-2026",
        oidc_redirect_uri="https://itsm.example.com/api/v1/auth/sso/callback",
        oidc_allowed_email_domains=["example.com"],
    )
    assert settings.oidc_enabled is True
    assert settings.oidc_allowed_algorithms == ["RS256"]


def test_production_secrets_can_be_loaded_from_docker_secret_files(tmp_path, monkeypatch) -> None:
    secret_values = {
        "jwt_secret_key": "file-jwt-secret-with-more-than-thirty-two-characters!",
        "mfa_encryption_key": "file-mfa-secret-with-more-than-thirty-two-characters!",
        "metrics_auth_token": "file-metrics-token-with-more-than-24-characters!",
        "alertmanager_webhook_token": "file-alertmanager-token-with-more-than-24-characters!",
        "credential_encryption_key": "file-credential-secret-with-more-than-32-characters!",
        "configuration_package_signing_key": "file-configuration-package-key-with-more-than-32-characters!",
        "database_url": "postgresql+psycopg://user:file-database-password@postgres/db",
        "redis_url": "redis://:file-redis-password@redis:6379/0",
    }
    for name, value in secret_values.items():
        (tmp_path / name).write_text(value, encoding="utf-8")
        monkeypatch.delenv(name.upper(), raising=False)

    settings = Settings(
        _env_file=None,
        _secrets_dir=tmp_path,
        app_env="production",
        demo_mode=False,
        run_startup_ddl=False,
        dashboard_realtime_transport="redis",
        backend_cors_origins=["https://itsm.example.com"],
        trusted_hosts=["itsm.example.com", "backend"],
        forwarded_allow_ips=["172.30.250.10"],
        mfa_enforcement_enabled=True,
    )

    assert settings.jwt_secret_key == secret_values["jwt_secret_key"]
    assert settings.mfa_encryption_key == secret_values["mfa_encryption_key"]
    assert settings.metrics_auth_token == secret_values["metrics_auth_token"]
    assert settings.alertmanager_webhook_token == secret_values["alertmanager_webhook_token"]
    assert settings.credential_encryption_key == secret_values["credential_encryption_key"]
    assert (
        settings.configuration_package_signing_key
        == secret_values["configuration_package_signing_key"]
    )
    assert settings.database_url == secret_values["database_url"]
    assert settings.redis_url == secret_values["redis_url"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("demo_mode", True),
        ("run_startup_ddl", True),
        ("jwt_secret_key", "short"),
        ("bootstrap_root_password", "weak"),
        ("metrics_auth_token", "short"),
        ("alertmanager_webhook_token", "short"),
        ("database_url", "sqlite:///prod.db"),
        ("database_url", "postgresql+psycopg://user:replace_password@postgres/db"),
        ("database_url", "postgresql+psycopg://user:short@postgres/db"),
        ("redis_url", "redis://redis:6379/0"),
        ("redis_url", "redis://:GENERATE-A-PASSWORD@redis:6379/0"),
        ("redis_url", "redis://:short@redis:6379/0"),
        ("dashboard_realtime_transport", "local"),
        ("dashboard_socket_token_ttl_seconds", 301),
        ("email_attachment_download_token_ttl_seconds", 301),
        ("oidc_enabled", True),
        ("backend_cors_origins", ["http://localhost:5173"]),
        ("backend_cors_origins", ["http://itsm.example.com"]),
        ("backend_cors_origins", ["https://itsm.example.com/api"]),
        ("trusted_hosts", ["*"]),
        ("trusted_hosts", ["other.example.com", "backend"]),
        ("forwarded_allow_ips", ["*"]),
        ("forwarded_allow_ips", ["0.0.0.0/0"]),
    ],
)
def test_unsafe_production_configuration_is_rejected(field: str, value: object) -> None:
    with pytest.raises(ValidationError, match="Unsafe production configuration"):
        _production_settings(**{field: value})


def test_system_seed_never_resets_existing_root_password(db_session, monkeypatch) -> None:
    seed_service = importlib.import_module("app.services.seed")
    seed_settings = SimpleNamespace(
        bootstrap_root_email="root@production.example",
        bootstrap_root_password="Initial-Root-Password-2026!",
        demo_root_email="unused@example.com",
        demo_root_password="unused",
    )
    monkeypatch.setattr(seed_service, "get_settings", lambda: seed_settings)
    seed_service.seed_system_data(db_session)
    root = db_session.scalar(select(User).where(User.is_root.is_(True)))
    assert root is not None
    root.password_hash = "externally-rotated-password-hash"
    setting = db_session.scalar(select(SystemSetting))
    assert setting is not None
    setting.value = "operator-managed-value"
    db_session.commit()

    seed_service.seed_system_data(db_session)
    db_session.refresh(root)
    db_session.refresh(setting)
    assert root.password_hash == "externally-rotated-password-hash"
    assert setting.value == "operator-managed-value"


def test_system_seed_refuses_to_promote_existing_tenant_user(db_session, monkeypatch) -> None:
    seed_service = importlib.import_module("app.services.seed")
    existing_user = User(
        id="00000000-0000-0000-0000-000000000001",
        tenant_id=None,
        role_id=None,
        email="root@production.example",
        full_name="Existing user",
        password_hash="existing-password-hash",
        is_active=True,
        is_superuser=False,
        is_root=False,
    )
    db_session.add(existing_user)
    db_session.commit()
    seed_settings = SimpleNamespace(
        bootstrap_root_email=existing_user.email,
        bootstrap_root_password="Initial-Root-Password-2026!",
        demo_root_email="unused@example.com",
        demo_root_password="unused",
    )
    monkeypatch.setattr(seed_service, "get_settings", lambda: seed_settings)

    with pytest.raises(RuntimeError, match="refusing automatic privilege escalation"):
        seed_service.seed_system_data(db_session)

    db_session.refresh(existing_user)
    assert existing_user.is_root is False
    assert existing_user.is_superuser is False


def test_system_seed_adds_missing_standard_roles_to_existing_tenant(
    db_session,
    monkeypatch,
) -> None:
    seed_service = importlib.import_module("app.services.seed")
    tenant = Tenant(
        id="00000000-0000-0000-0000-000000000099",
        name="Restored tenant",
        slug="restored-tenant",
        status="active",
    )
    db_session.add(tenant)
    db_session.commit()
    seed_settings = SimpleNamespace(
        bootstrap_root_email="root@production.example",
        bootstrap_root_password="Initial-Root-Password-2026!",
        demo_root_email="unused@example.com",
        demo_root_password="unused",
    )
    monkeypatch.setattr(seed_service, "get_settings", lambda: seed_settings)

    seed_service.seed_system_data(db_session)
    first_ids = {
        role.code: role.id
        for role in db_session.scalars(
            select(Role).where(Role.tenant_id == tenant.id)
        ).all()
    }
    expected_codes = {
        code
        for code, definition in seed_service.ROLE_DEFS.items()
        if definition["scope"] == "tenant"
    }
    assert set(first_ids) == expected_codes

    seed_service.seed_system_data(db_session)
    second_ids = {
        role.code: role.id
        for role in db_session.scalars(
            select(Role).where(Role.tenant_id == tenant.id)
        ).all()
    }
    assert second_ids == first_ids


def test_system_seed_adds_mandatory_ticket_references_without_demo_fixtures(
    db_session,
    monkeypatch,
) -> None:
    seed_service = importlib.import_module("app.services.seed")
    service_desk = importlib.import_module("app.services.service_desk")
    custom_category = TicketCategory(
        id="00000000-0000-0000-0000-000000000077",
        code="SOFTWARE_INSTALL",
        name="Operator localized software label",
        description="Operator managed description",
        color="#123456",
        sort_order=77,
        is_active=False,
    )
    additional_category = TicketCategory(
        id="00000000-0000-0000-0000-000000000078",
        code="CUSTOM_BUSINESS_APP",
        name="Custom business application",
        description=None,
        color="#654321",
        sort_order=78,
        is_active=True,
    )
    db_session.add_all([custom_category, additional_category])
    db_session.commit()
    seed_settings = SimpleNamespace(
        bootstrap_root_email="root@production.example",
        bootstrap_root_password="Initial-Root-Password-2026!",
        demo_root_email="unused@example.com",
        demo_root_password="unused",
    )
    monkeypatch.setattr(seed_service, "get_settings", lambda: seed_settings)

    seed_service.seed_system_data(db_session)
    first_ids = {
        "categories": {item.code: item.id for item in db_session.scalars(select(TicketCategory)).all()},
        "priorities": {item.code: item.id for item in db_session.scalars(select(TicketPriority)).all()},
        "statuses": {item.code: item.id for item in db_session.scalars(select(TicketStatus)).all()},
    }

    db_session.refresh(custom_category)
    assert custom_category.name == "Operator localized software label"
    assert custom_category.color == "#123456"
    assert custom_category.sort_order == 77
    assert custom_category.is_active is False
    assert set(first_ids["categories"]) == {
        definition["code"] for definition in service_desk.CATEGORY_DEFS
    } | {"CUSTOM_BUSINESS_APP"}
    assert set(first_ids["priorities"]) == {
        definition["code"] for definition in service_desk.PRIORITY_DEFS
    }
    assert set(first_ids["statuses"]) == {
        definition["code"] for definition in service_desk.STATUS_DEFS
    }
    assert db_session.scalar(select(func.count(Ticket.id))) == 0
    assert db_session.scalar(select(Tenant).where(Tenant.slug == "demo-tenant")) is None
    assert service_desk.next_ticket_number(db_session) == "SD-1001"
    assert service_desk.next_ticket_number(db_session) == "SD-1002"

    seed_service.seed_system_data(db_session)
    second_ids = {
        "categories": {item.code: item.id for item in db_session.scalars(select(TicketCategory)).all()},
        "priorities": {item.code: item.id for item in db_session.scalars(select(TicketPriority)).all()},
        "statuses": {item.code: item.id for item in db_session.scalars(select(TicketStatus)).all()},
    }
    assert second_ids == first_ids
    assert db_session.scalar(select(func.count(Ticket.id))) == 0


def test_rehearsal_smoke_user_is_non_privileged_and_idempotent(db_session) -> None:
    tenant = Tenant(
        id="00000000-0000-0000-0000-000000000088",
        name="Smoke tenant",
        slug="smoke-tenant",
        status="active",
    )
    requester_role = Role(
        id="00000000-0000-0000-0000-000000000087",
        tenant_id=tenant.id,
        code="requester",
        name="Requester",
        scope="tenant",
        is_system=True,
    )
    db_session.add_all([tenant, requester_role])
    db_session.commit()
    password = "Unique-Rehearsal-Smoke-Password-2026!"
    first = provision_smoke_user(
        db_session,
        email="smoke.requester@rehearsal.local",
        password=password,
    )
    second = provision_smoke_user(
        db_session,
        email="SMOKE.REQUESTER@rehearsal.local",
        password=password,
    )

    assert second.id == first.id
    assert second.is_active is True
    assert second.is_superuser is False
    assert second.is_root is False
    assert second.role is not None
    assert second.role.code == "requester"


def test_rehearsal_operator_can_use_bounded_tenant_admin_role(db_session) -> None:
    tenant = Tenant(
        id="00000000-0000-0000-0000-000000000068",
        name="Performance tenant",
        slug="performance-tenant",
        status="active",
    )
    admin_role = Role(
        id="00000000-0000-0000-0000-000000000067",
        tenant_id=tenant.id,
        code="organization_admin",
        name="Organization Admin",
        scope="tenant",
        is_system=True,
    )
    db_session.add_all([tenant, admin_role])
    db_session.commit()

    user = provision_smoke_user(
        db_session,
        email="performance.operator@rehearsal.local",
        password="Unique-Rehearsal-Performance-Password-2026!",
        tenant_slug=tenant.slug,
        role_code="organization_admin",
    )

    assert user.tenant_id == tenant.id
    assert user.role is not None
    assert user.role.code == "organization_admin"
    assert user.is_superuser is False
    assert user.is_root is False


def test_json_logs_include_fields_and_redact_secrets() -> None:
    record = logging.LogRecord(
        name="app.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="connected to redis://user:password@redis:6379/0",
        args=(),
        exc_info=None,
    )
    record.job_id = "job-1"
    record.access_token = "must-not-leak"

    payload = json.loads(JsonLogFormatter().format(record))

    assert payload["job_id"] == "job-1"
    assert payload["access_token"] == "<redacted>"
    assert "password" not in payload["event"]
