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
        assert run.json()['status'] == 'manual_pending'

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


def test_mock_email_is_simulated_and_never_marked_sent(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login(client, 'manager@sbs.local', 'Sbs!2026')
        created = client.post(
            '/api/v1/automation/rules',
            headers=_headers(token),
            json={
                'code': 'pytest_mock_email_integrity',
                'name': 'Mock email integrity',
                'trigger_type': 'manual',
                'conditions_json': {},
                'actions_json': [
                    {
                        'type': 'create_mock_email_log',
                        'to_email': 'preview@example.invalid',
                    },
                ],
                'is_active': True,
                'cooldown_minutes': 0,
            },
        )
        assert created.status_code == 201
        run = client.post(
            f"/api/v1/automation/rules/{created.json()['id']}/run",
            headers=_headers(token),
            json={'payload': {'entity_type': 'manual'}},
        )
        assert run.status_code == 200
        execution = run.json()['execution']
        assert execution['status'] == 'simulated'

        logs = client.get(
            f"/api/v1/automation/runs/{execution['id']}/logs",
            headers=_headers(token),
        )
        assert logs.status_code == 200
        assert logs.json()[0]['status'] == 'simulated'

        email_logs = client.get(
            '/api/v1/notifications/email-log?status=SIMULATED&page_size=100',
            headers=_headers(token),
        )
        assert email_logs.status_code == 200
        preview = next(
            item
            for item in email_logs.json()['items']
            if item['to_email'] == 'preview@example.invalid'
        )
        assert preview['provider'] == 'mock_automation'
        assert preview['status'] == 'SIMULATED'
        assert preview['sent_at'] is None
        assert preview['delivered_at'] is None


def test_automation_action_cannot_mutate_cross_tenant_ticket(db_session) -> None:
    from app.models.tenant import Tenant
    from app.models.ticket import Ticket
    from app.services.automation import execute_action

    tenant_a = Tenant(
        id='tenant-automation-a',
        name='Automation A',
        slug='automation-a',
        status='active',
    )
    tenant_b = Tenant(
        id='tenant-automation-b',
        name='Automation B',
        slug='automation-b',
        status='active',
    )
    ticket = Ticket(
        id='ticket-automation-b',
        tenant_id=tenant_b.id,
        title='Cross-tenant target',
        requester_email='requester@example.invalid',
        requester_name='Requester',
        department='IT',
        location='HQ',
        category='Service',
        priority='MEDIUM',
        status='OPEN',
    )
    db_session.add_all([tenant_a, tenant_b, ticket])
    db_session.flush()

    result = execute_action(
        db_session,
        {'type': 'assign_ticket', 'assignee': 'attacker@example.invalid'},
        {'ticket_id': ticket.id},
        tenant_id=tenant_a.id,
    )

    assert result['status'] == 'skipped'
    assert result['result']['reason'] == 'tenant_scoped_ticket_required'
    assert ticket.assignee_name is None


def test_automation_transition_uses_canonical_ticket_lifecycle(db_session) -> None:
    from app.models.tenant import Tenant
    from app.models.ticket import Ticket
    from app.models.ticket_history import TicketHistory
    from app.services.automation import execute_action
    from sqlalchemy import select

    tenant = Tenant(
        id='tenant-automation-lifecycle',
        name='Automation Lifecycle',
        slug='automation-lifecycle',
        status='active',
    )
    ticket = Ticket(
        id='ticket-automation-lifecycle',
        tenant_id=tenant.id,
        title='Canonical automation target',
        requester_email='requester@example.invalid',
        requester_name='Requester',
        department='IT',
        location='HQ',
        category='Service',
        priority='MEDIUM',
        status='NEW',
        governance_version=1,
    )
    db_session.add_all([tenant, ticket])
    db_session.flush()

    result = execute_action(
        db_session,
        {
            'type': 'transition_ticket_status',
            'status': 'TRIAGE',
            'idempotency_key': 'automation-lifecycle-0001',
        },
        {'ticket_id': ticket.id},
        tenant_id=tenant.id,
    )
    assert result['status'] == 'success'
    assert ticket.status == 'TRIAGE'
    assert ticket.governance_version == 2
    db_session.flush()
    histories = db_session.scalars(
        select(TicketHistory).where(
            TicketHistory.ticket_id == ticket.id,
            TicketHistory.field_name == 'status',
        )
    ).all()
    assert [(item.old_value, item.new_value) for item in histories] == [
        ('NEW', 'TRIAGE')
    ]

    rejected = execute_action(
        db_session,
        {'type': 'transition_ticket_status', 'status': 'OPEN'},
        {'ticket_id': ticket.id},
        tenant_id=tenant.id,
    )
    assert rejected['status'] == 'skipped'
    assert rejected['result']['reason'] == 'invalid_ticket_status'
    assert ticket.status == 'TRIAGE'


def test_manual_rule_execution_hides_cross_tenant_rule(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        root_token = _login(client, 'saas.root@sbs.local', 'Sbs!2026')
        tenants = client.get(
            '/api/v1/tenants',
            headers=_headers(root_token),
        ).json()
        other_tenant = next(
            item for item in tenants if item['slug'] == 'demo-tenant-2'
        )
        created = client.post(
            '/api/v1/automation/rules',
            headers=_headers(root_token),
            json={
                'tenant_id': other_tenant['id'],
                'code': 'pytest_other_tenant_rule',
                'name': 'Other tenant rule',
                'trigger_type': 'manual',
                'conditions_json': {},
                'actions_json': [
                    {
                        'type': 'create_notification',
                        'recipient_email': 'other.admin@sbs.local',
                    },
                ],
                'is_active': True,
            },
        )
        assert created.status_code == 201

        manager_token = _login(client, 'manager@sbs.local', 'Sbs!2026')
        denied = client.post(
            f"/api/v1/automation/rules/{created.json()['id']}/run",
            headers=_headers(manager_token),
            json={'payload': {'entity_type': 'manual'}},
        )
        assert denied.status_code == 404


def test_malformed_automation_conditions_fail_closed() -> None:
    from app.models.automation_rule import AutomationRule
    from app.services.automation import evaluate_conditions

    malformed = AutomationRule(
        id='rule-malformed',
        tenant_id='tenant-a',
        code='malformed',
        name='Malformed',
        trigger_type='manual',
        conditions_json='"unexpected"',
        actions_json='[]',
        is_active=True,
        priority=1,
    )
    missing_path = AutomationRule(
        id='rule-missing-path',
        tenant_id='tenant-a',
        code='missing-path',
        name='Missing path',
        trigger_type='manual',
        conditions_json='{"conditions":[{"operator":"eq","value":"x"}]}',
        actions_json='[]',
        is_active=True,
        priority=1,
    )

    assert evaluate_conditions(malformed, {}) is False
    assert evaluate_conditions(missing_path, {}) is False
