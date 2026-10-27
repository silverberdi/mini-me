"""F4 deterministic contracts: Issue provenance, semantic PRs and capabilities."""

import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from minime.adapters.github import GitHubAdapter
from minime.domain.enums import ExternalOutcome, ExternalReasonCode, OrchestrationStage, RetrySafety
from minime.domain.models import ExternalActionResult, OrchestrationRun
from minime.services.agent_runner import AgentExecutionResult
from minime.services.capability_manifest import (
    CapabilityConflictError,
    CapabilityManifestService,
    GreenfieldCapabilityAuthorization,
)
from minime.services.orchestration_coordinator import NativeOrchestrationCoordinator
from minime.services.pr_preparer_service import PrPreparationInput, PrPreparerService
from minime.services.request_normalization import (
    NormalizedRequest,
    RequestNormalizationError,
    RequestNormalizationService,
    gherkin_validation_errors,
    validate_normalized_body,
)


class StaticAuth:
    def __init__(self, handler):
        self.client = httpx.Client(
            base_url="https://api.github.test", transport=httpx.MockTransport(handler)
        )

    def get_installation_token(self):
        return "test-token"


def test_gherkin_validator_reports_supported_dialects_and_concrete_errors():
    validate_normalized_body(
        "Feature: Ordenación\n\nScenario: Criterios\n"
        "  Given una entrada\n  When se ordena\n  Then C1 se conserva"
    )
    validate_normalized_body(
        "# language: es\nCaracterística: Ordenación\n\n"
        "Escenario: Criterios\n Dado una entrada\n Cuando se ordena\n Entonces C1 se conserva"
    )
    assert gherkin_validation_errors("Feature: incompleta") == (
        "missing en Gherkin 'Scenario:' header",
        "missing en Gherkin 'Given' step",
        "missing en Gherkin 'When' step",
        "missing en Gherkin 'Then' step",
    )
    assert gherkin_validation_errors("# language: fr\nFonctionnalité: X") == (
        "unsupported Gherkin dialect 'fr'; supported dialects are en and es",
    )


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
            assert "if-match" not in request.headers
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
            return type(
                "Result", (), {"outcome": ExternalOutcome.SUCCESS, "data": {"body": "other"}}
            )()

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
    assert (
        sum("minime-request-normalization-semantic" in str(item["body"]) for item in comments) == 1
    )


@pytest.mark.asyncio
async def test_coordinator_requires_and_persists_structured_semantic_message(tmp_path: Path):
    issue = {
        "number": 11,
        "body": "C1: ordenar. C2: conservar. C3: explicar.",
        "repository_url": "/repos/o/r",
    }
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

        def update_issue_body(self, _repo, _number, body, expected_body=None):
            assert expected_body == issue["body"]
            issue["body"] = body
            return self.ok(issue)

    class Runner:
        def resolve_workflow(self, **_kwargs):
            return SimpleNamespace(
                dispatch_command="$minime-request-normalizer issue-11", workflow_sha256="wf"
            )

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
                output_truncated=True,
            )

        @staticmethod
        def observed_usage(_result):
            return None

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
    assert "rejected_response" not in run.stop_details
    assert any("Original Request" in str(item["body"]) for item in comments)
    assert any("Se normalizó" in str(item["body"]) for item in comments)
    assert run.current_stage is OrchestrationStage.ADMITTED


def test_normalizer_skills_match_coordinator_schema():
    coordinator_source = Path("src/minime/services/orchestration_coordinator.py").read_text(
        encoding="utf-8"
    )
    assert '"required": ["normalized_body", "criteria", "semantic_message"]' in coordinator_source
    for relative in (
        ".agents/skills/minime-request-normalizer/SKILL.md",
        ".agent/skills/minime-request-normalizer/SKILL.md",
    ):
        skill = Path(relative).read_text(encoding="utf-8")
        assert "`normalized_body`, `criteria` and `semantic_message`" in skill
        assert "`normalized_body` and `criteria`." not in skill


