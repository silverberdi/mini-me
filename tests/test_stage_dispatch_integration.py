"""Operational integration suite for full stage profile dispatch, capacity validation, and runner arguments.

Proves the end-to-end operational flow:
etapa -> perfil proveedor/modelo/esfuerzo -> descubrimiento de capacidades reales CLI/cuenta ->
validación de capacidad vinculada a cuenta/modelo -> preflight JIT -> argumentos efectivos del runner.

Intercepts subprocess dispatch without consuming provider inference tokens, verifying both valid
operational execution and fail-closed rejections of nonexistent models, incompatible efforts,
fabricated capacity, preflight errors, and reviewer collisions.
"""

from __future__ import annotations

import hashlib
import subprocess
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from minime.adapters.provider_adapter import CapacityObservation
from minime.config import (
    AppConfig,
    CliInvocationConfig,
    OpenSpecStage,
    ProjectConfig,
    ProviderConfig,
    StageProfileConfig,
)
from minime.domain.enums import (
    CapacitySignalSource,
    ChangeStatus,
    JobStatus,
    OrchestrationStage,
    ProviderHealthStatus,
    ProviderResultClass,
    ReadinessState,
    WorktreeCreationState,
)
from minime.domain.models import (
    Change,
    Job,
    OrchestrationRun,
    OrchestrationWorktreeOwnership,
    Project,
    ProjectManagedRepositoryBinding,
    ProviderHealth,
    RecoveryClaimContext,
    utc_now,
)
from minime.services.agent_confinement import AgentProcessConfinement, AgentProcessResult
from minime.services.cli_preflight import PreflightResult
from minime.services.execution_pipeline import ExecutionPipelineService
from minime.services.native_openspec_apply import AGY_APPLY_SKILL_PATH, CODEX_APPLY_SKILL_PATH
from minime.services.worktree_manager import WorktreeInfo


class OperationalTestWorktreeManager:
    """Deterministic worktree manager creating authentic files for native OpenSpec tests."""

    def __init__(self, workspace_path: Path):
        self.workspace_path = workspace_path
        self.workspace_path.mkdir(parents=True, exist_ok=True)

    async def create_worktree(
        self,
        job_id: str,
        change_name: str,
        base_branch: str,
        *args: Any,
        **kwargs: Any,
    ) -> WorktreeInfo:
        del job_id, change_name, base_branch, args, kwargs
        sha = await self.current_sha(self.workspace_path)
        return WorktreeInfo(
            path=self.workspace_path,
            branch_name="minime/change-branch",
            base_sha=sha,
        )

    async def create_execution_worktree(self, job_id: str, change_name: str, base_sha: str):
        del job_id, change_name, base_sha
        sha = await self.current_sha(self.workspace_path)
        return WorktreeInfo(
            path=self.workspace_path,
            branch_name="minime/change-branch",
            base_sha=sha,
        )

    async def current_sha(self, worktree_path: Path | str) -> str:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(worktree_path),
            check=False,
            capture_output=True,
            text=True,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return proc.stdout.strip()
        return "base-sha-123456"

    async def cleanup_worktree(self, job_id: str, project_id: str | None = None) -> None:
        del job_id, project_id

    async def remove_clean_worktree(self, job_id: str, project_id: str | None = None) -> None:
        del job_id, project_id

    async def working_state_fingerprint(self, worktree_path: Path) -> str:
        del worktree_path
        return "fp-clean"

    async def finalize_candidate_commit(
        self, worktree_path: Path, job_id: str, project_id: str
    ) -> str:
        del worktree_path, job_id, project_id
        return "candidate-sha-123456"

    async def create_review_worktree(
        self, job_id: str, change_name: str, candidate_sha: str, reviewer_role: str, project_id: str
    ):
        del job_id, change_name, candidate_sha, reviewer_role, project_id
        return WorktreeInfo(
            path=self.workspace_path,
            branch_name="minime/change-branch",
            base_sha="base-sha-123456",
        )


def _acquire_claim(in_memory_uow: Any, claim_key: str = "run:test-pipe") -> RecoveryClaimContext:
    if hasattr(in_memory_uow, "claims") and in_memory_uow.claims is not None:
        ctx = in_memory_uow.claims.acquire_or_reacquire(claim_key, "test-instance", 3600)
        if ctx:
            if isinstance(ctx, RecoveryClaimContext):
                return ctx
            return RecoveryClaimContext(
                claim_key=getattr(ctx, "claim_key", claim_key),
                owner_instance_id=getattr(ctx, "owner_instance_id", "test-instance"),
                fence_token=getattr(ctx, "fence_token", 1),
                lease_expires_at=getattr(ctx, "lease_expires_at", utc_now() + timedelta(hours=1)),
            )
    return RecoveryClaimContext(
        claim_key=claim_key,
        owner_instance_id="test-instance",
        fence_token=1,
        lease_expires_at=utc_now() + timedelta(hours=1),
    )


