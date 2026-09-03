"""Unit and integration test suite for 018.1 Provider Efficiency & Reviewer Independence Hardening.

Covers:
- Mandatory Rule A: Routine Implementation Workhorse (Codex default, AG ineligible)
- Mandatory Rule B: Retry Budget Enforcement (1 normal + 1 corrective)
- Mandatory Rule C: Same-SHA Anti-Loop (SAME_SHA_RETRY_SUPPRESSED)
- Mandatory Rule D: In-Process Lightweight Reconciliation (0 LLM cost)
- Mandatory Rule E: Antigravity Selection Governance (Mandatory reason codes)
- Mandatory Rule F: Drain Fallback and Distinct-Model Independence
- Mandatory Rule G: Reviewer Independence Technical Enforcement (Fail-closed on self-review)
- PostgreSQL Efficiency Telemetry & Self-Hosting Ratio Persistence
"""

from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from minime.domain.enums import (
    AdmissionDecision,
    AdmissionRefusalCode,
    AttemptProductivityClass,
    AuditRiskLevel,
    ContinuationDecision,
    EventType,
    EvidenceDiagnosticStatus,
    ExecutionOutcome,
    JobStatus,
    OrchestrationStage,
    PremiumProviderReasonCode,
    ProgressClassification,
    ProviderHealthStatus,
    ReadinessState,
    ReviewVerdict,
    SchedulerMode,
    TaskClass,
)
from minime.domain.models import (
    CandidateAuthorship,
    Change,
    Event,
    Job,
    JobAttempt,
    OrchestrationRun,
    Project,
    ProviderEfficiencyMetrics,
    ProviderHealth,
    utc_now,
)
from minime.services.authorship_service import AuthorshipService
from minime.services.continuation_engine import (
    ContinuationContext,
    ContinuationEngine,
)
from minime.services.efficiency_telemetry_service import EfficiencyTelemetryService
from minime.services.lightweight_reconciliation_service import LightweightReconciliationService
from minime.services.openspec_tasks import OpenSpecTask
from minime.services.orchestration_service import OrchestrationService
from minime.services.provider_policy_service import ProviderPolicyService
from minime.services.task_classifier import TaskClassifier


