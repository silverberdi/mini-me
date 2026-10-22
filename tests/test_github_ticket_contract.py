import json
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
