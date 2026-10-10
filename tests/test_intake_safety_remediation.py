"""Regression tests for the Phase 2 consolidated intake safety remediation.

Each test demonstrates a defect fixed by the fail-closed publication, readiness,
legacy-attribution, and git-commit corrections, and validates the correction.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from tests.conftest import (
    InMemoryPersistenceUnitOfWork,
    attach_local_bare_origin,
    create_isolated_openspec_change,
    publish_local_intake_ref,
    setup_managed_repository_fixture,
)

import minime.services.intake_service as intake_service_module
from minime.domain.enums import (
    IntakeWorkspaceCreationState,
    IntakeWorkspacePublicationState,
    ReadinessState,
    WorkItemStatus,
)
from minime.domain.exceptions import UnsafeIntakeWorkspaceStateError
from minime.domain.models import (
    BacklogItem,
    IntakeWorkspaceOwnership,
    Project,
    ProjectBinding,
    utc_now,
)
from minime.services.intake_service import IntakeService
from minime.services.openspec_generator import GeneratedOpenSpec
from minime.services.readiness_service import ReadinessService


def _generated(change_name: str = "safety-change") -> GeneratedOpenSpec:
    return GeneratedOpenSpec(
        change_name=change_name,
        proposal_content="# Proposal: Safety\n\nProblem.\n",
        tasks_content="# Tasks\n\n- [ ] task\n",
        design_content="# Design\n",
        specs={"specs/feature/spec.md": "## ADDED Requirements\n\n### Requirement: Safety\n"},
    )


def _ownership(
    change_name: str,
    ws_path: str,
    *,
    published_sha: str | None = None,
    head_sha: str | None = None,
    published_ref: str | None = None,
    identity: str = "github.com/org/repo",
) -> IntakeWorkspaceOwnership:
    return IntakeWorkspaceOwnership(
        workspace_id=f"ws-{change_name}",
        project_id="proj",
        item_key=change_name,
        saga_id=f"saga-{change_name}",
        change_name=change_name,
        canonical_workspace_path=ws_path,
        canonical_repository_identity=identity,
        base_sha="main",
        head_sha=head_sha,
        creation_state=IntakeWorkspaceCreationState.ACTIVE,
        publication_state=(
            IntakeWorkspacePublicationState.PUBLISHED
            if published_sha
            else IntakeWorkspacePublicationState.UNPUBLISHED
        ),
        published_ref=published_ref or f"refs/minime/intake/{change_name}",
        published_sha=published_sha,
    )


@pytest.fixture
def env(tmp_path: Path):
    uow = InMemoryPersistenceUnitOfWork()
    repo_dir = tmp_path / "managed"
    setup_managed_repository_fixture(
        uow,
        "proj",
        repo_dir,
        repo_dir / ".minime" / "worktrees",
        canonical_repository_identity="github.com/org/repo",
    )
    bare = attach_local_bare_origin(repo_dir, uow=uow, project_id="proj")
    project = Project(
        project_id="proj",
        display_name="Proj",
        repository="github.com/org/repo",
        base_branch="main",
    )
    uow.projects.save(project)
    uow.bindings.save(
        ProjectBinding(
            project_id="proj",
            repository="github.com/org/repo",
            github_issue_number=1,
            openspec_change_name="safety-change",
            is_valid=True,
        )
    )
    svc = IntakeService(uow, project_root=repo_dir)
    return {"uow": uow, "repo_dir": repo_dir, "bare": bare, "project": project, "svc": svc}


def _activated_workspace(env, change_name: str) -> IntakeWorkspaceOwnership:
    """Reserve and activate a real git worktree for the change, writing authored artifacts."""
    uow = env["uow"]
    svc = env["svc"]
    item = BacklogItem(
        project_id="proj",
        item_key=change_name,
        title="Safety Change",
        description="A safety change.",
        acceptance_criteria=["works"],
        status=WorkItemStatus.PREPARING,
        readiness_state=ReadinessState.NOT_READY,
        openspec_change_name=change_name,
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    uow.backlog_items.save(item)
    saga = svc.saga_engine.start_saga(
        saga_type="INTAKE", project_id="proj", work_item_key=change_name,
        change_name=change_name, initial_phase="WORKSPACE_ACTIVE",
    )
    ow = svc._reserve_intake_workspace(env["project"], item, saga)
    svc._activate_intake_workspace(ow, env["project"])
    return ow


def _write_artifacts(ws_path: str, change_name: str, generated: GeneratedOpenSpec) -> None:
    change_dir = Path(ws_path) / "openspec" / "changes" / change_name
    change_dir.mkdir(parents=True, exist_ok=True)
    contents = {"proposal.md": generated.proposal_content, "tasks.md": generated.tasks_content, **generated.specs}
    if generated.design_content:
        contents["design.md"] = generated.design_content
    for rel, text in contents.items():
        (change_dir / rel).parent.mkdir(parents=True, exist_ok=True)
        (change_dir / rel).write_text(text, encoding="utf-8")


# --- DEFECT 1: false publication success -------------------------------------


def test_remote_observation_failure_never_produces_published(env):
    """A transport failure during remote observation must never yield PUBLISHED."""
    uow = env["uow"]
    svc = env["svc"]
    # Point origin at an unreachable URL so ls-remote fails.
    subprocess.run(
        ["git", "remote", "set-url", "origin", "https://github.com/does-not-exist/repo.git"],
        cwd=env["repo_dir"], check=True,
    )
    ow = _ownership("unreachable-change", str(env["repo_dir"]), head_sha="deadbeef")
    uow.intake_workspace_ownerships.save(ow)

    with pytest.raises(RuntimeError, match="PUBLICATION_TRANSPORT_FAILURE"):
        svc._publish_intake_artifacts_cas(ow, env["project"])

    updated = uow.intake_workspace_ownerships.get_by_id(ow.workspace_id)
    assert updated.publication_state == IntakeWorkspacePublicationState.PUBLICATION_FAILED
    assert updated.published_sha is None


def test_concurrent_publication_triggers_atomic_cas_rejection(env):
    """Initial publication rejects when the remote ref already exists (expected-old absent)."""
    uow = env["uow"]
    svc = env["svc"]
    ow = _activated_workspace(env, "conflict-change")
    generated = _generated("conflict-change")
    _write_artifacts(ow.canonical_workspace_path, "conflict-change", generated)
    head_sha = svc._commit_intake_artifacts(ow, generated, env["project"])

    # A competing actor publishes the ref first.
    subprocess.run(
        ["git", "push", "origin", f"{head_sha}:refs/minime/intake/conflict-change"],
        cwd=env["repo_dir"], check=True, capture_output=True,
    )

    with pytest.raises(RuntimeError, match="REF_CAS_MISMATCH"):
        svc._publish_intake_artifacts_cas(ow, env["project"])

    updated = uow.intake_workspace_ownerships.get_by_id(ow.workspace_id)
    assert updated.publication_state == IntakeWorkspacePublicationState.PUBLICATION_FAILED


def test_initial_publication_uses_expected_absent_lease(env, monkeypatch):
    """The first remote ref creation carries Git's atomic expected-absent lease."""
    svc = env["svc"]
    ow = _activated_workspace(env, "initial-cas-change")
    generated = _generated("initial-cas-change")
    _write_artifacts(ow.canonical_workspace_path, "initial-cas-change", generated)
    svc._commit_intake_artifacts(ow, generated, env["project"])

    real_run = intake_service_module.subprocess.run
    push_commands: list[list[str]] = []

    def capture_push(command, *args, **kwargs):
        if command[:2] == ["git", "push"]:
            push_commands.append(command)
        return real_run(command, *args, **kwargs)

    monkeypatch.setattr(intake_service_module.subprocess, "run", capture_push)

    svc._publish_intake_artifacts_cas(ow, env["project"])

    published_ref = "refs/minime/intake/initial-cas-change"
    assert any(
        f"--force-with-lease={published_ref}:" in command for command in push_commands
    )


