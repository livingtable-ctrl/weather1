# Pass 5 verification — Sections 10 & Scope B (Feature Integration)

Verifier session, read-only. Repo root: `C:\Users\thesa\claude kalshi\.claude\worktrees\reverent-lumiere-f79c1f`

## Finding 1 — VaR gate blind to live positions (order_executor.py:2364/2930, monte_carlo.py, paper.py)
- order_executor.py:2313 imports `get_open_trades` from `paper`; line 2364 `_open_trades_list = get_open_trades()`. Confirmed.
- order_executor.py:~2928 `projected_var = portfolio_var(_open_trades_list + [candidate])` — runs before the `if live and live_config:` branch (line ~3002), so applies to both live and paper placement. Confirmed.
- paper.py:1299-1301 `get_open_trades()` = `[t for t in _load()["trades"] if not t["settled"]]` — paper_trades.json only, no execution_log reference. Confirmed.
- Checked ALL callers of `simulate_portfolio`/`portfolio_var` repo-wide (grep, 14 files incl. tests). Three non-test production callers besides order_executor.py:
  - main.py:8594 `cmd_montecarlo` — paper-only, human-triggered display, non-gating. Matches finding's claim.
  - cron.py:1779 — "Portfolio VaR summary after placement" — paper-only (`paper.get_open_trades`), explicitly post-placement, display/log only, non-gating.
  - web_app.py:1653 — dashboard VaR-95/99 display, paper-only, non-gating.
  - Finding's text said main.py:8592 was "the only other caller" — this is a minor incompleteness (missed cron.py and web_app.py), but doesn't change the substance: all three additional callers are display-only and paper-only, none gate placement. order_executor.py:2930 remains the sole live-trade-gating call site.
- utils.py:300 `MAX_VAR_DOLLARS = float(os.getenv("MAX_VAR_DOLLARS", "200.0"))` — $200 default confirmed.
- Verdict: CONFIRMED (E1, static trace, fully independently re-derived).

## Finding 2 — Startup banner misidentifies live-order-capable commands
- main.py:9567 `_live_orders_possible = cmd == "watch" and "--auto" in args and "--live" in args`. Confirmed at cited location.
- main.py:4531 (inside `cmd_order`, def at line 4333) and main.py:2481 (inside `_quick_paper_buy`, def at line 2170) both independently call `trading_gates.pre_live_trade_check(client)` guarded only by `getattr(client, "base_url", None) != DEMO_BASE`, entirely independent of `cmd == "watch"`. Confirmed both call sites, function identities, and guard logic exactly as described.
- e5331a8d commit message referenced as filing this as deferred — not independently re-read but consistent with backlog.txt findings for finding 3 (same investigation, same date).
- Verdict: CONFIRMED (E1).

## Finding 3 — paper.check_position_limits blind to live positions
- paper.py:3447 `def check_position_limits(...)`.
- paper.py:3629-3635 `existing_cost = sum(t.get("cost",0.0) or 0.0 for t in get_open_trades() if t.get("ticker")==ticker)` — paper-only.
- paper.py:3645 `get_total_exposure() + new_cost/_exposure_denom() >= MAX_TOTAL_OPEN_EXPOSURE` and the city/date/directional/correlated checks (3654-3684) all route through get_city_date_exposure/get_directional_exposure/get_correlated_exposure.
- grep for "execution_log" in paper.py: zero functional references (only comments referencing it by name for context, none imported/read in the exposure functions). Confirmed.
- backlog.txt lines ~1994-2057 contain the exact entry "paper.check_position_limits' EXPOSURE CAPS ARE STRUCTURALLY BLIND TO REAL LIVE POSITIONS", dated 2026-08-17, with near-verbatim "confirmed EMPIRICALLY MOOT today: zero live=1 rows have ever existed in execution_log" language matching the finding's own text. Confirmed already-filed status.
- Verdict: CONFIRMED (E1).

## Finding 4 — settlement_monitor METAR force-close gate structurally dormant
- settlement_monitor.py:277-313 docstring for `_calibrate_metar_settlement_confidence`; body at 324-356; actual output bound in code is `max(0.01, min(0.99, new_confidence))` (line 349), NOT [0.72,0.97] itself — the [0.72,0.97] bound belongs to `metar._dynamic_lock_in_confidence()` (metar.py:47,57), which is the INPUT range fed into this calibration, not this function's own output clamp. The finding's phrasing ("applies a hard [0.72, 0.97] output bound") is imprecise about which function owns the bound, but the docstring itself (settlement_monitor.py:306-313) correctly attributes it to metar.py and draws the same conclusion the finding does.
- cron.py:1471 `if _sig_conf >= 0.80 and _sig_ticker in _open_by_ticker:` confirms the >=0.80 force-close gate exists and consumes settlement-lag signals from `read_settlement_signals`.
- Independently recomputed the calibration math myself (not just trusting the docstring): sigmoid(a*ln(s) - b*ln(1-s) + c) with a=b=0.2262, c=0.4001 (values cited in the docstring), swept over s in the documented input range:
  - YES-lock, s=0.97 (max of [0.72,0.97]): calibrated = 0.7661 — matches docstring's "~0.766" claim exactly, and monotonically increasing in s so this is the max.
  - NO-lock, raw_p_yes=0.03 (max NO confidence, mapped from confidence=0.97 via 1-0.97=0.03): new_p_yes=0.4046 -> new_confidence(no)=1-0.4046=0.5954 — matches docstring's "~0.595" claim exactly.
  - Both are below the 0.80 gate threshold across the entire documented input domain.
  - Also confirmed `_METAR_CORRECTION_LIMIT=0.60` doesn't cause these corrections to be skipped (deltas computed are 0.20-0.375, under the 0.60 cap), so the calibration actually applies rather than silently falling back to raw (which could have been >=0.80).
- Could NOT independently verify the cron.log / schtasks claims (no cron.log present in this worktree; paths.py routes logs to the main clone) — relying on the commit message's own documented check for that specific sub-claim only.
- Verdict: CONFIRMED, upgraded evidence level to E2 (ran the actual calibration formula myself and reproduced the exact numbers, rather than relying on the docstring's assertion).
