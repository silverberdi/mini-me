"""Focused security and boundary tests for the GitHub App runtime authority."""

import base64
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from conftest import create_isolated_openspec_change
from minime.adapters import github as github_module
from minime.adapters.github import (
    GitHubAdapter,
    GitHubAppAuth,
    GitHubAuthorizationError,
    GitHubRemoteError,
    _CachedInstallationToken,
)
from minime.domain.enums import PullRequestLookupState
from minime.domain.models import Project, ProjectBinding
from minime.services.readiness_service import ReadinessService


def _key_file(tmp_path: Path) -> tuple[Path, object]:
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    path = tmp_path / "app.pem"
    path.write_bytes(
        private.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return path, private.public_key()


def test_app_jwt_claims_and_installation_token_cache(tmp_path):
    path, public_key = _key_file(tmp_path)
    now = [1_700_000_000.0]
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        token = jwt.decode(
            request.headers["Authorization"][7:],
            public_key,
            algorithms=["RS256"],
            options={"verify_exp": False},
        )
        assert token == {"iat": 1_699_999_940, "exp": 1_700_000_540, "iss": "42"}
        return httpx.Response(
            201, json={"token": "installation-secret", "expires_at": "2023-11-14T23:00:00Z"}
        )

    auth = GitHubAppAuth(
        "42",
        "99",
        path,
        client=httpx.Client(
            transport=httpx.MockTransport(handler), base_url="https://api.github.com"
        ),
        now=lambda: now[0],
    )
    assert auth.get_installation_token() == "installation-secret"
    assert auth.get_installation_token() == "installation-secret"
    assert len(calls) == 1


def test_app_token_refreshes_inside_sixty_seconds(tmp_path):
    path, _ = _key_file(tmp_path)
    now = [1_700_000_000.0]
    counter = {"calls": 0}

    def handler(_: httpx.Request) -> httpx.Response:
        counter["calls"] += 1
        return httpx.Response(
            201, json={"token": f"token-{counter['calls']}", "expires_at": "2023-11-14T22:14:30Z"}
        )

    auth = GitHubAppAuth(
        "42",
        "99",
        path,
        client=httpx.Client(
            transport=httpx.MockTransport(handler), base_url="https://api.github.com"
        ),
        now=lambda: now[0],
    )
    auth._cached = _CachedInstallationToken("old", datetime.fromtimestamp(now[0] + 59, tz=UTC))
    assert auth.get_installation_token() == "token-1"
    assert counter["calls"] == 1


def test_missing_app_credentials_fail_closed_even_with_legacy_token(monkeypatch):
    monkeypatch.delenv("MINIME_GITHUB_APP_ID", raising=False)
    monkeypatch.delenv("MINIME_GITHUB_INSTALLATION_ID", raising=False)
    monkeypatch.delenv("MINIME_GITHUB_PRIVATE_KEY_PATH", raising=False)
    with pytest.raises(GitHubAuthorizationError):
        GitHubAdapter(token="personal-gh-token").verify_repository("owner/repo")


def test_rest_pr_states_and_auth_header():
    responses = [
        [],
        [
            {
                "number": 7,
                "html_url": "https://github.com/o/r/pull/7",
                "head": {"sha": "abc", "ref": "feature"},
                "base": {"ref": "main"},
            }
        ],
        [{"number": 1}, {"number": 2}],
    ]
    index = {"value": 0}

    class Auth:
        mode = "github_app_installation"
        _cached = _CachedInstallationToken(
            "installation-secret", datetime.now(UTC) + timedelta(hours=1)
        )
        client = httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json=responses[min(index["value"], 2)])
            ),
            base_url="https://api.github.com",
        )

        def get_installation_token(self):
            return "installation-secret"

    adapter = GitHubAdapter(auth=Auth())
    assert adapter.get_pull_request("o/r", "feature").state == PullRequestLookupState.NOT_FOUND
    index["value"] += 1
    result = adapter.get_pull_request("o/r", "feature")
    assert result.state == PullRequestLookupState.FOUND_EXACT
    assert result.pull_request["head_sha"] == "abc"
    index["value"] += 1
    assert adapter.get_pull_request("o/r", "feature").state == PullRequestLookupState.AMBIGUOUS


