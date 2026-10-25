import io
import subprocess
import zipfile
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from minime.domain.enums import (
    ExternalOutcome,
    ExternalReasonCode,
    ProjectOnboardingStatus,
    ProjectType,
)
from minime.domain.models import (
    ExternalActionResult,
    Project,
    ProjectAgentProfile,
    ProjectConfigurationInput,
    ProjectExecutionPolicy,
    ProjectManagedRepositoryBinding,
    ProjectProviderConnection,
)
from minime.services.context_archive import UnsafeContextArchive
from minime.services.greenfield_bootstrap import (
    GreenfieldBootstrapCoordinator,
    GreenfieldBootstrapError,
)
from minime.services.implementer_runner import ImplementerResult
from minime.services.project_service import ProjectService


def _initialize_test_repository(worktree: Path) -> None:
    """The fail-closed candidate scope gate requires a real Git base commit."""
    subprocess.run(["git", "init"], cwd=worktree, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=worktree, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=worktree, check=True)
    subprocess.run(["git", "add", "."], cwd=worktree, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "baseline"],
        cwd=worktree,
        check=True,
        capture_output=True,
    )


def _configuration() -> ProjectConfigurationInput:
    profile = ProjectAgentProfile(
        agent_id="codex",
        model_id="gpt-5.6-luna",
        effort="medium",
        workflows=["$openspec-propose"],
        skills=["openspec-propose"],
    )
    profiles = {
        "thinking": profile,
        "execution": profile.model_copy(update={"model_id": "gpt-5.6-implementation"}),
        "independent_review": profile.model_copy(
            update={"agent_id": "antigravity", "model_id": "gemini-review"}
        ),
        "fallback": profile.model_copy(update={"agent_id": "antigravity", "model_id": "gemini-fallback"}),
    }
    connection = ProjectProviderConnection(
        provider_id="github", repository_url="example/greenfield", auth_mode="environment_app"
    )
    return ProjectConfigurationInput(
        project_id="greenfield",
        display_name="Greenfield",
        project_type=ProjectType.GREENFIELD,
        repository="example/greenfield",
        provider_connections={"tickets": connection, "git_pr": connection},
        agent_profiles=profiles,
        execution_policy=ProjectExecutionPolicy(
            fallback_daily_cap_usd=Decimal("0"), fallback_monthly_cap_usd=Decimal("0")
        ),
    )


def test_invalid_zip_is_rejected_before_project_persistence(in_memory_uow, tmp_path):
    coordinator = GreenfieldBootstrapCoordinator(
        in_memory_uow,
        trusted_managed_root=tmp_path / "managed",
    )

    with pytest.raises(UnsafeContextArchive):
        coordinator.bootstrap(_configuration(), b"not-a-zip")

    assert in_memory_uow.projects.get_by_id("greenfield") is None


def test_candidate_validation_requires_canonical_anchors_and_preserves_source(tmp_path: Path):
    package = tmp_path / "package"
    incoming = tmp_path / "worktree" / "context" / "incoming" / "sha"
    package.mkdir()
    incoming.mkdir(parents=True)
    (package / "facts.md").write_text("source", encoding="utf-8")
    (incoming / "facts.md").write_text("source", encoding="utf-8")
    worktree = incoming.parents[2]
    (worktree / "AGENTS.md").write_text("See context/incoming/sha/facts.md", encoding="utf-8")
    (worktree / "openspec").mkdir()
    (worktree / "openspec" / "config.yaml").write_text(
        "context: context/incoming/sha/facts.md\n", encoding="utf-8"
    )
    (worktree / "context" / "INDEX.md").write_text(
        "# Context\n\n- facts.md: context/incoming/sha/facts.md\n", encoding="utf-8"
    )

    _initialize_test_repository(worktree)
    GreenfieldBootstrapCoordinator._validate_candidate(
        worktree, incoming, ("facts.md",), package
    )

    (incoming / "facts.md").write_text("changed", encoding="utf-8")
    with pytest.raises(GreenfieldBootstrapError, match="fidelity"):
        GreenfieldBootstrapCoordinator._validate_candidate(
            worktree, incoming, ("facts.md",), package
        )


def test_candidate_validation_rejects_secret_markers(tmp_path: Path):
    worktree = tmp_path / "worktree"
    incoming = worktree / "context" / "incoming" / "sha"
    incoming.mkdir(parents=True)
    (incoming / "facts.md").write_text("source", encoding="utf-8")
    (worktree / "AGENTS.md").write_text("context/incoming/sha/facts.md", encoding="utf-8")
    (worktree / "openspec").mkdir()
    (worktree / "openspec" / "config.yaml").write_text(
        "context: context/incoming/sha/facts.md\n", encoding="utf-8"
    )
    (worktree / "notes.txt").write_text("BEGIN PRIVATE KEY", encoding="utf-8")
    _initialize_test_repository(worktree)

    with pytest.raises(GreenfieldBootstrapError, match="secret"):
        GreenfieldBootstrapCoordinator._validate_candidate(worktree, incoming)


