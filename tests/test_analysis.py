from __future__ import annotations

from io import StringIO
from pathlib import Path

from codex_protocol_log_analyzer import analyze_file, analyze_lines

FIXTURES = Path(__file__).parent / "fixtures"


def test_mixed_observed_protocol_families_share_one_report() -> None:
    report = analyze_file(FIXTURES / "mixed_observed_protocol.jsonl")

    assert report.event_count == 8
    assert report.families == {"app-server": 3, "exec": 5}
    assert report.event_names["item.started"] == 1
    assert report.event_names["item/started"] == 1
    assert report.item_types == {"commandExecution": 2, "command_execution": 2}
    assert report.token_usage == {
        "cached_input_tokens": 24448,
        "input_tokens": 24763,
        "output_tokens": 122,
        "reasoning_output_tokens": 0,
    }
    assert report.open_item_ids == ()


def test_malformed_and_unknown_lines_remain_visible() -> None:
    report = analyze_lines(
        StringIO('{"type":"turn.started"}\nnot-json\n\n{"future":true}\n'),
        source="observed.jsonl",
    )

    assert report.total_lines == 4
    assert report.blank_lines == 1
    assert report.event_count == 2
    assert report.malformed_line_count == 1
    assert report.unknown_event_count == 1
    assert report.unrecognized_event_count == 1
    assert report.diagnostics[0].line_number == 2
    assert report.diagnostics[0].raw_excerpt == "not-json"


def test_started_item_without_terminal_event_is_reported_as_open() -> None:
    report = analyze_lines(
        ['{"type":"item.started","item":{"id":"call-7","type":"mcp_tool_call"}}']
    )

    assert report.open_item_ids == ("call-7",)


def test_unrecognized_rollout_events_are_streamed_to_callback() -> None:
    observed = []
    report = analyze_lines(
        ['{"timestamp":"2026-08-16T00:00:00Z","type":"world_state","payload":{}}'],
        on_unrecognized=observed.append,
    )

    assert report.unrecognized_event_names == {"world_state": 1}
    assert [event.name for event in observed] == ["world_state"]
