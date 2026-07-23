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
        result = paper.check_breakeven_stops([t], {"T1": {"bid": 0.30, "ask": 0.30}})
        assert result == []

    def test_peak_below_trigger_no_exit(self):
        import paper

        t = self._open_trade("T1", "no", 0.45, 20, peak=0.20)  # only 20%, need 30%
        result = paper.check_breakeven_stops(
            [t], {"T1": {"bid": 0.50, "ask": 0.50}}
        )  # back to breakeven
        assert result == []

    def test_peak_hit_price_at_entry_triggers(self):
        import paper

        t = self._open_trade(
            "T1", "no", 0.45, 20, peak=0.80
        )  # was up 80% — above 0.75 threshold
        # yes=0.55 → our_price=0.45 → exactly at entry → pnl=0
        result = paper.check_breakeven_stops([t], {"T1": {"bid": 0.55, "ask": 0.55}})
        assert "T1" in result

    def test_peak_hit_price_below_entry_triggers(self):
        import paper

        t = self._open_trade(
            "T1", "no", 0.45, 20, peak=0.80
        )  # was up 80% — above 0.75 threshold
        # yes=0.60 → our_price=0.40 → below entry → pnl < 0
        result = paper.check_breakeven_stops([t], {"T1": {"bid": 0.60, "ask": 0.60}})
        assert "T1" in result

    def test_peak_hit_still_in_profit_no_exit(self):
        import paper

        t = self._open_trade("T1", "no", 0.45, 20, peak=0.50)
        # yes=0.40 → our_price=0.60 → still above entry → no exit
        result = paper.check_breakeven_stops([t], {"T1": {"bid": 0.40, "ask": 0.40}})
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
        changed = paper.update_peak_profits([t], {"T1": {"bid": 0.30, "ask": 0.30}})
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
        changed = paper.update_peak_profits([t], {"T1": {"bid": 0.50, "ask": 0.50}})
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

    def test_spread_eats_entire_edge_floors_at_zero(self):
        """#5: was floored at 0.5 — a trade with exactly zero effective edge
        after crossing the spread must size to 0, not half-Kelly."""
        import paper

        # spread=0.16 (16¢), net_edge=0.08 → spread_cost=0.08
        # effective_edge=0.0 → mult=0.0
        result = paper.spread_kelly_multiplier(0.42, 0.58, 0.08)
        assert result == 0.0

    def test_spread_larger_than_edge_floors_at_zero(self):
        """#5: negative effective_edge (spread eats MORE than the full edge —
        genuinely negative-EV after crossing it) must floor at 0, not 0.5 —
        the old floor still half-Kelly-sized a trade that shouldn't be placed."""
        import paper

        # spread=0.20, net_edge=0.05 → negative effective_edge → floor 0.0
        result = paper.spread_kelly_multiplier(0.40, 0.60, 0.05)
        assert result == 0.0

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


# ---------------------------------------------------------------------------
# backlog.txt "HOURLY-DIRECTIONAL TEMPERATURE MARKETS" Step 2 handoff item 2:
# var-derivation root-cause fix -- _score_ensemble_members must prefer the
# var stored on the trade record over re-deriving it from ticker substrings,
# which never match KXTEMPxxxH tickers and silently defaulted to "max".
# ---------------------------------------------------------------------------


def test_score_ensemble_members_prefers_stored_var(tmp_path, monkeypatch):
    """A trade with var="min" stored on it must log under var="min", even
    though its ticker contains neither "LOW" nor "LOWT" (an hourly-shaped
    ticker, where the old substring derivation would have silently defaulted
    to "max")."""
    import paper
    import tracker

    monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "test.db")
    tracker._db_initialized = False
    tracker.init_db()

    ticker = "KXTEMPNYCH-26JUL2006-T60.99"
    with tracker._conn() as con:
        con.execute(
            "INSERT OR IGNORE INTO outcomes (ticker, settled_yes) VALUES (?,1)",
            (ticker,),
        )
        con.execute("UPDATE outcomes SET settled_temp_f=61.0 WHERE ticker=?", (ticker,))

    trade = {
        "ticker": ticker,
        "city": "NYC",
        "target_date": "2026-07-20",
        "icon_forecast_mean": 60.0,
        "gfs_forecast_mean": 59.5,
        "forecast_temp": 60.2,
        "var": "min",
    }
    paper._score_ensemble_members(trade, outcome_yes=True)

    with tracker._conn() as con:
        rows = con.execute(
            "SELECT var FROM ensemble_member_scores WHERE city='NYC'"
        ).fetchall()
    assert rows, "_score_ensemble_members must insert at least one row"
    assert all(r[0] == "min" for r in rows), (
        f"Expected var='min' (from trade['var']), got: {[r[0] for r in rows]}"
    )


