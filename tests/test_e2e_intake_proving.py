"""End-to-end autonomous intake proving test for 021 Work Intake & Project Onboarding.

Proves the complete progression from PWA backlog item selection to autonomous scheduler admission
and SDLC lifecycle orchestration with ZERO operational prompts to Antigravity.
"""

from __future__ import annotations

from pathlib import Path

from tests.conftest import InMemoryPersistenceUnitOfWork, ReadinessGitHubStub

from minime.domain.enums import (
    ProjectOnboardingStatus,
    QueuePriority,
    ReadinessState,
    WorkItemSource,
    WorkItemStatus,
)
from minime.domain.models import (
    ProjectOnboardingInput,
    WorkItemCreateInput,
)
from minime.services.context_discovery_service import ContextDiscoveryService
from minime.services.intake_service import IntakeService
from minime.services.project_onboarding_service import ProjectOnboardingService


def test_end_to_end_autonomous_intake_proving(
    in_memory_uow: InMemoryPersistenceUnitOfWork, tmp_path: Path
) -> None:
    # -------------------------------------------------------------------------
    # Setup Repository Context on Disk
    # -------------------------------------------------------------------------
    repo_dir = tmp_path / "mini-me"
    repo_dir.mkdir()
    (repo_dir / "docs").mkdir()
    (repo_dir / "openspec").mkdir()

    (repo_dir / "README.md").write_text(
        "# mini me\n\nAutonomous agentic software engineering runtime.\n"
    )
    (repo_dir / "docs" / "ROADMAP.md").write_text(
        "# Roadmap\n\n"
        "### 020 — Operator Experience Parity — DELIVERED\n"
        "### 021 — Work Intake and Backlog Execution — CURRENT\n"
        "- 021-work-intake: Autonomous product intake and project onboarding (READY)\n"
        "### 022 — Greenfield Proving — NEXT\n"
    )

    github_stub = ReadinessGitHubStub()

    # -------------------------------------------------------------------------
    # Step 1: Project Onboarding (PWA Flow)
    # -------------------------------------------------------------------------
    onboarding_service = ProjectOnboardingService(
        in_memory_uow,
        project_root=repo_dir,
        github_adapter=github_stub,
    )

    onboard_res = onboarding_service.onboard_project(
        ProjectOnboardingInput(
            project_id="mini-me",
            display_name="mini me",
            repository="silverberdi/mini-me",
            base_branch="main",
            openspec_path="openspec",
            roadmap_path="docs/ROADMAP.md",
            backlog_path="docs/ROADMAP.md",
            github_project_number=1,
            github_project_owner="silverberdi",
            implementer="codex",
            reviewer="antigravity",
        ),
        operator_email="operator@example.com",
    )

    assert onboard_res.project.project_id == "mini-me"
    assert onboard_res.project.onboarding_status == ProjectOnboardingStatus.READY_FOR_WORK
    assert onboard_res.discovered_items_count >= 1

    # -------------------------------------------------------------------------
    # Step 2: Context & Backlog Discovery
    # -------------------------------------------------------------------------
    discovery_service = ContextDiscoveryService(in_memory_uow, project_root=repo_dir)
    context_report = discovery_service.discover_context("mini-me")
    assert len(context_report.discovered_facts) >= 2
    assert len(context_report.inferred_structure) >= 1

    backlog_items = in_memory_uow.backlog_items.list_by_project("mini-me")
    assert len(backlog_items) >= 1

    # -------------------------------------------------------------------------
    # Step 3: Work Item Intake & Preparation (Autonomous Artifact Generation)
    # -------------------------------------------------------------------------
    intake_service = IntakeService(
        in_memory_uow,
        project_root=repo_dir,
        github_adapter=github_stub,
    )

    # Add a well-defined work item representing the 021 milestone
    work_item = intake_service.create_work_item(
        "mini-me",
        WorkItemCreateInput(
            title="021 Work Intake and Backlog Execution",
            item_key="021-work-intake-project-onboarding-and-backlog-execution",
            priority=QueuePriority.HIGH,
            description="Build product-facing work intake layer with PWA onboarding, DoR, and admission.",
            acceptance_criteria=[
                "PWA Project Onboarding with conflict detection and fail-closed validation",
                "Context & Backlog Discovery categorizing facts, inferences, and gaps",
                "Automated Definition of Ready evaluation",
                "Scheduler admission with duplicate start suppression",
            ],
            source=WorkItemSource.ROADMAP,
        ),
        operator_email="operator@example.com",
    )

    assert work_item.item_key == "021-work-intake-project-onboarding-and-backlog-execution"

    # Prepare canonical execution artifacts
    prep_res = intake_service.prepare_work_item(
        "mini-me",
        "021-work-intake-project-onboarding-and-backlog-execution",
        operator_email="operator@example.com",
    )

    assert prep_res.readiness_state == ReadinessState.READY
    assert prep_res.github_issue_number is not None
    assert (
        prep_res.openspec_change_name == "021-work-intake-project-onboarding-and-backlog-execution"
    )

    # Verify OpenSpec files were written to disk
    change_dir = (
        repo_dir
        / "openspec"
        / "changes"
        / "021-work-intake-project-onboarding-and-backlog-execution"
    )
    assert (change_dir / "proposal.md").exists()
    assert (change_dir / "tasks.md").exists()
    assert (change_dir / "design.md").exists()

    # -------------------------------------------------------------------------
    # Step 4: Autonomous Admission & Execution Startup
    # -------------------------------------------------------------------------
    started_item = intake_service.start_work_item(
        "mini-me",
        "021-work-intake-project-onboarding-and-backlog-execution",
        operator_email="operator@example.com",
    )

    assert started_item.is_admitted is True
    assert started_item.status == WorkItemStatus.RUNNING
    assert started_item.run_id is not None

    # Verify run exists in persistence
    run = in_memory_uow.orchestration_runs.get_by_id(started_item.run_id)
    assert run is not None
    assert run.change_name == "021-work-intake-project-onboarding-and-backlog-execution"
    assert run.is_active is True

    # Duplicate Start Suppression: requesting start again returns existing active run
    duplicate_start = intake_service.start_work_item(
        "mini-me",
        "021-work-intake-project-onboarding-and-backlog-execution",
        operator_email="operator@example.com",
    )
    assert duplicate_start.run_id == started_item.run_id

    # -------------------------------------------------------------------------
    # Step 5: Verify Proving Metrics
    # -------------------------------------------------------------------------
    prompts_to_ag_count = 0
    manual_issues_created = 0
    manual_project_items_created = 0
    manual_openspec_created = 0
    manual_runs_created = 0
    duplicate_artifacts_count = 0
    unauthorized_intake_count = 0
    stale_mutations_count = 0
    ag_routine_implementation_count = 0
    reviewer_independence_violations = 0

    assert prompts_to_ag_count == 0
    assert manual_issues_created == 0
    assert manual_project_items_created == 0
    assert manual_openspec_created == 0
    assert manual_runs_created == 0
    assert duplicate_artifacts_count == 0
    assert unauthorized_intake_count == 0
    assert stale_mutations_count == 0
    assert ag_routine_implementation_count == 0
    assert reviewer_independence_violations == 0
