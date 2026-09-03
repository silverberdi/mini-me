"""Tests for project-level provider efficiency telemetry summaries."""

from minime.domain.models import Project, ProviderEfficiencyMetrics
from minime.services.efficiency_telemetry_service import EfficiencyTelemetryService
from minime.services.status_service import StatusService


def test_project_efficiency_summary_returns_zero_values_without_runs(in_memory_uow):
    summary = EfficiencyTelemetryService(in_memory_uow).get_project_efficiency_summary("project-1")

    assert summary == {
        "total_runs": 0,
        "total_productive_attempts": 0,
        "total_no_progress_attempts": 0,
        "productive_attempt_ratio": 0.0,
        "total_same_sha_suppressed": 0,
        "total_corrective_retries": 0,
        "total_reassignments": 0,
        "average_self_hosting_percentage": 0.0,
        "provider_breakdown": {},
    }


def test_project_efficiency_summary_aggregates_runs_and_providers(in_memory_uow):
    in_memory_uow.provider_efficiency.save(
        ProviderEfficiencyMetrics(
            metrics_id="metrics-1",
            run_id="run-1",
            project_id="project-1",
            change_name="change-1",
            productive_attempt_count=2,
            no_progress_attempt_count=1,
            same_sha_retry_suppressed_count=1,
            corrective_retry_count=1,
            reassignments_count=2,
            self_hosting_percentage=100.0,
            attempts_by_provider={"codex": 2, "antigravity": 1},
            duration_by_provider_ms={"codex": 1200, "antigravity": 300},
        )
    )
    in_memory_uow.provider_efficiency.save(
        ProviderEfficiencyMetrics(
            metrics_id="metrics-2",
            run_id="run-2",
            project_id="project-1",
            change_name="change-2",
            productive_attempt_count=1,
            no_progress_attempt_count=1,
            same_sha_retry_suppressed_count=2,
            corrective_retry_count=3,
            reassignments_count=1,
            self_hosting_percentage=80.0,
            attempts_by_provider={"codex": 1, "deepseek": 1},
            duration_by_provider_ms={"codex": 500, "deepseek": 700},
        )
    )

    summary = EfficiencyTelemetryService(in_memory_uow).get_project_efficiency_summary("project-1")

    assert summary["total_runs"] == 2
    assert summary["total_productive_attempts"] == 3
    assert summary["total_no_progress_attempts"] == 2
    assert summary["productive_attempt_ratio"] == 60.0
    assert summary["total_same_sha_suppressed"] == 3
    assert summary["total_corrective_retries"] == 4
    assert summary["total_reassignments"] == 3
    assert summary["average_self_hosting_percentage"] == 90.0
    assert summary["provider_breakdown"] == {
        "codex": {"attempts": 3, "duration_ms": 1700},
        "antigravity": {"attempts": 1, "duration_ms": 300},
        "deepseek": {"attempts": 1, "duration_ms": 700},
    }


def test_status_efficiency_summary_defaults_to_active_registered_project(in_memory_uow):
    in_memory_uow.projects.save(
        Project(
            project_id="project-1",
            display_name="mini me",
            repository="owner/mini-me",
        )
    )
    in_memory_uow.provider_efficiency.save(
        ProviderEfficiencyMetrics(
            metrics_id="metrics-1",
            run_id="run-1",
            project_id="project-1",
            change_name="change-1",
            productive_attempt_count=1,
        )
    )

    summary = StatusService(in_memory_uow).get_efficiency_summary()

    assert summary["total_runs"] == 1
    assert summary["total_productive_attempts"] == 1
