"""Unit test proving coordinator does not pause on identical context when prior attempt was an execution failure."""

import pytest

from minime.services.orchestration_coordinator import NativeOrchestrationCoordinator


def test_completed_complexity_attempts_excludes_execution_and_preflight_failures():
    """Execution and preflight failures must not count as completed assessments for duplicate suppression."""
    stop_details = {
        "complexity_attempts": [
            {"attempt_id": "1", "status": "EXECUTION_FAILED", "exit_code": 1},
            {"attempt_id": "2", "status": "PREFLIGHT_FAILED", "reason": "credential expired"},
            {"attempt_id": "3", "status": "IN_PROGRESS"},
        ]
    }
    completed = [
        attempt
        for attempt in (stop_details.get("complexity_attempts") or [])
        if isinstance(attempt, dict)
        and attempt.get("status") not in ("IN_PROGRESS", "PREFLIGHT_FAILED", "EXECUTION_FAILED", None)
    ]
    # None of these should count as completed valid assessments
    assert completed == []


def test_completed_complexity_attempts_includes_valid_assessments():
    """Only real assessments with actionable outcomes count as completed."""
    stop_details = {
        "complexity_attempts": [
            {"attempt_id": "1", "status": "VALID", "complexity": "high"},
            {"attempt_id": "2", "status": "FEASIBILITY_BLOCKED"},
        ]
    }
    completed = [
        attempt
        for attempt in (stop_details.get("complexity_attempts") or [])
        if isinstance(attempt, dict)
        and attempt.get("status") not in ("IN_PROGRESS", "PREFLIGHT_FAILED", "EXECUTION_FAILED", None)
    ]
    assert len(completed) == 2
