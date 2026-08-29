"""Add TOTP MFA enrollment and one-time login challenges.

Revision ID: 20260727_0028
Revises: 20260720_0027
"""

from alembic import op
import sqlalchemy as sa


revision = "20260727_0028"
down_revision = "20260720_0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("user_mfa"):
        op.create_table(
            "user_mfa",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("user_id", sa.String(length=36), nullable=False),
            sa.Column("secret_ciphertext", sa.Text(), nullable=False),
            sa.Column(
                "recovery_code_hashes_json",
                sa.Text(),
                nullable=False,
                server_default="[]",
            ),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("last_used_step", sa.BigInteger(), nullable=True),
            sa.Column("failed_attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
            sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("user_id"),
        )
        op.create_index("ix_user_mfa_user_id", "user_mfa", ["user_id"], unique=True)

    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("mfa_login_challenges"):
        op.create_table(
            "mfa_login_challenges",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("token_hash", sa.String(length=64), nullable=False),
            sa.Column("user_id", sa.String(length=36), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("token_hash"),
        )
        op.create_index(
            "ix_mfa_login_challenges_token_hash",
            "mfa_login_challenges",
            ["token_hash"],
            unique=True,
        )
        op.create_index(
            "ix_mfa_login_challenges_user_id",
            "mfa_login_challenges",
            ["user_id"],
        )
        op.create_index(
            "ix_mfa_login_challenges_expires_at",
            "mfa_login_challenges",
            ["expires_at"],
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("mfa_login_challenges"):
        op.drop_index(
            "ix_mfa_login_challenges_expires_at",
            table_name="mfa_login_challenges",
        )
        op.drop_index(
            "ix_mfa_login_challenges_user_id",
            table_name="mfa_login_challenges",
        )
        op.drop_index(
            "ix_mfa_login_challenges_token_hash",
            table_name="mfa_login_challenges",
        )
        op.drop_table("mfa_login_challenges")
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("user_mfa"):
        op.drop_index("ix_user_mfa_user_id", table_name="user_mfa")
        op.drop_table("user_mfa")
