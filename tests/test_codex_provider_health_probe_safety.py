from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from minime.adapters.provider_adapter import CodexProviderAdapter
from minime.domain.enums import (
    AdmissionBlockCondition,
    AdmissionDecisionKind,
    ProviderHealthStatus,
    ProviderResultClass,
    QueuePriority,
    ReadinessState,
)
from minime.domain.models import Project, ProjectBinding, WorkQueueItem
from minime.services.provider_health_service import ProviderHealthService
from minime.services.scheduler_service import SchedulerService


@pytest.mark.asyncio
async def test_codex_adapter_probe_includes_skip_git_repo_check():
    """Verify CodexProviderAdapter probe availability includes --skip-git-repo-check flag."""
    adapter = CodexProviderAdapter(executable="codex")

    mock_proc = AsyncMock()
    mock_proc.communicate = AsyncMock(return_value=(b"echo probe", b""))
    mock_proc.returncode = 0

    with (
        patch("shutil.which", return_value="/usr/local/bin/codex"),
        patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec,
    ):
        res = await adapter.probe_availability()
        assert res is True
        mock_exec.assert_called_once()
        args = mock_exec.call_args[0]
        assert "--skip-git-repo-check" in args
        assert "--ephemeral" in args


def test_codex_adapter_extracts_auth_error_signal():
    """Verify HTTP 401, token_expired, and login-required errors are extracted as AUTH_ERROR."""
    adapter = CodexProviderAdapter(executable="codex")

    token_expired_out = (
        "2026-09-18T19:26:06.428386Z ERROR codex_models_manager::manager: "
        "failed to refresh available models: unexpected status 401 Unauthorized: "
        "Provided authentication token is expired. Please try signing in again."
    )

    signal = adapter.extract_capacity_signal(token_expired_out, exit_code=1)
    assert signal is not None
    assert signal.result_class == ProviderResultClass.AUTH_ERROR
    assert "authentication token is expired" in signal.summary.lower()

    untrusted_dir_out = "Not inside a trusted directory and --skip-git-repo-check was not specified."
    signal_untrusted = adapter.extract_capacity_signal(untrusted_dir_out, exit_code=1)
    assert signal_untrusted is None


@pytest.mark.asyncio
async def test_expensive_probe_gated_when_no_ready_work(in_memory_uow):
    """Verify expensive background probes are skipped when no actionable READY work exists."""
    svc = ProviderHealthService(uow=in_memory_uow)

    # Set codex to TEMPORARILY_UNAVAILABLE
    in_memory_uow.provider_health.update_health(
        provider="codex",
        status=ProviderHealthStatus.TEMPORARILY_UNAVAILABLE.value,
        result_class=ProviderResultClass.RATE_LIMIT.value,
        error_summary="Rate limit exceeded",
    )

    # Work queue has only NOT_READY work
    in_memory_uow.work_queue.save(
        WorkQueueItem(
            project_id="mini-me",
            change_name="010-not-ready-task",
            github_issue_number=10,
            priority=QueuePriority.HIGH,
            readiness_state=ReadinessState.NOT_READY,
            admission_eligible=False,
        )
    )

    with patch(
        "minime.services.provider_health_service.get_provider_adapter"
    ) as mock_get_adapter:
        mock_adapter = MagicMock()
        mock_adapter.check_cli_present = AsyncMock(return_value=True)
        mock_adapter.check_auth_ready = AsyncMock(return_value=True)
        mock_adapter.probe_is_expensive = True
        mock_adapter.probe_verifies_capacity = True
        mock_adapter.probe_availability = AsyncMock(return_value=True)
        mock_get_adapter.return_value = mock_adapter

        probed = await svc.check_and_probe_provider("codex")

        # Must return False without executing expensive probe
        assert probed is False
        mock_adapter.probe_availability.assert_not_called()


