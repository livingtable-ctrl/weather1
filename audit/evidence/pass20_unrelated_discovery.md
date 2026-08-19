# Pass 20 — Unrelated Discovery

Scope: broad sweep outside the 53-commit window and its direct dependency
graph. Sampled modules: circuit_breaker.py, kalshi_ws.py, watchdog.py,
regime.py, cloud_backup.py, param_sweep.py, feature_importance.py,
sigma_audit.py, check_edge.py, notify.py, backlog_index.py, market_types.py,
acis_precip.py, acis_snow.py, climate_indices.py (partial), web_app.py
(auth/CSRF layer, halt/resume routes — spot check only, web_app.py is
already in-scope for the 53-commit deep dive so not re-audited fully here),
main.py (grep sweep for eval/exec/shell=True/pickle patterns across the
whole repo).

## Finding: param_sweep.py PAPER_MIN_EDGE sweep values don't overlap its own accepted range

- File: param_sweep.py:166-168 (`params_to_sweep` dict in `run_sweep()`),
  cross-referenced against param_sweep.py:102-129 (`load_swept_min_edge`,
  clamps to `[0.03, 0.15]`) and config.py:192-230
  (`_compute_paper_min_edge_from_files`, same `[0.03, 0.15]` walk-forward
  clamp, hardcoded 0.05 final fallback).
- `run_sweep()`'s `params_to_sweep["PAPER_MIN_EDGE"]` is
  `[0.15, 0.20, 0.25, 0.30, 0.35, 0.40]` — apparently copy-pasted from the
  adjacent `MED_EDGE` entry `[0.15, 0.20, 0.25, 0.30, 0.35]` (MED_EDGE's
  real domain, confirmed via utils.py:233 `MED_EDGE` default 0.15 and
  utils.py:227 `STRONG_EDGE` default 0.30 — that scale is correct for
  MED_EDGE).
- But PAPER_MIN_EDGE's real domain is `[0.03, 0.15]` per: config.py's own
  walk-forward acceptance check (`0.03 <= float(opt) <= 0.15`), its
  hardcoded final default (0.05), and tests/test_param_sweep_load.py's own
  example values (0.05, 0.06, 0.07, 0.08, 0.09, 0.10).
- Net effect: the swept candidate list for PAPER_MIN_EDGE overlaps its own
  accepted output range at exactly one point (0.15). `load_swept_min_edge()`
  can therefore only ever return 0.15 (if it happens to have the best
  win-rate among the tested values with enough trades) or None — it can
  never discover/return any value in the actual meaningful range
  [0.03, 0.15), which is most of the parameter's real operating range
  (default is 0.05, three times lower than the sweep's lowest tested
  value).
- Reproduced (E2) in audit/reproductions/repro_pass20_param_sweep_scale_mismatch.py:
  500 synthetic trades with `net_edge` uniformly distributed across
  PAPER_MIN_EDGE's real domain [0.03, 0.16] (weak edge→win-rate
  correlation). Sweeping with the actual `run_sweep()` values
  `[0.15, 0.20, 0.25, 0.30, 0.35, 0.40]` yields:
  ```
  value=0.15  trades=41   win_rate=0.7561
  value=0.20  trades=0    win_rate=None
  value=0.25  trades=0    win_rate=None
  value=0.30  trades=0    win_rate=None
  value=0.35  trades=0    win_rate=None
  value=0.40  trades=0    win_rate=None
  ```
  vs. sweeping the parameter's own documented range
  `[0.03, 0.05, 0.07, 0.09, 0.11, 0.13, 0.15]`:
  ```
  value=0.15  trades=41   win_rate=0.7561
  value=0.13  trades=120  win_rate=0.7167
  value=0.11  trades=206  win_rate=0.7087
  value=0.09  trades=279  win_rate=0.6738
  value=0.07  trades=351  win_rate=0.6667
  value=0.05  trades=432  win_rate=0.6458
  value=0.03  trades=500  win_rate=0.6300
  ```
  Only the second set actually explores PAPER_MIN_EDGE's real domain; the
  first (what the code actually runs) can only ever surface the single
  boundary point.
- Severity assessment: fails soft, not a live-trading danger — worst case
  `load_swept_min_edge()` returns None and `_paper_min_edge_default()`
  falls back to the hardcoded 0.05 default (or walk_forward_params.json's
  own separate, correctly-ranged sweep, which is checked first and would
  mask this bug whenever walk-forward has already produced a value). But
  as run, `param_sweep.py`'s PAPER_MIN_EDGE auto-tune (the `param_sweep`/
  `main.py sweep` CLI path, independent of walk-forward) is a
  structurally-broken feature: it can never learn a PAPER_MIN_EDGE below
  0.15 no matter how much settled trade history accumulates.

