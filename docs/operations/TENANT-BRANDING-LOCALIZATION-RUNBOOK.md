# Tenant branding and localization runbook

## Purpose

The tenant experience control plane gives each organization a versioned,
audited visual identity and deterministic formatting policy without allowing
arbitrary CSS, HTML, JavaScript, or external tracking images.

Current scope:

- product and short names;
- immutable content-addressed PNG logo assets;
- primary, accent, surface, and text colors;
- Russian UI locale plus Russian, Kazakh, and English formatting locales;
- IANA timezone, currency, date style, hour cycle, and first day of week;
- controlled ITSM terms for incidents, service requests, assets, services,
  and the knowledge base;
- governed tenant translations for knowledge articles and notification
  templates;
- source SHA-256 binding, payload SHA-256 evidence, optimistic revisions,
  independent review, single-published-version enforcement, and stale fallback;
- optimistic revision, immutable history, integrity hashes, and rollback.

The application chrome remains fail-closed to `ru-RU`; the platform does not
pretend to provide a fully translated interface. Content variants can be
managed for `ru-RU`, `kk-KZ`, and `en-US`. Knowledge readers may request an
explicit supported locale. Notification rendering uses the tenant UI locale.

## Access model

| Permission | Default roles |
|---|---|
| `tenant.experience.read` | all standard tenant roles |
| `tenant.experience.manage` | Organization Admin |
| `tenant.experience.rollback` | Organization Admin |
| `tenant.translations.read` | Organization Admin, Knowledge Manager, IT Manager |
| `tenant.translations.manage` | Organization Admin, Knowledge Manager |
| `tenant.translations.publish` | Organization Admin, Knowledge Manager |

SaaS Root bypasses permission checks but must explicitly select a tenant for
mutation. A non-root request containing another tenant ID is rejected.

All authenticated users read the same current tenant profile, so requester and
operator surfaces remain consistent. Read responses are private-cacheable for
60 seconds and carry an ETag derived from the canonical profile snapshot.

## Change procedure

1. Open **Администрирование → Организация → Опыт организации**.
2. Review the current revision and hash prefix.
3. Change identity, palette, formats, timezone, or controlled terminology.
4. Review the live preview and draft contrast ratios.
5. Enter a reason of at least five characters.
6. Publish.

The server locks the current profile, compares `expected_revision`, validates
every field, preserves the current logo asset unless the logo endpoint is
used, increments the revision, stores a canonical snapshot and SHA-256, and
writes tamper-evident audit evidence. A stale editor receives `409`.

Change reasons are retained in restricted revision history. Audit metadata
stores only the reason SHA-256, not the reason text.

## Controlled translation procedure

1. Open **Администрирование → Организация → Переводы контента и уведомлений**.
2. SaaS Root explicitly selects an organization; tenant roles remain bound to
   their own organization.
3. Select knowledge or notification content, target locale, and a source.
4. Create a new immutable version number and edit its draft.
5. Save with the current optimistic `revision`.
6. Enter a submission note and send the draft to review.
7. A different user with `tenant.translations.publish` verifies terminology,
   placeholders, source currency, and payload integrity.
8. Approve to publish or reject with a review comment.

The creator or latest submitting editor cannot approve the version. PostgreSQL
and SQLite both enforce a partial unique index allowing only one `PUBLISHED`
variant for each tenant/resource/locale tuple. Publishing retires the former
published variant but preserves it as evidence.

Submission and review text is not copied into audit metadata. Audit stores a
SHA-256 digest; the restricted lifecycle record retains the review comment.

## Translation safety and runtime resolution

- resource types are restricted to knowledge articles and notification
  templates;
- locales are restricted to `ru-RU`, `kk-KZ`, and `en-US`;
- payload keys must exactly match the source schema;
- NUL bytes, script tags, JavaScript URLs, and inline event handlers fail
  closed;
- notification placeholders must exactly match the source placeholder set;
- every version binds to a canonical source SHA-256 and canonical payload
  SHA-256;
