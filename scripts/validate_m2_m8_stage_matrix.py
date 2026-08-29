from __future__ import annotations

import json
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[1]
MATRIX = ROOT / "release" / "m2-m8-stage-matrix.json"
ROADMAP = ROOT / "docs" / "roadmap" / "PRODUCTION-ITSM-MASTER-ROADMAP.md"
ALLOWED_STATUSES = {
    "COMPLETED_LOCAL",
    "IMPLEMENTATION_COMPLETE_RUNTIME_GATE_PENDING",
}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def main() -> int:
    matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
    roadmap = ROADMAP.read_text(encoding="utf-8")
    scope = roadmap.split("# Milestone M2", maxsplit=1)[1].split(
        "# Milestone M9", maxsplit=1
    )[0]
    roadmap_ids = set(
        re.findall(r"^## ([A-Z][A-Z0-9-]*-\d{3})\s+—", scope, re.M)
    )
    stages = matrix.get("stages")
    _require(isinstance(stages, list), "Stage matrix must contain a stages list")
    matrix_ids = {str(stage.get("id")) for stage in stages}
    _require(
        matrix_ids == roadmap_ids,
        "Stage matrix and roadmap M2-M8 stage IDs differ: "
        f"missing={sorted(roadmap_ids - matrix_ids)}, "
        f"extra={sorted(matrix_ids - roadmap_ids)}",
    )
    _require(
        matrix.get("runtime_acceptance") == "PENDING",
        "Runtime acceptance must remain pending without live evidence",
    )

    artifact_count = 0
    for stage in stages:
        stage_id = str(stage["id"])
        _require(
            stage.get("status") in ALLOWED_STATUSES,
            f"{stage_id} has an invalid status",
        )
        _require(
            stage.get("milestone") in {f"M{number}" for number in range(2, 9)},
            f"{stage_id} has an invalid milestone",
        )
        for field in ("report", "runbook"):
            path = ROOT / str(stage.get(field, ""))
            _require(path.is_file(), f"{stage_id} misses {field}: {path}")
            artifact_count += 1
        verification = stage.get("verification")
        _require(
            isinstance(verification, list) and verification,
            f"{stage_id} has no verification artifacts",
        )
        for item in verification:
            path = ROOT / str(item)
            _require(path.is_file(), f"{stage_id} misses verification: {path}")
            artifact_count += 1

    print(
        "M2-M8 stage matrix valid: "
        f"{len(stages)} stages, {artifact_count} evidence links, "
        "runtime acceptance pending."
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, json.JSONDecodeError, IndexError) as exc:
        print(f"M2-M8 stage matrix invalid: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
