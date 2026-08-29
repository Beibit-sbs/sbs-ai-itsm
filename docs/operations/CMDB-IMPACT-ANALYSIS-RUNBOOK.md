# CMDB impact analysis runbook

## Purpose

Use CMDB impact analysis to understand which services, customers, and changes
may be affected by a CI or operational record. A calculated result is an
inference from the current CMDB graph, not a substitute for operator
validation.

## Direction semantics

- `UPSTREAM`: start at a failed or changed CI and follow dependencies toward
  consuming applications and services.
- `DOWNSTREAM`: start at a service/application and follow what it depends on.
- `BOTH`: investigate the connected dependency area in both directions.

For a typical service chain:

`Business Service -> Technical Service -> Application -> Infrastructure`

an upstream calculation from Infrastructure reaches the application,
technical service, and business service.

## Operator workflow

1. Confirm the record has at least one linked CI.
2. Open **Влияние** or **Blast radius** in the CI, Ticket, Problem, or Change
   card.
3. Select direction and maximum depth. Five levels upstream is the normal
   starting point for an infrastructure incident or Change.
4. Run the calculation.
5. Review:
   - inferred severity and reasons;
   - customer-impact warning;
   - impacted services and critical CIs;
   - production scope;
   - Change window/shared-scope collisions;
   - truncation warning.
6. For Ticket, Problem, or Change, save the assessment. It becomes the
   CURRENT immutable decision snapshot and supersedes the prior snapshot.
7. Recalculate whenever the UI reports a stale graph or stale process record.

## Change governance

Before CAB or ECAB:

- use `UPSTREAM` from all linked implementation CIs;
- investigate every `WINDOW_OVERLAP` collision;
- confirm whether every `SHARED_SCOPE` collision can safely run concurrently;
- validate critical/business service results with the service owner;
- retain the assessment hash in CAB evidence;
- recalculate after any Change scope or CMDB relationship update.

## Severity interpretation

- `LOW`: narrow scope with low-criticality CIs.
- `MEDIUM`: medium-criticality scope without stronger impact indicators.
- `HIGH`: business service, critical CI, or large production scope.
- `CRITICAL`: multiple critical CIs or an overlapping Change window.

Severity is deterministic and explainable through `severity_reasons`.
Business-service reachability sets `customer_impact=true`; it does not prove
that users are currently affected.

## Staleness and integrity

An assessment is stale when:

- `graph_is_stale`: CI or relationship revisions changed after calculation;
- `entity_is_stale`: the Change or Problem version changed, or the source
  entity is no longer available;
- `integrity_valid=false`: stored snapshot JSON no longer matches its
  SHA-256 hash.

Do not use a stale or integrity-invalid snapshot for an approval decision.
Recalculate stale assessments. Escalate an integrity failure to security and
database operations; preserve the audit trail and do not overwrite evidence.

## Cache behavior

Each root/direction/depth result is cached for 15 minutes. Cache entries are
accepted only if their graph hash matches the current tenant graph. A graph
revision invalidates old results automatically; manual cache deletion is not
required.

If traversal is slow:

1. inspect graph size and whether `BOTH`/depth 12 is necessary;
2. look for invalid dense relationship patterns;
3. check cache hit counts;
4. check PostgreSQL load and lock waits;
5. keep node limits enabled.

## Tenant and access controls

- All roots must belong to exactly the resolved tenant.
- A tenant user cannot request or retrieve another tenant's result.
- SaaS Root must provide tenant context for standalone CI previews.
- Entity assessments resolve tenant scope from the Ticket, Problem, or Change.
- Asset and process read permissions are both required.

## API examples

Preview from a CI:

```json
POST /api/v1/cmdb/impact/preview
{
  "root_ci_ids": ["<ci-id>"],
  "direction": "UPSTREAM",
  "max_depth": 5
}
```

Save a Change assessment:

```json
POST /api/v1/cmdb/impact/assessments/CHANGE/<change-id>
{
  "root_ci_ids": [],
  "direction": "UPSTREAM",
  "max_depth": 5,
  "expected_entity_version": 3
}
```

Linked Change/Problem/Ticket CIs are included automatically. Explicit roots
are additive and are always tenant validated.
