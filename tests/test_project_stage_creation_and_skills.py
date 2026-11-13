"""Tests for multi-stage project creation, GitHub grants validation, and canonical skills provisioning (Ref #355)."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from minime.adapters.github import GitHubAdapter
from minime.domain.enums import ExternalOutcome, ExternalReasonCode, ProjectStatus, ProjectType, RetrySafety
from minime.domain.models import ExternalActionResult, ProjectAgentProfile, ProjectConfigurationInput
from minime.services.canonical_capabilities import provision_canonical_capabilities, verify_workflow_readiness
from minime.services.project_service import ProjectService


def _test_configuration(repo="owner/my-project"):
    return ProjectConfigurationInput.model_validate(
        {
            "project_id": "test-stage-proj",
            "display_name": "Test Stage Project",
            "project_type": ProjectType.BROWNFIELD,
            "repository": f"https://github.com/{repo}",
            "base_branch": "main",
            "provider_connections": {
                "tickets": {
                    "provider_id": "github",
                    "repository_url": f"https://github.com/{repo}",
                    "auth_mode": "environment_app",
                },
                "git_pr": {
                    "provider_id": "github",
                    "repository_url": f"https://github.com/{repo}",
                    "auth_mode": "environment_app",
                },
            },
            "agent_profiles": {
                name: ProjectAgentProfile(
                    agent_id="antigravity" if name == "independent_review" else "codex",
                    model_id="gpt-5.6-luna",
                    effort="medium",
                ).model_dump()
                for name in ("thinking", "execution", "independent_review", "fallback")
            },
            "execution_policy": {
                "max_review_rounds": 2,
                "max_correction_attempts": 1,
                "code_review_policy": "risk_based",
            },
        }
    )


def test_validate_repository_grants_success():
    adapter = GitHubAdapter()
    adapter.verify_connection_permissions = MagicMock(
        side_effect=lambda repo, resp: ExternalActionResult(
            outcome=ExternalOutcome.SUCCESS,
            source_adapter="github_rest",
            reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
            retry_safety=RetrySafety.SAFE,
            data={"repository": repo, "permissions": {"issues": "read", "contents": "write"}},
        )
    )
    result = adapter.validate_repository_grants("owner/repo")
    assert result.outcome == ExternalOutcome.SUCCESS
    assert result.data["repository"] == "owner/repo"
    assert "permissions" in result.data


def test_validate_repository_grants_fails_closed_with_guidance_on_not_found():
    adapter = GitHubAdapter()
    adapter.verify_connection_permissions = MagicMock(
        return_value=ExternalActionResult(
            outcome=ExternalOutcome.FAILURE,
            source_adapter="github_rest",
            reason_code=ExternalReasonCode.NOT_FOUND,
            retry_safety=RetrySafety.SAFE,
            error_message="Repository not found or inaccessible.",
        )
    )
    result = adapter.validate_repository_grants("owner/inaccessible-repo")
    assert result.outcome == ExternalOutcome.FAILURE
    assert "GitHub App no tiene acceso al repositorio" in result.error_message
    assert "All repositories" in result.error_message


def test_create_configured_project_defaults_to_paused_and_effective_pause(in_memory_uow):
    service = ProjectService(in_memory_uow)
    config = _test_configuration()
    project = service.create_configured_project(config)

    assert project.status == ProjectStatus.PAUSED
    assert project.execution_policy.get("effective_pause") is True


def test_create_configured_project_fails_closed_when_grants_invalid(in_memory_uow, monkeypatch):
    service = ProjectService(in_memory_uow)
    config = _test_configuration("unauthorized/repo")

    mock_adapter = MagicMock()
    mock_adapter.validate_repository_grants.return_value = ExternalActionResult(
        outcome=ExternalOutcome.FAILURE,
        source_adapter="github_rest",
        reason_code=ExternalReasonCode.AUTH_REQUIRED,
        retry_safety=RetrySafety.SAFE,
        error_message="GitHub App lacks required permissions for tickets: issues",
    )

    monkeypatch.setattr(
        "minime.services.project_connection_service.ProjectConnectionService.adapter_for",
        lambda self, proj, resp: mock_adapter,
    )

    with pytest.raises(ValueError, match="lacks required permissions"):
        service.create_configured_project(config, validate_grants=True)


def test_provision_canonical_capabilities_and_readiness(tmp_path):
    manifest = provision_canonical_capabilities(tmp_path)
    assert manifest["skills_count"] > 0
    assert manifest["workflows_count"] > 0

    assert (tmp_path / ".agents" / "skills" / "minime-request-normalizer" / "SKILL.md").is_file()
    assert (tmp_path / ".agents" / "skills" / "minime-pr-preparer" / "SKILL.md").is_file()
    assert (tmp_path / ".agents" / "skills" / "openspec-propose" / "SKILL.md").is_file()
    assert (tmp_path / ".agent" / "workflows" / "opsx-propose.md").is_file()

    is_ready, missing = verify_workflow_readiness(tmp_path, {})
    assert is_ready is True
    assert missing == []


def test_verify_workflow_readiness_fails_closed_on_empty_dir(tmp_path):
    is_ready, missing = verify_workflow_readiness(tmp_path, {})
    assert is_ready is False
    assert len(missing) > 0
