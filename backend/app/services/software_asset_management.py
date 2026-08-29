from __future__ import annotations

import hashlib
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.asset import Asset
from app.models.software_asset import (
    SoftwareInstallation,
    SoftwareLicense,
    SoftwareProduct,
)


def software_catalog_key(
    *, name: str, publisher: str, version: str, edition: str | None
) -> str:
    parts = (name, publisher, version, edition or "")
    normalized = "\x1f".join(" ".join(part.strip().lower().split()) for part in parts)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _aware(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)


def license_is_usable(item: SoftwareLicense, *, now: datetime) -> bool:
    starts_at = _aware(item.starts_at)
    expires_at = _aware(item.expires_at)
    return (
        item.status == "ACTIVE"
        and (starts_at is None or starts_at <= now)
        and (expires_at is None or expires_at > now)
    )


def reconcile_expired_licenses(
    db: Session, *, tenant_id: str, now: datetime | None = None
) -> list[str]:
    effective_now = now or datetime.now(UTC)
    rows = db.scalars(
        select(SoftwareLicense).where(
            SoftwareLicense.tenant_id == tenant_id,
            SoftwareLicense.status == "ACTIVE",
            SoftwareLicense.expires_at.is_not(None),
        )
    ).all()
    changed: list[str] = []
    for item in rows:
        expires_at = _aware(item.expires_at)
        if expires_at is not None and expires_at <= effective_now:
            item.status = "EXPIRED"
            item.version_number += 1
            changed.append(item.id)
    return changed


