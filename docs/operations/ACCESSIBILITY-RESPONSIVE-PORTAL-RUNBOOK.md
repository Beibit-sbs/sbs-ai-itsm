# Accessibility and responsive portal runbook

## Purpose

This runbook defines the accessibility baseline for the SBS AI ITSM web
client. The implementation targets WCAG 2.2 AA for the core operator and
requester journeys, but conformance is not declared until the deferred
browser and assistive-technology acceptance gate is executed.

The baseline covers:

- application navigation and route changes;
- global search and keyboard shortcuts;
- ticket list, ticket creation, ticket details, and guarded bulk actions;
- requester catalog and service-request tracking;
- administrative, asset, knowledge, identity, and email dialogs;
- narrow/mobile layouts, touch targets, zoom/reflow, reduced motion, and
  forced-colors behavior.

## Keyboard contract

| Context | Required behavior |
|---|---|
| Application | The first Tab exposes “Перейти к основному содержимому” |
| Route change | Focus moves to the page heading and the title is announced |
| Mobile navigation | Menu exposes expanded state, traps focus, closes with Escape, and restores focus |
| Global search | `Ctrl/Cmd+K` or `/` opens; arrows move; Enter opens; Escape closes |
| Dialog | Focus enters the dialog, Tab/Shift+Tab remain inside, Escape closes, prior focus is restored |
| Ticket bulk action | Confirmation field receives initial focus; execute stays disabled until the exact phrase is entered |

Keyboard behavior must not bypass authorization, server validation, or the
guarded bulk-action confirmation.

## Screen-reader and semantic contract

- The document language is Russian (`lang="ru"`).
- The application has an explicit main landmark and labeled navigation.
- Every visual modal has `role="dialog"`, `aria-modal`, an accessible name,
  and programmatic focus management.
- Loading states use polite status regions where an update is meaningful.
- Failures and validation errors use alert regions.
- Result selection in global search uses listbox/option semantics and
  `aria-activedescendant`.
- Data tables in the core ticket workflow have hidden captions.
- Toggle/filter buttons expose pressed or expanded state.
- Decorative modal backdrops are presentational.

Do not put credentials, sensitive AI prompts, requester descriptions, or raw
server errors into live regions.

## Responsive and mobile behavior

- At 950 px and below, the persistent sidebar becomes a focus-managed drawer.
- At 600 px and below, page actions reflow, user decoration is hidden, ticket
  tables scroll horizontally, and dialogs become bottom sheets.
- At 850 px and below, the requester request list and detail view stack; when
  a request is selected, its detail heading receives focus and the panel
  scrolls into view.
- Coarse-pointer controls have a minimum 44 px target height.
- Dialog height is bounded by the dynamic viewport and content remains
  scrollable.

Acceptance must include 200% browser zoom and a 320 CSS-pixel viewport. No
information or action may require two-dimensional page scrolling; a bounded
data-table region may scroll horizontally.

## Motion, contrast, and system modes

The stylesheet:

- disables non-essential transitions, animations, and smooth scrolling when
  `prefers-reduced-motion: reduce` is active;
- supplies visible `:focus-visible` treatment;
- retains explicit borders and focus indicators in forced-colors mode;
- uses audited foreground/background pairs with at least 4.5:1 contrast for
  normal text represented in the static palette check.

Static palette checks are a regression guard, not a substitute for rendered
contrast inspection, state inspection, or non-text contrast validation.

## Local static gate

From `frontend`:

```powershell
$node = 'C:\Users\bsaua\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe'
& $node node_modules\typescript\bin\tsc --noEmit
& $node scripts\accessibility-audit.mjs
```

The audit fails when the application loses its language, skip link, main
target, route announcement, mobile expanded state, global focus treatment,
reduced-motion or forced-colors rules, core dialog focus management, ticket
table caption, announced ticket error, dialog names, image alternatives, or
presentational modal backdrops. It also calculates the maintained contrast
pairs.

## Deferred runtime acceptance

When browser/runtime access is restored, test at minimum:

1. Requester: sign in, open catalog, submit a service request, open request
   details, add a comment, and open an incident.
2. Agent: open global search entirely by keyboard, open a result, create and
   edit an incident, and cancel/complete the guarded bulk dialog.
3. Organization Admin: open and close each administration overlay without a
   mouse and verify focus restoration.
4. Run axe-core (or equivalent) on login, tickets, catalog, requests, search,
   and administration.
5. Repeat the journeys with NVDA + Chrome or Edge on Windows.
6. Inspect 320 px, 400% text spacing where applicable, 200% zoom, Windows
   High Contrast, and reduced motion.
7. Confirm no keyboard trap exists outside an intentionally open dialog.

Record browser, assistive technology, versions, role, tenant, viewport,
violations, evidence, and remediation. Until this matrix passes, retain
`implementation_complete_runtime_gate_pending`.

