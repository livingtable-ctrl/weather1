# Batch 34: Dashboard & web order-path hardening

> **PARTIALLY SUPERSEDED (2026-08-23, post-port).** This batch was written against the pre-port monolith (`App.jsx` at ~126 KB); commit `002c34cb` then retired that file and promoted the V3 tabbed app into `frontend/src/` (post-port `App.jsx` is ~22 KB / ~520 lines), so this batch's line cites for anything that lived in `App.jsx` are stale. A follow-up frontend review (`FRONTEND_REVIEW_HANDOFF.md`) re-located the still-open frontend items into new batches:
> - Item 3 (M-10) and item 4 (M-9) → **[batch-41](batch-41.md)**, bundled with that review's own C-1/C-2 client-side bugs (the review explicitly says fix client+server halves together).
> - Item 5 (M-11) → **[batch-41](batch-41.md)** (compounds C-1 there).
> - Item 1 (audit M-8: halt/resume/kill discard response) and item 6 (F-M7: Nav badge) → **[batch-45](batch-45.md)**.
> - Item 8 (F-M4: stale opportunity object) → **[batch-48](batch-48.md)**.
>
> Items 2 (M-7: `unlink()` missing `missing_ok`) and 7 (L-17 web sweep, `web_app.py`-only parts) are **untouched by the port and still valid here** — `web_app.py` wasn't part of the V3 promotion. Work items 2 and 7 from this file as originally written; work items 1/3/4/5/6/8 from their new batches instead, re-locating each to its current post-port file/line before editing.

## Context

