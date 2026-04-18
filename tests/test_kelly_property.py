"""Property-based tests for Kelly sizing using Hypothesis."""

from __future__ import annotations

from hypothesis import assume, given, settings
from hypothesis import strategies as st

# ── Task 8.1: Property-based Kelly tests ─────────────────────────────────────


@given(
    our_prob=st.floats(min_value=0.05, max_value=0.95),
    price=st.floats(min_value=0.05, max_value=0.95),
    fee_rate=st.floats(min_value=0.0, max_value=0.15),
)
@settings(max_examples=200)
def test_kelly_fraction_never_negative(our_prob, price, fee_rate):
    """kelly_fraction always returns a non-negative value."""
    from weather_markets import kelly_fraction

    result = kelly_fraction(our_prob, price, fee_rate)
    assert result >= 0.0


@given(
    our_prob=st.floats(min_value=0.05, max_value=0.95),
    price=st.floats(min_value=0.05, max_value=0.95),
)
@settings(max_examples=200)
def test_kelly_fraction_never_exceeds_cap(our_prob, price):
    """kelly_fraction never exceeds the hard cap of 0.33."""
    from weather_markets import kelly_fraction

    result = kelly_fraction(our_prob, price)
    assert result <= 0.33


@given(
    kelly_frac=st.floats(min_value=0.0, max_value=0.25),
    price=st.floats(min_value=0.01, max_value=0.99),
)
@settings(max_examples=200)
def test_kelly_quantity_cost_never_exceeds_balance(kelly_frac, price):
    """kelly_quantity cost (qty * price) never exceeds current balance."""
    import tempfile
    from pathlib import Path
    from unittest.mock import patch

    import paper

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp) / "paper_trades.json"
        with patch.object(paper, "DATA_PATH", tmp_path):
            balance = paper.get_balance()
            qty = paper.kelly_quantity(kelly_frac, price)
            cost = qty * price
            assert cost <= balance + 0.01  # allow floating-point tolerance


@given(
    our_prob=st.floats(min_value=0.55, max_value=0.95),
    price=st.floats(min_value=0.05, max_value=0.45),
)
@settings(max_examples=200)
def test_kelly_positive_edge_gives_nonzero_fraction(our_prob, price):
    """When our_prob significantly beats price (positive edge), Kelly > 0."""
    from weather_markets import kelly_fraction

    assume(our_prob > price + 0.05)  # meaningful edge
    result = kelly_fraction(our_prob, price)
    assert result > 0.0


@given(
    our_prob=st.floats(min_value=0.05, max_value=0.45),
    price=st.floats(min_value=0.55, max_value=0.95),
)
@settings(max_examples=200)
def test_kelly_negative_edge_gives_zero_fraction(our_prob, price):
    """When market price exceeds our_prob (negative edge), Kelly = 0."""
    from weather_markets import kelly_fraction

    assume(price > our_prob + 0.05)  # clear negative edge
    result = kelly_fraction(our_prob, price)
    assert result == 0.0


@given(
    our_prob=st.floats(min_value=0.5, max_value=0.9),
    price=st.floats(min_value=0.2, max_value=0.5),
)
@settings(max_examples=100)
def test_kelly_monotone_in_prob(our_prob, price):
    """Higher our_prob → higher or equal Kelly fraction (monotone)."""
    from weather_markets import kelly_fraction

    assume(our_prob + 0.05 <= 0.95)
    f1 = kelly_fraction(our_prob, price)
    f2 = kelly_fraction(our_prob + 0.05, price)
    assert f2 >= f1 - 1e-9  # allow floating-point tolerance
