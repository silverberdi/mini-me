"""Deterministic VERIFY gate and review-evidence report tests (Phase C)."""

from __future__ import annotations

from pathlib import Path

from conftest import create_isolated_openspec_change
from minime.adapters.openspec import OpenSpecAdapter
from minime.domain.enums import ReviewStatus, ReviewVerdict
from minime.domain.models import (
    Job,
    OrchestrationCandidate,
    OrchestrationRun,
    Project,
    Review,
)
from minime.services.authorship_service import AuthorshipService
from minime.services.lifecycle_gates import GateStatus, VerifyGate
from minime.services.review_evidence import build_review_evidence_report


def _project(change_name: str = "verify-change", **overrides) -> Project:
    kwargs = dict(
        project_id="mini-me",
        display_name="mini me",
        repository="silverberdi/mini-me",
        base_branch="main",
        openspec_path="openspec",
        implementer="codex",
        reviewer="antigravity",
    )
    kwargs.update(overrides)
    return Project(**kwargs)


def _candidate(
    run_id: str = "run-1",
    generation: int = 1,
    candidate_sha: str = "cand-sha",
    base_sha: str = "base-sha",
    manifest_id: str = "manifest-1",
    manifest_hash: str = "hash-1",
) -> OrchestrationCandidate:
    return OrchestrationCandidate(
        run_id=run_id,
        generation=generation,
        candidate_sha=candidate_sha,
        base_sha=base_sha,
        manifest_id=manifest_id,
        manifest_hash=manifest_hash,
    )


def _run(
    run_id: str = "run-1",
    base_sha: str = "base-sha",
    change_name: str = "verify-change",
    active_job_id: str = "job-1",
) -> OrchestrationRun:
    return OrchestrationRun(
        run_id=run_id,
        project_id="mini-me",
        change_name=change_name,
        base_sha=base_sha,
        active_job_id=active_job_id,
    )


def _job(
    job_id: str = "job-1",
    candidate_sha: str = "cand-sha",
    base_sha: str = "base-sha",
    change_name: str = "verify-change",
) -> Job:
    return Job(
        job_id=job_id,
        project_id="mini-me",
        change_name=change_name,
        implementer_role="codex",
        candidate_sha=candidate_sha,
        base_sha=base_sha,
    )


def _review(
    job_id: str = "job-1",
    run_id: str = "run-1",
    generation: int = 1,
    candidate_sha: str = "cand-sha",
    base_sha: str = "base-sha",
    manifest_id: str = "manifest-1",
    manifest_hash: str = "hash-1",
    status: ReviewStatus = ReviewStatus.REVIEW_COMPLETED,
    verdict: ReviewVerdict = ReviewVerdict.READY_TO_MERGE,
    change_name: str = "verify-change",
) -> Review:
    return Review(
        job_id=job_id,
        project_id="mini-me",
        change_name=change_name,
        reviewer_role="antigravity",
        orchestration_run_id=run_id,
        candidate_generation=generation,
        candidate_sha=candidate_sha,
        base_sha=base_sha,
        manifest_id=manifest_id,
        manifest_hash=manifest_hash,
        status=status,
        verdict=verdict,
    )


# --- VerifyGate -------------------------------------------------------------


def test_verify_gate_passes_with_valid_evidence(tmp_path: Path):
    """Valid canonical VERIFY evidence (strict + coherence + scope) passes."""
    create_isolated_openspec_change(
        tmp_path, "verify-ok", tasks_content="## 1. Foundation\n- [x] 1.1 Do thing\n"
    )
    project = _project("verify-ok")
    result = VerifyGate(OpenSpecAdapter()).evaluate(
        project=project,
        change_name="verify-ok",
        project_root=tmp_path,
        candidate_sha="abc123",
        changed_paths=["src/impl.py", "openspec/changes/verify-ok/tasks.md"],
    )
    assert result.status is GateStatus.PASS
    assert result.reason.code == "VERIFY_PASSED"


def test_verify_gate_blocks_when_openspec_validation_fails(tmp_path: Path):
    """A strict-invalid change fails the VERIFY gate."""
    create_isolated_openspec_change(tmp_path, "verify-invalid", spec_content="# Spec\n")
    project = _project("verify-invalid")
    result = VerifyGate(OpenSpecAdapter()).evaluate(
        project=project,
        change_name="verify-invalid",
        project_root=tmp_path,
        candidate_sha="abc123",
        changed_paths=["src/impl.py"],
    )
    assert result.status is GateStatus.FAIL
    assert result.reason.code == "VERIFY_OPENSPEC_INVALID"


