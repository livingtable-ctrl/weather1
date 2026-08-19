# Pass 15 — Reliability (Section 27)

Scope: startup/shutdown/restart, provider/API outage, DB/persistence failure,
stale data, partial failure, dependency failure, state recovery,
resynchronization, unexpected termination. Priority: silently incorrect
trading behavior (no exception, wrong decision).

## Finding 1 (HIGH): cmd_watch --auto --live has no standalone
_recover_pending_orders() call; a crash-window phantom 'pending' live row
stays invisible to live position protection whenever run_trade_cycle() is
skipped for lock contention.

- `_recover_pending_orders()` (order_executor.py:269-355) reconciles
  'pending' execution_log rows against Kalshi's API — specifically the
  crash window where a row was pre-logged before/without the API response
  being persisted (order_id missing, response falsy).
- It is called from exactly two places: cron.py:900-904 (top-level,
  unconditional, BEFORE `_check_live_position_exits`/`_check_live_model_exits`
  at cron.py:912-919 — deliberately restored there per backlog history, see
  cron.py:888-897 comment) and trade_cycle.py:222-226 (inside
  `run_trade_cycle()`, near the top, before scan/settle/analyze).
- cmd_watch (main.py) NEVER calls `_recover_pending_orders` directly (grep
  confirms zero call sites in main.py — only comment references at
  main.py:4683, 4729). It only reaches recovery indirectly, through
  `run_trade_cycle()`, called at main.py:3632 — but ONLY inside
  `if auto_trade:` AND only when `ctx.acquire_cron_lock()` (main.py:3622)
  succeeds. If the lock is held (cron.py's scheduled task is mid-run —
  `ctx.acquire_cron_lock()` is held for the FULL `_cmd_cron_body()` duration,
  cron.py:2409-2466, released only in `finally`; default watchdog timeout is
  8 minutes, cron.py:2402), `cycle_result` stays `None` (main.py:3641-3646,
  prints a routine yellow "[Auto] Could not acquire the cron lock ...
  auto-trade skipped this cycle" — not an error).
- The `if live:` block (main.py:3759-3790) that runs
  `_check_live_position_exits`/`_check_live_model_exits` is NOT gated on
  `cycle_result` — it runs every watch cycle regardless, using whatever
  execution_log state currently exists.
- `_get_live_open_positions()` (order_executor.py:1077-1115) sources from
  `execution_log.get_filled_unsettled_live_orders()` (execution_log.py:535-556),
  which filters `status = 'filled'` — a row stuck at `status='pending'` with
  no `response` is invisible to it.
- `_poll_pending_orders()` (order_executor.py:424-540), which cmd_watch DOES
  call every cycle (main.py:3760), only promotes pending rows that already
  have `response`/`order_id` recorded (filter at order_executor.py:442
  `and o.get("response")`, `if not order_id: continue` at 455) — it does
  NOT cover the exact crash-window case `_recover_pending_orders` exists for.
- LIVE_TRADING_RUNBOOK.md:131 confirms this is not a hypothetical
  interleaving: "`python main.py cron` never places live orders — only
  `watch --auto --live` does" — i.e. the documented, intended live-trading
  mode is exactly a long-running `watch --auto --live` session, while
  cron.py's own scheduled task (registered HOURLY /MO 3, i.e. every 3 hours,
  main.py:8963-8991) runs concurrently and independently against the SAME
  cron-lock file and the SAME execution_log.db.
- Net effect: a live order that fills on Kalshi's side but whose
  execution_log row never got its `response`/order_id persisted before a
  crash (the exact ~50ms window `_recover_pending_orders`'s own docstring
  describes) sits unrecoverable and untracked for however long the watch
  session's cycles keep losing the lock race against a concurrent cron run —
  bounded in practice to roughly one cron run's duration (up to the 8-minute
  watchdog) plus however many 5-minute watch cycles overlap it, i.e. a
  window on the order of 10-15+ minutes with ZERO stop-loss/breakeven/
  model-exit coverage on a real live position, and no exception or visible
  error distinguishing this from the routine "lock contended" message.
  cron.py's OWN next scheduled run (up to 3 hours later) will eventually
  self-heal it via its own `_recover_pending_orders()` call, so exposure is
  not unbounded, but the affected window is exactly when protection is
  most needed (right after an actual crash/restart).
