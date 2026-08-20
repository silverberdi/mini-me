"""OpenSpec adapter for discovering active changes and checking artifacts."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from minime.domain.enums import ChangeStatus, ReadinessState
from minime.domain.interfaces import OpenSpecAdapterInterface
from minime.domain.models import Change, Project, utc_now
from minime.logging import get_logger

logger = get_logger("adapters.openspec")


class OpenSpecAdapter(OpenSpecAdapterInterface):
    """Adapter for interacting with OpenSpec CLI and structured files."""

    def __init__(self, cli_command: str = "openspec"):
        self.cli_command = cli_command

    def _run_cli(self, args: list[str], cwd: Path) -> dict[str, Any] | None:
        """Run an OpenSpec CLI command and parse JSON output if possible."""
        try:
            cmd = [self.cli_command] + args + ["--json"]
            result = subprocess.run(
                cmd,
                cwd=str(cwd),
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode == 0 and result.stdout.strip():
                return json.loads(result.stdout)
        except Exception as e:
            logger.debug(f"OpenSpec CLI execution error: {e}")
        return None

    def discover_changes(self, project: Project, project_root: str) -> list[Change]:
        """Discover active OpenSpec changes for a registered project."""
        root = Path(project_root)
        changes_dir = root / project.openspec_path / "changes"

        if not changes_dir.exists() or not changes_dir.is_dir():
            logger.debug(f"No OpenSpec changes directory found at {changes_dir}")
            return []

        discovered: list[Change] = []
        now = utc_now()

        for item in sorted(changes_dir.iterdir()):
            if item.is_dir() and item.name != "archive" and not item.name.startswith("."):
                change_name = item.name
                artifacts = self._inspect_artifacts_on_disk(item)

                # Determine schema and stage if available
                cli_status = self._run_cli(["status", "--change", change_name], root)
                schema_name = (
                    cli_status.get("schemaName", "spec-driven") if cli_status else "spec-driven"
                )

                change = Change(
                    project_id=project.project_id,
                    name=change_name,
                    status=ChangeStatus.DISCOVERED,
                    schema_name=schema_name,
                    proposal_path=str(artifacts["proposal"]) if artifacts["proposal"] else None,
                    tasks_path=str(artifacts["tasks"]) if artifacts["tasks"] else None,
                    design_path=str(artifacts["design"]) if artifacts["design"] else None,
                    specs_paths=[str(p) for p in artifacts["specs"]],
                    last_readiness_status=ReadinessState.NOT_READY,
                    last_readiness_reasons=[],
                    discovered_at=now,
                    updated_at=now,
                )
                discovered.append(change)

        return discovered

    def evaluate_artifacts(
        self, project: Project, change_name: str, project_root: str
    ) -> dict[str, Any]:
        """Evaluate artifact presence and validity for a change."""
        root = Path(project_root)
        change_dir = root / project.openspec_path / "changes" / change_name

        if not change_dir.exists():
            return {
                "exists": False,
                "proposal_present": False,
                "tasks_present": False,
                "design_present": False,
                "specs_present": False,
                "specs_count": 0,
                "tasks_count": 0,
                "tasks_remaining": 0,
                "artifacts": {},
            }

        artifacts = self._inspect_artifacts_on_disk(change_dir)
        proposal_present = artifacts["proposal"] is not None
        tasks_present = artifacts["tasks"] is not None
        design_present = artifacts["design"] is not None
        specs_present = len(artifacts["specs"]) > 0

        # Extract tasks metrics if tasks file exists
        tasks_count = 0
        tasks_remaining = 0
        if artifacts["tasks"] and artifacts["tasks"].exists():
            try:
                content = artifacts["tasks"].read_text(encoding="utf-8")
                for line in content.splitlines():
                    trimmed = line.strip()
                    if trimmed.startswith("- [ ]") or trimmed.startswith("- [x]"):
                        tasks_count += 1
                        if trimmed.startswith("- [ ]"):
                            tasks_remaining += 1
            except Exception as e:
                logger.warning(f"Error reading tasks file for {change_name}: {e}")

        return {
            "exists": True,
            "proposal_present": proposal_present,
            "tasks_present": tasks_present,
            "design_present": design_present,
            "specs_present": specs_present,
            "specs_count": len(artifacts["specs"]),
            "tasks_count": tasks_count,
            "tasks_remaining": tasks_remaining,
            "artifacts": {
                "proposal": str(artifacts["proposal"]) if artifacts["proposal"] else None,
                "tasks": str(artifacts["tasks"]) if artifacts["tasks"] else None,
                "design": str(artifacts["design"]) if artifacts["design"] else None,
                "specs": [str(p) for p in artifacts["specs"]],
            },
        }

    def _inspect_artifacts_on_disk(self, change_dir: Path) -> dict[str, Any]:
        """Inspect artifact files directly on the filesystem."""
        proposal_file = change_dir / "proposal.md"
        tasks_file = change_dir / "tasks.md"
        design_file = change_dir / "design.md"
        specs_dir = change_dir / "specs"

        specs_files: list[Path] = []
        if specs_dir.exists() and specs_dir.is_dir():
            for s in specs_dir.rglob("*.md"):
                if s.is_file():
                    specs_files.append(s)

        return {
            "proposal": proposal_file if proposal_file.exists() else None,
            "tasks": tasks_file if tasks_file.exists() else None,
            "design": design_file if design_file.exists() else None,
            "specs": specs_files,
        }
