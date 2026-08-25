"""Tests for utils.kalshi_fee_rate_at and utils.required_gross_edge — batch-66
item 2 (A10), "a flat 6% edge floor is not the same threshold at 20c as at 80c".

Every expected value here is hand-computed in the test's own comment from the
formula, never copied from a run of the function.

`required_gross_edge` is DISPLAY-ONLY -- nothing in the sizing, gating or order
path reads it. `kalshi_fee_rate_at` is NOT: order_executor._clears_taker_fee
(a live gate deciding whether to cross the book as taker) calls it, which is
why its out-of-range behaviour is pinned below rather than left to the
docstring. That gate is covered in test_live_execution.py.
"""

from __future__ import annotations

import pytest

import utils


class TestKalshiFeeRateAt:
    def test_taker_rate_is_unrounded_curve(self):
        # 0.07 * 0.20 * 0.80 = 0.0112 -- NOT the $0.02 that kalshi_taker_fee(1,
        # 0.20) returns after rounding a single contract up to a whole cent.
        assert utils.kalshi_fee_rate_at(0.20) == pytest.approx(0.0112)
        # Positive control that the rounding difference this guards is real:
        # the rounded helper genuinely returns something else at this price.
        assert utils.kalshi_taker_fee(1, 0.20) == pytest.approx(0.02)

    def test_peaks_at_fifty_cents(self):
        # 0.07 * 0.50 * 0.50 = 0.0175/contract, Kalshi's published maximum.
        assert utils.kalshi_fee_rate_at(0.50) == pytest.approx(0.0175)
        # Symmetric about 0.50, and strictly lower away from it.
        assert utils.kalshi_fee_rate_at(0.20) == pytest.approx(
            utils.kalshi_fee_rate_at(0.80)
        )
        assert utils.kalshi_fee_rate_at(0.20) < utils.kalshi_fee_rate_at(0.50)

    def test_maker_rate_is_zero_by_default(self):
        # KALSHI_MAKER_FEE_RATE defaults to 0.0: this bot's weather series carry
        # maker multiplier M=0, so a resting fill genuinely pays nothing.
        assert utils.kalshi_fee_rate_at(0.50, taker=False) == 0.0

    def test_maker_rate_honours_operator_override(self, monkeypatch):
        """Absence-assertion above is paired with this positive control.

        Without it, "maker rate is 0" would keep passing if the function had
        been hardcoded to return 0 and ignored the constant entirely.
        """
        monkeypatch.setattr(utils, "KALSHI_MAKER_FEE_RATE", 0.0175)
        # 0.0175 * 0.50 * 0.50 = 0.004375
        assert utils.kalshi_fee_rate_at(0.50, taker=False) == pytest.approx(0.004375)

    def test_zero_at_the_boundaries(self):
        assert utils.kalshi_fee_rate_at(0.0) == 0.0
        assert utils.kalshi_fee_rate_at(1.0) == 0.0

    @pytest.mark.parametrize("bad", [-0.1, 1.5, 20, 100])
    def test_out_of_range_price_raises_rather_than_crediting(self, bad):
        """P*(1-P) goes NEGATIVE outside [0,1], i.e. the fee becomes a credit.

        The realistic way in is a cents-vs-dollars slip: price=20 gives
        -26.6. Since this feeds required_gross_edge, a negative fee would
        silently LOWER the bar beside a trading gate, so it must fail loudly.
        """
        with pytest.raises(ValueError, match="must be in"):
            utils.kalshi_fee_rate_at(bad)
        with pytest.raises(ValueError, match="must be in"):
            utils.required_gross_edge(bad)

    def test_in_range_prices_do_not_raise(self):
        """Positive control for the raise above -- the guard is a bound, not a
        blanket rejection that would make the function useless."""
        for ok in (0.0, 0.01, 0.5, 0.99, 1.0):
            utils.kalshi_fee_rate_at(ok)
            utils.required_gross_edge(ok)


