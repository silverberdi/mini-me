"""Context & Backlog Discovery Service for extracting product context and work items."""

from __future__ import annotations

import logging
import re
from pathlib import Path

from minime.adapters.openspec import OpenSpecAdapter
from minime.domain.enums import (
    EventType,
    QueuePriority,
    ReadinessState,
    WorkItemSource,
    WorkItemStatus,
)
from minime.domain.interfaces import PersistenceUnitOfWork
from minime.domain.models import (
    BacklogItem,
    ContextDiscoveryReport,
    DiscoveredContextFact,
    Event,
    utc_now,
)
from minime.services.openspec_generator import slugify

logger = logging.getLogger(__name__)


def parse_priority_text(text: str) -> QueuePriority:
    """Infer queue priority from label or description text."""
    lower = text.lower()
    if "critical" in lower or "p0" in lower or "urgent" in lower:
        return QueuePriority.CRITICAL
    if "high" in lower or "p1" in lower:
        return QueuePriority.HIGH
    if "low" in lower or "p3" in lower:
        return QueuePriority.LOW
    return QueuePriority.NORMAL


class ContextDiscoveryService:
    """Inspects repository context sources to discover facts, structure, and backlog items."""

    def __init__(
        self,
        uow: PersistenceUnitOfWork,
        project_root: str | Path = ".",
        openspec_adapter: OpenSpecAdapter | None = None,
    ):
        self.uow = uow
        self.project_root = Path(project_root).resolve()
        self.openspec_adapter = openspec_adapter or OpenSpecAdapter()

    def discover_context(self, project_id: str) -> ContextDiscoveryReport:
        """Scan repository context sources and reconcile backlog items."""
        project = self.uow.projects.get_by_id(project_id)
        if not project:
            raise ValueError(f"Project '{project_id}' not found.")

        facts: list[DiscoveredContextFact] = []
        inferred_structure: list[str] = []
        missing_context: list[str] = []
        discovered_items: list[BacklogItem] = []

        now = utc_now()
        root = self.project_root

        # 1. Inspect README
        readme_candidates = [root / "README.md", root / "readme.md", root / "README.MD"]
        readme_file = next((f for f in readme_candidates if f.exists()), None)
        if readme_file:
            try:
                content = readme_file.read_text(encoding="utf-8")
                # Extract first heading
                title_match = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
                if title_match:
                    facts.append(
                        DiscoveredContextFact(
                            source_file="README.md",
                            category="PRODUCT_IDENTITY",
                            title="Product Title",
                            detail=title_match.group(1).strip(),
                        )
                    )
                # Check for tech stack indicators
                if "python" in content.lower():
                    facts.append(
                        DiscoveredContextFact(
                            source_file="README.md",
                            category="TECH_STACK",
                            title="Language",
                            detail="Python",
                        )
                    )
                if "fastapi" in content.lower():
                    facts.append(
                        DiscoveredContextFact(
                            source_file="README.md",
                            category="TECH_STACK",
                            title="Framework",
                            detail="FastAPI",
                        )
                    )
            except Exception as exc:
                logger.warning(f"Error reading README: {exc}")
        else:
            missing_context.append("No README.md found in repository root.")

        # 2. Inspect ROADMAP.md
        roadmap_candidates = [
            root / project.roadmap_path,
            root / "docs" / "ROADMAP.md",
            root / "ROADMAP.md",
        ]
        roadmap_file = next((f for f in roadmap_candidates if f.exists()), None)
        if roadmap_file:
            try:
                content = roadmap_file.read_text(encoding="utf-8")
                facts.append(
                    DiscoveredContextFact(
                        source_file=str(roadmap_file.relative_to(root)),
                        category="ROADMAP",
                        title="Roadmap Present",
                        detail=f"Found roadmap file at {roadmap_file.name}",
                    )
                )

                # Parse roadmap sections / milestones (both headings and bullet lists)
                milestone_heading_pattern = re.compile(
                    r"^###?\s+(\d{3}|[0-9]+)\s*[—–-]\s*(.+?)(?:\s*\(`([^`]+)`\))?\s*(?:—\s*(DELIVERED|CURRENT|NEXT|BLOCKED|DONE|READY|BACKLOG))?$",
                    re.MULTILINE,
                )
                milestone_list_pattern = re.compile(
                    r"^[*-]\s+(?:\[[ x]\]\s*)?(\d{3}[a-zA-Z0-9_-]*|[0-9]+[a-zA-Z0-9_-]*|[a-zA-Z0-9_-]+)\s*[:—–-]\s*(.+?)(?:\s*\((DELIVERED|CURRENT|NEXT|BLOCKED|DONE|READY|BACKLOG)\))?$",
                    re.MULTILINE,
                )

                found_keys = set()
                # 1. Check headings
                for match in milestone_heading_pattern.finditer(content):
                    stage_num = match.group(1)
                    title = match.group(2).strip()
                    slug = match.group(3) or f"{stage_num}-{slugify(title)}"
                    state_tag = match.group(4) or "BACKLOG"
                    found_keys.add(slug)

                    inferred_structure.append(f"Milestone {stage_num}: {title} [{state_tag}]")

                    status = WorkItemStatus.BACKLOG
                    if state_tag in ("DELIVERED", "DONE"):
                        status = WorkItemStatus.COMPLETED
                    elif state_tag in ("CURRENT", "READY"):
                        status = WorkItemStatus.READY
                    elif state_tag == "BLOCKED":
                        status = WorkItemStatus.BLOCKED

                    item_key = slug
                    backlog_item = BacklogItem(
                        project_id=project.project_id,
                        item_key=item_key,
                        title=f"{stage_num} {title}",
                        description=f"Roadmap milestone {stage_num}: {title}",
                        priority=parse_priority_text(title),
                        status=status,
                        source=WorkItemSource.ROADMAP,
                        source_location=f"{roadmap_file.relative_to(root)}",
                        dependencies=[],
                        readiness_state=ReadinessState.READY
                        if status in (WorkItemStatus.READY, WorkItemStatus.COMPLETED)
                        else ReadinessState.NOT_READY,
                        openspec_change_name=slug,
                        created_at=now,
                        updated_at=now,
                    )
                    discovered_items.append(backlog_item)

                # 2. Check list items
                for match in milestone_list_pattern.finditer(content):
                    slug = match.group(1).strip()
                    if slug in found_keys:
                        continue
                    found_keys.add(slug)
                    raw_title = match.group(2).strip()
                    state_tag = match.group(3) or "BACKLOG"

                    inferred_structure.append(f"Roadmap Item {slug}: {raw_title} [{state_tag}]")

                    status = WorkItemStatus.BACKLOG
                    if state_tag in ("DELIVERED", "DONE"):
                        status = WorkItemStatus.COMPLETED
                    elif state_tag in ("CURRENT", "READY"):
                        status = WorkItemStatus.READY
                    elif state_tag == "BLOCKED":
                        status = WorkItemStatus.BLOCKED

                    backlog_item = BacklogItem(
                        project_id=project.project_id,
                        item_key=slug,
                        title=raw_title,
                        description=f"Roadmap task: {raw_title}",
                        priority=parse_priority_text(raw_title),
                        status=status,
                        source=WorkItemSource.ROADMAP,
                        source_location=f"{roadmap_file.relative_to(root)}",
                        dependencies=[],
                        readiness_state=ReadinessState.READY
                        if status in (WorkItemStatus.READY, WorkItemStatus.COMPLETED)
                        else ReadinessState.NOT_READY,
                        openspec_change_name=slug,
                        created_at=now,
                        updated_at=now,
                    )
                    discovered_items.append(backlog_item)
            except Exception as exc:
                logger.warning(f"Error parsing ROADMAP: {exc}")
        else:
            missing_context.append(f"Roadmap file '{project.roadmap_path}' not found on disk.")

        # 3. Inspect BACKLOG.md if present
        backlog_candidates = [
            root / project.backlog_path,
            root / "docs" / "BACKLOG.md",
            root / "BACKLOG.md",
        ]
        backlog_file = next(
            (f for f in backlog_candidates if f.exists() and f != roadmap_file), None
        )
        if backlog_file:
            try:
                content = backlog_file.read_text(encoding="utf-8")
                # Parse markdown checkboxes
                for line in content.splitlines():
                    trimmed = line.strip()
                    if trimmed.startswith("- [ ]") or trimmed.startswith("- [x]"):
                        is_done = trimmed.startswith("- [x]")
                        text = trimmed[5:].strip()
                        key = slugify(text)
                        discovered_items.append(
                            BacklogItem(
                                project_id=project.project_id,
                                item_key=key,
                                title=text,
                                description=f"Backlog task: {text}",
                                priority=parse_priority_text(text),
                                status=WorkItemStatus.COMPLETED
                                if is_done
                                else WorkItemStatus.BACKLOG,
                                source=WorkItemSource.LOCAL_BACKLOG,
                                source_location=f"{backlog_file.relative_to(root)}",
                                created_at=now,
                                updated_at=now,
                            )
                        )
            except Exception as exc:
                logger.warning(f"Error reading BACKLOG.md: {exc}")

        # 4. Check OpenSpec directory
        openspec_dir = root / project.openspec_path
        if openspec_dir.exists() and openspec_dir.is_dir():
            facts.append(
                DiscoveredContextFact(
                    source_file=project.openspec_path,
                    category="OPENSPEC",
                    title="OpenSpec Configuration",
                    detail=f"OpenSpec directory found at '{project.openspec_path}'",
                )
            )
            # Inspect existing active changes
            changes = self.openspec_adapter.discover_changes(project, str(root))
            for change in changes:
                inferred_structure.append(f"Active OpenSpec Change: {change.name}")
        else:
            missing_context.append(
                f"OpenSpec path '{project.openspec_path}' does not exist on disk."
            )

        # 5. Check Project Check Configuration
        if not project.checks:
            missing_context.append(
                "No deterministic checks configured in project policy (e.g. pytest / test suite)."
            )
        else:
            facts.append(
                DiscoveredContextFact(
                    source_file="project_policy",
                    category="CHECKS",
                    title="Configured Checks",
                    detail=f"{len(project.checks)} check command(s) registered.",
                )
            )

        # 6. Reconcile discovered items into PostgreSQL non-destructively
        for item in discovered_items:
            existing = self.uow.backlog_items.get_by_project_and_key(project_id, item.item_key)
            if not existing:
                self.uow.backlog_items.save(item)
            else:
                # Update metadata if item is still in default backlog state without overwriting manual edits
                if (
                    existing.status == WorkItemStatus.BACKLOG
                    and item.status != WorkItemStatus.BACKLOG
                ):
                    updated = existing.model_copy(
                        update={
                            "status": item.status,
                            "readiness_state": item.readiness_state,
                            "updated_at": now,
                        }
                    )
                    self.uow.backlog_items.save(updated)

        # Save event
        event = Event(
            event_type=EventType.CONTEXT_DISCOVERED,
            project_id=project_id,
            payload={
                "project_id": project_id,
                "facts_count": len(facts),
                "inferred_count": len(inferred_structure),
                "missing_count": len(missing_context),
                "items_count": len(discovered_items),
            },
            timestamp=now,
        )
        self.uow.events.save(event)
        self.uow.commit()

        return ContextDiscoveryReport(
            project_id=project_id,
            discovered_facts=facts,
            inferred_structure=inferred_structure,
            missing_required_context=missing_context,
            discovered_items_count=len(discovered_items),
            discovered_at=now,
        )

    def discover_and_sync_backlog(
        self,
        project_id: str,
        operator_email: str | None = None,
    ) -> list[BacklogItem]:
        """Discover context and return the complete synced backlog for a project."""
        self.discover_context(project_id)
        return self.uow.backlog_items.list_by_project(project_id)
