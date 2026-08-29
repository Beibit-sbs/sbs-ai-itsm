from __future__ import annotations

from datetime import UTC, datetime
import uuid

import pytest
from cryptography.exceptions import InvalidTag
from sqlalchemy import select

from app.core.config import Settings
from app.models.asset import Asset
from app.models.asset_discovery import (
    AssetDiscoveryConnector,
    AssetDiscoveryRun,
    AssetDiscoveryStaleCandidate,
)
from app.models.asset_history import AssetHistory
from app.models.cmdb_reconciliation import CMDBSource, CMDBSourceIdentity
from app.models.tenant import Tenant
from app.models.user import User
from app.services.asset_discovery import (
    AssetDiscoveryError,
    DiscoveryFetchResult,
    _govern_discovery_records,
    _process_missing_identities,
    decide_stale_candidate,
    decrypt_discovery_credential,
    encrypt_discovery_credential,
    normalize_azure_resource,
    normalize_intune_device,
    normalize_lansweeper_asset,
    normalize_sccm_device,
    process_discovery_run,
    validate_discovery_configuration,
    validate_discovery_credential,
)


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        demo_mode=True,
        credential_encryption_key=(
            "asset-discovery-test-only-encryption-key-material-2026"
        ),
        asset_discovery_sccm_allowed_hosts=["sccm.test.internal"],
    )


def _tenant_user_source_connector(db_session, *, missing_threshold: int = 2):
    suffix = uuid.uuid4().hex[:8]
    now = datetime.now(UTC)
    tenant = Tenant(
        id=str(uuid.uuid4()),
        name="Asset Discovery Test",
        slug=f"asset-discovery-{suffix}",
        status="active",
    )
    user = User(
        id=str(uuid.uuid4()),
        tenant_id=tenant.id,
        email=f"asset-discovery-{suffix}@example.test",
        full_name="Asset Discovery Worker",
        identity_source="LOCAL",
        provisioning_state="LOCAL",
        password_hash="not-used",
        is_active=True,
        is_superuser=False,
        is_root=False,
    )
    source = CMDBSource(
        id=str(uuid.uuid4()),
        tenant_id=tenant.id,
        code=f"DISC_TEST_{suffix}".upper(),
        name="Discovery test source",
        source_type="DISCOVERY",
        priority=100,
        identification_rules_json='["serial_number","asset_tag","name"]',
        authoritative_fields_json=(
            '["name","lifecycle_status","verification_status","attributes.*"]'
        ),
        claim_unowned_fields=True,
        stale_after_hours=24,
        status="ACTIVE",
        version=1,
        created_by_id=user.id,
        updated_by_id=user.id,
    )
    connector = AssetDiscoveryConnector(
        id=str(uuid.uuid4()),
        tenant_id=tenant.id,
        cmdb_source_id=source.id,
        name="Intune production connector",
        provider="INTUNE",
        status="ACTIVE",
        auth_type="OAUTH_CLIENT_CREDENTIALS",
        base_url="https://graph.microsoft.com",
        credential_version=1,
        last_tested_credential_version=1,
        configuration_json="{}",
        schedule_minutes=60,
        auto_apply=False,
        missing_threshold_runs=missing_threshold,
        max_records=5_000,
        version=1,
        successful_runs=0,
        failed_runs=0,
        discovered_records=0,
        created_by_id=user.id,
        updated_by_id=user.id,
        next_run_at=now,
    )
    db_session.add_all([tenant, user, source, connector])
    db_session.flush()
    return tenant, user, source, connector


def _asset_identity(db_session, tenant: Tenant, source: CMDBSource):
    now = datetime.now(UTC)
    asset = Asset(
        id=str(uuid.uuid4()),
        tenant_id=tenant.id,
        asset_tag=f"DISC-{uuid.uuid4().hex[:10].upper()}",
        name="managed-device-01",
        asset_type="GENERIC_ASSET",
        type="GENERIC_ASSET",
        source=f"cmdb_source:{source.code}",
        lifecycle_status="ACTIVE",
        criticality="MEDIUM",
        environment="OTHER",
        ci_version=1,
        ci_attributes_json="{}",
        status="in_use",
        owner_name="Asset Discovery Worker",
        location="Location unknown",
        condition="good",
        verification_status="DISCOVERED",
    )
    identity = CMDBSourceIdentity(
        id=str(uuid.uuid4()),
        tenant_id=tenant.id,
        source_id=source.id,
        external_id="provider-device-01",
        asset_id=asset.id,
        first_seen_at=now,
        last_seen_at=now,
        discovery_state="ACTIVE",
        missing_run_count=0,
        updated_at=now,
    )
    db_session.add_all([asset, identity])
    db_session.flush()
    return asset, identity


