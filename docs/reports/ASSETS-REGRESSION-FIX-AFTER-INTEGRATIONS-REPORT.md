# ASSETS-REGRESSION-FIX-AFTER-INTEGRATIONS Report

## Summary

Incident: `/assets` reported as broken after integrations production changes.

Resolved status: **restored**.

No commit performed.

## What was broken

- Frontend route `http://localhost:5173/assets` was initially unreachable (`ERR_CONNECTION_REFUSED`) because backend/frontend were not healthy from host perspective.
- After starting services, backend failed at startup with DB schema mismatch:
  - `sqlalchemy.exc.ProgrammingError: column external_systems.health_status does not exist`
- Because backend startup failed, Assets UI/API were unavailable.

## Root cause

Primary root cause: **pending Alembic migration** for integrations schema (`20261114_0008`) in the active Postgres volume.

This is not an Assets route/client logic bug.

- `alembic heads` showed `20261114_0008 (head)`.
- DB was still at `20261113_0007` before upgrade.
- Integrations model fields were already in ORM and seed query touched `external_systems.health_status` during app startup.

## Fix applied

Operational fix only (no feature work):

1. Applied migration to head using current running Postgres credentials (without exposing secret values):
   - current: `20261113_0007`
   - upgrade: `20261113_0007 -> 20261114_0008`
   - current after: `20261114_0008 (head)`

2. Restarted services:
   - `docker compose up -d backend frontend`
   - backend became healthy and assets endpoints returned 200.

No source-code regression patch was needed in Assets routes/client.

## Assets API verification

Authenticated via `/api/v1/auth/login` and validated:

- `GET /api/v1/assets?page=1&page_size=20` -> `200`
- `GET /api/v1/assets` -> `200`
- `GET /api/v1/assets/{id}` -> `200`
- `GET /api/v1/assets/{id}/history` -> `200`

Response bodies contain expected assets envelope (`items/total/page/page_size`) and asset detail payload.

## Frontend regression check

Checked files:
- `frontend/src/api/client.ts`
- `frontend/src/pages/AssetsPage.tsx`

Findings:
- `API_BASE_URL` valid.
- `fetchAssets/fetchAssetsPage` intact.
- `API_MAX_PAGE_SIZE=200` respected.
- `readJsonResponse` helper not broken.
- Asset types and methods were not overwritten by integrations methods.

## Backend assets route check

Checked:
- `backend/app/api/v1/routes/assets.py`

Findings:
- list/detail/history endpoints valid and working.
- assign/move/verify/dispose/restore endpoints present.
- import flow endpoints present and working.
- No runtime failure observed from integrations/automation/notification hooks during tested Assets operations.

## Browser smoke-check

Assets page (`/assets`) after fix:
- opens without white screen;
- assets list loads;
- navigation tabs work (`Реестр`, `Импорт Excel`, etc.);
- detail modal opens;
- detail `История` tab opens;
- move/assign/verify/dispose modals open;
- import tab is functional (file input/buttons/rows present);
- no critical runtime block observed.

Additional route spot-checks:
- `/tickets` opens;
- `/integrations` opens;
- `/automation` opens;
- `/notifications` opens;
- `/analytics` opens.

## Tests

Targeted:
- `backend/tests/test_asset_sla.py` -> pass
- `backend/tests/test_asset_import.py` -> pass
- `backend/tests/test_assets_inventory.py` -> pass
- `backend/tests/test_integrations.py` -> pass

Full backend:
- `pytest -q` -> **145 passed, 2 warnings**

## Frontend validation

- `npx tsc -b --pretty false` -> pass
- `npm run build` -> pass
- Non-blocking chunk-size warning from Vite remains.

## Docker / Compose validation

- `docker compose config` -> pass
- `docker compose up -d --build backend frontend` -> pass
- `backend`, `frontend`, `postgres`, `redis` healthy/running.

## Alembic validation

- `alembic heads` -> `20261114_0008 (head)`
- DB migrated to `20261114_0008 (head)`.

## Known limitations

- Startup traceback from pre-fix failed boot remains in historical logs (expected historical artifact).
- No new code changes were introduced for Assets because failure was migration/state related, not route/client logic regression.
