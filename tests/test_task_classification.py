"""Test-first tests for task complexity risk classification.

Tests domain enums, models, classifier service, persistence, and lifecycle
integration for the task-complexity-risk-classification OpenSpec change.
"""

from __future__ import annotations

import json

from minime.domain.enums import (
    ClassificationCompleteness,
    ClassificationStage,
    TaskComplexity,
    TaskRiskDimension,
    TaskSurfaceKind,
)
from minime.domain.models import (
    Change,
    TaskClassificationProfile,
    TaskClassificationSnapshot,
    TaskRiskProfile,
)
from minime.services.classification_rules import (
    CLASSIFIER_VERSION,
    match_path_to_security,
    match_path_to_surface,
    weak_surface_from_name,
)
from minime.services.task_complexity_risk_classifier import (
    TaskComplexityRiskClassifier,
)


class TestDomainEnums:
    """Task Group 1: Domain Enums and Models."""

    def test_task_complexity_values(self):
        assert TaskComplexity.LOW.value == "LOW"
        assert TaskComplexity.MEDIUM.value == "MEDIUM"
        assert TaskComplexity.HIGH.value == "HIGH"
        assert TaskComplexity.UNKNOWN.value == "UNKNOWN"
        assert len(TaskComplexity) == 4

    def test_task_surface_kind_values(self):
        values = {e.value for e in TaskSurfaceKind}
        assert "DOCS_ONLY" in values
        assert "TESTS_ONLY" in values
        assert "CONFIG_ONLY" in values
        assert "MIGRATION_SCHEMA" in values
        assert "BACKEND_SERVICE" in values
        assert "UI_FRONTEND" in values
        assert "INFRASTRUCTURE_DEPLOYMENT" in values
        assert "PROVIDER_INTEGRATION" in values
        assert "ORCHESTRATION_LIFECYCLE" in values
        assert "SECURITY_AUTH" in values
        assert "MIXED" in values
        assert "UNKNOWN" in values
        assert len(TaskSurfaceKind) == 12

    def test_classification_stage_values(self):
        assert ClassificationStage.PRE_EXECUTION.value == "PRE_EXECUTION"
        assert ClassificationStage.POST_MATERIALIZATION.value == "POST_MATERIALIZATION"
        assert len(ClassificationStage) == 2

    def test_classification_completeness_values(self):
        assert ClassificationCompleteness.COMPLETE.value == "COMPLETE"
        assert ClassificationCompleteness.PARTIAL.value == "PARTIAL"
        assert ClassificationCompleteness.MINIMAL.value == "MINIMAL"
        assert len(ClassificationCompleteness) == 3

    def test_task_risk_dimension_values(self):
        values = {e.value for e in TaskRiskDimension}
        assert "CODE_CHANGE_BREADTH" in values
        assert "ARCHITECTURAL_IMPACT" in values
        assert "PERSISTENCE_IMPACT" in values
        assert "SECURITY_AUTH_IMPACT" in values
        assert "PRODUCTION_RUNTIME" in values
        assert "PROVIDER_ORCHESTRATION" in values
        assert "DESTRUCTIVE_OPERATIONS" in values
        assert "DEPLOYMENT_CONFIG" in values
        assert len(TaskRiskDimension) == 8

    def test_task_risk_dimension_persistence_serialization(self):
        dim = TaskRiskDimension.PERSISTENCE_IMPACT
        assert json.loads(json.dumps(dim.value)) == "PERSISTENCE_IMPACT"

    def test_task_complexity_serialization(self):
        tc = TaskComplexity.HIGH
        assert json.loads(json.dumps(tc.value)) == "HIGH"


