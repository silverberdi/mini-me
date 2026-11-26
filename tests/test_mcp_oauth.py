from datetime import UTC, datetime, timedelta

from cryptography.fernet import Fernet
import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from minime.db.models import (
    Base,
    MCPCapabilityModel,
    MCPConnectionModel,
    OrchestrationRunModel,
    OrchestrationStageEventModel,
    ProjectModel,
)
from minime.mcp.auth import OAuthStateStore
from minime.mcp.service import MCPConnectionService
from minime.mcp.security import CredentialCipher


def test_oauth_state_is_single_use_and_bound_to_session():
    store = OAuthStateStore()
    authorization = store.issue("session-a")
    assert not store.consume(authorization.state, "session-b")
    assert store.consume(authorization.state, "session-a")
    assert not store.consume(authorization.state, "session-a")


def test_oauth_authorization_encrypts_tokens_and_atomic_refresh_updates_access_token():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    cipher = CredentialCipher(Fernet.generate_key())

    class Provider:
        def __init__(self):
            self.calls = []

        def exchange_code(self, *_args, **_kwargs):
            self.calls.append("exchange")
            return {"access_token": "access-1", "refresh_token": "refresh-1", "expires_in": 1}

        def refresh(self, *_args, **_kwargs):
            self.calls.append("refresh")
            return {"access_token": "access-2", "expires_in": 3600}

    provider = Provider()
    with Session(engine) as session:
        row = MCPConnectionModel(
            id="oauth", project_id="p", name="controlled", endpoint="http://mcp",
            transport="http", auth_type="oauth2", status="PENDING",
        )
        session.add(row)
        session.commit()
        service = MCPConnectionService(session, cipher)
        # Discovery is replaced only to isolate token persistence; protocol E2E is covered separately.
        service.discover = lambda _row: type("Discovery", (), {"tools": [], "resources": []})()
        service.authorize_oauth(row, "https://provider/token", "code", "https://mini/callback", "client", "secret", provider)
        assert provider.calls == ["exchange"]
        assert row.status == "ACTIVE"
        assert b"refresh-1" not in row.encrypted_credentials
        row.access_token_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        session.commit()
        service.renew_oauth("p", "oauth", client=provider)
        assert provider.calls == ["exchange", "refresh"]
        assert cipher.decrypt(row.encrypted_credentials)["access_token"] == "access-2"
        assert cipher.decrypt(row.encrypted_credentials)["refresh_token"] == "refresh-1"

        # Verify ensure_renewed recovers from ERROR status and restores ACTIVE
        row.status = "ERROR"
        row.diagnostic_code = "MCP_REFRESH_FAILED"
        row.access_token_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        session.commit()
        renewed = service.ensure_renewed("p", "oauth", client=provider)
        assert renewed.status == "ACTIVE"
        assert renewed.diagnostic_code is None
        assert len(provider.calls) == 3


