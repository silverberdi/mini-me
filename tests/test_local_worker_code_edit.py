"""Targeted tests for local worker code-edit execution, patch policy, and SDLC isolation."""

from __future__ import annotations

import json
import subprocess

import pytest

from minime.domain.enums import (
    ProviderResultClass,
)
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
from minime.local_worker.service import LocalWorkerService


@pytest.fixture
def temp_git_repo(tmp_path):
    """Fixture creating a real git repository with initial commit."""
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()

    subprocess.run(["git", "init"], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo_dir, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo_dir, check=True)

    # Initial file
    foo_path = repo_dir / "foo.py"
    foo_path.write_text("def foo():\n    return 42\n")

    test_path = repo_dir / "tests" / "test_foo.py"
    test_path.parent.mkdir()
    test_path.write_text("def test_foo():\n    assert foo() == 42\n")

    subprocess.run(["git", "add", "."], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=repo_dir, check=True, capture_output=True)

    return repo_dir


# 1. TEST_AUTHORING allowed file patch succeeds
@pytest.mark.asyncio
async def test_authoring_allowed_file_patch_succeeds(temp_git_repo):
    envelope = LocalTaskEnvelope(
        role="local_worker",
        task_class=LocalTaskClass.TEST_AUTHORING,
        allowed_files=["tests/test_foo.py"],
        instruction="Add test_bar",
    )

    patch_str = (
        "--- a/tests/test_foo.py\n"
        "+++ b/tests/test_foo.py\n"
        "@@ -1,2 +1,4 @@\n"
        " def test_foo():\n"
        "     assert foo() == 42\n"
        "+def test_bar():\n"
        "+    assert True\n"
    )

    applier = LocalPatchApplier()
    res = applier.apply_patch(worktree_path=temp_git_repo, envelope=envelope, patch=patch_str)
    assert res.success is True
    assert res.applied is True
    assert "tests/test_foo.py" in res.authoritative_changed_files


# 2. SMALL_CODE_FIX allowed file patch succeeds
@pytest.mark.asyncio
async def test_small_code_fix_allowed_file_patch_succeeds(temp_git_repo):
    envelope = LocalTaskEnvelope(
        role="local_worker",
        task_class=LocalTaskClass.SMALL_CODE_FIX,
        allowed_files=["foo.py"],
        instruction="Fix foo return value",
    )

    patch_str = (
        "--- a/foo.py\n"
        "+++ b/foo.py\n"
        "@@ -1,2 +1,2 @@\n"
        " def foo():\n"
        "-    return 42\n"
        "+    return 100\n"
    )

    applier = LocalPatchApplier()
    res = applier.apply_patch(worktree_path=temp_git_repo, envelope=envelope, patch=patch_str)
    assert res.success is True
    assert res.applied is True
    assert "foo.py" in res.authoritative_changed_files


# 3. patch outside allowed_files refused before mutation
def test_patch_outside_allowed_files_refused():
    envelope = LocalTaskEnvelope(
        role="local_worker",
        task_class=LocalTaskClass.SMALL_CODE_FIX,
        allowed_files=["foo.py"],
        instruction="Fix foo",
    )
    patch_str = (
        "--- a/bar.py\n"
        "+++ b/bar.py\n"
        "@@ -1 +1 @@\n"
        "-old\n"
        "+new\n"
    )
    decision = validate_patch_policy(patch_str, envelope)
    assert decision.valid is False
    assert "not in allowed_files" in decision.reason


# 4. ../ traversal refused
def test_path_traversal_refused():
    envelope = LocalTaskEnvelope(
        role="local_worker",
        task_class=LocalTaskClass.SMALL_CODE_FIX,
        allowed_files=["foo.py"],
        instruction="Fix foo",
    )
    patch_str = (
        "--- a/../etc/passwd\n"
        "+++ b/../etc/passwd\n"
        "@@ -1 +1 @@\n"
        "-old\n"
        "+new\n"
    )
    decision = validate_patch_policy(patch_str, envelope)
    assert decision.valid is False
    assert "Path traversal" in decision.reason


