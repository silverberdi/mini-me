"""Regression tests for Stage B fail-closed external evidence and postcondition contracts."""

from unittest.mock import MagicMock

from minime.adapters.github import GitHubAdapter
from minime.domain.enums import (
    ExternalActionStatus,
    ExternalActionType,
    ExternalOutcome,
    ExternalReasonCode,
    RetrySafety,
)
from minime.domain.models import ExternalActionResult, OrchestrationExternalAction, utc_now


def test_create_issue_rest_error_does_not_call_cli_fallback(monkeypatch):
    """Req 2: REST ambiguity must return AMBIGUOUS without making gh CLI mutation fallback."""
    adapter = GitHubAdapter()

    # Mock _request to simulate HTTP 500 error on POST /repos/foo/bar/issues
    def mock_request(method, path, **kwargs):
        if method == "GET":
            # Search for operation key returns no issue
            res = MagicMock()
            res.status_code = 200
            res.json.return_value = []
            return res
        elif method == "POST":
            res = MagicMock()
            res.status_code = 500
            return res
        raise ValueError(f"Unexpected request: {method} {path}")

    monkeypatch.setattr(adapter, "_request", mock_request)

    # Mock subprocess.run to verify it is NEVER called for gh issue create
    subprocess_mock = MagicMock()
    monkeypatch.setattr("subprocess.run", subprocess_mock)

    result = adapter.create_issue(
        repository="silverberdi/mini-me",
        title="Test Issue",
        body="Body content",
        operation_key="op_test_123",
    )

    assert result.outcome == ExternalOutcome.AMBIGUOUS
    assert result.reason_code == ExternalReasonCode.UNOBSERVABLE
    # Assert gh issue create CLI fallback was NOT called
    subprocess_mock.assert_not_called()


def test_create_pull_request_unknown_or_ambiguous_lookup_blocks_create(monkeypatch):
    """Req 4: UNKNOWN or AMBIGUOUS lookup outcome must block PR POST creation completely."""
    adapter = GitHubAdapter()

    # Case A: lookup returns UNKNOWN
    unknown_lookup = ExternalActionResult(
        outcome=ExternalOutcome.UNKNOWN,
        source_adapter="github_rest",
        reason_code=ExternalReasonCode.UNOBSERVABLE,
        retry_safety=RetrySafety.UNKNOWN,
        error_message="GitHub API unobservable",
    )
    monkeypatch.setattr(adapter, "get_pull_request", lambda *args, **kwargs: unknown_lookup)

    request_mock = MagicMock()
    monkeypatch.setattr(adapter, "_request", request_mock)

    res_unknown = adapter.create_pull_request(
        repository="silverberdi/mini-me",
        branch="minime/feat",
        base="main",
        title="PR Title",
        body="PR Body",
        head_sha="abc1234",
    )
    assert res_unknown.outcome == ExternalOutcome.UNKNOWN
    request_mock.assert_not_called()

    # Case B: lookup returns AMBIGUOUS
    ambiguous_lookup = ExternalActionResult(
        outcome=ExternalOutcome.AMBIGUOUS,
        source_adapter="github_rest",
        reason_code=ExternalReasonCode.CONFLICT,
        retry_safety=RetrySafety.UNKNOWN,
        error_message="Multiple PRs found",
    )
    monkeypatch.setattr(adapter, "get_pull_request", lambda *args, **kwargs: ambiguous_lookup)

    res_ambiguous = adapter.create_pull_request(
        repository="silverberdi/mini-me",
        branch="minime/feat",
        base="main",
        title="PR Title",
        body="PR Body",
        head_sha="abc1234",
    )
    assert res_ambiguous.outcome == ExternalOutcome.AMBIGUOUS
    request_mock.assert_not_called()


