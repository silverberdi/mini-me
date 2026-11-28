from datetime import UTC, datetime

from minime.services.watchdog_repository import PostgresWatchdogRepository


class _Session:
    def __init__(self):
        self.rows = []

    def scalar(self, statement):
        event_identity = statement.compile().params.get("event_identity_1")
        for row in self.rows:
            if event_identity is None or row.event_identity == event_identity:
                return row
        return None

    def add(self, row):
        self.rows.append(row)

    def flush(self):
        for row in self.rows:
            if row.created_at is None:
                row.created_at = datetime.now(UTC)
            row.updated_at = row.created_at


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


def test_distinct_events_share_candidate_without_colliding():
    repository = PostgresWatchdogRepository(_Session())
    first = repository.save_diagnosis(_diagnosis())
    second = repository.save_diagnosis({
        **_diagnosis(),
        "evidence": {
            "event_identity": "event-2",
            "sre_intervention_transition_key": "watchdog:attempt-2",
        },
    })

    assert second["id"] != first["id"]
    assert second["event_identity"] == "event-2"
