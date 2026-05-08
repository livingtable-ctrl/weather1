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

        with (
            patch.object(paper, "get_balance", return_value=1000.0),
            patch.object(paper, "get_peak_balance", return_value=1000.0),
        ):
            assert paper.drawdown_scaling_factor() == pytest.approx(1.0)

    def test_3pct_drawdown_full_kelly(self):
        # With default 20% halt: TIER_4=0.95, so 3% drawdown (0.97) is above TIER_4 → 1.0
        import paper

        with (
            patch.object(paper, "get_balance", return_value=970.0),
            patch.object(paper, "get_peak_balance", return_value=1000.0),
        ):
            assert paper.drawdown_scaling_factor() == pytest.approx(1.0)

    def test_7pct_drawdown_reduced(self):
        # With default 20% halt: TIER_3=0.90, TIER_4=0.95, so 7% drawdown (0.93) → 0.70
        import paper

        with (
            patch.object(paper, "get_balance", return_value=930.0),
            patch.object(paper, "get_peak_balance", return_value=1000.0),
        ):
            assert paper.drawdown_scaling_factor() == pytest.approx(0.70)

    def test_12pct_drawdown_conservative(self):
        # With default 20% halt: TIER_2=0.85, TIER_3=0.90, so 12% drawdown (0.88) → 0.30
        import paper

        with (
            patch.object(paper, "get_balance", return_value=880.0),
            patch.object(paper, "get_peak_balance", return_value=1000.0),
        ):
            assert paper.drawdown_scaling_factor() == pytest.approx(0.30)

    def test_17pct_drawdown_survival(self):
        # With default 20% halt: TIER_1=0.80, TIER_2=0.85, so 17% drawdown (0.83) → 0.10
        import paper

        with (
            patch.object(paper, "get_balance", return_value=830.0),
            patch.object(paper, "get_peak_balance", return_value=1000.0),
        ):
            assert paper.drawdown_scaling_factor() == pytest.approx(0.10)

    def test_20pct_drawdown_paused(self):
        # With default 20% halt: TIER_1=0.80, so exactly 20% drawdown (0.80) → 0.0
        import paper

        with (
            patch.object(paper, "get_balance", return_value=800.0),
            patch.object(paper, "get_peak_balance", return_value=1000.0),
        ):
            assert paper.drawdown_scaling_factor() == pytest.approx(0.0)

    def test_50pct_drawdown_paused(self):
        # Well below halt threshold → 0.0
        import paper

        with (
            patch.object(paper, "get_balance", return_value=500.0),
            patch.object(paper, "get_peak_balance", return_value=1000.0),
        ):
            assert paper.drawdown_scaling_factor() == pytest.approx(0.0)

    def test_zero_peak_balance_returns_one(self):
        import paper

        with (
            patch.object(paper, "get_balance", return_value=1000.0),
            patch.object(paper, "get_peak_balance", return_value=0.0),
        ):
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

    def test_tier_constants_are_absolute(self, monkeypatch):
        """P2-2: tiers must not shift when DRAWDOWN_HALT_PCT is non-default."""
        import importlib

        import paper

        monkeypatch.setenv("DRAWDOWN_HALT_PCT", "0.30")
        importlib.reload(paper)
        # With absolute constants, tiers stay at canonical values regardless of halt %
        assert paper._DRAWDOWN_TIER_1 == 0.80
        assert paper._DRAWDOWN_TIER_2 == 0.85
        assert paper._DRAWDOWN_TIER_3 == 0.90
        assert paper._DRAWDOWN_TIER_4 == 0.95

    def test_halt_at_20pct_drawdown(self, mock_balance_1000, monkeypatch):
        """At 20% drawdown, scaling factor should be 0.0."""
        import paper

        monkeypatch.setattr(paper, "MAX_DRAWDOWN_FRACTION", 0.20)
        monkeypatch.setattr(paper, "_DRAWDOWN_TIER_1", 0.80)
        monkeypatch.setattr(paper, "_DRAWDOWN_TIER_2", 0.85)
        monkeypatch.setattr(paper, "_DRAWDOWN_TIER_3", 0.90)
        monkeypatch.setattr(paper, "_DRAWDOWN_TIER_4", 0.95)
        monkeypatch.setattr(paper, "get_peak_balance", lambda: 1000.0)
        monkeypatch.setattr(paper, "get_balance", lambda: 790.0)  # 21% drawdown
        assert paper.drawdown_scaling_factor() == 0.0

    def test_full_sizing_near_peak(self, mock_balance_1000, monkeypatch):
        """Above TIER_4, full sizing (1.0) is returned."""
        import paper

        monkeypatch.setattr(paper, "MAX_DRAWDOWN_FRACTION", 0.20)
        monkeypatch.setattr(paper, "_DRAWDOWN_TIER_1", 0.80)
        monkeypatch.setattr(paper, "_DRAWDOWN_TIER_2", 0.85)
        monkeypatch.setattr(paper, "_DRAWDOWN_TIER_3", 0.90)
        monkeypatch.setattr(paper, "_DRAWDOWN_TIER_4", 0.95)
        monkeypatch.setattr(paper, "get_peak_balance", lambda: 1000.0)
        monkeypatch.setattr(paper, "get_balance", lambda: 970.0)  # 3% drawdown
        assert paper.drawdown_scaling_factor() == 1.0
