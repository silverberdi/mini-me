"""Focused regression coverage for the F3 audit corrections."""

import hashlib
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from minime.services.agent_runner import AgentExecutionResult
from minime.services.orchestration_coordinator import ApplyOutcome, NativeOrchestrationCoordinator
from minime.services.proposal_feasibility import ProposalFeasibilityEvaluator


class ScriptedRunner:
    def __init__(self, output: str, exit_code: int = 0) -> None:
        self.output = output
        self.exit_code = exit_code
        self.calls: list[str] = []

    def resolve_workflow(self, worktree_path, provider, operation, change_name):
        return SimpleNamespace(dispatch_command=f"native-{operation}")

    async def run(self, *, prompt_context, **kwargs):
        self.calls.append(prompt_context)
        return AgentExecutionResult(
            exit_code=self.exit_code,
            timed_out=False,
            stdout=[self.output],
            stderr=[],
            duration_ms=1,
        )


def coordinator(tmp_path: Path, runner: ScriptedRunner) -> NativeOrchestrationCoordinator:
    if not (tmp_path / ".git").exists():
        subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "Test"], check=True)
    seed = tmp_path / ".test-seed"
    seed.write_text("seed")
    subprocess.run(["git", "-C", str(tmp_path), "add", ".test-seed"], check=True)
    if subprocess.run(["git", "-C", str(tmp_path), "rev-parse", "HEAD"], capture_output=True).returncode:
        subprocess.run(["git", "-C", str(tmp_path), "commit", "-qm", "seed"], check=True)
    (tmp_path / "test_seed.py").write_text("def test_seed():\n    assert True\n")
    return NativeOrchestrationCoordinator(
        uow_factory=lambda: None,
        github_adapter=SimpleNamespace(),
        worktree_manager=SimpleNamespace(),
        agent_runner=runner,
    )


@pytest.mark.asyncio
async def test_complexity_requires_thinking_agent_and_evidence(tmp_path: Path):
    skill = tmp_path / ".agents" / "skills" / "openspec-propose"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("native")

    runner = ScriptedRunner('{"complexity":"low","evidence":"one focused change"}')
    result = await coordinator(tmp_path, runner)._assess_complexity(
        tmp_path, "codex", "Breaking migration wording", "ordinary request", "p1"
    )
    assert result.status == "VALID"
    assert result.complexity == "low"
    assert len(runner.calls) == 1

    runner.output = "low"
    invalid = await coordinator(tmp_path, runner)._assess_complexity(
        tmp_path, "codex", "title", "body", "p1"
    )
    assert invalid.is_valid is False


@pytest.mark.asyncio
async def test_complexity_rejects_multiple_or_prose_objects(tmp_path: Path):
    skill = tmp_path / ".agents" / "skills" / "openspec-propose"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("native")
    runner = ScriptedRunner(
        '{"complexity":"low","evidence":"a"}\n{"complexity":"high","evidence":"b"}'
    )
    result = await coordinator(tmp_path, runner)._assess_complexity(
        tmp_path, "codex", "title", "body", "p1"
    )
    assert result.status == "INVALID_OUTPUT"
    assert result.is_valid is False


def test_feasibility_requires_exact_native_task_and_scenario_coverage(tmp_path: Path):
    inputs = {
        "status": "READY",
        "candidate_sha": "a" * 40,
        "tasks": [{"task_id": "1.1", "text": "Run focused verification"}],
        "scenarios": [{"scenario_id": "capability:req-1:1", "text": "A feasible path exists"}],
        "capabilities": [
            {"ref": "profile:execution", "available": True},
            {"ref": "workflow:execution:apply", "available": True},
        ],
    }
    report = {
        "tasks": [
            {
                "task_id": "1.1",
                "actor": "execution",
                "execution_stage": "apply",
                "capability_evidence_refs": ["profile:execution", "workflow:execution:apply"],
                "depends_on_task_ids": [],
                "preconditions": [],
                "completion_evidence": "Focused test command exits zero",
            }
        ],
        "scenario_coverage": [
            {"scenario_id": "capability:req-1:1", "task_ids": ["1.1"], "evidence_stage": "apply"}
        ],
        "blockers": [],
        "resolution_options": [],
    }
    result = ProposalFeasibilityEvaluator.validate_report(
        report, inputs, tmp_path
    )
    assert result[0] == "EXECUTABLE"
    original_task_fingerprint = result[1][0]["source_text_sha256"]
    inputs["tasks"][0]["text"] = "Run focused verification against the exact candidate"
    revised = ProposalFeasibilityEvaluator.validate_report(report, inputs, tmp_path)
    assert revised[0] == "EXECUTABLE"
    assert revised[1][0]["source_text_sha256"] != original_task_fingerprint

    report["tasks"].append(dict(report["tasks"][0], task_id="extra"))
    blocked = ProposalFeasibilityEvaluator.validate_report(
        report, inputs, tmp_path
    )
    assert blocked[0] == "BLOCKED"
    assert any("unknown or duplicate ID" in reason for reason in blocked[3])


def test_later_stage_preview_does_not_block_apply_and_remains_pending(tmp_path: Path):
    workflow = tmp_path / ".github" / "workflows" / "deploy.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text("name: candidate preview\n")
    inputs = {
        "status": "READY",
        "candidate_sha": "b" * 40,
        "tasks": [{"task_id": "2.1", "text": "Validate the candidate on a phone"}],
        "scenarios": [{"scenario_id": "mobile:req-1:1", "text": "The mobile flow works"}],
        "capabilities": [
            {"ref": "profile:execution", "available": True},
            {"ref": "workflow:execution:apply", "available": True},
            {"ref": f"preview:{'b' * 40}", "available": False},
        ],
    }
    report = {
        "tasks": [
            {
                "task_id": "2.1",
                "actor": "project_ci_cd",
                "execution_stage": "verify",
                "capability_evidence_refs": ["path:.github/workflows/deploy.yml", f"preview:{'b' * 40}"],
                "depends_on_task_ids": [],
                "preconditions": [{
                    "required_before_stage": "verify",
                    "satisfied": False,
                    "evidence_refs": [f"preview:{'b' * 40}"],
                }],
                "completion_evidence": "Observed result from the exact candidate SHA",
            }
        ],
        "scenario_coverage": [
            {"scenario_id": "mobile:req-1:1", "task_ids": ["2.1"], "evidence_stage": "verify"}
        ],
        "blockers": [],
        "resolution_options": ["Provide an exact-SHA preview"],
    }
    result = ProposalFeasibilityEvaluator.validate_report(
        report, inputs, tmp_path
    )
    assert result[0] == "EXECUTABLE"
    assert result[1][0]["preconditions"][0]["status"] == "PENDING"