@pytest.mark.asyncio
async def test_failed_normalization_persists_diagnostic_and_blocks_reentry(tmp_path: Path):
    issue = {"number": 12, "body": "C1: una solicitud informal.", "repository_url": "/repos/o/r"}
    run = OrchestrationRun(project_id="project", change_name="issue-12", base_sha="main")
    calls = 0

    def ok(data):
        return ExternalActionResult(
            outcome=ExternalOutcome.SUCCESS,
            source_adapter="test",
            reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
            retry_safety=RetrySafety.SAFE,
            data=data,
        )

    class Github:
        def get_issue(self, *_):
            return ok(issue)

        def list_issue_comments(self, *_):
            return ok([])

    class Runner:
        def resolve_workflow(self, **_kwargs):
            return SimpleNamespace(
                dispatch_command="$minime-request-normalizer issue-12", workflow_sha256="wf"
            )

        async def run(self, **_kwargs):
            nonlocal calls
            calls += 1
            return AgentExecutionResult(
                exit_code=7,
                timed_out=False,
                stdout=[],
                stderr=["provider failure"],
                duration_ms=12,
                structured_output=[],
                diagnostic_output=[],
                structured_output_missing=True,
            )

        @staticmethod
        def observed_usage(_result):
            return None

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
    first, first_error = await coordinator._normalize_request_before_explore(
        active_run=run,
        project_id="project",
        repository="o/r",
        worktree_path=tmp_path,
        issue_number=12,
        issue_title="Solicitud",
        issue_body=issue["body"],
        provider="codex",
    )
    second, second_error = await coordinator._normalize_request_before_explore(
        active_run=run,
        project_id="project",
        repository="o/r",
        worktree_path=tmp_path,
        issue_number=12,
        issue_title="Solicitud",
        issue_body=issue["body"],
        provider="codex",
    )

    attempt = run.stop_details["normalization_attempt"]
    assert first is None and "verified result" in first_error
    assert second is None and "already recorded" in second_error
    assert calls == 1
    assert attempt["status"] == "FAILED"
    assert attempt["exit_code"] == 7
    assert attempt["structured_output_missing"] is True
    assert attempt["usage_status"] == "UNKNOWN"


@pytest.mark.asyncio
async def test_invalid_gherkin_is_quarantined_and_never_published(tmp_path: Path):
    issue = {"number": 13, "body": "C1: ordenar.", "repository_url": "/repos/o/r"}
    writes: list[str] = []
    run = OrchestrationRun(project_id="project", change_name="issue-13", base_sha="main")

    def ok(data):
        return ExternalActionResult(
            outcome=ExternalOutcome.SUCCESS,
            source_adapter="test",
            reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
            retry_safety=RetrySafety.SAFE,
            data=data,
        )

    class Github:
        def get_issue(self, *_):
            return ok(issue)

        def list_issue_comments(self, *_):
            return ok([])

        def comment_issue(self, *_args):
            writes.append("comment")
            return ok({})

        def update_issue_body(self, *_args, **_kwargs):
            writes.append("update")
            return ok(issue)

    class Runner:
        def resolve_workflow(self, **_kwargs):
            return SimpleNamespace(
                dispatch_command="$minime-request-normalizer issue-13", workflow_sha256="wf"
            )

        async def run(self, **_kwargs):
            payload = {
                "normalized_body": "Feature: incompleta\n\nScenario: Sin pasos",
                "criteria": ["C1"],
                "semantic_message": "La respuesta no cumple el formato requerido.",
                "api_key": "do-not-persist-this-secret",
            }
            return AgentExecutionResult(
                exit_code=0,
                timed_out=False,
                stdout=[],
                stderr=[],
                duration_ms=1,
                structured_output=[json.dumps(payload)],
                diagnostic_output=[],
            )

        @staticmethod
        def observed_usage(_result):
            return None

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
    result, error = await coordinator._normalize_request_before_explore(
        active_run=run,
        project_id="project",
        repository="o/r",
        worktree_path=tmp_path,
        issue_number=13,
        issue_title="Solicitud",
        issue_body=issue["body"],
        provider="codex",
    )

    assert result is None
    assert error == "Request normalization response was not structured."
    assert writes == []
    quarantine = run.stop_details["rejected_response"]
    assert quarantine["status"] == "QUARANTINED"
    assert quarantine["byte_length"] > 0
    assert quarantine["content"].startswith("{")
    assert "do-not-persist-this-secret" not in quarantine["content"]
    assert "[REDACTED]" in quarantine["content"]
    assert run.stop_details["normalization_attempt"]["response_status"] == "INVALID"


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
    assert (
        service.validate_f5_readiness(
            second,
            {"complete": True},
            project_type="GREENFIELD",
            profiles_observed=True,
            worktree_identity_verified=True,
            confinement_verified=True,
            github_binding_verified=True,
        )["status"]
        == "READY_FOR_F5_PREPARATION"
    )

    (target / ".agents/skills/minime-example/SKILL.md").write_text("changed", encoding="utf-8")
    with pytest.raises(CapabilityConflictError):
        service.install_greenfield(source, target)


