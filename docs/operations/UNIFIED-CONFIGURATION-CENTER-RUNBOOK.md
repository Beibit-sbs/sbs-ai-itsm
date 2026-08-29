# Unified Configuration Center runbook

## Purpose

The Configuration Center is the supported control plane for platform and
tenant settings. It replaces editing raw key/value rows with:

- task-oriented configuration domains;
- explicit `global` or `tenant` scope;
- readiness checks and actionable issues;
- role-aware prioritized setup guidance;
- explicit applicability (`NOT_APPLICABLE`) instead of false failures for
  optional or not-yet-selected external systems;
- live non-secret diagnostic evidence and deterministic SHA-256 hashes;
- safe-default explanations, exact remediation routes, required permissions,
  owner roles, runbook references, and audit navigation;
- typed values and bounded validation;
- optimistic revision control;
- captured baseline, revision history, SHA-256 evidence, and rollback;
- audit events containing metadata and hashes rather than secrets.

The legacy setting list is read-only diagnostics. Catalogued settings reject
the legacy raw PATCH endpoint.

## Roles and scope

- SaaS Root can select Global platform or a tenant.
- Organization Admin can manage only its tenant scope.
- IT Manager and Security Officer receive read-only readiness access by
  default.
- Global AI provider credentials, connection tests, models, and endpoints are
  mutable only by SaaS Root.
- Tenant administrators control tenant AI data policy, budgets, governed
  actions, and other tenant configuration through their domain panels.

Never grant `admin.configuration.manage` or
`admin.configuration.rollback` as a substitute for a domain-specific
permission.

## Typed settings

The first change through the center captures the current effective value as
revision 1, then records the requested state as revision 2. This preserves a
rollback point even when the previous value came from a global default.

Every update requires the current revision. A stale browser receives a
conflict and must reload. Boolean settings accept only explicit boolean forms;
integer settings enforce their server range. The server stores a normalized
value and immutable revision evidence.

Rollback never edits history. It validates a selected historical value and
creates a new current revision with `rolled_back_from_revision`.

## Readiness domains

- **Основные параметры**: typed platform/tenant settings are valid.
- **AI provider и секреты**: active global provider has a usable encrypted
  credential when required and PII redaction is enabled. Mock is intentionally
  shown as degraded for production readiness.
- **Tenant AI governance**: data/residency policy, hard budget, and guarded
  action policy exist.
- **Email и collaboration**: production email is applicable only when email
  notifications are enabled. Local mock delivery is a visible warning, not a
  hidden success. Teams is optional until selected as the collaboration stack.
- **Monitoring и интеграции**: active event source and healthy configured
  external systems.
- **Identity lifecycle**: provisioning becomes required when external identity
  is enabled or a connector exists; local-only identity is otherwise explicit
  and not applicable.
- **Security readiness**: privileged-user MFA coverage and enforcement.

Readiness is operational guidance, not a replacement for the production
release gate.

## Embedded administration guide

The API returns a typed guide together with each readiness snapshot:

- `guide.version` identifies the guidance contract;
- `generated_at` identifies when live diagnostics were evaluated;
- `operator_role` records the role used for role-aware actions;
- `next_actions` is sorted by critical, high, medium, then informational
  severity;
- every domain contains its complete checklist, owner roles, safe default,
  runbook, and domain evidence SHA-256;
- every check contains status, diagnostic, remediation, exact route,
  `can_manage`, required permission, non-secret evidence, evidence SHA-256,
  runbook, and audit route.

| Status | Meaning |
|---|---|
| `PASS` | Live evidence satisfies the check. |
| `INFO` | Operational task exists but does not reduce readiness. |
| `WARNING` | Safe fallback exists, but production hardening remains. |
| `ACTION_REQUIRED` | An applicable control is missing or unsafe. |
| `NOT_APPLICABLE` | The dependent capability is disabled or not selected. |

`NOT_APPLICABLE` checks are excluded from readiness denominators. This prevents
an unselected Teams stack or disabled external IdP from being reported as a
production defect. When the dependency becomes applicable, the check
automatically changes to pass or action-required from live evidence.

The browser shows a filtered priority queue, expands each domain into its
diagnostics, and exposes safe fallback, permission, ownership, runbook, audit,
and hash evidence. Read-only operators can inspect the same diagnostic but
receive **Open status** instead of a misleading mutation action.

The response is `private, no-store`, carries an ETag derived from scope,
domain evidence and setting revisions, and never includes credential names,
ciphertext, plaintext, tokens, or client secrets.

## AI provider secrets

OpenAI and Gemini keys saved from the UI are encrypted with AES-GCM using the
server credential-encryption key and purpose-bound associated data. The API
returns only configured/not-configured booleans. It never returns ciphertext
or plaintext.

In production, an old plaintext AI credential in `system_settings` is refused
by the provider loader. After applying migration `0059`:

1. configure `CREDENTIAL_ENCRYPTION_KEY` with a non-placeholder value of at
   least 32 characters;
2. sign in as SaaS Root;
3. replace each AI provider key in the guided panel;
4. test the provider connection;
5. confirm the database value starts with the encrypted `v1.` envelope and
   does not contain the key;
6. review `ai_provider_config_changed` and
   `ai_provider_connection_tested` audit events.

Do not copy encrypted values between environments; associated data and server
key ownership are part of the credential boundary.

## Change procedure

1. Select the correct Global/Tenant scope.
2. Review overall and domain readiness.
3. Change one typed setting at a time and provide a concrete reason.
4. Save and confirm the new revision.
5. Verify the dependent domain behavior.
6. If recovery is required, open history and roll back to a known revision.
7. Inspect audit evidence and the domain health indicator.

For email, Teams, monitoring, integrations, identity, and AI provider, use the
linked specialized console and its test-connection workflow.

Do not treat a green guide as release approval. The guide evaluates configured
state and safe defaults; migration execution, end-to-end delivery, load,
resilience, browser, and security acceptance remain separate gates.

## Incident response

- `Configuration revision conflict`: reload; never resubmit a stale value
  blindly.
- typed validation error: correct the value; do not use the legacy endpoint.
- global provider controls disabled: sign in as SaaS Root or route the change
  to the platform owner.
- credential decryption failure: disable the external provider, verify the
  credential-encryption key, then rotate and resave the credential.
- readiness degraded after save: open the listed issue and the linked domain
  console; roll back if the change caused the degradation.
- rollback target invalid: stop and inspect revision/audit integrity before a
  manual domain recovery.

## Release proof

Prove tenant/global isolation, root-only provider mutation, typed bounds,
optimistic conflicts, initial baseline capture, rollback-as-new-revision,
audit events, read-only legacy catalog settings, encrypted secret storage,
production refusal of plaintext credentials, responsive UI, and all linked
readiness domains.
