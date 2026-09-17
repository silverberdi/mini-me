"""OpenSpec integrity auditor: a read-only, point-in-time audit of repository OpenSpec state."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from minime.adapters.openspec import OpenSpecAdapter
from minime.domain.enums import EventType, OrchestrationStage
from minime.domain.interfaces import PersistenceUnitOfWork
from minime.domain.models import IntegrityAudit, Project


@dataclass(frozen=True)
class ClosedEvaluation:
    """Computed CLOSED evaluation: OpenSpec lifecycle + project delivery evidence."""

    change_name: str
    openspec_lifecycle_complete: bool
    delivery_complete: bool
    satisfied: bool
    missing_requirements: tuple[str, ...]


class OpenSpecIntegrityService:
    """Evaluates repository OpenSpec health and persists a structured audit result."""

    def __init__(
        self,
        uow: PersistenceUnitOfWork,
        project_root: str | Path = ".",
        openspec_adapter: OpenSpecAdapter | None = None,
    ):
        self.uow = uow
        self.project_root = Path(project_root).resolve()
        self.openspec_adapter = openspec_adapter or OpenSpecAdapter()

    def run_audit(self, project_id: str) -> IntegrityAudit:
        """Run all check phases, persist to integrity_findings, and return the result."""
        project = self.uow.projects.get_by_id(project_id)
        if not project:
            audit = IntegrityAudit(
                project_id=project_id,
                overall_status="UNKNOWN",
                evidence_gaps=[f"Project '{project_id}' is not registered."],
            )
            self.uow.integrity_findings.save(audit)
            self.uow.commit()
            return audit

        findings: list[dict[str, Any]] = []
        evidence_gaps: list[str] = []

        for check in (
            self._check_active_change_validity,
            self._check_merged_but_unsynced,
            self._check_closed_but_unarchived,
            self._check_orphan_directories,
            self._check_task_state_contradictions,
            self._check_legacy_classification,
        ):
            check_findings, check_gaps = check(project)
            findings.extend(check_findings)
            evidence_gaps.extend(check_gaps)

        audit = IntegrityAudit(
            project_id=project_id,
            overall_status=self._compute_overall(findings, evidence_gaps),
            findings=findings,
            evidence_gaps=evidence_gaps,
        )
        self.uow.integrity_findings.save(audit)
        self.uow.commit()
        return audit

    @staticmethod
    def _compute_overall(findings: list[dict[str, Any]], gaps: list[str]) -> str:
        if any(f.get("severity") == "CRITICAL" for f in findings):
            return "FAIL"
        if gaps:
            return "UNKNOWN"
        return "PASS"

    def evaluate_closed(self, project_id: str, change_name: str) -> ClosedEvaluation:
        """Compute CLOSED by composing OpenSpec lifecycle and delivery evidence."""
        events = self.uow.events.list_events(
            project_id=project_id, change_id=change_name, limit=1000
        )
        event_types = {e.event_type for e in events}

        verify = EventType.READY_FOR_HUMAN_MERGE in event_types
        sync = EventType.POST_MERGE_SYNC_VERIFIED in event_types
        archive = EventType.POST_MERGE_ARCHIVE_VERIFIED in event_types
        lifecycle_complete = verify and sync and archive

        merge = EventType.MERGE_DETECTED in event_types
        deployed = EventType.PRODUCTION_DEPLOYED in event_types
        production_verified = EventType.PRODUCTION_VERIFIED in event_types
        delivery_complete = merge and deployed and production_verified

        missing: list[str] = []
        for label, present in (
            ("verify", verify),
            ("sync", sync),
            ("archive", archive),
            ("merge", merge),
            ("deploy", deployed),
            ("production_verified", production_verified),
        ):
            if not present:
                missing.append(label)

        return ClosedEvaluation(
            change_name=change_name,
            openspec_lifecycle_complete=lifecycle_complete,
            delivery_complete=delivery_complete,
            satisfied=lifecycle_complete and delivery_complete,
            missing_requirements=tuple(missing),
        )

    def _active_change_names(self, project: Project) -> list[str]:
        changes_dir = self.project_root / project.openspec_path / "changes"
        if not changes_dir.exists():
            return []
        return sorted(
            d.name
            for d in changes_dir.iterdir()
            if d.is_dir() and d.name != "archive" and not d.name.startswith(".")
        )

    def _change_capabilities(self, project: Project, change_name: str) -> list[str]:
        specs_dir = self.project_root / project.openspec_path / "changes" / change_name / "specs"
        if specs_dir.exists():
            return sorted(c.name for c in specs_dir.iterdir() if c.is_dir())

        archive_dir = self.project_root / project.openspec_path / "changes" / "archive"
        if archive_dir.exists():
            for entry in archive_dir.iterdir():
                if entry.is_dir() and (
                    entry.name == change_name or entry.name.endswith(f"-{change_name}")
                ):
                    specs = entry / "specs"
                    if specs.exists():
                        return sorted(c.name for c in specs.iterdir() if c.is_dir())
        return []

    def _check_active_change_validity(
        self, project: Project
    ) -> tuple[list[dict[str, Any]], list[str]]:
        findings: list[dict[str, Any]] = []
        gaps: list[str] = []
        db_names = {c.name for c in self.uow.changes.list_by_project(project.project_id)}
        for name in self._active_change_names(project):
            if name not in db_names:
                continue
            result = self.openspec_adapter.validate_change_strict(name, str(self.project_root))
            if result["status"] == "FAIL":
                findings.append(
                    {
                        "severity": "CRITICAL",
                        "category": "INVALID_ACTIVE_CHANGE",
                        "change_name": name,
                        "description": f"Active change '{name}' fails strict OpenSpec validation.",
                        "evidence": {"stderr": result.get("stderr", ""), "returncode": result.get("returncode")},
                    }
                )
            elif result["status"] == "UNKNOWN":
                gaps.append(f"Strict validation unavailable for active change '{name}'.")
        return findings, gaps

    def _check_merged_but_unsynced(
        self, project: Project
    ) -> tuple[list[dict[str, Any]], list[str]]:
        findings: list[dict[str, Any]] = []
        gaps: list[str] = []
        runs = self.uow.orchestration_runs.list_runs(project_id=project.project_id)
        for run in runs:
            if run.current_stage not in (OrchestrationStage.COMPLETED, OrchestrationStage.PR_PREPARED):
                continue
            binding = self.uow.bindings.get_by_project_and_change(project.project_id, run.change_name)
            if not binding or not binding.github_pr_number:
                continue
            capabilities = self._change_capabilities(project, run.change_name)
            missing = [
                c
                for c in capabilities
                if not (self.project_root / project.openspec_path / "specs" / c / "spec.md").exists()
            ]
            if missing:
                findings.append(
                    {
                        "severity": "CRITICAL",
                        "category": "MERGED_BUT_UNSYNCED",
                        "change_name": run.change_name,
                        "description": f"Change '{run.change_name}' is merged but its delta specs are not synchronized.",
                        "evidence": {"unsynchronized_capabilities": missing},
                    }
                )
        return findings, gaps

    def _check_closed_but_unarchived(
        self, project: Project
    ) -> tuple[list[dict[str, Any]], list[str]]:
        findings: list[dict[str, Any]] = []
        gaps: list[str] = []
        runs = self.uow.orchestration_runs.list_runs(project_id=project.project_id)
        for run in runs:
            if run.current_stage != OrchestrationStage.COMPLETED:
                continue
            change_dir = self.project_root / project.openspec_path / "changes" / run.change_name
            if change_dir.exists():
                findings.append(
                    {
                        "severity": "CRITICAL",
                        "category": "CLOSED_BUT_UNARCHIVED",
                        "change_name": run.change_name,
                        "description": f"Change '{run.change_name}' is completed but still active under openspec/changes/.",
                        "evidence": {"active_path": str(change_dir)},
                    }
                )
        return findings, gaps

    def _check_orphan_directories(
        self, project: Project
    ) -> tuple[list[dict[str, Any]], list[str]]:
        findings: list[dict[str, Any]] = []
        gaps: list[str] = []
        db_names = {c.name for c in self.uow.changes.list_by_project(project.project_id)}
        active_runs = {
            r.change_name
            for r in self.uow.orchestration_runs.list_runs(project_id=project.project_id)
            if r.is_active
        }
        changes_dir = self.project_root / project.openspec_path / "changes"
        if not changes_dir.exists():
            return findings, gaps
        for entry in changes_dir.iterdir():
            if not entry.is_dir() or entry.name == "archive" or entry.name.startswith("."):
                continue
            has_artifact = (
                (entry / "proposal.md").exists()
                or (entry / ".openspec.yaml").exists()
                or ((entry / "specs").exists() and (entry / "specs").is_dir())
            )
            if has_artifact:
                continue
            if entry.name not in db_names and entry.name not in active_runs:
                findings.append(
                    {
                        "severity": "WARNING",
                        "category": "ORPHAN_DIRECTORY",
                        "change_name": entry.name,
                        "description": f"Directory '{entry.name}' has no OpenSpec artifacts, DB record, or active run.",
                        "evidence": {"path": str(entry)},
                    }
                )
        return findings, gaps

    def _check_task_state_contradictions(
        self, project: Project
    ) -> tuple[list[dict[str, Any]], list[str]]:
        findings: list[dict[str, Any]] = []
        gaps: list[str] = []
        stage_events = getattr(self.uow, "orchestration_stage_events", None)
        runs = self.uow.orchestration_runs.list_runs(project_id=project.project_id)
        for run in runs:
            artifacts = self.openspec_adapter.evaluate_artifacts(
                project, run.change_name, str(self.project_root)
            )
            if not artifacts.get("exists"):
                continue
            tasks_count = artifacts.get("tasks_count", 0)
            tasks_remaining = artifacts.get("tasks_remaining", 0)
            if tasks_count > 0 and tasks_remaining == 0:
                reached_implementing = False
                if stage_events is not None:
                    events = stage_events.list_by_run(run.run_id)
                    reached_implementing = any(
                        e.to_stage == OrchestrationStage.IMPLEMENTING for e in events
                    )
                if not reached_implementing:
                    findings.append(
                        {
                            "severity": "WARNING",
                            "category": "TASK_STATE_CONTRADICTION",
                            "change_name": run.change_name,
                            "description": f"Change '{run.change_name}' has all tasks checked but no IMPLEMENTING stage evidence.",
                            "evidence": {"run_id": run.run_id},
                        }
                    )
        return findings, gaps

    def _check_legacy_classification(
        self, project: Project
    ) -> tuple[list[dict[str, Any]], list[str]]:
        findings: list[dict[str, Any]] = []
        gaps: list[str] = []

        changes_dir = self.project_root / project.openspec_path / "changes"
        if changes_dir.exists():
            for entry in changes_dir.iterdir():
                if not entry.is_dir() or entry.name.startswith("."):
                    continue
                if entry.name == "archive":
                    continue
                classification = self._classify_active(entry)
                if classification != "CANONICAL":
                    findings.append(self._classification_finding(entry.name, classification))

        archive_dir = changes_dir / "archive"
        if archive_dir.exists():
            for entry in archive_dir.iterdir():
                if not entry.is_dir():
                    continue
                classification = self._classify_archive(entry)
                if classification != "CANONICAL":
                    findings.append(self._classification_finding(entry.name, classification))

        alt_archive = self.project_root / project.openspec_path / "archive"
        if alt_archive.exists() and any(alt_archive.iterdir()):
            findings.append(
                {
                    "severity": "WARNING",
                    "category": "LEGACY_CLASSIFICATION",
                    "change_name": None,
                    "description": "A non-canonical archive location was detected.",
                    "evidence": {"classification": "ARCHIVE_LAYOUT_AMBIGUITY", "path": str(alt_archive)},
                }
            )
        return findings, gaps

    @staticmethod
    def _classification_finding(name: str, classification: str) -> dict[str, Any]:
        return {
            "severity": "WARNING",
            "category": "LEGACY_CLASSIFICATION",
            "change_name": name,
            "description": f"Directory '{name}' was classified as {classification}.",
            "evidence": {"classification": classification},
        }

    @staticmethod
    def _classify_active(entry: Path) -> str:
        has_proposal = (entry / "proposal.md").exists()
        has_tasks = (entry / "tasks.md").exists()
        has_design = (entry / "design.md").exists()
        has_specs = (entry / "specs").exists() and (entry / "specs").is_dir()
        if has_proposal and has_tasks and has_design and has_specs:
            return "CANONICAL"
        if has_proposal or has_tasks or has_design or has_specs:
            return "LEGACY_INCOMPLETE"
        return "ORPHAN"

    @staticmethod
    def _classify_archive(entry: Path) -> str:
        has_proposal = (entry / "proposal.md").exists()
        has_tasks = (entry / "tasks.md").exists()
        has_design = (entry / "design.md").exists()
        has_specs = (entry / "specs").exists() and (entry / "specs").is_dir()
        if has_proposal and has_tasks and has_design and has_specs:
            return "CANONICAL"
        if has_proposal or has_tasks or has_design or has_specs:
            return "LEGACY_STRUCTURAL"
        return "LEGACY_ARCHIVE_DEBT"

