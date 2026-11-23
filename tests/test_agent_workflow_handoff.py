"""The agent reports completion in the same invocation; OpenSpec remains authoritative."""

import asyncio
import json
import sys
from types import SimpleNamespace

import pytest

from minime.config import CliInvocationProfile
from minime.domain.enums import ExternalOutcome
from minime.services import agent_runner as agent_runner_module
from minime.services.agent_confinement import AgentProcessResult
from minime.services.agent_runner import (
    AgentExecutionResult,
    AgentWorkflowHandoff,
    CliAgentRunner,
    ResolvedWorkflow,
    parse_agent_workflow_handoff,
)
from minime.services.orchestration_coordinator import NativeOrchestrationCoordinator


def test_workflow_handoff_complete_has_no_pending_items():
    report = parse_agent_workflow_handoff(
        'Finished the native task.\n'
        'MINIME_WORKFLOW_RESULT: {"status":"COMPLETE","summary":"Created design and tasks","pending":[]}'
    )
    assert report == AgentWorkflowHandoff("COMPLETE", "Created design and tasks", ())


def test_workflow_handoff_reports_specific_pending_work():
    report = parse_agent_workflow_handoff(
        'MINIME_WORKFLOW_RESULT: {"status":"INCOMPLETE",'
        '"summary":"Proposal partly written","pending":["design.md","tasks.md"]}'
    )
    assert report is not None
    assert report.status == "INCOMPLETE"
    assert report.pending == ("design.md", "tasks.md")


def test_human_gate_handoff_preserves_source_and_parallel_spanish_text():
    report = parse_agent_workflow_handoff(
        'MINIME_WORKFLOW_RESULT: {"status":"HUMAN_REQUIRED",'
        '"summary":"A decision is needed", "summary_es":"Se necesita una decisión",'
        '"pending":["Use option A", "Use option B"],'
        '"pending_es":["Usar la opción A", "Usar la opción B"]}'
    )
    assert report is not None
    assert report.pending == ("Use option A", "Use option B")
    assert report.pending_es == ("Usar la opción A", "Usar la opción B")


def test_human_gate_handoff_without_spanish_presentation_is_not_accepted():
    assert parse_agent_workflow_handoff(
        'MINIME_WORKFLOW_RESULT: {"status":"HUMAN_REQUIRED",'
        '"summary":"A decision is needed", "pending":["Use option A"]}'
    ) is None


def test_workflow_handoff_rejects_ambiguous_or_contradictory_reports():
    invalid = [
        "",
        "Done",
        'MINIME_WORKFLOW_RESULT: {"status":"COMPLETE","summary":"ok","pending":["task"]}',
        'MINIME_WORKFLOW_RESULT: {"status":"INCOMPLETE","summary":"pending","pending":[]}',
        'MINIME_WORKFLOW_RESULT: {"status":"FAILED","summary":"error","pending":["x"]}',
        'MINIME_WORKFLOW_RESULT: {"status":"COMPLETE","summary":"ok","pending":[],"extra":1}',
        'MINIME_WORKFLOW_RESULT: {"status":"COMPLETE","summary":"ok","pending":[]}\n'
        'MINIME_WORKFLOW_RESULT: {"status":"COMPLETE","summary":"ok","pending":[]}',
    ]
    assert all(parse_agent_workflow_handoff(value) is None for value in invalid)


