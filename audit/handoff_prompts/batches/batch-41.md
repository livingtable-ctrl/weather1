# Batch 41: Bulk-action order-path integrity — client guards + server halves (CRITICAL — do first)

## Context

Repo: weather1 (Kalshi weather-trading bot). Written 2026-08-23 against master `aecbe5454277` — **re-verify current before starting** (`git fetch` + `git log origin/master`); this is the exact commit the source review was done against, so line cites should still be fresh, but other frontend batches from this same handoff may already be in flight. Live trading is dormant (`LIVE_TRADING_ENABLED` unset) — these are dashboard paper-order paths, not live-money paths, but the dashboard is the primary operator interface and a false "✓ Placed N orders" / "✓ Closed N positions" toast is a real operational-trust hazard regardless of live/paper.

Source: `FRONTEND_REVIEW_HANDOFF.md` (2026-08-23 frontend review of pushed `master @ aecbe5454277`, post-port: V3 now lives in `frontend/src/`), cross-referenced with `audit/POST_MERGE_REVIEW.md` (2026-08-23 whole-program post-merge audit of `f4291771`) for the server-side halves — the frontend review explicitly flags that M-9/M-10 in that audit are the server counterparts of this batch's client bugs and should be fixed together, and that M-11 compounds C-1 below. **Neither this batch's content nor the underlying line numbers have been independently re-verified this session** — re-read the actual current code at each cited location before trusting this transcription, same as any other batch.

