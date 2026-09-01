"""Work Discovery Service for autonomous backlog and OpenSpec change ingestion."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from minime.adapters.github import GitHubAdapter
from minime.adapters.openspec import OpenSpecAdapter
from minime.domain.enums import (
    ChangeStatus,
    QueuePriority,
    ReadinessState,
)
from minime.domain.interfaces import PersistenceUnitOfWork
from minime.domain.models import (
    ProjectBinding,
    WorkQueueItem,
    utc_now,
)
from minime.services.readiness_service import ReadinessService

logger = logging.getLogger(__name__)


def extract_roadmap_stage(change_name: str) -> int | None:
    """Extract numeric roadmap stage from standard change name prefix (e.g., '016-foo' -> 16)."""
    match = re.match(r"^0*(\d+)", change_name)
    if match:
        try:
            return int(match.group(1))
        except ValueError:
            return None
    return None


def extract_priority_from_labels(labels: list[Any] | None) -> QueuePriority:
    """Extract declared queue priority from GitHub labels."""
    if not labels:
        return QueuePriority.NORMAL

    for label in labels:
        name = label.get("name", "") if isinstance(label, dict) else str(label)
        name_lower = name.lower().strip()
        if "critical" in name_lower or "p0" in name_lower:
            return QueuePriority.CRITICAL
        if "high" in name_lower or "p1" in name_lower:
            return QueuePriority.HIGH
        if "low" in name_lower or "p3" in name_lower:
            return QueuePriority.LOW
        if "normal" in name_lower or "p2" in name_lower:
            return QueuePriority.NORMAL

    return QueuePriority.NORMAL


class WorkDiscoveryService:
    """Discovers and reconciles work items from GitHub Project/Issues and local OpenSpec changes."""

    def __init__(
        self,
        uow: PersistenceUnitOfWork,
        project_root: str | Path = ".",
        openspec_adapter: OpenSpecAdapter | None = None,
        github_adapter: GitHubAdapter | None = None,
        readiness_service: ReadinessService | None = None,
    ):
        self.uow = uow
        self.project_root = Path(project_root).resolve()
        self.openspec_adapter = openspec_adapter or OpenSpecAdapter()
        self.github_adapter = github_adapter or GitHubAdapter()
        self.readiness_service = readiness_service or ReadinessService(
            uow,
            openspec_adapter=self.openspec_adapter,
            github_adapter=self.github_adapter,
        )

    def discover_work(self, project_id: str | None = None) -> list[WorkQueueItem]:
        """Discover, reconcile, and persist candidate work items across registered projects."""
        projects = self.uow.projects.list_all()
        if project_id:
            projects = [p for p in projects if p.project_id == project_id]

        discovered_items: list[WorkQueueItem] = []
        now = utc_now()

        for project in projects:
            # 1. Discover local OpenSpec changes on disk
            try:
                changes = self.openspec_adapter.discover_changes(project, str(self.project_root))
            except Exception as exc:
                logger.warning(
                    f"Failed discovering OpenSpec changes for project '{project.project_id}': {exc}"
                )
                changes = []

            for change in changes:
                existing_change = self.uow.changes.get_by_name(project.project_id, change.name)
                if not existing_change:
                    self.uow.changes.save(change)

            # Reconcile archived changes in DB to ChangeStatus.DONE
            archive_dir = Path(self.project_root) / project.openspec_path / "changes" / "archive"
            archived_names: set[str] = set()
            if archive_dir.exists() and archive_dir.is_dir():
                archived_names = {d.name for d in archive_dir.iterdir() if d.is_dir()}

            active_change_names = {c.name for c in changes}
            all_db_changes = self.uow.changes.list_by_project(project.project_id)
            for db_change in all_db_changes:
                if (
                    db_change.name not in active_change_names
                    and db_change.status != ChangeStatus.DONE
                ):
                    stage_num = extract_roadmap_stage(db_change.name)
                    stage_prefix = f"{stage_num:03d}" if stage_num is not None else None
                    is_archived = db_change.name in archived_names or any(
                        stage_prefix and (stage_prefix in a or f"-{stage_prefix}-" in a)
                        for a in archived_names
                    )
                    if is_archived:
                        updated_change = db_change.model_copy(
                            update={"status": ChangeStatus.DONE, "updated_at": now}
                        )
                        self.uow.changes.save(updated_change)

            # 2. Fetch remote issues from repository
            remote_issues: list[dict[str, Any]] = []
            try:
                remote_issues = self.github_adapter.list_issues(project.repository, state="all")
            except Exception as exc:
                logger.debug(
                    f"Remote issue discovery unavailable for '{project.repository}': {exc}"
                )

            # 3. For each active OpenSpec change, reconcile binding and queue status
            for change in changes:
                change_name = change.name
                stage_num = extract_roadmap_stage(change_name)

                # Reconcile binding
                binding = self.uow.bindings.get_by_project_and_change(
                    project.project_id, change_name
                )
                matched_issue_number: int | None = None
                matched_issue_title: str | None = None
                matched_priority = QueuePriority.NORMAL

                if binding and binding.github_issue_number:
                    matched_issue_number = binding.github_issue_number
                    # Find issue details if available
                    for issue in remote_issues:
                        if issue.get("number") == matched_issue_number:
                            matched_issue_title = issue.get("title")
                            matched_priority = extract_priority_from_labels(issue.get("labels"))
                            break
                else:
                    # Attempt to match from remote issues by change name or number
                    for issue in remote_issues:
                        title = issue.get("title", "")
                        body = issue.get("body", "") or ""
                        issue_num = issue.get("number")
                        if (
                            change_name in title
                            or change_name in body
                            or (stage_num is not None and f"{stage_num:03d}" in title)
                        ):
                            matched_issue_number = issue_num
                            matched_issue_title = title
                            matched_priority = extract_priority_from_labels(issue.get("labels"))

                            # Create or update durable binding
                            if not binding:
                                binding = ProjectBinding(
                                    project_id=project.project_id,
                                    repository=project.repository,
                                    github_issue_number=matched_issue_number,
                                    openspec_change_name=change_name,
                                    is_valid=True,
                                )
                                self.uow.bindings.save(binding)
                            break

                # 4. Evaluate readiness
                readiness_eval = self.readiness_service.evaluate_change_readiness(
                    project_id=project.project_id,
                    change_name=change_name,
                    project_root=str(self.project_root),
                    github_repo=project.repository,
                    github_issue=matched_issue_number,
                )

                # Extract declared dependencies
                dependencies: list[str] = []

                # 5. Check or update existing WorkQueueItem
                existing_queue_item = self.uow.work_queue.get_by_project_and_change(
                    project.project_id, change_name
                )
                discovered_at = existing_queue_item.discovered_at if existing_queue_item else now

                blocked_reason = (
                    "; ".join(readiness_eval.unmet_reasons) if not readiness_eval.is_ready else None
                )

                queue_item_kwargs = {
                    "project_id": project.project_id,
                    "change_name": change_name,
                    "github_issue_number": matched_issue_number,
                    "github_issue_title": matched_issue_title,
                    "priority": matched_priority,
                    "roadmap_stage": stage_num,
                    "dependencies": dependencies,
                    "readiness_state": readiness_eval.status,
                    "unmet_readiness_reasons": readiness_eval.unmet_reasons,
                    "blocked_reason": blocked_reason,
                    "admission_eligible": readiness_eval.is_ready
                    and readiness_eval.status == ReadinessState.READY,
                    "discovered_at": discovered_at,
                    "last_evaluated_at": now,
                }
                if existing_queue_item:
                    queue_item_kwargs["queue_item_id"] = existing_queue_item.queue_item_id

                queue_item = WorkQueueItem(**queue_item_kwargs)
                self.uow.work_queue.save(queue_item)
                discovered_items.append(queue_item)

        self.uow.commit()
        return self.uow.work_queue.list_all(project_id)
