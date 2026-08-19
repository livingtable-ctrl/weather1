# Pass 3 — Requirements audit evidence

## Method
This repo's commit messages + backlog.txt/BACKLOG_OPEN.md are unusually rich, self-documented
requirements artifacts (opus-review findings baked into commit bodies, explicit "Resolves
backlog.txt LNNNN" links, "Why not now" sections). Used these as primary requirements source
per pass instructions ("explicit requirements/comments" ranks above tests/docs in priority),
then verified each claim against the current HEAD code (not just trusting the commit message).

## Confirmed findings (see StructuredOutput for full detail)

1. L1947 (open) — main.py:9562-9584 KALSHI_ENV=prod startup banner's
   `_live_orders_possible = cmd == "watch" and "--auto" in args and "--live" in args`
   only accounts for watch --auto --live. cmd_order independently derives
   `_is_live = client.base_url != DEMO_BASE` (main.py:4528) and calls
   `pre_live_trade_check` (L4531-4534) -- so cmd_order buy/sell CAN place live
   orders once LIVE_TRADING_ENABLED=true, contradicting the banner text at L9578.
   Confirmed still present at HEAD (d190d09d).

2. L1994 (open) — paper.check_position_limits() (paper.py:3447) computes
   existing_cost (per-market cap, L3629-3632), get_total_exposure() (global 50%
   cap), get_city_date_exposure/get_directional_exposure/get_correlated_exposure
   (L1598-1622) -- ALL of these read paper.get_open_trades() (L1299-1301), which
   reads paper_trades.json exclusively. Since e5331a8d (2026-08-17) routed live
   fills into execution_log instead of paper_trades.json, check_position_limits'
   exposure caps are now structurally blind to real live positions across EVERY
   cap it enforces (per-market, global portfolio, city/date, directional,
   correlated-group) -- not just city/date as the backlog title implies.
   cmd_order's live buy path DOES call check_position_limits (main.py:4546-4569),
   so this is a real, reachable gap for live money once LIVE_TRADING_ENABLED=true.
   This is the "fixing a crash relocates it" pattern: e5331a8d fixed the live-fill
   visibility bug for the *protective-exit scanner* but this pre-existing
   exposure-cap blindness was pre-existing and is now confirmed still open,
   self-filed as a new backlog entry in the SAME commit that (accidentally)
   removed live fills from paper's ledger (their prior accidental visibility
   route, for the wrong reasons).

3. L4 (open, dormant) — cron.py:1471 `_sig_conf >= 0.80` T-ticker force-close
   gate. metar._dynamic_lock_in_confidence() (metar.py:31-57) is bounded to
   [0.72, 0.97] by construction (docstring + code, L47/L57). Backlog's
   hand-computed sweep through the calibration model claims calibrated output
   tops out at ~0.766 (YES) / ~0.595 (NO), both < 0.80 -- so this force-close
   gate can structurally never fire under the current fitted calibration model.
   d320142d (2026-08-16) wired METAR calibration into this exact gate and
   self-documented this as a new consequence, filed as backlog L4, explicitly
   deferred ("Why not now: no real settlement-lag data exists yet"). Confirmed
   the settlement-lag mechanism is wired (settlement_monitor.py + cron.py:1437+)
   but not yet scheduled on THIS machine (backlog's own schtasks check). Did
   NOT re-derive the calibration model's numeric ceiling myself (E1 static
   read of the bound + gate value only, not a full re-run of the fitted a/b/c
   sweep) -- treating the backlog's own hand-verified sweep as E1 secondary
   evidence, not re-confirmed independently this session (limitation noted in
   the finding).

4. NEW-M1 (self-documented in code, main.py:4605-4619, not a separate backlog
   entry -- folded into L1994's scope by the code comment itself) -- a live
   cmd_order sell only closes the OLDEST of multiple open live positions
   sharing the same ticker+side; others are print-warned but untouched.
   Root cause is the same one as L1994 (no mechanism prevents duplicate live
   entries because check_position_limits can't see existing live exposure).

## Areas checked and found consistent with reconstructed requirements (no new finding)

- cluster D core routing (execution_log.record_live_exit_fill, IOC order type,
  quantity clamping, settled_at concurrency guard) -- code matches commit
  message's description of the fixes; docstrings are detailed and self-consistent.
- cluster E timezone fix (6364b38b) in monte_carlo.py -- verified _today_mc is
  always a `date` object in both the ZoneInfo-success and except branches
  (utils.utc_today() returns `date`), so the date/string comparison fallback
  logic at L341-346 is sound.
- cluster M admin accuracy-override -- minutes<=0 guard present (main.py
  ~L3372-3374), CLI-only (grepped web_app.py, no accuracy-override route),
  matches commit's documented design.
- cluster L CSRF header check (web_app.py L187-205) -- all state-changing
  routes use explicit POST/DELETE methods (grepped all 68 @app.route decls);
  /api/override GET variant is read-only. No GET-based mutation route found.
- cluster C paths.py bypass guard -- ran tests/test_paths_bypass_guard.py and
  tests/test_bare_os_replace_guard.py directly (E2, both pass at HEAD). Manual
  grep for `Path(__file__)` sites not caught by the regex guard (its own
  documented limitation is indirect 2-line construction) found only legitimate
  non-data uses (env file discovery, bot.log placement anchored to script dir,
  code-audit's own source listing, start.bat launcher, test sys.path setup).
  No new unmigrated data/-directory bypass found.
- b0f4cad2 persistence_prob dead-branch fix -- verified the new
  _metar_station_for_city + fetch_metar_daily_extreme call replaces the dead
  nws.get_live_observation()-derived max_temp_f/high_f read; matches commit
  message; found no residual issue.
- cluster A shared engine -- grepped confirmed both cron.py:1281 and
  main.py's cmd_watch (~L3632) call the same trade_cycle.run_trade_cycle().

## Not deeply re-verified this pass (time-boxed; flagged for a future pass)
- d190d09d's far-tail climatology blend internals (199 lines + 577-line test
  rewrite) -- shadow/log-only (blended_prob/rec_side/sizing untouched per
  commit message), so financial risk is near-zero even if a bug exists; did
  not verify the SEAS5 tilt / deterministic cross-product math itself.
- EMOS activation chain (4557a77b/5d9b6c56/d320142d) end-to-end -- read the
  commit messages' self-documented opus-review fix lists but did not
  independently re-derive each fix's correctness against code this session.
- Hurricane shadow-only models (1a7c9aca/46c44435/9a7583aa) -- recon already
  confirmed the gate-refusal behavior; did not re-derive each model's math.
