# SEC-AI-PROVIDER-EVIDENCE-INTEGRITY — PENDING RUNTIME

## Local implementation

- Provider status now separates configured and effective providers and exposes
  `LOCAL_SIMULATION`, `FALLBACK_UNCONFIGURED`, or `EXTERNAL_CONFIGURED`.
- The local mock configuration test returns `simulation=true` and
  `success=false`; it can no longer be interpreted as a working OpenAI/Gemini
  connection.
- Invalid, unavailable, policy-blocked, or malformed external classifications
  return effective provider `mock`, model `keyword-rules-v1`, and explicit
  fallback evidence.
- `/ai/classify` preserves requested provider, effective provider, model,
  `provider_mock`, `fallback_used`, and execution mode.
- `/ai/rag/ask` preserves the same evidence. Citation grounding remains
  separate from provider provenance, so a citation-valid local extractive
  answer cannot be mistaken for an external LLM response.
- Copilot and both administration surfaces display simulation and fallback
  separately from a configured external provider; the RAG assistant does the
  same for grounded answers. The executive dashboard shows configured to
  effective provider, execution mode, and external-configuration state instead
  of a generic readiness badge.
- The usage ledger and provider circuit records distinguish `SUCCESS`,
  `BLOCKED`, and `FALLBACK`; fallback has no external-provider cost.
- Static enforcement is provided by
  `scripts/validate_ai_provider_evidence.py` and release control
  `SEC-AI-PROVIDER-EVIDENCE-INTEGRITY`.

## Local evidence

The implementation is included in the M1 local/static release gate. Unit
regressions cover default mock status, mock connection testing, invalid external
output fallback, and classify-response evidence.

## Deferred runtime gate

Status: `IMPLEMENTATION_COMPLETE_RUNTIME_GATE_PENDING`.

Runtime acceptance requires:

1. successful audited OpenAI and/or Gemini connection testing from the target
   server environment;
2. one confirmed external classification with provider/model evidence;
3. one confirmed external grounded answer with citation and provider evidence;
4. controlled transport, HTTP, and malformed-response failures;
5. matching Copilot, RAG, and usage-ledger `FALLBACK` evidence with zero
   external cost;
6. verification that secrets never appear in API, audit, log, or UI output.

No production-readiness claim is made until this evidence is retained and
approved by AI Platform Operations and Security Operations.
