"""Native OpenSpec orchestration coordinator for end-to-end request lifecycle."""

from __future__ import annotations

import ast
import asyncio
import hashlib
import inspect
import json
import os
import re
import shlex
import signal
from dataclasses import dataclass
from dataclasses import replace as dataclass_replace
from pathlib import Path
from typing import Any
from uuid import uuid4

from minime.adapters.github import GitHubAdapter
from minime.adapters.openspec import OpenSpecAdapter
from minime.domain.enums import (
    ExternalActionStatus,
    ExternalActionType,
    ExternalOutcome,
    HumanGate,
    OperatorActionStatus,
    OperatorActionType,
    OrchestrationStage,
    OrchestrationStopOutcome,
)
from minime.domain.interfaces import PersistenceUnitOfWork
from minime.domain.models import (
    DispatchAuthorization,
    ExternalActionResult,
    get_active_human_payload,
    OperatorActionRecord,
    OrchestrationExternalAction,
    OrchestrationRun,
    OrchestrationStageEvent,
    RecoveryClaimContext,
    utc_now,
)
from minime.logging import get_logger, redact_secrets
from minime.services.agent_confinement import (
    process_group_state,
    process_identity,
    process_identity_state,
)
from minime.services.agent_runner import (
    CliAgentRunner,
    NativeOpenSpecWorkflowUnavailable,
    ResolvedWorkflow,
)
from minime.services.pr_preparer_service import PrPreparationInput, PrPreparerService
from minime.services.remote_request_intake import RemoteRequestIntakeService
from minime.services.request_normalization import (
    NormalizedRequest,
    RequestNormalizationError,
    RequestNormalizationService,
    looks_like_complete_gherkin,
    validate_normalized_body,
)
from minime.services.review_verdict_parser import MalformedReviewOutputError, parse_review_verdict
from minime.services.worktree_manager import WorktreeManager

logger = get_logger("services.orchestration_coordinator")

_SENSITIVE_RESPONSE_KEYS = (
    "api_key",
    "apikey",
    "access_key",
    "client_secret",
    "password",
    "private_key",
    "secret",
    "token",
)

# Semantic roles used by the coordinator map to persisted profile keys. Keep a
# single source of truth so provider and model resolution can never drift apart.
_ROLE_TO_PROFILE_KEY = {"reviewer": "independent_review"}

# Review reentry outcomes, produced by a single fail-closed classifier shared by
# the proposal-review and code-review stages.
_REVIEW_ADVANCE = "advance"
_REVIEW_REJECTED = "rejected"
_REVIEW_CORRUPT = "corrupt"
_REVIEW_TECHNICAL_FAILURE = "technical_failure"
_REVIEW_AMBIGUOUS = "ambiguous"
_REVIEW_STALE = "stale"

# Exact output contract for independent reviews. parse_review_verdict rejects
# anything that does not match this shape, so the prompt must state it verbatim —
# field names, severity enum, and the READY_TO_MERGE ⇔ empty-findings invariant —
# or an API-backed model emits prose-shaped JSON and the review fails closed as
# invalid_response.
_REVIEW_VERDICT_SCHEMA_HINT = (
    "Return exactly one JSON object matching this schema: "
    '{"verdict":"READY_TO_MERGE|CHANGES_REQUIRED",'
    '"summary":"brief concrete result",'
    '"findings":[{"severity":"BLOCKER|MAJOR|MINOR",'
    '"location":"file or requirement",'
    '"violated_requirement":"what was violated",'
    '"expected_correction":"what must change"}]}. '
    "Use READY_TO_MERGE only when the review is clean and findings is empty; otherwise "
    "use CHANGES_REQUIRED with at least one concrete finding."
)


def _quarantine_response_content(raw_response: str) -> str:
    """Retain rejected JSON diagnostically while masking sensitive fields."""
    try:
        payload = json.loads(raw_response)
    except json.JSONDecodeError:
        return redact_secrets(raw_response)

    def scrub(value: Any, key: str | None = None) -> Any:
        normalized_key = (key or "").lower().replace("-", "_")
        if any(marker in normalized_key for marker in _SENSITIVE_RESPONSE_KEYS):
            return "[REDACTED]"
        if isinstance(value, dict):
            return {
                str(item_key): scrub(item_value, str(item_key))
                for item_key, item_value in value.items()
            }
        if isinstance(value, list):
            return [scrub(item) for item in value]
        return redact_secrets(value)

    return json.dumps(scrub(payload), ensure_ascii=False, sort_keys=True)


@dataclass(frozen=True)
class OrchestrationCoordinationResult:
    status: str  # "COMPLETED", "HUMAN_REQUIRED", "WAITING_CAPACITY", "PAUSED", "FAILED", "IDLE"
    run_id: str | None
    current_stage: OrchestrationStage
    message: str
    pr1_url: str | None = None
    pr2_url: str | None = None
    human_payload: dict[str, Any] | None = None


@dataclass(frozen=True)
class GitCommandResult:
    args: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


@dataclass(frozen=True)
class ApplyOutcome:
    status: str
    completed_tasks: tuple[str, ...]
    pending_tasks: tuple[str, ...]
    candidate_sha: str | None
    changed_files: tuple[str, ...]
    diff_fingerprint: str | None
    tests_passed: bool | None
    test_evidence: str
    error: str | None = None
    human_question: str | None = None
    human_options: tuple[str, ...] = ()
    branch: str | None = None
    worktree: str | None = None
    run_id: str | None = None

    def __bool__(self) -> bool:
        return self.status == "COMPLETE"


@dataclass(frozen=True)
class VerifyOutcome:
    status: str
    summary: str = ""
    human_question: str | None = None
    human_options: tuple[str, ...] = ()
    findings: tuple[dict[str, Any], ...] = ()

    def __bool__(self) -> bool:
        return self.status == "COMPLETE"


@dataclass(frozen=True)
class StageInvocation:
    attempt_id: str
    claim: RecoveryClaimContext
    claim_key: str
    candidate: dict[str, Any]
    recovery_count: int
    started_monotonic: float


class NativeStageHumanRequired(RuntimeError):
    """Preserved native workflow handoff from a DOC_CLOSING invocation."""

    def __init__(self, operation: str, question: str, options: tuple[str, ...]):
        super().__init__(question)
        self.operation = operation
        self.question = question
        self.options = options


@dataclass(frozen=True)
class ComplexityAssessment:
    """Typed, fail-closed result of the thinking-agent complexity stage."""

    status: str
    complexity: str | None = None
    evidence: str | None = None
    reason: str | None = None
    exit_code: int | None = None
    timed_out: bool = False
    preflight_error: str | None = None
    output: str = ""
    structured_output: str = ""
    diagnostic_output: str = ""
    output_truncated: bool = False
    structured_output_missing: bool = False
    structured_output_too_large: bool = False

    @property
    def is_valid(self) -> bool:
        return self.status == "VALID" and self.complexity is not None and bool(self.evidence)


class GitOperationError(RuntimeError):
    """A git operation failed and must be recoverable without advancing the run."""

    def __init__(self, result: GitCommandResult) -> None:
        super().__init__(
            f"git {' '.join(result.args)} failed ({result.returncode}): {result.stderr.strip()}"
        )
        self.result = result


class ReviewResult(dict):
    """Structured review execution result that maintains boolean truthiness compatibility."""

    def __bool__(self) -> bool:
        return self.get("status") == "approved"


