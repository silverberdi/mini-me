"""Offline tests for the minimal local worker bootstrap change.

These tests require NO live Ollama daemon and NO model download: every network interaction
runs through an injected ``httpx.MockTransport``, and eligibility/harness scenarios are fully
deterministic. Mirrors the behavioral authority in
``openspec/changes/minimal-local-worker-bootstrap/specs/.../spec.md``.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from minime.local_worker.harness import LocalWorkerHarness, parse_structured_result
from minime.local_worker.model_identity import (
    QWEN2_5_CODER_7B_INSTRUCT_Q4_K_M,
    assert_local_qwen_model,
    is_canonical_local_qwen_model,
    local_qwen_model_identity,
)
from minime.local_worker.models import (
    EscalationTarget,
    LocalExecutionEvidence,
    LocalResultKind,
    LocalTaskClass,
    LocalTaskEnvelope,
    LocalValidationVerdict,
    ValidationResult,
)
from minime.local_worker.ollama_adapter import LocalOllamaAdapter, OllamaGenerateResponse
from minime.local_worker.policy import (
    evaluate_eligibility,
    local_worker_authorities,
)

COPY_PREFIX = "src/minime/local_worker/"

# --- canonical model identity + no-authority (spec: exact identity, no merge/review/audit) ---


def test_exact_canonical_model_identity():
    assert QWEN2_5_CODER_7B_INSTRUCT_Q4_K_M == "qwen2.5-coder:7b-instruct-q4_K_M"
    assert local_qwen_model_identity() == "qwen2.5-coder:7b-instruct-q4_K_M"
    assert is_canonical_local_qwen_model("qwen2.5-coder:7b-instruct-q4_K_M")
    assert not is_canonical_local_qwen_model("qwen2.5-coder:7b")  # not exact
    assert_local_qwen_model("qwen2.5-coder:7b-instruct-q4_K_M")


def test_local_worker_has_no_review_audit_merge_approve_authority():
    authorities = local_worker_authorities()
    assert "implement" in authorities
    for forbidden in ("review", "audit", "merge", "approve", "validate_self_success"):
        assert forbidden not in authorities


# --- eligibility admission / refusal (spec) ---


def _envelope(task_class: LocalTaskClass, instruction: str) -> LocalTaskEnvelope:
    return LocalTaskEnvelope(
        role="local_worker",
        task_class=task_class,
        allowed_files=["src/minime/local_worker/*.py"],
        forbidden_files=[],
        instruction=instruction,
        context="bounded test context",
    )


def test_allowed_low_risk_class_is_admitted():
    decision = evaluate_eligibility(
        task_class=LocalTaskClass.SMALL_CODE_FIX.value,
        instruction="fix an off-by-one in the counting helper",
        allowed_files=["src/**"],
    )
    assert decision.admitted


@pytest.mark.parametrize(
    "bad_class,instruction",
    [
        ("DB_SCHEMA_MIGRATION", "add an alembic revision"),
        ("PROVIDER_POLICY_CHANGE", "change the retry budget"),
        ("UNCERTAIN_CLASSIFICATION", "apply an ambiguous broad refactor"),
        ("DESTRUCTIVE_OPERATION", "delete old data"),
    ],
)
def test_forbidden_class_is_refused_with_escalation(bad_class, instruction):
    decision = evaluate_eligibility(
        task_class=bad_class,
        instruction=instruction,
        allowed_files=["src/**"],
    )
    assert not decision.admitted
    assert decision.escalation_target is EscalationTarget.EXISTING_PROVIDER_POLICY


def test_forbidden_surface_in_instruction_is_refused():
    decision = evaluate_eligibility(
        task_class=LocalTaskClass.SMALL_CODE_FIX.value,
        instruction="tune the TLS credential handling",
        allowed_files=["src/**"],
    )
    assert not decision.admitted


# --- adapter offline (MockTransport), preflight reachability + model presence ---


def _tags_response(names):
    return httpx.Response(200, json={"models": [{"name": n} for n in names]})


async def test_preflight_success_when_reachable_and_model_present():
    transport = httpx.MockTransport(
        lambda request: _tags_response([QWEN2_5_CODER_7B_INSTRUCT_Q4_K_M])
    )
    client = httpx.AsyncClient(transport=transport, base_url="http://ollama.test")
    adapter = LocalOllamaAdapter(model=QWEN2_5_CODER_7B_INSTRUCT_Q4_K_M)
    result = await adapter.preflight(client=client)
    assert result.reachable is True
    assert result.model_present is True


async def test_preflight_fails_when_canonical_model_missing():
    transport = httpx.MockTransport(lambda request: _tags_response(["llama3.1"]))
    client = httpx.AsyncClient(transport=transport, base_url="http://ollama.test")
    adapter = LocalOllamaAdapter(model=QWEN2_5_CODER_7B_INSTRUCT_Q4_K_M)
    result = await adapter.preflight(client=client)
    assert result.model_present is False
    assert QWEN2_5_CODER_7B_INSTRUCT_Q4_K_M in result.reason


async def test_preflight_fails_when_ollama_unreachable():
    def handler(request):
        raise httpx.ConnectError("connection refused", request=request)

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://ollama.test"
    )
    adapter = LocalOllamaAdapter(model=QWEN2_5_CODER_7B_INSTRUCT_Q4_K_M)
    result = await adapter.preflight(client=client)
    assert result.reachable is False


async def test_generate_success_returns_bounded_text():
    def handler(request):
        return httpx.Response(
            200,
            json={
                "message": {"role": "assistant", "content": '{"kind":"CHANGES_PROPOSED"}'}
            },
        )

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://ollama.test"
    )
    adapter = LocalOllamaAdapter(model=QWEN2_5_CODER_7B_INSTRUCT_Q4_K_M)
    response = await adapter.generate(
        system_prompt="s", prompt="p", client=client
    )
    assert isinstance(response, OllamaGenerateResponse)
    assert response.text.startswith('{"kind"')


async def test_generate_non_success_class_maps_onto_provider_class():
    def handler(request):
        return httpx.Response(500, text="boom")

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://ollama.test"
    )
    adapter = LocalOllamaAdapter(model=QWEN2_5_CODER_7B_INSTRUCT_Q4_K_M)
    response = await adapter.generate(system_prompt="s", prompt="p", client=client)
    assert response.text == ""
    assert response.error != ""


# --- harness: structured parse, NO_CHANGE_JUSTIFIED acceptance, timeout, one-corrective cap ---


async def _always_pass(_task, _result, _attempt) -> ValidationResult:
    return ValidationResult(verdict=LocalValidationVerdict.PASS, reason="deterministic")


async def _always_fail(_task, _result, _attempt) -> ValidationResult:
    return ValidationResult(verdict=LocalValidationVerdict.FAIL, reason="not validated")


async def test_parse_accepts_no_change_justified_as_valid():
    result = parse_structured_result(
        '{```json\n{"kind":"NO_CHANGE_JUSTIFIED","summary":"no change needed",'
        '"files_changed":[],"confidence":0.9}\n```}'
    )
    assert result.kind is LocalResultKind.NO_CHANGE_JUSTIFIED
    assert result.is_no_change_justified


async def test_harness_accepts_no_change_justified_outcome_when_validated():
    async def dispatch(_t, _n):
        return '{"kind":"NO_CHANGE_JUSTIFIED","summary":"ok"}'

    harness = LocalWorkerHarness(dispatch=dispatch)
    envelope = _envelope(LocalTaskClass.SMALL_CODE_FIX, "look and decide no change needed")
    envelope.timeout_seconds = 5.0
    evidence = await harness.run(envelope, validator=lambda *a: _always_pass(*a))
    assert evidence.result is LocalResultKind.NO_CHANGE_JUSTIFIED
    assert evidence.validation_result is LocalValidationVerdict.PASS
    assert evidence.escalation.required is False


async def test_harness_timeout_cancels_in_flight_and_cleanup_called():
    cleanup_calls = []

    async def cleanup(attempt: int):
        cleanup_calls.append(attempt)

    async def slow_dispatch(_t, _n):
        await asyncio.sleep(30)  # far beyond the envelope deadline

    harness = LocalWorkerHarness(
        dispatch=slow_dispatch, cleanup=cleanup, max_corrective_attempts=0
    )
    envelope = _envelope(LocalTaskClass.SMALL_CODE_FIX, "touch file x")
    envelope.timeout_seconds = 0.05
    envelope.forbidden_files = []
    evidence = await harness.run(envelope, validator=lambda *a: _always_pass(*a))
    assert evidence.result_class == "TIMEOUT"
    assert harness.timeout_cleanup_calls == 1
    assert cleanup_calls == [1]  # in-flight work was cleaned up exactly once
    assert evidence.escalation.required is True



async def test_harness_allows_exactly_one_corrective_then_escalates():
    dispatch_calls = []
    fail_then_pass = {"already_used": False}

    async def dispatch(_t, _n):
        dispatch_calls.append(_n)
        return '{"kind":"CHANGES_PROPOSED","summary":"fix"}'

    async def validator(_t, _result, _attempt):
        if not fail_then_pass["already_used"]:
            fail_then_pass["already_used"] = True
            return ValidationResult(
                verdict=LocalValidationVerdict.FAIL, reason="first candidate invalid"
            )
        return ValidationResult(verdict=LocalValidationVerdict.PASS, reason="corrected ok")

    harness = LocalWorkerHarness(dispatch=dispatch, max_corrective_attempts=1)
    envelope = _envelope(LocalTaskClass.SMALL_CODE_FIX, "fix bounds helper")
    envelope.timeout_seconds = 5.0
    evidence = await harness.run(envelope, validator=validator)
    # initial attempt 1 + exactly one corrective attempt 2, never > 2 total dispatches.
    assert dispatch_calls == [1, 2]
    assert evidence.corrections_used == 1
    assert evidence.validation_result is LocalValidationVerdict.PASS


async def test_harness_stops_with_escalation_when_corrective_still_fails():
    dispatch_calls = []

    async def dispatch(_t, _n):
        dispatch_calls.append(_n)
        return '{"kind":"CHANGES_PROPOSED","summary":"still bad"}'

    harness = LocalWorkerHarness(dispatch=dispatch, max_corrective_attempts=1)
    envelope = _envelope(LocalTaskClass.SMALL_REFACTOR, "rename a local var")
    envelope.timeout_seconds = 5.0
    evidence = await harness.run(envelope, validator=lambda *a: _always_fail(*a))
    # exactly 2 total attempts (1 initial + 1 corrective), then stop/escalate, no unbounded retry.
    assert dispatch_calls == [1, 2]
    assert evidence.result_class == "VALIDATION_FAILED"
    assert evidence.escalation.required is True
    assert evidence.escalation.target is EscalationTarget.EXISTING_PROVIDER_POLICY


# --- service orchestration: forbidden refused pre-dispatch, success run yields evidence ---


async def test_service_refuses_forbidden_class_never_dispatches():
    from minime.local_worker.service import LocalWorkerService

    calls = {"net": 0}

    async def no_dispatch_generate(**kwargs):
        calls["net"] += 1
        raise AssertionError("must never reach the adapter on a refused task")

    service = LocalWorkerService()
    service.adapter.generate = no_dispatch_generate  # type: ignore[method-assign]
    envelope = _envelope(
        LocalTaskClass.SMALL_CODE_FIX, "rotate the API token stored by the credentials helper"
    )
    outcome = await service.run(envelope, validator=_always_pass)
    assert outcome.evidence.result_class == "REFUSED"
    assert outcome.evidence.task_class == envelope.task_class.value
    assert outcome.evidence.escalation.required is True
    assert calls["net"] == 0  # forbidden work was never executed


async def test_service_success_run_yields_minimal_structured_evidence():
    from minime.domain.enums import ProviderResultClass
    from minime.local_worker.model_identity import OLLAMA_PROVIDER
    from minime.local_worker.models import PreflightResult, PreflightStatus
    from minime.local_worker.service import LocalWorkerService

    ready = PreflightResult(
        provider=OLLAMA_PROVIDER,
        model=local_qwen_model_identity(),
        status=PreflightStatus.READY,
        reachable=True,
        model_present=True,
    )

    async def fake_generate(*, system_prompt=None, prompt=None, client=None):
        return OllamaGenerateResponse(
            result_class=ProviderResultClass.SUCCESS,
            text='{"kind":"CHANGES_PROPOSED","summary":"bumped the index check"}',
        )

    service = LocalWorkerService()
    service.adapter.generate = fake_generate  # type: ignore[method-assign]
    envelope = _envelope(LocalTaskClass.SMALL_CODE_FIX, "fix off-by-one in helper")
    envelope.timeout_seconds = 10.0
    outcome = await service.run(envelope, validator=lambda *a: _always_pass(*a), preflight=ready)
    assert isinstance(outcome.evidence, LocalExecutionEvidence)
    evidence = outcome.evidence
    assert evidence.provider == "ollama"
    assert evidence.model == "qwen2.5-coder:7b-instruct-q4_K_M"
    assert evidence.task_class == envelope.task_class.value
    assert evidence.attempt == 1
    assert evidence.result_class == "SUCCESS"
    assert evidence.validation_result is LocalValidationVerdict.PASS
    assert evidence.escalation.required is False
    assert evidence.result is LocalResultKind.CHANGES_PROPOSED





