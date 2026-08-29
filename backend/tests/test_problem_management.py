from __future__ import annotations

from fastapi.testclient import TestClient


def _login(client: TestClient, email: str, password: str = "Sbs!2026") -> str:
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _linked_records(client: TestClient, token: str) -> tuple[list[str], str]:
    tickets = client.get("/api/v1/tickets?page_size=3", headers=_headers(token))
    assets = client.get("/api/v1/assets?page_size=1", headers=_headers(token))
    assert tickets.status_code == 200, tickets.text
    assert assets.status_code == 200, assets.text
    return [item["id"] for item in tickets.json()["items"]], assets.json()["items"][0]["id"]


def _create_problem(
    client: TestClient,
    token: str,
    *,
    ticket_ids: list[str] | None = None,
    asset_ids: list[str] | None = None,
    change_ids: list[str] | None = None,
    problem_type: str = "REACTIVE",
) -> dict:
    response = client.post(
        "/api/v1/problems",
        headers=_headers(token),
        json={
            "title": "Recurring campus network packet loss",
            "description": "Repeated user-facing network degradation requires structural analysis.",
            "problem_type": problem_type,
            "service_name": "Campus Network",
            "category": "Network",
            "impact_level": "HIGH",
            "urgency_level": "HIGH",
            "detection_source": "Recurring incident review",
            "symptoms": "Intermittent packet loss, high latency, and repeated access-point reconnects.",
            "ticket_ids": ticket_ids or [],
            "asset_ids": asset_ids or [],
            "change_ids": change_ids or [],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _transition(
    client: TestClient,
    token: str,
    problem: dict,
    action: str,
    **extra,
) -> dict:
    response = client.post(
        f"/api/v1/problems/{problem['id']}/transitions",
        headers=_headers(token),
        json={"action": action, "expected_version": problem["version"], **extra},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_problem_full_rca_known_error_and_closure_lifecycle(app) -> None:
    with TestClient(app) as client:
        agent = _login(client, "agent.network@sbs.local")
        manager = _login(client, "manager@sbs.local")
        ticket_ids, asset_id = _linked_records(client, manager)
        assert len(ticket_ids) == 3
        problem = _create_problem(
            client,
            agent,
            ticket_ids=ticket_ids,
            asset_ids=[asset_id],
        )
        assert problem["priority"] == "P2"
        assert problem["incident_count"] == 3
        assert problem["asset_count"] == 1

        stale = client.patch(
            f"/api/v1/problems/{problem['id']}",
            headers=_headers(agent),
            json={"expected_version": 999, "title": "Stale problem update"},
        )
        assert stale.status_code == 409

        problem = _transition(client, agent, problem, "START_INVESTIGATION")
        problem = _transition(
            client,
            agent,
            problem,
            "IDENTIFY_ROOT_CAUSE",
            root_cause="A defective access-point firmware build leaks memory under roaming load.",
        )
        denied_publish = client.post(
            f"/api/v1/problems/{problem['id']}/transitions",
            headers=_headers(agent),
            json={
                "action": "PUBLISH_KNOWN_ERROR",
                "expected_version": problem["version"],
                "known_error_title": "AP roaming firmware memory leak",
                "workaround": "Restart affected access points and pin clients to the stable radio group.",
            },
        )
        assert denied_publish.status_code == 403

        problem = _transition(
            client,
            manager,
            problem,
            "PUBLISH_KNOWN_ERROR",
            known_error_title="AP roaming firmware memory leak",
            workaround="Restart affected access points and pin clients to the stable radio group.",
        )
        assert problem["status"] == "KNOWN_ERROR"
        assert problem["workaround_status"] == "PUBLISHED"
        assert problem["known_error_published_at"]

        kedb = client.get(
            "/api/v1/problems/known-errors?q=roaming",
            headers=_headers(agent),
        )
        assert kedb.status_code == 200, kedb.text
        assert kedb.json()["total"] == 1
        assert kedb.json()["items"][0]["problem_number"] == problem["problem_number"]

        problem = _transition(
            client,
            manager,
            problem,
            "RESOLVE",
            resolution_summary="Corrected firmware was deployed through an approved RFC and remained stable.",
        )
        problem = _transition(
            client,
            manager,
            problem,
            "CLOSE",
            validation_summary="Thirty-day monitoring confirmed no recurrence and normal roaming KPIs.",
        )
        assert problem["status"] == "CLOSED"
        assert problem["is_known_error"] is True
        assert {item["event_type"] for item in problem["history"]} >= {
            "CREATED",
            "START_INVESTIGATION",
            "IDENTIFY_ROOT_CAUSE",
            "PUBLISH_KNOWN_ERROR",
            "RESOLVE",
            "CLOSE",
        }

        summary = client.get("/api/v1/problems/summary", headers=_headers(manager))
        assert summary.status_code == 200, summary.text
        assert summary.json()["known_errors"] == 1
        assert summary.json()["recurring_problems"] == 1


def test_problem_transition_evidence_guards_and_reopen(app) -> None:
    with TestClient(app) as client:
        manager = _login(client, "manager@sbs.local")
        problem = _create_problem(client, manager, problem_type="PROACTIVE")

        premature = client.post(
            f"/api/v1/problems/{problem['id']}/transitions",
            headers=_headers(manager),
            json={
                "action": "PUBLISH_KNOWN_ERROR",
                "expected_version": problem["version"],
                "known_error_title": "Premature publication",
                "workaround": "This workaround must not be published before root cause analysis.",
            },
        )
        assert premature.status_code == 409

        problem = _transition(client, manager, problem, "START_INVESTIGATION")
        missing_rca = client.post(
            f"/api/v1/problems/{problem['id']}/transitions",
            headers=_headers(manager),
            json={
                "action": "IDENTIFY_ROOT_CAUSE",
                "expected_version": problem["version"],
                "root_cause": "short",
            },
        )
        assert missing_rca.status_code == 422

        problem = _transition(
            client,
            manager,
            problem,
            "IDENTIFY_ROOT_CAUSE",
            root_cause="Capacity exhaustion is caused by an undersized connection pool.",
        )
        problem = _transition(
            client,
            manager,
            problem,
            "RESOLVE",
            resolution_summary="Connection pool sizing was corrected and load-tested successfully.",
        )
        no_validation = client.post(
            f"/api/v1/problems/{problem['id']}/transitions",
            headers=_headers(manager),
            json={"action": "CLOSE", "expected_version": problem["version"]},
        )
        assert no_validation.status_code == 422
        problem = _transition(
            client,
            manager,
            problem,
            "CLOSE",
            validation_summary="Production observation confirmed stable pool utilization for two weeks.",
        )
        problem = _transition(
            client,
            manager,
            problem,
            "REOPEN",
            comment="A recurrence was detected under a new peak-load pattern.",
        )
        assert problem["status"] == "INVESTIGATING"
        assert problem["resolved_at"] is None
        assert problem["closed_at"] is None


def test_problem_relationship_validation_and_requester_denial(app) -> None:
    with TestClient(app) as client:
        manager = _login(client, "manager@sbs.local")
        requester = _login(client, "requester@sbs.local")
        invalid = client.post(
            "/api/v1/problems",
            headers=_headers(manager),
            json={
                "title": "Invalid relationship",
                "description": "Problem must reject links to records outside the available tenant scope.",
                "problem_type": "REACTIVE",
                "impact_level": "MEDIUM",
                "urgency_level": "MEDIUM",
                "symptoms": "A sufficiently detailed recurring symptom description.",
                "ticket_ids": ["00000000-0000-0000-0000-000000000000"],
            },
        )
        assert invalid.status_code == 422

        denied = client.get("/api/v1/problems", headers=_headers(requester))
        assert denied.status_code == 403


def test_known_error_retirement_removes_workaround_from_active_kedb(app) -> None:
    with TestClient(app) as client:
        manager = _login(client, "manager@sbs.local")
        problem = _create_problem(client, manager)
        problem = _transition(client, manager, problem, "START_INVESTIGATION")
        problem = _transition(
            client,
            manager,
            problem,
            "IDENTIFY_ROOT_CAUSE",
            root_cause="A legacy cache invalidation race leaves stale authorization state.",
        )
        problem = _transition(
            client,
            manager,
            problem,
            "PUBLISH_KNOWN_ERROR",
            known_error_title="Stale authorization cache",
            workaround="Flush the tenant authorization cache and restart the affected worker.",
        )
        problem = _transition(
            client,
            manager,
            problem,
            "RESOLVE",
            resolution_summary="Atomic cache invalidation was deployed and verified under concurrency.",
        )
        problem = _transition(
            client,
            manager,
            problem,
            "CLOSE",
            validation_summary="No stale authorization events occurred during the validation window.",
        )
        problem = _transition(
            client,
            manager,
            problem,
            "RETIRE_KNOWN_ERROR",
            comment="Permanent correction is stable; workaround is no longer required.",
        )
        assert problem["workaround_status"] == "RETIRED"
        kedb = client.get("/api/v1/problems/known-errors", headers=_headers(manager))
        assert kedb.status_code == 200
        assert kedb.json()["total"] == 0
