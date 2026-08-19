# Pass 7 -- Weather Semantics -- Evidence Notes

## Finding 1: _compute_persistence_prob's daily-extreme fix (b0f4cad2) only covers var="max", not var="min"

- weather_markets.py:6090-6154 (`_compute_persistence_prob`)
- Special-case branch: `if var == "max" and days_out == 0 and _live:` (L6121) resolves a METAR
  station and calls `metar.fetch_metar_daily_extreme(station, tz, local_today, "max")` to get the
  TRUE running daily high, instead of the instantaneous `temp_f`.
- No symmetric branch exists for `var == "min"`. All `var=="min"` days_out==0 calls fall through
  to `_live_temp = _live.get("temp_f") if _live else None` (L6143) -- the raw instantaneous
  reading.
- `metar.fetch_metar_daily_extreme()` (metar.py:374) explicitly supports `extreme="min"` and is
  already used this way by `_metar_lock_in`'s between-branch (weather_markets.py ~L10160-10164)
  for LOW markets.
- Confirmed via git history this asymmetry is NOT a deliberate, reasoned scope decision: backlog.txt's
  entry ("PREFER TODAY'S OBSERVED MAX BRANCH IS DEAD CODE") that led to b0f4cad2 discusses only the
  HIGH/max case throughout (filing, resolution, AskUserQuestion options) -- var="min" is never
  mentioned. tests/test_weather_markets.py::TestComputePersistenceProbRefactorSafetyNet::
  test_uses_instantaneous_temp_for_min_var (L5756) asserts the CURRENT (asymmetric) behavior as a
  regression-safety-net, not as evidence of an intentional design tradeoff -- it just locks in
  whatever b0f4cad2 shipped.
- persistence_p feeds real (non-shadow) blended_prob at 0.15 weight in analyze_trade's daily path
  (L12016-12024) whenever `not metar_locked` and `days_out<=2`, and in _analyze_hourly_trade
  (L10214-10217) unconditionally when available. This directly affects live trade edge/Kelly sizing
  for same-day (days_out=0) LOW/"below"-type markets and min-var hourly markets, whenever METAR has
  not yet locked (e.g. any time before the running-low's 3F clearance margin is reached, or for
  cities without METAR).
- Domain reasoning: for a LOW-type market the true daily low typically occurs pre-dawn; by the time
  a scan runs later in the day the instantaneous reading is materially warmer than the already-
  locked-in low. Using it as the persistence center systematically biases the signal toward "warmer
  than actually occurred," understating P(below threshold) exactly mirroring the HIGH-side bug
  b0f4cad2 fixed (afternoon instantaneous reading understating an already-passed peak).
- Evidence level: E1 (static code + test read, cross-referenced against backlog.txt narrative and
  metar.py's own extreme="min" support). Not run/reproduced this session (E2 would require invoking
  the function against a synthetic live METAR observation).

## Finding 2: settlement-lag force-close gate (d320142d, 2026-08-16) is a documented, permanently-unreachable threshold

- settlement_monitor.py:277-359 (`_calibrate_metar_settlement_confidence`), consumed by cron.py's
  ">=0.80 force-close" gate.
- The commit's own docstring/comment (L304-322) states the calibrated confidence can never exceed
  ~0.766 (YES) / ~0.595 (NO) under the currently-fitted model (a=b=0.2262, c=0.4001), both
  permanently below the 0.80 gate -- so the force-close path is currently dead code in practice,
  not merely rare.
- At review time (2026-08-16) the commit verified via `schtasks` that the daily
  `KalshiWeatherSettlementMonitor` task had never been registered on the reviewed machine, so this
  was framed as "not a live regression." `cmd_schedule()`'s registration step (main.py, added by
  64c08693 on 2026-08-10) is a manual, interactively-confirmed CLI action -- it does not
  self-register. Whether the task has since been registered on the user's actual production machine
  is unverifiable from this repo snapshot; if it has, the force-close path silently never fires
  under current calibration coefficients, and this asymmetry has no operator-visible failure mode
  (no error, no log warning) beyond the absence of "SETTLEMENT LAG signal" log lines.
- Self-tracked in backlog.txt (per the commit message) as a follow-up item, not omitted or hidden --
  logged here per audit instructions to record even self-acknowledged/tracked issues.
- Evidence level: E1 (static code read of the documented bound; did not re-derive the beta-calibration
  coefficients or re-run the model this session).

## Areas checked with no issues found (recent-commit scope, Pass 7 focus)

- d190d09d (far-tail climatology rain blend): unit consistency (inches throughout, both
  `_fetch_ensemble_precip_multiday`'s `precipitation_unit=inch` and acis_precip's historical sums),
  date-boundary/guard logic for the "before month starts" and "far case" branches (tail_start_day
  stays within the target month given the 6-day/14-day guards), SEAS5 tilt reuse -- all traced and
  internally consistent; shadow/log-only, does not affect real trades. The commit's own comments
  already disclose the short-tail floor-clamping SEAS5 approximation as an accepted, low-magnitude
  limitation.
- bded3d6a / 39b1ba54 (METAR between-bucket lock-in re-enable, weather_markets.py + settlement_monitor.py):
  re-read current state of `_metar_lock_in`'s between branch and `_check_between_settlement` --
  comp_temp_f threading, station-gap `between_edge` gate margin derivation, and the per-observation
  local-date guard all check out against the shipped fix; no residual AC3-class instantaneous-vs-
  extreme conflation found.
- 0100bffe / 6364b38b (city-local vs UTC target_date comparisons): verified fixes in weather_markets.py,
  nws.py, mos.py, tracker.py, main.py, monte_carlo.py all use ZoneInfo-based city-local "today" with a
  UTC fallback on ZoneInfo failure; nws_prob's `coords[2]` tz-index usage confirmed correct against
  `_CITY_TZ`'s own construction (`coords[2]` for every entry). Grepped remaining `datetime.now(UTC).date()`
  call sites across weather_markets.py -- the ones inspected (cache/season-year/close_time-based
  days_out at L5620, hurricane season year, activation timestamps) are legitimately UTC-anchored
  (external API cache keys, market close_time which Kalshi returns in UTC, hurricane season
  bookkeeping), not target_date/city-local comparisons of the bug class this cluster fixed.
- e0fd1cc0 (settle daily HIGH/LOW from Kalshi's own expiration_value): weather_markets.py's portion of
  this commit is a docstring/comment-only update (removed dead-branch-discrimination text, no logic
  change) -- no independent finding.
- F/C unit conversions across metar.py, nws.py, weather_markets.py (wet_bulb_temp): all use the
  correct `C*9/5+32` / `(F-32)*5/9` formulas; no inversion or coefficient errors found.
- 64c08693 (settlement-monitor cron scheduling, DST/local-midnight window computation): commit's own
  text describes 2 real DST/zone-date-crossing bugs found and fixed during implementation
  (independently opus-reviewed); current code was not independently re-derived against a live DST
  transition date this session (E1 read only, not exercised).
