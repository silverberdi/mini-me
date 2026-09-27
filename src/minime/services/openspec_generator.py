"""Deterministic OpenSpec authoring and artifact generation engine."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from minime.domain.models import BacklogItem


def slugify(text: str) -> str:
    """Convert arbitrary text to a kebab-case slug."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "-", text)
    return text.strip("-") or "work-item"


@dataclass
class GeneratedOpenSpec:
    """Generated OpenSpec change artifacts."""

    change_name: str
    proposal_content: str
    tasks_content: str
    specs: dict[str, str] = field(default_factory=dict)
    design_content: str | None = None
    is_complete: bool = True
    missing_reasons: list[str] = field(default_factory=list)
    human_questions: list[str] = field(default_factory=list)


class OpenSpecGenerator:
    """Generates standard canonical OpenSpec artifacts from normalized backlog items."""

    def __init__(
        self,
        project_root: str | Path = ".",
        uow: Any | None = None,
    ):
        self.project_root = Path(project_root).resolve()
        self.uow = uow

    def generate_from_backlog_item(
        self,
        item: BacklogItem,
        project_name: str = "mini-me",
    ) -> GeneratedOpenSpec:
        """Generate canonical OpenSpec artifacts for a backlog work item."""
        change_name = item.openspec_change_name or slugify(item.item_key or item.title)

        # Validation of minimum essential product intent
        missing_reasons: list[str] = []
        human_questions: list[str] = []

        title = item.title.strip()
        description = item.description.strip()
        criteria = [c.strip() for c in item.acceptance_criteria if c.strip()]

        if not title:
            missing_reasons.append("Work item title is empty.")
            human_questions.append("What is the primary title and objective of this work item?")

        if not description and not criteria:
            missing_reasons.append("Work item lacks both description and acceptance criteria.")
            human_questions.append(
                f"Please provide the observable functional requirements or acceptance criteria for '{title}'."
            )

        if len(description) < 10 and not criteria:
            missing_reasons.append(
                "Description is too brief and no acceptance criteria are defined."
            )
            human_questions.append(
                f"What are the expected behaviors and testable outcomes for '{title}'?"
            )

        is_complete = len(missing_reasons) == 0

        # Build proposal.md
        proposal_lines = [
            f"# Proposal: {title}",
            "",
            "## Problem Statement",
            description or f"Implement work item: {title}",
            "",
            "## Proposed Change",
            f"Deliver the capabilities and requirements defined for `{change_name}`.",
            "",
        ]
        if criteria:
            proposal_lines.extend(
                [
                    "## Acceptance Criteria",
                    *[f"- {crit}" for crit in criteria],
                    "",
                ]
            )
        proposal_lines.extend(
            [
                "## Non-Goals",
                "- Opportunistic refactoring outside the defined acceptance criteria.",
                "- Undocumented scope changes or speculative features.",
                "",
                "## Capabilities",
                f"- `{slugify(title)}`: {title}",
                "",
            ]
        )
        proposal_content = "\n".join(proposal_lines)

        # Build specs/<capability>/spec.md
        spec_slug = slugify(title)
        spec_lines = [
            f"# Specification: {title}",
            "",
            "## ADDED Requirements",
            "",
            "### Requirement: Primary Capability",
            f"The system SHALL implement {title} as described by the scenarios below.",
            "",
        ]

        if criteria:
            for idx, crit in enumerate(criteria, 1):
                spec_lines.extend(
                    [
                        f"#### Scenario {idx}: {crit}",
                        f"- **GIVEN** the configured environment for `{project_name}`,",
                        "- **WHEN** the capability is invoked,",
                        f"- **THEN** {crit}.",
                        "",
                    ]
                )
        else:
            spec_lines.extend(
                [
                    f"#### Scenario 1: Successful execution of {title}",
                    f"- **GIVEN** the configured environment for `{project_name}`,",
                    "- **WHEN** the capability is executed,",
                    "- **THEN** all tests and deterministic checks MUST pass.",
                    "",
                ]
            )

        specs = {f"specs/{spec_slug}/spec.md": "\n".join(spec_lines)}

        # Build tasks.md
        task_lines = [
            f"# Tasks: {title}",
            "",
            f"## Phase 1: Core Implementation for {title}",
        ]
        if criteria:
            for crit in criteria:
                task_lines.append(f"- [ ] Implement: {crit}")
        else:
            task_lines.append(f"- [ ] Implement core functionality for {title}")
        task_lines.append("- [ ] Verify automated checks and deterministic tests pass")
        task_lines.append("")

        tasks_content = "\n".join(task_lines)

        # Build design.md
        design_lines = [
            f"# Design: {title}",
            "",
            "## Architectural Approach",
            f"Implement {title} within canonical boundaries and existing persistence patterns.",
            "",
            "## Trade-offs & Invariants",
            "- Preserve deterministic validation and auditability.",
            "- Adhere strictly to the defined acceptance criteria.",
            "",
        ]
        design_content = "\n".join(design_lines)

        return GeneratedOpenSpec(
            change_name=change_name,
            proposal_content=proposal_content,
            tasks_content=tasks_content,
            specs=specs,
            design_content=design_content,
            is_complete=is_complete,
            missing_reasons=missing_reasons,
            human_questions=human_questions,
        )

    def write_change_to_disk(
        self,
        openspec_path: str,
        generated: GeneratedOpenSpec,
        overwrite: bool = True,
        project_id: str | None = None,
        uow: Any | None = None,
    ) -> Path:
        """Write the generated OpenSpec change directory and markdown files to disk under authorized MANAGED_REPOSITORY workspace."""
        eff_uow = uow or self.uow
        if not eff_uow or not project_id:
            raise RuntimeError("OpenSpec write denied: uow and project_id are mandatory for disk mutation.")

        # Path confinement check on inputs
        if Path(openspec_path).is_absolute() or ".." in Path(openspec_path).parts:
            raise RuntimeError(f"OpenSpec write denied: openspec_path '{openspec_path}' fails path confinement check.")
        if (
            Path(generated.change_name).is_absolute()
            or ".." in Path(generated.change_name).parts
            or Path(generated.change_name).name != generated.change_name
        ):
            raise RuntimeError(
                f"OpenSpec write denied: change_name '{generated.change_name}' fails path confinement check."
            )

        binding_repo = getattr(eff_uow, "project_managed_repository_bindings", None)
        binding = binding_repo.get_by_project_id(project_id) if binding_repo else None
        from minime.services.workspace_guard import is_binding_fully_valid

        if not is_binding_fully_valid(binding):
            raise RuntimeError(
                f"OpenSpec write denied: missing or invalid ProjectManagedRepositoryBinding for project '{project_id}'."
            )
        base_root = Path(binding.managed_repository_root).resolve()
        openspec_root = (base_root / openspec_path).resolve()

        # Construct final intended change directory and verify containment
        target_dir = (base_root / openspec_path / "changes" / generated.change_name).resolve()
        try:
            target_dir.relative_to(openspec_root)
        except ValueError:
            raise RuntimeError(
                f"OpenSpec write denied: change directory '{target_dir}' escapes OpenSpec root '{openspec_root}'."
            )

        # Validate spec relative paths
        for rel_spec_path in generated.specs.keys():
            if Path(rel_spec_path).is_absolute() or ".." in Path(rel_spec_path).parts:
                raise RuntimeError(
                    f"OpenSpec write denied: spec relative path '{rel_spec_path}' fails path confinement check."
                )
            spec_file = (target_dir / rel_spec_path).resolve()
            try:
                spec_file.relative_to(target_dir)
            except ValueError:
                raise RuntimeError(
                    f"OpenSpec write denied: spec file '{spec_file}' escapes change directory '{target_dir}'."
                )

        from minime.domain.enums import WorkspaceOperation, WorkspaceRole
        from minime.domain.models import WorkspaceMutationRequest
        from minime.services.workspace_guard import ManagedWorkspaceGuard

        guard = ManagedWorkspaceGuard(eff_uow)
        target_path_str = str(target_dir)
        req = WorkspaceMutationRequest(
            project_id=project_id,
            target_path=target_path_str,
            requested_operation=WorkspaceOperation.OPENSPEC_SYNC,
        )
        decision = guard.evaluate_mutation(req)
        if not decision.allowed or decision.workspace_role == WorkspaceRole.RUNTIME:
            raise RuntimeError(
                f"ManagedWorkspaceGuard denied OpenSpec generation write to '{target_path_str}': {decision.provider_detail or decision.reason_code.value}"
            )

        target_dir.mkdir(parents=True, exist_ok=True)

        proposal_file = target_dir / "proposal.md"
        tasks_file = target_dir / "tasks.md"
        design_file = target_dir / "design.md"

        if overwrite or not proposal_file.exists():
            proposal_file.write_text(generated.proposal_content, encoding="utf-8")

        if overwrite or not tasks_file.exists():
            tasks_file.write_text(generated.tasks_content, encoding="utf-8")

        if generated.design_content and (overwrite or not design_file.exists()):
            design_file.write_text(generated.design_content, encoding="utf-8")

        for rel_spec_path, spec_text in generated.specs.items():
            spec_file = (target_dir / rel_spec_path).resolve()
            spec_file.parent.mkdir(parents=True, exist_ok=True)
            if overwrite or not spec_file.exists():
                spec_file.write_text(spec_text, encoding="utf-8")

        return target_dir

    def write_to_disk(
        self,
        generated: GeneratedOpenSpec,
        openspec_path: str = "openspec",
        overwrite: bool = True,
        project_id: str | None = None,
        uow: Any | None = None,
    ) -> Path:
        """Write generated OpenSpec artifacts to disk."""
        return self.write_change_to_disk(openspec_path, generated, overwrite=overwrite, project_id=project_id, uow=uow)