def test_greenfield_capability_reconciliation_replaces_only_verified_predecessor(tmp_path: Path):
    source = tmp_path / "source"
    target = tmp_path / "target"
    source_file = source / ".agents/skills/minime-request-normalizer/SKILL.md"
    target_file = target / ".agents/skills/minime-request-normalizer/SKILL.md"
    source_file.parent.mkdir(parents=True)
    target_file.parent.mkdir(parents=True)
    source_file.write_text("normalized_body criteria semantic_message", encoding="utf-8")
    target_file.write_text("normalized_body criteria", encoding="utf-8")
    old_hash = hashlib.sha256(target_file.read_bytes()).hexdigest()
    service = CapabilityManifestService()
    profiles = {"thinking": {"agent_id": "codex", "skills": ["minime-request-normalizer"]}}
    authorization = GreenfieldCapabilityAuthorization(
        project_id="greenfield-project",
        project_type="GREENFIELD",
        onboarding_status="PREPARED",
        binding_project_id="greenfield-project",
        managed_repository_root=str(target),
        worktree_path=str(target),
        worktree_id="worktree-1",
        worktree_project_id="greenfield-project",
        worktree_state="CREATED",
        trusted_predecessor_hashes={".agents/skills/minime-request-normalizer/SKILL.md": old_hash},
    )

    result = service.reconcile_greenfield(
        source,
        target,
        profiles=profiles,
        expected_existing_hashes={".agents/skills/minime-request-normalizer/SKILL.md": old_hash},
        project_type="GREENFIELD",
        authorization=authorization,
    )

    assert result["replacements"][0]["from_sha256"] == old_hash
    assert target_file.read_text(encoding="utf-8") == source_file.read_text(encoding="utf-8")
    again = service.reconcile_greenfield(
        source,
        target,
        profiles=profiles,
        expected_existing_hashes={".agents/skills/minime-request-normalizer/SKILL.md": old_hash},
        project_type="GREENFIELD",
        authorization=authorization,
    )
    assert again["replacements"] == []


def test_greenfield_capability_reconciliation_preserves_unverified_conflict_and_brownfield(
    tmp_path: Path,
):
    source = tmp_path / "source"
    target = tmp_path / "target"
    source_file = source / ".agents/skills/minime-request-normalizer/SKILL.md"
    target_file = target / ".agents/skills/minime-request-normalizer/SKILL.md"
    source_file.parent.mkdir(parents=True)
    target_file.parent.mkdir(parents=True)
    source_file.write_text("new", encoding="utf-8")
    target_file.write_text("third-party", encoding="utf-8")
    service = CapabilityManifestService()
    profiles = {"thinking": {"agent_id": "codex", "skills": ["minime-request-normalizer"]}}
    authorization = GreenfieldCapabilityAuthorization(
        project_id="greenfield-project",
        project_type="GREENFIELD",
        onboarding_status="PREPARED",
        binding_project_id="greenfield-project",
        managed_repository_root=str(target),
        worktree_path=str(target),
        worktree_id="worktree-1",
        worktree_project_id="greenfield-project",
        worktree_state="CREATED",
        trusted_predecessor_hashes={".agents/skills/minime-request-normalizer/SKILL.md": "0" * 64},
    )

    with pytest.raises(CapabilityConflictError):
        service.reconcile_greenfield(
            source,
            target,
            profiles=profiles,
            expected_existing_hashes={
                ".agents/skills/minime-request-normalizer/SKILL.md": "0" * 64
            },
            project_type="GREENFIELD",
            authorization=authorization,
        )
    assert target_file.read_text(encoding="utf-8") == "third-party"
    with pytest.raises(CapabilityConflictError):
        service.reconcile_greenfield(
            source,
            target,
            profiles=profiles,
            expected_existing_hashes={},
            project_type="BROWNFIELD",
            authorization=authorization,
        )


