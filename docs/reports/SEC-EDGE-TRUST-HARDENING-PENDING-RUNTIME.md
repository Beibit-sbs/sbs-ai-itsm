# Edge trust hardening — runtime acceptance pending

## Outcome

The local production implementation now has an explicit Host and proxy-identity
boundary. FastAPI rejects unlisted Host values, Nginx accepts client identity
only from one declared TLS gateway, and Uvicorn accepts forwarded information
only from the statically addressed frontend proxy.

## Implemented controls

- exact `TRUSTED_HOSTS` parsing and production validation;
- bounded `FORWARDED_ALLOW_IPS` validation with wildcard/default-route rejection;
- `TrustedHostMiddleware` with redirects disabled;
- isolated configurable edge subnet, gateway, and frontend address;
- Nginx real-IP trust limited to `TLS_PROXY_CIDR`;
- sanitized one-value `X-Forwarded-For` propagation;
- templating limited to a single non-secret Nginx variable;
- Host-aware backend healthcheck and internal Prometheus compatibility;
- production preflight, contract validator, CI/local gate integration target,
  regression tests, and operator runbook.

## Current evidence

Static validation covers configuration relationships and all required edge
directives. Docker Compose configuration parsing is the strongest safe local
topology check currently available.

Runtime deployment, TLS-proxy behavior, forged-header rejection, real client
audit attribution, and Prometheus scrape continuity remain explicitly pending
until an executable production-equivalent runtime is available.