def _run(
    db_session,
    connector: AssetDiscoveryConnector,
    user: User,
) -> AssetDiscoveryRun:
    now = datetime.now(UTC)
    run = AssetDiscoveryRun(
        id=str(uuid.uuid4()),
        tenant_id=connector.tenant_id,
        connector_id=connector.id,
        idempotency_key=str(uuid.uuid4()),
        trigger_type="MANUAL",
        status="QUEUED",
        attempts=0,
        max_attempts=4,
        next_attempt_at=now,
        requested_by_id=user.id,
        pages_fetched=0,
        records_fetched=0,
        complete_snapshot=False,
        reconciliation_run_ids_json="[]",
        created_count=0,
        updated_count=0,
        unchanged_count=0,
        ambiguous_count=0,
        invalid_count=0,
        missing_count=0,
        stale_count=0,
        result_json="{}",
    )
    db_session.add(run)
    db_session.flush()
    return run


def test_configuration_and_credentials_are_provider_bound_and_secret_safe() -> None:
    oauth = validate_discovery_credential(
        "INTUNE",
        "OAUTH_CLIENT_CREDENTIALS",
        {
            "directory_tenant_id": "tenant.example",
            "client_id": "client-id",
            "client_secret": "a-long-client-secret",
        },
    )
    assert oauth["client_secret"] == "a-long-client-secret"

    with pytest.raises(ValueError, match="not supported"):
        validate_discovery_credential(
            "INTUNE",
            "API_TOKEN",
            {"token": "token-value"},
        )
    with pytest.raises(ValueError, match="configuration.auth.token"):
        validate_discovery_configuration(
            "INTUNE",
            None,
            {"auth": {"token": "must-never-live-here"}},
            settings=_settings(),
        )
    with pytest.raises(ValueError, match="allow"):
        validate_discovery_configuration(
            "SCCM_ADMIN_SERVICE",
            "https://untrusted.internal",
            {"endpoint_path": "/AdminService/v1.0/Device"},
            settings=_settings(),
        )

    base_url, configuration = validate_discovery_configuration(
        "SCCM_ADMIN_SERVICE",
        "https://sccm.test.internal",
        {"endpoint_path": "/AdminService/v1.0/Device"},
        settings=_settings(),
    )
    assert base_url == "https://sccm.test.internal"
    assert configuration["endpoint_path"].startswith("/AdminService/")


def test_credential_ciphertext_is_bound_to_connector_and_tenant() -> None:
    connector = AssetDiscoveryConnector(
        id=str(uuid.uuid4()),
        tenant_id=str(uuid.uuid4()),
    )
    credential = {
        "directory_tenant_id": "tenant.example",
        "client_id": "client-id",
        "client_secret": "a-long-client-secret",
    }
    encrypted = encrypt_discovery_credential(
        connector,
        credential,
        settings=_settings(),
    )
    connector.credential_encrypted = encrypted
    assert "a-long-client-secret" not in encrypted
    assert decrypt_discovery_credential(
        connector,
        settings=_settings(),
    ) == credential

    connector.tenant_id = str(uuid.uuid4())
    with pytest.raises(InvalidTag):
        decrypt_discovery_credential(connector, settings=_settings())


def test_provider_normalizers_produce_governed_cmdb_records() -> None:
    records = (
        normalize_intune_device(
            {
                "id": "intune-1",
                "deviceName": "LAPTOP-01",
                "serialNumber": "INT-001",
                "complianceState": "compliant",
            }
        ),
        normalize_azure_resource(
            {
                "id": "/subscriptions/sub-1/resourceGroups/rg/providers/Test/vm-1",
                "name": "vm-1",
                "type": "Microsoft.Compute/virtualMachines",
                "location": "westeurope",
                "tags": {"environment": "production"},
            }
        ),
        normalize_sccm_device(
            {
                "MachineId": 42,
                "Name": "SCCM-01",
                "SerialNumber": "SCCM-001",
            }
        ),
        normalize_lansweeper_asset(
            {
                "key": "ls-1",
                "assetBasicInfo": {"name": "SWITCH-01", "type": "Switch"},
                "assetCustom": {"serialNumber": "LS-001"},
            }
        ),
    )
    assert {item["external_id"] for item in records} == {
        "intune-1",
        "/subscriptions/sub-1/resourceGroups/rg/providers/Test/vm-1",
        "42",
        "ls-1",
    }
    assert all(item["name"] for item in records)
    assert all(item["lifecycle_status"] == "ACTIVE" for item in records)
    assert all(isinstance(item["attributes"], dict) for item in records)


