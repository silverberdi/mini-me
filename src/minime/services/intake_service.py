"""Work Intake Service for managing backlog items, canonical artifact generation, DoR, and admission."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from minime.adapters.github import GitHubAdapter
from minime.adapters.openspec import OpenSpecAdapter
from minime.domain.enums import (
    ChangeStatus,
    EventType,
    ExternalActionStatus,
    ExternalActionType,
    ExternalOutcome,
    IntakeWorkspaceCreationState,
    IntakeWorkspacePublicationState,
    OrchestrationStage,
    OrchestrationStopOutcome,
    QueuePriority,
    ReadinessState,
    SagaStatus,
    SagaType,
    WorkItemStatus,
)
from minime.domain.exceptions import (
    ManagedWorkspaceGuardDeniedError,
    UnsafeIntakeWorkspaceStateError,
)
from minime.domain.interfaces import PersistenceUnitOfWork
from minime.domain.models import (
    BacklogItem,
    Change,
    DurableSaga,
    Event,
    HumanAnswerRecord,
    IntakeWorkspaceOwnership,
    Project,
    ProjectBinding,
    RecoveryClaimContext,
    WorkItemAnswerInput,
    WorkItemCreateInput,
    WorkItemPrepareResult,
    WorkItemUpdateInput,
    WorkQueueItem,
    generate_uuid,
    utc_now,
)
from minime.logging import get_logger, set_correlation_context
from minime.services.lifecycle_transition_authority import LifecycleTransitionAuthority
from minime.services.openspec_generator import OpenSpecGenerator, slugify
from minime.services.readiness_service import ReadinessService
from minime.services.saga_engine import SagaEngine

logger = get_logger("services.intake")

INTAKE_PHASES = [
    "INTAKE_CREATED",
    "CONTEXT_CHECKED",
    "WORKSPACE_RESERVED",
    "WORKSPACE_ACTIVE",
    "OPENSPEC_AUTHORED",
    "ISSUE_BOUND",
    "PROJECT_ITEM_BOUND",
    "ARTIFACTS_PUBLISHED",
    "READINESS_EVALUATED",
    "READY",
]


def _has_passed_intake_phase(current_phase: str, target_phase: str) -> bool:
    try:
        curr_idx = INTAKE_PHASES.index(current_phase)
    except ValueError:
        curr_idx = 0
    try:
        targ_idx = INTAKE_PHASES.index(target_phase)
    except ValueError:
        targ_idx = 0
    return curr_idx >= targ_idx


def _git_porcelain_path(line: str) -> str | None:
    """Extract the filesystem path from a `git status --porcelain` v1 line.

    Handles the common ``XY PATH`` form and renames (``XY OLD -> NEW``) without
    relying on the porcelain v2 format.
    """
    if len(line) < 4:
        return None
    rest = line[3:]
    if " -> " in rest:
        rest = rest.split(" -> ", 1)[1]
    rest = rest.strip()
    if len(rest) >= 2 and rest[0] == '"' and rest[-1] == '"':
        rest = rest[1:-1].replace('\\"', '"')
    return rest


def extract_canonical_archived_change_name(dir_name: str) -> str:
    """Extract canonical change name from OpenSpec archive directory entry.

    OpenSpec archive naming convention uses either:
    1. 'YYYY-MM-DD-change-name' (10-char date prefix followed by hyphen)
    2. 'change-name' (exact change name without date prefix)
    """
    parts = dir_name.split("-", 3)
    if (
        len(parts) == 4
        and len(parts[0]) == 4
        and parts[0].isdigit()
        and len(parts[1]) == 2
        and parts[1].isdigit()
        and len(parts[2]) == 2
        and parts[2].isdigit()
    ):
        return parts[3]
    return dir_name


class IntakeService:
    """Backend service for work intake, artifact generation, and execution admission."""

    def __init__(
        self,
        uow: PersistenceUnitOfWork,
        project_root: str | Path = ".",
        github_adapter: GitHubAdapter | None = None,
        openspec_adapter: OpenSpecAdapter | None = None,
        readiness_service: ReadinessService | None = None,
        openspec_generator: OpenSpecGenerator | None = None,
        saga_engine: SagaEngine | None = None,
    ):
        self.uow = uow
        self.project_root = Path(project_root).resolve()
        self.github_adapter = github_adapter or GitHubAdapter()
        self.openspec_adapter = openspec_adapter or OpenSpecAdapter()
        self.readiness_service = readiness_service or ReadinessService(
            uow,
            openspec_adapter=self.openspec_adapter,
            github_adapter=self.github_adapter,
        )
        self.openspec_generator = openspec_generator or OpenSpecGenerator(
            project_root=self.project_root,
            uow=self.uow,
        )
        self.saga_engine = saga_engine or SagaEngine(self.uow)

    def _resolve_project_root(self, project: Project | str) -> Path:
        """Resolve canonical managed repository root for project, falling back to self.project_root."""
        project_id = project.project_id if isinstance(project, Project) else project
        binding_repo = getattr(self.uow, "project_managed_repository_bindings", None)
        if binding_repo:
            binding = binding_repo.get_by_project_id(project_id)
            if binding and binding.managed_repository_root:
                b_root = Path(binding.managed_repository_root)
                if b_root.exists() and b_root.is_dir():
                    return b_root
        return self.project_root

    def create_work_item(
        self,
        project_id: str,
        input_data: WorkItemCreateInput,
        operator_email: str = "operator",
    ) -> BacklogItem:
        """Create a new work item in the project backlog."""
        set_correlation_context(project_id=project_id, operation_id="create_work_item")

        project = self.uow.projects.get_by_id(project_id)
        if not project:
            raise ValueError(f"Project '{project_id}' not found.")

        title = input_data.title.strip()
        if not title:
            raise ValueError("Work item title cannot be empty.")

        item_key = input_data.item_key.strip() if input_data.item_key else slugify(title)

        existing = self.uow.backlog_items.get_by_project_and_key(project_id, item_key)
        if existing:
            raise ValueError(
                f"Work item with key '{item_key}' already exists in project '{project_id}'."
            )

        now = utc_now()
        item = BacklogItem(
            project_id=project_id,
            item_key=item_key,
            title=title,
            description=input_data.description,
            priority=input_data.priority,
            status=WorkItemStatus.BACKLOG,
            source=input_data.source,
            source_location=input_data.source_location,
            dependencies=input_data.dependencies,
            readiness_state=ReadinessState.NOT_READY,
            acceptance_criteria=input_data.acceptance_criteria,
            openspec_change_name=slugify(item_key),
            created_at=now,
            updated_at=now,
        )

        self.uow.backlog_items.save(item)

        event = Event(
            event_type=EventType.WORK_ITEM_CREATED,
            project_id=project_id,
            change_id=item.openspec_change_name,
            payload={
                "project_id": project_id,
                "item_key": item_key,
                "title": title,
                "priority": item.priority.value,
                "operator_email": operator_email,
            },
            timestamp=now,
        )
        self.uow.events.save(event)
        logger.info("Created backlog item '%s' for project '%s'", item_key, project_id)

        # Auto-prepare if project policy enables auto_prepare
        if getattr(project, "auto_prepare", True):
            logger.info("Auto-preparing backlog item '%s' for project '%s'", item_key, project_id)
            from minime.services.recovery_convergence_service import RecoveryConvergenceService
            rec_svc = RecoveryConvergenceService(self.uow, project_root=self.project_root)
            claim_ctx = rec_svc.acquire_claim(f"intake:{project_id}:{item_key}")
            prep_result = self.prepare_work_item(
                project_id, item_key, operator_email=operator_email, claim_context=claim_ctx
            )
            auto_prep_event = Event(
                event_type=EventType.WORK_ITEM_AUTO_PREPARED,
                project_id=project_id,
                change_id=item.openspec_change_name,
                payload={
                    "project_id": project_id,
                    "item_key": item_key,
                    "readiness_state": prep_result.readiness_state.value,
                    "status": prep_result.item.status.value,
                    "operator_email": operator_email,
                },
                timestamp=utc_now(),
            )
            self.uow.events.save(auto_prep_event)
            self.uow.commit()
            return prep_result.item

        return item

    def update_work_item(
        self,
        project_id: str,
        item_key: str,
        input_data: WorkItemUpdateInput,
        operator_email: str = "operator",
    ) -> BacklogItem:
        """Update fields of an existing backlog item."""
        set_correlation_context(project_id=project_id, operation_id="update_work_item")

        item = self.uow.backlog_items.get_by_project_and_key(project_id, item_key)
        if not item:
            raise ValueError(f"Work item '{item_key}' not found in project '{project_id}'.")

        updates: dict[str, Any] = {"updated_at": utc_now()}
        if input_data.title is not None:
            updates["title"] = input_data.title.strip()
        if input_data.description is not None:
            updates["description"] = input_data.description
        if input_data.priority is not None:
            updates["priority"] = input_data.priority
        if input_data.acceptance_criteria is not None:
            updates["acceptance_criteria"] = input_data.acceptance_criteria
        if input_data.dependencies is not None:
            updates["dependencies"] = input_data.dependencies

        updated_item = item.model_copy(update=updates)
        self.uow.backlog_items.save(updated_item)

        event = Event(
            event_type=EventType.WORK_ITEM_UPDATED,
            project_id=project_id,
            change_id=item.openspec_change_name,
            payload={
                "project_id": project_id,
                "item_key": item_key,
                "updates": {k: str(v) for k, v in updates.items()},
                "operator_email": operator_email,
            },
            timestamp=utc_now(),
        )
        self.uow.events.save(event)
        self.uow.commit()

        return updated_item

    def answer_human_question(
        self,
        project_id: str,
        item_key: str,
        input_data: WorkItemAnswerInput,
        operator_email: str = "operator",
    ) -> BacklogItem:
        """Answer a NEEDS_HUMAN product question and re-evaluate readiness."""
        set_correlation_context(project_id=project_id, operation_id="answer_human_question")

        item = self.uow.backlog_items.get_by_project_and_key(project_id, item_key)
        if not item:
            raise ValueError(f"Work item '{item_key}' not found in project '{project_id}'.")

        now = utc_now()
        record = HumanAnswerRecord(
            question=input_data.question,
            answer=input_data.answer,
            answered_by=operator_email,
            answered_at=now,
        )

        new_answers = list(item.human_answers) + [record]

        # Update description / acceptance criteria with answer context
        new_desc = item.description
        if input_data.answer.strip():
            new_desc = f"{item.description}\n\n**Clarification ({input_data.question}):** {input_data.answer}".strip()

        updated = item.model_copy(
            update={
                "human_answers": new_answers,
                "description": new_desc,
                "human_questions": [],
                "updated_at": now,
            }
        )
        self.uow.backlog_items.save(updated)

        if item.status != WorkItemStatus.PREPARING:
            authority = LifecycleTransitionAuthority(self.uow)
            updated = authority.transition_backlog_item(
                project_id=project_id,
                item_key=item_key,
                expected_from_state=item.status,
                to_state=WorkItemStatus.PREPARING,
                reason_code="answer_human_question",
                actor=operator_email,
            )

        event = Event(
            event_type=EventType.WORK_ITEM_QUESTION_ANSWERED,
            project_id=project_id,
            change_id=item.openspec_change_name,
            payload={
                "project_id": project_id,
                "item_key": item_key,
                "question": input_data.question,
                "answer": input_data.answer,
                "operator_email": operator_email,
            },
            timestamp=now,
        )
        self.uow.events.save(event)
        self.uow.commit()

        from minime.services.recovery_convergence_service import RecoveryConvergenceService
        rec_svc = RecoveryConvergenceService(self.uow, project_root=self.project_root)
        claim_ctx = rec_svc.acquire_claim(f"intake:{project_id}:{item_key}")
        prep_result = self.prepare_work_item(project_id, item_key, operator_email=operator_email, claim_context=claim_ctx)
        return prep_result.item

    def prepare_work_item(
        self,
        project_id: str,
        item_key: str,
        operator_email: str = "operator",
        claim_context: RecoveryClaimContext | None = None,
    ) -> WorkItemPrepareResult:
        from minime.domain.models import validate_claim_context_authoritative

        validate_claim_context_authoritative(self.uow, claim_context)

        set_correlation_context(project_id=project_id, operation_id="prepare_work_item")

        project = self.uow.projects.get_by_id(project_id)
        if not project:
            raise ValueError(f"Project '{project_id}' not found.")

        item = self.uow.backlog_items.get_by_project_and_key(project_id, item_key)
        if not item:
            raise ValueError(f"Work item '{item_key}' not found in project '{project_id}'.")

        now = utc_now()
        change_name = item.openspec_change_name or slugify(item.item_key)
        change_record = self.uow.changes.get_by_name(project_id, change_name)

        # Terminal Intake Protection (Root Cause 1 / Defect 1)
        is_terminal = item.status in (WorkItemStatus.COMPLETED, WorkItemStatus.CANCELLED) or (
            change_record is not None
            and change_record.status in (ChangeStatus.DONE, ChangeStatus.CANCELLED)
        )
        if is_terminal:
            logger.info(
                "Work item '%s' / change '%s' is in terminal state. Intake preparation denied.",
                item_key,
                change_name,
            )
            return WorkItemPrepareResult(
                item=item,
                openspec_change_name=change_name,
                readiness_state=item.readiness_state,
                unmet_readiness_reasons=item.unmet_readiness_reasons,
            )

        # Start or retrieve active INTAKE saga
        saga = self.saga_engine.start_saga(
            saga_type=SagaType.INTAKE,
            project_id=project_id,
            work_item_key=item_key,
            change_name=change_name,
            initial_phase="INTAKE_CREATED",
        )

        if saga.status == SagaStatus.COMPLETED or saga.current_phase == "READY":
            logger.info(
                "Saga '%s' is already COMPLETED at phase '%s'. Returning existing item.",
                saga.id,
                saga.current_phase,
            )
            return WorkItemPrepareResult(
                item=item,
                openspec_change_name=change_name,
                readiness_state=item.readiness_state,
                unmet_readiness_reasons=item.unmet_readiness_reasons,
            )

        if item.status in (
            WorkItemStatus.BACKLOG,
            WorkItemStatus.CONTEXT_CHECK,
            WorkItemStatus.BLOCKED,
        ):
            authority = LifecycleTransitionAuthority(self.uow)
            item = authority.transition_backlog_item(
                project_id=project_id,
                item_key=item_key,
                expected_from_state=item.status,
                to_state=WorkItemStatus.PREPARING,
                reason_code="prepare_start",
                actor=operator_email,
            )

        if not _has_passed_intake_phase(saga.current_phase, "CONTEXT_CHECKED"):
            self.saga_engine.advance_phase(saga, "CONTEXT_CHECKED", claim_context=claim_context)

        # Reserve and activate intake workspace
        if not _has_passed_intake_phase(saga.current_phase, "WORKSPACE_RESERVED"):
            workspace = self._reserve_intake_workspace(project, item, saga)
            self.saga_engine.advance_phase(saga, "WORKSPACE_RESERVED", claim_context=claim_context)
        else:
            intake_repo = getattr(self.uow, "intake_workspace_ownerships", None)
            workspace = intake_repo.get_active_by_item_key(project_id, item_key) if intake_repo else None
            if not workspace:
                workspace = self._reserve_intake_workspace(project, item, saga)

        if not _has_passed_intake_phase(saga.current_phase, "WORKSPACE_ACTIVE"):
            self._activate_intake_workspace(workspace, project, claim_context=claim_context)
            self.saga_engine.advance_phase(saga, "WORKSPACE_ACTIVE", claim_context=claim_context)

        # 1. OpenSpec Authored Phase
        author_action_key = f"openspec_author:{project_id}:{change_name}"
        if not _has_passed_intake_phase(saga.current_phase, "OPENSPEC_AUTHORED"):
            generated = self.openspec_generator.generate_from_backlog_item(
                item, project_name=project.display_name
            )

            if not generated.is_complete:
                updated_item = item.model_copy(
                    update={
                        "readiness_state": ReadinessState.NOT_READY,
                        "unmet_readiness_reasons": generated.missing_reasons,
                        "human_questions": generated.human_questions,
                        "updated_at": now,
                    }
                )
                self.uow.backlog_items.save(updated_item)
                if item.status != WorkItemStatus.NEEDS_HUMAN:
                    authority = LifecycleTransitionAuthority(self.uow)
                    updated_item = authority.transition_backlog_item(
                        project_id=project_id,
                        item_key=item_key,
                        expected_from_state=item.status,
                        to_state=WorkItemStatus.NEEDS_HUMAN,
                        reason_code="prepare_incomplete",
                        actor=operator_email,
                    )
                self.saga_engine.block_saga(
                    saga,
                    blocking_reason="OpenSpec generation incomplete; human clarification required.",
                    claim_context=claim_context,
                )
                self.uow.commit()

                return WorkItemPrepareResult(
                    item=updated_item,
                    openspec_change_name=change_name,
                    readiness_state=ReadinessState.NOT_READY,
                    unmet_readiness_reasons=generated.missing_reasons,
                    human_questions=generated.human_questions,
                )

            existing_author_action = self.uow.orchestration_external_actions.get_by_action_key(
                author_action_key
            )
            if (
                not existing_author_action
                or existing_author_action.status != ExternalActionStatus.COMPLETED
            ):
                def _observe_openspec():
                    from minime.domain.models import ExternalActionResult

                    change_dir = (
                        Path(workspace.canonical_workspace_path)
                        / project.openspec_path
                        / "changes"
                        / change_name
                    )
                    proposal_file = change_dir / "proposal.md"
                    tasks_file = change_dir / "tasks.md"
                    design_file = change_dir / "design.md"
                    if proposal_file.exists() and tasks_file.exists() and design_file.exists():
                        return ExternalActionResult(
                            outcome=ExternalOutcome.SUCCESS,
                            source_adapter="filesystem",
                            reason_code="OBSERVED_ON_DISK",
                            data={"change_name": change_name, "path": str(change_dir)},
                            external_id=change_name,
                        )
                    return ExternalActionResult(
                        outcome=ExternalOutcome.FAILURE,
                        source_adapter="filesystem",
                        reason_code="NOT_FOUND",
                    )

                def _mutate_openspec():
                    from minime.domain.models import ExternalActionResult

                    self.openspec_generator.write_change_to_disk(
                        project.openspec_path,
                        generated,
                        overwrite=True,
                        project_id=project_id,
                        uow=self.uow,
                        target_workspace_path=workspace.canonical_workspace_path,
                    )
                    self._commit_intake_artifacts(workspace, generated, project)
                    return ExternalActionResult(
                        outcome=ExternalOutcome.SUCCESS,
                        source_adapter="filesystem",
                        reason_code="EXECUTION_SUCCESS",
                        data={"change_name": change_name},
                        external_id=change_name,
                    )

                fenced_res = self.saga_engine.execute_fenced_external_action(
                    claim_context=claim_context,
                    action_key=author_action_key,
                    action_type=ExternalActionType.OPENSPEC_SYNC,
                    target_identity=change_name,
                    request_fingerprint=item_key,
                    mutation_fn=_mutate_openspec,
                    observation_fn=_observe_openspec,
                    saga_id=saga.id,
                )

                if fenced_res and getattr(fenced_res, "result_application_authorized", False):
                    self.saga_engine.advance_phase(saga, "OPENSPEC_AUTHORED", claim_context=claim_context)
            else:
                self.saga_engine.advance_phase(saga, "OPENSPEC_AUTHORED", claim_context=claim_context)

        # Save/update Change entity in DB if missing
        if not change_record:
            change_record = Change(
                project_id=project_id,
                name=change_name,
                status=ChangeStatus.DISCOVERED,
                proposal_path=f"{project.openspec_path}/changes/{change_name}/proposal.md",
                tasks_path=f"{project.openspec_path}/changes/{change_name}/tasks.md",
                design_path=f"{project.openspec_path}/changes/{change_name}/design.md",
                specs_paths=[f"{project.openspec_path}/changes/{change_name}/specs/spec.md"],
                discovered_at=now,
                updated_at=now,
            )
            self.uow.changes.save(change_record)

        # 3. Create or sync GitHub Issue with observe-before-repeat reconciliation & operation_key marker matching
        issue_number = item.github_issue_number
        issue_url = item.github_issue_url
        op_key = f"issue_create:{project.project_id}:{change_name}"

        if not _has_passed_intake_phase(saga.current_phase, "ISSUE_BOUND"):
            existing_issue_action = self.uow.orchestration_external_actions.get_by_action_key(
                op_key
            )
            if (
                existing_issue_action
                and existing_issue_action.status == ExternalActionStatus.COMPLETED
                and existing_issue_action.remote_identifier
            ):
                issue_number = int(existing_issue_action.remote_identifier)
                issue_url = f"https://github.com/{project.repository}/issues/{issue_number}"
            else:
                from minime.services.reconciliation_authority import ReconciliationAuthority

                rec_auth = ReconciliationAuthority(self.uow)
                rec_res = rec_auth.reconcile_issue_creation(
                    github_adapter=self.github_adapter,
                    repository=project.repository,
                    operation_key=op_key,
                    title=item.title,
                )
                if existing_issue_action:
                    retry_auth = rec_res.outcome != ExternalOutcome.SUCCESS
                    action = rec_auth.reconcile_observe_before_repeat(
                        op_key, rec_res, original_mutation_retry_authorized=retry_auth
                    )
                else:
                    action = None

                if rec_res.outcome == ExternalOutcome.SUCCESS and rec_res.data:
                    issue_number = rec_res.data.get("number")
                    issue_url = rec_res.data.get("html_url")
                    self.saga_engine.reserve_action(
                        action_key=op_key,
                        action_type=ExternalActionType.ISSUE_CREATE,
                        target_identity=change_name,
                        request_fingerprint=item_key,
                        saga_id=saga.id,
                    )
                    self.saga_engine.record_action_result(
                        op_key,
                        status=ExternalActionStatus.COMPLETED,
                        remote_identifier=str(issue_number),
                    )
                elif action and action.status in (
                    ExternalActionStatus.AMBIGUOUS,
                    ExternalActionStatus.UNKNOWN,
                ):
                    self.saga_engine.block_saga(
                        saga,
                        blocking_reason=f"GitHub Issue creation action is in ambiguous status ({action.status.value}). Safe retry unproven.",
                        claim_context=claim_context,
                    )
                    self.uow.commit()
                    return WorkItemPrepareResult(
                        item=item,
                        openspec_change_name=change_name,
                        readiness_state=ReadinessState.NOT_READY,
                        unmet_readiness_reasons=[
                            f"GitHub Issue creation action is in status {action.status.value}."
                        ],
                    )
                else:
                    def _mutate_issue():
                        return self.github_adapter.create_issue(
                            repository=project.repository,
                            title=f"[{change_name}] {item.title}",
                            body=f"## Work Item: {item.title}\n\n{item.description}\n\n**OpenSpec Change:** `{change_name}`\n\n<!-- minime-opkey: {op_key} -->",
                            labels=[f"priority:{item.priority.value.lower()}"],
                            operation_key=op_key,
                        )

                    try:
                        issue_res = self.saga_engine.execute_fenced_external_action(
                            claim_context=claim_context,
                            action_key=op_key,
                            action_type=ExternalActionType.ISSUE_CREATE,
                            target_identity=change_name,
                            request_fingerprint=item_key,
                            mutation_fn=_mutate_issue,
                            saga_id=saga.id,
                        )
                        if issue_res and getattr(issue_res, "outcome", None) == ExternalOutcome.SUCCESS and getattr(issue_res, "data", None):
                            issue_number = getattr(issue_res, "data", {}).get("number")
                            issue_url = getattr(issue_res, "data", {}).get("html_url")
                    except Exception as exc:
                        logger.warning(
                            "Could not create remote GitHub issue for '%s': %s", change_name, exc
                        )

            if not issue_number:
                self.saga_engine.block_saga(
                    saga,
                    blocking_reason=f"GitHub Issue creation for '{change_name}' failed or unverified.",
                    claim_context=claim_context,
                )
                self.uow.commit()
                return WorkItemPrepareResult(
                    item=item,
                    openspec_change_name=change_name,
                    readiness_state=ReadinessState.NOT_READY,
                    unmet_readiness_reasons=["GitHub Issue creation unverified."],
                )

            self.saga_engine.advance_phase(
                saga,
                "ISSUE_BOUND",
                evidence_references={"issue_number": issue_number, "issue_url": issue_url},
                claim_context=claim_context,
            )

        # 4. Sync GitHub Project v2 item with observe-before-repeat reconciliation
        project_item_id = item.github_project_item_id
        if not _has_passed_intake_phase(saga.current_phase, "PROJECT_ITEM_BOUND"):
            if not project_item_id and project.github_project_number and issue_url:
                op_key = f"project_item_add:{project.project_id}:{change_name}"
                existing_proj_action = self.uow.orchestration_external_actions.get_by_action_key(
                    op_key
                )
                if (
                    existing_proj_action
                    and existing_proj_action.status == ExternalActionStatus.COMPLETED
                    and existing_proj_action.remote_identifier
                ):
                    project_item_id = existing_proj_action.remote_identifier
                else:
                    from minime.services.reconciliation_authority import ReconciliationAuthority

                    rec_auth = ReconciliationAuthority(self.uow)
                    rec_res = rec_auth.reconcile_project_item_add(
                        github_adapter=self.github_adapter,
                        project_number=project.github_project_number,
                        owner=project.github_project_owner or "silverberdi",
                        issue_url=issue_url,
                        operation_key=op_key,
                    )
                    if existing_proj_action:
                        retry_auth = rec_res.outcome != ExternalOutcome.SUCCESS
                        action = rec_auth.reconcile_observe_before_repeat(
                            op_key, rec_res, original_mutation_retry_authorized=retry_auth
                        )
                    else:
                        action = None

                    if rec_res.outcome == ExternalOutcome.SUCCESS and rec_res.data:
                        project_item_id = str(rec_res.data)
                        self.saga_engine.reserve_action(
                            action_key=op_key,
                            action_type=ExternalActionType.PROJECT_ITEM_ADD,
                            target_identity=change_name,
                            request_fingerprint=item_key,
                            saga_id=saga.id,
                        )
                        self.saga_engine.record_action_result(
                            op_key,
                            status=ExternalActionStatus.COMPLETED,
                            remote_identifier=project_item_id,
                        )
                    elif action and action.status in (
                        ExternalActionStatus.AMBIGUOUS,
                        ExternalActionStatus.UNKNOWN,
                    ):
                        self.saga_engine.block_saga(
                            saga,
                            blocking_reason=f"Project item action is in ambiguous status ({action.status.value}). Safe retry unproven.",
                            claim_context=claim_context,
                        )
                        self.uow.commit()
                        return WorkItemPrepareResult(
                            item=item,
                            openspec_change_name=change_name,
                            readiness_state=ReadinessState.NOT_READY,
                            unmet_readiness_reasons=[
                                f"Project item action is in status {action.status.value}."
                            ],
                        )
                    else:
                        def _mutate_project_item_add():
                            return self.github_adapter.add_issue_to_project(
                                project_number=project.github_project_number,
                                owner=project.github_project_owner or "silverberdi",
                                issue_url=issue_url,
                                operation_key=op_key,
                            )

                        try:
                            project_res = self.saga_engine.execute_fenced_external_action(
                                claim_context=claim_context,
                                action_key=op_key,
                                action_type=ExternalActionType.PROJECT_ITEM_ADD,
                                target_identity=change_name,
                                request_fingerprint=item_key,
                                mutation_fn=_mutate_project_item_add,
                                saga_id=saga.id,
                            )
                            if project_res and getattr(project_res, "outcome", None) == ExternalOutcome.SUCCESS and getattr(project_res, "data", None):
                                project_item_id = str(getattr(project_res, "data", ""))
                        except Exception as exc:
                            logger.warning(
                                "Could not sync issue '%s' to GitHub Project: %s", issue_url, exc
                            )
                            self.saga_engine.record_action_result(
                                op_key, status=ExternalActionStatus.FAILED, error_message=str(exc)
                            )

            self.saga_engine.advance_phase(
                saga,
                "PROJECT_ITEM_BOUND",
                evidence_references={"github_project_item_id": project_item_id},
                claim_context=claim_context,
            )

        # 5. Create or sync durable ProjectBinding
        binding = self.uow.bindings.get_by_project_and_change(project_id, change_name)
        if not binding:
            binding = ProjectBinding(
                project_id=project_id,
                repository=project.repository,
                github_issue_number=issue_number,
                github_project_item_id=project_item_id,
                openspec_change_name=change_name,
                is_valid=True,
            )
            self.uow.bindings.save(binding)
        else:
            binding.github_issue_number = issue_number
            binding.github_project_item_id = project_item_id
            binding.is_valid = True
            binding.updated_at = now
            self.uow.bindings.save(binding)
        self.uow.commit()

        # 5.5 Artifact Publication Phase (Compare-And-Swap)
        if not _has_passed_intake_phase(saga.current_phase, "ARTIFACTS_PUBLISHED"):
            try:
                published_sha = self._publish_intake_artifacts_cas(workspace, project)
                self.saga_engine.advance_phase(
                    saga,
                    "ARTIFACTS_PUBLISHED",
                    evidence_references={"published_sha": published_sha},
                    claim_context=claim_context,
                )
            except Exception as exc:
                logger.error("Artifact publication failed for '%s': %s", change_name, exc)
                authority = LifecycleTransitionAuthority(self.uow)
                if item.status != WorkItemStatus.NEEDS_HUMAN:
                    authority.transition_backlog_item(
                        project_id=project_id,
                        item_key=item_key,
                        expected_from_state=item.status,
                        to_state=WorkItemStatus.NEEDS_HUMAN,
                        reason_code="conflicting_intake_publication_ref",
                        actor=operator_email,
                    )
                self.saga_engine.block_saga(
                    saga,
                    blocking_reason=f"Artifact publication failed: {exc}",
                    claim_context=claim_context,
                )
                self.uow.commit()
                return WorkItemPrepareResult(
                    item=item,
                    openspec_change_name=change_name,
                    readiness_state=ReadinessState.NOT_READY,
                    unmet_readiness_reasons=[f"Artifact publication failed: {exc}"],
                )

        # 6. Evaluate Definition of Ready (DoR)
        readiness_eval = self.readiness_service.evaluate_and_persist_change_readiness(
            project_id=project_id,
            change_name=change_name,
            project_root=str(self.project_root),
            github_repo=project.repository,
            github_issue=issue_number,
        )

        final_status = WorkItemStatus.READY if readiness_eval.is_ready else WorkItemStatus.PREPARING
        final_readiness = readiness_eval.status

        self.saga_engine.advance_phase(
            saga,
            "READINESS_EVALUATED",
            evidence_references={
                "is_ready": readiness_eval.is_ready,
                "status": final_readiness.value,
            },
            claim_context=claim_context,
        )

        # 7. Update BacklogItem state
        updated_item = item.model_copy(
            update={
                "openspec_change_name": change_name,
                "github_issue_number": issue_number,
                "github_issue_url": issue_url,
                "github_project_item_id": project_item_id,
                "readiness_state": final_readiness,
                "unmet_readiness_reasons": readiness_eval.unmet_reasons,
                "human_questions": [],
                "updated_at": now,
            }
        )
        self.uow.backlog_items.save(updated_item)
        if item.status != final_status:
            authority = LifecycleTransitionAuthority(self.uow)
            updated_item = authority.transition_backlog_item(
                project_id=project_id,
                item_key=item_key,
                expected_from_state=item.status,
                to_state=final_status,
                reason_code="prepare_complete",
                actor=operator_email,
            )

        if readiness_eval.is_ready:
            authority = LifecycleTransitionAuthority(self.uow)
            c_rec = self.uow.changes.get_by_name(project_id, change_name)
            if c_rec and c_rec.status != ChangeStatus.READY:
                authority.transition_change(
                    project_id=project_id,
                    name=change_name,
                    expected_from_state=c_rec.status,
                    to_state=ChangeStatus.READY,
                    reason_code="dor_ready",
                    actor=operator_email,
                )
            self.saga_engine.advance_phase(saga, "READY", claim_context=claim_context)
            self.saga_engine.complete_saga(saga, claim_context=claim_context)
        else:
            self.saga_engine.block_saga(
                saga, blocking_reason="; ".join(readiness_eval.unmet_reasons), claim_context=claim_context
            )

        # 8. Update WorkQueueItem for scheduler discovery
        queue_item = self.uow.work_queue.get_by_project_and_change(project_id, change_name)
        queue_kwargs = {
            "project_id": project_id,
            "change_name": change_name,
            "github_issue_number": issue_number,
            "github_issue_title": item.title,
            "github_project_item_id": project_item_id,
            "priority": item.priority,
            "readiness_state": final_readiness,
            "unmet_readiness_reasons": readiness_eval.unmet_reasons,
            "blocked_reason": "; ".join(readiness_eval.unmet_reasons)
            if not readiness_eval.is_ready
            else None,
            "admission_eligible": readiness_eval.is_ready
            and final_readiness == ReadinessState.READY,
            "discovered_at": queue_item.discovered_at if queue_item else now,
            "last_evaluated_at": now,
        }
        if queue_item:
            queue_kwargs["queue_item_id"] = queue_item.queue_item_id

        self.uow.work_queue.save(WorkQueueItem(**queue_kwargs))

        event = Event(
            event_type=EventType.WORK_ITEM_PREPARED,
            project_id=project_id,
            change_id=change_name,
            payload={
                "project_id": project_id,
                "item_key": item_key,
                "change_name": change_name,
                "issue_number": issue_number,
                "readiness": final_readiness.value,
                "operator_email": operator_email,
            },
            timestamp=now,
        )
        self.uow.events.save(event)
        self.uow.commit()

        logger.info(
            "Prepared work item '%s' (change: '%s', issue: #%s, readiness: %s)",
            item_key,
            change_name,
            issue_number,
            final_readiness.value,
        )

        return WorkItemPrepareResult(
            item=updated_item,
            openspec_change_name=change_name,
            github_issue_number=issue_number,
            github_project_item_id=project_item_id,
            readiness_state=final_readiness,
            unmet_readiness_reasons=readiness_eval.unmet_reasons,
            human_questions=[],
        )

    def start_work_item(
        self,
        project_id: str,
        item_key: str,
        operator_email: str = "operator",
    ) -> BacklogItem:
        """Start execution of a READY work item through the autonomous scheduler."""
        set_correlation_context(project_id=project_id, operation_id="start_work_item")

        item = self.uow.backlog_items.get_by_project_and_key(project_id, item_key)
        if not item:
            raise ValueError(f"Work item '{item_key}' not found in project '{project_id}'.")

        change_name = item.openspec_change_name or slugify(item.item_key)

        # 1. Verify DoR Readiness
        if item.readiness_state != ReadinessState.READY:
            from minime.services.recovery_convergence_service import RecoveryConvergenceService
            rec_svc = RecoveryConvergenceService(self.uow, project_root=self.project_root)
            claim_ctx = rec_svc.acquire_claim(f"intake:{project_id}:{item_key}")
            prep_res = self.prepare_work_item(project_id, item_key, operator_email=operator_email, claim_context=claim_ctx)
            item = prep_res.item
            if item.readiness_state != ReadinessState.READY:
                reasons = (
                    "; ".join(item.unmet_readiness_reasons) or "Definition of Ready not satisfied."
                )
                raise ValueError(f"Work item '{item_key}' is not READY: {reasons}")

        # 2. Duplicate Start Suppression / Idempotency
        # Check if an active orchestration run already exists for this change
        active_runs = self.uow.orchestration_runs.list_runs(project_id=project_id)
        for run in active_runs:
            if run.change_name == change_name and run.is_active:
                logger.info(
                    "Work item '%s' already has active orchestration run '%s'. Reusing existing run.",
                    item_key,
                    run.run_id,
                )
                if item.run_id != run.run_id:
                    updated_item = item.model_copy(
                        update={
                            "run_id": run.run_id,
                            "updated_at": utc_now(),
                        }
                    )
                    self.uow.backlog_items.save(updated_item)
                    self.uow.commit()
                    return updated_item
                return item

        # 3. Admit through the converged scheduler admission authority. Never bypass
        # scheduler policy with a direct orchestration admit_change call.
        from minime.services.scheduler_service import SchedulerService

        scheduler = SchedulerService(
            uow=self.uow,
            project_root=self.project_root,
            readiness_service=self.readiness_service,
        )
        _decision, decision_record, run = scheduler.admit_work_item(project_id, change_name)
        if run is None:
            reason = decision_record.reason_summary if decision_record else "admission blocked"
            raise ValueError(f"Work item admission blocked by scheduler policy: {reason}")

        now = utc_now()
        item_refreshed = self.uow.backlog_items.get_by_project_and_key(project_id, item_key) or item
        updated_item = item_refreshed.model_copy(
            update={
                "run_id": run.run_id,
                "updated_at": now,
            }
        )
        self.uow.backlog_items.save(updated_item)

        event = Event(
            event_type=EventType.WORK_ITEM_STARTED,
            project_id=project_id,
            change_id=change_name,
            payload={
                "project_id": project_id,
                "item_key": item_key,
                "run_id": run.run_id,
                "operator_email": operator_email,
            },
            timestamp=now,
        )
        self.uow.events.save(event)
        self.uow.commit()

        logger.info(
            "Started execution for work item '%s' (run_id: '%s')",
            item_key,
            run.run_id,
        )
        return updated_item

    def delete_work_item(
        self,
        project_id: str,
        item_key: str,
        operator_email: str = "operator",
    ) -> None:
        """Delete / cancel a backlog item."""
        set_correlation_context(project_id=project_id, operation_id="delete_work_item")

        item = self.uow.backlog_items.get_by_project_and_key(project_id, item_key)
        if not item:
            return

        if item.status != WorkItemStatus.CANCELLED:
            authority = LifecycleTransitionAuthority(self.uow)
            authority.transition_backlog_item(
                project_id=project_id,
                item_key=item_key,
                expected_from_state=item.status,
                to_state=WorkItemStatus.CANCELLED,
                reason_code="delete_work_item",
                actor=operator_email,
            )

        event = Event(
            event_type=EventType.WORK_ITEM_CANCELLED,
            project_id=project_id,
            change_id=item.openspec_change_name,
            payload={
                "project_id": project_id,
                "item_key": item_key,
                "operator_email": operator_email,
            },
            timestamp=utc_now(),
        )
        self.uow.events.save(event)
        self.uow.commit()

    def reconcile_and_persist_backlog_items(
        self, project_id: str | None = None
    ) -> list[BacklogItem]:
        """Reconcile backlog items against canonical evidence and persist state transitions via LifecycleTransitionAuthority."""
        projects = self.uow.projects.list_all()
        if project_id:
            projects = [p for p in projects if p.project_id == project_id]

        reconciled_items: list[BacklogItem] = []
        authority = LifecycleTransitionAuthority(self.uow)

        for project in projects:
            eff_root = self._resolve_project_root(project)
            pid = project.project_id
            items = self.uow.backlog_items.list_by_project(pid)
            if not items:
                continue

            runs = self.uow.orchestration_runs.list_runs(project_id=pid)
            runs_by_change: dict[str, list[Any]] = {}
            for r in runs:
                runs_by_change.setdefault(r.change_name, []).append(r)

            changes = self.uow.changes.list_by_project(pid)
            changes_by_name = {c.name: c for c in changes}

            archived_change_names: set[str] = set()
            archive_dir = eff_root / project.openspec_path / "changes" / "archive"
            if archive_dir.exists() and archive_dir.is_dir():
                for p in archive_dir.iterdir():
                    if p.is_dir():
                        archived_change_names.add(p.name)
                        archived_change_names.add(extract_canonical_archived_change_name(p.name))

            for item in items:
                if item.status in (WorkItemStatus.COMPLETED, WorkItemStatus.CANCELLED):
                    reconciled_items.append(item)
                    continue

                change_name = item.openspec_change_name or item.item_key
                item_runs = runs_by_change.get(change_name, []) or runs_by_change.get(item.item_key, [])
                latest_run = item_runs[-1] if item_runs else None
                change_rec = changes_by_name.get(change_name) or changes_by_name.get(item.item_key)

                is_archived = (
                    change_name in archived_change_names
                    or item.item_key in archived_change_names
                )
                is_run_completed = bool(
                    latest_run
                    and (
                        latest_run.current_stage == OrchestrationStage.COMPLETED
                        or latest_run.stop_outcome == OrchestrationStopOutcome.COMPLETED
                    )
                )
                is_done = (
                    is_archived
                    or is_run_completed
                    or bool(change_rec and change_rec.status == ChangeStatus.DONE)
                )
                is_cancelled = bool(
                    (change_rec and change_rec.status == ChangeStatus.CANCELLED)
                    or (latest_run and latest_run.stop_outcome == OrchestrationStopOutcome.CANCELLED)
                )

                new_status = item.status
                new_run_id = item.run_id
                reason_code = "backlog_reconciliation"

                if is_done:
                    new_status = WorkItemStatus.COMPLETED
                    reason_code = "canonical_completion_evidence"
                elif is_cancelled:
                    new_status = WorkItemStatus.CANCELLED
                    reason_code = "canonical_cancellation_evidence"
                elif latest_run and latest_run.is_active:
                    new_run_id = latest_run.run_id
                    new_status = WorkItemStatus.RUNNING
                    reason_code = "active_run_reconciliation"
                elif latest_run and latest_run.stop_outcome in {
                    OrchestrationStopOutcome.NEEDS_HUMAN,
                    OrchestrationStopOutcome.READY_FOR_HUMAN_MERGE,
                }:
                    new_run_id = latest_run.run_id
                    new_status = WorkItemStatus.NEEDS_HUMAN
                    reason_code = "human_gate_reconciliation"
                elif item.status == WorkItemStatus.READY:
                    active_change_dir = (
                        eff_root / project.openspec_path / "changes" / change_name
                    )
                    active_artifacts_present = active_change_dir.exists() and active_change_dir.is_dir()
                    if not active_artifacts_present or item.readiness_state != ReadinessState.READY:
                        new_status = WorkItemStatus.BLOCKED
                        reason_code = "stale_ready_artifacts_missing"
                elif (
                    not is_done
                    and item.status in (WorkItemStatus.RUNNING, WorkItemStatus.PREPARING)
                    and not item_runs
                ):
                    if item.readiness_state == ReadinessState.READY:
                        new_status = WorkItemStatus.READY
                        reason_code = "orphaned_preparing_to_ready"
                    else:
                        new_status = WorkItemStatus.BACKLOG
                        reason_code = "orphaned_preparing_to_backlog"

                if new_status != item.status:
                    try:
                        updated_item = authority.transition_backlog_item(
                            project_id=pid,
                            item_key=item.item_key,
                            expected_from_state=item.status,
                            to_state=new_status,
                            run_id=new_run_id,
                            reason_code=reason_code,
                            actor="system-backlog-convergence",
                        )
                        if new_status == WorkItemStatus.BLOCKED and reason_code == "stale_ready_artifacts_missing":
                            updated_item = updated_item.model_copy(
                                update={
                                    "readiness_state": ReadinessState.NOT_READY,
                                    "unmet_readiness_reasons": ["stale_ready_artifacts_missing"],
                                }
                            )
                            self.uow.backlog_items.save(updated_item)
                        reconciled_items.append(updated_item)
                    except Exception as exc:
                        logger.warning(
                            "Backlog lifecycle convergence transition failed for item '%s' (%s -> %s): %s",
                            item.item_key,
                            item.status.value,
                            new_status.value,
                            exc,
                        )
                        reconciled_items.append(item)
                else:
                    reconciled_items.append(item)

        self.uow.commit()
        return reconciled_items

    def reconcile_backlog_projections(self, project_id: str) -> list[BacklogItem]:
        """Reconcile and project accurate backlog item execution states against canonical runs and changes."""
        items = self.uow.backlog_items.list_by_project(project_id)
        if not items:
            return []

        runs = self.uow.orchestration_runs.list_runs(project_id=project_id)
        runs_by_change: dict[str, list[Any]] = {}
        for r in runs:
            runs_by_change.setdefault(r.change_name, []).append(r)

        changes = self.uow.changes.list_by_project(project_id)
        changes_by_name = {c.name: c for c in changes}

        # Check archived changes on disk if openspec path exists
        project = self.uow.projects.get_by_id(project_id)
        archived_change_names: set[str] = set()
        if project:
            eff_root = self._resolve_project_root(project)
            archive_dir = eff_root / project.openspec_path / "changes" / "archive"
            if archive_dir.exists() and archive_dir.is_dir():
                for p in archive_dir.iterdir():
                    if p.is_dir():
                        archived_change_names.add(p.name)
                        parts = p.name.split("-", 3)
                        if len(parts) == 4 and parts[0].isdigit() and len(parts[0]) == 4:
                            archived_change_names.add(parts[3])

        reconciled_items: list[BacklogItem] = []
        for item in items:
            if item.status in (WorkItemStatus.COMPLETED, WorkItemStatus.CANCELLED):
                reconciled_items.append(item)
                continue

            change_name = item.openspec_change_name or item.item_key
            item_runs = runs_by_change.get(change_name, []) or runs_by_change.get(item.item_key, [])
            latest_run = item_runs[-1] if item_runs else None
            change_rec = changes_by_name.get(change_name) or changes_by_name.get(item.item_key)

            is_archived = (
                change_name in archived_change_names
                or item.item_key in archived_change_names
                or any(
                    a == change_name
                    or a.endswith(f"-{change_name}")
                    or a == item.item_key
                    or a.endswith(f"-{item.item_key}")
                    for a in archived_change_names
                )
            )
            is_run_completed = bool(
                latest_run
                and (
                    latest_run.current_stage == OrchestrationStage.COMPLETED
                    or latest_run.stop_outcome == OrchestrationStopOutcome.COMPLETED
                )
            )
            is_done = (
                is_archived
                or is_run_completed
                or bool(change_rec and change_rec.status == ChangeStatus.DONE)
            )
            is_cancelled = bool(change_rec and change_rec.status == ChangeStatus.CANCELLED)

            new_status = item.status
            new_run_id = item.run_id

            if is_done:
                new_status = WorkItemStatus.COMPLETED
            elif is_cancelled:
                new_status = WorkItemStatus.CANCELLED
            elif latest_run:
                new_run_id = latest_run.run_id
                if latest_run.is_active:
                    new_status = WorkItemStatus.RUNNING
                elif latest_run.stop_outcome in {
                    OrchestrationStopOutcome.NEEDS_HUMAN,
                    OrchestrationStopOutcome.READY_FOR_HUMAN_MERGE,
                }:
                    new_status = WorkItemStatus.NEEDS_HUMAN
                elif latest_run.stop_outcome == OrchestrationStopOutcome.CANCELLED:
                    new_status = WorkItemStatus.CANCELLED
            elif (
                not is_done
                and item.status in (WorkItemStatus.RUNNING, WorkItemStatus.PREPARING)
                and not item_runs
            ):
                if item.readiness_state == ReadinessState.READY:
                    new_status = WorkItemStatus.READY
                else:
                    new_status = WorkItemStatus.BACKLOG

            if new_status != item.status or new_run_id != item.run_id:
                reconciled_items.append(
                    item.model_copy(update={"status": new_status, "run_id": new_run_id})
                )
            else:
                reconciled_items.append(item)

        return reconciled_items

    @staticmethod
    def is_blocked_retry_eligible(item: BacklogItem) -> bool:
        """Determine if a BLOCKED backlog item is eligible for single-cycle autonomous preparation.

        Autonomous re-preparation is permitted ONLY when the normalized blocker set
        contains EXACTLY the single canonical synthetic convergence reason ['stale_ready_artifacts_missing'].
        If any other blocker, combination of blockers, or empty set is present, retry is forbidden.
        """
        if item.status != WorkItemStatus.BLOCKED:
            return False

        reasons = item.unmet_readiness_reasons or []
        normalized_reasons = [str(r).strip().lower() for r in reasons if str(r).strip()]

        return normalized_reasons == ["stale_ready_artifacts_missing"]

    def sweep_unprepared_backlog_items(
        self,
        project_id: str | None = None,
    ) -> list[BacklogItem]:
        """Autonomously sweep and prepare eligible canonical backlog items."""
        projects = self.uow.projects.list_all()
        if project_id:
            projects = [p for p in projects if p.project_id == project_id]

        prepared_items: list[BacklogItem] = []
        for project in projects:
            if not getattr(project, "auto_prepare", True):
                continue

            # ROADMAP state is a pure projection. Preserve the persisted lifecycle
            # record, but use current source evidence to decide whether autonomous
            # preparation is authorized.
            roadmap_ready_keys: set[str] = set()
            try:
                from minime.services.context_discovery_service import ContextDiscoveryService

                _, projections = ContextDiscoveryService(
                    self.uow, project_root=self.project_root
                ).discover_context_pure(project.project_id)
                roadmap_ready_keys = {
                    projection.item_key
                    for projection in projections
                    if projection.source.value == "ROADMAP"
                    and projection.status == WorkItemStatus.READY
                }
            except Exception as exc:
                # Fail closed for ROADMAP-derived work if present evidence cannot be
                # observed. Local/manual backlog behavior remains unaffected.
                logger.warning(
                    "Unable to observe roadmap eligibility for project '%s': %s",
                    project.project_id,
                    exc,
                )

            items = self.uow.backlog_items.list_by_project(project.project_id)
            unprepared = [
                it
                for it in items
                if (
                    it.status in (
                        WorkItemStatus.BACKLOG,
                        WorkItemStatus.CONTEXT_CHECK,
                        WorkItemStatus.PREPARING,
                    )
                    or (it.status == WorkItemStatus.BLOCKED and IntakeService.is_blocked_retry_eligible(it))
                )
                and it.readiness_state != ReadinessState.READY
                and it.status
                not in (
                    WorkItemStatus.NEEDS_HUMAN,
                    WorkItemStatus.CANCELLED,
                    WorkItemStatus.COMPLETED,
                    WorkItemStatus.RUNNING,
                    WorkItemStatus.ADMITTED,
                )
                and (
                    it.source.value != "ROADMAP"
                    or it.item_key in roadmap_ready_keys
                )
            ]

            priority_order = {
                QueuePriority.CRITICAL: 0,
                QueuePriority.HIGH: 1,
                QueuePriority.NORMAL: 2,
                QueuePriority.LOW: 3,
            }
            unprepared.sort(key=lambda x: priority_order.get(x.priority, 99))

            for item in unprepared:
                try:
                    logger.info(
                        "Autonomous intake sweeping unprepared backlog item '%s' for project '%s'",
                        item.item_key,
                        project.project_id,
                    )
                    from minime.services.recovery_convergence_service import (
                        RecoveryConvergenceService,
                    )
                    rec_svc = RecoveryConvergenceService(self.uow, project_root=self.project_root)
                    claim_ctx = rec_svc.acquire_claim(f"intake:{project.project_id}:{item.item_key}")
                    res = self.prepare_work_item(
                        project.project_id,
                        item.item_key,
                        operator_email="system-autonomous-intake",
                        claim_context=claim_ctx,
                    )
                    prepared_items.append(res.item)
                except Exception as exc:
                    logger.warning(
                        "Autonomous intake sweep failed for item '%s' in project '%s': %s",
                        item.item_key,
                        project.project_id,
                        exc,
                        exc_info=True,
                    )

        return prepared_items

    def _reserve_intake_workspace(
        self, project: Project, item: BacklogItem, saga: DurableSaga
    ) -> IntakeWorkspaceOwnership:
        intake_repo = getattr(self.uow, "intake_workspace_ownerships", None)
        change_name = item.openspec_change_name or slugify(item.item_key)
        if intake_repo:
            existing = intake_repo.get_active_by_item_key(project.project_id, item.item_key)
            if existing:
                return existing

        binding_repo = getattr(self.uow, "project_managed_repository_bindings", None)
        binding = binding_repo.get_by_project_id(project.project_id) if binding_repo else None
        wt_parent = binding.worktree_parent_dir if binding else str(self.project_root / ".minime" / "worktrees")
        managed_root = binding.managed_repository_root if binding else str(self.project_root)
        repo_identity = binding.canonical_repository_identity if binding else project.repository

        workspace_id = generate_uuid()
        canonical_workspace_path = os.path.realpath(
            os.path.join(wt_parent, "intake-workspaces", project.project_id, workspace_id)
        )

        base_sha = "main"
        if os.path.exists(managed_root):
            try:
                res = subprocess.run(
                    ["git", "rev-parse", "HEAD"],
                    cwd=managed_root,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if res.returncode == 0 and res.stdout.strip():
                    base_sha = res.stdout.strip()
            except Exception:
                pass

        ownership = IntakeWorkspaceOwnership(
            workspace_id=workspace_id,
            project_id=project.project_id,
            item_key=item.item_key,
            saga_id=saga.id,
            change_name=change_name,
            canonical_workspace_path=canonical_workspace_path,
            canonical_repository_identity=repo_identity,
            base_sha=base_sha,
            creation_state=IntakeWorkspaceCreationState.RESERVED,
            publication_state=IntakeWorkspacePublicationState.UNPUBLISHED,
        )

        if intake_repo:
            intake_repo.save(ownership)
            self.uow.commit()

        return ownership

    def _activate_intake_workspace(
        self,
        ownership: IntakeWorkspaceOwnership,
        project: Project,
        claim_context: RecoveryClaimContext | None = None,
    ) -> None:
        binding_repo = getattr(self.uow, "project_managed_repository_bindings", None)
        binding = binding_repo.get_by_project_id(project.project_id) if binding_repo else None
        managed_root = binding.managed_repository_root if binding else str(self.project_root)

        ws_path = ownership.canonical_workspace_path
        os.makedirs(os.path.dirname(ws_path), exist_ok=True)

        marker_path = os.path.join(ws_path, ".minime_intake_workspace")
        worktree_created = False

        if os.path.exists(ws_path) and os.path.exists(marker_path):
            worktree_created = True
        else:
            if os.path.exists(managed_root):
                try:
                    branch_name = f"intake/{ownership.change_name}"
                    b_check = subprocess.run(
                        ["git", "rev-parse", "--verify", branch_name],
                        cwd=managed_root,
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    if b_check.returncode == 0:
                        cmd = ["git", "worktree", "add", ws_path, branch_name]
                    else:
                        cmd = ["git", "worktree", "add", "-b", branch_name, ws_path, ownership.base_sha]
                    res = subprocess.run(
                        cmd,
                        cwd=managed_root,
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    if res.returncode == 0:
                        worktree_created = True
                    else:
                        logger.warning("Git worktree add stderr: %s", res.stderr)
                except Exception as exc:
                    logger.warning("Failed creating git worktree: %s", exc)

            if not worktree_created:
                os.makedirs(ws_path, exist_ok=True)

            marker_data = {
                "workspace_id": ownership.workspace_id,
                "project_id": ownership.project_id,
                "item_key": ownership.item_key,
                "saga_id": ownership.saga_id,
                "change_name": ownership.change_name,
                "canonical_repository_identity": ownership.canonical_repository_identity,
            }
            with open(marker_path, "w", encoding="utf-8") as f:
                json.dump(marker_data, f, indent=2)

        ownership.creation_state = IntakeWorkspaceCreationState.ACTIVE
        intake_repo = getattr(self.uow, "intake_workspace_ownerships", None)
        if intake_repo:
            intake_repo.save(ownership)
            self.uow.commit()

    def _compute_artifact_sha256(self, generated: Any) -> dict[str, str]:
        """Compute deterministic SHA-256 fingerprints for the approved artifact manifest."""
        contents = {
            "proposal.md": generated.proposal_content,
            "tasks.md": generated.tasks_content,
            **generated.specs,
        }
        if generated.design_content:
            contents["design.md"] = generated.design_content
        return {
            rel_path: hashlib.sha256(content.encode("utf-8")).hexdigest()
            for rel_path, content in contents.items()
        }

    def _rev_parse_head(self, ws_path: str) -> str:
        """Resolve HEAD authoritatively, raising on failure (never falls back to base_sha)."""
        head_res = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ws_path,
            capture_output=True,
            text=True,
            check=False,
        )
        if head_res.returncode != 0 or not head_res.stdout.strip():
            raise UnsafeIntakeWorkspaceStateError(
                f"Git rev-parse HEAD failed in intake workspace '{ws_path}': "
                f"{(head_res.stderr or '').strip()}"
            )
        return head_res.stdout.strip()

    def _verify_committed_artifacts(
        self,
        ws_path: str,
        head_sha: str,
        change_dir_rel: str,
        expected_paths: set[str],
        manifest_files: tuple[str, ...],
        expected_hashes: dict[str, str],
    ) -> None:
        """Fail closed unless the committed tree matches the approved manifest exactly."""
        tree_res = subprocess.run(
            ["git", "ls-tree", "-r", "--name-only", head_sha, "--", change_dir_rel],
            cwd=ws_path,
            capture_output=True,
            text=True,
            check=False,
        )
        if tree_res.returncode != 0:
            raise UnsafeIntakeWorkspaceStateError(
                f"Committed tree inspection failed for commit '{head_sha}': "
                f"{tree_res.stderr.strip()}"
            )
        committed_paths = {p.strip() for p in tree_res.stdout.splitlines() if p.strip()}
        if committed_paths != expected_paths:
            raise UnsafeIntakeWorkspaceStateError(
                f"Committed tree for '{head_sha}' does not match the approved manifest: "
                f"expected={sorted(expected_paths)}, got={sorted(committed_paths)}."
            )

        for rel_file in manifest_files:
            blob_path = f"{head_sha}:{change_dir_rel}/{rel_file}"
            cat_res = subprocess.run(
                ["git", "cat-file", "blob", blob_path],
                cwd=ws_path,
                capture_output=True,
                text=False,
                check=False,
            )
            if cat_res.returncode != 0:
                raise UnsafeIntakeWorkspaceStateError(
                    f"Committed artifact '{blob_path}' is unreadable: "
                    f"{(cat_res.stderr or b'').decode(errors='replace').strip()}"
                )
            actual_hash = hashlib.sha256(cat_res.stdout).hexdigest()
            if actual_hash != expected_hashes[rel_file]:
                raise UnsafeIntakeWorkspaceStateError(
                    f"Committed artifact '{rel_file}' SHA-256 mismatch "
                    f"(expected {expected_hashes[rel_file]}, got {actual_hash})."
                )

        clean_res = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all"],
            cwd=ws_path,
            capture_output=True,
            text=True,
            check=False,
        )
        if clean_res.returncode != 0:
            raise UnsafeIntakeWorkspaceStateError(
                f"Post-commit git status failed in intake workspace '{ws_path}': "
                f"{clean_res.stderr.strip()}"
            )
        remaining = {_git_porcelain_path(line) for line in clean_res.stdout.splitlines()}
        remaining.discard(None)
        unexpected = remaining - {".minime_intake_workspace"}
        if unexpected:
            raise UnsafeIntakeWorkspaceStateError(
                f"Intake workspace '{ws_path}' is not clean after commit: unexpected={sorted(unexpected)}."
            )

    def _commit_intake_artifacts(
        self,
        ownership: IntakeWorkspaceOwnership,
        generated: Any,
        project: Project,
    ) -> str:
        ws_path = ownership.canonical_workspace_path
        if not os.path.exists(ws_path):
            raise UnsafeIntakeWorkspaceStateError(
                f"Intake workspace directory '{ws_path}' does not exist on disk."
            )

        manifest = self.openspec_generator.build_artifact_manifest(generated)
        expected_hashes = self._compute_artifact_sha256(generated)
        change_dir_rel = f"{project.openspec_path}/changes/{ownership.change_name}"
        expected_paths = {f"{change_dir_rel}/{rel}" for rel in manifest.files}
        allowed_rel_paths = expected_paths | {".minime_intake_workspace"}

        # Observe-before-repeat: adopt a prior commit only when HEAD matches the durable
        # fingerprint already recorded on the ownership record.
        if ownership.head_sha:
            head_probe = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=ws_path,
                capture_output=True,
                text=True,
                check=False,
            )
            if head_probe.returncode == 0 and head_probe.stdout.strip() == ownership.head_sha:
                self._verify_committed_artifacts(
                    ws_path, ownership.head_sha, change_dir_rel, expected_paths,
                    manifest.files, expected_hashes,
                )
                return ownership.head_sha

        # 1. git status must succeed; every changed path must be an approved manifest artifact.
        status_res = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all"],
            cwd=ws_path,
            capture_output=True,
            text=True,
            check=False,
        )
        if status_res.returncode != 0:
            raise UnsafeIntakeWorkspaceStateError(
                f"Git status failed in intake workspace '{ws_path}': {status_res.stderr.strip()}"
            )
        for line in status_res.stdout.splitlines():
            filepath = _git_porcelain_path(line)
            if not filepath:
                continue
            if filepath not in allowed_rel_paths:
                raise UnsafeIntakeWorkspaceStateError(
                    f"Unexpected file '{filepath}' in intake workspace '{ws_path}'. "
                    f"Only approved manifest artifacts may be committed."
                )

        # 2. Stage the authored change directory; fail closed on error.
        add_res = subprocess.run(
            ["git", "add", change_dir_rel],
            cwd=ws_path,
            capture_output=True,
            text=True,
            check=False,
        )
        if add_res.returncode != 0:
            raise UnsafeIntakeWorkspaceStateError(
                f"Git add failed for '{change_dir_rel}' in intake workspace '{ws_path}': "
                f"{add_res.stderr.strip()}"
            )

        # 3. The staged set must equal the approved manifest exactly.
        staged_res = subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            cwd=ws_path,
            capture_output=True,
            text=True,
            check=False,
        )
        if staged_res.returncode != 0:
            raise UnsafeIntakeWorkspaceStateError(
                f"Git staged-file inspection failed in intake workspace '{ws_path}': "
                f"{staged_res.stderr.strip()}"
            )
        staged_paths = {p.strip() for p in staged_res.stdout.splitlines() if p.strip()}
        if staged_paths != expected_paths:
            missing = sorted(expected_paths - staged_paths)
            unexpected = sorted(staged_paths - expected_paths)
            raise UnsafeIntakeWorkspaceStateError(
                f"Staged artifacts do not match the approved manifest in '{ws_path}': "
                f"missing={missing}, unexpected={unexpected}."
            )

        # 4. Commit; fail closed on any non-success (never substitute base_sha).
        commit_res = subprocess.run(
            [
                "git",
                "-c",
                "user.name=mini-me-bot",
                "-c",
                "user.email=bot@minime.internal",
                "commit",
                "-m",
                f"docs(openspec): author canonical artifacts for {ownership.change_name}",
            ],
            cwd=ws_path,
            capture_output=True,
            text=True,
            check=False,
        )
        if commit_res.returncode != 0:
            raise UnsafeIntakeWorkspaceStateError(
                f"Git commit failed in intake workspace '{ws_path}': "
                f"{(commit_res.stderr or '').strip()}"
            )

        # 5. Resolve HEAD authoritatively.
        head_sha = self._rev_parse_head(ws_path)

        # 6. Verify committed tree identity and SHA-256 manifest hashes.
        self._verify_committed_artifacts(
            ws_path, head_sha, change_dir_rel, expected_paths,
            manifest.files, expected_hashes,
        )

        ownership.head_sha = head_sha
        intake_repo = getattr(self.uow, "intake_workspace_ownerships", None)
        if intake_repo:
            intake_repo.save(ownership)
            self.uow.commit()

        return head_sha

    def _observe_remote_ref(
        self,
        managed_root: str,
        remote: str,
        ref: str,
    ) -> tuple[str | None, bool]:
        """Observe a remote ref authoritatively.

        Returns ``(sha_or_none, ok)``. ``ok=False`` means the remote could not be
        observed (transport failure / ambiguity); ``ok=True`` with ``None`` means the
        ref is genuinely absent.
        """
        try:
            ls_res = subprocess.run(
                ["git", "ls-remote", remote, ref],
                cwd=managed_root,
                capture_output=True,
                text=True,
                check=False,
            )
        except Exception as exc:
            logger.warning("git ls-remote raised for ref '%s': %s", ref, exc)
            return None, False

        if ls_res.returncode != 0:
            logger.warning("git ls-remote failed for ref '%s': %s", ref, ls_res.stderr.strip())
            return None, False

        lines = ls_res.stdout.splitlines()
        if not lines:
            return None, True
        for line in lines:
            parts = line.split()
            if len(parts) >= 2 and parts[1] == ref:
                return parts[0], True
        # Output present but the exact ref was not matched -> ambiguous.
        return None, False

    def _mark_publication_failed(self, ownership: IntakeWorkspaceOwnership) -> None:
        ownership.publication_state = IntakeWorkspacePublicationState.PUBLICATION_FAILED
        intake_repo = getattr(self.uow, "intake_workspace_ownerships", None)
        if intake_repo:
            intake_repo.save(ownership)
            self.uow.commit()

    def _publish_intake_artifacts_cas(
        self,
        ownership: IntakeWorkspaceOwnership,
        project: Project,
    ) -> str:
        binding_repo = getattr(self.uow, "project_managed_repository_bindings", None)
        binding = binding_repo.get_by_project_id(project.project_id) if binding_repo else None
        remote = binding.remote_name if binding else "origin"
        managed_root = binding.managed_repository_root if binding else str(self.project_root)
        published_ref = f"refs/minime/intake/{ownership.change_name}"

        # Never publish from base_sha; only a durable authored commit qualifies.
        head_sha = ownership.head_sha
        if not head_sha:
            self._mark_publication_failed(ownership)
            raise RuntimeError(
                f"PUBLICATION_FAILED: No candidate head SHA recorded for change "
                f"'{ownership.change_name}'; refusing to publish base_sha."
            )

        observed_old_sha, observe_ok = self._observe_remote_ref(managed_root, remote, published_ref)
        if not observe_ok:
            self._mark_publication_failed(ownership)
            raise RuntimeError(
                f"PUBLICATION_TRANSPORT_FAILURE: Could not authoritatively observe remote ref "
                f"'{published_ref}'; refusing to publish without remote truth."
            )

        push_needed = False
        push_cmd: list[str] | None = None

        if ownership.published_sha is None:
            # Initial publication enforces an atomic expected-old-ref condition: the
            # remote ref must be absent before we create it.
            if observed_old_sha is not None:
                self._mark_publication_failed(ownership)
                raise RuntimeError(
                    f"REF_CAS_MISMATCH: Conflicting publication ref '{published_ref}' already "
                    f"exists on remote at SHA '{observed_old_sha}' (expected absent)."
                )
            if observed_old_sha == head_sha:
                push_needed = False
            else:
                push_needed = True
                push_cmd = ["git", "push", remote, f"{head_sha}:{published_ref}"]
        else:
            # Subsequent publication uses an atomic exact-SHA CAS lease.
            if observed_old_sha != ownership.published_sha:
                self._mark_publication_failed(ownership)
                raise RuntimeError(
                    f"REF_CAS_MISMATCH: Remote ref '{published_ref}' current SHA '{observed_old_sha}' "
                    f"does not match expected published_sha '{ownership.published_sha}'."
                )
            if observed_old_sha == head_sha:
                push_needed = False
            else:
                push_needed = True
                push_cmd = [
                    "git",
                    "push",
                    f"--force-with-lease={published_ref}:{ownership.published_sha}",
                    remote,
                    f"{head_sha}:{published_ref}",
                ]

        if push_needed:
            ownership.publication_state = IntakeWorkspacePublicationState.PUBLISHING
            if getattr(self.uow, "intake_workspace_ownerships", None):
                self.uow.intake_workspace_ownerships.save(ownership)
                self.uow.commit()

            push_res = subprocess.run(
                push_cmd,
                cwd=managed_root,
                capture_output=True,
                text=True,
                check=False,
            )
            if push_res.returncode != 0:
                err_msg = push_res.stderr or ""
                is_unreachable_remote = any(
                    term in err_msg.lower()
                    for term in ["repository not found", "could not resolve host", "connection refused", "does not appear to be a git repository", "cannot access"]
                )
                if is_unreachable_remote and remote == "local":
                    # Local-only binding fallback: record a local ref for test/offline
                    # environments. The authoritative final observation below still gates
                    # PUBLISHED, so this can never fabricate a production publication.
                    logger.warning(
                        "Remote unreachable for git push in local environment; updating local ref '%s'",
                        published_ref,
                    )
                    subprocess.run(
                        ["git", "update-ref", published_ref, head_sha],
                        cwd=managed_root,
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                else:
                    self._mark_publication_failed(ownership)
                    raise RuntimeError(
                        f"REF_CAS_MISMATCH: Git push failed for '{published_ref}': {err_msg}"
                    )

        # Authoritative post-publication observation MUST return exactly head_sha.
        final_sha, final_ok = self._observe_remote_ref(managed_root, remote, published_ref)
        if not final_ok or final_sha != head_sha:
            self._mark_publication_failed(ownership)
            raise RuntimeError(
                f"PUBLICATION_AMBIGUOUS: Post-publication observation of '{published_ref}' "
                f"returned '{final_sha}' (ok={final_ok}); expected exact SHA '{head_sha}'."
            )

        ownership.publication_state = IntakeWorkspacePublicationState.PUBLISHED
        ownership.published_ref = published_ref
        ownership.published_sha = head_sha
        if getattr(self.uow, "intake_workspace_ownerships", None):
            self.uow.intake_workspace_ownerships.save(ownership)
            self.uow.commit()

        return head_sha

    def cleanup_intake_workspace(
        self,
        workspace_id: str,
        claim_context: RecoveryClaimContext | None = None,
    ) -> bool:
        intake_repo = getattr(self.uow, "intake_workspace_ownerships", None)
        if not intake_repo:
            return False

        ownership = intake_repo.get_by_id(workspace_id)
        if not ownership:
            return False

        if ownership.creation_state not in (
            IntakeWorkspaceCreationState.RELEASED_PENDING_CLEANUP,
            IntakeWorkspaceCreationState.FAILED_PENDING_CLEANUP,
        ):
            raise ManagedWorkspaceGuardDeniedError(
                f"Cleanup unauthorized: creation_state '{ownership.creation_state.value}' "
                f"is neither RELEASED_PENDING_CLEANUP nor FAILED_PENDING_CLEANUP."
            )

        target_path = os.path.realpath(ownership.canonical_workspace_path)
        if target_path != os.path.realpath(ownership.canonical_workspace_path):
            raise ManagedWorkspaceGuardDeniedError("Canonical path mismatch.")

        binding_repo = getattr(self.uow, "project_managed_repository_bindings", None)
        binding = binding_repo.get_by_project_id(ownership.project_id) if binding_repo else None
        managed_root = binding.managed_repository_root if binding else str(self.project_root)

        try:
            res = subprocess.run(
                ["git", "worktree", "list", "--porcelain"],
                cwd=managed_root,
                capture_output=True,
                text=True,
                check=False,
            )
            worktree_paths = [
                os.path.realpath(line.split()[1])
                for line in res.stdout.splitlines()
                if line.startswith("worktree ")
            ]
            if target_path not in worktree_paths:
                logger.warning("Target path %s not found in git worktree list", target_path)
        except Exception as exc:
            logger.warning("Git worktree list check failed: %s", exc)

        marker_path = os.path.join(target_path, ".minime_intake_workspace")
        if not os.path.exists(marker_path):
            raise ManagedWorkspaceGuardDeniedError(
                f"Root marker file missing at '{marker_path}'."
            )

        try:
            subprocess.run(
                ["git", "worktree", "remove", "--force", target_path],
                cwd=managed_root,
                capture_output=True,
                text=True,
                check=False,
            )
            subprocess.run(
                ["git", "branch", "-D", f"intake/{ownership.change_name}"],
                cwd=managed_root,
                capture_output=True,
                text=True,
                check=False,
            )
        except Exception as exc:
            logger.warning("Error running git worktree remove: %s", exc)

        if os.path.exists(target_path):
            shutil.rmtree(target_path, ignore_errors=True)

        target_state = (
            IntakeWorkspaceCreationState.RELEASED_CLEANED
            if ownership.creation_state == IntakeWorkspaceCreationState.RELEASED_PENDING_CLEANUP
            else IntakeWorkspaceCreationState.FAILED_CLEANED
        )
        ownership.creation_state = target_state
        ownership.released_at = utc_now()
        intake_repo.save(ownership)
        self.uow.commit()
        return True

    def _legacy_artifacts_match_manifest(
        self,
        item_dir: Path,
        manifest_files: tuple[str, ...],
        expected_hashes: dict[str, str],
    ) -> bool:
        """Verify legacy on-disk artifacts exactly match the canonical manifest and hashes.

        Only the individually approved OpenSpec artifacts are permitted; any missing,
        extra, or hash-mismatching file makes the directory non-provable.
        """
        if not item_dir.is_dir():
            return False
        allowed = set(manifest_files)
        for rel_file in allowed:
            src = item_dir / rel_file
            if not src.is_file():
                return False
            try:
                actual = hashlib.sha256(src.read_bytes()).hexdigest()
            except OSError:
                return False
            if actual != expected_hashes.get(rel_file):
                return False
        # Reject any file not in the approved manifest (no arbitrary legacy files).
        for f in item_dir.rglob("*"):
            if not f.is_file():
                continue
            rel = f.relative_to(item_dir).as_posix()
            if rel not in allowed:
                return False
        return True

    def reconcile_legacy_unowned_intake_artifacts(
        self,
        project_id: str,
    ) -> dict[str, Any]:
        binding_repo = getattr(self.uow, "project_managed_repository_bindings", None)
        binding = binding_repo.get_by_project_id(project_id) if binding_repo else None
        if not binding or not binding.managed_repository_root:
            return {"provable_adopted": [], "ambiguous_needs_human": []}

        managed_root = Path(binding.managed_repository_root).resolve()
        changes_dir = managed_root / "openspec" / "changes"
        if not changes_dir.exists() or not changes_dir.is_dir():
            return {"provable_adopted": [], "ambiguous_needs_human": []}

        intake_repo = getattr(self.uow, "intake_workspace_ownerships", None)
        active_ownerships = intake_repo.list_by_project(project_id) if intake_repo else []
        owned_change_names = {ow.change_name for ow in active_ownerships}

        # Historical INTAKE sagas provide the checkpoint/identity evidence required to
        # prove legacy artifacts were authored by a prior durable run.
        saga_repo = getattr(self.uow, "durable_sagas", None)
        historical_sagas = (
            saga_repo.list_by_project(project_id, saga_type=SagaType.INTAKE)
            if saga_repo and hasattr(saga_repo, "list_by_project")
            else []
        )
        sagas_by_change: dict[str, Any] = {}
        sagas_by_key: dict[str, Any] = {}
        for saga in historical_sagas:
            if saga.change_name:
                sagas_by_change[saga.change_name] = saga
            sagas_by_key[saga.work_item_key] = saga

        provable: list[str] = []
        ambiguous: list[str] = []

        for item_dir in sorted(changes_dir.iterdir()):
            if not item_dir.is_dir() or item_dir.name in ("archive", ".") or item_dir.name.startswith("."):
                continue

            cname = item_dir.name
            if cname in owned_change_names:
                continue

            item = self.uow.backlog_items.get_by_project_and_key(project_id, cname)
            project = self.uow.projects.get_by_id(project_id)

            # Authoritative durable evidence (fail-closed; file existence alone is never
            # sufficient to prove legacy attribution).
            binding_ev = (
                self.uow.bindings.get_by_project_and_change(project_id, cname)
                if getattr(self.uow.bindings, "get_by_project_and_change", None)
                else None
            )
            saga_ev = sagas_by_change.get(cname) or (sagas_by_key.get(item.item_key) if item else None)
            actions = []
            if saga_ev and getattr(self.uow.orchestration_external_actions, "list_by_saga", None):
                actions = self.uow.orchestration_external_actions.list_by_saga(saga_ev.id)

            generated = (
                self.openspec_generator.generate_from_backlog_item(item, project_name=project.display_name)
                if item else None
            )
            manifest = self.openspec_generator.build_artifact_manifest(generated) if generated else None
            manifest_matches = False
            if manifest and generated and generated.is_complete:
                expected_hashes = self._compute_artifact_sha256(generated)
                manifest_matches = self._legacy_artifacts_match_manifest(
                    item_dir, manifest.files, expected_hashes
                )

            # Historical saga must have reached the authored checkpoint, and there must
            # be corroborating external action + binding evidence.
            binding_ok = bool(
                binding_ev and binding_ev.is_valid and binding_ev.github_issue_number
            )
            saga_ok = bool(
                saga_ev
                and saga_ev.current_phase
                and _has_passed_intake_phase(saga_ev.current_phase, "OPENSPEC_AUTHORED")
            )
            identity_ok = bool(
                item is not None
                and saga_ev is not None
                and item.project_id == project_id
                and item.openspec_change_name == cname
                and item.item_key == saga_ev.work_item_key
            )

            is_provable = bool(
                item is not None
                and project is not None
                and binding_ok
                and saga_ok
                and identity_ok
                and bool(actions)
                and manifest_matches
            )

            if is_provable:
                try:
                    workspace = self._reserve_intake_workspace(project, item, saga_ev)
                    self._activate_intake_workspace(workspace, project)

                    ws_change_dir = (
                        Path(workspace.canonical_workspace_path)
                        / "openspec"
                        / "changes"
                        / cname
                    )
                    ws_change_dir.mkdir(parents=True, exist_ok=True)
                    # Copy ONLY the individually proven, allowed OpenSpec artifacts.
                    for rel_file in manifest.files:
                        src = item_dir / rel_file
                        dest = ws_change_dir / rel_file
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(src, dest)

                    self._commit_intake_artifacts(workspace, generated, project)
                    self._publish_intake_artifacts_cas(workspace, project)
                    provable.append(cname)
                except Exception as exc:
                    logger.warning(
                        "Legacy intake artifact adoption failed for '%s': %s", cname, exc
                    )
                    ambiguous.append(cname)
            else:
                if item and item.status != WorkItemStatus.NEEDS_HUMAN:
                    try:
                        authority = LifecycleTransitionAuthority(self.uow)
                        authority.transition_backlog_item(
                            project_id=project_id,
                            item_key=item.item_key,
                            expected_from_state=item.status,
                            to_state=WorkItemStatus.NEEDS_HUMAN,
                            reason_code="legacy_unowned_intake_artifacts_detected",
                            actor="reconciliation_authority",
                        )
                    except Exception as exc:
                        logger.warning(
                            "Failed to transition legacy item '%s' to NEEDS_HUMAN: %s", cname, exc
                        )
                ambiguous.append(cname)

        return {"provable_adopted": provable, "ambiguous_needs_human": ambiguous}
