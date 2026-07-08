from __future__ import annotations

import io

from openpyxl import Workbook


def _login(client, email: str, password: str) -> str:
    response = client.post('/api/v1/auth/login', json={'email': email, 'password': password})
    assert response.status_code == 200
    return response.json()['access_token']


def _build_excel_bytes(*, include_missing_location: bool = False) -> bytes:
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = 'Лист_1'

    for _ in range(6):
        worksheet.append([''] * 20)

    header = ['Наименование', 'Дата принятия к учету', 'Инвентарный номер', '', '', '', 'Первоначальная стоимость', '', 'Стоимость на конец периода', 'Амортизация на конец периода', 'Остаточная стоимость', 'МОЛ', 'Статус M', '', 'Статус O', 'ТЕХНИКА', '', 'КАБИНЕТ', 'Год']
    worksheet.append(header)

    worksheet.append(['Dell OptiPlex', '2023-05-01', 'INV-EXCEL-001', '', '', '', 120000, '', 80000, 40000, 80000, 'Иванов И.И.', '', '', '', 'СИСТЕМНЫЙ БЛОК', '', '311', 2023])
    worksheet.append(['HP Monitor', '2023-06-01', '', '', '', '', 50000, '', 35000, 15000, 35000, 'Петров П.П.', '', '', '', 'МОНИТОР', '', '205', 2023])
    worksheet.append(['Lenovo Laptop', '2022-01-10', 'INV-EXCEL-002', '', '', '', 240000, '', 90000, 150000, 90000, 'Сидорова С.С.', 'СПИСАНО', '', '', 'НОУТБУК', '', '120', 2022])
    worksheet.append(['Canon Printer', '2021-11-11', 'INV-EXCEL-003', '', '', '', 70000, '', 40000, 30000, 40000, 'Смирнова А.А.', '', '', 'ПЕРЕВЕДЕНО в Запасы', 'ПРИНТЕР', '', '' if include_missing_location else '105', 2021])
    worksheet.append(['Duplicate Desk', '2024-01-05', 'INV-EXCEL-001', '', '', '', 110000, '', 90000, 20000, 90000, 'Иванов И.И.', '', '', '', 'СИСТЕМНЫЙ БЛОК', '', '210', 2024])

    stream = io.BytesIO()
    workbook.save(stream)
    workbook.close()
    return stream.getvalue()


