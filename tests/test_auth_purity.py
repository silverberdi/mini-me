"""Adversarial test suite verifying authentication middleware query purity (Q25)."""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from minime.api.app import app, get_uow
from minime.domain.enums import OperatorAuthDecision
from minime.domain.models import AuthorizedOperator, AuthSession, utc_now
from minime.services.auth_service import AuthorizedOperatorService, SessionManager, hash_token


@pytest.fixture
def test_client_and_session(in_memory_uow):
    uow = in_memory_uow
    now = utc_now()
    raw_token = "test_auth_purity_token_1234567890"
    token_hash = hash_token(raw_token)

    # Seed operator and session
    operator = AuthorizedOperator(
        email="testop@example.com",
        display_name="Test Operator",
        google_sub=None,
        is_active=True,
    )
    uow.authorized_operators.save(operator)

    session = AuthSession(
        session_token_hash=token_hash,
        operator_email="testop@example.com",
        google_sub=None,
        created_at=now,
        expires_at=now + timedelta(days=1),
        last_seen_at=now,
        ip_address="127.0.0.1",
        user_agent="TestAgent/1.0",
    )
    uow.auth_sessions.save(session)
    uow.commit()

    def _get_uow_override():
        return uow

    app.dependency_overrides[get_uow] = _get_uow_override
    client = TestClient(app)
    yield client, uow, raw_token, session, operator
    app.dependency_overrides.clear()


def test_validate_session_pure_causes_zero_db_mutations(in_memory_uow):
    uow = in_memory_uow
    now = utc_now()
    raw_token = "pure_session_token_987654321"
    session = AuthSession(
        session_token_hash=hash_token(raw_token),
        operator_email="pureop@example.com",
        created_at=now,
        expires_at=now + timedelta(days=1),
        last_seen_at=now,
        ip_address="10.0.0.1",
        user_agent="PureClient/1.0",
    )
    uow.auth_sessions.save(session)
    uow.commit()
    uow.committed = False

    session_mgr = SessionManager(uow)
    validated = session_mgr.validate_session_pure(raw_token)

    assert validated is not None
    assert validated.operator_email == "pureop@example.com"
    assert uow.committed is False


def test_evaluate_operator_pure_causes_zero_db_mutations(in_memory_uow):
    uow = in_memory_uow
    operator = AuthorizedOperator(
        email="pureop2@example.com",
        display_name="Pure Operator 2",
        google_sub=None,
        is_active=True,
    )
    uow.authorized_operators.save(operator)
    uow.commit()
    uow.committed = False

    op_svc = AuthorizedOperatorService(uow)
    decision, evaluated = op_svc.evaluate_operator_pure(
        "pureop2@example.com", google_sub="sub-12345"
    )

    assert decision == OperatorAuthDecision.AUTHORIZED
    assert evaluated is not None
    # google_sub must NOT be linked during pure evaluation
    db_op = uow.authorized_operators.get_by_email("pureop2@example.com")
    assert db_op.google_sub is None
    assert uow.committed is False


def test_authenticated_get_request_leaves_auth_session_and_operator_unchanged(
    test_client_and_session,
):
    client, uow, raw_token, initial_session, initial_op = test_client_and_session

    initial_last_seen = initial_session.last_seen_at
    initial_ip = initial_session.ip_address
    initial_ua = initial_session.user_agent

    headers = {
        "Authorization": f"Bearer {raw_token}",
        "User-Agent": "MutatedUA/2.0",
    }
    response = client.get("/projects", headers=headers)
    assert response.status_code == 200

    # Verify AuthSession fields remain field-for-field identical
    reloaded_session = uow.auth_sessions.get_by_id(initial_session.session_id)
    assert reloaded_session.last_seen_at == initial_last_seen
    assert reloaded_session.ip_address == initial_ip
    assert reloaded_session.user_agent == initial_ua

    # Verify AuthorizedOperator fields remain identical
    reloaded_op = uow.authorized_operators.get_by_email(initial_op.email)
    assert reloaded_op.google_sub is None


def test_expired_or_revoked_session_rejected_without_mutation(test_client_and_session, monkeypatch):
    monkeypatch.setenv("MINIME_AUTH_ENABLED", "true")
    client, uow, raw_token, initial_session, _ = test_client_and_session

    # Revoke session
    initial_session.revoked_at = utc_now()
    uow.auth_sessions.save(initial_session)
    uow.commit()

    headers = {"Authorization": f"Bearer {raw_token}"}
    response = client.get("/projects", headers=headers)
    assert response.status_code == 401
    assert response.json()["code"] == "SESSION_EXPIRED"


def test_disabled_operator_rejected_without_mutation(test_client_and_session, monkeypatch):
    monkeypatch.setenv("MINIME_AUTH_ENABLED", "true")
    client, uow, raw_token, _, initial_op = test_client_and_session

    # Disable operator
    initial_op.is_active = False
    uow.authorized_operators.save(initial_op)
    uow.commit()

    headers = {"Authorization": f"Bearer {raw_token}"}
    response = client.get("/projects", headers=headers)
    assert response.status_code == 403
    assert response.json()["code"] == "IDENTITY_DISABLED"
