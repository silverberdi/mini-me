"""F4 deterministic contracts: Issue provenance, semantic PRs and capabilities."""

import json
from pathlib import Path

import httpx
import pytest

from minime.adapters.github import GitHubAdapter
from minime.domain.enums import ExternalOutcome, ExternalReasonCode, RetrySafety
from minime.domain.enums import OrchestrationStage
from minime.domain.models import ExternalActionResult, OrchestrationRun
from minime.services.agent_runner import AgentExecutionResult
from minime.services.capability_manifest import CapabilityConflictError, CapabilityManifestService
from minime.services.orchestration_coordinator import NativeOrchestrationCoordinator
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


def test_semantic_normalization_comment_is_idempotent_and_confirmed():
    original = "Necesitamos ordenar la salida y conservar tres criterios: C1, C2 y C3."
    normalized = """Feature: Ordenación de consola

Scenario: Salida estable
  Given una entrada válida
  When se ordena la salida
  Then se conserva el orden definido
"""
    issue = {"number": 8, "body": original, "repository_url": "/repos/o/r"}
    comments: list[dict[str, object]] = []

    def handler(request):
        if request.method == "GET" and request.url.path.endswith("/issues/8"):
            return httpx.Response(200, json=issue, headers={"etag": '"v1"'})
        if request.method == "GET" and request.url.path.endswith("/issues/8/comments"):
            return httpx.Response(200, json=comments)
        if request.method == "POST" and request.url.path.endswith("/issues/8/comments"):
            payload = json.loads(request.content)
            item = {"id": len(comments) + 1, "body": payload["body"]}
            comments.append(item)
            return httpx.Response(201, json=item)
        if request.method == "PATCH" and request.url.path.endswith("/issues/8"):
            issue["body"] = json.loads(request.content)["body"]
            return httpx.Response(200, json=issue)
        return httpx.Response(404)

    service = RequestNormalizationService(GitHubAdapter(auth=StaticAuth(handler)))
    request = NormalizedRequest(
        original,
        normalized,
        False,
        ("C1", "C2", "C3"),
        "Se normalizó el Request y se conservaron C1, C2 y C3.",
    )
    first = service.publish("o/r", 8, "run-semantic", request)
    second = service.publish("o/r", 8, "run-semantic", request)

    assert first["semantic_message"] == request.semantic_message
    assert second["provenance_key"] == "run-semantic:8"
    assert len(comments) == 2
    assert sum("Original Request" in str(item["body"]) for item in comments) == 1
    assert sum("minime-request-normalization-semantic" in str(item["body"]) for item in comments) == 1


@pytest.mark.asyncio
async def test_coordinator_requires_and_persists_structured_semantic_message(tmp_path: Path):
    issue = {"number": 11, "body": "C1: ordenar. C2: conservar. C3: explicar.", "repository_url": "/repos/o/r"}
    comments: list[dict[str, object]] = []

    class Github:
        @staticmethod
        def ok(data, evidence=None):
            return ExternalActionResult(
                outcome=ExternalOutcome.SUCCESS,
                source_adapter="test",
                reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
                retry_safety=RetrySafety.SAFE,
                data=data,
                observed_evidence=evidence or {},
            )

        def get_issue(self, *_):
            return self.ok(issue, {"etag": '"v1"'})

        def list_issue_comments(self, *_):
            return self.ok(comments)

        def comment_issue(self, _repo, _number, body, _key):
            if not any(item["body"] == body for item in comments):
                comments.append({"id": len(comments) + 1, "body": body})
            return self.ok(comments[-1])

        def update_issue_body(self, _repo, _number, body, expected_version=None):
            issue["body"] = body
            return self.ok(issue)

    class Runner:
        def resolve_workflow(self, **_kwargs):
            return object()

        async def run(self, **_kwargs):
            payload = {
                "normalized_body": (
                    "Feature: Ordenación\n\nScenario: Criterios\n"
                    "  Given una entrada\n  When se ordena\n  Then C1 C2 y C3 permanecen trazables"
                ),
                "criteria": ["C1", "C2", "C3"],
                "semantic_message": "Se normalizó el Request y se conservaron C1, C2 y C3.",
            }
            encoded = json.dumps(payload, ensure_ascii=False)
            return AgentExecutionResult(
                exit_code=0,
                timed_out=False,
                stdout=[],
                stderr=[],
                duration_ms=1,
                structured_output=[encoded],
                diagnostic_output=[],
            )

    run = OrchestrationRun(project_id="project", change_name="issue-11", base_sha="main")

    class Runs:
        def get_by_id(self, _run_id):
            return run

        def save(self, value):
            nonlocal run
            run = value

    class Uow:
        orchestration_runs = Runs()

        def commit(self):
            return None

    coordinator = NativeOrchestrationCoordinator(
        uow_factory=Uow,
        github_adapter=Github(),
        worktree_manager=object(),
        agent_runner=Runner(),
    )
    persisted, normalized_body = await coordinator._normalize_request_before_explore(
        active_run=run,
        project_id="project",
        repository="o/r",
        worktree_path=tmp_path,
        issue_number=11,
        issue_title="Criterios",
        issue_body=issue["body"],
        provider="codex",
    )

    assert normalized_body.startswith("Feature: Ordenación")
    assert persisted["criteria"] == ["C1", "C2", "C3"]
    assert persisted["semantic_message"].startswith("Se normalizó")
    assert any("Original Request" in str(item["body"]) for item in comments)
    assert any("Se normalizó" in str(item["body"]) for item in comments)
    assert run.current_stage is OrchestrationStage.ADMITTED


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
        second,
        {"complete": True},
        project_type="GREENFIELD",
        profiles_observed=True,
        worktree_identity_verified=True,
        confinement_verified=True,
        github_binding_verified=True,
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


