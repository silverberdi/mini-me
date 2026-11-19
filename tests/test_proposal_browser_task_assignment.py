from pathlib import Path
from types import SimpleNamespace
from copy import deepcopy

from minime.services.proposal_feasibility import ProposalFeasibilityEvaluator


def test_browser_scenarios_are_executor_work_and_real_decisions_stay_human(tmp_path: Path):
    (tmp_path / "package.json").write_text(
        '{"scripts":{"test:e2e":"playwright test"}}', encoding="utf-8"
    )
    (tmp_path / "openspec" / "changes" / "browser" ).mkdir(parents=True)
    (tmp_path / "openspec" / "changes" / "browser" / "tasks.md").write_text(
        "## Tasks\n- [ ] 1.1 Browser acceptance checks\n- [ ] 1.2 Obtain the operator's product decision\n- [ ] 1.3 Validate on a physical iPhone after merge\n",
        encoding="utf-8",
    )
    browser_scenarios = [
        "Scenario: browser navigation is correct",
        "Scenario: asynchronous UI updates are visible",
        "Scenario: responsive viewport remains usable",
        "Scenario: concurrent browser sessions remain isolated",
    ]
    raw_scenarios = [
        *browser_scenarios,
        "Scenario: operator chooses the privacy policy",
        "Scenario: physical iPhone audio behavior is recorded after merge",
    ]
    adapter = SimpleNamespace(
        show_change=lambda *_: {
            "deltas": [
                {
                    "spec": "ui",
                    "requirements": [{"id": "1", "scenarios": [{"rawText": text} for text in raw_scenarios]}],
                }
            ]
        },
        planning_status=lambda *_: {"status": "PASS"},
        validate_change_strict=lambda *_: {"status": "PASS"},
    )
    profiles = {
        "thinking": {"agent_id": "codex", "provider_id": "codex"},
        "execution": {"agent_id": "codex", "provider_id": "codex"},
    }
    evaluator = ProposalFeasibilityEvaluator(adapter, SimpleNamespace(resolve_workflow=lambda **_: object()))
    inputs = evaluator.collect_inputs(
        worktree_path=tmp_path,
        change_name="browser",
        project=SimpleNamespace(project_id="boxio", openspec_path="openspec", agent_profiles=profiles),
        candidate_sha="a" * 40,
        candidate_clean=True,
        preview_sessions=None,
        thinker_provider="codex",
        implementer_provider="codex",
    )
    assert inputs["test_tooling"]["playwright_declared"] is True
    assert any(item["command"] == "npm run test:e2e" for item in inputs["test_tooling"]["declared_test_commands"])

    report = {
        "tasks": [
            {
                "task_id": "1.1",
                "actor": "execution",
                "execution_stage": "apply",
                "capability_evidence_refs": ["profile:execution", "workflow:execution:apply"],
                "depends_on_task_ids": [],
                "preconditions": [],
                "completion_evidence": "Playwright result, exit code, output, and candidate SHA",
            },
            {
                "task_id": "1.2",
                "actor": "operator",
                "execution_stage": "human_validation",
                "capability_evidence_refs": ["operator:confirmed"],
                "depends_on_task_ids": [],
                "preconditions": [],
                "completion_evidence": "The operator's recorded decision",
            },
            {
                "task_id": "1.3",
                "actor": "operator",
                "execution_stage": "human_validation",
                "capability_evidence_refs": ["operator:confirmed"],
                "depends_on_task_ids": [],
                "preconditions": [],
                "completion_evidence": "Record the observed physical iPhone result after merge; do not claim it passed early.",
            },
        ],
        "scenario_coverage": [
            {
                "scenario_id": scenario["scenario_id"],
                "task_ids": [
                    "1.2" if "privacy policy" in scenario["text"]
                    else "1.3" if "physical iPhone" in scenario["text"]
                    else "1.1"
                ],
                "evidence_stage": "human_validation" if "privacy policy" in scenario["text"] or "physical iPhone" in scenario["text"] else "apply",
                "verification_mode": (
                    "human_decision" if "privacy policy" in scenario["text"]
                    else "physical_device" if "physical iPhone" in scenario["text"]
                    else "browser"
                ),
            }
            for scenario in inputs["scenarios"]
        ],
        "blockers": [],
        "resolution_options": [],
    }

    status, tasks, scenarios, blockers, _ = ProposalFeasibilityEvaluator.validate_report(
        report, inputs, tmp_path
    )

    assert status == "EXECUTABLE"
    assert blockers == ()
    assert [(task["task_id"], task["actor"], task["execution_stage"]) for task in tasks] == [
        ("1.1", "execution", "apply"),
        ("1.2", "operator", "human_validation"),
        ("1.3", "operator", "human_validation"),
    ]
    assert len(scenarios) == 6

    incorrect_mapping = deepcopy(report)
    for item in incorrect_mapping["scenario_coverage"]:
        if item["verification_mode"] == "browser":
            item["task_ids"] = ["1.2"]
            item["evidence_stage"] = "human_validation"
    blocked = ProposalFeasibilityEvaluator.validate_report(incorrect_mapping, inputs, tmp_path)
    assert blocked[0] == "BLOCKED"
    assert any("browser-reproducible work outside executor Apply/Verify" in issue for issue in blocked[3])
    assert ProposalFeasibilityEvaluator.only_correctable_structure_blockers(blocked[3])
