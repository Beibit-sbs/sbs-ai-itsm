#!/usr/bin/env python3
"""Rotate the first-deploy root password without disclosing credentials."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import secrets
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen


def _load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.removeprefix("export ").split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _request_json(
    base_url: str,
    method: str,
    path: str,
    *,
    payload: dict[str, Any] | None = None,
    token: str = "",
) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Accept": "application/json", "User-Agent": "sbs-bootstrap-rotation/1.0"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(
        urljoin(base_url.rstrip("/") + "/", path.lstrip("/")),
        data=body,
        headers=headers,
        method=method,
    )
    try:
        with urlopen(request, timeout=15) as response:
            return json.loads(response.read())
    except HTTPError as exc:
        raise RuntimeError(f"{method} {path} returned HTTP {exc.code}") from exc
    except (URLError, TimeoutError) as exc:
        raise RuntimeError(f"{method} {path} is unreachable") from exc


def _login(base_url: str, email: str, password: str) -> str:
    payload = _request_json(
        base_url,
        "POST",
        "/api/v1/auth/login",
        payload={"email": email, "password": password},
    )
    token = str(payload.get("access_token") or "")
    if not token:
        if payload.get("mfa_required"):
            raise RuntimeError("root account requires MFA; rotate the password through an MFA session")
        raise RuntimeError("login response has no access token")
    return token


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, default=Path(".env.production"))
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--email", default=None)
    parser.add_argument("--output-secret", default="root_admin_password")
    args = parser.parse_args()

    env_file = args.env_file.resolve()
    if not env_file.is_file():
        print(f"[FAIL] environment file not found: {env_file}", file=sys.stderr)
        return 1
    values = _load_env(env_file)
    email = args.email or values.get("BOOTSTRAP_ROOT_EMAIL", "")
    if not email:
        print("[FAIL] BOOTSTRAP_ROOT_EMAIL is not configured", file=sys.stderr)
        return 1

    secrets_dir_value = values.get("SECRETS_DIR", "")
    secrets_dir = Path(secrets_dir_value)
    if not secrets_dir.is_absolute():
        secrets_dir = env_file.parent / secrets_dir
    bootstrap_path = secrets_dir / "bootstrap_root_password"
    output_path = secrets_dir / args.output_secret
    if not bootstrap_path.is_file():
        print("[FAIL] bootstrap root password secret is missing", file=sys.stderr)
        return 1
    if output_path.exists():
        print(f"[FAIL] refusing to overwrite existing secret: {output_path}", file=sys.stderr)
        return 1

    old_password = bootstrap_path.read_text(encoding="utf-8").strip()
    new_password = "A9!a-" + secrets.token_urlsafe(36)
    try:
        access_token = _login(args.base_url, email, old_password)
        identity = _request_json(
            args.base_url,
            "GET",
            "/api/v1/auth/me",
            token=access_token,
        )
        user_id = str(identity.get("id") or "")
        if not user_id or str(identity.get("email") or "").lower() != email.lower():
            raise RuntimeError("authenticated identity does not match the bootstrap account")
        _request_json(
            args.base_url,
            "POST",
            f"/api/v1/admin/users/{user_id}/reset-password",
            payload={"new_password": new_password, "revoke_sessions": True},
            token=access_token,
        )
        _login(args.base_url, email, new_password)
    except RuntimeError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 1

    output_path.write_bytes((new_password + "\n").encode("utf-8"))
    if os.name != "nt":
        output_path.chmod(0o600)
    print(f"Rotated bootstrap root password and stored the replacement in {output_path}")
    print("Remove BOOTSTRAP_ROOT_EMAIL and the bootstrap secret mount before normal operation.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
