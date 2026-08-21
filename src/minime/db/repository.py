"""PostgreSQL repository implementations and transactional persistence."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from minime.db.models import (
    AuditFindingModel,
    AuditModel,
    CapacityWindowModel,
    ChangeModel,
    CheckResultModel,
    EventModel,
    GitOperationModel,
    JobLogModel,
    JobModel,
    MetricFactModel,
    ProjectBindingModel,
    ProjectModel,
    ProviderHealthModel,
    ReviewFindingModel,
    ReviewModel,
)
from minime.domain.enums import (
    PRIMARY_PROVIDERS,
    AuditFindingSeverity,
    AuditRiskLevel,
    AuditStatus,
    CapacitySignalSource,
    ChangeStatus,
    EventType,
    FindingSeverity,
    GitOperationStatus,
    JobStatus,
    ProjectStatus,
    ProviderHealthStatus,
    ProviderResultClass,
    ReadinessState,
    ReviewStatus,
    ReviewVerdict,
)
from minime.domain.interfaces import (
    AuditFindingRepositoryInterface,
    AuditRepositoryInterface,
    CapacityWindowRepositoryInterface,
    ChangeRepositoryInterface,
    CheckResultRepositoryInterface,
    EventRepositoryInterface,
    GitOperationRepositoryInterface,
    JobLogRepositoryInterface,
    JobRepositoryInterface,
    MetricFactRepositoryInterface,
    PersistenceUnitOfWork,
    ProjectBindingRepositoryInterface,
    ProjectRepositoryInterface,
    ProviderHealthRepositoryInterface,
    ReviewFindingRepositoryInterface,
    ReviewRepositoryInterface,
)
from minime.domain.models import (
    AuditFinding,
    AuditRecord,
    CapacityWindow,
    Change,
    CheckResult,
    Event,
    GitOperation,
    Job,
    JobLog,
    MetricFact,
    Project,
    ProjectBinding,
    ProviderHealth,
    Review,
    ReviewFinding,
    utc_now,
)


def project_model_to_domain(model: ProjectModel) -> Project:
    return Project(
        project_id=model.id,
        display_name=model.display_name,
        repository=model.repository,
        base_branch=model.base_branch,
        openspec_path=model.openspec_path,
        implementer=model.implementer,
        reviewer=model.reviewer,
        checks=model.checks or [],
        external_providers_allowed=model.external_providers_allowed or [],
        openrouter_drain_allowed=model.openrouter_drain_allowed,
        deployment_preview=model.deployment_preview or {},
        deployment_production=model.deployment_production or {},
        status=ProjectStatus(model.status),
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def change_model_to_domain(model: ChangeModel) -> Change:
    return Change(
        change_id=model.id,
        project_id=model.project_id,
        name=model.name,
        status=ChangeStatus(model.status),
        stage=model.stage,
        schema_name=model.schema_name,
        proposal_path=model.proposal_path,
        tasks_path=model.tasks_path,
        design_path=model.design_path,
        specs_paths=model.specs_paths or [],
        last_readiness_status=ReadinessState(model.last_readiness_status),
        last_readiness_reasons=model.last_readiness_reasons or [],
        discovered_at=model.discovered_at,
        updated_at=model.updated_at,
    )


def binding_model_to_domain(model: ProjectBindingModel) -> ProjectBinding:
    return ProjectBinding(
        binding_id=model.id,
        project_id=model.project_id,
        repository=model.repository,
        github_issue_number=model.github_issue_number,
        github_project_item_id=model.github_project_item_id,
        openspec_change_name=model.openspec_change_name,
        is_valid=model.is_valid,
        mismatch_reasons=model.mismatch_reasons or [],
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def event_model_to_domain(model: EventModel) -> Event:
    return Event(
        event_id=model.id,
        event_type=EventType(model.event_type),
        project_id=model.project_id,
        change_id=model.change_id,
        operation_id=model.operation_id,
        payload=model.payload or {},
        timestamp=model.timestamp,
    )


def fact_model_to_domain(model: MetricFactModel) -> MetricFact:
    return MetricFact(
        fact_id=model.id,
        metric_name=model.metric_name,
        project_id=model.project_id,
        change_id=model.change_id,
        stage=model.stage,
        duration_ms=model.duration_ms,
        fact_value=model.fact_value,
        details=model.details or {},
        recorded_at=model.recorded_at,
    )


def job_model_to_domain(model: JobModel) -> Job:
    return Job(
        job_id=model.id,
        project_id=model.project_id,
        change_name=model.change_name,
        status=JobStatus(model.status),
        implementer_role=model.implementer_role,
        candidate_sha=model.candidate_sha,
        base_sha=model.base_sha,
        error_message=model.error_message,
        waiting_provider=model.waiting_provider,
        capacity_block_reason=model.capacity_block_reason,
        recovery_blocked_reason=model.recovery_blocked_reason,
        expected_reset_at=model.expected_reset_at,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def provider_health_model_to_domain(model: ProviderHealthModel) -> ProviderHealth:
    return ProviderHealth(
        health_id=model.id,
        provider=model.provider,
        model=model.model,
        status=ProviderHealthStatus(model.status),
        consecutive_failures=model.consecutive_failures,
        last_result_class=ProviderResultClass(model.last_result_class)
        if model.last_result_class
        else None,
        last_error_summary=model.last_error_summary,
        last_success_at=model.last_success_at,
        last_failure_at=model.last_failure_at,
        updated_at=model.updated_at,
    )


def capacity_window_model_to_domain(model: CapacityWindowModel) -> CapacityWindow:
    return CapacityWindow(
        window_id=model.id,
        provider=model.provider,
        model=model.model,
        quota_exhausted_at=model.quota_exhausted_at,
        capacity_reset_at=model.capacity_reset_at,
        retry_after_seconds=model.retry_after_seconds,
        source_signal=CapacitySignalSource(model.source_signal)
        if model.source_signal
        else CapacitySignalSource.UNKNOWN,
        created_at=model.created_at,
    )


def git_operation_model_to_domain(model: GitOperationModel) -> GitOperation:
    return GitOperation(
        operation_id=model.id,
        job_id=model.job_id,
        project_id=model.project_id,
        worktree_path=model.worktree_path,
        operation_type=model.operation_type,
        pid=model.pid,
        status=GitOperationStatus(model.status),
        started_at=model.started_at,
        completed_at=model.completed_at,
    )


def job_log_model_to_domain(model: JobLogModel) -> JobLog:
    return JobLog(
        log_id=model.id,
        job_id=model.job_id,
        stream=model.stream,
        message=model.message,
        timestamp=model.timestamp,
    )


def check_result_model_to_domain(model: CheckResultModel) -> CheckResult:
    return CheckResult(
        result_id=model.id,
        job_id=model.job_id,
        check_name=model.check_name,
        command=model.command,
        exit_code=model.exit_code,
        duration_ms=model.duration_ms,
        output_snippet=model.output_snippet,
        created_at=model.created_at,
    )


def review_finding_model_to_domain(model: ReviewFindingModel) -> ReviewFinding:
    return ReviewFinding(
        finding_id=model.id,
        review_id=model.review_id,
        severity=FindingSeverity(model.severity),
        location=model.location,
        violated_requirement=model.violated_requirement,
        expected_correction=model.expected_correction,
        created_at=model.created_at,
    )


def review_model_to_domain(model: ReviewModel) -> Review:
    return Review(
        review_id=model.id,
        job_id=model.job_id,
        project_id=model.project_id,
        change_name=model.change_name,
        reviewer_role=model.reviewer_role,
        candidate_sha=model.candidate_sha,
        base_sha=model.base_sha,
        status=ReviewStatus(model.status),
        verdict=ReviewVerdict(model.verdict) if model.verdict else None,
        summary=model.summary,
        error_message=model.error_message,
        findings=[review_finding_model_to_domain(f) for f in (model.findings or [])],
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def audit_finding_model_to_domain(model: AuditFindingModel) -> AuditFinding:
    return AuditFinding(
        finding_id=model.id,
        audit_id=model.audit_id,
        severity=AuditFindingSeverity(model.severity),
        category=model.category,
        message=model.message,
        file=model.file,
        location=model.location,
        created_at=model.created_at,
    )


def audit_model_to_domain(model: AuditModel) -> AuditRecord:
    return AuditRecord(
        audit_id=model.id,
        job_id=model.job_id,
        project_id=model.project_id,
        change_name=model.change_name,
        provider=model.provider,
        model=model.model,
        candidate_sha=model.candidate_sha,
        base_sha=model.base_sha,
        review_id=model.review_id,
        review_verdict=ReviewVerdict(model.review_verdict) if model.review_verdict else None,
        status=AuditStatus(model.status),
        risk=AuditRiskLevel(model.risk) if model.risk else None,
        summary=model.summary,
        error_message=model.error_message,
        findings=[audit_finding_model_to_domain(f) for f in (model.findings or [])],
        created_at=model.created_at,
        updated_at=model.updated_at,
    )



class PostgresProjectRepository(ProjectRepositoryInterface):
    def __init__(self, session: Session):
        self.session = session

    def save(self, project: Project) -> None:
        existing = self.session.get(ProjectModel, project.project_id)
        if existing:
            existing.display_name = project.display_name
            existing.repository = project.repository
            existing.base_branch = project.base_branch
            existing.openspec_path = project.openspec_path
            existing.implementer = project.implementer
            existing.reviewer = project.reviewer
            existing.checks = project.checks
            existing.external_providers_allowed = project.external_providers_allowed
            existing.openrouter_drain_allowed = project.openrouter_drain_allowed
            existing.deployment_preview = project.deployment_preview
            existing.deployment_production = project.deployment_production
            existing.status = project.status.value
            existing.updated_at = project.updated_at
        else:
            model = ProjectModel(
                id=project.project_id,
                display_name=project.display_name,
                repository=project.repository,
                base_branch=project.base_branch,
                openspec_path=project.openspec_path,
                implementer=project.implementer,
                reviewer=project.reviewer,
                checks=project.checks,
                external_providers_allowed=project.external_providers_allowed,
                openrouter_drain_allowed=project.openrouter_drain_allowed,
                deployment_preview=project.deployment_preview,
                deployment_production=project.deployment_production,
                status=project.status.value,
                created_at=project.created_at,
                updated_at=project.updated_at,
            )
            self.session.add(model)

    def get_by_id(self, project_id: str) -> Project | None:
        model = self.session.get(ProjectModel, project_id)
        return project_model_to_domain(model) if model else None

    def list_all(self) -> list[Project]:
        stmt = select(ProjectModel).order_by(ProjectModel.id)
        models = self.session.scalars(stmt).all()
        return [project_model_to_domain(m) for m in models]


class PostgresChangeRepository(ChangeRepositoryInterface):
    def __init__(self, session: Session):
        self.session = session

    def save(self, change: Change) -> None:
        existing = self.session.get(ChangeModel, change.change_id)
        if existing:
            existing.name = change.name
            existing.status = change.status.value
            existing.stage = change.stage
            existing.schema_name = change.schema_name
            existing.proposal_path = change.proposal_path
            existing.tasks_path = change.tasks_path
            existing.design_path = change.design_path
            existing.specs_paths = change.specs_paths
            existing.last_readiness_status = change.last_readiness_status.value
            existing.last_readiness_reasons = change.last_readiness_reasons
            existing.updated_at = change.updated_at
        else:
            model = ChangeModel(
                id=change.change_id,
                project_id=change.project_id,
                name=change.name,
                status=change.status.value,
                stage=change.stage,
                schema_name=change.schema_name,
                proposal_path=change.proposal_path,
                tasks_path=change.tasks_path,
                design_path=change.design_path,
                specs_paths=change.specs_paths,
                last_readiness_status=change.last_readiness_status.value,
                last_readiness_reasons=change.last_readiness_reasons,
                discovered_at=change.discovered_at,
                updated_at=change.updated_at,
            )
            self.session.add(model)

    def get_by_id(self, change_id: str) -> Change | None:
        model = self.session.get(ChangeModel, change_id)
        return change_model_to_domain(model) if model else None

    def get_by_name(self, project_id: str, name: str) -> Change | None:
        stmt = select(ChangeModel).where(
            ChangeModel.project_id == project_id, ChangeModel.name == name
        )
        model = self.session.scalars(stmt).first()
        return change_model_to_domain(model) if model else None

    def list_by_project(self, project_id: str) -> list[Change]:
        stmt = (
            select(ChangeModel)
            .where(ChangeModel.project_id == project_id)
            .order_by(ChangeModel.discovered_at)
        )
        models = self.session.scalars(stmt).all()
        return [change_model_to_domain(m) for m in models]


class PostgresProjectBindingRepository(ProjectBindingRepositoryInterface):
    def __init__(self, session: Session):
        self.session = session

    def save(self, binding: ProjectBinding) -> None:
        existing = self.session.get(ProjectBindingModel, binding.binding_id)
        if existing:
            existing.repository = binding.repository
            existing.github_issue_number = binding.github_issue_number
            existing.github_project_item_id = binding.github_project_item_id
            existing.openspec_change_name = binding.openspec_change_name
            existing.is_valid = binding.is_valid
            existing.mismatch_reasons = binding.mismatch_reasons
            existing.updated_at = binding.updated_at
        else:
            model = ProjectBindingModel(
                id=binding.binding_id,
                project_id=binding.project_id,
                repository=binding.repository,
                github_issue_number=binding.github_issue_number,
                github_project_item_id=binding.github_project_item_id,
                openspec_change_name=binding.openspec_change_name,
                is_valid=binding.is_valid,
                mismatch_reasons=binding.mismatch_reasons,
                created_at=binding.created_at,
                updated_at=binding.updated_at,
            )
            self.session.add(model)

    def get_by_id(self, binding_id: str) -> ProjectBinding | None:
        model = self.session.get(ProjectBindingModel, binding_id)
        return binding_model_to_domain(model) if model else None

    def get_by_project_and_change(self, project_id: str, change_name: str) -> ProjectBinding | None:
        stmt = select(ProjectBindingModel).where(
            ProjectBindingModel.project_id == project_id,
            ProjectBindingModel.openspec_change_name == change_name,
        )
        models = self.session.scalars(stmt).all()
        if len(models) > 1:
            raise ValueError(
                f"Ambiguous bindings: {len(models)} bindings found for project '{project_id}' "
                f"and change '{change_name}'."
            )
        return binding_model_to_domain(models[0]) if models else None


class PostgresEventRepository(EventRepositoryInterface):
    def __init__(self, session: Session):
        self.session = session

    def save(self, event: Event) -> None:
        model = EventModel(
            id=event.event_id,
            event_type=event.event_type.value,
            project_id=event.project_id,
            change_id=event.change_id,
            operation_id=event.operation_id,
            payload=event.payload,
            timestamp=event.timestamp,
        )
        self.session.add(model)

    def list_events(
        self,
        project_id: str | None = None,
        change_id: str | None = None,
        limit: int = 100,
    ) -> list[Event]:
        stmt = select(EventModel)
        if project_id:
            stmt = stmt.where(EventModel.project_id == project_id)
        if change_id:
            stmt = stmt.where(EventModel.change_id == change_id)
        stmt = stmt.order_by(desc(EventModel.timestamp)).limit(limit)
        models = self.session.scalars(stmt).all()
        return [event_model_to_domain(m) for m in models]


class PostgresMetricFactRepository(MetricFactRepositoryInterface):
    def __init__(self, session: Session):
        self.session = session

    def save(self, fact: MetricFact) -> None:
        model = MetricFactModel(
            id=fact.fact_id,
            metric_name=fact.metric_name,
            project_id=fact.project_id,
            change_id=fact.change_id,
            stage=fact.stage,
            duration_ms=fact.duration_ms,
            fact_value=fact.fact_value,
            details=fact.details,
            recorded_at=fact.recorded_at,
        )
        self.session.add(model)

    def list_facts(
        self,
        project_id: str | None = None,
        change_id: str | None = None,
        metric_name: str | None = None,
        limit: int = 100,
    ) -> list[MetricFact]:
        stmt = select(MetricFactModel)
        if project_id:
            stmt = stmt.where(MetricFactModel.project_id == project_id)
        if change_id:
            stmt = stmt.where(MetricFactModel.change_id == change_id)
        if metric_name:
            stmt = stmt.where(MetricFactModel.metric_name == metric_name)
        stmt = stmt.order_by(desc(MetricFactModel.recorded_at)).limit(limit)
        models = self.session.scalars(stmt).all()
        return [fact_model_to_domain(m) for m in models]


class PostgresJobRepository(JobRepositoryInterface):
    _valid_transitions: dict[JobStatus, set[JobStatus]] = {
        JobStatus.QUEUED: {
            JobStatus.RUNNING,
            JobStatus.WAITING_CAPACITY,
            JobStatus.CANCELLED,
            JobStatus.FAILED,
        },
        JobStatus.RUNNING: {
            JobStatus.CHECKS_RUNNING,
            JobStatus.QUEUED,
            JobStatus.WAITING_CAPACITY,
            JobStatus.RECOVERY_BLOCKED,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
        },
        JobStatus.CHECKS_RUNNING: {
            JobStatus.CHECKS_PASSED,
            JobStatus.CHECKS_FAILED,
            JobStatus.QUEUED,
            JobStatus.WAITING_CAPACITY,
            JobStatus.RECOVERY_BLOCKED,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
        },
        JobStatus.CHECKS_PASSED: {
            JobStatus.REVIEW_RUNNING,
            JobStatus.WAITING_CAPACITY,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
        },
        JobStatus.CHECKS_FAILED: set(),
        JobStatus.REVIEW_RUNNING: {
            JobStatus.AUDIT_RUNNING,
            JobStatus.CHANGES_REQUIRED,
            JobStatus.CHECKS_PASSED,
            JobStatus.QUEUED,
            JobStatus.WAITING_CAPACITY,
            JobStatus.RECOVERY_BLOCKED,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
        },
        JobStatus.AUDIT_RUNNING: {
            JobStatus.READY_TO_MERGE,
            JobStatus.AUDIT_BLOCKED,
            JobStatus.CHECKS_PASSED,
            JobStatus.QUEUED,
            JobStatus.WAITING_CAPACITY,
            JobStatus.RECOVERY_BLOCKED,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
        },
        JobStatus.WAITING_CAPACITY: {
            JobStatus.RUNNING,
            JobStatus.CHECKS_RUNNING,
            JobStatus.REVIEW_RUNNING,
            JobStatus.AUDIT_RUNNING,
            JobStatus.RECOVERY_BLOCKED,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
        },
        JobStatus.RECOVERY_BLOCKED: {
            JobStatus.WAITING_CAPACITY,
            JobStatus.RUNNING,
            JobStatus.REVIEW_RUNNING,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
        },
        JobStatus.READY_TO_MERGE: set(),
        JobStatus.AUDIT_BLOCKED: set(),
        JobStatus.CHANGES_REQUIRED: set(),
        JobStatus.FAILED: set(),
        JobStatus.CANCELLED: set(),
    }

    def __init__(self, session: Session):
        self.session = session

    def save(self, job: Job) -> None:
        existing = self.session.get(JobModel, job.job_id)
        if existing:
            existing.status = job.status.value
            existing.implementer_role = job.implementer_role
            existing.candidate_sha = job.candidate_sha
            existing.base_sha = job.base_sha
            existing.error_message = job.error_message
            existing.waiting_provider = job.waiting_provider
            existing.capacity_block_reason = job.capacity_block_reason
            existing.recovery_blocked_reason = job.recovery_blocked_reason
            existing.expected_reset_at = job.expected_reset_at
            existing.updated_at = job.updated_at
        else:
            model = JobModel(
                id=job.job_id,
                project_id=job.project_id,
                change_name=job.change_name,
                status=job.status.value,
                implementer_role=job.implementer_role,
                candidate_sha=job.candidate_sha,
                base_sha=job.base_sha,
                error_message=job.error_message,
                waiting_provider=job.waiting_provider,
                capacity_block_reason=job.capacity_block_reason,
                recovery_blocked_reason=job.recovery_blocked_reason,
                expected_reset_at=job.expected_reset_at,
                created_at=job.created_at,
                updated_at=job.updated_at,
            )
            self.session.add(model)

    def get_by_id(self, job_id: str) -> Job | None:
        model = self.session.get(JobModel, job_id)
        return job_model_to_domain(model) if model else None

    def list_by_project(self, project_id: str, limit: int = 100) -> list[Job]:
        stmt = (
            select(JobModel)
            .where(JobModel.project_id == project_id)
            .order_by(desc(JobModel.created_at))
            .limit(limit)
        )
        models = self.session.scalars(stmt).all()
        return [job_model_to_domain(m) for m in models]

    def list_active_jobs(self) -> list[Job]:
        active_statuses = [
            JobStatus.QUEUED.value,
            JobStatus.RUNNING.value,
            JobStatus.CHECKS_RUNNING.value,
            JobStatus.CHECKS_PASSED.value,
            JobStatus.REVIEW_RUNNING.value,
            JobStatus.AUDIT_RUNNING.value,
            JobStatus.WAITING_CAPACITY.value,
            JobStatus.RECOVERY_BLOCKED.value,
        ]
        stmt = (
            select(JobModel)
            .where(JobModel.status.in_(active_statuses))
            .order_by(JobModel.created_at)
        )
        models = self.session.scalars(stmt).all()
        return [job_model_to_domain(m) for m in models]

    def transition(self, job_id: str, new_status: str, error_message: str | None = None) -> Job:
        model = self.session.get(JobModel, job_id)
        if not model:
            raise ValueError(f"Job '{job_id}' not found.")
        current = JobStatus(model.status)
        target = JobStatus(new_status)
        if target not in self._valid_transitions[current]:
            raise ValueError(f"Invalid job status transition: {current.value} -> {target.value}.")
        model.status = target.value
        model.error_message = error_message
        model.updated_at = utc_now()
        return job_model_to_domain(model)

    def set_waiting_capacity(
        self,
        job_id: str,
        waiting_provider: str,
        reason: str,
        expected_reset_at: datetime | None = None,
    ) -> Job:
        model = self.session.get(JobModel, job_id)
        if not model:
            raise ValueError(f"Job '{job_id}' not found.")
        current = JobStatus(model.status)
        target = JobStatus.WAITING_CAPACITY
        if target not in self._valid_transitions[current]:
            raise ValueError(f"Invalid job status transition: {current.value} -> {target.value}.")
        model.status = target.value
        model.waiting_provider = waiting_provider
        model.capacity_block_reason = reason
        model.expected_reset_at = expected_reset_at
        model.updated_at = utc_now()
        return job_model_to_domain(model)

    def set_recovery_blocked(self, job_id: str, reason: str) -> Job:
        model = self.session.get(JobModel, job_id)
        if not model:
            raise ValueError(f"Job '{job_id}' not found.")
        current = JobStatus(model.status)
        target = JobStatus.RECOVERY_BLOCKED
        if target not in self._valid_transitions[current]:
            raise ValueError(f"Invalid job status transition: {current.value} -> {target.value}.")
        model.status = target.value
        model.recovery_blocked_reason = reason
        model.updated_at = utc_now()
        return job_model_to_domain(model)


class PostgresJobLogRepository(JobLogRepositoryInterface):
    def __init__(self, session: Session):
        self.session = session

    def save(self, log: JobLog) -> None:
        self.session.add(
            JobLogModel(
                id=log.log_id,
                job_id=log.job_id,
                stream=log.stream,
                message=log.message,
                timestamp=log.timestamp,
            )
        )

    def list_by_job(self, job_id: str, limit: int = 500) -> list[JobLog]:
        stmt = (
            select(JobLogModel)
            .where(JobLogModel.job_id == job_id)
            .order_by(JobLogModel.timestamp)
            .limit(limit)
        )
        models = self.session.scalars(stmt).all()
        return [job_log_model_to_domain(m) for m in models]


class PostgresCheckResultRepository(CheckResultRepositoryInterface):
    def __init__(self, session: Session):
        self.session = session

    def save(self, result: CheckResult) -> None:
        self.session.add(
            CheckResultModel(
                id=result.result_id,
                job_id=result.job_id,
                check_name=result.check_name,
                command=result.command,
                exit_code=result.exit_code,
                duration_ms=result.duration_ms,
                output_snippet=result.output_snippet,
                created_at=result.created_at,
            )
        )

    def list_by_job(self, job_id: str) -> list[CheckResult]:
        stmt = (
            select(CheckResultModel)
            .where(CheckResultModel.job_id == job_id)
            .order_by(CheckResultModel.created_at)
        )
        models = self.session.scalars(stmt).all()
        return [check_result_model_to_domain(m) for m in models]


class PostgresReviewRepository(ReviewRepositoryInterface):
    _valid_transitions: dict[ReviewStatus, set[ReviewStatus]] = {
        ReviewStatus.REVIEW_PENDING: {
            ReviewStatus.REVIEW_RUNNING,
            ReviewStatus.REVIEW_FAILED,
            ReviewStatus.REVIEW_TIMED_OUT,
        },
        ReviewStatus.REVIEW_RUNNING: {
            ReviewStatus.REVIEW_COMPLETED,
            ReviewStatus.REVIEW_FAILED,
            ReviewStatus.REVIEW_TIMED_OUT,
        },
        ReviewStatus.REVIEW_COMPLETED: set(),
        ReviewStatus.REVIEW_FAILED: set(),
        ReviewStatus.REVIEW_TIMED_OUT: set(),
    }

    def __init__(self, session: Session):
        self.session = session

    def save(self, review: Review) -> None:
        existing = self.session.get(ReviewModel, review.review_id)
        if existing:
            existing.status = review.status.value
            existing.verdict = review.verdict.value if review.verdict else None
            existing.summary = review.summary
            existing.error_message = review.error_message
            existing.updated_at = review.updated_at
        else:
            model = ReviewModel(
                id=review.review_id,
                job_id=review.job_id,
                project_id=review.project_id,
                change_name=review.change_name,
                reviewer_role=review.reviewer_role,
                candidate_sha=review.candidate_sha,
                base_sha=review.base_sha,
                status=review.status.value,
                verdict=review.verdict.value if review.verdict else None,
                summary=review.summary,
                error_message=review.error_message,
                created_at=review.created_at,
                updated_at=review.updated_at,
            )
            self.session.add(model)

    def get_by_id(self, review_id: str) -> Review | None:
        model = self.session.get(ReviewModel, review_id)
        return review_model_to_domain(model) if model else None

    def get_by_job_id(self, job_id: str) -> Review | None:
        stmt = (
            select(ReviewModel)
            .where(ReviewModel.job_id == job_id)
            .order_by(desc(ReviewModel.created_at))
            .limit(1)
        )
        model = self.session.scalars(stmt).first()
        return review_model_to_domain(model) if model else None

    def list_by_project(self, project_id: str, limit: int = 100) -> list[Review]:
        stmt = (
            select(ReviewModel)
            .where(ReviewModel.project_id == project_id)
            .order_by(desc(ReviewModel.created_at))
            .limit(limit)
        )
        models = self.session.scalars(stmt).all()
        return [review_model_to_domain(m) for m in models]

    def transition(
        self,
        review_id: str,
        new_status: str,
        verdict: str | None = None,
        summary: str | None = None,
        error_message: str | None = None,
    ) -> Review:
        model = self.session.get(ReviewModel, review_id)
        if not model:
            raise ValueError(f"Review '{review_id}' not found.")
        current = ReviewStatus(model.status)
        target = ReviewStatus(new_status)
        if target not in self._valid_transitions[current]:
            raise ValueError(
                f"Invalid review status transition: {current.value} -> {target.value}."
            )
        model.status = target.value
        if verdict:
            model.verdict = ReviewVerdict(verdict).value
        if summary is not None:
            model.summary = summary
        if error_message is not None:
            model.error_message = error_message
        model.updated_at = utc_now()
        return review_model_to_domain(model)


class PostgresReviewFindingRepository(ReviewFindingRepositoryInterface):
    def __init__(self, session: Session):
        self.session = session

    def save(self, finding: ReviewFinding) -> None:
        self.session.add(
            ReviewFindingModel(
                id=finding.finding_id,
                review_id=finding.review_id,
                severity=finding.severity.value,
                location=finding.location,
                violated_requirement=finding.violated_requirement,
                expected_correction=finding.expected_correction,
                created_at=finding.created_at,
            )
        )

    def list_by_review(self, review_id: str) -> list[ReviewFinding]:
        stmt = (
            select(ReviewFindingModel)
            .where(ReviewFindingModel.review_id == review_id)
            .order_by(ReviewFindingModel.created_at)
        )
        models = self.session.scalars(stmt).all()
        return [review_finding_model_to_domain(m) for m in models]


class PostgresAuditRepository(AuditRepositoryInterface):
    _valid_transitions: dict[AuditStatus, set[AuditStatus]] = {
        AuditStatus.AUDIT_PENDING: {
            AuditStatus.AUDIT_RUNNING,
            AuditStatus.AUDIT_FAILED,
            AuditStatus.AUDIT_TIMED_OUT,
        },
        AuditStatus.AUDIT_RUNNING: {
            AuditStatus.AUDIT_COMPLETED,
            AuditStatus.AUDIT_BLOCKED,
            AuditStatus.AUDIT_FAILED,
            AuditStatus.AUDIT_TIMED_OUT,
        },
        AuditStatus.AUDIT_COMPLETED: set(),
        AuditStatus.AUDIT_BLOCKED: set(),
        AuditStatus.AUDIT_FAILED: set(),
        AuditStatus.AUDIT_TIMED_OUT: set(),
    }

    def __init__(self, session: Session):
        self.session = session

    def save(self, audit: AuditRecord) -> None:
        existing = self.session.get(AuditModel, audit.audit_id)
        if existing:
            existing.status = audit.status.value
            existing.risk = audit.risk.value if audit.risk else None
            existing.summary = audit.summary
            existing.error_message = audit.error_message
            existing.updated_at = audit.updated_at
        else:
            self.session.add(
                AuditModel(
                    id=audit.audit_id,
                    job_id=audit.job_id,
                    project_id=audit.project_id,
                    change_name=audit.change_name,
                    provider=audit.provider,
                    model=audit.model,
                    candidate_sha=audit.candidate_sha,
                    base_sha=audit.base_sha,
                    review_id=audit.review_id,
                    review_verdict=audit.review_verdict.value
                    if audit.review_verdict
                    else None,
                    status=audit.status.value,
                    risk=audit.risk.value if audit.risk else None,
                    summary=audit.summary,
                    error_message=audit.error_message,
                    created_at=audit.created_at,
                    updated_at=audit.updated_at,
                )
            )

    def get_by_id(self, audit_id: str) -> AuditRecord | None:
        model = self.session.get(AuditModel, audit_id)
        return audit_model_to_domain(model) if model else None

    def get_by_job_id(self, job_id: str) -> AuditRecord | None:
        stmt = (
            select(AuditModel)
            .where(AuditModel.job_id == job_id)
            .order_by(desc(AuditModel.created_at))
            .limit(1)
        )
        model = self.session.scalars(stmt).first()
        return audit_model_to_domain(model) if model else None

    def list_by_project(self, project_id: str, limit: int = 100) -> list[AuditRecord]:
        stmt = (
            select(AuditModel)
            .where(AuditModel.project_id == project_id)
            .order_by(desc(AuditModel.created_at))
            .limit(limit)
        )
        models = self.session.scalars(stmt).all()
        return [audit_model_to_domain(m) for m in models]

    def transition(
        self,
        audit_id: str,
        new_status: str,
        risk: str | None = None,
        summary: str | None = None,
        error_message: str | None = None,
    ) -> AuditRecord:
        model = self.session.get(AuditModel, audit_id)
        if not model:
            raise ValueError(f"Audit '{audit_id}' not found.")
        current = AuditStatus(model.status)
        target = AuditStatus(new_status)
        if target not in self._valid_transitions[current]:
            raise ValueError(
                f"Invalid audit status transition: {current.value} -> {target.value}."
            )
        model.status = target.value
        if risk:
            model.risk = AuditRiskLevel(risk).value
        if summary is not None:
            model.summary = summary
        if error_message is not None:
            model.error_message = error_message
        model.updated_at = utc_now()
        return audit_model_to_domain(model)


class PostgresAuditFindingRepository(AuditFindingRepositoryInterface):
    def __init__(self, session: Session):
        self.session = session

    def save(self, finding: AuditFinding) -> None:
        self.session.add(
            AuditFindingModel(
                id=finding.finding_id,
                audit_id=finding.audit_id,
                severity=finding.severity.value,
                category=finding.category,
                message=finding.message,
                file=finding.file,
                location=finding.location,
                created_at=finding.created_at,
            )
        )

    def list_by_audit(self, audit_id: str) -> list[AuditFinding]:
        stmt = (
            select(AuditFindingModel)
            .where(AuditFindingModel.audit_id == audit_id)
            .order_by(AuditFindingModel.created_at)
        )
        models = self.session.scalars(stmt).all()
        return [audit_finding_model_to_domain(m) for m in models]


class PostgresProviderHealthRepository(ProviderHealthRepositoryInterface):
    def __init__(self, session: Session):
        self.session = session

    def _validate_primary_provider(self, provider: str) -> None:
        if provider not in PRIMARY_PROVIDERS:
            raise ValueError(
                f"Invalid primary provider '{provider}'. "
                f"005 capacity tracking is restricted strictly to {PRIMARY_PROVIDERS}."
            )

    def save(self, health: ProviderHealth) -> None:
        health.validate_primary()
        existing = self.session.scalars(
            select(ProviderHealthModel).where(ProviderHealthModel.provider == health.provider)
        ).first()
        if existing:
            existing.model = health.model
            existing.status = health.status.value
            existing.consecutive_failures = health.consecutive_failures
            existing.last_result_class = (
                health.last_result_class.value if health.last_result_class else None
            )
            existing.last_error_summary = health.last_error_summary
            existing.last_success_at = health.last_success_at
            existing.last_failure_at = health.last_failure_at
            existing.updated_at = health.updated_at
        else:
            model = ProviderHealthModel(
                id=health.health_id,
                provider=health.provider,
                model=health.model,
                status=health.status.value,
                consecutive_failures=health.consecutive_failures,
                last_result_class=health.last_result_class.value
                if health.last_result_class
                else None,
                last_error_summary=health.last_error_summary,
                last_success_at=health.last_success_at,
                last_failure_at=health.last_failure_at,
                updated_at=health.updated_at,
            )
            self.session.add(model)

    def get_by_provider(self, provider: str) -> ProviderHealth | None:
        self._validate_primary_provider(provider)
        stmt = select(ProviderHealthModel).where(ProviderHealthModel.provider == provider)
        model = self.session.scalars(stmt).first()
        return provider_health_model_to_domain(model) if model else None

    def list_all(self) -> list[ProviderHealth]:
        stmt = select(ProviderHealthModel).order_by(ProviderHealthModel.provider)
        models = self.session.scalars(stmt).all()
        return [provider_health_model_to_domain(m) for m in models]

    def update_health(
        self,
        provider: str,
        status: str,
        result_class: str | None = None,
        error_summary: str | None = None,
        consecutive_failures: int | None = None,
    ) -> ProviderHealth:
        self._validate_primary_provider(provider)
        model = self.session.scalars(
            select(ProviderHealthModel).where(ProviderHealthModel.provider == provider)
        ).first()
        now = utc_now()
        target_status = ProviderHealthStatus(status)
        target_result_class = ProviderResultClass(result_class) if result_class else None

        if not model:
            init_failures = (
                consecutive_failures
                if consecutive_failures is not None
                else (0 if target_status == ProviderHealthStatus.AVAILABLE else 1)
            )
            model = ProviderHealthModel(
                id=f"ph-{provider}",
                provider=provider,
                status=target_status.value,
                consecutive_failures=init_failures,
                last_result_class=target_result_class.value if target_result_class else None,
                last_error_summary=error_summary,
                last_success_at=now if target_status == ProviderHealthStatus.AVAILABLE else None,
                last_failure_at=now if target_status != ProviderHealthStatus.AVAILABLE else None,
                updated_at=now,
            )
            self.session.add(model)
        else:
            model.status = target_status.value
            if target_result_class:
                model.last_result_class = target_result_class.value
            if error_summary is not None:
                model.last_error_summary = error_summary
            if consecutive_failures is not None:
                model.consecutive_failures = consecutive_failures
            elif target_status == ProviderHealthStatus.AVAILABLE:
                model.consecutive_failures = 0
            else:
                model.consecutive_failures += 1

            if target_status == ProviderHealthStatus.AVAILABLE and target_result_class == ProviderResultClass.SUCCESS:
                model.last_success_at = now
            elif target_result_class and target_result_class != ProviderResultClass.SUCCESS:
                model.last_failure_at = now

            model.updated_at = now

        return provider_health_model_to_domain(model)


class PostgresCapacityWindowRepository(CapacityWindowRepositoryInterface):
    def __init__(self, session: Session):
        self.session = session

    def _validate_primary_provider(self, provider: str) -> None:
        if provider not in PRIMARY_PROVIDERS:
            raise ValueError(
                f"Invalid primary provider '{provider}'. "
                f"005 capacity windows are restricted strictly to {PRIMARY_PROVIDERS}."
            )

    def save(self, window: CapacityWindow) -> None:
        window.validate_primary()
        model = CapacityWindowModel(
            id=window.window_id,
            provider=window.provider,
            model=window.model,
            quota_exhausted_at=window.quota_exhausted_at,
            capacity_reset_at=window.capacity_reset_at,
            retry_after_seconds=window.retry_after_seconds,
            source_signal=window.source_signal.value,
            created_at=window.created_at,
        )
        self.session.add(model)

    def get_latest_for_provider(self, provider: str) -> CapacityWindow | None:
        self._validate_primary_provider(provider)
        stmt = (
            select(CapacityWindowModel)
            .where(CapacityWindowModel.provider == provider)
            .order_by(desc(CapacityWindowModel.quota_exhausted_at))
            .limit(1)
        )
        model = self.session.scalars(stmt).first()
        return capacity_window_model_to_domain(model) if model else None

    def list_by_provider(self, provider: str, limit: int = 50) -> list[CapacityWindow]:
        self._validate_primary_provider(provider)
        stmt = (
            select(CapacityWindowModel)
            .where(CapacityWindowModel.provider == provider)
            .order_by(desc(CapacityWindowModel.quota_exhausted_at))
            .limit(limit)
        )
        models = self.session.scalars(stmt).all()
        return [capacity_window_model_to_domain(m) for m in models]


class PostgresGitOperationRepository(GitOperationRepositoryInterface):
    def __init__(self, session: Session):
        self.session = session

    def save(self, operation: GitOperation) -> None:
        existing = self.session.get(GitOperationModel, operation.operation_id)
        if existing:
            existing.job_id = operation.job_id
            existing.project_id = operation.project_id
            existing.worktree_path = operation.worktree_path
            existing.operation_type = operation.operation_type
            existing.pid = operation.pid
            existing.status = operation.status.value
            existing.started_at = operation.started_at
            existing.completed_at = operation.completed_at
        else:
            model = GitOperationModel(
                id=operation.operation_id,
                job_id=operation.job_id,
                project_id=operation.project_id,
                worktree_path=operation.worktree_path,
                operation_type=operation.operation_type,
                pid=operation.pid,
                status=operation.status.value,
                started_at=operation.started_at,
                completed_at=operation.completed_at,
            )
            self.session.add(model)

    def get_by_id(self, operation_id: str) -> GitOperation | None:
        model = self.session.get(GitOperationModel, operation_id)
        return git_operation_model_to_domain(model) if model else None

    def list_by_job(self, job_id: str) -> list[GitOperation]:
        stmt = (
            select(GitOperationModel)
            .where(GitOperationModel.job_id == job_id)
            .order_by(desc(GitOperationModel.started_at))
        )
        models = self.session.scalars(stmt).all()
        return [git_operation_model_to_domain(m) for m in models]

    def list_by_worktree(self, worktree_path: str) -> list[GitOperation]:
        stmt = (
            select(GitOperationModel)
            .where(GitOperationModel.worktree_path == worktree_path)
            .order_by(desc(GitOperationModel.started_at))
        )
        models = self.session.scalars(stmt).all()
        return [git_operation_model_to_domain(m) for m in models]

    def update_status(
        self,
        operation_id: str,
        status: GitOperationStatus,
        completed_at: datetime | None = None,
    ) -> GitOperation | None:
        model = self.session.get(GitOperationModel, operation_id)
        if not model:
            return None
        model.status = status.value
        if completed_at:
            model.completed_at = completed_at
        return git_operation_model_to_domain(model)


class PostgresPersistenceUnitOfWork(PersistenceUnitOfWork):
    """Encapsulates a database session for atomic operations across repositories."""

    def __init__(self, session: Session):
        self.session = session
        self.projects = PostgresProjectRepository(session)
        self.changes = PostgresChangeRepository(session)
        self.bindings = PostgresProjectBindingRepository(session)
        self.events = PostgresEventRepository(session)
        self.metrics = PostgresMetricFactRepository(session)
        self.jobs = PostgresJobRepository(session)
        self.job_logs = PostgresJobLogRepository(session)
        self.check_results = PostgresCheckResultRepository(session)
        self.reviews = PostgresReviewRepository(session)
        self.review_findings = PostgresReviewFindingRepository(session)
        self.audits = PostgresAuditRepository(session)
        self.audit_findings = PostgresAuditFindingRepository(session)
        self.provider_health = PostgresProviderHealthRepository(session)
        self.capacity_windows = PostgresCapacityWindowRepository(session)
        self.git_operations = PostgresGitOperationRepository(session)

    def commit(self) -> None:
        self.session.commit()

    def rollback(self) -> None:
        self.session.rollback()
