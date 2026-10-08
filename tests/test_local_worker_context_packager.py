"""Unit tests for LocalWorkerContextPackager, strict budget contract, multi-file fallback, task-class scoping, and fail-closed CONTEXT_NOT_READY execution semantics."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from minime.local_worker.context_packager import extract_candidate_symbols, package_task_context
from minime.local_worker.harness import format_patch_policy_corrective_reason
from minime.local_worker.models import (
    DEFAULT_CONTEXT_BUDGET_CHARS,
    LocalTaskClass,
    LocalTaskEnvelope,
    LocalValidationVerdict,
    ValidationResult,
)
from minime.local_worker.patch_applier import PatchPolicyDecision
from minime.local_worker.service import LocalWorkerService


def test_symbol_extraction_from_instruction():
    instruction = (
        "Repair stale test fixture in tests/test_foo.py so "
        "test_bar_deterministic_selection matches the current contract. "
        "Modify only this test file."
    )
    symbols = extract_candidate_symbols(instruction)
    assert "test_bar_deterministic_selection" in symbols


def test_package_context_finds_symbol_and_retains_full_function(tmp_path):
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
    pkg_res = package_task_context(
        instruction=instruction,
        task_class=LocalTaskClass.TEST_AUTHORING,
        allowed_files=[rel_path],
        worktree_path=tmp_path,
        max_budget_chars=12000,
    )

    assert pkg_res.success is True
    assert pkg_res.status == "OK"
    assert len(pkg_res.context) <= 12000
    assert f"FILE: {rel_path}" in pkg_res.context
    assert "SYMBOL: test_target_fixture_repair" in pkg_res.context
    assert "def test_target_fixture_repair():" in pkg_res.context
    assert "assert val == 123" in pkg_res.context


def test_oversized_target_symbol_fails_closed(tmp_path):
    """Requirement A: Target symbol exceeding hard budget fails closed with explicit status."""
    rel_path = "tests/test_big_symbol.py"
    target_file = tmp_path / rel_path
    target_file.parent.mkdir(parents=True, exist_ok=True)

    lines = ["    x = 1"] * 50
    big_fn = "def test_oversized():\n" + "\n".join(lines) + "\n    assert True\n"
    target_file.write_text(big_fn, encoding="utf-8")

    instruction = "Fix test_oversized"
    pkg_res = package_task_context(
        instruction=instruction,
        task_class=LocalTaskClass.TEST_AUTHORING,
        allowed_files=[rel_path],
        worktree_path=tmp_path,
        max_budget_chars=300,  # Hard budget smaller than mandatory minimal target symbol
    )

    assert pkg_res.success is False
    assert pkg_res.context == ""
    assert pkg_res.status == "TARGET_SYMBOL_EXCEEDS_BUDGET"


def test_multi_file_fallback_budget_accounting_exact(tmp_path):
    """Requirement A: Multi-file fallback correctly accounts for inter-part separators and stays strictly <= max_budget_chars."""
    file1_rel = "tests/test_a.py"
    file2_rel = "tests/test_b.py"

    (tmp_path / file1_rel).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / file1_rel).write_text("line1\nline2\nline3\n", encoding="utf-8")
    (tmp_path / file2_rel).write_text("lineA\nlineB\nlineC\n", encoding="utf-8")

    tight_budget = 45

    pkg_res = package_task_context(
        instruction="no symbol match",
        task_class=LocalTaskClass.SMALL_CODE_FIX,
        allowed_files=[file1_rel, file2_rel],
        worktree_path=tmp_path,
        max_budget_chars=tight_budget,
    )

    assert pkg_res.success is True
    assert pkg_res.status == "FALLBACK_EXCERPT"
    assert len(pkg_res.context) <= tight_budget


def test_adjacent_and_header_content_trimmed_first(tmp_path):
    """Requirement A: Header/adjacent content is trimmed first while complete symbol is retained."""
    rel_path = "tests/test_trimming.py"
    target_file = tmp_path / rel_path
    target_file.parent.mkdir(parents=True, exist_ok=True)

    header = '"""Very long header docstring."""\n' + "# header line\n" * 20
    target_fn = "def test_compact():\n    assert 1 == 1\n"
    adjacent = "\n# adjacent comment\n" * 20
    target_file.write_text(header + target_fn + adjacent, encoding="utf-8")

    instruction = "Fix test_compact"
    pkg_res = package_task_context(
        instruction=instruction,
        task_class=LocalTaskClass.TEST_AUTHORING,
        allowed_files=[rel_path],
        worktree_path=tmp_path,
        max_budget_chars=300,
    )

    assert pkg_res.success is True
    assert len(pkg_res.context) <= 300
    assert "def test_compact():" in pkg_res.context
    assert "assert 1 == 1" in pkg_res.context


def test_task_class_governs_symbol_packaging(tmp_path):
    """Requirement B: Symbol-aware packaging applies to TEST_AUTHORING; SMALL_CODE_FIX uses fallback."""
    rel_path = "tests/test_governance.py"
    target_file = tmp_path / rel_path
    target_file.parent.mkdir(parents=True, exist_ok=True)

    content = "def test_my_func():\n    return 42\n"
    target_file.write_text(content, encoding="utf-8")

    instruction = "Fix test_my_func"

    # TEST_AUTHORING => symbol aware
    res_test = package_task_context(
        instruction=instruction,
        task_class=LocalTaskClass.TEST_AUTHORING,
        allowed_files=[rel_path],
        worktree_path=tmp_path,
    )
    assert res_test.status == "OK"
    assert "SYMBOL: test_my_func" in res_test.context

    # SMALL_CODE_FIX => fallback excerpt
    res_code = package_task_context(
        instruction=instruction,
        task_class=LocalTaskClass.SMALL_CODE_FIX,
        allowed_files=[rel_path],
        worktree_path=tmp_path,
    )
    assert res_code.status == "FALLBACK_EXCERPT"
    assert "SYMBOL:" not in res_code.context
    assert "FILE: tests/test_governance.py" in res_code.context


@pytest.mark.asyncio
async def test_successful_packaged_context_dispatches_inference(tmp_path):
    """Requirement C1: Successful packaged context proceeds to inference."""
    rel_path = "tests/test_ok.py"
    (tmp_path / rel_path).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / rel_path).write_text("def test_ok_symbol(): pass\n", encoding="utf-8")

    adapter = AsyncMock()
    adapter.model = "qwen2.5-coder:7b-instruct-q4_K_M"
    adapter.provider = "ollama"

    from minime.domain.enums import ProviderResultClass
    from minime.local_worker.models import PreflightResult, PreflightStatus
    from minime.local_worker.ollama_adapter import OllamaGenerateResponse

    adapter.preflight.return_value = PreflightResult(
        provider="ollama", model=adapter.model, status=PreflightStatus.READY, reachable=True, model_present=True
    )
    adapter.generate.return_value = OllamaGenerateResponse(
        result_class=ProviderResultClass.SUCCESS,
        text='{"kind":"NO_CHANGE_JUSTIFIED","summary":"ok","files_changed":[],"patch":null,"confidence":1.0,"escalation_required":false,"escalation_reason":"","next_action":"none"}',
    )

    service = LocalWorkerService(adapter=adapter)
    task = LocalTaskEnvelope(
        role="LOCAL_WORKER",
        task_class=LocalTaskClass.TEST_AUTHORING,
        allowed_files=[rel_path],
        instruction="Fix test_ok_symbol",
    )
    validator = AsyncMock(return_value=ValidationResult(verdict=LocalValidationVerdict.PASS))

    outcome = await service.run(task, validator=validator, worktree_path=tmp_path)

    assert outcome.evidence.result_class == "SUCCESS"
    assert adapter.generate.call_count == 1


@pytest.mark.asyncio
async def test_packaging_failure_with_bounded_caller_context_dispatches(tmp_path):
    """Requirement C2: Packaging failure + valid bounded caller context proceeds to inference."""
    adapter = AsyncMock()
    adapter.model = "qwen2.5-coder:7b-instruct-q4_K_M"
    adapter.provider = "ollama"

    from minime.domain.enums import ProviderResultClass
    from minime.local_worker.models import PreflightResult, PreflightStatus
    from minime.local_worker.ollama_adapter import OllamaGenerateResponse

    adapter.preflight.return_value = PreflightResult(
        provider="ollama", model=adapter.model, status=PreflightStatus.READY, reachable=True, model_present=True
    )
    adapter.generate.return_value = OllamaGenerateResponse(
        result_class=ProviderResultClass.SUCCESS,
        text='{"kind":"NO_CHANGE_JUSTIFIED","summary":"ok","files_changed":[],"patch":null,"confidence":1.0,"escalation_required":false,"escalation_reason":"","next_action":"none"}',
    )

    service = LocalWorkerService(adapter=adapter)
    task = LocalTaskEnvelope(
        role="LOCAL_WORKER",
        task_class=LocalTaskClass.TEST_AUTHORING,
        allowed_files=["nonexistent_file.py"],  # Packaging fails
        instruction="Fix test_nonexistent",
        context="BOUNDED_CALLER_CONTEXT",
    )
    validator = AsyncMock(return_value=ValidationResult(verdict=LocalValidationVerdict.PASS))

    outcome = await service.run(task, validator=validator, worktree_path=tmp_path)

    assert outcome.evidence.result_class == "SUCCESS"
    assert adapter.generate.call_count == 1


@pytest.mark.asyncio
async def test_packaging_failure_no_caller_context_fails_closed_zero_inference(tmp_path):
    """Requirement C3: Packaging failure + no caller context -> ZERO adapter.generate calls, CONTEXT_NOT_READY evidence."""
    adapter = AsyncMock()
    adapter.model = "qwen2.5-coder:7b-instruct-q4_K_M"
    adapter.provider = "ollama"

    from minime.local_worker.models import PreflightResult, PreflightStatus
    adapter.preflight.return_value = PreflightResult(
        provider="ollama", model=adapter.model, status=PreflightStatus.READY, reachable=True, model_present=True
    )

    service = LocalWorkerService(adapter=adapter)
    task = LocalTaskEnvelope(
        role="LOCAL_WORKER",
        task_class=LocalTaskClass.TEST_AUTHORING,
        allowed_files=["nonexistent_file.py"],  # Packaging fails
        instruction="Fix test_nonexistent",
        context="",  # No caller context
    )
    validator = AsyncMock(return_value=ValidationResult(verdict=LocalValidationVerdict.PASS))

    outcome = await service.run(task, validator=validator, worktree_path=tmp_path)

    assert outcome.evidence.result_class == "CONTEXT_NOT_READY"
    assert outcome.evidence.escalation.required is True
    assert outcome.evidence.corrections_used == 0
    assert outcome.evidence.attempt == 0
    assert adapter.generate.call_count == 0  # ZERO LLM calls!


@pytest.mark.asyncio
async def test_packaging_failure_oversized_caller_context_fails_closed_zero_inference(tmp_path):
    """Requirement C4: Packaging failure + oversized caller context -> ZERO adapter.generate calls."""
    adapter = AsyncMock()
    adapter.model = "qwen2.5-coder:7b-instruct-q4_K_M"
    adapter.provider = "ollama"

    from minime.local_worker.models import PreflightResult, PreflightStatus
    adapter.preflight.return_value = PreflightResult(
        provider="ollama", model=adapter.model, status=PreflightStatus.READY, reachable=True, model_present=True
    )

    service = LocalWorkerService(adapter=adapter)
    oversized_ctx = "x" * (DEFAULT_CONTEXT_BUDGET_CHARS + 100)
    task = LocalTaskEnvelope(
        role="LOCAL_WORKER",
        task_class=LocalTaskClass.TEST_AUTHORING,
        allowed_files=["nonexistent_file.py"],
        instruction="Fix test_nonexistent",
        context=oversized_ctx,
    )
    validator = AsyncMock(return_value=ValidationResult(verdict=LocalValidationVerdict.PASS))

    outcome = await service.run(task, validator=validator, worktree_path=tmp_path)

    assert outcome.evidence.result_class == "CONTEXT_NOT_READY"
    assert outcome.evidence.escalation.required is True
    assert adapter.generate.call_count == 0  # ZERO LLM calls!


@pytest.mark.asyncio
async def test_target_symbol_exceeds_budget_fails_closed_zero_inference(tmp_path):
    """Requirement C5: TARGET_SYMBOL_EXCEEDS_BUDGET -> ZERO inference calls when no valid fallback context exists."""
    rel_path = "tests/test_oversized.py"
    (tmp_path / rel_path).parent.mkdir(parents=True, exist_ok=True)
    big_fn = "def test_oversized_symbol():\n" + "\n".join(["    x = 1"] * 2000) + "\n"
    (tmp_path / rel_path).write_text(big_fn, encoding="utf-8")

    adapter = AsyncMock()
    adapter.model = "qwen2.5-coder:7b-instruct-q4_K_M"
    adapter.provider = "ollama"

    from minime.local_worker.models import PreflightResult, PreflightStatus
    adapter.preflight.return_value = PreflightResult(
        provider="ollama", model=adapter.model, status=PreflightStatus.READY, reachable=True, model_present=True
    )

    service = LocalWorkerService(adapter=adapter)
    task = LocalTaskEnvelope(
        role="LOCAL_WORKER",
        task_class=LocalTaskClass.TEST_AUTHORING,
        allowed_files=[rel_path],
        instruction="Fix test_oversized_symbol",
        context="",
    )
    validator = AsyncMock(return_value=ValidationResult(verdict=LocalValidationVerdict.PASS))

    outcome = await service.run(task, validator=validator, worktree_path=tmp_path)

    assert outcome.evidence.result_class == "CONTEXT_NOT_READY"
    assert "TARGET_SYMBOL_EXCEEDS_BUDGET" in outcome.evidence.summary
    assert outcome.evidence.escalation.required is True
    assert outcome.evidence.corrections_used == 0
    assert outcome.evidence.attempt == 0
    assert adapter.generate.call_count == 0  # ZERO LLM calls!


def test_context_never_pulls_from_unauthorized_files(tmp_path):
    allowed_rel = "tests/test_allowed.py"
    unauthorized_rel = "tests/test_forbidden.py"

    (tmp_path / allowed_rel).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / allowed_rel).write_text("def test_allowed_sym(): assert True\n", encoding="utf-8")
    (tmp_path / unauthorized_rel).write_text("def test_forbidden_sym(): assert False\n", encoding="utf-8")

    instruction = "Fix test_forbidden_sym and test_allowed_sym"
    pkg_res = package_task_context(
        instruction=instruction,
        task_class=LocalTaskClass.TEST_AUTHORING,
        allowed_files=[allowed_rel],
        worktree_path=tmp_path,
    )

    assert f"FILE: {allowed_rel}" in pkg_res.context
    assert "test_forbidden_sym" not in pkg_res.context
    assert unauthorized_rel not in pkg_res.context


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