def test_capability_manifest_selects_resources_by_configured_provider(tmp_path: Path):
    source = tmp_path / "source"
    target = tmp_path / "target"
    for root in (".agents", ".agent"):
        for name in ("minime-request-normalizer", "minime-pr-preparer"):
            path = source / root / "skills" / name
            path.mkdir(parents=True)
            (path / "SKILL.md").write_text(f"{root}:{name}", encoding="utf-8")
    target.mkdir()
    manifest = CapabilityManifestService().install_greenfield(
        source,
        target,
        profiles={
            "thinking": {"agent_id": "codex", "skills": ["minime-request-normalizer"]},
            "execution": {"agent_id": "antigravity", "skills": ["minime-pr-preparer"]},
        },
    )
    assert set(manifest["selected_paths"]) == {
        ".agents/skills/minime-request-normalizer/SKILL.md",
        ".agent/skills/minime-pr-preparer/SKILL.md",
    }
    assert not (target / ".agents/skills/minime-pr-preparer").exists()
    assert not (target / ".agent/skills/minime-request-normalizer").exists()


def test_semantic_pr_agent_contract_is_structured_and_fail_closed(tmp_path: Path):
    class FakeRunner:
        def resolve_workflow(self, **kwargs):
            return object()

        async def run(self, **kwargs):
            return AgentExecutionResult(
                exit_code=0,
                timed_out=False,
                stdout=['{"title":"feat(req-7): semantic (Addresses #7)","body":"## Evidence\\n\\nAddresses #7"}'],
                stderr=[],
                duration_ms=1,
                structured_output=['{"title":"feat(req-7): semantic (Addresses #7)","body":"## Evidence\\n\\nAddresses #7"}'],
                diagnostic_output=[],
            )

    coordinator = NativeOrchestrationCoordinator(
        uow_factory=lambda: None,
        github_adapter=object(),
        worktree_manager=object(),
        agent_runner=FakeRunner(),
        semantic_pr_agent=True,
    )
    prepared = __import__("asyncio").run(
        coordinator._prepare_semantic_pr_content(
            worktree_path=tmp_path,
            provider="codex",
            project_id="project",
            run_id="run-1",
            pr_input=PrPreparationInput(
                project_id="project",
                repository="o/r",
                pr_type="implementation",
                issue_number=7,
                issue_title="Sorter",
                base_branch="main",
                candidate_branch="request-7-sorter",
                candidate_sha="a" * 40,
                change_name="req-7-sorter",
                change_summary="summary",
                test_evidence="pytest exit code 0",
            ),
            request_body="Feature: Sorter",
        )
    )
    assert prepared[0].startswith("feat(req-7)")