# 5. absolute path refused
def test_absolute_path_refused():
    envelope = LocalTaskEnvelope(
        role="local_worker",
        task_class=LocalTaskClass.SMALL_CODE_FIX,
        allowed_files=["foo.py"],
        instruction="Fix foo",
    )
    patch_str = (
        "--- a//etc/shadow\n"
        "+++ b//etc/shadow\n"
        "@@ -1 +1 @@\n"
        "-old\n"
        "+new\n"
    )
    decision = validate_patch_policy(patch_str, envelope)
    assert decision.valid is False
    assert "Absolute path" in decision.reason


# 6. forbidden surface refused
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


# 7. model files_changed lying about actual patch paths is detected
@pytest.mark.asyncio
async def test_model_files_changed_lying_detected(temp_git_repo):
    envelope = LocalTaskEnvelope(
        role="local_worker",
        task_class=LocalTaskClass.SMALL_CODE_FIX,
        allowed_files=["foo.py"],
        instruction="Fix foo",
    )

    patch_str = (
        "--- a/secret.py\n"
        "+++ b/secret.py\n"
        "@@ -1 +1 @@\n"
        "-old\n"
        "+new\n"
    )

    decision = validate_patch_policy(patch_str, envelope)
    assert decision.valid is False
    assert "secret.py" in decision.reason or "not in allowed_files" in decision.reason


# 8. dirty execution worktree refuses application
@pytest.mark.asyncio
async def test_dirty_execution_worktree_refuses_application(temp_git_repo):
    (temp_git_repo / "foo.py").write_text("dirty content")

    envelope = LocalTaskEnvelope(
        role="local_worker",
        task_class=LocalTaskClass.SMALL_CODE_FIX,
        allowed_files=["foo.py"],
        instruction="Fix foo",
    )
    patch_str = (
        "--- a/foo.py\n"
        "+++ b/foo.py\n"
        "@@ -1 +1 @@\n"
        "-dirty content\n"
        "+clean content\n"
    )

    applier = LocalPatchApplier()
    res = applier.apply_patch(worktree_path=temp_git_repo, envelope=envelope, patch=patch_str)
    assert res.success is False
    assert "dirty" in res.error.lower()


# 9. runtime checkout can never be mutation target
@pytest.mark.asyncio
async def test_runtime_checkout_mutation_target_refused(monkeypatch, tmp_path):
    runtime_dir = tmp_path / "opt" / "minime" / "app"
    runtime_dir.mkdir(parents=True)
    monkeypatch.setenv("MINIME_RUNTIME_ROOT", str(runtime_dir))

    envelope = LocalTaskEnvelope(
        role="local_worker",
        task_class=LocalTaskClass.SMALL_CODE_FIX,
        allowed_files=["foo.py"],
        instruction="Fix foo",
    )
    patch_str = "--- a/foo.py\n+++ b/foo.py\n@@ -1 +1 @@\n-a\n+b\n"

    applier = LocalPatchApplier()
    res = applier.apply_patch(worktree_path=runtime_dir, envelope=envelope, patch=patch_str)
    assert res.success is False
    assert "runtime checkout" in res.error.lower()


# 10. managed repository can never be direct mutation target
@pytest.mark.asyncio
async def test_managed_repository_direct_mutation_target_refused(monkeypatch, tmp_path):
    managed_dir = tmp_path / "opt" / "minime" / "repos" / "mini-me"
    managed_dir.mkdir(parents=True)
    monkeypatch.setenv("MINIME_MANAGED_ROOT", str(managed_dir))

    envelope = LocalTaskEnvelope(
        role="local_worker",
        task_class=LocalTaskClass.SMALL_CODE_FIX,
        allowed_files=["foo.py"],
        instruction="Fix foo",
    )
    patch_str = "--- a/foo.py\n+++ b/foo.py\n@@ -1 +1 @@\n-a\n+b\n"

    applier = LocalPatchApplier()
    res = applier.apply_patch(worktree_path=managed_dir, envelope=envelope, patch=patch_str)
    assert res.success is False
    assert "managed repository" in res.error.lower()


