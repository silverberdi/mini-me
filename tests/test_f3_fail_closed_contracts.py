"""Focused regression coverage for the F3 audit corrections."""

import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from minime.services.agent_runner import AgentExecutionResult
from minime.services.orchestration_coordinator import ApplyOutcome, NativeOrchestrationCoordinator


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
    if not (tmp_path / ".git").exists():
        subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "Test"], check=True)
    seed = tmp_path / ".test-seed"
    seed.write_text("seed")
    subprocess.run(["git", "-C", str(tmp_path), "add", ".test-seed"], check=True)
    if subprocess.run(["git", "-C", str(tmp_path), "rev-parse", "HEAD"], capture_output=True).returncode:
        subprocess.run(["git", "-C", str(tmp_path), "commit", "-qm", "seed"], check=True)
    (tmp_path / "test_seed.py").write_text("def test_seed():\n    assert True\n")
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
    runner = ScriptedRunner(
        '{"complexity":"low","evidence":"a"}\n{"complexity":"high","evidence":"b"}'
    )
    result = await coordinator(tmp_path, runner)._assess_complexity(
        tmp_path, "codex", "title", "body", "p1"
    )
    assert result.status == "INVALID_OUTPUT"
    assert result.is_valid is False


@pytest.mark.asyncio
async def test_explore_failure_blocks_propose(tmp_path: Path):
    runner = ScriptedRunner("READY_TO_PROPOSE")
    c = coordinator(tmp_path, runner)
    result = await c._run_explore(tmp_path, "codex", 5, "title", "body", project_id="p1")
    assert result["status"] == "READY_TO_PROPOSE"
    runner.output = "exploration narrative without an explicit verdict"
    assert (await c._run_explore(tmp_path, "codex", 5, "title", "body", project_id="p1"))[
        "status"
    ] == "FAILED"
    runner.exit_code = 2
    result = await c._run_explore(tmp_path, "codex", 5, "title", "body", project_id="p1")
    assert result["status"] == "FAILED"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("response", "status"),
    [
        (
            "READY_TO_PROPOSE\nLa aclaración resolvió el conflicto. "
            "El gate HUMAN REQUIRED anterior es solo antecedente.",
            "READY_TO_PROPOSE",
        ),
        (
            "## **READY_TO_PROPOSE**\nEl backend mínimo ya está autorizado. "
            "El texto HUMAN REQUIRED aparece en el Issue y logs.",
            "READY_TO_PROPOSE",
        ),
        (
            "Exploración: se revisó el antecedente HUMAN REQUIRED.\n"
            "READY_TO_PROPOSE\nListo para Propose.",
            "READY_TO_PROPOSE",
        ),
        (
            "```text\nHUMAN REQUIRED\n- Ejemplo histórico\n```\n"
            "READY_TO_PROPOSE\nLa decisión ya está tomada.",
            "READY_TO_PROPOSE",
        ),
        ("HUMAN REQUIRED\n- Consultar diseño\n- Mantener alcance", "HUMAN_REQUIRED"),
        ("**HUMAN REQUIRED**\n- Aclaración auténtica", "HUMAN_REQUIRED"),
        ("Se discutió HUMAN REQUIRED pero ya está resuelto.", "FAILED"),
        ("READY_TO_PROPOSE\nHUMAN REQUIRED\n- Pregunta", "FAILED"),
        ("- READY_TO_PROPOSE\nSin veredicto formal", "FAILED"),
        ("HUMAN REQUIRED sin opciones", "FAILED"),
    ],
)
async def test_explore_verdict_uses_exact_provider_disposition_not_context(
    tmp_path, response, status
):
    runner = ScriptedRunner(response)
    resolved = await coordinator(tmp_path, runner)._run_explore(
        tmp_path, "codex", 173, "F5", "Gherkin", project_id="mini-me"
    )
    assert resolved["status"] == status
    assert len(runner.calls) == 1


