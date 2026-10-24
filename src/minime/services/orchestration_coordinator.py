"""Native OpenSpec orchestration coordinator for end-to-end request lifecycle."""

from __future__ import annotations

import asyncio
import inspect
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from minime.adapters.github import GitHubAdapter
from minime.adapters.openspec import OpenSpecAdapter
from minime.domain.enums import ExternalOutcome, OrchestrationStage, OrchestrationStopOutcome
from minime.domain.interfaces import PersistenceUnitOfWork
from minime.domain.models import OrchestrationRun, utc_now
from minime.logging import get_logger, redact_secrets
from minime.services.agent_runner import CliAgentRunner, NativeOpenSpecWorkflowUnavailable
from minime.services.pr_preparer_service import PrPreparationInput, PrPreparerService
from minime.services.remote_request_intake import RemoteRequestIntakeService
from minime.services.review_verdict_parser import MalformedReviewOutputError, parse_review_verdict
from minime.services.worktree_manager import WorktreeManager

logger = get_logger("services.orchestration_coordinator")


@dataclass(frozen=True)
class OrchestrationCoordinationResult:
    status: str  # "COMPLETED", "HUMAN_REQUIRED", "WAITING_CAPACITY", "PAUSED", "FAILED", "IDLE"
    run_id: str | None
    current_stage: OrchestrationStage
    message: str
    pr1_url: str | None = None
    pr2_url: str | None = None
    human_payload: dict[str, Any] | None = None


@dataclass(frozen=True)
class GitCommandResult:
    args: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


@dataclass(frozen=True)
class ComplexityAssessment:
    """Typed, fail-closed result of the thinking-agent complexity stage."""

    status: str
    complexity: str | None = None
    evidence: str | None = None
    reason: str | None = None
    exit_code: int | None = None
    timed_out: bool = False
    preflight_error: str | None = None
    output: str = ""

    @property
    def is_valid(self) -> bool:
        return self.status == "VALID" and self.complexity is not None and bool(self.evidence)


class GitOperationError(RuntimeError):
    """A git operation failed and must be recoverable without advancing the run."""

    def __init__(self, result: GitCommandResult) -> None:
        super().__init__(f"git {' '.join(result.args)} failed ({result.returncode}): {result.stderr.strip()}")
        self.result = result


