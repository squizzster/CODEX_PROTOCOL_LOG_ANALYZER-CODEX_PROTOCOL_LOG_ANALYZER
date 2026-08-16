"""Command-line adapter for the shared analysis pipeline."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from contextlib import nullcontext
from pathlib import Path
from typing import TextIO

from .analysis import AnalysisReport, analyze_files, analyze_lines
from .events import ProtocolEvent


def main(argv: Sequence[str] | None = None) -> int:
    """Run the analyzer and return a process exit status."""
    parser = argparse.ArgumentParser(
        prog="codex-log-analyze",
        description="Summarize Codex exec or app-server protocol JSONL.",
    )
    parser.add_argument("paths", nargs="*", help="JSONL paths (default: stdin)")
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
    parser.add_argument(
        "--unrecognized-out",
        type=Path,
        help="write every currently unrecognized event to this JSONL file",
    )
    arguments = parser.parse_args(argv)

    try:
        paths = arguments.paths or ["-"]
        if "-" in paths and len(paths) != 1:
            parser.error("stdin cannot be combined with file paths")
        output_context = (
            arguments.unrecognized_out.open("w", encoding="utf-8")
            if arguments.unrecognized_out
            else nullcontext(None)
        )
        with output_context as unrecognized_output:
            writer = _unrecognized_writer(unrecognized_output)
            if paths == ["-"]:
                report = analyze_lines(sys.stdin, source="<stdin>", on_unrecognized=writer)
            elif len(paths) == 1:
                with Path(paths[0]).open(encoding="utf-8") as lines:
                    report = analyze_lines(lines, source=paths[0], on_unrecognized=writer)
            else:
                report = analyze_files(paths, on_unrecognized=writer)
    except KeyboardInterrupt:
        print("analysis interrupted", file=sys.stderr)
        return 130
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
        f"unrecognized events: {_counts(report.unrecognized_event_names)}",
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


def _unrecognized_writer(output: TextIO | None):
    if output is None:
        return None

    def write(event: ProtocolEvent) -> None:
        record = {
            "source_line": event.line_number,
            "family": event.family,
            "name": event.name,
            "raw": event.raw,
        }
        output.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
        output.write("\n")

    return write


if __name__ == "__main__":
    raise SystemExit(main())
