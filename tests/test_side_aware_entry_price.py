"""batch-26 item 3: main.py's cmd_market passed prices["implied_prob"]
(always the YES mid) into kelly_quantity() unconditionally, regardless of
analysis["recommended_side"] -- overcounting the displayed contract count
for every NO recommendation (dividing by the YES price instead of the
higher NO cost). Reproduces the audit's exact repro: $1000 balance, YES mid
0.30, kelly 0.01 -- shipped quantity 33 contracts (÷0.30), correct quantity
14 contracts (÷0.70)."""

from unittest.mock import MagicMock

import pytest

from main import _side_aware_entry_price


def _prices(yes_bid=None, yes_ask=None, implied_prob=0.5):
    return {
        "yes_bid": yes_bid if yes_bid is not None else implied_prob,
        "yes_ask": yes_ask if yes_ask is not None else implied_prob,
        "implied_prob": implied_prob,
    }


class TestSideAwareEntryPrice:
    def test_yes_side_uses_yes_ask(self):
        prices = _prices(yes_bid=0.28, yes_ask=0.32, implied_prob=0.30)
        assert _side_aware_entry_price("YES", prices) == 0.32
        # Positive control: not the mid, not the bid.
        assert _side_aware_entry_price("YES", prices) != prices["implied_prob"]
        assert _side_aware_entry_price("YES", prices) != prices["yes_bid"]

    def test_no_side_uses_one_minus_yes_bid_not_the_yes_mid(self):
        """The as-shipped bug's exact reproduction: NO recommendation at
        implied_prob (YES mid) 0.30 must price at 1 - yes_bid (~0.70-ish),
        not 0.30."""
        prices = _prices(yes_bid=0.28, yes_ask=0.32, implied_prob=0.30)
        result = _side_aware_entry_price("NO", prices)
        assert result == 1.0 - 0.28
        assert result != prices["implied_prob"]

    def test_side_is_case_insensitive(self):
        prices = _prices(yes_bid=0.28, yes_ask=0.32, implied_prob=0.30)
        assert _side_aware_entry_price("no", prices) == _side_aware_entry_price(
            "NO", prices
        )
        assert _side_aware_entry_price("yes", prices) == _side_aware_entry_price(
            "YES", prices
        )

    def test_audit_repro_no_side_quantity_matches_correct_not_shipped_value(self):
        """Full audit repro: $1000 balance, YES mid 0.30, kelly=0.01 --
        shipped quantity was 33 (÷0.30), correct is 14 (÷0.70)."""
        import paper

        prices = _prices(yes_bid=0.30, yes_ask=0.30, implied_prob=0.30)
        entry_price = _side_aware_entry_price("NO", prices)
        assert entry_price == 0.70

        correct_qty = paper.kelly_quantity(0.01, entry_price, balance_override=1000.0)
        buggy_qty = paper.kelly_quantity(
            0.01, prices["implied_prob"], balance_override=1000.0
        )
        assert correct_qty == 14
        assert buggy_qty == 33
        assert correct_qty != buggy_qty

    def test_no_side_falls_back_to_one_minus_mid_when_yes_bid_is_zero(self):
        """yes_bid == 0 (no real bid on the book) -- not a live quote to
        trust -- falls back to 1 - implied_prob, matching
        weather_markets._price_and_size's exact convention (opus-review-
        caught: an earlier draft gated this on the coarser "has_quote" flag
        -- true whenever yes_ask alone is nonzero -- which returned a
        degenerate 1.0 price here instead of the correct fallback)."""
        prices = _prices(yes_bid=0.0, yes_ask=0.62, implied_prob=0.40)
        result = _side_aware_entry_price("NO", prices)
        assert result == 1.0 - 0.40
        # Positive control: prove this isn't coincidentally the "correct"
        # value some OTHER formula would produce -- 1 - yes_bid (the
        # coarse-check bug's actual output) is 1.0, clearly wrong.
        assert result != 1.0 - prices["yes_bid"]

    def test_yes_side_falls_back_to_mid_when_yes_ask_is_zero(self):
        prices = _prices(yes_bid=0.0, yes_ask=0.0, implied_prob=0.45)
        result = _side_aware_entry_price("YES", prices)
        assert result == 0.45

    def test_no_side_with_yes_bid_at_one_falls_back_rather_than_zero_price(self):
        """A degenerate yes_bid=1.0 (empty/one-sided book edge case) would
        compute 1-1=0.0 -- must not silently divide-by-zero-adjacent
        downstream; the <=0 guard falls back to the implied_prob-derived
        value instead."""
        prices = _prices(yes_bid=1.0, yes_ask=1.0, implied_prob=0.95)
        result = _side_aware_entry_price("NO", prices)
        assert result > 0
        assert result == max(0.01, 1.0 - 0.95)


# ── batch-26 item 3 wiring: cmd_market actually calls kelly_quantity with the
# side-aware price (opus-review-caught MEDIUM-2: the leaf-function tests above
# prove _side_aware_entry_price is correct in isolation, but nothing proved
# cmd_market's own kelly_quantity call sites actually use it -- reverting
# _entry_price_ci back to prices["implied_prob"] passed the full suite
# silently). ──────────────────────────────────────────────────────────────────


def test_cmd_market_no_side_calls_kelly_quantity_with_side_aware_price(monkeypatch):
    import main

    market = {
        "ticker": "KXHIGH-26AUG22-T80",
        "title": "Test market",
        "close_time": "2099-01-01T00:00:00Z",
        "yes_bid": 54,
        "yes_ask": 56,
        "volume_fp": "0.00",
        "open_interest_fp": "0.00",
    }
    analysis = {
        "edge": -0.10,
        "forecast_prob": 0.30,
        "recommended_side": "no",
        "net_edge": 0.20,
        "fee_adjusted_kelly": 0.10,
        "ci_adjusted_kelly": 0.10,
        "signal": "STRONG SELL",
        "condition": {"type": "above", "threshold": 80.0},
    }

    client = MagicMock()
    client.get_market.return_value = market

    monkeypatch.setattr(main, "enrich_with_forecast", lambda m, **kw: {})
    monkeypatch.setattr(main, "analyze_trade", lambda enriched: analysis)
    monkeypatch.setattr(main, "is_liquid", lambda m: True)
    monkeypatch.setattr(main, "log_prediction", lambda *a, **kw: None)

    captured_prices = []

    def spy_kelly_quantity(kf, price, **kw):
        captured_prices.append(price)
        return 5

    monkeypatch.setattr("paper.kelly_quantity", spy_kelly_quantity)
    monkeypatch.setattr("paper.kelly_bet_dollars", lambda kf, **kw: 50.0)

    main.cmd_market(client, "KXHIGH-26AUG22-T80", verbose=False)

    assert len(captured_prices) == 1, "kelly_quantity must be called exactly once"
    # Correct NO-side price (1 - yes_bid = 0.46), not the YES mid (0.55)
    # prices["implied_prob"] would have passed pre-fix.
    assert captured_prices[0] == pytest.approx(1.0 - 0.54)
    assert captured_prices[0] != pytest.approx(0.55, abs=0.01)
