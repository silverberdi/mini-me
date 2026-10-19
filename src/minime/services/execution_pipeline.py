"""Execution pipeline orchestration for implementation, complementary review, and budgeted drain fallback."""

from __future__ import annotations

import inspect
import logging
import os
import re
import subprocess
from decimal import Decimal
from pathlib import Path
from typing import Any

from minime.adapters.openrouter_adapter import OpenRouterAdapter, OpenRouterRequest
from minime.config import (
    AppConfig,
    OpenSpecStage,
    ProjectConfig,
    ResolvedStageProfile,
    StageProfileError,
    load_config,
    resolve_stage_profile,
)
from minime.domain.enums import (
    AttemptProductivityClass,
    AuditFindingSeverity,
    AuditRiskLevel,
    AuditStatus,
    BlockerValidationVerdict,
    ContinuationDecision,
    EventType,
    EvidenceDiagnosticStatus,
    ExecutionOutcome,
    FindingSeverity,
    JobStatus,
    PremiumProviderReasonCode,
    PrimaryProvider,
    ProgressClassification,
    ProviderHealthStatus,
    ProviderResultClass,
    ReadinessState,
    ReviewStatus,
    ReviewVerdict,
    WorktreeCreationState,
)
from minime.domain.interfaces import PersistenceUnitOfWork
from minime.domain.models import (
    AuditFinding,
    AuditRecord,
    BlockerClaim,
    BlockerClaimPayload,
    Event,
    EvidenceDiagnostic,
    Job,
    JobAttempt,
    JobLog,
    MetricFact,
    Project,
    RecoveryClaimContext,
    Review,
    ReviewFinding,
    utc_now,
)
from minime.logging import redact_secrets
from minime.services.audit_verdict_parser import parse_audit_result
from minime.services.authorship_service import AuthorshipService
from minime.services.blocker_validation import (
    BlockerValidationContext,
    BlockerValidationService,
)
from minime.services.budget_service import BudgetService
from minime.services.candidate_integrity import (
    validate_post_review_integrity,
    validate_pre_review_integrity,
    verify_post_audit,
    verify_pre_audit,
)
from minime.services.candidate_manifest import (
    CandidateArtifactRejectionError,
    CandidateManifestService,
)
from minime.services.capacity_lifecycle_service import CapacityLifecycleService
from minime.services.checks_runner import ChecksRunner, ChecksRunResult
from minime.services.cli_preflight import preflight_cli_invocation
from minime.services.complementary_policy import validate_complementary_pair
from minime.services.continuation_engine import (
    ContinuationContext,
    ContinuationEngine,
)
from minime.services.contract_review_service import ContractReviewService
from minime.services.deepseek_auditor_runner import (
    AuditorRunnerInterface,
    DeepSeekAuditorRunner,
    build_audit_prompt,
)
from minime.services.deepseek_code_review_service import DeepSeekCodeReviewService
from minime.services.efficiency_telemetry_service import EfficiencyTelemetryService
from minime.services.handoff_manager import HandoffManager
from minime.services.implementer_runner import (
    CliImplementerRunner,
    ImplementerRunnerInterface,
    runner_for_implementer,
)
from minime.services.lightweight_reconciliation_service import LightweightReconciliationService
from minime.services.model_independence_policy import ModelIndependencePolicy
from minime.services.native_openspec_apply import (
    NativeOpenSpecWorkflowUnavailable,
    resolve_native_openspec_apply,
    workflow_unchanged,
)
from minime.services.openrouter_eligibility import OpenRouterEligibilityEvaluator
from minime.services.openspec_tasks import OpenSpecTaskTracker, is_verification_task
from minime.services.outcome_governance import (
    OutcomeGovernanceService,
    ProgressSignals,
)
from minime.services.provider_health_service import ProviderHealthService
from minime.services.provider_outcome_parser import ProviderOutcomeParser
from minime.services.provider_policy_service import ProviderPolicyService
from minime.services.review_verdict_parser import parse_review_verdict
from minime.services.reviewer_contract import build_reviewer_prompt
from minime.services.reviewer_runner import (
    CliReviewerRunner,
    ReviewerRunnerInterface,
    runner_for_reviewer,
)
from minime.services.reviewer_view import ReviewerViewManager
from minime.services.task_classifier import TaskClassifier
from minime.services.worktree_manager import WorktreeManager

logger = logging.getLogger(__name__)


def format_candidate_workspace_context(worktree_path: str | Path) -> str:
    """Build the provider-agnostic workspace boundary for an implementer attempt."""
    resolved_path = Path(worktree_path).resolve()
    return "\n".join(
        [
            "CANDIDATE WORKSPACE",
            f"Absolute path: {resolved_path}",
            "",
            "Treat this path as the authoritative candidate workspace for this attempt.",
            "Perform all repository reads, writes, edits, and generated implementation artifacts inside this workspace only.",
            "Do not write candidate files to provider scratch directories, another checkout, or the parent repository root.",
        ]
    )


def _classify_attempt_productivity(
    outcome: ExecutionOutcome,
    progress: ProgressClassification | None,
    *,
    is_same_sha_duplicate: bool,
) -> AttemptProductivityClass:
    """Classify provider completion from observed repository/task progress.

    A zero-exit provider result is not itself evidence of productive work. This
    keeps no-op completions from being recorded as substantive progress when
    Git/task evidence says otherwise.
    """
    if is_same_sha_duplicate:
        return AttemptProductivityClass.SAME_SHA_NO_PROGRESS
    if outcome == ExecutionOutcome.COMPLETED:
        if progress in {
            ProgressClassification.GOOD_PROGRESS,
            ProgressClassification.PARTIAL_PROGRESS,
        }:
            return AttemptProductivityClass.SUBSTANTIVE_PROGRESS
        return AttemptProductivityClass.OTHER
    if progress in {
        ProgressClassification.GOOD_PROGRESS,
        ProgressClassification.PARTIAL_PROGRESS,
    }:
        return AttemptProductivityClass.SUBSTANTIVE_PROGRESS
    if outcome in {ExecutionOutcome.CHANGES_REQUIRED, ExecutionOutcome.FALSE_BLOCKER}:
        return AttemptProductivityClass.VALID_CORRECTIVE_WORK
    if outcome in {ExecutionOutcome.AUTH_REQUIRED, ExecutionOutcome.PROVIDER_PREFLIGHT_FAILURE}:
        return AttemptProductivityClass.PROVIDER_PREFLIGHT_FAILURE
    if outcome == ExecutionOutcome.PROVIDER_FAILURE:
        return AttemptProductivityClass.PROVIDER_FAILURE
    return AttemptProductivityClass.SAME_SHA_NO_PROGRESS


EVENT_BY_STATUS = {
    JobStatus.QUEUED: EventType.JOB_QUEUED,
    JobStatus.RUNNING: EventType.JOB_RUNNING,
    JobStatus.CHECKS_RUNNING: EventType.JOB_CHECKS_RUNNING,
    JobStatus.CHECKS_PASSED: EventType.JOB_CHECKS_PASSED,
    JobStatus.CHECKS_FAILED: EventType.JOB_CHECKS_FAILED,
    JobStatus.REVIEW_RUNNING: EventType.JOB_REVIEW_RUNNING,
    JobStatus.AUDIT_RUNNING: EventType.JOB_AUDIT_RUNNING,
    JobStatus.READY_TO_MERGE: EventType.JOB_READY_TO_MERGE,
    JobStatus.AUDIT_BLOCKED: EventType.JOB_AUDIT_BLOCKED,
    JobStatus.CHANGES_REQUIRED: EventType.JOB_CHANGES_REQUIRED,
    JobStatus.WAITING_CAPACITY: EventType.JOB_WAITING_CAPACITY,
    JobStatus.RECOVERY_BLOCKED: EventType.RECOVERY_BLOCKED,
    JobStatus.NEEDS_HUMAN: EventType.JOB_NEEDS_HUMAN,
    JobStatus.FAILED: EventType.JOB_FAILED,
    JobStatus.CANCELLED: EventType.JOB_CANCELLED,
}


