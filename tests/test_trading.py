"""
Tests for Phase 5 trading improvements:
  #49  dynamic correlation matrix
  #50  slippage_adjusted_price
  #63  time_decay_edge
  #65  price improvement tracking
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


# ── Task 2: dynamic correlation matrix (#49) ──────────────────────────────────


class TestDynamicCorrelationMatrix:
    def test_uses_dynamic_when_available(self, tmp_path):
        """When learned_correlations.json exists, get_city_correlation uses it."""
        import json

        import monte_carlo

        corr_file = tmp_path / "learned_correlations.json"
        corr_file.write_text(json.dumps({"NYC|Boston": 0.92}))

        # Reset the module-level cache so our mock takes effect
        monte_carlo._dynamic_corr_loaded = False
        monte_carlo._dynamic_corr_cache = None

        with patch.object(
            monte_carlo,
            "_load_dynamic_correlations",
            return_value={frozenset({"NYC", "Boston"}): 0.92},
        ):
            monte_carlo._dynamic_corr_loaded = False
            result = monte_carlo.get_city_correlation("NYC", "Boston")

        assert result == pytest.approx(0.92)

        # Restore for other tests
        monte_carlo._dynamic_corr_loaded = False
        monte_carlo._dynamic_corr_cache = None

    def test_falls_back_to_hardcoded_when_none(self):
        """When _load_dynamic_correlations returns None, use _HARDCODED_CORR."""
        import monte_carlo

        monte_carlo._dynamic_corr_loaded = False
        monte_carlo._dynamic_corr_cache = None

        with patch.object(monte_carlo, "_load_dynamic_correlations", return_value=None):
            monte_carlo._dynamic_corr_loaded = False
            result = monte_carlo.get_city_correlation("NYC", "Boston")

        # Hardcoded value is 0.85
        assert result == pytest.approx(0.85)

        monte_carlo._dynamic_corr_loaded = False
        monte_carlo._dynamic_corr_cache = None

    def test_unknown_pair_returns_zero(self):
        """Unknown city pairs should return 0.0."""
        import monte_carlo

        monte_carlo._dynamic_corr_loaded = False
        monte_carlo._dynamic_corr_cache = None

        with patch.object(monte_carlo, "_load_dynamic_correlations", return_value=None):
            monte_carlo._dynamic_corr_loaded = False
            result = monte_carlo.get_city_correlation("NYC", "Honolulu")

        assert result == 0.0

        monte_carlo._dynamic_corr_loaded = False
        monte_carlo._dynamic_corr_cache = None


class TestCorrelationTablesStayInSync:
    """monte_carlo._DEFAULT_CORRELATIONS and _HARDCODED_CORR are hand-typed
    seeds that must agree with paper._CITY_PAIR_CORR (the table
    position_correlation_matrix() treats as authoritative) for any pair they
    share. These two dicts silently disagreed with paper.py for an unknown
    period (found via a deep code review, 2026-07-08) with nothing to catch
    it -- this test closes that gap so a future edit to one without the
    others can't ship unnoticed."""

    def test_default_correlations_seed_matches_city_pair_corr(self):
        import monte_carlo
        import paper

        for (city_a, city_b), seed_value in monte_carlo._DEFAULT_CORRELATIONS.items():
            pair = frozenset({city_a, city_b})
            assert pair in paper._CITY_PAIR_CORR, (
                f"monte_carlo._DEFAULT_CORRELATIONS has {city_a}/{city_b} "
                f"but paper._CITY_PAIR_CORR doesn't"
            )
            assert seed_value == pytest.approx(paper._CITY_PAIR_CORR[pair]), (
                f"monte_carlo._DEFAULT_CORRELATIONS[{city_a},{city_b}]={seed_value} "
                f"disagrees with paper._CITY_PAIR_CORR={paper._CITY_PAIR_CORR[pair]}"
            )

    def test_hardcoded_corr_matches_city_pair_corr_for_shared_pairs(self):
        import monte_carlo
        import paper

        for pair, value in monte_carlo._HARDCODED_CORR.items():
            if pair not in paper._CITY_PAIR_CORR:
                continue  # _HARDCODED_CORR covers some pairs paper.py doesn't
            assert value == pytest.approx(paper._CITY_PAIR_CORR[pair]), (
                f"monte_carlo._HARDCODED_CORR[{sorted(pair)}]={value} "
                f"disagrees with paper._CITY_PAIR_CORR={paper._CITY_PAIR_CORR[pair]}"
            )


# ── Task 4: time_decay_edge (#63) ─────────────────────────────────────────────


class TestTimeDecayEdge:
    def test_full_edge_far_from_close(self):
        """Well before close (>= reference_hours), edge should be unchanged."""
        from weather_markets import time_decay_edge

        raw_edge = 0.10
        close_time = datetime.now(UTC) + timedelta(hours=72)
        result = time_decay_edge(raw_edge, close_time, reference_hours=48.0)
        assert result == pytest.approx(raw_edge)

    def test_zero_at_close_time(self):
        """At or past close_time, edge should be 0."""
        from weather_markets import time_decay_edge

        raw_edge = 0.10
        # Past close
        result = time_decay_edge(raw_edge, datetime.now(UTC) - timedelta(minutes=1))
        assert result == 0.0

    def test_half_edge_at_half_time(self):
        """At exactly half of reference_hours remaining, edge should be halved."""
        from weather_markets import time_decay_edge

        raw_edge = 0.10
        reference_hours = 48.0
        close_time = datetime.now(UTC) + timedelta(hours=24)  # exactly half
        result = time_decay_edge(raw_edge, close_time, reference_hours=reference_hours)
        assert result == pytest.approx(raw_edge * 0.5, rel=0.02)

    def test_edge_decays_as_close_approaches(self):
        """Edge at 6h remaining < edge at 3h remaining (within 8h reference window)."""
        from weather_markets import time_decay_edge

        raw_edge = 0.10
        e_far = time_decay_edge(raw_edge, datetime.now(UTC) + timedelta(hours=6))
        e_near = time_decay_edge(raw_edge, datetime.now(UTC) + timedelta(hours=3))
        assert e_far > e_near > 0.0

    def test_full_edge_beyond_reference_hours(self):
        """At 10h before close with 8h reference: full edge returned."""
        from weather_markets import time_decay_edge

        close = datetime.now(UTC) + timedelta(hours=10)
        result = time_decay_edge(0.30, close, reference_hours=8.0)
        assert result == pytest.approx(0.30)

    def test_half_edge_at_half_reference_hours(self):
        """At 4h before close with 8h reference: ~50% of edge returned."""
        from weather_markets import time_decay_edge

        close = datetime.now(UTC) + timedelta(hours=4)
        result = time_decay_edge(0.30, close, reference_hours=8.0)
        assert result == pytest.approx(0.15, abs=0.01)

    def test_near_close_retains_meaningful_edge(self):
        """At 2h before close with 8h reference: >5% edge retained (was 4% with 48h)."""
        from weather_markets import time_decay_edge

        close = datetime.now(UTC) + timedelta(hours=2)
        result = time_decay_edge(0.30, close, reference_hours=8.0)
        assert result > 0.05


