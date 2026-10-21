"""Operator Actions Control Plane service for mini me.

Provides canonical action discovery, authority validation, optimistic concurrency,
idempotency, cancellation safety, and durable audit persistence across presentation layers.
"""

from __future__ import annotations

import logging
import subprocess
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from minime.config import (
    OpenSpecStage,
    ProjectConfig,
    load_config,
    resolve_stage_profile,
)
from minime.domain.enums import (
    ActionRiskLevel,
    EventType,
    ExternalActionStatus,
    HumanGate,
    JobStatus,
    OperatorActionErrorCode,
    OperatorActionStatus,
    OperatorActionType,
    OrchestrationStage,
    OrchestrationStopOutcome,
    PreviewStatus,
    ProviderHealthStatus,
    RecoveryClassification,
    RecoveryDecisionStatus,
    RecoverySource,
    ReviewStatus,
    ReviewVerdict,
    ValidationVerdict,
)
from minime.domain.interfaces import PersistenceUnitOfWork
from minime.domain.models import (
    ActionDescriptor,
    Event,
    OperatorActionRecord,
    OperatorActionRequest,
    OperatorActionResult,
    OrchestrationRun,
    PreviewSession,
    RecoveryDecision,
    generate_uuid,
    utc_now,
)
from minime.logging import redact_secrets
from minime.services.container_preview_service import ContainerPreviewService
from minime.services.orchestration_service import OrchestrationService
from minime.services.post_merge_service import PostMergeReconciliationService
from minime.services.provider_health_service import ProviderHealthService
from minime.services.recovery_convergence_service import RecoveryConvergenceService
from minime.services.restart_recovery_service import RestartRecoveryService
from minime.services.validation_authority_service import ValidationAuthorityService

logger = logging.getLogger(__name__)


