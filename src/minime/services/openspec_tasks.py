"""OpenSpec task parsing for execution jobs."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


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

    def format_prompt_context(self, openspec_path: str, change_name: str) -> str:
        tasks = self.parse_tasks(openspec_path, change_name)
        lines = [f"OpenSpec change: {change_name}", "Tasks:"]
        for task in tasks:
            status = "complete" if task.complete else "pending"
            section = f" [{task.section}]" if task.section else ""
            lines.append(f"- {task.task_id}{section}: {status}: {task.text}")
        return "\n".join(lines)
