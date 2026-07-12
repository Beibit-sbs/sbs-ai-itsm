# RELEASE-CANDIDATE-E2E-ACCEPTANCE-001 REPORT

## 1. Scope
End-to-end release candidate acceptance audit covering:
- static validation (backend tests, frontend typecheck/build, compose configs);
- alembic migration head vs current;
- runtime health / liveness / readiness / deep;
- API smoke matrix for core modules;
- RBAC role matrix on API endpoints;
- browser E2E across 13 routes for `saas_root` plus restricted-role sample (`requester`, `it_agent`);
- security surface (secrets not exposed, `.env.production` and backup artifacts ignored);
- one targeted regression fix.

No new business modules, no schema changes, no destructive operations.

## 2. Baseline
- Last commit before RC: `283d26f OPERATIONS-DEPLOYMENT-PRODUCTION-001 add deployment operations and diagnostics`
- Working tree at start: clean.
- Alembic head: `20261114_0008`.
- Alembic current (queried directly from Postgres container): `20261114_0008`.
- `alembic current` executed from the host fails with `failed to resolve host 'postgres'` because default `DATABASE_URL` uses the Docker service name; state is otherwise correct and validated via `psql`.

## 3. Validation Summary
| Check | Result |
| --- | --- |
| `pytest -q` (targeted `test_health.py`) | PASS (6 passed) |
| `pytest -q` (full backend suite) | PASS (149 passed, 4 warnings) |
| `npx tsc -b --pretty false` | PASS |
| `npm run build` | PASS (only Vite chunk-size warning, non-blocking) |
| `docker compose config` | PASS |
| `docker compose -f docker-compose.prod.yml config` | PASS |
| `/api/v1/health` | `ok` |
| `/api/v1/health/liveness` | `alive` |
| `/api/v1/health/readiness` | `ready=true`, postgres=ok, redis=ok |
| `/api/v1/health/deep` (root) | 200, postgres=ok, redis=ok, alembic=unknown (safe fallback), no secrets in payload |
| `.env.production` ignored | Yes (`.gitignore:3`) |
| Backup artifact ignored | Yes (`.gitignore:15`, `backups/`) |
| Browser smoke (`saas_root`, 13 routes) | 0 console errors, 0 4xx/5xx, 0 white screens, 0 secret leaks |

## 4. Role Matrix (API)
Endpoint access after fix (200=allowed, 403=denied by RBAC).

| Endpoint | saas_root | org_admin | it_manager | it_agent | security_officer | requester |
| --- | --- | --- | --- | --- | --- | --- |
| `/tickets?page=1&page_size=5` | 200 | 200 | 200 | 200 | 200 | 200 |
| `/assets?page=1&page_size=5` | 200 | 200 | 200 | 200 | 403 | 403 |
| `/knowledge/articles?page=1&page_size=5` | 200 | 200 | 200 | 200 | 200 | 200 |
| `/analytics/executive` | 200 | 200 | 200 | 403 | 200 | 403 |
| `/notifications` | 200 | 200 | 200 | 200 | 200 | 200 |
| `/automation/rules` | 200 | 200 | 200 | 200 | 200 | 403 |
| `/integrations/systems` | 200 | 200 | 200 | 403 | 200 | 403 |
| `/admin/users` | 200 | 200 | 403 | 403 | 403 | 403 |
| `/health/deep` (after fix) | 200 | 200 | 403 | 403 | 200 | 403 |

All non-allowed responses returned proper 403; no 500 observed.

## 5. API Smoke Matrix (root token)
| Method | Endpoint | Status | Payload size |
| --- | --- | --- | --- |
| GET | `/auth/me` | 200 | — |
| POST | `/auth/login` (saas_root/org_admin) | 200 | — |
| GET | `/tickets?page=1&page_size=20` | 200 | 12 items |
| GET | `/tickets/{id}` | 200 | — |
| GET | `/tickets/{id}/history` | 200 | — |
| GET | `/tickets/{id}/comments` | 405 (POST-only endpoint by design) | — |
| GET | `/assets?page=1&page_size=20` | 200 | 20 items |
| GET | `/assets/{id}` | 200 | — |
| GET | `/assets/{id}/history` | 200 | — |
| GET | `/knowledge/articles?page=1&page_size=20` | 200 | 20 items |
| GET | `/knowledge/categories` | 200 | 8 items |
| GET | `/ai/suggestions` | 404 (route is `/ai/suggestions/{ticket_id}`) | — |
| GET | `/analytics/executive` | 200 | — |
| GET | `/reports` | 200 | 28 items |
| GET | `/notifications` | 200 | 14 items |
| GET | `/notifications/email-log` | 200 | 2 items |
| GET | `/notifications/preferences` | 200 | 15 items |
| GET | `/automation/rules` | 200 | 12 items |
| GET | `/automation/executions` | 200 | 20 items |
| GET | `/automation/runbooks` | 200 | 15 items |
| GET | `/automation/approvals` | 200 | 8 items |
| GET | `/integrations/systems` | 200 | 8 items |
| GET | `/integrations/events` | 200 | 20 items |
| GET | `/integrations/webhooks` | 200 | 5 items |
| GET | `/integrations/import-jobs` | 200 | 5 items |
| GET | `/integrations/mappings` | 200 | 6 items |
| GET | `/admin/users` | 200 | 10 items |
| GET | `/health/deep` | 200 | — |

