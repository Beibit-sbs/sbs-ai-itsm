"""Guarantee a published order form for every published catalog item.

Revision ID: 20260729_0034
Revises: 20260729_0033
"""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
import uuid

from alembic import op
import sqlalchemy as sa


revision = "20260729_0034"
down_revision = "20260729_0033"
branch_labels = None
depends_on = None


def _canonical(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "catalog_form_versions" not in set(inspector.get_table_names()):
        return

    form_schema = {
        "title": "Данные запроса",
        "introduction": "Заполните сведения, необходимые для выполнения услуги.",
        "sections": [
            {
                "id": "request_details",
                "title": "Детали запроса",
                "description": "",
                "order": 10,
            }
        ],
        "fields": [],
    }
    attachment_rules = {
        "enabled": False,
        "required": False,
        "max_files": 3,
        "max_size_mb": 10,
        "allowed_extensions": ["pdf", "png", "jpg", "docx", "xlsx"],
    }
    schema_json = _canonical(form_schema)
    attachment_rules_json = _canonical(attachment_rules)
    digest = hashlib.sha256(
        _canonical(
            {
                "schema": form_schema,
                "attachment_rules": attachment_rules,
            }
        ).encode("utf-8")
    ).hexdigest()
    items = bind.execute(
        sa.text(
            """
            SELECT item.id, item.tenant_id, item.owner_user_id
            FROM catalog_items AS item
            WHERE item.lifecycle_status = 'PUBLISHED'
              AND NOT EXISTS (
                SELECT 1
                FROM catalog_form_versions AS form
                WHERE form.catalog_item_id = item.id
                  AND form.status = 'PUBLISHED'
              )
            """
        )
    ).mappings()
    now = datetime.now(UTC)
    for item in items:
        next_version = bind.execute(
            sa.text(
                """
                SELECT COALESCE(MAX(version), 0) + 1
                FROM catalog_form_versions
                WHERE catalog_item_id = :catalog_item_id
                """
            ),
            {"catalog_item_id": item["id"]},
        ).scalar_one()
        bind.execute(
            sa.text(
                """
                INSERT INTO catalog_form_versions (
                    id, tenant_id, catalog_item_id, version, revision, status,
                    schema_json, attachment_rules_json, schema_hash,
                    created_by_id, updated_by_id, published_by_id, published_at,
                    retired_at, created_at, updated_at
                ) VALUES (
                    :id, :tenant_id, :catalog_item_id, :version, 1, 'PUBLISHED',
                    :schema_json, :attachment_rules_json, :schema_hash,
                    :actor_id, :actor_id, :actor_id, :published_at,
                    NULL, :created_at, :updated_at
                )
                """
            ),
            {
                "id": str(uuid.uuid4()),
                "tenant_id": item["tenant_id"],
                "catalog_item_id": item["id"],
                "version": next_version,
                "schema_json": schema_json,
                "attachment_rules_json": attachment_rules_json,
                "schema_hash": digest,
                "actor_id": item["owner_user_id"],
                "published_at": now,
                "created_at": now,
                "updated_at": now,
            },
        )


def downgrade() -> None:
    # This revision backfills business data only. Retaining published form
    # snapshots is safer because requests may already reference them.
    pass
