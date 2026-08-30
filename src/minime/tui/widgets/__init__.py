"""TUI widgets package for mini me."""

from minime.tui.widgets.attention_list import AttentionListWidget
from minime.tui.widgets.audit_card import AuditSummaryWidget
from minime.tui.widgets.candidate_lineage import CandidateLineageWidget
from minime.tui.widgets.checks_table import ChecksSummaryWidget
from minime.tui.widgets.completions_list import RecentCompletionsWidget
from minime.tui.widgets.executions_list import ActiveExecutionsWidget
from minime.tui.widgets.header import HeaderWidget
from minime.tui.widgets.health_card import SystemHealthCard
from minime.tui.widgets.help_modal import HelpModal
from minime.tui.widgets.pipeline_stepper import PipelineStepperWidget
from minime.tui.widgets.preview_card import PreviewValidationWidget
from minime.tui.widgets.review_card import ReviewSummaryWidget
from minime.tui.widgets.timeline_view import TimelineWidget

__all__ = [
    "HeaderWidget",
    "SystemHealthCard",
    "AttentionListWidget",
    "ActiveExecutionsWidget",
    "RecentCompletionsWidget",
    "PipelineStepperWidget",
    "CandidateLineageWidget",
    "ChecksSummaryWidget",
    "ReviewSummaryWidget",
    "AuditSummaryWidget",
    "PreviewValidationWidget",
    "TimelineWidget",
    "HelpModal",
]
