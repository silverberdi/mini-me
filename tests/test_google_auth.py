"""Tests for Google OIDC Authentication, Operator Authorization, and Session Management."""

from __future__ import annotations

import os
import time
from unittest.mock import patch

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from jwt.algorithms import RSAAlgorithm
from tests.conftest import InMemoryPersistenceUnitOfWork

from minime.api.app import app, get_uow
from minime.domain.enums import AuthEventType
from minime.services.auth_service import (
    AuthorizedOperatorService,
    GoogleOidcService,
    SessionManager,
    generate_state_token,
)


@pytest.fixture
def auth_uow() -> InMemoryPersistenceUnitOfWork:
    return InMemoryPersistenceUnitOfWork()


@pytest.fixture
def rsa_key_pair():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()
    jwk_dict = RSAAlgorithm.to_jwk(public_key, as_dict=True)
    jwk_dict["kid"] = "test-key-id-001"
    jwk_dict["alg"] = "RS256"
    jwk_dict["use"] = "sig"
    return private_key, public_key, jwk_dict


@pytest.fixture
def client(auth_uow: InMemoryPersistenceUnitOfWork):
    app.dependency_overrides[get_uow] = lambda: auth_uow
    with patch.dict(os.environ, {"MINIME_AUTH_ENABLED": "true"}):
        test_client = TestClient(app, raise_server_exceptions=False)
        yield test_client
    app.dependency_overrides.clear()


# =============================================================================
# 1. Unauthenticated / Public Route Tests
# =============================================================================


def test_public_endpoints_accessible_without_auth(client: TestClient):
    """Public whitelist routes must be accessible without any session or bearer token."""
    # Health endpoint
    resp = client.get("/health")
    assert resp.status_code == 200

    # PWA login / dashboard shell
    resp = client.get("/")
    assert resp.status_code == 200

    # Auth status endpoint for unauthenticated caller
    resp = client.get("/api/v1/auth/me")
    assert resp.status_code == 200
    data = resp.json()
    assert data["authenticated"] is False
    assert data["operator"] is None


def test_unauthenticated_protected_endpoint_returns_401(client: TestClient):
    """Protected API endpoints must reject unauthenticated requests with 401 Unauthorized."""
    resp = client.get("/api/v1/dashboard/overview")
    assert resp.status_code == 401
    data = resp.json()
    assert data["code"] == "AUTH_REQUIRED"
    assert "Authentication required" in data["detail"]


def test_unauthenticated_direct_status_endpoint_returns_401(client: TestClient):
    """Direct root-level /status endpoint must reject unauthenticated requests with 401."""
    resp = client.get("/status")
    assert resp.status_code == 401


# =============================================================================
# 2. Session Validation Tests (Invalid, Expired, Revoked)
# =============================================================================


def test_invalid_session_token_returns_401(client: TestClient):
    """Non-existent or corrupted session token cookie must return 401."""
    client.cookies.set("minime_session", "invalid_non_existent_token_123456789")
    resp = client.get("/api/v1/dashboard/overview")
    assert resp.status_code == 401
    assert resp.json()["code"] in ("AUTH_REQUIRED", "SESSION_EXPIRED")


def test_expired_session_returns_401(client: TestClient, auth_uow: InMemoryPersistenceUnitOfWork):
    """Session past its expiration timestamp must return 401 SESSION_EXPIRED."""
    session_mgr = SessionManager(auth_uow)
    raw_token, session = session_mgr.create_session(
        operator_email="operator@example.com",
        lifetime_seconds=-10,  # Expired 10 seconds ago
    )
    client.cookies.set("minime_session", raw_token)
    resp = client.get("/api/v1/dashboard/overview")
    assert resp.status_code == 401
    assert resp.json()["code"] == "SESSION_EXPIRED"


def test_revoked_session_returns_401(client: TestClient, auth_uow: InMemoryPersistenceUnitOfWork):
    """Revoked session token must return 401."""
    session_mgr = SessionManager(auth_uow)
    raw_token, session = session_mgr.create_session(
        operator_email="operator@example.com",
        lifetime_seconds=3600,
    )
    session_mgr.revoke_session_by_id(session.session_id)

    client.cookies.set("minime_session", raw_token)
    resp = client.get("/api/v1/dashboard/overview")
    assert resp.status_code == 401


