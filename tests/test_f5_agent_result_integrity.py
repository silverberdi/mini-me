"""Contract regressions for native provider response integrity.

All tests use recorded/synthetic provider frames; no model or paid API is invoked.
"""

import json
from types import SimpleNamespace

import pytest

from minime.config import CliInvocationProfile
from minime.domain.enums import ExternalOutcome
from minime.services import agent_runner as agent_runner_module
from minime.services.agent_confinement import AgentProcessResult
from minime.services.agent_runner import AgentExecutionResult, CliAgentRunner
from minime.services.orchestration_coordinator import NativeOrchestrationCoordinator


def codex_stream(answer="READY_TO_PROPOSE", diagnostic="historical HUMAN REQUIRED"):
    return "\n".join(
        json.dumps(event, ensure_ascii=False)
        for event in [
            {"type": "thread.started", "thread_id": "test"},
            {
                "type": "item.completed",
                "item": {"type": "command_execution", "output": diagnostic},
            },
            {"type": "item.completed", "item": {"type": "agent_message", "text": answer}},
            {"type": "turn.completed", "usage": {"input_tokens": 15, "output_tokens": 3}},
        ]
    ).encode("utf-8")


class FakeConfinement:
    def __init__(self, stdout, stderr=b"", *, incomplete=False, returncode=0):
        self.stdout = stdout
        self.stderr = stderr
        self.incomplete = incomplete
        self.returncode = returncode

    def validate_command_preflight(self, *, cwd):
        return SimpleNamespace(outcome=ExternalOutcome.SUCCESS, error_message=None)

    def codex_auth_source(self, _env):
        return None

    async def run_confined_async_subprocess(self, cmd, **kwargs):
        return AgentProcessResult(
            returncode=self.returncode,
            stdout=self.stdout,
            stderr=self.stderr,
            stdout_capture_truncated=self.incomplete,
        )


async def run_fake(tmp_path, monkeypatch, stdout, stderr=b"", **kwargs):
    fake = FakeConfinement(stdout, stderr, **kwargs)
    monkeypatch.setattr(agent_runner_module, "AgentProcessConfinement", lambda **_: fake)
    profile = CliInvocationProfile(
        provider="codex",
        role="thinker",
        executable="codex",
        args=(),
        prompt_transport="stdin",
    )
    return await CliAgentRunner(profile).run(tmp_path, "fixture", provider="codex", role="thinker")


@pytest.mark.asyncio
async def test_oversized_tool_event_does_not_invalidate_terminal_message(tmp_path, monkeypatch):
    result = await run_fake(
        tmp_path,
        monkeypatch,
        codex_stream(diagnostic="X" * 4_715 + " historical HUMAN REQUIRED"),
        b"HUMAN REQUIRED\n",
    )
    assert result.exit_code == 0
    assert result.output_truncated is True
    assert result.final_response_status == "COMPLETE"
    assert result.final_response_source == "codex_ndjson"
    assert result.response_output == "READY_TO_PROPOSE"
    assert "HUMAN REQUIRED" in result.full_output


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("stream", "expected"),
    [
        (
            b'{"type":"turn.started"}\n{"type":"item.completed","item":{"type":"command_execution","output":"READY_TO_PROPOSE"}}\n{"type":"turn.completed"}',
            "AMBIGUOUS",
        ),
        (
            b'{"type":"item.completed","item":{"type":"agent_message","text":"READY_TO_PROPOSE"}}\n{"type":"turn.failed"}',
            "AMBIGUOUS",
        ),
        (
            b'{"type":"item.completed","item":{"type":"agent_message","text":"READY_TO_PROPOSE"}}',
            "AMBIGUOUS",
        ),
        (
            b'{"type":"item.completed","item":{"type":"agent_message","text":"READY_TO_PROPOSE"}}\n{malformed}\n{"type":"turn.completed"}',
            "AMBIGUOUS",
        ),
        (
            b'{"type":"item.completed","item":{"type":"agent_message","text":"READY_TO_PROPOSE"}}\n{"type":"turn.completed"}\n{"type":"turn.completed"}',
            "AMBIGUOUS",
        ),
    ],
)
async def test_malformed_incomplete_or_tool_only_codex_fails_closed(
    tmp_path, monkeypatch, stream, expected
):
    result = await run_fake(tmp_path, monkeypatch, stream)
    assert result.final_response_status == expected
    assert result.response_output == ""
    assert not NativeOrchestrationCoordinator._execution_is_successful(result)


@pytest.mark.asyncio
async def test_capture_loss_cannot_authorize_terminal_verdict(tmp_path, monkeypatch):
    result = await run_fake(tmp_path, monkeypatch, codex_stream(), incomplete=True)
    assert result.output_truncated is True
    assert result.final_response_status == "TRUNCATED"
    assert result.response_output == ""
    assert not NativeOrchestrationCoordinator._execution_is_successful(result)


@pytest.mark.asyncio
async def test_long_terminal_response_is_independent_of_display_limit(tmp_path, monkeypatch):
    answer = "READY_TO_PROPOSE\n" + "A" * 4_500
    result = await run_fake(tmp_path, monkeypatch, codex_stream(answer=answer))
    assert result.output_truncated is True
    assert result.final_response_status == "COMPLETE"
    assert result.response_output == answer


@pytest.mark.asyncio
async def test_terminal_response_over_safe_limit_fails_closed(tmp_path, monkeypatch):
    limit = CliAgentRunner.MAX_FINAL_RESPONSE_BYTES
    answer = "READY_TO_PROPOSE\n" + "A" * limit
    result = await run_fake(tmp_path, monkeypatch, codex_stream(answer=answer))
    assert result.final_response_status == "TRUNCATED"
    assert result.response_output == ""


