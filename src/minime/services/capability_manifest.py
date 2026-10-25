"""Small, observable manifest and installer for F4 Greenfield capabilities."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any


class CapabilityConflictError(RuntimeError):
    """An existing Greenfield resource differs from the selected capability."""


class CapabilityUnavailableError(RuntimeError):
    """A selected profile requires a capability absent from the trusted source."""


class CapabilityManifestService:
    """Copy only known mini me skills/helpers, never project or OpenSpec files."""

    _SKILL_ROOTS = (Path(".agents/skills"), Path(".agent/skills"))
    _WORKFLOW_ROOTS = (Path(".agent/workflows"), Path(".agents/workflows"))

    _ROLE_DEFAULTS = {
        "thinking": {"minime-request-normalizer", "minime-engineering-discipline", "minime-real-e2e-proof"},
        "execution": {"minime-engineering-discipline", "minime-real-e2e-proof", "minime-pr-preparer", "minime-safe-retirement"},
        "independent_review": {"minime-engineering-discipline", "minime-real-e2e-proof"},
        "fallback": {"minime-engineering-discipline"},
    }

    @staticmethod
    def _candidate_files(source_root: Path, selected_paths: set[str] | None = None) -> list[Path]:
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
                if allowed and (selected_paths is None or relative.as_posix() in selected_paths):
                    files.append(path)
        return files

    @classmethod
    def _selected_paths(cls, profiles: dict[str, Any]) -> set[str]:
        selected: set[str] = set()
        for role, raw_profile in profiles.items():
            profile = raw_profile.model_dump() if hasattr(raw_profile, "model_dump") else raw_profile
            if not isinstance(profile, dict):
                raise CapabilityUnavailableError(f"Profile '{role}' is not a mapping")
            provider = str(profile.get("agent_id") or "").strip().lower()
            provider_root = ".agent" if provider in {"antigravity", "agy"} else ".agents"
            declared_names: set[str] = set()
            for declared in profile.get("skills") or []:
                name = str(declared).strip().lstrip("$/")
                if name.startswith("minime-"):
                    declared_names.add(name)
            names = declared_names or set(cls._ROLE_DEFAULTS.get(role, set()))
            for name in names:
                selected.add(f"{provider_root}/skills/{name}/SKILL.md")
        return selected

    def install_greenfield(
        self,
        source_root: str | Path,
        target_root: str | Path,
        *,
        profiles: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        source = Path(source_root).resolve(strict=True)
        target = Path(target_root).resolve(strict=True)
        if source == target:
            raise CapabilityConflictError("Capability source and Greenfield target must be isolated")
        selected_paths = self._selected_paths(profiles) if profiles is not None else None
        source_files = self._candidate_files(source, selected_paths)
        if profiles is not None:
            available = {path.relative_to(source).as_posix() for path in source_files}
            missing = sorted(selected_paths - available)
            if missing:
                raise CapabilityUnavailableError(
                    "Selected profile capabilities are unavailable: " + ", ".join(missing)
                )
        installed: list[str] = []
        for source_path in source_files:
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
        return self.inspect(target, selected_paths=selected_paths)

    def inspect(self, target_root: str | Path, *, selected_paths: set[str] | None = None) -> dict[str, Any]:
        target = Path(target_root).resolve(strict=True)
        files = self._candidate_files(target, selected_paths)
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
            "selected_paths": sorted(selected_paths) if selected_paths is not None else None,
        }

    @staticmethod
    def validate_f5_readiness(
        capability_evidence: dict[str, Any],
        official_openspec: dict[str, Any],
        *,
        project_type: str,
        profiles_observed: bool = False,
        worktree_identity_verified: bool = False,
        confinement_verified: bool = False,
        github_binding_verified: bool = False,
    ) -> dict[str, Any]:
        """Record bounded self-host readiness without executing F5."""
        ready = (
            project_type == "GREENFIELD"
            and capability_evidence.get("count", 0) > 0
            and official_openspec.get("complete") is True
            and profiles_observed
            and worktree_identity_verified
            and confinement_verified
            and github_binding_verified
        )
        return {
            "status": "READY_FOR_F5_PREPARATION" if ready else "NOT_READY",
            "project_type": project_type,
            "capabilities_observed": capability_evidence.get("count", 0),
            "official_openspec_observed": official_openspec.get("complete") is True,
            "profiles_observed": profiles_observed,
            "worktree_identity_verified": worktree_identity_verified,
            "confinement_verified": confinement_verified,
            "github_binding_verified": github_binding_verified,
            "f5_executed": False,
            "brownfield_modified": False,
        }
