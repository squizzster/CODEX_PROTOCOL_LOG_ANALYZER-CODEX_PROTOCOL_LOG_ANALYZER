"""Privacy-safe statistical analysis of Codex rollout histories."""

from __future__ import annotations

import hashlib
import json
import math
import shlex
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


@dataclass(slots=True)
class _Turn:
    session: str
    turn_id: str
    started_at: datetime | None = None
    terminal_at: datetime | None = None
    outcome: str | None = None
    duration_ms: int | None = None
    ttft_ms: int | None = None
    command_ids: set[str] = field(default_factory=set)
    failed_command_ids: set[str] = field(default_factory=set)
    command_statuses: Counter[str] = field(default_factory=Counter)
    command_families: Counter[str] = field(default_factory=Counter)
    command_durations_ms: list[int] = field(default_factory=list)
    tool_call_ids: set[str] = field(default_factory=set)
    tool_output_ids: set[str] = field(default_factory=set)
    file_operation_ids: set[str] = field(default_factory=set)
    changed_paths: set[str] = field(default_factory=set)
    file_change_types: Counter[str] = field(default_factory=Counter)
    web_operation_ids: set[str] = field(default_factory=set)
    web_action_types: Counter[str] = field(default_factory=Counter)
    web_query_count: int = 0
    web_result_count: int = 0
    web_urls: set[str] = field(default_factory=set)
    collaboration_ids: set[str] = field(default_factory=set)
    collaboration_tools: Counter[str] = field(default_factory=Counter)
    agent_thread_ids: set[str] = field(default_factory=set)
    compaction_ids: set[str] = field(default_factory=set)
    goal_statuses: Counter[str] = field(default_factory=Counter)
    token_usage: Counter[str] = field(default_factory=Counter)
    context_observations: list[float] = field(default_factory=list)
    first_edit_sequence: int | None = None
    verification_sequences: list[int] = field(default_factory=list)
    first_web_sequence: int | None = None
    later_work_sequences: list[int] = field(default_factory=list)
    workspace: str | None = None
    model: str | None = None
    reasoning_effort: str | None = None
    local_hour: int | None = None
    timezone: str | None = None