def test_greenfield_reconciliation_rejects_unbound_worktree_and_untrusted_manifest(tmp_path: Path):
    source = tmp_path / "source"
    target = tmp_path / "target"
    source_file = source / ".agents/skills/minime-request-normalizer/SKILL.md"
    source_file.parent.mkdir(parents=True)
    target_file = target / ".agents/skills/minime-request-normalizer/SKILL.md"
    target_file.parent.mkdir(parents=True)
    source_file.write_text("new", encoding="utf-8")
    target_file.write_text("old", encoding="utf-8")
    old_hash = hashlib.sha256(target_file.read_bytes()).hexdigest()
    authorization = GreenfieldCapabilityAuthorization(
        project_id="project-a",
        project_type="GREENFIELD",
        onboarding_status="PREPARED",
        binding_project_id="project-b",
        managed_repository_root=str(target),
        worktree_path=str(target),
        worktree_id="worktree-1",
        worktree_project_id="project-a",
        worktree_state="CREATED",
        trusted_predecessor_hashes={".agents/skills/minime-request-normalizer/SKILL.md": old_hash},
    )
    with pytest.raises(CapabilityConflictError):
        CapabilityManifestService().reconcile_greenfield(
            source,
            target,
            profiles={"thinking": {"agent_id": "codex", "skills": ["minime-request-normalizer"]}},
            expected_existing_hashes={
                ".agents/skills/minime-request-normalizer/SKILL.md": old_hash
            },
            project_type="GREENFIELD",
            authorization=authorization,
        )
    assert target_file.read_text(encoding="utf-8") == "old"


def test_greenfield_reconciliation_rejects_predecessor_hash_not_from_authority(tmp_path: Path):
    source = tmp_path / "source"
    target = tmp_path / "target"
    source_file = source / ".agents/skills/minime-request-normalizer/SKILL.md"
    source_file.parent.mkdir(parents=True)
    target_file = target / ".agents/skills/minime-request-normalizer/SKILL.md"
    target_file.parent.mkdir(parents=True)
    source_file.write_text("new", encoding="utf-8")
    target_file.write_text("old", encoding="utf-8")
    old_hash = hashlib.sha256(target_file.read_bytes()).hexdigest()
    authorization = GreenfieldCapabilityAuthorization(
        project_id="project-a",
        project_type="GREENFIELD",
        onboarding_status="PREPARED",
        binding_project_id="project-a",
        managed_repository_root=str(target),
        worktree_path=str(target),
        worktree_id="worktree-1",
        worktree_project_id="project-a",
        worktree_state="CREATED",
        trusted_predecessor_hashes={".agents/skills/minime-request-normalizer/SKILL.md": "f" * 64},
    )
    with pytest.raises(CapabilityConflictError):
        CapabilityManifestService().reconcile_greenfield(
            source,
            target,
            profiles={"thinking": {"agent_id": "codex", "skills": ["minime-request-normalizer"]}},
            expected_existing_hashes={
                ".agents/skills/minime-request-normalizer/SKILL.md": old_hash
            },
            project_type="GREENFIELD",
            authorization=authorization,
        )
    assert target_file.read_text(encoding="utf-8") == "old"


