from __future__ import annotations

import json
from pathlib import Path

from codex_protocol_log_analyzer.statistics import (
    analyze_rollout_files,
    render_markdown,
)
from codex_protocol_log_analyzer.statistics_cli import main


def _write(path: Path, records: list[dict[str, object]]) -> Path:
    path.write_text(
        "".join(json.dumps(record) + "\n" for record in records), encoding="utf-8"
    )
    return path


def _record(record_type: str, payload: dict[str, object], second: int) -> dict[str, object]:
    return {
        "timestamp": f"2026-08-01T10:00:{second:02d}Z",
        "type": record_type,
        "payload": payload,
    }


def _token(
    total: int, input_tokens: int, output_tokens: int, *, cached: int = 0
) -> dict[str, object]:
    usage = {
        "total_tokens": total,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cached_input_tokens": cached,
        "reasoning_output_tokens": 5,
    }
    return {
        "type": "token_count",
        "info": {
            "total_token_usage": usage,
            "last_token_usage": usage,
            "model_context_window": 1000,
        },
    }


def test_mixed_generations_ledgers_tokens_and_privacy(tmp_path: Path) -> None:
    first = _write(
        tmp_path / "first.jsonl",
        [
            _record("session_meta", {"id": "s1"}, 0),
            _record("event_msg", {"type": "task_started", "turn_id": "t1"}, 1),
            _record(
                "turn_context",
                {
                    "turn_id": "t1",
                    "cwd": "/secret/workspace",
                    "model": "model-a",
                    "timezone": "Etc/UTC",
                },
                2,
            ),
            _record(
                "turn_context",
                {
                    "turn_id": "t1",
                    "cwd": "/secret/workspace",
                    "model": "model-a",
                    "timezone": "Etc/UTC",
                },
                3,
            ),
            _record("event_msg", _token(120, 100, 20, cached=50), 4),
            _record("event_msg", _token(120, 100, 20, cached=50), 5),
            _record(
                "event_msg",
                {
                    "type": "exec_command_end",
                    "turn_id": "t1",
                    "call_id": "c1",
                    "command": ["/bin/bash", "-lc", "secret-program --secret"],
                    "exit_code": 1,
                    "duration": {"secs": 1, "nanos": 500_000_000},
                },
                6,
            ),
            _record(
                "response_item",
                {"type": "function_call", "call_id": "c1", "name": "exec"},
                7,
            ),
            _record(
                "response_item",
                {"type": "function_call_output", "call_id": "c1", "output": "secret"},
                8,
            ),
            _record(
                "event_msg",
                {
                    "type": "patch_apply_end",
                    "turn_id": "t1",
                    "call_id": "p1",
                    "changes": {"/secret/a": {"type": "add", "content": "secret"}},
                },
                9,
            ),
            _record("event_msg", _token(180, 150, 30, cached=75), 10),
            _record("event_msg", _token(15, 10, 5), 11),
            _record(
                "event_msg",
                {
                    "type": "task_complete",
                    "turn_id": "t1",
                    "duration_ms": 100,
                    "time_to_first_token_ms": 10,
                },
                12,
            ),
            _record("compacted", {"window_id": "window-1"}, 13),
            _record("event_msg", {"type": "context_compacted"}, 14),
            _record(
                "event_msg",
                {"type": "thread_goal_updated", "goal": {"status": "complete"}},
                15,
            ),
        ],
    )
    second = _write(
        tmp_path / "second.jsonl",
        [
            _record("session_meta", {"id": "s2"}, 0),
            _record("event_msg", {"type": "task_started", "turn_id": "t1"}, 1),
            _record("event_msg", _token(50, 40, 10), 2),
            _record(
                "event_msg",
                {
                    "type": "item_completed",
                    "turn_id": "t1",
                    "item": {
                        "type": "CommandExecution",
                        "id": "c1",
                        "command": ["/bin/bash", "-lc", "pytest -q"],
                        "exit_code": 0,
                        "duration": {"secs": 2, "nanos": 0},
                    },
                },
                3,
            ),
            _record(
                "response_item",
                {"type": "function_call", "call_id": "c2", "name": "wait"},
                4,
            ),
            _record(
                "event_msg",
                {
                    "type": "item_completed",
                    "turn_id": "t1",
                    "item": {
                        "type": "CollabAgentToolCall",
                        "id": "c2",
                        "tool": "wait",
                    },
                },
                5,
            ),
            _record(
                "event_msg",
                {
                    "type": "item_completed",
                    "turn_id": "t1",
                    "item": {
                        "type": "FileChange",
                        "id": "f1",
                        "changes": {
                            "/secret/b": {"type": "update", "move_path": "/secret/c"}
                        },
                    },
                },
                6,
            ),
            _record(
                "event_msg",
                {"type": "turn_aborted", "turn_id": "t1", "duration_ms": 200},
                7,
            ),
        ],
    )

    report = analyze_rollout_files([first, second])
    basic = report.must_have_basic_stats

    assert basic["history_coverage"]["sessions"] == 2
    assert basic["turns"] == {"started": 2, "completed": 1, "aborted": 1, "open": 0}
    assert basic["token_usage"]["total_tokens"] == 245
    assert basic["commands_executed"]["count"] == 2
    assert basic["commands_executed"]["exit_status"] == {
        "nonzero_exit": 1,
        "zero_exit": 1,
    }
    assert basic["model_tool_requests"]["count"] == 2
    assert basic["model_tool_requests"]["output_paired"] == 1
    assert basic["file_changes"]["operations"] == 2
    assert basic["file_changes"]["distinct_paths"] == 3
    assert basic["collaboration"]["operations"] == 1
    assert basic["compactions"] == 1
    assert basic["workspaces_and_models"]["models"] == {"model-a": 1}
    assert report.audit["token_epochs"] == 3
    assert report.audit["repeated_token_snapshots"] == 1
    assert [(turn.session_id, turn.turn_id) for turn in report.turn_statistics] == [
        ("s1", "t1"),
        ("s2", "t1"),
    ]
    completed = report.turn_statistics[0]
    assert completed.outcome == "completed"
    assert completed.must_have_basic_stats["token_usage"]["total_tokens"] == 195
    assert completed.must_have_basic_stats["commands_executed"]["exit_status"] == {
        "nonzero_exit": 1
    }
    assert completed.must_have_basic_stats["model_tool_requests"] == {
        "count": 1,
        "output_paired": 1,
        "by_tool": {"exec": 1},
    }
    assert completed.must_have_basic_stats["file_changes"] == {
        "operations": 1,
        "distinct_paths": 1,
        "change_occurrences": 1,
        "by_type": {"add": 1},
    }
    assert completed.recommended_insight_stats["cached_input_share_percent"] == 46.9
    assert completed.recommended_insight_stats["completed_after_nonzero_command"] is True
    rendered = json.dumps(report.to_dict()) + render_markdown(report)
    assert "secret" not in rendered
    assert "/secret" not in rendered


