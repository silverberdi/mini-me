import json
import subprocess
from datetime import UTC, datetime, timedelta

import httpx

from minime.adapters.github import GitHubAdapter
from minime.domain.enums import ExternalOutcome
from minime.domain.interfaces import GitPullRequestAdapter, TicketSourceAdapter


class _StaticAuth:
    def __init__(self, handler):
        self.client = httpx.Client(
            base_url="https://api.github.test",
            transport=httpx.MockTransport(handler),
        )

    def get_installation_token(self):
        return "test-token"


def test_github_adapter_implements_narrow_ticket_and_git_contracts():
    adapter = GitHubAdapter(auth=_StaticAuth(lambda _: httpx.Response(200, json=[])))

    assert isinstance(adapter, TicketSourceAdapter)
    assert isinstance(adapter, GitPullRequestAdapter)


def test_project_github_adapter_creates_branch_from_observed_commit_and_reconciles():
    base_sha = "a" * 40
    created = []

    def handler(request):
        if request.method == "GET" and request.url.path.endswith("/git/ref/heads/topic/context"):
            if not created:
                return httpx.Response(404, json={"message": "Not Found"})
            return httpx.Response(
                200,
                json={
                    "ref": "refs/heads/topic/context",
                    "object": {"sha": created[-1]},
                },
            )
        if request.method == "POST" and request.url.path.endswith("/git/refs"):
            payload = json.loads(request.content)
            assert payload == {"ref": "refs/heads/topic/context", "sha": base_sha}
            created.append(payload["sha"])
            return httpx.Response(201, json={"ref": payload["ref"]})
        return httpx.Response(404)

    adapter = GitHubAdapter(auth=_StaticAuth(handler))
    result = adapter.create_remote_branch("example/demo", "topic/context", base_sha)

    assert result.outcome == ExternalOutcome.SUCCESS
    assert result.data == base_sha
    assert len(created) == 1
    reused = adapter.create_remote_branch("example/demo", "topic/context", base_sha)
    assert reused.outcome == ExternalOutcome.SUCCESS
    assert len(created) == 1


def test_project_github_adapter_blocks_branch_reuse_with_a_different_base():
    observed_sha = "b" * 40
    posts = []

    def handler(request):
        if request.method == "GET" and request.url.path.endswith("/git/ref/heads/main"):
            return httpx.Response(
                200,
                json={"ref": "refs/heads/main", "object": {"sha": observed_sha}},
            )
        if request.method == "POST":
            posts.append(request)
        return httpx.Response(404)

    result = GitHubAdapter(auth=_StaticAuth(handler)).create_remote_branch(
        "example/demo", "main", "a" * 40
    )

    assert result.outcome == ExternalOutcome.FAILURE
    assert result.data == observed_sha
    assert posts == []


def test_project_github_adapter_reports_provider_default_branch_only_for_exact_repo():
    requested = []

    def handler(request):
        requested.append(request.url.path)
        return httpx.Response(
            200,
            json={"full_name": "example/demo", "default_branch": "develop"},
        )

    result = GitHubAdapter(auth=_StaticAuth(handler)).get_repository_default_branch(
        "https://github.com/example/demo.git"
    )

    assert result.outcome == ExternalOutcome.SUCCESS
    assert result.data == "develop"
    assert requested == ["/repos/example/demo"]


def test_issue_comment_reconciles_by_operation_key_without_duplicate_post():
    comments = []
    posts = []

    def handler(request):
        if request.method == "GET":
            return httpx.Response(200, json=comments)
        if request.method == "POST":
            body = json.loads(request.content)
            posts.append(body)
            comment = {"id": 17, "body": body["body"]}
            comments.append(comment)
            return httpx.Response(201, json=comment)
        return httpx.Response(405)

    adapter = GitHubAdapter(auth=_StaticAuth(handler))
    first = adapter.comment_issue("owner/repo", 12, "Review is ready", "run-1:review")
    retried = adapter.comment_issue("owner/repo", 12, "Review is ready", "run-1:review")

    assert first.outcome == ExternalOutcome.SUCCESS
    assert retried.outcome == ExternalOutcome.SUCCESS
    assert retried.reason_code.value == "REUSED_EXISTING"
    assert len(posts) == 1
    assert "<!-- minime-operation:run-1:review -->" in posts[0]["body"]


def test_issue_comment_blocks_post_when_history_is_unobservable():
    def handler(request):
        return httpx.Response(503)

    adapter = GitHubAdapter(auth=_StaticAuth(handler))
    result = adapter.comment_issue("owner/repo", 12, "Review is ready", "run-1:review")

    assert result.outcome == ExternalOutcome.UNKNOWN
    assert "POST blocked" in result.error_message


def test_project_connection_permission_check_requires_exact_repo_and_grants():
    from minime.adapters.github import _CachedInstallationToken

    def handler(request):
        assert request.method == "GET"
        return httpx.Response(200, json={"full_name": "owner/repo"})

    auth = _StaticAuth(handler)
    auth._cached = _CachedInstallationToken(
        "test-token",
        datetime.now(UTC) + timedelta(hours=1),
        {"contents": "write", "pull_requests": "write"},
    )
    result = GitHubAdapter(auth=auth).verify_connection_permissions("owner/repo", "git_pr")

    assert result.outcome == ExternalOutcome.SUCCESS
    assert result.data["repository"] == "owner/repo"
    assert result.data["permissions"] == {"contents": "write", "pull_requests": "write"}


def test_project_connection_permission_check_fails_closed_when_grants_missing():
    from minime.adapters.github import _CachedInstallationToken

    auth = _StaticAuth(lambda _: httpx.Response(200, json={"full_name": "owner/repo"}))
    auth._cached = _CachedInstallationToken(
        "test-token",
        datetime.now(UTC) + timedelta(hours=1),
        {"contents": "read", "pull_requests": "read"},
    )
    result = GitHubAdapter(auth=auth).verify_connection_permissions("owner/repo", "git_pr")

    assert result.outcome == ExternalOutcome.FAILURE
    assert "contents, pull_requests" in result.error_message


def test_git_push_error_redacts_project_installation_token(tmp_path, monkeypatch):
    repository = tmp_path / "repo"
    repository.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repository, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repository, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=repository, check=True)
    (repository / "README.md").write_text("safe", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repository, check=True)
    subprocess.run(["git", "commit", "-m", "test"], cwd=repository, check=True, capture_output=True)
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repository, check=True, capture_output=True, text=True
    ).stdout.strip()
    subprocess.run(
        ["git", "remote", "add", "origin", "https://github.com/owner/repo.git"],
        cwd=repository,
        check=True,
    )
    adapter = GitHubAdapter(auth=_StaticAuth(lambda _: httpx.Response(200)))
    adapter.auth.get_installation_token = lambda: "raw-test-access-token"
    original_run_git = adapter._run_git

    def fake_run_git(args, **kwargs):
        if "push" in args:
            return subprocess.CompletedProcess(
                args,
                1,
                "",
                "remote rejected token raw-test-access-token (HTTP 403)",
            )
        return original_run_git(args, **kwargs)

    monkeypatch.setattr(adapter, "_run_git", fake_run_git)
    result = adapter.push_branch(str(repository), "origin", "candidate", sha)

    assert result.outcome == ExternalOutcome.FAILURE
    assert "raw-test-access-token" not in (result.error_message or "")
    assert "raw-test-access-token" not in (result.provider_detail or "")