def test_candidate_validation_rejects_repository_escape_or_missing_links(tmp_path: Path):
    worktree = tmp_path / "worktree"
    incoming = worktree / "context" / "incoming" / "sha"
    incoming.mkdir(parents=True)
    (incoming / "facts.md").write_text("source", encoding="utf-8")
    (worktree / "AGENTS.md").write_text(
        "[context](context/INDEX.md)", encoding="utf-8"
    )
    (worktree / "openspec").mkdir()
    (worktree / "openspec" / "config.yaml").write_text(
        "context: context/INDEX.md\n", encoding="utf-8"
    )
    (worktree / "context" / "INDEX.md").write_text(
        "[escape](../../outside.md)", encoding="utf-8"
    )
    _initialize_test_repository(worktree)

    with pytest.raises(GreenfieldBootstrapError, match="reference"):
        GreenfieldBootstrapCoordinator._validate_candidate(worktree, incoming)


def test_candidate_validation_rejects_unrelated_backlog_changes(tmp_path: Path):
    worktree = tmp_path / "worktree"
    incoming = worktree / "context" / "incoming" / "sha"
    incoming.mkdir(parents=True)
    (incoming / "facts.md").write_text("source", encoding="utf-8")
    (worktree / "AGENTS.md").write_text("context/INDEX.md", encoding="utf-8")
    (worktree / "openspec").mkdir()
    (worktree / "openspec" / "config.yaml").write_text(
        "context: |\n  Índice: [context/INDEX.md](context/INDEX.md)\n", encoding="utf-8"
    )
    (worktree / "context" / "INDEX.md").write_text("facts.md", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=worktree, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=worktree, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=worktree, check=True)
    subprocess.run(["git", "add", "."], cwd=worktree, check=True)
    subprocess.run(["git", "commit", "-m", "baseline"], cwd=worktree, check=True, capture_output=True)
    (worktree / "ROADMAP.md").write_text("unsupported backlog", encoding="utf-8")

    with pytest.raises(GreenfieldBootstrapError, match="unrelated"):
        GreenfieldBootstrapCoordinator._validate_candidate(worktree, incoming)


def test_candidate_scope_allows_official_openspec_scaffolds(tmp_path: Path):
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    subprocess.run(["git", "init"], cwd=worktree, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=worktree, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=worktree, check=True)
    (worktree / "openspec" / "changes" / "archive").mkdir(parents=True)
    (worktree / "openspec" / "specs").mkdir(parents=True)
    (worktree / "openspec" / "changes" / "archive" / ".gitkeep").touch()
    (worktree / "openspec" / "specs" / ".gitkeep").touch()
    subprocess.run(["git", "add", "."], cwd=worktree, check=True)
    subprocess.run(
        ["git", "commit", "-m", "baseline"],
        cwd=worktree,
        check=True,
        capture_output=True,
    )

    GreenfieldBootstrapCoordinator._validate_candidate_scope(worktree)


def test_candidate_scope_uses_exact_manifest_and_official_paths(tmp_path: Path):
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    subprocess.run(["git", "init"], cwd=worktree, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=worktree, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=worktree, check=True)
    (worktree / ".agents/skills/minime-engineering-discipline").mkdir(parents=True)
    (worktree / ".agents/skills/minime-engineering-discipline/SKILL.md").write_text(
        "guidance", encoding="utf-8"
    )
    (worktree / ".agents/skills/openspec-verify-change").mkdir(parents=True)
    (worktree / ".agents/skills/openspec-verify-change/SKILL.md").write_text(
        "official", encoding="utf-8"
    )
    (worktree / ".agents/workflows").mkdir(parents=True)
    (worktree / ".agents/workflows/opsx-verify.md").write_text(
        "official", encoding="utf-8"
    )
    subprocess.run(["git", "add", "."], cwd=worktree, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "baseline"], cwd=worktree, check=True, capture_output=True
    )

    (worktree / ".agents/skills/minime-engineering-discipline/SKILL.md").write_text(
        "updated", encoding="utf-8"
    )
    GreenfieldBootstrapCoordinator._validate_candidate_scope(
        worktree,
        allowed_paths={
            ".agents/skills/minime-engineering-discipline/SKILL.md",
            ".agents/skills/openspec-verify-change/SKILL.md",
            ".agents/workflows/opsx-verify.md",
        },
    )

    (worktree / ".agents/skills/unselected.txt").write_text("reject", encoding="utf-8")
    with pytest.raises(GreenfieldBootstrapError, match="unrelated"):
        GreenfieldBootstrapCoordinator._validate_candidate_scope(
            worktree,
            allowed_paths={
                ".agents/skills/minime-engineering-discipline/SKILL.md",
                ".agents/skills/openspec-verify-change/SKILL.md",
                ".agents/workflows/opsx-verify.md",
            },
        )


