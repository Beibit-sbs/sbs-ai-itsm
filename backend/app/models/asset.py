from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Asset(Base):
    __tablename__ = "assets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str | None] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True)
    ci_class_id: Mapped[str | None] = mapped_column(
        ForeignKey("ci_classes.id", ondelete="SET NULL"), nullable=True
    )
    ci_class_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("ci_class_versions.id", ondelete="SET NULL"), nullable=True
    )
    ci_class_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ci_class_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    ci_schema_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ci_schema_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ci_attributes_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    lifecycle_status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="ACTIVE"
    )
    owner_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    support_group: Mapped[str | None] = mapped_column(String(160), nullable=True)
    criticality: Mapped[str] = mapped_column(
        String(16), nullable=False, default="MEDIUM"
    )
    environment: Mapped[str] = mapped_column(
        String(24), nullable=False, default="OTHER"
    )
    ci_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    asset_tag: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    asset_type: Mapped[str] = mapped_column(String(120), nullable=False)
    type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    serial_number: Mapped[str | None] = mapped_column(String(120), nullable=True)
    inventory_number: Mapped[str | None] = mapped_column(String(80), nullable=True)
    source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_batch_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    original_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    manufacturer: Mapped[str | None] = mapped_column(String(200), nullable=True)
    model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    owner_name: Mapped[str] = mapped_column(String(200), nullable=False)
    assigned_to_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    assigned_to_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    department: Mapped[str | None] = mapped_column(String(200), nullable=True)
    location: Mapped[str] = mapped_column(String(200), nullable=False)
    building: Mapped[str | None] = mapped_column(String(120), nullable=True)
    floor: Mapped[str | None] = mapped_column(String(64), nullable=True)
    room: Mapped[str | None] = mapped_column(String(120), nullable=True)
    location_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    location_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    responsible_person_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    responsible_person_position: Mapped[str | None] = mapped_column(String(200), nullable=True)
    responsible_department: Mapped[str | None] = mapped_column(String(200), nullable=True)
    mol_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    mol_department: Mapped[str | None] = mapped_column(String(200), nullable=True)
    purchase_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    warranty_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    purchase_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    current_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    initial_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    depreciation_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    residual_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    residual_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    purchase_year: Mapped[int | None] = mapped_column(nullable=True)
    writeoff_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    writeoff_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    verification_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    imported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    moved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    disposed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_inventory_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    condition: Mapped[str] = mapped_column(String(32), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    tenant: Mapped["Tenant | None"] = relationship()
    histories: Mapped[list["AssetHistory"]] = relationship(back_populates="asset", cascade="all, delete-orphan")
