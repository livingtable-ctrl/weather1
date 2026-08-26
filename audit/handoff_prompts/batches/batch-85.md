# Batch 85: order_executor — a cap that isn't one, and a dataset nothing reads

## Context

Repo: weather1. Written 2026-08-26 against master `0c332140` — **re-verify current before starting**. Live trading dormant.

**Files owned: `order_executor.py`, `tests/test_trade_improvements.py`.** Both items live in the same file, which is the only reason they are batched together; they are otherwise unrelated.

## ⚠ REVIEW FINDINGS 2026-08-26 — read before anything else

This file was reviewed after being written. Three corrections; the third changes the work.

**1. `_reprice_or_cancel_pending_orders` is at `order_executor.py:2125`, not `:779`.** The `:779` in item 2 was inherited from the backlog entry's "as of 2026-08-24" citation and is stale by ~1350 lines. Re-locate by symbol.

**2. The gate itself is at `order_executor.py:4367-4368`** — `MAX_CONCURRENT_POSITIONS = int(os.getenv("MAX_CONCURRENT_POSITIONS", "20"))` then `if len(_open_trades_list) >= MAX_CONCURRENT_POSITIONS:`, a single pre-loop check. The item's description is accurate; it just never gave the location.

**3. Fixing item 1 breaks THREE tests, not one — and one of them is load-bearing.** Batch-80 rebuilt `TestMaxConcurrentPositions` into a four-test boundary bracket:

| Test | Open | Asserts | After a per-placement cap |
|---|---|---|---|
| `test_no_trades_placed_when_at_cap` | 20 | `== 0` | still 0 |
| `test_the_spend_cap_counts_each_placed_trade_s_cost` | — | `== 4` | re-derive |
| **`test_one_below_the_cap_still_places`** | **19** | `== 5` | **would place 1** |
| `test_trades_placed_below_cap` | 18 | `== 5` | would place 2 |

The item's note names only the last one. **`test_one_below_the_cap_still_places` exists specifically to pin the cap's VALUE**, and its docstring says why:

> *"With probes only at 18 and 20, the value 19 is indistinguishable from 20 for a `>=` gate: 18 >= 19 is False and 20 >= 19 is True, so mutating the cap to 19 left BOTH other tests green — the pair bracketed the cap to {19, 20}, not to 20."* (opus review M-4)

So the requirement is not "update three numbers". It is: **preserve the bracketing property under the new semantics.** After the change, a per-placement cap makes total-after-placement the invariant, so the probes must still distinguish a cap of 20 from 19 and 21. Design the new probe set deliberately and mutation-test the cap to 19 and 21, not just to something absurd — otherwise this change silently destroys the very property batch-80 added.

### 1. [LOW] `MAX_CONCURRENT_POSITIONS` is a per-cycle entry gate, so one cycle can exceed it

> `MAX_CONCURRENT_POSITIONS IS A PER-CYCLE ENTRY GATE, SO ONE CYCLE CAN OPEN MORE POSITIONS THAN THE CAP ALLOWS`

Surfaced by batch-80 while making `TestMaxConcurrentPositions` actually exercise the cap. It is checked **once before the placement loop**, not per placement: below the cap, everything that qualifies is placed. With 18 open it places 5 and ends at 23.

Paper trading is dormant and the overshoot is bounded by the spend and per-date caps, hence LOW. But it is a real gap between what the cap is documented to do and what it does.

**Note the test coupling, and do not break it.** `test_trades_placed_below_cap` currently asserts `== 5`, pinned to today's real behaviour. When this lands, that assertion becomes `== 2` — which is what the batch-62 entry originally expected the code to already do. Update it as part of this change, and mutation-test that it fails for the right reason.

### 2. [LOW] Queue-position data exists but nothing reads it back

> `Queue-position data now exists (execution_log.queue_positions) but nothing reads it back into a decision`

Data is being captured as a forward guard; no decision logic consumes it. Related but unrelated code to read first: `_reprice_or_cancel_pending_orders` (`order_executor.py:779` as of 2026-08-24) is the **existing** price-movement-triggered reprice-or-cancel logic and is *not* this item — the entry names it so you do not confuse the two.

**`AskUserQuestion` before writing anything.** This is a "what should consume it" design question, not a fix. A plausible-looking consumer wired in without a decision is worse than the current honest gap. Ask what queue position should change — reprice aggressiveness, cancel timing, or nothing yet.


## Process — follow the 29-step implementation workflow

Read `C:\Users\thesa\.claude\projects\C--Users-thesa-claude-kalshi\memory\feedback_implementation_workflow.md` and follow it.

(1) Re-verify every claim below against live code first — these were measured 2026-08-26 and the repo moved fast that day. (3) `AskUserQuestion` for any item marked as needing a decision. (7) Mutation-test via the **Edit** tool, never a string-replace script — a scripted revert has left a silent third state in this repo before. Pair every absence-assertion with a positive control. (8) Scoped tests only — **never the bare full suite**. This file originally named none; use:

> `tests/test_trade_improvements.py` (the four cap tests), `tests/test_queue_position_instrumentation.py` (item 2's dedicated suite), `tests/test_execution_log.py` (the `queue_positions` table, created at `execution_log.py:180`), `tests/test_trading_gates.py`, `tests/test_live_execution.py`, `tests/test_cron_integration.py`.
>
> `_auto_place_trades` is referenced in ~20 test files, so do **not** expand to all of them — that would be over half the suite. Instead, `grep -rln "<symbol>" tests/*.py` for the specific symbols you actually change and add only what that returns. (9) Lint via the real pre-commit hook, not the repo `.venv`'s mypy; the versions disagree. (11) Independent opus review at `effort: high`. (13) Address every finding including LOW. (14) Memory before commit. (15) Explicit user confirmation before commit/push. (16) `git fetch` + rebase immediately before push. (19) `python backlog_index.py`.

**Two standing hazards.** Scripts run outside pytest bypass conftest's real-`data/`-write blocker and its default-deny network guard — redirect `safe_io.project_root()` or the specific `paths.py` constant before running any scratch script. And do not run `git restore .` or `git checkout -- data/`.