def test_simulated_agent_cycle_validates_manifest_paths_and_preserves_checkpoint(
    in_memory_uow, tmp_path: Path
):
    config = _configuration()
    project = Project(
        project_id=config.project_id,
        display_name=config.display_name,
        repository=config.repository,
        project_type=ProjectType.GREENFIELD,
        base_branch="main",
        onboarding_checkpoint={"source_zip_sha256": "a" * 64},
    )
    in_memory_uow.projects.save(project)
    worktree = tmp_path / "worktree"
    incoming = worktree / "context" / "incoming" / ("a" * 64)
    incoming.mkdir(parents=True)
    package = tmp_path / "package"
    package.mkdir()
    (package / "request.md").write_text("Given a source\n", encoding="utf-8")
    (incoming / "request.md").write_text("Given a source\n", encoding="utf-8")
    (worktree / "AGENTS.md").write_text(
        "Use context/INDEX.md as the canonical context.\n", encoding="utf-8"
    )
    (worktree / "openspec").mkdir()
    (worktree / "openspec" / "config.yaml").write_text(
        "context: context/INDEX.md\n", encoding="utf-8"
    )
    (worktree / "context" / "INDEX.md").write_text(
        "# Context\n\n- [Request](01-producto/request.md)\n", encoding="utf-8"
    )
    (worktree / "context" / "01-producto").mkdir()
    (worktree / "context" / "01-producto" / "request.md").write_text(
        "Source-backed request.\n", encoding="utf-8"
    )
    (worktree / ".agents" / "skills" / "minime-engineering-discipline").mkdir(
        parents=True
    )
    skill = worktree / ".agents" / "skills" / "minime-engineering-discipline" / "SKILL.md"
    skill.write_text("Installed capability.\n", encoding="utf-8")
    _initialize_test_repository(worktree)

    class SimulatedAgent:
        async def run(self, agent_worktree, instruction, timeout_seconds):
            assert agent_worktree == worktree
            assert "context/incoming" in instruction
            assert timeout_seconds == 5
            return ImplementerResult(
                exit_code=0,
                timed_out=False,
                stdout=["simulated agent completed"],
                stderr=[],
                duration_ms=7,
                native_workflow_evidence={"workflow": "simulated"},
            )

    coordinator = GreenfieldBootstrapCoordinator(
        in_memory_uow, thinking_agent=SimulatedAgent(), trusted_managed_root=tmp_path
    )
    result = coordinator._run_thinking_agent(
        project, worktree, config.agent_profiles["thinking"], 5
    )
    coordinator._validate_candidate(
        worktree,
        incoming,
        ("request.md",),
        package,
        allowed_paths={skill.relative_to(worktree).as_posix()},
    )

    assert result.exit_code == 0
    checkpoint = in_memory_uow.projects.get_by_id(config.project_id).onboarding_checkpoint
    assert checkpoint["thinking_agent_attempt"]["status"] == "SUCCEEDED"
    assert checkpoint["thinking_agent_attempt"]["exit_code"] == 0


def test_blocked_bootstrap_without_agent_attempt_is_safe_pre_dispatch(
    in_memory_uow, tmp_path: Path, monkeypatch
):
    config = _configuration()
    project = Project(
        project_id=config.project_id,
        display_name=config.display_name,
        repository=config.repository,
        project_type=ProjectType.GREENFIELD,
        base_branch="main",
        provider_connections={
            key: value.model_dump(mode="json")
            for key, value in config.provider_connections.items()
        },
        agent_profiles={key: value.model_dump() for key, value in config.agent_profiles.items()},
        onboarding_status=ProjectOnboardingStatus.BLOCKED,
        onboarding_checkpoint={"source_zip_sha256": "a" * 64},
    )
    in_memory_uow.projects.save(project)
    managed_root = tmp_path / "managed" / config.project_id
    managed_root.mkdir(parents=True)
    subprocess.run(["git", "init"], cwd=managed_root, check=True, capture_output=True)
    monkeypatch.setattr(
        ProjectService,
        "verified_managed_workspace_root",
        lambda self, project_id: str(managed_root) if project_id == config.project_id else None,
    )

    class ReadOnlyAdapter:
        def get_remote_branch_head(self, repository, branch):
            if branch == "main":
                return SimpleNamespace(
                    outcome=ExternalOutcome.SUCCESS,
                    reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
                    data="b" * 40,
                )
            return SimpleNamespace(
                outcome=ExternalOutcome.FAILURE,
                reason_code=ExternalReasonCode.NOT_FOUND,
                data=None,
            )

        def get_pull_request(self, repository, branch, base_branch):
            return SimpleNamespace(
                outcome=ExternalOutcome.FAILURE,
                reason_code=ExternalReasonCode.NOT_FOUND,
                data=None,
            )

    class Connections:
        def require_git_pr_write(self, project):
            return ReadOnlyAdapter()

    coordinator = GreenfieldBootstrapCoordinator(
        in_memory_uow,
        connection_service=Connections(),
        trusted_managed_root=tmp_path / "managed",
    )
    report = coordinator.reconcile_blocked_bootstrap(config.project_id)

    assert report["safe_to_resume"] is True
    assert report["reason"] == "NO_REMOTE_EFFECT_OBSERVED_PRE_DISPATCH"
    assert "thinking_agent_attempt" not in in_memory_uow.projects.get_by_id(
        config.project_id
    ).onboarding_checkpoint


def test_candidate_validation_allows_documentary_contradictions_with_provenance(tmp_path: Path):
    worktree = tmp_path / "worktree"
    incoming = worktree / "context" / "incoming" / "sha"
    incoming.mkdir(parents=True)
    (incoming / "facts.md").write_text("old decision", encoding="utf-8")
    (incoming / "new-facts.md").write_text("conflicting proposal", encoding="utf-8")
    (worktree / "AGENTS.md").write_text("See context/INDEX.md", encoding="utf-8")
    (worktree / "openspec").mkdir()
    (worktree / "openspec" / "config.yaml").write_text(
        "context: context/INDEX.md\n", encoding="utf-8"
    )
    (worktree / "context" / "INDEX.md").write_text(
        "# Context\n\n- facts.md: old decision\n- new-facts.md: conflicting proposal\n"
        "\n## Contradictions\nBoth sources remain authoritative for review.\n",
        encoding="utf-8",
    )
    _initialize_test_repository(worktree)

    GreenfieldBootstrapCoordinator._validate_candidate(
        worktree, incoming, ("facts.md", "new-facts.md"), worktree / "context" / "incoming" / "sha"
    )


