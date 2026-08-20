"""Read-only reviewer workspace snapshot manager with symlink safety enforcement."""

from __future__ import annotations

import os
import shutil
import stat
from pathlib import Path


class SymlinkInCandidateError(RuntimeError):
    """Raised when candidate tree contains symlinks that could escape read-only boundary."""

    pass


def scan_candidate_for_symlinks(source_path: Path) -> list[str]:
    """Detect any symlinks in candidate files or directories without following links."""
    symlinks: list[str] = []

    if source_path.is_symlink():
        symlinks.append(str(source_path))
        return symlinks

    for root, dirs, files in os.walk(source_path, followlinks=False):
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
    """Manages creation and teardown of OS-level read-only reviewer workspace snapshots."""

    def __init__(self, base_dir: Path):
        self.base_dir = Path(base_dir)

    def view_path(self, view_id: str) -> Path:
        return self.base_dir / ".minime" / "reviewer_views" / view_id

    def create_readonly_view(self, source_path: Path, view_id: str) -> Path:
        """Create a dedicated read-only filesystem snapshot derived from source worktree.

        Fails closed if the candidate tree contains any symlinks.
        """
        # 1. Strict symlink scan - fail closed on any symlink
        detected_symlinks = scan_candidate_for_symlinks(source_path)
        if detected_symlinks:
            raise SymlinkInCandidateError(
                f"Candidate tree contains prohibited symlink(s): {', '.join(detected_symlinks[:5])}. "
                "Read-only review view cannot be safely established."
            )

        target = self.view_path(view_id)
        if target.exists():
            self.cleanup_readonly_view(view_id)

        target.parent.mkdir(parents=True, exist_ok=True)

        # 2. Copy directory tree without preserving symlinks
        shutil.copytree(
            source_path,
            target,
            symlinks=False,
            ignore_dangling_symlinks=False,
        )

        # 3. Recursively remove write permissions from all files and directories
        for root, dirs, files in os.walk(target, followlinks=False):
            root_path = Path(root)
            for f in files:
                f_path = root_path / f
                try:
                    current_mode = f_path.lstat().st_mode
                    # Remove all write bits (u-w, g-w, o-w) -> 0o444
                    f_path.chmod(current_mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
                except OSError:
                    pass

            for d in dirs:
                d_path = root_path / d
                try:
                    current_mode = d_path.lstat().st_mode
                    # Remove all write bits but keep read and exec -> 0o555
                    d_path.chmod(current_mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
                except OSError:
                    pass

        # Make the top-level view directory itself non-writable
        try:
            top_mode = target.lstat().st_mode
            target.chmod(top_mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
        except OSError:
            pass

        # 4. Verify that write denial is active
        test_file = target / ".minime_write_probe"
        try:
            test_file.write_text("probe")
            # If write succeeded, fail closed
            raise RuntimeError(
                f"Failed to establish read-only boundary at '{target}': probe write succeeded."
            )
        except (PermissionError, OSError):
            # Expected: write denial succeeded
            pass

        return target

    def cleanup_readonly_view(self, view_id: str) -> None:
        """Restore write permissions and recursively remove the reviewer snapshot."""
        target = self.view_path(view_id)
        if not target.exists():
            return

        # Recursively restore write permissions so shutil.rmtree can delete
        for root, dirs, files in os.walk(target, followlinks=False):
            root_path = Path(root)
            for d in dirs:
                d_path = root_path / d
                try:
                    current_mode = d_path.lstat().st_mode
                    d_path.chmod(current_mode | stat.S_IWUSR | stat.S_IXUSR)
                except OSError:
                    pass
            for f in files:
                f_path = root_path / f
                try:
                    current_mode = f_path.lstat().st_mode
                    f_path.chmod(current_mode | stat.S_IWUSR)
                except OSError:
                    pass

        try:
            target.chmod(stat.S_IRWXU)
        except OSError:
            pass

        def _handle_remove_readonly(func, path, exc_info):
            try:
                os.chmod(path, stat.S_IWRITE | stat.S_IREAD | stat.S_IEXEC)
                func(path)
            except OSError:
                pass

        shutil.rmtree(target, onerror=_handle_remove_readonly)
