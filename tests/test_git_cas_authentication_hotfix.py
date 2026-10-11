"""Targeted unit and security tests for Git CAS authentication, secret redaction, and publication recovery."""

import base64
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from minime.adapters.github import GitHubAdapter, _GitAuthBundle
from minime.domain.enums import (
    IntakeWorkspaceCreationState,
    IntakeWorkspacePublicationState,
    ReadinessState,
)
from minime.domain.models import (
    IntakeWorkspaceOwnership,
    Project,
)
from minime.services.intake_service import IntakeService
from minime.services.readiness_service import ReadinessService


def test_git_auth_bundle_uses_environment_config_not_cmdline_args():
    class DummyAuth:
        def get_installation_token(self):
            return "secret-token-123"

    adapter = GitHubAdapter(auth=DummyAuth())
    auth_bundle = adapter._git_auth_bundle("https://github.com/silverberdi/mini-me.git")

    # Command line args must be empty to avoid exposing secrets in ps aux / /proc/$PID/cmdline
    assert auth_bundle.args == ()

    # Secrets must be stored in environment variables (GIT_CONFIG_COUNT, GIT_CONFIG_KEY_<n>, GIT_CONFIG_VALUE_<n>)
    assert auth_bundle.env.get("GIT_CONFIG_COUNT") == "2"
    assert auth_bundle.env.get("GIT_CONFIG_KEY_0") == "credential.helper"
    assert auth_bundle.env.get("GIT_CONFIG_VALUE_0") == ""
    assert auth_bundle.env.get("GIT_CONFIG_KEY_1") == "http.extraHeader"
    assert "Authorization: Basic" in auth_bundle.env.get("GIT_CONFIG_VALUE_1", "")
    assert "secret-token-123" not in str(auth_bundle.args)


def test_git_run_git_sets_non_interactive_prompt_and_injects_auth_env(tmp_path):
    captured_env = {}

    def mock_run(args, cwd, capture_output, text, timeout, env):
        nonlocal captured_env
        captured_env = env
        return subprocess.CompletedProcess(args, 0, stdout="success\n", stderr="")

    with patch("minime.adapters.github.subprocess.run", side_effect=mock_run):
        auth_env = {
            "GIT_CONFIG_COUNT": "2",
            "GIT_CONFIG_KEY_1": "http.extraHeader",
            "GIT_CONFIG_VALUE_1": "Authorization: Basic secret",
        }
        res = GitHubAdapter._run_git(
            ["git", "ls-remote"], cwd=tmp_path, timeout=5, auth_env=auth_env
        )
        assert res.returncode == 0
        assert captured_env.get("GIT_TERMINAL_PROMPT") == "0"
        assert captured_env.get("GIT_CONFIG_VALUE_1") == "Authorization: Basic secret"


def test_intake_observe_remote_ref_authenticated_and_redacts_errors(tmp_path):
    token = "volatile-app-token"
    encoded = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    basic = f"Basic {encoded}"

    class FakeAuth:
        def get_installation_token(self):
            return token

    adapter = GitHubAdapter(auth=FakeAuth())
    uow = MagicMock()
    service = IntakeService(uow=uow, github_adapter=adapter)

    # 1. Success observation
    def mock_run_ls_remote(cmd, *args, **kwargs):
        env = kwargs.get("env")
        if cmd[1] == "remote":
            return subprocess.CompletedProcess(cmd, 0, stdout="https://github.com/silverberdi/mini-me.git\n", stderr="")
        if cmd[1] == "ls-remote":
            assert env is not None
            assert env.get("GIT_TERMINAL_PROMPT") == "0"
            assert env.get("GIT_CONFIG_KEY_1") == "http.extraHeader"
            return subprocess.CompletedProcess(cmd, 0, stdout="abc123head\trefs/minime/intake/change-1\n", stderr="")
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="failed")

    with patch("minime.services.intake_service.subprocess.run", side_effect=mock_run_ls_remote):
        sha, ok = service._observe_remote_ref(str(tmp_path), "origin", "refs/minime/intake/change-1")
        assert ok is True
        assert sha == "abc123head"

    # 2. Failure with secret redaction
    def mock_run_ls_remote_fail(cmd, *args, **kwargs):
        if cmd[1] == "remote":
            return subprocess.CompletedProcess(cmd, 0, stdout="https://github.com/silverberdi/mini-me.git\n", stderr="")
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr=f"fatal: authentication failed for {token} {basic}")

    with patch("minime.services.intake_service.subprocess.run", side_effect=mock_run_ls_remote_fail):
        with patch("minime.services.intake_service.logger.warning") as mock_warn:
            sha, ok = service._observe_remote_ref(str(tmp_path), "origin", "refs/minime/intake/change-1")
            assert ok is False
            assert sha is None
            # Verify secret was redacted in warning log
            mock_warn.assert_called()
            log_msg = mock_warn.call_args[0][2]
            assert token not in log_msg
            assert basic not in log_msg


