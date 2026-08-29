# Direct alert delivery integrity

## Purpose

This runbook governs the privileged direct-delivery endpoint
`POST /api/v1/jobs/alerts/execute/{alert_rule_id}`. It complements the primary
Prometheus → Alertmanager → event-to-incident path. It must never claim that an
email, Slack message, PagerDuty event, or webhook was delivered unless the
transport confirmed it.

Only SaaS Root may execute the endpoint. Every attempt writes
`jobs.alert.delivery_attempted` to the tamper-evident audit chain with the rule,
rollout, severity, attempted/succeeded channel counts, and confirmation state.
Titles, messages, identifiers, timeouts, metadata, and recipients are bounded.

## Configuration

Non-secret SMTP metadata belongs in `.env.production`:

```dotenv
JOBS_ALERT_SMTP_HOST=smtp.example.internal
JOBS_ALERT_SMTP_PORT=587
JOBS_ALERT_SMTP_FROM_ADDRESS=itsm-alerts@example.com
JOBS_ALERT_SMTP_USERNAME=itsm-alerts
JOBS_ALERT_SMTP_STARTTLS=true
JOBS_ALERT_EMAIL_RECIPIENTS=oncall@example.com,platform@example.com
JOBS_ALERT_TIMEOUT_SECONDS=10
```

Sensitive values are files under `SECRETS_DIR`, mounted by production Compose:

- `jobs_alert_smtp_password`
- `jobs_alert_slack_webhook_url`
- `jobs_alert_pagerduty_routing_key`
- `jobs_alert_webhook_url`

The production-secret initializer creates these files with unique disabled
sentinels. Replace only the channels that are approved. Never put these values
in `.env.production`, audit metadata, tickets, screenshots, or source control.

Slack accepts only `https://hooks.slack.com` or
`https://hooks.slack-gov.com`. PagerDuty always uses the fixed Events API v2
endpoint. A custom webhook must be an explicit deployment-owned HTTPS URL.
Callers cannot override any destination, credentials in URLs are rejected, and
outbound HTTP redirects are disabled.

Production SMTP requires STARTTLS and a non-loopback host. Username and password
must be configured together. Empty recipient lists fail closed.

## Confirmation semantics

- SMTP succeeds only when `send_message` returns no rejected recipients. The
  RFC Message-ID used in the delivered message is returned.
- Slack succeeds only after HTTP `200`; a provider request ID is returned only
  when Slack supplies it.
- PagerDuty succeeds only after HTTP `202` with a non-empty `dedup_key`.
- Custom webhook succeeds only after a `2xx`; its request ID is returned only
  when the remote endpoint supplies one.
- Zero confirmed channels sets
  `error = "No notification channel confirmed delivery"`.
- Mixed success sets `error = "One or more notification channels failed"`.

An HTTP request that completed is not, by itself, delivery evidence. Operators
must inspect `channels_succeeded`, per-channel `sent`, provider identifiers, and
the audit record.

## Deployment and rotation

1. Run `python scripts/check-production-env.py --env-file .env.production`.
2. Run `python scripts/validate_alert_delivery.py`.
3. Validate both production Compose configurations.
4. Deploy first to staging with a dedicated test recipient/service.
5. Trigger one alert per configured severity and retain provider-side evidence.
6. Verify the audit event contains no message body or secret.
7. Rotate a channel secret by replacing its secret file through the approved
   secret-manager workflow and restarting backend/worker processes.
8. Repeat the staging delivery proof after every endpoint or credential change.

## Incident response

For a false positive, duplicate, destination change, or suspected disclosure:

1. disable the affected secret with a disabled sentinel and restart services;
2. preserve the audit event and provider-side request/deduplication identifiers;
3. rotate the credential at the provider;
4. inspect `jobs.alert.delivery_attempted` and outbound proxy/provider logs;
5. verify no request could select a different destination;
6. open a security/operations incident and restore only after staging proof.

Do not weaken HTTPS, STARTTLS, host, timeout, root-only, or confirmation checks
to restore delivery.

## Acceptance

```powershell
python scripts/validate_alert_delivery.py
```

Runtime acceptance must prove unconfigured channels fail, empty recipients fail,
destination overrides fail without network access, redirects are not followed,
SMTP rejection is reported, Slack non-200 and PagerDuty non-202 fail, mixed
delivery is explicit, and every direct execution has one secrets-free audit
record.
