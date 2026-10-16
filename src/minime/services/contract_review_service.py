"""Governed, read-only DeepSeek Direct review of one OpenSpec contract checkpoint."""

from __future__ import annotations

import hashlib
import json
import os
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
from minime.domain.enums import EventType, ProviderHealthStatus, ReviewStatus, ReviewVerdict
from minime.domain.interfaces import PersistenceUnitOfWork
from minime.domain.models import (
    ContractReviewVerdictPayload,
    Event,
    Job,
    OrchestrationRun,
    Project,
    Review,
    ReviewFinding,
    utc_now,
)
from minime.services.budget_service import BudgetService
from minime.services.provider_health_service import ProviderHealthService

DIRECT_ENDPOINT = "https://api.deepseek.com/chat/completions"


def _review_reservation_key(*, run_id: str, job_id: str, stage: str, contract_hash: str) -> str:
    """Return a bounded deterministic key for the persisted VARCHAR(128) column."""
    identity = json.dumps([run_id, job_id, stage, contract_hash], separators=(",", ":")).encode(
        "utf-8"
    )
    return f"review:v1:{hashlib.sha256(identity).hexdigest()}"


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
                    "content": (
                        "You are an independent, read-only reviewer of an OpenSpec contract. "
                        "Evaluate specification consistency only. Do not evaluate implementation, "
                        "authorize APPLY, make product decisions, or approve merge. "
                        "Return only the required JSON schema."
                        if self.review_stage == "CONTRACT_REVIEW"
                        else "You are an independent, read-only code reviewer. Evaluate the exact "
                        "candidate source and deterministic execution evidence in the supplied "
                        "payload. Do not modify files, authorize APPLY, make product decisions, "
                        "or approve merge. A favorable review is not human merge authorization. "
                        "Return only the required JSON schema."
                    ),
                },
                {"role": "user", "content": contract_json},
            ],
            "temperature": 0,
            "max_tokens": 2048,
            "response_format": {"type": "json_object"},
        }
        client = self.client or httpx.AsyncClient(timeout=timeout_seconds)
        owned = self.client is None
        try:
            response = await client.post(
                self.endpoint,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            if response.status_code != 200:
                return DeepSeekReviewResponse(
                    response.status_code, None, None, None, None, f"HTTP {response.status_code}"
                )
            body = response.json()
            choices = body.get("choices")
            if not isinstance(choices, list) or len(choices) != 1:
                return DeepSeekReviewResponse(
                    0, None, body.get("model"), None, None, "malformed choices"
                )
            content = choices[0].get("message", {}).get("content")
            usage = body.get("usage") or {}
            prompt_tokens = usage.get("prompt_tokens")
            completion_tokens = usage.get("completion_tokens")
            return DeepSeekReviewResponse(
                0,
                content if isinstance(content, str) else None,
                body.get("model") if isinstance(body.get("model"), str) else None,
                prompt_tokens
                if isinstance(prompt_tokens, int)
                and not isinstance(prompt_tokens, bool)
                and prompt_tokens >= 0
                else None,
                completion_tokens
                if isinstance(completion_tokens, int)
                and not isinstance(completion_tokens, bool)
                and completion_tokens >= 0
                else None,
            )
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            return DeepSeekReviewResponse(0, None, None, None, None, type(exc).__name__)
        finally:
            if owned:
                await client.aclose()


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
        self, project: Project, run: OrchestrationRun, job: Job, worktree_path: str | Path
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
        previous = self.uow.reviews.get_by_job_stage(job.job_id, "CONTRACT_REVIEW")
        if previous:
            reservation = (
                self.uow.budget_reservations.get_by_id(previous.budget_reservation_id)
                if previous.budget_reservation_id
                else None
            )
            authorization = (
                self.uow.operator_actions.get_by_request_id(previous.budget_authorization_id)
                if previous.budget_authorization_id
                else None
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
                and reservation is not None
                and reservation.provider == "deepseek"
                and reservation.account_fingerprint == previous.account_fingerprint
                and reservation.canonical_model_identity == profile.model
                and reservation.stage == "CONTRACT_REVIEW"
                and reservation.billing_origin == "deepseek_direct"
                and reservation.authorization_id == previous.budget_authorization_id
                and reservation.status == "SETTLED"
                and authorization is not None
                and authorization.job_id == job.job_id
                and authorization.run_id == run.run_id
                and authorization.status.value == "COMPLETED"
                and authorization.action_type.value == "AUTHORIZE_DEEPSEEK_REVIEW"
                and authorization.project_id == project.project_id
                and authorization.change_name == job.change_name
                and authorization.result_payload_json.get("authorization", {}).get("provider")
                == "deepseek"
                and authorization.result_payload_json.get("authorization", {}).get(
                    "account_fingerprint"
                )
                == previous.account_fingerprint
                and authorization.result_payload_json.get("authorization", {}).get("model")
                == profile.model
                and authorization.result_payload_json.get("authorization", {}).get("stage")
                == "CONTRACT_REVIEW"
                and authorization.result_payload_json.get("authorization", {}).get("billing_origin")
                == "deepseek_direct"
                and authorization.result_payload_json.get("authorization", {}).get(
                    "pricing_snapshot_id"
                )
                == reservation.pricing_snapshot_id
                and authorization.result_payload_json.get("authorization", {}).get("run_id")
                == run.run_id
                and authorization.result_payload_json.get("authorization", {}).get("job_id")
                == job.job_id
            )
            if (
                exact_accepted_checkpoint
                and previous.status == ReviewStatus.REVIEW_COMPLETED
                and previous.verdict == ReviewVerdict.CONTRACT_ACCEPTED
            ):
                return ContractReviewResult(True, previous.review_id, contract_hash)
            return ContractReviewResult(
                False,
                previous.review_id,
                contract_hash,
                "CONTRACT_REVIEW_ALREADY_STARTED_OR_FAILED; refusing duplicate paid dispatch",
                waiting=previous.status == ReviewStatus.REVIEW_RUNNING,
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

        authorization = self._find_authorization(run, job, profile.model, account_fingerprint)
        if not authorization:
            return ContractReviewResult(
                False,
                None,
                contract_hash,
                "DEEPSEEK_CONTRACT_REVIEW_BUDGET_NOT_AUTHORIZED",
                waiting=True,
            )
        auth = authorization.result_payload_json["authorization"]
        prompt_json = json.dumps(
            {
                "stage": "CONTRACT_REVIEW",
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
        # Bytes are a conservative upper bound on token count; if this makes the
        # explicit authorization insufficient, no provider request is made.
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
            pricing_snapshot_id=str(auth["pricing_snapshot_id"]),
            prompt_token_upper_bound=prompt_bound,
            max_output_tokens=2048,
            idempotency_key=_review_reservation_key(
                run_id=run.run_id,
                job_id=job.job_id,
                stage="CONTRACT_REVIEW",
                contract_hash=contract_hash,
            ),
        )
        if not reservation:
            return ContractReviewResult(False, None, contract_hash, denial, waiting=True)

        review = Review(
            job_id=job.job_id,
            project_id=project.project_id,
            change_name=job.change_name,
            reviewer_role="deepseek",
            reviewer_model=profile.model,
            review_stage="CONTRACT_REVIEW",
            contract_hash=contract_hash,
            provider="deepseek",
            account_fingerprint=account_fingerprint,
            budget_authorization_id=authorization.action_request_id,
            budget_reservation_id=reservation.reservation_id,
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
                self.budget.mark_unresolved(reservation.reservation_id)
                self.uow.reviews.transition(
                    review.review_id,
                    ReviewStatus.REVIEW_FAILED.value,
                    error_message="Reviewer model/effort does not match the authorized profile.",
                )
                self.uow.commit()
                return ContractReviewResult(
                    False, review.review_id, contract_hash, "REVIEW_PROFILE_MISMATCH"
                )
        result = await runner.review(prompt_json, self.timeout_seconds)
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
            self.budget.mark_unresolved(reservation.reservation_id)
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
            self.budget.mark_unresolved(reservation.reservation_id)
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
            self.budget.mark_unresolved(reservation.reservation_id)
            self.uow.reviews.transition(
                review.review_id,
                ReviewStatus.REVIEW_FAILED.value,
                error_message="Code-review verdict cannot be substituted for contract-review evidence.",
            )
            self.uow.commit()
            return ContractReviewResult(
                False, review.review_id, contract_hash, "CROSS_STAGE_REVIEW_EVIDENCE_DENIED"
            )
        snapshot = self.uow.pricing_snapshots.get_by_id(reservation.pricing_snapshot_id)
        actual_cost = (
            Decimal(result.prompt_tokens) * snapshot.prompt_price_per_token
            + Decimal(result.completion_tokens) * snapshot.output_price_per_token
            + snapshot.additional_cost_per_request
        )
        settled = self.budget.settle_reservation(
            reservation.reservation_id,
            actual_cost,
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            total_tokens=result.prompt_tokens + result.completion_tokens,
        )
        if settled is None:
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
                    "budget_authorization_id": authorization.action_request_id,
                    "budget_reservation_id": reservation.reservation_id,
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

    def _find_authorization(self, run: OrchestrationRun, job: Job, model: str, account: str):
        actions = self.uow.operator_actions.list_by_run(run.run_id)
        for action in actions:
            auth = action.result_payload_json.get("authorization", {})
            if (
                action.action_type.value == "AUTHORIZE_DEEPSEEK_REVIEW"
                and action.status.value == "COMPLETED"
                and action.project_id == run.project_id
                and action.change_name == job.change_name
                and action.run_id == run.run_id
                and action.job_id == job.job_id
                and auth.get("run_id") == run.run_id
                and auth.get("job_id") == job.job_id
                and auth.get("stage") == "CONTRACT_REVIEW"
                and auth.get("provider") == "deepseek"
                and auth.get("model") == model
                and auth.get("account_fingerprint") == account
                and auth.get("billing_origin") == "deepseek_direct"
            ):
                return action
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
