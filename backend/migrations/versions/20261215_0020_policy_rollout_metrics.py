"""stage 032: add metrics history and snapshot tables

Revision ID: 20261215_0020_policy_rollout_metrics
Revises: 20261113_0019_policy_canary_rollouts
Create Date: 2026-07-13

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20261215_0020_policy_rollout_metrics'
down_revision = '20261113_0019_policy_canary_rollouts'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create policy_rollout_metrics_history table
    op.create_table(
        'policy_rollout_metrics_history',
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('rollout_id', sa.String(36), nullable=False),
        sa.Column('collected_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('error_rate', sa.Float(), nullable=True),
        sa.Column('latency_p99_ms', sa.Float(), nullable=True),
        sa.Column('throughput_eps', sa.Float(), nullable=True),
        sa.Column('cpu_percent', sa.Float(), nullable=True),
        sa.Column('memory_percent', sa.Float(), nullable=True),
        sa.Column('request_count', sa.Integer(), nullable=True),
        sa.Column('source', sa.String(50), nullable=True),
        sa.Column('collection_duration_ms', sa.Integer(), nullable=True),
        sa.Column('raw_data', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['rollout_id'], ['policy_canary_rollout.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_metrics_history_rollout_collected', 'policy_rollout_metrics_history', ['rollout_id', 'collected_at'])
    op.create_index('ix_metrics_history_collected_desc', 'policy_rollout_metrics_history', ['collected_at'])
    op.create_index('ix_policy_rollout_metrics_history_rollout_id', 'policy_rollout_metrics_history', ['rollout_id'])
    op.create_index('ix_policy_rollout_metrics_history_collected_at', 'policy_rollout_metrics_history', ['collected_at'])
    
    # Create policy_rollout_metrics_snapshot table
    op.create_table(
        'policy_rollout_metrics_snapshot',
        sa.Column('rollout_id', sa.String(36), nullable=False),
        sa.Column('error_rate', sa.Float(), nullable=True),
        sa.Column('latency_p99_ms', sa.Float(), nullable=True),
        sa.Column('throughput_eps', sa.Float(), nullable=True),
        sa.Column('cpu_percent', sa.Float(), nullable=True),
        sa.Column('memory_percent', sa.Float(), nullable=True),
        sa.Column('request_count', sa.Integer(), nullable=True),
        sa.Column('snapshot_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('error_rate_baseline', sa.Float(), nullable=True),
        sa.Column('error_rate_previous', sa.Float(), nullable=True),
        sa.Column('error_rate_increasing', sa.Boolean(), nullable=True),
        sa.Column('error_rate_change_percent', sa.Float(), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['rollout_id'], ['policy_canary_rollout.id'], ),
        sa.PrimaryKeyConstraint('rollout_id')
    )


def downgrade() -> None:
    op.drop_table('policy_rollout_metrics_snapshot')
    op.drop_table('policy_rollout_metrics_history')