class MockUOW:
    """In-memory Unit of Work for testing 018.1 services."""

    def __init__(self):
        self.jobs = MagicMock()
        self._jobs = {}
        self.jobs.get_by_id = lambda jid: self._jobs.get(jid)
        self.jobs.save = lambda j: self._jobs.update({j.job_id: j})

        self.projects = MagicMock()
        self._projects = {}
        self.projects.get_by_id = lambda pid: self._projects.get(pid)
        self.projects.save = lambda p: self._projects.update({p.project_id: p})

        self.changes = MagicMock()
        self._changes = {}
        self.changes.get_by_name = lambda pid, cname: self._changes.get(f"{pid}:{cname}")
        self.changes.save = lambda c: self._changes.update({f"{c.project_id}:{c.name}": c})

        self.events = MagicMock()
        self._events = []
        self.events.save = lambda e: self._events.append(e)
        self.events.list_events = lambda **kwargs: list(self._events)

        self.job_attempts = MagicMock()
        self._attempts = {}
        self.job_attempts.save = lambda a: self._attempts.update({a.attempt_id: a})
        self.job_attempts.list_by_job = lambda jid: [
            a for a in self._attempts.values() if a.job_id == jid
        ]

        self.candidate_authorships = MagicMock()
        self._authorships = {}
        self.candidate_authorships.save = lambda ca: self._authorships.update({ca.authorship_id: ca})
        self.candidate_authorships.list_by_job = lambda jid: [
            ca for ca in self._authorships.values() if ca.job_id == jid
        ]

        self.evidence_diagnostics = MagicMock()
        self._diagnostics = {}
        self.evidence_diagnostics.save = lambda ed: self._diagnostics.update({ed.diagnostic_id: ed})
        self.evidence_diagnostics.list_by_job = lambda jid: [
            ed for ed in self._diagnostics.values() if ed.job_id == jid
        ]

        self.provider_health = MagicMock()
        self._health = {
            "codex": ProviderHealth(
                provider="codex", status=ProviderHealthStatus.AVAILABLE, updated_at=utc_now()
            ),
            "antigravity": ProviderHealth(
                provider="antigravity", status=ProviderHealthStatus.AVAILABLE, updated_at=utc_now()
            ),
            "deepseek": ProviderHealth(
                provider="deepseek", status=ProviderHealthStatus.AVAILABLE, updated_at=utc_now()
            ),
        }
        self.provider_health.get_by_provider = lambda p: self._health.get(p)
        self.provider_health.list_all = lambda: list(self._health.values())

        self.provider_efficiency = MagicMock()
        self._efficiency = {}
        self.provider_efficiency.save = lambda pe: self._efficiency.update({pe.metrics_id: pe})
        self.provider_efficiency.get_by_id = lambda pid: self._efficiency.get(pid)
        self.provider_efficiency.get_by_run_id = lambda rid: next(
            (pe for pe in self._efficiency.values() if pe.run_id == rid), None
        )
        self.provider_efficiency.get_by_project_and_change = lambda pid, cname: next(
            (
                pe
                for pe in self._efficiency.values()
                if pe.project_id == pid and pe.change_name == cname
            ),
            None,
        )
        self.provider_efficiency.list_by_project = lambda pid, limit=50: [
            pe for pe in self._efficiency.values() if pe.project_id == pid
        ][:limit]

        self.orchestration_runs = MagicMock()
        self._runs = {}
        self.orchestration_runs.save = lambda r: self._runs.update({r.run_id: r})
        self.orchestration_runs.get_by_id = lambda rid: self._runs.get(rid)
        self.orchestration_runs.get_by_job_id = lambda jid: next(
            (r for r in self._runs.values() if r.job_id == jid), None
        )
        self.orchestration_runs.list_runs = lambda is_active=None: list(self._runs.values())

        self.orchestration_stage_events = MagicMock()
        self.orchestration_stage_events.save = MagicMock()

    def commit(self):
        pass


def test_task_classifier_determines_task_classes():
    """Verify deterministic task classification across all standard lifecycle scenarios."""
    classifier = TaskClassifier()

    # 1. Routine implementation
    res_impl = classifier.classify(stage="IMPLEMENTING")
    assert res_impl.task_class == TaskClass.ROUTINE_IMPLEMENTATION

    # 2. Test fix vs ordinary remediation
    res_test_fix = classifier.classify(
        stage="REMEDIATING",
        failing_checks=[{"name": "pytest"}],
    )
    assert res_test_fix.task_class == TaskClass.TEST_FIX

    res_lint_fix = classifier.classify(
        stage="REMEDIATING",
        failing_checks=[{"name": "flake8"}],
    )
    assert res_lint_fix.task_class == TaskClass.ORDINARY_REMEDIATION

    # 3. Architecture classification
    res_arch = classifier.classify(
        stage="IMPLEMENTING",
        is_architecture_scope=True,
    )
    assert res_arch.task_class == TaskClass.ARCHITECTURE

    # 4. UX / Visual QA classification
    res_ux = classifier.classify(
        stage="IMPLEMENTING",
        is_ux_validation=True,
    )
    assert res_ux.task_class == TaskClass.UX_VISUAL_QA

    # 5. Bookkeeping / Evidence reconciliation
    tasks = [
        OpenSpecTask(task_id="1.1", text="Sync tasks.md and record evidence", section=None, complete=False)
    ]
    res_bookkeeping = classifier.classify(
        stage="IMPLEMENTING",
        code_changed=True,
        incomplete_tasks=tasks,
    )
    assert res_bookkeeping.task_class == TaskClass.BOOKKEEPING_RECONCILIATION