def test_incremental_context_delta_preserves_approved_context_and_marks_replacements(tmp_path: Path):
    worktree = tmp_path / "worktree"
    package = tmp_path / "package"
    (worktree / "context").mkdir(parents=True)
    package.mkdir()
    (worktree / "context" / "existing.md").write_text("approved", encoding="utf-8")
    (package / "existing.md").write_text("proposed replacement", encoding="utf-8")
    (package / "new.md").write_text("addition", encoding="utf-8")

    delta = GreenfieldBootstrapCoordinator._context_delta(
        worktree, ("existing.md", "new.md"), package
    )

    assert delta == {
        "additions": ["new.md"],
        "replacement_candidates": ["existing.md"],
    }
    assert (worktree / "context" / "existing.md").read_text(encoding="utf-8") == "approved"


def test_incremental_authorization_is_bound_to_project_base_zip_and_profile(in_memory_uow):
    project = Project(
        project_id="prepared",
        display_name="Prepared",
        repository="example/prepared",
        project_type=ProjectType.GREENFIELD,
        base_branch="main",
        onboarding_status=ProjectOnboardingStatus.PREPARED,
        onboarding_checkpoint={"approved_context_sha": "m" * 40},
    )
    authorization = {
        "authorization_reference": "operator-instruction-f2-incremental-20261024-1",
        "project_id": "prepared",
        "repository": "example/prepared",
        "base_branch": "main",
        "base_sha": "m" * 40,
        "source_zip_sha256": "z" * 64,
        "agent": "codex",
        "model": "gpt-5.6-luna",
        "effort": "medium",
        "max_new_invocations": 1,
        "single_use": True,
        "purpose": "INCREMENTAL_CONTEXT_E2E",
    }

    GreenfieldBootstrapCoordinator._validate_incremental_authorization(
        project, authorization, "z" * 64
    )
    invalid = {**authorization, "source_zip_sha256": "x" * 64}
    with pytest.raises(GreenfieldBootstrapError, match="ZIP_MISMATCH"):
        GreenfieldBootstrapCoordinator._validate_incremental_authorization(
            project, invalid, "z" * 64
        )


def test_incremental_retry_reconciles_existing_pr_before_agent(in_memory_uow, tmp_path):
    project = Project(
        project_id="prepared",
        display_name="Prepared",
        repository="example/prepared",
        project_type=ProjectType.BROWNFIELD,
        base_branch="main",
        provider_connections={
            "git_pr": {
                "provider_id": "github",
                "repository_url": "example/prepared",
                "auth_mode": "environment_app",
            }
        },
        onboarding_status=ProjectOnboardingStatus.PREPARED,
    )
    in_memory_uow.projects.save(project)
    coordinator = GreenfieldBootstrapCoordinator(
        in_memory_uow, trusted_managed_root=tmp_path / "managed"
    )

    class Adapter:
        def get_pull_request(self, repository, branch, base):
            assert (repository, branch, base) == (
                "example/prepared",
                "minime/context/prepared-abc123",
                "main",
            )
            return SimpleNamespace(
                outcome=ExternalOutcome.SUCCESS,
                data={
                    "number": 7,
                    "url": "https://github.com/example/prepared/pull/7",
                    "head_sha": "candidate-sha",
                },
            )

    result = coordinator._reconcile_incremental_pr(
        project,
        Adapter(),
        "minime/context/prepared-abc123",
        "base-sha",
        "a" * 64,
    )

    assert result["reused"] is True
    assert in_memory_uow.projects.get_by_id("prepared").onboarding_checkpoint[
        "pending_context"
    ]["head_sha"] == "candidate-sha"


@pytest.mark.parametrize("exit_code,timed_out", [(1, False), (-1, True)])
def test_real_agent_failure_is_persisted_before_cleanup_and_never_auto_retried(
    in_memory_uow, tmp_path: Path, exit_code: int, timed_out: bool
):
    config = _configuration()
    project = Project(
        project_id=config.project_id,
        display_name=config.display_name,
        repository=config.repository,
        project_type=ProjectType.GREENFIELD,
        base_branch="main",
        onboarding_checkpoint={"source_zip_sha256": "a" * 64},
    )
    in_memory_uow.projects.save(project)

    class FailingThinkingAgent:
        calls = 0

        async def run(self, worktree, instruction, timeout_seconds):
            self.calls += 1
            assert worktree == tmp_path
            assert "source" in instruction
            assert timeout_seconds == 15
            return ImplementerResult(
                exit_code=exit_code,
                timed_out=timed_out,
                stdout=["diagnostic event"],
                stderr=["confined CLI failed before producing context"],
                duration_ms=123,
            )

    agent = FailingThinkingAgent()
    coordinator = GreenfieldBootstrapCoordinator(
        in_memory_uow, thinking_agent=agent, trusted_managed_root=tmp_path / "managed"
    )
    with pytest.raises(GreenfieldBootstrapError, match="Thinking agent did not complete"):
        coordinator._run_thinking_agent(project, tmp_path, config.agent_profiles["thinking"], 15)
    checkpoint = in_memory_uow.projects.get_by_id(project.project_id).onboarding_checkpoint
    assert checkpoint["source_zip_sha256"] == "a" * 64
    evidence = checkpoint["thinking_agent_attempt"]
    assert evidence["status"] == "FAILED_USAGE_UNKNOWN"
    assert evidence["usage_status"] == "UNKNOWN"
    assert evidence["exit_code"] == exit_code
    assert evidence["timed_out"] is timed_out
    assert evidence["duration_ms"] == 123
    assert evidence["stderr_tail"] == ["confined CLI failed before producing context"]
    assert evidence["stdout_line_count"] == 1
    assert agent.calls == 1

    coordinator._block(project, "GREENFIELD_BOOTSTRAP_FAILED:GreenfieldBootstrapError")
    latest = in_memory_uow.projects.get_by_id(project.project_id)
    assert latest.onboarding_status is ProjectOnboardingStatus.BLOCKED
    assert latest.onboarding_checkpoint["thinking_agent_attempt"] == evidence
    public = ProjectService.public_onboarding_state(latest)["checkpoint"]["thinking_agent_attempt"]
    assert public["status"] == "FAILED_USAGE_UNKNOWN"
    assert public["exit_code"] == exit_code
    assert "stderr_tail" not in public
    listed = ProjectService.public_project_payload(latest)
    assert "stderr_tail" not in listed["onboarding_checkpoint"]["thinking_agent_attempt"]
    with pytest.raises(GreenfieldBootstrapError, match="without a safely resumable"):
        coordinator.bootstrap(config, b"same-package-do-not-replay")
    assert agent.calls == 1


