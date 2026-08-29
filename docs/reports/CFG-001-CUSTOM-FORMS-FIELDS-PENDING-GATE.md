# CFG-001 — Custom Forms and Fields Platform

Status: **implementation complete; runtime release gate pending**

Date: 2026-07-29

## Outcome

The platform now has a governed, tenant-scoped custom-field layer for
incidents, assets/CIs, changes, problems, and service requests. It extends the
existing catalog form foundation into operational records without replacing
or weakening catalog versioning.

## Delivered

### Versioned data model

- Tenant-unique field sets with approved entity type, lifecycle,
  applicability, and optimistic revision.
- Editable drafts and immutable published/retired versions.
- Canonical schema JSON, SHA-256 integrity, validation evidence, version
  lineage, and publisher attribution.
- Version-bound entity values with integrity hash and optimistic update.
- Additive linear migration `20260729_0053`.

### Typed schema and governance

- Eight supported field types.
- Required/default, validation, choice options, conditional visibility,
  search, index, report, sensitivity, and immutability controls.
- Allowlisted entity applicability rather than arbitrary attribute access.
- Structural compatibility evidence.
- Explicit approval for breaking evolution when stored values exist.
- Published schema and bound-value integrity verification.

### Data protection and query controls

- AES-GCM encryption for sensitive values with tenant and field context.
- No decryption for unauthorized responses.
- Sensitive values excluded from search and indexing.
- Search over explicitly classified fields with escaped patterns.
- Report projection over explicitly reportable fields.
- No ciphertext or plaintext in audit metadata.

### API, RBAC, and audit

- 14 OpenAPI paths and 18 operations.
- Tenant-scoped dashboard, catalog, CRUD, versions, validation, comparison,
  publication, record values, search, and report data.
- Eight granular RBAC permissions.
- Audited creation, configuration, draft edit, publication, and value save.
- SaaS Root requires an explicit tenant for non-resource-scoped operations.

### Administration and record UX

- Dedicated **Настраиваемые поля** workspace.
- Visual field builder plus JSON expert mode.
- Keyboard-operable add, remove, ordering, type, flags, validation, choices,
  and conditional visibility controls.
- Applicability condition builder.
- Version/integrity history and publication controls.
- Unsaved-change protection.
- Real-record test and controlled search views.
- Reusable record panel integrated into Incident, Asset/CI, Change, Problem,
  and Service Request detail screens.

## Tests as code

`backend/tests/test_custom_fields.py` covers:

- sensitive/search/index schema denial;
- compatibility classification;
- applicability allowlists;
- publication and immutable versions;
- AES-GCM storage, masking, authorized reveal, and search text;
- immutable-after-set and optimistic version conflict;
- explicit breaking-change approval;
- tenant-scoped entity resolution;
- value integrity tamper detection.

## Static acceptance

- Full backend Ruff: passed (inaccessible stale pytest temp-directory warnings
  only).
- Full backend compileall: passed.
- Frontend TypeScript no-emit: passed.
- OpenAPI generation: passed with 526 total paths, 14 custom-field paths, and
  18 custom-field operations.
- Alembic graph: one head, `20260729_0053`.
- Development and production Compose parsing: passed.
- `git diff --check`: passed; repository line-ending notices only.

Runtime tests, migration rehearsal, production frontend build, and browser
acceptance remain deferred by the current execution-environment constraint.
No runtime completion claim is made.

## Operational reference

See `docs/operations/CUSTOM-FIELDS-PLATFORM-RUNBOOK.md`.
