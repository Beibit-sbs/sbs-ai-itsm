# Production-like continuation rehearsal — 2026-08-29

## Scope

Deploy migration `0081` and ticket duplicate/merge/split governance to the
existing isolated PostgreSQL/Redis rehearsal without reusing the development
SQLite data plane or clearing existing rehearsal records.

## Result

- Images rebuilt together: backend, migrate, worker, scheduler and frontend.
- PostgreSQL migration applied transactionally:
  `20260814_0080 -> 20260829_0081`.
- `alembic current`: `20260829_0081 (head)`.
- Backend replicas: 3/3 healthy.
- Frontend: healthy at `http://127.0.0.1:18080`.
- Worker and leader-elected scheduler: running.
- Readiness: HTTP 200, with PostgreSQL `ok`, Redis `ok`, migrations `ok`,
  runtime `ready` and websocket transport `ready`.
- Production Docker frontend build: 142 modules.
- Route authentication contract: 746 total, 739 protected, 7 governed public.
- OpenAPI: 738 operations / 621 paths.

## Focused gates

- current collection: 775 tests;
- new governance suite: 6/6;
- migration/on-behalf compatibility: 6/6;
- expanded ticket regression: 33/33;
- Ruff, compileall and TypeScript: PASS;
- accessibility and interactive controls: PASS.

No secret value was printed into the evidence. No rehearsal data was deleted.
