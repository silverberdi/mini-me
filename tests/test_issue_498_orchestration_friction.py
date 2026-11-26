from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from tests.conftest import InMemoryPersistenceUnitOfWork

from minime.domain.enums import OrchestrationStage
from minime.domain.models import OrchestrationRun
from minime.services.agent_runner import AgentExecutionResult
from minime.services.orchestration_coordinator import NativeOrchestrationCoordinator


def _coordinator():
    return NativeOrchestrationCoordinator(
        uow_factory=lambda: None,
        github_adapter=MagicMock(), worktree_manager=MagicMock(), agent_runner=MagicMock()
    )


def _git_repo(path: Path) -> str:
    path.mkdir(exist_ok=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(path)], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "Test"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "test@example.invalid"], check=True)
    return str(path)


@pytest.mark.parametrize("answer", ["Explore found the required constraints.", "READY_TO_PROPOSE\nFindings are complete."])
def test_explore_success_disposition_does_not_require_success_token(answer):
    disposition, _ = NativeOrchestrationCoordinator._explore_disposition(answer)
    assert disposition == "READY_TO_PROPOSE"


def test_explore_preserves_human_gate_and_rejects_conflicting_signals():
    assert NativeOrchestrationCoordinator._explore_disposition(
        "HUMAN REQUIRED\n- Opción A\nOPCIONES_ES:\n- Opción A"
    )[0] == "HUMAN_REQUIRED"
    assert NativeOrchestrationCoordinator._explore_disposition(
        "READY_TO_PROPOSE\nHUMAN REQUIRED"
    )[0] == "AMBIGUOUS"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("result", "expected"),
    [
        (AgentExecutionResult(1, False, [], ["provider exited"], 1, final_response_status="COMPLETE"), "FAILED"),
        (AgentExecutionResult(0, False, [], [], 1, final_response_status="MISSING"), "FAILED"),
    ],
)
async def test_explore_failure_and_empty_response_remain_actionable(tmp_path, result, expected):
    coordinator = _coordinator()
    coordinator.agent_runner.resolve_workflow = MagicMock(
        return_value=SimpleNamespace(dispatch_command="$openspec-explore")
    )
    coordinator.agent_runner.run = AsyncMock(return_value=result)
    value = await coordinator._run_explore(tmp_path, "antigravity", 101, "title", "body")
    assert value["status"] == expected
    assert value["message"]


@pytest.mark.asyncio
async def test_review_input_excludes_build_outputs_and_keeps_authored_frontend_source(tmp_path):
    _git_repo(tmp_path)
    (tmp_path / "source.py").write_text("value = 1\n")
    (tmp_path / "authored.js").write_text("const answer = 1;\n")
    (tmp_path / "frontend/src").mkdir(parents=True)
    (tmp_path / "frontend/src/app.ts").write_text("export const value = 1;\n")
    (tmp_path / "src/minime/static/js").mkdir(parents=True)
    (tmp_path / "src/minime/static/js/app.js").write_text("authored app source in copied static tree\n")
    (tmp_path / "src/minime/static/main-AB12CD34.js").write_text("generated bundle one\n")
    (tmp_path / "frontend/dist/app.js").mkdir(parents=True)
    (tmp_path / "frontend/dist/app.js/index.js").write_text("generated dist output one\n")
    (tmp_path / "app.js.map").write_text("generated source map one\n")
    (tmp_path / "app.min.js").write_text("generated minified output one\n")
    (tmp_path / "package-lock.json").write_text("{}\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-qm", "base"], check=True)
    (tmp_path / "source.py").write_text("value = 2\n")
    (tmp_path / "frontend/src/app.ts").write_text("export const value = 2;\n")
    (tmp_path / "src/minime/static/js/app.js").write_text("changed copied static output\n")
    (tmp_path / "src/minime/static/main-AB12CD34.js").write_text("generated bundle two\n")
    (tmp_path / "frontend/dist/app.js/index.js").write_text("generated dist output two\n")
    (tmp_path / "app.js.map").write_text("generated source map two\n")
    (tmp_path / "app.min.js").write_text("generated minified output two\n")
    (tmp_path / "authored.js").write_text("const answer = 2;\n")
    (tmp_path / "package-lock.json").write_text("changed lock\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-qm", "candidate"], check=True)

    diff, evidence = await _coordinator()._code_review_input(tmp_path, "HEAD~1..HEAD")

    assert "value = 2" in diff
    assert "const answer = 2" in diff
    assert "export const value = 2" in diff
    assert "changed copied static output" not in diff
    assert "generated bundle two" not in diff
    assert "generated dist output two" not in diff
    assert "generated source map two" not in diff
    assert "generated minified output two" not in diff
    assert "changed lock" not in diff
    assert evidence["excluded_generated_files"] == [
        "app.js.map",
        "app.min.js",
        "frontend/dist/app.js/index.js",
        "src/minime/static/js/app.js",
        "src/minime/static/main-AB12CD34.js",
    ]
    assert evidence["generated_file_reasons"]["src/minime/static/js/app.js"] == "project-static-build-output"
    assert evidence["excluded_lockfiles"] == 1
    assert evidence["source_coverage_complete"] is True