class NativeOrchestrationCoordinator:
    """Coordinates the end-to-end lifecycle of remote requests through native OpenSpec."""

    def __init__(
        self,
        uow_factory: Any,
        github_adapter: GitHubAdapter,
        worktree_manager: WorktreeManager,
        agent_runner: CliAgentRunner,
        openspec_adapter: OpenSpecAdapter | None = None,
        pr_preparer: PrPreparerService | None = None,
        max_correction_attempts: int = 3,
    ) -> None:
        self.uow_factory = uow_factory
        self.github_adapter = github_adapter
        self.worktree_manager = worktree_manager
        self.agent_runner = agent_runner
        self.openspec_adapter = openspec_adapter or OpenSpecAdapter()
        self.pr_preparer = pr_preparer or PrPreparerService()
        self.max_correction_attempts = max_correction_attempts

    async def execute_project_request(
        self,
        project_id: str,
        *,
        operator_ack: bool = False,
        operator_clarification: str | None = None,
        thinker_provider: str = "antigravity",
        implementer_provider: str = "codex",
        reviewer_provider: str = "antigravity",
    ) -> OrchestrationCoordinationResult:
        """Execute or resume the active/next request for a project."""
        uow: PersistenceUnitOfWork = self.uow_factory()
        intake_service = RemoteRequestIntakeService(github_adapter=self.github_adapter, uow=uow)

        # Resolve repository from the persisted project/binding. Never use a
        # placeholder: publishing against an unverified repository is unsafe.
        repository = None
        if hasattr(uow, "projects"):
            getter = getattr(uow.projects, "get_by_id", None) or getattr(uow.projects, "get", None)
            if getter:
                proj = getter(project_id)
                if proj and getattr(proj, "repository", None):
                    repository = proj.repository
        binding = None
        if hasattr(uow, "project_managed_repository_bindings"):
            binding = uow.project_managed_repository_bindings.get_by_project_id(project_id)
        if not repository or binding is None or not getattr(binding, "managed_repository_root", None):
            return OrchestrationCoordinationResult(
                status="PAUSED", run_id=None, current_stage=OrchestrationStage.ADMITTED,
                message="Project has no verified repository binding; work was not started.",
            )
        canonical = str(getattr(binding, "canonical_repository_identity", ""))
        expected = f"github.com/{repository}".lower().removeprefix("https://")
        if (canonical.lower().startswith(("github.com/", "https://"))
                and canonical.lower().removeprefix("https://") != expected):
            return OrchestrationCoordinationResult(
                status="PAUSED", run_id=None, current_stage=OrchestrationStage.ADMITTED,
                message="Project repository does not match its verified managed binding.",
            )

        # Step 1: Remote Request Intake and Selection
        selected = intake_service.select_next_request(project_id, repository)
        if not selected:
            return OrchestrationCoordinationResult(
                status="IDLE",
                run_id=None,
                current_stage=OrchestrationStage.ADMITTED,
                message="No eligible open requests found in remote repository.",
            )

        issue_number = selected.get("issue_number")
        issue_title = selected.get("title") or "change"
        issue_body = selected.get("body") or ""

        slug = self.worktree_manager.slugify_request_title(issue_title)
        change_name = f"req-{issue_number}-{slug}"

        # Step 2: Durable Run Record
        active_run = None
        if hasattr(uow, "orchestration_runs"):
            if hasattr(uow.orchestration_runs, "get_active_run"):
                active_run = uow.orchestration_runs.get_active_run(project_id, change_name)
            if not active_run and hasattr(uow.orchestration_runs, "list_runs"):
                active_runs = uow.orchestration_runs.list_runs(project_id=project_id, is_active=True)
                if active_runs:
                    active_run = active_runs[0]

        if not active_run:
            active_run = OrchestrationRun(
                project_id=project_id,
                change_name=change_name,
                base_sha="main",
                current_stage=OrchestrationStage.ADMITTED,
                resumable_stage=OrchestrationStage.ADMITTED,
                stop_details={"issue_number": issue_number, "issue_title": issue_title},
            )
            if hasattr(uow, "orchestration_runs"):
                uow.orchestration_runs.save(active_run)
                if hasattr(uow, "commit"):
                    uow.commit()

        # Step 3: Git Workspace Isolation
        base_branch = "main"
        worktree_info = await self.worktree_manager.create_request_worktree(
            project_id=project_id,
            issue_number=issue_number,
            issue_title=issue_title,
            base_branch=base_branch,
            run_id=active_run.run_id,
        )
        worktree_path = worktree_info.path

        # Step 4: Explore Stage
        if active_run.current_stage in (OrchestrationStage.ADMITTED, OrchestrationStage.PREPARING_EXECUTION, OrchestrationStage.EXPLORING):
            self._update_stage(uow, active_run, OrchestrationStage.EXPLORING)
            explore_result = await self._run_explore(
                worktree_path=worktree_path,
                provider=thinker_provider,
                issue_number=issue_number,
                issue_title=issue_title,
                issue_body=issue_body,
                operator_clarification=operator_clarification,
                project_id=project_id,
            )
            if explore_result.get("status") == "HUMAN_REQUIRED":
                return OrchestrationCoordinationResult(
                    status="HUMAN_REQUIRED",
                    run_id=active_run.run_id,
                    current_stage=OrchestrationStage.EXPLORING,
                    message="Explore stage requires operator clarification.",
                    human_payload=explore_result.get("human_payload"),
                )
            if explore_result.get("status") != "READY_TO_PROPOSE":
                return OrchestrationCoordinationResult(
                    status="PAUSED",
                    run_id=active_run.run_id,
                    current_stage=OrchestrationStage.EXPLORING,
                    message=explore_result.get("message", "Explore failed; proposal cannot start."),
                )

        # Step 5: Propose and Strict Validation Loop
        if active_run.current_stage in (OrchestrationStage.EXPLORING, OrchestrationStage.PROPOSING, OrchestrationStage.VALIDATING):
            existing_proposal = (
                active_run.current_stage == OrchestrationStage.VALIDATING
                and self._proposal_artifacts_present(worktree_path, change_name)
            )
            if not existing_proposal:
                self._update_stage(uow, active_run, OrchestrationStage.PROPOSING)
                propose_result = await self._run_propose(
                    worktree_path=worktree_path,
                    provider=thinker_provider,
                    change_name=change_name,
                    issue_number=issue_number,
                    issue_title=issue_title,
                    issue_body=issue_body,
                    project_id=project_id,
                )
                if propose_result.get("status") != "READY_TO_VALIDATE":
                    return OrchestrationCoordinationResult(
                        status="PAUSED", run_id=active_run.run_id,
                        current_stage=OrchestrationStage.PROPOSING,
                        message=propose_result.get("message", "Native Propose did not produce a valid result."),
                    )

                self._update_stage(uow, active_run, OrchestrationStage.VALIDATING)
            validate_pass = False
            for attempt in range(self.max_correction_attempts if not existing_proposal else 1):
                val_res = self.openspec_adapter.validate_change_strict(change_name, worktree_path)
                if val_res.get("status") == "PASS":
                    validate_pass = True
                    break
                if existing_proposal:
                    break
                # Correction pass
                logger.info(f"OpenSpec strict validation failed on attempt {attempt + 1}. Running correction pass...")
                correction_ok = await self._run_propose_correction(
                    worktree_path, thinker_provider, change_name, val_res.get("stderr", ""), project_id=project_id
                )
                if not correction_ok:
                    break

            if not validate_pass:
                return OrchestrationCoordinationResult(
                    status="PAUSED",
                    run_id=active_run.run_id,
                    current_stage=OrchestrationStage.VALIDATING,
                    message="Strict CLI validation failed after max correction attempts. Worktree preserved.",
                )

            # Evaluate Complexity
            complexity_result = await self._assess_complexity(
                worktree_path, thinker_provider, issue_title, issue_body, project_id
            )
            active_run.stop_details["complexity_assessment"] = {
                "status": complexity_result.status,
                "complexity": complexity_result.complexity,
                "evidence": complexity_result.evidence,
                "reason": complexity_result.reason,
                "exit_code": complexity_result.exit_code,
                "timed_out": complexity_result.timed_out,
                "preflight_error": complexity_result.preflight_error,
                "output": complexity_result.output,
            }
            if not complexity_result.is_valid:
                if hasattr(uow, "orchestration_runs"):
                    uow.orchestration_runs.save(active_run)
                    if hasattr(uow, "commit"):
                        uow.commit()
                return OrchestrationCoordinationResult(
                    status="PAUSED", run_id=active_run.run_id,
                    current_stage=OrchestrationStage.VALIDATING,
                    message=f"Thinking agent complexity assessment failed: {complexity_result.reason or complexity_result.status}.",
                )
            complexity = complexity_result.complexity
            active_run.stop_details["complexity"] = complexity
            active_run.stop_details["complexity_evidence"] = complexity_result.evidence
            if hasattr(uow, "orchestration_runs"):
                uow.orchestration_runs.save(active_run)
                if hasattr(uow, "commit"):
                    uow.commit()

            # Proposal Review for High Complexity
            if complexity == "high":
                self._update_stage(uow, active_run, OrchestrationStage.PROPOSAL_REVIEW)
                review_ok = await self._run_proposal_review(worktree_path, reviewer_provider, change_name, project_id=project_id)
                if not review_ok:
                    return OrchestrationCoordinationResult(
                        status="PAUSED",
                        run_id=active_run.run_id,
                        current_stage=OrchestrationStage.PROPOSAL_REVIEW,
                        message="Independent proposal review reported defects. Worktree preserved.",
                    )

            self._update_stage(uow, active_run, OrchestrationStage.READY_TO_APPLY)

        # Step 6: Verify Presence Verification (Fail-Closed Check Before Apply)
        try:
            self.agent_runner.resolve_workflow(
                worktree_path=worktree_path,
                provider=implementer_provider,
                operation="verify",
                change_name=change_name,
            )
        except NativeOpenSpecWorkflowUnavailable as exc:
            logger.error(f"Missing native Verify workflow for implementer {implementer_provider}: {exc}")
            return OrchestrationCoordinationResult(
                status="PAUSED",
                run_id=active_run.run_id,
                current_stage=OrchestrationStage.READY_TO_APPLY,
                message=f"Missing native OpenSpec Verify workflow in worktree: {exc}",
            )

        # Step 7: Apply Stage and Test Execution
        if active_run.current_stage in (OrchestrationStage.READY_TO_APPLY, OrchestrationStage.IMPLEMENTING):
            self._update_stage(uow, active_run, OrchestrationStage.IMPLEMENTING)
            apply_ok = await self._run_apply(worktree_path, implementer_provider, change_name, project_id=project_id)
            if not apply_ok:
                return OrchestrationCoordinationResult(
                    status="PAUSED", run_id=active_run.run_id,
                    current_stage=OrchestrationStage.IMPLEMENTING,
                    message="Native Apply failed or produced no authoritative evidence. Worktree preserved.",
                )

            self._update_stage(uow, active_run, OrchestrationStage.RUNNING_TESTS)
            tests_ok, test_evidence = await self._run_automated_tests(worktree_path)
            if not tests_ok:
                return OrchestrationCoordinationResult(
                    status="PAUSED",
                    run_id=active_run.run_id,
                    current_stage=OrchestrationStage.RUNNING_TESTS,
                    message="Automated tests failed during Apply. Worktree preserved.",
                )
            active_run.stop_details["test_evidence"] = test_evidence

            # Step 8: Verify Stage (Executed by implementer)
            self._update_stage(uow, active_run, OrchestrationStage.VERIFYING)
            verify_ok = await self._run_verify(worktree_path, implementer_provider, change_name, project_id=project_id)
            if not verify_ok:
                return OrchestrationCoordinationResult(
                    status="PAUSED",
                    run_id=active_run.run_id,
                    current_stage=OrchestrationStage.VERIFYING,
                    message="OpenSpec verify reported discrepancies. Worktree preserved.",
                )

            # Step 9: Post-Verify Routing & Code Review
            complexity = active_run.stop_details.get("complexity", "moderate")
            if complexity == "high":
                self._update_stage(uow, active_run, OrchestrationStage.CODE_REVIEW)
                code_review_ok = await self._run_code_review(worktree_path, reviewer_provider, change_name, project_id=project_id)
                if not code_review_ok:
                    return OrchestrationCoordinationResult(
                        status="PAUSED",
                        run_id=active_run.run_id,
                        current_stage=OrchestrationStage.CODE_REVIEW,
                        message="Independent code review requested changes. Worktree preserved.",
                    )

            self._update_stage(uow, active_run, OrchestrationStage.READY_FOR_PR)

        # Step 10: Implementation PR (PR1)
        pr1_url = active_run.stop_details.get("pr1_url")
        pr1_number = active_run.stop_details.get("pr1_number")
        complexity = active_run.stop_details.get("complexity", "moderate")
        try:
            candidate_sha = await self._get_git_head_sha(worktree_path)
        except GitOperationError as exc:
            return OrchestrationCoordinationResult(
                status="PAUSED", run_id=active_run.run_id,
                current_stage=OrchestrationStage.READY_FOR_PR,
                message=f"Unable to observe candidate Git state: {exc}. Worktree preserved.",
            )
        active_run.candidate_sha = candidate_sha

        if not pr1_number:
            self._update_stage(uow, active_run, OrchestrationStage.PR1_PENDING)
            prep_input = PrPreparationInput(
                project_id=project_id,
                repository=repository,
                pr_type="implementation",
                issue_number=issue_number,
                issue_title=issue_title,
                base_branch=base_branch,
                candidate_branch=worktree_info.branch_name,
                candidate_sha=candidate_sha,
                change_name=change_name,
                change_summary=f"Implementation of request #{issue_number}: {issue_title}",
                test_evidence=active_run.stop_details.get("test_evidence", "All tests passed (exit code 0)."),
                complexity=complexity,
            )
            prepared_pr = self.pr_preparer.prepare_pull_request(prep_input)

            # Push branch
            try:
                await self._push_branch(worktree_path, worktree_info.branch_name)
            except GitOperationError as exc:
                return OrchestrationCoordinationResult(
                    status="PAUSED", run_id=active_run.run_id,
                    current_stage=OrchestrationStage.PR1_PENDING,
                    message=f"Unable to publish PR1 branch: {exc}. Worktree preserved.",
                )

            # Open PR via GitHubAdapter
            opened_pr_call = self.github_adapter.create_pull_request(
                repository=repository,
                branch=worktree_info.branch_name,
                base=base_branch,
                title=prepared_pr.title,
                body=prepared_pr.body,
                head_sha=candidate_sha,
                draft=False,
            ) if hasattr(self.github_adapter, "_repo") else self.github_adapter.create_pull_request(
                base=base_branch,
                head=worktree_info.branch_name,
                title=prepared_pr.title,
                body=prepared_pr.body,
            )
            opened_pr_res = await opened_pr_call if inspect.isawaitable(opened_pr_call) else opened_pr_call
            if not self._external_success(opened_pr_res):
                return OrchestrationCoordinationResult(
                    status="PAUSED", run_id=active_run.run_id,
                    current_stage=OrchestrationStage.PR1_PENDING,
                    message="GitHub did not confirm creation of PR1. Worktree preserved.",
                )
            opened_data = opened_pr_res.data if hasattr(opened_pr_res, "data") else opened_pr_res
            pr1_number = opened_data.get("number") if isinstance(opened_data, dict) else getattr(opened_data, "number", None)
            pr1_url = opened_data.get("html_url") if isinstance(opened_data, dict) else getattr(opened_data, "html_url", None)
            if not pr1_number or not await self._confirm_pr_open(
                repository, pr1_number, worktree_info.branch_name, base_branch, candidate_sha
            ):
                return OrchestrationCoordinationResult(
                    status="PAUSED", run_id=active_run.run_id,
                    current_stage=OrchestrationStage.PR1_PENDING,
                    pr1_url=pr1_url,
                    message="PR1 identity or remote head/base state was not confirmed.",
                )
            active_run.stop_details["pr1_number"] = pr1_number
            active_run.stop_details["pr1_url"] = pr1_url
            if hasattr(uow, "orchestration_runs"):
                uow.orchestration_runs.save(active_run)
                if hasattr(uow, "commit"):
                    uow.commit()

        # Differentiated Merge Policy for PR1
        if active_run.current_stage == OrchestrationStage.PR1_PENDING:
            if complexity == "high" and not operator_ack:
                return OrchestrationCoordinationResult(
                    status="HUMAN_REQUIRED",
                    run_id=active_run.run_id,
                    current_stage=OrchestrationStage.PR1_PENDING,
                    pr1_url=pr1_url,
                    message="High-complexity change requires operator acknowledgement («Estoy enterado») before merging PR1.",
                    human_payload={
                        "action": "operator_ack",
                        "summary_es": f"Cambio de alta complejidad para el Issue #{issue_number}: {issue_title}. PR #{pr1_number} listo para fusión.",
                        "prompt": "Por favor confirme con «Estoy enterado» para proceder a la fusión remota.",
                    },
                )

            # Merge PR1
            merge_call = self.github_adapter.merge_pull_request(
                repository=repository,
                pr_number=pr1_number,
                candidate_sha=candidate_sha,
                merge_method="merge",
            ) if hasattr(self.github_adapter, "_repo") else self.github_adapter.merge_pull_request(
                pull_number=pr1_number,
                expected_head_sha=candidate_sha,
                merge_method="merge",
            )
            merge_res = await merge_call if inspect.isawaitable(merge_call) else merge_call
            if not self._external_success(merge_res):
                is_merged = False
            else:
                is_merged = await self._confirm_pr_merged(repository, pr1_number, candidate_sha)

            if not is_merged:
                err_msg = getattr(merge_res, "error_message", "Merge failed")
                return OrchestrationCoordinationResult(
                    status="PAUSED",
                    run_id=active_run.run_id,
                    current_stage=OrchestrationStage.PR1_PENDING,
                    pr1_url=pr1_url,
                    message=f"Failed to merge PR1: {err_msg}. Worktree preserved.",
                )
            self._update_stage(uow, active_run, OrchestrationStage.PR1_MERGED)

        # Step 11: Fresh Documentation Worktree & Sync/Archive (PR2)
        self._update_stage(uow, active_run, OrchestrationStage.DOC_CLOSING)
        doc_worktree_info = await self.worktree_manager.create_documentation_worktree(
            project_id=project_id,
            issue_number=issue_number,
            issue_title=issue_title,
            base_branch=base_branch,
            run_id=active_run.run_id,
        )
        doc_path = doc_worktree_info.path

        # Run native Sync & Archive
        try:
            sync_archive_ok = await self._run_sync_and_archive(doc_path, thinker_provider, change_name, project_id=project_id)
        except GitOperationError as exc:
            return OrchestrationCoordinationResult(
                status="PAUSED", run_id=active_run.run_id,
                current_stage=OrchestrationStage.DOC_CLOSING,
                pr1_url=pr1_url,
                message=f"Documentation Git operation failed: {exc}. Worktree preserved.",
            )
        if not sync_archive_ok:
            return OrchestrationCoordinationResult(
                status="PAUSED", run_id=active_run.run_id,
                current_stage=OrchestrationStage.DOC_CLOSING,
                pr1_url=pr1_url,
                message="Native Sync or Archive failed. Documentation worktree preserved.",
            )
        try:
            doc_head_sha = await self._get_git_head_sha(doc_path)
        except GitOperationError as exc:
            return OrchestrationCoordinationResult(
                status="PAUSED", run_id=active_run.run_id,
                current_stage=OrchestrationStage.DOC_CLOSING,
                pr1_url=pr1_url,
                message=f"Unable to observe documentation Git state: {exc}. Worktree preserved.",
            )

        # Step 12: Documentation PR (PR2)
        self._update_stage(uow, active_run, OrchestrationStage.PR2_PENDING)
        doc_prep_input = PrPreparationInput(
            project_id=project_id,
            repository=repository,
            pr_type="documentation",
            issue_number=issue_number,
            issue_title=issue_title,
            base_branch=base_branch,
            candidate_branch=doc_worktree_info.branch_name,
            candidate_sha=doc_head_sha,
            change_name=change_name,
            change_summary=f"Documentation sync and archive for request #{issue_number}",
            test_evidence="OpenSpec native sync and archive completed successfully.",
        )
        prepared_doc_pr = self.pr_preparer.prepare_pull_request(doc_prep_input)

        try:
            await self._push_branch(doc_path, doc_worktree_info.branch_name)
        except GitOperationError as exc:
            return OrchestrationCoordinationResult(
                status="PAUSED", run_id=active_run.run_id,
                current_stage=OrchestrationStage.PR2_PENDING,
                pr1_url=pr1_url,
                message=f"Unable to publish PR2 branch: {exc}. Worktree preserved.",
            )
        opened_doc_call = self.github_adapter.create_pull_request(
            repository=repository,
            branch=doc_worktree_info.branch_name,
            base=base_branch,
            title=prepared_doc_pr.title,
            body=prepared_doc_pr.body,
            head_sha=doc_head_sha,
            draft=False,
        ) if hasattr(self.github_adapter, "_repo") else self.github_adapter.create_pull_request(
            base=base_branch,
            head=doc_worktree_info.branch_name,
            title=prepared_doc_pr.title,
            body=prepared_doc_pr.body,
        )
        opened_doc_res = await opened_doc_call if inspect.isawaitable(opened_doc_call) else opened_doc_call
        if not self._external_success(opened_doc_res):
            return OrchestrationCoordinationResult(
                status="PAUSED", run_id=active_run.run_id,
                current_stage=OrchestrationStage.PR2_PENDING,
                pr1_url=pr1_url,
                message="GitHub did not confirm creation of PR2. Worktree preserved.",
            )
        opened_doc_data = opened_doc_res.data if hasattr(opened_doc_res, "data") else opened_doc_res
        pr2_number = opened_doc_data.get("number") if isinstance(opened_doc_data, dict) else getattr(opened_doc_data, "number", None)
        pr2_url = opened_doc_data.get("html_url") if isinstance(opened_doc_data, dict) else getattr(opened_doc_data, "html_url", None)
        if not pr2_number or not await self._confirm_pr_open(
            repository, pr2_number, doc_worktree_info.branch_name, base_branch, doc_head_sha
        ):
            return OrchestrationCoordinationResult(
                status="PAUSED", run_id=active_run.run_id,
                current_stage=OrchestrationStage.PR2_PENDING,
                pr1_url=pr1_url, pr2_url=pr2_url,
                message="PR2 identity or remote head/base state was not confirmed.",
            )
        active_run.stop_details["pr2_number"] = pr2_number
        active_run.stop_details["pr2_url"] = pr2_url

        # PR2 Auto-merge (always automatic)
        merge_doc_call = self.github_adapter.merge_pull_request(
            repository=repository,
            pr_number=pr2_number,
            candidate_sha=doc_head_sha,
            merge_method="merge",
        ) if hasattr(self.github_adapter, "_repo") else self.github_adapter.merge_pull_request(
            pull_number=pr2_number,
            expected_head_sha=doc_head_sha,
            merge_method="merge",
        )
        merge_doc_res = await merge_doc_call if inspect.isawaitable(merge_doc_call) else merge_doc_call
        doc_merged = self._external_success(merge_doc_res) and await self._confirm_pr_merged(
            repository, pr2_number, doc_head_sha
        )

        if not doc_merged:
            err_msg = getattr(merge_doc_res, "error_message", "Merge PR2 failed")
            return OrchestrationCoordinationResult(
                status="PAUSED",
                run_id=active_run.run_id,
                current_stage=OrchestrationStage.PR2_PENDING,
                pr1_url=pr1_url,
                pr2_url=pr2_url,
                message=f"Failed to merge documentation PR2: {err_msg}. Worktrees preserved.",
            )

        self._update_stage(uow, active_run, OrchestrationStage.PR2_MERGED)

        # Step 13: Remote Issue Closure and Lock Release
        close_call = self.github_adapter.close_issue(
            repository=repository,
            issue_number=issue_number,
            comment=(
                f"Completed by mini me F3 orchestration.\n\n"
                f"- Implementation PR: #{pr1_number} ({pr1_url})\n"
                f"- Documentation PR: #{pr2_number} ({pr2_url})\n"
                f"- OpenSpec Change: `{change_name}` archived."
            ),
        ) if hasattr(self.github_adapter, "_repo") else self.github_adapter.close_issue(
            issue_number=issue_number,
            comment=(
                f"Completed by mini me F3 orchestration.\n\n"
                f"- Implementation PR: #{pr1_number} ({pr1_url})\n"
                f"- Documentation PR: #{pr2_number} ({pr2_url})\n"
                f"- OpenSpec Change: `{change_name}` archived."
            ),
        )
        close_res = await close_call if inspect.isawaitable(close_call) else close_call
        if not self._external_success(close_res) or not await self._confirm_issue_closed(repository, issue_number):
            return OrchestrationCoordinationResult(
                status="PAUSED", run_id=active_run.run_id,
                current_stage=OrchestrationStage.PR2_MERGED,
                pr1_url=pr1_url, pr2_url=pr2_url,
                message="Remote issue closure was not confirmed; lock remains held.",
            )

        # Record the next FIFO candidate only after remote completion is
        # confirmed. The scheduler remains the sole owner of starting it.
        next_request = intake_service.select_next_request(project_id, repository)
        active_run.stop_details["next_fifo_request"] = (
            next_request.get("issue_number") if next_request else None
        )

        active_run.is_active = False
        active_run.stop_outcome = OrchestrationStopOutcome.COMPLETED
        self._update_stage(uow, active_run, OrchestrationStage.COMPLETED)

        return OrchestrationCoordinationResult(
            status="COMPLETED",
            run_id=active_run.run_id,
            current_stage=OrchestrationStage.COMPLETED,
            pr1_url=pr1_url,
            pr2_url=pr2_url,
            message=f"Request #{issue_number} successfully implemented, verified, merged, and closed.",
        )

    async def _confirm_pr_merged(self, repository: str, pr_number: int, candidate_sha: str) -> bool:
        """Re-read the remote PR; a merge request response alone is not proof."""
        getter = getattr(self.github_adapter, "get_pull_request_details", None)
        if not getter:
            return False
        result = getter(repository=repository, pr_number=pr_number)
        result = await result if inspect.isawaitable(result) else result
        if not self._external_success(result):
            return False
        data = result.data if hasattr(result, "data") else result
        if not isinstance(data, dict):
            return False
        return bool(data.get("is_merged") or data.get("merged")) and data.get("merge_commit_sha") is not None and (
            not data.get("head_sha") or data.get("head_sha") == candidate_sha
        )

    async def _confirm_pr_open(
        self, repository: str, pr_number: int, head_branch: str, base_branch: str, candidate_sha: str
    ) -> bool:
        getter = getattr(self.github_adapter, "get_pull_request_details", None)
        if not getter:
            return False
        result = getter(repository=repository, pr_number=pr_number)
        result = await result if inspect.isawaitable(result) else result
        if not self._external_success(result):
            return False
        data = result.data if hasattr(result, "data") else result
        return isinstance(data, dict) and data.get("state") == "open" and data.get("head_sha") == candidate_sha and (
            data.get("head_branch") == head_branch and data.get("base_branch") == base_branch
        )

    async def _confirm_issue_closed(self, repository: str, issue_number: int) -> bool:
        getter = getattr(self.github_adapter, "get_issue", None)
        if not getter:
            return False
        result = getter(repository=repository, issue_number=issue_number)
        result = await result if inspect.isawaitable(result) else result
        if not self._external_success(result):
            return False
        data = result.data if hasattr(result, "data") else result
        return isinstance(data, dict) and str(data.get("state", "")).lower() == "closed"

    def _update_stage(self, uow: Any, run: OrchestrationRun, stage: OrchestrationStage) -> None:
        run.current_stage = stage
        run.resumable_stage = stage
        run.updated_at = utc_now()
        if hasattr(uow, "orchestration_runs"):
            uow.orchestration_runs.save(run)
            if hasattr(uow, "commit"):
                uow.commit()

    @staticmethod
    def _execution_is_successful(result: Any) -> bool:
        """Only an explicit, evidenced, zero-exit execution can advance a stage."""
        if result is None or getattr(result, "exit_code", None) != 0:
            return False
        if getattr(result, "timed_out", False) or getattr(result, "preflight_error", None):
            return False
        if getattr(result, "environment_error", False):
            return False
        return bool(getattr(result, "full_output", "").strip())

    @staticmethod
    def _proposal_artifacts_present(worktree_path: Path, change_name: str) -> bool:
        """Confirm a complete existing proposal before resuming VALIDATING."""
        change_dir = worktree_path / "openspec" / "changes" / change_name
        required = (change_dir / "proposal.md", change_dir / "design.md", change_dir / "tasks.md")
        specs_dir = change_dir / "specs"
        return all(path.is_file() for path in required) and specs_dir.is_dir() and any(
            path.is_file() and path.suffix == ".md" for path in specs_dir.rglob("*.md")
        )

    @staticmethod
    def _external_success(result: Any) -> bool:
        if result is None:
            return False
        if isinstance(result, dict):
            return bool(result.get("success") or result.get("merged"))
        return getattr(result, "outcome", None) == ExternalOutcome.SUCCESS and bool(
            getattr(result, "data", None) is not None
        )

    @staticmethod
    def _parse_json_object(raw: str) -> dict[str, Any] | None:
        """Parse exactly one JSON object; reject prose, multiple objects, and ambiguity."""
        text = raw.strip()
        fenced = re.fullmatch(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
        candidate = fenced.group(1).strip() if fenced else text
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError:
            return None
        return value if isinstance(value, dict) else None

    async def _assess_complexity(
        self, worktree_path: Path, provider: str, title: str, body: str, project_id: str | None
    ) -> ComplexityAssessment:
        wf = self.agent_runner.resolve_workflow(
            worktree_path=worktree_path, provider=provider, operation="propose", change_name="complexity-assessment"
        )
        result = await self.agent_runner.run(
            worktree_path=worktree_path,
            prompt_context=(
                "Assess this Request's implementation complexity using the configured thinking agent. "
                "Return exactly one JSON object: {\"complexity\": \"low|moderate|high\", "
                "\"evidence\": \"brief concrete rationale\"}. Do not infer from keywords alone.\n"
                f"Title: {title}\nBody:\n{body}"
            ),
            project_id=project_id,
            role="thinker",
            provider=provider,
            workflow=wf,
        )
        output = redact_secrets(getattr(result, "full_output", ""))[:4000]
        if getattr(result, "preflight_error", None):
            return ComplexityAssessment(
                status="PREFLIGHT_FAILED",
                reason="agent preflight failed",
                exit_code=getattr(result, "exit_code", None),
                timed_out=bool(getattr(result, "timed_out", False)),
                preflight_error=redact_secrets(result.preflight_error),
                output=output,
            )
        if not self._execution_is_successful(result):
            return ComplexityAssessment(
                status="EXECUTION_FAILED",
                reason="agent exit, timeout, environment, or evidence check failed",
                exit_code=getattr(result, "exit_code", None),
                timed_out=bool(getattr(result, "timed_out", False)),
                output=output,
            )
        payload = self._parse_json_object(result.full_output)
        if not payload or payload.get("complexity") not in {"low", "moderate", "high"}:
            return ComplexityAssessment(
                status="INVALID_OUTPUT",
                reason="exactly one structured complexity object was not returned",
                exit_code=result.exit_code,
                output=output,
            )
        if not isinstance(payload.get("evidence"), str) or not payload["evidence"].strip():
            return ComplexityAssessment(
                status="MISSING_EVIDENCE",
                reason="structured complexity verdict has no concrete evidence",
                exit_code=result.exit_code,
                output=output,
            )
        return ComplexityAssessment(
            status="VALID",
            complexity=payload["complexity"],
            evidence=redact_secrets(payload["evidence"].strip())[:1000],
            exit_code=result.exit_code,
            output=output,
        )

    async def _run_explore(
        self,
        worktree_path: Path,
        provider: str,
        issue_number: int,
        issue_title: str,
        issue_body: str,
        operator_clarification: str | None = None,
        project_id: str | None = None,
    ) -> dict[str, Any]:
        """Execute official OpenSpec Explore workflow with configured thinking agent."""
        wf = self.agent_runner.resolve_workflow(
            worktree_path=worktree_path,
            provider=provider,
            operation="explore",
            change_name=f"issue-{issue_number}",
        )
        prompt = (
            f"You are the thinking agent for mini me. Execute official OpenSpec Explore for Request #{issue_number}.\n\n"
            f"Command: {wf.dispatch_command}\n"
            f"Issue Title: {issue_title}\n"
            f"Issue Body:\n{issue_body}\n"
        )
        if operator_clarification:
            prompt += f"\nOperator Clarification Provided:\n{operator_clarification}\n"

        res = await self.agent_runner.run(
            worktree_path=worktree_path,
            prompt_context=prompt,
            project_id=project_id,
            role="thinker",
            provider=provider,
            workflow=wf,
        )

        if not self._execution_is_successful(res):
            return {"status": "FAILED", "message": "Explore agent execution was not successful or evidenced."}
        full_out = res.full_output
        if "HUMAN REQUIRED" in full_out:
            options = [line.strip(" -*") for line in full_out.splitlines() if line.strip().startswith(("-", "•"))]
            if not options:
                return {"status": "FAILED", "message": "Explore requested human input without concrete options."}
            return {
                "status": "HUMAN_REQUIRED",
                "human_payload": {
                    "question": f"¿Cómo debe resolverse la ambigüedad en el Issue #{issue_number}?",
                    "options": options,
                    "agent_output": full_out[:1000] if full_out else "",
                },
            }
        return {"status": "READY_TO_PROPOSE", "execution": res}

    async def _run_propose(
        self,
        worktree_path: Path,
        provider: str,
        change_name: str,
        issue_number: int,
        issue_title: str,
        issue_body: str,
        project_id: str | None = None,
    ) -> dict[str, Any]:
        """Dispatch thinking agent to execute official OpenSpec Propose workflow."""
        wf = self.agent_runner.resolve_workflow(
            worktree_path=worktree_path,
            provider=provider,
            operation="propose",
            change_name=change_name,
        )
        prompt = (
            f"Execute official OpenSpec Propose for change '{change_name}'.\n"
            f"Workflow dispatch command: {wf.dispatch_command}\n\n"
            f"Remote Request #{issue_number}: {issue_title}\n"
            f"Description:\n{issue_body}\n"
            f"Generate canonical change planning artifacts under openspec/changes/{change_name}/: "
            f"proposal.md, specs/, design.md, and tasks.md."
        )
        res = await self.agent_runner.run(
            worktree_path=worktree_path,
            prompt_context=prompt,
            project_id=project_id,
            role="thinker",
            provider=provider,
            workflow=wf,
        )
        if not self._execution_is_successful(res):
            return {"status": "FAILED", "message": "Propose agent execution was not successful or evidenced."}
        return {"status": "READY_TO_VALIDATE", "workflow": wf, "execution": res}

    async def _run_propose_correction(
        self,
        worktree_path: Path,
        provider: str,
        change_name: str,
        error_output: str,
        project_id: str | None = None,
    ) -> bool:
        """Run correction pass by thinking agent on strict validation failure."""
        wf = self.agent_runner.resolve_workflow(
            worktree_path=worktree_path,
            provider=provider,
            operation="propose",
            change_name=change_name,
        )
        prompt = (
            f"OpenSpec strict CLI validation failed for change '{change_name}'.\n"
            f"Errors reported:\n{error_output}\n\n"
            f"Please correct the planning artifacts under openspec/changes/{change_name}/ so that "
            f"'openspec validate {change_name} --strict --type change' passes cleanly."
        )
        result = await self.agent_runner.run(
            worktree_path=worktree_path,
            prompt_context=prompt,
            project_id=project_id,
            role="thinker",
            provider=provider,
            workflow=wf,
        )
        return self._execution_is_successful(result)

    async def _run_proposal_review(
        self,
        worktree_path: Path,
        provider: str,
        change_name: str,
        project_id: str | None = None,
    ) -> bool:
        """Execute independent read-only proposal review for high complexity changes."""
        change_dir = worktree_path / "openspec" / "changes" / change_name
        proposal_text = (change_dir / "proposal.md").read_text(errors="ignore") if (change_dir / "proposal.md").exists() else ""
        prompt = (
            f"You are the independent reviewer agent (read-only). Perform independent review on OpenSpec change '{change_name}'.\n\n"
            f"Proposal Artifacts:\n{proposal_text[:3000]}\n\n"
            f"Evaluate architectural soundness, requirement coverage, and absence of overengineering.\n"
            "Emit exactly one JSON review payload matching ReviewVerdictPayload. Use verdict "
            "READY_TO_MERGE only with an empty findings list; otherwise use CHANGES_REQUIRED "
            "with concrete findings."
        )
        res = await self.agent_runner.run(
            worktree_path=worktree_path,
            prompt_context=prompt,
            project_id=project_id,
            role="reviewer",
            provider=provider,
        )
        if not self._execution_is_successful(res):
            return False
        try:
            return parse_review_verdict(res.full_output).verdict.value == "READY_TO_MERGE"
        except MalformedReviewOutputError:
            return False

    async def _run_apply(
        self,
        worktree_path: Path,
        provider: str,
        change_name: str,
        project_id: str | None = None,
    ) -> bool:
        """Dispatch configured implementer agent to execute official OpenSpec Apply workflow."""
        wf = self.agent_runner.resolve_workflow(
            worktree_path=worktree_path,
            provider=provider,
            operation="apply",
            change_name=change_name,
        )
        prompt = (
            f"You are the implementer agent. Execute official OpenSpec Apply for change '{change_name}'.\n"
            f"Workflow command: {wf.dispatch_command}\n\n"
            f"Implement all pending tasks specified in tasks.md, write unit and E2E tests, "
            f"ensure the test suite passes, and mark completed tasks as [x]."
        )
        result = await self.agent_runner.run(
            worktree_path=worktree_path,
            prompt_context=prompt,
            project_id=project_id,
            role="implementer",
            provider=provider,
            workflow=wf,
        )
        return self._execution_is_successful(result)

    async def _run_automated_tests(self, worktree_path: Path) -> tuple[bool, str]:
        """Execute project automated tests and verify exit code 0."""
        import shutil
        import sys
        pytest_bin = shutil.which("pytest") or str(Path(sys.executable).parent / "pytest")
        cmd = [pytest_bin, "-q"] if Path(pytest_bin).exists() else [sys.executable, "-m", "pytest", "-q"]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(worktree_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            evidence = stdout.decode(errors="replace") + stderr.decode(errors="replace")
            if proc.returncode == 0:
                normalized = evidence.lower()
                has_execution = bool(
                    re.search(r"\b\d+\s+(?:passed|failed|skipped|xfailed|xpassed)\b", normalized)
                    or re.search(r"collected\s+[1-9]\d*\s+items?", normalized)
                )
                if has_execution and "no tests ran" not in normalized:
                    return True, evidence
                return False, evidence or "Tests produced no collection/execution evidence."
            if "no tests ran" in evidence.lower() or proc.returncode == 5:
                return False, evidence or "No tests collected (pytest code 5)."
            return False, evidence
        except (OSError, FileNotFoundError) as exc:
            logger.warning(f"Automated test runner exception: {exc}")
            return False, f"Test execution failed to launch: {exc}"

    async def _run_verify(
        self,
        worktree_path: Path,
        provider: str,
        change_name: str,
        project_id: str | None = None,
    ) -> bool:
        """Dispatch the SAME implementer agent to execute native OpenSpec Verify workflow."""
        wf = self.agent_runner.resolve_workflow(
            worktree_path=worktree_path,
            provider=provider,
            operation="verify",
            change_name=change_name,
        )
        prompt = (
            f"Execute official OpenSpec Verify for change '{change_name}'.\n"
            f"Workflow dispatch command: {wf.dispatch_command}\n\n"
            f"Verify that all tasks and requirements are implemented and verified with green tests."
        )
        res = await self.agent_runner.run(
            worktree_path=worktree_path,
            prompt_context=prompt,
            project_id=project_id,
            role="implementer",
            provider=provider,
            workflow=wf,
        )
        if not self._execution_is_successful(res):
            return False
        try:
            return parse_review_verdict(res.full_output).verdict.value == "READY_TO_MERGE"
        except MalformedReviewOutputError:
            return False

    async def _run_code_review(
        self,
        worktree_path: Path,
        provider: str,
        change_name: str,
        project_id: str | None = None,
    ) -> bool:
        """Execute independent read-only code review for high-complexity changes."""
        diff = await self._git_run(worktree_path, ["diff", "HEAD~1..HEAD"])
        prompt = (
            f"You are the independent reviewer agent (read-only). Perform code review on OpenSpec change '{change_name}'.\n\n"
            f"Candidate Diff:\n{diff[:4000]}\n\n"
            f"Evaluate implementation correctness, security, maintainability, and absence of overengineering.\n"
            f"Emit APPROVED if code meets requirements, or CHANGES REQUESTED with actionable feedback."
        )
        res = await self.agent_runner.run(
            worktree_path=worktree_path,
            prompt_context=prompt,
            project_id=project_id,
            role="reviewer",
            provider=provider,
        )
        if not self._execution_is_successful(res):
            return False
        try:
            return parse_review_verdict(res.full_output).verdict.value == "READY_TO_MERGE"
        except MalformedReviewOutputError:
            return False

    async def _run_sync_and_archive(
        self,
        doc_path: Path,
        provider: str,
        change_name: str,
        project_id: str | None = None,
    ) -> bool:
        """Execute official OpenSpec Sync and Archive workflows with thinking agent."""
        sync_wf = self.agent_runner.resolve_workflow(
            worktree_path=doc_path,
            provider=provider,
            operation="sync",
            change_name=change_name,
        )
        archive_wf = self.agent_runner.resolve_workflow(
            worktree_path=doc_path,
            provider=provider,
            operation="archive",
            change_name=change_name,
        )

        sync_result = await self.agent_runner.run(
            worktree_path=doc_path,
            prompt_context=(
                f"Execute ONLY the official OpenSpec Sync workflow for '{change_name}'.\n"
                f"Dispatch: {sync_wf.dispatch_command}\n"
                "Return evidence of the resulting synced specs."
            ),
            project_id=project_id,
            role="thinker",
            provider=provider,
            workflow=sync_wf,
        )
        if not self._execution_is_successful(sync_result):
            return False

        archive_result = await self.agent_runner.run(
            worktree_path=doc_path,
            prompt_context=(
                f"Execute ONLY the official OpenSpec Archive workflow for '{change_name}'.\n"
                f"Dispatch: {archive_wf.dispatch_command}\n"
                "Return evidence of the resulting archive."
            ),
            project_id=project_id,
            role="thinker",
            provider=provider,
            workflow=archive_wf,
        )
        if not self._execution_is_successful(archive_result):
            return False

        # Check git status in doc worktree; if changes are uncommitted, stage and commit them
        status_result = await self._git_run(doc_path, ["status", "--porcelain"])
        if status_result.stdout.strip():
            await self._git_run(doc_path, ["add", "openspec/"])
            await self._git_run(doc_path, ["commit", "-m", f"docs({change_name}): sync specs and archive change"])
        return True

    async def _push_branch(self, worktree_path: Path, branch_name: str) -> None:
        # Git push branch
        await self._git_run(worktree_path, ["push", "-u", "origin", branch_name])

    async def _get_git_head_sha(self, worktree_path: Path) -> str:
        result = await self._git_run(worktree_path, ["rev-parse", "HEAD"])
        return result.stdout.strip()

    async def _git_run(self, cwd: Path, args: list[str]) -> GitCommandResult:
        proc = await asyncio.create_subprocess_exec(
            "git", *args,
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        result = GitCommandResult(
            tuple(args), proc.returncode or 0,
            stdout.decode(errors="replace"), stderr.decode(errors="replace"),
        )
        if not result.ok:
            raise GitOperationError(result)
        return result
