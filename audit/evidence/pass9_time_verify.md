# Pass 9 (Time) — Independent Verification Notes

## Finding 1: _target_date_due UTC vs city-local
- main.py:467-483 (`_target_date_due`) read directly — matches claim, docstring/fallback exactly as described.
- Call sites confirmed: main.py:886-892 (`cmd_watch_settle._pending`, comment at 883-885 explicitly asserts UTC-anchored rationale) and main.py:7230-7256 (main-menu due-today banner, `_utc_today_menu()`).
- git show 0100bffe -- tracker.py confirms only `log_prediction` was touched in tracker.py; commit message explicitly says main.py/monte_carlo.py sites were filed as a *separate* backlog entry ("not bundled in here").
- git show --stat 6364b38b confirms that follow-up commit fixed only `_feature_importance_days_out` (main.py) and `monte_carlo.py`'s `simulate_portfolio` — NOT `_target_date_due`. So the two `_target_date_due` call sites were never touched by either fix commit.
- Re-ran audit/reproductions/repro_target_date_due.py myself (`py audit/reproductions/repro_target_date_due.py`) — output:
  ```
  target_date = 2026-08-18
  compared against UTC-today (2026-08-18)  -> due=True
  compared against NY-local-today (2026-08-17) -> due=False
  ```
  Independently reproduces the claimed divergence. E2 confirmed.
- Verdict: CONFIRMED, unchanged.

## Finding 2: tracker.py _fetch_previous_run_daily / _fetch_previous_run_leads
- tracker.py:4195-4200 and 4277-4283 read directly — both comments explicitly justify UTC-anchored day arithmetic, matching claim verbatim.
- git show 0100bffe -- tracker.py confirms these two functions are untouched by that commit (only log_prediction changed).
- Confirmed target_date passed into `get_forecast_run_trend` (tracker.py:4327) originates from `get_forecast_run_trend_from_analysis` (tracker.py:4426), which extracts `analysis["target_date"]` — the same city-local value analyze_trade produces post-0100bffe.
- Minor: the finding's prose calls the live entry point "get_run_trend" — actual live caller is order_executor.py:2163 `from tracker import get_forecast_run_trend_from_analysis as _get_run_trend`; substance unaffected, just an informal alias, not a naming error in the underlying claim.
- Confirmed docstring of get_forecast_run_trend (tracker.py ~4340): "this signal is log-only today ... and must never block a trade decision" — supports the LOW severity / very-low financial-risk characterization.
- Verdict: CONFIRMED (E1 static, as originally claimed; not executed, matches "Not executed" self-disclosure).

## Finding 3: cmd_forecast UTC-anchored display
- main.py:3918-3949 read directly. Line 3924/3927: `from utils import utc_today as _utc_today` / `today = _utc_today()`, no ZoneInfo despite `city` param being known. Matches claim exactly.
- Verdict: CONFIRMED (E1, matches original).

## Finding 4: web_app.py api_forecast / api_today_forecasts stale comment
- web_app.py:2097-2128 is actually `api_today_forecasts` (confirmed uses `utils.utc_today()`).
- web_app.py:3184-3227 is actually `api_forecast` (confirmed uses `utils.utc_today()`, and carries the WA-timezone comment at 3202-3206).
- Note: the finding's parallel arrays (`symbols` vs `lines`) pair `api_forecast` with `2097-2128` and `api_today_forecasts` with `3184-3222` — the line ranges are correct for the two functions but the pairing order in the JSON is swapped relative to the symbols list. This is a cosmetic bookkeeping slip, not a substantive error — both functions and both line ranges are accurate, and the core comment-staleness claim is about `/api/forecast` specifically, which is genuinely at 3184-3227.
- git log -S "WA-timezone" -- web_app.py → commit 54b0c576, dated 2026-07-11 (confirmed via git log -1 --format=%ad). This predates 0100bffe (2026-08-11), confirming the "premise predates and is now contradicted" claim.
- Verdict: CONFIRMED (E1), with a note on the minor symbol/line pairing mix-up.

## Finding 5: tracker.py log_prediction UTC fallback
- tracker.py:864-886 read directly — matches claim exactly (already an explicitly-documented, intentional fallback per the 0100bffe diff itself).
- Verdict: CONFIRMED as accurately described (INFO-level, no action needed, as the finding itself states).

## Summary
All 5 findings independently verified against current code and git history; all held up. No disproven findings this pass. One executed reproduction (finding 1) upgraded from claimed E2 to independently-re-confirmed E2. Finding 4 has a minor cosmetic line/symbol pairing slip in the original JSON that does not affect the substance of the claim.
