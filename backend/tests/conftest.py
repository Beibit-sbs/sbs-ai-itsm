from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from fastapi import Depends, HTTPException, Request, status
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session


backend_root = Path(__file__).resolve().parents[1]
if str(backend_root) not in sys.path:
    sys.path.insert(0, str(backend_root))


# Legacy compatibility for stage_026/stage_027 tests that import symbols directly
legacy_db_path = backend_root / "tests" / ".legacy_policy_tests.db"
os.environ.setdefault("DATABASE_URL", f"sqlite:///{legacy_db_path}")
os.environ.setdefault("DEMO_MODE", "true")
os.environ.setdefault("RUN_STARTUP_DDL", "true")

from app.api.v1.routes.auth import AuthUserResponse, get_current_user  # noqa: E402
import app.models  # noqa: E402,F401
from app.db.base import Base  # noqa: E402
from app.db.session import engine  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.main import app as legacy_app  # noqa: E402
from app.models.user import User  # noqa: E402


def _legacy_current_user(request: Request, db: Session = Depends(SessionLocal)) -> AuthUserResponse:
    auth_header = request.headers.get("authorization", "")
    if not auth_header.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    email = auth_header.split(" ", 1)[1].strip().lower()
    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unknown test user")
    role_code = user.roles[0].code if user.roles else "requester"
    return AuthUserResponse(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=role_code,
        tenant_id=user.tenant_id,
        is_root=user.is_root,
        is_superuser=user.is_superuser,
    )


legacy_app.dependency_overrides[get_current_user] = _legacy_current_user
client = TestClient(legacy_app)

test_user_email = "admin@sbs.local"
admin_user_email = "admin@sbs.local"
standard_user_email = "manager@sbs.local"


@pytest.fixture()
def db_session() -> Session:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture()
def app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'app.db'}")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.setenv("RUN_STARTUP_DDL", "true")
    monkeypatch.setenv(
        "EMAIL_ATTACHMENT_STORAGE_PATH",
        str(tmp_path / "attachments"),
    )

    reload_prefixes = [
        "app.main",
        "app.db.session",
        "app.core.config",
        "app.services.seed",
        "app.services.service_desk",
        "app.api.v1.router",
        "app.api.v1.routes.",
    ]
    for module_name in list(sys.modules.keys()):
        if any(module_name == prefix or module_name.startswith(prefix) for prefix in reload_prefixes):
            sys.modules.pop(module_name, None)

    from app.main import app as fastapi_app

    return fastapi_app
