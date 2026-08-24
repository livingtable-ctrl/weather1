# Batch 39: Docs & backlog accuracy

## Context

Repo: weather1. Written 2026-08-23 against master `f4291771` — re-verify before starting. Source: `audit/POST_MERGE_REVIEW.md`. Files owned: `LIVE_TRADING_RUNBOOK.md`, `README.md`, `docs/grade_audit/outputs/paper.py.md`, `backlog.txt` (+ regenerated `BACKLOG_OPEN.md`), `paths.py`, `restore_window.ps1`. Parallel-safe with 33-38 (backlog.txt append-contention excepted — expect keep-both conflicts). Cheapest batch; LOW-tier ceremony throughout, but a runbook safety-procedure line is still a real safety artifact — re-verify every claim against code before writing.

## Items

### 1. L-16 [LOW, skeptic-corrected]: runbook Part 5 names the wrong lock file — 3 occurrences

`LIVE_TRADING_RUNBOOK.md:269, 281, 282`: `data/cron.lock` → real path `data/.cron.lock` (`paths.py:57`; corroborated by `docs/PRIORITY-CHECKLIST.md:71` and the on-disk `.cron.lock.mutex`). Skeptic corrections to fold into the text while fixing: `del` on the wrong name prints "Could Not Find" (visible, but reads as "no stale lock" — a false-negative diagnosis), and the runbook's own claimed non-self-heal case (PID reused by a different process) actually DOES self-heal via the create_time check — the only genuinely stuck case is PID-alive-plus-AccessDenied, capped by the 24h backstop. Rewrite the paragraph to match the real self-heal behavior, not just the filename.

### 2. M-24a [MEDIUM]: runbook Part 2's gate verification can never print its documented output

`LIVE_TRADING_RUNBOOK.md:120-129`: the bare `python -c` snippet has no `load_dotenv()`, so `KALSHI_ENV` reads "demo" and the check always prints BLOCKED — the documented `Expected: Gate: PASS` is unreachable, inviting operators to export vars in the shell to force it. Part 4's snippet does call `load_dotenv()` — copy that pattern into Part 2.

### 3. M-24b [MEDIUM]: README documents a nonexistent `main.py order` command

`README.md:95` → the real dispatcher is `buy`/`sell` (`main.py:11148`). The only doc/dispatch mismatch found across all three docs vs 74 commands (COMMANDS.md and the runbook are clean) — same defect class batch-05 fixed for `override set/clear`.

### 4. Backlog corrections [LOW — verify each against code before editing, then regenerate]

(a) `BACKLOG_OPEN.md` L24116's source entry: the taker-fee-only-on-wins item is FIXED at `order_executor.py:1177-1190` (`7dbd7ee3`) — add the Resolution section; do NOT touch its genuinely-open sibling L26177 (entry-side fee on early-exited taker positions).
(b) AUD-0047 (`backlog.txt:23259`): fixed by `0d601705` (`settlement_monitor.py:720-737` warns with an AUD-0047 comment) — add Resolution.
(c) L23899 (metar docstring caller list): fixed by `2a0f8e09`, verified — close it.
(d) File the NEVER-FILED mos.py UTC/city-local residual as its own entry (full detail in `audit/POST_MERGE_REVIEW.md` M-18c; batch 36 owns the code fix — coordinate wording, whoever lands second resolves).
(e) `backlog.txt:26464`'s follow-up cites `cron.py:1370`; real site is `cron.py:1829` — correct the citation.
(f) Append the fresh-host fail-open note to the T-ticker entry at `backlog.txt:~4-70` if batch 37 hasn't already (check first).
After all edits: `python backlog_index.py`, verify `BACKLOG_OPEN.md`.

### 5. L-4(docs) [LOW]: `docs/grade_audit/outputs/paper.py.md:340` documents `spread_kelly_multiplier()` — removed by batch-26 (`3b854726`), including its claimed "8 tests". Delete/annotate the section.

### 6. Cleanup [LOW]
(a) `restore_window.ps1` is orphaned — its only caller `run_and_sleep.bat` was deleted by batch-30. Confirm zero non-graphify references (head_limit:0), then delete (user-confirm first per repo norms on deletions).
(b) `paths.py:59` `PEAK_BALANCE_PATH` has zero importers (AST-verified in the audit) — delete the constant or add the intended consumer reference as a comment; check `git log -S PEAK_BALANCE_PATH` for intent first.

### 7. Commit the audit trail [required]

Ensure `audit/POST_MERGE_REVIEW.md`, `audit/POST_MERGE_REVIEW_COVERAGE.md`, `audit/handoff_prompts/batches/INDEX-POSTMERGE.md`, and `batch-31.md`..`batch-40.md` are committed (they may already be, if the user committed before batches started — check; this item exists so the trail can't stay uncommitted indefinitely).

## Process

LOW-tier: steps 11-12 downgrade applies (self-review + 1 review agent) — but every runbook/README claim you write must be re-verified against the current code first (a stale safety procedure is a HIGH finding; that's how these items were found). backlog.txt edits: verify entries by DISTINCTIVE PHRASING, not line numbers (citations go stale — 5x confirmed pattern). No production code changes in this batch beyond deletions in item 6. Scoped tests: none needed unless item 6 deletions surface references (then the specific file). Lint via the real pre-commit interpreter (markdown untouched by hooks, but backlog_index/paths changes are). Confirm before commit. Full workflow: `memory/feedback_implementation_workflow.md`.
