# Pass 16 -- Test Quality (Section 28)

Scope: tests covering the 53 recent feat/fix/refactor commits (2026-08-02..08-17),
esp. test_live_execution.py, test_trading_gates.py, test_positions.py,
test_ml_bias.py, test_risk_control.py, test_trade_cycle_engine.py,
test_cron_integration.py, test_execution_log.py, test_settlement_monitor.py,
test_rain_markets.py, tests/conftest.py, frontend/src/useData.test.js,
tests/test_web_auth.py, tests/test_p0_16_cron_endpoint.py.

## Overall impression

Test-writing discipline in this window is unusually high: commit messages
routinely describe opus-review rounds catching real bugs in the tests
themselves (vacuous assertions, wrong-orientation math, insufficiently
narrow boundary pins), and several tests document mutation-testing results
inline ("mutation-verified: `<= 14`, `<= 16`, and `<= 25` all previously
passed the full suite unnoticed"). Verified positive controls exist for
several regression tests (e.g. TestCmdOrderLiveRecording's demo-mode
sibling tests proving the paper-ledger branch is still reachable, so the
live-mode "no paper trade" assertion isn't vacuously true). Ran
tests/test_trading_gates.py, tests/test_risk_control.py, tests/test_positions.py,
tests/test_web_auth.py, tests/test_p0_16_cron_endpoint.py directly this
session (E2) -- all pass (67 + 27 = 94/94).

Despite that baseline, several concrete coverage gaps were found where a
recent commit's own stated risk is not actually exercised end-to-end by
any test, only unit-tested in isolation with the risky integration point
mocked away.

## Findings summary

1. Accuracy-circuit-breaker admin override (251e838e) is unit-tested
   against paper.is_accuracy_halted() and separately against
   trading_gates.LiveTradingGate.check() with is_accuracy_halted mocked
   out -- never tested with a real override file active through the real
   gate chain, despite the commit's own docstring/message stating the
   override "silently lifts the LIVE-order gate."

2. web_app.py's CSRF mitigation (X-Requested-With header, 0edf818b) has no
   test that sends correct Basic Auth credentials WITHOUT the CSRF header
   and asserts 401/rejection -- every "auth succeeds" test bundles both
   headers together via a shared `_basic_auth()`/`_auth` helper. The
   security-relevant branch (`_check_auth`'s `... or (X-Requested-With ==
   "XMLHttpRequest")` gate) is therefore never independently exercised.
   Confirmed via source read of web_app.py:166-209 that a request with
   valid Basic Auth and no X-Requested-With header hits the final `return
   Response(..., 401, ...)`.

3. frontend/src/useData.js's authHeader() helper (same 0edf818b fix) has
   no direct unit test asserting the X-Requested-With header is present in
   its return value, despite this being the exact header the bug (L18070)
   was missing on one of the two frontend trees.

4. main.cmd_order's live-sell "multiple tracked live positions share the
   same ticker+side" branch (e5331a8d, main.py's `_live_open_matches`
   multi-match warning) has zero test coverage -- neither the warning
   message nor the "closes exactly the oldest (`placed_at`-ascending)
   position, leaves the rest open and untouched" behavior is asserted
   anywhere in tests/test_trading_gates.py or tests/test_live_execution.py.

5. (Informational / already fixed, logged for completeness) tests/test_live_execution.py's
   test_full_exit_race_loss_does_not_crash_the_caller docstring claims to
   verify the caller "must not silently report success either," but the
   test body asserts `result is True`. This isn't a bug -- `_exit_live_position`'s
   True/False return means "the exchange fill itself succeeded," not
   "our bookkeeping succeeded," and the return value is discarded by every
   current caller (order_executor.py:1429/1445, `store.exit(...)` results
   unused) -- but the docstring's phrasing is misleading about what the
   test actually proves, and the return-value contract it pins has no
   consumer today.

## Positive/negative controls verified present
- e5331a8d's TestCmdOrderLiveRecording class: real end-to-end
  main.cmd_order() calls against a real (tmp) execution_log DB and real
  paper.get_all_trades(), covering live buy / demo buy positive-control /
  partial fill / live sell closing a tracked position / live sell with no
  match / IOC time_in_force / zero-fill cancel / close_time+entry_prob
  propagation. This is genuinely strong, non-mocked-to-uselessness
  coverage of the highest-stakes recent change.
- test_cron_integration.py / test_trade_cycle_engine.py both now stub
  trade_cycle._run_batch_prewarm (confirmed via grep, both fixtures
  present) -- the "4th known instance" of a real-network leak documented
  in 0c31fdd8/4fbcdfd7 is fixed and stays fixed.
