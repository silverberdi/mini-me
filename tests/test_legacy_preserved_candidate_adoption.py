"""Real-Git coverage for adopting pre-hotfix preserved candidate refs."""

from __future__ import annotations

import pytest
from tests.test_human_resolution_real_git import git, make_repo, make_service

from minime.domain.enums import EventType


def legacy_service(in_memory_uow, repo, base_a, candidate_sha):
    service, run_id = make_service(
        in_memory_uow, repo, base_a, candidate_sha, candidate_ref=None
    )
    return service, run_id


def valid_ref(run_id: str, job_id: str, change_name: str) -> str:
    return f"refs/heads/minime/{change_name}-{job_id}"


def prepare_legacy_branch(repo, candidate_sha, job_id="job-human-resolution"):
    ref = valid_ref(
        "run-human-resolution",
        job_id,
        "010-governance-and-recovery-hardening",
    )
    git(repo, "branch", ref.removeprefix("refs/heads/"), candidate_sha)
    return ref


def test_legacy_ref_adoption_validates_real_git_and_continues_resolution(
    tmp_path, in_memory_uow
):
    repo, base_a, candidate_sha, base_b = make_repo(tmp_path, conflict=False)
    ref = prepare_legacy_branch(repo, candidate_sha)
    service, run_id = legacy_service(in_memory_uow, repo, base_a, candidate_sha)
    service.drive_coordinator = lambda run_id, project_root=None: (
        in_memory_uow.orchestration_runs.get_by_id(run_id)
    )

    before = in_memory_uow.orchestration_candidates.get_latest_for_run(run_id)
    resolved = service.resolve_preserved_candidate(
        run_id,
        continue_preserved_candidate=True,
        candidate_ref=ref,
        project_root=repo,
    )

    adopted = in_memory_uow.orchestration_candidates.get_by_id(before.candidate_id)
    assert adopted.candidate_ref == ref
    assert adopted.candidate_sha == before.candidate_sha
    assert adopted.base_sha == before.base_sha
    assert adopted.generation == before.generation
    assert adopted.manifest_id == before.manifest_id
    assert adopted.manifest_hash == before.manifest_hash
    assert git(repo, "rev-parse", ref) == candidate_sha
    assert resolved.current_generation == 2
    assert in_memory_uow.jobs.get_by_id("job-human-resolution").base_sha == base_b

    adoption_events = [
        event
        for event in in_memory_uow.orchestration_stage_events.list_by_run(run_id)
        if event.event_type == EventType.LEGACY_CANDIDATE_REF_ADOPTED.value
    ]
    assert len(adoption_events) == 1
    assert adoption_events[0].evidence_references == {
        "run_id": run_id,
        "job_id": "job-human-resolution",
        "candidate_id": before.candidate_id,
        "candidate_generation": 1,
        "candidate_sha": candidate_sha,
        "adopted_candidate_ref": ref,
    }

    again = service.resolve_preserved_candidate(
        run_id,
        continue_preserved_candidate=True,
        candidate_ref=ref,
        project_root=repo,
    )
    assert again.current_generation == 2
    assert len(in_memory_uow.orchestration_candidates.list_by_run(run_id)) == 2
    assert len(
        [
            event
            for event in in_memory_uow.orchestration_stage_events.list_by_run(run_id)
            if event.event_type == EventType.LEGACY_CANDIDATE_REF_ADOPTED.value
        ]
    ) == 1


@pytest.mark.parametrize(
    ("ref_factory", "message"),
    [
        (
            lambda candidate_sha: "refs/heads/minime/010-governance-and-recovery-hardening-job-human-resolution-wrong",
            "current change/job",
        ),
        (
            lambda candidate_sha: "refs/heads/not-minime/job-human-resolution",
            "current change/job",
        ),
    ],
)
def test_legacy_ref_adoption_rejects_wrong_branch_identity(
    tmp_path, in_memory_uow, ref_factory, message
):
    repo, base_a, candidate_sha, _ = make_repo(tmp_path, conflict=False)
    ref = ref_factory(candidate_sha)
    git(repo, "branch", ref.removeprefix("refs/heads/"), candidate_sha)
    service, run_id = legacy_service(in_memory_uow, repo, base_a, candidate_sha)

    with pytest.raises(ValueError, match=message):
        service.resolve_preserved_candidate(
            run_id,
            continue_preserved_candidate=True,
            candidate_ref=ref,
            project_root=repo,
        )

    assert in_memory_uow.orchestration_candidates.get_latest_for_run(run_id).candidate_ref is None
    assert not in_memory_uow.orchestration_stage_events.list_by_run(run_id)


def test_legacy_ref_adoption_rejects_wrong_sha(tmp_path, in_memory_uow):
    repo, base_a, candidate_sha, _ = make_repo(tmp_path, conflict=False)
    wrong_sha = git(repo, "rev-parse", "main")
    ref = prepare_legacy_branch(repo, wrong_sha)
    service, run_id = legacy_service(in_memory_uow, repo, base_a, candidate_sha)

    with pytest.raises(ValueError, match="authoritative candidate SHA"):
        service.resolve_preserved_candidate(
            run_id,
            continue_preserved_candidate=True,
            candidate_ref=ref,
            project_root=repo,
        )


def test_existing_candidate_ref_does_not_trigger_adoption(tmp_path, in_memory_uow):
    repo, base_a, candidate_sha, _ = make_repo(tmp_path, conflict=False)
    ref = "refs/heads/historical-candidate"
    service, run_id = make_service(in_memory_uow, repo, base_a, candidate_sha, ref)
    service.drive_coordinator = lambda run_id, project_root=None: (
        in_memory_uow.orchestration_runs.get_by_id(run_id)
    )

    service.resolve_preserved_candidate(
        run_id,
        continue_preserved_candidate=True,
        project_root=repo,
    )

    assert not [
        event
        for event in in_memory_uow.orchestration_stage_events.list_by_run(run_id)
        if event.event_type == EventType.LEGACY_CANDIDATE_REF_ADOPTED.value
    ]


def test_legacy_ref_adoption_rejects_contradictory_persisted_ref(
    tmp_path, in_memory_uow
):
    repo, base_a, candidate_sha, _ = make_repo(tmp_path, conflict=False)
    ref = prepare_legacy_branch(repo, candidate_sha)
    service, run_id = make_service(
        in_memory_uow, repo, base_a, candidate_sha, "refs/heads/historical-candidate"
    )

    with pytest.raises(ValueError, match="disagrees"):
        service.resolve_preserved_candidate(
            run_id,
            continue_preserved_candidate=True,
            candidate_ref=ref,
            project_root=repo,
        )


def test_legacy_ref_adoption_requires_explicit_input(tmp_path, in_memory_uow):
    repo, base_a, candidate_sha, _ = make_repo(tmp_path, conflict=False)
    service, run_id = legacy_service(in_memory_uow, repo, base_a, candidate_sha)

    with pytest.raises(ValueError, match="--candidate-ref"):
        service.resolve_preserved_candidate(
            run_id,
            continue_preserved_candidate=True,
            project_root=repo,
        )
