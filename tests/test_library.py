from __future__ import annotations

import json
from pathlib import Path

from codex_protocol_log_analyzer import CodexProtocolLibrary
from codex_protocol_log_analyzer.library_cli import main as library_main
from codex_protocol_log_analyzer.statistics_cli import main as statistics_main


def _record(record_type: str, payload: dict[str, object], second: int) -> dict[str, object]:
    return {
        "timestamp": f"2026-08-01T10:00:{second:02d}Z",
        "type": record_type,
        "payload": payload,
    }


def _write_lines(path: Path, lines: list[str]) -> Path:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_persistent_lifecycle_partial_load_and_selected_stats(tmp_path: Path) -> None:
    database = tmp_path / "library.sqlite3"
    source = _write_lines(
        tmp_path / "rollout.jsonl",
        [
            json.dumps(_record("session_meta", {"id": "session-1"}, 0)),
            "not-json",
            '{"timestamp":"2026-08-01T10:00:00Z","type":"bad","value":NaN}',
            json.dumps(
                _record("event_msg", {"type": "task_started", "turn_id": "turn-1"}, 1)
            ),
            json.dumps(
                _record(
                    "event_msg",
                    {
                        "type": "task_complete",
                        "turn_id": "turn-1",
                        "duration_ms": 100,
                        "time_to_first_token_ms": 10,
                    },
                    2,
                )
            ),
            json.dumps(_record("future_event", {"value": 1}, 3)),
        ],
    )

    with CodexProtocolLibrary(database) as library:
        created = library.create_new_codex_protocol_id("user-7")
        assert created.status == "ok"
        assert created.value is not None
        protocol_id = created.value
        assert protocol_id.startswith("cpa_")

        loaded = library.load_file(protocol_id, source)
        assert loaded.status == "error"
        assert loaded.value is not None
        assert loaded.value.added_event_count == 4
        assert loaded.value.skipped_event_count == 2
        assert loaded.value.new_event_type_count == 1
        assert {(item.severity, item.code) for item in loaded.diagnostics} == {
            ("error", "malformed_json"),
            ("warning", "new_event_type"),
        }

        repeated = library.load_file(protocol_id, source)
        assert repeated.status == "ok"
        assert repeated.value is not None
        assert repeated.value.already_loaded is True
        assert repeated.value.added_event_count == 0

        selected = library.get_stats(
            protocol_id, include=["turns", "hands_on_turn_rate_percent"]
        )
        assert selected.status == "ok"
        assert selected.value is not None
        assert selected.value.must_have_basic_stats == {
            "turns": {"started": 1, "completed": 1, "aborted": 0, "open": 0}
        }
        assert set(selected.value.recommended_insight_stats) == {
            "hands_on_turn_rate_percent"
        }
        assert selected.value.audit == {}

        sources = library.list_sources(protocol_id)
        assert sources.value is not None
        assert len(sources.value) == 1
        assert sources.value[0].event_count == 4
        assert sources.value[0].skipped_event_count == 2

    with CodexProtocolLibrary(database) as reopened:
        current = reopened.get_stats(protocol_id)
        assert current.status == "ok"
        assert current.value is not None
        assert current.value.event_count == 4
        assert current.value.source_count == 1
        assert current.value.must_have_basic_stats["history_coverage"] == {
            "sessions": 1,
            "records": 4,
            "malformed_records": 2,
        }
        assert current.value.audit["new_event_type_warnings"] == 1


def test_chronological_appends_warn_skip_and_continue(tmp_path: Path) -> None:
    with CodexProtocolLibrary(tmp_path / "events.sqlite3") as library:
        created = library.create_new_codex_protocol_id("user")
        assert created.value is not None
        protocol_id = created.value

        known = library.add_event(protocol_id, _record("session_meta", {"id": "s"}, 1))
        assert known.status == "ok"
        assert known.value is not None
        assert known.value.added_event_count == 1

        new = library.add_event(protocol_id, _record("brand_new", {}, 2))
        assert new.status == "warning"
        assert new.value is not None
        assert new.value.added_event_count == 1
        assert new.diagnostics[0].code == "new_event_type"

        malformed = library.add_event(protocol_id, "{")
        assert malformed.status == "error"
        assert malformed.value is not None
        assert malformed.value.added_event_count == 0
        assert malformed.diagnostics[0].code == "invalid_event"

        partial = library.add_events(
            protocol_id,
            [
                _record("event_msg", {"type": "task_started", "turn_id": "t"}, 4),
                _record("event_msg", {"type": "task_complete", "turn_id": "t"}, 3),
                _record("event_msg", {"type": "task_complete", "turn_id": "t"}, 5),
                {"type": "event_msg", "payload": {"type": "token_count"}},
            ],
        )
        assert partial.status == "error"
        assert partial.value is not None
        assert partial.value.added_event_count == 2
        assert partial.value.skipped_event_count == 2
        assert {item.code for item in partial.diagnostics} == {
            "event_out_of_order",
            "invalid_event",
        }

        current = library.get_stats(protocol_id)
        assert current.value is not None
        assert current.value.event_count == 4
        assert current.value.must_have_basic_stats["turns"]["completed"] == 1


