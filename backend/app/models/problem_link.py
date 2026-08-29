from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ProblemTicketLink(Base):
    __tablename__ = "problem_ticket_links"
    __table_args__ = (
        UniqueConstraint("problem_id", "ticket_id", name="uq_problem_ticket_links_pair"),
        Index("ix_problem_ticket_links_problem_id", "problem_id"),
        Index("ix_problem_ticket_links_ticket_id", "ticket_id"),
        Index("ix_problem_ticket_links_tenant_id", "tenant_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    problem_id: Mapped[str] = mapped_column(
        ForeignKey("problems.id", ondelete="CASCADE"), nullable=False
    )
    ticket_id: Mapped[str] = mapped_column(
        ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ProblemAssetLink(Base):
    __tablename__ = "problem_asset_links"
    __table_args__ = (
        UniqueConstraint("problem_id", "asset_id", name="uq_problem_asset_links_pair"),
        Index("ix_problem_asset_links_problem_id", "problem_id"),
        Index("ix_problem_asset_links_asset_id", "asset_id"),
        Index("ix_problem_asset_links_tenant_id", "tenant_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    problem_id: Mapped[str] = mapped_column(
        ForeignKey("problems.id", ondelete="CASCADE"), nullable=False
    )
    asset_id: Mapped[str] = mapped_column(
        ForeignKey("assets.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ProblemChangeLink(Base):
    __tablename__ = "problem_change_links"
    __table_args__ = (
        UniqueConstraint("problem_id", "change_id", name="uq_problem_change_links_pair"),
        Index("ix_problem_change_links_problem_id", "problem_id"),
        Index("ix_problem_change_links_change_id", "change_id"),
        Index("ix_problem_change_links_tenant_id", "tenant_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    problem_id: Mapped[str] = mapped_column(
        ForeignKey("problems.id", ondelete="CASCADE"), nullable=False
    )
    change_id: Mapped[str] = mapped_column(
        ForeignKey("change_requests.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
