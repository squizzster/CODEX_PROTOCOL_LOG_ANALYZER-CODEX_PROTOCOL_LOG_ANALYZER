"""Thin JSON CLI adapter over :class:`CodexProtocolLibrary`."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

from .library import CodexProtocolLibrary, OperationResult


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="codex-protocol",
        description="Persist Codex protocol events and query deterministic statistics.",
    )
    parser.add_argument(
        "--database", default="codex-protocol.sqlite3", help="SQLite state path"
    )
    commands = parser.add_subparsers(dest="command", required=True)

    create = commands.add_parser("create", help="create an analysis ID")
    create.add_argument("user_id")

    load = commands.add_parser("load", help="ingest one JSONL file")
    load.add_argument("protocol_id")
    load.add_argument("path")

    add = commands.add_parser("add-event", help="append one chronological JSON event")
    add.add_argument("protocol_id")
    add.add_argument("event_json", help="JSON object, or - to read one object from stdin")
    add.add_argument("--stream-name", default="live")

    stats = commands.add_parser("stats", help="get all or selected current statistics")
    stats.add_argument("protocol_id")
    stats.add_argument("--include", nargs="*")

    listing = commands.add_parser("list", help="list analysis IDs")
    listing.add_argument("--user-id")

    sources = commands.add_parser("sources", help="list ingested sources")
    sources.add_argument("protocol_id")

    arguments = parser.parse_args(argv)
    try:
        with CodexProtocolLibrary(arguments.database) as library:
            result = _dispatch(library, arguments)
    except KeyboardInterrupt:
        print(json.dumps({"status": "fatal", "code": "interrupted"}))
        return 130
    print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
    return {"ok": 0, "warning": 0, "error": 1, "fatal": 2}[result.status]


def _dispatch(
    library: CodexProtocolLibrary, arguments: argparse.Namespace
) -> OperationResult[object]:
    if arguments.command == "create":
        return library.create_new_codex_protocol_id(arguments.user_id)
    if arguments.command == "load":
        return library.load_file(arguments.protocol_id, arguments.path)
    if arguments.command == "add-event":
        event_json = (
            sys.stdin.read() if arguments.event_json == "-" else arguments.event_json
        )
        return library.add_event(
            arguments.protocol_id, event_json, stream_name=arguments.stream_name
        )
    if arguments.command == "stats":
        return library.get_stats(arguments.protocol_id, include=arguments.include)
    if arguments.command == "list":
        return library.list_protocols(user_id=arguments.user_id)
    return library.list_sources(arguments.protocol_id)


if __name__ == "__main__":
    raise SystemExit(main())