No other findings reached the bar for reporting in the first sweep — the
rest of the sampled modules (circuit_breaker.py, kalshi_ws.py's ticker price
parsing — verified NOT a cents/dollars bug via tests/test_kalshi_ws.py
and the original phase-f plan doc, both confirming the WS "ticker"
message's `yes_bid` field is itself a dollar string, not legacy cents —
watchdog.py, cloud_backup.py, notify.py, feature_importance.py,
sigma_audit.py, backlog_index.py, market_types.py, acis_precip.py's
divide-by-len guards) were well-guarded or non-safety-relevant. The
`schtasks /Create ... shell=True` call in main.py (~line 9006) builds its
command from `sys.executable`/`Path(__file__)` (locally trusted, not
attacker-controlled) so it wasn't escalated to a finding.

## Session 2 — extended sweep (utils.py, colors.py, system_health.py,
schema_validator.py, ab_test.py, alerts.py, paper.py risk-gate functions,
trading_gates.py, execution_log.py, order_executor.py's `_place_live_order`)

### Finding: LiveTradingGate's risk-halt sub-checks are computed exclusively
from the paper ledger and never see live trading outcomes

- Files/symbols: trading_gates.py:72-110 (`LiveTradingGate.check()`),
  paper.py:626-635 (`is_paused_drawdown`), paper.py:2436-2454
  (`is_streak_paused`), paper.py:575-598 (`_drawdown_snapshot`),
  paper.py:2664-2696 (`get_daily_pnl`), paper.py:3383-3437
  (`get_unrealized_pnl_paper`), order_executor.py:1567-1577
  (`_place_live_order`'s gate call + separate execution_log check).
- Traced every function `trading_gates.LiveTradingGate.check()` calls before
  authorizing a live order: `is_paused_drawdown()`, `is_streak_paused()`,
  `is_daily_loss_halted(client)`, `is_accuracy_halted()`,
  `graduation_check()`. All except `is_daily_loss_halted` are called with NO
  `client` argument at all. Read each one's data source directly:
  - `is_paused_drawdown()` → `_drawdown_snapshot()` → `paper._load()` →
    `paper.DATA_PATH` (paper_trades.json). No execution_log/live data read
    anywhere in the call chain.
  - `is_streak_paused()` → `paper._load()["trades"]` directly. Same paper-only
    source.
  - `is_daily_loss_halted(client)` — the one sub-check that DOES accept
    `client` — still computes its `settled_pnl` term from
    `paper._load()["trades"]` (paper ledger only); the `client` argument only
    adds `get_unrealized_pnl_paper(client)`'s mark-to-market term, and that
    function's positions come from `paper.get_open_trades()` (again the paper
    ledger) — `client` is used solely to fetch current market quotes to price
    those paper positions, never to fetch real Kalshi positions/fills. So
    even the "live-aware" sub-check never reads execution_log.db.
  - `graduation_check()` reads `paper.get_performance()` + `tracker.py`'s
    Brier score — also paper-ledger/model-calibration based. Its docstring is
    explicit that this is by design ("Check if paper trading performance
    warrants going live"), so this piece is not itself miscategorized, but it
    means literally every sub-check in the aggregate gate except one is
    paper-only, and that one exception (`is_daily_loss_halted`) turns out to
    be paper-only too on closer read.
  - Real live realized-loss protection for *same-day* losses does exist, but
    lives elsewhere: `order_executor.py`'s `_place_live_order()` (the actual
    live-order placement function, reached by both `cmd_order` and the
    automated cron/`watch --auto --live` path per the cluster-A shared
    engine) separately checks `execution_log.get_today_live_loss()` — a real,
    execution_log-sourced counter — as its own step 1, AFTER calling
    `trading_gates.pre_live_trade_check()` as step 0. That check is genuinely
    live-aware. But `is_paused_drawdown()`/`is_streak_paused()` (multi-day
    drawdown-from-peak and consecutive-loss-streak) have no live-data
    equivalent anywhere in the codebase — grepped `order_executor.py` for
    `streak`/`drawdown` and the only hits are the same paper.py imports
    called with no live-side counterpart.
