"""Domain interfaces for repositories and external adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

from minime.domain.enums import (
    ExternalActionStatus,
    GitOperationStatus,
    HumanGate,
    OrchestrationStage,
    OrchestrationStopOutcome,
)
from minime.domain.models import (
    AuditFinding,
    AuditRecord,
    BlockerClaim,
    BudgetLedgerEntry,
    BudgetReservation,
    CandidateAuthorship,
    CandidateManifest,
    CapacityWindow,
    Change,
    CheckResult,
    Event,
    EvidenceDiagnostic,
    GitOperation,
    Job,
    JobAttempt,
    JobHandoff,
    JobLog,
    MetricFact,
    OpenRouterBudgetPolicy,
    OpenRouterPricingSnapshot,
    OrchestrationCandidate,
    OrchestrationExternalAction,
    OrchestrationRun,
    OrchestrationStageEvent,
    PreviewSession,
    Project,
    ProjectBinding,
    ProviderHealth,
    Review,
    ReviewFinding,
    ValidationRun,
)


class ProjectRepositoryInterface(ABC):
    @abstractmethod
    def save(self, project: Project) -> None: ...

    @abstractmethod
    def get_by_id(self, project_id: str) -> Project | None: ...

    @abstractmethod
    def list_all(self) -> list[Project]: ...


class ChangeRepositoryInterface(ABC):
    @abstractmethod
    def save(self, change: Change) -> None: ...

    @abstractmethod
    def get_by_id(self, change_id: str) -> Change | None: ...

    @abstractmethod
    def get_by_name(self, project_id: str, name: str) -> Change | None: ...

    @abstractmethod
    def list_by_project(self, project_id: str) -> list[Change]: ...


class ProjectBindingRepositoryInterface(ABC):
    @abstractmethod
    def save(self, binding: ProjectBinding) -> None: ...

    @abstractmethod
    def get_by_id(self, binding_id: str) -> ProjectBinding | None: ...

    @abstractmethod
    def get_by_project_and_change(
        self, project_id: str, change_name: str
    ) -> ProjectBinding | None: ...


class EventRepositoryInterface(ABC):
    @abstractmethod
    def save(self, event: Event) -> None: ...

    @abstractmethod
    def list_events(
        self,
        project_id: str | None = None,
        change_id: str | None = None,
        limit: int = 100,
    ) -> list[Event]: ...


class MetricFactRepositoryInterface(ABC):
    @abstractmethod
    def save(self, fact: MetricFact) -> None: ...

    @abstractmethod
    def list_facts(
        self,
        project_id: str | None = None,
        change_id: str | None = None,
        metric_name: str | None = None,
        limit: int = 100,
    ) -> list[MetricFact]: ...


class JobRepositoryInterface(ABC):
    @abstractmethod
    def save(self, job: Job) -> None: ...

    @abstractmethod
    def get_by_id(self, job_id: str) -> Job | None: ...

    @abstractmethod
    def list_by_project(self, project_id: str, limit: int = 100) -> list[Job]: ...

    @abstractmethod
    def list_active_jobs(self) -> list[Job]: ...

    @abstractmethod
    def transition(self, job_id: str, new_status: str, error_message: str | None = None) -> Job: ...

    @abstractmethod
    def set_waiting_capacity(
        self,
        job_id: str,
        waiting_provider: str,
        reason: str,
        expected_reset_at: datetime | None = None,
    ) -> Job: ...

    @abstractmethod
    def set_recovery_blocked(self, job_id: str, reason: str) -> Job: ...


class JobLogRepositoryInterface(ABC):
    @abstractmethod
    def save(self, log: JobLog) -> None: ...

    @abstractmethod
    def list_by_job(self, job_id: str, limit: int = 500) -> list[JobLog]: ...


class CheckResultRepositoryInterface(ABC):
    @abstractmethod
    def save(self, result: CheckResult) -> None: ...

    @abstractmethod
    def list_by_job(self, job_id: str) -> list[CheckResult]: ...


class ReviewRepositoryInterface(ABC):
    @abstractmethod
    def save(self, review: Review) -> None: ...

    @abstractmethod
    def get_by_id(self, review_id: str) -> Review | None: ...

    @abstractmethod
    def get_by_job_id(self, job_id: str) -> Review | None: ...

    @abstractmethod
    def list_by_project(self, project_id: str, limit: int = 100) -> list[Review]: ...

    @abstractmethod
    def transition(
        self,
        review_id: str,
        new_status: str,
        verdict: str | None = None,
        summary: str | None = None,
        error_message: str | None = None,
    ) -> Review: ...


class ReviewFindingRepositoryInterface(ABC):
    @abstractmethod
    def save(self, finding: ReviewFinding) -> None: ...

    @abstractmethod
    def list_by_review(self, review_id: str) -> list[ReviewFinding]: ...


class AuditRepositoryInterface(ABC):
    @abstractmethod
    def save(self, audit: AuditRecord) -> None: ...

    @abstractmethod
    def get_by_id(self, audit_id: str) -> AuditRecord | None: ...

    @abstractmethod
    def get_by_job_id(self, job_id: str) -> AuditRecord | None: ...

    @abstractmethod
    def list_by_project(self, project_id: str, limit: int = 100) -> list[AuditRecord]: ...

    @abstractmethod
    def transition(
        self,
        audit_id: str,
        new_status: str,
        risk: str | None = None,
        summary: str | None = None,
        error_message: str | None = None,
    ) -> AuditRecord: ...


class AuditFindingRepositoryInterface(ABC):
    @abstractmethod
    def save(self, finding: AuditFinding) -> None: ...

    @abstractmethod
    def list_by_audit(self, audit_id: str) -> list[AuditFinding]: ...


class ProviderHealthRepositoryInterface(ABC):
    @abstractmethod
    def save(self, health: ProviderHealth) -> None: ...

    @abstractmethod
    def get_by_provider(self, provider: str) -> ProviderHealth | None: ...

    @abstractmethod
    def list_all(self) -> list[ProviderHealth]: ...

    @abstractmethod
    def update_health(
        self,
        provider: str,
        status: str,
        result_class: str | None = None,
        error_summary: str | None = None,
        consecutive_failures: int | None = None,
    ) -> ProviderHealth: ...


class CapacityWindowRepositoryInterface(ABC):
    @abstractmethod
    def save(self, window: CapacityWindow) -> None: ...

    @abstractmethod
    def get_latest_for_provider(self, provider: str) -> CapacityWindow | None: ...

    @abstractmethod
    def list_by_provider(self, provider: str, limit: int = 50) -> list[CapacityWindow]: ...


class GitOperationRepositoryInterface(ABC):
    @abstractmethod
    def save(self, operation: GitOperation) -> None: ...

    @abstractmethod
    def get_by_id(self, operation_id: str) -> GitOperation | None: ...

    @abstractmethod
    def list_by_job(self, job_id: str) -> list[GitOperation]: ...

    @abstractmethod
    def list_by_worktree(self, worktree_path: str) -> list[GitOperation]: ...

    @abstractmethod
    def update_status(
        self,
        operation_id: str,
        status: GitOperationStatus,
        completed_at: datetime | None = None,
    ) -> GitOperation | None: ...


class OpenRouterBudgetPolicyRepositoryInterface(ABC):
    @abstractmethod
    def get_for_update(self, project_id: str) -> OpenRouterBudgetPolicy | None: ...

    @abstractmethod
    def save(self, policy: OpenRouterBudgetPolicy) -> None: ...


class OpenRouterPricingSnapshotRepositoryInterface(ABC):
    @abstractmethod
    def save(self, snapshot: OpenRouterPricingSnapshot) -> None: ...

    @abstractmethod
    def get_by_id(self, snapshot_id: str) -> OpenRouterPricingSnapshot | None: ...


class BudgetReservationRepositoryInterface(ABC):
    @abstractmethod
    def save(self, reservation: BudgetReservation) -> None: ...

    @abstractmethod
    def get_by_id(self, reservation_id: str) -> BudgetReservation | None: ...

    @abstractmethod
    def list_by_project(self, project_id: str) -> list[BudgetReservation]: ...


class BudgetLedgerRepositoryInterface(ABC):
    @abstractmethod
    def save(self, entry: BudgetLedgerEntry) -> None: ...

    @abstractmethod
    def list_by_project(self, project_id: str) -> list[BudgetLedgerEntry]: ...


class FallbackPolicyInterface(ABC):
    """Abstract fallback policy seam for future drain provider execution (006)."""

    @abstractmethod
    def is_fallback_eligible(self, project_id: str, job: Job, role: str) -> bool: ...


class JobAttemptRepositoryInterface(ABC):
    @abstractmethod
    def save(self, attempt: JobAttempt) -> None: ...

    @abstractmethod
    def get_by_id(self, attempt_id: str) -> JobAttempt | None: ...

    @abstractmethod
    def list_by_job(self, job_id: str) -> list[JobAttempt]: ...

    @abstractmethod
    def get_latest_attempt(self, job_id: str) -> JobAttempt | None: ...


class BlockerClaimRepositoryInterface(ABC):
    @abstractmethod
    def save(self, claim: BlockerClaim) -> None: ...

    @abstractmethod
    def get_by_id(self, claim_id: str) -> BlockerClaim | None: ...

    @abstractmethod
    def list_by_job(self, job_id: str) -> list[BlockerClaim]: ...

    @abstractmethod
    def list_by_attempt(self, attempt_id: str) -> list[BlockerClaim]: ...


class JobHandoffRepositoryInterface(ABC):
    @abstractmethod
    def save(self, handoff: JobHandoff) -> None: ...

    @abstractmethod
    def get_by_id(self, handoff_id: str) -> JobHandoff | None: ...

    @abstractmethod
    def get_latest_handoff(self, job_id: str) -> JobHandoff | None: ...

    @abstractmethod
    def list_by_job(self, job_id: str) -> list[JobHandoff]: ...


class CandidateManifestRepositoryInterface(ABC):
    @abstractmethod
    def save(self, manifest: CandidateManifest) -> None: ...

    @abstractmethod
    def get_by_id(self, manifest_id: str) -> CandidateManifest | None: ...

    @abstractmethod
    def get_by_candidate_sha(self, job_id: str, candidate_sha: str) -> CandidateManifest | None: ...

    @abstractmethod
    def get_latest_manifest(self, job_id: str) -> CandidateManifest | None: ...


class CandidateAuthorshipRepositoryInterface(ABC):
    @abstractmethod
    def save(self, authorship: CandidateAuthorship) -> None: ...

    @abstractmethod
    def list_by_job(self, job_id: str) -> list[CandidateAuthorship]: ...


class EvidenceDiagnosticRepositoryInterface(ABC):
    @abstractmethod
    def save(self, diagnostic: EvidenceDiagnostic) -> None: ...

    @abstractmethod
    def list_by_job(self, job_id: str) -> list[EvidenceDiagnostic]: ...

    @abstractmethod
    def list_by_attempt(self, attempt_id: str) -> list[EvidenceDiagnostic]: ...


class OrchestrationRunRepositoryInterface(ABC):
    @abstractmethod
    def save(self, run: OrchestrationRun) -> None: ...

    @abstractmethod
    def get_by_id(self, run_id: str) -> OrchestrationRun | None: ...

    @abstractmethod
    def get_active_run(self, project_id: str, change_name: str) -> OrchestrationRun | None: ...

    @abstractmethod
    def list_runs(
        self,
        project_id: str | None = None,
        change_name: str | None = None,
        is_active: bool | None = None,
    ) -> list[OrchestrationRun]: ...

    @abstractmethod
    def update_stage(
        self,
        run_id: str,
        current_stage: OrchestrationStage,
        resumable_stage: OrchestrationStage,
    ) -> OrchestrationRun: ...

    @abstractmethod
    def update_stop_outcome(
        self,
        run_id: str,
        stop_outcome: OrchestrationStopOutcome,
        human_gate: HumanGate | None = None,
        stop_reason: str | None = None,
        stop_details: dict[str, Any] | None = None,
        is_active: bool = False,
    ) -> OrchestrationRun: ...

    @abstractmethod
    def update_candidate_binding(
        self,
        run_id: str,
        current_generation: int,
        current_candidate_sha: str | None,
    ) -> OrchestrationRun: ...

    @abstractmethod
    def update_active_job(
        self,
        run_id: str,
        active_job_id: str | None,
    ) -> OrchestrationRun: ...


class OrchestrationStageEventRepositoryInterface(ABC):
    @abstractmethod
    def save(self, event: OrchestrationStageEvent) -> None: ...

    @abstractmethod
    def list_by_run(self, run_id: str) -> list[OrchestrationStageEvent]: ...

    @abstractmethod
    def get_by_transition_key(self, transition_key: str) -> OrchestrationStageEvent | None: ...


class OrchestrationCandidateRepositoryInterface(ABC):
    @abstractmethod
    def save(self, candidate: OrchestrationCandidate) -> None: ...

    @abstractmethod
    def get_by_id(self, candidate_id: str) -> OrchestrationCandidate | None: ...

    @abstractmethod
    def get_by_generation(self, run_id: str, generation: int) -> OrchestrationCandidate | None: ...

    @abstractmethod
    def get_latest_for_run(self, run_id: str) -> OrchestrationCandidate | None: ...

    @abstractmethod
    def list_by_run(self, run_id: str) -> list[OrchestrationCandidate]: ...

    @abstractmethod
    def supersede(self, candidate_id: str, superseded_by_id: str) -> None: ...


class OrchestrationExternalActionRepositoryInterface(ABC):
    @abstractmethod
    def reserve(self, action: OrchestrationExternalAction) -> None: ...

    @abstractmethod
    def get_by_action_key(self, action_key: str) -> OrchestrationExternalAction | None: ...

    @abstractmethod
    def list_by_run(self, run_id: str) -> list[OrchestrationExternalAction]: ...

    @abstractmethod
    def update_status(
        self,
        action_key: str,
        status: ExternalActionStatus,
        remote_identifier: str | None = None,
        result_payload: dict[str, Any] | None = None,
        error_message: str | None = None,
    ) -> OrchestrationExternalAction: ...


class PreviewSessionRepositoryInterface(ABC):
    @abstractmethod
    def save(self, session: PreviewSession) -> None: ...

    @abstractmethod
    def get_by_id(self, preview_id: str) -> PreviewSession | None: ...

    @abstractmethod
    def get_latest_for_run(self, run_id: str) -> PreviewSession | None: ...

    @abstractmethod
    def get_latest_for_candidate(
        self, project_id: str, change_name: str, head_sha: str
    ) -> PreviewSession | None: ...

    @abstractmethod
    def list_by_change(self, project_id: str, change_name: str) -> list[PreviewSession]: ...

    @abstractmethod
    def list_active(self) -> list[PreviewSession]: ...


class ValidationRunRepositoryInterface(ABC):
    @abstractmethod
    def save(self, validation: ValidationRun) -> None: ...

    @abstractmethod
    def get_by_id(self, validation_id: str) -> ValidationRun | None: ...

    @abstractmethod
    def get_latest_for_candidate(
        self,
        project_id: str,
        change_name: str,
        head_sha: str,
        base_sha: str,
        image_digest: str,
    ) -> ValidationRun | None: ...

    @abstractmethod
    def list_by_change(self, project_id: str, change_name: str) -> list[ValidationRun]: ...

    @abstractmethod
    def list_by_run(self, run_id: str) -> list[ValidationRun]: ...


class PersistenceUnitOfWork(ABC):
    """Transactional persistence boundary: atomically persists state changes and emitted events."""

    projects: ProjectRepositoryInterface
    changes: ChangeRepositoryInterface
    bindings: ProjectBindingRepositoryInterface
    events: EventRepositoryInterface
    metrics: MetricFactRepositoryInterface
    jobs: JobRepositoryInterface
    job_logs: JobLogRepositoryInterface
    check_results: CheckResultRepositoryInterface
    reviews: ReviewRepositoryInterface
    review_findings: ReviewFindingRepositoryInterface
    audits: AuditRepositoryInterface
    audit_findings: AuditFindingRepositoryInterface
    provider_health: ProviderHealthRepositoryInterface
    capacity_windows: CapacityWindowRepositoryInterface
    git_operations: GitOperationRepositoryInterface
    budget_policies: OpenRouterBudgetPolicyRepositoryInterface
    pricing_snapshots: OpenRouterPricingSnapshotRepositoryInterface
    budget_reservations: BudgetReservationRepositoryInterface
    budget_ledger: BudgetLedgerRepositoryInterface
    job_attempts: JobAttemptRepositoryInterface
    blocker_claims: BlockerClaimRepositoryInterface
    job_handoffs: JobHandoffRepositoryInterface
    candidate_manifests: CandidateManifestRepositoryInterface
    candidate_authorships: CandidateAuthorshipRepositoryInterface
    evidence_diagnostics: EvidenceDiagnosticRepositoryInterface
    orchestration_runs: OrchestrationRunRepositoryInterface
    orchestration_stage_events: OrchestrationStageEventRepositoryInterface
    orchestration_candidates: OrchestrationCandidateRepositoryInterface
    orchestration_external_actions: OrchestrationExternalActionRepositoryInterface
    preview_sessions: PreviewSessionRepositoryInterface
    validation_runs: ValidationRunRepositoryInterface

    @abstractmethod
    def commit(self) -> None: ...

    @abstractmethod
    def rollback(self) -> None: ...


class OpenSpecAdapterInterface(ABC):
    @abstractmethod
    def discover_changes(self, project: Project, project_root: str) -> list[Change]: ...

    @abstractmethod
    def evaluate_artifacts(
        self, project: Project, change_name: str, project_root: str
    ) -> dict[str, Any]: ...


class GitHubAdapterInterface(ABC):
    @abstractmethod
    def validate_issue_binding(
        self,
        expected_repository: str,
        issue_number: int,
        github_repository: str | None = None,
    ) -> tuple[bool, str | None]: ...

    @abstractmethod
    def record_sync_failure(
        self,
        project_id: str,
        change_id: str | None,
        operation: str,
        error_message: str,
    ) -> Event: ...

    @abstractmethod
    def get_pull_request(self, repository: str, branch: str, base: str = "main") -> Any: ...

    @abstractmethod
    def create_pull_request(
        self,
        repository: str,
        branch: str,
        base: str,
        title: str,
        body: str,
        head_sha: str,
    ) -> dict[str, Any]: ...

    @abstractmethod
    def push_branch(
        self,
        worktree_path: str,
        remote: str,
        branch: str,
        candidate_sha: str,
    ) -> bool: ...

    @abstractmethod
    def get_remote_branch_head(
        self, repository: str, branch: str, remote: str = "origin"
    ) -> str | None: ...
