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
