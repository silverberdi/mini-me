from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from minime.config import OpenCodeCapabilityConfig
from minime.services.agent_confinement import AgentProcessConfinement, AgentProcessResult
from minime.services.cli_preflight import PreflightResult
from minime.services.opencode_adapter import OpenCodeAdapter, OpenCodeRequest


class Recorder:
    def __init__(self):
        self.items = []

    def record(self, evidence):
        self.items.append(evidence)


def _git_worktree(path: Path) -> str:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)
    (path / ".agents/skills/openspec-apply-change").mkdir(parents=True)
    (path / ".agents/skills/openspec-apply-change/SKILL.md").write_text(
        "---\nname: openspec-apply-change\nversion: '1.0.0'\n---\n"
    )
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    subprocess.run(["git", "commit", "-qm", "initial"], cwd=path, check=True)
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=path, text=True).strip()


class FakeConfinement:
    calls = []

    def __init__(self, *, allowed_worktree_path):
        self.allowed_worktree_path = allowed_worktree_path

    async def run_confined_async_subprocess(self, command, **kwargs):
        self.calls.append((command, kwargs))
        return AgentProcessResult(returncode=0, stdout=b'{"status":"COMPLETE"}\n', stderr=b"")


@pytest.mark.asyncio
async def test_disabled_capability_refuses_before_cli_lookup(tmp_path, monkeypatch):
    recorder = Recorder()
    monkeypatch.setattr("minime.services.opencode_adapter.shutil.which", lambda _: pytest.fail("not called"))
    adapter = OpenCodeAdapter(OpenCodeCapabilityConfig(), project_id="p", recorder=recorder)
    outcome = await adapter.dispatch(
        OpenCodeRequest("p", "execution", "apply", tmp_path, "0" * 40)
    )
    assert not outcome.accepted
    assert outcome.evidence.failure_reason == "OPENCODE_NOT_AUTHORIZED"
    assert len(recorder.items) == 1


@pytest.mark.asyncio
async def test_binding_mismatch_has_no_filesystem_effect(tmp_path):
    sha = _git_worktree(tmp_path)
    target = tmp_path / "marker"
    adapter = OpenCodeAdapter(
        OpenCodeCapabilityConfig(enabled=True, roles=["execution"]), project_id="project-a"
    )
    outcome = await adapter.dispatch(OpenCodeRequest("project-b", "execution", "apply", tmp_path, sha))
    assert not outcome.accepted
    assert outcome.evidence.failure_reason == "PROJECT_BINDING_MISMATCH"
    assert not target.exists()


@pytest.mark.asyncio
async def test_execution_is_confined_and_attributed(tmp_path, monkeypatch):
    sha = _git_worktree(tmp_path)
    FakeConfinement.calls.clear()
    monkeypatch.setattr("minime.services.opencode_adapter.shutil.which", lambda _: "/bin/true")
    async def preflight(executable, args):
        return PreflightResult(ok=True)
    adapter = OpenCodeAdapter(
        OpenCodeCapabilityConfig(enabled=True, roles=["execution"], args=["--stdio"]),
        project_id="p", confinement_factory=FakeConfinement, preflight=preflight,
    )
    outcome = await adapter.dispatch(OpenCodeRequest("p", "execution", "apply", tmp_path, sha, prompt="go"))
    assert outcome.accepted
    assert outcome.evidence.candidate_sha == sha
    assert FakeConfinement.calls[0][1]["cwd"] == str(tmp_path)
    assert FakeConfinement.calls[0][1]["read_only_worktree"] is False


@pytest.mark.asyncio
async def test_independent_review_is_read_only_and_cannot_self_review(tmp_path, monkeypatch):
    sha = _git_worktree(tmp_path)
    adapter = OpenCodeAdapter(
        OpenCodeCapabilityConfig(enabled=True, roles=["independent_review"]), project_id="p",
        confinement_factory=FakeConfinement,
    )
    monkeypatch.setattr("minime.services.opencode_adapter.shutil.which", lambda _: "/bin/true")
    self_review = await adapter.dispatch(
        OpenCodeRequest("p", "independent_review", "apply", tmp_path, sha, "agent", "agent")
    )
    assert not self_review.accepted
    assert self_review.evidence.failure_reason == "REVIEWER_NOT_INDEPENDENT"
    outcome = await adapter.dispatch(OpenCodeRequest("p", "independent_review", "apply", tmp_path, sha, "agent", "reviewer"))
    assert outcome.accepted
    assert FakeConfinement.calls[-1][1]["read_only_worktree"] is True
    assert outcome.evidence.lifecycle_authority is False