def test_greenfield_reconciliation_is_atomic_when_replace_is_interrupted(
    tmp_path: Path, monkeypatch
):
    source = tmp_path / "source"
    target = tmp_path / "target"
    source_file = source / ".agents/skills/minime-request-normalizer/SKILL.md"
    target_file = target / ".agents/skills/minime-request-normalizer/SKILL.md"
    source_file.parent.mkdir(parents=True)
    target_file.parent.mkdir(parents=True)
    source_file.write_text("new", encoding="utf-8")
    target_file.write_text("old", encoding="utf-8")
    old_hash = hashlib.sha256(target_file.read_bytes()).hexdigest()
    authorization = GreenfieldCapabilityAuthorization(
        project_id="project-a",
        project_type="GREENFIELD",
        onboarding_status="PREPARED",
        binding_project_id="project-a",
        managed_repository_root=str(target),
        worktree_path=str(target),
        worktree_id="worktree-1",
        worktree_project_id="project-a",
        worktree_state="CREATED",
        trusted_predecessor_hashes={".agents/skills/minime-request-normalizer/SKILL.md": old_hash},
    )

    def interrupted_replace(*_args, **_kwargs):
        raise OSError("simulated interruption before atomic replace")

    monkeypatch.setattr(os, "replace", interrupted_replace)
    with pytest.raises(OSError, match="simulated interruption"):
        CapabilityManifestService().reconcile_greenfield(
            source,
            target,
            profiles={"thinking": {"agent_id": "codex", "skills": ["minime-request-normalizer"]}},
            expected_existing_hashes={
                ".agents/skills/minime-request-normalizer/SKILL.md": old_hash
            },
            project_type="GREENFIELD",
            authorization=authorization,
        )
    assert target_file.read_text(encoding="utf-8") == "old"
    assert list(target_file.parent.glob(f".{target_file.name}.*.minime-tmp")) == []


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
                stdout=[
                    '{"title":"feat(req-7): semantic (Addresses #7)","body":"## Evidence\\n\\nAddresses #7"}'
                ],
                stderr=[],
                duration_ms=1,
                structured_output=[
                    '{"title":"feat(req-7): semantic (Addresses #7)","body":"## Evidence\\n\\nAddresses #7"}'
                ],
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


@pytest.mark.asyncio
async def test_legacy_f5_budget_preflight_denial_is_archived_before_explicit_resume(tmp_path: Path):
    """A known pre-subprocess exception can be reconciled, never silently erased."""
    from tests.conftest import InMemoryPersistenceUnitOfWork

    previous = {
        "attempt_id": "0affa934-1bb7-4461-8af0-c9822b5d4772",
        "status": "FAILED",
        "provider": "codex",
        "workflow": "$minime-request-normalizer issue-173",
        "workflow_sha256": "verified-workflow-sha",
        "exit_code": None,
        "timed_out": None,
        "structured_output_present": False,
        "usage_status": "UNKNOWN",
        "usage": None,
        "diagnostic": "Budget policy/headroom is unavailable for project 'mini-me'.",
    }
    uow = InMemoryPersistenceUnitOfWork()
    run = OrchestrationRun(
        project_id="mini-me",
        change_name="gacela-05-ui-self-hosted",
        base_sha="main",
        stop_details={"issue_number": 173, "normalization_attempt": dict(previous)},
    )
    uow.orchestration_runs.save(run)

    github = MagicMock()
    github.get_issue.return_value = ExternalActionResult(
        outcome=ExternalOutcome.SUCCESS,
        source_adapter="test",
        reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
        retry_safety=RetrySafety.SAFE,
        data={"number": 173, "body": "Implement the F5 control center."},
    )
    github.list_issue_comments.return_value = ExternalActionResult(
        outcome=ExternalOutcome.SUCCESS,
        source_adapter="test",
        reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
        retry_safety=RetrySafety.SAFE,
        data=[],
    )
    runner = MagicMock()
    runner.resolve_workflow.return_value = SimpleNamespace(
        workflow_sha256="verified-workflow-sha",
        dispatch_command="$minime-request-normalizer issue-173",
    )
    runner.run = AsyncMock(side_effect=RuntimeError("test-only no-model stop"))
    coordinator = NativeOrchestrationCoordinator(
        uow_factory=lambda: uow,
        github_adapter=github,
        worktree_manager=object(),
        agent_runner=runner,
    )

    result, message = await coordinator._normalize_request_before_explore(
        active_run=run,
        project_id="mini-me",
        repository="silverberdi/mini-me",
        worktree_path=tmp_path,
        issue_number=173,
        issue_title="F5",
        issue_body="Implement the F5 control center.",
        provider="codex",
    )

    assert result is None and "dispatch failed" in message
    assert run.stop_details["normalization_attempt_history"] == [
        {**previous, "reconciliation": "CONFIRMED_PRE_DISPATCH_BUDGET_DENIAL"}
    ]
    assert run.stop_details["normalization_attempt"]["attempt_id"] != previous["attempt_id"]
    assert run.stop_details["normalization_attempt"]["status"] == "FAILED"
    assert run.run_id == uow.orchestration_runs.get_by_id(run.run_id).run_id
    runner.run.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("tamper", ["dispatch", "exit", "workflow", "output"])