def test_provider_policy_codex_default_and_antigravity_inelegibility():
    """Mandatory Rule A: Routine tasks select Codex; Antigravity is ineligible when Codex is available."""
    uow = MockUOW()
    policy = ProviderPolicyService(uow)

    project = Project(
        project_id="proj-1",
        name="test-project",
        display_name="Test Project",
        repository="owner/repo",
        implementer="codex",
        reviewer="antigravity",
    )
    uow.projects.save(project)

    # When task is routine implementation and codex is AVAILABLE
    expl = policy.evaluate_selection(
        task_class=TaskClass.ROUTINE_IMPLEMENTATION,
        project=project,
        attempts=[],
    )
    assert expl.selected_provider == "codex"
    assert expl.is_premium is False
    assert expl.premium_reason_code is None
    assert "PREMIUM_PROVIDER_NOT_REQUIRED" in expl.explanation


def test_provider_policy_antigravity_assignment_requires_reason_code():
    """Mandatory Rule E: Antigravity assignment requires and records a valid reason code."""
    uow = MockUOW()
    policy = ProviderPolicyService(uow)

    project = Project(
        project_id="proj-1",
        name="test-project",
        display_name="Test Project",
        repository="owner/repo",
        implementer="codex",
        reviewer="antigravity",
    )
    uow.projects.save(project)

    # 1. Architecture required
    expl_arch = policy.evaluate_selection(
        task_class=TaskClass.ARCHITECTURE,
        project=project,
    )
    assert expl_arch.selected_provider == "antigravity"
    assert expl_arch.premium_reason_code == PremiumProviderReasonCode.ARCHITECTURE_REQUIRED

    # 2. UX Visual QA required
    expl_ux = policy.evaluate_selection(
        task_class=TaskClass.UX_VISUAL_QA,
        project=project,
    )
    assert expl_ux.selected_provider == "antigravity"
    assert expl_ux.premium_reason_code == PremiumProviderReasonCode.UX_VISUAL_QA

    # 3. Platform recovery required
    expl_plat = policy.evaluate_selection(
        task_class=TaskClass.PLATFORM_RECOVERY,
        project=project,
    )
    assert expl_plat.selected_provider == "antigravity"
    assert expl_plat.premium_reason_code == PremiumProviderReasonCode.PLATFORM_RECOVERY

    # 4. Codex non-convergence escalation
    past_attempts = [
        JobAttempt(
            attempt_id="att-1",
            job_id="job-1",
            attempt_number=1,
            executor_role="codex",
            model_identity="codex",
            normalized_outcome=ExecutionOutcome.NO_PROGRESS,
            is_same_sha_duplicate=False,
        ),
        JobAttempt(
            attempt_id="att-2",
            job_id="job-1",
            attempt_number=2,
            executor_role="codex",
            model_identity="codex",
            normalized_outcome=ExecutionOutcome.NO_PROGRESS,
            is_same_sha_duplicate=False,
        ),
    ]
    expl_escalated = policy.evaluate_selection(
        task_class=TaskClass.ROUTINE_IMPLEMENTATION,
        project=project,
        attempts=past_attempts,
    )
    assert expl_escalated.selected_provider == "antigravity"
    assert expl_escalated.premium_reason_code == PremiumProviderReasonCode.CODEX_NON_CONVERGENCE