Files owned by this batch: `frontend/src/tabs/SignalsTab.jsx`, `frontend/src/tabs/PositionsTab.jsx`, `frontend/src/useData.js`, `web_app.py` (server halves only — coordinate with batch-33 if it also touches `web_app.py`; as of writing it does not). **This batch supersedes batch-34's items #3 (M-10), #4 (M-9), and #5 (M-11)** — those items were written against the pre-port monolith (`App.jsx` at 126 KB) and the post-port `App.jsx` is now ~22 KB / ~520 lines, so batch-34's line cites for those three items point past EOF or into code that moved into `tabs/*.jsx`. Do batch-34's items #3/#4/#5 **here**, not there; batch-34's remaining items (#1, #2, #6, #7, #8) are unaffected by the port and still belong to batch-34 (superseded separately — see batch-45/batch-48 for the frontend halves of those; batch-34's pure-`web_app.py` items stay as written).

## Items

### 1. C-1 [CRITICAL]: `handleBulkApprove` places live-money-adjacent paper orders with none of the single-approve path's guards

**Files:** `frontend/src/tabs/SignalsTab.jsx` — `handleBulkApprove`, contrast with `handleAction`/`handleConfirm`.

Single approve routes through `handleAction` → a confirmation modal showing entry price, cost, and balance-after → `handleConfirm`, which inspects `d.error`, writes `placedSet` (a sessionStorage dedup set) on success, then refreshes. The Approve button is also `disabled` whenever `edge_pct <= 0`.

`handleBulkApprove` shares none of this: no confirmation modal; **no `edge_pct > 0` filter**, so a negative-edge signal the single path structurally refuses to submit goes through in a batch; its `.then()` never inspects the response body before printing `✓ Placed N orders`; it never writes to `placedSet`, so every row stays live and immediately re-submittable (a second bulk-approve click re-places the same signals).

**Fix direction:** make bulk approve a loop over the single path's logic, not a separate implementation — one confirmation modal listing every order and total cost, the same `edge_pct > 0` filter, per-response `d.error` inspection, a `placedSet` write per success, and a toast reporting `n placed / m failed` from what the responses actually said (not an unconditional count).

### 2. C-2 [CRITICAL]: `handleBulkClose` reports success it never verified

**Files:** `frontend/src/tabs/PositionsTab.jsx` — `handleBulkClose`, contrast with the single-close handler.

Single close inspects `d.error` and surfaces the server's message on failure. Bulk close resolves its `Promise.all` and unconditionally prints `✓ Closed N positions` regardless of what the responses said. If the server rejects all N, the operator is told all N closed — and because the message is immediately followed by `M.refresh()`, the positions reappearing in the table reads as refresh lag, not as the close having failed.

Note the asymmetry: this is otherwise the most careful function in the file — it deliberately filters to `p.markIsLive` before closing, specifically so a fabricated fallback price is never submitted for a position whose live quote isn't available, and says why in a comment. Only the response-handling half is missing; don't rewrite the rest of it.

**Fix direction:** count responses without an `error` field and report that number, not `N`. Switch `Promise.all` → `Promise.allSettled` so one network failure doesn't discard the other N−1 real results.

### 3. C-3 [CRITICAL]: Selection survives filtering, so the "N selected" count lies about what a bulk action will actually do

**Files:** `frontend/src/tabs/PositionsTab.jsx` (same split exists across `SignalsTab.jsx`'s two tables — check both).

`selectedIds` is tracked independently of `filter`, but `handleBulkClose` resolves the selection against `filtered`, not the full unfiltered set. Concretely: select ten positions, then apply a filter that narrows the table to two of them still visible — the selection bar still reads **"10 selected"**, but Close All only closes the two currently-filtered rows, and the toast (once C-2 above is fixed to report real counts) will say `✓ Closed 2` — leaving eight open that the operator believes they closed, because the bar told them 10 were selected and the action "succeeded."

The header select-all checkbox has the mirror bug: `selectedIds.size === filtered.length` compares an all-rows selection count against a visible-rows count, so the "select all" checkbox silently unchecks itself as soon as a filter narrows the table, with no visible cause.

**Fix direction:** prune `selectedIds` down to the currently-visible/filtered set whenever `filter` changes (a `useEffect` keyed on `filter`, or derive the effective selection as `selectedIds ∩ filteredIds` everywhere it's consumed — pick one and apply consistently to both the count display and the action's target set). Apply the same fix to `SignalsTab.jsx`'s two tables.

### 4. Audit M-9 [MEDIUM, server half of C-2]: `/api/close-position` lacks the kill-switch/TRADING_PAUSED gates and price cross-check its sibling order route has

**Files:** `web_app.py:3127-3169` (as of `f4291771` — re-locate if `aecbe545`'s diff moved it); `paper.py:1497` does no validation of its own.

Its sibling `/api/paper-order` has all three guards (kill-switch, TRADING_PAUSED, and a live-quote deviation cross-check). `ee22c44c` widened `/api/close-position`'s reachability with an operator-typed manual exit price that feeds straight into `proceeds`/`pnl`/`balance` → drawdown tier, `peak_balance`, and graduation `total_pnl` — all without checking either gate, and (per `backlog.txt:20408`, already tracked separately) without checking the price against a live quote when one exists. The missing gates are not separately tracked anywhere.

**Fix direction:** add the kill-switch and TRADING_PAUSED gates server-side, matching `/api/paper-order`'s pattern exactly. Cross-check the manual price against a live quote when quotes exist; the manual-entry path is legitimately for the no-quote case, so keep that path open but bound it sanely (e.g. reject if a live quote exists and the manual price deviates beyond the same ±0.15 tolerance `/api/paper-order` uses).

### 5. Audit M-10 [MEDIUM, server half of C-1]: `/api/paper-order`'s price cross-check silently disables itself when `parse_market_price` raises

**Files:** `web_app.py:2909-2962` (as of `f4291771` — re-locate if moved).

`city`/`target_date`/`_mkt_prices_dash` are all derived inside one `try` block, with `_pmp_dash` (the price parse) last. If it raises, `city`/`target_date` are already bound by that point, so the fail-closed guard a few lines down passes on the identity check alone, `_mkt_prices_dash` stays `None`, and the ±0.15 deviation check — the one guard both `ee22c44c` and the batch-26 fix depend on — is silently skipped, while the log line claims city/date couldn't be derived (misleading about which check actually failed).

**Fix direction:** split the two derivations into separate `try` blocks. On a price-parse failure, either reject the order outright (recommended — fail closed the same way the identity check already does), or at minimum log accurately that the price check specifically was skipped, not the identity check.

### 6. Audit M-11 [MEDIUM, compounds C-1]: mock signals with live Approve buttons survive a real empty scan response

**Files:** `frontend/src/useData.js:433` (opportunities — also `:457` alerts, `:463` brierHistory); graduation Brier gate bar, `:107` + wherever `App.jsx:586,596`'s pre-port logic landed post-port (per the handoff doc, likely `tabs/OverviewTab.jsx` — **re-locate, don't trust the old App.jsx line cite**).

`if (sigsResult.signals.length)` keeps MOCK's 7 fabricated opportunities — each with a live Approve button — visible under a real "Last scan: Nm ago" header whenever a real scan legitimately returns zero signals. Server-side gates fail closed on the mock tickers today (bounding the blast radius to display-corruption, not real order placement) — **but that bound depends entirely on C-1 being unfixed in exactly the way that currently makes bulk-approve unconditionally report success without checking responses.** Once C-1 is fixed to actually inspect `d.error` per-response, this stops being purely cosmetic and starts being "bulk-approve 7 fake signals, get told 0 placed with 7 failures" — annoying but no longer silently wrong. Fix it anyway; don't rely on C-1's current bug as your safety net. Same `!= null` vs `.length`-truthiness bug `ee22c44c` already fixed for `positions`/`closedTrades` nearby in the same file — apply the identical pattern here. The graduation Brier bar has the same shape: it renders MOCK's `brier: 0.151` and paints green whenever the real value is `null`; render "insufficient data" instead.

**Fix direction:** replace the truthy-length checks with explicit `!= null` checks (mirroring the already-fixed sibling code in the same file), so a real empty response displays as empty, not as the mock seed.

## Process — follow the 29-step implementation workflow (`feedback-implementation-workflow`) exactly, in order

This batch is the dashboard's order-placement and position-close path — treat it with the same ceremony as a money-path batch even though live trading is dormant, because a dashboard operator trusts these toasts to reflect reality. Full 29 steps, no LOW-tier downgrade: (1) re-verify every claim against live code first — re-locate M-11's App.jsx cite, confirm M-9/M-10's `web_app.py` line numbers haven't drifted since `f4291771`. (3) The C-3 selection-pruning fix and the C-1 bulk-approve redesign both have more than one reasonable implementation shape — surface the choice via `AskUserQuestion` with a genuine recommendation rather than guessing. (7) Real, mutation-tested tests (via Edit-revert, not a string-replace script) for the response-inspection and selection-pruning logic specifically — these are exactly the kind of "looks right, silently doesn't check anything" bugs that need a test proving the guard actually fires. (8-9) Scoped tests only: `frontend` vitest suite (`cd frontend && npm test` — run `npm install` first if vitest isn't present) plus `tests/test_web_app.py`/`tests/test_web_auth.py` for the server halves — **never the full suite**. Rebuild `static/dist` in the same commit as any frontend change (repo convention) and confirm it's in sync. Lint via the real pre-commit interpreter. (11) Independent opus review at `effort: high` before push. (14-16) Backlog entries + `backlog_index.py` if `backlog.txt` is touched; compressed-pointer memory update; explicit confirmation before commit/push; `git fetch` + rebase-if-diverged immediately before the actual push. Full step list: `C:\Users\thesa\.claude\projects\C--Users-thesa-claude-kalshi\memory\feedback_implementation_workflow.md`.
