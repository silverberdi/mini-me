"""The legacy operational TUI is unavailable until the F5 replacement."""

from minime.services.legacy_unavailable import LegacyOperationUnavailable


def run_tui(*_args, **_kwargs) -> None:
    raise LegacyOperationUnavailable("operation_unavailable: legacy_tui (owner phase F5)")

__all__ = [
    "MiniMeTuiApp",
    "TuiQueryClient",
    "run_tui",
]
