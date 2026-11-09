import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock
from minime.domain.enums import OrchestrationStage
from minime.services.agent_runner import AgentExecutionResult
from minime.services.orchestration_coordinator import NativeOrchestrationCoordinator


@pytest.mark.asyncio
async def test_code_review_prompt_includes_character_limit_and_conciseness_rule(tmp_path):
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
    coordinator._git_run = AsyncMock(return_value=SimpleNamespace(stdout=diff))

    result = await coordinator._run_code_review(
        tmp_path, "deepseek", "test-change", candidate_sha="test-sha"
    )

    assert result["status"] == "approved"
    call = coordinator.agent_runner.run.await_args
    prompt = call.kwargs["prompt_context"]
    assert "REGLA ESTRICTA DE TAMAÑO Y CONCISIÓN:" in prompt
    assert "no más de 4000 caracteres" in prompt
    assert "Emite directamente el único bloque JSON con el veredicto" in prompt


@pytest.mark.asyncio
async def test_propose_review_prompt_includes_character_limit_and_conciseness_rule(tmp_path):
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
    assert "REGLA ESTRICTA DE TAMAÑO Y CONCISIÓN:" in prompt
    assert "no más de 4000 caracteres" in prompt
