"""Tests for P1-14 — alerts win/loss side confusion fix."""

from __future__ import annotations

from datetime import UTC, datetime


def _make_trade(outcome: str, side: str = "yes", placed_at: int = 0) -> dict:
    won = (side == "yes" and outcome == "yes") or (side == "no" and outcome == "no")
    return {
        "outcome": outcome,
        "side": side,
        "placed_at": placed_at,
        "edge": 0.10,
        "settled": True,
        # settled_at increases with placed_at so sort-by-settlement-time
        # preserves the same relative order these tests assume.
        "settled_at": f"2026-01-01T00:{placed_at:02d}:00Z",
        "pnl": 10.0 if won else -10.0,
    }


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


class TestGroupCFixes:
    """Regression tests for the lower-severity Fable findings fixed alongside
    the Group A/B work: days_out=None crash, Brier fail-closed, worktree-safe
    paths, daily-loss condition not gated on the (functionally unused) balance
    param, and the _is_halt_level unrecognized-type warning."""

    def test_days_out_none_does_not_crash(self, monkeypatch):
        """A trade record with days_out=None (key present, not absent) must
        not TypeError in the `.get("days_out", 1) >= 1` multi-day filter."""
        import tracker
        from alerts import check_black_swan_conditions

        monkeypatch.setattr(tracker, "brier_score", lambda city=None: None)
        monkeypatch.setattr(tracker, "get_history", lambda: [])

        trades = [_make_trade("no", side="no", placed_at=0)]
        trades[0]["days_out"] = None
        # Must not raise.
        result = check_black_swan_conditions(trades, balance=1000, peak_balance=1000)
        assert isinstance(result, list)

    def test_brier_check_failure_fails_closed(self, monkeypatch):
        """A Brier-check exception (e.g. a locked tracker.db) must be treated
        as triggered, not silently skipped — same fail-closed precedent as
        paper.is_accuracy_halted()."""
        import tracker
        from alerts import check_black_swan_conditions

        def _broken_brier(*a, **kw):
            raise RuntimeError("database is locked")

        monkeypatch.setattr(tracker, "count_settled_predictions", _broken_brier)

        trades = [_make_trade("no", side="no", placed_at=0)]
        result = check_black_swan_conditions(trades, balance=1000, peak_balance=1000)
        assert any("brier" in c.lower() for c in result), (
            f"a Brier check failure must fail closed (appear as triggered): {result}"
        )

    def test_brier_check_still_runs_when_trades_is_empty(self, monkeypatch):
        """Deep-review followup: an early `if not trades: return triggered`
        used to skip condition 3 (Brier collapse) entirely whenever trades
        was empty (e.g. a fresh or corrupt-recovered paper_trades.json) --
        even though the Brier check reads tracker.db directly and doesn't
        need trades at all. A real Brier-check failure with no paper trades
        on record must still fail closed, not be silently bypassed."""
        import tracker
        from alerts import check_black_swan_conditions

        def _broken_brier(*a, **kw):
            raise RuntimeError("database is locked")

        monkeypatch.setattr(tracker, "count_settled_predictions", _broken_brier)

        result = check_black_swan_conditions([], balance=1000, peak_balance=1000)
        assert any("brier" in c.lower() for c in result), (
            f"Brier check must still run and fail closed with trades=[]: {result}"
        )

    def test_daily_loss_condition_works_without_balance_param(self, monkeypatch):
        """balance isn't actually used in the daily-loss math (only
        peak_balance is) — the condition must still evaluate with
        balance=None as long as peak_balance is available."""
        import tracker
        from alerts import check_black_swan_conditions

        monkeypatch.setattr(tracker, "brier_score", lambda city=None: None)
        monkeypatch.setattr(tracker, "count_settled_predictions", lambda: 0)

        trades = [
            {
                "outcome": "no",
                "settled": True,
                "settled_at": datetime.now(UTC).strftime("%Y-%m-%dT00:00:00Z"),
                "pnl": -500.0,
            }
        ]
        result = check_black_swan_conditions(trades, balance=None, peak_balance=1000)
        assert any("daily loss" in c.lower() for c in result), (
            f"daily-loss condition must not require `balance` to be set: {result}"
        )

    def test_none_settled_at_does_not_crash_daily_loss_condition(self, monkeypatch):
        """Deep-review followup: t.get("settled_at", "") only covers a
        MISSING key -- a settled record with settled_at explicitly None
        (a real, documented state) returns None, and None[:10] raised
        TypeError, escaping to run_black_swan_check's catch-all and
        engaging the kill switch on every cycle until hand-fixed."""
        import tracker
        from alerts import check_black_swan_conditions

        monkeypatch.setattr(tracker, "brier_score", lambda city=None: None)
        monkeypatch.setattr(tracker, "count_settled_predictions", lambda: 0)

        trades = [
            {
                "outcome": "no",
                "settled": True,
                "settled_at": None,
                "pnl": -500.0,
            }
        ]
        # Must not raise.
        result = check_black_swan_conditions(trades, balance=1000, peak_balance=1000)
        assert isinstance(result, list)

    def test_breakeven_trades_excluded_from_win_rate_denominator(self):
        """Deep-review followup: breakeven (pnl == 0) trades were counted in
        the win-rate denominator but never the numerator, scoring every
        breakeven exit as a full loss for this metric -- inconsistent with
        _trade_lost() (used by the consecutive-losses check), which
        deliberately treats breakeven as neither win nor loss. 2 wins + 2
        losses + 6 breakevens is an even decided record (50%), but the old
        denominator (10) computed 20% and wrongly fired WIN RATE COLLAPSE."""
        from alerts import check_anomalies

        def _decided(pnl: float, i: int) -> dict:
            return {
                "outcome": "yes" if pnl > 0 else "no",
                "side": "yes",
                "placed_at": i,
                "settled": True,
                "settled_at": f"2026-01-01T00:{i:02d}:00Z",
                "pnl": pnl,
            }

        trades = (
            [_decided(10.0, i) for i in range(2)]  # 2 wins
            + [_decided(0.0, 2 + i) for i in range(6)]  # 6 breakeven early-exits
            + [_decided(-10.0, 8 + i) for i in range(2)]  # 2 losses
        )
        result = check_anomalies(trades)
        assert not any("win rate" in c.lower() for c in result), (
            f"a 2W/2L decided record must not fire WIN RATE COLLAPSE just "
            f"because 6 breakeven trades diluted the old denominator: {result}"
        )

    def test_kill_switch_path_matches_canonical_paths_module(self):
        """alerts.py's kill-switch/black-swan paths must be the same
        worktree-safe paths every other reader/writer in the repo uses."""
        import alerts
        import paths

        assert alerts._KILL_SWITCH_PATH == paths.KILL_SWITCH_PATH
        assert alerts._BLACK_SWAN_PATH == paths.BLACK_SWAN_PATH

    def test_unrecognized_anomaly_message_logs_a_warning(self, caplog):
        import logging

        from alerts import _is_halt_level

        with caplog.at_level(logging.WARNING):
            result = _is_halt_level("SOME NEW ANOMALY TYPE: 42")

        assert result is False  # still defaults to no-halt...
        assert any("unrecognized" in r.message.lower() for r in caplog.records), (
            "...but must not do so silently"
        )