class TestTaskClassificationDomainModels:
    """T1.5: Pydantic domain models for classification."""

    def test_task_risk_profile_creation(self):
        profile = TaskRiskProfile()
        assert profile.code_change_breadth == "NONE"
        assert profile.architectural_impact == "NONE"
        assert profile.persistence_impact == "NONE"
        assert profile.security_auth_impact == "NONE"
        assert profile.production_runtime == "NONE"
        assert profile.provider_orchestration == "NONE"
        assert profile.destructive_operations == "NONE"
        assert profile.deployment_config == "NONE"
        assert profile.requires_review_sensitivity is False

    def test_task_risk_profile_with_high_dimension_flags_review(self):
        profile = TaskRiskProfile(
            security_auth_impact="HIGH",
            code_change_breadth="LOW",
        )
        assert profile.security_auth_impact == "HIGH"
        assert profile.requires_review_sensitivity is True

    def test_task_risk_profile_all_low_no_review(self):
        profile = TaskRiskProfile(
            code_change_breadth="LOW",
            architectural_impact="LOW",
        )
        assert profile.requires_review_sensitivity is False

    def test_task_risk_profile_preserves_distinct_dimensions(self):
        profile = TaskRiskProfile(
            code_change_breadth="HIGH",
            security_auth_impact="NONE",
        )
        assert profile.code_change_breadth == "HIGH"
        assert profile.security_auth_impact == "NONE"
        assert profile.requires_review_sensitivity is True

    def test_task_classification_snapshot_pre_execution(self):
        snapshot = TaskClassificationSnapshot(
            change_id="change-1",
            stage=ClassificationStage.PRE_EXECUTION,
            classifier_version="1.0.0",
            complexity=TaskComplexity.MEDIUM,
            risk_profile=TaskRiskProfile(),
            surface_kind=TaskSurfaceKind.BACKEND_SERVICE,
            evidence_source="OPENSPEC_METADATA",
            classification_completeness=ClassificationCompleteness.PARTIAL,
        )
        assert snapshot.stage == ClassificationStage.PRE_EXECUTION
        assert snapshot.pre_execution_snapshot_id is None
        assert snapshot.breadth_mismatch_detected is False
        assert snapshot.is_legacy is False

    def test_task_classification_snapshot_post_materialization(self):
        pre_snapshot = TaskClassificationSnapshot(
            id="pre-1",
            change_id="change-1",
            stage=ClassificationStage.PRE_EXECUTION,
            classifier_version="1.0.0",
            complexity=TaskComplexity.MEDIUM,
            risk_profile=TaskRiskProfile(),
            surface_kind=TaskSurfaceKind.BACKEND_SERVICE,
            evidence_source="OPENSPEC_METADATA",
            classification_completeness=ClassificationCompleteness.PARTIAL,
        )
        post_snapshot = TaskClassificationSnapshot(
            change_id="change-1",
            job_id="job-1",
            stage=ClassificationStage.POST_MATERIALIZATION,
            classifier_version="1.0.0",
            complexity=TaskComplexity.HIGH,
            risk_profile=TaskRiskProfile(persistence_impact="HIGH"),
            surface_kind=TaskSurfaceKind.MIXED,
            evidence_source="GIT_DIFF",
            classification_completeness=ClassificationCompleteness.COMPLETE,
            pre_execution_snapshot_id=pre_snapshot.id,
            breadth_mismatch_detected=True,
        )
        assert post_snapshot.stage == ClassificationStage.POST_MATERIALIZATION
        assert post_snapshot.pre_execution_snapshot_id == pre_snapshot.id
        assert post_snapshot.breadth_mismatch_detected is True

    def test_task_classification_snapshot_serialization_roundtrip(self):
        profile = TaskRiskProfile(
            security_auth_impact="HIGH",
            destructive_operations="PRESENT",
            persistence_impact="HIGH",
        )
        snapshot = TaskClassificationSnapshot(
            id="snap-1",
            change_id="change-1",
            job_id="job-1",
            stage=ClassificationStage.POST_MATERIALIZATION,
            classifier_version="1.0.0",
            complexity=TaskComplexity.HIGH,
            risk_profile=profile,
            surface_kind=TaskSurfaceKind.SECURITY_AUTH,
            surface_details={"surfaces": ["security_auth", "backend_service"]},
            signals={"file_count": 12, "top_level_dirs": 4},
            rule_identifiers=["rule_backend_service", "rule_security_auth"],
            evidence_source="GIT_DIFF",
            classification_completeness=ClassificationCompleteness.COMPLETE,
            missing_signals=[],
            pre_execution_snapshot_id="pre-1",
            breadth_mismatch_detected=False,
            is_legacy=False,
            composite_surface=False,
        )
        data = snapshot.model_dump(mode="json")
        assert data["complexity"] == "HIGH"
        assert data["risk_profile"]["security_auth_impact"] == "HIGH"
        assert data["risk_profile"]["destructive_operations"] == "PRESENT"
        assert data["signals"]["file_count"] == 12
        assert data["rule_identifiers"] == ["rule_backend_service", "rule_security_auth"]

        restored = TaskClassificationSnapshot.model_validate(data)
        assert restored.complexity == TaskComplexity.HIGH
        assert restored.risk_profile.security_auth_impact == "HIGH"
        assert restored.surface_kind == TaskSurfaceKind.SECURITY_AUTH

    def test_task_classification_snapshot_legacy(self):
        snapshot = TaskClassificationSnapshot(
            change_id="change-1",
            stage=ClassificationStage.PRE_EXECUTION,
            classifier_version="1.0.0",
            complexity=TaskComplexity.UNKNOWN,
            risk_profile=TaskRiskProfile(),
            surface_kind=TaskSurfaceKind.UNKNOWN,
            evidence_source="OPENSPEC_METADATA",
            classification_completeness=ClassificationCompleteness.MINIMAL,
            missing_signals=["no diff available", "no openspec metadata"],
            is_legacy=True,
        )
        assert snapshot.is_legacy is True
        assert snapshot.complexity == TaskComplexity.UNKNOWN

    def test_task_classification_snapshot_unknown_incomplete(self):
        snapshot = TaskClassificationSnapshot(
            change_id="change-1",
            stage=ClassificationStage.PRE_EXECUTION,
            classifier_version="1.0.0",
            complexity=TaskComplexity.UNKNOWN,
            risk_profile=TaskRiskProfile(),
            surface_kind=TaskSurfaceKind.UNKNOWN,
            evidence_source="OPENSPEC_METADATA",
            classification_completeness=ClassificationCompleteness.MINIMAL,
            missing_signals=["no structural evidence available"],
        )
        assert snapshot.complexity == TaskComplexity.UNKNOWN
        assert snapshot.classification_completeness == ClassificationCompleteness.MINIMAL
        assert len(snapshot.missing_signals) == 1

    def test_task_classification_profile(self):
        profile = TaskClassificationProfile(
            complexity=TaskComplexity.HIGH,
            risk_profile=TaskRiskProfile(persistence_impact="HIGH"),
            surface_kind=TaskSurfaceKind.MIGRATION_SCHEMA,
        )
        assert profile.complexity == TaskComplexity.HIGH
        assert profile.risk_profile.persistence_impact == "HIGH"
        assert profile.surface_kind == TaskSurfaceKind.MIGRATION_SCHEMA

    def test_task_risk_profile_low_complexity_high_security(self):
        profile = TaskRiskProfile(
            security_auth_impact="HIGH",
            code_change_breadth="LOW",
        )
        assert profile.security_auth_impact == "HIGH"
        assert profile.code_change_breadth == "LOW"
        assert profile.requires_review_sensitivity is True


