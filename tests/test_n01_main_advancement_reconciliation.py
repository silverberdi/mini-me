"""Real-Git regression coverage for intake A/P -> B/P2 reconciliation."""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from tests.conftest import (
    InMemoryPersistenceUnitOfWork,
    attach_local_bare_origin,
    create_isolated_openspec_change,
    setup_managed_repository_fixture,
)

from minime.domain.enums import (
    ReadinessState,
    WorkItemStatus,
)
from minime.domain.models import BacklogItem, Project, ProjectBinding, utc_now
from minime.services.intake_service import IntakeService
from minime.services.lifecycle_gates import ApplyAttributionGate, GateStatus
from minime.services.openspec_generator import GeneratedOpenSpec
from minime.services.worktree_manager import WorktreeManager


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=True)
    return result.stdout.strip()


def _commit(root: Path, message: str) -> str:
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test User",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-m",
            message,
        ],
        cwd=root,
        check=True,
        capture_output=True,
    )
    return _git(root, "rev-parse", "HEAD")


@pytest.fixture
def intake_env(tmp_path: Path):
    uow = InMemoryPersistenceUnitOfWork()
    repo = tmp_path / "managed"
    worktree_parent = tmp_path / "worktrees"
    setup_managed_repository_fixture(
        uow,
        "mini-me",
        repo,
        worktree_parent,
        canonical_repository_identity="github.com/silverberdi/mini-me",
    )
    bare = Path(attach_local_bare_origin(repo, uow=uow, project_id="mini-me"))
    subprocess.run(
        ["git", "push", "--set-upstream", "origin", "main"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    project = Project(
        project_id="mini-me",
        display_name="mini me",
        repository="silverberdi/mini-me",
        base_branch="main",
        openspec_path="openspec",
    )
    uow.projects.save(project)
    change_name = "operational-blocker-visibility"
    uow.bindings.save(
        ProjectBinding(
            project_id="mini-me",
            repository=project.repository,
            github_issue_number=133,
            openspec_change_name=change_name,
        )
    )
    item = BacklogItem(
        project_id="mini-me",
        item_key=change_name,
        title="Operational blocker visibility",
        description="Expose operational blocker details.",
        status=WorkItemStatus.READY,
        readiness_state=ReadinessState.READY,
        openspec_change_name=change_name,
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    uow.backlog_items.save(item)
    service = IntakeService(uow, project_root=repo)
    saga = service.saga_engine.start_saga(
        saga_type="INTAKE",
        project_id="mini-me",
        work_item_key=change_name,
        change_name=change_name,
        initial_phase="READY",
    )
    ownership = service._reserve_intake_workspace(project, item, saga)
    service._activate_intake_workspace(ownership, project)
    change_dir = create_isolated_openspec_change(
        Path(ownership.canonical_workspace_path), change_name
    )
    generated = GeneratedOpenSpec(
        change_name=change_name,
        proposal_content=(change_dir / "proposal.md").read_text(encoding="utf-8"),
        tasks_content=(change_dir / "tasks.md").read_text(encoding="utf-8"),
        design_content=(change_dir / "design.md").read_text(encoding="utf-8"),
        specs={
            "specs/feature/spec.md": (change_dir / "specs/feature/spec.md").read_text(
                encoding="utf-8"
            )
        },
    )
    a_sha = ownership.base_sha
    p_sha = service._commit_intake_artifacts(ownership, generated, project)
    assert p_sha != a_sha
    assert service._publish_intake_artifacts_cas(ownership, project) == p_sha
    return {
        "uow": uow,
        "repo": repo,
        "bare": bare,
        "project": project,
        "service": service,
        "ownership": ownership,
        "change_name": change_name,
        "a_sha": a_sha,
        "p_sha": p_sha,
    }


def _advance_main(env, *, conflicting_artifact: bool = False) -> str:
    repo = env["repo"]
    if conflicting_artifact:
        target = repo / "openspec" / "changes" / env["change_name"]
        target.mkdir(parents=True)
        (target / "proposal.md").write_text("main-side conflicting proposal\n", encoding="utf-8")
    else:
        source = repo / "src" / "prior_change.py"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("# unrelated change already merged to main\n", encoding="utf-8")
    b_sha = _commit(repo, "advance main independently")
    subprocess.run(["git", "push", "origin", "main"], cwd=repo, check=True, capture_output=True)
    return b_sha


def test_ap_without_main_advance_remains_valid(intake_env):
    env = intake_env
    assert (
        env["service"].reconcile_main_advancement_before_admission("mini-me", env["change_name"])
        is None
    )
    updated = env["uow"].intake_workspace_ownerships.get_by_id(env["ownership"].workspace_id)
    assert updated.base_sha == env["a_sha"]
    assert updated.published_sha == env["p_sha"]
    assert _git(env["repo"], "rev-parse", f"refs/heads/intake/{env['change_name']}") == env["p_sha"]


def test_unrelated_main_advance_materializes_p2_and_clears_false_drift(intake_env):
    env = intake_env
    b_sha = _advance_main(env)
    p2 = env["service"].reconcile_main_advancement_before_admission("mini-me", env["change_name"])
    assert p2 and p2 != env["p_sha"]
    assert _git(env["repo"], "rev-parse", f"{p2}^") == b_sha
    ref_sha, ok = env["service"]._observe_remote_ref(
        str(env["repo"]), "origin", f"refs/minime/intake/{env['change_name']}"
    )
    assert ok and ref_sha == p2
    updated = env["uow"].intake_workspace_ownerships.get_by_id(env["ownership"].workspace_id)
    assert updated.base_sha == b_sha
    assert updated.published_sha == p2
    assert _git(env["repo"], "rev-parse", f"refs/heads/intake/{env['change_name']}") == env["p_sha"]
    gate = ApplyAttributionGate(env["service"].openspec_adapter).evaluate(
        project=env["project"],
        change_name=env["change_name"],
        project_root=updated.canonical_workspace_path,
    )
    assert gate.status is GateStatus.PASS
    assert env["uow"].orchestration_runs.list_runs(is_active=True) == []
    assert env["uow"].jobs.list_active_jobs() == []
    assert (
        env["service"].reconcile_main_advancement_before_admission("mini-me", env["change_name"])
        is None
    )
    assert _git(env["bare"], "rev-parse", "refs/minime/intake/" + env["change_name"]) == p2


def test_intake_introduced_implementation_still_fails_attribution(intake_env):
    env = intake_env
    workspace = Path(env["ownership"].canonical_workspace_path)
    code = workspace / "src" / "premature.py"
    code.parent.mkdir(parents=True, exist_ok=True)
    code.write_text("IMPLEMENTATION = True\n", encoding="utf-8")
    bad_p = _commit(workspace, "unauthorized implementation before admission")
    subprocess.run(
        ["git", "push", "origin", f"{bad_p}:refs/minime/intake/{env['change_name']}"],
        cwd=workspace,
        check=True,
        capture_output=True,
    )
    env["ownership"].head_sha = bad_p
    env["ownership"].published_sha = bad_p
    env["uow"].intake_workspace_ownerships.save(env["ownership"])
    _advance_main(env)
    gate = ApplyAttributionGate(env["service"].openspec_adapter).evaluate(
        project=env["project"],
        change_name=env["change_name"],
        project_root=workspace,
    )
    assert gate.status is GateStatus.FAIL
    assert gate.reason.code == "LIFECYCLE_DRIFT"
    with pytest.raises(Exception, match="not the original direct child"):
        env["service"].reconcile_main_advancement_before_admission("mini-me", env["change_name"])
    updated = env["uow"].intake_workspace_ownerships.get_by_id(env["ownership"].workspace_id)
    assert updated.published_sha == bad_p
    gate_after = ApplyAttributionGate(env["service"].openspec_adapter).evaluate(
        project=env["project"],
        change_name=env["change_name"],
        project_root=workspace,
    )
    assert gate_after.status is GateStatus.FAIL
    assert gate_after.reason.code == "LIFECYCLE_DRIFT"


def test_artifact_conflict_blocks_without_changing_publication(intake_env):
    env = intake_env
    _advance_main(env, conflicting_artifact=True)
    with pytest.raises(Exception, match="main already contains the intake change path"):
        env["service"].reconcile_main_advancement_before_admission("mini-me", env["change_name"])
    observed, ok = env["service"]._observe_remote_ref(
        str(env["repo"]), "origin", f"refs/minime/intake/{env['change_name']}"
    )
    assert ok and observed == env["p_sha"]
    updated = env["uow"].intake_workspace_ownerships.get_by_id(env["ownership"].workspace_id)
    assert updated.published_sha == env["p_sha"]


def test_post_push_observation_recovers_without_second_push(intake_env, monkeypatch):
    env = intake_env
    _advance_main(env)
    service = env["service"]
    original_observe = service._observe_remote_ref
    failed_once = False
    push_count = 0

    def fail_first_post_push(managed_root: str, remote: str, ref: str):
        nonlocal failed_once
        current, ok = original_observe(managed_root, remote, ref)
        if (
            ref == f"refs/minime/intake/{env['change_name']}"
            and current != env["p_sha"]
            and not failed_once
        ):
            failed_once = True
            return None, False
        return current, ok

    real_run = __import__("minime.services.intake_service", fromlist=["subprocess"]).subprocess.run

    def count_push(command, *args, **kwargs):
        nonlocal push_count
        if command[:2] == [
            "git",
            "push",
        ] and f"refs/minime/intake/{env['change_name']}" in " ".join(command):
            push_count += 1
        return real_run(command, *args, **kwargs)

    monkeypatch.setattr(service, "_observe_remote_ref", fail_first_post_push)
    monkeypatch.setattr("minime.services.intake_service.subprocess.run", count_push)
    with pytest.raises(Exception):
        service.reconcile_main_advancement_before_admission("mini-me", env["change_name"])
    p2 = service.reconcile_main_advancement_before_admission("mini-me", env["change_name"])
    assert p2
    assert push_count == 1
    assert _git(env["bare"], "rev-parse", f"refs/minime/intake/{env['change_name']}") == p2
    action = env["uow"].orchestration_external_actions.get_by_action_key(
        f"intake_main_advance_publish:mini-me:{env['change_name']}:{_git(env['bare'], 'rev-parse', 'refs/heads/main')}"
    )
    assert action is not None
    assert action.status.value == "COMPLETED"


def test_main_advance_cas_race_never_overwrites_competing_ref(intake_env, monkeypatch):
    env = intake_env
    b_sha = _advance_main(env)
    service = env["service"]
    original_run = subprocess.run
    raced = False

    def race_before_publish(command, *args, **kwargs):
        nonlocal raced
        if (
            not raced
            and command[:2] == ["git", "push"]
            and f"refs/minime/intake/{env['change_name']}" in " ".join(command)
        ):
            raced = True
            original_run(
                [
                    "git",
                    "push",
                    f"--force-with-lease=refs/minime/intake/{env['change_name']}:{env['p_sha']}",
                    "origin",
                    f"{b_sha}:refs/minime/intake/{env['change_name']}",
                ],
                cwd=env["repo"],
                check=True,
                capture_output=True,
                text=True,
            )
        return original_run(command, *args, **kwargs)

    monkeypatch.setattr("minime.services.intake_service.subprocess.run", race_before_publish)
    with pytest.raises(Exception):
        service.reconcile_main_advancement_before_admission("mini-me", env["change_name"])
    competing_sha = _git(
        env["repo"], "ls-remote", "origin", f"refs/minime/intake/{env['change_name']}"
    ).split()[0]
    assert raced
    assert competing_sha != env["p_sha"]
    assert (
        _git(
            env["repo"], "ls-remote", "origin", f"refs/minime/intake/{env['change_name']}"
        ).split()[0]
        == competing_sha
    )


def test_published_artifact_handoff_uses_noninteractive_github_app_git_env(intake_env, monkeypatch):
    env = intake_env
    subprocess.run(
        ["git", "remote", "set-url", "origin", "https://github.com/silverberdi/mini-me.git"],
        cwd=env["repo"],
        check=True,
        capture_output=True,
    )

    class AuthAdapter:
        def _git_auth_bundle(self, remote_url: str):
            assert remote_url == "https://github.com/silverberdi/mini-me.git"
            return SimpleNamespace(
                env={
                    "GIT_CONFIG_COUNT": "2",
                    "GIT_CONFIG_KEY_0": "credential.helper",
                    "GIT_CONFIG_VALUE_0": "",
                    "GIT_CONFIG_KEY_1": "http.extraHeader",
                    "GIT_CONFIG_VALUE_1": "Authorization: Basic redacted-test-credential",
                },
                secrets=("redacted-test-credential",),
            )

    captured: dict[str, str] = {}
    real_exec = asyncio.create_subprocess_exec

    class FailedFetchProcess:
        returncode = 128
        pid = 12345

        async def communicate(self):
            return b"", b"fatal: unable to access remote"

    async def capture_exec(program, *args, **kwargs):
        if program == "git" and args and args[0] == "fetch":
            captured.update(kwargs["env"])
            return FailedFetchProcess()
        return await real_exec(program, *args, **kwargs)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", capture_exec)
    manager = WorktreeManager(env["repo"], env["uow"], github_adapter=AuthAdapter())
    with pytest.raises(RuntimeError, match="unable to access remote"):
        asyncio.run(
            manager._git(
                ["fetch", "--no-tags", "origin", "refs/minime/intake/" + env["change_name"]],
                cwd=env["repo"],
                project_id="mini-me",
                operation_type="published_intake_ref_fetch",
            )
        )
    assert captured["GIT_TERMINAL_PROMPT"] == "0"
    assert captured["GIT_CONFIG_VALUE_0"] == ""
    assert captured["GIT_CONFIG_VALUE_1"].startswith("Authorization: Basic ")