@pytest.mark.asyncio
async def test_expensive_probe_runs_when_actionable_ready_work_exists(in_memory_uow):
    """Verify expensive probe is triggered when an actionable READY work item waits on codex."""
    svc = ProviderHealthService(uow=in_memory_uow)

    # Register project with implementer codex
    in_memory_uow.projects.save(
        Project(
            project_id="mini-me",
            display_name="mini me",
            repository="silverberdi/mini-me",
            base_branch="main",
            implementer="codex",
            reviewer="antigravity",
        )
    )

    in_memory_uow.provider_health.update_health(
        provider="codex",
        status=ProviderHealthStatus.TEMPORARILY_UNAVAILABLE.value,
        result_class=ProviderResultClass.RATE_LIMIT.value,
        error_summary="Rate limit exceeded",
    )

    # Save actionable READY item
    in_memory_uow.work_queue.save(
        WorkQueueItem(
            project_id="mini-me",
            change_name="001-ready-task",
            github_issue_number=1,
            priority=QueuePriority.HIGH,
            readiness_state=ReadinessState.READY,
            admission_eligible=True,
        )
    )

    with patch(
        "minime.services.provider_health_service.get_provider_adapter"
    ) as mock_get_adapter:
        mock_adapter = MagicMock()
        mock_adapter.check_cli_present = AsyncMock(return_value=True)
        mock_adapter.check_auth_ready = AsyncMock(return_value=True)
        mock_adapter.probe_is_expensive = True
        mock_adapter.probe_verifies_capacity = True
        mock_adapter.probe_availability = AsyncMock(return_value=True)
        mock_adapter.extract_capacity_signal = MagicMock(return_value=None)
        mock_get_adapter.return_value = mock_adapter

        probed = await svc.check_and_probe_provider("codex")

        assert probed is True
        mock_adapter.probe_availability.assert_called_once()


@pytest.mark.asyncio
async def test_auth_401_transitions_health_to_auth_required(in_memory_uow):
    """Verify HTTP 401 / token_expired transitions health to AUTH_REQUIRED and yields NEEDS_HUMAN."""
    svc = ProviderHealthService(uow=in_memory_uow)

    in_memory_uow.projects.save(
        Project(
            project_id="mini-me",
            display_name="mini me",
            repository="silverberdi/mini-me",
            base_branch="main",
            implementer="codex",
            reviewer="antigravity",
        )
    )

    in_memory_uow.bindings.save(
        ProjectBinding(
            project_id="mini-me",
            repository="silverberdi/mini-me",
            github_issue_number=1,
            openspec_change_name="001-ready-task",
            is_valid=True,
        )
    )

    in_memory_uow.provider_health.update_health(
        provider="codex",
        status=ProviderHealthStatus.TEMPORARILY_UNAVAILABLE.value,
        result_class=ProviderResultClass.RATE_LIMIT.value,
        error_summary="Rate limit exceeded",
    )

    in_memory_uow.work_queue.save(
        WorkQueueItem(
            project_id="mini-me",
            change_name="001-ready-task",
            github_issue_number=1,
            priority=QueuePriority.HIGH,
            readiness_state=ReadinessState.READY,
            admission_eligible=True,
        )
    )

    with patch(
        "minime.services.provider_health_service.get_provider_adapter"
    ) as mock_get_adapter:
        mock_adapter = MagicMock()
        mock_adapter.check_cli_present = AsyncMock(return_value=True)
        mock_adapter.check_auth_ready = AsyncMock(return_value=True)
        mock_adapter.probe_is_expensive = True
        mock_adapter.probe_verifies_capacity = True
        mock_adapter.probe_availability = AsyncMock(return_value=False)
        mock_adapter._last_probe_output = (
            "HTTP 401 Unauthorized: Provided authentication token is expired. Please try signing in again."
        )
        mock_adapter._last_exit_code = 1
        mock_adapter.extract_capacity_signal = CodexProviderAdapter.extract_capacity_signal.__get__(
            mock_adapter
        )
        mock_get_adapter.return_value = mock_adapter

        probed = await svc.check_and_probe_provider("codex")
        assert probed is False

    health = svc.get_existing_health("codex")
    assert health is not None
    assert health.status == ProviderHealthStatus.AUTH_REQUIRED
    assert health.last_result_class == ProviderResultClass.AUTH_ERROR

    # Verify Scheduler admission yields NEEDS_HUMAN with block_condition AUTH_REQUIRED
    mock_readiness = MagicMock()
    mock_readiness.evaluate_change_readiness.return_value = MagicMock(
        is_ready=True, unmet_reasons=[]
    )
    scheduler = SchedulerService(
        uow=in_memory_uow,
        provider_health_service=svc,
        readiness_service=mock_readiness,
    )
    eval_res = scheduler.evaluate_admission("mini-me", "001-ready-task")

    assert eval_res.decision == AdmissionDecisionKind.NEEDS_HUMAN
    assert eval_res.block_condition == AdmissionBlockCondition.AUTH_REQUIRED
    assert "credentials missing or invalid" in eval_res.rationale.lower()
