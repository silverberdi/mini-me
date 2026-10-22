"""Project registry and repository binding service."""

from __future__ import annotations

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
from minime.logging import redact_secrets
from minime.services.project_credential_store import ProjectCredentialStore
from minime.services.repository_identity import (
    normalize_repository_identity as _normalize_repository_identity,
)


def normalize_repository_identity(repo_input: str) -> str:
    """Normalize repository input using the shared host-sensitive identity rule."""
    normalized = _normalize_repository_identity(repo_input)
    if not normalized:
        raise ValueError("Repository identifier cannot be empty.")
    return normalized


class ProjectService:
    """Manage validated project configuration and lifecycle without onboarding side effects."""

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
        commit_started = False
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
                execution_policy=configuration.execution_policy.model_dump(mode="json"),
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
            commit_started = True
            self.uow.commit()
            return project
        except Exception:
            if credential_ref and not commit_started:
                self.credential_store.remove_github_app(project_id, credential_ref)
            self.uow.rollback()
            raise

    def set_lifecycle(self, project_id: str, *, active: bool) -> Project:
        project = self.uow.projects.get_by_id(project_id)
        if project is None:
            raise ValueError(f"Project '{project_id}' not found")
        if (
            active
            and project.project_type == ProjectType.GREENFIELD
            and project.onboarding_status != ProjectOnboardingStatus.PREPARED
        ):
            raise ValueError(
                "Greenfield project cannot be activated before its exact bootstrap PR merge is observed"
            )
        project.status = ProjectStatus.ACTIVE if active else ProjectStatus.PAUSED
        project.updated_at = utc_now()
        self.uow.projects.save(project)
        self.uow.commit()
        return project

    def observe_bootstrap_merge(self, project_id: str) -> dict[str, Any]:
        """Advance Greenfield readiness only from an exact provider-observed PR merge."""
        from minime.domain.enums import ExternalOutcome
        from minime.services.project_connection_service import ProjectConnectionService

        project = self.uow.projects.get_by_id(project_id)
        if project is None:
            raise ValueError(f"Project '{project_id}' not found")
        if project.project_type != ProjectType.GREENFIELD:
            raise ValueError("Bootstrap merge observation applies only to Greenfield projects")
        if project.onboarding_status not in {
            ProjectOnboardingStatus.PR_PENDING,
            ProjectOnboardingStatus.BOOTSTRAP_PENDING,
            ProjectOnboardingStatus.AWAITING_REVIEW,
        }:
            return {
                "project_id": project_id,
                "onboarding_status": project.onboarding_status.value,
                "observed": False,
                "reason": "project_has_no_pending_bootstrap_pr",
            }
        checkpoint = project.onboarding_checkpoint
        required = (
            "pull_request_number",
            "pull_request_url",
            "bootstrap_branch",
            "head_sha",
            "base_branch",
        )
        if any(not checkpoint.get(field) for field in required):
            return {
                "project_id": project_id,
                "onboarding_status": project.onboarding_status.value,
                "observed": False,
                "reason": "bootstrap_pr_identity_incomplete",
            }
        try:
            pr_number = int(checkpoint["pull_request_number"])
        except (TypeError, ValueError):
            pr_number = 0
        if pr_number <= 0:
            return {
                "project_id": project_id,
                "onboarding_status": project.onboarding_status.value,
                "observed": False,
                "reason": "bootstrap_pr_identity_incomplete",
            }
        try:
            adapter = ProjectConnectionService(self.credential_store).adapter_for(
                project, "git_pr"
            )
        except (ValueError, RuntimeError):
            return {
                "project_id": project_id,
                "onboarding_status": project.onboarding_status.value,
                "observed": False,
                "reason": "git_pr_connection_unavailable",
            }
        result = adapter.get_pull_request_details(
            project.provider_connections["git_pr"]["repository_url"],
            pr_number,
        )
        if result.outcome != ExternalOutcome.SUCCESS or not isinstance(result.data, dict):
            return {
                "project_id": project_id,
                "onboarding_status": project.onboarding_status.value,
                "observed": False,
                "reason": "pull_request_unobservable",
            }
        details = result.data
        try:
            configured_repository = normalize_repository_identity(
                project.provider_connections["git_pr"]["repository_url"]
            )
            observed_repository = normalize_repository_identity(str(details.get("repository", "")))
        except (KeyError, TypeError, ValueError):
            configured_repository = observed_repository = ""
        exact_identity = bool(configured_repository) and (
            observed_repository == configured_repository
            and details.get("number") == pr_number
            and details.get("url") == checkpoint["pull_request_url"]
            and details.get("head_branch") == checkpoint["bootstrap_branch"]
            and details.get("head_sha") == checkpoint["head_sha"]
            and details.get("base_branch") == checkpoint["base_branch"] == project.base_branch
        )
        if not exact_identity:
            return {
                "project_id": project_id,
                "onboarding_status": project.onboarding_status.value,
                "observed": False,
                "reason": "pull_request_identity_mismatch",
            }
        if not details.get("is_merged"):
            return {
                "project_id": project_id,
                "onboarding_status": project.onboarding_status.value,
                "observed": True,
                "merged": False,
                "pull_request_number": pr_number,
            }
        if not details.get("merge_commit_sha") or not details.get("merged_at"):
            return {
                "project_id": project_id,
                "onboarding_status": project.onboarding_status.value,
                "observed": False,
                "reason": "merge_postcondition_incomplete",
            }
        project.onboarding_status = ProjectOnboardingStatus.PREPARED
        project.onboarding_reasons = []
        project.onboarding_checkpoint = {
            **checkpoint,
            "merge_commit_sha": details["merge_commit_sha"],
            "merge_observed_at": utc_now().isoformat(),
        }
        project.updated_at = utc_now()
        self.uow.projects.save(project)
        self.uow.commit()
        return {
            "project_id": project_id,
            "onboarding_status": project.onboarding_status.value,
            "observed": True,
            "merged": True,
            "merge_commit_sha": details["merge_commit_sha"],
        }

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

        binding = self.uow.project_managed_repository_bindings.get_by_project_id(project_id)
        changed_base_branch = (
            patch.base_branch is not None and patch.base_branch.strip() != project.base_branch
        )
        if changed_base_branch and binding is not None:
            from minime.adapters.github import GitHubAdapter
            from minime.domain.enums import ExternalOutcome
            from minime.services.workspace_guard import (
                ManagedWorkspaceGuard,
                is_binding_fully_valid,
            )

            if not is_binding_fully_valid(binding) or normalize_repository_identity(
                binding.canonical_repository_identity
            ) != normalize_repository_identity(project.repository):
                raise ValueError("Cannot change base branch while repository binding is invalid")
            guard = ManagedWorkspaceGuard(self.uow)
            marker_ok, _, _, _ = guard.verify_managed_repository_ownership_marker(
                binding.managed_repository_root,
                project_id,
                binding.canonical_repository_identity,
                binding.ownership_marker_filename,
            )
            if not marker_ok:
                raise ValueError("Cannot change base branch without a valid managed-repository marker")
            git_connection = (
                patch.provider_connections.get("git_pr")
                if patch.provider_connections is not None
                else project.provider_connections.get("git_pr")
            )
            if not isinstance(git_connection, dict):
                raise ValueError("Cannot change base branch without a configured Git/PR connection")
            adapter = GitHubAdapter.for_project_connection(
                project_id, git_connection, self.credential_store
            )
            identity_ok, identity_reason = guard.verify_git_repository_identity(
                binding.managed_repository_root,
                binding.canonical_repository_identity,
                remote_name="origin",
            )
            if not identity_ok:
                raise ValueError(f"Cannot change base branch: repository identity failed: {identity_reason}")
            branch_result = adapter.get_remote_branch_head(
                binding.managed_repository_root, patch.base_branch.strip(), remote="origin"
            )
            if branch_result.outcome != ExternalOutcome.SUCCESS or not branch_result.data:
                raise ValueError(
                    "Cannot change base branch because the configured remote branch is absent or unobservable"
                )

        credential_ref: str | None = None
        commit_started = False
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
                if changed_base_branch and binding is not None:
                    binding.default_base_branch = project.base_branch
                    binding.updated_at = utc_now()
                    self.uow.project_managed_repository_bindings.save(binding)
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
                project.execution_policy = patch.execution_policy.model_dump(mode="json")
            project.updated_at = utc_now()
            self.uow.projects.save(project)
            commit_started = True
            self.uow.commit()
            return project
        except Exception:
            if credential_ref and not commit_started:
                self.credential_store.remove_github_app(project_id, credential_ref)
            self.uow.rollback()
            raise

    @staticmethod
    def _validate_agent_profiles(profiles) -> None:
        """Resolve chosen profiles against configured, installed file-capable CLIs."""
        from minime.config import (
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
        reviewer_id = normalized_ids.get("independent_review")
        for author_role in ("thinking", "execution"):
            if reviewer_id and reviewer_id == normalized_ids.get(author_role):
                raise ValueError(
                    f"Independent review must use an agent distinct from the {author_role} author"
                )

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

    @staticmethod
    def public_onboarding_state(project: Project) -> dict[str, Any]:
        """Expose truthful onboarding progress without returning arbitrary checkpoint data."""
        checkpoint_fields = {
            "operation_revision",
            "source_zip_sha256",
            "provenance_reference",
            "bootstrap_branch",
            "base_branch",
            "base_sha",
            "head_sha",
            "pull_request_number",
            "pull_request_url",
            "expected_base_sha",
            "merge_commit_sha",
            "merge_observed_at",
        }
        checkpoint = {
            key: value
            for key, value in project.onboarding_checkpoint.items()
            if key in checkpoint_fields
        }
        return {
            "project_id": project.project_id,
            "project_type": project.project_type.value,
            "lifecycle": project.status.value,
            "onboarding_status": project.onboarding_status.value,
            "reasons": [redact_secrets(reason) for reason in project.onboarding_reasons],
            "checkpoint": checkpoint,
        }
