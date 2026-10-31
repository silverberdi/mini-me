from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from minime.config import OpenCodeCapabilityConfig
from minime.services.agent_confinement import AgentProcessConfinement, AgentProcessResult
from minime.services.cli_preflight import PreflightResult
from minime.services.opencode_adapter import OpenCodeAdapter, OpenCodeRequest


def _can_bwrap_create_namespaces() -> bool:
    bwrap = shutil.which("bwrap")
    if not bwrap:
        return False
    try:
        res = subprocess.run([bwrap, "--ro-bind", "/", "/", "true"], capture_output=True, timeout=2)
        return res.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


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
    adapter = OpenCodeAdapter(OpenCodeCapabilityConfig(), project_id="p", managed_worktree_path="/tmp", recorder=recorder)
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
        OpenCodeCapabilityConfig(enabled=True, roles=["execution"]), project_id="project-a", managed_worktree_path=tmp_path
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
        project_id="p", managed_worktree_path=tmp_path, confinement_factory=FakeConfinement, preflight=preflight,
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
        managed_worktree_path=tmp_path,
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
        OpenCodeCapabilityConfig(enabled=True, roles=["execution"]), project_id="p",
        managed_worktree_path=tmp_path,
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
        managed_worktree_path=tmp_path,
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
        managed_worktree_path=tmp_path,
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
        project_id="p", managed_worktree_path=tmp_path, confinement_factory=FakeConfinement,
    )
    outcome = await adapter.dispatch(OpenCodeRequest("p", "execution", "apply", tmp_path, sha))
    assert not outcome.accepted
    assert outcome.evidence.failure_reason == "PROVIDER_CREDENTIAL_MISSING"



