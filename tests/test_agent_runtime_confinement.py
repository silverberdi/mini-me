"""Focused tests for attempt-private agent state and failure classification."""

import asyncio
import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from minime.domain.enums import (
    ContinuationDecision,
    ExecutionOutcome,
    ProviderResultClass,
)
from minime.services.agent_confinement import (
    AgentConfinementError,
    AgentCredentialError,
    AgentProcessConfinement,
)
from minime.services.continuation_engine import ContinuationContext, ContinuationEngine
from minime.services.implementer_runner import CliImplementerRunner
from minime.services.outcome_governance import (
    CompletionVerificationResult,
    OutcomeGovernanceService,
)
from minime.services.provider_outcome_parser import ProviderOutcomeParser
from minime.services.reviewer_runner import CliReviewerRunner


def _confinement(tmp_path: Path) -> tuple[AgentProcessConfinement, Path, Path]:
    worktree = tmp_path / "execution-worktree"
    runtime = tmp_path / "runtime"
    worktree.mkdir()
    runtime.mkdir()
    return (
        AgentProcessConfinement(
            allowed_worktree_path=str(worktree),
            runtime_root=str(runtime),
            private_state_parent=str(tmp_path),
            require_kernel_confinement=False,
        ),
        worktree,
        runtime,
    )


def test_runtime_root_uses_explicit_environment_and_missing_fallback_fails_closed(
    tmp_path: Path, monkeypatch
):
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    configured = tmp_path / "configured-runtime"
    configured.mkdir(mode=0o700)
    monkeypatch.setenv("MINIME_RUNTIME_ROOT", str(configured))
    configured_confinement = AgentProcessConfinement(
        str(worktree), require_kernel_confinement=False
    )
    assert configured_confinement.runtime_root == str(configured)

    monkeypatch.delenv("MINIME_RUNTIME_ROOT")
    monkeypatch.chdir(tmp_path)
    real_isdir = os.path.isdir
    monkeypatch.setattr(
        "minime.services.agent_confinement.os.path.isdir",
        lambda path: False
        if path in {"/opt/minime/runtime", "/opt/minime/app/.minime"}
        else real_isdir(path),
    )
    fallback_confinement = AgentProcessConfinement(
        str(worktree), require_kernel_confinement=False
    )
    assert fallback_confinement.runtime_root == str(tmp_path / ".minime")
    preflight = fallback_confinement.validate_command_preflight(str(worktree))
    assert preflight.error_message == "Runtime root is not an available directory."


def test_attempt_state_is_private_sanitized_and_removed(tmp_path: Path):
    confinement, _worktree, _runtime = _confinement(tmp_path)
    auth = tmp_path / "authorized-codex-auth.json"
    auth.write_text('{"access_token":"do-not-log"}', encoding="utf-8")
    auth.chmod(0o600)
    base_env = {
        "HOME": "/global/home",
        "CODEX_HOME": "/global/codex",
        "TMPDIR": "/host/tmp",
        "XDG_RUNTIME_DIR": "/host/run",
        "OPENAI_API_KEY": "must-not-inherit",
        "NORMAL_SETTING": "preserved",
    }

    with confinement.runtime_session(base_env, str(auth)) as runtime:
        root = runtime.host_root
        assert stat.S_IMODE(root.stat().st_mode) == 0o700
        assert stat.S_IMODE(runtime.auth_copy.stat().st_mode) == 0o600
        assert runtime.auth_copy.read_bytes() == auth.read_bytes()
        assert "do-not-log" in runtime.sensitive_values
        env_root = (
            runtime.sandbox_root if confinement.confinement_mechanism == "bubblewrap" else str(root)
        )
        assert runtime.environment["CODEX_HOME"] == f"{env_root}/codex"
        assert runtime.environment["HOME"] == f"{env_root}/home"
        assert runtime.environment["TMPDIR"] == f"{env_root}/tmp"
        assert runtime.environment["XDG_RUNTIME_DIR"] == f"{env_root}/runtime"
        assert "OPENAI_API_KEY" not in runtime.environment
        assert runtime.environment["NORMAL_SETTING"] == "preserved"

    assert not root.exists()
    assert auth.read_text(encoding="utf-8") == '{"access_token":"do-not-log"}'
    assert (
        AgentProcessConfinement._scrub_credential_values(b"CLI echoed do-not-log", ("do-not-log",))
        == b"CLI echoed [REDACTED_CODEX_CREDENTIAL]"
    )


def test_private_credential_rotation_is_detected_and_never_copied_back(tmp_path: Path):
    confinement, _worktree, _runtime = _confinement(tmp_path)
    auth = tmp_path / "auth.json"
    auth.write_text('{"token":"original"}', encoding="utf-8")
    auth.chmod(0o600)

    with confinement.runtime_session({}, str(auth)) as runtime:
        runtime.auth_copy.write_text('{"token":"rotated"}', encoding="utf-8")
        assert runtime.observe_credential_state() is True
        root = runtime.host_root

    assert not root.exists()
    assert auth.read_text(encoding="utf-8") == '{"token":"original"}'


