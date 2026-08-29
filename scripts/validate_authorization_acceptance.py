from __future__ import annotations

import json
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "security" / "authorization-acceptance.json"
CONTROL_ID = re.compile(r"^AUTH-[A-Z0-9-]+-\d{3}$")
ALLOWED_RISKS = {"HIGH", "CRITICAL"}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _workspace_file(raw_path: object, *, control_id: str) -> Path:
    relative = Path(str(raw_path))
    _require(
        not relative.is_absolute() and ".." not in relative.parts,
        f"{control_id} has an unsafe evidence path: {relative}",
    )
    path = ROOT / relative
    _require(path.is_file(), f"{control_id} misses evidence file: {relative}")
    return path


def main() -> int:
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    controls = catalog.get("controls")
    _require(isinstance(controls, list), "Authorization controls must be a list")
    _require(
        catalog.get("runtime_acceptance") == "PENDING",
        "Runtime acceptance must remain pending without live evidence",
    )
    _require(
        len(controls) >= 20,
        "Critical authorization inventory is too narrow",
    )

    required_actors = set(catalog.get("required_actors", []))
    allowed_results = set(catalog.get("allowed_expected_results", []))
    _require(len(required_actors) >= 8, "Required actor inventory is incomplete")
    _require(
        {"DENY_401", "DENY_403", "HIDE_404", "EMPTY_RESULT", "ALLOW_200"}
        <= allowed_results,
        "Expected-result vocabulary is incomplete",
    )

    control_ids: set[str] = set()
    covered_actors: set[str] = set()
    domains: set[str] = set()
    for control in controls:
        control_id = str(control.get("id", ""))
        _require(
            CONTROL_ID.fullmatch(control_id) is not None,
            f"Invalid authorization control id: {control_id}",
        )
        _require(control_id not in control_ids, f"Duplicate control: {control_id}")
        control_ids.add(control_id)

        actor = str(control.get("actor", ""))
        _require(actor in required_actors, f"{control_id} has unknown actor")
        covered_actors.add(actor)
        domain = str(control.get("domain", "")).strip()
        _require(bool(domain), f"{control_id} has no domain")
        domains.add(domain)
        _require(
            control.get("risk") in ALLOWED_RISKS,
            f"{control_id} must be HIGH or CRITICAL",
        )
        _require(
            control.get("expected") in allowed_results,
            f"{control_id} has an invalid expected result",
        )
        _require(
            bool(str(control.get("owner", "")).strip()),
            f"{control_id} has no owner",
        )
        _require(
            bool(str(control.get("boundary", "")).strip()),
            f"{control_id} has no protected boundary",
        )

        implementation = control.get("implementation")
        _require(
            isinstance(implementation, list) and implementation,
            f"{control_id} has no implementation evidence",
        )
        for raw_path in implementation:
            _workspace_file(raw_path, control_id=control_id)

        evidence = control.get("evidence")
        _require(
            isinstance(evidence, dict),
            f"{control_id} has no regression evidence",
        )
        evidence_path = _workspace_file(
            evidence.get("file", ""),
            control_id=control_id,
        )
        test_name = str(evidence.get("test", ""))
        _require(
            test_name.startswith("test_"),
            f"{control_id} has an invalid regression test name",
        )
        _require(
            test_name in evidence_path.read_text(encoding="utf-8"),
            f"{control_id} references a missing regression: {test_name}",
        )

    _require(
        covered_actors == required_actors,
        "Authorization catalog does not cover every required actor: "
        f"missing={sorted(required_actors - covered_actors)}",
    )
    _require(len(domains) >= 10, "Authorization domain coverage is too narrow")
    _require(
        sum(control["risk"] == "CRITICAL" for control in controls) >= 15,
        "Critical authorization coverage is too narrow",
    )

    print(
        "Authorization acceptance valid: "
        f"{len(controls)} controls, {len(domains)} domains, "
        f"{len(covered_actors)} actors, runtime acceptance pending."
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Authorization acceptance invalid: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