def test_unmet_apply_precondition_still_blocks_apply(tmp_path: Path):
    inputs = {
        "status": "READY",
        "candidate_sha": "c" * 40,
        "tasks": [{"task_id": "1.1", "text": "Build the workspace"}],
        "scenarios": [{"scenario_id": "build:req-1:1", "text": "Build succeeds"}],
        "capabilities": [
            {"ref": "profile:execution", "available": True},
            {"ref": "workflow:execution:apply", "available": True},
            {"ref": "required:credential", "available": False},
        ],
    }
    report = {
        "tasks": [{
            "task_id": "1.1",
            "actor": "execution",
            "execution_stage": "apply",
            "capability_evidence_refs": ["profile:execution", "workflow:execution:apply"],
            "depends_on_task_ids": [],
            "preconditions": [{
                "required_before_stage": "apply",
                "satisfied": False,
                "evidence_refs": ["required:credential"],
            }],
            "completion_evidence": "Build command exits successfully",
        }],
        "scenario_coverage": [{
            "scenario_id": "build:req-1:1",
            "task_ids": ["1.1"],
            "evidence_stage": "apply",
        }],
        "blockers": [],
        "resolution_options": ["Provide the required credential"],
    }
    result = ProposalFeasibilityEvaluator.validate_report(report, inputs, tmp_path)
    assert result[0] == "BLOCKED"
    assert any("required before Apply" in reason for reason in result[3])


def test_precondition_evidence_requires_exact_capability_or_prefixed_candidate_path(tmp_path: Path):
    gameplay = tmp_path / "docs" / "GAMEPLAY.md"
    gameplay.parent.mkdir()
    gameplay.write_text("Verified game rules")
    inputs = {
        "status": "READY",
        "candidate_sha": "c" * 40,
        "tasks": [{"task_id": "2.1", "text": "Implement the documented rules"}],
        "scenarios": [{"scenario_id": "game:req-1:1", "text": "Rules are applied"}],
        "capabilities": [
            {"ref": "profile:execution", "available": True},
            {"ref": "workflow:execution:apply", "available": True},
        ],
    }
    task = {
        "task_id": "2.1",
        "actor": "execution",
        "execution_stage": "apply",
        "capability_evidence_refs": ["profile:execution", "workflow:execution:apply"],
        "depends_on_task_ids": [],
        "preconditions": [{
            "required_before_stage": "apply",
            "satisfied": True,
            "evidence_refs": ["docs/GAMEPLAY.md"],
        }],
        "completion_evidence": "Focused rule tests pass",
    }
    report = {
        "tasks": [task],
        "scenario_coverage": [{
            "scenario_id": "game:req-1:1",
            "task_ids": ["2.1"],
            "evidence_stage": "apply",
        }],
        "blockers": [],
        "resolution_options": [],
    }

    unprefixed = ProposalFeasibilityEvaluator.validate_report(report, inputs, tmp_path)
    assert unprefixed[0] == "BLOCKED"
    assert any("unverified precondition evidence" in reason for reason in unprefixed[3])

    task["preconditions"][0]["evidence_refs"] = ["path:docs/GAMEPLAY.md"]
    prefixed = ProposalFeasibilityEvaluator.validate_report(report, inputs, tmp_path)
    assert prefixed[0] == "EXECUTABLE"


def test_apply_output_dependency_is_not_a_precondition_for_starting_apply(tmp_path: Path):
    inputs = {
        "status": "READY",
        "candidate_sha": "d" * 40,
        "tasks": [
            {"task_id": "1.2", "text": "Create the package manifest"},
            {"task_id": "4.1", "text": "Run the package build"},
        ],
        "scenarios": [{"scenario_id": "workspace:req-1:1", "text": "All workspaces build"}],
        "capabilities": [
            {"ref": "profile:execution", "available": True},
            {"ref": "workflow:execution:apply", "available": True},
        ],
    }
    report = {
        "tasks": [
            {
                "task_id": "1.2",
                "actor": "execution",
                "execution_stage": "apply",
                "capability_evidence_refs": ["profile:execution", "workflow:execution:apply"],
                "depends_on_task_ids": [],
                "preconditions": [],
                "completion_evidence": "Package manifest exists in the candidate diff",
            },
            {
                "task_id": "4.1",
                "actor": "execution",
                "execution_stage": "apply",
                "capability_evidence_refs": ["profile:execution", "workflow:execution:apply"],
                "depends_on_task_ids": ["1.2"],
                "preconditions": [],
                "completion_evidence": "Build command exits successfully",
            },
        ],
        "scenario_coverage": [{
            "scenario_id": "workspace:req-1:1",
            "task_ids": ["1.2", "4.1"],
            "evidence_stage": "apply",
        }],
        "blockers": [],
        "resolution_options": [],
    }
    result = ProposalFeasibilityEvaluator.validate_report(report, inputs, tmp_path)
    assert result[0] == "EXECUTABLE"
    assert result[1][1]["depends_on_task_ids"] == ["1.2"]


def test_verify_transition_checks_deferred_preview_against_current_candidate(tmp_path: Path):
    task_feasibility = [{
        "task_id": "4.1",
        "execution_stage": "verify",
        "preconditions": [{
            "required_before_stage": "verify",
            "satisfied": False,
            "status": "PENDING",
            "evidence_refs": ["preview:old-candidate"],
        }],
    }]
    inputs = {
        "status": "READY",
        "candidate_sha": "e" * 40,
        "capabilities": [{
            "ref": f"preview:{'e' * 40}",
            "available": False,
        }],
    }
    blocked = ProposalFeasibilityEvaluator.blockers_before_stage(
        task_feasibility, stage="verify", inputs=inputs, worktree_path=tmp_path
    )
    assert blocked
    assert "task 4.1" in blocked[0]

    inputs["capabilities"][0]["available"] = True
    passed = ProposalFeasibilityEvaluator.blockers_before_stage(
        task_feasibility, stage="verify", inputs=inputs, worktree_path=tmp_path
    )
    assert passed == ()


@pytest.mark.parametrize("stage", ["pre_pr", "post_merge", "human_validation"])
def test_deferred_stage_requires_its_declared_capability(stage: str, tmp_path: Path):
    task_feasibility = [{
        "task_id": "5.2",
        "actor": "human_operator",
        "execution_stage": stage,
        "capability_evidence_refs": ["operator:confirmed"],
        "preconditions": [],
    }]
    inputs = {"status": "READY", "candidate_sha": "a" * 40, "capabilities": []}

    blocked = ProposalFeasibilityEvaluator.blockers_before_stage(
        task_feasibility, stage=stage, inputs=inputs, worktree_path=tmp_path
    )
    assert blocked
    assert "task 5.2" in blocked[0]
    assert "human_operator" in blocked[0]

    inputs["capabilities"] = [{"ref": "operator:confirmed", "available": True}]
    assert ProposalFeasibilityEvaluator.blockers_before_stage(
        task_feasibility, stage=stage, inputs=inputs, worktree_path=tmp_path
    ) == ()


