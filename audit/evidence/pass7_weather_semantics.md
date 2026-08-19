# Pass 7 — Weather Semantics — Evidence Notes

## Finding 1: settlement_monitor.py T-ticker branch uses instantaneous METAR reading, not running daily extreme

- Code: `settlement_monitor.py` `check_city_settlement()`, T-ticker (above/below)
  branch, ~line 456-467: calls `check_metar_lockout(current_temp_f=obs["current_temp_f"], ...)`
  directly. Contrast with the `between` branch immediately above it
  (~line 413-421) which correctly calls `fetch_metar_daily_extreme(...)` first.
- Sibling fixes that did NOT touch this branch:
  - `bded3d6` (2026-08-09): fixed weather_markets.py's `_metar_lock_in` above/below
    AND between branches to use `fetch_metar_daily_extreme`.
  - `39b1ba54` (2026-08-09): fixed settlement_monitor.py's `_check_between_settlement`
    (the `between` branch only) to use `max_temp_f` from `fetch_metar_daily_extreme`.
  - Neither fix touched `check_city_settlement`'s T-ticker (above/below) call site.
- Repro: `audit/reproductions/pass7_settlement_monitor_tticker_instantaneous.py`
  — run, exit 0, confirms a scenario where the true daily high (90F) clearly
  satisfies "above 85" but the code locks a confident (conf=0.839) WRONG "no"
  because it only sees the post-peak-cooldown instantaneous reading (80F).
- Downstream consumer: `cron.py` ~line 1471, `_sig_conf >= 0.80` auto-closes
  the matching PAPER position via `paper.close_paper_early()` with **no human
  review**. 0.839 > 0.80, so the repro's confidence would trigger this path.
