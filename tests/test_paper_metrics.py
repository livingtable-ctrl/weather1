"""Tests for profit factor, break-even stop, and spread Kelly multiplier."""

from __future__ import annotations

import json

# ---------------------------------------------------------------------------
# Feature 1: Profit Factor
# ---------------------------------------------------------------------------


class TestProfitFactor:
    def _make_trades(self, tmp_path, settled):
        """Write a minimal paper_trades.json with given settled trade pnls."""
        trades = []
        for i, pnl in enumerate(settled):
            trades.append(
                {
                    "id": i + 1,
                    "ticker": f"TEST-{i}",
                    "side": "yes",
                    "quantity": 10,
                    "entry_price": 0.50,
                    "cost": 5.0,
                    "settled": True,
                    "outcome": "yes",
                    "pnl": pnl,
                }
            )
        data = {"balance": 1000.0, "peak_balance": 1000.0, "trades": trades}
        p = tmp_path / "paper_trades.json"
        p.write_text(json.dumps(data))
        return p

    def test_no_losses_returns_none(self, tmp_path, monkeypatch):
        p = self._make_trades(tmp_path, [5.0, 3.0])
        import paper

        monkeypatch.setattr(paper, "DATA_PATH", p)
        result = paper.get_profit_factor()
        assert result["profit_factor"] is None
        assert result["n_wins"] == 2
        assert result["n_losses"] == 0

    def test_no_settled_returns_none(self, tmp_path, monkeypatch):
        data = {"balance": 1000.0, "peak_balance": 1000.0, "trades": []}
        p = tmp_path / "paper_trades.json"
        p.write_text(json.dumps(data))
        import paper

        monkeypatch.setattr(paper, "DATA_PATH", p)
        result = paper.get_profit_factor()
        assert result["profit_factor"] is None
        assert result["n"] == 0

    def test_basic_ratio(self, tmp_path, monkeypatch):
        # gross_profit=10, gross_loss=5 → profit_factor=2.0
        p = self._make_trades(tmp_path, [6.0, 4.0, -3.0, -2.0])
        import paper

        monkeypatch.setattr(paper, "DATA_PATH", p)
        result = paper.get_profit_factor()
        assert result["profit_factor"] == 2.0
        assert result["gross_profit"] == 10.0
        assert result["gross_loss"] == 5.0
        assert result["avg_win"] == 5.0
        assert result["avg_loss"] == 2.5
        assert result["win_loss_ratio"] == 2.0
        assert result["n_wins"] == 2
        assert result["n_losses"] == 2

    def test_get_performance_includes_profit_factor(self, tmp_path, monkeypatch):
        p = self._make_trades(tmp_path, [6.0, -3.0])
        import paper

        monkeypatch.setattr(paper, "DATA_PATH", p)
        perf = paper.get_performance()
        assert "profit_factor" in perf
        assert perf["profit_factor"] == 2.0


# ---------------------------------------------------------------------------
# Feature 2: Break-Even Stop
# ---------------------------------------------------------------------------


class TestBreakEvenStop:
    def _open_trade(self, ticker, side, entry_price, qty, peak=None):
        cost = round(entry_price * qty, 4)
        return {
            "id": 1,
            "ticker": ticker,
            "side": side,
            "quantity": qty,
            "entry_price": entry_price,
            "cost": cost,
            "settled": False,
            "outcome": None,
            "pnl": None,
            "peak_profit_pct": peak,
            # 24h gate requires close_time; set far in the future so the gate
            # never fires during tests (we're testing the breakeven trigger, not the gate)
            "close_time": "2099-01-01T00:00:00Z",
        }

    def test_no_peak_no_exit(self):
        import paper

        t = self._open_trade("T1", "no", 0.45, 20, peak=None)
        # yes price = 0.30 → our_price = 0.70 → profit
        result = paper.check_breakeven_stops([t], {"T1": 0.30})
        assert result == []

    def test_peak_below_trigger_no_exit(self):
        import paper

        t = self._open_trade("T1", "no", 0.45, 20, peak=0.20)  # only 20%, need 30%
        result = paper.check_breakeven_stops([t], {"T1": 0.50})  # back to breakeven
        assert result == []

    def test_peak_hit_price_at_entry_triggers(self):
        import paper

        t = self._open_trade(
            "T1", "no", 0.45, 20, peak=0.80
        )  # was up 80% — above 0.75 threshold
        # yes=0.55 → our_price=0.45 → exactly at entry → pnl=0
        result = paper.check_breakeven_stops([t], {"T1": 0.55})
        assert "T1" in result

    def test_peak_hit_price_below_entry_triggers(self):
        import paper

        t = self._open_trade(
            "T1", "no", 0.45, 20, peak=0.80
        )  # was up 80% — above 0.75 threshold
        # yes=0.60 → our_price=0.40 → below entry → pnl < 0
        result = paper.check_breakeven_stops([t], {"T1": 0.60})
        assert "T1" in result

    def test_peak_hit_still_in_profit_no_exit(self):
        import paper

        t = self._open_trade("T1", "no", 0.45, 20, peak=0.50)
        # yes=0.40 → our_price=0.60 → still above entry → no exit
        result = paper.check_breakeven_stops([t], {"T1": 0.40})
        assert result == []

    def test_update_peak_profits_sets_new_high(self, tmp_path, monkeypatch):
        import paper

        t = self._open_trade("T1", "no", 0.45, 20, peak=None)
        data = {"balance": 900.0, "peak_balance": 1000.0, "trades": [t]}
        p = tmp_path / "paper_trades.json"
        p.write_text(json.dumps(data))
        monkeypatch.setattr(paper, "DATA_PATH", p)

        # yes=0.30 → our_price=0.70 → profit=(0.70-0.45)*20=5.0
        # profit_pct = 5.0 / cost(9.0) ≈ 0.556
        changed = paper.update_peak_profits([t], {"T1": 0.30})
        assert changed is True
        saved = json.loads(p.read_text())
        assert saved["trades"][0]["peak_profit_pct"] > 0.50

    def test_update_peak_profits_no_change_when_lower(self, tmp_path, monkeypatch):
        import paper

        t = self._open_trade("T1", "no", 0.45, 20, peak=0.80)
        data = {"balance": 900.0, "peak_balance": 1000.0, "trades": [t]}
        p = tmp_path / "paper_trades.json"
        p.write_text(json.dumps(data))
        monkeypatch.setattr(paper, "DATA_PATH", p)

        # price moved against us — profit pct is now lower
        changed = paper.update_peak_profits([t], {"T1": 0.50})
        assert changed is False


