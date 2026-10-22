"""Tests for CandidateManifestService and EvidenceDiagnostic generation in ChecksRunner."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from minime.domain.enums import EvidenceDiagnosticStatus
from minime.domain.models import CandidateManifest
from minime.services.candidate_integrity import validate_pre_review_integrity
from minime.services.candidate_manifest import (
    CandidateArtifactRejectionError,
    CandidateManifestService,
    is_generated_runtime_artifact,
    purge_transient_generated_artifacts,
)
from minime.services.checks_runner import ChecksRunner


def test_candidate_manifest_generation_and_hashing(tmp_path: Path):
    # Initialize a dummy git repository in tmp_path
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)

    file_a = tmp_path / "a.py"
    file_a.write_text("print('hello')")
    subprocess.run(["git", "add", "a.py"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=tmp_path, check=True)

    file_b = tmp_path / "b.txt"
    file_b.write_text("untracked text")

    service = CandidateManifestService()
    manifest = service.generate_manifest(
        worktree_path=tmp_path,
        candidate_sha="sha123",
        job_id="job123",
    )

    assert manifest.job_id == "job123"
    assert manifest.candidate_sha == "sha123"
    assert len(manifest.tracked_files) >= 1
    assert any(f["path"] == "a.py" for f in manifest.tracked_files)
    assert any(f["path"] == "b.txt" for f in manifest.untracked_files)
    assert manifest.manifest_hash is not None


def test_verify_reviewer_visibility_detects_blindness(tmp_path: Path):
    service = CandidateManifestService()

    manifest = CandidateManifest(
        manifest_id="m1",
        job_id="job1",
        candidate_sha="cand123",
        tracked_files=[{"path": "src/module.py", "sha256": "h1"}],
        staged_files=[],
        untracked_files=[{"path": "new_file.txt", "sha256": "h2"}],
        deleted_files=[],
        total_files_count=2,
        manifest_hash="hash1",
    )

    # Snapshot directory missing new_file.txt
    snapshot_dir = tmp_path / "snapshot"
    snapshot_dir.mkdir()
    (snapshot_dir / "src").mkdir()
    (snapshot_dir / "src" / "module.py").write_text("ok")

    is_visible, diag = service.verify_reviewer_visibility(
        manifest=manifest,
        reviewer_snapshot_path=snapshot_dir,
        job_id="job1",
        candidate_sha="cand123",
    )

    assert is_visible is False
    assert diag is not None
    assert diag.diagnostic_status == EvidenceDiagnosticStatus.REVIEW_ENVIRONMENT_INVALID
    assert "new_file.txt" in diag.evidence_reference["missing_files"]

    # Now provide new_file.txt
    (snapshot_dir / "new_file.txt").write_text("here")
    is_visible_now, diag_now = service.verify_reviewer_visibility(
        manifest=manifest,
        reviewer_snapshot_path=snapshot_dir,
        job_id="job1",
        candidate_sha="cand123",
    )
    assert is_visible_now is True
    assert diag_now is None


def test_verify_reviewer_visibility_staged_files_presence_and_absence(tmp_path: Path):
    service = CandidateManifestService()

    manifest = CandidateManifest(
        manifest_id="m2",
        job_id="job2",
        candidate_sha="cand456",
        tracked_files=[],
        staged_files=[{"path": "staged_file.py", "sha256": "h_staged"}],
        untracked_files=[],
        deleted_files=[],
        total_files_count=1,
        manifest_hash="hash2",
    )

    snapshot_dir = tmp_path / "snapshot_staged"
    snapshot_dir.mkdir()

    # 1. Staged file missing from reviewer snapshot -> REVIEW_ENVIRONMENT_INVALID
    is_vis, diag = service.verify_reviewer_visibility(
        manifest=manifest,
        reviewer_snapshot_path=snapshot_dir,
        job_id="job2",
        candidate_sha="cand456",
    )
    assert is_vis is False
    assert diag is not None
    assert diag.diagnostic_status == EvidenceDiagnosticStatus.REVIEW_ENVIRONMENT_INVALID
    assert "staged_file.py" in diag.evidence_reference["missing_files"]

    # 2. Staged file present in reviewer snapshot -> visibility passes
    (snapshot_dir / "staged_file.py").write_text("print('staged')")
    is_vis2, diag2 = service.verify_reviewer_visibility(
        manifest=manifest,
        reviewer_snapshot_path=snapshot_dir,
        job_id="job2",
        candidate_sha="cand456",
    )
    assert is_vis2 is True
    assert diag2 is None


def test_verify_reviewer_visibility_deduplicates_tracked_and_staged(tmp_path: Path):
    service = CandidateManifestService()

    # File appears in both tracked_files and staged_files
    manifest = CandidateManifest(
        manifest_id="m3",
        job_id="job3",
        candidate_sha="cand789",
        tracked_files=[{"path": "shared.py", "sha256": "h1"}],
        staged_files=[{"path": "shared.py", "sha256": "h1_new"}],
        untracked_files=[],
        deleted_files=[],
        total_files_count=1,
        manifest_hash="hash3",
    )

    snapshot_dir = tmp_path / "snapshot_shared"
    snapshot_dir.mkdir()
    (snapshot_dir / "shared.py").write_text("shared")

    # 3. Deduplicated path present -> visibility passes without duplicate error
    is_vis, diag = service.verify_reviewer_visibility(
        manifest=manifest,
        reviewer_snapshot_path=snapshot_dir,
        job_id="job3",
        candidate_sha="cand789",
    )
    assert is_vis is True
    assert diag is None


def test_verify_reviewer_visibility_mixed_staged_and_untracked(tmp_path: Path):
    service = CandidateManifestService()

    manifest = CandidateManifest(
        manifest_id="m4",
        job_id="job4",
        candidate_sha="cand101",
        tracked_files=[{"path": "tracked.py", "sha256": "h_t"}],
        staged_files=[{"path": "staged.py", "sha256": "h_s"}],
        untracked_files=[{"path": "untracked.py", "sha256": "h_u"}],
        deleted_files=[],
        total_files_count=3,
        manifest_hash="hash4",
    )

    snapshot_dir = tmp_path / "snapshot_mixed"
    snapshot_dir.mkdir()
    (snapshot_dir / "tracked.py").write_text("t")
    (snapshot_dir / "staged.py").write_text("s")

    # 4. Untracked file missing while tracked and staged exist -> fails with REVIEW_ENVIRONMENT_INVALID
    is_vis, diag = service.verify_reviewer_visibility(
        manifest=manifest,
        reviewer_snapshot_path=snapshot_dir,
        job_id="job4",
        candidate_sha="cand101",
    )
    assert is_vis is False
    assert diag is not None
    assert "untracked.py" in diag.evidence_reference["missing_files"]

    # Supply untracked.py -> passes
    (snapshot_dir / "untracked.py").write_text("u")
    is_vis2, diag2 = service.verify_reviewer_visibility(
        manifest=manifest,
        reviewer_snapshot_path=snapshot_dir,
        job_id="job4",
        candidate_sha="cand101",
    )
    assert is_vis2 is True
    assert diag2 is None


def test_verify_reviewer_visibility_deleted_files_handling(tmp_path: Path):
    service = CandidateManifestService()

    manifest = CandidateManifest(
        manifest_id="m5",
        job_id="job5",
        candidate_sha="cand202",
        tracked_files=[{"path": "kept.py", "sha256": "h_kept"}],
        staged_files=[],
        untracked_files=[],
        deleted_files=["deleted.py"],
        total_files_count=1,
        manifest_hash="hash5",
    )

    snapshot_dir = tmp_path / "snapshot_deleted"
    snapshot_dir.mkdir()
    (snapshot_dir / "kept.py").write_text("kept")

    # 5a. Deleted file is NOT present in snapshot -> passes cleanly, not treated as missing
    is_vis, diag = service.verify_reviewer_visibility(
        manifest=manifest,
        reviewer_snapshot_path=snapshot_dir,
        job_id="job5",
        candidate_sha="cand202",
    )
    assert is_vis is True
    assert diag is None

    # 5b. Deleted file is unexpectedly present in snapshot -> flagged with REVIEW_ENVIRONMENT_INVALID
    (snapshot_dir / "deleted.py").write_text("should be deleted")
    is_vis2, diag2 = service.verify_reviewer_visibility(
        manifest=manifest,
        reviewer_snapshot_path=snapshot_dir,
        job_id="job5",
        candidate_sha="cand202",
    )
    assert is_vis2 is False
    assert diag2 is not None
    assert diag2.diagnostic_status == EvidenceDiagnosticStatus.REVIEW_ENVIRONMENT_INVALID
    assert "deleted.py" in diag2.evidence_reference["unexpected_deleted_files"]


@pytest.mark.asyncio
async def test_checks_runner_diagnostics_classification(tmp_path: Path):
    runner = ChecksRunner()

    # 1. Passing check
    res_pass = await runner.run(
        job_id="job1",
        checks=[{"name": "echo", "command": "echo 'ok'"}],
        worktree_path=tmp_path,
        candidate_sha="sha1",
    )
    assert res_pass.passed is True
    assert len(res_pass.diagnostics) == 1
    assert res_pass.diagnostics[0].diagnostic_status == EvidenceDiagnosticStatus.PASS

    # 2. Failing test check
    res_fail = await runner.run(
        job_id="job1",
        checks=[{"name": "fail_check", "command": "python3 -c 'exit(1)'"}],
        worktree_path=tmp_path,
        candidate_sha="sha1",
    )
    assert res_fail.passed is False
    assert res_fail.diagnostics[0].diagnostic_status == EvidenceDiagnosticStatus.FAIL

    # 3. Environment unavailable check (nonexistent binary)
    res_env = await runner.run(
        job_id="job1",
        checks=[{"name": "missing_binary", "command": "nonexistent_binary_xyz_123"}],
        worktree_path=tmp_path,
        candidate_sha="sha1",
    )
    assert res_env.passed is False
    assert (
        res_env.diagnostics[0].diagnostic_status == EvidenceDiagnosticStatus.ENVIRONMENT_UNAVAILABLE
    )


@pytest.mark.asyncio
async def test_checks_runner_continues_after_failed_check_in_configured_order(tmp_path: Path):
    runner = ChecksRunner()
    result = await runner.run(
        job_id="job-order",
        checks=[
            {"name": "first", "command": f"{sys.executable} -c 'exit(3)'"},
            {"name": "second", "command": f"{sys.executable} -c 'print(\"ran\")'"},
        ],
        worktree_path=tmp_path,
    )

    assert [item.check_name for item in result.results] == ["first", "second"]
    assert [item.check_name for item in result.diagnostics] == ["first", "second"]
    assert result.results[1].output_snippet == "ran\n"
    assert result.passed is False


@pytest.mark.asyncio
async def test_checks_runner_missing_command_does_not_block_later_check(tmp_path: Path):
    runner = ChecksRunner()
    result = await runner.run(
        job_id="job-missing",
        checks=[
            {"name": "missing"},
            {"name": "valid", "command": f"{sys.executable} -c 'print(\"valid\")'"},
        ],
        worktree_path=tmp_path,
    )

    assert [item.check_name for item in result.results] == ["missing", "valid"]
    assert [item.check_name for item in result.diagnostics] == ["missing", "valid"]
    assert result.diagnostics[0].diagnostic_status == EvidenceDiagnosticStatus.FAIL
    assert result.diagnostics[1].diagnostic_status == EvidenceDiagnosticStatus.PASS


@pytest.mark.asyncio
async def test_checks_runner_aggregate_passed_is_false_when_any_check_fails(tmp_path: Path):
    result = await ChecksRunner().run(
        job_id="job-aggregate-fail",
        checks=[
            {"name": "pass", "command": f"{sys.executable} -c 'exit(0)'"},
            {"name": "fail", "command": f"{sys.executable} -c 'exit(1)'"},
        ],
        worktree_path=tmp_path,
    )

    assert result.passed is False
    assert len(result.results) == len(result.diagnostics) == 2


@pytest.mark.asyncio
async def test_checks_runner_aggregate_passed_is_true_when_all_checks_pass(tmp_path: Path):
    result = await ChecksRunner().run(
        job_id="job-aggregate-pass",
        checks=[
            {"name": "first", "command": f"{sys.executable} -c 'exit(0)'"},
            {"name": "second", "command": f"{sys.executable} -c 'exit(0)'"},
        ],
        worktree_path=tmp_path,
    )

    assert result.passed is True
    assert len(result.results) == len(result.diagnostics) == 2


def test_candidate_manifest_rejects_tracked_pyc_files(tmp_path: Path):
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)

    src = tmp_path / "src"
    src.mkdir()
    (src / "app.py").write_text("print('app')")
    pyc = src / "app.cpython-314.pyc"
    pyc.write_bytes(b"\x00\x00\x00\x00bytecode")

    subprocess.run(
        ["git", "add", "src/app.py", "src/app.cpython-314.pyc"], cwd=tmp_path, check=True
    )
    subprocess.run(["git", "commit", "-m", "add pyc"], cwd=tmp_path, check=True)

    service = CandidateManifestService()
    with pytest.raises(CandidateArtifactRejectionError) as exc_info:
        service.generate_manifest(
            worktree_path=tmp_path,
            candidate_sha="sha123",
            job_id="job123",
        )
    assert any("app.cpython-314.pyc" in path for path in exc_info.value.violating_paths)


def test_candidate_manifest_rejects_staged_pycache_artifacts(tmp_path: Path):
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)

    (tmp_path / "base.py").write_text("print('base')")
    subprocess.run(["git", "add", "base.py"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, check=True)

    cache_dir = tmp_path / "__pycache__"
    cache_dir.mkdir()
    (cache_dir / "base.cpython-314.pyc").write_bytes(b"\x00bytecode")
    subprocess.run(
        ["git", "add", "-f", "__pycache__/base.cpython-314.pyc"], cwd=tmp_path, check=True
    )

    service = CandidateManifestService()
    with pytest.raises(CandidateArtifactRejectionError) as exc_info:
        service.generate_manifest(
            worktree_path=tmp_path,
            candidate_sha="sha123",
            job_id="job123",
        )
    assert any("__pycache__" in path for path in exc_info.value.violating_paths)


def test_candidate_manifest_excludes_untracked_transient_bytecode(tmp_path: Path):
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)

    (tmp_path / "module.py").write_text("print('clean')")
    subprocess.run(["git", "add", "module.py"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "clean commit"], cwd=tmp_path, check=True)

    # Pollute worktree with untracked bytecode
    (tmp_path / "transient.pyc").write_bytes(b"\x00bytecode")
    cache_dir = tmp_path / "__pycache__"
    cache_dir.mkdir()
    (cache_dir / "module.cpython-314.pyc").write_bytes(b"\x00bytecode")

    service = CandidateManifestService()
    manifest = service.generate_manifest(
        worktree_path=tmp_path,
        candidate_sha="sha123",
        job_id="job123",
    )
    # Tracked files has only module.py
    assert len(manifest.tracked_files) == 1
    assert manifest.tracked_files[0]["path"] == "module.py"
    # Untracked files strictly excludes transient bytecode
    assert not any(is_generated_runtime_artifact(f["path"]) for f in manifest.untracked_files)
    assert not any("pyc" in f["path"] for f in manifest.untracked_files)


@pytest.mark.asyncio
async def test_checks_runner_isolates_bytecode_via_pythonpycacheprefix(tmp_path: Path):
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)

    script = tmp_path / "check_script.py"
    script.write_text("import os; print('PREFIX=' + os.environ.get('PYTHONPYCACHEPREFIX', 'NONE'))")
    subprocess.run(["git", "add", "check_script.py"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "add script"], cwd=tmp_path, check=True)

    runner = ChecksRunner()
    result = await runner.run(
        job_id="job-cache-iso",
        checks=[
            {"name": "check_prefix", "command": f"{sys.executable} check_script.py"},
        ],
        worktree_path=tmp_path,
    )

    assert result.passed is True
    assert "PREFIX=" in result.results[0].output_snippet
    assert "NONE" not in result.results[0].output_snippet
    assert "/minime/pycache/" in result.results[0].output_snippet
    # Verify no __pycache__ was created inside tmp_path
    assert not (tmp_path / "__pycache__").exists()


def test_non_destructive_remediation_purges_untracked_transient_artifacts(tmp_path: Path):
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)

    (tmp_path / "valid.py").write_text("x = 1\n")
    subprocess.run(["git", "add", "valid.py"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, check=True)

    sha_before = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, capture_output=True, text=True, check=True
    ).stdout.strip()

    # Pollute with untracked pycache and pyc
    cache = tmp_path / "__pycache__"
    cache.mkdir()
    (cache / "valid.cpython-314.pyc").write_bytes(b"byte")
    (tmp_path / "extra.pyc").write_bytes(b"byte")

    purged = purge_transient_generated_artifacts(tmp_path)
    assert len(purged) >= 1
    assert not cache.exists()
    assert not (tmp_path / "extra.pyc").exists()

    # Verify commit SHA and git status are pristine
    sha_after = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, capture_output=True, text=True, check=True
    ).stdout.strip()
    assert sha_before == sha_after

    status_proc = subprocess.run(
        ["git", "status", "--porcelain"], cwd=tmp_path, capture_output=True, text=True, check=True
    )
    assert status_proc.stdout.strip() == ""


def test_non_destructive_remediation_preserves_tracked_artifacts_for_rejection(tmp_path: Path):
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)

    (tmp_path / "tracked.pyc").write_bytes(b"tracked bytecode")
    subprocess.run(["git", "add", "tracked.pyc"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "committed pyc"], cwd=tmp_path, check=True)

    # Purge must NOT delete tracked.pyc
    purged = purge_transient_generated_artifacts(tmp_path)
    assert "tracked.pyc" not in purged
    assert (tmp_path / "tracked.pyc").exists()

    # And CandidateManifestService must reject it
    service = CandidateManifestService()
    with pytest.raises(CandidateArtifactRejectionError):
        service.generate_manifest(
            worktree_path=tmp_path,
            candidate_sha="sha123",
            job_id="job123",
        )


def test_validate_pre_review_integrity_rejects_tracked_pyc(tmp_path: Path):
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)

    (tmp_path / "app.py").write_text("print('app')")
    (tmp_path / "app.pyc").write_bytes(b"byte")
    subprocess.run(["git", "add", "app.py", "app.pyc"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "commit with pyc"], cwd=tmp_path, check=True)

    head_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, capture_output=True, text=True, check=True
    ).stdout.strip()

    # Set up remote tracking ref origin/main
    subprocess.run(["git", "branch", "-M", "main"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "update-ref", "refs/remotes/origin/main", head_sha], cwd=tmp_path, check=True
    )

    ok, err = validate_pre_review_integrity(
        worktree_path=tmp_path,
        expected_candidate_sha=head_sha,
        expected_base_sha=head_sha,
        base_branch="main",
        checks_passed=True,
    )
    assert ok is False
    assert "tracked generated compiler/runtime artifacts" in (err or "")
