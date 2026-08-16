from __future__ import annotations

import pytest

from codex_protocol_log_analyzer import ProtocolLogDecodeError, parse_protocol_line


def test_app_server_event_normalizes_nested_identity() -> None:
    event = parse_protocol_line(
        '{"method":"item/started","params":{"threadId":"thread-1",'
        '"turnId":"turn-1","item":{"id":"item-1","type":"webSearch"}}}'
    )

    assert event.family == "app-server"
    assert event.name == "item/started"
    assert event.lifecycle == "started"
    assert event.thread_id == "thread-1"
    assert event.turn_id == "turn-1"
    assert event.item_id == "item-1"
    assert event.item_type == "webSearch"


def test_exec_event_normalizes_documented_shape_and_keeps_raw_payload() -> None:
    event = parse_protocol_line(
        '{"type":"item.completed","item":{"id":"item_3",'
        '"type":"agent_message","text":"done"}}'
    )

    assert event.family == "exec"
    assert event.lifecycle == "completed"
    assert event.item_type == "agent_message"
    assert event.raw["item"]["text"] == "done"


def test_app_server_thread_started_reads_nested_thread_identity() -> None:
    event = parse_protocol_line(
        '{"method":"thread/started","params":{"thread":{"id":"thr_123"}}}'
    )

    assert event.family == "app-server"
    assert event.thread_id == "thr_123"


@pytest.mark.parametrize("line", ["[]", '"text"', "null", "{"])
def test_non_object_or_invalid_json_is_rejected(line: str) -> None:
    with pytest.raises(ProtocolLogDecodeError):
        parse_protocol_line(line, line_number=9)