# ---------------------------------------------------------------------------
# Feature 3: Spread Kelly Multiplier
# ---------------------------------------------------------------------------


class TestSpreadKellyMultiplier:
    def test_no_spread_returns_one(self):
        import paper

        assert paper.spread_kelly_multiplier(0.50, 0.50, 0.15) == 1.0

    def test_zero_net_edge_returns_one(self):
        import paper

        assert paper.spread_kelly_multiplier(0.47, 0.53, 0.0) == 1.0

    def test_negative_net_edge_returns_one(self):
        import paper

        assert paper.spread_kelly_multiplier(0.47, 0.53, -0.05) == 1.0

    def test_small_spread_minimal_reduction(self):
        import paper

        # spread=0.02 (2¢), net_edge=0.20 → spread_cost=0.01
        # effective_edge=0.19 → mult=0.19/0.20=0.95
        result = paper.spread_kelly_multiplier(0.49, 0.51, 0.20)
        assert abs(result - 0.95) < 0.001

    def test_medium_spread_moderate_reduction(self):
        import paper

        # spread=0.06 (6¢), net_edge=0.15 → spread_cost=0.03
        # effective_edge=0.12 → mult=0.12/0.15=0.8
        result = paper.spread_kelly_multiplier(0.47, 0.53, 0.15)
        assert abs(result - 0.8) < 0.001

    def test_spread_eats_half_edge_floors_at_half(self):
        import paper

        # spread=0.16 (16¢), net_edge=0.08 → spread_cost=0.08
        # effective_edge=0.0 → mult would be 0 but floors at 0.5
        result = paper.spread_kelly_multiplier(0.42, 0.58, 0.08)
        assert result == 0.5

    def test_spread_larger_than_edge_still_floors_at_half(self):
        import paper

        # spread=0.20, net_edge=0.05 → negative effective_edge → floor 0.5
        result = paper.spread_kelly_multiplier(0.40, 0.60, 0.05)
        assert result == 0.5

    def test_plan_example_six_cent_spread_fifteen_edge(self):
        import paper

        # From plan: spread=6¢ eats 20% of 15¢ edge → mult=0.8
        result = paper.spread_kelly_multiplier(0.47, 0.53, 0.15)
        assert result == 0.8

    def test_plan_example_six_cent_spread_eight_edge(self):
        import paper

        # From plan: spread=6¢ eats 37.5% of 8¢ edge → mult=0.625
        result = paper.spread_kelly_multiplier(0.47, 0.53, 0.08)
        assert result == 0.625


# ---------------------------------------------------------------------------
# Feature 4: _score_ensemble_members uses DB settled_temp_f (E12)
# ---------------------------------------------------------------------------


def test_score_ensemble_members_uses_db_settled_temp(tmp_path, monkeypatch):
    import paper
    import tracker

    monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "test.db")
    tracker._db_initialized = False
    tracker.init_db()

    # Pre-populate settled_temp_f in outcomes (as audit_settlement would do)
    with tracker._conn() as con:
        con.execute(
            "INSERT OR IGNORE INTO outcomes (ticker, settled_yes) VALUES (?,1)",
            ("KXHIGHNY-26JUL04-T85",),
        )
        con.execute(
            "UPDATE outcomes SET settled_temp_f=88.0 WHERE ticker=?",
            ("KXHIGHNY-26JUL04-T85",),
        )

    trade = {
        "ticker": "KXHIGHNY-26JUL04-T85",
        "city": "NYC",
        "target_date": "2026-07-04",
        "icon_forecast_mean": 84.0,
        "gfs_forecast_mean": 83.5,
        "forecast_temp": 84.2,
    }

    paper._score_ensemble_members(trade, outcome_yes=True)

    with tracker._conn() as con:
        rows = con.execute(
            "SELECT actual_temp FROM ensemble_member_scores WHERE city='NYC'"
        ).fetchall()

    assert rows, (
        "_score_ensemble_members must insert at least one row into ensemble_member_scores"
    )
    actual_temps = [r[0] for r in rows]
    assert all(abs(t - 88.0) < 0.1 for t in actual_temps), (
        f"Expected actual_temp=88.0 (DB settled_temp_f), got: {actual_temps}"
    )