Notes:
- `GET /ai/suggestions` returned 404 because AI suggestions endpoint is `/ai/suggestions/{ticket_id}`. Not a defect.
- `GET /tickets/{id}/comments` returned 405 because comments are POST-only; comments are surfaced inside ticket detail. Not a defect.

## 6. Browser Route Matrix (saas_root)
All 13 routes rendered with expected `h1`, 0 console errors, 0 4xx/5xx, 0 white screens, 0 secret leaks.

| Route | h1 | Console | 4xx | 5xx | White | Secret |
| --- | --- | --- | --- | --- | --- | --- |
| /dashboard | Добро пожаловать в SBS AI ITSM | 0 | 0 | 0 | no | no |
| /tickets | Заявки | 0 | 0 | 0 | no | no |
| /assets | Активы | 0 | 0 | 0 | no | no |
| /sla | SLA | 0 | 0 | 0 | no | no |
| /knowledge | База знаний | 0 | 0 | 0 | no | no |
| /copilot | AI Copilot | 0 | 0 | 0 | no | no |
| /analytics | Аналитика | 0 | 0 | 0 | no | no |
| /notifications | Уведомления | 0 | 0 | 0 | no | no |
| /notifications/email-log | Email Log | 0 | 0 | 0 | no | no |
| /automation | Автоматизация | 0 | 0 | 0 | no | no |
| /integrations | Интеграции | 0 | 0 | 0 | no | no |
| /admin | Администрирование | 0 | 0 | 0 | no | no |
| /admin/system | System Diagnostics | 0 | 0 | 0 | no | no |

Restricted-role sample (requester, it_agent):
- All pages render with h1, no white screens, no secret leaks, no 5xx.
- Some pages emit 403 responses on background API queries (expected RBAC behavior) that surface as console error entries but do not break UI.
- `/admin` for restricted roles is redirected to `/login` by the admin page-level guard (functional but sub-optimal UX; better would be `/dashboard`).

## 7. Module Acceptance
- Tickets: list, detail, history endpoints OK; UI opens and renders with correct h1; comments POST-only by design.
- Assets: list, detail, history OK; assets page renders; RBAC enforced for security/requester.
- Knowledge / AI: knowledge articles/categories OK; AI suggestions endpoint is per-ticket, no global list route by design.
- Analytics / Reports: `/analytics/executive` OK; `/reports` returns 28 items; UI opens.
- Notifications: list, email-log, preferences OK; UI opens.
- Automation: rules, executions, runbooks, approvals OK; UI opens.
- Integrations: systems, events, webhooks, import-jobs, mappings OK; UI opens.
- Admin / System: admin users list OK; `/admin/system` opens for saas_root/org_admin/security_officer after RBAC fix and does not expose secrets.

## 8. Security Checks
- `/health/deep` payload sanitized: `database_url`, `jwt_secret`, `password` literals not present.
- `.env.production` ignored: `.gitignore:3`.
- Backup artifacts ignored: `.gitignore:15` covers `backups/`; verified against latest `backups/db/*.sql.gz`.
- RBAC: correct 403 responses, no 500 substitution on unauthorized access.
- Credentials never printed in scripts (env checker prints OK/WEAK/MISSING only).
- External integrations remain mock-safe (existing project pattern; no real external calls invoked).
- No `docker compose down -v`, no volume delete, no DB reset.

## 9. Issues Found
Blockers: 0.
Major: 0.
Minor:
- M-01: Restricted roles opening `/admin` are redirected to `/login` instead of `/dashboard` (functional, but UX could be softer). Not a security issue.
- M-02: Deep health `alembic` block reports `status=unknown` in the runtime container (image lacks alembic ini path resolution as documented in the operations report). Postgres/Redis remain `ok`, so overall payload is `status=ok`. Acceptable safe fallback.
- M-03: Analytics/Integrations pages produce multiple background 403 requests for roles lacking analytics/integrations scopes. UI does not break; consider suppressing queries client-side by role in a later stage.
Accepted warnings:
- Vite chunk-size warning (bundle > 500 kB).
- Pytest StarletteDeprecationWarning about `httpx` and alembic path_separator DeprecationWarning; upstream lib warnings only.

## 10. Fixes Applied
- Fix F-01: `/api/v1/health/deep` previously required non-existent permission `admin.read`, so `organization_admin` and `security_officer` were blocked (`403`) even though the UI exposes `/admin/system` for these roles. Replaced with `admin.settings.read` / `admin.users.read` / `security.audit.read` any-of check while keeping `saas_root` bypass and preserving existing test (`test_deep_health_does_not_expose_secrets`).
  - File: `backend/app/api/v1/routes/health.py`
- After fix backend image was rebuilt (`docker compose up -d --build backend`).
- Re-tested `/health/deep` per role: root=200, org_admin=200, security_officer=200, it_manager=403, it_agent=403, requester=403.

## 11. Final RC Decision
RC_PASS_WITH_NOTES

Rationale:
- No blockers.
- No major issues.
- Core flows (auth, tickets, assets, knowledge, analytics, notifications, automation, integrations, admin, system diagnostics, health endpoints) all pass.
- Minor issues logged (M-01/M-02/M-03) do not affect release readiness.
- One targeted regression fix (F-01) was applied and validated.

## 12. Next Steps
- Optional: soften `/admin` redirect for authenticated but unauthorized users to `/dashboard`.
- Optional: gate analytics/integrations queries in the UI by role to reduce background 403 noise.
- Optional: package Alembic metadata into runtime image or expose migration head via seed to lift deep health `alembic` status to `ok`.
- Commit RC fix and report as a separate, explicit step.