def _build_test_app_config() -> AppConfig:
    return AppConfig(
        providers={
            "antigravity": ProviderConfig(
                type="cli",
                command="agy",
                enabled=True,
                roles=["implementer", "reviewer"],
                invocation={
                    "implementer": CliInvocationConfig(
                        args=[
                            "--mode",
                            "accept-edits",
                            "--dangerously-skip-permissions",
                            "--print-timeout",
                            "1h",
                            "--print={prompt}",
                        ],
                        prompt_transport="argument",
                    ),
                    "reviewer": CliInvocationConfig(
                        args=[
                            "--mode",
                            "plan",
                            "--dangerously-skip-permissions",
                            "--print-timeout",
                            "1h",
                            "--print={prompt}",
                        ],
                        prompt_transport="argument",
                    ),
                },
            ),
            "codex": ProviderConfig(
                type="cli",
                command="codex",
                enabled=True,
                roles=["implementer", "reviewer"],
                invocation={
                    "implementer": CliInvocationConfig(
                        args=["exec", "-", "--approve-for-me", "--ephemeral"],
                        prompt_transport="stdin",
                    ),
                    "reviewer": CliInvocationConfig(
                        args=["review", "-"],
                        prompt_transport="stdin",
                    ),
                },
            ),
        }
    )


def _seed_operational_workspace(
    in_memory_uow: Any,
    workspace_path: Path,
    change_name: str = "test-operational-change",
    implementer: str = "antigravity",
    reviewer: str = "codex",
    stage_profiles: dict[str, StageProfileConfig] | None = None,
) -> tuple[Project, Job, OrchestrationRun]:
    # 1. Install genuine native OpenSpec skill files in the candidate worktree
    skill_content = (
        "---\n"
        "name: openspec-apply-change\n"
        "description: Native OpenSpec apply workflow\n"
        "metadata:\n"
        '  version: "1.0"\n'
        "---\n"
        "Apply instructions\n"
    )
    agy_skill = workspace_path / AGY_APPLY_SKILL_PATH
    agy_skill.parent.mkdir(parents=True, exist_ok=True)
    agy_skill.write_text(skill_content, encoding="utf-8")

    codex_skill = workspace_path / CODEX_APPLY_SKILL_PATH
    codex_skill.parent.mkdir(parents=True, exist_ok=True)
    codex_skill.write_text(skill_content, encoding="utf-8")

    # 2. Seed OpenSpec change artifacts
    change_dir = workspace_path / "openspec" / "changes" / change_name
    change_dir.mkdir(parents=True, exist_ok=True)
    (change_dir / "proposal.md").write_text("# Proposal\n", encoding="utf-8")
    (change_dir / "design.md").write_text("# Design\n", encoding="utf-8")
    (change_dir / "tasks.md").write_text(
        "# Tasks\n\n## 1. Implementation\n- [ ] 1.1 First task\n", encoding="utf-8"
    )
    (change_dir / "specs" / "feature").mkdir(parents=True, exist_ok=True)
    (change_dir / "specs" / "feature" / "spec.md").write_text("# Spec\n", encoding="utf-8")

    # Initialize authentic git repository in candidate worktree
    subprocess.run(["git", "init"], cwd=str(workspace_path), check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=str(workspace_path),
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=str(workspace_path),
        check=True,
        capture_output=True,
    )
    subprocess.run(["git", "add", "."], cwd=str(workspace_path), check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"], cwd=str(workspace_path), check=True, capture_output=True
    )
    base_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(workspace_path),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    # 3. Save Project and Managed Binding
    project = Project(
        project_id="test-project",
        display_name="Test Operational Project",
        repository="test-org/test-repo",
        base_branch="main",
        openspec_path="openspec",
        implementer=implementer,
        reviewer=reviewer,
        external_providers_allowed=["codex", "antigravity"],
    )
    in_memory_uow.projects.save(project)

    binding = ProjectManagedRepositoryBinding(
        project_id="test-project",
        canonical_repository_identity="test-org/test-repo",
        managed_repository_root=str(workspace_path.parent / "repo"),
        worktree_parent_dir=str(workspace_path.parent / "worktrees"),
        is_valid=True,
    )
    in_memory_uow.project_managed_repository_bindings.save(binding)

    # 4. Save Change, Run, Job, and Ownership
    change = Change(
        project_id="test-project",
        name=change_name,
        status=ChangeStatus.READY,
        last_readiness_status=ReadinessState.READY,
    )
    in_memory_uow.changes.save(change)

    run = OrchestrationRun(
        run_id="run-operational-1",
        project_id="test-project",
        change_name=change_name,
        base_sha=base_sha,
        current_stage=OrchestrationStage.IMPLEMENTING,
        resumable_stage=OrchestrationStage.IMPLEMENTING,
        is_active=True,
        active_job_id="job-operational-1",
    )
    in_memory_uow.orchestration_runs.save(run)

    job = Job(
        job_id="job-operational-1",
        project_id="test-project",
        change_name=change_name,
        implementer_role=implementer,
        current_executor=implementer,
        base_sha=base_sha,
        status=JobStatus.QUEUED,
    )
    in_memory_uow.jobs.save(job)

    ownership = OrchestrationWorktreeOwnership(
        worktree_id="own-operational-1",
        job_id=job.job_id,
        run_id=run.run_id,
        project_id="test-project",
        change_name=change_name,
        canonical_worktree_path=str(workspace_path),
        source_repository_identity="test-org/test-repo",
        source_base_sha=base_sha,
        branch="minime/change-branch",
        creation_state=WorktreeCreationState.CREATED,
    )
    in_memory_uow.orchestration_worktree_ownerships.save(ownership)

    # 5. Set default available capacity health for providers
    in_memory_uow.provider_health.save(
        ProviderHealth(
            provider="antigravity",
            status=ProviderHealthStatus.AVAILABLE,
            last_result_class=ProviderResultClass.SUCCESS,
            last_success_at=utc_now(),
            model="gemini-3.8-flash-medium",
        )
    )
    in_memory_uow.provider_health.save(
        ProviderHealth(
            provider="codex",
            status=ProviderHealthStatus.AVAILABLE,
            last_result_class=ProviderResultClass.SUCCESS,
            last_success_at=utc_now(),
            model="gpt-4o-mini",
        )
    )
    in_memory_uow.commit()
    return project, job, run