def test_publish_intake_artifacts_cas_creates_initial_ref(tmp_path):
    uow = MagicMock()
    uow.project_managed_repository_bindings.get_by_project_id.return_value = MagicMock(
        remote_name="origin", managed_repository_root=str(tmp_path)
    )
    adapter = MagicMock()
    adapter._git_auth_bundle.return_value = _GitAuthBundle((), ("secret-1",), {"GIT_CONFIG_COUNT": "1"})
    service = IntakeService(uow=uow, github_adapter=adapter)

    project = Project(
        project_id="mini-me",
        display_name="mini me",
        repository="silverberdi/mini-me",
        base_branch="main",
        openspec_path="openspec",
    )
    ownership = IntakeWorkspaceOwnership(
        workspace_id="ws-123",
        project_id="mini-me",
        saga_id="saga-123",
        item_key="test-change",
        change_name="test-change",
        canonical_workspace_path=str(tmp_path),
        canonical_repository_identity="silverberdi/mini-me",
        base_sha="base-sha",
        head_sha="head-sha-123",
        creation_state=IntakeWorkspaceCreationState.ACTIVE,
        publication_state=IntakeWorkspacePublicationState.UNPUBLISHED,
    )

    observations = [
        (None, True),  # Pre-push observation: ref is absent
        ("head-sha-123", True),  # Post-push observation: ref created at head-sha-123
    ]

    service._observe_remote_ref = MagicMock(side_effect=lambda root, remote, ref: observations.pop(0))

    run_calls = []

    def mock_run(cmd, *args, **kwargs):
        run_calls.append((cmd, kwargs.get("env")))
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    with patch("minime.services.intake_service.subprocess.run", side_effect=mock_run):
        published_sha = service._publish_intake_artifacts_cas(ownership, project)
        assert published_sha == "head-sha-123"
        assert ownership.publication_state == IntakeWorkspacePublicationState.PUBLISHED
        assert ownership.published_sha == "head-sha-123"
        assert len(run_calls) >= 1
        # Confirm git push command line contained NO secrets in argv
        push_cmd = [c[0] for c in run_calls if "push" in c[0]][0]
        assert "secret-1" not in " ".join([str(arg) for arg in push_cmd])


def test_publish_reuses_existing_publication_when_sha_matches(tmp_path):
    uow = MagicMock()
    adapter = MagicMock()
    adapter._git_auth_bundle.return_value = _GitAuthBundle((), (), {})
    service = IntakeService(uow=uow, github_adapter=adapter)

    project = Project(project_id="mini-me", display_name="mini me", repository="silverberdi/mini-me")
    ownership = IntakeWorkspaceOwnership(
        workspace_id="ws-123",
        project_id="mini-me",
        saga_id="saga-123",
        item_key="test-change",
        change_name="test-change",
        canonical_workspace_path=str(tmp_path),
        canonical_repository_identity="silverberdi/mini-me",
        base_sha="base-sha",
        head_sha="head-sha-123",
        published_sha="head-sha-123",
        publication_state=IntakeWorkspacePublicationState.PUBLISHED,
    )

    # Remote ref observation already matches head-sha-123
    service._observe_remote_ref = MagicMock(return_value=("head-sha-123", True))

    with patch("minime.services.intake_service.subprocess.run") as mock_run:
        published_sha = service._publish_intake_artifacts_cas(ownership, project)
        assert published_sha == "head-sha-123"
        # Push was not needed and subprocess.run for push was never invoked
        push_calls = [call for call in mock_run.call_args_list if "push" in call[0][0]]
        assert len(push_calls) == 0


