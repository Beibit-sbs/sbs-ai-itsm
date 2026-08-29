from fastapi.testclient import TestClient

from app.core.config import Settings
from app.services.mfa import (
    consume_recovery_code,
    current_totp,
    decrypt_totp_secret,
    encode_recovery_code_hashes,
    encrypt_totp_secret,
    generate_recovery_codes,
    verify_totp,
)


def _password_login(client: TestClient, email: str, password: str) -> dict:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert response.status_code == 200
    return response.json()


def _enroll(
    client: TestClient,
    email: str,
    password: str,
) -> tuple[str, list[str], str]:
    session = _password_login(client, email, password)
    headers = {"Authorization": f"Bearer {session['access_token']}"}
    started = client.post(
        "/api/v1/auth/mfa/enroll",
        headers=headers,
        json={"current_password": password},
    )
    assert started.status_code == 200
    secret = started.json()["secret"]
    confirmed = client.post(
        "/api/v1/auth/mfa/confirm",
        headers=headers,
        json={"code": current_totp(secret)},
    )
    assert confirmed.status_code == 200
    recovery_codes = confirmed.json()["recovery_codes"]
    assert len(recovery_codes) == 10
    return secret, recovery_codes, session["access_token"]


def _mfa_login(
    client: TestClient,
    email: str,
    password: str,
    code: str,
) -> tuple[dict, str]:
    challenge = _password_login(client, email, password)
    assert challenge["mfa_required"] is True
    verified = client.post(
        "/api/v1/auth/mfa/verify-login",
        json={"challenge_token": challenge["challenge_token"], "code": code},
    )
    assert verified.status_code == 200
    return verified.json(), challenge["challenge_token"]


def test_totp_matches_rfc_6238_sha1_vector_and_prevents_replay() -> None:
    secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"
    assert current_totp(secret, at_time=59) == "287082"
    assert verify_totp(secret, "287082", at_time=59) == 1
    assert verify_totp(secret, "287082", at_time=59, last_used_step=1) is None


def test_mfa_secret_encryption_and_recovery_codes_are_one_time() -> None:
    settings = Settings(
        _env_file=None,
        database_url="sqlite:///mfa-test.db",
        mfa_encryption_key="mfa-test-key-with-more-than-thirty-two-characters",
    )
    secret = "JBSWY3DPEHPK3PXP"
    ciphertext = encrypt_totp_secret(secret, settings)
    assert ciphertext != secret
    assert decrypt_totp_secret(ciphertext, settings) == secret

    recovery_codes = generate_recovery_codes(2)
    hashes = encode_recovery_code_hashes(recovery_codes, settings)
    assert recovery_codes[0] not in hashes
    valid, remaining = consume_recovery_code(hashes, recovery_codes[0], settings)
    assert valid is True
    replayed, _ = consume_recovery_code(remaining, recovery_codes[0], settings)
    assert replayed is False


def test_totp_enrollment_login_refresh_and_disable_flow(app) -> None:
    with TestClient(app) as client:
        secret, recovery_codes, _ = _enroll(
            client,
            "admin@sbs.local",
            "Sbs!2026",
        )
        session, challenge_token = _mfa_login(
            client,
            "admin@sbs.local",
            "Sbs!2026",
            current_totp(secret),
        )
        assert session["user"]["mfa_enabled"] is True
        assert session["user"]["mfa_verified"] is True
        token = session["access_token"]

        replay = client.post(
            "/api/v1/auth/mfa/verify-login",
            json={"challenge_token": challenge_token, "code": current_totp(secret)},
        )
        assert replay.status_code == 401

        refreshed = client.post("/api/v1/auth/refresh", json={})
        assert refreshed.status_code == 200
        assert refreshed.json()["user"]["mfa_verified"] is True
        token = refreshed.json()["access_token"]

        status_response = client.get(
            "/api/v1/auth/mfa/status",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert status_response.status_code == 200
        assert status_response.json()["enabled"] is True
        assert status_response.json()["recovery_codes_remaining"] == 10

        disabled = client.post(
            "/api/v1/auth/mfa/disable",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "current_password": "Sbs!2026",
                "code": recovery_codes[0],
            },
        )
        assert disabled.status_code == 200
        assert disabled.json()["disabled"] is True

        revoked = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert revoked.status_code == 401


def test_recovery_code_is_consumed_during_login(app) -> None:
    with TestClient(app) as client:
        _secret, recovery_codes, _ = _enroll(
            client,
            "manager@sbs.local",
            "Sbs!2026",
        )
        session, _ = _mfa_login(
            client,
            "manager@sbs.local",
            "Sbs!2026",
            recovery_codes[0],
        )
        assert session["user"]["mfa_verified"] is True

        second_challenge = _password_login(
            client,
            "manager@sbs.local",
            "Sbs!2026",
        )
        replay = client.post(
            "/api/v1/auth/mfa/verify-login",
            json={
                "challenge_token": second_challenge["challenge_token"],
                "code": recovery_codes[0],
            },
        )
        assert replay.status_code == 401


def test_admin_mfa_reset_requires_verified_session_and_is_tenant_scoped(app) -> None:
    with TestClient(app) as client:
        manager_secret, _, _ = _enroll(
            client,
            "manager@sbs.local",
            "Sbs!2026",
        )
        assert manager_secret
        admin_secret, _, unverified_admin_token = _enroll(
            client,
            "admin@sbs.local",
            "Sbs!2026",
        )

        admin_session, _ = _mfa_login(
            client,
            "admin@sbs.local",
            "Sbs!2026",
            current_totp(admin_secret),
        )
        headers = {"Authorization": f"Bearer {admin_session['access_token']}"}
        overview = client.get("/api/v1/security/mfa/overview", headers=headers)
        assert overview.status_code == 200
        assert overview.json()["enrolled_users"] == 2
        manager = next(
            item
            for item in overview.json()["users"]
            if item["email"] == "manager@sbs.local"
        )

        blocked_reset = client.post(
            f"/api/v1/security/users/{manager['user_id']}/mfa/reset",
            headers={"Authorization": f"Bearer {unverified_admin_token}"},
        )
        assert blocked_reset.status_code == 403

        reset = client.post(
            f"/api/v1/security/users/{manager['user_id']}/mfa/reset",
            headers=headers,
        )
        assert reset.status_code == 200
        assert reset.json()["reset"] is True

        manager_login = _password_login(
            client,
            "manager@sbs.local",
            "Sbs!2026",
        )
        assert manager_login["user"]["mfa_enabled"] is False
