from copy import deepcopy
from types import SimpleNamespace

from fastapi.testclient import TestClient


def test_alertmanager_webhook_is_authenticated_and_idempotent(app, monkeypatch) -> None:
    import app.api.v1.routes.monitoring as monitoring_route

    monkeypatch.setattr(
        monitoring_route,
        "get_settings",
        lambda: SimpleNamespace(alertmanager_webhook_token="monitoring-token-value"),
    )
    payload = {
        "version": "4",
        "groupKey": "{}:{alertname=\"SbsBackendTargetDown\"}",
        "status": "firing",
        "receiver": "sbs-platform",
        "alerts": [
            {
                "status": "firing",
                "labels": {"alertname": "SbsBackendTargetDown", "severity": "critical"},
                "annotations": {"summary": "Backend replica is unavailable"},
                "startsAt": "2026-07-20T10:00:00Z",
                "endsAt": "0001-01-01T00:00:00Z",
                "generatorURL": "http://prometheus:9090/graph",
                "fingerprint": "abc123",
            }
        ],
    }
    with TestClient(app) as client:
        unauthorized = client.post("/api/v1/monitoring/alerts", json=payload)
        assert unauthorized.status_code == 401

        headers = {"Authorization": "Bearer monitoring-token-value"}
        accepted = client.post("/api/v1/monitoring/alerts", json=payload, headers=headers)
        duplicate = client.post("/api/v1/monitoring/alerts", json=payload, headers=headers)

        assert accepted.status_code == 200
        assert accepted.json() == {"accepted": 1, "duplicates": 0}
        assert duplicate.json() == {"accepted": 0, "duplicates": 1}

        batch_payload = deepcopy(payload)
        batch_payload["alerts"][0]["fingerprint"] = "x" * 128
        batch_payload["alerts"].append(deepcopy(batch_payload["alerts"][0]))
        first_occurrence = client.post(
            "/api/v1/monitoring/alerts", json=batch_payload, headers=headers
        )
        assert first_occurrence.json() == {"accepted": 1, "duplicates": 1}

        next_occurrence = deepcopy(batch_payload)
        next_occurrence["alerts"] = [next_occurrence["alerts"][0]]
        next_occurrence["alerts"][0]["startsAt"] = "2026-07-21T10:00:00Z"
        accepted_again = client.post(
            "/api/v1/monitoring/alerts", json=next_occurrence, headers=headers
        )
        assert accepted_again.json() == {"accepted": 1, "duplicates": 0}