async def test_f5_ambiguous_normalization_failure_cannot_reenter(tmp_path: Path, tamper: str):
    from tests.conftest import InMemoryPersistenceUnitOfWork

    previous = {
        "attempt_id": "prior",
        "status": "FAILED",
        "provider": "codex",
        "workflow": "$minime-request-normalizer issue-173",
        "workflow_sha256": "verified-workflow-sha",
        "exit_code": None,
        "timed_out": None,
        "structured_output_present": False,
        "usage_status": "UNKNOWN",
        "usage": None,
        "diagnostic": "Budget policy/headroom is unavailable for project 'mini-me'.",
    }
    if tamper == "dispatch":
        previous["dispatch_observed"] = True
    elif tamper == "exit":
        previous["exit_code"] = 1
    elif tamper == "workflow":
        previous["workflow_sha256"] = "wrong-hash"
    else:
        response = tmp_path / ".minime" / "request-normalization-fixed-run.json"
        response.parent.mkdir(parents=True)
        response.write_text("ambiguous output", encoding="utf-8")

    uow = InMemoryPersistenceUnitOfWork()
    run = OrchestrationRun(
        run_id="fixed-run",
        project_id="mini-me",
        change_name="gacela-05-ui-self-hosted",
        base_sha="main",
        stop_details={"normalization_attempt": previous},
    )
    uow.orchestration_runs.save(run)
    runner = MagicMock()
    runner.resolve_workflow.return_value = SimpleNamespace(
        workflow_sha256="verified-workflow-sha",
        dispatch_command="$minime-request-normalizer issue-173",
    )
    runner.run = AsyncMock()
    coordinator = NativeOrchestrationCoordinator(
        uow_factory=lambda: uow,
        github_adapter=MagicMock(),
        worktree_manager=object(),
        agent_runner=runner,
    )
    result, message = await coordinator._normalize_request_before_explore(
        active_run=run,
        project_id="mini-me",
        repository="silverberdi/mini-me",
        worktree_path=tmp_path,
        issue_number=173,
        issue_title="F5",
        issue_body="F5 body",
        provider="codex",
    )
    assert result is None
    assert "already recorded" in message or "mismatched evidence" in message
    assert run.stop_details["normalization_attempt"] == previous
    assert "normalization_attempt_history" not in run.stop_details
    runner.run.assert_not_awaited()


def test_issue_patch_rejects_if_match_and_succeeds_with_read_verify():
    """GitHub REST rejects conditional unsafe PATCH; our adapter must omit it."""
    original = "F5 original body"
    desired = "Feature: F5\n\nScenario: UI\n  Given access\n  When opened\n  Then it renders"
    issue = {"number": 173, "body": original}
    patches = []

    def handler(request):
        if request.method == "GET" and request.url.path.endswith("/issues/173"):
            return httpx.Response(200, json=issue, headers={"etag": 'W/"weak-etag"'})
        if request.method == "PATCH" and request.url.path.endswith("/issues/173"):
            patches.append(request)
            if "if-match" in request.headers:
                return httpx.Response(
                    400,
                    json={
                        "errors": ["Conditional request headers are not allowed in unsafe requests"]
                    },
                )
            issue["body"] = json.loads(request.content)["body"]
            return httpx.Response(200, json=issue)
        return httpx.Response(404)

    adapter = GitHubAdapter(auth=StaticAuth(handler))
    first = adapter.update_issue_body("o/r", 173, desired, expected_body=original)
    second = adapter.update_issue_body("o/r", 173, desired, expected_body=original)

    assert first.outcome is ExternalOutcome.SUCCESS
    assert second.outcome is ExternalOutcome.SUCCESS
    assert second.observed_evidence["already_published"] is True
    assert issue["body"] == desired
    assert len(patches) == 1
    assert "if-match" not in patches[0].headers


