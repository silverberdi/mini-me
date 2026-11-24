from __future__ import annotations

from types import SimpleNamespace

import pytest

from minime.api.app import request_run_watchdog_diagnosis


@pytest.mark.asyncio
async def test_manual_watchdog_recovery_is_accepted_through_scheduler_wakeup(monkeypatch):
    import minime.services.watchdog_service as watchdog_module

    run = SimpleNamespace(
        run_id="run-1",
        project_id="project-1",
        is_active=True,
        active_job_id="job-1",
    )
    observation = {
        "id": "diagnosis-1",
        "run_id": "run-1",
        "project_id": "project-1",
        "stage": "IMPLEMENTING",
        "candidate_sha": "a" * 40,
        "candidate_generation": 1,
        "status": "OBSERVED",
    }
    monkeypatch.setattr(
        watchdog_module.WatchdogObservationService,
        "observe",
        lambda *_args, **_kwargs: dict(observation),
    )

    async def add_semantic_diagnosis(self, result, _settings, *, worktree_path):
        assert worktree_path == "/managed/worktree"
        return result

    monkeypatch.setattr(
        watchdog_module.WatchdogObservationService,
        "add_semantic_diagnosis",
        add_semantic_diagnosis,
    )

    executed: list[tuple[object, dict[str, object]]] = []

    class Session:
        def execute(self, statement, parameters):
            executed.append((statement, parameters))

    class WatchdogRepository:
        def get_settings(self):
            return {
                "mode": "mechanical_remediation",
                "inactivity_threshold_minutes": 15,
            }

        def get_by_run_stage_generation(self, *_args):
            return None

        def save_diagnosis(self, value):
            return {**value, "id": "diagnosis-1"}

    uow = SimpleNamespace(
        session=Session(),
        orchestration_runs=SimpleNamespace(get_by_id=lambda _run_id: run),
        orchestration_stage_events=SimpleNamespace(list_by_run=lambda _run_id: []),
        job_logs=SimpleNamespace(list_by_job=lambda *_args, **_kwargs: []),
        watchdog=WatchdogRepository(),
        orchestration_worktree_ownerships=SimpleNamespace(
            get_by_job_id=lambda _job_id: SimpleNamespace(
                canonical_worktree_path="/managed/worktree"
            )
        ),
        commit=lambda: None,
    )

    response = await request_run_watchdog_diagnosis(
        "project-1", "run-1", object(), uow
    )

    assert response["status"] == "accepted"
    assert response["result"] == "recovery_queued"
    assert response["diagnosis"]["candidate_sha"] == "a" * 40
    assert len(executed) == 1
    assert executed[0][1]["channel"] == "minime_scheduler_wakeup"
    assert '"reason":"watchdog_diagnosis"' in executed[0][1]["payload"]
