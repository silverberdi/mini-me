"""Evidence-based diagnosis for legacy Apply checkpoints lost by a no-op Update."""

from __future__ import annotations

import hashlib
import json
from typing import Any

RECOVERY_GATE = "apply_checkpoint_recovery"
REBASELINE_RESPONSE = (
    "Autorizo usar las disposiciones actuales estrictamente validadas como nuevo baseline "
    "y reanudar Apply una sola vez en este mismo Run y candidato."
)
PRESERVE_RESPONSE = "Mantener el Run detenido y preservar el worktree."
_IDENTITY_FIELDS = ("run_id", "branch", "worktree", "generation", "candidate_sha")
_DISPOSITION_GATES = {"apply_gate_update", "physical_validation"}


def human_gate_fingerprint(run_id: str, stage: Any, payload: dict[str, Any]) -> str:
    """Match the fingerprint stored when the API accepts a response to a gate."""
    stage_value = getattr(stage, "value", stage)
    body = {
        "run_id": run_id,
        "stage": stage_value,
        "gate_id": payload.get("gate_id"),
        "gate": payload.get("gate"),
        "question": payload.get("question"),
        "options": payload.get("options"),
    }
    return hashlib.sha256(
        json.dumps(body, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def diagnose_lost_apply_checkpoint(
    run: Any,
    actions: list[Any],
    events: list[Any],
) -> dict[str, Any] | None:
    """Return a recoverable or blocked diagnosis only for the evidenced legacy sequence."""
    details = getattr(run, "stop_details", None) or {}
    persisted = details.get("apply_checkpoint_recovery") or {}
    if persisted.get("status") == "AUTHORIZED":
        return None
    if persisted.get("status") == "BLOCKED":
        return dict(persisted)
    payload = details.get("human_payload") or {}
    checkpoint = details.get("apply_gate_update") or {}
    if (
        not getattr(run, "is_active", False)
        or getattr(getattr(run, "current_stage", None), "value", getattr(run, "current_stage", None))
        != "IMPLEMENTING"
        or payload.get("gate") not in {"apply_escalation", RECOVERY_GATE}
        or checkpoint.get("status") != "VALIDATED"
        or checkpoint.get("changed") is not False
        or checkpoint.get("reclassified_tasks") != []
        or (checkpoint.get("validation") or {}).get("status") != "PASS"
    ):
        return None

    before = checkpoint.get("before") or {}
    after = checkpoint.get("after") or {}
    identity = {key: before.get(key) for key in _IDENTITY_FIELDS}
    if (
        any(value in (None, "") for value in identity.values())
        or any(before.get(key) != after.get(key) for key in _IDENTITY_FIELDS)
        or identity["run_id"] != run.run_id
        or checkpoint.get("change_name") != run.change_name
        or details.get("current_candidate_sha", run.current_candidate_sha)
        not in (None, identity["candidate_sha"])
    ):
        return _blocked(identity, "La identidad del checkpoint no coincide o está incompleta.")
    checkpoint_fingerprint = (after.get("candidate_fingerprint") or "")
    if not checkpoint_fingerprint or before.get("candidate_fingerprint") != checkpoint_fingerprint:
        return _blocked(identity, "La huella del candidato no coincide entre el inicio y el final del no-op.")

    snapshot = details.get("apply_snapshot")
    if (
        not isinstance(snapshot, dict)
        or any(snapshot.get(field) != identity[field] for field in ("run_id", "branch", "worktree"))
        or snapshot.get("sha") != identity["candidate_sha"]
    ):
        return _blocked(identity, "El Apply snapshot no acredita la misma identidad de candidato.")

    actions_by_id = {getattr(action, "action_request_id", None): action for action in actions}
    noop_action_id = checkpoint.get("operator_action_id")
    if not isinstance(noop_action_id, str):
        return _blocked(identity, "Falta la acción humana asociada al Update sin cambios.")
    noop_action = actions_by_id.get(noop_action_id)
    if not _accepted_gate_action(noop_action, run, allowed_gates={"apply_escalation"}):
        return _blocked(identity, "La acción humana del Update sin cambios no es verificable.")

    starts: dict[str, tuple[Any, dict[str, Any]]] = {}
    terminals: dict[str, tuple[Any, dict[str, Any]]] = {}
    active_attempts: set[str] = set()
    for event in events:
        evidence = getattr(event, "evidence_references", None) or {}
        claim_key = str(evidence.get("claim_key") or "")
        if not claim_key.startswith(f"stage-invocation:{run.run_id}:"):
            continue
        attempt_id = evidence.get("attempt_id")
        if not isinstance(attempt_id, str):
            continue
        if getattr(event, "event_type", None) == "STAGE_INVOCATION_STARTED":
            if _same_identity(evidence.get("candidate") or {}, identity):
                active_attempts.add(attempt_id)
            if not claim_key.startswith(f"stage-invocation:{run.run_id}:UPDATE:"):
                continue
            starts[attempt_id] = (event, evidence)
        elif getattr(event, "event_type", None) in {
            "STAGE_INVOCATION_COMPLETED", "STAGE_INVOCATION_FAILED",
            "STAGE_INVOCATION_HUMAN_REQUIRED", "STAGE_INVOCATION_ABANDONED",
        }:
            active_attempts.discard(attempt_id)
            if not claim_key.startswith(f"stage-invocation:{run.run_id}:UPDATE:"):
                continue
            terminals[attempt_id] = (event, evidence)

    if active_attempts:
        return _blocked(identity, "Hay una invocación de etapa activa para el mismo candidato.")

    matching_noops: list[tuple[Any, dict[str, Any], Any, dict[str, Any]]] = []
    matching_prior: list[tuple[Any, dict[str, Any], Any, dict[str, Any]]] = []
    for attempt_id, (start_event, start) in starts.items():
        candidate = start.get("candidate") or {}
        if not _same_identity(candidate, identity):
            continue
        terminal_pair = terminals.get(attempt_id)
        if terminal_pair is None:
            return _blocked(identity, "Hay una invocación UPDATE activa o sin cierre durable.")
        terminal_event, terminal = terminal_pair
        result = terminal.get("result") or {}
        action_id = start.get("operator_action_id")
        action = actions_by_id.get(action_id)
        if action_id == noop_action_id:
            if (
                getattr(terminal_event, "event_type", None) == "STAGE_INVOCATION_COMPLETED"
                and terminal.get("status") == "COMPLETE"
                and result.get("changed") is False
                and (result.get("validation") or {}).get("status") == "PASS"
            ):
                matching_noops.append((start_event, start, terminal_event, terminal))
        elif _accepted_gate_action(action, run, allowed_gates=_DISPOSITION_GATES):
            if (
                getattr(terminal_event, "event_type", None) == "STAGE_INVOCATION_COMPLETED"
                and terminal.get("status") == "COMPLETE"
                and result.get("changed") is True
                and (result.get("validation") or {}).get("status") == "PASS"
            ):
                matching_prior.append((start_event, start, terminal_event, terminal))

    if len(matching_noops) != 1:
        return _blocked(identity, "La invocación nativa del Update sin cambios no tiene evidencia única.")
    noop_started = matching_noops[0][0]
    prior_before_noop = [row for row in matching_prior if row[0].created_at < noop_started.created_at]
    if len(prior_before_noop) != 1:
        return _blocked(identity, "No existe una única invocación previa de Update validado con cambios.")

    prior_start, prior_evidence, prior_end, prior_result = prior_before_noop[0]
    prior_action_id = prior_evidence.get("operator_action_id")
    if not isinstance(prior_action_id, str) or prior_action_id == noop_action_id:
        return _blocked(identity, "La decisión humana previa no puede distinguirse del no-op.")

    current_dispositions = checkpoint.get("task_dispositions_after")
    if not isinstance(current_dispositions, dict) or not current_dispositions:
        return _blocked(identity, "El Update sin cambios no conserva las disposiciones actuales.")

    return {
        "status": "RECOVERABLE",
        "identity": identity,
        "candidate_fingerprint": checkpoint_fingerprint,
        "prior_snapshot": snapshot,
        "current_dispositions": current_dispositions,
        "prior_action_id": prior_action_id,
        "prior_update": _invocation_evidence(prior_start, prior_evidence, prior_end, prior_result),
        "no_op_action_id": noop_action_id,
        "no_op_update": _invocation_evidence(*matching_noops[0]),
    }


def recovery_gate_payload(run: Any, diagnosis: dict[str, Any]) -> dict[str, Any]:
    """Build a stable, evidence-linked gate projection without mutating the Run."""
    identity = diagnosis.get("identity") or {}
    evidence = {
        key: diagnosis.get(key)
        for key in (
            "candidate_fingerprint", "prior_snapshot", "current_dispositions", "prior_action_id", "prior_update",
            "no_op_action_id", "no_op_update", "reason",
        )
        if key in diagnosis
    }
    gate_id_seed = json.dumps(
        {"run_id": run.run_id, "identity": identity, "evidence": evidence},
        sort_keys=True, ensure_ascii=False, default=str,
    )
    gate_id = "apply-checkpoint-recovery-" + hashlib.sha256(gate_id_seed.encode()).hexdigest()[:20]
    if diagnosis.get("status") == "RECOVERABLE":
        question = (
            "Un Update sin cambios reemplazó el detalle de un Update anterior validado. "
            "Revisa el snapshot anterior, las disposiciones actuales y la identidad del candidato. "
            "Solo si autorizas explícitamente, se guardará el estado actual como baseline y se "
            "reanudarán una vez Apply en este mismo Run y candidato."
        )
        options = [
            {"id": "authorize_rebaseline", "label": REBASELINE_RESPONSE,
             "response_text": REBASELINE_RESPONSE},
            {"id": "preserve", "label": PRESERVE_RESPONSE,
             "response_text": PRESERVE_RESPONSE},
        ]
    else:
        question = (
            "No se puede recuperar el checkpoint de forma segura: "
            + str(diagnosis.get("reason") or "la evidencia no es suficiente o no coincide.")
            + " El Run permanece detenido; puedes preservar el worktree o usar la cancelación existente."
        )
        options = [{"id": "preserve", "label": PRESERVE_RESPONSE,
                    "response_text": PRESERVE_RESPONSE}]
    return {
        "gate_id": gate_id,
        "gate": RECOVERY_GATE,
        "stage": "IMPLEMENTING",
        "run_id": run.run_id,
        "question": question,
        "options": options,
        "explanation_es": question,
        "candidate_sha": identity.get("candidate_sha"),
        "recovery_status": diagnosis.get("status"),
        "recovery_evidence": evidence,
        "cancel_route_available": True,
    }


def _accepted_gate_action(action: Any, run: Any, *, allowed_gates: set[str]) -> bool:
    if action is None:
        return False
    action_type = getattr(getattr(action, "action_type", None), "value", getattr(action, "action_type", None))
    status = getattr(getattr(action, "status", None), "value", getattr(action, "status", None))
    return (
        getattr(action, "run_id", None) == run.run_id
        and getattr(action, "change_name", None) == run.change_name
        and action_type == "RESOLVE_GATE"
        and status == "COMPLETED"
        and getattr(action, "precondition_gate", None) in allowed_gates
        and isinstance((getattr(action, "parameters_json", None) or {}).get("accepted_response"), str)
    )


def _same_identity(candidate: dict[str, Any], identity: dict[str, Any]) -> bool:
    return all(candidate.get(key) == value for key, value in identity.items())


def _invocation_evidence(start_event: Any, start: dict[str, Any], terminal_event: Any, terminal: dict[str, Any]) -> dict[str, Any]:
    return {
        "started_event_id": getattr(start_event, "event_id", None),
        "finished_event_id": getattr(terminal_event, "event_id", None),
        "attempt_id": start.get("attempt_id"),
        "operator_action_id": start.get("operator_action_id"),
        "status": terminal.get("status"),
        "result": terminal.get("result"),
    }


def _blocked(identity: dict[str, Any], reason: str) -> dict[str, Any]:
    return {"status": "BLOCKED", "identity": identity, "reason": reason}
