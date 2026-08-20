"""PostgreSQL repository implementations and transactional persistence."""

from __future__ import annotations

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from minime.db.models import (
    ChangeModel,
    EventModel,
    MetricFactModel,
    ProjectBindingModel,
    ProjectModel,
)
from minime.domain.enums import (
    ChangeStatus,
    EventType,
    ProjectStatus,
    ReadinessState,
)
from minime.domain.interfaces import (
    ChangeRepositoryInterface,
    EventRepositoryInterface,
    MetricFactRepositoryInterface,
    PersistenceUnitOfWork,
    ProjectBindingRepositoryInterface,
    ProjectRepositoryInterface,
)
from minime.domain.models import (
    Change,
    Event,
    MetricFact,
    Project,
    ProjectBinding,
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


class PostgresPersistenceUnitOfWork(PersistenceUnitOfWork):
    """Encapsulates a database session for atomic operations across repositories."""

    def __init__(self, session: Session):
        self.session = session
        self.projects = PostgresProjectRepository(session)
        self.changes = PostgresChangeRepository(session)
        self.bindings = PostgresProjectBindingRepository(session)
        self.events = PostgresEventRepository(session)
        self.metrics = PostgresMetricFactRepository(session)

    def commit(self) -> None:
        self.session.commit()

    def rollback(self) -> None:
        self.session.rollback()
