# Pass 19 — Regression (Scope C) — re-run

This session re-ran Pass 19 independently. A prior pass19_regression.md
already existed in this audit tree (same pass key) with one MEDIUM finding
(cmd_order exposure-cap blind spot from e5331a8d) and one TEST_GAP finding.
Both were independently re-verified this session (still true at HEAD,
2026-08-17, commit d190d09d) with fresh evidence, and are restated below
alongside one new finding this session surfaced (settlement-monitor
force-close chain). This file supersedes the prior version at the same path.

## Finding 1 (re-verified): cmd_order live-buy exposure-cap protection regressed by e5331a8d

`paper.check_position_limits()` (paper.py:3447) is the shared enforcement
point for city/date/directional/correlated-group exposure caps on every
manual order path (cmd_order, cmd_paper, web_app /api/paper-order) per its
own docstring. Grepped paper.py:3447-3650 directly this session: its
`existing_cost` computation (paper.py ~3629) sums exclusively over
`get_open_trades()` (the paper_trades.json ledger) — zero references to
`execution_log` anywhere in the function body, confirmed at HEAD.

Before e5331a8d (2026-08-17), cmd_order's live buy fills were recorded
unconditionally via `paper.place_paper_order()` — the fix's own target bug
(the fill was invisible to the automated protective-exit scanner). A side
effect of that pre-fix bug was that the live buy's cost WAS counted by
`check_position_limits()` on any subsequent `cmd_order` call, since it
landed in the same ledger the exposure math reads. e5331a8d correctly
routes live fills through execution_log instead, but `check_position_limits`
was not updated to also read execution_log — so a real live position placed
via `cmd_order` is now invisible to this exposure gate, whereas before the
fix it was accidentally counted.

The commit's own message documents this explicitly as one of two
deliberately-not-fixed-here follow-ups ("paper.check_position_limits'
exposure caps never read execution_log for real live positions"), and it is
tracked in backlog.txt. This is a real regression in gate effectiveness
introduced as a side effect of an otherwise-correct fix, not merely a
pre-existing, always-blind gap — before e5331a8d this exact scenario
(repeated `cmd_order` live buys on the same city/date/side) WAS caught.

Severity: MEDIUM. Requires deliberate repeated manual `cmd_order` live
calls by the operator (not reachable from cron/watch's automated
`_auto_place_trades`, which uses its own Kelly/exposure sizing). Does not
bypass the master `trading_gates.LiveTradingGate` chain. Cannot be
exploited from this worktree (no `.env`/credentials present).

## Finding 2 (re-verified, TEST_GAP): no test covers check_position_limits vs execution_log interplay

`grep -rl check_position_limits tests/ | xargs grep -l execution_log` still
finds no test file at HEAD. Despite e5331a8d's large test addition (188
new/changed tests across main.py/order_executor.py/execution_log.py plus
tests/test_trading_gates.py, 470 new lines), none of that coverage asserts
or documents this specific interaction, matching what the commit's own
message frames as a known, filed gap rather than a fixed one.

## Finding 3 (new this session): settlement-monitor force-close chain (64c08693 -> d320142d) has never actually activated in production, and its own follow-up commit found the gate is mathematically unreachable under the current model

Two commits in the audited window build one feature chain:
- `64c08693` (2026-08-10) added `cmd_schedule()` registration of a 4th daily
  schtasks task to actually invoke `py main.py settlement-monitor`, and
  widened cron.py's staleness window for settlement-lag signals from 120min
  to 720min (cron.py ~L1444) specifically to accommodate it.
- `d320142d` (2026-08-16) then wired METAR calibration into
  `cron.py`'s `_sig_conf >= 0.80` T-ticker force-close gate (confirmed at
  cron.py:1471, unchanged at HEAD), reusing the entry-path calibration
  model.

`d320142d`'s own commit message (verified by its authors, re-verified this
session against backlog.txt L1-55) states two things directly relevant to
regression scope:

1. **The scheduled task registered by 64c08693 has never actually run in
   production** — confirmed by the commit's own investigation via
   `data/cron.log` (1.8MB, zero "SETTLEMENT LAG signal" lines) and
   `schtasks /Query /TN KalshiWeatherSettlementMonitor` (task not
   registered on the operator's machine). `cmd_schedule()` is a manual,
   idempotent-per-run CLI command (`py main.py schedule`) — grepped main.py
   and web_app.py this session for any auto-registration, startup check, or
   dashboard surface that would either register the task automatically or
   warn the operator it's missing; found none. The feature shipped as code
   but activation depends on a manual step the operator has evidently not
   performed since 08-10, six days before 08-16's follow-up commit and
   still true through 08-17's HEAD.
2. **Once wired, the calibrated force-close gate can never fire under the
   currently-fitted model**: `metar._dynamic_lock_in_confidence()` is
   hard-bounded to [0.72, 0.97]; run through the fitted calibration model
   across that entire input range the commit found calibrated output never
   exceeds ~0.766 (YES-lock) / ~0.595 (NO-lock) — both permanently below
   cron.py:1471's `>= 0.80` threshold. Independently re-verified this
   session only by reading cron.py:1471 directly (confirms the `0.80`
   literal is unchanged at HEAD); did not re-run the calibration sweep
   itself (E1, relying on the commit's own hand-verified math, not
   independently re-executed this session).
3. Separately noted by the same commit: the calibration model is fit on
   `weather_markets._metar_lock_in()` rows (`margin_f=3.0`, daily running
   extreme) but applied to `settlement_monitor.py`'s T-ticker path, which
   calls the same underlying function with `margin_f=1.0` against the
   *instantaneous* reading — a different population than the one the model
   was trained on, an extrapolation rather than a like-for-like correction.

Net effect: this is a two-commit feature chain in the audited window where
the second commit both extends and simultaneously documents that the
mechanism it's extending is inert (never scheduled) and, even if scheduled,
would be mathematically unable to trigger its own gate. Not an active
regression in the sense of "used to work, now broken" — by the commits'
own account it has never worked in production — but it is a real instance
of committed, tested functionality (feat commits, real test files) building
on an inactive dependency without any runtime signal that the dependency is
inactive. This matches this audit's cluster-K-adjacent pattern (a
multi-commit chain whose later commits assume the earlier commit's
precondition holds) and is already self-filed as an open, Low-priority
backlog entry — not a hidden defect, but confirmed still true at HEAD this
session via direct source read (cron.py:1471) and the backlog.txt entry's
own re-readable evidence trail.

