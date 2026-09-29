"""Definition of Ready (DoR) evaluation service."""

from __future__ import annotations

import os

from minime.adapters.github import GitHubAdapter, GitHubAuthorizationError, GitHubRemoteError
from minime.adapters.openspec import OpenSpecAdapter
from minime.db.session import SchemaInvariantResult, verify_physical_schema_invariants
from minime.domain.enums import (
    ChangeStatus,
    EventType,
    ExternalOutcome,
    ReadinessState,
)
from minime.domain.interfaces import PersistenceUnitOfWork
from minime.domain.models import (
    Event,
    MetricFact,
    ReadinessCheck,
    ReadinessEvaluation,
    utc_now,
)
from minime.logging import get_logger, set_correlation_context
from minime.services.lifecycle_gates import StrictValidationGate

logger = get_logger("services.readiness")


class ReadinessService:
    """Evaluates Definition of Ready for OpenSpec changes."""

    def __init__(
        self,
        uow: PersistenceUnitOfWork,
        openspec_adapter: OpenSpecAdapter | None = None,
        github_adapter: GitHubAdapter | None = None,
    ):
        self.uow = uow
        self.openspec_adapter = openspec_adapter or OpenSpecAdapter()
        self.github_adapter = github_adapter or GitHubAdapter()

    def evaluate_change_readiness_pure(
        self,
        project_id: str,
        change_name: str,
        project_root: str,
        current_active_change: str | None = None,
        github_repo: str | None = None,
        github_issue: int | None = None,
    ) -> ReadinessEvaluation:
        """Evaluate Definition of Ready purely against canonical criteria."""
        set_correlation_context(
            project_id=project_id,
            change_id=change_name,
            operation_id="evaluate_readiness",
        )

        checks: list[ReadinessCheck] = []
        unmet_reasons: list[str] = []

        # Postgres UOWs expose their bound session; test doubles need no physical
        # preflight. Inspection is read-only and never repairs the schema.
        session = getattr(self.uow, "session", None)
        engine = getattr(session, "bind", None) if session is not None else None
        if engine is not None:
            try:
                schema = verify_physical_schema_invariants(engine)
            except Exception as exc:
                # Admission must fail closed even when catalog inspection itself
                # is unavailable; runtime never repairs or bypasses this check.
                schema = SchemaInvariantResult(
                    valid=False,
                    reason=f"Physical schema inspection failed: {exc}",
                )
            if not schema.valid:
                reason = f"SCHEMA_INVARIANT_VIOLATION: {schema.reason}"
                checks.append(
                    ReadinessCheck(
                        name="physical_schema",
                        passed=False,
                        reason=reason,
                        details={
                            "missing_tables": schema.missing_tables,
                            "missing_columns": schema.missing_columns,
                            "revision": schema.revision,
                        },
                    )
                )
                unmet_reasons.append(reason)
            else:
                checks.append(
                    ReadinessCheck(
                        name="physical_schema", passed=True, details={"revision": schema.revision}
                    )
                )

        # 1. Registered project check
        project = self.uow.projects.get_by_id(project_id)
        if not project:
            reason = f"Project '{project_id}' is not registered in mini me."
            checks.append(ReadinessCheck(name="registered_project", passed=False, reason=reason))
            unmet_reasons.append(reason)
            return ReadinessEvaluation(
                change_id=change_name,
                project_id=project_id,
                status=ReadinessState.NOT_READY,
                is_ready=False,
                unmet_reasons=unmet_reasons,
                checks=checks,
            )

        checks.append(
            ReadinessCheck(
                name="registered_project",
                passed=True,
                details={"project_id": project.project_id, "status": project.status.value},
            )
        )

        # 2. Repository identity & base branch
        if not project.repository or not project.base_branch:
            reason = "Project lacks a canonical repository identity or base branch."
            checks.append(ReadinessCheck(name="repository_identity", passed=False, reason=reason))
            unmet_reasons.append(reason)
        else:
            checks.append(
                ReadinessCheck(
                    name="repository_identity",
                    passed=True,
                    details={"repository": project.repository, "base_branch": project.base_branch},
                )
            )

        # 3. Complementary primary roles
        try:
            from minime.services.project_service import validate_complementary_roles

            validate_complementary_roles(project.implementer, project.reviewer)
            checks.append(
                ReadinessCheck(
                    name="complementary_roles",
                    passed=True,
                    details={"implementer": project.implementer, "reviewer": project.reviewer},
                )
            )
        except ValueError as e:
            reason = str(e)
            checks.append(ReadinessCheck(name="complementary_roles", passed=False, reason=reason))
            unmet_reasons.append(reason)

        # 3b. Primary pair capacity availability (005 complete-pair admission gating)
        if project.implementer and project.reviewer:
            from minime.services.provider_health_service import ProviderHealthService

            health_service = ProviderHealthService(self.uow)
            try:
                pair_avail, pair_reason = health_service.is_pair_available(
                    project.implementer, project.reviewer
                )
                if not pair_avail:
                    reason = f"Primary pair capacity shortage: {pair_reason}."
                    checks.append(
                        ReadinessCheck(name="primary_capacity", passed=False, reason=reason)
                    )
                    unmet_reasons.append(reason)
                else:
                    checks.append(
                        ReadinessCheck(
                            name="primary_capacity",
                            passed=True,
                            details={
                                "implementer": project.implementer,
                                "reviewer": project.reviewer,
                                "status": "available",
                            },
                        )
                    )
            except Exception as e:
                logger.warning(f"Capacity check error: {e}")

        # Stage C Admission Fence: Re-validate CURRENT Stage C truth using canonical authorities
        managed_binding_repo = getattr(self.uow, "project_managed_repository_bindings", None)
        managed_binding = managed_binding_repo.get_by_project_id(project_id) if managed_binding_repo else None

        from minime.services.agent_confinement import AgentProcessConfinement
        from minime.services.workspace_guard import ManagedWorkspaceGuard, is_binding_fully_valid

        guard = ManagedWorkspaceGuard(self.uow)

        stage_c_reason: str | None = None
        confinement_mech = "unknown"

        if managed_binding is None:
            stage_c_reason = f"Stage C Admission Fence: Missing managed repository binding for project '{project_id}'."
        elif not is_binding_fully_valid(managed_binding):
            m_reasons = getattr(managed_binding, "mismatch_reasons", None) or ["Invalid ProjectManagedRepositoryBinding"]
            stage_c_reason = f"Stage C Admission Fence: Managed repository binding is invalid: {'; '.join(m_reasons)}."
        else:
            managed_root = managed_binding.managed_repository_root
            wt_parent = managed_binding.worktree_parent_dir

            # 1. Prove BOTH managed_repository_root and worktree_parent_dir are currently observable directories
            if not os.path.exists(managed_root) or not os.path.isdir(managed_root):
                stage_c_reason = f"Stage C Admission Fence: Managed repository root '{managed_root}' does not exist or is not a directory."
            elif not os.path.exists(wt_parent) or not os.path.isdir(wt_parent):
                stage_c_reason = f"Stage C Admission Fence: Worktree parent directory '{wt_parent}' does not exist or is not a directory."
            else:
                runtime_root = guard.runtime_root

                # 2. Prove BOTH have no equality/parent/child overlap with RUNTIME using guard path helpers
                if guard._paths_overlap(managed_root, runtime_root) or guard._paths_overlap(wt_parent, runtime_root):
                    stage_c_reason = f"Stage C Admission Fence: Runtime root '{runtime_root}' collides or overlaps with managed workspace or worktree parent directory."
                elif guard.trusted_managed_root and (
                    not guard._is_path_inside(managed_root, guard.trusted_managed_root)
                    or not guard._is_path_inside(wt_parent, guard.trusted_managed_root)
                ):
                    stage_c_reason = f"Stage C Admission Fence: Managed root '{managed_root}' or worktree parent directory '{wt_parent}' escapes trusted managed root '{guard.trusted_managed_root}'."

                # 3. Require authoritative workspace classification to remain MANAGED_REPOSITORY
                if not stage_c_reason:
                    from minime.domain.enums import WorkspaceOperation, WorkspaceRole
                    from minime.domain.models import WorkspaceMutationRequest
                    class_req = WorkspaceMutationRequest(
                        project_id=project_id,
                        target_path=managed_root,
                        requested_operation=WorkspaceOperation.READ,
                    )
                    class_decision = guard.evaluate_mutation(class_req)
                    if not class_decision.allowed or class_decision.workspace_role != WorkspaceRole.MANAGED_REPOSITORY:
                        stage_c_reason = f"Stage C Admission Fence: Managed root '{managed_root}' failed workspace classification: {class_decision.provider_detail}"

                # 4. Re-observe Git repository identity
                if not stage_c_reason:
                    git_ok, git_msg = guard.verify_git_repository_identity(
                        managed_root,
                        managed_binding.canonical_repository_identity,
                        remote_name=managed_binding.remote_name,
                    )
                    if not git_ok:
                        stage_c_reason = f"Stage C Admission Fence: Current Git repository identity verification failed: {git_msg}"

                # 5. Re-observe Ownership Marker
                if not stage_c_reason:
                    marker_ok, marker_msg, _, _ = guard.verify_managed_repository_ownership_marker(
                        managed_root,
                        expected_project_id=project_id,
                        expected_repo_identity=managed_binding.canonical_repository_identity,
                    )
                    if not marker_ok:
                        stage_c_reason = f"Stage C Admission Fence: Managed repository ownership marker verification failed: {marker_msg}"

                # 6. Re-observe Agent Process Confinement availability
                if not stage_c_reason:
                    confinement = AgentProcessConfinement(
                        allowed_worktree_path=f"{wt_parent}/wt-readiness-probe"
                    )
                    confinement_mech = confinement.confinement_mechanism
                    if not confinement.is_confinement_available():
                        stage_c_reason = "Stage C Admission Fence: Agent process confinement capability is unavailable."

        if stage_c_reason:
            checks.append(ReadinessCheck(name="stage_c_workspace_isolation", passed=False, reason=stage_c_reason))
            unmet_reasons.append(stage_c_reason)
        else:
            checks.append(
                ReadinessCheck(
                    name="stage_c_workspace_isolation",
                    passed=True,
                    details={
                        "is_runtime_isolated": True,
                        "confinement_mechanism": confinement_mech,
                    },
                )
            )

        # 4. Durable ProjectBinding & GitHub Issue validation (execution authorization)
        try:
            binding = self.uow.bindings.get_by_project_and_change(project_id, change_name)
        except ValueError as e:
            reason = f"Ambiguous project bindings: {e}"
            checks.append(
                ReadinessCheck(name="durable_project_binding", passed=False, reason=reason)
            )
            unmet_reasons.append(reason)
            binding = None
            is_ambiguous = True
        else:
            is_ambiguous = False

        if not is_ambiguous:
            if not binding:
                reason = (
                    f"Missing durable project binding: no validated ProjectBinding exists "
                    f"for project '{project_id}' and change '{change_name}'."
                )
                checks.append(
                    ReadinessCheck(name="durable_project_binding", passed=False, reason=reason)
                )
                unmet_reasons.append(reason)

            elif not binding.is_valid:
                reasons_str = (
                    "; ".join(binding.mismatch_reasons)
                    if binding.mismatch_reasons
                    else "binding marked invalid"
                )
                reason = f"Invalid project binding: {reasons_str}."
                checks.append(
                    ReadinessCheck(name="durable_project_binding", passed=False, reason=reason)
                )
                unmet_reasons.append(reason)
            elif binding.repository != project.repository:
                reason = (
                    f"Repository mismatch: ProjectBinding repository '{binding.repository}' "
                    f"does not match registered project repository '{project.repository}'."
                )
                checks.append(
                    ReadinessCheck(name="durable_project_binding", passed=False, reason=reason)
                )
                unmet_reasons.append(reason)
            elif github_repo and github_repo != project.repository:
                reason = (
                    f"Repository mismatch: work item repository '{github_repo}' "
                    f"does not match registered project repository '{project.repository}'."
                )
                checks.append(
                    ReadinessCheck(name="durable_project_binding", passed=False, reason=reason)
                )
                unmet_reasons.append(reason)
            elif binding.github_issue_number is None and github_issue is None:
                reason = (
                    f"Missing GitHub Issue binding: ProjectBinding for project '{project_id}' "
                    f"and change '{change_name}' has no associated GitHub Issue number."
                )
                checks.append(
                    ReadinessCheck(name="durable_project_binding", passed=False, reason=reason)
                )
                unmet_reasons.append(reason)
            else:
                effective_issue = github_issue or binding.github_issue_number
                try:
                    binding_res = self.github_adapter.validate_issue_binding(
                        project.repository, effective_issue, github_repository=github_repo
                    )
                    issue_valid = binding_res.outcome == ExternalOutcome.SUCCESS and binding_res.data is True
                    issue_reason = binding_res.error_message
                except GitHubRemoteError as exc:
                    issue_valid = False
                    issue_reason = f"Transient GitHub unobservability: {exc}"
                except GitHubAuthorizationError as exc:
                    issue_valid = False
                    issue_reason = f"GitHub App authorization failure: {exc}"
                if not issue_valid:
                    reason = issue_reason or "Remote GitHub Issue validation failed."
                    checks.append(
                        ReadinessCheck(
                            name="github_issue_verification",
                            passed=False,
                            reason=reason,
                            details={
                                "repository": project.repository,
                                "issue_number": effective_issue,
                            },
                        )
                    )
                    unmet_reasons.append(reason)
                else:
                    checks.append(
                        ReadinessCheck(
                            name="durable_project_binding",
                            passed=True,
                            details={
                                "binding_id": binding.binding_id,
                                "repository": binding.repository,
                                "issue_number": effective_issue,
                                "github_app_authentication": "github_app_installation",
                            },
                        )
                    )

        # 5. OpenSpec artifacts evaluation
        artifacts_eval = self.openspec_adapter.evaluate_artifacts(
            project, change_name, project_root
        )
        if not artifacts_eval["exists"]:
            reason = f"OpenSpec change directory for '{change_name}' does not exist on disk."
            checks.append(ReadinessCheck(name="openspec_artifacts", passed=False, reason=reason))
            unmet_reasons.append(reason)
        else:
            missing_artifacts: list[str] = []
            if not artifacts_eval["proposal_present"]:
                missing_artifacts.append("proposal.md")
            if not artifacts_eval["tasks_present"]:
                missing_artifacts.append("tasks.md")
            if not artifacts_eval["design_present"]:
                missing_artifacts.append("design.md")
            if not artifacts_eval["specs_present"]:
                missing_artifacts.append("specs/")

            if missing_artifacts:
                reason = f"Missing required OpenSpec artifacts: {', '.join(missing_artifacts)}."
                checks.append(
                    ReadinessCheck(name="openspec_artifacts", passed=False, reason=reason)
                )
                unmet_reasons.append(reason)
            else:
                checks.append(
                    ReadinessCheck(
                        name="openspec_artifacts",
                        passed=True,
                        details={
                            "specs_count": artifacts_eval["specs_count"],
                            "tasks_count": artifacts_eval["tasks_count"],
                            "tasks_remaining": artifacts_eval["tasks_remaining"],
                        },
                    )
                )

        # Canonical CLI validation is distinct from artifact presence. UNKNOWN is
        # deliberately blocking because readiness cannot truthfully be proven.
        if project.strict_validation_required:
            strict_result = StrictValidationGate(self.openspec_adapter).evaluate(
                change_name=change_name, project_root=project_root
            )
            if strict_result.is_blocking:
                reason = f"{strict_result.reason.code}: {strict_result.reason.message}"
                checks.append(
                    ReadinessCheck(
                        name="openspec_strict_validation",
                        passed=False,
                        reason=reason,
                        details=strict_result.reason.details,
                    )
                )
                unmet_reasons.append(reason)
            else:
                checks.append(
                    ReadinessCheck(
                        name="openspec_strict_validation",
                        passed=True,
                        details=strict_result.reason.details,
                    )
                )

        # 6. Roadmap gating
        # If another change is currently the designated active foundation change, later changes cannot be READY
        if current_active_change and current_active_change != change_name:
            reason = (
                f"Roadmap gating: earlier stage '{current_active_change}' is currently active. "
                f"Later change '{change_name}' cannot enter READY until prior stages complete."
            )
            checks.append(ReadinessCheck(name="roadmap_gating", passed=False, reason=reason))
            unmet_reasons.append(reason)
        else:
            checks.append(ReadinessCheck(name="roadmap_gating", passed=True))

        is_ready = len(unmet_reasons) == 0
        status = ReadinessState.READY if is_ready else ReadinessState.NOT_READY

        now = utc_now()
        return ReadinessEvaluation(
            change_id=change_name,
            project_id=project_id,
            status=status,
            is_ready=is_ready,
            unmet_reasons=unmet_reasons,
            checks=checks,
            evaluated_at=now,
        )

    def evaluate_change_readiness(
        self,
        project_id: str,
        change_name: str,
        project_root: str,
        current_active_change: str | None = None,
        github_repo: str | None = None,
        github_issue: int | None = None,
    ) -> ReadinessEvaluation:
        """Command alias: Evaluate Definition of Ready and persist updated Change, Event, and MetricFact."""
        return self.evaluate_and_persist_change_readiness(
            project_id=project_id,
            change_name=change_name,
            project_root=project_root,
            current_active_change=current_active_change,
            github_repo=github_repo,
            github_issue=github_issue,
        )

    def evaluate_and_persist_change_readiness(
        self,
        project_id: str,
        change_name: str,
        project_root: str,
        current_active_change: str | None = None,
        github_repo: str | None = None,
        github_issue: int | None = None,
    ) -> ReadinessEvaluation:
        """Command: Evaluate Definition of Ready and persist updated Change, Event, and MetricFact."""
        evaluation = self.evaluate_change_readiness_pure(
            project_id=project_id,
            change_name=change_name,
            project_root=project_root,
            current_active_change=current_active_change,
            github_repo=github_repo,
            github_issue=github_issue,
        )

        status = evaluation.status
        is_ready = evaluation.is_ready
        unmet_reasons = evaluation.unmet_reasons
        now = evaluation.evaluated_at

        # Update change record in persistence if exists, or create if absent
        change_record = self.uow.changes.get_by_name(project_id, change_name)
        state_changed = True
        if change_record:
            state_changed = (
                change_record.last_readiness_status != status
                or change_record.last_readiness_reasons != unmet_reasons
            )
            if state_changed:
                change_record.last_readiness_status = status
                change_record.last_readiness_reasons = unmet_reasons
                change_record.updated_at = now
                self.uow.changes.save(change_record)
        else:
            from minime.domain.models import Change

            change_record = Change(
                project_id=project_id,
                name=change_name,
                status=ChangeStatus.DISCOVERED,
                last_readiness_status=status,
                last_readiness_reasons=unmet_reasons,
                discovered_at=now,
                updated_at=now,
            )
            self.uow.changes.save(change_record)

        # Emit audit event and metric fact only on state transition or if no prior record
        if state_changed:
            event = Event(
                event_type=EventType.READINESS_EVALUATED,
                project_id=project_id,
                change_id=change_name,
                payload={
                    "is_ready": is_ready,
                    "status": status.value,
                    "unmet_reasons": unmet_reasons,
                },
                timestamp=now,
            )
            self.uow.events.save(event)

            metric_fact = MetricFact(
                metric_name="readiness_evaluation",
                project_id=project_id,
                change_id=change_name,
                fact_value=1.0 if is_ready else 0.0,
                details={"is_ready": is_ready, "unmet_reasons_count": len(unmet_reasons)},
                recorded_at=now,
            )
            self.uow.metrics.save(metric_fact)
            self.uow.commit()

        return evaluation
