# PERMISSION-AWARE UI RUNBOOK

## Purpose

Keep the visible workspace aligned with the effective union of a user's assigned
roles. The frontend reduces confusion and avoids known unauthorized requests;
FastAPI permission checks remain the authoritative security boundary.

## Access model

- `frontend/src/auth/accessControl.ts` is the single route-access registry used
  by both sidebar navigation and authenticated direct-route handling.
- Exact permissions grant module access where one read capability is sufficient.
- A route may accept a small explicit set of read capabilities when it hosts
  independent workspaces, such as Analytics/Reports or Notifications/Templates.
  A permission prefix is used only where every matching capability safely grants
  entry to the same control plane.
- `saas_root` retains platform-wide access.
- Custom role codes are not special-cased. Access comes from the permission
  array returned in the authenticated session.
- Multiple assigned roles are resolved by the backend into one effective
  permission union before the UI evaluates access.
- Administration additionally separates read, create, update, and manage
  capabilities for users, roles, permission catalog, settings, audit, login
  events, sessions, MFA, and organization scope. Internal tabs and requests are
  hidden or disabled independently.
- Change, release, SLA, event, request, and ticket consoles use operation-level
  permissions rather than privileged role-name lists.
- Event Operations independently gates ticket correlation, monitoring
  connectors, webhook receipts, receipt reprocessing, and integration policy
  management.
- Tenant-wide normalized events and correlation groups require
  `monitoring.events.read`; acknowledgement and escalation evaluation require
  `monitoring.events.manage`. Ordinary `tickets.read/update` never grants Event
  Operations access.
- Major Incident Command Center requires `major_incidents.read`; declarations,
  participants, communications, lifecycle, linked tickets, corrective actions,
  and PIR changes additionally require `major_incidents.manage`.
- Ticket Operations independently gates create, update, comments, assignment,
  bulk execution, CMDB, Known Error, AI suggestion, and Knowledge actions.
- Ticket record visibility is explicit and composable:
  `tickets.scope.all` reads the tenant queue, `tickets.scope.assigned` reads the
  current assignee plus unassigned queue, and `tickets.scope.requester` reads
  the current requester's records. `tickets.assign` implies all-queue scope;
  `tickets.self_assign` implies assigned/unassigned scope. `tickets.read`
  without any visibility scope returns no ticket records and cannot open the
  Tickets workspace.
- Service Request visibility follows the same fail-closed model:
  `requests.scope.all` reads the tenant queue and
  `requests.scope.requester` reads the current requester's records. Manage,
  fulfill, and approve capabilities imply all-queue scope; bare
  `requests.read` returns no records and cannot enter the Requests workspace.
- AI suggestions, permission-aware RAG, and CMDB ticket-impact checks reuse the
  central Ticket visibility evaluator; they cannot reintroduce role-name-based
  ticket access.
- Asset read/update/verify/assign/move/dispose/restore authorization is derived
  only from the corresponding effective permissions. Custom Asset roles behave
  like system roles with the same permission set.
- Change and Problem creation load optional Ticket, Asset, and RFC pickers only
  when the actor can read the referenced module; unavailable relationships are
  omitted instead of generating background 403 responses.
- System Diagnostics exposes provider configuration only to
  `admin.settings.read`; editing and provider tests require
  `admin.settings.update`.
- AI-entitled operators may read non-secret provider execution status, while
  provider credentials and configuration remain inside the admin settings
  boundary.
- Automation independently gates production workflow, rule, execution, runbook,
  approval, template, ticket-context, dry-run, run, retry, and decision
  capabilities. A visible tab never authorizes its mutations by itself.
- Integrations independently gates control-plane read, legacy local-demo access,
  analytics, jobs, webhooks, events, mappings, health checks, and mutations.
  Safe runtime capability discovery accepts narrow effective
  `integrations.*` roles without exposing credentials.
- Analytics exposes only entitled executive, ticket, SLA, asset, knowledge, AI,
  security, automation, and report workspaces. Report creation/export remains
  separate from report read.
- Identity Provisioning requires `identity.provisioning.read` for entry, then
  independently checks connector management, role-catalog read, and user read
  before configuration, mapping, or offboarding actions.
- Notifications separates notification read/update, preference update, template
  read/update, email-log read, and failed-email retry.
