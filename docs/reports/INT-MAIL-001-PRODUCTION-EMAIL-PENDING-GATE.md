# INT-MAIL-001 Production Email Channel — Pending Runtime Gate

**Implementation date:** 2026-07-29  
**Migration head:** `20260729_0047`  
**Status:** implementation complete; runtime release gate pending

## Implemented

- Tenant-scoped Microsoft Graph and local mock email channels.
- AES-256-GCM encryption for the Graph client secret, webhook client state,
  loop token, and delta checkpoint.
- Connection testing, optimistic versioning, single-active-channel invariant,
  pause, irreversible revoke, secret rotation, and audit.
- Microsoft Graph client-credential authentication using fixed Microsoft
  endpoints and in-memory access-token caching.
- Inbox delta synchronization, public webhook validation/persistence,
  subscription creation/renewal, and worker processing.
- Inbound deduplication, incident/request creation, public reply comments,
  protected thread markers, and requester/tenant authorization.
- Auto-response, bulk/list, loop, allowed-domain, and DMARC controls.
- Attachment filename normalization, executable denylist, extension and size
  policy, SHA-256, isolated storage, ClamAV integration, and quarantine
  decisions.
- Outbound queue, idempotency keys, Microsoft Graph `sendMail`, exponential
  retry, `Retry-After`, failure events, and NDR/bounce correlation.
- Honest status semantics: Graph `202` is `ACCEPTED`, not `DELIVERED`.
- Email operations administration workspace plus replacement of the old mock
  email log language and behavior.
- Production Compose shared attachment volume and dedicated credential
  encryption secret.

## Static acceptance

The stage is accepted statically only after all of the following pass:

- Ruff on changed backend and test files;
- Python `compileall`;
- TypeScript `tsc --noEmit`;
- OpenAPI import and email route inventory;
- Alembic single-head inspection through `0047`;
- Docker Compose configuration parsing;
- `git diff --check`.

## Written runtime tests

`backend/tests/test_email_channel.py` covers:

- administrative channel controls without secret disclosure;
- inbound ticket creation, idempotency, and reply threading;
- spoofed-thread and platform-loop isolation;
- safe and executable attachment behavior;
- outbound `ACCEPTED` semantics and queue idempotency;
- webhook event deduplication;
- tenant/purpose-bound credential encryption.

These tests are written but are not claimed as executed in the current
environment because the existing external runtime gate remains unavailable.

## Deferred runtime release gate

Required before production completion:

1. Apply migration `0047` to disposable PostgreSQL and then staging.
2. Run focused email tests and the full backend suite.
3. Run the production frontend build.
4. Run Microsoft 365 acceptance with a restricted test mailbox:
   - connection test;
   - initial delta checkpoint;
   - new email creates one ticket;
   - reply creates one public comment;
   - replay creates no duplicate;
   - spoofed reply is quarantined;
   - clean and malware-test attachments follow policy;
   - Graph 429 follows `Retry-After`;
   - Graph `202` remains `ACCEPTED`;
   - NDR produces `BOUNCED`.
5. Validate public HTTPS webhook and renewal on the target server.
6. Validate ClamAV and shared attachment storage.
7. Complete browser acceptance for SaaS Root, Organization Admin, IT Manager,
   IT Agent, and Security Officer.

No runtime or production-ready completion claim is made until this gate
passes.