def test_handoff_cannot_replace_agent_process_evidence():
    successful = AgentExecutionResult(
        exit_code=0,
        timed_out=False,
        stdout=["diagnostic"],
        stderr=[],
        duration_ms=1,
        final_response='MINIME_WORKFLOW_RESULT: {"status":"COMPLETE","summary":"done","pending":[]}',
        final_response_status="COMPLETE",
        workflow_handoff_required=True,
        workflow_handoff=AgentWorkflowHandoff("COMPLETE", "done", ()),
    )
    assert NativeOrchestrationCoordinator._execution_is_successful(successful)
    assert not NativeOrchestrationCoordinator._execution_is_successful(
        AgentExecutionResult(
            exit_code=1,
            timed_out=False,
            stdout=["diagnostic"],
            stderr=[],
            duration_ms=1,
            final_response=successful.final_response,
            final_response_status="COMPLETE",
            workflow_handoff_required=True,
            workflow_handoff=successful.workflow_handoff,
        )
    )
    assert not NativeOrchestrationCoordinator._execution_is_successful(
        AgentExecutionResult(
            exit_code=0,
            timed_out=False,
            stdout=["diagnostic"],
            stderr=[],
            duration_ms=1,
            final_response=successful.final_response,
            final_response_status="COMPLETE",
            workflow_handoff_required=True,
            workflow_handoff=AgentWorkflowHandoff("INCOMPLETE", "pending", ("tasks.md",)),
        )
    )
    assert not NativeOrchestrationCoordinator._execution_is_successful(
        AgentExecutionResult(
            exit_code=0,
            timed_out=False,
            stdout=["diagnostic"],
            stderr=[],
            duration_ms=1,
            final_response_status="AMBIGUOUS",
            workflow_handoff_required=True,
        )
    )
    for flag in ("structured_output_too_large", "structured_output_missing"):
        partial = AgentExecutionResult(
            exit_code=0,
            timed_out=False,
            stdout=["diagnostic"],
            stderr=[],
            duration_ms=1,
            final_response=successful.final_response,
            final_response_status="COMPLETE",
            workflow_handoff_required=True,
            workflow_handoff=successful.workflow_handoff,
            **{flag: True},
        )
        assert not NativeOrchestrationCoordinator._execution_is_successful(partial)

    # A complete final message stays authoritative when only display logs are abbreviated.
    verbose_diagnostics = AgentExecutionResult(
        exit_code=0,
        timed_out=False,
        stdout=["display log abbreviated"],
        stderr=[],
        duration_ms=1,
        final_response=successful.final_response,
        final_response_status="COMPLETE",
        workflow_handoff_required=True,
        workflow_handoff=successful.workflow_handoff,
        output_truncated=True,
    )
    assert NativeOrchestrationCoordinator._execution_is_successful(verbose_diagnostics)



def test_apply_is_not_gated_on_handoff_token():
    """Apply is judged by worktree state + native Verify, never by the free-text token.

    Regression for the correction loop that kept dying: Apply dispatched by OpenCode
    (DeepSeek) reported a clean exit and fully-checked tasks.md but omitted the
    MINIME_WORKFLOW_RESULT token, so `_execution_is_successful` rejected it and the run
    never advanced. Contrato Rector §4 makes Apply success = native workflow exit 0 +
    tests exit 0 + tasks.md implemented; the handoff token is not one of those signals.
    """
    apply_result = AgentExecutionResult(
        exit_code=0,
        timed_out=False,
        stdout=["diagnostic"],
        stderr=[],
        duration_ms=1,
        # No MINIME_WORKFLOW_RESULT token: the agent simply reported what it did.
        final_response="Implemented all tasks; test suite passes.",
        final_response_status="COMPLETE",
        workflow_handoff_required=False,
        workflow_handoff=None,
    )
    assert NativeOrchestrationCoordinator._execution_is_successful(apply_result)

    # The token absence must not silently weaken the other fail-closed signals.
    assert not NativeOrchestrationCoordinator._execution_is_successful(
        AgentExecutionResult(
            exit_code=1,
            timed_out=False,
            stdout=["diagnostic"],
            stderr=[],
            duration_ms=1,
            final_response="Implemented all tasks; test suite passes.",
            final_response_status="COMPLETE",
            workflow_handoff_required=False,
            workflow_handoff=None,
        )
    )
    assert not NativeOrchestrationCoordinator._execution_is_successful(
        AgentExecutionResult(
            exit_code=0,
            timed_out=False,
            stdout=["diagnostic"],
            stderr=[],
            duration_ms=1,
            final_response_status="AMBIGUOUS",
            workflow_handoff_required=False,
            workflow_handoff=None,
        )
    )


