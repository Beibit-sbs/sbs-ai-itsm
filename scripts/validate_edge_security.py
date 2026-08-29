from __future__ import annotations

import ipaddress
from pathlib import Path
import sys
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[1]


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def main() -> int:
    settings = (ROOT / "backend/app/core/config.py").read_text(encoding="utf-8")
    main_module = (ROOT / "backend/app/main.py").read_text(encoding="utf-8")
    nginx = (ROOT / "frontend/nginx.conf").read_text(encoding="utf-8")
    dockerfile = (ROOT / "frontend/Dockerfile").read_text(encoding="utf-8")
    compose = (ROOT / "docker-compose.prod.yml").read_text(encoding="utf-8")
    production_env = _load_env(ROOT / ".env.production.example")
    tests = (ROOT / "backend/tests/test_edge_trust.py").read_text(encoding="utf-8")

    _require(
        "TrustedHostMiddleware" in main_module
        and "allowed_hosts=settings.trusted_hosts" in main_module
        and "www_redirect=False" in main_module,
        "API TrustedHostMiddleware boundary is missing or redirecting invalid hosts",
    )
    _require(
        "trusted_hosts_must_be_valid" in settings
        and "FORWARDED_ALLOW_IPS must contain only bounded trusted proxy addresses"
        in settings,
        "Production host or forwarded-proxy configuration validation is missing",
    )
    _require(
        "test_trusted_host_boundary_rejects_unlisted_hosts_without_redirect" in tests,
        "Trusted Host rejection regression is missing",
    )

    for directive in (
        "server_tokens off;",
        "set_real_ip_from ${TLS_PROXY_CIDR};",
        "real_ip_header X-Forwarded-For;",
        "real_ip_recursive on;",
        "proxy_set_header X-Forwarded-For $remote_addr;",
        'add_header X-Content-Type-Options "nosniff" always;',
        'add_header Cross-Origin-Embedder-Policy "require-corp" always;',
        'add_header Cross-Origin-Opener-Policy "same-origin" always;',
        'add_header Cross-Origin-Resource-Policy "same-origin" always;',
        "base-uri 'self';",
        "form-action 'self';",
        "object-src 'none';",
        "add_header Content-Security-Policy",
    ):
        _require(directive in nginx, f"Nginx edge directive is missing: {directive}")
    _require(
        "$proxy_add_x_forwarded_for" not in nginx,
        "Nginx must overwrite, not append, the forwarded client identity",
    )
    _require(
        "NGINX_ENVSUBST_FILTER=" in dockerfile
        and "TLS_PROXY_CIDR|API_RATE_LIMIT|API_BURST|API_CONNECTION_LIMIT|LOGIN_RATE_LIMIT|LOGIN_RATE_BURST"
        in dockerfile
        and "/etc/nginx/templates/default.conf.template" in dockerfile,
        "Nginx template substitution is not restricted to the governed edge variables",
    )
    for directive in (
        "zone=sbs_api_per_ip:10m rate=${API_RATE_LIMIT};",
        "zone=sbs_login_per_ip:10m rate=${LOGIN_RATE_LIMIT};",
        "limit_req zone=sbs_api_per_ip burst=${API_BURST} nodelay;",
        "limit_req zone=sbs_login_per_ip burst=${LOGIN_RATE_BURST} nodelay;",
        "limit_conn sbs_connections_per_ip ${API_CONNECTION_LIMIT};",
    ):
        _require(directive in nginx, f"Governed edge limit is missing: {directive}")

    edge_subnet = ipaddress.ip_network(production_env["EDGE_SUBNET"], strict=True)
    edge_gateway = ipaddress.ip_address(production_env["EDGE_GATEWAY"])
    frontend_ip = ipaddress.ip_address(production_env["FRONTEND_EDGE_IP"])
    tls_proxy = ipaddress.ip_network(
        production_env["TLS_PROXY_CIDR"],
        strict=False,
    )
    forwarded = [
        ipaddress.ip_network(item.strip(), strict=False)
        for item in production_env["FORWARDED_ALLOW_IPS"].split(",")
        if item.strip()
    ]
    _require(edge_subnet.is_private, "EDGE_SUBNET must be private")
    _require(
        edge_gateway in edge_subnet
        and frontend_ip in edge_subnet
        and edge_gateway != frontend_ip,
        "Edge gateway and frontend identities must be distinct subnet members",
    )
    _require(
        tls_proxy.prefixlen == tls_proxy.max_prefixlen and edge_gateway in tls_proxy,
        "TLS_PROXY_CIDR must trust only the exact edge gateway",
    )
    _require(
        len(forwarded) == 1
        and forwarded[0].prefixlen == forwarded[0].max_prefixlen
        and frontend_ip in forwarded[0],
        "FORWARDED_ALLOW_IPS must trust only the exact frontend proxy",
    )
    _require(
        "ipv4_address: ${FRONTEND_EDGE_IP}" in compose
        and "FORWARDED_ALLOW_IPS: ${FORWARDED_ALLOW_IPS}" in compose
        and "subnet: ${EDGE_SUBNET}" in compose
        and "gateway: ${EDGE_GATEWAY}" in compose,
        "Compose does not bind the declared edge network identities",
    )
    _require(
        "headers={'Host': 'backend'}" in compose,
        "Backend healthcheck does not use a governed internal Host value",
    )

    cors_hosts = {
        str(urlsplit(origin.strip()).hostname).lower()
        for origin in production_env["BACKEND_CORS_ORIGINS"].split(",")
        if origin.strip() and urlsplit(origin.strip()).hostname
    }
    trusted_hosts = {
        item.strip().lower().rstrip(".")
        for item in production_env["TRUSTED_HOSTS"].split(",")
        if item.strip()
    }
    _require(
        cors_hosts
        and cors_hosts.issubset(trusted_hosts)
        and "backend" in trusted_hosts
        and "*" not in trusted_hosts,
        "TRUSTED_HOSTS must cover public origins and the internal scrape target",
    )

    print(
        "Edge security contract valid: "
        f"{len(trusted_hosts)} trusted hosts, "
        "1 TLS gateway, 1 frontend proxy identity."
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (KeyError, OSError, ValueError) as exc:
        print(f"Edge security contract invalid: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
