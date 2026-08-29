# Policy canary evidence governance

## Purpose

This runbook governs metrics evidence used to apply, graduate, complete, or
automatically roll back runbook and autoremediation policy canaries. Telemetry
is a release decision input, so missing, simulated, nullable, or caller-routed
metrics must never be interpreted as healthy.

## Required lifecycle

Only SaaS Root can create a canary, submit metrics evidence, graduate it, or
complete it.

1. Approve the policy through the existing dual-control approval flow.
2. Record a pre-change baseline when applying the initial canary:
   error rate, p99 latency, throughput, source, and an evidence reference.
3. Observe the canary for the approved interval.
4. Submit current metrics with source and evidence reference.
5. Evaluate graduation. Missing baseline/current evidence, rollback state, or
   an unsafe error-rate change returns a blocking result.
6. Graduate only after a safe evaluation. The verified current evidence becomes
   the baseline for the next percentage and current evidence is cleared.
7. Repeat observation and evidence submission at every stage.
8. At 100%, complete only after another safe observation window.

The body identifiers must match route identifiers. Every mutation records actor,
source, evidence reference, values, stage, and decision in the audit chain.

## Evidence sources

Accepted source labels are `PROMETHEUS`, `CLOUDWATCH`, and
`MANUAL_EVIDENCE`. A manual reference must point to an immutable internal
evidence record, change ticket, or signed acceptance result. Do not paste
credentials or raw tokens.

Prometheus and CloudWatch destinations come only from deployment settings:

- `PROMETHEUS_URL`
- `PROMETHEUS_TIMEOUT_SECONDS`
- `CLOUDWATCH_REGION`
- `CLOUDWATCH_NAMESPACE`

API callers cannot provide a destination or region. Prometheus URLs reject
credentials, query strings, and fragments. Requests do not follow redirects,
label values are bounded, responses must contain exactly one finite,
non-negative aggregate, and failures return `503`.

The Prometheus collector expects these governed series:

- `sbs_policy_rollout_events_total{rollout_id,consumer,outcome}`
- `sbs_policy_rollout_duration_seconds_bucket{rollout_id,consumer,le}`

The target environment must emit and retain those series before Prometheus
evidence is approved.

## Missing evidence and migration

Migration `20260729_0068` invalidates metrics on every in-progress rollout
created before this governance boundary. Those values may have originated from
legacy simulated paths and cannot be trusted. The rollout record remains, but
fresh baseline/current evidence is required.

Scheduled evaluation never generates synthetic metrics. If current evidence is
missing, it reports the rollout as unpolled and leaves it unable to progress.
Missing evidence produces maximum risk confidence, not a safe score.

## Incident response

If a canary progressed using suspect evidence:

1. activate the consumer emergency brake;
2. stop further graduation and preserve audit/telemetry;
3. compare source evidence with the stored values and references;
4. roll back the policy when impact or provenance is uncertain;
5. invalidate affected evidence and restart from a fresh baseline;
6. open a security/release incident for destination manipulation, forged
   evidence, or unauthorized mutation.

## Acceptance

Run:

```powershell
python scripts/validate_canary_evidence.py
```

Runtime acceptance must prove unavailable/empty/malformed metrics return `503`,
non-root evidence mutation is denied, missing evidence blocks graduation and
completion, unsafe evidence triggers rollback, stage transition clears current
evidence, and every decision has an exact audit record.