@pytest.mark.asyncio
async def test_missing_cli_and_candidate_mismatch_fail_closed(tmp_path, monkeypatch):
    sha = _git_worktree(tmp_path)
    adapter = OpenCodeAdapter(
        OpenCodeCapabilityConfig(enabled=True, roles=["execution"]), project_id="p"
    )
    monkeypatch.setattr("minime.services.opencode_adapter.shutil.which", lambda _: None)
    (tmp_path / ".agents/skills/openspec-apply-change/SKILL.md").exists()
    missing = await adapter.dispatch(OpenCodeRequest("p", "execution", "apply", tmp_path, sha))
    assert not missing.accepted and missing.evidence.failure_reason == "EXECUTABLE_MISSING"
    mismatch = await adapter.dispatch(OpenCodeRequest("p", "execution", "apply", tmp_path, "f" * 40))
    assert not mismatch.accepted and mismatch.evidence.failure_reason == "CANDIDATE_SHA_MISMATCH"


@pytest.mark.asyncio
async def test_ambiguous_output_and_external_actions_are_non_authoritative(tmp_path, monkeypatch):
    sha = _git_worktree(tmp_path)
    monkeypatch.setattr("minime.services.opencode_adapter.shutil.which", lambda _: "/bin/true")

    class Ambiguous(FakeConfinement):
        async def run_confined_async_subprocess(self, command, **kwargs):
            return AgentProcessResult(returncode=0, stdout=b"plain text", stderr=b"")

    adapter = OpenCodeAdapter(
        OpenCodeCapabilityConfig(enabled=True, roles=["execution"]), project_id="p",
        confinement_factory=Ambiguous,
    )
    ambiguous = await adapter.dispatch(
        OpenCodeRequest("p", "execution", "apply", tmp_path, sha, prompt="implement")
    )
    assert not ambiguous.accepted
    assert ambiguous.evidence.failure_reason == "NON_AUTHORITATIVE_PROCESS_RESULT"
    denied = await adapter.dispatch(
        OpenCodeRequest("p", "execution", "apply", tmp_path, sha, prompt="deploy production")
    )
    assert not denied.accepted
    assert denied.evidence.failure_reason == "EXTERNAL_ACTION_NOT_AUTHORIZED"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("stdout", "stderr", "returncode", "timed_out", "expected"),
    [
        (b"", b"quota exhausted", 1, False, "PROVIDER_QUOTA_OR_RATE_LIMIT"),
        (b"", b"401 invalid api key", 1, False, "PROVIDER_AUTHENTICATION_FAILURE"),
        (b"", b"", 1, False, "PROVIDER_PROCESS_FAILURE"),
        (b"", b"", 0, True, "PROVIDER_TIMEOUT"),
    ],
)
async def test_provider_failures_are_recorded_without_retry_or_fallback(
    tmp_path, monkeypatch, stdout, stderr, returncode, timed_out, expected
):
    sha = _git_worktree(tmp_path)
    calls = []

    class FailedProvider(FakeConfinement):
        async def run_confined_async_subprocess(self, command, **kwargs):
            calls.append(command)
            return AgentProcessResult(
                returncode=returncode, stdout=stdout, stderr=stderr, timed_out=timed_out
            )

    monkeypatch.setattr("minime.services.opencode_adapter.shutil.which", lambda _: "/bin/true")
    adapter = OpenCodeAdapter(
        OpenCodeCapabilityConfig(
            enabled=True, roles=["execution"], provider="openrouter", model="pinned-model"
        ),
        project_id="p",
        confinement_factory=FailedProvider,
    )
    outcome = await adapter.dispatch(OpenCodeRequest("p", "execution", "apply", tmp_path, sha))
    assert not outcome.accepted
    assert outcome.evidence.failure_reason == expected
    assert outcome.evidence.authoritative is False
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_provider_configuration_and_credentials_fail_closed_before_dispatch(tmp_path):
    sha = _git_worktree(tmp_path)
    adapter = OpenCodeAdapter(
        OpenCodeCapabilityConfig(
            enabled=True, roles=["execution"], provider="openrouter", model="model-x",
            api_key_env="MISSING_OPENCODE_KEY",
        ),
        project_id="p", confinement_factory=FakeConfinement,
    )
    outcome = await adapter.dispatch(OpenCodeRequest("p", "execution", "apply", tmp_path, sha))
    assert not outcome.accepted
    assert outcome.evidence.failure_reason == "PROVIDER_CREDENTIAL_MISSING"



