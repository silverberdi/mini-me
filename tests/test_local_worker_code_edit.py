"""Targeted tests for local worker code-edit execution, patch policy, and SDLC isolation."""

from __future__ import annotations

import json
import os
import subprocess

import pytest

from minime.domain.enums import (
    OrchestrationStage,
    ProviderResultClass,
)
from minime.domain.models import (
    Job,
    OrchestrationRun,
    ProjectManagedRepositoryBinding,
    utc_now,
)
from minime.local_worker.harness import parse_structured_result
from minime.local_worker.models import (
    LocalResultKind,
    LocalTaskClass,
    LocalTaskEnvelope,
    LocalValidationVerdict,
    PreflightResult,
    PreflightStatus,
    ValidationResult,
)
from minime.local_worker.ollama_adapter import OllamaGenerateResponse
from minime.local_worker.patch_applier import (
    LocalPatchApplier,
    validate_patch_policy,
)
from minime.local_worker.service import SYSTEM_PROMPT, LocalWorkerService
from minime.services.worktree_manager import WorktreeInfo, WorktreeManager


@pytest.fixture
def stage_c_environment(tmp_path):
    """Fixture establishing real Stage C UoW, managed repository, worktree parent, and binding."""
    base_dir = tmp_path / "stage_c_base"
    base_dir.mkdir()

    repo_dir = base_dir / "managed_repo"
    repo_dir.mkdir()
    worktrees_dir = base_dir / "worktrees"
    worktrees_dir.mkdir()
    runtime_dir = base_dir / "runtime_app"
    runtime_dir.mkdir()

    # Git init managed repo
    subprocess.run(["git", "init", "-b", "main"], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.name", "Test User"], cwd=repo_dir, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo_dir,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "remote", "add", "origin", "https://github.com/silverberdi/mini-me"],
        cwd=repo_dir,
        check=True,
        capture_output=True,
    )

    foo_path = repo_dir / "foo.py"
    foo_path.write_text("def foo():\n    return 42\n")
    test_path = repo_dir / "tests" / "test_foo.py"
    test_path.parent.mkdir()
    test_path.write_text("def test_foo():\n    assert foo() == 42\n")

    marker_path = repo_dir / ".minime-managed-project.json"
    marker_path.write_text(
        json.dumps(
            {
                "project_id": "mini-me",
                "canonical_repository_identity": "github.com/silverberdi/mini-me",
                "repository": "github.com/silverberdi/mini-me",
            }
        )
    )

    subprocess.run(["git", "add", "."], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"], cwd=repo_dir, check=True, capture_output=True
    )

    res_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo_dir, capture_output=True, text=True, check=True
    )
    base_sha = res_sha.stdout.strip()

    from tests.test_stage_c_isolation import MockUOW

    uow = MockUOW()

    binding = ProjectManagedRepositoryBinding(
        project_id="mini-me",
        canonical_repository_identity="github.com/silverberdi/mini-me",
        managed_repository_root=str(repo_dir),
        worktree_parent_dir=str(worktrees_dir),
        remote_name="origin",
        is_valid=True,
    )
    uow.project_managed_repository_bindings.save(binding)

    return {
        "uow": uow,
        "repo_dir": repo_dir,
        "worktrees_dir": worktrees_dir,
        "runtime_dir": runtime_dir,
        "base_sha": base_sha,
    }