# ── Task 5: price improvement tracking (#65) ──────────────────────────────────


class TestPriceImprovementTracking:
    def test_log_two_entries_stored(self, tmp_path):
        """log_price_improvement stores rows in the DB."""
        import sqlite3

        import tracker

        db_path = tmp_path / "test.db"
        with patch.object(tracker, "DB_PATH", db_path):
            tracker._db_initialized = False
            tracker.init_db()
            tracker.log_price_improvement("TICK1", 0.60, 0.58, 5, "yes")
            tracker.log_price_improvement("TICK1", 0.60, 0.61, 10, "no")
            tracker._db_initialized = False  # reset for next test

        with sqlite3.connect(db_path) as con:
            rows = con.execute("SELECT * FROM price_improvement").fetchall()
        assert len(rows) == 2

    def test_stats_returns_none_with_fewer_than_5_entries(self, tmp_path):
        """get_price_improvement_stats returns None when < 5 entries exist."""
        import tracker

        db_path = tmp_path / "test2.db"
        with patch.object(tracker, "DB_PATH", db_path):
            tracker._db_initialized = False
            tracker.init_db()
            tracker.log_price_improvement("TICK1", 0.60, 0.58, 5, "yes")
            tracker.log_price_improvement("TICK1", 0.60, 0.61, 10, "no")
            result = tracker.get_price_improvement_stats()
            tracker._db_initialized = False

        assert result is None


class TestCorrelationPersistence:
    """#49: load_correlations_from_backtest / save_correlations round-trip."""

    def test_save_and_reload(self, tmp_path):
        """save_correlations writes JSON; load_correlations_from_backtest reads it back."""
        from unittest.mock import patch

        import monte_carlo

        corr_file = tmp_path / "correlations.json"
        pairs = {"NYC|Boston": 0.91, "Chicago|Denver": 0.43}

        with patch.object(monte_carlo, "_CORR_PATH", corr_file):
            monte_carlo.save_correlations(pairs)
            assert corr_file.exists()
            result = monte_carlo.load_correlations_from_backtest()

        assert result[frozenset({"NYC", "Boston"})] == pytest.approx(0.91)
        assert result[frozenset({"Chicago", "Denver"})] == pytest.approx(0.43)

    def test_fallback_to_hardcoded_when_file_missing(self, tmp_path):
        """When correlations.json is absent, returns _HARDCODED_CORR."""
        from unittest.mock import patch

        import monte_carlo

        missing = tmp_path / "correlations.json"

        with patch.object(monte_carlo, "_CORR_PATH", missing):
            result = monte_carlo.load_correlations_from_backtest()

        # NYC|Boston hardcoded at 0.85
        assert result[frozenset({"NYC", "Boston"})] == pytest.approx(0.85)

    def test_save_correlations_valid_json(self, tmp_path):
        """save_correlations produces valid JSON with pipe-separated keys."""
        import json
        from unittest.mock import patch

        import monte_carlo

        corr_file = tmp_path / "correlations.json"
        with patch.object(monte_carlo, "_CORR_PATH", corr_file):
            monte_carlo.save_correlations({"LA|Phoenix": 0.60})

        raw = json.loads(corr_file.read_text())
        assert "LA|Phoenix" in raw
        assert raw["LA|Phoenix"] == pytest.approx(0.60)

    def test_unknown_pair_returns_zero_after_load(self, tmp_path):
        """After loading, unknown city pairs return 0.0."""
        from unittest.mock import patch

        import monte_carlo

        corr_file = tmp_path / "correlations.json"
        with patch.object(monte_carlo, "_CORR_PATH", corr_file):
            monte_carlo.save_correlations({"NYC|Boston": 0.88})
            result = monte_carlo.load_correlations_from_backtest()

        assert result.get(frozenset({"NYC", "Honolulu"}), 0.0) == 0.0


class TestSlippageAdjustedPrice:
    """#50: slippage_adjusted_price uses 0.001 * sqrt(quantity) model."""

    def test_buy_yes_increases_price(self):
        """Buying YES adds slippage to base price."""
        from paper import slippage_adjusted_price

        result = slippage_adjusted_price(0.50, 100, "yes")
        expected_slip = 0.001 * (100**0.5)  # 0.01
        assert result == pytest.approx(0.50 + expected_slip, rel=1e-5)

    def test_buy_no_decreases_price(self):
        """Buying NO subtracts slippage (worse fill for the buyer)."""
        from paper import slippage_adjusted_price

        result = slippage_adjusted_price(0.40, 100, "no")
        expected_slip = 0.001 * (100**0.5)
        assert result == pytest.approx(0.40 - expected_slip, rel=1e-5)

    def test_zero_slippage_at_quantity_zero(self):
        """quantity=1 produces 0.001 slippage."""
        from paper import slippage_adjusted_price

        result = slippage_adjusted_price(0.50, 1, "yes")
        assert result == pytest.approx(0.501, rel=1e-5)

    def test_clamped_to_0_01_0_99(self):
        """Output must always be in [0.01, 0.99]."""
        from paper import slippage_adjusted_price

        high = slippage_adjusted_price(0.99, 1_000_000, "yes")
        low = slippage_adjusted_price(0.01, 1_000_000, "no")
        assert high <= 0.99
        assert low >= 0.01

    def test_place_paper_order_stores_actual_fill_price(self, tmp_path):
        """place_paper_order records actual_fill_price != entry_price for large orders."""
        import shutil
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        import paper

        tmpdir = tempfile.mkdtemp()
        try:
            with patch("paper.DATA_PATH", Path(tmpdir) / "paper_trades.json"):
                trade = paper.place_paper_order(
                    ticker="KXHIGH-25APR10-NYC",
                    side="yes",
                    quantity=100,
                    entry_price=0.50,
                    entry_prob=0.65,
                    city="NYC",
                    target_date="2025-04-10",
                )
            assert "actual_fill_price" in trade
            assert trade["actual_fill_price"] != trade["entry_price"]
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