def test_review_diff_partitioning_is_bounded_and_lossless():
    diff = "".join(
        f"diff --git a/module-{index}.py b/module-{index}.py\n"
        f"index {index:07x}..{index + 1:07x} 100644\n"
        f"--- a/module-{index}.py\n+++ b/module-{index}.py\n"
        f"@@ -1 +1 @@\n+{index}:" + ("authored-source\n" * 20)
        for index in range(1, 9)
    )
    partitions, error = NativeOrchestrationCoordinator._partition_review_diff(diff, 900)

    assert error is None
    assert len(partitions) > 1
    assert all(len(part.encode("utf-8")) <= 900 for part in partitions)
    assert "".join(partitions) == diff


def test_review_diff_refuses_to_silently_split_an_oversized_hunk():
    diff = (
        "diff --git a/large.py b/large.py\n"
        "index 1234567..abcdef0 100644\n"
        "--- a/large.py\n+++ b/large.py\n"
        "@@ -1 +1 @@\n+" + ("one-authored-hunk-line\n" * 100)
    )

    partitions, error = NativeOrchestrationCoordinator._partition_review_diff(diff, 500)

    assert partitions == []
    assert "single diff hunk exceeds" in error


@pytest.mark.asyncio
async def test_unpartitionable_review_reports_incomplete_coverage_without_dispatch(tmp_path):
    project = SimpleNamespace(agent_profiles={
        "independent_review": {
            "provider_id": "review-provider", "harness_id": "codex", "model_id": "small-model"
        }
    })
    uow = SimpleNamespace(
        projects=SimpleNamespace(get_by_id=MagicMock(return_value=project)),
        provider_model_registry=SimpleNamespace(
            get=MagicMock(return_value=SimpleNamespace(max_context_tokens=100))
        ),
    )
    runner = SimpleNamespace(run=AsyncMock())
    coordinator = NativeOrchestrationCoordinator(
        uow_factory=lambda: uow,
        github_adapter=MagicMock(),
        worktree_manager=MagicMock(),
        agent_runner=runner,
    )
    coordinator._code_review_input = AsyncMock(
        return_value=("complete candidate diff", {"source_coverage_complete": True})
    )

    result = await coordinator._run_code_review(
        tmp_path, "codex", "small-context", project_id="project-1", candidate_sha="sha-1",
        uow=uow, base_sha="base-sha",
    )

    assert result["status"] == "coverage_incomplete"
    assert result["review_input"]["coverage_complete"] is False
    assert "no room for diff evidence" in result["error"]
    assert "complete candidate" in coordinator._review_pause_message("code", result)
    runner.run.assert_not_awaited()
    assert NativeOrchestrationCoordinator._classify_review_reentry(
        result, identity_matches=True, is_resume=True
    ) == "technical_failure"


@pytest.mark.asyncio
async def test_large_review_uses_bounded_partitions_and_reports_full_coverage(tmp_path):
    sections = [
        f"diff --git a/file-{index}.py b/file-{index}.py\n"
        f"index {index:07x}..{index + 1:07x} 100644\n"
        f"--- a/file-{index}.py\n+++ b/file-{index}.py\n"
        f"@@ -1 +1 @@\n+AUTHORED_FILE_{index}\n"
        for index in range(1, 40)
    ]
    diff = "".join(sections)
    project = SimpleNamespace(agent_profiles={
        "independent_review": {
            "provider_id": "review-provider", "harness_id": "codex", "model_id": "review-model"
        }
    })
    uow = SimpleNamespace(
        projects=SimpleNamespace(get_by_id=MagicMock(return_value=project)),
        provider_model_registry=SimpleNamespace(
            get=MagicMock(return_value=SimpleNamespace(max_context_tokens=5000))
        ),
    )
    complete = AgentExecutionResult(
        exit_code=0,
        timed_out=False,
        stdout=[],
        stderr=[],
        duration_ms=1,
        final_response='{"verdict":"READY_TO_MERGE","summary":"Limpio","findings":[]}',
        final_response_status="COMPLETE",
    )
    runner = SimpleNamespace(run=AsyncMock(return_value=complete))
    coordinator = NativeOrchestrationCoordinator(
        uow_factory=lambda: uow,
        github_adapter=MagicMock(),
        worktree_manager=MagicMock(),
        agent_runner=runner,
    )
    coordinator._code_review_input = AsyncMock(return_value=(diff, {"source_coverage_complete": True}))

    result = await coordinator._run_code_review(
        tmp_path, "codex", "large-review", project_id="project-1", candidate_sha="sha-1",
        uow=uow, base_sha="base-sha",
    )

    prompts = [call.kwargs["prompt_context"] for call in runner.run.await_args_list]
    assert result["status"] == "approved"
    assert result["review_input"]["coverage_complete"] is True
    assert result["review_input"]["partition_count"] == runner.run.await_count
    assert runner.run.await_count > 1
    assert all("Partition " in prompt for prompt in prompts)
    for index in range(1, 40):
        marker = f"+AUTHORED_FILE_{index}\n"
        assert sum(prompt.count(marker) for prompt in prompts) == 1


