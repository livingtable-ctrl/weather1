"""Tests for param_sweep.load_swept_min_edge() — A5 implementation."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


def _write_sweep(tmp_dir: str, paper_min_edge_results: list[dict]) -> Path:
    p = Path(tmp_dir) / "param_sweep_results.json"
    p.write_text(json.dumps({"PAPER_MIN_EDGE": paper_min_edge_results}))
    return p


class TestLoadSweptMinEdge(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def _load(self, min_trades: int = 10):
        import config
        from param_sweep import load_swept_min_edge

        with patch.object(config, "_DATA_DIR", Path(self.tmp)):
            return load_swept_min_edge(min_trades=min_trades)

    def test_returns_none_when_file_missing(self):
        self.assertIsNone(self._load())

    def test_returns_none_when_no_results_qualify(self):
        _write_sweep(
            self.tmp,
            [
                {"value": 0.07, "trades": 3, "win_rate": 0.80},
                {"value": 0.05, "trades": 5, "win_rate": 0.75},
            ],
        )
        self.assertIsNone(self._load(min_trades=10))

    def test_returns_best_win_rate_among_qualifying(self):
        _write_sweep(
            self.tmp,
            [
                {"value": 0.05, "trades": 15, "win_rate": 0.60},
                {"value": 0.07, "trades": 20, "win_rate": 0.72},  # best
                {"value": 0.10, "trades": 12, "win_rate": 0.68},
            ],
        )
        self.assertAlmostEqual(self._load(min_trades=10), 0.07)

    def test_out_of_range_value_returns_none(self):
        _write_sweep(
            self.tmp,
            [
                {"value": 0.50, "trades": 50, "win_rate": 0.99},  # out of [0.03, 0.15]
            ],
        )
        self.assertIsNone(self._load(min_trades=10))

    def test_min_trades_floor_filters_low_sample_entries(self):
        _write_sweep(
            self.tmp,
            [
                {"value": 0.06, "trades": 8, "win_rate": 0.90},  # excluded (< 10)
                {"value": 0.09, "trades": 10, "win_rate": 0.65},  # qualifies
            ],
        )
        self.assertAlmostEqual(self._load(min_trades=10), 0.09)

    def test_none_win_rate_entries_skipped(self):
        _write_sweep(
            self.tmp,
            [
                {"value": 0.05, "trades": 0, "win_rate": None},
                {"value": 0.07, "trades": 15, "win_rate": 0.70},
            ],
        )
        self.assertAlmostEqual(self._load(min_trades=10), 0.07)

    def test_returns_none_for_empty_results(self):
        _write_sweep(self.tmp, [])
        self.assertIsNone(self._load())

    def test_custom_min_trades_respected(self):
        _write_sweep(
            self.tmp,
            [
                {"value": 0.08, "trades": 5, "win_rate": 0.75},
            ],
        )
        # With min_trades=5 it qualifies; with min_trades=10 it doesn't
        self.assertAlmostEqual(self._load(min_trades=5), 0.08)
        self.assertIsNone(self._load(min_trades=10))


if __name__ == "__main__":
    unittest.main(verbosity=2)
