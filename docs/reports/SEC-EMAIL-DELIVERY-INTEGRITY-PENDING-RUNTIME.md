# SEC-EMAIL-DELIVERY-INTEGRITY

Status: `IMPLEMENTATION_COMPLETE_RUNTIME_ACCEPTANCE_PENDING`  
Date: 2026-07-29

## Outcome

The local mock email path no longer fabricates transport success. Mock channel
creation/testing/activation is demo-only, simulated mail has no external
delivery identifiers or timestamps, simulation is excluded from channel
success/readiness, inbound synchronization is Graph-only, and historical mock
success is invalidated by migration `20260729_0071`.

## Implemented evidence

- Queue, direct provider, and legacy queued-worker mock paths produce
  `SIMULATED` or fail closed outside demo mode.
- Mock connection tests return `ok=false`; mock activation does not set
  `last_success_at`.
- Email dashboard and operator UI separate simulation from production accepted
  delivery and hide the mock provider outside demo mode.
- Simulated records are terminal and cannot be retried as delivery failures.
- Migration `20260729_0071` clears mock transport IDs, timestamps, attempts,
  channel success counters, and reclassifies associated delivery events.
- Regression tests cover demo simulation and production fail-closed behavior.
- `SEC-EMAIL-DELIVERY-INTEGRITY` is release-blocking through CI, PRG-006, and
  the consolidated local release gate.

## Runtime acceptance still required

- Apply the migration to a representative PostgreSQL copy.
- Run the focused and full backend suites when the runtime is available.
- Verify a real Microsoft Graph connection, accepted request ID, retry behavior,
  webhook/delta processing, and provider delivery/bounce signals.
- Complete browser acceptance for the dashboard, channel control plane, email
  log, status filters, and local simulation warning.

No external transport or recipient delivery is claimed by this report.
