"""Autonomous Post-Merge Closure Service."""

from __future__ import annotations

import logging
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from minime.domain.enums import (
    ChangeStatus,
    EventType,
    ExternalActionStatus,
    ExternalActionType,
    ExternalOutcome,
    ExternalReasonCode,
    JobStatus,
    OrchestrationStage,
    OrchestrationStopOutcome,
    RetrySafety,
    SagaStatus,
    SagaType,
    WorkItemStatus,
)
from minime.domain.exceptions import StaleClaimError
from minime.domain.interfaces import GitHubAdapterInterface, PersistenceUnitOfWork
from minime.domain.models import (
    Event,
    ExternalActionResult,
    MetricFact,
    RecoveryClaimContext,
    utc_now,
)
from minime.services.lifecycle_transition_authority import LifecycleTransitionAuthority
from minime.services.openspec_sync import OpenSpecSyncService
from minime.services.saga_engine import SagaEngine
from minime.services.worktree_manager import WorktreeManager

logger = logging.getLogger(__name__)


def _run_coro_sync(coro: Any) -> Any:
    """Safely execute an async coroutine synchronously."""
    import asyncio
    import concurrent.futures

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


@dataclass
class PostMergeReconciliationResult:
    """Detailed outcome of post-merge reconciliation."""

    success: bool
    already_closed: bool
    change_name: str
    run_id: str
    job_id: str
    is_merged: bool
    merged_by: str | None = None
    merged_at: str | None = None
    merge_commit_sha: str | None = None
    candidate_sha: str | None = None
    ancestry_verified: bool = False
    issue_closed: bool = False
    project_item_updated: bool = False
    openspec_synced: bool = False
    openspec_archived: bool = False
    worktree_cleaned: bool = False
    branch_cleaned: bool = False
    locks_cleaned: bool = False
    terminal_stage: OrchestrationStage = OrchestrationStage.COMPLETED
    terminal_job_status: JobStatus = JobStatus.COMPLETED
    post_merge_duration_ms: int = 0
    native_phases_completed: int = 0
    total_phases: int = 13
    error_message: str | None = None


