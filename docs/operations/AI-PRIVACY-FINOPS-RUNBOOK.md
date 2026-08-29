# AI privacy, residency, FinOps, and circuit-breaker runbook

## Runtime rule

Every external AI call must pass all controls before network execution:

1. explicit tenant data policy exists and external processing is enabled;
2. provider is allowlisted and has an explicit residency region label;
3. active governed prompt/model has explicit input/output token rates;
4. data classification does not exceed the tenant external-processing ceiling;
5. PII uses mandatory redaction and the tenant permits reversible tokenization;
6. monthly/daily request and monthly estimated-cost hard budgets are configured
   and not exhausted;
7. provider circuit is closed or this request owns the single half-open probe.

Failure of any check uses the local mock/extractive provider. It does not send
data externally and does not make Copilot unavailable.

## Initial configuration

1. Apply migration `20260729_0057`.
2. In **AI Copilot → AI Privacy & FinOps**, select the tenant.
3. Save a hard budget. No external call is allowed without one.
4. Select allowed provider(s) and enter the contractually verified processing
   region/residency label.
5. Select the maximum external data class.
6. Save the data policy.
7. In Prompt Governance, ensure the active version contains current input and
   output USD-per-million-token rates.
8. Verify a call in the hash-only usage ledger and compare provider billing.

Changing the global provider/API key does not bypass tenant policy.

## Data classes

- `PUBLIC`: approved public content.
- `INTERNAL`: non-public operational guidance without detected PII.
- `CONFIDENTIAL`: PII or Incident, Problem, Change, or Asset context.
- `RESTRICTED`: explicitly restricted source.

Classification is conservative. PII always forces redaction. If reversible
redaction is disallowed, PII-bearing requests remain local.

## Budget behavior

Budgets apply before external calls and use row locking on PostgreSQL to prevent
concurrent overspend. The ledger counts requests and estimates token usage from
payload length. Cost uses rates bound to the active immutable prompt/model
version. Missing rates fail closed as `cost_rates_not_configured`.

The dashboard shows monthly requests, daily requests, estimated monthly cost,
limits, and utilization. Reconcile estimates with provider invoices; update
rates through a newly evaluated prompt/model version, never by editing an
active version.

## Circuit breaker

An external response that falls back to local is counted as a provider failure.
At the configured threshold the circuit opens for its cooldown. After cooldown,
one request receives the half-open probe; concurrent requests stay local. A
successful probe closes the circuit, while failure reopens it.

Manual reset is allowed only after an operator verifies recovery. Reset reason,
actor, provider, tenant, and revision are audited.

## Privacy-safe usage evidence

`ai_usage_ledger` stores:

- tenant/user identifiers;
- operation, requested/effective provider, model, and region;
- data class and redaction flag;
- input/output/correlation SHA-256;
- estimated tokens, estimated cost, latency, outcome, fallback reason;
- governed prompt version and timestamp.

It has no raw input or output fields. Retrieval query evidence remains
redacted/hash-only.

## Retention

The policy retention range is 30–2555 days. The confirmed retention-purge API
removes expired AI usage and RAG query evidence for one tenant and writes a
tamper-evident audit event with cutoff and row counts. Never perform direct
database deletion. Schedule this API through the governed job framework after
runtime acceptance.

## Incident response

- `provider_not_allowed` / `provider_region_not_configured`: correct policy,
  do not bypass it.
- `data_classification_blocked`: keep local or lower the ceiling only with data
  owner/privacy approval.
- `usage_budget_not_configured`: create a hard budget.
- `*_budget_exceeded`: keep local, reconcile usage, approve a budget change.
- `provider_circuit_open`: inspect provider health and wait for probe/cooldown.
- `provider_fallback`: inspect timeout/HTTP/provider logs; content remains safe.

## Release proof

Prove missing policy, missing budget, missing cost rates, disallowed provider,
missing region, PII restriction, data ceiling, each budget, open circuit, and
active half-open probe all prevent the external provider method from running.
Inspect database schema and audit payloads to prove raw content is absent.

