"""Public library contract for Codex protocol log analysis."""

from .analysis import AnalysisReport, Diagnostic, analyze_file, analyze_files, analyze_lines
from .events import ProtocolEvent, ProtocolLogDecodeError, parse_protocol_line

__all__ = [
    "AnalysisReport",
    "Diagnostic",
    "ProtocolEvent",
    "ProtocolLogDecodeError",
    "analyze_file",
    "analyze_files",
    "analyze_lines",
    "parse_protocol_line",
]
