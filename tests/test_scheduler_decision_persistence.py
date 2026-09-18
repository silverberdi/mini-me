"""Round-trip persistence tests for scheduler decision operational truth.

The scheduler_decision_records table has no dedicated operational-decision
columns; the canonical operational truth (RUN/DRAIN/WAIT/NEEDS_HUMAN plus block
semantics) is persisted inside the existing capacity_snapshot JSON column and
must survive a domain -> model -> domain reload without collapsing to legacy
ADMITTED/REFUSED.
"""

from __future__ import annotations

from datetime import timedelta

from minime.db.repository import (
    scheduler_decision_domain_to_model,
    scheduler_decision_model_to_domain,
)
from minime.domain.enums import (
    AdmissionBlockCondition,
    AdmissionDecision,
    AdmissionDecisionKind,
)
from minime.domain.models import SchedulerDecisionRecord, utc_now


def _roundtrip(record: SchedulerDecisionRecord) -> SchedulerDecisionRecord:
    model = scheduler_decision_domain_to_model(record)
    return scheduler_decision_model_to_domain(model)


def test_scheduler_decision_operational_roundtrip_run():
    record = SchedulerDecisionRecord(
        project_id="mini-me",
        change_name="016-feature",
        decision=AdmissionDecision.ADMITTED,
        reason_summary="READY and admitted",
        operational_decision=AdmissionDecisionKind.RUN,
        block_condition=None,
        eligible_reviewer="antigravity",
        safe_executable_pair_exists=True,
        has_deterministic_eta=False,
    )
    restored = _roundtrip(record)

    assert restored.operational_decision == AdmissionDecisionKind.RUN
    assert restored.block_condition is None
    assert restored.eligible_reviewer == "antigravity"
    assert restored.safe_executable_pair_exists is True
    assert restored.has_deterministic_eta is False


def test_scheduler_decision_operational_roundtrip_wait():
    record = SchedulerDecisionRecord(
        project_id="mini-me",
        change_name="016-feature",
        decision=AdmissionDecision.REFUSED,
        reason_summary="temporary capacity",
        operational_decision=AdmissionDecisionKind.WAIT,
        block_condition=AdmissionBlockCondition.CAPACITY_EXHAUSTED,
        eligible_reviewer="antigravity",
        safe_executable_pair_exists=False,
        has_deterministic_eta=True,
        cooldown_until=utc_now() + timedelta(minutes=15),
    )
    restored = _roundtrip(record)

    assert restored.operational_decision == AdmissionDecisionKind.WAIT
    assert restored.block_condition == AdmissionBlockCondition.CAPACITY_EXHAUSTED
    assert restored.safe_executable_pair_exists is False
    assert restored.has_deterministic_eta is True
    assert restored.cooldown_until == record.cooldown_until


def test_scheduler_decision_operational_roundtrip_needs_human():
    record = SchedulerDecisionRecord(
        project_id="mini-me",
        change_name="016-feature",
        decision=AdmissionDecision.REFUSED,
        reason_summary="evidence insufficient",
        operational_decision=AdmissionDecisionKind.NEEDS_HUMAN,
        block_condition=AdmissionBlockCondition.EVIDENCE_INSUFFICIENT,
        eligible_reviewer=None,
        safe_executable_pair_exists=False,
        has_deterministic_eta=False,
    )
    restored = _roundtrip(record)

    assert restored.operational_decision == AdmissionDecisionKind.NEEDS_HUMAN
    assert restored.block_condition == AdmissionBlockCondition.EVIDENCE_INSUFFICIENT
    assert restored.eligible_reviewer is None


def test_scheduler_decision_operational_roundtrip_drain():
    record = SchedulerDecisionRecord(
        project_id="mini-me",
        change_name="016-feature",
        decision=AdmissionDecision.ADMITTED,
        reason_summary="in-flight drain continuation",
        operational_decision=AdmissionDecisionKind.DRAIN,
        block_condition=None,
        eligible_reviewer="antigravity",
        safe_executable_pair_exists=True,
        has_deterministic_eta=False,
        run_id="run-1",
    )
    restored = _roundtrip(record)

    assert restored.operational_decision == AdmissionDecisionKind.DRAIN
    assert restored.block_condition is None
    assert restored.run_id == "run-1"


def test_scheduler_decision_legacy_row_without_operational_defaults():
    """Older rows without the reserved operational payload restore safely."""
    record = SchedulerDecisionRecord(
        project_id="mini-me",
        change_name="016-feature",
        decision=AdmissionDecision.REFUSED,
        reason_summary="legacy",
        operational_decision=None,
        block_condition=None,
    )
    model = scheduler_decision_domain_to_model(record)
    # Simulate a legacy row that never persisted the operational payload.
    model.capacity_snapshot = {"mode": "RUN"}
    restored = scheduler_decision_model_to_domain(model)

    assert restored.operational_decision is None
    assert restored.block_condition is None
    assert restored.safe_executable_pair_exists is False
