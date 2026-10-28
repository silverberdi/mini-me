"""Native OpenSpec orchestration coordinator for end-to-end request lifecycle."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import re
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
    OperatorActionStatus,
    OperatorActionType,
    OrchestrationStage,
    OrchestrationStopOutcome,
)
from minime.domain.interfaces import PersistenceUnitOfWork
from minime.domain.models import (
    DispatchAuthorization,
    ExternalActionResult,
    OperatorActionRecord,
    OrchestrationExternalAction,
    OrchestrationRun,
    RecoveryClaimContext,
    utc_now,
)
from minime.logging import get_logger, redact_secrets
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


@dataclass(frozen=True)
class ClassificationCheckpointResult:
    """Bounded result for the one-shot complexity recovery checkpoint."""

    status: str
    run_id: str
    attempt_id: str | None
    model_identity: str | None
    artifact_hashes: dict[str, str]
    assessment: ComplexityAssessment
    message: str


class GitOperationError(RuntimeError):
    """A git operation failed and must be recoverable without advancing the run."""

    def __init__(self, result: GitCommandResult) -> None:
        super().__init__(
            f"git {' '.join(result.args)} failed ({result.returncode}): {result.stderr.strip()}"
        )
        self.result = result


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

    async def _run_claimed(self, uow: Any, claim: RecoveryClaimContext, operation: Any) -> Any:
        """Keep the durable claim owned by this live worker, or fence the child."""
        renew = getattr(uow, "renew_claim_heartbeat_isolated", None)
        if not callable(renew):
            claims = getattr(uow, "claims", None)
            local_renew = getattr(claims, "renew_heartbeat", None)
            if not callable(local_renew):
                raise RuntimeError("Recovery claim heartbeat is unavailable")
            def renew(context: RecoveryClaimContext, lease: int) -> bool:
                return local_renew(
                    context.claim_key, context.owner_instance_id, context.fence_token, lease
                )
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
    ) -> Any:
        """Run one native agent call under the shared claim and close its intent."""
        attempt_id, action_key, claim = dispatch
        try:
            result = await self._run_claimed(uow, claim, work)
        except asyncio.CancelledError:
            self._finish_native_dispatch(uow, run, operation, attempt_id, action_key, claim, "AMBIGUOUS", None)
            raise
        except Exception as exc:
            self._finish_native_dispatch(uow, run, operation, attempt_id, action_key, claim, "AMBIGUOUS", str(exc))
            raise
        status = "COMPLETE" if complete(result) else "FAILED"
        self._finish_native_dispatch(
            uow, run, operation, attempt_id, action_key, claim, status,
            None if status == "COMPLETE" else result.get("message"),
        )
        return result

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

    def register_classification_retry_authorization(
        self,
        *,
        project_id: str,
        run_id: str,
        authorization_reference: str,
        actor_identity: str,
        issue_number: int,
        provider: str,
        model_identity: str,
        prior_attempt_id: str | None,
        artifact_hashes: dict[str, str],
        context_hashes: dict[str, str],
    ) -> bool:
        """Persist a future one-shot classification authorization without dispatching."""
        uow = self.uow_factory()
        run = uow.orchestration_runs.get_by_id(run_id)
        if not run or run.project_id != project_id or not run.is_active:
            return False
        actions = getattr(uow, "operator_actions", None)
        if actions is None or actions.get_by_request_id(authorization_reference) is not None:
            return False
        latest = (run.stop_details or {}).get("complexity_attempts") or []
        if not latest or latest[-1].get("attempt_id") != prior_attempt_id:
            return False
        action = OperatorActionRecord(
            action_request_id=authorization_reference,
            project_id=project_id,
            change_name=run.change_name,
            run_id=run_id,
            action_type=OperatorActionType.RETRY,
            actor_identity=actor_identity,
            source_interface="operator",
            precondition_stage=OrchestrationStage.VALIDATING.value,
            status=OperatorActionStatus.ACCEPTED,
            summary="One-shot authorization for the existing Codex classification attempt.",
            parameters_json={
                "single_use": True,
                "stage": "classification",
                "issue_number": issue_number,
                "provider": provider,
                "model_identity": model_identity,
                "prior_attempt_id": prior_attempt_id,
                "artifact_hashes": artifact_hashes,
                "context_hashes": context_hashes,
            },
        )
        actions.save(action)
        uow.commit()
        return True

    def register_explore_recovery_authorization(
        self,
        *,
        project_id: str,
        run_id: str,
        authorization_reference: str,
        actor_identity: str,
        source_interface: str,
        issue_number: int,
        provider: str,
        prior_attempt_id: str,
    ) -> bool:
        """Register one authenticated, Run-bound recovery decision before dispatch."""
        uow = self.uow_factory()
        run = (
            uow.orchestration_runs.get_for_update(run_id)
            if hasattr(uow.orchestration_runs, "get_for_update")
            else uow.orchestration_runs.get_by_id(run_id)
        )
        if not run or run.project_id != project_id or not run.is_active:
            return False
        details = dict(run.stop_details or {})
        attempt = details.get("explore_attempt")
        legacy_missing_attempt = prior_attempt_id is None
        if legacy_missing_attempt:
            if (
                attempt is not None
                or details.get("explore_checkpoint") is not None
                or run.current_stage != OrchestrationStage.EXPLORING
            ):
                return False
        elif not isinstance(attempt, dict) or attempt.get("attempt_id") != prior_attempt_id:
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
            precondition_stage=OrchestrationStage.EXPLORING.value,
            status=OperatorActionStatus.ACCEPTED,
            summary="One-shot authenticated authorization for Explore recovery.",
            parameters_json={
                "single_use": True,
                "stage": "explore",
                "issue_number": issue_number,
                "provider": provider,
                "prior_attempt_id": prior_attempt_id,
                "change_name": run.change_name,
                "legacy_missing_attempt": legacy_missing_attempt,
                "prior_context_sha256": (
                    attempt.get("context_sha256") if isinstance(attempt, dict) else None
                ),
                "prior_workflow_sha256": (
                    attempt.get("workflow_sha256") if isinstance(attempt, dict) else None
                ),
            },
        )
        actions.save(action)
        uow.commit()
        return True

    def register_propose_recovery_authorization(
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
    ) -> bool:
        """Register one Run-bound authorization for an incomplete Propose.

        A partial change directory is evidence of work, not evidence of a
        successful Propose.  The authorization is therefore consumed only by
        the continuation path and never turns a first invocation into a retry.
        """
        uow = self.uow_factory()
        run = (
            uow.orchestration_runs.get_for_update(run_id)
            if hasattr(uow.orchestration_runs, "get_for_update")
            else uow.orchestration_runs.get_by_id(run_id)
        )
        if not run or run.project_id != project_id or not run.is_active:
            return False
        details = dict(run.stop_details or {})
        attempt = details.get("propose_attempt")
        if run.current_stage not in {OrchestrationStage.PROPOSING, OrchestrationStage.VALIDATING}:
            return False
        if prior_attempt_id is not None and (
            not isinstance(attempt, dict) or attempt.get("attempt_id") != prior_attempt_id
        ):
            return False
        if prior_attempt_id is None and attempt is not None:
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
            summary="One-shot authorization to continue an incomplete native Propose.",
            parameters_json={
                "single_use": True,
                "stage": "propose",
                "issue_number": issue_number,
                "provider": provider,
                "prior_attempt_id": prior_attempt_id,
                "change_name": run.change_name,
            },
        )
        actions.save(action)
        uow.commit()
        return True

    async def classify_existing_run(
        self,
        project_id: str,
        run_id: str,
        worktree_path: Path,
        *,
        thinker_provider: str = "codex",
        issue_number: int | None = None,
        issue_title: str | None = None,
        issue_body: str | None = None,
        authorization_reference: str | None = None,
    ) -> ClassificationCheckpointResult:
        """Run only the pending complexity checkpoint for an existing VALIDATING run.

        This deliberately has no transition into proposal review, Apply, tests,
        Verify, or PR handling. It is the bounded recovery entrypoint used when
        the original classification evidence was not durable.
        """
        uow = self.uow_factory()
        run = uow.orchestration_runs.get_by_id(run_id)
        empty = ComplexityAssessment(status="BLOCKED", reason="checkpoint preflight failed")
        if not run or run.project_id != project_id or not run.is_active:
            return ClassificationCheckpointResult(
                "BLOCKED", run_id, None, None, {}, empty, "Original active run was not found."
            )
        if run.current_stage != OrchestrationStage.VALIDATING:
            return ClassificationCheckpointResult(
                "BLOCKED",
                run_id,
                None,
                None,
                {},
                empty,
                f"Run is not in VALIDATING (found {run.current_stage.value}).",
            )
        persisted_issue_number = (run.stop_details or {}).get("issue_number")
        if issue_number is not None and persisted_issue_number != issue_number:
            return ClassificationCheckpointResult(
                "BLOCKED",
                run_id,
                None,
                None,
                {},
                empty,
                "Checkpoint issue does not match the original run.",
            )
        hashes = self._proposal_artifact_hashes(worktree_path, run.change_name)
        if not self._proposal_artifacts_present(worktree_path, run.change_name):
            return ClassificationCheckpointResult(
                "BLOCKED",
                run_id,
                None,
                None,
                hashes,
                empty,
                "Preserved proposal artifacts are incomplete.",
            )
        validation = self.openspec_adapter.validate_change_strict(run.change_name, worktree_path)
        if validation.get("status") != "PASS":
            return ClassificationCheckpointResult(
                "BLOCKED",
                run_id,
                None,
                None,
                hashes,
                empty,
                "Preserved proposal failed strict OpenSpec validation.",
            )
        project = uow.projects.get_by_id(project_id)
        configured = self._configured_provider(project, "thinking")
        model_identity = self._configured_model(uow, project_id, "thinking")
        if configured != thinker_provider.strip().lower():
            return ClassificationCheckpointResult(
                "BLOCKED",
                run_id,
                None,
                model_identity,
                hashes,
                empty,
                "Checkpoint provider does not match the persisted thinking profile.",
            )
        issue_title = (
            issue_title
            if issue_title is not None
            else str((run.stop_details or {}).get("issue_title") or "")
        )
        issue_body = (
            issue_body
            if issue_body is not None
            else str((run.stop_details or {}).get("issue_body") or "")
        )
        context_hashes = self._classification_context_hashes(
            run, issue_number, issue_title, issue_body
        )
        stored = self._stored_complexity_assessment(run, hashes, context_hashes)
        if stored is not None:
            return ClassificationCheckpointResult(
                "REUSED",
                run_id,
                None,
                model_identity,
                hashes,
                stored,
                "A valid persisted classification was reused without invocation.",
            )
        persisted = (run.stop_details or {}).get("complexity_assessment")
        if (
            isinstance(persisted, dict)
            and persisted.get("artifact_hashes") == hashes
            and persisted.get("context_hashes") == context_hashes
        ):
            recovered = self._recover_persisted_complexity(persisted)
            if recovered is not None:
                recovered_payload = dict(persisted)
                recovered_payload.update(
                    {
                        "status": "VALID",
                        "complexity": recovered.complexity,
                        "evidence": recovered.evidence,
                        "reason": recovered.reason,
                        "structured_output": recovered.structured_output,
                        "diagnostic_output": recovered.diagnostic_output,
                        "recovered_without_invocation": True,
                    }
                )
                details = dict(run.stop_details or {})
                details["complexity_assessment"] = recovered_payload
                run.stop_details = details
                uow.orchestration_runs.save(run)
                uow.commit()
                return ClassificationCheckpointResult(
                    "RECOVERED",
                    run_id,
                    str(persisted.get("attempt_id") or ""),
                    model_identity,
                    hashes,
                    recovered,
                    "Classification recovered from the original separated response channel.",
                )
        if (run.stop_details or {}).get("complexity_attempts"):
            attempts = (run.stop_details or {}).get("complexity_attempts") or []
            prior_attempt_id = str(attempts[-1].get("attempt_id") or "")
            if not authorization_reference:
                return ClassificationCheckpointResult(
                    "BLOCKED",
                    run_id,
                    None,
                    model_identity,
                    hashes,
                    empty,
                    "A prior classification attempt exists; a new invocation requires explicit authorization.",
                )
            actions = getattr(uow, "operator_actions", None)
            if actions is None:
                return ClassificationCheckpointResult(
                    "BLOCKED",
                    run_id,
                    None,
                    model_identity,
                    hashes,
                    empty,
                    "Single-use authorization storage is unavailable.",
                )
            consumed = actions.consume_single_use(
                authorization_reference,
                run_id=run_id,
                action_type=OperatorActionType.RETRY,
                expected_parameters={
                    "single_use": True,
                    "stage": "classification",
                    "issue_number": issue_number,
                    "provider": thinker_provider,
                    "model_identity": model_identity,
                    "prior_attempt_id": prior_attempt_id,
                    "artifact_hashes": hashes,
                    "context_hashes": context_hashes,
                },
            )
            if consumed is None:
                return ClassificationCheckpointResult(
                    "BLOCKED",
                    run_id,
                    None,
                    model_identity,
                    hashes,
                    empty,
                    "Classification authorization is missing, mismatched, or already consumed.",
                )
        attempt_id = str(uuid4())
        in_progress = ComplexityAssessment(
            status="IN_PROGRESS", reason="classification invocation started"
        )
        self._persist_complexity_assessment(
            run,
            in_progress,
            attempt_id=attempt_id,
            model_identity=model_identity,
            artifact_hashes=hashes,
            context_hashes=context_hashes,
        )
        uow.orchestration_runs.save(run)
        uow.commit()
        assessment = await self._assess_complexity(
            worktree_path, thinker_provider, issue_title, issue_body, project_id, attempt_id
        )
        self._persist_complexity_assessment(
            run,
            assessment,
            attempt_id=attempt_id,
            model_identity=model_identity,
            artifact_hashes=hashes,
            context_hashes=context_hashes,
        )
        uow.orchestration_runs.save(run)
        uow.commit()
        return ClassificationCheckpointResult(
            "CLASSIFIED" if assessment.is_valid else "BLOCKED",
            run_id,
            attempt_id,
            model_identity,
            hashes,
            assessment,
            "Classification persisted; checkpoint stopped before Review or Apply.",
        )

    async def execute_project_request(
        self,
        project_id: str,
        *,
        operator_ack: bool = False,
        operator_clarification: str | None = None,
        explore_recovery_authorization_id: str | None = None,
        propose_recovery_authorization_id: str | None = None,
        thinker_provider: str = "antigravity",
        implementer_provider: str = "codex",
        reviewer_provider: str = "antigravity",
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
                json.dumps(
                    explore_base_context, ensure_ascii=False, sort_keys=True
                ).encode("utf-8")
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
                checkpoint_verified
                and stored_explore.get("context_sha256") == explore_context_sha
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
                (stored_explore is not None and not (
                    same_context or authorized_clarification
                ))
                or (
                    stored_explore is None
                    and stage_before_explore == OrchestrationStage.EXPLORING
                )
            )
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
                dispatch = self._prepare_explore_dispatch(
                    uow=uow,
                    run=active_run,
                    issue_number=issue_number,
                    provider=thinker_provider,
                    context_sha=explore_context_sha,
                    workflow_sha=(
                        expected_explore_wf.workflow_sha256
                        if expected_explore_wf is not None
                        else None
                    ),
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
                    lambda: self._run_explore(
                        worktree_path=worktree_path,
                        provider=thinker_provider,
                        issue_number=issue_number,
                        issue_title=issue_title,
                        issue_body=issue_body,
                        operator_clarification=operator_clarification,
                        project_id=project_id,
                    ),
                    lambda result: (
                        result.get("execution") is not None
                        and self._execution_is_successful(result["execution"])
                    ),
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
                        "human_payload": self._safe_human_payload(explore_result.get("human_payload")),
                        "duration_ms": getattr(evidence, "duration_ms", None),
                        "recorded_at": utc_now().isoformat(),
                    }
                    self._persist_run_stop_details(active_run, details)
            if explore_result.get("status") == "HUMAN_REQUIRED":
                return OrchestrationCoordinationResult(
                    status="HUMAN_REQUIRED",
                    run_id=active_run.run_id,
                    current_stage=OrchestrationStage.EXPLORING,
                    message="Explore stage requires operator clarification.",
                    human_payload=self._safe_human_payload(explore_result.get("human_payload")),
                )
            if explore_result.get("status") != "READY_TO_PROPOSE":
                return OrchestrationCoordinationResult(
                    status="PAUSED",
                    run_id=active_run.run_id,
                    current_stage=OrchestrationStage.EXPLORING,
                    message=explore_result.get("message", "Explore failed; proposal cannot start."),
                )

        # Step 6: Propose and Strict Validation Loop
        if active_run.current_stage in (
            OrchestrationStage.EXPLORING,
            OrchestrationStage.PROPOSING,
            OrchestrationStage.VALIDATING,
        ):
            stored_propose_attempt = (active_run.stop_details or {}).get("propose_attempt")
            stored_propose_checkpoint = (active_run.stop_details or {}).get("propose_checkpoint")
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
            ) or (
                planning is None and self._proposal_artifacts_present(worktree_path, change_name)
            )
            verified_propose_checkpoint = (
                isinstance(stored_propose_checkpoint, dict)
                and stored_propose_checkpoint.get("run_id") == active_run.run_id
                and stored_propose_checkpoint.get("provider") == thinker_provider
                and stored_propose_checkpoint.get("status") == "READY_TO_VALIDATE"
                and isinstance(stored_propose_attempt, dict)
                and stored_propose_attempt.get("status") == "COMPLETE"
                and stored_propose_checkpoint.get("attempt_id") == stored_propose_attempt.get("attempt_id")
            )
            propose_recovery_needed = (
                active_run.current_stage == OrchestrationStage.PROPOSING
                and not verified_propose_checkpoint
                and (stored_propose_attempt is not None or self._proposal_artifacts_any(worktree_path, change_name))
            ) or (
                active_run.current_stage == OrchestrationStage.VALIDATING
                and not complete_proposal
                and stored_propose_attempt is not None
            )
            stored_propose_gate = (active_run.stop_details or {}).get("propose_human_required")
            verified_propose_human_gate = (
                propose_recovery_needed
                and isinstance(stored_propose_gate, dict)
                and isinstance(stored_propose_attempt, dict)
                and stored_propose_gate.get("attempt_id") == stored_propose_attempt.get("attempt_id")
                and stored_propose_attempt.get("status") == "COMPLETE"
            )
            if (
                verified_propose_human_gate
                and not (isinstance(operator_clarification, str) and operator_clarification.strip())
            ):
                # A power interruption or refresh must not hide a genuine
                # human question or spend another model invocation to rediscover it.
                return OrchestrationCoordinationResult(
                    status="HUMAN_REQUIRED",
                    run_id=active_run.run_id,
                    current_stage=OrchestrationStage.PROPOSING,
                    message="Propose is awaiting an operator clarification.",
                    human_payload=self._safe_human_payload(stored_propose_gate.get("human_payload")),
                )
            if propose_recovery_needed and not propose_recovery_authorization_id:
                return OrchestrationCoordinationResult(
                    status="PAUSED",
                    run_id=active_run.run_id,
                    current_stage=OrchestrationStage.PROPOSING,
                    message="Propose recovery authorization is required before dispatch.",
                )
            existing_proposal = (
                active_run.current_stage == OrchestrationStage.VALIDATING and complete_proposal
            ) or (active_run.current_stage == OrchestrationStage.PROPOSING and verified_propose_checkpoint)
            if not existing_proposal:
                self._update_stage(uow, active_run, OrchestrationStage.PROPOSING)
                dispatch = self._prepare_propose_dispatch(
                    uow=uow,
                    run=active_run,
                    issue_number=issue_number,
                    provider=thinker_provider,
                    change_name=change_name,
                    is_recovery=propose_recovery_needed,
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
                    lambda: self._run_propose(
                        worktree_path=worktree_path,
                        provider=thinker_provider,
                        change_name=change_name,
                        issue_number=issue_number,
                        issue_title=issue_title,
                        issue_body=issue_body,
                        project_id=project_id,
                        continue_existing=propose_recovery_needed,
                        operator_clarification=(
                            operator_clarification if verified_propose_human_gate else None
                        ),
                    ),
                    lambda result: result.get("status") in {"READY_TO_VALIDATE", "HUMAN_REQUIRED"},
                )
                propose_attempt_id = dispatch[0]
                success = propose_result.get("status") == "READY_TO_VALIDATE"
                human_required = propose_result.get("status") == "HUMAN_REQUIRED"
                if success:
                        details = dict(active_run.stop_details or {})
                        details.pop("propose_human_required", None)
                        details["propose_checkpoint"] = {
                            "checkpoint_version": 1,
                            "run_id": active_run.run_id,
                            "provider": thinker_provider,
                            "status": "READY_TO_VALIDATE",
                            "attempt_id": propose_attempt_id,
                            "agent_response_sha256": hashlib.sha256(
                                propose_result["execution"].response_output.encode("utf-8")
                            ).hexdigest(),
                            "agent_handoff": (
                                {
                                    "status": propose_result["execution"].workflow_handoff.status,
                                    "summary": redact_secrets(
                                        propose_result["execution"].workflow_handoff.summary
                                    )[:600],
                                    "pending": [],
                                }
                                if getattr(propose_result["execution"], "workflow_handoff", None)
                                else None
                            ),
                            "recorded_at": utc_now().isoformat(),
                        }
                        self._persist_run_stop_details(active_run, details)
                elif human_required:
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
                correction_ok = await self._run_propose_correction(
                    worktree_path,
                    thinker_provider,
                    change_name,
                    val_res.get("stderr", ""),
                    project_id=project_id,
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
                review_ok = await self._run_proposal_review(
                    worktree_path, reviewer_provider, change_name, project_id=project_id
                )
                if not review_ok:
                    return OrchestrationCoordinationResult(
                        status="PAUSED",
                        run_id=active_run.run_id,
                        current_stage=OrchestrationStage.PROPOSAL_REVIEW,
                        message="Independent proposal review reported defects. Worktree preserved.",
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
            apply_ok = await self._run_apply(
                worktree_path, implementer_provider, change_name, project_id=project_id
            )
            if not apply_ok:
                return OrchestrationCoordinationResult(
                    status="PAUSED",
                    run_id=active_run.run_id,
                    current_stage=OrchestrationStage.IMPLEMENTING,
                    message="Native Apply failed or produced no authoritative evidence. Worktree preserved.",
                )
            self._update_stage(uow, active_run, OrchestrationStage.RUNNING_TESTS)

        if active_run.current_stage == OrchestrationStage.RUNNING_TESTS:
            tests_ok, test_evidence = await self._run_automated_tests(worktree_path)
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
            verify_ok = await self._run_verify(
                worktree_path, implementer_provider, change_name, project_id=project_id
            )
            if not verify_ok:
                return OrchestrationCoordinationResult(
                    status="PAUSED",
                    run_id=active_run.run_id,
                    current_stage=OrchestrationStage.VERIFYING,
                    message="OpenSpec verify reported discrepancies. Worktree preserved.",
                )

            # Step 9: Post-Verify Routing & Code Review
            complexity = active_run.stop_details.get("complexity", "moderate")
            if complexity == "high":
                self._update_stage(uow, active_run, OrchestrationStage.CODE_REVIEW)
                code_review_ok = await self._run_code_review(
                    worktree_path, reviewer_provider, change_name, project_id=project_id
                )
                if not code_review_ok:
                    return OrchestrationCoordinationResult(
                        status="PAUSED",
                        run_id=active_run.run_id,
                        current_stage=OrchestrationStage.CODE_REVIEW,
                        message="Independent code review requested changes. Worktree preserved.",
                    )

            self._update_stage(uow, active_run, OrchestrationStage.READY_FOR_PR)

        # Step 10: Implementation PR (PR1)
        pr1_url = active_run.stop_details.get("pr1_url")
        pr1_number = active_run.stop_details.get("pr1_number")
        complexity = active_run.stop_details.get("complexity", "moderate")
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
                current_stage=OrchestrationStage.READY_FOR_PR,
                message=f"Unable to observe candidate Git state: {exc}. Worktree preserved.",
            )
        active_run.candidate_sha = candidate_sha

        if not pr1_number:
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
            opened_data = opened_pr_res.data if hasattr(opened_pr_res, "data") else opened_pr_res
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

        # Differentiated Merge Policy for PR1
        if active_run.current_stage == OrchestrationStage.PR1_PENDING:
            if complexity == "high" and not operator_ack:
                return OrchestrationCoordinationResult(
                    status="HUMAN_REQUIRED",
                    run_id=active_run.run_id,
                    current_stage=OrchestrationStage.PR1_PENDING,
                    pr1_url=pr1_url,
                    message="High-complexity change requires operator acknowledgement («Estoy enterado») before merging PR1.",
                    human_payload={
                        "action": "operator_ack",
                        "summary_es": f"Cambio de alta complejidad para el Issue #{issue_number}: {issue_title}. PR #{pr1_number} listo para fusión.",
                        "prompt": "Por favor confirme con «Estoy enterado» para proceder a la fusión remota.",
                    },
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
            self._update_stage(uow, active_run, OrchestrationStage.PR1_MERGED)

        # Step 11: Fresh Documentation Worktree & Sync/Archive (PR2)
        self._update_stage(uow, active_run, OrchestrationStage.DOC_CLOSING)
        doc_worktree_info = await self.worktree_manager.create_documentation_worktree(
            project_id=project_id,
            issue_number=issue_number,
            issue_title=issue_title,
            base_branch=base_branch,
            run_id=active_run.run_id,
        )
        doc_path = doc_worktree_info.path

        # Run native Sync & Archive
        try:
            sync_archive_ok = await self._run_sync_and_archive(
                doc_path, thinker_provider, change_name, project_id=project_id
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
            return OrchestrationCoordinationResult(
                status="PAUSED",
                run_id=active_run.run_id,
                current_stage=OrchestrationStage.DOC_CLOSING,
                pr1_url=pr1_url,
                message="Native Sync or Archive failed. Documentation worktree preserved.",
            )
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
        opened_doc_data = opened_doc_res.data if hasattr(opened_doc_res, "data") else opened_doc_res
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

        # Admit the next FIFO request immediately after closure confirmation.
        # Admission creates only a durable ADMITTED checkpoint; a later explicit
        # request run resumes it and performs provider preflight before any agent.
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
        if (
            getattr(result, "structured_output_missing", False)
            or getattr(result, "structured_output_too_large", False)
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

    def _prepare_explore_dispatch(
        self,
        *,
        uow: Any,
        run: OrchestrationRun,
        issue_number: int,
        provider: str,
        context_sha: str,
        workflow_sha: str | None,
        is_recovery: bool,
        recovery_authorization_id: str | None = None,
    ) -> tuple[str, str, RecoveryClaimContext] | None:
        return self._prepare_native_dispatch(
            uow=uow,
            run=run,
            issue_number=issue_number,
            provider=provider,
            operation="explore",
            action_type=ExternalActionType.OPENSPEC_EXPLORE_DISPATCH,
            target_identity=f"{run.project_id}:{issue_number}:{provider}",
            request_fingerprint=context_sha,
            is_recovery=is_recovery,
            recovery_authorization_id=recovery_authorization_id,
            attempt_fields={
                "context_sha256": context_sha,
                "workflow_sha256": workflow_sha,
            },
        )

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

    def _finish_explore_dispatch(self, uow: Any, run: OrchestrationRun, attempt_id: str,
                                 action_key: str, claim_context: RecoveryClaimContext,
                                 attempt_status: str, error_message: str | None) -> None:
        self._finish_native_dispatch(
            uow, run, "explore", attempt_id, action_key, claim_context, attempt_status, error_message
        )

    def _prepare_propose_dispatch(
        self,
        *,
        uow: Any,
        run: OrchestrationRun,
        issue_number: int,
        provider: str,
        change_name: str,
        is_recovery: bool,
        recovery_authorization_id: str | None = None,
    ) -> tuple[str, str, RecoveryClaimContext] | None:
        return self._prepare_native_dispatch(
            uow=uow,
            run=run,
            issue_number=issue_number,
            provider=provider,
            operation="propose",
            action_type=ExternalActionType.OPENSPEC_EXPLORE_DISPATCH,
            target_identity=f"{run.project_id}:{issue_number}:{change_name}:{provider}",
            request_fingerprint=hashlib.sha256(
                f"{run.run_id}:{change_name}:{issue_number}:{provider}".encode()
            ).hexdigest(),
            is_recovery=is_recovery,
            recovery_authorization_id=recovery_authorization_id,
            attempt_fields={"change_name": change_name},
        )

    def _finish_propose_dispatch(self, uow: Any, run: OrchestrationRun, attempt_id: str,
                                 action_key: str, claim_context: RecoveryClaimContext,
                                 attempt_status: str, error_message: str | None) -> None:
        self._finish_native_dispatch(
            uow, run, "propose", attempt_id, action_key, claim_context, attempt_status, error_message
        )

    @staticmethod
    def _configured_provider(project: Any, role: str) -> str | None:
        profiles = getattr(project, "agent_profiles", {}) if project else {}
        raw = profiles.get(role) if isinstance(profiles, dict) else None
        if hasattr(raw, "model_dump"):
            raw = raw.model_dump()
        return str(raw.get("agent_id") or "").strip().lower() if isinstance(raw, dict) else None

    @classmethod
    def _configured_model(cls, uow: Any, project_id: str, role: str) -> str | None:
        project = uow.projects.get_by_id(project_id) if hasattr(uow, "projects") else None
        profiles = getattr(project, "agent_profiles", {}) if project else {}
        raw = profiles.get(role) if isinstance(profiles, dict) else None
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
                "human_payload": self._safe_human_payload({
                    "question": f"¿Cómo debe resolverse la ambigüedad en el Issue #{issue_number}?",
                    "options": options,
                    "agent_output": output[:1000],
                }),
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
                    "human_payload": self._safe_human_payload({
                        "question": report.pending[0],
                        "options": [],
                        "pending": list(report.pending),
                        "agent_output": report.summary,
                    }),
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
    ) -> bool:
        """Run correction pass by thinking agent on strict validation failure."""
        wf = self.agent_runner.resolve_workflow(
            worktree_path=worktree_path,
            provider=provider,
            operation="propose",
            change_name=change_name,
        )
        prompt = (
            f"OpenSpec strict CLI validation failed for change '{change_name}'.\n"
            f"Errors reported:\n{error_output}\n\n"
            f"Please correct the planning artifacts under openspec/changes/{change_name}/ so that "
            f"'openspec validate {change_name} --strict --type change' passes cleanly."
        )
        result = await self.agent_runner.run(
            worktree_path=worktree_path,
            prompt_context=prompt,
            project_id=project_id,
            role="thinker",
            provider=provider,
            workflow=wf,
        )
        return self._execution_is_successful(result)

    async def _run_proposal_review(
        self,
        worktree_path: Path,
        provider: str,
        change_name: str,
        project_id: str | None = None,
    ) -> bool:
        """Execute independent read-only proposal review for high complexity changes."""
        change_dir = worktree_path / "openspec" / "changes" / change_name
        proposal_text = (
            (change_dir / "proposal.md").read_text(errors="ignore")
            if (change_dir / "proposal.md").exists()
            else ""
        )
        prompt = (
            f"You are the independent reviewer agent (read-only). Perform independent review on OpenSpec change '{change_name}'.\n\n"
            f"Proposal Artifacts:\n{proposal_text[:3000]}\n\n"
            f"Evaluate architectural soundness, requirement coverage, and absence of overengineering.\n"
            "Emit exactly one JSON review payload matching ReviewVerdictPayload. Use verdict "
            "READY_TO_MERGE only with an empty findings list; otherwise use CHANGES_REQUIRED "
            "with concrete findings."
        )
        res = await self.agent_runner.run(
            worktree_path=worktree_path,
            prompt_context=prompt,
            project_id=project_id,
            role="reviewer",
            provider=provider,
        )
        if not self._execution_is_successful(res):
            return False
        try:
            return parse_review_verdict(res.response_output).verdict.value == "READY_TO_MERGE"
        except MalformedReviewOutputError:
            return False

    async def _run_apply(
        self,
        worktree_path: Path,
        provider: str,
        change_name: str,
        project_id: str | None = None,
    ) -> bool:
        """Dispatch configured implementer agent to execute official OpenSpec Apply workflow."""
        wf = self.agent_runner.resolve_workflow(
            worktree_path=worktree_path,
            provider=provider,
            operation="apply",
            change_name=change_name,
        )
        prompt = (
            f"You are the implementer agent. Execute official OpenSpec Apply for change '{change_name}'.\n"
            f"Workflow command: {wf.dispatch_command}\n\n"
            f"Implement all pending tasks specified in tasks.md, write unit and E2E tests, "
            f"ensure the test suite passes, and mark completed tasks as [x]."
        )
        result = await self.agent_runner.run(
            worktree_path=worktree_path,
            prompt_context=prompt,
            project_id=project_id,
            role="implementer",
            provider=provider,
            workflow=wf,
        )
        if not self._execution_is_successful(result):
            return False
        tasks_path = worktree_path / "openspec" / "changes" / change_name / "tasks.md"
        if not tasks_path.is_file():
            return False
        tasks_text = tasks_path.read_text(encoding="utf-8", errors="replace")
        # A successful CLI exit cannot replace the native Apply task postcondition.
        return not bool(re.search(r"(?m)^\s*-\s*\[\s\]\s+", tasks_text))

    async def _run_automated_tests(self, worktree_path: Path) -> tuple[bool, str]:
        """Execute project automated tests and verify exit code 0."""
        import sys

        # Use the runtime interpreter that launched mini me.  A PATH-resolved
        # pytest may belong to another environment and can produce a false
        # failure even when the candidate's declared dependencies pass.
        cmd = [sys.executable, "-m", "pytest", "-q"]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(worktree_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            evidence = stdout.decode(errors="replace") + stderr.decode(errors="replace")
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
                return False, evidence or "No tests collected (pytest code 5)."
            return False, evidence
        except (OSError, FileNotFoundError) as exc:
            logger.warning(f"Automated test runner exception: {exc}")
            return False, f"Test execution failed to launch: {exc}"

    async def _run_verify(
        self,
        worktree_path: Path,
        provider: str,
        change_name: str,
        project_id: str | None = None,
    ) -> bool:
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
        attempt_dir = worktree_path / ".minime" / "verify-attempts" / str(uuid4())
        response_path = attempt_dir / "last-message.json"
        res = await self.agent_runner.run(
            worktree_path=worktree_path,
            prompt_context=prompt,
            project_id=project_id,
            role="implementer",
            provider=provider,
            workflow=wf,
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
        if not self._execution_is_successful(res):
            return False
        if getattr(res, "structured_output_missing", False) or getattr(
            res, "structured_output_too_large", False
        ):
            return False
        try:
            return parse_review_verdict(res.response_output).verdict.value == "READY_TO_MERGE"
        except MalformedReviewOutputError:
            return False

    async def _run_code_review(
        self,
        worktree_path: Path,
        provider: str,
        change_name: str,
        project_id: str | None = None,
    ) -> bool:
        """Execute independent read-only code review for high-complexity changes."""
        diff_result = await self._git_run(worktree_path, ["diff", "HEAD~1..HEAD"])
        diff = diff_result.stdout
        prompt = (
            f"You are the independent reviewer agent (read-only). Perform code review on OpenSpec change '{change_name}'.\n\n"
            f"Candidate Diff:\n{diff[:4000]}\n\n"
            f"Evaluate implementation correctness, security, maintainability, and absence of overengineering.\n"
            "Return exactly one JSON review object with verdict READY_TO_MERGE and empty "
            "findings only on verified success, otherwise CHANGES_REQUIRED with "
            "concrete findings and required corrections. Do not use APPROVED prose."
        )
        res = await self.agent_runner.run(
            worktree_path=worktree_path,
            prompt_context=prompt,
            project_id=project_id,
            role="reviewer",
            provider=provider,
        )
        if not self._execution_is_successful(res):
            return False
        try:
            return parse_review_verdict(res.response_output).verdict.value == "READY_TO_MERGE"
        except MalformedReviewOutputError:
            return False

    async def _run_sync_and_archive(
        self,
        doc_path: Path,
        provider: str,
        change_name: str,
        project_id: str | None = None,
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

        sync_result = await self.agent_runner.run(
            worktree_path=doc_path,
            prompt_context=(
                f"Execute ONLY the official OpenSpec Sync workflow for '{change_name}'.\n"
                f"Dispatch: {sync_wf.dispatch_command}\n"
                "Return evidence of the resulting synced specs."
            ),
            project_id=project_id,
            role="thinker",
            provider=provider,
            workflow=sync_wf,
        )
        if not self._execution_is_successful(sync_result):
            return False

        archive_result = await self.agent_runner.run(
            worktree_path=doc_path,
            prompt_context=(
                f"Execute ONLY the official OpenSpec Archive workflow for '{change_name}'.\n"
                f"Dispatch: {archive_wf.dispatch_command}\n"
                "Return evidence of the resulting archive."
            ),
            project_id=project_id,
            role="thinker",
            provider=provider,
            workflow=archive_wf,
        )
        if not self._execution_is_successful(archive_result):
            return False
        archive_root = doc_path / "openspec" / "changes" / "archive"
        archived = (
            [
                p
                for p in archive_root.iterdir()
                if p.is_dir() and (p.name == change_name or p.name.endswith(f"-{change_name}"))
            ]
            if archive_root.is_dir()
            else []
        )
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
