# Pass 14 — Performance: Independent Verification

Re-examined all 7 findings from audit/evidence/pass14_performance.md against current
repo state (worktree reverent-lumiere-f79c1f). All file:line citations opened and
read directly; repro script re-executed independently.

## Finding 1 — paper.check_paper_position_exits() N+1 REST calls — CONFIRMED
- paper.py:1467-1469: `for t in open_trades: market = client.get_market(t["ticker"])`
  confirmed verbatim, one signed REST call per open position, no batching.
- order_executor._get_current_book (order_executor.py:131-166) confirmed to try
  `kalshi_ws.get_cached_book` first, REST only on miss — genuinely a better pattern
  paper's function does not use.
- web_app.py:1425-1459 confirmed single `client.get_markets(tickers=...)` batched call
  (same audited window, 709b0043) — contrast holds.
- cron.py:1683 and main.py:3825 both confirmed as unconditional call sites.
- Re-ran `python audit/reproductions/repro_n1_paper_position_exits.py` myself this
  session: output confirms 12 open positions -> 12 `client.get_market()` calls, 0
  `client.get_markets()` calls. Matches the finding's own repro output exactly.
- Verdict: CONFIRMED, E2 (independently re-executed), confidence HIGH.

## Finding 2 — Position-protection redundant analyze_trade() re-runs — CONFIRMED (static)
- trade_cycle.py:406-426: confirmed `_enrich_and_analyze` submitted to an 8-worker
  ThreadPoolExecutor (`ThreadPoolExecutor(max_workers=8)`) over `deduped_markets`
  (all open weather markets, no held-ticker filter found anywhere upstream).
- order_executor._check_early_exits (order_executor.py:1836-1930) and
  _check_live_model_exits (order_executor.py:1448-1537) both confirmed to
  independently call get_weather_markets(client) and run a plain sequential
  `for` loop calling enrich_with_forecast()+analyze_trade() per position — no
  ThreadPoolExecutor in either.
- backlog.txt:13520-13531 confirmed verbatim: "down to two: run_trade_cycle()'s own
  scan, and _check_early_exits()'s own separate scan... now the ONLY remaining one" —
  confirmed this omits _check_live_model_exits.
- Confirmed via `git show --stat efa13ed4`: dated 2026-07-13, "Add live position
  protection: stop-loss, breakeven-stop, model-exit" — wires _check_live_model_exits
  into main.py (line 3790, inside the `if live:` cmd_watch auto-loop block) and
  cron.py:919, matching the finding's claim that the Aug-3 backlog recount predates
  and did not re-examine this July commit.
- get_weather_markets 60s TTL cache confirmed at weather_markets.py:4263-4270
  (`_MARKETS_CACHE`, `_MARKETS_CACHE_TTL` check), supporting the finding's
  "network cost mitigated, CPU cost is the real one" caveat.
- Verdict: CONFIRMED at E1 (static only, no live credentials to measure wall-clock;
  original evidence_level E1 stands), confidence raised to HIGH — every specific
  claim independently traced and matched exactly.

## Finding 3 — Shadow-gate batch-hoisting (25aef473) — CONFIRMED (positive finding)
- order_executor.py:2569-2577: 6 gate booleans (`_hourly_gate_active` through
  `_storm_order_gate_active`) confirmed assigned once, before the `for item in opps:`
  loop starting at line 2579.
- tracker.py:2264-2318 (count_settled_hourly_predictions, count_settled_rain_predictions)
  confirmed each opens its own `_conn()` (tracker.py:413-419, a fresh
  `sqlite3.connect(DB_PATH)` per call, not pooled).
- Verdict: CONFIRMED, E1, confidence VERY HIGH (matches original).

## Finding 4 — ForecastCache migration (ae321905) no regression — CONFIRMED
- climatology.py:73,299 confirmed `_MEM_CACHE`/`_sigma_mem_cache` are
  `ForecastCache(ttl_secs=float("inf"))`.
- forecast_cache.py:43-54 confirmed `_evict_oldest` is an O(n) `min()` scan over
  `self._store`, only triggered in `set()` when `len(self._store) >= self._max_size`
  (default 500).
