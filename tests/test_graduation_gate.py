"""
Tests for the graduation gate in main.py (_check_graduation_gate).
"""

from __future__ import annotations

import pytest


def test_gate_raises_when_micro_live_and_insufficient_samples(monkeypatch):
    """RuntimeError raised when ENABLE_MICRO_LIVE=true and count < MIN_BRIER_SAMPLES."""

    monkeypatch.setenv("ENABLE_MICRO_LIVE", "true")

    import main
    import tracker
    import utils

    monkeypatch.setattr(tracker, "count_settled_predictions", lambda: 5)
    monkeypatch.setattr(utils, "MIN_BRIER_SAMPLES", 30)

    with pytest.raises(RuntimeError, match="Graduation gate"):
        main._check_graduation_gate()


def test_gate_passes_when_micro_live_and_sufficient_samples(monkeypatch):
    """No exception when ENABLE_MICRO_LIVE=true and count >= MIN_BRIER_SAMPLES."""
    monkeypatch.setenv("ENABLE_MICRO_LIVE", "true")

    import main
    import tracker
    import utils

    monkeypatch.setattr(tracker, "count_settled_predictions", lambda: 35)
    monkeypatch.setattr(utils, "MIN_BRIER_SAMPLES", 30)

    # Should not raise
    main._check_graduation_gate()


def test_gate_skipped_when_micro_live_false(monkeypatch):
    """No exception when ENABLE_MICRO_LIVE is not 'true' (gate is skipped entirely)."""
    monkeypatch.delenv("ENABLE_MICRO_LIVE", raising=False)

    import main
    import tracker
    import utils

    # count=0 would fail if gate were active, but it shouldn't be checked
    monkeypatch.setattr(tracker, "count_settled_predictions", lambda: 0)
    monkeypatch.setattr(utils, "MIN_BRIER_SAMPLES", 30)

    # Should not raise
    main._check_graduation_gate()


def test_gate_skipped_when_micro_live_explicitly_false(monkeypatch):
    """No exception when ENABLE_MICRO_LIVE='false'."""
    monkeypatch.setenv("ENABLE_MICRO_LIVE", "false")

    import main
    import tracker
    import utils

    monkeypatch.setattr(tracker, "count_settled_predictions", lambda: 0)
    monkeypatch.setattr(utils, "MIN_BRIER_SAMPLES", 30)

    main._check_graduation_gate()
