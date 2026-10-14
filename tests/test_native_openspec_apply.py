import hashlib
import json
from pathlib import Path

import pytest

from minime.config import CliInvocationProfile
from minime.services.implementer_runner import CliImplementerRunner
from minime.services.native_openspec_apply import (
    CODEX_APPLY_SKILL_PATH,
    NativeOpenSpecWorkflowUnavailable,
    parse_codex_apply_jsonl,
    resolve_codex_openspec_apply,
    workflow_unchanged,
)

_SKILL = """---
name: openspec-apply-change
description: Apply a change.
metadata:
  version: \"1.0\"
---
Use the native OpenSpec workflow.
"""


def _install_skill(root: Path, content: str = _SKILL) -> Path:
    skill = root / CODEX_APPLY_SKILL_PATH
    skill.parent.mkdir(parents=True)
    skill.write_text(content, encoding="utf-8")
    return skill


def test_resolve_native_apply_binds_exact_skill_hash_and_slug(tmp_path):
    skill = _install_skill(tmp_path)

    resolved = resolve_codex_openspec_apply(
        tmp_path,
        "sample-change",
        project_id="project-1",
        repository_identity="github.com/acme/repo",
        run_id="run-1",
        job_id="job-1",
        attempt_id="attempt-2",
        generation=3,
        base_sha="a" * 40,
    )

    assert resolved.workflow_name == "openspec-apply-change"
    assert resolved.version == "1.0"
    assert resolved.workflow_sha256 == hashlib.sha256(skill.read_bytes()).hexdigest()
    assert "$openspec-apply-change sample-change" in resolved.dispatch_instruction()
    assert "free-form implementation prompt" in resolved.dispatch_instruction()
    instruction = resolved.dispatch_instruction()
    for identity in (
        "project-1",
        "github.com/acme/repo",
        "run-1",
        "job-1",
        "attempt-2",
        "Candidate generation: 3",
        "Admitted base SHA: " + "a" * 40,
        "Stage: APPLY",
    ):
        assert identity in instruction
    assert workflow_unchanged(tmp_path, resolved)


@pytest.mark.parametrize("change_name", ["../escape", "/absolute", "", "bad name"])
def test_resolve_native_apply_rejects_unsafe_change_name(tmp_path, change_name):
    _install_skill(tmp_path)

    with pytest.raises(NativeOpenSpecWorkflowUnavailable, match="safe slug"):
        resolve_codex_openspec_apply(tmp_path, change_name)


def test_resolve_native_apply_fails_closed_for_missing_or_wrong_skill(tmp_path):
    with pytest.raises(NativeOpenSpecWorkflowUnavailable, match="missing"):
        resolve_codex_openspec_apply(tmp_path, "sample-change")

    _install_skill(tmp_path, _SKILL.replace("openspec-apply-change", "wrong-skill", 1))
    with pytest.raises(NativeOpenSpecWorkflowUnavailable, match="does not identify"):
        resolve_codex_openspec_apply(tmp_path, "sample-change")


def test_resolve_native_apply_rejects_symlink_escape(tmp_path):
    external = tmp_path / "external"
    external.mkdir()
    (external / "SKILL.md").write_text(_SKILL, encoding="utf-8")
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    (worktree / ".agents").symlink_to(external, target_is_directory=True)

    with pytest.raises(NativeOpenSpecWorkflowUnavailable, match="symlink"):
        resolve_codex_openspec_apply(worktree, "sample-change")


def test_codex_jsonl_trace_requires_skill_read_and_exact_apply_instructions():
    change = "sample-change"
    skill_command = f"cat {CODEX_APPLY_SKILL_PATH}"
    apply_command = f"openspec instructions apply --change {change} --json"
    lines = [
        json.dumps(
            {
                "type": "item.completed",
                "item": {
                    "id": "tool-1",
                    "type": "command_execution",
                    "command": skill_command,
                    "exit_code": 0,
                    "status": "completed",
                    "aggregated_output": "secret output must not be persisted",
                },
            }
        ),
        json.dumps(
            {
                "type": "item.completed",
                "item": {
                    "id": "tool-2",
                    "type": "command_execution",
                    "command": apply_command,
                    "exit_code": 0,
                    "status": "completed",
                },
            }
        ),
        json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "Done"}}),
    ]

    messages, evidence = parse_codex_apply_jsonl(
        lines,
        change_name=change,
        workflow_path=CODEX_APPLY_SKILL_PATH,
        workflow_sha256="a" * 64,
    )

    assert messages == ["Done"]
    assert evidence["workflow_observed"] is True
    assert evidence["skill_read_observed"] is True
    assert evidence["apply_instructions_observed"] is True
    assert "secret output" not in json.dumps(evidence)


def test_codex_jsonl_trace_rejects_wrong_change_and_malformed_events():
    line = json.dumps(
        {
            "type": "item.completed",
            "item": {
                "type": "command_execution",
                "command": "openspec instructions apply --change another-change --json",
                "exit_code": 0,
                "status": "completed",
            },
        }
    )

    _, wrong_change = parse_codex_apply_jsonl(
        [line],
        change_name="sample-change",
        workflow_path=CODEX_APPLY_SKILL_PATH,
        workflow_sha256="b" * 64,
    )
    _, malformed = parse_codex_apply_jsonl(
        [line, "not-json"],
        change_name="sample-change",
        workflow_path=CODEX_APPLY_SKILL_PATH,
        workflow_sha256="b" * 64,
    )

    assert wrong_change["workflow_observed"] is False
    assert malformed["jsonl_complete"] is False
    assert malformed["workflow_observed"] is False


def test_codex_jsonl_trace_does_not_accept_change_name_substring():
    line = json.dumps(
        {
            "type": "item.completed",
            "item": {
                "type": "command_execution",
                "command": "openspec instructions apply --change sample-change-extra --json",
                "exit_code": 0,
                "status": "completed",
            },
        }
    )
    _, evidence = parse_codex_apply_jsonl(
        [line],
        change_name="sample-change",
        workflow_path=CODEX_APPLY_SKILL_PATH,
        workflow_sha256="c" * 64,
    )
    assert evidence["apply_instructions_observed"] is False
    assert evidence["workflow_observed"] is False


def test_codex_implementer_command_enables_json_tool_trace():
    profile = CliInvocationProfile(
        provider="codex",
        role="implementer",
        executable="codex",
        args=("exec", "-", "--approve-for-me", "--ephemeral"),
        prompt_transport="stdin",
    )
    runner = CliImplementerRunner(profile)

    command = runner._command_for_prompt("$openspec-apply-change sample-change")

    assert command[1:4] == ["exec", "--json", "-"]
    assert "--approve-for-me" in command
    assert "--ephemeral" in command