def test_push_branch_verifies_remote_sha(tmp_path, monkeypatch):
    """Req 5: push_branch must verify exact remote SHA postcondition."""
    adapter = GitHubAdapter()

    # Create fake git worktree directory structure
    git_dir = tmp_path / ".git"
    git_dir.mkdir()

    # Setup _run_git mocks
    def mock_run_git(args, cwd, timeout, secrets=None):
        cmd = " ".join(args)
        proc = MagicMock()
        proc.returncode = 0
        if "remote get-url" in cmd:
            proc.stdout = "https://github.com/silverberdi/mini-me.git\n"
        elif "rev-parse --verify" in cmd:
            proc.stdout = "target_sha_123\n"
        elif "push" in cmd:
            proc.stdout = "pushed\n"
        return proc

    monkeypatch.setattr(adapter, "_run_git", mock_run_git)
    monkeypatch.setattr(adapter, "_git_auth_bundle", lambda r: MagicMock(args=(), secrets=()))

    # Case A: matching remote SHA -> SUCCESS
    monkeypatch.setattr(
        adapter,
        "get_remote_branch_head",
        lambda *a, **k: ExternalActionResult(
            outcome=ExternalOutcome.SUCCESS, source_adapter="git_cli", data="target_sha_123", reason_code=ExternalReasonCode.EXECUTION_SUCCESS
        ),
    )
    res_success = adapter.push_branch(str(tmp_path), "origin", "feat", "target_sha_123")
    assert res_success.outcome == ExternalOutcome.SUCCESS

    # Case B: different remote SHA -> FAILURE / CONFLICT
    monkeypatch.setattr(
        adapter,
        "get_remote_branch_head",
        lambda *a, **k: ExternalActionResult(
            outcome=ExternalOutcome.SUCCESS, source_adapter="git_cli", data="different_sha_999", reason_code=ExternalReasonCode.EXECUTION_SUCCESS
        ),
    )
    res_conflict = adapter.push_branch(str(tmp_path), "origin", "feat", "target_sha_123")
    assert res_conflict.outcome == ExternalOutcome.FAILURE
    assert res_conflict.reason_code == ExternalReasonCode.CONFLICT

    # Case C: unobservable remote SHA -> AMBIGUOUS (mutating effect occurred, postcondition unproven)
    monkeypatch.setattr(
        adapter,
        "get_remote_branch_head",
        lambda *a, **k: ExternalActionResult(
            outcome=ExternalOutcome.UNKNOWN, source_adapter="git_cli", reason_code=ExternalReasonCode.UNOBSERVABLE
        ),
    )
    res_ambiguous = adapter.push_branch(str(tmp_path), "origin", "feat", "target_sha_123")
    assert res_ambiguous.outcome == ExternalOutcome.AMBIGUOUS
    assert res_ambiguous.reason_code == ExternalReasonCode.POSTCONDITION_NOT_PROVEN
    assert res_ambiguous.retry_safety == RetrySafety.UNKNOWN


def test_update_project_item_status_verifies_postcondition(monkeypatch):
    """Req 6: update_project_item_status re-observes project items after edit command."""
    adapter = GitHubAdapter()

    # Case A: target status observed in list_project_items -> SUCCESS
    monkeypatch.setattr(
        adapter,
        "list_project_items",
        lambda p, o: ExternalActionResult(
            outcome=ExternalOutcome.SUCCESS,
            source_adapter="github_cli",
            data=[{"id": "item_100", "status": "Done"}],
            reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
        ),
    )
    monkeypatch.setattr("subprocess.run", lambda *a, **k: MagicMock(returncode=0))
    res_ok = adapter.update_project_item_status(2, "silverberdi", "item_100", "Done")
    assert res_ok.outcome == ExternalOutcome.SUCCESS

    # Case B: target status NOT observed -> FAILURE/CONFLICT
    monkeypatch.setattr(
        adapter,
        "list_project_items",
        lambda p, o: ExternalActionResult(
            outcome=ExternalOutcome.SUCCESS,
            source_adapter="github_cli",
            data=[{"id": "item_100", "status": "In Progress"}],
            reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
        ),
    )
    res_fail = adapter.update_project_item_status(2, "silverberdi", "item_100", "Done")
    assert res_fail.outcome == ExternalOutcome.FAILURE
    assert res_fail.reason_code == ExternalReasonCode.CONFLICT

    # Case C: list_project_items unobservable -> AMBIGUOUS (mutating edit occurred, postcondition unproven)
    monkeypatch.setattr(
        adapter,
        "list_project_items",
        lambda p, o: ExternalActionResult(
            outcome=ExternalOutcome.UNKNOWN,
            source_adapter="github_cli",
            reason_code=ExternalReasonCode.UNOBSERVABLE,
        ),
    )
    res_ambiguous = adapter.update_project_item_status(2, "silverberdi", "item_100", "Done")
    assert res_ambiguous.outcome == ExternalOutcome.AMBIGUOUS
    assert res_ambiguous.reason_code == ExternalReasonCode.POSTCONDITION_NOT_PROVEN
    assert res_ambiguous.retry_safety == RetrySafety.UNKNOWN


