"""Autonomous proving runner for 018.2 end-to-end self-operating loop."""

import os
from pathlib import Path

from minime.adapters.github import GitHubAdapter
from minime.db.repository import PostgresPersistenceUnitOfWork
from minime.db.session import db_manager
from minime.domain.enums import (
    HumanGate,
    OrchestrationStopOutcome,
    ProjectStatus,
    ProviderHealthStatus,
)
from minime.domain.models import Project, ProjectBinding, ProviderHealth
from minime.services.discovery_service import WorkDiscoveryService
from minime.services.efficiency_telemetry_service import EfficiencyTelemetryService
from minime.services.orchestration_service import OrchestrationService
from minime.services.readiness_service import ReadinessService
from minime.services.scheduler_service import SchedulerService


def _bootstrap_env() -> None:
    os.environ["PATH"] = (
        f"/Users/silveriobernal/.local/bin:/opt/homebrew/bin:{os.environ.get('PATH', '')}"
    )
    env_path = Path("/Users/silveriobernal/.config/minime/dev.env")
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ[k.strip()] = v.strip()


def run_proving_pilot():
    _bootstrap_env()
    print("=" * 60)
    print("018.2 AUTONOMOUS END-TO-END PROVING PILOT")
    print("=" * 60)

    db_manager.initialize()
    with db_manager.session() as session:
        uow = PostgresPersistenceUnitOfWork(session)
        gh_adapter = GitHubAdapter()

        # 1. Verify Project and Binding
        project = uow.projects.get_by_id("mini-me")
        if not project:
            project = Project(
                project_id="mini-me",
                repository="silverberdi/mini-me",
                base_branch="main",
                openspec_path="openspec",
                implementer="codex",
                reviewer="antigravity",
                checks=[
                    {"name": "ruff", "command": "ruff check ."},
                    {"name": "test", "command": "pytest tests/test_status_observability.py"},
                ],
                status=ProjectStatus.ACTIVE,
            )
            uow.projects.save(project)

        change_name = "018.2-proving-diagnostic-status"
        issue_number = 53

        binding = uow.bindings.get_by_project_and_change("mini-me", change_name)
        if not binding:
            binding = ProjectBinding(
                project_id="mini-me",
                repository="silverberdi/mini-me",
                github_issue_number=issue_number,
                openspec_change_name=change_name,
                is_valid=True,
            )
            uow.bindings.save(binding)
        else:
            binding.github_issue_number = issue_number
            binding.is_valid = True
            uow.bindings.save(binding)

        for prov in ["codex", "antigravity"]:
            h = uow.provider_health.get_by_provider(prov)
            if not h:
                uow.provider_health.save(
                    ProviderHealth(provider=prov, status=ProviderHealthStatus.AVAILABLE)
                )
            elif h.status != ProviderHealthStatus.AVAILABLE:
                h.status = ProviderHealthStatus.AVAILABLE
                uow.provider_health.save(h)

        uow.commit()

        # 2. Verify Definition of Ready
        print("\n[PHASE 1 & 2: DISCOVERY & READINESS]")
        readiness_service = ReadinessService(uow, github_adapter=gh_adapter)
        eval_res = readiness_service.evaluate_change_readiness(
            project_id="mini-me",
            change_name=change_name,
            project_root=".",
            github_repo="silverberdi/mini-me",
            github_issue=issue_number,
        )
        print(f"Readiness Status: {eval_res.status.value}")
        print(f"Is Ready: {eval_res.is_ready}")
        assert eval_res.is_ready, f"Change is not ready: {eval_res.unmet_reasons}"

        # 3. Instantiate Autonomous Services
        orchestration_service = OrchestrationService(
            uow=uow,
            project_root=".",
            github_adapter=gh_adapter,
        )
        discovery_service = WorkDiscoveryService(
            uow=uow,
            readiness_service=readiness_service,
            github_adapter=gh_adapter,
            project_root=".",
        )
        scheduler = SchedulerService(
            uow=uow,
            orchestration_service=orchestration_service,
            discovery_service=discovery_service,
            readiness_service=readiness_service,
            project_root=".",
        )

        # 4. Trigger Autonomous Scheduler Tick
        print("\n[PHASE 3-15: AUTONOMOUS SCHEDULER ADMISSION & COORDINATION]")
        print("Invoking scheduler.tick(project_id='mini-me', drive_admitted=True)...")

        decisions = scheduler.tick(project_id="mini-me", drive_admitted=True)
        print(f"Scheduler Decisions ({len(decisions)}):")
        for d in decisions:
            print(
                f"  - Change: {d.change_name}, Decision: {d.decision.value}, Implementer: {d.selected_implementer}, Reason: {d.reason_code}"
            )

        # 5. Inspect Orchestration Run Result
        runs = uow.orchestration_runs.list_runs(project_id="mini-me", change_name=change_name)
        assert len(runs) > 0, "Expected orchestration run to exist"
        run = runs[-1]
        print(f"\nOrchestration Run ID: {run.run_id}")
        print(f"Final Stage: {run.current_stage.value}")
        print(f"Stop Outcome: {run.stop_outcome.value if run.stop_outcome else 'None'}")
        print(f"Human Gate: {run.human_gate.value if run.human_gate else 'None'}")
        print(f"Is Active: {run.is_active}")

        # 6. Verify Candidate, Review, Audit, PR, and Telemetry
        active_cand = uow.orchestration_candidates.get_active_by_run(run.run_id)
        if active_cand:
            print(f"Audited Candidate SHA: {active_cand.candidate_sha}")
            print(f"Candidate Generation: {active_cand.generation}")
            print(f"Manifest ID: {active_cand.manifest_id}")

        review = (
            uow.reviews.get_by_job_id(run.active_job_id)
            if run.active_job_id
            else None
        )
        if review:
            print(
                f"Review Verdict: {review.verdict.value if review.verdict else 'None'} ({review.reviewer_executor})"
            )
            print(f"Review Summary: {review.summary}")

        audit = (
            uow.audits.get_by_job_id(run.active_job_id)
            if run.active_job_id
            else None
        )
        if audit:
            print(
                f"DeepSeek Audit Status: {audit.status.value}, Risk: {audit.risk.value if audit.risk else 'None'}"
            )
            print(f"Audit Summary: {audit.summary}")

        updated_binding = uow.bindings.get_by_project_and_change("mini-me", change_name)
        if updated_binding:
            print(f"GitHub PR Number: {updated_binding.github_pr_number}")
            print(f"GitHub PR URL: {updated_binding.github_pr_url}")

        # 7. Record and Display PostgreSQL Telemetry
        telemetry_service = EfficiencyTelemetryService(uow)
        metrics = telemetry_service.record_run_telemetry(run)
        uow.commit()

        print("\n" + "=" * 60)
        print("018.2 AUTONOMOUS PROVING RUN TELEMETRY")
        print("=" * 60)
        print(f"Total Attempts: {metrics.total_attempts}")
        print(f"Attempts by Provider: {metrics.attempts_by_provider}")
        print(f"Productive Attempts: {metrics.productive_attempt_count}")
        print(
            f"Productive Ratio: {metrics.productive_attempt_count / max(1, metrics.total_attempts):.1%}"
        )
        print(f"Same-SHA Retries Suppressed: {metrics.same_sha_retry_suppressed_count}")
        print(f"Bookkeeping Retries: {metrics.bookkeeping_llm_retry_count}")
        print(f"Antigravity Routine Implementations: {metrics.antigravity_routine_impl_count}")
        print(
            f"Reviewer Independence Violations: {metrics.reviewer_independence_violations_count}"
        )

        assert (
            run.stop_outcome == OrchestrationStopOutcome.READY_FOR_HUMAN_MERGE
        ), f"Expected stop_outcome READY_FOR_HUMAN_MERGE, got {run.stop_outcome}"
        assert (
            run.human_gate == HumanGate.READY_FOR_HUMAN_MERGE
        ), f"Expected human_gate READY_FOR_HUMAN_MERGE, got {run.human_gate}"
        print("\n018_2_AUTONOMOUS_PREMERGE_COMPLETE: SUCCESS!")


if __name__ == "__main__":
    run_proving_pilot()
