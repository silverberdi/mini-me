"""Tests for HandoffManager and AuthorshipService."""

from __future__ import annotations

from unittest.mock import MagicMock

from minime.domain.enums import JobStatus
from minime.domain.models import (
    CandidateAuthorship,
    CandidateManifest,
    CheckResult,
    Job,
    JobHandoff,
)
from minime.services.authorship_service import AuthorshipService
from minime.services.handoff_manager import HandoffManager
from minime.services.openspec_tasks import OpenSpecTask


def test_handoff_manager_create_and_format_prompt():
    manager = HandoffManager()

    completed = [OpenSpecTask("1.1", "Create enum", "Phase 1", True)]
    remaining = [OpenSpecTask("1.2", "Create model", "Phase 1", False)]

    manifest = CandidateManifest(
        manifest_id="m1",
        job_id="j1",
        candidate_sha="cand123",
        tracked_files=[{"path": "src/enums.py", "sha256": "h1"}],
        staged_files=[],
        untracked_files=[],
        deleted_files=[],
        total_files_count=1,
        manifest_hash="manhash",
    )

    check = CheckResult(
        result_id="c1",
        job_id="j1",
        check_name="test_enums",
        command="pytest",
        exit_code=0,
        duration_ms=10,
        output_snippet="PASSED",
    )

    handoff = manager.create_handoff(
        job_id="j1",
        from_attempt_id="att1",
        from_executor="codex",
        to_executor="antigravity",
        worktree_path="/tmp/worktree",
        base_sha="base123",
        candidate_sha="cand123",
        completed_tasks=completed,
        remaining_tasks=remaining,
        manifest=manifest,
        check_results=[check],
    )

    assert handoff.from_executor == "codex"
    assert handoff.to_executor == "antigravity"
    assert handoff.completed_tasks == ["1.1"]
    assert handoff.remaining_tasks == ["1.2"]
    assert any("1.1" in g for g in handoff.do_not_redo_guidance)
    assert not handoff.is_consumed

    prompt = manager.format_handoff_prompt(handoff)
    assert "Prior Executor: codex" in prompt
    assert "[x] Task 1.1" in prompt
    assert "[ ] Task 1.2" in prompt
    assert "DO NOT REDO GUIDANCE:" in prompt


def test_handoff_manager_consume_handoff():
    manager = HandoffManager()
    uow = MagicMock()

    existing_handoff = JobHandoff(
        handoff_id="h1",
        job_id="j1",
        from_attempt_id="att1",
        from_executor="codex",
        to_executor="antigravity",
        worktree_path="/tmp/worktree",
        base_sha="base123",
        candidate_sha="cand123",
    )
    uow.job_handoffs.get_by_id.return_value = existing_handoff

    consumed = manager.consume_handoff("h1", "att2", uow)
    assert consumed is not None
    assert consumed.is_consumed is True
    assert consumed.to_attempt_id == "att2"
    uow.job_handoffs.save.assert_called_once_with(existing_handoff)


def test_authorship_service_tracking_single_and_mixed():
    service = AuthorshipService()
    uow = MagicMock()

    job = Job(
        job_id="j1",
        project_id="p1",
        change_name="007-change",
        status=JobStatus.RUNNING,
        implementer_role="codex",
    )
    uow.jobs.get_by_id.return_value = job

    # 1. First author
    auth1 = CandidateAuthorship(
        authorship_id="a1",
        job_id="j1",
        agent_role="codex",
        model_identity="codex-default",
        attempt_number=1,
        files_touched=["src/a.py"],
        is_primary_author=True,
    )
    uow.candidate_authorships.list_by_job.return_value = [auth1]

    res1 = service.record_attempt_authorship(
        job_id="j1",
        agent_role="codex",
        model_identity="codex-default",
        attempt_number=1,
        files_touched=["src/a.py"],
        uow=uow,
    )
    assert res1.is_primary_author is True
    assert job.is_mixed_authorship is False

    # 2. Second author (different role / model)
    auth2 = CandidateAuthorship(
        authorship_id="a2",
        job_id="j1",
        agent_role="antigravity",
        model_identity="agy-default",
        attempt_number=2,
        files_touched=["src/b.py"],
        is_primary_author=False,
    )
    uow.candidate_authorships.list_by_job.return_value = [auth1, auth2]

    res2 = service.record_attempt_authorship(
        job_id="j1",
        agent_role="antigravity",
        model_identity="agy-default",
        attempt_number=2,
        files_touched=["src/b.py"],
        uow=uow,
    )
    assert res2.is_primary_author is False
    assert job.is_mixed_authorship is True
    uow.jobs.save.assert_called_with(job)

    # 3. Summary
    summary = service.get_authorship_summary("j1", uow)
    assert summary["is_mixed_authorship"] is True
    assert summary["author_count"] == 2
    assert "codex-default" in summary["distinct_models"]
    assert "agy-default" in summary["distinct_models"]
