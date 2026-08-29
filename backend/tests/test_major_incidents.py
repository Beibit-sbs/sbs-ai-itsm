from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient


def login(client: TestClient, email: str) -> tuple[str, dict]:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "Sbs!2026"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    return body["access_token"], body["user"]


def headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def ticket(client: TestClient, token: str, title: str) -> dict:
    response = client.post(
        "/api/v1/tickets",
        headers=headers(token),
        json={
            "title": title,
            "description": "Production service is unavailable for all users.",
            "requester_name": "NOC Operator",
            "requester_email": "noc@sbs.local",
            "on_behalf_reason": "NOC reported the outage",
            "department": "IT",
            "location": "Datacenter",
            "category": "NETWORK_INTERNET",
            "priority": "CRITICAL",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_major_incident_command_communications_pir_and_isolation(app) -> None:
    with TestClient(app) as client:
        manager_token, manager = login(client, "manager@sbs.local")
        admin_token, admin = login(client, "admin@sbs.local")
        other_token, _ = login(client, "other.admin@sbs.local")
        requester_token, _ = login(client, "requester@sbs.local")
        denied = client.get(
            "/api/v1/major-incidents",
            headers=headers(requester_token),
        )
        assert denied.status_code == 403
        parent = ticket(client, manager_token, "Campus network unavailable")
        child = ticket(client, manager_token, "Wi-Fi authentication unavailable")

        declared_response = client.post(
            "/api/v1/major-incidents",
            headers=headers(manager_token),
            json={
                "ticket_id": parent["id"],
                "severity": "SEV1",
                "title": "Campus connectivity major incident",
                "executive_summary": "Campus network access is unavailable.",
                "impact_statement": "All wired and wireless users are affected.",
                "affected_service": "Campus Network",
                "customer_impact": "Employees cannot access business applications.",
                "commander_user_id": manager["id"],
                "communications_lead_user_id": admin["id"],
                "war_room_url": "https://meet.example.test/incident-001",
                "child_ticket_ids": [child["id"]],
            },
        )
        assert declared_response.status_code == 201, declared_response.text
        incident = declared_response.json()
        assert incident["status"] == "DECLARED"
        assert incident["severity"] == "SEV1"
        assert incident["commander_name"] == manager["full_name"]
        assert len(incident["child_tickets"]) == 1
        assert incident["updates"][0]["update_type"] == "MILESTONE"

        duplicate = client.post(
            "/api/v1/major-incidents",
            headers=headers(manager_token),
            json={
                "ticket_id": parent["id"],
                "severity": "SEV1",
                "title": "Duplicate declaration",
                "executive_summary": "This duplicate must be rejected.",
                "impact_statement": "Duplicate declaration must not be accepted.",
                "affected_service": "Campus Network",
                "customer_impact": "Duplicate declaration has no new impact.",
                "commander_user_id": manager["id"],
                "communications_lead_user_id": admin["id"],
            },
        )
        assert duplicate.status_code == 409

        participant = client.post(
            f"/api/v1/major-incidents/{incident['id']}/participants",
            headers=headers(manager_token),
            json={
                "role": "TECHNICAL_LEAD",
                "user_id": admin["id"],
                "display_name": admin["full_name"],
            },
        )
        assert participant.status_code == 201, participant.text
        incident = participant.json()
        assert incident["participants"][0]["role"] == "TECHNICAL_LEAD"

        communication = client.post(
            f"/api/v1/major-incidents/{incident['id']}/updates",
            headers=headers(manager_token),
            json={
                "update_type": "STAKEHOLDER_COMMUNICATION",
                "audience": "STAKEHOLDERS",
                "message": "Network team isolated the failing core switch.",
                "service_status": "PARTIAL_OUTAGE",
                "channel": "email",
            },
        )
        assert communication.status_code == 200, communication.text
        incident = communication.json()
        assert incident["service_status"] == "PARTIAL_OUTAGE"
        assert incident["updates"][-1]["audience"] == "STAKEHOLDERS"

        def transition(action: str, comment: str) -> dict:
            nonlocal incident
            response = client.post(
                f"/api/v1/major-incidents/{incident['id']}/transitions",
                headers=headers(manager_token),
                json={
                    "expected_version": incident["version"],
                    "action": action,
                    "comment": comment,
                },
            )
            assert response.status_code == 200, response.text
            incident = response.json()
            return incident

        transition("START_MITIGATION", "Recovery work started.")
        transition("MONITOR", "Connectivity restored; monitoring stability.")
        transition("RESOLVE", "Service stable and customer impact ended.")
        assert incident["status"] == "RESOLVED"

        action_response = client.post(
            f"/api/v1/major-incidents/{incident['id']}/actions",
            headers=headers(manager_token),
            json={
                "title": "Replace unsupported core switch",
                "description": "Procure and install a supported redundant pair.",
                "owner_user_id": manager["id"],
                "due_at": (datetime.now(UTC) + timedelta(days=30)).isoformat(),
            },
        )
        assert action_response.status_code == 201, action_response.text
        incident = action_response.json()
        assert incident["actions"][0]["status"] == "OPEN"

        pir_response = client.put(
            f"/api/v1/major-incidents/{incident['id']}/pir",
            headers=headers(manager_token),
            json={
                "summary": "Unsupported hardware failed during peak usage.",
                "root_cause": "A core switch power subsystem failed permanently.",
                "contributing_factors": "Redundancy was not operational.",
                "lessons_learned": "Failover must be tested quarterly.",
                "prevention_plan": "Replace hardware and automate failover tests.",
            },
        )
        assert pir_response.status_code == 200, pir_response.text
        incident = pir_response.json()
        self_approval = client.post(
            f"/api/v1/major-incidents/{incident['id']}/pir/approve",
            headers=headers(manager_token),
            json={"expected_version": incident["pir"]["version"]},
        )
        assert self_approval.status_code == 403

        approved = client.post(
            f"/api/v1/major-incidents/{incident['id']}/pir/approve",
            headers=headers(admin_token),
            json={"expected_version": incident["pir"]["version"]},
        )
        assert approved.status_code == 200, approved.text
        incident = approved.json()
        assert incident["pir"]["status"] == "APPROVED"
        transition("CLOSE", "PIR approved; command lifecycle closed.")
        assert incident["status"] == "CLOSED"

        hidden = client.get(
            f"/api/v1/major-incidents/{incident['id']}",
            headers=headers(other_token),
        )
        assert hidden.status_code == 404