class ExecutionPipelineService:
    """Coordinates job state, isolated workspace, implementer execution, checks, complementary review, and fallback."""

    def __init__(
        self,
        uow: PersistenceUnitOfWork,
        project_root: str | Path,
        implementer_runner: ImplementerRunnerInterface | None = None,
        reviewer_runner: ReviewerRunnerInterface | None = None,
        auditor_runner: AuditorRunnerInterface | None = None,
        worktree_manager: WorktreeManager | None = None,
        reviewer_view_manager: ReviewerViewManager | None = None,
        checks_runner: ChecksRunner | None = None,
        task_tracker: OpenSpecTaskTracker | None = None,
        health_service: ProviderHealthService | None = None,
        lifecycle_service: CapacityLifecycleService | None = None,
        budget_service: BudgetService | None = None,
        openrouter_adapter: OpenRouterAdapter | None = None,
        independence_policy: ModelIndependencePolicy | None = None,
        eligibility_evaluator: OpenRouterEligibilityEvaluator | None = None,
        outcome_governance: OutcomeGovernanceService | None = None,
        blocker_validation: BlockerValidationService | None = None,
        continuation_engine: ContinuationEngine | None = None,
        handoff_manager: HandoffManager | None = None,
        authorship_service: AuthorshipService | None = None,
        manifest_service: CandidateManifestService | None = None,
        openrouter_api_key: str | None = None,
        implementer_timeout_seconds: int = 3600,
        reviewer_timeout_seconds: int = 3600,
        app_config: AppConfig | None = None,
        contract_review_service: ContractReviewService | None = None,
        code_review_service: DeepSeekCodeReviewService | None = None,
    ):
        self.uow = uow
        self.project_root = Path(project_root)
        self.app_config = app_config or load_config()
        self.contract_review_service = contract_review_service
        self.code_review_service = code_review_service
        self.implementer_runner = implementer_runner
        self.reviewer_runner = reviewer_runner
        self.auditor_runner = auditor_runner
        self.worktree_manager = worktree_manager or WorktreeManager(self.project_root, uow=self.uow)
        self.reviewer_view_manager = reviewer_view_manager or ReviewerViewManager(self.project_root)
        self.checks_runner = checks_runner or ChecksRunner()
        self.task_tracker = task_tracker or OpenSpecTaskTracker(self.project_root)
        self.health_service = health_service or ProviderHealthService(self.uow)
        self.lifecycle_service = lifecycle_service or CapacityLifecycleService(
            self.uow, health_service=self.health_service
        )
        self.budget_service = budget_service or BudgetService(self.uow)
        self.openrouter_adapter = openrouter_adapter or OpenRouterAdapter()
        self.independence_policy = independence_policy or ModelIndependencePolicy()
        self.eligibility_evaluator = eligibility_evaluator or OpenRouterEligibilityEvaluator()
        self.outcome_governance = outcome_governance or OutcomeGovernanceService(self.task_tracker)
        self.blocker_validation = blocker_validation or BlockerValidationService()
        self.continuation_engine = continuation_engine or ContinuationEngine()
        self.handoff_manager = handoff_manager or HandoffManager()
        self.authorship_service = authorship_service or AuthorshipService()
        self.manifest_service = manifest_service or CandidateManifestService()
        self.task_classifier = TaskClassifier()
        self.provider_policy = ProviderPolicyService(self.uow)
        self.reconciliation_service = LightweightReconciliationService(self.uow)
        self.telemetry_service = EfficiencyTelemetryService(self.uow)
        self.openrouter_api_key = openrouter_api_key
        self.implementer_timeout_seconds = implementer_timeout_seconds
        self.reviewer_timeout_seconds = reviewer_timeout_seconds
        self.default_implementer_model = "anthropic/claude-3.5-sonnet"
        self.allowed_reviewer_models = [
            "openai/gpt-4o",
            "meta-llama/llama-3.3-70b-instruct",
            "mistralai/mistral-large",
        ]

    async def _working_state_fingerprint(self, worktree_path: Path) -> str:
        method = getattr(self.worktree_manager, "working_state_fingerprint", None)
        if method is None:
            return ""
        result = method(worktree_path)
        return str(await result) if inspect.isawaitable(result) else str(result)

    async def _finalize_candidate(
        self, worktree_path: Path, job_id: str, project_id: str, current_sha: str
    ) -> str:
        method = getattr(self.worktree_manager, "finalize_candidate_commit", None)
        if method is None:
            return current_sha
        result = method(worktree_path, job_id, project_id)
        return str(await result) if inspect.isawaitable(result) else current_sha

    def _get_provider_health(self, provider: str):
        getter = getattr(self.health_service, "get_health", None)
        return getter(provider) if callable(getter) else None

    def _stage_capacity_evidence_matches(self, provider: str, model: str | None) -> bool:
        """Bind JIT evidence to the model/scope selected for this exact stage."""
        if not model:
            return False
        verifier = getattr(self.health_service, "has_fresh_capacity_evidence", None)
        if not callable(verifier):
            return False
        quota_scope = None
        if provider == "codex":
            quota_scope = "codex"
        elif provider in {"antigravity", "agy"}:
            from minime.adapters.provider_adapter import AntigravityProviderAdapter

            quota_scope = AntigravityProviderAdapter.map_model_to_quota_group(model)
            if quota_scope is None:
                return False
        try:
            return bool(verifier(provider, model=model, quota_scope=quota_scope))
        except Exception:
            logger.info("Stage-bound capacity evidence unavailable for %s", provider)
            return False

    async def _refresh_capacity_before_stage(self, provider: str, model: str | None = None):
        """Refresh provider-owned capacity immediately before a stage is dispatched."""
        refresh = getattr(self.health_service, "refresh_capacity_from_read_only_source", None)
        if callable(refresh):
            try:
                sig = inspect.signature(refresh)
                if "model" in sig.parameters:
                    result = refresh(provider, model=model)
                else:
                    result = refresh(provider)
                if inspect.isawaitable(result):
                    await result
            except Exception:
                logger.info("JIT read-only capacity observation unavailable for %s", provider)
        return self._get_provider_health(provider)

    def _get_project_config(self, project: Project) -> ProjectConfig:
        from minime.config import StageProfileConfig

        if project.project_id in self.app_config.projects:
            cfg = self.app_config.projects[project.project_id].model_copy(deep=True)
            if project.implementer:
                cfg.implementer = project.implementer
            if project.reviewer:
                cfg.reviewer = project.reviewer
            if project.reviewer and project.reviewer == project.implementer:
                cfg.stage_profiles["REVIEW"] = StageProfileConfig(
                    provider=project.reviewer,
                    model="",
                    effort="medium",
                    workflow="openspec-verify-change",
                )
            return cfg
        stage_profiles = {}
        if project.reviewer and project.reviewer == project.implementer:
            stage_profiles["REVIEW"] = StageProfileConfig(
                provider=project.reviewer,
                model="",
                effort="medium",
                workflow="openspec-verify-change",
            )
        return ProjectConfig(
            repository=project.repository,
            base_branch=project.base_branch,
            openspec_path=project.openspec_path,
            implementer=project.implementer,
            reviewer=project.reviewer,
            checks=project.checks,
            external_providers_allowed=project.external_providers_allowed,
            openrouter_drain_allowed=project.openrouter_drain_allowed,
            stage_profiles=stage_profiles,
        )

    def _resolve_stage_profile(
        self,
        project: Project,
        stage: OpenSpecStage | str,
        *,
        requested_provider: str | None = None,
        requested_model: str | None = None,
        requested_effort: str | None = None,
        implementer_provider: str | None = None,
    ) -> ResolvedStageProfile:
        project_config = self._get_project_config(project)
        return resolve_stage_profile(
            project_config,
            stage,
            app_config=self.app_config,
            requested_provider=requested_provider,
            requested_model=requested_model,
            requested_effort=requested_effort,
            implementer_provider=implementer_provider,
        )

    def _verify_frozen_candidate_review_resume(
        self,
        *,
        run_identity,
        job: Job,
        candidate_generation: int,
        worktree,
    ):
        """Return the exact frozen candidate/manifest only when review-only resume is safe."""
        if (
            run_identity is None
            or run_identity.project_id != job.project_id
            or run_identity.change_name != job.change_name
            or run_identity.active_job_id != job.job_id
            or run_identity.current_generation != candidate_generation
            or run_identity.current_candidate_sha != job.candidate_sha
            or not job.candidate_sha
            or not job.base_sha
            or run_identity.base_sha != job.base_sha
            or getattr(worktree, "base_sha", None) != job.base_sha
        ):
            return None, None, "durable Run/Job/candidate identity is inconsistent"

        candidate = self.uow.orchestration_candidates.get_by_generation(
            run_identity.run_id, candidate_generation
        )
        if (
            candidate is None
            or not candidate.is_frozen
            or candidate.run_id != run_identity.run_id
            or candidate.base_sha != job.base_sha
            or candidate.candidate_sha != job.candidate_sha
            or not candidate.candidate_ref
        ):
            return None, None, "matching frozen candidate record is unavailable"

        manifest = self.uow.candidate_manifests.get_by_id(candidate.manifest_id)
        if (
            manifest is None
            or manifest.job_id != job.job_id
            or manifest.candidate_sha != candidate.candidate_sha
            or manifest.manifest_id != candidate.manifest_id
            or manifest.manifest_hash != candidate.manifest_hash
            or not manifest.manifest_hash
            or manifest.total_files_count <= 0
        ):
            return None, None, "candidate manifest does not match the frozen record"

        root = Path(worktree.path).resolve(strict=True)
        if Path(worktree.path).is_symlink() or not root.is_dir():
            return None, None, "candidate worktree is missing or resolves through a symlink"
        try:
            git_root = subprocess.run(
                ["git", "rev-parse", "--show-toplevel"],
                cwd=root,
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
            head = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=root,
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
            branch = subprocess.run(
                ["git", "symbolic-ref", "--short", "HEAD"],
                cwd=root,
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
            status = subprocess.run(
                ["git", "status", "--porcelain=v1", "--untracked-files=all"],
                cwd=root,
                capture_output=True,
                text=True,
                check=True,
            ).stdout
        except (OSError, subprocess.SubprocessError) as exc:
            return None, None, f"candidate Git identity is unobservable ({type(exc).__name__})"

        expected_branch = candidate.candidate_ref.removeprefix("refs/heads/")
        if (
            Path(git_root).resolve() != root
            or head != candidate.candidate_sha
            or branch != expected_branch
            or status
        ):
            return None, None, "candidate worktree HEAD, branch, repository, or cleanliness differs"

        try:
            observed_manifest = self.manifest_service.generate_manifest(
                root, candidate.candidate_sha, job.job_id
            )
        except (CandidateArtifactRejectionError, OSError, ValueError) as exc:
            return None, None, f"candidate manifest cannot be verified ({type(exc).__name__})"
        if (
            observed_manifest.manifest_hash != manifest.manifest_hash
            or observed_manifest.tracked_files != manifest.tracked_files
            or observed_manifest.staged_files != manifest.staged_files
            or observed_manifest.untracked_files != manifest.untracked_files
            or observed_manifest.deleted_files != manifest.deleted_files
            or observed_manifest.total_files_count != manifest.total_files_count
        ):
            return None, None, "candidate tree does not reproduce its frozen manifest"
        return candidate, manifest, None

    async def _preserve_and_cleanup_worktree(self, job: Job, worktree) -> None:
        """Preserve active orchestration candidates for review/remediation resume."""
        if job.candidate_sha:
            runs_repo = getattr(self.uow, "orchestration_runs", None)
            ownership_repo = getattr(self.uow, "orchestration_worktree_ownerships", None)
            ownership = ownership_repo.get_by_job_id(job.job_id) if ownership_repo else None
            run = (
                runs_repo.get_by_id(ownership.run_id)
                if runs_repo and ownership and ownership.run_id
                else None
            )
            if ownership is not None:
                if run is None:
                    raise RuntimeError(
                        "Candidate worktree preservation denied: durable ownership has no matching Run."
                    )
                if (
                    ownership.creation_state != WorktreeCreationState.CREATED
                    or Path(ownership.canonical_worktree_path).is_symlink()
                    or not Path(ownership.canonical_worktree_path).is_dir()
                    or str(Path(ownership.canonical_worktree_path).resolve())
                    != str(Path(worktree.path).resolve())
                    or ownership.branch != worktree.branch_name
                    or run.active_job_id != job.job_id
                    or run.project_id != job.project_id
                    or run.change_name != job.change_name
                ):
                    raise RuntimeError(
                        "Candidate worktree preservation denied: active Run/Job identity conflicts."
                    )
                manifests = getattr(self.uow, "candidate_manifests", None)
                manifest = (
                    manifests.get_by_candidate_sha(job.job_id, job.candidate_sha)
                    if manifests
                    else None
                )
                if (
                    not manifest
                    or manifest.candidate_sha != job.candidate_sha
                    or not manifest.manifest_hash
                    or manifest.total_files_count <= 0
                ):
                    # Keep the physical worktree even when its candidate evidence is
                    # incomplete. A later governed retry must fail closed, not lose it.
                    raise RuntimeError(
                        "Candidate worktree preservation denied: matching durable manifest is unavailable."
                    )
                return

        # Candidate-free attempts retain the existing snapshot-then-cleanup path.
        create_snapshot = getattr(self.worktree_manager, "create_recovery_snapshot", None)
        remove_clean = getattr(self.worktree_manager, "remove_clean_worktree", None)
        if inspect.iscoroutinefunction(create_snapshot) and inspect.iscoroutinefunction(
            remove_clean
        ):
            try:
                recovery_sha = await create_snapshot(job.job_id, project_id=job.project_id)
            except TypeError:
                recovery_sha = await create_snapshot(job.job_id)
            if recovery_sha:
                latest = self._require_job(job.job_id)
                self._save_event(
                    EventType.WORKTREE_RECOVERY_SNAPSHOT,
                    latest,
                    {
                        "recovery_sha": recovery_sha,
                        "branch": worktree.branch_name,
                        "worktree_path": str(worktree.path),
                        "authoritative_candidate": False,
                    },
                )
                # This commit is the authority boundary: no removal is
                # attempted until the recovery evidence is durable.
                self.uow.commit()
            try:
                await remove_clean(job.job_id, project_id=job.project_id)
            except TypeError:
                await remove_clean(job.job_id)
            return

        # Compatibility for lightweight test doubles and older adapters; the
        # production manager uses the two-phase API.
        try:
            await self.worktree_manager.cleanup_worktree(job.job_id, project_id=job.project_id)
        except TypeError:
            await self.worktree_manager.cleanup_worktree(job.job_id)

    def queue_job(self, project_id: str, change_name: str, *, commit: bool = True) -> Job:
        project = self._require_project(project_id)
        change = self.uow.changes.get_by_name(project_id, change_name)
        if not change or change.last_readiness_status != ReadinessState.READY:
            raise ValueError(f"Change '{change_name}' for project '{project_id}' is not READY.")
        can_admit, admit_err = self.lifecycle_service.can_admit_change(project_id)
        if not can_admit:
            raise ValueError(f"Cannot admit change '{change_name}': {admit_err}")

        job = Job(
            project_id=project_id,
            change_name=change_name,
            implementer_role=project.implementer,
            current_executor=project.implementer,
        )
        self.uow.jobs.save(job)
        self._save_event(
            EventType.JOB_QUEUED,
            job,
            {"status": JobStatus.QUEUED.value, "implementer": project.implementer},
        )
        if commit:
            self.uow.commit()
        return job

    async def run_job(
        self,
        project_id: str,
        change_name: str,
        claim_context: RecoveryClaimContext | None = None,
    ) -> Job:
        from minime.domain.models import validate_claim_context_authoritative

        validate_claim_context_authoritative(self.uow, claim_context)
        job = self.queue_job(project_id, change_name)
        run_identity = self.uow.orchestration_runs.get_active_run(project_id, change_name)
        if run_identity and run_identity.active_job_id != job.job_id:
            run_identity.active_job_id = job.job_id
            if hasattr(self.uow.orchestration_runs, "update_active_job"):
                self.uow.orchestration_runs.update_active_job(run_identity.run_id, job.job_id)
            else:
                self.uow.orchestration_runs.save(run_identity)
            self.uow.commit()
        return await self.execute_queued_job(job.job_id, claim_context=claim_context)

    async def run_checks_only(
        self,
        job_id: str,
        candidate_generation: int = 1,
        claim_context: RecoveryClaimContext | None = None,
    ) -> Job:
        """Execute deterministic checks against a preserved, unmutated candidate worktree."""
        from minime.domain.exceptions import StaleClaimError
        from minime.domain.models import MetricFact, validate_claim_context_authoritative

        validate_claim_context_authoritative(self.uow, claim_context)

        job = self._require_job(job_id)
        project = self._require_project(job.project_id)
        if not job.candidate_sha:
            raise ValueError(f"Job '{job.job_id}' has no candidate_sha; checks cannot run.")

        # Resolve worktree path strictly via WorktreeManager and durable managed repository binding
        try:
            worktree_path = self.worktree_manager.worktree_path(
                job.job_id, project_id=job.project_id
            )
        except Exception as wt_err:
            raise ValueError(
                f"Failed to resolve worktree path for job '{job.job_id}': {wt_err}"
            ) from wt_err

        if not worktree_path.exists() or not worktree_path.is_dir():
            raise ValueError(
                f"Preserved candidate worktree does not exist or is not a directory: {worktree_path}"
            )

        # Validate git HEAD
        head_res = subprocess.run(
            ["git", "-C", str(worktree_path), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
        if head_res.returncode != 0 or head_res.stdout.strip() != job.candidate_sha:
            raise ValueError(
                f"Worktree HEAD '{head_res.stdout.strip()}' does not match job candidate_sha '{job.candidate_sha}'."
            )

        # Validate git clean
        status_res = subprocess.run(
            ["git", "-C", str(worktree_path), "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=False,
        )
        if status_res.returncode != 0 or status_res.stdout.strip():
            raise ValueError("Preserved worktree is not clean.")

        checks_started = utc_now()
        job = self._transition(job, JobStatus.CHECKS_RUNNING, claim_context=claim_context)
        try:
            check_run = await self._invoke_checks_runner(
                job.job_id,
                project.checks or [],
                worktree_path,
                candidate_sha=job.candidate_sha,
                candidate_generation=candidate_generation,
            )
        except Exception as runner_exc:
            # Runner or environment failure before CheckRunResult was produced.
            # Check if fence is still valid. If fence lost -> rollback with zero writes.
            try:
                validate_claim_context_authoritative(self.uow, claim_context, for_update=True)
            except Exception as fence_exc:
                self.uow.rollback()
                raise StaleClaimError(
                    f"Claim fence lost during checks runner failure for job '{job.job_id}': {fence_exc}"
                ) from fence_exc

            # Fence is valid: stage CHECKS_FAILED and diagnostic evidence without committing here.
            # The caller (drive_coordinator) transitions Run to NEEDS_HUMAN and commits both
            # Job and Run atomically in a single PostgreSQL transaction with zero two-phase commit gap.
            redacted_err = redact_secrets(str(runner_exc))
            job = self._transition(
                job,
                JobStatus.CHECKS_FAILED,
                error_message=redacted_err,
                claim_context=claim_context,
                auto_commit=False,
            )
            self.uow.evidence_diagnostics.save(
                EvidenceDiagnostic(
                    job_id=job.job_id,
                    stage_type="CHECKS",
                    check_name="checks_runner_pipeline",
                    diagnostic_status=EvidenceDiagnosticStatus.ENVIRONMENT_UNAVAILABLE,
                    environment_identity=str(worktree_path)[-128:],
                    candidate_sha=job.candidate_sha,
                    candidate_generation=candidate_generation,
                    reason=f"Runner execution failed: {type(runner_exc).__name__}: {redacted_err}",
                    evidence_reference={
                        "exception_type": type(runner_exc).__name__,
                        "error": redacted_err,
                        "checks_only_recovery": True,
                        "fault_source": "runner_setup_or_confinement",
                    },
                )
            )
            raise

        # POST-CHECKS FENCE REVALIDATION: verify claim is still valid before writing ANY results
        # Acquire short row lock on recovery claim to serialize evidence publication through commit
        try:
            validate_claim_context_authoritative(self.uow, claim_context, for_update=True)
        except Exception as fence_exc:
            self.uow.rollback()
            raise StaleClaimError(
                f"Claim fence lost during checks execution for job '{job.job_id}': {fence_exc}"
            ) from fence_exc

        # Persist results and diagnostics bound to candidate_sha and candidate_generation
        try:
            check_run_results = check_run.results
            for index, check_result in enumerate(check_run.results):
                if (
                    check_result.candidate_sha != (job.candidate_sha or "")
                    or check_result.candidate_generation != candidate_generation
                ):
                    check_result = check_result.model_copy(
                        update={
                            "candidate_sha": job.candidate_sha or "",
                            "candidate_generation": candidate_generation,
                        }
                    )
                check_run_results[index] = check_result
                self.uow.check_results.save(check_result)

            for diag in check_run.diagnostics:
                self.uow.evidence_diagnostics.save(diag)

            checks_duration = int((utc_now() - checks_started).total_seconds() * 1000)
            self.uow.metrics.save(
                MetricFact(
                    metric_name="checks_duration_ms",
                    project_id=job.project_id,
                    change_id=job.change_name,
                    duration_ms=checks_duration,
                    details={"job_id": job.job_id, "recovery": True},
                )
            )

            # Enforce single recovery batch completeness: all configured checks must be present,
            # exact name+command matches, no duplicates, and all exit_code == 0 in this batch
            configured_checks = project.checks or []
            configured_names = [c.get("name") for c in configured_checks if c.get("name")]
            executed_names = [r.check_name for r in check_run_results]

            if not configured_checks:
                err = "Project has no checks configured."
                job = self._transition(
                    job, JobStatus.CHECKS_FAILED, error_message=err, claim_context=claim_context
                )
                return self._require_job(job.job_id)

            if len(configured_names) != len(set(configured_names)):
                err = "Configuration error: duplicate check names configured in project."
                job = self._transition(
                    job, JobStatus.CHECKS_FAILED, error_message=err, claim_context=claim_context
                )
                return self._require_job(job.job_id)

            if len(executed_names) != len(set(executed_names)):
                err = "Execution error: duplicate check results in batch."
                job = self._transition(
                    job, JobStatus.CHECKS_FAILED, error_message=err, claim_context=claim_context
                )
                return self._require_job(job.job_id)

            missing_in_batch = set(configured_names) - set(executed_names)
            command_by_name = {
                c["name"]: c.get("command") for c in configured_checks if c.get("name")
            }
            commands_match = all(
                r.command == command_by_name.get(r.check_name) for r in check_run_results
            )

            all_passed = (
                check_run.passed
                and not missing_in_batch
                and commands_match
                and all(r.exit_code == 0 for r in check_run_results)
            )

            if not all_passed:
                err = f"Deterministic checks failed or incomplete (missing={sorted(list(missing_in_batch))}, commands_match={commands_match})."
                job = self._transition(
                    job, JobStatus.CHECKS_FAILED, error_message=err, claim_context=claim_context
                )
                return self._require_job(job.job_id)

            # Materialize CandidateManifest strictly within schema after successful checks
            manifest = self.uow.candidate_manifests.get_by_candidate_sha(
                job.job_id, job.candidate_sha
            )
            if not manifest or not manifest.manifest_hash or manifest.total_files_count <= 0:
                validate_claim_context_authoritative(self.uow, claim_context)
                manifest = self.manifest_service.generate_manifest(
                    worktree_path,
                    job.candidate_sha,
                    job.job_id,
                )
                validate_claim_context_authoritative(self.uow, claim_context)
                self.uow.candidate_manifests.save(manifest)
                self._save_event(
                    EventType.CANDIDATE_MANIFEST_CREATED,
                    job,
                    {
                        "manifest_hash": manifest.manifest_hash,
                        "total_files": manifest.total_files_count,
                        "source": "checks_only_recovery",
                    },
                )

            job = self._transition(job, JobStatus.CHECKS_PASSED, claim_context=claim_context)
            return self._require_job(job.job_id)
        except Exception:
            self.uow.rollback()
            raise

    async def execute_queued_job(
        self,
        job_id: str,
        candidate_generation: int = 1,
        claim_context: RecoveryClaimContext | None = None,
    ) -> Job:
        from minime.domain.models import validate_claim_context_authoritative

        validate_claim_context_authoritative(self.uow, claim_context)

        job = self._require_job(job_id)
        project = self._require_project(job.project_id)
        worktree_created = False
        readonly_view_created = False
        phase_started = utc_now()
        check_run_results = []
        implementer_fallback_used = False
        fallback_implementer_model: str | None = None

        try:
            # Continuation loop initialization & state reconstruction from durable PostgreSQL truth
            from minime.services.operator_executor_selection import effective_job_executor

            run_identity = self.uow.orchestration_runs.get_active_run(
                job.project_id, job.change_name
            )
            current_executor, pending_handoff, operator_reassigned = effective_job_executor(
                self.uow, run_identity, job
            )
            current_executor = current_executor or project.implementer
            job.current_executor = current_executor

            # Resume without APPLY only for a candidate with durable, exact
            # CODE_REVIEW work still in progress. A candidate SHA alone is not
            # sufficient: remediation after CHANGES_REQUIRED must return to APPLY.
            pending_code_review = (
                self.uow.reviews.get_by_job_stage(job.job_id, "CODE_REVIEW")
                if job.candidate_sha
                else None
            )
            resume_frozen_candidate = bool(
                run_identity
                and pending_code_review
                and pending_code_review.status == ReviewStatus.REVIEW_RUNNING
                and pending_code_review.review_stage == "CODE_REVIEW"
                and pending_code_review.project_id == job.project_id
                and pending_code_review.job_id == job.job_id
                and pending_code_review.change_name == job.change_name
                and pending_code_review.orchestration_run_id == run_identity.run_id
                and pending_code_review.candidate_generation == candidate_generation
                and pending_code_review.candidate_sha == job.candidate_sha
                and pending_code_review.base_sha == job.base_sha
                and bool(pending_code_review.manifest_id)
                and bool(pending_code_review.manifest_hash)
            )

            past_attempts = self.uow.job_attempts.list_by_job(job.job_id)
            past_attempts.sort(key=lambda a: a.attempt_number)

            # If resuming an episode that reached non-convergence / false human gate, transition to Antigravity recovery
            if (
                current_executor == PrimaryProvider.CODEX.value
                and not operator_reassigned
                and self.provider_policy._verify_codex_non_convergence(past_attempts)
                and (
                    job.reassignment_count >= 1
                    or any(
                        a.continuation_decision
                        in {
                            ContinuationDecision.REASSIGN_AGENT,
                            ContinuationDecision.NEEDS_HUMAN,
                        }
                        for a in past_attempts
                    )
                    or (
                        getattr(
                            self._get_provider_health(PrimaryProvider.CODEX.value), "status", None
                        )
                        != ProviderHealthStatus.AVAILABLE
                    )
                )
            ):
                ag_health = self._get_provider_health(PrimaryProvider.ANTIGRAVITY.value)
                if ag_health is not None and ag_health.status == ProviderHealthStatus.AVAILABLE:
                    orig_executor = current_executor
                    current_executor = PrimaryProvider.ANTIGRAVITY.value
                    job.current_executor = current_executor
                    self.uow.jobs.save(job)
                    self._save_event(
                        EventType.AGENT_REASSIGNED,
                        job,
                        {
                            "from_executor": orig_executor,
                            "to_executor": current_executor,
                            "reassignment_count": job.reassignment_count,
                        },
                    )
                    self._save_event(
                        EventType.PREMIUM_PROVIDER_ASSIGNED,
                        job,
                        {
                            "role": "implementer",
                            "provider": current_executor,
                            "premium_reason_code": PremiumProviderReasonCode.PREMIUM_RECOVERY_NON_CONVERGENCE.value,
                            "originating_provider": orig_executor,
                            "candidate_sha_before_recovery": job.candidate_sha or job.base_sha,
                            "recovery_provider": current_executor,
                            "attempt_id": f"att-{job.job_id}-{job.attempt_count + 1}",
                            "attempt_number": job.attempt_count + 1,
                        },
                    )
                    self._save_event(
                        EventType.PREMIUM_RECOVERY_ASSIGNED,
                        job,
                        {
                            "recovery_reason": PremiumProviderReasonCode.PREMIUM_RECOVERY_NON_CONVERGENCE.value,
                            "originating_provider": orig_executor,
                            "candidate_sha_before_recovery": job.candidate_sha or job.base_sha,
                            "recovery_provider": current_executor,
                            "attempt_id": f"att-{job.job_id}-{job.attempt_count + 1}",
                            "attempt_number": job.attempt_count + 1,
                        },
                    )
                    self.uow.commit()

            # APPLY capability and capacity are deliberately resolved only after
            # CONTRACT_REVIEW. A later stage's provider must not prevent the
            # earlier read-only contract gate from running.
            apply_profile: ResolvedStageProfile | None = None

            # Transition to RUNNING if not already in RUNNING status
            if job.status != JobStatus.RUNNING:
                job = self._transition(job, JobStatus.RUNNING)
            worktree = await self.worktree_manager.create_worktree(
                job.job_id,
                job.change_name,
                project.base_branch,
                project_id=project.project_id,
                run_id=getattr(job, "run_id", None),
                reuse_existing=True,
            )
            worktree_created = True
            if resume_frozen_candidate:
                if worktree.base_sha != job.base_sha:
                    return self._transition(
                        job,
                        JobStatus.NEEDS_HUMAN,
                        "Frozen candidate worktree base differs from durable Job base; candidate preserved.",
                    )
            else:
                job.base_sha = worktree.base_sha
                self.uow.jobs.save(job)
                if run_identity and run_identity.base_sha != worktree.base_sha:
                    run_identity.base_sha = worktree.base_sha
                    self.uow.orchestration_runs.save(run_identity)
            self._log(job.job_id, "system", f"Created worktree {worktree.path}")
            self.uow.commit()

            frozen_candidate = None
            frozen_manifest = None
            if resume_frozen_candidate:
                frozen_candidate, frozen_manifest, resume_error = (
                    self._verify_frozen_candidate_review_resume(
                        run_identity=run_identity,
                        job=job,
                        candidate_generation=candidate_generation,
                        worktree=worktree,
                    )
                )
                if resume_error:
                    return self._transition(
                        job,
                        JobStatus.NEEDS_HUMAN,
                        f"Frozen candidate review resume denied: {resume_error}",
                    )

            corrective_retries_for_current_executor = 0
            same_outcome_streak = 1
            same_blocker_fingerprint_streak = 0
            previous_outcome: ExecutionOutcome | None = None
            previous_blocker_fp: str | None = None
            corrective_prompt: str | None = None
            active_attempt: JobAttempt | None = None
            worktree_task_tracker = OpenSpecTaskTracker(worktree.path)

            # Production CLI execution requires the independent OpenSpec contract
            # review before any APPLY dispatch. Explicitly injected implementer
            # runners are isolated test/diagnostic doubles and are not production
            # admission evidence; the dedicated operational acceptance exercises
            # this path with the real service and intercepted HTTP boundary.
            if (
                self.implementer_runner is None
                and not past_attempts
                and job.attempt_count <= 1
                and not job.candidate_sha
            ):
                if not run_identity or run_identity.active_job_id != job.job_id:
                    return self._transition(
                        job,
                        JobStatus.NEEDS_HUMAN,
                        error_message="CONTRACT_REVIEW requires exact durable Run/Job identity.",
                    )
                contract_review = self.contract_review_service or ContractReviewService(
                    self.uow,
                    health_service=self.health_service,
                    budget_service=self.budget_service,
                    app_config=self.app_config,
                )
                result = await contract_review.review_before_apply(
                    project,
                    run_identity,
                    job,
                    worktree.path,
                    claim_context=claim_context,
                )
                if not result.accepted:
                    reason = (
                        result.reason or "DeepSeek CONTRACT_REVIEW did not accept the contract."
                    )
                    if result.waiting:
                        job = self.uow.jobs.set_waiting_capacity(job.job_id, "deepseek", reason)
                        self._save_event(
                            EventType.JOB_WAITING_CAPACITY,
                            job,
                            {
                                "waiting_provider": "deepseek",
                                "review_stage": "CONTRACT_REVIEW",
                                "reason": reason,
                            },
                        )
                        self.uow.commit()
                        return job
                    return self._transition(job, JobStatus.NEEDS_HUMAN, error_message=reason)

            if not resume_frozen_candidate:
                # A configured stage profile is authoritative for a new job.
                # Only a durable operator reassignment, handoff, prior attempt,
                # or already materialized non-default executor may override it.
                profile_override = bool(
                    operator_reassigned
                    or pending_handoff
                    or past_attempts
                    or current_executor != project.implementer
                )
                try:
                    apply_profile = self._resolve_stage_profile(
                        project,
                        OpenSpecStage.APPLY,
                        requested_provider=current_executor if profile_override else None,
                    )
                except StageProfileError as exc:
                    reason = f"Stage profile resolution rejected for APPLY: {exc}"
                    return self._transition(job, JobStatus.NEEDS_HUMAN, reason)

                if not profile_override and current_executor != apply_profile.provider:
                    previous_executor = current_executor
                    current_executor = apply_profile.provider
                    job.current_executor = current_executor
                    self.uow.jobs.save(job)
                    self._save_event(
                        EventType.STAGE_PROFILE_SELECTED,
                        job,
                        {
                            "stage": OpenSpecStage.APPLY.value,
                            "previous_executor": previous_executor,
                            "selected_provider": apply_profile.provider,
                            "model": apply_profile.model,
                            "effort": apply_profile.effort,
                            "workflow": apply_profile.workflow,
                            "selection_source": "configured_stage_profile",
                        },
                    )
                    self.uow.commit()

                # Validate exact account/model/effort and stage-bound capacity
                # only at the APPLY dispatch boundary, after contract review.
                if self.implementer_runner is None:
                    from minime.adapters.provider_adapter import get_provider_adapter

                    adapter = get_provider_adapter(apply_profile.provider, self.app_config)
                    supported, check_reason = await adapter.check_model_supported(
                        apply_profile.model, effort=apply_profile.effort
                    )
                    if not supported:
                        reason = f"Account capability check rejected for APPLY: {check_reason}"
                        return self._transition(job, JobStatus.NEEDS_HUMAN, reason)

                imp_health = await self._refresh_capacity_before_stage(
                    apply_profile.provider, model=apply_profile.model
                )
                is_primary_imp_available = (
                    imp_health is not None
                    and imp_health.status == ProviderHealthStatus.AVAILABLE
                    and self._stage_capacity_evidence_matches(
                        apply_profile.provider, apply_profile.model
                    )
                )
                if is_primary_imp_available and imp_health.model:
                    from minime.adapters.provider_adapter import AntigravityProviderAdapter

                    target_group = AntigravityProviderAdapter.map_model_to_quota_group(
                        apply_profile.model
                    )
                    observed_group = AntigravityProviderAdapter.map_model_to_quota_group(
                        imp_health.model
                    )
                    if (
                        imp_health.model.lower() != apply_profile.model.lower()
                        and target_group
                        and observed_group != target_group
                    ):
                        is_primary_imp_available = False

                if not is_primary_imp_available:
                    dual_exhausted = self._is_dual_primary_exhausted(project)
                    if not dual_exhausted:
                        status_desc = imp_health.status.value if imp_health else "UNKNOWN"
                        job = self.uow.jobs.set_waiting_capacity(
                            job.job_id,
                            apply_profile.provider,
                            f"Stage APPLY provider '{apply_profile.provider}' is {status_desc}",
                        )
                        self._save_event(
                            EventType.JOB_WAITING_CAPACITY,
                            job,
                            {
                                "waiting_provider": apply_profile.provider,
                                "status": status_desc,
                                "stage": "APPLY",
                                "model": apply_profile.model,
                            },
                        )
                        self.uow.commit()
                        return job

                    sched_status = self.lifecycle_service.get_scheduler_status(project.project_id)
                    policy, headroom = self.budget_service.get_headroom(project.project_id)
                    primary_health_records = self.health_service.list_all_health()
                    elig = self.eligibility_evaluator.evaluate_10_points(
                        scheduler_mode=sched_status.mode,
                        job=job,
                        role="implementer",
                        is_new_ready_change=False,
                        primary_health_records=primary_health_records,
                        project=project,
                        policy=policy,
                        headroom=headroom,
                        model_identity_valid=True,
                        candidate_integrity_valid=True,
                        pipeline_invariants_valid=True,
                    )
                    if not elig.eligible:
                        self._save_event(
                            EventType.FALLBACK_DENIED,
                            job,
                            {
                                "role": "implementer",
                                "reason": elig.denial_reason,
                                "reasons": elig.reasons,
                            },
                        )
                        job = self.uow.jobs.set_waiting_capacity(
                            job.job_id,
                            "openrouter",
                            f"OpenRouter fallback ineligible: {elig.denial_reason}",
                        )
                        self._save_event(
                            EventType.JOB_WAITING_CAPACITY,
                            job,
                            {"waiting_provider": "openrouter", "status": "fallback_ineligible"},
                        )
                        self.uow.commit()
                        return job
                    implementer_fallback_used = True
                    fallback_implementer_model = self.default_implementer_model

            if past_attempts:
                last_att = past_attempts[-1]
                cur_exec_attempts = []
                for a in reversed(past_attempts):
                    if a.executor_role == current_executor:
                        cur_exec_attempts.append(a)
                    else:
                        break
                cur_exec_attempts.reverse()

                corrective_retries_for_current_executor = sum(
                    1
                    for a in cur_exec_attempts
                    if a.continuation_decision == ContinuationDecision.CORRECT_AND_RETRY
                )
                same_outcome_streak = last_att.same_outcome_streak or 1
                same_blocker_fingerprint_streak = last_att.same_blocker_fingerprint_streak or 0
                previous_outcome = last_att.normalized_outcome
                if last_att.continuation_decision == ContinuationDecision.CORRECT_AND_RETRY:
                    corrective_prompt = last_att.corrective_prompt

                if not corrective_prompt and job.status == JobStatus.CHECKS_FAILED:
                    failing_checks = [
                        c
                        for c in self.uow.check_results.list_by_job(job.job_id)
                        if c.exit_code != 0
                    ]
                    if failing_checks:
                        lines = [
                            f"- [{c.check_name}] Command `{c.command}` failed with exit code {c.exit_code}:\n{c.output_snippet}"
                            for c in failing_checks
                        ]
                        corrective_prompt = (
                            "TARGETED REMEDIATION DIRECTIVE (Preserve Valid Working Code):\n"
                            "Valid incremental code in the worktree has been preserved. Do NOT reset or rewrite passing implementations.\n"
                            "Address exclusively the failing checks below:\n" + "\n".join(lines)
                        )

                latest_blockers = self.uow.blocker_claims.list_by_job(job.job_id)
                if latest_blockers:
                    previous_blocker_fp = latest_blockers[-1].blocker_fingerprint

                if last_att.completed_at is None:
                    job.attempt_count = last_att.attempt_number
                else:
                    job.attempt_count = max(job.attempt_count, len(past_attempts) + 1)

            # Main implementer continuation loop
            while not resume_frozen_candidate:
                past_attempts = self.uow.job_attempts.list_by_job(job.job_id)
                past_attempts.sort(key=lambda a: a.attempt_number)
                attempt_number = job.attempt_count
                attempt_id = f"att-{job.job_id}-{attempt_number}"

                attempt_runner: ImplementerRunnerInterface | None = None
                native_apply_workflow = None
                unverified_runner = False
                if not implementer_fallback_used and self.implementer_runner is None:
                    try:
                        apply_profile = self._resolve_stage_profile(
                            project,
                            OpenSpecStage.APPLY,
                            requested_provider=current_executor,
                        )
                        attempt_runner = runner_for_implementer(
                            apply_profile.provider,
                            config=self.app_config,
                            model=apply_profile.model,
                            effort=apply_profile.effort,
                        )
                        if isinstance(attempt_runner, CliImplementerRunner):
                            if (
                                attempt_runner.profile is None
                                or attempt_runner.profile.provider.lower()
                                not in {"codex", "antigravity", "agy"}
                            ):
                                raise NativeOpenSpecWorkflowUnavailable(
                                    f"R01 native APPLY evidence is verified for Codex and Antigravity, got: {attempt_runner.profile.provider if attempt_runner.profile else 'None'}."
                                )
                            preflight = preflight_cli_invocation(attempt_runner.profile)
                            if inspect.isawaitable(preflight):
                                preflight = await preflight
                            if not preflight.ok:
                                reason = f"Implementer CLI preflight failed: {preflight.reason}"
                                job = self._transition(job, JobStatus.NEEDS_HUMAN, reason)
                                return job
                            managed_binding = (
                                self.uow.project_managed_repository_bindings.get_by_project_id(
                                    job.project_id
                                )
                                if getattr(
                                    self.uow,
                                    "project_managed_repository_bindings",
                                    None,
                                )
                                else None
                            )
                            if (
                                not run_identity
                                or run_identity.project_id != job.project_id
                                or run_identity.change_name != job.change_name
                                or run_identity.active_job_id != job.job_id
                                or not managed_binding
                                or not managed_binding.is_valid
                                or not managed_binding.canonical_repository_identity
                                or not job.base_sha
                            ):
                                raise NativeOpenSpecWorkflowUnavailable(
                                    "Native APPLY requires an exact durable Run, Job, repository, and base binding."
                                )
                            apply_provider = attempt_runner.profile.provider.lower()
                            native_apply_workflow = resolve_native_openspec_apply(
                                worktree.path,
                                job.change_name,
                                provider=apply_provider,
                                project_id=job.project_id,
                                repository_identity=managed_binding.canonical_repository_identity,
                                run_id=run_identity.run_id,
                                job_id=job.job_id,
                                attempt_id=attempt_id,
                                generation=candidate_generation,
                                base_sha=job.base_sha,
                            )
                        else:
                            # A non-CLI injected/diagnostic boundary is not product evidence.
                            # It may exercise failure handling in tests, but can never
                            # authorize a candidate below.
                            unverified_runner = True
                    except StageProfileError as exc:
                        reason = f"Stage profile rejected for APPLY: {exc}"
                        job = self._transition(job, JobStatus.NEEDS_HUMAN, reason)
                        return job
                    except (NativeOpenSpecWorkflowUnavailable, ValueError, OSError) as exc:
                        reason = f"Native OpenSpec APPLY preflight blocked: {exc}"
                        job = self._transition(job, JobStatus.NEEDS_HUMAN, reason)
                        return job
                    except Exception as exc:
                        reason = (
                            "Validated APPLY profile could not construct runner; "
                            f"refusing unprofiled dispatch ({type(exc).__name__})."
                        )
                        job = self._transition(job, JobStatus.NEEDS_HUMAN, reason)
                        return job
                elif self.implementer_runner is not None:
                    # Explicitly injected runner dependencies are used by isolated unit/contract
                    # tests; they do not constitute product acceptance or native workflow evidence.
                    attempt_runner = self.implementer_runner

                # Consume pending handoff if available
                latest_handoff = pending_handoff
                handoff_prompt = ""
                if latest_handoff and not latest_handoff.is_consumed:
                    self.handoff_manager.consume_handoff(
                        latest_handoff.handoff_id, attempt_id, self.uow
                    )
                    handoff_prompt = self.handoff_manager.format_handoff_prompt(
                        latest_handoff, authoritative_worktree_path=worktree.path.resolve()
                    )

                workspace_path = worktree.path.resolve()
                workspace_context = format_candidate_workspace_context(workspace_path)
                if native_apply_workflow is not None:
                    prompt_context = (
                        f"{workspace_context}\n\n{native_apply_workflow.dispatch_instruction()}"
                    )
                else:
                    prompt_context = (
                        f"{workspace_context}\n\nApply OpenSpec change '{job.change_name}'."
                    )
                if handoff_prompt:
                    prompt_context = f"{prompt_context}\n\n{handoff_prompt}"
                if corrective_prompt:
                    prompt_context = f"{prompt_context}\n\n{corrective_prompt}"
                else:
                    remediation_sections: list[str] = []
                    latest_rev = self.uow.reviews.get_by_job_id(job.job_id)
                    if latest_rev:
                        findings = self.uow.review_findings.list_by_review(latest_rev.review_id)
                        if findings:
                            lines = [
                                f"- [{f.severity.value}] {f.location}: {f.violated_requirement} (Expected correction: {f.expected_correction})"
                                for f in findings
                            ]
                            remediation_sections.append(
                                "CORRECTIVE GUIDANCE (Review Findings to Address):\n"
                                + "\n".join(lines)
                            )
                    latest_aud = self.uow.audits.get_by_job_id(job.job_id)
                    if latest_aud and latest_aud.status == AuditStatus.AUDIT_BLOCKED:
                        aud_findings = self.uow.audit_findings.list_by_audit(latest_aud.audit_id)
                        if aud_findings:
                            lines = [
                                f"- [{f.severity.value}] {f.category} at {f.location or f.file or 'candidate'}: {f.message}"
                                for f in aud_findings
                            ]
                            remediation_sections.append(
                                "CORRECTIVE GUIDANCE (Audit Findings to Address):\n"
                                + "\n".join(lines)
                            )
                    if remediation_sections:
                        prompt_context = f"{prompt_context}\n\n" + "\n\n".join(remediation_sections)

                attempt_start_sha = await self.worktree_manager.current_sha(worktree.path)
                attempt_start_tasks = {
                    task.task_id
                    for task in worktree_task_tracker.parse_tasks(
                        project.openspec_path, job.change_name
                    )
                    if task.complete
                }
                attempt_start_fingerprint = await self._working_state_fingerprint(worktree.path)

                # Deterministic Task Classification & Multi-Factor Provider Policy Evaluation
                incomplete_tasks_start = worktree_task_tracker.incomplete_tasks(
                    project.openspec_path, job.change_name
                )
                task_class_result = self.task_classifier.classify(
                    stage="IMPLEMENTING",
                    attempt_number=attempt_number,
                    code_changed=(attempt_start_sha != job.base_sha) if job.base_sha else False,
                    incomplete_tasks=incomplete_tasks_start,
                )
                prov_policy_result = self.provider_policy.evaluate_selection(
                    task_class=task_class_result.task_class,
                    role="implementer",
                    project=project,
                    attempts=past_attempts,
                )
                premium_reason = (
                    prov_policy_result.premium_reason_code
                    if prov_policy_result.is_premium
                    else None
                )
                active_attempt = JobAttempt(
                    attempt_id=attempt_id,
                    job_id=job.job_id,
                    attempt_number=attempt_number,
                    executor_role=current_executor,
                    model_identity=fallback_implementer_model or current_executor,
                    start_sha=attempt_start_sha,
                    normalized_outcome=ExecutionOutcome.PREMATURE_STOP,
                    corrective_retries_count=corrective_retries_for_current_executor,
                    same_outcome_streak=same_outcome_streak,
                    same_blocker_fingerprint_streak=same_blocker_fingerprint_streak,
                    corrective_prompt=corrective_prompt,
                    task_class=task_class_result.task_class,
                    premium_reason_code=premium_reason,
                )
                self.uow.job_attempts.save(active_attempt)
                self.uow.commit()

                imp_outcome = None
                has_policy_violation = False
                has_environment_failure = False
                has_malformed_result = False
                has_preflight_failure = False
                has_insufficient_evidence = False
                blocker_claim = None
                runner_stdout: list[str] = []
                runner_stderr: list[str] = []
                exec_start = utc_now()

                if implementer_fallback_used and fallback_implementer_model:
                    # OpenRouter fallback implementer path
                    canonical_imp = self.independence_policy.registry.normalize(
                        fallback_implementer_model
                    )
                    canonical_name = (
                        canonical_imp.canonical_name
                        if canonical_imp
                        else fallback_implementer_model
                    )
                    snapshot = self.uow.pricing_snapshots.get_latest_verified_for_model(
                        fallback_implementer_model, canonical_name
                    )
                    if not snapshot:
                        self._save_event(
                            EventType.FALLBACK_DENIED,
                            job,
                            {
                                "role": "implementer",
                                "reason": "PRICING_SNAPSHOT_MISSING",
                                "model": fallback_implementer_model,
                            },
                        )
                        job = self.uow.jobs.set_waiting_capacity(
                            job.job_id,
                            "openrouter",
                            f"Fallback denied: No verified pricing snapshot for model '{fallback_implementer_model}' (PRICING_SNAPSHOT_MISSING)",
                        )
                        self._save_event(
                            EventType.JOB_WAITING_CAPACITY,
                            job,
                            {"waiting_provider": "openrouter", "status": "pricing_unverified"},
                        )
                        self.uow.commit()
                        return job

                    prompt_upper = max(len(prompt_context.split()) * 2, 2000)
                    max_output = 4096

                    reservation, denial_reason, headroom = self.budget_service.reserve_budget(
                        project_id=project.project_id,
                        job_id=job.job_id,
                        change_id=job.change_name,
                        role="implementer",
                        canonical_model_identity=canonical_name,
                        pricing_snapshot=snapshot,
                        prompt_token_upper_bound=prompt_upper,
                        max_output_tokens=max_output,
                    )
                    if not reservation:
                        self._save_event(
                            EventType.FALLBACK_DENIED,
                            job,
                            {"role": "implementer", "reason": denial_reason},
                        )
                        job = self.uow.jobs.set_waiting_capacity(
                            job.job_id,
                            "openrouter",
                            f"Fallback budget reservation denied: {denial_reason}",
                        )
                        self._save_event(
                            EventType.JOB_WAITING_CAPACITY,
                            job,
                            {"waiting_provider": "openrouter", "status": "budget_denied"},
                        )
                        self.uow.commit()
                        return job

                    self.uow.commit()

                    self._save_event(
                        EventType.FALLBACK_MODEL_SELECTED,
                        job,
                        {
                            "role": "implementer",
                            "model": fallback_implementer_model,
                            "canonical_identity": canonical_name,
                        },
                    )
                    self._save_event(
                        EventType.FALLBACK_INVOKED,
                        job,
                        {
                            "role": "implementer",
                            "model": fallback_implementer_model,
                            "reservation_id": reservation.reservation_id,
                        },
                    )
                    self.uow.commit()

                    api_key = self.openrouter_api_key or os.environ.get(
                        "OPENROUTER_API_KEY", "mock-openrouter-key"
                    )
                    openrouter_res, meta = await self.openrouter_adapter.execute(
                        OpenRouterRequest(
                            model=fallback_implementer_model,
                            canonical_model_identity=canonical_name,
                            prompt=prompt_context,
                            max_output_tokens=max_output,
                            authorized_max_output_tokens=max_output,
                            api_key=api_key,
                            pricing_snapshot=snapshot,
                            pricing_snapshot_id=snapshot.snapshot_id,
                            timeout_seconds=self.implementer_timeout_seconds,
                        )
                    )

                    if openrouter_res.result_class == ProviderResultClass.SUCCESS:
                        prompt_tok = meta.get("prompt_tokens") or (prompt_upper // 2)
                        comp_tok = meta.get("completion_tokens") or 500
                        tot_tok = meta.get("total_tokens") or (prompt_tok + comp_tok)
                        actual_cost = meta.get("actual_cost_usd")
                        if actual_cost is None:
                            actual_cost = (
                                Decimal(prompt_tok) * snapshot.prompt_price_per_token
                                + Decimal(comp_tok) * snapshot.output_price_per_token
                                + snapshot.additional_cost_per_request
                            )
                        # The provider call genuinely consumed money, but no material
                        # repository work was delivered (no editing harness). Record the
                        # actual cost truthfully while leaving the reservation unresolved.
                        self.budget_service.settle_unproductive_reservation(
                            reservation_id=reservation.reservation_id,
                            actual_cost_usd=actual_cost,
                            prompt_tokens=prompt_tok,
                            completion_tokens=comp_tok,
                            total_tokens=tot_tok,
                        )
                        self.uow.commit()
                        self._log(
                            job.job_id,
                            "stdout",
                            openrouter_res.summary or "OpenRouter implementer succeeded",
                        )
                        # Textual provider success is not repository implementation success.
                        # No repository-editing harness exists, so no candidate may be
                        # materialized; classify as insufficient evidence (NOT capacity
                        # exhaustion and NOT provider transport failure).
                        has_insufficient_evidence = True
                        imp_outcome = openrouter_res
                    else:
                        self.budget_service.mark_unresolved(reservation.reservation_id)
                        self.uow.commit()
                        imp_outcome = openrouter_res
                else:
                    # Primary implementer runner execution
                    runner = attempt_runner or self.implementer_runner
                    if runner is None:
                        job = self._transition(
                            job,
                            JobStatus.NEEDS_HUMAN,
                            "Validated APPLY profile did not produce a runner; refusing unprofiled dispatch.",
                        )
                        return job
                    result = await runner.run(
                        worktree.path,
                        prompt_context,
                        timeout_seconds=self.implementer_timeout_seconds,
                    )
                    runner_stdout = result.stdout
                    runner_stderr = result.stderr
                    if native_apply_workflow is not None:
                        workflow_evidence = dict(result.native_workflow_evidence or {})
                        workflow_evidence["dispatch_identity"] = {
                            "project_id": native_apply_workflow.project_id,
                            "repository_identity": native_apply_workflow.repository_identity,
                            "run_id": native_apply_workflow.run_id,
                            "job_id": native_apply_workflow.job_id,
                            "attempt_id": native_apply_workflow.attempt_id,
                            "generation": native_apply_workflow.generation,
                            "base_sha": native_apply_workflow.base_sha,
                            "stage": "APPLY",
                            "change_name": native_apply_workflow.change_name,
                        }
                        workflow_evidence["skill_source_unchanged"] = workflow_unchanged(
                            worktree.path, native_apply_workflow
                        )
                        workflow_evidence["workflow_observed"] = (
                            workflow_evidence.get("workflow_observed") is True
                            and workflow_evidence["skill_source_unchanged"] is True
                            and workflow_evidence.get("change_name") == job.change_name
                            and workflow_evidence.get("workflow_sha256")
                            == native_apply_workflow.workflow_sha256
                        )
                        active_attempt.error_details["native_openspec_apply"] = workflow_evidence
                        if workflow_evidence["workflow_observed"] is not True:
                            has_insufficient_evidence = True
                        self.uow.job_attempts.save(active_attempt)
                    elif unverified_runner:
                        has_insufficient_evidence = True
                    if getattr(result, "environment_error", False):
                        has_environment_failure = True
                    elif getattr(result, "preflight_error", None):
                        has_preflight_failure = True

                    for line in result.stdout:
                        self._log(job.job_id, "stdout", line)
                    for line in result.stderr:
                        self._log(job.job_id, "stderr", line)
                    self.uow.commit()

                    self.uow.metrics.save(
                        MetricFact(
                            metric_name="implementer_duration_ms",
                            project_id=job.project_id,
                            change_id=job.change_name,
                            duration_ms=result.duration_ms,
                            details={"job_id": job.job_id, "attempt": attempt_number},
                        )
                    )

                    imp_outcome = ProviderOutcomeParser.parse_runner_output(
                        provider=current_executor,
                        role="implementer",
                        model=None,
                        exit_code=result.exit_code,
                        timed_out=result.timed_out,
                        stdout_lines=result.stdout,
                        stderr_lines=result.stderr,
                        environment_failure=has_environment_failure,
                    )
                    if (
                        not has_preflight_failure
                        and imp_outcome.result_class != ProviderResultClass.ENVIRONMENT_UNAVAILABLE
                    ):
                        self.health_service.record_outcome(imp_outcome)
                    if result.timed_out or imp_outcome.result_class == ProviderResultClass.TIMEOUT:
                        self._save_event(
                            EventType.JOB_TIMEOUT,
                            job,
                            {
                                "attempt": attempt_number,
                                "executor": current_executor,
                                "duration_ms": result.duration_ms,
                            },
                        )

                    # Check for explicit blocker claim in stdout / stderr
                    full_output = "\n".join(runner_stdout + runner_stderr)
                    if "BLOCKER_CLAIM:" in full_output or "BLOCKER:" in full_output:
                        try:
                            # Parse structured blocker claim payload
                            b_type = (
                                "MISSING_FILE"
                                if "not exist" in full_output or "missing" in full_output.lower()
                                else "GENERAL_BLOCKER"
                            )
                            claim_payload = BlockerClaimPayload(
                                blocker_type=b_type,
                                rationale=full_output[-500:],
                                is_agent_solvable=True,
                            )
                            val_res = self.blocker_validation.validate(
                                claim_payload,
                                BlockerValidationContext(
                                    change_name=job.change_name,
                                    available_integration_points=[],
                                    required_files=[
                                        value
                                        for value in re.findall(
                                            r"`([^`]+\.(?:py|md|yaml|yml|json|sql))`",
                                            (
                                                worktree.path
                                                / project.openspec_path
                                                / "changes"
                                                / job.change_name
                                                / "tasks.md"
                                            ).read_text(encoding="utf-8")
                                            if (
                                                worktree.path
                                                / project.openspec_path
                                                / "changes"
                                                / job.change_name
                                                / "tasks.md"
                                            ).exists()
                                            else "",
                                        )
                                    ],
                                    candidate_tree_files=[
                                        str(path.relative_to(worktree.path))
                                        for path in worktree.path.rglob("*")
                                        if path.is_file() and ".git" not in path.parts
                                    ],
                                ),
                            )
                            blocker_claim = BlockerClaim(
                                job_id=job.job_id,
                                attempt_id=attempt_id,
                                blocker_type=claim_payload.blocker_type,
                                blocker_fingerprint=val_res.fingerprint,
                                rationale=claim_payload.rationale,
                                is_agent_solvable=val_res.is_agent_solvable,
                                validation_verdict=val_res.verdict,
                                validation_rationale=val_res.rationale,
                                available_integration_points=val_res.available_integration_points,
                            )
                            self.uow.blocker_claims.save(blocker_claim)
                            self.uow.commit()
                        except Exception as b_err:
                            logger.warning(f"Failed to process blocker claim: {b_err}")

                # Capture touched files
                current_sha = await self.worktree_manager.current_sha(worktree.path)
                post_provider_fingerprint = await self._working_state_fingerprint(worktree.path)
                post_tasks = worktree_task_tracker.parse_tasks(
                    project.openspec_path, job.change_name
                )
                incomplete_tasks = [t for t in post_tasks if not t.complete]
                if incomplete_tasks and all(is_verification_task(t) for t in incomplete_tasks):
                    try:
                        pre_check_run = await self.checks_runner.run(
                            job.job_id,
                            project.checks,
                            worktree.path,
                            candidate_sha=current_sha,
                        )
                        if pre_check_run.passed:
                            reconciled, rec_ids = (
                                worktree_task_tracker.reconcile_verification_tasks(
                                    project.openspec_path,
                                    job.change_name,
                                    check_evidence_passed=True,
                                    project_id=job.project_id,
                                    job_id=job.job_id,
                                    uow=self.uow,
                                )
                            )
                            if reconciled:
                                logger.info(
                                    f"Automatically reconciled verification tasks {rec_ids} for job '{job.job_id}' with passing check evidence."
                                )
                                post_tasks = worktree_task_tracker.parse_tasks(
                                    project.openspec_path, job.change_name
                                )
                    except Exception as err:
                        logger.warning(f"Failed pre-check task reconciliation: {err}")

                if not any(not task.complete for task in post_tasks):
                    current_sha = await self._finalize_candidate(
                        worktree.path, job.job_id, job.project_id, current_sha
                    )
                ver_res = self.outcome_governance.verify_completion(
                    worktree_path=worktree.path,
                    openspec_path=project.openspec_path,
                    change_name=job.change_name,
                    base_sha=job.base_sha or "",
                    candidate_sha=current_sha,
                )
                touched_files = ver_res.modified_files
                if ver_res.incomplete_tasks:
                    self._save_event(
                        EventType.INCOMPLETE_TASKS,
                        job,
                        {
                            "attempt": attempt_number,
                            "incomplete_count": len(ver_res.incomplete_tasks),
                            "incomplete_tasks": [t.task_id for t in ver_res.incomplete_tasks],
                        },
                    )

                # Record attempt authorship
                self.authorship_service.record_attempt_authorship(
                    job_id=job.job_id,
                    agent_role=current_executor,
                    model_identity=fallback_implementer_model or current_executor,
                    attempt_number=attempt_number,
                    files_touched=touched_files,
                    uow=self.uow,
                )

                # Classify outcome and progress
                outcome = self.outcome_governance.classify_outcome(
                    verification_result=ver_res,
                    provider_result=imp_outcome,
                    blocker_claim=blocker_claim,
                    has_policy_violation=has_policy_violation,
                    has_environment_failure=has_environment_failure,
                    has_malformed_result=has_malformed_result,
                    has_preflight_failure=has_preflight_failure,
                    has_insufficient_evidence=has_insufficient_evidence,
                )
                progress = self.outcome_governance.evaluate_progress(
                    ProgressSignals(
                        completed_task_delta=len(
                            {task.task_id for task in post_tasks if task.complete}
                            - attempt_start_tasks
                        ),
                        remaining_task_count=len(ver_res.incomplete_tasks),
                        candidate_file_delta=int(
                            post_provider_fingerprint != attempt_start_fingerprint
                            or current_sha != attempt_start_sha
                        ),
                    )
                )

                # Mandatory Rule D: In-process Lightweight Bookkeeping Reconciliation
                only_bookkeeping = bool(
                    ver_res.incomplete_tasks
                    and all(
                        is_verification_task(t)
                        or (
                            (not t.section or "implementation" not in t.section.lower())
                            and any(
                                re.search(rf"\b{kw}\b", t.text.lower())
                                for kw in [
                                    "sync",
                                    "spec",
                                    "document",
                                    "manifest",
                                    "evidence",
                                ]
                            )
                        )
                        for t in ver_res.incomplete_tasks
                    )
                )
                can_reconcile = self.reconciliation_service.can_reconcile(
                    code_changed=bool(
                        touched_files or (attempt_start_sha and current_sha != attempt_start_sha)
                    ),
                    checks_passed=(
                        outcome == ExecutionOutcome.COMPLETED or not ver_res.failing_checks
                    ),
                    incomplete_tasks_count=len(ver_res.incomplete_tasks),
                    only_bookkeeping_remaining=only_bookkeeping,
                )
                if can_reconcile and ver_res.incomplete_tasks:
                    rec_res = self.reconciliation_service.reconcile_bookkeeping(
                        worktree_path=worktree.path,
                        openspec_path=project.openspec_path,
                        change_name=job.change_name,
                        job=job,
                        project=project,
                        checks_passed=True,
                        changed_files=touched_files,
                    )
                    if rec_res.get("tasks_reconciled_count", 0) > 0:
                        post_tasks = worktree_task_tracker.parse_tasks(
                            project.openspec_path, job.change_name
                        )
                        if not any(not t.complete for t in post_tasks):
                            outcome = ExecutionOutcome.COMPLETED
                            current_sha = await self._finalize_candidate(
                                worktree.path, job.job_id, job.project_id, current_sha
                            )

                if outcome == ExecutionOutcome.COMPLETED:
                    current_sha = await self._finalize_candidate(
                        worktree.path, job.job_id, job.project_id, current_sha
                    )

                # Mandatory Rule C: Same-SHA Duplicate Detection
                is_same_sha = False
                if past_attempts:
                    prev = past_attempts[-1]
                    if (
                        prev.end_sha
                        and prev.end_sha == current_sha
                        and prev.normalized_outcome == outcome
                    ):
                        is_same_sha = True
                active_attempt.is_same_sha_duplicate = is_same_sha
                active_attempt.productivity_class = _classify_attempt_productivity(
                    outcome,
                    progress,
                    is_same_sha_duplicate=is_same_sha,
                )

                duration_ms = int((utc_now() - exec_start).total_seconds() * 1000)
                active_attempt.end_sha = current_sha
                active_attempt.normalized_outcome = outcome
                active_attempt.progress_classification = progress
                active_attempt.completed_at = utc_now()
                active_attempt.duration_ms = duration_ms
                self.uow.job_attempts.save(active_attempt)

                # Candidate truth invariant: a candidate SHA may only be assigned
                # when a candidate commit was actually materialized (COMPLETED).
                # The base/worktree HEAD is not a candidate SHA.
                if outcome == ExecutionOutcome.COMPLETED:
                    job.candidate_sha = current_sha
                job.latest_outcome = outcome
                job.latest_progress = progress
                self.uow.jobs.save(job)
                self.uow.commit()

                self._try_classify_post_materialization(job, worktree_path=worktree.path)

                if outcome == ExecutionOutcome.COMPLETED:
                    # Implementer phase succeeded with full task completion and clean git state
                    break

                # Evaluate alternative executor candidate and Rule K eligibility
                target_executor = (
                    project.reviewer
                    if current_executor == project.implementer
                    else project.implementer
                )
                alt_eligible = False
                target_model_id = None

                if target_executor and target_executor != current_executor:
                    is_pair_valid, _ = validate_complementary_pair(
                        target_executor, current_executor
                    )
                    if is_pair_valid:
                        # Check provider policy for target executor eligibility
                        # For routine tasks, Antigravity requires a verified premium reason code (e.g. non-convergence)
                        pol_eval = self.provider_policy.evaluate_selection(
                            task_class=task_class_result.task_class,
                            role="implementer",
                            project=project,
                            attempts=past_attempts + [active_attempt],
                        )
                        if pol_eval.selected_provider == target_executor:
                            alt_eligible = True
                            target_model_id = target_executor
                        elif target_executor == project.implementer:
                            alt_eligible = True
                            target_model_id = target_executor

                        # Anti-ping-pong: target executor must not have previously failed without intervening substantive progress
                        if past_attempts and alt_eligible:
                            prior_roles = [a.executor_role for a in past_attempts]
                            if target_executor in prior_roles:
                                last_idx = max(
                                    i for i, r in enumerate(prior_roles) if r == target_executor
                                )
                                attempts_since = past_attempts[last_idx:] + [active_attempt]
                                made_progress = any(
                                    a.productivity_class
                                    in {
                                        AttemptProductivityClass.SUBSTANTIVE_PROGRESS,
                                        AttemptProductivityClass.VALID_CORRECTIVE_WORK,
                                    }
                                    for a in attempts_since
                                )
                                if not made_progress:
                                    alt_eligible = False
                                    self._save_event(
                                        EventType.AGENT_PING_PONG_EXHAUSTED,
                                        job,
                                        {
                                            "from_executor": current_executor,
                                            "to_executor": target_executor,
                                            "reason": "Ping-pong reassignment suppressed: target executor previously failed on unchanged failure without intervening progress.",
                                        },
                                    )

                        # Model independence check if fallback implementer was used
                        if fallback_implementer_model and alt_eligible:
                            is_indep, _ = self.independence_policy.validate(
                                fallback_implementer_model, target_model_id
                            )
                            if not is_indep:
                                alt_eligible = False

                # Non-complete outcome: evaluate continuation decision
                ctx = ContinuationContext(
                    job_id=job.job_id,
                    attempt_number=attempt_number,
                    current_executor_role=current_executor,
                    current_model_identity=fallback_implementer_model or current_executor,
                    outcome=outcome,
                    progress=progress,
                    blocker_claim=blocker_claim,
                    corrective_retries_for_current_executor=corrective_retries_for_current_executor,
                    reassignment_count=job.reassignment_count,
                    same_outcome_streak=same_outcome_streak,
                    same_blocker_fingerprint_streak=same_blocker_fingerprint_streak,
                    incomplete_tasks=ver_res.incomplete_tasks,
                    failing_checks=ver_res.failing_checks,
                    error_message=ver_res.reason,
                    alternative_executor_eligible=alt_eligible,
                    target_executor_role=target_executor if alt_eligible else None,
                    target_model_identity=target_model_id if alt_eligible else None,
                    is_same_sha_duplicate=is_same_sha,
                    can_lightweight_reconcile=can_reconcile,
                )
                decision_res = self.continuation_engine.decide(ctx)
                job.continuation_decision = decision_res.decision
                active_attempt.continuation_decision = decision_res.decision
                self.uow.job_attempts.save(active_attempt)
                self.uow.jobs.save(job)
                self._save_event(
                    EventType.CONTINUATION_DECIDED,
                    job,
                    {
                        "decision": decision_res.decision.value,
                        "attempt": attempt_number,
                        "outcome": outcome.value,
                        "reason": decision_res.escalation_reason,
                    },
                )
                if decision_res.suppressed_same_sha:
                    self._save_event(
                        EventType.SAME_SHA_RETRY_SUPPRESSED,
                        job,
                        {
                            "attempt": attempt_number,
                            "candidate_sha": current_sha,
                            "reason": decision_res.escalation_reason,
                        },
                    )
                self.uow.commit()

                if decision_res.decision == ContinuationDecision.NEEDS_HUMAN:
                    job = self._transition(job, JobStatus.NEEDS_HUMAN)
                    job.escalation_reason = decision_res.escalation_reason
                    self.uow.jobs.save(job)
                    self._save_event(
                        EventType.JOB_NEEDS_HUMAN,
                        job,
                        {"reason": decision_res.escalation_reason},
                    )
                    self.uow.commit()
                    return job

                if decision_res.decision == ContinuationDecision.WAIT_EXTERNAL:
                    waiting_prov = current_executor
                    reset_at = imp_outcome.capacity_reset_at if imp_outcome else None
                    job = self.uow.jobs.set_waiting_capacity(
                        job.job_id,
                        waiting_prov,
                        decision_res.escalation_reason,
                        expected_reset_at=reset_at,
                    )
                    self._save_event(
                        EventType.JOB_WAITING_CAPACITY,
                        job,
                        {
                            "waiting_provider": waiting_prov,
                            "reason": decision_res.escalation_reason,
                            "expected_reset_at": reset_at.isoformat() if reset_at else None,
                        },
                    )
                    self.uow.commit()
                    return job

                if decision_res.decision == ContinuationDecision.CORRECT_AND_RETRY:
                    corrective_retries_for_current_executor += 1
                    job.attempt_count += 1
                    if outcome == previous_outcome:
                        same_outcome_streak += 1
                    else:
                        same_outcome_streak = 1
                    previous_outcome = outcome
                    if blocker_claim:
                        if blocker_claim.blocker_fingerprint == previous_blocker_fp:
                            same_blocker_fingerprint_streak += 1
                        else:
                            same_blocker_fingerprint_streak = 1
                        previous_blocker_fp = blocker_claim.blocker_fingerprint
                        if same_blocker_fingerprint_streak >= 3:
                            reason = "REPETITIVE_LOOP_DETECTED: consecutive identical blocker streak >= 3"
                            return self._transition(job, JobStatus.NEEDS_HUMAN, reason)
                    else:
                        same_blocker_fingerprint_streak = 0
                        previous_blocker_fp = None
                    corrective_prompt = decision_res.corrective_prompt
                    self.uow.jobs.save(job)
                    self.uow.commit()
                    continue

                if decision_res.decision == ContinuationDecision.REASSIGN_AGENT:
                    target_executor = decision_res.target_executor_role or (
                        project.reviewer
                        if current_executor == project.implementer
                        else project.implementer
                    )
                    all_tasks = worktree_task_tracker.parse_tasks(
                        project.openspec_path, job.change_name
                    )
                    completed_tasks = [t for t in all_tasks if t.complete]
                    remaining_tasks = [t for t in all_tasks if not t.complete]

                    handoff = self.handoff_manager.create_handoff(
                        job_id=job.job_id,
                        from_attempt_id=attempt_id,
                        from_executor=current_executor,
                        to_executor=target_executor,
                        worktree_path=str(worktree.path.resolve()),
                        base_sha=job.base_sha or "",
                        candidate_sha=current_sha,
                        completed_tasks=completed_tasks,
                        remaining_tasks=remaining_tasks,
                        blocker_claims=[blocker_claim] if blocker_claim else None,
                        authorship_history=self.uow.candidate_authorships.list_by_job(job.job_id),
                    )
                    self.uow.job_handoffs.save(handoff)

                    job.reassignment_count += 1
                    job.attempt_count += 1
                    current_executor = target_executor
                    job.current_executor = current_executor
                    corrective_retries_for_current_executor = 0
                    same_outcome_streak = 1
                    same_blocker_fingerprint_streak = 0
                    previous_outcome = None
                    previous_blocker_fp = None
                    corrective_prompt = None
                    self.uow.jobs.save(job)
                    self._save_event(
                        EventType.AGENT_REASSIGNED,
                        job,
                        {
                            "from_executor": active_attempt.executor_role,
                            "to_executor": target_executor,
                            "reassignment_count": job.reassignment_count,
                        },
                    )
                    # If target executor is a premium provider assignment (e.g. Antigravity recovery)
                    target_policy_eval = self.provider_policy.evaluate_selection(
                        task_class=task_class_result.task_class,
                        role="implementer",
                        project=project,
                        attempts=past_attempts + [active_attempt],
                    )
                    if (
                        target_policy_eval.selected_provider == target_executor
                        and target_policy_eval.is_premium
                        and target_policy_eval.premium_reason_code
                    ):
                        self._save_event(
                            EventType.PREMIUM_PROVIDER_ASSIGNED,
                            job,
                            {
                                "role": "implementer",
                                "provider": target_executor,
                                "premium_reason_code": target_policy_eval.premium_reason_code.value,
                                "originating_provider": active_attempt.executor_role,
                                "failure_classification": outcome.value,
                                "candidate_sha_before_recovery": current_sha,
                                "recovery_provider": target_executor,
                                "attempt_id": attempt_id,
                                "attempt_number": attempt_number,
                            },
                        )
                        self._save_event(
                            EventType.PREMIUM_RECOVERY_ASSIGNED,
                            job,
                            {
                                "recovery_reason": target_policy_eval.premium_reason_code.value,
                                "originating_provider": active_attempt.executor_role,
                                "failure_classification": outcome.value,
                                "candidate_sha_before_recovery": current_sha,
                                "recovery_provider": target_executor,
                                "attempt_id": attempt_id,
                                "attempt_number": attempt_number,
                            },
                        )
                    self.uow.commit()

                    # Check target executor capacity availability under canonical 005/006 lifecycle
                    target_health = self._get_provider_health(target_executor)
                    if (
                        target_health is not None
                        and target_health.status != ProviderHealthStatus.AVAILABLE
                    ):
                        dual_exhausted = self._is_dual_primary_exhausted(project)
                        if not dual_exhausted:
                            job = self.uow.jobs.set_waiting_capacity(
                                job.job_id,
                                target_executor,
                                f"Reassigned target provider '{target_executor}' is {target_health.status.value}",
                            )
                            self._save_event(
                                EventType.JOB_WAITING_CAPACITY,
                                job,
                                {
                                    "waiting_provider": target_executor,
                                    "status": target_health.status.value,
                                },
                            )
                            self.uow.commit()
                            return job

                        # Dual-primary exhaustion: Evaluate 10-point OpenRouter fallback eligibility for in-flight work
                        sched_status = self.lifecycle_service.get_scheduler_status(
                            project.project_id
                        )
                        policy, headroom = self.budget_service.get_headroom(project.project_id)
                        primary_health_records = self.health_service.list_all_health()

                        elig = self.eligibility_evaluator.evaluate_10_points(
                            scheduler_mode=sched_status.mode,
                            job=job,
                            role="implementer",
                            is_new_ready_change=False,
                            primary_health_records=primary_health_records,
                            project=project,
                            policy=policy,
                            headroom=headroom,
                            model_identity_valid=True,
                            candidate_integrity_valid=True,
                            pipeline_invariants_valid=True,
                        )

                        if not elig.eligible:
                            self._save_event(
                                EventType.FALLBACK_DENIED,
                                job,
                                {
                                    "role": "implementer",
                                    "reason": elig.denial_reason,
                                    "reasons": elig.reasons,
                                },
                            )
                            job = self.uow.jobs.set_waiting_capacity(
                                job.job_id,
                                "openrouter",
                                f"OpenRouter fallback ineligible: {elig.denial_reason}",
                            )
                            self._save_event(
                                EventType.JOB_WAITING_CAPACITY,
                                job,
                                {"waiting_provider": "openrouter", "status": "fallback_ineligible"},
                            )
                            self.uow.commit()
                            return job

                        implementer_fallback_used = True
                        fallback_implementer_model = self.default_implementer_model

                    continue

            # Candidate Manifest generation before checks and review. A resumed
            # candidate must retain its frozen manifest identity; regenerating
            # one would create a different durable checkpoint.
            try:
                if frozen_manifest is not None:
                    manifest = frozen_manifest
                else:
                    manifest = self.manifest_service.generate_manifest(
                        worktree.path,
                        job.candidate_sha or "",
                        job.job_id,
                        attempt_id=active_attempt.attempt_id if active_attempt else None,
                    )
            except CandidateArtifactRejectionError as err:
                logger.error("Candidate manifest rejected: %s", err)
                diag = EvidenceDiagnostic(
                    job_id=job.job_id,
                    attempt_id=active_attempt.attempt_id if active_attempt else None,
                    stage_type="CANDIDATE_FREEZE",
                    check_name="candidate_artifact_exclusion",
                    diagnostic_status=EvidenceDiagnosticStatus.FAIL,
                    environment_identity=str(worktree.path),
                    candidate_sha=job.candidate_sha or "",
                    reason=str(err),
                    evidence_reference={"violating_paths": err.violating_paths},
                )
                self.uow.evidence_diagnostics.save(diag)
                self._save_event(
                    EventType.COMPLETION_REJECTED,
                    job,
                    {"error": str(err), "violating_paths": err.violating_paths},
                )
                self.uow.commit()
                self._transition(job, JobStatus.FAILED)
                return self._require_job(job.job_id)

            if frozen_manifest is None:
                self.uow.candidate_manifests.save(manifest)
                self._save_event(
                    EventType.CANDIDATE_MANIFEST_CREATED,
                    job,
                    {
                        "manifest_hash": manifest.manifest_hash,
                        "total_files": manifest.total_files_count,
                    },
                )
                self.uow.commit()

            # Deterministic checks stage
            checks_started = utc_now()
            job = self._transition(job, JobStatus.CHECKS_RUNNING)
            check_run = await self._invoke_checks_runner(
                job.job_id,
                project.checks,
                worktree.path,
                candidate_sha=job.candidate_sha or "",
                candidate_generation=candidate_generation,
                attempt_id=active_attempt.attempt_id if active_attempt else None,
            )
            check_run_results = check_run.results
            for index, check_result in enumerate(check_run.results):
                if (
                    check_result.candidate_sha != (job.candidate_sha or "")
                    or check_result.candidate_generation != candidate_generation
                ):
                    check_result = check_result.model_copy(
                        update={
                            "candidate_sha": job.candidate_sha or "",
                            "candidate_generation": candidate_generation,
                        }
                    )
                check_run_results[index] = check_result
                self.uow.check_results.save(check_result)
            for diag in check_run.diagnostics:
                self.uow.evidence_diagnostics.save(diag)
            checks_duration = int((utc_now() - checks_started).total_seconds() * 1000)
            self.uow.metrics.save(
                MetricFact(
                    metric_name="checks_duration_ms",
                    project_id=job.project_id,
                    change_id=job.change_name,
                    duration_ms=checks_duration,
                    details={"job_id": job.job_id},
                )
            )
            self.uow.commit()

            if not check_run.passed:
                self._transition(job, JobStatus.CHECKS_FAILED)
                return self._require_job(job.job_id)

            job = self._transition(job, JobStatus.CHECKS_PASSED)

            if not run_identity:
                return self._transition(
                    job,
                    JobStatus.NEEDS_HUMAN,
                    "CODE_REVIEW_CANDIDATE_FREEZE_REQUIRES_ACTIVE_RUN; candidate preserved.",
                )
            from minime.services.orchestration_service import OrchestrationService

            candidate_authority = OrchestrationService(
                self.uow, project_root=self.project_root, pipeline=self
            )
            frozen_candidate = candidate_authority.freeze_candidate_for_review(run_identity, job)
            if not frozen_candidate:
                return self._transition(
                    job,
                    JobStatus.NEEDS_HUMAN,
                    "CODE_REVIEW_CANDIDATE_FREEZE_FAILED; candidate preserved.",
                )
            if frozen_candidate.generation != candidate_generation:
                # Candidate generations are finalized when the post-check
                # manifest is frozen. Bind the just-completed checks for this
                # exact SHA to that durable generation before review can read
                # them; older-generation check evidence is never rewritten.
                rebound_results = []
                for check_result in check_run_results:
                    if check_result.candidate_sha != frozen_candidate.candidate_sha:
                        return self._transition(
                            job,
                            JobStatus.NEEDS_HUMAN,
                            "CODE_REVIEW_CHECK_IDENTITY_MISMATCH; candidate is preserved.",
                        )
                    rebound = check_result.model_copy(
                        update={"candidate_generation": frozen_candidate.generation}
                    )
                    self.uow.check_results.save(rebound)
                    rebound_results.append(rebound)
                check_run_results = rebound_results
                self.uow.commit()
                candidate_generation = frozen_candidate.generation

            # The frozen candidate record is the authority for the manifest
            # identity. A freshly generated in-memory manifest may have the
            # same content hash but a different ID (for example after a retry
            # that observed the same candidate SHA). Review must use the exact
            # durable manifest referenced by the frozen candidate.
            authoritative_manifest = self.uow.candidate_manifests.get_by_id(
                frozen_candidate.manifest_id or ""
            )
            if (
                authoritative_manifest is None
                or authoritative_manifest.job_id != job.job_id
                or authoritative_manifest.candidate_sha != frozen_candidate.candidate_sha
                or authoritative_manifest.manifest_id != frozen_candidate.manifest_id
                or authoritative_manifest.manifest_hash != frozen_candidate.manifest_hash
                or authoritative_manifest.manifest_hash != manifest.manifest_hash
            ):
                return self._transition(
                    job,
                    JobStatus.NEEDS_HUMAN,
                    "CODE_REVIEW_CANDIDATE_MANIFEST_IDENTITY_MISMATCH; candidate is preserved.",
                )
            manifest = authoritative_manifest
            run_identity = self.uow.orchestration_runs.get_by_id(run_identity.run_id)

            # R01 final code review is an independent DeepSeek Direct stage; no
            # primary executor, auditor, or OpenRouter route may substitute.
            effective_reviewer = "deepseek"
            review_profile: ResolvedStageProfile | None = None
            try:
                review_profile = self._resolve_stage_profile(
                    project,
                    OpenSpecStage.REVIEW,
                    implementer_provider=current_executor,
                )
            except StageProfileError as exc:
                if "CODE_REVIEW_WAITING" in str(exc):
                    reason = f"Stage profile waiting for REVIEW: {exc}"
                    job = self.uow.jobs.set_waiting_capacity(job.job_id, effective_reviewer, reason)
                    self._save_event(
                        EventType.JOB_WAITING_CAPACITY,
                        job,
                        {
                            "waiting_provider": effective_reviewer,
                            "review_stage": "CODE_REVIEW",
                            "reason": reason,
                        },
                    )
                    self.uow.commit()
                    return job
                err_msg = f"Stage profile rejected for REVIEW: {exc}"
                self._save_event(
                    EventType.REVIEW_POLICY_VIOLATION,
                    job,
                    {
                        "error": err_msg,
                        "implementer": current_executor,
                        "reviewer": effective_reviewer,
                    },
                )
                job = self._transition(job, JobStatus.NEEDS_HUMAN, err_msg)
                return job

            if review_profile and self.reviewer_runner is None:
                from minime.adapters.provider_adapter import get_provider_adapter

                rev_adapter = get_provider_adapter(review_profile.provider, self.app_config)
                rev_supported, rev_reason = await rev_adapter.check_model_supported(
                    review_profile.model, effort=review_profile.effort
                )
                if not rev_supported:
                    err_msg = f"Account capability check rejected for REVIEW: {rev_reason}"
                    self._save_event(
                        EventType.REVIEW_POLICY_VIOLATION,
                        job,
                        {
                            "error": err_msg,
                            "implementer": current_executor,
                            "reviewer": effective_reviewer,
                        },
                    )
                    job = self._transition(job, JobStatus.NEEDS_HUMAN, err_msg)
                    return job

            # Checks may take minutes; admission-time reviewer capacity is not
            # reusable here. Refresh just before entering the review stage.
            if self.reviewer_runner is not None and self.code_review_service is None:
                is_primary_rev_available = True
            else:
                rev_health = await self._refresh_capacity_before_stage(
                    effective_reviewer, model=review_profile.model if review_profile else None
                )
                is_primary_rev_available = (
                    rev_health is not None
                    and rev_health.status == ProviderHealthStatus.AVAILABLE
                    and self._stage_capacity_evidence_matches(
                        effective_reviewer, review_profile.model if review_profile else None
                    )
                )
            reviewer_fallback_used = False
            selected_reviewer_model: str | None = None
            rev_identity = None

            if not is_primary_rev_available:
                status = rev_health.status.value if rev_health else "unknown"
                reason = (
                    "OpenRouter is executor rescue only and cannot review. "
                    f"Independent reviewer '{effective_reviewer}' is {status}; preserving candidate."
                )
                job = self.uow.jobs.set_waiting_capacity(job.job_id, effective_reviewer, reason)
                self._save_event(
                    EventType.JOB_WAITING_CAPACITY,
                    job,
                    {"waiting_provider": effective_reviewer, "status": status, "reason": reason},
                )
                self.uow.commit()
                return job

            if (
                self.reviewer_runner is None
                and self.code_review_service is None
                and (review_profile is None or review_profile.provider != "deepseek")
            ):
                reason = (
                    "R01 CODE_REVIEW requires DeepSeek Direct; reviewer substitution is forbidden."
                )
                self._save_event(
                    EventType.REVIEW_POLICY_VIOLATION,
                    job,
                    {
                        "error": reason,
                        "configured_provider": review_profile.provider if review_profile else None,
                    },
                )
                job = self._transition(job, JobStatus.NEEDS_HUMAN, reason)
                return job

            if review_profile.provider != "deepseek" and not reviewer_fallback_used:
                valid_pair, pair_err = validate_complementary_pair(
                    current_executor, effective_reviewer
                )
                if not valid_pair:
                    self._save_event(
                        EventType.REVIEW_POLICY_VIOLATION,
                        job,
                        {
                            "error": pair_err,
                            "implementer": current_executor,
                            "reviewer": effective_reviewer,
                        },
                    )
                    raise RuntimeError(pair_err or "Invalid complementary pair.")

            # Pre-review candidate integrity validation
            valid_pre, pre_err = validate_pre_review_integrity(
                worktree.path,
                job.candidate_sha,
                job.base_sha,
                base_branch=project.base_branch,
                repo_root_path=self.project_root,
                checks_passed=True,
            )
            if not valid_pre:
                self._save_event(
                    EventType.CANDIDATE_SHA_MISMATCH,
                    job,
                    {"error": pre_err},
                )
                self.uow.commit()
                raise RuntimeError(pre_err or "Pre-review candidate integrity failure.")

            # Observation-only symlink safety scan
            self.reviewer_view_manager.verify_candidate_tree(worktree.path)

            effective_reviewer_role = "deepseek"

            # Candidate verification and worktree preparation can outlive the
            # earlier reviewer snapshot. Obtain one final observation immediately
            # before materializing the review workspace / persisting REVIEW_RUNNING.
            if not reviewer_fallback_used and (
                self.reviewer_runner is None or self.code_review_service is not None
            ):
                rev_health = await self._refresh_capacity_before_stage(
                    effective_reviewer,
                    model=review_profile.model if review_profile else None,
                )
                if (
                    rev_health is None
                    or rev_health.status != ProviderHealthStatus.AVAILABLE
                    or not self._stage_capacity_evidence_matches(
                        effective_reviewer, review_profile.model if review_profile else None
                    )
                ):
                    job = self.uow.jobs.set_waiting_capacity(
                        job.job_id,
                        effective_reviewer,
                        f"Primary reviewer '{effective_reviewer}' is {rev_health.status.value}",
                    )
                    self._save_event(
                        EventType.JOB_WAITING_CAPACITY,
                        job,
                        {"waiting_provider": effective_reviewer, "status": rev_health.status.value},
                    )
                    self.uow.commit()
                    return job

            # Create dedicated reviewer EXECUTION_WORKTREE
            review_wt_info = await self.worktree_manager.create_review_worktree(
                job_id=job.job_id,
                change_name=job.change_name,
                candidate_sha=job.candidate_sha or "",
                reviewer_role=effective_reviewer_role,
                project_id=job.project_id,
            )
            readonly_view = review_wt_info.path
            readonly_view_created = True

            # Reviewer visibility verification against Candidate Manifest
            is_visible, blind_diag = self.manifest_service.verify_reviewer_visibility(
                manifest=manifest,
                reviewer_snapshot_path=readonly_view,
                job_id=job.job_id,
                candidate_sha=job.candidate_sha or "",
                attempt_id=active_attempt.attempt_id if active_attempt else None,
            )
            if not is_visible and blind_diag:
                self.uow.evidence_diagnostics.save(blind_diag)
                self._save_event(
                    EventType.EVIDENCE_DIAGNOSTIC_RECORDED,
                    job,
                    {"status": blind_diag.diagnostic_status.value, "reason": blind_diag.reason},
                )
                job = self._transition(job, JobStatus.NEEDS_HUMAN, error_message=blind_diag.reason)
                self.uow.commit()
                return job

            # Transition to REVIEW_RUNNING and persist Review record
            job = self._transition(job, JobStatus.REVIEW_RUNNING)

            diff = subprocess.run(
                ["git", "diff", "--name-only", f"{job.base_sha}..{job.candidate_sha}"],
                cwd=worktree.path,
                capture_output=True,
                text=True,
                check=False,
            )
            # A base..candidate diff is supporting evidence only. The frozen
            # manifest is authoritative for all surviving files, including
            # unchanged files that do not occur in the diff.
            candidate_files = {
                item["path"]
                for entries in (
                    manifest.tracked_files,
                    manifest.staged_files,
                    manifest.untracked_files,
                )
                for item in entries
                if item.get("path")
            }
            authorship_evidence = self.authorship_service.evaluate_reviewer_authorship(
                job_id=job.job_id,
                reviewer_role=effective_reviewer_role,
                surviving_files=candidate_files,
                candidate_sha=job.candidate_sha or "",
                candidate_generation=candidate_generation,
                uow=self.uow,
            )

            # Mandatory Rule G: Evaluate Reviewer Independence
            is_independent, ineligibility_reason = self.authorship_service.is_reviewer_eligible(
                job_id=job.job_id,
                reviewer_role=effective_reviewer_role,
                uow=self.uow,
            )
            if not is_independent:
                err_msg = (
                    f"REVIEWER_INDEPENDENCE_UNAVAILABLE: Reviewer '{effective_reviewer_role}' has material authorship "
                    f"in candidate '{job.candidate_sha}' and is strictly disqualified under reviewer independence policy."
                )
                self._save_event(
                    EventType.REVIEWER_INDEPENDENCE_BLOCKED,
                    job,
                    {
                        "candidate_sha": job.candidate_sha,
                        "disqualified_reviewer": effective_reviewer_role,
                        "reason": err_msg,
                    },
                )
                review = Review(
                    job_id=job.job_id,
                    project_id=job.project_id,
                    change_name=job.change_name,
                    reviewer_role=effective_reviewer_role,
                    candidate_sha=job.candidate_sha or "",
                    base_sha=job.base_sha or "",
                    status=ReviewStatus.REVIEW_FAILED,
                    is_mixed_authorship=True,
                    authorship_evidence=authorship_evidence,
                    error_message=err_msg,
                )
                self.uow.reviews.save(review)
                job = self._transition(job, JobStatus.NEEDS_HUMAN)
                job.escalation_reason = err_msg
                self.uow.jobs.save(job)
                self.uow.commit()
                return job

            review = Review(
                job_id=job.job_id,
                project_id=job.project_id,
                change_name=job.change_name,
                reviewer_role=effective_reviewer_role,
                reviewer_model=review_profile.model if review_profile else None,
                review_stage="CODE_REVIEW",
                orchestration_run_id=run_identity.run_id if run_identity else None,
                candidate_generation=candidate_generation,
                candidate_sha=job.candidate_sha or "",
                base_sha=job.base_sha or "",
                manifest_id=manifest.manifest_id,
                manifest_hash=manifest.manifest_hash,
                status=ReviewStatus.REVIEW_RUNNING,
                is_mixed_authorship=authorship_evidence["is_mixed_authorship"],
                authorship_evidence=authorship_evidence,
            )
            self.uow.reviews.save(review)
            self.uow.commit()

            review_prompt = build_reviewer_prompt(
                project=project,
                change_name=job.change_name,
                job_id=job.job_id,
                candidate_sha=job.candidate_sha or "",
                base_sha=job.base_sha or "",
                candidate_worktree_path=readonly_view,
                checks_results=check_run_results,
                authorship_evidence=authorship_evidence,
            )

            verdict_payload = None

            if self.code_review_service is not None or (
                review_profile
                and review_profile.provider == "deepseek"
                and self.reviewer_runner is None
            ):
                candidate = (
                    self.uow.orchestration_candidates.get_by_generation(
                        run_identity.run_id, candidate_generation
                    )
                    if run_identity
                    else None
                )
                if candidate is None:
                    return self._transition(
                        job,
                        JobStatus.NEEDS_HUMAN,
                        "CODE_REVIEW_CANDIDATE_RECORD_MISSING; candidate is preserved.",
                    )
                code_review_service = self.code_review_service or DeepSeekCodeReviewService(
                    self.uow,
                    health_service=self.health_service,
                    budget_service=self.budget_service,
                    app_config=self.app_config,
                    timeout_seconds=self.reviewer_timeout_seconds,
                )
                code_review = await code_review_service.review_candidate(
                    project=project,
                    run=run_identity,
                    job=job,
                    candidate=candidate,
                    manifest=manifest,
                    candidate_worktree=readonly_view,
                    authorship_evidence=authorship_evidence,
                )
                if not code_review.accepted or not code_review.verdict:
                    if code_review.waiting:
                        reason = code_review.reason or "DEEPSEEK_CODE_REVIEW_WAITING"
                        job = self.uow.jobs.set_waiting_capacity(job.job_id, "deepseek", reason)
                        self._save_event(
                            EventType.JOB_WAITING_CAPACITY,
                            job,
                            {"waiting_provider": "deepseek", "stage": "REVIEW", "reason": reason},
                        )
                        self.uow.commit()
                        return job
                    reason = code_review.reason or "DeepSeek code review failed closed."
                    return self._transition(job, JobStatus.NEEDS_HUMAN, reason)
                review = self.uow.reviews.get_by_id(code_review.review_id) or review
                verdict_payload = code_review.verdict
            elif reviewer_fallback_used and selected_reviewer_model and rev_identity:
                # OpenRouter fallback reviewer execution
                snapshot = self.uow.pricing_snapshots.get_latest_verified_for_model(
                    selected_reviewer_model, rev_identity.canonical_name
                )
                if not snapshot:
                    self._save_event(
                        EventType.FALLBACK_DENIED,
                        job,
                        {
                            "role": "reviewer",
                            "reason": "PRICING_SNAPSHOT_MISSING",
                            "model": selected_reviewer_model,
                        },
                    )
                    self.uow.reviews.transition(
                        review.review_id,
                        ReviewStatus.REVIEW_FAILED.value,
                        error_message=f"Fallback reviewer denied: No verified pricing snapshot for model '{selected_reviewer_model}' (PRICING_SNAPSHOT_MISSING)",
                    )
                    job = self.uow.jobs.set_waiting_capacity(
                        job.job_id,
                        "openrouter",
                        f"Fallback reviewer denied: No verified pricing snapshot for model '{selected_reviewer_model}' (PRICING_SNAPSHOT_MISSING)",
                    )
                    self._save_event(
                        EventType.JOB_WAITING_CAPACITY,
                        job,
                        {"waiting_provider": "openrouter", "status": "pricing_unverified"},
                    )
                    self.uow.commit()
                    return job

                prompt_upper = max(len(review_prompt.split()) * 2, 2000)
                max_output = 4096

                # Atomic reservation on PostgreSQL policy before HTTP dispatch
                reservation, denial_reason, headroom = self.budget_service.reserve_budget(
                    project_id=project.project_id,
                    job_id=job.job_id,
                    change_id=job.change_name,
                    role="reviewer",
                    canonical_model_identity=rev_identity.canonical_name,
                    pricing_snapshot=snapshot,
                    prompt_token_upper_bound=prompt_upper,
                    max_output_tokens=max_output,
                )
                if not reservation:
                    self._save_event(
                        EventType.FALLBACK_DENIED,
                        job,
                        {"role": "reviewer", "reason": denial_reason},
                    )
                    self.uow.reviews.transition(
                        review.review_id,
                        ReviewStatus.REVIEW_FAILED.value,
                        error_message=f"Budget reservation denied: {denial_reason}",
                    )
                    job = self.uow.jobs.set_waiting_capacity(
                        job.job_id,
                        "openrouter",
                        f"Fallback budget reservation denied: {denial_reason}",
                    )
                    self._save_event(
                        EventType.JOB_WAITING_CAPACITY,
                        job,
                        {"waiting_provider": "openrouter", "status": "budget_denied"},
                    )
                    self.uow.commit()
                    return job

                # COMMIT reservation before external HTTP call
                self.uow.commit()

                self._save_event(
                    EventType.FALLBACK_MODEL_SELECTED,
                    job,
                    {
                        "role": "reviewer",
                        "model": selected_reviewer_model,
                        "canonical_identity": rev_identity.canonical_name,
                    },
                )
                self._save_event(
                    EventType.FALLBACK_INVOKED,
                    job,
                    {
                        "role": "reviewer",
                        "model": selected_reviewer_model,
                        "reservation_id": reservation.reservation_id,
                    },
                )
                self.uow.commit()

                api_key = self.openrouter_api_key or os.environ.get(
                    "OPENROUTER_API_KEY", "mock-openrouter-key"
                )
                openrouter_res, meta = await self.openrouter_adapter.execute(
                    OpenRouterRequest(
                        model=selected_reviewer_model,
                        canonical_model_identity=rev_identity.canonical_name,
                        prompt=review_prompt,
                        max_output_tokens=max_output,
                        authorized_max_output_tokens=max_output,
                        api_key=api_key,
                        pricing_snapshot=snapshot,
                        pricing_snapshot_id=snapshot.snapshot_id,
                        timeout_seconds=self.reviewer_timeout_seconds,
                    )
                )

                if openrouter_res.result_class == ProviderResultClass.SUCCESS:
                    prompt_tok = meta.get("prompt_tokens") or (prompt_upper // 2)
                    comp_tok = meta.get("completion_tokens") or 500
                    tot_tok = meta.get("total_tokens") or (prompt_tok + comp_tok)
                    actual_cost = meta.get("actual_cost_usd")
                    if actual_cost is None:
                        actual_cost = (
                            Decimal(prompt_tok) * snapshot.prompt_price_per_token
                            + Decimal(comp_tok) * snapshot.output_price_per_token
                            + snapshot.additional_cost_per_request
                        )
                    self.budget_service.settle_reservation(
                        reservation_id=reservation.reservation_id,
                        actual_cost_usd=actual_cost,
                        prompt_tokens=prompt_tok,
                        completion_tokens=comp_tok,
                        total_tokens=tot_tok,
                    )
                    self.uow.commit()

                    raw_lines = (
                        openrouter_res.raw_output.splitlines() if openrouter_res.raw_output else []
                    )
                    for line in raw_lines:
                        self._log(job.job_id, "stdout", line)
                    try:
                        verdict_payload = parse_review_verdict(raw_lines)
                    except Exception as e:
                        err_msg = f"Malformed OpenRouter review output: {e}"
                        self.uow.reviews.transition(
                            review.review_id,
                            ReviewStatus.REVIEW_FAILED.value,
                            error_message=err_msg,
                        )
                        self._save_event(EventType.MALFORMED_REVIEW_OUTPUT, job, {"error": err_msg})
                        self.uow.commit()
                        raise RuntimeError(err_msg) from e
                else:
                    # Mark unresolved and pause job
                    self.budget_service.mark_unresolved(reservation.reservation_id)
                    self.uow.reviews.transition(
                        review.review_id,
                        ReviewStatus.REVIEW_FAILED.value,
                        error_message=openrouter_res.summary,
                    )
                    self.health_service.record_outcome(openrouter_res)
                    self._save_event(
                        EventType.JOB_WAITING_CAPACITY,
                        job,
                        {"waiting_provider": "openrouter", "error": openrouter_res.summary},
                    )
                    self.uow.commit()
                    job = self.uow.jobs.set_waiting_capacity(
                        job.job_id,
                        "openrouter",
                        openrouter_res.summary or "OpenRouter reviewer fallback failed",
                    )
                    return job
            else:
                # Primary reviewer runner execution
                if self.reviewer_runner is not None:
                    reviewer = self.reviewer_runner
                elif review_profile and review_profile.cli_invocation is not None:
                    reviewer = CliReviewerRunner(review_profile.cli_invocation)
                else:
                    try:
                        if review_profile is None:
                            raise StageProfileError("REVIEW profile is unavailable")
                        reviewer = runner_for_reviewer(
                            effective_reviewer,
                            config=self.app_config,
                            model=review_profile.model,
                            effort=review_profile.effort,
                        )
                    except (TypeError, StageProfileError) as exc:
                        self.uow.reviews.transition(
                            review.review_id,
                            ReviewStatus.REVIEW_FAILED.value,
                            error_message=f"Validated REVIEW profile could not construct runner: {exc}",
                        )
                        self.uow.commit()
                        return self._transition(
                            job,
                            JobStatus.NEEDS_HUMAN,
                            "Validated REVIEW profile could not construct runner; refusing unprofiled dispatch.",
                        )
                review_result = await reviewer.run(
                    readonly_view,
                    review_prompt,
                    timeout_seconds=self.reviewer_timeout_seconds,
                )

                # Reviewer preflight / CLI configuration incompatibility: no provider
                # execution was attempted, provider health must not degrade, and the
                # job must escalate (not consume corrective-retry budget).
                preflight_err = getattr(review_result, "preflight_error", None)
                if preflight_err:
                    self.uow.reviews.transition(
                        review.review_id,
                        ReviewStatus.REVIEW_FAILED.value,
                        error_message=f"Reviewer CLI preflight failed: {preflight_err}",
                    )
                    self.uow.commit()
                    return self._transition(
                        job,
                        JobStatus.NEEDS_HUMAN,
                        f"Reviewer CLI preflight failed: {preflight_err}",
                    )

                for line in review_result.stdout:
                    self._log(job.job_id, "stdout", line)
                for line in review_result.stderr:
                    self._log(job.job_id, "stderr", line)
                self.uow.commit()

                self.uow.metrics.save(
                    MetricFact(
                        metric_name="review_duration_ms",
                        project_id=job.project_id,
                        change_id=job.change_name,
                        duration_ms=review_result.duration_ms,
                        details={"job_id": job.job_id, "reviewer": effective_reviewer},
                    )
                )

                domain_verdict_valid = False
                try:
                    verdict_payload = parse_review_verdict(review_result.stdout)
                    domain_verdict_valid = True
                except Exception:
                    pass

                rev_outcome = ProviderOutcomeParser.parse_runner_output(
                    provider=effective_reviewer,
                    role="reviewer",
                    model=None,
                    exit_code=review_result.exit_code,
                    timed_out=review_result.timed_out,
                    stdout_lines=review_result.stdout,
                    stderr_lines=review_result.stderr,
                    domain_verdict_valid=domain_verdict_valid,
                    environment_failure=getattr(review_result, "environment_error", False),
                )
                if rev_outcome.result_class != ProviderResultClass.ENVIRONMENT_UNAVAILABLE:
                    self.health_service.record_outcome(rev_outcome)

                if rev_outcome.result_class == ProviderResultClass.ENVIRONMENT_UNAVAILABLE:
                    reason = (
                        "ENVIRONMENT_UNAVAILABLE: confined reviewer runtime initialization failed; "
                        "waiting for local environment correction without provider penalty."
                    )
                    self.uow.reviews.transition(
                        review.review_id,
                        ReviewStatus.REVIEW_FAILED.value,
                        error_message=reason,
                    )
                    job = self.uow.jobs.set_waiting_capacity(job.job_id, effective_reviewer, reason)
                    self.uow.commit()
                    return job

                if rev_outcome.result_class in {
                    ProviderResultClass.QUOTA_LIMIT,
                    ProviderResultClass.RATE_LIMIT,
                }:
                    job = self.uow.jobs.set_waiting_capacity(
                        job.job_id,
                        effective_reviewer,
                        rev_outcome.summary or f"Capacity exhausted on {effective_reviewer}",
                        rev_outcome.capacity_reset_at,
                    )
                    self._save_event(
                        EventType.JOB_WAITING_CAPACITY,
                        job,
                        {
                            "waiting_provider": effective_reviewer,
                            "reset_at": rev_outcome.capacity_reset_at.isoformat()
                            if rev_outcome.capacity_reset_at
                            else None,
                        },
                    )
                    self.uow.commit()
                    return job

                if review_result.timed_out:
                    self.uow.reviews.transition(
                        review.review_id,
                        ReviewStatus.REVIEW_TIMED_OUT.value,
                        error_message=f"Reviewer execution timed out after {self.reviewer_timeout_seconds} seconds.",
                    )
                    self._save_event(
                        EventType.REVIEW_TIMEOUT,
                        job,
                        {"timeout_seconds": self.reviewer_timeout_seconds},
                    )
                    self.uow.commit()
                    raise RuntimeError("Reviewer execution timed out.")

                if review_result.exit_code != 0:
                    err_msg = f"Reviewer process exited with code {review_result.exit_code}."
                    self.uow.reviews.transition(
                        review.review_id,
                        ReviewStatus.REVIEW_FAILED.value,
                        error_message=err_msg,
                    )
                    self.uow.commit()
                    raise RuntimeError(err_msg)

            # Post-review non-mutation integrity validation on original worktree
            valid_post, post_err = validate_post_review_integrity(
                worktree.path, job.candidate_sha or ""
            )
            if not valid_post:
                self.uow.reviews.transition(
                    review.review_id,
                    ReviewStatus.REVIEW_FAILED.value,
                    error_message=post_err,
                )
                self._save_event(
                    EventType.UNAUTHORIZED_REVIEWER_MUTATION,
                    job,
                    {"error": post_err},
                )
                self.uow.commit()
                raise RuntimeError(post_err or "Post-review mutation detected.")

            # Parse structured review verdict strictly if not already parsed
            if not verdict_payload:
                try:
                    verdict_payload = parse_review_verdict(review_result.stdout)
                except Exception as parse_exc:
                    parse_err = f"Malformed review output: {parse_exc}"
                    self.uow.reviews.transition(
                        review.review_id,
                        ReviewStatus.REVIEW_FAILED.value,
                        error_message=parse_err,
                    )
                    self._save_event(
                        EventType.MALFORMED_REVIEW_OUTPUT,
                        job,
                        {"error": parse_err},
                    )
                    self.uow.commit()
                    raise RuntimeError(parse_err) from parse_exc

            # Apply review verdict transition
            if verdict_payload.findings:
                tree_files = {
                    item["path"]
                    for entries in (
                        manifest.tracked_files,
                        manifest.staged_files,
                        manifest.untracked_files,
                    )
                    for item in entries
                    if item.get("path")
                }
                tasks_path = (
                    worktree.path / project.openspec_path / "changes" / job.change_name / "tasks.md"
                )
                task_text = tasks_path.read_text(encoding="utf-8") if tasks_path.exists() else ""
                required_files = re.findall(r"`([^`]+\.(?:py|md|yaml|yml|json|sql))`", task_text)
                blocker_context = BlockerValidationContext(
                    change_name=job.change_name,
                    required_files=required_files,
                    candidate_tree_files=sorted(tree_files),
                    manifest_files=sorted(tree_files),
                    base_diff_files=[
                        line.strip() for line in diff.stdout.splitlines() if line.strip()
                    ],
                )
                normalized_findings = []
                for item in verdict_payload.findings:
                    is_missing = (
                        "missing"
                        in (f"{item.violated_requirement} {item.expected_correction}").lower()
                    )
                    if item.severity.value == "BLOCKER" and is_missing:
                        validation = self.blocker_validation.validate_missing_file(
                            item.location, blocker_context
                        )
                        if validation.verdict == BlockerValidationVerdict.FALSE_BLOCKER:
                            item = item.model_copy(update={"severity": FindingSeverity.MINOR})
                    normalized_findings.append(item)
                verdict_payload = verdict_payload.model_copy(
                    update={"findings": normalized_findings}
                )

            if verdict_payload.verdict == ReviewVerdict.READY_TO_MERGE:
                self.uow.reviews.transition(
                    review.review_id,
                    ReviewStatus.REVIEW_COMPLETED.value,
                    verdict=ReviewVerdict.READY_TO_MERGE.value,
                    summary=verdict_payload.summary,
                )
                self._save_event(
                    EventType.CODE_REVIEW_COMPLETED,
                    job,
                    {
                        "review_id": review.review_id,
                        "review_stage": "CODE_REVIEW",
                        "provider": review.provider,
                        "model": review.reviewer_model,
                        "account_fingerprint": review.account_fingerprint,
                        "authorization_id": review.budget_authorization_id,
                        "reservation_id": review.budget_reservation_id,
                        "candidate_sha": review.candidate_sha,
                        "base_sha": review.base_sha,
                        "generation": review.candidate_generation,
                        "manifest_id": review.manifest_id,
                        "manifest_hash": review.manifest_hash,
                        "verdict": ReviewVerdict.READY_TO_MERGE.value,
                    },
                )
                self.uow.commit()
                if project.independent_audit_required:
                    job = await self._run_audit_stage(
                        job=job,
                        project=project,
                        worktree_path=worktree.path,
                        check_run_results=check_run_results,
                        review_id=review.review_id,
                    )
                else:
                    job = self._transition(job, JobStatus.READY_TO_MERGE)
            elif verdict_payload.verdict == ReviewVerdict.CHANGES_REQUIRED:
                self.uow.reviews.transition(
                    review.review_id,
                    ReviewStatus.REVIEW_COMPLETED.value,
                    verdict=ReviewVerdict.CHANGES_REQUIRED.value,
                    summary=verdict_payload.summary,
                )
                self._save_event(
                    EventType.CODE_REVIEW_COMPLETED,
                    job,
                    {
                        "review_id": review.review_id,
                        "review_stage": "CODE_REVIEW",
                        "provider": review.provider,
                        "model": review.reviewer_model,
                        "account_fingerprint": review.account_fingerprint,
                        "authorization_id": review.budget_authorization_id,
                        "reservation_id": review.budget_reservation_id,
                        "candidate_sha": review.candidate_sha,
                        "base_sha": review.base_sha,
                        "generation": review.candidate_generation,
                        "manifest_id": review.manifest_id,
                        "manifest_hash": review.manifest_hash,
                        "verdict": ReviewVerdict.CHANGES_REQUIRED.value,
                    },
                )
                if not self.uow.review_findings.list_by_review(review.review_id):
                    for item in verdict_payload.findings:
                        finding = ReviewFinding(
                            review_id=review.review_id,
                            severity=item.severity,
                            location=item.location,
                            violated_requirement=item.violated_requirement,
                            expected_correction=item.expected_correction,
                        )
                        self.uow.review_findings.save(finding)
                self.uow.commit()
                self._transition(job, JobStatus.CHANGES_REQUIRED)

        except Exception as exc:
            logger.exception(f"Exception in execute_queued_job: {exc}")
            latest = self._require_job(job.job_id)
            if latest.status not in {
                JobStatus.CHECKS_FAILED,
                JobStatus.READY_TO_MERGE,
                JobStatus.AUDIT_BLOCKED,
                JobStatus.CHANGES_REQUIRED,
                JobStatus.WAITING_CAPACITY,
                JobStatus.RECOVERY_BLOCKED,
                JobStatus.NEEDS_HUMAN,
                JobStatus.FAILED,
                JobStatus.CANCELLED,
            }:
                self._transition(latest, JobStatus.FAILED, str(exc))
        finally:
            if readonly_view_created and "readonly_view" in locals() and readonly_view:
                try:
                    await self.worktree_manager.remove_review_worktree(
                        readonly_view, job.job_id, job.project_id
                    )
                except Exception as clean_err:
                    logger.warning(
                        f"Failed to clean up review worktree at '{readonly_view}': {clean_err}"
                    )

            if worktree_created:
                try:
                    await self._preserve_and_cleanup_worktree(job, worktree)
                except Exception as cleanup_error:
                    redacted_error = redact_secrets(str(cleanup_error))
                    logger.error(
                        "Managed candidate preservation/cleanup failed: %s", redacted_error
                    )
                    latest = self._require_job(job.job_id)
                    if latest.status != JobStatus.RECOVERY_BLOCKED:
                        latest = self._transition(
                            latest, JobStatus.RECOVERY_BLOCKED, redacted_error
                        )
                    latest.recovery_blocked_reason = redacted_error
                    latest.error_message = redacted_error
                    latest.escalation_reason = redacted_error
                    self.uow.jobs.save(latest)
                    self._save_event(
                        EventType.RECOVERY_BLOCKED,
                        latest,
                        {"error": redacted_error, "worktree_path": str(worktree.path)},
                    )
                    self.uow.commit()
            latest = self._require_job(job.job_id)
            if latest.status in {
                JobStatus.READY_TO_MERGE,
                JobStatus.AUDIT_BLOCKED,
                JobStatus.CHANGES_REQUIRED,
                JobStatus.CHECKS_FAILED,
                JobStatus.NEEDS_HUMAN,
                JobStatus.FAILED,
                JobStatus.CANCELLED,
            }:
                total_duration = int((utc_now() - phase_started).total_seconds() * 1000)
                self.uow.metrics.save(
                    MetricFact(
                        metric_name="total_duration_ms",
                        project_id=latest.project_id,
                        change_id=latest.change_name,
                        duration_ms=total_duration,
                        details={
                            "job_id": latest.job_id,
                            "status": latest.status.value,
                        },
                    )
                )
                self.uow.commit()
        return self._require_job(job.job_id)

    async def _run_audit_stage(
        self,
        job: Job,
        project: Project,
        worktree_path: Path,
        check_run_results: list,
        review_id: str,
    ) -> Job:
        """Execute DeepSeek Direct audit. OpenRouter is never used for audit."""
        review = self.uow.reviews.get_by_id(review_id)
        review_findings = self.uow.review_findings.list_by_review(review_id) if review else []
        persisted_checks = [
            r
            for r in self.uow.check_results.list_by_job(job.job_id)
            if r.candidate_sha == job.candidate_sha
        ]
        effective_checks_results = check_run_results if check_run_results else persisted_checks
        pre_ok, pre_err = verify_pre_audit(
            worktree_path=worktree_path,
            job=job,
            review=review,
            checks_results=effective_checks_results,
            base_branch=project.base_branch,
            repo_root_path=self.project_root,
        )
        if not pre_ok:
            self._save_event(EventType.CANDIDATE_SHA_MISMATCH, job, {"error": pre_err})
            raise RuntimeError(pre_err or "Pre-audit integrity failure.")

        job = self._transition(job, JobStatus.AUDIT_RUNNING)
        audit = AuditRecord(
            job_id=job.job_id,
            project_id=job.project_id,
            change_name=job.change_name,
            candidate_sha=job.candidate_sha or "",
            base_sha=job.base_sha or "",
            review_id=review.review_id if review else None,
            review_verdict=review.verdict if review else None,
            status=AuditStatus.AUDIT_RUNNING,
        )
        self.uow.audits.save(audit)
        self.uow.commit()

        audit_view_created = False
        try:
            # Observation-only symlink safety scan
            self.reviewer_view_manager.verify_candidate_tree(worktree_path)

            audit_wt_info = await self.worktree_manager.create_review_worktree(
                job_id=job.job_id,
                change_name=job.change_name,
                candidate_sha=job.candidate_sha or "",
                reviewer_role="deepseek-auditor",
                project_id=job.project_id,
            )
            audit_view = audit_wt_info.path
            audit_view_created = True

            prompt = build_audit_prompt(
                project=project,
                change_name=job.change_name,
                job_id=job.job_id,
                audit_id=audit.audit_id,
                candidate_sha=job.candidate_sha or "",
                base_sha=job.base_sha or "",
                audit_view_path=audit_view,
                checks_results=check_run_results,
                review=review,
                review_findings=review_findings,
            )
            runner = self.auditor_runner or DeepSeekAuditorRunner()
            result = await runner.run(
                audit_view,
                prompt,
                timeout_seconds=self.reviewer_timeout_seconds,
            )
            for line in result.output:
                self._log(job.job_id, "audit", line)
            self.uow.metrics.save(
                MetricFact(
                    metric_name="audit_duration_ms",
                    project_id=job.project_id,
                    change_id=job.change_name,
                    duration_ms=result.duration_ms,
                    details={
                        "job_id": job.job_id,
                        "audit_id": audit.audit_id,
                        "provider": result.provider,
                        "model": result.model,
                    },
                )
            )

            if result.timed_out:
                self.uow.audits.transition(
                    audit.audit_id,
                    AuditStatus.AUDIT_TIMED_OUT.value,
                    error_message=result.error_message
                    or f"DeepSeek audit timed out after {self.reviewer_timeout_seconds} seconds.",
                )
                self._save_event(
                    EventType.AUDIT_TIMEOUT,
                    job,
                    {"audit_id": audit.audit_id, "provider": "deepseek"},
                )
                self.uow.commit()
                raise RuntimeError("DeepSeek audit timed out.")

            if result.exit_code != 0:
                err = result.error_message or f"DeepSeek audit failed with code {result.exit_code}."
                self.uow.audits.transition(
                    audit.audit_id,
                    AuditStatus.AUDIT_FAILED.value,
                    error_message=err,
                )
                self._save_event(
                    EventType.JOB_AUDIT_FAILED,
                    job,
                    {"audit_id": audit.audit_id, "error": err},
                )
                self.uow.commit()
                raise RuntimeError(err)

            post_ok, post_err = verify_post_audit(worktree_path, job.candidate_sha or "")
            if not post_ok:
                self.uow.audits.transition(
                    audit.audit_id,
                    AuditStatus.AUDIT_FAILED.value,
                    error_message=post_err,
                )
                self._save_event(
                    EventType.UNAUTHORIZED_AUDITOR_MUTATION,
                    job,
                    {"audit_id": audit.audit_id, "error": post_err},
                )
                self.uow.commit()
                raise RuntimeError(post_err or "Post-audit mutation detected.")

            try:
                audit_result = parse_audit_result(result.output)
            except Exception as exc:
                err = f"Malformed audit output: {exc}"
                self.uow.audits.transition(
                    audit.audit_id,
                    AuditStatus.AUDIT_FAILED.value,
                    error_message=err,
                )
                self._save_event(
                    EventType.AUDIT_MALFORMED_OUTPUT,
                    job,
                    {"audit_id": audit.audit_id, "error": err},
                )
                self.uow.commit()
                raise RuntimeError(err) from exc

            has_blocking_finding = any(
                f.severity in {AuditFindingSeverity.HIGH, AuditFindingSeverity.CRITICAL}
                for f in audit_result.findings
            )
            blocking = (
                audit_result.risk
                in {
                    AuditRiskLevel.HIGH,
                    AuditRiskLevel.CRITICAL,
                }
                or has_blocking_finding
            )
            audit_status = AuditStatus.AUDIT_BLOCKED if blocking else AuditStatus.AUDIT_COMPLETED
            self.uow.audits.transition(
                audit.audit_id,
                audit_status.value,
                risk=audit_result.risk.value,
                summary=audit_result.summary,
            )
            for item in audit_result.findings:
                self.uow.audit_findings.save(
                    AuditFinding(
                        audit_id=audit.audit_id,
                        severity=item.severity,
                        category=item.category,
                        message=item.message,
                        file=item.file,
                        location=item.location,
                    )
                )
            event_type = EventType.JOB_AUDIT_BLOCKED if blocking else EventType.JOB_AUDIT_COMPLETED
            audit_diag = EvidenceDiagnostic(
                job_id=job.job_id,
                stage_type="AUDIT",
                check_name="deepseek_direct_audit",
                diagnostic_status=EvidenceDiagnosticStatus.FAIL
                if blocking
                else EvidenceDiagnosticStatus.PASS,
                environment_identity="deepseek-direct",
                candidate_sha=job.candidate_sha or "",
                reason=audit_result.summary,
                evidence_reference={
                    "risk": audit_result.risk.value,
                    "findings_count": len(audit_result.findings),
                },
            )
            self.uow.evidence_diagnostics.save(audit_diag)
            self.uow.commit()
            self._save_event(
                event_type,
                job,
                {
                    "audit_id": audit.audit_id,
                    "risk": audit_result.risk.value,
                    "findings": len(audit_result.findings),
                },
            )
            self.uow.commit()
            return self._transition(
                job, JobStatus.AUDIT_BLOCKED if blocking else JobStatus.READY_TO_MERGE
            )
        except Exception as exc:
            latest_audit = self.uow.audits.get_by_id(audit.audit_id)
            if latest_audit and latest_audit.status not in {
                AuditStatus.AUDIT_COMPLETED,
                AuditStatus.AUDIT_BLOCKED,
                AuditStatus.AUDIT_FAILED,
                AuditStatus.AUDIT_TIMED_OUT,
            }:
                err = str(exc)
                self.uow.audits.transition(
                    audit.audit_id,
                    AuditStatus.AUDIT_FAILED.value,
                    error_message=err,
                )
                self._save_event(
                    EventType.JOB_AUDIT_FAILED,
                    job,
                    {"audit_id": audit.audit_id, "error": err},
                )
                self.uow.commit()
            raise
        finally:
            if audit_view_created and "audit_view" in locals() and audit_view:
                try:
                    await self.worktree_manager.remove_review_worktree(
                        audit_view, job.job_id, job.project_id
                    )
                except Exception as clean_err:
                    logger.warning(
                        f"Failed to clean up audit worktree at '{audit_view}': {clean_err}"
                    )

    def _is_dual_primary_exhausted(self, project: Project) -> bool:
        """Check if both primary providers (Codex and Antigravity) are exhausted / unavailable."""
        codex_h = self._get_provider_health("codex")
        agy_h = self._get_provider_health("antigravity")
        codex_unavail = codex_h is not None and codex_h.status != ProviderHealthStatus.AVAILABLE
        agy_unavail = agy_h is not None and agy_h.status != ProviderHealthStatus.AVAILABLE
        return codex_unavail and agy_unavail

    def _require_project(self, project_id: str) -> Project:
        project = self.uow.projects.get_by_id(project_id)
        if not project:
            raise ValueError(f"Project '{project_id}' not found.")
        return project

    def _require_job(self, job_id: str) -> Job:
        job = self.uow.jobs.get_by_id(job_id)
        if not job:
            raise ValueError(f"Job '{job_id}' not found.")
        return job

    async def _invoke_checks_runner(
        self,
        job_id: str,
        checks: list[dict[str, Any]],
        worktree_path: Path,
        *,
        candidate_sha: str | None = None,
        candidate_generation: int | None = None,
        attempt_id: str | None = None,
    ) -> ChecksRunResult:
        """Invoke checks runner exactly once after pre-inspecting accepted signature parameters."""
        import inspect

        sig = inspect.signature(self.checks_runner.run)
        kwargs: dict[str, Any] = {}
        if "candidate_sha" in sig.parameters and candidate_sha is not None:
            kwargs["candidate_sha"] = candidate_sha
        if "candidate_generation" in sig.parameters and candidate_generation is not None:
            kwargs["candidate_generation"] = candidate_generation
        if "attempt_id" in sig.parameters and attempt_id is not None:
            kwargs["attempt_id"] = attempt_id
        return await self.checks_runner.run(
            job_id,
            checks,
            worktree_path,
            **kwargs,
        )

    def _transition(
        self,
        job: Job,
        status: JobStatus,
        error_message: str | None = None,
        claim_context: RecoveryClaimContext | None = None,
        auto_commit: bool = True,
    ) -> Job:
        updated = self.uow.jobs.transition(
            job.job_id, status.value, error_message=error_message, claim_context=claim_context
        )
        event_type = EVENT_BY_STATUS[status]
        self._save_event(event_type, updated, {"status": status.value, "error": error_message})
        if claim_context is not None:
            from minime.domain.models import validate_claim_context_authoritative

            validate_claim_context_authoritative(self.uow, claim_context)
        if auto_commit:
            self.uow.commit()
        return updated

    def _save_event(self, event_type: EventType, job: Job, payload: dict) -> None:
        self.uow.events.save(
            Event(
                event_type=event_type,
                project_id=job.project_id,
                change_id=job.change_name,
                operation_id=job.job_id,
                payload={"job_id": job.job_id, **payload},
            )
        )

    def _log(self, job_id: str, stream: str, message: str) -> None:
        self.uow.job_logs.save(JobLog(job_id=job_id, stream=stream, message=message))

    def _try_classify_post_materialization(
        self, job: Job, worktree_path: str | Path | None = None
    ) -> None:
        """Perform post-materialization classification, fire-and-forget.

        Classification failure is logged and an error event is emitted
        but never blocks the pipeline.
        """
        try:
            if not job.candidate_sha or not job.base_sha:
                return

            diff_paths: list[str] = []
            if worktree_path and Path(worktree_path).exists():
                diff = subprocess.run(
                    ["git", "diff", "--name-only", f"{job.base_sha}..{job.candidate_sha}"],
                    cwd=worktree_path,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if diff.returncode == 0 and diff.stdout:
                    diff_paths = [line.strip() for line in diff.stdout.splitlines() if line.strip()]

            change = self.uow.changes.get_by_name(job.project_id, job.change_name)
            change_id = change.change_id if change else None

            pre_snapshot = None
            if change_id:
                try:
                    pre_snapshot = self.uow.classification_snapshots.find_latest_by_change(
                        change_id
                    )
                except Exception:
                    pass

            from minime.services.task_complexity_risk_classifier import (
                TaskComplexityRiskClassifier,
            )

            classifier = TaskComplexityRiskClassifier()
            snapshot = classifier.classify_post_materialization(
                pre_execution_snapshot=pre_snapshot,
                diff_file_paths=diff_paths,
            )
            snapshot.job_id = job.job_id
            snapshot.change_id = change_id

            self.uow.classification_snapshots.save(snapshot)

            job.classification_snapshot_id = snapshot.id
            self.uow.jobs.save(job)

            logger.info(
                "Post-materialization classification created: job=%s, complexity=%s, "
                "surface=%s, mismatch=%s, snapshot_id=%s",
                job.job_id,
                snapshot.complexity.value,
                snapshot.surface_kind.value,
                snapshot.breadth_mismatch_detected,
                snapshot.id,
            )
        except Exception as exc:
            logger.error(
                "Post-materialization classification failed (non-blocking): job=%s, error=%s",
                job.job_id,
                exc,
            )
            self.uow.events.save(
                Event(
                    event_type=EventType.AUXILIARY_CLASSIFICATION_FAILED,
                    project_id=job.project_id,
                    change_id=job.change_name,
                    payload={
                        "classification_error": str(exc),
                        "stage": "post_materialization",
                        "job_id": job.job_id,
                    },
                    timestamp=utc_now(),
                )
            )
