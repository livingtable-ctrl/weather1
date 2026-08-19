# Batch 18: Position read-model & CLI display consistency

## Context

Repo: weather1 (Kalshi weather-trading bot). Branch `claude/code-max-depth-audit-5518e9`, HEAD `d190d09dd699df5266e85650a6ddf8e2d1420891` at the time these batches were written (2026-08-18) -- **re-verify this is current before starting** (workflow step 1): other batches from this same grouping may already be merged, and this project routinely runs many parallel worktree sessions. `git fetch` + `git log origin/master` before touching anything.

This batch groups 3 **pre-existing** backlog item(s) (not from the 2026-08-18 audit) sharing **main.py, positions.py**. Each item's full existing entry is reproduced verbatim below from `backlog.txt` -- these already have their own Problem/Priority write-ups from earlier sessions; read them in full rather than treating the excerpt here as complete.

**Do NOT touch other batches' files while working this one** -- batches were constructed so no two share a touched file; if you find yourself needing to edit something outside this batch's file list, stop and check whether another batch already covers it (see the full batch list in `audit/handoff_prompts/batches/INDEX.md`) rather than expanding scope silently.

## Items in this batch

### 1. Pre-existing backlog item (`backlog.txt:14358`)

```
[PARTIALLY RESOLVED 2026-08-14 -- the Medium-priority price-convention
  divergence is fixed; the Low-priority dict-vs-Position sourcing is
  deliberately still open, unchanged from the original filing, see "Why
  not now" below] check_model_exits/_check_live_model_exits/
  _check_early_exits STILL SOURCE POSITIONS AS RAW DICTS, NOT THE NEW
  Position READ-MODEL -- AND THEIR EXIT-PRICE CONVENTIONS HAVE ALREADY
  DIVERGED
Priority: Medium for the price-convention divergence, Low for the dict-vs-
  Position sourcing itself. The dict-sourcing IS cosmetic (see "What it
  would look like" below). But these functions do NOT merely duplicate
  per-trade API-call/analysis STRUCTURE with no price-math risk, as this
  entry originally (and wrongly) claimed: order_executor.
  _check_live_model_exits computes its exit price via _liquidation_price()
  (order_executor.py:1471, bid for YES / 1-ask for NO -- the realizable
  closing price), while order_executor._check_early_exits (paper-only)
  computes its via _midpoint_price() (order_executor.py:1854, the bid/ask
  midpoint) -- verified live by grepping both call sites 2026-08-13, not
  assumed. positions.liquidation_price()'s own docstring explains why this
  matters: pricing at the midpoint instead of the realizable bid/ask
  "overvalu[es] the position by the bid-ask spread ... inflating
  take-profit/exit proceeds." So paper's model-exits book a more optimistic
  P&L than live's would for the identical shift/threshold -- precisely the
  live/paper divergence class this whole backlog entry (see the resolved
  entry above) was filed to eliminate, just found in a different function
  pair than the one that got fixed.

Problem:
  Price-convention divergence (the real issue): paper.check_model_exits
  doesn't compute its own exit price at all (it's a pure recommendation
  generator -- main.py's cmd_brief/watch-mode display decides the actual
  close_paper_early() call and price separately). order_executor.
  _check_early_exits DOES exit paper trades directly and uses
  _midpoint_price(). order_executor._check_live_model_exits exits live
  positions directly and uses _liquidation_price(). Two functions doing the
  conceptually identical job (close a position because the model's
  probability shifted past a threshold) price the close differently.

  Dict-vs-Position sourcing (cosmetic): paper.check_model_exits still calls
  get_open_trades() (raw dicts, full ~20-field trade shape) directly rather
  than PaperPositionStore.get_open(). order_executor._check_live_model_exits
  and order_executor._check_early_exits still call
  _get_live_open_positions()/paper.get_open_trades() directly rather than
  LivePositionStore.get_open(). All three return dicts (not Position) in
  their recommendation payloads, since callers (main.py's exit-signal
  display, cmd_brief) read extra fields (thesis, full market dict, etc.)
  Position deliberately doesn't carry.

What it would look like:
  Price convention: decide which is actually correct (liquidation_price's
  own docstring argues realizable bid/ask, not midpoint, is the right
  convention for a real exit -- the same argument that motivated fixing
  paper's stop-loss/breakeven pricing originally) and make
  _check_early_exits use liquidation_price() too, falling back to
  entry_price like the other exit paths already do when no quote is
  available. Needs its own before/after test proving the P&L booked for a
  model-exit changes (or doesn't, if the spread is usually thin enough not
  to matter -- check real settled-trade data before assuming impact).

  Dict-vs-Position sourcing: not a straightforward swap -- these functions'
  return payloads need the FULL trade/position dict for display, not just
  Position's fields, so routing their position-SOURCING through the stores
  (get_open()) while keeping their OWN return shape as dicts would need
  each function to either look up the original dict by id after getting
  Position objects (like check_paper_position_exits' by_id pattern) or the
  stores would need a "get full record" escape hatch. Worth designing
  properly rather than forcing a fit -- not a mechanical change.

Why not now:
  Price convention: not independently verified yet whether the divergence
  moves real P&L by a meaningful amount (see "What it would look like"
  above) -- needs that check before deciding this is worth a live-order
  code change, not just deferred out of caution. Genuinely NOT scoped out
  because it's low-risk; scoped out because filing it accurately (this
  entry) and fixing it correctly are two different amounts of work, and the
  2026-08-13 session that found it was already mid-review of a different,
  larger change.
  Dict-sourcing: genuinely has no duplication risk (it's structural, not
  mathematical) -- pure internal consistency, not a bug. Pick up
  opportunistically or if these functions are touched for another reason.

When to revisit:
  Price convention: soon -- this is a real, live-order-adjacent pricing
  bug, not cosmetic; the only reason it isn't fixed in this same entry is
  that it was caught by review after the sibling entry's implementation
  was already done and confirmed, not before. Dict-sourcing: no blocking
  dependency.

Resolution (2026-08-14):
  Both remaining execute-a-close sites switched from _midpoint_price() to
  liquidation_price() (positions.py): order_executor._check_early_exits
  (order_executor.py, the automated paper path, cron/watch-driven) and
  main.py's interactive exit-signal menu (~line 6858, the manual y/N close
  reached via check_model_exits' recommendations). Both now price a
  model-exit identically to order_executor._check_live_model_exits
  (unchanged) -- same current_prices dict shape ({ticker: {"bid","ask"}}
  via coalesce_market_price(*YES_BID_KEYS/YES_ASK_KEYS)), and, added during
  review (see Finding 1 below), the same _get_current_book(client, ticker)
  or market WS-then-REST freshness step live already used -- paper's
  pricing now literally mirrors live's, not just conceptually.

  Two scope/design decisions surfaced via AskUserQuestion before
  implementing (terse question, tradeoffs in option descriptions, per this
  project's standing workflow):
    1. Fix both _check_early_exits AND main.py's manual close site
       (chosen) vs. _check_early_exits only. Chosen because leaving the
       manual site on the old midpoint convention would have created a
       NEW divergence (manual paper closes vs. automated paper closes
       pricing the same trigger differently) the moment this entry closed.
    2. Preserve the existing skip-this-cycle-on-bad-quote behavior
       (chosen) vs. this entry's own original "What it would look like"
       text, which prescribed falling back to entry_price "like the other
       exit paths already do." Re-verified against live code
       (order_executor.py, both _check_live_model_exits and
       _check_early_exits) before implementing: that claim was wrong --
       neither existing model-exit site falls back to entry_price on a
       bad quote; both skip the cycle. The entry_price fallback is the
       STOP-LOSS/BREAKEVEN family's convention (order_executor.py's
       _check_live_position_exits, paper.py's stop-loss/breakeven exit
       loop), a different function family with a different contract.
       Implemented as `if exit_price is None or exit_price <= 0: continue`
       -- liquidation_price() returns None on a missing/invalid quote
       (never negative), so this preserves the exact skip semantics both
       existing model-exit sites already had, just checking a different
       function's return contract.

  Real-data impact check (this entry's own stated precondition under "Why
  not now" above): queried predictions.db's price_history table
  (yes_bid_close/yes_ask_close) against all 37 historical paper trades
  settled via the model-exit-family midpoint convention (paper_trades.json,
  outcome="early_exit", exit_reason IS NULL -- this bucket covers both
  _check_early_exits' automated closes and the manual menu's closes, since
  neither tags a reason). Matched each trade's settled_at to the nearest
  price_history candle by ticker; only 12 of 37 matched within 15 minutes
  of the actual exit (price_history's per-ticker coverage is sparse -- the
  other 25 matched a candle 6-48+ hours away and were excluded as
  unreliable, not averaged in). Of the 12 reliable matches: median spread
  ~3c, mean ~4.8c, mean per-trade P&L overstatement (midpoint vs. realizable)
  ~$1.34, max $4.73 on a single trade. Confirms this entry's own suspicion
  under "Why not now": spreads are consistently thin on these weather-market
  tickers, so per-trade dollar impact is modest -- but real, directionally
  consistent with liquidation_price()'s docstring (midpoint always
  overvalues by roughly half the spread), and non-zero, which is enough to
  justify the fix on consistency grounds even before considering compounding
  effects (see Finding 11 below on the paper P&L series becoming
  non-homogeneous across this changeover).

  Tests: 5 new tests -- tests/test_early_exits.py's new
  TestEarlyExitPricingConvention (4 tests: hand-computed liquidation price
  vs. the old midpoint for both YES and NO sides; a positive-controlled
  skip-on-None test; a skip-on-exactly-0.0 test added per Finding 3 below,
  covering the `exit_price <= 0` half of the guard that `is None` alone
  does not) and tests/test_menu_ux.py's new
  test_exit_signals_uses_realizable_price_not_midpoint (drives the real
  main.py manual-close code path end to end with no pricing mock). 2
  existing tests updated in test_menu_ux.py (mock arity/values for the
  _midpoint_price -> _liquidation_price switch) and 2 in
  test_live_execution.py (TestMidpointPrice now imports from
  order_executor, since main.py no longer re-exports the now-paper-close-
  unused _midpoint_price -- it remains legitimately used for live order
  placement/repricing, order_executor.py:983/1582, untouched by this
  change). Every new/changed pricing assertion mutation-tested by reverting
  the relevant production line via Edit, confirming the right test failed
  for the price-difference reason (not an unrelated one), then restoring:
  the YES/NO liquidation-vs-midpoint tests fail with "got 0.3, expected
  0.2" against the reverted midpoint code; the missing-quote skip test
  fails by actually closing at a fabricated 0.5 against reverted code; the
  exactly-0.0 skip test (added for Finding 3) fails by closing at a
  fabricated $0.00 when the guard is mutated to drop its `<= 0` clause.
  140 tests pass (freshly re-run immediately before writing this sentence)
  across tests/test_early_exits.py, test_menu_ux.py, and
  test_live_execution.py; a broader regression sweep of
  tests/test_positions.py, test_trading.py, test_paper.py,
  test_main_cron_smoke.py, and test_trading_gates.py (250 tests, also
  freshly re-run) passes clean given this touches a live-order-adjacent
  exit-pricing path. ruff + ruff format + mypy clean via the actual
  pre-commit hook on all changed files.

  Independent opus review (effort=high) before push found 11 findings, all
  addressed:
    - 2 LOW findings, fixed: (1) unlike _check_live_model_exits,
      _check_early_exits was pricing off the same-cycle get_weather_markets
      scan dict rather than calling _get_current_book(client, ticker) first
      for a WS-cache-then-REST-fresh quote -- not a regression (the old
      _midpoint_price() call used the identical stale dict), but it left
      the "same convention as live" claim in this change's own docstring
      not quite true. Now calls _get_current_book exactly like
      _check_live_model_exits does. (2) The `exit_price <= 0` half of the
      skip guard (as opposed to `is None`) was reachable but untested at
      both new sites -- a NO position in a market with yes_ask=100c
      produces liquidation_price()==0.0, not None, so mutating the guard
      to check only `is None` would have passed every other test. Added
      test_skips_cycle_when_no_side_liquidation_is_exactly_zero;
      mutation-tested (see Tests above).
    - 3 LOW findings, fixed: (1) main.py's growing module-level `utils`
      import block was adding a second function-object symbol
      (coalesce_market_price) to the exact "frozen at process-import time
      across a test's importlib.reload(utils)" risk class a standing
      comment in that import block already documents and warns against --
      moved coalesce_market_price/YES_BID_KEYS/YES_ASK_KEYS to a local
      import inside the sub=="4" branch, matching that branch's existing
      local-import convention (`from paper import ...` two lines above).
      _liquidation_price stays module-level (tests monkeypatch
      main._liquidation_price by name). (2) tests/test_menu_ux.py's new
      end-to-end test asserted exact float equality
      (`close_calls == [(11, 0.38)]`) on a genuinely computed value
      (1.0 - 0.62); passed today only because that particular subtraction
      happens to be exactly representable -- changed to
      `exit_price == pytest.approx(0.38)`. (3) that same test duplicated
      ~25 lines of the existing _run_paper_sub4 helper because the helper
      unconditionally mocked _liquidation_price -- added a
      patch_liquidation=True parameter so the new test can reuse the
      helper with patch_liquidation=False.
    - 2 informational findings, no action -- explicit reasoned no-ops:
      (1) liquidation_price() doesn't round to 2dp the way the old
      _midpoint_price() did; verified harmless, since close_paper_early
      already rounds both exit_price and pnl to 4dp and the ledger's own
      balance-drift check tolerates 0.05. (2) no regression test pins
      _check_live_model_exits' own pricing convention -- that function is
      byte-for-byte unchanged by this entry, so adding coverage for
      already-existing, already-shipped behavior is a genuinely separate,
      unscoped task, not a gap this change introduced.
    - 1 LOW finding, documented deliberate no-op: main.py's manual y/N
      close path now declines (prints "no realizable quote", moves on)
      when the quote is missing, with no operator escape hatch to enter a
      manual price. This is correct for the automated paths (paper's own
      duplicate-order-guard-adjacent invariant: never fabricate a price),
      and is already a net improvement here too -- the OLD behavior always
      closed, at a possibly-fabricated _midpoint_price default (0.50,
      exactly the class of bug this entry exists to fix), so this is not a
      regression. Adding a manual-price-entry prompt is a genuine UX
      feature addition, not a bug fix, and out of scope for this entry.
    - 1 MEDIUM finding, fixed: this entry's own "What it would look like"
      text (see above) prescribed the entry_price fallback that decision 2
      above explicitly rejected as factually wrong for this function
      family -- left as originally written, a future session picking up
      the dict-sourcing half of this entry could "finish" it by adding
      that fallback and silently reintroducing a fabricated-price bug.
      This resolution note is the fix: the original problem/plan text
      above is left intact for history (per this project's convention),
      but decision 2 in this Resolution section is now the authoritative
      record of what shipped and why the entry's own prescription was not
      followed.
    - 1 LOW/informational finding, noted rather than actioned: paper
      model-exit closes from this date forward book systematically lower
      proceeds than before (by roughly half the spread, both sides) --
      correct and intended, but it makes the paper P&L series
      non-homogeneous across 2026-08-14 for anything that reads it in
      aggregate (paper.graduation_check's win-rate/total-pnl thresholds,
      the drawdown pause, tracker calibration). Not a bug and not
      reverted; recorded here so a future "why did paper P&L step down
      around mid-August" question has a documented answer.
    - 1 MEDIUM finding, spun off as its own new backlog entry rather than
      fixed here (same-payload test: genuinely separate consumer, not the
      same data flow this entry touches -- a different function, different
      file, Python+JSX rather than this entry's pure-Python sites): the
      React dashboard's Close button (frontend/src/App.jsx,
      frontend/src/useData.js, web_app.py's POST /api/close-position) is a
      FOURTH paper-close site, with a pricing convention worse than either
      bug this entry fixed -- see the new entry near the end of this file
      for the full writeup.

  Dict-vs-Position sourcing (the Low-priority half of this entry):
  deliberately still not touched, unchanged from the original filing above
  -- genuinely has no duplication risk, pure internal consistency, pick up
  opportunistically or if these functions are touched for another reason.
```

