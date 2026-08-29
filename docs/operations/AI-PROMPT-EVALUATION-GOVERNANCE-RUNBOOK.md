# AI prompt and evaluation governance runbook

## Control objective

AI prompt/model configuration is treated as production configuration, not as
editable text. Every deployable version has an immutable SHA-256 identity,
repeatable evaluation evidence, independent review, a separate deployment
actor, deterministic canary routing, audit evidence, and rollback.

## Roles and permissions

- `ai.governance.read`: read policies, versions, datasets, runs, and metrics.
- `ai.governance.manage`: create policies, immutable versions, datasets, cases.
- `ai.governance.evaluate`: run evaluation suites.
- `ai.governance.approve`: independently approve/reject a passed version.
- `ai.governance.deploy`: create canary/full rollout and roll back.
- `ai.governance.audit`: inspect governance evidence through the audit module.

Organization Admin and IT Manager receive the full control set. The release
workflow still rejects self-review and requires the deployment actor to be
different from both author and reviewer. SaaS Root must explicitly select the
tenant for list/create operations.

## Standard release procedure

1. Create one active policy for `ticket_classification` or `grounded_answer`.
2. Create an immutable version with provider, exact model, parameters, change
   summary, and system prompt. Credentials are rejected.
3. Create a representative dataset and cases. Do not put raw personal data,
   credentials, or prompt-injection instructions in evaluation fixtures.
4. Run evaluation against the currently configured provider/model.
5. Review quality, groundedness, safety, average/p95 latency, estimated cost,
   baseline regression, case count, and evidence hash.
6. A different user approves the passed version.
7. A third user starts a deterministic canary or full activation.
8. Observe query/provider metrics. Promote or roll back.

The runtime refuses a governed prompt when its live content no longer matches
the evaluated SHA-256. A version for a provider/model different from the
currently configured provider cannot be evaluated.

## Default release thresholds

| Metric | Default gate |
| --- | --- |
| Weighted quality | at least 0.70 |
| Weighted groundedness | at least 0.80 |
| Weighted safety | exactly 1.00 |
| Average latency | at most 30 seconds |
| Estimated run cost | at most USD 0.10 |
| Quality regression vs baseline | at most 0.05 |

Threshold overrides are allowlisted and bounded. Unknown or out-of-range
thresholds fail closed.

## Evidence and privacy

Evaluation result rows store scores, latency, estimated cost, citation IDs,
failure reason codes, and output SHA-256. They do not store raw model output.
Cases are tenant scoped, size bounded, hashed, and credential screened. Prompt
text is visible only to roles with governance read permission and never copied
into audit metadata.

## Canary behavior

Canary assignment hashes tenant, policy, and stable routing key. The same user
or ticket remains in the same bucket. Grounded-answer routing uses user ID;
classification routing uses ticket ID when present. If canary integrity fails,
the runtime falls back to the last valid active version or built-in safe prompt.

## Rollback

Use the rollout rollback operation. It retires the candidate, restores the
previous version when available, updates policy revision, preserves rollout
history, and emits an audit event. Never edit a version in the database to
simulate rollback.

## Release acceptance

Before server release, execute migration `0056`, focused and full regression,
and browser acceptance with three separate identities. Prove self-review,
reviewer deployment, changed prompt hash, failed evaluation, provider/model
mismatch, unsafe dataset, and out-of-range thresholds are rejected.

