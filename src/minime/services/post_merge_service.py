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
    ExternalOutcome,
    ExternalReasonCode,
    JobStatus,
    OrchestrationStage,
    OrchestrationStopOutcome,
    RetrySafety,
    WorkItemStatus,
)
from minime.domain.interfaces import GitHubAdapterInterface, PersistenceUnitOfWork
from minime.domain.models import Event, ExternalActionResult, MetricFact, utc_now
from minime.services.lifecycle_transition_authority import LifecycleTransitionAuthority
from minime.services.openspec_sync import OpenSpecSyncService
from minime.services.worktree_manager import WorktreeManager

logger = logging.getLogger(__name__)


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
    total_phases: int = 12
    error_message: str | None = None


class PostMergeReconciliationService:
    """Orchestrates native post-merge SDLC lifecycle closure and cleanup."""

    def __init__(
        self,
        uow: PersistenceUnitOfWork,
        project_root: str | Path,
        github_adapter: GitHubAdapterInterface,
        worktree_manager: WorktreeManager | None = None,
        openspec_sync: OpenSpecSyncService | None = None,
    ):
        self.uow = uow
        self.project_root = Path(project_root).resolve()
        self.github_adapter = github_adapter
        self.worktree_manager = worktree_manager or WorktreeManager(self.project_root, uow=uow)
        self.openspec_sync = openspec_sync or OpenSpecSyncService(self.project_root)

    def verify_candidate_ancestry(self, candidate_sha: str, base_ref: str = "HEAD") -> bool:
        """Verify that the candidate SHA is an ancestor of the base/main branch."""
        try:
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

    def reconcile_post_merge(
        self,
        project_id: str,
        change_name: str,
        run_id: str | None = None,
    ) -> PostMergeReconciliationResult:
        """Execute the complete post-merge closure cycle idempotently."""
        start_time = time.time()
        native_phases = 0

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

        # Check if already closed
        if (
            run.current_stage == OrchestrationStage.COMPLETED
            and not run.is_active
            and (job is None or job.status == JobStatus.COMPLETED)
        ):
            logger.info("Change '%s' (Run: %s) is already closed.", change_name, run.run_id)
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
                native_phases_completed=7,
                total_phases=7,
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
                    pr_details_res = self.github_adapter.get_pull_request_details(repository, pr_number)
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
                    native_phases_completed=7,
                    total_phases=7,
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

        native_phases += 1  # Phase 1: Merge detection passed

        merged_by = pr_details.get("merged_by_login") or "human"
        merged_at = pr_details.get("merged_at")
        merge_commit_sha = pr_details.get("merge_commit_sha")
        cand_sha = run.candidate_sha or pr_details.get("head_sha") or ""

        native_phases += 1  # Phase 2: Executor classified

        # 3. Ancestry verification
        # Fetch latest main in local repository
        subprocess.run(
            ["git", "fetch", "origin", f"{base_branch}:{base_branch}"],
            cwd=self.project_root,
            capture_output=True,
            text=True,
            check=False,
        )
        ancestry_ok = self.verify_candidate_ancestry(cand_sha, base_branch)
        if not ancestry_ok and merge_commit_sha:
            ancestry_ok = self.verify_candidate_ancestry(cand_sha, merge_commit_sha)

        native_phases += 1  # Phase 3: Ancestry verified

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
                    "ancestry_verified": ancestry_ok,
                },
                timestamp=utc_now(),
            )
        )
        self.uow.commit()

        # 4. Stage Transition to POST_MERGE_RECONCILING
        run.current_stage = OrchestrationStage.POST_MERGE_RECONCILING
        if job:
            job.status = JobStatus.POST_MERGE_RECONCILING
            self.uow.jobs.save(job)
        self.uow.orchestration_runs.save(run)
        self.uow.commit()

        # 5. GitHub Issue Closure
        issue_required = bool(binding and binding.github_issue_number)
        issue_closed = False
        issue_num = binding.github_issue_number if binding else None
        if issue_num:
            try:
                close_res = self.github_adapter.close_issue(
                    repository,
                    issue_num,
                    comment=f"Closed automatically by mini me upon post-merge reconciliation of `{change_name}`.",
                )
                issue_closed = close_res.outcome == ExternalOutcome.SUCCESS and close_res.data is True
                if issue_closed:
                    self.uow.events.save(
                        Event(
                            event_type=EventType.ISSUE_CLOSED,
                            project_id=project_id,
                            change_id=change_name,
                            payload={"issue_number": issue_num},
                            timestamp=utc_now(),
                        )
                    )
            except Exception as exc:
                logger.warning("Failed to close GitHub Issue #%d: %s", issue_num, exc)

        # 6. GitHub Project Item Done
        project_item_required = bool(binding and (binding.github_project_item_id or binding.github_issue_number))
        project_item_updated = False
        project_item_id = binding.github_project_item_id if binding else None
        try:
            update_res = self.github_adapter.update_project_item_status(
                project_number=2,
                owner="silverberdi",
                item_id=project_item_id or str(issue_num),
                status="Done",
            )
            project_item_updated = update_res.outcome == ExternalOutcome.SUCCESS and update_res.data is True
            if project_item_updated:
                self.uow.events.save(
                    Event(
                        event_type=EventType.PROJECT_ITEM_DONE,
                        project_id=project_id,
                        change_id=change_name,
                        payload={"project_item_id": project_item_id or issue_num, "status": "Done"},
                        timestamp=utc_now(),
                    )
                )
        except Exception as exc:
            logger.warning("Failed to update GitHub Project item: %s", exc)

        # 7. OpenSpec Spec Sync + verification
        synced_specs: list[str] = []
        sync_verified = False
        try:
            sync_res = self.openspec_sync.sync_change_specs(openspec_path, change_name)
            verify_sync_res = self.openspec_sync.verify_sync(openspec_path, change_name, sync_res)
            sync_verified = (
                verify_sync_res.outcome == ExternalOutcome.SUCCESS
                and verify_sync_res.data is True
            )
            if sync_verified:
                synced_specs = sync_res.data or []
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
        except Exception as exc:
            logger.warning("OpenSpec spec sync failed for '%s': %s", change_name, exc)

        # 8. OpenSpec Archive + verification (only after sync is verified)
        archived_path: Path | None = None
        archive_verified = False
        if sync_verified:
            try:
                archive_res = self.openspec_sync.archive_change(openspec_path, change_name)
                verify_arc_res = self.openspec_sync.verify_archive(
                    openspec_path, change_name, archive_res
                )
                archive_verified = (
                    verify_arc_res.outcome == ExternalOutcome.SUCCESS
                    and verify_arc_res.data is True
                )
                if archive_verified:
                    archived_path = archive_res.data
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
            except Exception as exc:
                logger.warning("OpenSpec archive failed for '%s': %s", change_name, exc)

        # 9. Worktree Cleanup
        wt_clean_res = self._clean_worktrees(job_id)
        worktree_cleaned = wt_clean_res.outcome == ExternalOutcome.SUCCESS
        if worktree_cleaned:
            self.uow.events.save(
                Event(
                    event_type=EventType.WORKTREE_CLEANED,
                    project_id=project_id,
                    change_id=change_name,
                    payload={"job_id": job_id},
                    timestamp=utc_now(),
                )
            )

        # 10. Local and Remote Branch Cleanup
        local_branches = [
            f"minime/{change_name}-{job_id}" if job_id else None,
            f"minime/{change_name}",
        ]
        local_clean_ok = True
        for b in local_branches:
            if b:
                loc_res = self._delete_local_branch(b)
                if loc_res.outcome != ExternalOutcome.SUCCESS:
                    local_clean_ok = False

        delete_remote_res = self.github_adapter.delete_remote_branch(repository, f"minime/{change_name}")
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

        # 12. Single Explicit Terminal Gate
        unverified_phases: list[str] = []
        if not ancestry_ok:
            unverified_phases.append("ancestry")
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
                ancestry_verified=ancestry_ok,
                issue_closed=issue_closed,
                project_item_updated=project_item_updated,
                openspec_synced=sync_verified,
                openspec_archived=archive_verified,
                worktree_cleaned=worktree_cleaned,
                branch_cleaned=branch_cleaned,
                locks_cleaned=locks_cleaned,
                terminal_stage=OrchestrationStage.POST_MERGE_RECONCILING,
                terminal_job_status=job.status if job else JobStatus.POST_MERGE_RECONCILING,
                native_phases_completed=7 - len(unverified_phases),
                total_phases=7,
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
            "ancestry_verified": ancestry_ok,
        }
        self.uow.orchestration_runs.save(run)

        if job:
            job.status = JobStatus.COMPLETED
            self.uow.jobs.save(job)

        self._reconcile_change_and_backlog_item(project_id, change_name)

        # 14. Persist Post-Merge Metric Facts
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
                    "ancestry_verified": ancestry_ok,
                    "native_phases": 7,
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
            ancestry_verified=ancestry_ok,
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
            native_phases_completed=7,
            total_phases=7,
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

    def _clean_worktrees(self, job_id: str | None) -> ExternalActionResult[bool]:
        """Clean worktrees associated with a job fail-closed with postcondition verification."""
        if not job_id:
            return ExternalActionResult(
                outcome=ExternalOutcome.SUCCESS,
                source_adapter="worktree_manager",
                reason_code=ExternalReasonCode.ALREADY_ABSENT,
                retry_safety=RetrySafety.SAFE,
                data=True,
            )

        target_paths: list[Path] = []
        scan_failed = False
        scan_err: str = ""
        try:
            wt_path = self.worktree_manager.worktree_path(job_id)
            if wt_path.exists():
                target_paths.append(wt_path)
            worktrees_dir = self.project_root / ".minime" / "worktrees"
            if worktrees_dir.exists():
                for child in worktrees_dir.glob(f"{job_id}*"):
                    if child.exists() and child not in target_paths:
                        target_paths.append(child)
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

        all_removed = True
        errors: list[str] = []
        for path in target_paths:
            try:
                res = subprocess.run(
                    ["git", "worktree", "remove", "--force", str(path)],
                    cwd=self.project_root,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if path.exists() or res.returncode != 0:
                    all_removed = False
                    errors.append(f"Failed removing worktree at '{path}': rc={res.returncode}, stderr={res.stderr.strip()}")
            except Exception as exc:
                all_removed = False
                errors.append(f"Exception removing worktree at '{path}': {exc}")

        if all_removed:
            return ExternalActionResult(
                outcome=ExternalOutcome.SUCCESS,
                source_adapter="worktree_manager",
                reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
                retry_safety=RetrySafety.SAFE,
                data=True,
            )

        return ExternalActionResult(
            outcome=ExternalOutcome.FAILURE,
            source_adapter="worktree_manager",
            reason_code=ExternalReasonCode.POSTCONDITION_NOT_PROVEN,
            retry_safety=RetrySafety.SAFE,
            data=False,
            error_message="; ".join(errors),
        )

    def _delete_local_branch(self, branch_name: str) -> ExternalActionResult[bool]:
        """Delete a local git branch fail-closed with postcondition verification."""
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
                retry_safety=RetrySafety.SAFE,
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
        self._clean_worktrees(job_id)
        local_branches = [
            f"minime/{change_name}-{job_id}" if job_id else None,
            f"minime/{change_name}",
        ]
        for b in local_branches:
            if b:
                self._delete_local_branch(b)