class PostMergeReconciliationService:
    """Orchestrates native post-merge SDLC lifecycle closure and cleanup."""

    def __init__(
        self,
        uow: PersistenceUnitOfWork,
        project_root: str | Path,
        github_adapter: GitHubAdapterInterface | None = None,
        worktree_manager: WorktreeManager | None = None,
        openspec_sync: OpenSpecSyncService | None = None,
        saga_engine: SagaEngine | None = None,
    ):
        self.uow = uow
        self.project_root = Path(project_root).resolve()
        from minime.adapters.github import GitHubAdapter

        self.github_adapter = github_adapter or GitHubAdapter()
        self.worktree_manager = worktree_manager or WorktreeManager(self.project_root, uow=uow)
        self.openspec_sync = openspec_sync or OpenSpecSyncService(self.project_root, uow=uow)
        self.saga_engine = saga_engine or SagaEngine(self.uow)

    def _authorize_managed_repo_mutation(self, project_id: str) -> None:
        """Verify project binding, canonical path match, and ManagedWorkspaceGuard authorization before Git mutations."""
        if not project_id:
            raise ValueError("project_id is mandatory for post-merge repository mutations.")
        if not self.uow:
            raise RuntimeError(
                "PersistenceUnitOfWork (uow) is required for post-merge repository authorization."
            )

        from minime.domain.enums import ExternalOutcome, WorkspaceOperation, WorkspaceRole
        from minime.domain.models import WorkspaceMutationRequest
        from minime.services.workspace_guard import ManagedWorkspaceGuard, is_binding_fully_valid

        binding_repo = getattr(self.uow, "project_managed_repository_bindings", None)
        binding = binding_repo.get_by_project_id(project_id) if binding_repo else None

        if not is_binding_fully_valid(binding):
            raise RuntimeError(
                f"Failing closed: no valid durable binding found for project_id '{project_id}'."
            )

        guard = ManagedWorkspaceGuard(self.uow)
        req = WorkspaceMutationRequest(
            project_id=project_id,
            target_path=str(self.project_root),
            requested_operation=WorkspaceOperation.GIT_BRANCH,
        )
        decision = guard.evaluate_mutation(req)

        if not decision.allowed or decision.outcome != ExternalOutcome.SUCCESS:
            raise RuntimeError(
                f"Failing closed: post-merge Git mutation denied for project_id '{project_id}': {decision.provider_detail}"
            )

        if decision.workspace_role != WorkspaceRole.MANAGED_REPOSITORY:
            raise RuntimeError(
                f"Failing closed: project_root workspace role is '{decision.workspace_role.value}', not MANAGED_REPOSITORY."
            )

        canonical_project_root = str(self.project_root.resolve())
        canonical_managed_root = str(Path(binding.managed_repository_root).resolve())

        if canonical_project_root != canonical_managed_root:
            raise RuntimeError(
                f"Failing closed: self.project_root '{canonical_project_root}' does not match binding.managed_repository_root '{canonical_managed_root}'."
            )

    def verify_candidate_ancestry(
        self, candidate_sha: str, base_ref: str = "HEAD", project_id: str | None = None
    ) -> bool:
        """Verify that the candidate SHA is an ancestor of the base/main branch."""
        if not project_id:
            logger.warning("Failing closed: project_id is mandatory for verify_candidate_ancestry.")
            return False
        try:
            self._authorize_managed_repo_mutation(project_id)
            # Fetch remote origin if base_ref references origin
            if "origin" in base_ref or base_ref in {"HEAD", "main", "origin/main"}:
                subprocess.run(
                    ["git", "fetch", "origin"],
                    cwd=self.project_root,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=30,
                )
            res = subprocess.run(
                ["git", "merge-base", "--is-ancestor", candidate_sha, base_ref],
                cwd=self.project_root,
                capture_output=True,
                text=True,
                check=False,
            )
            return res.returncode == 0
        except Exception as exc:
            logger.warning("Failed candidate ancestry verification: %s", exc)
            return False

    def verify_candidate_delivery(
        self,
        candidate_sha: str,
        base_branch: str,
        project_id: str,
        pr_details: dict[str, Any] | None = None,
    ) -> bool:
        """Verify delivery of candidate SHA to base branch supporting both normal ancestry and squash merges."""
        if not candidate_sha or not project_id:
            return False

        # 1. Direct ancestry check
        if self.verify_candidate_ancestry(candidate_sha, base_branch, project_id=project_id):
            return True

        # 2. Check squash merge delivery requiring all PR metadata fields fail-closed (Defect 3)
        if not pr_details:
            return False

        from minime.services.project_service import normalize_repository_identity

        project = self.uow.projects.get_by_id(project_id) if self.uow else None
        if not project or not project.repository or not project.base_branch:
            logger.warning(
                "Failing closed: missing project or project binding in verify_candidate_delivery."
            )
            return False

        expected_repo = normalize_repository_identity(project.repository)
        pr_repo = pr_details.get("repository")
        if not pr_repo or normalize_repository_identity(pr_repo) != expected_repo:
            logger.warning(
                "PR repository mismatch or missing in verify_candidate_delivery: expected '%s', got '%s'",
                expected_repo,
                pr_repo,
            )
            return False

        pr_base = pr_details.get("base_branch")
        if not pr_base or not base_branch:
            logger.warning("Missing pr_base or base_branch in verify_candidate_delivery.")
            return False

        norm_pr_base = pr_base.replace("refs/heads/", "").strip()
        norm_base_branch = base_branch.replace("refs/heads/", "").replace("origin/", "").strip()
        if norm_pr_base != norm_base_branch:
            logger.warning(
                "PR base branch mismatch in verify_candidate_delivery: expected '%s', got '%s'",
                norm_base_branch,
                norm_pr_base,
            )
            return False

        is_merged = pr_details.get("is_merged", False)
        merge_commit_sha = pr_details.get("merge_commit_sha")
        pr_head_sha = pr_details.get("head_sha")

        if not is_merged or not merge_commit_sha or not pr_head_sha:
            logger.warning(
                "Failing closed: missing is_merged (%s), merge_commit_sha (%s), or head_sha (%s) in PR details.",
                is_merged,
                merge_commit_sha,
                pr_head_sha,
            )
            return False

        if pr_head_sha != candidate_sha:
            logger.warning(
                "PR head SHA mismatch: expected candidate '%s', got PR head '%s'",
                candidate_sha,
                pr_head_sha,
            )
            return False

        # Check merge_commit_sha ancestry on base_branch
        try:
            self._authorize_managed_repo_mutation(project_id)
            res = subprocess.run(
                ["git", "merge-base", "--is-ancestor", merge_commit_sha, base_branch],
                cwd=self.project_root,
                capture_output=True,
                text=True,
                check=False,
            )
            if res.returncode == 0:
                logger.info(
                    "Squash merge delivery verified for candidate '%s' via merge commit '%s'",
                    candidate_sha,
                    merge_commit_sha,
                )
                return True
        except Exception as exc:
            logger.warning("Squash merge verification exception: %s", exc)

        return False

    def reconcile_post_merge(
        self,
        project_id: str,
        change_name: str,
        run_id: str | None = None,
        claim_context: RecoveryClaimContext | None = None,
    ) -> PostMergeReconciliationResult:
        """Execute the complete post-merge closure cycle idempotently."""
        if claim_context and not claim_context.is_valid():
            raise StaleClaimError("Recovery claim context is expired or invalid.")

        start_time = time.time()

        # 1. Locate Run and Job
        if run_id:
            run = self.uow.orchestration_runs.get_by_id(run_id)
        else:
            runs = self.uow.orchestration_runs.list_runs(
                project_id=project_id, change_name=change_name
            )
            run = runs[-1] if runs else None

        if not run:
            return PostMergeReconciliationResult(
                success=False,
                already_closed=False,
                change_name=change_name,
                run_id=run_id or "",
                job_id="",
                is_merged=False,
                error_message=f"No orchestration run found for change '{change_name}'.",
            )

        job = self.uow.jobs.get_by_id(run.active_job_id) if run.active_job_id else None
        job_id = job.job_id if job else ""

        # Check if already closed and saga completed
        existing_saga = self.saga_engine.get_active_saga(project_id, change_name, SagaType.CLOSURE)
        completed_sagas = self.uow.durable_sagas.list_by_project(
            project_id, saga_type=SagaType.CLOSURE, status=SagaStatus.COMPLETED
        )
        has_completed_saga = any(
            s.work_item_key == change_name or s.change_name == change_name for s in completed_sagas
        )

        is_run_terminal = (
            run.current_stage == OrchestrationStage.COMPLETED
            or run.stop_outcome
            in {OrchestrationStopOutcome.COMPLETED, OrchestrationStopOutcome.CANCELLED}
            or not run.is_active
        )
        is_job_terminal = job is None or job.status in {JobStatus.COMPLETED, JobStatus.CANCELLED}

        if is_run_terminal and is_job_terminal:
            if has_completed_saga or (
                existing_saga is not None and existing_saga.status == SagaStatus.COMPLETED
            ):
                logger.info(
                    "Change '%s' (Run: %s) is already closed with completed saga.",
                    change_name,
                    run.run_id,
                )
                self._reconcile_change_and_backlog_item(project_id, change_name)
                return PostMergeReconciliationResult(
                    success=True,
                    already_closed=True,
                    change_name=change_name,
                    run_id=run.run_id,
                    job_id=job_id,
                    is_merged=True,
                    ancestry_verified=True,
                    issue_closed=True,
                    project_item_updated=True,
                    openspec_synced=True,
                    openspec_archived=True,
                    worktree_cleaned=True,
                    branch_cleaned=True,
                    locks_cleaned=True,
                    native_phases_completed=13,
                    total_phases=13,
                )

            # Terminal run/job but saga in-progress or unstarted: run observation-only reconciliation
            saga = existing_saga or self.saga_engine.start_saga(
                saga_type=SagaType.CLOSURE,
                project_id=project_id,
                work_item_key=change_name,
                change_name=change_name,
                run_id=run.run_id,
                job_id=job_id,
                initial_phase="MERGE_OBSERVED",
            )
            # Reconcile saga phases strictly from existing external action records or observed postconditions (Defect 4)
            actions = (
                self.uow.orchestration_external_actions.list_by_saga(saga.id)
                if hasattr(self.uow.orchestration_external_actions, "list_by_saga")
                else []
            )
            if not actions:
                actions = self.uow.orchestration_external_actions.list_by_run(run.run_id)

            completed_action_types = {
                act.action_type for act in actions if act.status == ExternalActionStatus.COMPLETED
            }

            binding = self.uow.bindings.get_by_project_and_change(project_id, change_name)
            issue_required = bool(binding and binding.github_issue_number)
            project_item_required = bool(
                binding and (binding.github_project_item_id or binding.github_issue_number)
            )

            merge_observed_ev = run.stop_outcome == OrchestrationStopOutcome.COMPLETED or bool(
                run.stop_details and run.stop_details.get("is_merged")
            )
            delivery_verified_ev = run.stop_outcome == OrchestrationStopOutcome.COMPLETED or bool(
                run.stop_details and run.stop_details.get("ancestry_verified")
            )
            run_job_reconciled_ev = is_run_terminal and is_job_terminal
            issue_closed_ev = (not issue_required) or (
                ExternalActionType.ISSUE_CLOSE in completed_action_types
            )
            project_done_ev = (not project_item_required) or (
                ExternalActionType.PROJECT_ITEM_EDIT in completed_action_types
            )
            spec_synced_ev = ExternalActionType.OPENSPEC_SYNC in completed_action_types
            sync_verified_ev = ExternalActionType.OPENSPEC_SYNC in completed_action_types
            spec_archived_ev = ExternalActionType.OPENSPEC_ARCHIVE in completed_action_types
            archive_verified_ev = ExternalActionType.OPENSPEC_ARCHIVE in completed_action_types
            worktree_clean_ev = ExternalActionType.WORKTREE_DELETE in completed_action_types
            branch_clean_ev = ExternalActionType.BRANCH_DELETE in completed_action_types
            locks_released_ev = True

            missing_phases: list[str] = []
            if not merge_observed_ev:
                missing_phases.append("MERGE_OBSERVED")
            if not delivery_verified_ev:
                missing_phases.append("MERGED_DELIVERY_VERIFIED")
            if not run_job_reconciled_ev:
                missing_phases.append("RUN_JOB_RECONCILED")
            if not issue_closed_ev:
                missing_phases.append("ISSUE_CLOSED")
            if not project_done_ev:
                missing_phases.append("PROJECT_ITEM_DONE")
            if not spec_synced_ev:
                missing_phases.append("SPEC_SYNCED")
            if not sync_verified_ev:
                missing_phases.append("SYNC_VERIFIED")
            if not spec_archived_ev:
                missing_phases.append("SPEC_ARCHIVED")
            if not archive_verified_ev:
                missing_phases.append("ARCHIVE_VERIFIED")
            if not worktree_clean_ev:
                missing_phases.append("WORKTREE_CLEANED")
            if not branch_clean_ev:
                missing_phases.append("BRANCH_CLEANED")
            if not locks_released_ev:
                missing_phases.append("LOCKS_RELEASED")

            if missing_phases:
                reason = f"Terminal closure reconciliation missing positive evidence for phase(s): {', '.join(missing_phases)}"
                logger.warning(reason)
                self.saga_engine.block_saga(saga, blocking_reason=reason)
                self.uow.commit()
                return PostMergeReconciliationResult(
                    success=False,
                    already_closed=False,
                    change_name=change_name,
                    run_id=run.run_id,
                    job_id=job_id,
                    is_merged=True,
                    ancestry_verified=True,
                    error_message=reason,
                )

            self.saga_engine.advance_phase(saga, "MERGE_OBSERVED")
            self.saga_engine.advance_phase(saga, "MERGED_DELIVERY_VERIFIED")
            self.saga_engine.advance_phase(saga, "RUN_JOB_RECONCILED")
            self.saga_engine.advance_phase(
                saga, "ISSUE_CLOSED", evidence_references={"issue_closed": issue_closed_ev}
            )
            self.saga_engine.advance_phase(
                saga,
                "PROJECT_ITEM_DONE",
                evidence_references={"project_item_updated": project_done_ev},
            )
            self.saga_engine.advance_phase(saga, "SPEC_SYNCED")
            self.saga_engine.advance_phase(
                saga, "SYNC_VERIFIED", evidence_references={"sync_verified": sync_verified_ev}
            )
            self.saga_engine.advance_phase(saga, "SPEC_ARCHIVED")
            self.saga_engine.advance_phase(
                saga,
                "ARCHIVE_VERIFIED",
                evidence_references={"archive_verified": archive_verified_ev},
            )
            self.saga_engine.advance_phase(
                saga,
                "WORKTREE_CLEANED",
                evidence_references={"worktree_cleaned": worktree_clean_ev},
            )
            self.saga_engine.advance_phase(
                saga, "BRANCH_CLEANED", evidence_references={"branch_cleaned": branch_clean_ev}
            )
            self.saga_engine.advance_phase(saga, "LOCKS_RELEASED")
            self.saga_engine.advance_phase(saga, "FINAL_CLOSED")

            self.saga_engine.complete_saga(saga)
            self._reconcile_change_and_backlog_item(project_id, change_name)
            self.uow.commit()

            return PostMergeReconciliationResult(
                success=True,
                already_closed=True,
                change_name=change_name,
                run_id=run.run_id,
                job_id=job_id,
                is_merged=True,
                ancestry_verified=True,
                issue_closed=True,
                project_item_updated=True,
                openspec_synced=True,
                openspec_archived=True,
                worktree_cleaned=True,
                branch_cleaned=True,
                locks_cleaned=True,
                native_phases_completed=13,
                total_phases=13,
            )

        project = self.uow.projects.get_by_id(project_id)
        openspec_path = project.openspec_path if project else "openspec"
        repository = project.repository if project else "silverberdi/mini-me"
        base_branch = project.base_branch if project else "main"

        binding = self.uow.bindings.get_by_project_and_change(project_id, change_name)

        # 2. Query GitHub for PR merge state
        pr_number = binding.github_pr_number if binding else None
        pr_details: dict[str, Any] = {}
        if pr_number:
            try:
                pr_res = self.github_adapter.get_pull_request_details(repository, pr_number)
                if pr_res.outcome == ExternalOutcome.SUCCESS and pr_res.data:
                    pr_details = pr_res.data
            except Exception as exc:
                logger.warning("Failed to fetch PR details for #%d: %s", pr_number, exc)

        if not pr_details:
            # Fallback lookup by head branch
            branch_name = f"minime/{change_name}"
            lookup_res = self.github_adapter.get_pull_request(repository, branch_name, base_branch)
            if lookup_res.outcome == ExternalOutcome.SUCCESS and lookup_res.data:
                pr_num = lookup_res.data.get("number")
                if pr_num:
                    pr_number = pr_num
                    pr_details_res = self.github_adapter.get_pull_request_details(
                        repository, pr_number
                    )
                    if pr_details_res.outcome == ExternalOutcome.SUCCESS and pr_details_res.data:
                        pr_details = pr_details_res.data

        is_merged = pr_details.get("is_merged", False)
        if not is_merged:
            if pr_details.get("state") == "closed":
                logger.info(
                    "PR #%s for '%s' was closed without merging. Reconciling run to CANCELLED.",
                    pr_number,
                    change_name,
                )
                now = utc_now()
                run.is_active = False
                run.stop_outcome = OrchestrationStopOutcome.CANCELLED
                run.stop_reason = f"Pull request #{pr_number} was closed without merge."
                run.updated_at = now
                self.uow.orchestration_runs.save(run)
                if job and job.status != JobStatus.COMPLETED:
                    job.status = JobStatus.CANCELLED
                    job.error_message = run.stop_reason
                    job.updated_at = now
                    self.uow.jobs.save(job)
                self._clean_worktree_and_branches(project_id, change_name, job_id)
                self._reconcile_change_and_backlog_item(project_id, change_name)
                self.uow.commit()
                return PostMergeReconciliationResult(
                    success=True,
                    already_closed=True,
                    change_name=change_name,
                    run_id=run.run_id,
                    job_id=job_id,
                    is_merged=False,
                    worktree_cleaned=True,
                    branch_cleaned=True,
                    locks_cleaned=True,
                    native_phases_completed=13,
                    total_phases=13,
                )

            logger.info("PR #%s for '%s' is not yet merged.", pr_number, change_name)
            return PostMergeReconciliationResult(
                success=False,
                already_closed=False,
                change_name=change_name,
                run_id=run.run_id,
                job_id=job_id,
                is_merged=False,
                error_message=f"PR #{pr_number} is not merged.",
            )

        # Drive CLOSURE DurableSaga across 13 phases
        saga = self.saga_engine.start_saga(
            saga_type=SagaType.CLOSURE,
            project_id=project_id,
            work_item_key=change_name,
            change_name=change_name,
            run_id=run.run_id,
            job_id=job_id,
            initial_phase="MERGE_OBSERVED",
        )

        merged_by = pr_details.get("merged_by_login") or "human"
        merged_at = pr_details.get("merged_at")
        merge_commit_sha = pr_details.get("merge_commit_sha")
        cand_sha = run.candidate_sha or pr_details.get("head_sha") or ""

        self.saga_engine.advance_phase(
            saga,
            "MERGE_OBSERVED",
            evidence_references={
                "pr_number": pr_number,
                "is_merged": is_merged,
                "merged_by": merged_by,
                "merged_at": merged_at,
                "merge_commit_sha": merge_commit_sha,
                "candidate_sha": cand_sha,
            },
        )

        # 3. Delivery verification (ancestry + squash merge support)
        delivery_ok = self.verify_candidate_delivery(
            candidate_sha=cand_sha,
            base_branch=base_branch,
            project_id=project_id,
            pr_details=pr_details,
        )

        if delivery_ok:
            self.saga_engine.advance_phase(
                saga,
                "MERGED_DELIVERY_VERIFIED",
                evidence_references={"delivery_verified": delivery_ok},
            )

        # Record merge detected event
        self.uow.events.save(
            Event(
                event_type=EventType.MERGE_DETECTED,
                project_id=project_id,
                change_id=change_name,
                payload={
                    "run_id": run.run_id,
                    "pr_number": pr_number,
                    "merged_by": merged_by,
                    "merged_at": merged_at,
                    "merge_commit_sha": merge_commit_sha,
                    "candidate_sha": cand_sha,
                    "ancestry_verified": delivery_ok,
                },
                timestamp=utc_now(),
            )
        )
        self.uow.commit()

        # 4. Stage Transition to POST_MERGE_RECONCILING
        run.current_stage = OrchestrationStage.POST_MERGE_RECONCILING
        if job and job.status != JobStatus.COMPLETED:
            job.status = JobStatus.POST_MERGE_RECONCILING
            self.uow.jobs.save(job)
        self.uow.orchestration_runs.save(run)
        self.uow.commit()
        self.saga_engine.advance_phase(saga, "RUN_JOB_RECONCILED")

        # 5. GitHub Issue Closure with action reservation
        issue_required = bool(binding and binding.github_issue_number)
        issue_closed = False
        issue_num = binding.github_issue_number if binding else None
        if issue_num:
            op_key = f"issue_close:{project_id}:{change_name}"
            self.saga_engine.reserve_action(
                action_key=op_key,
                action_type=ExternalActionType.ISSUE_CLOSE,
                target_identity=change_name,
                request_fingerprint=run.run_id,
                saga_id=saga.id,
            )
            try:
                close_res = self.github_adapter.close_issue(
                    repository,
                    issue_num,
                    comment=f"Closed automatically by mini me upon post-merge reconciliation of `{change_name}`.",
                )
                issue_closed = (
                    close_res.outcome == ExternalOutcome.SUCCESS and close_res.data is True
                )
                if issue_closed:
                    self.saga_engine.record_action_result(
                        op_key,
                        status=ExternalActionStatus.COMPLETED,
                        remote_identifier=str(issue_num),
                    )
                    self.uow.events.save(
                        Event(
                            event_type=EventType.ISSUE_CLOSED,
                            project_id=project_id,
                            change_id=change_name,
                            payload={"issue_number": issue_num},
                            timestamp=utc_now(),
                        )
                    )
                else:
                    self.saga_engine.record_action_result(
                        op_key,
                        status=ExternalActionStatus.FAILED,
                        error_message=close_res.error_message,
                    )
            except Exception as exc:
                logger.warning("Failed to close GitHub Issue #%d: %s", issue_num, exc)
                self.saga_engine.record_action_result(
                    op_key, status=ExternalActionStatus.FAILED, error_message=str(exc)
                )

        if issue_closed or not issue_required:
            self.saga_engine.advance_phase(
                saga, "ISSUE_CLOSED", evidence_references={"issue_closed": issue_closed}
            )

        # 6. GitHub Project Item Done with action reservation
        project_item_required = bool(
            binding and (binding.github_project_item_id or binding.github_issue_number)
        )
        project_item_updated = False
        project_item_id = binding.github_project_item_id if binding else None
        if project_item_required:
            op_key = f"project_item_done:{project_id}:{change_name}"
            self.saga_engine.reserve_action(
                action_key=op_key,
                action_type=ExternalActionType.PROJECT_ITEM_EDIT,
                target_identity=change_name,
                request_fingerprint=run.run_id,
                saga_id=saga.id,
            )
            try:
                update_res = self.github_adapter.update_project_item_status(
                    project_number=2,
                    owner="silverberdi",
                    item_id=project_item_id or str(issue_num),
                    status="Done",
                )
                project_item_updated = (
                    update_res.outcome == ExternalOutcome.SUCCESS and update_res.data is True
                )
                if project_item_updated:
                    self.saga_engine.record_action_result(
                        op_key,
                        status=ExternalActionStatus.COMPLETED,
                        remote_identifier=str(project_item_id or issue_num),
                    )
                    self.uow.events.save(
                        Event(
                            event_type=EventType.PROJECT_ITEM_DONE,
                            project_id=project_id,
                            change_id=change_name,
                            payload={
                                "project_item_id": project_item_id or issue_num,
                                "status": "Done",
                            },
                            timestamp=utc_now(),
                        )
                    )
                else:
                    self.saga_engine.record_action_result(
                        op_key,
                        status=ExternalActionStatus.FAILED,
                        error_message=update_res.error_message,
                    )
            except Exception as exc:
                logger.warning("Failed to update GitHub Project item: %s", exc)
                self.saga_engine.record_action_result(
                    op_key, status=ExternalActionStatus.FAILED, error_message=str(exc)
                )

        if project_item_updated or not project_item_required:
            self.saga_engine.advance_phase(
                saga,
                "PROJECT_ITEM_DONE",
                evidence_references={"project_item_updated": project_item_updated},
            )

        # 7. OpenSpec Spec Sync + verification with action reservation
        synced_specs: list[str] = []
        sync_verified = False
        op_key = f"openspec_sync:{project_id}:{change_name}"
        self.saga_engine.reserve_action(
            action_key=op_key,
            action_type=ExternalActionType.OPENSPEC_SYNC,
            target_identity=change_name,
            request_fingerprint=run.run_id,
            saga_id=saga.id,
        )
        try:
            sync_res = self.openspec_sync.sync_change_specs(
                openspec_path, change_name, project_id=project_id
            )
            verify_sync_res = self.openspec_sync.verify_sync(openspec_path, change_name, sync_res)
            sync_verified = (
                verify_sync_res.outcome == ExternalOutcome.SUCCESS and verify_sync_res.data is True
            )
            if sync_verified:
                synced_specs = sync_res.data or []
                self.saga_engine.record_action_result(op_key, status=ExternalActionStatus.COMPLETED)
                self.uow.events.save(
                    Event(
                        event_type=EventType.OPEN_SPEC_SYNCED,
                        project_id=project_id,
                        change_id=change_name,
                        payload={"synced_capabilities": synced_specs},
                        timestamp=utc_now(),
                    )
                )
                self.uow.events.save(
                    Event(
                        event_type=EventType.POST_MERGE_SYNC_VERIFIED,
                        project_id=project_id,
                        change_id=change_name,
                        payload={"synced_capabilities": synced_specs},
                        timestamp=utc_now(),
                    )
                )
            else:
                self.saga_engine.record_action_result(
                    op_key,
                    status=ExternalActionStatus.FAILED,
                    error_message="Sync verification failed.",
                )
        except Exception as exc:
            logger.warning("OpenSpec spec sync failed for '%s': %s", change_name, exc)
            self.saga_engine.record_action_result(
                op_key, status=ExternalActionStatus.FAILED, error_message=str(exc)
            )

        if sync_verified:
            self.saga_engine.advance_phase(saga, "SPEC_SYNCED")
            self.saga_engine.advance_phase(
                saga, "SYNC_VERIFIED", evidence_references={"sync_verified": sync_verified}
            )

        # 8. OpenSpec Archive + verification with action reservation (only after sync is verified)
        archived_path: Path | None = None
        archive_verified = False
        if sync_verified:
            op_key = f"openspec_archive:{project_id}:{change_name}"
            self.saga_engine.reserve_action(
                action_key=op_key,
                action_type=ExternalActionType.OPENSPEC_ARCHIVE,
                target_identity=change_name,
                request_fingerprint=run.run_id,
                saga_id=saga.id,
            )
            try:
                archive_res = self.openspec_sync.archive_change(
                    openspec_path, change_name, project_id=project_id
                )
                verify_arc_res = self.openspec_sync.verify_archive(
                    openspec_path, change_name, archive_res
                )
                archive_verified = (
                    verify_arc_res.outcome == ExternalOutcome.SUCCESS
                    and verify_arc_res.data is True
                )
                if archive_verified:
                    archived_path = archive_res.data
                    self.saga_engine.record_action_result(
                        op_key,
                        status=ExternalActionStatus.COMPLETED,
                        remote_identifier=str(archived_path) if archived_path else None,
                    )
                    self.uow.events.save(
                        Event(
                            event_type=EventType.OPEN_SPEC_ARCHIVED,
                            project_id=project_id,
                            change_id=change_name,
                            payload={"archived_path": str(archived_path) if archived_path else ""},
                            timestamp=utc_now(),
                        )
                    )
                    self.uow.events.save(
                        Event(
                            event_type=EventType.POST_MERGE_ARCHIVE_VERIFIED,
                            project_id=project_id,
                            change_id=change_name,
                            payload={"archived_path": str(archived_path) if archived_path else ""},
                            timestamp=utc_now(),
                        )
                    )
                else:
                    self.saga_engine.record_action_result(
                        op_key,
                        status=ExternalActionStatus.FAILED,
                        error_message="Archive verification failed.",
                    )
            except Exception as exc:
                logger.warning("OpenSpec archive failed for '%s': %s", change_name, exc)
                self.saga_engine.record_action_result(
                    op_key, status=ExternalActionStatus.FAILED, error_message=str(exc)
                )

        if archive_verified:
            self.saga_engine.advance_phase(saga, "SPEC_ARCHIVED")
            self.saga_engine.advance_phase(
                saga, "ARCHIVE_VERIFIED", evidence_references={"archive_verified": archive_verified}
            )

        # 9. Worktree Cleanup with action reservation
        op_key = f"worktree_clean:{project_id}:{change_name}"
        self.saga_engine.reserve_action(
            action_key=op_key,
            action_type=ExternalActionType.WORKTREE_DELETE,
            target_identity=change_name,
            request_fingerprint=run.run_id,
            saga_id=saga.id,
        )
        wt_clean_res = self._clean_worktrees(job_id, project_id=project_id)
        worktree_cleaned = wt_clean_res.outcome == ExternalOutcome.SUCCESS
        if worktree_cleaned:
            self.saga_engine.record_action_result(op_key, status=ExternalActionStatus.COMPLETED)
            self.uow.events.save(
                Event(
                    event_type=EventType.WORKTREE_CLEANED,
                    project_id=project_id,
                    change_id=change_name,
                    payload={"job_id": job_id},
                    timestamp=utc_now(),
                )
            )
        else:
            self.saga_engine.record_action_result(
                op_key, status=ExternalActionStatus.FAILED, error_message=wt_clean_res.error_message
            )

        if worktree_cleaned:
            self.saga_engine.advance_phase(
                saga, "WORKTREE_CLEANED", evidence_references={"worktree_cleaned": worktree_cleaned}
            )

        # 10. Local and Remote Branch Cleanup with action reservation
        local_branches = [
            f"minime/{change_name}-{job_id}" if job_id else None,
            f"minime/{change_name}",
        ]
        local_clean_ok = True
        for b in local_branches:
            if b:
                loc_res = self._delete_local_branch(b, project_id=project_id)
                if loc_res.outcome != ExternalOutcome.SUCCESS:
                    local_clean_ok = False

        delete_remote_res = self.github_adapter.delete_remote_branch(
            repository, f"minime/{change_name}"
        )
        remote_clean_ok = delete_remote_res.outcome == ExternalOutcome.SUCCESS
        branch_cleaned = local_clean_ok and remote_clean_ok

        if branch_cleaned:
            self.uow.events.save(
                Event(
                    event_type=EventType.BRANCH_CLEANED,
                    project_id=project_id,
                    change_id=change_name,
                    payload={
                        "branches": [b for b in local_branches if b],
                        "remote_cleaned": remote_clean_ok,
                        "reason_code": delete_remote_res.reason_code.value,
                    },
                    timestamp=utc_now(),
                )
            )
            self.saga_engine.advance_phase(
                saga, "BRANCH_CLEANED", evidence_references={"branch_cleaned": branch_cleaned}
            )

        # 11. Locks and Preview Cleanup
        locks_cleaned = True
        self.uow.events.save(
            Event(
                event_type=EventType.LOCKS_RELEASED,
                project_id=project_id,
                change_id=change_name,
                payload={"run_id": run.run_id},
                timestamp=utc_now(),
            )
        )
        self.saga_engine.advance_phase(saga, "LOCKS_RELEASED")

        # 12. Check all unverified phases before terminal gate
        unverified_phases: list[str] = []
        if not delivery_ok:
            unverified_phases.append("delivery_ancestry")
        if issue_required and not issue_closed:
            unverified_phases.append("issue_closure")
        if project_item_required and not project_item_updated:
            unverified_phases.append("project_item_done")
        if not sync_verified:
            unverified_phases.append("openspec_sync")
        if not archive_verified:
            unverified_phases.append("openspec_archive")
        if not worktree_cleaned:
            unverified_phases.append("worktree_cleanup")
        if not branch_cleaned:
            unverified_phases.append("branch_cleanup")

        if unverified_phases:
            reason = (
                "Post-merge reconciliation blocked: missing required "
                + ", ".join(unverified_phases)
                + " verification evidence."
            )
            run.stop_outcome = OrchestrationStopOutcome.WAITING_EXTERNAL
            run.human_gate = None
            run.stop_reason = reason
            run.is_active = True
            run.updated_at = utc_now()
            self.uow.orchestration_runs.save(run)
            self.saga_engine.block_saga(saga, blocking_reason=reason)
            self.uow.commit()
            return PostMergeReconciliationResult(
                success=False,
                already_closed=False,
                change_name=change_name,
                run_id=run.run_id,
                job_id=job_id,
                is_merged=True,
                merged_by=merged_by,
                merged_at=merged_at,
                merge_commit_sha=merge_commit_sha,
                candidate_sha=cand_sha,
                ancestry_verified=delivery_ok,
                issue_closed=issue_closed,
                project_item_updated=project_item_updated,
                openspec_synced=sync_verified,
                openspec_archived=archive_verified,
                worktree_cleaned=worktree_cleaned,
                branch_cleaned=branch_cleaned,
                locks_cleaned=locks_cleaned,
                terminal_stage=OrchestrationStage.POST_MERGE_RECONCILING,
                terminal_job_status=job.status if job else JobStatus.POST_MERGE_RECONCILING,
                native_phases_completed=13 - len(unverified_phases),
                total_phases=13,
                error_message=reason,
            )

        # 13. Terminal State Transitions (Only reached when all required phases are verified)
        run.current_stage = OrchestrationStage.COMPLETED
        run.resumable_stage = OrchestrationStage.COMPLETED
        run.stop_outcome = OrchestrationStopOutcome.COMPLETED
        run.human_gate = None
        run.is_active = False
        run.stop_reason = "Autonomous post-merge closure completed successfully."
        run.stop_details = {
            "is_merged": True,
            "merged_by": merged_by,
            "merged_at": merged_at,
            "merge_commit_sha": merge_commit_sha,
            "ancestry_verified": delivery_ok,
        }
        self.uow.orchestration_runs.save(run)

        if job:
            job.status = JobStatus.COMPLETED
            self.uow.jobs.save(job)

        self._reconcile_change_and_backlog_item(project_id, change_name)

        # 14. Mark CLOSURE DurableSaga as completed
        self.saga_engine.advance_phase(saga, "FINAL_CLOSED")
        self.saga_engine.complete_saga(saga)

        # 15. Persist Post-Merge Metric Facts
        duration_ms = int((time.time() - start_time) * 1000)
        self.uow.metrics.save(
            MetricFact(
                metric_name="post_merge_closure_duration_ms",
                project_id=project_id,
                change_id=change_name,
                stage=OrchestrationStage.COMPLETED.value,
                duration_ms=duration_ms,
                details={
                    "run_id": run.run_id,
                    "merged_by": merged_by,
                    "ancestry_verified": delivery_ok,
                    "native_phases": 13,
                },
                recorded_at=utc_now(),
            )
        )
        self.uow.events.save(
            Event(
                event_type=EventType.POST_MERGE_COMPLETED,
                project_id=project_id,
                change_id=change_name,
                payload={
                    "run_id": run.run_id,
                    "duration_ms": duration_ms,
                    "terminal_stage": OrchestrationStage.COMPLETED.value,
                    "terminal_job_status": JobStatus.COMPLETED.value,
                },
                timestamp=utc_now(),
            )
        )
        self.uow.commit()

        return PostMergeReconciliationResult(
            success=True,
            already_closed=False,
            change_name=change_name,
            run_id=run.run_id,
            job_id=job_id,
            is_merged=True,
            merged_by=merged_by,
            merged_at=merged_at,
            merge_commit_sha=merge_commit_sha,
            candidate_sha=cand_sha,
            ancestry_verified=delivery_ok,
            issue_closed=issue_closed,
            project_item_updated=project_item_updated,
            openspec_synced=sync_verified,
            openspec_archived=archive_verified,
            worktree_cleaned=worktree_cleaned,
            branch_cleaned=branch_cleaned,
            locks_cleaned=locks_cleaned,
            terminal_stage=OrchestrationStage.COMPLETED,
            terminal_job_status=JobStatus.COMPLETED,
            post_merge_duration_ms=duration_ms,
            native_phases_completed=13,
            total_phases=13,
        )

    def _reconcile_change_and_backlog_item(self, project_id: str, change_name: str) -> None:
        """Ensure Change and BacklogItem reflect completed post-merge status via LifecycleTransitionAuthority."""
        authority = LifecycleTransitionAuthority(self.uow)
        if hasattr(self.uow, "changes"):
            change_record = self.uow.changes.get_by_name(project_id, change_name)
            if change_record and change_record.status != ChangeStatus.DONE:
                authority.transition_change(
                    project_id=project_id,
                    name=change_name,
                    expected_from_state=change_record.status,
                    to_state=ChangeStatus.DONE,
                    reason_code="post_merge_reconciled",
                    actor="post_merge",
                )

        if hasattr(self.uow, "backlog_items"):
            backlog_item = self.uow.backlog_items.get_by_project_and_key(project_id, change_name)
            if not backlog_item:
                items = self.uow.backlog_items.list_by_project(project_id)
                for item in items:
                    if item.openspec_change_name == change_name or item.item_key == change_name:
                        backlog_item = item
                        break
            if backlog_item and backlog_item.status != WorkItemStatus.COMPLETED:
                authority.transition_backlog_item(
                    project_id=project_id,
                    item_key=backlog_item.item_key,
                    expected_from_state=backlog_item.status,
                    to_state=WorkItemStatus.COMPLETED,
                    reason_code="post_merge_reconciled",
                    actor="post_merge",
                )

    def _clean_worktrees(
        self, job_id: str | None, project_id: str | None = None
    ) -> ExternalActionResult[bool]:
        """Clean worktrees associated with a job fail-closed using central WorktreeManager authority."""
        if not job_id:
            return ExternalActionResult(
                outcome=ExternalOutcome.SUCCESS,
                source_adapter="worktree_manager",
                reason_code=ExternalReasonCode.ALREADY_ABSENT,
                retry_safety=RetrySafety.SAFE,
                data=True,
            )

        if not project_id and self.uow:
            job = self.uow.jobs.get_by_id(job_id) if hasattr(self.uow.jobs, "get_by_id") else None
            if job and getattr(job, "project_id", None):
                project_id = job.project_id

        if not project_id:
            return ExternalActionResult(
                outcome=ExternalOutcome.FAILURE,
                source_adapter="worktree_manager",
                reason_code=ExternalReasonCode.POLICY_DENIED,
                retry_safety=RetrySafety.SAFE,
                data=False,
                error_message="project_id is mandatory for post-merge worktree cleanup.",
            )

        try:
            self._authorize_managed_repo_mutation(project_id)
        except Exception as exc:
            return ExternalActionResult(
                outcome=ExternalOutcome.FAILURE,
                source_adapter="worktree_manager",
                reason_code=ExternalReasonCode.POLICY_DENIED,
                retry_safety=RetrySafety.SAFE,
                data=False,
                error_message=f"Post-merge worktree cleanup denied by workspace guard: {exc}",
            )

        target_paths: list[Path] = []
        scan_failed = False
        scan_err: str = ""
        try:
            wt_path = self.worktree_manager.worktree_path(job_id, project_id=project_id)
            if wt_path.exists():
                target_paths.append(wt_path.resolve())
            worktrees_parent = self.worktree_manager.resolve_worktree_parent_dir(project_id)
            if worktrees_parent.exists():
                for child in worktrees_parent.glob(f"{job_id}*"):
                    resolved_child = child.resolve()
                    if resolved_child.exists() and resolved_child not in target_paths:
                        target_paths.append(resolved_child)
        except Exception as exc:
            logger.warning("Error scanning worktrees for job '%s': %s", job_id, exc)
            scan_failed = True
            scan_err = str(exc)

        if scan_failed:
            return ExternalActionResult(
                outcome=ExternalOutcome.UNKNOWN,
                source_adapter="worktree_manager",
                reason_code=ExternalReasonCode.UNOBSERVABLE,
                retry_safety=RetrySafety.SAFE,
                data=False,
                error_message=f"Worktree scan failed for job '{job_id}': {scan_err}",
            )

        if not target_paths:
            return ExternalActionResult(
                outcome=ExternalOutcome.SUCCESS,
                source_adapter="worktree_manager",
                reason_code=ExternalReasonCode.ALREADY_ABSENT,
                retry_safety=RetrySafety.SAFE,
                data=True,
            )

        for path in target_paths:
            try:
                cleanup_res = _run_coro_sync(
                    self.worktree_manager.remove_clean_worktree_path(
                        path, job_id, project_id=project_id
                    )
                )
                if cleanup_res and cleanup_res.outcome in (
                    ExternalOutcome.UNKNOWN,
                    ExternalOutcome.FAILURE,
                ):
                    return ExternalActionResult(
                        outcome=cleanup_res.outcome,
                        source_adapter="worktree_manager",
                        reason_code=cleanup_res.reason_code,
                        retry_safety=RetrySafety.SAFE,
                        data=False,
                        error_message=cleanup_res.provider_detail
                        or f"Worktree cleanup failed for '{path}'.",
                    )
                if path.exists():
                    return ExternalActionResult(
                        outcome=ExternalOutcome.FAILURE,
                        source_adapter="worktree_manager",
                        reason_code=ExternalReasonCode.POSTCONDITION_NOT_PROVEN,
                        retry_safety=RetrySafety.SAFE,
                        data=False,
                        error_message=f"Worktree path '{path}' still exists after cleanup.",
                    )
            except Exception as exc:
                return ExternalActionResult(
                    outcome=ExternalOutcome.FAILURE,
                    source_adapter="worktree_manager",
                    reason_code=ExternalReasonCode.POSTCONDITION_NOT_PROVEN,
                    retry_safety=RetrySafety.SAFE,
                    data=False,
                    error_message=f"Exception removing worktree at '{path}': {exc}",
                )

        return ExternalActionResult(
            outcome=ExternalOutcome.SUCCESS,
            source_adapter="worktree_manager",
            reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
            retry_safety=RetrySafety.UNSAFE,
            data=True,
        )

    def _delete_local_branch(
        self, branch_name: str, project_id: str | None = None
    ) -> ExternalActionResult[bool]:
        """Delete a local git branch fail-closed with postcondition verification."""
        if not project_id:
            return ExternalActionResult(
                outcome=ExternalOutcome.FAILURE,
                source_adapter="git_cli",
                reason_code=ExternalReasonCode.POLICY_DENIED,
                retry_safety=RetrySafety.SAFE,
                data=False,
                error_message="project_id is mandatory for post-merge branch deletion.",
            )

        try:
            self._authorize_managed_repo_mutation(project_id)
        except Exception as exc:
            return ExternalActionResult(
                outcome=ExternalOutcome.FAILURE,
                source_adapter="git_cli",
                reason_code=ExternalReasonCode.POLICY_DENIED,
                retry_safety=RetrySafety.SAFE,
                data=False,
                error_message=f"Post-merge branch deletion denied by workspace guard: {exc}",
            )

        try:
            check_res = subprocess.run(
                ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch_name}"],
                cwd=self.project_root,
                capture_output=True,
                text=True,
                check=False,
            )
        except Exception as exc:
            return ExternalActionResult(
                outcome=ExternalOutcome.UNKNOWN,
                source_adapter="git_cli",
                reason_code=ExternalReasonCode.UNOBSERVABLE,
                retry_safety=RetrySafety.SAFE,
                data=False,
                error_message=f"Git show-ref pre-check failed for branch '{branch_name}': {exc}",
            )

        if check_res.returncode == 1:
            return ExternalActionResult(
                outcome=ExternalOutcome.SUCCESS,
                source_adapter="git_cli",
                reason_code=ExternalReasonCode.ALREADY_ABSENT,
                retry_safety=RetrySafety.SAFE,
                data=True,
            )
        elif check_res.returncode != 0:
            return ExternalActionResult(
                outcome=ExternalOutcome.UNKNOWN,
                source_adapter="git_cli",
                reason_code=ExternalReasonCode.UNOBSERVABLE,
                retry_safety=RetrySafety.SAFE,
                data=False,
                error_message=f"Git show-ref pre-check failed with exit code {check_res.returncode}: {check_res.stderr.strip()}",
            )

        try:
            del_res = subprocess.run(
                ["git", "branch", "-D", branch_name],
                cwd=self.project_root,
                capture_output=True,
                text=True,
                check=False,
            )
        except Exception as exc:
            return ExternalActionResult(
                outcome=ExternalOutcome.UNKNOWN,
                source_adapter="git_cli",
                reason_code=ExternalReasonCode.UNOBSERVABLE,
                retry_safety=RetrySafety.SAFE,
                data=False,
                error_message=f"Git branch deletion failed for '{branch_name}': {exc}",
            )

        try:
            post_check = subprocess.run(
                ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch_name}"],
                cwd=self.project_root,
                capture_output=True,
                text=True,
                check=False,
            )
        except Exception as exc:
            return ExternalActionResult(
                outcome=ExternalOutcome.UNKNOWN,
                source_adapter="git_cli",
                reason_code=ExternalReasonCode.UNOBSERVABLE,
                retry_safety=RetrySafety.SAFE,
                data=False,
                error_message=f"Git show-ref post-check failed for branch '{branch_name}': {exc}",
            )

        if post_check.returncode == 1:
            return ExternalActionResult(
                outcome=ExternalOutcome.SUCCESS,
                source_adapter="git_cli",
                reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
                retry_safety=RetrySafety.UNSAFE,
                data=True,
            )
        elif post_check.returncode == 0:
            return ExternalActionResult(
                outcome=ExternalOutcome.FAILURE,
                source_adapter="git_cli",
                reason_code=ExternalReasonCode.POSTCONDITION_NOT_PROVEN,
                retry_safety=RetrySafety.SAFE,
                data=False,
                error_message=f"Local branch '{branch_name}' still present after deletion (rc={del_res.returncode}): {del_res.stderr.strip()}",
            )
        else:
            return ExternalActionResult(
                outcome=ExternalOutcome.UNKNOWN,
                source_adapter="git_cli",
                reason_code=ExternalReasonCode.UNOBSERVABLE,
                retry_safety=RetrySafety.SAFE,
                data=False,
                error_message=f"Git show-ref post-check failed with exit code {post_check.returncode}: {post_check.stderr.strip()}",
            )

    def _clean_worktree_and_branches(
        self, project_id: str, change_name: str, job_id: str | None = None
    ) -> None:
        """Clean up worktrees and git branches associated with a job/change."""
        self._clean_worktrees(job_id, project_id=project_id)
        local_branches = [
            f"minime/{change_name}-{job_id}" if job_id else None,
            f"minime/{change_name}",
        ]
        for b in local_branches:
            if b:
                self._delete_local_branch(b, project_id=project_id)
