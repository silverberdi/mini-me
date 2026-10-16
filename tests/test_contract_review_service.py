"""Deterministic operational tests for governed DeepSeek contract review."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from minime.adapters.provider_adapter import CapacityObservation, DeepSeekProviderAdapter
from minime.config import (
    AppConfig,
    OpenSpecStage,
    ProjectConfig,
    ProviderConfig,
    StageProfileConfig,
    resolve_stage_profile,
)
from minime.domain.enums import (
    CapacitySignalSource,
    OperatorActionStatus,
    OperatorActionType,
    OrchestrationStage,
    ReviewStatus,
)
from minime.domain.models import (
    Job,
    OpenRouterPricingSnapshot,
    OperatorActionRequest,
    OrchestrationRun,
    Project,
)
from minime.services import control_plane_service
from minime.services.contract_review_service import (
    ContractReviewService,
    DeepSeekReviewResponse,
)
from minime.services.provider_health_service import ProviderHealthService


class _InterceptedDeepSeekAdapter(DeepSeekProviderAdapter):
    """Keep provider boundaries real while returning deterministic account evidence."""

    def __init__(self, *, available: bool = True):
        super().__init__()
        self.available = available
        self.capacity_reads = 0
        self.model_checks: list[tuple[str, str | None]] = []

    async def check_cli_present(self) -> bool:
        return True

    async def check_auth_ready(self, timeout_seconds: float = 10.0) -> bool:
        return bool(self.authenticated_api_key)

    async def check_model_supported(
        self, model: str, effort: str | None = None, timeout_seconds: float = 10.0
    ):
        self.model_checks.append((model, effort))
        return (model == "deepseek-flash" and effort == "low", None)

    async def read_capacity_observation(
        self, timeout_seconds: float = 10.0, selected_model: str | None = None
    ):
        self.capacity_reads += 1
        now = datetime.now(UTC)
        return CapacityObservation(
            provider="deepseek",
            ordinary_usage_allowed=self.available,
            observed_at=now,
            expires_at=now + timedelta(seconds=60),
            source_signal=CapacitySignalSource.DEEPSEEK_ACCOUNT_BALANCE,
            account_id=self.account_fingerprint,
            model=selected_model,
            quota_scope="deepseek_direct_account_balance",
        )


class _DeterministicReviewer:
    model = "deepseek-flash"
    effort = "low"

    def __init__(self, content: str | None = None):
        self.calls = 0
        self.content = content or json.dumps(
            {
                "verdict": "CONTRACT_ACCEPTED",
                "summary": "Contract is internally consistent.",
                "findings": [],
            }
        )

    async def review(self, contract_json: str, timeout_seconds: int):
        assert "CONTRACT_REVIEW" in contract_json
        assert timeout_seconds > 0
        self.calls += 1
        return DeepSeekReviewResponse(0, self.content, self.model, 12, 7)


async def _configure(monkeypatch, uow, tmp_path: Path, *, capacity: bool = True, reviewer=None):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-only-account-key")
    project_id = "review-project"
    change_name = "contract-change"
    project = Project(
        project_id=project_id,
        display_name="Review project",
        repository="owner/repo",
        openspec_path="openspec",
        external_providers_allowed=["codex", "antigravity", "deepseek"],
    )
    project_config = ProjectConfig(
        repository="owner/repo",
        openspec_path="openspec",
        external_providers_allowed=["codex", "antigravity", "deepseek"],
        stage_profiles={
            "CONTRACT_REVIEW": StageProfileConfig(
                provider="deepseek",
                model="deepseek-flash",
                effort="low",
                workflow="openspec-explore",
            )
        },
    )
    app_config = AppConfig(
        providers={
            "deepseek": ProviderConfig(
                type="api",
                enabled=True,
                budget={
                    "maximum_contract_review_usd": "0.50",
                    "maximum_code_review_usd": "1.00",
                    "maximum_combined_review_usd": "1.50",
                },
            )
        },
        projects={project_id: project_config},
    )
    job = Job(project_id=project_id, change_name=change_name, implementer_role="codex")
    run = OrchestrationRun(
        project_id=project_id,
        change_name=change_name,
        base_sha="base-sha",
        active_job_id=job.job_id,
        current_stage=OrchestrationStage.ADMITTED,
    )
    uow.projects.save(project)
    uow.jobs.save(job)
    uow.orchestration_runs.save(run)

    change_dir = tmp_path / "openspec" / "changes" / change_name
    (change_dir / "specs" / "contract").mkdir(parents=True)
    (change_dir / "proposal.md").write_text(
        "# Proposal\nReview an exact contract.\n", encoding="utf-8"
    )
    (change_dir / "tasks.md").write_text("- [ ] Preserve exact identity.\n", encoding="utf-8")
    (change_dir / "specs" / "contract" / "spec.md").write_text(
        "## Requirements\n", encoding="utf-8"
    )

    adapter = _InterceptedDeepSeekAdapter(available=capacity)
    import minime.adapters.provider_adapter as provider_adapter

    monkeypatch.setitem(provider_adapter._ADAPTER_REGISTRY, "deepseek", adapter)
    pricing = OpenRouterPricingSnapshot(
        id="deepseek-price",
        canonical_model_identity="deepseek-flash",
        routed_model_identity="deepseek-flash",
        prompt_price_per_token=Decimal("0.000001"),
        output_price_per_token=Decimal("0.000001"),
        additional_cost_per_request=Decimal("0"),
        currency="USD",
        source="deepseek_official_pricing",
        provider="deepseek",
        account_fingerprint=adapter.account_fingerprint,
        billing_origin="deepseek_direct",
    )
    uow.pricing_snapshots.save(pricing)
    monkeypatch.setattr(control_plane_service, "load_config", lambda: app_config)
    assert (
        resolve_stage_profile(
            project_config, OpenSpecStage.CONTRACT_REVIEW, app_config=app_config
        ).model
        == "deepseek-flash"
    )
    assert await adapter.check_model_supported("deepseek-flash", effort="low") == (True, None)
    assert (
        pricing.is_verified
        and pricing.provider == "deepseek"
        and pricing.account_fingerprint == adapter.account_fingerprint
    )

    request = OperatorActionRequest(
        action_request_id="authorize-contract-review-1",
        project_id=project_id,
        change_name=change_name,
        run_id=run.run_id,
        action_type=OperatorActionType.AUTHORIZE_DEEPSEEK_REVIEW,
        parameters={
            "max_spend_usd": "0.50",
            "expires_at": (datetime.now(UTC) + timedelta(minutes=15)).isoformat(),
            "pricing_snapshot_id": pricing.snapshot_id,
        },
        actor_identity="test-operator",
        expected_stage=run.current_stage,
        expected_generation=run.current_generation,
    )
    action = await asyncio.to_thread(
        control_plane_service.ControlPlaneService(uow, project_root=tmp_path).execute_action,
        request,
    )
    return (
        project,
        run,
        job,
        app_config,
        adapter,
        pricing,
        action,
        reviewer or _DeterministicReviewer(),
    )


@pytest.mark.asyncio
async def test_contract_review_operational_path_authorizes_reserves_dispatches_and_reuses_checkpoint(
    in_memory_uow, monkeypatch, tmp_path
):
    project, run, job, app_config, adapter, _, action, reviewer = await _configure(
        monkeypatch, in_memory_uow, tmp_path
    )
    assert action.status == OperatorActionStatus.COMPLETED, action.summary

    service = ContractReviewService(
        in_memory_uow,
        health_service=ProviderHealthService(in_memory_uow),
        app_config=app_config,
        runner=reviewer,
    )
    first = await service.review_before_apply(project, run, job, tmp_path)
    assert first.accepted
    assert first.contract_hash and first.review_id
    assert adapter.capacity_reads == 1
    assert adapter.model_checks == [("deepseek-flash", "low")] * 3
    assert reviewer.calls == 1

    review = in_memory_uow.reviews.get_by_job_stage(job.job_id, "CONTRACT_REVIEW")
    reservation = in_memory_uow.budget_reservations.get_by_id(review.budget_reservation_id)
    assert review.status == ReviewStatus.REVIEW_COMPLETED
    assert review.candidate_sha == first.contract_hash
    assert review.contract_hash == first.contract_hash
    assert review.provider == "deepseek"
    assert review.billing_origin == "deepseek_direct"
    assert reservation.provider == "deepseek"
    assert reservation.stage == "CONTRACT_REVIEW"
    assert reservation.account_fingerprint == adapter.account_fingerprint
    assert reservation.status == "SETTLED"
    assert len(in_memory_uow.budget_reservations.list_by_project(project.project_id)) == 1
    assert len(in_memory_uow.budget_ledger.list_by_project(project.project_id)) == 1
    duplicate_reservation, duplicate_reason = service.budget.reserve_review_budget(
        project_id=project.project_id,
        run_id=run.run_id,
        job_id=job.job_id,
        change_id=job.change_name,
        provider="deepseek",
        account_fingerprint=adapter.account_fingerprint,
        model="deepseek-flash",
        stage="CONTRACT_REVIEW",
        billing_origin="deepseek_direct",
        pricing_snapshot_id=reservation.pricing_snapshot_id,
        prompt_token_upper_bound=100,
        max_output_tokens=100,
        idempotency_key="second-reservation-for-same-authorization",
    )
    assert duplicate_reservation is None
    assert duplicate_reason == "REVIEW_BUDGET_AUTHORIZATION_ALREADY_CONSUMED"

    second = await service.review_before_apply(project, run, job, tmp_path)
    assert second.accepted and second.review_id == first.review_id
    assert reviewer.calls == 1
    assert adapter.capacity_reads == 1


@pytest.mark.asyncio
async def test_contract_review_waits_without_capacity_and_does_not_dispatch(
    in_memory_uow, monkeypatch, tmp_path
):
    project, run, job, app_config, _, _, action, reviewer = await _configure(
        monkeypatch, in_memory_uow, tmp_path, capacity=False
    )
    assert action.status == OperatorActionStatus.COMPLETED, action.summary
    result = await ContractReviewService(
        in_memory_uow, app_config=app_config, runner=reviewer
    ).review_before_apply(project, run, job, tmp_path)
    assert not result.accepted and result.waiting
    assert result.reason == "DEEPSEEK_CAPACITY_UNKNOWN_OR_EXHAUSTED"
    assert reviewer.calls == 0
    assert in_memory_uow.budget_reservations.list_by_project(project.project_id) == []


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("account_fingerprint", "f" * 64),
        ("model", "different-model"),
        ("stage", "REVIEW"),
        ("billing_origin", "openrouter"),
        ("pricing_snapshot_id", "openrouter-price-id"),
    ],
)
@pytest.mark.asyncio
async def test_contract_review_rejects_mismatched_durable_spend_authority(
    in_memory_uow, monkeypatch, tmp_path, field, value
):
    project, run, job, app_config, _, _, action, reviewer = await _configure(
        monkeypatch, in_memory_uow, tmp_path
    )
    stored = in_memory_uow.operator_actions.get_by_request_id(action.action_request_id)
    payload = stored.result_payload_json.copy()
    payload["authorization"] = payload["authorization"].copy()
    payload["authorization"][field] = value
    stored.result_payload_json = payload
    in_memory_uow.operator_actions.save(stored)

    result = await ContractReviewService(
        in_memory_uow, app_config=app_config, runner=reviewer
    ).review_before_apply(project, run, job, tmp_path)
    assert not result.accepted and result.waiting
    assert reviewer.calls == 0
    assert in_memory_uow.budget_reservations.list_by_project(project.project_id) == []


@pytest.mark.asyncio
async def test_contract_review_rejects_code_review_verdict_and_never_creates_merge_authority(
    in_memory_uow, monkeypatch, tmp_path
):
    reviewer = _DeterministicReviewer(
        json.dumps(
            {"verdict": "READY_TO_MERGE", "summary": "Not a contract verdict.", "findings": []}
        )
    )
    project, run, job, app_config, _, _, action, _ = await _configure(
        monkeypatch, in_memory_uow, tmp_path, reviewer=reviewer
    )
    assert action.status == OperatorActionStatus.COMPLETED, action.summary
    result = await ContractReviewService(
        in_memory_uow, app_config=app_config, runner=reviewer
    ).review_before_apply(project, run, job, tmp_path)
    assert not result.accepted
    assert not result.waiting
    assert result.reason in {"CONTRACT_REVIEW_MALFORMED", "CROSS_STAGE_REVIEW_EVIDENCE_DENIED"}
    assert reviewer.calls == 1
    assert in_memory_uow.reviews.get_by_job_stage(job.job_id, "CODE_REVIEW") is None


@pytest.mark.asyncio
async def test_contract_review_rejects_boolean_token_usage_without_settlement(
    in_memory_uow, monkeypatch, tmp_path
):
    class MalformedUsageReviewer(_DeterministicReviewer):
        async def review(self, contract_json: str, timeout_seconds: int):
            assert "CONTRACT_REVIEW" in contract_json
            self.calls += 1
            return DeepSeekReviewResponse(
                0,
                self.content,
                self.model,
                True,
                7,
            )

    reviewer = MalformedUsageReviewer()
    project, run, job, app_config, _, _, action, _ = await _configure(
        monkeypatch, in_memory_uow, tmp_path, reviewer=reviewer
    )
    assert action.status == OperatorActionStatus.COMPLETED

    result = await ContractReviewService(
        in_memory_uow, app_config=app_config, runner=reviewer
    ).review_before_apply(project, run, job, tmp_path)

    assert not result.accepted
    assert result.reason == "DEEPSEEK_REVIEW_RESPONSE_UNVERIFIABLE"
    review = in_memory_uow.reviews.get_by_job_stage(job.job_id, "CONTRACT_REVIEW")
    reservation = in_memory_uow.budget_reservations.get_by_id(review.budget_reservation_id)
    assert review.status == ReviewStatus.REVIEW_FAILED
    assert reservation.status == "UNRESOLVED"
    assert in_memory_uow.budget_ledger.list_by_project(project.project_id) == []
    retry = await ContractReviewService(
        in_memory_uow, app_config=app_config, runner=reviewer
    ).review_before_apply(project, run, job, tmp_path)
    assert not retry.accepted
    assert reviewer.calls == 1
    assert len(in_memory_uow.budget_reservations.list_by_project(project.project_id)) == 1


def test_deepseek_review_cannot_reuse_openrouter_price_snapshot(in_memory_uow):
    from minime.services.budget_service import BudgetService

    reservation, reason = BudgetService(in_memory_uow).reserve_review_budget(
        project_id="p",
        run_id="r",
        job_id="j",
        change_id="c",
        provider="deepseek",
        account_fingerprint="a" * 64,
        model="deepseek-flash",
        stage="CONTRACT_REVIEW",
        billing_origin="deepseek_direct",
        pricing_snapshot_id="missing-openrouter-snapshot",
        prompt_token_upper_bound=100,
        max_output_tokens=100,
        idempotency_key="review:r:j:CONTRACT_REVIEW:hash",
    )
    assert reservation is None
    assert reason == "DURABLE_REVIEW_BUDGET_AUTHORIZATION_MISSING_OR_MISMATCHED"
