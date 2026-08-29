# UX-003 — Accessibility and responsive portal

**Status:** implementation complete; runtime accessibility gate pending  
**Date:** 2026-07-29  
**Database migration:** none

## Delivered

- Shared dialog focus-management hook with initial focus, Tab/Shift+Tab trap,
  Escape close, body-scroll lock, and previous-focus restoration.
- Focus management and accessible names across 16 visual dialogs in global
  search, tickets, catalog, assets, knowledge, administration, email logs,
  and identity provisioning.
- Skip link, explicit main and navigation landmarks, route-title live
  announcement, and programmatic page-heading focus.
- Responsive mobile navigation drawer with expanded state, labeled close
  backdrop, focus containment, Escape handling, and route-close behavior.
- Global-search listbox state hardened with entity-qualified option IDs;
  loading, save, and failure feedback are announced.
- Core ticket loading/error states are announced and both ticket tables have
  accessible captions.
- Requester catalog controls expose pressed state and announce loading,
  notices, validation, and network failures.
- Request-tracking list exposes selection state; detail loading, failures, and
  updates are announced; narrow-screen selection moves focus and scrolls the
  detail panel into view while honoring reduced motion.
- Login, identity, and email-operation failures are exposed as alerts.
- Mobile bottom-sheet dialogs, stable scroll regions, horizontal table
  containment, reflowed page actions, and 44 px coarse-pointer targets.
- Global visible focus, reduced-motion, and forced-colors safeguards.
- Dependency-free static accessibility gate with structural dialog/image/
  backdrop inventory and WCAG AA contrast calculations for maintained theme
  text pairs.

## Static acceptance

- TypeScript `tsc --noEmit` passed.
- Accessibility audit passed over 68 source files.
- Full backend Ruff and Python compile checks passed.
- Alembic reports one head: `20260729_0062`.
- Local and production Compose configurations parse successfully.
- `git diff --check` passed; Windows line-ending notices are informational.
- Audit inventory: 16 dialogs, zero potentially unnamed dialogs, zero dialogs
  without focus management, zero images missing alternatives, 28 explicit
  alert/status regions, and eight text contrast pairs at or above 4.5:1.
- The audit also locks the skip link, main target, route announcement, mobile
  expanded state, focus visibility, reduced motion, forced colors, guarded
  bulk dialog, catalog dialog, core ticket table name, and announced ticket
  loading failure.

The static gate does not establish WCAG conformance. Browser rendering,
axe-core, keyboard journeys, NVDA/Chrome or NVDA/Edge, 320 px reflow, 200%
zoom, Windows High Contrast, reduced motion, and multi-role acceptance remain
in the accumulated deferred runtime gate. No runtime or WCAG-conformance
claim is made.

## Next stage

`UX-004-BRANDING-LOCALIZATION`.
