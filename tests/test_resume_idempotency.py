from minime.domain.models import OrchestrationRun
from minime.services.orchestration_service import OrchestrationService


def test_resume_uses_deterministic_key_and_does_not_duplicate_event(in_memory_uow):
    run = OrchestrationRun(run_id="run-1", project_id="p", change_name="c", base_sha="base")
    in_memory_uow.orchestration_runs.save(run)
    service = object.__new__(OrchestrationService)
    service.uow = in_memory_uow
    service.drive_coordinator = lambda run_id, project_root=None: in_memory_uow.orchestration_runs.get_by_id(run_id)

    service.resume("run-1")
    service.resume("run-1")

    events = in_memory_uow.orchestration_stage_events.list_by_run("run-1")
    assert len(events) == 1
    assert events[0].transition_key == "run-1:RESUME:ADMITTED:1"
