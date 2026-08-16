# Codex Protocol Log Analyzer

Parse Codex protocol JSONL once and inspect it through either a Python library or a
small command-line report.

> **Development status: EXP.** The current contract is an evidence-led first slice.
> It supports observed records, preserves unknown payloads, and may change as real
> captures expose better boundaries.

## Supported inputs

- `codex exec --json` events such as `thread.started`, `turn.completed`, and `item.*`.
- Codex app-server lifecycle notifications such as `turn/started`, `item/completed`,
  and `thread/status/changed`.
- Codex persisted rollout records with `{timestamp, type, payload}` envelopes.
- Unrecognized JSON object shapes, retained as `unknown` events rather than discarded.

The two protocol families are normalized into one small event contract but counted
separately. Malformed lines become diagnostics, so one damaged record does not hide the
rest of a capture.

## Quick start

```bash
uv sync
uv run codex-log-analyze capture.jsonl
uv run codex-log-analyze capture.jsonl --format json
uv run codex-log-analyze test_log_sources/*.jsonl \
  --unrecognized-out artifacts/unrecognized-events.jsonl
uv run codex-log-stats test_log_sources/*.jsonl
uv run codex-log-stats test_log_sources/*.jsonl --format json
codex exec --json "inspect this repository" | uv run codex-log-analyze -
```

Use `--strict` when malformed input should produce exit status 2 after the report is
printed.

```python
from codex_protocol_log_analyzer import (
    analyze_file,
    analyze_rollout_files,
    parse_protocol_line,
)

event = parse_protocol_line('{"type":"turn.started"}')
report = analyze_file("capture.jsonl")
statistics = analyze_rollout_files(["rollout-1.jsonl", "rollout-2.jsonl"])

print(event.family)
print(report.event_names)
print(statistics.must_have_basic_stats["turns"])
```

## Current analysis

Reports include detected protocol families, event and item-type counts, statuses,
token-usage totals, thread and turn identities, malformed-line diagnostics, and item
IDs that were started but had no terminal event before the capture ended.

`codex-log-stats` builds separate session, turn, tool-request, and executed-operation
ledgers over persisted rollout files. It reports deterministic human statistics while
omitting prompts, responses, commands, output, paths, searches, and URLs. Token usage is
derived from cumulative per-session snapshots rather than summing snapshot records.

Multiple paths are analyzed as one streaming corpus. `--unrecognized-out` writes every
event outside the analyzer's explicit vocabulary as JSONL, including its raw payload,
for the next evidence-led parser iteration.

Open items are observations about the capture boundary, not claims that Codex left work
running. Unknown records are preserved because Codex can add notification and item
variants beyond the fields used by this initial analyzer.

Official format references:

- [Codex non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode#make-output-machine-readable)
- [Codex app-server events](https://learn.chatgpt.com/docs/app-server#events)

Product direction and evidence:

- [Human analytics priorities](docs/HUMAN_ANALYTICS_PRIORITIES.md)
- [Observed rollout event inventory](docs/evidence/2026-08-16-observed-codex-rollout-event-inventory.md)
- [Preliminary statistical report](docs/evidence/2026-08-16-preliminary-statistical-report.md)

## Development

```bash
uv run ruff format --check .
uv run ruff check .
uv run pytest
uv build
```
