from __future__ import annotations

from datetime import UTC, datetime
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.catalog_user_preference import CatalogUserPreference


def get_catalog_preference(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    catalog_item_id: str,
) -> CatalogUserPreference | None:
    return db.scalar(
        select(CatalogUserPreference).where(
            CatalogUserPreference.tenant_id == tenant_id,
            CatalogUserPreference.user_id == user_id,
            CatalogUserPreference.catalog_item_id == catalog_item_id,
        )
    )


def catalog_preferences_by_item(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    catalog_item_ids: list[str],
) -> dict[str, CatalogUserPreference]:
    if not catalog_item_ids:
        return {}
    preferences = db.scalars(
        select(CatalogUserPreference).where(
            CatalogUserPreference.tenant_id == tenant_id,
            CatalogUserPreference.user_id == user_id,
            CatalogUserPreference.catalog_item_id.in_(catalog_item_ids),
        )
    ).all()
    return {preference.catalog_item_id: preference for preference in preferences}


def touch_catalog_preference(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    catalog_item_id: str,
    viewed: bool = False,
    requested: bool = False,
    favorite: bool | None = None,
) -> CatalogUserPreference:
    preference = get_catalog_preference(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        catalog_item_id=catalog_item_id,
    )
    if preference is None:
        preference = CatalogUserPreference(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            user_id=user_id,
            catalog_item_id=catalog_item_id,
            is_favorite=False,
            view_count=0,
            request_count=0,
        )
        db.add(preference)

    now = datetime.now(UTC)
    if viewed:
        preference.view_count += 1
        preference.last_viewed_at = now
    if requested:
        preference.request_count += 1
        preference.last_requested_at = now
    if favorite is not None:
        preference.is_favorite = favorite
    preference.updated_at = now
    return preference
