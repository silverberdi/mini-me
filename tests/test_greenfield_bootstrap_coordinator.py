from decimal import Decimal
from pathlib import Path

import pytest

from minime.domain.enums import ProjectType
from minime.domain.models import (
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
    worktree = incoming.parents[3]
    (worktree / "AGENTS.md").write_text("See context/incoming/sha/facts.md", encoding="utf-8")
    (worktree / "openspec").mkdir()
    (worktree / "openspec" / "config.yaml").write_text(
        "context: context/incoming/sha/facts.md\n", encoding="utf-8"
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
