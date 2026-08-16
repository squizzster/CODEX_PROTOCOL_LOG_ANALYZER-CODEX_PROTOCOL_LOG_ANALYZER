# Human analytics priorities

**Decision status:** first deterministic statistical slice implemented

**Audience:** the person whose Codex history is being analyzed

**Evidence:** [observed rollout event inventory](evidence/2026-08-16-observed-codex-rollout-event-inventory.md)

The analyzer is not for protocol experts who already understand the event stream. It
should help a person answer:

1. What did I accomplish?
2. Where did Codex help me?
3. How did Codex work?
4. What slowed the work down?
5. What was unusual or memorable?

This ranking synthesizes three independent reviews: human interest, statistical rigor,
and skeptical editorial value. Event counts establish coverage; joined domain ledgers
produce human facts.

## Ranked top 20

| Rank | Human-facing insight | Definition and guardrail |
|---:|---|---|
| 1 | What you got done | Present completed turns as recognizable task/outcome summaries joined from the opening request and final response. Say “completed turns,” not “successful goals.” |
| 2 | Your busiest projects | Show completed work, active time, files changed, and tool activity by normalized workspace or repository. Keep full paths internally to avoid basename collisions. |
| 3 | Files Codex worked on | Count distinct files touched, most frequently revisited files, and projects with the widest change footprint. Display workspace-relative paths by default. |
| 4 | Your coding footprint | Count files created, updated, moved, and deleted. Lines changed are secondary because volume is not value and later patches can undo earlier work. |
| 5 | Typical turnaround | Report median and p90 completed-turn duration, sample size, quickest wins, and longest work. This is Codex elapsed work, not human time saved. |
| 6 | Finished, interrupted, or left open | Reconcile unique started turns against completed, interrupted, and missing terminal events. Do not call this an objective success rate; an open turn may reflect a capture boundary. |
| 7 | How quickly Codex responded | Report median and p90 time-to-first-token plus slow outliers. Distinguish model TTFT from the first user-visible message. |
| 8 | Did Codex verify its work? | Classify test, lint, format, type-check, and build commands. Show the share of coding turns with verification and whether the final verification command passed. Label command classification as inferred. |
| 9 | Recovery after a stumble | Count turns containing an unsuccessful command that later completed. This is more useful than a raw command-error rate, but completion does not prove that a specific failure was fixed. |
| 10 | How Codex worked for you | Group deduplicated operations into friendly capabilities: shell inspection, editing, testing, research, external apps, image work, and collaboration. Do not expose protocol names as the primary labels. |
| 11 | The biggest pieces of work | Highlight turns by duration, files touched, operations, and tokens. Show each dimension separately rather than hiding judgment inside a composite complexity score. |
| 12 | Autonomy per request | Report hands-on turn rate, median/p90 operations per turn, and action-heavy requests. Tool-free conversational turns are not inferior. |
| 13 | Where commands got sticky | Group terminal commands by purpose and show completion, non-zero exits, slow operations, and repeated attempts. A non-zero probe or failing test is not automatically an agent failure. |
| 14 | Your working rhythm | Show active days, busiest day, preferred working hours, longest streak, and work distribution using the recorded timezone where available. Do not count gaps between events as active work. |
| 15 | When Codex brought in a team | Show turns using sub-agents, distinct agent threads, interactions, and collaboration tool mix. The observed events do not support a trustworthy universal sub-agent success rate. |
| 16 | Research moments | Show turns using web research, searches versus opened pages, result counts, and privacy-safe topic or domain summaries. Search results do not prove pages were read or accepted as evidence. |
| 17 | Goals pursued | For threads using goals, show goals created, completed, or left active, with elapsed time and tokens. Do not extrapolate goal completion to ordinary turns. |
| 18 | Token efficiency | Show tokens per completed turn, input/output/reasoning composition, and prompt-cache reuse. Tokens are not cost unless historical model pricing is supplied separately. |
| 19 | Context-marathon moments | Deduplicate compaction representations, then report compacted conversations, compactions per 100 turns, turns between compactions, context-pressure thresholds, and outcomes after compaction. Compaction is not confusion. |
| 20 | Interesting rarities | Surface image/audio requests, MCP or external-app use, unusual tools, rare workflows, and personalized “you did this only once” facts. Prefer memorable facts over meaningless percentages for rare events. |

Model and reasoning-effort comparisons remain useful filters or drill-downs. They are
descriptive rather than causal because different models and effort settings are used
for different kinds of work.

## Audit layer, not headline analytics

Retain these for provenance, joins, integrity checks, and technical drill-downs:

- Raw counts for the 28 observed event names.
- Session, thread, turn, item, call, process, event, and window IDs.
- CLI version, hashes, provider, originator, source, and history mode.
- Raw world-state, settings, model, permission, sandbox, and approval snapshots.
- Request/output pairing, duplicate IDs, orphaned outputs, and open lifecycles.
- Timestamp ordering and stored-duration consistency.
- Malformed, unknown, and structurally unmatched records.
- Raw rate-limit and encrypted-reasoning records.
- Raw prompts, paths, commands, tool outputs, stdout, and stderr.

These fields make the human facts defensible. They are not themselves the story.

## Metrics to reject

- “Time saved” inferred from Codex elapsed duration.
- “Objective success rate” inferred from completed turns.
- Raw event or tool-call counts presented as productivity.
- Lines changed presented as value delivered.
- Reasoning-item count presented as model thoughts.
- Non-zero command exits presented as Codex failures.
- Compaction count presented as confusion or poor quality.
- Prompt length presented as sophistication or engagement.
- Estimated monetary savings without historical model and billing evidence.
- Any opaque composite productivity score.

## Required analysis boundary

Build three deduplicated ledgers before producing human statistics:

```text
sessions → turns → operations
```

The same command, patch, message, tool call, or compaction can appear in response,
event-stream, specialized completion, and canonical completed-item records. The
operation ledger must choose one authoritative representation and retain the others as
provenance rather than counting each projection as separate work.

### Token accounting warning

`event_msg.token_count` is a snapshot stream, not a safely additive event stream. In
the six-file evidence corpus, repeated cumulative totals exist and at least one session
contains a cumulative counter decrease. Summing every `last_token_usage` snapshot can
therefore overcount.

For human analytics:

1. Partition token records by session and counter epoch.
2. Derive positive component-wise deltas from `info.total_token_usage`.
3. Ignore repeated zero-delta snapshots.
4. Start a new epoch when cumulative total tokens decrease, falling back to the
   input/output counters when a total is absent.
5. Attach each delta to the active turn.
6. Reconcile per-turn totals back to each session/epoch total.

Only after that reconciliation should the product display token totals, per-turn token
distributions, cache reuse, or context pressure.

## First-screen recommendation

The initial human-facing view should be small:

1. What you got done.
2. Your busiest projects.
3. Files Codex worked on.
4. Typical turnaround.
5. Finished, interrupted, or open.

Secondary sections can then explain how Codex worked, friction and recovery, working
rhythm, collaboration, research, efficiency, and memorable facts.
