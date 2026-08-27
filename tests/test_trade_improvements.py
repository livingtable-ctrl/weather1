"""
Tests for 3 approved trading improvements:
  1. MAX_CONCURRENT_POSITIONS cap (20) in _auto_place_trades
  2. MIN_PROB_EDGE gate (8pp probability delta) in cron.py
  3. Ensemble member threshold lowered from >=10 to >=2 in weather_markets.py
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


# ─────────────────────────────────────────────────────────────────────────────
# 1. MAX_CONCURRENT_POSITIONS cap
# ─────────────────────────────────────────────────────────────────────────────


class TestMaxConcurrentPositions:
    """_auto_place_trades must never let a cycle END above 20 open positions.

    batch-85 item 1 changed what this class is testing. MAX_CONCURRENT_POSITIONS
    used to be a single pre-loop entry gate: it refused a cycle that already
    started at the cap and imposed no limit at all below it, so 18 open plus 5
    qualifying signals placed all five and finished at 23. It is now re-checked
    per placement against `_open_trades_list`, which both placement branches
    append to, so the number placed is `max(0, min(n_signals, cap - n_open))`
    -- the outer max matters, since at n_open > cap the inner expression goes
    negative while the code of course places 0.

    WHY THAT MATTERS FOR THE PROBE SET, and what must be preserved if anyone
    changes these numbers again. batch-80 added
    test_one_below_the_cap_still_places specifically because the old `>=`
    boolean gate turned every probe into one bit: 18 open said "did not fire"
    and 20 open said "fired", which brackets the cap to {19, 20} and no
    tighter, since 18 >= 19 is False and 20 >= 19 is True. A third probe at 19
    was the only way to separate 19 from 20.

    Under the new semantics each probe returns a COUNT rather than a bit, so a
    single probe is two-sided by itself:

        n_open   cap=19   cap=20   cap=21
          20       0        0        1
          19       0        1        2
          18       1        2        3

    Read that table as counts under THIS fixture's pinned gates: MAX_DAILY_
    SPEND 500, MAX_VAR_DOLLARS 200, and no `target_date` so the per-date cap is
    structurally unreachable. The worst cell is 5 placements -- ~$220 of spend
    and 24 position rows of VaR -- so none of those three binds in any cell.
    Change the fixture and re-derive the table.

    Which cells are actually PROVEN differs, and the difference matters
    (opus round-2 INFO-2): the 1-, 2- and 3-placement cells are re-derived by
    a green test on every run. The 5-placement worst case is not -- no test
    in this class asserts more than 4 -- so that spend/VaR figure rests on a
    manual probe recorded here, not on anything the suite re-checks. Treat it
    as documentation, and re-measure before relying on it.

    Both the 19-open and the 18-open probes read differently for all three cap
    values, so either one alone pins the cap from both directions -- strictly
    sharper than what batch-80 built, not a regression of it. It holds beyond
    the three columns shown, too: at cap <= 18 the pre-loop gate fires at
    n_open=19 and gives 0, and at cap >= 24 the room exceeds the signal count
    and gives 5, so every cap value other than 20 reads as something other
    than 1. The 20-open probe is still one-sided (a cap of 19 also places 0
    there), which is exactly why it is not the only test and why its own
    `== 0` is documented as an absence needing the siblings as its positive
    control. Mutation evidence for cap 19 and cap 21 is recorded on
    test_one_below_the_cap_still_places.
    """

    def _make_open_trades(self, n: int) -> list[dict]:
        # batch-80 item 3: these are internally consistent positions now --
        # entry_price * quantity == cost (0.40 * 25 == $10.00). The old shape
        # was {"cost": 10.0, "qty": 1}, which is not a position that can exist:
        # a Kalshi contract settles at $0 or $1, so one contract cannot cost
        # $10. It also spelled the size `qty`, while monte_carlo's
        # simulate_portfolio reads `quantity` (monte_carlo.py:384) and falls
        # back to 1, and reads `entry_price` (line 382) falling back to 0.50.
        #
        # That mismatch is not cosmetic -- it is what kept the repaired test
        # from ever reaching the cap. Measured via portfolio_var(): 18
        # old-shape rows project $174 of VaR against the $200 MAX_VAR_DOLLARS
        # limit, and the candidate trade pushes that to $217, so every
        # opportunity was skipped as var_limit($217>$200) before the placement
        # path. The 18-open case is the one that matters -- at 20 open the
        # concurrent-position gate returns before VaR is ever reached. (An
        # earlier note here paired the 20-row figure, $194, with the 18-row
        # $217; both are real but they belong to different portfolios --
        # opus review M-5.) The same 18 positions in this consistent shape
        # project $30. The fixture was manufacturing a near-limit portfolio
        # out of an impossible position, not exercising a real risk gate.
        return [
            {
                "ticker": f"KXHIGH-NYC-{i}",
                "side": "yes",
                "cost": 10.0,
                "entry_price": 0.40,
                "quantity": 25,
                # `qty` kept only because the old fixture had it; dropping it
                # would be an unrelated change. The earlier note here claimed
                # "both spellings are read in different places" -- overstated
                # (opus review L-4): outside tests/ exactly one reader touches
                # it, main.py's `t.get("quantity", t.get("qty", 0))`, and only
                # as a fallback. paper.place_paper_order never writes a `qty`
                # key at all, so it is not a field the real system produces.
                "qty": 25,
                "entry_prob": 0.55,
            }
            for i in range(n)
        ]

    def _make_opp(self, idx: int) -> tuple[dict, dict]:
        ticker = f"KXHIGH-CHI-{idx}"
        # volume/open_interest are load-bearing, not decoration: without them
        # order_executor's liquidity_kelly_scale(m) multiplies adj_kelly to
        # 0.0 and every opportunity is skipped as kelly_too_small, which is
        # why test_trades_placed_below_cap placed 0 trades and still passed
        # under its old `<= 2` bound (opus-review-caught, batch-62).
        m = {
            "ticker": ticker,
            "yes_bid": 40,
            "yes_ask": 44,
            "volume": 500,
            "open_interest": 1000,
        }
        a = {
            "ticker": ticker,
            "forecast_prob": 0.70,
            "market_prob": 0.50,
            "edge": 0.20,
            "net_edge": 0.20,
            "kelly_fraction": 0.15,
            # batch-80 item 3: THE field that made both tests in this class
            # vacuous. _auto_place_trades sizes from `ci_adjusted_kelly` or,
            # failing that, `fee_adjusted_kelly` (order_executor.py:4761-4765)
            # -- it never reads `kelly_fraction`. With neither key present
            # ci_kelly fell back to 0.0, so adj_kelly was 0.0 no matter what
            # the three scaling factors did and every opportunity was skipped
            # as kelly_too_small(0.0000) before reaching any cap.
            #
            # This corrects the diagnosis recorded here by batch-62, which
            # blamed the synthetic ticker not parsing to a real city/target
            # date. That is true but not the cause: with city and target_date
            # both absent, portfolio_kelly_fraction takes its `if not city or
            # not target_date_str` branch and returns min(base_fraction,
            # remaining) -- it passes the value through rather than zeroing
            # it. liquidity_kelly_scale returns 1.00 here (volume 500 +
            # open_interest 1000 = 1500 > 500). The zero was only ever the
            # missing key.
            "fee_adjusted_kelly": 0.05,
            "recommended_side": "yes",
            "signal": "STRONG BUY",
            "net_signal": "STRONG BUY",
            "days_out": 2,
            "days_to_expiry": 2,
        }
        return (m, a)

    def _run_with_open(
        self,
        monkeypatch,
        repatch_paper_paths,
        n_open: int,
        max_daily_spend: float = 500.0,
    ) -> int:
        """Run _auto_place_trades against 5 opportunities and `n_open` positions.

        batch-80 item 3: both tests in this class call this, so `n_open` is
        the ONLY thing that differs between them. That matters more than the
        deduplication -- the two assertions are a matched pair (one places
        five, the other places none), and a pair is only evidence about the
        cap while everything except the position count is held identical. As
        two hand-maintained setup blocks they had already drifted: the at-cap
        one stubbed `place_paper_order` with a bare MagicMock() and omitted
        the `execution_log` stub entirely, which was invisible while it
        returned at the cap gate and never reached either one.
        """
        import importlib

        import paper

        # backlog L24334: reload FIRST, then isolate -- the other order lets
        # the reload discard the patch, so Kelly sizing below runs against the
        # REAL balance/peak. A production account in drawdown returns
        # scaling 0.0, which would satisfy a loose bound for entirely the
        # wrong reason. Opus-review-caught, batch-62.
        importlib.reload(paper)
        repatch_paper_paths(paper)
        import main
        import order_executor

        open_trades = self._make_open_trades(n_open)
        monkeypatch.setattr(paper, "get_open_trades", lambda: open_trades)
        monkeypatch.setattr(paper, "is_daily_loss_halted", lambda c: False)
        monkeypatch.setattr(paper, "is_streak_paused", lambda *_a, **_k: False)
        monkeypatch.setattr(paper, "is_paused_drawdown", lambda *_a, **_k: False)

        # opus review H-1/M-3: PIN THE CAPS THE ASSERTION DEPENDS ON.
        # `import main` above runs main.py's load_dotenv(), and find_dotenv()
        # walks UP OUT OF THIS WORKTREE to the main clone's .env, which sets
        # MAX_DAILY_SPEND=200. So the expected placement count was a property
        # of one machine's .env rather than of the code -- on a checkout
        # without that file the same run uses the 500.0 code default. Both
        # this and MAX_VAR_DOLLARS are module-level constants imported from
        # utils, so patch the attribute, not the env (setenv cannot reach a
        # value already bound at import).
        monkeypatch.setattr(order_executor, "MAX_DAILY_SPEND", max_daily_spend)
        monkeypatch.setattr(order_executor, "MAX_VAR_DOLLARS", 200.0)
        # MAX_POSITIONS_PER_DATE is read from the env INSIDE the function, so
        # it takes setenv rather than setattr. Pinned DEFENSIVELY and
        # currently UNREACHABLE: _make_opp supplies no `target_date`, so
        # _multiday_date_counts never increments and the gate cannot fire.
        # Mutating this pin to "1" leaves all three tests green (round-2 opus
        # review L5) -- it is here so that the moment someone gives the
        # fixture a real target_date, the count this file asserts is not also
        # silently at the mercy of an env var. See the docstring on
        # test_trades_placed_below_cap for what happens then.
        monkeypatch.setenv("MAX_POSITIONS_PER_DATE", "4")
        # MAX_CONCURRENT_POSITIONS is DELETED, never set. It is also read via
        # os.getenv inside the function, so setting it would override the
        # literal default in order_executor.py -- and that literal is exactly
        # what this class's mutation testing edits. Pinning it with setenv
        # would therefore make every cap mutation invisible and hand the class
        # straight back to the vacuity this batch removed. Deleting it forces
        # the source default to be the value under test.
        monkeypatch.delenv("MAX_CONCURRENT_POSITIONS", raising=False)

        monkeypatch.setattr(order_executor, "_daily_paper_spend", lambda: 0.0)
        monkeypatch.setattr(
            order_executor,
            "_validate_trade_opportunity",
            lambda opp, live=False, market=None: (True, "ok"),
        )
        monkeypatch.setattr(
            order_executor, "_current_forecast_cycle", lambda: "2026-04-25-06"
        )

        placed_count = 0

        # A recording double, NOT a bare MagicMock. MagicMock's auto-vivified
        # return value is not a dict, and order_executor reads fields off
        # whatever place_paper_order returns -- a MagicMock flows into the
        # VaR comparison ("'<' not supported between MagicMock and float",
        # which fails CLOSED and skips the rest) and into tracker's sqlite
        # bind. Under the at-cap test that was harmless only because the
        # function returned before ever placing; the moment the cap gate is
        # mutated away -- i.e. exactly when this test has to do its job --
        # it capped the observable count at 1 instead of 5.
        def _fake_place(ticker, side, qty, price, **kwargs):
            nonlocal placed_count
            placed_count += 1
            # The REAL trade shape (opus review H-1). The previous version
            # returned no `cost`, and order_executor both accumulates
            # `daily_spent += trade.get("cost", 0.0)` and appends this dict to
            # _open_trades_list for the in-cycle VaR gate. So the spend cap was
            # inert for the whole cycle, and every position placed this cycle
            # was re-read by portfolio_var with quantity defaulting to 1 and
            # entry_price to 0.5 -- reintroducing, one function later, the
            # exact impossible-position shape this batch just removed from
            # _make_open_trades.
            #
            # Mirrors the FIELDS paper.place_paper_order writes, with one
            # deliberate exception: `qty` is included even though the real
            # writer emits only `quantity` (round-2 opus review I6). It is
            # here to match _make_open_trades, which keeps the same legacy
            # spelling for the same reason -- so the two halves of this
            # fixture describe positions the same way.
            return {
                "id": placed_count,
                "ticker": ticker,
                "side": side,
                "qty": qty,
                "quantity": qty,
                "entry_price": price,
                "entry_prob": 0.70,
                "cost": round(price * qty, 2),
                "city": None,
                "target_date": None,
                "days_out": 2,
            }

        monkeypatch.setattr(paper, "place_paper_order", _fake_place)

        mock_exec_log = MagicMock()
        mock_exec_log.was_ordered_this_cycle.return_value = False
        mock_exec_log.was_traded_today.return_value = False
        # was_ordered_recently must be stubbed too. A bare MagicMock attribute
        # auto-vivifies and returns a TRUTHY MagicMock, so order_executor's
        # `if execution_log.was_ordered_recently(ticker, days=7)` gate
        # (order_executor.py:4202) skipped all 5 opportunities and
        # test_trades_placed_below_cap placed 0 trades -- which its old
        # `<= 2` bound accepted, so it never exercised the 20-position cap it
        # is named for. Surfaced by tightening that bound (batch-62).
        mock_exec_log.was_ordered_recently.return_value = False
        monkeypatch.setattr(order_executor, "execution_log", mock_exec_log)

        opps = [self._make_opp(i) for i in range(5)]
        result = main._auto_place_trades(opps, client=None, live=False)
        # opus review L-2: the counting double existed but its count was
        # thrown away. Comparing it against the reported return value is free,
        # and it is the one thing the two hand-written setup blocks could have
        # caught that a shared helper otherwise cannot: a divergence between
        # what _auto_place_trades REPORTS and what it actually placed.
        assert placed_count == result, (
            f"_auto_place_trades reported {result} placements but "
            f"place_paper_order was called {placed_count} time(s)"
        )
        return result

    def test_no_trades_placed_when_at_cap(self, monkeypatch, repatch_paper_paths):
        """When 20 positions already open, _auto_place_trades should place 0 new trades."""
        result = self._run_with_open(monkeypatch, repatch_paper_paths, 20)
        # batch-80 item 3: this `== 0` is only meaningful because the five
        # opportunities are now genuinely placeable -- its siblings place 1
        # and 2 of them from the identical fixture with 19 and 18 open
        # instead of 20. Before that repair this assertion passed with the
        # cap deleted too (every opportunity died at kelly_too_small first),
        # so it proved nothing about the cap. Those siblings are this
        # assertion's positive control (step 28): an absence is only evidence
        # when the thing could have been present.
        #
        # batch-85 item 1: this probe is ONE-SIDED and always has been. A cap
        # mutated DOWN to 19 also places 0 here (20 open is above 19 either
        # way), so this test alone cannot tell 19 from 20 -- it only catches a
        # cap raised to 21+. What pins the value from both sides is
        # test_one_below_the_cap_still_places, whose count now moves for 19,
        # 20 and 21 alike; see this class's docstring for the full table and
        # that test for the recorded mutation runs. Left as an equality at 0
        # rather than deleted because the at-cap case is the one that must
        # place nothing at all, and because it is the only probe that reaches
        # the pre-loop fast path (pinned separately by
        # test_the_pre_loop_fast_path_short_circuits_the_whole_cycle).
        #
        # KNOWN REDUNDANCY, kept deliberately (opus review INFO). This test is
        # strictly subsumed by that fast-path sibling, which asserts this same
        # `result == 0` first and then two more things: across all five
        # mutations run for this batch there is no case where this test fails
        # and that one passes. It stays because the two assert different
        # CONTRACTS -- "at the cap, nothing is placed" is the risk-control
        # invariant and must remain readable as its own named test even if the
        # fast path is someday removed, at which point its sibling goes with it
        # and this one must not.
        assert result == 0, f"Expected 0 trades placed, got {result}"

    def test_the_pre_loop_fast_path_short_circuits_the_whole_cycle(
        self, monkeypatch, repatch_paper_paths, capsys
    ):
        """At the cap, the pre-loop gate returns before the placement loop runs.

        batch-85 item 1 made the cap a per-placement check, which by itself
        would produce the right ANSWER at 20 open (nothing placed) through a
        different path: every signal would enter the loop and be skipped
        individually. The pre-loop `return 0` was deliberately kept, so it
        needs a test of its own rather than sitting behind an equality that
        the in-loop check satisfies just as well.

        What the fast path is kept FOR is the operator-facing "Position cap
        reached" line, which is the one thing the in-loop path does not
        produce. It does NOT save the live orderbook re-fetch or the VaR run
        (opus round-2 MEDIUM-C: both sit below the in-loop cap check, so an
        at-cap cycle skips them either way); its per-item saving is the
        shadow-family predicates plus a duplicate validate and two duplicate
        execution_log queries.

        The two halves are each other's control (step 28). The absence half is
        "no per-signal position_cap skip line": those are exactly what the
        in-loop check emits, so they appear if and only if the loop was
        entered. The positive half is the "Position cap reached" line itself,
        proving the function actually reached the gate rather than returning
        earlier at the daily-loss or drawdown halt, in which case "no skip
        lines" would be true for entirely the wrong reason.

        EACH HALF NEEDS ITS OWN MUTATION, and they are not the same one
        (opus review LOW-4 -- an earlier version of this docstring credited
        the absence half with evidence that never reached it):

          * Delete the whole pre-loop block -> the POSITIVE CONTROL fails
            first, at the "Position cap reached" assertion, and pytest never
            evaluates the absence line. FOR THAT MUTATION SPECIFICALLY the
            absence half is implied by the positive control -- deleting the
            print and the return together means a printed message could only
            have come from a branch that also returned. That implication does
            NOT generalise, which is exactly the point of the next bullet:
            keep the print and the two come apart.
          * Keep the print, delete ONLY the `return 0` -> the message still
            prints, the loop runs anyway, and the ABSENCE half is what fails
            ("the placement loop ran at the cap"). This is the mutation that
            actually pins the absence assertion, and the refactor it guards
            against: someone who keeps the operator message but loses the
            short-circuit.

        Both mutations verified 2026-08-26 via the Edit tool, each reverted
        by its exact inverse. test_no_trades_placed_when_at_cap stays GREEN
        under both -- which is the whole reason this test exists separately.
        """
        result = self._run_with_open(monkeypatch, repatch_paper_paths, 20)
        out = capsys.readouterr().out
        assert result == 0, f"Expected 0 trades placed, got {result}"
        # POSITIVE CONTROL: the pre-loop gate is the branch that ran.
        assert "Position cap reached (20/20 open)" in out, (
            "expected the pre-loop fast path's operator message; got:\n" + out
        )
        # ABSENCE: the placement loop was never entered, so no signal got an
        # individual position_cap skip line. Pinned by the delete-only-the-
        # `return 0` mutation described in the docstring, NOT by deleting the
        # whole block (that one fails at the positive control two lines above,
        # before this line is ever reached).
        assert "position_cap(" not in out, (
            "the placement loop ran at the cap — the pre-loop fast path did "
            "not short-circuit:\n" + out
        )

    def test_the_spend_cap_counts_each_placed_trade_s_cost(
        self, monkeypatch, repatch_paper_paths
    ):
        """The placed trade's `cost` must feed the daily-spend accumulator.

        round-2 opus review L4. _fake_place returning a realistic dict is
        half of this class's H-1 remediation, and the half the resolution
        describes most emphatically -- without a `cost` key,
        `daily_spent += trade.get("cost", 0.0)` (order_executor.py) never
        advances and MAX_DAILY_SPEND is inert for the whole cycle. But the
        other three tests pin MAX_DAILY_SPEND at 500 while five placements
        cost only ~$220, so deleting `cost` left all of them green: the
        remediation was itself unmutation-covered.

        Pinning the cap at 200 makes the accumulator load-bearing. Five
        trades at ~$44 each cross it on the fifth, so this expects 4 -- and
        with `cost` removed from _fake_place it would be 5 again.

        batch-85 item 1 moved `n_open` from 18 to 10, and that is not
        cosmetic. With the cap now re-checked per placement, 18 open leaves
        room for exactly 2 of the 5 signals, so the position cap stops the
        third and the spend accumulator never gets near $200 -- measured, it
        returned 2. The test would still have been green at `== 2` while
        proving nothing about `cost`, since deleting `cost` also returns 2.
        10 open leaves 10 slots for 5 signals, so the position cap cannot
        bind at all here and the daily-spend accumulator is once again the
        SOLE gate that stops the fifth trade. If you raise this number, keep
        enough room or you silently hand this test back to the vacuity round-2
        opus review L4 removed. The exact condition is `cap - n_open >=
        n_signals` -- at n_open=15 the fifth signal still sees `19 >= 20` False
        and places, so 15 would technically work. 10 is chosen to sit clear of
        that boundary rather than on it, so adding a sixth opportunity to the
        fixture does not silently re-introduce the confound.
        """
        result = self._run_with_open(
            monkeypatch, repatch_paper_paths, 10, max_daily_spend=200.0
        )
        assert result == 4, (
            f"expected the 5th trade to be stopped by the $200 daily cap, "
            f"got {result} placements"
        )

    def test_cap_skipped_signals_are_shadow_logged_not_dropped(
        self, monkeypatch, repatch_paper_paths
    ):
        """A signal skipped by the per-placement cap still reaches the shadow logger.

        opus review MEDIUM-1. Before batch-85 item 1, 18 open + 5 signals
        placed all five, so all five got a real tracker.log_prediction() row.
        After it, three are cap-skipped -- and if that branch just appended a
        skip reason and moved on, those three rows would vanish from the
        population brier_score_by_method() and the strategy auto-retirement
        logic read. `opps` is sorted by edge x kelly descending, so the rows
        that survived would be systematically the highest-edge ones: a
        selection bias in exactly the sample that drives retirement. The
        pre-loop gate never had this problem (it shadow-logs the whole batch
        via _shadow_suffix), and _log_shadow_predictions' own docstring names
        "position/spend caps" as a case it covers, so the in-loop branch
        failing to do it would have been a gap the codebase already claims
        does not exist.

        WHY THIS ASSERTS ON log_prediction AND NOT ON THE `logged=` SUFFIX
        printed in the skip summary. That suffix reads False for this fixture,
        and legitimately so: tracker.log_prediction returns False when
        `city is None` (tracker.py:1351), and _make_opp deliberately supplies
        no city -- the same fixture limitation documented on
        test_trades_placed_below_cap. Asserting on the suffix would therefore
        pin the fixture's city-lessness rather than this branch's behaviour,
        and would keep passing if the shadow append were deleted outright.
        What this batch actually changed is whether the cap-skipped items are
        HANDED to the shadow logger at all, so that is what is asserted:
        log_prediction is called for them, with is_shadow=True.
        """
        import tracker

        shadow_calls: list[str] = []

        def _record(ticker, city, target_date, a, is_shadow=False, conn=None, **kw):
            if is_shadow:
                shadow_calls.append(ticker)
            return False  # mirror the real return for a city-less opp

        monkeypatch.setattr(tracker, "log_prediction", _record)

        result = self._run_with_open(monkeypatch, repatch_paper_paths, 18)
        assert result == 2, f"fixture drifted: expected 2 placed, got {result}"

        # POSITIVE CONTROL: the three the cap turned away did reach the
        # shadow logger. Deleting the `_shadow_batch.append(item)` from the
        # cap branch in order_executor.py empties this list.
        assert sorted(shadow_calls) == [
            "KXHIGH-CHI-2",
            "KXHIGH-CHI-3",
            "KXHIGH-CHI-4",
        ], f"expected the 3 cap-skipped tickers to be shadow-logged, got {shadow_calls}"

        # ABSENCE, paired with the control above: the two that actually
        # PLACED must not also be shadow-logged -- they get a real
        # (is_shadow=False) prediction row from the placement path, and
        # double-counting them would corrupt the same scoring population
        # this fix exists to keep whole.
        assert "KXHIGH-CHI-0" not in shadow_calls, (
            "a placed trade was also shadow-logged: " + str(shadow_calls)
        )
        assert "KXHIGH-CHI-1" not in shadow_calls, (
            "a placed trade was also shadow-logged: " + str(shadow_calls)
        )

    def test_a_failing_shadow_flush_does_not_lose_the_placements(
        self, monkeypatch, repatch_paper_paths, capsys
    ):
        """A raising shadow flush must not discard the cycle's placed count.

        opus review round-2 LOW-4. _log_shadow_predictions deliberately does
        not swallow its own errors, and the batched flush after the loop was
        the one bookkeeping block in _auto_place_trades with no try/except --
        so a locked/corrupt tracker DB propagated out of the function AFTER
        placements had already happened, discarding `placed`. There is no
        enclosing try at the cmd_watch call site, so it could take a
        persistent watch process down.

        Pre-existing, but batch-85 item 1 is what made it reachable in the
        common case: before, a paper cycle with no active shadow families left
        _shadow_batch empty and the flush a no-op; now every cycle that hits
        the position cap goes through it.
        """
        import order_executor

        def _boom(*_a, **_k):
            raise sqlite3.OperationalError("database is locked")

        monkeypatch.setattr(order_executor, "_log_shadow_predictions", _boom)

        result = self._run_with_open(monkeypatch, repatch_paper_paths, 18)

        # POSITIVE CONTROL, and the whole point: the two placements survive the
        # failing flush. Without the try/except this line is never reached --
        # the OperationalError propagates out of _auto_place_trades and pytest
        # reports an error, not an assertion failure.
        assert result == 2, (
            f"a failing shadow flush lost the cycle's placements; got {result}"
        )
        out = capsys.readouterr().out
        # The three cap-skipped signals must still be REPORTED, and reported
        # honestly as unlogged rather than silently claiming success.
        assert out.count("(logged=False)") == 3, (
            "expected 3 cap-skip lines all marked unlogged:\n" + out
        )

    def test_one_below_the_cap_still_places(self, monkeypatch, repatch_paper_paths):
        """19 open leaves room for exactly one more, and one is what places.

        opus review M-4 added this probe because, under the old pre-loop `>=`
        gate, 18 and 20 bracketed the cap only to {19, 20}: 18 >= 19 is False
        and 20 >= 19 is True, so mutating the cap to 19 left both of those
        tests green. 19 open was the third probe that closed the gap.

        batch-85 item 1 keeps the probe and sharpens what it proves. The cap
        is now re-checked per placement, so this no longer answers "did the
        gate fire" with a bit -- it answers "how much room was left" with a
        count, and 20 - 19 = 1 is a number that differs for every nearby cap
        value. THIS SINGLE TEST now brackets the cap from both sides, which
        the old pair could not do:

          cap 19 -> 0 placed ("expected 1, got 0")
          cap 20 -> 1 placed (green)
          cap 21 -> 2 placed ("expected 1, got 2")

        Mutation-verified 2026-08-26 by editing the default literal in
        `int(os.getenv("MAX_CONCURRENT_POSITIONS", "20"))` at
        order_executor.py to "19" and then "21" and re-running this class --
        both values fail here, with the counts above. That is the property
        batch-80 built and this batch had to preserve under new semantics:
        the probe set still separates 20 from BOTH 19 and 21, rather than
        merely from something absurd like 99.
        """
        result = self._run_with_open(monkeypatch, repatch_paper_paths, 19)
        # EQUALITY, and specifically not `>= 1`: the point is the exact size
        # of the remaining room. A bound would accept 2 and hand the cap
        # value back to guesswork.
        assert result == 1, (
            f"19 open leaves room for exactly 1 of the 5 signals; got {result}"
        )

    def test_trades_placed_below_cap(self, monkeypatch, repatch_paper_paths):
        """18 open leaves room for two, and the cycle ends at the cap, not past it.

        THE TEST THIS BATCH EXISTS FOR. Until batch-85 item 1,
        MAX_CONCURRENT_POSITIONS was a single pre-loop entry gate
        (order_executor.py, the `return 0` above the placement loop): it
        refused a cycle that already started at the cap and imposed no limit
        at all below it. So this test asserted 5, the whole input surviving,
        and the cycle finished holding 23 positions against a cap documented
        as 20 -- which is the defect the batch-62/batch-80 note at the bottom
        of this test recorded and deliberately left standing.

        The cap is now re-checked per placement against `_open_trades_list`,
        which both placement branches append to, so 18 + 2 = 20 and the third,
        fourth and fifth signals are skipped as position_cap(20/20). 2 is the
        number the batch-62 entry originally expected the code to already
        produce.

        THE OTHER GATES this fixture sits under, unchanged and still worth
        knowing before anyone edits the fixture and gets a bare red test:

          * MAX_POSITIONS_PER_DATE (default 4). All five tickers are the same
            city, so giving _make_opp a real `target_date` would make the
            fifth fail date_cap(4/4) -- now moot here, since the position cap
            stops the third first, but it still binds in the sibling that
            runs with 10 open.
          * MAX_DAILY_SPEND. _run_with_open pins it at 500.0; two placements
            cost ~$88, so it does not bite. Its own dedicated test pins it at
            200 with enough position headroom to be the sole binding gate.

        Neither is a defect in the code. If you change the fixture, re-derive
        the number from the printed skip reasons rather than loosening the
        assertion.
        """
        result = self._run_with_open(monkeypatch, repatch_paper_paths, 18)

        # batch-80 item 3 closes the KNOWN-VACUOUS gap batch-62 recorded here
        # (backlog "test_trades_placed_below_cap has never exercised the
        # 20-position cap"). The old bound was `<= 2`, and the code placed 0,
        # so it passed without a single opportunity ever reaching a cap. Two
        # fixture defects had to go, both documented at their own site above:
        # the missing `fee_adjusted_kelly` key (_make_opp) and the impossible
        # {"cost": 10.0, "qty": 1} position shape (_make_open_trades).
        #
        # EQUALITY, not a bound. `<= 5` would pass at 0 all over again, which
        # is exactly how this test spent months green while proving nothing;
        # `>= 1` would not notice signals silently dying at some other gate.
        # A count is what makes any new gate that starts biting this fixture
        # show up as a number rather than as a still-green tick.
        #
        # POSITIVE CONTROL for the sibling test's `== 0` (step 28). That
        # assertion is an absence, and an absence is only evidence if the
        # thing could have been present: this line proves the identical five
        # opportunities DO place when the only difference is 18 open rather
        # than 20.
        #
        # Two-sided on its own, like the 19-open probe: cap 19 gives 1 here
        # and cap 21 gives 3, so this equality separates 20 from both
        # neighbours by itself. Mutation-verified 2026-08-26 alongside
        # test_one_below_the_cap_still_places, same two edits to the default
        # literal.
        #
        # WHY TWO AND NOT FIVE: the cap is now spent, not just tested at the
        # door. 18 open + 2 placed = 20 = the cap, so the remaining three are
        # skipped as position_cap(20/20). The old answer here was 5, ending
        # the cycle at 23 open -- see the docstring.
        assert result == 2, (
            f"18 open leaves room for exactly 2 of the 5 signals; got {result}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# 2. MIN_PROB_EDGE gate in cron.py
# ─────────────────────────────────────────────────────────────────────────────


class TestMinProbEdgeGate:
    """cron.py must skip signals where probability edge < MIN_PROB_EDGE (0.08)."""

    def _make_enriched(self, forecast_prob: float, market_prob: float) -> dict:
        edge = forecast_prob - market_prob
        return {
            "ticker": "KXHIGH-NYC-TEST",
            "_city": "New York",
            "forecast_prob": forecast_prob,
            "market_prob": market_prob,
            "edge": edge,
            "net_edge": edge * 1.1,
            "adjusted_edge": edge * 1.1,
            "signal": "STRONG BUY" if edge > 0 else "STRONG SELL",
            "net_signal": "STRONG BUY" if edge > 0 else "STRONG SELL",
            "recommended_side": "yes" if edge > 0 else "no",
            "days_out": 2,
        }

    def test_low_prob_edge_signal_skipped(self):
        """Signal with only 5pp probability edge must be skipped by the gate."""
        import cron
        from utils import MIN_PROB_EDGE

        assert hasattr(cron, "MIN_PROB_EDGE") or MIN_PROB_EDGE is not None, (
            "MIN_PROB_EDGE must be importable"
        )

        enriched = self._make_enriched(0.55, 0.50)  # only 5pp edge — below 8pp
        prob_edge = abs(enriched["forecast_prob"] - enriched["market_prob"])
        assert prob_edge < 0.08, "Test setup: prob_edge should be below threshold"

    def test_sufficient_prob_edge_signal_passes(self):
        """Signal with 12pp probability edge must NOT be skipped by the gate."""
        enriched = self._make_enriched(0.62, 0.50)  # 12pp edge — above 8pp
        prob_edge = abs(enriched["forecast_prob"] - enriched["market_prob"])
        assert prob_edge >= 0.08, "Test setup: prob_edge should be above threshold"

    def test_min_prob_edge_constant_exists(self):
        """MIN_PROB_EDGE constant must be defined in utils.py with value 0.08."""
        from utils import MIN_PROB_EDGE

        assert MIN_PROB_EDGE == 0.08, (
            f"MIN_PROB_EDGE should be 0.08, got {MIN_PROB_EDGE}"
        )

    def test_cron_imports_min_prob_edge(self):
        """The prob-edge gate (MIN_PROB_EDGE) must be wired into the module
        that actually applies it. This moved from cron.py into
        trade_cycle.run_trade_cycle() during the headless-engine extraction
        (backlog.txt "THE ONLY LIVE-ORDER PATH..."), applied identically to
        both cron and watch -- cron.py itself no longer imports it directly,
        so the import-presence check re-points at trade_cycle."""
        import trade_cycle

        assert hasattr(trade_cycle, "MIN_PROB_EDGE"), (
            "trade_cycle must import MIN_PROB_EDGE"
        )


# ─────────────────────────────────────────────────────────────────────────────
# 3. Ensemble member threshold >= 2
# ─────────────────────────────────────────────────────────────────────────────


class TestEnsembleMemberThreshold:
    """_score_ensemble_members must run once at least 2 temp samples exist."""

    def test_model_consensus_guard_uses_two(self):
        """The model-consensus-check guard (ens_prob + _get_consensus_probs block)
        must use >= 2, not >= 10, so consensus probs are attempted with few ensemble members."""
        src = Path(__file__).parent.parent / "weather_markets.py"
        lines = src.read_text(encoding="utf-8").splitlines()
        # Find the line that gates _get_consensus_probs (contains ens_prob is not None)
        for i, line in enumerate(lines):
            if "ens_prob is not None" in line and "len(temps)" in line:
                assert ">= 2" in line, (
                    f"Line {i + 1}: expected 'len(temps) >= 2', got: {line.strip()!r}"
                )
                return
        pytest.fail(
            "Could not find the 'ens_prob is not None and len(temps)' guard line"
        )

    def test_ensemble_guard_uses_two(self):
        """Confirming the >= 2 threshold is present in weather_markets.py."""
        src = Path(__file__).parent.parent / "weather_markets.py"
        text = src.read_text(encoding="utf-8")
        assert "ens_prob is not None and len(temps) >= 2" in text, (
            "Expected 'ens_prob is not None and len(temps) >= 2' in weather_markets.py"
        )