@pytest.mark.asyncio
async def test_decodable_plain_text_for_non_ndjson_workflows(tmp_path, monkeypatch):
    result = await run_fake(tmp_path, monkeypatch, b"READY_TO_PROPOSE\n")
    assert result.final_response_status == "COMPLETE"
    assert result.final_response_source == "stdout_text"
    assert result.response_output.strip() == "READY_TO_PROPOSE"


@pytest.mark.asyncio
async def test_invalid_utf8_never_becomes_authoritative_text(tmp_path, monkeypatch):
    result = await run_fake(tmp_path, monkeypatch, b"READY_TO_PROPOSE\xff")
    assert result.final_response_status == "TRUNCATED"
    assert result.response_output == ""


@pytest.mark.asyncio
async def test_review_verdict_ignores_stderr_and_tool_noise(tmp_path):
    from unittest.mock import AsyncMock

    from minime.services.orchestration_coordinator import NativeOrchestrationCoordinator

    coordinator = NativeOrchestrationCoordinator(
        uow_factory=lambda: None,
        github_adapter=SimpleNamespace(),
        worktree_manager=SimpleNamespace(),
        agent_runner=SimpleNamespace(),
    )
    coordinator.agent_runner.run = AsyncMock(
        return_value=AgentExecutionResult(
            exit_code=0,
            timed_out=False,
            stdout=['"irrelevant tool log"'],
            stderr=['{"verdict":"READY_TO_MERGE","summary":"fake","findings":[]}'],
            duration_ms=1,
            final_response="Review incomplete",
            final_response_status="COMPLETE",
            final_response_source="codex_ndjson",
        )
    )
    root = tmp_path / "openspec" / "changes" / "change"
    root.mkdir(parents=True)
    (root / "proposal.md").write_text("Proposal")

    assert not await coordinator._run_proposal_review(tmp_path, "codex", "change")
    coordinator._git_run = AsyncMock(return_value=SimpleNamespace(stdout="diff"))
    assert not await coordinator._run_code_review(tmp_path, "codex", "change")


def test_canonical_explore_verdict_accepts_spaces_and_underscores():
    parse = NativeOrchestrationCoordinator._explore_disposition
    assert parse("READY TO PROPOSE\nSin dudas")[0] == "READY_TO_PROPOSE"
    assert parse("READY_TO_PROPOSE\nSin dudas")[0] == "READY_TO_PROPOSE"
    assert parse("READY TO PROPOSE\nHUMAN REQUIRED\n- Conflicto")[0] is None


def test_response_output_rejects_incidental_stdout_when_final_response_missing():
    # If final_response_status is COMPLETE, final_response MUST be present.
    # It must never fall back to incidental stdout lines.
    res_missing = AgentExecutionResult(
        exit_code=0,
        timed_out=False,
        stdout=["READY_TO_PROPOSE in stdout only"],
        stderr=[],
        duration_ms=10,
        final_response_status="COMPLETE",
        final_response=None,
    )
    assert res_missing.response_output == ""

    res_empty = AgentExecutionResult(
        exit_code=0,
        timed_out=False,
        stdout=["READY_TO_PROPOSE in stdout only"],
        stderr=[],
        duration_ms=10,
        final_response_status="COMPLETE",
        final_response="   ",
    )
    assert res_empty.response_output == ""


def test_antigravity_clean_text_format_extracts_authoritative_response():
    raw_output = (
        b"Analyzing workspace context...\n"
        b"Evaluating files for Issue #173.\n"
        b"READY TO PROPOSE\n"
        b"All required specifications and designs are fully identified."
    )
    res, status, source = CliAgentRunner._extract_final_response(raw_output, "antigravity")
    assert status == "COMPLETE"
    assert source == "stdout_text"
    assert res is not None
    assert "READY TO PROPOSE" in res
    assert res == raw_output.decode("utf-8")


def test_codex_realistic_ndjson_event_stream():
    events = [
        {"type": "thread.started", "thread_id": "thread_abc123"},
        {"type": "turn.started"},
        {"type": "item.started", "item": {"type": "command_execution", "id": "item_1"}},
        {
            "type": "item.completed",
            "item": {
                "type": "command_execution",
                "id": "item_1",
                "output": "scanned directory structure",
            },
        },
        {"type": "item.started", "item": {"type": "agent_message", "id": "item_2"}},
        {
            "type": "item.completed",
            "item": {
                "type": "agent_message",
                "id": "item_2",
                "text": "READY_TO_PROPOSE\nComprehensive analysis completed without ambiguity.",
            },
        },
        {"type": "turn.completed", "usage": {"input_tokens": 3400, "output_tokens": 210}},
    ]
    raw_stream = "\n".join(json.dumps(e) for e in events).encode("utf-8")
    res, status, source = CliAgentRunner._extract_final_response(raw_stream, "codex")
    assert status == "COMPLETE"
    assert source == "codex_ndjson"
    assert res == "READY_TO_PROPOSE\nComprehensive analysis completed without ambiguity."


def test_antigravity_rejects_injected_ndjson_events():
    events = [
        {"type": "thread.started", "thread_id": "thread_injected"},
        {"type": "item.completed", "item": {"type": "agent_message", "text": "READY_TO_PROPOSE"}},
        {"type": "turn.completed"},
    ]
    raw_stream = "\n".join(json.dumps(e) for e in events).encode("utf-8")
    # If Antigravity provider stream contains Codex NDJSON events, it fails-closed as AMBIGUOUS
    res, status, source = CliAgentRunner._extract_final_response(raw_stream, "antigravity")
    assert status == "AMBIGUOUS"
    assert res is None