@pytest.mark.skipif(
    not AgentProcessConfinement.is_host_confinement_available(),
    reason="confined credential-output suppression requires an OS confinement mechanism",
)
def test_rotated_codex_credentials_and_child_output_are_never_returned(tmp_path: Path):
    confinement, worktree, _runtime = _confinement(tmp_path)
    auth = tmp_path / "auth.json"
    auth.write_text('{"token":"old-secret-token"}', encoding="utf-8")
    auth.chmod(0o600)
    script = (
        "import json,os,pathlib; "
        "p=pathlib.Path(os.environ['CODEX_HOME'])/'auth.json'; "
        "p.write_text(json.dumps({'token':'new-rotated-secret'})); "
        "print('new-rotated-secret')"
    )
    result = asyncio.run(
        confinement.run_confined_async_subprocess(
            [sys.executable, "-c", script],
            cwd=str(worktree),
            input_bytes=None,
            timeout_seconds=10,
            env=os.environ.copy(),
            codex_auth_source=str(auth),
        )
    )
    assert result.credential_rotation_detected is True
    assert result.stdout == b""
    assert b"new-rotated-secret" not in result.stderr
    assert auth.read_text(encoding="utf-8") == '{"token":"old-secret-token"}'


def test_unsafe_or_symlinked_credential_source_fails_closed(tmp_path: Path):
    confinement, _worktree, _runtime = _confinement(tmp_path)
    auth = tmp_path / "auth.json"
    auth.write_text("{}", encoding="utf-8")
    auth.chmod(0o620)
    with pytest.raises(AgentCredentialError):
        with confinement.runtime_session({}, str(auth)):
            pytest.fail("unsafe auth source should not enter the runtime")

    auth.chmod(0o600)
    link = tmp_path / "auth-link.json"
    link.symlink_to(auth)
    with pytest.raises(AgentCredentialError):
        with confinement.runtime_session({}, str(link)):
            pytest.fail("symlink auth source should not enter the runtime")


def test_antigravity_auth_source_resolves_actual_cli_oauth_path(tmp_path: Path):
    host_home = tmp_path / "service-home"
    assert AgentProcessConfinement.antigravity_auth_source({"HOME": str(host_home)}) == str(
        host_home / ".gemini" / "antigravity-cli" / "antigravity-oauth-token"
    )


def test_antigravity_auth_is_projected_as_one_private_file_and_rotation_is_not_persisted(
    tmp_path: Path,
):
    confinement, _worktree, _runtime = _confinement(tmp_path)
    host_home = tmp_path / "host-home"
    gemini_home = host_home / ".gemini"
    gemini_home.mkdir(parents=True)
    host_cli_home = gemini_home / "antigravity-cli"
    host_cli_home.mkdir(mode=0o700)
    source = host_cli_home / "antigravity-oauth-token"
    source.write_text("opaque-authentication-token-for-test", encoding="utf-8")
    source.chmod(0o600)
    (gemini_home / "settings.json").write_text('{"unrelated":"host-only"}', encoding="utf-8")

    with confinement.runtime_session(
        {"HOME": str(host_home)}, antigravity_auth_source=str(source)
    ) as runtime:
        # The credential copy is a host-side private file, while the CLI sees
        # the same directory through Bubblewrap's /run/minime-agent mount.
        private_home = runtime.host_root / "home"
        expected_cli_home = (
            Path(runtime.sandbox_root) / "home"
            if confinement.confinement_mechanism == "bubblewrap"
            else private_home
        )
        assert Path(runtime.environment["HOME"]) == expected_cli_home
        private_gemini_home = private_home / ".gemini"
        private_cli_home = private_gemini_home / "antigravity-cli"
        projected = runtime.antigravity_auth_copy
        assert projected == private_cli_home / "antigravity-oauth-token"
        assert projected.read_text(encoding="utf-8") == "opaque-authentication-token-for-test"
        assert stat.S_IMODE(projected.stat().st_mode) == 0o600
        assert stat.S_IMODE(private_gemini_home.stat().st_mode) == 0o700
        assert stat.S_IMODE(private_cli_home.stat().st_mode) == 0o700
        assert {path.name for path in private_gemini_home.iterdir()} == {"antigravity-cli"}
        assert {path.name for path in private_cli_home.iterdir()} == {"antigravity-oauth-token"}
        assert "opaque-authentication-token-for-test" in runtime.sensitive_values
        projected.write_text("rotated-private-token", encoding="utf-8")
        assert runtime.observe_credential_state() is True
        private_root = runtime.host_root

    assert not private_root.exists()
    assert source.read_text(encoding="utf-8") == "opaque-authentication-token-for-test"
    assert "host-only" in (gemini_home / "settings.json").read_text(encoding="utf-8")


def _fake_antigravity_oauth(*, access="old-access-secret", refresh="stable-refresh-secret"):
    return {
        "token": {
            "access_token": access,
            "token_type": "Bearer",
            "refresh_token": refresh,
            "expiry": "2026-10-12T12:00:00Z",
        },
        "auth_method": "oauth",
    }


@pytest.mark.parametrize(
    "change,expected",
    [
        ({"access_token": "new-access-secret", "expiry": "2026-10-12T13:00:00Z"}, True),
        ({"refresh_token": "rotated-refresh-secret"}, False),
        ({"token_type": "Other"}, False),
        ({"extra_field": "unexpected"}, False),
        ({"access_token": ""}, False),
    ],
)
def test_antigravity_oauth_rotation_classifier_accepts_access_refresh_only(change, expected):
    from minime.services.agent_confinement import AgentRuntimeState

    original = _fake_antigravity_oauth()
    changed = json.loads(json.dumps(original))
    changed["token"].update(change)
    assert (
        AgentRuntimeState._is_access_refresh_only(
            json.dumps(original).encode(), json.dumps(changed).encode()
        )
        is expected
    )


