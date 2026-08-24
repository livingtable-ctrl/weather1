# Batch 31: Live-order crash-recovery & exit serialization (CRITICAL — do first, gates live enablement)

## Context

Repo: weather1 (Kalshi weather-trading bot). Written 2026-08-23 against master `f4291771` — **re-verify current before starting** (`git fetch` + `git log origin/master`). Source: `audit/POST_MERGE_REVIEW.md` (post-merge audit; finding IDs below reference it). Live trading is dormant (`LIVE_TRADING_ENABLED` unset) so nothing here is actively bleeding — but every item sits on the real live-order path once enabled, and CR-1 must be fixed before any live enablement.

Files owned by this batch: `order_executor.py`, `execution_log.py`, `tests/` (new tests). Do not touch other batches' files (see `INDEX-POSTMERGE.md`).

## Items

### 1. CR-1 [CRITICAL | CONFIRMED by adversarial verification with executed repro]: batch-22×batch-23 collision — pre-logged idempotency key ≠ wire key, so crash recovery marks REAL live orders 'failed'

**Files:** `order_executor.py:1347-1349` vs `:1378` (`_replace_live_order`); `order_executor.py:2084-2086` vs `:2133` (`_exit_live_position`). Batches `7dbd7ee3` × `f704c581`.

Batch-23 scoped `place_order`'s cycle to `f"{cycle}:replace:{replaces_order_id}"` / `f"{cycle}:exit:{log_id}"` but left the pre-log `compute_client_order_id(...)` calls on the bare `cycle`. Verified twice by executing the real function: pre-logged cid ≠ the cid `place_order` derives internally (control `_place_live_order`: equal). The exit case is structural — the wire key needs `log_id`, which doesn't exist until after `log_order()` commits.

**Failure path (traced end-to-end):** crash in the pre-log→`log_order_result` window — and `cron.py:3108-3156`'s watchdog `os._exit(1)`s into exactly this window by design — then recovery: pending→sent (wrong cid preserved, `:553-558`) → `claim_sent_order` → unknown → `_find_order_by_client_id(wrong_cid)` completes all 3 passes, confirmed negative, `uncertain=False` → `:844-849` writes `'failed'`.
- Replace: real live BUY becomes an **untracked live position** (no protective exits, no settlement accounting, no `add_live_loss`); after a 12h forecast-cycle rollover the ticker is re-orderable (duplicate BUY). The untracked-position harm is immediate and unmitigated.
- Exit: real protective SELL marked 'failed'; position row keeps `settled_at=NULL` forever → the exit scanner places a **fresh real SELL every cycle** against an already-sold position; permanently consumes a `max_open_positions` slot.

