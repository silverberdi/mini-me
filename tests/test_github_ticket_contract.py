import json

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
