# Pass 3 — Requirements: Independent Verification

Verifier re-examined all 5 raw findings against current code (not the findings' own descriptions).

## Finding 1 — check_position_limits() exposure caps blind to live cmd_order positions
- Read paper.py:3447-3686 (check_position_limits full body) directly. Confirmed: per-market cap
  (existing_cost, L3629-3633), global cap (get_total_exposure, L3645), and city/date/directional/
  correlated caps (L3653-3685) all derive solely from get_open_trades() (paper.py:1299-1301),
  which reads only `_load()["trades"]` (paper_trades.json). No other data source is consulted.
- Confirmed main.py:4528 `_is_live = getattr(client, "base_url", None) != DEMO_BASE` and
  main.py:4546-4569 cmd_order buy path calling `check_position_limits()` exactly as claimed.
- Grepped `_get_live_open_positions` repo-wide (50 files, mostly docs/graphify/tests) — confirmed
  it is used only in cmd_order's live-sell matching (main.py) and exit-gate logic (positions.py,
  order_executor.py), never fed into check_position_limits or any of the exposure-getter
  functions. No refutation found.
- Independently re-ran the pre-existing audit/scratch/repro_exposure_blind.py this session.
  Output reproduced exactly as claimed: after simulating an execution_log-only (post-e5331a8d)
  prior live buy, a second live buy on the same city/date/side reports
  `{'ok': True, 'reason': None, 'existing_cost': 0, 'limit': 250.0}`.
- Verdict: CONFIRMED. E2 (reproduced this session, script re-executed and read).

## Finding 2 — startup banner wrongly claims only `watch --auto --live` can place live orders
- Read main.py:9558-9587 directly. `_live_orders_possible = cmd == "watch" and "--auto" in args
  and "--live" in args` (L9567) and the false-claim print at L9578 match the finding exactly,
  current line numbers included.
- Confirmed cmd_order's independent live-order path (main.py:4528-4537) is real and unconditioned
  on `_live_orders_possible` — it derives its own `_is_live` and calls pre_live_trade_check
  directly, so `py main.py order buy ...` against prod really can place a live order despite the
  banner's claim.
- Cross-checked backlog.txt: entries at L1620-1622 and L1960-1999 independently document this
  exact gap (referencing `_live_orders_possible`, `cmd == "watch"`, broadening to `cmd in ("buy",
  "sell")`), corroborating this is a known, still-open item, not a fabricated claim.
- Verdict: CONFIRMED. E1 (static read; this is a startup-banner code path requiring
  KALSHI_ENV=prod + live credentials to execute, unavailable in this worktree — matches the
  finding's own honest E1 self-rating).

## Finding 3 — METAR settlement-lag force-close gate structurally unreachable
- Read cron.py:1440-1480: confirmed `_sig_conf >= 0.80` gate at L1471 exactly as cited.
- Read settlement_monitor.py:277-340 (_calibrate_metar_settlement_confidence): the function's own
  docstring already states the 0.7661/0.5954 ceiling finding almost verbatim (this is clearly
  self-documented in-repo, not novel to this audit pass, but that does not make it false).
- Independently re-ran audit/reproductions/metar_calibration_bound_check.py this session (a
  from-scratch reimplementation, not importing ml_bias.py). Output matched exactly: max YES-lock
  0.7661 at raw=0.97, max NO-lock 0.5954 at raw confidence=0.97, "Gate reachable under this fit:
  False".
- Verdict: CONFIRMED. E2 (reproduced this session). Note for pass_summary: this is essentially a
  re-statement of an already-self-documented, already-backlogged finding (backlog.txt L4/near
  settlement_monitor.py's own docstring) — real and correctly rated LOW severity given the
  mechanism has never actually run against real trades per the docstring's own cron.log/schtasks
  citation, which this pass did not independently re-verify (schtasks/cron.log unavailable to
  re-check meaningfully in this worktree).

## Finding 4 — live cmd_order sell only closes oldest of N>1 tracked positions
- Read main.py:4577-4630 directly. Confirmed the exact code, comment ("Opus review (2026-08-17),
  NEW-M1..."), and warning-print logic described in the finding, matching almost verbatim
  (finding's quoted comment text is a faithful transcription of the actual code comment).
- Verdict: CONFIRMED. E1 (static read, matches finding's own rating).

## Finding 5 — AMBIGUITY: no spec for N>1 live-sell-match behavior
- Grepped tests/test_live_execution.py and tests/test_trading_gates.py for
  oldest/_live_open_matches/"multiple...live...position" patterns — no matches in either file,
  confirming no test asserts a specific behavior for the N>1 scenario. Broader repo-wide grep for
  "oldest" in tests/ matched only unrelated files (test_tracker.py, test_paper.py, etc., false
  positives on the word "oldest" in unrelated contexts).
- Verdict: CONFIRMED as an honest ambiguity finding (i.e., the absence-of-spec claim itself holds
  up). E1, matching finding's own rating.

## Summary
All 5 findings survive independent verification. Two (1 and 3) were independently re-executed
via their pre-existing reproduction scripts with matching output. None were disproven or
downgraded. Finding 3 gets a verification-note caveat that it is largely a re-statement of an
already-self-documented in-code/backlog finding, which does not reduce its correctness but
reduces its novelty.
