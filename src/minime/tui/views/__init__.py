"""TUI views package for mini me."""

from minime.tui.views.changes import ChangesView
from minime.tui.views.detail import RunDetailView
from minime.tui.views.overview import OverviewView
from minime.tui.views.preview import PreviewView

__all__ = [
    "OverviewView",
    "ChangesView",
    "RunDetailView",
    "PreviewView",
]
