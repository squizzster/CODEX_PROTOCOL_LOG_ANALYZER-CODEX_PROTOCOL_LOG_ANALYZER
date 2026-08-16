"""Single analysis pipeline shared by library and command-line entry points."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable, Iterator
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from .events import ProtocolEvent, ProtocolLogDecodeError, parse_protocol_line

UnrecognizedEventWriter = Callable[[ProtocolEvent], None]


@dataclass(frozen=True, slots=True)
class Diagnostic:
    """A recoverable problem tied to its source line."""

    line_number: int
    severity: Literal["warning"]
    message: str
    raw_excerpt: str


@dataclass(frozen=True, slots=True)
class AnalysisReport:
    """Deterministic aggregate facts observed in one JSONL stream."""

    source: str
    total_lines: int
    blank_lines: int
    event_count: int
    malformed_line_count: int
    unknown_event_count: int
    unrecognized_event_count: int
    families: dict[str, int]
    event_names: dict[str, int]
    unrecognized_event_names: dict[str, int]
    item_types: dict[str, int]
    statuses: dict[str, int]
    token_usage: dict[str, int]
    thread_ids: tuple[str, ...]
    turn_ids: tuple[str, ...]
    open_item_ids: tuple[str, ...]
    diagnostics: tuple[Diagnostic, ...]

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""
        return asdict(self)


def analyze_file(path: str | Path) -> AnalysisReport:
    """Analyze a UTF-8 JSONL file."""
    log_path = Path(path)
    with log_path.open(encoding="utf-8") as lines:
        return analyze_lines(lines, source=str(log_path))


def analyze_files(
    paths: Iterable[str | Path],
    *,
    on_unrecognized: UnrecognizedEventWriter | None = None,
) -> AnalysisReport:
    """Analyze multiple UTF-8 JSONL files as one streaming corpus."""
    log_paths = tuple(Path(path) for path in paths)
    return analyze_lines(
        _file_lines(log_paths),
        source=f"{len(log_paths)} files",
        on_unrecognized=on_unrecognized,
    )


def analyze_lines(
    lines: Iterable[str],
    *,
    source: str = "<stream>",
    on_unrecognized: UnrecognizedEventWriter | None = None,
) -> AnalysisReport:
    """Analyze JSONL text with malformed records isolated as diagnostics."""
    total_lines = 0
    blank_lines = 0
    diagnostics: list[Diagnostic] = []
    family_counts: Counter[str] = Counter()
    event_counts: Counter[str] = Counter()
    unrecognized_event_counts: Counter[str] = Counter()
    item_counts: Counter[str] = Counter()
    status_counts: Counter[str] = Counter()
    usage_counts: Counter[str] = Counter()
    thread_ids: set[str] = set()
    turn_ids: set[str] = set()
    open_items: set[str] = set()
    event_count = 0

    for line_number, line in enumerate(lines, start=1):
        total_lines = line_number
        if not line.strip():
            blank_lines += 1
            continue
        try:
            event = parse_protocol_line(line, line_number=line_number)
        except ProtocolLogDecodeError as error:
            diagnostics.append(
                Diagnostic(
                    line_number=line_number,
                    severity="warning",
                    message=str(error),
                    raw_excerpt=line.rstrip("\r\n")[:160],
                )
            )
            continue
        event_count += 1
        family_counts[event.family] += 1
        event_counts[event.name] += 1
        if not event.recognized:
            unrecognized_event_counts[event.name] += 1
            if on_unrecognized is not None:
                on_unrecognized(event)
        if event.item_type:
            item_counts[event.item_type] += 1
        if event.status:
            status_counts[event.status] += 1
        usage_counts.update(event.usage)
        if event.thread_id:
            thread_ids.add(event.thread_id)
        if event.turn_id:
            turn_ids.add(event.turn_id)
        _update_open_items(open_items, event)

    return AnalysisReport(
        source=source,
        total_lines=total_lines,
        blank_lines=blank_lines,
        event_count=event_count,
        malformed_line_count=len(diagnostics),
        unknown_event_count=family_counts["unknown"],
        unrecognized_event_count=sum(unrecognized_event_counts.values()),
        families=_sorted_counts(family_counts),
        event_names=_sorted_counts(event_counts),
        unrecognized_event_names=_sorted_counts(unrecognized_event_counts),
        item_types=_sorted_counts(item_counts),
        statuses=_sorted_counts(status_counts),
        token_usage=_sorted_counts(usage_counts),
        thread_ids=tuple(sorted(thread_ids)),
        turn_ids=tuple(sorted(turn_ids)),
        open_item_ids=tuple(sorted(open_items)),
        diagnostics=tuple(diagnostics),
    )


def _file_lines(paths: Iterable[Path]) -> Iterator[str]:
    for path in paths:
        with path.open(encoding="utf-8") as lines:
            yield from lines


def _update_open_items(open_items: set[str], event: ProtocolEvent) -> None:
    if event.item_id is None:
        return
    if event.lifecycle in {"started", "in_progress"}:
        open_items.add(event.item_id)
    elif event.lifecycle in {"completed", "failed", "cancelled"}:
        open_items.discard(event.item_id)


def _sorted_counts(counts: Counter[str]) -> dict[str, int]:
    return dict(sorted(counts.items()))
