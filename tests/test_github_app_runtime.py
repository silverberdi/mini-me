"""Focused security, boundary, and fail-closed tests for the GitHub App runtime authority."""

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
    _CachedInstallationToken,
)
from minime.domain.enums import ExternalOutcome, ExternalReasonCode, RetrySafety
from minime.domain.models import ExternalActionResult, Project, ProjectBinding
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
    res = GitHubAdapter(token="personal-gh-token").verify_repository("owner/repo")
    assert res.is_failure
    assert res.reason_code == ExternalReasonCode.AUTH_REQUIRED


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

    res1 = adapter.get_pull_request("o/r", "feature")
    assert res1.outcome == ExternalOutcome.FAILURE
    assert res1.reason_code == ExternalReasonCode.NOT_FOUND

    index["value"] += 1
    res2 = adapter.get_pull_request("o/r", "feature")
    assert res2.outcome == ExternalOutcome.SUCCESS
    assert res2.reason_code == ExternalReasonCode.EXECUTION_SUCCESS
    assert res2.data["head_sha"] == "abc"

    index["value"] += 1
    res3 = adapter.get_pull_request("o/r", "feature")
    assert res3.outcome == ExternalOutcome.AMBIGUOUS
    assert res3.reason_code == ExternalReasonCode.CONFLICT


def test_issue_validation_distinguishes_not_found_and_unobservable():
    class Auth:
        _cached = None
        client = httpx.Client(
            transport=httpx.MockTransport(lambda request: httpx.Response(404)),
            base_url="https://api.github.com",
        )

        def get_installation_token(self):
            return "token"

    res = GitHubAdapter(auth=Auth()).validate_issue_binding("o/r", 12)
    assert res.outcome == ExternalOutcome.FAILURE
    assert res.reason_code == ExternalReasonCode.NOT_FOUND

    class Outage(Auth):
        client = httpx.Client(
            transport=httpx.MockTransport(
                lambda request: (_ for _ in ()).throw(httpx.ConnectError("down"))
            ),
            base_url="https://api.github.com",
        )

    res_outage = GitHubAdapter(auth=Outage()).validate_issue_binding("o/r", 12)
    assert res_outage.outcome == ExternalOutcome.UNKNOWN
    assert res_outage.reason_code in (ExternalReasonCode.UNOBSERVABLE, ExternalReasonCode.TIMEOUT)


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
    res = GitHubAdapter(auth=_issue_auth(payload)).validate_issue_binding("o/r", 12)
    assert res.is_success
    assert res.data is True


def test_issue_validation_rejects_repository_mismatch_and_malformed_fixture():
    mismatch = {"number": 12, "repository_url": "https://api.github.com/repos/other/repo"}
    res_mismatch = GitHubAdapter(auth=_issue_auth(mismatch)).validate_issue_binding("o/r", 12)
    assert res_mismatch.is_failure
    assert res_mismatch.reason_code in (ExternalReasonCode.CONFLICT, ExternalReasonCode.NOT_FOUND)

    malformed = {
        "number": 12,
        "title": "Issue",
        "repository_url": "invalid-repo-url-format",
    }
    res_malformed = GitHubAdapter(auth=_issue_auth(malformed)).validate_issue_binding("o/r", 12)
    assert res_malformed.is_unknown_or_ambiguous or res_malformed.is_failure
    assert res_malformed.reason_code in (ExternalReasonCode.MALFORMED_RESPONSE, ExternalReasonCode.CONFLICT)


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


def _assert_secret_free(text_content: str, values: tuple[str, ...]):
    assert all(value not in text_content for value in values)


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
    res = adapter.push_branch(str(tmp_path), "origin", "feature", "abc")
    assert res.is_failure or res.outcome == ExternalOutcome.AMBIGUOUS
    message = res.error_message or ""
    _assert_secret_free(message, (token, encoded, basic, header))


class _FreshGitAuth:
    def __init__(self, token: str):
        self.token = token
        self.calls = 0
        self._cached = None

    def get_installation_token(self):
        self.calls += 1
        return self.token


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

    res = adapter.push_branch(str(tmp_path), "origin", "feature", "abc")
    assert auth.calls == 1
    assert res.is_failure or res.outcome == ExternalOutcome.AMBIGUOUS
    _assert_secret_free(res.error_message or "", (token, encoded, basic, header))


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

    res = adapter.get_remote_branch_head(str(tmp_path), "feature")
    assert auth.calls == 1
    assert res.is_failure or res.outcome == ExternalOutcome.UNKNOWN
    _assert_secret_free(res.error_message or "", (token, encoded, basic, header))


