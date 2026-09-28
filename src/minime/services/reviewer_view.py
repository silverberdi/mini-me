"""Read-only reviewer workspace snapshot manager with symlink safety enforcement."""

from __future__ import annotations

import os
from pathlib import Path


class SymlinkInCandidateError(RuntimeError):
    """Raised when candidate tree contains symlinks that could escape read-only boundary."""

    pass


IGNORED_REVIEW_DIRS = {
    ".venv",
    "venv",
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    ".minime",
    "node_modules",
}


def scan_candidate_for_symlinks(source_path: Path) -> list[str]:
    """Detect any symlinks in candidate files or directories without following links."""
    symlinks: list[str] = []

    if source_path.is_symlink():
        symlinks.append(str(source_path))
        return symlinks

    for root, dirs, files in os.walk(source_path, followlinks=False):
        dirs[:] = [d for d in dirs if d not in IGNORED_REVIEW_DIRS]
        root_path = Path(root)

        # Check directories for symlinks
        for d in list(dirs):
            d_path = root_path / d
            if d_path.is_symlink() or os.path.islink(d_path):
                rel = str(d_path.relative_to(source_path))
                symlinks.append(rel)
                dirs.remove(d)  # Don't descend into directory symlinks

        # Check files for symlinks
        for f in files:
            f_path = root_path / f
            if f_path.is_symlink() or os.path.islink(f_path):
                rel = str(f_path.relative_to(source_path))
                symlinks.append(rel)

    return symlinks


class ReviewerViewManager:
    """Observation-only symlink inspector for candidate trees."""

    def __init__(self, base_dir: Path | str | None = None):
        if base_dir:
            self.base_dir = Path(base_dir)

    def scan_candidate_for_symlinks(self, source_path: Path) -> list[str]:
        """Detect any symlinks in candidate files or directories without following links."""
        return scan_candidate_for_symlinks(source_path)

    def verify_candidate_tree(self, source_path: Path) -> None:
        """Verify candidate tree contains no prohibited symlinks.

        Fails closed if the candidate tree contains any symlinks.
        """
        detected_symlinks = scan_candidate_for_symlinks(source_path)
        if detected_symlinks:
            raise SymlinkInCandidateError(
                f"Candidate tree contains prohibited symlink(s): {', '.join(detected_symlinks[:5])}. "
                "Read-only review view cannot be safely established."
            )