# ── Task 5: tiered auto-trade ─────────────────────────────────────────────────


def test_auto_place_trades_med_tier_uses_20_cap(monkeypatch):
    """_auto_place_trades with cap=20.0 should call kelly_quantity with cap=20.0."""
    import main
    import order_executor as _oe

    # Multi-day opp (default days_out=1) is gated by the real, wall-clock-
    # dependent _in_gfs_update_window() -- not mocking this makes the test
    # spuriously fail whenever it runs during that recurring UTC window.
    monkeypatch.setattr(_oe, "_in_gfs_update_window", lambda now_utc=None: False)

    captured_caps = []

    def fake_kelly_quantity(kf, price, min_dollars=1.0, cap=None, method=None):
        captured_caps.append(cap)
        # Return 10 contracts so the trade goes through
        return 10

    def fake_portfolio_kelly_fraction(ci_kelly, city, target_date, side=None):
        return 0.05  # non-trivial fraction so we don't skip

    def fake_get_open_trades():
        return []  # no existing positions

    def fake_is_paused_drawdown():
        return False

    def fake_is_daily_loss_halted(client=None):
        return False

    def fake_is_streak_paused():
        return False

    def fake_place_paper_order(*args, **kwargs):
        return {"id": 1}

    def fake_was_ordered_this_cycle(ticker, side, cycle):
        return False

    monkeypatch.setattr("order_executor.place_paper_order", fake_place_paper_order)
    monkeypatch.setattr(
        "order_executor.execution_log.was_ordered_this_cycle",
        fake_was_ordered_this_cycle,
    )

    import paper

    monkeypatch.setattr(paper, "kelly_quantity", fake_kelly_quantity)
    monkeypatch.setattr(
        paper, "portfolio_kelly_fraction", fake_portfolio_kelly_fraction
    )
    monkeypatch.setattr(paper, "get_open_trades", fake_get_open_trades)
    monkeypatch.setattr(paper, "is_paused_drawdown", fake_is_paused_drawdown)
    monkeypatch.setattr(paper, "is_daily_loss_halted", fake_is_daily_loss_halted)
    monkeypatch.setattr(paper, "is_streak_paused", fake_is_streak_paused)
    monkeypatch.setattr(paper, "drawdown_scaling_factor", lambda: 1.0)
    import order_executor as _oe

    monkeypatch.setattr(_oe, "_daily_paper_spend", lambda: 0.0)
    monkeypatch.setattr(
        _oe,
        "_validate_trade_opportunity",
        lambda opp, live=False, market=None: (True, "ok"),
    )
    monkeypatch.setattr(
        _oe.execution_log, "was_traded_today", lambda ticker, side: False
    )

    opps = [
        (
            {"ticker": "KXHIGH-26APR15-NYC", "_city": "NYC", "_date": None},
            {
                "net_signal": "STRONG BUY",
                "time_risk": "LOW",
                "recommended_side": "yes",
                "ci_adjusted_kelly": 0.10,
                "market_prob": 0.40,
                "forecast_prob": 0.60,
                "net_edge": 0.18,
                "method": "ensemble",
                "model_consensus": True,
                "near_threshold": False,
            },
        )
    ]

    placed = main._auto_place_trades(opps, client=None, cap=20.0)

    assert placed == 1
    assert len(captured_caps) == 1, f"kelly_quantity called {len(captured_caps)} times"
    assert captured_caps[0] == 20.0, f"Expected cap=20.0, got cap={captured_caps[0]}"


def test_auto_place_trades_stops_at_daily_spend_cap(monkeypatch):
    """Should not place trades when MAX_DAILY_SPEND is already reached."""
    import paper
    import utils

    monkeypatch.setattr(
        utils, "MAX_DAILY_SPEND", 0.01
    )  # $0.01 cap — immediately exceeded
    import order_executor as _oe

    monkeypatch.setattr(
        _oe, "MAX_DAILY_SPEND", 0.01
    )  # $0.01 cap in order_executor's namespace
    monkeypatch.setattr(_oe, "_daily_paper_spend", lambda: 50.0)  # already spent $50

    placed_count = [0]

    def fake_place(*a, **kw):
        placed_count[0] += 1
        return {"id": 1, "cost": 10.0}

    monkeypatch.setattr(paper, "place_paper_order", fake_place)

    # Build a minimal opp that would otherwise be placed
    enriched = {"ticker": "TEST-TICKER", "_city": "NYC", "_date": None}
    analysis = {
        "net_signal": "BUY",
        "time_risk": "LOW",
        "recommended_side": "yes",
        "market_prob": 0.40,
        "forecast_prob": 0.65,
        "net_edge": 0.28,
        "ci_adjusted_kelly": 0.05,
        "model_consensus": True,
        "method": "ensemble",
    }
    from main import _auto_place_trades

    result = _auto_place_trades([(enriched, analysis)], cap=50.0)
    assert result == 0
    assert placed_count[0] == 0


# ── Task 7: early exit loop ────────────────────────────────────────────────────


