"""Command-line adapter for the shared analysis pipeline."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

from .analysis import AnalysisReport, analyze_file, analyze_lines


def main(argv: Sequence[str] | None = None) -> int:
    """Run the analyzer and return a process exit status."""
    parser = argparse.ArgumentParser(
        prog="codex-log-analyze",
        description="Summarize Codex exec or app-server protocol JSONL.",
    )
    parser.add_argument("path", nargs="?", default="-", help="JSONL path (default: stdin)")
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="report representation (default: text)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="exit with status 2 when malformed input lines were observed",
    )
    arguments = parser.parse_args(argv)

    try:
        report = (
            analyze_lines(sys.stdin, source="<stdin>")
            if arguments.path == "-"
            else analyze_file(arguments.path)
        )
    except OSError as error:
        parser.error(str(error))

    if arguments.format == "json":
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    else:
        print(_format_text(report))
    return 2 if arguments.strict and report.malformed_line_count else 0


def _format_text(report: AnalysisReport) -> str:
    lines = [
        f"source: {report.source}",
        (
            f"lines: {report.total_lines} "
            f"({report.event_count} events, {report.blank_lines} blank, "
            f"{report.malformed_line_count} malformed)"
        ),
        f"families: {_counts(report.families)}",
        f"events: {_counts(report.event_names)}",
        f"item types: {_counts(report.item_types)}",
        f"statuses: {_counts(report.statuses)}",
        f"token usage: {_counts(report.token_usage)}",
        f"threads: {len(report.thread_ids)}; turns: {len(report.turn_ids)}",
        f"items still open at end of capture: {len(report.open_item_ids)}",
    ]
    if report.unknown_event_count:
        lines.append(f"unknown-shape events: {report.unknown_event_count}")
    for diagnostic in report.diagnostics:
        lines.append(f"warning: {diagnostic.message}")
    return "\n".join(lines)


def _counts(values: dict[str, int]) -> str:
    return ", ".join(f"{name}={count}" for name, count in values.items()) or "none"


if __name__ == "__main__":
    raise SystemExit(main())
