from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from tests.conftest import InMemoryPersistenceUnitOfWork, setup_managed_repository_fixture

from minime.domain.enums import OrchestrationStage
from minime.domain.models import OrchestrationRun
from minime.services.agent_runner import AgentExecutionResult, CliAgentRunner
from minime.services.orchestration_coordinator import NativeOrchestrationCoordinator
from minime.services.worktree_manager import WorktreeInfo, WorktreeManager


@pytest.fixture
def mock_env(tmp_path: Path):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    managed_root = tmp_path / "worktrees"
    managed_root.mkdir()

    # Create dummy workflow files in worktree
    agent_dir = repo_dir / ".agent" / "workflows"
    agent_dir.mkdir(parents=True)
    for op in [
        "opsx-explore.md",
        "opsx-propose.md",
        "opsx-apply.md",
        "opsx-verify.md",
        "opsx-sync.md",
        "opsx-archive.md",
    ]:
        (agent_dir / op).write_text(f"# {op}")

    uow = InMemoryPersistenceUnitOfWork()
    setup_managed_repository_fixture(
        uow,
        "proj-1",
        repo_dir,
        managed_root,
        canonical_repository_identity="github.com/org/proj-1",
    )

    from minime.domain.enums import ExternalOutcome, ExternalReasonCode, RetrySafety
    from minime.domain.models import ExternalActionResult

    github_mock = MagicMock()

    def mock_list_issues(repo, state="open", limit=None):
        return ExternalActionResult(
            outcome=ExternalOutcome.SUCCESS,
            source_adapter="github",
            reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
            retry_safety=RetrySafety.SAFE,
            data=[
                {
                    "number": 101,
                    "title": "Add caching layer",
                    "body": "We need redis caching layer",
                    "labels": [{"name": "backend"}],
                    "created_at": "2026-10-20T10:00:00Z",
                    "updated_at": "2026-10-20T10:00:00Z",
                    "html_url": "https://github.com/org/proj-1/issues/101",
                }
            ],
        )

    github_mock.list_issues.side_effect = mock_list_issues

    wt_manager = WorktreeManager(repo_dir, uow=uow)
    wt_manager.create_request_worktree = AsyncMock(
        return_value=WorktreeInfo(
            path=repo_dir, branch_name="request-101-add-caching-layer", base_sha="abc1234"
        )
    )
    wt_manager.create_documentation_worktree = AsyncMock(
        return_value=WorktreeInfo(
            path=repo_dir, branch_name="doc-close-101-add-caching-layer", base_sha="def5678"
        )
    )

    agent_runner = CliAgentRunner()

    coordinator = NativeOrchestrationCoordinator(
        uow_factory=lambda: uow,
        github_adapter=github_mock,
        worktree_manager=wt_manager,
        agent_runner=agent_runner,
    )
    return coordinator, uow, github_mock, repo_dir


@pytest.mark.asyncio
async def test_propose_lifecycle_explore_and_propose(mock_env):
    coordinator, uow, github_mock, repo_dir = mock_env

    # Configure runner to create proposal artifacts on propose dispatch
    async def mock_agent_run(worktree_path, prompt_context, **kwargs):
        from minime.services.agent_runner import AgentExecutionResult

        if "Execute official OpenSpec Propose" in prompt_context:
            change_dir = worktree_path / "openspec" / "changes" / "req-101-add-caching-layer"
            change_dir.mkdir(parents=True, exist_ok=True)
            (change_dir / "proposal.md").write_text("# Proposal\nAdd caching layer")
            (change_dir / "tasks.md").write_text("## Tasks\n- [ ] 1.1 Add caching")
            specs_dir = change_dir / "specs" / "feature"
            specs_dir.mkdir(parents=True, exist_ok=True)
            (specs_dir / "spec.md").write_text("## Spec\nCaching spec")
        return AgentExecutionResult(
            exit_code=0,
            timed_out=False,
            stdout=[
                "READY_TO_PROPOSE"
                if "Execute official OpenSpec Explore" in prompt_context
                else "Done"
            ],
            stderr=[],
            duration_ms=10,
        )

    coordinator.agent_runner.run = AsyncMock(side_effect=mock_agent_run)
    coordinator.openspec_adapter.validate_change_strict = MagicMock(
        return_value={"status": "PASS", "returncode": 0}
    )

    # Test Explore & Propose execution
    result = await coordinator.execute_project_request(
        "proj-1",
        thinker_provider="antigravity",
        implementer_provider="antigravity",
        reviewer_provider="antigravity",
    )

    assert result.status in ("COMPLETED", "HUMAN_REQUIRED", "PAUSED")
    # Verify change artifacts created
    change_dir = repo_dir / "openspec" / "changes" / "req-101-add-caching-layer"
    assert (change_dir / "proposal.md").exists() or (
        repo_dir / "openspec" / "archive" / "req-101-add-caching-layer"
    ).exists()