def test_expected_and_fatal_failures_are_structured(tmp_path: Path) -> None:
    with CodexProtocolLibrary() as library:
        missing = library.get_stats("cpa_does_not_exist")
        assert missing.status == "error"
        assert missing.value is None
        assert missing.diagnostics[0].code == "protocol_id_not_found"

        invalid_user = library.create_new_codex_protocol_id("  ")
        assert invalid_user.status == "error"
        assert invalid_user.diagnostics[0].code == "invalid_input"

    unavailable = CodexProtocolLibrary(tmp_path)
    assert unavailable.ready is False
    result = unavailable.create_new_codex_protocol_id("user")
    assert result.status == "fatal"
    assert result.value is None
    assert result.diagnostics[0].severity == "fatal"


def test_unknown_stat_selection_is_an_error_not_an_exception() -> None:
    with CodexProtocolLibrary() as library:
        created = library.create_new_codex_protocol_id("user")
        assert created.value is not None

        result = library.get_stats(created.value, include=["imaginary_stat"])

        assert result.status == "error"
        assert result.value is None
        assert result.diagnostics[0].code == "unknown_statistic"


def test_bulk_and_exact_turn_statistics_share_scoped_session_identity(
    tmp_path: Path,
) -> None:
    first = _write_lines(
        tmp_path / "first.jsonl",
        [
            json.dumps(_record("session_meta", {"id": "session-1"}, 0)),
            json.dumps(
                _record("event_msg", {"type": "task_started", "turn_id": "same"}, 1)
            ),
        ],
    )
    second = _write_lines(
        tmp_path / "second.jsonl",
        [
            json.dumps(_record("session_meta", {"id": "session-2"}, 0)),
            json.dumps(
                _record("event_msg", {"type": "task_started", "turn_id": "same"}, 1)
            ),
            json.dumps(
                _record(
                    "event_msg",
                    {"type": "task_complete", "turn_id": "same"},
                    2,
                )
            ),
        ],
    )
    with CodexProtocolLibrary() as library:
        created = library.create_new_codex_protocol_id("user")
        assert created.value is not None
        assert library.load_file(created.value, first).value is not None
        assert library.load_file(created.value, second).value is not None

        aggregate_only = library.get_stats(created.value)
        assert aggregate_only.value is not None
        assert aggregate_only.value.turn_statistics == ()

        bulk = library.get_stats(created.value, include_turn_statistics=True)
        assert bulk.value is not None
        assert [(turn.session_id, turn.outcome) for turn in bulk.value.turn_statistics] == [
            ("session-1", "open"),
            ("session-2", "completed"),
        ]

        ambiguous = library.get_turn_stats(created.value, "same")
        assert ambiguous.status == "error"
        assert ambiguous.value is None
        assert ambiguous.diagnostics[0].code == "turn_id_ambiguous"

        exact = library.get_turn_stats(created.value, "same", session_id="session-2")
        assert exact.status == "ok"
        assert exact.value is not None
        assert exact.value.outcome == "completed"

        missing = library.get_turn_stats(created.value, "missing")
        assert missing.status == "error"
        assert missing.diagnostics[0].code == "turn_id_not_found"


def test_statistics_cli_uses_partial_result_for_malformed_json(
    tmp_path: Path, capsys
) -> None:
    source = _write_lines(
        tmp_path / "partial.jsonl",
        [
            json.dumps(_record("session_meta", {"id": "s"}, 0)),
            "not-json",
            json.dumps(_record("event_msg", {"type": "task_started", "turn_id": "t"}, 1)),
        ],
    )

    assert statistics_main([str(source), "--format", "json"]) == 1
    output = capsys.readouterr()
    payload = json.loads(output.out)
    assert payload["must_have_basic_stats"]["history_coverage"] == {
        "sessions": 1,
        "records": 2,
        "malformed_records": 1,
    }
    assert "error: malformed_json" in output.err


def test_library_cli_is_a_thin_persistent_api_adapter(tmp_path: Path, capsys) -> None:
    database = tmp_path / "cli.sqlite3"
    common = ["--database", str(database)]

    assert library_main([*common, "create", "user-9"]) == 0
    created = json.loads(capsys.readouterr().out)
    protocol_id = created["value"]

    event = json.dumps(_record("session_meta", {"id": "session-9"}, 0))
    assert library_main([*common, "add-event", protocol_id, event]) == 0
    added = json.loads(capsys.readouterr().out)
    assert added["value"]["added_event_count"] == 1

    assert library_main([*common, "add-event", protocol_id, "{"]) == 1
    malformed = json.loads(capsys.readouterr().out)
    assert malformed["status"] == "error"
    assert malformed["diagnostics"][0]["code"] == "invalid_event"

    assert library_main([*common, "stats", protocol_id, "--include", "turns"]) == 0
    stats = json.loads(capsys.readouterr().out)
    assert stats["value"]["must_have_basic_stats"]["turns"]["started"] == 0
