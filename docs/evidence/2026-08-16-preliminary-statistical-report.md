# Preliminary statistical report

**Evidence date:** 2026-08-16

**Source:** six copied rollout JSONL files, 75,984 records

**Method:** deterministic aggregate analysis; no AI interpretation

**Privacy:** prompts, responses, commands, output, paths, searches, and URLs omitted

This is the first implemented statistical view of the pressure-test corpus. The
machine-readable counterpart is generated locally at
`artifacts/preliminary-statistics.json`.

## MUST HAVE BASIC STATS

1. **Sessions and coverage:** 6 sessions; 75,984 records; 0 malformed.
2. **Turn calls:** 281 started; 262 completed; 19 aborted; 0 open.
3. **Completed-turn duration:** median 1.9m; p90 39.9m; p95 1.2h; max 8.1h (n=262).
4. **Time to first token:** median 10.0s; p90 31.3s; p95 56.8s; max 2.6m (n=262).
5. **Tokens:** 2,002,696,493 total; 1,995,376,171 input; 7,320,322 output;
   median 652,781 per turn (n=281).
6. **Context use:** 18.3% median latest session fill; 97.7% observed high-water mark.
7. **Commands executed:** 3,052; 2,839 zero exit; 213 nonzero exit. Deterministic mix:
   inspect/search 1,163; other 835; language/package 438; verification 347; version
   control 169; filesystem inspection 99; unknown 1.
8. **Model tool requests:** 14,282; all 14,282 paired with output records. Mix: exec
   11,311; wait 2,294; wait-agent 357; spawn-agent 95; follow-up 80; send-message 65;
   list-agents 48; exec-command 23; interrupt-agent 8; apply-patch 1.
9. **Files changed:** 1,914 operations; 985 distinct paths; 2,533 change occurrences.
10. **Web activity:** 17 operations; 17 queries; 270 result records.
11. **Collaboration:** 257 completed collaboration operations; 54 agent threads started.
12. **Compactions:** 98 context-window compactions.
13. **Workspaces and models:** 4 workspaces; gpt-5.6-sol 278 turns, gpt-5.4 2,
    gpt-5.6-terra 1.

## RECOMMENDED INSIGHT STATS

1. **Typical turn anatomy:** median 0 commands, 4 tool requests, and 0 changed files.
2. **Hands-on turn rate:** 75.1% of turns used a tool request, command, file operation,
   web operation, or collaboration operation.
3. **Recovery after a nonzero command:** 20 of 28 such turns later completed (71.4%).
4. **Command reliability:** 93.0% of commands with a known exit code exited zero.
5. **Exact command repetition:** 26.6% of command executions repeated a command seen
   elsewhere in the corpus.
6. **Cached-input share:** 98.0% of input tokens were cached.
7. **Reasoning-output share:** 30.6% of output tokens were reasoning tokens.
8. **Edit then verify:** 24 of 120 edited turns had a later deterministically classified
   verification command (20.0%).
9. **Web follow-through:** 6 of 7 web turns had later command or file work (85.7%).
10. **File revisits:** 39.8% of changed paths appeared in at least two file-change
    operations.
11. **Project concentration:** the busiest workspace accounted for 77.2% of
    workspace-tagged turns.
12. **Working rhythm:** the busiest local start hour was 10:00, with 30 turns (n=281).
13. **Goal tracking:** 11 updates; 7 active and 4 paused.

## Trust notes

The ledgers count model tool requests separately from executed operations. Old and new
protocol generations are unioned within each operation category, while mirrored
projections are not added together. The 98 detailed `compacted` records are counted
once; their legacy and canonical detail projections are provenance.

Token totals are positive deltas of cumulative per-session snapshots. Repeated
zero-delta snapshots are ignored and a new epoch begins on a cumulative total decrease.
The corpus contains 258 repeated snapshots and 7 epochs across 6 sessions. Cached input
is a subset of input; reasoning output is a subset of output.

Percentiles use nearest rank; an even-sample median uses the midpoint. “Completed” means
a terminal record exists, not that the objective succeeded. A completed turn after a
nonzero command is a recovery sequence, not proof the error caused or was fixed by the
remaining work. Search results do not prove a page was read. Elapsed duration is not
active human time or time saved.
