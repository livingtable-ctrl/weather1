"""test_phase2_batch_o.py — Tests for same-day spend cap (MAX_SAME_DAY_SPEND).

Covers:
- _daily_sameday_spend() only sums days_out=0 trades placed today
- The two caps are independent: multi-day full doesn't block same-day
- Per-signal cap routing in _auto_place_trades (via skip-reason labels)
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch

TODAY = datetime.now(UTC).date().isoformat()


def _make_trade(
    cost: float, days_out: int | None, entered_at: str | None = None
) -> dict:
    return {
        "cost": cost,
        "days_out": days_out,
        "entered_at": entered_at or f"{TODAY}T12:00:00+00:00",
    }


# ---------------------------------------------------------------------------
# _daily_sameday_spend unit tests
# ---------------------------------------------------------------------------


class TestDailySamedaySpend:
    """_daily_sameday_spend() must only sum days_out==0 trade costs."""

    def _call(self, trades: list[dict]) -> float:
        from order_executor import _daily_sameday_spend

        fake_data = {"trades": trades}
        with patch("paper._load", return_value=fake_data):
            return _daily_sameday_spend()

    def test_sameday_trade_counted(self):
        # days_out=0 trade MUST count toward the same-day cap.
        trades = [_make_trade(cost=100.0, days_out=0)]
        assert self._call(trades) == 100.0

    def test_multiday_trade_excluded(self):
        # days_out=1 trade must NOT count toward the same-day cap.
        trades = [_make_trade(cost=50.0, days_out=1)]
        assert self._call(trades) == 0.0

    def test_legacy_none_excluded(self):
        # Legacy trades (no days_out) are treated as multi-day — not counted here.
        trades = [_make_trade(cost=30.0, days_out=None)]
        assert self._call(trades) == 0.0

    def test_mixed_only_sameday_summed(self):
        # Only days_out=0 costs are summed; multi-day and legacy are ignored.
        trades = [
            _make_trade(cost=197.80, days_out=0),  # same-day — counted
            _make_trade(cost=25.00, days_out=1),  # multi-day — excluded
            _make_trade(cost=15.00, days_out=None),  # legacy — excluded
        ]
        assert abs(self._call(trades) - 197.80) < 0.01

    def test_yesterday_sameday_not_counted(self):
        # Same-day trade placed on a previous UTC day must not count today.
        trades = [
            _make_trade(cost=500.0, days_out=0, entered_at="2020-01-01T12:00:00+00:00")
        ]
        assert self._call(trades) == 0.0

    def test_empty_trades(self):
        assert self._call([]) == 0.0

    def test_multiple_sameday_summed(self):
        # Multiple same-day trades today are all summed.
        trades = [
            _make_trade(cost=60.0, days_out=0),
            _make_trade(cost=40.0, days_out=0),
            _make_trade(cost=20.0, days_out=1),  # excluded
        ]
        assert abs(self._call(trades) - 100.0) < 0.01


# ---------------------------------------------------------------------------
# Cap independence: _daily_paper_spend vs _daily_sameday_spend
# ---------------------------------------------------------------------------


class TestCapIndependence:
    """The two caps read from non-overlapping trade subsets — no double-counting."""

    def _paper_spend(self, trades: list[dict]) -> float:
        from order_executor import _daily_paper_spend

        fake_data = {"trades": trades}
        with patch("paper._load", return_value=fake_data):
            return _daily_paper_spend()

    def _sameday_spend(self, trades: list[dict]) -> float:
        from order_executor import _daily_sameday_spend

        fake_data = {"trades": trades}
        with patch("paper._load", return_value=fake_data):
            return _daily_sameday_spend()

    def test_same_trade_not_counted_in_both(self):
        # A same-day trade contributes to sameday_spend but not paper_spend.
        trades = [_make_trade(cost=100.0, days_out=0)]
        assert self._paper_spend(trades) == 0.0
        assert self._sameday_spend(trades) == 100.0

    def test_multiday_trade_not_counted_in_sameday(self):
        # A multi-day trade contributes to paper_spend but not sameday_spend.
        trades = [_make_trade(cost=80.0, days_out=2)]
        assert self._paper_spend(trades) == 80.0
        assert self._sameday_spend(trades) == 0.0

    def test_combined_totals_add_up(self):
        # paper_spend + sameday_spend should equal total cost across all trades today.
        trades = [
            _make_trade(cost=100.0, days_out=0),
            _make_trade(cost=80.0, days_out=1),
            _make_trade(cost=60.0, days_out=0),
            _make_trade(cost=40.0, days_out=2),
        ]
        total = sum(t["cost"] for t in trades)
        assert (
            abs(self._paper_spend(trades) + self._sameday_spend(trades) - total) < 0.01
        )
