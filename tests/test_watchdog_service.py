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


def test_only_proposal_feasibility_gate_gets_sre_diagnostic_context():
    run = _run(updated_at=datetime.now(UTC))
    run.human_gate = "NEEDS_HUMAN"
    run.stop_details = {}
    gate = {
        "gate": "proposal_feasibility", "gate_id": "gate-1",
        "question": "Original question", "options": ["Option A", "Option B"],
        "blockers": ["fallback warning"], "task_feasibility": [{"task_id": "1.1"}],
    }

    observation = WatchdogObservationService().observe_human_gate(run, gate)
    assert observation is not None
    assert observation["trigger"] == "proposal_feasibility_human_gate"
    assert observation["evidence"]["question"] == "Original question"
    assert observation["evidence"]["options"] == ["Option A", "Option B"]
    assert WatchdogObservationService().observe_human_gate(run, {**gate, "gate": "business_decision"}) is None


def test_intervention_event_write_is_idempotent():
    from minime.domain.enums import OrchestrationStage
    from minime.domain.models import OrchestrationRun
    from tests.conftest import InMemoryPersistenceUnitOfWork

    uow = InMemoryPersistenceUnitOfWork()
    run = OrchestrationRun(
        project_id="project", change_name="change", base_sha="main",
        current_stage=OrchestrationStage.IMPLEMENTING,
        current_candidate_sha="a" * 40,
    )
    assert WatchdogObservationService.record_intervention_event(
        uow, run, event_type="SRE_UNBLOCKER_ATTEMPTED",
        transition_key="sre-unblocker:test-attempt",
        evidence={"trigger": "test", "secret": "refresh_token=private"},
    ) is True
    assert WatchdogObservationService.record_intervention_event(
        uow, run, event_type="SRE_UNBLOCKER_ATTEMPTED",
        transition_key="sre-unblocker:test-attempt", evidence={"trigger": "test"},
    ) is False
    events = uow.orchestration_stage_events.list_by_run(run.run_id)
    assert len(events) == 1
    assert events[0].actor == "sre_unblocker"
    assert "private" not in str(events[0].evidence_references)


def test_improvement_feed_requires_prior_run_with_linked_intervention():
    diagnosis = {
        "project_id": "project", "run_id": "current", "root_cause": "no_recent_activity",
        "affected_component": "apply",
    }
    history = [
        {**diagnosis, "run_id": "old-unlinked", "evidence": {}},
        {**diagnosis, "run_id": "old-linked", "evidence": {
            "sre_intervention_transition_key": "sre-unblocker:attempt:123",
        }},
    ]
    repo = SimpleNamespace(list_diagnoses=lambda **_kwargs: history)
    assert WatchdogObservationService.has_prior_sre_pattern(repo, diagnosis) is True
    assert WatchdogObservationService.has_prior_sre_pattern(
        SimpleNamespace(list_diagnoses=lambda **_kwargs: history[:1]), diagnosis
    ) is False


def test_watchdog_suggestion_payload_exposes_source_intervention_event():
    from minime.services.watchdog_repository import PostgresWatchdogRepository

    row = SimpleNamespace(
        id="diagnosis-1", project_id="project", run_id="run-1", change_name="change",
        stage="APPLY", candidate_sha="a" * 40, candidate_generation=1,
        status="OBSERVED", root_cause="no_recent_activity", affected_component="apply",
        summary="Observed stall", evidence={
            "sre_intervention_transition_key": "sre-unblocker:attempt:123",
        }, action=None, action_result={}, improvement_suggestion="Improve prevention",
        suggestion_status="pending", created_at=datetime.now(UTC), updated_at=datetime.now(UTC),
    )
    payload = PostgresWatchdogRepository._diagnosis_payload(row)
    assert payload["source_intervention_transition_key"] == "sre-unblocker:attempt:123"


@pytest.mark.asyncio
async def test_unavailable_semantic_model_is_recorded_without_changing_observed_playbook(tmp_path, monkeypatch):
    from minime.config import CliInvocationProfile

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
        lambda *_args, **_kwargs: CliInvocationProfile(
            provider="codex", role="thinking", executable="codex", args=("exec", "-"),
            prompt_transport="stdin",
        ),
    )

    class UnavailableRunner:
        def __init__(self, **_kwargs):
            pass

        async def run(self, **_kwargs):
            assert "minime-sre-unblocker" in _kwargs["prompt_context"]
            assert "Original OpenSpec question" in _kwargs["prompt_context"]
            assert '"Original option A"' in _kwargs["prompt_context"]
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
        human_payload={
            "question": "Original OpenSpec question",
            "options": ["Original option A", "Original option B"],
        },
    )

    assert result["evidence"]["semantic_model_status"] == "UNAVAILABLE"
    assert result["evidence"]["semantic_model_provider_id"] == "provider"
    assert result["evidence"]["semantic_model_harness_id"] == "codex"
    assert result["evidence"]["semantic_model_id"] == "model"
    assert result["action_result"] == {"status": "NOT_ATTEMPTED"}
    assert result["candidate_sha"] == "a" * 40
