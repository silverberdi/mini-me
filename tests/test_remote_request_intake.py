"""Unit tests for RemoteRequestIntakeService (F3 tasks 1.1 - 1.5)."""

from unittest.mock import MagicMock

from minime.domain.enums import ExternalOutcome, ExternalReasonCode, RetrySafety
from minime.domain.models import ExternalActionResult
from minime.services.remote_request_intake import (
    RemoteRequestIntakeService,
    parse_explicit_dependencies,
)


class MockGitHubAdapter:
    def __init__(self, issues: list[dict]):
        self.issues = issues
        self.list_issues_calls: list[dict] = []

    def list_issues(self, repository: str, state: str = "open", limit: int | None = None):
        self.list_issues_calls.append({"repository": repository, "state": state, "limit": limit})
        return ExternalActionResult(
            outcome=ExternalOutcome.SUCCESS,
            source_adapter="mock_github",
            reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
            retry_safety=RetrySafety.SAFE,
            data=list(self.issues),
        )


def test_parse_explicit_dependencies_identifies_formal_directives():
    body = (
        "This feature implements user onboarding.\n\n"
        "Depends on #101\n"
        "blocked by: #102\n"
        "- [ ] Depends on #103\n"
        "- [ ] #104\n"
        "Relates to #105 casually.\n"
        "See also #106 for context.\n"
        "Fixed in #107."
    )
    deps = parse_explicit_dependencies(body)
    assert 101 in deps
    assert 102 in deps
    assert 103 in deps
    assert 104 in deps
    # Casual mentions are NOT dependencies
    assert 105 not in deps
    assert 106 not in deps
    assert 107 not in deps


def test_fifo_ordering_and_deterministic_tie_breaker():
    issues = [
        {"number": 3, "title": "C", "created_at": "2026-10-20T12:00:00Z"},
        {"number": 1, "title": "A", "created_at": "2026-10-18T10:00:00Z"},
        {"number": 2, "title": "B", "created_at": "2026-10-19T11:00:00Z"},
        # Same timestamp as issue 4, but number is lower
        {"number": 5, "title": "E", "created_at": "2026-10-21T00:00:00Z"},
        {"number": 4, "title": "D", "created_at": "2026-10-21T00:00:00Z"},
    ]
    adapter = MockGitHubAdapter(issues)
    service = RemoteRequestIntakeService(github_adapter=adapter)

    eligible = service.get_eligible_requests("owner/repo")
    numbers = [item["number"] for item in eligible]
    assert numbers == [1, 2, 3, 4, 5]


def test_filter_excludes_disabled_issues():
    issues = [
        {"number": 1, "title": "Disabled issue", "created_at": "2026-10-10T10:00:00Z", "labels": [{"name": "disabled"}]},
        {"number": 2, "title": "String disabled", "created_at": "2026-10-11T10:00:00Z", "labels": ["Disabled"]},
        {"number": 3, "title": "Active issue", "created_at": "2026-10-12T10:00:00Z", "labels": [{"name": "bug"}]},
    ]
    adapter = MockGitHubAdapter(issues)
    service = RemoteRequestIntakeService(github_adapter=adapter)

    eligible = service.get_eligible_requests("owner/repo")
    assert len(eligible) == 1
    assert eligible[0]["number"] == 3


def test_filter_excludes_blocked_by_open_dependency_and_unblocks_when_closed():
    # Issue 2 depends on Issue 1. Issue 1 is open.
    # Issue 3 depends on Issue 99. Issue 99 is closed (not in open list).
    issues = [
        {"number": 1, "title": "Base task", "created_at": "2026-10-01T10:00:00Z", "body": "Initial work"},
        {
            "number": 2,
            "title": "Blocked task",
            "created_at": "2026-10-02T10:00:00Z",
            "body": "Depends on #1",
        },
        {
            "number": 3,
            "title": "Unblocked task with closed dep",
            "created_at": "2026-10-03T10:00:00Z",
            "body": "Depends on #99",
        },
        {
            "number": 4,
            "title": "Casual mention not blocked",
            "created_at": "2026-10-04T10:00:00Z",
            "body": "Relates to #1",
        },
    ]
    adapter = MockGitHubAdapter(issues)
    service = RemoteRequestIntakeService(github_adapter=adapter)

    eligible = service.get_eligible_requests("owner/repo")
    numbers = [item["number"] for item in eligible]
    # Issue 1 is eligible.
    # Issue 2 is blocked because Issue 1 is open.
    # Issue 3 is eligible because 99 is closed.
    # Issue 4 is eligible because "Relates to" is casual.
    assert numbers == [1, 3, 4]

    # Now simulate Issue 1 being closed (removed from open issues)
    adapter.issues = [issues[1], issues[2], issues[3]]
    eligible_after_close = service.get_eligible_requests("owner/repo")
    numbers_after_close = [item["number"] for item in eligible_after_close]
    # Issue 2 is now unblocked and preserves its original FIFO seniority!
    assert numbers_after_close == [2, 3, 4]


def test_select_next_request_returns_none_when_idle():
    adapter = MockGitHubAdapter([])
    service = RemoteRequestIntakeService(github_adapter=adapter)

    selected = service.select_next_request("proj-1", "owner/repo")
    assert selected is None


def test_select_next_request_recognizes_reentrant_active_run():
    mock_run = MagicMock()
    mock_run.id = "run-123"
    mock_run.is_active = True
    mock_run.issue_number = 42
    mock_run.change_name = "test-change"

    mock_uow = MagicMock()
    mock_runs_repo = MagicMock()
    mock_runs_repo.get_active_by_project.return_value = mock_run
    mock_uow.orchestration_runs = mock_runs_repo

    adapter = MockGitHubAdapter([{"number": 99, "created_at": "2026-10-01T00:00:00Z"}])
    service = RemoteRequestIntakeService(github_adapter=adapter, uow=mock_uow)

    selected = service.select_next_request("proj-1", "owner/repo")
    assert selected is not None
    assert selected["re_entrant"] is True
    assert selected["run_id"] == "run-123"
    assert selected["issue_number"] == 42
    # Remote issues were not picked over active run
    assert adapter.list_issues_calls == []


def test_select_next_request_picks_first_fifo_when_idle():
    issues = [
        {"number": 10, "title": "First", "created_at": "2026-10-01T00:00:00Z", "body": "Details"},
        {"number": 20, "title": "Second", "created_at": "2026-10-02T00:00:00Z", "body": "Details"},
    ]
    mock_uow = MagicMock()
    mock_runs_repo = MagicMock()
    mock_runs_repo.get_active_by_project.return_value = None
    mock_uow.orchestration_runs = mock_runs_repo

    adapter = MockGitHubAdapter(issues)
    service = RemoteRequestIntakeService(github_adapter=adapter, uow=mock_uow)

    selected = service.select_next_request("proj-1", "owner/repo")
    assert selected is not None
    assert selected["re_entrant"] is False
    assert selected["issue_number"] == 10
    assert selected["title"] == "First"
