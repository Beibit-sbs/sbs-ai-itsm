# Legacy integration simulation boundary — runtime acceptance pending

Status: `IMPLEMENTATION_COMPLETE_RUNTIME_ACCEPTANCE_PENDING`  
Date: 2026-07-29

## Outcome

The old integration registry can no longer look like a working production
connector suite. Demo providers report simulated or unsupported outcomes,
legacy mutations are unavailable outside demo mode, preview actions cannot
claim delivery/import/export success, and the production UI exposes the real
integration control plane instead.

## Implemented evidence

- authenticated runtime capability disclosure;
- permission-before-feature-state authorization on 23 demo mutation paths;
- production rejection of legacy create, enable, health, credential, webhook,
  retry, import, export, connection-test, and mock actions;
- explicit provider evidence classifier that reserves success for confirmed
  production providers;
- fail-closed retry outcomes and zero imported-record evidence;
- simulated export with `exported=false`;
- side-effect-free webhook simulation;
- warning presentation for every mock/simulated/planned/future status;
- migration `20260729_0069` to invalidate historical false success;
- regression tests-as-code, release-blocking control, static validator, and
  operator runbook.

Static Ruff, compile, TypeScript, OpenAPI, migration-head, contract, and release
gate evidence is reproducible locally. Representative PostgreSQL migration,
production-mode HTTP acceptance, isolated demo side-effect observation, and a
real production-control-plane remote delivery correlation remain pending in a
staging environment.