### 2. Pre-existing backlog item (`backlog.txt:19036`)

```
[main.py's _rating() CLI TABLE IS A 4TH, STILL-TEXT-DERIVED STAR LADDER, NOW CONTRADICTING THE FIXED ONES]
Priority: Low -- cosmetic/display-only, same family as the entry above and
  equally not a placement-path bug (placement still gates on `tier` alone,
  never on any of these star renderings).

Problem:
  Filed 2026-08-08, surfaced by the same opus review that resolved
  "[RESOLVED 2026-08-08] DASHBOARD STARS + WATCH-MODE STRONG ALERT KEY OFF
  SIGNAL TEXT, NOT THE tier FIELD]" (see above), deliberately kept out of
  scope for that entry (genuinely separate function/call-site surgery, not
  a same-shape 1-line swap).

  main.py's `_rating()` helper (~line 1643-1651 as of 2026-08-08):
  ```
  def _rating(net_edge: float, risk: str) -> str:
      ae = abs(net_edge)
      if ae >= STRONG_EDGE and risk != "HIGH":  return green("★★★")
      elif ae >= 0.12:                          return yellow("★★ ")
      else:                                     return dim("★  ")
  ```
  renders the Rating column in `_render_analysis_results`'s console table
  -- the table cmd_watch and cron's own console output actually print. It
  is a 4th independent star ladder (trade_cycle.py's dashboard stars and
  main.py's watch-mode alert were the 2 the resolved entry above
  converted; cron.py's signals_cache.json summary was a 3rd, also fixed
  same session) -- and unlike the other 3, it was NEVER tier-aware even
  before this session: it keys off raw `net_edge` magnitude (not
  adjusted_edge) and `risk != "HIGH"` (not `== "LOW"`), so it never agreed
  with trade_cycle.py's ladder by construction.

  The resolved entry above's fix widens the practical impact of this
  pre-existing gap: opus review's mutation-test run captured live evidence
  of the exact untiered-but-STRONG-text candidate the resolved entry's own
  regression test uses (adjusted_edge/net_edge qualify for STRONG, raw edge
  too small for validate()'s MIN_EDGE gate, tier=None) rendering "★★★" in
  this CLI table, "★" in signals_cache.json's `stars` field, and firing no
  watch-mode alert -- three different verdicts for the same candidate in
  the same cycle. Before the resolved entry's fix, all 3 (well, then-2)
  sites agreed, wrongly, using the same signal-text logic; now this one is
  the visible outlier.

  cmd_watch calls `_render_analysis_results` with `cycle_result.liquid_opps`
  (main.py ~line 3570), whose analysis dicts DO carry `tier` (unlike
  `_analyze_once`'s own analysis dicts, which never do -- see the resolved
  entry above's own note on why that fallback path was correctly left
  alone). So unlike that fallback path, this one is not blocked by data
  availability -- `_rating()` could read `tier` if it accepted it.

  What it would look like: `_rating()` needs either an added `tier`
  parameter (defaulting to None) that takes priority over the net_edge/risk
  math when present, or the call site needs to branch. Not a blind
  signature swap: `_render_analysis_results` is also called from
  `_analyze_once`'s own render path (tier-free analysis dicts), so
  `_rating()` must keep working correctly with `tier` absent -- trace every
  call site of `_render_analysis_results`/`_rating()` before changing the
  signature, matching this repo's own gate-caller-tracing convention. Once
  fixed, add a regression test asserting the CLI table's rendered stars
  agree with signals_cache.json's `stars` field for the same candidate (the
  resolved entry above's `test_untiered_strong_text_no_longer_shows_
  multiple_stars` fixture is exactly the shape to reuse).

  Also worth folding into the same pass (both LOW, both surfaced by the
  same review, both cosmetic):
  - The `_analyze_once`-reached fallback watch alert (main.py ~line
    1543-1548, hit when cycle_result is None -- e.g. the cron lock is held
    by a concurrent cron) still alerts on `"STRONG" in net_signal` text
    with no placement-gate awareness, while the cycle_result path (fixed
    this session) now alerts on `tier == TIER_STRONG`. Same market, same
    session, different alert behavior depending purely on whether the lock
    was free that cycle. Would need `tier` plumbed through analyze_trade()/
    _analyze_once to close for real -- bigger surgery, same shape as the
    _rating() fix above.
  - frontend/src/App.jsx's (and the sibling `weather app site V_3 (3)`
    SignalsTab.jsx's) legend labels "★★" as "Strong signal" -- now also
    covers MED tier since the resolved entry above's fix. Not a hard break
    (both frontends bucket on `stars.length >= 2`, not the exact label
    text), but the copy is stale. A quick pass to relabel "★★" as
    "Strong or med signal" (or similar) would close this.

  Deliberately NOT in scope for this entry, confirmed genuinely separate:
  web_app.py's own independent top-opportunities star ladder (~line
  2974-2979, edge_pct-based) -- fed by its own analyze_trade() call, same
  `tier`-unavailable shape as `_analyze_once`, not fixable without the same
  analyze_trade()-level plumbing the fallback-alert bullet above would also
  need.
```

