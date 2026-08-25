"""Definition of Ready (DoR) evaluation service."""

from __future__ import annotations

from minime.adapters.github import GitHubAdapter, GitHubAuthorizationError, GitHubRemoteError
from minime.adapters.openspec import OpenSpecAdapter
from minime.domain.enums import ChangeStatus, EventType, ReadinessState
from minime.domain.interfaces import PersistenceUnitOfWork
from minime.domain.models import (
    Event,
    MetricFact,
    ReadinessCheck,
    ReadinessEvaluation,
    utc_now,
)
from minime.logging import get_logger, set_correlation_context

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

    def evaluate_change_readiness(
        self,
        project_id: str,
        change_name: str,
        project_root: str,
        current_active_change: str | None = None,
        github_repo: str | None = None,
        github_issue: int | None = None,
    ) -> ReadinessEvaluation:
        """Evaluate Definition of Ready against canonical criteria."""
        set_correlation_context(
            project_id=project_id,
            change_id=change_name,
            operation_id="evaluate_readiness",
        )

        checks: list[ReadinessCheck] = []
        unmet_reasons: list[str] = []

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
                    issue_valid, issue_reason = self.github_adapter.validate_issue_binding(
                        project.repository, effective_issue, github_repository=github_repo
                    )
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
                            name="github_issue_verification", passed=False, reason=reason,
                            details={"repository": project.repository, "issue_number": effective_issue},
                        )
                    )
                    unmet_reasons.append(reason)
                else:
                    checks.append(
                        ReadinessCheck(
                            name="durable_project_binding", passed=True,
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
        evaluation = ReadinessEvaluation(
            change_id=change_name,
            project_id=project_id,
            status=status,
            is_ready=is_ready,
            unmet_reasons=unmet_reasons,
            checks=checks,
            evaluated_at=now,
        )

        # Update change record in persistence if exists
        change_record = self.uow.changes.get_by_name(project_id, change_name)
        if change_record:
            change_record.last_readiness_status = status
            change_record.last_readiness_reasons = unmet_reasons
            change_record.status = ChangeStatus.READY if is_ready else ChangeStatus.DISCOVERED
            change_record.updated_at = now
            self.uow.changes.save(change_record)

        # Emit audit event and metric fact
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
