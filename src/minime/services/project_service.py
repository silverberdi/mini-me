"""Project registry and repository binding service."""

from __future__ import annotations

import os
import shutil
from typing import Any

from minime.domain.enums import EventType, ProjectOnboardingStatus, ProjectStatus, ProjectType
from minime.domain.interfaces import (
    PersistenceUnitOfWork,
)
from minime.domain.models import (
    Event,
    Project,
    ProjectConfigurationInput,
    ProjectConfigurationPatch,
    utc_now,
)
from minime.logging import get_logger, set_correlation_context
from minime.services.project_credential_store import ProjectCredentialStore
from minime.services.repository_identity import (
    normalize_repository_identity as _normalize_repository_identity,
)

logger = get_logger("services.project")


def normalize_repository_identity(repo_input: str) -> str:
    """Normalize repository input using the shared host-sensitive identity rule."""
    normalized = _normalize_repository_identity(repo_input)
    if not normalized:
        raise ValueError("Repository identifier cannot be empty.")
    return normalized


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


def validate_admission_policy(
    auto_prepare: bool, auto_admit: bool, max_concurrent_jobs: int
) -> None:
    """Reject invalid admission settings before mutating project state."""
    for name, value in (("auto_prepare", auto_prepare), ("auto_admit", auto_admit)):
        if type(value) is not bool:
            raise ValueError(f"{name} must be a boolean")
    if type(max_concurrent_jobs) is not int or max_concurrent_jobs < 1:
        raise ValueError("max_concurrent_jobs must be a positive integer")


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

    def __init__(
        self,
        uow: PersistenceUnitOfWork,
        credential_store: ProjectCredentialStore | None = None,
    ):
        self.uow = uow
        self.credential_store = credential_store or ProjectCredentialStore()

    def create_configured_project(self, configuration: ProjectConfigurationInput) -> Project:
        """Persist a validated project configuration without claiming bootstrap readiness.

        Greenfield creation is deliberately refused here: it must be paired with a
        validated context package and the durable bootstrap coordinator.
        """
        if configuration.project_type == ProjectType.GREENFIELD:
            raise ValueError("GREENFIELD requires a validated ZIP bootstrap operation")
        project_id = configuration.project_id.strip()
        repository = normalize_repository_identity(configuration.repository)
        self._validate_agent_profiles(configuration.agent_profiles)
        normalized_connections: dict[str, dict[str, Any]] = {}
        for key, value in configuration.provider_connections.items():
            connection_repository = normalize_repository_identity(value.repository_url)
            if not connection_repository or connection_repository.startswith(("/", "file:")):
                raise ValueError(f"Provider connection '{key}' requires a GitHub repository identity")
            if "://" in value.repository_url and "github.com/" not in value.repository_url.lower():
                raise ValueError(f"Provider connection '{key}' must use a GitHub repository URL")
            normalized_connections[key] = value.model_dump(mode="json")
            normalized_connections[key]["repository_url"] = connection_repository
        if self.uow.projects.get_by_id(project_id):
            raise ValueError(f"Project with ID '{project_id}' is already registered")
        for existing in self.uow.projects.list_all():
            if normalize_repository_identity(existing.repository) == repository:
                raise ValueError(
                    f"Repository '{repository}' is already bound to project '{existing.project_id}'"
                )

        credential_ref: str | None = None
        try:
            if configuration.github_app_credentials:
                credentials = configuration.github_app_credentials
                credential_ref = self.credential_store.store_github_app(
                    project_id,
                    credentials.app_id,
                    credentials.installation_id,
                    credentials.private_key.get_secret_value(),
                )
            connections = normalized_connections
            for key, value in configuration.provider_connections.items():
                connection = connections[key]
                if value.auth_mode == "project_app" and credential_ref:
                    connection["secret_reference"] = credential_ref
                connections[key] = connection

            now = utc_now()
            project = Project(
                project_id=project_id,
                display_name=configuration.display_name.strip(),
                repository=repository,
                project_type=configuration.project_type,
                base_branch=configuration.base_branch.strip() or "main",
                provider_connections=connections,
                agent_profiles={
                    key: value.model_dump(mode="json")
                    for key, value in configuration.agent_profiles.items()
                },
                execution_policy=configuration.execution_policy,
                onboarding_status=ProjectOnboardingStatus.CONFIGURED,
                onboarding_reasons=[
                    "Brownfield adaptation is deferred; project is configuration-only."
                ],
                status=ProjectStatus.ACTIVE,
                created_at=now,
                updated_at=now,
            )
            self.uow.projects.save(project)
            self.uow.events.save(
                Event(
                    project_id=project.project_id,
                    event_type=EventType.PROJECT_REGISTERED,
                    payload={
                        "project_type": project.project_type.value,
                        "repository": project.repository,
                        "onboarding_status": project.onboarding_status.value,
                    },
                    timestamp=now,
                )
            )
            self.uow.commit()
            return project
        except Exception:
            if credential_ref:
                self.credential_store.remove_github_app(project_id, credential_ref)
            self.uow.rollback()
            raise

    def set_lifecycle(self, project_id: str, *, active: bool) -> Project:
        project = self.uow.projects.get_by_id(project_id)
        if project is None:
            raise ValueError(f"Project '{project_id}' not found")
        project.status = ProjectStatus.ACTIVE if active else ProjectStatus.PAUSED
        project.updated_at = utc_now()
        self.uow.projects.save(project)
        self.uow.commit()
        return project

    def update_configuration(
        self, project_id: str, patch: ProjectConfigurationPatch
    ) -> Project:
        project = self.uow.projects.get_by_id(project_id)
        if project is None:
            raise ValueError(f"Project '{project_id}' not found")
        if patch.github_app_credentials and patch.provider_connections is None:
            raise ValueError("updating GitHub App credentials requires an explicit provider connection update")
        if patch.agent_profiles is not None:
            self._validate_agent_profiles(patch.agent_profiles)

        credential_ref: str | None = None
        try:
            if patch.github_app_credentials:
                credentials = patch.github_app_credentials
                credential_ref = self.credential_store.store_github_app(
                    project_id,
                    credentials.app_id,
                    credentials.installation_id,
                    credentials.private_key.get_secret_value(),
                )
            if patch.display_name is not None:
                project.display_name = patch.display_name.strip()
            if patch.base_branch is not None:
                project.base_branch = patch.base_branch.strip()
            if patch.provider_connections is not None:
                connections: dict[str, dict[str, Any]] = {}
                for key, value in patch.provider_connections.items():
                    connection_repository = normalize_repository_identity(value.repository_url)
                    if not connection_repository or connection_repository.startswith(("/", "file:")):
                        raise ValueError(
                            f"Provider connection '{key}' requires a GitHub repository identity"
                        )
                    if "://" in value.repository_url and "github.com/" not in value.repository_url.lower():
                        raise ValueError(f"Provider connection '{key}' must use a GitHub repository URL")
                    connection = value.model_dump(mode="json")
                    connection["repository_url"] = connection_repository
                    if value.auth_mode == "project_app":
                        reference = credential_ref or connection.get("secret_reference")
                        if not reference:
                            existing = project.provider_connections.get(key, {})
                            reference = existing.get("secret_reference")
                        if not reference:
                            raise ValueError("project_app connection has no protected credential")
                        connection["secret_reference"] = reference
                    connections[key] = connection
                project.provider_connections = connections
            if patch.agent_profiles is not None:
                expected = {"thinking", "execution", "independent_review", "fallback"}
                missing = expected - set(patch.agent_profiles)
                if missing:
                    raise ValueError("Missing agent profiles: " + ", ".join(sorted(missing)))
                project.agent_profiles = {
                    key: value.model_dump(mode="json")
                    for key, value in patch.agent_profiles.items()
                }
            if patch.execution_policy is not None:
                project.execution_policy = patch.execution_policy
            project.updated_at = utc_now()
            self.uow.projects.save(project)
            self.uow.commit()
            return project
        except Exception:
            if credential_ref:
                self.credential_store.remove_github_app(project_id, credential_ref)
            self.uow.rollback()
            raise

    @staticmethod
    def _validate_agent_profiles(profiles) -> None:
        """Resolve chosen profiles against configured, installed file-capable CLIs."""
        from minime.config import (
            SUPPORTED_PROVIDER_EFFORTS,
            SUPPORTED_PROVIDER_MODELS,
            load_config,
            resolve_cli_invocation,
        )

        role_names = {
            "thinking": "implementer",
            "execution": "implementer",
            "independent_review": "reviewer",
            "fallback": "implementer",
        }
        config = load_config()
        normalized_ids: dict[str, str] = {}
        for role, profile in profiles.items():
            agent_id = profile.agent_id.strip().lower()
            provider_id = "antigravity" if agent_id == "agy" else agent_id
            provider = config.providers.get(provider_id)
            if provider is None or provider.type != "cli" or not provider.enabled:
                raise ValueError(f"Agent '{agent_id}' is not an enabled native CLI provider")
            executable = (provider.command or "").strip().split(maxsplit=1)
            if not executable or shutil.which(executable[0]) is None:
                raise ValueError(f"Agent '{agent_id}' executable is not installed")
            provider_models = SUPPORTED_PROVIDER_MODELS.get(provider_id, {})
            if profile.model_id.strip().lower() not in provider_models:
                raise ValueError(f"Model '{profile.model_id}' is not in the verified {agent_id} catalog")
            supported_efforts = SUPPORTED_PROVIDER_EFFORTS.get(provider_id, set())
            if profile.effort.strip().lower() not in supported_efforts:
                raise ValueError(f"Effort '{profile.effort}' is not supported by {agent_id}")
            try:
                resolve_cli_invocation(
                    provider_id,
                    role_names[role],
                    config,
                    model=profile.model_id,
                    effort=profile.effort,
                )
            except ValueError as exc:
                raise ValueError(f"Agent profile '{role}' cannot be invoked: {exc}") from exc
            normalized_ids[role] = provider_id
        if normalized_ids.get("execution") == normalized_ids.get("independent_review"):
            raise ValueError("Independent review must use an agent distinct from the execution author")

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
        independent_audit_required: bool = False,
        strict_validation_required: bool = True,
        verify_gate_required: bool = True,
        sync_gate_required: bool = True,
        archive_gate_required: bool = True,
        deployment_preview: dict[str, Any] | None = None,
        deployment_production: dict[str, Any] | None = None,
        auto_prepare: bool = True,
        auto_admit: bool = True,
        max_concurrent_jobs: int = 1,
    ) -> Project:
        """Register a new project with immutable project_id and validated policy."""
        set_correlation_context(project_id=project_id, operation_id="register_project")

        validate_admission_policy(auto_prepare, auto_admit, max_concurrent_jobs)

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
            independent_audit_required=independent_audit_required,
            strict_validation_required=strict_validation_required,
            verify_gate_required=verify_gate_required,
            sync_gate_required=sync_gate_required,
            archive_gate_required=archive_gate_required,
            deployment_preview=deployment_preview or {},
            deployment_production=deployment_production or {},
            auto_prepare=auto_prepare,
            auto_admit=auto_admit,
            max_concurrent_jobs=max_concurrent_jobs,
            status=ProjectStatus.ACTIVE,
            created_at=now,
            updated_at=now,
        )

        from minime.domain.models import ProjectManagedRepositoryBinding
        from minime.services.workspace_guard import ManagedWorkspaceGuard

        trusted_root = os.path.realpath(os.environ.get("MINIME_MANAGED_ROOT", "/opt/minime/repos"))
        managed_root = os.path.realpath(
            openspec_path if openspec_path.startswith("/") else f"{trusted_root}/{project_id}"
        )
        runtime_root = os.path.realpath(os.environ.get("MINIME_RUNTIME_ROOT", os.getcwd()))
        worktree_parent_dir = os.path.realpath(f"{managed_root}/.minime/worktrees")

        mismatch_reasons: list[str] = []
        guard = ManagedWorkspaceGuard(
            self.uow, runtime_root=runtime_root, trusted_managed_root=trusted_root
        )

        # Check forward & reverse overlap
        if guard._paths_overlap(managed_root, runtime_root):
            mismatch_reasons.append(
                f"Managed repository root '{managed_root}' aliases or overlaps runtime root '{runtime_root}'."
            )

        if guard._paths_overlap(worktree_parent_dir, runtime_root):
            mismatch_reasons.append(
                f"Worktree parent dir '{worktree_parent_dir}' aliases or overlaps runtime root '{runtime_root}'."
            )

        # Check trusted root for BOTH managed_root and worktree_parent_dir
        if trusted_root:
            if not (
                guard._is_path_inside(managed_root, trusted_root) or managed_root == trusted_root
            ):
                mismatch_reasons.append(
                    f"Managed repository root '{managed_root}' is outside trusted managed root '{trusted_root}'."
                )
            if not (
                guard._is_path_inside(worktree_parent_dir, trusted_root)
                or worktree_parent_dir == trusted_root
            ):
                mismatch_reasons.append(
                    f"Worktree parent directory '{worktree_parent_dir}' is outside trusted managed root '{trusted_root}'."
                )

        # Check directory existence and Git repository proof
        if not os.path.exists(managed_root) or not os.path.isdir(managed_root):
            mismatch_reasons.append(
                f"Managed repository root directory '{managed_root}' does not exist on disk."
            )
        else:
            valid_git, git_reason = guard.verify_git_repository_identity(
                managed_root, norm_repo, remote_name="origin"
            )
            if not valid_git:
                mismatch_reasons.append(
                    f"Git repository identity verification failed for '{managed_root}': {git_reason}"
                )

        if not os.path.exists(worktree_parent_dir) or not os.path.isdir(worktree_parent_dir):
            mismatch_reasons.append(
                f"Worktree parent directory '{worktree_parent_dir}' does not exist on disk."
            )

        is_valid_binding = len(mismatch_reasons) == 0

        managed_binding = ProjectManagedRepositoryBinding(
            project_id=project_id,
            canonical_repository_identity=norm_repo,
            remote_name="origin",
            managed_repository_root=managed_root,
            worktree_parent_dir=worktree_parent_dir,
            default_base_branch=base_branch,
            is_valid=is_valid_binding,
            mismatch_reasons=mismatch_reasons,
            created_at=now,
            updated_at=now,
        )
        self.uow.project_managed_repository_bindings.save(managed_binding)

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
        independent_audit_required: bool | None = None,
        deployment_preview: dict[str, Any] | None = None,
        deployment_production: dict[str, Any] | None = None,
        auto_prepare: bool | None = None,
        auto_admit: bool | None = None,
        max_concurrent_jobs: int | None = None,
        status: ProjectStatus | None = None,
    ) -> Project:
        """Update mutable fields of a registered project. The project_id remains immutable."""
        set_correlation_context(project_id=project_id, operation_id="update_project")

        project = self.uow.projects.get_by_id(project_id)
        if not project:
            raise ValueError(f"Project '{project_id}' not found.")

        validate_admission_policy(
            auto_prepare if auto_prepare is not None else project.auto_prepare,
            auto_admit if auto_admit is not None else project.auto_admit,
            max_concurrent_jobs if max_concurrent_jobs is not None else project.max_concurrent_jobs,
        )

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
        if independent_audit_required is not None:
            project.independent_audit_required = independent_audit_required
        if deployment_preview is not None:
            project.deployment_preview = deployment_preview
        if deployment_production is not None:
            project.deployment_production = deployment_production
        if auto_prepare is not None:
            project.auto_prepare = auto_prepare
        if auto_admit is not None:
            project.auto_admit = auto_admit
        if max_concurrent_jobs is not None:
            project.max_concurrent_jobs = max_concurrent_jobs
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

    @staticmethod
    def public_project_payload(project: Project) -> dict[str, Any]:
        """Serialize project configuration without host-secret references."""
        payload = project.model_dump(mode="json")
        for connection in payload.get("provider_connections", {}).values():
            if not isinstance(connection, dict):
                continue
            credential_configured = bool(connection.pop("secret_reference", None))
            connection["credential_configured"] = credential_configured
        return payload
