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
    """kelly_fraction never exceeds the hard cap (KELLY_CAP = 0.25)."""
    from utils import KELLY_CAP
    from weather_markets import kelly_fraction

    result = kelly_fraction(our_prob, price)
    assert result <= KELLY_CAP


@given(
    kelly_frac=st.floats(min_value=0.0, max_value=0.25),
    price=st.floats(min_value=0.01, max_value=0.99),
)
# deadline=None (batch-80 item 4). This test flaked with hypothesis'
# DeadlineExceeded under machine load, reproduced on unmodified master.
# The deadline is the wrong instrument here: what it actually times is this
# test's OWN per-example fixture I/O (a TemporaryDirectory created and torn
# down 200 times over), not kelly_quantity(), which is pure arithmetic and
# cannot regress in a way a wall clock would catch. Measured 2026-08-25:
# ~0.57s for all 200 examples (~3ms each) against a 200ms default, so a
# failure needs a ~65x stall -- i.e. an external stall, never a code change.
#
# Ruled OUT as the cause before retuning (the batch-80 handoff asked for
# this explicitly): tests/conftest.py's default-deny network guard
# (3cca1e8e) and real-data/-write blocker (27949ffa). Both landed
# 2026-08-25 -- the handoff said 2026-08-26, which `git log` contradicts and
# which would be tomorrow (opus review L-5). Timed at 95b0df4c, the true
# parent of 3cca1e8e, in a throwaway worktree: 0.57-0.58s, versus
# 0.57-0.59s with both present.
# They cost roughly 0.25ms per example, against ~197ms of headroom -- they
# did not move this test measurably closer to the deadline.
#
# Strict on VALUES, lenient on TIME: the assertion below is a financial
# invariant (cost never exceeds balance) and is deliberately left untouched,
# as is max_examples. Only the clock is dropped. The five tests in this file
# that do no I/O keep their default deadline.
#
# CONSIDERED AND DECLINED (opus review L-6): a generous ceiling --
# deadline=timedelta(seconds=2), ~600x the measured per-example cost --
# rather than None. It would keep an order-of-magnitude tripwire and would
# not have flaked under the load that produced the original report. Declined
# because what the clock measures here is this test's own per-example
# TemporaryDirectory churn, so the tripwire would guard fixture I/O rather
# than kelly_quantity, and the stall behind the report was unbounded rather
# than merely large -- a 2s ceiling narrows the flake window without closing
# it. A real perf guard for kelly_quantity belongs on the function.
@settings(max_examples=200, deadline=None)
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


@given(
    kelly_frac=st.floats(min_value=0.0, max_value=0.25),
    drawdown_scale=st.floats(min_value=0.0, max_value=1.0),
    balance=st.floats(min_value=10.0, max_value=10_000.0),
)
# deadline=None -- same reasoning, same evidence, as
# test_kelly_quantity_cost_never_exceeds_balance above (batch-80 item 4).
# This one is the slower of the two because each example also WRITES the
# ledger file (a per-example `balance` is the whole point of the property),
# so its fixture I/O is strictly larger and its measured ~0.63s/200 examples
# strictly closer to the deadline -- and equally unrelated to the invariant.
@settings(max_examples=200, deadline=None)
def test_kelly_bet_dollars_never_exceeds_balance(kelly_frac, drawdown_scale, balance):
    """P3-3: kelly_bet_dollars * drawdown_scaling_factor must never exceed current balance.

    The product represents the maximum dollar exposure per trade. A rounding
    error or unclamped multiplier should not allow it to exceed the account balance.
    """
    import tempfile
    from pathlib import Path
    from unittest.mock import patch

    import paper

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp) / "paper_trades.json"
        tmp_path.write_text(
            f'{{"_version": 2, "balance": {balance}, "peak_balance": {balance}, "trades": []}}'
        )
        with (
            patch.object(paper, "DATA_PATH", tmp_path),
            patch.object(paper, "drawdown_scaling_factor", lambda: drawdown_scale),
            patch.object(paper, "is_streak_paused", lambda *_a, **_k: False),
            patch.object(paper, "_method_kelly_multiplier", lambda method: 1.0),
            patch.object(paper, "_dynamic_kelly_cap", lambda: balance * 2),
        ):
            dollars = paper.kelly_bet_dollars(kelly_frac)
            # The resulting dollar bet must never exceed the current balance.
            assert dollars <= balance + 0.01, (
                f"kelly_bet_dollars={dollars:.4f} > balance={balance:.4f} "
                f"(kelly_frac={kelly_frac}, drawdown_scale={drawdown_scale})"
            )
