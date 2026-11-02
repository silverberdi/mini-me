from types import SimpleNamespace

from tests.conftest import InMemoryPersistenceUnitOfWork

from minime.api.app import _should_publish_run_notification
from minime.domain.enums import OrchestrationStage
from minime.domain.models import OrchestrationRun


def _result(message: str):
    return SimpleNamespace(
        run_id="run-proposal-review",
        status="PAUSED",
        current_stage=OrchestrationStage.PROPOSAL_REVIEW,
        message=message,
        human_payload=None,
    )


def test_paused_proposal_review_notification_is_durable_and_idempotent():
    uow = InMemoryPersistenceUnitOfWork()
    uow.orchestration_runs.save(
        OrchestrationRun(
            project_id="mini-me",
            run_id="run-proposal-review",
            change_name="f12-change",
            base_sha="base-sha",
            current_stage=OrchestrationStage.PROPOSAL_REVIEW,
            stop_details={
                "proposal_review": {"attempt_id": "review-1", "status": "changes_required"}
            },
        )
    )

    assert _should_publish_run_notification(uow, _result("Requested changes")) is True
    assert _should_publish_run_notification(uow, _result("Requested changes")) is False

    # A new review attempt is a new observable outcome even if the stage/status
    # remain paused.
    run = uow.orchestration_runs.get_by_id("run-proposal-review")
    run.stop_details["proposal_review"]["attempt_id"] = "review-2"
    uow.orchestration_runs.save(run)
    assert _should_publish_run_notification(uow, _result("Requested changes")) is True
