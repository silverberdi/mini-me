"""Authority-preserving remediation of frozen orchestration candidates."""

from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from minime.domain.enums import (
    HumanGate,
    JobStatus,
    OrchestrationStopOutcome,
    RemediationFailureCode,
    RemediationStatus,
)
from minime.domain.models import CandidateRemediation, OrchestrationCandidate, RemediationContract
from minime.services.candidate_integrity import resolve_base_branch_sha
from minime.services.candidate_manifest import CandidateManifestService
from minime.services.worktree_manager import WorktreeManager


class RemediationError(ValueError):
    def __init__(self, code: RemediationFailureCode, message: str):
        super().__init__(message)
        self.code = code


class CandidateRemediationService:
    """Owns remediation lifecycle; orchestration only delegates to this component."""

    def __init__(
        self,
        uow,
        project_root: str | Path,
        pipeline=None,
        worktree_manager: WorktreeManager | None = None,
        implementer_runner=None,
    ):
        self.uow = uow
        self.project_root = Path(project_root).resolve()
        self.pipeline = pipeline
        self.worktree_manager = worktree_manager or WorktreeManager(self.project_root, uow=uow)
        self.implementer_runner = implementer_runner
        self.manifest_service = CandidateManifestService()

    def _remediations(self):
        repo = getattr(self.uow, "candidate_remediations", None)
        if repo is None:
            raise RemediationError(
                RemediationFailureCode.PRESERVATION_FAILED,
                "Durable candidate remediation repository is unavailable.",
            )
        return repo

    def _get_identity(self, run_id: str, generation: int, sha: str, contract_hash: str):
        return self._remediations().get_by_identity(run_id, generation, sha, contract_hash)

    def _save(self, remediation: CandidateRemediation) -> None:
        self._remediations().save(remediation)

    def _validate_workspace_identity(
        self, remediation: CandidateRemediation, job, change_name: str, generation: int
    ) -> None:
        expected_path = self.worktree_manager.remediation_worktree_path(
            job.job_id, generation
        ).resolve()
        expected_branch = f"minime/{change_name}-{job.job_id}-remediation-gen{generation}"
        if (
            remediation.workspace_path != str(expected_path)
            or remediation.branch_name != expected_branch
        ):
            raise RemediationError(
                RemediationFailureCode.PRESERVATION_FAILED,
                "Persisted remediation workspace identity does not match the managed workspace.",
            )

    def _source_candidate(self, run_id: str):
        candidates = [
            c
            for c in self.uow.orchestration_candidates.list_by_run(run_id)
            if not c.superseded_by_id
        ]
        return candidates[0] if len(candidates) == 1 else None

    def _validate_candidate_ref(self, candidate: OrchestrationCandidate) -> None:
        if not candidate.candidate_ref:
            raise RemediationError(
                RemediationFailureCode.AUTHORITY_MISMATCH,
                "Current candidate has no authoritative candidate ref.",
            )
        proc = subprocess.run(
            ["git", "rev-parse", "--verify", f"{candidate.candidate_ref}^{{commit}}"],
            cwd=self.project_root,
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0 or proc.stdout.strip() != candidate.candidate_sha:
            raise RemediationError(
                RemediationFailureCode.AUTHORITY_MISMATCH,
                "Candidate ref does not resolve to the persisted candidate SHA.",
            )

    def _validate_authority(self, run, job, candidate):
        if run.stop_outcome != OrchestrationStopOutcome.NEEDS_HUMAN or not run.active_job_id:
            raise RemediationError(
                RemediationFailureCode.AUTHORITY_MISMATCH,
                "Remediation requires an active NEEDS_HUMAN run.",
            )
        if (
            not candidate
            or candidate.generation != run.current_generation
            or candidate.candidate_sha != run.current_candidate_sha
        ):
            raise RemediationError(
                RemediationFailureCode.AUTHORITY_MISMATCH,
                "Latest non-superseded candidate does not match run authority.",
            )
        if (
            job.job_id != run.active_job_id
            or job.project_id != run.project_id
            or job.change_name != run.change_name
        ):
            raise RemediationError(
                RemediationFailureCode.AUTHORITY_MISMATCH,
                "Active job does not match run authority.",
            )
        if job.candidate_sha != candidate.candidate_sha or job.base_sha != candidate.base_sha:
            raise RemediationError(
                RemediationFailureCode.AUTHORITY_MISMATCH,
                "Job candidate/base does not match current candidate authority.",
            )
        manifest = (
            self.uow.candidate_manifests.get_by_id(candidate.manifest_id)
            if candidate.manifest_id
            else None
        )
        if (
            not manifest
            or manifest.candidate_sha != candidate.candidate_sha
            or manifest.manifest_hash != candidate.manifest_hash
        ):
            raise RemediationError(
                RemediationFailureCode.AUTHORITY_MISMATCH,
                "Candidate manifest does not match current candidate authority.",
            )
        return manifest

    def _validate_reconciled_authority(self, run, job, source, result) -> None:
        if (
            not result
            or run.current_generation != result.generation
            or run.current_candidate_sha != result.candidate_sha
            or job.candidate_sha != result.candidate_sha
            or job.base_sha != result.base_sha
        ):
            raise RemediationError(
                RemediationFailureCode.PRESERVATION_FAILED,
                "Durable remediation result contradicts current candidate authority.",
            )
        manifest = (
            self.uow.candidate_manifests.get_by_id(result.manifest_id)
            if result.manifest_id
            else None
        )
        if not manifest or manifest.manifest_hash != result.manifest_hash:
            raise RemediationError(
                RemediationFailureCode.PRESERVATION_FAILED,
                "Durable remediation result manifest cannot be reconciled.",
            )

    @staticmethod
    def load_contract(payload: dict[str, Any] | str | Path) -> RemediationContract:
        try:
            data = (
                json.loads(Path(payload).read_text(encoding="utf-8"))
                if isinstance(payload, (str, Path)) and Path(payload).exists()
                else (json.loads(payload) if isinstance(payload, str) else payload)
            )
            return RemediationContract.model_validate(data)
        except (OSError, json.JSONDecodeError, ValidationError, TypeError, ValueError) as exc:
            raise RemediationError(
                RemediationFailureCode.CONTRACT_INVALID, f"Invalid remediation contract: {exc}"
            ) from exc

    async def _run(self, run_id: str, contract: RemediationContract) -> CandidateRemediation:
        run = self.uow.orchestration_runs.get_by_id(run_id)
        if not run:
            raise RemediationError(
                RemediationFailureCode.AUTHORITY_MISMATCH,
                f"Orchestration run '{run_id}' not found.",
            )
        contract_hash = contract.contract_hash()
        replay = self._get_identity(
            run_id,
            contract.source_candidate_generation,
            contract.source_candidate_sha,
            contract_hash,
        )
        if replay and replay.status in {
            RemediationStatus.COMPLETED,
            RemediationStatus.CHECKS_FAILED,
            RemediationStatus.FINALIZED,
        }:
            return replay
        job = self.uow.jobs.get_by_id(run.active_job_id) if run.active_job_id else None
        reconciliation_mode = bool(
            replay
            and replay.result_candidate_id
            and replay.status
            in {RemediationStatus.CANDIDATE_PERSISTED, RemediationStatus.CHECKS_RUNNING}
        )
        candidate = (
            self.uow.orchestration_candidates.get_by_id(replay.source_candidate_id)
            if reconciliation_mode and replay
            else self._source_candidate(run_id)
        )
        if not job:
            raise RemediationError(
                RemediationFailureCode.AUTHORITY_MISMATCH, "Active remediation job is missing."
            )
        if reconciliation_mode and replay:
            result_candidate = self.uow.orchestration_candidates.get_by_id(
                replay.result_candidate_id
            )
            self._validate_reconciled_authority(run, job, candidate, result_candidate)
        else:
            self._validate_authority(run, job, candidate)
        self._validate_candidate_ref(candidate)
        if (
            contract.run_id != run_id
            or contract.change_name != run.change_name
            or contract.source_candidate_generation != candidate.generation
            or contract.source_candidate_sha != candidate.candidate_sha
            or contract.source_candidate_base_sha != candidate.base_sha
        ):
            raise RemediationError(
                RemediationFailureCode.CONTRACT_INVALID,
                "Remediation contract is not bound to the current source candidate.",
            )
        project = self.uow.projects.get_by_id(run.project_id)
        if not project:
            raise RemediationError(
                RemediationFailureCode.AUTHORITY_MISMATCH, "Project authority is missing."
            )
        authoritative_base, base_error = resolve_base_branch_sha(
            self.project_root, project.base_branch
        )
        if not authoritative_base:
            raise RemediationError(
                RemediationFailureCode.AUTHORITY_MISMATCH,
                f"Authoritative base cannot be resolved: {base_error}",
            )
        if authoritative_base != candidate.base_sha:
            raise RemediationError(
                RemediationFailureCode.BASE_ADVANCED_REQUIRES_INTEGRATION,
                "Registered base advanced beyond the source candidate base.",
            )

        existing = self._get_identity(
            run_id, candidate.generation, candidate.candidate_sha, contract_hash
        )
        existing_status = existing.status if existing else None
        existing_tree_fingerprint = existing.tree_fingerprint if existing else None
        if existing and existing.status in {
            RemediationStatus.COMPLETED,
            RemediationStatus.CHECKS_FAILED,
            RemediationStatus.FINALIZED,
        }:
            return existing
        if existing and existing.contract_payload != contract.canonical_payload():
            raise RemediationError(
                RemediationFailureCode.CONTRACT_INVALID,
                "An admitted remediation contract cannot be replaced.",
            )
        if existing and existing.status == RemediationStatus.IMPLEMENTER_RUNNING:
            raise RemediationError(
                RemediationFailureCode.PRESERVATION_FAILED,
                "Provider execution was in-flight at restart; refusing duplicate invocation.",
            )
        remediation = existing or CandidateRemediation(
            run_id=run_id,
            job_id=job.job_id,
            source_candidate_id=candidate.candidate_id,
            source_generation=candidate.generation,
            source_candidate_sha=candidate.candidate_sha,
            source_base_sha=candidate.base_sha,
            contract_version=contract.contract_version,
            contract_hash=contract_hash,
            contract_payload=contract.canonical_payload(),
            authorized_paths=contract.allowed_paths,
        )
        self._save(remediation)
        self.uow.commit()

        generation = candidate.generation + 1
        if existing and existing.status == RemediationStatus.WORKSPACE_READY:
            self._validate_workspace_identity(existing, job, run.change_name, generation)
        reconciled_commit = None
        if (
            existing_status == RemediationStatus.SCOPE_VALIDATED
            and existing
            and existing.result_candidate_id is None
        ):
            reconciled_commit = await self.worktree_manager.reconcile_remediation_worktree(
                job.job_id,
                run.change_name,
                candidate.candidate_sha,
                generation,
                remediation.remediation_id,
                contract_hash,
                contract.allowed_paths,
            )
        workspace_source_sha = (
            existing.result_candidate_sha
            if existing
            and existing.status
            in {RemediationStatus.CANDIDATE_PERSISTED, RemediationStatus.CHECKS_RUNNING}
            and existing.result_candidate_sha
            else candidate.candidate_sha
        )
        workspace = reconciled_commit or await self.worktree_manager.create_remediation_worktree(
            job.job_id,
            run.change_name,
            workspace_source_sha,
            generation,
            project_id=run.project_id,
        )
        if existing is None:
            remediation.status = RemediationStatus.WORKSPACE_READY
        remediation.workspace_path = str(workspace.path)
        remediation.branch_name = workspace.branch_name
        remediation.authorized_paths = contract.allowed_paths
        self._save(remediation)
        self.uow.commit()

        runner = self.implementer_runner or (
            self.pipeline.implementer_runner if self.pipeline is not None else None
        )
        if runner is None and remediation.status == RemediationStatus.WORKSPACE_READY:
            remediation.status = RemediationStatus.FAILED
            remediation.failure_code = RemediationFailureCode.PROVIDER_UNAVAILABLE
            remediation.failure_reason = "No remediation implementer is configured."
            self._save(remediation)
            self.uow.commit()
            raise RemediationError(remediation.failure_code, remediation.failure_reason)
        if remediation.status not in {
            RemediationStatus.IMPLEMENTER_COMPLETED,
            RemediationStatus.SCOPE_VALIDATED,
            RemediationStatus.CANDIDATE_PERSISTED,
            RemediationStatus.CHECKS_RUNNING,
        }:
            remediation.status = RemediationStatus.IMPLEMENTER_RUNNING
            self._save(remediation)
            self.uow.commit()
        prompt = "\n".join(
            [
                "EXECUTE ONLY THIS IMMUTABLE REMEDIATION CONTRACT.",
                f"Contract hash: {contract_hash}",
                f"Worktree: {workspace.path}",
                json.dumps(contract.canonical_payload(), sort_keys=True, indent=2),
                "Do not modify the contract or protected paths. Return a structured blocker if required work is outside this contract.",
            ]
        )
        result = None
        if remediation.status == RemediationStatus.IMPLEMENTER_RUNNING:
            result = await runner.run(workspace.path, prompt, 3600)
        if result is not None and result.exit_code != 0:
            remediation.status = RemediationStatus.NEEDS_HUMAN
            remediation.failure_code = RemediationFailureCode.PROVIDER_UNAVAILABLE
            remediation.failure_reason = "Remediation implementer did not complete successfully."
            self._save(remediation)
            self.uow.commit()
            raise RemediationError(remediation.failure_code, remediation.failure_reason)

        if remediation.status == RemediationStatus.IMPLEMENTER_RUNNING:
            remediation.status = RemediationStatus.IMPLEMENTER_COMPLETED
            self._save(remediation)
            self.uow.commit()

        persisted_boundary = (
            existing is not None
            and existing.result_candidate_id is not None
            and existing.status
            in {RemediationStatus.CANDIDATE_PERSISTED, RemediationStatus.CHECKS_RUNNING}
        )
        if reconciled_commit:
            new_sha = await self.worktree_manager.current_sha(reconciled_commit.path)
        elif persisted_boundary:
            new_candidate = self.uow.orchestration_candidates.get_by_id(
                existing.result_candidate_id
            )
            if not new_candidate:
                raise RemediationError(
                    RemediationFailureCode.PRESERVATION_FAILED,
                    "Durable remediation result points to a missing candidate.",
                )
            (
                reconciled,
                reconciliation_error,
            ) = await self.worktree_manager.verify_remediation_commit(
                workspace.path,
                candidate.candidate_sha,
                workspace.branch_name,
                remediation.remediation_id,
                contract_hash,
                contract.allowed_paths,
            )
            if not reconciled:
                raise RemediationError(
                    RemediationFailureCode.PRESERVATION_FAILED,
                    reconciliation_error or "Remediation commit reconciliation failed.",
                )
            new_sha = new_candidate.candidate_sha
        else:
            changed = set(
                await self.worktree_manager.changed_paths_since(
                    workspace.path, candidate.candidate_sha
                )
            )
            allowed = set(contract.allowed_paths)
            protected = set(contract.protected_paths) | {
                "openspec/changes/011-preserved-candidate-remediation-generations",
                ".minime",
            }
            if (
                not changed
                or not changed.issubset(allowed)
                or any(
                    p == x or p.startswith(x.rstrip("/") + "/") for p in changed for x in protected
                )
            ):
                remediation.status = RemediationStatus.SCOPE_FAILED
                remediation.failure_code = (
                    RemediationFailureCode.NO_PROGRESS
                    if not changed
                    else RemediationFailureCode.SCOPE_VIOLATION
                )
                remediation.failure_reason = (
                    "No authorized progress."
                    if not changed
                    else f"Unauthorized changed paths: {sorted(changed - allowed)}"
                )
                self._save(remediation)
                self.uow.commit()
                raise RemediationError(remediation.failure_code, remediation.failure_reason)

            remediation.status = RemediationStatus.SCOPE_VALIDATED
            remediation.tree_fingerprint = await self.worktree_manager.working_state_fingerprint(
                workspace.path
            )
            if (
                existing_status == RemediationStatus.SCOPE_VALIDATED
                and remediation.tree_fingerprint != existing_tree_fingerprint
            ):
                raise RemediationError(
                    RemediationFailureCode.PRESERVATION_FAILED,
                    "Validated remediation workspace state changed before finalization.",
                )
            self._save(remediation)
            self.uow.commit()

            if existing_status == RemediationStatus.SCOPE_VALIDATED:
                new_sha = await self.worktree_manager.finalize_candidate_commit(
                    workspace.path,
                    job.job_id,
                    run.project_id,
                    remediation.remediation_id,
                    contract_hash,
                )
            else:
                new_sha = await self.worktree_manager.finalize_candidate_commit(
                    workspace.path,
                    job.job_id,
                    run.project_id,
                    remediation.remediation_id,
                    contract_hash,
                )
        if not persisted_boundary:
            new_manifest = self.manifest_service.generate_manifest(
                workspace.path, new_sha, job.job_id
            )
            self.uow.candidate_manifests.save(new_manifest)
            new_candidate = OrchestrationCandidate(
                run_id=run_id,
                generation=generation,
                base_sha=candidate.base_sha,
                candidate_sha=new_sha,
                candidate_ref=f"refs/heads/{workspace.branch_name}",
                manifest_id=new_manifest.manifest_id,
                manifest_hash=new_manifest.manifest_hash,
                authorship_summary={"remediation_id": remediation.remediation_id},
                is_frozen=True,
            )
            self.uow.orchestration_candidates.save(new_candidate)
            self.uow.orchestration_candidates.supersede(
                candidate.candidate_id, new_candidate.candidate_id
            )
            job.candidate_sha = new_sha
            job.base_sha = candidate.base_sha
            self.uow.jobs.save(job)
            self.uow.orchestration_runs.update_candidate_binding(run_id, generation, new_sha)
            remediation.status = RemediationStatus.CANDIDATE_PERSISTED
            remediation.result_candidate_id = new_candidate.candidate_id
            remediation.result_generation = generation
            remediation.result_candidate_sha = new_sha
            self._save(remediation)
            self.uow.commit()

        remediation.status = RemediationStatus.CHECKS_RUNNING
        self._save(remediation)
        self.uow.commit()
        checks = (
            await self.pipeline.checks_runner.run(
                job.job_id,
                project.checks,
                workspace.path,
                candidate_sha=new_sha,
                candidate_generation=generation,
            )
            if self.pipeline
            else None
        )
        if checks:
            for result in checks.results:
                self.uow.check_results.save(result)
            for diagnostic in checks.diagnostics:
                self.uow.evidence_diagnostics.save(diagnostic)
            remediation.status = (
                RemediationStatus.COMPLETED if checks.passed else RemediationStatus.CHECKS_FAILED
            )
            job.status = JobStatus.CHECKS_PASSED if checks.passed else JobStatus.CHECKS_FAILED
            self.uow.jobs.save(job)
            if not checks.passed:
                remediation.failure_code = RemediationFailureCode.CHECKS_FAILED
                remediation.failure_reason = "One or more deterministic checks failed."
                self.uow.orchestration_runs.update_stop_outcome(
                    run_id,
                    OrchestrationStopOutcome.NEEDS_HUMAN,
                    HumanGate.NEEDS_HUMAN,
                    remediation.failure_reason,
                    {"code": remediation.failure_code.value},
                )
            self._save(remediation)
            self.uow.commit()
        return remediation

    def remediate(
        self, run_id: str, contract: RemediationContract | dict[str, Any] | str | Path
    ) -> CandidateRemediation:
        if not isinstance(contract, RemediationContract):
            contract = self.load_contract(contract)
        try:
            return asyncio.run(self._run(run_id, contract))
        except RemediationError:
            raise
