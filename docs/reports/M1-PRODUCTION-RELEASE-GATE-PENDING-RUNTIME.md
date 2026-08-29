# M1 — Production Release Gate

Status: `LOCAL_STATIC_GATE_PENDING_HOST_LINT_RUNTIME_ACCEPTANCE_PENDING`  
Date: 2026-07-29  
Latest local evidence SHA-256:
`746a9243316866a8b03040d83dce44806e09d1144efcc268fa8dc2ec6b083fe3`

## Outcome

PRG-001 through PRG-007 are represented by a machine-readable release contract
with 67 existing artifacts, accountable owners, and seven explicit runtime
gates. The latest run passed 25 of 26 checks. Windows Application Control
blocked the bundled Ruff executable before linting; this is recorded as a gate
failure rather than waived. The milestone also remains incomplete until the
environment-dependent gates produce real evidence.

## Reproducible local gate

Run:

```powershell
python scripts/run_local_release_gate.py
```

When Node is not on `PATH`, supply `--node <absolute-node-path>`. Optional
`--output <workspace-path>` stores the secrets-safe JSON evidence.
If host Application Control has already blocked the trusted Ruff binary, use
`--record-ruff-blocked` to retain Ruff as an explicit failed check while
running the remaining gate. This option never waives lint or produces PASS.

The latest run covered:

- Ruff: blocked by host Application Control (`WinError 4551`);
- backend/script compileall;
- seventeen contract validators: observability, PRG-006, M1, M2-M8,
  authorization, route authentication, edge security, session security,
  canary evidence, alert-delivery integrity, and the legacy-integration
  simulation boundary, automation-execution integrity, email-delivery
  integrity, Teams-delivery integrity, AI-provider evidence integrity, and
  permission-aware UI, and operational UI state resilience;
- TypeScript no-emit check;
- accessibility source audit;
- production and bootstrap Compose parsing;
- OpenAPI construction with 591 paths;
- single Alembic head `20260814_0073`;
- `git diff --check`.

All checks except Ruff passed. The 26-check evidence is deliberately recorded
as `FAIL` with `runtime_acceptance=NOT_EXECUTED`. The prior 23-check baseline
passed before the AI-provider evidence stage, but it is not presented as
evidence for the current source state.

## Immutable release implementation

Version tags matching semantic `vX.Y.Z` now:

- build backend/frontend images without a mutable `latest` tag;
- publish version and commit-SHA tags;
- generate SBOM and maximum build provenance;
- block on high/critical image findings;
- sign both digest-pinned images with GitHub OIDC/Cosign;
- publish registry provenance attestations;
- create a release manifest containing source commit and immutable digests;
- retain the manifest and generate release notes.

Staging promotion and rollback remain an environment-approved gate. Images must
be promoted by digest from the release manifest, never rebuilt or retagged by
hand.

## Runtime blockers retained

1. Target DNS, TLS, network segmentation, readiness, and production smoke.
2. Clean and representative PostgreSQL migration rehearsal.
3. Scheduled backup plus isolated restore drill meeting approved RPO/RTO.
4. IdP connection, privileged MFA enforcement, step-up, and break-glass.
5. Live metrics/dashboard/synthetic and alert delivery/ack/dedup/resolution.
6. Baseline, peak, soak, queue/import/WebSocket, and controlled failure tests.
7. Cross-tenant concurrent isolation plus SCA/SAST/image/secret/DAST evidence.
8. Immutable staging promotion, smoke, and known-good digest rollback.
9. Final Release Manager, Security, Database, Platform, and Service Management
   sign-off.

## Exit decision

Local/static gate: PENDING A TRUSTED RUFF EXECUTION.  
M1 production milestone: PENDING RUNTIME ACCEPTANCE.
