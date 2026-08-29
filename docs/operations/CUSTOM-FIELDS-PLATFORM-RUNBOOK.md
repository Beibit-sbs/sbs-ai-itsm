# Custom Fields Platform Runbook

## Purpose

This runbook covers tenant-owned, typed custom fields attached to approved
ITSM record types:

- Incident (`ticket`);
- Asset / configuration item (`asset`);
- Change (`change`);
- Problem (`problem`);
- Service request (`request`).

Catalog item forms remain governed by their existing catalog lifecycle. Both
systems use the same field-definition and submission validators so type,
visibility, option, and validation behavior stays consistent.

## Operator workspace

Open **Admin & Security → Настраиваемые поля** or navigate to:

`/admin/custom-fields`

The workspace provides:

- tenant and entity filters;
- visual and JSON schema editors;
- applicability conditions;
- version history and SHA-256 integrity state;
- validation and compatibility evidence;
- explicit breaking-change approval;
- record-level test and save;
- controlled search over fields marked `searchable`.

Published versions are immutable. To change a published schema, create a new
draft from it, edit and validate the draft, then publish it.

## Data and lifecycle

### Field set

A field set owns:

- tenant-unique code;
- one supported entity type;
- `ACTIVE`, `PAUSED`, or `ARCHIVED` lifecycle;
- applicability conditions;
- current draft and published version pointers;
- optimistic revision.

`ARCHIVED` is terminal. An active set must have a published version.

### Schema version

Each version is:

- `DRAFT`, `PUBLISHED`, or `RETIRED`;
- bound to canonical JSON and a SHA-256 hash;
- validated before save and publish;
- linked to its source version;
- attributed to author, editor, and publisher.

Publishing a new version retires the previous published version. Existing
value records retain the exact schema version that accepted them and move to
the new version only after the next successful save.

### Value record

There is at most one value record per field set and entity. It includes:

- exact schema version binding;
- canonical value JSON and SHA-256 integrity hash;
- optimistic version;
- controlled search text;
- creator/editor attribution.

## Supported field capabilities

Supported types:

- `text`, `textarea`, `number`, `boolean`;
- `select`, `multiselect`;
- `date`, `email`.

Per-field controls:

- required/optional;
- default value;
- validation rules;
- conditional visibility based on an earlier field;
- searchable, indexed, and reportable classifications;
- sensitive encryption;
- immutable-after-first-set.

Sensitive fields cannot be searchable or indexed. Textarea and multiselect
fields cannot use the indexed classification. Schema validation and publish
fail closed when these rules are violated.

## Applicability

Applicability is an allowlisted conjunction (`all`) of at most ten conditions.
Supported operators are `eq`, `neq`, and `in`. Attributes are allowlisted per
entity type; arbitrary model attribute access is rejected.

No conditions means the field set applies to every record of its entity type.

## Safe schema evolution

The compatibility analyzer marks these changes as breaking:

- removing an existing field;
- changing a field type;
- adding a required field without a default;
- making an existing optional field required without a default;
- removing the sensitive classification;
- removing immutable-after-set protection.

When stored values exist, a breaking version cannot publish unless the
publisher has `custom_fields.publish` and explicitly enables breaking-change
approval. The reason and full compatibility result are written to audit.

Before approving a breaking change:

1. Export or query reportable data needed for migration verification.
2. Confirm how removed and retyped values will be handled.
3. Test the draft against representative records.
4. Record the change or release reference in the publication reason.
5. Publish in a controlled window and verify records after save.

## Sensitive fields

Sensitive values use the platform credential-vault AES-GCM primitive with
tenant, field-set, and field-key authenticated context.

Production requires a non-placeholder `CREDENTIAL_ENCRYPTION_KEY` of at least
32 characters. Never rotate this value without a controlled re-encryption
procedure: existing ciphertext cannot be decrypted with a different key.

Users without `custom_fields.sensitive.read` receive a fixed mask and the API
does not decrypt plaintext for that response. Stored ciphertext, encryption
envelopes, and plaintext are never added to search text or audit metadata.

## Search and reporting

Search:

- requires `custom_fields.search`;
- scans only normalized values from fields marked `searchable`;
- uses tenant and optional entity/field-set scope;
- escapes query wildcard characters;
- returns sensitive values masked unless separately authorized.

Reporting:

- requires `custom_fields.report`;
- returns only fields marked `reportable`;
- preserves schema version and entity identifiers;
- masks sensitive fields unless the caller also has
  `custom_fields.sensitive.read`.

## Permissions

- `custom_fields.read` — field-set and version metadata;
- `custom_fields.design` — create and edit drafts and applicability;
- `custom_fields.publish` — publish and approve breaking evolution;
- `custom_fields.values.read` — read attached values;
- `custom_fields.values.write` — validate and save attached values;
- `custom_fields.sensitive.read` — decrypt sensitive values;
- `custom_fields.search` — controlled search;
- `custom_fields.report` — reportable-field projection.

SaaS Root is still required to select an explicit tenant. No endpoint accepts
an implicit global custom-field scope.

## API entry points

All paths are below `/api/v1/custom-fields`.

- `/catalog`, `/dashboard`;
- `/` and `/{field_set_id}`;
- `/{field_set_id}/versions`;
- `/{field_set_id}/drafts`;
- `/{field_set_id}/versions/{version}`;
- validation, compare, and publication subresources;
- `/entities/{entity_type}/{entity_id}/field-sets`;
- `/{field_set_id}/entities/{entity_id}/values`;
- `/search`;
- `/reports/data`.

## Troubleshooting

### Publication is rejected

Inspect validation errors, schema integrity, current field-set/version
revisions, and compatibility evidence. Save the current draft before
publishing. Enable breaking-change approval only after review.

### A field set is missing from a record

Confirm:

1. set status is `ACTIVE`;
2. a published version exists;
3. entity type matches;
4. every applicability condition matches the current entity;
5. the user has `custom_fields.values.read`.

### Sensitive save fails

Confirm `CREDENTIAL_ENCRYPTION_KEY` is configured and unchanged. Do not put
the key into platform settings or the database.

### Integrity verification fails

Treat this as a security and data-integrity incident. Stop publication or
editing, preserve database evidence, inspect audit events and database access,
and restore only through an approved recovery procedure.

### Optimistic version conflict

Reload the field set, draft, or value record and reconcile changes. Do not
blindly repeat a stale update.

## Deferred runtime release gate

Repository static acceptance does not replace runtime acceptance. Before
production release:

1. apply migration `20260729_0053` to a disposable PostgreSQL copy;
2. execute focused and full backend regression;
3. test concurrent value updates and duplicate creation;
4. verify encryption/masking using the intended production key;
5. verify cross-tenant and role access with multiple users;
6. complete browser keyboard and responsive acceptance;
7. build the production frontend bundle;
8. execute readiness and backup/restore rehearsal.
