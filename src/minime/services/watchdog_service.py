"""Cheap, read-only stall observations for the existing scheduler loop."""

from __future__ import annotations

import json
import hashlib
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from minime.logging import redact_secrets
from minime.domain.models import OrchestrationStageEvent
from minime.services.agent_confinement import process_identity_state


def _as_utc(value: Any) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class WatchdogObservationService:
    """Classify durable inactivity without changing orchestration state."""

    def observe(
        self,
        run: Any,
        events: list[Any],
        *,
        job_logs: list[Any] | None = None,
        threshold_minutes: int = 15,
        now: datetime | None = None,
    ) -> dict[str, Any] | None:
        if not getattr(run, "is_active", False) or getattr(run, "human_gate", None):
            return None
        now = _as_utc(now) or datetime.now(UTC)
        stage = getattr(getattr(run, "current_stage", None), "value", run.current_stage)
        terminal_types = {
            "STAGE_INVOCATION_COMPLETED",
            "STAGE_INVOCATION_HUMAN_REQUIRED",
            "STAGE_INVOCATION_FAILED",
            "STAGE_INVOCATION_ABANDONED",
        }
        starts: dict[str, Any] = {}
        process_events: dict[str, Any] = {}
        terminal: set[str] = set()
        for event in events:
            evidence = getattr(event, "evidence_references", {}) or {}
            attempt_id = str(evidence.get("attempt_id") or "")
            if event.event_type == "STAGE_INVOCATION_STARTED":
                candidate = evidence.get("candidate") or {}
                event_stage = getattr(getattr(event, "from_stage", None), "value", event.from_stage)
                if event_stage == stage or candidate.get("stage") == stage:
                    starts[attempt_id] = event
            elif event.event_type == "STAGE_INVOCATION_PROCESS_STARTED":
                process_events[attempt_id] = event
            elif event.event_type in terminal_types:
                terminal.add(attempt_id)

        pending = [
            (attempt, event)
            for attempt, event in starts.items()
            if attempt and attempt not in terminal
        ]
        process_state = "UNKNOWN"
        attempt_id = None
        started_at = None
        if len(pending) == 1:
            attempt_id, start_event = pending[0]
            started_at = _as_utc(start_event.evidence_references.get("started_at")) or _as_utc(
                start_event.created_at
            )
            process_event = process_events.get(attempt_id)
            identity = (
                (process_event.evidence_references or {}).get("process_identity")
                if process_event
                else None
            )
            if isinstance(identity, dict):
                process_state = process_identity_state(identity)
        activity_timestamps = [
            timestamp
            for timestamp in (
                *(_as_utc(event.created_at) for event in events),
                _as_utc(getattr(run, "updated_at", None)),
            )
            if timestamp is not None
        ]
        activity_timestamps.extend(
            timestamp
            for timestamp in (_as_utc(getattr(log, "timestamp", None)) for log in (job_logs or []))
            if timestamp is not None
        )
        last_activity = max(activity_timestamps, default=started_at or _as_utc(run.updated_at))
        elapsed = (now - last_activity).total_seconds() if last_activity else None
        proven_absent = bool(pending and process_state == "GONE")
        stale = elapsed is not None and elapsed >= max(1, threshold_minutes) * 60
        if not proven_absent and not stale:
            return None
        if len(pending) > 1:
            result = self._observation(
                run,
                stage,
                "ambiguous_invocations",
                "AMBIGUOUS",
                now,
                {
                    "active_invocation_count": len(pending),
                    "last_activity_at": last_activity.isoformat() if last_activity else None,
                    "inactive_seconds": max(0, int(elapsed)) if elapsed is not None else None,
                    "threshold_minutes": max(1, threshold_minutes),
                    "event_count": len(events),
                    "job_log_count": len(job_logs or []),
                },
                "Hay más de una invocación sin cierre durable; no se puede atribuir la propiedad de forma segura.",
            )
            result["affected_component"] = self._component_for_stage(stage)
            return result
        evidence = {
            "last_activity_at": last_activity.isoformat() if last_activity else None,
            "observed_at": now.isoformat(),
            "inactive_seconds": max(0, int(elapsed)) if elapsed is not None else None,
            "threshold_minutes": max(1, threshold_minutes),
            "attempt_id": attempt_id,
            "child_process_state": process_state,
            "process_absence_proven": proven_absent,
            "event_count": len(events),
            "job_log_count": len(job_logs or []),
        }
        cause = "orphaned_stage_process" if proven_absent else "no_recent_activity"
        summary = (
            "El proceso registrado para la invocación ya no existe; la recuperación debe pasar por el coordinador nativo."
            if proven_absent
            else f"No se observó actividad durable durante {evidence['inactive_seconds']} segundos."
        )
        result = self._observation(run, stage, cause, "OBSERVED", now, evidence, summary)
        result["affected_component"] = self._component_for_stage(stage)
        return result

    def observe_human_gate(self, run: Any, payload: dict[str, Any]) -> dict[str, Any] | None:
        """Prepare read-only SRE context only for technical feasibility gates."""
        if not getattr(run, "is_active", False) or payload.get("gate") != "proposal_feasibility":
            return None
        stage = getattr(getattr(run, "current_stage", None), "value", run.current_stage)
        evidence = redact_secrets({
            "gate_id": payload.get("gate_id"),
            "question": payload.get("question"),
            "options": payload.get("options"),
            "blockers": payload.get("blockers"),
            "task_feasibility": payload.get("task_feasibility"),
            "scenario_coverage": payload.get("scenario_coverage"),
            "candidate_sha": payload.get("candidate_sha"),
        })
        result = self._observation(
            run, str(stage), "proposal_feasibility_human_gate", "HUMAN_REQUIRED",
            datetime.now(UTC), evidence,
            "El gate de factibilidad requiere revisión técnica; la pregunta y opciones originales siguen bajo autoridad del operador.",
        )
        result["trigger"] = "proposal_feasibility_human_gate"
        return result

    @staticmethod
    def record_intervention_event(
        uow: Any, run: Any, *, event_type: str, transition_key: str, evidence: dict[str, Any]
    ) -> bool:
        """Append one idempotent intervention fact without mutating prior events."""
        repository = getattr(uow, "orchestration_stage_events", None)
        if repository is None or not callable(getattr(repository, "save", None)):
            return False
        get_by_key = getattr(repository, "get_by_transition_key", None)
        if callable(get_by_key) and get_by_key(transition_key) is not None:
            return False
        stage = getattr(run, "current_stage", None)
        repository.save(OrchestrationStageEvent(
            run_id=run.run_id,
            from_stage=stage,
            to_stage=stage,
            event_type=event_type,
            transition_key=transition_key,
            actor="sre_unblocker",
            evidence_references=redact_secrets({
                "project_id": run.project_id,
                "run_id": run.run_id,
                "stage": getattr(stage, "value", stage),
                "candidate_sha": getattr(run, "current_candidate_sha", None),
                **evidence,
            }),
        ))
        return True

    @staticmethod
    def has_prior_sre_pattern(watchdog_repository: Any, diagnosis: dict[str, Any]) -> bool:
        """Find a prior supported diagnosis without requiring a seed row."""
        list_diagnoses = getattr(watchdog_repository, "list_diagnoses", None)
        if not callable(list_diagnoses):
            return False
        prior = list_diagnoses(project_id=diagnosis.get("project_id"), limit=200)
        current_evidence = diagnosis.get("evidence") or {}
        current_key = current_evidence.get("sre_intervention_transition_key")
        current_identity = current_evidence.get("event_identity")
        for item in prior:
            if item.get("run_id") == diagnosis.get("run_id"):
                continue
            if (
                item.get("root_cause") != diagnosis.get("root_cause")
                or item.get("affected_component") != diagnosis.get("affected_component")
            ):
                continue
            evidence = item.get("evidence") or {}
            prior_key = evidence.get("sre_intervention_transition_key")
            prior_identity = evidence.get("event_identity")
            if current_key and prior_key == current_key:
                return True
            if current_identity and prior_identity == current_identity:
                return True
            # Keep compatibility with older persisted rows that predate the
            # explicit event identity while requiring a linked intervention.
            if not current_key and not current_identity and prior_key:
                return True
        return False

    @staticmethod
    def has_persisted_event(watchdog_repository: Any, diagnosis: dict[str, Any]) -> bool:
        """Deduplicate retries by the immutable event identity, not by its run slot."""
        evidence = diagnosis.get("evidence") or {}
        event_identity = diagnosis.get("event_identity") or evidence.get("event_identity")
        if not event_identity:
            return False
        get_by_event_identity = getattr(watchdog_repository, "get_by_event_identity", None)
        if callable(get_by_event_identity):
            return get_by_event_identity(event_identity) is not None
        list_diagnoses = getattr(watchdog_repository, "list_diagnoses", None)
        if not callable(list_diagnoses):
            return False
        return any(
            (item.get("event_identity") or (item.get("evidence") or {}).get("event_identity"))
            == event_identity
            for item in list_diagnoses(project_id=diagnosis.get("project_id"), limit=200)
        )

    @staticmethod
    def _component_for_stage(stage: Any) -> str:
        return {
            "EXPLORING": "exploration",
            "PROPOSING": "proposal",
            "IMPLEMENTING": "apply",
            "APPLY": "apply",
            "RUNNING_TESTS": "verification",
            "VERIFYING": "verification",
            "CODE_REVIEW": "independent_review",
            "READY_FOR_PR": "pull_request",
            "DOC_CLOSING": "openspec_closure",
        }.get(str(stage).upper(), "orchestration")

    async def add_semantic_diagnosis(
        self,
        observation: dict[str, Any],
        settings: dict[str, Any],
        *,
        worktree_path: str | Path | None,
        human_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Ask only the explicitly selected model to explain an already observed stall."""
        selection = (
            settings.get("provider_id"),
            settings.get("harness_id"),
            settings.get("canonical_model_id"),
        )
        if not all(selection):
            observation["evidence"]["semantic_model_status"] = "NOT_CONFIGURED"
            return observation
        if not worktree_path or not Path(worktree_path).is_dir():
            observation["evidence"]["semantic_model_status"] = "WORKTREE_UNAVAILABLE"
            return observation
        try:
            from minime.config import load_config, resolve_cli_invocation
            from minime.services.agent_runner import CliAgentRunner

            provider_id, harness_id, model_id = selection
            profile = resolve_cli_invocation(
                str(harness_id), "thinking", config=load_config(), model=str(model_id)
            )
            profile = replace(
                profile,
                canonical_provider_id=str(provider_id),
                harness_id=str(harness_id),
            )
            observation["evidence"].update({
                "semantic_model_provider_id": str(provider_id),
                "semantic_model_harness_id": str(harness_id),
                "semantic_model_id": str(model_id),
            })
            runner = CliAgentRunner(invocation=profile)
            prompt = (
                "Usa la skill canónica minime-sre-unblocker disponible en este worktree para diagnosticar "
                "este bloqueo. La skill limita las acciones a playbooks probados y preserva las decisiones "
                "humanas. En esta invocación eres diagnóstico: no respondas gates, no cambies archivos ni "
                "reintentes operaciones. Devuelve causa, playbook aplicable (A, B, C o ninguno), evidencia "
                "concreta, acción segura recomendada y cualquier incertidumbre. Si la evidencia no basta, "
                "dilo explícitamente. La pregunta y opciones originales se incluyen como evidencia; no las "
                "parafrasees ni sustituyas.\n"
                + json.dumps(
                    {
                        "project_id": observation["project_id"],
                        "run_id": observation["run_id"],
                        "change_name": observation["change_name"],
                        "stage": observation["stage"],
                        "candidate_sha": observation.get("candidate_sha"),
                        "root_cause_observed": observation["root_cause"],
                        "evidence": observation["evidence"],
                        "original_human_payload": human_payload,
                        "skill": "minime-sre-unblocker",
                    },
                    ensure_ascii=False,
                )
            )
            result = await runner.run(
                worktree_path=Path(worktree_path),
                prompt_context=prompt,
                timeout_seconds=90,
                project_id=str(observation["project_id"]),
                role="thinker",
                provider=str(harness_id),
                run_id=str(observation["run_id"]),
            )
            if (
                result.exit_code == 0
                and result.final_response_status == "COMPLETE"
                and result.final_response
            ):
                answer = redact_secrets(result.final_response).strip()[:4000]
                observation["evidence"]["semantic_model_status"] = "COMPLETED"
                observation["evidence"]["semantic_analysis"] = answer
                observation["improvement_suggestion"] = answer
            else:
                observation["evidence"]["semantic_model_status"] = "UNAVAILABLE"
                observation["evidence"].update({
                    "semantic_model_exit_code": result.exit_code,
                    "semantic_model_timed_out": bool(result.timed_out),
                    "semantic_model_final_response_status": result.final_response_status,
                    "semantic_model_provider_used": result.provider_used,
                    "semantic_model_profile_used": result.profile_used,
                    "semantic_model_model_used": result.model_used,
                    "semantic_model_final_response_source": result.final_response_source,
                    "semantic_model_stdout_line_count": len(result.stdout or []),
                    "semantic_model_stderr_line_count": len(result.stderr or []),
                    "semantic_model_output_truncated": bool(result.output_truncated),
                })
        except Exception as exc:
            observation["evidence"]["semantic_model_status"] = "UNAVAILABLE"
            observation["evidence"]["semantic_model_error"] = redact_secrets(type(exc).__name__)
        return observation

    @staticmethod
    def _observation(
        run: Any,
        stage: str,
        root_cause: str,
        status: str,
        now: datetime,
        evidence: dict[str, Any],
        summary: str | None = None,
    ) -> dict[str, Any]:
        candidate_sha = getattr(run, "current_candidate_sha", None)
        candidate_generation = int(getattr(run, "current_generation", 1) or 1)
        event_identity = hashlib.sha256(
            json.dumps(
                {
                    "run_id": run.run_id,
                    "stage": str(stage),
                    "candidate_sha": candidate_sha,
                    "candidate_generation": candidate_generation,
                    "attempt_id": evidence.get("attempt_id"),
                    "gate_id": evidence.get("gate_id"),
                    "root_cause": root_cause,
                },
                sort_keys=True,
                ensure_ascii=False,
            ).encode()
        ).hexdigest()
        evidence = {**evidence, "event_identity": event_identity}
        return {
            "project_id": run.project_id,
            "run_id": run.run_id,
            "change_name": run.change_name,
            "stage": str(stage),
            "candidate_sha": candidate_sha,
            "candidate_generation": candidate_generation,
            "status": status,
            "root_cause": root_cause,
            "affected_component": WatchdogObservationService._component_for_stage(stage),
            "summary": summary
            or "Hay evidencia concurrente o incompleta; no se ejecutó ninguna remediación.",
            "evidence": redact_secrets(evidence),
            "action": None,
            "action_result": {"status": "NOT_ATTEMPTED"},
            "improvement_suggestion": None,
        }
