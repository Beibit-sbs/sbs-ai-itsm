from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.system_setting import SystemSetting


def get_password_minimum_length(
    db: Session,
    tenant_id: str | None,
    *,
    default: int = 10,
) -> int:
    statement = select(SystemSetting).where(
        SystemSetting.key == "password_min_length"
    )
    candidate = (
        db.scalar(statement.where(SystemSetting.tenant_id == tenant_id))
        if tenant_id
        else None
    )
    if candidate is None:
        candidate = db.scalar(statement.where(SystemSetting.tenant_id.is_(None)))
    try:
        value = int(candidate.value) if candidate is not None else default
    except (TypeError, ValueError):
        return default
    return value if 8 <= value <= 256 else default
