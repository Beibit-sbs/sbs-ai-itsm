from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_m1_contract_is_complete_but_not_falsely_runtime_approved() -> None:
    contract = json.loads(
        (ROOT / "release" / "m1-gate.json").read_text(encoding="utf-8")
    )

    assert contract["milestone"] == "M1"
    assert contract["milestone_status"] == "RUNTIME_ACCEPTANCE_PENDING"
    assert {stage["id"] for stage in contract["stages"]} == {
        f"PRG-{number:03d}" for number in range(1, 8)
    }
    assert all(stage["artifacts"] for stage in contract["stages"])
    assert all(stage["deferred_gates"] for stage in contract["stages"])


def test_release_workflow_uses_immutable_signed_attested_images() -> None:
    workflow = (
        ROOT / ".github" / "workflows" / "release-images.yml"
    ).read_text(encoding="utf-8")

    assert "docker/build-push-action@v6" in workflow
    assert "sbom: true" in workflow
    assert "provenance: mode=max" in workflow
    assert "cosign sign --yes" in workflow
    assert "actions/attest-build-provenance@v3" in workflow
    assert "mutable_tags:false" in workflow
    assert "value=latest" not in workflow
    assert "tags: latest" not in workflow