Severity: LOW (self-documented, Low-priority, no live-order or fund-safety
impact — this only ever gated a *paper*-position force-close signal, and
the master `trading_gates.LiveTradingGate` chain is entirely independent of
it). Filed as ARCHITECTURAL_CONCERN / RELIABILITY rather than a fresh bug,
since the codebase's own commit history already surfaces and tracks it.

## Areas checked this session with no regression found

- **execution_log partial-exit settlement (105cf4ce)**: verified
  `record_live_exit_fill` (execution_log.py:734-804) computes each exit's
  P&L strictly from that exit's own `clamped_fill_count`, not the
  position's original quantity — no double-counting risk when a position
  closes across multiple partial IOC fills before a final full exit.
  `export_live_tax_csv`'s new self-join (execution_log.py ~672) correctly
  excludes a FULL exit order's own row (settled_at stays NULL on it,
  filtered out) so it can't double-count against the position row that
  fixed branch settles instead.
- **get_live_pnl_summary (execution_log.py:894)**: confirmed unchanged and
  correctly picks up 105cf4ce's newly-settled partial-exit rows via its
  existing `WHERE live=1 AND settled_at IS NOT NULL AND pnl IS NOT NULL`
  filter — matches the commit's own "needed no changes" claim.
- **positions.py pricing consistency (fc8e3555 + c6288b9c)**: verified
  `check_stop_losses`/`check_breakeven_stops`/`update_peak_profits`
  (positions.py:184-294) already used `liquidation_price()` before
  c6288b9c, and c6288b9c brought `_check_early_exits` (paper model-exit)
  and main.py's manual exit-signal close menu into the same convention —
  no cross-path pricing-convention divergence found among stop-loss/
  breakeven/peak-profit/model-exit paths (only the already-tracked,
  separately-fixed React-dashboard close button, ee22c44c, lagged behind).
- **monte_carlo.py city-local date fix (6364b38b)**: diff reviewed in full;
  correct per-city ZoneInfo lookup via `weather_markets._CITY_TZ` with a
  logged UTC fallback on exception, mirrors `analyze_trade`'s established
  pattern; defaults to America/New_York when a trade dict has no `city`
  key. No regression found.
- **d190d09d far-tail climatology blend**: confirmed shadow-only per its
  own commit message and code read (weather_markets.py — new branch only
  populates `forecast_blend_signal` / logged metadata; `blended_prob`,
  `rec_side`, and sizing are untouched by this block). Not a live-trading
  regression candidate.
- **cron.py signal-banner accuracy (d37a3e04) vs later STRONG/MED
  validate()-gate hardening (c9b0fc02)**: read trade_cycle.py's own
  docstring (~L143-162), which explicitly documents that `strong_opps`/
  `med_opps` (the banner's "found" count) already include only candidates
  that clear the validate() edge gates — i.e. c9b0fc02's gate hardening and
  d37a3e04's "found vs placed" banner semantics are consistent by design,
  not accidentally divergent.
- **Live-fill routing coverage beyond cmd_order (cluster D)**: enumerated
  every `client.place_order(` call site in main.py/order_executor.py. The
  `ENABLE_MICRO_LIVE` automated path (order_executor.py ~3253-3282) already
  logs via `execution_log.log_order`/`log_order_result`, not
  `paper.place_paper_order` — this path predates the audited window's
  cluster-D fixes and was not regressed by them. (Noted in passing: this
  micro-live path's own gate, `_micro_live_gate_ok`, calls only
  `trading_gates.pre_live_trade_check` — no `check_position_limits` call at
  all, so it has no city/date/directional exposure cap of its own either;
  this is pre-existing and unchanged by any of the 53 audited commits, so
  out of scope for a *regression* finding, not filed as one.)
- **web_app.py /api/close-position (cluster F)**: confirmed by direct code
  read (web_app.py:2965-3007) that this route's own docstring documents
  paper-only scope, and `/api/trades` (web_app.py:1398), the only
  positions-list source the React dashboard's Close button acts against,
  reads exclusively from `paper.get_open_trades()` — never execution_log.
  No live-position dashboard-close path exists at all (matches recon's note
  that live-position management stayed CLI-only); not a new gap introduced
  by ee22c44c/d47b59d3.
- **Admin accuracy-override reachability (251e838e)**: grepped main.py and
  web_app.py for any web route wiring to `override_accuracy_halt` — none
  found; confirmed CLI-only as the commit intends.
