"""Real-Git coverage for adopting pre-hotfix preserved candidate refs."""

from __future__ import annotations

import pytest
from tests.test_human_resolution_real_git import git, make_repo, make_service

from minime.domain.enums import EventType, OrchestrationStage
from minime.domain.models import CandidateManifest, OrchestrationCandidate, OrchestrationStageEvent


def legacy_service(in_memory_uow, repo, base_a, candidate_sha):
    service, run_id = make_service(in_memory_uow, repo, base_a, candidate_sha, candidate_ref=None)
    historical = in_memory_uow.orchestration_candidates.get_latest_for_run(run_id)
    in_memory_uow.orchestration_candidates._store.pop(historical.candidate_id)
    in_memory_uow.candidate_manifests.save(
        CandidateManifest(
            job_id="job-human-resolution",
            candidate_sha=candidate_sha,
            manifest_hash="historical-manifest-hash",
            tracked_files=[{"path": "candidate.txt"}],
            total_files_count=1,
        )
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


def two_generation_legacy_service(
    in_memory_uow, repo, base_a, candidate_sha, base_b, *, bad_sha=None
):
    service, run_id = legacy_service(in_memory_uow, repo, base_a, candidate_sha)
    project = in_memory_uow.projects.get_by_id("mini-me")
    project.checks = []
    in_memory_uow.projects.save(project)
    historical_manifest = in_memory_uow.candidate_manifests.get_by_candidate_sha(
        "job-human-resolution", candidate_sha
    )
    historical = OrchestrationCandidate(
        run_id=run_id,
        generation=1,
        base_sha=base_a,
        candidate_sha=candidate_sha,
        candidate_ref="refs/heads/historical-candidate",
        manifest_id=historical_manifest.manifest_id,
        manifest_hash=historical_manifest.manifest_hash,
        is_frozen=True,
    )
    git(repo, "branch", "current-candidate", base_b)
    current_sha = git(repo, "rev-parse", "refs/heads/current-candidate")
    current = OrchestrationCandidate(
        run_id=run_id,
        generation=2,
        base_sha=base_b,
        candidate_sha=current_sha,
        candidate_ref="refs/heads/current-candidate",
        manifest_id="current-manifest",
        manifest_hash="current-manifest-hash",
        is_frozen=True,
    )
    in_memory_uow.orchestration_candidates.save(historical)
    in_memory_uow.orchestration_candidates.save(current)
    in_memory_uow.orchestration_candidates.supersede(historical.candidate_id, current.candidate_id)
    run = in_memory_uow.orchestration_runs.get_by_id(run_id)
    run.base_sha = base_b
    run.current_generation = 2
    run.current_candidate_sha = current_sha
    in_memory_uow.orchestration_runs.save(run)
    job = in_memory_uow.jobs.get_by_id("job-human-resolution")
    job.base_sha = base_b
    job.candidate_sha = current_sha
    in_memory_uow.jobs.save(job)
    evidence = {
        "run_id": run_id,
        "job_id": job.job_id,
        "candidate_id": historical.candidate_id,
        "candidate_generation": historical.generation,
        "candidate_sha": bad_sha or historical.candidate_sha,
        "base_sha": historical.base_sha,
        "manifest_id": historical.manifest_id,
        "manifest_hash": historical.manifest_hash,
    }
    in_memory_uow.orchestration_stage_events.save(
        OrchestrationStageEvent(
            run_id=run_id,
            from_stage=OrchestrationStage.COMPLEMENTARY_REVIEW,
            to_stage=OrchestrationStage.COMPLEMENTARY_REVIEW,
            event_type=EventType.LEGACY_CANDIDATE_RECORD_ADOPTED.value,
            transition_key=f"historical-adoption-{historical.candidate_id}",
            evidence_references=evidence,
        )
    )
    return service, run_id, historical, current


def test_historical_record_adoption_remains_valid_after_current_generation_advances(
    tmp_path, in_memory_uow
):
    repo, base_a, candidate_sha, base_b = make_repo(tmp_path, conflict=False)
    service, run_id, historical, current = two_generation_legacy_service(
        in_memory_uow, repo, base_a, candidate_sha, base_b
    )
    service.drive_coordinator = lambda run_id, project_root=None: (
        in_memory_uow.orchestration_runs.get_by_id(run_id)
    )

    resolved = service.resolve_preserved_candidate(
        run_id, continue_preserved_candidate=True, project_root=repo
    )

    assert resolved.current_generation == 2
    assert historical.candidate_id != current.candidate_id
    assert (
        in_memory_uow.orchestration_candidates.get_by_id(historical.candidate_id).superseded_by_id
        == current.candidate_id
    )


def test_historical_record_adoption_rejects_contradictory_historical_sha(tmp_path, in_memory_uow):
    repo, base_a, candidate_sha, base_b = make_repo(tmp_path, conflict=False)
    service, run_id, _, _ = two_generation_legacy_service(
        in_memory_uow, repo, base_a, candidate_sha, base_b, bad_sha=git(repo, "rev-parse", "main")
    )

    with pytest.raises(ValueError, match="conflicts with the candidate record"):
        service.resolve_preserved_candidate(
            run_id, continue_preserved_candidate=True, project_root=repo
        )


def test_legacy_ref_adoption_validates_real_git_and_continues_resolution(tmp_path, in_memory_uow):
    repo, base_a, candidate_sha, base_b = make_repo(tmp_path, conflict=False)
    ref = prepare_legacy_branch(repo, candidate_sha)
    service, run_id = legacy_service(in_memory_uow, repo, base_a, candidate_sha)
    service.drive_coordinator = lambda run_id, project_root=None: (
        in_memory_uow.orchestration_runs.get_by_id(run_id)
    )

    resolved = service.resolve_preserved_candidate(
        run_id,
        continue_preserved_candidate=True,
        candidate_ref=ref,
        project_root=repo,
    )

    adopted = in_memory_uow.orchestration_candidates.get_by_generation(run_id, 1)
    assert adopted.candidate_ref == ref
    assert adopted.candidate_sha == candidate_sha
    assert adopted.base_sha == base_a
    assert adopted.generation == 1
    assert adopted.manifest_hash == "historical-manifest-hash"
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
        "candidate_id": adopted.candidate_id,
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
    assert (
        len(
            [
                event
                for event in in_memory_uow.orchestration_stage_events.list_by_run(run_id)
                if event.event_type == EventType.LEGACY_CANDIDATE_REF_ADOPTED.value
            ]
        )
        == 1
    )


@pytest.mark.parametrize(
    ("ref_factory", "message"),
    [
        (
            lambda candidate_sha: (
                "refs/heads/minime/010-governance-and-recovery-hardening-job-human-resolution-wrong"
            ),
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

    assert in_memory_uow.orchestration_candidates.get_latest_for_run(run_id) is None
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


def test_legacy_ref_adoption_rejects_contradictory_persisted_ref(tmp_path, in_memory_uow):
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


def test_legacy_record_adoption_rejects_missing_manifest(tmp_path, in_memory_uow):
    repo, base_a, candidate_sha, _ = make_repo(tmp_path, conflict=False)
    ref = prepare_legacy_branch(repo, candidate_sha)
    service, run_id = make_service(in_memory_uow, repo, base_a, candidate_sha, None)
    historical = in_memory_uow.orchestration_candidates.get_latest_for_run(run_id)
    in_memory_uow.orchestration_candidates._store.pop(historical.candidate_id)

    with pytest.raises(ValueError, match="canonical candidate manifest"):
        service.resolve_preserved_candidate(
            run_id, continue_preserved_candidate=True, candidate_ref=ref, project_root=repo
        )


@pytest.mark.parametrize(
    "field_values, message",
    [
        ({"manifest_hash": ""}, "manifest hash"),
        ({"total_files_count": 0}, "at least one file"),
    ],
)
def test_legacy_record_adoption_rejects_invalid_manifest(
    tmp_path, in_memory_uow, field_values, message
):
    repo, base_a, candidate_sha, _ = make_repo(tmp_path, conflict=False)
    ref = prepare_legacy_branch(repo, candidate_sha)
    service, run_id = legacy_service(in_memory_uow, repo, base_a, candidate_sha)
    manifest = in_memory_uow.candidate_manifests.get_by_candidate_sha(
        "job-human-resolution", candidate_sha
    )
    for field, value in field_values.items():
        setattr(manifest, field, value)
    in_memory_uow.candidate_manifests.save(manifest)

    with pytest.raises(ValueError, match=message):
        service.resolve_preserved_candidate(
            run_id, continue_preserved_candidate=True, candidate_ref=ref, project_root=repo
        )


def test_legacy_record_adoption_rejects_run_job_base_mismatch(tmp_path, in_memory_uow):
    repo, base_a, candidate_sha, base_b = make_repo(tmp_path, conflict=False)
    ref = prepare_legacy_branch(repo, candidate_sha)
    service, run_id = legacy_service(in_memory_uow, repo, base_a, candidate_sha)
    run = in_memory_uow.orchestration_runs.get_by_id(run_id)
    run.base_sha = base_b
    in_memory_uow.orchestration_runs.save(run)

    with pytest.raises(ValueError, match="run and job base SHA equality"):
        service.resolve_preserved_candidate(
            run_id, continue_preserved_candidate=True, candidate_ref=ref, project_root=repo
        )


def test_legacy_record_adoption_rejects_missing_or_invalid_generation(tmp_path, in_memory_uow):
    repo, base_a, candidate_sha, _ = make_repo(tmp_path, conflict=False)
    ref = prepare_legacy_branch(repo, candidate_sha)
    service, run_id = legacy_service(in_memory_uow, repo, base_a, candidate_sha)
    run = in_memory_uow.orchestration_runs.get_by_id(run_id)
    run.current_generation = 0
    in_memory_uow.orchestration_runs.save(run)

    with pytest.raises(ValueError, match="positive run generation"):
        service.resolve_preserved_candidate(
            run_id, continue_preserved_candidate=True, candidate_ref=ref, project_root=repo
        )


def test_legacy_record_adoption_rejects_missing_job_candidate_sha(tmp_path, in_memory_uow):
    repo, base_a, candidate_sha, _ = make_repo(tmp_path, conflict=False)
    ref = prepare_legacy_branch(repo, candidate_sha)
    service, run_id = legacy_service(in_memory_uow, repo, base_a, candidate_sha)
    job = in_memory_uow.jobs.get_by_id("job-human-resolution")
    job.candidate_sha = None
    in_memory_uow.jobs.save(job)

    with pytest.raises(ValueError, match="authoritative job candidate SHA"):
        service.resolve_preserved_candidate(
            run_id, continue_preserved_candidate=True, candidate_ref=ref, project_root=repo
        )


def test_legacy_record_adoption_rejects_non_ancestor_base(tmp_path, in_memory_uow):
    repo, base_a, candidate_sha, base_b = make_repo(tmp_path, conflict=False)
    ref = prepare_legacy_branch(repo, candidate_sha)
    service, run_id = legacy_service(in_memory_uow, repo, base_a, candidate_sha)
    run = in_memory_uow.orchestration_runs.get_by_id(run_id)
    run.base_sha = base_b
    in_memory_uow.orchestration_runs.save(run)
    job = in_memory_uow.jobs.get_by_id("job-human-resolution")
    job.base_sha = base_b
    in_memory_uow.jobs.save(job)

    with pytest.raises(ValueError, match="not an ancestor"):
        service.resolve_preserved_candidate(
            run_id, continue_preserved_candidate=True, candidate_ref=ref, project_root=repo
        )


def test_record_adoption_evidence_without_candidate_fails_closed(tmp_path, in_memory_uow):
    repo, base_a, candidate_sha, _ = make_repo(tmp_path, conflict=False)
    ref = prepare_legacy_branch(repo, candidate_sha)
    service, run_id = legacy_service(in_memory_uow, repo, base_a, candidate_sha)
    manifest = in_memory_uow.candidate_manifests.get_by_candidate_sha(
        "job-human-resolution", candidate_sha
    )
    key = (
        f"{run_id}:LEGACY_CANDIDATE_RECORD_ADOPTED:1:{base_a}:{candidate_sha}:"
        f"{manifest.manifest_hash}"
    )
    in_memory_uow.orchestration_stage_events.save(
        OrchestrationStageEvent(
            run_id=run_id,
            from_stage=OrchestrationStage.COMPLEMENTARY_REVIEW,
            to_stage=OrchestrationStage.COMPLEMENTARY_REVIEW,
            event_type=EventType.LEGACY_CANDIDATE_RECORD_ADOPTED.value,
            transition_key=key,
            evidence_references={"run_id": run_id},
        )
    )

    with pytest.raises(ValueError, match="record adoption evidence exists"):
        service.resolve_preserved_candidate(
            run_id, continue_preserved_candidate=True, candidate_ref=ref, project_root=repo
        )
