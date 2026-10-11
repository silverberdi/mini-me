"""Real-Git regression coverage for intake A/P -> B/P2 reconciliation."""

from __future__ import annotations

import asyncio
import subprocess
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from tests.conftest import (
    InMemoryPersistenceUnitOfWork,
    attach_local_bare_origin,
    create_isolated_openspec_change,
    setup_managed_repository_fixture,
)

from minime.adapters.github import GitHubAdapter, GitHubAuthorizationError
from minime.domain.enums import (
    ChangeStatus,
    ExternalOutcome,
    ExternalReasonCode,
    IntakeWorkspaceCreationState,
    IntakeWorkspacePublicationState,
    ProviderHealthStatus,
    ReadinessState,
    RetrySafety,
    WorkItemStatus,
)
from minime.domain.models import (
    BacklogItem,
    Change,
    ExternalActionResult,
    Project,
    ProjectBinding,
    ProviderHealth,
    utc_now,
)
from minime.services.intake_service import IntakeService
from minime.services.intake_workspace_ownership_selection import (
    IntakeWorkspaceOwnershipSelectionError,
    resolve_published_intake_ownership,
)
from minime.services.lifecycle_gates import ApplyAttributionGate, GateStatus
from minime.services.openspec_generator import GeneratedOpenSpec
from minime.services.readiness_service import ReadinessService
from minime.services.scheduler_service import SchedulerService
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


def _simulate_private_https_remote(monkeypatch, env):
    """Route fake private-HTTPS Git URLs to the test bare remote, retaining auth env."""
    private_url = "https://github.example/silverberdi/mini-me.git"
    subprocess.run(
        ["git", "remote", "set-url", "origin", private_url],
        cwd=env["repo"],
        check=True,
        capture_output=True,
        text=True,
    )
    token = "ephemeral-test-installation-token"
    auth_env = {
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "http.extraHeader",
        "GIT_CONFIG_VALUE_0": "Authorization: Basic ephemeral-test-header",
    }
    auth_calls: list[str] = []
    operations: list[tuple[list[str], dict[str, str]]] = []

    def auth_bundle(_adapter, remote_url):
        auth_calls.append(remote_url)
        if remote_url != private_url:
            raise AssertionError("GitHub App auth requested for unexpected remote identity")
        return SimpleNamespace(env=auth_env, secrets=(token, "ephemeral-test-header"))

    real_run = subprocess.run

    def simulated_run(command, *args, **kwargs):
        argv = [str(part) for part in command]
        env_arg = dict(kwargs.get("env") or {})
        if argv[:3] == ["git", "remote", "get-url"] and len(argv) == 4:
            return subprocess.CompletedProcess(argv, 0, private_url + "\n", "")
        if argv[:3] == ["git", "ls-remote", "origin"]:
            operations.append((argv, env_arg))
            argv[2] = str(env["bare"])
        elif argv[0] == "git" and "fetch" in argv:
            url_index = next(
                (i for i, value in enumerate(argv) if value in (private_url, "origin")),
                None,
            )
            if url_index is not None:
                operations.append((argv, env_arg))
                argv[url_index] = str(env["bare"])
        elif argv[:2] == ["git", "push"] and "origin" in argv:
            operations.append((argv, env_arg))
            argv[argv.index("origin")] = str(env["bare"])
        return real_run(argv, *args, **kwargs)

    monkeypatch.setattr(GitHubAdapter, "_git_auth_bundle", auth_bundle)
    monkeypatch.setattr(subprocess, "run", simulated_run)
    return private_url, token, auth_calls, operations


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


