from __future__ import annotations

import time
from urllib.parse import parse_qs, urlsplit

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from jwt.algorithms import RSAAlgorithm
from sqlalchemy import select

from app.core.config import Settings
from app.models.audit_log import AuditLog
from app.models.external_identity import ExternalIdentity
from app.services.oidc import OidcClient, OidcError, OidcIdentityClaims, create_pkce_pair


def _oidc_settings(**overrides) -> Settings:
    values = {
        "oidc_enabled": True,
        "oidc_issuer_url": "https://login.example.com/realms/company",
        "oidc_client_id": "sbs-ai-itsm",
        "oidc_client_secret": "test-client-secret-value",
        "oidc_redirect_uri": "https://itsm.example.com/api/v1/auth/sso/callback",
        "oidc_allowed_algorithms": ["RS256"],
        "oidc_allowed_email_domains": ["sbs.local"],
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


@pytest.mark.asyncio
async def test_oidc_id_token_validation_checks_signature_claims_and_nonce() -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_jwk = RSAAlgorithm.to_jwk(private_key.public_key(), as_dict=True)
    public_jwk.update({"kid": "key-1", "alg": "RS256", "use": "sig"})
    settings = _oidc_settings()
    client = OidcClient(settings)
    client._jwks = {"keys": [public_jwk]}
    client._jwks_expires_at = time.monotonic() + 60
    now = int(time.time())
    id_token = jwt.encode(
        {
            "iss": settings.oidc_issuer_url,
            "sub": "employee-123",
            "aud": settings.oidc_client_id,
            "iat": now,
            "exp": now + 300,
            "nonce": "expected-nonce",
            "email": "manager@sbs.local",
            "email_verified": True,
            "name": "Operations Manager",
        },
        private_key,
        algorithm="RS256",
        headers={"kid": "key-1"},
    )

    claims = await client.validate_id_token(id_token, expected_nonce="expected-nonce")

    assert claims.subject == "employee-123"
    assert claims.email == "manager@sbs.local"
    with pytest.raises(OidcError, match="nonce"):
        await client.validate_id_token(id_token, expected_nonce="replayed-nonce")


def test_pkce_pair_has_verifier_and_sha256_challenge() -> None:
    verifier, challenge = create_pkce_pair()
    assert len(verifier) >= 43
    assert len(challenge) == 43
    assert verifier != challenge


class _FakeOidcClient:
    async def authorization_url(self, *, state: str, nonce: str, code_challenge: str) -> str:
        assert state and nonce and code_challenge
        return f"https://login.example.com/authorize?state={state}"

    async def exchange_code(self, *, code: str, code_verifier: str) -> dict[str, str]:
        assert code == "authorization-code"
        assert len(code_verifier) >= 43
        return {"id_token": "validated-by-fake"}

    async def validate_id_token(
        self, id_token: str, *, expected_nonce: str
    ) -> OidcIdentityClaims:
        assert id_token == "validated-by-fake"
        assert expected_nonce
        return OidcIdentityClaims(
            issuer="https://login.example.com/realms/company",
            subject="employee-123",
            email="manager@sbs.local",
            email_verified=True,
            full_name="Operations Manager",
        )


def test_oidc_authorization_code_flow_links_verified_account_and_issues_session(app) -> None:
    import app.api.v1.routes.auth as auth_route
    from app.db.session import SessionLocal

    auth_route.settings.oidc_enabled = True
    auth_route.settings.oidc_issuer_url = "https://login.example.com/realms/company"
    auth_route.settings.oidc_client_id = "sbs-ai-itsm"
    auth_route.settings.oidc_client_secret = "test-client-secret-value"
    auth_route.settings.oidc_redirect_uri = "https://itsm.example.com/api/v1/auth/sso/callback"
    auth_route.settings.oidc_allowed_email_domains = ["sbs.local"]
    auth_route.settings.oidc_allow_email_linking = True
    auth_route.oidc_client = _FakeOidcClient()

    with TestClient(app, follow_redirects=False) as client:
        config = client.get("/api/v1/auth/sso/config")
        assert config.status_code == 200
        assert config.json()["enabled"] is True

        start = client.get("/api/v1/auth/sso/login?return_to=/tickets")
        assert start.status_code == 302
        state = parse_qs(urlsplit(start.headers["location"]).query)["state"][0]
        callback = client.get(
            f"/api/v1/auth/sso/callback?code=authorization-code&state={state}"
        )
        assert callback.status_code == 302
        assert callback.headers["location"].startswith("/login?sso=success")

        refreshed = client.post("/api/v1/auth/refresh", json={})
        assert refreshed.status_code == 200
        assert refreshed.json()["user"]["email"] == "manager@sbs.local"

        with SessionLocal() as db:
            identity = db.scalar(
                select(ExternalIdentity).where(ExternalIdentity.subject == "employee-123")
            )
            assert identity is not None
            success = db.scalar(
                select(AuditLog).where(AuditLog.action == "oidc_login_success")
            )
            assert success is not None

        replay = client.get(
            f"/api/v1/auth/sso/callback?code=authorization-code&state={state}"
        )
        assert replay.status_code == 401
