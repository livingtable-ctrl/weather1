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

    def test_5pct_drawdown_full_kelly(self):
        import paper

        with (
            patch.object(paper, "get_balance", return_value=950.0),
            patch.object(paper, "get_peak_balance", return_value=1000.0),
        ):
            assert paper.drawdown_scaling_factor() == pytest.approx(1.0)

    def test_10pct_drawdown_full_kelly(self):
        # With default 50% halt: TIER_4=0.65, so 10% drawdown (0.90) is above TIER_4 → 1.0
        import paper

        with (
            patch.object(paper, "get_balance", return_value=900.0),
            patch.object(paper, "get_peak_balance", return_value=1000.0),
        ):
            assert paper.drawdown_scaling_factor() == pytest.approx(1.0)

    def test_15pct_drawdown_full_kelly(self):
        # With default 50% halt: TIER_4=0.65, so 15% drawdown (0.85) is above TIER_4 → 1.0
        import paper

        with (
            patch.object(paper, "get_balance", return_value=850.0),
            patch.object(paper, "get_peak_balance", return_value=1000.0),
        ):
            assert paper.drawdown_scaling_factor() == pytest.approx(1.0)

    def test_20pct_drawdown_full_kelly(self):
        # With default 50% halt: TIER_4=0.65, so 20% drawdown (0.80) is above TIER_4 → 1.0
        import paper

        with (
            patch.object(paper, "get_balance", return_value=800.0),
            patch.object(paper, "get_peak_balance", return_value=1000.0),
        ):
            assert paper.drawdown_scaling_factor() == pytest.approx(1.0)

    def test_35pct_drawdown_reduced(self):
        # With default 50% halt: TIER_4=0.65, so 35% drawdown (0.65) is <= TIER_4 → 0.70
        import paper

        with (
            patch.object(paper, "get_balance", return_value=650.0),
            patch.object(paper, "get_peak_balance", return_value=1000.0),
        ):
            assert paper.drawdown_scaling_factor() == pytest.approx(0.70)

    def test_40pct_drawdown_conservative(self):
        # With default 50% halt: TIER_3=0.60, so 40% drawdown (0.60) is <= TIER_3 → 0.30
        import paper

        with (
            patch.object(paper, "get_balance", return_value=600.0),
            patch.object(paper, "get_peak_balance", return_value=1000.0),
        ):
            assert paper.drawdown_scaling_factor() == pytest.approx(0.30)

    def test_50pct_drawdown_paused(self):
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
    """Tiers must be relative to halt threshold, not hardcoded absolutes."""

    def test_tiers_scale_with_halt_threshold(self, monkeypatch):
        """With 20% halt, tier thresholds should shift proportionally."""
        import importlib

        import paper

        monkeypatch.setenv("DRAWDOWN_HALT_PCT", "0.20")
        importlib.reload(paper)
        # Halt is at 80% of peak. Tier 2 (conservative) must be above halt (>80%)
        assert paper._DRAWDOWN_TIER_2 > paper._DRAWDOWN_TIER_1
        assert paper._DRAWDOWN_TIER_3 > paper._DRAWDOWN_TIER_2
        assert paper._DRAWDOWN_TIER_4 > paper._DRAWDOWN_TIER_3

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
