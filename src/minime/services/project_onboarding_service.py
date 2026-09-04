"""Project Onboarding Service for registration, binding validation, and auto-discovery."""

from __future__ import annotations

from pathlib import Path

from minime.adapters.github import GitHubAdapter, GitHubAuthorizationError, GitHubRemoteError
from minime.domain.enums import EventType, ProjectOnboardingStatus, ProjectStatus
from minime.domain.interfaces import PersistenceUnitOfWork
from minime.domain.models import (
    Event,
    Project,
    ProjectOnboardingInput,
    ProjectOnboardingResult,
    utc_now,
)
from minime.logging import get_logger, set_correlation_context
from minime.services.context_discovery_service import ContextDiscoveryService
from minime.services.project_service import (
    normalize_repository_identity,
    validate_complementary_roles,
)

logger = get_logger("services.project_onboarding")


class ProjectOnboardingService:
    """Manages the onboarding flow for external projects."""

    def __init__(
        self,
        uow: PersistenceUnitOfWork,
        project_root: str | Path = ".",
        github_adapter: GitHubAdapter | None = None,
        context_discovery_service: ContextDiscoveryService | None = None,
    ):
        self.uow = uow
        self.project_root = Path(project_root).resolve()
        self.github_adapter = github_adapter or GitHubAdapter()
        self.context_discovery_service = context_discovery_service or ContextDiscoveryService(
            uow, project_root=self.project_root
        )

    def onboard_project(
        self,
        input_data: ProjectOnboardingInput,
        operator_email: str = "operator",
    ) -> ProjectOnboardingResult:
        """Onboard a new project with auto-discovery, conflict detection, and fail-closed validation."""
        set_correlation_context(
            project_id=input_data.project_id,
            operation_id="onboard_project",
        )

        project_id = input_data.project_id.strip()
        if not project_id:
            raise ValueError("project_id is required and cannot be empty.")

        display_name = input_data.display_name.strip() or project_id
        raw_repo = input_data.repository.strip()
        if not raw_repo:
            raise ValueError("repository identifier is required and cannot be empty.")

        # 1. Normalize repository identity
        try:
            norm_repo = normalize_repository_identity(raw_repo)
        except ValueError as exc:
            raise ValueError(f"Invalid repository identity '{raw_repo}': {exc}") from exc

        # 2. Duplicate detection
        existing_project = self.uow.projects.get_by_id(project_id)
        if existing_project:
            raise ValueError(
                f"Project with ID '{project_id}' is already registered. Identifiers are immutable."
            )

        # Check for existing repository binding conflict
        all_projects = self.uow.projects.list_all()
        for p in all_projects:
            if p.repository.lower() == norm_repo.lower():
                raise ValueError(
                    f"Repository '{norm_repo}' is already bound to project '{p.project_id}'."
                )

        # 3. Validate complementary agent roles
        validate_complementary_roles(input_data.implementer, input_data.reviewer)

        # 4. Probe repository accessibility via GitHub App
        onboarding_status = ProjectOnboardingStatus.READY_FOR_WORK
        reasons: list[str] = []

        is_accessible = True
        try:
            valid, mismatch_reason = self.github_adapter.verify_repository(norm_repo)
            if not valid:
                is_accessible = False
                onboarding_status = ProjectOnboardingStatus.BLOCKED
                reasons.append(mismatch_reason or "Repository access verification failed.")
        except GitHubAuthorizationError as exc:
            is_accessible = False
            onboarding_status = ProjectOnboardingStatus.BLOCKED
            reasons.append(f"GitHub App authorization error: {exc}")
        except GitHubRemoteError as exc:
            # Remote transient issue
            reasons.append(f"GitHub API was unobservable during repository verification: {exc}")
        except Exception as exc:
            logger.debug(f"Local verification mode or unobservable: {exc}")

        # If repo is blocked due to hard access denial, fail closed
        if not is_accessible and onboarding_status == ProjectOnboardingStatus.BLOCKED:
            raise ValueError(
                f"Project onboarding failed closed on repository verification: {'; '.join(reasons)}"
            )

        # 5. Check local context directory presence
        root = self.project_root
        openspec_dir = root / input_data.openspec_path
        if not openspec_dir.exists():
            reasons.append(f"OpenSpec path '{input_data.openspec_path}' does not exist on disk.")
            if onboarding_status != ProjectOnboardingStatus.BLOCKED:
                onboarding_status = ProjectOnboardingStatus.CONTEXT_INCOMPLETE

        now = utc_now()
        project = Project(
            project_id=project_id,
            display_name=display_name,
            repository=norm_repo,
            base_branch=input_data.base_branch,
            openspec_path=input_data.openspec_path,
            implementer=input_data.implementer,
            reviewer=input_data.reviewer,
            checks=input_data.checks,
            context_sources=input_data.context_sources,
            roadmap_path=input_data.roadmap_path,
            backlog_path=input_data.backlog_path,
            github_project_number=input_data.github_project_number,
            github_project_owner=input_data.github_project_owner,
            onboarding_status=onboarding_status,
            onboarding_reasons=reasons,
            status=ProjectStatus.ACTIVE,
            created_at=now,
            updated_at=now,
        )

        # 6. Save project entity and audit event
        self.uow.projects.save(project)

        event = Event(
            event_type=EventType.PROJECT_ONBOARDED,
            project_id=project_id,
            payload={
                "project_id": project_id,
                "display_name": display_name,
                "repository": norm_repo,
                "onboarding_status": onboarding_status.value,
                "operator_email": operator_email,
                "reasons": reasons,
            },
            timestamp=now,
        )
        self.uow.events.save(event)
        self.uow.commit()

        # 7. Trigger initial context and backlog discovery
        discovery_report = None
        try:
            discovery_report = self.context_discovery_service.discover_context(project_id)
        except Exception as exc:
            logger.warning(
                f"Initial context discovery encountered an error for '{project_id}': {exc}"
            )

        return ProjectOnboardingResult(
            project=project,
            status=onboarding_status,
            reasons=reasons,
            discovered_context=discovery_report,
        )