def _insert_failed_history_before_active(env):
    """Reproduce PostgreSQL's historical-first row order without changing authority."""
    repository = env["uow"].intake_workspace_ownerships
    active = repository.get_by_id(env["ownership"].workspace_id)
    historical = active.model_copy(
        update={
            "workspace_id": str(uuid.uuid4()),
            "canonical_workspace_path": str(
                Path(active.canonical_workspace_path).with_name("failed")
            ),
            "creation_state": IntakeWorkspaceCreationState.FAILED_PENDING_CLEANUP,
            "publication_state": IntakeWorkspacePublicationState.UNPUBLISHED,
            "head_sha": None,
            "published_ref": None,
            "published_sha": None,
        }
    )
    # The in-memory test repository preserves insertion order, intentionally
    # reproducing the old get_by_item_key() ambiguity.
    repository._store.clear()
    repository.save(historical)
    repository.save(active)
    assert (
        repository.get_by_item_key("mini-me", env["change_name"]).workspace_id
        == historical.workspace_id
    )
    return historical, active


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


def test_readiness_published_ref_and_tree_fetch_use_app_auth(intake_env, monkeypatch):
    env = intake_env
    private_url, token, auth_calls, operations = _simulate_private_https_remote(monkeypatch, env)
    readiness = ReadinessService(
        env["uow"],
        openspec_adapter=env["service"].openspec_adapter,
        github_adapter=GitHubAdapter(),
    )
    ref = f"refs/minime/intake/{env['change_name']}"

    observed, ok, error = readiness._observe_published_ref(str(env["repo"]), "origin", ref)
    assert ok and observed == env["p_sha"]
    assert error is None

    artifacts, strict, error = readiness._evaluate_verified_published_tree(
        project=env["project"],
        change_name=env["change_name"],
        managed_root=str(env["repo"]),
        remote="origin",
        published_ref=ref,
        published_sha=env["p_sha"],
    )
    assert error is None
    assert artifacts and artifacts["exists"]
    assert len(auth_calls) >= 2
    assert all(url == private_url for url in auth_calls)
    authenticated_network_calls = [
        (argv, child_env)
        for argv, child_env in operations
        if "ls-remote" in argv or "fetch" in argv
    ]
    assert any("ls-remote" in argv for argv, _ in authenticated_network_calls)
    assert any("fetch" in argv for argv, _ in authenticated_network_calls)
    for argv, child_env in authenticated_network_calls:
        assert child_env.get("GIT_TERMINAL_PROMPT") == "0"
        assert child_env.get("GIT_CONFIG_VALUE_0") == "Authorization: Basic ephemeral-test-header"
        assert token not in " ".join(argv)


def test_readiness_denies_published_tree_when_app_auth_cannot_be_minted(intake_env, monkeypatch):
    env = intake_env
    _simulate_private_https_remote(monkeypatch, env)

    def deny_auth(_adapter, _remote_url):
        raise GitHubAuthorizationError("installation token unavailable")

    monkeypatch.setattr(GitHubAdapter, "_git_auth_bundle", deny_auth)
    readiness = ReadinessService(env["uow"], github_adapter=GitHubAdapter())
    observed, ok, observation_error = readiness._observe_published_ref(
        str(env["repo"]), "origin", f"refs/minime/intake/{env['change_name']}"
    )
    assert observed is None and not ok
    assert observation_error and "GitHub App authorization was denied" in observation_error

    artifacts, strict, error = readiness._evaluate_verified_published_tree(
        project=env["project"],
        change_name=env["change_name"],
        managed_root=str(env["repo"]),
        remote="origin",
        published_ref=f"refs/minime/intake/{env['change_name']}",
        published_sha=env["p_sha"],
    )
    assert artifacts is None and strict is None
    assert error and "GitHub App authorization is unavailable" in error

    project_binding = env["uow"].bindings.get_by_project_and_change("mini-me", env["change_name"])
    project_binding.is_valid = True
    env["uow"].bindings.save(project_binding)
    evaluation = readiness.evaluate_change_readiness_pure(
        project_id="mini-me",
        change_name=env["change_name"],
        project_root=str(env["repo"]),
        github_repo=env["project"].repository,
        github_issue=133,
        require_published_ref=True,
    )
    assert not evaluation.is_ready
    assert any(
        "GitHub App authorization was denied" in reason for reason in evaluation.unmet_reasons
    )


