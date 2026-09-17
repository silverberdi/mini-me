"""Deterministic APPLY-attribution and pre-admission drift gate tests (Phase B)."""

from __future__ import annotations

import subprocess
from pathlib import Path

from conftest import ReadinessGitHubStub, create_isolated_openspec_change
from minime.adapters.openspec import OpenSpecAdapter
from minime.domain.models import Change, Project, ProjectBinding
from minime.services.lifecycle_gates import ApplyAttributionGate, GateStatus
from minime.services.orchestration_service import OrchestrationService


def _init_git_repo(root: Path) -> None:
    subprocess.run(["git", "init", "-b", "main"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=root, check=True)
    subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=root, check=True)
    (root / "README.md").write_text("# repo\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "-m", "base"], cwd=root, check=True, capture_output=True)
    subprocess.run(
        ["git", "update-ref", "refs/remotes/origin/main", "HEAD"], cwd=root, check=True
    )


def _project(change_name: str, **overrides) -> Project:
    kwargs = {
        "project_id": "mini-me",
        "display_name": "mini me",
        "repository": "silverberdi/mini-me",
        "base_branch": "main",
        "openspec_path": "openspec",
        "implementer": "codex",
        "reviewer": "antigravity",
        "strict_validation_required": False,
    }
    kwargs.update(overrides)
    return Project(**kwargs)


def _register(uow, project: Project, change_name: str) -> None:
    uow.projects.save(project)
    uow.bindings.save(
        ProjectBinding(
            project_id=project.project_id,
            repository=project.repository,
            github_issue_number=1,
            openspec_change_name=change_name,
        )
    )
    uow.changes.save(Change(project_id=project.project_id, name=change_name))


def _service(uow, root: Path) -> OrchestrationService:
    return OrchestrationService(
        uow,
        project_root=root,
        github_adapter=ReadinessGitHubStub(),
        openspec_adapter=OpenSpecAdapter(),
    )


# --- Direct gate coverage --------------------------------------------------


def test_clean_apply_context_passes(tmp_path: Path):
    """A clean, correctly attributed APPLY context passes the gate."""
    _init_git_repo(tmp_path)
    create_isolated_openspec_change(tmp_path, "clean-change")
    project = _project("clean-change")
    result = ApplyAttributionGate(OpenSpecAdapter()).evaluate(
        project=project, change_name="clean-change", project_root=tmp_path
    )
    assert result.status is GateStatus.PASS
    assert result.reason.code == "APPLY_ATTRIBUTION_VERIFIED"


def test_uncommitted_implementation_artifact_predating_blocks(tmp_path: Path):
    """An uncommitted implementation artifact already present predates admission."""
    _init_git_repo(tmp_path)
    create_isolated_openspec_change(tmp_path, "drift-uncommitted")
    (tmp_path / "src").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / "impl.py").write_text("print('hello')\n", encoding="utf-8")
    project = _project("drift-uncommitted")
    result = ApplyAttributionGate(OpenSpecAdapter()).evaluate(
        project=project, change_name="drift-uncommitted", project_root=tmp_path
    )
    assert result.status is GateStatus.FAIL
    assert result.reason.code == "LIFECYCLE_DRIFT"
    assert any("src/impl.py" in p for p in result.reason.details["predating_paths"])


def test_implementation_commit_predating_blocks(tmp_path: Path):
    """A committed implementation change predating the run boundary is drift."""
    _init_git_repo(tmp_path)
    create_isolated_openspec_change(tmp_path, "drift-committed")
    (tmp_path / "src").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / "impl.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "commit", "-m", "predating implementation"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    project = _project("drift-committed")
    result = ApplyAttributionGate(OpenSpecAdapter()).evaluate(
        project=project, change_name="drift-committed", project_root=tmp_path
    )
    assert result.status is GateStatus.FAIL
    assert result.reason.code == "LIFECYCLE_DRIFT"
    assert any("src/impl.py" in p for p in result.reason.details["predating_paths"])


def test_ambiguous_attribution_blocks(tmp_path: Path):
    """Without a verifiable git base boundary the gate fails closed as UNKNOWN."""
    create_isolated_openspec_change(tmp_path, "ambiguous")
    project = _project("ambiguous")
    result = ApplyAttributionGate(OpenSpecAdapter()).evaluate(
        project=project, change_name="ambiguous", project_root=tmp_path
    )
    assert result.status is GateStatus.UNKNOWN
    assert result.reason.code == "ATTRIBUTION_UNVERIFIABLE"


def test_planning_only_artifacts_not_mistaken_for_implementation(tmp_path: Path):
    """Planning-only OpenSpec artifacts committed on top of base are not drift."""
    _init_git_repo(tmp_path)
    create_isolated_openspec_change(tmp_path, "planning-only")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "commit", "-m", "add planning artifacts"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    project = _project("planning-only")
    result = ApplyAttributionGate(OpenSpecAdapter()).evaluate(
        project=project, change_name="planning-only", project_root=tmp_path
    )
    assert result.status is GateStatus.PASS
    assert result.reason.code == "APPLY_ATTRIBUTION_VERIFIED"