### 3. Pre-existing backlog item (`backlog.txt:17119`)

```
[PARTIALLY RESOLVED 2026-07-19 -- STALE COUNT CORRECTED 2026-07-31, see note
  at end: 3 of the original 7 reload(utils) sites were converted the same
  day, leaving 4, not ~6] main.py's FROZEN `from utils import ...` COULD
  REPEAT THE SAME IDENTITY-DIVERGENCE BUG -- utils IS RELOADED BY 4 TESTS
Priority: Low -- latent structural risk, not a current bug; nothing today
  asserts an identity check that would catch it firing.

RESOLVED 2026-07-19 (partially -- the audit below found the entry's own
  "likely possible for most/all of them" framing overstated; only 2 of the
  7 real reload(utils) call sites could actually be converted):
  Audited all 7 call sites individually (the entry said "~6 tests" but
  test_p9_p10.py and test_sameday_reserve.py each reload twice, for 7
  total) rather than trusting the "likely possible for most/all" claim at
  face value. Found two genuinely different shapes:
  (a) 3 reload(utils) call sites across 2 files (test_kalshi_ws.py's
  test_stale_entry_returns_none; test_sameday_reserve.py's _patch_env and
  _patch_dynamic_env helpers, used by 10 tests) use reload(utils) purely as
  a means to get a downstream
  function (kalshi_ws.get_cached_mid_price, order_executor.
  _sameday_effective_cap) to observe a new constant value -- exactly the
  order_executor._prediction_kwargs_from_analysis shape this entry was
  modeled on. Confirmed both downstream functions do a function-local
  `from utils import X` fresh on every call (not a frozen copy), so
  monkeypatch.setattr(utils, "X", value) reproduces the exact same
  observable effect with none of the whole-module rebind risk. Converted
  both -- reload(utils) is now gone from these 2 files entirely.
  (b) The other 4 sites (test_p9_p10.py's test_enable_micro_live_defaults_
  false / test_brier_alert_threshold_default, test_risk_control.py's
  test_drawdown_halt_default_is_20pct, test_starting_balance.py's
  test_utils_exports_starting_balance) assert directly on utils.<CONST>
  itself -- the test SUBJECT is utils' own `float(os.getenv(...))`
  module-level parsing logic. Converting these to monkeypatch.setattr
  would make them tautological (assert a value you just set equals
  itself), testing nothing about production code. Left these as
  reload(utils) -- genuinely the correct tool for what they verify, not
  an oversight.
  Since 4 reload(utils) sites remain and genuinely can't be eliminated,
  the underlying hazard for main.py's frozen `from utils import (...)`
  (line 94) is only reduced, not closed -- any of those 4 tests can still
  cause main.is_trading_paused/MIN_ARB_EDGE/MIN_EDGE/STRONG_EDGE to
  diverge from utils' live copies for the rest of a pytest session if a
  future identity-check test is ever added and happens to run after one
  of them. Took this entry's own second option for the remaining risk:
  documented the hazard directly in main.py's import block (a comment
  above the `from utils import ...` line explaining the mechanism,
  naming is_trading_paused as the highest-risk symbol since it's a
  function object, and pointing at this backlog entry) rather than adding
  a new test that would itself demonstrate/cause the exact divergence
  it's warning about -- that would be introducing the failure mode to
  prove it exists, not fixing anything.
  27 tests pass in the 2 converted files; scoped as low-risk since the
  conversions only change *how* a constant is set for a test, not what's
  asserted. No new tests needed -- the existing tests already
  differentiate outcomes by the patched values (e.g. slots=0 vs slots=2
  producing different expected caps across the existing test suite),
  which is itself adequate coverage that the monkeypatched attribute
  really flows through to the function under test (spot-verified by hand:
  temporarily setting utils.WS_CACHE_TTL_SECS to a huge value flips
  get_cached_mid_price's result from None to a real price, confirming the
  attribute is what's actually read).

Problem (as originally scoped, still accurate for the un-converted 4 sites
and the remaining latent main.py risk):
  main.py:94 does `from utils import MIN_ARB_EDGE, MIN_EDGE, STRONG_EDGE,
  is_trading_paused` once at process-import time -- the exact same frozen-
  import shape that caused the order_executor bug above. utils.py is
  reloaded by ~6 tests (test_kalshi_ws.py:234, test_p9_p10.py:620/629,
  test_risk_control.py:371, test_sameday_reserve.py:17/123,
  test_starting_balance.py:36), each to pick up an env-var-driven constant
  the same way test_execution_stability.py's now-fixed reload did for
  order_executor. No test today asserts `main.<symbol> is
  utils.<symbol>` the way test_prediction_kwargs.py does for
  order_executor, so nothing currently fails -- but if such a test is ever
  added (a very plausible next step, since it's the same defensive pattern
  that caught the order_executor bug), or if any of those 6 reloads is ever
  reordered to run before a test relying on main.py's frozen utils symbols
  behaving identically to utils' live ones, the same bug class recurs.

What it would look like:
  Either audit whether any of the reload sites could instead monkeypatch
  the specific derived constant directly (DONE 2026-07-19 for 3 of 7 --
  see resolution above; the other 4 genuinely can't, they test utils' own
  parsing), or document the frozen-import hazard directly in main.py's
  import block so a future contributor adding an identity check knows to
  check for this (DONE 2026-07-19, see resolution above).

Why not now (for the remaining 4-site latent risk):
  - Not a live bug -- no identity assertion exists yet to trip it, and the
    4 remaining reload(utils) sites are the correct tool for what they
    test (utils' own env-var parsing), not something to work around.
    Genuinely closable only by a larger restructuring (e.g. an autouse
    fixture that reasserts main.py's frozen symbols after any utils
    reload) that isn't worth it for a risk with no current trigger.

When to revisit:
  - If a new main.py <-> utils identity-check test is ever added (it would
    immediately surface whether the remaining 4 sites actually cause
    trouble in practice), or test_p9_p10.py/test_risk_control.py/
    test_starting_balance.py is next open for other reasons.

RE-VERIFIED 2026-07-31 (staleness re-check on this entry's own title/header,
  not a new finding about the underlying risk): the title's "~6 TESTS"
  figure was out of date. The 2026-07-19 resolution above already converted
  3 of the original 7 reload(utils) call sites (test_kalshi_ws.py's
  test_stale_entry_returns_none; test_sameday_reserve.py's
  _patch_env/_patch_dynamic_env helpers) to monkeypatch.setattr, leaving
  only 4 reload(utils) sites today (test_p9_p10.py x2, test_risk_control.py,
  test_starting_balance.py) -- matching what this entry's own "Why not
  now"/"When to revisit" sections already correctly say, just never
  reflected in the title itself. The underlying structural risk (main.py's
  frozen `from utils import ...` diverging if one of those 4 reloads ever
  runs before an identity-check test) is unchanged and still real; only the
  title's count was stale.

======================================================
```

