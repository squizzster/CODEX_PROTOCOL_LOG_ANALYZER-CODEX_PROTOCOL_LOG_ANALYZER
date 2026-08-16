# Observed Codex rollout event inventory

**Evidence date:** 2026-08-16  
**Development mode:** EXP  
**Corpus:** the three largest rollout JSONL files present in `/home/dna/.codex/sessions`
when this experiment began

This is the initial working vocabulary for the analyzer. `recognized` means the current
code has an explicit normalization path for the event name. `unrecognized` means the
record parsed successfully but its semantics are not yet represented; every occurrence
was copied verbatim to the git-ignored `artifacts/unrecognized-events.jsonl` evidence
stream for later inspection.

## Result

- Source files: 3
- Source bytes: 233,105,982 bytes (223 MiB reported by `du`)
- Records read: 75,669
- Records parsed: 75,669
- Malformed records: 0
- Unique event names: 25
- Recognized occurrences: 61,594
- Unrecognized occurrences: 14,075
- Unique recognized event names: 13
- Unique unrecognized event names: 12
- Corpus runtime: 2.47 seconds
- Peak resident memory: 34,516 KiB
- Unrecognized evidence size: 109 MiB

## Working event list

| Event name | Occurrences | Current result |
|---|---:|---|
| `compacted` | 98 | unrecognized |
| `event_msg.agent_message` | 1,671 | unrecognized |
| `event_msg.context_compacted` | 73 | unrecognized |
| `event_msg.item_completed` | 9,706 | unrecognized |
| `event_msg.patch_apply_end` | 1,214 | unrecognized |
| `event_msg.sub_agent_activity` | 78 | unrecognized |
| `event_msg.task_complete` | 258 | recognized |
| `event_msg.task_started` | 276 | recognized |
| `event_msg.thread_goal_updated` | 11 | unrecognized |
| `event_msg.thread_settings_applied` | 288 | unrecognized |
| `event_msg.token_count` | 14,752 | recognized |
| `event_msg.turn_aborted` | 18 | recognized |
| `event_msg.user_message` | 417 | unrecognized |
| `event_msg.web_search_end` | 6 | unrecognized |
| `inter_agent_communication_metadata` | 308 | unrecognized |
| `response_item.agent_message` | 308 | recognized |
| `response_item.custom_tool_call` | 11,284 | recognized |
| `response_item.custom_tool_call_output` | 11,284 | recognized |
| `response_item.function_call` | 2,947 | recognized |
| `response_item.function_call_output` | 2,947 | recognized |
| `response_item.message` | 3,155 | recognized |
| `response_item.reasoning` | 13,994 | recognized |
| `session_meta` | 3 | recognized |
| `turn_context` | 368 | recognized |
| `world_state` | 205 | unrecognized |

## Event meaning glossary

Parser recognition above and semantic understanding below are separate. A record may
remain `unrecognized` in code even when its observed purpose is now clear enough to
guide the next implementation. Descriptions apply to this corpus and stay deliberately
short.