def test_publish_raises_cas_mismatch_on_conflicting_remote_sha(tmp_path):
    uow = MagicMock()
    adapter = MagicMock()
    adapter._git_auth_bundle.return_value = _GitAuthBundle((), (), {})
    service = IntakeService(uow=uow, github_adapter=adapter)

    project = Project(project_id="mini-me", display_name="mini me", repository="silverberdi/mini-me")
    ownership = IntakeWorkspaceOwnership(
        workspace_id="ws-123",
        project_id="mini-me",
        saga_id="saga-123",
        item_key="test-change",
        change_name="test-change",
        canonical_workspace_path=str(tmp_path),
        canonical_repository_identity="silverberdi/mini-me",
        base_sha="base-sha",
        head_sha="head-sha-123",
        published_sha=None,  # Expects remote ref to be absent
    )

    # Remote ref exists at conflicting SHA
    service._observe_remote_ref = MagicMock(return_value=("conflicting-sha-999", True))

    with pytest.raises(RuntimeError) as exc_info:
        service._publish_intake_artifacts_cas(ownership, project)

    assert "REF_CAS_MISMATCH" in str(exc_info.value)
    assert ownership.publication_state == IntakeWorkspacePublicationState.PUBLICATION_FAILED


def test_publish_transport_failure_does_not_mutate_blindly(tmp_path):
    uow = MagicMock()
    adapter = MagicMock()
    adapter._git_auth_bundle.return_value = _GitAuthBundle((), (), {})
    service = IntakeService(uow=uow, github_adapter=adapter)

    project = Project(project_id="mini-me", display_name="mini me", repository="silverberdi/mini-me")
    ownership = IntakeWorkspaceOwnership(
        workspace_id="ws-123",
        project_id="mini-me",
        saga_id="saga-123",
        item_key="test-change",
        change_name="test-change",
        canonical_workspace_path=str(tmp_path),
        canonical_repository_identity="silverberdi/mini-me",
        base_sha="base-sha",
        head_sha="head-sha-123",
    )

    # Remote observation unobservable (ok=False)
    service._observe_remote_ref = MagicMock(return_value=(None, False))

    with pytest.raises(RuntimeError) as exc_info:
        service._publish_intake_artifacts_cas(ownership, project)

    assert "PUBLICATION_TRANSPORT_FAILURE" in str(exc_info.value)
    assert ownership.publication_state == IntakeWorkspacePublicationState.PUBLICATION_FAILED


def test_auth_failure_leaves_readiness_in_safe_not_ready_state(tmp_path):
    uow = MagicMock()
    adapter = MagicMock()
    adapter.validate_issue_binding.return_value = MagicMock(is_success=True)

    readiness_service = ReadinessService(uow, github_adapter=adapter)

    # Mock observation returning unobservable / transport error
    readiness_service._observe_published_ref = MagicMock(return_value=(None, False))

    res = readiness_service.evaluate_change_readiness(
        project_id="mini-me",
        change_name="test-change",
        project_root=str(tmp_path),
        require_published_ref=True,
    )

    assert res.is_ready is False
    assert res.status == ReadinessState.NOT_READY
    assert any("published ref" in r.lower() or "unobservable" in r.lower() for r in res.unmet_reasons)


def test_ownership_contract_and_workspace_isolation_preserved(tmp_path):
    ownership = IntakeWorkspaceOwnership(
        workspace_id="ws-999",
        project_id="mini-me",
        saga_id="saga-123",
        item_key="isolated-item",
        change_name="isolated-item",
        canonical_workspace_path=str(tmp_path / "isolated-ws"),
        canonical_repository_identity="silverberdi/mini-me",
        base_sha="ea5d9a9cdea7d1ae54c3e8fdcceefaa2b017ebc8",
        head_sha="d7c54f672ec2f982a80b86c82d478cfd49a32b18",
        creation_state=IntakeWorkspaceCreationState.ACTIVE,
        publication_state=IntakeWorkspacePublicationState.UNPUBLISHED,
    )

    assert ownership.canonical_workspace_path == str(tmp_path / "isolated-ws")
    assert ownership.base_sha == "ea5d9a9cdea7d1ae54c3e8fdcceefaa2b017ebc8"
    assert ownership.head_sha == "d7c54f672ec2f982a80b86c82d478cfd49a32b18"
    assert ownership.creation_state == IntakeWorkspaceCreationState.ACTIVE
