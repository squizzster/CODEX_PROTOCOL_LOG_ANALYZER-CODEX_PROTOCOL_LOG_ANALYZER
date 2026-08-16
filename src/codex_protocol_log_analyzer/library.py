"""Persistent application-facing library for Codex protocol statistics."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Self, TypeVar

from .statistics import analyze_rollout_record_sources

_KNOWN_ROLLOUT_EVENTS = frozenset(
    {
        "compacted",
        "event_msg.agent_message",
        "event_msg.agent_reasoning",
        "event_msg.context_compacted",
        "event_msg.exec_command_end",
        "event_msg.item_completed",
        "event_msg.mcp_tool_call_end",
        "event_msg.patch_apply_end",
        "event_msg.sub_agent_activity",
        "event_msg.task_complete",
        "event_msg.task_started",
        "event_msg.thread_goal_updated",
        "event_msg.thread_settings_applied",
        "event_msg.token_count",
        "event_msg.turn_aborted",
        "event_msg.user_message",
        "event_msg.web_search_end",
        "inter_agent_communication_metadata",
        "response_item.agent_message",
        "response_item.custom_tool_call",
        "response_item.custom_tool_call_output",
        "response_item.function_call",
        "response_item.function_call_output",
        "response_item.message",
        "response_item.reasoning",
        "session_meta",
        "turn_context",
        "world_state",
    }
)
_KNOWN_COMPLETED_ITEM_TYPES = frozenset(
    {
        "AgentMessage",
        "CollabAgentToolCall",
        "CommandExecution",
        "ContextCompaction",
        "Extension",
        "FileChange",
        "ImageView",
        "McpToolCall",
        "Reasoning",
        "SubAgentActivity",
        "UserMessage",
    }
)


class CodexProtocolLibraryError(Exception):
    """Base exception for the persistent library contract."""


class ProtocolIdNotFoundError(CodexProtocolLibraryError):
    """A requested Codex protocol analysis ID does not exist."""


class InvalidProtocolEventError(CodexProtocolLibraryError):
    """An event cannot be stored as a chronological JSON object."""


class InvalidProtocolLogError(CodexProtocolLibraryError):
    """A source file is not an atomic sequence of JSON object records."""


class UnknownStatisticError(CodexProtocolLibraryError):
    """A requested statistic is outside the current public vocabulary."""


DiagnosticSeverity = Literal["warning", "error", "fatal"]
ResultStatus = Literal["ok", "warning", "error", "fatal"]
ResultValue = TypeVar("ResultValue")
ProtocolEventInput = Mapping[str, Any] | str | bytes


@dataclass(frozen=True, slots=True)
class LibraryDiagnostic:
    """A warning or failure that applications can handle without parsing text."""

    severity: DiagnosticSeverity
    code: str
    message: str
    source: str | None = None
    line_number: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class OperationResult[ResultValue]:
    """Stable no-crash boundary for every public application operation."""

    status: ResultStatus
    value: ResultValue | None
    diagnostics: tuple[LibraryDiagnostic, ...] = ()

    @property
    def is_fatal(self) -> bool:
        return self.status == "fatal"

    @property
    def has_value(self) -> bool:
        return self.value is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "value": _jsonable(self.value),
            "diagnostics": [diagnostic.to_dict() for diagnostic in self.diagnostics],
        }


@dataclass(frozen=True, slots=True)
class ProtocolDataset:
    """Persistent metadata for one application's analysis dataset."""

    protocol_id: str
    user_id: str
    created_at: str
    updated_at: str
    revision: int
    event_count: int
    source_count: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class LoadedSource:
    """Provenance for an ingested file or application event stream."""

    source_id: str
    source_kind: str
    source_name: str
    sha256: str | None
    event_count: int
    skipped_event_count: int
    new_event_type_count: int
    loaded_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class LoadFileResult:
    """Result of an idempotent file ingestion."""

    protocol_id: str
    source_id: str
    added_event_count: int
    skipped_event_count: int
    new_event_type_count: int
    already_loaded: bool
    revision: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class AddEventsResult:
    """Result of one atomic chronological append."""

    protocol_id: str
    stream_name: str
    added_event_count: int
    skipped_event_count: int
    new_event_type_count: int
    first_sequence: int
    last_sequence: int
    revision: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class StatsSnapshot:
    """Statistics calculated from one immutable dataset revision."""

    protocol_id: str
    user_id: str
    revision: int
    event_count: int
    source_count: int
    selected_stats: tuple[str, ...] | None
    must_have_basic_stats: dict[str, Any]
    recommended_insight_stats: dict[str, Any]
    audit: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class _PersistentCodexProtocolStore:
    """Own persistent analysis IDs and expose deterministic current statistics.

    One instance owns one SQLite connection. Applications that use multiple threads
    should create one instance per thread against the same database path.
    """

    def __init__(self, database_path: str | Path = ":memory:") -> None:
        database_name = str(database_path)
        if database_name != ":memory:":
            Path(database_name).expanduser().resolve().parent.mkdir(
                parents=True, exist_ok=True
            )
            database_name = str(Path(database_name).expanduser())
        self._connection = sqlite3.connect(database_name, timeout=30)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute("PRAGMA journal_mode = WAL")
        self._initialize_schema()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        """Close the owned database connection."""
        self._connection.close()

    def create_new_codex_protocol_id(self, user_id: str) -> str:
        """Create an empty persistent dataset for one application user."""
        normalized_user_id = _required_text(user_id, field_name="user_id")
        protocol_id = f"cpa_{uuid.uuid4().hex}"
        now = _utc_now()
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO protocol_datasets (
                    protocol_id, user_id, created_at, updated_at, revision
                ) VALUES (?, ?, ?, ?, 0)
                """,
                (protocol_id, normalized_user_id, now, now),
            )
        return protocol_id

    def get_protocol(self, protocol_id: str) -> ProtocolDataset:
        """Return metadata and current ingestion counts for one dataset."""
        row = self._connection.execute(
            """
            SELECT d.protocol_id, d.user_id, d.created_at, d.updated_at, d.revision,
                   (SELECT COUNT(*) FROM protocol_events AS e
                     WHERE e.protocol_id = d.protocol_id) AS event_count,
                   (SELECT COUNT(*) FROM protocol_sources AS s
                     WHERE s.protocol_id = d.protocol_id) AS source_count
              FROM protocol_datasets AS d
             WHERE d.protocol_id = ?
            """,
            (_required_protocol_id(protocol_id),),
        ).fetchone()
        if row is None:
            raise ProtocolIdNotFoundError(f"unknown protocol_id: {protocol_id}")
        return _dataset_from_row(row)

    def list_protocols(self, *, user_id: str | None = None) -> tuple[ProtocolDataset, ...]:
        """List datasets, optionally restricted to one external application user."""
        query = """
            SELECT d.protocol_id, d.user_id, d.created_at, d.updated_at, d.revision,
                   (SELECT COUNT(*) FROM protocol_events AS e
                     WHERE e.protocol_id = d.protocol_id) AS event_count,
                   (SELECT COUNT(*) FROM protocol_sources AS s
                     WHERE s.protocol_id = d.protocol_id) AS source_count
              FROM protocol_datasets AS d
        """
        parameters: tuple[str, ...] = ()
        if user_id is not None:
            query += " WHERE d.user_id = ?"
            parameters = (_required_text(user_id, field_name="user_id"),)
        query += " ORDER BY d.created_at, d.protocol_id"
        return tuple(
            _dataset_from_row(row)
            for row in self._connection.execute(query, parameters).fetchall()
        )

    def load_file(
        self, protocol_id: str, path: str | Path
    ) -> tuple[LoadFileResult, tuple[LibraryDiagnostic, ...]]:
        """Atomically ingest one JSONL file; identical bytes are loaded only once."""
        normalized_id = self._require_existing_protocol(protocol_id)
        log_path = Path(path)
        digest = _file_sha256(log_path)
        existing = self._connection.execute(
            """
            SELECT source_id
              FROM protocol_sources
             WHERE protocol_id = ? AND sha256 = ?
            """,
            (normalized_id, digest),
        ).fetchone()
        if existing is not None:
            return LoadFileResult(
                protocol_id=normalized_id,
                source_id=existing["source_id"],
                added_event_count=0,
                skipped_event_count=0,
                new_event_type_count=0,
                already_loaded=True,
                revision=self.get_protocol(normalized_id).revision,
            ), ()

        source_id = f"file_sha256_{digest}"
        loaded_at = _utc_now()
        added = 0
        skipped = 0
        diagnostics: list[LibraryDiagnostic] = []
        new_event_types: Counter[str] = Counter()
        second_digest = hashlib.sha256()
        try:
            with self._connection:
                self._connection.execute(
                    """
                    INSERT INTO protocol_sources (
                        protocol_id, source_id, source_kind, source_name, sha256,
                        event_count, skipped_event_count, new_event_type_count, loaded_at
                    ) VALUES (?, ?, 'file', ?, ?, 0, 0, 0, ?)
                    """,
                    (normalized_id, source_id, log_path.name, digest, loaded_at),
                )
                with log_path.open("rb") as lines:
                    for source_line, raw_line in enumerate(lines, start=1):
                        second_digest.update(raw_line)
                        if not raw_line.strip():
                            continue
                        try:
                            record = _decode_record(raw_line, source_line=source_line)
                        except InvalidProtocolLogError as error:
                            diagnostics.append(
                                LibraryDiagnostic(
                                    severity="error",
                                    code="malformed_json",
                                    message=str(error),
                                    source=log_path.name,
                                    line_number=source_line,
                                )
                            )
                            skipped += 1
                            continue
                        if event_name := _new_event_name(record):
                            new_event_types[event_name] += 1
                        self._insert_event(
                            normalized_id,
                            source_id,
                            source_line,
                            record,
                            require_timestamp=False,
                        )
                        added += 1
                if second_digest.hexdigest() != digest:
                    raise InvalidProtocolLogError(
                        f"source changed while it was being loaded: {log_path}"
                    )
                self._connection.execute(
                    """
                    UPDATE protocol_sources
                       SET event_count = ?, skipped_event_count = ?,
                           new_event_type_count = ?
                     WHERE protocol_id = ? AND source_id = ?
                    """,
                    (
                        added,
                        skipped,
                        len(new_event_types),
                        normalized_id,
                        source_id,
                    ),
                )
                revision = self._advance_revision(normalized_id)
        except sqlite3.IntegrityError:
            existing = self._connection.execute(
                """
                SELECT source_id
                  FROM protocol_sources
                 WHERE protocol_id = ? AND sha256 = ?
                """,
                (normalized_id, digest),
            ).fetchone()
            if existing is None:
                raise
            return LoadFileResult(
                protocol_id=normalized_id,
                source_id=existing["source_id"],
                added_event_count=0,
                skipped_event_count=0,
                new_event_type_count=0,
                already_loaded=True,
                revision=self.get_protocol(normalized_id).revision,
            ), ()
        for event_name, count in sorted(new_event_types.items()):
            diagnostics.append(
                LibraryDiagnostic(
                    severity="warning",
                    code="new_event_type",
                    message=f"new event type observed: {event_name} ({count} records)",
                    source=log_path.name,
                )
            )
        return (
            LoadFileResult(
                normalized_id,
                source_id,
                added,
                skipped,
                len(new_event_types),
                False,
                revision,
            ),
            tuple(diagnostics),
        )

    def add_event(
        self,
        protocol_id: str,
        event: ProtocolEventInput,
        *,
        stream_name: str = "live",
    ) -> tuple[AddEventsResult, tuple[LibraryDiagnostic, ...]]:
        """Append one timestamped event to a named chronological application stream."""
        return self.add_events(protocol_id, [event], stream_name=stream_name)

    def add_events(
        self,
        protocol_id: str,
        events: Iterable[ProtocolEventInput],
        *,
        stream_name: str = "live",
    ) -> tuple[AddEventsResult, tuple[LibraryDiagnostic, ...]]:
        """Append usable records and return diagnostics for records that were skipped."""
        normalized_id = self._require_existing_protocol(protocol_id)
        normalized_stream = _required_text(stream_name, field_name="stream_name")
        source_id = f"stream_{_sha256(normalized_stream)}"
        loaded_at = _utc_now()
        diagnostics: list[LibraryDiagnostic] = []
        new_event_types: Counter[str] = Counter()
        candidates: list[tuple[int, dict[str, Any], datetime]] = []
        for position, event in enumerate(events, start=1):
            try:
                record = _validated_record(event, require_timestamp=True)
                occurred_at = _event_datetime(record, required=True)
                assert occurred_at is not None
            except (InvalidProtocolEventError, TypeError, ValueError) as error:
                diagnostics.append(
                    LibraryDiagnostic(
                        severity="error",
                        code="invalid_event",
                        message=str(error),
                        source=normalized_stream,
                        line_number=position,
                    )
                )
                continue
            candidates.append((position, record, occurred_at))

        if not candidates:
            revision = self.get_protocol(normalized_id).revision
            return (
                AddEventsResult(
                    normalized_id,
                    normalized_stream,
                    0,
                    len(diagnostics),
                    0,
                    0,
                    0,
                    revision,
                ),
                tuple(diagnostics),
            )

        with self._connection:
            self._connection.execute(
                """
                INSERT OR IGNORE INTO protocol_sources (
                    protocol_id, source_id, source_kind, source_name, sha256,
                    event_count, skipped_event_count, new_event_type_count, loaded_at
                ) VALUES (?, ?, 'stream', ?, NULL, 0, 0, 0, ?)
                """,
                (normalized_id, source_id, normalized_stream, loaded_at),
            )
            row = self._connection.execute(
                """
                SELECT COALESCE(MAX(source_line), 0) AS last_sequence,
                       MAX(occurred_at) AS latest_timestamp
                  FROM protocol_events
                 WHERE protocol_id = ? AND source_id = ?
                """,
                (normalized_id, source_id),
            ).fetchone()
            first_sequence = int(row["last_sequence"]) + 1
            latest = _parse_datetime(row["latest_timestamp"])
            accepted: list[dict[str, Any]] = []
            for position, record, occurred_at in candidates:
                if latest is not None and occurred_at < latest:
                    diagnostics.append(
                        LibraryDiagnostic(
                            severity="error",
                            code="event_out_of_order",
                            message=(
                                "event timestamp is earlier than the latest accepted "
                                "event in this stream"
                            ),
                            source=normalized_stream,
                            line_number=position,
                        )
                    )
                    continue
                accepted.append(record)
                latest = occurred_at
                if event_name := _new_event_name(record):
                    new_event_types[event_name] += 1
            for offset, record in enumerate(accepted):
                self._insert_event(
                    normalized_id,
                    source_id,
                    first_sequence + offset,
                    record,
                    require_timestamp=True,
                )
            self._connection.execute(
                """
                UPDATE protocol_sources
                   SET event_count = event_count + ?,
                       skipped_event_count = skipped_event_count + ?,
                       new_event_type_count = new_event_type_count + ?
                 WHERE protocol_id = ? AND source_id = ?
                """,
                (
                    len(accepted),
                    len(candidates)
                    - len(accepted)
                    + sum(d.code == "invalid_event" for d in diagnostics),
                    len(new_event_types),
                    normalized_id,
                    source_id,
                ),
            )
            revision = (
                self._advance_revision(normalized_id)
                if accepted
                else self.get_protocol(normalized_id).revision
            )
        for event_name, count in sorted(new_event_types.items()):
            diagnostics.append(
                LibraryDiagnostic(
                    severity="warning",
                    code="new_event_type",
                    message=f"new event type observed: {event_name} ({count} records)",
                    source=normalized_stream,
                )
            )
        return (
            AddEventsResult(
                protocol_id=normalized_id,
                stream_name=normalized_stream,
                added_event_count=len(accepted),
                skipped_event_count=len(candidates)
                - len(accepted)
                + sum(d.code == "invalid_event" for d in diagnostics),
                new_event_type_count=len(new_event_types),
                first_sequence=first_sequence if accepted else 0,
                last_sequence=(first_sequence + len(accepted) - 1 if accepted else 0),
                revision=revision,
            ),
            tuple(diagnostics),
        )

    def list_sources(self, protocol_id: str) -> tuple[LoadedSource, ...]:
        """Return ingestion provenance without exposing stored event content."""
        normalized_id = self._require_existing_protocol(protocol_id)
        rows = self._connection.execute(
            """
            SELECT source_id, source_kind, source_name, sha256, event_count,
                   skipped_event_count, new_event_type_count, loaded_at
              FROM protocol_sources
             WHERE protocol_id = ?
             ORDER BY loaded_at, source_id
            """,
            (normalized_id,),
        ).fetchall()
        return tuple(LoadedSource(**dict(row)) for row in rows)

    def get_available_stats(self) -> dict[str, tuple[str, ...]]:
        """Return the current selectable statistic vocabulary."""
        report = analyze_rollout_record_sources([], source_description="empty dataset")
        report.audit["new_event_type_warnings"] = 0
        return {
            "must_have_basic_stats": tuple(report.must_have_basic_stats),
            "recommended_insight_stats": tuple(report.recommended_insight_stats),
            "audit": tuple(report.audit),
        }

    def get_stats(
        self,
        protocol_id: str,
        *,
        include: Sequence[str] | None = None,
    ) -> StatsSnapshot:
        """Calculate a revision-consistent snapshot without changing state."""
        with self._connection:
            self._connection.execute("BEGIN")
            return self._calculate_stats(protocol_id, include=include)

    def _calculate_stats(
        self,
        protocol_id: str,
        *,
        include: Sequence[str] | None,
    ) -> StatsSnapshot:
        dataset = self.get_protocol(protocol_id)
        source_ids = self._connection.execute(
            """
            SELECT source_id
              FROM protocol_sources
             WHERE protocol_id = ?
             ORDER BY source_id
            """,
            (dataset.protocol_id,),
        ).fetchall()
        report = analyze_rollout_record_sources(
            (
                (
                    row["source_id"],
                    self._stored_records(dataset.protocol_id, row["source_id"]),
                )
                for row in source_ids
            ),
            source_description=f"protocol_id:{dataset.protocol_id}",
        )
        basic = report.must_have_basic_stats
        insights = report.recommended_insight_stats
        audit = report.audit
        source_quality = self._connection.execute(
            """
            SELECT COALESCE(SUM(skipped_event_count), 0) AS skipped,
                   COALESCE(SUM(new_event_type_count), 0) AS new_event_types
              FROM protocol_sources
             WHERE protocol_id = ?
            """,
            (dataset.protocol_id,),
        ).fetchone()
        basic["history_coverage"]["malformed_records"] = int(source_quality["skipped"])
        audit["new_event_type_warnings"] = int(source_quality["new_event_types"])
        selected: tuple[str, ...] | None = None
        if include is not None:
            selected = tuple(dict.fromkeys(include))
            basic, insights, audit = _select_stats(selected, basic, insights, audit)
        return StatsSnapshot(
            protocol_id=dataset.protocol_id,
            user_id=dataset.user_id,
            revision=dataset.revision,
            event_count=dataset.event_count,
            source_count=dataset.source_count,
            selected_stats=selected,
            must_have_basic_stats=basic,
            recommended_insight_stats=insights,
            audit=audit,
        )

    def _stored_records(self, protocol_id: str, source_id: str) -> Iterable[dict[str, Any]]:
        rows = self._connection.execute(
            """
            SELECT record_json
              FROM protocol_events
             WHERE protocol_id = ? AND source_id = ?
             ORDER BY source_line
            """,
            (protocol_id, source_id),
        )
        for row in rows:
            yield json.loads(row["record_json"])

    def _require_existing_protocol(self, protocol_id: str) -> str:
        normalized_id = _required_protocol_id(protocol_id)
        row = self._connection.execute(
            "SELECT 1 FROM protocol_datasets WHERE protocol_id = ?", (normalized_id,)
        ).fetchone()
        if row is None:
            raise ProtocolIdNotFoundError(f"unknown protocol_id: {protocol_id}")
        return normalized_id

    def _insert_event(
        self,
        protocol_id: str,
        source_id: str,
        source_line: int,
        record: Mapping[str, Any],
        *,
        require_timestamp: bool,
    ) -> None:
        validated = _validated_record(record, require_timestamp=require_timestamp)
        occurred_at = _event_datetime(validated, required=require_timestamp)
        self._connection.execute(
            """
            INSERT INTO protocol_events (
                protocol_id, source_id, source_line, occurred_at, record_json
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                protocol_id,
                source_id,
                source_line,
                occurred_at.isoformat() if occurred_at else None,
                json.dumps(
                    validated, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                ),
            ),
        )

    def _advance_revision(self, protocol_id: str) -> int:
        now = _utc_now()
        self._connection.execute(
            """
            UPDATE protocol_datasets
               SET revision = revision + 1, updated_at = ?
             WHERE protocol_id = ?
            """,
            (now, protocol_id),
        )
        row = self._connection.execute(
            "SELECT revision FROM protocol_datasets WHERE protocol_id = ?", (protocol_id,)
        ).fetchone()
        return int(row["revision"])

    def _initialize_schema(self) -> None:
        with self._connection:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS protocol_datasets (
                    protocol_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    revision INTEGER NOT NULL CHECK (revision >= 0)
                );

                CREATE TABLE IF NOT EXISTS protocol_sources (
                    protocol_id TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    source_kind TEXT NOT NULL CHECK (source_kind IN ('file', 'stream')),
                    source_name TEXT NOT NULL,
                    sha256 TEXT,
                    event_count INTEGER NOT NULL CHECK (event_count >= 0),
                    skipped_event_count INTEGER NOT NULL DEFAULT 0
                        CHECK (skipped_event_count >= 0),
                    new_event_type_count INTEGER NOT NULL DEFAULT 0
                        CHECK (new_event_type_count >= 0),
                    loaded_at TEXT NOT NULL,
                    PRIMARY KEY (protocol_id, source_id),
                    UNIQUE (protocol_id, sha256),
                    FOREIGN KEY (protocol_id) REFERENCES protocol_datasets(protocol_id)
                );

                CREATE TABLE IF NOT EXISTS protocol_events (
                    event_row_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    protocol_id TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    source_line INTEGER NOT NULL CHECK (source_line >= 1),
                    occurred_at TEXT,
                    record_json TEXT NOT NULL,
                    UNIQUE (protocol_id, source_id, source_line),
                    FOREIGN KEY (protocol_id, source_id)
                        REFERENCES protocol_sources(protocol_id, source_id)
                );

                CREATE INDEX IF NOT EXISTS protocol_events_dataset
                    ON protocol_events(protocol_id, source_id, source_line);

                PRAGMA user_version = 2;
                """
            )
            self._ensure_source_column("skipped_event_count")
            self._ensure_source_column("new_event_type_count")

    def _ensure_source_column(self, column: str) -> None:
        existing = {
            row["name"]
            for row in self._connection.execute("PRAGMA table_info(protocol_sources)")
        }
        if column not in existing:
            self._connection.execute(
                f"ALTER TABLE protocol_sources ADD COLUMN {column} "
                "INTEGER NOT NULL DEFAULT 0 CHECK (" + column + " >= 0)"
            )


class CodexProtocolLibrary:
    """No-crash application API over the authoritative persistent pipeline."""

    def __init__(self, database_path: str | Path = ":memory:") -> None:
        self._store: _PersistentCodexProtocolStore | None = None
        self._startup_diagnostics: tuple[LibraryDiagnostic, ...] = ()
        try:
            self._store = _PersistentCodexProtocolStore(database_path)
        except Exception as error:  # Database startup is an application-visible fatal.
            self._startup_diagnostics = (
                _exception_diagnostic(error, operation="initialize", fatal=True),
            )

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    @property
    def ready(self) -> bool:
        return self._store is not None

    @property
    def startup_diagnostics(self) -> tuple[LibraryDiagnostic, ...]:
        return self._startup_diagnostics

    def close(self) -> OperationResult[bool]:
        """Close storage without raising into the host application."""
        if self._store is None:
            return OperationResult("fatal", False, self._startup_diagnostics)
        try:
            self._store.close()
        except Exception as error:
            return _failure_result(error, operation="close")
        self._store = None
        return OperationResult("ok", True)

    def create_new_codex_protocol_id(self, user_id: str) -> OperationResult[str]:
        """Create a dataset and return its unique ID in a structured result."""
        return self._call(
            "create_new_codex_protocol_id",
            lambda store: store.create_new_codex_protocol_id(user_id),
        )

    def get_protocol(self, protocol_id: str) -> OperationResult[ProtocolDataset]:
        return self._call("get_protocol", lambda store: store.get_protocol(protocol_id))

    def list_protocols(
        self, *, user_id: str | None = None
    ) -> OperationResult[tuple[ProtocolDataset, ...]]:
        return self._call(
            "list_protocols", lambda store: store.list_protocols(user_id=user_id)
        )

    def load_file(
        self, protocol_id: str, path: str | Path
    ) -> OperationResult[LoadFileResult]:
        return self._call_diagnostic_operation(
            "load_file", lambda store: store.load_file(protocol_id, path)
        )

    def add_event(
        self,
        protocol_id: str,
        event: ProtocolEventInput,
        *,
        stream_name: str = "live",
    ) -> OperationResult[AddEventsResult]:
        return self.add_events(protocol_id, [event], stream_name=stream_name)

    def add_events(
        self,
        protocol_id: str,
        events: Iterable[ProtocolEventInput],
        *,
        stream_name: str = "live",
    ) -> OperationResult[AddEventsResult]:
        return self._call_diagnostic_operation(
            "add_events",
            lambda store: store.add_events(protocol_id, events, stream_name=stream_name),
        )

    def list_sources(self, protocol_id: str) -> OperationResult[tuple[LoadedSource, ...]]:
        return self._call("list_sources", lambda store: store.list_sources(protocol_id))

    def get_available_stats(self) -> OperationResult[dict[str, tuple[str, ...]]]:
        return self._call("get_available_stats", lambda store: store.get_available_stats())

    def get_stats(
        self,
        protocol_id: str,
        *,
        include: Sequence[str] | None = None,
    ) -> OperationResult[StatsSnapshot]:
        return self._call(
            "get_stats", lambda store: store.get_stats(protocol_id, include=include)
        )

    def _call(
        self,
        operation: str,
        callback: Callable[[_PersistentCodexProtocolStore], ResultValue],
    ) -> OperationResult[ResultValue]:
        if self._store is None:
            return OperationResult("fatal", None, self._not_ready_diagnostics(operation))
        try:
            return OperationResult("ok", callback(self._store))
        except Exception as error:
            return _failure_result(error, operation=operation)

    def _call_diagnostic_operation(
        self,
        operation: str,
        callback: Callable[
            [_PersistentCodexProtocolStore],
            tuple[ResultValue, tuple[LibraryDiagnostic, ...]],
        ],
    ) -> OperationResult[ResultValue]:
        if self._store is None:
            return OperationResult("fatal", None, self._not_ready_diagnostics(operation))
        try:
            value, diagnostics = callback(self._store)
        except Exception as error:
            return _failure_result(error, operation=operation)
        return OperationResult(_result_status(diagnostics), value, diagnostics)

    def _not_ready_diagnostics(self, operation: str) -> tuple[LibraryDiagnostic, ...]:
        if self._startup_diagnostics:
            return self._startup_diagnostics
        return (
            LibraryDiagnostic(
                severity="fatal",
                code="library_closed",
                message=f"cannot {operation}: library storage is closed",
            ),
        )


def _select_stats(
    selected: tuple[str, ...],
    basic: dict[str, Any],
    insights: dict[str, Any],
    audit: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    categories = {
        "must_have_basic_stats": basic,
        "recommended_insight_stats": insights,
        "audit": audit,
    }
    known = set(categories)
    for values in categories.values():
        known.update(values)
    unknown = sorted(set(selected) - known)
    if unknown:
        raise UnknownStatisticError(f"unknown statistics: {', '.join(unknown)}")
    chosen: list[dict[str, Any]] = []
    for category_name, values in categories.items():
        if category_name in selected:
            chosen.append(dict(values))
        else:
            chosen.append({key: value for key, value in values.items() if key in selected})
    return chosen[0], chosen[1], chosen[2]


def _dataset_from_row(row: sqlite3.Row) -> ProtocolDataset:
    return ProtocolDataset(
        protocol_id=row["protocol_id"],
        user_id=row["user_id"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        revision=int(row["revision"]),
        event_count=int(row["event_count"]),
        source_count=int(row["source_count"]),
    )


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _decode_record(raw_line: bytes, *, source_line: int) -> dict[str, Any]:
    try:
        value = json.loads(raw_line, parse_constant=_reject_json_constant)
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as error:
        raise InvalidProtocolLogError(
            f"line {source_line}: invalid UTF-8 JSON object"
        ) from error
    if not isinstance(value, dict):
        raise InvalidProtocolLogError(f"line {source_line}: expected a JSON object")
    return value


def _validated_record(
    event: ProtocolEventInput, *, require_timestamp: bool
) -> dict[str, Any]:
    if isinstance(event, str | bytes):
        try:
            event = json.loads(event)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise InvalidProtocolEventError("event is malformed JSON") from error
    if not isinstance(event, Mapping):
        raise InvalidProtocolEventError("event must be a JSON object")
    record = dict(event)
    try:
        json.dumps(record, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as error:
        raise InvalidProtocolEventError(
            "event must contain JSON-compatible values"
        ) from error
    _event_datetime(record, required=require_timestamp)
    return record


def _event_datetime(event: Mapping[str, Any], *, required: bool) -> datetime | None:
    value = event.get("timestamp")
    if value is None and not required:
        return None
    if not isinstance(value, str) or not value:
        raise InvalidProtocolEventError(
            "event.timestamp must be a non-empty ISO-8601 string"
        )
    parsed = _parse_datetime(value)
    if parsed is None:
        raise InvalidProtocolEventError("event.timestamp is not valid ISO-8601")
    if parsed.tzinfo is None:
        raise InvalidProtocolEventError("event.timestamp must include a UTC offset")
    return parsed.astimezone(UTC)


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _required_protocol_id(value: str) -> str:
    normalized = _required_text(value, field_name="protocol_id")
    if not normalized.startswith("cpa_"):
        raise ProtocolIdNotFoundError(f"invalid protocol_id: {value}")
    return normalized


def _required_text(value: str, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    if len(value) > 1024:
        raise ValueError(f"{field_name} must be at most 1024 characters")
    return value.strip()


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds")


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-standard JSON number: {value}")


def _new_event_name(record: Mapping[str, Any]) -> str | None:
    record_type = record.get("type")
    if not isinstance(record_type, str) or not record_type:
        return "<unknown-shape>"
    payload = record.get("payload")
    payload_type = payload.get("type") if isinstance(payload, Mapping) else None
    event_name = (
        f"{record_type}.{payload_type}"
        if isinstance(payload_type, str) and payload_type
        else record_type
    )
    if event_name not in _KNOWN_ROLLOUT_EVENTS:
        return event_name
    if event_name == "event_msg.item_completed" and isinstance(payload, Mapping):
        item = payload.get("item")
        item_type = item.get("type") if isinstance(item, Mapping) else None
        if isinstance(item_type, str) and item_type not in _KNOWN_COMPLETED_ITEM_TYPES:
            return f"{event_name}.{item_type}"
    return None


def _result_status(diagnostics: tuple[LibraryDiagnostic, ...]) -> ResultStatus:
    severities = {diagnostic.severity for diagnostic in diagnostics}
    if "fatal" in severities:
        return "fatal"
    if "error" in severities:
        return "error"
    if "warning" in severities:
        return "warning"
    return "ok"


def _failure_result(error: Exception, *, operation: str) -> OperationResult[ResultValue]:
    diagnostic = _exception_diagnostic(error, operation=operation)
    return OperationResult(diagnostic.severity, None, (diagnostic,))


def _exception_diagnostic(
    error: Exception, *, operation: str, fatal: bool = False
) -> LibraryDiagnostic:
    severity: DiagnosticSeverity = "fatal" if fatal else "error"
    code = "invalid_input"
    if isinstance(error, ProtocolIdNotFoundError):
        code = "protocol_id_not_found"
    elif isinstance(error, UnknownStatisticError):
        code = "unknown_statistic"
    elif isinstance(error, FileNotFoundError):
        severity = "fatal"
        code = "source_not_found"
    elif isinstance(error, sqlite3.Error):
        severity = "fatal"
        code = "storage_error"
    elif isinstance(error, OSError):
        severity = "fatal"
        code = "io_error"
    elif not isinstance(error, (CodexProtocolLibraryError, TypeError, ValueError)):
        severity = "fatal"
        code = "internal_error"
    return LibraryDiagnostic(
        severity=severity,
        code=code,
        message=f"{operation} failed: {error}",
    )


def _jsonable(value: Any) -> Any:
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if isinstance(value, tuple | list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    return value