def build_compliance_positions(
    db: Session,
    *,
    tenant_id: str,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    effective_now = now or datetime.now(UTC)
    products = db.scalars(
        select(SoftwareProduct)
        .where(SoftwareProduct.tenant_id == tenant_id)
        .order_by(SoftwareProduct.name.asc(), SoftwareProduct.version.asc())
    ).all()
    licenses = db.scalars(
        select(SoftwareLicense).where(SoftwareLicense.tenant_id == tenant_id)
    ).all()
    installations = db.scalars(
        select(SoftwareInstallation).where(
            SoftwareInstallation.tenant_id == tenant_id,
            SoftwareInstallation.status == "ACTIVE",
        )
    ).all()
    licenses_by_product: dict[str, list[SoftwareLicense]] = defaultdict(list)
    installs_by_product: dict[str, list[SoftwareInstallation]] = defaultdict(list)
    for item in licenses:
        licenses_by_product[item.product_id].append(item)
    for item in installations:
        installs_by_product[item.product_id].append(item)

    positions: list[dict[str, Any]] = []
    for product in products:
        product_licenses = licenses_by_product[product.id]
        product_installations = installs_by_product[product.id]
        usable = [item for item in product_licenses if license_is_usable(item, now=effective_now)]
        purchased = sum(item.purchased_quantity for item in usable)
        detected = len(product_installations)
        assigned = sum(1 for item in product_installations if item.assigned_user_id)
        unauthorized = sum(
            1
            for item in product_installations
            if item.authorization_status == "UNAUTHORIZED" or product.is_prohibited
        )
        all_expired = bool(product_licenses) and not usable and all(
            item.status in {"EXPIRED", "RETIRED", "SUSPENDED"}
            or (_aware(item.expires_at) is not None and _aware(item.expires_at) <= effective_now)
            for item in product_licenses
        )
        if product.is_prohibited and detected:
            compliance_state = "PROHIBITED"
        elif unauthorized:
            compliance_state = "UNAUTHORIZED"
        elif detected and all_expired:
            compliance_state = "EXPIRED"
        elif detected > purchased:
            compliance_state = "UNLICENSED" if purchased == 0 else "OVER_DEPLOYED"
        elif purchased > detected:
            compliance_state = "UNDERUTILIZED"
        else:
            compliance_state = "COMPLIANT"

        costs: dict[str, Decimal] = defaultdict(lambda: Decimal("0.00"))
        unit_costs: dict[str, list[Decimal]] = defaultdict(list)
        for item in usable:
            costs[item.currency] += Decimal(item.unit_cost) * item.purchased_quantity
            unit_costs[item.currency].append(Decimal(item.unit_cost))
        cost_at_risk: dict[str, Decimal] = {}
        shortfall = max(0, detected - purchased)
        for currency, values in unit_costs.items():
            average = sum(values, Decimal("0.00")) / max(len(values), 1)
            cost_at_risk[currency] = average * shortfall
        positions.append(
            {
                "product_id": product.id,
                "name": product.name,
                "publisher": product.publisher,
                "version": product.version,
                "edition": product.edition,
                "status": product.status,
                "is_prohibited": product.is_prohibited,
                "purchased_quantity": purchased,
                "assigned_quantity": assigned,
                "detected_quantity": detected,
                "unauthorized_quantity": unauthorized,
                "available_quantity": max(0, purchased - detected),
                "shortfall_quantity": shortfall,
                "compliance_state": compliance_state,
                "purchase_cost_by_currency": {
                    key: float(value) for key, value in sorted(costs.items())
                },
                "cost_at_risk_by_currency": {
                    key: float(value) for key, value in sorted(cost_at_risk.items())
                },
            }
        )
    severity = {
        "PROHIBITED": 0,
        "UNAUTHORIZED": 1,
        "EXPIRED": 2,
        "UNLICENSED": 3,
        "OVER_DEPLOYED": 4,
        "UNDERUTILIZED": 5,
        "COMPLIANT": 6,
    }
    return sorted(
        positions,
        key=lambda item: (severity[item["compliance_state"]], item["name"].lower()),
    )


def build_sam_dashboard(
    db: Session,
    *,
    tenant_id: str,
    renewal_days: int = 90,
    now: datetime | None = None,
) -> dict[str, Any]:
    effective_now = now or datetime.now(UTC)
    positions = build_compliance_positions(db, tenant_id=tenant_id, now=effective_now)
    licenses = db.scalars(
        select(SoftwareLicense).where(SoftwareLicense.tenant_id == tenant_id)
    ).all()
    products = {
        item.id: item
        for item in db.scalars(
            select(SoftwareProduct).where(SoftwareProduct.tenant_id == tenant_id)
        ).all()
    }
    assets = {
        item.id: item
        for item in db.scalars(select(Asset).where(Asset.tenant_id == tenant_id)).all()
    }
    installations = db.scalars(
        select(SoftwareInstallation).where(
            SoftwareInstallation.tenant_id == tenant_id,
            SoftwareInstallation.status == "ACTIVE",
        )
    ).all()
    renewal_cutoff = effective_now + timedelta(days=renewal_days)
    renewals: list[dict[str, Any]] = []
    for item in licenses:
        if item.status not in {"ACTIVE", "EXPIRED"}:
            continue
        due_at = _aware(item.renewal_at) or _aware(item.expires_at)
        if due_at is None or due_at > renewal_cutoff:
            continue
        product = products.get(item.product_id)
        renewals.append(
            {
                "license_id": item.id,
                "license_reference": item.license_reference,
                "product_id": item.product_id,
                "product_name": product.name if product else "Unknown product",
                "due_at": due_at,
                "status": "OVERDUE" if due_at <= effective_now else "UPCOMING",
                "auto_renew": item.auto_renew,
                "purchased_quantity": item.purchased_quantity,
                "unit_cost": float(item.unit_cost),
                "currency": item.currency,
            }
        )
    renewals.sort(key=lambda item: item["due_at"])
    unauthorized_installations = []
    for item in installations:
        product = products.get(item.product_id)
        if item.authorization_status != "UNAUTHORIZED" and not (
            product and product.is_prohibited
        ):
            continue
        asset = assets.get(item.asset_id)
        unauthorized_installations.append(
            {
                "installation_id": item.id,
                "product_id": item.product_id,
                "product_name": product.name if product else "Unknown product",
                "asset_id": item.asset_id,
                "asset_tag": asset.asset_tag if asset else None,
                "asset_name": asset.name if asset else None,
                "authorization_status": item.authorization_status,
                "prohibited": bool(product and product.is_prohibited),
                "last_seen_at": item.last_seen_at,
            }
        )
    cost_by_currency: dict[str, Decimal] = defaultdict(lambda: Decimal("0.00"))
    risk_by_currency: dict[str, Decimal] = defaultdict(lambda: Decimal("0.00"))
    for position in positions:
        for currency, amount in position["purchase_cost_by_currency"].items():
            cost_by_currency[currency] += Decimal(str(amount))
        for currency, amount in position["cost_at_risk_by_currency"].items():
            risk_by_currency[currency] += Decimal(str(amount))
    violating_states = {"PROHIBITED", "UNAUTHORIZED", "EXPIRED", "UNLICENSED", "OVER_DEPLOYED"}
    return {
        "tenant_id": tenant_id,
        "generated_at": effective_now,
        "summary": {
            "products": len(products),
            "licenses": len(licenses),
            "active_installations": len(installations),
            "compliant_products": sum(
                1 for item in positions if item["compliance_state"] in {"COMPLIANT", "UNDERUTILIZED"}
            ),
            "noncompliant_products": sum(
                1 for item in positions if item["compliance_state"] in violating_states
            ),
            "unauthorized_installations": len(unauthorized_installations),
            "upcoming_renewals": len(renewals),
            "purchase_cost_by_currency": {
                key: float(value) for key, value in sorted(cost_by_currency.items())
            },
            "cost_at_risk_by_currency": {
                key: float(value) for key, value in sorted(risk_by_currency.items())
            },
        },
        "positions": positions,
        "renewals": renewals,
        "unauthorized_installations": unauthorized_installations,
    }