- Reproduced (E2) in
  `audit/reproductions/verify_pass20_gate_paper_only.py`: monkeypatches
  `paper.DATA_PATH` and `execution_log.DB_PATH` to files inside a throwaway
  `tempfile.TemporaryDirectory()` (never touches the real project `data/`
  directory — see project memory's "Worktree data dir gotcha"), seeds a
  perfectly healthy empty paper ledger (`balance == peak_balance ==
  STARTING_BALANCE`, 0 trades), then calls the real `execution_log.add_live_loss(95.0)`
  ten times (a genuine $950 realized loss recorded via the real production
  code path) to simulate 10 consecutive live losing trades. Output:
  ```
  execution_log.get_today_live_loss() after 10x $95 live losses = $950.00
  paper.is_paused_drawdown()  -> False
  paper.is_streak_paused()    -> False
  paper.get_balance()         -> 1000.0
  paper.get_peak_balance()    -> 1000.0
  ```
  Despite a real, execution_log-recorded $950 (95% of starting balance)
  live realized loss across 10 consecutive live trades, both drawdown and
  streak gates report clean because they only ever look at the (here,
  untouched) paper ledger.
- Root cause: `is_paused_drawdown()`/`is_streak_paused()` were written when
  paper.py's ledger was the only trade record in the system; they were never
  extended to also incorporate `execution_log.db` once live trading (and
  especially after `e5331a8d`, 2026-08-17, which explicitly stopped routing
  live fills into the paper ledger at all) became a separate, disjoint data
  store. Cluster D's fix (routing live fills to execution_log instead of the
  paper ledger) was correct and necessary for its own stated purpose
  (stopping phantom-position bugs), but as a side effect it also guarantees
  these two risk gates can now *never* see live losses through any path,
  including the accidental one that might have partially masked this before.
- Expected behavior: a real live account suffering a sustained drawdown or
  loss streak should have `LiveTradingGate.check()` refuse further live
  orders, the same way `is_daily_loss_halted`'s sibling check for same-day
  spend does via execution_log.
- Actual behavior: `is_paused_drawdown()`/`is_streak_paused()` (both part of
  the mandatory pre-live-order gate chain, and also called directly from
  `order_executor._auto_place_trades` for the shared cron/watch batch-trade
  path) are structurally blind to live trading performance. A live account
  could be on an arbitrarily long real losing streak or an arbitrarily deep
  real drawdown and neither gate would ever fire, as long as paper trading
  (which may run on different signals, timing, or fills) happens to look
  healthy.
- Financial risk: real — this is the multi-day/loss-streak layer of the live
  risk-management stack, sitting alongside (not replaced by)
  `execution_log.get_today_live_loss()`'s same-day-only protection. A slow
  bleed spread across many days (each day individually under the daily-loss
  cap) would go completely uncaught by any live-aware gate. Currently
  moot in this environment specifically because `LIVE_TRADING_ENABLED` is
  unset (dormant), but this is a structural code defect independent of
  today's env state — it activates the moment live trading is turned on.
- Related but distinct from the already-documented pass13_security.md
  finding about `paper.get_open_trades()`-sourced exposure caps
  (`MAX_CITY_DATE_EXPOSURE` etc.) also being blind to live positions — that
  finding is about position-sizing caps; this one is about the core
  authorization gate deciding whether to allow *any* further live order at
  all.
- Severity: HIGH. Confidence: HIGH. Evidence: E2 (reproduced with real
  production functions against synthetic, sandboxed data).
- Limitations: did not check whether any other, not-yet-found live-loss
  guard exists outside `order_executor.py`/`trading_gates.py`/`paper.py`
  that might independently catch a slow multi-day live bleed (e.g. an
  external monitoring/alerting cron job) — grepped `cron.py`/`main.py` for
  `execution_log` + `drawdown`/`streak` and found no hits, but did not
  exhaustively trace every scheduled job.

### Finding: schema_validator.py's boolean return values are discarded by
every caller — validation is logging-only, never gating

- Files: schema_validator.py:36 (`validate_market`), :125
  (`validate_forecast`), :173 (`validate_nws_response`); callers at
  kalshi_client.py:324, kalshi_client.py:343, nws.py:236,
  weather_markets.py:1524.
- All three validators return `bool` ("Returns True if valid, False if
  critical fields are missing/wrong type"), but every call site in
  production code (`kalshi_client.get_markets`/`get_market`,
  `nws._get_daily_forecast` or equivalent, `weather_markets`'s Open-Meteo
  daily-fetch helper) calls the function as a bare statement and discards
  the return value — only the internal `_log.warning()` calls have any
  effect. A market or forecast payload that fails validation (missing
  ticker, inverted bid/ask spread, wrong-typed forecast field) still flows
  on into the caller's normal processing exactly as if it had validated
  clean.
- This appears to be intentional per the module docstring ("Logs warnings
  on violations rather than crashing") rather than a functional regression,
  but the boolean return type invites the opposite assumption, and it means
  "validation" here provides pure observability (a WARNING line to search
  logs for) with zero actual protective effect — a caller relying on
  schema_validator to keep malformed data out of the pipeline would be
  wrong.
- Severity: LOW (by-design logging layer, not a gating regression;
  downstream code generally already defends itself with `.get()`
  defaults/None checks). Confidence: HIGH. Evidence: E1 (static read of
  every call site).
- Recommendation: either have the documented-as-defensive callers
  (`kalshi_client.get_markets`, the Open-Meteo fetch path) actually act on a
  `False` return (skip/flag the record), or rename/re-document the
  functions as pure logging helpers so future readers don't assume they
  gate anything.