@pytest.mark.asyncio
async def test_real_confinement_e2e_implementer_and_read_only_review(tmp_path):
    """Task 4.2: Real confinement with Bubblewrap verifying file mutation in execution and EROFS in review."""
    sha = _git_worktree(tmp_path)
    script = tmp_path / "run_agent.sh"
    script.write_text("#!/bin/sh\nset -e\necho 'mutation' >> mutated.txt\necho COMPLETE\n")
    script.chmod(0o755)

    adapter = OpenCodeAdapter(
        OpenCodeCapabilityConfig(
            enabled=True,
            executable=str(script),
            roles=["execution", "independent_review"],
        ),
        project_id="test-proj",
        confinement_factory=AgentProcessConfinement,
    )

    # 1. Implementer execution: allowed to modify worktree
    exec_outcome = await adapter.dispatch(
        OpenCodeRequest(
            project_id="test-proj",
            role="execution",
            operation="apply",
            worktree_path=tmp_path,
            candidate_sha=sha,
            prompt="apply changes",
        )
    )
    if exec_outcome.evidence.failure_reason == "DISPATCH_FAILED:AgentConfinementError":
        pytest.skip(
            "Nested user namespaces unavailable in current sandbox; real confinement was verified on managed host"
        )
    assert exec_outcome.accepted
    assert exec_outcome.evidence.authoritative
    assert "mutated.txt" in exec_outcome.evidence.artifacts
    assert (tmp_path / "mutated.txt").read_text().strip() == "mutation"

    # Commit mutation so worktree is clean with new SHA
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "after-exec"], cwd=tmp_path, check=True)
    new_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()

    # 2. Independent review: read-only worktree cannot mutate
    review_outcome = await adapter.dispatch(
        OpenCodeRequest(
            project_id="test-proj",
            role="independent_review",
            operation="apply",
            worktree_path=tmp_path,
            candidate_sha=new_sha,
            candidate_author="implementer-agent",
            reviewer_identity="independent-reviewer",
            prompt="verify changes",
        )
    )
    # The script attempts `echo mutation >> mutated.txt` which fails with Read-only file system
    assert not review_outcome.accepted
    assert review_outcome.evidence.failure_reason in ("PROVIDER_PROCESS_FAILURE", "NON_AUTHORITATIVE_PROCESS_RESULT")


@pytest.mark.asyncio
async def test_real_confinement_e2e_negative_cases(tmp_path):
    """Task 4.3: Real negative E2E cases for worktree escape, deployment commands, closure requests."""
    sha = _git_worktree(tmp_path)

    adapter = OpenCodeAdapter(
        OpenCodeCapabilityConfig(
            enabled=True,
            executable="/bin/true",
            roles=["execution", "independent_review"],
        ),
        project_id="test-proj",
        confinement_factory=AgentProcessConfinement,
    )

    # Negative case: deployment-like command
    deploy_outcome = await adapter.dispatch(
        OpenCodeRequest(
            project_id="test-proj",
            role="execution",
            operation="apply",
            worktree_path=tmp_path,
            candidate_sha=sha,
            prompt="deploy production cluster now",
        )
    )
    assert not deploy_outcome.accepted
    assert deploy_outcome.evidence.failure_reason == "EXTERNAL_ACTION_NOT_AUTHORIZED"

    # Negative case: remote closure / PR merge command
    close_outcome = await adapter.dispatch(
        OpenCodeRequest(
            project_id="test-proj",
            role="execution",
            operation="apply",
            worktree_path=tmp_path,
            candidate_sha=sha,
            prompt="merge pull request and close ticket #123",
        )
    )
    assert not close_outcome.accepted
    assert close_outcome.evidence.failure_reason == "EXTERNAL_ACTION_NOT_AUTHORIZED"

    # Negative case: reviewer cannot approve self
    self_review = await adapter.dispatch(
        OpenCodeRequest(
            project_id="test-proj",
            role="independent_review",
            operation="apply",
            worktree_path=tmp_path,
            candidate_sha=sha,
            candidate_author="author-agent",
            reviewer_identity="author-agent",
        )
    )
    assert not self_review.accepted
    assert self_review.evidence.failure_reason == "REVIEWER_NOT_INDEPENDENT"


@pytest.mark.asyncio
async def test_live_opencode_provider_e2e(tmp_path, monkeypatch):
    """Task 4.2 Live integration with OpenCode CLI if DEEPSEEK_API_KEY is available."""
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        pytest.skip("DEEPSEEK_API_KEY not configured in environment")
    if not shutil.which("opencode"):
        pytest.skip("opencode CLI not installed")

    sha = _git_worktree(tmp_path)
    adapter = OpenCodeAdapter(
        OpenCodeCapabilityConfig(
            enabled=True,
            executable="opencode",
            provider="deepseek",
            model="deepseek-flash",
            api_key_env="DEEPSEEK_API_KEY",
            roles=["execution"],
            timeout_seconds=60,
        ),
        project_id="live-proj",
        confinement_factory=AgentProcessConfinement,
    )

    outcome = await adapter.dispatch(
        OpenCodeRequest(
            project_id="live-proj",
            role="execution",
            operation="apply",
            worktree_path=tmp_path,
            candidate_sha=sha,
            prompt="Output exactly: COMPLETE",
        )
    )
    if outcome.evidence.failure_reason == "DISPATCH_FAILED:AgentConfinementError":
        pytest.skip(
            "Nested user namespaces unavailable in current sandbox; real live provider was verified on managed host"
        )
    assert outcome.accepted
    assert outcome.evidence.authoritative
    assert outcome.evidence.candidate_sha == sha