def test_score_ensemble_members_falls_back_for_legacy_trade_without_var(
    tmp_path, monkeypatch
):
    """A trade placed before the var field existed (no 'var' key at all)
    must fall back to the old ticker-substring derivation, not crash."""
    import paper
    import tracker

    monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "test.db")
    tracker._db_initialized = False
    tracker.init_db()

    ticker = "KXHIGHNY-26JUL04-T85"
    with tracker._conn() as con:
        con.execute(
            "INSERT OR IGNORE INTO outcomes (ticker, settled_yes) VALUES (?,1)",
            (ticker,),
        )
        con.execute("UPDATE outcomes SET settled_temp_f=88.0 WHERE ticker=?", (ticker,))

    trade = {
        "ticker": ticker,
        "city": "NYC",
        "target_date": "2026-07-04",
        "icon_forecast_mean": 84.0,
        "gfs_forecast_mean": 83.5,
        "forecast_temp": 84.2,
        # no "var" key -- legacy trade
    }
    paper._score_ensemble_members(trade, outcome_yes=True)

    with tracker._conn() as con:
        rows = con.execute(
            "SELECT var FROM ensemble_member_scores WHERE city='NYC'"
        ).fetchall()
    assert rows
    assert all(r[0] == "max" for r in rows), (
        f"Expected var='max' (ticker-substring fallback for KXHIGH), got: {[r[0] for r in rows]}"
    )


def test_place_paper_order_stores_var_on_trade(tmp_path, monkeypatch):
    import paper

    monkeypatch.setattr(paper, "DATA_PATH", tmp_path / "paper_trades.json")

    trade = paper.place_paper_order(
        "KXTEMPNYCH-26JUL2006-T60.99",
        "yes",
        10,
        0.5,
        city="NYC",
        target_date="2026-07-20",
        var="min",
    )
    assert trade["var"] == "min"


# ---------------------------------------------------------------------------
# backlog.txt "TRACK ECMWF FORECAST ACCURACY": ecmwf_aifs_forecast_mean and
# ecmwf_ifs_forecast_mean must be stored on the trade record (mirroring
# icon/gfs) and logged by _score_ensemble_members under model=
# "ecmwf_aifs025_ensemble" / "ecmwf_ifs025" respectively (2 real, independent
# ECMWF products — fixing one does not give the other a learned weight).
# ---------------------------------------------------------------------------


def test_place_paper_order_stores_ecmwf_forecast_means(tmp_path, monkeypatch):
    import paper

    monkeypatch.setattr(paper, "DATA_PATH", tmp_path / "paper_trades.json")

    trade = paper.place_paper_order(
        "KXHIGHNY-26JUL04-T85",
        "yes",
        10,
        0.5,
        city="NYC",
        target_date="2026-07-04",
        icon_forecast_mean=84.0,
        gfs_forecast_mean=83.5,
        ecmwf_aifs_forecast_mean=85.2,
        ecmwf_ifs_forecast_mean=83.9,
    )
    assert abs(trade["ecmwf_aifs_forecast_mean"] - 85.2) < 0.001
    assert abs(trade["ecmwf_ifs_forecast_mean"] - 83.9) < 0.001


def test_score_ensemble_members_logs_ecmwf_aifs_row(tmp_path, monkeypatch):
    """A trade with ecmwf_aifs_forecast_mean set must produce a row in
    ensemble_member_scores under model='ecmwf_aifs025_ensemble'."""
    import paper
    import tracker

    monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "test.db")
    tracker._db_initialized = False
    tracker.init_db()

    ticker = "KXHIGHNY-26JUL04-T85"
    with tracker._conn() as con:
        con.execute(
            "INSERT OR IGNORE INTO outcomes (ticker, settled_yes) VALUES (?,1)",
            (ticker,),
        )
        con.execute("UPDATE outcomes SET settled_temp_f=88.0 WHERE ticker=?", (ticker,))

    trade = {
        "ticker": ticker,
        "city": "NYC",
        "target_date": "2026-07-04",
        "icon_forecast_mean": 84.0,
        "gfs_forecast_mean": 83.5,
        "ecmwf_aifs_forecast_mean": 85.2,
        "forecast_temp": 84.2,
    }
    paper._score_ensemble_members(trade, outcome_yes=True)

    with tracker._conn() as con:
        rows = con.execute(
            "SELECT predicted_temp, actual_temp FROM ensemble_member_scores "
            "WHERE city='NYC' AND model='ecmwf_aifs025_ensemble'"
        ).fetchall()
    assert rows, (
        "_score_ensemble_members must insert an 'ecmwf_aifs025_ensemble' row "
        "when trade['ecmwf_aifs_forecast_mean'] is set"
    )
    assert abs(rows[0][0] - 85.2) < 0.001
    assert abs(rows[0][1] - 88.0) < 0.001