- Evidence level: E1 (static code read of all four functions + both
  call-site files + the runbook's stated operating mode). Not exercised
  live (no credentials in this worktree). Reproduction would require a
  live client and deliberately induced order_id-write failure — out of
  reach here.
- Distinct from Pass 10/22's confirmed Finding 1 (cmd_watch's `if live:`
  block missing try/except around the SAME four calls) — that finding is
  about an unhandled exception killing the whole watch loop; this finding
  is about an ordering/coverage gap that produces silently-absent
  protection with no exception at all, and is specific to the
  cron-lock-contention interleaving that cluster A's "cron and cmd_watch
  share one engine now" claim doesn't fully cover.

## Finding 2 (MEDIUM): far-tail rain-blend's newly-reachable
_fetch_ensemble_precip_multiday() far-case path shares `_ensemble_cb`
(weather_markets.py's global ensemble circuit breaker) with the REAL
temperature trading blend's prewarm fetch — a false trip from the shadow
signal can silently degrade live ensemble data quality with no error.

- d190d09d (2026-08-17) extends `_analyze_monthly_rain_trade`'s shadow-only
  `rain_forecast_blend_prob` signal to early-month tickets, newly reaching
  `_fetch_ensemble_precip_multiday(lat, lon, tz, remaining_start_date,
  fetch_end_date)` for windows where `remaining_start_date` is up to 6 days
  out (weather_markets.py, guard at the diff's `if (remaining_start_date is
  not None and fetch_end_date is not None and fetch_end_date >=
  remaining_start_date and (remaining_start_date - today_local).days <= 6)`).
  The commit's own message calls this "a newly-reachable circuit-breaker
  corruption path" and adds the 6-day cap specifically to reduce (not
  eliminate) it — the accompanying comment explicitly concedes "6 days is a
  conservative, explicitly-documented heuristic ... not a precise constant."
- Inside `_fetch_ensemble_precip_multiday` (weather_markets.py:8016-8149),
  each per-model fetch (`_fetch_model_totals`, :8073-8137) that returns an
  all-null response for the requested day range raises internally and is
  caught by its OWN `except Exception: _ensemble_cb.record_failure()`
  (:8128-8129) — this is a SIDE EFFECT on the shared, global, disk-persisted
  `_ensemble_cb` (weather_markets.py:108-113, `CircuitBreaker(name=
  "open_meteo_ensemble", failure_threshold=3, recovery_timeout=300,
  burst_window=2.0)`) that happens BEFORE and INDEPENDENTLY of the outer
  `except Exception as _fb_exc:` wrapper in `_analyze_monthly_rain_trade`
  that the commit's docstring cites as isolating "a bug here must only ever
  cost this new signal" — that isolation covers the shadow signal's own
  LOGIC exceptions, not this circuit-breaker mutation.
- `_ensemble_cb` is the SAME breaker instance consulted by
  `batch_prewarm_ensemble`'s Tier-1 "blend-critical temp models" loop
  (weather_markets.py:2009-2014, comment verbatim: "These feed the live
  trading blend directly ... first claim on the rate budget" — `for model in
  blend_models: if _ensemble_cb.is_open(): break`) and by the real
  (non-shadow) per-market ensemble fetch call sites at weather_markets.py
  lines 1997, 2097, 3013, 3048, 7613, 7991.
- `trade_cycle.py:309-310` confirms `_run_batch_prewarm(ctx, markets)` runs
  ONCE, before the per-market analysis loop (:314+) — so within a single
  scan, a same-cycle false trip from monthly-rain analysis (which runs
  later, per-market) cannot retroactively undo an already-completed
  same-cycle prewarm. The realistic impact windows are: (a) any real
  per-market analysis later in the SAME loop iteration that hits an
  ensemble-fetch cache miss (a fresh network call through the same shared
  breaker) after the shadow signal has already tripped it earlier in that
  same loop, and (b) the NEXT cycle's prewarm, if the breaker (300s
  recovery_timeout) is still open when that next cycle's `batch_prewarm_*`
  runs — for `watch --auto` (5-minute refresh loop, main.py comment
  "Auto-refreshes every 5 min") this window is comparable to the loop
  interval, so cross-cycle contamination is plausible; for the scheduled
  cron job (HOURLY /MO 3 = 3-hour interval) it self-heals well before the
  next run.
- `burst_window=2.0s` absorbs same-call, near-simultaneous failures — one
  ticket's own 3-model fetch sequence (icon_seamless, gfs_seamless,
  ecmwf_ifs025, weather_markets.py:8139-8144) landing within 2s of each
  other likely counts as a single failure event, not three, so tripping
  `failure_threshold=3` in one call is unlikely; it requires this pattern
  recurring across MULTIPLE early-month monthly-rain tickets (different
  cities → different HTTP calls, plausibly >2s apart) within one scan
  cycle, i.e. correlated near-boundary misses across several cities'
  fetches — a real, if narrower, scenario than "any single call trips it."
- Net effect: a shadow-only, log-only signal explicitly designed so "a bug
  here must only ever cost this new signal, never the existing
  bootstrap-only analysis below" can, via a side channel its own isolation
  claim does not cover, silently degrade the REAL live temperature trading
  blend's ensemble diversity (fewer members from skipped models) with no
  exception and no visible symptom beyond a WARNING-level circuit-breaker
  log line unrelated on its face to temperature markets.
- Evidence level: E1 (static code read of both the new far-case code path,
  `_fetch_ensemble_precip_multiday`, `circuit_breaker.py`'s exact trip
  semantics, `batch_prewarm_ensemble`'s shared-instance use, and
  `trade_cycle.py`'s prewarm-then-analyze ordering). Not reproduced live
  (would require live Open-Meteo API access and control over per-model
  response timing to force the correlated-miss scenario) — confidence
  reflects that this is a real, code-verified causal chain but the
  probability of actually tripping the shared breaker in any given cycle
  is not independently measured here.

## Finding 3 (MEDIUM, self-disclosed by the codebase): settlement-lag
force-close's METAR-calibrated confidence can mathematically never reach
cron.py's >=0.80 gate under the current fitted model — the safety net is
silently dormant by construction, not by a runtime failure.

- d320142d (2026-08-16) wires `_calibrate_metar_settlement_confidence()`
  (settlement_monitor.py:277-354) into the T-ticker settlement-lag
  force-close signal. Its own docstring (settlement_monitor.py:304-322)
  states, verified against real production coefficients (a=b=0.2262,
  c=0.4001): `metar._dynamic_lock_in_confidence()`'s hard [0.72, 0.97]
  bound, run through the calibration, never exceeds ~0.766 (YES-lock) or
  ~0.595 (NO-lock) — both permanently below cron.py's `>=0.80` force-close
  threshold.
- Confirmed current: settlement_monitor.py:283 and :309 still reference the
  ">=0.80 force-close gate" and the dormancy conclusion verbatim; no
  rescale has landed (matches the commit's own statement that this was
  filed as a follow-up backlog entry, deliberately not fixed, pending real
  settlement-lag data).
- The commit's own text states this is "not a behavior regression against
  real production traffic" because, at the time, the daily
  KalshiWeatherSettlementMonitor schtasks job had never been registered on
  this machine. Per recon (cluster H/64c08693), `main.py` now DOES contain
  code to register that daily job — so once an operator runs the setup
  flow the runbook describes, this gate becomes live-but-permanently-inert:
  it will compute, log, and evaluate a calibrated confidence every day, but
  can never actually trigger a force-close, with no error, warning, or
  visible indicator that the safety net is unreachable under current
  calibration data (the WARNING-level log at settlement_monitor.py:344-350
  fires only on the unrelated "correction magnitude exceeds cap" path, not
  on "confidence structurally can't reach the gate").
- This is included for completeness per this pass's instructions ("log
  even small findings") — it is largely self-disclosed by the commit
  message/docstring/backlog rather than a fresh discovery, but it is
  squarely on-topic for this pass (a safety-net dependency that is silently
  unable to do its job) and worth confirming still-open.
- Evidence level: E1 (static read of settlement_monitor.py's current code
  and its own docstring's stated verification; did not independently refit
  the METAR model to re-derive the 0.766/0.595 bounds — trusting the
  commit's own stated verification here, consistent with its detail and
  internal consistency).

## Finding 4 (INFO): ml_bias.py's HMAC sidecar write bypasses the
codebase's established atomic-write convention, but the HMAC-verification
design happens to fail safe on a torn write anyway.

- `_write_hmac()` (ml_bias.py:72-75) does `_HMAC_PATH.write_text(...)`
  directly — not `safe_io.atomic_write_text`/`atomic_write_json`, unlike
  the rest of the codebase's post-cluster-J convention (94d36402, 3a28ae33,
  f2c03d98 routed remaining bare-write sites through safe_io, and
  `tests/test_bare_os_replace_guard.py` exists specifically to catch
  stragglers — this path writes via `Path.write_text` directly, not
  `os.replace`, so that particular guard test would not catch it).
- However, `_load_models()`'s docstring (ml_bias.py:78-90) confirms every
  rejection path (missing secret, missing sidecar, HMAC mismatch) returns
  `{}` — no bias correction, not a crash and not silently-accepted garbage.
  A process kill mid-write to either the pickle or the `.hmac` sidecar
  produces a mismatch (or a missing/truncated file), which the HMAC check
  is specifically designed to reject. So despite the non-atomic write
  pattern, the specific verify-before-use design already provides the same
  practical protection atomic-write would — no live risk identified, purely
  a convention inconsistency.
- Evidence level: E1 (static read of `_write_hmac`, `_load_models`,
  confirmed no atomic_write_* call in the HMAC sidecar's write path).

## Areas checked with no findings logged
- kalshi_ws.py reconnect loop, flash-crash cooldown/history persistence
  across restart (circuit_breaker.py:294-455): reconnect-with-backoff,
  disk-persisted cooldowns/history correctly pruned to non-expired entries
  on load, both call sites (WS thread + order_executor fallback) already
  documented and consistent. No issue found.
- execution_log.py / tracker.py SQLite connection settings: WAL +
  `synchronous=FULL` + `timeout=30`, versioned `PRAGMA user_version`
  migrations with per-step version advancement (crash-between-migrations
  leaves an accurate version, not v0) and duplicate-column-vs-genuine-error
  discrimination. `add_live_loss`/`get_today_live_loss`/
  `get_today_live_spend` fail closed (return `inf`) on DB failure via a
  same-day degraded-flag mechanism (execution_log.py:383-532) — a
  deliberately hardened pattern, no gap found in this pass's read.
- `_recover_pending_orders` cron.py-side ordering (recovery before
  `_check_live_position_exits`) is correctly fixed per backlog.txt's own
  historical note and confirmed current at cron.py:888-923 — this pass
  independently re-verified it is NOT similarly fixed for cmd_watch (see
  Finding 1).
- ForecastCache / PersistentForecastCache (forecast_cache.py): TTL
  semantics, monotonic-vs-wall-clock timestamp handling on disk
  restore, and the documented `set_at_with_ttl` vs `set_at` distinction
  (avoiding accidentally resurrecting an already-expired short-TTL entry)
  are correctly reasoned through in the code's own docstrings; no defect
  found on read.