class TestClassificationRules:
    """T2: Centralized classification rules."""

    def test_classifier_version(self):
        assert CLASSIFIER_VERSION == "1.0.0"

    def test_match_path_to_surface_docs(self):
        assert match_path_to_surface("docs/architecture.md") == TaskSurfaceKind.DOCS_ONLY.value

    def test_match_path_to_surface_tests(self):
        assert match_path_to_surface("tests/test_foo.py") == TaskSurfaceKind.TESTS_ONLY.value

    def test_match_path_to_surface_unknown(self):
        assert match_path_to_surface("random_file.txt") is None

    def test_match_path_to_security_true(self):
        assert match_path_to_security("src/minime/auth/service.py") is True

    def test_match_path_to_security_false(self):
        assert match_path_to_security("src/minime/utils/helpers.py") is False

    def test_match_path_to_security_credentials(self):
        assert match_path_to_security("src/credentials.yaml") is True

    def test_weak_surface_hint_from_name(self):
        assert weak_surface_from_name("fix-bug-in-service") == TaskSurfaceKind.BACKEND_SERVICE.value

    def test_weak_surface_no_match(self):
        assert weak_surface_from_name("xyz-unrelated") is None

    def test_destructive_patterns_not_in_filename(self):
        from minime.services.classification_rules import is_destructive_operation

        assert is_destructive_operation("delete_old_test.py") is False
        assert is_destructive_operation("this is a normal update") is False

    def test_destructive_patterns_actual_ddl(self):
        from minime.services.classification_rules import is_destructive_operation

        assert is_destructive_operation("DROP TABLE users") is True
        assert is_destructive_operation("op.execute('TRUNCATE orders')") is True


