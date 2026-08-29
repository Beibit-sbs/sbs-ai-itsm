# PRG-003 — BACKUP, RESTORE, AND DISASTER RECOVERY REPORT

**Date:** 2026-07-28  
**Execution mode:** local-first  
**Result:** `GO / COMPLETED_LOCAL`

## 1. Objective

Prove that SBS AI ITSM can create a complete encrypted recovery set, detect a
failed backup, restore into a new isolated environment, preserve tenant data
and attachments, authenticate a privileged user, and remain inside the local
RPO/RTO targets.

No active staging or rehearsal volume was replaced. The restore target was the
new Compose project `sbs-itsm-drill`.

## 2. Implemented controls

- streaming AES-256-GCM encryption for database and runtime-data artifacts;
- SHA-256 artifact manifests and per-file runtime-data hashes;
- migration revision, size, timestamp, duration, and project metadata;
- restore-time manifest verification and authenticated decryption;
- transactional PostgreSQL restore with fail-fast behavior;
- safe runtime archive extraction with traversal/link/device rejection;
- grandfather-father-son retention: 7 daily, 4 weekly, 6 monthly per stream;
- one scheduled database + runtime-data operation with a run manifest;
- critical `SbsDatabaseBackupFailed` Alertmanager event and automatic resolve;
- daily Windows Task Scheduler execution at 02:00;
- explicit local/server ownership, escalation, copy, and recovery policy.

## 3. Recovery artifacts

Final database recovery point:

| Field | Value |
|---|---|
| Artifact | `backups/prg003/database/prg003_final_head.dump.enc` |
| Format | PostgreSQL custom dump inside SBS encrypted backup v1 |
| Encryption | AES-256-GCM |
| Bytes | 276,163 |
| SHA-256 | `07a15dc98194863c9c21be62dff0d84e7ac5469c63ada6502c228fb1e94f7243` |
| Alembic revision | `20260727_0028` |
| Backup duration | 0.688 s |
| Created UTC | `2026-07-28T17:24:13.873205+00:00` |

Runtime-data recovery point:

| Field | Value |
|---|---|
| Artifact | `backups/prg003/data/prg003_runtime-data.tar.gz.enc` |
| Encryption | AES-256-GCM |
| Bytes | 401 |
| SHA-256 | `3e21bca1191651184cf7b1a05ea99818db473e602e17d53d9ee5828e83f534e1` |
| Files | 1 |
| Source bytes | 135 |
| Attachment SHA-256 | `064b7f63bf34236ac404eab601f51f714feca03c350f6bc631adbca0eb03a78e` |
| Backup duration | 0.006 s |

The scheduled orchestration also produced an independent database artifact,
runtime-data artifact, two manifests, and
`backups/prg003/scheduled/runs/20260728_172928_sbs-itsm-rehearsal.json`.

Artifacts and secrets are Git-ignored. Secret values were not printed or
written to the report.

## 4. Measured RPO and RTO

Local engineering targets:

- RPO: 24 hours;
- RTO: 30 minutes.

Measured results:

| Measurement | Result | Target | Outcome |
|---|---:|---:|---|
| Recovery-point age at DR project creation | 13.862 s | ≤ 86,400 s | PASS |
| Fresh PostgreSQL preparation | 10.930 s | — | evidence |
| Encrypted database restore | 0.820 s | — | evidence |
| Complete stack build/start/health | 24.996 s | — | evidence |
| Runtime-data restore | 0.007 s | — | evidence |
| Full technical recovery through smoke | approximately 37.4 s | ≤ 1,800 s | PASS |

The measured RPO is the age between final manifest creation and creation of
the isolated DR PostgreSQL container. Business targets still require service
owner approval before server cutover.

## 5. Restored data validation

