"""Work Intake Service for managing backlog items, canonical artifact generation, DoR, and admission."""

from __future__ import annotations

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
    OrchestrationStage,
    OrchestrationStopOutcome,
    QueuePriority,
    ReadinessState,
    SagaStatus,
    SagaType,
    WorkItemStatus,
)
from minime.domain.interfaces import PersistenceUnitOfWork
from minime.domain.models import (
    BacklogItem,
    Change,
    Event,
    HumanAnswerRecord,
    ProjectBinding,
    RecoveryClaimContext,
    WorkItemAnswerInput,
    WorkItemCreateInput,
    WorkItemPrepareResult,
    WorkItemUpdateInput,
    WorkQueueItem,
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
    "OPENSPEC_AUTHORED",
    "ISSUE_BOUND",
    "PROJECT_ITEM_BOUND",
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
                        self.project_root / project.openspec_path / "changes" / change_name
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
                    )
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
            archive_dir = Path(self.project_root) / project.openspec_path / "changes" / "archive"
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
                projected_item = item.model_copy(
                    update={
                        "status": new_status,
                        "run_id": new_run_id,
                    }
                )
                reconciled_items.append(projected_item)
            else:
                reconciled_items.append(item)

        return reconciled_items

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

            # ROADMAP state is a pure projection.  Preserve the persisted lifecycle
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
                if it.status
                in (
                    WorkItemStatus.BACKLOG,
                    WorkItemStatus.CONTEXT_CHECK,
                    WorkItemStatus.PREPARING,
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
