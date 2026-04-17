"""Tests for ab_test.py — A/B experiment framework."""

from __future__ import annotations

import pytest

import ab_test as _ab_module
from ab_test import ABTest, get_active_variant, list_all_summaries


@pytest.fixture(autouse=True)
def _patch_ab_dir(tmp_path, monkeypatch):
    """Redirect all ab_test state I/O to a temp directory for test isolation."""
    ab_dir = tmp_path / "ab_tests"
    ab_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(_ab_module, "_AB_TEST_DIR", ab_dir)
    return ab_dir


class TestABTest:
    def test_pick_variant_returns_valid_variant(self, tmp_path, monkeypatch):
        """pick_variant returns a name that is in the variants dict."""
        test = ABTest(
            name="test_pick",
            variants={"control": 0.08, "higher": 0.10, "lower": 0.06},
        )
        variant_name, variant_value = test.pick_variant()
        assert variant_name in test.variants
        assert variant_value == test.variants[variant_name]

    def test_pick_variant_round_robins_to_least_traded(self, tmp_path, monkeypatch):
        """pick_variant favours the variant with fewest trades."""
        test = ABTest(
            name="test_rr",
            variants={"control": 0.08, "higher": 0.10, "lower": 0.06},
        )
        # Record several outcomes for "control" to inflate its trade count
        for _ in range(5):
            test.record_outcome("control", won=True, edge_realized=0.05)

        # "control" has 5 trades; "higher" and "lower" each have 0 — should not pick control
        variant_name, _ = test.pick_variant()
        assert variant_name != "control", (
            f"Expected a non-control variant (fewest trades), got {variant_name!r}"
        )

    def test_record_outcome_increments_trades_and_wins(self, tmp_path, monkeypatch):
        """record_outcome increments trades count; wins only on won=True."""
        test = ABTest(
            name="test_record",
            variants={"control": 0.08, "higher": 0.10},
        )
        # Record a win and a loss for "control"
        test.record_outcome("control", won=True, edge_realized=0.10)
        test.record_outcome("control", won=False, edge_realized=0.02)

        summary = test.summary()
        assert summary["control"]["trades"] == 2
        # 1 win out of 2 trades → 0.5 win rate
        assert summary["control"]["win_rate"] == pytest.approx(0.5, abs=1e-4)
        # "higher" untouched
        assert summary["higher"]["trades"] == 0

    def test_auto_disable_low_performer(self, tmp_path, monkeypatch):
        """Variant with win_rate 20pp below best is auto-disabled after max_trades."""
        test = ABTest(
            name="test_disable",
            variants={"control": 0.08, "loser": 0.05},
            max_trades_per_variant=5,
            disable_threshold=0.20,
        )
        # Give "control" a perfect record (5 wins)
        for _ in range(5):
            test.record_outcome("control", won=True, edge_realized=0.08)

        # Give "loser" a terrible record (0 wins out of 5)
        for _ in range(5):
            test.record_outcome("loser", won=False, edge_realized=0.0)

        summary = test.summary()
        # loser: 0% win rate vs control: 100% — gap is 100pp > 20pp threshold
        assert summary["loser"]["disabled"] is True, (
            "Expected 'loser' variant to be auto-disabled after max_trades with poor win rate"
        )
        # control should remain enabled
        assert summary["control"]["disabled"] is False

    def test_summary_has_required_keys(self, tmp_path, monkeypatch):
        """summary() returns win_rate, avg_edge, trades, disabled per variant."""
        test = ABTest(
            name="test_summary",
            variants={"control": 0.08, "higher": 0.10, "lower": 0.06},
        )
        test.record_outcome("control", won=True, edge_realized=0.10)

        summary = test.summary()
        required_keys = {"win_rate", "avg_edge", "trades", "disabled"}
        for variant in ("control", "higher", "lower"):
            assert variant in summary, f"Missing variant {variant!r} in summary"
            missing = required_keys - set(summary[variant].keys())
            assert not missing, f"Variant {variant!r} missing keys: {missing}"

    def test_get_active_variant_fallback(self, tmp_path, monkeypatch):
        """get_active_variant returns ('control', None) for unknown test name."""
        # No state file exists for this name — must fall back gracefully
        variant_name, value = get_active_variant("nonexistent_test_xyz")
        assert variant_name == "control"
        assert value is None

    def test_list_all_summaries_returns_dict(self, tmp_path, monkeypatch):
        """list_all_summaries returns a dict (empty if no tests on disk)."""
        # No tests written yet — should be an empty dict, not an error
        result = list_all_summaries()
        assert isinstance(result, dict)

    def test_list_all_summaries_includes_saved_test(self, tmp_path, monkeypatch):
        """list_all_summaries includes tests that have been persisted to disk."""
        test = ABTest(
            name="visible_test",
            variants={"control": 0.08},
        )
        test.record_outcome("control", won=True, edge_realized=0.05)

        result = list_all_summaries()
        assert isinstance(result, dict)
        assert "visible_test" in result

    def test_get_active_variant_returns_least_traded(self, tmp_path, monkeypatch):
        """get_active_variant picks the least-traded active variant from disk state."""
        # Create a test and record trades so state is on disk
        test = ABTest(
            name="disk_test",
            variants={"control": 0.08, "higher": 0.10},
        )
        # Give "control" more trades so "higher" should be preferred
        for _ in range(3):
            test.record_outcome("control", won=True, edge_realized=0.05)

        variant_name, _ = get_active_variant("disk_test")
        # "higher" has 0 trades vs "control" with 3 — should pick "higher"
        assert variant_name == "higher"

    def test_record_outcome_unknown_variant_is_noop(self, tmp_path, monkeypatch):
        """record_outcome with an unknown variant name does nothing (no crash)."""
        test = ABTest(
            name="test_noop",
            variants={"control": 0.08},
        )
        # Should not raise
        test.record_outcome("nonexistent_variant", won=True, edge_realized=0.5)
        summary = test.summary()
        # State must be unchanged
        assert summary["control"]["trades"] == 0

    def test_pick_variant_all_exhausted_falls_back_to_control(
        self, tmp_path, monkeypatch
    ):
        """When all variants are exhausted, pick_variant falls back to 'control'."""
        test = ABTest(
            name="test_exhausted",
            variants={"control": 0.08, "higher": 0.10},
            max_trades_per_variant=2,
        )
        # Exhaust all variants
        for _ in range(2):
            test.record_outcome("control", won=True)
            test.record_outcome("higher", won=True)

        variant_name, variant_value = test.pick_variant()
        assert variant_name == "control"
        assert variant_value == 0.08
