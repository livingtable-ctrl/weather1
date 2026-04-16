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

    def test_10pct_drawdown_half_kelly(self):
        import paper

        with (
            patch.object(paper, "get_balance", return_value=900.0),
            patch.object(paper, "get_peak_balance", return_value=1000.0),
        ):
            assert paper.drawdown_scaling_factor() == pytest.approx(0.50)

    def test_15pct_drawdown_half_kelly(self):
        import paper

        with (
            patch.object(paper, "get_balance", return_value=850.0),
            patch.object(paper, "get_peak_balance", return_value=1000.0),
        ):
            assert paper.drawdown_scaling_factor() == pytest.approx(0.50)

    def test_20pct_drawdown_survival_mode(self):
        import paper

        with (
            patch.object(paper, "get_balance", return_value=800.0),
            patch.object(paper, "get_peak_balance", return_value=1000.0),
        ):
            assert paper.drawdown_scaling_factor() == pytest.approx(0.20)

    def test_35pct_drawdown_survival_mode(self):
        import paper

        with (
            patch.object(paper, "get_balance", return_value=650.0),
            patch.object(paper, "get_peak_balance", return_value=1000.0),
        ):
            assert paper.drawdown_scaling_factor() == pytest.approx(0.20)

    def test_40pct_drawdown_paused(self):
        import paper

        with (
            patch.object(paper, "get_balance", return_value=600.0),
            patch.object(paper, "get_peak_balance", return_value=1000.0),
        ):
            assert paper.drawdown_scaling_factor() == pytest.approx(0.0)

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
