"""Tests for step-function drawdown-tiered Kelly reduction."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestDrawdownScalingFactor:
    def test_no_drawdown_full_kelly(self):
        import paper

        with patch.object(paper, "_drawdown_snapshot", return_value=(1000.0, 1000.0)):
            assert paper.drawdown_scaling_factor() == pytest.approx(1.0)

    def test_3pct_drawdown_full_kelly(self):
        # With default 20% halt: TIER_4=0.95, so 3% drawdown (0.97) is above TIER_4 → 1.0
        import paper

        with patch.object(paper, "_drawdown_snapshot", return_value=(970.0, 1000.0)):
            assert paper.drawdown_scaling_factor() == pytest.approx(1.0)

    def test_7pct_drawdown_reduced(self):
        # With default 20% halt: TIER_3=0.90, TIER_4=0.95, so 7% drawdown (0.93) → 0.70
        import paper

        with patch.object(paper, "_drawdown_snapshot", return_value=(930.0, 1000.0)):
            assert paper.drawdown_scaling_factor() == pytest.approx(0.70)

    def test_12pct_drawdown_conservative(self):
        # With default 20% halt: TIER_2=0.85, TIER_3=0.90, so 12% drawdown (0.88) → 0.30
        import paper

        with patch.object(paper, "_drawdown_snapshot", return_value=(880.0, 1000.0)):
            assert paper.drawdown_scaling_factor() == pytest.approx(0.30)

    def test_17pct_drawdown_survival(self):
        # With default 20% halt: TIER_1=0.80, TIER_2=0.85, so 17% drawdown (0.83) → 0.10
        import paper

        with patch.object(paper, "_drawdown_snapshot", return_value=(830.0, 1000.0)):
            assert paper.drawdown_scaling_factor() == pytest.approx(0.10)

    def test_20pct_drawdown_paused(self):
        # With default 20% halt: TIER_1=0.80, so exactly 20% drawdown (0.80) → 0.0
        import paper

        with patch.object(paper, "_drawdown_snapshot", return_value=(800.0, 1000.0)):
            assert paper.drawdown_scaling_factor() == pytest.approx(0.0)

    def test_50pct_drawdown_paused(self):
        # Well below halt threshold → 0.0
        import paper

        with patch.object(paper, "_drawdown_snapshot", return_value=(500.0, 1000.0)):
            assert paper.drawdown_scaling_factor() == pytest.approx(0.0)

    def test_zero_peak_balance_returns_one(self):
        import paper

        with patch.object(paper, "_drawdown_snapshot", return_value=(1000.0, 0.0)):
            assert paper.drawdown_scaling_factor() == pytest.approx(1.0)


class TestDrawdownTiersRelativeToHalt:
    """P2-2: Tiers must be absolute constants, not derived from DRAWDOWN_HALT_PCT."""

    def test_tier_constants_are_ordered(self, monkeypatch):
        """Tier ordering invariant: TIER_1 < TIER_2 < TIER_3 < TIER_4 <= 1.0."""
        import paper

        assert paper._DRAWDOWN_TIER_1 < paper._DRAWDOWN_TIER_2
        assert paper._DRAWDOWN_TIER_2 < paper._DRAWDOWN_TIER_3
        assert paper._DRAWDOWN_TIER_3 < paper._DRAWDOWN_TIER_4
        assert paper._DRAWDOWN_TIER_4 <= 1.0

    def test_tier_constants_are_absolute(
        self, monkeypatch, tmp_path, repatch_paper_paths
    ):
        """P2-2: tiers must not shift when DRAWDOWN_HALT_PCT is non-default."""
        import importlib
        import os

        import paper

        # Captured before the reload so the restore check at the end of this
        # test compares against this environment's real value, not a hardcoded
        # 0.20 that a machine setting DRAWDOWN_HALT_PCT in .env would break.
        halt_pct_before = paper.MAX_DRAWDOWN_FRACTION
        env_before = os.environ.get("DRAWDOWN_HALT_PCT")

        monkeypatch.setenv("DRAWDOWN_HALT_PCT", "0.30")
        importlib.reload(paper)
        # backlog L24334: the reload above is load-bearing here (the whole point
        # is re-executing paper.py's module body under the patched env), but it
        # also recomputes DATA_PATH/_LOSS_OVERRIDE_PATH/_ACCURACY_HALT_OVERRIDE_PATH
        # from safe_io.project_root(), discarding conftest's autouse
        # isolate_paper_data patches and re-pointing them at the REAL data/ files
        # for the rest of this test. Re-apply all three via conftest's shared
        # helper so there is one definition of "isolated".
        repatch_paper_paths(paper)
        try:
            # With absolute constants, tiers stay at canonical values
            # regardless of halt %
            assert paper._DRAWDOWN_TIER_1 == 0.80
            assert paper._DRAWDOWN_TIER_2 == 0.85
            assert paper._DRAWDOWN_TIER_3 == 0.90
            assert paper._DRAWDOWN_TIER_4 == 0.95
        finally:
            # Same L24334 family, other direction: monkeypatch.setenv is undone
            # at teardown but the RELOAD is not, so without this every later
            # test in the session would see paper.MAX_DRAWDOWN_FRACTION frozen
            # at 0.30 instead of this environment's real default (paper.py:293
            # reads the env var at import time). Harmless in this file's own
            # order; a real hazard for any `-k`-filtered or reordered run, and
            # for anything that later reads paper.MAX_DRAWDOWN_FRACTION.
            #
            # Restore the ORIGINAL value rather than delenv'ing (opus-review-
            # caught, batch-62): on a machine whose .env sets DRAWDOWN_HALT_PCT,
            # delenv + reload would rebuild the module from the 0.20 fallback,
            # not from that machine's real value, and the assertion below would
            # fail with a misleading "leaked into later tests" message.
            if env_before is None:
                monkeypatch.delenv("DRAWDOWN_HALT_PCT", raising=False)
            else:
                monkeypatch.setenv("DRAWDOWN_HALT_PCT", env_before)
            importlib.reload(paper)

        # Deliberately OUTSIDE the finally: this asserts the restore above
        # actually took effect, but must not be able to mask a genuine failure
        # from the tier assertions in the try block.
        assert paper.MAX_DRAWDOWN_FRACTION == halt_pct_before, (
            "the reload under DRAWDOWN_HALT_PCT=0.30 leaked into later tests"
        )

    def test_halt_at_20pct_drawdown(self, mock_balance_1000, monkeypatch):
        """At 20% drawdown, scaling factor should be 0.0."""
        import paper

        monkeypatch.setattr(paper, "MAX_DRAWDOWN_FRACTION", 0.20)
        monkeypatch.setattr(paper, "_DRAWDOWN_TIER_1", 0.80)
        monkeypatch.setattr(paper, "_DRAWDOWN_TIER_2", 0.85)
        monkeypatch.setattr(paper, "_DRAWDOWN_TIER_3", 0.90)
        monkeypatch.setattr(paper, "_DRAWDOWN_TIER_4", 0.95)
        monkeypatch.setattr(paper, "_drawdown_snapshot", lambda: (790.0, 1000.0))
        assert paper.drawdown_scaling_factor() == 0.0

    def test_full_sizing_near_peak(self, mock_balance_1000, monkeypatch):
        """Above TIER_4, full sizing (1.0) is returned."""
        import paper

        monkeypatch.setattr(paper, "MAX_DRAWDOWN_FRACTION", 0.20)
        monkeypatch.setattr(paper, "_DRAWDOWN_TIER_1", 0.80)
        monkeypatch.setattr(paper, "_DRAWDOWN_TIER_2", 0.85)
        monkeypatch.setattr(paper, "_DRAWDOWN_TIER_3", 0.90)
        monkeypatch.setattr(paper, "_DRAWDOWN_TIER_4", 0.95)
        monkeypatch.setattr(paper, "_drawdown_snapshot", lambda: (970.0, 1000.0))
        assert paper.drawdown_scaling_factor() == 1.0


def test_no_trades_placed_when_drawdown_breached_mid_cycle(monkeypatch):
    """If balance drops below HALT mid-cycle, _auto_place_trades must stop placing.

    Calls order_executor._auto_place_trades directly — the only correct way
    to test this guard.
    """
    import order_executor as oe
    import paper

    placed = []

    def mock_place(ticker, side, qty, entry_price, **kwargs):
        placed.append(ticker)
        if len(placed) == 1:
            # After first placement, simulate balance crashing below HALT
            monkeypatch.setattr(paper, "is_paused_drawdown", lambda *_a, **_k: True)
        return {
            "ticker": ticker,
            "side": side,
            "settled": False,
            "pnl": 0,
            "id": len(placed),
            "cost": entry_price * qty,
        }

    monkeypatch.setattr(paper, "place_paper_order", mock_place)
    monkeypatch.setattr(paper, "is_paused_drawdown", lambda *_a, **_k: False)
    monkeypatch.setattr(paper, "is_daily_loss_halted", lambda _client=None: False)
    monkeypatch.setattr(paper, "is_streak_paused", lambda *_a, **_k: False)
    monkeypatch.setattr(paper, "get_open_trades", lambda: [])
    monkeypatch.setattr(paper, "drawdown_scaling_factor", lambda: 1.0)
    monkeypatch.setattr(paper, "kelly_quantity", lambda kelly, price, **kw: 1)
    monkeypatch.setattr(
        paper,
        "portfolio_kelly_fraction",
        lambda kelly, city, date, side="yes", client=None: 0.05,
    )
    monkeypatch.setattr(paper, "corr_kelly_scale", lambda opp, trades: 1.0)
    # Bypass the multi-guard validation to keep the test focused on the drawdown gate
    monkeypatch.setattr(
        oe,
        "_validate_trade_opportunity",
        lambda opp, live=False, market=None: (True, "ok"),
    )
    # Bypass internal spend/cap helpers
    monkeypatch.setattr(oe, "_daily_paper_spend", lambda: 0.0)
    monkeypatch.setattr(oe, "_daily_sameday_spend", lambda: 0.0)
    monkeypatch.setattr(oe, "_sameday_effective_cap", lambda max_pos: max_pos)

    opps = [
        {
            "ticker": "KXHIGH-A",
            "side": "yes",
            "qty": 1,
            "entry_price": 0.55,
            "net_edge": 0.15,
            "days_out": 1,
            "ci_adjusted_kelly": 0.05,
            "forecast_prob": 0.70,
            "market_prob": 0.55,
            "yes_bid": 0.52,
            "yes_ask": 0.58,
        },
        {
            "ticker": "KXHIGH-B",
            "side": "yes",
            "qty": 1,
            "entry_price": 0.55,
            "net_edge": 0.15,
            "days_out": 1,
            "ci_adjusted_kelly": 0.05,
            "forecast_prob": 0.70,
            "market_prob": 0.55,
            "yes_bid": 0.52,
            "yes_ask": 0.58,
        },
    ]

    result = oe._auto_place_trades(opps, client=None)

    assert len(placed) == 1, (
        f"Expected 1 trade placed, got {len(placed)}: {placed}. "
        "The per-trade drawdown guard must call is_paused_drawdown() before each order."
    )
    assert result == 1, (
        f"Return value must be count of placements; expected 1, got {result}"
    )
