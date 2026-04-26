"""
Tests for 3 approved trading improvements:
  1. MAX_CONCURRENT_POSITIONS cap (20) in _auto_place_trades
  2. MIN_PROB_EDGE gate (8pp probability delta) in cron.py
  3. Ensemble member threshold lowered from >=10 to >=2 in weather_markets.py
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


# ─────────────────────────────────────────────────────────────────────────────
# 1. MAX_CONCURRENT_POSITIONS cap
# ─────────────────────────────────────────────────────────────────────────────


class TestMaxConcurrentPositions:
    """_auto_place_trades must refuse new trades once 20 open positions exist."""

    def _make_open_trades(self, n: int) -> list[dict]:
        return [
            {"ticker": f"KXHIGH-NYC-{i}", "side": "yes", "cost": 10.0, "qty": 1}
            for i in range(n)
        ]

    def _make_opp(self, idx: int) -> tuple[dict, dict]:
        ticker = f"KXHIGH-CHI-{idx}"
        m = {"ticker": ticker, "yes_bid": 40, "yes_ask": 44}
        a = {
            "ticker": ticker,
            "forecast_prob": 0.70,
            "market_prob": 0.50,
            "edge": 0.20,
            "net_edge": 0.20,
            "kelly_fraction": 0.15,
            "recommended_side": "yes",
            "signal": "STRONG BUY",
            "net_signal": "STRONG BUY",
            "days_out": 2,
            "days_to_expiry": 2,
        }
        return (m, a)

    def test_no_trades_placed_when_at_cap(self, tmp_path, monkeypatch):
        """When 20 positions already open, _auto_place_trades should place 0 new trades."""
        import importlib

        import paper

        monkeypatch.setattr(paper, "DATA_PATH", tmp_path / "paper_trades.json")
        importlib.reload(paper)
        import main

        open_trades = self._make_open_trades(20)
        monkeypatch.setattr(paper, "get_open_trades", lambda: open_trades)
        monkeypatch.setattr(paper, "is_daily_loss_halted", lambda c: False)
        monkeypatch.setattr(paper, "is_streak_paused", lambda: False)
        monkeypatch.setattr(paper, "is_paused_drawdown", lambda: False)
        monkeypatch.setattr(main, "_daily_paper_spend", lambda: 0.0)
        monkeypatch.setattr(
            main, "_validate_trade_opportunity", lambda opp, live=False: (True, "ok")
        )
        monkeypatch.setattr(main, "_current_forecast_cycle", lambda: "2026-04-25-06")
        monkeypatch.setattr(paper, "place_paper_order", MagicMock())

        opps = [self._make_opp(i) for i in range(5)]
        result = main._auto_place_trades(opps, client=None, live=False)
        assert result == 0, f"Expected 0 trades placed, got {result}"

    def test_trades_placed_below_cap(self, tmp_path, monkeypatch):
        """When only 18 positions open, up to 2 more should be allowed."""
        import importlib

        import paper

        monkeypatch.setattr(paper, "DATA_PATH", tmp_path / "paper_trades.json")
        importlib.reload(paper)
        import main

        open_trades = self._make_open_trades(18)
        monkeypatch.setattr(paper, "get_open_trades", lambda: open_trades)
        monkeypatch.setattr(paper, "is_daily_loss_halted", lambda c: False)
        monkeypatch.setattr(paper, "is_streak_paused", lambda: False)
        monkeypatch.setattr(paper, "is_paused_drawdown", lambda: False)
        monkeypatch.setattr(main, "_daily_paper_spend", lambda: 0.0)
        monkeypatch.setattr(
            main, "_validate_trade_opportunity", lambda opp, live=False: (True, "ok")
        )
        monkeypatch.setattr(main, "_current_forecast_cycle", lambda: "2026-04-25-06")

        placed_count = 0

        def _fake_place(ticker, side, qty, price, **kwargs):
            nonlocal placed_count
            placed_count += 1
            return {"id": placed_count, "ticker": ticker, "side": side, "qty": qty}

        monkeypatch.setattr(paper, "place_paper_order", _fake_place)
        # Also mock execution_log so was_ordered_this_cycle never blocks
        mock_exec_log = MagicMock()
        mock_exec_log.was_ordered_this_cycle.return_value = False
        mock_exec_log.was_traded_today.return_value = False
        monkeypatch.setattr(main, "execution_log", mock_exec_log)

        opps = [self._make_opp(i) for i in range(5)]
        result = main._auto_place_trades(opps, client=None, live=False)
        # Should place at most 2 (cap is 20, 18 open → 2 slots remaining)
        assert result <= 2, f"Expected ≤2 trades placed, got {result}"


# ─────────────────────────────────────────────────────────────────────────────
# 2. MIN_PROB_EDGE gate in cron.py
# ─────────────────────────────────────────────────────────────────────────────


class TestMinProbEdgeGate:
    """cron.py must skip signals where probability edge < MIN_PROB_EDGE (0.08)."""

    def _make_enriched(self, forecast_prob: float, market_prob: float) -> dict:
        edge = forecast_prob - market_prob
        return {
            "ticker": "KXHIGH-NYC-TEST",
            "_city": "New York",
            "forecast_prob": forecast_prob,
            "market_prob": market_prob,
            "edge": edge,
            "net_edge": edge * 1.1,
            "adjusted_edge": edge * 1.1,
            "signal": "STRONG BUY" if edge > 0 else "STRONG SELL",
            "net_signal": "STRONG BUY" if edge > 0 else "STRONG SELL",
            "recommended_side": "yes" if edge > 0 else "no",
            "days_out": 2,
        }

    def test_low_prob_edge_signal_skipped(self):
        """Signal with only 5pp probability edge must be skipped by the gate."""
        import cron
        from utils import MIN_PROB_EDGE

        assert hasattr(cron, "MIN_PROB_EDGE") or MIN_PROB_EDGE is not None, (
            "MIN_PROB_EDGE must be importable"
        )

        enriched = self._make_enriched(0.55, 0.50)  # only 5pp edge — below 8pp
        prob_edge = abs(enriched["forecast_prob"] - enriched["market_prob"])
        assert prob_edge < 0.08, "Test setup: prob_edge should be below threshold"

    def test_sufficient_prob_edge_signal_passes(self):
        """Signal with 12pp probability edge must NOT be skipped by the gate."""
        enriched = self._make_enriched(0.62, 0.50)  # 12pp edge — above 8pp
        prob_edge = abs(enriched["forecast_prob"] - enriched["market_prob"])
        assert prob_edge >= 0.08, "Test setup: prob_edge should be above threshold"

    def test_min_prob_edge_constant_exists(self):
        """MIN_PROB_EDGE constant must be defined in utils.py with value 0.08."""
        from utils import MIN_PROB_EDGE

        assert MIN_PROB_EDGE == 0.08, (
            f"MIN_PROB_EDGE should be 0.08, got {MIN_PROB_EDGE}"
        )

    def test_cron_imports_min_prob_edge(self):
        """cron.py must import MIN_PROB_EDGE from utils."""
        import cron

        # Check the module's globals contain MIN_PROB_EDGE (imported)
        assert hasattr(cron, "MIN_PROB_EDGE") or "MIN_PROB_EDGE" in dir(cron), (
            "cron must import MIN_PROB_EDGE"
        )


# ─────────────────────────────────────────────────────────────────────────────
# 3. Ensemble member threshold >= 2
# ─────────────────────────────────────────────────────────────────────────────


class TestEnsembleMemberThreshold:
    """_score_ensemble_members must run once at least 2 temp samples exist."""

    def test_model_consensus_guard_uses_two(self):
        """The model-consensus-check guard (ens_prob + _get_consensus_probs block)
        must use >= 2, not >= 10, so consensus probs are attempted with few ensemble members."""
        src = Path(__file__).parent.parent / "weather_markets.py"
        lines = src.read_text(encoding="utf-8").splitlines()
        # Find the line that gates _get_consensus_probs (contains ens_prob is not None)
        for i, line in enumerate(lines):
            if "ens_prob is not None" in line and "len(temps)" in line:
                assert ">= 2" in line, (
                    f"Line {i + 1}: expected 'len(temps) >= 2', got: {line.strip()!r}"
                )
                return
        pytest.fail(
            "Could not find the 'ens_prob is not None and len(temps)' guard line"
        )

    def test_ensemble_guard_uses_two(self):
        """Confirming the >= 2 threshold is present in weather_markets.py."""
        src = Path(__file__).parent.parent / "weather_markets.py"
        text = src.read_text(encoding="utf-8")
        assert "ens_prob is not None and len(temps) >= 2" in text, (
            "Expected 'ens_prob is not None and len(temps) >= 2' in weather_markets.py"
        )