def test_issue_patch_refuses_changed_body_without_remote_write():
    original = "Original F5 requirement"
    remote = {"number": 173, "body": "Human edited requirement"}
    patch_attempts = []

    def handler(request):
        if request.method == "GET" and request.url.path.endswith("/issues/173"):
            return httpx.Response(200, json=remote)
        if request.method == "PATCH":
            patch_attempts.append(request)
            return httpx.Response(200, json=remote)
        return httpx.Response(404)

    adapter = GitHubAdapter(auth=StaticAuth(handler))
    result = adapter.update_issue_body("o/r", 173, "Feature: F5", expected_body=original)

    assert result.outcome is ExternalOutcome.FAILURE
    assert result.reason_code is ExternalReasonCode.CONFLICT
    assert patch_attempts == []


def test_issue_patch_denies_missing_precondition_or_unobservable_issue():
    patch_attempts = []

    def handler(request):
        if request.method == "GET":
            return httpx.Response(503)
        if request.method == "PATCH":
            patch_attempts.append(request)
        return httpx.Response(503)

    adapter = GitHubAdapter(auth=StaticAuth(handler))
    without_expected = adapter.update_issue_body("o/r", 173, "Feature: F5")
    unreadable = adapter.update_issue_body(
        "o/r", 173, "Feature: F5", expected_body="Original requirement"
    )
    assert without_expected.outcome is ExternalOutcome.FAILURE
    assert unreadable.outcome is ExternalOutcome.UNKNOWN
    assert patch_attempts == []


def test_issue_patch_requires_verifiable_response_body():
    issue = {"number": 173, "body": "Original requirement"}
    patch_attempts = []

    def handler(request):
        if request.method == "GET" and request.url.path.endswith("/issues/173"):
            return httpx.Response(200, json=issue)
        if request.method == "PATCH" and request.url.path.endswith("/issues/173"):
            patch_attempts.append(request)
            return httpx.Response(200, json={"number": 173, "body": "Unexpected remote result"})
        return httpx.Response(404)

    result = GitHubAdapter(auth=StaticAuth(handler)).update_issue_body(
        "o/r", 173, "Feature: F5", expected_body="Original requirement"
    )
    assert result.outcome is ExternalOutcome.UNKNOWN
    assert len(patch_attempts) == 1


def test_normalization_refuses_source_edit_after_provenance_before_patch():
    original = "F5 original requirement"
    normalized = (
        "Feature: F5\n\nScenario: Dashboard\n"
        "  Given an operator\n  When the page loads\n  Then the dashboard is visible"
    )
    remote = {"number": 173, "body": original}
    issue_reads = 0
    patch_attempts = []
    comments = []

    def handler(request):
        nonlocal issue_reads
        if request.method == "GET" and request.url.path.endswith("/issues/173"):
            issue_reads += 1
            if issue_reads == 2:
                remote["body"] = "Changed by an operator while publishing"
            return httpx.Response(200, json=remote)
        if request.method == "GET" and request.url.path.endswith("/issues/173/comments"):
            return httpx.Response(200, json=comments)
        if request.method == "POST" and request.url.path.endswith("/issues/173/comments"):
            comment = {"id": len(comments) + 1, "body": json.loads(request.content)["body"]}
            comments.append(comment)
            return httpx.Response(201, json=comment)
        if request.method == "PATCH":
            patch_attempts.append(request)
            return httpx.Response(500)
        return httpx.Response(404)

    service = RequestNormalizationService(GitHubAdapter(auth=StaticAuth(handler)))
    with pytest.raises(RequestNormalizationError, match="not confirmed remotely"):
        service.publish("o/r", 173, "run-f5", NormalizedRequest(original, normalized, False))
    assert issue_reads >= 2
    assert patch_attempts == []
    assert remote["body"] == "Changed by an operator while publishing"
    assert len(comments) == 1