def test_check_early_exits_closes_position_when_prob_flips(tmp_path, monkeypatch):
    """If updated prob shifts >25pp against position, close_paper_early is called."""
    import importlib

    import paper

    # Isolate paper storage in a temp dir so other tests' trades don't bleed in
    monkeypatch.setattr(paper, "DATA_PATH", tmp_path / "paper_trades.json")
    importlib.reload(paper)
    # Re-apply DATA_PATH after reload (reload re-executes module-level assignment)
    monkeypatch.setattr(paper, "DATA_PATH", tmp_path / "paper_trades.json")

    from paper import get_open_trades, place_paper_order

    # Place an open YES trade at 70% prob.
    # close_time far in the future so the 24h gate doesn't skip the early-exit check.
    place_paper_order(
        "TEST-TICKER",
        "yes",
        5,
        0.70,
        entry_prob=0.70,
        close_time="2099-01-01T00:00:00Z",
    )
    trade_id = get_open_trades()[0]["id"]

    # Back-date entered_at so the 12h hold-time guard doesn't block the exit check
    from datetime import datetime as _dt
    from datetime import timedelta as _td

    _old_time = (_dt.now(UTC) - _td(hours=24)).isoformat()
    _pdata = paper._load()
    for _t in _pdata.get("trades", []):
        _t["entered_at"] = _old_time
    paper._save(_pdata)

    closed = []

    def fake_close(tid, exit_price):
        closed.append((tid, exit_price))
        return {"id": tid, "outcome": "early_exit", "pnl": -1.0}

    fake_market = {"ticker": "TEST-TICKER", "yes_bid": 48, "yes_ask": 52}
    # entry_prob=0.70 → current=0.40: shift=0.30 > 0.25 threshold → triggers early exit
    fake_analysis = {"forecast_prob": 0.40, "market_prob": 0.50}

    # Patch at the module where names are resolved inside _check_early_exits (order_executor)
    import order_executor as _oe

    monkeypatch.setattr(paper, "close_paper_early", fake_close)
    monkeypatch.setattr(_oe, "analyze_trade", lambda e: fake_analysis)
    monkeypatch.setattr(_oe, "enrich_with_forecast", lambda m: m)
    monkeypatch.setattr(_oe, "get_weather_markets", lambda client: [fake_market])

    from main import _check_early_exits

    result = _check_early_exits(client="fake-client")

    assert result == 1
    assert len(closed) == 1
    assert closed[0][0] == trade_id


# ── L3-B regression: cmd_watch must auto-execute check_model_exits recommendations ─────


def test_check_model_exits_includes_market_in_rec(tmp_path, monkeypatch):
    """check_model_exits must include 'market' key in each recommendation (L3-B)."""
    import importlib

    import paper

    monkeypatch.setattr(paper, "DATA_PATH", tmp_path / "paper_trades.json")
    importlib.reload(paper)
    monkeypatch.setattr(paper, "DATA_PATH", tmp_path / "paper_trades.json")

    paper.place_paper_order("TEST-FLIP", "yes", 5, 0.65, entry_prob=0.65)

    # Back-date entered_at so the 12h hold-time guard doesn't block the exit check
    from datetime import datetime as _dt
    from datetime import timedelta as _td

    _old_time = (_dt.now(UTC) - _td(hours=24)).isoformat()
    _pdata = paper._load()
    for _t in _pdata.get("trades", []):
        _t["entered_at"] = _old_time
    paper._save(_pdata)

    fake_market = {"ticker": "TEST-FLIP", "yes_bid": 30, "yes_ask": 36}
    # net_edge < -0.10 → model_flipped for a YES position
    fake_analysis = {
        "edge": -0.12,
        "net_edge": -0.12,
        "forecast_prob": 0.38,
        "market_prob": 0.50,
    }

    fake_client = type("C", (), {"get_market": lambda self, t: fake_market})()

    monkeypatch.setattr("weather_markets.analyze_trade", lambda e: fake_analysis)
    monkeypatch.setattr("weather_markets.enrich_with_forecast", lambda m: m)

    recs = paper.check_model_exits(fake_client)

    assert len(recs) == 1, "Expected one model_flipped recommendation"
    assert "market" in recs[0], "Recommendation must include 'market' key (L3-B)"
    assert recs[0]["market"] is fake_market


def test_cmd_watch_auto_executes_model_exits(tmp_path, monkeypatch):
    """cmd_watch must call close_paper_early for each exit recommendation, not just print (L3-B)."""
    import importlib

    import main
    import paper

    monkeypatch.setattr(paper, "DATA_PATH", tmp_path / "paper_trades.json")
    importlib.reload(paper)
    monkeypatch.setattr(paper, "DATA_PATH", tmp_path / "paper_trades.json")

    paper.place_paper_order("EXIT-TICKER", "yes", 5, 0.65, entry_prob=0.65)
    open_id = paper.get_open_trades()[0]["id"]

    fake_market = {"ticker": "EXIT-TICKER", "yes_bid": 28, "yes_ask": 34}
    fake_rec = {
        "trade": paper.get_open_trades()[0],
        "reason": "model_flipped",
        "current_edge": -0.12,
        "held_side": "yes",
        "market": fake_market,
    }

    closed: list = []

    def fake_close(tid, exit_price):
        closed.append((tid, exit_price))
        return {"id": tid, "outcome": "early_exit", "pnl": -0.50}

    monkeypatch.setattr(paper, "close_paper_early", fake_close)
    monkeypatch.setattr(main, "RUNNING_FLAG_PATH", tmp_path / ".cron_running")
    monkeypatch.setattr(main, "KILL_SWITCH_PATH", tmp_path / ".kill_switch")

    # Patch check_model_exits to return our rec immediately, then [] to stop the loop
    call_count = {"n": 0}

    def fake_check_exits(client=None):
        call_count["n"] += 1
        return [fake_rec] if call_count["n"] == 1 else []

    from unittest.mock import MagicMock

    monkeypatch.setattr("paper.check_model_exits", fake_check_exits)
    monkeypatch.setattr("paper.check_expiring_trades", lambda warn_hours=24: [])
    monkeypatch.setattr(main, "get_weather_markets", lambda client: [])
    monkeypatch.setattr(main, "check_ensemble_circuit_health", lambda: None)
    monkeypatch.setattr(main, "_check_startup_orders", lambda: None)
    monkeypatch.setattr(main, "sync_outcomes", lambda client: 0)
    monkeypatch.setattr(main, "_check_early_exits", lambda client=None: 0)

    # Drive one iteration of the watch loop by raising KeyboardInterrupt after first pass
    sleep_calls = {"n": 0}

    def fake_sleep(s):
        sleep_calls["n"] += 1
        if sleep_calls["n"] >= 1:
            raise KeyboardInterrupt

    monkeypatch.setattr("time.sleep", fake_sleep)
    monkeypatch.setattr("paper.is_paused_drawdown", lambda: False)

    try:
        main.cmd_watch(MagicMock())
    except (KeyboardInterrupt, SystemExit):
        pass

    assert len(closed) >= 1, (
        "cmd_watch must call close_paper_early for model exit recommendations (L3-B)"
    )
    assert closed[0][0] == open_id