@pytest.mark.asyncio
async def test_explore_codex_ndjson_uses_final_agent_message_not_tool_logs(tmp_path):
    import json

    events = [
        {"type": "thread.started", "thread_id": "thread-f5"},
        {
            "type": "item.completed",
            "item": {
                "type": "command_execution",
                "output": "HUMAN REQUIRED\n- An earlier user decision",
            },
        },
        {
            "type": "item.completed",
            "item": {
                "type": "agent_message",
                "text": ("READY_TO_PROPOSE\nLa aclaración resuelve el anterior HUMAN REQUIRED."),
            },
        },
        {"type": "turn.completed", "usage": {"input_tokens": 200, "output_tokens": 40}},
    ]
    stdout = "\n".join(json.dumps(item) for item in events)
    runner = ScriptedRunner(stdout)
    verdict = await coordinator(tmp_path, runner)._run_explore(
        tmp_path, "codex", 173, "F5", "Gherkin", project_id="mini-me"
    )
    assert verdict["status"] == "READY_TO_PROPOSE"
    assert len(runner.calls) == 1


@pytest.mark.asyncio
async def test_explore_refuses_codex_events_without_final_assistant_message(tmp_path):
    import json

    output = "\n".join(
        json.dumps(event)
        for event in [
            {"type": "turn.started"},
            {
                "type": "item.completed",
                "item": {
                    "type": "command_execution",
                    "output": "READY_TO_PROPOSE",
                },
            },
            {"type": "turn.completed"},
        ]
    )
    result = await coordinator(tmp_path, ScriptedRunner(output))._run_explore(
        tmp_path, "codex", 173, "F5", "Gherkin", project_id="mini-me"
    )
    assert result["status"] == "FAILED"


@pytest.mark.asyncio
async def test_explore_codex_json_failure_event_refuses_to_advance(tmp_path):
    import json

    payload = [
        {"type": "item.completed", "item": {"type": "agent_message", "text": "READY_TO_PROPOSE"}},
        {"type": "turn.failed"},
    ]
    text = "\n".join(json.dumps(event) for event in payload)
    result = await coordinator(tmp_path, ScriptedRunner(text))._run_explore(
        tmp_path, "codex", 173, "F5", "Gherkin", project_id="mini-me"
    )
    assert result["status"] == "FAILED"


@pytest.mark.asyncio
async def test_explore_ignores_stderr_and_blocks_incomplete_final_response(tmp_path):
    from unittest.mock import AsyncMock

    c = coordinator(tmp_path, ScriptedRunner(""))
    c.agent_runner.run = AsyncMock(
        return_value=AgentExecutionResult(
            exit_code=0,
            timed_out=False,
            stdout=["READY_TO_PROPOSE"],
            stderr=["HUMAN REQUIRED (prior debug notice)"],
            duration_ms=1,
        )
    )
    assert (await c._run_explore(tmp_path, "codex", 173, "F5", "Gherkin", project_id="mini-me"))[
        "status"
    ] == "READY_TO_PROPOSE"
    c.agent_runner.run.return_value = AgentExecutionResult(
        exit_code=0,
        timed_out=False,
        stdout=["READY_TO_PROPOSE"],
        stderr=[],
        duration_ms=1,
        output_truncated=True,
        final_response_status="TRUNCATED",
    )
    assert (await c._run_explore(tmp_path, "codex", 173, "F5", "Gherkin", project_id="mini-me"))[
        "status"
    ] == "FAILED"


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
async def test_branch_publication_uses_authenticated_github_adapter(tmp_path: Path):
    from minime.domain.enums import ExternalOutcome, ExternalReasonCode, RetrySafety
    from minime.domain.models import ExternalActionResult

    adapter = SimpleNamespace(
        push_branch=lambda **kwargs: ExternalActionResult(
            outcome=ExternalOutcome.SUCCESS,
            source_adapter="github",
            reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
            retry_safety=RetrySafety.UNSAFE,
            data=kwargs["candidate_sha"],
        )
    )
    c = NativeOrchestrationCoordinator(
        uow_factory=lambda: None,
        github_adapter=adapter,
        worktree_manager=SimpleNamespace(),
        agent_runner=ScriptedRunner("unused"),
    )
    c._get_git_head_sha = AsyncMock(return_value="a" * 40)

    await c._push_branch(tmp_path, "request-5-test")


