"""F4 deterministic contracts: Issue provenance, semantic PRs and capabilities."""

import json
from pathlib import Path

import httpx
import pytest

from minime.adapters.github import GitHubAdapter
from minime.domain.enums import ExternalOutcome
from minime.services.capability_manifest import CapabilityConflictError, CapabilityManifestService
from minime.services.pr_preparer_service import PrPreparationInput, PrPreparerService
from minime.services.request_normalization import (
    NormalizedRequest,
    RequestNormalizationError,
    RequestNormalizationService,
)


class StaticAuth:
    def __init__(self, handler):
        self.client = httpx.Client(
            base_url="https://api.github.test", transport=httpx.MockTransport(handler)
        )

    def get_installation_token(self):
        return "test-token"


def test_normalization_preserves_original_and_reconciles_idempotently():
    original = "We need a sorter with a stable console output."
    normalized = """Feature: Console sorter

Scenario: Stable output
  Given a sorter input
  When the sorter runs
  Then the console output is stable
"""
    issue = {"number": 7, "body": original, "updated_at": "v1", "repository_url": "/repos/o/r"}
    comments: list[dict[str, object]] = []

    def handler(request):
        if request.method == "GET" and request.url.path.endswith("/issues/7"):
            return httpx.Response(200, json=issue, headers={"etag": '"v1"'})
        if request.method == "GET" and request.url.path.endswith("/issues/7/comments"):
            return httpx.Response(200, json=comments)
        if request.method == "POST" and request.url.path.endswith("/issues/7/comments"):
            payload = json.loads(request.content)
            comment = {"id": len(comments) + 1, "body": payload["body"]}
            comments.append(comment)
            return httpx.Response(201, json=comment)
        if request.method == "PATCH" and request.url.path.endswith("/issues/7"):
            assert request.headers["if-match"] == '"v1"'
            issue["body"] = json.loads(request.content)["body"]
            return httpx.Response(200, json=issue, headers={"etag": '"v2"'})
        return httpx.Response(404)

    service = RequestNormalizationService(GitHubAdapter(auth=StaticAuth(handler)))
    result = service.publish(
        "o/r", 7, "run-1", NormalizedRequest(original, normalized, False, ("AC1",))
    )
    repeated = service.publish(
        "o/r", 7, "run-1", NormalizedRequest(original, normalized, False, ("AC1",))
    )

    assert result["original_body_sha256"] != result["normalized_body_sha256"]
    assert repeated["provenance_key"] == "run-1:7"
    assert len(comments) == 1
    assert original in str(comments[0]["body"])
    assert issue["body"] == normalized


def test_normalization_fails_closed_when_remote_issue_changed():
    class ChangedIssue:
        def get_issue(self, *_):
            return type("Result", (), {"outcome": ExternalOutcome.SUCCESS, "data": {"body": "other"}})()

    service = RequestNormalizationService(ChangedIssue())
    with pytest.raises(RequestNormalizationError, match="changed concurrently"):
        service.publish("o/r", 7, "run-1", NormalizedRequest("original", "normalized", False))


def test_semantic_pr_content_is_validated_without_auto_close():
    prepared = PrPreparerService().prepare_pull_request(
        PrPreparationInput(
            project_id="project",
            repository="o/r",
            pr_type="implementation",
            issue_number=7,
            issue_title="Original title",
            base_branch="main",
            candidate_branch="request-7-change",
            candidate_sha="a" * 40,
            change_name="req-7-change",
            change_summary="unused fallback",
            test_evidence="pytest exit code 0",
            semantic_title="feat(req-7-change): semantic title (Addresses #7)",
            semantic_body="## Evidence\n\nAddresses #7; no automatic closure.",
        )
    )
    assert prepared.title.startswith("feat(req-7-change)")
    assert "Addresses #7" in prepared.body


def test_greenfield_capability_manifest_is_idempotent_and_preserves_conflicts(tmp_path: Path):
    source = tmp_path / "source"
    target = tmp_path / "target"
    (source / ".agents/skills/minime-example").mkdir(parents=True)
    (source / ".agents/skills/minime-example/SKILL.md").write_text("source", encoding="utf-8")
    (source / ".agent/workflows/minime-helper.md").parent.mkdir(parents=True)
    (source / ".agent/workflows/minime-helper.md").write_text("workflow", encoding="utf-8")
    target.mkdir()

    service = CapabilityManifestService()
    first = service.install_greenfield(source, target)
    second = service.install_greenfield(source, target)
    assert first["count"] == second["count"] == 2
    assert service.validate_f5_readiness(
        second, {"complete": True}, project_type="GREENFIELD"
    )["status"] == "READY_FOR_F5_PREPARATION"

    (target / ".agents/skills/minime-example/SKILL.md").write_text("changed", encoding="utf-8")
    with pytest.raises(CapabilityConflictError):
        service.install_greenfield(source, target)


def test_deterministic_greenfield_vertical_journey_uses_real_contracts(tmp_path: Path):
    """A simulated agent proves orchestration contracts, never functional E2E."""
    source = tmp_path / "source"
    target = tmp_path / "target"
    (source / ".agents/skills/minime-example").mkdir(parents=True)
    (source / ".agents/skills/minime-example/SKILL.md").write_text("source", encoding="utf-8")
    target.mkdir()
    manifest = CapabilityManifestService().install_greenfield(source, target)
    assert manifest["greenfield_only"] is True

    original = "Define a stable sorter output."
    issue = {"number": 9, "body": original, "repository_url": "/repos/o/r"}
    comments: list[dict[str, object]] = []

    def handler(request):
        if request.method == "GET" and request.url.path.endswith("/issues/9"):
            return httpx.Response(200, json=issue, headers={"etag": '"one"'})
        if request.method == "GET" and request.url.path.endswith("/issues/9/comments"):
            return httpx.Response(200, json=comments)
        if request.method == "POST" and request.url.path.endswith("/issues/9/comments"):
            payload = json.loads(request.content)
            item = {"id": len(comments) + 1, "body": payload["body"]}
            comments.append(item)
            return httpx.Response(201, json=item)
        if request.method == "PATCH" and request.url.path.endswith("/issues/9"):
            issue["body"] = json.loads(request.content)["body"]
            return httpx.Response(200, json=issue)
        return httpx.Response(404)

    normalizer = RequestNormalizationService(
        GitHubAdapter(auth=StaticAuth(handler)),
        semantic_normalizer=lambda _title, _body: (
            "Feature: Sorter\n\n"
            "Scenario: Stable output\n"
            "  Given input\n  When sorting\n  Then output is stable\n"
        ),
    )
    normalized = normalizer.normalize("Sorter", original)
    evidence = normalizer.publish("o/r", 9, "run-deterministic", normalized)
    pr = PrPreparerService().prepare_pull_request(
        PrPreparationInput(
            project_id="greenfield",
            repository="o/r",
            pr_type="implementation",
            issue_number=9,
            issue_title="Sorter",
            base_branch="main",
            candidate_branch="request-9-sorter",
            candidate_sha="b" * 40,
            change_name="req-9-sorter",
            change_summary="Documented sorter behavior",
            test_evidence="deterministic contract exit code 0",
            semantic_title="feat(req-9-sorter): sorter (Addresses #9)",
            semantic_body="## Evidence\n\nAddresses #9",
        )
    )
    assert evidence["normalized"] is True
    assert issue["body"] == normalized.normalized_body
    assert pr.candidate_sha == "b" * 40