@dataclass(frozen=True, slots=True)
class StatisticalReport:
    """Deterministic, JSON-serializable human statistics and trust metadata."""

    source: str
    must_have_basic_stats: dict[str, Any]
    recommended_insight_stats: dict[str, Any]
    audit: dict[str, Any]
    turn_statistics: tuple[TurnStatisticalReport, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class TurnStatisticalReport:
    """Privacy-safe statistics for one turn after full chronological analysis."""

    session_id: str
    turn_id: str
    started_at: str | None
    terminal_at: str | None
    outcome: str
    must_have_basic_stats: dict[str, Any]
    recommended_insight_stats: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def analyze_rollout_files(paths: list[str | Path]) -> StatisticalReport:
    """Build deduplicated ledgers over one or more Codex rollout JSONL files."""
    analyzer = _StatisticalAnalyzer()
    log_paths = [Path(path) for path in paths]
    for path in log_paths:
        analyzer.consume_file(path)
    return analyzer.report(source=f"{len(log_paths)} rollout files")


def analyze_rollout_record_sources(
    sources: Iterable[tuple[str, Iterable[Mapping[str, Any]]]],
    *,
    source_description: str = "rollout record sources",
) -> StatisticalReport:
    """Analyze named in-memory sources through the same pipeline used for files."""
    analyzer = _StatisticalAnalyzer()
    for source_name, records in sources:
        analyzer.consume_records(source_name, records)
    return analyzer.report(source=source_description)


class _StatisticalAnalyzer:
    def __init__(self) -> None:
        self.sessions: set[str] = set()
        self.turns: dict[tuple[str, str], _Turn] = {}
        self.active_turn: dict[str, str] = {}
        self.tool_requests: dict[tuple[str, str], str] = {}
        self.tool_outputs: set[tuple[str, str]] = set()
        self.commands: set[tuple[str, str]] = set()
        self.file_operations: set[tuple[str, str]] = set()
        self.web_operations: set[tuple[str, str]] = set()
        self.mcp_operations: set[tuple[str, str]] = set()
        self.collaboration_operations: set[tuple[str, str]] = set()
        self.compactions: set[tuple[str, str]] = set()
        self.agent_threads: set[tuple[str, str]] = set()
        self.command_statuses: Counter[str] = Counter()
        self.command_families: Counter[str] = Counter()
        self.command_durations_ms: list[int] = []
        self.command_hashes: Counter[str] = Counter()
        self.file_change_types: Counter[str] = Counter()
        self.path_operation_counts: Counter[str] = Counter()
        self.web_action_types: Counter[str] = Counter()
        self.web_query_count = 0
        self.web_result_count = 0
        self.web_urls: set[str] = set()
        self.collaboration_tools: Counter[str] = Counter()
        self.token_totals: Counter[str] = Counter()
        self.token_previous: dict[str, dict[str, int]] = {}
        self.token_epochs: Counter[str] = Counter()
        self.token_snapshots = 0
        self.token_repeated_snapshots = 0
        self.context_observations: list[float] = []
        self.last_context_ratio: dict[str, float] = {}
        self.goal_updates = 0
        self.goal_statuses: Counter[str] = Counter()
        self.malformed_lines = 0
        self.records = 0
        self.duplicate_operations = 0
        self.duplicate_terminals = 0
        self.terminal_without_start = 0
        self.sequence = 0

    def consume_file(self, path: Path) -> None:
        def parsed_records() -> Iterable[dict[str, Any]]:
            with path.open(encoding="utf-8") as lines:
                for line in lines:
                    if not line.strip():
                        continue
                    try:
                        record = json.loads(line)
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        self.malformed_lines += 1
                        continue
                    if not isinstance(record, dict):
                        self.malformed_lines += 1
                        continue
                    yield record

        self.consume_records(str(path.resolve()), parsed_records())

    def consume_records(
        self, source_name: str, records: Iterable[Mapping[str, Any]]
    ) -> None:
        """Consume one ordered source without leaking active state into the next."""
        source_key = f"source:{_digest(source_name)}"
        session = source_key
        self.sessions.add(session)
        self.active_turn.pop(session, None)
        for supplied_record in records:
            record = dict(supplied_record)
            self.records += 1
            self.sequence += 1
            payload = _mapping(record.get("payload"))
            if record.get("type") == "session_meta":
                identifier = _text(payload.get("id"))
                if identifier:
                    self.sessions.discard(source_key)
                    session = identifier
                    self.sessions.add(session)
                continue
            self._consume(record, payload, session)
        self.active_turn.pop(session, None)

    def _consume(
        self, record: dict[str, Any], payload: dict[str, Any], session: str
    ) -> None:
        record_type = _text(record.get("type")) or ""
        payload_type = _text(payload.get("type")) or ""
        turn_id = _text(payload.get("turn_id")) or self.active_turn.get(session)

        if record_type == "turn_context":
            self._turn_context(session, payload)
        elif record_type == "event_msg" and payload_type == "task_started":
            self._task_started(session, payload, record)
        elif record_type == "event_msg" and payload_type in {
            "task_complete",
            "turn_aborted",
        }:
            self._terminal(session, payload, record, payload_type)
        elif record_type == "event_msg" and payload_type == "token_count":
            self._tokens(session, turn_id, payload)
        elif record_type == "response_item":
            self._response_item(session, turn_id, payload)
        elif record_type == "event_msg" and payload_type == "item_completed":
            self._completed_item(session, turn_id, payload)
        elif record_type == "event_msg" and payload_type == "exec_command_end":
            self._command(session, turn_id, payload, "legacy")
        elif record_type == "event_msg" and payload_type == "patch_apply_end":
            self._file_change(session, turn_id, payload, "legacy")
        elif record_type == "event_msg" and payload_type == "web_search_end":
            self._web(session, turn_id, payload, "legacy")
        elif record_type == "event_msg" and payload_type == "mcp_tool_call_end":
            self._operation(self.mcp_operations, session, payload, "legacy-mcp")
        elif record_type == "event_msg" and payload_type == "sub_agent_activity":
            agent = _text(payload.get("agent_thread_id"))
            if payload.get("kind") == "started" and agent:
                self.agent_threads.add((session, agent))
                if turn := self._get_turn(session, turn_id):
                    turn.agent_thread_ids.add(agent)
        elif record_type == "event_msg" and payload_type == "thread_goal_updated":
            self.goal_updates += 1
            status = _text(_mapping(payload.get("goal")).get("status")) or "unknown"
            self.goal_statuses[status] += 1
            if turn := self._get_turn(session, turn_id):
                turn.goal_statuses[status] += 1
        elif record_type == "compacted":
            marker = _text(payload.get("window_id")) or _text(record.get("timestamp"))
            self.compactions.add((session, marker or str(self.sequence)))
            if turn := self._get_turn(session, turn_id):
                turn.compaction_ids.add(marker or str(self.sequence))

    def _task_started(
        self, session: str, payload: dict[str, Any], record: dict[str, Any]
    ) -> None:
        turn_id = _text(payload.get("turn_id"))
        if not turn_id:
            return
        key = (session, turn_id)
        turn = self.turns.setdefault(key, _Turn(session, turn_id))
        turn.started_at = turn.started_at or _timestamp(record.get("timestamp"))
        self.active_turn[session] = turn_id

    def _terminal(
        self,
        session: str,
        payload: dict[str, Any],
        record: dict[str, Any],
        payload_type: str,
    ) -> None:
        turn_id = _text(payload.get("turn_id"))
        if not turn_id:
            return
        key = (session, turn_id)
        turn = self.turns.get(key)
        if turn is None:
            self.terminal_without_start += 1
            return
        if turn.outcome is not None:
            self.duplicate_terminals += 1
            return
        turn.outcome = "completed" if payload_type == "task_complete" else "aborted"
        turn.terminal_at = _timestamp(record.get("timestamp"))
        turn.duration_ms = _nonnegative_int(payload.get("duration_ms"))
        turn.ttft_ms = _nonnegative_int(payload.get("time_to_first_token_ms"))
        if self.active_turn.get(session) == turn_id:
            self.active_turn.pop(session, None)

    def _turn_context(self, session: str, payload: dict[str, Any]) -> None:
        turn_id = _text(payload.get("turn_id"))
        if not turn_id:
            return
        turn = self.turns.get((session, turn_id))
        if turn is None:
            return
        cwd = _text(payload.get("cwd"))
        if cwd:
            turn.workspace = _digest(cwd)
        model = _text(payload.get("model"))
        if model:
            turn.model = model
        reasoning_effort = _text(payload.get("effort"))
        if reasoning_effort:
            turn.reasoning_effort = reasoning_effort
        timezone = _text(payload.get("timezone"))
        if timezone:
            turn.timezone = timezone
        if turn.started_at:
            try:
                zone = ZoneInfo(turn.timezone) if turn.timezone else None
            except ZoneInfoNotFoundError:
                zone = None
            observed = turn.started_at.astimezone(zone) if zone else turn.started_at
            turn.local_hour = observed.hour

    def _response_item(
        self, session: str, turn_id: str | None, payload: dict[str, Any]
    ) -> None:
        item_type = _text(payload.get("type")) or ""
        call_id = _text(payload.get("call_id"))
        if item_type in {"custom_tool_call", "function_call"} and call_id:
            key = (session, call_id)
            name = _text(payload.get("name")) or _text(payload.get("tool")) or "unknown"
            self.tool_requests.setdefault(key, name)
            if turn := self._get_turn(session, turn_id):
                turn.tool_call_ids.add(call_id)
        elif item_type in {"custom_tool_call_output", "function_call_output"} and call_id:
            self.tool_outputs.add((session, call_id))
            if turn := self._get_turn(session, turn_id):
                turn.tool_output_ids.add(call_id)

    def _completed_item(
        self, session: str, turn_id: str | None, payload: dict[str, Any]
    ) -> None:
        item = _mapping(payload.get("item"))
        item_type = _text(item.get("type")) or ""
        if item_type == "CommandExecution":
            self._command(session, turn_id, item, "canonical")
        elif item_type == "FileChange":
            self._file_change(session, turn_id, item, "canonical")
        elif item_type == "Extension" and item.get("kind") == "web.search":
            self._web(session, turn_id, item, "canonical")
        elif item_type == "CollabAgentToolCall":
            if self._operation(
                self.collaboration_operations, session, item, "collaboration"
            ):
                tool = _text(item.get("tool")) or "unknown"
                self.collaboration_tools[tool] += 1
                if turn := self._get_turn(session, turn_id):
                    turn.collaboration_ids.add(_operation_id(item, str(self.sequence)))
                    turn.collaboration_tools[tool] += 1
        elif item_type == "McpToolCall":
            self._operation(self.mcp_operations, session, item, "mcp")

    def _command(
        self, session: str, turn_id: str | None, item: dict[str, Any], provenance: str
    ) -> None:
        identifier = _operation_id(item, f"{provenance}:{self.sequence}")
        key = (session, identifier)
        if key in self.commands:
            self.duplicate_operations += 1
            return
        self.commands.add(key)
        exit_code = item.get("exit_code")
        status = "zero_exit" if exit_code == 0 else "nonzero_exit"
        if not isinstance(exit_code, int) or isinstance(exit_code, bool):
            status = "unknown_exit"
        self.command_statuses[status] += 1
        duration_ms = _duration_ms(item.get("duration"))
        if duration_ms is not None:
            self.command_durations_ms.append(duration_ms)
        family, command_hash = _command_identity(item)
        self.command_families[family] += 1
        if command_hash:
            self.command_hashes[command_hash] += 1
        if turn := self._get_turn(session, turn_id):
            turn.command_ids.add(identifier)
            turn.command_statuses[status] += 1
            turn.command_families[family] += 1
            if duration_ms is not None:
                turn.command_durations_ms.append(duration_ms)
            if status == "nonzero_exit":
                turn.failed_command_ids.add(identifier)
            if family == "verification":
                turn.verification_sequences.append(self.sequence)
            turn.later_work_sequences.append(self.sequence)

    def _file_change(
        self, session: str, turn_id: str | None, item: dict[str, Any], provenance: str
    ) -> None:
        identifier = _operation_id(item, f"{provenance}:{self.sequence}")
        if not self._operation(self.file_operations, session, item, provenance):
            return
        turn = self._get_turn(session, turn_id)
        if turn:
            turn.file_operation_ids.add(identifier)
            turn.first_edit_sequence = turn.first_edit_sequence or self.sequence
            turn.later_work_sequences.append(self.sequence)
        for path, change_value in _mapping(item.get("changes")).items():
            if not isinstance(path, str):
                continue
            path_key = _digest(path)
            self.path_operation_counts[path_key] += 1
            if turn:
                turn.changed_paths.add(path_key)
            change = _mapping(change_value)
            change_type = _text(change.get("type")) or "unknown"
            self.file_change_types[change_type] += 1
            if turn:
                turn.file_change_types[change_type] += 1
            move_path = _text(change.get("move_path"))
            if move_path:
                move_key = _digest(move_path)
                self.path_operation_counts[move_key] += 1
                if turn:
                    turn.changed_paths.add(move_key)

    def _web(
        self, session: str, turn_id: str | None, item: dict[str, Any], provenance: str
    ) -> None:
        identifier = _operation_id(item, f"{provenance}:{self.sequence}")
        if not self._operation(self.web_operations, session, item, provenance):
            return
        action = _mapping(item.get("action"))
        action_type = _text(action.get("type")) or "unknown"
        normalized = {"open_page": "open_page", "openPage": "open_page"}.get(
            action_type, action_type
        )
        self.web_action_types[normalized] += 1
        query = item.get("query")
        query_count = 0
        if isinstance(query, str) and query:
            self.web_query_count += 1
            query_count += 1
        queries = item.get("queries")
        if isinstance(queries, list):
            observed_queries = sum(
                isinstance(value, str) and bool(value) for value in queries
            )
            self.web_query_count += observed_queries
            query_count += observed_queries
        results = item.get("results")
        result_count = 0
        observed_urls: set[str] = set()
        if isinstance(results, list):
            result_count = len(results)
            self.web_result_count += result_count
            for result in results:
                url = _text(_mapping(result).get("url"))
                if url:
                    observed_urls.add(_digest(url))
        self.web_urls.update(observed_urls)
        if url := _text(action.get("url")):
            observed_urls.add(_digest(url))
            self.web_urls.add(_digest(url))
        if turn := self._get_turn(session, turn_id):
            turn.web_operation_ids.add(identifier)
            turn.first_web_sequence = turn.first_web_sequence or self.sequence
            turn.web_action_types[normalized] += 1
            turn.web_query_count += query_count
            turn.web_result_count += result_count
            turn.web_urls.update(observed_urls)

    def _tokens(self, session: str, turn_id: str | None, payload: dict[str, Any]) -> None:
        info = _mapping(payload.get("info"))
        current = _numeric_mapping(info.get("total_token_usage"))
        if not current:
            return
        self.token_snapshots += 1
        previous = self.token_previous.get(session)
        reset = previous is None or _cumulative_usage_decreased(previous, current)
        if reset:
            self.token_epochs[session] += 1
            delta = current
        else:
            delta = {
                key: value - previous.get(key, 0)
                for key, value in current.items()
                if value - previous.get(key, 0) > 0
            }
            if not delta:
                self.token_repeated_snapshots += 1
        self.token_previous[session] = current
        self.token_totals.update(delta)
        if turn := self._get_turn(session, turn_id):
            turn.token_usage.update(delta)
        last_usage = _numeric_mapping(info.get("last_token_usage"))
        total = last_usage.get("total_tokens")
        window = info.get("model_context_window")
        if isinstance(total, int) and isinstance(window, int) and window > 0:
            ratio = total / window
            self.context_observations.append(ratio)
            self.last_context_ratio[session] = ratio
            if turn := self._get_turn(session, turn_id):
                turn.context_observations.append(ratio)

    def _operation(
        self,
        ledger: set[tuple[str, str]],
        session: str,
        item: dict[str, Any],
        fallback: str,
    ) -> bool:
        key = (session, _operation_id(item, f"{fallback}:{self.sequence}"))
        if key in ledger:
            self.duplicate_operations += 1
            return False
        ledger.add(key)
        return True

    def _get_turn(self, session: str, turn_id: str | None) -> _Turn | None:
        return self.turns.get((session, turn_id)) if turn_id else None

    def _turn_statistical_report(self, turn: _Turn) -> TurnStatisticalReport:
        token_usage = {
            name: turn.token_usage[name]
            for name in (
                "input_tokens",
                "cached_input_tokens",
                "cache_write_input_tokens",
                "output_tokens",
                "reasoning_output_tokens",
                "total_tokens",
            )
        }
        tool_names = Counter(
            self.tool_requests[(turn.session, call_id)]
            for call_id in turn.tool_call_ids
            if (turn.session, call_id) in self.tool_requests
        )
        edited_then_verified = bool(
            turn.first_edit_sequence is not None
            and any(
                sequence > turn.first_edit_sequence
                for sequence in turn.verification_sequences
            )
        )
        researched_then_worked = bool(
            turn.first_web_sequence is not None
            and any(
                sequence > turn.first_web_sequence for sequence in turn.later_work_sequences
            )
        )
        basic = {
            "timing": {
                "duration_ms": turn.duration_ms,
                "time_to_first_token_ms": turn.ttft_ms,
            },
            "token_usage": token_usage,
            "context_window": {
                "observation_count": len(turn.context_observations),
                "high_water_percent": _round_percent(
                    max(turn.context_observations, default=0)
                ),
            },
            "commands_executed": {
                "count": len(turn.command_ids),
                "exit_status": dict(sorted(turn.command_statuses.items())),
                "duration_ms": _distribution(turn.command_durations_ms),
                "families": dict(turn.command_families.most_common()),
            },
            "model_tool_requests": {
                "count": len(turn.tool_call_ids),
                "output_paired": len(turn.tool_call_ids & turn.tool_output_ids),
                "by_tool": dict(tool_names.most_common()),
            },
            "file_changes": {
                "operations": len(turn.file_operation_ids),
                "distinct_paths": len(turn.changed_paths),
                "change_occurrences": sum(turn.file_change_types.values()),
                "by_type": dict(sorted(turn.file_change_types.items())),
            },
            "web_activity": {
                "operations": len(turn.web_operation_ids),
                "queries": turn.web_query_count,
                "result_records": turn.web_result_count,
                "distinct_result_or_action_urls": len(turn.web_urls),
                "by_action": dict(sorted(turn.web_action_types.items())),
            },
            "collaboration": {
                "operations": len(turn.collaboration_ids),
                "agents_started": len(turn.agent_thread_ids),
                "by_tool": dict(turn.collaboration_tools.most_common()),
            },
            "compactions": len(turn.compaction_ids),
            "workspace_and_model": {
                "workspace_digest": turn.workspace,
                "model": turn.model,
                "reasoning_effort": turn.reasoning_effort,
                "local_start_hour": turn.local_hour,
            },
        }
        insights = {
            "hands_on": bool(
                turn.command_ids
                or turn.tool_call_ids
                or turn.file_operation_ids
                or turn.web_operation_ids
                or turn.collaboration_ids
            ),
            "completed_after_nonzero_command": bool(
                turn.failed_command_ids and turn.outcome == "completed"
            ),
            "cached_input_share_percent": _rate(
                turn.token_usage["cached_input_tokens"],
                turn.token_usage["input_tokens"],
            ),
            "reasoning_output_share_percent": _rate(
                turn.token_usage["reasoning_output_tokens"],
                turn.token_usage["output_tokens"],
            ),
            "edited_then_verified": edited_then_verified,
            "web_research_followed_by_command_or_file_work": researched_then_worked,
            "goal_tracking": {
                "updates": sum(turn.goal_statuses.values()),
                "statuses": dict(sorted(turn.goal_statuses.items())),
            },
        }
        return TurnStatisticalReport(
            session_id=turn.session,
            turn_id=turn.turn_id,
            started_at=(None if turn.started_at is None else turn.started_at.isoformat()),
            terminal_at=(
                None if turn.terminal_at is None else turn.terminal_at.isoformat()
            ),
            outcome=turn.outcome or "open",
            must_have_basic_stats=basic,
            recommended_insight_stats=insights,
        )

    def report(self, *, source: str) -> StatisticalReport:
        turns = list(self.turns.values())
        workspaces = Counter(turn.workspace for turn in turns if turn.workspace is not None)
        models = Counter(turn.model for turn in turns if turn.model is not None)
        reasoning_efforts = Counter(
            turn.reasoning_effort for turn in turns if turn.reasoning_effort is not None
        )
        completed = [turn for turn in turns if turn.outcome == "completed"]
        aborted = [turn for turn in turns if turn.outcome == "aborted"]
        open_turns = [turn for turn in turns if turn.outcome is None]
        completed_durations = [
            turn.duration_ms for turn in completed if turn.duration_ms is not None
        ]
        ttfts = [turn.ttft_ms for turn in completed if turn.ttft_ms is not None]
        turn_tokens = [turn.token_usage["total_tokens"] for turn in turns]
        turns_with_failed_commands = [turn for turn in turns if turn.failed_command_ids]
        recovered_turns = [
            turn for turn in turns_with_failed_commands if turn.outcome == "completed"
        ]
        hands_on = [
            turn
            for turn in turns
            if turn.command_ids
            or turn.tool_call_ids
            or turn.file_operation_ids
            or turn.web_operation_ids
            or turn.collaboration_ids
        ]
        edited = [turn for turn in turns if turn.file_operation_ids]
        verified_after_edit = [
            turn
            for turn in edited
            if turn.first_edit_sequence is not None
            and any(seq > turn.first_edit_sequence for seq in turn.verification_sequences)
        ]
        web_turns = [turn for turn in turns if turn.web_operation_ids]
        web_follow_through = [
            turn
            for turn in web_turns
            if turn.first_web_sequence is not None
            and any(seq > turn.first_web_sequence for seq in turn.later_work_sequences)
        ]
        tool_names = Counter(self.tool_requests.values())
        commands_per_turn = [len(turn.command_ids) for turn in turns]
        tools_per_turn = [len(turn.tool_call_ids) for turn in turns]
        files_per_turn = [len(turn.changed_paths) for turn in turns]
        repeated_commands = sum(
            count for count in self.command_hashes.values() if count > 1
        )
        revisited_distinct_paths = sum(
            count >= 2 for count in self.path_operation_counts.values()
        )
        workspace_tagged_turns = sum(workspaces.values())
        turns_in_busiest_workspace = max(workspaces.values(), default=0)
        input_tokens = self.token_totals["input_tokens"]
        output_tokens = self.token_totals["output_tokens"]
        hour_counts = Counter(
            turn.local_hour for turn in turns if turn.local_hour is not None
        )
        basic = {
            "history_coverage": {
                "sessions": len(self.sessions),
                "records": self.records,
                "malformed_records": self.malformed_lines,
            },
            "turns": {
                "started": len(turns),
                "completed": len(completed),
                "aborted": len(aborted),
                "open": len(open_turns),
            },
            "completed_turn_duration_ms": _distribution(completed_durations),
            "time_to_first_token_ms": _distribution(ttfts),
            "token_usage": {
                **{
                    name: self.token_totals[name]
                    for name in (
                        "input_tokens",
                        "cached_input_tokens",
                        "cache_write_input_tokens",
                        "output_tokens",
                        "reasoning_output_tokens",
                        "total_tokens",
                    )
                },
                "per_turn_total_tokens": _distribution(turn_tokens),
            },
            "context_window": {
                "observation_count": len(self.context_observations),
                "latest_session_median_percent": _percent_value(
                    list(self.last_context_ratio.values())
                ),
                "high_water_percent": _round_percent(
                    max(self.context_observations, default=0)
                ),
            },
            "commands_executed": {
                "count": len(self.commands),
                "exit_status": dict(sorted(self.command_statuses.items())),
                "duration_ms": _distribution(self.command_durations_ms),
                "families": dict(self.command_families.most_common()),
            },
            "model_tool_requests": {
                "count": len(self.tool_requests),
                "output_paired": len(self.tool_requests.keys() & self.tool_outputs),
                "by_tool": dict(tool_names.most_common()),
            },
            "file_changes": {
                "operations": len(self.file_operations),
                "distinct_paths": len(self.path_operation_counts),
                "change_occurrences": sum(self.file_change_types.values()),
                "by_type": dict(sorted(self.file_change_types.items())),
            },
            "web_activity": {
                "operations": len(self.web_operations),
                "queries": self.web_query_count,
                "result_records": self.web_result_count,
                "distinct_result_or_action_urls": len(self.web_urls),
                "by_action": dict(sorted(self.web_action_types.items())),
            },
            "collaboration": {
                "operations": len(self.collaboration_operations),
                "agents_started": len(self.agent_threads),
                "by_tool": dict(self.collaboration_tools.most_common()),
            },
            "compactions": len(self.compactions),
            "workspaces_and_models": {
                "distinct_workspaces": len(workspaces),
                "models": dict(models.most_common()),
                "reasoning_efforts": dict(reasoning_efforts.most_common()),
            },
        }
        insights = {
            "typical_turn_anatomy": {
                "turns": len(turns),
                "commands_per_turn": _distribution(commands_per_turn),
                "tool_requests_per_turn": _distribution(tools_per_turn),
                "files_per_turn": _distribution(files_per_turn),
            },
            "hands_on_turn_count": len(hands_on),
            "hands_on_turn_rate_percent": _rate(len(hands_on), len(turns)),
            "completed_after_nonzero_command": {
                "turns_with_nonzero_command": len(turns_with_failed_commands),
                "subsequently_completed": len(recovered_turns),
                "percent": _rate(len(recovered_turns), len(turns_with_failed_commands)),
            },
            "command_zero_exit_rate_percent": _rate(
                self.command_statuses["zero_exit"],
                self.command_statuses["zero_exit"] + self.command_statuses["nonzero_exit"],
            ),
            "repeated_command_execution_count": repeated_commands,
            "exact_command_repeat_rate_percent": _rate(
                repeated_commands, len(self.commands)
            ),
            "cached_input_share_percent": _rate(
                self.token_totals["cached_input_tokens"], input_tokens
            ),
            "reasoning_output_share_percent": _rate(
                self.token_totals["reasoning_output_tokens"], output_tokens
            ),
            "turns_with_edit_then_verification": {
                "edited_turns": len(edited),
                "verified_after_edit": len(verified_after_edit),
                "percent": _rate(len(verified_after_edit), len(edited)),
            },
            "web_research_follow_through": {
                "web_turns": len(web_turns),
                "later_command_or_file_work": len(web_follow_through),
                "percent": _rate(len(web_follow_through), len(web_turns)),
            },
            "revisited_distinct_path_count": revisited_distinct_paths,
            "file_revisit_rate_percent": _rate(
                revisited_distinct_paths, len(self.path_operation_counts)
            ),
            "workspace_tagged_turn_count": workspace_tagged_turns,
            "turns_in_busiest_workspace_count": turns_in_busiest_workspace,
            "busiest_workspace_turn_share_percent": _rate(
                turns_in_busiest_workspace, workspace_tagged_turns
            ),
            "working_rhythm": {
                "turns_with_hour": sum(hour_counts.values()),
                "busiest_local_hour": (
                    hour_counts.most_common(1)[0][0] if hour_counts else None
                ),
                "turns_in_busiest_hour": (
                    hour_counts.most_common(1)[0][1] if hour_counts else 0
                ),
            },
            "goal_tracking": {
                "updates": self.goal_updates,
                "statuses": dict(sorted(self.goal_statuses.items())),
            },
        }
        audit = {
            "privacy": (
                "aggregate-only; content, commands, outputs, paths, queries, and URLs "
                "omitted"
            ),
            "percentile_method": "nearest-rank; median uses midpoint for even samples",
            "token_method": (
                "positive deltas of cumulative per-session snapshots; new epoch on decrease"
            ),
            "token_snapshots": self.token_snapshots,
            "repeated_token_snapshots": self.token_repeated_snapshots,
            "token_epochs": sum(self.token_epochs.values()),
            "duplicate_operations_ignored": self.duplicate_operations,
            "duplicate_terminals_ignored": self.duplicate_terminals,
            "terminal_events_without_start_ignored": self.terminal_without_start,
            "limits": [
                (
                    "completed means a terminal record exists, not that the objective "
                    "succeeded"
                ),
                (
                    "nonzero command recovery means the turn later completed, not that "
                    "the error caused it"
                ),
                "web results do not prove a page was read",
                "command families are deterministic inference with unknowns retained",
                "elapsed duration is not active human time or time saved",
            ],
        }
        turn_statistics = tuple(
            self._turn_statistical_report(turn)
            for turn in sorted(
                turns,
                key=lambda item: (
                    item.session,
                    "" if item.started_at is None else item.started_at.isoformat(),
                    item.turn_id,
                ),
            )
        )
        return StatisticalReport(source, basic, insights, audit, turn_statistics)


def render_markdown(report: StatisticalReport) -> str:
    """Render a compact preliminary report with the two human-facing lists."""
    basic = report.must_have_basic_stats
    insights = report.recommended_insight_stats
    turns = basic["turns"]
    tokens = basic["token_usage"]
    commands = basic["commands_executed"]
    tools = basic["model_tool_requests"]
    files = basic["file_changes"]
    web = basic["web_activity"]
    collab = basic["collaboration"]
    duration = basic["completed_turn_duration_ms"]
    ttft = basic["time_to_first_token_ms"]
    coverage = basic["history_coverage"]
    context = basic["context_window"]
    work = basic["workspaces_and_models"]
    anatomy = insights["typical_turn_anatomy"]
    recovery = insights["completed_after_nonzero_command"]
    edit_verify = insights["turns_with_edit_then_verification"]
    web_follow = insights["web_research_follow_through"]
    rhythm = insights["working_rhythm"]
    goals = insights["goal_tracking"]
    turn_token_dist = tokens["per_turn_total_tokens"]
    lines = [
        "# Preliminary statistical report",
        "",
        f"Source: {report.source}. Deterministic aggregate analysis; no AI interpretation.",
        "",
        "## MUST HAVE BASIC STATS",
        "",
        f"1. **Sessions and coverage:** {coverage['sessions']:,} sessions; "
        f"{coverage['records']:,} records; {coverage['malformed_records']:,} malformed.",
        f"2. **Turn calls:** {turns['started']:,} started; "
        f"{turns['completed']:,} completed; "
        f"{turns['aborted']:,} aborted; {turns['open']:,} open.",
        f"3. **Completed-turn duration:** {_dist_text(duration)}.",
        f"4. **Time to first token:** {_dist_text(ttft)}.",
        f"5. **Tokens:** {tokens.get('total_tokens', 0):,} total; "
        f"{tokens.get('input_tokens', 0):,} input; "
        f"{tokens.get('output_tokens', 0):,} output; "
        f"median {_display(turn_token_dist['median'])} per turn "
        f"(n={turn_token_dist['n']:,}).",
        f"6. **Context use:** {context['latest_session_median_percent']}% "
        f"median latest session fill; {context['high_water_percent']}% high-water mark.",
        f"7. **Commands executed:** {commands['count']:,}; "
        f"{commands['exit_status'].get('zero_exit', 0):,} zero exit; "
        f"{commands['exit_status'].get('nonzero_exit', 0):,} nonzero exit; "
        f"mix: {_counts_text(commands['families'])}.",
        f"8. **Model tool requests:** {tools['count']:,}; "
        f"{tools['output_paired']:,} paired with an output record; "
        f"mix: {_counts_text(tools['by_tool'])}.",
        f"9. **Files changed:** {files['operations']:,} operations; "
        f"{files['distinct_paths']:,} distinct paths; "
        f"{files['change_occurrences']:,} change occurrences.",
        f"10. **Web activity:** {web['operations']:,} operations; "
        f"{web['queries']:,} queries; "
        f"{web['result_records']:,} result records.",
        f"11. **Collaboration:** {collab['operations']:,} completed operations; "
        f"{collab['agents_started']:,} agent threads started.",
        f"12. **Compactions:** {basic['compactions']:,} context-window compactions.",
        f"13. **Workspaces and model settings:** "
        f"{work['distinct_workspaces']:,} workspaces; "
        f"models: {_counts_text(work['models'])}; reasoning efforts: "
        f"{_counts_text(work['reasoning_efforts'])}.",
        "",
        "## RECOMMENDED INSIGHT STATS",
        "",
        f"1. **Typical turn anatomy:** median "
        f"{anatomy['commands_per_turn']['median']} commands, "
        f"{anatomy['tool_requests_per_turn']['median']} tool requests, and "
        f"{anatomy['files_per_turn']['median']} changed files.",
        f"2. **Hands-on turn rate:** {insights['hands_on_turn_rate_percent']}% "
        "of turns used a tool request, command, "
        "file operation, web operation, or collaboration operation.",
        f"3. **Recovery after a nonzero command:** "
        f"{recovery['subsequently_completed']:,} of "
        f"{recovery['turns_with_nonzero_command']:,} such turns later completed "
        f"({recovery['percent']}%).",
        f"4. **Command reliability:** {insights['command_zero_exit_rate_percent']}% "
        "of commands with a "
        "known exit code exited zero.",
        f"5. **Exact command repetition:** "
        f"{insights['exact_command_repeat_rate_percent']}% of command "
        "executions repeated a command seen elsewhere in the corpus.",
        f"6. **Cached-input share:** {insights['cached_input_share_percent']}% "
        "of input tokens were cached.",
        f"7. **Reasoning-output share:** {insights['reasoning_output_share_percent']}% "
        "of output tokens "
        "were reasoning tokens.",
        f"8. **Edit then verify:** {edit_verify['verified_after_edit']:,} of "
        f"{edit_verify['edited_turns']:,} edited turns had a later "
        f"deterministically classified verification command "
        f"({edit_verify['percent']}%).",
        f"9. **Web follow-through:** {web_follow['later_command_or_file_work']:,} of "
        f"{web_follow['web_turns']:,} web turns had later command or file work "
        f"({web_follow['percent']}%).",
        f"10. **File revisits:** {insights['file_revisit_rate_percent']}% "
        "of changed paths appeared in "
        "at least two file-change operations.",
        f"11. **Project concentration:** the busiest workspace accounted for "
        f"{insights['busiest_workspace_turn_share_percent']}% of workspace-tagged turns.",
        f"12. **Working rhythm:** busiest local start hour "
        f"{rhythm['busiest_local_hour']!s}:00 with "
        f"{rhythm['turns_in_busiest_hour']:,} turns "
        f"(n={rhythm['turns_with_hour']:,}).",
        f"13. **Goal tracking:** {goals['updates']:,} updates; "
        f"{_counts_text(goals['statuses'])}.",
        "",
        "## Trust notes",
        "",
        f"- Tokens: {report.audit['token_method']}; "
        f"{report.audit['repeated_token_snapshots']:,} repeated snapshots ignored across "
        f"{report.audit['token_epochs']:,} epochs.",
        f"- Percentiles: {report.audit['percentile_method']}.",
        f"- Privacy: {report.audit['privacy']}.",
    ]
    lines.extend(f"- Limitation: {limit}." for limit in report.audit["limits"])
    return "\n".join(lines) + "\n"


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _numeric_mapping(value: Any) -> dict[str, int]:
    return {
        key: number
        for key, number in _mapping(value).items()
        if isinstance(key, str) and isinstance(number, int) and not isinstance(number, bool)
    }


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _nonnegative_int(value: Any) -> int | None:
    return (
        value
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0
        else None
    )


def _timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None


def _duration_ms(value: Any) -> int | None:
    duration = _mapping(value)
    secs = duration.get("secs")
    nanos = duration.get("nanos")
    if not isinstance(secs, int) or isinstance(secs, bool):
        return None
    if not isinstance(nanos, int) or isinstance(nanos, bool):
        nanos = 0
    return max(0, secs * 1000 + nanos // 1_000_000)


def _cumulative_usage_decreased(previous: dict[str, int], current: dict[str, int]) -> bool:
    if "total_tokens" in previous and "total_tokens" in current:
        return current["total_tokens"] < previous["total_tokens"]
    core_fields = ("input_tokens", "output_tokens")
    return any(
        key in previous and key in current and current[key] < previous[key]
        for key in core_fields
    )


def _operation_id(item: dict[str, Any], fallback: str) -> str:
    return _text(item.get("id")) or _text(item.get("call_id")) or fallback


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _command_identity(item: dict[str, Any]) -> tuple[str, str | None]:
    command = item.get("command")
    if not isinstance(command, list) or not all(isinstance(part, str) for part in command):
        return "unknown", None
    joined = "\0".join(command)
    raw = command[-1].strip().lower() if command else ""
    family = "other"
    verification_markers = (
        "pytest",
        "unittest",
        "ruff",
        "mypy",
        "pyright",
        "npm test",
        "cargo test",
        "go test",
        " test ",
        " lint",
    )
    if any(marker in f" {raw} " for marker in verification_markers):
        family = "verification"
    else:
        try:
            first = shlex.split(raw)[0] if raw else ""
        except ValueError:
            first = ""
        binary = Path(first).name
        if binary in {"git", "gh"}:
            family = "version_control"
        elif binary in {"rg", "grep", "find", "fd", "sed", "awk", "head", "tail"}:
            family = "inspect_or_search"
        elif binary in {
            "python",
            "python3",
            "uv",
            "pip",
            "pip3",
            "npm",
            "npx",
            "cargo",
            "go",
        }:
            family = "language_or_package"
        elif binary in {"ls", "pwd", "wc", "stat", "file", "du", "df"}:
            family = "filesystem_inspection"
        elif not binary:
            family = "unknown"
    return family, _digest(joined)


def _distribution(values: list[int]) -> dict[str, int | float | None]:
    ordered = sorted(values)
    if not ordered:
        return {
            "n": 0,
            "total": 0,
            "median": None,
            "p75": None,
            "p90": None,
            "p95": None,
            "max": None,
        }
    return {
        "n": len(ordered),
        "total": sum(ordered),
        "median": round(median(ordered), 1),
        "p75": _nearest_rank(ordered, 75),
        "p90": _nearest_rank(ordered, 90),
        "p95": _nearest_rank(ordered, 95),
        "max": ordered[-1],
    }


def _nearest_rank(ordered: list[int], percentile: int) -> int:
    return ordered[max(0, math.ceil(percentile / 100 * len(ordered)) - 1)]


def _rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator * 100, 1) if denominator else None


def _round_percent(value: float) -> float:
    return round(value * 100, 1)


def _percent_value(values: list[float]) -> float | None:
    return round(median(values) * 100, 1) if values else None


def _dist_text(distribution: dict[str, Any]) -> str:
    if not distribution["n"]:
        return "n/a (n=0)"
    return (
        f"median {_duration_text(distribution['median'])}; "
        f"p90 {_duration_text(distribution['p90'])}; "
        f"p95 {_duration_text(distribution['p95'])}; "
        f"max {_duration_text(distribution['max'])} "
        f"(n={distribution['n']:,})"
    )


def _counts_text(counts: dict[str, int]) -> str:
    return ", ".join(f"{key}={value:,}" for key, value in counts.items()) or "none"


def _display(value: Any) -> str:
    return "n/a" if value is None else f"{value:,}"


def _duration_text(milliseconds: int | float) -> str:
    seconds = milliseconds / 1000
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes = seconds / 60
    if minutes < 60:
        return f"{minutes:.1f}m"
    return f"{minutes / 60:.1f}h"
