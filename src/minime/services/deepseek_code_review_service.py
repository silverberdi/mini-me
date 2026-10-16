"""Candidate-bound, read-only DeepSeek Direct code review using R01 authorities."""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from decimal import Decimal
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
from minime.domain.enums import ProviderHealthStatus, ReviewStatus, ReviewVerdict
from minime.domain.interfaces import PersistenceUnitOfWork
from minime.domain.models import (
    CandidateManifest,
    Job,
    OrchestrationCandidate,
    OrchestrationRun,
    Project,
    Review,
    ReviewFinding,
    ReviewVerdictPayload,
)
from minime.logging import redact_secrets
from minime.services.authorship_service import AuthorshipService
from minime.services.budget_service import BudgetService
from minime.services.candidate_manifest import CandidateManifestService
from minime.services.contract_review_service import (
    DeepSeekContractReviewRunner,
    DeepSeekReviewResponse,
)
from minime.services.provider_health_service import ProviderHealthService
from minime.services.review_verdict_parser import parse_review_verdict

MAX_REVIEW_INPUT_BYTES = 1_000_000
MAX_REVIEW_OUTPUT_TOKENS = 4096


@dataclass(frozen=True)
class CodeReviewResult:
    accepted: bool
    review_id: str | None
    candidate_sha: str
    verdict: ReviewVerdictPayload | None = None
    reason: str | None = None
    waiting: bool = False


