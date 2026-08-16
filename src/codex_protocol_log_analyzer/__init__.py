"""Public library contract for Codex protocol log analysis."""

from .analysis import AnalysisReport, Diagnostic, analyze_file, analyze_files, analyze_lines
from .events import ProtocolEvent, ProtocolLogDecodeError, parse_protocol_line
from .statistics import StatisticalReport, analyze_rollout_files, render_markdown

__all__ = [
    "AnalysisReport",
    "Diagnostic",
    "ProtocolEvent",
    "ProtocolLogDecodeError",
    "StatisticalReport",
    "analyze_file",
    "analyze_files",
    "analyze_lines",
    "analyze_rollout_files",
    "parse_protocol_line",
    "render_markdown",
]
