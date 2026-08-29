# Email delivery integrity runbook

## Purpose

Keep local email simulation visibly separate from production transport
acceptance and delivery. `SIMULATED` means the platform rendered and retained a
local preview only. It does not mean that Microsoft Graph, an SMTP relay, a
mailbox, or a recipient accepted the message.

## Invariants

- `MOCK` channels can be created, tested, or activated only while
  `DEMO_MODE=true`.
- A mock message has status `SIMULATED`, no provider message ID, no
  `accepted_at`, `sent_at`, or `delivered_at`, and zero delivery attempts.
- Mock processing never increments channel success counters or sets
  `last_success_at`.
- A mock connection test returns `ok=false` and `status=SIMULATED`.
- Inbound synchronization is Microsoft Graph-only; mock synchronization cannot
  return a successful empty result.
- Simulated messages are terminal previews and cannot enter the retry queue.
- Dashboard health is `SIMULATED`, never `HEALTHY`, when only a mock channel is
  active.

## Local verification

```powershell
python scripts/validate_email_delivery_integrity.py
python scripts/validate_prg006_contract.py
python scripts/validate_m1_release_gate.py
```

Inspect the email operations dashboard and email log:

1. A local mock channel is labelled simulation-only.
2. Its test email appears as `SIMULATED`.
3. Transport timestamps and provider message ID are empty.
4. Production-success counters remain unchanged.
5. With `DEMO_MODE=false`, mock creation, testing, and activation return HTTP
   410.

## Production acceptance

1. Apply migrations through `20260729_0071`.
2. Require `DEMO_MODE=false`.
3. Confirm no active `MOCK` channel is used for business notifications.
4. Configure Microsoft Graph and run the governed connection test.
5. Send a test message and retain the Graph request ID and `ACCEPTED` event.
6. If provider delivery signals are available, retain the separate
   `DELIVERED`, `BOUNCED`, or complaint event.
7. Confirm the dashboard counts simulations separately from accepted delivery.

## Incident response

Treat any mock-linked `SENT`, `ACCEPTED`, `DELIVERED`, transport timestamp,
provider message ID, channel success increment, or `HEALTHY` readiness as
invalid evidence. Pause the channel, preserve the audit/email records, apply
the reclassification migration, rerun the integrity validator, and investigate
which code path wrote the false success before restoring production email.