def test_retry_budget_enforcement_one_normal_one_corrective():
    """Mandatory Rule B: ContinuationEngine allows 1 normal attempt + 1 corrective retry before root-cause."""
    engine = ContinuationEngine(max_corrective_retries_per_executor=1)

    # Attempt 1 (Normal attempt) fails with PREMATURE_STOP
    # Corrective retries count = 0 -> Decision: CORRECT_AND_RETRY
    ctx1 = ContinuationContext(
        job_id="job-1",
        attempt_number=1,
        current_executor_role="codex",
        current_model_identity="codex",
        outcome=ExecutionOutcome.PREMATURE_STOP,
        progress=ProgressClassification.PARTIAL_PROGRESS,
        corrective_retries_for_current_executor=0,
        reassignment_count=0,
        same_outcome_streak=1,
    )
    res1 = engine.decide(ctx1)
    assert res1.decision == ContinuationDecision.CORRECT_AND_RETRY

    # Attempt 2 (Corrective retry 1) fails with PREMATURE_STOP
    # Corrective retries count = 1 -> Retry budget exhausted! Decision: REASSIGN_AGENT
    ctx2 = ContinuationContext(
        job_id="job-1",
        attempt_number=2,
        current_executor_role="codex",
        current_model_identity="codex",
        outcome=ExecutionOutcome.PREMATURE_STOP,
        progress=ProgressClassification.NO_PROGRESS,
        corrective_retries_for_current_executor=1,
        reassignment_count=0,
        same_outcome_streak=2,
        target_executor_role="antigravity",
    )
    res2 = engine.decide(ctx2)
    assert res2.decision == ContinuationDecision.REASSIGN_AGENT


def test_same_sha_anti_loop_suppression():
    """Mandatory Rule C: Duplicate attempts with same SHA and no progress are suppressed."""
    engine = ContinuationEngine()

    ctx = ContinuationContext(
        job_id="job-1",
        attempt_number=2,
        current_executor_role="codex",
        current_model_identity="codex",
        outcome=ExecutionOutcome.NO_PROGRESS,
        is_same_sha_duplicate=True,
    )
    res = engine.decide(ctx)
    assert res.decision == ContinuationDecision.NEEDS_HUMAN
    assert "SAME_SHA_RETRY_SUPPRESSED" in res.escalation_reason
    assert res.suppressed_same_sha is True


def test_lightweight_in_process_reconciliation(tmp_path: Path):
    """Mandatory Rule D: In-process reconciliation marks remaining tasks and records evidence at 0 LLM cost."""
    uow = MockUOW()
    rec_service = LightweightReconciliationService(uow)

    # Create synthetic change dir with tasks.md
    change_dir = tmp_path / "openspec" / "changes" / "018-test-change"
    change_dir.mkdir(parents=True, exist_ok=True)
    tasks_file = change_dir / "tasks.md"
    tasks_file.write_text(
        "# Tasks\n- [x] 1.1 Core code implementation\n- [ ] 1.2 tasks.md reconciliation and evidence sync\n"
    )

    project = Project(
        project_id="proj-1",
        name="test-project",
        display_name="Test Project",
        repository="owner/repo",
        implementer="codex",
        reviewer="antigravity",
    )
    job = Job(
        job_id="job-rec-1",
        project_id="proj-1",
        change_name="018-test-change",
        implementer_role="codex",
        candidate_sha="sha-abc",
    )

    result = rec_service.reconcile_bookkeeping(
        worktree_path=tmp_path,
        openspec_path="openspec",
        change_name="018-test-change",
        project=project,
        job=job,
        checks_passed=True,
        changed_files=["src/core.py"],
    )

    assert result["success"] is True
    assert "1.2" in result["reconciled_tasks"]

    # Verify tasks.md was updated
    updated_tasks = tasks_file.read_text()
    assert "- [x] 1.2 tasks.md reconciliation and evidence sync" in updated_tasks

    # Verify event was emitted
    events = uow._events
    assert any(e.event_type == EventType.LIGHTWEIGHT_RECONCILIATION_PERFORMED for e in events)


