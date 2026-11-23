from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from minime.services.agent_runner import AgentExecutionResult
from minime.services.orchestration_coordinator import NativeOrchestrationCoordinator
from minime.services.review_verdict_parser import parse_review_verdict


@pytest.mark.asyncio
async def test_code_review_prompt_includes_verdict_first_rule_and_excludes_lockfiles(tmp_path):
    coordinator = NativeOrchestrationCoordinator(
        uow_factory=lambda: None,
        github_adapter=SimpleNamespace(),
        worktree_manager=SimpleNamespace(),
        agent_runner=SimpleNamespace(
            run=AsyncMock(
                return_value=AgentExecutionResult(
                    exit_code=0,
                    timed_out=False,
                    stdout=[],
                    stderr=[],
                    duration_ms=1,
                    final_response='{"verdict":"READY_TO_MERGE","summary":"Limpio","findings":[]}',
                    final_response_status="COMPLETE",
                )
            )
        ),
    )
    diff = "diff --git a/a.js b/a.js\n+console.log(1);"
    git_calls = []

    async def fake_git_run(worktree, args):
        git_calls.append(args)
        if args[0] == "merge-base":
            return SimpleNamespace(returncode=0, stdout="abc1234\n")
        if args[:3] == ["diff", "--name-only", "-z"]:
            return SimpleNamespace(
                returncode=0,
                stdout="a.js\0package-lock.json\0poetry.lock\0pnpm-lock.yaml\0yarn.lock\0",
            )
        return SimpleNamespace(returncode=0, stdout=diff)

    coordinator._git_run = fake_git_run

    result = await coordinator._run_code_review(
        tmp_path, "deepseek", "test-change", candidate_sha="test-sha", base_sha="main"
    )

    assert result["status"] == "approved"
    call = coordinator.agent_runner.run.await_args
    prompt = call.kwargs["prompt_context"]
    assert "REGLA OBLIGATORIA DE FORMATO (VERDICT-FIRST):" in prompt
    assert "- Tu respuesta DEBE iniciar directamente con el único bloque JSON estructurado" in prompt

    # Keep the Git argument vector fixed, independent of the changed-file count.
    diff_calls = [args for args in git_calls if args[0] == "diff"]
    assert diff_calls[0][:3] == ["diff", "--name-only", "-z"]
    assert diff_calls[1][:4] == ["diff", "abc1234..HEAD", "--", "."]
    assert ":(exclude,glob)src/*/static/**" in diff_calls[1]
    assert ":(exclude,glob)frontend/dist/**" in diff_calls[1]
    assert ":(exclude,glob)**/*.map" in diff_calls[1]
    assert ":(exclude,glob)**/*.min.js" in diff_calls[1]
    assert all(f":(exclude,glob)**/{name}" in diff_calls[1] for name in (
        "package-lock.json", "poetry.lock", "pnpm-lock.yaml", "yarn.lock"
    ))
    assert "a.js" not in diff_calls[1]


@pytest.mark.asyncio
async def test_propose_review_prompt_includes_verdict_first_rule(tmp_path):
    coordinator = NativeOrchestrationCoordinator(
        uow_factory=lambda: None,
        github_adapter=SimpleNamespace(),
        worktree_manager=SimpleNamespace(),
        agent_runner=SimpleNamespace(
            run=AsyncMock(
                return_value=AgentExecutionResult(
                    exit_code=0,
                    timed_out=False,
                    stdout=[],
                    stderr=[],
                    duration_ms=1,
                    final_response='{"verdict":"READY_TO_MERGE","summary":"Propuesta limpia","findings":[]}',
                    final_response_status="COMPLETE",
                )
            )
        ),
    )
    ch_dir = tmp_path / "openspec" / "changes" / "test-change"
    ch_dir.mkdir(parents=True)
    (ch_dir / "proposal.md").write_text("# Proposal")
    (ch_dir / "design.md").write_text("# Design")
    (ch_dir / "tasks.md").write_text("# Tasks")

    result = await coordinator._run_proposal_review(
        tmp_path, "deepseek", "test-change"
    )

    assert result["status"] == "approved"
    call = coordinator.agent_runner.run.await_args
    prompt = call.kwargs["prompt_context"]
    assert "REGLA OBLIGATORIA DE FORMATO (VERDICT-FIRST):" in prompt
    assert "- Tu respuesta DEBE iniciar directamente con el único bloque JSON estructurado" in prompt


@pytest.mark.asyncio
async def test_code_review_captures_raw_diagnostic_on_malformed_response(tmp_path):
    coordinator = NativeOrchestrationCoordinator(
        uow_factory=lambda: None,
        github_adapter=SimpleNamespace(),
        worktree_manager=SimpleNamespace(),
        agent_runner=SimpleNamespace(
            run=AsyncMock(
                return_value=AgentExecutionResult(
                    exit_code=0,
                    timed_out=False,
                    stdout=["Analyzing file 1...", "Looking at code...", "Truncated here"],
                    stderr=[],
                    duration_ms=1,
                    final_response="Analyzing file 1... Looking at code... Truncated here",
                    final_response_status="COMPLETE",
                )
            )
        ),
    )
    coordinator._git_run = AsyncMock(return_value=SimpleNamespace(returncode=0, stdout="diff"))

    result = await coordinator._run_code_review(
        tmp_path, "deepseek", "test-change", candidate_sha="test-sha"
    )

    assert result["status"] == "invalid_response"
    assert "raw_diagnostic" in result
    assert "Analyzing file 1..." in result["raw_diagnostic"]

    # Verify pause message surfaces the raw diagnostic snippet
    pause_msg = NativeOrchestrationCoordinator._review_pause_message("code", result)
    assert "Analyzing file 1..." in pause_msg
    assert "Worktree preserved." in pause_msg


def test_parse_review_verdict_tolerates_truncated_subsequent_text():
    raw_response = (
        "```json\n"
        "{\n"
        '  "verdict": "READY_TO_MERGE",\n'
        '  "summary": "Cambio verificado y listo para merge.",\n'
        '  "findings": []\n'
        "}\n"
        "```\n"
        "Aquí continúa el análisis del revisor detallando archivo por archivo:\n"
        "1. js/app.js: todo correcto...\n"
        "2. js/engine.js: [la respuesta fue cortada abruptamente aquí"
    )
    parsed = parse_review_verdict(raw_response)
    assert parsed.verdict.value == "READY_TO_MERGE"
    assert parsed.summary == "Cambio verificado y listo para merge."
    assert parsed.findings == []
