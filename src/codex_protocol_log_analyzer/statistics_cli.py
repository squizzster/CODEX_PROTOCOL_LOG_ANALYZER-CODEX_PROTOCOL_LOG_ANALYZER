"""Command-line adapter for deterministic human-facing statistics."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

from .statistics import analyze_rollout_files, render_markdown


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="codex-log-stats",
        description="Produce privacy-safe human statistics from Codex rollout JSONL.",
    )
    parser.add_argument("paths", nargs="+", help="rollout JSONL paths")
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    arguments = parser.parse_args(argv)
    try:
        report = analyze_rollout_files(arguments.paths)
    except KeyboardInterrupt:
        print("analysis interrupted", file=sys.stderr)
        return 130
    except OSError as error:
        parser.error(str(error))
    if arguments.format == "json":
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    else:
        print(render_markdown(report), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
