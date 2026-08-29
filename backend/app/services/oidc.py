from __future__ import annotations

import asyncio
import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode, urlsplit

import httpx
import jwt
from jwt import PyJWK

from app.core.config import Settings, get_settings


MAX_PROVIDER_RESPONSE_BYTES = 1_048_576


class OidcError(RuntimeError):
    pass


@dataclass(frozen=True)
class OidcIdentityClaims:
    issuer: str
    subject: str
    email: str
    email_verified: bool
    full_name: str


class OidcClient:
    def __init__(self, settings: Settings | None = None, client: httpx.AsyncClient | None = None) -> None:
        self.settings = settings or get_settings()
        self._client = client
        self._metadata: dict[str, Any] | None = None
        self._metadata_expires_at = 0.0
        self._jwks: dict[str, Any] | None = None
        self._jwks_expires_at = 0.0
        self._lock = asyncio.Lock()

    async def _get_json(self, url: str) -> dict[str, Any]:
        owned_client = self._client is None
        client = self._client or httpx.AsyncClient(
            timeout=httpx.Timeout(10.0), follow_redirects=False
        )
        try:
            response = await client.get(url, headers={"Accept": "application/json"})
            response.raise_for_status()
            if len(response.content) > MAX_PROVIDER_RESPONSE_BYTES:
                raise OidcError("OIDC provider response is too large")
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise OidcError("OIDC provider request failed") from exc
        finally:
            if owned_client:
                await client.aclose()
        if not isinstance(payload, dict):
            raise OidcError("OIDC provider returned an invalid document")
        return payload

    @staticmethod
    def _require_https_endpoint(value: object, field: str, *, production: bool) -> str:
        endpoint = str(value or "").strip()
        parsed = urlsplit(endpoint)
        allowed_schemes = {"https"} if production else {"http", "https"}
        if parsed.scheme not in allowed_schemes or not parsed.hostname or parsed.fragment:
            raise OidcError(f"OIDC discovery contains an invalid {field}")
        return endpoint

    async def metadata(self, *, force: bool = False) -> dict[str, Any]:
        now = time.monotonic()
        if not force and self._metadata is not None and now < self._metadata_expires_at:
            return self._metadata
        async with self._lock:
            now = time.monotonic()
            if not force and self._metadata is not None and now < self._metadata_expires_at:
                return self._metadata
            issuer = (self.settings.oidc_issuer_url or "").rstrip("/")
            if not issuer:
                raise OidcError("OIDC issuer is not configured")
            payload = await self._get_json(f"{issuer}/.well-known/openid-configuration")
            discovered_issuer = str(payload.get("issuer") or "").rstrip("/")
            if not hmac.compare_digest(discovered_issuer, issuer):
                raise OidcError("OIDC discovery issuer does not match configured issuer")
            production = self.settings.app_env.lower() == "production"
            for field in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
                payload[field] = self._require_https_endpoint(
                    payload.get(field), field, production=production
                )
            supported = payload.get("id_token_signing_alg_values_supported")
            if isinstance(supported, list) and not set(self.settings.oidc_allowed_algorithms).intersection(
                str(item) for item in supported
            ):
                raise OidcError("OIDC provider does not support an allowed signing algorithm")
            auth_methods = payload.get("token_endpoint_auth_methods_supported")
            if isinstance(auth_methods, list) and self.settings.oidc_client_auth_method not in {
                str(item) for item in auth_methods
            }:
                raise OidcError("OIDC provider does not support the configured client authentication method")
            self._metadata = payload
            self._metadata_expires_at = now + self.settings.oidc_metadata_cache_seconds
            return payload

    async def authorization_url(
        self,
        *,
        state: str,
        nonce: str,
        code_challenge: str,
    ) -> str:
        metadata = await self.metadata()
        query = urlencode(
            {
                "client_id": self.settings.oidc_client_id or "",
                "redirect_uri": self.settings.oidc_redirect_uri or "",
                "response_type": "code",
                "scope": " ".join(self.settings.oidc_scopes),
                "state": state,
                "nonce": nonce,
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
            }
        )
        return f"{metadata['authorization_endpoint']}?{query}"

    async def exchange_code(self, *, code: str, code_verifier: str) -> dict[str, Any]:
        metadata = await self.metadata()
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.settings.oidc_redirect_uri or "",
            "client_id": self.settings.oidc_client_id or "",
            "code_verifier": code_verifier,
        }
        auth: httpx.BasicAuth | None = None
        if self.settings.oidc_client_auth_method == "client_secret_basic":
            auth = httpx.BasicAuth(
                self.settings.oidc_client_id or "", self.settings.oidc_client_secret or ""
            )
        else:
            data["client_secret"] = self.settings.oidc_client_secret or ""
        owned_client = self._client is None
        client = self._client or httpx.AsyncClient(
            timeout=httpx.Timeout(10.0), follow_redirects=False
        )
        try:
            response = await client.post(
                metadata["token_endpoint"],
                data=data,
                auth=auth,
                headers={"Accept": "application/json"},
            )
            response.raise_for_status()
            if len(response.content) > MAX_PROVIDER_RESPONSE_BYTES:
                raise OidcError("OIDC token response is too large")
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise OidcError("OIDC code exchange failed") from exc
        finally:
            if owned_client:
                await client.aclose()
        if not isinstance(payload, dict) or not isinstance(payload.get("id_token"), str):
            raise OidcError("OIDC token response does not contain an ID token")
        return payload

    async def _load_jwks(self, *, force: bool = False) -> dict[str, Any]:
        now = time.monotonic()
        if not force and self._jwks is not None and now < self._jwks_expires_at:
            return self._jwks
        metadata = await self.metadata()
        payload = await self._get_json(metadata["jwks_uri"])
        if not isinstance(payload.get("keys"), list):
            raise OidcError("OIDC provider returned an invalid JWKS document")
        self._jwks = payload
        self._jwks_expires_at = now + min(self.settings.oidc_metadata_cache_seconds, 900)
        return payload

    async def validate_id_token(self, id_token: str, *, expected_nonce: str) -> OidcIdentityClaims:
        try:
            header = jwt.get_unverified_header(id_token)
        except jwt.PyJWTError as exc:
            raise OidcError("OIDC ID token header is invalid") from exc
        algorithm = str(header.get("alg") or "")
        key_id = str(header.get("kid") or "")
        if algorithm not in self.settings.oidc_allowed_algorithms or not key_id:
            raise OidcError("OIDC ID token uses an unapproved signing key")

        selected_key: dict[str, Any] | None = None
        for force in (False, True):
            jwks = await self._load_jwks(force=force)
            selected_key = next(
                (
                    item
                    for item in jwks["keys"]
                    if isinstance(item, dict) and str(item.get("kid") or "") == key_id
                ),
                None,
            )
            if selected_key is not None:
                break
        if selected_key is None:
            raise OidcError("OIDC signing key is unknown")

        try:
            signing_key = PyJWK.from_dict(selected_key, algorithm=algorithm).key
            claims = jwt.decode(
                id_token,
                signing_key,
                algorithms=list(self.settings.oidc_allowed_algorithms),
                audience=self.settings.oidc_client_id,
                issuer=(self.settings.oidc_issuer_url or "").rstrip("/"),
                leeway=30,
                options={"require": ["iss", "sub", "aud", "exp", "iat", "nonce"]},
            )
        except (jwt.PyJWTError, ValueError) as exc:
            raise OidcError("OIDC ID token validation failed") from exc

        nonce = str(claims.get("nonce") or "")
        if not hmac.compare_digest(nonce, expected_nonce):
            raise OidcError("OIDC ID token nonce is invalid")
        subject = str(claims.get("sub") or "").strip()
        email = str(claims.get("email") or "").strip().lower()
        email_verified = claims.get("email_verified") is True
        if not subject or len(subject) > 255 or not email or "@" not in email:
            raise OidcError("OIDC ID token is missing required identity claims")
        if not email_verified:
            raise OidcError("OIDC email address is not verified")
        full_name = str(claims.get("name") or email.split("@", 1)[0]).strip()[:200]
        return OidcIdentityClaims(
            issuer=(self.settings.oidc_issuer_url or "").rstrip("/"),
            subject=subject,
            email=email,
            email_verified=True,
            full_name=full_name or email,
        )


def create_pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    challenge = jwt.utils.base64url_encode(hashlib.sha256(verifier.encode("ascii")).digest()).decode(
        "ascii"
    )
    return verifier, challenge
