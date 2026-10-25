"""Deterministic contracts for Codex's structured response channel."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from minime.config import CliInvocationProfile
from minime.domain.enums import ExternalOutcome, ExternalReasonCode, RetrySafety
from minime.domain.models import ExternalActionResult, OrchestrationRun
from minime.services import agent_runner as agent_runner_module
from minime.services.agent_confinement import AgentProcessResult
from minime.services.agent_runner import AgentExecutionResult, CliAgentRunner
from minime.services.orchestration_coordinator import NativeOrchestrationCoordinator
from minime.services.request_normalization import (
    RequestNormalizationError,
    RequestNormalizationService,
)


class _FakeConfinement:
    def __init__(self, *, response: str, diagnostic_line: str = ""):
        self.response = response
        self.diagnostic_line = diagnostic_line

    def validate_command_preflight(self, *, cwd):
        return SimpleNamespace(outcome=ExternalOutcome.SUCCESS, error_message=None)

    def codex_auth_source(self, _env):
        return None

    async def run_confined_async_subprocess(self, cmd, **_kwargs):
        response_path = Path(cmd[cmd.index("--output-last-message") + 1])
        response_path.write_text(self.response, encoding="utf-8")
        return AgentProcessResult(
            returncode=0,
            stdout=b"diagnostic " + self.diagnostic_line.encode("utf-8"),
            stderr=b"stderr " + self.diagnostic_line.encode("utf-8"),
        )


def _runner(tmp_path, monkeypatch, response, diagnostic_line=""):
    fake = _FakeConfinement(response=response, diagnostic_line=diagnostic_line)
    monkeypatch.setattr(agent_runner_module, "AgentProcessConfinement", lambda **_: fake)
    profile = CliInvocationProfile(
        provider="codex",
        role="thinker",
        executable="codex",
        args=(),
        prompt_transport="stdin",
    )
    runner = CliAgentRunner(profile)
    return runner, tmp_path / "response.json"


@pytest.mark.asyncio
async def test_long_diagnostics_do_not_truncate_structured_json(tmp_path, monkeypatch):
    payload = {"value": "x" * 4_500}
    runner, response_path = _runner(tmp_path, monkeypatch, json.dumps(payload), "d" * 5_000)

    result = await runner.run(
        tmp_path,
        "prompt",
        provider="codex",
        workflow=None,
        output_schema={"type": "object"},
        output_last_message_path=response_path,
    )

    assert result.output_truncated is True
    assert result.structured_output_too_large is False
    assert json.loads(result.response_output) == payload


@pytest.mark.asyncio
async def test_structured_json_over_safe_limit_fails_closed(tmp_path, monkeypatch):
    oversized = "{" + "x" * (CliAgentRunner.MAX_STRUCTURED_OUTPUT_BYTES + 1) + "}"
    runner, response_path = _runner(tmp_path, monkeypatch, oversized)

    result = await runner.run(
        tmp_path,
        "prompt",
        provider="codex",
        workflow=None,
        output_schema={"type": "object"},
        output_last_message_path=response_path,
    )

    assert result.structured_output_too_large is True
    assert result.response_output == ""


@pytest.mark.asyncio
async def test_validated_checkpoint_reconciles_without_dispatch(tmp_path):
    original = "Solicitud informal con C1."
    normalized = "Feature: Ordenación\n\nScenario: C1\n  Given una entrada\n  When se procesa\n  Then C1 se conserva"
    issue = {"number": 5, "body": original, "title": "Ordenar", "repository_url": "/repos/o/r"}
    comments = []

    def ok(data, evidence=None):
        return ExternalActionResult(
            outcome=ExternalOutcome.SUCCESS,
            source_adapter="test",
            reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
            retry_safety=RetrySafety.SAFE,
            data=data,
            observed_evidence=evidence or {"etag": '"v1"'},
        )

    class Github:
        def get_issue(self, *_):
            return ok(issue)

        def list_issue_comments(self, *_):
            return ok(comments)

        def comment_issue(self, _repo, _number, body, _key):
            comments.append({"body": body})
            return ok(comments[-1])

        def update_issue_body(self, _repo, _number, body, expected_version=None):
            issue["body"] = body
            return ok(issue)

    class Runner:
        def run(self, **_kwargs):
            raise AssertionError("validated checkpoint must not dispatch an agent")

    run = OrchestrationRun(
        project_id="project",
        change_name="issue-5",
        base_sha="main",
        stop_details={
            "normalization_attempt": {
                "status": "SUCCEEDED",
                "response_status": "VALIDATED",
                "publish_status": "FAILED",
            },
            "validated_normalization_response": {
                "original_body": original,
                "normalized_body": normalized,
                "criteria": ["C1"],
                "semantic_message": "Se conservó C1.",
            },
        },
    )

    class Runs:
        def get_by_id(self, _run_id):
            return run

        def save(self, value):
            nonlocal run
            run = value

    class Uow:
        orchestration_runs = Runs()

        def commit(self):
            return None

    coordinator = NativeOrchestrationCoordinator(
        uow_factory=Uow,
        github_adapter=Github(),
        worktree_manager=object(),
        agent_runner=Runner(),
    )
    result, error = await coordinator._normalize_request_before_explore(
        active_run=run,
        project_id="project",
        repository="o/r",
        worktree_path=tmp_path,
        issue_number=5,
        issue_title="Ordenar",
        issue_body=original,
        provider="codex",
    )

    assert error == normalized
    assert result["normalized_body"] == normalized
    assert run.stop_details["normalization_attempt"]["publish_status"] == "CONFIRMED"


@pytest.mark.asyncio
async def test_invalid_gherkin_is_rejected_before_remote_writes(tmp_path):
    issue = {"number": 6, "body": "Solicitud informal", "title": "Ordenar"}
    writes = []

    class Github:
        def get_issue(self, *_):
            return ExternalActionResult(
                outcome=ExternalOutcome.SUCCESS,
                source_adapter="test",
                reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
                retry_safety=RetrySafety.SAFE,
                data=issue,
            )

        def list_issue_comments(self, *_):
            return ExternalActionResult(
                outcome=ExternalOutcome.SUCCESS,
                source_adapter="test",
                reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
                retry_safety=RetrySafety.SAFE,
                data=[],
            )

        def comment_issue(self, *_args):
            writes.append("comment")

        def update_issue_body(self, *_args, **_kwargs):
            writes.append("update")

    class Runner:
        @staticmethod
        def observed_usage(_result):
            return None

        def resolve_workflow(self, **_kwargs):
            return SimpleNamespace(dispatch_command="$minime-request-normalizer issue-6", workflow_sha256="wf")

        async def run(self, **_kwargs):
            return AgentExecutionResult(
                exit_code=0,
                timed_out=False,
                stdout=[],
                stderr=[],
                duration_ms=1,
                structured_output=[
                    json.dumps(
                        {
                            "normalized_body": "not Gherkin",
                            "criteria": ["C1"],
                            "semantic_message": "Se recibió la solicitud.",
                        }
                    )
                ],
                diagnostic_output=[],
            )

    run = OrchestrationRun(project_id="project", change_name="issue-6", base_sha="main")

    class Runs:
        def get_by_id(self, _run_id):
            return run

        def save(self, value):
            nonlocal run
            run = value

    class Uow:
        orchestration_runs = Runs()

        def commit(self):
            return None

    coordinator = NativeOrchestrationCoordinator(
        uow_factory=Uow,
        github_adapter=Github(),
        worktree_manager=object(),
        agent_runner=Runner(),
    )
    result, error = await coordinator._normalize_request_before_explore(
        active_run=run,
        project_id="project",
        repository="o/r",
        worktree_path=tmp_path,
        issue_number=6,
        issue_title="Ordenar",
        issue_body=issue["body"],
        provider="codex",
    )

    assert result is None
    assert "Gherkin" in error
    assert writes == []
    assert run.stop_details["normalization_attempt"]["response_status"] == "INVALID"


def test_semantic_message_limit_is_fail_closed_before_publish():
    with pytest.raises(RequestNormalizationError):
        RequestNormalizationService.semantic_comment("x" * 2_001, "run:6")