def test_thinking_agent_uncaught_exception_retains_unknown_attempt(in_memory_uow, tmp_path):
    config = _configuration()
    project = Project(
        project_id=config.project_id,
        display_name=config.display_name,
        repository=config.repository,
        project_type=ProjectType.GREENFIELD,
        base_branch="main",
    )
    in_memory_uow.projects.save(project)

    class CrashedAgent:
        async def run(self, worktree, instruction, timeout_seconds):
            raise RuntimeError("agent process disappeared")

    coordinator = GreenfieldBootstrapCoordinator(in_memory_uow, thinking_agent=CrashedAgent())
    with pytest.raises(RuntimeError, match="process disappeared"):
        coordinator._run_thinking_agent(project, tmp_path, config.agent_profiles["thinking"], 5)
    attempt = in_memory_uow.projects.get_by_id(project.project_id).onboarding_checkpoint[
        "thinking_agent_attempt"
    ]
    assert attempt["status"] == "EXECUTION_UNKNOWN"
    assert attempt["usage_status"] == "UNKNOWN"


def test_blocked_bootstrap_reconciliation_preserves_unknown_attempt_and_refuses_replay(
    in_memory_uow, tmp_path: Path
):
    config = _configuration()
    project = Project(
        project_id=config.project_id,
        display_name=config.display_name,
        repository=config.repository,
        project_type=ProjectType.GREENFIELD,
        base_branch="main",
        provider_connections={
            key: value.model_dump(mode="json")
            for key, value in config.provider_connections.items()
        },
        agent_profiles={
            key: value.model_dump(mode="json")
            for key, value in config.agent_profiles.items()
        },
        onboarding_status=ProjectOnboardingStatus.BLOCKED,
        onboarding_checkpoint={
            "source_zip_sha256": "a" * 64,
            "thinking_agent_attempt": {
                "status": "FAILED_USAGE_UNKNOWN",
                "usage_status": "UNKNOWN",
            },
        },
    )
    in_memory_uow.projects.save(project)

    class ReadOnlyAdapter:
        def get_remote_branch_head(self, repository, branch):
            if branch == "main":
                return SimpleNamespace(
                    outcome=ExternalOutcome.SUCCESS,
                    reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
                    data="b" * 40,
                )
            return SimpleNamespace(
                outcome=ExternalOutcome.FAILURE,
                reason_code=ExternalReasonCode.NOT_FOUND,
                data=None,
            )

        def get_pull_request(self, repository, branch, base_branch):
            return SimpleNamespace(
                outcome=ExternalOutcome.FAILURE,
                reason_code=ExternalReasonCode.NOT_FOUND,
                data=None,
            )

    class Connections:
        def require_git_pr_write(self, project):
            return ReadOnlyAdapter()

    coordinator = GreenfieldBootstrapCoordinator(
        in_memory_uow,
        connection_service=Connections(),
        trusted_managed_root=tmp_path / "managed",
    )
    report = coordinator.reconcile_blocked_bootstrap(config.project_id)

    assert report["safe_to_resume"] is False
    assert report["reason"] == "THINKING_AGENT_CONSUMPTION_UNKNOWN"
    saved = in_memory_uow.projects.get_by_id(config.project_id)
    assert saved.onboarding_status is ProjectOnboardingStatus.BLOCKED
    assert saved.onboarding_checkpoint["thinking_agent_attempt"]["status"] == (
        "FAILED_USAGE_UNKNOWN"
    )
    assert saved.onboarding_checkpoint["bootstrap_recovery"]["reason"] == (
        "THINKING_AGENT_CONSUMPTION_UNKNOWN"
    )
    with pytest.raises(
        GreenfieldBootstrapError,
        match="THINKING_AGENT_RETRY_REQUIRES_EXPLICIT_AUTHORIZATION",
    ):
        coordinator.resume_blocked_bootstrap(config.project_id, b"not-a-zip")