def _reservation_key(run_id: str, job_id: str, candidate_sha: str, manifest_hash: str) -> str:
    raw = json.dumps(
        [run_id, job_id, "REVIEW", candidate_sha, manifest_hash], separators=(",", ":")
    ).encode()
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
    ) -> CodeReviewResult:
        sha = candidate.candidate_sha
        if not self._identity_matches(project, run, job, candidate, manifest):
            return CodeReviewResult(
                False, None, sha, reason="CODE_REVIEW_CANDIDATE_IDENTITY_MISMATCH"
            )
        try:
            source_files = self._read_exact_candidate(candidate_worktree, candidate, manifest)
            checks = self._read_exact_checks(job, candidate)
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            return CodeReviewResult(
                False, None, sha, reason=f"CODE_REVIEW_PREFLIGHT_BLOCKED:{type(exc).__name__}"
            )

        surviving_paths = {item["path"] for item in source_files if item.get("path")}
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

        authorization = self._find_authorization(
            run, job, candidate, manifest, profile.model, account
        )
        if not authorization:
            return CodeReviewResult(
                False, None, sha, reason="DEEPSEEK_CODE_REVIEW_BUDGET_NOT_AUTHORIZED", waiting=True
            )
        auth = authorization.result_payload_json["authorization"]
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
        input_size = len(request_json.encode("utf-8"))
        if input_size > MAX_REVIEW_INPUT_BYTES:
            return CodeReviewResult(False, None, sha, reason="CODE_REVIEW_INPUT_EXCEEDS_BOUND")

        prior = self.uow.reviews.get_by_job_stage(job.job_id, "CODE_REVIEW")
        resumable_placeholder = False
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
                prior.status == ReviewStatus.REVIEW_RUNNING
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
            if not resumable_placeholder:
                return CodeReviewResult(
                    False,
                    prior.review_id,
                    sha,
                    reason="CODE_REVIEW_CHECKPOINT_EXISTS; refusing blind duplicate dispatch",
                    waiting=prior.status
                    in {ReviewStatus.REVIEW_PENDING, ReviewStatus.REVIEW_RUNNING},
                )

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
            pricing_snapshot_id=str(auth["pricing_snapshot_id"]),
            prompt_token_upper_bound=input_size,
            max_output_tokens=MAX_REVIEW_OUTPUT_TOKENS,
            idempotency_key=_reservation_key(
                run.run_id, job.job_id, candidate.candidate_sha, manifest.manifest_hash
            ),
            candidate_sha=candidate.candidate_sha,
            candidate_generation=candidate.generation,
            manifest_id=manifest.manifest_id,
            manifest_hash=manifest.manifest_hash,
        )
        if not reservation:
            return CodeReviewResult(False, None, sha, reason=denial, waiting=True)

        review = (
            prior.model_copy(
                update={
                    "reviewer_model": profile.model,
                    "provider": "deepseek",
                    "account_fingerprint": account,
                    "budget_authorization_id": authorization.action_request_id,
                    "budget_reservation_id": reservation.reservation_id,
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
                budget_authorization_id=authorization.action_request_id,
                budget_reservation_id=reservation.reservation_id,
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
        self.uow.commit()
        # A committed RUNNING checkpoint prevents a billed request from being replayed blindly.
        if review.status == ReviewStatus.REVIEW_PENDING:
            self.uow.reviews.transition(review.review_id, ReviewStatus.REVIEW_RUNNING.value)
            self.uow.commit()
            review = self.uow.reviews.get_by_id(review.review_id) or review

        runner = self.runner or DeepSeekContractReviewRunner(
            api_key=getattr(adapter, "authenticated_api_key", None),
            model=profile.model,
            effort=profile.effort,
            review_stage="CODE_REVIEW",
        )
        if (
            getattr(runner, "model", None) != profile.model
            or getattr(runner, "effort", None) != profile.effort
            or getattr(runner, "review_stage", "CODE_REVIEW") != "CODE_REVIEW"
        ):
            self.budget.mark_unresolved(reservation.reservation_id)
            self.uow.reviews.transition(
                review.review_id,
                ReviewStatus.REVIEW_FAILED.value,
                error_message="DeepSeek runner identity does not match the authorized code-review profile.",
            )
            self.uow.commit()
            return CodeReviewResult(
                False, review.review_id, sha, reason="CODE_REVIEW_RUNNER_PROFILE_MISMATCH"
            )
        try:
            response: DeepSeekReviewResponse = await runner.review(
                request_json, self.timeout_seconds
            )
        except Exception as exc:
            # The request may have reached DeepSeek and been billed. Preserve the
            # running checkpoint and unresolved reservation; never replay blindly.
            self.budget.mark_unresolved(reservation.reservation_id)
            self.uow.commit()
            return CodeReviewResult(
                False,
                review.review_id,
                sha,
                reason=f"CODE_REVIEW_OUTCOME_AMBIGUOUS:{type(exc).__name__}",
            )
        if (
            response.exit_code != 0
            or response.error
            or response.model != profile.model
            or not response.content
            or not isinstance(response.prompt_tokens, int)
            or isinstance(response.prompt_tokens, bool)
            or response.prompt_tokens < 0
            or not isinstance(response.completion_tokens, int)
            or isinstance(response.completion_tokens, bool)
            or response.completion_tokens < 0
        ):
            self.budget.mark_unresolved(reservation.reservation_id)
            self.uow.reviews.transition(
                review.review_id,
                ReviewStatus.REVIEW_FAILED.value,
                error_message=response.error
                or "DeepSeek code-review response identity or usage is unverifiable.",
            )
            self.uow.commit()
            return CodeReviewResult(
                False,
                review.review_id,
                sha,
                reason="DEEPSEEK_CODE_REVIEW_RESPONSE_UNVERIFIABLE",
                waiting=True,
            )
        try:
            verdict = parse_review_verdict(response.content)
        except (ValueError, TypeError):
            self.budget.mark_unresolved(reservation.reservation_id)
            self.uow.reviews.transition(
                review.review_id,
                ReviewStatus.REVIEW_FAILED.value,
                error_message="DeepSeek code review did not match the strict verdict schema.",
            )
            self.uow.commit()
            return CodeReviewResult(False, review.review_id, sha, reason="CODE_REVIEW_MALFORMED")

        snapshot = self.uow.pricing_snapshots.get_by_id(reservation.pricing_snapshot_id)
        if not snapshot:
            self.budget.mark_unresolved(reservation.reservation_id)
            return CodeReviewResult(
                False, review.review_id, sha, reason="CODE_REVIEW_PRICE_EVIDENCE_MISSING"
            )
        actual_cost = (
            Decimal(response.prompt_tokens) * snapshot.prompt_price_per_token
            + Decimal(response.completion_tokens) * snapshot.output_price_per_token
            + snapshot.additional_cost_per_request
        )
        settled = self.budget.settle_reservation(
            reservation_id=reservation.reservation_id,
            actual_cost_usd=actual_cost,
            prompt_tokens=response.prompt_tokens,
            completion_tokens=response.completion_tokens,
            total_tokens=response.prompt_tokens + response.completion_tokens,
        )
        if not settled:
            self.budget.mark_unresolved(reservation.reservation_id)
            self.uow.reviews.transition(
                review.review_id,
                ReviewStatus.REVIEW_FAILED.value,
                error_message="DeepSeek code-review spend could not be reconciled within its authorization.",
            )
            self.uow.commit()
            return CodeReviewResult(
                False, review.review_id, sha, reason="CODE_REVIEW_BUDGET_RECONCILIATION_FAILED"
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
        self.uow.commit()
        return CodeReviewResult(True, review.review_id, sha, verdict)

    @staticmethod
    def _identity_matches(project, run, job, candidate, manifest) -> bool:
        return bool(
            run.project_id == project.project_id
            and run.change_name == job.change_name
            and job.project_id == project.project_id
            and run.active_job_id == job.job_id
            and run.current_candidate_sha == candidate.candidate_sha
            and run.current_generation == candidate.generation
            and candidate.run_id == run.run_id
            and candidate.is_frozen
            and candidate.base_sha == run.base_sha == job.base_sha
            and candidate.candidate_sha == job.candidate_sha
            and candidate.manifest_id == manifest.manifest_id
            and candidate.manifest_hash == manifest.manifest_hash
            and manifest.job_id == job.job_id
            and manifest.candidate_sha == candidate.candidate_sha
        )

    @staticmethod
    def _read_exact_candidate(
        worktree: str | Path, candidate: OrchestrationCandidate, manifest: CandidateManifest
    ) -> list[dict[str, str]]:
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
        for rel in manifest.deleted_files:
            posix = PurePosixPath(rel)
            if posix.is_absolute() or any(part in {"", ".", ".."} for part in posix.parts):
                raise ValueError("deleted candidate path is unsafe")
            if root.joinpath(*posix.parts).exists():
                raise ValueError("manifest marks an existing candidate file deleted")
            items.append({"path": rel, "deleted": "true", "content": ""})
        if not items:
            raise ValueError("frozen candidate has no reviewable files")
        return items

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

    def _find_authorization(self, run, job, candidate, manifest, model: str, account: str):
        for action in self.uow.operator_actions.list_by_run(run.run_id):
            auth = action.result_payload_json.get("authorization", {})
            if (
                action.action_type.value == "AUTHORIZE_DEEPSEEK_CODE_REVIEW"
                and action.status.value == "COMPLETED"
                and action.project_id == run.project_id
                and action.change_name == job.change_name
                and action.run_id == run.run_id
                and action.job_id == job.job_id
                and auth.get("stage") == "REVIEW"
                and auth.get("provider") == "deepseek"
                and auth.get("model") == model
                and auth.get("account_fingerprint") == account
                and auth.get("billing_origin") == "deepseek_direct"
                and auth.get("candidate_sha") == candidate.candidate_sha
                and auth.get("base_sha") == candidate.base_sha
                and auth.get("generation") == candidate.generation
                and auth.get("manifest_id") == manifest.manifest_id
                and auth.get("manifest_hash") == manifest.manifest_hash
            ):
                return action
        return None

    def _prior_checkpoint_matches(
        self, review, run, job, candidate, manifest, model, account
    ) -> bool:
        reservation = (
            self.uow.budget_reservations.get_by_id(review.budget_reservation_id)
            if review.budget_reservation_id
            else None
        )
        authorization = (
            self.uow.operator_actions.get_by_request_id(review.budget_authorization_id)
            if review.budget_authorization_id
            else None
        )
        auth = authorization.result_payload_json.get("authorization", {}) if authorization else {}
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
            and reservation
            and reservation.status == "SETTLED"
            and reservation.stage == "REVIEW"
            and reservation.provider == "deepseek"
            and reservation.account_fingerprint == account
            and reservation.canonical_model_identity == model
            and reservation.authorization_id == review.budget_authorization_id
            and authorization
            and authorization.action_type.value == "AUTHORIZE_DEEPSEEK_CODE_REVIEW"
            and authorization.status.value == "COMPLETED"
            and auth.get("candidate_sha") == candidate.candidate_sha
            and auth.get("manifest_hash") == manifest.manifest_hash
        )
