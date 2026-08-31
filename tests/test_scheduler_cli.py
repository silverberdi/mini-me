"""CLI tests for queue and scheduler commands."""

from contextlib import contextmanager
from unittest.mock import MagicMock

from minime.cli import main
from minime.domain.enums import (
    AdmissionDecision,
    QueuePriority,
    ReadinessState,
    SchedulerMode,
)
from minime.domain.models import (
    QueueExplainReport,
    SchedulerDecisionRecord,
    SchedulerStatusView,
    WorkQueueItem,
    utc_now,
)


def test_queue_list_cli(monkeypatch, capsys):
    item = WorkQueueItem(
        project_id="mini-me",
        change_name="016-autonomous-queue-work-selection",
        github_issue_number=45,
        priority=QueuePriority.HIGH,
        roadmap_stage=16,
        readiness_state=ReadinessState.READY,
        admission_eligible=True,
        priority_score=5000.0,
    )

    class MockSchedulerService:
        def __init__(self, uow):
            pass

        def rank_candidates(self, items):
            return [item]

    class MockUOW:
        def __init__(self, session):
            self.work_queue = MagicMock()
            self.work_queue.list_all.return_value = [item]

    @contextmanager
    def mock_session():
        yield object()

    monkeypatch.setattr(main.db_manager, "session", mock_session)
    monkeypatch.setattr(main, "PostgresPersistenceUnitOfWork", MockUOW)
    monkeypatch.setattr(main, "SchedulerService", MockSchedulerService)

    main.queue_list_cmd(project_id="mini-me", ready_only=False, json_output=False)
    output = capsys.readouterr().out
    assert "016-autonomous-queue-work-selection" in output
    assert "HIGH" in output
    assert "5000.0" in output


def test_queue_explain_cli(monkeypatch, capsys):
    report = QueueExplainReport(
        project_id="mini-me",
        change_name="016-autonomous-queue-work-selection",
        github_issue_number=45,
        readiness_state=ReadinessState.READY,
        admission_eligible=True,
        priority=QueuePriority.HIGH,
        base_score=5000.0,
        aging_bonus=50.0,
        roadmap_precedence_penalty=0.0,
        total_score=5050.0,
        queue_position=1,
        blockers=[],
        refusal_code=None,
        selection_rationale="Ranked #1: Base score 5000 + Aging 50",
        evaluated_at=utc_now(),
    )

    class MockSchedulerService:
        def __init__(self, uow):
            pass

        def explain_item_priority(self, project_id, change_name):
            return report

    @contextmanager
    def mock_session():
        yield object()

    monkeypatch.setattr(main.db_manager, "session", mock_session)
    monkeypatch.setattr(main, "PostgresPersistenceUnitOfWork", lambda s: MagicMock())
    monkeypatch.setattr(main, "SchedulerService", MockSchedulerService)

    main.queue_explain_cmd(
        change_name="016-autonomous-queue-work-selection",
        project_id="mini-me",
        json_output=False,
    )
    output = capsys.readouterr().out
    assert "Position: #1" in output
    assert "Priority: HIGH" in output
    assert "Base Score: 5000.0" in output
    assert "Admission Eligible: YES" in output


def test_scheduler_status_cli(monkeypatch, capsys):
    status_view = SchedulerStatusView(
        mode=SchedulerMode.RUN,
        queue_depth=5,
        ready_count=2,
        blocked_count=3,
        active_runs_count=1,
        max_global_jobs=1,
        next_candidate=None,
        recent_decisions=[],
        provider_health={"codex": "AVAILABLE", "antigravity": "AVAILABLE"},
        evaluated_at=utc_now(),
    )

    class MockSchedulerService:
        def __init__(self, uow):
            pass

        def get_status(self, project_id=None):
            return status_view

    @contextmanager
    def mock_session():
        yield object()

    monkeypatch.setattr(main.db_manager, "session", mock_session)
    monkeypatch.setattr(main, "PostgresPersistenceUnitOfWork", lambda s: MagicMock())
    monkeypatch.setattr(main, "SchedulerService", MockSchedulerService)

    main.scheduler_status_cmd(project_id="mini-me", json_output=False)
    output = capsys.readouterr().out
    assert "Queue Depth: 5" in output
    assert "Active Runs: 1/1" in output
    assert "codex: AVAILABLE" in output


def test_scheduler_tick_cli(monkeypatch, capsys):
    decision = SchedulerDecisionRecord(
        project_id="mini-me",
        change_name="016-autonomous-queue-work-selection",
        github_issue_number=45,
        decision=AdmissionDecision.ADMITTED,
        reason_summary="READY and admitted",
        priority_score=5000.0,
    )

    class MockSchedulerService:
        def __init__(self, uow):
            pass

        def tick(self, project_id=None):
            return [decision]

    @contextmanager
    def mock_session():
        yield object()

    monkeypatch.setattr(main.db_manager, "session", mock_session)
    monkeypatch.setattr(main, "PostgresPersistenceUnitOfWork", lambda s: MagicMock())
    monkeypatch.setattr(main, "SchedulerService", MockSchedulerService)

    main.scheduler_tick_cmd(project_id="mini-me", json_output=False)
    output = capsys.readouterr().out
    assert "Scheduler tick completed: 1 items evaluated" in output
    assert "[ADMITTED] 016-autonomous-queue-work-selection" in output
