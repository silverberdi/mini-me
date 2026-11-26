import pytest
import sys
import json
from pathlib import Path
from cryptography.fernet import Fernet
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from minime.db.models import Base, MCPConnectionModel
from minime.mcp.runtime import EphemeralMCPRelay, MCPRuntimeProfileResolver
from minime.mcp.security import CredentialCipher
from minime.services.agent_runner import CliAgentRunner
from minime.services.agent_confinement import AgentProcessConfinement


def test_inactive_connection_cannot_resolve_profile():
    engine = create_engine("sqlite://", future=True)
    Base.metadata.create_all(engine)
    cipher = CredentialCipher(Fernet.generate_key())
    with Session(engine) as session:
        session.add(MCPConnectionModel(id="c", project_id="p", name="x", endpoint="http://x", transport="http", auth_type="bearer", status="REVOKED", encrypted_credentials=cipher.encrypt({"token": "x"})))
        session.commit()
        with pytest.raises(PermissionError):
            MCPRuntimeProfileResolver(session, cipher).resolve("p", "run", "agent", "c")


def test_relay_is_owner_only_and_ephemeral():
    relay = EphemeralMCPRelay()
    path = relay.start()
    assert path.startswith(relay._directory.name)
    assert (path and __import__("os").stat(path).st_mode & 0o777) == 0o600
    relay.close()
    assert not __import__("os").path.exists(path)


def test_agent_cli_receives_only_ephemeral_stdio_bridge_configuration():
    codex = CliAgentRunner._configure_mcp_command(
        ["codex", "exec", "-", "--ephemeral"], "codex", "/private/runtime/relay.sock", "/tmp/work"
    )
    assert codex[2:4] == [
        "-c", f'mcp_servers.mini_me.command="{sys.executable}"'
    ]
    assert codex[4:6] == [
        "-c", 'mcp_servers.mini_me.args=["-m", "minime.mcp.agent_bridge", "/private/runtime/relay.sock"]'
    ]
    assert codex[6:8] == ["-c", 'mcp_servers.mini_me.cwd="/tmp/work"']
    agy = CliAgentRunner._antigravity_mcp_config(".minime/relay.sock", "/tmp/work")
    server = agy["mcpServers"]["mini_me"]
    assert server == {
        "command": sys.executable,
        "args": ["-m", "minime.mcp.agent_bridge", ".minime/relay.sock"],
        "cwd": "/tmp/work",
    }
    assert all("token" not in part.lower() for part in codex + server["args"])


def test_antigravity_mcp_config_lives_only_in_private_invocation_home(tmp_path):
    worktree = tmp_path / "worktree"
    runtime = tmp_path / "runtime"
    worktree.mkdir()
    runtime.mkdir()
    confinement = AgentProcessConfinement(
        str(worktree), runtime_root=str(runtime), private_state_parent=str(tmp_path)
    )
    config = CliAgentRunner._antigravity_mcp_config(".minime/relay.sock", str(worktree))
    with confinement.runtime_session(antigravity_mcp_config=config) as state:
        path = state.host_root / "home" / ".gemini" / "config" / "mcp_config.json"
        assert json.loads(path.read_text()) == config
        assert path.stat().st_mode & 0o777 == 0o600
        assert not (worktree / ".agents" / "mcp_config.json").exists()
    assert not path.exists()