def test_issue_validation_distinguishes_not_found_and_unobservable():
    class Auth:
        _cached = None
        client = httpx.Client(
            transport=httpx.MockTransport(lambda request: httpx.Response(404)),
            base_url="https://api.github.com",
        )

        def get_installation_token(self):
            return "token"

    ok, reason = GitHubAdapter(auth=Auth()).validate_issue_binding("o/r", 12)
    assert not ok and "does not exist" in reason

    class Outage(Auth):
        client = httpx.Client(
            transport=httpx.MockTransport(
                lambda request: (_ for _ in ()).throw(httpx.ConnectError("down"))
            ),
            base_url="https://api.github.com",
        )

    with pytest.raises(GitHubRemoteError):
        GitHubAdapter(auth=Outage()).validate_issue_binding("o/r", 12)


def _issue_auth(payload, status=200):
    class Auth:
        _cached = None
        client = httpx.Client(
            transport=httpx.MockTransport(lambda request: httpx.Response(status, json=payload)),
            base_url="https://api.github.com",
        )

        def get_installation_token(self):
            return "token"

    return Auth()


def test_issue_validation_accepts_standard_repository_url_fixture():
    payload = {
        "number": 12,
        "title": "Issue",
        "repository_url": "https://api.github.com/repos/o/r",
        "url": "https://api.github.com/repos/o/r/issues/12",
    }
    assert GitHubAdapter(auth=_issue_auth(payload)).validate_issue_binding("o/r", 12) == (
        True,
        None,
    )


def test_issue_validation_rejects_repository_mismatch_and_malformed_fixture():
    mismatch = {"number": 12, "repository_url": "https://api.github.com/repos/other/repo"}
    ok, reason = GitHubAdapter(auth=_issue_auth(mismatch)).validate_issue_binding("o/r", 12)
    assert not ok and "Repository mismatch" in reason

    malformed = {
        "number": 12,
        "title": "Issue",
        "url": "https://api.github.com/repos/o/r/issues/12",
    }
    ok, reason = GitHubAdapter(auth=_issue_auth(malformed)).validate_issue_binding("o/r", 12)
    assert not ok and "invalid" in reason.lower()


def test_git_timeout_and_generic_failures_do_not_expose_command_or_chain(monkeypatch, tmp_path):
    token = "installation-secret"
    encoded = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    command = ["git", "-c", f"http.extraHeader=Authorization: Basic {encoded}", "push"]

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(command, 30)

    monkeypatch.setattr(github_module.subprocess, "run", timeout)
    with pytest.raises(RuntimeError) as caught:
        github_module.GitHubAdapter._run_git(
            command, cwd=tmp_path, timeout=1, secrets=[token, encoded, f"Basic {encoded}"]
        )
    assert str(caught.value) == "Git command timed out."
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    assert not any(
        value in repr(caught.value) for value in (token, encoded, f"Basic {encoded}", command[-2])
    )

    def generic(*args, **kwargs):
        raise RuntimeError(f"failed command={command!r}")

    monkeypatch.setattr(github_module.subprocess, "run", generic)
    with pytest.raises(RuntimeError) as caught:
        github_module.GitHubAdapter._run_git(
            command, cwd=tmp_path, timeout=1, secrets=[token, encoded, f"Basic {encoded}"]
        )
    assert str(caught.value) == "Git command failed before completion."
    assert caught.value.__cause__ is None and caught.value.__context__ is None


def test_git_nonzero_stderr_redacts_all_authorization_forms(tmp_path):
    token = "installation-secret"
    encoded = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    basic = f"Basic {encoded}"
    header = f"http.extraHeader=Authorization: {basic}"

    class Auth:
        _cached = _CachedInstallationToken(token, datetime.now(UTC) + timedelta(hours=1))

        def get_installation_token(self):
            return token

    adapter = GitHubAdapter(auth=Auth())
    (tmp_path / ".git").mkdir()
    calls = [
        subprocess.CompletedProcess([], 0, stdout="https://github.com/o/r.git\n", stderr=""),
        subprocess.CompletedProcess([], 0, stdout="abc\n", stderr=""),
        subprocess.CompletedProcess([], 1, stdout="", stderr=f"fatal: {header} {token} {encoded}"),
    ]
    adapter._run_git = lambda *args, **kwargs: calls.pop(0)
    with pytest.raises(RuntimeError) as caught:
        adapter.push_branch(str(tmp_path), "origin", "feature", "abc")
    message = str(caught.value)
    assert all(value not in message for value in (token, encoded, basic, header))


