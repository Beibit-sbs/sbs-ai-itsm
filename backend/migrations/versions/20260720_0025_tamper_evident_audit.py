"""Add tamper-evident tenant-scoped audit hash chains.

Revision ID: 20260720_0025
Revises: 20260720_0024
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

from alembic import op
import sqlalchemy as sa


revision = "20260720_0025"
down_revision = "20260720_0024"
branch_labels = None
depends_on = None


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _event_hash(row: sa.RowMapping, scope: str, sequence: int, previous: str | None) -> str:
    canonical = json.dumps(
        {
            "id": row["id"],
            "chain_scope": scope,
            "sequence": sequence,
            "previous_hash": previous,
            "actor_email": row["actor_email"],
            "action": row["action"],
            "entity_type": row["entity_type"],
            "entity_id": row["entity_id"],
            "ip_address": row["ip_address"],
            "user_agent": row["user_agent"],
            "metadata": row["metadata"],
            "created_at": _timestamp(row["created_at"]),
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    existing_columns = {item["name"] for item in inspector.get_columns("audit_logs")}
    audit_chain_columns = {"chain_scope", "sequence", "previous_hash", "event_hash"}
    if audit_chain_columns.issubset(existing_columns) and inspector.has_table(
        "audit_chain_heads"
    ):
        return
    op.add_column("audit_logs", sa.Column("chain_scope", sa.String(length=64), nullable=True))
    op.add_column("audit_logs", sa.Column("sequence", sa.BigInteger(), nullable=True))
    op.add_column("audit_logs", sa.Column("previous_hash", sa.String(length=64), nullable=True))
    op.add_column("audit_logs", sa.Column("event_hash", sa.String(length=64), nullable=True))
    op.create_table(
        "audit_chain_heads",
        sa.Column("scope", sa.String(length=64), nullable=False),
        sa.Column("last_event_hash", sa.String(length=64), nullable=False),
        sa.Column("event_count", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("scope"),
    )

    audit_logs = sa.table(
        "audit_logs",
        sa.column("id", sa.String()),
        sa.column("tenant_id", sa.String()),
        sa.column("actor_email", sa.String()),
        sa.column("action", sa.String()),
        sa.column("entity_type", sa.String()),
        sa.column("entity_id", sa.String()),
        sa.column("ip_address", sa.String()),
        sa.column("user_agent", sa.Text()),
        sa.column("metadata", sa.Text()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("chain_scope", sa.String()),
        sa.column("sequence", sa.BigInteger()),
        sa.column("previous_hash", sa.String()),
        sa.column("event_hash", sa.String()),
    )
    heads = sa.table(
        "audit_chain_heads",
        sa.column("scope", sa.String()),
        sa.column("last_event_hash", sa.String()),
        sa.column("event_count", sa.BigInteger()),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    connection = op.get_bind()
    rows = connection.execute(
        sa.select(audit_logs).order_by(audit_logs.c.created_at.asc(), audit_logs.c.id.asc())
    ).mappings()
    state: dict[str, tuple[int, str | None, datetime]] = {}
    for row in rows:
        scope = str(row["tenant_id"] or "global")
        previous_sequence, previous_hash, _ = state.get(
            scope, (0, None, row["created_at"])
        )
        sequence = previous_sequence + 1
        event_hash = _event_hash(row, scope, sequence, previous_hash)
        connection.execute(
            audit_logs.update()
            .where(audit_logs.c.id == row["id"])
            .values(
                chain_scope=scope,
                sequence=sequence,
                previous_hash=previous_hash,
                event_hash=event_hash,
            )
        )
        state[scope] = (sequence, event_hash, row["created_at"])
    if state:
        connection.execute(
            heads.insert(),
            [
                {
                    "scope": scope,
                    "last_event_hash": event_hash,
                    "event_count": sequence,
                    "updated_at": updated_at,
                }
                for scope, (sequence, event_hash, updated_at) in state.items()
            ],
        )

    with op.batch_alter_table("audit_logs") as batch:
        batch.alter_column("chain_scope", existing_type=sa.String(length=64), nullable=False)
        batch.alter_column("sequence", existing_type=sa.BigInteger(), nullable=False)
        batch.alter_column("event_hash", existing_type=sa.String(length=64), nullable=False)
        batch.create_unique_constraint(
            "uq_audit_logs_chain_sequence", ["chain_scope", "sequence"]
        )
        batch.create_unique_constraint("uq_audit_logs_event_hash", ["event_hash"])
    op.create_index("ix_audit_logs_chain_scope", "audit_logs", ["chain_scope"])


def downgrade() -> None:
    op.drop_index("ix_audit_logs_chain_scope", table_name="audit_logs")
    with op.batch_alter_table("audit_logs") as batch:
        batch.drop_constraint("uq_audit_logs_event_hash", type_="unique")
        batch.drop_constraint("uq_audit_logs_chain_sequence", type_="unique")
        batch.drop_column("event_hash")
        batch.drop_column("previous_hash")
        batch.drop_column("sequence")
        batch.drop_column("chain_scope")
    op.drop_table("audit_chain_heads")
