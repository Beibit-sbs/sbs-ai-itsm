from __future__ import annotations

import argparse
import os
import sys
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import hash_password, validate_password_strength
from app.db.session import SessionLocal
from app.models.role import Role
from app.models.tenant import Tenant
from app.models.user import User
from app.services.password_policy import get_password_minimum_length


def provision_smoke_user(
    db: Session,
    *,
    email: str,
    password: str,
    tenant_slug: str | None = None,
    role_code: str = "requester",
) -> User:
    normalized_email = email.strip().lower()
    if "@" not in normalized_email:
        raise RuntimeError("smoke user email is invalid")

    allowed_role_codes = {
        "requester",
        "it_agent",
        "it_manager",
        "organization_admin",
    }
    if role_code not in allowed_role_codes:
        raise RuntimeError("unsupported rehearsal role")

    role_query = (
        select(Role)
        .join(Tenant, Tenant.id == Role.tenant_id)
        .where(
            Role.code == role_code,
            Role.is_system.is_(True),
            Tenant.status == "active",
        )
        .order_by(Tenant.id)
    )
    if tenant_slug:
        role_query = role_query.where(Tenant.slug == tenant_slug)
    role = db.scalar(role_query)
    if role is None or role.tenant_id is None:
        raise RuntimeError(
            f"no active tenant with a system {role_code} role is available"
        )

    password_error = validate_password_strength(
        password,
        minimum_length=get_password_minimum_length(db, role.tenant_id),
        demo_mode=get_settings().demo_mode,
    )
    if password_error:
        raise RuntimeError(password_error)

    password_hash = hash_password(password)
    user = db.scalar(select(User).where(User.email == normalized_email))
    if user is not None and (user.is_root or user.is_superuser):
        raise RuntimeError("refusing to repurpose a privileged user as a smoke user")
    if user is None:
        user = User(
            id=str(uuid.uuid4()),
            email=normalized_email,
            full_name="Production Rehearsal Operator",
            password_hash=password_hash,
        )
        db.add(user)
    user.tenant_id = role.tenant_id
    user.role_id = role.id
    user.full_name = (
        "Production Smoke Requester"
        if role_code == "requester"
        else "Production Rehearsal Operator"
    )
    user.identity_source = "LOCAL"
    user.provisioning_state = "LOCAL"
    user.password_hash = password_hash
    user.must_change_password = False
    user.is_active = True
    user.is_superuser = False
    user.is_root = False
    user.roles = [role]
    db.commit()
    db.refresh(user)
    return user


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--email", required=True)
    parser.add_argument("--tenant-slug", default=None)
    parser.add_argument(
        "--role-code",
        choices=("requester", "it_agent", "it_manager", "organization_admin"),
        default="requester",
    )
    parser.add_argument("--confirm-rehearsal", action="store_true")
    args = parser.parse_args()

    if not args.confirm_rehearsal or os.environ.get(
        "REHEARSAL_SMOKE_PROVISIONING_ENABLED",
        "",
    ).lower() != "true":
        print(
            "[FAIL] rehearsal confirmation and environment opt-in are required",
            file=sys.stderr,
        )
        return 1
    password = sys.stdin.readline().rstrip("\r\n")
    if not password:
        print("[FAIL] smoke password is required on stdin", file=sys.stderr)
        return 1

    db = SessionLocal()
    try:
        user = provision_smoke_user(
            db,
            email=args.email,
            password=password,
            tenant_slug=args.tenant_slug,
            role_code=args.role_code,
        )
    except RuntimeError as exc:
        db.rollback()
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 1
    finally:
        db.close()
    print(f"Provisioned rehearsal identity: {user.email} ({args.role_code})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