@pytest.mark.asyncio
async def test_propose_lifecycle_human_required_ambiguity(mock_env):
    coordinator, uow, github_mock, repo_dir = mock_env
    from minime.services.agent_runner import AgentExecutionResult

    coordinator.agent_runner.run = AsyncMock(
        return_value=AgentExecutionResult(
            exit_code=0,
            timed_out=False,
            stdout=["HUMAN REQUIRED\n- Opción A\n- Opción B"],
            stderr=[],
            duration_ms=1,
        )
    )

    from minime.domain.enums import ExternalOutcome, ExternalReasonCode, RetrySafety
    from minime.domain.models import ExternalActionResult

    github_mock.list_issues.side_effect = lambda repo, state="open", limit=None: (
        ExternalActionResult(
            outcome=ExternalOutcome.SUCCESS,
            source_adapter="github",
            reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
            retry_safety=RetrySafety.SAFE,
            data=[
                {
                    "number": 102,
                    "title": "Unclear architectural requirement",
                    "body": "Material ambiguity: HUMAN REQUIRED to choose architecture",
                    "labels": [],
                    "created_at": "2026-10-20T10:00:00Z",
                    "updated_at": "2026-10-20T10:00:00Z",
                    "html_url": "https://github.com/org/proj-1/issues/102",
                }
            ],
        )
    )

    result = await coordinator.execute_project_request(
        "proj-1",
        thinker_provider="antigravity",
        implementer_provider="antigravity",
        reviewer_provider="antigravity",
    )

    assert result.status == "HUMAN_REQUIRED"
    assert result.current_stage == OrchestrationStage.EXPLORING
    assert result.human_payload is not None
    assert "pregunta" in result.human_payload.get(
        "question", ""
    ).lower() or "¿" in result.human_payload.get("question", "")


@pytest.mark.asyncio
async def test_complexity_evaluation_uses_structured_agent_result(mock_env):
    coordinator, _, _, _ = mock_env
    from minime.services.agent_runner import AgentExecutionResult

    coordinator.agent_runner.run = AsyncMock(
        return_value=AgentExecutionResult(
            exit_code=0,
            timed_out=False,
            stdout=['{"complexity":"high","evidence":"cross-cutting architectural impact"}'],
            stderr=[],
            duration_ms=1,
        )
    )
    result = await coordinator._assess_complexity(
        _, "antigravity", "Small typo", "breaking migration words", "proj-1"
    )
    assert result.status == "VALID"
    assert result.complexity == "high"


@pytest.mark.asyncio
async def test_resume_validating_reuses_existing_proposal_without_propose(mock_env):
    coordinator, uow, _, repo_dir = mock_env
    change_name = "req-101-add-caching-layer"
    change_dir = repo_dir / "openspec" / "changes" / change_name
    (change_dir / "specs" / "feature").mkdir(parents=True)
    for name in ("proposal.md", "design.md", "tasks.md"):
        (change_dir / name).write_text("# existing")
    (change_dir / "specs" / "feature" / "spec.md").write_text("# existing")
    codex_skill = repo_dir / ".agents" / "skills" / "openspec-propose"
    codex_skill.mkdir(parents=True)
    (codex_skill / "SKILL.md").write_text("native")
    uow.orchestration_runs.save(
        OrchestrationRun(
            project_id="proj-1",
            change_name=change_name,
            base_sha="abc1234",
            current_stage=OrchestrationStage.VALIDATING,
            resumable_stage=OrchestrationStage.VALIDATING,
        )
    )
    coordinator.openspec_adapter.validate_change_strict = MagicMock(
        return_value={"status": "PASS", "returncode": 0}
    )
    coordinator._run_propose = AsyncMock(side_effect=AssertionError("propose must not repeat"))
    coordinator.agent_runner.run = AsyncMock(
        return_value=AgentExecutionResult(
            exit_code=0,
            timed_out=False,
            stdout=['{"complexity":"low","evidence":"one focused change"}'],
            stderr=[],
            duration_ms=1,
        )
    )
    coordinator._run_apply = AsyncMock(return_value=False)

    result = await coordinator.execute_project_request(
        "proj-1",
        thinker_provider="antigravity",
        implementer_provider="antigravity",
        reviewer_provider="antigravity",
    )

    assert result.status == "PAUSED"
    coordinator._run_propose.assert_not_awaited()
    assert uow.orchestration_runs.list_runs(project_id="proj-1")[0].run_id


