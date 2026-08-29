from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_authorization_catalog_covers_roles_domains_and_fail_closed_results() -> None:
    catalog = json.loads(
        (ROOT / "security" / "authorization-acceptance.json").read_text(
            encoding="utf-8"
        )
    )
    controls = catalog["controls"]

    assert catalog["runtime_acceptance"] == "PENDING"
    assert len(controls) >= 20
    assert {item["actor"] for item in controls} == set(
        catalog["required_actors"]
    )
    assert len({item["domain"] for item in controls}) >= 10
    assert sum(item["risk"] == "CRITICAL" for item in controls) >= 15
    assert all(item["owner"] and item["evidence"] for item in controls)


def test_authorization_control_ids_are_unique() -> None:
    catalog = json.loads(
        (ROOT / "security" / "authorization-acceptance.json").read_text(
            encoding="utf-8"
        )
    )
    control_ids = [item["id"] for item in catalog["controls"]]

    assert len(control_ids) == len(set(control_ids))