def test_antigravity_access_refresh_detection_keeps_persistent_source_unchanged(tmp_path: Path):
    confinement, _worktree, _runtime = _confinement(tmp_path)
    source = tmp_path / "ag-oauth-token"
    original = _fake_antigravity_oauth()
    source.write_text(json.dumps(original), encoding="utf-8")
    source.chmod(0o600)

    with confinement.runtime_session({}, antigravity_auth_source=str(source)) as runtime:
        changed = _fake_antigravity_oauth(access="new-access-secret")
        changed["token"]["expiry"] = "2026-10-12T13:00:00Z"
        runtime.antigravity_auth_copy.write_text(json.dumps(changed), encoding="utf-8")
        assert runtime.observe_credential_state() is True
        assert runtime.credential_access_refresh_only is True
        private_root = runtime.host_root

    assert not private_root.exists()
    assert json.loads(source.read_text(encoding="utf-8")) == original


@pytest.mark.skipif(
    not AgentProcessConfinement.is_host_confinement_available(),
    reason="real Bubblewrap is required to prove stdout redaction of refreshed credentials",
)
def test_real_bubblewrap_access_refresh_redacts_new_token_and_preserves_result(tmp_path: Path):
    confinement, worktree, _runtime = _confinement(tmp_path)
    source = tmp_path / "ag-oauth-token"
    source.write_text(json.dumps(_fake_antigravity_oauth()), encoding="utf-8")
    source.chmod(0o600)
    script = (
        "import json,os,pathlib; "
        "p=pathlib.Path(os.environ['HOME'])/'.gemini'/'antigravity-cli'/'antigravity-oauth-token'; "
        "d=json.loads(p.read_text()); "
        "d['token']['access_token']='new-access-secret'; "
        "d['token']['expiry']='2026-10-12T13:00:00Z'; "
        "p.write_text(json.dumps(d)); "
        "print('review-result new-access-secret old-access-secret')"
    )
    result = asyncio.run(
        confinement.run_confined_async_subprocess(
            [sys.executable, "-c", script],
            cwd=str(worktree),
            input_bytes=None,
            timeout_seconds=10,
            env=os.environ.copy(),
            antigravity_auth_source=str(source),
        )
    )
    assert result.returncode == 0
    assert result.credential_rotation_detected is True
    assert result.credential_access_refresh_only is True
    assert b"review-result" in result.stdout
    assert b"new-access-secret" not in result.stdout + result.stderr
    assert b"old-access-secret" not in result.stdout + result.stderr
    assert json.loads(source.read_text(encoding="utf-8")) == _fake_antigravity_oauth()


@pytest.mark.skipif(
    not AgentProcessConfinement.is_host_confinement_available(),
    reason="real Bubblewrap is required to prove refresh-authority rotation fails closed",
)
def test_real_bubblewrap_refresh_authority_rotation_suppresses_output(tmp_path: Path):
    confinement, worktree, _runtime = _confinement(tmp_path)
    source = tmp_path / "ag-oauth-token"
    source.write_text(json.dumps(_fake_antigravity_oauth()), encoding="utf-8")
    source.chmod(0o600)
    script = (
        "import json,os,pathlib; "
        "p=pathlib.Path(os.environ['HOME'])/'.gemini'/'antigravity-cli'/'antigravity-oauth-token'; "
        "d=json.loads(p.read_text()); "
        "d['token']['refresh_token']='rotated-refresh-secret'; "
        "p.write_text(json.dumps(d)); "
        "print('sensitive-output rotated-refresh-secret')"
    )
    result = asyncio.run(
        confinement.run_confined_async_subprocess(
            [sys.executable, "-c", script],
            cwd=str(worktree),
            input_bytes=None,
            timeout_seconds=10,
            env=os.environ.copy(),
            antigravity_auth_source=str(source),
        )
    )
    assert result.credential_rotation_detected is True
    assert result.credential_access_refresh_only is False
    assert result.stdout == b""
    assert b"rotated-refresh-secret" not in result.stderr
    assert json.loads(source.read_text(encoding="utf-8")) == _fake_antigravity_oauth()


def test_antigravity_auth_source_rejects_symlinks_and_unsafe_permissions(tmp_path: Path):
    confinement, _worktree, _runtime = _confinement(tmp_path)
    source = tmp_path / "agy-token"
    source.write_text("opaque-authentication-token", encoding="utf-8")
    source.chmod(0o640)
    with pytest.raises(AgentCredentialError):
        with confinement.runtime_session({}, antigravity_auth_source=str(source)):
            pytest.fail("group-readable auth source should fail closed")
    source.chmod(0o600)
    symlink = tmp_path / "agy-token-link"
    symlink.symlink_to(source)
    with pytest.raises(AgentCredentialError):
        with confinement.runtime_session({}, antigravity_auth_source=str(symlink)):
            pytest.fail("symlinked auth source should fail closed")


