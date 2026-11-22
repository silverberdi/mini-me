from pathlib import Path
from types import SimpleNamespace

from minime.services.proposal_feasibility import ProposalFeasibilityEvaluator


def test_collect_inputs_omits_preview_capability_when_no_preview_session(tmp_path: Path):
    (tmp_path / "openspec" / "changes" / "test-change").mkdir(parents=True)
    (tmp_path / "openspec" / "changes" / "test-change" / "tasks.md").write_text(
        "## Tasks\n- [ ] 1.1 Do something\n", encoding="utf-8"
    )
    adapter = SimpleNamespace(
        show_change=lambda *_: {
            "deltas": [{"spec": "s", "requirements": [{"id": "1", "scenarios": [{"rawText": "Scenario: ok"}]}]}]
        },
        planning_status=lambda *_: {"status": "PASS"},
        validate_change_strict=lambda *_: {"status": "PASS"},
    )
    profiles = {
        "thinking": {"agent_id": "codex", "provider_id": "codex"},
        "execution": {"agent_id": "codex", "provider_id": "codex"},
    }
    evaluator = ProposalFeasibilityEvaluator(adapter, SimpleNamespace(resolve_workflow=lambda **_: object()))

    # When preview_sessions is None (e.g. static site like Beastie Studio)
    inputs = evaluator.collect_inputs(
        worktree_path=tmp_path,
        change_name="test-change",
        project=SimpleNamespace(project_id="beastie-studio", openspec_path="openspec", agent_profiles=profiles),
        candidate_sha="a" * 40,
        candidate_clean=True,
        preview_sessions=None,
        thinker_provider="codex",
        implementer_provider="codex",
    )

    assert inputs.get("status") == "READY"
    capabilities = inputs.get("capabilities", [])
    preview_caps = [c for c in capabilities if str(c.get("ref", "")).startswith("preview:")]
    assert len(preview_caps) == 0, "No preview capability should be injected when preview_sessions is None"


def test_collect_inputs_includes_preview_capability_when_preview_session_exists(tmp_path: Path):
    (tmp_path / "openspec" / "changes" / "test-change").mkdir(parents=True)
    (tmp_path / "openspec" / "changes" / "test-change" / "tasks.md").write_text(
        "## Tasks\n- [ ] 1.1 Do something\n", encoding="utf-8"
    )
    adapter = SimpleNamespace(
        show_change=lambda *_: {
            "deltas": [{"spec": "s", "requirements": [{"id": "1", "scenarios": [{"rawText": "Scenario: ok"}]}]}]
        },
        planning_status=lambda *_: {"status": "PASS"},
        validate_change_strict=lambda *_: {"status": "PASS"},
    )
    profiles = {
        "thinking": {"agent_id": "codex", "provider_id": "codex"},
        "execution": {"agent_id": "codex", "provider_id": "codex"},
    }
    evaluator = ProposalFeasibilityEvaluator(adapter, SimpleNamespace(resolve_workflow=lambda **_: object()))

    fake_preview = SimpleNamespace(
        status=SimpleNamespace(value="READY"),
        head_sha="a" * 40,
        preview_url="http://preview.local:8090",
        preview_id="prev-123",
    )
    fake_preview_repo = SimpleNamespace(
        get_latest_for_candidate=lambda *_: fake_preview
    )

    inputs = evaluator.collect_inputs(
        worktree_path=tmp_path,
        change_name="test-change",
        project=SimpleNamespace(project_id="boxio", openspec_path="openspec", agent_profiles=profiles),
        candidate_sha="a" * 40,
        candidate_clean=True,
        preview_sessions=fake_preview_repo,
        thinker_provider="codex",
        implementer_provider="codex",
    )

    assert inputs.get("status") == "READY"
    capabilities = inputs.get("capabilities", [])
    preview_caps = [c for c in capabilities if str(c.get("ref", "")).startswith("preview:")]
    assert len(preview_caps) == 1
    assert preview_caps[0]["available"] is True
    assert preview_caps[0]["ref"] == f"preview:{'a' * 40}"


def test_blockers_before_stage_ignores_phantom_preview_precondition_when_no_preview_available(tmp_path: Path):
    evaluator = ProposalFeasibilityEvaluator(SimpleNamespace(), SimpleNamespace())

    task_with_preview_precondition = [
        {
            "task_id": "4.4",
            "actor": "execution",
            "execution_stage": "pre_pr",
            "preconditions": [
                {
                    "required_before_stage": "pre_pr",
                    "evidence_refs": [f"preview:{'9' * 40}"],
                }
            ],
        }
    ]

    inputs_without_preview = {
        "status": "READY",
        "capabilities": [
            {"ref": "profile:execution", "available": True},
            {"ref": "operator:confirmed", "available": True},
        ],
        "openspec_path": "openspec",
        "change_name": "test-change",
    }

    blockers = evaluator.blockers_before_stage(
        task_with_preview_precondition,
        stage="pre_pr",
        inputs=inputs_without_preview,
        worktree_path=tmp_path,
    )

    # The phantom preview precondition must not block pre_pr when no preview service exists
    assert len(blockers) == 0, f"Expected 0 blockers, got: {blockers}"
