from __future__ import annotations

from pathlib import Path
from minime.services.proposal_feasibility import ProposalFeasibilityEvaluator


def test_verified_evidence_refs_accepts_directories_and_files(tmp_path: Path):
    # Setup real project directory structure
    src_dir = tmp_path / "src"
    components_dir = src_dir / "components"
    components_dir.mkdir(parents=True)
    existing_file = components_dir / "Button.astro"
    existing_file.write_text("// button", encoding="utf-8")

    styles_dir = src_dir / "styles"
    styles_dir.mkdir(parents=True)
    global_css = styles_dir / "global.css"
    global_css.write_text("/* styles */", encoding="utf-8")

    brand_dir = tmp_path / "public" / "assets" / "brand"
    brand_dir.mkdir(parents=True)

    refs = [
        "path:src",                          # Existing directory
        "path:src/components",               # Existing subdirectory
        "path:src/components/Button.astro",  # Existing file
        "path:src/styles/global.css",        # Existing file
        "path:public/assets/brand",          # Existing directory
        "path:nonexistent/file.txt",         # Missing path
        "path:../../etc/passwd",             # Malicious traversal path
        "workflow:execution:apply",          # Standard capability
        "profile:execution",                 # Standard capability
    ]
    available_refs = {"workflow:execution:apply", "profile:execution"}

    verified, unknown = ProposalFeasibilityEvaluator.verified_evidence_refs(
        refs=refs,
        available_refs=available_refs,
        worktree_path=tmp_path,
    )

    assert "path:src" in verified
    assert "path:src/components" in verified
    assert "path:src/components/Button.astro" in verified
    assert "path:src/styles/global.css" in verified
    assert "path:public/assets/brand" in verified
    assert "workflow:execution:apply" in verified
    assert "profile:execution" in verified

    # Nonexistent path and malicious path traversal remain unknown/rejected
    assert "path:nonexistent/file.txt" in unknown
    assert "path:../../etc/passwd" in unknown
    assert len(unknown) == 2


def test_validate_report_accepts_tasks_with_directory_preconditions(tmp_path: Path):
    src_dir = tmp_path / "src"
    src_dir.mkdir(parents=True)
    new_file = src_dir / "new_file.js"
    new_file.write_text("// js", encoding="utf-8")

    inputs = {
        "status": "READY",
        "openspec_path": "openspec",
        "change_name": "test-change",
        "tasks": [
            {"task_id": "1.1", "text": "Task 1.1"},
        ],
        "scenarios": [
            {"scenario_id": "SC-1", "text": "Scenario 1"},
        ],
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
                "capability_evidence_refs": [
                    "profile:execution",
                    "workflow:execution:apply",
                    "path:src",
                    "path:src/new_file.js",
                ],
                "completion_evidence": "Implementation complete with tests passing.",
                "depends_on_task_ids": [],
                "preconditions": [
                    {
                        "evidence_refs": [
                            "workflow:execution:apply",
                            "path:src",
                        ],
                        "required_before_stage": "apply",
                        "satisfied": True,
                    }
                ],
            }
        ],
        "scenario_coverage": [
            {
                "scenario_id": "SC-1",
                "task_ids": ["1.1"],
                "evidence_stage": "apply",
                "verification_mode": "browser",
                "evidence_refs": ["path:src"],
            }
        ],
    }

    status, tasks, scenarios, blockers, actions = ProposalFeasibilityEvaluator.validate_report(
        report=report,
        inputs=inputs,
        worktree_path=tmp_path,
    )

    assert status == "EXECUTABLE"
    assert len(blockers) == 0