# 11. EXECUTION_WORKTREE with valid ownership succeeds
@pytest.mark.asyncio
async def test_execution_worktree_valid_ownership_succeeds(temp_git_repo):
    envelope = LocalTaskEnvelope(
        role="local_worker",
        task_class=LocalTaskClass.TEST_AUTHORING,
        allowed_files=["foo.py"],
        instruction="Fix foo",
    )
    patch_str = "--- a/foo.py\n+++ b/foo.py\n@@ -1,2 +1,2 @@\n def foo():\n-    return 42\n+    return 100\n"

    applier = LocalPatchApplier()
    res = applier.apply_patch(worktree_path=temp_git_repo, envelope=envelope, patch=patch_str)
    assert res.success is True
    assert res.applied is True


# 12. malformed patch fails closed
def test_malformed_patch_fails_closed():
    envelope = LocalTaskEnvelope(
        role="local_worker",
        task_class=LocalTaskClass.SMALL_CODE_FIX,
        allowed_files=["foo.py"],
        instruction="Fix foo",
    )
    patch_str = "THIS IS NOT A VALID UNIFIED DIFF"
    decision = validate_patch_policy(patch_str, envelope)
    assert decision.valid is False
    assert "Malformed" in decision.reason or "no valid touched files" in decision.reason


# 13. patch application failure escalates
@pytest.mark.asyncio
async def test_patch_application_failure_escalates(temp_git_repo):
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
        provider="ollama", model=service.model, status=PreflightStatus.READY, reachable=True, model_present=True
    )

    class CustomAdapter:
        async def generate(self, system_prompt, prompt, client=None):
            return OllamaGenerateResponse(result_class=ProviderResultClass.SUCCESS, text=raw_response)

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
        worktree_path=temp_git_repo,
    )

    assert outcome.evidence.validation_result is LocalValidationVerdict.FAIL
    assert outcome.evidence.result_class == "PATCH_APPLY_FAILED"
    assert outcome.evidence.escalation.required is True


# 14. post-apply actual changed-files mismatch fails closed
@pytest.mark.asyncio
async def test_post_apply_actual_changed_files_mismatch_fails_closed(temp_git_repo):
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

    applier = LocalPatchApplier()
    res = applier.apply_patch(worktree_path=temp_git_repo, envelope=strict_envelope, patch=patch_str)
    assert res.success is False
    assert "Postcondition failed" in res.error or "allowed_files" in res.error


# 15. deterministic validator failure triggers at most one corrective attempt
@pytest.mark.asyncio
async def test_deterministic_validator_failure_triggers_one_corrective_attempt(temp_git_repo):
    service = LocalWorkerService(max_corrective_attempts=1)
    attempt_counter = 0

    patch_str = "--- a/foo.py\n+++ b/foo.py\n@@ -1,2 +1,2 @@\n def foo():\n-    return 42\n+    return 100\n"

    raw_response = (
        '{"kind":"CHANGES_PROPOSED","summary":"fix","files_changed":["foo.py"],'
        f'"patch":{json.dumps(patch_str)},"confidence":0.9,"escalation_required":false,'
        '"escalation_reason":"","next_action":"apply_patch"}'
    )

    async def mock_validator(task, result, attempt):
        nonlocal attempt_counter
        attempt_counter += 1
        if attempt_counter == 1:
            return ValidationResult(verdict=LocalValidationVerdict.FAIL, reason="Attempt 1 validator check failed")
        return ValidationResult(verdict=LocalValidationVerdict.PASS, reason="Attempt 2 validator check passed")

    preflight = PreflightResult(
        provider="ollama", model=service.model, status=PreflightStatus.READY, reachable=True, model_present=True
    )

    class CustomAdapter:
        async def generate(self, system_prompt, prompt, client=None):
            return OllamaGenerateResponse(result_class=ProviderResultClass.SUCCESS, text=raw_response)

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
        worktree_path=temp_git_repo,
    )

    assert attempt_counter == 2
    assert outcome.evidence.corrections_used == 1
    assert outcome.evidence.fully_validated is True


