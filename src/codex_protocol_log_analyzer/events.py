"""Normalize observed Codex JSONL shapes without discarding their raw payloads."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal

ProtocolFamily = Literal["app-server", "exec", "unknown"]


class ProtocolLogDecodeError(ValueError):
    """One nonblank log line is not a JSON object."""


@dataclass(frozen=True, slots=True)
class ProtocolEvent:
    """A small common view over one Codex event, retaining its full payload."""

    line_number: int
    family: ProtocolFamily
    name: str
    lifecycle: str | None
    thread_id: str | None
    turn_id: str | None
    item_id: str | None
    item_type: str | None
    status: str | None
    usage: dict[str, int]
    raw: dict[str, Any]


def parse_protocol_line(line: str, *, line_number: int = 1) -> ProtocolEvent:
    """Parse and normalize one nonblank JSONL record.

    Unknown JSON object shapes are valid events. This keeps newer protocol records
    available to callers even before the analyzer learns their fields.
    """
    try:
        raw = json.loads(line)
    except json.JSONDecodeError as error:
        raise ProtocolLogDecodeError(
            f"line {line_number}: invalid JSON at column {error.colno}: {error.msg}"
        ) from error
    if not isinstance(raw, dict):
        raise ProtocolLogDecodeError(f"line {line_number}: expected a JSON object")

    method = raw.get("method")
    event_type = raw.get("type")
    if isinstance(method, str):
        return _from_app_server(raw, method, line_number)
    if isinstance(event_type, str):
        return _from_exec(raw, event_type, line_number)
    return ProtocolEvent(
        line_number=line_number,
        family="unknown",
        name="<unknown>",
        lifecycle=None,
        thread_id=_string(raw.get("thread_id")),
        turn_id=_string(raw.get("turn_id")),
        item_id=None,
        item_type=None,
        status=_string(raw.get("status")),
        usage=_numeric_usage(raw.get("usage")),
        raw=raw,
    )


def _from_app_server(raw: dict[str, Any], method: str, line_number: int) -> ProtocolEvent:
    params = _mapping(raw.get("params"))
    item = _mapping(params.get("item"))
    turn = _mapping(params.get("turn"))
    thread = _mapping(params.get("thread"))
    lifecycle = method.rsplit("/", 1)[-1] if "/" in method else None
    return ProtocolEvent(
        line_number=line_number,
        family="app-server",
        name=method,
        lifecycle=lifecycle,
        thread_id=_string(params.get("threadId")) or _string(thread.get("id")),
        turn_id=_string(params.get("turnId")) or _string(turn.get("id")),
        item_id=_string(item.get("id")),
        item_type=_string(item.get("type")),
        status=(
            _status_value(item.get("status"))
            or _status_value(turn.get("status"))
            or _status_value(thread.get("status"))
        ),
        usage=_first_usage(raw, params, turn, thread),
        raw=raw,
    )


def _from_exec(raw: dict[str, Any], event_type: str, line_number: int) -> ProtocolEvent:
    item = _mapping(raw.get("item"))
    lifecycle = event_type.rsplit(".", 1)[-1] if "." in event_type else None
    return ProtocolEvent(
        line_number=line_number,
        family="exec",
        name=event_type,
        lifecycle=lifecycle,
        thread_id=_string(raw.get("thread_id")),
        turn_id=_string(raw.get("turn_id")),
        item_id=_string(item.get("id")),
        item_type=_string(item.get("type")),
        status=_string(item.get("status")) or _status_value(raw.get("status")),
        usage=_first_usage(raw, item),
        raw=raw,
    )


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _string(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _status_value(value: Any) -> str | None:
    if isinstance(value, str) and value:
        return value
    if isinstance(value, dict):
        return _string(value.get("type"))
    return None


def _first_usage(*containers: dict[str, Any]) -> dict[str, int]:
    for container in containers:
        usage = _numeric_usage(container.get("usage"))
        if usage:
            return usage
    return {}


def _numeric_usage(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    return {
        key: number
        for key, number in value.items()
        if isinstance(key, str) and isinstance(number, int) and not isinstance(number, bool)
    }
