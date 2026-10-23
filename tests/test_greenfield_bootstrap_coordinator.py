from decimal import Decimal

import pytest

from minime.domain.enums import ProjectType
from minime.domain.models import (
    ProjectAgentProfile,
    ProjectConfigurationInput,
    ProjectExecutionPolicy,
    ProjectProviderConnection,
)
from minime.services.context_archive import UnsafeContextArchive
from minime.services.greenfield_bootstrap import GreenfieldBootstrapCoordinator


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