@pytest.mark.asyncio
async def test_coordinator_holds_transition_until_stage_evidence_exists(tmp_path: Path):
    c = coordinator(tmp_path, ScriptedRunner("unused"))
    task_text = "Validate the exact candidate in the project preview"
    task_hash = hashlib.sha256(task_text.encode()).hexdigest()
    scenario_text = "The candidate is available for validation"
    scenario_hash = hashlib.sha256(scenario_text.encode()).hexdigest()
    task = {
        "task_id": "4.2",
        "actor": "human_operator",
        "execution_stage": "pre_pr",
        "capability_evidence_refs": [],
        "preconditions": [{
            "required_before_stage": "pre_pr",
            "satisfied": False,
            "evidence_refs": ["preview:prior-candidate"],
        }],
        "source_text_sha256": task_hash,
    }
    assessment = {
        "task_feasibility": [task],
        "scenario_coverage": [{
            "scenario_id": "change:req-388:1",
            "source_text_sha256": scenario_hash,
        }],
    }
    run = SimpleNamespace(
        run_id="run-388",
        change_name="req-388-reject-unexecutable-proposals",
        current_stage="PR2_MERGED",
        stop_details={"complexity_assessment": assessment},
    )
    uow = SimpleNamespace(projects=SimpleNamespace(get_by_id=MagicMock(return_value=None)))
    current_task = {"task_id": "4.2", "text": task_text}
    current_scenario = {"scenario_id": "change:req-388:1", "text": scenario_text}
    c.proposal_feasibility.collect_inputs = MagicMock(return_value={
        "status": "READY",
        "candidate_sha": "a" * 40,
        "tasks": [current_task],
        "scenarios": [current_scenario],
        "capabilities": [],
    })
    gate_payload = {"question": "Evidence required", "gate": "proposal_feasibility"}
    c._record_current_human_gate = MagicMock(return_value=gate_payload)

    result = await c._check_stage_feasibility(
        uow,
        run,
        project_id="project-1",
        worktree_path=tmp_path,
        thinker_provider="codex",
        implementer_provider="codex",
        stage="pre_pr",
    )

    assert result is not None
    assert result.status == "HUMAN_REQUIRED"
    assert "pre_pr" in c._record_current_human_gate.call_args.kwargs["question"]
    assert c._record_current_human_gate.call_args.kwargs["payload"]["blocked_transition"] == "pre_pr"


@pytest.mark.asyncio
async def test_structured_assessment_only_passes_when_all_capabilities_are_verified(tmp_path: Path):
    skill = tmp_path / ".agents" / "skills" / "openspec-propose"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("native propose")
    feasibility = {
        "status": "READY",
        "candidate_sha": "c" * 40,
        "tasks": [{"task_id": "1.1", "text": "Run focused tests"}],
        "scenarios": [{"scenario_id": "change:req-1:1", "text": "The Change is verifiable"}],
        "capabilities": [
            {"ref": "profile:execution", "available": True},
            {"ref": "workflow:execution:apply", "available": True},
        ],
    }
    output = {
        "complexity": "moderate",
        "evidence": "One bounded workflow change.",
        "feasibility": {
            "tasks": [{
                "task_id": "1.1",
                "actor": "execution",
            "execution_stage": "apply",
                "capability_evidence_refs": ["profile:execution", "workflow:execution:apply"],
            "depends_on_task_ids": [],
                "preconditions": [],
                "completion_evidence": "Focused test command exits zero",
            }],
            "scenario_coverage": [{"scenario_id": "change:req-1:1", "task_ids": ["1.1"], "evidence_stage": "apply"}],
            "blockers": [],
            "resolution_options": [],
        },
    }
    runner = ScriptedRunner(json.dumps(output))
    result = await coordinator(tmp_path, runner)._assess_complexity(
        tmp_path,
        "codex",
        "title",
        "request",
        "project",
        change_name="change",
        feasibility_inputs=feasibility,
    )
    assert result.status == "VALID"
    assert result.is_executable
    assert result.feasibility_status == "EXECUTABLE"
    assert "path:<repo-relative-path>" in runner.calls[0]
    assert "Never use unprefixed paths" in runner.calls[0]

    feasibility["capabilities"] = []
    blocked = await coordinator(tmp_path, runner)._assess_complexity(
        tmp_path,
        "codex",
        "title",
        "request",
        "project",
        change_name="change",
        feasibility_inputs=feasibility,
    )
    assert blocked.is_valid
    assert blocked.feasibility_status == "BLOCKED"
    assert not blocked.is_executable


def test_feasibility_inventory_rejects_unknown_candidate_sha(tmp_path: Path):
    runner = ScriptedRunner("unused")
    c = coordinator(tmp_path, runner)
    result = c.proposal_feasibility.collect_inputs(
        worktree_path=tmp_path,
        change_name="change",
        project=None,
        candidate_sha="unknown",
        candidate_clean=False,
        preview_sessions=None,
        thinker_provider="codex",
        implementer_provider="codex",
    )
    assert result["status"] == "UNKNOWN"
    assert "SHA" in result["reason"]


def test_feasibility_inventory_blocks_unconfigured_agent_and_missing_preview(tmp_path: Path):
    change_dir = tmp_path / "openspec" / "changes" / "change"
    change_dir.mkdir(parents=True)
    (change_dir / "tasks.md").write_text("## Checks\n- [ ] 1.1 Verify candidate", encoding="utf-8")
    adapter = SimpleNamespace(
        show_change=MagicMock(
            return_value={
                "deltas": [
                    {
                        "spec": "feature",
                        "requirements": [
                            {
                                "id": "1",
                                "scenarios": [{"rawText": "WHEN validated THEN evidence exists"}],
                            }
                        ],
                    }
                ]
            }
        )
    )
    runner = SimpleNamespace(resolve_workflow=MagicMock(side_effect=AssertionError("no profile")))
    project = SimpleNamespace(project_id="project", openspec_path="openspec", agent_profiles={})
    preview_sessions = SimpleNamespace(get_latest_for_candidate=MagicMock(return_value=None))

    inputs = ProposalFeasibilityEvaluator(adapter, runner).collect_inputs(
        worktree_path=tmp_path,
        change_name="change",
        project=project,
        candidate_sha="d" * 40,
        candidate_clean=True,
        preview_sessions=preview_sessions,
        thinker_provider="codex",
        implementer_provider="codex",
    )

    assert inputs["status"] == "READY"
    assert any("profile:thinking" in blocker for blocker in inputs["mandatory_blockers"])
    assert any("workflow:execution:apply" in blocker for blocker in inputs["mandatory_blockers"])
    assert {item["ref"] for item in inputs["capabilities"] if item["available"]} == {
        "operator:confirmed"
    }
    runner.resolve_workflow.assert_not_called()
    preview_sessions.get_latest_for_candidate.assert_called_once_with(
        "project", "change", "d" * 40
    )