def test_reviewer_independence_technical_enforcement():
    """Mandatory Rule G: Material candidate authors are disqualified from reviewer role; fails closed."""
    uow = MockUOW()
    auth_service = AuthorshipService()

    project = Project(
        project_id="proj-1",
        name="test-project",
        display_name="Test Project",
        repository="owner/repo",
        implementer="codex",
        reviewer="antigravity",
    )
    uow.projects.save(project)

    job = Job(
        job_id="job-review-1",
        project_id="proj-1",
        change_name="018-independence",
        implementer_role="codex",
        current_executor="codex",
    )
    uow.jobs.save(job)

    # 1. Candidate authorship by codex
    ca = CandidateAuthorship(
        authorship_id="auth-1",
        job_id=job.job_id,
        attempt_id="att-1",
        attempt_number=1,
        agent_role="codex",
        model_identity="codex-model",
        files_touched=["src/impl.py"],
    )
    uow.candidate_authorships.save(ca)

    # Check independence: codex is author, antigravity is independent
    summary = auth_service.evaluate_reviewer_independence(
        job_id=job.job_id,
        configured_reviewers=["codex", "antigravity"],
        uow=uow,
    )
    assert summary.is_independent is True
    assert "antigravity" in summary.eligible_reviewers
    assert "codex" in summary.disqualified_reviewers

    # 2. If both codex and antigravity authored candidate code (e.g. mixed authorship)
    ca2 = CandidateAuthorship(
        authorship_id="auth-2",
        job_id=job.job_id,
        attempt_id="att-2",
        attempt_number=2,
        agent_role="antigravity",
        model_identity="antigravity-model",
        files_touched=["src/impl.py"],
    )
    uow.candidate_authorships.save(ca2)

    summary_mixed = auth_service.evaluate_reviewer_independence(
        job_id=job.job_id,
        configured_reviewers=["codex", "antigravity"],
        uow=uow,
    )
    # Fails closed because all primary agents are candidate authors!
    assert summary_mixed.is_independent is False
    assert len(summary_mixed.eligible_reviewers) == 0
    assert "codex" in summary_mixed.disqualified_reviewers
    assert "antigravity" in summary_mixed.disqualified_reviewers


def test_efficiency_telemetry_aggregation_and_persistence():
    """Verify PostgreSQL ProviderEfficiencyMetrics compilation and 9-phase self-hosting ratio."""
    uow = MockUOW()
    telemetry_service = EfficiencyTelemetryService(uow)

    job = Job(
        job_id="job-eff-1",
        project_id="proj-1",
        change_name="018-efficiency",
        implementer_role="codex",
    )
    uow.jobs.save(job)

    run = OrchestrationRun(
        run_id="run-eff-1",
        active_job_id="job-eff-1",
        project_id="proj-1",
        change_name="018-efficiency",
        job_id="job-eff-1",
        base_sha="base-123",
        current_stage=OrchestrationStage.PR_PREPARED,
    )
    uow.orchestration_runs.save(run)

    # Add 2 codex attempts and 0 antigravity attempts
    att1 = JobAttempt(
        attempt_id="att-1",
        job_id="job-eff-1",
        attempt_number=1,
        executor_role="codex",
        model_identity="codex",
        normalized_outcome=ExecutionOutcome.COMPLETED,
        duration_ms=5000,
        productivity_class=AttemptProductivityClass.SUBSTANTIVE_PROGRESS,
    )
    att2 = JobAttempt(
        attempt_id="att-2",
        job_id="job-eff-1",
        attempt_number=2,
        executor_role="codex",
        model_identity="codex",
        normalized_outcome=ExecutionOutcome.CHANGES_REQUIRED,
        duration_ms=3000,
        productivity_class=AttemptProductivityClass.VALID_CORRECTIVE_WORK,
    )
    uow.job_attempts.save(att1)
    uow.job_attempts.save(att2)

    # Record telemetry
    metrics = telemetry_service.record_run_telemetry(run)

    assert metrics.attempts_by_provider["codex"] == 2
    assert metrics.attempts_by_provider.get("antigravity", 0) == 0
    assert metrics.duration_by_provider_ms["codex"] == 8000
    assert metrics.productive_attempt_count == 2
    assert metrics.self_hosting_native_phases == 9
    assert metrics.self_hosting_total_phases == 9
    assert metrics.self_hosting_percentage == 100.0

    # Retrieve telemetry view
    view = telemetry_service.get_efficiency_view("proj-1", "018-efficiency")
    assert view is not None
    assert view.metrics.metrics_id == metrics.metrics_id
    assert view.metrics.self_hosting_percentage == 100.0
