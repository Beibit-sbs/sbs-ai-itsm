# ASSET-IMPORT-001 Implementation Report

## Status

PASS

## Goal

Implement a safe and auditable Excel import flow for Assets with mandatory preview before commit, tenant-aware RBAC, duplicate inventory protection, and non-regression for existing modules.

## Scope Delivered

1. Backend import domain models for batches and rows.
2. Backend import service for parse/normalize/validate/preview/commit.
3. Asset API extensions for import workflow and advanced filters.
4. RBAC permissions and role grants for import actions.
5. Audit events for upload, preview, commit, and row-level outcomes.
6. Asset analytics extensions for import-specific metrics.
7. Frontend Assets page import UI (upload -> preview -> commit).
8. Frontend API client/types update for import and analytics payloads.
9. New backend tests for import flow and permissions.

## Backend Changes

- Extended Asset model fields:
  - source, source_batch_id, original_type
  - accepted_at, purchase_cost, current_cost, depreciation_amount, residual_value
  - purchase_year, verification_status, imported_at
- Added model: backend/app/models/asset_import_batch.py
- Added model: backend/app/models/asset_import_row.py
- Added service: backend/app/services/asset_import.py
- Registered models in backend/app/models/__init__.py
- Startup schema guard wired in backend/app/main.py via ensure_asset_import_schema(engine)
- Dependencies added in backend/pyproject.toml:
  - openpyxl==3.1.5
  - python-multipart==0.0.20

### Import Endpoints Implemented

- POST /api/v1/assets/import/upload
- POST /api/v1/assets/import/preview
- POST /api/v1/assets/import/{batch_id}/commit
- GET /api/v1/assets/import/batches
- GET /api/v1/assets/import/batches/{batch_id}
- GET /api/v1/assets/import/batches/{batch_id}/rows
- GET /api/v1/assets/import/template
- GET /api/v1/assets/import/summary

### Asset Filters Extended

GET /api/v1/assets now supports:

- source
- verification_status
- without_location
- disposed
- assigned_to_name
- purchase_year
- type

## Import Mapping and Rules

### Excel Parsing

- Uses openpyxl, no pandas.
- Sheet preference: "Лист_1", fallback to active sheet.
- Header auto-detection by marker scoring, default fallback to row 7.

### Normalization

- Status normalization:
  - contains "СПИСАНО" -> disposed
  - contains "ПЕРЕВЕДЕНО" and "ЗАПАС" -> in_stock
  - otherwise -> active
- Type normalization from Russian source labels into internal asset_type values.
- verification_status:
  - needs_location when location is empty
  - verified otherwise

### Validation and Duplicate Control

- Missing inventory number -> row status error.
- Duplicate inventory number within file -> duplicate.
- Duplicate inventory number against existing tenant assets -> duplicate.
- Commit is blocked until preview has been generated.
- Upload stores payload in batch metadata (base64) for deterministic preview/commit processing.

## RBAC and Roles

### New Permissions

- assets.import
- assets.import.preview
- assets.import.commit
- assets.import.read_batches

### Role Grants Updated

- saas_root: full import permissions
- tenant_admin: full import permissions
- requester: read-only import visibility path (preview/read batches) according to role matrix updates

## Audit Coverage

Events logged during import flow include:

- asset_import_uploaded
- asset_import_preview_generated
- asset_import_committed
- asset_import_row_skipped
- asset_updated_from_import
- asset_created_from_import

## Analytics Extensions

Asset analytics now include import-related counters and breakdowns:

- imported_assets_count
- assets_missing_location_count
- disposed_assets_count
- assets_by_source
- assets_by_purchase_year
- top_responsible_persons
- duplicate_inventory_numbers

## Frontend Changes

- Updated API types and methods in frontend/src/api/client.ts
- Assets page expanded in frontend/src/pages/AssetsPage.tsx:
  - File upload (.xlsx)
  - Preview generation
  - Commit validated rows
  - Error report CSV download
  - Import summary cards
  - Extended asset filters and source visibility
- Analytics page expanded in frontend/src/pages/AnalyticsPage.tsx with import metrics

## Tests Added and Updated

- Added: backend/tests/test_asset_import.py
  - upload
  - preview
  - normalization checks
  - duplicate handling
  - commit behavior
  - permission restrictions
  - audit log presence
- Updated: backend/tests/test_auth.py
  - replaced brittle fixed-count assertions with resilient non-regression assertions

## Validation Executed

1. Backend tests
- Command: pytest -q
- Result: PASS

2. Frontend type check
- Command: npm run -s tsc -b --pretty false
- Result: PASS

3. Frontend production build
- Command: npm run build
- Result: PASS

4. Compose configuration
- Command: docker compose config
- Result: PASS

## Non-Regression Notes

- Existing modules and routes were preserved; import functionality was added incrementally.
- Preview-before-commit contract is enforced by API state checks.
- Duplicate inventory protection prevents uncontrolled asset multiplication.
- Demo-safe behavior is preserved (no external systems required).

## Known Limits

- Supported file type is .xlsx only.
- Import payload size is limited by FILE_SIZE_LIMIT_BYTES (5 MB).
- Parsing and normalization are tailored to the agreed accounting sheet structure and markers.

## Next Stage

ITSM-POLISH-001