# ── L3-C regression: paper orders must be logged so was_traded_today() survives restarts ──


def test_auto_place_trades_logs_paper_order_to_execution_log(tmp_path, monkeypatch):
    """_auto_place_trades must log paper orders to execution_log so was_traded_today()
    returns True after a process restart, even for settled positions (L3-C)."""
    import importlib

    import execution_log
    import main
    import order_executor as _oe
    import paper

    # Multi-day opp (days_out=1) is gated by the real, wall-clock-dependent
    # _in_gfs_update_window() -- not mocking this makes the test spuriously
    # fail whenever it runs during that recurring UTC window.
    monkeypatch.setattr(_oe, "_in_gfs_update_window", lambda now_utc=None: False)

    # Isolate both storage files
    monkeypatch.setattr(paper, "DATA_PATH", tmp_path / "paper_trades.json")
    monkeypatch.setattr(execution_log, "DB_PATH", tmp_path / "exec.db")
    importlib.reload(paper)
    importlib.reload(execution_log)
    monkeypatch.setattr(paper, "DATA_PATH", tmp_path / "paper_trades.json")
    monkeypatch.setattr(execution_log, "DB_PATH", tmp_path / "exec.db")

    from utils import STRONG_EDGE

    ticker = "KXHIGH-NYC-26APR30-B70"
    fake_market = {"ticker": ticker, "yes_bid": 30, "yes_ask": 34, "_city": "NYC"}
    fake_analysis = {
        "edge": STRONG_EDGE + 0.06,
        "net_edge": STRONG_EDGE + 0.06,
        "adjusted_edge": STRONG_EDGE + 0.06,
        "signal": "STRONG BUY",
        "net_signal": "STRONG BUY",
        "recommended_side": "yes",
        "time_risk": "LOW",
        "forecast_prob": 0.75,
        "market_prob": 0.30,
        "days_out": 1,
        "target_date": "2026-04-30",
        "entry_price": 0.34,
        "fee_adjusted_kelly": 0.05,
        "ci_adjusted_kelly": 0.05,
    }

    monkeypatch.setattr(main, "get_weather_markets", lambda client: [fake_market])
    monkeypatch.setattr(main, "enrich_with_forecast", lambda m: m)
    monkeypatch.setattr(main, "analyze_trade", lambda e: fake_analysis)
    monkeypatch.setattr("paper.is_paused_drawdown", lambda: False)
    monkeypatch.setattr("paper.is_daily_loss_halted", lambda client=None: False)
    monkeypatch.setattr("paper.is_streak_paused", lambda: False)

    strong_opps = [(fake_market, fake_analysis)]
    main._auto_place_trades(strong_opps, client=None)

    # was_traded_today must now return True — surviving a "restart" (fresh module reload)
    assert execution_log.was_traded_today(ticker, "yes"), (
        "Paper order must be logged to execution_log so was_traded_today() returns True "
        "after restart (L3-C)"
    )


def test_was_traded_today_blocks_reentry_after_settlement(tmp_path, monkeypatch):
    """After a paper position settles, was_traded_today() must still block re-entry
    on the same day because the order was logged to execution_log (L3-C)."""
    import importlib

    import execution_log
    import paper

    monkeypatch.setattr(paper, "DATA_PATH", tmp_path / "paper_trades.json")
    monkeypatch.setattr(execution_log, "DB_PATH", tmp_path / "exec.db")
    importlib.reload(paper)
    importlib.reload(execution_log)
    monkeypatch.setattr(paper, "DATA_PATH", tmp_path / "paper_trades.json")
    monkeypatch.setattr(execution_log, "DB_PATH", tmp_path / "exec.db")

    ticker = "KXHIGH-NYC-26APR30-B70"

    # Simulate what _auto_place_trades now does: log the paper order
    execution_log.log_order(
        ticker=ticker,
        side="yes",
        quantity=3,
        price=0.34,
        order_type="market",
        status="filled",
        live=False,
    )

    # Simulate settle: mark trade as settled in paper trades
    paper.place_paper_order(ticker, "yes", 3, 0.34)
    trade_id = paper.get_open_trades()[0]["id"]
    paper.settle_paper_trade(trade_id, outcome_yes=True)

    # open_tickers would be empty (position settled), but was_traded_today must block
    open_tickers = {t["ticker"] for t in paper.get_open_trades()}
    assert ticker not in open_tickers, "Settled trade should not be in open_tickers"
    assert execution_log.was_traded_today(ticker, "yes"), (
        "was_traded_today() must return True even after position settles (L3-C)"
    )


# ── L4-B regression: null-city rows must not pollute get_quintile_bias ──


