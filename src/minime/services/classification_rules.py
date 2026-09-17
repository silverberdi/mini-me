"""Centralized, versioned classification rule configuration.

All path/keyword surface rules live in this single canonical module,
not scattered throughout the classifier. Rule precedence is:

  Tier 1: Observed structural evidence (diff file paths)
  Tier 2: Canonical path/surface rules (this module)
  Tier 3: Weak planning/textual hints

Destructive risk requires actual SQL DDL evidence, not filename or
natural-language mention of delete/drop/truncate.
"""

from __future__ import annotations

from minime.domain.enums import TaskRiskDimension, TaskSurfaceKind

CLASSIFIER_VERSION = "1.0.0"

PATH_RISK_SURFACES: dict[str, list[str]] = {
    "src/minime/db/": [
        TaskRiskDimension.PERSISTENCE_IMPACT.value,
    ],
    "alembic/": [
        TaskRiskDimension.PERSISTENCE_IMPACT.value,
    ],
    "src/minime/services/provider_policy_service.py": [
        TaskRiskDimension.PROVIDER_ORCHESTRATION.value,
    ],
    "src/minime/services/provider_health_service.py": [
        TaskRiskDimension.PROVIDER_ORCHESTRATION.value,
    ],
    "src/minime/services/scheduler_service.py": [
        TaskRiskDimension.PROVIDER_ORCHESTRATION.value,
    ],
    "src/minime/services/orchestration_service.py": [
        TaskRiskDimension.PROVIDER_ORCHESTRATION.value,
    ],
    "src/minime/services/execution_pipeline.py": [
        TaskRiskDimension.PROVIDER_ORCHESTRATION.value,
    ],
    "src/minime/services/continuation_engine.py": [
        TaskRiskDimension.PROVIDER_ORCHESTRATION.value,
    ],
    "src/minime/services/capacity_lifecycle_service.py": [
        TaskRiskDimension.PROVIDER_ORCHESTRATION.value,
    ],
    "src/minime/services/model_independence_policy.py": [
        TaskRiskDimension.PROVIDER_ORCHESTRATION.value,
    ],
    "src/minime/services/task_classifier.py": [
        TaskRiskDimension.PROVIDER_ORCHESTRATION.value,
    ],
    "src/minime/services/budget_service.py": [
        TaskRiskDimension.PROVIDER_ORCHESTRATION.value,
    ],
    "src/minime/adapters/": [
        TaskRiskDimension.PROVIDER_ORCHESTRATION.value,
    ],
    "config/": [
        TaskRiskDimension.DEPLOYMENT_CONFIG.value,
    ],
    "docker-compose": [
        TaskRiskDimension.DEPLOYMENT_CONFIG.value,
    ],
    "Dockerfile": [
        TaskRiskDimension.DEPLOYMENT_CONFIG.value,
    ],
    ".github/": [
        TaskRiskDimension.DEPLOYMENT_CONFIG.value,
    ],
    "docker/": [
        TaskRiskDimension.DEPLOYMENT_CONFIG.value,
    ],
    "scripts/": [
        TaskRiskDimension.DEPLOYMENT_CONFIG.value,
    ],
    "src/minime/cli/": [
        TaskRiskDimension.PRODUCTION_RUNTIME.value,
    ],
    "src/minime/api/": [
        TaskRiskDimension.PRODUCTION_RUNTIME.value,
    ],
    "src/minime/config.py": [
        TaskRiskDimension.PRODUCTION_RUNTIME.value,
    ],
    "src/minime/daemon.py": [
        TaskRiskDimension.PRODUCTION_RUNTIME.value,
    ],
}

PATH_SURFACE_MAPPINGS: dict[str, str] = {
    "docs/": TaskSurfaceKind.DOCS_ONLY.value,
    "README.md": TaskSurfaceKind.DOCS_ONLY.value,
    "tests/": TaskSurfaceKind.TESTS_ONLY.value,
    "alembic/versions/": TaskSurfaceKind.MIGRATION_SCHEMA.value,
    "config/": TaskSurfaceKind.CONFIG_ONLY.value,
    "docker/": TaskSurfaceKind.INFRASTRUCTURE_DEPLOYMENT.value,
    ".github/": TaskSurfaceKind.INFRASTRUCTURE_DEPLOYMENT.value,
    "scripts/": TaskSurfaceKind.INFRASTRUCTURE_DEPLOYMENT.value,
    "src/minime/services/": TaskSurfaceKind.BACKEND_SERVICE.value,
    "src/minime/domain/": TaskSurfaceKind.BACKEND_SERVICE.value,
    "src/minime/db/": TaskSurfaceKind.BACKEND_SERVICE.value,
    "src/minime/adapters/": TaskSurfaceKind.PROVIDER_INTEGRATION.value,
    "src/minime/local_worker/": TaskSurfaceKind.BACKEND_SERVICE.value,
    "src/minime/cli/": TaskSurfaceKind.BACKEND_SERVICE.value,
    "src/minime/api/": TaskSurfaceKind.BACKEND_SERVICE.value,
    "src/minime/tui/": TaskSurfaceKind.UI_FRONTEND.value,
    "tui/": TaskSurfaceKind.UI_FRONTEND.value,
    "schemas/": TaskSurfaceKind.CONFIG_ONLY.value,
}

