# Edge trust boundary runbook

## Purpose

This runbook governs the client-identity and Host-header boundary between the
public TLS endpoint and SBS AI ITSM. The production chain is:

`client -> approved TLS reverse proxy -> frontend Nginx -> FastAPI`

Each hop has a separate, bounded identity. No application component trusts an
arbitrary `Host`, `X-Forwarded-For`, or `X-Forwarded-Proto` value.

## Required topology

The reference production Compose topology uses these configurable values:

| Variable | Purpose | Reference value |
| --- | --- | --- |
| `EDGE_SUBNET` | Dedicated private Compose edge network | `172.30.250.0/24` |
| `EDGE_GATEWAY` | Host/TLS-proxy identity seen by Nginx | `172.30.250.1` |
| `FRONTEND_EDGE_IP` | Stable Nginx identity seen by FastAPI | `172.30.250.10` |
| `TLS_PROXY_CIDR` | Exact proxy address Nginx may trust | `172.30.250.1/32` |
| `FORWARDED_ALLOW_IPS` | Exact Nginx address Uvicorn may trust | `172.30.250.10` |
| `TRUSTED_HOSTS` | Exact public API hosts plus `backend` for Prometheus | `itsm.example.com,backend` |

Before first server deployment, choose an unused private subnet and keep the
gateway and frontend addresses distinct. Do not use `*`, `0.0.0.0/0`, broad
RFC1918 ranges, or an unbounded IPv6 network for either proxy trust variable.

## TLS proxy requirements

The outer TLS reverse proxy must:

1. accept only the approved public server names;
2. terminate TLS with the approved certificate and modern protocol policy;
3. replace any inbound `X-Forwarded-For` value with the actual client address;
4. set `X-Forwarded-Proto: https`;
5. connect only to the loopback-bound frontend port;
6. set HSTS at the TLS boundary after HTTPS cutover is verified.

HSTS is intentionally not emitted by the bundled HTTP-only Nginx container.
Adding it there could incorrectly mark a non-TLS internal endpoint as secure.

## Application enforcement

- Nginx trusts forwarded client identity only from `TLS_PROXY_CIDR`.
- Nginx overwrites the downstream `X-Forwarded-For` header with its sanitized
  `$remote_addr`; it never appends an untrusted inbound chain.
- Uvicorn processes proxy headers only from `FORWARDED_ALLOW_IPS`.
- FastAPI `TrustedHostMiddleware` rejects unknown Host values with `400` and
  does not redirect them.
- Production settings validation requires every CORS hostname to appear in
  `TRUSTED_HOSTS` and rejects wildcard proxy trust.

The internal `backend` Host is required for the Prometheus scrape and backend
healthcheck. It is not a public DNS name and must never be exposed by the outer
TLS proxy.

## Pre-deployment validation

Run:

```powershell
python scripts/validate_edge_security.py
python scripts/check-production-env.py --env-file .env.production
docker compose -f docker-compose.prod.yml --env-file .env.production config --quiet
```

Then validate on the target server:

1. An approved public Host reaches readiness through HTTPS.
2. An unknown Host is rejected by the TLS proxy or returns `400`.
3. A direct external connection to backend port `8000` is impossible.
4. A request carrying a forged forwarded address cannot change the audit IP.
5. Login, administrative, integration, and security audit events contain the
   real client address.
6. Prometheus continues to scrape `/api/v1/metrics`.

Record sanitized request/response evidence, the selected network values,
firewall rules, proxy configuration hash, and representative audit-event IDs.

## Change and rollback

Changing the edge subnet or frontend address requires a coordinated update of
all six topology variables and a Compose recreation. If client identity or
healthchecks fail, remove public traffic, restore the last approved values,
recreate the frontend/backend containers, and repeat the acceptance sequence.
