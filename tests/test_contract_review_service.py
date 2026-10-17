"""Deterministic operational tests for governed DeepSeek contract review."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import httpx
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
    EventType,
    JobStatus,
    OperatorActionStatus,
    OperatorActionType,
    OrchestrationStage,
    RecoveryClassification,
    RecoveryDecisionStatus,
    RecoverySource,
    ReviewStatus,
)
from minime.domain.models import (
    ContractReviewVerdictPayload,
    Job,
    OpenRouterPricingSnapshot,
    OperatorActionRequest,
    OrchestrationRun,
    Project,
    RecoveryClaimContext,
    RecoveryDecision,
)
from minime.services import control_plane_service
from minime.services.contract_review_service import (
    ContractReviewService,
    DeepSeekContractReviewRunner,
    DeepSeekResponseDiagnostics,
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
        return DeepSeekReviewResponse(
            0,
            self.content,
            self.model,
            12,
            7,
            response_diagnostics=DeepSeekResponseDiagnostics(
                http_status=200,
                returned_model=self.model,
                model_matches_request=True,
                choices_count=1,
                finish_reason="stop",
                content_present=True,
                content_type="str",
                content_length=len(self.content),
                usage_present=True,
                prompt_tokens=12,
                completion_tokens=7,
                total_tokens=19,
                usage_valid=True,
            ),
        )


async def _configure(
    monkeypatch, uow, tmp_path: Path, *, capacity: bool = True, reviewer=None, authorize=True
):
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
                # Test-only owner policy exercising optional bounded reservations.
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
    action = (
        await asyncio.to_thread(
            control_plane_service.ControlPlaneService(uow, project_root=tmp_path).execute_action,
            request,
        )
        if authorize
        else None
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
async def test_contract_review_operational_path_uses_owner_policy_without_per_call_auth(
    in_memory_uow, monkeypatch, tmp_path
):
    project, run, job, app_config, adapter, _, action, reviewer = await _configure(
        monkeypatch, in_memory_uow, tmp_path, authorize=False
    )
    assert action is None

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
    assert adapter.model_checks == [("deepseek-flash", "low")] * 2
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
        idempotency_key="second-reservation-for-same-operation",
        maximum_stage_usd=Decimal("0.00002"),
        maximum_combined_usd=Decimal("1.50"),
    )
    assert duplicate_reservation is None
    assert duplicate_reason == "REVIEW_STAGE_SPENDING_LIMIT_EXCEEDED"

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


@pytest.mark.asyncio
async def test_contract_review_configured_stage_limit_counts_unresolved_exposure(
    in_memory_uow, monkeypatch, tmp_path
):
    from minime.domain.models import BudgetReservation

    project, run, job, app_config, adapter, pricing, _, reviewer = await _configure(
        monkeypatch, in_memory_uow, tmp_path, authorize=False
    )
    app_config.providers["deepseek"].budget = {"maximum_contract_review_usd": "0.50"}
    in_memory_uow.budget_reservations.save(
        BudgetReservation(
            project_id=project.project_id,
            job_id="historic-job",
            run_id="historic-run",
            change_id="historic-change",
            role="reviewer",
            canonical_model_identity="deepseek-flash",
            reserved_amount_usd=Decimal("0.50"),
            status="UNRESOLVED",
            pricing_snapshot_id=pricing.snapshot_id,
            provider="deepseek",
            account_fingerprint=adapter.account_fingerprint,
            stage="CONTRACT_REVIEW",
            billing_origin="deepseek_direct",
        )
    )
    result = await ContractReviewService(
        in_memory_uow, app_config=app_config, runner=reviewer
    ).review_before_apply(project, run, job, tmp_path)
    assert not result.accepted and result.waiting
    assert result.reason == "REVIEW_STAGE_SPENDING_LIMIT_EXCEEDED"
    assert reviewer.calls == 0
    assert len(in_memory_uow.budget_reservations.list_by_project(project.project_id)) == 1


@pytest.mark.asyncio
async def test_contract_review_without_optional_limit_accounts_usage_without_human_action(
    in_memory_uow, monkeypatch, tmp_path
):
    project, run, job, app_config, _, _, action, reviewer = await _configure(
        monkeypatch, in_memory_uow, tmp_path, authorize=False
    )
    app_config.providers["deepseek"].budget = {}
    result = await ContractReviewService(
        in_memory_uow, app_config=app_config, runner=reviewer
    ).review_before_apply(project, run, job, tmp_path)
    assert result.accepted
    assert action is None
    review = in_memory_uow.reviews.get_by_id(result.review_id)
    assert review and review.budget_reservation_id is None
    entries = in_memory_uow.budget_ledger.list_by_project(project.project_id)
    assert len(entries) == 1
    assert entries[0].provider == "deepseek"
    assert entries[0].billing_origin == "deepseek_direct"
    assert entries[0].prompt_tokens == 12 and entries[0].completion_tokens == 7
    repeated = await ContractReviewService(
        in_memory_uow, app_config=app_config, runner=reviewer
    ).review_before_apply(project, run, job, tmp_path)
    assert repeated.accepted and repeated.review_id == result.review_id
    assert reviewer.calls == 1
    assert len(in_memory_uow.budget_ledger.list_by_project(project.project_id)) == 1


@pytest.mark.asyncio
async def test_contract_review_rejects_price_evidence_from_another_account(
    in_memory_uow, monkeypatch, tmp_path
):
    project, run, job, app_config, _, _, _, reviewer = await _configure(
        monkeypatch, in_memory_uow, tmp_path, authorize=False
    )
    monkeypatch.setenv("DEEPSEEK_API_KEY", "a-different-account-key")
    result = await ContractReviewService(
        in_memory_uow, app_config=app_config, runner=reviewer
    ).review_before_apply(project, run, job, tmp_path)
    assert not result.accepted and result.waiting
    assert result.reason == "DEEPSEEK_DIRECT_PRICE_SNAPSHOT_UNAVAILABLE"
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
    # A bool is not an integer token count; neither output nor usage is trusted.
    assert reservation.status == "UNRESOLVED"
    assert in_memory_uow.budget_ledger.list_by_project(project.project_id) == []
    retry = await ContractReviewService(
        in_memory_uow, app_config=app_config, runner=reviewer
    ).review_before_apply(project, run, job, tmp_path)
    assert not retry.accepted
    assert reviewer.calls == 1
    assert len(in_memory_uow.budget_reservations.list_by_project(project.project_id)) == 1


@pytest.mark.asyncio
async def test_failed_contract_review_recovers_as_distinct_fenced_operation(
    in_memory_uow, monkeypatch, tmp_path
):
    class MalformedUsageReviewer(_DeterministicReviewer):
        async def review(self, contract_json: str, timeout_seconds: int):
            self.calls += 1
            return DeepSeekReviewResponse(0, self.content, self.model, True, 7)

    project, run, job, app_config, _, _, _, first_reviewer = await _configure(
        monkeypatch, in_memory_uow, tmp_path, reviewer=MalformedUsageReviewer()
    )
    first_result = await ContractReviewService(
        in_memory_uow, app_config=app_config, runner=first_reviewer
    ).review_before_apply(project, run, job, tmp_path)
    assert not first_result.accepted
    prior_review = in_memory_uow.reviews.get_by_id(first_result.review_id)
    prior_reservation = in_memory_uow.budget_reservations.get_by_id(
        prior_review.budget_reservation_id
    )
    assert prior_review.status == ReviewStatus.REVIEW_FAILED
    assert prior_reservation.status == "UNRESOLVED"
    old_review = prior_review.model_copy(deep=True)
    old_reservation = prior_reservation.model_copy(deep=True)

    # Represent the live state while the canonical Control Plane CONTINUE is
    # synchronously inside resume(): the decision and Run claim are still active.
    run.current_stage = OrchestrationStage.IMPLEMENTING
    run.is_active = True
    in_memory_uow.orchestration_runs.save(run)
    job.status = JobStatus.RUNNING
    in_memory_uow.jobs.save(job)
    claim = in_memory_uow.claims.acquire_or_reacquire(
        f"run:{run.run_id}", "control-plane-test-owner", lease_seconds=300
    )
    claim_context = RecoveryClaimContext(
        claim_key=claim.claim_key,
        owner_instance_id=claim.owner_instance_id,
        fence_token=claim.fence_token,
        lease_expires_at=claim.lease_expires_at,
    )
    decision = RecoveryDecision(
        cycle_id="continue-cycle-after-failed-contract-review",
        claim_key=claim.claim_key,
        identity_type="RUN",
        identity_id=run.run_id,
        project_id=project.project_id,
        change_name=job.change_name,
        source=RecoverySource.CONTROL_PLANE,
        classification=RecoveryClassification.RESUME_SAFE_CHECKPOINT,
        planned_action="DRIVE_CONTINUATION",
        fence_token=claim.fence_token,
        status=RecoveryDecisionStatus.EXECUTING,
    )
    in_memory_uow.recovery_decisions.create_decision(decision)

    retry_reviewer = _DeterministicReviewer()
    result = await ContractReviewService(
        in_memory_uow, app_config=app_config, runner=retry_reviewer
    ).review_before_apply(project, run, job, tmp_path, claim_context=claim_context)

    assert result.accepted and result.review_id != first_result.review_id
    assert retry_reviewer.calls == 1
    assert in_memory_uow.reviews.get_by_id(first_result.review_id) == old_review
    assert (
        in_memory_uow.budget_reservations.get_by_id(old_reservation.reservation_id)
        == old_reservation
    )
    new_review = in_memory_uow.reviews.get_by_id(result.review_id)
    new_reservation = in_memory_uow.budget_reservations.get_by_id(new_review.budget_reservation_id)
    assert new_review.status == ReviewStatus.REVIEW_COMPLETED
    assert new_reservation.status == "SETTLED"
    assert new_reservation.idempotency_key != old_reservation.idempotency_key
    assert new_reservation.reserved_amount_usd + old_reservation.reserved_amount_usd <= Decimal(
        "0.50"
    )
    operations = [
        event
        for event in in_memory_uow.events.list_events(project.project_id, job.change_name)
        if event.event_type == EventType.CONTRACT_REVIEW_OPERATION_STARTED
    ]
    assert len(operations) == 2
    retry_event = next(event for event in operations if event.operation_id == result.review_id)
    assert retry_event.payload["supersedes_review_id"] == first_result.review_id
    assert retry_event.payload["reservation_id"] == new_reservation.reservation_id


@pytest.mark.asyncio
async def test_failed_contract_review_retry_requires_current_control_plane_continue(
    in_memory_uow, monkeypatch, tmp_path
):
    class MalformedUsageReviewer(_DeterministicReviewer):
        async def review(self, contract_json: str, timeout_seconds: int):
            self.calls += 1
            return DeepSeekReviewResponse(0, self.content, self.model, True, 7)

    project, run, job, app_config, _, _, _, failed_reviewer = await _configure(
        monkeypatch, in_memory_uow, tmp_path, reviewer=MalformedUsageReviewer()
    )
    failed = await ContractReviewService(
        in_memory_uow, app_config=app_config, runner=failed_reviewer
    ).review_before_apply(project, run, job, tmp_path)
    assert not failed.accepted
    job.status = JobStatus.RUNNING
    in_memory_uow.jobs.save(job)
    run.current_stage = OrchestrationStage.IMPLEMENTING
    in_memory_uow.orchestration_runs.save(run)
    claim = in_memory_uow.claims.acquire_or_reacquire(
        f"run:{run.run_id}", "control-plane-test-owner", lease_seconds=300
    )
    claim_context = RecoveryClaimContext(
        claim_key=claim.claim_key,
        owner_instance_id=claim.owner_instance_id,
        fence_token=claim.fence_token,
        lease_expires_at=claim.lease_expires_at,
    )
    in_memory_uow.recovery_decisions.create_decision(
        RecoveryDecision(
            cycle_id="api-recovery-is-not-control-plane-continue",
            claim_key=claim.claim_key,
            identity_type="RUN",
            identity_id=run.run_id,
            project_id=project.project_id,
            change_name=job.change_name,
            source=RecoverySource.API,
            classification=RecoveryClassification.RESUME_SAFE_CHECKPOINT,
            planned_action="DRIVE_CONTINUATION",
            fence_token=claim.fence_token,
            status=RecoveryDecisionStatus.EXECUTING,
        )
    )
    retry_reviewer = _DeterministicReviewer()
    result = await ContractReviewService(
        in_memory_uow, app_config=app_config, runner=retry_reviewer
    ).review_before_apply(project, run, job, tmp_path, claim_context=claim_context)
    assert not result.accepted and result.waiting
    assert result.reason == "CONTRACT_REVIEW_RECOVERY_DECISION_NOT_CURRENT_CONTINUE"
    assert retry_reviewer.calls == 0


_UNSET_CONTENT = object()


def _official_chat_completion(
    *, model="deepseek-flash", content=_UNSET_CONTENT, usage=None, finish="stop"
):
    if content is _UNSET_CONTENT:
        content = json.dumps(
            {
                "verdict": "CONTRACT_ACCEPTED",
                "summary": "Contract is internally consistent.",
                "findings": [],
            }
        )
    return {
        "id": "completion-test-123",
        "object": "chat.completion",
        "model": model,
        "choices": [
            {
                "index": 0,
                "finish_reason": finish,
                "message": {
                    "role": "assistant",
                    "content": content,
                    "reasoning_content": "PRIVATE_REASONING_MUST_NOT_BE_PERSISTED",
                },
            }
        ],
        "usage": usage
        if usage is not None
        else {
            "prompt_tokens": 12,
            "completion_tokens": 7,
            "total_tokens": 19,
            "prompt_tokens_details": {"cached_tokens": 0},
        },
    }


@pytest.mark.asyncio
async def test_deepseek_http_response_is_diagnosed_before_verdict_parse_without_sensitive_text(
    in_memory_uow, monkeypatch, tmp_path
):
    body = _official_chat_completion(content="not-json")

    async def respond(request):
        payload = json.loads(request.content)
        system_prompt = payload["messages"][0]["content"]
        assert "valid json" in system_prompt.lower() and '"verdict"' in system_prompt
        assert payload["response_format"] == {"type": "json_object"}
        assert payload["max_tokens"] == 65536
        return httpx.Response(200, json=body)

    project, run, job, app_config, _, pricing, action, _ = await _configure(
        monkeypatch, in_memory_uow, tmp_path
    )
    assert action.status == OperatorActionStatus.COMPLETED
    client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    runner = DeepSeekContractReviewRunner(
        api_key="intercepted-test-key",
        endpoint="https://api.deepseek.com/chat/completions",
        model="deepseek-flash",
        effort="low",
        client=client,
    )
    original_validator = ContractReviewVerdictPayload.model_validate_json

    def validate_only_after_diagnostic(raw_content):
        persisted = [
            event
            for event in in_memory_uow.events.list_events(project.project_id, job.change_name)
            if event.event_type == EventType.EVIDENCE_DIAGNOSTIC_RECORDED
            and event.payload.get("diagnostic_kind") == "DEEPSEEK_REVIEW_HTTP_RESPONSE"
        ]
        assert len(persisted) == 1, "safe provider response evidence must commit before parse"
        return original_validator(raw_content)

    monkeypatch.setattr(
        ContractReviewVerdictPayload,
        "model_validate_json",
        staticmethod(validate_only_after_diagnostic),
    )
    result = await ContractReviewService(
        in_memory_uow, app_config=app_config, runner=runner
    ).review_before_apply(project, run, job, tmp_path)
    await client.aclose()

    assert not result.accepted and result.reason == "CONTRACT_REVIEW_MALFORMED"
    review = in_memory_uow.reviews.get_by_job_stage(job.job_id, "CONTRACT_REVIEW")
    reservation = in_memory_uow.budget_reservations.get_by_id(review.budget_reservation_id)
    assert review.status == ReviewStatus.REVIEW_FAILED
    assert reservation.status == "SETTLED"
    assert reservation.reserved_amount_usd >= Decimal("65536") * pricing.output_price_per_token
    diagnostic_events = [
        event
        for event in in_memory_uow.events.list_events(project.project_id, job.change_name)
        if event.event_type == EventType.EVIDENCE_DIAGNOSTIC_RECORDED
        and event.payload.get("diagnostic_kind") == "DEEPSEEK_REVIEW_HTTP_RESPONSE"
    ]
    assert len(diagnostic_events) == 1
    diagnostic = diagnostic_events[0].payload["response"]
    assert diagnostic["http_status"] == 200
    assert diagnostic["response_id"] == "completion-test-123"
    assert diagnostic["model_matches_request"] is True
    assert diagnostic["finish_reason"] == "stop"
    assert diagnostic["usage_valid"] is True
    assert diagnostic["reasoning_content_length"] == len("PRIVATE_REASONING_MUST_NOT_BE_PERSISTED")
    assert "PRIVATE_REASONING_MUST_NOT_BE_PERSISTED" not in json.dumps(diagnostic_events[0].payload)
    assert "not-json" not in json.dumps(diagnostic_events[0].payload)


@pytest.mark.parametrize(
    ("body", "expected_reason", "expected_model_match", "expected_finish", "expected_reservation"),
    [
        (
            _official_chat_completion(model="different-model"),
            "DEEPSEEK_REVIEW_RESPONSE_UNVERIFIABLE",
            False,
            "stop",
            "UNRESOLVED",
        ),
        (
            _official_chat_completion(content=None),
            "DEEPSEEK_REVIEW_RESPONSE_UNVERIFIABLE",
            True,
            "stop",
            "SETTLED",
        ),
        (
            _official_chat_completion(usage={"prompt_tokens": 12, "completion_tokens": 7}),
            "DEEPSEEK_REVIEW_RESPONSE_UNVERIFIABLE",
            True,
            "stop",
            "UNRESOLVED",
        ),
        (
            _official_chat_completion(finish="length", content='{"verdict":'),
            "DEEPSEEK_REVIEW_RESPONSE_UNVERIFIABLE",
            True,
            "length",
            "SETTLED",
        ),
        (
            _official_chat_completion(
                usage={"prompt_tokens": 12, "completion_tokens": 7, "total_tokens": 99}
            ),
            "DEEPSEEK_REVIEW_RESPONSE_UNVERIFIABLE",
            True,
            "stop",
            "UNRESOLVED",
        ),
    ],
)
@pytest.mark.asyncio
async def test_deepseek_http_200_validation_failures_are_deterministic_and_unresolved(
    in_memory_uow,
    monkeypatch,
    tmp_path,
    body,
    expected_reason,
    expected_model_match,
    expected_finish,
    expected_reservation,
):
    async def respond(_request):
        return httpx.Response(200, json=body)

    project, run, job, app_config, _, _, action, _ = await _configure(
        monkeypatch, in_memory_uow, tmp_path
    )
    assert action.status == OperatorActionStatus.COMPLETED
    client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    runner = DeepSeekContractReviewRunner(
        api_key="intercepted-test-key",
        model="deepseek-flash",
        effort="low",
        client=client,
    )
    result = await ContractReviewService(
        in_memory_uow, app_config=app_config, runner=runner
    ).review_before_apply(project, run, job, tmp_path)
    await client.aclose()

    assert not result.accepted and result.reason == expected_reason
    review = in_memory_uow.reviews.get_by_job_stage(job.job_id, "CONTRACT_REVIEW")
    reservation = in_memory_uow.budget_reservations.get_by_id(review.budget_reservation_id)
    assert reservation.status == expected_reservation
    diagnostic = next(
        event.payload["response"]
        for event in in_memory_uow.events.list_events(project.project_id, job.change_name)
        if event.event_type == EventType.EVIDENCE_DIAGNOSTIC_RECORDED
        and event.payload.get("diagnostic_kind") == "DEEPSEEK_REVIEW_HTTP_RESPONSE"
    )
    assert diagnostic["model_matches_request"] is expected_model_match
    assert diagnostic["finish_reason"] == expected_finish
    assert diagnostic["http_status"] == 200


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
    assert reason == "VERIFIED_PROVIDER_PRICE_MISSING_OR_MISMATCHED"
