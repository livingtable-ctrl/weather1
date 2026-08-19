# Pass 9 (Time) — Independent Verification Notes

## Finding 1: _target_date_due UTC vs city-local (main.py)
- Confirmed function at main.py:467-483 (docstring/comment still asserts UTC-anchored
  rationale, referencing "backlog.txt ... 17 SITES STILL DON'T").
- Confirmed exactly two call sites: cmd_watch_settle's `_pending()` (main.py ~L878-892,
  `today_date = _utc_today()`, comment reasserts UTC-anchored premise) and the main-menu
  banner (main.py ~L7248-7255, `_today_date_menu = _utc_today_menu()`).
- Confirmed via `git show 0100bffe --stat` / commit message: that commit made
  analyze_trade's target_date city-local and explicitly says "main.py/monte_carlo.py's
  non-trading-path days_out sites are ... filed as a new backlog entry instead of bundled
  in here."
- Confirmed via `git show 6364b38b -- main.py`: the follow-up commit only touched
  `_feature_importance_days_out` (adds a `city` param + ZoneInfo) and monte_carlo.py's
  `simulate_portfolio`. It never touches `_target_date_due`, `cmd_watch_settle`, or the
  menu banner. So the claimed "missed by the fix sweep" is accurate — verified negatively
  (diff doesn't touch these lines) not just by absence of memory.
- Re-ran `audit/reproductions/repro_target_date_due.py` myself (not just trusted the
  original's transcript): output reproduced exactly as claimed —
  `due=True` vs UTC-today(2026-08-18), `due=False` vs NY-local-today(2026-08-17) for the
  same target_date=2026-08-18. This is genuine E2 evidence, independently obtained.
- Checked downstream impact: cmd_watch_settle's `_pending()` only controls loop exit/retry
  cadence; the actual settlement work each iteration is `sync_outcomes()` +
  `auto_settle_paper_trades()`, called unconditionally on every loop pass regardless of
  `_pending()`'s output (main.py ~L909-911). This supports the finding's own claim that
  financial risk is low/indirect — verified, not just repeated.
- Verdict: CONFIRMED, E2 (self-reproduced), confidence VERY HIGH.

## Finding 2: tracker.py Previous-Runs-API UTC arithmetic
- Confirmed `_fetch_previous_run_daily` (tracker.py ~L4178-4200) and
  `_fetch_previous_run_leads` (~L4257-4283) both use `_utc_today()` with matching stale
  comments citing pre-0100bffe rationale.
- Confirmed `_fetch_previous_run_daily` is only called from the offline
  `backfill_emos_data` path (tracker.py ~L4613).
- Confirmed `_fetch_previous_run_leads` is only reached via
  `get_forecast_run_trend` -> `get_forecast_run_trend_from_analysis`, called with
  `analysis["target_date"]`/`analysis["days_out"]` — i.e. analyze_trade's own city-local
  values (post-0100bffe). `get_forecast_run_trend`'s own docstring confirms this signal is
  "log-only today ... must never block a trade decision", matching the finding's "Very low"
  financial-risk claim.
- Off-by-one direction double-checked: during the evening window `utc_today()` runs ahead
  of city-local today, so `forecast_days = (target_date - utc_today()).days + 1` is
  under-counted by 1 relative to using city-local today — consistent with the finding.
- Verdict: CONFIRMED, E1 (static, but cross-referenced against call graph and 0100bffe
  diff), confidence HIGH.

## Finding 3: cmd_forecast UTC-anchored display
- Confirmed main.py:3918-3949 `cmd_forecast(city)` uses `utils.utc_today()` with no
  ZoneInfo despite `city` being a parameter of the function.
- Financial risk correctly characterized as none (manual CLI display command).
- Verdict: CONFIRMED, E1, confidence HIGH.

## Finding 4: web_app.py forecast endpoints UTC labeling + stale comment
- Actual function positions are swapped relative to the finding's symbol-order text but
  the line ranges and content are correct: `api_today_forecasts` is at web_app.py
  ~L2097-2124 (uses `utils.utc_today()`, uniform across cities, no comment), and
  `api_forecast` is at ~L3185-3222 and contains the "WA-timezone" comment claiming
  "the tracker/analytics side of this codebase standardizes on utils.utc_today()".
- Confirmed via `git log -S"WA-timezone" -- web_app.py` -> commit 54b0c576, dated
  2026-07-11, which predates 0100bffe (2026-08-11, moved the trading-logic side of the
  codebase to city-local target_date comparisons) — so the comment's premise is now
  contradicted, exactly as claimed.
- Verdict: CONFIRMED, E1, confidence HIGH. (Minor cosmetic note: the finding's symbols
  list order doesn't match line order, but the substance is accurate — not treated as a
  factual error.)

## Finding 5: log_prediction's documented UTC fallback
- Confirmed tracker.py ~L863-886: prefers `analysis["days_out"]`, falls back to
  `max(0, (market_date - _utc_today()).days)` only when the caller doesn't supply
  `analysis["days_out"]`, with an explicit comment describing this as the accepted
  fallback for shadow/lookup writes.
- This is presented (correctly) as informational/already-understood, not a bug.
- Verdict: CONFIRMED (as an accurate, intentional observation), E1, confidence HIGH.

## Summary
All 5 findings verified against current code and, for #1, independently re-executed.
None disproven. No new findings introduced (out of scope for this verification pass).