# 16. no unbounded retry
@pytest.mark.asyncio
async def test_no_unbounded_retry(temp_git_repo):
    service = LocalWorkerService(max_corrective_attempts=1)
    attempt_counter = 0

    patch_str = "--- a/foo.py\n+++ b/foo.py\n@@ -1,2 +1,2 @@\n def foo():\n-    return 42\n+    return 100\n"

    raw_response = (
        '{"kind":"CHANGES_PROPOSED","summary":"fix","files_changed":["foo.py"],'
        f'"patch":{json.dumps(patch_str)},"confidence":0.9,"escalation_required":false,'
        '"escalation_reason":"","next_action":"apply_patch"}'
    )

    async def mock_validator(task, result, attempt):
        nonlocal attempt_counter
        attempt_counter += 1
        return ValidationResult(verdict=LocalValidationVerdict.FAIL, reason="Validator fails always")

    preflight = PreflightResult(
        provider="ollama", model=service.model, status=PreflightStatus.READY, reachable=True, model_present=True
    )

    class CustomAdapter:
        async def generate(self, system_prompt, prompt, client=None):
            return OllamaGenerateResponse(result_class=ProviderResultClass.SUCCESS, text=raw_response)

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
        worktree_path=temp_git_repo,
    )

    assert attempt_counter == 2
    assert outcome.evidence.corrections_used == 1
    assert outcome.evidence.fully_validated is False
    assert outcome.evidence.result_class == "VALIDATION_FAILED"


# 17. NO_CHANGE_JUSTIFIED remains valid and performs zero mutation
@pytest.mark.asyncio
async def test_no_change_justified_zero_mutation(temp_git_repo):
    service = LocalWorkerService(max_corrective_attempts=1)

    raw_response = (
        '{"kind":"NO_CHANGE_JUSTIFIED","summary":"Code is already correct","files_changed":[],'
        '"patch":null,"confidence":0.95,"escalation_required":false,'
        '"escalation_reason":"","next_action":"no_change"}'
    )

    async def mock_validator(task, result, attempt):
        return ValidationResult(verdict=LocalValidationVerdict.PASS, reason="No change verified")

    preflight = PreflightResult(
        provider="ollama", model=service.model, status=PreflightStatus.READY, reachable=True, model_present=True
    )

    class CustomAdapter:
        async def generate(self, system_prompt, prompt, client=None):
            return OllamaGenerateResponse(result_class=ProviderResultClass.SUCCESS, text=raw_response)

    service.adapter = CustomAdapter()

    envelope = LocalTaskEnvelope(
        role="local_worker",
        task_class=LocalTaskClass.SMALL_CODE_FIX,
        allowed_files=["foo.py"],
        instruction="Check foo",
    )

    outcome = await service.run(
        envelope,
        validator=mock_validator,
        preflight=preflight,
        worktree_path=temp_git_repo,
    )

    assert outcome.evidence.result == LocalResultKind.NO_CHANGE_JUSTIFIED
    assert outcome.evidence.patch_applied is False
    assert outcome.evidence.fully_validated is True


# 18. local Qwen still has no review/audit/merge/approve authority
def test_local_qwen_no_review_audit_merge_authority():
    from minime.local_worker.policy import local_worker_authorities
    auths = local_worker_authorities()
    assert "review" not in auths
    assert "audit" not in auths
    assert "merge" not in auths
    assert "approve" not in auths
    assert "lifecycle" not in auths


# 19-20. Phase 9 Demonstration
def test_phase9_first_real_use_readiness_representation():
    envelope = LocalTaskEnvelope(
        role="local_worker",
        task_class=LocalTaskClass.TEST_AUTHORING,
        allowed_files=["tests/test_autonomous_intake_admission.py"],
        instruction=(
            "Replace the stale bare readiness-service MagicMock wiring so discovery receives a real "
            "OpenSpecAdapter; preserve production behavior and make no source-code changes."
        ),
    )
    assert envelope.task_class == LocalTaskClass.TEST_AUTHORING
    assert envelope.allowed_files == ["tests/test_autonomous_intake_admission.py"]

