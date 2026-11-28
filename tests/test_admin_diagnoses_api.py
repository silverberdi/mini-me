from types import SimpleNamespace

from minime.api.app import list_watchdog_suggestions


def test_admin_diagnoses_returns_pending_persisted_suggestions():
    record = {
        "id": "diagnosis-1",
        "project_id": "project",
        "run_id": "run-1",
        "root_cause": "no_recent_activity",
        "affected_component": "apply",
        "improvement_suggestion": "Review activity signals",
        "suggestion_status": "pending",
        "evidence": {"event_identity": "event-1"},
    }
    uow = SimpleNamespace(
        watchdog=SimpleNamespace(
            list_diagnoses=lambda **kwargs: [record]
            if kwargs["suggestion_status"] == "pending" and kwargs["suggestions_only"]
            else []
        )
    )

    response = list_watchdog_suggestions(object(), uow, status_filter="pending")

    assert response["items"] == [record]
    assert response["items"][0]["suggestion_status"] == "pending"
    assert response["recurrences"] == {"no_recent_activity:apply": 1}