class NativeOrchestrationCoordinator:
    """Coordinates the end-to-end lifecycle of remote requests through native OpenSpec."""

    def __init__(
        self,
        uow_factory: Any,
        github_adapter: GitHubAdapter,
        worktree_manager: WorktreeManager,
        agent_runner: CliAgentRunner,
        openspec_adapter: OpenSpecAdapter | None = None,
        pr_preparer: PrPreparerService | None = None,
        semantic_pr_agent: bool = False,
        max_correction_attempts: int = 3,
    ) -> None:
        self.uow_factory = uow_factory
        self.github_adapter = github_adapter
        self.worktree_manager = worktree_manager
        self.agent_runner = agent_runner
        self.openspec_adapter = openspec_adapter or OpenSpecAdapter()
        self.pr_preparer = pr_preparer or PrPreparerService()
        self.semantic_pr_agent = semantic_pr_agent
        self.max_correction_attempts = max_correction_attempts

    @staticmethod
    def _safe_human_payload(payload: Any) -> dict[str, Any]:
        """Redact agent text once before it becomes durable or operator-visible."""
        clean = redact_secrets(payload)
        return clean if isinstance(clean, dict) else {}

    @staticmethod
    def _stage_recovery_is_safe(
        coordinator: Any,
        workflow_process: Any,
        current_process: Any,
        *,
        candidate_matches: bool,
        recovery_count: int,
    ) -> bool:
        """Pure fail-closed gate for the only automatic stage retry."""
        if (
            not candidate_matches
            or recovery_count >= 1
            or not isinstance(coordinator, dict)
            or not isinstance(workflow_process, dict)
            or coordinator.get("status") != "AVAILABLE"
            or workflow_process.get("status") != "AVAILABLE"
            or coordinator.get("host") != current_process.get("host")
            or coordinator.get("boot_id") != current_process.get("boot_id")
        ):
            return False
        return (
            process_identity_state(coordinator) == "GONE"
            and process_identity_state(workflow_process) == "GONE"
            and process_group_state(workflow_process.get("pgid")) == "GONE"
        )

    def _record_current_human_gate(
        self,
        uow: Any,
        run: OrchestrationRun,
        *,
        gate: str,
        question: str,
        options: list[Any] | tuple[Any, ...] = (),
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Replace and persist the one active operator request for this Run."""
        choice_list = list(options) if isinstance(options, (list, tuple)) else []
        active_payload = {
            **(payload or {}),
            "gate_id": str(uuid4()),
            "gate": gate,
            "stage": run.current_stage.value,
            "run_id": run.run_id,
            "question": question,
            "options": choice_list,
        }
        active_payload = self._safe_human_payload(active_payload)
        details = dict(run.stop_details or {})
        details["human_payload"] = active_payload
        run.stop_details = details
        run.human_gate = HumanGate.NEEDS_HUMAN
        run.stop_outcome = OrchestrationStopOutcome.NEEDS_HUMAN
        run.stop_reason = question

        runs = getattr(uow, "orchestration_runs", None)
        updater = getattr(runs, "update_stop_outcome", None)
        if callable(updater):
            updater(
                run.run_id,
                OrchestrationStopOutcome.NEEDS_HUMAN,
                HumanGate.NEEDS_HUMAN,
                question,
                details,
                is_active=run.is_active,
            )
        elif runs is not None:
            runs.save(run)
        if hasattr(uow, "commit"):
            uow.commit()
        return active_payload

    def _clear_current_human_gate(
        self, uow: Any, run: OrchestrationRun, *, response_text: str | None = None
    ) -> None:
        """Clear an active gate only after its existing flow confirms resolution."""
        details = dict(run.stop_details or {})
        payload = get_active_human_payload(run)
        has_active_gate = (
            (isinstance(payload, dict) and bool(payload))
            or run.human_gate == HumanGate.NEEDS_HUMAN
            or run.stop_outcome == OrchestrationStopOutcome.NEEDS_HUMAN
            or (isinstance(details.get("explore_checkpoint"), dict) and details["explore_checkpoint"].get("status") == "HUMAN_REQUIRED")
            or (isinstance(details.get("propose_human_required"), dict) and details["propose_human_required"].get("status") == "HUMAN_REQUIRED")
        )
        if not has_active_gate:
            return

        # Atomically record gate resolution into resolved_human_gates audit log
        if isinstance(payload, dict) and payload:
            resolved_entry = {
                "gate_id": payload.get("gate_id"),
                "gate": payload.get("gate"),
                "stage": run.current_stage.value if hasattr(run.current_stage, "value") else str(run.current_stage),
                "question": payload.get("question"),
                "response": redact_secrets(response_text) if response_text else None,
                "resolved_at": utc_now().isoformat(),
            }
            resolved_list = list(details.get("resolved_human_gates") or [])
            resolved_list.append(resolved_entry)
            details["resolved_human_gates"] = resolved_list

        # Mark explore/propose checkpoints resolved so they cannot resurface as zombies
        if isinstance(details.get("explore_checkpoint"), dict):
            if details["explore_checkpoint"].get("status") == "HUMAN_REQUIRED":
                details["explore_checkpoint"]["status"] = "RESOLVED"
        if isinstance(details.get("propose_human_required"), dict):
            details["propose_human_required"]["status"] = "RESOLVED"

        details.pop("human_payload", None)
        run.stop_details = details
        run.human_gate = None
        run.stop_outcome = None
        run.stop_reason = None
        runs = getattr(uow, "orchestration_runs", None)
        updater = getattr(runs, "update_stop_outcome", None)
        if callable(updater):
            updater(
                run.run_id,
                None,
                None,
                None,
                details,
                is_active=run.is_active,
            )
        elif runs is not None:
            runs.save(run)
        if hasattr(uow, "commit"):
            uow.commit()

    def _record_pr1_acknowledgement_gate(
        self,
        uow: Any,
        run: OrchestrationRun,
        *,
        issue_number: int,
        issue_title: str,
        pr_number: int,
    ) -> dict[str, Any]:
        question = "Por favor confirme con «Estoy enterado» para proceder a la fusión remota."
        return self._record_current_human_gate(
            uow,
            run,
            gate="pr1_merge_acknowledgement",
            question=question,
            options=["Estoy enterado"],
            payload={
                "action": "operator_ack",
                "summary_es": f"Cambio de alta complejidad para el Issue #{issue_number}: {issue_title}. PR #{pr_number} listo para fusión.",
                "prompt": question,
            },
        )

    async def _stage_candidate_identity(
        self, run: OrchestrationRun, worktree_path: Path, stage: str
    ) -> dict[str, Any]:
        head = await self._git_run(worktree_path, ["rev-parse", "HEAD"])
        branch = await self._git_run(worktree_path, ["branch", "--show-current"])
        diff = await self._git_run(worktree_path, ["diff", "--binary", "HEAD"])
        status = await self._git_run(worktree_path, ["status", "--porcelain"])
        untracked = await self._git_run(
            worktree_path, ["ls-files", "--others", "--exclude-standard", "-z"]
        )
        untracked_hashes: list[tuple[str, str]] = []
        for relative in sorted(path for path in untracked.stdout.split("\0") if path):
            candidate_path = worktree_path / relative
            if candidate_path.is_symlink():
                content = os.readlink(candidate_path).encode()
            elif candidate_path.is_file():
                content = candidate_path.read_bytes()
            else:
                content = b""
            untracked_hashes.append((relative, hashlib.sha256(content).hexdigest()))
        candidate_fingerprint = hashlib.sha256(
            diff.stdout.encode() + status.stdout.encode()
            + json.dumps(untracked_hashes, sort_keys=True).encode()
        ).hexdigest()
        payload = {
            "run_id": run.run_id,
            "stage": stage,
            "worktree": str(worktree_path.resolve()),
            "branch": branch.stdout.strip(),
            "generation": int(run.current_generation or 0),
            "candidate_sha": head.stdout.strip(),
            "candidate_fingerprint": candidate_fingerprint,
        }
        payload["fingerprint"] = hashlib.sha256(
            json.dumps(payload, sort_keys=True).encode()
        ).hexdigest()
        return payload

    def _save_stage_invocation_event(
        self, uow: Any, run: OrchestrationRun, event_type: str, evidence: dict[str, Any]
    ) -> None:
        repository = getattr(uow, "orchestration_stage_events", None)
        if repository is None or not callable(getattr(repository, "save", None)):
            raise RuntimeError("Durable stage invocation journal is unavailable")
        repository.save(
            OrchestrationStageEvent(
                run_id=run.run_id,
                from_stage=run.current_stage,
                to_stage=run.current_stage,
                event_type=event_type,
                evidence_references=redact_secrets(evidence),
            )
        )
        uow.commit()

    async def _begin_stage_invocation(
        self, uow: Any, run: OrchestrationRun, worktree_path: Path, stage: str,
        *, allow_human_resume: bool = False, authorized_retry: bool = False,
    ) -> StageInvocation | None:
        claims = getattr(uow, "claims", None)
        if claims is None or not all(
            callable(getattr(claims, method, None))
            for method in ("get_by_key", "acquire_or_reacquire", "validate_cas", "release_claim")
        ):
            return None
        candidate = await self._stage_candidate_identity(run, worktree_path, stage)
        claim_prefix = f"stage-invocation:{run.run_id}:{stage}:"
        claim_key = f"{claim_prefix}{candidate['fingerprint']}"
        prior_claim = claims.get_by_key(claim_key)
        events_repo = getattr(uow, "orchestration_stage_events", None)
        if events_repo is None or not callable(getattr(events_repo, "list_by_run", None)):
            return None
        prior_events = events_repo.list_by_run(run.run_id)
        all_stage_events = [
            event for event in prior_events
            if str((event.evidence_references or {}).get("claim_key") or "").startswith(claim_prefix)
        ]
        stage_events = [
            event for event in all_stage_events
            if (event.evidence_references or {}).get("claim_key") == claim_key
        ]
        starts: dict[str, dict[str, Any]] = {}
        terminal: set[str] = set()
        terminal_status: dict[str, str] = {}
        for event in all_stage_events:
            evidence = event.evidence_references or {}
            attempt_id = str(evidence.get("attempt_id") or "")
            if event.event_type == "STAGE_INVOCATION_STARTED":
                starts[attempt_id] = evidence
            elif event.event_type in {
                "STAGE_INVOCATION_COMPLETED", "STAGE_INVOCATION_HUMAN_REQUIRED",
                "STAGE_INVOCATION_FAILED", "STAGE_INVOCATION_ABANDONED",
            }:
                terminal.add(attempt_id)
                terminal_status[attempt_id] = str(evidence.get("status") or "")
        prior_finished = [
            terminal_status.get(attempt_id, "") for attempt_id in starts
            if attempt_id in terminal
            and starts[attempt_id].get("candidate") == candidate
        ]
        if prior_finished:
            last_status = prior_finished[-1]
            if last_status == "COMPLETE":
                return None
            if last_status == "HUMAN_REQUIRED" and not allow_human_resume:
                return None
            if last_status in {"FAILED", "PARTIAL"} and not (
                authorized_retry or (stage == "APPLY" and last_status == "PARTIAL")
            ):
                return None
        incomplete = [item for key, item in starts.items() if key not in terminal]
        recovery_count = 0
        abandoned_attempt: dict[str, Any] | None = None
        if prior_claim is not None and prior_claim.is_active:
            return None
        if prior_claim is not None and incomplete:
            previous = incomplete[-1]
            if previous.get("candidate") != candidate:
                return None
            previous_claim_key = str(previous.get("claim_key") or "")
            if previous_claim_key != claim_key:
                return None
            prior_attempt_id = previous.get("attempt_id")
            process_event = next(
                (event.evidence_references or {} for event in reversed(stage_events)
                 if event.event_type == "STAGE_INVOCATION_PROCESS_STARTED"
                 and (event.evidence_references or {}).get("attempt_id") == prior_attempt_id),
                None,
            )
            coordinator = previous.get("coordinator_process")
            child = (process_event or {}).get("process_identity")
            current = process_identity()
            prior_recovery_count = int(previous.get("recovery_count", 0))
            if not self._stage_recovery_is_safe(
                coordinator,
                child,
                current,
                candidate_matches=previous.get("candidate") == candidate,
                recovery_count=prior_recovery_count,
            ):
                return None
            recovery_count = prior_recovery_count + 1
            abandoned_attempt = previous
        elif incomplete:
            # A different candidate cannot bypass an active or ambiguous
            # run/stage attempt merely by producing a different fingerprint.
            return None
        owner = f"stage:{stage}:{uuid4()}"
        claim = claims.acquire_or_reacquire(
            claim_key=claim_key, owner_instance_id=owner, lease_seconds=120
        )
        if claim is None:
            return None
        context = RecoveryClaimContext(
            claim_key=claim.claim_key,
            owner_instance_id=claim.owner_instance_id,
            fence_token=claim.fence_token,
            lease_expires_at=claim.lease_expires_at,
        )
        invocation = StageInvocation(
            attempt_id=str(uuid4()), claim=context, claim_key=claim_key,
            candidate=candidate, recovery_count=recovery_count,
            started_monotonic=asyncio.get_running_loop().time(),
        )
        try:
            coordinator_identity = process_identity()
            if abandoned_attempt is not None:
                self._save_stage_invocation_event(
                    uow, run, "STAGE_INVOCATION_ABANDONED", {
                        "attempt_id": abandoned_attempt.get("attempt_id"),
                        "claim_key": claim_key,
                        "fence_token": context.fence_token,
                        "candidate": candidate,
                        "status": "ABANDONED",
                        "finished_at": utc_now().isoformat(),
                        "reason": "Expired lease; coordinator and workflow process group proven absent.",
                        "recovery_count": recovery_count,
                    },
                )
            self._save_stage_invocation_event(
                uow, run, "STAGE_INVOCATION_STARTED", {
                    "attempt_id": invocation.attempt_id, "claim_key": claim_key,
                    "fence_token": context.fence_token, "candidate": candidate,
                    "started_at": utc_now().isoformat(),
                    "coordinator_process": coordinator_identity,
                    "recovery_proof": (
                        "UNAVAILABLE"
                        if coordinator_identity.get("status") != "AVAILABLE"
                        else "AWAITING_WORKFLOW_PROCESS_IDENTITY"
                    ),
                    "recovery_count": recovery_count,
                    "recovered_from_attempt_id": (
                        abandoned_attempt.get("attempt_id") if abandoned_attempt else None
                    ),
                },
            )
        except Exception:
            claims.release_claim(context)
            uow.commit()
            raise
        return invocation

    def _observe_stage_process(
        self, uow: Any, run: OrchestrationRun, invocation: StageInvocation
    ) -> Any:
        def observe(identity: dict[str, Any]) -> None:
            self._save_stage_invocation_event(
                uow, run, "STAGE_INVOCATION_PROCESS_STARTED", {
                    "attempt_id": invocation.attempt_id,
                    "claim_key": invocation.claim_key,
                    "process_identity": identity,
                    "recovery_proof": (
                        "UNAVAILABLE" if identity.get("status") != "AVAILABLE" else "AVAILABLE"
                    ),
                    "observed_at": utc_now().isoformat(),
                },
            )
        return observe

    async def _finish_stage_invocation(
        self, uow: Any, run: OrchestrationRun, invocation: StageInvocation,
        status: str, result: dict[str, Any],
    ) -> None:
        claim = invocation.claim
        if not uow.claims.validate_cas(
            claim.claim_key, claim.owner_instance_id, claim.fence_token
        ):
            raise RuntimeError("Stage invocation result rejected by stale fence")
        elapsed_ms = int((asyncio.get_running_loop().time() - invocation.started_monotonic) * 1000)
        event_type = {
            "COMPLETE": "STAGE_INVOCATION_COMPLETED",
            "HUMAN_REQUIRED": "STAGE_INVOCATION_HUMAN_REQUIRED",
        }.get(status, "STAGE_INVOCATION_FAILED")
        self._save_stage_invocation_event(
            uow, run, event_type, {
                "attempt_id": invocation.attempt_id, "claim_key": invocation.claim_key,
                "fence_token": claim.fence_token, "candidate": invocation.candidate,
                "status": status, "finished_at": utc_now().isoformat(),
                "duration_ms": elapsed_ms, "result": redact_secrets(result),
            },
        )
        uow.claims.release_claim(claim)
        uow.commit()

    async def _run_claimed(self, uow: Any, claim: RecoveryClaimContext, operation: Any) -> Any:
        """Keep the durable claim owned by this live worker, or fence the child."""
        renew = getattr(uow, "renew_claim_heartbeat_isolated", None)
        if not callable(renew):
            raise RuntimeError("Recovery claim heartbeat is unavailable")
        stopped = asyncio.Event()
        lost = False

        async def heartbeat() -> None:
            nonlocal lost
            while True:
                try:
                    await asyncio.wait_for(
                        stopped.wait(),
                        timeout=getattr(self, "_claim_heartbeat_interval_seconds", 30),
                    )
                    return
                except asyncio.TimeoutError:
                    try:
                        renewed = await asyncio.to_thread(renew, claim, 90)
                    except Exception:
                        renewed = False
                    if not renewed:
                        lost = True
                        return

        work = asyncio.create_task(operation())
        heart = asyncio.create_task(heartbeat())
        try:
            while not work.done() and not heart.done():
                await asyncio.wait({work, heart}, return_when=asyncio.FIRST_COMPLETED)
            if lost:
                work.cancel()
                await asyncio.gather(work, return_exceptions=True)
                raise RuntimeError("Recovery claim heartbeat lost while agent was executing")
            return await work
        finally:
            stopped.set()
            if not heart.done():
                heart.cancel()
            if not work.done():
                work.cancel()
            await asyncio.gather(heart, return_exceptions=True)
            await asyncio.gather(work, return_exceptions=True)

    async def _run_native_dispatch(
        self,
        uow: Any,
        run: OrchestrationRun,
        operation: str,
        dispatch: tuple[str, str, RecoveryClaimContext],
        work: Any,
        complete: Any,
        worktree_path: Path,
        allow_human_resume: bool = False,
        authorized_retry: bool = False,
    ) -> Any:
        """Run one native agent call under the shared claim and close its intent."""
        attempt_id, action_key, claim = dispatch
        invocation = await self._begin_stage_invocation(
            uow, run, worktree_path, operation.upper(),
            allow_human_resume=allow_human_resume,
            authorized_retry=authorized_retry,
        )
        if invocation is None:
            raise RuntimeError(f"{operation.title()} stage invocation is already active or ambiguous")
        try:
            result = await self._run_claimed(
                uow, claim,
                lambda: self._run_claimed(
                    uow, invocation.claim,
                    lambda: work(self._observe_stage_process(uow, run, invocation)),
                ),
            )
        except asyncio.CancelledError:
            self._finish_native_dispatch(
                uow, run, operation, attempt_id, action_key, claim, "AMBIGUOUS", None
            )
            raise
        except Exception as exc:
            self._finish_native_dispatch(
                uow, run, operation, attempt_id, action_key, claim, "AMBIGUOUS", str(exc)
            )
            raise
        status = "COMPLETE" if complete(result) else "FAILED"
        native_status = (
            result.get("status") if isinstance(result, dict) else None
        )
        if native_status == "HUMAN_REQUIRED":
            invocation_status = "HUMAN_REQUIRED"
        else:
            invocation_status = status
        await self._finish_stage_invocation(
            uow, run, invocation, invocation_status,
            {
                "native_status": native_status,
                "status": invocation_status,
                "message": result.get("message") if isinstance(result, dict) else None,
                "human_payload": result.get("human_payload") if isinstance(result, dict) else None,
            },
        )
        self._finish_native_dispatch(
            uow,
            run,
            operation,
            attempt_id,
            action_key,
            claim,
            status,
            None if status == "COMPLETE" else result.get("message"),
        )
        return result

    async def _run_native_boolean_stage(
        self,
        uow: Any,
        run: OrchestrationRun,
        worktree_path: Path,
        stage: str,
        dispatch: Any,
    ) -> bool:
        """Guard a native workflow whose existing caller consumes a boolean result."""
        invocation = await self._begin_stage_invocation(
            uow, run, worktree_path, stage,
        )
        if invocation is None:
            return False
        try:
            result = await self._run_claimed(
                uow, invocation.claim,
                lambda: dispatch(self._observe_stage_process(uow, run, invocation)),
            )
            complete = bool(result)
            await self._finish_stage_invocation(
                uow, run, invocation, "COMPLETE" if complete else "FAILED",
                {"observed_success": complete},
            )
            return complete
        except Exception:
            uow.claims.release_claim(invocation.claim)
            uow.commit()
            return False

    async def _normalize_request_before_explore(
        self,
        *,
        active_run: OrchestrationRun,
        project_id: str,
        repository: str,
        worktree_path: Path,
        issue_number: int,
        issue_title: str,
        issue_body: str,
        provider: str,
    ) -> tuple[dict[str, Any] | None, str | None]:
        """Normalize once before Explore while retaining the same Run and Worktree."""
        details = dict(active_run.stop_details or {})
        persisted = details.get("request_normalization")
        if isinstance(persisted, dict) and persisted.get("normalized_body"):
            return persisted, str(persisted["normalized_body"])
        prior_attempt = details.get("normalization_attempt")
        validated_response = details.get("validated_normalization_response")
        normalized: NormalizedRequest | None = None

        # F5 bootstrap compatibility: the legacy OpenRouter budget guard could
        # reject a direct Codex call BEFORE any subprocess was started. Only
        # that exact, evidence-bound pre-dispatch denial can be reconciled when
        # the operator explicitly re-invokes the request CLI. Preserve the
        # original attempt; all ambiguous/actually dispatched failures remain
        # fail-closed and require a separate operator decision.
        if isinstance(prior_attempt, dict) and normalized is None:
            known_pre_dispatch_denial = (
                prior_attempt.get("status") == "FAILED"
                and prior_attempt.get("diagnostic")
                == f"Budget policy/headroom is unavailable for project '{project_id}'."
                and prior_attempt.get("provider") == provider
                and prior_attempt.get("workflow")
                == f"$minime-request-normalizer issue-{issue_number}"
                and isinstance(prior_attempt.get("workflow_sha256"), str)
                and bool(prior_attempt.get("workflow_sha256"))
                and bool(prior_attempt.get("attempt_id"))
                and prior_attempt.get("dispatch_observed") is not True
                and prior_attempt.get("exit_code") is None
                and prior_attempt.get("timed_out") is None
                and prior_attempt.get("structured_output_present") is False
                and prior_attempt.get("structured_output_missing") is None
                and prior_attempt.get("usage_status") == "UNKNOWN"
                and prior_attempt.get("usage") is None
                and prior_attempt.get("response_status") is None
                and prior_attempt.get("publish_status") is None
                and not validated_response
            )
            if known_pre_dispatch_denial:
                try:
                    current_workflow = self.agent_runner.resolve_workflow(
                        worktree_path=worktree_path,
                        provider=provider,
                        operation="normalize",
                        change_name=f"issue-{issue_number}",
                    )
                except (NativeOpenSpecWorkflowUnavailable, ValueError, OSError):
                    return (
                        None,
                        "Previous normalization preflight cannot be reconciled: workflow unavailable.",
                    )
                response_path = (
                    worktree_path / ".minime" / f"request-normalization-{active_run.run_id}.json"
                )
                if (
                    current_workflow.workflow_sha256 != prior_attempt["workflow_sha256"]
                    or current_workflow.dispatch_command != prior_attempt["workflow"]
                    or response_path.exists()
                    or response_path.with_name("response.schema.json").exists()
                ):
                    return (
                        None,
                        "Previous normalization preflight has mismatched evidence; retry denied.",
                    )
                history = details.get("normalization_attempt_history", [])
                if not isinstance(history, list) or any(
                    not isinstance(item, dict)
                    or item.get("attempt_id") == prior_attempt["attempt_id"]
                    for item in history
                ):
                    return None, "Previous normalization preflight history is ambiguous."
                details["normalization_attempt_history"] = [
                    *history,
                    {**prior_attempt, "reconciliation": "CONFIRMED_PRE_DISPATCH_BUDGET_DENIAL"},
                ]
                details.pop("normalization_attempt", None)
                self._persist_run_stop_details(active_run, details)
                prior_attempt = None
        if (
            isinstance(prior_attempt, dict)
            and prior_attempt.get("response_status") == "VALIDATED"
            and isinstance(validated_response, dict)
            and prior_attempt.get("publish_status") != "CONFIRMED"
        ):
            try:
                normalized = NormalizedRequest(
                    original_body=str(validated_response["original_body"]),
                    normalized_body=str(validated_response["normalized_body"]),
                    already_normalized=False,
                    criteria=tuple(str(item) for item in validated_response["criteria"]),
                    semantic_message=str(validated_response["semantic_message"]),
                )
            except (KeyError, TypeError, ValueError):
                return (
                    None,
                    "Validated normalization checkpoint is incomplete; retry is not automatic.",
                )
        if (
            isinstance(prior_attempt, dict)
            and (
                prior_attempt.get("dispatch_observed") is True
                or prior_attempt.get("status") in {"IN_PROGRESS", "FAILED", "SUCCEEDED"}
            )
            and normalized is None
        ):
            return (
                None,
                "Normalization attempt already recorded; reconciliation or new authorization is required.",
            )

        service = RequestNormalizationService(self.github_adapter)
        try:
            # Older deterministic coordinator doubles do not implement the
            # ticket adapter contract. They cannot claim normalization; keep
            # their lifecycle tests focused on the stage under test.
            observed = self.github_adapter.get_issue(repository, issue_number)
            if not isinstance(observed, ExternalActionResult):
                return {"normalized_body": issue_body, "legacy_adapter": True}, None
            source_context: dict[str, Any] = {
                "issue": observed.data if isinstance(observed.data, dict) else {"body": issue_body},
                "comments": [],
            }
            list_comments = getattr(self.github_adapter, "list_issue_comments", None)
            if callable(list_comments):
                comments_result = list_comments(repository, issue_number)
                if (
                    not isinstance(comments_result, ExternalActionResult)
                    or comments_result.outcome is not ExternalOutcome.SUCCESS
                ):
                    return None, "Request normalization source comments were not verified."
                source_context["comments"] = (
                    comments_result.data if isinstance(comments_result.data, list) else []
                )
            if normalized is None:
                initial = (
                    NormalizedRequest(issue_body, issue_body, True)
                    if looks_like_complete_gherkin(issue_body)
                    else None
                )
                if initial is not None and initial.already_normalized:
                    normalized = initial
            if normalized is None:
                workflow = self.agent_runner.resolve_workflow(
                    worktree_path=worktree_path,
                    provider=provider,
                    operation="normalize",
                    change_name=f"issue-{issue_number}",
                )
                response_path = (
                    worktree_path / ".minime" / f"request-normalization-{active_run.run_id}.json"
                )
                attempt = {
                    "attempt_id": str(uuid4()),
                    "status": "IN_PROGRESS",
                    "provider": provider,
                    "workflow": workflow.dispatch_command,
                    "workflow_sha256": workflow.workflow_sha256,
                    "exit_code": None,
                    "timed_out": None,
                    "structured_output_present": False,
                    "structured_output_missing": None,
                    "structured_output_too_large": None,
                    "output_truncated": None,
                    "usage_status": "UNKNOWN",
                    "usage": None,
                }
                details["normalization_attempt"] = attempt
                active_run.stop_details = details
                self._persist_run_stop_details(active_run, details)
                try:
                    result = await self.agent_runner.run(
                        worktree_path=worktree_path,
                        prompt_context=(
                            "Use the installed minime-request-normalizer skill. Return exactly one JSON object "
                            "with normalized_body containing complete Gherkin: Feature:/Scenario:/Given/When/Then "
                            "in English, or # language: es with Característica:/Escenario:/Dado/Cuando/Entonces; "
                            "criteria as an array, and "
                            "semantic_message containing a brief concrete Spanish comment about the result. "
                            "Preserve every fact and do not invent requirements, decisions, or tasks.\n"
                            f"Request title: {issue_title}\nRequest body:\n{issue_body}\n"
                            "Authoritative Issue context (including comments and any declared attachments):\n"
                            f"{json.dumps(source_context, ensure_ascii=False, default=str)}\n"
                        ),
                        project_id=project_id,
                        role="thinker",
                        provider=provider,
                        workflow=workflow,
                        output_schema={
                            "type": "object",
                            "properties": {
                                "normalized_body": {"type": "string", "minLength": 1},
                                "criteria": {"type": "array", "items": {"type": "string"}},
                                "semantic_message": {
                                    "type": "string",
                                    "minLength": 1,
                                    "maxLength": 2000,
                                },
                            },
                            "required": ["normalized_body", "criteria", "semantic_message"],
                            "additionalProperties": False,
                        },
                        output_last_message_path=response_path,
                    )
                except Exception as exc:
                    attempt.update(
                        {"status": "FAILED", "diagnostic": redact_secrets(str(exc))[:500]}
                    )
                    self._persist_run_stop_details(active_run, details)
                    return None, "Request normalization dispatch failed; retry is not automatic."
                attempt.update(
                    {
                        "status": "SUCCEEDED"
                        if result.exit_code == 0 and not result.timed_out
                        else "FAILED",
                        "exit_code": result.exit_code,
                        "timed_out": result.timed_out,
                        "preflight_error": redact_secrets(result.preflight_error or "")[:500]
                        or None,
                        "structured_output_present": bool(result.response_output.strip()),
                        "structured_output_missing": result.structured_output_missing,
                        "structured_output_too_large": result.structured_output_too_large,
                        "output_truncated": result.output_truncated,
                        "duration_ms": result.duration_ms,
                    }
                )
                usage = self.agent_runner.observed_usage(result)
                if usage is not None:
                    attempt.update({"usage_status": "OBSERVED", "usage": usage})
                self._persist_run_stop_details(active_run, details)
                if (
                    result.exit_code != 0
                    or result.timed_out
                    or result.preflight_error
                    or result.structured_output_missing
                    or result.structured_output_too_large
                ):
                    return None, "Request normalization agent did not produce a verified result."
                raw_response = result.response_output or ""
                response_bytes = raw_response.encode("utf-8")
                details["rejected_response"] = {
                    "status": "QUARANTINED",
                    "attempt_id": attempt["attempt_id"],
                    "sha256": hashlib.sha256(response_bytes).hexdigest(),
                    "byte_length": len(response_bytes),
                    "content": _quarantine_response_content(raw_response)[
                        : CliAgentRunner.MAX_STRUCTURED_OUTPUT_BYTES
                    ],
                    "content_truncated": len(response_bytes)
                    > CliAgentRunner.MAX_STRUCTURED_OUTPUT_BYTES,
                }
                self._persist_run_stop_details(active_run, details)
                try:
                    payload = json.loads(result.response_output)
                except json.JSONDecodeError:
                    attempt["response_status"] = "INVALID"
                    attempt["diagnostic"] = "structured response is not valid JSON"
                    self._persist_run_stop_details(active_run, details)
                    return None, "Request normalization response was not structured."
                if (
                    not isinstance(payload, dict)
                    or set(payload) != {"normalized_body", "criteria", "semantic_message"}
                    or not isinstance(payload.get("normalized_body"), str)
                    or not isinstance(payload.get("criteria"), list)
                    or not all(
                        isinstance(item, str) and item.strip() for item in payload["criteria"]
                    )
                    or not isinstance(payload.get("semantic_message"), str)
                    or not payload["semantic_message"].strip()
                ):
                    attempt["response_status"] = "INVALID"
                    attempt["diagnostic"] = (
                        "structured response must contain exactly normalized_body, criteria and semantic_message"
                    )
                    self._persist_run_stop_details(active_run, details)
                    return None, "Request normalization response was not structured."
                attempt["response_status"] = "VALIDATED"
                normalized = NormalizedRequest(
                    original_body=issue_body,
                    normalized_body=payload["normalized_body"].strip(),
                    already_normalized=False,
                    criteria=tuple(str(item) for item in payload.get("criteria", [])),
                    semantic_message=payload["semantic_message"].strip(),
                )
                details["_normalization_response_sha256"] = hashlib.sha256(
                    result.response_output.encode("utf-8")
                ).hexdigest()
            try:
                validate_normalized_body(normalized.normalized_body)
                details.pop("rejected_response", None)
                if normalized.semantic_message.strip():
                    service.semantic_comment(
                        normalized.semantic_message,
                        service.provenance_key(active_run.run_id, issue_number),
                    )
            except RequestNormalizationError as exc:
                if isinstance(details.get("normalization_attempt"), dict):
                    details["normalization_attempt"]["response_status"] = "INVALID"
                    details["normalization_attempt"]["diagnostic"] = str(exc)[:500]
                    if isinstance(details.get("rejected_response"), dict):
                        details["rejected_response"]["validation_error"] = str(exc)[:500]
                    self._persist_run_stop_details(active_run, details)
                return None, str(exc)
            if isinstance(details.get("normalization_attempt"), dict):
                details["normalization_attempt"]["response_status"] = "VALIDATED"
                previous_validated = details.get("validated_normalization_response")
                response_sha256 = details.pop("_normalization_response_sha256", None)
                details["validated_normalization_response"] = {
                    "original_body": normalized.original_body,
                    "normalized_body": normalized.normalized_body,
                    "criteria": list(normalized.criteria),
                    "semantic_message": normalized.semantic_message,
                    "response_sha256": response_sha256
                    or (
                        previous_validated.get("response_sha256")
                        if isinstance(previous_validated, dict)
                        else None
                    ),
                }
                self._persist_run_stop_details(active_run, details)
            try:
                evidence = service.publish(repository, issue_number, active_run.run_id, normalized)
            except RequestNormalizationError as exc:
                if isinstance(details.get("normalization_attempt"), dict):
                    details["normalization_attempt"]["publish_status"] = "FAILED"
                    details["normalization_attempt"]["diagnostic"] = str(exc)[:500]
                    self._persist_run_stop_details(active_run, details)
                raise
        except (
            RequestNormalizationError,
            NativeOpenSpecWorkflowUnavailable,
            ValueError,
            json.JSONDecodeError,
        ) as exc:
            return None, str(exc)

        persisted = {
            **evidence,
            "original_body": issue_body,
            "normalized_body": normalized.normalized_body,
            "already_normalized": normalized.already_normalized,
            "criteria": list(normalized.criteria),
            "semantic_message": normalized.semantic_message,
            "source_context_sha256": hashlib.sha256(
                json.dumps(source_context, sort_keys=True, ensure_ascii=False, default=str).encode(
                    "utf-8"
                )
            ).hexdigest(),
        }
        details["request_normalization"] = persisted
        active_run.stop_details = details
        if isinstance(details.get("normalization_attempt"), dict):
            details["normalization_attempt"]["publish_status"] = "CONFIRMED"
        uow = self.uow_factory()
        stored = uow.orchestration_runs.get_by_id(active_run.run_id)
        if stored is not None:
            stored.stop_details = details
            uow.orchestration_runs.save(stored)
            uow.commit()
        return persisted, normalized.normalized_body

    def _persist_run_stop_details(
        self, active_run: OrchestrationRun, details: dict[str, Any]
    ) -> None:
        """Persist normalization identity and result before allowing any continuation."""
        active_run.stop_details = details
        uow = self.uow_factory()
        stored = uow.orchestration_runs.get_by_id(active_run.run_id)
        if stored is not None:
            stored.stop_details = details
            uow.orchestration_runs.save(stored)
            uow.commit()

    def register_recovery_authorization(
        self,
        *,
        project_id: str,
        run_id: str,
        authorization_reference: str,
        actor_identity: str,
        source_interface: str,
        issue_number: int,
        provider: str,
        prior_attempt_id: str | None,
        stage: str,
    ) -> bool:
        """Register one authenticated, Run-bound recovery decision for a native stage."""
        if stage not in {"explore", "propose", "proposal_review", "code_review"}:
            return False
        uow = self.uow_factory()
        run = (
            uow.orchestration_runs.get_for_update(run_id)
            if hasattr(uow.orchestration_runs, "get_for_update")
            else uow.orchestration_runs.get_by_id(run_id)
        )
        if not run or run.project_id != project_id or not run.is_active:
            return False
        details = dict(run.stop_details or {})
        attempt = details.get(f"{stage}_attempt")
        if stage == "explore":
            if prior_attempt_id is None:
                if (
                    attempt is not None
                    or details.get("explore_checkpoint") is not None
                    or run.current_stage != OrchestrationStage.EXPLORING
                ):
                    return False
            elif not isinstance(attempt, dict) or attempt.get("attempt_id") != prior_attempt_id:
                return False
        elif stage == "propose":
            if run.current_stage not in {
                OrchestrationStage.PROPOSING,
                OrchestrationStage.VALIDATING,
            }:
                return False
            if prior_attempt_id is not None and (
                not isinstance(attempt, dict) or attempt.get("attempt_id") != prior_attempt_id
            ):
                return False
            if prior_attempt_id is None and attempt is not None:
                return False
        elif stage == "proposal_review":
            if run.current_stage != OrchestrationStage.PROPOSAL_REVIEW:
                return False
            review_attempt = details.get("proposal_review")
            if prior_attempt_id is not None and (
                not isinstance(review_attempt, dict)
                or review_attempt.get("attempt_id") != prior_attempt_id
            ):
                return False
        elif stage == "code_review":
            if run.current_stage != OrchestrationStage.CODE_REVIEW:
                return False
            code_review_attempt = details.get("code_review")
            if prior_attempt_id is not None and (
                not isinstance(code_review_attempt, dict)
                or code_review_attempt.get("attempt_id") != prior_attempt_id
            ):
                return False
        else:
            return False
        actions = getattr(uow, "operator_actions", None)
        if actions is None or actions.get_by_request_id(authorization_reference) is not None:
            return False
        action = OperatorActionRecord(
            action_request_id=authorization_reference,
            project_id=project_id,
            change_name=run.change_name,
            run_id=run_id,
            action_type=OperatorActionType.RETRY,
            actor_identity=actor_identity,
            source_interface=source_interface,
            precondition_stage=run.current_stage.value,
            status=OperatorActionStatus.ACCEPTED,
            summary=f"One-shot authenticated authorization for {stage} recovery.",
            parameters_json={
                "single_use": True,
                "stage": stage,
                "issue_number": issue_number,
                "provider": provider,
                "prior_attempt_id": prior_attempt_id,
                "change_name": run.change_name,
                **(
                    {
                        "legacy_missing_attempt": prior_attempt_id is None,
                        "prior_context_sha256": (
                            attempt.get("context_sha256") if isinstance(attempt, dict) else None
                        ),
                        "prior_workflow_sha256": (
                            attempt.get("workflow_sha256") if isinstance(attempt, dict) else None
                        ),
                    }
                    if stage == "explore"
                    else {}
                ),
            },
        )
        actions.save(action)
        uow.commit()
        return True

    async def execute_project_request(
        self,
        project_id: str,
        *,
        operator_ack: bool = False,
        operator_clarification: str | None = None,
        explore_recovery_authorization_id: str | None = None,
        propose_recovery_authorization_id: str | None = None,
        proposal_review_recovery_authorization_id: str | None = None,
        code_review_recovery_authorization_id: str | None = None,
        thinker_provider: str = "antigravity",
        implementer_provider: str = "codex",
        reviewer_provider: str = "antigravity",
        target_run_id: str | None = None,
    ) -> OrchestrationCoordinationResult:
        """Execute or resume the active/next request for a project."""
        uow: PersistenceUnitOfWork = self.uow_factory()
        intake_service = RemoteRequestIntakeService(github_adapter=self.github_adapter, uow=uow)

        # Resolve repository from the persisted project/binding. Never use a
        # placeholder: publishing against an unverified repository is unsafe.
        repository = None
        if hasattr(uow, "projects"):
            getter = getattr(uow.projects, "get_by_id", None) or getattr(uow.projects, "get", None)
            if getter:
                proj = getter(project_id)
                if proj and getattr(proj, "repository", None):
                    repository = proj.repository
        binding = None
        if hasattr(uow, "project_managed_repository_bindings"):
            binding = uow.project_managed_repository_bindings.get_by_project_id(project_id)
        if (
            not repository
            or binding is None
            or not getattr(binding, "managed_repository_root", None)
        ):
            return OrchestrationCoordinationResult(
                status="PAUSED",
                run_id=None,
                current_stage=OrchestrationStage.ADMITTED,
                message="Project has no verified repository binding; work was not started.",
            )
        canonical = str(getattr(binding, "canonical_repository_identity", ""))
        expected = f"github.com/{repository}".lower().removeprefix("https://")
        if (
            canonical.lower().startswith(("github.com/", "https://"))
            and canonical.lower().removeprefix("https://") != expected
        ):
            return OrchestrationCoordinationResult(
                status="PAUSED",
                run_id=None,
                current_stage=OrchestrationStage.ADMITTED,
                message="Project repository does not match its verified managed binding.",
            )

        # Step 1: Remote Request Intake and Selection
        if target_run_id and hasattr(uow, "orchestration_runs"):
            target_run = uow.orchestration_runs.get_by_id(target_run_id)
            if target_run and getattr(target_run, "is_active", True):
                selected = {
                    "re_entrant": True,
                    "run_id": target_run.run_id,
                    "change_name": target_run.change_name,
                    "run": target_run,
                }
            else:
                selected = intake_service.select_next_request(project_id, repository)
        else:
            selected = intake_service.select_next_request(project_id, repository)
        if not selected:
            return OrchestrationCoordinationResult(
                status="IDLE",
                run_id=None,
                current_stage=OrchestrationStage.ADMITTED,
                message="No eligible open requests found in remote repository.",
            )

        issue_number = selected.get("issue_number")
        issue_title = selected.get("title") or "change"
        issue_body = selected.get("body") or ""
        if selected.get("re_entrant"):
            # Durable Run identity wins on re-entry; the Issue may have been edited.
            active_details = getattr(selected.get("run"), "stop_details", {}) or {}
            issue_number = issue_number or active_details.get("issue_number")
            issue_title = active_details.get("issue_title") or issue_title
            change_name = selected.get("change_name")
            if not change_name or not isinstance(issue_number, int):
                return OrchestrationCoordinationResult(
                    status="PAUSED",
                    run_id=selected.get("run_id"),
                    current_stage=OrchestrationStage.ADMITTED,
                    message="Active Request lacks immutable Change or Issue identity.",
                )
            # Do not send an empty or subsequently edited remote Issue body to
            # Propose on re-entry. Normalization is a durable, immutable
            # checkpoint for the accepted Request.
            normalized = active_details.get("request_normalization")
            normalized_body = (
                normalized.get("normalized_body") if isinstance(normalized, dict) else None
            )
            if isinstance(normalized_body, str) and normalized_body.strip():
                issue_body = normalized_body
            elif getattr(selected.get("run"), "current_stage", None) in (
                OrchestrationStage.ADMITTED,
                OrchestrationStage.PREPARING_EXECUTION,
                OrchestrationStage.EXPLORING,
            ):
                # Older admitted Runs retained the Issue identity but not its
                # source body. Re-read the authoritative remote Request, never
                # dispatch an empty prompt or silently switch Change identity.
                observed = self.github_adapter.get_issue(repository, issue_number)
                remote_issue = (
                    observed.data
                    if (
                        isinstance(observed, ExternalActionResult)
                        and observed.outcome is ExternalOutcome.SUCCESS
                        and isinstance(observed.data, dict)
                    )
                    else None
                )
                remote_body = remote_issue.get("body") if remote_issue else None
                if (
                    not remote_issue
                    or remote_issue.get("number") != issue_number
                    or remote_issue.get("title") != issue_title
                    or not isinstance(remote_body, str)
                    or not remote_body.strip()
                ):
                    return OrchestrationCoordinationResult(
                        status="PAUSED",
                        run_id=selected.get("run_id"),
                        current_stage=selected["run"].current_stage,
                        message="Admitted Request source body or identity cannot be verified.",
                    )
                try:
                    remote_change = WorktreeManager.resolve_request_change_name(
                        issue_number, issue_title, remote_body
                    )
                except ValueError:
                    remote_change = None
                if remote_change != change_name:
                    return OrchestrationCoordinationResult(
                        status="PAUSED",
                        run_id=selected.get("run_id"),
                        current_stage=selected["run"].current_stage,
                        message="Admitted Request Change reservation does not match the durable Run.",
                    )
                issue_body = remote_body
            else:
                return OrchestrationCoordinationResult(
                    status="PAUSED",
                    run_id=selected.get("run_id"),
                    current_stage=selected["run"].current_stage,
                    message="Active Request has no verified durable normalized body; Propose cannot resume.",
                )
        else:
            try:
                change_name = WorktreeManager.resolve_request_change_name(
                    issue_number, issue_title, issue_body
                )
            except ValueError as exc:
                return OrchestrationCoordinationResult(
                    status="PAUSED",
                    run_id=None,
                    current_stage=OrchestrationStage.ADMITTED,
                    message=f"Request Change identity is invalid: {exc}",
                )

        # Step 2: Durable Run Record
        active_run = None
        if hasattr(uow, "orchestration_runs"):
            if hasattr(uow.orchestration_runs, "get_active_run"):
                active_run = uow.orchestration_runs.get_active_run(project_id, change_name)
            if not active_run and hasattr(uow.orchestration_runs, "list_runs"):
                active_runs = uow.orchestration_runs.list_runs(
                    project_id=project_id, is_active=True
                )
                if active_runs:
                    active_run = active_runs[0]

        if not active_run:
            active_run = OrchestrationRun(
                project_id=project_id,
                change_name=change_name,
                base_sha="main",
                current_stage=OrchestrationStage.ADMITTED,
                resumable_stage=OrchestrationStage.ADMITTED,
                stop_details={"issue_number": issue_number, "issue_title": issue_title},
            )
            if hasattr(uow, "orchestration_runs"):
                uow.orchestration_runs.save(active_run)
                if hasattr(uow, "commit"):
                    uow.commit()
        elif hasattr(uow.orchestration_runs, "get_for_update"):
            locked_run = uow.orchestration_runs.get_for_update(active_run.run_id)
            if locked_run is not None:
                active_run = locked_run

        # Capture the stage this execution *entered* at. Review stages are
        # transition points: if a run enters already sitting on a review stage,
        # that is a resume and must fail closed on absent/ambiguous evidence.
        entry_stage = active_run.current_stage
        pending_gate = (active_run.stop_details or {}).get("human_payload")
        gate_pending = (
            active_run.human_gate == HumanGate.NEEDS_HUMAN
            or active_run.stop_outcome == OrchestrationStopOutcome.NEEDS_HUMAN
        )
        accepted_response = operator_clarification and operator_clarification.strip()
        if gate_pending and not accepted_response and not operator_ack:
            if isinstance(pending_gate, dict):
                return OrchestrationCoordinationResult(
                    status="HUMAN_REQUIRED", run_id=active_run.run_id,
                    current_stage=active_run.current_stage,
                    message=str(pending_gate.get("question") or "A human gate is still pending."),
                    human_payload=self._safe_human_payload(pending_gate),
                )
            return OrchestrationCoordinationResult(
                status="PAUSED", run_id=active_run.run_id,
                current_stage=active_run.current_stage,
                message="A human gate is pending but its durable payload is unavailable; no stage was dispatched.",
            )

        # Step 3: Git Workspace Isolation
        base_branch = "main"
        worktree_info = await self.worktree_manager.create_request_worktree(
            project_id=project_id,
            issue_number=issue_number,
            issue_title=issue_title,
            base_branch=base_branch,
            run_id=active_run.run_id,
            change_name=change_name,
        )
        worktree_path = worktree_info.path

        # Step 4: Request normalization must complete before Explore while
        # retaining the same durable Run and authorized Worktree.
        if active_run.current_stage in (
            OrchestrationStage.ADMITTED,
            OrchestrationStage.PREPARING_EXECUTION,
            OrchestrationStage.EXPLORING,
        ):
            normalization, normalization_error = await self._normalize_request_before_explore(
                active_run=active_run,
                project_id=project_id,
                repository=repository,
                worktree_path=worktree_path,
                issue_number=issue_number,
                issue_title=issue_title,
                issue_body=issue_body,
                provider=thinker_provider,
            )
            if normalization is None:
                return OrchestrationCoordinationResult(
                    status="PAUSED",
                    run_id=active_run.run_id,
                    current_stage=active_run.current_stage,
                    message=normalization_error or "Request normalization was not verified.",
                )
            issue_body = str(normalization.get("normalized_body") or issue_body)

        # Step 5: Explore Stage
        if active_run.current_stage in (
            OrchestrationStage.ADMITTED,
            OrchestrationStage.PREPARING_EXECUTION,
            OrchestrationStage.EXPLORING,
        ):
            stage_before_explore = active_run.current_stage
            self._update_stage(uow, active_run, OrchestrationStage.EXPLORING)
            # A validated Explore disposition is immutable for the same
            # Run/Issue/clarification context. Re-entry must not spend another
            # subscription turn only to re-read an already accepted verdict.
            explore_context = {
                "run_id": active_run.run_id,
                "project_id": project_id,
                "issue_number": issue_number,
                "issue_title": issue_title,
                "issue_body": issue_body,
                "provider": thinker_provider,
                "operator_clarification": operator_clarification,
            }
            explore_context_sha = hashlib.sha256(
                json.dumps(explore_context, ensure_ascii=False, sort_keys=True).encode("utf-8")
            ).hexdigest()
            # Preserve the immutable Request/context identity separately so a
            # new human clarification can authorize another Explore only after
            # a genuine, otherwise verified HUMAN_REQUIRED checkpoint.
            explore_base_context = dict(explore_context)
            explore_base_context.pop("operator_clarification", None)
            explore_base_context_sha = hashlib.sha256(
                json.dumps(explore_base_context, ensure_ascii=False, sort_keys=True).encode("utf-8")
            ).hexdigest()
            expected_explore_wf: ResolvedWorkflow | None = None
            try:
                expected_explore_wf = self.agent_runner.resolve_workflow(
                    worktree_path=worktree_path,
                    provider=thinker_provider,
                    operation="explore",
                    change_name=f"issue-{issue_number}",
                )
            except Exception:
                expected_explore_wf = None

            stored_explore = (active_run.stop_details or {}).get("explore_checkpoint")
            checkpoint_verified = (
                expected_explore_wf is not None
                and isinstance(stored_explore, dict)
                and stored_explore.get("run_id") == active_run.run_id
                and stored_explore.get("provider") == thinker_provider
                and stored_explore.get("status") in {"HUMAN_REQUIRED", "READY_TO_PROPOSE"}
                and stored_explore.get("checkpoint_version") == 2
                and stored_explore.get("response_status") == "COMPLETE"
                and stored_explore.get("response_source")
                in {"codex_ndjson", "structured_file", "stdout_text"}
                and isinstance(stored_explore.get("response_sha256"), str)
                and len(stored_explore["response_sha256"]) == 64
                and stored_explore.get("workflow_sha256") == expected_explore_wf.workflow_sha256
                and stored_explore.get("base_context_sha256") == explore_base_context_sha
            )
            same_context = (
                checkpoint_verified and stored_explore.get("context_sha256") == explore_context_sha
            )
            authorized_clarification = (
                checkpoint_verified
                and not same_context
                and stored_explore.get("status") == "HUMAN_REQUIRED"
                and isinstance(operator_clarification, str)
                and bool(operator_clarification.strip())
            )
            # A previously dispatched Explore without a checkpoint is also
            # ambiguous. Never turn an ordinary resumed API call into another
            # paid inference. Recovery is explicit, Run-bound and one-use.
            recovery_needed = (
                stored_explore is not None and not (same_context or authorized_clarification)
            ) or (stored_explore is None and stage_before_explore == OrchestrationStage.EXPLORING)
            if recovery_needed:
                if not explore_recovery_authorization_id:
                    return OrchestrationCoordinationResult(
                        status="PAUSED",
                        run_id=active_run.run_id,
                        current_stage=OrchestrationStage.EXPLORING,
                        message=(
                            "Explore has incomplete or unverified prior evidence; "
                            "an explicit, Run-bound recovery authorization is required."
                        ),
                    )
                prior = getattr(uow, "operator_actions", None)
                existing = (
                    prior.get_by_request_id(explore_recovery_authorization_id)
                    if prior is not None
                    else None
                )
                if existing is not None and existing.status != OperatorActionStatus.ACCEPTED:
                    return OrchestrationCoordinationResult(
                        status="PAUSED",
                        run_id=active_run.run_id,
                        current_stage=OrchestrationStage.EXPLORING,
                        message="Explore recovery authorization has already been consumed.",
                    )
            if same_context:
                explore_result = {
                    "status": stored_explore["status"],
                    "human_payload": self._safe_human_payload(stored_explore.get("human_payload")),
                }
            else:
                dispatch = self._prepare_native_dispatch(
                    uow=uow,
                    run=active_run,
                    issue_number=issue_number,
                    provider=thinker_provider,
                    operation="explore",
                    action_type=ExternalActionType.OPENSPEC_EXPLORE_DISPATCH,
                    target_identity=f"{active_run.project_id}:{issue_number}:{thinker_provider}",
                    request_fingerprint=explore_context_sha,
                    attempt_fields={
                        "context_sha256": explore_context_sha,
                        "workflow_sha256": (
                            expected_explore_wf.workflow_sha256
                            if expected_explore_wf is not None
                            else None
                        ),
                    },
                    is_recovery=recovery_needed,
                    recovery_authorization_id=explore_recovery_authorization_id,
                )
                if dispatch is None:
                    return OrchestrationCoordinationResult(
                        status="PAUSED",
                        run_id=active_run.run_id,
                        current_stage=OrchestrationStage.EXPLORING,
                        message="Explore dispatch is already owned or its durable intent is ambiguous.",
                    )
                explore_result = await self._run_native_dispatch(
                    uow,
                    active_run,
                    "explore",
                    dispatch,
                    lambda process_observer: self._run_explore(
                        worktree_path=worktree_path,
                        provider=thinker_provider,
                        issue_number=issue_number,
                        issue_title=issue_title,
                        issue_body=issue_body,
                        operator_clarification=operator_clarification,
                        project_id=project_id,
                        process_start_observer=process_observer,
                    ),
                    lambda result: (
                        result.get("execution") is not None
                        and self._execution_is_successful(result["execution"])
                    ),
                    worktree_path=worktree_path,
                    allow_human_resume=bool(operator_clarification),
                    authorized_retry=recovery_needed,
                )
                evidence = explore_result.get("execution")
                if (
                    explore_result.get("status") in {"HUMAN_REQUIRED", "READY_TO_PROPOSE"}
                    and evidence is not None
                    and self._execution_is_successful(evidence)
                    and getattr(evidence, "final_response_status", None) == "COMPLETE"
                    and getattr(evidence, "response_output", "").strip()
                    and isinstance(
                        getattr(getattr(evidence, "workflow", None), "workflow_sha256", None),
                        str,
                    )
                ):
                    details = dict(active_run.stop_details or {})
                    details["explore_checkpoint"] = {
                        "checkpoint_version": 2,
                        "run_id": active_run.run_id,
                        "provider": thinker_provider,
                        "response_status": evidence.final_response_status,
                        "response_source": evidence.final_response_source,
                        "workflow_sha256": evidence.workflow.workflow_sha256,
                        "status": explore_result["status"],
                        "context_sha256": explore_context_sha,
                        "base_context_sha256": explore_base_context_sha,
                        "response_sha256": hashlib.sha256(
                            evidence.response_output.encode("utf-8")
                        ).hexdigest(),
                        "attempt_id": dispatch[0],
                        "human_payload": self._safe_human_payload(
                            explore_result.get("human_payload")
                        ),
                        "duration_ms": getattr(evidence, "duration_ms", None),
                        "recorded_at": utc_now().isoformat(),
                    }
                    self._persist_run_stop_details(active_run, details)
            if explore_result.get("status") == "HUMAN_REQUIRED":
                raw_payload = explore_result.get("human_payload") or {}
                recorded_payload = self._record_current_human_gate(
                    uow,
                    active_run,
                    gate="explore_clarification",
                    question=str(raw_payload.get("question") or "Explore stage requires operator clarification."),
                    options=raw_payload.get("options", []),
                    payload=raw_payload,
                )
                return OrchestrationCoordinationResult(
                    status="HUMAN_REQUIRED",
                    run_id=active_run.run_id,
                    current_stage=OrchestrationStage.EXPLORING,
                    message="Explore stage requires operator clarification.",
                    human_payload=recorded_payload,
                )
            if explore_result.get("status") != "READY_TO_PROPOSE":
                return OrchestrationCoordinationResult(
                    status="PAUSED",
                    run_id=active_run.run_id,
                    current_stage=OrchestrationStage.EXPLORING,
                    message=explore_result.get("message", "Explore failed; proposal cannot start."),
                )
            self._clear_current_human_gate(uow, active_run, response_text=operator_clarification)

        # Step 6: Propose and Strict Validation Loop
        if active_run.current_stage in (
            OrchestrationStage.EXPLORING,
            OrchestrationStage.PROPOSING,
            OrchestrationStage.VALIDATING,
        ):
            stored_propose_attempt = (active_run.stop_details or {}).get("propose_attempt")
            planning = (
                self.openspec_adapter.planning_status(change_name, worktree_path)
                if active_run.current_stage == OrchestrationStage.VALIDATING
                else None
            )
            if isinstance(planning, dict) and planning.get("status") == "UNKNOWN":
                return OrchestrationCoordinationResult(
                    status="PAUSED",
                    run_id=active_run.run_id,
                    current_stage=OrchestrationStage.VALIDATING,
                    message="OpenSpec planning status is unobservable; no Propose dispatch is permitted.",
                )
            complete_proposal = (
                isinstance(planning, dict) and planning.get("status") == "PASS"
            ) or (planning is None and self._proposal_artifacts_present(worktree_path, change_name))
            propose_recovery_needed = (
                active_run.current_stage == OrchestrationStage.PROPOSING
                and (
                    stored_propose_attempt is not None
                    or self._proposal_artifacts_any(worktree_path, change_name)
                )
            ) or (
                active_run.current_stage == OrchestrationStage.VALIDATING and not complete_proposal
            )
            pending_revision = (active_run.stop_details or {}).get("pending_proposal_revision")
            stored_propose_gate = (active_run.stop_details or {}).get("propose_human_required")
            verified_propose_human_gate = (
                propose_recovery_needed
                and isinstance(stored_propose_gate, dict)
                and isinstance(stored_propose_attempt, dict)
                and stored_propose_gate.get("attempt_id")
                == stored_propose_attempt.get("attempt_id")
                and stored_propose_attempt.get("status") == "COMPLETE"
            )
            if verified_propose_human_gate and not (
                isinstance(operator_clarification, str) and operator_clarification.strip()
            ):
                # A power interruption or refresh must not hide a genuine
                # human question or spend another model invocation to rediscover it.
                return OrchestrationCoordinationResult(
                    status="HUMAN_REQUIRED",
                    run_id=active_run.run_id,
                    current_stage=OrchestrationStage.PROPOSING,
                    message="Propose is awaiting an operator clarification.",
                    human_payload=self._safe_human_payload(
                        stored_propose_gate.get("human_payload")
                    ),
                )
            if (
                propose_recovery_needed
                and not propose_recovery_authorization_id
                and not pending_revision
            ):
                return OrchestrationCoordinationResult(
                    status="PAUSED",
                    run_id=active_run.run_id,
                    current_stage=OrchestrationStage.PROPOSING,
                    message="Propose recovery authorization is required before dispatch.",
                )
            existing_proposal = (
                active_run.current_stage == OrchestrationStage.VALIDATING and complete_proposal
            )
            if not existing_proposal:
                self._update_stage(uow, active_run, OrchestrationStage.PROPOSING)
                dispatch = self._prepare_native_dispatch(
                    uow=uow,
                    run=active_run,
                    issue_number=issue_number,
                    provider=thinker_provider,
                    operation="propose",
                    action_type=ExternalActionType.OPENSPEC_EXPLORE_DISPATCH,
                    target_identity=f"{active_run.project_id}:{issue_number}:{change_name}:{thinker_provider}",
                    request_fingerprint=hashlib.sha256(
                        f"{active_run.run_id}:{change_name}:{issue_number}:{thinker_provider}".encode()
                    ).hexdigest(),
                    attempt_fields={"change_name": change_name},
                    is_recovery=propose_recovery_needed and not pending_revision,
                    recovery_authorization_id=propose_recovery_authorization_id,
                )
                if dispatch is None:
                    return OrchestrationCoordinationResult(
                        status="PAUSED",
                        run_id=active_run.run_id,
                        current_stage=OrchestrationStage.PROPOSING,
                        message="Propose dispatch is already owned or its durable intent is ambiguous.",
                    )
                propose_result = await self._run_native_dispatch(
                    uow,
                    active_run,
                    "propose",
                    dispatch,
                    lambda process_observer: self._run_propose(
                        worktree_path=worktree_path,
                        provider=thinker_provider,
                        change_name=change_name,
                        issue_number=issue_number,
                        issue_title=issue_title,
                        issue_body=issue_body,
                        project_id=project_id,
                        continue_existing=propose_recovery_needed or bool(pending_revision),
                        operator_clarification=(
                            self._proposal_revision_prompt(pending_revision)
                            if pending_revision
                            else (operator_clarification if verified_propose_human_gate else None)
                        ),
                        process_start_observer=process_observer,
                    ),
                    lambda result: result.get("status") in {"READY_TO_VALIDATE", "HUMAN_REQUIRED"},
                    worktree_path=worktree_path,
                    allow_human_resume=bool(verified_propose_human_gate and operator_clarification),
                    authorized_retry=propose_recovery_needed and not pending_revision,
                )
                propose_attempt_id = dispatch[0]
                human_required = propose_result.get("status") == "HUMAN_REQUIRED"
                if human_required:
                    details = dict(active_run.stop_details or {})
                    details["propose_human_required"] = {
                        "attempt_id": propose_attempt_id,
                        "human_payload": self._safe_human_payload(propose_result["human_payload"]),
                        "recorded_at": utc_now().isoformat(),
                    }
                    self._persist_run_stop_details(active_run, details)
                if propose_result.get("status") == "HUMAN_REQUIRED":
                    return OrchestrationCoordinationResult(
                        status="HUMAN_REQUIRED",
                        run_id=active_run.run_id,
                        current_stage=OrchestrationStage.PROPOSING,
                        message=propose_result["message"],
                        human_payload=self._safe_human_payload(propose_result["human_payload"]),
                    )
                if propose_result.get("status") != "READY_TO_VALIDATE":
                    return OrchestrationCoordinationResult(
                        status="PAUSED",
                        run_id=active_run.run_id,
                        current_stage=OrchestrationStage.PROPOSING,
                        message=propose_result.get(
                            "message", "Native Propose did not produce a valid result."
                        ),
                    )

                if verified_propose_human_gate or pending_revision:
                    details = dict(active_run.stop_details or {})
                    details.pop("propose_human_required", None)
                    details.pop("pending_proposal_revision", None)
                    self._persist_run_stop_details(active_run, details)
                self._update_stage(uow, active_run, OrchestrationStage.VALIDATING)
            validate_pass = False
            for attempt in range(self.max_correction_attempts if not existing_proposal else 1):
                val_res = self.openspec_adapter.validate_change_strict(change_name, worktree_path)
                if val_res.get("status") == "PASS":
                    validate_pass = True
                    break
                if existing_proposal:
                    break
                # Correction pass
                logger.info(
                    f"OpenSpec strict validation failed on attempt {attempt + 1}. Running correction pass..."
                )
                correction_ok = await self._run_native_boolean_stage(
                    uow, active_run, worktree_path, "UPDATE",
                    lambda observer: self._run_propose_correction(
                        worktree_path,
                        thinker_provider,
                        change_name,
                        val_res.get("stderr", ""),
                        project_id=project_id,
                        process_start_observer=observer,
                    ),
                )
                if not correction_ok:
                    break

            if not validate_pass:
                return OrchestrationCoordinationResult(
                    status="PAUSED",
                    run_id=active_run.run_id,
                    current_stage=OrchestrationStage.VALIDATING,
                    message="Strict CLI validation failed after max correction attempts. Worktree preserved.",
                )

            # Evaluate Complexity. A previous non-valid attempt is durable evidence
            # that automatic re-entry must stop; it may not spend another call.
            artifact_hashes = self._proposal_artifact_hashes(worktree_path, change_name)
            context_hashes = self._classification_context_hashes(
                active_run, issue_number, issue_title, issue_body
            )
            complexity_result = self._stored_complexity_assessment(
                active_run, artifact_hashes, context_hashes
            )
            if complexity_result is None:
                if (active_run.stop_details or {}).get("complexity_attempts"):
                    return OrchestrationCoordinationResult(
                        status="PAUSED",
                        run_id=active_run.run_id,
                        current_stage=OrchestrationStage.VALIDATING,
                        message="A previous complexity attempt exists; explicit authorization is required before a new invocation.",
                    )
                attempt_id = str(uuid4())
                in_progress = ComplexityAssessment(
                    status="IN_PROGRESS", reason="classification invocation started"
                )
                self._persist_complexity_assessment(
                    active_run,
                    in_progress,
                    attempt_id=attempt_id,
                    model_identity=self._configured_model(uow, project_id, "thinking"),
                    artifact_hashes=artifact_hashes,
                    context_hashes=context_hashes,
                )
                uow.orchestration_runs.save(active_run)
                uow.commit()
                complexity_result = await self._assess_complexity(
                    worktree_path, thinker_provider, issue_title, issue_body, project_id, attempt_id
                )
                self._persist_complexity_assessment(
                    active_run,
                    complexity_result,
                    attempt_id=attempt_id,
                    model_identity=self._configured_model(uow, project_id, "thinking"),
                    artifact_hashes=artifact_hashes,
                    context_hashes=context_hashes,
                )
            if not complexity_result.is_valid:
                if hasattr(uow, "orchestration_runs"):
                    uow.orchestration_runs.save(active_run)
                    if hasattr(uow, "commit"):
                        uow.commit()
                return OrchestrationCoordinationResult(
                    status="PAUSED",
                    run_id=active_run.run_id,
                    current_stage=OrchestrationStage.VALIDATING,
                    message=f"Thinking agent complexity assessment failed: {complexity_result.reason or complexity_result.status}.",
                )
            complexity = complexity_result.complexity
            active_run.stop_details["complexity"] = complexity
            active_run.stop_details["complexity_evidence"] = complexity_result.evidence
            if hasattr(uow, "orchestration_runs"):
                uow.orchestration_runs.save(active_run)
                if hasattr(uow, "commit"):
                    uow.commit()

            # Proposal Review for High Complexity
            if complexity == "high":
                self._update_stage(uow, active_run, OrchestrationStage.PROPOSAL_REVIEW)
            else:
                self._update_stage(uow, active_run, OrchestrationStage.READY_TO_APPLY)

        # Independent Proposal Review Stage (Dedicated reentry block)
        if active_run.current_stage == OrchestrationStage.PROPOSAL_REVIEW:
            if (active_run.stop_details or {}).get("proposal_review_escalated"):
                # The review hit its correction ceiling and escalated to the operator.
                # Only an explicit operator clarification authorizes a fresh revision
                # pass; without it the run stays gated for the human decision.
                if isinstance(operator_clarification, str) and operator_clarification.strip():
                    details = dict(active_run.stop_details or {})
                    stored_review = details.get("proposal_review")
                    findings = (stored_review or {}).get("findings") or []
                    details.pop("proposal_review_escalated", None)
                    details.pop("proposal_review", None)
                    details.pop("proposal_correction", None)
                    # The revised proposal changes the artifacts, so the prior
                    # complexity assessment no longer matches. Drop the durable
                    # one-shot gate so the complexity is re-evaluated (the issue
                    # scope is unchanged, so it stays high).
                    details.pop("complexity_attempts", None)
                    details.pop("complexity_assessment", None)
                    details.pop("complexity", None)
                    details.pop("complexity_evidence", None)
                    details["pending_proposal_revision"] = {
                        "clarification": operator_clarification.strip(),
                        "findings": findings,
                    }
                    active_run.stop_details = details
                    self._clear_current_human_gate(uow, active_run)
                    self._update_stage(uow, active_run, OrchestrationStage.PROPOSING)
                    return OrchestrationCoordinationResult(
                        status="RUNNING",
                        run_id=active_run.run_id,
                        current_stage=OrchestrationStage.PROPOSING,
                        message="Operator authorized a proposal revision; dispatching the thinker to re-propose.",
                    )
                return OrchestrationCoordinationResult(
                    status="HUMAN_REQUIRED",
                    run_id=active_run.run_id,
                    current_stage=OrchestrationStage.PROPOSAL_REVIEW,
                    message="Independent proposal review reached its correction ceiling; operator decision required.",
                )
            stored_review = (active_run.stop_details or {}).get("proposal_review")
            current_hashes = self._compute_proposal_artifacts_hashes(worktree_path, change_name)
            action = self._classify_review_reentry(
                stored_review,
                identity_matches=(
                    isinstance(stored_review, dict)
                    and stored_review.get("artifact_hashes") == current_hashes
                ),
                is_resume=(entry_stage == OrchestrationStage.PROPOSAL_REVIEW),
            )

            if action == _REVIEW_ADVANCE:
                self._clear_current_human_gate(uow, active_run)
                self._update_stage(uow, active_run, OrchestrationStage.READY_TO_APPLY)
            elif action == _REVIEW_REJECTED:
                if isinstance(stored_review, dict) and stored_review.get("findings"):
                    return await self._route_proposal_changes_required(
                        uow=uow,
                        project_id=project_id,
                        run=active_run,
                        result=stored_review,
                        worktree_path=worktree_path,
                        thinker_provider=thinker_provider,
                        change_name=change_name,
                    )
                return OrchestrationCoordinationResult(
                    status="PAUSED",
                    run_id=active_run.run_id,
                    current_stage=OrchestrationStage.PROPOSAL_REVIEW,
                    message=self._review_pause_message("proposal", stored_review),
                )
            elif action == _REVIEW_CORRUPT:
                return OrchestrationCoordinationResult(
                    status="PAUSED",
                    run_id=active_run.run_id,
                    current_stage=OrchestrationStage.PROPOSAL_REVIEW,
                    message="Independent proposal review recorded an invalid approval verdict without READY_TO_MERGE. Worktree preserved.",
                )
            else:
                # _REVIEW_STALE, _REVIEW_TECHNICAL_FAILURE, or _REVIEW_AMBIGUOUS.
                # Re-dispatch freely only when the prior review is stale; a
                # technical failure or ambiguous record needs a single-use,
                # Run-bound recovery authorization before spending again.
                needs_auth = action in {_REVIEW_TECHNICAL_FAILURE, _REVIEW_AMBIGUOUS}
                effective_auth_id = (
                    proposal_review_recovery_authorization_id or propose_recovery_authorization_id
                )
                if needs_auth and not effective_auth_id:
                    msg = (
                        self._review_pause_message("proposal", stored_review)
                        + " Recovery authorization is required to retry."
                        if action == _REVIEW_TECHNICAL_FAILURE
                        else "Proposal review recovery authorization is required before re-dispatch."
                    )
                    return OrchestrationCoordinationResult(
                        status="PAUSED",
                        run_id=active_run.run_id,
                        current_stage=OrchestrationStage.PROPOSAL_REVIEW,
                        message=msg,
                    )
                if needs_auth:
                    operator_actions = getattr(uow, "operator_actions", None)
                    if not operator_actions:
                        return OrchestrationCoordinationResult(
                            status="PAUSED",
                            run_id=active_run.run_id,
                            current_stage=OrchestrationStage.PROPOSAL_REVIEW,
                            message="Operator action store is unavailable for recovery authorization. Worktree preserved.",
                        )
                    consumed = operator_actions.consume_single_use(
                        effective_auth_id,
                        run_id=active_run.run_id,
                        action_type=OperatorActionType.RETRY,
                        expected_parameters={
                            "single_use": True,
                            "stage": "proposal_review",
                            "prior_attempt_id": (stored_review or {}).get("attempt_id"),
                        },
                    )
                    if consumed is None:
                        return OrchestrationCoordinationResult(
                            status="PAUSED",
                            run_id=active_run.run_id,
                            current_stage=OrchestrationStage.PROPOSAL_REVIEW,
                            message="Proposal review recovery authorization is missing, mismatched, or already consumed.",
                        )

                # Record dispatch intent before executing I/O
                attempt_id = str(uuid4())
                review_invocation = await self._begin_stage_invocation(
                    uow, active_run, worktree_path, "PROPOSAL_REVIEW",
                    authorized_retry=needs_auth,
                )
                if review_invocation is None:
                    return OrchestrationCoordinationResult(
                        status="PAUSED", run_id=active_run.run_id,
                        current_stage=OrchestrationStage.PROPOSAL_REVIEW,
                        message="Proposal review invocation is already active or recovery evidence is ambiguous. Worktree preserved.",
                    )
                details = dict(active_run.stop_details or {})
                prior_review = details.get("proposal_review")
                prior_round = (
                    prior_review.get("round")
                    if isinstance(prior_review, dict) and isinstance(prior_review.get("round"), int)
                    else 0
                )
                details["proposal_review"] = {
                    "attempt_id": attempt_id,
                    "status": "dispatched",
                    "reviewer_provider": reviewer_provider,
                    "artifact_hashes": current_hashes,
                    "recorded_at": utc_now().isoformat(),
                    "round": prior_round,
                }
                active_run.stop_details = details
                if hasattr(uow, "orchestration_runs"):
                    uow.orchestration_runs.save(active_run)
                    if hasattr(uow, "commit"):
                        uow.commit()

                try:
                    review_res = await self._run_claimed(
                        uow, review_invocation.claim,
                        lambda: self._run_proposal_review(
                            worktree_path, reviewer_provider, change_name,
                            project_id=project_id, uow=uow,
                            process_start_observer=self._observe_stage_process(
                                uow, active_run, review_invocation
                            ),
                        ),
                    )
                    review_status = (
                        "COMPLETE"
                        if review_res.get("status") in {"approved", "changes_required"}
                        else "FAILED"
                    )
                    await self._finish_stage_invocation(
                        uow, active_run, review_invocation, review_status,
                        {"status": review_res.get("status"),
                         "verdict": review_res.get("verdict"),
                         "findings": review_res.get("findings"),
                         "error": review_res.get("error")},
                    )
                except Exception:
                    uow.claims.release_claim(review_invocation.claim)
                    uow.commit()
                    return OrchestrationCoordinationResult(
                        status="PAUSED", run_id=active_run.run_id,
                        current_stage=OrchestrationStage.PROPOSAL_REVIEW,
                        message="Proposal review invocation failed or lost its durable claim. Worktree preserved.",
                    )
                details = dict(active_run.stop_details or {})
                res_dict = (
                    dict(review_res)
                    if isinstance(review_res, dict)
                    else {
                        "status": "approved" if review_res else "changes_required",
                        "verdict": "READY_TO_MERGE" if review_res else None,
                        "findings": [],
                    }
                )
                details["proposal_review"] = {
                    "attempt_id": attempt_id,
                    **res_dict,
                    "round": prior_round,
                }
                active_run.stop_details = details
                if hasattr(uow, "orchestration_runs"):
                    uow.orchestration_runs.save(active_run)
                    if hasattr(uow, "commit"):
                        uow.commit()

                if (
                    res_dict.get("status") != "approved"
                    or res_dict.get("verdict") != "READY_TO_MERGE"
                ):
                    if res_dict.get("status") == "changes_required":
                        return await self._route_proposal_changes_required(
                            uow=uow,
                            project_id=project_id,
                            run=active_run,
                            result=res_dict,
                            worktree_path=worktree_path,
                            thinker_provider=thinker_provider,
                            change_name=change_name,
                        )
                    return OrchestrationCoordinationResult(
                        status="PAUSED",
                        run_id=active_run.run_id,
                        current_stage=OrchestrationStage.PROPOSAL_REVIEW,
                        message=self._review_pause_message("proposal", res_dict),
                    )
                self._update_stage(uow, active_run, OrchestrationStage.READY_TO_APPLY)

        # Step 6: Verify Presence Verification (Fail-Closed Check Before Apply)
        try:
            self.agent_runner.resolve_workflow(
                worktree_path=worktree_path,
                provider=implementer_provider,
                operation="verify",
                change_name=change_name,
            )
        except NativeOpenSpecWorkflowUnavailable as exc:
            logger.error(
                f"Missing native Verify workflow for implementer {implementer_provider}: {exc}"
            )
            return OrchestrationCoordinationResult(
                status="PAUSED",
                run_id=active_run.run_id,
                current_stage=OrchestrationStage.READY_TO_APPLY,
                message=f"Missing native OpenSpec Verify workflow in worktree: {exc}",
            )

        # Step 7: Apply Stage and Test Execution
        if active_run.current_stage in (
            OrchestrationStage.READY_TO_APPLY,
            OrchestrationStage.IMPLEMENTING,
        ):
            self._update_stage(uow, active_run, OrchestrationStage.IMPLEMENTING)
            # Physical-validation tasks (marked NOT_VERIFIED in tasks.md) require
            # evidence only a human can produce (real devices, manual scenarios).
            # If they are the only remaining unchecked work, escalate immediately
            # instead of burning Apply retries on evidence mini me can never create.
            tasks_path = worktree_path / "openspec" / "changes" / change_name / "tasks.md"
            if tasks_path.is_file():
                tasks_text = tasks_path.read_text(encoding="utf-8", errors="replace")
                automated_pending, not_verified = self._classify_pending_tasks(tasks_text)
                if not automated_pending and not_verified:
                    reason = (
                        "Physical validation required: task(s) "
                        + ", ".join(not_verified)
                        + " need evidence only a human can produce (real devices / physical "
                        "scenarios) and are marked NOT_VERIFIED in tasks.md. Automated Apply "
                        "cannot satisfy them; worktree preserved for operator validation."
                    )
                    return self._escalate_apply_to_human(
                        uow, active_run, reason, gate="physical_validation"
                    )
            # Durable correction context from a prior CHANGES_REQUIRED verdict.
            pending_corrections = list(
                (active_run.stop_details or {}).get("pending_corrections") or []
            )
            prior = (active_run.stop_details or {}).get("apply_snapshot")
            attempts = int((active_run.stop_details or {}).get("apply_total_attempts", self._apply_attempts(active_run)))
            no_progress = int((active_run.stop_details or {}).get("apply_no_progress", 0))
            outcome = None
            policy = {}
            if hasattr(uow, "projects"):
                project = uow.projects.get_by_id(project_id)
                policy = getattr(project, "execution_policy", {}) or {}
            hard_limit = self._positive_policy_limit(policy, "apply_max_attempts", max(1, min(self.max_correction_attempts, 5)))
            no_progress_limit = self._positive_policy_limit(policy, "apply_max_no_progress", 2)
            details = dict(active_run.stop_details or {})
            details["apply_limits"] = {"max_attempts": hard_limit, "max_no_progress": no_progress_limit}
            self._persist_run_stop_details(active_run, details)
            while attempts < hard_limit:
                invocation = await self._begin_stage_invocation(
                    uow, active_run, worktree_path, "APPLY",
                    allow_human_resume=bool(operator_clarification),
                )
                if invocation is None:
                    return OrchestrationCoordinationResult(
                        status="PAUSED", run_id=active_run.run_id,
                        current_stage=OrchestrationStage.IMPLEMENTING,
                        message="Apply invocation is already active or recovery evidence is ambiguous. Worktree preserved.",
                    )
                try:
                    outcome = await self._run_claimed(
                        uow, invocation.claim,
                        lambda: self._run_apply(
                            worktree_path, implementer_provider, change_name,
                            project_id=project_id, corrections=pending_corrections,
                            recovery_context=self._apply_recovery_context(prior),
                            run_id=active_run.run_id, base_branch=base_branch,
                            operator_response=operator_clarification,
                            process_start_observer=self._observe_stage_process(
                                uow, active_run, invocation
                            ),
                        ),
                    )
                    await self._finish_stage_invocation(
                        uow, active_run, invocation, outcome.status,
                        {
                            "candidate_sha": outcome.candidate_sha,
                            "changed_files": list(outcome.changed_files),
                            "completed_tasks": list(outcome.completed_tasks),
                            "pending_tasks": list(outcome.pending_tasks),
                            "error": outcome.error,
                            "human_question": outcome.human_question,
                            "human_options": list(outcome.human_options),
                        },
                    )
                except Exception as exc:
                    logger.warning("Apply invocation failed: %s", exc)
                    return OrchestrationCoordinationResult(
                        status="PAUSED", run_id=active_run.run_id,
                        current_stage=OrchestrationStage.IMPLEMENTING,
                        message="Apply invocation failed or lost its durable claim. Worktree preserved.",
                    )
                if isinstance(outcome, bool):
                    outcome = ApplyOutcome("COMPLETE" if outcome else "FAILED", (), (), None, (), None,
                                           None, "Legacy boolean Apply result; no structured evidence.")
                attempts += 1
                if outcome.status == "HUMAN_REQUIRED":
                    payload = self._record_current_human_gate(
                        uow,
                        active_run,
                        gate="apply_escalation",
                        question=outcome.human_question or "OpenSpec Apply requires operator input.",
                        options=outcome.human_options,
                    )
                    return OrchestrationCoordinationResult(
                        status="HUMAN_REQUIRED", run_id=active_run.run_id,
                        current_stage=OrchestrationStage.IMPLEMENTING,
                        message=payload["question"],
                        human_payload=payload,
                    )
                if outcome.status == "COMPLETE":
                    break
                if prior and self._apply_regressed(prior, outcome):
                    return self._escalate_apply_to_human(
                        uow,
                        active_run,
                        "Apply recovery detected candidate regression; automatic retries stopped. Candidate preserved.",
                        attempts=attempts,
                        hard_limit=hard_limit,
                        no_progress=no_progress,
                        outcome=outcome,
                        worktree_path=worktree_path,
                        change_name=change_name,
                    )
                progressed = prior is None or self._apply_made_progress(prior, outcome)
                if not progressed:
                    no_progress += 1
                else:
                    no_progress = 0
                prior = self._apply_snapshot(outcome)
                details = dict(active_run.stop_details or {})
                details.update(apply_snapshot=prior, apply_total_attempts=attempts,
                               apply_no_progress=no_progress)
                active_run.stop_details = details
                self._persist_run_stop_details(active_run, details)
                if outcome.status == "FAILED" or no_progress >= no_progress_limit:
                    break
            if outcome is None or outcome.status != "COMPLETE":
                return self._escalate_apply_to_human(
                    uow,
                    active_run,
                    f"Native Apply failed or recovery stopped ({outcome.status if outcome is not None else 'NO_RESULT'}); "
                    f"hard attempt ceiling {hard_limit} reached or recovery halted; "
                    f"attempts={attempts}/{hard_limit}, no_progress={no_progress}. Candidate preserved.",
                    attempts=attempts,
                    hard_limit=hard_limit,
                    no_progress=no_progress,
                    outcome=outcome,
                    worktree_path=worktree_path,
                    change_name=change_name,
                )
            self._clear_current_human_gate(uow, active_run)
            if pending_corrections or self._apply_attempts(active_run):
                details = dict(active_run.stop_details or {})
                details.pop("pending_corrections", None)
                details.pop("apply_failure_count", None)
                active_run.stop_details = details
                if hasattr(uow, "orchestration_runs"):
                    uow.orchestration_runs.save(active_run)
                    if hasattr(uow, "commit"):
                        uow.commit()
            self._update_stage(uow, active_run, OrchestrationStage.RUNNING_TESTS)

        if active_run.current_stage == OrchestrationStage.RUNNING_TESTS:
            tests_ok, test_evidence = (outcome.tests_passed, outcome.test_evidence) if outcome else (None, "")
            if tests_ok is None:
                tests_ok, test_evidence = await self._run_automated_tests(worktree_path, base_branch)
            active_run.stop_details["test_evidence"] = test_evidence
            if hasattr(uow, "orchestration_runs"):
                uow.orchestration_runs.save(active_run)
                if hasattr(uow, "commit"):
                    uow.commit()
            if not tests_ok:
                return OrchestrationCoordinationResult(
                    status="PAUSED",
                    run_id=active_run.run_id,
                    current_stage=OrchestrationStage.RUNNING_TESTS,
                    message="Automated tests failed during Apply. Worktree preserved.",
                )

            self._update_stage(uow, active_run, OrchestrationStage.VERIFYING)

        if active_run.current_stage == OrchestrationStage.VERIFYING:
            # Step 8: Verify Stage (Executed by implementer)
            invocation = await self._begin_stage_invocation(
                uow, active_run, worktree_path, "VERIFY",
                allow_human_resume=bool(operator_clarification),
            )
            if invocation is None:
                return OrchestrationCoordinationResult(
                    status="PAUSED", run_id=active_run.run_id,
                    current_stage=OrchestrationStage.VERIFYING,
                    message="Verify invocation is already active or recovery evidence is ambiguous. Worktree preserved.",
                )
            try:
                verify_outcome = await self._run_claimed(
                    uow, invocation.claim,
                    lambda: self._run_verify(
                        worktree_path, implementer_provider, change_name,
                        project_id=project_id,
                        operator_response=operator_clarification,
                        process_start_observer=self._observe_stage_process(
                            uow, active_run, invocation
                        ),
                    ),
                )
                await self._finish_stage_invocation(
                    uow, active_run, invocation, verify_outcome.status,
                    {"summary": verify_outcome.summary,
                     "human_question": verify_outcome.human_question,
                     "human_options": list(verify_outcome.human_options),
                     "findings": list(verify_outcome.findings)},
                )
            except Exception as exc:
                logger.warning("Verify invocation failed: %s", exc)
                return OrchestrationCoordinationResult(
                    status="PAUSED", run_id=active_run.run_id,
                    current_stage=OrchestrationStage.VERIFYING,
                    message="Verify invocation failed or lost its durable claim. Worktree preserved.",
                )
            if verify_outcome.status == "HUMAN_REQUIRED":
                payload = self._record_current_human_gate(
                    uow, active_run, gate="apply_escalation",
                    question=verify_outcome.human_question or "OpenSpec Verify requires operator input.",
                    options=verify_outcome.human_options,
                )
                return OrchestrationCoordinationResult(
                    status="HUMAN_REQUIRED", run_id=active_run.run_id,
                    current_stage=OrchestrationStage.VERIFYING,
                    message=payload["question"], human_payload=payload,
                )
            if not verify_outcome:
                return OrchestrationCoordinationResult(
                    status="PAUSED",
                    run_id=active_run.run_id,
                    current_stage=OrchestrationStage.VERIFYING,
                    message="OpenSpec verify reported discrepancies. Worktree preserved.",
                )

            # Step 9: Post-Verify Routing & Code Review
            complexity = active_run.stop_details.get("complexity", "moderate")
            if complexity == "high":
                try:
                    await self._ensure_candidate_commit(worktree_path, issue_number)
                except GitOperationError as exc:
                    return OrchestrationCoordinationResult(
                        status="PAUSED",
                        run_id=active_run.run_id,
                        current_stage=OrchestrationStage.VERIFYING,
                        message=f"Unable to commit candidate changes before code review: {exc}. Worktree preserved.",
                    )
                self._update_stage(uow, active_run, OrchestrationStage.CODE_REVIEW)
            else:
                self._update_stage(uow, active_run, OrchestrationStage.READY_FOR_PR)

        # Independent Code Review Stage (Dedicated reentry block)
        if active_run.current_stage == OrchestrationStage.CODE_REVIEW:
            try:
                await self._ensure_candidate_commit(worktree_path, issue_number)
                candidate_sha = await self._get_git_head_sha(worktree_path)
                active_run.current_candidate_sha = candidate_sha
                if hasattr(uow, "orchestration_runs"):
                    uow.orchestration_runs.save(active_run)
                    if hasattr(uow, "commit"):
                        uow.commit()
            except GitOperationError as exc:
                return OrchestrationCoordinationResult(
                    status="PAUSED",
                    run_id=active_run.run_id,
                    current_stage=OrchestrationStage.CODE_REVIEW,
                    message=f"Unable to observe candidate Git state: {exc}. Worktree preserved.",
                )
            stored_code_review = (active_run.stop_details or {}).get("code_review")
            action = self._classify_review_reentry(
                stored_code_review,
                identity_matches=(
                    isinstance(stored_code_review, dict)
                    and stored_code_review.get("candidate_sha") == candidate_sha
                ),
                is_resume=(entry_stage == OrchestrationStage.CODE_REVIEW),
            )

            if action == _REVIEW_ADVANCE:
                self._clear_current_human_gate(uow, active_run)
                self._update_stage(uow, active_run, OrchestrationStage.READY_FOR_PR)
            elif action == _REVIEW_REJECTED:
                return self._route_changes_required(
                    uow, project_id, active_run, stored_code_review
                )
            elif action == _REVIEW_CORRUPT:
                return OrchestrationCoordinationResult(
                    status="PAUSED",
                    run_id=active_run.run_id,
                    current_stage=OrchestrationStage.CODE_REVIEW,
                    message="Independent code review recorded an invalid approval verdict without READY_TO_MERGE. Worktree preserved.",
                )
            else:
                # _REVIEW_STALE, _REVIEW_TECHNICAL_FAILURE, or _REVIEW_AMBIGUOUS.
                needs_auth = action in {_REVIEW_TECHNICAL_FAILURE, _REVIEW_AMBIGUOUS}
                effective_code_auth_id = (
                    code_review_recovery_authorization_id or propose_recovery_authorization_id
                )
                if needs_auth and not effective_code_auth_id:
                    msg = (
                        self._review_pause_message("code", stored_code_review)
                        + " Recovery authorization is required to retry."
                        if action == _REVIEW_TECHNICAL_FAILURE
                        else "Code review recovery authorization is required before re-dispatch."
                    )
                    return OrchestrationCoordinationResult(
                        status="PAUSED",
                        run_id=active_run.run_id,
                        current_stage=OrchestrationStage.CODE_REVIEW,
                        message=msg,
                    )
                if needs_auth:
                    operator_actions = getattr(uow, "operator_actions", None)
                    if not operator_actions:
                        return OrchestrationCoordinationResult(
                            status="PAUSED",
                            run_id=active_run.run_id,
                            current_stage=OrchestrationStage.CODE_REVIEW,
                            message="Operator action store is unavailable for recovery authorization. Worktree preserved.",
                        )
                    consumed = operator_actions.consume_single_use(
                        effective_code_auth_id,
                        run_id=active_run.run_id,
                        action_type=OperatorActionType.RETRY,
                        expected_parameters={
                            "single_use": True,
                            "stage": "code_review",
                            "prior_attempt_id": (stored_code_review or {}).get("attempt_id"),
                        },
                    )
                    if consumed is None:
                        return OrchestrationCoordinationResult(
                            status="PAUSED",
                            run_id=active_run.run_id,
                            current_stage=OrchestrationStage.CODE_REVIEW,
                            message="Code review recovery authorization is missing, mismatched, or already consumed.",
                        )

                attempt_id = str(uuid4())
                review_invocation = await self._begin_stage_invocation(
                    uow, active_run, worktree_path, "CODE_REVIEW",
                    authorized_retry=needs_auth,
                )
                if review_invocation is None:
                    return OrchestrationCoordinationResult(
                        status="PAUSED", run_id=active_run.run_id,
                        current_stage=OrchestrationStage.CODE_REVIEW,
                        message="Code review invocation is already active or recovery evidence is ambiguous. Worktree preserved.",
                    )
                details = dict(active_run.stop_details or {})
                prior_review = details.get("code_review")
                prior_round = (
                    prior_review.get("round")
                    if isinstance(prior_review, dict) and isinstance(prior_review.get("round"), int)
                    else 0
                )
                details["code_review"] = {
                    "attempt_id": attempt_id,
                    "status": "dispatched",
                    "reviewer_provider": reviewer_provider,
                    "candidate_sha": candidate_sha,
                    "recorded_at": utc_now().isoformat(),
                    "round": prior_round,
                }
                active_run.stop_details = details
                if hasattr(uow, "orchestration_runs"):
                    uow.orchestration_runs.save(active_run)
                    if hasattr(uow, "commit"):
                        uow.commit()

                try:
                    code_review_res = await self._run_claimed(
                        uow, review_invocation.claim,
                        lambda: self._run_code_review(
                            worktree_path,
                            reviewer_provider,
                            change_name,
                            project_id=project_id,
                            candidate_sha=candidate_sha,
                            uow=uow,
                            process_start_observer=self._observe_stage_process(
                                uow, active_run, review_invocation
                            ),
                        ),
                    )
                    review_status = (
                        "COMPLETE"
                        if code_review_res.get("status") in {"approved", "changes_required"}
                        else "FAILED"
                    )
                    await self._finish_stage_invocation(
                        uow, active_run, review_invocation, review_status,
                        {"status": code_review_res.get("status"),
                         "verdict": code_review_res.get("verdict"),
                         "candidate_sha": candidate_sha,
                         "findings": code_review_res.get("findings"),
                         "error": code_review_res.get("error")},
                    )
                except Exception:
                    uow.claims.release_claim(review_invocation.claim)
                    uow.commit()
                    return OrchestrationCoordinationResult(
                        status="PAUSED", run_id=active_run.run_id,
                        current_stage=OrchestrationStage.CODE_REVIEW,
                        message="Code review invocation failed or lost its durable claim. Worktree preserved.",
                    )
                details = dict(active_run.stop_details or {})
                c_dict = (
                    dict(code_review_res)
                    if isinstance(code_review_res, dict)
                    else {
                        "status": "approved" if code_review_res else "changes_required",
                        "candidate_sha": candidate_sha,
                        "verdict": "READY_TO_MERGE" if code_review_res else None,
                        "findings": [],
                    }
                )
                details["code_review"] = {
                    "attempt_id": attempt_id,
                    **c_dict,
                    "round": prior_round,
                }
                active_run.stop_details = details
                if hasattr(uow, "orchestration_runs"):
                    uow.orchestration_runs.save(active_run)
                    if hasattr(uow, "commit"):
                        uow.commit()

                if c_dict.get("status") != "approved" or c_dict.get("verdict") != "READY_TO_MERGE":
                    if c_dict.get("status") == "changes_required":
                        return self._route_changes_required(uow, project_id, active_run, c_dict)
                    return OrchestrationCoordinationResult(
                        status="PAUSED",
                        run_id=active_run.run_id,
                        current_stage=OrchestrationStage.CODE_REVIEW,
                        message=self._review_pause_message("code", c_dict),
                    )
                self._update_stage(uow, active_run, OrchestrationStage.READY_FOR_PR)

        # Step 10: Implementation PR (PR1)
        pr1_url = (active_run.stop_details or {}).get("pr1_url")
        pr1_number = (active_run.stop_details or {}).get("pr1_number")
        if active_run.current_stage in (
            OrchestrationStage.READY_FOR_PR,
            OrchestrationStage.PR1_PENDING,
        ):
            complexity = (active_run.stop_details or {}).get("complexity", "moderate")

            # If PR1 is not yet created, ensure commit and get candidate SHA
            if not pr1_number:
                try:
                    await self._ensure_candidate_commit(worktree_path, issue_number)
                except GitOperationError as exc:
                    return OrchestrationCoordinationResult(
                        status="PAUSED",
                        run_id=active_run.run_id,
                        current_stage=OrchestrationStage.READY_FOR_PR,
                        message=f"Unable to persist candidate Git state: {exc}. Worktree preserved.",
                    )
                try:
                    candidate_sha = await self._get_git_head_sha(worktree_path)
                except GitOperationError as exc:
                    return OrchestrationCoordinationResult(
                        status="PAUSED",
                        run_id=active_run.run_id,
                        current_stage=active_run.current_stage,
                        message=f"Unable to observe candidate Git state: {exc}. Worktree preserved.",
                    )
                active_run.candidate_sha = candidate_sha

                self._update_stage(uow, active_run, OrchestrationStage.PR1_PENDING)
                test_evidence = str(active_run.stop_details.get("test_evidence") or "").strip()
                if not test_evidence:
                    return OrchestrationCoordinationResult(
                        status="PAUSED",
                        run_id=active_run.run_id,
                        current_stage=OrchestrationStage.PR1_PENDING,
                        message="Verified test evidence is required before preparing PR1. Worktree preserved.",
                    )
                prep_input = PrPreparationInput(
                    project_id=project_id,
                    repository=repository,
                    pr_type="implementation",
                    issue_number=issue_number,
                    issue_title=issue_title,
                    base_branch=base_branch,
                    candidate_branch=worktree_info.branch_name,
                    candidate_sha=candidate_sha,
                    change_name=change_name,
                    change_summary=f"Implementation of request #{issue_number}: {issue_title}",
                    test_evidence=test_evidence,
                    complexity=complexity,
                )
                if self.semantic_pr_agent:
                    try:
                        semantic_title, semantic_body = await self._prepare_semantic_pr_content(
                            worktree_path=worktree_path,
                            provider=thinker_provider,
                            project_id=project_id,
                            run_id=active_run.run_id,
                            pr_input=prep_input,
                            request_body=issue_body,
                        )
                    except (NativeOpenSpecWorkflowUnavailable, ValueError, OSError) as exc:
                        return OrchestrationCoordinationResult(
                            status="PAUSED",
                            run_id=active_run.run_id,
                            current_stage=OrchestrationStage.PR1_PENDING,
                            message=f"Semantic PR1 content was not verified: {exc}. Worktree preserved.",
                        )
                    prep_input = dataclass_replace(
                        prep_input, semantic_title=semantic_title, semantic_body=semantic_body
                    )
                prepared_pr = self.pr_preparer.prepare_pull_request(prep_input)

                # Push branch
                try:
                    await self._push_branch(worktree_path, worktree_info.branch_name)
                except GitOperationError as exc:
                    return OrchestrationCoordinationResult(
                        status="PAUSED",
                        run_id=active_run.run_id,
                        current_stage=OrchestrationStage.PR1_PENDING,
                        message=f"Unable to publish PR1 branch: {exc}. Worktree preserved.",
                    )

                # Open PR via GitHubAdapter
                opened_pr_call = (
                    self.github_adapter.create_pull_request(
                        repository=repository,
                        branch=worktree_info.branch_name,
                        base=base_branch,
                        title=prepared_pr.title,
                        body=prepared_pr.body,
                        head_sha=candidate_sha,
                        draft=False,
                    )
                    if hasattr(self.github_adapter, "_repo")
                    else self.github_adapter.create_pull_request(
                        base=base_branch,
                        head=worktree_info.branch_name,
                        title=prepared_pr.title,
                        body=prepared_pr.body,
                    )
                )
                opened_pr_res = (
                    await opened_pr_call if inspect.isawaitable(opened_pr_call) else opened_pr_call
                )
                if not self._external_success(opened_pr_res):
                    pr_error = (
                        getattr(opened_pr_res, "error_message", None)
                        or "remote response was not successful"
                    )
                    return OrchestrationCoordinationResult(
                        status="PAUSED",
                        run_id=active_run.run_id,
                        current_stage=OrchestrationStage.PR1_PENDING,
                        message=f"GitHub did not confirm creation of PR1: {pr_error}. Worktree preserved.",
                    )
                opened_data = (
                    opened_pr_res.data if hasattr(opened_pr_res, "data") else opened_pr_res
                )
                pr1_number = (
                    opened_data.get("number")
                    if isinstance(opened_data, dict)
                    else getattr(opened_data, "number", None)
                )
                pr1_url = (
                    opened_data.get("html_url")
                    if isinstance(opened_data, dict)
                    else getattr(opened_data, "html_url", None)
                )
                if not pr1_number or not await self._confirm_pr_open(
                    repository, pr1_number, worktree_info.branch_name, base_branch, candidate_sha
                ):
                    return OrchestrationCoordinationResult(
                        status="PAUSED",
                        run_id=active_run.run_id,
                        current_stage=OrchestrationStage.PR1_PENDING,
                        pr1_url=pr1_url,
                        message="PR1 identity or remote head/base state was not confirmed.",
                    )
                active_run.stop_details["pr1_number"] = pr1_number
                active_run.stop_details["pr1_url"] = pr1_url
                if hasattr(uow, "orchestration_runs"):
                    uow.orchestration_runs.save(active_run)
                    if hasattr(uow, "commit"):
                        uow.commit()
            else:
                candidate_sha = active_run.candidate_sha or await self._get_git_head_sha(
                    worktree_path
                )

        # Differentiated Merge Policy for PR1
        if active_run.current_stage == OrchestrationStage.PR1_PENDING:
            if complexity == "high" and not operator_ack:
                payload = self._record_pr1_acknowledgement_gate(
                    uow,
                    active_run,
                    issue_number=issue_number,
                    issue_title=issue_title,
                    pr_number=pr1_number,
                )
                return OrchestrationCoordinationResult(
                    status="HUMAN_REQUIRED",
                    run_id=active_run.run_id,
                    current_stage=OrchestrationStage.PR1_PENDING,
                    pr1_url=pr1_url,
                    message="High-complexity change requires operator acknowledgement («Estoy enterado») before merging PR1.",
                    human_payload=payload,
                )

            # Merge PR1
            merge_call = (
                self.github_adapter.merge_pull_request(
                    repository=repository,
                    pr_number=pr1_number,
                    candidate_sha=candidate_sha,
                    merge_method="merge",
                )
                if hasattr(self.github_adapter, "_repo")
                else self.github_adapter.merge_pull_request(
                    pull_number=pr1_number,
                    expected_head_sha=candidate_sha,
                    merge_method="merge",
                )
            )
            merge_res = await merge_call if inspect.isawaitable(merge_call) else merge_call
            if not self._external_success(merge_res):
                is_merged = False
            else:
                is_merged = await self._confirm_pr_merged(repository, pr1_number, candidate_sha)

            if not is_merged:
                err_msg = getattr(merge_res, "error_message", "Merge failed")
                return OrchestrationCoordinationResult(
                    status="PAUSED",
                    run_id=active_run.run_id,
                    current_stage=OrchestrationStage.PR1_PENDING,
                    pr1_url=pr1_url,
                    message=f"Failed to merge PR1: {err_msg}. Worktree preserved.",
                )
            self._clear_current_human_gate(uow, active_run)
            self._update_stage(uow, active_run, OrchestrationStage.PR1_MERGED)

        # Step 11: Fresh Documentation Worktree & Sync/Archive (PR2)
        if active_run.current_stage not in (
            OrchestrationStage.PR1_MERGED,
            OrchestrationStage.DOC_CLOSING,
            OrchestrationStage.PR2_PENDING,
        ):
            return OrchestrationCoordinationResult(
                status="PAUSED",
                run_id=active_run.run_id,
                current_stage=active_run.current_stage,
                message=f"Documentation closing cannot start from stage {active_run.current_stage.value}. Worktree preserved.",
            )

        pr2_number = active_run.stop_details.get("pr2_number")
        pr2_url = active_run.stop_details.get("pr2_url")

        if not pr2_number:
            self._update_stage(uow, active_run, OrchestrationStage.DOC_CLOSING)
            doc_worktree_info = await self.worktree_manager.create_documentation_worktree(
                project_id=project_id,
                issue_number=issue_number,
                issue_title=issue_title,
                base_branch=base_branch,
                run_id=active_run.run_id,
            )
            doc_path = doc_worktree_info.path

            try:
                sync_archive_ok, state_detail = await self._ensure_doc_closing_sync_archive(
                    doc_path, thinker_provider, change_name, project_id=project_id,
                    uow=uow, run=active_run,
                    operator_response=operator_clarification,
                )
            except GitOperationError as exc:
                return OrchestrationCoordinationResult(
                    status="PAUSED",
                    run_id=active_run.run_id,
                    current_stage=OrchestrationStage.DOC_CLOSING,
                    pr1_url=pr1_url,
                    message=f"Documentation Git operation failed: {exc}. Worktree preserved.",
                )
            if not sync_archive_ok:
                current_gate = (active_run.stop_details or {}).get("human_payload")
                if (
                    active_run.human_gate == HumanGate.NEEDS_HUMAN
                    and isinstance(current_gate, dict)
                ):
                    return OrchestrationCoordinationResult(
                        status="HUMAN_REQUIRED", run_id=active_run.run_id,
                        current_stage=OrchestrationStage.DOC_CLOSING,
                        pr1_url=pr1_url,
                        message=str(current_gate.get("question") or state_detail or "DOC_CLOSING requires operator input."),
                        human_payload=self._safe_human_payload(current_gate),
                    )
                return OrchestrationCoordinationResult(
                    status="PAUSED",
                    run_id=active_run.run_id,
                    current_stage=OrchestrationStage.DOC_CLOSING,
                    pr1_url=pr1_url,
                    message=(
                        f"{state_detail or 'Native Sync or Archive failed.'} "
                        "Documentation worktree preserved."
                    ),
                )
            self._clear_current_human_gate(uow, active_run)
            try:
                doc_head_sha = await self._get_git_head_sha(doc_path)
            except GitOperationError as exc:
                return OrchestrationCoordinationResult(
                    status="PAUSED",
                    run_id=active_run.run_id,
                    current_stage=OrchestrationStage.DOC_CLOSING,
                    pr1_url=pr1_url,
                    message=f"Unable to observe documentation Git state: {exc}. Worktree preserved.",
                )

            # Step 12: Documentation PR (PR2)
            self._update_stage(uow, active_run, OrchestrationStage.PR2_PENDING)
            doc_prep_input = PrPreparationInput(
                project_id=project_id,
                repository=repository,
                pr_type="documentation",
                issue_number=issue_number,
                issue_title=issue_title,
                base_branch=base_branch,
                candidate_branch=doc_worktree_info.branch_name,
                candidate_sha=doc_head_sha,
                change_name=change_name,
                change_summary=f"Documentation sync and archive for request #{issue_number}",
                test_evidence="OpenSpec native sync and archive completed successfully.",
            )
            if self.semantic_pr_agent:
                try:
                    semantic_title, semantic_body = await self._prepare_semantic_pr_content(
                        worktree_path=doc_path,
                        provider=thinker_provider,
                        project_id=project_id,
                        run_id=active_run.run_id,
                        pr_input=doc_prep_input,
                        request_body=issue_body,
                    )
                except (NativeOpenSpecWorkflowUnavailable, ValueError, OSError) as exc:
                    return OrchestrationCoordinationResult(
                        status="PAUSED",
                        run_id=active_run.run_id,
                        current_stage=OrchestrationStage.PR2_PENDING,
                        pr1_url=pr1_url,
                        message=f"Semantic PR2 content was not verified: {exc}. Worktree preserved.",
                    )
                doc_prep_input = dataclass_replace(
                    doc_prep_input, semantic_title=semantic_title, semantic_body=semantic_body
                )
            prepared_doc_pr = self.pr_preparer.prepare_pull_request(doc_prep_input)

            try:
                await self._push_branch(doc_path, doc_worktree_info.branch_name)
            except GitOperationError as exc:
                return OrchestrationCoordinationResult(
                    status="PAUSED",
                    run_id=active_run.run_id,
                    current_stage=OrchestrationStage.PR2_PENDING,
                    pr1_url=pr1_url,
                    message=f"Unable to publish PR2 branch: {exc}. Worktree preserved.",
                )
            opened_doc_call = (
                self.github_adapter.create_pull_request(
                    repository=repository,
                    branch=doc_worktree_info.branch_name,
                    base=base_branch,
                    title=prepared_doc_pr.title,
                    body=prepared_doc_pr.body,
                    head_sha=doc_head_sha,
                    draft=False,
                )
                if hasattr(self.github_adapter, "_repo")
                else self.github_adapter.create_pull_request(
                    base=base_branch,
                    head=doc_worktree_info.branch_name,
                    title=prepared_doc_pr.title,
                    body=prepared_doc_pr.body,
                )
            )
            opened_doc_res = (
                await opened_doc_call if inspect.isawaitable(opened_doc_call) else opened_doc_call
            )
            if not self._external_success(opened_doc_res):
                return OrchestrationCoordinationResult(
                    status="PAUSED",
                    run_id=active_run.run_id,
                    current_stage=OrchestrationStage.PR2_PENDING,
                    pr1_url=pr1_url,
                    message="GitHub did not confirm creation of PR2. Worktree preserved.",
                )
            opened_doc_data = (
                opened_doc_res.data if hasattr(opened_doc_res, "data") else opened_doc_res
            )
            pr2_number = (
                opened_doc_data.get("number")
                if isinstance(opened_doc_data, dict)
                else getattr(opened_doc_data, "number", None)
            )
            pr2_url = (
                opened_doc_data.get("html_url")
                if isinstance(opened_doc_data, dict)
                else getattr(opened_doc_data, "html_url", None)
            )
            if not pr2_number or not await self._confirm_pr_open(
                repository, pr2_number, doc_worktree_info.branch_name, base_branch, doc_head_sha
            ):
                return OrchestrationCoordinationResult(
                    status="PAUSED",
                    run_id=active_run.run_id,
                    current_stage=OrchestrationStage.PR2_PENDING,
                    pr1_url=pr1_url,
                    pr2_url=pr2_url,
                    message="PR2 identity or remote head/base state was not confirmed.",
                )
            active_run.stop_details["pr2_number"] = pr2_number
            active_run.stop_details["pr2_url"] = pr2_url
            active_run.stop_details["pr2_head_sha"] = doc_head_sha

        doc_head_sha = active_run.stop_details.get("pr2_head_sha")

        # PR2 Auto-merge (always automatic)
        merge_doc_call = (
            self.github_adapter.merge_pull_request(
                repository=repository,
                pr_number=pr2_number,
                candidate_sha=doc_head_sha,
                merge_method="merge",
            )
            if hasattr(self.github_adapter, "_repo")
            else self.github_adapter.merge_pull_request(
                pull_number=pr2_number,
                expected_head_sha=doc_head_sha,
                merge_method="merge",
            )
        )
        merge_doc_res = (
            await merge_doc_call if inspect.isawaitable(merge_doc_call) else merge_doc_call
        )
        doc_merged = self._external_success(merge_doc_res) and await self._confirm_pr_merged(
            repository, pr2_number, doc_head_sha
        )

        if not doc_merged:
            err_msg = getattr(merge_doc_res, "error_message", "Merge PR2 failed")
            return OrchestrationCoordinationResult(
                status="PAUSED",
                run_id=active_run.run_id,
                current_stage=OrchestrationStage.PR2_PENDING,
                pr1_url=pr1_url,
                pr2_url=pr2_url,
                message=f"Failed to merge documentation PR2: {err_msg}. Worktrees preserved.",
            )

        self._update_stage(uow, active_run, OrchestrationStage.PR2_MERGED)

        # Step 13: Remote Issue Closure and Lock Release
        close_call = (
            self.github_adapter.close_issue(
                repository=repository,
                issue_number=issue_number,
                comment=(
                    f"Ciclo completado por mini me.\n\n"
                    f"- PR de implementación: #{pr1_number} ({pr1_url})\n"
                    f"- PR documental: #{pr2_number} ({pr2_url})\n"
                    f"- Change OpenSpec: `{change_name}` archivado."
                ),
            )
            if hasattr(self.github_adapter, "_repo")
            else self.github_adapter.close_issue(
                issue_number=issue_number,
                comment=(
                    f"Ciclo completado por mini me.\n\n"
                    f"- PR de implementación: #{pr1_number} ({pr1_url})\n"
                    f"- PR documental: #{pr2_number} ({pr2_url})\n"
                    f"- Change OpenSpec: `{change_name}` archivado."
                ),
            )
        )
        close_res = await close_call if inspect.isawaitable(close_call) else close_call
        if not self._external_success(close_res) or not await self._confirm_issue_closed(
            repository, issue_number
        ):
            return OrchestrationCoordinationResult(
                status="PAUSED",
                run_id=active_run.run_id,
                current_stage=OrchestrationStage.PR2_MERGED,
                pr1_url=pr1_url,
                pr2_url=pr2_url,
                message="Remote issue closure was not confirmed; lock remains held.",
            )

        active_run.is_active = False
        active_run.stop_outcome = OrchestrationStopOutcome.COMPLETED
        self._update_stage(uow, active_run, OrchestrationStage.COMPLETED)

        # Clean up the managed worktree now that the change is complete and merged.
        try:
            cleanup = await self.worktree_manager.remove_clean_worktree_path(
                worktree_path, active_run.run_id, project_id
            )
            if cleanup.outcome != ExternalOutcome.SUCCESS:
                logger.warning(
                    f"Worktree cleanup for completed run {active_run.run_id} did not succeed: "
                    f"{cleanup.reason_code} — {cleanup.provider_detail}"
                )
        except Exception as exc:  # cleanup is best-effort; never block completion on it
            logger.warning(f"Worktree cleanup for completed run {active_run.run_id} failed: {exc}")

        # Apply any pending deferred transitions for this project or global pause
        applied_transitions = self._apply_deferred_transitions(uow, project_id)
        if applied_transitions:
            active_run.stop_details["applied_transitions"] = applied_transitions

        # Check if project remains the selected executor and is not paused
        can_admit_next = True
        if hasattr(uow, "projects"):
            current_p = uow.projects.get_by_id(project_id)
            if current_p:
                pol = getattr(current_p, "execution_policy", {}) or {}
                if not pol.get("is_executor", False) or pol.get("effective_pause", False) or pol.get("global_pause", False):
                    can_admit_next = False
        if hasattr(uow, "deferred_transitions"):
            if uow.deferred_transitions.get_pending_by_project(project_id):
                can_admit_next = False

        if can_admit_next:
            next_request = intake_service.select_next_request(project_id, repository)
            next_run = self._admit_next_fifo_request(
                uow=uow,
                project_id=project_id,
                repository=repository,
                completed_run_id=active_run.run_id,
                next_request=next_request,
            )
            active_run.stop_details["next_fifo_request"] = (
                next_request.get("issue_number") if next_request else None
            )
            active_run.stop_details["next_fifo_run_id"] = next_run.run_id if next_run else None
        else:
            active_run.stop_details["next_fifo_request"] = None
            active_run.stop_details["next_fifo_run_id"] = None
        if hasattr(uow, "orchestration_runs"):
            uow.orchestration_runs.save(active_run)
            if hasattr(uow, "commit"):
                uow.commit()

        return OrchestrationCoordinationResult(
            status="COMPLETED",
            run_id=active_run.run_id,
            current_stage=OrchestrationStage.COMPLETED,
            pr1_url=pr1_url,
            pr2_url=pr2_url,
            message=f"Request #{issue_number} successfully implemented, verified, merged, and closed.",
        )

    @staticmethod
    def _apply_deferred_transitions(uow: PersistenceUnitOfWork, project_id: str) -> list[str]:
        applied = []
        if not hasattr(uow, "deferred_transitions") or not hasattr(uow, "projects"):
            return applied

        pending = list(uow.deferred_transitions.get_pending_by_project(project_id))
        pending_all = uow.deferred_transitions.list_pending()
        for t in pending_all:
            if t not in pending and t.transition_type == "global_pause":
                pending.append(t)

        now = utc_now()
        for transition in pending:
            if transition.transition_type == "change_executor" and transition.target_project_id:
                projects = uow.projects.list_all() if hasattr(uow.projects, "list_all") else []
                for p_item in projects:
                    pol = dict(p_item.execution_policy or {})
                    pol["is_executor"] = (p_item.project_id == transition.target_project_id)
                    p_item.execution_policy = pol
                    p_item.updated_at = now
                    uow.projects.save(p_item)
                transition.status = "APPLIED"
                transition.applied_at = now
                uow.deferred_transitions.save(transition)
                applied.append(f"change_executor->{transition.target_project_id}")

            elif transition.transition_type == "project_pause":
                p_item = uow.projects.get_by_id(transition.project_id)
                if p_item:
                    pol = dict(p_item.execution_policy or {})
                    pol["effective_pause"] = True
                    p_item.execution_policy = pol
                    p_item.updated_at = now
                    uow.projects.save(p_item)
                transition.status = "APPLIED"
                transition.applied_at = now
                uow.deferred_transitions.save(transition)
                applied.append(f"project_pause->{transition.project_id}")

            elif transition.transition_type == "global_pause":
                projects = uow.projects.list_all() if hasattr(uow.projects, "list_all") else []
                for p_item in projects:
                    pol = dict(p_item.execution_policy or {})
                    pol["global_pause"] = True
                    p_item.execution_policy = pol
                    p_item.updated_at = now
                    uow.projects.save(p_item)
                transition.status = "APPLIED"
                transition.applied_at = now
                uow.deferred_transitions.save(transition)
                applied.append("global_pause")

        if applied and hasattr(uow, "commit"):
            uow.commit()
        return applied

    @staticmethod
    def _admit_next_fifo_request(
        *,
        uow: PersistenceUnitOfWork,
        project_id: str,
        repository: str,
        completed_run_id: str,
        next_request: dict[str, Any] | None,
    ) -> OrchestrationRun | None:
        """Persist the next FIFO admission without dispatching an agent."""
        if not next_request or next_request.get("re_entrant"):
            return None
        issue_number = next_request.get("issue_number")
        issue_title = str(next_request.get("title") or "change")
        if not isinstance(issue_number, int) or issue_number < 1:
            return None
        try:
            change_name = WorktreeManager.resolve_request_change_name(
                issue_number, issue_title, str(next_request.get("body") or "")
            )
        except ValueError as exc:
            logger.warning("Next FIFO request has an invalid Change reservation: %s", exc)
            return None
        runs = getattr(uow, "orchestration_runs", None)
        if runs is None:
            raise RuntimeError("Durable orchestration run repository is unavailable.")
        existing = (
            runs.get_active_run(project_id, change_name)
            if hasattr(runs, "get_active_run")
            else None
        )
        if existing:
            return existing
        admitted = OrchestrationRun(
            project_id=project_id,
            change_name=change_name,
            base_sha="main",
            current_stage=OrchestrationStage.ADMITTED,
            resumable_stage=OrchestrationStage.ADMITTED,
            stop_details={
                "issue_number": issue_number,
                "issue_title": issue_title,
                "repository": repository,
                "fifo_parent_run_id": completed_run_id,
                "admission_only": True,
            },
        )
        runs.save(admitted)
        if hasattr(uow, "commit"):
            uow.commit()
        return admitted

    async def _confirm_pr_merged(self, repository: str, pr_number: int, candidate_sha: str) -> bool:
        """Re-read the remote PR; a merge request response alone is not proof."""
        getter = getattr(self.github_adapter, "get_pull_request_details", None)
        if not getter:
            return False
        result = getter(repository=repository, pr_number=pr_number)
        result = await result if inspect.isawaitable(result) else result
        if not self._external_success(result):
            return False
        data = result.data if hasattr(result, "data") else result
        if not isinstance(data, dict):
            return False
        return (
            bool(data.get("is_merged") or data.get("merged"))
            and data.get("merge_commit_sha") is not None
            and (not data.get("head_sha") or data.get("head_sha") == candidate_sha)
        )

    async def _confirm_pr_open(
        self,
        repository: str,
        pr_number: int,
        head_branch: str,
        base_branch: str,
        candidate_sha: str,
    ) -> bool:
        getter = getattr(self.github_adapter, "get_pull_request_details", None)
        if not getter:
            return False
        result = getter(repository=repository, pr_number=pr_number)
        result = await result if inspect.isawaitable(result) else result
        if not self._external_success(result):
            return False
        data = result.data if hasattr(result, "data") else result
        return (
            isinstance(data, dict)
            and data.get("state") == "open"
            and data.get("head_sha") == candidate_sha
            and (data.get("head_branch") == head_branch and data.get("base_branch") == base_branch)
        )

    async def _confirm_issue_closed(self, repository: str, issue_number: int) -> bool:
        getter = getattr(self.github_adapter, "get_issue", None)
        if not getter:
            return False
        result = getter(repository=repository, issue_number=issue_number)
        result = await result if inspect.isawaitable(result) else result
        if not self._external_success(result):
            return False
        data = result.data if hasattr(result, "data") else result
        return isinstance(data, dict) and str(data.get("state", "")).lower() == "closed"

    def _update_stage(self, uow: Any, run: OrchestrationRun, stage: OrchestrationStage) -> None:
        run.current_stage = stage
        run.resumable_stage = stage
        run.updated_at = utc_now()
        if hasattr(uow, "orchestration_runs"):
            uow.orchestration_runs.save(run)
            if hasattr(uow, "commit"):
                uow.commit()

    def _review_round(
        self,
        uow: Any,
        project_id: str,
        run: OrchestrationRun,
        review_key: str = "code_review",
    ) -> tuple[int, int]:
        """Return (current_review_round, max_review_rounds) from durable run state.

        The round counter is persisted in stop_details so a scheduler re-entry
        cannot silently reset the escalation ladder and loop forever. The ceiling
        comes from the project's persisted execution_policy.
        """
        details = dict(run.stop_details or {})
        round_num = 0
        review_state = details.get(review_key)
        if isinstance(review_state, dict) and isinstance(review_state.get("round"), int):
            round_num = review_state["round"]
        max_rounds = 2
        if hasattr(uow, "projects"):
            proj = uow.projects.get_by_id(project_id)
            policy = getattr(proj, "execution_policy", {}) or {}
            if isinstance(policy, dict):
                candidate = policy.get("max_review_rounds")
                if isinstance(candidate, int) and candidate >= 1:
                    max_rounds = min(candidate, 2)
        return round_num, max_rounds

    def _apply_attempts(self, run: OrchestrationRun) -> int:
        """Return the durable count of consecutive Apply failures for this run."""
        details = dict(run.stop_details or {})
        attempts = details.get("apply_failure_count")
        return attempts if isinstance(attempts, int) and attempts >= 0 else 0

    _UNCHECKED_TASK_RE = re.compile(r"(?m)^\s*-\s*\[\s\]\s+([^\n]*)$")

    @staticmethod
    def _classify_pending_tasks(tasks_text: str) -> tuple[list[str], list[str]]:
        """Split unchecked tasks.md boxes into (automated_pending, not_verified) ids.

        A task whose line carries the ``NOT_VERIFIED`` marker needs evidence only a
        human can produce (physical devices, manual scenarios). Those must never gate
        or retry Apply — they are escalated to the operator instead of re-dispatching
        an agent that can never satisfy them.
        """
        automated_pending: list[str] = []
        not_verified: list[str] = []
        for match in NativeOrchestrationCoordinator._UNCHECKED_TASK_RE.finditer(tasks_text):
            line = match.group(1).strip()
            task_id = line.split()[0] if line else "?"
            if "NOT_VERIFIED" in line.upper():
                not_verified.append(task_id)
            else:
                automated_pending.append(task_id)
        return automated_pending, not_verified

    def _record_apply_failure(self, uow: Any, run: OrchestrationRun) -> int:
        """Increment the durable Apply-failure counter and return the new value."""
        details = dict(run.stop_details or {})
        next_count = self._apply_attempts(run) + 1
        details["apply_failure_count"] = next_count
        run.stop_details = details
        if hasattr(uow, "orchestration_runs"):
            uow.orchestration_runs.save(run)
            if hasattr(uow, "commit"):
                uow.commit()
        return next_count

    @staticmethod
    def _apply_snapshot(outcome: ApplyOutcome) -> dict[str, Any]:
        return {"pending": list(outcome.pending_tasks), "completed": list(outcome.completed_tasks),
                "sha": outcome.candidate_sha, "files": list(outcome.changed_files),
                "fingerprint": outcome.diff_fingerprint, "tests_passed": outcome.tests_passed,
                "test_evidence": outcome.test_evidence, "branch": outcome.branch,
                "worktree": outcome.worktree, "run_id": outcome.run_id}

    @staticmethod
    def _apply_made_progress(previous: dict[str, Any], current: ApplyOutcome) -> bool:
        return (len(current.pending_tasks) < len(previous.get("pending", [])) or
                (current.diff_fingerprint is not None and current.changed_files and
                 current.diff_fingerprint != previous.get("fingerprint")))

    @staticmethod
    def _apply_regressed(previous: dict[str, Any], current: ApplyOutcome) -> bool:
        identity_changed = any((previous.get(key) and value and previous[key] != value)
                               for key, value in (("branch", current.branch),
                                                  ("worktree", current.worktree),
                                                  ("run_id", current.run_id)))
        files_removed = set(previous.get("files", ())) - set(current.changed_files)
        tasks_lost = set(previous.get("completed", ())) - set(current.completed_tasks)
        tests_regressed = previous.get("tests_passed") is True and current.tests_passed is False
        return identity_changed or bool(files_removed or tasks_lost or tests_regressed)

    @staticmethod
    def _positive_policy_limit(policy: Any, key: str, default: int) -> int:
        value = policy.get(key) if isinstance(policy, dict) else None
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            return min(value, 10)
        return default

    @staticmethod
    def _apply_recovery_context(previous: dict[str, Any] | None) -> str:
        if not previous:
            return ""
        return ("\n\nApply recovery context (observed by coordinator):\n"
                f"Completed tasks: {previous.get('completed', [])}\n"
                f"Pending tasks: {previous.get('pending', [])}\n"
                f"Git changed files: {previous.get('files', [])}\n"
                f"Candidate SHA: {previous.get('sha')}\n"
                f"Prior test result: {previous.get('tests_passed')}\n"
                f"Prior test evidence: {previous.get('test_evidence', '')[-3000:]}\n"
                "Inspect and preserve valid existing work. Mark [x] only tasks supported by observed diff and passing relevant tests. "
                "Do not redo or discard valid work. This recovery context is separate from reviewer corrections.")

    def _escalate_apply_to_human(
        self,
        uow: Any,
        run: OrchestrationRun,
        reason: str,
        *,
        gate: str = "apply_escalation",
        options: list[Any] | tuple[Any, ...] | None = None,
        attempts: int | None = None,
        hard_limit: int | None = None,
        no_progress: int | None = None,
        outcome: Any = None,
        worktree_path: Path | None = None,
        change_name: str | None = None,
    ) -> OrchestrationCoordinationResult:
        """Mark the run for human attention so the scheduler stops re-dispatching."""
        details = dict(run.stop_details or {})
        details["apply_escalated"] = True

        att_count = attempts if attempts is not None else details.get("apply_total_attempts", 0)
        ceiling = hard_limit if hard_limit is not None else 3
        no_prog = no_progress if no_progress is not None else details.get("apply_no_progress", 0)

        pending_tasks: list[str] = []
        if outcome and getattr(outcome, "pending_tasks", None):
            pending_tasks = list(outcome.pending_tasks)
        elif worktree_path and change_name:
            tasks_path = Path(worktree_path) / "openspec" / "changes" / change_name / "tasks.md"
            if tasks_path.exists():
                automated, not_ver = self._classify_pending_tasks(tasks_path.read_text(errors="ignore"))
                pending_tasks = automated + not_ver

        candidate_sha = (
            getattr(outcome, "candidate_sha", None)
            or run.current_candidate_sha
            or "No generado"
        )
        tests_passed = getattr(outcome, "tests_passed", None) if outcome else None
        test_evidence = getattr(outcome, "test_evidence", "") if outcome else ""

        pending_str = ", ".join(pending_tasks) if pending_tasks else "Ver tasks.md"
        test_str = "Aprobadas" if tests_passed else "No aprobadas" if tests_passed is False else "Sin ejecutar"

        explanation_es = (
            f"La implementación automática (Apply) se detuvo tras alcanzar el límite de recuperación "
            f"({att_count}/{ceiling} intentos, {no_prog} sin progreso). "
            f"Tareas pendientes: {pending_str}. "
            f"Estado de pruebas: {test_str}. "
            f"Candidate SHA: {candidate_sha}. "
            f"Se requiere la intervención del operador para revisar el estado del candidato y decidir cómo proceder."
        )

        question = reason
        if options is not None:
            opts = list(options)
        elif gate == "apply_escalation" and (attempts is not None or hard_limit is not None):
            opts = [
                {"id": "retry", "label": "Reintentar implementación (Apply)"},
                {"id": "cancel", "label": "Cancelar run y preservar worktree"},
            ]
        else:
            opts = []

        diagnostic_payload = {
            "attempts": att_count,
            "hard_limit": ceiling,
            "no_progress": no_prog,
            "pending_tasks": pending_tasks,
            "candidate_sha": candidate_sha,
            "tests_passed": tests_passed,
            "logs_available": bool(test_evidence),
            "explanation_es": explanation_es,
            "raw_reason": reason,
        }

        run.stop_details = details
        payload = self._record_current_human_gate(
            uow,
            run,
            gate=gate,
            question=question,
            options=opts,
            payload=diagnostic_payload,
        )
        return OrchestrationCoordinationResult(
            status="HUMAN_REQUIRED",
            run_id=run.run_id,
            current_stage=OrchestrationStage.IMPLEMENTING,
            message=question,
            human_payload=payload,
        )

    def _route_changes_required(
        self,
        uow: Any,
        project_id: str,
        run: OrchestrationRun,
        result: dict[str, Any],
    ) -> OrchestrationCoordinationResult:
        """Route a CHANGES_REQUIRED code-review outcome.

        With actionable findings and rounds remaining, this persists the next
        round and rewinds to IMPLEMENTING so the executor consumes the findings
        and re-enters Verify/review automatically. It escalates to the operator
        (PAUSED) only when the round limit is exhausted or no findings exist.
        """
        findings = result.get("findings") or []
        round_num, max_rounds = self._review_round(uow, project_id, run)
        if findings and round_num < max_rounds:
            details = dict(run.stop_details or {})
            review_state = dict(details.get("code_review") or {})
            review_state["round"] = round_num + 1
            details["code_review"] = review_state
            details["pending_corrections"] = findings
            run.stop_details = details
            if hasattr(uow, "orchestration_runs"):
                uow.orchestration_runs.save(run)
                if hasattr(uow, "commit"):
                    uow.commit()
            self._update_stage(uow, run, OrchestrationStage.IMPLEMENTING)
            return OrchestrationCoordinationResult(
                status="RUNNING",
                run_id=run.run_id,
                current_stage=OrchestrationStage.IMPLEMENTING,
                message=(
                    f"Independent review requested changes (round {round_num + 1}/{max_rounds}); "
                    "dispatching corrections to the implementer automatically."
                ),
            )
        return OrchestrationCoordinationResult(
            status="PAUSED",
            run_id=run.run_id,
            current_stage=OrchestrationStage.CODE_REVIEW,
            message=self._review_pause_message("code", result)
            + ("" if findings else " No actionable findings were returned."),
            human_payload=self._record_current_human_gate(
                uow,
                run,
                gate="code_review_escalation",
                question=(
                    self._review_pause_message("code", result)
                    + ("" if findings else " No actionable findings were returned.")
                ),
                options=result.get("options") or (),
            ),
        )

    @staticmethod
    def _execution_is_successful(result: Any) -> bool:
        """Only an explicit, evidenced, zero-exit execution can advance a stage."""
        if result is None or getattr(result, "exit_code", None) != 0:
            return False
        if getattr(result, "workflow_handoff_required", False):
            report = getattr(result, "workflow_handoff", None)
            if report is None or getattr(report, "status", None) != "COMPLETE":
                return False
        if getattr(result, "timed_out", False) or getattr(result, "preflight_error", None):
            return False
        if getattr(result, "environment_error", False):
            return False
        # Diagnostic output may be abbreviated for display. The authoritative
        # provider response is checked separately through final_response_status.
        if getattr(result, "structured_output_missing", False) or getattr(
            result, "structured_output_too_large", False
        ):
            return False
        if getattr(result, "final_response_status", None) not in (None, "COMPLETE"):
            return False
        return bool(getattr(result, "response_output", "").strip())

    @staticmethod
    def _proposal_artifacts_present(worktree_path: Path, change_name: str) -> bool:
        """Confirm a complete existing proposal before resuming VALIDATING."""
        change_dir = worktree_path / "openspec" / "changes" / change_name
        required = (change_dir / "proposal.md", change_dir / "design.md", change_dir / "tasks.md")
        specs_dir = change_dir / "specs"
        return (
            all(path.is_file() for path in required)
            and specs_dir.is_dir()
            and any(path.is_file() and path.suffix == ".md" for path in specs_dir.rglob("*.md"))
        )

    @staticmethod
    def _proposal_artifacts_any(worktree_path: Path, change_name: str) -> bool:
        change_dir = worktree_path / "openspec" / "changes" / change_name
        return change_dir.is_dir() and any(
            path.is_file() and path.suffix == ".md" for path in change_dir.rglob("*.md")
        )

    @staticmethod
    def _proposal_artifact_hashes(worktree_path: Path, change_name: str) -> dict[str, str]:
        change_dir = worktree_path / "openspec" / "changes" / change_name
        paths = (
            [path for path in change_dir.rglob("*") if path.is_file() and path.suffix == ".md"]
            if change_dir.is_dir()
            else []
        )
        return {
            str(path.relative_to(worktree_path)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(paths)
        }

    def _prepare_native_dispatch(
        self,
        *,
        uow: Any,
        run: OrchestrationRun,
        issue_number: int,
        provider: str,
        operation: str,
        action_type: ExternalActionType,
        target_identity: str,
        request_fingerprint: str,
        is_recovery: bool,
        recovery_authorization_id: str | None,
        attempt_fields: dict[str, Any],
    ) -> tuple[str, str, RecoveryClaimContext] | None:
        """Persist one native dispatch intent and its fenced claim before I/O."""
        actions = getattr(uow, "orchestration_external_actions", None)
        claims = getattr(uow, "claims", None)
        if actions is None or claims is None:
            return None

        attempt_id = str(uuid4())
        action_key = f"{operation}:{run.run_id}:{attempt_id}"
        details = dict(run.stop_details or {})
        previous_attempt = details.get(f"{operation}_attempt") or {}
        details[f"{operation}_attempt"] = {
            "attempt_id": attempt_id,
            "status": "IN_PROGRESS",
            "provider": provider,
            "issue_number": issue_number,
            "action_key": action_key,
            "recovery": is_recovery,
            "recorded_at": utc_now().isoformat(),
            **attempt_fields,
        }
        claim = claims.acquire_or_reacquire(
            claim_key=f"run:{run.run_id}",
            owner_instance_id=f"{operation}:{uuid4()}",
            lease_seconds=90,
        )
        if claim is None:
            return None
        claim_context = RecoveryClaimContext(
            claim_key=claim.claim_key,
            owner_instance_id=claim.owner_instance_id,
            fence_token=claim.fence_token,
            lease_expires_at=claim.lease_expires_at,
        )
        try:
            run.stop_details = details
            uow.orchestration_runs.save(run)
            actions.reserve(
                OrchestrationExternalAction(
                    run_id=run.run_id,
                    action_key=action_key,
                    action_type=action_type,
                    target_identity=target_identity,
                    request_fingerprint=request_fingerprint,
                    generation=run.current_generation,
                    status=ExternalActionStatus.RESERVED,
                )
            )
            uow.flush()
            if is_recovery:
                if not recovery_authorization_id:
                    raise ValueError(f"{operation.title()} recovery authorization is required")
                operator_actions = getattr(uow, "operator_actions", None)
                if operator_actions is None:
                    raise ValueError("Operator action repository is unavailable")
                consumed = operator_actions.consume_single_use(
                    recovery_authorization_id,
                    run_id=run.run_id,
                    action_type=OperatorActionType.RETRY,
                    expected_parameters={
                        "single_use": True,
                        "stage": operation,
                        "issue_number": issue_number,
                        "provider": provider,
                        "prior_attempt_id": previous_attempt.get("attempt_id"),
                        **(
                            {
                                "legacy_missing_attempt": not bool(previous_attempt),
                                "prior_context_sha256": previous_attempt.get("context_sha256"),
                                "prior_workflow_sha256": previous_attempt.get("workflow_sha256"),
                            }
                            if operation == "explore"
                            else {}
                        ),
                        **(
                            {"change_name": attempt_fields.get("change_name")}
                            if operation == "propose"
                            else {}
                        ),
                    },
                )
                if consumed is None:
                    raise ValueError(
                        f"{operation.title()} recovery authorization is missing, mismatched, or consumed"
                    )
            claims.commit_fenced_dispatch_intent(
                claim_key=claim_context.claim_key,
                owner_instance_id=claim_context.owner_instance_id,
                fence_token=claim_context.fence_token,
                action_key=action_key,
                authorization=DispatchAuthorization(
                    action_key=action_key,
                    is_authorized=True,
                    authorization_reason=(
                        f"Explicit operator authorization for {operation} recovery."
                        if is_recovery
                        else f"Original {operation.title()} dispatch for this Run."
                    ),
                    is_retry=is_recovery,
                ),
            )
        except Exception as exc:
            logger.warning("%s dispatch preparation failed: %s", operation.title(), exc)
            uow.rollback()
            claims.release_claim(claim_context)
            uow.commit()
            return None
        return attempt_id, action_key, claim_context

    def _finish_native_dispatch(
        self,
        uow: Any,
        run: OrchestrationRun,
        operation: str,
        attempt_id: str,
        action_key: str,
        claim_context: RecoveryClaimContext,
        attempt_status: str,
        error_message: str | None,
    ) -> None:
        """Close one observed native result; crashes remain in-progress/ambiguous."""
        validate = getattr(uow.claims, "validate_cas", None)
        if callable(validate) and not validate(
            claim_context.claim_key, claim_context.owner_instance_id, claim_context.fence_token
        ):
            uow.orchestration_external_actions.update_status(
                action_key=action_key,
                status=ExternalActionStatus.AMBIGUOUS,
                error_message="Dispatch claim was fenced before result persistence.",
            )
            uow.commit()
            raise RuntimeError("Dispatch result rejected because its recovery claim was fenced")
        details = dict(run.stop_details or {})
        attempt = dict(details.get(f"{operation}_attempt") or {})
        if attempt.get("attempt_id") == attempt_id:
            attempt.update(status=attempt_status, finished_at=utc_now().isoformat())
            if error_message:
                attempt["error"] = redact_secrets(error_message)[:1000]
            details[f"{operation}_attempt"] = attempt
            run.stop_details = details
            uow.orchestration_runs.save(run)
        status = {
            "COMPLETE": ExternalActionStatus.COMPLETED,
            "FAILED": ExternalActionStatus.FAILED,
            "AMBIGUOUS": ExternalActionStatus.AMBIGUOUS,
        }.get(attempt_status, ExternalActionStatus.UNKNOWN)
        try:
            uow.orchestration_external_actions.update_status(
                action_key=action_key,
                status=status,
                error_message=redact_secrets(error_message)[:1000] if error_message else None,
            )
            uow.commit()
        finally:
            uow.claims.release_claim(claim_context)
            uow.commit()

    @staticmethod
    def _profile_key_for_role(role: str) -> str:
        """Resolve a semantic role to its persisted profile key.

        ``reviewer`` is the coordinator's semantic role; the persisted F2 key is
        ``independent_review``. Centralizing the mapping keeps provider and model
        resolution consistent everywhere instead of patching each caller.
        """
        return _ROLE_TO_PROFILE_KEY.get(role, role)

    @staticmethod
    def _configured_provider(project: Any, role: str) -> str | None:
        profiles = getattr(project, "agent_profiles", {}) if project else {}
        raw = (
            profiles.get(_ROLE_TO_PROFILE_KEY.get(role, role))
            if isinstance(profiles, dict)
            else None
        )
        if hasattr(raw, "model_dump"):
            raw = raw.model_dump()
        return str(raw.get("agent_id") or "").strip().lower() if isinstance(raw, dict) else None

    @classmethod
    def _configured_model(cls, uow: Any, project_id: str, role: str) -> str | None:
        project = uow.projects.get_by_id(project_id) if hasattr(uow, "projects") else None
        profiles = getattr(project, "agent_profiles", {}) if project else {}
        raw = (
            profiles.get(_ROLE_TO_PROFILE_KEY.get(role, role))
            if isinstance(profiles, dict)
            else None
        )
        if hasattr(raw, "model_dump"):
            raw = raw.model_dump()
        return str(raw.get("model_id") or "").strip() or None if isinstance(raw, dict) else None

    @staticmethod
    def _classification_context_hashes(
        run: OrchestrationRun,
        issue_number: int | None,
        issue_title: str,
        issue_body: str,
    ) -> dict[str, str]:
        issue_payload = json.dumps(
            {"number": issue_number, "title": issue_title, "body": issue_body},
            sort_keys=True,
            separators=(",", ":"),
        )
        run_payload = json.dumps(
            {
                "run_id": run.run_id,
                "project_id": run.project_id,
                "change_name": run.change_name,
                "base_sha": run.base_sha,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return {
            "issue": hashlib.sha256(issue_payload.encode()).hexdigest(),
            "run": hashlib.sha256(run_payload.encode()).hexdigest(),
        }

    @staticmethod
    def _stored_complexity_assessment(
        run: OrchestrationRun,
        artifact_hashes: dict[str, str] | None = None,
        context_hashes: dict[str, str] | None = None,
    ) -> ComplexityAssessment | None:
        payload = (run.stop_details or {}).get("complexity_assessment")
        if not isinstance(payload, dict) or payload.get("status") != "VALID":
            return None
        if artifact_hashes is not None and payload.get("artifact_hashes") != artifact_hashes:
            return None
        if context_hashes is not None and payload.get("context_hashes") != context_hashes:
            return None
        return ComplexityAssessment(
            status=str(payload.get("status")),
            complexity=payload.get("complexity"),
            evidence=payload.get("evidence"),
            reason=payload.get("reason"),
            exit_code=payload.get("exit_code"),
            timed_out=bool(payload.get("timed_out")),
            preflight_error=payload.get("preflight_error"),
            output=payload.get("output", ""),
            structured_output=payload.get("structured_output", ""),
            diagnostic_output=payload.get("diagnostic_output", ""),
            output_truncated=bool(payload.get("output_truncated")),
            structured_output_missing=bool(payload.get("structured_output_missing")),
            structured_output_too_large=bool(payload.get("structured_output_too_large")),
        )

    @staticmethod
    def _persist_complexity_assessment(
        run: OrchestrationRun,
        assessment: ComplexityAssessment,
        *,
        attempt_id: str,
        model_identity: str | None,
        artifact_hashes: dict[str, str],
        context_hashes: dict[str, str] | None = None,
    ) -> None:
        payload = {
            "status": assessment.status,
            "complexity": assessment.complexity,
            "evidence": assessment.evidence,
            "reason": assessment.reason,
            "exit_code": assessment.exit_code,
            "timed_out": assessment.timed_out,
            "preflight_error": assessment.preflight_error,
            "output": assessment.output,
            "attempt_id": attempt_id,
            "model_identity": model_identity,
            "artifact_hashes": artifact_hashes,
            "consumption": "unknown",
            "context_hashes": context_hashes,
            "structured_output": assessment.structured_output,
            "diagnostic_output": assessment.diagnostic_output,
            "output_truncated": assessment.output_truncated,
            "structured_output_missing": assessment.structured_output_missing,
            "structured_output_too_large": assessment.structured_output_too_large,
        }
        details = dict(run.stop_details or {})
        attempts = list(details.get("complexity_attempts") or [])
        attempts.append(payload)
        details["complexity_attempts"] = attempts
        details["complexity_assessment"] = payload
        run.stop_details = details

    @staticmethod
    def _external_success(result: Any) -> bool:
        if result is None:
            return False
        if isinstance(result, dict):
            return bool(result.get("success") or result.get("merged"))
        return getattr(result, "outcome", None) == ExternalOutcome.SUCCESS and bool(
            getattr(result, "data", None) is not None
        )

    @staticmethod
    def _parse_json_object(raw: str) -> dict[str, Any] | None:
        """Parse exactly one JSON object; reject prose, multiple objects, and ambiguity."""
        text = raw.strip()
        fenced = re.fullmatch(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
        candidate = fenced.group(1).strip() if fenced else text
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError:
            return None
        return value if isinstance(value, dict) else None

    async def _prepare_semantic_pr_content(
        self,
        *,
        worktree_path: Path,
        provider: str,
        project_id: str,
        run_id: str,
        pr_input: PrPreparationInput,
        request_body: str,
    ) -> tuple[str, str]:
        """Ask the configured agent for PR prose; never manufacture success prose."""
        workflow = self.agent_runner.resolve_workflow(
            worktree_path=worktree_path,
            provider=provider,
            operation="pr_prepare",
            change_name=pr_input.change_name,
        )
        response_path = worktree_path / ".minime" / f"pr-preparer-{pr_input.pr_type}-{run_id}.json"
        result = await self.agent_runner.run(
            worktree_path=worktree_path,
            prompt_context=(
                "Use the installed minime-pr-preparer skill. Return exactly one JSON object with "
                "title and body strings. Draft semantic content from the Request and verified evidence; "
                "do not invent tests, merges, capabilities, or decisions and never emit auto-closing directives.\n"
                f"Input: {json.dumps({**pr_input.__dict__, 'request_body': request_body}, ensure_ascii=False, default=str)}"
            ),
            project_id=project_id,
            role="thinker",
            provider=provider,
            workflow=workflow,
            output_schema={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "minLength": 1},
                    "body": {"type": "string", "minLength": 1},
                },
                "required": ["title", "body"],
                "additionalProperties": False,
            },
            output_last_message_path=response_path,
        )
        if (
            result.exit_code != 0
            or result.timed_out
            or result.preflight_error
            or result.structured_output_missing
            or result.structured_output_too_large
        ):
            raise ValueError("PR semantic agent did not produce verified content")
        payload = self._parse_json_object(result.response_output)
        if (
            not payload
            or not isinstance(payload.get("title"), str)
            or not isinstance(payload.get("body"), str)
        ):
            raise ValueError(
                "PR semantic agent response was not a single structured title/body object"
            )
        title = payload["title"].strip()
        body = payload["body"].strip()
        if not title or not body:
            raise ValueError("PR semantic agent returned empty content")
        return title, body

    @classmethod
    def _recover_persisted_complexity(cls, payload: dict[str, Any]) -> ComplexityAssessment | None:
        """Recover only an explicitly separated, complete provider response."""
        if (
            payload.get("exit_code") != 0
            or payload.get("structured_output_missing")
            or payload.get("structured_output_too_large")
            or not isinstance(payload.get("attempt_id"), str)
            or not payload.get("attempt_id")
            or not isinstance(payload.get("artifact_hashes"), dict)
            or not isinstance(payload.get("context_hashes"), dict)
        ):
            return None
        structured = payload.get("structured_output")
        diagnostics = payload.get("diagnostic_output")
        if not isinstance(structured, str) or not isinstance(diagnostics, str):
            return None
        parsed = cls._parse_json_object(structured)
        if not parsed or parsed.get("complexity") not in {"low", "moderate", "high"}:
            return None
        evidence = parsed.get("evidence")
        if not isinstance(evidence, str) or not evidence.strip():
            return None
        return ComplexityAssessment(
            status="VALID",
            complexity=parsed["complexity"],
            evidence=redact_secrets(evidence.strip())[:1000],
            reason="Recovered from the original separated response channel.",
            exit_code=0,
            output=redact_secrets(payload.get("output", ""))[:4000],
            structured_output=redact_secrets(structured),
            diagnostic_output=redact_secrets(diagnostics)[:4000],
        )

    async def _assess_complexity(
        self,
        worktree_path: Path,
        provider: str,
        title: str,
        body: str,
        project_id: str | None,
        attempt_id: str | None = None,
    ) -> ComplexityAssessment:
        wf = self.agent_runner.resolve_workflow(
            worktree_path=worktree_path,
            provider=provider,
            operation="propose",
            change_name="complexity-assessment",
        )
        response_path = (
            worktree_path / ".minime" / "classification-attempts" / attempt_id / "last-message.json"
            if attempt_id
            else None
        )
        result = await self.agent_runner.run(
            worktree_path=worktree_path,
            prompt_context=(
                "Assess this Request's implementation complexity using the configured thinking agent. "
                'Return exactly one JSON object: {"complexity": "low|moderate|high", '
                '"evidence": "brief concrete rationale"}. Do not infer from keywords alone.\n'
                f"Title: {title}\nBody:\n{body}"
            ),
            project_id=project_id,
            role="thinker",
            provider=provider,
            workflow=wf,
            output_schema={
                "type": "object",
                "properties": {
                    "complexity": {"type": "string", "enum": ["low", "moderate", "high"]},
                    "evidence": {"type": "string", "minLength": 1},
                },
                "required": ["complexity", "evidence"],
                "additionalProperties": False,
            }
            if response_path
            else None,
            output_last_message_path=response_path,
        )
        output = redact_secrets(getattr(result, "full_output", ""))[:4000]
        structured_output_raw = getattr(result, "response_output", "")
        structured_output = redact_secrets(structured_output_raw)
        diagnostic_output = redact_secrets(
            "\n".join(getattr(result, "diagnostic_output", None) or getattr(result, "stderr", []))
        )[:4000]
        output_truncated = bool(getattr(result, "output_truncated", False))
        structured_output_missing = bool(getattr(result, "structured_output_missing", False))
        structured_output_too_large = bool(getattr(result, "structured_output_too_large", False))
        if getattr(result, "preflight_error", None):
            return ComplexityAssessment(
                status="PREFLIGHT_FAILED",
                reason="agent preflight failed",
                exit_code=getattr(result, "exit_code", None),
                timed_out=bool(getattr(result, "timed_out", False)),
                preflight_error=redact_secrets(result.preflight_error),
                output=output,
                structured_output=structured_output,
                diagnostic_output=diagnostic_output,
                output_truncated=output_truncated,
                structured_output_missing=structured_output_missing,
            )
        if not self._execution_is_successful(result):
            return ComplexityAssessment(
                status="EXECUTION_FAILED",
                reason="agent exit, timeout, environment, or evidence check failed",
                exit_code=getattr(result, "exit_code", None),
                timed_out=bool(getattr(result, "timed_out", False)),
                output=output,
                structured_output=structured_output,
                diagnostic_output=diagnostic_output,
                output_truncated=output_truncated,
                structured_output_missing=structured_output_missing,
            )
        if structured_output_missing or structured_output_too_large:
            return ComplexityAssessment(
                status="MISSING_EVIDENCE",
                reason=(
                    "provider structured response exceeded its safe size limit"
                    if structured_output_too_large
                    else "provider did not produce the authorized last-message file"
                ),
                exit_code=result.exit_code,
                output=output,
                structured_output=structured_output,
                diagnostic_output=diagnostic_output,
                output_truncated=output_truncated,
                structured_output_missing=structured_output_missing,
            )
        payload = self._parse_json_object(structured_output_raw)
        if not payload or payload.get("complexity") not in {"low", "moderate", "high"}:
            return ComplexityAssessment(
                status="INVALID_OUTPUT",
                reason="exactly one structured complexity object was not returned",
                exit_code=result.exit_code,
                output=output,
                structured_output=structured_output,
                diagnostic_output=diagnostic_output,
            )
        if not isinstance(payload.get("evidence"), str) or not payload["evidence"].strip():
            return ComplexityAssessment(
                status="MISSING_EVIDENCE",
                reason="structured complexity verdict has no concrete evidence",
                exit_code=result.exit_code,
                output=output,
                structured_output=structured_output,
                diagnostic_output=diagnostic_output,
            )
        return ComplexityAssessment(
            status="VALID",
            complexity=payload["complexity"],
            evidence=redact_secrets(payload["evidence"].strip())[:1000],
            exit_code=result.exit_code,
            output=output,
            structured_output=structured_output,
            diagnostic_output=diagnostic_output,
        )

    async def _run_explore(
        self,
        worktree_path: Path,
        provider: str,
        issue_number: int,
        issue_title: str,
        issue_body: str,
        operator_clarification: str | None = None,
        project_id: str | None = None,
        process_start_observer: Any = None,
    ) -> dict[str, Any]:
        """Execute official OpenSpec Explore workflow with configured thinking agent."""
        wf = self.agent_runner.resolve_workflow(
            worktree_path=worktree_path,
            provider=provider,
            operation="explore",
            change_name=f"issue-{issue_number}",
        )
        prompt = (
            f"You are the thinking agent for mini me. Execute official OpenSpec Explore for Request #{issue_number}.\n\n"
            f"Command: {wf.dispatch_command}\n"
            f"Issue Title: {issue_title}\n"
            f"Issue Body:\n{issue_body}\n"
        )
        if operator_clarification:
            prompt += f"\nOperator Clarification Provided:\n{operator_clarification}\n"
        prompt += (
            "\nIn your final response use exactly one standalone disposition line: "
            "READY_TO_PROPOSE if no material questions remain, or HUMAN REQUIRED "
            "if an unresolved decision genuinely blocks Propose. For HUMAN REQUIRED "
            "include concrete bullet-point options after that line. Mentions of "
            "historical gates must not be presented as disposition lines.\n"
        )

        res = await self.agent_runner.run(
            worktree_path=worktree_path,
            prompt_context=prompt,
            project_id=project_id,
            role="thinker",
            provider=provider,
            workflow=wf,
            process_start_observer=process_start_observer,
        )

        if not self._execution_is_successful(res):
            return {
                "status": "FAILED",
                "message": "Explore failed or has no complete authoritative final response.",
            }

        # Interpret ONLY explicit, standalone dispositions from the provider's
        # response channel. Broad substring searches across stdout/stderr
        # misclassify READY_TO_PROPOSE when prior HUMAN REQUIRED gates are quoted.
        output = self._explore_final_message(res.response_output)
        disposition, marker_line = self._explore_disposition(output)
        if disposition is None:
            return {
                "status": "FAILED",
                "message": "Explore verdict missing or ambiguous; Propose is blocked.",
            }
        if disposition == "HUMAN_REQUIRED":
            lines = output.splitlines()
            options = [
                line.strip().lstrip("-• ").strip()[:500]
                for line in lines[marker_line + 1 :]
                if line.strip().startswith(("- ", "• "))
            ][:20]
            if not options:
                return {
                    "status": "FAILED",
                    "message": "Explore requested human input without concrete options.",
                }
            return {
                "status": "HUMAN_REQUIRED",
                "human_payload": self._safe_human_payload(
                    {
                        "question": f"¿Cómo debe resolverse la ambigüedad en el Issue #{issue_number}?",
                        "options": options,
                        "agent_output": output[:1000],
                    }
                ),
                "execution": res,
            }
        return {"status": "READY_TO_PROPOSE", "execution": res}

    @staticmethod
    def _explore_final_message(provider_response: str) -> str:
        """Extract a Codex NDJSON agent message instead of parsing tool logs.

        The subscribed Codex exec CLI can emit event records containing
        tool output, quoted requests and progress. Only the last completed
        assistant message is its final Explore answer. Unrecognised event
        streams fail closed; plain-text Antigravity responses remain supported.
        """
        messages: list[str] = []
        event_stream = False
        completed_turn = False
        failed_turn = False
        for line in provider_response.splitlines():
            try:
                event = json.loads(line)
            except (TypeError, json.JSONDecodeError):
                continue
            if not isinstance(event, dict) or not isinstance(event.get("type"), str):
                continue
            if event["type"] in {
                "thread.started",
                "turn.started",
                "turn.completed",
                "turn.failed",
                "item.started",
                "item.updated",
                "item.completed",
            }:
                event_stream = True
            if event["type"] == "turn.completed":
                completed_turn = True
            if event["type"] == "turn.failed":
                failed_turn = True
            item = event.get("item")
            if (
                event.get("type") == "item.completed"
                and isinstance(item, dict)
                and item.get("type") == "agent_message"
                and isinstance(item.get("text"), str)
                and item["text"].strip()
            ):
                messages.append(item["text"])
        if event_stream:
            return messages[-1] if messages and completed_turn and not failed_turn else ""
        return provider_response

    @staticmethod
    def _explore_disposition(response: str) -> tuple[str | None, int]:
        """Require exactly one verdict marker, not incidental status mentions.

        Quoted instructions, tool diagnostics, code blocks and narrative about
        prior HUMAN REQUIRED gates are not valid new human checkpoints.
        Competing explicit markers fail closed rather than silently advancing.
        """
        pattern = re.compile(
            r"^(?:#{1,6}\s+)?(?:\*\*)?"
            r"(READY(?:_| )TO(?:_| )PROPOSE|HUMAN(?:_| )REQUIRED)"
            r"(?:\*\*)?(?:\s*[:—–-]\s*.+)?\s*$"
        )
        matches: list[tuple[str, int]] = []
        fenced = False
        for index, line in enumerate(response.splitlines()):
            stripped = line.strip()
            if stripped.startswith(("```", "~~~")):
                fenced = not fenced
                continue
            if fenced or stripped.startswith((">", "- ", "• ", "{", '"')):
                continue
            found = pattern.fullmatch(stripped)
            if found:
                status = found.group(1).replace(" ", "_")
                matches.append((status, index))
        return matches[0] if len(matches) == 1 else (None, -1)

    @staticmethod
    def _proposal_revision_prompt(revision: dict[str, Any] | None) -> str:
        """Format an operator-authorized proposal revision as a prompt fragment."""
        if not isinstance(revision, dict):
            return ""
        clarification = str(revision.get("clarification") or "").strip()
        findings = revision.get("findings") or []
        parts = ["Operator-authorized proposal revision."]
        if clarification:
            parts.append(f"Operator guidance: {clarification}")
        if findings:
            parts.append(
                "Prior independent-review findings to resolve: "
                + json.dumps(findings, ensure_ascii=False)
            )
        return "\n".join(parts)

    async def _run_propose(
        self,
        worktree_path: Path,
        provider: str,
        change_name: str,
        issue_number: int,
        issue_title: str,
        issue_body: str,
        project_id: str | None = None,
        continue_existing: bool = False,
        operator_clarification: str | None = None,
        process_start_observer: Any = None,
    ) -> dict[str, Any]:
        """Dispatch native Propose or native Continue for an incomplete proposal."""
        operation = "continue" if continue_existing else "propose"
        wf = self.agent_runner.resolve_workflow(
            worktree_path=worktree_path,
            provider=provider,
            operation=operation,
            change_name=change_name,
        )
        prompt = (
            f"Execute official OpenSpec {'Continue' if continue_existing else 'Propose'} for change '{change_name}'.\n"
            f"Workflow dispatch command: {wf.dispatch_command}\n\n"
            f"Remote Request #{issue_number}: {issue_title}\n"
            f"Description:\n{issue_body}\n"
            + (
                f"Continue the existing native change workflow and preserve every valid artifact under "
                f"openspec/changes/{change_name}/; complete only the missing canonical planning artifacts."
                if continue_existing
                else f"Generate canonical change planning artifacts under openspec/changes/{change_name}/: proposal.md, specs/, design.md, and tasks.md."
            )
        )
        if continue_existing and operator_clarification:
            prompt += f"\nOperator clarification for the pending native workflow:\n{operator_clarification}\n"
        res = await self.agent_runner.run(
            worktree_path=worktree_path,
            prompt_context=prompt,
            project_id=project_id,
            role="thinker",
            provider=provider,
            workflow=wf,
            process_start_observer=process_start_observer,
        )
        report = getattr(res, "workflow_handoff", None)
        if (
            getattr(res, "workflow_handoff_required", False)
            and report is not None
            and report.status != "COMPLETE"
            and getattr(res, "exit_code", None) == 0
            and not getattr(res, "timed_out", False)
            and not getattr(res, "preflight_error", None)
            and not getattr(res, "environment_error", False)
            and getattr(res, "final_response_status", None) == "COMPLETE"
        ):
            message = redact_secrets(
                f"Agent reported {report.status}: {report.summary}; "
                f"pending: {'; '.join(report.pending)}"
            )[:1000]
            if report.status == "HUMAN_REQUIRED":
                return {
                    "status": "HUMAN_REQUIRED",
                    "message": message,
                    "human_payload": self._safe_human_payload(
                        {
                            "question": report.pending[0],
                            "options": [],
                            "pending": list(report.pending),
                            "agent_output": report.summary,
                        }
                    ),
                    "execution": res,
                }
            return {"status": "INCOMPLETE", "message": message}
        if not self._execution_is_successful(res):
            return {
                "status": "FAILED",
                "message": "Propose agent execution was not successful or did not report a valid final handoff.",
            }
        planning = self.openspec_adapter.planning_status(change_name, worktree_path)
        if not isinstance(planning, dict):
            return {
                "status": "FAILED",
                "message": "OpenSpec planning status was not structured.",
            }
        if planning.get("status") != "PASS":
            pending = ", ".join(planning.get("pending") or [])
            return {
                "status": "INCOMPLETE" if planning.get("status") == "INCOMPLETE" else "FAILED",
                "message": redact_secrets(
                    f"OpenSpec planning is not complete: {planning.get('reason')}; pending: {pending}"
                )[:1000],
            }
        return {"status": "READY_TO_VALIDATE", "workflow": wf, "execution": res}

    async def _run_propose_correction(
        self,
        worktree_path: Path,
        provider: str,
        change_name: str,
        error_output: str,
        project_id: str | None = None,
        process_start_observer: Any = None,
    ) -> bool:
        """Run the native OpenSpec update workflow for review findings."""
        wf = self.agent_runner.resolve_workflow(
            worktree_path=worktree_path,
            provider=provider,
            operation="update",
            change_name=change_name,
        )
        prompt = (
            f"OpenSpec strict CLI validation failed for change '{change_name}'.\n"
            f"Errors reported:\n{error_output}\n\n"
            f"Use the native OpenSpec update workflow to correct only the planning artifacts under "
            f"openspec/changes/{change_name}/. Preserve valid decisions and keep the change within "
            f"its authorized scope. Then ensure the planning artifacts validate cleanly."
        )
        result = await self.agent_runner.run(
            worktree_path=worktree_path,
            prompt_context=prompt,
            project_id=project_id,
            role="thinker",
            provider=provider,
            workflow=wf,
            process_start_observer=process_start_observer,
        )
        return self._execution_is_successful(result)

    async def _route_proposal_changes_required(
        self,
        *,
        uow: Any,
        project_id: str,
        run: OrchestrationRun,
        result: dict[str, Any],
        worktree_path: Path,
        thinker_provider: str,
        change_name: str,
    ) -> OrchestrationCoordinationResult:
        """Correct proposal findings once, then require a second independent review."""
        findings = result.get("findings") or []
        round_num, max_rounds = self._review_round(uow, project_id, run, "proposal_review")
        if not findings or round_num + 1 >= max_rounds:
            if findings:
                reason = (
                    "La revisión independiente sigue bloqueando la propuesta y se agotaron los "
                    "intentos. Revisa el hallazgo y elige la sugerencia o escribe otra instrucción. "
                    "El mismo Run reanudará Propose y la propuesta deberá pasar otra revisión "
                    "independiente; tu respuesta no la aprueba."
                )
                review_options = result.get("options") or [
                    {
                        "id": "request_correction_and_rereview",
                        "label": "Pedir corrección y nueva revisión",
                        "description": (
                            "El mismo Run reanudará Propose con este hallazgo; después, el "
                            "revisor independiente deberá evaluar de nuevo la propuesta."
                        ),
                        "source": "system_generated",
                    }
                ]
                options_source = "native" if result.get("options") else "system_generated"
            else:
                reason = (
                    self._review_pause_message("proposal", result)
                    + " No se recibieron hallazgos accionables."
                )
                review_options = result.get("options") or ()
                options_source = "native" if result.get("options") else "free_text"
            details = dict(run.stop_details or {})
            details["proposal_review_escalated"] = True
            run.stop_details = details
            payload = self._record_current_human_gate(
                uow,
                run,
                gate="proposal_review_escalation",
                question=reason,
                options=review_options,
                payload={
                    "review_findings": findings,
                    "reviewer_summary": result.get("summary") or "",
                    "options_source": options_source,
                },
            )
            return OrchestrationCoordinationResult(
                status="HUMAN_REQUIRED",
                run_id=run.run_id,
                current_stage=OrchestrationStage.PROPOSAL_REVIEW,
                message=reason,
                human_payload=payload,
            )

        details = dict(run.stop_details or {})
        review_state = dict(details.get("proposal_review") or {})
        review_state["round"] = round_num + 1
        details["proposal_review"] = review_state
        details["pending_proposal_corrections"] = findings
        details["proposal_correction"] = {
            "status": "dispatched",
            "round": round_num + 1,
            "recorded_at": utc_now().isoformat(),
        }
        run.stop_details = details
        if hasattr(uow, "orchestration_runs"):
            uow.orchestration_runs.save(run)
            if hasattr(uow, "commit"):
                uow.commit()

        correction_ok = await self._run_native_boolean_stage(
            uow, run, worktree_path, "UPDATE",
            lambda observer: self._run_propose_correction(
                worktree_path,
                thinker_provider,
                change_name,
                json.dumps(findings, ensure_ascii=False),
                project_id=project_id,
                process_start_observer=observer,
            ),
        )
        new_hashes = self._compute_proposal_artifacts_hashes(worktree_path, change_name)
        old_hashes = result.get("artifact_hashes") or {}
        details = dict(run.stop_details or {})
        correction = dict(details.get("proposal_correction") or {})
        correction.update(
            {
                "status": "completed" if correction_ok else "failed",
                "artifact_hashes": new_hashes,
                "finished_at": utc_now().isoformat(),
            }
        )
        details["proposal_correction"] = correction
        details.pop("pending_proposal_corrections", None)
        run.stop_details = details
        if hasattr(uow, "orchestration_runs"):
            uow.orchestration_runs.save(run)
            if hasattr(uow, "commit"):
                uow.commit()

        if not correction_ok:
            reason = "Native OpenSpec update failed after independent proposal findings; human decision required."
            return OrchestrationCoordinationResult(
                status="HUMAN_REQUIRED",
                run_id=run.run_id,
                current_stage=OrchestrationStage.PROPOSAL_REVIEW,
                message=reason,
                human_payload={"question": reason, "options": [], "run_id": run.run_id},
            )
        if new_hashes == old_hashes:
            reason = "Proposal correction produced no artifact change; human decision required."
            return OrchestrationCoordinationResult(
                status="HUMAN_REQUIRED",
                run_id=run.run_id,
                current_stage=OrchestrationStage.PROPOSAL_REVIEW,
                message=reason,
                human_payload={"question": reason, "options": [], "run_id": run.run_id},
            )

        self._update_stage(uow, run, OrchestrationStage.PROPOSAL_REVIEW)
        return OrchestrationCoordinationResult(
            status="RUNNING",
            run_id=run.run_id,
            current_stage=OrchestrationStage.PROPOSAL_REVIEW,
            message=(
                f"Independent proposal review requested changes (round {round_num + 1}/{max_rounds}); "
                "native OpenSpec correction completed and a second independent review is pending."
            ),
        )

    @staticmethod
    def _classify_review_reentry(
        stored: Any,
        *,
        identity_matches: bool,
        is_resume: bool,
    ) -> str:
        """Classify a review-stage reentry into one fail-closed action.

        The invariant: an approval is reusable only when it binds exactly to the
        current content. Any other durable state either pauses, or — when it is
        ambiguous or stale — requires an explicit governed re-dispatch.
        """
        if not isinstance(stored, dict):
            # No durable review evidence. A fresh dispatch is safe only on the
            # pass that just entered the stage; on a resume it is ambiguous
            # (e.g. a legacy run whose review was never recorded).
            return _REVIEW_AMBIGUOUS if is_resume else _REVIEW_STALE
        status = stored.get("status")
        if status == "dispatched":
            # An in-flight attempt with no definitive result is ambiguous no
            # matter what identity it recorded.
            return _REVIEW_AMBIGUOUS
        if not identity_matches:
            # Content changed after the prior review: that review is stale.
            return _REVIEW_STALE
        if status == "approved":
            return _REVIEW_ADVANCE if stored.get("verdict") == "READY_TO_MERGE" else _REVIEW_CORRUPT
        if status == "changes_required":
            return _REVIEW_REJECTED
        if status in {"provider_error", "invalid_response"}:
            return _REVIEW_TECHNICAL_FAILURE
        return _REVIEW_AMBIGUOUS

    @staticmethod
    def _review_pause_message(kind: str, result: dict[str, Any]) -> str:
        """Build a single honest pause message for a non-approved review result."""
        status = result.get("status")
        if status == "changes_required":
            return f"Independent {kind} review requested changes: {result.get('summary', 'see findings')}. Worktree preserved."
        if status == "provider_error":
            return f"Independent {kind} review provider failed: {result.get('error', 'unknown error')}. Worktree preserved."
        if status == "invalid_response":
            return f"Independent {kind} review produced invalid response: {result.get('error', 'malformed output')}. Worktree preserved."
        return f"Independent {kind} review did not approve. Worktree preserved."

    @staticmethod
    def _review_failure_error(res: Any) -> str:
        """Build a diagnostic error string for a failed review execution.

        The CLI runner reports the classified reason in ``preflight_error`` (e.g.
        PROVIDER_PROCESS_FAILURE) but the raw provider message that explains it lives in
        ``stderr``. Persist both so a PAUSED run shows the real cause instead of the
        generic "Reviewer agent execution failed" fallback.
        """
        reason = getattr(res, "preflight_error", None) or getattr(res, "error_message", None)
        if not reason:
            return "Reviewer agent execution failed"
        stderr = getattr(res, "stderr", None) or []
        tail = " | ".join(str(line) for line in stderr[-4:]).strip()
        if tail:
            return f"{reason} :: {tail[:500]}"
        return reason

    @staticmethod
    def _compute_proposal_artifacts_hashes(worktree_path: Path, change_name: str) -> dict[str, str]:
        """Compute stable SHA256 hashes of all proposal planning artifacts."""
        change_dir = worktree_path / "openspec" / "changes" / change_name
        hashes = {}
        for fname in ["proposal.md", "design.md", "tasks.md"]:
            fpath = change_dir / fname
            if fpath.is_file():
                hashes[fname] = hashlib.sha256(fpath.read_bytes()).hexdigest()
        specs_dir = change_dir / "specs"
        if specs_dir.is_dir():
            for sp in sorted(specs_dir.rglob("*.md")):
                rel = str(sp.relative_to(change_dir))
                hashes[rel] = hashlib.sha256(sp.read_bytes()).hexdigest()
        return hashes

    async def _run_proposal_review(
        self,
        worktree_path: Path,
        provider: str,
        change_name: str,
        project_id: str | None = None,
        uow: Any = None,
        process_start_observer: Any = None,
    ) -> ReviewResult:
        """Execute independent read-only proposal review for high complexity changes."""
        change_dir = worktree_path / "openspec" / "changes" / change_name
        proposal_text = (
            (change_dir / "proposal.md").read_text(errors="ignore")
            if (change_dir / "proposal.md").exists()
            else ""
        )
        design_text = (
            (change_dir / "design.md").read_text(errors="ignore")
            if (change_dir / "design.md").exists()
            else ""
        )
        tasks_text = (
            (change_dir / "tasks.md").read_text(errors="ignore")
            if (change_dir / "tasks.md").exists()
            else ""
        )
        prompt = (
            f"You are the independent reviewer agent (read-only). Perform independent review on OpenSpec change '{change_name}'.\n\n"
            f"Proposal Artifacts:\n{proposal_text}\n\n"
            f"Design Artifacts:\n{design_text}\n\n"
            f"Tasks Artifacts:\n{tasks_text}\n\n"
            f"Evaluate architectural soundness, correctness, security, and scope. Flag only "
            f"substantive defects that would make the change incorrect, unsafe, or out of scope. "
            f"Do NOT flag documentation completeness, wording, or formatting. A BLOCKER must mean "
            f"the change cannot be implemented safely at all; a MAJOR must mean a real "
            f"correctness or security gap; a MINOR is a nit that must not block. Do not re-flag a "
            f"requirement that is already covered by an existing task; report only findings that "
            f"are new and material.\n"
            f"{_REVIEW_VERDICT_SCHEMA_HINT}\n"
        )
        model = (
            self._configured_model(uow, project_id, "reviewer") if (uow and project_id) else None
        )
        artifact_hashes = self._compute_proposal_artifacts_hashes(worktree_path, change_name)
        reviewer_id = f"{provider}:{model or 'reviewer'}"
        res = await self.agent_runner.run(
            worktree_path=worktree_path,
            prompt_context=prompt,
            project_id=project_id,
            role="reviewer",
            provider=provider,
            reviewer_identity=reviewer_id,
            process_start_observer=process_start_observer,
        )
        base_record = {
            "reviewer_provider": provider,
            "reviewer_model": model,
            "artifact_hashes": artifact_hashes,
            "recorded_at": utc_now().isoformat(),
        }
        if not self._execution_is_successful(res):
            return ReviewResult(
                {
                    **base_record,
                    "status": "provider_error",
                    "verdict": None,
                    "findings": [],
                    "error": self._review_failure_error(res),
                }
            )
        try:
            parsed = parse_review_verdict(res.response_output)
            findings_data = [
                f.model_dump() if hasattr(f, "model_dump") else dict(f) for f in parsed.findings
            ]
            if parsed.verdict.value == "READY_TO_MERGE":
                return ReviewResult(
                    {
                        **base_record,
                        "status": "approved",
                        "verdict": parsed.verdict.value,
                        "findings": [],
                    }
                )
            return ReviewResult(
                {
                    **base_record,
                    "status": "changes_required",
                    "verdict": parsed.verdict.value,
                    "findings": findings_data,
                    "summary": parsed.summary,
                }
            )
        except MalformedReviewOutputError as exc:
            return ReviewResult(
                {
                    **base_record,
                    "status": "invalid_response",
                    "verdict": None,
                    "findings": [],
                    "error": str(exc),
                }
            )

    async def _run_apply(
        self,
        worktree_path: Path,
        provider: str,
        change_name: str,
        project_id: str | None = None,
        corrections: list[dict[str, Any]] | None = None,
        recovery_context: str = "",
        run_id: str | None = None,
        base_branch: str = "main",
        process_start_observer: Any = None,
        operator_response: str | None = None,
    ) -> ApplyOutcome:
        """Dispatch configured implementer agent to execute official OpenSpec Apply workflow."""
        wf = self.agent_runner.resolve_workflow(
            worktree_path=worktree_path,
            provider=provider,
            operation="apply",
            change_name=change_name,
        )
        correction_instruction = ""
        if corrections:
            rendered = []
            for idx, finding in enumerate(corrections, 1):
                sev = str(finding.get("severity", "MAJOR")).upper()
                loc = str(finding.get("location") or "unspecified").strip()
                req = str(finding.get("violated_requirement") or "").strip()
                fix = str(finding.get("expected_correction") or "").strip()
                rendered.append(
                    f"{idx}. [{sev}] {loc}\n   Violated: {req or 'unspecified'}\n   Fix: {fix or 'unspecified'}"
                )
            correction_instruction = (
                "\n\nThe independent reviewer returned CHANGES_REQUIRED with the following findings. "
                "Correct every finding in this same change, then re-run the test suite:\n\n"
                + "\n\n".join(rendered)
                + "\n\nDo not expand scope beyond these findings; preserve the existing OpenSpec change."
            )
        prompt = (
            f"You are the implementer agent. Execute official OpenSpec Apply for change '{change_name}'.\n"
            f"Workflow command: {wf.dispatch_command}\n\n"
            f"Implement all pending tasks specified in tasks.md, write unit and E2E tests, "
            f"ensure the test suite passes, and mark completed tasks as [x] only when coordinator-observed diff and passing relevant tests support completion."
            f"{correction_instruction}"
            f"{recovery_context}"
        )
        if operator_response and operator_response.strip():
            prompt += "\n\nAccepted operator response for the current gate (context only):\n" + operator_response.strip()
        try:
            await self._git_run(worktree_path, ["rev-parse", "HEAD"])
            await self._git_run(worktree_path, ["status", "--porcelain"])
        except GitOperationError as exc:
            return ApplyOutcome("FAILED", (), (), None, (), None, None, "", error=str(exc))
        result = await self.agent_runner.run(
            worktree_path=worktree_path,
            prompt_context=prompt,
            project_id=project_id,
            role="implementer",
            provider=provider,
            workflow=wf,
            process_start_observer=process_start_observer,
        )
        tasks_path = worktree_path / "openspec" / "changes" / change_name / "tasks.md"
        if not tasks_path.is_file():
            return ApplyOutcome("FAILED", (), (), None, (), None, None, "", error="tasks.md missing")
        tasks_text = tasks_path.read_text(encoding="utf-8", errors="replace") if tasks_path.is_file() else ""
        pending, _ = self._classify_pending_tasks(tasks_text)
        completed = re.findall(r"(?m)^\s*-\s*\[x\]\s+([^\n]*)$", tasks_text, re.I)
        completed_ids = tuple(line.strip().split()[0] for line in completed if line.strip())
        try:
            sha = await self._git_run(worktree_path, ["rev-parse", "HEAD"])
            diff = await self._git_run(worktree_path, ["diff", "--binary", "HEAD"])
            paths = await self._git_run(worktree_path, ["status", "--porcelain"])
            branch = await self._git_run(worktree_path, ["branch", "--show-current"])
        except GitOperationError as exc:
            return ApplyOutcome("FAILED", completed_ids, tuple(pending), None, (), None, None, "", error=str(exc))
        sha_text = sha.stdout if hasattr(sha, "stdout") else str(sha)
        diff_text = diff.stdout if hasattr(diff, "stdout") else str(diff)
        paths_text = paths.stdout if hasattr(paths, "stdout") else str(paths)
        branch_text = branch.stdout if hasattr(branch, "stdout") else str(branch)
        changed_files = tuple(sorted({line[3:].strip() for line in paths_text.splitlines() if len(line) > 3}))
        diff_ok = getattr(diff, "ok", getattr(diff, "returncode", 0) == 0)
        digest = hashlib.sha256(diff_text.encode()).hexdigest() if diff_ok and diff_text else None
        handoff = getattr(result, "workflow_handoff", None)
        tests_passed, test_evidence = await self._run_automated_tests(
            worktree_path, base_branch, process_start_observer=process_start_observer
        )
        if getattr(result, "workflow_handoff_required", False) and handoff and handoff.status == "HUMAN_REQUIRED":
            return ApplyOutcome("HUMAN_REQUIRED", completed_ids, tuple(pending), sha_text.strip() if getattr(sha, "ok", True) else None,
                                changed_files, digest, tests_passed, test_evidence,
                                human_question=handoff.summary, human_options=handoff.pending,
                                branch=branch_text.strip(), worktree=str(worktree_path), run_id=run_id)
        successful = self._execution_is_successful(result)
        ready = successful and not pending
        status = "COMPLETE" if ready else ("PARTIAL" if successful else "FAILED")
        error = None if successful else self._review_failure_error(result)
        return ApplyOutcome(status, completed_ids, tuple(pending), sha_text.strip() if getattr(sha, "ok", True) else None,
                            changed_files, digest, tests_passed, test_evidence, error=error,
                            branch=branch_text.strip(), worktree=str(worktree_path), run_id=run_id)

    async def _git_changed_paths_for_tests(
        self, worktree_path: Path, base_branch: str
    ) -> tuple[set[str] | None, str | None]:
        """Read candidate changes from Git; agent-reported paths are never authoritative."""
        commands = (
            ["diff", "--name-only", "-z", "--diff-filter=ACMR", f"{base_branch}...HEAD"],
            ["diff", "--cached", "--name-only", "-z", "--diff-filter=ACMR"],
            ["diff", "--name-only", "-z", "--diff-filter=ACMR"],
            ["ls-files", "--others", "--exclude-standard", "-z"],
        )
        changed_paths: set[str] = set()
        for command in commands:
            try:
                result = await self._git_run(worktree_path, command)
            except (GitOperationError, OSError) as exc:
                return None, f"git {' '.join(command)} failed: {exc}"
            changed_paths.update(path for path in result.stdout.split("\0") if path)
        return changed_paths, None

    @staticmethod
    def _is_pytest_file(path: str) -> bool:
        name = Path(path).name
        return path.endswith(".py") and (name.startswith("test_") or name.endswith("_test.py"))

    @staticmethod
    def _python_module_name(path: str) -> str | None:
        source_path = Path(path)
        if source_path.suffix != ".py":
            return None
        parts = list(source_path.with_suffix("").parts)
        if parts and parts[0] in {"src", "lib"}:
            parts = parts[1:]
        if parts and parts[-1] == "__init__":
            parts.pop()
        return ".".join(parts) if parts else None

    @staticmethod
    def _imported_modules(test_path: Path) -> set[str]:
        """Parse a test file once and return its directly imported module names."""
        try:
            tree = ast.parse(test_path.read_text(encoding="utf-8", errors="replace"))
        except (OSError, SyntaxError, UnicodeError):
            return set()
        imported_modules: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_modules.add(node.module)
                imported_modules.update(f"{node.module}.{alias.name}" for alias in node.names)
        return imported_modules

    @classmethod
    def _select_relevant_test_paths(
        cls, worktree_path: Path, changed_paths: set[str], candidate_paths: set[str]
    ) -> list[str]:
        changed_tests = {
            path for path in changed_paths
            if cls._is_pytest_file(path) and (worktree_path / path).is_file()
        }
        changed_sources = [
            path for path in changed_paths
            if path.endswith(".py") and not cls._is_pytest_file(path)
            and (worktree_path / path).is_file()
        ]
        source_stems = {Path(path).stem for path in changed_sources}
        source_modules = {
            module for path in changed_sources
            if (module := cls._python_module_name(path)) is not None
        }
        import_index: dict[str, set[str]] = {}
        for test in candidate_paths:
            if not cls._is_pytest_file(test) or not (worktree_path / test).is_file():
                continue
            for module in cls._imported_modules(worktree_path / test):
                import_index.setdefault(module, set()).add(test)

        tests_by_changed_imports: set[str] = set()
        for module in source_modules:
            tests_by_changed_imports.update(import_index.get(module, set()))

        selected = set(changed_tests)
        for test in candidate_paths:
            if not cls._is_pytest_file(test) or not (worktree_path / test).is_file():
                continue
            test_path = Path(test)
            test_name = test_path.name
            mapped_by_name = any(
                test_name in {f"test_{stem}.py", f"{stem}_test.py"}
                for stem in source_stems
            )
            mapped_by_path = any(
                len(Path(module).parts) > 1
                and test_path.parent.parts[-(len(Path(module).parts) - 1):]
                == Path(module).parts[:-1]
                and test_name in {
                    f"test_{Path(module).stem}.py",
                    f"{Path(module).stem}_test.py",
                }
                for module in source_modules
            )
            mapped_by_import = test in tests_by_changed_imports
            if mapped_by_name or mapped_by_path or mapped_by_import:
                selected.add(test)
        return sorted(selected)

    async def _run_automated_tests(
        self, worktree_path: Path, base_branch: str = "main",
        process_start_observer: Any = None,
    ) -> tuple[bool, str]:
        """Run only pytest files selected from Git-observed candidate changes."""
        import sys

        # Use the runtime interpreter that launched mini me.  A PATH-resolved
        # pytest may belong to another environment and can produce a false
        # failure even when the candidate's declared dependencies pass.
        try:
            changed_paths, selection_error = await self._git_changed_paths_for_tests(
                worktree_path, base_branch
            )
            if changed_paths is None:
                return False, f"Test selection failed; pytest was not run. {selection_error}"
            files_result = await self._git_run(
                worktree_path,
                ["ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            )
            candidate_paths = {path for path in files_result.stdout.split("\0") if path}
        except (GitOperationError, OSError) as exc:
            return False, f"Test selection failed; pytest was not run. {exc}"
        selected_tests = self._select_relevant_test_paths(
            worktree_path, changed_paths, candidate_paths
        )
        if not selected_tests:
            return False, (
                "Test selection failed: no tests were selected; pytest was not run. "
                f"Changed files: {', '.join(sorted(changed_paths)) or '(none)'}"
            )

        cmd = [sys.executable, "-m", "pytest", "-q", *selected_tests]
        command_text = shlex.join(cmd)
        selected_text = ", ".join(selected_tests)
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(worktree_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
            )
            if process_start_observer is not None:
                identity = process_identity(proc.pid)
                identity["pgid"] = proc.pid
                try:
                    process_start_observer(identity)
                except Exception as exc:
                    try:
                        os.killpg(proc.pid, signal.SIGKILL)
                    except OSError:
                        proc.kill()
                    await proc.communicate()
                    return False, (
                        f"selected_tests: {selected_text}\ncommand: {command_text}\n"
                        "exit_code: NOT_STARTED\nstdout:\n\nstderr:\n"
                        f"Unable to persist test process identity: {type(exc).__name__}"
                    )
            stdout, stderr = await proc.communicate()
            stdout_text = stdout.decode(errors="replace")
            stderr_text = stderr.decode(errors="replace")
            evidence = (
                f"selected_tests: {selected_text}\n"
                f"command: {command_text}\n"
                f"exit_code: {proc.returncode}\n"
                f"stdout:\n{stdout_text}\n"
                f"stderr:\n{stderr_text}"
            )
            if proc.returncode == 0:
                normalized = evidence.lower()
                has_execution = bool(
                    re.search(r"\b\d+\s+(?:passed|failed|skipped|xfailed|xpassed)\b", normalized)
                    or re.search(r"collected\s+[1-9]\d*\s+items?", normalized)
                )
                if has_execution and "no tests ran" not in normalized:
                    return True, evidence
                return False, evidence or "Tests produced no collection/execution evidence."
            if "no tests ran" in evidence.lower() or proc.returncode == 5:
                return False, evidence
            return False, evidence
        except OSError as exc:
            logger.warning(f"Automated test runner exception: {exc}")
            return False, (
                f"selected_tests: {selected_text}\ncommand: {command_text}\n"
                f"exit_code: NOT_STARTED\nstdout:\n\nstderr:\n{exc}"
            )

    async def _run_verify(
        self,
        worktree_path: Path,
        provider: str,
        change_name: str,
        project_id: str | None = None,
        process_start_observer: Any = None,
        operator_response: str | None = None,
    ) -> VerifyOutcome:
        """Dispatch the SAME implementer agent to execute native OpenSpec Verify workflow."""
        wf = self.agent_runner.resolve_workflow(
            worktree_path=worktree_path,
            provider=provider,
            operation="verify",
            change_name=change_name,
        )
        prompt = (
            f"Execute official OpenSpec Verify for change '{change_name}'.\n"
            f"Workflow dispatch command: {wf.dispatch_command}\n\n"
            "Verify that all tasks and requirements are implemented and verified with green tests. "
            "After completing the native Verify workflow, return exactly one JSON object in the "
            "authorized final response channel matching this schema: "
            '{"verdict":"READY_TO_MERGE|CHANGES_REQUIRED",'
            '"summary":"brief concrete result",'
            '"findings":[{"severity":"BLOCKER|MAJOR|MINOR",'
            '"location":"file or requirement",'
            '"violated_requirement":"required only for a finding",'
            '"expected_correction":"required only for a finding"}]}.'
            " Use READY_TO_MERGE only when the native Verify result is positive and findings is empty."
        )
        if operator_response and operator_response.strip():
            prompt += "\n\nAccepted operator response for the current gate (context only):\n" + operator_response.strip()
        attempt_dir = worktree_path / ".minime" / "verify-attempts" / str(uuid4())
        response_path = attempt_dir / "last-message.json"
        res = await self.agent_runner.run(
            worktree_path=worktree_path,
            prompt_context=prompt,
            project_id=project_id,
            role="implementer",
            provider=provider,
            workflow=wf,
            process_start_observer=process_start_observer,
            output_schema={
                "type": "object",
                "properties": {
                    "verdict": {"type": "string", "enum": ["READY_TO_MERGE", "CHANGES_REQUIRED"]},
                    "summary": {"type": "string"},
                    "findings": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "severity": {
                                    "type": "string",
                                    "enum": ["BLOCKER", "MAJOR", "MINOR"],
                                },
                                "location": {"type": "string"},
                                "violated_requirement": {"type": "string"},
                                "expected_correction": {"type": "string"},
                            },
                            "required": [
                                "severity",
                                "location",
                                "violated_requirement",
                                "expected_correction",
                            ],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["verdict", "summary", "findings"],
                "additionalProperties": False,
            },
            output_last_message_path=response_path,
        )
        handoff = getattr(res, "workflow_handoff", None)
        if (
            getattr(res, "workflow_handoff_required", False)
            and handoff is not None
            and handoff.status == "HUMAN_REQUIRED"
        ):
            return VerifyOutcome(
                "HUMAN_REQUIRED", handoff.summary,
                human_question=handoff.summary,
                human_options=tuple(handoff.pending),
            )
        if not self._execution_is_successful(res):
            return VerifyOutcome("FAILED", "Native Verify execution failed.")
        if getattr(res, "structured_output_missing", False) or getattr(
            res, "structured_output_too_large", False
        ):
            return VerifyOutcome("FAILED", "Native Verify structured result is missing.")
        try:
            parsed = parse_review_verdict(res.response_output)
            return VerifyOutcome(
                "COMPLETE" if parsed.verdict.value == "READY_TO_MERGE" else "FAILED",
                parsed.summary,
                findings=tuple(
                    item.model_dump() if hasattr(item, "model_dump") else dict(item)
                    for item in parsed.findings
                ),
            )
        except MalformedReviewOutputError:
            return VerifyOutcome("FAILED", "Native Verify returned an invalid structured result.")

    async def _run_code_review(
        self,
        worktree_path: Path,
        provider: str,
        change_name: str,
        project_id: str | None = None,
        candidate_sha: str | None = None,
        uow: Any = None,
        process_start_observer: Any = None,
    ) -> ReviewResult:
        """Execute independent read-only code review for high-complexity changes."""
        diff_result = await self._git_run(worktree_path, ["diff", "HEAD~1..HEAD"])
        diff = diff_result.stdout
        prompt = (
            f"You are the independent reviewer agent (read-only). Perform code review on OpenSpec change '{change_name}'.\n\n"
            f"Candidate Diff:\n{diff}\n\n"
            f"Evaluate only substantive correctness, security, and scope defects. "
            f"Do NOT request wording or formatting changes. "
            f"A BLOCKER means the change cannot be implemented safely at all; a MAJOR means a real "
            f"correctness or security gap; a MINOR is a nit that must not block. Do not re-flag a "
            f"requirement that is already covered by an existing task; report only findings that "
            f"are new and material.\n"
            f"{_REVIEW_VERDICT_SCHEMA_HINT}\n"
            "Do not use APPROVED prose."
        )
        model = (
            self._configured_model(uow, project_id, "reviewer") if (uow and project_id) else None
        )
        reviewer_id = f"{provider}:{model or 'reviewer'}"
        res = await self.agent_runner.run(
            worktree_path=worktree_path,
            prompt_context=prompt,
            project_id=project_id,
            role="reviewer",
            provider=provider,
            reviewer_identity=reviewer_id,
            process_start_observer=process_start_observer,
        )
        base_record = {
            "reviewer_provider": provider,
            "reviewer_model": model,
            "candidate_sha": candidate_sha,
            "recorded_at": utc_now().isoformat(),
        }
        if not self._execution_is_successful(res):
            return ReviewResult(
                {
                    **base_record,
                    "status": "provider_error",
                    "verdict": None,
                    "findings": [],
                    "error": self._review_failure_error(res),
                }
            )
        try:
            parsed = parse_review_verdict(res.response_output)
            findings_data = [
                f.model_dump() if hasattr(f, "model_dump") else dict(f) for f in parsed.findings
            ]
            if parsed.verdict.value == "READY_TO_MERGE":
                return ReviewResult(
                    {
                        **base_record,
                        "status": "approved",
                        "verdict": parsed.verdict.value,
                        "findings": [],
                    }
                )
            return ReviewResult(
                {
                    **base_record,
                    "status": "changes_required",
                    "verdict": parsed.verdict.value,
                    "findings": findings_data,
                    "summary": parsed.summary,
                }
            )
        except MalformedReviewOutputError as exc:
            return ReviewResult(
                {
                    **base_record,
                    "status": "invalid_response",
                    "verdict": None,
                    "findings": [],
                    "error": str(exc),
                }
            )

    async def _run_sync_and_archive(
        self,
        doc_path: Path,
        provider: str,
        change_name: str,
        project_id: str | None = None,
        uow: Any = None,
        run: OrchestrationRun | None = None,
        operator_response: str | None = None,
    ) -> bool:
        """Execute official OpenSpec Sync and Archive workflows with thinking agent."""
        sync_wf = self.agent_runner.resolve_workflow(
            worktree_path=doc_path,
            provider=provider,
            operation="sync",
            change_name=change_name,
        )
        archive_wf = self.agent_runner.resolve_workflow(
            worktree_path=doc_path,
            provider=provider,
            operation="archive",
            change_name=change_name,
        )

        async def dispatch(operation: str, workflow: ResolvedWorkflow, prompt: str) -> Any:
            if uow is None or run is None:
                raise RuntimeError("Durable stage invocation context is required for DOC_CLOSING")
            invocation = await self._begin_stage_invocation(
                uow, run, doc_path, operation.upper(),
                allow_human_resume=bool(operator_response),
            )
            if invocation is None:
                raise RuntimeError(f"{operation.title()} invocation is already active or ambiguous")
            dispatch_prompt = prompt
            if operator_response and operator_response.strip():
                dispatch_prompt += (
                    "\n\nAccepted operator response for the current gate (context only):\n"
                    + operator_response.strip()
                )
            try:
                result = await self._run_claimed(
                    uow, invocation.claim,
                    lambda: self.agent_runner.run(
                        worktree_path=doc_path,
                        prompt_context=dispatch_prompt,
                        project_id=project_id,
                        role="thinker",
                        provider=provider,
                        workflow=workflow,
                        process_start_observer=self._observe_stage_process(uow, run, invocation),
                    ),
                )
                handoff = getattr(result, "workflow_handoff", None)
                if (
                    getattr(result, "workflow_handoff_required", False)
                    and handoff is not None
                    and handoff.status == "HUMAN_REQUIRED"
                ):
                    question = str(handoff.summary or "El workflow nativo requiere una decisión humana.")
                    options = tuple(handoff.pending or ())
                    await self._finish_stage_invocation(
                        uow, run, invocation, "HUMAN_REQUIRED",
                        {"operation": operation, "question": question, "options": options},
                    )
                    raise NativeStageHumanRequired(operation, question, options)
                status = "COMPLETE" if self._execution_is_successful(result) else "FAILED"
                await self._finish_stage_invocation(
                    uow, run, invocation, status,
                    {"exit_code": getattr(result, "exit_code", None),
                     "timed_out": getattr(result, "timed_out", None),
                     "final_response_status": getattr(result, "final_response_status", None)},
                )
                return result
            except Exception:
                # Leave the durable start open. Recovery must prove both processes gone.
                uow.claims.release_claim(invocation.claim)
                uow.commit()
                raise

        gate = (run.stop_details or {}).get("human_payload") if run else None
        archive_resume = (
            isinstance(gate, dict) and gate.get("gate") == "doc_closing_archive"
            and bool(operator_response)
        )
        if not archive_resume:
            sync_result = await dispatch(
                "sync", sync_wf,
                (
                    f"Execute ONLY the official OpenSpec Sync workflow for '{change_name}'.\n"
                    f"Dispatch: {sync_wf.dispatch_command}\n"
                    "Return evidence of the resulting synced specs."
                ),
            )
            if not self._execution_is_successful(sync_result):
                return False

        archive_prompt = (
            f"Execute ONLY the official OpenSpec Archive workflow for '{change_name}'.\n"
            f"Dispatch: {archive_wf.dispatch_command}\n"
            "The delta specs have already been synced in the prior step. Archive the change "
            "directly without requesting a sync decision.\n"
            "Return evidence of the resulting archive."
        )
        if operator_response and operator_response.strip():
            archive_prompt += "\n\nAccepted operator response for the current gate (context only):\n" + operator_response.strip()
        archive_result = await dispatch(
            "archive", archive_wf,
            archive_prompt,
        )
        if not self._execution_is_successful(archive_result):
            return False
        archive_root = doc_path / "openspec" / "changes" / "archive"
        archived = self._matching_archived_changes(archive_root, change_name)
        # A success narrative cannot substitute for a real OpenSpec archive.
        if len(archived) != 1:
            return False
        archived_change = archived[0]
        if not (
            (archived_change / "proposal.md").is_file()
            and (archived_change / "design.md").is_file()
            and (archived_change / "tasks.md").is_file()
            and (archived_change / "specs").is_dir()
        ):
            return False

        # Check git status in doc worktree; if changes are uncommitted, stage and commit them
        status_result = await self._git_run(doc_path, ["status", "--porcelain"])
        if status_result.stdout.strip():
            await self._git_run(doc_path, ["add", "openspec/"])
            await self._git_run(
                doc_path, ["commit", "-m", f"docs({change_name}): sync specs and archive change"]
            )
        return True

    async def _ensure_doc_closing_sync_archive(
        self,
        doc_path: Path,
        provider: str,
        change_name: str,
        project_id: str | None = None,
        uow: Any = None,
        run: OrchestrationRun | None = None,
        operator_response: str | None = None,
    ) -> tuple[bool, str | None]:
        """Observe DOC_CLOSING before deciding whether native workflows are needed."""
        state, detail = self._observe_doc_closing_change(doc_path, change_name)
        if state == "archived_complete":
            return True, None
        if state != "active":
            return False, f"Documentation Change state is {state}: {detail}."
        try:
            completed = await self._run_sync_and_archive(
                doc_path, provider, change_name, project_id=project_id, uow=uow, run=run,
                operator_response=operator_response,
            )
        except NativeStageHumanRequired as handoff:
            if uow is not None and run is not None:
                self._record_current_human_gate(
                    uow, run, gate=f"doc_closing_{handoff.operation}",
                    question=handoff.question, options=handoff.options,
                )
            return False, handoff.question
        if not completed:
            return False, "Native Sync or Archive failed."
        return True, None

    @staticmethod
    def _matching_archived_changes(archive_root: Path, change_name: str) -> list[Path]:
        """Find exact or date-prefixed OpenSpec archive directories for a Change."""
        if not archive_root.is_dir() or archive_root.is_symlink():
            return []
        dated_name = re.compile(rf"\d{{4}}-\d{{2}}-\d{{2}}-{re.escape(change_name)}\Z")
        return [
            entry
            for entry in archive_root.iterdir()
            if entry.is_dir()
            and (entry.name == change_name or dated_name.fullmatch(entry.name))
        ]

    @classmethod
    def _observe_doc_closing_change(cls, doc_path: Path, change_name: str) -> tuple[str, str]:
        """Read the reused documentation worktree before repeating Sync/Archive."""
        changes_root = doc_path / "openspec" / "changes"
        active_change = changes_root / change_name
        archive_root = changes_root / "archive"

        if changes_root.is_symlink():
            return "incomplete", "openspec/changes is a symbolic link"
        if archive_root.is_symlink():
            return "incomplete", "openspec/changes/archive is a symbolic link"

        archived = cls._matching_archived_changes(archive_root, change_name)
        if active_change.exists() and active_change.is_symlink():
            return "incomplete", "active Change path is a symbolic link"
        if active_change.exists() and not active_change.is_dir():
            return "incomplete", "active Change path is not a directory"
        if active_change.is_dir() and archived:
            return "ambiguous", "both an active Change and matching archive entries exist"
        if active_change.is_dir():
            return "active", "active Change is present"
        if len(archived) != 1:
            return "ambiguous", f"expected one matching archive entry, found {len(archived)}"

        archived_change = archived[0]
        if archived_change.is_symlink():
            return "incomplete", "archived Change path is a symbolic link"
        required = ("proposal.md", "design.md", "tasks.md")
        missing = [name for name in required if not (archived_change / name).is_file()]
        if missing:
            return "incomplete", f"archived Change is missing required artifacts: {', '.join(missing)}"

        delta_root = archived_change / "specs"
        if not delta_root.is_dir() or delta_root.is_symlink():
            return "incomplete", "archived Change has no regular specs directory"
        delta_specs = sorted(delta_root.rglob("*.md"))
        if not delta_specs:
            return "incomplete", "archived Change contains no delta spec files"

        main_specs_root = doc_path / "openspec" / "specs"
        if not main_specs_root.is_dir() or main_specs_root.is_symlink():
            return "incomplete", "main OpenSpec specs directory is unavailable"
        for delta_spec in delta_specs:
            if delta_spec.is_symlink() or not delta_spec.is_file():
                return "incomplete", f"delta spec is not a regular file: {delta_spec.name}"
            relative_spec = delta_spec.relative_to(delta_root)
            main_spec = main_specs_root / relative_spec
            if main_spec.is_symlink() or not main_spec.is_file():
                return "incomplete", f"corresponding main spec is missing: {relative_spec.as_posix()}"
            if not main_spec.resolve().is_relative_to(main_specs_root.resolve()):
                return "incomplete", f"corresponding main spec escapes specs/: {relative_spec.as_posix()}"

        return "archived_complete", "archived Change and corresponding main specs are present"

    async def _push_branch(self, worktree_path: Path, branch_name: str) -> None:
        """Publish a candidate through the configured GitHub adapter identity."""
        candidate_sha = await self._get_git_head_sha(worktree_path)
        push = getattr(self.github_adapter, "push_branch", None)
        if push is None:
            raise GitOperationError(
                GitCommandResult(
                    ("push", "-u", "origin", branch_name),
                    1,
                    "",
                    "Configured GitHub adapter does not provide authenticated branch publication.",
                )
            )
        result = push(
            worktree_path=str(worktree_path),
            remote="origin",
            branch=branch_name,
            candidate_sha=candidate_sha,
        )
        result = await result if inspect.isawaitable(result) else result
        if not self._external_success(result) or getattr(result, "data", None) != candidate_sha:
            detail = (
                getattr(result, "error_message", None)
                or "Authenticated branch publication was not confirmed."
            )
            raise GitOperationError(
                GitCommandResult(("push", "-u", "origin", branch_name), 1, "", str(detail))
            )

    async def _ensure_candidate_commit(self, worktree_path: Path, issue_number: int) -> None:
        """Persist Apply output before publishing it; never publish a dirty worktree."""
        status = await self._git_run(worktree_path, ["status", "--porcelain"])
        status_text = status if isinstance(status, str) else status.stdout
        if not status_text.strip():
            return
        await self._git_run(worktree_path, ["add", "-A"])
        ignored_paths: list[str] = []
        for cache_dir in worktree_path.rglob("__pycache__"):
            if cache_dir.is_dir():
                ignored_paths.append(str(cache_dir.relative_to(worktree_path)))
        ignored_paths.extend(
            str(path.relative_to(worktree_path))
            for path in worktree_path.rglob("*.pyc")
            if path.is_file()
        )
        if ignored_paths:
            await self._git_run(worktree_path, ["reset", "--", *ignored_paths])
        staged = await self._git_run(worktree_path, ["diff", "--cached", "--name-only"])
        if not staged.stdout.strip():
            return
        await self._git_run(
            worktree_path,
            ["commit", "-m", f"feat(request-{issue_number}): implement OpenSpec change"],
        )

    async def _get_git_head_sha(self, worktree_path: Path) -> str:
        result = await self._git_run(worktree_path, ["rev-parse", "HEAD"])
        return result.stdout.strip()

    async def _git_run(self, cwd: Path, args: list[str]) -> GitCommandResult:
        proc = await asyncio.create_subprocess_exec(
            "git",
            *args,
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        result = GitCommandResult(
            tuple(args),
            proc.returncode or 0,
            stdout.decode(errors="replace"),
            stderr.decode(errors="replace"),
        )
        if not result.ok:
            raise GitOperationError(result)
        return result
