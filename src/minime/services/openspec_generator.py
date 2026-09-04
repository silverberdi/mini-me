"""Deterministic OpenSpec authoring and artifact generation engine."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

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

    def __init__(self, project_root: str | Path = "."):
        self.project_root = Path(project_root).resolve()

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
            "## Requirements",
            "",
            f"### REQ-{spec_slug.upper()}-1: Primary Capability",
            description or f"The system MUST implement {title}.",
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
    ) -> Path:
        """Write the generated OpenSpec change directory and markdown files to disk."""
        target_dir = self.project_root / openspec_path / "changes" / generated.change_name
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
            spec_file = target_dir / rel_spec_path
            spec_file.parent.mkdir(parents=True, exist_ok=True)
            if overwrite or not spec_file.exists():
                spec_file.write_text(spec_text, encoding="utf-8")

        return target_dir

    def write_to_disk(
        self,
        generated: GeneratedOpenSpec,
        openspec_path: str = "openspec",
        overwrite: bool = True,
    ) -> Path:
        """Write generated OpenSpec artifacts to disk."""
        return self.write_change_to_disk(openspec_path, generated, overwrite=overwrite)
