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
codex exec --json "inspect this repository" | uv run codex-log-analyze -
```

Use `--strict` when malformed input should produce exit status 2 after the report is
printed.

```python
from codex_protocol_log_analyzer import analyze_file, parse_protocol_line

event = parse_protocol_line('{"type":"turn.started"}')
report = analyze_file("capture.jsonl")

print(event.family)
print(report.event_names)
```

## Current analysis

Reports include detected protocol families, event and item-type counts, statuses,
token-usage totals, thread and turn identities, malformed-line diagnostics, and item
IDs that were started but had no terminal event before the capture ended.

Multiple paths are analyzed as one streaming corpus. `--unrecognized-out` writes every
event outside the analyzer's explicit vocabulary as JSONL, including its raw payload,
for the next evidence-led parser iteration.

Open items are observations about the capture boundary, not claims that Codex left work
running. Unknown records are preserved because Codex can add notification and item
variants beyond the fields used by this initial analyzer.

Official format references:

- [Codex non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode#make-output-machine-readable)
- [Codex app-server events](https://learn.chatgpt.com/docs/app-server#events)

## Development

```bash
uv run ruff format --check .
uv run ruff check .
uv run pytest
uv build
```