- git show ae321905 commit message confirms "preserving exact 'load once per
  process' behavior" intent, matching diff behavior.
- Verdict: CONFIRMED, E1, confidence HIGH (matches original).

## Finding 5 — Far-tail rain cross-product uncached but negligible — CONFIRMED, with one caveat
- weather_markets.py:8880-8898 confirmed the deterministic cross-product
  `combined_totals = [m + t for m in member_totals for t in tail_sums_tilted]`,
  not memoized (no cache wraps this block; only the upstream
  `_fetch_ensemble_precip_multiday` call has its own 4h `ForecastCache`, confirmed
  at weather_markets.py:2231/8064/8148).
- acis_precip.py:396-433 (historical_remaining_and_full_month_sums) confirmed to
  iterate `history.items()` (one entry per historical year), bounding
  tail_sums_tilted by available-year count.
- Caveat: the finding's evidence text says member_totals is "bounded to roughly 30
  (icon_seamless + gfs_seamless + weighted ecmwf_ifs025)" as if all three models
  contribute in the far case. The actual in-code comment at weather_markets.py:8800-8803
  is more specific and slightly contradicts that framing: in the far-case branch
  specifically, "the far case's 'ensemble' was actually always exactly 30
  gfs_seamless members, zero ECMWF weight" (icon_seamless's own horizon is too short
  to reach the far window). The finding's numeric bound (~30) is still correct, just
  the attribution to "three models summed" is imprecise — it's actually one model's
  ~30 members. Does not change the negligible-cost conclusion.
- Verdict: CONFIRMED, E1, confidence HIGH (downgraded from finding's stated intent
  only by the minor attribution imprecision noted above, not the conclusion).

## Finding 6 — monte_carlo.portfolio_var() O(n^2) pure-Python inner loop — CONFIRMED
- monte_carlo.py:478-486 confirmed the per-simulation Cholesky application is a
  pure-Python nested comprehension: `z = [sum(chol[i][k]*epsilon[k] for k in
  range(i+1)) for i in range(n_trades)]` — triangular O(n_trades^2/2) per simulation,
  no numpy.
- order_executor.py:2908-2915 confirmed the exact benchmark comment cited
  ("~2.5s cumulative across a realistic 15-candidate cron cycle... negligible
  against this bot's multi-hour cron cadence, but real") verbatim, and
  order_executor.py:2929 confirmed `portfolio_var(_open_trades_list + [candidate])`
  called once per surviving candidate inside the placement loop.
- `git show 6364b38b -- monte_carlo.py` confirmed the exact timezone-fix diff:
  replaced `utc_today()` comparison with a ZoneInfo-based city-local `_today_mc`,
  matching the finding's causal claim that more trades now correctly survive the
  past-date filter and participate in the O(n^2) loop.
- Verdict: CONFIRMED, E1, confidence HIGH (matches original; did not re-benchmark
  the 2.5s figure, same limitation as original).

## Finding 7 — web_app.py batch-fetch live quotes (709b0043) — CONFIRMED
- web_app.py:1404-1459 confirmed single `client.get_markets(tickers=",".join(_tickers),
  limit=min(len(_tickers), 1000))` call, `client` closed over from `_build_app(client)`
  (web_app.py:134) rather than reconstructed — confirmed no `KalshiClient()` call
  inside `api_trades`.
- web_app.py:1460-1474 confirmed fallback-to-SSE-snapshot-cache logic per ticker on
  partial/missing batch results.
- frontend/src/useData.js:540 and 'weather app site V_3 (3)/src/useData.js':608 both
  confirmed `setInterval(fetchAll, 60_000)` — 60s polling in both frontend trees.
- Verdict: CONFIRMED, E1, confidence VERY HIGH (matches original).

## Summary
All 7 findings survive verification with their original status directionally
correct. No findings disproven. One finding (5) has a minor evidentiary imprecision
(model attribution) that does not affect its conclusion. Finding 1's evidence level
raised to a personally-re-executed E2. Finding 2's confidence raised from MEDIUM to
HIGH after tracing every cited line and cross-referencing the efa13ed4 commit date
independently (the original finding's efa13ed4 claim was not itself re-derived from
git log in the original pass's own evidence text — I verified it here).