@pytest.mark.asyncio
async def test_explore_failed_blocks_propose(mock_env):
    coordinator, _, _, _ = mock_env
    coordinator.agent_runner.run = AsyncMock(
        return_value=AgentExecutionResult(
            exit_code=2,
            timed_out=False,
            stdout=[],
            stderr=["explore failed"],
            duration_ms=1,
        )
    )
    coordinator._run_propose = AsyncMock(
        side_effect=AssertionError("failed Explore must block Propose")
    )

    result = await coordinator.execute_project_request(
        "proj-1",
        thinker_provider="antigravity",
        implementer_provider="antigravity",
        reviewer_provider="antigravity",
    )

    assert result.status == "PAUSED"
    assert result.current_stage == OrchestrationStage.EXPLORING
    coordinator._run_propose.assert_not_awaited()


@pytest.mark.asyncio
async def test_classification_checkpoint_stops_after_one_codex_call(mock_env):
    coordinator, uow, _, repo_dir = mock_env
    project = uow.projects.get_by_id("proj-1")
    project.agent_profiles = {"thinking": {"agent_id": "codex", "model_id": "gpt-test"}}
    uow.projects.save(project)
    change_name = "req-101-add-caching-layer"
    change_dir = repo_dir / "openspec" / "changes" / change_name
    (change_dir / "specs" / "feature").mkdir(parents=True)
    for name in ("proposal.md", "design.md", "tasks.md"):
        (change_dir / name).write_text("# existing")
    (change_dir / "specs" / "feature" / "spec.md").write_text("# existing")
    codex_skill = repo_dir / ".agents" / "skills" / "openspec-propose"
    codex_skill.mkdir(parents=True)
    (codex_skill / "SKILL.md").write_text("native")
    run = OrchestrationRun(
        project_id="proj-1",
        change_name=change_name,
        base_sha="abc1234",
        current_stage=OrchestrationStage.VALIDATING,
        resumable_stage=OrchestrationStage.VALIDATING,
        stop_details={"issue_number": 101, "issue_title": "title", "issue_body": "body"},
    )
    uow.orchestration_runs.save(run)
    coordinator.openspec_adapter.validate_change_strict = MagicMock(
        return_value={"status": "PASS", "returncode": 0}
    )
    coordinator.agent_runner.run = AsyncMock(
        return_value=AgentExecutionResult(
            exit_code=0,
            timed_out=False,
            stdout=['{"complexity":"moderate","evidence":"single focused change"}'],
            stderr=[],
            duration_ms=1,
        )
    )
    coordinator._run_explore = AsyncMock(side_effect=AssertionError("Explore must not run"))
    coordinator._run_propose = AsyncMock(side_effect=AssertionError("Propose must not run"))
    coordinator._run_apply = AsyncMock(side_effect=AssertionError("Apply must not run"))

    result = await coordinator.classify_existing_run(
        "proj-1", run.run_id, repo_dir, thinker_provider="codex"
    )

    assert result.status == "CLASSIFIED"
    assert result.assessment.complexity == "moderate"
    assert result.attempt_id
    assert coordinator.agent_runner.run.await_count == 1
    persisted = uow.orchestration_runs.get_by_id(run.run_id)
    assert persisted is not None
    assert persisted.current_stage == OrchestrationStage.VALIDATING
    assert persisted.stop_details["complexity_assessment"]["artifact_hashes"]