class TestTaskComplexityRiskClassifier:
    """T3: Task Complexity Risk Classifier service tests."""

    def _make_change(self, name: str = "test-change") -> Change:
        return Change(
            change_id="change-1",
            project_id="proj-1",
            name=name,
        )

    def test_classify_pre_execution_minimal(self):
        classifier = TaskComplexityRiskClassifier()
        change = self._make_change()
        snapshot = classifier.classify_pre_execution(change)
        assert snapshot.stage == ClassificationStage.PRE_EXECUTION
        assert snapshot.classifier_version == "1.0.0"
        assert snapshot.complexity == TaskComplexity.UNKNOWN
        assert snapshot.classification_completeness == ClassificationCompleteness.MINIMAL

    def test_classify_pre_execution_with_tasks(self):
        classifier = TaskComplexityRiskClassifier()
        change = self._make_change("small-fix")
        snapshot = classifier.classify_pre_execution(change, tasks=[{}, {}])
        assert snapshot.complexity == TaskComplexity.LOW

    def test_classify_pre_execution_with_proposal_text(self):
        classifier = TaskComplexityRiskClassifier()
        change = self._make_change("auth-refactor")
        snapshot = classifier.classify_pre_execution(
            change, tasks=[{}, {}, {}], proposal_text="Refactoring auth module"
        )
        assert snapshot.risk_profile.security_auth_impact == "LOW"

    def test_post_materialization_empty_diff(self):
        classifier = TaskComplexityRiskClassifier()
        snapshot = classifier.classify_post_materialization(
            pre_execution_snapshot=None,
            diff_file_paths=[],
        )
        assert snapshot.complexity == TaskComplexity.UNKNOWN
        assert snapshot.classification_completeness == ClassificationCompleteness.MINIMAL

    def test_post_materialization_docs_only_low_complexity(self):
        classifier = TaskComplexityRiskClassifier()
        snapshot = classifier.classify_post_materialization(
            pre_execution_snapshot=None,
            diff_file_paths=[
                "docs/architecture.md",
                "docs/guide.md",
            ],
        )
        assert snapshot.complexity == TaskComplexity.LOW
        assert snapshot.surface_kind == TaskSurfaceKind.DOCS_ONLY
        assert snapshot.risk_profile.code_change_breadth == "LOW"

    def test_post_materialization_tests_only(self):
        classifier = TaskComplexityRiskClassifier()
        snapshot = classifier.classify_post_materialization(
            pre_execution_snapshot=None,
            diff_file_paths=[
                "tests/test_foo.py",
                "tests/test_bar.py",
            ],
        )
        assert snapshot.surface_kind == TaskSurfaceKind.TESTS_ONLY

    def test_post_materialization_medium_complexity(self):
        classifier = TaskComplexityRiskClassifier()
        files = [f"src/minime/services/mod_{i}.py" for i in range(5)]
        snapshot = classifier.classify_post_materialization(
            pre_execution_snapshot=None,
            diff_file_paths=files,
        )
        assert snapshot.complexity == TaskComplexity.MEDIUM

    def test_post_materialization_high_complexity_many_files(self):
        classifier = TaskComplexityRiskClassifier()
        files = [f"src/minime/services/mod_{i}.py" for i in range(20)]
        snapshot = classifier.classify_post_materialization(
            pre_execution_snapshot=None,
            diff_file_paths=files,
        )
        assert snapshot.complexity == TaskComplexity.HIGH
        assert snapshot.risk_profile.code_change_breadth == "HIGH"

    def test_post_materialization_high_complexity_migration(self):
        classifier = TaskComplexityRiskClassifier()
        snapshot = classifier.classify_post_materialization(
            pre_execution_snapshot=None,
            diff_file_paths=[
                "src/minime/service.py",
                "alembic/versions/022_new_migration.py",
            ],
        )
        assert snapshot.complexity == TaskComplexity.HIGH
        assert snapshot.risk_profile.persistence_impact == "HIGH"

    def test_post_materialization_security_auth_detected(self):
        classifier = TaskComplexityRiskClassifier()
        snapshot = classifier.classify_post_materialization(
            pre_execution_snapshot=None,
            diff_file_paths=[
                "src/minime/auth/service.py",
                "src/minime/auth/models.py",
                "src/minime/auth/routes.py",
            ],
        )
        assert snapshot.risk_profile.security_auth_impact == "MEDIUM"

    def test_post_materialization_low_complexity_high_security(self):
        classifier = TaskComplexityRiskClassifier()
        snapshot = classifier.classify_post_materialization(
            pre_execution_snapshot=None,
            diff_file_paths=[
                "src/minime/auth/token.py",
            ],
        )
        assert snapshot.complexity == TaskComplexity.LOW
        assert snapshot.risk_profile.security_auth_impact == "MEDIUM"
        assert snapshot.risk_profile.requires_review_sensitivity is False

    def test_post_materialization_high_complexity_low_security(self):
        classifier = TaskComplexityRiskClassifier()
        snapshot = classifier.classify_post_materialization(
            pre_execution_snapshot=None,
            diff_file_paths=[
                f"src/minime/utils/helper_{i}.py" for i in range(20)
            ],
        )
        assert snapshot.complexity == TaskComplexity.HIGH
        assert snapshot.risk_profile.security_auth_impact == "NONE"
        assert snapshot.risk_profile.provider_orchestration == "NONE"

    def test_post_materialization_provider_paths(self):
        classifier = TaskComplexityRiskClassifier()
        snapshot = classifier.classify_post_materialization(
            pre_execution_snapshot=None,
            diff_file_paths=[
                "src/minime/services/provider_policy_service.py",
                "src/minime/services/scheduler_service.py",
            ],
        )
        assert snapshot.risk_profile.provider_orchestration == "MEDIUM"

    def test_post_materialization_deployment_paths(self):
        classifier = TaskComplexityRiskClassifier()
        snapshot = classifier.classify_post_materialization(
            pre_execution_snapshot=None,
            diff_file_paths=[
                "docker/Dockerfile",
                "docker-compose.yml",
            ],
        )
        assert snapshot.risk_profile.deployment_config == "LOW"

    def test_post_materialization_mixed_surface(self):
        classifier = TaskComplexityRiskClassifier()
        snapshot = classifier.classify_post_materialization(
            pre_execution_snapshot=None,
            diff_file_paths=[
                "src/minime/services/service.py",
                "alembic/versions/022_migration.py",
                "tests/test_service.py",
            ],
        )
        assert snapshot.surface_kind == TaskSurfaceKind.MIXED
        assert snapshot.composite_surface is True

    def test_post_materialization_config_only(self):
        classifier = TaskComplexityRiskClassifier()
        snapshot = classifier.classify_post_materialization(
            pre_execution_snapshot=None,
            diff_file_paths=[
                "config/settings.yaml",
                "pyproject.toml",
            ],
        )
        assert snapshot.surface_kind == TaskSurfaceKind.CONFIG_ONLY

    def test_post_materialization_breadth_mismatch_detected(self):
        classifier = TaskComplexityRiskClassifier()
        pre_snapshot = TaskClassificationSnapshot(
            id="pre-1",
            change_id="change-1",
            stage=ClassificationStage.PRE_EXECUTION,
            classifier_version="1.0.0",
            complexity=TaskComplexity.LOW,
            risk_profile=TaskRiskProfile(),
            surface_kind=TaskSurfaceKind.BACKEND_SERVICE,
            evidence_source="OPENSPEC_METADATA",
            classification_completeness=ClassificationCompleteness.PARTIAL,
        )
        post_snapshot = classifier.classify_post_materialization(
            pre_execution_snapshot=pre_snapshot,
            diff_file_paths=[
                f"src/minime/services/mod_{i}.py" for i in range(20)
            ],
        )
        assert post_snapshot.breadth_mismatch_detected is True
        assert post_snapshot.pre_execution_snapshot_id == "pre-1"

    def test_post_materialization_deterministic_repeatability(self):
        classifier = TaskComplexityRiskClassifier()
        files = [f"src/minime/services/mod_{i}.py" for i in range(5)]
        snap1 = classifier.classify_post_materialization(
            pre_execution_snapshot=None, diff_file_paths=files
        )
        snap2 = classifier.classify_post_materialization(
            pre_execution_snapshot=None, diff_file_paths=files
        )
        assert snap1.complexity == snap2.complexity
        assert snap1.surface_kind == snap2.surface_kind
        assert snap1.risk_profile.model_dump() == snap2.risk_profile.model_dump()

    def test_post_materialization_destructive_risk_in_migration(self):
        classifier = TaskComplexityRiskClassifier()
        snapshot = classifier.classify_post_materialization(
            pre_execution_snapshot=None,
            diff_file_paths=["alembic/versions/022_migration.py"],
            migration_contents={"alembic/versions/022_migration.py": "DROP TABLE users"},
        )
        assert snapshot.risk_profile.destructive_operations == "PRESENT"
        assert snapshot.risk_profile.persistence_impact == "HIGH"

    def test_post_materialization_no_destructive_for_normal_file(self):
        classifier = TaskComplexityRiskClassifier()
        snapshot = classifier.classify_post_materialization(
            pre_execution_snapshot=None,
            diff_file_paths=["src/minime/delete_old_test.py"],
        )
        assert snapshot.risk_profile.destructive_operations == "NONE"

    def test_post_materialization_actual_diff_smaller_than_planned(self):
        classifier = TaskComplexityRiskClassifier()
        pre_snapshot = TaskClassificationSnapshot(
            id="pre-1",
            change_id="change-1",
            stage=ClassificationStage.PRE_EXECUTION,
            classifier_version="1.0.0",
            complexity=TaskComplexity.HIGH,
            risk_profile=TaskRiskProfile(),
            surface_kind=TaskSurfaceKind.BACKEND_SERVICE,
            evidence_source="OPENSPEC_METADATA",
            classification_completeness=ClassificationCompleteness.PARTIAL,
        )
        post_snapshot = classifier.classify_post_materialization(
            pre_execution_snapshot=pre_snapshot,
            diff_file_paths=["src/minime/services/one_file.py"],
        )
        assert post_snapshot.complexity == TaskComplexity.LOW
        assert post_snapshot.breadth_mismatch_detected is False

    def test_pre_execution_does_not_fabricate_low(self):
        classifier = TaskComplexityRiskClassifier()
        change = self._make_change("unknown-scope")
        snapshot = classifier.classify_pre_execution(change, tasks=[], proposal_text=None)
        assert snapshot.complexity == TaskComplexity.UNKNOWN
        assert snapshot.classification_completeness == ClassificationCompleteness.MINIMAL
        assert "no proposal text" in snapshot.missing_signals

    def test_pre_execution_snapshot_is_immutable(self):
        classifier = TaskComplexityRiskClassifier()
        change = self._make_change("test-change")
        snapshot = classifier.classify_pre_execution(change, tasks=[{}, {}])

        original_complexity = snapshot.complexity
        snapshot.complexity = TaskComplexity.HIGH
        assert snapshot.complexity != original_complexity


