# INC-003 — Ticket participants and watcher preferences

Date: 2026-08-14  
Status: `COMPLETE_LOCAL`

## Delivered

- tenant-scoped `ticket_participants` model and migration `0079`;
- internal users and external email participants;
- watcher, collaborator and requester-representative roles;
- `ALL`, `PUBLIC_ONLY`, `STATUS_ONLY` and `NONE` event scopes;
- independent in-app/email channels;
- self-subscription and self-service preference changes;
- optimistic version checks, reason-required updates and soft removal;
- ticket history and tamper-evident audit events;
- private fan-out that excludes requester/internal-comment leakage;
- recipient-scoped Notification Center and protected tenant operational scope;
- RU/KK/EN frontend tab and requester runtime smoke.

## Verification

| Gate | Result |
|---|---|
| Participants + notifications focused tests | 16 passed |
| Auth/migration/localization regression | 10 passed |
| Ruff / compileall | PASS |
| TypeScript / Vite production build | PASS |
| PostgreSQL migration | `20260814_0079 (head)` |
| Backend runtime | 3/3 healthy |
| Readiness / frontend | HTTP 200 / HTTP 200 |
| RU/KK/EN browser check | PASS |
| Browser console errors | 0 |

## Remaining external acceptance

Real outbound email delivery, provider bounce/complaint handling and
server-sized notification fan-out/load remain part of production server and
external-provider acceptance. They are not represented as mock success.
