"""OpenSpec task parsing for execution jobs."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class OpenSpecTask:
    task_id: str
    text: str
    section: str | None
    complete: bool


class OpenSpecTaskTracker:
    """Parses tasks.md without adding runtime metadata to OpenSpec."""

    _task_re = re.compile(r"^- \[(?P<mark>[ xX])\]\s+(?P<body>.+)$")
    _task_id_re = re.compile(r"(?P<id>\d+(?:\.\d+)*)")

    def __init__(self, project_root: str | Path):
        self.project_root = Path(project_root)

    def tasks_path(self, openspec_path: str, change_name: str) -> Path:
        return self.project_root / openspec_path / "changes" / change_name / "tasks.md"

    def parse_tasks(self, openspec_path: str, change_name: str) -> list[OpenSpecTask]:
        path = self.tasks_path(openspec_path, change_name)
        if not path.exists():
            return []
        current_section: str | None = None
        tasks: list[OpenSpecTask] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("## "):
                current_section = stripped[3:].strip()
                continue
            match = self._task_re.match(stripped)
            if not match:
                continue
            body = match.group("body").strip()
            id_match = self._task_id_re.search(body)
            task_id = id_match.group("id") if id_match else body
            tasks.append(
                OpenSpecTask(
                    task_id=task_id,
                    text=body,
                    section=current_section,
                    complete=match.group("mark").lower() == "x",
                )
            )
        return tasks

    def incomplete_tasks(self, openspec_path: str, change_name: str) -> list[OpenSpecTask]:
        return [t for t in self.parse_tasks(openspec_path, change_name) if not t.complete]

    def reconcile_verification_tasks(
        self,
        openspec_path: str,
        change_name: str,
        check_evidence_passed: bool = True,
        project_id: str | None = None,
        job_id: str | None = None,
        uow: Any | None = None,
    ) -> tuple[bool, list[str]]:
        """Reconcile verification tasks in tasks.md with mandatory Stage C durable authority and workspace guard policy."""
        if not check_evidence_passed:
            return False, []

        if not uow or not project_id or not job_id:
            raise RuntimeError(
                "Task reconciliation write denied: uow, project_id, and job_id are mandatory for mutation."
            )

        # Path confinement check on inputs
        if Path(openspec_path).is_absolute() or ".." in Path(openspec_path).parts:
            raise RuntimeError(f"OpenSpec path '{openspec_path}' fails path confinement check.")
        if (
            Path(change_name).is_absolute()
            or ".." in Path(change_name).parts
            or Path(change_name).name != change_name
        ):
            raise RuntimeError(f"Change name '{change_name}' fails path confinement check.")

        target_file = (
            self.project_root / openspec_path / "changes" / change_name / "tasks.md"
        ).resolve()

        # Durable worktree ownership verification
        wt_ownership_repo = getattr(uow, "orchestration_worktree_ownerships", None)
        ownership = wt_ownership_repo.get_by_job_id(job_id) if wt_ownership_repo else None
        if not ownership:
            raise RuntimeError(
                f"Task reconciliation denied: missing OrchestrationWorktreeOwnership for job '{job_id}'."
            )

        from minime.domain.enums import WorktreeCreationState

        if ownership.creation_state != WorktreeCreationState.CREATED:
            raise RuntimeError(
                f"Task reconciliation denied: worktree creation_state is '{ownership.creation_state.value}', expected CREATED."
            )

        canonical_worktree = Path(ownership.canonical_worktree_path).resolve()

        # Verify target_file is strictly contained inside canonical_worktree
        try:
            target_file.relative_to(canonical_worktree)
        except ValueError:
            raise RuntimeError(
                f"Task reconciliation denied: target file '{target_file}' escapes authorized worktree '{canonical_worktree}'."
            )

        # ManagedWorkspaceGuard authorization
        from minime.domain.enums import WorkspaceOperation, WorkspaceRole
        from minime.domain.models import WorkspaceMutationRequest
        from minime.services.workspace_guard import ManagedWorkspaceGuard

        guard = ManagedWorkspaceGuard(uow)
        req = WorkspaceMutationRequest(
            project_id=project_id,
            target_path=str(target_file),
            requested_operation=WorkspaceOperation.EDIT,
            job_id=job_id,
        )
        decision = guard.evaluate_mutation(req)
        if not decision.allowed or decision.workspace_role == WorkspaceRole.RUNTIME:
            raise RuntimeError(
                f"ManagedWorkspaceGuard denied task reconciliation write to '{target_file}': {decision.provider_detail or decision.reason_code.value}"
            )

        if not target_file.exists():
            return False, []

        lines = target_file.read_text(encoding="utf-8").splitlines()
        reconciled_ids: list[str] = []
        new_lines: list[str] = []

        for line in lines:
            stripped = line.strip()
            match = self._task_re.match(stripped)
            if match and match.group("mark").lower() != "x":
                body = match.group("body").strip()
                id_match = self._task_id_re.search(body)
                task_id = id_match.group("id") if id_match else body
                task = OpenSpecTask(
                    task_id=task_id,
                    text=body,
                    section=None,
                    complete=False,
                )
                if is_verification_task(task):
                    indent = line[: len(line) - len(stripped)]
                    new_lines.append(f"{indent}- [x] {body}")
                    reconciled_ids.append(task_id)
                    continue
            new_lines.append(line)

        if reconciled_ids:
            target_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
            return True, reconciled_ids
        return False, []

    def format_prompt_context(self, openspec_path: str, change_name: str) -> str:
        tasks = self.parse_tasks(openspec_path, change_name)
        lines = [f"OpenSpec change: {change_name}", "Tasks:"]
        for task in tasks:
            status = "complete" if task.complete else "pending"
            section = f" [{task.section}]" if task.section else ""
            lines.append(f"- {task.task_id}{section}: {status}: {task.text}")
        return "\n".join(lines)


_VERIFICATION_PATTERNS = (
    re.compile(
        r"\b(?:run|execute)\b.*\b(?:test|tests|pytest|suite|ruff|check|checks|lint|linter)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:confirm|verify)\b.*\b(?:clean\s+pass|passing|tests?\s+pass|checks?\s+pass)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:ruff|pytest|mypy)\b", re.IGNORECASE),
)


def is_verification_task(task: OpenSpecTask) -> bool:
    """Determine if an OpenSpec task represents deterministic verification/checks."""
    text = task.text.lower()
    return any(pattern.search(text) for pattern in _VERIFICATION_PATTERNS)