# =============================================================================
# 3. Operator Authorization Allowlist Tests (403 vs 200)
# =============================================================================


def test_non_allowlisted_operator_identity_returns_403(
    client: TestClient, auth_uow: InMemoryPersistenceUnitOfWork
):
    """Authenticated Google identity that is NOT allowlisted must return 403 Forbidden."""
    session_mgr = SessionManager(auth_uow)
    raw_token, session = session_mgr.create_session(
        operator_email="unauthorized_stranger@example.com",
        lifetime_seconds=3600,
    )
    client.cookies.set("minime_session", raw_token)
    resp = client.get("/api/v1/dashboard/overview")
    assert resp.status_code == 403
    assert resp.json()["code"] == "IDENTITY_NOT_ALLOWLISTED"


def test_disabled_operator_identity_returns_403(
    client: TestClient, auth_uow: InMemoryPersistenceUnitOfWork
):
    """Allowlisted operator account whose is_active=False must return 403 Forbidden."""
    op_svc = AuthorizedOperatorService(auth_uow)
    op_svc.seed_operator("disabled_admin@example.com", is_active=False)

    session_mgr = SessionManager(auth_uow)
    raw_token, session = session_mgr.create_session(
        operator_email="disabled_admin@example.com",
        lifetime_seconds=3600,
    )
    client.cookies.set("minime_session", raw_token)
    resp = client.get("/api/v1/dashboard/overview")
    assert resp.status_code == 403
    assert resp.json()["code"] == "IDENTITY_DISABLED"


def test_authorized_operator_succeeds_with_cookie(
    client: TestClient, auth_uow: InMemoryPersistenceUnitOfWork
):
    """Allowlisted active operator with valid session cookie receives 200 OK and dashboard data."""
    op_svc = AuthorizedOperatorService(auth_uow)
    op_svc.seed_operator("authorized_operator@example.com", display_name="Lead Ops")

    session_mgr = SessionManager(auth_uow)
    raw_token, session = session_mgr.create_session(
        operator_email="authorized_operator@example.com",
        lifetime_seconds=3600,
    )
    client.cookies.set("minime_session", raw_token)

    # 1. Check /api/v1/auth/me
    me_resp = client.get("/api/v1/auth/me")
    assert me_resp.status_code == 200
    me_data = me_resp.json()
    assert me_data["authenticated"] is True
    assert me_data["operator"]["email"] == "authorized_operator@example.com"
    assert me_data["operator"]["display_name"] == "Lead Ops"

    # 2. Check protected dashboard endpoint
    dash_resp = client.get("/api/v1/dashboard/overview")
    assert dash_resp.status_code == 200
    dash_data = dash_resp.json()
    assert "system_status" in dash_data


def test_authorized_operator_succeeds_with_bearer_token(
    client: TestClient, auth_uow: InMemoryPersistenceUnitOfWork
):
    """Allowlisted operator authenticating via Authorization Bearer header receives 200 OK."""
    op_svc = AuthorizedOperatorService(auth_uow)
    op_svc.seed_operator("bearer_user@example.com")

    session_mgr = SessionManager(auth_uow)
    raw_token, session = session_mgr.create_session(
        operator_email="bearer_user@example.com",
        lifetime_seconds=3600,
    )

    headers = {"Authorization": f"Bearer {raw_token}"}
    resp = client.get("/api/v1/dashboard/overview", headers=headers)
    assert resp.status_code == 200


# =============================================================================
# 4. Logout & Session Revocation Tests
# =============================================================================


