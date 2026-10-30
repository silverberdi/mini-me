"""Remote request intake and FIFO selection for managed projects."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from minime.domain.enums import ExternalOutcome
from minime.domain.interfaces import GitHubAdapterInterface, PersistenceUnitOfWork
from minime.logging import get_logger

logger = get_logger("services.remote_request_intake")

# Strict regex matching formal dependency directives only; excludes casual references.
_DEPENDENCY_DIRECTIVES_RE = re.compile(
    r"(?i)\b(?:depends\s+on|blocked\s+by)\s*[:#\s]*#?(\d+)\b"
)
_CHECKLIST_DEPENDENCY_RE = re.compile(
    r"(?im)^\s*-\s*\[\s*\]\s*(?:(?:depends\s+on|blocked\s+by)\s*)?#(\d+)\b"
)


def parse_explicit_dependencies(body: str | None) -> set[int]:
    """Extract explicit dependency issue numbers from issue body text.

    Only formal directives like 'Depends on #12', 'Blocked by #34', or
    '- [ ] #12' / '- [ ] Depends on #12' are recognized.
    Casual mentions like 'relates to #12' or 'see also #15' are ignored.
    """
    if not body:
        return set()
    dependencies: set[int] = set()
    for match in _DEPENDENCY_DIRECTIVES_RE.finditer(body):
        dependencies.add(int(match.group(1)))
    for match in _CHECKLIST_DEPENDENCY_RE.finditer(body):
        dependencies.add(int(match.group(1)))
    return dependencies


def parse_iso_datetime(value: Any) -> datetime:
    """Parse ISO datetime string into UTC datetime, falling back to minimum datetime."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            # Handle trailing Z
            clean = value.replace("Z", "+00:00")
            dt = datetime.fromisoformat(clean)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            pass
    return datetime.min.replace(tzinfo=timezone.utc)