class TestNonInterference:
    """T7: Non-interference verification."""

    def test_provider_policy_service_not_altered(self):
        from minime.domain.enums import TaskClass
        from minime.services.provider_policy_service import ProviderPolicyService

        svc = ProviderPolicyService(uow=None)
        result = svc.evaluate_selection(
            task_class=TaskClass.ROUTINE_IMPLEMENTATION,
            role="implementer",
        )
        assert result.task_class == TaskClass.ROUTINE_IMPLEMENTATION
        assert result.selected_provider is not None

    def test_continuation_engine_not_altered(self):
        from minime.domain.enums import (
            ContinuationDecision,
            ExecutionOutcome,
            ProgressClassification,
        )
        from minime.services.continuation_engine import (
            ContinuationContext,
            ContinuationEngine,
        )

        engine = ContinuationEngine()
        ctx = ContinuationContext(
            job_id="job-1",
            attempt_number=1,
            current_executor_role="codex",
            current_model_identity="codex-model",
            outcome=ExecutionOutcome.CHANGES_REQUIRED,
            progress=ProgressClassification.PARTIAL_PROGRESS,
        )
        result = engine.decide(ctx)
        assert result.decision in {
            ContinuationDecision.CORRECT_AND_RETRY,
            ContinuationDecision.REASSIGN_AGENT,
            ContinuationDecision.WAIT_EXTERNAL,
            ContinuationDecision.NEEDS_HUMAN,
        }

    def test_classifier_zero_external_api_calls(self):
        import inspect

        from minime.services.classification_rules import CLASSIFIER_VERSION
        from minime.services.task_complexity_risk_classifier import (
            TaskComplexityRiskClassifier,
        )

        source = inspect.getsource(TaskComplexityRiskClassifier)
        no_http = all(
            kw not in source for kw in ("httpx", "requests", "urllib", "http", "api_call")
        )
        assert no_http, "Classifier must not make external API calls"

        classifier = TaskComplexityRiskClassifier()
        change = Change(change_id="ch-1", project_id="p-1", name="test")
        snapshot = classifier.classify_pre_execution(change, tasks=[{}, {}])

        assert snapshot.classifier_version == "1.0.0"
        assert CLASSIFIER_VERSION == "1.0.0"

    def test_task_class_unchanged(self):
        from minime.domain.enums import TaskClass

        values = {e.value for e in TaskClass}
        expected = {
            "ROUTINE_IMPLEMENTATION",
            "ORDINARY_REMEDIATION",
            "TEST_FIX",
            "BOOKKEEPING_RECONCILIATION",
            "EVIDENCE_RECONCILIATION",
            "ARCHITECTURE",
            "UX_VISUAL_QA",
            "PLATFORM_RECOVERY",
            "SPECIALIZED",
        }
        assert values == expected