def test_readiness_rejects_inline_remote_credentials_without_echoing_them(intake_env, caplog):
    env = intake_env
    secret = "must-never-appear-in-argv-or-logs"
    subprocess.run(
        [
            "git",
            "remote",
            "set-url",
            "origin",
            f"https://x-access-token:{secret}@github.example/silverberdi/mini-me.git",
        ],
        cwd=env["repo"],
        check=True,
        capture_output=True,
    )
    readiness = ReadinessService(env["uow"], github_adapter=GitHubAdapter())
    observed, ok, error = readiness._observe_published_ref(
        str(env["repo"]), "origin", f"refs/minime/intake/{env['change_name']}"
    )
    assert observed is None and not ok
    assert error and "GitHub App authorization was denied" in error
    assert secret not in caplog.text


def test_orchestrate_start_cli_reconciles_and_checks_published_tree_auth(intake_env, monkeypatch):
    env = intake_env
    historical, active = _insert_failed_history_before_active(env)
    _advance_main(env)
    private_url, token, auth_calls, operations = _simulate_private_https_remote(monkeypatch, env)

    class FakeSessionContext:
        def __enter__(self):
            return None

        def __exit__(self, *_args):
            return None

    monkeypatch.setattr("minime.cli.main.db_manager.session", lambda: FakeSessionContext())
    monkeypatch.setattr(
        "minime.cli.main.PostgresPersistenceUnitOfWork", lambda _session: env["uow"]
    )

    sequence: list[str] = []
    resolved_ownership_ids: list[str] = []
    original_resolver = resolve_published_intake_ownership

    def tracked_resolver(*args, **kwargs):
        selected = original_resolver(*args, **kwargs)
        if selected:
            resolved_ownership_ids.append(selected.workspace_id)
        return selected

    monkeypatch.setattr(
        "minime.services.intake_workspace_ownership_selection.resolve_published_intake_ownership",
        tracked_resolver,
    )
    original_reconcile = IntakeService.reconcile_main_advancement_before_admission

    def tracked_reconcile(service, project_id, change_name):
        sequence.append("reconcile")
        return original_reconcile(service, project_id, change_name)

    original_observe = ReadinessService._observe_published_ref

    def tracked_observe(service, *args, **kwargs):
        sequence.append("readiness_ref_observation")
        return original_observe(service, *args, **kwargs)

    original_tree = ReadinessService._evaluate_verified_published_tree

    def tracked_tree(service, *args, **kwargs):
        sequence.append("readiness_tree_fetch")
        return original_tree(service, *args, **kwargs)

    monkeypatch.setattr(
        IntakeService, "reconcile_main_advancement_before_admission", tracked_reconcile
    )
    monkeypatch.setattr(ReadinessService, "_observe_published_ref", tracked_observe)
    monkeypatch.setattr(ReadinessService, "_evaluate_verified_published_tree", tracked_tree)

    from typer.testing import CliRunner

    from minime.cli.main import app as cli_app

    result = CliRunner().invoke(
        cli_app,
        [
            "orchestrate",
            "start",
            "mini-me",
            env["change_name"],
            "--path",
            str(env["repo"]),
        ],
    )
    assert result.exit_code != 0  # Other gates may block this isolated fixture.
    assert "reconcile" in sequence
    assert "readiness_ref_observation" in sequence
    assert "readiness_tree_fetch" in sequence
    assert sequence.index("reconcile") < sequence.index("readiness_ref_observation")
    assert sequence.index("readiness_ref_observation") < sequence.index("readiness_tree_fetch")
    assert any(
        "ls-remote" in argv and child_env.get("GIT_TERMINAL_PROMPT") == "0"
        for argv, child_env in operations
    )
    assert any(
        "fetch" in argv and child_env.get("GIT_TERMINAL_PROMPT") == "0"
        for argv, child_env in operations
    )
    assert auth_calls and all(url == private_url for url in auth_calls)
    for argv, child_env in operations:
        if "ls-remote" in argv or "fetch" in argv or "push" in argv:
            assert (
                child_env.get("GIT_CONFIG_VALUE_0") == "Authorization: Basic ephemeral-test-header"
            )
            assert token not in " ".join(argv)
    updated = env["uow"].intake_workspace_ownerships.get_by_id(env["ownership"].workspace_id)
    assert updated.base_sha != env["a_sha"]
    assert updated.workspace_id == active.workspace_id
    unchanged_history = env["uow"].intake_workspace_ownerships.get_by_id(historical.workspace_id)
    assert unchanged_history.creation_state == IntakeWorkspaceCreationState.FAILED_PENDING_CLEANUP
    assert unchanged_history.publication_state == IntakeWorkspacePublicationState.UNPUBLISHED
    assert unchanged_history.published_sha is None
    assert resolved_ownership_ids
    assert set(resolved_ownership_ids) == {active.workspace_id}
    assert env["uow"].orchestration_runs.list_runs(is_active=True) == []
    assert env["uow"].jobs.list_active_jobs() == []


