"""Focused regression coverage for the F3 audit corrections."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from minime.services.agent_runner import AgentExecutionResult
from minime.services.orchestration_coordinator import NativeOrchestrationCoordinator


class ScriptedRunner:
    def __init__(self, output: str, exit_code: int = 0) -> None:
        self.output = output
        self.exit_code = exit_code
        self.calls: list[str] = []

    def resolve_workflow(self, worktree_path, provider, operation, change_name):
        return SimpleNamespace(dispatch_command=f"native-{operation}")

    async def run(self, *, prompt_context, **kwargs):
        self.calls.append(prompt_context)
        return AgentExecutionResult(
            exit_code=self.exit_code,
            timed_out=False,
            stdout=[self.output],
            stderr=[],
            duration_ms=1,
        )


def coordinator(tmp_path: Path, runner: ScriptedRunner) -> NativeOrchestrationCoordinator:
    return NativeOrchestrationCoordinator(
        uow_factory=lambda: None,
        github_adapter=SimpleNamespace(),
        worktree_manager=SimpleNamespace(),
        agent_runner=runner,
    )


@pytest.mark.asyncio
async def test_complexity_requires_thinking_agent_and_evidence(tmp_path: Path):
    skill = tmp_path / ".agents" / "skills" / "openspec-propose"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("native")

    runner = ScriptedRunner('{"complexity":"low","evidence":"one focused change"}')
    result = await coordinator(tmp_path, runner)._assess_complexity(
        tmp_path, "codex", "Breaking migration wording", "ordinary request", "p1"
    )
    assert result.status == "VALID"
    assert result.complexity == "low"
    assert len(runner.calls) == 1

    runner.output = "low"
    invalid = await coordinator(tmp_path, runner)._assess_complexity(
        tmp_path, "codex", "title", "body", "p1"
    )
    assert invalid.is_valid is False


@pytest.mark.asyncio
async def test_complexity_rejects_multiple_or_prose_objects(tmp_path: Path):
    skill = tmp_path / ".agents" / "skills" / "openspec-propose"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("native")
    runner = ScriptedRunner('{"complexity":"low","evidence":"a"}\n{"complexity":"high","evidence":"b"}')
    result = await coordinator(tmp_path, runner)._assess_complexity(
        tmp_path, "codex", "title", "body", "p1"
    )
    assert result.status == "INVALID_OUTPUT"
    assert result.is_valid is False


@pytest.mark.asyncio
async def test_explore_failure_blocks_propose(tmp_path: Path):
    runner = ScriptedRunner("not valid")
    c = coordinator(tmp_path, runner)
    result = await c._run_explore(tmp_path, "codex", 5, "title", "body", project_id="p1")
    assert result["status"] == "READY_TO_PROPOSE"
    runner.exit_code = 2
    result = await c._run_explore(tmp_path, "codex", 5, "title", "body", project_id="p1")
    assert result["status"] == "FAILED"


@pytest.mark.asyncio
async def test_reviews_require_positive_structured_verdict(tmp_path: Path):
    change_dir = tmp_path / "openspec" / "changes" / "change"
    change_dir.mkdir(parents=True)
    (change_dir / "proposal.md").write_text("proposal")
    runner = ScriptedRunner("APPROVED")
    assert not await coordinator(tmp_path, runner)._run_proposal_review(tmp_path, "codex", "change")

    runner.output = '{"verdict":"READY_TO_MERGE","summary":"verified","findings":[]}'
    assert await coordinator(tmp_path, runner)._run_proposal_review(tmp_path, "codex", "change")


@pytest.mark.asyncio
async def test_verify_requires_native_final_response_channel(tmp_path: Path):
    skill = tmp_path / ".agents" / "skills" / "openspec-verify-change"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("native verify")
    runner = ScriptedRunner('{"verdict":"READY_TO_MERGE","summary":"verified","findings":[]}')

    result = await coordinator(tmp_path, runner)._run_verify(tmp_path, "codex", "change")

    assert result is True
    assert "output-schema" not in runner.calls[0]
    assert "authorized final response channel" in runner.calls[0]


@pytest.mark.asyncio
async def test_apply_and_sync_fail_closed_on_agent_error(tmp_path: Path):
    runner = ScriptedRunner("failure", exit_code=2)
    c = coordinator(tmp_path, runner)
    assert not await c._run_apply(tmp_path, "codex", "change")

    runner.exit_code = 0
    runner.output = "sync evidence"
    c._git_run = AsyncMock(return_value=SimpleNamespace(stdout=""))
    assert await c._run_sync_and_archive(tmp_path, "codex", "change")
    assert len(runner.calls) == 3  # Apply plus independent Sync and Archive.


@pytest.mark.asyncio
async def test_pytest_exit_five_is_not_pass(tmp_path: Path):
    c = coordinator(tmp_path, ScriptedRunner("unused"))
    ok, evidence = await c._run_automated_tests(tmp_path)
    assert not ok
    assert "no tests" in evidence.lower() or "collected" in evidence.lower()

    (tmp_path / "test_real.py").write_text("def test_real():\n    assert True\n")
    ok, evidence = await c._run_automated_tests(tmp_path)
    assert ok
    assert "passed" in evidence.lower()

