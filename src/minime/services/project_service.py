"""Project registry and repository binding service."""

from __future__ import annotations

import re
from typing import Any

from minime.domain.enums import EventType, ProjectStatus
from minime.domain.interfaces import (
    PersistenceUnitOfWork,
)
from minime.domain.models import Event, Project, utc_now
from minime.logging import get_logger, set_correlation_context

logger = get_logger("services.project")


def normalize_repository_identity(repo_input: str) -> str:
    """Normalize repository URLs/names into canonical 'owner/repo' or trimmed local path.

    Supports:
    - https://github.com/owner/repo(.git) -> owner/repo
    - git@github.com:owner/repo(.git) -> owner/repo
    - ssh://git@github.com/owner/repo(.git) -> owner/repo
    - owner/repo -> owner/repo
    - /path/to/repo -> /path/to/repo
    """
    cleaned = repo_input.strip()
    if not cleaned:
        raise ValueError("Repository identifier cannot be empty.")

    # Match git@github.com:owner/repo(.git)
    ssh_match = re.match(r"^git@[^:]+:([^/]+)/(.+?)(?:\.git)?$", cleaned)
    if ssh_match:
        return f"{ssh_match.group(1)}/{ssh_match.group(2)}"

    # Match https://... or ssh://...
    url_match = re.match(r"^(?:https?|ssh)://[^/]+/([^/]+)/(.+?)(?:\.git)?$", cleaned)
    if url_match:
        return f"{url_match.group(1)}/{url_match.group(2)}"

    # Match simple owner/repo
    simple_match = re.match(r"^([a-zA-Z0-9_\-\.]+)/([a-zA-Z0-9_\-\.]+)$", cleaned)
    if simple_match:
        return cleaned

    # Fallback to absolute or relative path for local repositories
    return cleaned


def validate_complementary_roles(implementer: str, reviewer: str) -> None:
    """Validate that implementer and reviewer are complementary if both are primary agents."""
    norm_impl = implementer.strip().lower()
    norm_rev = reviewer.strip().lower()

    valid_primaries = {"codex", "antigravity"}
    if norm_impl in valid_primaries and norm_rev in valid_primaries and norm_impl == norm_rev:
        raise ValueError(
            f"Invalid role configuration: '{implementer}' cannot be both implementer and reviewer. "
            f"mini me requires Codex and Antigravity to be complementary primary roles."
        )


def validate_project_policy(data: dict[str, Any]) -> list[str]:
    """Validate required project configuration fields and return any missing or invalid errors."""
    errors: list[str] = []

    if not data.get("project_id"):
        errors.append("project_id is required and cannot be empty")
    if not data.get("display_name"):
        errors.append("display_name is required and cannot be empty")
    if not data.get("repository"):
        errors.append("repository is required and cannot be empty")
    if not data.get("base_branch"):
        errors.append("base_branch is required and cannot be empty")

    implementer = data.get("implementer", "codex")
    reviewer = data.get("reviewer", "antigravity")
    try:
        validate_complementary_roles(implementer, reviewer)
    except ValueError as e:
        errors.append(str(e))

    return errors


