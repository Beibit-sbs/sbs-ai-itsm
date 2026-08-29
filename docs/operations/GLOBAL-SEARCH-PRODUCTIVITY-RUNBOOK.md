# Global Search and Guarded Bulk Productivity runbook

## Purpose

The global search palette provides one keyboard-first entry point to records
the current user is already allowed to open. It is not an authorization
shortcut. The bulk workflow replaces browser-side update loops with a bounded,
server-owned preview and execute plan.

The implementation covers:

- incidents, service requests, knowledge, assets/CI, changes, problems, and
  users;
- personal and role-shared saved views;
- `Ctrl/Cmd+K` and `/` palette shortcuts, arrow navigation, Enter, Escape,
  focus restoration, and direct record opening;
- guarded incident bulk status/assignment with server preview, confirmation,
  state fingerprints, revalidation, atomic execution, audit, and idempotent
  replay.

## Access boundary

Global search first requires `search.use`, then independently checks the
domain permission for every selected entity:

| Entity | Domain permission | Additional object scope |
|---|---|---|
| Incident | `tickets.read` | requester owns it; agent owns it or it is unassigned |
| Service request | `requests.read` | requester owns it |
| Knowledge | `knowledge.read` | non-managers see published public/internal only |
| Asset/CI | `assets.read` | tenant |
| Change | `changes.read` | tenant |
| Problem | `problems.read` | tenant |
| User | `admin.users.read` | tenant |

SaaS Root can search across tenants. Every result still carries its tenant ID,
and a bulk plan may contain records from only one tenant.

Search responses intentionally contain only identifier, title, short
operational subtitle, status, destination, update time, score, and matched
field names. Descriptions, article content, requester email, credentials, and
raw snippets are never returned by this endpoint.

## Query and performance limits

- Query length: 2–100 characters.
- Entity types: fixed server allowlist.
- Per-type limit: 1–20.
- Total result limit: 1–100.
- Candidate window: at most 100 per entity type.
- SQL wildcard characters are escaped and treated literally.

PostgreSQL migration `0062` enables `pg_trgm` and creates seven composite GIN
search-document indexes. SQLite keeps the portable bounded fallback used for
local test execution. Before a production migration, ensure the database
migration owner can install or already owns the `pg_trgm` extension.

The query audit event stores only lowercased query SHA-256, selected types,
result counts, total, and duration. It never stores the raw query.

## Saved views

`search.views.manage` allows a user to create up to 50 owned views. A view
stores only normalized query and allowed entity types. Name uniqueness is
enforced per owner and tenant.

`search.views.share` allows a view owner to share with explicit role codes
that exist in the same tenant. Organization Admin, IT Manager, and Knowledge
Manager receive this permission by default. Shared recipients can apply the
view but cannot edit or delete it.

Updates require `expected_revision`; stale writes return `409`. Audit events
contain query hash, revision, sharing state, and role codes, not raw query
text.

## Guarded ticket bulk procedure

1. Select no more than 50 incidents.
2. Choose a target status and optional assignee/comment.
3. Request server preview.
4. Review every admitted and excluded target, expiry, operation hash, and
   target hash.
5. Type the exact phrase `APPLY N`.
6. Execute before the ten-minute expiry.

Preview requires `tickets.read`, `tickets.update`, and
`tickets.bulk.execute`. Assignment also requires `tickets.assign` and queue
management scope.

The server:

- deduplicates IDs and rejects mixed-tenant plans;
- applies requester/agent/object scope;
- validates assignee activity and tenant;
- evaluates the effective transition after assignment;
- fingerprints status, assignee, tenant, and update timestamp;
- persists immutable operation/target SHA-256 evidence;
- binds the plan to its creator and optimistic revision.

Execute locks the plan and all targets, verifies stored evidence integrity,
rechecks every permission, target fingerprint, assignee, and transition, then
executes all targets in one transaction. Any target drift rejects the entire
plan; no unaffected target is changed. Successful replay returns the prior
result without applying changes again.

## Failure handling

- `403`: permission or queue-management scope is missing.
- `409 Revision conflict`: reload and create a new preview.
- `409 Bulk plan expired`: create a new preview.
- `409 Ticket state changed after preview`: review the listed drift targets
  and create a new preview.
- `422`: invalid target status, assignee, confirmation phrase, mixed tenant,
  or more than 50 targets.

Never retry a failed plan by looping over individual ticket endpoints. Generate
a fresh preview so the complete set is evaluated atomically.

## Audit evidence

Search and saved view events:

- `global_search.executed`
- `global_search.view_created`
- `global_search.view_updated`
- `global_search.view_deleted`

Bulk events:

- `ticket.bulk_previewed`
- `ticket.bulk_execute_denied_drift`
- `ticket.bulk_item_executed`
- `ticket.bulk_executed`

Use operation and target hashes to correlate preview, item events, and final
execution without exposing comments or search text in audit metadata.