def test_handoff_materializes_from_active_publication_not_failed_history(intake_env, monkeypatch):
    env = intake_env
    historical, active = _insert_failed_history_before_active(env)
    from minime.adapters.github import GitHubAdapter
    from minime.services.worktree_manager import WorktreeManager

    # Permit this local bare test remote through the same Git child-process path;
    # Git itself performs ls-remote/fetch and the real handoff selector/materializer.
    monkeypatch.setattr(
        GitHubAdapter,
        "_git_auth_bundle",
        lambda _adapter, _url: SimpleNamespace(env={}, secrets=()),
    )
    destination = env["repo"].parent / "execution-worktree"
    destination.mkdir()
    manager = WorktreeManager(env["repo"], env["uow"])
    result = asyncio.run(
        manager._materialize_verified_published_intake_artifacts(
            destination_worktree=destination,
            project_id="mini-me",
            change_name=env["change_name"],
            job_id="test-job",
        )
    )
    assert result is True
    assert (destination / "openspec/changes" / env["change_name"] / "proposal.md").is_file()
    assert (destination / "openspec/changes" / env["change_name"] / "proposal.md").read_text(
        encoding="utf-8"
    ).strip() == (
        Path(active.canonical_workspace_path)
        / "openspec/changes"
        / env["change_name"]
        / "proposal.md"
    ).read_text(encoding="utf-8").strip()
    assert (
        env["uow"].intake_workspace_ownerships.get_by_id(historical.workspace_id).published_sha
        is None
    )


