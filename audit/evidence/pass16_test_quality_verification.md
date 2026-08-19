# Pass 16 — Test Quality: independent verification notes

Session: verifier re-examining Section 28 raw findings. Repo root:
C:\Users\thesa\claude kalshi\.claude\worktrees\reverent-lumiere-f79c1f

## Finding 1 — accuracy-circuit-breaker admin override / live gate integration test gap
- Read trading_gates.py in full (140 lines). Confirmed `is_accuracy_halted` imported
  from `paper` (line 75) and called at line 107, inside try/except that fails closed.
- `grep -n 'patch("paper.is_accuracy_halted"' tests/test_trading_gates.py` -> exactly
  lines 38, 99, 114, 129, 158, 174, 189, 204, 450, 480 — matches claim precisely.
- `grep -rln 'ACCURACY_HALT_OVERRIDE|accuracy_override|accuracy-override' tests/*.py`
  -> only tests/test_risk_control.py and tests/conftest.py.
- `grep 'import trading_gates|LiveTradingGate|pre_live_trade_check' tests/test_risk_control.py`
  -> no matches; test_risk_control.py never touches trading_gates.
- Read paper.py L234-2625: is_accuracy_halted() itself reads
  _ACCURACY_HALT_OVERRIDE_PATH (same function trading_gates.py calls) — confirms the
  wiring claim (same function object) is real, not just asserted.
- CONFIRMED. No integration test exercises the override -> LiveTradingGate.check() path.

## Finding 2 — web_app.py CSRF header (X-Requested-With) untested in isolation
- Read web_app.py L160-209: `_check_auth` requires GET/HEAD/OPTIONS or
  X-Requested-With == "XMLHttpRequest" (L198-201), else 401. Matches description.
- Read tests/test_web_auth.py in full: `_basic_auth()` (L19-24) always bundles both
  Authorization and X-Requested-With. Every "without_auth" test (L28-47) omits
  Authorization entirely, not just the CSRF header. `test_halt_with_wrong_password`
  (L68) also uses the bundled helper. No test isolates "correct password, no CSRF
  header" and asserts 401.
- Same `_basic_auth` pattern confirmed in tests/test_p0_16_cron_endpoint.py.
- CONFIRMED.

## Finding 3 — frontend authHeader() CSRF header untested
- Read frontend/src/useData.js L1-45: authHeader() (L29-41) always includes
  X-Requested-With.
- Grepped frontend/src/useData.test.js (276 lines) for "Requested" (case-insensitive)
  -> ZERO matches, not even in a comment. The original finding's evidence text ("only
  appears in a code comment") is itself slightly inaccurate — the string doesn't
  appear anywhere in the test file, which if anything is *stronger* support for the
  finding's conclusion (no coverage at all), not weaker.
- Core claim (no unit test asserts the CSRF header's presence in authHeader()'s
  output) CONFIRMED; evidence-level correction noted above.

## Finding 4 — misleading docstring in test_full_exit_race_loss_does_not_crash_the_caller
- Read tests/test_live_execution.py L2900-2961: docstring and assertion match exactly
  as quoted (L2915-2925 docstring, L2955-2956 "must not raise... report success
  either" / `assert result is True`).
- Read order_executor.py L1136-1373: LivePositionStore.exit() (L1161) calls
  _exit_live_position and returns its bool. _check_live_position_exits (L1376-1445)
  calls store.exit() at L1429 and L1445 and discards the return both times — matches
  the finding's claim for THAT function.
- HOWEVER: found a second, separate caller the original finding did not examine —
  _check_live_model_exits (L1448-1536) calls `_exit_live_position` DIRECTLY (not via
  store.exit()) at L1523: `if _exit_live_position(client, pos, exit_price,
  "model_exit", cycle): closed += 1` plus an info log. This DOES branch on the
  True/False return, contradicting the finding's broader claim ("the True/False
  contract has no current caller that branches on it"). In the specific race-loss
  scenario (True returned after a caught RuntimeError, L1365), this caller would log
  "%s %s closed..." and increment the returned `closed` count — not exactly a false
  "success" report (the position genuinely is closed, just by a different writer/
  reason than "model_exit" implies), but it is a real consumer of the return value
  that the finding's supporting evidence missed.
- Net effect: the core documentation observation (docstring overstates what's proven)
  still stands, but the finding's supporting "no consumer of the return value exists"
  claim is factually incomplete. Downgrading confidence from HIGH to MEDIUM and status
  from INFO/CONFIRMED to CONFIRMED-with-correction.

## Finding 5 — high test-writing discipline observation
- Re-ran both cited commands this session:
  - `py -m pytest tests/test_trading_gates.py tests/test_risk_control.py -q` -> 67
    passed in 15.97s. Matches claim exactly.
  - `py -m pytest tests/test_positions.py tests/test_web_auth.py
    tests/test_p0_16_cron_endpoint.py -q` -> 27 passed in 5.81s. Matches claim exactly.
- CONFIRMED, E2 (directly reproduced this session).

## Cross-check for Finding 3 (cmd_order multi-open-live-position, "sell" branch)
(Numbered 4th in the input JSON array, listed after CSRF findings above in this file
for grouping convenience.)
- Read main.py L4580-4630: confirms _live_open_matches list build, `[0]` taken as
  the "oldest" close target, warning printed when len > 1 (L4611-4630), matches
  description closely.
- `grep -n "ORDER BY placed_at" execution_log.py` -> L553 inside
  get_filled_unsettled_live_orders(), ascending (no DESC) — confirms `[0]` really is
  the oldest by placed_at.
- Grepped tests/test_trading_gates.py and tests/test_live_execution.py for
  "oldest"/"_live_open_matches"/"multiple.*tracked live" -> no matches in either file.
  TestCmdOrderLiveRecording only has test_live_sell_closes_matching_tracked_position
  (single match) and test_live_sell_with_no_matching_position_... (no match) — no
  multi-match test.
- CONFIRMED.
