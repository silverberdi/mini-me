"""Domain exceptions for mini me lifecycle authority and domain operations."""

from __future__ import annotations


class DomainError(Exception):
    """Base domain exception for mini me."""


class LifecycleError(DomainError):
    """Base exception for lifecycle transition operations."""


class LifecycleBypassError(LifecycleError):
    """Raised when generic repository save() or update() attempts to alter lifecycle status on existing entity."""


class LifecycleTransitionError(LifecycleError):
    """Base exception for lifecycle transition authority failures."""


class LifecycleInvalidTransitionError(LifecycleTransitionError):
    """Raised when a requested status transition is invalid according to the state matrix."""


class LifecycleTransitionConflictError(LifecycleTransitionError):
    """Raised when atomic compare-and-set (CAS) affects 0 rows due to stale state or concurrency conflict."""
