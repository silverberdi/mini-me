import subprocess
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from minime.domain.enums import ExternalOutcome, ProjectOnboardingStatus, ProjectType
from minime.domain.models import (
    Project,
    ProjectAgentProfile,
    ProjectConfigurationInput,
    ProjectExecutionPolicy,
    ProjectProviderConnection,
)
from minime.services.context_archive import UnsafeContextArchive
from minime.services.greenfield_bootstrap import (
    GreenfieldBootstrapCoordinator,
    GreenfieldBootstrapError,
)
from minime.services.implementer_runner import ImplementerResult
from minime.services.project_service import ProjectService


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
        "context: context/INDEX.md\n", encoding="utf-8"
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