@pytest.mark.asyncio
async def test_complexity_uses_response_channel_and_ignores_diagnostics(mock_env):
    coordinator, _, _, repo_dir = mock_env
    coordinator.agent_runner.run = AsyncMock(
        return_value=AgentExecutionResult(
            exit_code=0,
            timed_out=False,
            stdout=['{"complexity":"moderate","evidence":"bounded change"}'],
            stderr=["Codex session metadata and progress output"],
            duration_ms=1,
        )
    )

    result = await coordinator._assess_complexity(
        repo_dir, "antigravity", "Issue", "Body", "proj-1"
    )

    assert result.status == "VALID"
    assert result.complexity == "moderate"
    assert result.diagnostic_output == "Codex session metadata and progress output"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "stdout,expected",
    [
        (
            '{"complexity":"low","evidence":"one"}\n{"complexity":"high","evidence":"two"}',
            "INVALID_OUTPUT",
        ),
        ('session log {"complexity":"low","evidence":"incidental"}', "INVALID_OUTPUT"),
    ],
)
async def test_complexity_rejects_ambiguous_response_channel(mock_env, stdout, expected):
    coordinator, _, _, repo_dir = mock_env
    coordinator.agent_runner.run = AsyncMock(
        return_value=AgentExecutionResult(
            exit_code=0,
            timed_out=False,
            stdout=stdout.splitlines(),
            stderr=[],
            duration_ms=1,
        )
    )

    result = await coordinator._assess_complexity(
        repo_dir, "antigravity", "Issue", "Body", "proj-1"
    )

    assert result.status == expected


@pytest.mark.asyncio
async def test_complexity_accepts_structured_response_when_diagnostics_truncated(mock_env):
    coordinator, _, _, repo_dir = mock_env
    coordinator.agent_runner.run = AsyncMock(
        return_value=AgentExecutionResult(
            exit_code=0,
            timed_out=False,
            stdout=['{"complexity":"moderate","evidence":"bounded change"}'],
            stderr=[],
            duration_ms=1,
            structured_output=['{"complexity":"moderate","evidence":"bounded change"}'],
            diagnostic_output=["diagnostic output was truncated"],
            output_truncated=True,
        )
    )

    result = await coordinator._assess_complexity(
        repo_dir, "antigravity", "Issue", "Body", "proj-1"
    )

    assert result.status == "VALID"
    assert result.complexity == "moderate"


@pytest.mark.asyncio
async def test_invalid_classification_reentry_never_invokes_again(mock_env):
    coordinator, uow, _, repo_dir = mock_env
    change_name = "req-101-add-caching-layer"
    change_dir = repo_dir / "openspec" / "changes" / change_name
    (change_dir / "specs" / "feature").mkdir(parents=True)
    for name in ("proposal.md", "design.md", "tasks.md"):
        (change_dir / name).write_text("# existing")
    (change_dir / "specs" / "feature" / "spec.md").write_text("# existing")
    (repo_dir / ".agents" / "skills" / "openspec-propose").mkdir(parents=True)
    (repo_dir / ".agents" / "skills" / "openspec-propose" / "SKILL.md").write_text("native")
    run = OrchestrationRun(
        project_id="proj-1",
        change_name=change_name,
        base_sha="abc1234",
        current_stage=OrchestrationStage.VALIDATING,
        resumable_stage=OrchestrationStage.VALIDATING,
        stop_details={
            "issue_number": 101,
            "issue_title": "title",
            "issue_body": "body",
            "complexity_attempts": [{"status": "INVALID_OUTPUT", "attempt_id": "old"}],
            "complexity_assessment": {"status": "INVALID_OUTPUT"},
        },
    )
    uow.orchestration_runs.save(run)
    coordinator.openspec_adapter.validate_change_strict = MagicMock(
        return_value={"status": "PASS", "returncode": 0}
    )
    coordinator.agent_runner.run = AsyncMock(side_effect=AssertionError("re-entry must not invoke"))

    result = await coordinator.classify_existing_run(
        "proj-1", run.run_id, repo_dir, thinker_provider="codex", issue_number=101
    )

    assert result.status == "BLOCKED"
    assert coordinator.agent_runner.run.await_count == 0