| Event name | Meaning | Basis |
|---|---|---|
| `compacted` | Persists replacement conversation history after context compaction. Window IDs and numbers link the old and new context windows; `message` and `replacement_history` carry the compacted state used for continuation. | Observed; compaction lifecycle documented |
| `event_msg.agent_message` | Event-stream copy of accumulated assistant text. `phase` distinguishes progress commentary from the final answer; `memory_citation` can associate memory evidence. | Observed; agent-message semantics documented |
| `event_msg.context_compacted` | Lightweight notification that conversation context was compacted. It carries no additional fields in this corpus; detailed replacement history appears in `compacted`. | Observed; compaction lifecycle documented |
| `event_msg.item_completed` | Terminal event for one typed work item, scoped by thread and turn with start/end times. The nested item contains the authoritative final result, status, output, or changes. | Observed; completed-item authority documented |
| `event_msg.patch_apply_end` | Legacy/specialized patch-operation completion. Records call and turn IDs, changed files, success and status, plus captured stdout and stderr. | Observed |
| `event_msg.sub_agent_activity` | Announces a sub-agent activity transition for a named agent path and thread. Observed kinds were `started` and `interacted`; `event_id` and time support ordering. | Observed; exact consumer inferred |
| `event_msg.task_complete` | Marks successful task/turn completion and records start, completion, duration, time-to-first-token, turn ID, and the last agent message. | Observed; turn completion documented |
| `event_msg.task_started` | Marks task/turn start. Captures turn ID, start time, collaboration mode, and model context-window size active for the work. | Observed; turn start documented |
| `event_msg.thread_goal_updated` | Persists the current thread goal snapshot: objective, status, thread ID, creation/update times, elapsed time, and token usage. | Observed |
| `event_msg.thread_settings_applied` | Records the effective settings applied to the thread, including model, reasoning effort, working directory, collaboration mode, personality, approvals, and permission profiles. | Observed |
| `event_msg.token_count` | Usage telemetry snapshot containing last-response usage, cumulative usage, model context-window size, and rate-limit state. The analyzer currently aggregates `last_token_usage` to avoid summing cumulative totals repeatedly. | Observed; token-usage updates documented |
| `event_msg.turn_aborted` | Marks an interrupted turn with turn ID, reason, start/end times, and duration. All 18 observed reasons were `interrupted`. | Observed; interrupted turn status documented |
| `event_msg.user_message` | Event-stream representation of user input, including message text plus image, audio, local-media, and structured text-element metadata. | Observed; user-message item documented |
| `event_msg.web_search_end` | Terminal web operation record keyed by call ID. Captures search/open-page action, query, and returned result metadata; observed actions were `search` and `open_page`. | Observed; web-search actions documented |
| `inter_agent_communication_metadata` | Metadata controlling whether an inter-agent communication triggers a turn. Every observed record had `trigger_turn: false`; no message body is stored in this record. | Observed; purpose inferred from name and field |
| `response_item.agent_message` | Persisted inter-agent message with item ID, author, recipient, and content. This is distinct from ordinary assistant-role `response_item.message` records. | Observed; routing role inferred from fields |
| `response_item.custom_tool_call` | Persisted model request to a custom tool, with item/call IDs, tool name, input, and status. It pairs with `custom_tool_call_output` through `call_id`. | Observed; tool-call lifecycle documented |
| `response_item.custom_tool_call_output` | Persisted result of a custom tool invocation. `call_id` links the output to its request; `output` carries the returned tool content. | Observed; tool-call lifecycle documented |
| `response_item.function_call` | Persisted model-issued function call with item/call IDs, function name, optional namespace, and serialized arguments. It pairs with `function_call_output`. | Observed; tool-call lifecycle documented |
| `response_item.function_call_output` | Persisted function result linked to its request by `call_id`. `output` contains the function/tool response returned to the model. | Observed; tool-call lifecycle documented |
| `response_item.message` | Canonical Responses-style conversation message. Observed roles were developer, user, and assistant; assistant messages use commentary or final-answer phases and content entries carry input/output text. | Observed; user/agent messages documented |
| `response_item.reasoning` | Persisted reasoning item containing an ID, encrypted reasoning content, and optional summary parts. It records model reasoning state without requiring plaintext reasoning. | Observed; reasoning item documented |
| `session_meta` | Rollout header identifying the session/thread and its origin. Captures timestamps, CLI version, model provider, working directory, source, context window, history mode, Git context, and base instructions. | Observed |
| `turn_context` | Snapshot of the effective context for one turn: model and effort, working roots, date/timezone, collaboration and personality settings, sandbox, approvals, permissions, and compaction hash. | Observed |
| `world_state` | Full or partial snapshot of runtime state supplied around turns. Observed state includes environments, instructions, skills, plugins, permissions, model, collaboration mode, and related host capabilities. | Observed; replay purpose inferred |

## Semantic research boundary

The corpus establishes exact local envelopes, fields, values, counts, and ordering. The
official Codex app-server documentation establishes the corresponding public thread,
turn, item, token-usage, web-search, and compaction semantics, but does not specify this
persisted rollout envelope as a stable public schema. Internal-only descriptions above
therefore remain explicitly evidence-led rather than contractual.

- [Official Codex app-server events](https://learn.chatgpt.com/docs/app-server#events)
- [Official Codex app-server item types](https://learn.chatgpt.com/docs/app-server#items)
- [Official Codex thread compaction](https://learn.chatgpt.com/docs/app-server#trigger-thread-compaction)

## Source provenance

| Source file | Bytes | SHA-256 |
|---|---:|---|
| `rollout-2026-08-03T22-32-50-019fc9c2-1f06-7b72-afd2-47a9335a5ac1.jsonl` | 113,252,197 | `a9873fce74934c99ff960c177c6c3f90fda522e0c42425e426c84fd4550152be` |
| `rollout-2026-08-11T22-53-21-019ff307-c999-7ad0-a02b-fdfc29dcfa74.jsonl` | 66,235,652 | `38b563ba6792d4eed65467af526def0f6141b8faa4477231344acd0aa94fd8d3` |
| `rollout-2026-08-13T18-32-02-019ffc65-41d5-7a82-b256-da58c6cff3fd.jsonl` | 53,618,133 | `78e83c7e36cbc347fe515462356c7c17ac9ec1f64693a98fd912de94b851b3ed` |

The copied source files and raw unrecognized-event stream are deliberately excluded
from Git because they contain local conversation history. This Markdown inventory
contains structural names, counts, sizes, and hashes only.

## Reproduction

```bash
uv run codex-log-analyze test_log_sources/*.jsonl \
  --format json \
  --unrecognized-out artifacts/unrecognized-events.jsonl \
  > artifacts/corpus-report.json
```