**Scope corrections from verification (don't over-fix):** the `OrderStatusUnknownError` path is NOT affected — its handlers overwrite `response` with the correct wire cid (`:1382-1387`, `:2139-2144`); `main.py`'s own pre-log sites (`cmd_order`, `_quick_paper_buy`) are already correct (they pass matching `time_in_force`-scoped keys). Corroboration that this was an oversight: `_amend_live_order:1485-1501`'s comment lists exactly these sites as the cid-storing ones.

**Fix direction:** make the pre-logged cid equal the wire cid at both sites. For replace: pass the scoped cycle (`f"{cycle}:replace:{replaces_order_id}"`) plus the same `time_in_force` into the pre-log `compute_client_order_id`. For exit: the scoped cycle needs `log_id` — either (a) restructure to log_order first, then compute the cid from the returned `log_id` and update the row's response before calling `place_order` with an explicitly-passed `client_order_id` (check whether `place_order` accepts one; if not, add the parameter to `kalshi_client.place_order` — coordinate: that file is not owned by any other new batch), or (b) derive the exit key from something that exists pre-log (e.g. the position row id) and pass the SAME string to both. Whatever the design, the invariant to enforce and test: **pre-logged response.client_order_id == the id that reaches the wire, byte-identical, on every live path.**

**Tests (the current gap is total):** `tests/test_idempotency.py` never asserts pre-log==wire; the batch-22 F7 test pattern (`test_trading_gates.py:1290-1355`, `:1435-1492`) covers only `cmd_order`/`_quick_paper_buy`. Add the equivalent for `_replace_live_order`, `_exit_live_position`, and (defensively) micro-live.

### 2. M-4 [MEDIUM]: add an atomic position-row claim in `_exit_live_position` — closes the concurrent double-exit AND CR-1's exit half AND M-2's residual race

**Files:** `order_executor.py:2108-2133`, `execution_log.py`. Batch `f704c581`.

Batch-23's per-attempt exit key removed the only (accidental, price-equality-dependent) server-side dedup against cron's and watch's exit scanners both selling the same position — verified: both derive identical `cycle` internally, run unserialized (AUD-0013-documented), and `LivePositionStore.exit` has no row claim; `record_live_exit_fill`'s guard fires only after the second SELL already executed. The hazard pre-existed batch-23 (report as defense-in-depth regression, not a batch-introduced bug).

**Fix direction:** an atomic compare-and-set claim on the position row (mirror `claim_unknown_row_for_recovery`'s pattern, `execution_log.py:320`) before `place_order` in `_exit_live_position`; loser skips the sell entirely. Design it together with item 1's exit-key fix — one coherent change.

### 3. M-2 [MEDIUM | skeptic-corrected scope]: `record_live_settlement` has no `settled_at IS NULL` guard

**Files:** `execution_log.py:918-933`; caller `order_executor.py:1191-1192`.

Unconditional `UPDATE orders SET settled_at=?, outcome_yes=?, pnl=? WHERE id=?`, followed by unconditional `add_live_loss(-pnl)`. Skeptic correction: the originally-claimed cron-vs-watch race is unreachable (cron never calls `_poll_pending_orders`; exit IOC fills are impossible on finalized markets) — but narrower races survive (cron's `_settle_recovered_exit_order` vs watch's stale `get_filled_unsettled_live_orders()` snapshot; two concurrent watch processes), and the danger direction is real: a **winning** position credited twice makes the live daily-loss brake looser than reality; the overwrite also silently replaces an early-exit's realized pnl (tax CSV / `get_live_pnl_summary` / settlement-streak corruption).

**Fix direction:** guard the UPDATE on `settled_at IS NULL` like every sibling (`:1013`, `:1028`, `:1283`), return whether the write landed, and make the caller skip `add_live_loss` on a lost race. Also fix the stale docstring at `order_executor.py:891-899` ("get_positions() is a single unpaginated GET" — batch-23 paginated it) and the batch-23 comment at `kalshi_client.py:775-788` claiming AUD-0025's consumer doesn't exist yet (L-12; trivial, same functions).

### 4. M-23a [MEDIUM test-gap, mutation-verified]: no test kills removing the `settled_at IS NULL` guard from `record_live_early_exit`'s unconditional branch

Mutation testing removed the guard at `execution_log.py:1013` and **281 tests passed** across `test_execution_log.py`, `test_dedup.py`, `test_live_execution.py`, `test_batch01_live_position_visibility.py`. Add a direct test: settle a row, call `record_live_early_exit` again, assert the second call reports the lost race and the row is unchanged. Cover item 3's new guard with the same pattern.

### 5. L-10 [LOW, same file — sweep while here]: three `order_executor.py` hardening nits

(a) `_finalize_cancel`'s exception fallback (`:975-988`) calls `log_order_result(row_id, status="canceled")` bare — `fill_quantity` and `response` (carrying `order_id`) are non-COALESCE columns and get nulled, so a partially-filled position can go fully untracked. Preserve them (pass through the previously-recorded values, or make those columns COALESCE in `log_order_result`).
(b) `:2541` bare `config["max_trade_dollars"]` subscript while steps 1/1b/2 defensively `.get()` the same hand-editable dict → `.get` with a conservative default (refuse, not unlimited).
(c) micro-live `:4407-4410`: `.get("daily_loss_limit", 0.0)` + `if _micro_daily_limit > 0` fails OPEN — opposite of `_place_live_order`'s `float("inf")` fail-closed. Align to fail-closed. (Skeptic context: micro-live is hard-disabled by source literal `utils.py:410`, so this is LOW; do NOT attempt the full micro-live gate re-plumb here — `utils.py:410`'s own comment already scopes that to a future re-implementation.)

## Process — follow the 29-step implementation workflow (`feedback-implementation-workflow`) exactly, in order

This batch is the money path. Full ceremony, no LOW-tier downgrade: re-verify every claim against live code first (the audit's line numbers can drift); AskUserQuestion for item 1's exit-key design choice (a) vs (b) with a genuine recommendation; mutation-test every new test via Edit-revert; scoped pytest only (test_idempotency, test_live_execution, test_execution_log, test_trading_gates, test_dedup — **never the full suite**); lint via the real pre-commit interpreter; independent opus review at effort=high (this repo's pattern: expect the review to find real issues in your fixes — round 2 reviews the fixes); confirm before commit; backlog.txt entries + `python backlog_index.py`; graphify-out refresh scoped to changed files if it exists. Full text: `C:\Users\thesa\.claude\projects\C--Users-thesa-claude-kalshi\memory\feedback_implementation_workflow.md`.