@pytest.mark.asyncio
async def test_antigravity_apply_operational_dispatch_effective_arguments(
    in_memory_uow, tmp_path, monkeypatch
):
    """Prove the complete operational flow for Antigravity APPLY.

    Validates: stage selection -> stage profile -> JIT preflight -> runner dispatch.
    Intercepts subprocess execution without calling any external provider inference,
    verifying effective arguments (--model gemini-3.8-flash-medium, --effort medium)
    and the native /opsx-apply instruction in the prompt.
    """
    workspace = tmp_path / "candidate-worktree"
    project, job, _ = _seed_operational_workspace(
        in_memory_uow, workspace, implementer="antigravity", reviewer="codex"
    )

    app_cfg = _build_test_app_config()
    pipeline = ExecutionPipelineService(
        in_memory_uow,
        project_root=tmp_path,
        app_config=app_cfg,
        worktree_manager=OperationalTestWorktreeManager(workspace),
    )

    intercepted_subprocesses: list[dict[str, Any]] = []

    async def mock_run_confined_async_subprocess(
        self, cmd, cwd, *, input_bytes, timeout_seconds, **kwargs
    ):
        intercepted_subprocesses.append(
            {
                "cmd": list(cmd),
                "cwd": cwd,
                "input_bytes": input_bytes,
                "timeout_seconds": timeout_seconds,
            }
        )
        # Return valid exit code 0 without executing real inference
        return AgentProcessResult(
            returncode=0,
            stdout=b"Antigravity native apply completed tasks.\n",
            stderr=b"",
        )

    monkeypatch.setattr(
        AgentProcessConfinement,
        "run_confined_async_subprocess",
        mock_run_confined_async_subprocess,
    )

    # Preflight JIT check against binary/flags should succeed
    monkeypatch.setattr(
        "minime.services.execution_pipeline.preflight_cli_invocation",
        lambda profile: PreflightResult(ok=True),
    )

    claim = _acquire_claim(in_memory_uow)

    # Execute queued job
    _ = await pipeline.execute_queued_job(job.job_id, claim_context=claim)

    # Verify that the runner was dispatched exactly once
    assert len(intercepted_subprocesses) == 1
    call = intercepted_subprocesses[0]

    cmd = call["cmd"]
    # Check effective runner arguments
    assert "--model" in cmd
    model_idx = cmd.index("--model")
    assert cmd[model_idx + 1] == "gemini-3.8-flash-medium"

    assert "--effort" in cmd
    effort_idx = cmd.index("--effort")
    assert cmd[effort_idx + 1] == "medium"

    # Check that native /opsx-apply instruction was passed in the argument prompt
    print_arg = next((arg for arg in cmd if arg.startswith("--print=")), None)
    assert print_arg is not None
    assert "/opsx-apply test-operational-change" in print_arg
    assert "CANDIDATE WORKSPACE" in print_arg
    assert str(workspace.resolve()) in print_arg