def test_mcp_oauth_401_renews_once_and_retries_the_rejected_call(monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    cipher = CredentialCipher(Fernet.generate_key())
    request = httpx.Request("POST", "https://mcp.example.invalid")
    unauthorized = httpx.HTTPStatusError(
        "401 Unauthorized", request=request, response=httpx.Response(401, request=request)
    )

    class Provider:
        def __init__(self):
            self.refresh_calls = []

        def refresh(self, endpoint, refresh_token, client_id, client_secret):
            self.refresh_calls.append((endpoint, refresh_token, client_id, client_secret))
            return {"access_token": "new-access", "expires_in": 3600}

    provider = Provider()
    monkeypatch.setattr("minime.mcp.service.OAuthClient", lambda: provider)
    with Session(engine) as session:
        session.add(ProjectModel(id="project", display_name="Project", repository="owner/project"))
        session.add(OrchestrationRunModel(
            id="run-401", project_id="project", change_name="oauth-refresh",
            base_sha="a" * 40, current_stage="IMPLEMENTING",
            current_candidate_sha="b" * 40,
        ))
        connection = MCPConnectionModel(
            id="oauth-401", project_id="project", name="oauth",
            endpoint="https://mcp.example.invalid", transport="http", auth_type="oauth2",
            status="ACTIVE",
            encrypted_credentials=cipher.encrypt({
                "access_token": "old-access", "refresh_token": "refresh-secret",
                "_oauth": {
                    "token_endpoint": "https://auth.example.invalid/token",
                    "client_id": "client-id", "client_secret": "client-secret",
                },
            }),
            access_token_expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        session.add(connection)
        session.add(MCPCapabilityModel(
            id="capability", connection_id="oauth-401", kind="tool", name="read_status",
            metadata_json={"annotations": {"readOnlyHint": True}},
        ))
        session.commit()
        service = MCPConnectionService(session, cipher)
        attempts = []

        class Transport:
            def call_tool(self, _tool, _arguments):
                attempts.append("call")
                if len(attempts) == 1:
                    raise unauthorized
                return {"result": "ok"}

        monkeypatch.setattr(service, "_transport", lambda _row: Transport())
        result = service.invoke(
            "project", "oauth-401", "read_status", {"detail": True}, run_id="run-401"
        )

        assert result == {"result": "ok"}
        assert attempts == ["call", "call"]
        assert provider.refresh_calls == [(
            "https://auth.example.invalid/token", "refresh-secret", "client-id", "client-secret"
        )]
        assert connection.status == "ACTIVE"
        stored = cipher.decrypt(connection.encrypted_credentials)
        assert stored["access_token"] == "new-access"
        assert stored["refresh_token"] == "refresh-secret"
        events = session.query(OrchestrationStageEventModel).filter_by(run_id="run-401").all()
        assert {event.event_type for event in events} == {
            "SRE_UNBLOCKER_ATTEMPTED", "SRE_UNBLOCKER_RESOLVED",
        }
        assert all("refresh-secret" not in str(event.evidence_references) for event in events)


def test_mcp_oauth_401_refresh_does_not_replay_tool_without_repeatability_evidence(monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    cipher = CredentialCipher(Fernet.generate_key())
    request = httpx.Request("POST", "https://mcp.example.invalid")
    unauthorized = httpx.HTTPStatusError(
        "401 Unauthorized", request=request, response=httpx.Response(401, request=request)
    )

    class Provider:
        def __init__(self):
            self.refresh_calls = 0

        def refresh(self, *_args):
            self.refresh_calls += 1
            return {"access_token": "new-access", "expires_in": 3600}

    provider = Provider()
    monkeypatch.setattr("minime.mcp.service.OAuthClient", lambda: provider)
    with Session(engine) as session:
        session.add(ProjectModel(id="project", display_name="Project", repository="owner/project"))
        session.add(OrchestrationRunModel(
            id="run-401-unsafe", project_id="project", change_name="oauth-refresh",
            base_sha="a" * 40, current_stage="IMPLEMENTING", current_candidate_sha="b" * 40,
        ))
        connection = MCPConnectionModel(
            id="oauth-401-unsafe", project_id="project", name="oauth",
            endpoint="https://mcp.example.invalid", transport="http", auth_type="oauth2",
            status="ACTIVE",
            encrypted_credentials=cipher.encrypt({
                "access_token": "old-access", "refresh_token": "refresh-secret",
                "_oauth": {
                    "token_endpoint": "https://auth.example.invalid/token",
                    "client_id": "client-id", "client_secret": "client-secret",
                },
            }),
        )
        session.add(connection)
        session.add(MCPCapabilityModel(
            id="capability-unsafe", connection_id="oauth-401-unsafe", kind="tool", name="write_record",
            metadata_json={},
        ))
        session.commit()
        service = MCPConnectionService(session, cipher)
        attempts = []

        class Transport:
            def call_tool(self, _tool, _arguments):
                attempts.append("call")
                raise unauthorized

        monkeypatch.setattr(service, "_transport", lambda _row: Transport())
        try:
            service.invoke("project", "oauth-401-unsafe", "write_record", {"value": 1}, run_id="run-401-unsafe")
        except Exception as exc:
            assert "repeatability was not proven" in str(exc)
        else:
            raise AssertionError("unsafe operation should not be replayed")

        assert attempts == ["call"]
        assert provider.refresh_calls == 1
        assert connection.status == "ACTIVE"
        events = session.query(OrchestrationStageEventModel).filter_by(run_id="run-401-unsafe").all()
        assert [event.event_type for event in events] == ["SRE_UNBLOCKER_ATTEMPTED", "SRE_UNBLOCKER_ESCALATED"]
        assert "tool_repeatability_unproven" in str(events[-1].evidence_references)
        assert all("refresh-secret" not in str(event.evidence_references) for event in events)
