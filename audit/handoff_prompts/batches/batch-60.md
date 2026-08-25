# Batch 60: Trade-entry guards & manual-order pricing (MEDIUM)

## Context

Repo: weather1. Written 2026-08-24 against master `223dedadcfd2` — re-verify current before starting. Source: backlog.txt L138, L163, L26159, L23228 (re-verified against live code during batch-48's backlog sweep, 2026-08-24).

Files owned: `paper.py`, `main.py` (`cmd_order`, `cmd_today`'s interactive place flow, `_pick_display`). Parallel-safe with 57-59, 61-62.

**Overlap warning:** batch 58 also touches `main.py`, but only `cmd_cancel`. These are far apart in the file; whichever lands second rebases. If `git diff` after rebase shows anything unexpected in the other batch's region, stop and reconcile by hand.

**Live-trading state:** `LIVE_TRADING_ENABLED` is unset, so `cmd_order`'s live path (items 2, 4) is dormant today — but it is a genuine real-order entry point gated *only* by that flag, independent of `ENABLE_MICRO_LIVE`. Someone setting `LIVE_TRADING_ENABLED=true` to test `watch --auto --live` also arms `cmd_order`. Treat as live-money code.

## Items

### 1. `place_paper_order()`'s stale-`target_date` guard has no upper bound [L138]

**Files:** `paper.py:1082-1096` (the guard), `paper.py:414` (`STALE_TARGET_DATE_GRACE_DAYS`)

The guard rejects `_stale_days > STALE_TARGET_DATE_GRACE_DAYS` — i.e. only the **past** direction. There is no ceiling on a target_date far in the *future*, and the constant has no sibling max-days-out cross-reference.

**Consequence:** a malformed or mis-parsed ticker yielding a target_date months out books a paper trade that will not settle for months, silently occupying exposure budget and position-limit slots.

**Fix:** add a future-side bound. **Derive the ceiling from an existing config value rather than inventing a constant** — grep for the real max-days-out the scanner already honors (the analysis path has one) and reuse it, so the two can't drift. State the chosen source in the resolution.

**Sentinel check before you pick a bound:** grep the field's real consumers for their exact comparison operators first. A plausible-looking "normal range" bound has previously rejected a legitimate sentinel value in this repo.

### 2. Live `cmd_order` BUY never validates `target_date` freshness [L163]

**Files:** `main.py:5635-5665` (the `_is_live and action == "buy"` gate block)

That block adds loss/spend/open-count checks only. `grep STALE_TARGET_DATE_GRACE_DAYS main.py order_executor.py` returns **nothing** — the staleness guard from item 1 exists solely on the paper-mirror path. So the manual live-buy CLI has strictly weaker date validation than the automated paper path.

**Fix:** apply the same guard (both directions, post-item-1) on the live buy path. Do item 1 first so there is one shared helper to call rather than two hand-written copies — that duplication is exactly how the exclusion-tuple drift in batch 57 happened.

### 3. `cmd_today`'s interactive "[P] Place" books at the bid-ask MID, not the real ask [L26159]

**Files:** `main.py:3594` (`_entry_price1 = _market_prob1 if _side1 == "yes" else 1 - _market_prob1`), passed to `_ppo_today` at `:3793-3797`, printed cost at `:3804`. Sibling display path `_pick_display` at `:3487` has the identical mid-based line at `:3505`.

The repo already has the correct helper — `_side_aware_entry_price` (`main.py:1481`) — but it is used at only one site (`:1587`). This is the same defect class batch-26 fixed in the frontend's `buildPaperOrderBody`/`sideAwareEntryPrice`, still present in the CLI.

**Consequence:** a paper trade placed interactively books at a price the operator could not actually have gotten, biasing the paper corpus optimistically — and that corpus feeds the graduation gate that authorizes live trading.

**Fix:** route both `:3594` and `:3505` through `_side_aware_entry_price`. **Include `_pick_display`** — the entry anticipated it and its line has since drifted to `:3505`.

**Backfill question:** existing paper rows booked at mid are now known-optimistic. Decide explicitly whether to correct them or fix forward only, and say which in the resolution. Do not silently fix forward — that leaves a date boundary in the corpus that nothing records.

### 4. Live `cmd_order` sell closes only the oldest matching position [L23228]

**Files:** `main.py:5740` (takes `_live_open_matches[0]`), operator warning at `:5753-5760`

With multiple tracked live positions on the same ticker+side, a sell closes the oldest and warns the operator rather than letting them choose.

**Status nuance — read before deciding:** this entry's own recommendation was "no independent action recommended," because its root-cause prerequisite (exposure caps being blind to `execution_log`) was open at the time. **That prerequisite is now `[RESOLVED 2026-08-18]`.** So the reason for deferring no longer holds, and the entry deserves a fresh decision rather than inheriting its old one.

**Fix direction:** either (a) let the operator select which position to close (an index/id argument), or (b) close proportionally across matches, or (c) keep current behavior and downgrade the entry to a documented accepted-risk with the warning as the mitigation. **Surface via `AskUserQuestion`** — this is a genuine UX/semantics choice on a live-order path, not a default to pick. If the answer is (c), that is a legitimate outcome; record it as an explicit reasoned decision, not a silent skip.

## Process

Full 29-step workflow. **No LOW-tier downgrade** — items 2 and 4 are live-order paths, and item 3 feeds the graduation gate. Opus review at `effort: high`.

**Item 4 requires `AskUserQuestion` before implementation.** Items 1 and 3 have embedded decisions (bound source; backfill scope) that should be surfaced too if the answer is not obvious from the code — give both the same visibility rather than deciding one in a comment.

Tests: scope to `tests/test_paper.py`, `tests/test_config.py`, and whichever `main.py` CLI tests cover `cmd_order`/`cmd_today` — grep `tests/` for `place_paper_order`, `_ppo_today`, and `_side_aware_entry_price` before finalizing. **Never run the bare full suite.**

**Test-isolation hazard specific to this batch:** `tests/conftest.py`'s `mock_balance_1000` fixture does **not** actually isolate `paper.DATA_PATH` — it patches then `importlib.reload(paper)`, which undoes the patch, so tests using it read/write the REAL production `data/paper_trades.json`. That is backlog L24334, assigned to **batch 62**. Until 62 lands, do not use that fixture for any new test here; isolate `DATA_PATH` explicitly yourself.

Any standalone verification script gets the same isolation discipline as a real test — mock `project_root()`/`DATA_DIR` before running it, every time.

Lint via the real pre-commit hook. Update all 4 backlog resolutions, run `python backlog_index.py`, confirm before committing.