@pytest.mark.skipif(
    not AgentProcessConfinement.is_host_confinement_available(),
    reason="real Linux Bubblewrap is required for write-boundary proof",
)
def test_real_bubblewrap_projects_only_antigravity_auth_and_enforces_write_boundary(
    tmp_path: Path,
):
    confinement, worktree, runtime_root = _confinement(tmp_path)
    source = tmp_path / "agy-token"
    source.write_text("private-auth-token-for-test", encoding="utf-8")
    source.chmod(0o600)
    unrelated_home = tmp_path / "host-home"
    unrelated_gemini = unrelated_home / ".gemini"
    unrelated_gemini.mkdir(parents=True)
    unrelated_file = unrelated_gemini / "settings.json"
    unrelated_file.write_text("host-only", encoding="utf-8")
    script = "\n".join(
        (
            "import os,pathlib",
            "home=pathlib.Path(os.environ['HOME'])",
            "gemini=home/'.gemini'",
            "assert [p.name for p in gemini.iterdir()]==['antigravity-cli']",
            "cli=gemini/'antigravity-cli'",
            "assert [p.name for p in cli.iterdir()]==['antigravity-oauth-token']",
            "assert (cli/'antigravity-oauth-token').read_text()=='private-auth-token-for-test'",
            "pathlib.Path(os.environ['MINIME_CONFINED_WORKTREE'],'allowed.txt').write_text('ok')",
            "blocked=False",
            "try:",
            " pathlib.Path(os.environ['MINIME_RUNTIME_ROOT'],'denied.txt').write_text('no')",
            "except OSError:",
            " blocked=True",
            "assert blocked",
            f"blocked=False\ntry:\n pathlib.Path({str(unrelated_file)!r}).write_text('no')",
            "except OSError:",
            " blocked=True",
            "assert blocked",
            "print('boundary-ok')",
        )
    )

    with confinement.runtime_session(
        {"HOME": str(unrelated_home)}, antigravity_auth_source=str(source)
    ) as runtime:
        private_root = runtime.host_root
        wrapped = confinement.wrap_command([sys.executable, "-c", script], runtime)
        result = subprocess.run(
            wrapped,
            cwd=str(worktree),
            env=runtime.environment,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "boundary-ok"

    assert not private_root.exists()
    assert (worktree / "allowed.txt").read_text(encoding="utf-8") == "ok"
    assert not (runtime_root / "denied.txt").exists()
    assert unrelated_file.read_text(encoding="utf-8") == "host-only"
    assert source.read_text(encoding="utf-8") == "private-auth-token-for-test"


@pytest.mark.skipif(
    not AgentProcessConfinement.is_host_confinement_available() or not shutil.which("agy"),
    reason="real Bubblewrap and Antigravity CLI are required for catalog-auth proof",
)
def test_real_bubblewrap_agy_models_authenticates_without_inference(tmp_path: Path):
    confinement, worktree, _runtime = _confinement(tmp_path)
    source = Path(AgentProcessConfinement.antigravity_auth_source())
    if not source.is_file():
        pytest.skip("authorized Antigravity auth source is unavailable")
    result = asyncio.run(
        confinement.run_confined_async_subprocess(
            [shutil.which("agy") or "agy", "models"],
            cwd=str(worktree),
            input_bytes=None,
            timeout_seconds=60,
            env=os.environ.copy(),
            antigravity_auth_source=str(source),
        )
    )
    # `agy models` performs auth/catalog observation only; it sends no model prompt.
    assert result.returncode == 0, "confined `agy models` authentication/catalog check failed"
    # A real OAuth access-token refresh is legitimate only if its refresh
    # authority and all other metadata are unchanged.
    assert not result.credential_rotation_detected or result.credential_access_refresh_only
    assert b"Provider credential rotation was not persisted." not in result.stderr
    assert b"antigravity-oauth-token" not in result.stdout + result.stderr


def test_bubblewrap_command_binds_only_worktree_and_private_state(tmp_path: Path, monkeypatch):
    confinement, worktree, runtime_root = _confinement(tmp_path)
    confinement.confinement_mechanism = "bubblewrap"
    monkeypatch.setattr(confinement, "_host_resolver_projection", lambda: None)
    with confinement.runtime_session({}) as runtime:
        command = confinement.wrap_command(["/usr/bin/true"], runtime)

    assert command[command.index("--bind") + 1 : command.index("--bind") + 3] == [
        str(worktree.resolve()),
        str(worktree.resolve()),
    ]
    assert ["--ro-bind", str(runtime_root.resolve()), str(runtime_root.resolve())] == [
        command[i : i + 3]
        for i in range(len(command) - 2)
        if command[i] == "--ro-bind" and command[i + 1] == str(runtime_root.resolve())
    ][0]
    ro_root_idx = [
        i
        for i in range(len(command) - 2)
        if command[i] == "--ro-bind" and command[i + 1] == "/" and command[i + 2] == "/"
    ][0]
    assert command[ro_root_idx + 3 : ro_root_idx + 5] == ["--dev", "/dev"]
    assert ["--dev", "/dev"] == command[command.index("--dev") : command.index("--dev") + 2]
    assert ["--tmpfs", "/run"] == command[command.index("--tmpfs") : command.index("--tmpfs") + 2]
    assert "--unshare-pid" in command
    assert "/global" not in " ".join(command)

    command_no_runtime = confinement.wrap_command(["/usr/bin/true"])
    assert ["--dev", "/dev"] == command_no_runtime[
        command_no_runtime.index("--dev") : command_no_runtime.index("--dev") + 2
    ]
    ro_root_no_rt = [
        i
        for i in range(len(command_no_runtime) - 2)
        if command_no_runtime[i] == "--ro-bind"
        and command_no_runtime[i + 1] == "/"
        and command_no_runtime[i + 2] == "/"
    ][0]
    assert command_no_runtime[ro_root_no_rt + 3 : ro_root_no_rt + 5] == ["--dev", "/dev"]


def test_resolver_projection_only_exposes_verified_target_under_private_run(tmp_path: Path):
    run_root = tmp_path / "run"
    resolver_dir = run_root / "systemd" / "resolve"
    resolver_dir.mkdir(parents=True)
    resolver_file = resolver_dir / "stub-resolv.conf"
    resolver_file.write_text("nameserver 192.0.2.53\n", encoding="utf-8")
    resolv_link = tmp_path / "resolv.conf"
    resolv_link.symlink_to(resolver_file)

    projection = AgentProcessConfinement._host_resolver_projection(str(resolv_link), str(run_root))
    assert projection == (str(resolver_file), str(resolver_file))

    mounts = AgentProcessConfinement._bubblewrap_resolver_mounts(
        "/host/run/systemd/resolve/stub-resolv.conf",
        "/run/systemd/resolve/stub-resolv.conf",
    )
    assert mounts == [
        "--dir",
        "/run/systemd",
        "--dir",
        "/run/systemd/resolve",
        "--ro-bind",
        "/host/run/systemd/resolve/stub-resolv.conf",
        "/run/systemd/resolve/stub-resolv.conf",
    ]
    assert "--bind" not in mounts
    assert "/run" not in mounts


def test_resolver_projection_preserves_lexical_run_target_for_symlinked_file(tmp_path: Path):
    run_root = tmp_path / "run"
    run_root.mkdir()
    actual_file = tmp_path / "resolver-data" / "resolv.conf"
    actual_file.parent.mkdir()
    actual_file.write_text("nameserver 192.0.2.53\n", encoding="utf-8")
    resolver_alias = run_root / "resolver-alias"
    resolver_alias.symlink_to(actual_file)
    resolv_link = tmp_path / "resolv.conf"
    resolv_link.symlink_to(resolver_alias)

    assert AgentProcessConfinement._host_resolver_projection(str(resolv_link), str(run_root)) == (
        str(actual_file),
        str(resolver_alias),
    )


def test_resolver_projection_accepts_ordinary_config_and_rejects_unsafe_targets(tmp_path: Path):
    ordinary = tmp_path / "resolv.conf"
    ordinary.write_text("nameserver 192.0.2.53\n", encoding="utf-8")
    run_root = tmp_path / "run"
    run_root.mkdir()
    assert AgentProcessConfinement._host_resolver_projection(str(ordinary), str(run_root)) is None

    directory_link = tmp_path / "directory-resolv.conf"
    directory_link.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(AgentConfinementError, match="resolver configuration"):
        AgentProcessConfinement._host_resolver_projection(
            str(directory_link), str(tmp_path / "run")
        )
    broken_link = tmp_path / "broken-resolv.conf"
    broken_link.symlink_to(tmp_path / "missing-resolv.conf")
    with pytest.raises(AgentConfinementError, match="unavailable or unverifiable"):
        AgentProcessConfinement._host_resolver_projection(str(broken_link), str(run_root))


def test_resolver_mount_rejects_runtime_collision_and_path_traversal():
    for destination in (
        "/run/minime-agent/resolver.conf",
        "/run/systemd/../minime-agent/resolver.conf",
        "/run/../etc/resolv.conf",
    ):
        with pytest.raises(AgentConfinementError, match="unsafe|escaped"):
            AgentProcessConfinement._bubblewrap_resolver_mounts(
                "/run/systemd/resolve/stub-resolv.conf", destination
            )


def test_runtime_session_mounts_only_resolver_file_after_private_run(tmp_path: Path, monkeypatch):
    confinement, worktree, _runtime_root = _confinement(tmp_path)
    confinement.confinement_mechanism = "bubblewrap"
    resolver = tmp_path / "stub-resolv.conf"
    resolver.write_text("nameserver 192.0.2.53\n", encoding="utf-8")
    monkeypatch.setattr(
        confinement,
        "_host_resolver_projection",
        lambda: (str(resolver), "/run/systemd/resolve/stub-resolv.conf"),
    )
    with confinement.runtime_session({}) as runtime:
        command = confinement.wrap_command(["/usr/bin/true"], runtime)

    run_tmpfs = command.index("--tmpfs")
    dns_bind = command.index("--ro-bind", run_tmpfs)
    private_runtime_bind = command.index("--bind", dns_bind)
    assert run_tmpfs < dns_bind < private_runtime_bind
    assert command[dns_bind : dns_bind + 3] == [
        "--ro-bind",
        str(resolver),
        "/run/systemd/resolve/stub-resolv.conf",
    ]
    assert "--unshare-net" not in command


@pytest.mark.skipif(
    not AgentProcessConfinement.is_host_confinement_available() or not shutil.which("getent"),
    reason="effective DNS boundary proof requires Linux, Bubblewrap, and getent",
)
def test_real_bubblewrap_private_run_projects_dns_read_only_and_resolves(
    tmp_path: Path, monkeypatch
):
    confinement, worktree, _runtime = _confinement(tmp_path)
    confinement.confinement_mechanism = "bubblewrap"
    # Use the host's actual resolver bytes at a /run-shaped test path, and an isolated /etc
    # containing the corresponding symlink. This models Ubuntu without changing host config.
    source = tmp_path / "host-run" / "systemd" / "resolve" / "stub-resolv.conf"
    source.parent.mkdir(parents=True)
    source.write_bytes(Path("/etc/resolv.conf").read_bytes())
    source.chmod(0o444)
    (source.parent / "host-only.sock").write_text("must stay hidden", encoding="utf-8")
    host_hosts = tmp_path / "host-hosts"
    host_hosts.write_bytes(Path("/etc/hosts").read_bytes())
    host_nsswitch = tmp_path / "host-nsswitch.conf"
    host_nsswitch.write_bytes(Path("/etc/nsswitch.conf").read_bytes())
    monkeypatch.setattr(
        confinement,
        "_host_resolver_projection",
        lambda: (str(source), "/run/systemd/resolve/stub-resolv.conf"),
    )

    with confinement.runtime_session({}) as runtime:
        resolver_path = "/run/systemd/resolve/stub-resolv.conf"

        def overlay_etc(command: list[str]) -> list[str]:
            mount_args = [
                "--tmpfs",
                "/etc",
                "--ro-bind",
                str(host_hosts),
                "/etc/hosts",
                "--ro-bind",
                str(host_nsswitch),
                "/etc/nsswitch.conf",
                "--symlink",
                resolver_path,
                "/etc/resolv.conf",
            ]
            command = list(command)
            insert_at = command.index("--unshare-pid")
            command[insert_at:insert_at] = mount_args
            return command

        visible = subprocess.run(
            overlay_etc(
                confinement.wrap_command(
                    [
                        "sh",
                        "-c",
                        f"test -r {resolver_path} && test ! -e /run/systemd/resolve/host-only.sock && getent hosts example.com",
                    ],
                    runtime,
                )
            ),
            cwd=worktree,
            env=runtime.environment,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        assert visible.returncode == 0, visible.stderr
        assert visible.stdout.strip()

        denied_write = subprocess.run(
            overlay_etc(
                confinement.wrap_command(["sh", "-c", f"echo unsafe > {resolver_path}"], runtime)
            ),
            cwd=worktree,
            env=runtime.environment,
            capture_output=True,
            text=True,
            check=False,
        )
        assert denied_write.returncode != 0

        hidden_socket = subprocess.run(
            confinement.wrap_command(
                ["sh", "-c", "test ! -e /run/host-service.sock && test -d /run/minime-agent"],
                runtime,
            ),
            cwd=worktree,
            env=runtime.environment,
            capture_output=True,
            text=True,
            check=False,
        )
        assert hidden_socket.returncode == 0, hidden_socket.stderr
        old_profile = [
            "bwrap",
            "--ro-bind",
            "/",
            "/",
            "--tmpfs",
            "/run",
            "--tmpfs",
            "/etc",
            "--ro-bind",
            str(host_hosts),
            "/etc/hosts",
            "--ro-bind",
            str(host_nsswitch),
            "/etc/nsswitch.conf",
            "--symlink",
            resolver_path,
            "/etc/resolv.conf",
            "--unshare-pid",
            "--chdir",
            str(worktree.resolve()),
            "sh",
            "-c",
            "test ! -e /run/systemd/resolve/stub-resolv.conf && ! getent hosts example.com",
        ]
        absent = subprocess.run(
            old_profile,
            cwd=worktree,
            env=runtime.environment,
            capture_output=True,
            text=True,
            check=False,
        )
        assert absent.returncode == 0


def test_environment_filesystem_failures_are_not_provider_failures():
    for message in (
        "Read-only file system (os error 30)",
        "failed to initialize sqlite state runtime: EROFS",
        "ENOENT: missing required path CODEX_HOME/tmp",
        "unable to create path aliases",
    ):
        parsed = ProviderOutcomeParser.parse_runner_output(
            provider="codex",
            role="implementer",
            model=None,
            exit_code=1,
            timed_out=False,
            stdout_lines=[],
            stderr_lines=[message],
        )
        assert parsed.result_class == ProviderResultClass.ENVIRONMENT_UNAVAILABLE
        outcome = OutcomeGovernanceService().classify_outcome(
            CompletionVerificationResult(is_complete=False), parsed
        )
        assert outcome == ExecutionOutcome.ENVIRONMENT_UNAVAILABLE
        decision = ContinuationEngine().decide(
            ContinuationContext(
                job_id="job",
                attempt_number=4,
                current_executor_role="codex",
                current_model_identity="codex",
                outcome=outcome,
                corrective_retries_for_current_executor=2,
                reassignment_count=2,
            )
        )
        assert decision.decision == ContinuationDecision.WAIT_EXTERNAL


def test_unknown_error_does_not_become_environment_failure():
    parsed = ProviderOutcomeParser.parse_runner_output(
        provider="codex",
        role="implementer",
        model=None,
        exit_code=1,
        timed_out=False,
        stdout_lines=[],
        stderr_lines=["UNKNOWN_ERROR: task could not be completed"],
    )
    assert parsed.result_class == ProviderResultClass.UNKNOWN_ERROR


@pytest.mark.skipif(
    not AgentProcessConfinement.is_host_confinement_available(),
    reason="long-lived lifecycle proof requires an OS confinement mechanism",
)
def test_agent_workflow_without_total_timeout_remains_alive_until_normal_exit(tmp_path: Path):
    confinement, worktree, _runtime = _confinement(tmp_path)
    result = asyncio.run(
        confinement.run_confined_async_subprocess(
            [sys.executable, "-c", "import time; time.sleep(0.15); print('complete')"],
            cwd=str(worktree),
            input_bytes=None,
            timeout_seconds=None,
            env=os.environ.copy(),
        )
    )
    assert result.returncode == 0
    assert result.timed_out is False
    assert b"complete" in result.stdout


@pytest.mark.parametrize("runner_type", [CliImplementerRunner, CliReviewerRunner])
def test_missing_kernel_confinement_is_environment_failure_before_cli_preflight(
    tmp_path: Path, monkeypatch, runner_type
):
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    monkeypatch.setattr(AgentProcessConfinement, "is_confinement_available", lambda _self: False)
    result = asyncio.run(runner_type(["codex", "exec", "-"]).run(worktree, "no inference", 1))
    assert result.environment_error is True
    assert result.preflight_error is None


@pytest.mark.skipif(
    not AgentProcessConfinement.is_host_confinement_available(),
    reason="process lifecycle cleanup requires an OS confinement mechanism",
)
def test_timeout_and_cancellation_reap_process_and_remove_private_runtime(tmp_path: Path):
    confinement, worktree, _runtime = _confinement(tmp_path)
    timed_out = asyncio.run(
        confinement.run_confined_async_subprocess(
            [sys.executable, "-c", "import time; time.sleep(10)"],
            cwd=str(worktree),
            input_bytes=None,
            timeout_seconds=0.05,
            env=os.environ.copy(),
        )
    )
    assert timed_out.timed_out is True
    assert not list(tmp_path.glob("minime-agent-state-*"))

    async def cancel_attempt():
        task = asyncio.create_task(
            confinement.run_confined_async_subprocess(
                [sys.executable, "-c", "import time; time.sleep(10)"],
                cwd=str(worktree),
                input_bytes=None,
                timeout_seconds=30,
                env=os.environ.copy(),
            )
        )
        for _ in range(100):
            if list(tmp_path.glob("minime-agent-state-*")):
                break
            await asyncio.sleep(0.01)
        assert list(tmp_path.glob("minime-agent-state-*"))
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not list(tmp_path.glob("minime-agent-state-*"))

    asyncio.run(cancel_attempt())


@pytest.mark.skipif(
    not AgentProcessConfinement.is_host_confinement_available(),
    reason="real write-denial proof requires Linux with Bubblewrap",
)
def test_real_bubblewrap_write_boundaries_and_ephemeral_cleanup(tmp_path: Path):
    confinement, worktree, runtime = _confinement(tmp_path)
    managed = tmp_path / "managed"
    other_worktree = tmp_path / "other-worktree"
    global_home = tmp_path / "global-home"
    arbitrary = tmp_path / "arbitrary-host-path"
    for directory in (managed, other_worktree, global_home):
        directory.mkdir()
    auth = tmp_path / "diagnostic-auth.json"
    auth.write_text("{}", encoding="utf-8")
    auth.chmod(0o600)
    ephemeral_root: Path | None = None
    with confinement.runtime_session({}, str(auth)) as state:
        ephemeral_root = state.host_root
        command = [
            sys.executable,
            "-c",
            "import pathlib,sys; p=pathlib.Path(sys.argv[1]); p.parent.mkdir(parents=True,exist_ok=True); p.write_text('bad')",
            str(runtime / "escape"),
        ]
        wrapped = confinement.wrap_command(command, state)
        denied = subprocess.run(
            wrapped,
            cwd=worktree,
            env=state.environment,
            capture_output=True,
            text=True,
            check=False,
        )
        assert denied.returncode != 0
        assert not (runtime / "escape").exists()
        positive = subprocess.run(
            confinement.wrap_command(
                [
                    sys.executable,
                    "-c",
                    "import os,pathlib; pathlib.Path('inside-worktree').write_text('ok'); "
                    "pathlib.Path(os.environ['CODEX_HOME'],'inside-state').write_text('ok')",
                ],
                state,
            ),
            cwd=worktree,
            env=state.environment,
            capture_output=True,
            text=True,
            check=False,
        )
        assert positive.returncode == 0, positive.stderr
        assert (worktree / "inside-worktree").read_text(encoding="utf-8") == "ok"
        assert (state.host_root / "codex" / "inside-state").read_text(encoding="utf-8") == "ok"
        denied_paths = [
            runtime / "escape-2",
            managed / "escape",
            other_worktree / "escape",
            global_home / "escape",
            arbitrary / "escape",
            auth,
            tmp_path / "host-tmp-escape",
        ]
        for denied_path in denied_paths:
            wrapped = confinement.wrap_command(
                [
                    sys.executable,
                    "-c",
                    "import pathlib,sys; pathlib.Path(sys.argv[1]).write_text('bad')",
                    str(denied_path),
                ],
                state,
            )
            denied = subprocess.run(
                wrapped,
                cwd=worktree,
                env=state.environment,
                capture_output=True,
                text=True,
                check=False,
            )
            assert denied.returncode != 0, f"write unexpectedly succeeded: {denied_path}"
            if denied_path == auth:
                assert auth.read_text(encoding="utf-8") == "{}"
            else:
                assert not denied_path.exists()
        assert stat.S_IMODE(state.host_root.stat().st_mode) == 0o700
    assert ephemeral_root is not None and not ephemeral_root.exists()
    assert not (managed / "escape").exists()
    assert not (other_worktree / "escape").exists()
    assert not (global_home / "escape").exists()
    assert not (arbitrary / "escape").exists()
    assert auth.read_text(encoding="utf-8") == "{}"


@pytest.mark.skipif(
    not AgentProcessConfinement.is_host_confinement_available() or not shutil.which("codex"),
    reason="initialize-only Codex app-server smoke requires Linux, Bubblewrap, and Codex CLI",
)
def test_real_codex_app_server_initialize_only_under_bubblewrap(tmp_path: Path):
    worktree = tmp_path / "worktree"
    runtime = tmp_path / "runtime"
    worktree.mkdir()
    runtime.mkdir()
    confinement = AgentProcessConfinement(
        str(worktree), runtime_root=str(runtime), private_state_parent=str(tmp_path)
    )
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "clientInfo": {"name": "mini-me-diagnostic", "version": "1"},
            "capabilities": {},
        },
    }

    async def initialize_only() -> tuple[bytes, bytes]:
        with confinement.runtime_session(os.environ.copy()) as runtime_state:
            process = await asyncio.create_subprocess_exec(
                *confinement.wrap_command(
                    ["codex", "app-server", "--listen", "stdio://"],
                    runtime_state,
                    unshare_network=True,
                ),
                cwd=str(worktree),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=runtime_state.environment,
                start_new_session=True,
            )
            assert process.stdin is not None and process.stdout is not None
            process.stdin.write((json.dumps(request) + "\n").encode())
            await process.stdin.drain()
            try:
                response = await asyncio.wait_for(process.stdout.readline(), timeout=20)
                returncode = process.returncode
                if returncode is None:
                    await confinement._terminate_process_group(process)
                stderr = await process.stderr.read() if process.stderr is not None else b""
                return response + f"\nreturncode={returncode}".encode(), stderr
            finally:
                if process.returncode is None:
                    await confinement._terminate_process_group(process)

    response, stderr = asyncio.run(initialize_only())
    output = response.decode(errors="replace") + stderr.decode(errors="replace")
    assert "EROFS" not in output and "read-only file system" not in output.lower()
    assert response and b'"id":1' in response.replace(b" ", b"")