@pytest.mark.asyncio
async def test_codex_apply_operational_dispatch_effective_arguments(
    in_memory_uow, tmp_path, monkeypatch
):
    """Prove the complete operational flow for Codex APPLY.

    Validates: stage selection -> stage profile -> JIT preflight -> runner dispatch.
    Intercepts subprocess execution without calling any external provider inference,
    verifying effective arguments (--model gpt-4o-mini, model_reasoning_effort="medium")
    and the native $openspec-apply-change instruction on stdin.
    """
    workspace = tmp_path / "candidate-worktree"
    project, job, _ = _seed_operational_workspace(
        in_memory_uow, workspace, implementer="codex", reviewer="antigravity"
    )

    app_cfg = _build_test_app_config()
    pipeline = ExecutionPipelineService(
        in_memory_uow,
        project_root=tmp_path,
        app_config=app_cfg,
        worktree_manager=OperationalTestWorktreeManager(workspace),
    )

    intercepted_subprocesses: list[dict[str, Any]] = []

    async def mock_run_confined_async_subprocess(
        self, cmd, cwd, *, input_bytes, timeout_seconds, **kwargs
    ):
        intercepted_subprocesses.append(
            {
                "cmd": list(cmd),
                "cwd": cwd,
                "input_bytes": input_bytes,
                "timeout_seconds": timeout_seconds,
            }
        )
        return AgentProcessResult(
            returncode=0,
            stdout=b'{"type": "message", "content": "Codex apply done"}\n',
            stderr=b"",
        )

    monkeypatch.setattr(
        AgentProcessConfinement,
        "run_confined_async_subprocess",
        mock_run_confined_async_subprocess,
    )
    monkeypatch.setattr(
        "minime.services.execution_pipeline.preflight_cli_invocation",
        lambda profile: PreflightResult(ok=True),
    )

    claim = _acquire_claim(in_memory_uow)

    _ = await pipeline.execute_queued_job(job.job_id, claim_context=claim)

    assert len(intercepted_subprocesses) == 1
    call = intercepted_subprocesses[0]

    cmd = call["cmd"]
    assert "--model" in cmd
    model_idx = cmd.index("--model")
    assert cmd[model_idx + 1] == "gpt-4o-mini"

    # Check reasoning effort configuration
    cmd_str = " ".join(cmd)
    assert 'model_reasoning_effort="medium"' in cmd_str

    # Check that native Codex skill is invoked via stdin
    stdin_text = call["input_bytes"].decode("utf-8")
    assert "$openspec-apply-change test-operational-change" in stdin_text
    assert "CANDIDATE WORKSPACE" in stdin_text


@pytest.mark.asyncio
async def test_rejection_of_unsupported_model_fails_closed_before_runner(
    in_memory_uow, tmp_path, monkeypatch
):
    """Prove an unmapped/nonexistent model fails closed to NEEDS_HUMAN before runner dispatch."""
    workspace = tmp_path / "candidate-worktree"
    project, job, _ = _seed_operational_workspace(
        in_memory_uow, workspace, implementer="antigravity", reviewer="codex"
    )

    # Configure an unsupported model on the project for APPLY
    app_cfg = _build_test_app_config()
    app_cfg.projects["test-project"] = ProjectConfig(
        repository="test-org/test-repo",
        external_providers_allowed=["codex", "antigravity"],
        stage_profiles={
            "APPLY": StageProfileConfig(
                provider="antigravity",
                model="gemini-nonexistent-99",
                effort="medium",
            )
        },
    )

    pipeline = ExecutionPipelineService(
        in_memory_uow,
        project_root=tmp_path,
        app_config=app_cfg,
        worktree_manager=OperationalTestWorktreeManager(workspace),
    )

    intercepted: list[str] = []

    async def mock_run_fail(self, *args, **kwargs):
        intercepted.append("subprocess")
        raise AssertionError("Subprocess must not be invoked when model is unsupported")

    monkeypatch.setattr(
        AgentProcessConfinement,
        "run_confined_async_subprocess",
        mock_run_fail,
    )

    claim = _acquire_claim(in_memory_uow)

    result_job = await pipeline.execute_queued_job(job.job_id, claim_context=claim)

    assert result_job.status == JobStatus.NEEDS_HUMAN
    assert "UNSUPPORTED_MODEL" in (result_job.error_message or "")
    assert intercepted == []


