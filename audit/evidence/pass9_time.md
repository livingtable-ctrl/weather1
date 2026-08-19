# Pass 9 — Time — Evidence Notes

## Scope

Traced the city-local-vs-UTC target_date fix chain (0100bffe, 6364b38b) and
verified whether it was applied everywhere `target_date` (a city-local
calendar date derived from `parse_city_date()`/ticker parsing) is compared
against "today". Also checked DST/ZoneInfo construction (tzdata is present
in requirements.txt and works on this Windows host — verified live), METAR
observation staleness gates (metar.py, tz-aware throughout, no bug found),
daily-extreme running-max window logic (metar.fetch_metar_daily_extreme,
correctly documented "today only" contract, both callers respect it),
settlement_monitor.py's scheduled-task DST handling (64c08693, careful
target-instant-based conversion, no bug found), and the far-tail-blend
commit (d190d09d) for month-boundary rollover in its near/far day
arithmetic (no rollover bug found — guard conditions keep fetch_end_date
within the target month in all reachable cases).

## Key finding: `_target_date_due()` still compares city-local target_date to UTC-today

`main.py:467` `_target_date_due()` is called from exactly two sites
(confirmed via grep — no other callers):
- `cmd_watch_settle()`'s `_pending()` closure, main.py:886-892
- the main-menu "N trade(s) due today" banner, main.py:7251-7255

Both compute `today_date = utils.utc_today()` and pass it into
`_target_date_due(t.get("target_date"), today_date)`. `target_date` on a
paper trade dict is stored verbatim from `analyze_trade()`'s
`target_date.isoformat()` (order_executor.py:3101, `target_date=target_date_str`),
which — per the entire 0100bffe/6364b38b fix chain — is the CITY-LOCAL
calendar date parsed from the market ticker, not a UTC-anchored value.

This is the exact bug class both those commits fixed everywhere else they
found it (weather_markets.py, nws.py, mos.py, tracker.py, main.py's
`_feature_importance_days_out`, monte_carlo.py's `simulate_portfolio`) —
missed at these two sites, whose comments (main.py:883-885) still assert
the old, now-incorrect "target_date is UTC-anchored" rationale.

### Reproduction (E2)

`audit/reproductions/repro_target_date_due.py` imports `main` directly and
calls `main._target_date_due()` with a concrete boundary case: a trade
target_date of `2026-08-18` (tomorrow in NY-local terms), evaluated at a
simulated instant where UTC-today has already rolled to `2026-08-18` but
NY-local-today is still `2026-08-17` (a real ~4h window that occurs nightly
for Eastern-zone markets, longer for western zones).

```
target_date = 2026-08-18
compared against UTC-today (2026-08-18)  -> due=True
compared against NY-local-today (2026-08-17) -> due=False
```

Confirms the function marks a trade "due" for settlement up to a day before
its market has actually reached its local target date, during the nightly
UTC-ahead-of-local window.

### Impact assessment

Both call sites are observational/human-facing, not order-placement gates:
- `cmd_watch_settle`'s `_pending()` only controls when the poll loop
  concludes ("Exits automatically when nothing remains to settle") — being
  over-inclusive means the loop keeps polling longer than necessary, not
  that it settles anything incorrectly (actual settlement is driven by
  `auto_settle_paper_trades()` against real Kalshi/tracker state, not by
  this predicate).
- The main-menu banner just misinforms the operator ("N trade(s) due
  today") up to ~1 day early during the nightly window.

No direct money-moving consequence found, but it is a real, currently-live
instance of the documented bug class in the exact dimension this pass
targets, in code whose sibling call sites were already fixed by name.

## Secondary findings (same bug family, lower impact)

- `tracker.py:4195-4283` (`_fetch_previous_run_daily`, `_fetch_previous_run_leads`)
  — comments literally assert "target_date is UTC-anchored (see
  analyze_trade's own days_out computation against datetime.now(UTC))",
  which was true before 0100bffe but is now stale/wrong; `_utc_today()` is
  still used to compute `past_days`/`forecast_days` against a target_date
  that is genuinely city-local for these callers' real usage (via
  `get_run_trend`'s shadow "FORECAST RUN-TO-RUN TREND SIGNAL", log-only,
  and an offline backfill script). Off-by-one during the nightly window
  could under-size `forecast_days`/mis-size `past_days` by one day,
  degrading a shadow signal's data quality, not a live trading gate.

- `main.py:3918` `cmd_forecast()` — CLI "7-day forecast" display starts its
  date range from `utc_today()` rather than city-local today; during the
  nightly window the displayed "today" row is actually tomorrow's
  forecast. Human-facing CLI-only display, not touched in the audited
  commit window.

- `web_app.py:3184` `/api/forecast` and `web_app.py:2097`
  `/api/today_forecasts` — both use `utc_today()` as "today" for a
  per-city forecast display; the inline comment at web_app.py:3202-3206
  ("the tracker/analytics side of this codebase standardizes on
  utils.utc_today()") is now stale given 0100bffe moved the trading-logic
  side to city-local dates — the documented rationale for this dashboard's
  own known limitation no longer matches the rest of the codebase. Predates
  the audited commit window (2026-07-11, commit 54b0c576), display-only.

- `tracker.py:864-886` `log_prediction()`'s fallback days_out clamp
  (`elif market_date is not None: days_out = max(0, (market_date -
  _utc_today()).days)`) is UTC-based, used only when the caller doesn't
  supply `analysis["days_out"]` — explicitly documented in the surrounding
  comment as an accepted, narrow-scope fallback for non-analyze_trade
  callers (shadow/lookup writes). Noted for completeness, not a new gap.

## Areas checked with no finding

- metar.py observation-age staleness gate (90 min) — obsTime parsed
  tz-aware in every branch (epoch int, ISO string, reportTime fallback),
  compared against `datetime.now(UTC)` consistently — no naive/aware
  mismatch.
- `metar.fetch_metar_daily_extreme()` — correctly documented "only valid
  for target_date == today in city_tz" contract; both callers
  (`weather_markets._metar_lock_in`, `_compute_persistence_prob`,
  `settlement_monitor.check_city_settlement`) pass a freshly-computed
  city-local "today", not a caller-supplied arbitrary date.
- `settlement_monitor.py`'s scheduled-task registration (64c08693,
  main.py `cmd_schedule()`) — computes the daily task's fixed local
  start time from the target instant's own timestamp (not "now"'s),
  correctly avoiding a DST-transition-window bug a naive
  now-based-offset conversion would have introduced.
- `d190d09d`'s far-tail rain-blend day arithmetic — `near_end_date`/
  `fetch_end_date` never cross a month boundary in any of the three
  reachable branches (verified the day-count algebra for all three:
  before-month-starts, mid-month, and the (defensive/unreachable) past-
  month-end case), so `tail_start_day = fetch_end_date.day + 1` is always
  a valid day-of-month for the ticker's own accrual month.
- `zoneinfo`/`tzdata` availability on this Windows host — verified live
  (`ZoneInfo('America/New_York')` resolves correctly), so the
  `try/except Exception: fallback to UTC` pattern used throughout the
  fix chain is not silently defeating itself on this platform.
- `monte_carlo.py`'s `simulate_portfolio` city key (`t.get("city")`) is
  the consistently-used key throughout that file and matches the key
  `paper.py` actually stores trades under — no key-name mismatch that
  would silently default every trade to the "America/New_York" fallback.
