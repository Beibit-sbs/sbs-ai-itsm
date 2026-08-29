# UX-005 — Embedded administration guidance

**Status:** implementation complete; runtime acceptance gate pending  
**Date:** 2026-07-29  
**Migration:** none; additive typed API and UI

## Delivered

- Extended the Unified Configuration Center from summary cards into a
  role-aware operator guidance layer.
- Added live checklists for typed settings, global AI provider safety, tenant
  AI governance, branding/translations, email/Teams, monitoring/integrations,
  identity lifecycle, and privileged MFA.
- Added explicit `PASS`, `INFO`, `WARNING`, `ACTION_REQUIRED`, and
  `NOT_APPLICABLE` states with applicability-aware readiness denominators.
- Corrected false readiness assumptions: Teams remains optional until selected,
  provisioning remains not applicable while external identity is disabled,
  disabled tenant AI does not demand policy/budget/action controls, and
  disabled email does not demand a production channel.
- Made local safe defaults explicit: mock AI/email, fail-closed AI actions,
  source-language translation fallback, inactive event intake, local identity,
  and staged MFA enforcement are visible rather than silently reported ready.
- Added exact remediation routes, required permissions, role ownership,
  specialized runbook references, audit navigation, and role-aware mutation
  labels.
- Added non-secret per-check evidence, deterministic check and domain SHA-256
  hashes, guide version, generated time, prioritized next actions, and typed
  OpenAPI response models.
- Added `private, no-store`, evidence-derived ETag, and guide-version response
  headers.
- Added responsive priority queue, filters with pressed-state semantics,
  expandable domain diagnostics, safe-default explanations, evidence fields,
  and narrow-screen layouts.
- Added tests-as-code for typed guidance, status vocabulary, evidence/runbook/
  permission completeness, secret minimization, response headers, deterministic
  hashes, role-aware actions, and cross-tenant denial.

## Static evidence

- Backend Ruff and compile checks: pass.
- TypeScript `tsc --noEmit`: pass.
- Accessibility baseline: pass over 71 source files, 16 named/focus-managed
  dialogs, two images with alternatives, 37 alert/status regions, and eight
  maintained contrast pairs.
- Typed OpenAPI schema for the Configuration Center: generated.
- No migration was added; the single Alembic head remains `20260729_0064`.

## Deferred runtime acceptance

No pytest, production bundle, live PostgreSQL query profile, browser,
assistive-technology, or production release claim is made under the blocked
runtime gate.

When runtime access returns:

1. run focused Configuration Center and full backend regression;
2. compare guidance for SaaS Root, Organization Admin, IT Manager, Security
   Officer, Knowledge Manager, and cross-tenant attempts;
3. change dependent settings and connectors and prove applicability transitions;
4. verify ETag changes only when evidence changes and that responses remain
   private/no-store;
5. inspect priority filtering, deep links, audit navigation, 320 px reflow,
   200% zoom, forced colors, keyboard, and screen reader behavior;
6. verify no secret-like value enters API responses, browser storage, logs, or
   screenshots.
