# Library API

`CodexProtocolLibrary` is the ALPHA application boundary for persistent Codex history
statistics. It uses SQLite from the Python standard library and introduces no runtime
dependency.

## One pipeline

```text
JSONL files / chronological events
              ↓
validation + structured diagnostics
              ↓
persistent source and event ledger
              ↓
one deterministic statistics pipeline
              ↓
StatsSnapshot → Python API / JSON CLI / Markdown CLI
```

The adapters do not calculate their own statistics. A dataset revision therefore has
the same meaning whether queried by another application, `codex-protocol`, or
`codex-log-stats`.

## Basic lifecycle

```python
from codex_protocol_log_analyzer import CodexProtocolLibrary

with CodexProtocolLibrary("runtime/codex-protocol.sqlite3") as library:
    created = library.create_new_codex_protocol_id("external-user-id")
    if created.value is None:
        handle(created.diagnostics)
    else:
        protocol_id = created.value

        loaded = library.load_file(protocol_id, "rollout.jsonl")
        appended = library.add_event(
            protocol_id,
            {
                "timestamp": "2026-08-16T12:00:00Z",
                "type": "event_msg",
                "payload": {"type": "task_started", "turn_id": "turn-1"},
            },
        )
        all_stats = library.get_stats(protocol_id)
        selected = library.get_stats(
            protocol_id,
            include=["turns", "token_usage", "command_zero_exit_rate_percent"],
        )
        bulk_turns = library.get_stats(protocol_id, include_turn_statistics=True)
        exact_turn = library.get_turn_stats(
            protocol_id, "turn-1", session_id="codex-session-id"
        )
```

The lifecycle methods are:

- `create_new_codex_protocol_id(user_id)` creates a durable `cpa_…` dataset ID.
- `load_file(protocol_id, path)` ingests valid JSON-object lines atomically and skips
  malformed lines with diagnostics. Loading identical file bytes again is idempotent.
- `add_event(protocol_id, event, stream_name="live")` appends one event. It accepts a
  mapping, JSON string, or UTF-8 JSON bytes.
- `add_events(...)` appends a batch, accepting chronological records and skipping
  invalid or out-of-order members.
- `get_stats(protocol_id)` returns every current statistic at one consistent revision.
- `get_stats(protocol_id, include=[...])` returns only named statistics or categories.
- `get_stats(protocol_id, include_turn_statistics=True)` also returns every keyed turn
  projection calculated in that same chronological pass.
- `get_turn_stats(protocol_id, turn_id, session_id=None)` selects one exact turn after
  full-dataset analysis. Supply `session_id` when the same turn ID exists in more than
  one source; missing and ambiguous identities return structured error diagnostics.
- `get_available_stats()` declares the current selectable vocabulary.
- `get_protocol`, `list_protocols`, and `list_sources` expose metadata and provenance.

One library instance owns one SQLite connection. Create one instance per application
thread; multiple instances may use the same database path.

The SQLite database stores complete source events so statistics can be recalculated as
the analyzer evolves. Those events can contain prompts, responses, paths, commands, and
tool output. Treat the database as sensitive application data and apply the same access,
retention, and backup controls as the original Codex logs. Human-facing statistics omit
that content by default.

## Result contract

Every public operation returns `OperationResult[T]` with `status`, optional `value`, and
zero or more typed `LibraryDiagnostic` values. Applications should branch on the result,
not parse exception text.

| Status | Meaning | Value |
|---|---|---|
| `ok` | Operation completed without diagnostics. | Present where the operation returns data. |
| `warning` | Operation completed, but a valid new event shape was observed. | Present. |
| `error` | One or more inputs were rejected or skipped, but the library remains usable. | Present for partial success; otherwise absent. |
| `fatal` | The operation could not safely complete, such as unavailable storage or source I/O. | Absent. |

Diagnostic codes are stable machine-facing categories. Current codes include
`new_event_type`, `malformed_json`, `invalid_event`, `event_out_of_order`,
`turn_id_not_found`, `turn_id_ambiguous`,
`protocol_id_not_found`, `unknown_statistic`, `source_not_found`, `storage_error`,
`io_error`, `library_closed`, and `internal_error`.

Valid unknown events are retained and produce an aggregated `new_event_type` warning.
Malformed JSON is skipped and produces a line-addressed `malformed_json` error; it is
not fatal and valid records from the same file remain queryable. Fatal diagnostics are
reserved for failures that prevent the requested operation from producing a trustworthy
result.

## CLI adapter

`codex-protocol` emits the same `OperationResult` as JSON and maps status to exit code:

- `ok` or `warning`: `0`
- `error`: `1`
- `fatal`: `2`
- interrupted: `130`

```bash
codex-protocol --database runtime/codex.sqlite3 create USER_ID
codex-protocol --database runtime/codex.sqlite3 load CPA_ID rollout.jsonl
codex-protocol --database runtime/codex.sqlite3 add-event CPA_ID '{...}'
codex-protocol --database runtime/codex.sqlite3 stats CPA_ID --include turns token_usage
codex-protocol --database runtime/codex.sqlite3 sources CPA_ID
```