def test_explicit_retry_authorization_allows_only_reconciled_unknown_attempt(
    in_memory_uow, tmp_path: Path
):
    config = _configuration()
    base_sha = "b" * 40
    project = Project(
        project_id=config.project_id,
        display_name=config.display_name,
        repository=config.repository,
        project_type=ProjectType.GREENFIELD,
        base_branch="main",
        provider_connections={
            key: value.model_dump(mode="json")
            for key, value in config.provider_connections.items()
        },
        onboarding_status=ProjectOnboardingStatus.BLOCKED,
        onboarding_checkpoint={"source_zip_sha256": "a" * 64},
    )
    in_memory_uow.projects.save(project)

    class ReadOnlyAdapter:
        @staticmethod
        def _not_found():
            return SimpleNamespace(
                outcome=ExternalOutcome.FAILURE,
                reason_code=ExternalReasonCode.NOT_FOUND,
                data=None,
            )

        def get_remote_branch_head(self, repository, branch):
            if branch == "main":
                return SimpleNamespace(
                    outcome=ExternalOutcome.SUCCESS,
                    reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
                    data=base_sha,
                )
            return self._not_found()

        def get_pull_request(self, repository, branch, base_branch):
            return self._not_found()

    class Connections:
        def require_git_pr_write(self, project):
            return ReadOnlyAdapter()

    coordinator = GreenfieldBootstrapCoordinator(
        in_memory_uow,
        connection_service=Connections(),
        trusted_managed_root=tmp_path / "managed",
    )
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    coordinator.projects.verified_managed_workspace_root = lambda project_id: tmp_path
    authorization = {
        "authorization_reference": "github-comment:6372352972",
        "project_id": config.project_id,
        "source_zip_sha256": "a" * 64,
        "repository": config.repository,
        "base_branch": "main",
        "base_sha": base_sha,
        "purpose": "PRIOR_USAGE_UNRECOVERABLE",
        "max_new_invocations": 1,
        "single_use": True,
    }

    report = coordinator.reconcile_blocked_bootstrap(config.project_id, authorization)

    assert report["safe_to_resume"] is True
    assert report["reason"] == "NO_REMOTE_EFFECT_OBSERVED_EXPLICIT_AUTHORIZATION_REQUIRED"
    assert in_memory_uow.projects.get_by_id(config.project_id).onboarding_status is (
        ProjectOnboardingStatus.BLOCKED
    )


def test_new_explicit_grant_replaces_used_prior_grant_without_erasing_history(
    in_memory_uow, tmp_path: Path
):
    config = _configuration()
    base_sha = "b" * 40
    project = Project(
        project_id=config.project_id,
        display_name=config.display_name,
        repository=config.repository,
        project_type=ProjectType.GREENFIELD,
        base_branch="main",
        provider_connections={
            key: value.model_dump(mode="json")
            for key, value in config.provider_connections.items()
        },
        onboarding_status=ProjectOnboardingStatus.BLOCKED,
        onboarding_checkpoint={
            "source_zip_sha256": "a" * 64,
            "thinking_agent_attempt": {
                "status": "FAILED_USAGE_UNKNOWN",
                "usage_status": "UNKNOWN",
            },
            "thinking_agent_retry_authorization": {
                "authorization_reference": "github-comment:6372352972",
                "used": True,
            },
            "bootstrap_recovery": {"safe_to_resume": False},
        },
    )
    in_memory_uow.projects.save(project)

    class ReadOnlyAdapter:
        @staticmethod
        def _not_found():
            return SimpleNamespace(
                outcome=ExternalOutcome.FAILURE,
                reason_code=ExternalReasonCode.NOT_FOUND,
                data=None,
            )

        def get_remote_branch_head(self, repository, branch):
            if branch == "main":
                return SimpleNamespace(
                    outcome=ExternalOutcome.SUCCESS,
                    reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
                    data=base_sha,
                )
            return self._not_found()

        def get_pull_request(self, repository, branch, base_branch):
            return self._not_found()

    class Connections:
        def require_git_pr_write(self, project):
            return ReadOnlyAdapter()

    coordinator = GreenfieldBootstrapCoordinator(
        in_memory_uow,
        connection_service=Connections(),
        trusted_managed_root=tmp_path / "managed",
    )
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    coordinator.projects.verified_managed_workspace_root = lambda project_id: tmp_path
    authorization = {
        "authorization_reference": "github-comment:6373419891",
        "project_id": config.project_id,
        "source_zip_sha256": "a" * 64,
        "repository": config.repository,
        "base_branch": "main",
        "base_sha": base_sha,
        "purpose": "PRIOR_USAGE_UNRECOVERABLE",
        "max_new_invocations": 1,
        "single_use": True,
    }

    report = coordinator.reconcile_blocked_bootstrap(config.project_id, authorization)

    assert report["safe_to_resume"] is True
    assert report["reason"] == "NO_REMOTE_EFFECT_OBSERVED_EXPLICIT_AUTHORIZATION_REQUIRED"
    saved = in_memory_uow.projects.get_by_id(config.project_id)
    assert saved.onboarding_checkpoint["thinking_agent_retry_authorization"]["used"] is True
    assert saved.onboarding_checkpoint["thinking_agent_attempt"]["usage_status"] == "UNKNOWN"


