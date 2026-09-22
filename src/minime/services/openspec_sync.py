"""Native OpenSpec delta spec synchronization and change directory archiving."""

from __future__ import annotations

import logging
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path

from minime.domain.enums import ExternalOutcome, ExternalReasonCode, RetrySafety
from minime.domain.models import ExternalActionResult

logger = logging.getLogger(__name__)


class OpenSpecSyncError(RuntimeError):
    """Raised when delta spec synchronization fails validation."""


class OpenSpecSyncService:
    """Natively synchronizes delta specs and archives completed OpenSpec changes."""

    def __init__(self, project_root: str | Path):
        self.project_root = Path(project_root).resolve()

    def sync_change_specs(
        self, openspec_path: str, change_name: str
    ) -> ExternalActionResult[list[str]]:
        """Synchronize all delta specs of a change into main specs under openspec/specs/."""
        change_dir = self.project_root / openspec_path / "changes" / change_name
        change_specs_dir = change_dir / "specs"

        if not change_dir.exists():
            return ExternalActionResult(
                outcome=ExternalOutcome.UNKNOWN,
                source_adapter="openspec_sync",
                reason_code=ExternalReasonCode.UNOBSERVABLE,
                retry_safety=RetrySafety.SAFE,
                data=[],
                error_message=f"OpenSpec change directory does not exist: {change_dir}",
            )

        if not change_specs_dir.exists():
            logger.info("No delta specs directory for change '%s'.", change_name)
            return ExternalActionResult(
                outcome=ExternalOutcome.SUCCESS,
                source_adapter="openspec_sync",
                reason_code=ExternalReasonCode.REUSED_EXISTING,
                retry_safety=RetrySafety.SAFE,
                data=[],
                provider_detail="NO_DELTA_SPECS_SYNC_NOT_REQUIRED",
                error_message="No delta specs directory present for change.",
            )

        synced_capabilities: list[str] = []
        main_specs_dir = self.project_root / openspec_path / "specs"
        main_specs_dir.mkdir(parents=True, exist_ok=True)

        try:
            cap_dirs = [d for d in sorted(change_specs_dir.iterdir()) if d.is_dir()]
            if not cap_dirs:
                return ExternalActionResult(
                    outcome=ExternalOutcome.SUCCESS,
                    source_adapter="openspec_sync",
                    reason_code=ExternalReasonCode.REUSED_EXISTING,
                    retry_safety=RetrySafety.SAFE,
                    data=[],
                    provider_detail="NO_DELTA_SPECS_SYNC_NOT_REQUIRED",
                    error_message="No capability directories found in delta specs.",
                )

            # Preflight validation: verify all capability directories contain readable spec.md before any write
            for cap_dir in cap_dirs:
                delta_spec_file = cap_dir / "spec.md"
                if not delta_spec_file.exists():
                    return ExternalActionResult(
                        outcome=ExternalOutcome.FAILURE,
                        source_adapter="openspec_sync",
                        reason_code=ExternalReasonCode.EVIDENCE_INSUFFICIENT,
                        retry_safety=RetrySafety.SAFE,
                        data=[],
                        error_message=f"Capability directory '{cap_dir.name}' is missing required 'spec.md' artifact.",
                    )
                try:
                    _ = delta_spec_file.read_text(encoding="utf-8")
                except Exception as read_exc:
                    return ExternalActionResult(
                        outcome=ExternalOutcome.FAILURE,
                        source_adapter="openspec_sync",
                        reason_code=ExternalReasonCode.EVIDENCE_INSUFFICIENT,
                        retry_safety=RetrySafety.SAFE,
                        data=[],
                        error_message=f"Capability directory '{cap_dir.name}' spec.md cannot be read: {read_exc}",
                    )

            # Writes begin ONLY after complete preflight succeeds
            synced_capabilities: list[str] = []
            main_specs_dir = self.project_root / openspec_path / "specs"
            main_specs_dir.mkdir(parents=True, exist_ok=True)

            for cap_dir in cap_dirs:
                delta_spec_file = cap_dir / "spec.md"
                capability_name = cap_dir.name
                target_cap_dir = main_specs_dir / capability_name
                target_cap_dir.mkdir(parents=True, exist_ok=True)
                target_spec_file = target_cap_dir / "spec.md"

                delta_content = delta_spec_file.read_text(encoding="utf-8")
                if not target_spec_file.exists():
                    target_spec_file.write_text(delta_content, encoding="utf-8")
                    synced_capabilities.append(capability_name)
                    logger.info("Created main spec for capability '%s'.", capability_name)
                    continue

                main_content = target_spec_file.read_text(encoding="utf-8")
                merged = self._merge_spec_markdown(main_content, delta_content)
                target_spec_file.write_text(merged, encoding="utf-8")
                synced_capabilities.append(capability_name)
                logger.info("Synchronized main spec for capability '%s'.", capability_name)

            if not synced_capabilities:
                return ExternalActionResult(
                    outcome=ExternalOutcome.SUCCESS,
                    source_adapter="openspec_sync",
                    reason_code=ExternalReasonCode.REUSED_EXISTING,
                    retry_safety=RetrySafety.SAFE,
                    data=[],
                    provider_detail="NO_DELTA_SPECS_SYNC_NOT_REQUIRED",
                    error_message="No delta spec files present for change.",
                )

            return ExternalActionResult(
                outcome=ExternalOutcome.SUCCESS,
                source_adapter="openspec_sync",
                reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
                retry_safety=RetrySafety.UNSAFE,
                data=synced_capabilities,
                external_id=f"{openspec_path}/changes/{change_name}",
            )
        except Exception as exc:
            logger.warning("Error during delta spec synchronization for '%s': %s", change_name, exc)
            return ExternalActionResult(
                outcome=ExternalOutcome.AMBIGUOUS,
                source_adapter="openspec_sync",
                reason_code=ExternalReasonCode.POSTCONDITION_NOT_PROVEN,
                retry_safety=RetrySafety.UNKNOWN,
                data=synced_capabilities,
                error_message=f"Delta spec synchronization interrupted or ambiguous: {exc}",
            )

    def _merge_spec_markdown(self, main_text: str, delta_text: str) -> str:
        """Merge delta spec requirements into main spec markdown."""
        req_pattern = re.compile(
            r"(^## Requirement:[\s\S]*?)(?=(^## Requirement:|\Z))",
            re.MULTILINE,
        )
        delta_reqs = req_pattern.findall(delta_text)

        if not delta_reqs:
            if delta_text.strip() not in main_text:
                return main_text.rstrip() + "\n\n" + delta_text.strip() + "\n"
            return main_text

        merged = main_text
        for req_match in delta_reqs:
            req_block = req_match[0].strip()
            title_line = req_block.splitlines()[0].strip()
            escaped_title = re.escape(title_line)
            existing_match = re.search(
                rf"(^{escaped_title}[\s\S]*?)(?=(^## Requirement:|\Z))",
                merged,
                re.MULTILINE,
            )
            if existing_match:
                merged = (
                    merged[: existing_match.start()]
                    + req_block
                    + "\n\n"
                    + merged[existing_match.end() :]
                )
            else:
                merged = merged.rstrip() + "\n\n" + req_block + "\n"

        return merged

    def archive_change(
        self,
        openspec_path: str,
        change_name: str,
        target_date: str | None = None,
    ) -> ExternalActionResult[Path]:
        """Move active change directory to openspec/changes/archive/{date}-{change_name}."""
        change_dir = self.project_root / openspec_path / "changes" / change_name
        archive_root = self.project_root / openspec_path / "changes" / "archive"
        archive_root.mkdir(parents=True, exist_ok=True)

        if re.match(r"^\d{4}-\d{2}-\d{2}-", change_name):
            target_name = change_name
        else:
            date_str = target_date or datetime.now(UTC).strftime("%Y-%m-%d")
            target_name = f"{date_str}-{change_name}"

        target_dir = archive_root / target_name

        if change_dir.exists() and target_dir.exists():
            return ExternalActionResult(
                outcome=ExternalOutcome.AMBIGUOUS,
                source_adapter="openspec_archive",
                reason_code=ExternalReasonCode.POSTCONDITION_NOT_PROVEN,
                retry_safety=RetrySafety.UNKNOWN,
                data=target_dir,
                error_message=f"Archive target collision: '{target_dir}' already exists alongside active change '{change_dir}'.",
            )

        if not change_dir.exists():
            if target_dir.exists():
                logger.info("Change '%s' is already archived at '%s'.", change_name, target_dir)
                return ExternalActionResult(
                    outcome=ExternalOutcome.SUCCESS,
                    source_adapter="openspec_archive",
                    reason_code=ExternalReasonCode.REUSED_EXISTING,
                    retry_safety=RetrySafety.SAFE,
                    data=target_dir,
                    provider_detail="",
                    external_id=str(target_dir),
                )
            alt_dir = self.project_root / openspec_path / "archive" / change_name
            if alt_dir.exists():
                return ExternalActionResult(
                    outcome=ExternalOutcome.SUCCESS,
                    source_adapter="openspec_archive",
                    reason_code=ExternalReasonCode.REUSED_EXISTING,
                    retry_safety=RetrySafety.SAFE,
                    data=alt_dir,
                    provider_detail="",
                    external_id=str(alt_dir),
                )
            return ExternalActionResult(
                outcome=ExternalOutcome.UNKNOWN,
                source_adapter="openspec_archive",
                reason_code=ExternalReasonCode.UNOBSERVABLE,
                retry_safety=RetrySafety.SAFE,
                error_message=f"OpenSpec change directory not found: {change_dir}",
            )

        # Capture expected artifact manifest before moving active change directory
        expected_manifest: list[str] = []
        for std_file in ["proposal.md", "design.md", "tasks.md"]:
            if (change_dir / std_file).exists():
                expected_manifest.append(std_file)
        specs_dir = change_dir / "specs"
        if specs_dir.exists():
            for spec_file in specs_dir.rglob("spec.md"):
                rel_spec = str(spec_file.relative_to(change_dir))
                if rel_spec not in expected_manifest:
                    expected_manifest.append(rel_spec)

        try:
            shutil.move(str(change_dir), str(target_dir))
            if target_dir.exists() and not change_dir.exists():
                logger.info("Archived change '%s' -> '%s'.", change_name, target_dir)
                return ExternalActionResult(
                    outcome=ExternalOutcome.SUCCESS,
                    source_adapter="openspec_archive",
                    reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
                    retry_safety=RetrySafety.UNSAFE,
                    data=target_dir,
                    provider_detail=",".join(expected_manifest),
                    external_id=str(target_dir),
                )
            return ExternalActionResult(
                outcome=ExternalOutcome.AMBIGUOUS,
                source_adapter="openspec_archive",
                reason_code=ExternalReasonCode.POSTCONDITION_NOT_PROVEN,
                retry_safety=RetrySafety.UNKNOWN,
                data=target_dir,
                error_message=f"Archive move incomplete: active directory '{change_dir}' still present.",
            )
        except Exception as exc:
            logger.warning("Failed archiving change '%s': %s", change_name, exc)
            return ExternalActionResult(
                outcome=ExternalOutcome.AMBIGUOUS,
                source_adapter="openspec_archive",
                reason_code=ExternalReasonCode.POSTCONDITION_NOT_PROVEN,
                retry_safety=RetrySafety.UNKNOWN,
                data=target_dir,
                error_message=f"Archive move failed: {exc}",
            )

    def verify_sync(
        self,
        openspec_path: str,
        change_name: str,
        synced_capabilities: ExternalActionResult[list[str]] | list[str],
    ) -> ExternalActionResult[bool]:
        """Confirm synchronized requirements are present in the canonical specs."""
        if isinstance(synced_capabilities, ExternalActionResult):
            if synced_capabilities.outcome != ExternalOutcome.SUCCESS:
                return ExternalActionResult(
                    outcome=synced_capabilities.outcome,
                    source_adapter="openspec_sync",
                    reason_code=synced_capabilities.reason_code,
                    retry_safety=RetrySafety.SAFE,
                    data=False,
                    error_message=f"Sync unverified due to sync outcome '{synced_capabilities.outcome}': {synced_capabilities.error_message}",
                )
            if synced_capabilities.provider_detail == "NO_DELTA_SPECS_SYNC_NOT_REQUIRED":
                return ExternalActionResult(
                    outcome=ExternalOutcome.SUCCESS,
                    source_adapter="openspec_sync",
                    reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
                    retry_safety=RetrySafety.SAFE,
                    data=True,
                    provider_detail="NO_DELTA_SPECS_SYNC_NOT_REQUIRED",
                    error_message="No delta specs required sync; verification passed.",
                )
            caps = synced_capabilities.data or []
        else:
            caps = synced_capabilities
            if not caps:
                change_specs_dir = self.project_root / openspec_path / "changes" / change_name / "specs"
                if not change_specs_dir.exists():
                    return ExternalActionResult(
                        outcome=ExternalOutcome.SUCCESS,
                        source_adapter="openspec_sync",
                        reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
                        retry_safety=RetrySafety.SAFE,
                        data=True,
                        provider_detail="NO_DELTA_SPECS_SYNC_NOT_REQUIRED",
                    )
                return ExternalActionResult(
                    outcome=ExternalOutcome.FAILURE,
                    source_adapter="openspec_sync",
                    reason_code=ExternalReasonCode.EVIDENCE_INSUFFICIENT,
                    retry_safety=RetrySafety.SAFE,
                    data=False,
                    error_message="Delta specs expected but none synchronized.",
                )

        change_specs_dir = self.project_root / openspec_path / "changes" / change_name / "specs"
        main_specs_dir = self.project_root / openspec_path / "specs"

        for capability in caps:
            canonical = main_specs_dir / capability / "spec.md"
            if not canonical.exists():
                return ExternalActionResult(
                    outcome=ExternalOutcome.FAILURE,
                    source_adapter="openspec_sync",
                    reason_code=ExternalReasonCode.EVIDENCE_INSUFFICIENT,
                    retry_safety=RetrySafety.SAFE,
                    data=False,
                    error_message=f"Canonical spec missing for capability '{capability}'.",
                )

            canonical_text = canonical.read_text(encoding="utf-8")
            delta_file = change_specs_dir / capability / "spec.md"
            if not delta_file.exists():
                if not canonical_text.strip():
                    return ExternalActionResult(
                        outcome=ExternalOutcome.FAILURE,
                        source_adapter="openspec_sync",
                        reason_code=ExternalReasonCode.EVIDENCE_INSUFFICIENT,
                        retry_safety=RetrySafety.SAFE,
                        data=False,
                        error_message=f"Canonical spec empty for capability '{capability}'.",
                    )
                continue

            delta_requirements = self._requirement_titles(delta_file.read_text(encoding="utf-8"))
            if any(title not in canonical_text for title in delta_requirements):
                return ExternalActionResult(
                    outcome=ExternalOutcome.FAILURE,
                    source_adapter="openspec_sync",
                    reason_code=ExternalReasonCode.EVIDENCE_INSUFFICIENT,
                    retry_safety=RetrySafety.SAFE,
                    data=False,
                    error_message=f"Canonical spec for '{capability}' missing delta requirement titles.",
                )

        return ExternalActionResult(
            outcome=ExternalOutcome.SUCCESS,
            source_adapter="openspec_sync",
            reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
            retry_safety=RetrySafety.SAFE,
            data=True,
        )

    def verify_archive(
        self,
        openspec_path: str,
        change_name: str,
        archived_path: ExternalActionResult[Path] | Path | None,
        expected_manifest: list[str] | None = None,
    ) -> ExternalActionResult[bool]:
        """Confirm active change directory is gone, archive target exists, and all expected artifacts are preserved."""
        target_dir: Path | None = None
        manifest: list[str] = expected_manifest or []

        if isinstance(archived_path, ExternalActionResult):
            if archived_path.outcome == ExternalOutcome.AMBIGUOUS:
                return ExternalActionResult(
                    outcome=ExternalOutcome.AMBIGUOUS,
                    source_adapter="openspec_archive",
                    reason_code=ExternalReasonCode.POSTCONDITION_NOT_PROVEN,
                    retry_safety=RetrySafety.UNKNOWN,
                    data=False,
                    error_message=f"Archive unverified due to ambiguous archive outcome: {archived_path.error_message}",
                )
            if archived_path.outcome == ExternalOutcome.UNKNOWN:
                return ExternalActionResult(
                    outcome=ExternalOutcome.UNKNOWN,
                    source_adapter="openspec_archive",
                    reason_code=ExternalReasonCode.UNOBSERVABLE,
                    retry_safety=RetrySafety.SAFE,
                    data=False,
                    error_message=f"Archive unverified due to unknown archive outcome: {archived_path.error_message}",
                )
            if archived_path.outcome == ExternalOutcome.FAILURE:
                return ExternalActionResult(
                    outcome=ExternalOutcome.FAILURE,
                    source_adapter="openspec_archive",
                    reason_code=archived_path.reason_code,
                    retry_safety=RetrySafety.SAFE,
                    data=False,
                    error_message=f"Archive failed: {archived_path.error_message}",
                )
            target_dir = archived_path.data
            if not manifest and archived_path.provider_detail:
                manifest = [f.strip() for f in archived_path.provider_detail.split(",") if f.strip()]
        elif isinstance(archived_path, Path):
            target_dir = archived_path

        change_dir = self.project_root / openspec_path / "changes" / change_name

        if change_dir.exists() and target_dir and target_dir.exists():
            return ExternalActionResult(
                outcome=ExternalOutcome.AMBIGUOUS,
                source_adapter="openspec_archive",
                reason_code=ExternalReasonCode.POSTCONDITION_NOT_PROVEN,
                retry_safety=RetrySafety.UNKNOWN,
                data=False,
                error_message=f"Active change directory '{change_dir}' still exists alongside archive target '{target_dir}'.",
            )

        if change_dir.exists() and (not target_dir or not target_dir.exists()):
            return ExternalActionResult(
                outcome=ExternalOutcome.FAILURE,
                source_adapter="openspec_archive",
                reason_code=ExternalReasonCode.EVIDENCE_INSUFFICIENT,
                retry_safety=RetrySafety.SAFE,
                data=False,
                error_message=f"Active change directory '{change_dir}' is intact and target archive does not exist.",
            )

        if not change_dir.exists() and target_dir and target_dir.exists():
            if not manifest:
                return ExternalActionResult(
                    outcome=ExternalOutcome.UNKNOWN,
                    source_adapter="openspec_archive",
                    reason_code=ExternalReasonCode.EVIDENCE_INSUFFICIENT,
                    retry_safety=RetrySafety.SAFE,
                    data=False,
                    error_message=f"Historical expected manifest unavailable for target archive '{target_dir}'; archive completeness cannot be proven independently.",
                )

            missing_or_corrupt: list[str] = []
            for rel_path in manifest:
                artifact = target_dir / rel_path
                if not artifact.exists() or (artifact.is_file() and artifact.stat().st_size == 0):
                    missing_or_corrupt.append(rel_path)

            if missing_or_corrupt:
                return ExternalActionResult(
                    outcome=ExternalOutcome.FAILURE,
                    source_adapter="openspec_archive",
                    reason_code=ExternalReasonCode.EVIDENCE_INSUFFICIENT,
                    retry_safety=RetrySafety.SAFE,
                    data=False,
                    error_message=f"Archive artifact verification failed: missing or empty expected files: {missing_or_corrupt}",
                )

            return ExternalActionResult(
                outcome=ExternalOutcome.SUCCESS,
                source_adapter="openspec_archive",
                reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
                retry_safety=RetrySafety.SAFE,
                data=True,
            )

        return ExternalActionResult(
            outcome=ExternalOutcome.UNKNOWN,
            source_adapter="openspec_archive",
            reason_code=ExternalReasonCode.UNOBSERVABLE,
            retry_safety=RetrySafety.SAFE,
            data=False,
            error_message="Neither active change directory nor target archive directory exists.",
        )

    @staticmethod
    def _requirement_titles(text: str) -> list[str]:
        titles: list[str] = []
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("## Requirement:") or stripped.startswith("### Requirement:"):
                titles.append(stripped)
        return titles

