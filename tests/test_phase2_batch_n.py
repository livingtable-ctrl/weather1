"""test_phase2_batch_n.py — Tests for order_executor daily spend cap separation.

Covers the fix that excludes same-day trades (days_out=0) from _daily_paper_spend()
so MAX_DAILY_SPEND only gates multi-day signals and same-day costs don't block
multi-day trading later in the same calendar day.
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


class TestDailyPaperSpend:
    """_daily_paper_spend() must only sum multi-day trade costs."""

    def _call(self, trades: list[dict]) -> float:
        from order_executor import _daily_paper_spend

        fake_data = {"trades": trades}
        # _daily_paper_spend does `from paper import _load` internally,
        # so we patch at the paper module level.
        with patch("paper._load", return_value=fake_data):
            return _daily_paper_spend()

    def test_same_day_trades_excluded(self):
        # Same-day trade (days_out=0) must NOT count toward the cap.
        trades = [_make_trade(cost=100.0, days_out=0)]
        assert self._call(trades) == 0.0

    def test_multiday_trades_included(self):
        # Multi-day trade (days_out=1) MUST count toward the cap.
        trades = [_make_trade(cost=50.0, days_out=1)]
        assert self._call(trades) == 50.0

    def test_legacy_none_days_out_included(self):
        # Legacy trades with no days_out field are treated as multi-day (included).
        trades = [_make_trade(cost=30.0, days_out=None)]
        assert self._call(trades) == 30.0

    def test_mixed_same_day_and_multiday(self):
        # Only multi-day costs are summed; same-day costs are ignored.
        trades = [
            _make_trade(cost=197.80, days_out=0),  # same-day — excluded
            _make_trade(cost=25.00, days_out=1),  # multi-day — included
            _make_trade(cost=15.00, days_out=2),  # multi-day — included
        ]
        assert abs(self._call(trades) - 40.0) < 0.01

    def test_yesterday_trades_not_counted(self):
        # Trades placed on a previous UTC day must not count toward today's cap.
        trades = [
            _make_trade(cost=500.0, days_out=1, entered_at="2020-01-01T12:00:00+00:00")
        ]
        assert self._call(trades) == 0.0

    def test_empty_trades(self):
        assert self._call([]) == 0.0

    def test_multiple_multiday_summed(self):
        trades = [
            _make_trade(cost=60.0, days_out=1),
            _make_trade(cost=40.0, days_out=3),
            _make_trade(cost=20.0, days_out=0),  # excluded
        ]
        assert abs(self._call(trades) - 100.0) < 0.01