- Team's own awareness: `backlog.txt` lines 1-140 document TWO related, already
  fully-tracked entries about this exact call site — but both frame it purely
  as a **calibration/confidence-population mismatch** ("different margin,
  different temperature basis... an extrapolation, not a like-for-like
  correction"), not as a **wrong lock-direction** (AC3-class) bug. The
  resolved entry (2026-08-16) added confidence *recalibration*
  (`_calibrate_metar_settlement_confidence`) but did not change what
  temperature value feeds the lock/outcome decision itself — recalibrating
  confidence cannot fix a locked `outcome` that is flatly wrong in direction.
- Live-status caveat (from the same backlog entries, self-reported by the
  team as of 2026-08-16): `data/cron.log` (1.8MB) has zero "SETTLEMENT LAG
  signal" lines ever, and `schtasks /Query /TN KalshiWeatherSettlementMonitor`
  shows the task was not registered on the machine that wrote that entry —
  i.e. this mechanism has apparently not fired in production yet. `cmd_schedule()`
  (added in `64c08693`, 2026-08-10) can register it; whether it has been
  registered on the actual trading machine is unverifiable from this
  worktree.

## Finding 2: _compute_persistence_prob's var="min" branch retains the staleness bug var="max" was fixed for

- Code: `weather_markets.py` `_compute_persistence_prob()`, lines 6121-6143.
  `if var == "max" and days_out == 0 and _live:` branch (fixed by `b0f4cad2`,
  2026-08-17) resolves a METAR station and calls
  `metar.fetch_metar_daily_extreme(..., "max")`. The `else` branch (covers
  `var == "min"` for ALL days_out, including 0) uses
  `_live.get("temp_f")` — the raw instantaneous NWS reading from
  `nws.get_live_observation()`.
- `nws.get_live_observation()` (nws.py line 432-484) confirmed to return only
  `{temp_f, timestamp, description}` — no max/min field, so the `else` branch
  is provably always the instantaneous reading, never a daily extreme.
- Existing test `tests/test_weather_markets.py::TestComputePersistenceProbRefactorSafetyNet::test_uses_instantaneous_temp_for_min_var`
  (line 5756) explicitly pins this as intended behavior with no domain
  justification given in its docstring beyond "the daily-max special case
  only applies to var='max'". No backlog.txt/BACKLOG_OPEN.md entry documents
  a deliberate scope decision to exclude var="min".
- Repro: `audit/reproductions/pass7_persistence_prob_min_var_staleness.py` —
  run, exit 0, confirms `climatology.persistence_prob("below", 60.0, None,
  current_value)` produces 0.0026 when fed the stale instantaneous 74F
  reading vs. 0.9452 when fed the true (already-realized) 52F daily low, for
  an identical "is the low below 60F" question.
- Consumption path (real, non-shadow, confirmed by reading `analyze_trade`):
  - Hourly path: `weather_markets.py` line 10207-10217, `0.15 * persistence_p`
    blend weight whenever `persistence_p is not None`.
  - Daily path: `weather_markets.py` lines 11955, 12016-12024, `w_persist = 0.15`
    whenever `persistence_p is not None and days_out <= 2`, folded into the
    renormalized `_active` weighted blend at line 12082-12095 that produces
    `blended_prob` → `rec_side` → Kelly sizing.
  - Both paths are gated on `not metar_locked` (verified: `_compute_persistence_prob`
    call sites sit inside `if not metar_locked:` blocks at both the hourly
    ~line 10192 and daily ~line 11592 call sites), so this only fires when
    METAR hasn't already confidently locked the outcome — i.e. exactly the
    ambiguous same-day LOW-market cases where a directionally-biased 0.15
    weight can matter most.

## Areas checked and confirmed NOT to be bugs (verified, not assumed)

- `CITY_COORDS` hardcoded fallback (weather_markets.py:240-268) is
  intentionally set to each city's actual settlement-station coordinates
  (confirmed by comment + spot-check of NYC=Central Park≈KNYC). `data/cities.json`
  does not exist in this environment (`Get-Content` confirmed
  `PathNotFound`), so the hardcoded fallback (not a separately-maintained
  JSON file that could drift) is what's actually in effect — `nws._get_obs_station`'s
  "nearest station" lookup from those coordinates should resolve to the same
  station as `metar.MARKET_STATION_MAP` in practice.
- `d190d09d`'s far-tail rain-climatology blend (`_analyze_monthly_rain_trade`):
  walked the `fetch_end_date`/`remaining_start_date`/`tail_start_day` month-
  boundary arithmetic; `fetch_end_date` is provably always within the target
  month (sandwiched between `remaining_start_date` and `remaining_end_date`,
  both constructed via `date(year, month, ...)`). Units consistent: Open-Meteo
  fetch explicitly requests `precipitation_unit: "inch"` (weather_markets.py:8086),
  matching ACIS `pcpn` (inches). Still shadow-only (blended_prob/rec_side/sizing
  untouched), so no live-trading impact regardless.
- `monte_carlo.py`'s `6364b38b` city-local-today fix: verified `t.get("city")`
  is reliably populated on every stored open-trade dict (`paper.py` writes it
  at multiple sites, e.g. line 995) and on the VaR-gate's synthetic `candidate`
  dict (`order_executor.py` line 2926) — the `America/New_York` fallback for a
  missing city is the established codebase-wide convention, not a new gap.
- `mos.py`'s NBS/NBP 00Z=max/12Z=min timezone-independence claim
  (`_fetch_nbs_daily_extremes`, `_parse_nbp_bulletin`): verified algebraically
  for all CONUS whole-hour-offset timezones (Eastern/Central/Mountain/Pacific,
  both standard and daylight) — the 12h period boundaries never straddle
  local midnight, consistent with the code's own live-verification claim.
- `nws.py`/`weather_markets.py`'s `_fetch_daily_temps_f`'s 30-hour observation
  window: confirmed sufficient to cover local-midnight-to-now for any CONUS
  timezone regardless of UTC offset, since the max possible local-midnight-to-now
  span is <24h by construction (not extended by timezone offset).
- `climatology.py`'s obs_prob (nws.py `obs_prob()`, not to be confused with
  `_compute_persistence_prob`): uses a fixed sigma=3.5 around the instantaneous
  reading for ALL condition types/vars, which is a deliberately coarser
  "always uncertain" model rather than the "resolve the true extreme when
  possible" design `_metar_lock_in`/`_compute_persistence_prob` use — this is
  a different, defensible design choice, not the same staleness bug (sigma=3.5
  already prices in the gap between "now" and the eventual extreme), so not
  flagged.

## Minor / INFO item (logged per pass instructions, not independently verified beyond static read)

- `climatology.py` `_climatological_prob_inner()` line 207:
  `diff = min(diff, 365 - diff)` for year-boundary wraparound in its
  day-of-year windowing uses a fixed 365, not the actual 365/366 length of
  either year being compared. This can shift the effective ±WINDOW_DAYS
  climatology window by up to 1 day near a leap-year boundary (e.g. Feb 29
  itself, or dates within WINDOW_DAYS of Dec 31 in a leap year). Not
  independently reproduced at runtime; effect size is at most 1 day out of a
  14-21 day window, applied only to the climatology baseline signal (one of
  several blended sources). Judged INFO severity.
