"""Tests for 004 DeepSeek Direct independent audit."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from minime.api.app import app, get_uow
from minime.cli.main import app as cli_app
from minime.db.models import Base
from minime.domain.enums import (
    AuditFindingSeverity,
    AuditRiskLevel,
    AuditStatus,
    ChangeStatus,
    EventType,
    JobStatus,
    ReadinessState,
    ReviewStatus,
    ReviewVerdict,
)
from minime.domain.models import (
    AuditFinding,
    AuditRecord,
    Change,
    Job,
    Project,
    Review,
)
from minime.services.audit_verdict_parser import (
    MalformedAuditOutputError,
    parse_audit_result,
)
from minime.services.deepseek_auditor_runner import (
    DeepSeekAuditorRunner,
    MockAuditorRunner,
    build_audit_prompt,
)
from minime.services.execution_pipeline import ExecutionPipelineService
from minime.services.implementer_runner import MockImplementerRunner
from minime.services.reviewer_runner import MockReviewerRunner
from minime.services.worktree_manager import WorktreeInfo


class GitFakeWorktreeManager:
    def __init__(self, root: Path, symlink: bool = False, mutate_after_current_sha: bool = False):
        self.root = root
        self.symlink = symlink
        self.mutate_after_current_sha = mutate_after_current_sha

    async def create_worktree(
        self, job_id: str, change_name: str, base_branch: str
    ) -> WorktreeInfo:
        del change_name, base_branch
        path = self.root / ".minime" / "worktrees" / job_id
        path.mkdir(parents=True, exist_ok=True)
        if (self.root / "openspec").exists():
            shutil.copytree(self.root / "openspec", path / "openspec")
        subprocess.run(["git", "init"], cwd=str(path), check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=str(path), check=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"], cwd=str(path), check=True
        )
        subprocess.run(["git", "add", "."], cwd=str(path), check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "--allow-empty", "-m", "init"],
            cwd=str(path),
            check=True,
            capture_output=True,
        )
        subprocess.run(["git", "branch", "-M", "main"], cwd=str(path), check=True)
        subprocess.run(
            ["git", "update-ref", "refs/remotes/origin/main", "HEAD"],
            cwd=str(path),
            check=True,
        )
        if self.symlink:
            os.symlink("/tmp", path / "tmp_escape", target_is_directory=True)
        head_sha = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(path),
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        return WorktreeInfo(path=path, branch_name=f"minime/test-{job_id}", base_sha=head_sha)

    async def current_sha(self, worktree_path: str | Path) -> str:
        path = Path(worktree_path)
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(path),
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        if self.mutate_after_current_sha:
            (path / "auditor-mutation.txt").write_text("dirty", encoding="utf-8")
        return sha

    async def cleanup_worktree(self, job_id: str) -> None:
        del job_id


def seed_ready_change(
    uow,
    tmp_path: Path,
    implementer: str = "codex",
    reviewer: str = "antigravity",
) -> None:
    change_name = "synthetic-audit-change"
    change_dir = tmp_path / "openspec" / "changes" / change_name
    (change_dir / "specs" / "feature").mkdir(parents=True, exist_ok=True)
    (change_dir / "proposal.md").write_text("# Proposal\n", encoding="utf-8")
    (change_dir / "design.md").write_text("# Design\n", encoding="utf-8")
    (change_dir / "tasks.md").write_text("# Tasks\n- [x] 1.1 Done\n", encoding="utf-8")
    (change_dir / "specs" / "feature" / "spec.md").write_text("# Spec\n", encoding="utf-8")
    uow.projects.save(
        Project(
            project_id="audit-project",
            display_name="Audit Project",
            repository="silverberdi/audit-project",
            base_branch="main",
            implementer=implementer,
            reviewer=reviewer,
            checks=[{"name": "ok", "command": f"{sys.executable} -c 'print(1)'"}],
        )
    )
    uow.changes.save(
        Change(
            project_id="audit-project",
            name=change_name,
            status=ChangeStatus.READY,
            last_readiness_status=ReadinessState.READY,
        )
    )


def test_audit_result_parser_strict_single_payload():
    valid = parse_audit_result(
        '```json\n{"risk":"medium","summary":"Looks acceptable.","findings":[]}\n```'
    )
    assert valid.risk == AuditRiskLevel.MEDIUM
    assert valid.findings == []

    bad_cases = [
        "",
        "Risk is low",
        '{"risk":"low","summary":"ok","findings":[]}\n{"risk":"low","summary":"ok","findings":[]}',
        '```json\n{"risk":"low","summary":"ok","findings":[]}\n```\nprose',
        '{"risk":"unknown","summary":"ok","findings":[]}',
        '{"risk":"low","summary":"","findings":[]}',
        '{"risk":"low","summary":"ok","findings":[],"extra":true}',
        '{"risk":"low","summary":"ok","findings":[{"severity":"critical","category":"security","message":"bad","extra":true}]}',
    ]
    for case in bad_cases:
        with pytest.raises(MalformedAuditOutputError):
            parse_audit_result(case)


@pytest.mark.asyncio
async def test_deepseek_runner_direct_endpoint_and_secret_redaction(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-secret")
    runner = DeepSeekAuditorRunner(endpoint="https://openrouter.ai/api/v1/chat/completions")
    with pytest.raises(ValueError, match="DeepSeek"):
        await runner.run(Path("."), "prompt", 1)

    missing = DeepSeekAuditorRunner(
        api_key="", endpoint="https://api.deepseek.com/chat/completions"
    )
    result = await missing.run(Path("."), "prompt", 1)
    assert result.exit_code == 1
    assert "DEEPSEEK_API_KEY" in (result.error_message or "")

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.deepseek.com"
        assert request.headers["authorization"] == "Bearer sk-test-secret"
        return httpx.Response(500, text="token=sk-test-secret")

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://api.deepseek.com",
    )
    runner = DeepSeekAuditorRunner(api_key="sk-test-secret", client=client)
    result = await runner.run(Path("."), "prompt", 1)
    await client.aclose()
    assert result.exit_code == 500
    assert "sk-test-secret" not in (result.error_message or "")
    assert "[REDACTED]" in (result.error_message or "")


def test_build_audit_prompt_includes_immutable_context(tmp_path):
    change_dir = tmp_path / "openspec" / "changes" / "c1"
    (change_dir / "specs" / "feature").mkdir(parents=True)
    (change_dir / "proposal.md").write_text("# Proposal", encoding="utf-8")
    (change_dir / "design.md").write_text("# Design", encoding="utf-8")
    (change_dir / "tasks.md").write_text("- [x] Done", encoding="utf-8")
    (change_dir / "specs" / "feature" / "spec.md").write_text("# Spec", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=str(tmp_path), check=True, capture_output=True)
    project = Project(project_id="p1", display_name="P", repository="owner/repo")
    review = Review(
        review_id="r1",
        job_id="j1",
        project_id="p1",
        change_name="c1",
        reviewer_role="antigravity",
        candidate_sha="candidate",
        base_sha="base",
        status=ReviewStatus.REVIEW_COMPLETED,
        verdict=ReviewVerdict.READY_TO_MERGE,
    )
    prompt = build_audit_prompt(
        project,
        "c1",
        "j1",
        "a1",
        "candidate",
        "base",
        tmp_path,
        [],
        review,
        [],
    )
    assert "a1" in prompt
    assert "candidate" in prompt
    assert "READY_TO_MERGE" in prompt
    assert "independent read-only contradiction" in prompt


@pytest.mark.asyncio
async def test_audit_pipeline_low_risk_ready_to_merge(in_memory_uow, tmp_path):
    seed_ready_change(in_memory_uow, tmp_path)
    service = ExecutionPipelineService(
        in_memory_uow,
        project_root=tmp_path,
        implementer_runner=MockImplementerRunner(),
        reviewer_runner=MockReviewerRunner(
            stdout=['{"verdict":"READY_TO_MERGE","summary":"ok","findings":[]}']
        ),
        auditor_runner=MockAuditorRunner(
            output=['{"risk":"low","summary":"No material risk.","findings":[]}']
        ),
        worktree_manager=GitFakeWorktreeManager(tmp_path),
    )
    job = await service.run_job("audit-project", "synthetic-audit-change")
    assert job.status == JobStatus.READY_TO_MERGE
    audit = in_memory_uow.audits.get_by_job_id(job.job_id)
    assert audit is not None
    assert audit.status == AuditStatus.AUDIT_COMPLETED
    assert audit.risk == AuditRiskLevel.LOW
    metrics = in_memory_uow.metrics.list_facts(project_id="audit-project")
    assert "audit_duration_ms" in {m.metric_name for m in metrics}


@pytest.mark.asyncio
async def test_audit_pipeline_high_finding_blocks_even_with_low_risk(in_memory_uow, tmp_path):
    seed_ready_change(in_memory_uow, tmp_path)
    service = ExecutionPipelineService(
        in_memory_uow,
        project_root=tmp_path,
        implementer_runner=MockImplementerRunner(),
        reviewer_runner=MockReviewerRunner(
            stdout=['{"verdict":"READY_TO_MERGE","summary":"ok","findings":[]}']
        ),
        auditor_runner=MockAuditorRunner(
            output=[
                '{"risk":"low","summary":"Risk understated.","findings":[{"severity":"high","category":"security","message":"Blocking issue"}]}'
            ]
        ),
        worktree_manager=GitFakeWorktreeManager(tmp_path),
    )
    job = await service.run_job("audit-project", "synthetic-audit-change")
    assert job.status == JobStatus.AUDIT_BLOCKED
    audit = in_memory_uow.audits.get_by_job_id(job.job_id)
    assert audit is not None
    assert audit.status == AuditStatus.AUDIT_BLOCKED
    findings = in_memory_uow.audit_findings.list_by_audit(audit.audit_id)
    assert findings[0].severity == AuditFindingSeverity.HIGH


@pytest.mark.asyncio
async def test_changes_required_prevents_audit(in_memory_uow, tmp_path):
    seed_ready_change(in_memory_uow, tmp_path)
    service = ExecutionPipelineService(
        in_memory_uow,
        project_root=tmp_path,
        implementer_runner=MockImplementerRunner(),
        reviewer_runner=MockReviewerRunner(
            stdout=[
                '{"verdict":"CHANGES_REQUIRED","summary":"bad","findings":[{"severity":"BLOCKER","violated_requirement":"r","expected_correction":"c"}]}'
            ]
        ),
        auditor_runner=MockAuditorRunner(output=["should not run"]),
        worktree_manager=GitFakeWorktreeManager(tmp_path),
    )
    job = await service.run_job("audit-project", "synthetic-audit-change")
    assert job.status == JobStatus.CHANGES_REQUIRED
    assert in_memory_uow.audits.get_by_job_id(job.job_id) is None


@pytest.mark.asyncio
async def test_audit_timeout_malformed_symlink_and_mutation_fail_safely(in_memory_uow, tmp_path):
    seed_ready_change(in_memory_uow, tmp_path)
    base_kwargs = {
        "uow": in_memory_uow,
        "project_root": tmp_path,
        "implementer_runner": MockImplementerRunner(),
        "reviewer_runner": MockReviewerRunner(
            stdout=['{"verdict":"READY_TO_MERGE","summary":"ok","findings":[]}']
        ),
    }
    service = ExecutionPipelineService(
        **base_kwargs,
        auditor_runner=MockAuditorRunner(timed_out=True),
        worktree_manager=GitFakeWorktreeManager(tmp_path),
    )
    job = await service.run_job("audit-project", "synthetic-audit-change")
    assert job.status == JobStatus.FAILED
    assert in_memory_uow.audits.get_by_job_id(job.job_id).status == AuditStatus.AUDIT_TIMED_OUT

    seed_ready_change(in_memory_uow, tmp_path)
    service = ExecutionPipelineService(
        **base_kwargs,
        auditor_runner=MockAuditorRunner(output=["not json"]),
        worktree_manager=GitFakeWorktreeManager(tmp_path),
    )
    job = await service.run_job("audit-project", "synthetic-audit-change")
    assert job.status == JobStatus.FAILED
    assert in_memory_uow.audits.get_by_job_id(job.job_id).status == AuditStatus.AUDIT_FAILED

    seed_ready_change(in_memory_uow, tmp_path)
    service = ExecutionPipelineService(
        **base_kwargs,
        auditor_runner=MockAuditorRunner(output=['{"risk":"low","summary":"ok","findings":[]}']),
        worktree_manager=GitFakeWorktreeManager(tmp_path, symlink=True),
    )
    job = await service.run_job("audit-project", "synthetic-audit-change")
    assert job.status == JobStatus.FAILED
    assert "prohibited symlink" in (job.error_message or "")

    seed_ready_change(in_memory_uow, tmp_path)
    service = ExecutionPipelineService(
        **base_kwargs,
        auditor_runner=MockAuditorRunner(output=['{"risk":"low","summary":"ok","findings":[]}']),
        worktree_manager=GitFakeWorktreeManager(tmp_path, mutate_after_current_sha=True),
    )
    job = await service.run_job("audit-project", "synthetic-audit-change")
    assert job.status == JobStatus.FAILED
    events = in_memory_uow.events.list_events(project_id="audit-project")
    assert any(
        e.event_type in {EventType.CANDIDATE_SHA_MISMATCH, EventType.UNAUTHORIZED_REVIEWER_MUTATION}
        for e in events
    )


def test_audit_models_metadata_and_invalid_transition(in_memory_uow):
    tables = Base.metadata.tables
    assert "audits" in tables
    assert "audit_findings" in tables
    audit = AuditRecord(
        audit_id="a1",
        job_id="j1",
        project_id="p1",
        change_name="c1",
        candidate_sha="candidate",
        base_sha="base",
        status=AuditStatus.AUDIT_COMPLETED,
    )
    in_memory_uow.audits.save(audit)
    with pytest.raises(ValueError):
        in_memory_uow.audits.transition("a1", AuditStatus.AUDIT_RUNNING.value)


def test_api_and_cli_audit_observability(in_memory_uow, monkeypatch):
    job = Job(
        job_id="job-audit",
        project_id="p1",
        change_name="c1",
        implementer_role="codex",
        status=JobStatus.AUDIT_BLOCKED,
        candidate_sha="candidate",
        base_sha="base",
    )
    audit = AuditRecord(
        audit_id="audit-1",
        job_id="job-audit",
        project_id="p1",
        change_name="c1",
        candidate_sha="candidate",
        base_sha="base",
        status=AuditStatus.AUDIT_BLOCKED,
        risk=AuditRiskLevel.HIGH,
        summary="High risk",
    )
    finding = AuditFinding(
        finding_id="af-1",
        audit_id="audit-1",
        severity=AuditFindingSeverity.HIGH,
        category="security",
        message="token=supersecret",
        file="src/app.py",
        location="10",
    )
    in_memory_uow.jobs.save(job)
    in_memory_uow.audits.save(audit)
    in_memory_uow.audit_findings.save(finding)

    app.dependency_overrides[get_uow] = lambda: in_memory_uow
    client = TestClient(app)
    res = client.get("/jobs/job-audit/audit")
    assert res.status_code == 200
    assert res.json()["risk"] == "high"
    assert "[REDACTED]" in res.json()["findings"][0]["message"]
    app.dependency_overrides.clear()

    @contextmanager
    def mock_session():
        yield None

    monkeypatch.setattr("minime.cli.main.db_manager.session", mock_session)
    monkeypatch.setattr(
        "minime.cli.main.PostgresPersistenceUnitOfWork", lambda session: in_memory_uow
    )
    result = CliRunner().invoke(cli_app, ["jobs", "audit", "job-audit"])
    assert result.exit_code == 0
    assert "Audit ID: audit-1" in result.output
    assert "high" in result.output