def test_logout_invalidates_session_and_clears_cookie(
    client: TestClient, auth_uow: InMemoryPersistenceUnitOfWork
):
    """POST /api/v1/auth/logout revokes session, audits the event, and clears cookie."""
    op_svc = AuthorizedOperatorService(auth_uow)
    op_svc.seed_operator("logout_tester@example.com")

    session_mgr = SessionManager(auth_uow)
    raw_token, session = session_mgr.create_session(
        operator_email="logout_tester@example.com",
        lifetime_seconds=3600,
    )
    client.cookies.set("minime_session", raw_token)

    # Verify initially authenticated
    assert client.get("/api/v1/auth/me").json()["authenticated"] is True

    # Perform logout
    logout_resp = client.post("/api/v1/auth/logout")
    assert logout_resp.status_code == 200
    assert logout_resp.json()["status"] == "logged_out"

    # Check session was marked revoked in database
    db_session = auth_uow.auth_sessions.get_by_id(session.session_id)
    assert db_session is not None
    assert db_session.revoked_at is not None

    # Check audit log recorded LOGOUT
    events = auth_uow.auth_audit_events.list_events(operator_email="logout_tester@example.com")
    assert any(e.event_type == AuthEventType.LOGOUT for e in events)


# =============================================================================
# 5. Google OAuth Flow & OIDC ID Token Verification Tests
# =============================================================================


def test_google_login_endpoint_redirect_and_state_cookie(client: TestClient):
    """GET /api/v1/auth/google/login creates state cookie and redirects to Google."""
    with patch.dict(os.environ, {"GOOGLE_CLIENT_ID": "test-client-id.apps.googleusercontent.com"}):
        resp = client.get("/api/v1/auth/google/login", follow_redirects=False)
        assert resp.status_code == 302
        redirect_url = resp.headers.get("location", "")
        assert "accounts.google.com" in redirect_url
        assert "client_id=test-client-id.apps.googleusercontent.com" in redirect_url
        assert "state=" in redirect_url
        assert "minime_oauth_state" in resp.cookies


def test_oauth_callback_rejects_state_mismatch(
    client: TestClient, auth_uow: InMemoryPersistenceUnitOfWork
):
    """Callback with mismatched or missing state cookie must be rejected."""
    client.cookies.set("minime_oauth_state", "correct_state_token_123456789")
    resp = client.get("/api/v1/auth/google/callback?code=abc&state=wrong_state_token")
    assert resp.status_code == 400
    assert "Invalid or expired OAuth state" in resp.text

    # Audit event should reflect rejection
    events = auth_uow.auth_audit_events.list_events()
    assert any(e.event_type == AuthEventType.LOGIN_REJECTED for e in events)


def test_oidc_service_token_verification_lifecycle(rsa_key_pair):
    """Unit test GoogleOidcService ID token verification against simulated JWKS."""
    private_key, public_key, jwk_dict = rsa_key_pair
    client_id = "test-client-id.apps.googleusercontent.com"

    service = GoogleOidcService(client_id=client_id, client_secret="test-secret")
    service.set_jwks_cache({"keys": [jwk_dict]})

    # 1. Valid Token
    now = int(time.time())
    payload = {
        "iss": "https://accounts.google.com",
        "aud": client_id,
        "sub": "google-sub-12345",
        "email": "operator@company.com",
        "email_verified": True,
        "name": "Operator Name",
        "iat": now,
        "exp": now + 3600,
    }
    valid_jwt = jwt.encode(
        payload, private_key, algorithm="RS256", headers={"kid": "test-key-id-001"}
    )
    claims = service.verify_id_token(valid_jwt)
    assert claims["sub"] == "google-sub-12345"
    assert claims["email"] == "operator@company.com"

    # 2. Expired Token
    expired_payload = dict(payload, exp=now - 60)
    expired_jwt = jwt.encode(
        expired_payload, private_key, algorithm="RS256", headers={"kid": "test-key-id-001"}
    )
    with pytest.raises(ValueError, match="expired"):
        service.verify_id_token(expired_jwt)

    # 3. Audience Mismatch
    wrong_aud_payload = dict(payload, aud="unrelated-app.apps.googleusercontent.com")
    wrong_aud_jwt = jwt.encode(
        wrong_aud_payload, private_key, algorithm="RS256", headers={"kid": "test-key-id-001"}
    )
    with pytest.raises(ValueError, match="audience mismatch"):
        service.verify_id_token(wrong_aud_jwt)

    # 4. Unverified Email
    unverified_payload = dict(payload, email_verified=False)
    unverified_jwt = jwt.encode(
        unverified_payload, private_key, algorithm="RS256", headers={"kid": "test-key-id-001"}
    )
    with pytest.raises(ValueError, match="email is not verified"):
        service.verify_id_token(unverified_jwt)

    # 5. Invalid Issuer
    bad_iss_payload = dict(payload, iss="https://evil-issuer.com")
    bad_iss_jwt = jwt.encode(
        bad_iss_payload, private_key, algorithm="RS256", headers={"kid": "test-key-id-001"}
    )
    with pytest.raises(ValueError, match="Invalid ID token issuer"):
        service.verify_id_token(bad_iss_jwt)


