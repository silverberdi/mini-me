"""Explicit, side-effect-free boundary for capabilities deferred beyond F1."""

from __future__ import annotations


class LegacyOperationUnavailable(RuntimeError):
    """Raised when a retired legacy operation is requested."""


class UnavailableLegacyService:
    """Compatibility sentinel for unreachable F1 legacy route bodies.

    It is deliberately not a workflow, repository, scheduler, or adapter: any
    direct use fails before an operation can observe or mutate durable state.
    """

    def __init__(self, *_args, **_kwargs) -> None:
        raise LegacyOperationUnavailable("operation_unavailable: retired legacy service")


def unavailable_payload(operation: str, owner_phase: str) -> dict[str, str]:
    """Return the stable machine-readable denial used by API and CLI surfaces."""
    return {
        "code": "operation_unavailable",
        "operation": operation,
        "owner_phase": owner_phase,
        "detail": "This legacy operation was retired in F1 and has no active replacement yet.",
    }
