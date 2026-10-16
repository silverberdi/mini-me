"""Deterministic review-evidence validation and STALE_REVIEW reporting."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from minime.domain.enums import ReviewStatus, ReviewVerdict
from minime.domain.interfaces import PersistenceUnitOfWork
from minime.domain.models import Job, OrchestrationCandidate, OrchestrationRun, Project


def validate_review_authority(
    uow: PersistenceUnitOfWork,
    run: OrchestrationRun,
    job: Job,
    cand: OrchestrationCandidate,
    authorship_service: Any,
) -> tuple[bool, ReviewVerdict | None, str | None]:
    """Deterministically validate review authority against the current candidate.

    Requires: a candidate with candidate_sha; a review record for the job with
    status REVIEW_COMPLETED; exact candidate/base SHA binding; manifest and
    generation binding; reviewer identity matching the assigned reviewer; a
    structured verdict; and reviewer independence. Fails closed on any missing
    field, mismatched identity, or wrong generation.
    """
    if not cand or not cand.candidate_sha:
        return False, None, "No active candidate recorded."

    existing_review = uow.reviews.get_by_job_id(job.job_id)
    if not existing_review:
        return False, None, f"No review record exists for job '{job.job_id}'."

    if existing_review.status != ReviewStatus.REVIEW_COMPLETED:
        return (
            False,
            None,
            f"Review status '{existing_review.status.value}' is not REVIEW_COMPLETED.",
        )

    required_review_binding = {
        "orchestration_run_id": (existing_review.orchestration_run_id, run.run_id),
        "candidate_generation": (existing_review.candidate_generation, cand.generation),
        "manifest_id": (existing_review.manifest_id, cand.manifest_id),
        "manifest_hash": (existing_review.manifest_hash, cand.manifest_hash),
    }
    for field_name, (actual, expected) in required_review_binding.items():
        if actual is None or actual == "":
            return False, None, f"Review binding field '{field_name}' is missing."
        if expected is None or actual != expected:
            return (
                False,
                None,
                f"Review binding field '{field_name}' does not match current candidate.",
            )

    project = uow.projects.get_by_id(run.project_id)
    if (
        not project
        or existing_review.review_stage != "CODE_REVIEW"
        or existing_review.provider != "deepseek"
        or existing_review.reviewer_role != "deepseek"
        or existing_review.billing_origin != "deepseek_direct"
        or not existing_review.account_fingerprint
        or not existing_review.budget_authorization_id
        or not existing_review.budget_reservation_id
    ):
        return False, None, "Review is not an authorized direct DeepSeek CODE_REVIEW record."

    authorization = uow.operator_actions.get_by_request_id(
        existing_review.budget_authorization_id
    )
    reservation = uow.budget_reservations.get_by_id(existing_review.budget_reservation_id)
    auth = (
        authorization.result_payload_json.get("authorization", {}) if authorization else {}
    )
    if not (
        authorization
        and authorization.action_type.value == "AUTHORIZE_DEEPSEEK_CODE_REVIEW"
        and authorization.status.value == "COMPLETED"
        and authorization.project_id == project.project_id
        and authorization.change_name == job.change_name
        and authorization.run_id == run.run_id
        and authorization.job_id == job.job_id
        and auth.get("stage") == "REVIEW"
        and auth.get("provider") == "deepseek"
        and auth.get("billing_origin") == "deepseek_direct"
        and auth.get("account_fingerprint") == existing_review.account_fingerprint
        and auth.get("model") == existing_review.reviewer_model
        and auth.get("candidate_sha") == existing_review.candidate_sha
        and auth.get("base_sha") == existing_review.base_sha
        and auth.get("generation") == existing_review.candidate_generation
        and auth.get("manifest_id") == existing_review.manifest_id
        and auth.get("manifest_hash") == existing_review.manifest_hash
        and reservation
        and reservation.status == "SETTLED"
        and reservation.authorization_id == authorization.action_request_id
        and reservation.provider == "deepseek"
        and reservation.account_fingerprint == existing_review.account_fingerprint
        and reservation.canonical_model_identity == existing_review.reviewer_model
        and reservation.stage == "REVIEW"
        and reservation.billing_origin == "deepseek_direct"
    ):
        return False, None, "Review lacks matching candidate-bound budget authorization and settlement."

    if not existing_review.candidate_sha or existing_review.candidate_sha != cand.candidate_sha:
        return (
            False,
            None,
            f"Review candidate SHA '{existing_review.candidate_sha}' does not match "
            f"current candidate '{cand.candidate_sha}'.",
        )

    if not existing_review.base_sha or existing_review.base_sha != run.base_sha:
        return (
            False,
            None,
            f"Review base SHA '{existing_review.base_sha}' does not match run base '{run.base_sha}'.",
        )

    if existing_review.verdict is None:
        return False, None, "Review has no structured verdict."

    is_eligible, ineligibility_reason = authorship_service.is_reviewer_eligible(
        job.job_id, existing_review.reviewer_role, uow
    )
    if not is_eligible:
        return False, None, ineligibility_reason

    return True, existing_review.verdict, None


@dataclass(frozen=True)
class ReviewEvidenceReport:
    """Structured review-evidence evaluation used by VERIFY and the integrity auditor."""

    satisfied: bool
    status: str  # PASS | FAIL | UNKNOWN
    reason: str | None = None
    finding_category: str | None = None  # STALE_REVIEW | MISSING_REVIEW | None
    review_id: str | None = None
    candidate_sha: str | None = None
    expected_candidate_sha: str | None = None
    run_id: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


def build_review_evidence_report(
    uow: PersistenceUnitOfWork,
    run: OrchestrationRun,
    job: Job,
    candidate: OrchestrationCandidate,
    project: Project,
    authorship_service: Any,
) -> ReviewEvidenceReport:
    """Build a fail-closed review-evidence report bound to the current candidate."""
    expected_sha = candidate.candidate_sha if candidate else run.current_candidate_sha
    existing_review = uow.reviews.get_by_job_id(job.job_id)
    if not existing_review:
        return ReviewEvidenceReport(
            satisfied=False,
            status="FAIL",
            finding_category="MISSING_REVIEW",
            reason=f"No review record exists for job '{job.job_id}'.",
            expected_candidate_sha=expected_sha,
            run_id=run.run_id,
        )

    stale = bool(
        existing_review.candidate_sha
        and expected_sha
        and existing_review.candidate_sha != expected_sha
    )

    valid, verdict, reason = validate_review_authority(uow, run, job, candidate, authorship_service)
    if valid:
        return ReviewEvidenceReport(
            satisfied=True,
            status="PASS",
            review_id=existing_review.review_id,
            candidate_sha=existing_review.candidate_sha,
            expected_candidate_sha=expected_sha,
            run_id=run.run_id,
            details={"verdict": verdict.value if verdict else None},
        )

    return ReviewEvidenceReport(
        satisfied=False,
        status="FAIL",
        reason=reason,
        finding_category="STALE_REVIEW" if stale else None,
        review_id=existing_review.review_id,
        candidate_sha=existing_review.candidate_sha,
        expected_candidate_sha=expected_sha,
        run_id=run.run_id,
        details={"stale": stale},
    )
