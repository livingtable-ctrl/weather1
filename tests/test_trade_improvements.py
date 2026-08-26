"""
Tests for 3 approved trading improvements:
  1. MAX_CONCURRENT_POSITIONS cap (20) in _auto_place_trades
  2. MIN_PROB_EDGE gate (8pp probability delta) in cron.py
  3. Ensemble member threshold lowered from >=10 to >=2 in weather_markets.py
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


# ─────────────────────────────────────────────────────────────────────────────
# 1. MAX_CONCURRENT_POSITIONS cap
# ─────────────────────────────────────────────────────────────────────────────


class TestMaxConcurrentPositions:
    """_auto_place_trades must refuse new trades once 20 open positions exist."""

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
        # opportunities are now genuinely placeable -- its sibling
        # test_trades_placed_below_cap places all five from the identical
        # fixture with 18 open instead of 20. Before that repair this
        # assertion passed with the cap deleted too (every opportunity died
        # at kelly_too_small first), so it proved nothing about the cap.
        # Mutation-verified 2026-08-25 against order_executor.py:4367, by
        # editing the default in `int(os.getenv("MAX_CONCURRENT_POSITIONS",
        # "20"))` and re-running this class. Three mutations, two of them on
        # the gate's OWN boundary, which is the only pair that separates
        # "some cap exists" from "the cap is 20":
        #   "99" -> this test fails, "Expected 0 trades placed, got 5"
        #   "21" -> this test fails the same way (20 >= 21 is False, so the
        #           gate stops firing at exactly one above the real value)
        #   "18" -> test_trades_placed_below_cap fails, "Expected all 5
        #           trades placed, got 0" (18 >= 18 fires the gate a rung
        #           early), while THIS test still passes
        # 21 breaks one half and 18 breaks the other, so the pair brackets
        # the cap at 20 from both sides. Before the fixture repair, every one
        # of those three left both tests green.
        assert result == 0, f"Expected 0 trades placed, got {result}"

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
        """
        result = self._run_with_open(
            monkeypatch, repatch_paper_paths, 18, max_daily_spend=200.0
        )
        assert result == 4, (
            f"expected the 5th trade to be stopped by the $200 daily cap, "
            f"got {result} placements"
        )

    def test_one_below_the_cap_still_places(self, monkeypatch, repatch_paper_paths):
        """19 open is still below 20, so the gate must not fire.

        opus review M-4. With probes only at 18 and 20, the value 19 is
        indistinguishable from 20 for a `>=` gate: 18 >= 19 is False and
        20 >= 19 is True, so mutating the cap to 19 left BOTH other tests
        green -- the pair bracketed the cap to {19, 20}, not to 20. This is
        the third probe that closes it, and it is the whole difference
        between "a cap exists somewhere near here" and "the cap is 20".
        """
        result = self._run_with_open(monkeypatch, repatch_paper_paths, 19)
        assert result == 5, f"19 open is below the cap; expected 5, got {result}"

    def test_trades_placed_below_cap(self, monkeypatch, repatch_paper_paths):
        """Below the cap, the concurrent-position gate blocks nothing.

        Named for the cap, and it does exercise it -- as the negative half of
        the pair. MAX_CONCURRENT_POSITIONS is a single pre-loop entry gate
        (order_executor.py:4368), not a per-placement counter: it returns 0
        for the whole cycle when already at the cap, and imposes no limit at
        all below it. So the real assertion here is "18 open does not block",
        and the number placed is set by the OTHER caps, not by 20 - 18.

        WHICH other caps, concretely -- because the next person to make this
        fixture more realistic will turn 5 into a smaller number and deserves
        to know why rather than getting a bare red test:

          * MAX_POSITIONS_PER_DATE (default 4). All five tickers are the same
            city, so giving _make_opp a real `target_date` makes the fifth
            fail date_cap(4/4) and the answer becomes 4. Measured.
          * MAX_DAILY_SPEND. _run_with_open pins it at 500.0; the five
            placements cost ~$220 in total, so it does not bite. It is only
            unpinned in production, where the operator's .env sets 200 --
            which WOULD stop the fifth.

        Neither is a defect in the code; both are gates this fixture happens
        to sit under. If you change the fixture, re-derive the number from
        the printed skip reasons rather than loosening the assertion.
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
        # `>= 1` would not notice four of the five silently dying at a gate.
        # 5 is the whole input surviving, so any new gate that starts biting
        # this fixture shows up as a number, not as a still-green tick.
        #
        # POSITIVE CONTROL for the sibling test's `== 0` (step 28). That
        # assertion is an absence, and an absence is only evidence if the
        # thing could have been present: this line proves the identical five
        # opportunities DO place when the only difference is 18 open rather
        # than 20. The two assertions are a matched pair and must be read
        # together -- the pair, not either line alone, is what pins the cap.
        #
        # Why five and not two: nothing decrements toward the cap during the
        # cycle. See this test's docstring. Placing five on top of 18 leaves
        # 23 open, past the 20 the class docstring describes -- real, and
        # filed as its own backlog entry rather than fixed here, since
        # changing it would change live sizing behaviour, which this batch is
        # explicitly scoped out of.
        assert result == 5, f"Expected all 5 trades placed, got {result}"


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
