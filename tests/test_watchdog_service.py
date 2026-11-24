from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

import minime.config as config_module
import minime.services.agent_runner as agent_runner_module
from minime.services import watchdog_service
from minime.services.watchdog_service import WatchdogObservationService


def _run(*, updated_at):
    return SimpleNamespace(
        run_id="run-1",
        project_id="boxio",
        change_name="change-1",
        current_stage="APPLY",
        current_generation=2,
        current_candidate_sha="a" * 40,
        is_active=True,
        human_gate=None,
        stop_details={},
        updated_at=updated_at,
    )


def _event(event_type, evidence, created_at, *, from_stage="APPLY"):
    return SimpleNamespace(
        event_type=event_type,
        evidence_references=evidence,
        created_at=created_at,
        from_stage=from_stage,
    )


def test_recent_durable_activity_does_not_create_watchdog_observation():
    now = datetime.now(UTC)
    events = [_event("STAGE_INVOCATION_STARTED", {}, now - timedelta(seconds=20))]

    result = WatchdogObservationService().observe(
        _run(updated_at=now), events, threshold_minutes=15, now=now
    )

    assert result is None


def test_recent_run_update_prevents_stale_prior_stage_events_from_marking_stall():
    now = datetime.now(UTC)
    old = now - timedelta(minutes=30)
    events = [_event("STAGE_INVOCATION_STARTED", {}, old)]

    result = WatchdogObservationService().observe(
        _run(updated_at=now), events, threshold_minutes=15, now=now
    )

    assert result is None


def test_ambiguous_invocations_wait_for_inactivity_threshold():
    now = datetime.now(UTC)
    started = now - timedelta(seconds=10)
    events = [
        _event("STAGE_INVOCATION_STARTED", {"attempt_id": "a1"}, started),
        _event("STAGE_INVOCATION_STARTED", {"attempt_id": "a2"}, started),
    ]

    result = WatchdogObservationService().observe(
        _run(updated_at=started), events, threshold_minutes=15, now=now
    )

    assert result is None


def test_stale_run_produces_candidate_bound_read_only_observation():
    now = datetime.now(UTC)
    old = now - timedelta(minutes=20)
    events = [_event("STAGE_INVOCATION_STARTED", {"candidate": {"stage": "APPLY"}}, old)]

    result = WatchdogObservationService().observe(
        _run(updated_at=old), events, threshold_minutes=15, now=now
    )

    assert result is not None
    assert result["status"] == "OBSERVED"
    assert result["root_cause"] == "no_recent_activity"
    assert result["candidate_sha"] == "a" * 40
    assert result["candidate_generation"] == 2
    assert result["action"] is None
    assert result["action_result"] == {"status": "NOT_ATTEMPTED"}


def test_proven_absent_child_is_detected_before_threshold(monkeypatch):
    now = datetime.now(UTC)
    start = now - timedelta(seconds=5)
    events = [
        _event(
            "STAGE_INVOCATION_STARTED",
            {"attempt_id": "a1", "started_at": start.isoformat(), "candidate": {"stage": "APPLY"}},
            start,
        ),
        _event(
            "STAGE_INVOCATION_PROCESS_STARTED",
            {"attempt_id": "a1", "process_identity": {"pid": 123}},
            start,
        ),
    ]
    monkeypatch.setattr(watchdog_service, "process_identity_state", lambda _: "GONE")

    result = WatchdogObservationService().observe(
        _run(updated_at=start), events, threshold_minutes=15, now=now
    )

    assert result is not None
    assert result["root_cause"] == "orphaned_stage_process"
    assert result["evidence"]["process_absence_proven"] is True


def test_human_gate_is_not_reclassified_as_watchdog_stall():
    now = datetime.now(UTC)
    run = _run(updated_at=now - timedelta(hours=1))
    run.human_gate = "NEEDS_HUMAN"

    assert WatchdogObservationService().observe(run, [], now=now) is None


@pytest.mark.asyncio
async def test_unavailable_semantic_model_is_recorded_without_changing_observed_playbook(tmp_path, monkeypatch):
    observation = {
        "project_id": "boxio",
        "run_id": "run-1",
        "change_name": "change-1",
        "stage": "APPLY",
        "candidate_sha": "a" * 40,
        "root_cause": "orphaned_stage_process",
        "evidence": {"process_absence_proven": True},
        "action": None,
        "action_result": {"status": "NOT_ATTEMPTED"},
    }
    monkeypatch.setattr(config_module, "load_config", lambda: SimpleNamespace())
    monkeypatch.setattr(
        config_module,
        "resolve_cli_invocation",
        lambda *_args, **_kwargs: SimpleNamespace(),
    )

    class UnavailableRunner:
        def __init__(self, **_kwargs):
            pass

        async def run(self, **_kwargs):
            return SimpleNamespace(
                exit_code=1,
                final_response_status="FAILED",
                final_response=None,
            )

    monkeypatch.setattr(agent_runner_module, "CliAgentRunner", UnavailableRunner)
    result = await WatchdogObservationService().add_semantic_diagnosis(
        observation,
        {"provider_id": "provider", "harness_id": "codex", "canonical_model_id": "model"},
        worktree_path=tmp_path,
    )

    assert result["evidence"]["semantic_model_status"] == "UNAVAILABLE"
    assert result["action_result"] == {"status": "NOT_ATTEMPTED"}
    assert result["candidate_sha"] == "a" * 40
