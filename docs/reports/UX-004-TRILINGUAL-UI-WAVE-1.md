# UX-004 — Trilingual application UI, wave 1

**Status:** wave 1 complete; full specialist-module coverage in progress  
**Date:** 2026-07-30  
**Locales:** `ru-RU`, `kk-KZ`, `en-US`

## Delivered

- Backend tenant-experience validation and capabilities now accept all three
  UI locales.
- A dependency-free, typed UI message catalog provides deterministic
  Russian, Kazakh, and English fallback-free strings.
- The selected language is persisted locally and applied to the document
  `lang` attribute.
- A language selector is available both in the authenticated application
  shell and on the login screen.
- Navigation groups and items, role labels, session context, logout/menu
  actions, page announcements, and all main module titles/subtitles are
  localized.
- Global search, API health, shared partial-data failures, and retry controls
  use the same catalog.
- The Major Incident Command Center static interface is fully migrated,
  including declaration, response team, linked tickets, communications,
  lifecycle evidence, corrective actions, timeline, PIR, and locale-aware
  date/time rendering.
- The tenant-experience editor clearly exposes the three organization-default
  UI languages with human-readable labels and locale codes.

## Acceptance evidence

- TypeScript: `tsc -p tsconfig.app.json --noEmit` — pass.
- Accessibility source baseline — pass over 75 source files, 16 dialogs,
  72 explicit alert/status regions, and eight maintained contrast pairs.
- Backend focused regression: `tests/test_tenant_experience.py` — `4 passed`.
- Direct backend validation accepted `ru-RU`, `kk-KZ`, and `en-US`.
- Live manager-role browser:
  - Russian, Kazakh, and English navigation and Major Incident chrome verified;
  - the document language changed to `ru`, `kk`, and `en`;
  - the selected locale survived a page reload;
  - global search changed to English;
  - the final visible preference was restored to Russian.

## Active completion queue

1. Migrate shared field/status/action dictionaries and server business enums.
2. Translate high-use operational modules: Dashboard, Tickets, Requests,
   Catalog, Assets, SLA, Changes, Problems, and Knowledge.
3. Translate governance/integration modules and Administration.
4. Localize backend validation and notification/error payloads without
   weakening stable machine-readable error codes.
5. Add per-locale tenant terminology overrides and server-persisted user
   language preferences.
6. Run requester, agent, manager, organization-admin, security, and root
   browser acceptance at desktop and narrow viewports.

This report does not claim the remaining specialist module bodies are already
translated. The shared foundation is production-oriented and the remaining
work is explicitly tracked rather than hidden behind mixed-language screens.
