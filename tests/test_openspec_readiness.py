"""Tests for OpenSpec discovery, artifact verification, and Definition of Ready (DoR)."""

from conftest import create_isolated_openspec_change
from minime.adapters.openspec import OpenSpecAdapter
from minime.domain.enums import ReadinessState
from minime.domain.models import Project, ProjectBinding
from minime.services.project_service import ProjectService
from minime.services.readiness_service import ReadinessService


def test_discover_active_changes_on_disk(in_memory_uow, tmp_path):
    """Proves: Active OpenSpec changes with standard artifacts are discovered on disk."""
    create_isolated_openspec_change(tmp_path, "synthetic-change-alpha")
    create_isolated_openspec_change(tmp_path, "synthetic-change-beta")

    project = Project(
        project_id="mini-me",
        display_name="mini me",
        repository="silverberdi/mini-me",
        base_branch="main",
        openspec_path="openspec",
    )
    in_memory_uow.projects.save(project)

    adapter = OpenSpecAdapter()
    changes = adapter.discover_changes(project, project_root=str(tmp_path))

    assert len(changes) == 2
    names = [c.name for c in changes]
    assert "synthetic-change-alpha" in names
    assert "synthetic-change-beta" in names


def test_dor_missing_project_binding_blocks_ready(in_memory_uow, tmp_path):
    """Proves: Registered project with NO durable ProjectBinding => NOT READY with structured reason."""
    create_isolated_openspec_change(tmp_path, "synthetic-change")

    service = ProjectService(in_memory_uow)
    service.register_project(
        project_id="mini-me",
        display_name="mini me",
        repository="silverberdi/mini-me",
        base_branch="main",
        openspec_path="openspec",
        implementer="codex",
        reviewer="antigravity",
    )

    readiness_service = ReadinessService(in_memory_uow)
    eval_result = readiness_service.evaluate_change_readiness(
        project_id="mini-me",
        change_name="synthetic-change",
        project_root=str(tmp_path),
    )

    assert eval_result.is_ready is False
    assert eval_result.status == ReadinessState.NOT_READY
    assert any("Missing durable project binding" in r for r in eval_result.unmet_reasons)


def test_dor_missing_github_issue_blocks_ready(in_memory_uow, tmp_path):
    """Proves: Valid ProjectBinding with github_issue_number=None => NOT READY with structured reason."""
    create_isolated_openspec_change(tmp_path, "synthetic-change")

    service = ProjectService(in_memory_uow)
    service.register_project(
        project_id="mini-me",
        display_name="mini me",
        repository="silverberdi/mini-me",
        base_branch="main",
        openspec_path="openspec",
        implementer="codex",
        reviewer="antigravity",
    )

    binding = ProjectBinding(
        project_id="mini-me",
        repository="silverberdi/mini-me",
        github_issue_number=None,
        openspec_change_name="synthetic-change",
    )
    in_memory_uow.bindings.save(binding)

    readiness_service = ReadinessService(in_memory_uow)
    eval_result = readiness_service.evaluate_change_readiness(
        project_id="mini-me",
        change_name="synthetic-change",
        project_root=str(tmp_path),
    )

    assert eval_result.is_ready is False
    assert eval_result.status == ReadinessState.NOT_READY
    assert any("Missing GitHub Issue binding" in r for r in eval_result.unmet_reasons)


def test_dor_evaluation_success(in_memory_uow, tmp_path):
    """Proves: Valid durable ProjectBinding with issue number => READY when all other DoR checks pass."""
    create_isolated_openspec_change(tmp_path, "synthetic-change")

    service = ProjectService(in_memory_uow)
    service.register_project(
        project_id="mini-me",
        display_name="mini me",
        repository="silverberdi/mini-me",
        base_branch="main",
        openspec_path="openspec",
        implementer="codex",
        reviewer="antigravity",
    )

    binding = ProjectBinding(
        project_id="mini-me",
        repository="silverberdi/mini-me",
        github_issue_number=1,
        openspec_change_name="synthetic-change",
    )
    in_memory_uow.bindings.save(binding)

    readiness_service = ReadinessService(in_memory_uow)
    eval_result = readiness_service.evaluate_change_readiness(
        project_id="mini-me",
        change_name="synthetic-change",
        project_root=str(tmp_path),
    )

    assert eval_result.is_ready is True
    assert eval_result.status == ReadinessState.READY
    assert len(eval_result.unmet_reasons) == 0


def test_dor_mismatched_project_binding_blocks_ready(in_memory_uow, tmp_path):
    """Proves: Mismatched durable ProjectBinding => NOT READY with structured reason."""
    create_isolated_openspec_change(tmp_path, "synthetic-change")

    service = ProjectService(in_memory_uow)
    service.register_project(
        project_id="mini-me",
        display_name="mini me",
        repository="silverberdi/mini-me",
        base_branch="main",
        openspec_path="openspec",
        implementer="codex",
        reviewer="antigravity",
    )

    # Binding repository points to a different repository
    binding = ProjectBinding(
        project_id="mini-me",
        repository="other-org/other-repo",
        github_issue_number=1,
        openspec_change_name="synthetic-change",
    )
    in_memory_uow.bindings.save(binding)

    readiness_service = ReadinessService(in_memory_uow)
    eval_result = readiness_service.evaluate_change_readiness(
        project_id="mini-me",
        change_name="synthetic-change",
        project_root=str(tmp_path),
    )

    assert eval_result.is_ready is False
    assert eval_result.status == ReadinessState.NOT_READY
    assert any("Repository mismatch" in r for r in eval_result.unmet_reasons)


