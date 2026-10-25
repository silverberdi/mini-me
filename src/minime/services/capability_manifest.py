"""Small, observable manifest and installer for F4 Greenfield capabilities."""

from __future__ import annotations

import fcntl
import hashlib
import os
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class CapabilityConflictError(RuntimeError):
    """An existing Greenfield resource differs from the selected capability."""


class CapabilityUnavailableError(RuntimeError):
    """A selected profile requires a capability absent from the trusted source."""


@dataclass(frozen=True)
class GreenfieldCapabilityAuthorization:
    """Verified identity and provenance supplied by the project/worktree authority."""

    project_id: str
    project_type: str
    onboarding_status: str
    binding_project_id: str
    managed_repository_root: str
    worktree_path: str
    worktree_id: str
    worktree_project_id: str
    worktree_state: str
    trusted_predecessor_hashes: dict[str, str]

    def verify(self, target_root: Path, expected_hashes: dict[str, str]) -> None:
        """Fail closed unless the supplied identity is internally consistent."""
        if self.project_type != "GREENFIELD" or self.onboarding_status != "PREPARED":
            raise CapabilityConflictError("Capability reconciliation requires a PREPARED Greenfield project")
        if not self.project_id or self.binding_project_id != self.project_id:
            raise CapabilityConflictError("Capability binding identity is not verified")
        if self.worktree_project_id != self.project_id or not self.worktree_id:
            raise CapabilityConflictError("Capability Worktree identity is not verified")
        if self.worktree_state not in {"CREATED", "PENDING"}:
            raise CapabilityConflictError("Capability Worktree is not managed")
        managed_root = Path(self.managed_repository_root).resolve()
        worktree = Path(self.worktree_path).resolve()
        if target_root != worktree or managed_root not in (worktree, *worktree.parents):
            raise CapabilityConflictError("Capability target is outside the authorized Worktree binding")
        if not expected_hashes or expected_hashes != self.trusted_predecessor_hashes:
            raise CapabilityConflictError("Capability predecessor provenance is not trusted")


@contextmanager
def _reconciliation_lock(target: Path):
    """Serialize reconciliations for one authorized Worktree without changing it."""
    lock_name = hashlib.sha256(str(target).encode("utf-8")).hexdigest()
    lock_path = Path(tempfile.gettempdir()) / f"minime-capability-{lock_name}.lock"
    with lock_path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


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

    def reconcile_greenfield(
        self,
        source_root: str | Path,
        target_root: str | Path,
        *,
        profiles: dict[str, Any],
        expected_existing_hashes: dict[str, str],
        project_type: str,
        authorization: GreenfieldCapabilityAuthorization,
    ) -> dict[str, Any]:
        """Replace only a verified stale Greenfield capability.

        A replacement is permitted only when the current file hash matches
        the recorded predecessor hash. Unselected, symlinked, external, and
        Brownfield paths remain fail-closed.
        """
        if project_type != authorization.project_type:
            raise CapabilityConflictError("Capability project type does not match its authorization")
        source = Path(source_root).resolve(strict=True)
        target = Path(target_root).resolve(strict=True)
        if source == target:
            raise CapabilityConflictError("Capability source and Greenfield target must be isolated")
        authorization.verify(target, expected_existing_hashes)
        selected_paths = self._selected_paths(profiles)
        source_files = self._candidate_files(source, selected_paths)
        available = {path.relative_to(source).as_posix() for path in source_files}
        missing = sorted(selected_paths - available)
        if missing:
            raise CapabilityUnavailableError(
                "Selected profile capabilities are unavailable: " + ", ".join(missing)
            )

        replacements: list[dict[str, str]] = []
        installed: list[str] = []
        with _reconciliation_lock(target):
            plan: list[tuple[Path, str, bytes, str, str | None]] = []
            for source_path in source_files:
                relative = source_path.relative_to(source)
                relative_name = relative.as_posix()
                target_path = target / relative
                cursor = target
                for part in relative.parts[:-1]:
                    cursor /= part
                    if cursor.is_symlink():
                        raise CapabilityConflictError(f"Capability target traverses a symlink: {relative_name}")
                if target_path.is_symlink():
                    raise CapabilityConflictError(f"Capability target is a symlink: {relative_name}")
                source_bytes = source_path.read_bytes()
                source_hash = hashlib.sha256(source_bytes).hexdigest()
                current_hash = None
                if target_path.exists():
                    if not target_path.is_file():
                        raise CapabilityConflictError(f"Capability target is not a file: {relative_name}")
                    current_hash = hashlib.sha256(target_path.read_bytes()).hexdigest()
                    if current_hash != source_hash and current_hash != expected_existing_hashes.get(relative_name):
                        raise CapabilityConflictError(f"Capability conflict preserved: {relative_name}")
                plan.append((target_path, relative_name, source_bytes, source_hash, current_hash))

            # Compare-and-swap immediately before creating any replacement.
            for target_path, relative_name, _, _, planned_hash in plan:
                observed_hash = (
                    hashlib.sha256(target_path.read_bytes()).hexdigest() if target_path.exists() else None
                )
                if observed_hash != planned_hash:
                    raise CapabilityConflictError(f"Capability changed concurrently: {relative_name}")
            for target_path, relative_name, source_bytes, source_hash, current_hash in plan:
                if current_hash == source_hash:
                    installed.append(relative_name)
                    continue
                target_path.parent.mkdir(parents=True, exist_ok=True)
                fd, temporary_name = tempfile.mkstemp(
                    prefix=f".{target_path.name}.", suffix=".minime-tmp", dir=target_path.parent
                )
                try:
                    with os.fdopen(fd, "wb") as temporary:
                        temporary.write(source_bytes)
                        temporary.flush()
                        os.fsync(temporary.fileno())
                    os.replace(temporary_name, target_path)
                finally:
                    if os.path.exists(temporary_name):
                        os.unlink(temporary_name)
                replacements.append(
                    {"path": relative_name, "from_sha256": current_hash or "", "to_sha256": source_hash}
                )
                installed.append(relative_name)
        evidence = self.inspect(target, selected_paths=selected_paths)
        evidence.update({"reconciled": True, "replacements": replacements, "installed": installed})
        return evidence

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
