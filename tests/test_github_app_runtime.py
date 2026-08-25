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

from minime.adapters import github as github_module
from minime.adapters.github import (
    GitHubAdapter,
    GitHubAppAuth,
    GitHubAuthorizationError,
    GitHubRemoteError,
    _CachedInstallationToken,
)
from minime.domain.enums import PullRequestLookupState


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
        token = jwt.decode(request.headers["Authorization"][7:], public_key, algorithms=["RS256"], options={"verify_exp": False})
        assert token == {"iat": 1_699_999_940, "exp": 1_700_000_540, "iss": "42"}
        return httpx.Response(201, json={"token": "installation-secret", "expires_at": "2023-11-14T23:00:00Z"})

    auth = GitHubAppAuth("42", "99", path, client=httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api.github.com"), now=lambda: now[0])
    assert auth.get_installation_token() == "installation-secret"
    assert auth.get_installation_token() == "installation-secret"
    assert len(calls) == 1


def test_app_token_refreshes_inside_sixty_seconds(tmp_path):
    path, _ = _key_file(tmp_path)
    now = [1_700_000_000.0]
    counter = {"calls": 0}

    def handler(_: httpx.Request) -> httpx.Response:
        counter["calls"] += 1
        return httpx.Response(201, json={"token": f"token-{counter['calls']}", "expires_at": "2023-11-14T22:14:30Z"})

    auth = GitHubAppAuth("42", "99", path, client=httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api.github.com"), now=lambda: now[0])
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
    responses = [[ ], [{"number": 7, "html_url": "https://github.com/o/r/pull/7", "head": {"sha": "abc", "ref": "feature"}, "base": {"ref": "main"}}], [{"number": 1}, {"number": 2}]]
    index = {"value": 0}

    class Auth:
        mode = "github_app_installation"
        _cached = _CachedInstallationToken("installation-secret", datetime.now(UTC) + timedelta(hours=1))
        client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=responses[min(index["value"], 2)])), base_url="https://api.github.com")

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
        client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(404)), base_url="https://api.github.com")

        def get_installation_token(self):
            return "token"

    ok, reason = GitHubAdapter(auth=Auth()).validate_issue_binding("o/r", 12)
    assert not ok and "does not exist" in reason

    class Outage(Auth):
        client = httpx.Client(transport=httpx.MockTransport(lambda request: (_ for _ in ()).throw(httpx.ConnectError("down"))), base_url="https://api.github.com")

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
    assert GitHubAdapter(auth=_issue_auth(payload)).validate_issue_binding("o/r", 12) == (True, None)


def test_issue_validation_rejects_repository_mismatch_and_malformed_fixture():
    mismatch = {"number": 12, "repository_url": "https://api.github.com/repos/other/repo"}
    ok, reason = GitHubAdapter(auth=_issue_auth(mismatch)).validate_issue_binding("o/r", 12)
    assert not ok and "Repository mismatch" in reason

    malformed = {"number": 12, "title": "Issue", "url": "https://api.github.com/repos/o/r/issues/12"}
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
        github_module.GitHubAdapter._run_git(command, cwd=tmp_path, timeout=1, secrets=[token, encoded, f"Basic {encoded}"])
    assert str(caught.value) == "Git command timed out."
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    assert not any(value in repr(caught.value) for value in (token, encoded, f"Basic {encoded}", command[-2]))

    def generic(*args, **kwargs):
        raise RuntimeError(f"failed command={command!r}")

    monkeypatch.setattr(github_module.subprocess, "run", generic)
    with pytest.raises(RuntimeError) as caught:
        github_module.GitHubAdapter._run_git(command, cwd=tmp_path, timeout=1, secrets=[token, encoded, f"Basic {encoded}"])
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