def test_dor_invalid_project_binding_blocks_ready(in_memory_uow, tmp_path):
    """Proves: Invalid durable ProjectBinding (is_valid=False) => NOT READY with structured reason."""
    create_isolated_openspec_change(tmp_path, "synthetic-change")

    service = ProjectService(in_memory_uow)
    service.register_project(
        project_id="mini-me",
        display_name="mini me",
        repository="silverberdi/mini-me",
        base_branch="main",
        openspec_path="openspec",
        implementer="codex",
        reviewer="antigravity",
    )

    binding = ProjectBinding(
        project_id="mini-me",
        repository="silverberdi/mini-me",
        github_issue_number=1,
        openspec_change_name="synthetic-change",
        is_valid=False,
        mismatch_reasons=["binding unverified on remote"],
    )
    in_memory_uow.bindings.save(binding)

    readiness_service = ReadinessService(in_memory_uow)
    eval_result = readiness_service.evaluate_change_readiness(
        project_id="mini-me",
        change_name="synthetic-change",
        project_root=str(tmp_path),
    )

    assert eval_result.is_ready is False
    assert eval_result.status == ReadinessState.NOT_READY
    assert any("Invalid project binding" in r for r in eval_result.unmet_reasons)


def test_dor_missing_artifacts(in_memory_uow, tmp_path):
    # Setup dummy project with incomplete openspec directory
    empty_openspec = tmp_path / "openspec" / "changes" / "incomplete-change"
    empty_openspec.mkdir(parents=True)
    # Only create proposal.md, leaving tasks.md, design.md, specs/ missing
    (empty_openspec / "proposal.md").write_text("# Proposal", encoding="utf-8")

    project = Project(
        project_id="test-proj",
        display_name="Test Project",
        repository="org/test",
        base_branch="main",
        openspec_path="openspec",
    )
    in_memory_uow.projects.save(project)

    binding = ProjectBinding(
        project_id="test-proj",
        repository="org/test",
        github_issue_number=1,
        openspec_change_name="incomplete-change",
    )
    in_memory_uow.bindings.save(binding)

    readiness_service = ReadinessService(in_memory_uow)
    eval_result = readiness_service.evaluate_change_readiness(
        project_id="test-proj",
        change_name="incomplete-change",
        project_root=str(tmp_path),
    )

    assert eval_result.is_ready is False
    assert eval_result.status == ReadinessState.NOT_READY
    assert any("Missing required OpenSpec artifacts" in r for r in eval_result.unmet_reasons)


def test_dor_roadmap_gating(in_memory_uow, tmp_path):
    create_isolated_openspec_change(tmp_path, "future-change")

    project = Project(
        project_id="mini-me",
        display_name="mini me",
        repository="silverberdi/mini-me",
        base_branch="main",
        openspec_path="openspec",
    )
    in_memory_uow.projects.save(project)

    binding = ProjectBinding(
        project_id="mini-me",
        repository="silverberdi/mini-me",
        github_issue_number=1,
        openspec_change_name="future-change",
    )
    in_memory_uow.bindings.save(binding)

    readiness_service = ReadinessService(in_memory_uow)
    # If active change is earlier-stage, future change is blocked by roadmap gating
    eval_result = readiness_service.evaluate_change_readiness(
        project_id="mini-me",
        change_name="future-change",
        project_root=str(tmp_path),
        current_active_change="earlier-stage-change",
    )

    assert eval_result.is_ready is False
    assert any("Roadmap gating" in r for r in eval_result.unmet_reasons)


def test_runtime_isolation_does_not_modify_openspec(in_memory_uow, tmp_path):
    """Verify that runtime evaluation and status transitions leave OpenSpec files completely untouched."""
    change_dir = create_isolated_openspec_change(tmp_path, "synthetic-change")
    proposal_path = change_dir / "proposal.md"
    initial_stat = proposal_path.stat().st_mtime_ns
    initial_content = proposal_path.read_text(encoding="utf-8")

    project = Project(
        project_id="mini-me",
        display_name="mini me",
        repository="silverberdi/mini-me",
        base_branch="main",
        openspec_path="openspec",
    )
    in_memory_uow.projects.save(project)

    binding = ProjectBinding(
        project_id="mini-me",
        repository="silverberdi/mini-me",
        github_issue_number=1,
        openspec_change_name="synthetic-change",
    )
    in_memory_uow.bindings.save(binding)

    readiness_service = ReadinessService(in_memory_uow)
    eval_result = readiness_service.evaluate_change_readiness(
        project_id="mini-me",
        change_name="synthetic-change",
        project_root=str(tmp_path),
    )
    assert eval_result.is_ready is True

    # Content and mtime must remain identical
    assert proposal_path.read_text(encoding="utf-8") == initial_content
    assert proposal_path.stat().st_mtime_ns == initial_stat