def test_full_oauth_callback_flow_success(
    client: TestClient, auth_uow: InMemoryPersistenceUnitOfWork, rsa_key_pair
):
    """End-to-end OAuth callback exchange, token validation, operator lookup, and cookie issuance."""
    private_key, public_key, jwk_dict = rsa_key_pair
    client_id = "test-client-id.apps.googleusercontent.com"
    client_secret = "test-secret"
    operator_email = "primary_operator@example.com"

    # Seed authorized operator
    op_svc = AuthorizedOperatorService(auth_uow)
    op_svc.seed_operator(operator_email, display_name="Lead Engineer")

    # Generate signed test ID token
    now = int(time.time())
    payload = {
        "iss": "https://accounts.google.com",
        "aud": client_id,
        "sub": "google-sub-998877",
        "email": operator_email,
        "email_verified": True,
        "name": "Lead Engineer",
        "iat": now,
        "exp": now + 3600,
    }
    test_id_token = jwt.encode(
        payload, private_key, algorithm="RS256", headers={"kid": "test-key-id-001"}
    )

    state_token = generate_state_token()
    client.cookies.set("minime_oauth_state", state_token)

    env_patch = {
        "GOOGLE_CLIENT_ID": client_id,
        "GOOGLE_CLIENT_SECRET": client_secret,
    }
    with patch.dict(os.environ, env_patch):
        with patch.object(
            GoogleOidcService, "exchange_code", return_value={"id_token": test_id_token}
        ):
            with patch.object(GoogleOidcService, "fetch_jwks", return_value={"keys": [jwk_dict]}):
                resp = client.get(
                    f"/api/v1/auth/google/callback?code=mock_oauth_code_123&state={state_token}",
                    follow_redirects=False,
                )
                assert resp.status_code == 302
                assert resp.headers.get("location") == "/"
                assert "minime_session" in resp.cookies

                # Verify session was created in DB
                sessions = auth_uow.auth_sessions.list_by_operator_email(operator_email)
                assert len(sessions) == 1
                assert sessions[0].google_sub == "google-sub-998877"

                # Verify audit trail contains LOGIN_SUCCEEDED
                events = auth_uow.auth_audit_events.list_events(operator_email=operator_email)
                assert any(e.event_type == AuthEventType.LOGIN_SUCCEEDED for e in events)


def test_authorized_operators_env_seeding(auth_uow: InMemoryPersistenceUnitOfWork):
    """MINIME_AUTHORIZED_OPERATORS env var should be parsed and seeded into authorized_operators."""
    import asyncio
    from unittest.mock import PropertyMock

    from minime.api.app import lifespan

    with patch.dict(
        os.environ,
        {"MINIME_AUTHORIZED_OPERATORS": "op1@example.com, op2@example.com"},
    ):
        with patch(
            "minime.api.app.db_manager.__class__.sessionmaker", new_callable=PropertyMock
        ) as mock_sm:
            mock_sm.return_value = lambda: None
            with patch("minime.api.app.PostgresPersistenceUnitOfWork", return_value=auth_uow):

                async def run_lifespan():
                    async with lifespan(app):
                        pass

                asyncio.run(run_lifespan())

    op1 = auth_uow.authorized_operators.get_by_email("op1@example.com")
    op2 = auth_uow.authorized_operators.get_by_email("op2@example.com")
    assert op1 is not None and op1.is_active is True
    assert op2 is not None and op2.is_active is True
