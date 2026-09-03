"""Native OpenSpec delta spec synchronization and change directory archiving."""

from __future__ import annotations

import logging
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)


class OpenSpecSyncError(RuntimeError):
    """Raised when delta spec synchronization fails validation."""


class OpenSpecSyncService:
    """Natively synchronizes delta specs and archives completed OpenSpec changes."""

    def __init__(self, project_root: str | Path):
        self.project_root = Path(project_root).resolve()

    def sync_change_specs(self, openspec_path: str, change_name: str) -> list[str]:
        """Synchronize all delta specs of a change into main specs under openspec/specs/."""
        change_specs_dir = self.project_root / openspec_path / "changes" / change_name / "specs"
        if not change_specs_dir.exists():
            # Check if change has delta specs
            logger.info("No delta specs directory for change '%s'.", change_name)
            return []

        synced_capabilities: list[str] = []
        main_specs_dir = self.project_root / openspec_path / "specs"
        main_specs_dir.mkdir(parents=True, exist_ok=True)

        for cap_dir in sorted(change_specs_dir.iterdir()):
            if not cap_dir.is_dir():
                continue
            delta_spec_file = cap_dir / "spec.md"
            if not delta_spec_file.exists():
                continue

            capability_name = cap_dir.name
            target_cap_dir = main_specs_dir / capability_name
            target_cap_dir.mkdir(parents=True, exist_ok=True)
            target_spec_file = target_cap_dir / "spec.md"

            delta_content = delta_spec_file.read_text(encoding="utf-8")
            if not target_spec_file.exists():
                # Direct creation if main spec doesn't exist yet
                target_spec_file.write_text(delta_content, encoding="utf-8")
                synced_capabilities.append(capability_name)
                logger.info("Created main spec for capability '%s'.", capability_name)
                continue

            # Merge delta into existing main spec
            main_content = target_spec_file.read_text(encoding="utf-8")
            merged = self._merge_spec_markdown(main_content, delta_content)
            target_spec_file.write_text(merged, encoding="utf-8")
            synced_capabilities.append(capability_name)
            logger.info("Synchronized main spec for capability '%s'.", capability_name)

        return synced_capabilities

    def _merge_spec_markdown(self, main_text: str, delta_text: str) -> str:
        """Merge delta spec requirements into main spec markdown."""
        # Parse requirement sections from delta
        # Requirements start with '## Requirement:' or '## ADDED Requirements' / '## MODIFIED Requirements'
        req_pattern = re.compile(
            r"(^## Requirement:[\s\S]*?)(?=(^## Requirement:|\Z))",
            re.MULTILINE,
        )
        delta_reqs = req_pattern.findall(delta_text)

        if not delta_reqs:
            # If no structured requirements found, append delta if not already present
            if delta_text.strip() not in main_text:
                return main_text.rstrip() + "\n\n" + delta_text.strip() + "\n"
            return main_text

        merged = main_text
        for req_match in delta_reqs:
            req_block = req_match[0].strip()
            title_line = req_block.splitlines()[0].strip()
            # If requirement exists in main, replace; else append
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
    ) -> Path:
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

        if not change_dir.exists():
            if target_dir.exists():
                logger.info("Change '%s' is already archived at '%s'.", change_name, target_dir)
                return target_dir
            # Check alternative archive location: openspec/archive/
            alt_dir = self.project_root / openspec_path / "archive" / change_name
            if alt_dir.exists():
                return alt_dir
            raise FileNotFoundError(f"OpenSpec change directory not found: {change_dir}")

        if target_dir.exists():
            logger.info(
                "Target archive '%s' already exists; removing old active change.", target_dir
            )
            shutil.rmtree(change_dir)
            return target_dir

        shutil.move(str(change_dir), str(target_dir))
        logger.info("Archived change '%s' -> '%s'.", change_name, target_dir)
        return target_dir
