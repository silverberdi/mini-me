"""Governed, read-only DeepSeek Direct review of one OpenSpec contract checkpoint."""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import httpx
from pydantic import ValidationError

from minime.adapters.provider_adapter import get_provider_adapter
from minime.config import (
    AppConfig,
    OpenSpecStage,
    ProjectConfig,
    StageProfileError,
    load_config,
    resolve_stage_profile,
)
from minime.domain.enums import (
    EventType,
    ExternalActionStatus,
    OrchestrationStage,
    ProviderHealthStatus,
    RecoveryClassification,
    RecoveryDecisionStatus,
    RecoverySource,
    ReviewStatus,
    ReviewVerdict,
)
from minime.domain.interfaces import PersistenceUnitOfWork
from minime.domain.models import (
    ContractReviewVerdictPayload,
    Event,
    Job,
    OrchestrationRun,
    Project,
    RecoveryClaimContext,
    Review,
    ReviewFinding,
    generate_uuid,
    utc_now,
    validate_claim_context_authoritative,
)
from minime.services.budget_service import BudgetService
from minime.services.provider_health_service import ProviderHealthService

DIRECT_ENDPOINT = "https://api.deepseek.com/chat/completions"
CONTRACT_REVIEW_MAX_OUTPUT_TOKENS = 65536


def _review_reservation_key(
    *, run_id: str, job_id: str, stage: str, contract_hash: str, operation_id: str | None = None
) -> str:
    """Return a bounded deterministic key for the persisted VARCHAR(128) column."""
    if operation_id is None:
        identity = [run_id, job_id, stage, contract_hash]
        version = "v1"
    else:
        identity = [run_id, job_id, stage, contract_hash, operation_id]
        version = "v2"
    payload = json.dumps(identity, separators=(",", ":")).encode("utf-8")
    return f"review:{version}:{hashlib.sha256(payload).hexdigest()}"


@dataclass(frozen=True)
class ContractReviewResult:
    accepted: bool
    review_id: str | None
    contract_hash: str | None
    reason: str | None = None
    waiting: bool = False


@dataclass(frozen=True)
class DeepSeekReviewResponse:
    exit_code: int
    content: str | None
    model: str | None
    prompt_tokens: int | None
    completion_tokens: int | None
    error: str | None = None
    response_diagnostics: DeepSeekResponseDiagnostics | None = None


@dataclass(frozen=True)
class DeepSeekResponseDiagnostics:
    """Allowlisted response metadata; never contains response or reasoning text."""

    http_status: int
    response_id: str | None = None
    response_object: str | None = None
    returned_model: str | None = None
    model_matches_request: bool | None = None
    choices_count: int | None = None
    finish_reason: str | None = None
    content_present: bool = False
    content_type: str = "missing"
    content_length: int | None = None
    reasoning_content_present: bool = False
    reasoning_content_type: str = "missing"
    reasoning_content_length: int | None = None
    usage_present: bool = False
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    usage_valid: bool = False


_SAFE_PROVIDER_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_KNOWN_FINISH_REASONS = {
    "stop",
    "length",
    "content_filter",
    "tool_calls",
    "insufficient_system_resource",
    "aborted",
}


def _bounded_provider_id(value: object) -> str | None:
    if isinstance(value, str) and _SAFE_PROVIDER_ID.fullmatch(value):
        return value
    return None


def _response_diagnostics(
    status_code: int, body: object, requested_model: str
) -> DeepSeekResponseDiagnostics:
    if not isinstance(body, dict):
        return DeepSeekResponseDiagnostics(http_status=status_code)

    returned_model = _bounded_provider_id(body.get("model"))
    choices = body.get("choices")
    choice = choices[0] if isinstance(choices, list) and choices else None
    choice = choice if isinstance(choice, dict) else None
    message = choice.get("message") if choice else None
    message = message if isinstance(message, dict) else None
    content = message.get("content") if message else None
    reasoning = message.get("reasoning_content") if message else None
    usage = body.get("usage")
    usage = usage if isinstance(usage, dict) else None

    def token_count(value: object) -> int | None:
        return (
            value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None
        )

    prompt_tokens = token_count(usage.get("prompt_tokens")) if usage else None
    completion_tokens = token_count(usage.get("completion_tokens")) if usage else None
    total_tokens = token_count(usage.get("total_tokens")) if usage else None
    usage_valid = (
        prompt_tokens is not None
        and completion_tokens is not None
        and total_tokens is not None
        and total_tokens == prompt_tokens + completion_tokens
    )
    finish_reason = choice.get("finish_reason") if choice else None
    if finish_reason not in _KNOWN_FINISH_REASONS:
        finish_reason = None

    return DeepSeekResponseDiagnostics(
        http_status=status_code,
        response_id=_bounded_provider_id(body.get("id")),
        response_object=_bounded_provider_id(body.get("object")),
        returned_model=returned_model,
        model_matches_request=returned_model == requested_model if returned_model else False,
        choices_count=len(choices) if isinstance(choices, list) else None,
        finish_reason=finish_reason,
        content_present=bool(message is not None and "content" in message),
        content_type=type(content).__name__
        if message is not None and "content" in message
        else "missing",
        content_length=len(content) if isinstance(content, str) else None,
        reasoning_content_present=bool(message is not None and "reasoning_content" in message),
        reasoning_content_type=(
            type(reasoning).__name__
            if message is not None and "reasoning_content" in message
            else "missing"
        ),
        reasoning_content_length=len(reasoning) if isinstance(reasoning, str) else None,
        usage_present=usage is not None,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        usage_valid=usage_valid,
    )


