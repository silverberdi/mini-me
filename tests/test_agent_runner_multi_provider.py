"""Tests verifying multi-provider execution decoupling for CliAgentRunner."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from minime.config import CliInvocationProfile
from minime.services.agent_runner import CapacityExhaustedError, CliAgentRunner, ResolvedWorkflow


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
async def test_inflight_apply_uses_configured_fallback_profile_and_native_workflow(
    tmp_path: Path, monkeypatch
):
    skill = tmp_path / ".agents" / "skills" / "openspec-apply-change" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("# Native Apply workflow\n")

    class Capacity:
        def can_execute_inflight_apply(self, project_id, run_id, provider):
            assert (project_id, run_id, provider) == ("p1", "r1", "codex")
            return False

        def fallback_provider_for_inflight_apply(self, project_id, run_id, provider):
            assert (project_id, run_id, provider) == ("p1", "r1", "codex")
            return "opencode"

        def can_admit_change(self, project_id):
            raise AssertionError("An in-flight Apply must use the stage-specific capacity decision")

    fallback = CliInvocationProfile(
        provider="opencode",
        role="implementer",
        executable="opencode",
        args=(),
        prompt_transport="stdin",
        model="openrouter/deepseek/deepseek-chat",
        canonical_provider_id="openrouter",
        harness_id="opencode",
    )
    from minime.config import AppConfig, OpenCodeCapabilityConfig, ProjectConfig

    app_config = AppConfig(
        projects={
            "p1": ProjectConfig(
                repository="org/repo",
                opencode=OpenCodeCapabilityConfig(
                    enabled=True,
                    provider="deepseek",
                    model="deepseek/deepseek-flash",
                    api_key_env="DEEPSEEK_API_KEY",
                    roles=["execution"],
                ),
            )
        }
    )
    monkeypatch.setattr("minime.services.agent_runner.load_config", lambda: app_config)
    runner = CliAgentRunner(
        capacity_service=Capacity(),
        profiles={("fallback", "opencode"): fallback},
    )
    primary_workflow = runner.resolve_workflow(
        tmp_path, "codex", "apply", "change-1"
    )

    class FakeConfinement:
        def __init__(self, allowed_worktree_path=None):
            pass

        def validate_command_preflight(self, cwd=None):
            from minime.services.agent_confinement import ExternalActionResult, ExternalOutcome
            return ExternalActionResult(
                source_adapter="confinement", action="preflight", outcome=ExternalOutcome.SUCCESS, payload=True
            )

        def is_local_environment_preflight_error(self, err):
            return False

    class FakeOpenCodeAdapter:
        def __init__(self, config, **kwargs):
            self.config = config

        async def dispatch(self, request):
            assert request.operation == "apply"
            assert request.role == "execution"
            assert self.config.provider == "openrouter"
            assert self.config.model == "openrouter/deepseek/deepseek-chat"
            return SimpleNamespace(
                accepted=True,
                evidence=SimpleNamespace(
                    exit_code=0,
                    timed_out=False,
                    failure_reason=None,
                    stdout=["Apply finished"],
                    stderr=[],
                ),
            )

    with (
        patch("minime.services.agent_runner.AgentProcessConfinement", FakeConfinement),
        patch("minime.services.opencode_adapter.OpenCodeAdapter", FakeOpenCodeAdapter),
    ):
        result = await runner.run(
            worktree_path=tmp_path,
            prompt_context="Continue the same Change",
            project_id="p1",
            run_id="r1",
            role="implementer",
            provider="codex",
            workflow=primary_workflow,
        )

    assert result.exit_code == 0
    assert result.workflow.provider == "opencode"
    assert result.provider_used == "openrouter"
    assert result.profile_used == "fallback"
    assert result.model_used == "openrouter/deepseek/deepseek-chat"


def test_inflight_fallback_is_never_used_for_independent_review():
    class Capacity:
        fallback_calls = 0

        def can_admit_change(self, project_id):
            return False, "primary capacity unavailable"

        def fallback_provider_for_inflight_apply(self, project_id, run_id, provider):
            self.fallback_calls += 1
            return "opencode"

        def can_execute_inflight_apply(self, project_id, run_id, provider):
            self.fallback_calls += 1
            return False

    capacity = Capacity()
    runner = CliAgentRunner(capacity_service=capacity)
    workflow = ResolvedWorkflow(
        provider="codex",
        operation="apply",
        workflow_name="openspec-apply-change",
        workflow_path=".agents/skills/openspec-apply-change/SKILL.md",
        workflow_sha256="workflow-sha",
        change_name="change-1",
        dispatch_command="$openspec-apply-change change-1",
    )

    with pytest.raises(CapacityExhaustedError):
        runner.check_capacity_preflight(
            "p1", "codex", "reviewer", run_id="r1", workflow=workflow
        )
    assert capacity.fallback_calls == 0


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
