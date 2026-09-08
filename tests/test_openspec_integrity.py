"""Deterministic OpenSpec integrity auditor tests (Phase E)."""

from __future__ import annotations

from pathlib import Path

from conftest import create_isolated_openspec_change
from minime.adapters.openspec import OpenSpecAdapter
from minime.domain.enums import OrchestrationStage, OrchestrationStopOutcome
from minime.domain.models import Change, OrchestrationRun, Project, ProjectBinding
from minime.services.openspec_integrity import OpenSpecIntegrityService


def _project(**overrides) -> Project:
    kwargs = dict(
        project_id="mini-me",
        display_name="mini me",
        repository="silverberdi/mini-me",
        base_branch="main",
        openspec_path="openspec",
    )
    kwargs.update(overrides)
    return Project(**kwargs)


def _register_project(uow, project: Project) -> None:
    uow.projects.save(project)


def _save_change(uow, name: str) -> None:
    uow.changes.save(Change(project_id="mini-me", name=name))


def _save_run(
    uow,
    name: str,
    run_id: str,
    stage: OrchestrationStage,
    *,
    active: bool = False,
    pr_number: int | None = None,
) -> None:
    uow.orchestration_runs.save(
        OrchestrationRun(
            run_id=run_id,
            project_id="mini-me",
            change_name=name,
            base_sha="base123",
            current_stage=stage,
            stop_outcome=OrchestrationStopOutcome.READY_FOR_HUMAN_MERGE
            if stage == OrchestrationStage.PR_PREPARED
            else None,
            is_active=active,
        )
    )
    if pr_number is not None:
        uow.bindings.save(
            ProjectBinding(
                project_id="mini-me",
                repository="silverberdi/mini-me",
                github_issue_number=1,
                github_pr_number=pr_number,
                openspec_change_name=name,
                is_valid=True,
            )
        )


def _categories(audit) -> set[str]:
    return {f["category"] for f in audit.findings}


def test_integrity_audit_healthy_repository_passes(in_memory_uow, tmp_path: Path):
    project = _project()
    _register_project(in_memory_uow, project)
    create_isolated_openspec_change(tmp_path, "healthy-change")
    _save_change(in_memory_uow, "healthy-change")

    audit = OpenSpecIntegrityService(in_memory_uow, project_root=tmp_path).run_audit("mini-me")

    assert audit.overall_status == "PASS"
    assert audit.findings == []


def test_integrity_audit_invalid_active_change_fails(in_memory_uow, tmp_path: Path):
    project = _project()
    _register_project(in_memory_uow, project)
    create_isolated_openspec_change(tmp_path, "invalid-change", spec_content="# Spec\n")
    _save_change(in_memory_uow, "invalid-change")

    audit = OpenSpecIntegrityService(in_memory_uow, project_root=tmp_path).run_audit("mini-me")

    assert audit.overall_status == "FAIL"
    assert "INVALID_ACTIVE_CHANGE" in _categories(audit)


def test_integrity_audit_merged_but_unsynced(in_memory_uow, tmp_path: Path):
    project = _project()
    _register_project(in_memory_uow, project)
    create_isolated_openspec_change(tmp_path, "merged-unsynced")
    _save_change(in_memory_uow, "merged-unsynced")
    _save_run(
        in_memory_uow,
        "merged-unsynced",
        "run-1",
        OrchestrationStage.PR_PREPARED,
        pr_number=42,
    )

    audit = OpenSpecIntegrityService(in_memory_uow, project_root=tmp_path).run_audit("mini-me")

    assert audit.overall_status == "FAIL"
    assert "MERGED_BUT_UNSYNCED" in _categories(audit)
    finding = next(f for f in audit.findings if f["category"] == "MERGED_BUT_UNSYNCED")
    assert "feature" in finding["evidence"]["unsynchronized_capabilities"]


def test_integrity_audit_closed_but_unarchived(in_memory_uow, tmp_path: Path):
    project = _project()
    _register_project(in_memory_uow, project)
    create_isolated_openspec_change(tmp_path, "closed-unarchived")
    _save_run(in_memory_uow, "closed-unarchived", "run-2", OrchestrationStage.COMPLETED)

    audit = OpenSpecIntegrityService(in_memory_uow, project_root=tmp_path).run_audit("mini-me")

    assert audit.overall_status == "FAIL"
    assert "CLOSED_BUT_UNARCHIVED" in _categories(audit)


def test_integrity_audit_orphan_directory_warning(in_memory_uow, tmp_path: Path):
    project = _project()
    _register_project(in_memory_uow, project)
    (tmp_path / "openspec" / "changes" / "orphan-thing").mkdir(parents=True)

    audit = OpenSpecIntegrityService(in_memory_uow, project_root=tmp_path).run_audit("mini-me")

    assert "ORPHAN_DIRECTORY" in _categories(audit)
    orphan = next(f for f in audit.findings if f["category"] == "ORPHAN_DIRECTORY")
    assert orphan["severity"] == "WARNING"


def test_integrity_audit_insufficient_evidence_unknown(in_memory_uow, tmp_path: Path):
    project = _project()
    _register_project(in_memory_uow, project)
    create_isolated_openspec_change(tmp_path, "unverifiable-change")
    _save_change(in_memory_uow, "unverifiable-change")

    audit = OpenSpecIntegrityService(
        in_memory_uow,
        project_root=tmp_path,
        openspec_adapter=OpenSpecAdapter(cli_command="does-not-exist"),
    ).run_audit("mini-me")

    assert audit.overall_status == "UNKNOWN"
    assert audit.evidence_gaps


def test_integrity_legacy_classification_does_not_fabricate(in_memory_uow, tmp_path: Path):
    project = _project()
    _register_project(in_memory_uow, project)
    create_isolated_openspec_change(tmp_path, "no-metadata-change")
    # An archived entry with no OpenSpec artifacts -> LEGACY_ARCHIVE_DEBT.
    archive_dir = tmp_path / "openspec" / "changes" / "archive" / "2026-01-01-legacy-thing"
    archive_dir.mkdir(parents=True)
    (archive_dir / "src").mkdir()
    (archive_dir / "src" / "impl.py").write_text("x = 1\n")

    audit = OpenSpecIntegrityService(in_memory_uow, project_root=tmp_path).run_audit("mini-me")

    legacy_findings = [f for f in audit.findings if f["category"] == "LEGACY_CLASSIFICATION"]
    classifications = {f["evidence"]["classification"] for f in legacy_findings}
    # The complete change without .openspec.yaml is CANONICAL, so it is not flagged.
    assert "CANONICAL" not in classifications
    assert "LEGACY_ARCHIVE_DEBT" in classifications


def test_integrity_task_state_contradiction(in_memory_uow, tmp_path: Path):
    project = _project()
    _register_project(in_memory_uow, project)
    create_isolated_openspec_change(
        tmp_path, "task-contradiction", tasks_content="- [x] 1.1 Done\n"
    )
    _save_run(in_memory_uow, "task-contradiction", "run-3", OrchestrationStage.ADMITTED)

    audit = OpenSpecIntegrityService(in_memory_uow, project_root=tmp_path).run_audit("mini-me")

    assert "TASK_STATE_CONTRADICTION" in _categories(audit)