def persist_deepseek_response_diagnostic(
    uow: PersistenceUnitOfWork, review: Review, response: DeepSeekReviewResponse
) -> None:
    """Commit safe provider response metadata before validating reviewer output."""
    diagnostic = response.response_diagnostics
    if diagnostic is None:
        return
    payload = diagnostic.__dict__
    uow.events.save(
        Event(
            event_type=EventType.EVIDENCE_DIAGNOSTIC_RECORDED,
            project_id=review.project_id,
            change_id=review.change_name,
            operation_id=review.job_id,
            payload={
                "diagnostic_kind": "DEEPSEEK_REVIEW_HTTP_RESPONSE",
                "review_id": review.review_id,
                "review_stage": review.review_stage,
                "run_id": review.orchestration_run_id,
                "job_id": review.job_id,
                "contract_hash": review.contract_hash,
                "candidate_sha": review.candidate_sha,
                "provider": "deepseek",
                "model": review.reviewer_model,
                "account_fingerprint": review.account_fingerprint,
                "reservation_id": review.budget_reservation_id,
                "response": payload,
            },
        )
    )
    uow.commit()


class DeepSeekContractReviewRunner:
    """Shared direct, bounded DeepSeek reviewer transport; no tools or write access."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        endpoint: str = DIRECT_ENDPOINT,
        model: str = "deepseek-chat",
        effort: str = "low",
        review_stage: str = "CONTRACT_REVIEW",
        client: httpx.AsyncClient | None = None,
    ):
        self.api_key = api_key if api_key is not None else os.getenv("DEEPSEEK_API_KEY")
        self.endpoint = endpoint
        self.model = model
        self.effort = effort
        if review_stage not in {"CONTRACT_REVIEW", "CODE_REVIEW"}:
            raise ValueError("Unsupported DeepSeek review stage.")
        self.review_stage = review_stage
        self.client = client

    async def review(self, contract_json: str, timeout_seconds: int) -> DeepSeekReviewResponse:
        if self.endpoint != DIRECT_ENDPOINT or not self.api_key:
            return DeepSeekReviewResponse(
                0, None, None, None, None, "direct endpoint or API key unavailable"
            )
        payload = {
            "model": self.model,
            "reasoning_effort": self.effort,
            "messages": [
                {
                    "role": "system",
                    "content": self._system_prompt(),
                },
                {"role": "user", "content": contract_json},
            ],
            "temperature": 0,
            "max_tokens": CONTRACT_REVIEW_MAX_OUTPUT_TOKENS,
            "response_format": {"type": "json_object"},
        }
        client = self.client or httpx.AsyncClient(timeout=timeout_seconds)
        owned = self.client is None
        diagnostics = DeepSeekResponseDiagnostics(http_status=0)
        try:
            response = await client.post(
                self.endpoint,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            diagnostics = DeepSeekResponseDiagnostics(http_status=response.status_code)
            if response.status_code != 200:
                return DeepSeekReviewResponse(
                    response.status_code,
                    None,
                    None,
                    None,
                    None,
                    f"HTTP {response.status_code}",
                    DeepSeekResponseDiagnostics(http_status=response.status_code),
                )
            body = response.json()
            diagnostics = _response_diagnostics(response.status_code, body, self.model)
            if not isinstance(body, dict):
                return DeepSeekReviewResponse(
                    0,
                    None,
                    None,
                    None,
                    None,
                    "malformed response body",
                    diagnostics,
                )
            choices = body.get("choices")
            if not isinstance(choices, list) or len(choices) != 1:
                return DeepSeekReviewResponse(
                    0,
                    None,
                    diagnostics.returned_model,
                    None,
                    None,
                    "malformed choices",
                    diagnostics,
                )
            choice = choices[0]
            if not isinstance(choice, dict):
                return DeepSeekReviewResponse(
                    0, None, diagnostics.returned_model, None, None, "malformed choice", diagnostics
                )
            message = choice.get("message")
            if not isinstance(message, dict):
                return DeepSeekReviewResponse(
                    0,
                    None,
                    diagnostics.returned_model,
                    None,
                    None,
                    "malformed message",
                    diagnostics,
                )
            content = message.get("content")
            prompt_tokens = diagnostics.prompt_tokens
            completion_tokens = diagnostics.completion_tokens
            response_error = None
            if diagnostics.finish_reason != "stop":
                response_error = f"incomplete generation ({diagnostics.finish_reason or 'unknown'})"
            elif not diagnostics.usage_valid:
                response_error = "provider token usage is missing or inconsistent"
            return DeepSeekReviewResponse(
                0,
                content if isinstance(content, str) else None,
                diagnostics.returned_model,
                prompt_tokens,
                completion_tokens,
                response_error,
                diagnostics,
            )
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            return DeepSeekReviewResponse(
                0, None, None, None, None, type(exc).__name__, diagnostics
            )
        finally:
            if owned:
                await client.aclose()

    def _system_prompt(self) -> str:
        if self.review_stage == "CONTRACT_REVIEW":
            purpose = (
                "You are an independent, read-only reviewer of an OpenSpec contract. "
                "Evaluate specification consistency only. Do not evaluate implementation, "
                "authorize APPLY, make product decisions, or approve merge."
            )
            verdicts = "CONTRACT_ACCEPTED or CONTRACT_CHANGES_REQUIRED"
        else:
            purpose = (
                "You are an independent, read-only code reviewer. Evaluate only the exact "
                "candidate source and deterministic execution evidence in the supplied payload. "
                "Do not modify files, authorize APPLY, make product decisions, or approve merge. "
                "A favorable review is not human merge authorization."
            )
            verdicts = "READY_TO_MERGE or CHANGES_REQUIRED"
        return (
            f"{purpose} Return one valid json object and no surrounding prose. The object "
            "must have exactly these keys: verdict, summary, findings. The verdict must be "
            f"one of: {verdicts}. Each findings item must have exactly severity, location, "
            "violated_requirement, expected_correction; severity is BLOCKER, MAJOR, or MINOR, "
            "and location may be null. Example JSON: "
            '{"verdict":"' + verdicts.split(" or ")[0] + '","summary":"Review summary",'
            '"findings":[]}.'
        )


class ContractReviewService:
    """Executes only the pre-APPLY CONTRACT_REVIEW stage using existing authorities."""

    def __init__(
        self,
        uow: PersistenceUnitOfWork,
        *,
        health_service: ProviderHealthService | None = None,
        budget_service: BudgetService | None = None,
        runner: DeepSeekContractReviewRunner | None = None,
        app_config: AppConfig | None = None,
        timeout_seconds: int = 90,
    ):
        self.uow = uow
        self.health = health_service or ProviderHealthService(uow)
        self.budget = budget_service or BudgetService(uow)
        self.runner = runner
        self.app_config = app_config or load_config()
        self.timeout_seconds = timeout_seconds

    async def review_before_apply(
        self,
        project: Project,
        run: OrchestrationRun,
        job: Job,
        worktree_path: str | Path,
        *,
        claim_context: RecoveryClaimContext | None = None,
    ) -> ContractReviewResult:
        if (
            run.project_id != project.project_id
            or run.change_name != job.change_name
            or job.project_id != project.project_id
            or run.active_job_id != job.job_id
        ):
            return ContractReviewResult(False, None, None, "CONTRACT_REVIEW_IDENTITY_MISMATCH")
        try:
            contract_payload, contract_hash = self._read_contract(
                project, job.change_name, worktree_path
            )
        except (OSError, ValueError) as exc:
            return ContractReviewResult(
                False, None, None, f"CONTRACT_REVIEW_PREFLIGHT_BLOCKED:{exc}"
            )
        try:
            project_config = self.app_config.projects.get(project.project_id) or ProjectConfig(
                repository=project.repository,
                base_branch=project.base_branch,
                openspec_path=project.openspec_path,
                implementer=project.implementer,
                reviewer=project.reviewer,
                external_providers_allowed=project.external_providers_allowed,
            )
            profile = resolve_stage_profile(
                project_config, OpenSpecStage.CONTRACT_REVIEW, app_config=self.app_config
            )
        except StageProfileError as exc:
            return ContractReviewResult(
                False,
                None,
                contract_hash,
                f"CONTRACT_REVIEW_PROFILE_UNAVAILABLE:{exc}",
                waiting=True,
            )

        adapter = get_provider_adapter("deepseek", self.app_config)
        provider_config = self.app_config.providers.get("deepseek")
        if (
            not provider_config
            or not provider_config.enabled
            or "deepseek" not in project.external_providers_allowed
        ):
            return ContractReviewResult(
                False, None, contract_hash, "DEEPSEEK_OWNER_POLICY_DISABLED", waiting=True
            )
        prior_reviews = [
            review
            for review in self.uow.reviews.list_by_job(job.job_id)
            if review.review_stage == "CONTRACT_REVIEW"
        ]
        previous = prior_reviews[0] if prior_reviews else None
        if previous:
            history_identity_matches = all(
                review.project_id == project.project_id
                and review.job_id == job.job_id
                and review.change_name == job.change_name
                and review.orchestration_run_id == run.run_id
                and review.candidate_generation == run.current_generation
                and review.review_stage == "CONTRACT_REVIEW"
                and review.contract_hash == contract_hash
                and review.candidate_sha == contract_hash
                and review.provider == "deepseek"
                and review.reviewer_role == "deepseek"
                and review.billing_origin == "deepseek_direct"
                and bool(review.account_fingerprint)
                and bool(review.reviewer_model)
                for review in prior_reviews
            )
            if not history_identity_matches:
                return ContractReviewResult(
                    False,
                    previous.review_id,
                    contract_hash,
                    "CONTRACT_REVIEW_RECOVERY_IDENTITY_CONTRADICTORY",
                )
            if any(
                review.status == ReviewStatus.REVIEW_COMPLETED
                and review.verdict == ReviewVerdict.CONTRACT_CHANGES_REQUIRED
                for review in prior_reviews
            ):
                return ContractReviewResult(
                    False,
                    previous.review_id,
                    contract_hash,
                    "CONTRACT_REVIEW_CHANGES_REQUIRED_BLOCKS_RETRY",
                )
            reservation = (
                self.uow.budget_reservations.get_by_id(previous.budget_reservation_id)
                if previous.budget_reservation_id
                else None
            )
            usage_recorded = any(
                event.event_type == EventType.BUDGET_SETTLED
                and event.operation_id == job.job_id
                and event.payload.get("review_id") == previous.review_id
                for event in self.uow.events.list_events(
                    project_id=project.project_id, change_id=job.change_name, limit=10000
                )
            )
            exact_accepted_checkpoint = bool(
                previous.project_id == project.project_id
                and previous.job_id == job.job_id
                and previous.change_name == job.change_name
                and previous.orchestration_run_id == run.run_id
                and previous.candidate_generation == run.current_generation
                and previous.review_stage == "CONTRACT_REVIEW"
                and previous.contract_hash == contract_hash
                and previous.candidate_sha == contract_hash
                and previous.provider == "deepseek"
                and previous.reviewer_role == "deepseek"
                and previous.reviewer_model == profile.model
                and previous.account_fingerprint
                and previous.billing_origin == "deepseek_direct"
                and (
                    bool(
                        reservation
                        and reservation.provider == "deepseek"
                        and reservation.account_fingerprint == previous.account_fingerprint
                        and reservation.canonical_model_identity == profile.model
                        and reservation.stage == "CONTRACT_REVIEW"
                        and reservation.billing_origin == "deepseek_direct"
                        and reservation.status == "SETTLED"
                    )
                    or (reservation is None and usage_recorded)
                )
            )
            if (
                exact_accepted_checkpoint
                and previous.status == ReviewStatus.REVIEW_COMPLETED
                and previous.verdict == ReviewVerdict.CONTRACT_ACCEPTED
            ):
                return ContractReviewResult(True, previous.review_id, contract_hash)
            recovery_block = self._failed_review_recovery_block(
                project=project,
                run=run,
                job=job,
                contract_hash=contract_hash,
                reviews=prior_reviews,
                claim_context=claim_context,
            )
            if recovery_block:
                return ContractReviewResult(
                    False,
                    previous.review_id,
                    contract_hash,
                    recovery_block,
                    waiting=True,
                )

        supported, _ = await adapter.check_model_supported(profile.model, effort=profile.effort)
        account_fingerprint = getattr(adapter, "account_fingerprint", None)
        if not supported or not account_fingerprint:
            return ContractReviewResult(
                False, None, contract_hash, "DEEPSEEK_ACCOUNT_MODEL_UNAVAILABLE", waiting=True
            )
        observed = await self.health.refresh_capacity_from_read_only_source(
            "deepseek", model=profile.model
        )
        health = self.health.get_existing_health("deepseek")
        if (
            not observed
            or not health
            or health.status != ProviderHealthStatus.AVAILABLE
            or not self.health.has_fresh_capacity_evidence(
                "deepseek",
                model=profile.model,
                account_fingerprint=account_fingerprint,
                quota_scope="deepseek_direct_account_balance",
            )
        ):
            return ContractReviewResult(
                False, None, contract_hash, "DEEPSEEK_CAPACITY_UNKNOWN_OR_EXHAUSTED", waiting=True
            )

        pricing = self.budget.get_verified_review_price_snapshot(
            provider="deepseek",
            account_fingerprint=account_fingerprint,
            model=profile.model,
            billing_origin="deepseek_direct",
        )
        if not pricing:
            return ContractReviewResult(
                False,
                None,
                contract_hash,
                "DEEPSEEK_DIRECT_PRICE_SNAPSHOT_UNAVAILABLE",
                waiting=True,
            )
        review_limits = self.app_config.providers.get("deepseek")
        configured_budget = review_limits.budget if review_limits else {}
        review_operation_id = generate_uuid()
        prompt_json = json.dumps(
            {
                "stage": "CONTRACT_REVIEW",
                "review_operation_id": review_operation_id,
                "project_id": project.project_id,
                "change_name": job.change_name,
                "run_id": run.run_id,
                "job_id": job.job_id,
                "base_sha": run.base_sha,
                "contract_hash": contract_hash,
                "manifest": contract_payload,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        # UTF-8 bytes conservatively bound prompt tokens before an optional cap.
        prompt_bound = len(prompt_json.encode("utf-8"))
        reservation, denial = self.budget.reserve_review_budget(
            project_id=project.project_id,
            run_id=run.run_id,
            job_id=job.job_id,
            change_id=job.change_name,
            provider="deepseek",
            account_fingerprint=account_fingerprint,
            model=profile.model,
            stage="CONTRACT_REVIEW",
            billing_origin="deepseek_direct",
            pricing_snapshot_id=pricing.snapshot_id,
            prompt_token_upper_bound=prompt_bound,
            max_output_tokens=CONTRACT_REVIEW_MAX_OUTPUT_TOKENS,
            idempotency_key=_review_reservation_key(
                run_id=run.run_id,
                job_id=job.job_id,
                stage="CONTRACT_REVIEW",
                contract_hash=contract_hash,
                operation_id=review_operation_id,
            ),
            maximum_stage_usd=configured_budget.get("maximum_contract_review_usd"),
            maximum_combined_usd=configured_budget.get("maximum_combined_review_usd"),
        )
        if denial:
            return ContractReviewResult(False, None, contract_hash, denial, waiting=True)

        review = Review(
            review_id=review_operation_id,
            job_id=job.job_id,
            project_id=project.project_id,
            change_name=job.change_name,
            reviewer_role="deepseek",
            reviewer_model=profile.model,
            review_stage="CONTRACT_REVIEW",
            contract_hash=contract_hash,
            provider="deepseek",
            account_fingerprint=account_fingerprint,
            budget_authorization_id=None,
            budget_reservation_id=reservation.reservation_id if reservation else None,
            billing_origin="deepseek_direct",
            orchestration_run_id=run.run_id,
            candidate_generation=run.current_generation,
            candidate_sha=contract_hash,
            base_sha=run.base_sha,
            manifest_id=contract_hash,
            manifest_hash=contract_hash,
            status=ReviewStatus.REVIEW_PENDING,
        )
        self.uow.reviews.save(review)
        self.uow.events.save(
            Event(
                event_type=EventType.CONTRACT_REVIEW_OPERATION_STARTED,
                project_id=project.project_id,
                change_id=job.change_name,
                operation_id=review.review_id,
                payload={
                    "review_operation_id": review.review_id,
                    "review_stage": "CONTRACT_REVIEW",
                    "contract_hash": contract_hash,
                    "run_id": run.run_id,
                    "job_id": job.job_id,
                    "generation": run.current_generation,
                    "attempt_number": len(prior_reviews) + 1,
                    "supersedes_review_id": previous.review_id if previous else None,
                    "reservation_id": reservation.reservation_id if reservation else None,
                    "idempotency_key": reservation.idempotency_key if reservation else None,
                },
                timestamp=utc_now(),
            )
        )
        self.uow.commit()
        # A durable RUNNING state is a dispatch checkpoint. After interruption it
        # is never replayed blindly because the remote request may have been billed.
        self.uow.reviews.transition(review.review_id, ReviewStatus.REVIEW_RUNNING.value)
        self.uow.commit()

        api_key = getattr(adapter, "authenticated_api_key", None)
        if self.runner is None:
            runner = DeepSeekContractReviewRunner(
                api_key=api_key, model=profile.model, effort=profile.effort
            )
        else:
            runner = self.runner
            if (
                getattr(runner, "model", None) != profile.model
                or getattr(runner, "effort", None) != profile.effort
            ):
                if reservation:
                    self.budget.release_reservation(reservation.reservation_id, "profile_mismatch")
                self.uow.reviews.transition(
                    review.review_id,
                    ReviewStatus.REVIEW_FAILED.value,
                    error_message="Reviewer model/effort does not match the authorized profile.",
                )
                self.uow.commit()
                return ContractReviewResult(
                    False, review.review_id, contract_hash, "REVIEW_PROFILE_MISMATCH"
                )
        try:
            result = await runner.review(prompt_json, self.timeout_seconds)
        except Exception as exc:
            if reservation:
                self.budget.mark_unresolved(reservation.reservation_id)
            self.uow.reviews.transition(
                review.review_id,
                ReviewStatus.REVIEW_FAILED.value,
                error_message=f"DeepSeek review outcome is ambiguous ({type(exc).__name__}).",
            )
            self.uow.commit()
            return ContractReviewResult(
                False,
                review.review_id,
                contract_hash,
                "DEEPSEEK_REVIEW_OUTCOME_AMBIGUOUS",
                waiting=True,
            )
        persist_deepseek_response_diagnostic(self.uow, review, result)
        diagnostics = result.response_diagnostics
        usage_verified = bool(
            result.model == profile.model
            and diagnostics
            and diagnostics.http_status == 200
            and diagnostics.model_matches_request is True
            and diagnostics.usage_valid
            and isinstance(result.prompt_tokens, int)
            and isinstance(result.completion_tokens, int)
            and result.prompt_tokens == diagnostics.prompt_tokens
            and result.completion_tokens == diagnostics.completion_tokens
        )
        usage_settled = False
        if usage_verified:
            actual_cost = (
                Decimal(result.prompt_tokens) * pricing.prompt_price_per_token
                + Decimal(result.completion_tokens) * pricing.output_price_per_token
                + pricing.additional_cost_per_request
            )
            if reservation:
                usage_settled = bool(
                    self.budget.settle_reservation(
                        reservation.reservation_id,
                        actual_cost,
                        prompt_tokens=result.prompt_tokens,
                        completion_tokens=result.completion_tokens,
                        total_tokens=result.prompt_tokens + result.completion_tokens,
                    )
                )
            else:
                self.budget.record_unreserved_review_usage(
                    project_id=project.project_id,
                    job_id=job.job_id,
                    change_id=job.change_name,
                    provider="deepseek",
                    account_fingerprint=account_fingerprint,
                    model=profile.model,
                    stage="CONTRACT_REVIEW",
                    billing_origin="deepseek_direct",
                    review_id=review.review_id,
                    prompt_tokens=result.prompt_tokens,
                    completion_tokens=result.completion_tokens,
                    actual_cost_usd=actual_cost,
                )
                usage_settled = True
        elif reservation:
            self.budget.mark_unresolved(reservation.reservation_id)
        if (
            result.exit_code != 0
            or result.error
            or result.model != profile.model
            or not result.content
            or not isinstance(result.prompt_tokens, int)
            or isinstance(result.prompt_tokens, bool)
            or result.prompt_tokens < 0
            or not isinstance(result.completion_tokens, int)
            or isinstance(result.completion_tokens, bool)
            or result.completion_tokens < 0
        ):
            self.uow.reviews.transition(
                review.review_id,
                ReviewStatus.REVIEW_FAILED.value,
                error_message=result.error
                or "DeepSeek response identity, usage, or output is incomplete.",
            )
            self.uow.commit()
            return ContractReviewResult(
                False, review.review_id, contract_hash, "DEEPSEEK_REVIEW_RESPONSE_UNVERIFIABLE"
            )
        try:
            parsed = ContractReviewVerdictPayload.model_validate_json(result.content)
        except (ValidationError, ValueError):
            self.uow.reviews.transition(
                review.review_id,
                ReviewStatus.REVIEW_FAILED.value,
                error_message="DeepSeek contract review did not match the strict structured schema.",
            )
            self.uow.commit()
            return ContractReviewResult(
                False, review.review_id, contract_hash, "CONTRACT_REVIEW_MALFORMED"
            )
        if parsed.verdict not in {
            ReviewVerdict.CONTRACT_ACCEPTED,
            ReviewVerdict.CONTRACT_CHANGES_REQUIRED,
        }:
            self.uow.reviews.transition(
                review.review_id,
                ReviewStatus.REVIEW_FAILED.value,
                error_message="Code-review verdict cannot be substituted for contract-review evidence.",
            )
            self.uow.commit()
            return ContractReviewResult(
                False, review.review_id, contract_hash, "CROSS_STAGE_REVIEW_EVIDENCE_DENIED"
            )
        if not usage_settled:
            return ContractReviewResult(
                False, review.review_id, contract_hash, "REVIEW_COST_RECONCILIATION_FAILED"
            )
        review = self.uow.reviews.get_by_id(review.review_id)
        review.verdict = parsed.verdict
        review.summary = parsed.summary
        review.status = ReviewStatus.REVIEW_COMPLETED
        review.updated_at = utc_now()
        self.uow.reviews.save(review)
        for item in parsed.findings:
            self.uow.review_findings.save(
                ReviewFinding(
                    review_id=review.review_id,
                    severity=item.severity,
                    location=item.location,
                    violated_requirement=item.violated_requirement,
                    expected_correction=item.expected_correction,
                )
            )
        self.uow.events.save(
            Event(
                event_type=EventType.CONTRACT_REVIEW_COMPLETED,
                project_id=project.project_id,
                change_id=job.change_name,
                operation_id=job.job_id,
                payload={
                    "review_id": review.review_id,
                    "review_stage": "CONTRACT_REVIEW",
                    "contract_hash": contract_hash,
                    "run_id": run.run_id,
                    "job_id": job.job_id,
                    "provider": "deepseek",
                    "model": profile.model,
                    "account_fingerprint": account_fingerprint,
                    "budget_authorization_id": None,
                    "budget_reservation_id": reservation.reservation_id if reservation else None,
                    "verdict": parsed.verdict.value,
                },
                timestamp=utc_now(),
            )
        )
        self.uow.commit()
        accepted = parsed.verdict == ReviewVerdict.CONTRACT_ACCEPTED
        return ContractReviewResult(
            accepted,
            review.review_id,
            contract_hash,
            None if accepted else "CONTRACT_CHANGES_REQUIRED",
        )

    def _failed_review_recovery_block(
        self,
        *,
        project: Project,
        run: OrchestrationRun,
        job: Job,
        contract_hash: str,
        reviews: list[Review],
        claim_context: RecoveryClaimContext | None,
    ) -> str | None:
        """Authorize only a distinct review following a canonical fenced CONTINUE."""
        if not reviews:
            return "CONTRACT_REVIEW_RECOVERY_HISTORY_MISSING"
        for review in reviews:
            if (
                review.project_id != project.project_id
                or review.job_id != job.job_id
                or review.change_name != job.change_name
                or review.orchestration_run_id != run.run_id
                or review.candidate_generation != run.current_generation
                or review.review_stage != "CONTRACT_REVIEW"
                or review.contract_hash != contract_hash
                or review.candidate_sha != contract_hash
                or review.provider != "deepseek"
                or review.reviewer_role != "deepseek"
                or review.billing_origin != "deepseek_direct"
                or not review.account_fingerprint
                or not review.reviewer_model
            ):
                return "CONTRACT_REVIEW_RECOVERY_IDENTITY_CONTRADICTORY"
            if review.status != ReviewStatus.REVIEW_FAILED:
                if review.status in {
                    ReviewStatus.REVIEW_PENDING,
                    ReviewStatus.REVIEW_RUNNING,
                    ReviewStatus.REVIEW_TIMED_OUT,
                }:
                    return "CONTRACT_REVIEW_OPERATION_STILL_UNRESOLVED"
                return "CONTRACT_REVIEW_COMPLETED_OR_NONFAILED_HISTORY_BLOCKS_RETRY"
            if not review.error_message:
                return "CONTRACT_REVIEW_FAILURE_EVIDENCE_MISSING"
            if review.budget_reservation_id:
                reservation = self.uow.budget_reservations.get_by_id(review.budget_reservation_id)
                if not reservation or (
                    reservation.project_id != project.project_id
                    or reservation.run_id != run.run_id
                    or reservation.job_id != job.job_id
                    or reservation.change_id != job.change_name
                    or reservation.provider != "deepseek"
                    or reservation.account_fingerprint != review.account_fingerprint
                    or reservation.canonical_model_identity != review.reviewer_model
                    or reservation.stage != "CONTRACT_REVIEW"
                    or reservation.billing_origin != "deepseek_direct"
                    or reservation.status not in {"UNRESOLVED", "SETTLED"}
                ):
                    return "CONTRACT_REVIEW_PRIOR_USAGE_IDENTITY_UNVERIFIED"
            else:
                settled_events = [
                    event
                    for event in self.uow.events.list_events(
                        project_id=project.project_id, change_id=job.change_name, limit=10000
                    )
                    if event.event_type == EventType.BUDGET_SETTLED
                    and event.payload.get("review_id") == review.review_id
                    and event.payload.get("provider") == "deepseek"
                    and event.payload.get("account_fingerprint") == review.account_fingerprint
                    and event.payload.get("model") == review.reviewer_model
                    and event.payload.get("stage") == "CONTRACT_REVIEW"
                    and event.payload.get("billing_origin") == "deepseek_direct"
                ]
                if not settled_events:
                    return "CONTRACT_REVIEW_PRIOR_USAGE_EVIDENCE_MISSING"

        if not run.is_active or run.active_job_id != job.job_id or job.status.value != "RUNNING":
            return "CONTRACT_REVIEW_RECOVERY_RUN_NOT_ACTIVE"
        if job.candidate_sha or run.current_candidate_sha:
            return "CONTRACT_REVIEW_RECOVERY_CANDIDATE_EXISTS"
        if run.current_stage not in {
            OrchestrationStage.ADMITTED,
            OrchestrationStage.PREPARING_EXECUTION,
            OrchestrationStage.IMPLEMENTING,
        }:
            return "CONTRACT_REVIEW_RECOVERY_STAGE_INVALID"
        if not claim_context or claim_context.claim_key != f"run:{run.run_id}":
            return "CONTRACT_REVIEW_RECOVERY_CLAIM_REQUIRED"
        try:
            validate_claim_context_authoritative(self.uow, claim_context)
        except Exception:
            return "CONTRACT_REVIEW_RECOVERY_CLAIM_STALE"

        decisions_repo = getattr(self.uow, "recovery_decisions", None)
        claims_repo = getattr(self.uow, "claims", None)
        if not decisions_repo or not claims_repo:
            return "CONTRACT_REVIEW_RECOVERY_AUTHORITY_UNAVAILABLE"
        decisions = decisions_repo.list_by_claim_key(claim_context.claim_key)
        if not decisions:
            return "CONTRACT_REVIEW_RECOVERY_DECISION_MISSING"
        decision = max(decisions, key=lambda item: item.created_at)
        latest_review_at = max(item.updated_at for item in reviews)
        if (
            decision.claim_key != claim_context.claim_key
            or decision.identity_type != "RUN"
            or decision.identity_id != run.run_id
            or decision.project_id != project.project_id
            or decision.change_name != job.change_name
            or decision.source != RecoverySource.CONTROL_PLANE
            or decision.planned_action != "DRIVE_CONTINUATION"
            or decision.classification != RecoveryClassification.RESUME_SAFE_CHECKPOINT
            or decision.status != RecoveryDecisionStatus.EXECUTING
            or decision.fence_token != claim_context.fence_token
            or decision.created_at <= latest_review_at
        ):
            return "CONTRACT_REVIEW_RECOVERY_DECISION_NOT_CURRENT_CONTINUE"
        cycle_decisions = decisions_repo.list_by_cycle(decision.cycle_id)
        if len(cycle_decisions) != 1 or cycle_decisions[0].decision_id != decision.decision_id:
            return "CONTRACT_REVIEW_RECOVERY_DECISION_AMBIGUOUS"
        claim = claims_repo.get_by_key(claim_context.claim_key)
        if (
            not claim
            or not claim.is_active
            or claim.owner_instance_id != claim_context.owner_instance_id
            or claim.fence_token != claim_context.fence_token
        ):
            return "CONTRACT_REVIEW_RECOVERY_CLAIM_NOT_AUTHORITATIVE"

        action_repo = getattr(self.uow, "orchestration_external_actions", None)
        if not action_repo:
            return "CONTRACT_REVIEW_RECOVERY_ACTION_AUTHORITY_UNAVAILABLE"
        unresolved_statuses = {
            ExternalActionStatus.RESERVED,
            ExternalActionStatus.EXECUTING,
            ExternalActionStatus.UNKNOWN,
            ExternalActionStatus.AMBIGUOUS,
        }
        if any(
            action.status in unresolved_statuses for action in action_repo.list_by_run(run.run_id)
        ):
            return "CONTRACT_REVIEW_RECOVERY_EXTERNAL_ACTION_UNRESOLVED"
        return None

    @staticmethod
    def _read_contract(project: Project, change_name: str, worktree_path: str | Path):
        root = Path(worktree_path).resolve(strict=True)
        change_dir = root / project.openspec_path / "changes" / change_name
        if change_dir.is_symlink() or not change_dir.is_dir():
            raise ValueError("bound OpenSpec change directory is missing or a symlink")
        change_dir = change_dir.resolve(strict=True)
        change_dir.relative_to(root)
        paths = [change_dir / "proposal.md", change_dir / "design.md", change_dir / "tasks.md"]
        specs_root = change_dir / "specs"
        if specs_root.exists():
            if specs_root.is_symlink():
                raise ValueError("OpenSpec specs directory is a symlink")
            paths.extend(sorted(specs_root.rglob("*.md")))
        files = []
        for path in paths:
            if not path.exists():
                if path.name == "design.md":
                    continue
                raise ValueError(
                    f"required contract artifact missing: {path.relative_to(change_dir)}"
                )
            if path.is_symlink() or not path.is_file():
                raise ValueError("OpenSpec contract contains a non-regular artifact")
            resolved = path.resolve(strict=True)
            resolved.relative_to(change_dir)
            content = resolved.read_text(encoding="utf-8")
            files.append({"path": resolved.relative_to(change_dir).as_posix(), "content": content})
        if not files:
            raise ValueError("OpenSpec contract has no reviewable artifacts")
        canonical = json.dumps(files, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if len(canonical.encode("utf-8")) > 1_000_000:
            raise ValueError("OpenSpec contract exceeds the bounded review input limit")
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return {"files": files}, digest