@pytest.mark.asyncio
async def test_classification_retry_authorization_is_single_use(mock_env):
    coordinator, uow, _, repo_dir = mock_env
    project = uow.projects.get_by_id("proj-1")
    project.agent_profiles = {"thinking": {"agent_id": "codex", "model_id": "gpt-test"}}
    uow.projects.save(project)
    change_name = "req-101-add-caching-layer"
    change_dir = repo_dir / "openspec" / "changes" / change_name
    (change_dir / "specs" / "feature").mkdir(parents=True)
    for name in ("proposal.md", "design.md", "tasks.md"):
        (change_dir / name).write_text("# existing")
    (change_dir / "specs" / "feature" / "spec.md").write_text("# existing")
    (repo_dir / ".agents" / "skills" / "openspec-propose").mkdir(parents=True)
    (repo_dir / ".agents" / "skills" / "openspec-propose" / "SKILL.md").write_text("native")
    run = OrchestrationRun(
        project_id="proj-1",
        change_name=change_name,
        base_sha="abc1234",
        current_stage=OrchestrationStage.VALIDATING,
        resumable_stage=OrchestrationStage.VALIDATING,
        stop_details={
            "issue_number": 101,
            "issue_title": "title",
            "issue_body": "body",
            "complexity_attempts": [{"status": "INVALID_OUTPUT", "attempt_id": "old"}],
            "complexity_assessment": {"status": "INVALID_OUTPUT"},
        },
    )
    uow.orchestration_runs.save(run)
    coordinator.openspec_adapter.validate_change_strict = MagicMock(
        return_value={"status": "PASS", "returncode": 0}
    )
    hashes = coordinator._proposal_artifact_hashes(repo_dir, change_name)
    context_hashes = coordinator._classification_context_hashes(run, 101, "title", "body")
    assert coordinator.register_classification_retry_authorization(
        project_id="proj-1",
        run_id=run.run_id,
        authorization_reference="retry-once",
        actor_identity="operator",
        issue_number=101,
        provider="codex",
        model_identity="gpt-test",
        prior_attempt_id="old",
        artifact_hashes=hashes,
        context_hashes=context_hashes,
    )
    coordinator.agent_runner.run = AsyncMock(
        return_value=AgentExecutionResult(
            exit_code=2, timed_out=False, stdout=[], stderr=["blocked"], duration_ms=1
        )
    )

    first = await coordinator.classify_existing_run(
        "proj-1",
        run.run_id,
        repo_dir,
        thinker_provider="codex",
        issue_number=101,
        authorization_reference="retry-once",
    )
    second = await coordinator.classify_existing_run(
        "proj-1",
        run.run_id,
        repo_dir,
        thinker_provider="codex",
        issue_number=101,
        authorization_reference="retry-once",
    )

    assert first.status == "BLOCKED"
    assert second.status == "BLOCKED"
    assert coordinator.agent_runner.run.await_count == 1


def test_persisted_recovery_requires_explicit_channels_and_accepts_one_valid_message():
    recovered = NativeOrchestrationCoordinator._recover_persisted_complexity(
        {
            "exit_code": 0,
            "output_truncated": False,
            "structured_output": '{"complexity":"low","evidence":"one focused change"}',
            "diagnostic_output": "Codex session banner",
            "output": "combined sanitized output",
            "attempt_id": "attempt-1",
            "artifact_hashes": {"proposal.md": "hash"},
            "context_hashes": {"issue": "hash", "run": "hash"},
        }
    )
    assert recovered is not None
    assert recovered.complexity == "low"
    assert (
        NativeOrchestrationCoordinator._recover_persisted_complexity(
            {
                "exit_code": 0,
                "structured_output": '{"complexity":"low","evidence":"one"}',
                "diagnostic_output": "",
            }
        )
        is None
    )


def test_valid_classification_is_not_reused_after_artifact_hash_change():
    run = OrchestrationRun(
        project_id="proj-1",
        change_name="req-101-add-caching-layer",
        base_sha="abc1234",
        stop_details={
            "complexity_assessment": {
                "status": "VALID",
                "complexity": "low",
                "evidence": "one",
                "artifact_hashes": {"proposal.md": "old"},
                "context_hashes": {"issue": "issue", "run": "run"},
            }
        },
    )

    assert (
        NativeOrchestrationCoordinator._stored_complexity_assessment(
            run,
            {"proposal.md": "new"},
            {"issue": "issue", "run": "run"},
        )
        is None
    )


