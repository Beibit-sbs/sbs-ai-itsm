# CMDB schema and relationship runbook

## Scope

This runbook covers CI classes, inherited attributes, identity rules, class
lifecycle, directional relationship types, cardinality, cycle protection,
service topology, and safe schema evolution.

## Change a CI class

1. Identify class owner, business purpose, parent class, matching identity, and
   affected sources.
2. Review inherited and local attributes for key collisions, type changes,
   required/default semantics, sensitivity, and search/index requirements.
3. Preview affected CIs, reconciliation rules, imports, forms, relationships,
   impact analysis, and reports.
4. Add a new attribute/version. Do not reinterpret historical values in place.
5. Backfill through a governed reconciliation/import run with dry-run evidence.
6. Require explicit approval before making an optional attribute required.
7. Retire unused attributes only after dependency analysis; retain historical
   snapshots and audit evidence.

Safe default: an invalid class or attribute definition cannot activate.

## Change a relationship type

1. Define source/target class constraints, direction, inverse label, cardinality,
   ownership, and whether cycles are permitted.
2. Preview current links that would violate the new rule.
3. Prove self-link, prohibited cycle, cardinality, and cross-tenant attempts fail.
4. Activate the new version and create/retire links only through governed APIs.
5. Rebuild or invalidate bounded topology/impact caches.
6. Verify both endpoint histories and the relationship audit record.

Do not reverse a relationship by changing labels only. Create a new governed
type/version and migrate links with explicit evidence.

## Service model validation

- Every production application/technical service has an accountable owner.
- Business services reach their supporting applications/infrastructure through
  approved directional relationships.
- Critical CIs have environment, lifecycle, ownership, and service context.
- Traversal enforces tenant, depth, node, and edge caps.
- Shared/global schema is immutable to tenant administrators.

## Troubleshooting

CI cannot be created:

- inspect class activation, required attributes, allowed values, identity rule,
  and tenant scope;
- do not weaken identity or required fields to force ingestion.

Relationship cannot be created:

- inspect endpoint classes, tenant scope, cardinality, duplicate/self-link, and
  cycle diagnostics;
- use the topology preview before changing rules.

Topology is incomplete:

- verify direction and active relationship versions;
- inspect reconciliation/quality findings and cache source hash;
- refresh through the bounded API, not direct cache deletion.

## Rollback

- Disable a new schema/relationship version and reactivate the last approved
  compatible version.
- Reverse data migration only from an immutable preview/apply manifest.
- Never delete CI, relationship, impact, change, incident, or audit history to
  make a rollback pass.

## Evidence

Record definition/version hashes, owners, preview counts, incompatible rows,
approval, apply manifest, topology before/after, cache invalidation, tenant
negative tests, and rollback decision.
