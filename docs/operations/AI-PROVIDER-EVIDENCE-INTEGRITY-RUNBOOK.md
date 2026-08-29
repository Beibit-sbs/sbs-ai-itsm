# AI PROVIDER EVIDENCE INTEGRITY RUNBOOK

## Purpose

Keep local AI simulation, runtime fallback, and confirmed external-provider
execution operationally distinct. A useful local recommendation is not evidence
that OpenAI or Gemini was contacted.

## Evidence states

- `LOCAL_SIMULATION`: the configured/effective provider is the deterministic
  local `mock` classifier. External readiness and connection-test success are
  false.
- `FALLBACK_UNCONFIGURED`: OpenAI or Gemini was selected but its credential is
  absent. The effective provider is local `mock`.
- `EXTERNAL_CONFIGURED`: an external provider credential and model are present.
  This means configured, not continuously healthy.
- Per-result `EXTERNAL_PROVIDER`: the returned classification identifies the
  requested external provider.
- Per-result `LOCAL_SIMULATION` with `fallback_used=true`: an external provider
  was requested, but the returned result came from the local classifier.

## Operator procedure

1. Open `Administration -> AI Provider Configuration`.
2. Select OpenAI or Gemini, enter the provider credential and model, and run
   `Test current config`.
3. Treat only a non-simulated `success=true` response from that requested
   provider as connection-test evidence. The mock test always returns
   `simulation=true` and `success=false`.
4. Save the external provider only after a successful test. Secret values must
   remain write-only in the UI and audit payloads.
5. In Copilot, verify the result shows requested provider, effective provider,
   model, execution mode, and fallback warning where applicable.
6. In the grounded RAG assistant, verify local extractive answers and external
   provider fallback show the same requested/effective provider evidence. A
   grounded answer can be citation-valid while still using local fallback.
7. Review the AI usage ledger for `SUCCESS`, `BLOCKED`, and `FALLBACK` outcomes.
   A mock result must have zero external-provider cost.

## Validation

Run:

```text
python scripts/validate_ai_provider_evidence.py
```

The release contract must also pass:

```text
python scripts/run_local_release_gate.py --python <python> --node <node> --docker <docker> --git <git>
```

## Incident response

- If a mock result is presented as external success, disable external AI
  activation, retain the suggestion and usage-ledger records, and open a
  security incident for evidence misclassification.
- If the external provider is configured but results fall back, inspect the
  provider transport, HTTP status, response shape, runtime policy decision, and
  circuit-breaker state. Do not relabel fallback records after the fact.
- If credentials may have leaked, rotate them in the provider console and in
  Administration. Confirm API responses and audit metadata still expose only
  configured flags.

## Runtime acceptance still required

Before production sign-off, test each enabled external provider against the
server deployment, retain the audited connection-test result, force a controlled
provider failure, and verify the user-facing result plus usage ledger both show
fallback without external success or cost for both classification and grounded
RAG answers.