def test_score_ensemble_members_logs_ecmwf_ifs_row(tmp_path, monkeypatch):
    """A trade with ecmwf_ifs_forecast_mean set must produce a row in
    ensemble_member_scores under model='ecmwf_ifs025' — independent of the
    aifs025_ensemble row above (2 distinct real ECMWF products)."""
    import paper
    import tracker

    monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "test.db")
    tracker._db_initialized = False
    tracker.init_db()

    ticker = "KXHIGHNY-26JUL04-T85"
    with tracker._conn() as con:
        con.execute(
            "INSERT OR IGNORE INTO outcomes (ticker, settled_yes) VALUES (?,1)",
            (ticker,),
        )
        con.execute("UPDATE outcomes SET settled_temp_f=88.0 WHERE ticker=?", (ticker,))

    trade = {
        "ticker": ticker,
        "city": "NYC",
        "target_date": "2026-07-04",
        "icon_forecast_mean": 84.0,
        "gfs_forecast_mean": 83.5,
        "ecmwf_ifs_forecast_mean": 83.9,
        "forecast_temp": 84.2,
    }
    paper._score_ensemble_members(trade, outcome_yes=True)

    with tracker._conn() as con:
        rows = con.execute(
            "SELECT predicted_temp, actual_temp FROM ensemble_member_scores "
            "WHERE city='NYC' AND model='ecmwf_ifs025'"
        ).fetchall()
    assert rows, (
        "_score_ensemble_members must insert an 'ecmwf_ifs025' row "
        "when trade['ecmwf_ifs_forecast_mean'] is set"
    )
    assert abs(rows[0][0] - 83.9) < 0.001
    assert abs(rows[0][1] - 88.0) < 0.001


def test_score_ensemble_members_skips_ecmwf_rows_when_means_absent(
    tmp_path, monkeypatch
):
    """A legacy trade with neither ecmwf_aifs_forecast_mean nor
    ecmwf_ifs_forecast_mean must NOT produce either ECMWF row — mirrors
    icon/gfs's existing None-skip behavior (model_means.items() only logs
    non-None predicted_temp)."""
    import paper
    import tracker

    monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "test.db")
    tracker._db_initialized = False
    tracker.init_db()

    ticker = "KXHIGHNY-26JUL04-T85"
    with tracker._conn() as con:
        con.execute(
            "INSERT OR IGNORE INTO outcomes (ticker, settled_yes) VALUES (?,1)",
            (ticker,),
        )
        con.execute("UPDATE outcomes SET settled_temp_f=88.0 WHERE ticker=?", (ticker,))

    trade = {
        "ticker": ticker,
        "city": "NYC",
        "target_date": "2026-07-04",
        "icon_forecast_mean": 84.0,
        "gfs_forecast_mean": 83.5,
        "forecast_temp": 84.2,
        # no ecmwf_aifs_forecast_mean/ecmwf_ifs_forecast_mean keys -- legacy trade
    }
    paper._score_ensemble_members(trade, outcome_yes=True)

    with tracker._conn() as con:
        rows = con.execute(
            "SELECT predicted_temp, model FROM ensemble_member_scores "
            "WHERE city='NYC' AND model IN ('ecmwf_aifs025_ensemble', 'ecmwf_ifs025')"
        ).fetchall()
    assert not rows, f"expected no ECMWF rows for a legacy trade, got: {rows}"
    # icon/gfs rows must still be logged normally.
    with tracker._conn() as con:
        icon_rows = con.execute(
            "SELECT predicted_temp FROM ensemble_member_scores "
            "WHERE city='NYC' AND model='icon_seamless'"
        ).fetchall()
    assert icon_rows and abs(icon_rows[0][0] - 84.0) < 0.001