@pytest.mark.asyncio
async def test_review_correction_reentry_is_same_candidate_only_and_keeps_retry_guard(tmp_path):
    candidate = tmp_path / "candidate"
    _git_repo(candidate)
    (candidate / "source.py").write_text("value = 1\n")
    subprocess.run(["git", "-C", str(candidate), "add", "source.py"], check=True)
    subprocess.run(["git", "-C", str(candidate), "commit", "-qm", "candidate"], check=True)
    uow = InMemoryPersistenceUnitOfWork()
    run = OrchestrationRun(
        project_id="mini-me", change_name="issue-498",
        current_stage=OrchestrationStage.IMPLEMENTING, base_sha="main",
    )
    uow.orchestration_runs.save(run)
    coordinator = NativeOrchestrationCoordinator(
        uow_factory=lambda: uow, github_adapter=MagicMock(),
        worktree_manager=MagicMock(), agent_runner=MagicMock(),
    )
    original = await coordinator._begin_stage_invocation(uow, run, candidate, "APPLY")
    assert original is not None
    await coordinator._finish_stage_invocation(uow, run, original, "COMPLETE", {"status": "COMPLETE"})
    assert await coordinator._begin_stage_invocation(uow, run, candidate, "APPLY") is None
    resumed = await coordinator._begin_stage_invocation(
        uow, run, candidate, "APPLY", authorized_retry=True
    )
    assert resumed is not None
    assert resumed.candidate == original.candidate

    review = {
        "candidate_run_id": run.run_id, "candidate_change_name": "issue-498",
        "candidate_sha": resumed.candidate["candidate_sha"],
        "candidate_branch": resumed.candidate["branch"],
        "candidate_worktree": resumed.candidate["worktree"],
    }
    assert NativeOrchestrationCoordinator._review_correction_identity_mismatches(
        review, run.run_id, run.change_name, resumed.candidate
    ) == []
    assert NativeOrchestrationCoordinator._review_correction_identity_mismatches(
        review, run.run_id, "other-change", resumed.candidate
    ) == ["Change"]


@pytest.mark.asyncio
async def test_argument_transport_partitions_large_diff_without_model_context_limit(tmp_path):
    sections = [
        f"diff --git a/file-{index}.py b/file-{index}.py\n"
        f"index {index:07x}..{index + 1:07x} 100644\n"
        f"--- a/file-{index}.py\n+++ b/file-{index}.py\n"
        f"@@ -1 +1 @@\n+" + ("A" * 2500) + "\n"
        for index in range(1, 50)
    ]
    diff = "".join(sections)
    uow = SimpleNamespace(
        projects=SimpleNamespace(get_by_id=MagicMock(return_value=None)),
        provider_model_registry=None,
    )
    complete = AgentExecutionResult(
        exit_code=0,
        timed_out=False,
        stdout=[],
        stderr=[],
        duration_ms=1,
        final_response='{"verdict":"READY_TO_MERGE","summary":"Limpio","findings":[]}',
        final_response_status="COMPLETE",
    )
    runner = SimpleNamespace(
        run=AsyncMock(return_value=complete),
        _profile_for=MagicMock(return_value=SimpleNamespace(prompt_transport="argument")),
    )
    coordinator = NativeOrchestrationCoordinator(
        uow_factory=lambda: uow,
        github_adapter=MagicMock(),
        worktree_manager=MagicMock(),
        agent_runner=runner,
    )
    coordinator._code_review_input = AsyncMock(return_value=(diff, {"source_coverage_complete": True}))

    result = await coordinator._run_code_review(
        tmp_path, "antigravity", "large-argument-diff", project_id="project-1", candidate_sha="sha-1",
        uow=uow, base_sha="base-sha",
    )

    assert result["status"] == "approved"
    assert result["review_input"]["coverage_complete"] is True
    assert runner.run.await_count > 1
    prompts = [call.kwargs["prompt_context"] for call in runner.run.await_args_list]
    assert all(len(p.encode("utf-8")) <= 96 * 1024 for p in prompts)