def test_cli_start_resolves_active_owner_through_p2_readiness_admission_and_handoff(
    intake_env, monkeypatch
):
    env = intake_env
    historical, active = _insert_failed_history_before_active(env)
    _advance_main(env)

    # The fixture's Git remote is a local bare repository. Keep Git operations
    # real while avoiding network credentials and provider execution.
    from minime.adapters.github import GitHubAdapter
    from minime.services.worktree_manager import WorktreeManager

    monkeypatch.setattr(
        GitHubAdapter,
        "_git_auth_bundle",
        lambda _adapter, _url: SimpleNamespace(env={}, secrets=()),
    )
    monkeypatch.setattr(
        GitHubAdapter,
        "validate_issue_binding",
        lambda _adapter, *_args, **_kwargs: ExternalActionResult(
            outcome=ExternalOutcome.SUCCESS,
            source_adapter="test-observation",
            reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
            retry_safety=RetrySafety.SAFE,
            data=True,
        ),
    )
    for provider in ("codex", "antigravity"):
        env["uow"].provider_health.save(
            ProviderHealth(provider=provider, status=ProviderHealthStatus.AVAILABLE)
        )
    env["uow"].changes.save(
        Change(
            project_id="mini-me",
            name=env["change_name"],
            schema_name="feature",
            status=ChangeStatus.READY,
            last_readiness_status=ReadinessState.READY,
        )
    )

    class FakeSessionContext:
        def __enter__(self):
            return None

        def __exit__(self, *_args):
            return None

    monkeypatch.setattr("minime.cli.main.db_manager.session", lambda: FakeSessionContext())
    monkeypatch.setattr(
        "minime.cli.main.PostgresPersistenceUnitOfWork", lambda _session: env["uow"]
    )

    selected_ids: list[str] = []
    original_resolver = resolve_published_intake_ownership

    def tracked_resolver(*args, **kwargs):
        owner = original_resolver(*args, **kwargs)
        if owner:
            selected_ids.append(owner.workspace_id)
        return owner

    monkeypatch.setattr(
        "minime.services.intake_workspace_ownership_selection.resolve_published_intake_ownership",
        tracked_resolver,
    )
    observed_readiness: list[str] = []
    readiness_ownership_ids: list[str] = []
    ownership_repo = env["uow"].intake_workspace_ownerships
    original_active_lookup = ownership_repo.get_active_by_item_key

    def tracked_active_lookup(project_id, item_key):
        owner = original_active_lookup(project_id, item_key)
        if owner:
            readiness_ownership_ids.append(owner.workspace_id)
        return owner

    ownership_repo.get_active_by_item_key = tracked_active_lookup
    original_tree_evaluation = ReadinessService._evaluate_verified_published_tree

    def tracked_tree_evaluation(service, **kwargs):
        observed_readiness.append(kwargs["published_sha"])
        return original_tree_evaluation(service, **kwargs)

    monkeypatch.setattr(
        ReadinessService,
        "_evaluate_verified_published_tree",
        tracked_tree_evaluation,
    )
    materialized: list[Path] = []
    original_handoff = WorktreeManager._materialize_verified_published_intake_artifacts

    async def stop_after_real_handoff(manager, **kwargs):
        await original_handoff(manager, **kwargs)
        materialized.append(
            kwargs["destination_worktree"]
            / "openspec"
            / "changes"
            / kwargs["change_name"]
            / "proposal.md"
        )
        # Stop the integration run before any provider is invoked. The real
        # published-tree selector and materializer have already completed.
        raise RuntimeError("test stop after verified published handoff")

    monkeypatch.setattr(
        WorktreeManager,
        "_materialize_verified_published_intake_artifacts",
        stop_after_real_handoff,
    )

    from typer.testing import CliRunner

    from minime.cli.main import app as cli_app

    result = CliRunner().invoke(
        cli_app,
        [
            "orchestrate",
            "start",
            "mini-me",
            env["change_name"],
            "--path",
            str(env["repo"]),
        ],
    )
    updated = env["uow"].intake_workspace_ownerships.get_by_id(active.workspace_id)
    assert updated.base_sha != env["a_sha"]
    assert updated.published_sha != env["p_sha"]
    assert observed_readiness == [updated.published_sha]
    assert selected_ids and set(selected_ids) == {active.workspace_id}
    assert readiness_ownership_ids
    assert set(readiness_ownership_ids) == {active.workspace_id}
    assert len(selected_ids) >= 3
    assert materialized and materialized[0].is_file(), result.output
    assert (
        env["uow"].intake_workspace_ownerships.get_by_id(historical.workspace_id).published_sha
        is None
    )
    assert env["uow"].orchestration_runs.list_runs()


def test_only_failed_historical_ownership_cannot_authorize_admission(intake_env):
    env = intake_env
    historical, _active = _insert_failed_history_before_active(env)
    repository = env["uow"].intake_workspace_ownerships
    repository._store.pop(env["ownership"].workspace_id)
    with pytest.raises(IntakeWorkspaceOwnershipSelectionError, match="Historical intake ownership"):
        resolve_published_intake_ownership(
            repository,
            project_id="mini-me",
            change_name=env["change_name"],
        )
    scheduler = SchedulerService(
        env["uow"],
        project_root=env["repo"],
        readiness_service=ReadinessService(env["uow"]),
    )
    with pytest.raises(IntakeWorkspaceOwnershipSelectionError):
        scheduler.admit_work_item("mini-me", env["change_name"])
    assert env["uow"].orchestration_runs.list_runs(is_active=True) == []
    assert (
        repository.get_by_id(historical.workspace_id).publication_state
        == IntakeWorkspacePublicationState.UNPUBLISHED
    )


