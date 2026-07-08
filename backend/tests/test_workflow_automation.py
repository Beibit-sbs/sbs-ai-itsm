def _login(client, email: str, password: str):
    response = client.post('/api/v1/auth/login', json={'email': email, 'password': password})
    assert response.status_code == 200
    return response.json()['access_token']


def _headers(token: str):
    return {'Authorization': f'Bearer {token}'}


def _find_rule_id(rules: list[dict], code: str) -> str:
    for item in rules:
        if item['code'] == code:
            return item['id']
    raise AssertionError(f'Rule {code} not found')


def test_manager_can_read_automation_overview_and_rules(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login(client, 'manager@sbs.local', 'Sbs!2026')
        overview = client.get('/api/v1/automation/overview', headers=_headers(token))
        assert overview.status_code == 200
        payload = overview.json()
        assert payload['active_rules'] >= 10
        assert payload['runbooks_available'] >= 10

        rules = client.get('/api/v1/automation/rules', headers=_headers(token))
        assert rules.status_code == 200
        assert len(rules.json()) >= 10


def test_dry_run_rule_returns_match_for_critical_ticket(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login(client, 'manager@sbs.local', 'Sbs!2026')
        rules = client.get('/api/v1/automation/rules', headers=_headers(token)).json()
        rule_id = _find_rule_id(rules, 'critical_network_ticket_auto_assign')

        response = client.post(
            f'/api/v1/automation/rules/{rule_id}/dry-run',
            headers=_headers(token),
            json={
                'trigger_type': 'ticket_created',
                'context': {
                    'entity_type': 'ticket',
                    'entity_id': 'demo-1',
                    'ticket': {'priority': 'CRITICAL', 'category': 'Сеть', 'title': 'Critical network outage'},
                },
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload['matched'] is True
        assert len(payload['planned_actions']) >= 1


def test_manual_run_creates_action_logs(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login(client, 'manager@sbs.local', 'Sbs!2026')
        rules = client.get('/api/v1/automation/rules', headers=_headers(token)).json()
        rule_id = _find_rule_id(rules, 'manual_executive_check')

        run_response = client.post(
            f'/api/v1/automation/rules/{rule_id}/manual-run',
            headers=_headers(token),
            json={'trigger_type': 'manual_run', 'context': {'entity_type': 'manual', 'entity_id': 'qa-manual-1'}},
        )
        assert run_response.status_code == 200
        run_id = run_response.json()['run']['id']

        logs_response = client.get(f'/api/v1/automation/runs/{run_id}/logs', headers=_headers(token))
        assert logs_response.status_code == 200
        logs = logs_response.json()
        assert len(logs) >= 1


def test_approval_flow_approve_and_reject(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login(client, 'manager@sbs.local', 'Sbs!2026')
        approvals = client.get('/api/v1/automation/approvals?status=PENDING', headers=_headers(token))
        assert approvals.status_code == 200
        pending = approvals.json()
        assert len(pending) >= 1

        first_id = pending[0]['id']
        approve = client.patch(
            f'/api/v1/automation/approvals/{first_id}',
            headers=_headers(token),
            json={'decision': 'APPROVED', 'comment': 'Looks good'},
        )
        assert approve.status_code == 200
        assert approve.json()['status'] == 'APPROVED'

        approvals_after = client.get('/api/v1/automation/approvals?status=PENDING', headers=_headers(token)).json()
        if approvals_after:
            reject = client.patch(
                f"/api/v1/automation/approvals/{approvals_after[0]['id']}",
                headers=_headers(token),
                json={'decision': 'REJECTED', 'comment': 'Need more details'},
            )
            assert reject.status_code == 200
            assert reject.json()['status'] == 'REJECTED'


def test_suggestions_for_phishing_ticket(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login(client, 'manager@sbs.local', 'Sbs!2026')

        ticket = client.post(
            '/api/v1/tickets',
            headers=_headers(token),
            json={
                'title': 'Подозрение на фишинг в почте',
                'description': 'Пользователь получил фишинг-письмо с вредной ссылкой',
                'requester_name': 'Security User',
                'requester_email': 'security.user@sbs.local',
                'department': 'Security',
                'location': 'HQ',
                'category': 'SECURITY_PHISHING',
                'priority': 'HIGH',
                'assignee_name': 'Security Officer',
                'asset_id': None,
            },
        )
        assert ticket.status_code == 201
        ticket_id = ticket.json()['id']

        suggestions = client.get(f'/api/v1/automation/tickets/{ticket_id}/suggestions', headers=_headers(token))
        assert suggestions.status_code == 200
        payload = suggestions.json()
        assert payload['ticket_id'] == ticket_id
        assert len(payload['suggested_runbooks']) >= 1


def test_ticket_creation_triggers_automation_run(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login(client, 'manager@sbs.local', 'Sbs!2026')

        before_runs = client.get('/api/v1/automation/runs', headers=_headers(token))
        assert before_runs.status_code == 200
        before_count = len(before_runs.json())

        created = client.post(
            '/api/v1/tickets',
            headers=_headers(token),
            json={
                'title': 'Printer outage on floor 3',
                'description': 'Принтер не печатает и показывает ошибку. moodle printer integration check',
                'requester_name': 'Office User',
                'requester_email': 'office.user@sbs.local',
                'department': 'Operations',
                'location': 'Floor 3',
                'category': 'PRINTING',
                'priority': 'MEDIUM',
                'assignee_name': 'Support Agent',
                'asset_id': None,
            },
        )
        assert created.status_code == 201

        after_runs = client.get('/api/v1/automation/runs', headers=_headers(token))
        assert after_runs.status_code == 200
        assert len(after_runs.json()) > before_count


def test_requester_cannot_access_automation(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login(client, 'requester@sbs.local', 'Sbs!2026')
        response = client.get('/api/v1/automation/rules', headers=_headers(token))
        assert response.status_code == 403


def test_it_agent_cannot_manage_runbooks(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login(client, 'agent.support@sbs.local', 'Sbs!2026')
        response = client.post(
            '/api/v1/automation/runbooks',
            headers=_headers(token),
            json={
                'code': 'forbidden-runbook',
                'title': 'Forbidden runbook',
                'category': 'security',
                'severity': 'high',
                'steps_json': [],
            },
        )
        assert response.status_code == 403


def test_audit_log_created_for_automation_manual_run(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        manager_token = _login(client, 'manager@sbs.local', 'Sbs!2026')
        rules = client.get('/api/v1/automation/rules', headers=_headers(manager_token)).json()
        rule_id = _find_rule_id(rules, 'manual_executive_check')

        run_response = client.post(
            f'/api/v1/automation/rules/{rule_id}/manual-run',
            headers=_headers(manager_token),
            json={'trigger_type': 'manual_run', 'context': {'entity_type': 'manual', 'entity_id': 'audit-check-1'}},
        )
        assert run_response.status_code == 200

        admin_token = _login(client, 'admin@sbs.local', 'Sbs!2026')
        logs = client.get('/api/v1/admin/audit-logs?action=automation_manual_run_executed', headers=_headers(admin_token))
        assert logs.status_code == 200
        assert any(item['entity_id'] == rule_id for item in logs.json())
