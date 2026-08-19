# Pass 20 — Unrelated Discovery (Scope D & Section 33) — Independent Verification

Re-examined 3 raw findings against current code (not the original pass's own description). All three CONFIRMED.

## Finding 1 — LiveTradingGate drawdown/streak checks blind to execution_log

- Read trading_gates.py (full file, 140 lines): `LiveTradingGate.check()` calls `paper.is_paused_drawdown`, `paper.is_streak_paused`, `paper.is_daily_loss_halted(client)`, `paper.is_accuracy_halted`, `paper.graduation_check` — confirmed none but `is_daily_loss_halted` accept `client`.
- Read paper.py: `_drawdown_snapshot()` (L575-598) reads only `_load()["balance"/"peak_balance"/"trades"]` (paper_trades.json). `is_paused_drawdown` (L626-635), `is_streak_paused` (L2436-2454) both confirmed paper-ledger-only, no execution_log reference.
- `is_daily_loss_halted(client)` (L2723-2754) -> `get_daily_pnl(client)` (L2664-2696): settled_pnl term sums `_load()["trades"]` (paper ledger); client is only used for `get_unrealized_pnl_paper(client)` MTM add-on.
- `get_unrealized_pnl_paper(client)` (L3383+) confirmed: iterates `get_open_trades()` (paper.py's own open trades), uses `client` solely to fetch market quotes for repricing those paper positions — never reads execution_log.
- Also confirmed order_executor.py `_auto_place_trades` (L2294+, shared by cron/watch for BOTH paper and live) independently calls the same paper-only `is_paused_drawdown()`/`is_daily_loss_halted(client)`/`is_streak_paused()` — this broadens the blind spot beyond just the `LiveTradingGate.check()` call path.
- execution_log.py confirmed to have its own separate `get_today_live_loss()`/`get_today_live_spend()`/`add_live_loss()` (L415-488+), never consulted by any of the above.
- **Independently re-ran** `audit/reproductions/verify_pass20_gate_paper_only.py` this session (E3, not just re-read): script uses only a `tempfile.TemporaryDirectory()`, monkeypatches `paper.DATA_PATH`/`execution_log.DB_PATH` at the attribute level, never touches real project data. Output:
  ```
  execution_log.get_today_live_loss() after 10x $95 live losses = $950.00
  paper.is_paused_drawdown()  -> False
  paper.is_streak_paused()    -> False
  paper.get_balance()         -> 1000.0
  paper.get_peak_balance()    -> 1000.0
  ```
  Confirms: a synthetic $950 (95%) real live loss is completely invisible to both risk halts.

**Status: CONFIRMED. Confidence: VERY HIGH. Evidence: E3** (own re-run this session, on top of static trace).

## Finding 2 — schema_validator.py return values discarded everywhere

- Grepped every call site of `validate_market`/`validate_forecast`/`validate_nws_response` repo-wide (excluding graphify-out/docs cache and tests).
- Confirmed 4 production call sites, all bare statement calls (no assignment, no `if`):
  - kalshi_client.py:324 (`get_markets`, inside pagination loop)
  - kalshi_client.py:343 (`get_market`)
  - nws.py:236 (daily forecast fetch)
  - weather_markets.py:1525 (Open-Meteo daily-fetch helper)
- Read schema_validator.py header docstring: confirms bool return signature ("Returns True if valid...") is real, and functions are documented as intentionally logging-only ("Logs warnings on violations rather than crashing").
- No additional production call site found beyond the 4 already cited; `tests/test_phase2_batch_l.py`'s `validate_market` reference is a test-only wrapper, not a production path.

**Status: CONFIRMED. Confidence: HIGH. Evidence: E1** (static grep + direct read, same as original — no dynamic repro needed for "return value discarded", it's directly visible in the syntax).

## Finding 3 — param_sweep.py PAPER_MIN_EDGE sweep/accept-range mismatch

- Confirmed current code: `param_sweep.py:166` `params_to_sweep["PAPER_MIN_EDGE"] = [0.15, 0.20, 0.25, 0.30, 0.35, 0.40]`; `load_swept_min_edge()` (L102-129) only returns a value when `0.03 <= val <= 0.15`, else implicitly falls through to `return None`. Only overlap point is exactly 0.15 — confirmed by direct read.
- **Re-ran** `audit/reproductions/repro_pass20_param_sweep_scale_mismatch.py` this session (E3): confirms mechanically that of the 6 shipped sweep values, only 0.15 ever returns a populated result (`trades=41`), and 0.20-0.40 always return `trades=0, win_rate=None` — structurally unelectable by `load_swept_min_edge()`'s clamp regardless of outcome quality.
- **Root-cause nuance (correction to the raw finding):** `git log -L160,170:param_sweep.py` shows this was NOT an accidental copy-paste. Commit `b476092` (2026-06-07, "Fix 4 bugs...") *deliberately* changed `PAPER_MIN_EDGE` from `[0.03..0.15]` to `[0.15..0.40]` "to match the actual net_edge scale," with an inline comment added in the same commit explicitly acknowledging `load_swept_min_edge()`'s `[0.03,0.15]` clamp and calling it a safety valve ("so auto-tuned values fed back into PAPER_MIN_EDGE config stay in the safe range regardless of which threshold wins here"). So the author was aware of the clamp's existence but the practical consequence (0.15 is the *only* value that can ever be both tested and accepted) does not appear to have been the intended design — it reads as an overlooked side effect of a deliberate scale change, not a blind copy/paste. The raw finding's "apparent copy-paste error between two adjacent dict entries" root-cause line is not well supported by the commit history and should be treated as speculative; the functional bug claim itself is accurate and independently reproduced.
- **Materiality caveat:** `param_sweep.py`'s own docstring (and the June 7 commit message) state real recorded `net_edge` values in this codebase's paper trades sit in the 0.15–0.87 range (a return-on-capital-style metric — `weather_markets.py:7843` `net_edge = min((net_ev/entry_price)*time_decay, 3.0)` — not the same quantity/scale as a raw probability-edge). `get_paper_min_edge()` itself is hard-capped to `min(x, 0.05)` (utils.py:72, "must be <=5% per system requirements"). If real net_edge values genuinely cluster >=0.15 as documented, then sweeping the sub-0.15 region may have limited practical value even if it worked (most/all trades would trivially pass any threshold that low) — so the finding's "silently non-functional across most of its intended range" framing is technically true of the mechanism, but its practical bite may be smaller than implied. This does not change the underlying code defect, only its real-world severity.

**Status: CONFIRMED (mechanism), root-cause characterization downgraded. Confidence: HIGH. Evidence: E3** (own re-run this session).