## Process -- follow the 29-step implementation workflow from memory (`feedback-implementation-workflow`) exactly, in order

At least one item in this batch touches a live-order/live-money/safety-gate path (or is adjacent enough to warrant it) -- this batch does **not** qualify for the steps 11-12 LOW-tier downgrade. Apply the full ceremony as written, all 29 steps, for the batch as a whole.

Non-negotiable highlights regardless of tier: (1) re-verify every item's claims against live state before trusting this prompt's transcription -- re-read the actual current code/docs at the cited locations. (2) Research the real code structure before designing a fix. (3) Surface genuine design decisions via `AskUserQuestion`, don't guess. (7) Write real, mutation-tested tests for anything code-level (via the Edit tool for mutation reverts, never a string-replace script). (8-9) Scoped test run, then lint/mypy. (11) Independent opus review at `effort: high` before push for anything live-money-adjacent -- and if that review's findings get fixed, the fix itself needs its own independent review too. (13) Address every review finding regardless of severity. (14-16) Compressed-pointer memory update before commit; explicit confirmation before commit/push; `git fetch` + rebase-if-diverged immediately before the actual push -- this matters more than usual here since other batches may be pushing to the same branch/master concurrently. (19) If `backlog.txt` gets edited, run `python backlog_index.py` afterward and confirm the entry landed correctly in `BACKLOG_OPEN.md`. (29) Refresh `graphify-out/` (AST always; semantic `--update` too if any item is non-LOW-tier) before committing, if it exists -- scope the refresh to just the files this batch actually changed, not a full incremental sweep (a full sweep pulls in every other in-flight batch's uncommitted work too).

Full step list and tiering rules live in memory under `feedback-implementation-workflow` -- apply all 29 steps in order. **If this memory entry isn't loaded in your session**, its full text is preserved at `C:\Users\thesa\.claude\projects\C--Users-thesa-claude-kalshi\memory\feedback_implementation_workflow.md` -- read it directly rather than proceeding without it.