@pytest.mark.parametrize(
    ("head_sha", "candidate_clean", "expected"),
    [("e" * 40, True, True), ("f" * 40, True, False), ("e" * 40, False, False)],
)
def test_preview_capability_requires_exact_clean_candidate(
    tmp_path: Path, head_sha: str, candidate_clean: bool, expected: bool
):
    change_dir = tmp_path / "openspec" / "changes" / "change"
    change_dir.mkdir(parents=True)
    (change_dir / "tasks.md").write_text("## Checks\n- [ ] 1.1 Validate preview", encoding="utf-8")
    adapter = SimpleNamespace(
        show_change=lambda *_: {
            "deltas": [
                {
                    "spec": "feature",
                    "requirements": [
                        {"id": "1", "scenarios": [{"rawText": "WHEN previewed THEN pass"}]}
                    ],
                }
            ]
        }
    )
    preview = SimpleNamespace(
        status=SimpleNamespace(value="READY"),
        head_sha=head_sha,
        preview_url="https://preview.example.test",
        preview_id="preview-1",
    )
    preview_sessions = SimpleNamespace(get_latest_for_candidate=lambda *_: preview)
    inputs = ProposalFeasibilityEvaluator(adapter, SimpleNamespace()).collect_inputs(
        worktree_path=tmp_path,
        change_name="change",
        project=SimpleNamespace(project_id="project", openspec_path="openspec", agent_profiles={}),
        candidate_sha="e" * 40,
        candidate_clean=candidate_clean,
        preview_sessions=preview_sessions,
        thinker_provider="codex",
        implementer_provider="codex",
    )
    preview_capability = next(item for item in inputs["capabilities"] if item["kind"] == "candidate_sha_matched_preview")
    assert preview_capability["available"] is expected


@pytest.mark.asyncio
async def test_explore_failure_blocks_propose(tmp_path: Path):
    runner = ScriptedRunner("READY_TO_PROPOSE")
    c = coordinator(tmp_path, runner)
    result = await c._run_explore(tmp_path, "codex", 5, "title", "body", project_id="p1")
    assert result["status"] == "READY_TO_PROPOSE"
    runner.output = "exploration narrative without an explicit verdict"
    assert (await c._run_explore(tmp_path, "codex", 5, "title", "body", project_id="p1"))[
        "status"
    ] == "FAILED"
    runner.exit_code = 2
    result = await c._run_explore(tmp_path, "codex", 5, "title", "body", project_id="p1")
    assert result["status"] == "FAILED"


@pytest.mark.asyncio
async def test_request_revision_dispatches_installed_openspec_update(tmp_path: Path):
    runner = ScriptedRunner("updated planning artifacts")
    c = coordinator(tmp_path, runner)
    c.openspec_adapter.planning_status = MagicMock(
        return_value={"status": "PASS", "pending": []}
    )

    result = await c._run_propose(
        worktree_path=tmp_path,
        provider="codex",
        change_name="req-388-reject-unexecutable-proposals",
        issue_number=388,
        issue_title="Reject unexecutable proposals",
        issue_body="Use the current authoritative Request.",
        project_id="minime",
        continue_existing=True,
        pending_revision=True,
        operator_clarification="Reconcile using native OpenSpec Update.",
    )

    assert result["status"] == "READY_TO_VALIDATE"
    assert "Execute official OpenSpec Update" in runner.calls[0]
    assert "native-update" in runner.calls[0]
    assert "Use the current authoritative Request." in runner.calls[0]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("response", "status"),
    [
        (
            "READY_TO_PROPOSE\nLa aclaración resolvió el conflicto. "
            "El gate HUMAN REQUIRED anterior es solo antecedente.",
            "READY_TO_PROPOSE",
        ),
        (
            "## **READY_TO_PROPOSE**\nEl backend mínimo ya está autorizado. "
            "El texto HUMAN REQUIRED aparece en el Issue y logs.",
            "READY_TO_PROPOSE",
        ),
        (
            "Exploración: se revisó el antecedente HUMAN REQUIRED.\n"
            "READY_TO_PROPOSE\nListo para Propose.",
            "READY_TO_PROPOSE",
        ),
        (
            "```text\nHUMAN REQUIRED\n- Ejemplo histórico\n```\n"
            "READY_TO_PROPOSE\nLa decisión ya está tomada.",
            "READY_TO_PROPOSE",
        ),
        ("HUMAN REQUIRED\n- Consultar diseño\n- Mantener alcance", "HUMAN_REQUIRED"),
        ("**HUMAN REQUIRED**\n- Aclaración auténtica", "HUMAN_REQUIRED"),
        ("Se discutió HUMAN REQUIRED pero ya está resuelto.", "FAILED"),
        ("READY_TO_PROPOSE\nHUMAN REQUIRED\n- Pregunta", "FAILED"),
        ("- READY_TO_PROPOSE\nSin veredicto formal", "FAILED"),
        ("HUMAN REQUIRED sin opciones", "FAILED"),
    ],
)
async def test_explore_verdict_uses_exact_provider_disposition_not_context(
    tmp_path, response, status
):
    runner = ScriptedRunner(response)
    resolved = await coordinator(tmp_path, runner)._run_explore(
        tmp_path, "codex", 173, "F5", "Gherkin", project_id="mini-me"
    )
    assert resolved["status"] == status
    assert len(runner.calls) == 1


@pytest.mark.asyncio
async def test_explore_codex_ndjson_uses_final_agent_message_not_tool_logs(tmp_path):
    import json

    events = [
        {"type": "thread.started", "thread_id": "thread-f5"},
        {
            "type": "item.completed",
            "item": {
                "type": "command_execution",
                "output": "HUMAN REQUIRED\n- An earlier user decision",
            },
        },
        {
            "type": "item.completed",
            "item": {
                "type": "agent_message",
                "text": ("READY_TO_PROPOSE\nLa aclaración resuelve el anterior HUMAN REQUIRED."),
            },
        },
        {"type": "turn.completed", "usage": {"input_tokens": 200, "output_tokens": 40}},
    ]
    stdout = "\n".join(json.dumps(item) for item in events)
    runner = ScriptedRunner(stdout)
    verdict = await coordinator(tmp_path, runner)._run_explore(
        tmp_path, "codex", 173, "F5", "Gherkin", project_id="mini-me"
    )
    assert verdict["status"] == "READY_TO_PROPOSE"
    assert len(runner.calls) == 1


@pytest.mark.asyncio
async def test_explore_refuses_codex_events_without_final_assistant_message(tmp_path):
    import json

    output = "\n".join(
        json.dumps(event)
        for event in [
            {"type": "turn.started"},
            {
                "type": "item.completed",
                "item": {
                    "type": "command_execution",
                    "output": "READY_TO_PROPOSE",
                },
            },
            {"type": "turn.completed"},
        ]
    )
    result = await coordinator(tmp_path, ScriptedRunner(output))._run_explore(
        tmp_path, "codex", 173, "F5", "Gherkin", project_id="mini-me"
    )
    assert result["status"] == "FAILED"


@pytest.mark.asyncio
async def test_explore_codex_json_failure_event_refuses_to_advance(tmp_path):
    import json

    payload = [
        {"type": "item.completed", "item": {"type": "agent_message", "text": "READY_TO_PROPOSE"}},
        {"type": "turn.failed"},
    ]
    text = "\n".join(json.dumps(event) for event in payload)
    result = await coordinator(tmp_path, ScriptedRunner(text))._run_explore(
        tmp_path, "codex", 173, "F5", "Gherkin", project_id="mini-me"
    )
    assert result["status"] == "FAILED"


