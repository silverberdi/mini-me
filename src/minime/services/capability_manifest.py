"""Small, observable manifest and installer for F4 Greenfield capabilities."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any


class CapabilityConflictError(RuntimeError):
    """An existing Greenfield resource differs from the selected capability."""


class CapabilityManifestService:
    """Copy only known mini me skills/helpers, never project or OpenSpec files."""

    _SKILL_ROOTS = (Path(".agents/skills"), Path(".agent/skills"))
    _WORKFLOW_ROOTS = (Path(".agent/workflows"), Path(".agents/workflows"))

    @staticmethod
    def _candidate_files(source_root: Path) -> list[Path]:
        files: list[Path] = []
        for root in CapabilityManifestService._SKILL_ROOTS + CapabilityManifestService._WORKFLOW_ROOTS:
            directory = source_root / root
            if not directory.is_dir():
                continue
            for path in sorted(directory.rglob("*")):
                if not path.is_file() or path.is_symlink():
                    continue
                relative = path.relative_to(source_root)
                if root in CapabilityManifestService._SKILL_ROOTS:
                    allowed = len(relative.parts) > 2 and relative.parts[2].startswith("minime-")
                else:
                    allowed = relative.name.startswith("minime-")
                if allowed:
                    files.append(path)
        return files

    def install_greenfield(self, source_root: str | Path, target_root: str | Path) -> dict[str, Any]:
        source = Path(source_root).resolve(strict=True)
        target = Path(target_root).resolve(strict=True)
        if source == target:
            raise CapabilityConflictError("Capability source and Greenfield target must be isolated")
        installed: list[str] = []
        for source_path in self._candidate_files(source):
            relative = source_path.relative_to(source)
            target_path = target / relative
            if target_path.is_symlink():
                raise CapabilityConflictError(f"Capability target is a symlink: {relative}")
            content = source_path.read_bytes()
            if target_path.exists():
                if not target_path.is_file() or target_path.read_bytes() != content:
                    raise CapabilityConflictError(f"Capability conflict preserved: {relative}")
            else:
                target_path.parent.mkdir(parents=True, exist_ok=True)
                target_path.write_bytes(content)
            installed.append(relative.as_posix())
        return self.inspect(target)

    def inspect(self, target_root: str | Path) -> dict[str, Any]:
        target = Path(target_root).resolve(strict=True)
        files = self._candidate_files(target)
        entries = []
        for path in files:
            relative = path.relative_to(target).as_posix()
            entries.append(
                {
                    "path": relative,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }
            )
        return {
            "manifest_version": "f4-capabilities-v1",
            "files": entries,
            "count": len(entries),
            "greenfield_only": True,
            "source_preserved": True,
        }

    @staticmethod
    def validate_f5_readiness(
        capability_evidence: dict[str, Any],
        official_openspec: dict[str, Any],
        *,
        project_type: str,
    ) -> dict[str, Any]:
        """Record bounded self-host readiness without executing F5."""
        ready = (
            project_type == "GREENFIELD"
            and capability_evidence.get("count", 0) > 0
            and official_openspec.get("complete") is True
        )
        return {
            "status": "READY_FOR_F5_PREPARATION" if ready else "NOT_READY",
            "project_type": project_type,
            "capabilities_observed": capability_evidence.get("count", 0),
            "official_openspec_observed": official_openspec.get("complete") is True,
            "f5_executed": False,
            "brownfield_modified": False,
        }
