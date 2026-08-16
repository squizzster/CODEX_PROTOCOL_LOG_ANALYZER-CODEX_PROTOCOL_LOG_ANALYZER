"""Command-line adapter for deterministic human-facing statistics."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from tempfile import TemporaryDirectory

from .library import CodexProtocolLibrary, LibraryDiagnostic
from .statistics import StatisticalReport, render_markdown


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="codex-log-stats",
        description="Produce privacy-safe human statistics from Codex rollout JSONL.",
    )
    parser.add_argument("paths", nargs="+", help="rollout JSONL paths")
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    arguments = parser.parse_args(argv)
    diagnostics: list[LibraryDiagnostic] = []
    try:
        with TemporaryDirectory(prefix="codex-log-stats-") as temporary_directory:
            database = Path(temporary_directory) / "batch.sqlite3"
            with CodexProtocolLibrary(database) as library:
                created = library.create_new_codex_protocol_id("batch-cli")
                diagnostics.extend(created.diagnostics)
                if created.value is None:
                    _print_diagnostics(diagnostics)
                    return 2
                for path in arguments.paths:
                    loaded = library.load_file(created.value, path)
                    diagnostics.extend(loaded.diagnostics)
                    if loaded.is_fatal:
                        _print_diagnostics(diagnostics)
                        return 2
                current = library.get_stats(created.value)
                diagnostics.extend(current.diagnostics)
                if current.value is None:
                    _print_diagnostics(diagnostics)
                    return 2 if current.is_fatal else 1
                snapshot = current.value
                report = StatisticalReport(
                    source=f"{len(arguments.paths)} rollout files",
                    must_have_basic_stats=snapshot.must_have_basic_stats,
                    recommended_insight_stats=snapshot.recommended_insight_stats,
                    audit=snapshot.audit,
                )
    except KeyboardInterrupt:
        print("analysis interrupted", file=sys.stderr)
        return 130

    _print_diagnostics(diagnostics)
    if arguments.format == "json":
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    else:
        print(render_markdown(report), end="")
    return 1 if any(item.severity == "error" for item in diagnostics) else 0


def _print_diagnostics(diagnostics: list[LibraryDiagnostic]) -> None:
    for diagnostic in diagnostics:
        location = diagnostic.source or "library"
        if diagnostic.line_number is not None:
            location = f"{location}:{diagnostic.line_number}"
        print(
            f"{diagnostic.severity}: {diagnostic.code}: {location}: {diagnostic.message}",
            file=sys.stderr,
        )


if __name__ == "__main__":
    raise SystemExit(main())
