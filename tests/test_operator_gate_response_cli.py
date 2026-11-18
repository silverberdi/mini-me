from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from minime.api.app import ProjectRequestRunPayload, prepare_gate_response
from minime.cli import main as cli_main
from minime.domain.enums import OrchestrationStage


class MemoryActionRepository:
    def __init__(self):
        self.actions = {}

    def get_by_request_id(self, request_id):
        return self.actions.get(request_id)

    def save(self, action):
        self.actions[action.action_request_id] = action


def make_uow(runs):
    actions = MemoryActionRepository()
    uow = SimpleNamespace(
        orchestration_runs=SimpleNamespace(
            list_runs=lambda **_: runs,
            get_for_update=lambda run_id: next(
                (run for run in runs if run.run_id == run_id), None
            ),
        ),
        operator_actions=actions,
        commits=0,
    )
    uow.commit = lambda: setattr(uow, "commits", uow.commits + 1)
    return uow, actions


def active_gated_run(run_id="run-1"):
    return SimpleNamespace(
        run_id=run_id,
        project_id="project-1",
        change_name="change-1",
        is_active=True,
        current_stage=OrchestrationStage.VALIDATING,
        stop_outcome=None,
        stop_details={
            "human_payload": {
                "gate_id": "gate-1",
                "gate": "proposal_feasibility",
                "question": "Choose how to proceed",
                "options": ["Update", "Cancel"],
            }
        },
    )


def test_cli_gate_response_uses_durable_idempotent_web_path():
    run = active_gated_run()
    uow, actions = make_uow([run])

    first = ProjectRequestRunPayload(operator_response="Continue with native Update")
    active, accepted, early = prepare_gate_response(
        uow, "project-1", first, require_active_gate=True
    )
    assert early is None
    assert active == [run]
    assert first.target_run_id == run.run_id
    assert first.operator_clarification == "Continue with native Update"
    assert accepted.action_type.value == "RESOLVE_GATE"
    assert accepted.parameters_json["accepted_response"] == "Continue with native Update"

    repeated = ProjectRequestRunPayload(operator_response="Continue with native Update")
    _, duplicate, early = prepare_gate_response(
        uow, "project-1", repeated, require_active_gate=True
    )
    assert early is None
    assert duplicate.action_request_id == accepted.action_request_id
    assert len(actions.actions) == 1
    assert uow.commits == 1


def test_cli_gate_response_rejects_absent_or_ambiguous_gate():
    uow, actions = make_uow([])
    with pytest.raises(HTTPException) as absent:
        prepare_gate_response(
            uow,
            "project-1",
            ProjectRequestRunPayload(operator_response="Continue"),
            require_active_gate=True,
        )
    assert absent.value.status_code == 409
    assert not actions.actions

    uow, actions = make_uow([active_gated_run("run-1"), active_gated_run("run-2")])
    with pytest.raises(HTTPException) as ambiguous:
        prepare_gate_response(
            uow,
            "project-1",
            ProjectRequestRunPayload(operator_response="Continue"),
            require_active_gate=True,
        )
    assert ambiguous.value.status_code == 409
    assert not actions.actions

    run = active_gated_run()
    uow, actions = make_uow([run])
    with pytest.raises(HTTPException) as stale:
        prepare_gate_response(
            uow,
            "project-1",
            ProjectRequestRunPayload(
                target_run_id="stale-run",
                operator_response="Continue",
            ),
            require_active_gate=True,
        )
    assert stale.value.status_code == 409
    assert not actions.actions


def test_cli_gate_response_rejects_when_active_run_has_no_current_gate():
    run = active_gated_run()
    run.stop_details = {}
    uow, actions = make_uow([run])

    with pytest.raises(HTTPException) as missing_gate:
        prepare_gate_response(
            uow,
            "project-1",
            ProjectRequestRunPayload(operator_response="Continue"),
            require_active_gate=True,
        )
    assert missing_gate.value.status_code == 409
    assert not actions.actions


def test_request_run_cli_passes_the_accepted_current_gate_action(monkeypatch):
    run = active_gated_run()
    uow, _ = make_uow([run])
    project = SimpleNamespace(agent_profiles={}, repository="silverberdi/example")
    uow.projects = SimpleNamespace(get_by_id=lambda _: project)
    uow.project_managed_repository_bindings = SimpleNamespace(
        get_by_project_id=lambda _: SimpleNamespace(managed_repository_root="/tmp/example")
    )
    seen = {}

    @contextmanager
    def session():
        yield object()

    class FakeCoordinator:
        async def execute_project_request(self, **kwargs):
            seen["calls"] = seen.get("calls", 0) + 1
            seen.update(kwargs)
            return SimpleNamespace(
                status="HUMAN_REQUIRED",
                run_id=run.run_id,
                current_stage=OrchestrationStage.VALIDATING,
                message="Still waiting at the current gate",
                pr1_url=None,
                pr2_url=None,
                human_payload=run.stop_details["human_payload"],
            )

    class FakeRunner:
        @staticmethod
        def provider_for_role(role):
            return role

    monkeypatch.setattr(cli_main.db_manager, "session", session)
    monkeypatch.setattr(cli_main, "PostgresPersistenceUnitOfWork", lambda _: uow)
    monkeypatch.setattr("minime.adapters.github.GitHubAdapter", lambda: object())
    monkeypatch.setattr("minime.services.worktree_manager.WorktreeManager", lambda **_: object())
    monkeypatch.setattr(
        "minime.services.capacity_lifecycle_service.CapacityLifecycleService",
        lambda _: object(),
    )
    monkeypatch.setattr(
        "minime.services.agent_runner.CliAgentRunner.for_project_profiles",
        lambda *_, **__: FakeRunner(),
    )
    monkeypatch.setattr(
        "minime.services.orchestration_coordinator.NativeOrchestrationCoordinator",
        lambda **_: FakeCoordinator(),
    )

    cli_main.request_run_cmd(
        "project-1",
        operator_ack=False,
        operator_response="Continue from this gate",
        explore_recovery_authorization_id=None,
        propose_recovery_authorization_id=None,
        json_output=False,
    )

    assert seen["target_run_id"] == run.run_id
    assert seen["operator_clarification"] == "Continue from this gate"
    assert seen["operator_action_id"] in uow.operator_actions.actions
    assert uow.operator_actions.actions[seen["operator_action_id"]].status == "COMPLETED"
    assert uow.operator_actions.actions[seen["operator_action_id"]].result_payload_json["run_id"] == run.run_id

    cli_main.request_run_cmd(
        "project-1",
        operator_ack=False,
        operator_response="Continue from this gate",
        explore_recovery_authorization_id=None,
        propose_recovery_authorization_id=None,
        json_output=False,
    )
    assert seen["calls"] == 1