- Configuration Center does not load or render without
  `admin.configuration.read`; raw platform settings continue to require
  `admin.settings.read/update`.

## Operator procedure

1. In `Administration -> Users`, select the organization and open the user.
2. Assign one or more tenant roles. Keep the least-privilege role first when it
   should be displayed as the primary role label.
3. Save and have the user refresh or sign in again so the access token/session
   contains the current effective permissions.
4. Confirm the sidebar contains only entitled modules.
5. Try one entitled direct URL and one non-entitled direct URL. The latter must
   show `Недостаточно прав` without loading the module.
6. Open Dashboard and confirm it does not issue or display metrics for modules
   outside the user's permissions.
7. Open Administration with a narrow custom role. Confirm internal tabs,
   detail panels, and mutation buttons match its exact read/manage permissions.
8. Open Tickets and Event Operations with narrow custom roles. Confirm that
   each visible query, tab, and action matches the exact backend permission.
9. Test three custom Ticket roles: read + requester scope, read/update +
   assigned scope/self-assign, and read + all scope. Also test a bare
   `tickets.read` role; it must not enter the workspace or receive records.
10. Repeat the scope matrix for Service Requests: requester scope, all scope,
    fulfiller/approver implied all scope, and a deliberately unscoped reader.
11. Verify a custom Asset editor and verifier can perform exactly the operations
    granted by `assets.update` and `assets.verify`, without a system role code.
12. Sign in as requester and verify direct `/events` and `/major-incidents`
    navigation is denied and both APIs return 403. Then verify read-only and
    manage custom roles for each operational console.
13. Open System Diagnostics with `security.audit.read` but without
   `admin.settings.read`. Diagnostics must load and AI configuration must remain
   absent.
14. Exercise Automation, Integrations, Analytics, Identity, and Notifications
    with narrow roles. Confirm unavailable tabs issue no requests and each
    mutation remains hidden or disabled without its exact action permission.
15. Open Administration with `admin.configuration.read` but without
    `admin.settings.read`. Configuration Center may load; raw settings and AI
    provider controls must remain absent.
16. In `Roles and permissions`, search by business name or technical code,
    review the scope explanation, and use module-level select/clear only for the
    intended domain. Saving `tickets.read` or `requests.read` without an
    applicable record-visibility scope must be blocked in the UI and return
    backend `422` if submitted directly.
17. Review API/audit telemetry. A frontend access defect must never turn a
    backend 403 into data disclosure.

## Validation

Run:

```text
python scripts/validate_permission_aware_ui.py
```

The consolidated local gate must also include the validator, TypeScript, and
accessibility checks:

```text
python scripts/run_local_release_gate.py --python <python> --node <node> --docker <docker> --git <git>
```

When a trusted Ruff executable is already known to be blocked by host policy,
add `--record-ruff-blocked`. The gate will still fail, retain the blocker in
evidence, and complete all non-lint checks.

## Troubleshooting

- Missing menu after a role update: refresh the session and inspect the
  authenticated `permissions` array; do not add role-name exceptions.
- Menu visible but API returns 403: compare the central route requirement with
  the first protected page endpoint and the backend permission. Tighten the UI
  requirement; never weaken the API check to fit the menu.
- Valid custom role denied: verify its permissions are tenant-scoped and included
  in the effective union regression before changing the central registry.
- Dashboard shows misleading zero values: confirm its query and section are both
  guarded by the corresponding read capability.
- A custom dispatcher cannot assign tickets: verify `tickets.assign` is in the
  effective union. Queue-management authority is permission-based; assigning a
  built-in role name without that permission must not grant the action.
- A custom Ticket role sees an empty or denied workspace: add exactly one
  visibility scope appropriate to the role. Do not grant `tickets.scope.all`
  merely to remove the empty state.
- A role update returns `422 visibility scope`: keep the read permission and add
  the least-privilege requester/assigned scope, or remove read. The backend
  rejects inconsistent role definitions atomically.

## Runtime acceptance

Before production sign-off, exercise requester, agent, manager, organization
administrator, security officer, a read-only custom role, and a multi-role user.
Retain screenshots/network evidence for allowed navigation, denied direct URLs,
absence of unauthorized Dashboard and composite-console requests, mutation
boundaries, Configuration Center/settings separation, and matching backend 403
behavior.
