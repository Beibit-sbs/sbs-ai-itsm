# Release Management Runbook

## Purpose

This runbook governs release trains and deployment promotion in SBS AI ITSM.
The operator workspace is `/releases`; the tenant-scoped API is
`/api/v1/releases`.

The process ensures that:

- only approved RFCs enter a release;
- every component is tied to a versioned, checksummed artifact;
- dependencies and readiness gates block unsafe promotion;
- Go/No-Go is independent from the release author and owner;
- environments are promoted in order;
- deployment, validation, failure, and rollback evidence remain auditable;
- production release and deployment performance is measurable.

## Roles and separation of duties

| Activity | Change operator | Change approver | Release executor | SaaS Root |
|---|---:|---:|---:|---:|
| Read portfolio, calendar, evidence, analytics | Yes | Yes | Yes | Yes |
| Create release and assemble scope | Yes | Yes | No | Yes |
| Verify package and decide manual gate | No | Yes | No | Yes |
| Make Go/No-Go decision | No | Yes | No | Yes |
| Plan deployment | No | Yes | No | Yes |
| Execute, validate, fail, or rollback deployment | No | Yes | Yes | Yes |

The release author or owner cannot make the Go/No-Go decision. Conditional Go
creates mandatory follow-up gates; deployment cannot start until they pass or
receive a documented waiver.

## Release lifecycle

```text
DRAFT -> PLANNING -> READY -> APPROVED -> DEPLOYING -> VALIDATING -> RELEASED
                        |                         \-> FAILED -> ROLLED_BACK
                        \-> NO-GO -> PLANNING
```

Cancellation is allowed only before active deployment. A failed release must be
resolved through rollback evidence, not hidden by cancellation.

## Configure promotion environments

1. Create tenant environments such as Test, Staging, and Production.
2. Assign each a unique promotion order.
3. Mark Production explicitly and require smoke tests.
4. Keep only currently usable targets active.
5. Review `current_version` after every successful deployment and rollback.

A production target must use the `PRODUCTION` type. Production cannot be the
first executed target: a lower target included in the release must succeed
first.

## Assemble a release

1. Create a release with service, semantic version, type, target date,
   production window, risk, scope, notes, validation, rollback, and
   communication plans.
2. Link approved RFCs in execution order. Draft or unapproved changes are
   rejected.
3. Add every deployable application, database, configuration, infrastructure,
   and documentation package.
4. Record immutable artifact URI, SHA-256 checksum, build reference, and
   package dependencies.
5. Have an authorized reviewer verify each checksum and record evidence.
6. Add predecessor releases when this release requires or follows them.

Circular release dependencies are rejected. A required predecessor must reach
`RELEASED` before the dependency readiness gate passes.

## Readiness gates

The platform derives these mandatory gates:

- linked changes are approved or later in their lifecycle;
- at least one package exists and every package is verified;
- dependencies are released;
- the production window is complete and valid;
- rollback plan is documented.

Authorized reviewers decide the Test, Security, Business, and custom manual
gates. Passing, failure, or waiver requires evidence and a comment. Waivers
must describe the accepted risk, owner, and compensating control.

Move the release to `READY` only after all structural checks pass. The
readiness score is informational; any mandatory failed or pending gate blocks
Go and deployment.

## Go/No-Go

1. Confirm readiness has not drifted since the last review.
2. Confirm decision maker is not the author or owner.
3. Record `GO`, `NO_GO`, or `CONDITIONAL` with a substantive protocol.
4. For conditional approval, list each condition and its owner.

The decision stores a complete readiness snapshot. `NO_GO` returns the release
to planning. Conditional controls become new mandatory gates and must be
closed before execution.

## Plan and execute deployments

1. After Go, plan each environment once and follow promotion order.
2. Schedule Production inside the approved release window.
3. Start only when no other deployment for the release is active and the
   previous planned target succeeded.
4. Record deployment logs before validation.
5. Run required smoke tests and attach validation evidence.
6. Mark success only when deployment and validation evidence both exist.
7. After successful Production validation, publish the release.

The platform re-evaluates readiness at deployment start. A package,
dependency, RFC, or conditional-gate regression blocks execution even if Go
was previously recorded.

## Failure and coordinated rollback

On failure:

1. Stop promotion and mark the active deployment `FAILED` with the observed
   reason and logs.
2. Execute the documented rollback plan.
3. Record recovery commands, artifact/version restored, health checks, smoke
   tests, and operator evidence.
4. Mark the deployment `ROLLED_BACK`.
5. Verify the environment registry returned to `previous_version`.
6. Open or link Incident/Problem records where required and communicate the
   outcome.

Never edit `current_version`, deployment status, or release history directly
in the database.

## Metrics and operating review

Review the 90-day dashboard weekly:

- release success rate;
- production deployment frequency;
- deployment failure rate;
- rollback rate;
- release lead time;
- deployment duration;
- active deployments.

Investigate deterioration by service, environment, release type, package, RFC,
and owner. The metric is a process signal, not a target to bypass gates.

## Troubleshooting

- HTTP 409: stale optimistic version, invalid lifecycle, another active
  deployment, missing previous promotion, or production outside its window.
- HTTP 422: incomplete evidence, failed readiness, dependency cycle, invalid
  checksum, or scope violation.
- HTTP 404: record is absent or outside the current tenant.
- Refresh the release before retrying a rejected mutation. Do not replay stale
  transition or deployment commands.

