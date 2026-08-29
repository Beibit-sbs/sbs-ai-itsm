# SBS AI ITSM — P0 security and supply-chain gate

Date: 2026-08-14 12:48 +05:00  
Revision: `0b04ada23744349f565b44d60d52182da7f6da38` (dirty worktree)  
Result: `PASS_LOCAL_CURRENT_REVISION`

## Decision

The current local source tree and the isolated production-like rehearsal have
no open Critical or High finding in the completed dependency, SAST, secret and
container-image scans. Passive DAST has no FAIL rule. This result closes the
scanner/SBOM part of Stage 2; it does **not** authorize public production
exposure because server TLS, privileged MFA, malware quarantine, rate-limit
stress and an external penetration test remain separate gates.

## Final results

| Control | Final result | Evidence |
|---|---:|---|
| Python dependency audit | 57 packages, 0 known vulnerabilities | `P0-PIP-AUDIT-2026-08-14.json` |
| Frontend dependency audit | 155 packages, 0 vulnerabilities | `P0-NPM-AUDIT-2026-08-14.json` |
| Bandit SAST | 0 findings | `P0-BANDIT-2026-08-14.json` |
| Gitleaks Git history | 102 commits, 0 leaks | `P0-GITLEAKS-2026-08-14.json` |
| Gitleaks worktree | 27.06 MB, 0 leaks | `P0-GITLEAKS-WORKTREE-2026-08-14.json` |
| Backend image High/Critical CVE | 0 | `P0-BACKEND-IMAGE-CVES-2026-08-14.sarif.json` |
| Frontend image High/Critical CVE | 0 | `P0-FRONTEND-IMAGE-CVES-2026-08-14.sarif.json` |
| OWASP ZAP baseline | 0 FAIL, 4 WARN rule IDs, 63 PASS | `P0-ZAP-BASELINE-2026-08-14.json` |
| Source/image SBOM | generated for both applications and both images | four SBOM files in `docs/audit/evidence/` |

All JSON/SARIF/SBOM hashes are recorded in
`P0-SECURITY-GATE-2026-08-14.json`. Secret values were not copied into the
evidence.

## Findings closed during the gate

- Python audit initially reported vulnerable `aiohttp 3.9.1` and
  `python-multipart 0.0.20`; they are now `3.14.3` and `0.0.31`.
- NPM audits identified affected React Router packages and, on the final
  registry refresh, `brace-expansion`, `nanoid` and `postcss`; the lockfile now
  resolves to fixed versions and a clean audit.
- Bandit reported one B310 outbound-request finding. Provider URLs are now
  accepted only for HTTPS, port 443, with a hostname and without userinfo or a
  fragment. Gemini query parameters remain supported.
- The former Debian backend image and the original nginx Alpine package set
  contained High/Critical OS findings. The backend now uses a pinned Alpine
  Python base. The frontend upgrades the bounded OpenSSL packages and removes
  curl/libcurl from runtime. Both final images scan clean at High/Critical.
- Nginx now has CSP fallback directives and cross-origin isolation headers.
  The COEP ZAP warning is closed.
- Gitleaks covers both Git history and the dirty worktree. Local ignored
  `.env.production`, rehearsal secret files, verified backups and generated
  temporary artifacts are excluded from source scanning; examples and source
  code are not broadly excluded. Six synthetic test fingerprints are ignored
  exactly and documented.

## DAST warning disposition

No ZAP warning is reported as fixed when it is not:

1. `CSP: style-src unsafe-inline` — Medium risk, High confidence, three public
   shell instances. Accepted for the local gate because current React styling
   uses inline style attributes. Required follow-up: nonce/hash-compatible
   styling before the public hardening gate.
2. Suspicious comment — informational, one minified production-bundle match;
   reviewed as a generated bundle false positive.
3. Modern Web Application — informational SPA classification.
4. Cacheability observations — informational behavior for hashed static assets
   and the unauthenticated shell/metadata. Authenticated API responses remain a
   separate server-TLS/browser verification item.

## Verification after remediation

- production frontend clean build: PASS;
- focused backend regression: 130 passed, 0 failed;
- accessibility baseline: PASS;
- interactive controls audit: 651 buttons and 39 links, PASS;
- isolated production authenticated smoke: PASS;
- fresh runtime error/critical/traceback signatures: 0.

## Remaining release boundary

The following controls are not silently converted into success: public
domain/TLS active scanning, privileged MFA enrollment and enforcement,
ClamAV/quarantine acceptance, tenant/API-token/global rate-limit stress, and an
independent penetration test. Until they pass, the overall public-production
decision remains `NO-GO/BLOCKED_EXTERNAL` even though this scanner gate passes.