class ProjectService:
    """Service for managing project registrations, updates, and repository binding."""

    def __init__(self, uow: PersistenceUnitOfWork):
        self.uow = uow

    def register_project(
        self,
        project_id: str,
        display_name: str,
        repository: str,
        base_branch: str = "main",
        openspec_path: str = "openspec",
        implementer: str = "codex",
        reviewer: str = "antigravity",
        checks: list[dict[str, Any]] | None = None,
        external_providers_allowed: list[str] | None = None,
        openrouter_drain_allowed: bool = False,
        deployment_preview: dict[str, Any] | None = None,
        deployment_production: dict[str, Any] | None = None,
    ) -> Project:
        """Register a new project with immutable project_id and validated policy."""
        set_correlation_context(project_id=project_id, operation_id="register_project")

        norm_repo = ""
        if repository and repository.strip():
            try:
                norm_repo = normalize_repository_identity(repository)
            except ValueError:
                norm_repo = ""

        data = {
            "project_id": project_id.strip() if project_id else "",
            "display_name": display_name.strip() if display_name else "",
            "repository": norm_repo,
            "base_branch": base_branch.strip() if base_branch else "",
            "implementer": implementer,
            "reviewer": reviewer,
        }
        errors = validate_project_policy(data)
        if errors:
            raise ValueError(f"Project registration failed policy validation: {'; '.join(errors)}")

        # Check for existing project with this project_id
        existing = self.uow.projects.get_by_id(project_id)
        if existing:
            raise ValueError(
                f"Project with ID '{project_id}' is already registered. "
                f"Project identifiers are immutable."
            )

        now = utc_now()
        project = Project(
            project_id=project_id,
            display_name=display_name,
            repository=norm_repo,
            base_branch=base_branch,
            openspec_path=openspec_path,
            implementer=implementer,
            reviewer=reviewer,
            checks=checks or [],
            external_providers_allowed=external_providers_allowed
            or ["codex", "antigravity", "deepseek"],
            openrouter_drain_allowed=openrouter_drain_allowed,
            deployment_preview=deployment_preview or {},
            deployment_production=deployment_production or {},
            status=ProjectStatus.ACTIVE,
            created_at=now,
            updated_at=now,
        )

        event = Event(
            event_type=EventType.PROJECT_REGISTERED,
            project_id=project.project_id,
            payload={
                "project_id": project.project_id,
                "display_name": project.display_name,
                "repository": project.repository,
                "base_branch": project.base_branch,
                "implementer": project.implementer,
                "reviewer": project.reviewer,
            },
            timestamp=now,
        )

        self.uow.projects.save(project)
        self.uow.events.save(event)
        self.uow.commit()

        logger.info(
            f"Registered project '{project.project_id}' bound to repository '{project.repository}'"
        )
        return project

    def update_project(
        self,
        project_id: str,
        display_name: str | None = None,
        base_branch: str | None = None,
        openspec_path: str | None = None,
        implementer: str | None = None,
        reviewer: str | None = None,
        checks: list[dict[str, Any]] | None = None,
        external_providers_allowed: list[str] | None = None,
        openrouter_drain_allowed: bool | None = None,
        deployment_preview: dict[str, Any] | None = None,
        deployment_production: dict[str, Any] | None = None,
        status: ProjectStatus | None = None,
    ) -> Project:
        """Update mutable fields of a registered project. The project_id remains immutable."""
        set_correlation_context(project_id=project_id, operation_id="update_project")

        project = self.uow.projects.get_by_id(project_id)
        if not project:
            raise ValueError(f"Project '{project_id}' not found.")

        new_impl = implementer if implementer is not None else project.implementer
        new_rev = reviewer if reviewer is not None else project.reviewer
        validate_complementary_roles(new_impl, new_rev)

        if display_name is not None:
            project.display_name = display_name
        if base_branch is not None:
            project.base_branch = base_branch
        if openspec_path is not None:
            project.openspec_path = openspec_path
        if implementer is not None:
            project.implementer = implementer
        if reviewer is not None:
            project.reviewer = reviewer
        if checks is not None:
            project.checks = checks
        if external_providers_allowed is not None:
            project.external_providers_allowed = external_providers_allowed
        if openrouter_drain_allowed is not None:
            project.openrouter_drain_allowed = openrouter_drain_allowed
        if deployment_preview is not None:
            project.deployment_preview = deployment_preview
        if deployment_production is not None:
            project.deployment_production = deployment_production
        if status is not None:
            project.status = status

        now = utc_now()
        project.updated_at = now

        event = Event(
            event_type=EventType.PROJECT_UPDATED,
            project_id=project.project_id,
            payload={
                "project_id": project.project_id,
                "display_name": project.display_name,
                "status": project.status.value,
            },
            timestamp=now,
        )

        self.uow.projects.save(project)
        self.uow.events.save(event)
        self.uow.commit()

        logger.info(f"Updated project '{project.project_id}'")
        return project

    def get_project(self, project_id: str) -> Project | None:
        return self.uow.projects.get_by_id(project_id)

    def list_projects(self) -> list[Project]:
        return self.uow.projects.list_all()