def test_turn_tokens_are_selected_after_the_session_baseline_is_reconciled(
    tmp_path: Path,
) -> None:
    source = _write(
        tmp_path / "baseline.jsonl",
        [
            _record("session_meta", {"id": "session"}, 0),
            _record("event_msg", _token(100, 80, 20, cached=40), 1),
            _record("event_msg", {"type": "task_started", "turn_id": "target"}, 2),
            _record("event_msg", _token(150, 120, 30, cached=70), 3),
            _record(
                "event_msg",
                {
                    "type": "task_complete",
                    "turn_id": "target",
                    "duration_ms": 400,
                    "time_to_first_token_ms": 25,
                },
                4,
            ),
        ],
    )

    turn = analyze_rollout_files([source]).turn_statistics[0]

    assert turn.must_have_basic_stats["token_usage"] == {
        "input_tokens": 40,
        "cached_input_tokens": 30,
        "cache_write_input_tokens": 0,
        "output_tokens": 10,
        "reasoning_output_tokens": 0,
        "total_tokens": 50,
    }
    assert turn.must_have_basic_stats["timing"] == {
        "duration_ms": 400,
        "time_to_first_token_ms": 25,
    }
    assert turn.recommended_insight_stats["cached_input_share_percent"] == 75.0


def test_insight_rates_include_their_relational_base_counts(tmp_path: Path) -> None:
    source = _write(
        tmp_path / "insight-bases.jsonl",
        [
            _record("session_meta", {"id": "session"}, 0),
            _record("event_msg", {"type": "task_started", "turn_id": "t1"}, 1),
            _record(
                "turn_context",
                {"turn_id": "t1", "cwd": "/workspace/a"},
                2,
            ),
            _record(
                "event_msg",
                {
                    "type": "exec_command_end",
                    "turn_id": "t1",
                    "call_id": "command-1",
                    "command": ["/bin/bash", "-lc", "pytest -q"],
                    "exit_code": 0,
                },
                3,
            ),
            _record(
                "event_msg",
                {
                    "type": "patch_apply_end",
                    "turn_id": "t1",
                    "call_id": "change-1",
                    "changes": {"/workspace/a/file.py": {"type": "update"}},
                },
                4,
            ),
            _record("event_msg", {"type": "task_complete", "turn_id": "t1"}, 5),
            _record("event_msg", {"type": "task_started", "turn_id": "t2"}, 6),
            _record(
                "turn_context",
                {"turn_id": "t2", "cwd": "/workspace/a"},
                7,
            ),
            _record(
                "event_msg",
                {
                    "type": "exec_command_end",
                    "turn_id": "t2",
                    "call_id": "command-2",
                    "command": ["/bin/bash", "-lc", "pytest -q"],
                    "exit_code": 0,
                },
                8,
            ),
            _record(
                "event_msg",
                {
                    "type": "patch_apply_end",
                    "turn_id": "t2",
                    "call_id": "change-2",
                    "changes": {"/workspace/a/file.py": {"type": "update"}},
                },
                9,
            ),
            _record("event_msg", {"type": "task_complete", "turn_id": "t2"}, 10),
            _record("event_msg", {"type": "task_started", "turn_id": "t3"}, 11),
            _record(
                "turn_context",
                {"turn_id": "t3", "cwd": "/workspace/b"},
                12,
            ),
            _record("event_msg", {"type": "task_complete", "turn_id": "t3"}, 13),
        ],
    )

    insights = analyze_rollout_files([source]).recommended_insight_stats

    assert insights["hands_on_turn_count"] == 2
    assert insights["repeated_command_execution_count"] == 2
    assert insights["exact_command_repeat_rate_percent"] == 100.0
    assert insights["revisited_distinct_path_count"] == 1
    assert insights["file_revisit_rate_percent"] == 100.0
    assert insights["workspace_tagged_turn_count"] == 3
    assert insights["turns_in_busiest_workspace_count"] == 2
    assert insights["busiest_workspace_turn_share_percent"] == 66.7


def test_empty_history_renders_na_and_cli_json(tmp_path: Path, capsys) -> None:
    source = _write(tmp_path / "empty.jsonl", [_record("session_meta", {"id": "s"}, 0)])

    report = analyze_rollout_files([source])

    assert report.must_have_basic_stats["token_usage"] == {
        "input_tokens": 0,
        "cached_input_tokens": 0,
        "cache_write_input_tokens": 0,
        "output_tokens": 0,
        "reasoning_output_tokens": 0,
        "total_tokens": 0,
        "per_turn_total_tokens": {
            "n": 0,
            "total": 0,
            "median": None,
            "p75": None,
            "p90": None,
            "p95": None,
            "max": None,
        },
    }
    assert "n/a (n=0)" in render_markdown(report)
    assert main([str(source), "--format", "json"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["must_have_basic_stats"]["turns"]["started"] == 0