def test_initial_publication_cas_rejects_race_after_absence_observation(env, monkeypatch):
    """A writer creating the ref after ls-remote still loses the initial CAS."""
    svc = env["svc"]
    ow = _activated_workspace(env, "initial-cas-race")
    generated = _generated("initial-cas-race")
    _write_artifacts(ow.canonical_workspace_path, "initial-cas-race", generated)
    candidate_sha = svc._commit_intake_artifacts(ow, generated, env["project"])
    competing_sha = subprocess.run(
        ["git", "rev-parse", f"{candidate_sha}^"],
        cwd=env["repo_dir"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    real_run = intake_service_module.subprocess.run
    raced = False
    published_ref = "refs/minime/intake/initial-cas-race"

    def race_before_push(command, *args, **kwargs):
        nonlocal raced
        if (
            not raced
            and command[:2] == ["git", "push"]
            and f"--force-with-lease={published_ref}:" in command
        ):
            raced = True
            real_run(
                ["git", "push", "origin", f"{competing_sha}:refs/minime/race-source"],
                cwd=env["repo_dir"],
                check=True,
                capture_output=True,
            )
            real_run(
                ["git", f"--git-dir={env['bare']}", "update-ref", published_ref, competing_sha],
                check=True,
                capture_output=True,
            )
        return real_run(command, *args, **kwargs)

    monkeypatch.setattr(intake_service_module.subprocess, "run", race_before_push)

    with pytest.raises(RuntimeError, match="REF_CAS_MISMATCH"):
        svc._publish_intake_artifacts_cas(ow, env["project"])

    assert (
        env["uow"].intake_workspace_ownerships.get_by_id(ow.workspace_id).publication_state
        == IntakeWorkspacePublicationState.PUBLICATION_FAILED
    )


def test_subsequent_publication_uses_exact_previous_sha_lease(env, monkeypatch):
    """P -> P2 may advance only from the persisted exact P SHA."""
    svc = env["svc"]
    ow = _activated_workspace(env, "subsequent-cas-change")
    generated = _generated("subsequent-cas-change")
    _write_artifacts(ow.canonical_workspace_path, "subsequent-cas-change", generated)
    candidate_sha = svc._commit_intake_artifacts(ow, generated, env["project"])
    previous_sha = subprocess.run(
        ["git", "rev-parse", f"{candidate_sha}^"],
        cwd=env["repo_dir"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    published_ref = "refs/minime/intake/subsequent-cas-change"
    subprocess.run(
        ["git", "push", "origin", f"{previous_sha}:{published_ref}"],
        cwd=env["repo_dir"],
        check=True,
        capture_output=True,
    )
    ow.publication_state = IntakeWorkspacePublicationState.PUBLISHED
    ow.published_sha = previous_sha
    ow.published_ref = published_ref
    env["uow"].intake_workspace_ownerships.save(ow)

    real_run = intake_service_module.subprocess.run
    push_commands: list[list[str]] = []

    def capture_push(command, *args, **kwargs):
        if command[:2] == ["git", "push"]:
            push_commands.append(command)
        return real_run(command, *args, **kwargs)

    monkeypatch.setattr(intake_service_module.subprocess, "run", capture_push)
    assert svc._publish_intake_artifacts_cas(ow, env["project"]) == candidate_sha
    assert any(
        f"--force-with-lease={published_ref}:{previous_sha}" in command
        for command in push_commands
    )


def test_post_push_observation_failure_never_marks_published(env, monkeypatch):
    """PUBLISHED is impossible until an authoritative post-push read succeeds."""
    svc = env["svc"]
    ow = _activated_workspace(env, "post-push-observation")
    generated = _generated("post-push-observation")
    _write_artifacts(ow.canonical_workspace_path, "post-push-observation", generated)
    svc._commit_intake_artifacts(ow, generated, env["project"])

    observations = iter([(None, True), (None, False)])
    monkeypatch.setattr(svc, "_observe_remote_ref", lambda *_: next(observations))

    with pytest.raises(RuntimeError, match="PUBLICATION_AMBIGUOUS"):
        svc._publish_intake_artifacts_cas(ow, env["project"])

    assert (
        env["uow"].intake_workspace_ownerships.get_by_id(ow.workspace_id).publication_state
        == IntakeWorkspacePublicationState.PUBLICATION_FAILED
    )


def test_ambiguous_post_publish_observation_fails_closed(env):
    """Post-publication observation must return exactly the candidate SHA or fail."""
    uow = env["uow"]
    svc = env["svc"]
    ow = _activated_workspace(env, "ambiguous-change")
    generated = _generated("ambiguous-change")
    _write_artifacts(ow.canonical_workspace_path, "ambiguous-change", generated)
    svc._commit_intake_artifacts(ow, generated, env["project"])

    # Break the remote AFTER commit so the final observation cannot confirm.
    subprocess.run(
        ["git", "remote", "set-url", "origin", "https://github.com/does-not-exist/repo.git"],
        cwd=env["repo_dir"], check=True,
    )
    with pytest.raises(RuntimeError):
        svc._publish_intake_artifacts_cas(ow, env["project"])

    updated = uow.intake_workspace_ownerships.get_by_id(ow.workspace_id)
    assert updated.publication_state != IntakeWorkspacePublicationState.PUBLISHED


# --- DEFECT 4: git commit fail-closed ----------------------------------------


def test_failed_git_commit_cannot_publish_base_sha(env):
    """A failed commit must never fall back to base_sha; it must raise."""
    svc = env["svc"]
    ow = _ownership("no-repo-change", str(env["repo_dir"] / "missing-ws"), head_sha=None)
    generated = _generated("no-repo-change")

    with pytest.raises(UnsafeIntakeWorkspaceStateError):
        svc._commit_intake_artifacts(ow, generated, env["project"])
    assert ow.head_sha is None


def test_unexpected_manifest_path_fails_closed(env):
    """An unexpected file in the workspace must fail the commit."""
    uow = env["uow"]
    svc = env["svc"]
    ow = _activated_workspace(env, "unexpected-change")
    generated = _generated("unexpected-change")
    _write_artifacts(ow.canonical_workspace_path, "unexpected-change", generated)
    # Add an unexpected file outside the approved manifest.
    (Path(ow.canonical_workspace_path) / "unexpected.txt").write_text("bad", encoding="utf-8")

    with pytest.raises(UnsafeIntakeWorkspaceStateError, match="Unexpected file"):
        svc._commit_intake_artifacts(ow, generated, env["project"])

    assert uow.intake_workspace_ownerships.get_by_id(ow.workspace_id).head_sha is None


# --- DEFECT 3: legacy attribution -------------------------------------------


def test_legacy_artifacts_without_historical_evidence_need_human(env):
    """File existence + backlog item alone is never PROVABLE; converge to NEEDS_HUMAN."""
    uow = env["uow"]
    svc = env["svc"]
    create_isolated_openspec_change(env["repo_dir"], "orphan-legacy")
    now = utc_now()
    item = BacklogItem(
        project_id="proj", item_key="orphan-legacy", title="Orphan Legacy",
        status=WorkItemStatus.READY, readiness_state=ReadinessState.READY,
        openspec_change_name="orphan-legacy", created_at=now, updated_at=now,
    )
    uow.backlog_items.save(item)

    result = svc.reconcile_legacy_unowned_intake_artifacts("proj")

    assert "orphan-legacy" in result["ambiguous_needs_human"]
    assert "orphan-legacy" not in result["provable_adopted"]
    assert uow.backlog_items.get_by_project_and_key("proj", "orphan-legacy").status == WorkItemStatus.NEEDS_HUMAN


def test_legacy_artifacts_contradictory_hash_not_adopted(env):
    """Legacy files whose content contradicts the canonical generation are not adopted."""
    uow = env["uow"]
    svc = env["svc"]
    change_name = "tampered-legacy"
    legacy_dir = env["repo_dir"] / "openspec" / "changes" / change_name
    create_isolated_openspec_change(env["repo_dir"], change_name)
    # Tamper with a file so its hash contradicts the canonical generated content.
    (legacy_dir / "proposal.md").write_text("# Tampered\n", encoding="utf-8")

    now = utc_now()
    item = BacklogItem(
        project_id="proj", item_key=change_name, title="Tampered Legacy",
        description="A legitimately described legacy change.",
        acceptance_criteria=["works"],
        status=WorkItemStatus.READY, readiness_state=ReadinessState.READY,
        openspec_change_name=change_name, created_at=now, updated_at=now,
    )
    uow.backlog_items.save(item)

    result = svc.reconcile_legacy_unowned_intake_artifacts("proj")

    assert change_name in result["ambiguous_needs_human"]
    assert change_name not in result["provable_adopted"]


# --- DEFECT 2: readiness unverified local source -----------------------------


def test_remote_ref_sha_mismatch_prevents_ready(env):
    """Readiness must refuse when the remote ref SHA drifts from published_sha."""
    uow = env["uow"]
    ws_path = str(env["repo_dir"])
    change_name = "drift-change"
    create_isolated_openspec_change(env["repo_dir"], change_name)
    publish_local_intake_ref(env["repo_dir"], change_name)
    # Ownership records a WRONG published_sha.
    ow = _ownership(change_name, ws_path, published_sha="0" * 40)
    uow.intake_workspace_ownerships.save(ow)

    svc = ReadinessService(uow)
    eval_result = svc.evaluate_change_readiness_pure(
        project_id="proj", change_name=change_name, project_root=ws_path,
        github_repo="github.com/org/repo", github_issue=1, require_published_ref=True,
    )
    assert not eval_result.is_ready
    assert any("drift" in r or "mismatch" in r for r in eval_result.unmet_reasons)


def test_modified_local_workspace_cannot_authorize_admission(env):
    """Readiness derives artifacts from the published tree, not a tampered workspace."""
    uow = env["uow"]
    change_name = "workspace-tamper"
    ws_path = str(env["repo_dir"] / "tamper-ws")
    # No published ref exists at all; only a local workspace with artifacts.
    create_isolated_openspec_change(env["repo_dir"], change_name)
    ow = _ownership(change_name, ws_path)
    uow.intake_workspace_ownerships.save(ow)

    svc = ReadinessService(uow)
    eval_result = svc.evaluate_change_readiness_pure(
        project_id="proj", change_name=change_name, project_root=ws_path,
        github_repo="github.com/org/repo", github_issue=1, require_published_ref=True,
    )
    assert not eval_result.is_ready
    assert any("published" in r for r in eval_result.unmet_reasons)


def test_verified_published_tree_ignores_tampered_intake_workspace(env):
    """A mutable workspace cannot make or break the artifact readiness proof."""
    uow = env["uow"]
    change_name = "published-tree-authority"
    create_isolated_openspec_change(env["repo_dir"], change_name)
    published_sha = publish_local_intake_ref(env["repo_dir"], change_name)

    tampered_workspace = env["repo_dir"] / "tampered-workspace"
    (tampered_workspace / "openspec" / "changes" / change_name).mkdir(parents=True)
    (tampered_workspace / "openspec" / "changes" / change_name / "proposal.md").write_text(
        "not the published proposal", encoding="utf-8"
    )
    identity = uow.project_managed_repository_bindings.get_by_project_id("proj")
    ow = _ownership(
        change_name,
        str(tampered_workspace),
        published_sha=published_sha,
        identity=identity.canonical_repository_identity,
    )
    uow.intake_workspace_ownerships.save(ow)

    result = ReadinessService(uow).evaluate_change_readiness_pure(
        project_id="proj",
        change_name=change_name,
        project_root=str(tampered_workspace),
        github_repo="github.com/org/repo",
        github_issue=1,
        require_published_ref=True,
    )

    artifacts_check = next(check for check in result.checks if check.name == "openspec_artifacts")
    assert artifacts_check.passed
    published_check = next(
        check for check in result.checks if check.name == "published_artifact_identity"
    )
    assert published_check.passed
    assert published_check.details["tree_verified"] is True


def test_missing_published_artifact_prevents_ready(env):
    """Required files are checked in the remote commit, not only on local disk."""
    uow = env["uow"]
    change_name = "missing-published-design"
    change_dir = env["repo_dir"] / "openspec" / "changes" / change_name
    change_dir.mkdir(parents=True)
    (change_dir / "proposal.md").write_text("# proposal\n", encoding="utf-8")
    (change_dir / "tasks.md").write_text("# tasks\n", encoding="utf-8")
    specs = change_dir / "specs" / "feature"
    specs.mkdir(parents=True)
    (specs / "spec.md").write_text("## ADDED Requirements\n", encoding="utf-8")
    published_sha = publish_local_intake_ref(env["repo_dir"], change_name)
    identity = uow.project_managed_repository_bindings.get_by_project_id("proj")
    uow.intake_workspace_ownerships.save(
        _ownership(
            change_name,
            str(env["repo_dir"] / "unused-workspace"),
            published_sha=published_sha,
            identity=identity.canonical_repository_identity,
        )
    )

    result = ReadinessService(uow).evaluate_change_readiness_pure(
        project_id="proj",
        change_name=change_name,
        project_root=str(env["repo_dir"]),
        github_repo="github.com/org/repo",
        github_issue=1,
        require_published_ref=True,
    )

    assert not result.is_ready
    assert any("missing required files: design.md" in reason for reason in result.unmet_reasons)


def test_invalid_published_artifact_prevents_ready(env):
    """Strict validation is also performed against the verified published tree."""
    uow = env["uow"]
    change_name = "invalid-published-spec"
    change_dir = create_isolated_openspec_change(env["repo_dir"], change_name)
    (change_dir / "specs" / "feature" / "spec.md").write_text(
        "not an OpenSpec delta", encoding="utf-8"
    )
    published_sha = publish_local_intake_ref(env["repo_dir"], change_name)
    identity = uow.project_managed_repository_bindings.get_by_project_id("proj")
    uow.intake_workspace_ownerships.save(
        _ownership(
            change_name,
            str(env["repo_dir"] / "unused-workspace"),
            published_sha=published_sha,
            identity=identity.canonical_repository_identity,
        )
    )

    result = ReadinessService(uow).evaluate_change_readiness_pure(
        project_id="proj",
        change_name=change_name,
        project_root=str(env["repo_dir"]),
        github_repo="github.com/org/repo",
        github_issue=1,
        require_published_ref=True,
    )

    assert not result.is_ready
    strict_check = next(
        check for check in result.checks if check.name == "openspec_strict_validation"
    )
    assert not strict_check.passed


def test_local_ref_fallback_cannot_authorize_production_admission(env):
    """A local-only ref (remote='local' fallback) is not acceptable to admission readiness."""
    uow = env["uow"]
    change_name = "local-only-change"
    # Set up a binding whose remote is 'local' and record a locally-updated ref only.
    binding = uow.project_managed_repository_bindings.get_by_project_id("proj")
    binding.remote_name = "local"
    uow.project_managed_repository_bindings.save(binding)
    create_isolated_openspec_change(env["repo_dir"], change_name)
    # Update a LOCAL ref (not a real remote) to mimic the local fallback.
    subprocess.run(
        ["git", "update-ref", f"refs/minime/intake/{change_name}", "HEAD"],
        cwd=env["repo_dir"], check=True, capture_output=True,
    )
    ow = _ownership(change_name, str(env["repo_dir"]), published_sha="HEAD")
    uow.intake_workspace_ownerships.save(ow)

    svc = ReadinessService(uow)
    eval_result = svc.evaluate_change_readiness_pure(
        project_id="proj", change_name=change_name, project_root=str(env["repo_dir"]),
        github_repo="github.com/org/repo", github_issue=1, require_published_ref=True,
    )
    assert not eval_result.is_ready


# --- Retry gating regression (DEFECT 2 helper) -------------------------------


def test_retry_gating_exact_allowlist():
    from minime.services.intake_service import IntakeService

    def item(reasons):
        return BacklogItem(
            project_id="proj", item_key="k", title="t", status=WorkItemStatus.BLOCKED,
            unmet_readiness_reasons=reasons, created_at=utc_now(), updated_at=utc_now(),
        )

    assert IntakeService.is_blocked_retry_eligible(item(["stale_ready_artifacts_missing"])) is True
    assert IntakeService.is_blocked_retry_eligible(item(["stale_ready_artifacts_missing", "auth_failed"])) is False
    assert IntakeService.is_blocked_retry_eligible(item(["budget_exhausted"])) is False
    assert IntakeService.is_blocked_retry_eligible(item([])) is False
