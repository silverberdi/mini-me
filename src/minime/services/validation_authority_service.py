"""Validation authority and guided scenario service for mini me.

Evaluates candidate preview eligibility, parses validation scenarios,
binds human validation to exact (head_sha, base_sha, image_digest) tuples,
and evaluates stale validation status.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from minime.config import AppConfig, load_config
from minime.domain.enums import EventType, ValidationVerdict
from minime.domain.interfaces import PersistenceUnitOfWork
from minime.domain.models import (
    Event,
    Project,
    ValidationRun,
    ValidationScenario,
    utc_now,
)
from minime.logging import get_logger

logger = get_logger("services.validation_authority")


class ValidationAuthorityService:
    """Evaluates candidate validation eligibility, authority, and stale invalidation."""

    def __init__(
        self,
        uow: PersistenceUnitOfWork,
        config: AppConfig | None = None,
    ):
        self.uow = uow
        self.config = config or load_config()

    def is_preview_required(
        self,
        project: Project,
        change_name: str,
        project_root: str | Path | None = None,
    ) -> bool:
        """Determine if a change requires container preview and visual validation."""
        deployment_preview = project.deployment_preview or {}
        if deployment_preview.get("required_for_all_changes", False):
            return True

        if deployment_preview.get("required_for_ui_changes", True) is False:
            return False

        # Inspect OpenSpec proposal and specs for explicit 'surface: ui' or UI validation markers
        root = Path(project_root or ".")
        openspec_dir = root / project.openspec_path / "changes" / change_name

        if not openspec_dir.exists():
            archive_candidates = list(
                (root / project.openspec_path / "changes" / "archive").glob(f"*{change_name}*")
            )
            if archive_candidates:
                openspec_dir = archive_candidates[0]

        has_explicit_ui_surface = False
        if openspec_dir.exists():
            files_to_check = []
            proposal_file = openspec_dir / "proposal.md"
            if proposal_file.exists():
                files_to_check.append(proposal_file)

            specs_dir = openspec_dir / "specs"
            if specs_dir.exists():
                files_to_check.extend(list(specs_dir.rglob("*.md")))

            ui_patterns = [
                re.compile(r"surface\s*:\s*['\"]?ui['\"]?", re.IGNORECASE),
                re.compile(r"ui_validation\s*:\s*true", re.IGNORECASE),
                re.compile(r"ui_validation_required\s*:\s*true", re.IGNORECASE),
                re.compile(r"##\s*ui\s+validation\s+required", re.IGNORECASE),
            ]

            for file_path in files_to_check:
                try:
                    text = file_path.read_text(encoding="utf-8")
                    for pattern in ui_patterns:
                        if pattern.search(text):
                            has_explicit_ui_surface = True
                            break
                    if has_explicit_ui_surface:
                        break
                except Exception as e:
                    logger.warning(f"Failed to read file '{file_path}': {e}")

        return has_explicit_ui_surface

    def get_validation_scenarios(
        self,
        project: Project,
        change_name: str,
        project_root: str | Path | None = None,
    ) -> list[ValidationScenario]:
        """Extract or construct guided visual validation scenarios for a change."""
        root = Path(project_root or ".")
        openspec_dir = root / project.openspec_path / "changes" / change_name
        if not openspec_dir.exists():
            archive_candidates = list(
                (root / project.openspec_path / "changes" / "archive").glob(f"*{change_name}*")
            )
            if archive_candidates:
                openspec_dir = archive_candidates[0]

        scenarios: list[ValidationScenario] = []

        if openspec_dir.exists():
            specs_dir = openspec_dir / "specs"
            if specs_dir.exists():
                idx = 1
                for spec_file in sorted(specs_dir.rglob("*.md")):
                    try:
                        text = spec_file.read_text(encoding="utf-8")
                        # Parse #### Scenario: blocks
                        scenario_matches = re.finditer(
                            r"####\s+Scenario:\s*([^\n]+)([\s\S]*?)(?=####|\Z)", text
                        )
                        for match in scenario_matches:
                            title = match.group(1).strip()
                            body = match.group(2).strip()
                            steps = [
                                line.strip()
                                for line in body.splitlines()
                                if line.strip().startswith(("Given", "When", "Then", "And"))
                            ]
                            scenarios.append(
                                ValidationScenario(
                                    scenario_id=f"sc_{idx:02d}",
                                    title=title,
                                    description=body,
                                    ordered_steps=steps or [body],
                                    expected_result="Scenario visible expectations satisfied without defect.",
                                    viewport="desktop",
                                    required=True,
                                )
                            )
                            idx += 1
                    except Exception as e:
                        logger.warning(f"Error parsing scenarios from '{spec_file}': {e}")

        # Fallback scenario if none found in specs
        if not scenarios:
            scenarios.append(
                ValidationScenario(
                    scenario_id="sc_01",
                    title="Core User Flow Validation",
                    description="Navigate to the preview environment and verify all visual and interactive capabilities function correctly.",
                    ordered_steps=[
                        "Navigate to the preview URL",
                        "Verify dashboard/UI renders with correct layout and theme",
                        "Verify no visual anomalies or console errors",
                    ],
                    expected_result="Application renders cleanly with complete functionality.",
                    viewport="desktop",
                    required=True,
                )
            )

        return scenarios

    def evaluate_candidate_validation_authority(
        self,
        project_id: str,
        change_name: str,
        head_sha: str,
        base_sha: str,
        image_digest: str,
    ) -> tuple[bool, ValidationRun | None, bool]:
        """Evaluate if the exact candidate tuple is authorized by a valid non-stale validation.

        Returns:
            (is_authorized, latest_validation_run, is_stale)
        """
        # Look for exact matching validation run
        exact_validation = self.uow.validation_runs.get_latest_for_candidate(
            project_id=project_id,
            change_name=change_name,
            head_sha=head_sha,
            base_sha=base_sha,
            image_digest=image_digest,
        )

        if exact_validation and exact_validation.verdict == ValidationVerdict.PASS:
            return True, exact_validation, False

        # Check if there are older validations for this change that are now stale
        all_validations = self.uow.validation_runs.list_by_change(project_id, change_name)
        if all_validations:
            latest_any = all_validations[0]
            # Has head/base/digest changed?
            is_stale = (
                latest_any.head_sha != head_sha
                or latest_any.base_sha != base_sha
                or latest_any.image_digest != image_digest
            )
            return False, latest_any, is_stale

        return False, None, False

    def record_validation(
        self,
        project_id: str,
        change_name: str,
        head_sha: str,
        base_sha: str,
        image_digest: str,
        verdict: ValidationVerdict,
        scenario_results: list[dict[str, Any]] | None = None,
        run_id: str | None = None,
        preview_id: str | None = None,
        generation: int = 1,
        notes: str | None = None,
        operator: str | None = "operator",
    ) -> ValidationRun:
        """Record an immutable validation run tied strictly to the candidate tuple."""
        validation = ValidationRun(
            preview_id=preview_id,
            project_id=project_id,
            change_name=change_name,
            run_id=run_id,
            candidate_generation=generation,
            head_sha=head_sha,
            base_sha=base_sha,
            image_digest=image_digest,
            verdict=verdict,
            scenario_results=scenario_results or [],
            notes=notes,
            operator=operator,
            created_at=utc_now(),
        )

        self.uow.validation_runs.save(validation)
        self.uow.events.save(
            Event(
                project_id=project_id,
                change_id=change_name,
                event_type=EventType.VALIDATION_SUBMITTED,
                payload={
                    "validation_id": validation.validation_id,
                    "verdict": verdict.value,
                    "head_sha": head_sha,
                    "base_sha": base_sha,
                    "image_digest": image_digest,
                    "generation": generation,
                    "operator": operator,
                },
            )
        )
        self.uow.commit()
        return validation
