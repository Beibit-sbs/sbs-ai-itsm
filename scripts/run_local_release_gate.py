from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def _tool(explicit: str | None, name: str) -> str:
    resolved = explicit or shutil.which(name)
    if not resolved:
        raise ValueError(f"Required tool is unavailable: {name}")
    return resolved


def _run(
    name: str,
    command: list[str],
    *,
    cwd: Path,
) -> dict[str, Any]:
    started = time.perf_counter()
    result = subprocess.run(
        command,
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        timeout=180,
    )
    duration = round(time.perf_counter() - started, 3)
    combined = f"{result.stdout}\n{result.stderr}".strip()
    print(f"[{name}] exit={result.returncode} duration={duration}s")
    if combined:
        print(combined)
    return {
        "name": name,
        "exit_code": result.returncode,
        "duration_seconds": duration,
        "output_sha256": hashlib.sha256(combined.encode("utf-8")).hexdigest(),
        "passed": result.returncode == 0,
    }


def _capture(command: list[str], *, cwd: Path) -> str:
    result = subprocess.run(
        command,
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise ValueError(f"Provenance command failed: {command[1]}")
    return result.stdout.strip()


def _artifact_refs(values: list[str]) -> dict[str, str]:
    refs: dict[str, str] = {}
    for value in values:
        name, separator, digest = value.partition("=")
        if not separator or not re.fullmatch(r"[a-z][a-z0-9_-]{1,39}", name):
            raise ValueError("Artifact refs must use name=sha256:<64 lowercase hex> format")
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
            raise ValueError("Artifact refs must use name=sha256:<64 lowercase hex> format")
        if name in refs:
            raise ValueError(f"Duplicate artifact ref: {name}")
        refs[name] = digest
    return dict(sorted(refs.items()))


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run the safe local/static M1 release gate. "
            "This does not claim runtime acceptance."
        )
    )
    parser.add_argument("--python", dest="python_executable")
    parser.add_argument("--node", dest="node_executable")
    parser.add_argument("--docker", dest="docker_executable")
    parser.add_argument("--git", dest="git_executable")
    parser.add_argument(
        "--release-source-sha",
        help=(
            "Optional immutable source commit used to build runtime artifacts. "
            "Defaults to the current Git HEAD."
        ),
    )
    parser.add_argument(
        "--artifact",
        action="append",
        default=[],
        help="Repeatable artifact binding in name=sha256:<64 lowercase hex> format.",
    )
    parser.add_argument(
        "--record-ruff-blocked",
        action="store_true",
        help=(
            "Do not execute Ruff; retain it as an explicit failed check when "
            "a trusted executable is blocked by host policy."
        ),
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    python = _tool(args.python_executable or sys.executable, "python")
    node = _tool(args.node_executable, "node")
    docker = _tool(args.docker_executable, "docker")
    git = _tool(args.git_executable, "git")
    started_at = datetime.now(UTC)
    git_sha = _capture([git, "rev-parse", "HEAD"], cwd=ROOT)
    git_branch = _capture([git, "branch", "--show-current"], cwd=ROOT)
    git_status = _capture(
        [git, "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=ROOT,
    )
    release_source_sha = args.release_source_sha or git_sha
    if not re.fullmatch(r"[0-9a-f]{40}", release_source_sha):
        raise ValueError("Release source SHA must be a full lowercase Git SHA")
    artifact_refs = _artifact_refs(args.artifact)

    commands = [
        (
            "ruff",
            [python, "-m", "ruff", "check", "backend/app", "backend/tests", "scripts"],
            ROOT,
        ),
        (
            "compileall",
            [python, "-m", "compileall", "-q", "backend/app", "scripts"],
            ROOT,
        ),
        (
            "observability-contract",
            [python, "scripts/validate_observability_contract.py"],
            ROOT,
        ),
        (
            "prg006-contract",
            [python, "scripts/validate_prg006_contract.py"],
            ROOT,
        ),
        (
            "m1-contract",
            [python, "scripts/validate_m1_release_gate.py"],
            ROOT,
        ),
        (
            "m2-m8-stage-matrix",
            [python, "scripts/validate_m2_m8_stage_matrix.py"],
            ROOT,
        ),
        (
            "authorization-acceptance",
            [python, "scripts/validate_authorization_acceptance.py"],
            ROOT,
        ),
        (
            "route-authentication",
            [python, "scripts/validate_route_authentication.py"],
            ROOT,
        ),
        (
            "edge-security",
            [python, "scripts/validate_edge_security.py"],
            ROOT,
        ),
        (
            "session-security",
            [python, "scripts/validate_session_security.py"],
            ROOT,
        ),
        (
            "canary-evidence",
            [python, "scripts/validate_canary_evidence.py"],
            ROOT,
        ),
        (
            "alert-delivery",
            [python, "scripts/validate_alert_delivery.py"],
            ROOT,
        ),
        (
            "legacy-integration-boundary",
            [python, "scripts/validate_legacy_integration_boundary.py"],
            ROOT,
        ),
        (
            "automation-execution-integrity",
            [python, "scripts/validate_automation_execution_integrity.py"],
            ROOT,
        ),
        (
            "email-delivery-integrity",
            [python, "scripts/validate_email_delivery_integrity.py"],
            ROOT,
        ),
        (
            "teams-delivery-integrity",
            [python, "scripts/validate_teams_delivery_integrity.py"],
            ROOT,
        ),
        (
            "ai-provider-evidence-integrity",
            [python, "scripts/validate_ai_provider_evidence.py"],
            ROOT,
        ),
        (
            "permission-aware-ui",
            [python, "scripts/validate_permission_aware_ui.py"],
            ROOT,
        ),
        (
            "operational-ui-states",
            [python, "scripts/validate_operational_ui_states.py"],
            ROOT,
        ),
        (
            "i18n",
            [node, "scripts/i18n-audit.mjs"],
            ROOT / "frontend",
        ),
        (
            "typescript",
            [
                node,
                "node_modules/typescript/bin/tsc",
                "-p",
                "tsconfig.app.json",
                "--noEmit",
            ],
            ROOT / "frontend",
        ),
        (
            "accessibility",
            [node, "scripts/accessibility-audit.mjs"],
            ROOT / "frontend",
        ),
        (
            "interactive-controls",
            [node, "scripts/interactive-controls-audit.mjs"],
            ROOT / "frontend",
        ),
        (
            "compose-production",
            [
                docker,
                "compose",
                "-f",
                "docker-compose.prod.yml",
                "--env-file",
                ".env.production.example",
                "config",
                "--quiet",
            ],
            ROOT,
        ),
        (
            "compose-bootstrap",
            [
                docker,
                "compose",
                "-f",
                "docker-compose.prod.yml",
                "-f",
                "docker-compose.bootstrap.yml",
                "--env-file",
                ".env.production.example",
                "config",
                "--quiet",
            ],
            ROOT,
        ),
        (
            "openapi",
            [
                python,
                "-c",
                (
                    "from app.main import app; "
                    "spec=app.openapi(); "
                    "assert len(spec['paths']) >= 580; "
                    "print(len(spec['paths']))"
                ),
            ],
            ROOT / "backend",
        ),
        (
            "alembic-heads",
            [python, "-m", "alembic", "heads"],
            ROOT / "backend",
        ),
        (
            "diff-check",
            [git, "diff", "--check"],
            ROOT,
        ),
    ]

    results: list[dict[str, Any]] = []
    for name, command, cwd in commands:
        if name == "ruff" and args.record_ruff_blocked:
            blocked_output = (
                "BLOCKED: trusted Ruff execution is unavailable under the "
                "current host Application Control policy; lint is not waived."
            )
            print(f"[{name}] exit=126 duration=0.0s")
            print(blocked_output)
            results.append(
                {
                    "name": name,
                    "exit_code": 126,
                    "duration_seconds": 0.0,
                    "output_sha256": hashlib.sha256(
                        blocked_output.encode("utf-8")
                    ).hexdigest(),
                    "passed": False,
                    "blocked": True,
                }
            )
            continue
        results.append(_run(name, command, cwd=cwd))

    evidence = {
        "schema_version": "2026.07.1",
        "gate": "M1_LOCAL_STATIC",
        "status": "PASS" if all(item["passed"] for item in results) else "FAIL",
        "runtime_acceptance": "NOT_EXECUTED",
        "provenance": {
            "git_sha": git_sha,
            "git_branch": git_branch,
            "worktree_clean": not bool(git_status),
            "worktree_path_count": len(git_status.splitlines()) if git_status else 0,
            "release_source_sha": release_source_sha,
            "artifact_refs": artifact_refs,
        },
        "started_at": started_at.isoformat(),
        "finished_at": datetime.now(UTC).isoformat(),
        "checks": results,
    }
    canonical = json.dumps(evidence, sort_keys=True, separators=(",", ":"))
    evidence["evidence_sha256"] = hashlib.sha256(canonical.encode()).hexdigest()
    rendered = json.dumps(evidence, ensure_ascii=False, indent=2)
    print(rendered)
    if args.output:
        output = args.output.resolve()
        if ROOT not in output.parents:
            raise ValueError("Evidence output must remain inside the workspace")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(
            json.dumps(
                {
                    "schema_version": "2026.07.1",
                    "gate": "M1_LOCAL_STATIC",
                    "status": "FAIL",
                    "runtime_acceptance": "NOT_EXECUTED",
                    "error_type": exc.__class__.__name__,
                    "error": str(exc)[:500],
                },
                ensure_ascii=False,
            )
        )
        raise SystemExit(1) from exc