@pytest.mark.asyncio
async def test_rejection_of_incompatible_effort_fails_closed_before_runner(
    in_memory_uow, tmp_path, monkeypatch
):
    """Prove an incompatible effort fails closed to NEEDS_HUMAN before runner dispatch."""
    workspace = tmp_path / "candidate-worktree"
    project, job, _ = _seed_operational_workspace(
        in_memory_uow, workspace, implementer="antigravity", reviewer="codex"
    )

    app_cfg = _build_test_app_config()
    app_cfg.projects["test-project"] = ProjectConfig(
        repository="test-org/test-repo",
        external_providers_allowed=["codex", "antigravity"],
        stage_profiles={
            "APPLY": StageProfileConfig(
                provider="antigravity",
                model="gemini-3.8-flash-medium",
                effort="unsupported-effort",
            )
        },
    )

    pipeline = ExecutionPipelineService(
        in_memory_uow,
        project_root=tmp_path,
        app_config=app_cfg,
        worktree_manager=OperationalTestWorktreeManager(workspace),
    )

    intercepted: list[str] = []

    async def mock_run_fail(self, *args, **kwargs):
        intercepted.append("subprocess")
        raise AssertionError("Subprocess must not be invoked when effort is unsupported")

    monkeypatch.setattr(
        AgentProcessConfinement,
        "run_confined_async_subprocess",
        mock_run_fail,
    )

    claim = _acquire_claim(in_memory_uow)

    result_job = await pipeline.execute_queued_job(job.job_id, claim_context=claim)

    assert result_job.status == JobStatus.NEEDS_HUMAN
    assert "UNSUPPORTED_EFFORT" in (result_job.error_message or "")
    assert intercepted == []


@pytest.mark.asyncio
async def test_rejection_of_premium_model_default_fails_closed_before_runner(
    in_memory_uow, tmp_path, monkeypatch
):
    """Prove configured premium models fail closed without authorized escalation."""
    workspace = tmp_path / "candidate-worktree"
    project, job, _ = _seed_operational_workspace(
        in_memory_uow, workspace, implementer="antigravity", reviewer="codex"
    )

    app_cfg = _build_test_app_config()
    app_cfg.projects["test-project"] = ProjectConfig(
        repository="test-org/test-repo",
        external_providers_allowed=["codex", "antigravity"],
        stage_profiles={
            "APPLY": StageProfileConfig(
                provider="antigravity",
                model="gemini-2.5-pro",
                effort="medium",
            )
        },
    )

    pipeline = ExecutionPipelineService(
        in_memory_uow,
        project_root=tmp_path,
        app_config=app_cfg,
        worktree_manager=OperationalTestWorktreeManager(workspace),
    )

    intercepted: list[str] = []

    async def mock_run_fail(self, *args, **kwargs):
        intercepted.append("subprocess")
        raise AssertionError("Subprocess must not be invoked when premium model is unauthorized")

    monkeypatch.setattr(
        AgentProcessConfinement,
        "run_confined_async_subprocess",
        mock_run_fail,
    )

    claim = _acquire_claim(in_memory_uow)

    result_job = await pipeline.execute_queued_job(job.job_id, claim_context=claim)

    assert result_job.status == JobStatus.NEEDS_HUMAN
    assert "PREMIUM_MODEL_REJECTED" in (result_job.error_message or "")
    assert intercepted == []


