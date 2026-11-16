"""Evidence collection and structural validation for proposal executability."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from minime.services.agent_runner import NativeOpenSpecWorkflowUnavailable
from minime.services.openspec_tasks import OpenSpecTaskTracker


class ProposalFeasibilityEvaluator:
    """Read current capability evidence and validate a thinking-agent report."""

    STAGE_ORDER = {
        "apply": 0,
        "verify": 1,
        "pre_pr": 2,
        "post_merge": 3,
        "human_validation": 4,
    }

    def __init__(self, openspec_adapter: Any, agent_runner: Any) -> None:
        self.openspec_adapter = openspec_adapter
        self.agent_runner = agent_runner

    def collect_inputs(
        self,
        *,
        worktree_path: Path,
        change_name: str,
        project: Any,
        candidate_sha: str,
        candidate_clean: bool,
        preview_sessions: Any,
        thinker_provider: str,
        implementer_provider: str,
    ) -> dict[str, Any]:
        """Collect task/scenario facts and capabilities observable for this candidate."""
        if not re.fullmatch(r"[0-9a-f]{40,64}", candidate_sha, re.IGNORECASE):
            return {"status": "UNKNOWN", "reason": "candidate SHA is unavailable or malformed"}
        openspec_path = str(getattr(project, "openspec_path", "openspec") or "openspec")
        tasks = OpenSpecTaskTracker(worktree_path).parse_tasks(openspec_path, change_name)
        show_change = getattr(self.openspec_adapter, "show_change", None)
        native_change = show_change(change_name, worktree_path) if callable(show_change) else None
        if not isinstance(native_change, dict):
            return {"status": "UNKNOWN", "reason": "native OpenSpec show could not read the Change"}

        scenarios: list[dict[str, str]] = []
        deltas = native_change.get("deltas")
        if not isinstance(deltas, list) or not deltas:
            return {"status": "UNKNOWN", "reason": "native OpenSpec show returned no validated deltas"}
        spec_requirement_counters: dict[str, int] = {}
        for delta in deltas:
            if not isinstance(delta, dict):
                continue
            spec_name = str(delta.get("spec") or "").strip()
            requirements = delta.get("requirements")
            if not spec_name or not isinstance(requirements, list):
                continue
            for requirement in requirements:
                if not isinstance(requirement, dict):
                    continue
                raw_id = requirement.get("id")
                if raw_id is not None and str(raw_id).strip():
                    requirement_id = str(raw_id).strip()
                else:
                    spec_requirement_counters[spec_name] = (
                        spec_requirement_counters.get(spec_name, 0) + 1
                    )
                    requirement_id = str(spec_requirement_counters[spec_name])
                for scenario_index, scenario in enumerate(requirement.get("scenarios") or (), start=1):
                    if isinstance(scenario, dict) and isinstance(scenario.get("rawText"), str):
                        scenarios.append(
                            {
                                "scenario_id": f"{spec_name}:{requirement_id}:{scenario_index}",
                                "text": scenario["rawText"],
                            }
                        )
        if not tasks or not scenarios:
            return {
                "status": "UNKNOWN",
                "reason": "native task or acceptance-scenario inventory is incomplete",
                "task_ids": [task.task_id for task in tasks],
                "scenario_ids": [scenario["scenario_id"] for scenario in scenarios],
            }

        capabilities: list[dict[str, Any]] = []
        profiles = getattr(project, "agent_profiles", {}) if project else {}
        if not isinstance(profiles, dict):
            profiles = {}
        role_provider = {"thinking": thinker_provider, "execution": implementer_provider}
        for role, operation in (
            ("thinking", "propose"),
            ("execution", "apply"),
            ("execution", "verify"),
        ):
            raw_profile = profiles.get(role)
            if hasattr(raw_profile, "model_dump"):
                raw_profile = raw_profile.model_dump()
            profile_present = isinstance(raw_profile, dict) and bool(
                str(raw_profile.get("agent_id") or raw_profile.get("harness_id") or "").strip()
            )
            provider = (
                str(raw_profile.get("agent_id") or raw_profile.get("harness_id") or "").strip()
                if profile_present
                else ""
            )
            capabilities.append(
                {
                    "ref": f"profile:{role}",
                    "kind": "configured_profile",
                    "available": profile_present,
                    "agent_id": provider if profile_present else None,
                    "provider_id": str(raw_profile.get("provider_id") or "") if profile_present else None,
                    "model_id": str(raw_profile.get("model_id") or "") if profile_present else None,
                }
            )
            selected_provider = str(role_provider.get(role) or "").strip().lower()
            configured_provider = provider.lower()
            selected_provider = "antigravity" if selected_provider == "agy" else selected_provider
            configured_provider = "antigravity" if configured_provider == "agy" else configured_provider
            workflow_available = False
            if provider and selected_provider == configured_provider:
                try:
                    self.agent_runner.resolve_workflow(
                        worktree_path=worktree_path,
                        provider=provider,
                        operation=operation,
                        change_name=change_name,
                    )
                    workflow_available = True
                except (NativeOpenSpecWorkflowUnavailable, OSError, ValueError):
                    workflow_available = False
            capabilities.append(
                {
                    "ref": f"workflow:{role}:{operation}",
                    "kind": "installed_native_workflow",
                    "available": workflow_available,
                }
            )

        # The single-operator installation can present a human gate. This does
        # not claim that an external participant has been recruited or that
        # human validation has already happened.
        capabilities.append(
            {
                "ref": "operator:confirmed",
                "kind": "operator_interaction",
                "available": True,
            }
        )

        planning_status = getattr(self.openspec_adapter, "planning_status", None)
        planning_res = planning_status(change_name, worktree_path) if callable(planning_status) else None
        planning_complete = isinstance(planning_res, dict) and planning_res.get("status") == "PASS"
        capabilities.append(
            {
                "ref": "openspec:status:planning_complete",
                "kind": "openspec_planning_status",
                "available": planning_complete,
            }
        )

        validate_strict = getattr(self.openspec_adapter, "validate_change_strict", None)
        val_res = validate_strict(change_name, worktree_path) if callable(validate_strict) else None
        validation_valid = isinstance(val_res, dict) and val_res.get("status") == "PASS"
        capabilities.append(
            {
                "ref": "openspec:validate:valid",
                "kind": "openspec_validation_status",
                "available": validation_valid,
            }
        )

        preview = None
        if preview_sessions:
            try:
                preview = preview_sessions.get_latest_for_candidate(
                    str(getattr(project, "project_id", "")), change_name, candidate_sha
                )
            except Exception:
                preview = None
        preview_status = getattr(getattr(preview, "status", None), "value", getattr(preview, "status", None))
        preview_ready = bool(
            preview
            and candidate_clean
            and str(getattr(preview, "head_sha", "")).lower() == candidate_sha.lower()
            and str(preview_status).upper() in {"READY", "RUNNING"}
            and getattr(preview, "preview_url", None)
        )
        capabilities.append(
            {
                "ref": f"preview:{candidate_sha}",
                "kind": "candidate_sha_matched_preview",
                "available": preview_ready,
                "preview_id": getattr(preview, "preview_id", None) if preview_ready else None,
                "candidate_clean": candidate_clean,
            }
        )
        available = {
            str(item.get("ref"))
            for item in capabilities
            if isinstance(item, dict) and item.get("available") is True
        }
        mandatory_blockers = [
            f"Required capability {ref} is unavailable in this project/worktree."
            for ref in (
                "profile:thinking",
                "workflow:thinking:propose",
                "profile:execution",
                "workflow:execution:apply",
                "workflow:execution:verify",
            )
            if ref not in available
        ]
        return {
            "status": "READY",
            "candidate_sha": candidate_sha,
            "tasks": [{"task_id": task.task_id, "text": task.text} for task in tasks],
            "scenarios": scenarios,
            "capabilities": capabilities,
            "mandatory_blockers": mandatory_blockers,
        }

    @staticmethod
    def verified_evidence_refs(
        refs: list[str], available_refs: set[str], worktree_path: Path
    ) -> tuple[set[str], set[str]]:
        verified = set(refs) & available_refs
        unknown = set(refs) - available_refs
        for ref in tuple(unknown):
            if ref.startswith("path:"):
                relative = Path(ref[5:])
                candidate_path = (worktree_path / relative).resolve()
                try:
                    candidate_path.relative_to(worktree_path.resolve())
                    safe_relative = not relative.is_absolute() and ".." not in relative.parts
                except ValueError:
                    safe_relative = False
                has_symlink = any(
                    (worktree_path / Path(*relative.parts[:index])).is_symlink()
                    for index in range(1, len(relative.parts) + 1)
                )
                if safe_relative and not has_symlink and candidate_path.is_file():
                    verified.add(ref)
                    unknown.remove(ref)
            elif re.fullmatch(
                r"^openspec(?:\s+|:)\s*status(?:\s*:\s*|\s+)(?:planning[\s_]+(?:artifacts[\s_]+)?complete)$",
                ref.strip(),
                re.IGNORECASE,
            ):
                if "openspec:status:planning_complete" in available_refs:
                    verified.add(ref)
                    unknown.remove(ref)
            elif re.fullmatch(
                r"^openspec(?:\s+|:)\s*validate(?:\s*:\s*|\s+)(?:(?:change[\s_]+is[\s_]+)?valid)$",
                ref.strip(),
                re.IGNORECASE,
            ):
                if "openspec:validate:valid" in available_refs:
                    verified.add(ref)
                    unknown.remove(ref)
        return verified, unknown

    @classmethod
    def validate_report(
        cls, report: Any, inputs: dict[str, Any], worktree_path: Path
    ) -> tuple[str, tuple[dict[str, Any], ...], tuple[dict[str, Any], ...], tuple[str, ...], tuple[str, ...]]:
        if not isinstance(report, dict) or inputs.get("status") != "READY":
            return "BLOCKED", (), (), (str(inputs.get("reason") or "feasibility evidence unavailable"),), ()
        blockers = [
            str(item)[:500]
            for item in inputs.get("mandatory_blockers", [])
            if isinstance(item, str) and item.strip()
        ]
        available_refs = {
            str(item.get("ref"))
            for item in inputs.get("capabilities", [])
            if isinstance(item, dict) and item.get("available") is True
        }
        known_refs = {
            str(item.get("ref"))
            for item in inputs.get("capabilities", [])
            if isinstance(item, dict)
        }
        expected_tasks = {str(item["task_id"]) for item in inputs.get("tasks", [])}
        expected_scenarios = {str(item["scenario_id"]) for item in inputs.get("scenarios", [])}
        task_rows = report.get("tasks") if isinstance(report.get("tasks"), list) else []
        scenario_rows = report.get("scenario_coverage") if isinstance(report.get("scenario_coverage"), list) else []
        if not isinstance(report.get("tasks"), list):
            blockers.append("assessment omitted the OpenSpec task inventory")
        if not isinstance(report.get("scenario_coverage"), list):
            blockers.append("assessment omitted acceptance-scenario coverage")
        role_refs = {
            "thinking": {"profile:thinking", "workflow:thinking:propose"},
            "execution": {"profile:execution", "workflow:execution:apply"},
            "operator": {"operator:confirmed"},
            "project_ci_cd": set(),
            "external": {"external:confirmed"},
        }
        seen_tasks: set[str] = set()
        validated_tasks: list[dict[str, Any]] = []
        for item in task_rows:
            if not isinstance(item, dict):
                blockers.append("assessment contains a malformed task entry")
                continue
            task_id = str(item.get("task_id") or "")
            if not task_id or task_id not in expected_tasks or task_id in seen_tasks:
                blockers.append(f"task entry has unknown or duplicate ID: {task_id or '(empty)'}")
                continue
            seen_tasks.add(task_id)
            actor = str(item.get("actor") or "")
            execution_stage = str(item.get("execution_stage") or "")
            if execution_stage not in cls.STAGE_ORDER:
                blockers.append(f"task {task_id} has an unknown or missing execution stage")
            is_apply_task = execution_stage == "apply"
            refs = [str(ref) for ref in item.get("capability_evidence_refs", [])] if isinstance(item.get("capability_evidence_refs"), list) else []
            task_capability_refs = list(refs)
            verified_refs, unknown_refs = cls.verified_evidence_refs(refs, available_refs, worktree_path)
            # A known capability that is not available yet may belong to a
            # later stage. Unknown references and invalid paths remain blockers.
            unregistered_refs = {ref for ref in unknown_refs if ref not in known_refs}
            if actor not in role_refs:
                blockers.append(f"task {task_id} names an unsupported responsible actor")
            elif actor == "project_ci_cd":
                workflow_paths = {
                    ref for ref in verified_refs
                    if ref.startswith("path:.github/workflows/")
                }
                if is_apply_task:
                    blockers.append(f"task {task_id} assigns Apply work to project CI/CD")
                elif not workflow_paths:
                    blockers.append(f"task {task_id} has no verified project CI/CD workflow path")
            elif actor == "external":
                if not role_refs[actor].issubset(set(refs)) or not role_refs[actor].issubset(verified_refs):
                    blockers.append(f"task {task_id} has no confirmed external participant or capability path")
            elif is_apply_task:
                if unknown_refs:
                    blockers.append(f"task {task_id} cites unavailable capability evidence: {', '.join(sorted(unknown_refs))}")
                if not role_refs[actor].issubset(verified_refs):
                    blockers.append(f"task {task_id} lacks the required verified capability for actor {actor}")
            elif actor in {"thinking", "execution", "operator"}:
                if not role_refs[actor].issubset(available_refs):
                    blockers.append(f"task {task_id} has no authorized capability path for actor {actor}")
                if unregistered_refs:
                    blockers.append(f"task {task_id} cites unknown capability evidence: {', '.join(sorted(unregistered_refs))}")
            preconditions = item.get("preconditions")
            if not isinstance(preconditions, list):
                blockers.append(f"task {task_id} has no structured precondition assessment")
                preconditions = []
            validated_preconditions: list[dict[str, Any]] = []
            for precondition in preconditions:
                if not isinstance(precondition, dict):
                    blockers.append(f"task {task_id} has a malformed precondition assessment")
                    continue
                required_before_stage = str(precondition.get("required_before_stage") or "")
                if required_before_stage not in cls.STAGE_ORDER:
                    blockers.append(f"task {task_id} has a precondition with an unknown required stage")
                    continue
                if execution_stage in cls.STAGE_ORDER and cls.STAGE_ORDER[required_before_stage] > cls.STAGE_ORDER[execution_stage]:
                    blockers.append(f"task {task_id} has a dependency scheduled after its execution stage")
                required_before_apply = cls.STAGE_ORDER[required_before_stage] <= cls.STAGE_ORDER["apply"]
                satisfied = precondition.get("satisfied") is True
                evidence_refs = [str(ref) for ref in precondition.get("evidence_refs", [])] if isinstance(precondition.get("evidence_refs"), list) else []
                verified_evidence, unknown_evidence = cls.verified_evidence_refs(
                    evidence_refs, available_refs, worktree_path
                )
                if required_before_apply and not satisfied:
                    blockers.append(f"task {task_id} has an unmet or unknown precondition required before Apply")
                if required_before_apply and (not evidence_refs or unknown_evidence):
                    details = f": {', '.join(sorted(unknown_evidence))}" if unknown_evidence else ""
                    blockers.append(f"task {task_id} has unverified precondition evidence required before Apply{details}")
                validated_preconditions.append(
                    {
                        "required_before_stage": required_before_stage,
                        "satisfied": satisfied if required_before_apply else False,
                        "status": (
                            "SATISFIED"
                            if required_before_apply and satisfied and not unknown_evidence
                            else "PENDING"
                        ),
                        "evidence_refs": sorted(evidence_refs),
                    }
                )
            completion_evidence = str(item.get("completion_evidence") or "")
            if not completion_evidence.strip():
                blockers.append(f"task {task_id} has no observable completion evidence")
            validated_tasks.append(
                {
                    "task_id": task_id,
                    "source_text_sha256": hashlib.sha256(
                        str(next(
                            task.get("text", "")
                            for task in inputs.get("tasks", [])
                            if str(task.get("task_id")) == task_id
                        )).encode("utf-8")
                    ).hexdigest(),
                    "actor": actor,
                    "execution_stage": execution_stage,
                    "capability_evidence_refs": task_capability_refs,
                    "depends_on_task_ids": [str(value) for value in item.get("depends_on_task_ids", [])]
                    if isinstance(item.get("depends_on_task_ids"), list) else [],
                    "preconditions": validated_preconditions,
                    "completion_evidence": completion_evidence,
                }
            )
        if seen_tasks != expected_tasks:
            blockers.append("assessment task IDs do not exactly cover native tasks")
        task_stages = {
            str(item.get("task_id")): str(item.get("execution_stage"))
            for item in validated_tasks
        }
        for item in validated_tasks:
            task_id = str(item.get("task_id"))
            dependencies = item.get("depends_on_task_ids", [])
            if len(dependencies) != len(set(dependencies)):
                blockers.append(f"task {task_id} repeats a task dependency")
            for dependency_id in dependencies:
                dependency_stage = task_stages.get(dependency_id)
                if dependency_id == task_id or dependency_stage is None:
                    blockers.append(f"task {task_id} depends on an unknown or self-referential task")
                elif (
                    dependency_stage in cls.STAGE_ORDER
                    and item.get("execution_stage") in cls.STAGE_ORDER
                    and cls.STAGE_ORDER[dependency_stage] > cls.STAGE_ORDER[item["execution_stage"]]
                ):
                    blockers.append(f"task {task_id} depends on work scheduled for a later stage")

        seen_scenarios: set[str] = set()
        validated_scenarios: list[dict[str, Any]] = []
        for item in scenario_rows:
            if not isinstance(item, dict):
                blockers.append("assessment contains malformed scenario coverage")
                continue
            scenario_id = str(item.get("scenario_id") or "")
            task_ids = [str(task_id) for task_id in item.get("task_ids", [])] if isinstance(item.get("task_ids"), list) else []
            evidence_stage = str(item.get("evidence_stage") or "")
            if not scenario_id or scenario_id not in expected_scenarios or scenario_id in seen_scenarios:
                blockers.append(f"scenario entry has unknown or duplicate ID: {scenario_id or '(empty)'}")
                continue
            seen_scenarios.add(scenario_id)
            if evidence_stage not in cls.STAGE_ORDER:
                blockers.append(f"scenario {scenario_id} has an unknown or missing evidence stage")
            if not task_ids or not set(task_ids).issubset(expected_tasks):
                blockers.append(f"scenario {scenario_id} maps to no known OpenSpec task")
            elif evidence_stage in cls.STAGE_ORDER and any(
                task_stages.get(task_id) in cls.STAGE_ORDER
                and cls.STAGE_ORDER[task_stages[task_id]] > cls.STAGE_ORDER[evidence_stage]
                for task_id in task_ids
            ):
                blockers.append(f"scenario {scenario_id} claims evidence before its mapped task stage")
            validated_scenarios.append(
                {
                    "scenario_id": scenario_id,
                    "source_text_sha256": hashlib.sha256(
                        str(next(
                            scenario.get("text", "")
                            for scenario in inputs.get("scenarios", [])
                            if str(scenario.get("scenario_id")) == scenario_id
                        )).encode("utf-8")
                    ).hexdigest(),
                    "task_ids": task_ids,
                    "evidence_stage": evidence_stage,
                }
            )
        if seen_scenarios != expected_scenarios:
            blockers.append("assessment scenario IDs do not exactly cover native scenarios")
        for reported in report.get("blockers", []) if isinstance(report.get("blockers"), list) else []:
            if isinstance(reported, str) and reported.strip():
                blockers.append(reported.strip()[:500])
        actions = report.get("resolution_options")
        validated_actions = tuple(
            action.strip()[:300]
            for action in actions[:5]
            if isinstance(action, str) and action.strip()
        ) if isinstance(actions, list) else ()
        if blockers and not validated_actions:
            validated_actions = (
                "Actualizar la solicitud mediante el flujo nativo OpenSpec Update y validarla de nuevo",
                "Aportar evidencia verificable de la capacidad o precondición que falta",
            )
        return (
            "EXECUTABLE" if not blockers else "BLOCKED",
            tuple(validated_tasks),
            tuple(validated_scenarios),
            tuple(dict.fromkeys(blockers)),
            validated_actions,
        )

    @classmethod
    def blockers_before_stage(
        cls,
        task_feasibility: list[dict[str, Any]] | tuple[dict[str, Any], ...],
        *,
        stage: str,
        inputs: dict[str, Any],
        worktree_path: Path,
    ) -> tuple[str, ...]:
        """Check only the deferred prerequisites consumed by this stage."""
        if stage not in cls.STAGE_ORDER or inputs.get("status") != "READY":
            return (str(inputs.get("reason") or f"capability evidence for {stage} is unavailable"),)
        available_refs = {
            str(item.get("ref"))
            for item in inputs.get("capabilities", [])
            if isinstance(item, dict) and item.get("available") is True
        }
        current_preview = next(
            (ref for ref in available_refs if ref.startswith("preview:")), None
        )
        blockers: list[str] = []
        for task in task_feasibility:
            task_id = str(task.get("task_id") or "unknown")
            actor = str(task.get("actor") or "unknown")
            if task.get("execution_stage") == stage:
                capability_refs = [
                    str(ref) for ref in task.get("capability_evidence_refs", [])
                ]
                verified_capabilities, unknown_capabilities = cls.verified_evidence_refs(
                    capability_refs, available_refs, worktree_path
                )
                missing_capabilities = unknown_capabilities | (
                    set(capability_refs) - verified_capabilities
                )
                if missing_capabilities:
                    blockers.append(
                        f"task {task_id} (actor {actor}) lacks verified stage capability before {stage}: "
                        + ", ".join(sorted(missing_capabilities))
                    )
            for precondition in task.get("preconditions", []):
                if not isinstance(precondition, dict) or precondition.get("required_before_stage") != stage:
                    continue
                refs = [str(ref) for ref in precondition.get("evidence_refs", [])]
                if not refs:
                    blockers.append(f"task {task_id} has no evidence reference for its {stage} dependency")
                    continue
                stage_refs: list[str] = []
                for ref in refs:
                    # Preview evidence is candidate-specific. The initial
                    # assessment may contain the pre-Apply SHA; resolve the
                    # same capability kind against the candidate at this stage.
                    stage_refs.append(current_preview if ref.startswith("preview:") and current_preview else ref)
                verified, unknown = cls.verified_evidence_refs(stage_refs, available_refs, worktree_path)
                if unknown or len(verified) != len(set(stage_refs)):
                    blockers.append(
                        f"task {task_id} (actor {actor}) still lacks "
                        f"verified evidence required before {stage}: "
                        + ", ".join(sorted(unknown or (set(stage_refs) - verified)))
                    )
        return tuple(dict.fromkeys(blockers))

    @staticmethod
    def output_schema() -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "complexity": {"type": ["string", "null"], "enum": ["low", "moderate", "high", None]},
                "evidence": {"type": "string", "minLength": 1},
                "feasibility": {
                    "type": "object",
                    "properties": {
                        "tasks": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "task_id": {"type": "string"},
                                    "actor": {"type": "string", "enum": ["thinking", "execution", "operator", "project_ci_cd", "external"]},
                                    "execution_stage": {"type": "string", "enum": list(ProposalFeasibilityEvaluator.STAGE_ORDER)},
                                    "capability_evidence_refs": {
                                        "type": "array",
                                        "description": "Exact ref values from the supplied capabilities inventory; do not use descriptive prose or unprefixed paths.",
                                        "items": {"type": "string"},
                                    },
                                    "depends_on_task_ids": {"type": "array", "items": {"type": "string"}},
                                    "preconditions": {
                                        "type": "array",
                                        "items": {
                                            "type": "object",
                                            "properties": {
                                                "required_before_stage": {"type": "string", "enum": list(ProposalFeasibilityEvaluator.STAGE_ORDER)},
                                                "satisfied": {"type": "boolean"},
                                                "evidence_refs": {
                                                    "type": "array",
                                                    "description": "Use exact capability refs from the supplied inventory or path:<repo-relative-path> for an existing candidate file. Never cite outputs created by Apply as preconditions.",
                                                    "items": {"type": "string"},
                                                },
                                            },
                                            "required": ["required_before_stage", "satisfied", "evidence_refs"],
                                            "additionalProperties": False,
                                        },
                                    },
                                    "completion_evidence": {"type": "string"},
                                },
                                "required": ["task_id", "actor", "execution_stage", "capability_evidence_refs", "depends_on_task_ids", "preconditions", "completion_evidence"],
                                "additionalProperties": False,
                            },
                        },
                        "scenario_coverage": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "scenario_id": {"type": "string"},
                                    "task_ids": {"type": "array", "items": {"type": "string"}},
                                    "evidence_stage": {"type": "string", "enum": list(ProposalFeasibilityEvaluator.STAGE_ORDER)},
                                },
                                "required": ["scenario_id", "task_ids", "evidence_stage"],
                                "additionalProperties": False,
                            },
                        },
                        "blockers": {"type": "array", "items": {"type": "string"}},
                        "resolution_options": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["tasks", "scenario_coverage", "blockers", "resolution_options"],
                    "additionalProperties": False,
                },
            },
            "required": ["complexity", "evidence", "feasibility"],
            "additionalProperties": False,
        }