class _ReadinessGitHubStub:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error

    def validate_issue_binding(self, expected_repository, issue_number, github_repository=None):
        if self.error:
            return ExternalActionResult(
                outcome=ExternalOutcome.UNKNOWN,
                source_adapter="stub",
                reason_code=ExternalReasonCode.UNOBSERVABLE,
                error_message=str(self.error),
            )
        if self.result is False or (isinstance(self.result, tuple) and not self.result[0]):
            reason = self.result[1] if isinstance(self.result, tuple) else "Issue binding invalid"
            return ExternalActionResult(
                outcome=ExternalOutcome.FAILURE,
                source_adapter="stub",
                reason_code=ExternalReasonCode.NOT_FOUND,
                error_message=reason,
            )
        return ExternalActionResult(
            outcome=ExternalOutcome.SUCCESS,
            source_adapter="stub",
            reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
            data=True,
        )


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
    assert any("Issue repository mismatch" in r or "Issue binding" in r for r in result.unmet_reasons)


# Adversarial Unit Tests for Stage B Requirements (Task 15 & Task 16)

def test_create_issue_timeout_returns_ambiguous_without_fabricated_defaults():
    class TimeoutAuth:
        _cached = None
        client = httpx.Client(
            transport=httpx.MockTransport(
                lambda req: (_ for _ in ()).throw(httpx.TimeoutException("POST timeout"))
            ),
            base_url="https://api.github.com",
        )

        def get_installation_token(self):
            return "token"

    adapter = GitHubAdapter(auth=TimeoutAuth())
    res = adapter.create_issue("o/r", "Bug title", "Body content", operation_key="test-op-key-123")
    assert res.outcome == ExternalOutcome.AMBIGUOUS
    assert res.reason_code in (ExternalReasonCode.TIMEOUT, ExternalReasonCode.UNOBSERVABLE)
    assert res.retry_safety == RetrySafety.UNKNOWN
    assert res.data is None
    assert res.external_id is None
    assert res.error_message and "issue #1" not in res.error_message


def test_close_issue_404_returns_failure_not_found_no_true_fallback():
    class NotFoundAuth:
        _cached = None
        client = httpx.Client(
            transport=httpx.MockTransport(lambda req: httpx.Response(404, json={"message": "Not Found"})),
            base_url="https://api.github.com",
        )

        def get_installation_token(self):
            return "token"

    adapter = GitHubAdapter(auth=NotFoundAuth())
    res = adapter.close_issue("o/r", 999)
    assert res.outcome == ExternalOutcome.FAILURE
    assert res.reason_code == ExternalReasonCode.NOT_FOUND
    assert res.retry_safety == RetrySafety.UNSAFE
    assert res.data is False


def test_add_issue_to_project_auth_rejection_returns_failure_no_pvti_mock():
    class AuthRejectionAuth:
        _cached = None
        client = httpx.Client(
            transport=httpx.MockTransport(lambda req: httpx.Response(403, json={"message": "Resource protected"})),
            base_url="https://api.github.com",
        )

        def get_installation_token(self):
            return "token"

    adapter = GitHubAdapter(auth=AuthRejectionAuth())
    res = adapter.add_issue_to_project(1, "https://github.com/o/r/issues/12", "owner")
    assert res.outcome in (ExternalOutcome.FAILURE, ExternalOutcome.AMBIGUOUS)
    assert res.data is None
    assert res.external_id != "PVTI_mock_1"


def test_delete_remote_branch_404_requires_ls_remote_confirmation(tmp_path):
    class Auth:
        _cached = None
        client = httpx.Client(
            transport=httpx.MockTransport(lambda req: httpx.Response(404)),
            base_url="https://api.github.com",
        )

        def get_installation_token(self):
            return "token"

    adapter = GitHubAdapter(auth=Auth())
    adapter.get_remote_branch_head = lambda *args, **kwargs: ExternalActionResult(
        outcome=ExternalOutcome.FAILURE,
        source_adapter="git_cli",
        reason_code=ExternalReasonCode.NOT_FOUND,
        retry_safety=RetrySafety.SAFE,
    )

    res = adapter.delete_remote_branch("o/r", "feature-branch")
    assert res.outcome == ExternalOutcome.SUCCESS
    assert res.reason_code == ExternalReasonCode.ALREADY_ABSENT
    assert res.retry_safety == RetrySafety.UNSAFE
    assert res.data is True
