from datetime import UTC, datetime

from minime.services.watchdog_repository import PostgresWatchdogRepository


class _Session:
    def __init__(self):
        self.row = None

    def scalar(self, _statement):
        return self.row

    def add(self, row):
        self.row = row

    def flush(self):
        if self.row.created_at is None:
            self.row.created_at = datetime.now(UTC)
        self.row.updated_at = self.row.created_at


def _diagnosis():
    return {
        "project_id": "project",
        "run_id": "run",
        "change_name": "change",
        "stage": "APPLY",
        "candidate_sha": "a" * 40,
        "candidate_generation": 1,
        "status": "OBSERVED",
        "root_cause": "no_recent_activity",
        "affected_component": "apply",
        "summary": "Observed stall",
        "evidence": {
            "event_identity": "event-1",
            "sre_intervention_transition_key": "watchdog:attempt-1",
        },
        "action": None,
        "action_result": {"status": "NOT_ATTEMPTED"},
        "improvement_suggestion": "Review activity signals",
    }


def test_save_diagnosis_is_idempotent_and_preserves_event_link():
    repository = PostgresWatchdogRepository(_Session())
    first = repository.save_diagnosis(_diagnosis())
    second = repository.save_diagnosis(_diagnosis())

    assert first["id"] == second["id"]
    assert second["event_identity"] == "event-1"
    assert second["source_intervention_transition_key"] == "watchdog:attempt-1"
    assert second["suggestion_status"] == "pending"
