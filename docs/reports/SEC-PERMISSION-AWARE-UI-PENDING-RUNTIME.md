# SEC-PERMISSION-AWARE-UI — PENDING RUNTIME

## Local implementation

- Added a central route-to-permission registry shared by sidebar navigation and
  authenticated direct-route handling.
- Removed UI access decisions based on built-in role names. Custom roles and
  multiple assigned roles now use the session's effective permission union.
- Added an accessible access-denied state for non-entitled direct URLs.
- Permission-gated Administration tabs and every eager/detail query by the
  exact backend read capability; separated user creation, user update, role
  management, settings update, session revocation, and MFA reset actions.
- Limited tenant fleet and tenant provisioning UI to SaaS Root, matching the
  backend's root-only check, while retaining tenant profile access for entitled
  organization roles.
- Removed the incorrect assumption that `admin.users.update` grants session
  revocation; the UI now requires `security.sessions.manage`, as the API does.
- Permission-gated the Dashboard's tickets, assets, SLA, knowledge,
  notifications, email-log, administration, analytics, and AI provider queries.
- Permission-gated Dashboard metrics, operational sections, and quick actions
  so unavailable data is not represented as a legitimate zero.
- Added an explicit limited-workspace explanation for active users whose roles
  contain no dashboard-readable capabilities.
- Replaced privileged role-name checks in change governance, release
  governance, SLA management, Event Operations, and Ticket Operations with
  exact effective-permission checks.
- Split Event Operations into independent ticket-event, monitoring connector,
  webhook receipt, receipt-reprocess, and integration-policy query/action
  boundaries so narrow monitoring roles do not trigger unrelated 403s.
- Removed the unsafe inheritance from generic `tickets.read/update`: normalized
  event/group visibility now requires `monitoring.events.read`, acknowledgement
  and escalation require `monitoring.events.manage`, and requester denial has a
  backend regression.
- Added dedicated `major_incidents.read/manage` boundaries across API, routing,
  queries, declarations, participants, communications, lifecycle, linked
  tickets, corrective actions, and PIR. A read-only observer sees evidence
  without mutation controls; requester denial has a backend regression.
- Split Ticket Operations across ticket create/update/comment/assign/bulk,
  CMDB, KEDB, AI suggestion, and Knowledge permissions. Unauthorized optional
  queries and controls are no longer rendered or requested.
- Changed backend ticket queue-management authority from built-in role names to
  the effective `tickets.assign` permission and added a custom-role regression.
- Replaced requester/agent role-name ticket visibility with composable
  `tickets.scope.all`, `tickets.scope.assigned`, and
  `tickets.scope.requester`; added `tickets.self_assign`, fail-closed unscoped
  reads, scope-aware internal comments/transitions/bulk actions, and multi-role
  union regressions. Frontend queues and quick actions use the same scopes.
- Centralized Ticket visibility in backend RBAC and reused it for Tickets,
  AI suggestions, permission-aware RAG, and CMDB impact so optional consumers
  cannot drift back to built-in role branches.
- Added fail-closed `requests.scope.all/requester`, implied all-queue scope for
  manage/fulfill/approve, scope-aware internal activity/comments, permission-
  based approval override, matching frontend routing, and custom-role
  regressions.
- Removed redundant manager/admin/agent role gates from Asset APIs. Exact
  update/verify/assign/move/dispose/restore permissions now work for custom
  roles, with a focused regression.
- Permission-gated optional Ticket, Asset, and Change pickers in Change/Problem
  creation so cross-module data is neither requested nor shown without its read
  capability.
- Permission-gated request comments, System Diagnostics AI configuration, and
  Copilot ticket/provider requests. AI-entitled operators may read safe
  provider execution metadata without receiving provider credentials.
- Corrected AI governance version loading so it cannot run without
  `ai.governance.read`.
- Split Automation into exact workflow, rule, run, log, runbook, execution,
  approval, suggestion, ticket-context, dry-run, run, retry, and decision
  boundaries. Tabs, queries, and actions now derive from the same effective
  capability set.
- Split Integrations into control-plane, legacy local-demo, analytics, job,
  webhook, event, mapping, health-check, and mutation boundaries. Narrow
  `integrations.*` roles can discover secret-safe runtime capabilities without
  gaining configuration authority.
- Split Analytics into executive, ticket, SLA, asset, knowledge, AI, security,
  automation, report read/create/export boundaries; report-only users can enter
  without receiving unrelated analytics requests.
- Required exact Identity Provisioning read access for entry and independently
  gated connector management, user visibility, role mappings, and offboarding.
- Split Notifications into notification read/update, preference update, template
  read/update, email-log read, and failed-email retry boundaries.
- Separated `admin.configuration.read` from raw `admin.settings.read/update`;
  Configuration Center neither requests nor renders for a non-entitled user.
- Kept backend permission enforcement authoritative; the UI controls are
  defense-in-depth and request minimization, not a replacement authorization
  boundary.
- Added static enforcement through
  `scripts/validate_permission_aware_ui.py` and release control
  `SEC-PERMISSION-AWARE-UI`.

## Local evidence

- TypeScript no-emit: pass.
- Accessibility source audit: pass.
- Permission-aware UI contract: pass.
- Existing backend regression confirms that multiple roles produce an effective
  permission union.
- Backend regressions cover permission-based custom ticket dispatch,
  fail-closed/composable ticket visibility scopes, and provider-status access
  for an AI-entitled operator.
- No schema migration was required; the Alembic head remains
  `20260814_0073`.

## Deferred runtime gate

Status: `IMPLEMENTATION_COMPLETE_RUNTIME_GATE_PENDING`.

Runtime acceptance requires:

1. requester, agent, manager, organization administrator, and security officer
   browser sessions;
2. one tenant custom role with a narrow read capability;
3. custom requester-scope, assigned/self-assign-scope, all-scope, and deliberately
   unscoped Ticket roles;
4. equivalent requester/all/unscoped Service Request roles and a fulfiller whose
   all-scope is implied by its operation permission;
5. custom Asset editor and verifier roles;
6. one user whose effective permissions come from two assigned roles;
7. allowed/hidden sidebar evidence for each persona;
8. allowed and denied direct-URL evidence;
9. browser network evidence showing no known unauthorized Dashboard requests;
10. Automation, Integrations, Analytics, Identity, Notifications, and
   Configuration Center tab/query/action matrices for narrow roles;
11. Event Operations and Major Incident read/manage matrices, including requester
   direct-URL and API denial;
12. matching backend 403 responses for bypass attempts;
13. desktop/mobile and keyboard/screen-reader checks for the denied state.

Production UI authorization is not claimed until this matrix is executed
against the target server and approved by Application Security.
