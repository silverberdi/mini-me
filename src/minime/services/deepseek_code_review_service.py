"""Candidate-bound, read-only DeepSeek Direct code review using R01 authorities."""

from __future__ import annotations

import hashlib
import json
import subprocess
import time
from dataclasses import dataclass
from dataclasses import replace as dataclass_replace
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Any

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
    JobStatus,
    OrchestrationStopOutcome,
    ProviderHealthStatus,
    ReviewStatus,
    ReviewVerdict,
)
from minime.domain.interfaces import PersistenceUnitOfWork
from minime.domain.models import (
    CandidateManifest,
    Event,
    Job,
    MetricFact,
    OrchestrationCandidate,
    OrchestrationRun,
    Project,
    RecoveryClaimContext,
    Review,
    ReviewFinding,
    ReviewVerdictPayload,
    utc_now,
    validate_claim_context_authoritative,
)
from minime.logging import redact_secrets
from minime.services.authorship_service import AuthorshipService
from minime.services.budget_service import BudgetService
from minime.services.candidate_integrity import validate_post_review_integrity
from minime.services.candidate_manifest import CandidateManifestService
from minime.services.contract_review_service import (
    CONTRACT_REVIEW_MAX_OUTPUT_TOKENS,
    DeepSeekContractReviewRunner,
    DeepSeekReviewResponse,
    persist_deepseek_response_diagnostic,
)
from minime.services.current_check_batch import validate_current_checks_batch
from minime.services.provider_health_service import ProviderHealthService
from minime.services.review_verdict_parser import parse_review_verdict

MAX_REVIEW_INPUT_BYTES = 1_000_000
MAX_REVIEW_DIFF_BYTES = 250_000
MAX_REVIEW_OUTPUT_TOKENS = 16384


class CodeReviewOutcomeKind(StrEnum):
    """Canonical read-only classification of persisted CODE_REVIEW evidence."""

    NO_PRIOR_REVIEW = "NO_PRIOR_REVIEW"
    VALID_INDEPENDENT_VERDICT = "VALID_INDEPENDENT_VERDICT"
    DEFINITIVE_UNUSABLE_SETTLED = "DEFINITIVE_UNUSABLE_SETTLED"
    UNRESOLVED_OR_AMBIGUOUS = "UNRESOLVED_OR_AMBIGUOUS"
    INTEGRITY_CONFLICT = "INTEGRITY_CONFLICT"


@dataclass(frozen=True)
class CodeReviewReconciliation:
    kind: CodeReviewOutcomeKind
    reason: str

    @property
    def permits_new_authorization(self) -> bool:
        return self.kind == CodeReviewOutcomeKind.DEFINITIVE_UNUSABLE_SETTLED


