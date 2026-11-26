import json
import os
import subprocess
import sys
from pathlib import Path

from cryptography.fernet import Fernet
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from minime.db.models import Base, MCPCapabilityModel, MCPConnectionModel
from minime.mcp.runtime import MCPRuntimeProfileResolver
from minime.mcp.security import CredentialCipher
from tests.mcp_controlled_server import ControlledMCPHandler, controlled_server


def test_runtime_e2e_lists_and_invokes_global_tool_through_stdio_bridge(tmp_path):
    server, endpoint = controlled_server()
    ControlledMCPHandler.require_auth = True
    engine = create_engine(f"sqlite:///{tmp_path / 'mcp-runtime-e2e.sqlite'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    cipher = CredentialCipher(Fernet.generate_key())
    try:
        with Session(engine) as session:
            session.add(MCPConnectionModel(
                id="global-connection", project_id=None, name="global", endpoint=endpoint,
                transport="http", auth_type="bearer", status="ACTIVE",
                encrypted_credentials=cipher.encrypt({"token": "runtime-ephemeral"}),
            ))
            session.add(MCPCapabilityModel(
                id="global-tool", connection_id="global-connection", kind="tool",
                name="stitch_get", description="Read the controlled design",
                metadata_json={"inputSchema": {"type": "object", "properties": {"run_id": {"type": "string"}}}},
            ))
            session.commit()
            resolver = MCPRuntimeProfileResolver(session, cipher)
            profile = resolver.prepare("project-a", "run-e2e", "codex")
            assert profile.relay_path
            incoming = "\n".join([
                json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}),
                json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}),
                json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}),
                json.dumps({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
                    "name": "mcp_global_connection_stitch_get", "arguments": {"run_id": "run-e2e"},
                }}),
            ]) + "\n"
            env = os.environ.copy()
            src_path = str(Path(__file__).parents[1] / "src")
            env["PYTHONPATH"] = src_path + os.pathsep + env.get("PYTHONPATH", "")
            process = subprocess.run(
                [sys.executable, "-m", "minime.mcp.agent_bridge", profile.relay_path],
                input=incoming, text=True, capture_output=True, env=env, timeout=20, check=False,
            )
            assert process.returncode == 0, process.stderr
            messages = [json.loads(line) for line in process.stdout.splitlines()]
            assert messages[0]["result"]["serverInfo"]["name"] == "mini-me"
            assert messages[1]["result"]["tools"][0]["name"] == "mcp_global_connection_stitch_get"
            assert messages[2]["result"]["content"][0]["text"] == "controlled-result"
            assert "runtime-ephemeral" not in process.stdout
            resolver.close("run-e2e")
    finally:
        server.shutdown()
    assert ControlledMCPHandler.effect[-1] == {
        "tool": "stitch_get", "arguments": {"run_id": "run-e2e"}
    }