def test_log_prediction_with_null_city_is_noop(tmp_path):
    """log_prediction(city=None) must write nothing to the DB (L4-B)."""
    import sqlite3
    from unittest.mock import patch

    import tracker

    db_path = tmp_path / "tracker.db"
    with patch.object(tracker, "DB_PATH", db_path):
        tracker._db_initialized = False
        tracker.init_db()

        tracker.log_prediction(
            ticker="KXHIGH-NYC-26APR25-B70",
            city=None,
            market_date=None,
            analysis={"forecast_prob": 0.70, "edge": 0.15, "recommended_side": "yes"},
        )
        tracker._db_initialized = False

    con = sqlite3.connect(str(db_path))
    rows = con.execute("SELECT * FROM predictions").fetchall()
    con.close()
    assert rows == [], "log_prediction(city=None) must not write to predictions (L4-B)"


def test_get_quintile_bias_excludes_null_city_rows(tmp_path):
    """get_quintile_bias must ignore rows where city IS NULL even when no city filter
    is applied (L4-B)."""
    import sqlite3
    from datetime import date
    from unittest.mock import patch

    import tracker

    db_path = tmp_path / "tracker.db"

    with patch.object(tracker, "DB_PATH", db_path):
        tracker._db_initialized = False
        tracker.init_db()

        today = date.today().isoformat()
        con = sqlite3.connect(str(db_path))

        # Null-city prediction that always resolves YES — must NOT affect bias
        con.execute(
            "INSERT INTO predictions (ticker, city, market_date, our_prob, predicted_at)"
            " VALUES (?, NULL, ?, 0.50, ?)",
            ("KXHIGH-NULL-26APR25-B70", today, today),
        )
        con.execute(
            "INSERT INTO outcomes (ticker, settled_yes, settled_at) VALUES (?, 1, ?)",
            ("KXHIGH-NULL-26APR25-B70", today),
        )

        # Real-city rows: 3 YES + 3 NO → mean ≈ 0.5, bias near 0
        for i in range(6):
            tkr = f"KXHIGH-NYC-26APR{i:02d}-B70"
            con.execute(
                "INSERT INTO predictions (ticker, city, market_date, our_prob, predicted_at)"
                " VALUES (?, 'NYC', ?, 0.50, ?)",
                (tkr, today, today),
            )
            con.execute(
                "INSERT INTO outcomes (ticker, settled_yes, settled_at) VALUES (?, ?, ?)",
                (tkr, 1 if i < 3 else 0, today),
            )
        con.commit()
        con.close()

        bias = tracker.get_quintile_bias(city="NYC", month=None, forecast_prob=0.50)
        tracker._db_initialized = False

    assert isinstance(bias, float), "get_quintile_bias must return a float (L4-B)"


# ── L4-C regression: small-sample shrinkage toward 0 ──


def test_get_bias_shrinks_toward_zero_for_small_samples(tmp_path):
    """With only min_samples rows, the returned bias must be strictly smaller in
    magnitude than the raw mean bias — shrinkage prevents single-outlier dominance (L4-C)."""
    import sqlite3
    from datetime import date
    from unittest.mock import patch

    import tracker

    db_path = tmp_path / "tracker.db"
    with patch.object(tracker, "DB_PATH", db_path):
        tracker._db_initialized = False
        tracker.init_db()

        today = date.today().isoformat()
        con = sqlite3.connect(str(db_path))

        # 5 predictions: all our_prob=0.80, all settled YES=0 → raw bias = +0.80
        # With shrinkage prior=10: shrunk = 0.80 * 5/15 ≈ 0.267
        for i in range(5):
            tkr = f"KXHIGH-TEST-SMALL-{i}"
            con.execute(
                "INSERT INTO predictions (ticker, city, market_date, our_prob, predicted_at)"
                " VALUES (?, 'TEST', ?, 0.80, ?)",
                (tkr, today, today),
            )
            con.execute(
                "INSERT INTO outcomes (ticker, settled_yes, settled_at) VALUES (?, 0, ?)",
                (tkr, today),
            )
        con.commit()
        con.close()

        bias = tracker.get_bias(city="TEST", month=None)
        tracker._db_initialized = False

    # Raw bias would be 0.80; shrinkage must bring it below that
    assert 0 < bias < 0.80, (
        f"get_bias with 5 samples must shrink below raw mean 0.80; got {bias:.4f} (L4-C)"
    )
    # At n=5, prior=10: expected ≈ 0.267; allow small floating-point tolerance
    assert bias < 0.40, (
        f"Shrinkage at n=5 must reduce bias to <0.40; got {bias:.4f} (L4-C)"
    )


def test_get_bias_near_full_strength_for_large_samples(tmp_path):
    """With many samples the shrinkage factor is negligible — bias stays near its
    raw computed value (L4-C)."""
    import sqlite3
    from datetime import date
    from unittest.mock import patch

    import tracker

    db_path = tmp_path / "tracker.db"
    with patch.object(tracker, "DB_PATH", db_path):
        tracker._db_initialized = False
        tracker.init_db()

        today = date.today().isoformat()
        con = sqlite3.connect(str(db_path))

        # 100 predictions: all our_prob=0.60, all settled YES=0 → raw bias = +0.60
        # With shrinkage prior=10: shrunk = 0.60 * 100/110 ≈ 0.545
        for i in range(100):
            tkr = f"KXHIGH-TEST-LARGE-{i}"
            con.execute(
                "INSERT INTO predictions (ticker, city, market_date, our_prob, predicted_at)"
                " VALUES (?, 'BIG', ?, 0.60, ?)",
                (tkr, today, today),
            )
            con.execute(
                "INSERT INTO outcomes (ticker, settled_yes, settled_at) VALUES (?, 0, ?)",
                (tkr, today),
            )
        con.commit()
        con.close()

        bias = tracker.get_bias(city="BIG", month=None)
        tracker._db_initialized = False

    # n=100, prior=10: multiplier = 100/110 ≈ 0.909 — should be > 85% of raw 0.60
    assert bias > 0.50, (
        f"With n=100 samples shrinkage should be <10%; bias={bias:.4f} (L4-C)"
    )


# ── L7-B regression: paper fill price must be ask, not mid ───────────────────


