"""Candidate worktree, base ref, and SHA integrity validation."""

from __future__ import annotations

import subprocess
from pathlib import Path


def resolve_base_branch_sha(
    repo_path: Path,
    base_branch: str,
) -> tuple[str | None, str | None]:
    """Resolve the authoritative SHA of the project's registered base branch from remote-tracking ref origin/<base_branch>."""
    if not repo_path.exists():
        return None, f"Repository path '{repo_path}' does not exist."

    branch_name = base_branch.removeprefix("origin/")
    remote_ref = f"origin/{branch_name}"
    try:
        proc = subprocess.run(
            ["git", "rev-parse", remote_ref],
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode == 0:
            sha = proc.stdout.strip()
            if sha:
                return sha, None
            return None, f"Resolved empty SHA for authoritative remote ref '{remote_ref}'"

        err_detail = proc.stderr.strip() or f"Ref '{remote_ref}' not found"
        return (
            None,
            f"Failed to resolve authoritative base ref '{remote_ref}': {err_detail}",
        )
    except Exception as exc:
        return None, f"Error resolving authoritative base ref '{remote_ref}': {exc}"


def validate_pre_review_integrity(
    worktree_path: Path,
    expected_candidate_sha: str | None,
    expected_base_sha: str | None,
    base_branch: str = "main",
    repo_root_path: Path | None = None,
    checks_passed: bool = True,
) -> tuple[bool, str | None]:
    """Validate candidate worktree state, HEAD SHA, base SHA against registered base ref, and check prerequisites."""
    if not checks_passed:
        return (
            False,
            "Pre-review integrity failure: deterministic checks did not pass.",
        )

    if not worktree_path.exists() or not worktree_path.is_dir():
        return (
            False,
            f"Pre-review integrity failure: candidate worktree directory '{worktree_path}' does not exist.",
        )

    if not expected_candidate_sha:
        return (
            False,
            "Pre-review integrity failure: expected candidate SHA is missing.",
        )

    if not expected_base_sha:
        return (
            False,
            "Pre-review integrity failure: expected base SHA is missing.",
        )

    # 1. Validate worktree HEAD SHA matches expected candidate SHA
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(worktree_path),
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            return (
                False,
                f"Pre-review integrity failure: failed to resolve worktree HEAD SHA: {proc.stderr.strip()}",
            )
        current_head = proc.stdout.strip()
        if current_head != expected_candidate_sha:
            return (
                False,
                f"Candidate SHA mismatch: worktree HEAD is '{current_head}' but expected candidate SHA is '{expected_candidate_sha}'.",
            )
    except Exception as exc:
        return (
            False,
            f"Pre-review integrity error checking worktree SHA: {exc}",
        )

    # 2. Validate base SHA against registered remote tracking base branch ref (origin/<base_branch>)
    ref_lookup_path = (
        repo_root_path
        if (repo_root_path and (repo_root_path / ".git").exists())
        else worktree_path
    )
    resolved_base_sha, base_err = resolve_base_branch_sha(ref_lookup_path, base_branch)
    if not resolved_base_sha:
        return (
            False,
            f"Pre-review base ref resolution failure: {base_err}",
        )

    if resolved_base_sha != expected_base_sha:
        return (
            False,
            f"Base SHA mismatch: registered base branch 'origin/{base_branch}' resolves to '{resolved_base_sha}' but expected base SHA is '{expected_base_sha}'.",
        )

    return True, None


def validate_post_review_integrity(
    worktree_path: Path,
    expected_candidate_sha: str,
) -> tuple[bool, str | None]:
    """Validate that the candidate worktree remained completely unmutated."""
    if not worktree_path.exists() or not worktree_path.is_dir():
        return (
            False,
            f"Post-review integrity failure: worktree '{worktree_path}' was removed or does not exist.",
        )

    # 1. Check git status --porcelain
    try:
        proc_status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(worktree_path),
            capture_output=True,
            text=True,
            check=False,
        )
        if proc_status.returncode != 0:
            return (
                False,
                f"Post-review integrity error running git status: {proc_status.stderr.strip()}",
            )
        status_output = proc_status.stdout.strip()
        if status_output:
            return (
                False,
                f"Unauthorized reviewer mutation: uncommitted changes detected in candidate worktree: {status_output[:200]}",
            )

        # 2. Check git rev-parse HEAD
        proc_head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(worktree_path),
            capture_output=True,
            text=True,
            check=False,
        )
        if proc_head.returncode != 0:
            return (
                False,
                f"Post-review integrity error resolving HEAD SHA: {proc_head.stderr.strip()}",
            )
        current_head = proc_head.stdout.strip()
        if current_head != expected_candidate_sha:
            return (
                False,
                f"Unauthorized reviewer mutation: HEAD SHA changed from '{expected_candidate_sha}' to '{current_head}' during review.",
            )
    except Exception as exc:
        return False, f"Post-review integrity error: {exc}"

    return True, None
