"""Tests for provider health execution readiness and preflight failure recovery semantics."""

import pytest
from unittest.mock import AsyncMock, patch

from minime.adapters.provider_adapter import AntigravityProviderAdapter
from minime.domain.enums import (
    AttemptProductivityClass,
    ExecutionOutcome,
    JobStatus,
    PremiumProviderReasonCode,
    PrimaryProvider,
    ProviderHealthStatus,
    ProviderResultClass,
    TaskClass,
)
from minime.domain.models import (
    JobAttempt,
    NormalizedProviderResult,
    Project,
)
from minime.services.outcome_governance import CompletionVerificationResult, OutcomeGovernanceService
from minime.services.provider_health_service import ProviderHealthService
from minime.services.provider_outcome_parser import ProviderOutcomeParser
from minime.services.provider_policy_service import ProviderPolicyService


@pytest.mark.asyncio
async def test_antigravity_probe_fails_when_unauthenticated():
    adapter = AntigravityProviderAdapter(executable="agy")
    with patch("shutil.which", return_value="/usr/local/bin/agy"):
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            proc = AsyncMock()
            proc.communicate.return_value = (
                b"Fetching available models...\n",
                b"Error: Please sign in to view available models. Launch the CLI without arguments to sign in.\n",
            )
            proc.returncode = 1
            mock_exec.return_value = proc

            ready = await adapter.probe_availability()
            assert ready is False


@pytest.mark.asyncio
async def test_antigravity_probe_succeeds_when_authenticated():
    adapter = AntigravityProviderAdapter(executable="agy")
    with patch("shutil.which", return_value="/usr/local/bin/agy"):
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            proc = AsyncMock()
            proc.communicate.return_value = (
                b"Models:\n- gemini-2.5-pro\n- gemini-2.5-flash\n",
                b"",
            )
            proc.returncode = 0
            mock_exec.return_value = proc

            ready = await adapter.probe_availability()
            assert ready is True


def test_provider_outcome_parser_matches_auth_required():
    parsed = ProviderOutcomeParser.parse_runner_output(
        provider="antigravity",
        role="implementer",
        model=None,
        exit_code=1,
        timed_out=False,
        stdout_lines=[],
        stderr_lines=[
            "Error: authentication required. Run 'agy.real' to log in, then retry.",
            "Error: authentication failed or timed out",
        ],
    )
    assert parsed.result_class == ProviderResultClass.AUTH_ERROR


def test_outcome_governance_classifies_auth_error_as_auth_required():
    service = OutcomeGovernanceService()
    ver_res = CompletionVerificationResult(is_complete=False)
    prov_res = NormalizedProviderResult(
        result_class=ProviderResultClass.AUTH_ERROR,
        provider="antigravity",
        role="implementer",
        summary="Authentication error for provider antigravity",
    )
    outcome = service.classify_outcome(ver_res, provider_result=prov_res)
    assert outcome == ExecutionOutcome.AUTH_REQUIRED


def test_provider_health_transitions_to_auth_required(in_memory_uow):
    health_svc = ProviderHealthService(in_memory_uow)
    health = health_svc.record_outcome(
        NormalizedProviderResult(
            provider="antigravity",
            role="implementer",
            result_class=ProviderResultClass.AUTH_ERROR,
            summary="Authentication required for agy",
        )
    )
    assert health.status == ProviderHealthStatus.AUTH_REQUIRED


def test_preflight_auth_failure_does_not_consume_material_recovery_budget(in_memory_uow):
    policy = ProviderPolicyService(in_memory_uow)
    project = Project(
        project_id="p1",
        display_name="Project 1",
        repository="owner/repo",
        implementer="codex",
        reviewer="antigravity",
    )

    # 2 failed codex attempts followed by an attempt 3 that failed preflight due to AUTH_REQUIRED
    past_attempts = [
        JobAttempt(
            attempt_id="att-1",
            job_id="job-1",
            attempt_number=1,
            executor_role="codex",
            model_identity="codex",
            normalized_outcome=ExecutionOutcome.MALFORMED_RESULT,
        ),
        JobAttempt(
            attempt_id="att-2",
            job_id="job-1",
            attempt_number=2,
            executor_role="codex",
            model_identity="codex",
            normalized_outcome=ExecutionOutcome.MALFORMED_RESULT,
        ),
        JobAttempt(
            attempt_id="att-3",
            job_id="job-1",
            attempt_number=3,
            executor_role="antigravity",
            model_identity="antigravity",
            normalized_outcome=ExecutionOutcome.AUTH_REQUIRED,
            productivity_class=AttemptProductivityClass.PROVIDER_PREFLIGHT_FAILURE,
            premium_reason_code=PremiumProviderReasonCode.PREMIUM_RECOVERY_NON_CONVERGENCE,
            duration_ms=600,
        ),
    ]

    # Codex non-convergence verification must remain TRUE because Att 3 was a preflight failure
    assert policy._verify_codex_non_convergence(past_attempts) is True

    # Once Antigravity is available, it is selected for premium recovery
    health_records = [
        type("Health", (), {"provider": "codex", "status": ProviderHealthStatus.TEMPORARILY_UNAVAILABLE})(),
        type("Health", (), {"provider": "antigravity", "status": ProviderHealthStatus.AVAILABLE})(),
    ]
    expl = policy.evaluate_selection(
        task_class=TaskClass.ROUTINE_IMPLEMENTATION,
        project=project,
        attempts=past_attempts,
        provider_health_records=health_records,
    )
    assert expl.selected_provider == PrimaryProvider.ANTIGRAVITY.value
    assert expl.is_premium is True
    assert expl.premium_reason_code == PremiumProviderReasonCode.PREMIUM_RECOVERY_NON_CONVERGENCE
