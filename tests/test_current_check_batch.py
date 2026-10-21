from datetime import UTC, datetime, timedelta

from minime.domain.enums import OrchestrationStage
from minime.domain.models import CheckResult, Job, OrchestrationRun, Project
from minime.services.current_check_batch import validate_current_checks_batch


def _state(checks: list[dict], results: list[CheckResult]):
    job = Job(
        job_id="job-check-batch",
        project_id="project-check-batch",
        change_name="candidate-review",
        implementer_role="codex",
        candidate_sha="candidate-sha",
    )
    run = OrchestrationRun(
        run_id="run-check-batch",
        project_id=job.project_id,
        change_name=job.change_name,
        base_sha="base-sha",
        active_job_id=job.job_id,
        current_stage=OrchestrationStage.COMPLEMENTARY_REVIEW,
        current_generation=3,
        current_candidate_sha=job.candidate_sha,
    )
    project = Project(
        project_id=job.project_id,
        display_name="check batch fixture",
        repository="owner/check-batch",
        checks=checks,
    )
    return job, run, project


def _result(
    name: str,
    command: str,
    exit_code: int,
    timestamp: datetime,
    *,
    sha: str = "candidate-sha",
    generation: int = 3,
):
    return CheckResult(
        job_id="job-check-batch",
        check_name=name,
        command=command,
        exit_code=exit_code,
        duration_ms=10,
        output_snippet="fixture evidence",
        candidate_sha=sha,
        candidate_generation=generation,
        created_at=timestamp,
    )


def test_latest_complete_passing_batch_wins_and_preserves_old_failure():
    now = datetime.now(UTC)
    checks = [{"name": "unit", "command": "pytest -q"}]
    historical_failure = _result("unit", "pytest -q", 1, now - timedelta(days=1))
    latest_pass = _result("unit", "pytest -q", 0, now)
    job, run, project = _state(checks, [historical_failure, latest_pass])

    valid, reason, selected = validate_current_checks_batch(
        check_results=[historical_failure, latest_pass],
        job=job,
        run=run,
        project=project,
        require_configured_checks=True,
    )

    assert valid and reason is None
    assert selected == [latest_pass]
    assert historical_failure.exit_code == 1


def test_latest_batch_rejects_missing_duplicate_wrong_command_and_wrong_identity():
    now = datetime.now(UTC)
    checks = [
        {"name": "unit", "command": "pytest -q"},
        {"name": "lint", "command": "ruff check ."},
    ]
    job, run, project = _state(checks, [])
    adversarial_batches = [
        [_result("unit", "pytest -q", 0, now)],
        [
            _result("unit", "pytest -q", 0, now),
            _result("unit", "pytest -q", 0, now + timedelta(milliseconds=1)),
        ],
        [
            _result("unit", "pytest -q", 0, now),
            _result("lint", "ruff format .", 0, now + timedelta(milliseconds=1)),
        ],
        [
            _result("unit", "pytest -q", 0, now, sha="other-sha"),
            _result("lint", "ruff check .", 0, now + timedelta(milliseconds=1)),
        ],
        [
            _result("unit", "pytest -q", 0, now),
            _result("lint", "ruff check .", 0, now, generation=2),
        ],
    ]

    for batch in adversarial_batches:
        valid, reason, selected = validate_current_checks_batch(
            check_results=batch,
            job=job,
            run=run,
            project=project,
            require_configured_checks=True,
        )
        assert not valid and reason and not selected


def test_latest_complete_batch_rejects_new_failure_and_empty_exceptional_config():
    now = datetime.now(UTC)
    checks = [{"name": "unit", "command": "pytest -q"}]
    old_pass = _result("unit", "pytest -q", 0, now - timedelta(seconds=5))
    latest_failure = _result("unit", "pytest -q", 1, now)
    job, run, project = _state(checks, [old_pass, latest_failure])

    valid, _, _ = validate_current_checks_batch(
        check_results=[old_pass, latest_failure],
        job=job,
        run=run,
        project=project,
        require_configured_checks=True,
    )
    assert not valid

    no_checks_project = project.model_copy(update={"checks": []})
    ordinary_valid, _, _ = validate_current_checks_batch(
        check_results=[], job=job, run=run, project=no_checks_project
    )
    exceptional_valid, reason, _ = validate_current_checks_batch(
        check_results=[],
        job=job,
        run=run,
        project=no_checks_project,
        require_configured_checks=True,
    )
    assert ordinary_valid
    assert not exceptional_valid and reason