SECURITY_PATH_MARKERS: tuple[str, ...] = (
    "auth",
    "security",
    "secrets",
    "credentials",
    "tokens",
    "password",
    "session",
    "oauth",
    "jwt",
    "api_key",
    "authorization",
    "authentication",
)

PROVIDER_ORCHESTRATION_PATH_MARKERS: tuple[str, ...] = (
    "provider",
    "scheduler",
    "orchestration",
    "execution_pipeline",
    "continuation_engine",
    "capacity",
    "probe",
    "drain",
    "fallback",
    "retry",
    "routing",
)

DEPLOYMENT_PATH_MARKERS: tuple[str, ...] = (
    "docker",
    "deploy",
    "ci",
    "cd",
    "github/workflows",
    "github/actions",
    "container",
    "infrastructure",
)

CONFIG_FILE_PATTERNS: tuple[str, ...] = (
    "pyproject.toml",
    ".env",
    "alembic.ini",
    "config.yaml",
    "config.yml",
)

DESTRUCTIVE_MIGRATION_PATTERNS: tuple[str, ...] = (
    "DROP TABLE",
    "DROP COLUMN",
    "DROP INDEX",
    "DROP CONSTRAINT",
    "DROP SCHEMA",
    "TRUNCATE",
    "sa.Column(",
)

WEAK_SURFACE_HINTS: dict[str, str] = {
    "docs": TaskSurfaceKind.DOCS_ONLY.value,
    "test": TaskSurfaceKind.TESTS_ONLY.value,
    "fix": TaskSurfaceKind.BACKEND_SERVICE.value,
    "feature": TaskSurfaceKind.BACKEND_SERVICE.value,
    "refactor": TaskSurfaceKind.BACKEND_SERVICE.value,
    "migration": TaskSurfaceKind.MIGRATION_SCHEMA.value,
    "schema": TaskSurfaceKind.MIGRATION_SCHEMA.value,
    "security": TaskSurfaceKind.SECURITY_AUTH.value,
    "auth": TaskSurfaceKind.SECURITY_AUTH.value,
    "ui": TaskSurfaceKind.UI_FRONTEND.value,
    "frontend": TaskSurfaceKind.UI_FRONTEND.value,
    "deploy": TaskSurfaceKind.INFRASTRUCTURE_DEPLOYMENT.value,
    "config": TaskSurfaceKind.CONFIG_ONLY.value,
    "provider": TaskSurfaceKind.PROVIDER_INTEGRATION.value,
    "orchestration": TaskSurfaceKind.ORCHESTRATION_LIFECYCLE.value,
    "scheduler": TaskSurfaceKind.ORCHESTRATION_LIFECYCLE.value,
}


def is_destructive_operation(content: str) -> bool:
    """Check if migration content contains actual destructive DDL operations.

    Only actual SQL DDL patterns qualify. Path names containing
    'delete', natural language, or comments do NOT trigger this.
    """
    for pattern in DESTRUCTIVE_MIGRATION_PATTERNS:
        if pattern.upper() in content.upper():
            return True
    return False


def match_path_to_surface(path: str) -> str | None:
    """Match a file path to a canonical surface kind using centralized rules.

    Returns the surface kind string or None if no match found.
    """
    for prefix, surface in PATH_SURFACE_MAPPINGS.items():
        if path.startswith(prefix) or prefix in path:
            return surface
    return None


def match_path_to_risk_dimensions(path: str) -> list[str]:
    """Match a file path to risk dimensions using centralized rules.

    Returns list of risk dimension strings that apply.
    """
    dimensions: list[str] = []
    for prefix, dims in PATH_RISK_SURFACES.items():
        if path.startswith(prefix) or prefix in path:
            dimensions.extend(dims)
    return list(set(dimensions))


def match_path_to_security(path: str) -> bool:
    """Check if a path contains canonical security/auth markers."""
    path_lower = path.lower()
    for marker in SECURITY_PATH_MARKERS:
        if marker in path_lower:
            return True
    return False


def match_path_to_provider_orchestration(path: str) -> bool:
    """Check if a path matches provider/orchestration markers."""
    path_lower = path.lower()
    for marker in PROVIDER_ORCHESTRATION_PATH_MARKERS:
        if marker in path_lower:
            return True
    return False


def match_path_to_deployment(path: str) -> bool:
    """Check if a path matches deployment markers."""
    path_lower = path.lower()
    for marker in DEPLOYMENT_PATH_MARKERS:
        if marker in path_lower:
            return True
    return False


def match_path_to_config(path: str) -> bool:
    """Check if a path is a known config file."""
    for pattern in CONFIG_FILE_PATTERNS:
        if path.endswith(pattern) or pattern in path:
            return True
    return False


def weak_surface_from_name(name: str) -> str | None:
    """Extract weak surface hint from change name or proposal text.

    These are Tier 3 hints only, never override structural evidence.
    """
    name_lower = name.lower()
    for hint, surface in WEAK_SURFACE_HINTS.items():
        if hint in name_lower:
            return surface
    return None