def test_stale_local_bootstrap_branch_is_reconciled_only_at_exact_base(tmp_path: Path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "README.md").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "README.md"], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "-c", "user.email=e2e@example.invalid", "-c", "user.name=e2e", "commit", "-qm", "base"],
        check=True,
    )
    base_sha = subprocess.check_output(
        ["git", "-C", str(tmp_path), "rev-parse", "HEAD"], text=True
    ).strip()
    branch = "minime/bootstrap/recovery"
    subprocess.run(["git", "-C", str(tmp_path), "branch", branch, base_sha], check=True)

    GreenfieldBootstrapCoordinator._prepare_local_branch(str(tmp_path), branch, base_sha)

    assert subprocess.run(
        ["git", "-C", str(tmp_path), "show-ref", "--verify", f"refs/heads/{branch}"],
        capture_output=True,
        check=False,
    ).returncode != 0


def test_pre_dispatch_recovery_reconciles_unbound_divergent_local_branch(tmp_path: Path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "README.md").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "README.md"], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "-c", "user.email=e2e@example.invalid", "-c", "user.name=e2e", "commit", "-qm", "base"],
        check=True,
    )
    base_sha = subprocess.check_output(
        ["git", "-C", str(tmp_path), "rev-parse", "HEAD"], text=True
    ).strip()
    branch = "minime/bootstrap/recovery"
    (tmp_path / "extra.txt").write_text("stale\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "extra.txt"], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "-c", "user.email=e2e@example.invalid", "-c", "user.name=e2e", "commit", "-qm", "stale"],
        check=True,
    )
    subprocess.run(["git", "-C", str(tmp_path), "branch", branch], check=True)

    GreenfieldBootstrapCoordinator._prepare_local_branch(
        str(tmp_path), branch, base_sha, allow_pre_dispatch_reconcile=True
    )

    assert subprocess.run(
        ["git", "-C", str(tmp_path), "show-ref", "--verify", f"refs/heads/{branch}"],
        capture_output=True,
        check=False,
    ).returncode != 0


def test_candidate_scope_rejects_staged_unrelated_file_not_just_untracked(tmp_path: Path):
    worktree = tmp_path / "repo"
    worktree.mkdir()
    subprocess.run(["git", "init"], cwd=worktree, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=worktree, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=worktree, check=True)
    (worktree / "README.md").write_text("baseline", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=worktree, check=True)
    subprocess.run(
        ["git", "commit", "-m", "base"], cwd=worktree, check=True, capture_output=True
    )
    (worktree / "ROADMAP.md").write_text("out of scope", encoding="utf-8")
    subprocess.run(["git", "add", "ROADMAP.md"], cwd=worktree, check=True)
    with pytest.raises(GreenfieldBootstrapError, match="count=1"):
        GreenfieldBootstrapCoordinator._validate_candidate_scope(worktree)


def test_candidate_scope_fails_closed_when_git_inventory_unavailable(tmp_path: Path):
    with pytest.raises(GreenfieldBootstrapError, match="scope could not be inspected"):
        GreenfieldBootstrapCoordinator._validate_candidate_scope(tmp_path)


def test_failed_post_agent_candidate_is_quarantined_and_not_replayed(
    in_memory_uow, tmp_path: Path
):
    managed = tmp_path / "managed"
    worktree = managed / "project" / ".minime" / "worktrees" / "candidate"
    worktree.mkdir(parents=True)
    (worktree / "context.md").write_text("private candidate", encoding="utf-8")
    project = Project(
        project_id="project",
        display_name="Project",
        repository="example/project",
        project_type=ProjectType.GREENFIELD,
        base_branch="main",
        onboarding_status=ProjectOnboardingStatus.BLOCKED,
        onboarding_checkpoint={"source_zip_sha256": "a" * 64},
    )
    in_memory_uow.projects.save(project)
    coordinator = GreenfieldBootstrapCoordinator(
        in_memory_uow, trusted_managed_root=managed
    )
    coordinator._retain_candidate_for_recovery(
        project, worktree, "minime/bootstrap/project-aaaaaaaaaaaa",
        "b" * 40, GreenfieldBootstrapError("candidate has out-of-scope paths")
    )
    assert worktree.is_dir()
    assert (worktree / "context.md").read_text(encoding="utf-8") == "private candidate"
    latest = in_memory_uow.projects.get_by_id("project")
    recovery = latest.onboarding_checkpoint["candidate_recovery"]
    assert recovery["status"] == "QUARANTINED_REVIEW_REQUIRED"
    assert recovery["worktree"] == str(worktree)
    assert "candidate_recovery" not in ProjectService.public_project_payload(
        latest
    )["onboarding_checkpoint"]
    report = coordinator.reconcile_blocked_bootstrap("project")
    assert report["safe_to_resume"] is False
    assert report["reason"] == "CANDIDATE_QUARANTINED_REVIEW_REQUIRED"


