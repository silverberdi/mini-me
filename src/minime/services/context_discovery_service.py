"""Read-only repository-context inspection retained for project configuration."""

from __future__ import annotations

import logging
import re
from pathlib import Path

from minime.adapters.openspec import OpenSpecAdapter
from minime.domain.enums import EventType
from minime.domain.interfaces import PersistenceUnitOfWork
from minime.domain.models import ContextDiscoveryReport, DiscoveredContextFact, Event, utc_now

logger = logging.getLogger(__name__)


class ContextDiscoveryService:
    """Inspects declared context without creating a local ticket/backlog projection."""

    def __init__(
        self,
        uow: PersistenceUnitOfWork,
        project_root: str | Path = ".",
        openspec_adapter: OpenSpecAdapter | None = None,
    ):
        self.uow = uow
        self.project_root = Path(project_root).resolve()
        self.openspec_adapter = openspec_adapter or OpenSpecAdapter()

    def discover_context_pure(self, project_id: str) -> ContextDiscoveryReport:
        project = self.uow.projects.get_by_id(project_id)
        if not project:
            raise ValueError(f"Project '{project_id}' not found.")

        facts: list[DiscoveredContextFact] = []
        structure: list[str] = []
        missing: list[str] = []
        root = self.project_root
        readme = next((root / name for name in ("README.md", "readme.md", "README.MD") if (root / name).exists()), None)
        if readme:
            try:
                content = readme.read_text(encoding="utf-8")
                title = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
                if title:
                    facts.append(DiscoveredContextFact(source_file=readme.name, category="PRODUCT_IDENTITY", title="Product Title", detail=title.group(1).strip()))
            except OSError as exc:
                logger.warning("Unable to read repository README: %s", exc)
        else:
            missing.append("No README.md found in repository root.")

        openspec_root = root / project.openspec_path
        if openspec_root.is_dir():
            facts.append(DiscoveredContextFact(source_file=project.openspec_path, category="OPENSPEC", title="OpenSpec Configuration", detail="OpenSpec directory found."))
            for change in self.openspec_adapter.discover_changes(project, str(root)):
                structure.append(f"Active OpenSpec Change: {change.name}")
        else:
            missing.append(f"OpenSpec path '{project.openspec_path}' does not exist on disk.")

        if project.checks:
            facts.append(DiscoveredContextFact(source_file="project_policy", category="CHECKS", title="Configured Checks", detail=f"{len(project.checks)} check command(s) registered."))
        else:
            missing.append("No deterministic checks configured in project policy.")

        return ContextDiscoveryReport(
            project_id=project_id,
            discovered_facts=facts,
            inferred_structure=structure,
            missing_required_context=missing,
            discovered_items_count=0,
            discovered_at=utc_now(),
        )

    def discover_context(self, project_id: str) -> ContextDiscoveryReport:
        report = self.discover_context_pure(project_id)
        self.uow.events.save(Event(event_type=EventType.CONTEXT_DISCOVERED, project_id=project_id, payload={"project_id": project_id, "facts_count": len(report.discovered_facts), "items_count": 0}, timestamp=report.discovered_at))
        self.uow.commit()
        return report
