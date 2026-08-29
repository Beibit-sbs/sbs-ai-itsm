# CMDB data quality and certification runbook

## Purpose

Use this runbook to measure CMDB trustworthiness, manage remediation work, and
retain evidence that accountable owners periodically certified critical CIs.

## Quality dimensions

- **Completeness:** required ownership, support, and physical-location data.
- **Correctness:** governed schema, valid owner, and consistent lifecycle.
- **Freshness:** recent CI observation and healthy active ingestion sources.
- **Duplicates:** unresolved reconciliation duplicate candidates.
- **Orphans / connectivity:** service-model CIs connected to the dependency
  graph.

Each dimension is scored from 0 to 100. The overall index uses:

- completeness: 30%;
- correctness: 20%;
- freshness: 20%;
- duplicates: 15%;
- connectivity: 15%.

A waiver records an accepted risk but does not improve the data score.

## Quality scan workflow

1. Open **Активы → Качество CMDB**.
2. Select the organization when operating as SaaS Root.
3. Run **quality scan**.
4. Confirm the snapshot integrity indicator is valid.
5. Review critical, overdue, and unassigned findings first.
6. Assign every open finding to an accountable tenant user.
7. Correct the source CI or ingestion policy; do not merely close the finding.
8. Run another scan. A corrected defect closes automatically with an
   automatic-resolution note.
9. Use `WAIVED` only with a documented, time-bounded risk justification.

Repeated scans update the same finding identity and occurrence count. A
previously resolved defect reopens if it returns. Tenant advisory locking
prevents simultaneous scans from producing duplicate queue items.

## Default remediation targets

- critical: 2 days;
- high: 7 days;
- medium: 14 days;
- low: 30 days.

Operators may change a due date through the API when a documented policy
requires a different target. Overdue open/in-progress findings are highlighted
in the workspace and summary.

## Certification campaign workflow

1. Define a bounded scope by explicit CI, class, criticality, environment,
   lifecycle, or missing owner.
2. Set a future due date and optional default certifier.
3. Create the campaign as `DRAFT`.
4. Review scope, then activate. Activation creates one immutable item for each
   CI, recording its `ci_version`, canonical snapshot, and SHA-256 hash.
5. The assigned owner/default certifier reviews source, owner, support,
   lifecycle, criticality, environment, location, and dependency scope.
6. Choose:
   - `CERTIFIED` with evidence when the snapshot is correct;
   - `REJECTED` with a concrete defect description.
7. A changed CI or invalid snapshot hash blocks certification. Start a new
   campaign/snapshot after correcting scope.
8. A rejection automatically creates a certification remediation finding.
9. Complete the campaign only when no items remain pending. Rejected items may
   remain as tracked findings.

## Integrity incident

If `integrity_valid=false`:

1. do not certify or use the snapshot as evidence;
2. preserve the record and audit chain;
3. record the database, host, user, correlation ID, and time;
4. notify security and database operations;
5. verify audit-chain integrity and database access logs;
6. create a new campaign only after the incident is contained.

## API reference

- `GET /api/v1/cmdb/quality/summary`
- `POST /api/v1/cmdb/quality/scan`
- `GET /api/v1/cmdb/quality/findings`
- `PATCH /api/v1/cmdb/quality/findings/{finding_id}`
- `GET|POST /api/v1/cmdb/quality/campaigns`
- `GET /api/v1/cmdb/quality/campaigns/{campaign_id}`
- `POST /api/v1/cmdb/quality/campaigns/{campaign_id}/activate`
- `POST /api/v1/cmdb/quality/campaigns/{campaign_id}/items/{item_id}/decision`
- `POST /api/v1/cmdb/quality/campaigns/{campaign_id}/complete`
- `POST /api/v1/cmdb/quality/campaigns/{campaign_id}/cancel`

All calls are tenant scoped. SaaS Root must provide `tenant_id` for summary,
scan, findings, and campaign list/create operations.
