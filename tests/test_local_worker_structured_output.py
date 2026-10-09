"""Targeted unit tests for local worker structured output schema, adapter formatting, and corrective prompt flow."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from minime.domain.enums import ProviderResultClass
from minime.local_worker.harness import parse_structured_result
from minime.local_worker.models import (
    LOCAL_WORKER_RESPONSE_SCHEMA,
    LocalResultKind,
    LocalTaskClass,
    LocalTaskEnvelope,
    LocalValidationVerdict,
    ValidationResult,
)
from minime.local_worker.ollama_adapter import LocalOllamaAdapter
from minime.local_worker.service import LocalWorkerService
from minime.logging import redact_secrets


def test_schema_cannot_select_uncertain():
    """Requirement 5: Model cannot select UNCERTAIN via the provider schema."""
    enum_values = LOCAL_WORKER_RESPONSE_SCHEMA["properties"]["kind"]["enum"]
    assert "CHANGES_PROPOSED" in enum_values
    assert "NO_CHANGE_JUSTIFIED" in enum_values
    assert "UNCERTAIN" not in enum_values
    assert LOCAL_WORKER_RESPONSE_SCHEMA.get("additionalProperties") is False


def test_parse_valid_changes_proposed():
    """Requirement 3: Valid structured CHANGES_PROPOSED JSON parses correctly."""
    raw = json.dumps(
        {
            "kind": "CHANGES_PROPOSED",
            "summary": "Fix test fixture",
            "files_changed": ["tests/test_foo.py"],
            "patch": "--- a/tests/test_foo.py\n+++ b/tests/test_foo.py\n@@ -1 +1 @@\n-old\n+new\n",
            "confidence": 0.95,
            "escalation_required": False,
            "escalation_reason": "",
            "next_action": "apply",
        }
    )
    res = parse_structured_result(raw)
    assert res.kind is LocalResultKind.CHANGES_PROPOSED
    assert res.summary == "Fix test fixture"
    assert res.files_changed == ["tests/test_foo.py"]
    assert res.patch is not None
    assert "--- a/tests/test_foo.py" in res.patch
    assert res.confidence == 0.95


def test_parse_valid_no_change_justified():
    """Requirement 4: Valid NO_CHANGE_JUSTIFIED parses correctly."""
    raw = json.dumps(
        {
            "kind": "NO_CHANGE_JUSTIFIED",
            "summary": "Code is already correct",
            "files_changed": [],
            "patch": None,
            "confidence": 1.0,
            "escalation_required": False,
            "escalation_reason": "",
            "next_action": "none",
        }
    )
    res = parse_structured_result(raw)
    assert res.kind is LocalResultKind.NO_CHANGE_JUSTIFIED
    assert res.patch is None


def test_unified_diff_with_newlines_survives_json():
    """Requirement 6: Unified diff with newline characters survives JSON structured output correctly."""
    diff_text = (
        "--- a/foo.py\n+++ b/foo.py\n@@ -1,3 +1,3 @@\n def foo():\n-    return 1\n+    return 2\n"
    )
    raw = json.dumps(
        {
            "kind": "CHANGES_PROPOSED",
            "summary": "Update foo return value",
            "files_changed": ["foo.py"],
            "patch": diff_text,
            "confidence": 0.9,
            "escalation_required": False,
            "escalation_reason": "",
            "next_action": "apply",
        }
    )
    parsed = parse_structured_result(raw)
    assert parsed.patch == diff_text


# R2 Strict Parsing Rejection Tests
def test_strict_parser_missing_required_field():
    raw = json.dumps(
        {
            "kind": "CHANGES_PROPOSED",
            "summary": "Missing confidence",
            "files_changed": [],
            "patch": None,
            "escalation_required": False,
            "escalation_reason": "",
            "next_action": "none",
        }
    )
    with pytest.raises(ValueError, match="missing required fields"):
        parse_structured_result(raw)


def test_strict_parser_rejects_uncertain_and_unknown_kind():
    raw_uncertain = json.dumps(
        {
            "kind": "UNCERTAIN",
            "summary": "s",
            "files_changed": [],
            "patch": None,
            "confidence": 0.5,
            "escalation_required": False,
            "escalation_reason": "",
            "next_action": "a",
        }
    )
    with pytest.raises(ValueError, match="kind 'UNCERTAIN' is invalid"):
        parse_structured_result(raw_uncertain)


def test_strict_parser_rejects_extra_properties():
    raw = json.dumps(
        {
            "kind": "CHANGES_PROPOSED",
            "summary": "Extra prop",
            "files_changed": [],
            "patch": None,
            "confidence": 0.5,
            "escalation_required": False,
            "escalation_reason": "",
            "next_action": "a",
            "unexpected_field": True,
        }
    )
    with pytest.raises(ValueError, match="unexpected additional properties"):
        parse_structured_result(raw)


def test_strict_parser_rejects_invalid_field_types():
    # files_changed not list
    raw1 = json.dumps(
        {
            "kind": "CHANGES_PROPOSED",
            "summary": "s",
            "files_changed": "foo.py",
            "patch": None,
            "confidence": 0.5,
            "escalation_required": False,
            "escalation_reason": "",
            "next_action": "a",
        }
    )
    with pytest.raises(ValueError, match="files_changed"):
        parse_structured_result(raw1)

    # confidence is boolean
    raw2 = json.dumps(
        {
            "kind": "CHANGES_PROPOSED",
            "summary": "s",
            "files_changed": [],
            "patch": None,
            "confidence": True,
            "escalation_required": False,
            "escalation_reason": "",
            "next_action": "a",
        }
    )
    with pytest.raises(ValueError, match="confidence"):
        parse_structured_result(raw2)

    # confidence out of bounds
    raw3 = json.dumps(
        {
            "kind": "CHANGES_PROPOSED",
            "summary": "s",
            "files_changed": [],
            "patch": None,
            "confidence": 1.5,
            "escalation_required": False,
            "escalation_reason": "",
            "next_action": "a",
        }
    )
    with pytest.raises(ValueError, match="confidence"):
        parse_structured_result(raw3)


# Strict Envelope Rejection Tests (Cases A-D)
def test_strict_envelope_rejects_markdown_fences():
    """Case A: Markdown fenced JSON response fails parsing."""
    valid_obj = {
        "kind": "NO_CHANGE_JUSTIFIED",
        "summary": "s",
        "files_changed": [],
        "patch": None,
        "confidence": 1.0,
        "escalation_required": False,
        "escalation_reason": "",
        "next_action": "none",
    }
    raw = f"```json\n{json.dumps(valid_obj)}\n```"
    with pytest.raises(ValueError, match="Model output is not valid JSON"):
        parse_structured_result(raw)


def test_strict_envelope_rejects_prose_prefix():
    """Case B: Prose prefix followed by valid JSON fails parsing."""
    valid_obj = {
        "kind": "NO_CHANGE_JUSTIFIED",
        "summary": "s",
        "files_changed": [],
        "patch": None,
        "confidence": 1.0,
        "escalation_required": False,
        "escalation_reason": "",
        "next_action": "none",
    }
    raw = f"Here is the response:\n{json.dumps(valid_obj)}"
    with pytest.raises(ValueError, match="Model output is not valid JSON"):
        parse_structured_result(raw)


def test_strict_envelope_rejects_prose_suffix():
    """Case C: Valid JSON followed by prose suffix fails parsing."""
    valid_obj = {
        "kind": "NO_CHANGE_JUSTIFIED",
        "summary": "s",
        "files_changed": [],
        "patch": None,
        "confidence": 1.0,
        "escalation_required": False,
        "escalation_reason": "",
        "next_action": "none",
    }
    raw = f"{json.dumps(valid_obj)}\nHope this helps!"
    with pytest.raises(ValueError, match="Model output is not valid JSON"):
        parse_structured_result(raw)


def test_strict_envelope_rejects_extra_wrapper_text_or_braces():
    """Case D: Extra wrapper text or braces around otherwise valid JSON fails parsing."""
    valid_obj = {
        "kind": "NO_CHANGE_JUSTIFIED",
        "summary": "s",
        "files_changed": [],
        "patch": None,
        "confidence": 1.0,
        "escalation_required": False,
        "escalation_reason": "",
        "next_action": "none",
    }
    raw = f"{{ wrapper: {json.dumps(valid_obj)} }}"
    with pytest.raises(ValueError, match="Model output is not valid JSON"):
        parse_structured_result(raw)


# R3 Redaction Tests
def test_diagnostic_excerpt_secret_redaction():
    secret_text = '{"kind": "MALFORMED", "secret": "api_key=sk-1234567890abcdef"}'
    redacted = redact_secrets(secret_text)
    assert "sk-1234567890abcdef" not in redacted
    assert "api_key=[REDACTED]" in redacted


@pytest.mark.asyncio
async def test_boundary_spanning_secret_redacted_before_truncation():
    """ISSUE A: Secret spanning across the 300-char truncation boundary must be redacted, not leaked by premature slicing."""
    from minime.local_worker.harness import LocalWorkerHarness

    padding = " " * 270 + '{"k": "'
    raw_with_spanning_secret = f"{padding}sk-1234567890abcdef_extra_secret_data"

    async def mock_dispatch(task, attempt, corrective_reason=None):
        return raw_with_spanning_secret

    harness = LocalWorkerHarness(dispatch=mock_dispatch, max_corrective_attempts=0)
    task = LocalTaskEnvelope(
        role="LOCAL_WORKER",
        task_class=LocalTaskClass.TEST_AUTHORING,
        allowed_files=["foo.py"],
        instruction="Fix foo",
    )
    validator = AsyncMock(return_value=ValidationResult(verdict=LocalValidationVerdict.PASS))

    evidence = await harness.run(task, validator=validator)

    assert evidence.raw_output_excerpt is not None
    assert "sk-1234567890abcdef" not in evidence.raw_output_excerpt
    assert "[REDACTED_KEY]" in evidence.raw_output_excerpt


@pytest.mark.asyncio
async def test_model_controlled_failure_reason_redacted():
    """ISSUE B: Secret-like values placed in model-controlled fields (e.g. kind) are redacted in failure reason and logs."""
    from minime.local_worker.harness import LocalWorkerHarness

    raw_with_secret_kind = json.dumps(
        {
            "kind": "sk-1234567890abcdef_invalid_kind",
            "summary": "s",
            "files_changed": [],
            "patch": None,
            "confidence": 1.0,
            "escalation_required": False,
            "escalation_reason": "",
            "next_action": "none",
        }
    )

    async def mock_dispatch(task, attempt, corrective_reason=None):
        return raw_with_secret_kind

    harness = LocalWorkerHarness(dispatch=mock_dispatch, max_corrective_attempts=0)
    task = LocalTaskEnvelope(
        role="LOCAL_WORKER",
        task_class=LocalTaskClass.TEST_AUTHORING,
        allowed_files=["foo.py"],
        instruction="Fix foo",
    )
    validator = AsyncMock(return_value=ValidationResult(verdict=LocalValidationVerdict.PASS))

    evidence = await harness.run(task, validator=validator)

    assert evidence.model_output_failure_reason is not None
    assert "sk-1234567890abcdef" not in evidence.model_output_failure_reason
    assert "[REDACTED_KEY]" in evidence.model_output_failure_reason


@pytest.mark.asyncio
async def test_adapter_sends_format_field():
    """Requirement 2: Adapter sends supported Ollama structured-output field ('format') in /api/chat request."""
    adapter = LocalOllamaAdapter(model="qwen2.5-coder:7b-instruct-q4_K_M")

    captured_body = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_body
        captured_body = json.loads(request.read())
        return httpx.Response(
            200,
            json={
                "model": "qwen2.5-coder:7b-instruct-q4_K_M",
                "message": {
                    "role": "assistant",
                    "content": json.dumps(
                        {
                            "kind": "NO_CHANGE_JUSTIFIED",
                            "summary": "ok",
                            "files_changed": [],
                            "patch": None,
                            "confidence": 1.0,
                            "escalation_required": False,
                            "escalation_reason": "",
                            "next_action": "none",
                        }
                    ),
                },
                "done": True,
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:11434") as client:
        res = await adapter.generate(
            system_prompt="sys",
            prompt="usr",
            client=client,
            response_format=LOCAL_WORKER_RESPONSE_SCHEMA,
        )

    assert res.result_class is ProviderResultClass.SUCCESS
    assert captured_body is not None
    assert "format" in captured_body
    assert captured_body["format"] == LOCAL_WORKER_RESPONSE_SCHEMA


@pytest.mark.asyncio
async def test_service_passes_schema_and_differentiates_attempt_2():
    """Requirements R1 & R4:
    R1: LocalWorkerService passes structured schema mandatory to LocalOllamaAdapter.
    R4: Attempt 2 prompt receives cause-specific corrective instruction.
    """
    adapter = MagicMock(spec=LocalOllamaAdapter)
    adapter.model = "qwen2.5-coder:7b-instruct-q4_K_M"
    adapter.provider = "ollama"

    preflight_mock = AsyncMock()
    from minime.local_worker.models import PreflightResult, PreflightStatus

    preflight_mock.return_value = PreflightResult(
        provider="ollama",
        model="qwen2.5-coder:7b-instruct-q4_K_M",
        status=PreflightStatus.READY,
        reachable=True,
        model_present=True,
    )
    adapter.preflight = preflight_mock

    calls = []

    async def mock_generate(*args, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            from minime.local_worker.ollama_adapter import OllamaGenerateResponse

            return OllamaGenerateResponse(
                result_class=ProviderResultClass.SUCCESS,
                text="Not JSON at all",
            )
        else:
            from minime.local_worker.ollama_adapter import OllamaGenerateResponse

            valid_json = json.dumps(
                {
                    "kind": "NO_CHANGE_JUSTIFIED",
                    "summary": "Corrected",
                    "files_changed": [],
                    "patch": None,
                    "confidence": 1.0,
                    "escalation_required": False,
                    "escalation_reason": "",
                    "next_action": "none",
                }
            )
            return OllamaGenerateResponse(
                result_class=ProviderResultClass.SUCCESS,
                text=valid_json,
            )

    adapter.generate = AsyncMock(side_effect=mock_generate)

    service = LocalWorkerService(adapter=adapter, max_corrective_attempts=1)
    task = LocalTaskEnvelope(
        role="LOCAL_WORKER",
        task_class=LocalTaskClass.TEST_AUTHORING,
        allowed_files=["foo.py"],
        instruction="Fix foo",
    )

    from minime.domain.enums import (
        ClassificationCompleteness,
        ClassificationStage,
        TaskComplexity,
        TaskSurfaceKind,
    )
    from minime.domain.models import TaskClassificationSnapshot, TaskRiskProfile
    from minime.local_worker.models import (
        LocalMechanicalOperation,
        LocalMutationMode,
        OperatorMechanicalCommand,
    )

    cmd = OperatorMechanicalCommand(
        operation_type=LocalMechanicalOperation.TEXT_REPLACEMENT,
        mutation_mode=LocalMutationMode.MUTATING,
        target_file="foo.py",
        authoritative_change={"replacement": "..."},
        deterministic_acceptance={"test_target": "tests/test_foo.py"},
    )
    snapshot = TaskClassificationSnapshot(
        id="snap-test-struct-1",
        stage=ClassificationStage.PRE_EXECUTION,
        classifier_version="1.0.0",
        evidence_source="test_fixture",
        classification_completeness=ClassificationCompleteness.PARTIAL,
        missing_signals=[],
        complexity=TaskComplexity.LOW,
        surface_kind=TaskSurfaceKind.BACKEND_SERVICE,
        risk_profile=TaskRiskProfile(
            architectural_impact="NONE",
            persistence_impact="NONE",
            security_auth_impact="NONE",
            production_runtime="NONE",
            provider_orchestration="NONE",
            destructive_operations="NONE",
        ),
    )
    validator = AsyncMock(return_value=ValidationResult(verdict=LocalValidationVerdict.PASS))

    outcome = await service.run(
        task,
        validator=validator,
        routing_source=cmd,
        classification_snapshot=snapshot,
    )

    assert len(calls) == 2
    assert calls[0]["response_format"] == LOCAL_WORKER_RESPONSE_SCHEMA
    assert "IMPORTANT CORRECTIVE INSTRUCTION" not in calls[0]["prompt"]

    assert calls[1]["response_format"] == LOCAL_WORKER_RESPONSE_SCHEMA
    assert (
        "Previous response did not satisfy the required structured response contract"
        in calls[1]["prompt"]
    )
    assert outcome.evidence.result_class == "SUCCESS"
    assert outcome.evidence.attempt == 2


@pytest.mark.asyncio
async def test_cause_specific_corrective_reasons_patch_policy():
    """R4: Attempt 2 receives patch policy corrective instruction when policy fails."""
    from minime.local_worker.harness import LocalWorkerHarness

    harness = LocalWorkerHarness(max_corrective_attempts=1)
    dispatches = []

    async def mock_dispatch(envelope, attempt, corrective_reason=None):
        dispatches.append((attempt, corrective_reason))
        if attempt == 1:
            return json.dumps(
                {
                    "kind": "CHANGES_PROPOSED",
                    "summary": "Unauthorized file patch",
                    "files_changed": ["forbidden.py"],
                    "patch": "--- a/forbidden.py\n+++ b/forbidden.py\n@@ -1 +1 @@\n-old\n+new\n",
                    "confidence": 0.8,
                    "escalation_required": False,
                    "escalation_reason": "",
                    "next_action": "apply",
                }
            )
        else:
            return json.dumps(
                {
                    "kind": "NO_CHANGE_JUSTIFIED",
                    "summary": "Fixed after policy warning",
                    "files_changed": [],
                    "patch": None,
                    "confidence": 1.0,
                    "escalation_required": False,
                    "escalation_reason": "",
                    "next_action": "none",
                }
            )

    harness._dispatch = mock_dispatch

    task = LocalTaskEnvelope(
        role="LOCAL_WORKER",
        task_class=LocalTaskClass.TEST_AUTHORING,
        allowed_files=["allowed.py"],
        instruction="Fix allowed",
    )

    validator = AsyncMock(return_value=ValidationResult(verdict=LocalValidationVerdict.PASS))

    evidence = await harness.run(task, validator=validator)

    assert "Previous patch targeted an unauthorized file" in dispatches[1][1]
    assert "forbidden.py" in dispatches[1][1]
    assert "allowed.py" in dispatches[1][1]
    assert evidence.result_class == "SUCCESS"


@pytest.mark.asyncio
async def test_incompatible_adapter_fails_closed():
    """R1: Incompatible adapter that fails response_format causes LocalWorkerService.run to fail/escalate fail-closed."""

    class IncompatibleAdapter:
        model = "qwen2.5-coder:7b-instruct-q4_K_M"
        provider = "ollama"

        async def preflight(self, client=None):
            from minime.local_worker.models import PreflightResult, PreflightStatus

            return PreflightResult(
                provider="ollama",
                model=self.model,
                status=PreflightStatus.READY,
                reachable=True,
                model_present=True,
            )

        async def generate(self, system_prompt, prompt, client=None):
            # Does not accept response_format parameter!
            raise TypeError("generate() got an unexpected keyword argument 'response_format'")

    service = LocalWorkerService(adapter=IncompatibleAdapter(), max_corrective_attempts=1)
    task = LocalTaskEnvelope(
        role="LOCAL_WORKER",
        task_class=LocalTaskClass.TEST_AUTHORING,
        allowed_files=["foo.py"],
        instruction="Fix foo",
    )

    from minime.domain.enums import (
        ClassificationCompleteness,
        ClassificationStage,
        TaskComplexity,
        TaskSurfaceKind,
    )
    from minime.domain.models import TaskClassificationSnapshot, TaskRiskProfile
    from minime.local_worker.models import (
        LocalMechanicalOperation,
        LocalMutationMode,
        OperatorMechanicalCommand,
    )

    cmd = OperatorMechanicalCommand(
        operation_type=LocalMechanicalOperation.TEXT_REPLACEMENT,
        mutation_mode=LocalMutationMode.MUTATING,
        target_file="foo.py",
        authoritative_change={"replacement": "..."},
        deterministic_acceptance={"test_target": "tests/test_foo.py"},
    )
    snapshot = TaskClassificationSnapshot(
        id="snap-test-struct-2",
        stage=ClassificationStage.PRE_EXECUTION,
        classifier_version="1.0.0",
        evidence_source="test_fixture",
        classification_completeness=ClassificationCompleteness.PARTIAL,
        missing_signals=[],
        complexity=TaskComplexity.LOW,
        surface_kind=TaskSurfaceKind.BACKEND_SERVICE,
        risk_profile=TaskRiskProfile(
            architectural_impact="NONE",
            persistence_impact="NONE",
            security_auth_impact="NONE",
            production_runtime="NONE",
            provider_orchestration="NONE",
            destructive_operations="NONE",
            deployment_config="NONE",
            code_change_breadth="LOW",
        ),
    )

    validator = AsyncMock(return_value=ValidationResult(verdict=LocalValidationVerdict.PASS))

    outcome = await service.run(
        task,
        validator=validator,
        routing_source=cmd,
        classification_snapshot=snapshot,
    )

    assert outcome.evidence.result_class == "UNEXPECTED_FAILURE"
    assert outcome.evidence.escalation.required is True


@pytest.mark.asyncio
async def test_no_retry_after_filesystem_mutation(tmp_path):
    """Requirement 10: No corrective attempt occurs after filesystem mutation."""
    from minime.local_worker.harness import LocalWorkerHarness

    harness = LocalWorkerHarness(max_corrective_attempts=1)

    dispatch_calls = 0

    async def mock_dispatch(envelope, attempt, corrective_reason=None):
        nonlocal dispatch_calls
        dispatch_calls += 1
        return json.dumps(
            {
                "kind": "CHANGES_PROPOSED",
                "summary": "Bad patch",
                "files_changed": ["foo.py"],
                "patch": "--- a/foo.py\n+++ b/foo.py\n@@ -1 +1 @@\n-old\n+new\n",
                "confidence": 0.8,
                "escalation_required": False,
                "escalation_reason": "",
                "next_action": "apply",
            }
        )

    harness._dispatch = mock_dispatch

    task = LocalTaskEnvelope(
        role="LOCAL_WORKER",
        task_class=LocalTaskClass.TEST_AUTHORING,
        allowed_files=["foo.py"],
        instruction="Fix foo",
    )

    validator = AsyncMock(
        return_value=ValidationResult(
            verdict=LocalValidationVerdict.FAIL, reason="Post-apply test failure"
        )
    )

    patch_applier = MagicMock()
    from minime.local_worker.patch_applier import PatchApplicationResult

    patch_applier.apply_patch.return_value = PatchApplicationResult(
        applied=True,
        success=False,
        error="Post-apply syntax error in python file",
        authoritative_changed_files=("foo.py",),
    )
    harness.patch_applier = patch_applier

    evidence = await harness.run(
        task,
        validator=validator,
        worktree_path=str(tmp_path),
        uow=MagicMock(),
        project_id="mini-me",
        job_id="job-123",
    )

    assert dispatch_calls == 1
    assert evidence.patch_applied is True
    assert evidence.result_class == "PATCH_APPLY_FAILED"
    assert evidence.escalation.required is True
