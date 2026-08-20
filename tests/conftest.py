"""Test fixtures and mock repositories for mini me tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from minime.domain.enums import JobStatus, ReviewStatus, ReviewVerdict
from minime.domain.interfaces import (
    ChangeRepositoryInterface,
    CheckResultRepositoryInterface,
    EventRepositoryInterface,
    JobLogRepositoryInterface,
    JobRepositoryInterface,
    MetricFactRepositoryInterface,
    PersistenceUnitOfWork,
    ProjectBindingRepositoryInterface,
    ProjectRepositoryInterface,
    ReviewFindingRepositoryInterface,
    ReviewRepositoryInterface,
)
from minime.domain.models import (
    Change,
    CheckResult,
    Event,
    Job,
    JobLog,
    MetricFact,
    Project,
    ProjectBinding,
    Review,
    ReviewFinding,
)


class InMemoryProjectRepository(ProjectRepositoryInterface):
    def __init__(self):
        self._store: dict[str, Project] = {}

    def save(self, project: Project) -> None:
        self._store[project.project_id] = project.model_copy(deep=True)

    def get_by_id(self, project_id: str) -> Project | None:
        p = self._store.get(project_id)
        return p.model_copy(deep=True) if p else None

    def list_all(self) -> list[Project]:
        return [p.model_copy(deep=True) for p in self._store.values()]


class InMemoryChangeRepository(ChangeRepositoryInterface):
    def __init__(self):
        self._store: dict[str, Change] = {}

    def save(self, change: Change) -> None:
        self._store[change.change_id] = change.model_copy(deep=True)

    def get_by_id(self, change_id: str) -> Change | None:
        c = self._store.get(change_id)
        return c.model_copy(deep=True) if c else None

    def get_by_name(self, project_id: str, name: str) -> Change | None:
        for c in self._store.values():
            if c.project_id == project_id and c.name == name:
                return c.model_copy(deep=True)
        return None

    def list_by_project(self, project_id: str) -> list[Change]:
        return [c.model_copy(deep=True) for c in self._store.values() if c.project_id == project_id]


class InMemoryProjectBindingRepository(ProjectBindingRepositoryInterface):
    def __init__(self):
        self._store: dict[str, ProjectBinding] = {}

    def save(self, binding: ProjectBinding) -> None:
        for existing in self._store.values():
            if (
                existing.project_id == binding.project_id
                and existing.openspec_change_name == binding.openspec_change_name
                and existing.binding_id != binding.binding_id
            ):
                raise ValueError(
                    f"Unique constraint violation: binding already exists for project '{binding.project_id}' "
                    f"and change '{binding.openspec_change_name}'."
                )
        self._store[binding.binding_id] = binding.model_copy(deep=True)

    def get_by_id(self, binding_id: str) -> ProjectBinding | None:
        b = self._store.get(binding_id)
        return b.model_copy(deep=True) if b else None

    def get_by_project_and_change(self, project_id: str, change_name: str) -> ProjectBinding | None:
        matches = [
            b
            for b in self._store.values()
            if b.project_id == project_id and b.openspec_change_name == change_name
        ]
        if len(matches) > 1:
            raise ValueError(
                f"Ambiguous bindings: {len(matches)} bindings found for project '{project_id}' "
                f"and change '{change_name}'."
            )
        return matches[0].model_copy(deep=True) if matches else None


class InMemoryEventRepository(EventRepositoryInterface):
    def __init__(self):
        self._store: list[Event] = []

    def save(self, event: Event) -> None:
        self._store.append(event.model_copy(deep=True))

    def list_events(
        self,
        project_id: str | None = None,
        change_id: str | None = None,
        limit: int = 100,
    ) -> list[Event]:
        res = self._store
        if project_id:
            res = [e for e in res if e.project_id == project_id]
        if change_id:
            res = [e for e in res if e.change_id == change_id]
        return [e.model_copy(deep=True) for e in reversed(res[-limit:])]


class InMemoryMetricFactRepository(MetricFactRepositoryInterface):
    def __init__(self):
        self._store: list[MetricFact] = []

    def save(self, fact: MetricFact) -> None:
        self._store.append(fact.model_copy(deep=True))

    def list_facts(
        self,
        project_id: str | None = None,
        change_id: str | None = None,
        metric_name: str | None = None,
        limit: int = 100,
    ) -> list[MetricFact]:
        res = self._store
        if project_id:
            res = [f for f in res if f.project_id == project_id]
        if change_id:
            res = [f for f in res if f.change_id == change_id]
        if metric_name:
            res = [f for f in res if f.metric_name == metric_name]
        return [f.model_copy(deep=True) for f in reversed(res[-limit:])]


class InMemoryJobRepository(JobRepositoryInterface):
    _valid_transitions: dict[JobStatus, set[JobStatus]] = {
        JobStatus.QUEUED: {JobStatus.RUNNING, JobStatus.CANCELLED, JobStatus.FAILED},
        JobStatus.RUNNING: {JobStatus.CHECKS_RUNNING, JobStatus.FAILED, JobStatus.CANCELLED},
        JobStatus.CHECKS_RUNNING: {
            JobStatus.CHECKS_PASSED,
            JobStatus.CHECKS_FAILED,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
        },
        JobStatus.CHECKS_PASSED: {
            JobStatus.REVIEW_RUNNING,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
        },
        JobStatus.CHECKS_FAILED: set(),
        JobStatus.REVIEW_RUNNING: {
            JobStatus.READY_TO_MERGE,
            JobStatus.CHANGES_REQUIRED,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
        },
        JobStatus.READY_TO_MERGE: set(),
        JobStatus.CHANGES_REQUIRED: set(),
        JobStatus.FAILED: set(),
        JobStatus.CANCELLED: set(),
    }

    def __init__(self):
        self._store: dict[str, Job] = {}

    def save(self, job: Job) -> None:
        self._store[job.job_id] = job.model_copy(deep=True)

    def get_by_id(self, job_id: str) -> Job | None:
        job = self._store.get(job_id)
        return job.model_copy(deep=True) if job else None

    def list_by_project(self, project_id: str, limit: int = 100) -> list[Job]:
        jobs = [j for j in self._store.values() if j.project_id == project_id]
        jobs.sort(key=lambda j: j.created_at, reverse=True)
        return [j.model_copy(deep=True) for j in jobs[:limit]]

    def transition(self, job_id: str, new_status: str, error_message: str | None = None) -> Job:
        job = self._store.get(job_id)
        if not job:
            raise ValueError(f"Job '{job_id}' not found.")
        target = JobStatus(new_status)
        if target not in self._valid_transitions[job.status]:
            raise ValueError(f"Invalid job status transition: {job.status.value} -> {target.value}.")
        updated = job.model_copy(update={"status": target, "error_message": error_message})
        self._store[job_id] = updated
        return updated.model_copy(deep=True)


class InMemoryJobLogRepository(JobLogRepositoryInterface):
    def __init__(self):
        self._store: list[JobLog] = []

    def save(self, log: JobLog) -> None:
        self._store.append(log.model_copy(deep=True))

    def list_by_job(self, job_id: str, limit: int = 500) -> list[JobLog]:
        logs = [log for log in self._store if log.job_id == job_id]
        return [log.model_copy(deep=True) for log in logs[:limit]]


class InMemoryCheckResultRepository(CheckResultRepositoryInterface):
    def __init__(self):
        self._store: list[CheckResult] = []

    def save(self, result: CheckResult) -> None:
        self._store.append(result.model_copy(deep=True))

    def list_by_job(self, job_id: str) -> list[CheckResult]:
        return [r.model_copy(deep=True) for r in self._store if r.job_id == job_id]


class InMemoryReviewRepository(ReviewRepositoryInterface):
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

    def __init__(self):
        self._store: dict[str, Review] = {}

    def save(self, review: Review) -> None:
        self._store[review.review_id] = review.model_copy(deep=True)

    def get_by_id(self, review_id: str) -> Review | None:
        rev = self._store.get(review_id)
        return rev.model_copy(deep=True) if rev else None

    def get_by_job_id(self, job_id: str) -> Review | None:
        reviews = [r for r in self._store.values() if r.job_id == job_id]
        reviews.sort(key=lambda r: r.created_at, reverse=True)
        return reviews[0].model_copy(deep=True) if reviews else None

    def list_by_project(self, project_id: str, limit: int = 100) -> list[Review]:
        reviews = [r for r in self._store.values() if r.project_id == project_id]
        reviews.sort(key=lambda r: r.created_at, reverse=True)
        return [r.model_copy(deep=True) for r in reviews[:limit]]

    def transition(
        self,
        review_id: str,
        new_status: str,
        verdict: str | None = None,
        summary: str | None = None,
        error_message: str | None = None,
    ) -> Review:
        rev = self._store.get(review_id)
        if not rev:
            raise ValueError(f"Review '{review_id}' not found.")
        target = ReviewStatus(new_status)
        if target not in self._valid_transitions[rev.status]:
            raise ValueError(
                f"Invalid review status transition: {rev.status.value} -> {target.value}."
            )
        update_dict: dict[str, object] = {"status": target}
        if verdict:
            update_dict["verdict"] = ReviewVerdict(verdict)
        if summary is not None:
            update_dict["summary"] = summary
        if error_message is not None:
            update_dict["error_message"] = error_message
        updated = rev.model_copy(update=update_dict)
        self._store[review_id] = updated
        return updated.model_copy(deep=True)


class InMemoryReviewFindingRepository(ReviewFindingRepositoryInterface):
    def __init__(self):
        self._store: list[ReviewFinding] = []

    def save(self, finding: ReviewFinding) -> None:
        self._store.append(finding.model_copy(deep=True))

    def list_by_review(self, review_id: str) -> list[ReviewFinding]:
        return [f.model_copy(deep=True) for f in self._store if f.review_id == review_id]


class InMemoryPersistenceUnitOfWork(PersistenceUnitOfWork):
    def __init__(self):
        self.projects = InMemoryProjectRepository()
        self.changes = InMemoryChangeRepository()
        self.bindings = InMemoryProjectBindingRepository()
        self.events = InMemoryEventRepository()
        self.metrics = InMemoryMetricFactRepository()
        self.jobs = InMemoryJobRepository()
        self.job_logs = InMemoryJobLogRepository()
        self.check_results = InMemoryCheckResultRepository()
        self.reviews = InMemoryReviewRepository()
        self.review_findings = InMemoryReviewFindingRepository()
        self.committed = False
        self.rolled_back = False

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True



@pytest.fixture
def in_memory_uow() -> InMemoryPersistenceUnitOfWork:
    return InMemoryPersistenceUnitOfWork()


def create_isolated_openspec_change(
    root: Path,
    change_name: str = "synthetic-change",
    proposal_content: str = "# Proposal\n",
    tasks_content: str = "# Tasks\n",
    design_content: str = "# Design\n",
    spec_content: str = "# Spec\n",
) -> Path:
    """Helper to create a fully isolated OpenSpec change directory with valid standard artifacts."""
    change_dir = root / "openspec" / "changes" / change_name
    change_dir.mkdir(parents=True, exist_ok=True)
    (change_dir / "proposal.md").write_text(proposal_content, encoding="utf-8")
    (change_dir / "tasks.md").write_text(tasks_content, encoding="utf-8")
    (change_dir / "design.md").write_text(design_content, encoding="utf-8")
    specs_dir = change_dir / "specs" / "feature"
    specs_dir.mkdir(parents=True, exist_ok=True)
    (specs_dir / "spec.md").write_text(spec_content, encoding="utf-8")
    return change_dir
