def _login(client, email: str, password: str):
    response = client.post('/api/v1/auth/login', json={'email': email, 'password': password})
    assert response.status_code == 200
    return response.json()['access_token']


def _headers(token: str):
    return {'Authorization': f'Bearer {token}'}


def _items(payload):
    if isinstance(payload, list):
        return payload
    return payload.get('items', [])


def test_requester_denied_automation(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login(client, 'requester@sbs.local', 'Sbs!2026')
        response = client.get('/api/v1/automation/rules', headers=_headers(token))
        assert response.status_code == 403


def test_manager_can_create_update_enable_disable_rule(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login(client, 'manager@sbs.local', 'Sbs!2026')
        created = client.post(
            '/api/v1/automation/rules',
            headers=_headers(token),
            json={
                'code': 'pytest_rule_stage_001',
                'name': 'Pytest Rule',
                'description': 'created by pytest',
                'trigger_type': 'manual',
                'conditions_json': {},
                'actions_json': [{'type': 'create_notification', 'title': 'pytest'}],
                'is_active': True,
                'requires_approval': False,
                'cooldown_minutes': 0,
                'priority': 77,
            },
        )
        assert created.status_code == 201
        rule_id = created.json()['id']

        patched = client.patch(
            f'/api/v1/automation/rules/{rule_id}',
            headers=_headers(token),
            json={'description': 'updated', 'is_active': False},
        )
        assert patched.status_code == 200
        assert patched.json()['description'] == 'updated'
        assert patched.json()['is_active'] is False

        enabled = client.post(f'/api/v1/automation/rules/{rule_id}/enable', headers=_headers(token))
        assert enabled.status_code == 200
        assert enabled.json()['is_active'] is True

        disabled = client.post(f'/api/v1/automation/rules/{rule_id}/disable', headers=_headers(token))
        assert disabled.status_code == 200
        assert disabled.json()['is_active'] is False


def test_dry_run_and_manual_run_create_execution(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login(client, 'manager@sbs.local', 'Sbs!2026')
        rules = _items(client.get('/api/v1/automation/rules', headers=_headers(token)).json())
        rule_id = next(item['id'] for item in rules if item['code'] == 'manual_executive_check')

        dry_run = client.post(
            f'/api/v1/automation/rules/{rule_id}/dry-run',
            headers=_headers(token),
            json={'trigger_type': 'manual', 'context': {'entity_type': 'manual', 'entity_id': 'pytest-dry'}},
        )
        assert dry_run.status_code == 200
        assert dry_run.json()['execution']['status'] == 'dry_run'

        run = client.post(
            f'/api/v1/automation/rules/{rule_id}/run',
            headers=_headers(token),
            json={'payload': {'entity_type': 'manual', 'entity_id': 'pytest-run-1'}},
        )
        assert run.status_code == 200
        assert run.json()['execution']['id']


def test_requires_approval_creates_approval_request(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login(client, 'manager@sbs.local', 'Sbs!2026')
        created = client.post(
            '/api/v1/automation/rules',
            headers=_headers(token),
            json={
                'code': 'pytest_rule_approval_001',
                'name': 'Pytest Approval Rule',
                'trigger_type': 'manual',
                'conditions_json': {},
                'actions_json': [{'type': 'close_ticket'}],
                'is_active': True,
                'requires_approval': True,
                'approval_role': 'it_manager',
                'priority': 5,
            },
        )
        assert created.status_code == 201
        rule_id = created.json()['id']

        run = client.post(
            f'/api/v1/automation/rules/{rule_id}/run',
            headers=_headers(token),
            json={'payload': {'entity_type': 'manual', 'entity_id': 'pytest-approval-run'}},
        )
        assert run.status_code == 200
        assert run.json()['execution']['status'] == 'waiting_approval'

        approvals = client.get('/api/v1/automation/approvals?status=pending', headers=_headers(token))
        assert approvals.status_code == 200
        assert len(_items(approvals.json())) >= 1


def test_approval_approve_reject_and_runbook_flow(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login(client, 'manager@sbs.local', 'Sbs!2026')

        runbook = client.post(
            '/api/v1/automation/runbooks',
            headers=_headers(token),
            json={
                'code': 'pytest_runbook_001',
                'title': 'Pytest Runbook',
                'description': 'pytest runbook',
                'category': 'service',
                'severity': 'MEDIUM',
                'steps_json': [{'title': 'Step 1', 'description': 'desc', 'action_type': 'notify_role', 'action_payload': {}, 'requires_confirmation': False, 'order': 1}],
                'requires_approval': False,
            },
        )
        assert runbook.status_code == 201
        runbook_id = runbook.json()['id']

        dry = client.post(f'/api/v1/automation/runbooks/{runbook_id}/dry-run', headers=_headers(token), json={'payload': {'source': 'pytest'}})
        assert dry.status_code == 200
        assert dry.json()['status'] == 'dry_run'

        run = client.post(f'/api/v1/automation/runbooks/{runbook_id}/run', headers=_headers(token), json={'payload': {'source': 'pytest'}})
        assert run.status_code == 200

        approvals = client.get('/api/v1/automation/approvals?status=pending', headers=_headers(token))
        assert approvals.status_code == 200
        pending = _items(approvals.json())
        if pending:
            approve = client.post(f"/api/v1/automation/approvals/{pending[0]['id']}/approve", headers=_headers(token), json={'comment': 'ok'})
            assert approve.status_code == 200
            assert approve.json()['status'] == 'approved'

        approvals = client.get('/api/v1/automation/approvals?status=pending', headers=_headers(token))
        pending = _items(approvals.json())
        if pending:
            reject = client.post(f"/api/v1/automation/approvals/{pending[0]['id']}/reject", headers=_headers(token), json={'comment': 'no'})
            assert reject.status_code == 200
            assert reject.json()['status'] == 'rejected'


def test_executions_pagination_and_detail(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login(client, 'manager@sbs.local', 'Sbs!2026')
        page = client.get('/api/v1/automation/executions?page=1&page_size=10', headers=_headers(token))
        assert page.status_code == 200
        payload = page.json()
        assert 'items' in payload and 'total' in payload

        items = payload['items']
        if items:
            detail = client.get(f"/api/v1/automation/executions/{items[0]['id']}", headers=_headers(token))
            assert detail.status_code == 200
            assert 'execution' in detail.json()
            assert 'action_logs' in detail.json()