@pytest.mark.asyncio
async def test_candidate_commit_is_created_only_for_dirty_worktree(tmp_path: Path):
    c = coordinator(tmp_path, ScriptedRunner("unused"))
    calls: list[list[str]] = []

    async def fake_git_run(_cwd: Path, args: list[str]):
        calls.append(args)
        if args == ["status", "--porcelain"]:
            return SimpleNamespace(stdout=" M src/app.py\n")
        if args == ["diff", "--cached", "--name-only"]:
            return SimpleNamespace(returncode=0, stdout="src/app.py\n")
        return SimpleNamespace(returncode=0, stdout="")

    c._git_run = fake_git_run
    await c._ensure_candidate_commit(tmp_path, 5)
    assert ["add", "-A"] in calls
    assert ["commit", "-m", "feat(request-5): implement OpenSpec change"] in calls


@pytest.mark.asyncio
async def test_apply_and_sync_fail_closed_on_agent_error(tmp_path: Path):
    runner = ScriptedRunner("failure", exit_code=2)
    c = coordinator(tmp_path, runner)
    assert not await c._run_apply(tmp_path, "codex", "change")

    runner.exit_code = 0
    runner.output = "sync evidence"
    c._git_run = AsyncMock(return_value=SimpleNamespace(stdout=""))
    # Exit zero and a success narrative are insufficient without archive files.
    assert not await c._run_sync_and_archive(tmp_path, "codex", "change")
    archive = tmp_path / "openspec" / "changes" / "archive" / "2026-10-27-change"
    (archive / "specs").mkdir(parents=True)
    for filename in ("proposal.md", "design.md", "tasks.md"):
        (archive / filename).write_text("native")
    assert await c._run_sync_and_archive(tmp_path, "codex", "change")
    assert len(runner.calls) == 5  # Apply plus two complete Sync/Archive cycles.


