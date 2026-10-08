"""Unit tests for LocalWorkerContextPackager and corrective patch policy feedback."""

from __future__ import annotations

from minime.local_worker.context_packager import extract_candidate_symbols, package_task_context
from minime.local_worker.harness import format_patch_policy_corrective_reason
from minime.local_worker.models import LocalTaskClass, LocalTaskEnvelope
from minime.local_worker.patch_applier import PatchPolicyDecision


def test_symbol_extraction_from_instruction():
    instruction = (
        "Repair stale test fixture in tests/test_foo.py so "
        "test_bar_deterministic_selection matches the current contract. "
        "Modify only this test file."
    )
    symbols = extract_candidate_symbols(instruction)
    assert "test_bar_deterministic_selection" in symbols


def test_package_context_finds_symbol_and_retains_full_function(tmp_path):
    # Setup test file in tmp_path
    rel_path = "tests/test_sample.py"
    target_file = tmp_path / rel_path
    target_file.parent.mkdir(parents=True, exist_ok=True)

    header = '"""Module docstring."""\nimport pytest\n\n'
    dummy_fn = "def test_unrelated():\n    assert True\n\n"
    target_fn = (
        "def test_target_fixture_repair():\n"
        "    # Step 1: setup\n"
        "    val = 123\n"
        "    # Step 2: assert\n"
        "    assert val == 123\n"
    )
    target_file.write_text(header + dummy_fn + target_fn, encoding="utf-8")

    instruction = "Repair test_target_fixture_repair in tests/test_sample.py"
    packaged = package_task_context(
        instruction=instruction,
        task_class=LocalTaskClass.TEST_AUTHORING,
        allowed_files=[rel_path],
        worktree_path=tmp_path,
        max_budget_chars=12000,
    )

    assert f"FILE: {rel_path}" in packaged
    assert "SYMBOL: test_target_fixture_repair" in packaged
    assert "def test_target_fixture_repair():" in packaged
    assert "assert val == 123" in packaged
    assert packaged.endswith("assert val == 123") or "--- ADJACENT" in packaged or "assert val == 123\n" in packaged


def test_context_never_pulls_from_unauthorized_files(tmp_path):
    allowed_rel = "tests/test_allowed.py"
    unauthorized_rel = "tests/test_forbidden.py"

    (tmp_path / allowed_rel).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / allowed_rel).write_text("def test_allowed_sym(): assert True\n", encoding="utf-8")
    (tmp_path / unauthorized_rel).write_text("def test_forbidden_sym(): assert False\n", encoding="utf-8")

    instruction = "Fix test_forbidden_sym and test_allowed_sym"
    packaged = package_task_context(
        instruction=instruction,
        task_class=LocalTaskClass.TEST_AUTHORING,
        allowed_files=[allowed_rel],
        worktree_path=tmp_path,
    )

    assert f"FILE: {allowed_rel}" in packaged
    assert "test_forbidden_sym" not in packaged
    assert unauthorized_rel not in packaged


def test_context_packaging_is_deterministic(tmp_path):
    rel_path = "tests/test_deterministic.py"
    (tmp_path / rel_path).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / rel_path).write_text("def test_foo(): pass\n", encoding="utf-8")

    instruction = "Fix test_foo in tests/test_deterministic.py"

    res1 = package_task_context(
        instruction=instruction,
        task_class=LocalTaskClass.TEST_AUTHORING,
        allowed_files=[rel_path],
        worktree_path=tmp_path,
    )
    res2 = package_task_context(
        instruction=instruction,
        task_class=LocalTaskClass.TEST_AUTHORING,
        allowed_files=[rel_path],
        worktree_path=tmp_path,
    )

    assert res1 == res2


def test_missing_symbol_falls_back_safely(tmp_path):
    rel_path = "tests/test_fallback.py"
    (tmp_path / rel_path).parent.mkdir(parents=True, exist_ok=True)
    content = "import os\n\ndef helper():\n    return 42\n"
    (tmp_path / rel_path).write_text(content, encoding="utf-8")

    instruction = "No explicit symbol matching here"
    packaged = package_task_context(
        instruction=instruction,
        task_class=LocalTaskClass.TEST_AUTHORING,
        allowed_files=[rel_path],
        worktree_path=tmp_path,
    )

    assert f"FILE: {rel_path}" in packaged
    assert "SYMBOL:" not in packaged
    assert "import os" in packaged


def test_budget_is_respected_and_function_not_cut(tmp_path):
    rel_path = "tests/test_budget.py"
    (tmp_path / rel_path).parent.mkdir(parents=True, exist_ok=True)

    long_body = "\n".join([f"    x_{i} = {i}" for i in range(100)])
    code = f"def test_big():\n{long_body}\n    assert True\n"
    (tmp_path / rel_path).write_text(code, encoding="utf-8")

    instruction = "Fix test_big"
    packaged = package_task_context(
        instruction=instruction,
        task_class=LocalTaskClass.TEST_AUTHORING,
        allowed_files=[rel_path],
        worktree_path=tmp_path,
        max_budget_chars=500,  # Small budget
    )

    assert f"FILE: {rel_path}" in packaged
    assert "SYMBOL: test_big" in packaged
    assert "def test_big():" in packaged
    assert "assert True" in packaged  # Complete function body retained despite small budget


def test_corrective_feedback_unauthorized_file():
    decision = PatchPolicyDecision(
        valid=False,
        touched_files=("tests/test_scheduler.py",),
        reason="Touched file 'tests/test_scheduler.py' is not in allowed_files",
    )
    envelope = LocalTaskEnvelope(
        role="LOCAL_WORKER",
        task_class=LocalTaskClass.TEST_AUTHORING,
        allowed_files=["tests/test_autonomous_intake_admission.py"],
        instruction="Fix test",
    )

    msg = format_patch_policy_corrective_reason(decision, envelope)

    assert "Previous patch targeted an unauthorized file:" in msg
    assert "tests/test_scheduler.py" in msg
    assert "tests/test_autonomous_intake_admission.py" in msg
    assert "Return a valid unified diff modifying only authorized files." in msg


def test_corrective_feedback_malformed_diff():
    decision = PatchPolicyDecision(
        valid=False,
        touched_files=(),
        reason="Patch contained no valid touched files",
    )
    envelope = LocalTaskEnvelope(
        role="LOCAL_WORKER",
        task_class=LocalTaskClass.TEST_AUTHORING,
        allowed_files=["foo.py"],
        instruction="Fix foo",
    )

    msg = format_patch_policy_corrective_reason(decision, envelope)

    assert "Previous patch violated patch policy formatting" in msg
    assert "--- a/<allowed-relative-path>" in msg
    assert "+++ b/<allowed-relative-path>" in msg
    assert "@@ ... @@" in msg