async def create_authorized_worktree(
    stage_c_env: dict, job_id: str, run_id: str, change_name: str = "local-edit"
) -> WorktreeInfo:
    uow = stage_c_env["uow"]
    project_id = "mini-me"

    job = Job(
        job_id=job_id,
        project_id=project_id,
        change_name=change_name,
        implementer_role="local_qwen",
    )
    uow.jobs.save(job)

    run = OrchestrationRun(
        run_id=run_id,
        active_job_id=job_id,
        project_id=project_id,
        change_name=change_name,
        base_sha=stage_c_env["base_sha"],
        current_stage=OrchestrationStage.IMPLEMENTING,
        resumable_stage=OrchestrationStage.IMPLEMENTING,
        is_active=True,
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    uow.orchestration_runs.save(run)

    wt_mgr = WorktreeManager(project_root=stage_c_env["repo_dir"], uow=uow)
    return await wt_mgr.create_worktree(
        job_id=job_id,
        change_name=change_name,
        base_branch="main",
        project_id=project_id,
        branch_name=f"feature/{job_id}",
        run_id=run_id,
    )


# B4: PROMPT AND PARSER CONTRACT TESTS
def test_system_prompt_includes_patch_schema():
    assert '"patch":"<unified diff>"|null' in SYSTEM_PROMPT


def test_parse_structured_result_with_patch():
    raw = (
        '{"kind":"CHANGES_PROPOSED","summary":"add bar","files_changed":["foo.py"],'
        '"patch":"--- a/foo.py\\n+++ b/foo.py\\n@@ -1 +1 @@\\n-old\\n+new\\n",'
        '"confidence":0.9,"escalation_required":false,"escalation_reason":"","next_action":"apply"}'
    )
    res = parse_structured_result(raw)
    assert res.kind == LocalResultKind.CHANGES_PROPOSED
    assert res.patch is not None
    assert "old" in res.patch


# B5: PATCH POLICY CONTRACT TESTS
def test_no_change_justified_with_null_patch_valid():
    envelope = LocalTaskEnvelope(
        role="local_worker",
        task_class=LocalTaskClass.SMALL_CODE_FIX,
        allowed_files=["foo.py"],
        instruction="Check foo",
    )
    decision = validate_patch_policy(None, envelope, kind=LocalResultKind.NO_CHANGE_JUSTIFIED)
    assert decision.valid is True


def test_no_change_justified_with_patch_fails_closed():
    envelope = LocalTaskEnvelope(
        role="local_worker",
        task_class=LocalTaskClass.SMALL_CODE_FIX,
        allowed_files=["foo.py"],
        instruction="Check foo",
    )
    decision = validate_patch_policy(
        "some patch", envelope, kind=LocalResultKind.NO_CHANGE_JUSTIFIED
    )
    assert decision.valid is False
    assert "must not supply a patch" in decision.reason


def test_changes_proposed_empty_patch_fails_closed():
    envelope = LocalTaskEnvelope(
        role="local_worker",
        task_class=LocalTaskClass.SMALL_CODE_FIX,
        allowed_files=["foo.py"],
        instruction="Fix foo",
    )
    decision = validate_patch_policy("", envelope, kind=LocalResultKind.CHANGES_PROPOSED)
    assert decision.valid is False
    assert "requires a non-empty patch" in decision.reason


def test_patch_outside_allowed_files_refused():
    envelope = LocalTaskEnvelope(
        role="local_worker",
        task_class=LocalTaskClass.SMALL_CODE_FIX,
        allowed_files=["foo.py"],
        instruction="Fix foo",
    )
    patch_str = "--- a/bar.py\n+++ b/bar.py\n@@ -1 +1 @@\n-old\n+new\n"
    decision = validate_patch_policy(patch_str, envelope)
    assert decision.valid is False
    assert "not in allowed_files" in decision.reason


def test_path_traversal_refused():
    envelope = LocalTaskEnvelope(
        role="local_worker",
        task_class=LocalTaskClass.SMALL_CODE_FIX,
        allowed_files=["foo.py"],
        instruction="Fix foo",
    )
    patch_str = "--- a/../etc/passwd\n+++ b/../etc/passwd\n@@ -1 +1 @@\n-old\n+new\n"
    decision = validate_patch_policy(patch_str, envelope)
    assert decision.valid is False
    assert "Path traversal" in decision.reason


def test_absolute_path_refused():
    envelope = LocalTaskEnvelope(
        role="local_worker",
        task_class=LocalTaskClass.SMALL_CODE_FIX,
        allowed_files=["foo.py"],
        instruction="Fix foo",
    )
    patch_str = "--- a//etc/shadow\n+++ b//etc/shadow\n@@ -1 +1 @@\n-old\n+new\n"
    decision = validate_patch_policy(patch_str, envelope)
    assert decision.valid is False
    assert "Absolute path" in decision.reason


def test_forbidden_surface_refused():
    envelope = LocalTaskEnvelope(
        role="local_worker",
        task_class=LocalTaskClass.SMALL_CODE_FIX,
        allowed_files=["src/minime/services/scheduler_service.py"],
        forbidden_files=["src/minime/services/scheduler_service.py"],
        instruction="Modify scheduler",
    )
    patch_str = (
        "--- a/src/minime/services/scheduler_service.py\n"
        "+++ b/src/minime/services/scheduler_service.py\n"
        "@@ -1 +1 @@\n"
        "-old\n"
        "+new\n"
    )
    decision = validate_patch_policy(patch_str, envelope)
    assert decision.valid is False
    assert "in forbidden_files" in decision.reason


# B6: 10 REQUIRED INTEGRATION REFUSAL/SUCCESS TESTS USING STAGE C MACHINERY
def test_b6_1_no_uow_or_authority_context_refused():
    with pytest.raises(ValueError, match="mandatory"):
        LocalPatchApplier(uow=None)


def test_b6_2_plain_git_repo_not_registered_refused(stage_c_environment, tmp_path):
    plain_repo = tmp_path / "plain_repo"
    plain_repo.mkdir()
    subprocess.run(["git", "init"], cwd=plain_repo, check=True, capture_output=True)

    envelope = LocalTaskEnvelope(
        role="local_worker",
        task_class=LocalTaskClass.SMALL_CODE_FIX,
        allowed_files=["foo.py"],
        instruction="Fix foo",
    )
    patch_str = "--- a/foo.py\n+++ b/foo.py\n@@ -1 +1 @@\n-old\n+new\n"

    applier = LocalPatchApplier(uow=stage_c_environment["uow"])
    res = applier.apply_patch(
        worktree_path=plain_repo,
        envelope=envelope,
        patch=patch_str,
        project_id="mini-me",
        job_id="job-plain",
    )
    assert res.success is False
    assert res.applied is False
    assert "Workspace mutation denied" in res.error or "missing" in res.error


def test_b6_3_runtime_checkout_refused(stage_c_environment, monkeypatch):
    monkeypatch.setenv("MINIME_RUNTIME_ROOT", str(stage_c_environment["runtime_dir"]))
    envelope = LocalTaskEnvelope(
        role="local_worker",
        task_class=LocalTaskClass.SMALL_CODE_FIX,
        allowed_files=["foo.py"],
        instruction="Fix foo",
    )
    patch_str = "--- a/foo.py\n+++ b/foo.py\n@@ -1 +1 @@\n-old\n+new\n"

    applier = LocalPatchApplier(uow=stage_c_environment["uow"])
    res = applier.apply_patch(
        worktree_path=stage_c_environment["runtime_dir"],
        envelope=envelope,
        patch=patch_str,
        project_id="mini-me",
        job_id="job-runtime",
    )
    assert res.success is False
    assert "runtime checkout" in res.error.lower() or "runtime root" in res.error.lower()


def test_b6_4_managed_repository_refused(stage_c_environment, monkeypatch):
    monkeypatch.setenv("MINIME_MANAGED_ROOT", str(stage_c_environment["repo_dir"]))
    envelope = LocalTaskEnvelope(
        role="local_worker",
        task_class=LocalTaskClass.SMALL_CODE_FIX,
        allowed_files=["foo.py"],
        instruction="Fix foo",
    )
    patch_str = "--- a/foo.py\n+++ b/foo.py\n@@ -1 +1 @@\n-old\n+new\n"

    applier = LocalPatchApplier(uow=stage_c_environment["uow"])
    res = applier.apply_patch(
        worktree_path=stage_c_environment["repo_dir"],
        envelope=envelope,
        patch=patch_str,
        project_id="mini-me",
        job_id="job-managed",
    )
    assert res.success is False
    assert "managed repository" in res.error.lower() or "Workspace mutation denied" in res.error


def test_b6_5_execution_worktree_path_missing_durable_ownership_refused(stage_c_environment):
    unowned_wt = stage_c_environment["worktrees_dir"] / "job-unowned"
    unowned_wt.mkdir()
    subprocess.run(["git", "init"], cwd=unowned_wt, check=True, capture_output=True)

    envelope = LocalTaskEnvelope(
        role="local_worker",
        task_class=LocalTaskClass.SMALL_CODE_FIX,
        allowed_files=["foo.py"],
        instruction="Fix foo",
    )
    patch_str = "--- a/foo.py\n+++ b/foo.py\n@@ -1 +1 @@\n-old\n+new\n"

    applier = LocalPatchApplier(uow=stage_c_environment["uow"])
    res = applier.apply_patch(
        worktree_path=unowned_wt,
        envelope=envelope,
        patch=patch_str,
        project_id="mini-me",
        job_id="job-unowned",
    )
    assert res.success is False
    assert (
        "Durable OrchestrationWorktreeOwnership missing" in res.error
        or "Workspace mutation denied" in res.error
    )


@pytest.mark.asyncio
async def test_b6_6_wrong_job_id_ownership_refused(stage_c_environment):
    uow = stage_c_environment["uow"]
    wt_info = await create_authorized_worktree(
        stage_c_environment, job_id="job-100", run_id="run-100"
    )

    envelope = LocalTaskEnvelope(
        role="local_worker",
        task_class=LocalTaskClass.SMALL_CODE_FIX,
        allowed_files=["foo.py"],
        instruction="Fix foo",
    )
    patch_str = "--- a/foo.py\n+++ b/foo.py\n@@ -1,2 +1,2 @@\n def foo():\n-    return 42\n+    return 100\n"

    applier = LocalPatchApplier(uow=uow)
    res = applier.apply_patch(
        worktree_path=wt_info.path,
        envelope=envelope,
        patch=patch_str,
        project_id="mini-me",
        job_id="job-WRONG",
    )
    assert res.success is False
    assert "job_id mismatch" in res.error


@pytest.mark.asyncio
async def test_b6_7_wrong_project_id_ownership_refused(stage_c_environment):
    uow = stage_c_environment["uow"]
    wt_info = await create_authorized_worktree(
        stage_c_environment, job_id="job-101", run_id="run-101"
    )

    envelope = LocalTaskEnvelope(
        role="local_worker",
        task_class=LocalTaskClass.SMALL_CODE_FIX,
        allowed_files=["foo.py"],
        instruction="Fix foo",
    )
    patch_str = "--- a/foo.py\n+++ b/foo.py\n@@ -1,2 +1,2 @@\n def foo():\n-    return 42\n+    return 100\n"

    applier = LocalPatchApplier(uow=uow)
    res = applier.apply_patch(
        worktree_path=wt_info.path,
        envelope=envelope,
        patch=patch_str,
        project_id="wrong-project",
        job_id="job-101",
    )
    assert res.success is False
    assert "project" in res.error.lower()


@pytest.mark.asyncio
async def test_b6_8_valid_durable_ownership_and_execution_worktree_succeeds(stage_c_environment):
    uow = stage_c_environment["uow"]
    wt_info = await create_authorized_worktree(
        stage_c_environment, job_id="job-102", run_id="run-102"
    )

    envelope = LocalTaskEnvelope(
        role="local_worker",
        task_class=LocalTaskClass.SMALL_CODE_FIX,
        allowed_files=["foo.py"],
        instruction="Fix foo",
    )
    patch_str = "--- a/foo.py\n+++ b/foo.py\n@@ -1,2 +1,2 @@\n def foo():\n-    return 42\n+    return 100\n"

    applier = LocalPatchApplier(uow=uow)
    res = applier.apply_patch(
        worktree_path=wt_info.path,
        envelope=envelope,
        patch=patch_str,
        project_id="mini-me",
        job_id="job-102",
    )
    assert res.success is True
    assert res.applied is True
    assert "foo.py" in res.authoritative_changed_files


@pytest.mark.asyncio
async def test_b6_9_symlink_path_identity_mismatch_refused(stage_c_environment, tmp_path):
    uow = stage_c_environment["uow"]
    wt_info = await create_authorized_worktree(
        stage_c_environment, job_id="job-103", run_id="run-103"
    )

    symlink_wt = tmp_path / "symlink_worktree"
    try:
        os.symlink(wt_info.path, symlink_wt)
    except OSError:
        pytest.skip("Symlinks not supported on this platform")

    envelope = LocalTaskEnvelope(
        role="local_worker",
        task_class=LocalTaskClass.SMALL_CODE_FIX,
        allowed_files=["foo.py"],
        instruction="Fix foo",
    )
    patch_str = "--- a/foo.py\n+++ b/foo.py\n@@ -1,2 +1,2 @@\n def foo():\n-    return 42\n+    return 100\n"

    applier = LocalPatchApplier(uow=uow)
    res = applier.apply_patch(
        worktree_path=symlink_wt,
        envelope=envelope,
        patch=patch_str,
        project_id="mini-me",
        job_id="job-103",
    )
    assert res.success is False
    assert "Path identity mismatch" in res.error or "Workspace mutation denied" in res.error


@pytest.mark.asyncio
async def test_b6_10_dirty_precondition_refused(stage_c_environment):
    uow = stage_c_environment["uow"]
    wt_info = await create_authorized_worktree(
        stage_c_environment, job_id="job-104", run_id="run-104"
    )

    (wt_info.path / "foo.py").write_text("dirty uncommitted content")

    envelope = LocalTaskEnvelope(
        role="local_worker",
        task_class=LocalTaskClass.SMALL_CODE_FIX,
        allowed_files=["foo.py"],
        instruction="Fix foo",
    )
    patch_str = "--- a/foo.py\n+++ b/foo.py\n@@ -1,2 +1,2 @@\n def foo():\n-    return 42\n+    return 100\n"

    applier = LocalPatchApplier(uow=uow)
    res = applier.apply_patch(
        worktree_path=wt_info.path,
        envelope=envelope,
        patch=patch_str,
        project_id="mini-me",
        job_id="job-104",
    )
    assert res.success is False
    assert "dirty" in res.error.lower()


# ADDITIONAL SERVICE AND HARNESS INTEGRATION TESTS
@pytest.mark.asyncio
async def test_patch_application_failure_escalates(stage_c_environment):
    uow = stage_c_environment["uow"]
    wt_info = await create_authorized_worktree(
        stage_c_environment, job_id="job-105", run_id="run-105"
    )

    service = LocalWorkerService(max_corrective_attempts=0)

    bad_patch = "--- a/foo.py\n+++ b/foo.py\n@@ -1,2 +1,2 @@\n-def non_existent_function():\n+def foo():\n     return 42\n"

    raw_response = (
        '{"kind":"CHANGES_PROPOSED","summary":"bad","files_changed":["foo.py"],'
        f'"patch":{json.dumps(bad_patch)},"confidence":0.9,"escalation_required":false,'
        '"escalation_reason":"","next_action":"apply_patch"}'
    )

    async def mock_validator(task, result, attempt):
        return ValidationResult(verdict=LocalValidationVerdict.PASS)

    preflight = PreflightResult(
        provider="ollama",
        model=service.model,
        status=PreflightStatus.READY,
        reachable=True,
        model_present=True,
    )

    class CustomAdapter:
        async def generate(self, system_prompt, prompt, client=None, **kwargs):
            return OllamaGenerateResponse(
                result_class=ProviderResultClass.SUCCESS, text=raw_response
            )

    service.adapter = CustomAdapter()

    envelope = LocalTaskEnvelope(
        role="local_worker",
        task_class=LocalTaskClass.SMALL_CODE_FIX,
        allowed_files=["foo.py"],
        instruction="Fix foo",
    )

    outcome = await service.run(
        envelope,
        validator=mock_validator,
        preflight=preflight,
        worktree_path=wt_info.path,
        uow=uow,
        project_id="mini-me",
        job_id="job-105",
    )

    assert outcome.evidence.validation_result is LocalValidationVerdict.FAIL
    assert outcome.evidence.result_class == "PATCH_APPLY_FAILED"
    assert outcome.evidence.escalation.required is True


@pytest.mark.asyncio
async def test_post_apply_actual_changed_files_mismatch_fails_closed(stage_c_environment):
    uow = stage_c_environment["uow"]
    wt_info = await create_authorized_worktree(
        stage_c_environment, job_id="job-106", run_id="run-106"
    )

    patch_str = (
        "--- a/foo.py\n"
        "+++ b/foo.py\n"
        "@@ -1,2 +1,2 @@\n"
        " def foo():\n"
        "-    return 42\n"
        "+    return 100\n"
        "--- a/tests/test_foo.py\n"
        "+++ b/tests/test_foo.py\n"
        "@@ -1,2 +1,2 @@\n"
        " def test_foo():\n"
        "-    assert foo() == 42\n"
        "+    assert foo() == 100\n"
    )

    strict_envelope = LocalTaskEnvelope(
        role="local_worker",
        task_class=LocalTaskClass.SMALL_CODE_FIX,
        allowed_files=["foo.py"],
        instruction="Fix foo",
    )

    applier = LocalPatchApplier(uow=uow)
    res = applier.apply_patch(
        worktree_path=wt_info.path,
        envelope=strict_envelope,
        patch=patch_str,
        project_id="mini-me",
        job_id="job-106",
    )
    assert res.success is False
    assert "Postcondition failed" in res.error or "allowed_files" in res.error


def test_local_qwen_no_review_audit_merge_authority():
    from minime.local_worker.policy import local_worker_authorities

    auths = local_worker_authorities()
    assert "review" not in auths
    assert "audit" not in auths
    assert "merge" not in auths
    assert "approve" not in auths
    assert "lifecycle" not in auths


# F1-F8 FAIL-CLOSED REMEDIATION TESTS
@pytest.mark.asyncio
async def test_f1_changes_proposed_without_worktree_cannot_succeed():
    from minime.local_worker.harness import LocalWorkerHarness

    patch_str = "--- a/foo.py\n+++ b/foo.py\n@@ -1 +1 @@\n-old\n+new\n"
    raw_response = json.dumps(
        {
            "kind": "CHANGES_PROPOSED",
            "summary": "edit foo",
            "files_changed": ["foo.py"],
            "patch": patch_str,
            "confidence": 0.9,
            "escalation_required": False,
            "escalation_reason": "",
            "next_action": "apply",
        }
    )

    async def mock_dispatch(task, attempt):
        return raw_response

    async def mock_validator(task, result, attempt):
        return ValidationResult(verdict=LocalValidationVerdict.PASS)

    harness = LocalWorkerHarness(dispatch=mock_dispatch)
    envelope = LocalTaskEnvelope(
        role="local_worker",
        task_class=LocalTaskClass.SMALL_CODE_FIX,
        allowed_files=["foo.py"],
        instruction="Fix foo",
    )

    evidence = await harness.run(
        envelope,
        validator=mock_validator,
        worktree_path=None,  # No worktree provided!
    )

    assert evidence.result_class == "PATCH_APPLY_FAILED"
    assert evidence.patch_applied is False
    assert evidence.escalation.required is True


def test_f2_empty_allowed_files_fails_closed():
    envelope = LocalTaskEnvelope(
        role="local_worker",
        task_class=LocalTaskClass.SMALL_CODE_FIX,
        allowed_files=[],  # Empty allowlist!
        instruction="Fix foo",
    )
    patch_str = "--- a/foo.py\n+++ b/foo.py\n@@ -1 +1 @@\n-old\n+new\n"
    decision = validate_patch_policy(patch_str, envelope, kind=LocalResultKind.CHANGES_PROPOSED)
    assert decision.valid is False
    assert "allowed_files cannot be empty" in decision.reason


@pytest.mark.asyncio
async def test_f3_no_retry_after_filesystem_mutation(stage_c_environment):
    from minime.local_worker.harness import LocalWorkerHarness

    uow = stage_c_environment["uow"]
    wt_info = await create_authorized_worktree(
        stage_c_environment, job_id="job-f3", run_id="run-f3"
    )

    valid_patch = "--- a/foo.py\n+++ b/foo.py\n@@ -1,2 +1,2 @@\n def foo():\n-    return 42\n+    return 100\n"
    raw_response = json.dumps(
        {
            "kind": "CHANGES_PROPOSED",
            "summary": "edit foo",
            "files_changed": ["foo.py"],
            "patch": valid_patch,
            "confidence": 0.9,
            "escalation_required": False,
            "escalation_reason": "",
            "next_action": "apply",
        }
    )

    dispatch_calls = 0

    async def mock_dispatch(task, attempt):
        nonlocal dispatch_calls
        dispatch_calls += 1
        return raw_response

    # Validator fails after patch application
    async def mock_validator(task, result, attempt):
        return ValidationResult(
            verdict=LocalValidationVerdict.FAIL, reason="Test validator failed after apply"
        )

    harness = LocalWorkerHarness(dispatch=mock_dispatch, max_corrective_attempts=2)
    envelope = LocalTaskEnvelope(
        role="local_worker",
        task_class=LocalTaskClass.SMALL_CODE_FIX,
        allowed_files=["foo.py"],
        instruction="Fix foo",
    )

    evidence = await harness.run(
        envelope,
        validator=mock_validator,
        worktree_path=wt_info.path,
        uow=uow,
        project_id="mini-me",
        job_id="job-f3",
    )

    assert evidence.patch_applied is True
    assert evidence.result_class == "VALIDATION_FAILED"
    assert evidence.escalation.required is True
    assert dispatch_calls == 1  # No second dispatch after filesystem mutation!


def test_f5_prohibited_patch_operations():
    envelope = LocalTaskEnvelope(
        role="local_worker",
        task_class=LocalTaskClass.SMALL_CODE_FIX,
        allowed_files=["foo.py"],
        instruction="Fix foo",
    )

    # Creation
    create_patch = "--- /dev/null\n+++ b/newfile.py\n@@ -0,0 +1 @@\n+print(1)\n"
    d1 = validate_patch_policy(create_patch, envelope)
    assert d1.valid is False
    assert "prohibited" in d1.reason.lower() or "creation" in d1.reason.lower()

    # Deletion
    delete_patch = "--- a/foo.py\n+++ /dev/null\n@@ -1 +0,0 @@\n-old\n"
    d2 = validate_patch_policy(delete_patch, envelope)
    assert d2.valid is False
    assert "prohibited" in d2.reason.lower() or "deletion" in d2.reason.lower()

    # Rename
    rename_patch = "rename from foo.py\nrename to bar.py\n"
    d3 = validate_patch_policy(rename_patch, envelope)
    assert d3.valid is False
    assert "prohibited" in d3.reason.lower() or "rename" in d3.reason.lower()

    # Binary
    binary_patch = "Binary files a/image.png and b/image.png differ\n"
    d4 = validate_patch_policy(binary_patch, envelope)
    assert d4.valid is False
    assert "prohibited" in d4.reason.lower() or "binary" in d4.reason.lower()


def test_f6_pattern_matching_fnmatch():
    envelope = LocalTaskEnvelope(
        role="local_worker",
        task_class=LocalTaskClass.SMALL_CODE_FIX,
        allowed_files=["src/minime/*"],
        forbidden_files=["src/minime/services/*"],
        instruction="Fix foo",
    )

    # Allowed pattern match
    patch_ok = "--- a/src/minime/foo.py\n+++ b/src/minime/foo.py\n@@ -1 +1 @@\n-old\n+new\n"
    d_ok = validate_patch_policy(patch_ok, envelope)
    assert d_ok.valid is True

    # Forbidden pattern overrides allowed
    patch_forbidden = "--- a/src/minime/services/scheduler.py\n+++ b/src/minime/services/scheduler.py\n@@ -1 +1 @@\n-old\n+new\n"
    d_forb = validate_patch_policy(patch_forbidden, envelope)
    assert d_forb.valid is False
    assert "forbidden_files" in d_forb.reason


def test_f7_offending_forbidden_surface_integration():
    envelope = LocalTaskEnvelope(
        role="local_worker",
        task_class=LocalTaskClass.SMALL_CODE_FIX,
        allowed_files=["alembic/versions/123_migration.py"],
        instruction="Edit migration",
    )
    patch_str = "--- a/alembic/versions/123_migration.py\n+++ b/alembic/versions/123_migration.py\n@@ -1 +1 @@\n-old\n+new\n"
    decision = validate_patch_policy(patch_str, envelope)
    assert decision.valid is False
    assert "forbidden surface" in decision.reason.lower() or "migration" in decision.reason.lower()


def test_f8_containment_and_symlink_check(tmp_path):
    from minime.local_worker.patch_applier import check_path_containment_and_symlinks

    worktree = tmp_path / "worktree"
    worktree.mkdir()
    (worktree / "real_dir").mkdir()

    symlink_dir = worktree / "sym_dir"
    try:
        os.symlink(worktree / "real_dir", symlink_dir)
    except OSError:
        pytest.skip("Symlinks not supported")

    # Path traversal
    err1 = check_path_containment_and_symlinks(worktree, {"../outside.py"})
    assert err1 is not None
    assert "Path traversal" in err1

    # Absolute path
    err2 = check_path_containment_and_symlinks(worktree, {"/etc/passwd"})
    assert err2 is not None
    assert "Absolute path" in err2

    # Symlink segment
    err3 = check_path_containment_and_symlinks(worktree, {"sym_dir/file.py"})
    assert err3 is not None
    assert "Symlink detected" in err3


# C1 DIRECT-APPLIER SAFETY TESTS
@pytest.mark.asyncio
async def test_c1_direct_applier_unauthorized_patch_refused(stage_c_environment):
    uow = stage_c_environment["uow"]
    wt_info = await create_authorized_worktree(
        stage_c_environment, job_id="job-c1", run_id="run-c1"
    )

    original_content = (wt_info.path / "foo.py").read_text()

    unauthorized_patch = (
        "--- a/foo.py\n"
        "+++ b/foo.py\n"
        "@@ -1,2 +1,2 @@\n"
        " def foo():\n"
        "-    return 42\n"
        "+    return 999\n"
    )

    unauthorized_envelope = LocalTaskEnvelope(
        role="local_worker",
        task_class=LocalTaskClass.SMALL_CODE_FIX,
        allowed_files=["tests/test_foo.py"],  # foo.py is NOT allowed!
        instruction="Fix test only",
    )

    applier = LocalPatchApplier(uow=uow)
    res = applier.apply_patch(
        worktree_path=wt_info.path,
        envelope=unauthorized_envelope,
        patch=unauthorized_patch,
        project_id="mini-me",
        job_id="job-c1",
    )

    assert res.success is False
    assert res.applied is False
    assert "not in allowed_files" in res.error

    # Verify zero filesystem mutation
    diff_res = subprocess.run(
        ["git", "diff"], cwd=wt_info.path, capture_output=True, text=True, check=True
    )
    assert diff_res.stdout.strip() == ""
    assert (wt_info.path / "foo.py").read_text() == original_content


@pytest.mark.asyncio
async def test_c1_direct_applier_forbidden_surface_refused(stage_c_environment):
    uow = stage_c_environment["uow"]
    wt_info = await create_authorized_worktree(
        stage_c_environment, job_id="job-c1-forb", run_id="run-c1-forb"
    )

    forbidden_patch = "--- a/alembic/env.py\n+++ b/alembic/env.py\n@@ -1 +1 @@\n-old\n+new\n"

    envelope = LocalTaskEnvelope(
        role="local_worker",
        task_class=LocalTaskClass.SMALL_CODE_FIX,
        allowed_files=["alembic/env.py"],
        instruction="Modify alembic env",
    )

    applier = LocalPatchApplier(uow=uow)
    res = applier.apply_patch(
        worktree_path=wt_info.path,
        envelope=envelope,
        patch=forbidden_patch,
        project_id="mini-me",
        job_id="job-c1-forb",
    )

    assert res.success is False
    assert res.applied is False
    assert "forbidden surface" in res.error.lower() or "migration" in res.error.lower()

    diff_res = subprocess.run(
        ["git", "diff"], cwd=wt_info.path, capture_output=True, text=True, check=True
    )
    assert diff_res.stdout.strip() == ""


@pytest.mark.asyncio
async def test_topology_canonical_nested_execution_worktree_succeeds(tmp_path):
    """Prove canonical nested worktree (repo_dir/.minime/worktrees/job-123) can reach git apply."""
    repo_dir = tmp_path / "managed_repo"
    repo_dir.mkdir()
    nested_worktrees_dir = repo_dir / ".minime" / "worktrees"
    nested_worktrees_dir.mkdir(parents=True)
    runtime_dir = tmp_path / "runtime_app"
    runtime_dir.mkdir()

    subprocess.run(["git", "init", "-b", "main"], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.name", "Test User"], cwd=repo_dir, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo_dir,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "remote", "add", "origin", "https://github.com/silverberdi/mini-me"],
        cwd=repo_dir,
        check=True,
        capture_output=True,
    )

    foo_path = repo_dir / "foo.py"
    foo_path.write_text("def foo():\n    return 42\n")

    marker_path = repo_dir / ".minime-managed-project.json"
    marker_path.write_text(
        json.dumps(
            {
                "project_id": "mini-me",
                "canonical_repository_identity": "github.com/silverberdi/mini-me",
                "repository": "github.com/silverberdi/mini-me",
            }
        )
    )

    subprocess.run(["git", "add", "."], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"], cwd=repo_dir, check=True, capture_output=True
    )

    res_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo_dir, capture_output=True, text=True, check=True
    )
    base_sha = res_sha.stdout.strip()

    from tests.test_stage_c_isolation import MockUOW

    uow = MockUOW()
    binding = ProjectManagedRepositoryBinding(
        project_id="mini-me",
        canonical_repository_identity="github.com/silverberdi/mini-me",
        managed_repository_root=str(repo_dir),
        worktree_parent_dir=str(nested_worktrees_dir),
        remote_name="origin",
        is_valid=True,
    )
    uow.project_managed_repository_bindings.save(binding)

    env_dict = {
        "uow": uow,
        "repo_dir": repo_dir,
        "worktrees_dir": nested_worktrees_dir,
        "runtime_dir": runtime_dir,
        "base_sha": base_sha,
    }

    job_id = "job-nested-101"
    run_id = "run-nested-101"
    wt_info = await create_authorized_worktree(env_dict, job_id=job_id, run_id=run_id)

    # Confirm the worktree is created nested inside repo_dir
    assert str(wt_info.path).startswith(str(repo_dir))

    envelope = LocalTaskEnvelope(
        role="local_worker",
        task_class=LocalTaskClass.SMALL_CODE_FIX,
        allowed_files=["foo.py"],
        instruction="Fix foo",
    )
    patch_str = "--- a/foo.py\n+++ b/foo.py\n@@ -1,2 +1,2 @@\n def foo():\n-    return 42\n+    return 100\n"

    applier = LocalPatchApplier(uow=uow)
    res = applier.apply_patch(
        worktree_path=wt_info.path,
        envelope=envelope,
        patch=patch_str,
        project_id="mini-me",
        job_id=job_id,
    )
    assert res.success is True
    assert res.applied is True
    assert "foo.py" in res.authoritative_changed_files
    assert (wt_info.path / "foo.py").read_text() == "def foo():\n    return 100\n"


