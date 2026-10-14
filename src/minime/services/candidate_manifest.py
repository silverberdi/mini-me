"""Candidate manifest generation and reviewer snapshot visibility verification."""

from __future__ import annotations

import hashlib
import logging
import subprocess
from pathlib import Path
from typing import Any

from minime.domain.enums import EvidenceDiagnosticStatus
from minime.domain.models import CandidateManifest, EvidenceDiagnostic

logger = logging.getLogger(__name__)


def compute_file_sha256(path: Path) -> str:
    """Compute SHA-256 hash of a file's contents."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


GENERATED_ARTIFACT_EXTENSIONS = (".pyc", ".pyo")
GENERATED_ARTIFACT_DIRS = ("__pycache__", ".pytest_cache")


def is_generated_runtime_artifact(rel_path: str) -> bool:
    """Check if relative path points to a compiler or runtime generated artifact."""
    p = Path(rel_path)
    if any(part in GENERATED_ARTIFACT_DIRS for part in p.parts):
        return True
    if rel_path.endswith(GENERATED_ARTIFACT_EXTENSIONS):
        return True
    if p.name.startswith(".coverage") or any(part == ".coverage" for part in p.parts):
        return True
    return False


class CandidateArtifactRejectionError(ValueError):
    """Raised when tracked or staged files contain generated compiler or runtime artifacts."""

    def __init__(self, message: str, violating_paths: list[str] | None = None):
        super().__init__(message)
        self.violating_paths = violating_paths or []


def purge_transient_generated_artifacts(worktree_path: str | Path) -> list[str]:
    """Non-destructively remove untracked compiler and runtime artifacts from worktree.

    Tracked files are preserved so that CandidateManifestService can detect and reject them.
    Only untracked/ignored bytecode, cache directories, and test artifacts are purged.
    """
    wt = Path(worktree_path).resolve()
    if not wt.exists() or not wt.is_dir():
        return []

    tracked_proc = subprocess.run(
        ["git", "ls-files"],
        cwd=wt,
        capture_output=True,
        text=True,
        check=False,
    )
    tracked_set = set(tracked_proc.stdout.splitlines()) if tracked_proc.returncode == 0 else set()

    purged: list[str] = []

    # Target directories: __pycache__, .pytest_cache
    for dir_name in GENERATED_ARTIFACT_DIRS:
        for d in list(wt.rglob(dir_name)):
            if not d.is_dir():
                continue
            rel = str(d.relative_to(wt))
            if any(tf == rel or tf.startswith(f"{rel}/") for tf in tracked_set):
                continue
            try:
                import shutil

                shutil.rmtree(d, ignore_errors=True)
                purged.append(rel)
            except Exception:
                pass

    # Target file extensions: .pyc, .pyo, .coverage*
    for pattern in ("*.pyc", "*.pyo", ".coverage*"):
        for f in list(wt.rglob(pattern)):
            if not f.is_file():
                continue
            rel = str(f.relative_to(wt))
            if rel in tracked_set:
                continue
            try:
                f.unlink(missing_ok=True)
                purged.append(rel)
            except Exception:
                pass

    return purged


class CandidateManifestService:
    """Generates immutable candidate manifests and verifies reviewer visibility."""

    def generate_manifest(
        self,
        worktree_path: str | Path,
        candidate_sha: str,
        job_id: str,
        attempt_id: str | None = None,
    ) -> CandidateManifest:
        """Inspect worktree and generate candidate manifest."""
        worktree = Path(worktree_path)

        tracked_files: list[dict[str, Any]] = []
        staged_files: list[dict[str, Any]] = []
        untracked_files: list[dict[str, Any]] = []
        deleted_files: list[str] = []

        try:
            # 1. Tracked files
            ls_proc = subprocess.run(
                ["git", "ls-files"],
                cwd=worktree,
                capture_output=True,
                text=True,
                check=False,
            )
            if ls_proc.returncode == 0:
                for rel_path in ls_proc.stdout.splitlines():
                    clean_rel = rel_path.strip()
                    if clean_rel:
                        full_p = worktree / clean_rel
                        if full_p.is_file():
                            tracked_files.append(
                                {
                                    "path": clean_rel,
                                    "size_bytes": full_p.stat().st_size,
                                    "sha256": compute_file_sha256(full_p),
                                }
                            )
                        else:
                            deleted_files.append(clean_rel)

            # 2. Staged files
            staged_proc = subprocess.run(
                ["git", "diff", "--name-only", "--cached"],
                cwd=worktree,
                capture_output=True,
                text=True,
                check=False,
            )
            if staged_proc.returncode == 0:
                for rel_path in staged_proc.stdout.splitlines():
                    clean_rel = rel_path.strip()
                    if clean_rel:
                        full_p = worktree / clean_rel
                        if full_p.is_file():
                            staged_files.append(
                                {
                                    "path": clean_rel,
                                    "size_bytes": full_p.stat().st_size,
                                    "sha256": compute_file_sha256(full_p),
                                }
                            )

            # 3. Untracked files
            untracked_proc = subprocess.run(
                ["git", "ls-files", "--others", "--exclude-standard"],
                cwd=worktree,
                capture_output=True,
                text=True,
                check=False,
            )
            if untracked_proc.returncode == 0:
                for rel_path in untracked_proc.stdout.splitlines():
                    clean_rel = rel_path.strip()
                    if clean_rel:
                        full_p = worktree / clean_rel
                        if full_p.is_file():
                            untracked_files.append(
                                {
                                    "path": clean_rel,
                                    "size_bytes": full_p.stat().st_size,
                                    "sha256": compute_file_sha256(full_p),
                                }
                            )

            # 4. Deleted files
            deleted_proc = subprocess.run(
                ["git", "ls-files", "--deleted"],
                cwd=worktree,
                capture_output=True,
                text=True,
                check=False,
            )
            if deleted_proc.returncode == 0:
                for rel_path in deleted_proc.stdout.splitlines():
                    clean_rel = rel_path.strip()
                    if clean_rel and clean_rel not in deleted_files:
                        deleted_files.append(clean_rel)

        except Exception as err:
            logger.warning("Error generating candidate manifest via git: %s", err)

        # Check for tracked and staged generated compiler/runtime artifacts
        violating: list[str] = []
        for tf in tracked_files:
            if is_generated_runtime_artifact(tf["path"]):
                violating.append(tf["path"])
        for sf in staged_files:
            if is_generated_runtime_artifact(sf["path"]):
                violating.append(sf["path"])
        if violating:
            violating_sorted = sorted(set(violating))
            raise CandidateArtifactRejectionError(
                f"Candidate rejected: tracked or staged generated compiler/runtime artifacts detected: {violating_sorted}",
                violating_paths=violating_sorted,
            )

        # Strictly exclude untracked generated artifacts from candidate manifest
        untracked_files = [
            uf for uf in untracked_files if not is_generated_runtime_artifact(uf["path"])
        ]

        # Compute deterministic manifest hash over all existing files
        all_manifest_entries: list[str] = []
        for tf in tracked_files:
            all_manifest_entries.append(f"tracked:{tf['path']}:{tf['sha256']}")
        for sf in staged_files:
            all_manifest_entries.append(f"staged:{sf['path']}:{sf['sha256']}")
        for uf in untracked_files:
            all_manifest_entries.append(f"untracked:{uf['path']}:{uf['sha256']}")
        for df in deleted_files:
            all_manifest_entries.append(f"deleted:{df}")

        all_manifest_entries.sort()
        manifest_raw = "\n".join(all_manifest_entries)
        manifest_hash = hashlib.sha256(manifest_raw.encode("utf-8")).hexdigest()

        unique_candidate_paths = {
            f["path"] for f in tracked_files + staged_files + untracked_files if f.get("path")
        }
        total_files_count = len(unique_candidate_paths)

        return CandidateManifest(
            job_id=job_id,
            attempt_id=attempt_id,
            candidate_sha=candidate_sha,
            tracked_files=tracked_files,
            staged_files=staged_files,
            untracked_files=untracked_files,
            deleted_files=deleted_files,
            total_files_count=total_files_count,
            manifest_hash=manifest_hash,
        )

    def verify_reviewer_visibility(
        self,
        manifest: CandidateManifest,
        reviewer_snapshot_path: str | Path,
        job_id: str,
        candidate_sha: str,
        attempt_id: str | None = None,
    ) -> tuple[bool, EvidenceDiagnostic | None]:
        """Verify that the reviewer snapshot contains all candidate files (tracked, staged, untracked)
        and reflects deleted file states.
        """
        snapshot = Path(reviewer_snapshot_path)
        missing_files: list[str] = []
        unexpected_deleted_files: list[str] = []

        # Build deduplicated union of all reviewable candidate file paths
        candidate_paths: set[str] = set()
        for item in manifest.tracked_files:
            if item.get("path"):
                candidate_paths.add(item["path"])
        for item in manifest.staged_files:
            if item.get("path"):
                candidate_paths.add(item["path"])
        for item in manifest.untracked_files:
            if item.get("path"):
                candidate_paths.add(item["path"])

        # Exclude paths that are explicitly marked deleted in candidate
        deleted_set = set(manifest.deleted_files)
        candidate_paths -= deleted_set

        for rel_p in sorted(candidate_paths):
            target_p = snapshot / rel_p
            if not target_p.is_file():
                missing_files.append(rel_p)

        # Validate that deleted files do not exist as regular files in reviewer snapshot
        for df in sorted(deleted_set):
            if df and (snapshot / df).is_file():
                unexpected_deleted_files.append(df)

        if missing_files or unexpected_deleted_files:
            reasons = []
            if missing_files:
                reasons.append(f"{len(missing_files)} candidate files missing from snapshot")
            if unexpected_deleted_files:
                reasons.append(
                    f"{len(unexpected_deleted_files)} deleted files still present in snapshot"
                )
            reason_str = f"Reviewer environment blindness: {'; '.join(reasons)}"

            diagnostic = EvidenceDiagnostic(
                job_id=job_id,
                attempt_id=attempt_id,
                stage_type="REVIEW",
                check_name="reviewer_snapshot_visibility",
                diagnostic_status=EvidenceDiagnosticStatus.REVIEW_ENVIRONMENT_INVALID,
                environment_identity=str(snapshot),
                candidate_sha=candidate_sha,
                reason=reason_str,
                evidence_reference={
                    "missing_files": missing_files,
                    "unexpected_deleted_files": unexpected_deleted_files,
                },
            )
            return False, diagnostic

        return True, None