class _FreshGitAuth:
    def __init__(self, token: str):
        self.token = token
        self.calls = 0
        self._cached = None

    def get_installation_token(self):
        self.calls += 1
        return self.token


def _assert_secret_free(error, values):
    surfaces = [
        str(error),
        repr(error),
        repr(error.args),
        repr(error.__cause__),
        repr(error.__context__),
    ]
    assert all(value not in "\n".join(surfaces) for value in values)
    assert error.__cause__ is None and error.__context__ is None


def test_push_first_use_builds_redaction_set_from_fresh_token(tmp_path):
    token = "fresh-installation-token"
    encoded = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    basic = f"Basic {encoded}"
    header = f"http.extraHeader=Authorization: {basic}"
    auth = _FreshGitAuth(token)
    adapter = GitHubAdapter(auth=auth)
    (tmp_path / ".git").mkdir()
    calls = [
        subprocess.CompletedProcess([], 0, stdout="https://github.com/o/r.git\n", stderr=""),
        subprocess.CompletedProcess([], 0, stdout="abc\n", stderr=""),
        subprocess.CompletedProcess([], 1, stdout="", stderr=f"fatal: {header} {token} {encoded}"),
    ]
    adapter._run_git = lambda *args, **kwargs: calls.pop(0)

    with pytest.raises(RuntimeError) as caught:
        adapter.push_branch(str(tmp_path), "origin", "feature", "abc")
    assert auth.calls == 1
    _assert_secret_free(caught.value, (token, encoded, basic, header))


def test_remote_head_first_use_builds_redaction_set_from_fresh_token(tmp_path):
    token = "fresh-remote-token"
    encoded = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    basic = f"Basic {encoded}"
    header = f"http.extraHeader=Authorization: {basic}"
    auth = _FreshGitAuth(token)
    adapter = GitHubAdapter(auth=auth)
    (tmp_path / ".git").mkdir()
    calls = [
        subprocess.CompletedProcess([], 0, stdout=f"{tmp_path}\n", stderr=""),
        subprocess.CompletedProcess([], 0, stdout="https://github.com/o/r.git\n", stderr=""),
        subprocess.CompletedProcess([], 1, stdout="", stderr=f"fatal: {header} {token} {encoded}"),
    ]
    adapter._run_git = lambda *args, **kwargs: calls.pop(0)

    with pytest.raises(RuntimeError) as caught:
        adapter.get_remote_branch_head(str(tmp_path), "feature")
    assert auth.calls == 1
    _assert_secret_free(caught.value, (token, encoded, basic, header))


class _ReadinessGitHubStub:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error

    def validate_issue_binding(self, expected_repository, issue_number, github_repository=None):
        if self.error:
            raise self.error
        return self.result


def _readiness_case(in_memory_uow, tmp_path, github):
    create_isolated_openspec_change(tmp_path, "audit-readiness")
    in_memory_uow.projects.save(
        Project(
            project_id="mini-me",
            display_name="mini me",
            repository="o/r",
            base_branch="main",
            openspec_path="openspec",
            implementer="codex",
            reviewer="antigravity",
        )
    )
    in_memory_uow.bindings.save(
        ProjectBinding(
            project_id="mini-me",
            repository="o/r",
            github_issue_number=12,
            openspec_change_name="audit-readiness",
        )
    )
    return ReadinessService(in_memory_uow, github_adapter=github).evaluate_change_readiness(
        "mini-me", "audit-readiness", str(tmp_path)
    )


def test_readiness_fails_closed_when_issue_validation_returns_false(in_memory_uow, tmp_path):
    result = _readiness_case(
        in_memory_uow,
        tmp_path,
        _ReadinessGitHubStub(result=(False, "Issue repository mismatch")),
    )
    assert not result.is_ready
    assert "Issue repository mismatch" in result.unmet_reasons


@pytest.mark.parametrize(
    "error, expected",
    [
        (
            GitHubRemoteError("GitHub Issue validation is unobservable."),
            "Transient GitHub unobservability",
        ),
        (
            GitHubAuthorizationError("GitHub App is unauthorized."),
            "GitHub App authorization failure",
        ),
    ],
)
def test_readiness_fails_closed_for_github_boundary_errors(
    in_memory_uow, tmp_path, error, expected
):
    result = _readiness_case(in_memory_uow, tmp_path, _ReadinessGitHubStub(error=error))
    assert not result.is_ready
    assert any(expected in reason for reason in result.unmet_reasons)