@pytest.mark.asyncio
async def test_explore_ignores_stderr_and_blocks_incomplete_final_response(tmp_path):
    from unittest.mock import AsyncMock

    c = coordinator(tmp_path, ScriptedRunner(""))
    c.agent_runner.run = AsyncMock(
        return_value=AgentExecutionResult(
            exit_code=0,
            timed_out=False,
            stdout=["READY_TO_PROPOSE"],
            stderr=["HUMAN REQUIRED (prior debug notice)"],
            duration_ms=1,
        )
    )
    assert (await c._run_explore(tmp_path, "codex", 173, "F5", "Gherkin", project_id="mini-me"))[
        "status"
    ] == "READY_TO_PROPOSE"
    c.agent_runner.run.return_value = AgentExecutionResult(
        exit_code=0,
        timed_out=False,
        stdout=["READY_TO_PROPOSE"],
        stderr=[],
        duration_ms=1,
        output_truncated=True,
        final_response_status="TRUNCATED",
    )
    assert (await c._run_explore(tmp_path, "codex", 173, "F5", "Gherkin", project_id="mini-me"))[
        "status"
    ] == "FAILED"


@pytest.mark.asyncio
async def test_reviews_require_positive_structured_verdict(tmp_path: Path):
    change_dir = tmp_path / "openspec" / "changes" / "change"
    change_dir.mkdir(parents=True)
    (change_dir / "proposal.md").write_text("proposal")
    runner = ScriptedRunner("APPROVED")
    assert not await coordinator(tmp_path, runner)._run_proposal_review(tmp_path, "codex", "change")

    runner.output = '{"verdict":"READY_TO_MERGE","summary":"verified","findings":[]}'
    assert await coordinator(tmp_path, runner)._run_proposal_review(tmp_path, "codex", "change")


@pytest.mark.asyncio
async def test_verify_requires_native_final_response_channel(tmp_path: Path):
    skill = tmp_path / ".agents" / "skills" / "openspec-verify-change"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("native verify")
    runner = ScriptedRunner('{"verdict":"READY_TO_MERGE","summary":"verified","findings":[]}')

    result = await coordinator(tmp_path, runner)._run_verify(tmp_path, "codex", "change")

    assert result is True
    assert "output-schema" not in runner.calls[0]
    assert "authorized final response channel" in runner.calls[0]


@pytest.mark.asyncio
async def test_branch_publication_uses_authenticated_github_adapter(tmp_path: Path):
    from minime.domain.enums import ExternalOutcome, ExternalReasonCode, RetrySafety
    from minime.domain.models import ExternalActionResult

    adapter = SimpleNamespace(
        push_branch=lambda **kwargs: ExternalActionResult(
            outcome=ExternalOutcome.SUCCESS,
            source_adapter="github",
            reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
            retry_safety=RetrySafety.UNSAFE,
            data=kwargs["candidate_sha"],
        )
    )
    c = NativeOrchestrationCoordinator(
        uow_factory=lambda: None,
        github_adapter=adapter,
        worktree_manager=SimpleNamespace(),
        agent_runner=ScriptedRunner("unused"),
    )
    c._get_git_head_sha = AsyncMock(return_value="a" * 40)

    await c._push_branch(tmp_path, "request-5-test")


@pytest.mark.asyncio
async def test_candidate_commit_is_created_only_for_dirty_worktree(tmp_path: Path):
    c = coordinator(tmp_path, ScriptedRunner("unused"))
    calls: list[list[str]] = []

    async def fake_git_run(_cwd: Path, args: list[str]):
        calls.append(args)
        if args == ["status", "--porcelain"]:
            return SimpleNamespace(stdout=" M src/app.py\n")
        if args == ["diff", "--cached", "--name-only"]:
            return SimpleNamespace(returncode=0, stdout="src/app.py\n")
        return SimpleNamespace(returncode=0, stdout="")

    c._git_run = fake_git_run
    await c._ensure_candidate_commit(tmp_path, 5)
    assert ["add", "-A"] in calls
    assert ["commit", "-m", "feat(request-5): implement OpenSpec change"] in calls


@pytest.mark.asyncio
async def test_apply_and_sync_fail_closed_on_agent_error(tmp_path: Path):
    runner = ScriptedRunner("failure", exit_code=2)
    c = coordinator(tmp_path, runner)
    assert not await c._run_apply(tmp_path, "codex", "change")

    runner.exit_code = 0
    runner.output = "sync evidence"
    c._git_run = AsyncMock(return_value=SimpleNamespace(stdout=""))
    # Exit zero and a success narrative are insufficient without archive files.
    assert not await c._run_sync_and_archive(tmp_path, "codex", "change")
    archive = tmp_path / "openspec" / "changes" / "archive" / "2026-10-27-change"
    (archive / "specs").mkdir(parents=True)
    for filename in ("proposal.md", "design.md", "tasks.md"):
        (archive / filename).write_text("native")
    assert await c._run_sync_and_archive(tmp_path, "codex", "change")
    assert len(runner.calls) == 5  # Apply plus two complete Sync/Archive cycles.


