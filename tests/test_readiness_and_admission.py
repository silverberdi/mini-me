"""Unit and integration tests for 021.5 Definition of Ready & Admission."""

from __future__ import annotations

from pathlib import Path

from tests.conftest import InMemoryPersistenceUnitOfWork

from minime.domain.enums import WorkItemPriority, WorkItemStatus
from minime.domain.models import BacklogItem, Project, WorkItemAnswerInput
from minime.services.intake_service import IntakeService


def test_needs_human_question_answering_flow(
    in_memory_uow: InMemoryPersistenceUnitOfWork, tmp_path: Path
) -> None:
    repo_dir = tmp_path / "app-repo"
    repo_dir.mkdir()

    project = Project(
        project_id="app-proj",
        display_name="App Project",
        repository="test-owner/app-repo",
        base_branch="main",
    )
    in_memory_uow.projects.save(project)

    # Underspecified item without description or acceptance criteria
    item = BacklogItem(
        project_id="app-proj",
        item_key="024-vague-feature",
        title="Improve performance",
        priority=WorkItemPriority.NORMAL,
        status=WorkItemStatus.BACKLOG,
        description="",
        acceptance_criteria=[],
    )
    in_memory_uow.backlog_items.save(item)

    from tests.conftest import ReadinessGitHubStub

    service = IntakeService(
        in_memory_uow, project_root=repo_dir, github_adapter=ReadinessGitHubStub()
    )

    # Preparing underspecified item sets NEEDS_HUMAN
    res = service.prepare_work_item(
        "app-proj", "024-vague-feature", operator_email="operator@example.com"
    )
    assert res.item.status == WorkItemStatus.NEEDS_HUMAN
    assert len(res.human_questions) > 0

    # Operator answers question with clarification in PWA
    answered = service.answer_human_question(
        "app-proj",
        "024-vague-feature",
        WorkItemAnswerInput(
            question="What is the functional scope?",
            answer="Optimize database queries and add index for fast lookups.",
        ),
        operator_email="operator@example.com",
    )

    assert answered.status == WorkItemStatus.READY
    assert len(answered.human_questions) == 0


def test_start_work_item_and_duplicate_suppression(
    in_memory_uow: InMemoryPersistenceUnitOfWork, tmp_path: Path
) -> None:
    from tests.conftest import ReadinessGitHubStub

    repo_dir = tmp_path / "app-repo"
    repo_dir.mkdir()

    project = Project(
        project_id="app-proj",
        display_name="App Project",
        repository="test-owner/app-repo",
        base_branch="main",
    )
    in_memory_uow.projects.save(project)

    item = BacklogItem(
        project_id="app-proj",
        item_key="025-ready-task",
        title="Implement audit logging",
        priority=WorkItemPriority.NORMAL,
        status=WorkItemStatus.BACKLOG,
        description="Add audit log entry on all operator mutations.",
        acceptance_criteria=["Logs contain operator, timestamp, and action"],
    )
    in_memory_uow.backlog_items.save(item)

    service = IntakeService(
        in_memory_uow, project_root=repo_dir, github_adapter=ReadinessGitHubStub()
    )

    # Prepare to reach READY
    service.prepare_work_item("app-proj", "025-ready-task", operator_email="operator@example.com")

    # Start execution
    start1 = service.start_work_item(
        "app-proj", "025-ready-task", operator_email="operator@example.com"
    )
    assert start1.is_admitted is True
    assert start1.run_id is not None

    # Duplicate start request returns existing active run
    start2 = service.start_work_item(
        "app-proj", "025-ready-task", operator_email="operator@example.com"
    )
    assert start2.run_id == start1.run_id
    assert start2.is_admitted is True
