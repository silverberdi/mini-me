"""Work Intake Service for managing backlog items, canonical artifact generation, DoR, and admission."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from minime.adapters.github import GitHubAdapter
from minime.adapters.openspec import OpenSpecAdapter
from minime.domain.enums import (
    ChangeStatus,
    EventType,
    ReadinessState,
    WorkItemStatus,
)
from minime.domain.interfaces import PersistenceUnitOfWork
from minime.domain.models import (
    BacklogItem,
    Change,
    Event,
    HumanAnswerRecord,
    ProjectBinding,
    WorkItemAnswerInput,
    WorkItemCreateInput,
    WorkItemPrepareResult,
    WorkItemUpdateInput,
    WorkQueueItem,
    utc_now,
)
from minime.logging import get_logger, set_correlation_context
from minime.services.openspec_generator import OpenSpecGenerator, slugify
from minime.services.readiness_service import ReadinessService

logger = get_logger("services.intake")


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
            project_root=self.project_root
        )

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
        self.uow.commit()

        logger.info("Created backlog item '%s' for project '%s'", item_key, project_id)
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
                "status": WorkItemStatus.PREPARING,
                "human_questions": [],
                "updated_at": now,
            }
        )
        self.uow.backlog_items.save(updated)

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

        # Re-prepare after answering
        prep_result = self.prepare_work_item(project_id, item_key, operator_email=operator_email)
        return prep_result.item

    def prepare_work_item(
        self,
        project_id: str,
        item_key: str,
        operator_email: str = "operator",
    ) -> WorkItemPrepareResult:
        """Prepare canonical execution artifacts (GitHub Issue, Project item, OpenSpec change)."""
        set_correlation_context(project_id=project_id, operation_id="prepare_work_item")

        project = self.uow.projects.get_by_id(project_id)
        if not project:
            raise ValueError(f"Project '{project_id}' not found.")

        item = self.uow.backlog_items.get_by_project_and_key(project_id, item_key)
        if not item:
            raise ValueError(f"Work item '{item_key}' not found in project '{project_id}'.")

        now = utc_now()
        change_name = item.openspec_change_name or slugify(item.item_key)

        # 1. Generate OpenSpec artifacts
        generated = self.openspec_generator.generate_from_backlog_item(
            item, project_name=project.display_name
        )

        # If incomplete / ambiguous -> set NEEDS_HUMAN
        if not generated.is_complete:
            updated_item = item.model_copy(
                update={
                    "status": WorkItemStatus.NEEDS_HUMAN,
                    "readiness_state": ReadinessState.NOT_READY,
                    "unmet_readiness_reasons": generated.missing_reasons,
                    "human_questions": generated.human_questions,
                    "updated_at": now,
                }
            )
            self.uow.backlog_items.save(updated_item)
            self.uow.commit()

            return WorkItemPrepareResult(
                item=updated_item,
                openspec_change_name=change_name,
                readiness_state=ReadinessState.NOT_READY,
                unmet_readiness_reasons=generated.missing_reasons,
                human_questions=generated.human_questions,
            )

        # 2. Write OpenSpec files to disk
        self.openspec_generator.write_change_to_disk(
            project.openspec_path, generated, overwrite=True
        )

        # Save/update Change entity in DB
        change_record = self.uow.changes.get_by_name(project_id, change_name)
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

        # 3. Create or sync GitHub Issue
        issue_number = item.github_issue_number
        issue_url = item.github_issue_url
        if not issue_number:
            issue_res = self.github_adapter.create_issue(
                repository=project.repository,
                title=f"[{change_name}] {item.title}",
                body=f"## Work Item: {item.title}\n\n{item.description}\n\n**OpenSpec Change:** `{change_name}`",
                labels=[f"priority:{item.priority.value.lower()}"],
            )
            issue_number = issue_res.get("number")
            issue_url = issue_res.get("html_url")

        # 4. Sync GitHub Project v2 item if configured
        project_item_id = item.github_project_item_id
        if not project_item_id and project.github_project_number and issue_url:
            project_item_id = self.github_adapter.add_issue_to_project(
                project_number=project.github_project_number,
                owner=project.github_project_owner or "silverberdi",
                issue_url=issue_url,
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
        readiness_eval = self.readiness_service.evaluate_change_readiness(
            project_id=project_id,
            change_name=change_name,
            project_root=str(self.project_root),
            github_repo=project.repository,
            github_issue=issue_number,
        )

        final_status = WorkItemStatus.READY if readiness_eval.is_ready else WorkItemStatus.PREPARING
        final_readiness = readiness_eval.status

        # 7. Update BacklogItem state
        updated_item = item.model_copy(
            update={
                "openspec_change_name": change_name,
                "github_issue_number": issue_number,
                "github_issue_url": issue_url,
                "github_project_item_id": project_item_id,
                "status": final_status,
                "readiness_state": final_readiness,
                "unmet_readiness_reasons": readiness_eval.unmet_reasons,
                "human_questions": [],
                "updated_at": now,
            }
        )
        self.uow.backlog_items.save(updated_item)

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
            # Try re-preparing once in case DoR criteria became satisfied
            prep_res = self.prepare_work_item(project_id, item_key, operator_email=operator_email)
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
                if item.status != WorkItemStatus.RUNNING or item.run_id != run.run_id:
                    updated_item = item.model_copy(
                        update={
                            "status": WorkItemStatus.RUNNING,
                            "run_id": run.run_id,
                            "updated_at": utc_now(),
                        }
                    )
                    self.uow.backlog_items.save(updated_item)
                    self.uow.commit()
                    return updated_item
                return item

        # 3. Admit into scheduler
        from minime.services.orchestration_service import OrchestrationService

        orch_service = OrchestrationService(
            uow=self.uow,
            project_root=self.project_root,
            github_adapter=self.github_adapter,
            openspec_adapter=self.openspec_adapter,
        )
        admission = orch_service.admit_change(project_id=project_id, change_name=change_name)
        if not admission.admitted or not admission.run:
            raise ValueError(f"Work item admission failed: {admission.refusal_reason}")
        run = admission.run

        now = utc_now()
        updated_item = item.model_copy(
            update={
                "status": WorkItemStatus.RUNNING,
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

        self.uow.backlog_items.delete(item.item_id)

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