def reconcile_code_review_outcome(
    uow: PersistenceUnitOfWork,
    *,
    run: OrchestrationRun,
    job: Job,
    candidate: OrchestrationCandidate,
    manifest: CandidateManifest,
    claim_context: RecoveryClaimContext | None = None,
) -> CodeReviewReconciliation:
    """Classify CODE_REVIEW history from immutable, linked durable evidence.

    Diagnostic duration and reasoning telemetry are optional. Eligibility is
    derived only from provider response identity, usage, reservation/ledger
    linkage, finalized dispatch evidence and the frozen-candidate authority.
    This function is read-only; callers must still enforce the current claim and
    fence before any state transition or billable dispatch.
    """

    def decision(kind: CodeReviewOutcomeKind, reason: str) -> CodeReviewReconciliation:
        return CodeReviewReconciliation(kind, reason)

    if (
        run.current_candidate_sha != candidate.candidate_sha
        or run.base_sha != candidate.base_sha
        or run.current_generation != candidate.generation
        or run.active_job_id != job.job_id
        or run.project_id != job.project_id
        or run.change_name != job.change_name
        or candidate.run_id != run.run_id
        or not candidate.is_frozen
        or job.candidate_sha != candidate.candidate_sha
        or job.base_sha != candidate.base_sha
        or manifest.job_id != job.job_id
        or manifest.candidate_sha != candidate.candidate_sha
        or manifest.manifest_id != candidate.manifest_id
        or manifest.manifest_hash != candidate.manifest_hash
    ):
        return decision(
            CodeReviewOutcomeKind.INTEGRITY_CONFLICT,
            "candidate or run identity contradicts the frozen manifest",
        )

    reviews = [
        review
        for review in uow.reviews.list_by_job(job.job_id)
        if review.review_stage == "CODE_REVIEW"
    ]
    if not reviews:
        return decision(CodeReviewOutcomeKind.NO_PRIOR_REVIEW, "no prior CODE_REVIEW exists")

    for review in reviews:
        if (
            review.project_id != run.project_id
            or review.job_id != job.job_id
            or review.change_name != job.change_name
            or review.orchestration_run_id != run.run_id
            or review.candidate_generation != candidate.generation
            or review.candidate_sha != candidate.candidate_sha
            or review.base_sha != candidate.base_sha
            or review.manifest_id != manifest.manifest_id
            or review.manifest_hash != manifest.manifest_hash
        ):
            return decision(
                CodeReviewOutcomeKind.INTEGRITY_CONFLICT,
                "review identity contradicts the frozen candidate",
            )
        if (
            review.status == ReviewStatus.REVIEW_COMPLETED
            and review.verdict in {ReviewVerdict.READY_TO_MERGE, ReviewVerdict.CHANGES_REQUIRED}
            and review.provider == "deepseek"
            and review.reviewer_role == "deepseek"
            and review.billing_origin == "deepseek_direct"
            and review.account_fingerprint
            and review.reviewer_model
        ):
            eligible, _ = AuthorshipService().is_reviewer_eligible(job.job_id, "deepseek", uow)
            if eligible:
                return decision(
                    CodeReviewOutcomeKind.VALID_INDEPENDENT_VERDICT,
                    "an exact independent verdict is already persisted",
                )
            return decision(
                CodeReviewOutcomeKind.INTEGRITY_CONFLICT,
                "persisted verdict reviewer is not independent",
            )

    if (
        run.is_active
        or run.stop_outcome != OrchestrationStopOutcome.NEEDS_HUMAN
        or any(
            item.status != ReviewStatus.REVIEW_FAILED or item.verdict is not None
            for item in reviews
        )
    ):
        return decision(
            CodeReviewOutcomeKind.UNRESOLVED_OR_AMBIGUOUS,
            "review history is not a terminal inactive failure",
        )

    stop_details = run.stop_details or {}
    if stop_details.get("code") not in {
        "CODE_REVIEW_TERMINAL_FAILURE_SETTLED",
        # Compatibility for the already-persisted pre-fix checkpoint. It is
        # accepted only when every independent transport/accounting proof below
        # establishes that the old generic failure was actually terminal.
        "CODE_REVIEW_FAILED_CLOSED",
    }:
        return decision(
            CodeReviewOutcomeKind.UNRESOLVED_OR_AMBIGUOUS,
            "run is not held at a recognized terminal code-review checkpoint",
        )
    if any(
        observed is not None and observed != expected
        for observed, expected in (
            (stop_details.get("candidate_sha"), candidate.candidate_sha),
            (stop_details.get("base_sha"), candidate.base_sha),
            (stop_details.get("generation"), candidate.generation),
            (stop_details.get("manifest_id"), manifest.manifest_id),
            (stop_details.get("manifest_hash"), manifest.manifest_hash),
        )
    ):
        return decision(
            CodeReviewOutcomeKind.INTEGRITY_CONFLICT,
            "terminal checkpoint identity contradicts the frozen candidate",
        )
    claim = uow.claims.get_by_key(f"run:{run.run_id}")
    if claim_context is not None:
        if claim_context.claim_key != f"run:{run.run_id}":
            return decision(
                CodeReviewOutcomeKind.UNRESOLVED_OR_AMBIGUOUS,
                "current run claim is invalid or belongs to another operation",
            )
        try:
            validate_claim_context_authoritative(uow, claim_context)
        except Exception:
            return decision(
                CodeReviewOutcomeKind.UNRESOLVED_OR_AMBIGUOUS,
                "claim context is no longer authoritative",
            )
    elif claim is not None and claim.is_active:
        return decision(
            CodeReviewOutcomeKind.UNRESOLVED_OR_AMBIGUOUS,
            "a live run claim exists without this operation's claim context",
        )

    events = uow.events.list_events(
        project_id=run.project_id, change_id=run.change_name, limit=10000
    )
    reservations = uow.budget_reservations.list_by_project(run.project_id)
    ledger = uow.budget_ledger.list_by_project(run.project_id)
    actions = uow.operator_actions.list_by_run(run.run_id, limit=10000)

    for review in reviews:
        if (
            review.status != ReviewStatus.REVIEW_FAILED
            or review.verdict is not None
            or review.provider != "deepseek"
            or review.reviewer_role != "deepseek"
            or review.review_stage != "CODE_REVIEW"
            or review.project_id != run.project_id
            or review.job_id != job.job_id
            or review.change_name != job.change_name
            or review.orchestration_run_id != run.run_id
            or review.candidate_generation != candidate.generation
            or review.candidate_sha != candidate.candidate_sha
            or review.base_sha != candidate.base_sha
            or review.manifest_id != manifest.manifest_id
            or review.manifest_hash != manifest.manifest_hash
            or not review.budget_authorization_id
            or not review.budget_reservation_id
            or not review.account_fingerprint
            or not review.reviewer_model
            or review.billing_origin != "deepseek_direct"
        ):
            return decision(
                CodeReviewOutcomeKind.INTEGRITY_CONFLICT,
                "review record has incomplete or contradictory provider/candidate identity",
            )
        authorization_id = review.budget_authorization_id
        authorization_record = uow.operator_actions.get_by_request_id(authorization_id)
        authorization = (
            authorization_record.result_payload_json.get("authorization", {})
            if authorization_record
            else {}
        )
        if (
            not authorization_record
            or authorization_record.action_type.value != "AUTHORIZE_DEEPSEEK_CODE_REVIEW"
            or authorization_record.status.value != "COMPLETED"
            or authorization_record.run_id != run.run_id
            or authorization_record.job_id != job.job_id
            or authorization.get("run_id") != run.run_id
            or authorization.get("job_id") != job.job_id
            or authorization.get("candidate_sha") != candidate.candidate_sha
            or authorization.get("base_sha") != candidate.base_sha
            or authorization.get("generation") != candidate.generation
            or authorization.get("manifest_id") != manifest.manifest_id
            or authorization.get("manifest_hash") != manifest.manifest_hash
            or authorization.get("provider") != "deepseek"
            or authorization.get("account_fingerprint") != review.account_fingerprint
            or authorization.get("model") != review.reviewer_model
            or authorization.get("stage") != "REVIEW"
            or authorization.get("billing_origin") != "deepseek_direct"
            or authorization.get("action_request_id") != authorization_id
        ):
            return decision(
                CodeReviewOutcomeKind.INTEGRITY_CONFLICT,
                "review authorization identity or payload does not match",
            )
        reservation = next(
            (item for item in reservations if item.reservation_id == review.budget_reservation_id),
            None,
        )
        if (
            not reservation
            or reservation.status != "SETTLED"
            or reservation.authorization_id != authorization_id
            or reservation.project_id != run.project_id
            or reservation.run_id != run.run_id
            or reservation.job_id != job.job_id
            or reservation.change_id != job.change_name
            or reservation.provider != "deepseek"
            or reservation.account_fingerprint != review.account_fingerprint
            or reservation.canonical_model_identity != review.reviewer_model
            or reservation.stage != "REVIEW"
            or reservation.billing_origin != "deepseek_direct"
        ):
            return decision(
                CodeReviewOutcomeKind.UNRESOLVED_OR_AMBIGUOUS,
                "review does not have exactly one matching settled reservation",
            )
        settlement_entries = [
            item
            for item in ledger
            if item.reservation_id == reservation.reservation_id and item.entry_type == "SETTLEMENT"
        ]
        if len(settlement_entries) != 1:
            return decision(
                CodeReviewOutcomeKind.UNRESOLVED_OR_AMBIGUOUS,
                "settlement ledger does not contain exactly one settlement",
            )
        settlement = settlement_entries[0]
        diagnostic_events = [
            event
            for event in events
            if event.event_type == EventType.EVIDENCE_DIAGNOSTIC_RECORDED
            and event.payload.get("diagnostic_kind") == "DEEPSEEK_REVIEW_HTTP_RESPONSE"
            and event.payload.get("review_id") == review.review_id
        ]
        if len(diagnostic_events) != 1:
            return decision(
                CodeReviewOutcomeKind.UNRESOLVED_OR_AMBIGUOUS,
                "response diagnostic is missing or duplicated",
            )
        response = diagnostic_events[0].payload.get("response", {})
        prompt_tokens = response.get("prompt_tokens")
        completion_tokens = response.get("completion_tokens")
        total_tokens = response.get("total_tokens")
        request_duration_ms = response.get("request_duration_ms")
        finish_reason = response.get("finish_reason")
        content_length = response.get("content_length")
        content_length_valid = (
            isinstance(content_length, int)
            and not isinstance(content_length, bool)
            and content_length >= 0
        )
        definitively_unusable = bool(
            content_length_valid
            and (
                finish_reason == "length"
                or finish_reason == "stop"
                and content_length == 0
                or finish_reason == "stop"
                and content_length > 0
                and review.error_message
                == "DeepSeek code review did not match the strict verdict schema."
            )
        )
        token_values_valid = all(
            isinstance(value, int) and not isinstance(value, bool) and value >= 0
            for value in (prompt_tokens, completion_tokens, total_tokens)
        )
        if not (
            response.get("http_status") == 200
            and response.get("returned_model") == review.reviewer_model
            and response.get("model_matches_request") is True
            and definitively_unusable
            and response.get("content_present") is True
            and response.get("content_type") == "str"
            and response.get("usage_valid") is True
            and token_values_valid
            and total_tokens == prompt_tokens + completion_tokens
            and (
                response.get("reasoning_content_present") is None
                or isinstance(response.get("reasoning_content_present"), bool)
            )
            and (
                request_duration_ms is None
                or isinstance(request_duration_ms, int)
                and not isinstance(request_duration_ms, bool)
                and request_duration_ms >= 0
            )
            and (
                response.get("reasoning_content_length") is None
                or isinstance(response.get("reasoning_content_length"), int)
                and not isinstance(response.get("reasoning_content_length"), bool)
                and response.get("reasoning_content_length") >= 0
            )
            and settlement.provider == "deepseek"
            and settlement.account_fingerprint == review.account_fingerprint
            and settlement.canonical_model_identity == review.reviewer_model
            and settlement.stage == "REVIEW"
            and settlement.billing_origin == "deepseek_direct"
            and settlement.prompt_tokens == prompt_tokens
            and settlement.completion_tokens == completion_tokens
            and settlement.total_tokens == total_tokens
        ):
            return decision(
                CodeReviewOutcomeKind.INTEGRITY_CONFLICT,
                "response diagnostics, usage, or settlement attribution contradicts persisted identity",
            )
        pricing = uow.pricing_snapshots.get_by_id(reservation.pricing_snapshot_id)
        expected_settlement = (
            Decimal(prompt_tokens) * pricing.prompt_price_per_token
            + Decimal(completion_tokens) * pricing.output_price_per_token
            + pricing.additional_cost_per_request
            if pricing
            else None
        )
        if expected_settlement is not None:
            expected_settlement = expected_settlement.quantize(
                Decimal("0.000001"), rounding=ROUND_HALF_UP
            )
        if (
            not pricing
            or not pricing.is_verified
            or pricing.provider != "deepseek"
            or pricing.account_fingerprint != review.account_fingerprint
            or pricing.canonical_model_identity != review.reviewer_model
            or pricing.billing_origin != "deepseek_direct"
            or settlement.amount_usd != expected_settlement
            or settlement.amount_usd > reservation.reserved_amount_usd
        ):
            return decision(
                CodeReviewOutcomeKind.UNRESOLVED_OR_AMBIGUOUS,
                "verified pricing or settlement amount cannot be reconciled",
            )

        dispatch_key = f"deepseek-code-review:{authorization_id}"
        external_action = uow.orchestration_external_actions.get_by_action_key(dispatch_key)
        external_attempts = uow.external_action_attempts.list_by_action_key(dispatch_key)
        execute_actions = [
            item
            for item in actions
            if item.action_type.value == "EXECUTE_AUTHORIZED_DEEPSEEK_CODE_REVIEW"
            and item.parameters_json.get("authorization_id") == authorization_id
        ]
        finalized_terminal_actions = [
            item
            for item in execute_actions
            if item.project_id == run.project_id
            and item.run_id == run.run_id
            and item.job_id == job.job_id
            and item.action_type.value == "EXECUTE_AUTHORIZED_DEEPSEEK_CODE_REVIEW"
            if item.status.value == "BLOCKED"
            and item.result_payload_json.get("review_id") == review.review_id
            and item.result_payload_json.get("reason")
            in {
                "DEEPSEEK_CODE_REVIEW_TERMINAL_TRUNCATED",
                "DEEPSEEK_CODE_REVIEW_TERMINAL_UNUSABLE",
                "DEEPSEEK_CODE_REVIEW_RESPONSE_UNVERIFIABLE",
                "CODE_REVIEW_MALFORMED",
            }
            and item.result_payload_json.get("recovery_decision_id")
        ]
        side_effect_free_rejections = [
            item
            for item in execute_actions
            if item not in finalized_terminal_actions
            and item.status.value == "REJECTED"
            and not item.result_payload_json.get("recovery_decision_id")
            and not item.result_payload_json.get("dispatch_action_key")
        ]
        if (
            not external_action
            or external_action.run_id != run.run_id
            or external_action.action_type.value != "DEEPSEEK_CODE_REVIEW_DISPATCH"
            or external_action.candidate_sha != candidate.candidate_sha
            or external_action.generation != candidate.generation
            or external_action.target_identity
            != f"deepseek:{review.account_fingerprint}:{review.reviewer_model}:REVIEW"
            or external_action.request_fingerprint
            != hashlib.sha256(
                json.dumps(
                    [
                        run.run_id,
                        job.job_id,
                        candidate.candidate_sha,
                        manifest.manifest_hash,
                        authorization_id,
                    ],
                    separators=(",", ":"),
                ).encode()
            ).hexdigest()
            or external_action.status != ExternalActionStatus.FAILED
            or len(external_attempts) != 1
            or external_attempts[0].status != "FAILED"
            or external_attempts[0].attempt_number != 1
            or external_attempts[0].action_key != dispatch_key
            or external_attempts[0].claim_key != f"run:{run.run_id}"
            or external_attempts[0].fence_token <= 0
            or external_action.last_dispatch_intent_id != external_attempts[0].attempt_id
            or len(finalized_terminal_actions) != 1
            or len(finalized_terminal_actions) + len(side_effect_free_rejections)
            != len(execute_actions)
        ):
            return decision(
                CodeReviewOutcomeKind.UNRESOLVED_OR_AMBIGUOUS,
                "external dispatch or attempt is missing, duplicated, or not finalized",
            )
        execute_action = finalized_terminal_actions[0]
        decision_id = execute_action.result_payload_json.get("recovery_decision_id")
        recovery_decision = uow.recovery_decisions.get_by_id(decision_id) if decision_id else None
        if (
            not recovery_decision
            or recovery_decision.claim_key != f"run:{run.run_id}"
            or recovery_decision.identity_type != "RUN"
            or recovery_decision.identity_id != run.run_id
            or recovery_decision.project_id != run.project_id
            or recovery_decision.change_name != run.change_name
            or recovery_decision.source.value != "CONTROL_PLANE"
            or recovery_decision.classification.value != "RESUME_SAFE_CHECKPOINT"
            or recovery_decision.planned_action != "DISPATCH_FROZEN_CODE_REVIEW"
            or recovery_decision.status.value != "BLOCKED"
            or recovery_decision.fence_token != external_attempts[0].fence_token
            or recovery_decision.observation_refs.get("authorization_id") != authorization_id
        ):
            return decision(
                CodeReviewOutcomeKind.UNRESOLVED_OR_AMBIGUOUS,
                "terminal dispatch lacks its canonical fenced recovery decision",
            )

    # Audit every row for this exact direct CODE_REVIEW operation set. Orphan
    # rows or rows that cannot be linked by reservation to one of the reviewed
    # authorizations invalidate the whole recovery proof; timestamps are never
    # used to associate an entry with an operation.
    authorization_ids = {review.budget_authorization_id for review in reviews}
    if len(authorization_ids) != len(reviews):
        return decision(
            CodeReviewOutcomeKind.UNRESOLVED_OR_AMBIGUOUS,
            "multiple reviews reuse one authorization identity",
        )
    reservation_by_id = {item.reservation_id: item for item in reservations}
    linked_reservations: dict[str, list] = {}
    for reservation in reservations:
        if reservation.authorization_id in authorization_ids:
            linked_reservations.setdefault(reservation.authorization_id, []).append(reservation)
    if any(len(linked_reservations.get(auth_id, [])) != 1 for auth_id in authorization_ids):
        return decision(
            CodeReviewOutcomeKind.UNRESOLVED_OR_AMBIGUOUS,
            "one or more authorizations do not map to exactly one reservation",
        )
    related_reservations = [item for rows in linked_reservations.values() for item in rows]
    related_reservation_ids = {item.reservation_id for item in related_reservations}
    if any(
        item.project_id != run.project_id
        or item.run_id != run.run_id
        or item.job_id != job.job_id
        or item.change_id != job.change_name
        or item.provider != "deepseek"
        or item.stage != "REVIEW"
        or item.billing_origin != "deepseek_direct"
        for item in related_reservations
    ):
        return decision(
            CodeReviewOutcomeKind.INTEGRITY_CONFLICT,
            "a review authorization is linked to a reservation with contradictory identity",
        )
    related_ledger = [
        item
        for item in ledger
        if item.reservation_id in related_reservation_ids
        or item.project_id == run.project_id
        and item.job_id == job.job_id
        and item.stage == "REVIEW"
        and (item.provider == "deepseek" or item.billing_origin == "deepseek_direct")
    ]
    if any(
        item.billing_origin != "deepseek_direct"
        or item.reservation_id not in related_reservation_ids
        or item.reservation_id not in reservation_by_id
        or reservation_by_id[item.reservation_id].authorization_id not in authorization_ids
        or item.provider != "deepseek"
        or item.account_fingerprint != reservation_by_id[item.reservation_id].account_fingerprint
        or item.canonical_model_identity
        != reservation_by_id[item.reservation_id].canonical_model_identity
        or item.change_id != reservation_by_id[item.reservation_id].change_id
        or item.stage != "REVIEW"
        or item.entry_type != "SETTLEMENT"
        for item in related_ledger
    ):
        return decision(
            CodeReviewOutcomeKind.UNRESOLVED_OR_AMBIGUOUS,
            "a direct CODE_REVIEW ledger row is orphaned or mismatched",
        )

    return decision(
        CodeReviewOutcomeKind.DEFINITIVE_UNUSABLE_SETTLED,
        "all CODE_REVIEW operations are definitive, unusable, finalized, and financially settled",
    )


