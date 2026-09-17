"""Deterministic Task Complexity and Risk Classifier.

Classifies work complexity, multi-dimensional risk, and structural surface
from observable evidence. Produces TaskClassificationSnapshot records.

Rules:
  - Deterministic: same inputs + same version = same result
  - No LLM, no randomness, no provider state
  - Fail-closed: UNKNOWN when evidence is incomplete
  - Evidence precedence: structural > canonical rules > textual hints
  - Complexity and risk remain independent dimensions
"""

from __future__ import annotations

import logging
from typing import Any

from minime.domain.enums import (
    ClassificationCompleteness,
    ClassificationStage,
    TaskComplexity,
    TaskSurfaceKind,
)
from minime.domain.models import (
    Change,
    TaskClassificationSnapshot,
    TaskRiskProfile,
)
from minime.services.classification_rules import (
    CLASSIFIER_VERSION,
    match_path_to_config,
    match_path_to_deployment,
    match_path_to_provider_orchestration,
    match_path_to_security,
    match_path_to_surface,
    weak_surface_from_name,
)

logger = logging.getLogger(__name__)


class TaskComplexityRiskClassifier:
    """Deterministic, provider-agnostic work classifier.

    Complexity and risk remain distinct. Does NOT select provider,
    model, effort, or route.
    """

    def classify_pre_execution(
        self,
        change: Change,
        tasks: list[Any] | None = None,
        proposal_text: str | None = None,
    ) -> TaskClassificationSnapshot:
        """Classify work before any diff exists, from OpenSpec metadata only."""
        signals: dict[str, Any] = {}
        rule_ids: list[str] = []

        signals["change_name"] = change.name

        if proposal_text:
            signals["has_proposal_text"] = True
        else:
            signals["has_proposal_text"] = False

        task_count = len(tasks) if tasks else 0
        signals["task_count"] = task_count

        weak_surface = weak_surface_from_name(change.name)
        if weak_surface:
            signals["weak_surface_hint"] = weak_surface
            rule_ids.append("rule_weak_surface")

        complexity = self._extract_pre_execution_complexity(signals)
        risk_profile = self._extract_pre_execution_risk(signals, proposal_text)
        surface_kind = self._extract_pre_execution_surface(signals, change, tasks)

        completeness = ClassificationCompleteness.PARTIAL
        missing: list[str] = []
        if not proposal_text:
            missing.append("no proposal text")
        if not tasks:
            missing.append("no task definitions")

        if complexity == TaskComplexity.UNKNOWN:
            completeness = ClassificationCompleteness.MINIMAL
            if "no structural evidence" not in missing:
                missing.append("no structural evidence")

        return TaskClassificationSnapshot(
            change_id=change.change_id,
            stage=ClassificationStage.PRE_EXECUTION,
            classifier_version=CLASSIFIER_VERSION,
            complexity=complexity,
            risk_profile=risk_profile,
            surface_kind=surface_kind,
            signals=signals,
            rule_identifiers=rule_ids,
            evidence_source="OPENSPEC_METADATA",
            classification_completeness=completeness,
            missing_signals=missing,
        )

    def classify_post_materialization(
        self,
        pre_execution_snapshot: TaskClassificationSnapshot | None,
        diff_file_paths: list[str],
        migration_files: list[str] | None = None,
        migration_contents: dict[str, str] | None = None,
        design_content: str | None = None,
    ) -> TaskClassificationSnapshot:
        """Classify work after implementation, from actual diff evidence."""

        if not diff_file_paths:
            return self._unknown_snapshot(
                change_id=(
                    pre_execution_snapshot.change_id if pre_execution_snapshot else None
                ),
                job_id=(
                    pre_execution_snapshot.job_id if pre_execution_snapshot else None
                ),
                missing=["no diff file paths available"],
                pre_snapshot_id=pre_execution_snapshot.id if pre_execution_snapshot else None,
            )

        signals = self._extract_signals(
            diff_file_paths, migration_files, migration_contents, design_content
        )
        rule_ids = self._collect_rule_identifiers(signals)

        complexity = self._extract_complexity(signals)
        risk_profile = self._extract_risk_profile(signals)
        surface_kind = self._extract_surface_kind(signals)

        breadth_mismatch = False
        if pre_execution_snapshot:
            breadth_mismatch = self._detect_breadth_mismatch(
                pre_execution_snapshot, signals, complexity, surface_kind
            )

        return TaskClassificationSnapshot(
            change_id=(
                pre_execution_snapshot.change_id if pre_execution_snapshot else None
            ),
            job_id=(
                pre_execution_snapshot.job_id if pre_execution_snapshot else None
            ),
            stage=ClassificationStage.POST_MATERIALIZATION,
            classifier_version=CLASSIFIER_VERSION,
            complexity=complexity,
            risk_profile=risk_profile,
            surface_kind=surface_kind,
            surface_details=signals.get("surface_details", {}),
            signals=signals,
            rule_identifiers=rule_ids,
            evidence_source="GIT_DIFF",
            classification_completeness=ClassificationCompleteness.COMPLETE,
            pre_execution_snapshot_id=pre_execution_snapshot.id if pre_execution_snapshot else None,
            breadth_mismatch_detected=breadth_mismatch,
            composite_surface=surface_kind == TaskSurfaceKind.MIXED,
        )

    def _extract_signals(
        self,
        diff_paths: list[str],
        migration_files: list[str] | None = None,
        migration_contents: dict[str, str] | None = None,
        design_content: str | None = None,
    ) -> dict[str, Any]:
        """Extract all signals from diff paths and migration evidence."""
        signals: dict[str, Any] = {}
        signals["file_count"] = len(diff_paths)

        top_dirs: set[str] = set()
        for path in diff_paths:
            parts = path.split("/")
            if parts:
                if parts[0] in (".", ".."):
                    top_dirs.add(parts[1] if len(parts) > 1 else parts[0])
                else:
                    top_dirs.add(parts[0])
        signals["top_level_dirs"] = sorted(top_dirs)
        signals["top_level_dir_count"] = len(top_dirs)

        has_migration = False
        migration_paths: list[str] = []
        mig_files = migration_files or []
        for path in diff_paths:
            if path.startswith("alembic/versions/") or path.startswith("alembic/script"):
                has_migration = True
                migration_paths.append(path)
        if mig_files:
            has_migration = True
            for mf in mig_files:
                if mf not in migration_paths:
                    migration_paths.append(mf)
        signals["has_migration"] = has_migration
        signals["migration_paths"] = migration_paths

        has_design_md = any(p.endswith("design.md") for p in diff_paths)
        signals["has_design_md"] = has_design_md

        has_cross_module = len(top_dirs) > 3
        signals["cross_module"] = has_cross_module

        has_security = any(match_path_to_security(p) for p in diff_paths)
        signals["has_security_paths"] = has_security

        has_provider = any(match_path_to_provider_orchestration(p) for p in diff_paths)
        signals["has_provider_paths"] = has_provider

        has_deployment = any(match_path_to_deployment(p) for p in diff_paths)
        signals["has_deployment_paths"] = has_deployment

        has_config = any(match_path_to_config(p) for p in diff_paths)
        signals["has_config_paths"] = has_config

        destructive = False
        mig_contents = migration_contents or {}
        for path, content in mig_contents.items():
            if "DROP TABLE" in content.upper() or "DROP COLUMN" in content.upper():
                destructive = True
                break
            if "TRUNCATE" in content.upper():
                destructive = True
                break
            if "sa.Column(" in content and ".drop(" in content:
                destructive = True
                break
        signals["destructive_migration_detected"] = destructive

        surfaces: set[str] = set()
        for path in diff_paths:
            surface = match_path_to_surface(path)
            if surface:
                surfaces.add(surface)
        signals["detected_surfaces"] = sorted(surfaces)
        signals["surface_details"] = {"surfaces": sorted(surfaces)}

        has_design_context = bool(design_content)
        signals["has_design_context"] = has_design_context

        return signals

    def _extract_complexity(self, signals: dict[str, Any]) -> TaskComplexity:
        """Deterministically extract complexity from signals.

        Rules:
          - 3 or fewer files, single dir, no migration -> LOW
          - 4-15 files, <= 3 top-level dirs, no migration -> MEDIUM
          - >15 files OR >3 top-level dirs OR has migration -> HIGH
        """
        file_count = signals.get("file_count", 0)
        top_dir_count = signals.get("top_level_dir_count", 0)
        has_migration = signals.get("has_migration", False)

        if file_count == 0:
            return TaskComplexity.UNKNOWN

        if has_migration:
            return TaskComplexity.HIGH

        if file_count > 15 or top_dir_count > 3:
            return TaskComplexity.HIGH

        if 4 <= file_count <= 15 and top_dir_count <= 3:
            return TaskComplexity.MEDIUM

        if file_count <= 3 and top_dir_count <= 1:
            return TaskComplexity.LOW

        return TaskComplexity.UNKNOWN

    def _extract_pre_execution_complexity(
        self, signals: dict[str, Any]
    ) -> TaskComplexity:
        """Extract complexity from pre-execution signals (metadata only)."""
        task_count = signals.get("task_count", 0)

        if task_count == 0:
            return TaskComplexity.UNKNOWN

        if task_count <= 3:
            return TaskComplexity.LOW
        elif task_count <= 10:
            return TaskComplexity.MEDIUM
        else:
            return TaskComplexity.HIGH

    def _extract_risk_profile(self, signals: dict[str, Any]) -> TaskRiskProfile:
        """Extract multi-dimensional risk profile from signals."""
        file_count = signals.get("file_count", 0)
        top_dir_count = signals.get("top_level_dir_count", 0)
        has_migration = signals.get("has_migration", False)
        has_security = signals.get("has_security_paths", False)
        has_provider = signals.get("has_provider_paths", False)
        has_deployment = signals.get("has_deployment_paths", False)
        destructive = signals.get("destructive_migration_detected", False)
        cross_module = signals.get("cross_module", False)

        def _breadth_level(
            count: int, dirs: int, xmod: bool
        ) -> str:
            if count > 15 or xmod:
                return "HIGH"
            elif count > 3 or dirs > 1:
                return "MEDIUM"
            elif count > 0:
                return "LOW"
            return "NONE"

        profile = TaskRiskProfile()

        profile.code_change_breadth = _breadth_level(file_count, top_dir_count, cross_module)

        if has_migration:
            profile.persistence_impact = "HIGH"
            if destructive:
                profile.persistence_impact = "HIGH"

        if has_security:
            profile.security_auth_impact = "HIGH" if top_dir_count > 1 or file_count > 5 else "MEDIUM"

        if has_provider:
            profile.provider_orchestration = "HIGH" if cross_module else "MEDIUM"

        if has_deployment:
            profile.deployment_config = "MEDIUM" if cross_module else "LOW"

        if destructive:
            profile.destructive_operations = "PRESENT"

        return profile

    def _extract_pre_execution_risk(
        self,
        signals: dict[str, Any],
        proposal_text: str | None = None,
    ) -> TaskRiskProfile:
        """Extract risk profile from pre-execution metadata hints."""
        profile = TaskRiskProfile()

        if proposal_text:
            text_lower = proposal_text.lower()
            if any(kw in text_lower for kw in ("auth", "security", "token", "credential")):
                profile.security_auth_impact = "LOW"
            if any(kw in text_lower for kw in ("migration", "schema", "alembic")):
                profile.persistence_impact = "LOW"
            if any(kw in text_lower for kw in ("provider", "scheduler", "orchestration")):
                profile.provider_orchestration = "LOW"

        return profile

    def _extract_surface_kind(self, signals: dict[str, Any]) -> TaskSurfaceKind:
        """Extract structural surface kind from detected surfaces."""
        surfaces = signals.get("detected_surfaces", [])

        if not surfaces:
            return TaskSurfaceKind.UNKNOWN

        canonical_surfaces = set(surfaces)

        if len(canonical_surfaces) == 0:
            return TaskSurfaceKind.UNKNOWN

        if len(canonical_surfaces) > 1:
            return TaskSurfaceKind.MIXED

        surface_str = list(canonical_surfaces)[0]
        try:
            return TaskSurfaceKind(surface_str)
        except ValueError:
            return TaskSurfaceKind.MIXED

    def _extract_pre_execution_surface(
        self,
        signals: dict[str, Any],
        change: Change,
        tasks: list[Any] | None = None,
    ) -> TaskSurfaceKind:
        """Extract surface kind from pre-execution metadata."""
        weak = signals.get("weak_surface_hint")
        if weak:
            try:
                return TaskSurfaceKind(weak)
            except ValueError:
                pass
        return TaskSurfaceKind.UNKNOWN

    def _collect_rule_identifiers(self, signals: dict[str, Any]) -> list[str]:
        """Collect rule identifiers that contributed to the classification."""
        rules: list[str] = []

        if signals.get("has_migration"):
            rules.append("rule_migration_detected")
        if signals.get("has_security_paths"):
            rules.append("rule_security_auth_path")
        if signals.get("has_provider_paths"):
            rules.append("rule_provider_orchestration_path")
        if signals.get("has_deployment_paths"):
            rules.append("rule_deployment_path")
        if signals.get("has_config_paths"):
            rules.append("rule_config_path")
        if signals.get("destructive_migration_detected"):
            rules.append("rule_destructive_migration")
        if signals.get("cross_module"):
            rules.append("rule_cross_module")

        file_count = signals.get("file_count", 0)
        top_dir_count = signals.get("top_level_dir_count", 0)
        if file_count <= 3 and top_dir_count <= 1:
            rules.append("rule_low_complexity")
        elif 4 <= file_count <= 15:
            rules.append("rule_medium_complexity")
        elif file_count > 15 or top_dir_count > 3:
            rules.append("rule_high_complexity")

        return rules

    def _detect_breadth_mismatch(
        self,
        pre_snapshot: TaskClassificationSnapshot,
        post_signals: dict[str, Any],
        post_complexity: TaskComplexity,
        post_surface: TaskSurfaceKind,
    ) -> bool:
        """Detect if actual diff scope exceeds planned scope."""
        pre_complexity = pre_snapshot.complexity
        pre_surface = pre_snapshot.surface_kind

        complexity_order = {
            TaskComplexity.UNKNOWN: 0,
            TaskComplexity.LOW: 1,
            TaskComplexity.MEDIUM: 2,
            TaskComplexity.HIGH: 3,
        }

        if complexity_order.get(post_complexity, 0) > complexity_order.get(
            pre_complexity, 0
        ):
            return True

        if (
            pre_surface not in (TaskSurfaceKind.UNKNOWN, TaskSurfaceKind.MIXED)
            and post_surface == TaskSurfaceKind.MIXED
        ):
            return True

        return False

    def _unknown_snapshot(
        self,
        change_id: str | None = None,
        job_id: str | None = None,
        missing: list[str] | None = None,
        pre_snapshot_id: str | None = None,
    ) -> TaskClassificationSnapshot:
        """Produce a fail-closed UNKNOWN snapshot."""
        return TaskClassificationSnapshot(
            change_id=change_id,
            job_id=job_id,
            stage=ClassificationStage.POST_MATERIALIZATION,
            classifier_version=CLASSIFIER_VERSION,
            complexity=TaskComplexity.UNKNOWN,
            risk_profile=TaskRiskProfile(),
            surface_kind=TaskSurfaceKind.UNKNOWN,
            evidence_source="GIT_DIFF",
            classification_completeness=ClassificationCompleteness.MINIMAL,
            missing_signals=missing or ["no diff file paths available"],
            pre_execution_snapshot_id=pre_snapshot_id,
        )
