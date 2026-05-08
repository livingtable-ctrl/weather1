"""Tests for P1-14 — alerts win/loss side confusion fix."""

from __future__ import annotations


def _make_trade(outcome: str, side: str = "yes", placed_at: int = 0) -> dict:
    return {"outcome": outcome, "side": side, "placed_at": placed_at, "edge": 0.10}


class TestTradeWon:
    def test_yes_side_yes_outcome_is_win(self):
        from alerts import _trade_won

        assert _trade_won({"side": "yes", "outcome": "yes"}) is True

    def test_yes_side_no_outcome_is_loss(self):
        from alerts import _trade_won

        assert _trade_won({"side": "yes", "outcome": "no"}) is False

    def test_no_side_no_outcome_is_win(self):
        from alerts import _trade_won

        assert _trade_won({"side": "no", "outcome": "no"}) is True

    def test_no_side_yes_outcome_is_loss(self):
        from alerts import _trade_won

        assert _trade_won({"side": "no", "outcome": "yes"}) is False

    def test_missing_side_defaults_to_yes(self):
        from alerts import _trade_won

        assert _trade_won({"outcome": "yes"}) is True
        assert _trade_won({"outcome": "no"}) is False


class TestCheckAnomaliesNoSideWinRate:
    def test_no_side_wins_not_counted_as_losses(self):
        """P1-14: 8 winning NO-side trades must not trigger win-rate collapse."""
        from alerts import check_anomalies

        # 8 NO-side trades that all won (outcome="no" = correct NO prediction)
        trades = [_make_trade("no", side="no", placed_at=i) for i in range(8)]
        alerts = check_anomalies(trades)
        assert not any("WIN RATE" in a for a in alerts), (
            f"Winning NO trades must not trigger win-rate collapse: {alerts}"
        )

    def test_no_side_losses_trigger_collapse(self):
        """P1-14: 8 losing NO-side trades (outcome='yes') must trigger collapse."""
        from alerts import check_anomalies

        # 8 NO-side trades that all lost (outcome="yes" = NO bet lost)
        trades = [_make_trade("yes", side="no", placed_at=i) for i in range(8)]
        alerts = check_anomalies(trades)
        assert any("WIN RATE" in a for a in alerts), (
            f"Losing NO trades must trigger win-rate collapse: {alerts}"
        )

    def test_mixed_sides_correct_win_count(self):
        """P1-14: 5 yes-wins + 5 no-wins = 100% win rate, no alert."""
        from alerts import check_anomalies

        trades = [_make_trade("yes", side="yes", placed_at=i) for i in range(5)]
        trades += [_make_trade("no", side="no", placed_at=5 + i) for i in range(5)]
        alerts = check_anomalies(trades)
        assert not any("WIN RATE" in a for a in alerts)


class TestCheckAnomaliesNoSideConsecutiveLoss:
    def test_no_side_wins_not_counted_as_consec_losses(self):
        """P1-14: 6 consecutive NO-side wins must not trigger consecutive-loss alert."""
        from alerts import check_anomalies

        # Most recent 6 trades are NO-side wins (outcome="no")
        trades = [_make_trade("no", side="no", placed_at=i) for i in range(6)]
        alerts = check_anomalies(trades)
        assert not any("CONSECUTIVE" in a for a in alerts), (
            f"NO-side wins must not be counted as consecutive losses: {alerts}"
        )

    def test_no_side_consecutive_losses_trigger(self):
        """P1-14: 6 consecutive NO-side losses (outcome='yes') must trigger alert."""
        from alerts import check_anomalies

        trades = [_make_trade("yes", side="no", placed_at=i) for i in range(6)]
        alerts = check_anomalies(trades)
        assert any("CONSECUTIVE" in a for a in alerts)


class TestCheckBlackSwanNoSide:
    def test_no_side_consecutive_wins_not_black_swan(self, monkeypatch):
        """P1-14: 12 consecutive NO-side wins must not trigger black swan."""
        import tracker

        monkeypatch.setattr(tracker, "brier_score", lambda city=None: None)
        monkeypatch.setattr(tracker, "get_history", lambda: [])

        from alerts import check_black_swan_conditions

        trades = [_make_trade("no", side="no", placed_at=i) for i in range(12)]
        result = check_black_swan_conditions(trades, balance=1000, peak_balance=1000)
        assert not any("consecutive" in c.lower() for c in result), (
            f"Winning NO trades must not trigger black swan: {result}"
        )

    def test_no_side_consecutive_losses_trigger_black_swan(self, monkeypatch):
        """P1-14: 12 consecutive NO-side losses (outcome='yes') trigger black swan."""
        import tracker

        monkeypatch.setattr(tracker, "brier_score", lambda city=None: None)
        monkeypatch.setattr(tracker, "get_history", lambda: [])

        from alerts import check_black_swan_conditions

        trades = [_make_trade("yes", side="no", placed_at=i) for i in range(12)]
        result = check_black_swan_conditions(trades, balance=900, peak_balance=1000)
        assert any("consecutive" in c.lower() for c in result)
