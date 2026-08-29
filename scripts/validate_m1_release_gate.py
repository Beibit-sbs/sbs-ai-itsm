from __future__ import annotations

import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "release" / "m1-gate.json"
EXPECTED_STAGES = {f"PRG-{number:03d}" for number in range(1, 8)}
ALLOWED_LOCAL_STATUSES = {
    "COMPLETED_LOCAL",
    "EXTERNAL_DEPENDENCY",
    "IMPLEMENTATION_COMPLETE_RUNTIME_GATE_PENDING",
}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def main() -> int:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    _require(contract.get("milestone") == "M1", "Contract milestone must be M1")
    _require(
        contract.get("milestone_status") == "RUNTIME_ACCEPTANCE_PENDING",
        "M1 must not be marked complete before runtime evidence exists",
    )
    stages = contract.get("stages")
    _require(isinstance(stages, list), "M1 stages must be a list")
    ids = {stage.get("id") for stage in stages}
    _require(ids == EXPECTED_STAGES, "M1 must contain PRG-001 through PRG-007")

    deferred_count = 0
    artifact_count = 0
    for stage in stages:
        stage_id = str(stage["id"])
        _require(
            stage.get("local_status") in ALLOWED_LOCAL_STATUSES,
            f"{stage_id} has an invalid local status",
        )
        _require(bool(stage.get("owner")), f"{stage_id} has no owner")
        artifacts = stage.get("artifacts")
        _require(
            isinstance(artifacts, list) and artifacts,
            f"{stage_id} has no artifacts",
        )
        for artifact in artifacts:
            _require(
                (ROOT / str(artifact)).exists(),
                f"{stage_id} references missing artifact {artifact}",
            )
            artifact_count += 1

        gates = stage.get("deferred_gates")
        _require(
            isinstance(gates, list) and gates,
            f"{stage_id} must retain explicit runtime gates",
        )
        for gate in gates:
            for field in ("id", "owner", "command", "acceptance", "evidence"):
                _require(
                    bool(str(gate.get(field, "")).strip()),
                    f"{stage_id} deferred gate misses {field}",
                )
            deferred_count += 1

    release_workflow = (
        ROOT / ".github" / "workflows" / "release-images.yml"
    ).read_text(encoding="utf-8")
    for control in (
        "docker/build-push-action@v6",
        "sbom: true",
        "provenance: mode=max",
        "cosign sign --yes",
        "actions/attest-build-provenance@v3",
        "mutable_tags:false",
    ):
        _require(control in release_workflow, f"Release workflow misses {control}")
    _require(
        "value=latest" not in release_workflow
        and "tags: latest" not in release_workflow,
        "Release workflow must not publish a mutable latest tag",
    )

    print(
        "M1 local release contract valid: "
        f"{len(stages)} stages, {artifact_count} artifacts, "
        f"{deferred_count} explicit runtime gates."
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"M1 release contract invalid: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