Repo: weather1. Written 2026-08-23 against master `f4291771` — re-verify before starting. Source: `audit/POST_MERGE_REVIEW.md` (plus `findings_F` detail preserved there). Files owned: `web_app.py`, `frontend/src/*` (+ rebuild `static/dist` and commit it, matching the repo's convention of shipping the built bundle). Parallel-safe with 33/35-39. Prereq quick-action: `cd frontend && npm install` (vitest is a declared devDependency, currently missing — M-23g; run `npm test` after every frontend change, 29 tests exist).

Positive baseline from the audit (don't re-litigate): all 67 routes are behind `_check_auth` (auth + X-Requested-With CSRF), no secrets serialize into responses, batch-26/ee22c44c bid-ask pricing verified correct on all four sites, the auth-dedupe and stale-selectedPos fixes are intact.

## Items

### 1. M-8 [MEDIUM | skeptic-downgraded from HIGH]: halt/resume/kill buttons discard the server response

**Files:** `frontend/src/App.jsx:238, 1675, 2152, 2156` (exhaustive — verified; also present in the shipped `static/dist` bundle).
`window.confirm(...) && fetch('/api/halt', {method:'POST', headers: authHeader()})` — no `.then`/`.catch`/state update. Batch-25 gave `/api/halt` a real 500 path (`web_app.py:2097`) that no client code reads; failures are silent and the ⛔ badge lags up to the next 60s poll. Skeptic context: the CLI is the documented kill procedure and a watching operator sees the badge not flip — hence MEDIUM — but the fix is trivial: `.then(r => r.ok ? data.refresh() : addToast('Halt FAILED — use `py main.py kill`', 'error')).catch(...)`; `addToast` already exists in scope. Apply to all four call sites.

### 2. M-7 [MEDIUM]: `api_resume`'s `unlink()` lacks `missing_ok`, re-opening batch-25's own M5 race

**Files:** `web_app.py:2104-2106` (sibling parked-unlink 15 lines below HAS `missing_ok=True`); same pattern at `api_override_clear` (`:2516-2518`) racing cron's expiry auto-clear.
The resume case is the bad one: `main.py:425` parks the kill switch at `.kill_switch.tmp` during an override window; if that lands between `exists()` and `unlink()`, the raised FileNotFoundError → 500 → **the parked-copy cleanup at `:2121-2124` never runs → the kill switch silently re-arms when the override ends** — exactly what batch-25 wrote those lines to prevent, compounded by item 1's silent client. Fix: `missing_ok=True` on both, and wrap `api_override_clear`'s in the route's JSON error shape instead of Flask's HTML 500.

### 3. M-10 [MEDIUM]: `/api/paper-order`'s price cross-check silently disabled when `parse_market_price` raises

**Files:** `web_app.py:2909-2962`.
`city`/`target_date`/`_mkt_prices_dash` derive in ONE try, with `_pmp_dash` last: if it raises, city/date are already bound so the fail-closed guard at `:2943` passes, `_mkt_prices_dash` stays None, and the ±0.15 deviation check at `:2962` — the guard batch-26 and ee22c44c both depend on — is skipped, with a log line claiming city/date couldn't be derived. Fix: split the two derivations into separate try blocks; on price-parse failure either reject the order (recommended — fail closed like `:2943`) or at minimum log accurately.

### 4. M-9 [MEDIUM]: `/api/close-position` missing the kill-switch + TRADING_PAUSED gates and any price cross-check

**Files:** `web_app.py:3127-3169`; `paper.py:1497` does no validation of its own.
Its sibling `/api/paper-order` has all three (`:2783`, `:2787`, `:2962`). ee22c44c widened reachability with an operator-typed manual exit price feeding straight into `proceeds`/`pnl`/`balance` → drawdown tier, `peak_balance`, graduation `total_pnl`. The missing price-check is tracked (`backlog.txt:20408`); the missing gates are not. Fix: add both gates server-side; cross-check the manual price against live quotes when quotes exist (manual entry is legitimately for the no-quote case — keep that path, bound it sanely).

### 5. M-11 [MEDIUM]: mock data survives real empty responses

**Files:** `frontend/src/useData.js:433` (opportunities; also `:457` alerts, `:463` brierHistory), `:107` + `App.jsx:586,596` (graduation Brier).
`if (sigsResult.signals.length)` keeps MOCK's 7 fabricated opportunities — with live Approve buttons — under a real "Last scan: 3m ago" header whenever a real scan returns zero signals (server fails closed on the mock tickers, so display-corruption not order risk). And the graduation gate bar renders MOCK's `brier: 0.151` and paints itself green whenever the real value is null. Apply the same `!= null` fix ee22c44c already applied to positions/closedTrades 20 lines above, and make the Brier bar render "insufficient data" on null instead of the mock seed.

### 6. F-M7 [MEDIUM, display]: Nav badge hardcodes `Demo · Paper` on a `KALSHI_ENV=prod` deployment

**Files:** `frontend/src/App.jsx:221`. `/api/status` already returns `kalshi_env`/`is_live` and SettingsTab renders the real value — the always-visible header contradicts it. Bind the badge to the real values.

### 7. L-17 web sweep [LOW — same files, do while here]
(a) `web_app.py:2803` `quantity` parse outside any try → HTML 500 on non-numeric; match the file's own `WA-input-validation` pattern.
(b) `:2781` `/api/paper-order` reads the kill switch via `from cron import KILL_SWITCH_PATH` while every sibling uses `_KS_PATH` — unify (monkeypatch blind spot).
(c) `:2969` NO-side order on a `yes_bid==1.0` market skips the deviation check (`_expected_side_price > 0`) — handle the boundary.
(d) `:3053` past target date clamped to `days_out=0` labels a stale multi-day market same-day and dodges the `MAX_POSITIONS_PER_DATE` slot cap — reject or floor at rejection, don't clamp.
(e) `:372-425` both SSE generators are `while True` with no client-disconnect break — pinned worker thread per tab; break on GeneratorExit.
(f) `:1492-1493` a live quote degraded to 0 never falls back to the snapshot, contrary to the adjacent comment.
(g) `App.jsx:1223` confirm-modal Enter handler dead (no tabIndex); `:533,828,905` divide-by-`p.qty` with no zero guard (NaN render).

### 8. F-M4 [MEDIUM, stretch — do if time allows, else file to backlog]: SignalsTab submits orders from a detached stale opportunity object

**Files:** `App.jsx:959,964,1087,1092` (batch-26 edited these lines).
Identity-compare selection + `confirmPending` freezing the whole opp (with quotes) at Approve-click; a confirm modal open across a 60s poll or scan-refetch books at pre-refresh quotes, bounded only by the server's ±0.15 check (which item 3 fixes). PositionsTab was already rewritten to `selectedId` + `useMemo` for exactly this (`App.jsx:694-705`) — generalize the same pattern to SignalsTab.

## Process

Full 29-step workflow (the dashboard can place paper orders and toggle the kill switch — safety-adjacent; opus review effort=high). Re-verify claims live. Tests: `tests/test_web_app.py`, `tests/test_web_auth.py`, `frontend` vitest — **never the full suite**. Rebuild `static/dist` in the same commit as frontend changes (repo convention). Lint via the real pre-commit interpreter. Backlog entries + `backlog_index.py`. Confirm before commit. Full workflow: `memory/feedback_implementation_workflow.md`.