| Check | Source/recovery expectation | Restored result |
|---|---:|---:|
| Alembic revision | `20260727_0028` | `20260727_0028` |
| Tenants | 2 | 2 |
| Users | 3 | 3 |
| Tickets | 50 | 50 |
| Tenant A tickets | 25 | 25 |
| Tenant B tickets | 25 | 25 |
| Orphan tickets | 0 | 0 |
| Invalid indexes | 0 | 0 |
| Unvalidated constraints | 0 | 0 |
| Backup failure audit events | firing + resolved | present |
| Restored attachment SHA | source SHA | exact match |

Audit totals increased after restore because smoke and integrity login created
new valid events. The final audit-chain check validated 23 events across one
chain with `valid=true` and no failures.

## 6. Application validation

The isolated application was exposed only on loopback:

- application: `http://127.0.0.1:28080`;
- Grafana: `http://127.0.0.1:23000`;
- Alertmanager: `http://127.0.0.1:29093`.

Production smoke passed:

- liveness;
- readiness for database, Redis, migrations, and runtime;
- frontend HTML;
- anonymous protected-API rejection;
- authenticated Prometheus metrics;
- Grafana health;
- Alertmanager readiness;
- privileged login, identity lookup, and logout.

Backend, worker, and migration log review: 71 lines inspected, zero
error-level/traceback matches.

## 7. Failure alert evidence

A safe failure was triggered by attempting to overwrite an existing encrypted
artifact. The backup tool refused the overwrite and submitted:

- alert: `SbsDatabaseBackupFailed`;
- severity: `critical`;
- state: `active`;
- project: `sbs-itsm-rehearsal`;
- diagnostic: overwrite refusal;
- runbook: `docs/operations/BACKUP-RESTORE-RUNBOOK.md`.

The alert was visible through Alertmanager `/api/v2/alerts`. A subsequent
successful backup submitted the resolved state; active backup alerts returned
to zero. The protected monitoring webhook also persisted firing/resolved audit
events.

## 8. Scheduler evidence

Windows task:

- name: `SBS AI ITSM Local Backup`;
- schedule: daily at 02:00 local time;
- mode: interactive local user;
- state after test: `Ready`;
- manual end-to-end result: `0`;
- next run at acceptance: `2026-07-29T02:00:00+05:00`.

The first manual task execution exposed the Microsoft Store `python3` alias and
returned code 1. The wrapper was corrected to prefer the verified bundled
Python runtime. The repeated Task Scheduler execution completed with code 0
and produced the complete encrypted staging recovery set. This is recorded as
useful acceptance evidence rather than hidden.

## 9. Test evidence

- production preflight for `.env.drill.local`: 41 OK, 1 expected MFA warning,
  0 failures after backup-key enforcement;
- production Compose config: valid;
- focused backup/monitoring suite: 12 passed;
- full backend regression: 511 passed, 16 skipped, 1 dependency deprecation
  warning;
- isolated production smoke: passed;
- audit integrity: passed;
- runtime logs: zero error-level matches.

The warning is the existing Starlette `httpx` compatibility deprecation and is
not a PRG-003 regression.

## 10. Retention, access, and external copy decision

Local retention is active in the scheduled wrapper:

- 7 daily;
- 4 weekly;
- 6 monthly;
- evaluated independently for database and runtime-data streams;
- deletion occurs only after a complete successful backup set.

Local artifacts remain in Git-ignored `backups/`; keys remain in Git-ignored
secret directories. External storage is intentionally not connected during
local-first execution.

Server go-live remains blocked until a second storage medium and an immutable
off-site copy are configured, access is separated, and restore is tested from
that off-site copy. The encryption key must remain in the approved secret
manager and outside the backup bucket.

## 11. Exit-criteria decision

- Full isolated restore: PASS.
- Measured local RPO/RTO: PASS.
- Database, tenant, authentication, attachment, and audit validation: PASS.
- Backup failure creates an actionable critical alert: PASS.
- Daily encrypted schedule and retention: PASS.
- Owners, escalation, and decision points documented: PASS.

`PRG-003` is accepted as `COMPLETED_LOCAL`. Advance to `PRG-004 — Identity and
security cutover`. External/off-site copy activation remains a mandatory final
server-cutover action, consistent with the recorded local-first decision.