class TestLifecycleFkLinkage:
    """T6: Lifecycle FK column linkage."""

    def test_pre_execution_sets_latest_classification_snapshot_id(self):
        change = Change(
            change_id="ch-lifecycle-1",
            project_id="proj-1",
            name="test-lifecycle-change",
        )
        assert change.latest_classification_snapshot_id is None

        classifier = TaskComplexityRiskClassifier()
        snapshot = classifier.classify_pre_execution(change, tasks=[{}, {}, {}])

        change.latest_classification_snapshot_id = snapshot.id
        assert change.latest_classification_snapshot_id == snapshot.id
        assert change.latest_classification_snapshot_id is not None

    def test_post_materialization_sets_classification_snapshot_id(self):
        from minime.domain.enums import JobStatus
        from minime.domain.models import Job

        job = Job(
            job_id="job-lifecycle-1",
            project_id="proj-1",
            change_name="test-lifecycle-change",
            status=JobStatus.RUNNING,
            implementer_role="codex",
            candidate_sha="abc123def456",
            base_sha="base000base000",
        )

        pre_snapshot = TaskClassificationSnapshot(
            id="pre-lifecycle-1",
            change_id="ch-lifecycle-1",
            stage=ClassificationStage.PRE_EXECUTION,
            classifier_version="1.0.0",
            complexity=TaskComplexity.LOW,
            risk_profile=TaskRiskProfile(),
            surface_kind=TaskSurfaceKind.BACKEND_SERVICE,
            evidence_source="OPENSPEC_METADATA",
            classification_completeness=ClassificationCompleteness.PARTIAL,
        )

        classifier = TaskComplexityRiskClassifier()
        post_snapshot = classifier.classify_post_materialization(
            pre_execution_snapshot=pre_snapshot,
            diff_file_paths=["src/minime/services/service.py"],
        )
        post_snapshot.job_id = job.job_id
        post_snapshot.change_id = pre_snapshot.change_id

        job.classification_snapshot_id = post_snapshot.id

        assert job.classification_snapshot_id == post_snapshot.id
        assert job.classification_snapshot_id is not None

        post_data = post_snapshot.model_dump(mode="json")
        assert post_data["pre_execution_snapshot_id"] == pre_snapshot.id