def test_adversarial_observe_before_repeat_read_safe_does_not_authorize_mutation(in_memory_uow):
    """Req 7: Original action AMBIGUOUS + read NOT_FOUND (read retry_safety=SAFE) MUST NOT transition to EXECUTING without explicit original_mutation_retry_authorized=True."""
    action_key = "pr_create:mini-me:008-test"

    # Save an initial AMBIGUOUS external action
    action = OrchestrationExternalAction(
        action_key=action_key,
        project_id="mini-me",
        run_id="run-123",
        job_id="job-123",
        action_type=ExternalActionType.PR_CREATE,
        status=ExternalActionStatus.AMBIGUOUS,
        target_identity="silverberdi/mini-me:minime/008-test",
        request_fingerprint="fp123",
        candidate_sha="cand123",
        generation=1,
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    in_memory_uow.orchestration_external_actions.reserve(action)

    # Simulated read observation returns NOT_FOUND with read retry_safety = SAFE
    read_observation = ExternalActionResult(
        outcome=ExternalOutcome.FAILURE,
        source_adapter="github_rest",
        reason_code=ExternalReasonCode.NOT_FOUND,
        retry_safety=RetrySafety.SAFE,
        error_message="PR not found on remote",
    )

    # 1. When original_mutation_retry_authorized is False (default): MUST remain AMBIGUOUS!
    reconciled = in_memory_uow.orchestration_external_actions.reconcile_observe_before_repeat(
        action_key=action_key,
        observed_result=read_observation,
        original_mutation_retry_authorized=False,
    )
    assert reconciled.status == ExternalActionStatus.AMBIGUOUS
    assert reconciled.status != ExternalActionStatus.EXECUTING

    # 2. When original_mutation_retry_authorized is explicitly True: transitions to EXECUTING
    reconciled_auth = in_memory_uow.orchestration_external_actions.reconcile_observe_before_repeat(
        action_key=action_key,
        observed_result=read_observation,
        original_mutation_retry_authorized=True,
    )
    assert reconciled_auth.status == ExternalActionStatus.EXECUTING


def test_create_issue_pre_observation_unknown_blocks_post(monkeypatch):
    """create_issue pre-observation list_issues returning UNKNOWN MUST fail closed and block POST mutation."""
    adapter = GitHubAdapter()

    # Pre-observation list_issues returns UNKNOWN
    monkeypatch.setattr(
        adapter,
        "list_issues",
        lambda repo, **kwargs: ExternalActionResult(
            outcome=ExternalOutcome.UNKNOWN,
            source_adapter="github_rest",
            reason_code=ExternalReasonCode.UNOBSERVABLE,
            retry_safety=RetrySafety.SAFE,
            error_message="GitHub list_issues unobservable",
        ),
    )

    req_mock = MagicMock()
    monkeypatch.setattr(adapter, "_request", req_mock)

    result = adapter.create_issue(
        repository="silverberdi/mini-me",
        title="Test Issue",
        body="Body",
        operation_key="op_test_key",
    )

    assert result.outcome == ExternalOutcome.UNKNOWN
    assert result.reason_code == ExternalReasonCode.UNOBSERVABLE
    req_mock.assert_not_called()


def test_add_issue_to_project_pre_observation_unknown_blocks_cli(monkeypatch):
    """add_issue_to_project pre-observation list_project_items returning UNKNOWN MUST block CLI item-add."""
    adapter = GitHubAdapter()

    # Pre-observation list_project_items returns UNKNOWN
    monkeypatch.setattr(
        adapter,
        "list_project_items",
        lambda project_number, owner: ExternalActionResult(
            outcome=ExternalOutcome.UNKNOWN,
            source_adapter="github_cli",
            reason_code=ExternalReasonCode.UNOBSERVABLE,
            retry_safety=RetrySafety.SAFE,
            error_message="Project list unobservable",
        ),
    )

    sub_mock = MagicMock()
    monkeypatch.setattr("subprocess.run", sub_mock)

    result = adapter.add_issue_to_project(
        project_number=2,
        owner="silverberdi",
        issue_url="https://github.com/silverberdi/mini-me/issues/101",
    )

    assert result.outcome == ExternalOutcome.UNKNOWN
    assert result.reason_code == ExternalReasonCode.UNOBSERVABLE
    sub_mock.assert_not_called()


def test_create_issue_201_missing_identity_returns_ambiguous(monkeypatch):
    """create_issue 201 response missing issue identity fields MUST return AMBIGUOUS (EVIDENCE_INSUFFICIENT, RetrySafety.UNKNOWN)."""
    adapter = GitHubAdapter()

    # Pre-observation list_issues returns no match
    monkeypatch.setattr(
        adapter,
        "list_issues",
        lambda repo, **kwargs: ExternalActionResult(
            outcome=ExternalOutcome.SUCCESS,
            source_adapter="github_rest",
            reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
            retry_safety=RetrySafety.SAFE,
            data=[],
        ),
    )

    # REST POST returns 201 created but missing issue number and html_url
    def mock_request(method, path, **kwargs):
        res = MagicMock()
        res.status_code = 201
        res.json.return_value = {"title": "Test Issue"}  # Missing "number" and "html_url"
        return res

    monkeypatch.setattr(adapter, "_request", mock_request)

    result = adapter.create_issue(
        repository="silverberdi/mini-me",
        title="Test Issue",
        body="Body",
        operation_key="op_test_key",
    )

    assert result.outcome == ExternalOutcome.AMBIGUOUS
    assert result.reason_code == ExternalReasonCode.EVIDENCE_INSUFFICIENT
    assert result.retry_safety == RetrySafety.UNKNOWN