def test_quarantined_candidate_is_recovered_without_agent_replay(in_memory_uow, tmp_path: Path):
    config = _configuration()
    source_zip = io.BytesIO()
    with zipfile.ZipFile(source_zip, "w") as archive:
        archive.writestr("request.md", "Given a source\n")
    payload = source_zip.getvalue()
    source_sha = __import__("hashlib").sha256(payload).hexdigest()
    branch = "minime/bootstrap/greenfield-" + source_sha[:12]
    managed = tmp_path / "managed" / config.project_id
    worktree = managed / ".minime" / "worktrees" / branch.replace("/", "-")
    worktree.mkdir(parents=True)
    incoming = worktree / "context" / "incoming" / source_sha
    incoming.mkdir(parents=True)
    (incoming / "request.md").write_text("Given a source\n", encoding="utf-8")
    (worktree / "AGENTS.md").write_text(
        "Use context/INDEX.md as the canonical context.\n", encoding="utf-8"
    )
    (worktree / "openspec").mkdir()
    (worktree / "openspec" / "config.yaml").write_text(
        "context: context/INDEX.md\n", encoding="utf-8"
    )
    (worktree / "context" / "INDEX.md").write_text(
        "# Context\n\n- [Request](01-producto/request.md)\n", encoding="utf-8"
    )
    (worktree / "context" / "01-producto").mkdir()
    (worktree / "context" / "01-producto" / "request.md").write_text(
        "Source-backed request.\n", encoding="utf-8"
    )
    (worktree / ".agents" / "skills" / "minime-engineering-discipline").mkdir(
        parents=True
    )
    (worktree / ".agents" / "skills" / "minime-engineering-discipline" / "SKILL.md").write_text(
        "Installed capability.\n", encoding="utf-8"
    )
    (worktree / ".agents" / "skills" / "openspec-propose").mkdir(parents=True)
    (worktree / ".agents" / "skills" / "openspec-propose" / "SKILL.md").write_text(
        "Official skill.\n", encoding="utf-8"
    )
    (worktree / ".agents" / "workflows").mkdir(parents=True)
    (worktree / ".agents" / "workflows" / "opsx-propose.md").write_text(
        "Official workflow.\n", encoding="utf-8"
    )
    _initialize_test_repository(worktree)
    (worktree / ".agents" / "skills" / "minime-engineering-discipline" / "SKILL.md").write_text(
        "Installed capability updated by recovery.\n", encoding="utf-8"
    )
    subprocess.run(["git", "-C", str(worktree), "branch", branch], check=True)
    subprocess.run(["git", "-C", str(worktree), "checkout", "--detach", "-q"], check=True)

    project = Project(
        project_id=config.project_id,
        display_name=config.display_name,
        repository=config.repository,
        project_type=ProjectType.GREENFIELD,
        base_branch="main",
        provider_connections={
            key: value.model_dump(mode="json")
            for key, value in config.provider_connections.items()
        },
        agent_profiles={key: value.model_dump() for key, value in config.agent_profiles.items()},
        execution_policy=config.execution_policy.model_dump(),
        onboarding_status=ProjectOnboardingStatus.BLOCKED,
        onboarding_checkpoint={
            "source_zip_sha256": source_sha,
            "candidate_recovery": {
                "status": "QUARANTINED_REVIEW_REQUIRED",
                "worktree": str(worktree),
                "branch": branch,
                "base_sha": subprocess.check_output(
                    ["git", "-C", str(worktree), "rev-parse", "HEAD"], text=True
                ).strip(),
            },
            "thinking_agent_attempt": {
                "status": "SUCCEEDED",
                "usage_status": "OBSERVED",
                "agent": "codex",
                "model": "gpt-5.6-luna",
                "exit_code": 0,
                "duration_ms": 7,
            },
        },
    )
    in_memory_uow.projects.save(project)
    in_memory_uow.project_managed_repository_bindings.save(
        ProjectManagedRepositoryBinding(
            project_id=project.project_id,
            canonical_repository_identity=project.repository,
            managed_repository_root=str(managed),
            worktree_parent_dir=str(managed / ".minime" / "worktrees"),
        )
    )

    class Adapter:
        def get_repository_branch_head(self, *_args):
            return SimpleNamespace(outcome=ExternalOutcome.FAILURE, reason_code=ExternalReasonCode.NOT_FOUND)

        def get_pull_request(self, *_args):
            return SimpleNamespace(outcome=ExternalOutcome.FAILURE, reason_code=ExternalReasonCode.NOT_FOUND)

        def push_branch(self, _worktree, _remote, _branch, head_sha):
            return ExternalActionResult(
                outcome=ExternalOutcome.SUCCESS,
                source_adapter="test",
                reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
                data=head_sha,
            )

    class Connections:
        def require_git_pr_write(self, _project):
            return Adapter()

        def create_pull_request(self, *_args, **_kwargs):
            return ExternalActionResult(
                outcome=ExternalOutcome.SUCCESS,
                source_adapter="test",
                reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
                data={"number": 9, "url": "https://example.invalid/pull/9"},
            )

    class Manifest:
        def install_greenfield(self, *_args, **_kwargs):
            return {"files": [{"path": ".agents/skills/minime-engineering-discipline/SKILL.md"}]}

        def validate_f5_readiness(self, *_args, **_kwargs):
            return {"status": "READY_FOR_F5_VALIDATION"}

    class OpenSpec:
        def inspect_integrations(self, *_args):
            return {"integrations": {"codex": ["propose"], "antigravity": ["propose"]}}

        def validate_workspace(self, _worktree):
            return {"status": "PASS"}

    coordinator = GreenfieldBootstrapCoordinator(
        in_memory_uow,
        connection_service=Connections(),
        openspec=OpenSpec(),
        capability_manifest=Manifest(),
        trusted_managed_root=tmp_path / "managed",
    )
    result = coordinator.recover_quarantined_candidate(project.project_id, payload)

    assert result["onboarding_status"] == ProjectOnboardingStatus.PR_PENDING.value
    saved = in_memory_uow.projects.get_by_id(project.project_id)
    assert saved.onboarding_checkpoint["pull_request_number"] == 9
    assert saved.onboarding_checkpoint["thinking_agent_attempt"]["usage_status"] == "OBSERVED"
    assert saved.onboarding_checkpoint["candidate_recovery"]["status"] == "QUARANTINED_REVIEW_REQUIRED"