@pytest.mark.asyncio
async def test_topology_arbitrary_managed_repo_descendant_refused(stage_c_environment):
    """Prove arbitrary descendant inside managed repo (e.g. repo_dir/random-dir) is refused."""
    repo_dir = stage_c_environment["repo_dir"]
    random_dir = repo_dir / "random-dir"
    random_dir.mkdir(exist_ok=True)

    envelope = LocalTaskEnvelope(
        role="local_worker",
        task_class=LocalTaskClass.SMALL_CODE_FIX,
        allowed_files=["foo.py"],
        instruction="Fix foo",
    )
    patch_str = "--- a/foo.py\n+++ b/foo.py\n@@ -1 +1 @@\n-old\n+new\n"

    applier = LocalPatchApplier(uow=stage_c_environment["uow"])
    res = applier.apply_patch(
        worktree_path=random_dir,
        envelope=envelope,
        patch=patch_str,
        project_id="mini-me",
        job_id="job-random",
    )
    assert res.success is False
    assert res.applied is False
    assert "managed repository" in res.error.lower() or "Workspace mutation denied" in res.error


@pytest.mark.asyncio
async def test_topology_synthetic_ownership_refused(stage_c_environment):
    """Prove durable ownership with has_synthetic_placeholder=True is refused."""
    uow = stage_c_environment["uow"]
    wt_info = await create_authorized_worktree(
        stage_c_environment, job_id="job-synth", run_id="run-synth"
    )

    # Mutate ownership in UoW to set synthetic placeholder field
    canonical_wt_path = os.path.realpath(wt_info.path)
    ownership = uow.orchestration_worktree_ownerships.get_by_canonical_path(canonical_wt_path)
    assert ownership is not None
    updated_ownership = ownership.model_copy(update={"run_id": "run-default"})
    assert updated_ownership.has_synthetic_placeholder is True
    uow.orchestration_worktree_ownerships.save(updated_ownership)

    envelope = LocalTaskEnvelope(
        role="local_worker",
        task_class=LocalTaskClass.SMALL_CODE_FIX,
        allowed_files=["foo.py"],
        instruction="Fix foo",
    )
    patch_str = "--- a/foo.py\n+++ b/foo.py\n@@ -1,2 +1,2 @@\n def foo():\n-    return 42\n+    return 100\n"

    applier = LocalPatchApplier(uow=uow)
    res = applier.apply_patch(
        worktree_path=wt_info.path,
        envelope=envelope,
        patch=patch_str,
        project_id="mini-me",
        job_id="job-synth",
    )
    assert res.success is False
    assert res.applied is False
    assert "synthetic" in res.error.lower() or "Workspace mutation denied" in res.error


@pytest.mark.asyncio
async def test_topology_outside_worktree_parent_dir_refused(stage_c_environment, tmp_path):
    """Prove target outside worktree parent directory and outside managed repo is refused."""
    outside_dir = tmp_path / "outside_worktree"
    outside_dir.mkdir(exist_ok=True)
    subprocess.run(["git", "init"], cwd=outside_dir, check=True, capture_output=True)

    envelope = LocalTaskEnvelope(
        role="local_worker",
        task_class=LocalTaskClass.SMALL_CODE_FIX,
        allowed_files=["foo.py"],
        instruction="Fix foo",
    )
    patch_str = "--- a/foo.py\n+++ b/foo.py\n@@ -1 +1 @@\n-old\n+new\n"

    applier = LocalPatchApplier(uow=stage_c_environment["uow"])
    res = applier.apply_patch(
        worktree_path=outside_dir,
        envelope=envelope,
        patch=patch_str,
        project_id="mini-me",
        job_id="job-outside",
    )
    assert res.success is False
    assert res.applied is False
    assert "outside" in res.error.lower() or "Workspace mutation denied" in res.error

