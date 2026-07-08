from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest


backend_root = Path(__file__).resolve().parents[1]
if str(backend_root) not in sys.path:
    sys.path.insert(0, str(backend_root))


@pytest.fixture()
def app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'app.db'}")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")

    for module_name in ["app.main", "app.db.session", "app.core.config", "app.services.seed", "app.services.service_desk"]:
        sys.modules.pop(module_name, None)

    from app.main import app as fastapi_app

    return fastapi_app