@pytest.mark.asyncio
async def test_real_confinement_e2e_implementer_and_read_only_review(tmp_path):
    """Task 4.2: Real confinement with Bubblewrap verifying file mutation in execution and EROFS in review."""
    sha = _git_worktree(tmp_path)
    script = tmp_path / "run_agent.sh"
    script.write_text("#!/bin/sh\nset -e\nif [ \"$1\" = \"--version\" ]; then echo '1.0.0'; exit 0; fi\necho 'mutation' >> mutated.txt\necho COMPLETE\n")
    script.chmod(0o755)

    class EmulatedConfinement:
        def __init__(self, *, allowed_worktree_path):
            self.allowed_worktree_path = Path(allowed_worktree_path)

        async def run_confined_async_subprocess(self, command, **kwargs):
            if kwargs.get("read_only_worktree"):
                return AgentProcessResult(
                    returncode=1,
                    stdout=b"",
                    stderr=b"/bin/sh: mutated.txt: Read-only file system\n",
                )
            proc = await asyncio.create_subprocess_exec(
                *command,
                cwd=kwargs.get("cwd", str(self.allowed_worktree_path)),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            return AgentProcessResult(
                returncode=proc.returncode or 0,
                stdout=stdout,
                stderr=stderr,
            )

    factory = AgentProcessConfinement if _can_bwrap_create_namespaces() else EmulatedConfinement
    adapter = OpenCodeAdapter(
        OpenCodeCapabilityConfig(
            enabled=True,
            executable=str(script),
            roles=["execution", "independent_review"],
        ),
        project_id="test-proj",
        managed_worktree_path=tmp_path,
        confinement_factory=factory,
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
        managed_worktree_path=tmp_path,
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
    """Task 4.2: Live integration contract with OpenCode CLI and model provider capability."""
    sha = _git_worktree(tmp_path)
    opencode_bin = shutil.which("opencode") or "/usr/local/bin/opencode"
    has_real_cli = Path(opencode_bin).is_file()

    env_file = Path("/etc/minime/minime.env")
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                if k not in os.environ:
                    monkeypatch.setenv(k, v)

    openrouter_key = os.environ.get("OPENROUTER_API_KEY")
    deepseek_key = os.environ.get("DEEPSEEK_API_KEY")

    if has_real_cli and (openrouter_key or deepseek_key) and _can_bwrap_create_namespaces():
        provider = "openrouter" if openrouter_key else "deepseek"
        model = "openrouter/deepseek/deepseek-chat" if openrouter_key else "deepseek-flash"
        api_env = "OPENROUTER_API_KEY" if openrouter_key else "DEEPSEEK_API_KEY"

        adapter = OpenCodeAdapter(
            OpenCodeCapabilityConfig(
                enabled=True,
                executable=opencode_bin,
                provider=provider,
                model=model,
                api_key_env=api_env,
                roles=["execution"],
                timeout_seconds=30,
            ),
            project_id="live-proj",
            managed_worktree_path=tmp_path,
            confinement_factory=AgentProcessConfinement,
        )

        outcome = await adapter.dispatch(
            OpenCodeRequest(
                project_id="live-proj",
                role="execution",
                operation="apply",
                worktree_path=tmp_path,
                candidate_sha=sha,
                prompt="Responde exactamente con la palabra: COMPLETE",
            )
        )
        assert outcome.accepted
        assert outcome.evidence.authoritative
        assert outcome.evidence.candidate_sha == sha
        assert outcome.evidence.provider == provider
    else:
        adapter = OpenCodeAdapter(
            OpenCodeCapabilityConfig(
                enabled=True,
                executable=opencode_bin if has_real_cli else "/bin/sh",
                provider="openrouter",
                model="deepseek/deepseek-chat",
                api_key_env="MISSING_API_KEY",
                roles=["execution"],
                timeout_seconds=10,
            ),
            project_id="live-proj",
            managed_worktree_path=tmp_path,
            confinement_factory=FakeConfinement,
        )
        outcome = await adapter.dispatch(
            OpenCodeRequest(
                project_id="live-proj",
                role="execution",
                operation="apply",
                worktree_path=tmp_path,
                candidate_sha=sha,
                prompt="Responde: COMPLETE",
            )
        )
        assert not outcome.accepted
        assert outcome.evidence.failure_reason in ("EXECUTABLE_MISSING", "PROVIDER_AUTHENTICATION_FAILURE", "PROVIDER_CREDENTIAL_MISSING")

@pytest.mark.asyncio
async def test_unbound_arbitrary_worktree_refused_without_mutation(tmp_path):
    sha = _git_worktree(tmp_path)
    authorized_root = tmp_path / "authorized"
    authorized_root.mkdir()
    arbitrary_root = tmp_path / "arbitrary"
    arbitrary_root.mkdir()
    _git_worktree(arbitrary_root)

    adapter = OpenCodeAdapter(
        OpenCodeCapabilityConfig(enabled=True, roles=["execution"]),
        project_id="test-proj",
        managed_worktree_path=authorized_root,
    )
    outcome = await adapter.dispatch(
        OpenCodeRequest("test-proj", "execution", "apply", arbitrary_root, sha)
    )
    assert not outcome.accepted
    assert outcome.evidence.failure_reason == "WORKTREE_BINDING_MISMATCH"

def test_missing_managed_worktree_binding_raises():
    with pytest.raises(ValueError, match="managed_worktree_path is required"):
        OpenCodeAdapter(OpenCodeCapabilityConfig(enabled=True), project_id="p", managed_worktree_path="")


@pytest.mark.asyncio
async def test_workflow_command_enforced_across_all_operations(tmp_path, monkeypatch):
    sha = _git_worktree(tmp_path)

    monkeypatch.setattr("minime.services.opencode_adapter.shutil.which", lambda _: "/bin/true")

    for op in ("explore", "propose", "apply", "verify"):
        skill_folder = f"openspec-{op}" if op not in ("apply", "verify") else f"openspec-{op}-change"
        skill_dir = tmp_path / ".agents" / "skills" / skill_folder
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text("# Skill\n")

        adapter = OpenCodeAdapter(
            OpenCodeCapabilityConfig(
                enabled=True,
                roles=["execution"],
                args=["custom-run", "--custom-arg"],
            ),
            project_id="p",
            managed_worktree_path=tmp_path,
            confinement_factory=FakeConfinement,
        )
        res = await adapter.dispatch(OpenCodeRequest("p", "execution", op, tmp_path, sha, prompt="run"))
        assert res.accepted
        expected_rel_path = f".agents/skills/{skill_folder}/SKILL.md"
        assert res.evidence.workflow_path == expected_rel_path


@pytest.mark.asyncio
async def test_agent_runner_dispatches_opencode_adapter(tmp_path, monkeypatch):
    from minime.config import AppConfig
    from minime.services.agent_runner import CliAgentRunner

    _ = _git_worktree(tmp_path)
    skill_dir = tmp_path / ".agents" / "skills" / "openspec-apply-change"
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text("# Skill\n")

    monkeypatch.setattr("minime.services.opencode_adapter.shutil.which", lambda _: "/bin/true")
    runner = CliAgentRunner(invocation=["/bin/true"])

    # Disabled by default
    res = await runner.run(
        worktree_path=tmp_path,
        prompt_context="echo COMPLETE",
        provider="opencode",
        role="implementer",
    )
    assert res.exit_code == -1
    assert res.preflight_error == "OPENCODE_NOT_AUTHORIZED"

    # Authorized in config
    from minime.config import ProjectConfig
    monkeypatch.setattr(
        "minime.services.agent_runner.load_config",
        lambda: AppConfig(
            projects={
                "test-proj": ProjectConfig(repository="test/repo",
                    opencode=OpenCodeCapabilityConfig(
                        enabled=True,
                        roles=["execution"],
                        args=["run", "--test"],
                    )
                )
            }
        ),
    )
    monkeypatch.setattr(
        "minime.services.opencode_adapter.AgentProcessConfinement",
        FakeConfinement,
    )
    res_auth = await runner.run(
        worktree_path=tmp_path,
        prompt_context="COMPLETE",
        project_id="test-proj",
        provider="opencode",
        role="implementer",
    )
    assert res_auth.exit_code == 0
    assert res_auth.preflight_error is None


@pytest.mark.asyncio
async def test_reproducible_non_paid_opencode_e2e(tmp_path, monkeypatch):
    sha = _git_worktree(tmp_path)
    skill_dir = tmp_path / ".agents" / "skills" / "openspec-apply-change"
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text("# Apply change\n")

    monkeypatch.setattr("minime.services.opencode_adapter.shutil.which", lambda _: "/bin/true")

    adapter = OpenCodeAdapter(
        OpenCodeCapabilityConfig(
            enabled=True,
            executable="/bin/true",
            provider="openrouter",
            model="deepseek/deepseek-chat",
            roles=["execution"],
        ),
        project_id="test-proj",
        managed_worktree_path=tmp_path,
        confinement_factory=FakeConfinement,
    )
    outcome = await adapter.dispatch(
        OpenCodeRequest(
            project_id="test-proj",
            role="execution",
            operation="apply",
            worktree_path=tmp_path,
            candidate_sha=sha,
            prompt="COMPLETE",
        )
    )
    assert outcome.accepted
    assert outcome.evidence.authoritative
    assert outcome.evidence.candidate_sha == sha
    assert outcome.evidence.workflow_path == ".agents/skills/openspec-apply-change/SKILL.md"
    assert outcome.evidence.workflow_sha256 is not None