def test_verify_gate_blocks_when_unverifiable(tmp_path: Path):
    """Unavailable strict validation is UNKNOWN and blocking."""
    create_isolated_openspec_change(tmp_path, "verify-unknown")
    project = _project("verify-unknown")
    result = VerifyGate(OpenSpecAdapter(cli_command="does-not-exist")).evaluate(
        project=project,
        change_name="verify-unknown",
        project_root=tmp_path,
        candidate_sha="abc123",
        changed_paths=["src/impl.py"],
    )
    assert result.status is GateStatus.UNKNOWN
    assert result.reason.code == "VERIFY_UNVERIFIABLE"


def test_verify_gate_blocks_when_tasks_done_without_evidence(tmp_path: Path):
    """All tasks checked but zero implementation evidence is blocked."""
    create_isolated_openspec_change(
        tmp_path, "verify-empty", tasks_content="## 1. Foundation\n- [x] 1.1 Do thing\n"
    )
    project = _project("verify-empty")
    result = VerifyGate(OpenSpecAdapter()).evaluate(
        project=project,
        change_name="verify-empty",
        project_root=tmp_path,
        candidate_sha="abc123",
        changed_paths=["openspec/changes/verify-empty/tasks.md"],
    )
    assert result.status is GateStatus.FAIL
    assert result.reason.code == "VERIFY_TASK_EVIDENCE_MISSING"


def test_verify_gate_blocks_on_scope_violation(tmp_path: Path):
    """Touching another change's planning or canonical specs violates scope."""
    create_isolated_openspec_change(tmp_path, "verify-scope")
    create_isolated_openspec_change(tmp_path, "other-change")
    project = _project("verify-scope")
    result = VerifyGate(OpenSpecAdapter()).evaluate(
        project=project,
        change_name="verify-scope",
        project_root=tmp_path,
        candidate_sha="abc123",
        changed_paths=[
            "src/impl.py",
            "openspec/changes/other-change/proposal.md",
        ],
    )
    assert result.status is GateStatus.FAIL
    assert result.reason.code == "VERIFY_SCOPE_VIOLATION"


def test_verify_gate_requires_candidate_binding(tmp_path: Path):
    """No candidate SHA bound means verification cannot be truthfully evaluated."""
    create_isolated_openspec_change(tmp_path, "verify-unbound")
    project = _project("verify-unbound")
    result = VerifyGate(OpenSpecAdapter()).evaluate(
        project=project,
        change_name="verify-unbound",
        project_root=tmp_path,
        candidate_sha=None,
        changed_paths=["src/impl.py"],
    )
    assert result.status is GateStatus.UNKNOWN


# --- ReviewEvidenceReport ---------------------------------------------------


def test_review_evidence_report_passes(in_memory_uow):
    project = _project()
    in_memory_uow.projects.save(project)
    in_memory_uow.reviews.save(_review())
    report = build_review_evidence_report(
        in_memory_uow, _run(), _job(), _candidate(), project, AuthorshipService()
    )
    assert report.satisfied is True
    assert report.status == "PASS"


def test_review_evidence_report_missing_review_blocks(in_memory_uow):
    project = _project()
    in_memory_uow.projects.save(project)
    report = build_review_evidence_report(
        in_memory_uow, _run(), _job(), _candidate(), project, AuthorshipService()
    )
    assert report.satisfied is False
    assert report.finding_category == "MISSING_REVIEW"


def test_review_evidence_report_stale_review_blocks(in_memory_uow):
    project = _project()
    in_memory_uow.projects.save(project)
    in_memory_uow.reviews.save(_review(candidate_sha="old-sha"))
    report = build_review_evidence_report(
        in_memory_uow, _run(), _job(), _candidate(), project, AuthorshipService()
    )
    assert report.satisfied is False
    assert report.finding_category == "STALE_REVIEW"
    assert report.candidate_sha == "old-sha"
    assert report.expected_candidate_sha == "cand-sha"


def test_review_evidence_report_wrong_run_blocks(in_memory_uow):
    """Review evidence bound to another run must not satisfy the gate."""
    project = _project()
    in_memory_uow.projects.save(project)
    in_memory_uow.reviews.save(_review(run_id="other-run"))
    report = build_review_evidence_report(
        in_memory_uow, _run(), _job(), _candidate(), project, AuthorshipService()
    )
    assert report.satisfied is False
    assert report.finding_category is None