@dataclass(frozen=True)
class CodeReviewResult:
    accepted: bool
    review_id: str | None
    candidate_sha: str
    verdict: ReviewVerdictPayload | None = None
    reason: str | None = None
    waiting: bool = False


def _reservation_key(
    run_id: str,
    job_id: str,
    candidate_sha: str,
    manifest_hash: str,
    authorization_id: str | None = None,
) -> str:
    identity = [run_id, job_id, "REVIEW", candidate_sha, manifest_hash]
    if authorization_id is not None:
        identity.append(authorization_id)
    raw = json.dumps(identity, separators=(",", ":")).encode()
    return f"review:v1:{hashlib.sha256(raw).hexdigest()}"


class DeepSeekCodeReviewService:
    """Run an independent code review after exact-candidate checks have passed."""

    def __init__(
        self,
        uow: PersistenceUnitOfWork,
        *,
        health_service: ProviderHealthService | None = None,
        budget_service: BudgetService | None = None,
        runner: Any | None = None,
        app_config: AppConfig | None = None,
        authorship_service: AuthorshipService | None = None,
        timeout_seconds: int = 90,
    ):
        self.uow = uow
        self.health = health_service or ProviderHealthService(uow)
        self.budget = budget_service or BudgetService(uow)
        self.runner = runner
        self.authorship = authorship_service or AuthorshipService()
        self.app_config = app_config or load_config()
        self.timeout_seconds = timeout_seconds

    async def review_candidate(
        self,
        *,
        project: Project,
        run: OrchestrationRun,
        job: Job,
        candidate: OrchestrationCandidate,
        manifest: CandidateManifest,
        candidate_worktree: str | Path,
        authorship_evidence: dict[str, Any],
        authorization_id: str | None = None,
        claim_context: Any | None = None,
        dispatch_action_key: str | None = None,
    ) -> CodeReviewResult:
        sha = candidate.candidate_sha
        identity_mismatches = self._identity_mismatches(project, run, job, candidate, manifest)
        if identity_mismatches:
            return CodeReviewResult(
                False,
                None,
                sha,
                reason=("CODE_REVIEW_CANDIDATE_IDENTITY_MISMATCH:" + ",".join(identity_mismatches)),
            )
        try:
            source_files, git_diff = self._read_exact_candidate(
                candidate_worktree, candidate, manifest, change_name=job.change_name
            )
            checks_valid, checks_error, current_check_batch = validate_current_checks_batch(
                check_results=self.uow.check_results.list_by_job(job.job_id),
                job=job,
                run=run,
                project=project,
                require_configured_checks=authorization_id is not None,
            )
            if not checks_valid:
                raise ValueError(checks_error or "Current configured check batch is invalid.")
            if authorization_id is not None and not current_check_batch:
                raise ValueError(
                    "Exceptional code review requires a non-empty current check batch."
                )
            checks = [
                {
                    "check_name": item.check_name,
                    "command": item.command,
                    "exit_code": item.exit_code,
                    "duration_ms": item.duration_ms,
                    "output_snippet": redact_secrets(item.output_snippet),
                }
                for item in current_check_batch
            ] or self._read_exact_checks(job, candidate)
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            return CodeReviewResult(
                False, None, sha, reason=f"CODE_REVIEW_PREFLIGHT_BLOCKED:{type(exc).__name__}"
            )

        surviving_paths = {entry["path"] for entry in manifest.tracked_files if entry.get("path")}
        canonical_authorship = self.authorship.evaluate_reviewer_authorship(
            job_id=job.job_id,
            reviewer_role="deepseek",
            surviving_files=surviving_paths,
            candidate_sha=candidate.candidate_sha,
            candidate_generation=candidate.generation,
            uow=self.uow,
        )
        independent, independence_reason = self.authorship.is_reviewer_eligible(
            job.job_id, "deepseek", self.uow
        )
        if not independent:
            return CodeReviewResult(
                False,
                None,
                sha,
                reason=f"CODE_REVIEW_REVIEWER_NOT_INDEPENDENT:{independence_reason}",
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
                project_config, OpenSpecStage.REVIEW, app_config=self.app_config
            )
        except StageProfileError as exc:
            return CodeReviewResult(
                False, None, sha, reason=f"CODE_REVIEW_PROFILE_UNAVAILABLE:{exc}", waiting=True
            )

        provider_config = self.app_config.providers.get("deepseek")
        if (
            not provider_config
            or not provider_config.enabled
            or "deepseek" not in project.external_providers_allowed
        ):
            return CodeReviewResult(
                False, None, sha, reason="DEEPSEEK_OWNER_POLICY_DISABLED", waiting=True
            )
        adapter = get_provider_adapter("deepseek", self.app_config)
        if profile.provider != "deepseek":
            return CodeReviewResult(
                False, None, sha, reason="CODE_REVIEW_PROVIDER_SUBSTITUTION_DENIED"
            )
        supported, _ = await adapter.check_model_supported(profile.model, effort=profile.effort)
        account = getattr(adapter, "account_fingerprint", None)
        if not supported or not account:
            return CodeReviewResult(
                False,
                None,
                sha,
                reason="DEEPSEEK_CODE_REVIEW_ACCOUNT_MODEL_UNAVAILABLE",
                waiting=True,
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
                account_fingerprint=account,
                quota_scope="deepseek_direct_account_balance",
            )
        ):
            return CodeReviewResult(
                False,
                None,
                sha,
                reason="DEEPSEEK_CODE_REVIEW_CAPACITY_UNKNOWN_OR_EXHAUSTED",
                waiting=True,
            )

        pricing = self.budget.get_verified_review_price_snapshot(
            provider="deepseek",
            account_fingerprint=account,
            model=profile.model,
            billing_origin="deepseek_direct",
        )
        deepseek_config = self.app_config.providers.get("deepseek")
        configured_budget = deepseek_config.budget if deepseek_config else {}
        exceptional_authorization = None
        if authorization_id is not None:
            action = self.uow.operator_actions.get_by_request_id(authorization_id)
            authorization = action.result_payload_json.get("authorization", {}) if action else {}
            expected_authority = {
                "provider": "deepseek",
                "account_fingerprint": account,
                "model": profile.model,
                "effort": profile.effort,
                "stage": "REVIEW",
                "billing_origin": "deepseek_direct",
                "run_id": run.run_id,
                "job_id": job.job_id,
                "candidate_sha": candidate.candidate_sha,
                "base_sha": candidate.base_sha,
                "generation": candidate.generation,
                "manifest_id": manifest.manifest_id,
                "manifest_hash": manifest.manifest_hash,
                "action_request_id": authorization_id,
            }
            valid_authorization = bool(
                action
                and action.action_type.value == "AUTHORIZE_DEEPSEEK_CODE_REVIEW"
                and action.status.value == "COMPLETED"
                and action.project_id == project.project_id
                and action.change_name == job.change_name
                and action.run_id == run.run_id
                and action.job_id == job.job_id
                and all(
                    authorization.get(key) == value for key, value in expected_authority.items()
                )
                and authorization.get("authorized_by")
                and authorization.get("pricing_snapshot_id")
                and authorization.get("expires_at")
                and authorization.get("max_spend_usd")
            )
            try:
                authorization_expiry = datetime.fromisoformat(str(authorization.get("expires_at")))
                authorization_maximum = Decimal(str(authorization.get("max_spend_usd")))
            except (TypeError, ValueError, ArithmeticError):
                valid_authorization = False
                authorization_expiry = None
                authorization_maximum = Decimal("0")
            pricing = (
                self.uow.pricing_snapshots.get_by_id(str(authorization.get("pricing_snapshot_id")))
                if valid_authorization
                else None
            )
            configured_maximum = configured_budget.get("maximum_code_review_usd")
            if configured_maximum is not None:
                try:
                    authorization_maximum = min(
                        authorization_maximum, Decimal(str(configured_maximum))
                    )
                except ArithmeticError:
                    valid_authorization = False
            if (
                not valid_authorization
                or not authorization_expiry
                or authorization_expiry.tzinfo is None
                or authorization_expiry <= utc_now()
                or authorization_maximum <= 0
                or authorization.get("pricing_snapshot_id") != getattr(pricing, "snapshot_id", None)
                or not pricing
                or not pricing.is_verified
                or pricing.provider != "deepseek"
                or pricing.account_fingerprint != account
                or pricing.canonical_model_identity != profile.model
                or pricing.billing_origin != "deepseek_direct"
                or not claim_context
                or claim_context.claim_key != f"run:{run.run_id}"
                or not dispatch_action_key
            ):
                return CodeReviewResult(
                    False,
                    None,
                    sha,
                    reason="CODE_REVIEW_EXCEPTIONAL_AUTHORITY_MISSING_OR_MISMATCHED",
                )
            exceptional_authorization = authorization
        if not pricing:
            return CodeReviewResult(
                False, None, sha, reason="DEEPSEEK_DIRECT_PRICE_SNAPSHOT_UNAVAILABLE", waiting=True
            )
        request_json = json.dumps(
            {
                "stage": "CODE_REVIEW",
                "provider": "deepseek_direct",
                "project_id": project.project_id,
                "repository": project.repository,
                "change_name": job.change_name,
                "run_id": run.run_id,
                "job_id": job.job_id,
                "generation": candidate.generation,
                "base_sha": candidate.base_sha,
                "candidate_sha": candidate.candidate_sha,
                "manifest_id": manifest.manifest_id,
                "manifest_hash": manifest.manifest_hash,
                "checks": checks,
                "authorship": canonical_authorship,
                "git_diff": git_diff,
                "files": source_files,
                "required_output": {
                    "verdict": ["READY_TO_MERGE", "CHANGES_REQUIRED"],
                    "summary": "string",
                    "findings": [
                        {
                            "severity": ["BLOCKER", "MAJOR", "MINOR"],
                            "location": "string or null",
                            "violated_requirement": "string",
                            "expected_correction": "string",
                        }
                    ],
                },
                "limitations": "A review never authorizes APPLY or human merge.",
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        prior = self.uow.reviews.get_by_job_stage(job.job_id, "CODE_REVIEW")
        resumable_placeholder = False
        terminal_retry = False
        if prior:
            exact = self._prior_checkpoint_matches(
                prior, run, job, candidate, manifest, profile.model, account
            )
            if (
                exact
                and prior.status
                in {
                    ReviewStatus.REVIEW_RUNNING,
                    ReviewStatus.REVIEW_COMPLETED,
                }
                and prior.verdict
                in {
                    ReviewVerdict.READY_TO_MERGE,
                    ReviewVerdict.CHANGES_REQUIRED,
                }
                and (
                    authorization_id is None
                    or prior.budget_authorization_id == authorization_id
                    and prior.budget_reservation_id is not None
                    and (
                        reservation := self.uow.budget_reservations.get_by_id(
                            prior.budget_reservation_id
                        )
                    )
                    is not None
                    and reservation.authorization_id == authorization_id
                )
            ):
                findings = self.uow.review_findings.list_by_review(prior.review_id)
                payload = ReviewVerdictPayload(
                    verdict=prior.verdict,
                    summary=prior.summary or "",
                    findings=[
                        {
                            "severity": finding.severity,
                            "location": finding.location,
                            "violated_requirement": finding.violated_requirement,
                            "expected_correction": finding.expected_correction,
                        }
                        for finding in findings
                    ],
                )
                return CodeReviewResult(True, prior.review_id, sha, payload)
            resumable_placeholder = bool(
                authorization_id is None
                and prior.status == ReviewStatus.REVIEW_RUNNING
                and prior.review_stage == "CODE_REVIEW"
                and prior.project_id == project.project_id
                and prior.job_id == job.job_id
                and prior.change_name == job.change_name
                and prior.orchestration_run_id == run.run_id
                and prior.candidate_generation == candidate.generation
                and prior.candidate_sha == candidate.candidate_sha
                and prior.base_sha == candidate.base_sha
                and prior.manifest_id == manifest.manifest_id
                and prior.manifest_hash == manifest.manifest_hash
                and prior.reviewer_role == "deepseek"
                and prior.budget_authorization_id is None
                and prior.budget_reservation_id is None
                and prior.provider is None
            )
            if authorization_id is not None and prior.status == ReviewStatus.REVIEW_FAILED:
                old_review_actions = [
                    item
                    for item in self.uow.reviews.list_by_job(job.job_id)
                    if item.review_stage == "CODE_REVIEW"
                ]
                terminal_retry = bool(
                    all(
                        item.budget_authorization_id != authorization_id
                        for item in old_review_actions
                    )
                    and reconcile_code_review_outcome(
                        self.uow,
                        run=run,
                        job=job,
                        candidate=candidate,
                        manifest=manifest,
                        claim_context=claim_context,
                    ).permits_new_authorization
                )
            if not resumable_placeholder and not terminal_retry:
                return CodeReviewResult(
                    False,
                    prior.review_id,
                    sha,
                    reason="CODE_REVIEW_CHECKPOINT_EXISTS; refusing blind duplicate dispatch",
                    waiting=prior.status
                    in {ReviewStatus.REVIEW_PENDING, ReviewStatus.REVIEW_RUNNING},
                )

        # Authorization identity is hashed into the fixed-length key so each
        # explicitly renewed operation is distinct within the schema bound.
        reservation_key = _reservation_key(
            run.run_id,
            job.job_id,
            candidate.candidate_sha,
            manifest.manifest_hash,
            authorization_id=authorization_id,
        )
        configured_output_tokens = getattr(
            provider_config, "code_review_max_output_tokens", MAX_REVIEW_OUTPUT_TOKENS
        )
        if (
            not isinstance(configured_output_tokens, int)
            or isinstance(configured_output_tokens, bool)
            or configured_output_tokens <= 0
            or configured_output_tokens > CONTRACT_REVIEW_MAX_OUTPUT_TOKENS
        ):
            return CodeReviewResult(
                False, None, sha, reason="CODE_REVIEW_OUTPUT_TOKEN_BOUND_INVALID"
            )
        runner = self.runner or DeepSeekContractReviewRunner(
            api_key=getattr(adapter, "authenticated_api_key", None),
            model=profile.model,
            effort=profile.effort,
            review_stage="CODE_REVIEW",
            max_output_tokens=configured_output_tokens,
        )
        if (
            getattr(runner, "model", None) != profile.model
            or getattr(runner, "effort", None) != profile.effort
            or getattr(runner, "review_stage", "CODE_REVIEW") != "CODE_REVIEW"
            or getattr(runner, "max_output_tokens", None) != configured_output_tokens
        ):
            return CodeReviewResult(False, None, sha, reason="CODE_REVIEW_RUNNER_PROFILE_MISMATCH")
        try:
            input_size = DeepSeekContractReviewRunner.input_token_upper_bound_for(
                "CODE_REVIEW", request_json
            )
        except (TypeError, ValueError):
            return CodeReviewResult(
                False, None, sha, reason="CODE_REVIEW_RUNNER_INPUT_BOUND_UNAVAILABLE"
            )
        if (
            not isinstance(input_size, int)
            or input_size <= 0
            or input_size > MAX_REVIEW_INPUT_BYTES
        ):
            return CodeReviewResult(False, None, sha, reason="CODE_REVIEW_INPUT_EXCEEDS_BOUND")

        reservation, denial = self.budget.reserve_review_budget(
            project_id=project.project_id,
            run_id=run.run_id,
            job_id=job.job_id,
            change_id=job.change_name,
            provider="deepseek",
            account_fingerprint=account,
            model=profile.model,
            stage="REVIEW",
            billing_origin="deepseek_direct",
            pricing_snapshot_id=pricing.snapshot_id,
            prompt_token_upper_bound=input_size,
            max_output_tokens=configured_output_tokens,
            idempotency_key=reservation_key,
            candidate_sha=candidate.candidate_sha,
            candidate_generation=candidate.generation,
            manifest_id=manifest.manifest_id,
            manifest_hash=manifest.manifest_hash,
            maximum_stage_usd=(
                str(authorization_maximum)
                if exceptional_authorization is not None
                else configured_budget.get("maximum_code_review_usd")
            ),
            maximum_combined_usd=configured_budget.get("maximum_combined_review_usd"),
            authorization_id=authorization_id,
        )
        if denial:
            return CodeReviewResult(False, None, sha, reason=denial, waiting=True)

        review = (
            prior.model_copy(
                update={
                    "reviewer_model": profile.model,
                    "provider": "deepseek",
                    "account_fingerprint": account,
                    "budget_authorization_id": authorization_id,
                    "budget_reservation_id": reservation.reservation_id if reservation else None,
                    "billing_origin": "deepseek_direct",
                    "status": ReviewStatus.REVIEW_RUNNING,
                    "is_mixed_authorship": bool(canonical_authorship.get("is_mixed_authorship")),
                    "authorship_evidence": canonical_authorship,
                }
            )
            if resumable_placeholder and prior
            else Review(
                job_id=job.job_id,
                project_id=project.project_id,
                change_name=job.change_name,
                reviewer_role="deepseek",
                reviewer_model=profile.model,
                review_stage="CODE_REVIEW",
                provider="deepseek",
                account_fingerprint=account,
                budget_authorization_id=authorization_id,
                budget_reservation_id=reservation.reservation_id if reservation else None,
                billing_origin="deepseek_direct",
                orchestration_run_id=run.run_id,
                candidate_generation=candidate.generation,
                candidate_sha=candidate.candidate_sha,
                base_sha=candidate.base_sha,
                manifest_id=manifest.manifest_id,
                manifest_hash=manifest.manifest_hash,
                status=ReviewStatus.REVIEW_PENDING,
                is_mixed_authorship=bool(canonical_authorship.get("is_mixed_authorship")),
                authorship_evidence=canonical_authorship,
            )
        )
        self.uow.reviews.save(review)
        if exceptional_authorization is not None:
            if self.uow.claims.get_by_key(claim_context.claim_key) is None:
                self.uow.rollback()
                return CodeReviewResult(
                    False, review.review_id, sha, reason="CODE_REVIEW_CLAIM_MISSING"
                )
            existing_action = self.uow.orchestration_external_actions.get_by_action_key(
                dispatch_action_key
            )
            attempts = self.uow.external_action_attempts.list_by_action_key(dispatch_action_key)
            if existing_action and (
                existing_action.status.value != "RESERVED"
                or existing_action.last_dispatch_intent_id
                or existing_action.remote_identifier
                or attempts
            ):
                self.uow.rollback()
                return CodeReviewResult(
                    False,
                    review.review_id,
                    sha,
                    reason="CODE_REVIEW_DISPATCH_ALREADY_POSSIBLE; refusing repeat",
                    waiting=True,
                )
            if not existing_action:
                from minime.domain.enums import ExternalActionType
                from minime.domain.models import OrchestrationExternalAction

                action_fingerprint = hashlib.sha256(
                    json.dumps(
                        [
                            run.run_id,
                            job.job_id,
                            candidate.candidate_sha,
                            manifest.manifest_hash,
                            authorization_id,
                        ],
                        separators=(",", ":"),
                    ).encode()
                ).hexdigest()
                self.uow.orchestration_external_actions.reserve(
                    OrchestrationExternalAction(
                        run_id=run.run_id,
                        action_key=dispatch_action_key,
                        action_type=ExternalActionType.DEEPSEEK_CODE_REVIEW_DISPATCH,
                        target_identity=f"deepseek:{account}:{profile.model}:REVIEW",
                        request_fingerprint=action_fingerprint,
                        candidate_sha=candidate.candidate_sha,
                        generation=candidate.generation,
                    )
                )
            try:
                current_run = self.uow.orchestration_runs.get_by_id(run.run_id)
                current_job = self.uow.jobs.get_by_id(job.job_id)
                if not current_run or not current_job:
                    raise ValueError("Review Run/Job disappeared before dispatch.")
                current_run.is_active = True
                current_run.stop_outcome = None
                current_run.human_gate = None
                current_run.stop_reason = None
                current_run.stop_details = {"code": "CODE_REVIEW_DISPATCHING"}
                current_job.status = JobStatus.REVIEW_RUNNING
                self.uow.orchestration_runs.save(current_run)
                self.uow.jobs.save(current_job)
                # The production UOW disables autoflush. Make the reserved
                # external action visible to the fenced repository read while
                # keeping reservation, Review, checkpoint, and intent in this
                # same uncommitted PostgreSQL transaction.
                self.uow.flush()
                self.uow.claims.commit_fenced_dispatch_intent(
                    claim_key=claim_context.claim_key,
                    owner_instance_id=claim_context.owner_instance_id,
                    fence_token=claim_context.fence_token,
                    action_key=dispatch_action_key,
                    attempt_number=1,
                )
            except Exception as exc:
                self.uow.rollback()
                return CodeReviewResult(
                    False,
                    review.review_id,
                    sha,
                    reason=f"CODE_REVIEW_DISPATCH_FENCE_REJECTED:{type(exc).__name__}",
                )
        else:
            self.uow.commit()
        # A committed RUNNING checkpoint prevents a billed request from being replayed blindly.
        if review.status == ReviewStatus.REVIEW_PENDING:
            self.uow.reviews.transition(review.review_id, ReviewStatus.REVIEW_RUNNING.value)
            self.uow.commit()
            review = self.uow.reviews.get_by_id(review.review_id) or review

        try:
            review_started_at = time.monotonic()
            response: DeepSeekReviewResponse = await runner.review(
                request_json, self.timeout_seconds
            )
        except Exception as exc:
            if exceptional_authorization is not None:
                from minime.domain.models import validate_claim_context_authoritative

                try:
                    validate_claim_context_authoritative(self.uow, claim_context, for_update=True)
                except Exception:
                    # A request may have reached the provider, but a superseded
                    # owner cannot settle, finalize, or relabel its dispatch.
                    # Leave the committed intent/checkpoint for canonical recovery.
                    return CodeReviewResult(
                        False,
                        review.review_id,
                        sha,
                        reason="CODE_REVIEW_CLAIM_LOST_AFTER_DISPATCH",
                        waiting=True,
                    )
            # The request may have reached DeepSeek and been billed. Preserve the
            # running checkpoint and unresolved reservation; never replay blindly.
            if reservation:
                self.budget.mark_unresolved(reservation.reservation_id)
            if exceptional_authorization is not None:
                self.uow.orchestration_external_actions.update_status(
                    dispatch_action_key,
                    ExternalActionStatus.AMBIGUOUS,
                    error_message=f"Provider outcome uncertain: {type(exc).__name__}",
                )
                attempts = self.uow.external_action_attempts.list_by_action_key(dispatch_action_key)
                if attempts:
                    self.uow.external_action_attempts.update_status(
                        attempts[0].attempt_id,
                        "AMBIGUOUS",
                        error_message=f"Provider outcome uncertain: {type(exc).__name__}",
                    )
            self.uow.commit()
            return CodeReviewResult(
                False,
                review.review_id,
                sha,
                reason=f"CODE_REVIEW_OUTCOME_AMBIGUOUS:{type(exc).__name__}",
            )
        if exceptional_authorization is not None:
            from minime.domain.models import validate_claim_context_authoritative

            try:
                validate_claim_context_authoritative(self.uow, claim_context, for_update=True)
            except Exception:
                # The remote result cannot be applied by a stale owner. Keep the
                # one-shot checkpoint non-replayable for authoritative recovery.
                return CodeReviewResult(
                    False,
                    review.review_id,
                    sha,
                    reason="CODE_REVIEW_CLAIM_LOST_AFTER_DISPATCH",
                    waiting=True,
                )
        request_duration_ms = max(0, int((time.monotonic() - review_started_at) * 1000))
        self.uow.metrics.save(
            MetricFact(
                metric_name="review_duration_ms",
                project_id=project.project_id,
                change_id=job.change_name,
                stage="CODE_REVIEW",
                duration_ms=request_duration_ms,
                details={
                    "job_id": job.job_id,
                    "reviewer": "deepseek",
                    "model": profile.model,
                    "candidate_sha": candidate.candidate_sha,
                    "review_id": review.review_id,
                },
            )
        )
        if response.response_diagnostics is not None:
            response = dataclass_replace(
                response,
                response_diagnostics=dataclass_replace(
                    response.response_diagnostics, request_duration_ms=request_duration_ms
                ),
            )
        persist_deepseek_response_diagnostic(self.uow, review, response)
        diagnostics = response.response_diagnostics
        usage_verified = bool(
            response.model == profile.model
            and diagnostics
            and diagnostics.http_status == 200
            and diagnostics.model_matches_request is True
            and diagnostics.usage_valid
            and isinstance(response.prompt_tokens, int)
            and isinstance(response.completion_tokens, int)
            and response.prompt_tokens == diagnostics.prompt_tokens
            and response.completion_tokens == diagnostics.completion_tokens
        )
        usage_settled = False
        if usage_verified:
            actual_cost = (
                Decimal(response.prompt_tokens) * pricing.prompt_price_per_token
                + Decimal(response.completion_tokens) * pricing.output_price_per_token
                + pricing.additional_cost_per_request
            )
            if reservation:
                usage_settled = bool(
                    self.budget.settle_reservation(
                        reservation_id=reservation.reservation_id,
                        actual_cost_usd=actual_cost,
                        prompt_tokens=response.prompt_tokens,
                        completion_tokens=response.completion_tokens,
                        total_tokens=response.prompt_tokens + response.completion_tokens,
                    )
                )
            else:
                self.budget.record_unreserved_review_usage(
                    project_id=project.project_id,
                    job_id=job.job_id,
                    change_id=job.change_name,
                    provider="deepseek",
                    account_fingerprint=account,
                    model=profile.model,
                    stage="REVIEW",
                    billing_origin="deepseek_direct",
                    review_id=review.review_id,
                    prompt_tokens=response.prompt_tokens,
                    completion_tokens=response.completion_tokens,
                    actual_cost_usd=actual_cost,
                )
                usage_settled = True
        elif reservation:
            self.budget.mark_unresolved(reservation.reservation_id)

        if (
            response.exit_code != 0
            or response.error
            or response.model != profile.model
            or not response.content
            or not usage_verified
        ):
            if exceptional_authorization is not None:
                self.uow.orchestration_external_actions.update_status(
                    dispatch_action_key,
                    ExternalActionStatus.FAILED,
                    error_message="DeepSeek response failed strict identity, content, or usage validation.",
                )
                attempts = self.uow.external_action_attempts.list_by_action_key(dispatch_action_key)
                if attempts:
                    self.uow.external_action_attempts.update_status(
                        attempts[0].attempt_id,
                        "FAILED",
                        error_message="DeepSeek response failed strict identity, content, or usage validation.",
                    )
            self.uow.reviews.transition(
                review.review_id,
                ReviewStatus.REVIEW_FAILED.value,
                error_message=response.error
                or "DeepSeek code-review response identity or usage is unverifiable.",
            )
            self.uow.commit()
            terminal_unusable = bool(
                response.exit_code == 0
                and response.model == profile.model
                and diagnostics
                and diagnostics.http_status == 200
                and diagnostics.model_matches_request is True
                and diagnostics.content_present
                and diagnostics.content_type == "str"
                and isinstance(diagnostics.content_length, int)
                and not isinstance(diagnostics.content_length, bool)
                and diagnostics.content_length >= 0
                and usage_verified
                and usage_settled
                and (
                    diagnostics.finish_reason == "length"
                    or diagnostics.finish_reason == "stop"
                    and diagnostics.content_length == 0
                )
            )
            return CodeReviewResult(
                False,
                review.review_id,
                sha,
                reason=(
                    "DEEPSEEK_CODE_REVIEW_TERMINAL_TRUNCATED"
                    if diagnostics and diagnostics.finish_reason == "length"
                    else "DEEPSEEK_CODE_REVIEW_TERMINAL_UNUSABLE"
                    if terminal_unusable
                    else "DEEPSEEK_CODE_REVIEW_RESPONSE_UNVERIFIABLE"
                ),
                waiting=not terminal_unusable,
            )
        try:
            verdict = parse_review_verdict(response.content)
        except (ValueError, TypeError):
            if exceptional_authorization is not None:
                self.uow.orchestration_external_actions.update_status(
                    dispatch_action_key,
                    ExternalActionStatus.FAILED,
                    error_message="DeepSeek response did not match the strict review schema.",
                )
                attempts = self.uow.external_action_attempts.list_by_action_key(dispatch_action_key)
                if attempts:
                    self.uow.external_action_attempts.update_status(
                        attempts[0].attempt_id,
                        "FAILED",
                        error_message="DeepSeek response did not match the strict review schema.",
                    )
            self.uow.reviews.transition(
                review.review_id,
                ReviewStatus.REVIEW_FAILED.value,
                error_message="DeepSeek code review did not match the strict verdict schema.",
            )
            self.uow.commit()
            malformed_terminal = bool(
                exceptional_authorization is not None
                and diagnostics
                and diagnostics.http_status == 200
                and diagnostics.model_matches_request is True
                and diagnostics.finish_reason == "stop"
                and diagnostics.content_present
                and diagnostics.content_type == "str"
                and isinstance(diagnostics.content_length, int)
                and not isinstance(diagnostics.content_length, bool)
                and diagnostics.content_length > 0
                and usage_verified
                and usage_settled
            )
            return CodeReviewResult(
                False,
                review.review_id,
                sha,
                reason="CODE_REVIEW_MALFORMED",
                waiting=not malformed_terminal,
            )

        if not usage_settled:
            if exceptional_authorization is not None:
                self.uow.orchestration_external_actions.update_status(
                    dispatch_action_key,
                    ExternalActionStatus.FAILED,
                    error_message="DeepSeek usage could not be reconciled within authority.",
                )
                attempts = self.uow.external_action_attempts.list_by_action_key(dispatch_action_key)
                if attempts:
                    self.uow.external_action_attempts.update_status(
                        attempts[0].attempt_id,
                        "FAILED",
                        error_message="DeepSeek usage could not be reconciled within authority.",
                    )
            self.uow.reviews.transition(
                review.review_id,
                ReviewStatus.REVIEW_FAILED.value,
                error_message="DeepSeek code-review spend could not be reconciled within its authorization.",
            )
            self.uow.commit()
            return CodeReviewResult(
                False, review.review_id, sha, reason="CODE_REVIEW_BUDGET_RECONCILIATION_FAILED"
            )
        if exceptional_authorization is not None:
            # The exceptional path owns finalization here (unlike the ordinary
            # pipeline, which validates after this service returns). Recheck the
            # exact worktree after reviewer I/O and before accepting its verdict.
            # Keep the response diagnostic and verified usage settlement durable,
            # but never mark a review of a mutated candidate complete.
            intact, integrity_error = validate_post_review_integrity(
                Path(candidate_worktree), candidate.candidate_sha
            )
            if not intact:
                message = integrity_error or "Post-review candidate integrity failed."
                self.uow.reviews.transition(
                    review.review_id,
                    ReviewStatus.REVIEW_FAILED.value,
                    error_message=message,
                )
                self.uow.orchestration_external_actions.update_status(
                    dispatch_action_key,
                    ExternalActionStatus.FAILED,
                    error_message="Candidate integrity changed during read-only review.",
                )
                attempts = self.uow.external_action_attempts.list_by_action_key(dispatch_action_key)
                if attempts:
                    self.uow.external_action_attempts.update_status(
                        attempts[0].attempt_id,
                        "FAILED",
                        error_message="Candidate integrity changed during read-only review.",
                    )
                self.uow.events.save(
                    Event(
                        event_type=EventType.UNAUTHORIZED_REVIEWER_MUTATION,
                        project_id=project.project_id,
                        change_id=job.change_name,
                        operation_id=job.job_id,
                        payload={
                            "run_id": run.run_id,
                            "job_id": job.job_id,
                            "review_id": review.review_id,
                            "candidate_sha": candidate.candidate_sha,
                            "generation": candidate.generation,
                            "error": message,
                        },
                        timestamp=utc_now(),
                    )
                )
                self.uow.commit()
                return CodeReviewResult(
                    False,
                    review.review_id,
                    sha,
                    reason="CODE_REVIEW_POST_REVIEW_INTEGRITY_FAILED",
                )
        # Persist the response with settlement before returning to the pipeline.
        # The pipeline still performs its post-review immutability check before
        # finalizing REVIEW_COMPLETED. A crash in between can recover this exact
        # result without dispatching a second paid request.
        review.verdict = verdict.verdict
        review.summary = verdict.summary
        self.uow.reviews.save(review)
        for item in verdict.findings:
            self.uow.review_findings.save(
                ReviewFinding(
                    review_id=review.review_id,
                    severity=item.severity,
                    location=item.location,
                    violated_requirement=item.violated_requirement,
                    expected_correction=item.expected_correction,
                )
            )
        if exceptional_authorization is not None:
            self.uow.reviews.transition(review.review_id, ReviewStatus.REVIEW_COMPLETED.value)
            self.uow.orchestration_external_actions.update_status(
                dispatch_action_key,
                ExternalActionStatus.COMPLETED,
                remote_identifier=review.review_id,
                result_payload={
                    "review_id": review.review_id,
                    "candidate_sha": candidate.candidate_sha,
                    "generation": candidate.generation,
                    "manifest_hash": manifest.manifest_hash,
                    "verdict": verdict.verdict.value,
                    "authorization_id": authorization_id,
                },
            )
            attempts = self.uow.external_action_attempts.list_by_action_key(dispatch_action_key)
            if attempts:
                self.uow.external_action_attempts.update_status(
                    attempts[0].attempt_id,
                    "COMPLETED",
                    result_payload={
                        "review_id": review.review_id,
                        "candidate_sha": candidate.candidate_sha,
                        "verdict": verdict.verdict.value,
                    },
                )
            self.uow.events.save(
                Event(
                    event_type=EventType.CODE_REVIEW_COMPLETED,
                    project_id=project.project_id,
                    change_id=job.change_name,
                    operation_id=job.job_id,
                    payload={
                        "run_id": run.run_id,
                        "job_id": job.job_id,
                        "review_id": review.review_id,
                        "review_stage": "CODE_REVIEW",
                        "provider": "deepseek",
                        "model": review.reviewer_model,
                        "account_fingerprint": review.account_fingerprint,
                        "authorization_id": authorization_id,
                        "reservation_id": reservation.reservation_id if reservation else None,
                        "candidate_sha": candidate.candidate_sha,
                        "base_sha": candidate.base_sha,
                        "generation": candidate.generation,
                        "manifest_id": manifest.manifest_id,
                        "manifest_hash": manifest.manifest_hash,
                        "verdict": verdict.verdict.value,
                    },
                    timestamp=utc_now(),
                )
            )
        self.uow.commit()
        return CodeReviewResult(True, review.review_id, sha, verdict)

    @staticmethod
    def _identity_matches(project, run, job, candidate, manifest) -> bool:
        return not DeepSeekCodeReviewService._identity_mismatches(
            project, run, job, candidate, manifest
        )

    @staticmethod
    def _identity_mismatches(project, run, job, candidate, manifest) -> list[str]:
        checks = {
            "run_project": run.project_id == project.project_id,
            "run_change": run.change_name == job.change_name,
            "job_project": job.project_id == project.project_id,
            "active_job": run.active_job_id == job.job_id,
            "run_candidate": run.current_candidate_sha == candidate.candidate_sha,
            "run_generation": run.current_generation == candidate.generation,
            "candidate_run": candidate.run_id == run.run_id,
            "candidate_frozen": candidate.is_frozen,
            "base_sha": candidate.base_sha == run.base_sha == job.base_sha,
            "job_candidate": candidate.candidate_sha == job.candidate_sha,
            "manifest_id": candidate.manifest_id == manifest.manifest_id,
            "manifest_hash": candidate.manifest_hash == manifest.manifest_hash,
            "manifest_job": manifest.job_id == job.job_id,
            "manifest_candidate": manifest.candidate_sha == candidate.candidate_sha,
        }
        return [name for name, matched in checks.items() if not matched]

    @staticmethod
    def _read_exact_candidate(
        worktree: str | Path,
        candidate: OrchestrationCandidate,
        manifest: CandidateManifest,
        change_name: str | None = None,
    ) -> tuple[list[dict[str, str]], str]:
        root = Path(worktree).resolve(strict=True)
        repository_root = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        if Path(repository_root).resolve(strict=True) != root:
            raise ValueError("review path is not the candidate repository root")
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=True
        ).stdout.strip()
        if head != candidate.candidate_sha:
            raise ValueError("review worktree HEAD differs from frozen candidate")
        status = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        if status.strip():
            raise ValueError("review worktree is not clean")
        if manifest.staged_files or manifest.untracked_files:
            raise ValueError("candidate manifest contains non-committed files")
        observed_manifest = CandidateManifestService().generate_manifest(
            root, candidate.candidate_sha, manifest.job_id, manifest.attempt_id
        )
        if (
            observed_manifest.manifest_hash != manifest.manifest_hash
            or observed_manifest.tracked_files != manifest.tracked_files
            or observed_manifest.staged_files != manifest.staged_files
            or observed_manifest.untracked_files != manifest.untracked_files
            or observed_manifest.deleted_files != manifest.deleted_files
        ):
            raise ValueError("candidate manifest does not describe the complete observed Git tree")

        # Determine base commit for git diff
        diff_base = None
        has_base = False
        if candidate.base_sha:
            has_base = (
                subprocess.run(
                    ["git", "cat-file", "-e", f"{candidate.base_sha}^{{commit}}"],
                    cwd=root,
                    capture_output=True,
                ).returncode
                == 0
            )
            if has_base:
                diff_base = candidate.base_sha

        if not diff_base:
            has_parent = (
                subprocess.run(
                    ["git", "cat-file", "-e", f"{candidate.candidate_sha}^^{{commit}}"],
                    cwd=root,
                    capture_output=True,
                ).returncode
                == 0
            )
            if has_parent:
                diff_base = f"{candidate.candidate_sha}^"
            else:
                # 4b825dc642cb6eb9a060e54bf8d69288fbee4904 is the empty tree SHA
                diff_base = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"

        diff_text = subprocess.run(
            ["git", "diff", f"{diff_base}..{candidate.candidate_sha}"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        if len(diff_text.encode("utf-8")) > MAX_REVIEW_DIFF_BYTES:
            raise ValueError("candidate git diff exceeds allowable review input bound")
        safe_git_diff = redact_secrets(diff_text)
        if len(safe_git_diff.encode("utf-8")) > MAX_REVIEW_DIFF_BYTES:
            raise ValueError("candidate git diff exceeds allowable review input bound")

        name_status_lines = subprocess.run(
            ["git", "diff", "--name-status", f"{diff_base}..{candidate.candidate_sha}"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.splitlines()

        diff_changed: set[str] = set()
        diff_deleted: set[str] = set()
        for line in name_status_lines:
            parts = line.split("\t")
            if not parts:
                continue
            code = parts[0]
            if code.startswith("D"):
                diff_deleted.add(parts[1].strip())
            elif code.startswith("R"):
                diff_deleted.add(parts[1].strip())
                if len(parts) > 2:
                    diff_changed.add(parts[2].strip())
            else:
                if len(parts) > 1:
                    diff_changed.add(parts[1].strip())

        active_change_prefix = f"openspec/changes/{change_name}/" if change_name else None
        active_change_dot_prefix = f".openspec/changes/{change_name}/" if change_name else None
        is_empty_diff = not diff_changed and not diff_deleted

        items = []
        size = 0
        seen: set[str] = set()
        for entry in manifest.tracked_files:
            rel = entry.get("path")
            if not isinstance(rel, str) or not rel or rel in seen:
                raise ValueError("candidate manifest path is missing or duplicated")
            seen.add(rel)
            posix = PurePosixPath(rel)
            if posix.is_absolute() or any(part in {"", ".", ".."} for part in posix.parts):
                raise ValueError("candidate manifest path is unsafe")
            if any(
                token in rel.lower()
                for token in (".env", "credential", "secret", "id_rsa", ".pem", ".key")
            ):
                raise ValueError("candidate contains a sensitive-path artifact")

            # Selection rule: only candidate-modified/added files, active change specs,
            # or all files if the diff against base was completely empty.
            is_candidate_changed = rel in diff_changed
            is_active_change_spec = bool(
                (active_change_prefix and rel.startswith(active_change_prefix))
                or (active_change_dot_prefix and rel.startswith(active_change_dot_prefix))
            )
            # Security-critical paths touched by candidate are included by virtue of being in diff_changed.
            if not (is_candidate_changed or is_active_change_spec or is_empty_diff):
                continue

            path = root.joinpath(*posix.parts)
            if path.is_symlink() or not path.is_file():
                raise ValueError("candidate file is absent, non-regular, or a symlink")
            resolved = path.resolve(strict=True)
            resolved.relative_to(root)
            size_bytes = resolved.stat().st_size
            if (
                size_bytes > MAX_REVIEW_INPUT_BYTES
                or size + len(rel.encode()) + size_bytes > MAX_REVIEW_INPUT_BYTES
            ):
                raise ValueError("candidate source exceeds review input bound")
            raw = resolved.read_bytes()
            if hashlib.sha256(raw).hexdigest() != entry.get("sha256"):
                raise ValueError("candidate bytes do not match the frozen manifest")
            content = raw.decode("utf-8")
            safe_content = redact_secrets(content)
            size += len(rel.encode()) + len(safe_content.encode())
            if size > MAX_REVIEW_INPUT_BYTES:
                raise ValueError("candidate source exceeds review input bound")
            items.append({"path": rel, "sha256": entry["sha256"], "content": safe_content})

        all_deleted = sorted(diff_deleted | set(manifest.deleted_files))
        for rel in all_deleted:
            posix = PurePosixPath(rel)
            if posix.is_absolute() or any(part in {"", ".", ".."} for part in posix.parts):
                raise ValueError("deleted candidate path is unsafe")
            if root.joinpath(*posix.parts).exists():
                raise ValueError("manifest marks an existing candidate file deleted")
            deletion_context = ""
            if has_base:
                try:
                    cat_proc = subprocess.run(
                        ["git", "show", f"{candidate.base_sha}:{rel}"],
                        cwd=root,
                        capture_output=True,
                        text=True,
                    )
                    if cat_proc.returncode == 0:
                        deletion_context = redact_secrets(cat_proc.stdout[:2000])
                except Exception:
                    pass
            items.append({"path": rel, "deleted": "true", "content": deletion_context})

        if not items:
            raise ValueError("frozen candidate has no reviewable files")
        return items, safe_git_diff

    def _read_exact_checks(
        self, job: Job, candidate: OrchestrationCandidate
    ) -> list[dict[str, Any]]:
        checks = [
            check
            for check in self.uow.check_results.list_by_job(job.job_id)
            if check.candidate_sha == candidate.candidate_sha
            and check.candidate_generation == candidate.generation
        ]
        if not checks or any(check.exit_code != 0 for check in checks):
            raise ValueError("passing deterministic checks for the exact candidate are unavailable")
        return [
            {
                "check_name": item.check_name,
                "command": item.command,
                "exit_code": item.exit_code,
                "duration_ms": item.duration_ms,
                "output_snippet": redact_secrets(item.output_snippet),
            }
            for item in checks
        ]

    def _prior_checkpoint_matches(
        self, review, run, job, candidate, manifest, model, account
    ) -> bool:
        reservation = (
            self.uow.budget_reservations.get_by_id(review.budget_reservation_id)
            if review.budget_reservation_id
            else None
        )
        usage_recorded = any(
            event.event_type.value == "BUDGET_SETTLED"
            and event.operation_id == job.job_id
            and event.payload.get("review_id") == review.review_id
            for event in self.uow.events.list_events(
                project_id=run.project_id, change_id=job.change_name, limit=10000
            )
        )
        return bool(
            review.review_stage == "CODE_REVIEW"
            and review.project_id == run.project_id
            and review.job_id == job.job_id
            and review.change_name == job.change_name
            and review.orchestration_run_id == run.run_id
            and review.candidate_generation == candidate.generation
            and review.candidate_sha == candidate.candidate_sha
            and review.base_sha == candidate.base_sha
            and review.manifest_id == manifest.manifest_id
            and review.manifest_hash == manifest.manifest_hash
            and review.provider == "deepseek"
            and review.reviewer_role == "deepseek"
            and review.reviewer_model == model
            and review.account_fingerprint == account
            and review.billing_origin == "deepseek_direct"
            and (
                bool(
                    reservation
                    and reservation.status == "SETTLED"
                    and reservation.stage == "REVIEW"
                    and reservation.provider == "deepseek"
                    and reservation.account_fingerprint == account
                    and reservation.canonical_model_identity == model
                    and reservation.billing_origin == "deepseek_direct"
                )
                or (reservation is None and usage_recorded)
            )
        )