@pytest.mark.asyncio
async def test_explore_checkpoint_survives_reentry_without_paid_repeat(mock_env):
    coordinator, uow, _, _repo_dir = mock_env
    coordinator.agent_runner.run = AsyncMock(
        return_value=AgentExecutionResult(
            exit_code=0,
            timed_out=False,
            stdout=["READY_TO_PROPOSE\nLa aclaración resolvió el gate HUMAN REQUIRED anterior."],
            stderr=[],
            duration_ms=19,
        )
    )
    coordinator._run_propose = AsyncMock(
        return_value={"status": "FAILED", "message": "Test checkpoint boundary"}
    )
    first = await coordinator.execute_project_request(
        "proj-1",
        operator_clarification="Autorizado backend mínimo de F5",
        thinker_provider="antigravity",
        implementer_provider="antigravity",
        reviewer_provider="antigravity",
    )
    assert first.status == "PAUSED"
    assert first.current_stage == OrchestrationStage.PROPOSING
    run = uow.orchestration_runs.get_by_id(first.run_id)
    assert run is not None
    checkpoint = run.stop_details["explore_checkpoint"]
    assert checkpoint["status"] == "READY_TO_PROPOSE"
    assert checkpoint["run_id"] == first.run_id
    assert len(checkpoint["response_sha256"]) == 64
    assert checkpoint["duration_ms"] == 19

    # Re-entry into Explore after interruption must not repeat the model.
    run.current_stage = OrchestrationStage.EXPLORING
    run.resumable_stage = OrchestrationStage.EXPLORING
    run.stop_details["request_normalization"] = {"normalized_body": "We need redis caching layer"}
    uow.orchestration_runs.save(run)
    coordinator._run_explore = AsyncMock(
        side_effect=AssertionError("Exploration should reuse its verified checkpoint")
    )
    second = await coordinator.execute_project_request(
        "proj-1",
        operator_clarification="Autorizado backend mínimo de F5",
        thinker_provider="antigravity",
        implementer_provider="antigravity",
        reviewer_provider="antigravity",
    )
    assert second.run_id == first.run_id
    assert second.current_stage == OrchestrationStage.PROPOSING
    coordinator._run_explore.assert_not_awaited()
    assert coordinator.agent_runner.run.await_count == 1


@pytest.mark.asyncio
async def test_explore_checkpoint_rejects_different_clarification(mock_env):
    coordinator, uow, _, _repo_dir = mock_env
    coordinator.agent_runner.run = AsyncMock(
        return_value=AgentExecutionResult(
            exit_code=0,
            timed_out=False,
            stdout=["HUMAN REQUIRED\n- Debe decidir un alcance"],
            stderr=[],
            duration_ms=11,
        )
    )
    first = await coordinator.execute_project_request(
        "proj-1",
        thinker_provider="antigravity",
        implementer_provider="antigravity",
        reviewer_provider="antigravity",
    )
    assert first.status == "HUMAN_REQUIRED"
    run = uow.orchestration_runs.get_by_id(first.run_id)
    assert run.stop_details["explore_checkpoint"]["status"] == "HUMAN_REQUIRED"

    # An identical reentry returns the durable gate without new inference.
    run.stop_details["request_normalization"] = {"normalized_body": "We need redis caching layer"}
    uow.orchestration_runs.save(run)
    second = await coordinator.execute_project_request(
        "proj-1",
        thinker_provider="antigravity",
        implementer_provider="antigravity",
        reviewer_provider="antigravity",
    )
    assert second.status == "HUMAN_REQUIRED"
    assert second.human_payload == first.human_payload
    assert coordinator.agent_runner.run.await_count == 1

    # A new operator clarification changes the hash: no stale gate reuse.
    coordinator._run_explore = AsyncMock(return_value={"status": "READY_TO_PROPOSE"})
    coordinator._run_propose = AsyncMock(
        return_value={"status": "FAILED", "message": "Boundary stop"}
    )
    third = await coordinator.execute_project_request(
        "proj-1",
        operator_clarification="Clarificación nueva y material",
        thinker_provider="antigravity",
        implementer_provider="antigravity",
        reviewer_provider="antigravity",
    )
    assert third.current_stage == OrchestrationStage.PROPOSING
    coordinator._run_explore.assert_awaited_once()