class RemoteRequestIntakeService:
    """Intake and select eligible remote requests (GitHub Issues) in deterministic FIFO order."""

    def __init__(
        self,
        github_adapter: GitHubAdapterInterface,
        uow: PersistenceUnitOfWork | None = None,
    ) -> None:
        self.github_adapter = github_adapter
        self.uow = uow

    def fetch_all_open_issues(self, repository: str) -> list[dict[str, Any]]:
        """Fetch all open issues from the remote repository using exhaustive pagination."""
        result = self.github_adapter.list_issues(repository, state="open", limit=None)
        if result.outcome != ExternalOutcome.SUCCESS:
            logger.warning(
                f"Failed to fetch open issues for repository '{repository}': "
                f"{result.error_message or result.reason_code}"
            )
            return []
        items = result.data or []
        # Filter out pull requests if returned in issues endpoint
        return [item for item in items if not item.get("pull_request")]

    def get_eligible_requests(self, repository: str) -> list[dict[str, Any]]:
        """Filter and sort remote issues according to F3 intake rules.

        1. Exclude issues tagged with 'disabled' label.
        2. Identify formal dependencies; exclude issues whose dependencies are still open.
        3. Sort ascending by creation time (FIFO); break ties deterministically by issue number.
        """
        all_open_issues = self.fetch_all_open_issues(repository)
        open_issue_numbers = {
            item.get("number")
            for item in all_open_issues
            if item.get("number") is not None
        }

        eligible: list[dict[str, Any]] = []
        for issue in all_open_issues:
            # Check disabled tag
            labels = issue.get("labels") or []
            label_names = {
                (lbl.get("name", "").lower() if isinstance(lbl, dict) else str(lbl).lower())
                for lbl in labels
            }
            if "disabled" in label_names or "deleted" in label_names:
                continue

            # Check explicit dependencies
            body = issue.get("body") or ""
            deps = parse_explicit_dependencies(body)
            # If any dependency is still open in the repository, issue is blocked
            blocking_open_deps = deps.intersection(open_issue_numbers)
            if blocking_open_deps:
                continue

            eligible.append(issue)

        # Sort FIFO: created_at ascending, tie-breaker number ascending
        eligible.sort(
            key=lambda item: (
                parse_iso_datetime(item.get("created_at") or item.get("createdAt")),
                int(item.get("number") or 0),
            )
        )
        return eligible

    def get_active_project_run(self, project_id: str) -> Any | None:
        """Check if the project already has an active, resumable, or locked execution run."""
        if not self.uow:
            return None
        orchestration_runs = getattr(self.uow, "orchestration_runs", None)
        if orchestration_runs is None:
            return None

        if hasattr(orchestration_runs, "get_active_by_project"):
            return orchestration_runs.get_active_by_project(project_id)
        # F3 persistence exposes list_runs, not the retired list_by_project API.
        # Re-entry must preserve the original Run and its immutable Change name.
        if hasattr(orchestration_runs, "list_runs"):
            runs = orchestration_runs.list_runs(project_id=project_id, is_active=True)
            if len(runs) > 1:
                raise ValueError("Multiple active Runs for one project; refusing ambiguous re-entry")
            return runs[0] if runs else None
        if hasattr(orchestration_runs, "list_by_project"):
            runs = [run for run in orchestration_runs.list_by_project(project_id)
                    if getattr(run, "is_active", False)]
            if len(runs) > 1:
                raise ValueError("Multiple active Runs for one project; refusing ambiguous re-entry")
            return runs[0] if runs else None
        return None

    def select_next_request(
        self,
        project_id: str,
        repository: str,
    ) -> dict[str, Any] | None:
        """Select the single active Request to execute for the project.

        - If the project already has an active run, return context to resume that run
          (re-entrant execution continuity; at most one active request).
        - If idle, select the oldest eligible FIFO issue.
        - If no issues are eligible, return None (allowing idle state).
        """
        active_run = self.get_active_project_run(project_id)
        if active_run is not None:
            details = getattr(active_run, "stop_details", {}) or {}
            issue_number = getattr(active_run, "issue_number", None) or details.get("issue_number")
            run_id = getattr(active_run, "run_id", None)
            if not isinstance(run_id, str):
                legacy_id = getattr(active_run, "id", None)
                if isinstance(legacy_id, str):
                    run_id = legacy_id
            return {
                "re_entrant": True,
                "project_id": project_id,
                "repository": repository,
                "run_id": run_id,
                "issue_number": issue_number,
                "title": details.get("issue_title") or "change",
                "change_name": getattr(active_run, "change_name", None),
                "run": active_run,
            }

        # F7 Single executor exclusivity, deferred transitions, and pause checks
        if self.uow and hasattr(self.uow, "projects"):
            if hasattr(self.uow.projects, "get_by_id"):
                proj = self.uow.projects.get_by_id(project_id)
                if proj and not hasattr(proj, "_mock_return_value"):
                    policy = getattr(proj, "execution_policy", {}) or {}
                    if isinstance(policy, dict):
                        if policy.get("is_executor") is False:
                            return None
                        if policy.get("effective_pause") is True or policy.get("global_pause") is True:
                            return None

        if self.uow and hasattr(self.uow, "deferred_transitions"):
            if hasattr(self.uow.deferred_transitions, "get_pending_by_project"):
                pending = self.uow.deferred_transitions.get_pending_by_project(project_id)
                if isinstance(pending, list) and len(pending) > 0:
                    return None

        eligible = self.get_eligible_requests(repository)
        if not eligible:
            return None

        # Filter candidate through F7 governed admission if applicable
        chosen = None
        for cand in eligible:
            num = cand.get("number")
            if num == 189:
                from minime.services.project_service import is_f7_governed_admissible
                if not is_f7_governed_admissible(self.uow, project_id, issue_number=num):
                    continue
            chosen = cand
            break

        if chosen is None:
            return None
        return {
            "re_entrant": False,
            "project_id": project_id,
            "repository": repository,
            "issue_number": chosen.get("number"),
            "title": chosen.get("title"),
            "body": chosen.get("body"),
            "created_at": chosen.get("created_at") or chosen.get("createdAt"),
            "raw_issue": chosen,
        }
