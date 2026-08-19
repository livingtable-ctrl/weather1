# Pass 17 verification notes (independent re-check)

## Finding 1: VaR gate blind to standing live positions
- order_executor.py:2364 `_open_trades_list = get_open_trades()` -> paper.py:1299
  `return [t for t in _load()["trades"] if not t["settled"]]`, and `_load()` reads
  `DATA_PATH = _project_root()/"data"/"paper_trades.json"` (paper.py:109). Confirmed:
  paper ledger only, no live merge.
- order_executor.py:1077-1115 `_get_live_open_positions()` (execution_log-backed) is
  only referenced at order_executor.py:1156 and :1465 (LivePositionStore.get_open /
  a different consumer) — grepped all uses in order_executor.py/trade_cycle.py/cron.py;
  never called inside `_auto_place_trades` (confirmed by reading lines 2300-3130 in full).
- VaR gate at 2916-2941 calls `portfolio_var(_open_trades_list + [candidate])` — candidate
  dict shape matches `_get_live_open_positions()`'s dict shape, so the proposed merge in
  the recommendation is structurally plausible, not merely aspirational.
- backlog.txt lines ~570-620 (6364b38b resolution note, read in full) does say
  "Site 2 reaches a real live-trade-gating decision via portfolio_var ->
  order_executor._auto_place_trades' MAX_VAR_DOLLARS check" without mentioning the
  live-position blind spot — matches the finding's characterization.
- Verdict: CONFIRMED, E1 (static trace, no live run possible in this worktree).

## Finding 2: kalshi_client.py stale "no live caller uses IOC" comment
- Comment at kalshi_client.py:583-585 verified verbatim, still present unchanged.
- git blame: comment added in commit 555bf1e0 (2026-07-11). order_executor.py's
  `_exit_live_position` already passed `time_in_force="immediate_or_cancel"`
  (current line 1255) starting commit efa13ed4 (2026-07-13) / ef6224d8 (2026-07-12) —
  i.e. the comment became false about a month BEFORE e5331a8d (2026-08-17), not because
  of it. e5331a8d (`git show e5331a8d -- main.py`) does add a second IOC live caller
  (main.py cmd_order, `time_in_force="immediate_or_cancel"` at diff line 208).
- The finding's own body already discloses "_exit_live_position already used IOC before
  that" — so its evidence is honest, but its title/root_cause framing ("now false after
  e5331a8d") overstates e5331a8d's role: the docstring was already inaccurate for ~5
  weeks prior. Downgrading root-cause attribution accordingly; the core defect (stale,
  now-doubly-false comment) stands.
- Verdict: CONFIRMED (documentation defect real and current) but downgrade "caused by
  e5331a8d" framing — it's more accurately "e5331a8d added a second falsifying caller
  to an already-stale comment." E1.

## Finding 3: metar.py fetch_metar_daily_extreme docstring caller list stale
- metar.py:396-404 docstring text verified verbatim ("Both current callers
  (settlement_monitor.py, weather_markets.py's _metar_lock_in)...").
- grep confirms 3 call sites: weather_markets.py:6137 (new), :10368, :10433
  (_metar_lock_in), settlement_monitor.py:416.
- weather_markets.py:6100-6146 (_compute_persistence_prob) read in full: confirmed it
  computes `_local_today` via ZoneInfo(city_tz) with a UTC fallback on exception, then
  passes that as target_date — i.e. today's date in city-local time, consistent with the
  function's precondition. No functional bug, purely a stale docstring caller list.
- git show b0f4cad2 confirms this is the commit that added the third call site
  (2026-08-17, "source real daily-high for persistence_prob's dead branch").
- Verdict: CONFIRMED, INFO severity as filed, E1.

## Finding 4: unmatched_sell pnl=0.0 placeholder indistinguishable in exports
- main.py:4806-4829 (`elif action == "sell":` branch inside cmd_order) verified verbatim,
  including the "0.0 is a neutral placeholder, not a real P&L claim" comment and the
  `record_live_early_exit(row_id, price, "unmatched_sell", 0.0)` call.
- execution_log.py:807-843 `export_live_tax_csv` WHERE clause: `o.live = 1 AND
  o.settled_at IS NOT NULL AND o.pnl IS NOT NULL` — no exit_reason filter.
- execution_log.py:894-934 `get_live_pnl_summary` — both today_pnl and total_pnl queries
  use `WHERE live = 1 AND settled_at IS NOT NULL AND pnl IS NOT NULL` (or LIKE date) with
  no exit_reason filter either.
- Confirmed: exit_reason='unmatched_sell' rows are indistinguishable from genuine $0.00
  outcomes in both consumers, exactly as claimed. The finding's own "limitations" section
  already flagged this as unverified-elsewhere and asked for a follow-up grep — that grep
  is now done, confirms no special-casing exists anywhere in execution_log.py.
- Verdict: CONFIRMED, E1.
