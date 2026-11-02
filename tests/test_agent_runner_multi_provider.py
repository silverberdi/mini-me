"""Tests verifying multi-provider execution decoupling for CliAgentRunner."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from minime.config import CliInvocationProfile
from minime.services.agent_runner import CliAgentRunner, ResolvedWorkflow


def test_resolve_workflow_supports_opencode(tmp_path: Path):
    skill_dir = tmp_path / ".agent" / "skills" / "openspec-verify-change"
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text("# Verify change\n")

    runner = CliAgentRunner()
    wf = runner.resolve_workflow(
        worktree_path=tmp_path,
        provider="opencode",
        operation="verify",
        change_name="test-change",
    )
    assert isinstance(wf, ResolvedWorkflow)
    assert wf.provider == "opencode"
    assert wf.operation == "verify"
    assert wf.dispatch_command == "$openspec-verify-change test-change"


def test_resolve_workflow_supports_antigravity(tmp_path: Path):
    wf_dir = tmp_path / ".agent" / "workflows"
    wf_dir.mkdir(parents=True, exist_ok=True)
    (wf_dir / "opsx-verify.md").write_text("# Opsx verify\n")

    runner = CliAgentRunner()
    wf = runner.resolve_workflow(
        worktree_path=tmp_path,
        provider="antigravity",
        operation="verify",
        change_name="test-change",
    )
    assert isinstance(wf, ResolvedWorkflow)
    assert wf.provider == "antigravity"
    assert wf.operation == "verify"
    assert wf.dispatch_command == "/opsx-verify test-change"


@pytest.mark.asyncio
async def test_antigravity_does_not_inject_codex_output_flags(tmp_path: Path):
    profile = CliInvocationProfile(
        provider="antigravity",
        role="implementer",
        executable="agy",
        args=["--print", "{prompt}"],
        prompt_transport="argument",
    )
    runner = CliAgentRunner(
        profiles={("execution", "antigravity"): profile}
    )

    schema = {"type": "object", "properties": {"status": {"type": "string"}}}
    response_file = tmp_path / "last-message.json"

    captured_cmds = []

    class FakeConfinement:
        def __init__(self, allowed_worktree_path=None):
            pass

        def validate_command_preflight(self, cwd=None):
            from minime.services.agent_confinement import ExternalActionResult, ExternalOutcome
            return ExternalActionResult(source_adapter="confinement", action="preflight", outcome=ExternalOutcome.SUCCESS, payload=True)

        def is_local_environment_preflight_error(self, err):
            return False

        def antigravity_auth_source(self, env):
            return "/tmp/auth"

        async def run_confined_async_subprocess(self, cmd, **kwargs):
            captured_cmds.append(list(cmd))
            from unittest.mock import MagicMock
            mock_proc = MagicMock()
            mock_proc.returncode = 0
            mock_proc.timed_out = False
            mock_proc.stdout = b'{"status": "ok"}'
            mock_proc.stderr = b""
            mock_proc.stdout_capture_truncated = False
            mock_proc.stderr_capture_truncated = False
            mock_proc.credential_rotation_detected = False
            mock_proc.credential_access_refresh_only = False
            return mock_proc

    with patch("minime.services.agent_runner.AgentProcessConfinement", FakeConfinement):
        res = await runner.run(
            worktree_path=tmp_path,
            prompt_context="Run verify",
            role="implementer",
            provider="antigravity",
            output_schema=schema,
            output_last_message_path=response_file,
        )

    assert res.exit_code == 0
    assert len(captured_cmds) == 1
    cmd = captured_cmds[0]

    # Must NOT have Codex-specific flags or incompatible schema flags
    assert "--output-schema" not in cmd
    assert "--output-last-message" not in cmd
    assert "--json-schema" not in cmd

    # Structured output should have been parsed and populated before cleanup
    assert not res.structured_output_missing
    assert res.final_response_status == "COMPLETE"
    assert json.loads(res.response_output) == {"status": "ok"}
