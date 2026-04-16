"""Tests for confidence-tiered edge thresholds."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestGetMinEdgeForConfidence:
    def test_high_confidence_low_spread(self):
        from utils import get_min_edge_for_confidence

        assert get_min_edge_for_confidence(spread=0.04, is_live=False) == pytest.approx(
            0.05
        )

    def test_moderate_confidence_medium_spread(self):
        from utils import get_min_edge_for_confidence

        assert get_min_edge_for_confidence(spread=0.10, is_live=False) == pytest.approx(
            0.07
        )

    def test_low_confidence_wide_spread(self):
        from utils import get_min_edge_for_confidence

        assert get_min_edge_for_confidence(spread=0.20, is_live=False) == pytest.approx(
            0.10
        )

    def test_live_thresholds_higher(self):
        from utils import get_min_edge_for_confidence

        assert get_min_edge_for_confidence(
            0.04, is_live=True
        ) > get_min_edge_for_confidence(0.04, is_live=False)
        assert get_min_edge_for_confidence(
            0.10, is_live=True
        ) > get_min_edge_for_confidence(0.10, is_live=False)
        assert get_min_edge_for_confidence(
            0.20, is_live=True
        ) > get_min_edge_for_confidence(0.20, is_live=False)

    def test_zero_spread_is_high(self):
        from utils import get_min_edge_for_confidence

        assert get_min_edge_for_confidence(0.0, is_live=False) == pytest.approx(0.05)

    def test_boundary_005_is_moderate(self):
        from utils import get_min_edge_for_confidence

        assert get_min_edge_for_confidence(0.05, is_live=False) == pytest.approx(0.07)

    def test_classify_confidence_returns_string(self):
        from utils import classify_confidence_tier

        assert classify_confidence_tier(0.04) == "HIGH"
        assert classify_confidence_tier(0.10) == "MODERATE"
        assert classify_confidence_tier(0.20) == "LOW"
        assert classify_confidence_tier(0.05) == "MODERATE"  # boundary → MODERATE
