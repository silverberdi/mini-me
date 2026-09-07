"""Deterministic local worker task classes and forbidden surfaces.

LOW-risk eligibility for the local worker is decided here deterministically and never by the
model. Task classes follow the canonical allowlist defined by the minimal local worker
bootstrap change; every other class and every known forbidden surface is refused.
"""

from __future__ import annotations

from enum import Enum

# Canonical LOW-risk task classes the local worker may execute.
ALLOWED_LOCAL_TASK_CLASSES = frozenset(
    {
        "SMALL_CODE_FIX",
        "TEST_AUTHORING",
        "LOG_ANALYSIS",
        "SMALL_REFACTOR",
        "API_SMALL_CHANGE",
        "UI_SMALL_POLISH",
    }
)

UNKNOWN_CLASS = "UNKNOWN"
UNCERTAIN_CLASSIFICATION = "UNCERTAIN_CLASSIFICATION"

# Forbidden-surface keyword families. Matching is case-insensitive substring over the
# normalized task description and touch-path surface strings.
FORBIDDEN_SURFACE_FAMILIES: dict[str, tuple[str, ...]] = {
    "lifecycle_state_machine": (
        "lifecycle",
        "state-machine",
        "state machine",
        "state_machine",
        "transition key",
        "workflow status",
    ),
    "provider_policy": (
        "provider-policy",
        "provider policy",
        "provider_policy",
        "policy change",
        "policy_changes",
        "retry budget",
        "capacity policy",
        "fallback policy",
        "quota policy",
    ),
    "security_sensitive": (
        "security",
        "credential",
        "secret",
        "token",
        "authn",
        "authnz",
        "authorization",
        "authenticate",
        "encrypt",
        "tls",
        "pki",
    ),
    "db_schema_migrations": (
        "migration",
        "alembic",
        "ddl",
        "database schema",
        "schema change",
        "db schema",
    ),
    "architecture": (
        "architecture",
        "architectural",
        "interface redesign",
        "structural subsystem",
        "design doc",
    ),
    "deployment_runtime_infrastructure": (
        "deployment",
        "runtime infrastructure",
        "infrastructure",
        "systemd",
        "docker",
        "container",
        "tunnel",
        "server runtime",
        "production",
    ),
    "destructive": (
        "delete",
        "drop ",
        "truncate",
        "reset --hard",
        "force",
        "rm -rf",
        "destructive",
        "purge",
    ),
    "uncertain_classification": (
        "uncertain",
        "ambiguous",
        "unknown impact",
        "classified",
    ),
}

# Canonical forbidden high-risk task classes.
FORBIDDEN_TASK_CLASSES = frozenset(
    {
        "LIFECYCLE_STATE_MACHINE_CHANGE",
        "PROVIDER_POLICY_CHANGE",
        "SECURITY_SENSITIVE_CHANGE",
        "DB_SCHEMA_MIGRATION",
        "ARCHITECTURE_CHANGE",
        "DEPLOYMENT_RUNTIME_CHANGE",
        "DESTRUCTIVE_OPERATION",
        "UNCERTAIN_CLASSIFICATION",
    }
)

# Files / surfaces that are never legal for a local worker touch.
FORBIDDEN_FILE_SURFACE_KEYWORDS = frozenset(
    {
        "alembic",
        "migrations",
        ".env",
        "*.pem",
        "*.key",
        "secrets",
        "credentials",
        "systemd",
        "config/minime.yaml",
        "pyproject.toml",
        "docs/PROVIDER_POLICY.md",
    }
)


class ForbiddenSurfaceKind(str, Enum):
    """Stable identifiers for forbidden surface families."""

    LIFECYCLE_STATE_MACHINE = "lifecycle_state_machine"
    PROVIDER_POLICY = "provider_policy"
    SECURITY_SENSITIVE = "security_sensitive"
    DB_SCHEMA_MIGRATIONS = "db_schema_migrations"
    ARCHITECTURE = "architecture"
    DEPLOYMENT_RUNTIME_INFRASTRUCTURE = "deployment_runtime_infrastructure"
    DESTRUCTIVE = "destructive"
    UNCERTAIN_CLASSIFICATION = "uncertain_classification"


def allowed_local_task_class(task_class: str) -> bool:
    """Return True only if ``task_class`` is a canonical LOW-risk allowlisted class."""
    return task_class.upper() in ALLOWED_LOCAL_TASK_CLASSES


def forbidden_task_class_reason(task_class: str) -> str | None:
    """Return a canonical forbidden label when ``task_class`` is not LOW-risk, else None.

    The label is the specific forbidden class when known, otherwise
    ``UNCERTAIN_CLASSIFICATION``. Allowed LOW-risk classes return None so surface scanning
    may continue.
    """
    if allowed_local_task_class(task_class):
        return None
    upper = task_class.upper()
    if upper in FORBIDDEN_TASK_CLASSES:
        return upper
    return UNCERTAIN_CLASSIFICATION


def offending_forbidden_surface(
    *,
    task_description: str = "",
    touched_surfaces: list[str] | None = None,
    task_class: str = "",
):
    """Return the first offending ``ForbiddenSurfaceKind`` for a task envelope, or None.

    ``touched_surfaces`` are file paths and/or surface names the task would touch. A task is
    forbidden when its class is not a canonical LOW-risk allowlisted class, when its
    description/surfaces match a forbidden family, or when a touched file matches a
    forbidden file-surface keyword.

    Because a non-allowed task class encodes uncertainty, it maps to
    ``UNCERTAIN_CLASSIFICATION`` so the caller can treat it as high-risk.
    """
    class_reason = forbidden_task_class_reason(task_class)
    if class_reason is not None:
        if class_reason in FORBIDDEN_TASK_CLASSES:
            # Map a specific forbidden class onto its surface kind when possible.
            mapping = {
                "LIFECYCLE_STATE_MACHINE_CHANGE": ForbiddenSurfaceKind.LIFECYCLE_STATE_MACHINE,
                "PROVIDER_POLICY_CHANGE": ForbiddenSurfaceKind.PROVIDER_POLICY,
                "SECURITY_SENSITIVE_CHANGE": ForbiddenSurfaceKind.SECURITY_SENSITIVE,
                "DB_SCHEMA_MIGRATION": ForbiddenSurfaceKind.DB_SCHEMA_MIGRATIONS,
                "ARCHITECTURE_CHANGE": ForbiddenSurfaceKind.ARCHITECTURE,
                "DEPLOYMENT_RUNTIME_CHANGE": ForbiddenSurfaceKind.DEPLOYMENT_RUNTIME_INFRASTRUCTURE,
                "DESTRUCTIVE_OPERATION": ForbiddenSurfaceKind.DESTRUCTIVE,
            }
            return mapping.get(class_reason, ForbiddenSurfaceKind.UNCERTAIN_CLASSIFICATION)
        return ForbiddenSurfaceKind.UNCERTAIN_CLASSIFICATION

    haystack = [task_description.lower()]
    if touched_surfaces:
        haystack.extend(s.lower() for s in touched_surfaces)

    for kind, keywords in FORBIDDEN_SURFACE_FAMILIES.items():
        for kw in keywords:
            kwl = kw.lower()
            if any(kwl in text for text in haystack):
                return ForbiddenSurfaceKind(kind)

    if touched_surfaces:
        for surface in touched_surfaces:
            lowered = surface.lower()
            if any(kw in lowered for kw in FORBIDDEN_FILE_SURFACE_KEYWORDS):
                return ForbiddenSurfaceKind.UNCERTAIN_CLASSIFICATION

    return None