def test_only_complete_snapshots_advance_missing_state(
    db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant, user, source, connector = _tenant_user_source_connector(
        db_session,
        missing_threshold=1,
    )
    _, identity = _asset_identity(db_session, tenant, source)
    truncated_run = _run(db_session, connector, user)
    monkeypatch.setattr(
        "app.services.asset_discovery.fetch_discovery_records",
        lambda *_args, **_kwargs: DiscoveryFetchResult(
            records=[],
            pages=1,
            complete_snapshot=False,
            cursor="next-page",
        ),
    )

    process_discovery_run(db_session, truncated_run, settings=_settings())
    assert truncated_run.status == "COMPLETED"
    assert identity.missing_run_count == 0
    assert db_session.scalar(select(AssetDiscoveryStaleCandidate.id)) is None

    complete_run = _run(db_session, connector, user)
    monkeypatch.setattr(
        "app.services.asset_discovery.fetch_discovery_records",
        lambda *_args, **_kwargs: DiscoveryFetchResult(
            records=[],
            pages=1,
            complete_snapshot=True,
        ),
    )
    process_discovery_run(db_session, complete_run, settings=_settings())
    candidate = db_session.scalar(
        select(AssetDiscoveryStaleCandidate).where(
            AssetDiscoveryStaleCandidate.source_identity_id == identity.id
        )
    )
    assert complete_run.missing_count == 1
    assert complete_run.stale_count == 1
    assert identity.discovery_state == "STALE"
    assert candidate is not None
    assert candidate.status == "OPEN"


def test_stale_retirement_is_audited_sticky_and_recoverable(db_session) -> None:
    tenant, user, source, connector = _tenant_user_source_connector(
        db_session,
        missing_threshold=1,
    )
    asset, identity = _asset_identity(db_session, tenant, source)
    missing_run = _run(db_session, connector, user)
    _process_missing_identities(db_session, connector, missing_run, set())
    candidate = db_session.scalar(
        select(AssetDiscoveryStaleCandidate).where(
            AssetDiscoveryStaleCandidate.source_identity_id == identity.id
        )
    )
    assert candidate is not None

    decide_stale_candidate(
        db_session,
        candidate,
        decision="RETIRE",
        expected_version=candidate.version,
        actor_id=user.id,
        reason="Confirmed absent in provider and decommissioned by asset owner",
    )
    assert asset.lifecycle_status == "RETIRED"
    assert asset.status == "inactive"
    history = db_session.scalar(
        select(AssetHistory).where(
            AssetHistory.asset_id == asset.id,
            AssetHistory.action == "asset_discovery_stale_retired",
        )
    )
    assert history is not None

    governed = _govern_discovery_records(
        db_session,
        connector,
        [
            {
                "external_id": identity.external_id,
                "name": asset.name,
                "lifecycle_status": "ACTIVE",
                "verification_status": "DISCOVERED",
            }
        ],
    )
    assert "lifecycle_status" not in governed[0]
    assert "verification_status" not in governed[0]

    with pytest.raises(AssetDiscoveryError, match="duplicate external_id"):
        _govern_discovery_records(
            db_session,
            connector,
            [
                {"external_id": "duplicate", "name": "one"},
                {"external_id": "duplicate", "name": "two"},
            ],
        )


def test_dismissed_candidate_recovers_and_can_open_on_a_new_missing_episode(
    db_session,
) -> None:
    tenant, user, source, connector = _tenant_user_source_connector(
        db_session,
        missing_threshold=1,
    )
    _, identity = _asset_identity(db_session, tenant, source)
    first_run = _run(db_session, connector, user)
    _process_missing_identities(db_session, connector, first_run, set())
    candidate = db_session.scalar(
        select(AssetDiscoveryStaleCandidate).where(
            AssetDiscoveryStaleCandidate.source_identity_id == identity.id
        )
    )
    assert candidate is not None
    decide_stale_candidate(
        db_session,
        candidate,
        decision="DISMISS",
        expected_version=candidate.version,
        actor_id=user.id,
        reason="Temporary provider visibility issue confirmed",
    )

    recovered_run = _run(db_session, connector, user)
    _process_missing_identities(
        db_session,
        connector,
        recovered_run,
        {identity.external_id},
    )
    assert candidate.status == "RECOVERED"
    assert identity.missing_run_count == 0

    new_missing_run = _run(db_session, connector, user)
    _process_missing_identities(db_session, connector, new_missing_run, set())
    assert candidate.status == "OPEN"
    assert identity.missing_run_count == 1
