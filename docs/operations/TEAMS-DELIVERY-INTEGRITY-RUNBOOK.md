# Microsoft Teams delivery integrity runbook

## Purpose

Reserve `SENT` for an accepted call to an allowlisted Microsoft Teams Workflow
webhook. `SIMULATED` means the platform rendered and retained an Adaptive Card
locally; no Teams endpoint was called and no channel receipt is claimed.

## Invariants

- `MOCK` connectors can be created, tested, or activated only while
  `DEMO_MODE=true`.
- Mock delivery has status `SIMULATED`, zero attempts, no HTTP status, provider
  reference, last-attempt timestamp, or sent timestamp.
- Mock processing never increments connector success counters or sets
  `last_success_at`.
- Mock connector tests return `ok=false` and `status=SIMULATED`.
- Production event and major-incident room routing select only
  `WORKFLOW_WEBHOOK` connectors.
- Webhook rotation is unavailable for a mock connector.
- Dashboard health is `SIMULATED`, never `HEALTHY`, when only mock connectors
  are active.

## Local verification

```powershell
python scripts/validate_teams_delivery_integrity.py
python scripts/validate_prg006_contract.py
python scripts/validate_m1_release_gate.py
```

In the Teams control plane:

1. A legacy mock connector is labelled simulation-only.
2. Its connection test returns a simulation result.
3. A queued demo card becomes `SIMULATED`.
4. HTTP status, provider reference, sent timestamp, attempts, and connector
   success remain empty or zero.
5. With `DEMO_MODE=false`, mock creation, test, and activation return HTTP 410.

## Production acceptance

1. Apply migrations through current head `20260814_0073` (including Teams evidence migration `20260729_0072`).
2. Require `DEMO_MODE=false`.
3. Configure an allowlisted Microsoft Teams Workflow HTTPS endpoint.
4. Run the governed connector test and retain the returned HTTP status and
   optional Workflow run ID.
5. Trigger an approved business event and retain the `SENT` delivery, audit
   attribution, Teams channel receipt, and retry/dead-letter evidence.
6. Confirm major-incident rooms use a production connector and approved Teams
   deep links.
7. Confirm simulations are excluded from success and health metrics.

## Incident response

Treat any mock-linked `SENT`, HTTP success, provider reference, sent timestamp,
attempt, success counter, `last_success_at`, `HEALTHY` readiness, or production
war-room routing as invalid evidence. Pause the connector, preserve delivery
and audit records, apply the reclassification migration, rerun the validator,
and investigate the writer before restoring the collaboration channel.
