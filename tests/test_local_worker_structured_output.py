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


def test_schema_cannot_select_uncertain():
    """Requirement 5: Model cannot select UNCERTAIN via the provider schema."""
    enum_values = LOCAL_WORKER_RESPONSE_SCHEMA["properties"]["kind"]["enum"]
    assert "CHANGES_PROPOSED" in enum_values
    assert "NO_CHANGE_JUSTIFIED" in enum_values
    assert "UNCERTAIN" not in enum_values


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
    """Requirements 1, 7, 8, 9:
    1. LocalWorkerService passes the structured schema to LocalOllamaAdapter.
    7. Initial pre-mutation protocol failure receives one corrective attempt.
    8. Attempt 2 prompt is actually different and explicitly corrective.
    9. Maximum generation attempts remains 2 total.
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
            # Attempt 1 returns malformed output
            from minime.local_worker.ollama_adapter import OllamaGenerateResponse

            return OllamaGenerateResponse(
                result_class=ProviderResultClass.SUCCESS,
                text="Not JSON at all",
            )
        else:
            # Attempt 2 returns valid NO_CHANGE_JUSTIFIED
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

    validator = AsyncMock(return_value=ValidationResult(verdict=LocalValidationVerdict.PASS))

    outcome = await service.run(task, validator=validator)

    assert len(calls) == 2  # Max 2 attempts total
    # Check attempt 1
    assert calls[0]["response_format"] == LOCAL_WORKER_RESPONSE_SCHEMA
    assert "IMPORTANT CORRECTIVE INSTRUCTION" not in calls[0]["prompt"]

    # Check attempt 2
    assert calls[1]["response_format"] == LOCAL_WORKER_RESPONSE_SCHEMA
    assert "IMPORTANT CORRECTIVE INSTRUCTION" in calls[1]["prompt"]
    assert calls[1]["prompt"] != calls[0]["prompt"]
    assert outcome.evidence.result_class == "SUCCESS"
    assert outcome.evidence.attempt == 2


@pytest.mark.asyncio
async def test_no_retry_after_filesystem_mutation(tmp_path):
    """Requirement 10: No corrective attempt occurs after filesystem mutation."""
    from minime.local_worker.harness import LocalWorkerHarness

    harness = LocalWorkerHarness(max_corrective_attempts=1)

    dispatch_calls = 0

    async def mock_dispatch(envelope, attempt):
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

    # Patch was applied to disk (mutated), but application/post-check failed
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

    # Exactly 1 dispatch call because filesystem mutated: retry MUST BE NO!
    assert dispatch_calls == 1
    assert evidence.patch_applied is True
    assert evidence.result_class == "PATCH_APPLY_FAILED"
    assert evidence.escalation.required is True
