"""Single analysis pipeline shared by library and command-line entry points."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from .events import ProtocolEvent, ProtocolLogDecodeError, parse_protocol_line


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
    families: dict[str, int]
    event_names: dict[str, int]
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


def analyze_lines(lines: Iterable[str], *, source: str = "<stream>") -> AnalysisReport:
    """Analyze JSONL text with malformed records isolated as diagnostics."""
    total_lines = 0
    blank_lines = 0
    events: list[ProtocolEvent] = []
    diagnostics: list[Diagnostic] = []

    for line_number, line in enumerate(lines, start=1):
        total_lines = line_number
        if not line.strip():
            blank_lines += 1
            continue
        try:
            events.append(parse_protocol_line(line, line_number=line_number))
        except ProtocolLogDecodeError as error:
            diagnostics.append(
                Diagnostic(
                    line_number=line_number,
                    severity="warning",
                    message=str(error),
                    raw_excerpt=line.rstrip("\r\n")[:160],
                )
            )

    family_counts = Counter(event.family for event in events)
    event_counts = Counter(event.name for event in events)
    item_counts = Counter(event.item_type for event in events if event.item_type)
    status_counts = Counter(event.status for event in events if event.status)
    usage_counts: Counter[str] = Counter()
    for event in events:
        usage_counts.update(event.usage)

    return AnalysisReport(
        source=source,
        total_lines=total_lines,
        blank_lines=blank_lines,
        event_count=len(events),
        malformed_line_count=len(diagnostics),
        unknown_event_count=family_counts["unknown"],
        families=_sorted_counts(family_counts),
        event_names=_sorted_counts(event_counts),
        item_types=_sorted_counts(item_counts),
        statuses=_sorted_counts(status_counts),
        token_usage=_sorted_counts(usage_counts),
        thread_ids=tuple(sorted({event.thread_id for event in events if event.thread_id})),
        turn_ids=tuple(sorted({event.turn_id for event in events if event.turn_id})),
        open_item_ids=_open_item_ids(events),
        diagnostics=tuple(diagnostics),
    )


def _open_item_ids(events: Iterable[ProtocolEvent]) -> tuple[str, ...]:
    open_items: set[str] = set()
    for event in events:
        if event.item_id is None:
            continue
        if event.lifecycle in {"started", "in_progress"}:
            open_items.add(event.item_id)
        elif event.lifecycle in {"completed", "failed", "cancelled"}:
            open_items.discard(event.item_id)
    return tuple(sorted(open_items))


def _sorted_counts(counts: Counter[str]) -> dict[str, int]:
    return dict(sorted(counts.items()))
