# Pass 16 — Test Quality: Independent Verification Notes

Verifier session, re-examining the 4 raw findings from Pass 16 against current code.
Did not trust the original pass's own description; re-derived each claim from source.

## Finding 1 — CSRF X-Requested-With rejection branch untested — CONFIRMED

- `grep -n "X-Requested-With" web_app.py` → only web_app.py:199 (inside `_check_auth`).
- `grep -rln "X-Requested-With" tests/` → only `tests/test_web_auth.py` and
  `tests/test_p0_16_cron_endpoint.py`, and both files' header-builder helpers
  (`_basic_auth`, `_auth_headers`) unconditionally set the header.
- Ran `python -m pytest audit/reproductions/test_csrf_header_gap_repro.py -q`
  myself this session → 1 passed. Confirms production code correctly 401s a
  correct-password request missing the CSRF header today, and that this exact
  assertion is genuinely absent from the shipped suite.

## Finding 2 — V_3 frontend tree has zero test coverage — CONFIRMED

- `find frontend -iname "*.test.*"` → `frontend/src/useData.test.js` only.
- `find "weather app site V_3 (3)" -iname "*.test.*"` and `-iname "package.json"`
  → both empty. Tree has no build/test infra at all.
- `git show d47b59d3 --stat` → touches only
  `weather app site V_3 (3)/src/tabs/PositionsTab.jsx`.
- `git show 0edf818b --stat` → 4 V_3-tree files changed (useData.js,
  PositionsTab.jsx, AnalyticsTab.jsx, OverviewTab.jsx) alongside
  `frontend/src/useData.js` and `frontend/src/useData.test.js` (+169 lines);
  no V_3 test file appears in that diff. Matches the finding exactly.

## Finding 3 — Bare MagicMock() for KalshiClient in live-trading tests — CONFIRMED

- `grep -c "MagicMock()"` → test_live_execution.py:83, test_trading_gates.py:20.
- `grep -c "MagicMock(spec"` → 0 and 0 in those files; only
  `tests/test_phase2_batch_e.py` uses `MagicMock(spec=...)` anywhere in tests/
  (2 occurrences, unrelated file). Exact match to the claim.
- Spot-checked ~15 of the 83 test_live_execution.py call sites — all are
  `mock_client = MagicMock()` / inline client mocks, consistent with the
  finding's "client stand-in" characterization.
- Reproduced the mock-vs-spec behavior gap myself: a bare `MagicMock()` lets
  a nonexistent method call silently succeed; `MagicMock(spec=kalshi_client.KalshiClient)`
  correctly raises `AttributeError`. Confirmed `kalshi_client.py` defines real
  `place_order`/`get_order`/`get_market`/`get_markets`/`get_orderbook` methods.

## Finding 4 — "No structural test enforces gate parity" — DISPROVEN

This finding's central factual claim is wrong. `tests/test_trade_cycle_engine.py`
contains `class TestPlacementGateMirrorsValidateOpportunity` (line 1661), which:

- Has a docstring explicitly stating its purpose: "Opus review (2026-08-07):
  four one-directional assertions on trade_cycle's own gate can't catch drift
  between it and the function it mirrors. This binds the two together directly."
- Is a `@pytest.mark.parametrize`'d test over 5 edge/kelly/spread scenarios that,
  for each candidate trade_cycle tiers as STRONG/MED, calls the REAL
  `main._validate_trade_opportunity()` (order_executor's actual placement gate,
  imported via `main`) and asserts it returns `ok=True` — i.e. it directly
  re-runs the real gate function and fails if trade_cycle ever tiers something
  validate() would reject. This is precisely the historically-recurring bug
  class (STRONG banner that can never place) that the finding says has no
  tripwire.
- Ran it myself: `pytest tests/test_trade_cycle_engine.py -k
  TestPlacementGateMirrorsValidateOpportunity -q` → 5 passed.

So "no test exists that structurally compares the two functions' gate sets"
and "a future gate added to _validate_trade_opportunity ... would not be
caught by any test" are both directly contradicted by code already in the
suite. The original pass's own evidence note ("Grepped the file for any
parity/enumeration-style test and found only individual per-gate assertions")
appears to have simply missed this class, which sits later in the file
(line 1661) than the per-gate classes it did cite (1483-1567).

**Genuine residual gap** (much narrower than the original finding): the test
binds only the "tiered ⇒ validate() accepts" direction, not the full converse
(its own docstring says so — validate()'s `_MIN_EDGE_AB_TEST` gate is
deliberately unmirrored and untested here), and it exercises a fixed set of 5
hand-picked parametrized inputs rather than mechanically enumerating
validate()'s gate list, so a brand-new gate whose rejection condition isn't
triggered by any of those 5 fixtures could still slip through silently. That
narrower point is defensible; the finding as written is not.
