from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from tests.conftest import InMemoryPersistenceUnitOfWork, setup_managed_repository_fixture

from minime.services.agent_runner import (
    CapacityExhaustedError,
    CliAgentRunner,
    NativeOpenSpecWorkflowUnavailable,
)
from minime.services.worktree_manager import WorktreeInfo, WorktreeManager


def test_slugify_request_and_branch_formatting():
    title = "Refactor Authentication & Session Management (v2.0)!"
    slug = WorktreeManager.slugify_request_title(title)
    assert slug == "refactor-authentication-session-manageme"

    branch = WorktreeManager.format_request_branch_name(171, title)
    assert branch == "request-171-refactor-authentication-session-manageme"

    doc_branch = WorktreeManager.format_documentation_branch_name(171, title)
    assert doc_branch == "doc-close-171-refactor-authentication-session-manageme"


@pytest.mark.asyncio
async def test_worktree_manager_create_request_worktree(tmp_path: Path):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    managed_root = tmp_path / "worktrees"
    managed_root.mkdir()

    uow = InMemoryPersistenceUnitOfWork()
    setup_managed_repository_fixture(
        uow,
        "proj-1",
        repo_dir,
        managed_root,
        canonical_repository_identity="github.com/org/proj-1",
    )

    manager = WorktreeManager(repo_dir, uow=uow)
    manager._git = MagicMock()
    async def async_git(args, project_id=None):
        return "commit123"
    manager._git.side_effect = async_git

    info = await manager.create_request_worktree(
        project_id="proj-1",
        issue_number=171,
        issue_title="Add OpenSpec Orchestration",
        base_branch="main",
    )

    assert isinstance(info, WorktreeInfo)
    assert info.branch_name == "request-171-add-openspec-orchestration"
    assert str(info.path).startswith(str(managed_root))
    assert info.base_sha == "commit123"


def test_agent_runner_dynamic_workflow_resolution_codex(tmp_path: Path):
    # Setup test workspace with .agents/skills/openspec-verify-change/SKILL.md
    skill_dir = tmp_path / ".agents" / "skills" / "openspec-verify-change"
    skill_dir.mkdir(parents=True)
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text("# Verify Skill")

    runner = CliAgentRunner()
    resolved = runner.resolve_workflow(
        worktree_path=tmp_path,
        provider="codex",
        operation="verify",
        change_name="gacela-03-openspec-y-revision",
    )
    assert resolved.workflow_path == ".agents/skills/openspec-verify-change/SKILL.md"
    assert resolved.provider == "codex"
    assert resolved.operation == "verify"
    assert resolved.dispatch_command == "$openspec-verify-change gacela-03-openspec-y-revision"


def test_agent_runner_dynamic_workflow_resolution_antigravity(tmp_path: Path):
    # Setup test workspace with .agent/workflows/opsx-verify.md
    wf_dir = tmp_path / ".agent" / "workflows"
    wf_dir.mkdir(parents=True)
    wf_file = wf_dir / "opsx-verify.md"
    wf_file.write_text("# Opsx Verify Workflow")

    runner = CliAgentRunner()
    resolved = runner.resolve_workflow(
        worktree_path=tmp_path,
        provider="antigravity",
        operation="verify",
        change_name="gacela-03-openspec-y-revision",
    )
    assert resolved.workflow_path == ".agent/workflows/opsx-verify.md"
    assert resolved.provider == "antigravity"
    assert resolved.operation == "verify"
    assert resolved.dispatch_command == "/opsx-verify gacela-03-openspec-y-revision"


def test_agent_runner_dynamic_workflow_missing_fails_closed(tmp_path: Path):
    runner = CliAgentRunner()
    with pytest.raises(NativeOpenSpecWorkflowUnavailable, match="Native OpenSpec Verify workflow is not installed"):
        runner.resolve_workflow(
            worktree_path=tmp_path,
            provider="codex",
            operation="verify",
            change_name="test-change",
        )


def test_agent_runner_capacity_preflight_gating():
    capacity_service = MagicMock()
    capacity_service.can_admit_change.return_value = False

    budget_service = MagicMock()
    budget_service.get_headroom.return_value = (
        SimpleNamespace(enabled=True),
        SimpleNamespace(daily_headroom_usd=0, monthly_headroom_usd=0),
    )

    runner = CliAgentRunner(
        capacity_service=capacity_service,
        budget_service=budget_service,
    )

    with pytest.raises(CapacityExhaustedError, match="Capacity service rejected admission"):
        runner.check_capacity_preflight(project_id="proj-1", provider_id="codex", role="thinker")

    capacity_service.can_admit_change.return_value = True
    with pytest.raises(CapacityExhaustedError, match="Budget headroom exhausted"):
        runner.check_capacity_preflight(project_id="proj-1", provider_id="openrouter", role="thinker")


def test_agent_runner_allows_direct_provider_when_openrouter_budget_disabled():
    capacity_service = MagicMock()
    capacity_service.can_admit_change.return_value = True
    budget_service = MagicMock()
    budget_service.get_headroom.return_value = (
        SimpleNamespace(enabled=False),
        SimpleNamespace(daily_headroom_usd=0, monthly_headroom_usd=0),
    )

    CliAgentRunner(
        capacity_service=capacity_service,
        budget_service=budget_service,
    ).check_capacity_preflight(
        project_id="proj-1", provider_id="codex", role="thinker"
    )
    budget_service.get_headroom.assert_not_called()


@pytest.mark.parametrize("provider", ["codex", "antigravity"])
def test_direct_subscription_provider_is_independent_of_openrouter_policy(provider: str):
    capacity_service = MagicMock()
    capacity_service.can_admit_change.return_value = (True, None)
    budget_service = MagicMock()
    budget_service.get_headroom.return_value = (None, None)

    CliAgentRunner(
        capacity_service=capacity_service,
        budget_service=budget_service,
    ).check_capacity_preflight(
        project_id="mini-me", provider_id=provider, role="thinker"
    )
    capacity_service.can_admit_change.assert_called_once_with("mini-me")
    budget_service.get_headroom.assert_not_called()


@pytest.mark.parametrize(
    "policy,headroom",
    [
        (None, None),
        (SimpleNamespace(enabled=False), SimpleNamespace(daily_headroom_usd=0, monthly_headroom_usd=0)),
    ],
)
def test_openrouter_remains_denied_without_enabled_policy(policy, headroom):
    budget_service = MagicMock()
    budget_service.get_headroom.return_value = (policy, headroom)
    runner = CliAgentRunner(budget_service=budget_service)
    with pytest.raises(CapacityExhaustedError, match="OpenRouter budget policy"):
        runner.check_capacity_preflight("mini-me", "openrouter", "implementer")
    budget_service.get_headroom.assert_called_once_with("mini-me")


def test_openrouter_requires_positive_budget_and_capacity():
    capacity_service = MagicMock()
    capacity_service.can_admit_change.return_value = (True, None)
    budget_service = MagicMock()
    budget_service.get_headroom.return_value = (
        SimpleNamespace(enabled=True),
        SimpleNamespace(daily_headroom_usd=1, monthly_headroom_usd=1),
    )
    CliAgentRunner(
        capacity_service=capacity_service,
        budget_service=budget_service,
    ).check_capacity_preflight("mini-me", "openrouter", "implementer")
    budget_service.get_headroom.assert_called_once_with("mini-me")
