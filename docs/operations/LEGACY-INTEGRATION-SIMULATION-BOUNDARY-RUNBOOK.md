# Legacy integration simulation boundary

## Purpose

The `/api/v1/integrations` legacy registry contains demonstration LDAP, Zimbra,
SMTP, Platonus, Moodle, 1C, Telegram, file-import, and webhook providers. These
providers are not production connectors. They must never create evidence that an
external system was contacted, a message was delivered, records were imported,
or an entity was exported.

The production integration control plane is the `Production API & Webhooks`
panel backed by `/api/v1/integration-platform`. Legacy actions are an optional
local demonstration surface only.

## Environment boundary

- Production and staging: set `DEMO_MODE=false`.
- Local product evaluation: keep `DEMO_MODE=false` unless a demonstration of
  synthetic connector data is explicitly required.
- Isolated demo: `DEMO_MODE=true` may expose the legacy tabs and actions.

`GET /api/v1/integrations/runtime-capabilities` is authenticated and reports
whether the legacy UI may be displayed. With demo mode off, the frontend shows
only the production control plane and does not query legacy systems, jobs,
events, mappings, or webhooks.

Legacy mutation endpoints enforce their normal permission first and then reject
execution with HTTP `410` when demo mode is off. Read endpoints remain available
for evidence review and migration support. Destructive cleanup and disabling an
old system remain available as safe production actions.

## Evidence semantics

- Mock health and connection checks use `simulated`, never `success` or
  `healthy`.
- Planned or unconfigured providers are skipped/failed; they are never promoted
  to success.
- Only a provider explicitly classified as `production` can create success
  evidence after a confirmed production result.
- Legacy retries preserve `simulated`; unsupported delivery becomes `failed`.
- Import actions are previews even when the caller requested `run`.
  `dry_run=true`, `success_rows=0`, `records_success=0`, and
  `imported_rows=0`.
- Export actions return `exported=false` and create a `simulated` event.
- Webhook simulation creates a `simulated` event but does not update
  `success_count`/`last_received_at`, create a domain notification, or trigger
  automation.
- The UI renders mock/demo/simulated/planned/future/logged-only states as
  warnings, not positive success.

Migration `20260729_0069` invalidates historical legacy success evidence:
mock-system health success timestamps are cleared, success events are
reclassified, import success counters are zeroed and marked dry-run, and legacy
webhook receipt success counters are cleared. Downgrade cannot restore evidence
whose trust has been invalidated.

## Operator verification

Run before every staging or production deployment:

```powershell
python scripts/validate_legacy_integration_boundary.py
python scripts/check-production-env.py --env-file .env.production
```

Then verify:

1. `DEMO_MODE=false`.
2. `/integrations` displays only `Production API & Webhooks`.
3. an authorized request to a legacy mutation endpoint returns HTTP `410`;
4. an unauthorized user receives HTTP `403` without learning feature state;
5. migration head is at least `20260729_0069`;
6. no mock system has `last_success_at`;
7. no mock-linked integration event remains `success`;
8. no completed mock import contains a positive success counter.

Use the production control plane for service accounts, API credentials,
outbound webhooks, delivery attempts, retry/DLQ operations, and health evidence.

## Runtime acceptance

In an isolated staging copy:

1. migrate a database containing historical mock success records and retain
   before/after counts;
2. prove all invalidated records match the semantics above;
3. call every guarded endpoint with demo mode off as both authorized and
   unauthorized users;
4. enable demo mode only in the isolated environment and prove simulated
   webhook/import/export actions create no production side effects;
5. execute one real production-control-plane delivery and correlate its
   transport response, delivery history, audit event, and remote receipt.

Do not convert a legacy provider to production by changing its displayed status.
Implement real transport, deployment-owned credentials, destination controls,
timeout/retry policy, tenant isolation, audit, tests, and runtime acceptance in
the production integration platform.
