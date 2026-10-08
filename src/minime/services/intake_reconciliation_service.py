"""Narrow, checkpointed reconciliation for abandoned intake preparation."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from minime.domain.enums import (
    ChangeStatus,
    ExternalActionStatus,
    ExternalActionType,
    ExternalOutcome,
    ExternalReasonCode,
    IntakeReconciliationDisposition,
    SagaStatus,
    SagaType,
    WorkItemSource,
    WorkItemStatus,
    WorkspaceOperation,
)
from minime.domain.models import (
    ExternalActionResult,
    RecoveryClaimContext,
    WorkspaceMutationRequest,
    validate_claim_context_authoritative,
)
from minime.services.context_discovery_service import ContextDiscoveryService
from minime.services.lifecycle_transition_authority import LifecycleTransitionAuthority
from minime.services.openspec_generator import OpenSpecGenerator
from minime.services.saga_engine import SagaEngine
from minime.services.workspace_guard import ManagedWorkspaceGuard


@dataclass(frozen=True)
class IntakeReconciliationResult:
    project_id: str
    item_key: str
    change_name: str
    disposition: IntakeReconciliationDisposition
    issue_reconciled: bool
    openspec_reconciled: bool
    backlog_status: WorkItemStatus
    change_status: ChangeStatus
    saga_status: SagaStatus
    already_converged: bool


class IntakeReconciliationService:
    def __init__(self, uow, project_root: str | Path = ".", github_adapter=None, context_discovery_service=None):
        self.uow = uow
        self.project_root = Path(project_root).resolve()
        self.github_adapter = github_adapter
        self.context_discovery_service = context_discovery_service
        self.saga_engine = SagaEngine(uow)

    def reconcile_abandoned_intake(
        self,
        project_id: str,
        item_key: str,
        disposition: IntakeReconciliationDisposition,
        claim_context: RecoveryClaimContext,
    ) -> IntakeReconciliationResult:
        validate_claim_context_authoritative(self.uow, claim_context)
        if claim_context.claim_key != f"intake:{project_id}:{item_key}":
            raise ValueError("reconciliation claim does not own this intake item")

        project = self.uow.projects.get_by_id(project_id)
        item = self.uow.backlog_items.get_by_project_and_key(project_id, item_key)
        binding = self.uow.project_managed_repository_bindings.get_by_project_id(project_id)
        if not project or not item or not binding:
            raise ValueError("project, backlog item, and managed binding are required")

        change_name = item.openspec_change_name or item.item_key
        change = self.uow.changes.get_by_name(project_id, change_name)
        if not change:
            raise ValueError("change record is required")

        saga = self.uow.durable_sagas.get_active_saga(project_id, item_key, SagaType.INTAKE)
        if not saga:
            existing_sagas = self.uow.durable_sagas.list_by_project(project_id, saga_type=SagaType.INTAKE)
            saga = next((s for s in existing_sagas if s.work_item_key == item_key), None)

        if not saga:
            raise ValueError("active intake saga required")

        if saga.change_name and saga.change_name != change_name:
            raise ValueError("intake identity mismatch")

        if saga.saga_type != SagaType.INTAKE:
            raise ValueError("intake identity mismatch")

        if self.uow.orchestration_runs.get_active_run(project_id, change_name):
            raise ValueError("active run prevents intake reconciliation")

        if any(j.project_id == project_id and j.change_name == change_name for j in self.uow.jobs.list_active_jobs()):
            raise ValueError("active job prevents intake reconciliation")

        discovery = self.context_discovery_service or ContextDiscoveryService(self.uow, self.project_root)
        _, projections = discovery.discover_context_pure(project_id)
        projection = next((x for x in projections if x.item_key == item_key), None)

        if disposition == IntakeReconciliationDisposition.INVALID_DISCOVERY:
            if projection is not None:
                raise ValueError("INVALID_DISCOVERY requires item absence from pure discovery")
            target_item, target_change, reason = WorkItemStatus.CANCELLED, ChangeStatus.CANCELLED, "INVALID_DISCOVERY"
        elif disposition == IntakeReconciliationDisposition.DEFERRED_ROADMAP:
            if item.source != WorkItemSource.ROADMAP:
                raise ValueError("DEFERRED_ROADMAP requires a ROADMAP source item")
            if projection is None or projection.status == WorkItemStatus.READY:
                raise ValueError("DEFERRED_ROADMAP requires a non-ready ROADMAP projection")
            target_item, target_change, reason = WorkItemStatus.BLOCKED, ChangeStatus.BLOCKED, "ROADMAP_NOT_PREPARATION_ELIGIBLE"
        else:
            raise ValueError("unsupported reconciliation disposition")

        if saga.status == SagaStatus.CANCELLED and item.status == target_item and change.status == target_change:
            return IntakeReconciliationResult(
                project_id=project_id,
                item_key=item_key,
                change_name=change_name,
                disposition=disposition,
                issue_reconciled=True,
                openspec_reconciled=True,
                backlog_status=item.status,
                change_status=change.status,
                saga_status=saga.status,
                already_converged=True,
            )

        issue_key = f"issue_create:{project_id}:{change_name}"
        author_key = f"openspec_author:{project_id}:{change_name}"
        issue_action = self.uow.orchestration_external_actions.get_by_action_key(issue_key)
        author_action = self.uow.orchestration_external_actions.get_by_action_key(author_key)

        if not issue_action or issue_action.action_type != ExternalActionType.ISSUE_CREATE or issue_action.status != ExternalActionStatus.COMPLETED or not issue_action.remote_identifier:
            raise ValueError("missing exact completed intake ISSUE_CREATE evidence")
        if issue_action.saga_id != saga.id:
            raise ValueError("wrong ISSUE_CREATE saga")
        if not author_action or author_action.action_type != ExternalActionType.OPENSPEC_SYNC or author_action.status != ExternalActionStatus.COMPLETED:
            raise ValueError("missing exact completed intake OPENSPEC_SYNC evidence")

        number = int(issue_action.remote_identifier)
        if item.github_issue_number and item.github_issue_number != number:
            raise ValueError("backlog issue conflicts with intake action")

        if self.github_adapter is None:
            raise ValueError("GitHub adapter required")

        marker = f"<!-- minime-opkey: {issue_key} -->"

        def observe_issue() -> ExternalActionResult:
            res = self.github_adapter.get_issue(project.repository, number)
            if not res or res.outcome != ExternalOutcome.SUCCESS or not res.data or marker not in res.data.get("body", ""):
                return ExternalActionResult(outcome=ExternalOutcome.UNKNOWN, source_adapter="github")
            if res.data.get("state") == "closed":
                return ExternalActionResult(outcome=ExternalOutcome.SUCCESS, source_adapter="github", external_id=str(number))
            return ExternalActionResult(outcome=ExternalOutcome.FAILURE, reason_code=ExternalReasonCode.NOT_FOUND, source_adapter="github")

        def close_issue() -> ExternalActionResult:
            return self.github_adapter.close_issue(
                project.repository,
                number,
                comment=f"Closed automatically by mini me because intake preparation was canonically reconciled as {disposition.value}.",
            )

        issue_result = self.saga_engine.execute_fenced_external_action(
            claim_context=claim_context,
            action_key=f"intake_reconcile_issue_close:{project_id}:{change_name}",
            action_type=ExternalActionType.ISSUE_CLOSE,
            target_identity=change_name,
            request_fingerprint=item_key,
            mutation_fn=close_issue,
            saga_id=saga.id,
            observation_fn=observe_issue,
        )

        if not issue_result or issue_result.outcome != ExternalOutcome.SUCCESS:
            raise ValueError("issue close checkpoint not proven")

        self._rollback_artifacts(project, binding, item, saga, claim_context)

        authority = LifecycleTransitionAuthority(self.uow)
        if item.status != target_item:
            authority.transition_backlog_item(project_id, item_key, item.status, target_item, reason_code=reason, actor="intake-reconciliation")
        if change.status != target_change:
            authority.transition_change(project_id, change_name, change.status, target_change, reason_code=reason, actor="intake-reconciliation")

        saga_cur = self.uow.durable_sagas.get_by_id(saga.id)
        if saga_cur and saga_cur.status != SagaStatus.CANCELLED:
            saga_cur = self.saga_engine.cancel_saga(saga_cur, f"intake reconciled: {reason}", claim_context)

        item_final = self.uow.backlog_items.get_by_project_and_key(project_id, item_key)
        change_final = self.uow.changes.get_by_name(project_id, change_name)
        saga_final = self.uow.durable_sagas.get_by_id(saga.id)

        return IntakeReconciliationResult(
            project_id=project_id,
            item_key=item_key,
            change_name=change_name,
            disposition=disposition,
            issue_reconciled=True,
            openspec_reconciled=True,
            backlog_status=item_final.status,
            change_status=change_final.status,
            saga_status=saga_final.status,
            already_converged=False,
        )

    def _rollback_artifacts(self, project, binding, item, saga, claim_context):
        target = Path(binding.managed_repository_root) / project.openspec_path / "changes" / saga.change_name

        guard = ManagedWorkspaceGuard(self.uow)
        decision = guard.evaluate_mutation(
            WorkspaceMutationRequest(
                project_id=project.project_id,
                target_path=str(target),
                requested_operation=WorkspaceOperation.OPENSPEC_SYNC,
            )
        )
        if not decision.allowed:
            raise ValueError("managed workspace guard denied rollback")

        def observe() -> ExternalActionResult:
            if not target.exists():
                return ExternalActionResult(outcome=ExternalOutcome.SUCCESS, source_adapter="filesystem")
            return ExternalActionResult(outcome=ExternalOutcome.FAILURE, reason_code=ExternalReasonCode.NOT_FOUND, source_adapter="filesystem")

        def mutate() -> ExternalActionResult:
            if not target.exists():
                return ExternalActionResult(outcome=ExternalOutcome.SUCCESS, source_adapter="filesystem")

            if target.is_symlink():
                raise ValueError("symlink escape rejects rollback")

            for p in target.rglob("*"):
                if p.is_symlink():
                    raise ValueError("symlink escape rejects rollback")
                try:
                    p.resolve().relative_to(target.resolve())
                except ValueError:
                    raise ValueError("symlink escape rejects rollback")

            tracked = subprocess.run(
                ["git", "-C", str(binding.managed_repository_root), "ls-files", "--", str(target)],
                capture_output=True,
                text=True,
            ).stdout.strip()

            if tracked:
                raise ValueError("tracked file rejects rollback")

            generator = OpenSpecGenerator(self.project_root, self.uow)
            generated = generator.generate_from_backlog_item(item, project.display_name)
            manifest = generator.build_artifact_manifest(generated)
            allowed = set(manifest.files)

            actual = {str(p.relative_to(target)) for p in target.rglob("*") if p.is_file()}

            if actual != allowed:
                raise ValueError("unexpected untracked file rejects rollback")

            for p in sorted((p for p in target.rglob("*") if p.is_file()), reverse=True):
                p.unlink()
            for p in sorted((p for p in target.rglob("*") if p.is_dir()), reverse=True):
                p.rmdir()
            if target.exists():
                target.rmdir()

            return ExternalActionResult(outcome=ExternalOutcome.SUCCESS, source_adapter="filesystem")

        result = self.saga_engine.execute_fenced_external_action(
            claim_context=claim_context,
            action_key=f"intake_openspec_rollback:{project.project_id}:{saga.change_name}",
            action_type=ExternalActionType.OPENSPEC_ROLLBACK,
            target_identity=saga.change_name,
            request_fingerprint=item.item_key,
            mutation_fn=mutate,
            saga_id=saga.id,
            observation_fn=observe,
        )

        if not result or result.outcome != ExternalOutcome.SUCCESS:
            raise ValueError("OpenSpec rollback checkpoint not proven")