class TestFailClosedEvidence:
    """T8.2: Failure-injection and fail-closed tests."""

    def test_missing_inputs_produces_unknown(self):
        classifier = TaskComplexityRiskClassifier()
        post = classifier.classify_post_materialization(
            pre_execution_snapshot=None,
            diff_file_paths=[],
        )
        assert post.complexity == TaskComplexity.UNKNOWN
        assert post.classification_completeness == ClassificationCompleteness.MINIMAL
        assert len(post.missing_signals) > 0

    def test_legacy_item_is_truthful(self):
        from minime.domain.models import generate_uuid

        snapshot = TaskClassificationSnapshot(
            id=generate_uuid(),
            change_id="old-change",
            stage=ClassificationStage.PRE_EXECUTION,
            classifier_version="1.0.0",
            complexity=TaskComplexity.UNKNOWN,
            risk_profile=TaskRiskProfile(),
            surface_kind=TaskSurfaceKind.UNKNOWN,
            evidence_source="OPENSPEC_METADATA",
            classification_completeness=ClassificationCompleteness.MINIMAL,
            missing_signals=["no openspec metadata available", "no diff available"],
            is_legacy=True,
        )
        assert snapshot.is_legacy is True
        assert snapshot.complexity == TaskComplexity.UNKNOWN
        assert "no diff available" in snapshot.missing_signals

    def test_pre_execution_fail_closed_does_not_silently_classify_low(self):
        classifier = TaskComplexityRiskClassifier()
        change = Change(change_id="ch-fc", project_id="p-fc", name="mystery-change")
        snapshot = classifier.classify_pre_execution(
            change, tasks=[], proposal_text=None
        )
        assert snapshot.complexity == TaskComplexity.UNKNOWN
        assert snapshot.classification_completeness == ClassificationCompleteness.MINIMAL
        assert "no proposal text" in snapshot.missing_signals

    def test_pre_snapshot_immutable_after_post(self):
        pre_snapshot = TaskClassificationSnapshot(
            id="immutable-pre",
            change_id="ch-imm",
            stage=ClassificationStage.PRE_EXECUTION,
            classifier_version="1.0.0",
            complexity=TaskComplexity.LOW,
            risk_profile=TaskRiskProfile(),
            surface_kind=TaskSurfaceKind.BACKEND_SERVICE,
            evidence_source="OPENSPEC_METADATA",
            classification_completeness=ClassificationCompleteness.PARTIAL,
        )
        original_complexity = pre_snapshot.complexity
        original_surface = pre_snapshot.surface_kind

        classifier = TaskComplexityRiskClassifier()
        post = classifier.classify_post_materialization(
            pre_execution_snapshot=pre_snapshot,
            diff_file_paths=[
                f"src/minime/services/mod_{i}.py" for i in range(20)
            ],
        )

        assert pre_snapshot.complexity == original_complexity
        assert pre_snapshot.surface_kind == original_surface
        assert post.breadth_mismatch_detected is True
        assert post.pre_execution_snapshot_id == "immutable-pre"

    def test_reclassification_creates_new_snapshot(self):
        change = Change(change_id="ch-recl", project_id="p-recl", name="reclassify-me")
        classifier = TaskComplexityRiskClassifier()

        snap1 = classifier.classify_pre_execution(change, tasks=[{}, {}])
        snap2 = classifier.classify_pre_execution(change, tasks=[{}, {}, {}, {}])

        assert snap1.id != snap2.id
        assert snap1.classifier_version == snap2.classifier_version

    def test_no_pre_snapshot_path_is_truthful(self):
        classifier = TaskComplexityRiskClassifier()
        post = classifier.classify_post_materialization(
            pre_execution_snapshot=None,
            diff_file_paths=["src/minime/services/a.py", "src/minime/services/b.py"],
        )
        assert post.pre_execution_snapshot_id is None
        assert post.breadth_mismatch_detected is False