@pytest.mark.asyncio
async def test_rejection_of_fabricated_capacity_observation_fails_closed_to_waiting(
    in_memory_uow, tmp_path, monkeypatch
):
    """Prove fabricated capacity observations (e.g. positive output tokens) fail closed to WAITING_CAPACITY."""
    workspace = tmp_path / "candidate-worktree"
    project, job, _ = _seed_operational_workspace(
        in_memory_uow, workspace, implementer="antigravity", reviewer="codex"
    )

    # Simulate adapter returning invalid/unauthenticated/fabricated capacity observation
    now = utc_now()
    fabricated_obs = CapacityObservation(
        provider="antigravity",
        model="gemini-3.8-flash-medium",
        observed_at=now,
        expires_at=now + timedelta(seconds=60),
        ordinary_usage_allowed=None,  # Invalid/unverified capacity result!
        source_signal=CapacitySignalSource.AGY_PRINT_USAGE,
        account_id=hashlib.sha256(b"authentic-account").hexdigest(),
    )

    class FabricatingAdapter:
        supports_read_only_capacity_observation = True

        async def check_cli_present(self):
            return True

        async def check_auth_ready(self):
            return True

        async def read_capacity_observation(self, timeout_seconds=10.0, selected_model=None):
            return fabricated_obs

    monkeypatch.setattr(
        "minime.services.provider_health_service.get_provider_adapter",
        lambda provider: FabricatingAdapter(),
    )

    app_cfg = _build_test_app_config()
    pipeline = ExecutionPipelineService(
        in_memory_uow,
        project_root=tmp_path,
        app_config=app_cfg,
        worktree_manager=OperationalTestWorktreeManager(workspace),
    )

    intercepted: list[str] = []

    async def mock_run_fail(self, *args, **kwargs):
        intercepted.append("subprocess")
        raise AssertionError(
            "Subprocess must not be invoked when capacity observation is fabricated"
        )

    monkeypatch.setattr(
        AgentProcessConfinement,
        "run_confined_async_subprocess",
        mock_run_fail,
    )

    claim = _acquire_claim(in_memory_uow)

    result_job = await pipeline.execute_queued_job(job.job_id, claim_context=claim)

    # Must transition to WAITING_CAPACITY without invoking the runner
    assert result_job.status == JobStatus.WAITING_CAPACITY
    assert intercepted == []


@pytest.mark.asyncio
async def test_rejection_of_jit_cli_preflight_failure_fails_closed_before_runner(
    in_memory_uow, tmp_path, monkeypatch
):
    """Prove JIT preflight failure (e.g. missing CLI or flags) transitions to NEEDS_HUMAN before running."""
    workspace = tmp_path / "candidate-worktree"
    project, job, _ = _seed_operational_workspace(
        in_memory_uow, workspace, implementer="antigravity", reviewer="codex"
    )

    app_cfg = _build_test_app_config()
    pipeline = ExecutionPipelineService(
        in_memory_uow,
        project_root=tmp_path,
        app_config=app_cfg,
        worktree_manager=OperationalTestWorktreeManager(workspace),
    )

    # Simulate JIT preflight failure (e.g. executable missing)
    monkeypatch.setattr(
        "minime.services.execution_pipeline.preflight_cli_invocation",
        lambda profile: PreflightResult(ok=False, reason="EXECUTABLE_MISSING"),
    )

    intercepted: list[str] = []

    async def mock_run_fail(self, *args, **kwargs):
        intercepted.append("subprocess")
        raise AssertionError("Subprocess must not be invoked when JIT preflight fails")

    monkeypatch.setattr(
        AgentProcessConfinement,
        "run_confined_async_subprocess",
        mock_run_fail,
    )

    claim = _acquire_claim(in_memory_uow)

    result_job = await pipeline.execute_queued_job(job.job_id, claim_context=claim)

    assert result_job.status == JobStatus.NEEDS_HUMAN
    assert "Implementer CLI preflight failed: EXECUTABLE_MISSING" in (
        result_job.error_message or ""
    )
    assert intercepted == []


@pytest.mark.asyncio
async def test_rejection_of_author_reviewer_identity_collision_fails_closed(
    in_memory_uow, tmp_path, monkeypatch
):
    """Prove REVIEW stage profile resolution rejects same-identity author/reviewer collision."""
    workspace = tmp_path / "candidate-worktree"
    # Seed workspace with identical implementer and reviewer
    project, job, _ = _seed_operational_workspace(
        in_memory_uow, workspace, implementer="antigravity", reviewer="antigravity"
    )

    app_cfg = _build_test_app_config()
    pipeline = ExecutionPipelineService(
        in_memory_uow,
        project_root=tmp_path,
        app_config=app_cfg,
        worktree_manager=OperationalTestWorktreeManager(workspace),
    )

    with pytest.raises(Exception, match="REVIEWER_IDENTITY_COLLISION"):
        pipeline._resolve_stage_profile(
            project,
            OpenSpecStage.REVIEW,
            requested_provider="antigravity",
            implementer_provider="antigravity",
        )