class TestRequiredGrossEdge:
    def test_maker_requirement_scales_linearly_with_price(self):
        """The batch's actual question, answered.

        required_gross_edge = F*P + fee(P). For a maker fill fee(P) is 0, so at
        F=0.07 the requirement is exactly 0.07*P:
            P=0.20 -> 0.014   (1.4 probability points)
            P=0.80 -> 0.056   (5.6 probability points)
        A 4x swing across the price range with the fee contributing zero -- the
        price-dependence is real but comes from net_edge dividing by cost, not
        from the fee the handoff assumed was driving it.
        """
        assert utils.required_gross_edge(0.20, min_edge=0.07) == pytest.approx(0.014)
        assert utils.required_gross_edge(0.80, min_edge=0.07) == pytest.approx(0.056)

    def test_taker_adds_the_curved_fee_symmetrically(self):
        # taker = F*P + 0.07*P*(1-P):
        #   P=0.20 -> 0.014 + 0.0112 = 0.0252
        #   P=0.80 -> 0.056 + 0.0112 = 0.0672
        # The fee term is IDENTICAL at both prices (symmetric about 0.50); only
        # the F*P term differs. Pins which half carries the price-dependence.
        assert utils.required_gross_edge(
            0.20, min_edge=0.07, taker=True
        ) == pytest.approx(0.0252)
        assert utils.required_gross_edge(
            0.80, min_edge=0.07, taker=True
        ) == pytest.approx(0.0672)
        fee_term_lo = utils.required_gross_edge(
            0.20, min_edge=0.07, taker=True
        ) - utils.required_gross_edge(0.20, min_edge=0.07)
        fee_term_hi = utils.required_gross_edge(
            0.80, min_edge=0.07, taker=True
        ) - utils.required_gross_edge(0.80, min_edge=0.07)
        assert fee_term_lo == pytest.approx(fee_term_hi)

    def test_defaults_to_maker(self):
        """Pins the default, which is a real decision, not a formality.

        The bot's initial ENTRY is always a resting midpoint GTC limit order,
        so maker is the fee that entry actually pays, and defaulting to taker
        would overstate every displayed requirement by the fee term. Not a
        blanket claim about the bot: the reprice branch can cross as taker and
        protective exits are IOC, which is what taker=True is for.
        """
        assert utils.required_gross_edge(0.35) == pytest.approx(
            utils.required_gross_edge(0.35, taker=False)
        )
        assert utils.required_gross_edge(0.35) != pytest.approx(
            utils.required_gross_edge(0.35, taker=True)
        )

    def test_min_edge_default_resolves_at_call_time(self, monkeypatch):
        """The default is resolved in the BODY, not bound as a default argument.

        What late binding actually buys, stated precisely: MIN_EDGE is itself a
        module constant evaluated once at utils import, so this does NOT pick
        up a .env loaded after import. It buys respecting a runtime REBIND of
        the attribute — main.py's settings screen does importlib.reload(utils),
        and tests monkeypatch it, which is exactly what this test exercises. A
        round-2 opus review caught an earlier version of this docstring
        claiming the stronger, false property.
        """
        before = utils.required_gross_edge(0.50)
        monkeypatch.setattr(utils, "MIN_EDGE", 0.99)
        # Resolved in the body, so a monkeypatched MIN_EDGE IS picked up.
        assert utils.required_gross_edge(0.50) == pytest.approx(0.495)
        assert utils.required_gross_edge(0.50) != pytest.approx(before)
        # Explicit argument still wins over the module constant.
        assert utils.required_gross_edge(0.50, min_edge=0.07) == pytest.approx(0.035)

    def test_round_trip_against_the_net_edge_definition(self):
        """A forecast exactly at the requirement produces net_edge == min_edge.

        This is the property the helper exists to express, checked against the
        definition of net_edge itself (EV per dollar of cost) rather than
        against a restatement of the same formula:
            p = P + required_gross_edge(P)  =>  (p - P - fee)/P == F
        """
        for price in (0.15, 0.35, 0.50, 0.80):
            for taker in (False, True):
                req = utils.required_gross_edge(price, min_edge=0.07, taker=taker)
                p = price + req
                fee = utils.kalshi_fee_rate_at(price, taker=taker)
                net_edge = (p * (1 - price) - (1 - p) * price - fee) / price
                assert net_edge == pytest.approx(0.07), (price, taker)