def test_contradictory_ownership_identity_fails_closed(intake_env):
    env = intake_env
    owner = env["ownership"]
    contradictory = owner.model_copy(
        update={"workspace_id": str(uuid.uuid4()), "item_key": "different-item"}
    )
    env["uow"].intake_workspace_ownerships.save(contradictory)
    with pytest.raises(
        IntakeWorkspaceOwnershipSelectionError, match="conflicting project, item, or change"
    ):
        resolve_published_intake_ownership(
            env["uow"].intake_workspace_ownerships,
            project_id="mini-me",
            change_name=env["change_name"],
        )


def test_published_sha_contradiction_blocks_main_advancement(intake_env):
    env = intake_env
    _advance_main(env)
    owner = env["ownership"].model_copy(update={"published_sha": "f" * 40})
    env["uow"].intake_workspace_ownerships.save(owner)
    with pytest.raises(Exception, match="Published intake ref drifted"):
        env["service"].reconcile_main_advancement_before_admission("mini-me", env["change_name"])
    unchanged = env["uow"].intake_workspace_ownerships.get_by_id(owner.workspace_id)
    assert unchanged.published_sha == "f" * 40
    observed, ok = env["service"]._observe_remote_ref(
        str(env["repo"]), "origin", owner.published_ref
    )
    assert ok and observed == env["p_sha"]


def test_handoff_accepts_unique_released_publication(intake_env, monkeypatch):
    env = intake_env
    historical, active = _insert_failed_history_before_active(env)
    active.creation_state = IntakeWorkspaceCreationState.RELEASED_PENDING_CLEANUP
    env["uow"].intake_workspace_ownerships.save(active)
    from minime.adapters.github import GitHubAdapter
    from minime.services.worktree_manager import WorktreeManager

    monkeypatch.setattr(
        GitHubAdapter,
        "_git_auth_bundle",
        lambda _adapter, _url: SimpleNamespace(env={}, secrets=()),
    )
    destination = env["repo"].parent / "released-execution-worktree"
    destination.mkdir()
    result = asyncio.run(
        WorktreeManager(env["repo"], env["uow"])._materialize_verified_published_intake_artifacts(
            destination_worktree=destination,
            project_id="mini-me",
            change_name=env["change_name"],
            job_id="released-job",
        )
    )
    assert result is True
    assert (destination / "openspec/changes" / env["change_name"] / "proposal.md").is_file()
    assert (
        env["uow"].intake_workspace_ownerships.get_by_id(historical.workspace_id).published_sha
        is None
    )


def test_unpublished_owned_intake_cannot_use_legacy_admission_default(intake_env):
    env = intake_env
    ownership = env["uow"].intake_workspace_ownerships.get_by_id(env["ownership"].workspace_id)
    ownership.publication_state = IntakeWorkspacePublicationState.UNPUBLISHED
    ownership.published_ref = None
    ownership.published_sha = None
    env["uow"].intake_workspace_ownerships.save(ownership)
    env["uow"].changes.save(
        Change(
            project_id="mini-me",
            name=env["change_name"],
            schema_name="feature",
            status=ChangeStatus.READY,
        )
    )

    scheduler = SchedulerService(
        env["uow"],
        project_root=env["repo"],
        readiness_service=ReadinessService(
            env["uow"], openspec_adapter=env["service"].openspec_adapter
        ),
    )
    with pytest.raises(
        IntakeWorkspaceOwnershipSelectionError,
        match="Active intake workspace ownership is not an active published authority",
    ):
        scheduler.admit_work_item("mini-me", env["change_name"], drive_admitted=True)
    assert env["uow"].orchestration_runs.list_runs(is_active=True) == []
    assert env["uow"].jobs.list_active_jobs() == []