@pytest.mark.asyncio
async def test_empty_selection_is_not_pass(tmp_path: Path):
    c = coordinator(tmp_path, ScriptedRunner("unused"))
    base_branch = subprocess.run(
        ["git", "-C", str(tmp_path), "branch", "--show-current"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    (tmp_path / "test_seed.py").unlink()
    ok, evidence = await c._run_automated_tests(tmp_path, base_branch)
    assert not ok
    assert "no tests" in evidence.lower() or "collected" in evidence.lower()

    (tmp_path / "test_real.py").write_text("def test_real():\n    assert True\n")
    ok, evidence = await c._run_automated_tests(tmp_path, base_branch)
    assert ok
    assert "passed" in evidence.lower()


@pytest.mark.asyncio
async def test_native_apply_requires_tasks_not_just_success_text(tmp_path: Path):
    runner = ScriptedRunner("Apply completed")
    c = coordinator(tmp_path, runner)
    assert not await c._run_apply(tmp_path, "codex", "change")
    change = tmp_path / "openspec" / "changes" / "change"
    change.mkdir(parents=True)
    (change / "tasks.md").write_text("## Tasks\n- [ ] 1.1 Implement\n")
    assert not await c._run_apply(tmp_path, "codex", "change")
    (change / "tasks.md").write_text("## Tasks\n- [x] 1.1 Implement\n")
    assert await c._run_apply(tmp_path, "codex", "change")


def test_classify_pending_tasks_splits_not_verified():
    tasks = (
        "## Tasks\n"
        "- [x] 1.1 Done\n"
        "- [ ] 2.1 Pending automated work\n"
        "- [ ] 3.1 Validar en un iPhone real. (NOT_VERIFIED: no hay evidencia física disponible.)\n"
        "- [ ] 3.2 Vincular SHA. (NOT_VERIFIED: no existe SHA candidato inmutable.)\n"
    )
    automated, not_verified = NativeOrchestrationCoordinator._classify_pending_tasks(tasks)
    assert automated == ["2.1"]
    assert not_verified == ["3.1", "3.2"]


def test_deferred_task_stays_pending_without_being_apply_work_or_completed():
    tasks = (
        "## Tasks\n"
        "- [ ] 4.2 Validar audio en iPhone [DEFERRED] hasta integrar TTS; SHA de versión publicada: desconocido.\n"
    )

    automated, not_verified = NativeOrchestrationCoordinator._classify_pending_tasks(tasks)

    assert automated == []
    assert not_verified == []
    assert NativeOrchestrationCoordinator._deferred_task_ids(tasks) == ["4.2"]


def test_published_version_evidence_needs_exact_candidate_sha_to_complete():
    candidate_sha = "a" * 40
    matching = f'- [x] 4.1 Desktop check [PUBLISHED_EVIDENCE source="GitHub Pages"; sha={candidate_sha}]'
    mismatched = '- [x] 4.2 iPhone check [PUBLISHED_EVIDENCE source="GitHub Pages"; sha=unknown]'

    assert NativeOrchestrationCoordinator._invalid_published_evidence_completions(
        matching, candidate_sha
    ) == []
    assert NativeOrchestrationCoordinator._invalid_published_evidence_completions(
        mismatched, candidate_sha
    ) == ["4.2"]


def test_apply_recovery_progress_uses_pending_count_or_diff_fingerprint():
    previous = {"pending": ["1.1", "1.2"], "fingerprint": "old"}
    fewer_tasks = ApplyOutcome("PARTIAL", ("1.1",), ("1.2",), "sha-1", (), None, False, "red")
    changed_diff = ApplyOutcome("PARTIAL", (), ("1.1", "1.2"), "sha-2", ("src/a.py",), "new", False, "red")
    no_progress = ApplyOutcome("PARTIAL", (), ("1.1", "1.2"), "sha-1", (), "old", False, "red")

    assert NativeOrchestrationCoordinator._apply_made_progress(previous, fewer_tasks)
    assert NativeOrchestrationCoordinator._apply_made_progress(previous, changed_diff)
    assert not NativeOrchestrationCoordinator._apply_made_progress(previous, no_progress)

    context = NativeOrchestrationCoordinator._apply_recovery_context(
        NativeOrchestrationCoordinator._apply_snapshot(changed_diff)
    )
    assert "Git changed files: ['src/a.py']" in context
    assert "Mark [x]" in context


def test_apply_regression_guard_detects_identity_files_tasks_and_test_loss():
    previous = {"branch": "request-259", "worktree": "/candidate", "run_id": "run-1",
                "files": ["src/a.py", "src/b.py"], "completed": ["1.1", "1.2"],
                "tests_passed": True}
    same = ApplyOutcome("PARTIAL", ("1.1", "1.2"), ("1.3",), "sha", ("src/a.py", "src/b.py"),
                        "digest", True, "ok", branch="request-259", worktree="/candidate", run_id="run-1")
    changed_branch = ApplyOutcome("PARTIAL", same.completed_tasks, same.pending_tasks, "sha", same.changed_files,
                                  "digest", True, "ok", branch="other", worktree="/candidate", run_id="run-1")
    missing_file = ApplyOutcome("PARTIAL", same.completed_tasks, same.pending_tasks, "sha", ("src/a.py",),
                                "digest", True, "ok", branch="request-259", worktree="/candidate", run_id="run-1")
    failing_tests = ApplyOutcome("PARTIAL", same.completed_tasks, same.pending_tasks, "sha", same.changed_files,
                                 "digest", False, "failed", branch="request-259", worktree="/candidate", run_id="run-1")

    assert not NativeOrchestrationCoordinator._apply_regressed(previous, same)
    assert NativeOrchestrationCoordinator._apply_regressed(previous, changed_branch)
    assert NativeOrchestrationCoordinator._apply_regressed(previous, missing_file)
    assert NativeOrchestrationCoordinator._apply_regressed(previous, failing_tests)


def test_validated_update_ignores_only_exact_task_reclassification_losses():
    from minime.services.orchestration_coordinator import NativeOrchestrationCoordinator

    prior = {
        "run_id": "run-1", "sha": "sha-1", "branch": "request-259",
        "worktree": "/candidate", "completed": ["1.1", "1.2"],
    }
    checkpoint = {
        "status": "VALIDATED", "operator_action_id": "action-1",
        "change_name": "change-1",
        "before": {"run_id": "run-1", "candidate_sha": "sha-1",
                   "branch": "request-259", "worktree": "/candidate", "generation": 1},
        "after": {"run_id": "run-1", "candidate_sha": "sha-1",
                  "branch": "request-259", "worktree": "/candidate", "generation": 1},
        "reclassified_tasks": ["1.1"],
        "task_dispositions_before": {"1.1": "completed", "1.2": "completed"},
        "task_dispositions_after": {"1.1": "deferred", "1.2": "completed"},
    }
    current = ApplyOutcome(
        "PARTIAL", ("1.2",), ("1.1", "1.3"), "sha-1", (), None, None, "",
        branch="request-259", worktree="/candidate", run_id="run-1",
    )
    ignored = NativeOrchestrationCoordinator._validated_apply_reclassifications(
        checkpoint, operator_action_id="action-1", prior=prior, run_id="run-1",
        generation=1, change_name="change-1",
    )
    assert ignored == {"1.1"}
    assert not NativeOrchestrationCoordinator._apply_regressed(
        prior, current, ignored_task_losses=ignored
    )

    unrelated_loss = ApplyOutcome(
        "PARTIAL", (), ("1.1", "1.2", "1.3"), "sha-1", (), None, None, "",
        branch="request-259", worktree="/candidate", run_id="run-1",
    )
    assert NativeOrchestrationCoordinator._apply_regressed(
        prior, unrelated_loss, ignored_task_losses=ignored
    )
    assert NativeOrchestrationCoordinator._validated_apply_reclassifications(
        {**checkpoint, "after": {**checkpoint["after"], "candidate_sha": "other-sha"}},
        operator_action_id="action-1", prior=prior, run_id="run-1", generation=1,
        change_name="change-1",
    ) == set()
    assert NativeOrchestrationCoordinator._validated_apply_reclassifications(
        checkpoint, operator_action_id="action-1", prior=prior, run_id="run-1",
        generation=2, change_name="change-1",
    ) == set()


def test_apply_retry_limits_are_persistable_and_bounded():
    assert NativeOrchestrationCoordinator._positive_policy_limit(
        {"apply_max_attempts": 4}, "apply_max_attempts", 3
    ) == 4
    assert NativeOrchestrationCoordinator._positive_policy_limit(
        {"apply_max_attempts": 100}, "apply_max_attempts", 3
    ) == 10
    assert NativeOrchestrationCoordinator._positive_policy_limit(
        {"apply_max_attempts": 0}, "apply_max_attempts", 3
    ) == 3


@pytest.mark.asyncio
async def test_run_apply_succeeds_when_only_not_verified_remain(tmp_path: Path):
    """NOT_VERIFIED physical-validation tasks are not part of the Apply postcondition."""
    runner = ScriptedRunner("Apply completed")
    c = coordinator(tmp_path, runner)
    change = tmp_path / "openspec" / "changes" / "change"
    change.mkdir(parents=True)
    (change / "tasks.md").write_text(
        "## Tasks\n"
        "- [x] 1.1 Implement\n"
        "- [ ] 6.1 Validar en iPhone real. (NOT_VERIFIED: no hay evidencia física disponible.)\n"
    )
    assert await c._run_apply(tmp_path, "codex", "change")

    # A genuinely-pending non-NOT_VERIFIED task still gates Apply fail-closed.
    (change / "tasks.md").write_text(
        "## Tasks\n- [x] 1.1 Implement\n- [ ] 2.1 Pending automated work\n"
    )
    assert not await c._run_apply(tmp_path, "codex", "change")


def test_boxio_gate_regression_scenarios_and_evidence_are_accepted(tmp_path: Path):
    """Exact regression reproducing Boxio D0 gate: 8 deltas across 3 specs and observed evidence refs."""
    change_dir = tmp_path / "openspec" / "changes" / "change"
    change_dir.mkdir(parents=True)
    task_lines = [
        "- [ ] 1.1 Toolchain y estructura del workspace",
        "- [ ] 1.2 Monorepo de paquetes web, server y engine",
        "- [ ] 1.3 Scripts reproducibles de instalacion, build y test",
        "- [ ] 2.1 Contratos TypeScript de juego",
        "- [ ] 2.2 Representacion minima y validacion",
        "- [ ] 2.3 Transicion de turno y puntuacion",
        "- [ ] 2.4 Pruebas deterministas de engine",
        "- [ ] 3.1 Integracion de paquetes",
        "- [ ] 3.2 Assets locales canonicos",
        "- [ ] 3.3 Comprobacion automatizada de catalogo",
    ]
    (change_dir / "tasks.md").write_text("## Tasks\n" + "\n".join(task_lines) + "\n", encoding="utf-8")

    deltas = [
        {"spec": "foundation-workspace", "requirements": [{"scenarios": [{"rawText": "WHEN build THEN pass"}, {"rawText": "WHEN run THEN no external"}]}]},
        {"spec": "foundation-workspace", "requirements": [{"scenarios": [{"rawText": "WHEN shapes THEN canonical"}, {"rawText": "WHEN non-square THEN reject"}]}]},
        {"spec": "foundation-workspace", "requirements": [{"scenarios": [{"rawText": "WHEN tests THEN pass"}, {"rawText": "WHEN toolchain THEN compatible"}]}]},
        {"spec": "game-contracts", "requirements": [{"scenarios": [{"rawText": "WHEN board THEN valid"}, {"rawText": "WHEN cell THEN square"}]}]},
        {"spec": "game-contracts", "requirements": [{"scenarios": [{"rawText": "WHEN line THEN toggle"}, {"rawText": "WHEN box THEN score"}]}]},
        {"spec": "game-contracts", "requirements": [{"scenarios": [{"rawText": "WHEN chain THEN continue"}, {"rawText": "WHEN complete THEN finish"}]}]},
        {"spec": "game-contracts", "requirements": [{"scenarios": [{"rawText": "WHEN semantic THEN match"}]}]},
        {"spec": "local-assets", "requirements": [{"scenarios": [{"rawText": "WHEN assets THEN local"}, {"rawText": "WHEN clean THEN pass"}]}]},
    ]
    adapter = SimpleNamespace(
        show_change=lambda *_: {"deltas": deltas},
        planning_status=lambda *_: {"status": "PASS"},
        validate_change_strict=lambda *_: {"status": "PASS"},
    )
    runner = SimpleNamespace(resolve_workflow=MagicMock(return_value=SimpleNamespace(dispatch_command="codex exec")))
    agent_profiles = {
        "thinking": {"agent_id": "codex", "provider_id": "codex"},
        "execution": {"agent_id": "codex", "provider_id": "codex"},
    }
    evaluator = ProposalFeasibilityEvaluator(adapter, runner)
    inputs = evaluator.collect_inputs(
        worktree_path=tmp_path,
        change_name="change",
        project=SimpleNamespace(project_id="boxio", openspec_path="openspec", agent_profiles=agent_profiles),
        candidate_sha="c" * 40,
        candidate_clean=True,
        preview_sessions=SimpleNamespace(get_latest_for_candidate=lambda *_: None),
        thinker_provider="codex",
        implementer_provider="codex",
    )
    assert inputs["status"] == "READY"
    scenario_ids = [s["scenario_id"] for s in inputs["scenarios"]]
    assert len(scenario_ids) == 15
    assert len(set(scenario_ids)) == 15
    # The four scenarios that previously suffered collision must be distinct and present
    assert "foundation-workspace:1:1" in scenario_ids
    assert "foundation-workspace:1:2" in scenario_ids
    assert "foundation-workspace:2:1" in scenario_ids
    assert "foundation-workspace:2:2" in scenario_ids
    assert "game-contracts:1:1" in scenario_ids
    assert "game-contracts:1:2" in scenario_ids
    assert "game-contracts:2:1" in scenario_ids
    assert "game-contracts:2:2" in scenario_ids

    # Construct report matching the exact tasks and evidence observed at Boxio gate
    report_tasks = []
    for tid in ["1.1", "1.2", "1.3", "2.1", "2.2", "2.3", "2.4", "3.1", "3.2", "3.3"]:
        report_tasks.append({
            "task_id": tid,
            "actor": "execution",
            "execution_stage": "apply",
            "capability_evidence_refs": ["profile:execution", "workflow:execution:apply"],
            "depends_on_task_ids": [],
            "preconditions": [
                {
                    "required_before_stage": "apply",
                    "satisfied": True,
                    "evidence_refs": [
                        "openspec status: planning artifacts complete",
                        "openspec validate: change is valid",
                        "operator:confirmed",
                        "workflow:execution:apply",
                    ],
                }
            ],
            "completion_evidence": f"Task {tid} done",
        })

    def map_task_ids(sid: str) -> list[str]:
        if sid.startswith("foundation-workspace:1"):
            return ["1.1"]
        elif sid.startswith("foundation-workspace:2"):
            return ["1.2"]
        elif sid.startswith("foundation-workspace:3"):
            return ["1.3"]
        elif sid.startswith("game-contracts:1"):
            return ["2.1"]
        elif sid.startswith("game-contracts:2"):
            return ["2.2"]
        elif sid.startswith("game-contracts:3"):
            return ["2.3"]
        elif sid.startswith("game-contracts:4"):
            return ["2.4"]
        elif sid.startswith("local-assets"):
            return ["3.1", "3.2"]
        return ["1.1"]

    scenario_coverage = [
        {"scenario_id": sid, "task_ids": map_task_ids(sid), "evidence_stage": "apply"}
        for sid in scenario_ids
    ]
    report = {
        "tasks": report_tasks,
        "scenario_coverage": scenario_coverage,
        "blockers": [],
        "resolution_options": [],
    }
    status, tasks, scenarios, blockers, actions = ProposalFeasibilityEvaluator.validate_report(
        report, inputs, tmp_path
    )
    assert status == "EXECUTABLE"
    assert blockers == ()


def test_proposal_feasibility_blocks_when_openspec_cli_fails(tmp_path: Path):
    """Fail-closed: When OpenSpec CLI validate or status fails, proposal feasibility BLOCKS."""
    change_dir = tmp_path / "openspec" / "changes" / "change"
    change_dir.mkdir(parents=True)
    (change_dir / "tasks.md").write_text("## Tasks\n- [ ] 1.1 Task one\n", encoding="utf-8")
    deltas = [
        {"spec": "feature", "requirements": [{"scenarios": [{"rawText": "WHEN run THEN pass"}]}]}
    ]

    # Case 1: validate_change_strict returns FAIL
    failing_validate_adapter = SimpleNamespace(
        show_change=lambda *_: {"deltas": deltas},
        planning_status=lambda *_: {"status": "PASS"},
        validate_change_strict=lambda *_: {"status": "FAIL", "error": "schema error in change"},
    )
    runner = SimpleNamespace(resolve_workflow=MagicMock(return_value=SimpleNamespace(dispatch_command="codex exec")))
    agent_profiles = {
        "thinking": {"agent_id": "codex", "provider_id": "codex"},
        "execution": {"agent_id": "codex", "provider_id": "codex"},
    }
    evaluator = ProposalFeasibilityEvaluator(failing_validate_adapter, runner)
    inputs = evaluator.collect_inputs(
        worktree_path=tmp_path,
        change_name="change",
        project=SimpleNamespace(project_id="boxio", openspec_path="openspec", agent_profiles=agent_profiles),
        candidate_sha="c" * 40,
        candidate_clean=True,
        preview_sessions=SimpleNamespace(get_latest_for_candidate=lambda *_: None),
        thinker_provider="codex",
        implementer_provider="codex",
    )
    assert inputs["status"] == "READY"
    validate_cap = next(c for c in inputs["capabilities"] if c["ref"] == "openspec:validate:valid")
    assert validate_cap["available"] is False

    report = {
        "tasks": [
            {
                "task_id": "1.1",
                "actor": "execution",
                "execution_stage": "apply",
                "capability_evidence_refs": ["profile:execution", "workflow:execution:apply"],
                "depends_on_task_ids": [],
                "preconditions": [
                    {
                        "required_before_stage": "apply",
                        "satisfied": True,
                        "evidence_refs": [
                            "openspec validate: change is valid",
                            "operator:confirmed",
                            "workflow:execution:apply",
                        ],
                    }
                ],
                "completion_evidence": "Done",
            }
        ],
        "scenario_coverage": [
            {"scenario_id": "feature:1:1", "task_ids": ["1.1"], "evidence_stage": "apply"}
        ],
        "blockers": [],
        "resolution_options": [],
    }
    status, tasks, scenarios, blockers, actions = ProposalFeasibilityEvaluator.validate_report(
        report, inputs, tmp_path
    )
    assert status == "BLOCKED"
    assert any("has unverified precondition evidence required before Apply: openspec validate: change is valid" in b for b in blockers)

    # Case 2: planning_status returns INCOMPLETE
    incomplete_status_adapter = SimpleNamespace(
        show_change=lambda *_: {"deltas": deltas},
        planning_status=lambda *_: {"status": "INCOMPLETE", "pending": ["tasks"]},
        validate_change_strict=lambda *_: {"status": "PASS"},
    )
    evaluator_incomplete = ProposalFeasibilityEvaluator(incomplete_status_adapter, runner)
    inputs_incomplete = evaluator_incomplete.collect_inputs(
        worktree_path=tmp_path,
        change_name="change",
        project=SimpleNamespace(project_id="boxio", openspec_path="openspec", agent_profiles=agent_profiles),
        candidate_sha="c" * 40,
        candidate_clean=True,
        preview_sessions=SimpleNamespace(get_latest_for_candidate=lambda *_: None),
        thinker_provider="codex",
        implementer_provider="codex",
    )
    report_status = {
        "tasks": [
            {
                "task_id": "1.1",
                "actor": "execution",
                "execution_stage": "apply",
                "capability_evidence_refs": ["profile:execution", "workflow:execution:apply"],
                "depends_on_task_ids": [],
                "preconditions": [
                    {
                        "required_before_stage": "apply",
                        "satisfied": True,
                        "evidence_refs": [
                            "openspec status: planning artifacts complete",
                            "operator:confirmed",
                            "workflow:execution:apply",
                        ],
                    }
                ],
                "completion_evidence": "Done",
            }
        ],
        "scenario_coverage": [
            {"scenario_id": "feature:1:1", "task_ids": ["1.1"], "evidence_stage": "apply"}
        ],
        "blockers": [],
        "resolution_options": [],
    }
    status2, _, _, blockers2, _ = ProposalFeasibilityEvaluator.validate_report(
        report_status, inputs_incomplete, tmp_path
    )
    assert status2 == "BLOCKED"
    assert any("has unverified precondition evidence required before Apply: openspec status: planning artifacts complete" in b for b in blockers2)


def test_proposal_feasibility_blocks_when_valid_capability_coexists_with_unverified_dependency(tmp_path: Path):
    """Fail-closed: A valid capability ref DOES NOT ignore an unverified dependency in the same precondition."""
    inputs = {
        "status": "READY",
        "tasks": [{"task_id": "1.1", "text": "Setup task"}],
        "scenarios": [{"scenario_id": "feature:1:1", "text": "WHEN run THEN pass"}],
        "capabilities": [
            {"ref": "profile:execution", "kind": "configured_profile", "available": True},
            {"ref": "workflow:execution:apply", "kind": "executable_workflow", "available": True},
            {"ref": "operator:confirmed", "kind": "operator_authorization", "available": True},
        ],
    }
    report = {
        "tasks": [
            {
                "task_id": "1.1",
                "actor": "execution",
                "execution_stage": "apply",
                "capability_evidence_refs": ["profile:execution", "workflow:execution:apply"],
                "depends_on_task_ids": [],
                "preconditions": [
                    {
                        "required_before_stage": "apply",
                        "satisfied": True,
                        "evidence_refs": [
                            "workflow:execution:apply",
                            "operator:confirmed",
                            "database migration 003 must be applied in staging",
                        ],
                    }
                ],
                "completion_evidence": "Setup complete",
            }
        ],
        "scenario_coverage": [
            {"scenario_id": "feature:1:1", "task_ids": ["1.1"], "evidence_stage": "apply"}
        ],
        "blockers": [],
        "resolution_options": [],
    }
    status, tasks, scenarios, blockers, actions = ProposalFeasibilityEvaluator.validate_report(
        report, inputs, tmp_path
    )
    # Must remain BLOCKED fail-closed; the unverified dependency is NOT silently ignored
    assert status == "BLOCKED"
    assert any("has unverified precondition evidence required before Apply" in b for b in blockers)
    assert any("database migration 003 must be applied in staging" in b for b in blockers)