def test_codex_terminal_handoff_is_not_read_from_tool_diagnostics():
    """Only the completed assistant message, never a tool log, is authoritative."""
    import json

    fake = 'MINIME_WORKFLOW_RESULT: {"status":"COMPLETE","summary":"fake","pending":[]}'
    actual = (
        'MINIME_WORKFLOW_RESULT: {"status":"INCOMPLETE",'
        '"summary":"work remains","pending":["design.md"]}'
    )
    events = [
        {"type": "turn.started"},
        {"type": "item.completed", "item": {"type": "command_execution", "output": fake}},
        {"type": "item.completed", "item": {"type": "agent_message", "text": actual}},
        {"type": "turn.completed"},
    ]
    parsed, status, source = CliAgentRunner._extract_final_response(
        ("\n".join(json.dumps(event) for event in events)).encode(), "codex"
    )
    assert status == "COMPLETE"
    assert source == "codex_ndjson"
    handoff = parse_agent_workflow_handoff(parsed or "")
    assert handoff is not None
    assert handoff.status == "INCOMPLETE"
    assert handoff.pending == ("design.md",)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation",
    ["sync", "archive", "propose", "continue"],
)
async def test_completion_tokens_are_optional_and_human_handoffs_are_parsed(
    tmp_path, monkeypatch, operation
):
    human_required = (
        'MINIME_WORKFLOW_RESULT: {"status":"HUMAN_REQUIRED",'
        '"summary":"Decision required", "summary_es":"Se requiere una decisión",'
        '"pending":["Option A"], "pending_es":["Opción A"]}'
    )
    stream = "\n".join(
        json.dumps(event)
        for event in [
            {"type": "turn.started"},
            {"type": "item.completed", "item": {"type": "agent_message", "text": human_required}},
            {"type": "turn.completed"},
        ]
    ).encode()

    class FakeConfinement:
        prompt = None

        def __init__(self, **_kwargs):
            pass

        def validate_command_preflight(self, *, cwd):
            return SimpleNamespace(outcome=ExternalOutcome.SUCCESS, error_message=None)

        def codex_auth_source(self, _env):
            return None

        async def run_confined_async_subprocess(self, _cmd, **kwargs):
            FakeConfinement.prompt = kwargs.get("input_bytes", b"").decode()
            return AgentProcessResult(returncode=0, stdout=stream, stderr=b"")

    monkeypatch.setattr(agent_runner_module, "AgentProcessConfinement", FakeConfinement)
    profile = CliInvocationProfile(
        provider="codex", role="thinker", executable=sys.executable,
        args=("-c", "pass"), prompt_transport="stdin",
    )
    workflow = ResolvedWorkflow(
        provider="codex", operation=operation, workflow_name=f"opsx-{operation}",
        workflow_path=".agents/skills/workflow/SKILL.md", workflow_sha256="f" * 64,
        change_name="change", dispatch_command=f"$opsx-{operation} change",
    )

    result = await CliAgentRunner(profile).run(
        tmp_path, "Run the native workflow", provider="codex", role="thinker", workflow=workflow
    )

    assert result.workflow_handoff_required is False
    assert "MINIME_WORKFLOW_RESULT:" not in FakeConfinement.prompt
    assert result.workflow_handoff is not None
    assert result.workflow_handoff.status == "HUMAN_REQUIRED"
    assert result.workflow_handoff.pending_es == ("Opción A",)


def test_sync_archive_process_success_does_not_require_final_response():
    process_result = AgentExecutionResult(
        exit_code=0,
        timed_out=False,
        stdout=[],
        stderr=[],
        duration_ms=1,
        final_response_status="MISSING",
        workflow_handoff_required=False,
    )
    assert NativeOrchestrationCoordinator._execution_is_successful(
        process_result, require_response=False
    )
    assert not NativeOrchestrationCoordinator._execution_is_successful(process_result)
    assert not NativeOrchestrationCoordinator._execution_is_successful(
        AgentExecutionResult(
            exit_code=0, timed_out=True, stdout=[], stderr=[], duration_ms=1,
            final_response_status="MISSING", workflow_handoff_required=False,
        ),
        require_response=False,
    )


@pytest.mark.asyncio
async def test_claim_heartbeat_loss_fences_the_child():
    coordinator = NativeOrchestrationCoordinator.__new__(NativeOrchestrationCoordinator)
    calls = []

    def renew(_claim, _lease):
        calls.append(True)
        return False

    uow = SimpleNamespace(renew_claim_heartbeat_isolated=renew)
    coordinator._claim_heartbeat_interval_seconds = 0.01
    claim = object()

    async def work():
        await asyncio.sleep(0.1)

    with pytest.raises(RuntimeError, match="heartbeat lost"):
        await coordinator._run_claimed(uow, claim, work)
    assert calls


def test_human_payload_is_redacted_at_the_output_boundary():
    payload = NativeOrchestrationCoordinator._safe_human_payload(
        {"question": "Use token=sk-secret12345678", "pending": ["password=hidden"]}
    )
    assert "sk-secret12345678" not in payload["question"]
    assert "password=hidden" not in payload["pending"][0]
