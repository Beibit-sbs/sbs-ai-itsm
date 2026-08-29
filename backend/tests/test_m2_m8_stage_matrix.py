from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_m2_m8_matrix_tracks_every_local_stage_and_runtime_gate() -> None:
    matrix = json.loads(
        (ROOT / "release" / "m2-m8-stage-matrix.json").read_text(
            encoding="utf-8"
        )
    )

    assert matrix["runtime_acceptance"] == "PENDING"
    assert len(matrix["stages"]) == 35
    assert {stage["milestone"] for stage in matrix["stages"]} == {
        f"M{number}" for number in range(2, 9)
    }
    assert all(stage["report"] for stage in matrix["stages"])
    assert all(stage["runbook"] for stage in matrix["stages"])
    assert all(stage["verification"] for stage in matrix["stages"])


def test_m2_m8_matrix_has_no_duplicate_stage_ids() -> None:
    matrix = json.loads(
        (ROOT / "release" / "m2-m8-stage-matrix.json").read_text(
            encoding="utf-8"
        )
    )
    stage_ids = [stage["id"] for stage in matrix["stages"]]

    assert len(stage_ids) == len(set(stage_ids))