- source deletion, source edits, payload corruption, unsupported locales, or
  non-published states produce a safe source-language fallback;
- global knowledge and notification sources are inherited read-only by tenant
  administrators; tenant translations are overlays and never mutate them;
- tenant-specific notification templates take precedence over global
  templates before localized content resolution;
- no machine translation or external AI provider is in the rendering path.

Knowledge responses expose `content_locale`, `translation_version`, and
`translation_status`. `STALE_FALLBACK` is explicit evidence that a previously
published variant no longer matches its source. Notification rendering does
not emit stale content; it silently uses the current source template.

## Color safety

Only six-digit hexadecimal tokens are accepted. The server requires:

- text/surface contrast of at least 4.5:1;
- primary/surface contrast of at least 3:1;
- accent/surface contrast of at least 3:1.

Button foreground colors are derived from the higher-contrast dark or light
candidate. The client preview is advisory; server validation is authoritative.
No tenant-provided selector, declaration, stylesheet, markup, or executable
content is persisted.

## Logo safety

Only PNG is accepted:

- maximum 512 KiB;
- width and height from 32 through 2048 pixels;
- valid PNG signature;
- valid IHDR color/encoding parameters;
- bounded chunk structure;
- CRC validation for every chunk;
- non-empty IDAT and terminal IEND;
- no trailing data.

Assets are keyed by tenant, kind, and SHA-256 and deduplicated. At most 20
brand assets are retained per tenant. Old assets are retained so an immutable
revision can be restored. SVG, external URLs, and data supplied as CSS are
not accepted.

## Locale and timezone behavior

- `ui_locale`: currently `ru-RU` only, until translation acceptance exists.
- `format_locale`: `ru-RU`, `kk-KZ`, or `en-US`.
- `timezone`: any valid IANA identifier; the admin UI suggests common zones.
- currency: KZT, RUB, USD, or EUR.
- date styles: short, medium, or long.
- hour cycle: 24-hour (`h23`) or 12-hour (`h12`).

The authenticated bootstrap applies CSS variables, document language, product
title, logo, terms, and shared Intl formatters. A six-hour session fallback
cache is strictly shape-checked and refreshed from the API; invalid or expired
cache entries are discarded. Network failure falls back to the safe platform
profile and never blocks authentication or navigation.

## Rollback

History is visible only with `tenant.experience.rollback`. Every history row
recomputes the stored snapshot hash. Rollback fails closed when:

- the current revision changed;
- target revision does not exist;
- snapshot integrity fails;
- snapshot validation fails under current policy;
- the referenced immutable logo asset is unavailable or belongs to another
  tenant.

Rollback creates a new revision with `rolled_back_from_revision`; it never
deletes or rewrites history.

## Audit events

- `tenant_experience.updated`
- `tenant_experience.logo_updated`
- `tenant_experience.logo_removed`
- `tenant_experience.rolled_back`
- `localized_content.created`
- `localized_content.updated`
- `localized_content.submitted`
- `localized_content.published`
- `localized_content.rejected`

Correlate by tenant ID, revision, snapshot SHA-256, and reason SHA-256.

## Deferred runtime gate

After runtime access is restored:

1. migrate PostgreSQL through `0064`;
2. publish profiles for two tenants and prove isolation;
3. reload requester, agent, admin, and root sessions;
4. verify ETag/cache refresh and cross-tab behavior;
5. upload valid/corrupt/oversized PNGs;
6. force revision conflicts and rollback;
7. inspect 320 px, 200% zoom, forced colors, and contrast after branding;
8. verify date/currency output around UTC date boundaries and DST zones;
9. inspect audit-chain integrity.
10. create, submit, reject, publish, stale, and republish knowledge and
    notification variants with two independent users;
11. prove the partial unique published-version index under concurrent
    publication attempts;
12. verify tenant/global source inheritance, cross-tenant denial, placeholder
    rendering, explicit knowledge locale selection, and source fallback.
