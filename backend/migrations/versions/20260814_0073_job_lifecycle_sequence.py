"""Add deterministic per-job lifecycle event sequence.

Revision ID: 20260814_0073
Revises: 20260729_0072
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260814_0073"
down_revision: str | None = "20260729_0072"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {str(column["name"]): column for column in inspector.get_columns("job_lifecycle_events")}
    if "sequence" not in columns:
        with op.batch_alter_table("job_lifecycle_events") as batch_op:
            batch_op.add_column(sa.Column("sequence", sa.Integer(), nullable=True))

    rows = bind.execute(
        sa.text(
            """
            SELECT id, job_id
            FROM job_lifecycle_events
            ORDER BY job_id, created_at, id
            """
        )
    ).mappings()
    next_sequence: dict[str, int] = {}
    for row in rows:
        job_id = str(row["job_id"])
        sequence = next_sequence.get(job_id, 0) + 1
        next_sequence[job_id] = sequence
        bind.execute(
            sa.text("UPDATE job_lifecycle_events SET sequence = :sequence WHERE id = :id"),
            {"sequence": sequence, "id": str(row["id"])},
        )

    inspector = sa.inspect(bind)
    columns = {str(column["name"]): column for column in inspector.get_columns("job_lifecycle_events")}
    constraint_names = {
        str(item.get("name")) for item in inspector.get_unique_constraints("job_lifecycle_events")
    }
    index_names = {str(item.get("name")) for item in inspector.get_indexes("job_lifecycle_events")}
    sequence_nullable = bool(columns["sequence"].get("nullable", True))
    unique_missing = "uq_job_lifecycle_events_job_sequence" not in constraint_names and (
        "uq_job_lifecycle_events_job_sequence" not in index_names
    )
    index_missing = "ix_job_lifecycle_events_job_sequence" not in index_names

    if sequence_nullable or unique_missing or index_missing:
        with op.batch_alter_table("job_lifecycle_events") as batch_op:
            if sequence_nullable:
                batch_op.alter_column("sequence", existing_type=sa.Integer(), nullable=False)
            if unique_missing:
                batch_op.create_unique_constraint(
                    "uq_job_lifecycle_events_job_sequence",
                    ["job_id", "sequence"],
                )
            if index_missing:
                batch_op.create_index(
                    "ix_job_lifecycle_events_job_sequence",
                    ["job_id", "sequence"],
                    unique=False,
                )


def downgrade() -> None:
    with op.batch_alter_table("job_lifecycle_events") as batch_op:
        batch_op.drop_index("ix_job_lifecycle_events_job_sequence")
        batch_op.drop_constraint("uq_job_lifecycle_events_job_sequence", type_="unique")
        batch_op.drop_column("sequence")