def _upload_preview(client, token: str, payload: bytes) -> str:
    upload_response = client.post(
        '/api/v1/assets/import/upload',
        headers={'Authorization': f'Bearer {token}'},
        files={'file': ('assets.xlsx', payload, 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')},
    )
    assert upload_response.status_code == 201
    batch_id = upload_response.json()['id']

    preview_response = client.post(
        '/api/v1/assets/import/preview',
        headers={'Authorization': f'Bearer {token}'},
        json={'batch_id': batch_id, 'dry_run': True},
    )
    assert preview_response.status_code == 200
    return batch_id


def test_upload_import_file(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login(client, 'manager@sbs.local', 'Sbs!2026')
        payload = _build_excel_bytes()
        response = client.post(
            '/api/v1/assets/import/upload',
            headers={'Authorization': f'Bearer {token}'},
            files={'file': ('assets.xlsx', payload, 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')},
        )
        assert response.status_code == 201
        body = response.json()
        assert body['status'] == 'uploaded'
        assert body['original_file_name'] == 'assets.xlsx'


def test_preview_import(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login(client, 'manager@sbs.local', 'Sbs!2026')
        batch_id = _upload_preview(client, token, _build_excel_bytes())
        rows_response = client.get(
            f'/api/v1/assets/import/batches/{batch_id}/rows',
            headers={'Authorization': f'Bearer {token}'},
        )
        assert rows_response.status_code == 200
        rows = rows_response.json()
        assert len(rows) >= 5


def test_normalize_row(app) -> None:
    from app.services.asset_import import AssetImportService

    service = AssetImportService()
    row = service.normalize_row(
        {
            'name': 'Lenovo',
            'inventory_number': 'INV-1',
            'original_type': 'НОУТБУК',
            'status_m': '',
            'status_o': '',
            'location': '201',
            'assigned_to_name': 'Иван',
            'accepted_at': '2022-01-01',
            'purchase_year': 2022,
            'purchase_cost': '100000',
            'current_cost': '50000',
            'depreciation_amount': '50000',
            'residual_value': '50000',
        }
    )
    assert row['asset_type'] == 'laptop'
    assert row['status'] == 'active'
    assert row['verification_status'] == 'verified'


def test_detect_disposed_asset(app) -> None:
    from app.services.asset_import import AssetImportService

    service = AssetImportService()
    row = service.normalize_row({'inventory_number': 'INV-2', 'original_type': 'НОУТБУК', 'status_m': 'СПИСАНО', 'status_o': ''})
    assert row['status'] == 'disposed'


def test_detect_missing_location(app) -> None:
    from app.services.asset_import import AssetImportService

    service = AssetImportService()
    row = service.normalize_row({'inventory_number': 'INV-3', 'original_type': 'ПРИНТЕР', 'status_m': '', 'status_o': '', 'location': ''})
    assert row['verification_status'] == 'needs_location'


def test_detect_duplicate_inventory_number(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login(client, 'manager@sbs.local', 'Sbs!2026')
        preview_response = client.post(
            '/api/v1/assets/import/preview',
            headers={'Authorization': f'Bearer {token}'},
            json={'batch_id': _upload_preview(client, token, _build_excel_bytes()), 'dry_run': True},
        )
        assert preview_response.status_code == 200
        payload = preview_response.json()
        assert payload['duplicate_rows'] >= 1


def test_commit_import_creates_assets(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login(client, 'manager@sbs.local', 'Sbs!2026')
        before_assets = client.get('/api/v1/assets', headers={'Authorization': f'Bearer {token}'}).json()

        batch_id = _upload_preview(client, token, _build_excel_bytes(include_missing_location=True))
        commit_response = client.post(
            f'/api/v1/assets/import/{batch_id}/commit',
            headers={'Authorization': f'Bearer {token}'},
            json={'dry_run': False},
        )
        assert commit_response.status_code == 200
        assert commit_response.json()['imported_rows'] >= 2

        after_assets = client.get('/api/v1/assets?source=excel_import', headers={'Authorization': f'Bearer {token}'}).json()
        assert len(after_assets) >= len(before_assets)


def test_commit_import_does_not_duplicate_existing_inventory_number(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login(client, 'manager@sbs.local', 'Sbs!2026')
        batch_id = _upload_preview(client, token, _build_excel_bytes())

        first_commit = client.post(
            f'/api/v1/assets/import/{batch_id}/commit',
            headers={'Authorization': f'Bearer {token}'},
            json={'dry_run': False},
        )
        assert first_commit.status_code == 200

        second_batch = _upload_preview(client, token, _build_excel_bytes())
        second_commit = client.post(
            f'/api/v1/assets/import/{second_batch}/commit',
            headers={'Authorization': f'Bearer {token}'},
            json={'dry_run': False},
        )
        assert second_commit.status_code == 200

        assets = client.get('/api/v1/assets?source=excel_import', headers={'Authorization': f'Bearer {token}'}).json()
        inventory_numbers = [item['inventory_number'] for item in assets if item['inventory_number']]
        assert len(inventory_numbers) == len(set(inventory_numbers))


def test_import_summary(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login(client, 'manager@sbs.local', 'Sbs!2026')
        _upload_preview(client, token, _build_excel_bytes())
        response = client.get('/api/v1/assets/import/summary', headers={'Authorization': f'Bearer {token}'})
        assert response.status_code == 200
        body = response.json()
        assert 'total_batches' in body
        assert 'total_rows' in body


def test_requester_cannot_import_assets(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login(client, 'requester@sbs.local', 'Sbs!2026')
        response = client.post(
            '/api/v1/assets/import/upload',
            headers={'Authorization': f'Bearer {token}'},
            files={'file': ('assets.xlsx', _build_excel_bytes(), 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')},
        )
        assert response.status_code == 403


def test_manager_can_preview_import(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login(client, 'manager@sbs.local', 'Sbs!2026')
        batch_id = _upload_preview(client, token, _build_excel_bytes())
        response = client.post(
            '/api/v1/assets/import/preview',
            headers={'Authorization': f'Bearer {token}'},
            json={'batch_id': batch_id, 'dry_run': True},
        )
        assert response.status_code == 200


def test_audit_log_created_on_commit(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        manager_token = _login(client, 'manager@sbs.local', 'Sbs!2026')
        batch_id = _upload_preview(client, manager_token, _build_excel_bytes())
        commit_response = client.post(
            f'/api/v1/assets/import/{batch_id}/commit',
            headers={'Authorization': f'Bearer {manager_token}'},
            json={'dry_run': False},
        )
        assert commit_response.status_code == 200

        admin_token = _login(client, 'admin@sbs.local', 'Sbs!2026')
        audit_response = client.get(
            '/api/v1/admin/audit-logs?action=asset_import_committed',
            headers={'Authorization': f'Bearer {admin_token}'},
        )
        assert audit_response.status_code == 200
        logs = audit_response.json()
        assert any(item['entity_id'] == batch_id for item in logs)