def test_preexisting_repository_state_no_false_attribution(tmp_path: Path):
    """Pre-existing base-branch implementation history is not candidate drift."""
    _init_git_repo(tmp_path)
    (tmp_path / "src").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / "legacy.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "commit", "-m", "pre-existing implementation"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "update-ref", "refs/remotes/origin/main", "HEAD"], cwd=tmp_path, check=True
    )
    create_isolated_openspec_change(tmp_path, "pre-existing")
    project = _project("pre-existing")
    result = ApplyAttributionGate(OpenSpecAdapter()).evaluate(
        project=project, change_name="pre-existing", project_root=tmp_path
    )
    assert result.status is GateStatus.PASS


def test_gate_blocks_missing_openspec_change(tmp_path: Path):
    """Admission with no on-disk OpenSpec change is refused without fabrication."""
    _init_git_repo(tmp_path)
    project = _project("missing-change")
    result = ApplyAttributionGate(OpenSpecAdapter()).evaluate(
        project=project, change_name="missing-change", project_root=tmp_path
    )
    assert result.status is GateStatus.FAIL
    assert result.reason.code == "OPENSPEC_CHANGE_MISSING"


# --- Admission integration coverage ---------------------------------------


def test_valid_admission_with_clean_worktree_allowed(in_memory_uow, tmp_path: Path):
    """A clean planning-only worktree admits a run (Phase A readiness + Phase B gate)."""
    _init_git_repo(tmp_path)
    create_isolated_openspec_change(tmp_path, "clean-admit")
    project = _project("clean-admit")
    _register(in_memory_uow, project, "clean-admit")

    admission = _service(in_memory_uow, tmp_path).admit_change(
        "mini-me", "clean-admit", tmp_path
    )
    assert admission.admitted is True
    assert admission.run is not None
    assert in_memory_uow.orchestration_runs.get_by_id(admission.run.run_id) is not None


def test_admission_blocks_predating_implementation_commit(in_memory_uow, tmp_path: Path):
    """Phase B gate blocks admission when implementation predates the run boundary."""
    _init_git_repo(tmp_path)
    create_isolated_openspec_change(tmp_path, "drift-admit")
    (tmp_path / "src").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / "impl.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "commit", "-m", "predating"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    project = _project("drift-admit")
    _register(in_memory_uow, project, "drift-admit")

    admission = _service(in_memory_uow, tmp_path).admit_change(
        "mini-me", "drift-admit", tmp_path
    )
    assert admission.admitted is False
    assert admission.refusal_details["code"] == "LIFECYCLE_DRIFT"
    assert in_memory_uow.orchestration_runs.list_runs() == []


def test_duplicate_admission_refused_with_existing_run(in_memory_uow, tmp_path: Path):
    """A second admission returns the existing run identity without a new run."""
    _init_git_repo(tmp_path)
    create_isolated_openspec_change(tmp_path, "dup-admit")
    project = _project("dup-admit")
    _register(in_memory_uow, project, "dup-admit")
    service = _service(in_memory_uow, tmp_path)

    first = service.admit_change("mini-me", "dup-admit", tmp_path)
    assert first.admitted is True

    second = service.admit_change("mini-me", "dup-admit", tmp_path)
    assert second.admitted is False
    assert second.refusal_details["code"] == "DUPLICATE_ACTIVE_RUN"
    assert second.existing_run_id == first.run.run_id


def test_no_openspec_change_blocks_admission(in_memory_uow, tmp_path: Path):
    """Requested admission with no on-disk OpenSpec change refuses without a run."""
    _init_git_repo(tmp_path)
    project = _project("missing-admit")
    _register(in_memory_uow, project, "missing-admit")

    admission = _service(in_memory_uow, tmp_path).admit_change(
        "mini-me", "missing-admit", tmp_path
    )
    assert admission.admitted is False
    assert in_memory_uow.orchestration_runs.list_runs() == []


def test_apply_gate_composes_with_readiness_strict_validation(in_memory_uow, tmp_path: Path):
    """Phase A strict validation still blocks when Phase B attribution is clean."""
    _init_git_repo(tmp_path)
    # A planning-complete but strict-invalid delta spec must still be blocked by
    # Phase A, proving Phase A is not weakened by the Phase B attribution gate.
    create_isolated_openspec_change(tmp_path, "strict-invalid-clean", spec_content="# Spec\n")
    project = _project("strict-invalid-clean", strict_validation_required=True)
    _register(in_memory_uow, project, "strict-invalid-clean")

    admission = _service(in_memory_uow, tmp_path).admit_change(
        "mini-me", "strict-invalid-clean", tmp_path
    )
    assert admission.admitted is False
    assert admission.refusal_details["code"] == "NOT_READY"
    reasons = admission.refusal_details.get("unmet_reasons", [])
    assert any(
        reason.startswith("OPENSPEC_STRICT_VALIDATION_FAILED")
        or reason.startswith("OPENSPEC_CLI_UNAVAILABLE")
        for reason in reasons
    )
    assert in_memory_uow.orchestration_runs.list_runs() == []
