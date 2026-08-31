"""Unit tests for Autonomous Queue and Scheduler domain models and enums."""

from datetime import datetime

from minime.domain.enums import (
    AdmissionDecision,
    AdmissionRefusalCode,
    QueuePriority,
    ReadinessState,
    SchedulerMode,
)
from minime.domain.models import (
    QueueExplainReport,
    SchedulerDecisionRecord,
    SchedulerStatusView,
    WorkQueueItem,
)


def test_queue_priority_enum_values():
    assert QueuePriority.CRITICAL == "CRITICAL"
    assert QueuePriority.HIGH == "HIGH"
    assert QueuePriority.NORMAL == "NORMAL"
    assert QueuePriority.LOW == "LOW"


def test_admission_decision_and_refusal_codes():
    assert AdmissionDecision.ADMITTED == "ADMITTED"
    assert AdmissionDecision.REFUSED == "REFUSED"
    assert AdmissionDecision.SKIPPED == "SKIPPED"

    assert AdmissionRefusalCode.ROADMAP_PREDECESSOR_INCOMPLETE == "ROADMAP_PREDECESSOR_INCOMPLETE"
    assert AdmissionRefusalCode.DEPENDENCY_BLOCKED == "DEPENDENCY_BLOCKED"
    assert AdmissionRefusalCode.GLOBAL_CONCURRENCY_LIMIT == "GLOBAL_CONCURRENCY_LIMIT"
    assert AdmissionRefusalCode.PROJECT_CONCURRENCY_LIMIT == "PROJECT_CONCURRENCY_LIMIT"
    assert AdmissionRefusalCode.PROVIDER_DRAIN == "PROVIDER_DRAIN"


def test_work_queue_item_instantiation_and_defaults():
    item = WorkQueueItem(
        project_id="mini-me",
        change_name="016-autonomous-queue-work-selection",
        github_issue_number=45,
        github_issue_title="Autonomous Queue & Work Selection",
        priority=QueuePriority.HIGH,
        roadmap_stage=16,
    )
    assert item.queue_item_id is not None
    assert item.project_id == "mini-me"
    assert item.change_name == "016-autonomous-queue-work-selection"
    assert item.priority == QueuePriority.HIGH
    assert item.roadmap_stage == 16
    assert item.readiness_state == ReadinessState.NOT_READY
    assert item.admission_eligible is False
    assert isinstance(item.discovered_at, datetime)
    assert isinstance(item.last_evaluated_at, datetime)


def test_scheduler_decision_record_instantiation():
    record = SchedulerDecisionRecord(
        project_id="mini-me",
        change_name="016-autonomous-queue-work-selection",
        github_issue_number=45,
        decision=AdmissionDecision.ADMITTED,
        reason_summary="Change is READY and capacity is available.",
        priority_score=5250.0,
        selected_implementer="codex",
        concurrency_snapshot={"global_active": 0, "project_active": 0},
        capacity_snapshot={"mode": "RUN", "codex": "AVAILABLE"},
        run_id="run-123",
    )
    assert record.decision_id is not None
    assert record.decision == AdmissionDecision.ADMITTED
    assert record.selected_implementer == "codex"
    assert record.run_id == "run-123"
    assert record.priority_score == 5250.0


def test_queue_explain_report_model():
    report = QueueExplainReport(
        project_id="mini-me",
        change_name="016-autonomous-queue-work-selection",
        github_issue_number=45,
        readiness_state=ReadinessState.READY,
        admission_eligible=True,
        priority=QueuePriority.HIGH,
        base_score=5000.0,
        aging_bonus=200.0,
        roadmap_precedence_penalty=0.0,
        total_score=5200.0,
        queue_position=1,
        selection_rationale="Ranked 1st: HIGH priority with 4h aging bonus.",
    )
    assert report.total_score == 5200.0
    assert report.queue_position == 1
    assert report.admission_eligible is True


def test_scheduler_status_view():
    status = SchedulerStatusView(
        mode=SchedulerMode.RUN,
        queue_depth=3,
        ready_count=1,
        blocked_count=2,
        active_runs_count=0,
        max_global_jobs=1,
    )
    assert status.mode == SchedulerMode.RUN
    assert status.queue_depth == 3
    assert status.ready_count == 1
    assert status.blocked_count == 2
