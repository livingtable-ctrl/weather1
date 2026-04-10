"""Regression test: Brier score must not degrade more than 1% after refactors."""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from pathlib import Path

import pytest

BASELINE_FILE = Path(__file__).parent / "fixtures" / "regression_baseline.json"
TOLERANCE = 0.01


def test_brier_score_not_degraded():
    baseline = json.loads(BASELINE_FILE.read_text())
    baseline_bs = baseline.get("brier_score")
    if baseline_bs is None:
        pytest.skip("No baseline Brier score yet")
    from tracker import brier_score

    current = brier_score()
    assert current is not None
    assert current <= baseline_bs + TOLERANCE, (
        f"Brier score degraded: {current:.4f} vs baseline {baseline_bs:.4f}"
    )


def test_roc_auc_not_degraded():
    baseline = json.loads(BASELINE_FILE.read_text())
    baseline_roc = baseline.get("roc_auc")
    if baseline_roc is None:
        pytest.skip("No baseline ROC-AUC yet")
    from tracker import get_roc_auc

    current = get_roc_auc()
    assert current is not None
    assert current >= baseline_roc - TOLERANCE
