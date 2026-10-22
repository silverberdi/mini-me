"""Retired Textual execution console boundary.

The previous TUI was an operational client for the local queue, scheduler and
orchestration engine. Those systems are not available during F1. Keeping a
small importable boundary lets callers receive a truthful error without
loading deleted clients, views, or action controls.
"""

from __future__ import annotations

from minime.services.legacy_unavailable import LegacyOperationUnavailable


class MiniMeTuiApp:
    """Compatibility shell that refuses to start the retired operational TUI."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        del args, kwargs
        raise LegacyOperationUnavailable(
            "operation_unavailable: legacy_tui (owner phase F5)"
        )


def run_tui(*args: object, **kwargs: object) -> None:
    """Fail closed until the F5 UI replaces the legacy execution console."""
    del args, kwargs
    raise LegacyOperationUnavailable("operation_unavailable: legacy_tui (owner phase F5)")
