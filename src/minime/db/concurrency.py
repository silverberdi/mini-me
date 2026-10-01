"""Process-independent PostgreSQL advisory locking primitives for Stage F concurrency control."""

from __future__ import annotations

import hashlib

GLOBAL_ADMISSION_NAMESPACE = "minime:admission:global"
PROJECT_ADMISSION_NAMESPACE_PREFIX = "minime:admission:project:"


def derive_advisory_lock_key(namespace_string: str) -> int:
    """Derive a process-independent signed 64-bit integer for pg_advisory_xact_lock(bigint)."""
    digest = hashlib.sha256(namespace_string.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=True)


def derive_global_admission_lock_key() -> int:
    """Derive global admission transaction advisory lock key."""
    return derive_advisory_lock_key(GLOBAL_ADMISSION_NAMESPACE)


def derive_project_admission_lock_key(project_id: str) -> int:
    """Derive project admission transaction advisory lock key for a given project_id."""
    return derive_advisory_lock_key(f"{PROJECT_ADMISSION_NAMESPACE_PREFIX}{project_id}")