@pytest.mark.asyncio
async def test_empty_selection_is_not_pass(tmp_path: Path):
    c = coordinator(tmp_path, ScriptedRunner("unused"))
    base_branch = subprocess.run(
        ["git", "-C", str(tmp_path), "branch", "--show-current"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    (tmp_path / "test_seed.py").unlink()
    ok, evidence = await c._run_automated_tests(tmp_path, base_branch)
    assert not ok
    assert "no tests" in evidence.lower() or "collected" in evidence.lower()

    (tmp_path / "test_real.py").write_text("def test_real():\n    assert True\n")
    ok, evidence = await c._run_automated_tests(tmp_path, base_branch)
    assert ok
    assert "passed" in evidence.lower()


@pytest.mark.asyncio
async def test_native_apply_requires_tasks_not_just_success_text(tmp_path: Path):
    runner = ScriptedRunner("Apply completed")
    c = coordinator(tmp_path, runner)
    assert not await c._run_apply(tmp_path, "codex", "change")
    change = tmp_path / "openspec" / "changes" / "change"
    change.mkdir(parents=True)
    (change / "tasks.md").write_text("## Tasks\n- [ ] 1.1 Implement\n")
    assert not await c._run_apply(tmp_path, "codex", "change")
    (change / "tasks.md").write_text("## Tasks\n- [x] 1.1 Implement\n")
    assert await c._run_apply(tmp_path, "codex", "change")


def test_classify_pending_tasks_splits_not_verified():
    tasks = (
        "## Tasks\n"
        "- [x] 1.1 Done\n"
        "- [ ] 2.1 Pending automated work\n"
        "- [ ] 3.1 Validar en un iPhone real. (NOT_VERIFIED: no hay evidencia física disponible.)\n"
        "- [ ] 3.2 Vincular SHA. (NOT_VERIFIED: no existe SHA candidato inmutable.)\n"
    )
    automated, not_verified = NativeOrchestrationCoordinator._classify_pending_tasks(tasks)
    assert automated == ["2.1"]
    assert not_verified == ["3.1", "3.2"]


def test_deferred_task_stays_pending_without_being_apply_work_or_completed():
    tasks = (
        "## Tasks\n"
        "- [ ] 4.2 Validar audio en iPhone [DEFERRED] hasta integrar TTS; SHA de versión publicada: desconocido.\n"
    )

    automated, not_verified = NativeOrchestrationCoordinator._classify_pending_tasks(tasks)

    assert automated == []
    assert not_verified == []
    assert NativeOrchestrationCoordinator._deferred_task_ids(tasks) == ["4.2"]


def test_published_version_evidence_needs_exact_candidate_sha_to_complete():
    candidate_sha = "a" * 40
    matching = f'- [x] 4.1 Desktop check [PUBLISHED_EVIDENCE source="GitHub Pages"; sha={candidate_sha}]'
    mismatched = '- [x] 4.2 iPhone check [PUBLISHED_EVIDENCE source="GitHub Pages"; sha=unknown]'

    assert NativeOrchestrationCoordinator._invalid_published_evidence_completions(
        matching, candidate_sha
    ) == []
    assert NativeOrchestrationCoordinator._invalid_published_evidence_completions(
        mismatched, candidate_sha
    ) == ["4.2"]


def test_apply_recovery_progress_uses_pending_count_or_diff_fingerprint():
    previous = {"pending": ["1.1", "1.2"], "fingerprint": "old"}
    fewer_tasks = ApplyOutcome("PARTIAL", ("1.1",), ("1.2",), "sha-1", (), None, False, "red")
    changed_diff = ApplyOutcome("PARTIAL", (), ("1.1", "1.2"), "sha-2", ("src/a.py",), "new", False, "red")
    no_progress = ApplyOutcome("PARTIAL", (), ("1.1", "1.2"), "sha-1", (), "old", False, "red")

    assert NativeOrchestrationCoordinator._apply_made_progress(previous, fewer_tasks)
    assert NativeOrchestrationCoordinator._apply_made_progress(previous, changed_diff)
    assert not NativeOrchestrationCoordinator._apply_made_progress(previous, no_progress)

    context = NativeOrchestrationCoordinator._apply_recovery_context(
        NativeOrchestrationCoordinator._apply_snapshot(changed_diff)
    )
    assert "Git changed files: ['src/a.py']" in context
    assert "Mark [x]" in context


def test_apply_regression_guard_detects_identity_files_tasks_and_test_loss():
    previous = {"branch": "request-259", "worktree": "/candidate", "run_id": "run-1",
                "files": ["src/a.py", "src/b.py"], "completed": ["1.1", "1.2"],
                "tests_passed": True}
    same = ApplyOutcome("PARTIAL", ("1.1", "1.2"), ("1.3",), "sha", ("src/a.py", "src/b.py"),
                        "digest", True, "ok", branch="request-259", worktree="/candidate", run_id="run-1")
    changed_branch = ApplyOutcome("PARTIAL", same.completed_tasks, same.pending_tasks, "sha", same.changed_files,
                                  "digest", True, "ok", branch="other", worktree="/candidate", run_id="run-1")
    missing_file = ApplyOutcome("PARTIAL", same.completed_tasks, same.pending_tasks, "sha", ("src/a.py",),
                                "digest", True, "ok", branch="request-259", worktree="/candidate", run_id="run-1")
    failing_tests = ApplyOutcome("PARTIAL", same.completed_tasks, same.pending_tasks, "sha", same.changed_files,
                                 "digest", False, "failed", branch="request-259", worktree="/candidate", run_id="run-1")

    assert not NativeOrchestrationCoordinator._apply_regressed(previous, same)
    assert NativeOrchestrationCoordinator._apply_regressed(previous, changed_branch)
    assert NativeOrchestrationCoordinator._apply_regressed(previous, missing_file)
    assert NativeOrchestrationCoordinator._apply_regressed(previous, failing_tests)


def test_validated_update_ignores_only_exact_task_reclassification_losses():
    from minime.services.orchestration_coordinator import NativeOrchestrationCoordinator

    prior = {
        "run_id": "run-1", "sha": "sha-1", "branch": "request-259",
        "worktree": "/candidate", "completed": ["1.1", "1.2"],
    }
    checkpoint = {
        "status": "VALIDATED", "operator_action_id": "action-1",
        "change_name": "change-1",
        "before": {"run_id": "run-1", "candidate_sha": "sha-1",
                   "branch": "request-259", "worktree": "/candidate", "generation": 1},
        "after": {"run_id": "run-1", "candidate_sha": "sha-1",
                  "branch": "request-259", "worktree": "/candidate", "generation": 1},
        "reclassified_tasks": ["1.1"],
        "task_dispositions_before": {"1.1": "completed", "1.2": "completed"},
        "task_dispositions_after": {"1.1": "deferred", "1.2": "completed"},
    }
    current = ApplyOutcome(
        "PARTIAL", ("1.2",), ("1.1", "1.3"), "sha-1", (), None, None, "",
        branch="request-259", worktree="/candidate", run_id="run-1",
    )
    ignored = NativeOrchestrationCoordinator._validated_apply_reclassifications(
        checkpoint, operator_action_id="action-1", prior=prior, run_id="run-1",
        change_name="change-1",
    )
    assert ignored == {"1.1"}
    assert not NativeOrchestrationCoordinator._apply_regressed(
        prior, current, ignored_task_losses=ignored
    )

    unrelated_loss = ApplyOutcome(
        "PARTIAL", (), ("1.1", "1.2", "1.3"), "sha-1", (), None, None, "",
        branch="request-259", worktree="/candidate", run_id="run-1",
    )
    assert NativeOrchestrationCoordinator._apply_regressed(
        prior, unrelated_loss, ignored_task_losses=ignored
    )
    assert NativeOrchestrationCoordinator._validated_apply_reclassifications(
        {**checkpoint, "after": {**checkpoint["after"], "candidate_sha": "other-sha"}},
        operator_action_id="action-1", prior=prior, run_id="run-1", change_name="change-1",
    ) == set()


def test_apply_retry_limits_are_persistable_and_bounded():
    assert NativeOrchestrationCoordinator._positive_policy_limit(
        {"apply_max_attempts": 4}, "apply_max_attempts", 3
    ) == 4
    assert NativeOrchestrationCoordinator._positive_policy_limit(
        {"apply_max_attempts": 100}, "apply_max_attempts", 3
    ) == 10
    assert NativeOrchestrationCoordinator._positive_policy_limit(
        {"apply_max_attempts": 0}, "apply_max_attempts", 3
    ) == 3


@pytest.mark.asyncio
async def test_run_apply_succeeds_when_only_not_verified_remain(tmp_path: Path):
    """NOT_VERIFIED physical-validation tasks are not part of the Apply postcondition."""
    runner = ScriptedRunner("Apply completed")
    c = coordinator(tmp_path, runner)
    change = tmp_path / "openspec" / "changes" / "change"
    change.mkdir(parents=True)
    (change / "tasks.md").write_text(
        "## Tasks\n"
        "- [x] 1.1 Implement\n"
        "- [ ] 6.1 Validar en iPhone real. (NOT_VERIFIED: no hay evidencia física disponible.)\n"
    )
    assert await c._run_apply(tmp_path, "codex", "change")

    # A genuinely-pending non-NOT_VERIFIED task still gates Apply fail-closed.
    (change / "tasks.md").write_text(
        "## Tasks\n- [x] 1.1 Implement\n- [ ] 2.1 Pending automated work\n"
    )
    assert not await c._run_apply(tmp_path, "codex", "change")