def test_deterministic_wrap_command_dev_null_flag_injection(tmp_path: Path):
    """Task 1.2: Deterministic verification that Bubblewrap command includes --dev /dev directly after root mount."""
    confinement, _worktree, _runtime = _confinement(tmp_path)
    confinement.confinement_mechanism = "bubblewrap"

    cmd_list = confinement.wrap_command(["pytest", "-q"])
    ro_idx = [
        i
        for i in range(len(cmd_list) - 2)
        if cmd_list[i] == "--ro-bind" and cmd_list[i + 1] == "/" and cmd_list[i + 2] == "/"
    ][0]
    assert cmd_list[ro_idx + 3 : ro_idx + 5] == ["--dev", "/dev"]

    cmd_str = confinement.wrap_command("pytest -q")
    ro_idx_str = [
        i
        for i in range(len(cmd_str) - 2)
        if cmd_str[i] == "--ro-bind" and cmd_str[i + 1] == "/" and cmd_str[i + 2] == "/"
    ][0]
    assert cmd_str[ro_idx_str + 3 : ro_idx_str + 5] == ["--dev", "/dev"]


@pytest.mark.skipif(
    not AgentProcessConfinement.is_host_confinement_available(),
    reason="real Bubblewrap device access proof requires Linux with Bubblewrap",
)
def test_real_bubblewrap_dev_null_access(tmp_path: Path):
    """Task 1.3: Deterministic execution test verifying subprocesses can open /dev/null without Errno 13."""
    confinement, worktree, _runtime = _confinement(tmp_path)
    code = (
        "import sys\n"
        "with open('/dev/null', 'rb') as f:\n"
        "    f.read()\n"
        "with open('/dev/null', 'wb') as f:\n"
        "    f.write(b'ok')\n"
        "sys.stdout.write('DEV_NULL_SUCCESS')\n"
    )
    cmd = [sys.executable, "-c", code]
    wrapped = confinement.wrap_command(cmd)
    res = subprocess.run(
        wrapped,
        cwd=worktree,
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 0, f"Process failed: {res.stderr}"
    assert "DEV_NULL_SUCCESS" in res.stdout
    assert "PermissionError" not in res.stderr
    assert "Errno 13" not in res.stderr


@pytest.mark.skipif(
    not AgentProcessConfinement.is_host_confinement_available(),
    reason="real ChecksRunner execution under Bubblewrap requires Linux with Bubblewrap",
)
def test_real_bubblewrap_checks_runner_execution(tmp_path: Path):
    """Task 1.4: Real Linux Bubblewrap integration test executing ChecksRunner on a sample test suite."""
    from minime.services.checks_runner import ChecksRunner

    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir()
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    sample_test = worktree / "test_sample.py"
    sample_test.write_text(
        "def test_sample():\n"
        "    with open('/dev/null', 'wb') as f:\n"
        "        f.write(b'sample')\n"
        "    assert 1 + 1 == 2\n",
        encoding="utf-8",
    )

    runner = ChecksRunner(runtime_root=str(runtime_root))
    result = asyncio.run(
        runner.run(
            job_id="job-test-checks-bwrap",
            checks=[
                {
                    "name": "sample_suite",
                    "command": f"{sys.executable} -m pytest {sample_test.name} -q",
                }
            ],
            worktree_path=worktree,
        )
    )
    assert len(result.results) == 1
    assert result.results[0].exit_code == 0, f"Checks failed: {result.results[0].output_snippet}"
    assert "PermissionError" not in result.results[0].output_snippet
    assert "Errno 13" not in result.results[0].output_snippet
    assert "passed" in result.results[0].output_snippet.lower()


@pytest.mark.skipif(
    not AgentProcessConfinement.is_host_confinement_available(),
    reason="real write-denial proof requires Linux with Bubblewrap",
)
def test_real_bubblewrap_negative_confinement_system_paths(tmp_path: Path):
    """Task 1.5: Real negative confinement test under Bubblewrap asserting writes outside worktree fail."""
    confinement, worktree, _runtime = _confinement(tmp_path)
    for system_target in [
        "/etc/minime_escape_probe",
        "/usr/minime_escape_probe",
        "/opt/minime_escape_probe",
    ]:
        code = (
            f"import sys\n"
            f"try:\n"
            f"    with open('{system_target}', 'w') as f:\n"
            f"        f.write('escape')\n"
            f"    sys.exit(0)\n"
            f"except OSError:\n"
            f"    sys.exit(42)\n"
        )
        cmd = [sys.executable, "-c", code]
        wrapped = confinement.wrap_command(cmd)
        res = subprocess.run(
            wrapped,
            cwd=worktree,
            capture_output=True,
            text=True,
            check=False,
        )
        assert res.returncode == 42, f"System path write unexpectedly succeeded to {system_target}"