def _l7b_common_patches(monkeypatch):
    """Apply the common monkeypatches needed for L7-B _auto_place_trades tests."""
    import main
    import order_executor as _oe
    import paper

    # These tests use multi-day opps (days_out >= 1), which real
    # _in_gfs_update_window() gates during a real recurring UTC window --
    # not mocking this makes the test spuriously fail whenever it happens to
    # run during that window, same bug class as the 2026-07-09 GFS-lockout
    # test flakiness already fixed elsewhere in this file.
    monkeypatch.setattr(_oe, "_in_gfs_update_window", lambda now_utc=None: False)
    monkeypatch.setattr(paper, "is_paused_drawdown", lambda: False)
    monkeypatch.setattr(paper, "is_daily_loss_halted", lambda client=None: False)
    monkeypatch.setattr(paper, "is_streak_paused", lambda: False)
    monkeypatch.setattr(paper, "drawdown_scaling_factor", lambda: 1.0)
    import order_executor as _oe

    monkeypatch.setattr(_oe, "_daily_paper_spend", lambda: 0.0)
    monkeypatch.setattr(
        _oe,
        "_validate_trade_opportunity",
        lambda opp, live=False, market=None: (True, "ok"),
    )
    monkeypatch.setattr(
        _oe.execution_log, "was_traded_today", lambda ticker, side: False
    )
    monkeypatch.setattr(
        _oe.execution_log, "was_ordered_this_cycle", lambda ticker, side, cycle: False
    )
    monkeypatch.setattr(
        _oe.execution_log, "was_ordered_recently", lambda ticker, days=7: False
    )
    return main, paper


def test_auto_place_uses_yes_ask_not_mid_for_yes_trades(monkeypatch):
    """Regression for L7-B: for YES trades, entry_price passed to place_paper_order
    must equal yes_ask (what you actually pay), not the mid-price.

    Before fix: entry_price = market_prob = mid = (38+42)/2/100 = 0.40
    After fix:  entry_price = yes_ask = 42/100 = 0.42
    """
    main, paper = _l7b_common_patches(monkeypatch)

    captured_prices = []

    def fake_place_paper_order(ticker, side, qty, entry_price, **kwargs):
        captured_prices.append(entry_price)
        return {"id": 1}

    monkeypatch.setattr("order_executor.place_paper_order", fake_place_paper_order)

    # Market with yes_bid=38¢, yes_ask=42¢ → mid=40¢ (market_prob=0.40)
    # Correct YES fill price = yes_ask = 0.42 (not mid 0.40)
    fake_market = {
        "ticker": "KXHIGHNYC-26APR30-T70",
        "yes_bid": 38,
        "yes_ask": 42,
        "_city": "NYC",
        "_date": None,
    }

    fake_analysis = {
        "edge": 0.25,  # blended_prob - mid = 0.65 - 0.40
        "net_edge": 0.20,
        "adjusted_edge": 0.20,
        "signal": "STRONG BUY",
        "net_signal": "STRONG BUY",
        "recommended_side": "yes",
        "time_risk": "LOW",
        "forecast_prob": 0.65,
        "market_prob": 0.40,  # mid-price
        "days_out": 2,
        "target_date": "2026-04-30",
        "fee_adjusted_kelly": 0.06,
        "ci_adjusted_kelly": 0.06,
        "model_consensus": True,
        "near_threshold": False,
        "method": "ensemble",
    }

    main._auto_place_trades([(fake_market, fake_analysis)], client=None)

    assert len(captured_prices) == 1, (
        f"Expected exactly 1 paper order; got {len(captured_prices)}"
    )
    assert abs(captured_prices[0] - 0.42) < 0.001, (
        f"L7-B: YES entry_price={captured_prices[0]:.4f} must be yes_ask=0.42, "
        f"not mid=0.40 (paper P&L would be systematically optimistic)"
    )


def test_auto_place_uses_no_ask_not_mid_for_no_trades(monkeypatch):
    """Regression for L7-B: for NO trades, entry_price must equal no_ask = 1 - yes_bid
    (what you actually pay to buy NO), not 1 - mid.

    Market: yes_bid=38¢, yes_ask=42¢ → mid=40¢, no_ask=62¢ (=1-0.38)
    Before fix: entry_price = 1 - mid = 1 - 0.40 = 0.60
    After fix:  entry_price = 1 - yes_bid = 1 - 0.38 = 0.62
    """
    main, paper = _l7b_common_patches(monkeypatch)

    captured_prices = []

    def fake_place_paper_order(ticker, side, qty, entry_price, **kwargs):
        captured_prices.append(entry_price)
        return {"id": 1}

    monkeypatch.setattr("order_executor.place_paper_order", fake_place_paper_order)

    # Market with yes_bid=38¢, yes_ask=42¢ → mid=40¢
    # Correct NO fill price = no_ask = 1 - yes_bid = 1 - 0.38 = 0.62 (not 1 - 0.40 = 0.60)
    fake_market = {
        "ticker": "KXHIGHNYC-26APR30-T70",
        "yes_bid": 38,
        "yes_ask": 42,
        "_city": "NYC",
        "_date": None,
    }
    fake_analysis = {
        "edge": -0.15,  # blended_prob - mid = 0.25 - 0.40 (negative → NO side)
        "net_edge": 0.10,
        "adjusted_edge": 0.10,
        "signal": "SELL",
        "net_signal": "SELL",
        "recommended_side": "no",
        "time_risk": "LOW",
        "forecast_prob": 0.25,  # we think YES prob is 25%; market says 40% → buy NO
        "market_prob": 0.40,  # mid-price
        "days_out": 2,
        "target_date": "2026-04-30",
        "fee_adjusted_kelly": 0.05,
        "ci_adjusted_kelly": 0.05,
        "model_consensus": True,
        "near_threshold": False,
        "method": "ensemble",
    }

    main._auto_place_trades([(fake_market, fake_analysis)], client=None)

    assert len(captured_prices) == 1, (
        f"Expected exactly 1 paper order; got {len(captured_prices)}"
    )
    assert abs(captured_prices[0] - 0.62) < 0.001, (
        f"L7-B: NO entry_price={captured_prices[0]:.4f} must be no_ask=0.62 "
        f"(= 1 - yes_bid = 1 - 0.38), not 1 - mid = 0.60"
    )