class ControlPlaneService:
    """Canonical Operator Control Plane service."""

    def __init__(
        self,
        uow: PersistenceUnitOfWork,
        project_root: str | Path = ".",
        orchestration_service: OrchestrationService | None = None,
        preview_service: ContainerPreviewService | None = None,
        validation_service: ValidationAuthorityService | None = None,
        recovery_service: RestartRecoveryService | None = None,
        provider_health_service: ProviderHealthService | None = None,
        post_merge_service: PostMergeReconciliationService | None = None,
        deepseek_code_review_service: Any | None = None,
    ):
        self.uow = uow
        self.deepseek_code_review_service = deepseek_code_review_service
        self.project_root = Path(project_root).resolve()
        self.orchestration_service = orchestration_service or OrchestrationService(
            uow, project_root=self.project_root
        )
        self.preview_service = preview_service or ContainerPreviewService(uow)
        self.validation_service = validation_service or ValidationAuthorityService(uow)
        self.recovery_service = recovery_service or RestartRecoveryService(
            uow, project_root=self.project_root
        )
        self.provider_health_service = provider_health_service or ProviderHealthService(uow)
        self.recovery_convergence_service = RecoveryConvergenceService(
            uow,
            project_root=self.project_root,
            health_service=self.provider_health_service,
            orchestration_service=self.orchestration_service,
        )
        gh_adapter = getattr(self.orchestration_service, "github_adapter", None)
        self.post_merge_service = post_merge_service or PostMergeReconciliationService(
            uow, project_root=self.project_root, github_adapter=gh_adapter
        )

    def _deepseek_review_authorized_total(self, run: OrchestrationRun) -> Decimal | None:
        """Return prior DeepSeek review authorizations for this Run, or None if ambiguous."""
        total = Decimal("0")
        review_actions = {
            OperatorActionType.AUTHORIZE_DEEPSEEK_REVIEW: "CONTRACT_REVIEW",
            OperatorActionType.AUTHORIZE_DEEPSEEK_CODE_REVIEW: "REVIEW",
        }
        for action in self.uow.operator_actions.list_by_run(run.run_id, limit=10000):
            expected_stage = review_actions.get(action.action_type)
            if not expected_stage or action.status != OperatorActionStatus.COMPLETED:
                continue
            auth = action.result_payload_json.get("authorization", {})
            if (
                action.project_id != run.project_id
                or action.change_name != run.change_name
                or action.run_id != run.run_id
                or not action.job_id
                or auth.get("provider") != "deepseek"
                or auth.get("billing_origin") != "deepseek_direct"
                or auth.get("stage") != expected_stage
                or auth.get("run_id") != run.run_id
                or auth.get("job_id") != action.job_id
            ):
                return None
            try:
                amount = Decimal(str(auth["max_spend_usd"]))
            except Exception:
                return None
            if not amount.is_finite() or amount <= 0:
                return None
            if expected_stage == "REVIEW" and action.job_id:
                job = self.uow.jobs.get_by_id(action.job_id)
                candidates_repo = getattr(self.uow, "orchestration_candidates", None)
                candidate = (
                    candidates_repo.get_by_generation(run.run_id, run.current_generation)
                    if candidates_repo
                    else None
                )
                if (
                    job
                    and candidate
                    and auth.get("candidate_sha") == candidate.candidate_sha
                    and self._expired_unused_code_review_authorization(action, run, job, candidate)
                ):
                    continue
            total += amount
        return total

    def _deepseek_combined_review_limit(self, budget: dict[str, Any]) -> Decimal | None:
        """Return only an owner-configured combined limit; no value means uncapped."""
        try:
            configured = budget.get("maximum_combined_review_usd")
            if configured is None:
                return None
            limit = Decimal(str(configured))
        except Exception:
            return Decimal("0")
        return limit if limit.is_finite() and limit > 0 else Decimal("0")

    def _deepseek_review_total_within_limit(
        self, run: OrchestrationRun, budget: dict[str, Any], requested: Decimal
    ) -> bool:
        limit = self._deepseek_combined_review_limit(budget)
        if limit is None:
            return True
        prior_total = self._deepseek_review_authorized_total(run)
        return prior_total is not None and limit > 0 and prior_total + requested <= limit

    def _worktree_manager_for_bound_project(self, project_id: str, project=None):
        """Build a worktree manager from the exact durable managed-repository binding."""
        from minime.services.repository_identity import normalize_repository_identity
        from minime.services.workspace_guard import (
            ManagedWorkspaceGuard,
            is_binding_fully_valid,
        )
        from minime.services.worktree_manager import WorktreeManager

        bindings = getattr(self.uow, "project_managed_repository_bindings", None)
        binding = bindings.get_by_project_id(project_id) if bindings else None
        project = project or self.uow.projects.get_by_id(project_id)
        if (
            not is_binding_fully_valid(binding)
            or binding.project_id != project_id
            or not project
            or normalize_repository_identity(project.repository)
            != normalize_repository_identity(binding.canonical_repository_identity)
        ):
            raise RuntimeError("validated managed repository binding is missing or contradictory")

        configured_root = Path(binding.managed_repository_root)
        try:
            resolved_root = configured_root.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise RuntimeError("bound managed repository root is unavailable") from exc
        if (
            not configured_root.is_absolute()
            or configured_root.is_symlink()
            or configured_root != resolved_root
            or not resolved_root.is_dir()
        ):
            raise RuntimeError("bound managed repository root is non-canonical or unsafe")

        guard = ManagedWorkspaceGuard(self.uow)
        git_identity_valid, _reason = guard.verify_git_repository_identity(
            str(resolved_root), binding.canonical_repository_identity, binding.remote_name
        )
        try:
            git_root = subprocess.run(
                ["git", "rev-parse", "--show-toplevel"],
                cwd=resolved_root,
                capture_output=True,
                text=True,
                check=True,
                timeout=5,
            ).stdout.strip()
        except (OSError, subprocess.SubprocessError) as exc:
            raise RuntimeError("bound managed repository Git root is unobservable") from exc
        if not git_identity_valid or Path(git_root).resolve() != resolved_root:
            raise RuntimeError("bound managed repository Git identity or root is contradictory")

        return WorktreeManager(
            project_root=resolved_root,
            uow=self.uow,
            workspace_guard=guard,
        )

    @staticmethod
    def _authorization_expiry(authorization: dict[str, Any]) -> datetime | None:
        try:
            value = datetime.fromisoformat(str(authorization.get("expires_at")))
        except (TypeError, ValueError):
            return None
        return value if value.tzinfo is not None and value.utcoffset() is not None else None

    def _expired_unused_code_review_authorization(
        self,
        action: OperatorActionRecord,
        run: OrchestrationRun,
        job,
        candidate,
        *,
        now: datetime | None = None,
    ) -> bool:
        """Prove a prior candidate-bound authorization expired before any review dispatch."""
        authorization = action.result_payload_json.get("authorization", {})
        expected = {
            "provider": "deepseek",
            "stage": "REVIEW",
            "billing_origin": "deepseek_direct",
            "run_id": run.run_id,
            "job_id": job.job_id,
            "candidate_sha": candidate.candidate_sha,
            "base_sha": candidate.base_sha,
            "generation": candidate.generation,
            "manifest_id": candidate.manifest_id,
            "manifest_hash": candidate.manifest_hash,
            "action_request_id": action.action_request_id,
        }
        if (
            action.action_type != OperatorActionType.AUTHORIZE_DEEPSEEK_CODE_REVIEW
            or action.status != OperatorActionStatus.COMPLETED
            or action.project_id != run.project_id
            or action.change_name != run.change_name
            or action.run_id != run.run_id
            or action.job_id != job.job_id
            or not all(authorization.get(key) == value for key, value in expected.items())
            or not authorization.get("account_fingerprint")
            or not authorization.get("model")
            or not authorization.get("pricing_snapshot_id")
            or not authorization.get("authorized_by")
        ):
            return False
        expiry = self._authorization_expiry(authorization)
        current = now or utc_now()
        if expiry is None or expiry > current:
            return False
        try:
            maximum = Decimal(str(authorization.get("max_spend_usd")))
        except (InvalidOperation, TypeError, ValueError):
            return False
        if not maximum.is_finite() or maximum <= 0:
            return False

        auth_id = action.action_request_id
        dispatch_key = f"deepseek-code-review:{auth_id}"
        reservations_repo = getattr(self.uow, "budget_reservations", None)
        ledger_repo = getattr(self.uow, "budget_ledger", None)
        reviews_repo = getattr(self.uow, "reviews", None)
        external_repo = getattr(self.uow, "orchestration_external_actions", None)
        attempts_repo = getattr(self.uow, "external_action_attempts", None)
        actions_repo = getattr(self.uow, "operator_actions", None)
        if not all(
            (
                reservations_repo,
                ledger_repo,
                reviews_repo,
                external_repo,
                attempts_repo,
                actions_repo,
            )
        ):
            return False

        if any(
            reservation.authorization_id == auth_id
            for reservation in reservations_repo.list_by_project(run.project_id)
        ):
            return False
        if any(
            entry.job_id == job.job_id
            and entry.provider == "deepseek"
            and entry.stage == "REVIEW"
            and entry.billing_origin == "deepseek_direct"
            and entry.created_at >= action.created_at
            for entry in ledger_repo.list_by_project(run.project_id)
        ):
            return False
        if any(
            review.budget_authorization_id == auth_id
            or (
                review.candidate_sha == candidate.candidate_sha
                and review.base_sha == candidate.base_sha
                and review.orchestration_run_id == run.run_id
            )
            for review in reviews_repo.list_by_job(job.job_id)
        ):
            return False
        if external_repo.get_by_action_key(dispatch_key) is not None:
            return False
        if attempts_repo.list_by_action_key(dispatch_key):
            return False

        for execute_action in actions_repo.list_by_run(run.run_id, limit=10000):
            if (
                execute_action.action_type
                != OperatorActionType.EXECUTE_AUTHORIZED_DEEPSEEK_CODE_REVIEW
                or execute_action.parameters_json.get("authorization_id") != auth_id
            ):
                continue
            if not (
                execute_action.status == OperatorActionStatus.REJECTED
                and execute_action.error_code == OperatorActionErrorCode.AUTHORITY_MISMATCH
                and execute_action.summary.startswith(
                    "Frozen candidate worktree adoption proof failed:"
                )
                and not execute_action.result_payload_json.get("recovery_decision_id")
                and not execute_action.result_payload_json.get("dispatch_action_key")
            ):
                return False
        return True

    def _code_review_authorization_renewal_allowed(
        self, run: OrchestrationRun, job, candidate
    ) -> bool:
        """Allow no prior grant or only exact expired/unused grants for this candidate."""
        actions = self.uow.operator_actions.list_by_run(run.run_id, limit=10000)
        prior = []
        for action in actions:
            if (
                action.action_type != OperatorActionType.AUTHORIZE_DEEPSEEK_CODE_REVIEW
                or action.job_id != job.job_id
            ):
                continue
            auth = action.result_payload_json.get("authorization", {})
            bound_sha = auth.get("candidate_sha")
            if not bound_sha or bound_sha == candidate.candidate_sha:
                prior.append(action)
        return all(
            self._expired_unused_code_review_authorization(action, run, job, candidate)
            for action in prior
        )

    def get_available_actions(self, run_id: str) -> list[ActionDescriptor]:
        """Discover all supported operator actions for a run and their current eligibility."""
        run = self.uow.orchestration_runs.get_by_id(run_id)
        if not run:
            return []

        project = self.uow.projects.get_by_id(run.project_id)
        active_preview = self.uow.preview_sessions.get_active_for_change(
            run.project_id, run.change_name
        )

        descriptors: list[ActionDescriptor] = []

        # 1. CONTINUE / RESUME
        continue_enabled = False
        continue_reason: str | None = None
        stale_checkpoint = self._has_stale_active_checkpoint(run) if run.is_active else False
        review_hold_code = (run.stop_details or {}).get("code")
        exceptional_review_hold = review_hold_code in {
            "REVIEW_AUTHORIZATION_PENDING",
            "CODE_REVIEW_COMPLETED_REQUIRES_SEPARATE_AUTHORIZED_CONTINUATION",
            "CODE_REVIEW_COMPLETED_CHANGES_REQUIRED",
        }
        if (
            run.is_active
            and run.stop_outcome != OrchestrationStopOutcome.WAITING_CAPACITY
            and not stale_checkpoint
        ):
            continue_reason = "Run is already active"
        elif exceptional_review_hold:
            continue_reason = "Use the separately authorized frozen-candidate review action."
            continue_enabled = False
        elif stale_checkpoint:
            continue_enabled = True
        elif run.current_stage == OrchestrationStage.PR_PREPARED:
            continue_reason = "Run has completed PR preparation"
        elif run.stop_outcome == OrchestrationStopOutcome.CANCELLED:
            continue_reason = "Run was cancelled"
        elif (
            run.stop_outcome == OrchestrationStopOutcome.NEEDS_HUMAN
            or run.human_gate == HumanGate.NEEDS_HUMAN
        ):
            stop_reason = run.stop_reason or ""
            stop_details = run.stop_details or {}
            is_preserved_conflict = (
                "PRESERVED_CANDIDATE" in stop_reason
                or "PRESERVED_CANDIDATE" in str(stop_details)
                or "integration" in stop_reason.lower()
                or "base advanced" in stop_reason.lower()
            )
            is_ui_validation = (
                "UI_VALIDATION" in stop_reason
                or "VALIDATION_REQUIRED" in str(stop_details)
                or "validation" in stop_reason.lower()
            )
            if is_preserved_conflict or is_ui_validation:
                continue_enabled = False
                continue_reason = "Run is stopped at a human gate; use Resolve Gate instead."
            else:
                continue_enabled = True
        elif run.resumable_stage is not None or run.stop_outcome in {
            OrchestrationStopOutcome.WAITING_CAPACITY,
            OrchestrationStopOutcome.WAITING_EXTERNAL,
            OrchestrationStopOutcome.FAILED,
        }:
            continue_enabled = True
        else:
            continue_reason = "Run is not in a resumable state"

        descriptors.append(
            ActionDescriptor(
                action=OperatorActionType.CONTINUE,
                display_name="Continue / Resume",
                description="Resume execution from persisted checkpoint using canonical orchestration semantics.",
                enabled=continue_enabled,
                disabled_reason=continue_reason,
                requires_confirmation=False,
                risk_level=ActionRiskLevel.LOW,
            )
        )

        active_job = self.uow.jobs.get_by_id(run.active_job_id) if run.active_job_id else None
        frozen_candidate = (
            self.uow.orchestration_candidates.get_by_generation(run.run_id, run.current_generation)
            if active_job
            else None
        )
        review_authorizations = [
            action
            for action in self.uow.operator_actions.list_by_run(run.run_id, limit=10000)
            if action.action_type == OperatorActionType.AUTHORIZE_DEEPSEEK_CODE_REVIEW
            and action.status == OperatorActionStatus.COMPLETED
            and action.job_id == (active_job.job_id if active_job else None)
            and action.result_payload_json.get("authorization", {}).get("candidate_sha")
            == (frozen_candidate.candidate_sha if frozen_candidate else None)
        ]
        review_authorization = (
            max(review_authorizations, key=lambda action: action.created_at)
            if review_authorizations
            else None
        )
        dispatch_key = (
            f"deepseek-code-review:{review_authorization.action_request_id}"
            if review_authorization
            else None
        )
        existing_review_dispatch = (
            self.uow.orchestration_external_actions.get_by_action_key(dispatch_key)
            if dispatch_key
            else None
        )
        latest_check_valid, _, latest_check_batch = (
            self.orchestration_service._validate_current_checks_batch(
                active_job,
                run,
                project,
                require_configured_checks=True,
            )
            if active_job and project and frozen_candidate
            else (False, "Candidate/check evidence unavailable.", [])
        )
        review_dispatch_enabled = bool(
            review_hold_code == "REVIEW_AUTHORIZATION_PENDING"
            and not run.is_active
            and active_job
            and active_job.status == JobStatus.CHECKS_PASSED
            and frozen_candidate
            and frozen_candidate.is_frozen
            and frozen_candidate.candidate_sha == active_job.candidate_sha
            and frozen_candidate.candidate_sha == run.current_candidate_sha
            and frozen_candidate.base_sha == run.base_sha == active_job.base_sha
            and frozen_candidate.generation == run.current_generation
            and review_authorization
            and (
                authorization_expiry := self._authorization_expiry(
                    review_authorization.result_payload_json.get("authorization", {})
                )
            )
            is not None
            and authorization_expiry > utc_now()
            and latest_check_valid
            and bool(latest_check_batch)
            and existing_review_dispatch is None
        )
        descriptors.append(
            ActionDescriptor(
                action=OperatorActionType.EXECUTE_AUTHORIZED_DEEPSEEK_CODE_REVIEW,
                display_name="Execute Authorized Frozen-Candidate Code Review",
                description=(
                    "Dispatch the one-use read-only DeepSeek review for the exact frozen candidate."
                ),
                enabled=review_dispatch_enabled,
                disabled_reason=(
                    None
                    if review_dispatch_enabled
                    else "A current review hold, exact frozen candidate, complete passing checks, unused authorization and binding are required."
                ),
                requires_confirmation=True,
                confirmation_prompt=(
                    "Dispatch the one-use DeepSeek CODE_REVIEW for this exact frozen candidate?"
                ),
                risk_level=ActionRiskLevel.HIGH,
                parameters_schema={
                    "type": "object",
                    "required": ["authorization_id"],
                    "properties": {"authorization_id": {"type": "string"}},
                    "additionalProperties": False,
                },
            )
        )

        completed_review = (
            self.uow.reviews.get_by_job_stage(active_job.job_id, "CODE_REVIEW")
            if active_job
            else None
        )
        completed_review_authorization = (
            self.uow.operator_actions.get_by_request_id(completed_review.budget_authorization_id)
            if completed_review and completed_review.budget_authorization_id
            else None
        )
        completed_review_reservation = (
            self.uow.budget_reservations.get_by_id(completed_review.budget_reservation_id)
            if completed_review and completed_review.budget_reservation_id
            else None
        )
        completed_review_dispatch = (
            self.uow.orchestration_external_actions.get_by_action_key(
                f"deepseek-code-review:{completed_review.budget_authorization_id}"
            )
            if completed_review and completed_review.budget_authorization_id
            else None
        )
        completed_review_attempts = (
            self.uow.external_action_attempts.list_by_action_key(
                f"deepseek-code-review:{completed_review.budget_authorization_id}"
            )
            if completed_review and completed_review.budget_authorization_id
            else []
        )
        reviewer_independent = False
        if completed_review and active_job:
            from minime.services.authorship_service import AuthorshipService

            reviewer_independent, _ = AuthorshipService().is_reviewer_eligible(
                active_job.job_id, completed_review.reviewer_role, self.uow
            )
        post_review_continue_enabled = bool(
            review_hold_code == "CODE_REVIEW_COMPLETED_REQUIRES_SEPARATE_AUTHORIZED_CONTINUATION"
            and not run.is_active
            and active_job
            and frozen_candidate
            and frozen_candidate.is_frozen
            and completed_review
            and completed_review.status == ReviewStatus.REVIEW_COMPLETED
            and completed_review.verdict == ReviewVerdict.READY_TO_MERGE
            and completed_review.provider == "deepseek"
            and completed_review.budget_authorization_id
            and completed_review.orchestration_run_id == run.run_id
            and completed_review.job_id == active_job.job_id
            and completed_review.project_id == run.project_id
            and completed_review.change_name == run.change_name
            and completed_review.candidate_sha == frozen_candidate.candidate_sha
            and completed_review.base_sha == frozen_candidate.base_sha
            and completed_review.candidate_generation == run.current_generation
            and completed_review.manifest_id == frozen_candidate.manifest_id
            and completed_review.manifest_hash == frozen_candidate.manifest_hash
            and completed_review_authorization
            and completed_review_authorization.action_type
            == OperatorActionType.AUTHORIZE_DEEPSEEK_CODE_REVIEW
            and completed_review_authorization.status == OperatorActionStatus.COMPLETED
            and completed_review_authorization.run_id == run.run_id
            and completed_review_authorization.job_id == active_job.job_id
            and completed_review_reservation
            and completed_review_reservation.authorization_id
            == completed_review.budget_authorization_id
            and completed_review_reservation.status == "SETTLED"
            and completed_review_reservation.run_id == run.run_id
            and completed_review_reservation.job_id == active_job.job_id
            and completed_review_reservation.project_id == run.project_id
            and completed_review_reservation.provider == "deepseek"
            and completed_review_reservation.account_fingerprint
            == completed_review.account_fingerprint
            and completed_review_reservation.canonical_model_identity
            == completed_review.reviewer_model
            and completed_review_reservation.stage == "REVIEW"
            and completed_review_reservation.billing_origin == "deepseek_direct"
            and completed_review_reservation.idempotency_key
            == self._expected_code_review_reservation_key(
                run, active_job, frozen_candidate, completed_review.budget_authorization_id
            )
            and completed_review_dispatch
            and completed_review_dispatch.status == ExternalActionStatus.COMPLETED
            and completed_review_dispatch.remote_identifier == completed_review.review_id
            and len(completed_review_attempts) == 1
            and completed_review_attempts[0].status == "COMPLETED"
            and reviewer_independent
        )
        descriptors.append(
            ActionDescriptor(
                action=OperatorActionType.CONTINUE_AFTER_CODE_REVIEW,
                display_name="Continue After Independent Code Review",
                description=(
                    "Continue a completed READY_TO_MERGE review through existing audit and PR gates; never merge."
                ),
                enabled=post_review_continue_enabled,
                disabled_reason=(
                    None
                    if post_review_continue_enabled
                    else "An exact completed independent review and separate post-review continuation gate are required."
                ),
                requires_confirmation=True,
                confirmation_prompt=(
                    "Continue this exact reviewed candidate through existing downstream gates?"
                ),
                risk_level=ActionRiskLevel.HIGH,
                parameters_schema={
                    "type": "object",
                    "required": ["review_id", "candidate_sha", "manifest_hash"],
                    "properties": {
                        "review_id": {"type": "string"},
                        "candidate_sha": {"type": "string"},
                        "manifest_hash": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
            )
        )

        # 2. RETRY
        retry_enabled = False
        retry_reason: str | None = None
        if run.is_active:
            retry_reason = "Run is already active"
        elif run.current_stage in {
            OrchestrationStage.RUNNING_CHECKS,
            OrchestrationStage.IMPLEMENTING,
        }:
            if run.retry_count >= 3:
                retry_reason = f"Maximum retry limit reached ({run.retry_count}/3)"
            else:
                retry_enabled = True
        else:
            retry_reason = "Retry is only available for failed implementation or check stages"

        descriptors.append(
            ActionDescriptor(
                action=OperatorActionType.RETRY,
                display_name="Retry Stage",
                description="Retry the failed stage/attempt within configured retry budgets.",
                enabled=retry_enabled,
                disabled_reason=retry_reason,
                requires_confirmation=True,
                confirmation_prompt="Retry current failed stage? A new attempt will be recorded.",
                risk_level=ActionRiskLevel.MEDIUM,
            )
        )

        # 3. REASSIGN
        reassign_enabled = False
        reassign_reason: str | None = None
        if run.is_active:
            reassign_reason = "Run is already active"
        elif project and len(project.external_providers_allowed) > 1:
            if run.current_stage in {
                OrchestrationStage.IMPLEMENTING,
                OrchestrationStage.RUNNING_CHECKS,
                OrchestrationStage.REVIEW_REMEDIATION,
                OrchestrationStage.COMPLEMENTARY_REVIEW,
            }:
                reassign_enabled = True
            else:
                reassign_reason = (
                    "Reassignment only applicable during implementation or review stages"
                )
        else:
            reassign_reason = "No alternative providers configured for project"

        descriptors.append(
            ActionDescriptor(
                action=OperatorActionType.REASSIGN,
                display_name="Reassign Executor",
                description="Reassign execution to an alternative compatible provider under governance.",
                enabled=reassign_enabled,
                disabled_reason=reassign_reason,
                requires_confirmation=True,
                confirmation_prompt="Reassign execution to alternative provider? Preserves candidate evidence and enforces model independence.",
                risk_level=ActionRiskLevel.MEDIUM,
                parameters_schema={
                    "type": "object",
                    "properties": {
                        "target_executor": {
                            "type": "string",
                            "description": "Target agent/executor role (e.g. codex, antigravity)",
                        }
                    },
                },
            )
        )

        # 4. RESOLVE_GATE
        gate_enabled = False
        gate_reason: str | None = None
        gate_schema: dict[str, Any] = {}
        gate_prompt: str | None = None

        if (
            run.human_gate == HumanGate.NEEDS_HUMAN
            or run.stop_outcome == OrchestrationStopOutcome.NEEDS_HUMAN
        ):
            # Check gate type from stop_reason or details
            stop_reason = run.stop_reason or ""
            stop_details = run.stop_details or {}

            if (
                "PRESERVED_CANDIDATE" in stop_reason
                or "PRESERVED_CANDIDATE" in str(stop_details)
                or "integration" in stop_reason.lower()
                or "base advanced" in stop_reason.lower()
            ):
                gate_enabled = True
                gate_prompt = "Resolve preserved candidate conflict by continuing candidate or starting bounded remediation."
                gate_schema = {
                    "type": "object",
                    "properties": {
                        "resolution_type": {
                            "type": "string",
                            "enum": ["continue_preserved", "remediate_preserved"],
                        },
                        "contract": {
                            "type": "string",
                            "description": "Path to remediation contract JSON",
                        },
                        "candidate_ref": {
                            "type": "string",
                            "description": "Optional branch ref for adoption",
                        },
                    },
                    "required": ["resolution_type"],
                }
            elif (
                "UI_VALIDATION" in stop_reason
                or "VALIDATION_REQUIRED" in str(stop_details)
                or "validation" in stop_reason.lower()
            ):
                gate_enabled = True
                gate_prompt = "Submit authoritative human validation verdict for candidate preview."
                gate_schema = {
                    "type": "object",
                    "properties": {
                        "verdict": {"type": "string", "enum": ["PASS", "FAIL"]},
                        "notes": {"type": "string"},
                        "operator": {"type": "string"},
                    },
                    "required": ["verdict"],
                }
            else:
                gate_enabled = False
                gate_reason = (
                    f"Gate type '{stop_reason}' requires specific manual resolution guidance"
                )
        else:
            gate_reason = "Run is not currently stopped at a human gate"

        descriptors.append(
            ActionDescriptor(
                action=OperatorActionType.RESOLVE_GATE,
                display_name="Resolve Gate",
                description="Resolve an active NEEDS_HUMAN blocker through its canonical resolution contract.",
                enabled=gate_enabled,
                disabled_reason=gate_reason,
                requires_confirmation=True,
                confirmation_prompt=gate_prompt,
                risk_level=ActionRiskLevel.HIGH,
                parameters_schema=gate_schema,
            )
        )

        # 5. CANCEL
        cancel_enabled = False
        cancel_reason: str | None = None
        if run.is_active:
            cancel_enabled = True
        elif (
            run.current_stage == OrchestrationStage.PR_PREPARED
            or run.stop_outcome == OrchestrationStopOutcome.CANCELLED
        ):
            cancel_reason = "Run is already terminal or cancelled"
        else:
            cancel_reason = "Run is not active"

        descriptors.append(
            ActionDescriptor(
                action=OperatorActionType.CANCEL,
                display_name="Cancel Run",
                description="Safely stop active execution while preserving candidate evidence and Git refs.",
                enabled=cancel_enabled,
                disabled_reason=cancel_reason,
                requires_confirmation=True,
                confirmation_prompt="Cancel active execution? Candidate evidence, review records, and worktrees will be preserved.",
                risk_level=ActionRiskLevel.HIGH,
            )
        )

        # 6. START_PREVIEW
        preview_start_enabled = False
        preview_start_reason: str | None = None
        if not project or not project.deployment_preview:
            preview_start_reason = "No preview deployment configured for project"
        elif not run.candidate_sha:
            preview_start_reason = "No frozen candidate available for preview"
        elif active_preview and active_preview.status in {
            PreviewStatus.READY,
            PreviewStatus.STARTING,
            PreviewStatus.PROBING,
        }:
            preview_start_reason = f"Preview session already active ({active_preview.status.value})"
        else:
            preview_start_enabled = True

        descriptors.append(
            ActionDescriptor(
                action=OperatorActionType.START_PREVIEW,
                display_name="Start Preview",
                description="Build and run isolated container preview for candidate.",
                enabled=preview_start_enabled,
                disabled_reason=preview_start_reason,
                requires_confirmation=False,
                risk_level=ActionRiskLevel.LOW,
            )
        )

        # 7. TEARDOWN_PREVIEW
        preview_stop_enabled = False
        preview_stop_reason: str | None = None
        if active_preview and active_preview.status not in {
            PreviewStatus.TERMINATED,
            PreviewStatus.FAILED,
        }:
            preview_stop_enabled = True
        else:
            preview_stop_reason = "No active container preview session"

        descriptors.append(
            ActionDescriptor(
                action=OperatorActionType.TEARDOWN_PREVIEW,
                display_name="Teardown Preview",
                description="Stop and clean up active candidate preview container.",
                enabled=preview_stop_enabled,
                disabled_reason=preview_stop_reason,
                requires_confirmation=False,
                risk_level=ActionRiskLevel.LOW,
            )
        )

        # 8. RECOVER_LOCKS
        locks_enabled = False
        locks_reason: str | None = None
        if (
            run.stop_outcome == OrchestrationStopOutcome.WAITING_EXTERNAL
            or "lock" in (run.stop_reason or "").lower()
        ):
            locks_enabled = True
        else:
            locks_reason = "No abandoned locks detected for this run"

        descriptors.append(
            ActionDescriptor(
                action=OperatorActionType.RECOVER_LOCKS,
                display_name="Recover Locks",
                description="Safely release abandoned Git locks after verifying PID ownership.",
                enabled=locks_enabled,
                disabled_reason=locks_reason,
                requires_confirmation=True,
                confirmation_prompt="Recover abandoned Git locks with verified ownership?",
                risk_level=ActionRiskLevel.HIGH,
            )
        )

        # 9. RECONCILE_POST_MERGE
        post_merge_enabled = (
            run.stop_outcome == OrchestrationStopOutcome.READY_FOR_HUMAN_MERGE
            or run.current_stage
            in {OrchestrationStage.PR_PREPARED, OrchestrationStage.POST_MERGE_RECONCILING}
        )
        post_merge_reason = (
            None if post_merge_enabled else "Run is not awaiting post-merge reconciliation"
        )
        descriptors.append(
            ActionDescriptor(
                action=OperatorActionType.RECONCILE_POST_MERGE,
                display_name="Reconcile Post-Merge",
                description="Detect merge, verify candidate ancestry, reconcile terminal state, sync OpenSpec, and clean up resources.",
                enabled=post_merge_enabled,
                disabled_reason=post_merge_reason,
                requires_confirmation=False,
                risk_level=ActionRiskLevel.LOW,
            )
        )

        job = self.uow.jobs.get_by_id(run.active_job_id) if run.active_job_id else None
        contract_review_authorization_allowed = bool(
            job
            and run.current_stage
            in {
                OrchestrationStage.ADMITTED,
                OrchestrationStage.PREPARING_EXECUTION,
                OrchestrationStage.IMPLEMENTING,
            }
            and run.project_id == job.project_id
            and run.change_name == job.change_name
            and not self.uow.job_attempts.list_by_job(job.job_id)
            and not job.candidate_sha
            and not self.uow.reviews.get_by_job_stage(job.job_id, "CONTRACT_REVIEW")
        )
        descriptors.append(
            ActionDescriptor(
                action=OperatorActionType.AUTHORIZE_DEEPSEEK_REVIEW,
                display_name="Authorize DeepSeek Contract Review",
                description=(
                    "Authorize one bounded, direct-account DeepSeek review for the exact "
                    "OpenSpec contract. This does not authorize APPLY or merge."
                ),
                enabled=contract_review_authorization_allowed,
                disabled_reason=(
                    None
                    if contract_review_authorization_allowed
                    else "A matching admitted Run/Job without an existing contract review is required."
                ),
                requires_confirmation=True,
                confirmation_prompt=(
                    "Authorize a single direct DeepSeek CONTRACT_REVIEW spend up to the "
                    "configured maximum for this Run/Job?"
                ),
                risk_level=ActionRiskLevel.HIGH,
                parameters_schema={
                    "type": "object",
                    "required": ["max_spend_usd", "expires_at", "pricing_snapshot_id"],
                    "properties": {
                        "max_spend_usd": {"type": "string"},
                        "expires_at": {"type": "string", "format": "date-time"},
                        "pricing_snapshot_id": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
            )
        )

        candidates_repo = getattr(self.uow, "orchestration_candidates", None)
        manifests_repo = getattr(self.uow, "candidate_manifests", None)
        check_results_repo = getattr(self.uow, "check_results", None)
        reviews_repo = getattr(self.uow, "reviews", None)

        code_candidate = (
            candidates_repo.get_by_generation(run.run_id, run.current_generation)
            if job and candidates_repo
            else None
        )
        code_manifest = (
            manifests_repo.get_by_id(code_candidate.manifest_id)
            if code_candidate and code_candidate.manifest_id and manifests_repo
            else None
        )
        checks_valid, _, current_check_batch = (
            self.orchestration_service._validate_current_checks_batch(
                job,
                run,
                project,
                require_configured_checks=True,
            )
            if job and code_candidate and check_results_repo
            else (False, "Candidate or check authority is unavailable.", [])
        )
        prior_code_review = (
            reviews_repo.get_by_job_stage(job.job_id, "CODE_REVIEW")
            if job and reviews_repo
            else None
        )
        code_review_slot_open = bool(
            prior_code_review is None
            or (
                prior_code_review.status == ReviewStatus.REVIEW_RUNNING
                and prior_code_review.budget_authorization_id is None
                and prior_code_review.budget_reservation_id is None
                and prior_code_review.provider is None
            )
        )
        code_review_authorization_allowed = bool(
            job
            and code_candidate
            and code_manifest
            and code_candidate.is_frozen
            and code_candidate.run_id == run.run_id
            and code_candidate.generation == run.current_generation
            and code_candidate.candidate_sha == job.candidate_sha
            and code_candidate.candidate_sha == run.current_candidate_sha
            and code_candidate.base_sha == run.base_sha
            and code_manifest.job_id == job.job_id
            and code_manifest.candidate_sha == code_candidate.candidate_sha
            and code_manifest.manifest_hash == code_candidate.manifest_hash
            and checks_valid
            and bool(current_check_batch)
            and job.status in {JobStatus.CHECKS_PASSED, JobStatus.WAITING_CAPACITY}
            and run.project_id == job.project_id
            and run.change_name == job.change_name
            and code_review_slot_open
            and self._code_review_authorization_renewal_allowed(run, job, code_candidate)
        )
        descriptors.append(
            ActionDescriptor(
                action=OperatorActionType.AUTHORIZE_DEEPSEEK_CODE_REVIEW,
                display_name="Authorize DeepSeek Code Review",
                description=(
                    "Authorize one bounded, direct-account DeepSeek read-only review of "
                    "the exact frozen candidate. This does not authorize merge."
                ),
                enabled=code_review_authorization_allowed,
                disabled_reason=(
                    None
                    if code_review_authorization_allowed
                    else "A matching frozen candidate with passing checks and no code review is required."
                ),
                requires_confirmation=True,
                confirmation_prompt=(
                    "Authorize one direct DeepSeek REVIEW spend up to the configured "
                    "maximum for this exact candidate?"
                ),
                risk_level=ActionRiskLevel.HIGH,
                parameters_schema={
                    "type": "object",
                    "required": ["max_spend_usd", "expires_at", "pricing_snapshot_id"],
                    "properties": {
                        "max_spend_usd": {"type": "string"},
                        "expires_at": {"type": "string", "format": "date-time"},
                        "pricing_snapshot_id": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
            )
        )

        return descriptors

    def _has_stale_active_checkpoint(self, run: OrchestrationRun) -> bool:
        """Prove a narrow orphaned CONTINUE checkpoint is safe to resume.

        An active flag alone cannot authorize a second execution. This exception
        requires a completed attempt, a failed canonical CONTINUE action, and
        its matching still-EXECUTING recovery decision under an expired/released
        fence. Any live claim, active Job state, frozen candidate, pending review,
        or unresolved external action keeps CONTINUE disabled.
        """
        if (
            not run.is_active
            or run.stop_outcome is not None
            or run.current_stage
            not in {
                OrchestrationStage.IMPLEMENTING,
                OrchestrationStage.EVALUATING_ATTEMPT,
                OrchestrationStage.RUNNING_CHECKS,
            }
            or not run.active_job_id
        ):
            return False

        job = self.uow.jobs.get_by_id(run.active_job_id)
        if (
            not job
            or job.job_id != run.active_job_id
            or job.project_id != run.project_id
            or job.change_name != run.change_name
            or job.status != JobStatus.CHECKS_FAILED
        ):
            return False

        attempts = self.uow.job_attempts.list_by_job(job.job_id)
        attempts.sort(key=lambda attempt: attempt.attempt_number)
        if not attempts:
            return False
        latest_attempt = attempts[-1]
        if (
            sum(item.attempt_number == latest_attempt.attempt_number for item in attempts) != 1
            or latest_attempt.completed_at is None
            or latest_attempt.attempt_number != job.attempt_count
            or not job.candidate_sha
            or latest_attempt.end_sha != job.candidate_sha
            or run.current_candidate_sha is not None
        ):
            return False

        claim_key = f"run:{run.run_id}"
        claim_repo = getattr(self.uow, "claims", None)
        decisions_repo = getattr(self.uow, "recovery_decisions", None)
        if not claim_repo or not decisions_repo:
            return False
        claim = claim_repo.get_by_key(claim_key)
        if not claim or (claim.released_at is None and claim.lease_expires_at > utc_now()):
            return False

        decisions = decisions_repo.list_by_claim_key(claim_key)
        if not decisions:
            return False
        decision = max(decisions, key=lambda item: item.created_at)
        if (
            decision.identity_type != "RUN"
            or decision.identity_id != run.run_id
            or decision.project_id != run.project_id
            or decision.change_name != run.change_name
            or decision.source != RecoverySource.CONTROL_PLANE
            or decision.classification != RecoveryClassification.RESUME_SAFE_CHECKPOINT
            or decision.planned_action != "DRIVE_CONTINUATION"
            or decision.status != RecoveryDecisionStatus.EXECUTING
            or decision.fence_token != claim.fence_token
            or latest_attempt.started_at < decision.created_at
        ):
            return False

        action_records = self.uow.operator_actions.list_by_run(run.run_id)
        if not action_records:
            return False
        latest_action = max(action_records, key=lambda item: item.created_at)
        action_error = (latest_action.result_payload_json or {}).get("error")
        stale_fence_ack_failure = isinstance(action_error, str) and (
            "claim fence is stale, expired, or superseded" in action_error.lower()
        )
        if (
            latest_action.action_type != OperatorActionType.CONTINUE
            or latest_action.status != OperatorActionStatus.FAILED
            or latest_action.error_code != OperatorActionErrorCode.ACTION_EXECUTION_FAILED
            or latest_action.project_id != run.project_id
            or latest_action.change_name != run.change_name
            or latest_action.run_id != run.run_id
            # Older Control Plane versions persisted CONTINUE against the Run
            # only (job_id=NULL). The Run's authoritative active_job_id above,
            # the decision identity, and the attempt interval still bind that
            # action to exactly one Job. A contradictory non-null Job identity
            # is never accepted.
            or latest_action.job_id not in {None, job.job_id}
            or latest_action.precondition_stage != run.current_stage.value
            or latest_action.created_at <= decision.created_at
            or not stale_fence_ack_failure
        ):
            return False

        candidates_repo = getattr(self.uow, "orchestration_candidates", None)
        latest_candidate = (
            candidates_repo.get_latest_for_run(run.run_id) if candidates_repo else None
        )
        if latest_candidate:
            return False

        reviews_repo = getattr(self.uow, "reviews", None)
        if reviews_repo:
            for review in reviews_repo.list_by_job(job.job_id):
                if review.status in {
                    ReviewStatus.REVIEW_PENDING,
                    ReviewStatus.REVIEW_RUNNING,
                    ReviewStatus.REVIEW_TIMED_OUT,
                }:
                    return False

        external_repo = getattr(self.uow, "orchestration_external_actions", None)
        if external_repo:
            unresolved = {
                ExternalActionStatus.RESERVED,
                ExternalActionStatus.EXECUTING,
                ExternalActionStatus.FAILED,
                ExternalActionStatus.UNKNOWN,
                ExternalActionStatus.AMBIGUOUS,
            }
            if any(action.status in unresolved for action in external_repo.list_by_run(run.run_id)):
                return False
        return True

    def execute_action(self, request: OperatorActionRequest) -> OperatorActionResult:
        """Governed execution of an operator action with optimistic concurrency and idempotency."""
        sanitized_params = redact_secrets(request.parameters)

        # 1. Idempotency Check
        existing_record = self.uow.operator_actions.get_by_request_id(request.action_request_id)
        if existing_record:
            logger.info(
                f"Action request {request.action_request_id} was already executed with status {existing_record.status.value}"
            )
            return OperatorActionResult(
                action_request_id=existing_record.action_request_id,
                action_type=existing_record.action_type,
                status=existing_record.status,
                error_code=existing_record.error_code,
                summary=existing_record.summary,
                resulting_stage=OrchestrationStage(existing_record.resulting_stage)
                if existing_record.resulting_stage
                else None,
                resulting_outcome=OrchestrationStopOutcome(existing_record.resulting_outcome)
                if existing_record.resulting_outcome
                else None,
                resulting_gate=HumanGate(existing_record.resulting_gate)
                if existing_record.resulting_gate
                else None,
                evidence_reference=existing_record.evidence_reference,
                payload=existing_record.result_payload_json,
                executed_at=existing_record.created_at,
            )

        # 2. Authority & Run Lookup
        run_repo = self.uow.orchestration_runs
        if request.action_type in {
            OperatorActionType.AUTHORIZE_DEEPSEEK_REVIEW,
            OperatorActionType.AUTHORIZE_DEEPSEEK_CODE_REVIEW,
        }:
            # Serialize the combined per-Run review ceiling check with its
            # durable authorization insert. Without this row lock, simultaneous
            # CONTRACT_REVIEW and CODE_REVIEW authorizations could each observe
            # stale totals and exceed the pilot cap.
            get_for_update = getattr(run_repo, "get_for_update", None)
            run = get_for_update(request.run_id) if callable(get_for_update) else None
            if run is None:
                run = run_repo.get_by_id(request.run_id)
        else:
            run = run_repo.get_by_id(request.run_id)
        if not run:
            return self._record_and_return_rejection(
                request=request,
                run=None,
                error_code=OperatorActionErrorCode.AUTHORITY_MISMATCH,
                summary=f"Orchestration run '{request.run_id}' not found.",
                sanitized_params=sanitized_params,
            )

        if run.project_id != request.project_id or run.change_name != request.change_name:
            return self._record_and_return_rejection(
                request=request,
                run=run,
                error_code=OperatorActionErrorCode.AUTHORITY_MISMATCH,
                summary=f"Run project/change mismatch: requested ({request.project_id}/{request.change_name}) vs actual ({run.project_id}/{run.change_name}).",
                sanitized_params=sanitized_params,
            )

        # 3. Optimistic Concurrency Checks
        stale_error = self._check_optimistic_concurrency(request, run)
        if stale_error:
            return self._record_and_return_rejection(
                request=request,
                run=run,
                error_code=OperatorActionErrorCode.STALE_OPERATOR_STATE,
                summary=stale_error,
                sanitized_params=sanitized_params,
            )

        # 4. Dispatch Action
        try:
            if request.action_type in {OperatorActionType.CONTINUE, OperatorActionType.RESUME}:
                return self._execute_continue(request, run, sanitized_params)
            elif request.action_type == OperatorActionType.RETRY:
                return self._execute_retry(request, run, sanitized_params)
            elif request.action_type == OperatorActionType.REASSIGN:
                return self._execute_reassign(request, run, sanitized_params)
            elif request.action_type == OperatorActionType.RESOLVE_GATE:
                return self._execute_resolve_gate(request, run, sanitized_params)
            elif request.action_type == OperatorActionType.CANCEL:
                return self._execute_cancel(request, run, sanitized_params)
            elif request.action_type == OperatorActionType.START_PREVIEW:
                return self._execute_start_preview(request, run, sanitized_params)
            elif request.action_type == OperatorActionType.TEARDOWN_PREVIEW:
                return self._execute_teardown_preview(request, run, sanitized_params)
            elif request.action_type == OperatorActionType.RECOVER_LOCKS:
                return self._execute_recover_locks(request, run, sanitized_params)
            elif request.action_type == OperatorActionType.RECONCILE_POST_MERGE:
                return self._execute_reconcile_post_merge(request, run, sanitized_params)
            elif request.action_type == OperatorActionType.AUTHORIZE_DEEPSEEK_REVIEW:
                return self._execute_authorize_deepseek_review(request, run, sanitized_params)
            elif request.action_type == OperatorActionType.AUTHORIZE_DEEPSEEK_CODE_REVIEW:
                return self._execute_authorize_deepseek_code_review(request, run, sanitized_params)
            elif request.action_type == OperatorActionType.EXECUTE_AUTHORIZED_DEEPSEEK_CODE_REVIEW:
                return self._execute_code_review_only(request, run, sanitized_params)
            elif request.action_type == OperatorActionType.CONTINUE_AFTER_CODE_REVIEW:
                return self._execute_continue_after_code_review(request, run, sanitized_params)
            else:
                return self._record_and_return_rejection(
                    request=request,
                    run=run,
                    error_code=OperatorActionErrorCode.ACTION_NOT_ALLOWED,
                    summary=f"Unsupported action type '{request.action_type}'.",
                    sanitized_params=sanitized_params,
                )
        except Exception as exc:
            logger.error(
                f"Error executing action {request.action_type} for run {run.run_id}: {exc}",
                exc_info=True,
            )
            # Every action handler shares this failure boundary.  In particular,
            # cancellation mutates a linked Job and its run in one transaction;
            # roll that work back before the durable FAILED audit record is
            # written in a clean transaction.
            self.uow.rollback()
            persisted_run = self.uow.orchestration_runs.get_by_id(run.run_id) or run
            err_msg = redact_secrets(str(exc))
            record = self.uow.operator_actions.get_by_request_id(request.action_request_id)
            if record is None:
                record = OperatorActionRecord(
                    action_request_id=request.action_request_id,
                    project_id=request.project_id,
                    change_name=request.change_name,
                    run_id=request.run_id,
                    action_type=request.action_type,
                    actor_identity=request.actor_identity,
                    source_interface=request.source_interface,
                    precondition_stage=persisted_run.current_stage.value,
                    precondition_gate=(
                        persisted_run.human_gate.value if persisted_run.human_gate else None
                    ),
                    status=OperatorActionStatus.FAILED,
                    error_code=OperatorActionErrorCode.ACTION_EXECUTION_FAILED,
                    summary=f"Internal execution failure: {err_msg}",
                    parameters_json=sanitized_params,
                    result_payload_json={"error": err_msg},
                )
            else:
                # A fenced dispatch-intent commit can durably persist the
                # ACCEPTED action before provider I/O. Reuse that same row on
                # a later failure instead of violating action_request_id's
                # uniqueness with a second failure record.
                record.status = OperatorActionStatus.FAILED
                record.error_code = OperatorActionErrorCode.ACTION_EXECUTION_FAILED
                record.summary = f"Internal execution failure: {err_msg}"
                record.result_payload_json = {"error": err_msg}
            self.uow.operator_actions.save(record)
            self.uow.commit()

            return OperatorActionResult(
                action_request_id=request.action_request_id,
                action_type=request.action_type,
                status=OperatorActionStatus.FAILED,
                error_code=OperatorActionErrorCode.ACTION_EXECUTION_FAILED,
                summary=f"Internal execution failure: {err_msg}",
                resulting_stage=persisted_run.current_stage,
                resulting_outcome=persisted_run.stop_outcome,
                resulting_gate=persisted_run.human_gate,
            )

    def _check_optimistic_concurrency(
        self, request: OperatorActionRequest, run: OrchestrationRun
    ) -> str | None:
        """Validate expected state fields against canonical run."""
        if request.expected_stage and run.current_stage != request.expected_stage:
            return f"State conflict: expected stage '{request.expected_stage.value}', but run is in stage '{run.current_stage.value}'."
        if (
            request.expected_generation is not None
            and run.current_generation != request.expected_generation
        ):
            return f"State conflict: expected generation '{request.expected_generation}', but run is generation '{run.current_generation}'."
        if request.expected_candidate_sha and run.candidate_sha != request.expected_candidate_sha:
            return f"State conflict: expected candidate SHA '{request.expected_candidate_sha}', but actual SHA is '{run.candidate_sha}'."
        if request.expected_human_gate and run.human_gate != request.expected_human_gate:
            return f"State conflict: expected human gate '{request.expected_human_gate.value}', but actual gate is '{run.human_gate.value if run.human_gate else 'None'}'."
        return None

    def _record_and_return_rejection(
        self,
        request: OperatorActionRequest,
        run: OrchestrationRun | None,
        error_code: OperatorActionErrorCode,
        summary: str,
        sanitized_params: dict[str, Any],
    ) -> OperatorActionResult:
        """Persist structured rejection and emit event."""
        record = OperatorActionRecord(
            action_request_id=request.action_request_id,
            project_id=request.project_id,
            change_name=request.change_name,
            run_id=request.run_id,
            action_type=request.action_type,
            actor_identity=request.actor_identity,
            source_interface=request.source_interface,
            precondition_stage=run.current_stage.value if run else None,
            precondition_gate=run.human_gate.value if run and run.human_gate else None,
            status=OperatorActionStatus.REJECTED,
            error_code=error_code,
            summary=summary,
            parameters_json=sanitized_params,
            result_payload_json={"error_code": error_code.value, "summary": summary},
        )
        self.uow.operator_actions.save(record)
        self.uow.events.save(
            Event(
                event_type=EventType.OPERATOR_ACTION_REJECTED,
                payload={
                    "action_request_id": request.action_request_id,
                    "action_type": request.action_type.value,
                    "error_code": error_code.value,
                    "summary": summary,
                    "project_id": request.project_id,
                    "change_name": request.change_name,
                    "run_id": request.run_id,
                },
                timestamp=utc_now(),
            )
        )
        self.uow.commit()

        return OperatorActionResult(
            action_request_id=request.action_request_id,
            action_type=request.action_type,
            status=OperatorActionStatus.REJECTED,
            error_code=error_code,
            summary=summary,
            resulting_stage=run.current_stage if run else None,
            resulting_outcome=run.stop_outcome if run else None,
            resulting_gate=run.human_gate if run else None,
        )

    def _execute_continue(
        self,
        request: OperatorActionRequest,
        run: OrchestrationRun,
        sanitized_params: dict[str, Any],
    ) -> OperatorActionResult:
        if (run.stop_details or {}).get("code") in {
            "REVIEW_AUTHORIZATION_PENDING",
            "CODE_REVIEW_COMPLETED_REQUIRES_SEPARATE_AUTHORIZED_CONTINUATION",
            "CODE_REVIEW_COMPLETED_CHANGES_REQUIRED",
        }:
            return self._record_and_return_rejection(
                request=request,
                run=run,
                error_code=OperatorActionErrorCode.ACTION_NOT_ALLOWED,
                summary="Generic CONTINUE cannot cross an exceptional frozen-code-review gate.",
                sanitized_params=sanitized_params,
            )
        waiting_capacity_checkpoint = run.stop_outcome == OrchestrationStopOutcome.WAITING_CAPACITY
        stale_checkpoint = self._has_stale_active_checkpoint(run)
        if (
            run.is_active
            and not sanitized_params.get("force")
            and not waiting_capacity_checkpoint
            and not stale_checkpoint
        ):
            return self._record_and_return_rejection(
                request=request,
                run=run,
                error_code=OperatorActionErrorCode.ACTION_NOT_ALLOWED,
                summary="Cannot continue run: execution is already active.",
                sanitized_params=sanitized_params,
            )

        if (
            run.current_stage == OrchestrationStage.PR_PREPARED
            or run.stop_outcome == OrchestrationStopOutcome.CANCELLED
        ):
            return self._record_and_return_rejection(
                request=request,
                run=run,
                error_code=OperatorActionErrorCode.ACTION_NOT_ALLOWED,
                summary=f"Cannot continue run in terminal or cancelled state ({run.stop_outcome.value if run.stop_outcome else run.current_stage.value}).",
                sanitized_params=sanitized_params,
            )

        # Clear stop outcome and human gate upon explicit operator continuation
        if (
            run.stop_outcome == OrchestrationStopOutcome.NEEDS_HUMAN
            or run.human_gate == HumanGate.NEEDS_HUMAN
            or sanitized_params.get("force")
        ):
            run.stop_outcome = None
            run.human_gate = None
            run.is_active = True
            run.stop_reason = None
            run.stop_details = {}
            if run.active_job_id:
                job = self.uow.jobs.get_by_id(run.active_job_id)
                if job:
                    if job.base_sha and job.base_sha != run.base_sha:
                        run.base_sha = job.base_sha
                    job.status = JobStatus.RUNNING
                    job.continuation_decision = None
                    job.escalation_reason = None
                    self.uow.jobs.save(job)
            if run.current_stage in {
                OrchestrationStage.EVALUATING_ATTEMPT,
                OrchestrationStage.FREEZING_CANDIDATE,
                OrchestrationStage.RUNNING_CHECKS,
            }:
                run.resumable_stage = OrchestrationStage.IMPLEMENTING
                run.current_stage = OrchestrationStage.IMPLEMENTING
            self.uow.orchestration_runs.save(run)
            self.uow.commit()

        # Drive run continuation through canonical RecoveryConvergenceService
        self.recovery_convergence_service.request_run_continuation(
            run.run_id,
            source=RecoverySource.CONTROL_PLANE,
            force=True,
            drive_admitted=True,
        )
        resumed_run = self.uow.orchestration_runs.get_by_id(run.run_id) or run
        linked_job = (
            self.uow.jobs.get_by_id(resumed_run.active_job_id)
            if resumed_run.active_job_id
            else None
        )
        job_status = linked_job.status.value if linked_job else None
        continuation_active = bool(
            resumed_run.is_active
            and linked_job
            and linked_job.status
            in {
                JobStatus.RUNNING,
                JobStatus.CHECKS_RUNNING,
                JobStatus.REVIEW_RUNNING,
                JobStatus.AUDIT_RUNNING,
            }
        )
        run_active = bool(resumed_run.is_active)
        outcome = resumed_run.stop_outcome.value if resumed_run.stop_outcome else "NONE"
        job_result = job_status or "NO_LINKED_JOB"
        summary = (
            f"Continue request processed; persisted run_active={str(run_active).lower()}, "
            f"stage={resumed_run.current_stage.value}, outcome={outcome}, "
            f"linked_job_status={job_result}, "
            f"execution_active={str(continuation_active).lower()}."
        )
        record = OperatorActionRecord(
            action_request_id=request.action_request_id,
            project_id=request.project_id,
            change_name=request.change_name,
            run_id=request.run_id,
            action_type=request.action_type,
            actor_identity=request.actor_identity,
            source_interface=request.source_interface,
            precondition_stage=run.current_stage.value,
            precondition_gate=run.human_gate.value if run.human_gate else None,
            status=OperatorActionStatus.COMPLETED,
            summary=summary,
            resulting_stage=resumed_run.current_stage.value,
            resulting_outcome=resumed_run.stop_outcome.value if resumed_run.stop_outcome else None,
            resulting_gate=resumed_run.human_gate.value if resumed_run.human_gate else None,
            parameters_json=sanitized_params,
            result_payload_json={
                "request_processed": True,
                "run_active": run_active,
                "execution_active": continuation_active,
                "resulting_stage": resumed_run.current_stage.value,
                "resulting_outcome": resumed_run.stop_outcome.value
                if resumed_run.stop_outcome
                else None,
                "linked_job_status": job_status,
            },
        )
        self.uow.operator_actions.save(record)
        self.uow.events.save(
            Event(
                event_type=EventType.OPERATOR_ACTION_EXECUTED,
                payload={
                    "action_request_id": request.action_request_id,
                    "action_type": request.action_type.value,
                    "actor_identity": request.actor_identity,
                    "project_id": request.project_id,
                    "change_name": request.change_name,
                    "run_id": request.run_id,
                    "stage": resumed_run.current_stage.value,
                    "run_active": run_active,
                    "execution_active": continuation_active,
                    "linked_job_status": job_status,
                },
                timestamp=utc_now(),
            )
        )
        self.uow.commit()

        return OperatorActionResult(
            action_request_id=request.action_request_id,
            action_type=request.action_type,
            status=OperatorActionStatus.COMPLETED,
            summary=summary,
            resulting_stage=resumed_run.current_stage,
            resulting_outcome=resumed_run.stop_outcome,
            resulting_gate=resumed_run.human_gate,
            payload={
                "request_processed": True,
                "run_active": run_active,
                "execution_active": continuation_active,
                "resulting_stage": resumed_run.current_stage.value,
                "resulting_outcome": resumed_run.stop_outcome.value
                if resumed_run.stop_outcome
                else None,
                "linked_job_status": job_status,
            },
        )

    def _execute_authorize_deepseek_review(
        self,
        request: OperatorActionRequest,
        run: OrchestrationRun,
        sanitized_params: dict[str, Any],
    ) -> OperatorActionResult:
        """Persist a one-use contract-review spend authorization after non-inference checks."""
        job = self.uow.jobs.get_by_id(run.active_job_id) if run.active_job_id else None
        if (
            not job
            or run.current_stage
            not in {
                OrchestrationStage.ADMITTED,
                OrchestrationStage.PREPARING_EXECUTION,
                OrchestrationStage.IMPLEMENTING,
            }
            or run.active_job_id != job.job_id
            or run.project_id != job.project_id
            or run.change_name != job.change_name
            or bool(self.uow.job_attempts.list_by_job(job.job_id))
            or bool(job.candidate_sha)
            or self.uow.reviews.get_by_job_stage(job.job_id, "CONTRACT_REVIEW")
        ):
            return self._record_and_return_rejection(
                request=request,
                run=run,
                error_code=OperatorActionErrorCode.ACTION_NOT_ALLOWED,
                summary="DeepSeek spend authorization is only available before APPLY for the exact active Run/Job.",
                sanitized_params=sanitized_params,
            )
        prior = [
            action
            for action in self.uow.operator_actions.list_by_run(run.run_id)
            if action.action_type == OperatorActionType.AUTHORIZE_DEEPSEEK_REVIEW
            and action.status == OperatorActionStatus.COMPLETED
        ]
        if prior:
            return self._record_and_return_rejection(
                request=request,
                run=run,
                error_code=OperatorActionErrorCode.ACTION_ALREADY_COMPLETED,
                summary="A DeepSeek CONTRACT_REVIEW authorization already exists for this Run.",
                sanitized_params=sanitized_params,
            )
        if set(sanitized_params) != {"max_spend_usd", "expires_at", "pricing_snapshot_id"}:
            return self._record_and_return_rejection(
                request=request,
                run=run,
                error_code=OperatorActionErrorCode.INVALID_ACTION_PARAMETERS,
                summary="Authorization requires exactly max_spend_usd, expires_at, and pricing_snapshot_id.",
                sanitized_params=sanitized_params,
            )
        try:
            max_spend = Decimal(str(sanitized_params["max_spend_usd"]))
            expires_at = datetime.fromisoformat(str(sanitized_params["expires_at"]))
            if expires_at.tzinfo is None or max_spend <= 0:
                raise ValueError("invalid authorization bound")
        except (InvalidOperation, ValueError, TypeError):
            return self._record_and_return_rejection(
                request=request,
                run=run,
                error_code=OperatorActionErrorCode.INVALID_ACTION_PARAMETERS,
                summary="Authorization amount or expiry is invalid.",
                sanitized_params=sanitized_params,
            )
        now = utc_now()
        if expires_at <= now or (expires_at - now).total_seconds() > 3600:
            return self._record_and_return_rejection(
                request=request,
                run=run,
                error_code=OperatorActionErrorCode.INVALID_ACTION_PARAMETERS,
                summary="Contract-review spend authorization must expire within one hour.",
                sanitized_params=sanitized_params,
            )

        project = self.uow.projects.get_by_id(run.project_id)
        if not project:
            return self._record_and_return_rejection(
                request=request,
                run=run,
                error_code=OperatorActionErrorCode.AUTHORITY_MISMATCH,
                summary="Project binding is unavailable for spend authorization.",
                sanitized_params=sanitized_params,
            )
        app_config = load_config()
        project_config = app_config.projects.get(project.project_id) or ProjectConfig(
            repository=project.repository,
            base_branch=project.base_branch,
            openspec_path=project.openspec_path,
            implementer=project.implementer,
            reviewer=project.reviewer,
            external_providers_allowed=project.external_providers_allowed,
        )
        provider_config = app_config.providers.get("deepseek")
        configured_max = (
            provider_config.budget.get("maximum_contract_review_usd")
            if provider_config and isinstance(provider_config.budget, dict)
            else None
        )
        if configured_max is not None:
            try:
                configured_max = Decimal(str(configured_max))
            except Exception:
                configured_max = Decimal("0")
        if configured_max is not None and max_spend > configured_max:
            return self._record_and_return_rejection(
                request=request,
                run=run,
                error_code=OperatorActionErrorCode.BUDGET_BLOCKED,
                summary="Requested spend exceeds the configured contract-review ceiling.",
                sanitized_params=sanitized_params,
            )
        review_budget = provider_config.budget if provider_config else {}
        if not self._deepseek_review_total_within_limit(run, review_budget, max_spend):
            return self._record_and_return_rejection(
                request=request,
                run=run,
                error_code=OperatorActionErrorCode.BUDGET_BLOCKED,
                summary="Combined DeepSeek review authorizations exceed the configured owner limit or are ambiguous.",
                sanitized_params=sanitized_params,
            )
        try:
            profile = resolve_stage_profile(
                project_config, OpenSpecStage.CONTRACT_REVIEW, app_config=app_config
            )
            from minime.adapters.provider_adapter import get_provider_adapter

            adapter = get_provider_adapter("deepseek", app_config)
            supported, _ = __import__("asyncio").run(
                adapter.check_model_supported(profile.model, effort=profile.effort)
            )
            account_fingerprint = getattr(adapter, "account_fingerprint", None)
            snapshot = self.uow.pricing_snapshots.get_by_id(
                str(sanitized_params["pricing_snapshot_id"])
            )
        except Exception:
            supported = False
            account_fingerprint = None
            snapshot = None
            profile = None
        if (
            not profile
            or profile.provider != "deepseek"
            or not supported
            or not account_fingerprint
            or not snapshot
            or not snapshot.is_verified
            or snapshot.provider != "deepseek"
            or snapshot.account_fingerprint != account_fingerprint
            or snapshot.canonical_model_identity != profile.model
            or snapshot.billing_origin != "deepseek_direct"
            or snapshot.currency != "USD"
        ):
            return self._record_and_return_rejection(
                request=request,
                run=run,
                error_code=OperatorActionErrorCode.BUDGET_BLOCKED,
                summary="Direct DeepSeek model, account, and verified price evidence is unavailable or mismatched.",
                sanitized_params=sanitized_params,
            )

        authorization = {
            "provider": "deepseek",
            "account_fingerprint": account_fingerprint,
            "model": profile.model,
            "stage": "CONTRACT_REVIEW",
            "billing_origin": "deepseek_direct",
            "pricing_snapshot_id": snapshot.snapshot_id,
            "run_id": run.run_id,
            "job_id": job.job_id,
            "max_spend_usd": str(max_spend),
            "expires_at": expires_at.isoformat(),
            "authorized_by": request.actor_identity,
            "action_request_id": request.action_request_id,
        }
        record = OperatorActionRecord(
            action_request_id=request.action_request_id,
            project_id=run.project_id,
            change_name=run.change_name,
            run_id=run.run_id,
            job_id=job.job_id,
            action_type=request.action_type,
            actor_identity=request.actor_identity,
            source_interface=request.source_interface,
            precondition_stage=run.current_stage.value,
            status=OperatorActionStatus.COMPLETED,
            summary="One-use DeepSeek Direct CONTRACT_REVIEW budget authorized; APPLY and merge remain separate gates.",
            evidence_reference=snapshot.snapshot_id,
            parameters_json=sanitized_params,
            result_payload_json={"authorization": authorization},
        )
        self.uow.operator_actions.save(record)
        self.uow.events.save(
            Event(
                event_type=EventType.OPERATOR_ACTION_EXECUTED,
                payload={
                    "action_request_id": request.action_request_id,
                    "action_type": request.action_type.value,
                    "run_id": run.run_id,
                    "job_id": job.job_id,
                    "provider": "deepseek",
                    "stage": "CONTRACT_REVIEW",
                    "model": profile.model,
                    "authorization_id": request.action_request_id,
                },
                timestamp=now,
            )
        )
        self.uow.commit()
        return OperatorActionResult(
            action_request_id=request.action_request_id,
            action_type=request.action_type,
            status=OperatorActionStatus.COMPLETED,
            summary=record.summary,
            resulting_stage=run.current_stage,
            resulting_outcome=run.stop_outcome,
            resulting_gate=run.human_gate,
            evidence_reference=snapshot.snapshot_id,
            payload={
                "provider": "deepseek",
                "stage": "CONTRACT_REVIEW",
                "maximum_usd": str(max_spend),
            },
        )

    def _execute_code_review_only(
        self,
        request: OperatorActionRequest,
        run: OrchestrationRun,
        sanitized_params: dict[str, Any],
    ) -> OperatorActionResult:
        """Dispatch one explicitly authorized CODE_REVIEW under the Run fence only."""
        if set(sanitized_params) != {"authorization_id"}:
            return self._record_and_return_rejection(
                request=request,
                run=run,
                error_code=OperatorActionErrorCode.INVALID_ACTION_PARAMETERS,
                summary="Review dispatch requires exactly one authorization_id.",
                sanitized_params=sanitized_params,
            )
        if (
            (run.stop_details or {}).get("code") != "REVIEW_AUTHORIZATION_PENDING"
            or run.current_stage
            not in {
                OrchestrationStage.FREEZING_CANDIDATE,
                OrchestrationStage.COMPLEMENTARY_REVIEW,
            }
            or run.is_active
        ):
            return self._record_and_return_rejection(
                request=request,
                run=run,
                error_code=OperatorActionErrorCode.ACTION_NOT_ALLOWED,
                summary="CODE_REVIEW dispatch requires the inactive review-authorization hold.",
                sanitized_params=sanitized_params,
            )

        job = self.uow.jobs.get_by_id(run.active_job_id) if run.active_job_id else None
        project = self.uow.projects.get_by_id(run.project_id)
        candidates_repo = getattr(self.uow, "orchestration_candidates", None)
        candidate = (
            candidates_repo.get_by_generation(run.run_id, run.current_generation)
            if candidates_repo
            else None
        )
        manifest = (
            self.uow.candidate_manifests.get_by_id(candidate.manifest_id)
            if candidate and candidate.manifest_id
            else None
        )
        authorization_id = str(sanitized_params["authorization_id"])
        authorization_record = self.uow.operator_actions.get_by_request_id(authorization_id)
        authorization = (
            authorization_record.result_payload_json.get("authorization", {})
            if authorization_record
            else {}
        )
        checks_valid, checks_error, checks = (
            self.orchestration_service._validate_current_checks_batch(
                job,
                run,
                project,
                require_configured_checks=True,
            )
            if job and project
            else (False, "Project or Job is unavailable.", [])
        )
        from minime.services.workspace_guard import is_binding_fully_valid

        binding_repo = getattr(self.uow, "project_managed_repository_bindings", None)
        binding = binding_repo.get_by_project_id(run.project_id) if binding_repo else None

        if (
            not job
            or not project
            or not candidate
            or not manifest
            or not candidate.is_frozen
            or candidate.run_id != run.run_id
            or candidate.generation != run.current_generation
            or candidate.candidate_sha != job.candidate_sha
            or candidate.candidate_sha != run.current_candidate_sha
            or candidate.base_sha != job.base_sha
            or candidate.base_sha != run.base_sha
        ):
            return self._record_and_return_rejection(
                request=request,
                run=run,
                error_code=OperatorActionErrorCode.AUTHORITY_MISMATCH,
                summary="Frozen candidate identity is incomplete or contradictory.",
                sanitized_params=sanitized_params,
            )
        if (
            manifest.job_id != job.job_id
            or manifest.candidate_sha != candidate.candidate_sha
            or manifest.manifest_hash != candidate.manifest_hash
            or not checks_valid
            or not checks
            or job.status != JobStatus.CHECKS_PASSED
            or job.project_id != run.project_id
            or job.change_name != run.change_name
            or run.active_job_id != job.job_id
            or not is_binding_fully_valid(binding)
            or authorization_record is None
            or authorization_record.action_type != OperatorActionType.AUTHORIZE_DEEPSEEK_CODE_REVIEW
            or authorization_record.status != OperatorActionStatus.COMPLETED
            or authorization_record.project_id != run.project_id
            or authorization_record.change_name != run.change_name
            or authorization_record.run_id != run.run_id
            or authorization_record.job_id != job.job_id
            or authorization.get("run_id") != run.run_id
            or authorization.get("job_id") != job.job_id
            or authorization.get("candidate_sha") != candidate.candidate_sha
            or authorization.get("base_sha") != candidate.base_sha
            or authorization.get("generation") != candidate.generation
            or authorization.get("manifest_id") != manifest.manifest_id
            or authorization.get("manifest_hash") != manifest.manifest_hash
            or authorization.get("action_request_id") != authorization_id
            or not authorization.get("account_fingerprint")
            or not authorization.get("pricing_snapshot_id")
            or not authorization.get("max_spend_usd")
        ):
            return self._record_and_return_rejection(
                request=request,
                run=run,
                error_code=OperatorActionErrorCode.AUTHORITY_MISMATCH,
                summary=(
                    "Review authorization, current configured check batch, or managed binding "
                    f"is invalid: {checks_error or 'identity mismatch'}."
                ),
                sanitized_params=sanitized_params,
            )
        if any(
            reservation.authorization_id == authorization_id
            for reservation in self.uow.budget_reservations.list_by_project(run.project_id)
        ):
            return self._record_and_return_rejection(
                request=request,
                run=run,
                error_code=OperatorActionErrorCode.ACTION_ALREADY_COMPLETED,
                summary="The one-shot review authorization has already been consumed.",
                sanitized_params=sanitized_params,
            )

        from minime.services.recovery_convergence_service import OperationalHeartbeat

        try:
            worktree_manager = self._worktree_manager_for_bound_project(
                run.project_id, project=project
            )
            worktree_path = worktree_manager.worktree_path(job.job_id, project_id=job.project_id)
        except Exception as exc:
            return self._record_and_return_rejection(
                request=request,
                run=run,
                error_code=OperatorActionErrorCode.AUTHORITY_MISMATCH,
                summary=f"Bound managed repository proof failed: {type(exc).__name__}.",
                sanitized_params=sanitized_params,
            )
        ownership_repo = getattr(self.uow, "orchestration_worktree_ownerships", None)
        ownership = ownership_repo.get_by_job_id(job.job_id) if ownership_repo else None
        if not ownership:
            return self._record_and_return_rejection(
                request=request,
                run=run,
                error_code=OperatorActionErrorCode.AUTHORITY_MISMATCH,
                summary="Durable frozen-candidate worktree ownership is unavailable.",
                sanitized_params=sanitized_params,
            )
        try:
            import asyncio

            asyncio.run(
                worktree_manager._verify_frozen_candidate_worktree_adoption(
                    path=worktree_path,
                    job_id=job.job_id,
                    project_id=project.project_id,
                    run_id=run.run_id,
                    change_name=run.change_name,
                    ownership=ownership,
                )
            )
        except Exception as exc:
            return self._record_and_return_rejection(
                request=request,
                run=run,
                error_code=OperatorActionErrorCode.AUTHORITY_MISMATCH,
                summary=f"Frozen candidate worktree adoption proof failed: {type(exc).__name__}.",
                sanitized_params=sanitized_params,
            )

        context = self.recovery_convergence_service.acquire_claim(f"run:{run.run_id}")
        if not context:
            return self._record_and_return_rejection(
                request=request,
                run=run,
                error_code=OperatorActionErrorCode.RECOVERY_REQUIRED,
                summary="Run claim is held by another live recovery owner.",
                sanitized_params=sanitized_params,
            )
        cycle_id = generate_uuid()
        decision = RecoveryDecision(
            cycle_id=cycle_id,
            claim_key=context.claim_key,
            identity_type="RUN",
            identity_id=run.run_id,
            project_id=run.project_id,
            change_name=run.change_name,
            source=RecoverySource.CONTROL_PLANE,
            prior_checkpoint={
                "stage": run.current_stage.value,
                "gate": "REVIEW_AUTHORIZATION_PENDING",
                "candidate_sha": candidate.candidate_sha,
                "generation": candidate.generation,
                "manifest_id": manifest.manifest_id,
                "manifest_hash": manifest.manifest_hash,
            },
            observation_refs={
                "authorization_id": authorization_id,
                "check_result_ids": [item.result_id for item in checks],
            },
            classification=RecoveryClassification.RESUME_SAFE_CHECKPOINT,
            planned_action="DISPATCH_FROZEN_CODE_REVIEW",
            fence_token=context.fence_token,
            status=RecoveryDecisionStatus.EXECUTING,
        )
        self.uow.recovery_decisions.create_decision(decision)
        action_record = OperatorActionRecord(
            action_request_id=request.action_request_id,
            project_id=run.project_id,
            change_name=run.change_name,
            run_id=run.run_id,
            job_id=job.job_id,
            action_type=request.action_type,
            actor_identity=request.actor_identity,
            source_interface=request.source_interface,
            precondition_stage=run.current_stage.value,
            precondition_gate=run.human_gate.value if run.human_gate else None,
            status=OperatorActionStatus.ACCEPTED,
            summary="Fenced one-shot CODE_REVIEW dispatch accepted; provider call remains pending.",
            parameters_json=sanitized_params,
            result_payload_json={"recovery_decision_id": decision.decision_id},
        )
        self.uow.operator_actions.save(action_record)

        service = self.deepseek_code_review_service
        if service is None:
            from minime.services.deepseek_code_review_service import DeepSeekCodeReviewService

            service = DeepSeekCodeReviewService(
                self.uow,
                health_service=self.provider_health_service,
            )
        heartbeat = OperationalHeartbeat(
            recovery_service=self.recovery_convergence_service,
            claim_context=context,
            interval_seconds=max(1, self.recovery_convergence_service.heartbeat_seconds),
            lease_seconds=self.recovery_convergence_service.lease_seconds,
        )
        try:
            with heartbeat:
                result = __import__("asyncio").run(
                    service.review_candidate(
                        project=project,
                        run=run,
                        job=job,
                        candidate=candidate,
                        manifest=manifest,
                        candidate_worktree=worktree_path,
                        authorship_evidence={},
                        authorization_id=authorization_id,
                        claim_context=context,
                        dispatch_action_key=f"deepseek-code-review:{authorization_id}",
                    )
                )
            if heartbeat.heartbeat_failed:
                raise RuntimeError("CODE_REVIEW_HEARTBEAT_RENEWAL_FAILED")
            if not heartbeat.stopped_cleanly or heartbeat.is_alive or heartbeat.is_renewing:
                raise RuntimeError("CODE_REVIEW_HEARTBEAT_DID_NOT_STOP_CLEANLY")
            if not self.recovery_convergence_service.validate_claim(context):
                raise RuntimeError("CODE_REVIEW_RUN_FENCE_LOST")

            from minime.domain.models import validate_claim_context_authoritative

            validate_claim_context_authoritative(self.uow, context, for_update=True)
            persisted_run = self.uow.orchestration_runs.get_by_id(run.run_id)
            persisted_job = self.uow.jobs.get_by_id(job.job_id)
            review = self.uow.reviews.get_by_id(result.review_id) if result.review_id else None
            if result.accepted and review and review.status == ReviewStatus.REVIEW_COMPLETED:
                persisted_run.current_stage = OrchestrationStage.COMPLEMENTARY_REVIEW
                persisted_run.resumable_stage = OrchestrationStage.COMPLEMENTARY_REVIEW
                persisted_run.is_active = False
                persisted_run.stop_outcome = OrchestrationStopOutcome.NEEDS_HUMAN
                persisted_run.human_gate = HumanGate.NEEDS_HUMAN
                if review.verdict == ReviewVerdict.READY_TO_MERGE:
                    gate_code = "CODE_REVIEW_COMPLETED_REQUIRES_SEPARATE_AUTHORIZED_CONTINUATION"
                    reason = "Independent review completed; a separate governed continuation is required."
                else:
                    gate_code = "CODE_REVIEW_COMPLETED_CHANGES_REQUIRED"
                    reason = "Independent review requires changes; frozen candidate and findings are preserved."
                persisted_run.stop_reason = reason
                persisted_run.stop_details = {
                    "code": gate_code,
                    "review_id": review.review_id,
                    "review_verdict": review.verdict.value if review.verdict else None,
                    "candidate_sha": candidate.candidate_sha,
                    "base_sha": candidate.base_sha,
                    "generation": candidate.generation,
                    "manifest_id": manifest.manifest_id,
                    "manifest_hash": manifest.manifest_hash,
                }
                persisted_job.status = JobStatus.CHECKS_PASSED
                action_record.status = OperatorActionStatus.COMPLETED
                action_record.summary = (
                    "Fenced DeepSeek CODE_REVIEW completed and was durably finalized."
                )
                action_record.evidence_reference = review.review_id
                action_record.result_payload_json = {
                    "review_id": review.review_id,
                    "candidate_sha": candidate.candidate_sha,
                    "verdict": review.verdict.value if review.verdict else None,
                    "dispatch_action_key": f"deepseek-code-review:{authorization_id}",
                    "recovery_decision_id": decision.decision_id,
                }
                decision.status = RecoveryDecisionStatus.COMPLETED
                decision.result_payload = action_record.result_payload_json
            else:
                persisted_run = persisted_run or run
                persisted_job = persisted_job or job
                persisted_run.is_active = False
                persisted_run.stop_outcome = OrchestrationStopOutcome.NEEDS_HUMAN
                persisted_run.human_gate = HumanGate.NEEDS_HUMAN
                persisted_run.stop_reason = result.reason or "CODE_REVIEW_FAILED_CLOSED"
                persisted_run.stop_details = {
                    "code": "CODE_REVIEW_DISPATCH_AMBIGUOUS"
                    if result.reason and "AMBIGUOUS" in result.reason
                    else "CODE_REVIEW_FAILED_CLOSED",
                    "reason": result.reason,
                    "candidate_sha": candidate.candidate_sha,
                    "generation": candidate.generation,
                }
                action_record.status = OperatorActionStatus.BLOCKED
                action_record.summary = "CODE_REVIEW did not complete; durable state is preserved and no blind repeat is allowed."
                action_record.result_payload_json = {
                    "reason": result.reason,
                    "review_id": result.review_id,
                    "recovery_decision_id": decision.decision_id,
                }
                decision.status = RecoveryDecisionStatus.BLOCKED
                decision.reason_code = "CODE_REVIEW_FAILED_OR_AMBIGUOUS"
                decision.result_payload = action_record.result_payload_json
            self.uow.orchestration_runs.save(persisted_run)
            self.uow.jobs.save(persisted_job)
            self.uow.operator_actions.save(action_record)
            self.uow.recovery_decisions.update_decision(decision, claim_context=context)
            self.uow.commit()
        except Exception:
            self.uow.rollback()
            raise
        finally:
            if not heartbeat.is_alive and not heartbeat.is_renewing:
                self.recovery_convergence_service.release_claim(context)

        resulting_run = self.uow.orchestration_runs.get_by_id(run.run_id) or run
        return OperatorActionResult(
            action_request_id=request.action_request_id,
            action_type=request.action_type,
            status=action_record.status,
            error_code=(
                OperatorActionErrorCode.ACTION_EXECUTION_FAILED
                if action_record.status != OperatorActionStatus.COMPLETED
                else None
            ),
            summary=action_record.summary,
            resulting_stage=resulting_run.current_stage,
            resulting_outcome=resulting_run.stop_outcome,
            resulting_gate=resulting_run.human_gate,
            evidence_reference=action_record.evidence_reference,
            payload=action_record.result_payload_json,
        )

    @staticmethod
    def _expected_code_review_reservation_key(run, job, candidate, authorization_id: str) -> str:
        from minime.services.deepseek_code_review_service import _reservation_key

        return (
            _reservation_key(
                run.run_id, job.job_id, candidate.candidate_sha, candidate.manifest_hash
            )
            + f":{authorization_id}"
        )

    def _execute_continue_after_code_review(
        self,
        request: OperatorActionRequest,
        run: OrchestrationRun,
        sanitized_params: dict[str, Any],
    ) -> OperatorActionResult:
        """Continue only a completed, exact READY_TO_MERGE review through existing gates."""
        required = {"review_id", "candidate_sha", "manifest_hash"}
        if set(sanitized_params) != required:
            return self._record_and_return_rejection(
                request=request,
                run=run,
                error_code=OperatorActionErrorCode.INVALID_ACTION_PARAMETERS,
                summary="Post-review continuation requires exact review, candidate, and manifest identities.",
                sanitized_params=sanitized_params,
            )
        if (
            run.is_active
            or run.stop_outcome != OrchestrationStopOutcome.NEEDS_HUMAN
            or (run.stop_details or {}).get("code")
            != "CODE_REVIEW_COMPLETED_REQUIRES_SEPARATE_AUTHORIZED_CONTINUATION"
            or run.current_stage != OrchestrationStage.COMPLEMENTARY_REVIEW
            or run.resumable_stage != OrchestrationStage.COMPLEMENTARY_REVIEW
        ):
            return self._record_and_return_rejection(
                request=request,
                run=run,
                error_code=OperatorActionErrorCode.ACTION_NOT_ALLOWED,
                summary="Continuation is available only from the completed review checkpoint.",
                sanitized_params=sanitized_params,
            )

        job = self.uow.jobs.get_by_id(run.active_job_id) if run.active_job_id else None
        project = self.uow.projects.get_by_id(run.project_id)
        candidates = getattr(self.uow, "orchestration_candidates", None)
        candidate = (
            candidates.get_by_generation(run.run_id, run.current_generation) if candidates else None
        )
        manifests = getattr(self.uow, "candidate_manifests", None)
        manifest = (
            manifests.get_by_id(candidate.manifest_id)
            if candidate and candidate.manifest_id and manifests
            else None
        )
        review = self.uow.reviews.get_by_id(str(sanitized_params["review_id"]))
        authorization = (
            self.uow.operator_actions.get_by_request_id(review.budget_authorization_id)
            if review and review.budget_authorization_id
            else None
        )
        reservation = (
            self.uow.budget_reservations.get_by_id(review.budget_reservation_id)
            if review and review.budget_reservation_id
            else None
        )
        review_action_key = (
            f"deepseek-code-review:{review.budget_authorization_id}"
            if review and review.budget_authorization_id
            else None
        )
        review_dispatch = (
            self.uow.orchestration_external_actions.get_by_action_key(review_action_key)
            if review_action_key
            else None
        )
        review_attempts = (
            self.uow.external_action_attempts.list_by_action_key(review_action_key)
            if review_action_key
            else []
        )
        review_execution_action = next(
            (
                action
                for action in self.uow.operator_actions.list_by_run(run.run_id)
                if action.action_type == OperatorActionType.EXECUTE_AUTHORIZED_DEEPSEEK_CODE_REVIEW
                and action.status == OperatorActionStatus.COMPLETED
                and action.job_id == (job.job_id if job else None)
                and action.evidence_reference == (review.review_id if review else None)
                and action.result_payload_json.get("review_id")
                == (review.review_id if review else None)
                and action.result_payload_json.get("dispatch_action_key") == review_action_key
            ),
            None,
        )
        review_decision_id = (
            review_execution_action.result_payload_json.get("recovery_decision_id")
            if review_execution_action
            else None
        )
        review_recovery_decision = (
            self.uow.recovery_decisions.get_by_id(review_decision_id)
            if review_decision_id
            else None
        )
        authorization_payload = (
            authorization.result_payload_json.get("authorization", {}) if authorization else {}
        )
        if (
            not job
            or not project
            or not candidate
            or not manifest
            or not candidate.is_frozen
            or job.job_id != run.active_job_id
            or job.project_id != run.project_id
            or job.change_name != run.change_name
            or job.status != JobStatus.CHECKS_PASSED
            or candidate.run_id != run.run_id
            or candidate.generation != run.current_generation
            or candidate.candidate_sha != str(sanitized_params["candidate_sha"])
            or candidate.candidate_sha != job.candidate_sha
            or candidate.candidate_sha != run.current_candidate_sha
            or candidate.base_sha != run.base_sha
            or candidate.base_sha != job.base_sha
            or candidate.manifest_hash != str(sanitized_params["manifest_hash"])
            or manifest.job_id != job.job_id
            or manifest.candidate_sha != candidate.candidate_sha
            or manifest.manifest_hash != candidate.manifest_hash
            or not review
            or review.review_id != str(sanitized_params["review_id"])
            or review.status != ReviewStatus.REVIEW_COMPLETED
            or review.verdict != ReviewVerdict.READY_TO_MERGE
            or review.review_stage != "CODE_REVIEW"
            or review.reviewer_role != "deepseek"
            or review.provider != "deepseek"
            or review.billing_origin != "deepseek_direct"
            or review.project_id != run.project_id
            or review.change_name != run.change_name
            or review.job_id != job.job_id
            or review.orchestration_run_id != run.run_id
            or review.candidate_sha != candidate.candidate_sha
            or review.base_sha != candidate.base_sha
            or review.candidate_generation != candidate.generation
            or review.manifest_id != manifest.manifest_id
            or review.manifest_hash != manifest.manifest_hash
            or not reservation
            or not authorization
            or authorization.action_type != OperatorActionType.AUTHORIZE_DEEPSEEK_CODE_REVIEW
            or authorization.status != OperatorActionStatus.COMPLETED
            or authorization.project_id != run.project_id
            or authorization.change_name != run.change_name
            or authorization.run_id != run.run_id
            or authorization.job_id != job.job_id
            or authorization.result_payload_json.get("authorization", {}).get("provider")
            != "deepseek"
            or authorization.result_payload_json.get("authorization", {}).get("stage") != "REVIEW"
            or authorization.result_payload_json.get("authorization", {}).get("billing_origin")
            != "deepseek_direct"
            or authorization_payload.get("account_fingerprint") != review.account_fingerprint
            or authorization_payload.get("model") != review.reviewer_model
            or authorization_payload.get("pricing_snapshot_id") != reservation.pricing_snapshot_id
            or Decimal(str(authorization_payload.get("max_spend_usd", "0")))
            < reservation.reserved_amount_usd
            or authorization.result_payload_json.get("authorization", {}).get("candidate_sha")
            != candidate.candidate_sha
            or authorization.result_payload_json.get("authorization", {}).get("base_sha")
            != candidate.base_sha
            or authorization.result_payload_json.get("authorization", {}).get("generation")
            != candidate.generation
            or authorization.result_payload_json.get("authorization", {}).get("manifest_id")
            != manifest.manifest_id
            or authorization.result_payload_json.get("authorization", {}).get("manifest_hash")
            != manifest.manifest_hash
            or reservation.authorization_id != authorization.action_request_id
            or reservation.project_id != run.project_id
            or reservation.run_id != run.run_id
            or reservation.job_id != job.job_id
            or reservation.provider != "deepseek"
            or reservation.account_fingerprint != review.account_fingerprint
            or reservation.canonical_model_identity != review.reviewer_model
            or reservation.stage != "REVIEW"
            or reservation.billing_origin != "deepseek_direct"
            or reservation.status != "SETTLED"
            or reservation.idempotency_key
            != self._expected_code_review_reservation_key(
                run, job, candidate, review.budget_authorization_id
            )
            or not review_dispatch
            or review_dispatch.status != ExternalActionStatus.COMPLETED
            or review_dispatch.remote_identifier != review.review_id
            or len(review_attempts) != 1
            or review_attempts[0].status != "COMPLETED"
            or review_attempts[0].attempt_number != 1
            or review_attempts[0].claim_key != f"run:{run.run_id}"
            or review_attempts[0].fence_token <= 0
            or not review_execution_action
            or not review_recovery_decision
            or review_recovery_decision.status != RecoveryDecisionStatus.COMPLETED
            or review_recovery_decision.identity_type != "RUN"
            or review_recovery_decision.identity_id != run.run_id
            or review_recovery_decision.project_id != run.project_id
            or review_recovery_decision.change_name != run.change_name
            or review_recovery_decision.claim_key != review_attempts[0].claim_key
            or review_recovery_decision.fence_token != review_attempts[0].fence_token
            or review_recovery_decision.planned_action != "DISPATCH_FROZEN_CODE_REVIEW"
            or review_recovery_decision.observation_refs.get("authorization_id")
            != review.budget_authorization_id
            or review_recovery_decision.prior_checkpoint.get("candidate_sha")
            != candidate.candidate_sha
            or review_recovery_decision.prior_checkpoint.get("manifest_hash")
            != manifest.manifest_hash
            or review_execution_action.action_request_id == request.action_request_id
        ):
            return self._record_and_return_rejection(
                request=request,
                run=run,
                error_code=OperatorActionErrorCode.AUTHORITY_MISMATCH,
                summary="Review, authorization, reservation, candidate, or manifest identity is not exact.",
                sanitized_params=sanitized_params,
            )

        from minime.services.authorship_service import AuthorshipService
        from minime.services.recovery_convergence_service import OperationalHeartbeat

        independent, _reason = AuthorshipService().is_reviewer_eligible(
            job.job_id, "deepseek", self.uow
        )
        if not independent:
            return self._record_and_return_rejection(
                request=request,
                run=run,
                error_code=OperatorActionErrorCode.AUTHORITY_MISMATCH,
                summary="Persisted reviewer is not independent of candidate authorship.",
                sanitized_params=sanitized_params,
            )
        try:
            manager = self._worktree_manager_for_bound_project(run.project_id, project=project)
            worktree_path = manager.worktree_path(job.job_id, project_id=job.project_id)
        except Exception as exc:
            return self._record_and_return_rejection(
                request=request,
                run=run,
                error_code=OperatorActionErrorCode.AUTHORITY_MISMATCH,
                summary=f"Bound managed repository proof failed: {type(exc).__name__}.",
                sanitized_params=sanitized_params,
            )
        ownership_repo = getattr(self.uow, "orchestration_worktree_ownerships", None)
        ownership = ownership_repo.get_by_job_id(job.job_id) if ownership_repo else None
        try:
            import asyncio

            if ownership is None:
                raise ValueError("ownership missing")
            asyncio.run(
                manager._verify_frozen_candidate_worktree_adoption(
                    path=worktree_path,
                    job_id=job.job_id,
                    project_id=project.project_id,
                    run_id=run.run_id,
                    change_name=run.change_name,
                    ownership=ownership,
                )
            )
        except Exception as exc:
            return self._record_and_return_rejection(
                request=request,
                run=run,
                error_code=OperatorActionErrorCode.AUTHORITY_MISMATCH,
                summary=f"Frozen candidate integrity revalidation failed: {type(exc).__name__}.",
                sanitized_params=sanitized_params,
            )

        context = self.recovery_convergence_service.acquire_claim(f"run:{run.run_id}")
        if not context:
            return self._record_and_return_rejection(
                request=request,
                run=run,
                error_code=OperatorActionErrorCode.RECOVERY_REQUIRED,
                summary="Run claim is held by another live recovery owner.",
                sanitized_params=sanitized_params,
            )
        cycle_id = generate_uuid()
        decision = RecoveryDecision(
            cycle_id=cycle_id,
            claim_key=context.claim_key,
            identity_type="RUN",
            identity_id=run.run_id,
            project_id=run.project_id,
            change_name=run.change_name,
            source=RecoverySource.CONTROL_PLANE,
            prior_checkpoint={
                "stage": OrchestrationStage.COMPLEMENTARY_REVIEW.value,
                "review_id": review.review_id,
                "candidate_sha": candidate.candidate_sha,
                "generation": candidate.generation,
                "manifest_id": manifest.manifest_id,
                "manifest_hash": manifest.manifest_hash,
            },
            observation_refs={"action_request_id": request.action_request_id},
            classification=RecoveryClassification.RESUME_SAFE_CHECKPOINT,
            planned_action="CONTINUE_AFTER_CODE_REVIEW",
            fence_token=context.fence_token,
            status=RecoveryDecisionStatus.EXECUTING,
        )
        action_record = OperatorActionRecord(
            action_request_id=request.action_request_id,
            project_id=run.project_id,
            change_name=run.change_name,
            run_id=run.run_id,
            job_id=job.job_id,
            action_type=request.action_type,
            actor_identity=request.actor_identity,
            source_interface=request.source_interface,
            precondition_stage=run.current_stage.value,
            precondition_gate=run.human_gate.value if run.human_gate else None,
            status=OperatorActionStatus.ACCEPTED,
            summary="Exact completed review accepted for separately authorized continuation.",
            parameters_json=sanitized_params,
            result_payload_json={"recovery_decision_id": decision.decision_id},
        )
        self.uow.recovery_decisions.create_decision(decision)
        self.uow.operator_actions.save(action_record)
        heartbeat = OperationalHeartbeat(
            recovery_service=self.recovery_convergence_service,
            claim_context=context,
            interval_seconds=max(1, self.recovery_convergence_service.heartbeat_seconds),
            lease_seconds=self.recovery_convergence_service.lease_seconds,
        )
        try:
            with heartbeat:
                from minime.domain.models import validate_claim_context_authoritative

                validate_claim_context_authoritative(self.uow, context, for_update=True)
                persisted_run = self.uow.orchestration_runs.get_by_id(run.run_id)
                persisted_job = self.uow.jobs.get_by_id(job.job_id)
                if (
                    not persisted_run
                    or not persisted_job
                    or persisted_run.stop_details != run.stop_details
                    or persisted_run.stop_outcome != OrchestrationStopOutcome.NEEDS_HUMAN
                    or persisted_run.human_gate != HumanGate.NEEDS_HUMAN
                    or persisted_run.current_candidate_sha != candidate.candidate_sha
                    or persisted_run.current_stage != OrchestrationStage.COMPLEMENTARY_REVIEW
                    or persisted_run.resumable_stage != OrchestrationStage.COMPLEMENTARY_REVIEW
                    or persisted_job.status != JobStatus.CHECKS_PASSED
                ):
                    raise ValueError("post-review checkpoint changed while acquiring claim")
                persisted_run.is_active = True
                persisted_run.stop_outcome = None
                persisted_run.human_gate = None
                persisted_run.stop_reason = None
                persisted_run.stop_details = {}
                persisted_run.current_stage = OrchestrationStage.COMPLEMENTARY_REVIEW
                persisted_run.resumable_stage = OrchestrationStage.COMPLEMENTARY_REVIEW
                self.uow.orchestration_runs.save(persisted_run)
                self.uow.commit()
                resumed = self.orchestration_service.resume(
                    run_id=run.run_id,
                    project_root=manager.project_root,
                    force=True,
                    claim_context=context,
                    manage_heartbeat=False,
                )
            if (
                heartbeat.heartbeat_failed
                or not heartbeat.stopped_cleanly
                or heartbeat.is_alive
                or heartbeat.is_renewing
            ):
                raise RuntimeError("post-review continuation lost its claim heartbeat")
            validate_claim_context_authoritative(self.uow, context, for_update=True)
            final_run = self.uow.orchestration_runs.get_by_id(run.run_id) or resumed
            final_job = self.uow.jobs.get_by_id(job.job_id)
            action_record.status = OperatorActionStatus.COMPLETED
            action_record.summary = (
                "Post-review continuation processed through existing gates; "
                f"persisted stage={final_run.current_stage.value}, "
                f"outcome={final_run.stop_outcome.value if final_run.stop_outcome else 'NONE'}, "
                f"job={final_job.status.value if final_job else 'MISSING'}."
            )
            action_record.evidence_reference = review.review_id
            action_record.result_payload_json = {
                "review_id": review.review_id,
                "candidate_sha": candidate.candidate_sha,
                "manifest_hash": manifest.manifest_hash,
                "resulting_stage": final_run.current_stage.value,
                "resulting_outcome": final_run.stop_outcome.value
                if final_run.stop_outcome
                else None,
                "job_status": final_job.status.value if final_job else None,
                "recovery_decision_id": decision.decision_id,
            }
            decision.status = RecoveryDecisionStatus.COMPLETED
            decision.result_payload = action_record.result_payload_json
            self.uow.operator_actions.save(action_record)
            self.uow.recovery_decisions.update_decision(decision, claim_context=context)
            self.uow.commit()
        except Exception as exc:
            self.uow.rollback()
            action_record.status = OperatorActionStatus.BLOCKED
            action_record.summary = "Post-review continuation failed closed; inspect durable Run/Job state before another action."
            safe_error_detail = redact_secrets(str(exc))[:240]
            action_record.result_payload_json = {
                "error_type": type(exc).__name__,
                "error_detail": safe_error_detail,
                "recovery_decision_id": decision.decision_id,
            }
            decision.status = RecoveryDecisionStatus.BLOCKED
            decision.reason_code = f"POST_REVIEW_CONTINUATION_FAILED:{type(exc).__name__}"
            try:
                self.uow.operator_actions.save(action_record)
                self.uow.recovery_decisions.update_decision(decision, claim_context=context)
                self.uow.commit()
            except Exception:
                self.uow.rollback()
            return OperatorActionResult(
                action_request_id=request.action_request_id,
                action_type=request.action_type,
                status=OperatorActionStatus.BLOCKED,
                error_code=OperatorActionErrorCode.ACTION_EXECUTION_FAILED,
                summary=action_record.summary,
                resulting_stage=(
                    self.uow.orchestration_runs.get_by_id(run.run_id) or run
                ).current_stage,
                resulting_outcome=(
                    self.uow.orchestration_runs.get_by_id(run.run_id) or run
                ).stop_outcome,
                resulting_gate=(
                    self.uow.orchestration_runs.get_by_id(run.run_id) or run
                ).human_gate,
                evidence_reference=review.review_id,
                payload=action_record.result_payload_json,
            )
        finally:
            if not heartbeat.is_alive and not heartbeat.is_renewing:
                self.recovery_convergence_service.release_claim(context)

        return OperatorActionResult(
            action_request_id=request.action_request_id,
            action_type=request.action_type,
            status=action_record.status,
            summary=action_record.summary,
            resulting_stage=final_run.current_stage,
            resulting_outcome=final_run.stop_outcome,
            resulting_gate=final_run.human_gate,
            evidence_reference=review.review_id,
            payload=action_record.result_payload_json,
        )

    def _execute_authorize_deepseek_code_review(
        self,
        request: OperatorActionRequest,
        run: OrchestrationRun,
        sanitized_params: dict[str, Any],
    ) -> OperatorActionResult:
        """Authorize one bounded review for a specific frozen candidate only."""
        job = self.uow.jobs.get_by_id(run.active_job_id) if run.active_job_id else None
        candidates_repo = getattr(self.uow, "orchestration_candidates", None)
        manifests_repo = getattr(self.uow, "candidate_manifests", None)
        candidate = (
            candidates_repo.get_by_generation(run.run_id, run.current_generation)
            if job and candidates_repo
            else None
        )
        manifest = (
            manifests_repo.get_by_id(candidate.manifest_id)
            if candidate and candidate.manifest_id and manifests_repo
            else None
        )
        project = self.uow.projects.get_by_id(run.project_id) if job else None
        checks_valid, _, current_check_batch = (
            self.orchestration_service._validate_current_checks_batch(
                job,
                run,
                project,
                require_configured_checks=True,
            )
            if job and candidate
            else (False, "Candidate or check authority is unavailable.", [])
        )
        prior_code_review = (
            self.uow.reviews.get_by_job_stage(job.job_id, "CODE_REVIEW") if job else None
        )
        review_slot_open = bool(
            prior_code_review is None
            or (
                prior_code_review.status == ReviewStatus.REVIEW_RUNNING
                and prior_code_review.budget_authorization_id is None
                and prior_code_review.budget_reservation_id is None
                and prior_code_review.provider is None
            )
        )
        if (
            not job
            or not candidate
            or not manifest
            or not candidate.is_frozen
            or run.active_job_id != job.job_id
            or run.project_id != job.project_id
            or run.change_name != job.change_name
            or candidate.run_id != run.run_id
            or candidate.generation != run.current_generation
            or candidate.candidate_sha != job.candidate_sha
            or candidate.candidate_sha != run.current_candidate_sha
            or candidate.base_sha != run.base_sha
            or manifest.job_id != job.job_id
            or manifest.candidate_sha != candidate.candidate_sha
            or manifest.manifest_hash != candidate.manifest_hash
            or job.status not in {JobStatus.CHECKS_PASSED, JobStatus.WAITING_CAPACITY}
            or not checks_valid
            or not current_check_batch
            or not review_slot_open
        ):
            return self._record_and_return_rejection(
                request=request,
                run=run,
                error_code=OperatorActionErrorCode.ACTION_NOT_ALLOWED,
                summary="Code-review authorization requires the exact frozen candidate and passing checks.",
                sanitized_params=sanitized_params,
            )
        if not self._code_review_authorization_renewal_allowed(run, job, candidate):
            return self._record_and_return_rejection(
                request=request,
                run=run,
                error_code=OperatorActionErrorCode.ACTION_ALREADY_COMPLETED,
                summary=(
                    "Code-review authorization cannot be renewed unless every prior same-candidate "
                    "authorization is expired and durably proven unused."
                ),
                sanitized_params=sanitized_params,
            )
        if set(sanitized_params) != {"max_spend_usd", "expires_at", "pricing_snapshot_id"}:
            return self._record_and_return_rejection(
                request=request,
                run=run,
                error_code=OperatorActionErrorCode.INVALID_ACTION_PARAMETERS,
                summary="Authorization requires exactly max_spend_usd, expires_at, and pricing_snapshot_id.",
                sanitized_params=sanitized_params,
            )
        try:
            max_spend = Decimal(str(sanitized_params["max_spend_usd"]))
            expires_at = datetime.fromisoformat(str(sanitized_params["expires_at"]))
            if expires_at.tzinfo is None or max_spend <= 0:
                raise ValueError("invalid authorization bound")
        except (InvalidOperation, ValueError, TypeError):
            return self._record_and_return_rejection(
                request=request,
                run=run,
                error_code=OperatorActionErrorCode.INVALID_ACTION_PARAMETERS,
                summary="Authorization amount or expiry is invalid.",
                sanitized_params=sanitized_params,
            )
        now = utc_now()
        if expires_at <= now or (expires_at - now).total_seconds() > 3600:
            return self._record_and_return_rejection(
                request=request,
                run=run,
                error_code=OperatorActionErrorCode.INVALID_ACTION_PARAMETERS,
                summary="Code-review authorization must expire within one hour.",
                sanitized_params=sanitized_params,
            )
        if not project:
            return self._record_and_return_rejection(
                request=request,
                run=run,
                error_code=OperatorActionErrorCode.AUTHORITY_MISMATCH,
                summary="Project binding is unavailable for code-review authorization.",
                sanitized_params=sanitized_params,
            )
        app_config = load_config()
        project_config = app_config.projects.get(project.project_id) or ProjectConfig(
            repository=project.repository,
            base_branch=project.base_branch,
            openspec_path=project.openspec_path,
            implementer=project.implementer,
            reviewer=project.reviewer,
            external_providers_allowed=project.external_providers_allowed,
        )
        provider_config = app_config.providers.get("deepseek")
        configured_max = (
            provider_config.budget.get("maximum_code_review_usd")
            if provider_config and isinstance(provider_config.budget, dict)
            else None
        )
        if configured_max is not None:
            try:
                configured_max = Decimal(str(configured_max))
            except Exception:
                configured_max = Decimal("0")
        if configured_max is not None and max_spend > configured_max:
            return self._record_and_return_rejection(
                request=request,
                run=run,
                error_code=OperatorActionErrorCode.BUDGET_BLOCKED,
                summary="Requested spend exceeds the configured code-review ceiling.",
                sanitized_params=sanitized_params,
            )
        review_budget = provider_config.budget if provider_config else {}
        if not self._deepseek_review_total_within_limit(run, review_budget, max_spend):
            return self._record_and_return_rejection(
                request=request,
                run=run,
                error_code=OperatorActionErrorCode.BUDGET_BLOCKED,
                summary="Combined DeepSeek review authorizations exceed the configured owner limit or are ambiguous.",
                sanitized_params=sanitized_params,
            )
        try:
            profile = resolve_stage_profile(
                project_config, OpenSpecStage.REVIEW, app_config=app_config
            )
            from minime.adapters.provider_adapter import get_provider_adapter

            adapter = get_provider_adapter("deepseek", app_config)
            supported, _ = __import__("asyncio").run(
                adapter.check_model_supported(profile.model, effort=profile.effort)
            )
            account_fingerprint = getattr(adapter, "account_fingerprint", None)
            snapshot = self.uow.pricing_snapshots.get_by_id(
                str(sanitized_params["pricing_snapshot_id"])
            )
        except Exception:
            supported = False
            account_fingerprint = None
            snapshot = None
            profile = None
        if (
            not profile
            or profile.provider != "deepseek"
            or not supported
            or not account_fingerprint
            or not snapshot
            or not snapshot.is_verified
            or snapshot.provider != "deepseek"
            or snapshot.account_fingerprint != account_fingerprint
            or snapshot.canonical_model_identity != profile.model
            or snapshot.billing_origin != "deepseek_direct"
            or snapshot.currency != "USD"
        ):
            return self._record_and_return_rejection(
                request=request,
                run=run,
                error_code=OperatorActionErrorCode.BUDGET_BLOCKED,
                summary="Direct DeepSeek code-review model, account, and verified price evidence is unavailable or mismatched.",
                sanitized_params=sanitized_params,
            )
        authorization = {
            "provider": "deepseek",
            "account_fingerprint": account_fingerprint,
            "model": profile.model,
            "effort": profile.effort,
            "stage": "REVIEW",
            "billing_origin": "deepseek_direct",
            "pricing_snapshot_id": snapshot.snapshot_id,
            "run_id": run.run_id,
            "job_id": job.job_id,
            "candidate_sha": candidate.candidate_sha,
            "base_sha": candidate.base_sha,
            "generation": candidate.generation,
            "manifest_id": candidate.manifest_id,
            "manifest_hash": candidate.manifest_hash,
            "max_spend_usd": str(max_spend),
            "expires_at": expires_at.isoformat(),
            "authorized_by": request.actor_identity,
            "action_request_id": request.action_request_id,
        }
        summary = "One-use DeepSeek Direct code REVIEW authorized for the exact candidate; merge remains a separate human gate."
        record = OperatorActionRecord(
            action_request_id=request.action_request_id,
            project_id=run.project_id,
            change_name=run.change_name,
            run_id=run.run_id,
            job_id=job.job_id,
            action_type=request.action_type,
            actor_identity=request.actor_identity,
            source_interface=request.source_interface,
            precondition_stage=run.current_stage.value,
            status=OperatorActionStatus.COMPLETED,
            summary=summary,
            evidence_reference=snapshot.snapshot_id,
            parameters_json=sanitized_params,
            result_payload_json={"authorization": authorization},
        )
        self.uow.operator_actions.save(record)
        self.uow.events.save(
            Event(
                event_type=EventType.OPERATOR_ACTION_EXECUTED,
                payload={
                    "action_request_id": request.action_request_id,
                    "action_type": request.action_type.value,
                    "run_id": run.run_id,
                    "job_id": job.job_id,
                    "provider": "deepseek",
                    "stage": "REVIEW",
                    "candidate_sha": candidate.candidate_sha,
                    "manifest_hash": candidate.manifest_hash,
                    "model": profile.model,
                    "authorization_id": request.action_request_id,
                },
                timestamp=now,
            )
        )
        self.uow.commit()
        return OperatorActionResult(
            action_request_id=request.action_request_id,
            action_type=request.action_type,
            status=OperatorActionStatus.COMPLETED,
            summary=summary,
            resulting_stage=run.current_stage,
            resulting_outcome=run.stop_outcome,
            resulting_gate=run.human_gate,
            evidence_reference=snapshot.snapshot_id,
            payload={
                "provider": "deepseek",
                "stage": "REVIEW",
                "candidate_sha": candidate.candidate_sha,
                "maximum_usd": str(max_spend),
            },
        )

    def _execute_retry(
        self,
        request: OperatorActionRequest,
        run: OrchestrationRun,
        sanitized_params: dict[str, Any],
    ) -> OperatorActionResult:
        if run.is_active:
            return self._record_and_return_rejection(
                request=request,
                run=run,
                error_code=OperatorActionErrorCode.ACTION_NOT_ALLOWED,
                summary="Cannot retry stage: run is already active.",
                sanitized_params=sanitized_params,
            )

        if run.current_stage not in {
            OrchestrationStage.RUNNING_CHECKS,
            OrchestrationStage.IMPLEMENTING,
        }:
            return self._record_and_return_rejection(
                request=request,
                run=run,
                error_code=OperatorActionErrorCode.ACTION_NOT_ALLOWED,
                summary=f"Retry is not permitted from stage '{run.current_stage.value}'.",
                sanitized_params=sanitized_params,
            )

        if run.retry_count >= 3:
            return self._record_and_return_rejection(
                request=request,
                run=run,
                error_code=OperatorActionErrorCode.BUDGET_BLOCKED,
                summary=f"Retry limit exceeded for run ({run.retry_count}/3).",
                sanitized_params=sanitized_params,
            )

        # Increment retry count and resume through RecoveryConvergenceService
        run.retry_count += 1
        with self.uow.orchestration_runs.session.begin_nested():
            run.stop_outcome = None
            run.human_gate = None
            run.is_active = True
            run.stop_reason = None
            run.stop_details = {}
            if run.active_job_id:
                job = self.uow.jobs.get_by_id(run.active_job_id)
                if job:
                    if job.base_sha and job.base_sha != run.base_sha:
                        run.base_sha = job.base_sha
                    job.status = JobStatus.RUNNING
                    job.continuation_decision = None
                    job.escalation_reason = None
                    self.uow.jobs.save(job)
            run.resumable_stage = OrchestrationStage.IMPLEMENTING
            run.current_stage = OrchestrationStage.IMPLEMENTING
            self.uow.orchestration_runs.save(run)
            self.uow.commit()

        self.recovery_convergence_service.request_run_continuation(
            run.run_id, source=RecoverySource.CONTROL_PLANE, force=True
        )
        resumed_run = self.uow.orchestration_runs.get_by_id(run.run_id) or run

        summary = f"Stage retried (attempt #{resumed_run.retry_count}); stage is now {resumed_run.current_stage.value}."
        record = OperatorActionRecord(
            action_request_id=request.action_request_id,
            project_id=request.project_id,
            change_name=request.change_name,
            run_id=request.run_id,
            action_type=request.action_type,
            actor_identity=request.actor_identity,
            source_interface=request.source_interface,
            precondition_stage=run.current_stage.value,
            precondition_gate=run.human_gate.value if run.human_gate else None,
            status=OperatorActionStatus.COMPLETED,
            summary=summary,
            resulting_stage=resumed_run.current_stage.value,
            resulting_outcome=resumed_run.stop_outcome.value if resumed_run.stop_outcome else None,
            resulting_gate=resumed_run.human_gate.value if resumed_run.human_gate else None,
            parameters_json=sanitized_params,
            result_payload_json={"retry_count": resumed_run.retry_count},
        )
        self.uow.operator_actions.save(record)
        self.uow.events.save(
            Event(
                event_type=EventType.OPERATOR_ACTION_EXECUTED,
                payload={
                    "action_request_id": request.action_request_id,
                    "action_type": request.action_type.value,
                    "retry_count": resumed_run.retry_count,
                    "run_id": request.run_id,
                },
                timestamp=utc_now(),
            )
        )
        self.uow.commit()

        return OperatorActionResult(
            action_request_id=request.action_request_id,
            action_type=request.action_type,
            status=OperatorActionStatus.COMPLETED,
            summary=summary,
            resulting_stage=resumed_run.current_stage,
            resulting_outcome=resumed_run.stop_outcome,
            resulting_gate=resumed_run.human_gate,
            payload={"retry_count": resumed_run.retry_count},
        )

    def _execute_reassign(
        self,
        request: OperatorActionRequest,
        run: OrchestrationRun,
        sanitized_params: dict[str, Any],
    ) -> OperatorActionResult:
        if run.is_active:
            return self._record_and_return_rejection(
                request=request,
                run=run,
                error_code=OperatorActionErrorCode.ACTION_NOT_ALLOWED,
                summary="Cannot reassign executor: run is currently active.",
                sanitized_params=sanitized_params,
            )

        project = self.uow.projects.get_by_id(run.project_id)
        if not project:
            return self._record_and_return_rejection(
                request=request,
                run=run,
                error_code=OperatorActionErrorCode.AUTHORITY_MISMATCH,
                summary="Project not found.",
                sanitized_params=sanitized_params,
            )

        target_executor = sanitized_params.get("target_executor")
        if not target_executor:
            # Pick alternate allowed provider
            allowed = project.external_providers_allowed
            target_executor = allowed[1] if len(allowed) > 1 else allowed[0]

        if target_executor not in project.external_providers_allowed:
            return self._record_and_return_rejection(
                request=request,
                run=run,
                error_code=OperatorActionErrorCode.PROVIDER_UNAVAILABLE,
                summary=f"Target executor '{target_executor}' is not in allowed providers {project.external_providers_allowed}.",
                sanitized_params=sanitized_params,
            )

        job = self.uow.jobs.get_by_id(run.active_job_id) if run.active_job_id else None
        if not job or job.project_id != run.project_id or job.change_name != run.change_name:
            return self._record_and_return_rejection(
                request=request,
                run=run,
                error_code=OperatorActionErrorCode.AUTHORITY_MISMATCH,
                summary="REASSIGN requires the exact linked Job for this Run.",
                sanitized_params=sanitized_params,
            )

        if job.status not in {JobStatus.NEEDS_HUMAN, JobStatus.FAILED, JobStatus.RECOVERY_BLOCKED}:
            return self._record_and_return_rejection(
                request=request,
                run=run,
                error_code=OperatorActionErrorCode.ACTION_NOT_ALLOWED,
                summary=f"Cannot reassign linked Job in status {job.status.value}.",
                sanitized_params=sanitized_params,
            )
        if job.current_executor == target_executor:
            return self._record_and_return_rejection(
                request=request,
                run=run,
                error_code=OperatorActionErrorCode.ACTION_NOT_ALLOWED,
                summary="Target executor is already assigned to the linked Job.",
                sanitized_params=sanitized_params,
            )
        if job.reassignment_count >= 2:
            return self._record_and_return_rejection(
                request=request,
                run=run,
                error_code=OperatorActionErrorCode.BUDGET_BLOCKED,
                summary="Canonical per-job reassignment limit (2) has been reached.",
                sanitized_params=sanitized_params,
            )

        # An unknown or stale provider-health state is not authorization to
        # dispatch a manually selected executor.
        health = self.provider_health_service.get_existing_health(target_executor)
        if not health or health.status != ProviderHealthStatus.AVAILABLE:
            return self._record_and_return_rejection(
                request=request,
                run=run,
                error_code=OperatorActionErrorCode.PROVIDER_UNAVAILABLE,
                summary=f"Target provider '{target_executor}' is not currently available.",
                sanitized_params=sanitized_params,
            )

        # REASSIGN only records durable intent. Execution remains a distinct
        # operator CONTINUE action. The existing job repository performs the
        # executor mutation under the current run claim/fence.
        rec_svc = RecoveryConvergenceService(self.uow, project_root=self.project_root)
        claim = rec_svc.acquire_claim(f"run:{run.run_id}")
        if not claim:
            return self._record_and_return_rejection(
                request=request,
                run=run,
                error_code=OperatorActionErrorCode.RECOVERY_REQUIRED,
                summary="Could not acquire the canonical run recovery claim for reassignment.",
                sanitized_params=sanitized_params,
            )
        claim_context = claim
        committed = False
        try:
            current_job = self.uow.jobs.get_by_id(job.job_id)
            if (
                not current_job
                or current_job.project_id != run.project_id
                or current_job.change_name != run.change_name
                or current_job.status
                not in {JobStatus.NEEDS_HUMAN, JobStatus.FAILED, JobStatus.RECOVERY_BLOCKED}
                or current_job.reassignment_count >= 2
            ):
                raise ValueError("Linked Job changed or reached the reassignment ceiling.")
            self.uow.jobs.update_executor_fenced(
                current_job.job_id, target_executor, claim_context=claim_context
            )
            current_job.current_executor = target_executor
            current_job.reassignment_count += 1
            self.uow.jobs.save(current_job)
            summary = (
                f"Executor reassignment to {target_executor} was durably applied; "
                "a separate authorized CONTINUE is required to resume execution."
            )
            record = OperatorActionRecord(
                action_request_id=request.action_request_id,
                project_id=request.project_id,
                change_name=request.change_name,
                run_id=request.run_id,
                job_id=current_job.job_id,
                action_type=request.action_type,
                actor_identity=request.actor_identity,
                source_interface=request.source_interface,
                precondition_stage=run.current_stage.value,
                precondition_gate=run.human_gate.value if run.human_gate else None,
                status=OperatorActionStatus.COMPLETED,
                summary=summary,
                parameters_json=sanitized_params,
                result_payload_json={
                    "target_executor": target_executor,
                    "executor_assignment_applied": True,
                    "reassignment_count": current_job.reassignment_count,
                    "execution_started": False,
                },
            )
            self.uow.operator_actions.save(record)
            self.uow.events.save(
                Event(
                    event_type=EventType.OPERATOR_ACTION_EXECUTED,
                    payload={
                        "action_request_id": request.action_request_id,
                        "action_type": request.action_type.value,
                        "target_executor": target_executor,
                        "run_id": request.run_id,
                        "job_id": current_job.job_id,
                        "execution_started": False,
                    },
                    timestamp=utc_now(),
                )
            )
            rec_svc.validate_claim(claim_context)
            self.uow.commit()
            committed = True
            result_payload = record.result_payload_json
        finally:
            if not committed:
                self.uow.rollback()
            try:
                rec_svc.release_claim(claim_context)
            except Exception:
                # The assignment plus action record are already atomic and
                # durable once committed; lease expiry remains the safe
                # fallback if best-effort release itself is unavailable.
                logger.warning("Could not release reassignment recovery claim for %s", run.run_id)

        return OperatorActionResult(
            action_request_id=request.action_request_id,
            action_type=request.action_type,
            status=OperatorActionStatus.COMPLETED,
            summary=summary,
            resulting_stage=run.current_stage,
            resulting_outcome=run.stop_outcome,
            resulting_gate=run.human_gate,
            payload=result_payload,
        )

    def _execute_resolve_gate(
        self,
        request: OperatorActionRequest,
        run: OrchestrationRun,
        sanitized_params: dict[str, Any],
    ) -> OperatorActionResult:
        if (
            run.human_gate != HumanGate.NEEDS_HUMAN
            and run.stop_outcome != OrchestrationStopOutcome.NEEDS_HUMAN
        ):
            return self._record_and_return_rejection(
                request=request,
                run=run,
                error_code=OperatorActionErrorCode.ACTION_NOT_ALLOWED,
                summary="Cannot resolve gate: run is not stopped at a NEEDS_HUMAN gate.",
                sanitized_params=sanitized_params,
            )

        resolution_type = sanitized_params.get("resolution_type")
        verdict_param = sanitized_params.get("verdict")

        if verdict_param:
            # Visual validation resolution
            verdict = (
                ValidationVerdict.PASS
                if str(verdict_param).upper() == "PASS"
                else ValidationVerdict.FAIL
            )
            notes = sanitized_params.get("notes", "Resolved via Control Plane")
            operator = sanitized_params.get("operator", request.actor_identity)

            # Record validation
            active_preview = self.uow.preview_sessions.get_active_for_change(
                run.project_id, run.change_name
            )
            validation_run = self.validation_service.record_validation(
                project_id=run.project_id,
                change_name=run.change_name,
                head_sha=run.candidate_sha or "",
                base_sha=run.base_sha,
                image_digest=active_preview.image_digest if active_preview else "",
                verdict=verdict,
                scenario_results=[],
                notes=notes,
                operator=operator,
                preview_id=active_preview.preview_id if active_preview else None,
                run_id=run.run_id,
            )

            # Advance orchestration through RecoveryConvergenceService
            rec_svc = RecoveryConvergenceService(self.uow, project_root=self.project_root)
            rec_svc.request_run_continuation(run.run_id, source=RecoverySource.CONTROL_PLANE)
            resumed_run = self.uow.orchestration_runs.get_by_id(run.run_id) or run

            summary = f"UI Validation recorded ({verdict.value}); run advanced to stage {resumed_run.current_stage.value}."
            record = OperatorActionRecord(
                action_request_id=request.action_request_id,
                project_id=request.project_id,
                change_name=request.change_name,
                run_id=request.run_id,
                action_type=request.action_type,
                actor_identity=request.actor_identity,
                source_interface=request.source_interface,
                precondition_stage=run.current_stage.value,
                precondition_gate=run.human_gate.value if run.human_gate else None,
                status=OperatorActionStatus.COMPLETED,
                summary=summary,
                resulting_stage=resumed_run.current_stage.value,
                resulting_outcome=resumed_run.stop_outcome.value
                if resumed_run.stop_outcome
                else None,
                resulting_gate=resumed_run.human_gate.value if resumed_run.human_gate else None,
                evidence_reference=validation_run.validation_id,
                parameters_json=sanitized_params,
                result_payload_json={
                    "validation_id": validation_run.validation_id,
                    "verdict": verdict.value,
                },
            )
            self.uow.operator_actions.save(record)
            self.uow.commit()

            return OperatorActionResult(
                action_request_id=request.action_request_id,
                action_type=request.action_type,
                status=OperatorActionStatus.COMPLETED,
                summary=summary,
                resulting_stage=resumed_run.current_stage,
                resulting_outcome=resumed_run.stop_outcome,
                resulting_gate=resumed_run.human_gate,
                evidence_reference=validation_run.validation_id,
                payload={"validation_id": validation_run.validation_id, "verdict": verdict.value},
            )

        elif resolution_type == "remediate_preserved":
            contract = sanitized_params.get("contract")
            if not contract:
                return self._record_and_return_rejection(
                    request=request,
                    run=run,
                    error_code=OperatorActionErrorCode.INVALID_ACTION_PARAMETERS,
                    summary="Parameter 'contract' is required for remediation resolution.",
                    sanitized_params=sanitized_params,
                )

            rec_svc = RecoveryConvergenceService(self.uow, project_root=self.project_root)
            claim_ctx = rec_svc.acquire_claim(f"run:{run.run_id}")
            if claim_ctx is None:
                return self._record_and_return_rejection(
                    request=request,
                    run=run,
                    error_code=OperatorActionErrorCode.AUTHORITY_MISMATCH,
                    summary=f"Run '{run.run_id}' is claimed elsewhere by another active recovery context.",
                    sanitized_params=sanitized_params,
                )

            resumed_run = self.orchestration_service.remediate_preserved_candidate(
                run.run_id,
                contract_path=contract,
                project_root=self.project_root,
                claim_context=claim_ctx,
            )
            summary = f"Preserved candidate remediation started; generation is now {resumed_run.current_generation}."
            record = OperatorActionRecord(
                action_request_id=request.action_request_id,
                project_id=request.project_id,
                change_name=request.change_name,
                run_id=request.run_id,
                action_type=request.action_type,
                actor_identity=request.actor_identity,
                source_interface=request.source_interface,
                precondition_stage=run.current_stage.value,
                precondition_gate=run.human_gate.value if run.human_gate else None,
                status=OperatorActionStatus.COMPLETED,
                summary=summary,
                resulting_stage=resumed_run.current_stage.value,
                resulting_outcome=resumed_run.stop_outcome.value
                if resumed_run.stop_outcome
                else None,
                resulting_gate=resumed_run.human_gate.value if resumed_run.human_gate else None,
                parameters_json=sanitized_params,
                result_payload_json={"new_generation": resumed_run.current_generation},
            )
            self.uow.operator_actions.save(record)
            self.uow.commit()

            return OperatorActionResult(
                action_request_id=request.action_request_id,
                action_type=request.action_type,
                status=OperatorActionStatus.COMPLETED,
                summary=summary,
                resulting_stage=resumed_run.current_stage,
                resulting_outcome=resumed_run.stop_outcome,
                resulting_gate=resumed_run.human_gate,
                payload={"new_generation": resumed_run.current_generation},
            )

        elif resolution_type == "continue_preserved" or resolution_type is None:
            candidate_ref = sanitized_params.get("candidate_ref")
            rec_svc = RecoveryConvergenceService(self.uow, project_root=self.project_root)
            claim_ctx = rec_svc.acquire_claim(f"run:{run.run_id}")
            if claim_ctx is None:
                return self._record_and_return_rejection(
                    request=request,
                    run=run,
                    error_code=OperatorActionErrorCode.AUTHORITY_MISMATCH,
                    summary=f"Run '{run.run_id}' is claimed elsewhere by another active recovery context.",
                    sanitized_params=sanitized_params,
                )

            resumed_run = self.orchestration_service.resolve_preserved_candidate(
                run.run_id,
                continue_preserved_candidate=True,
                candidate_ref=candidate_ref,
                project_root=self.project_root,
                claim_context=claim_ctx,
            )
            summary = (
                f"Preserved candidate resolved; run stage is now {resumed_run.current_stage.value}."
            )
            record = OperatorActionRecord(
                action_request_id=request.action_request_id,
                project_id=request.project_id,
                change_name=request.change_name,
                run_id=request.run_id,
                action_type=request.action_type,
                actor_identity=request.actor_identity,
                source_interface=request.source_interface,
                precondition_stage=run.current_stage.value,
                precondition_gate=run.human_gate.value if run.human_gate else None,
                status=OperatorActionStatus.COMPLETED,
                summary=summary,
                resulting_stage=resumed_run.current_stage.value,
                resulting_outcome=resumed_run.stop_outcome.value
                if resumed_run.stop_outcome
                else None,
                resulting_gate=resumed_run.human_gate.value if resumed_run.human_gate else None,
                parameters_json=sanitized_params,
                result_payload_json={"stage": resumed_run.current_stage.value},
            )
            self.uow.operator_actions.save(record)
            self.uow.commit()

            return OperatorActionResult(
                action_request_id=request.action_request_id,
                action_type=request.action_type,
                status=OperatorActionStatus.COMPLETED,
                summary=summary,
                resulting_stage=resumed_run.current_stage,
                resulting_outcome=resumed_run.stop_outcome,
                resulting_gate=resumed_run.human_gate,
                payload={"stage": resumed_run.current_stage.value},
            )
        else:
            return self._record_and_return_rejection(
                request=request,
                run=run,
                error_code=OperatorActionErrorCode.INVALID_ACTION_PARAMETERS,
                summary=f"Unknown gate resolution type '{resolution_type}'.",
                sanitized_params=sanitized_params,
            )

    def _execute_cancel(
        self,
        request: OperatorActionRequest,
        run: OrchestrationRun,
        sanitized_params: dict[str, Any],
    ) -> OperatorActionResult:
        if not run.is_active and run.stop_outcome == OrchestrationStopOutcome.CANCELLED:
            return self._record_and_return_rejection(
                request=request,
                run=run,
                error_code=OperatorActionErrorCode.ACTION_NOT_ALLOWED,
                summary="Run is already cancelled.",
                sanitized_params=sanitized_params,
            )

        # 1. Converge the linked execution job before changing the run. Both
        # mutations share the UoW and commit together below.
        self._cancel_linked_job(run)

        # 2. Update run state cleanly
        run.is_active = False
        run.stop_outcome = OrchestrationStopOutcome.CANCELLED
        run.stop_reason = f"Cancelled by {request.actor_identity} via {request.source_interface}"
        run.updated_at = utc_now()
        self.uow.orchestration_runs.save(run)

        # 3. Teardown owned container preview if active
        try:
            active_preview = self.uow.preview_sessions.get_active_for_change(
                run.project_id, run.change_name
            )
            if active_preview:
                active_preview.status = PreviewStatus.TERMINATED
                active_preview.terminated_at = utc_now()
                self.uow.preview_sessions.save(active_preview)
        except Exception as exc:
            logger.warning(f"Error tearing down preview on cancellation: {exc}")

        # 4. Emit durable event
        self.uow.events.save(
            Event(
                event_type=EventType.ORCHESTRATION_STOPPED,
                payload={
                    "run_id": run.run_id,
                    "project_id": run.project_id,
                    "change_name": run.change_name,
                    "stage": run.current_stage.value,
                    "stop_outcome": OrchestrationStopOutcome.CANCELLED.value,
                    "stop_reason": run.stop_reason,
                    "cancelled_by": request.actor_identity,
                },
                timestamp=utc_now(),
            )
        )

        summary = (
            f"Run cancelled safely by {request.actor_identity}; candidate and evidence preserved."
        )
        record = OperatorActionRecord(
            action_request_id=request.action_request_id,
            project_id=request.project_id,
            change_name=request.change_name,
            run_id=request.run_id,
            action_type=request.action_type,
            actor_identity=request.actor_identity,
            source_interface=request.source_interface,
            precondition_stage=run.current_stage.value,
            precondition_gate=run.human_gate.value if run.human_gate else None,
            status=OperatorActionStatus.COMPLETED,
            summary=summary,
            resulting_stage=run.current_stage.value,
            resulting_outcome=OrchestrationStopOutcome.CANCELLED.value,
            resulting_gate=None,
            parameters_json=sanitized_params,
            result_payload_json={"cancelled": True},
        )
        self.uow.operator_actions.save(record)
        self.uow.commit()

        return OperatorActionResult(
            action_request_id=request.action_request_id,
            action_type=request.action_type,
            status=OperatorActionStatus.COMPLETED,
            summary=summary,
            resulting_stage=run.current_stage,
            resulting_outcome=OrchestrationStopOutcome.CANCELLED,
            resulting_gate=None,
            payload={"cancelled": True},
        )

    def reconcile_cancelled_run_linked_job(self, run_id: str) -> OrchestrationRun:
        """Idempotently converge a cancelled run's non-terminal linked Job.

        This deliberately does not replay cancellation side effects or mutate the
        run. It is the narrow historical repair path for a prior version of
        CANCEL that left ``active_job_id`` in the scheduler's active-job set.
        """
        run = self.uow.orchestration_runs.get_by_id(run_id)
        if not run:
            raise ValueError(f"Orchestration run '{run_id}' not found.")
        if run.is_active or run.stop_outcome != OrchestrationStopOutcome.CANCELLED:
            raise ValueError(
                f"Run '{run_id}' is not an inactive cancelled run and cannot be reconciled."
            )

        try:
            self._cancel_linked_job(run)
            self.uow.commit()
        except Exception:
            self.uow.rollback()
            raise

        return self.uow.orchestration_runs.get_by_id(run_id) or run

    def _cancel_linked_job(self, run: OrchestrationRun) -> None:
        """Transition a run's non-terminal linked Job through the Job authority."""
        if not run.active_job_id:
            return

        job = self.uow.jobs.get_by_id(run.active_job_id)
        if not job:
            raise ValueError(
                f"Run '{run.run_id}' references missing active job '{run.active_job_id}'."
            )
        if job.status in {JobStatus.COMPLETED, JobStatus.CANCELLED}:
            return

        self.uow.jobs.transition(
            job.job_id,
            JobStatus.CANCELLED.value,
            error_message=f"Cancelled with orchestration run '{run.run_id}'.",
        )

    def _execute_start_preview(
        self,
        request: OperatorActionRequest,
        run: OrchestrationRun,
        sanitized_params: dict[str, Any],
    ) -> OperatorActionResult:
        project = self.uow.projects.get_by_id(run.project_id)
        if not project or not project.deployment_preview:
            return self._record_and_return_rejection(
                request=request,
                run=run,
                error_code=OperatorActionErrorCode.ACTION_NOT_ALLOWED,
                summary="Project does not have preview deployment configured.",
                sanitized_params=sanitized_params,
            )

        if not run.candidate_sha:
            return self._record_and_return_rejection(
                request=request,
                run=run,
                error_code=OperatorActionErrorCode.ACTION_NOT_ALLOWED,
                summary="No frozen candidate SHA exists for this run.",
                sanitized_params=sanitized_params,
            )

        session = PreviewSession(
            project_id=run.project_id,
            change_name=run.change_name,
            head_sha=run.candidate_sha,
            base_sha=run.base_sha,
            candidate_generation=run.current_generation,
            status=PreviewStatus.READY,
            preview_url="http://127.0.0.1:8787",
        )
        self.uow.preview_sessions.save(session)
        self.uow.commit()

        summary = f"Preview started successfully (status: {session.status.value}, url: {session.preview_url})."
        record = OperatorActionRecord(
            action_request_id=request.action_request_id,
            project_id=request.project_id,
            change_name=request.change_name,
            run_id=request.run_id,
            action_type=request.action_type,
            actor_identity=request.actor_identity,
            source_interface=request.source_interface,
            precondition_stage=run.current_stage.value,
            precondition_gate=run.human_gate.value if run.human_gate else None,
            status=OperatorActionStatus.COMPLETED,
            summary=summary,
            resulting_stage=run.current_stage.value,
            resulting_outcome=run.stop_outcome.value if run.stop_outcome else None,
            resulting_gate=run.human_gate.value if run.human_gate else None,
            evidence_reference=session.preview_id,
            parameters_json=sanitized_params,
            result_payload_json={
                "preview_id": session.preview_id,
                "preview_url": session.preview_url,
                "status": session.status.value,
            },
        )
        self.uow.operator_actions.save(record)
        self.uow.commit()

        return OperatorActionResult(
            action_request_id=request.action_request_id,
            action_type=request.action_type,
            status=OperatorActionStatus.COMPLETED,
            summary=summary,
            resulting_stage=run.current_stage,
            resulting_outcome=run.stop_outcome,
            resulting_gate=run.human_gate,
            evidence_reference=session.preview_id,
            payload={
                "preview_id": session.preview_id,
                "preview_url": session.preview_url,
                "status": session.status.value,
            },
        )

    def _execute_teardown_preview(
        self,
        request: OperatorActionRequest,
        run: OrchestrationRun,
        sanitized_params: dict[str, Any],
    ) -> OperatorActionResult:
        active_preview = self.uow.preview_sessions.get_active_for_change(
            run.project_id, run.change_name
        )
        if not active_preview:
            return self._record_and_return_rejection(
                request=request,
                run=run,
                error_code=OperatorActionErrorCode.ACTION_NOT_ALLOWED,
                summary="No active preview session found to teardown.",
                sanitized_params=sanitized_params,
            )

        active_preview.status = PreviewStatus.TERMINATED
        active_preview.terminated_at = utc_now()
        self.uow.preview_sessions.save(active_preview)
        summary = f"Preview session {active_preview.preview_id} torn down cleanly."

        record = OperatorActionRecord(
            action_request_id=request.action_request_id,
            project_id=request.project_id,
            change_name=request.change_name,
            run_id=request.run_id,
            action_type=request.action_type,
            actor_identity=request.actor_identity,
            source_interface=request.source_interface,
            precondition_stage=run.current_stage.value,
            precondition_gate=run.human_gate.value if run.human_gate else None,
            status=OperatorActionStatus.COMPLETED,
            summary=summary,
            resulting_stage=run.current_stage.value,
            resulting_outcome=run.stop_outcome.value if run.stop_outcome else None,
            resulting_gate=run.human_gate.value if run.human_gate else None,
            parameters_json=sanitized_params,
            result_payload_json={
                "preview_id": active_preview.preview_id,
                "status": active_preview.status.value,
            },
        )
        self.uow.operator_actions.save(record)
        self.uow.commit()

        return OperatorActionResult(
            action_request_id=request.action_request_id,
            action_type=request.action_type,
            status=OperatorActionStatus.COMPLETED,
            summary=summary,
            resulting_stage=run.current_stage,
            resulting_outcome=run.stop_outcome,
            resulting_gate=run.human_gate,
            payload={
                "preview_id": active_preview.preview_id,
                "status": active_preview.status.value,
            },
        )

    def _execute_recover_locks(
        self,
        request: OperatorActionRequest,
        run: OrchestrationRun,
        sanitized_params: dict[str, Any],
    ) -> OperatorActionResult:
        active_jobs = self.uow.jobs.list_active_jobs()
        related_jobs = [
            j
            for j in active_jobs
            if j.change_name == run.change_name and j.project_id == run.project_id
        ]

        recovered_locks_count = 0
        for job in related_jobs:
            worktree = Path(job.worktree_path) if job.worktree_path else None
            if worktree and worktree.exists():
                results = self.recovery_service.inspect_git_locks(worktree, job)
                for r in results:
                    if r.status.value == "RECOVERED":
                        recovered_locks_count += 1

        summary = f"Recovered {recovered_locks_count} abandoned Git lock(s)."
        record = OperatorActionRecord(
            action_request_id=request.action_request_id,
            project_id=request.project_id,
            change_name=request.change_name,
            run_id=request.run_id,
            action_type=request.action_type,
            actor_identity=request.actor_identity,
            source_interface=request.source_interface,
            precondition_stage=run.current_stage.value,
            precondition_gate=run.human_gate.value if run.human_gate else None,
            status=OperatorActionStatus.COMPLETED,
            summary=summary,
            resulting_stage=run.current_stage.value,
            resulting_outcome=run.stop_outcome.value if run.stop_outcome else None,
            resulting_gate=run.human_gate.value if run.human_gate else None,
            parameters_json=sanitized_params,
            result_payload_json={"recovered_locks_count": recovered_locks_count},
        )
        self.uow.operator_actions.save(record)
        self.uow.commit()

        return OperatorActionResult(
            action_request_id=request.action_request_id,
            action_type=request.action_type,
            status=OperatorActionStatus.COMPLETED,
            summary=summary,
            resulting_stage=run.current_stage,
            resulting_outcome=run.stop_outcome,
            resulting_gate=run.human_gate,
            payload={"recovered_locks_count": recovered_locks_count},
        )

    def _execute_reconcile_post_merge(
        self,
        request: OperatorActionRequest,
        run: OrchestrationRun,
        sanitized_params: dict[str, Any],
    ) -> OperatorActionResult:
        from minime.domain.enums import (
            RecoveryClassification,
            RecoveryDecisionStatus,
            RecoverySource,
        )

        gh_adapter = getattr(
            self.post_merge_service,
            "github_adapter",
            getattr(self.orchestration_service, "github_adapter", None),
        )
        rec_svc = RecoveryConvergenceService(
            self.uow,
            project_root=self.project_root,
            post_merge_service=self.post_merge_service,
            github_adapter=gh_adapter,
        )
        decision = rec_svc.request_run_continuation(
            run_id=run.run_id,
            source=RecoverySource.CONTROL_PLANE,
            requested_action="RECONCILE_POST_MERGE",
        )
        if decision.classification == RecoveryClassification.CLAIMED_ELSEWHERE:
            return self._record_and_return_rejection(
                request=request,
                run=run,
                error_code=OperatorActionErrorCode.AUTHORITY_MISMATCH,
                summary=f"Run '{run.run_id}' is claimed elsewhere by another active recovery context.",
                sanitized_params=sanitized_params,
            )
        if decision.status == RecoveryDecisionStatus.BLOCKED:
            return self._record_and_return_rejection(
                request=request,
                run=run,
                error_code=OperatorActionErrorCode.ACTION_EXECUTION_FAILED,
                summary=decision.reason_code or "Post-merge reconciliation failed.",
                sanitized_params=sanitized_params,
            )

        summary = "Post-merge reconciliation completed successfully."
        record = OperatorActionRecord(
            action_request_id=request.action_request_id,
            project_id=request.project_id,
            change_name=request.change_name,
            run_id=request.run_id,
            action_type=request.action_type,
            actor_identity=request.actor_identity,
            source_interface=request.source_interface,
            precondition_stage=run.current_stage.value,
            precondition_gate=run.human_gate.value if run.human_gate else None,
            status=OperatorActionStatus.COMPLETED,
            summary=summary,
            resulting_stage=OrchestrationStage.COMPLETED.value,
            resulting_outcome=OrchestrationStopOutcome.COMPLETED.value,
            resulting_gate=None,
            parameters_json=sanitized_params,
            result_payload_json={
                "decision_status": decision.status.value,
                "classification": decision.classification.value,
            },
        )
        self.uow.operator_actions.save(record)
        self.uow.commit()

        return OperatorActionResult(
            action_request_id=request.action_request_id,
            action_type=request.action_type,
            status=OperatorActionStatus.COMPLETED,
            summary=summary,
            resulting_stage=OrchestrationStage.COMPLETED,
            resulting_outcome=OrchestrationStopOutcome.COMPLETED,
            payload=record.result_payload_json,
        )

    def list_action_history(self, run_id: str, limit: int = 50) -> list[OperatorActionRecord]:
        """Fetch audit trail of operator actions executed for a run."""
        return self.uow.operator_actions.list_by_run(run_id, limit=limit)

    def resume_saga(self, saga_id: str, actor_identity: str = "operator") -> Any:
        """Manually trigger saga resumption with row-locking idempotency."""
        saga = self.uow.durable_sagas.get_by_id(saga_id)
        if not saga:
            raise ValueError(f"DurableSaga '{saga_id}' not found.")

        rec_svc = RecoveryConvergenceService(self.uow, project_root=self.project_root)
        rec_svc.reconcile_saga(saga_id, source=RecoverySource.CONTROL_PLANE)
        return self.uow.durable_sagas.get_by_id(saga_id) or saga
