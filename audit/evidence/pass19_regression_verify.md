# Pass 19 — Regression: independent verification notes

## Finding 1: check_position_limits() blind to execution_log live positions

Read paper.py:3447-3692 (full check_position_limits body) and the exposure
helpers it calls: get_open_trades (paper.py:1299-1301), get_city_date_exposure
(1598-1605), get_directional_exposure (1608-1617), get_total_exposure
(1620-1623), get_ticker_exposure (1626-1629), get_correlated_exposure
(1654-1673). All exclusively sum over get_open_trades(), which reads
`_load()["trades"]` — paper.py's own JSON ledger. `grep execution_log
paper.py` returns 4 hits, none inside check_position_limits or any exposure
helper (just comments elsewhere).

Confirmed main.py cmd_order's buy-path call site (main.py:4539-4576) calls
paper.check_position_limits() directly, with a comment block explicitly
citing the same regression ("previously enforced on the auto-trade and
_quick_paper_buy manual paths but not here...").

backlog.txt:1994-2049 contains a codebase-authored entry ("paper.
check_position_limits' EXPOSURE CAPS ARE STRUCTURALLY BLIND TO REAL LIVE
POSITIONS") that independently corroborates essentially the entire finding,
including: the exact pre-fix/post-fix behavior change for cmd_order, that
order_executor._auto_place_trades' automated live path has ALWAYS been
blind (branches live/paper as mutually exclusive if/else, order_executor.py
~2966/~3014), and an empirical note that this is "moot today" because zero
live=1 rows have ever existed in execution_log. This last point supports
the finding's own "financial_risk" framing (real but currently unexploitable
given this worktree/current production state) and its self-assessed
Medium severity (backlog.txt independently also says Priority: Medium).

Verdict: CONFIRMED. Evidence level E1 (direct static source read across
paper.py + main.py + backlog.txt cross-corroboration), consistent with the
original finding's own E1 rating. Did not re-run repro_exposure_blind.py
this session (script not independently executed), so not elevated to E2.

## Finding 2: no test coverage for the check_position_limits/execution_log gap

Re-ran the finding's own evidence command:
`grep -rl check_position_limits tests/ | xargs grep -l execution_log`
→ returns `tests/test_hurricane_gating.py` (NOT empty, contradicting the
finding's literal claim "returns no files at HEAD").

Inspected the match (test_hurricane_gating.py:352-478): the file's
`execution_log` reference is an unrelated monkeypatch of
`execution_log.was_recently_ordered` inside a duplicate-order-guard test:
it has nothing to do with exposure caps or live-position visibility to
check_position_limits(). No assertion anywhere in that file (or the other
7 files matching check_position_limits) exercises check_position_limits()
against an execution_log-tracked live position.

Verdict: CONFIRMED (the substantive claim — no test covers this
interaction — holds), but the finding's cited grep evidence is factually
inaccurate as stated (it does return one file, just a false-positive
coincidental match). Downgraded confidence from HIGH to MEDIUM and flagged
the evidence inaccuracy explicitly.

## Finding 3: settlement-monitor force-close chain never activated / unreachable gate

Confirmed cron.py:1471 literal is still `_sig_conf >= 0.80` at HEAD
(unchanged). Confirmed the block only calls `paper.close_paper_early`
(cron.py:1455, 1482) against `paper.get_open_trades()` — paper positions
only, not live; corroborates the finding's "financial_risk: None" claim.

backlog.txt:1-60 contains a matching self-authored entry with identical
specifics: `data/cron.log` shows zero "SETTLEMENT LAG signal" lines ever,
`schtasks /Query /TN KalshiWeatherSettlementMonitor` shows the task is not
registered, and a hand-verified calibration sweep giving max calibrated
confidence 0.7661 (YES) / 0.5954 (NO), both < 0.80.

Confirmed cmd_schedule() (main.py:8962+) requires a manual, non-idempotent
operator re-run (`py main.py schedule`) to register schtasks entries
(including the settlement-monitor task at main.py:9143-9184), and grepped
web_app.py for any "schtasks"/"SettlementMonitor" reference — zero matches,
supporting the "nothing auto-registers or health-checks this task" claim.

Verdict: CONFIRMED. Evidence level E1 (static source read; did not
independently re-run the calibration sweep or query schtasks on this
machine — matches the finding's own stated limitation).