# ── L7-D regression: net_edge and adjusted_edge must decay near close ─────────


class TestTimeDecayEdgeScope:
    """Regression tests for L7-D: time_decay_edge must apply to all edge metrics
    (edge, entry_side_edge, net_edge → adjusted_edge), not only the display 'edge'.

    Before fix: only result['edge'] was decayed.  result['net_edge'] and
    result['adjusted_edge'] were computed AFTER the decay block and received the
    full undecayed net EV, so the gate (adjusted_edge) passed near-close markets
    at full strength even when the display showed a near-zero 'edge'.
    """

    _ENRICHED = {
        "title": "NYC high > 70°F",
        "_city": "NYC",
        "_hour": None,
        "_forecast": {
            "high_f": 74.0,
            "low_f": 60.0,
            "precip_in": 0.0,
            "city": "NYC",
            "models_used": 3,
            "high_range": (72.0, 76.0),
        },
        "yes_bid": 50,
        "yes_ask": 56,
        "no_bid": 44,
        "close_time": "",  # overridden per test
        "series_ticker": "KXHIGHNY",
        "volume": 1000,
        "open_interest": 400,
    }

    def _make_enriched(self, close_iso: str):
        from datetime import UTC, datetime

        target = datetime.now(UTC).date()  # same-day market
        e = dict(self._ENRICHED)
        e["_date"] = target
        e["_forecast"] = dict(self._ENRICHED["_forecast"])
        e["_forecast"]["date"] = target.isoformat()
        e["ticker"] = f"KXHIGHNY-{target.strftime('%d%b%y').upper()}-T70"
        e["close_time"] = close_iso
        return e

    def _run(self, close_iso: str):
        from unittest.mock import patch

        import weather_markets as wm

        enriched = self._make_enriched(close_iso)
        with (
            patch.object(
                wm, "get_ensemble_temps", return_value=[75.0] * 12 + [65.0] * 8
            ),
            patch.object(wm, "fetch_temperature_nbm", return_value=71.0),
            patch.object(wm, "fetch_temperature_ecmwf", return_value=71.5),
            patch("weather_markets.get_ensemble_members", return_value=[]),
            patch("weather_markets.climatological_prob", return_value=0.60),
            patch("weather_markets.nws_prob", return_value=None),
            patch("weather_markets.get_live_observation", return_value=None),
            patch("weather_markets.temperature_adjustment", return_value=0.0),
            patch.object(wm, "_SEASONAL_WEIGHTS", {}),
            patch.object(wm, "_CONDITION_WEIGHTS", {}),
            patch.object(wm, "_CITY_WEIGHTS", {}),
            patch.object(
                wm, "_get_consensus_probs", return_value=(None, None, None, None)
            ),
        ):
            return wm.analyze_trade(enriched)

    def test_net_edge_reduced_near_close_vs_far(self):
        """Regression for L7-D: net_edge must be smaller when close_time is
        imminent (1h away) compared to far (24h away) for the same forecast.

        Before fix: both returned the same net_edge because time decay was not
        applied to net_edge — only to the display 'edge'.
        """
        from datetime import UTC, datetime, timedelta

        now = datetime.now(UTC)
        far_close = (now + timedelta(hours=24)).isoformat()
        near_close = (now + timedelta(minutes=30)).isoformat()

        far = self._run(far_close)
        near = self._run(near_close)

        assert far is not None and near is not None
        assert abs(near["net_edge"]) < abs(far["net_edge"]), (
            f"L7-D: time decay must reduce net_edge magnitude when close is near: "
            f"|near|={abs(near['net_edge']):.4f} |far|={abs(far['net_edge']):.4f} — "
            f"before fix both were equal (time decay didn't reach net_edge)"
        )

    def test_adjusted_edge_zero_at_close(self):
        """Regression for L7-D: adjusted_edge must be 0 when market has already
        closed (close_time in the past).

        Before fix: adjusted_edge was based on undecayed net_edge and remained
        positive even past close, allowing ghost trades past market expiry.
        """
        from datetime import UTC, datetime, timedelta

        past_close = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
        result = self._run(past_close)

        assert result is not None
        assert result["adjusted_edge"] == 0.0, (
            f"L7-D: adjusted_edge must be 0 when market is past close; "
            f"got {result['adjusted_edge']:.4f}"
        )
        assert result["net_edge"] == 0.0, (
            f"L7-D: net_edge must be 0 when market is past close; "
            f"got {result['net_edge']:.4f}"
        )


def test_cmd_readiness_fails_when_brier_above_threshold(monkeypatch, capsys):
    """cmd_readiness returns False and prints FAIL when Brier > 0.20."""
    from unittest.mock import MagicMock

    import circuit_breaker
    import main

    monkeypatch.setattr(
        "backtest.run_backtest",
        lambda *a, **kw: {
            "train_brier": 0.28,
            "val_brier": 0.28,
            "val_brier_unreliable": False,
            "n_markets": 120,
        },
    )
    monkeypatch.setattr("paper.get_max_drawdown_pct", lambda: 0.05)
    monkeypatch.setattr(circuit_breaker.flash_crash_cb, "_cooldowns", {})

    result = main.cmd_readiness(MagicMock())
    out = capsys.readouterr().out

    assert result is False
    assert "FAIL" in out or "✗" in out


def test_cmd_readiness_passes_when_all_gates_clear(monkeypatch, capsys):
    """cmd_readiness returns True only when all 4 gates pass."""
    from unittest.mock import MagicMock

    import circuit_breaker
    import main

    monkeypatch.setattr(
        "backtest.run_backtest",
        lambda *a, **kw: {
            "train_brier": 0.18,
            "val_brier": 0.18,
            "val_brier_unreliable": False,
            "n_markets": 120,
        },
    )
    monkeypatch.setattr("paper.get_max_drawdown_pct", lambda: 0.05)
    monkeypatch.setattr(circuit_breaker.flash_crash_cb, "_cooldowns", {})

    result = main.cmd_readiness(MagicMock())
    out = capsys.readouterr().out

    assert result is True
    assert "PASS" in out or "✓" in out
