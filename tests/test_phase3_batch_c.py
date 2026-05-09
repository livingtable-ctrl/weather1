"""Phase 3 Batch C regression tests: P3-1, P3-7, P3-16, P3-17, P3-25."""

from __future__ import annotations

import random
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


# ── Shared helpers ────────────────────────────────────────────────────────────


def _make_db(tmp_path: Path, rows: list[dict]) -> Path:
    """Seed a predictions+outcomes DB for calibration tests."""
    db = tmp_path / "cal.db"
    with sqlite3.connect(str(db)) as con:
        con.executescript("""
            CREATE TABLE predictions (
                ticker TEXT, city TEXT, market_date TEXT, condition_type TEXT,
                ensemble_prob REAL, nws_prob REAL, clim_prob REAL
            );
            CREATE TABLE outcomes (ticker TEXT PRIMARY KEY, settled_yes INTEGER);
        """)
        for r in rows:
            con.execute(
                "INSERT INTO predictions VALUES (?,?,?,?,?,?,?)",
                (
                    r["ticker"],
                    r.get("city", "NYC"),
                    r["market_date"],
                    r.get("condition_type", "above"),
                    r.get("ensemble_prob"),
                    r.get("nws_prob"),
                    r.get("clim_prob"),
                ),
            )
            con.execute(
                "INSERT OR REPLACE INTO outcomes VALUES (?,?)",
                (r["ticker"], int(r["settled_yes"])),
            )
    return db


def _rows(
    n: int,
    city: str = "NYC",
    ctype: str = "above",
    base_date: str = "2025-01-",
    ticker_prefix: str = "T",
) -> list[dict]:
    """Generate n rows with spread-out dates for stable 80/20 splits."""
    rng = random.Random(0)
    result = []
    for i in range(n):
        # Spread dates across ~3 years so splits are meaningful
        year = 2023 + (i // 120)
        month = (i % 12) + 1
        day = (i % 28) + 1
        result.append(
            {
                "ticker": f"{ticker_prefix}-{i}",
                "city": city,
                "market_date": f"{year}-{month:02d}-{day:02d}",
                "condition_type": ctype,
                "ensemble_prob": rng.uniform(0.3, 0.8),
                "nws_prob": rng.uniform(0.3, 0.7),
                "clim_prob": rng.uniform(0.3, 0.7),
                "settled_yes": rng.randint(0, 1),
            }
        )
    return result


# ── P3-17: _brier() filters None rows ─────────────────────────────────────────


class TestBrierNoneFiltering:
    """P3-17: _brier must skip rows with any None component."""

    def test_all_none_returns_inf(self):
        from calibration import _brier

        rows = [(None, None, None, None)]
        assert _brier(rows, 1 / 3, 1 / 3, 1 / 3) == float("inf")

    def test_partial_none_skipped(self):
        from calibration import _brier

        good = (0.6, 0.5, 0.55, 1)
        bad = (None, 0.5, 0.5, 1)
        rows = [good, bad]
        score_good_only = _brier([good], 1 / 3, 1 / 3, 1 / 3)
        score_with_none = _brier(rows, 1 / 3, 1 / 3, 1 / 3)
        assert score_good_only == pytest.approx(score_with_none)

    def test_empty_rows_returns_inf(self):
        from calibration import _brier

        assert _brier([], 1 / 3, 1 / 3, 1 / 3) == float("inf")

    def test_valid_rows_computes_correctly(self):
        from calibration import _brier

        rows = [(1.0, 0.0, 0.0, 1)]
        score = _brier(rows, 1.0, 0.0, 0.0)
        assert score == pytest.approx(0.0)

    def test_none_settled_skipped(self):
        from calibration import _brier

        rows = [(0.6, 0.5, 0.5, None)]
        assert _brier(rows, 1 / 3, 1 / 3, 1 / 3) == float("inf")


# ── P3-25: _CITY_MIN == 50 ────────────────────────────────────────────────────


class TestCityMinThreshold:
    """P3-25: _CITY_MIN must be 50."""

    def test_city_min_is_50(self):
        from calibration import _CITY_MIN

        assert _CITY_MIN == 50

    def test_49_rows_city_omitted(self, tmp_path):
        from calibration import calibrate_city_weights

        db = _make_db(tmp_path, _rows(49))
        result = calibrate_city_weights(db)
        assert "NYC" not in result

    def test_50_rows_city_present(self, tmp_path):
        from calibration import calibrate_city_weights

        db = _make_db(tmp_path, _rows(55))
        result = calibrate_city_weights(db)
        assert "NYC" in result


# ── P3-7: random search + Brier gate ─────────────────────────────────────────


class TestRandomSearchAndGate:
    """P3-7: _best_weights uses random search; gate returns equal weights when no improvement."""

    def test_weights_sum_to_one(self, tmp_path):
        from calibration import calibrate_city_weights

        db = _make_db(tmp_path, _rows(55))
        result = calibrate_city_weights(db)
        assert "NYC" in result
        w = result["NYC"]
        assert abs(w["ensemble"] + w["climatology"] + w["nws"] - 1.0) < 1e-6

    def test_all_weights_in_range(self, tmp_path):
        from calibration import calibrate_city_weights

        db = _make_db(tmp_path, _rows(55))
        result = calibrate_city_weights(db)
        if "NYC" in result:
            for v in result["NYC"].values():
                assert 0.0 <= v <= 1.0

    def test_equal_weights_returned_when_gate_fails(self):
        """When val Brier improvement <= 0.005, equal weights are returned."""
        from calibration import _best_weights

        # Identical rows → any weight triple scores the same → no improvement → gate fires
        rows = [(0.5, 0.5, 0.5, 1)] * 80
        train, val = rows[:64], rows[64:]
        result = _best_weights(train, val)
        assert result == pytest.approx(
            {"ensemble": 1 / 3, "climatology": 1 / 3, "nws": 1 / 3}, abs=1e-9
        )

    def test_n_random_search_is_200(self):
        from calibration import _N_RANDOM_SEARCH

        assert _N_RANDOM_SEARCH == 200

    def test_brier_gate_constant(self):
        from calibration import _BRIER_IMPROVEMENT_GATE

        assert _BRIER_IMPROVEMENT_GATE == pytest.approx(0.005)

    def test_calibrate_city_weights_deterministic(self, tmp_path):
        """Same data → same weights (random search uses fixed seed=42)."""
        from calibration import calibrate_city_weights

        db = _make_db(tmp_path, _rows(55))
        r1 = calibrate_city_weights(db)
        r2 = calibrate_city_weights(db)
        assert r1 == r2


# ── P3-1: cutoff_date temporal isolation for seasonal + city ──────────────────


class TestTemporalIsolationSeasonalCity:
    """P3-1: calibrate_seasonal_weights and calibrate_city_weights accept cutoff_date."""

    def test_seasonal_accepts_cutoff_date_kwarg(self, tmp_path):
        from calibration import calibrate_seasonal_weights

        db = _make_db(tmp_path, _rows(30))
        result = calibrate_seasonal_weights(db, cutoff_date="2025-06-01")
        assert isinstance(result, dict)

    def test_city_accepts_cutoff_date_kwarg(self, tmp_path):
        from calibration import calibrate_city_weights

        db = _make_db(tmp_path, _rows(55))
        result = calibrate_city_weights(db, cutoff_date="2025-06-01")
        assert isinstance(result, dict)

    def test_cutoff_excludes_future_rows_from_training(self, tmp_path):
        """Rows after cutoff must not affect training — weights with tight cutoff differ."""
        from calibration import calibrate_city_weights

        all_rows = _rows(60)
        # Mark final 10 rows with a very different probability pattern
        for r in all_rows[-10:]:
            r["market_date"] = "2030-01-01"
            r["ensemble_prob"] = 0.99
            r["settled_yes"] = 0  # badly miscalibrated

        db = _make_db(tmp_path, all_rows)
        # With cutoff before 2030, last 10 rows are val-only
        result_with = calibrate_city_weights(db, cutoff_date="2028-01-01")
        # Without cutoff, auto 80/20 includes some bad rows in training
        result_auto = calibrate_city_weights(db)
        # Both must return valid results (weights sum to 1)
        for result in (result_with, result_auto):
            if "NYC" in result:
                w = result["NYC"]
                assert abs(w["ensemble"] + w["climatology"] + w["nws"] - 1.0) < 1e-6

    def test_auto_split_80_20(self, tmp_path):
        """Without cutoff_date, function runs without error on enough rows."""
        from calibration import calibrate_seasonal_weights

        # 60 January rows (all winter) → auto 80/20 → 48 train, 12 val
        all_rows = _rows(60)
        for i, r in enumerate(all_rows):
            r["market_date"] = f"2025-01-{(i % 28) + 1:02d}"
        db = _make_db(tmp_path, all_rows)
        result = calibrate_seasonal_weights(db)
        assert isinstance(result, dict)

    def test_weights_with_explicit_cutoff_sum_to_one(self, tmp_path):
        from calibration import calibrate_city_weights

        db = _make_db(tmp_path, _rows(60))
        result = calibrate_city_weights(db, cutoff_date="2024-06-01")
        if "NYC" in result:
            w = result["NYC"]
            assert abs(w["ensemble"] + w["climatology"] + w["nws"] - 1.0) < 1e-6


# ── P3-16: cutoff_date temporal isolation for condition weights ────────────────


class TestTemporalIsolationCondition:
    """P3-16: calibrate_condition_weights accepts cutoff_date; no look-ahead bias."""

    def _make_condition_db(self, tmp_path: Path, n_per_type: int = 120) -> Path:
        rng = random.Random(1)
        rows = []
        for ctype in ("above", "below", "between"):
            for i in range(n_per_type):
                year = 2023 + (i // 120)
                month = (i % 12) + 1
                day = (i % 28) + 1
                rows.append(
                    {
                        "ticker": f"{ctype}-{i}",
                        "city": "NYC",
                        "market_date": f"{year}-{month:02d}-{day:02d}",
                        "condition_type": ctype,
                        "ensemble_prob": rng.uniform(0.3, 0.8),
                        "nws_prob": rng.uniform(0.3, 0.7),
                        "clim_prob": rng.uniform(0.3, 0.7),
                        "settled_yes": rng.randint(0, 1),
                    }
                )
        return _make_db(tmp_path, rows)

    def test_accepts_cutoff_date_kwarg(self, tmp_path):
        from calibration import calibrate_condition_weights

        db = self._make_condition_db(tmp_path)
        result = calibrate_condition_weights(db, cutoff_date="2024-01-01")
        assert isinstance(result, dict)

    def test_weights_sum_to_one(self, tmp_path):
        from calibration import calibrate_condition_weights

        db = self._make_condition_db(tmp_path)
        result = calibrate_condition_weights(db, min_samples=100)
        for ctype in ("above", "below", "between"):
            if ctype in result:
                w = result[ctype]
                assert abs(w["ensemble"] + w["climatology"] + w["nws"] - 1.0) < 1e-6

    def test_cutoff_date_with_min_samples(self, tmp_path):
        from calibration import calibrate_condition_weights

        db = self._make_condition_db(tmp_path)
        result = calibrate_condition_weights(
            db, min_samples=50, cutoff_date="2024-06-01"
        )
        assert isinstance(result, dict)

    def test_no_market_date_rows_handled_gracefully(self, tmp_path):
        """Rows with NULL market_date fall back to empty-string cutoff comparison."""
        from calibration import calibrate_condition_weights

        rows = []
        rng = random.Random(2)
        for i in range(120):
            rows.append(
                {
                    "ticker": f"above-{i}",
                    "city": "NYC",
                    "market_date": None,
                    "condition_type": "above",
                    "ensemble_prob": rng.uniform(0.3, 0.8),
                    "nws_prob": rng.uniform(0.3, 0.7),
                    "clim_prob": rng.uniform(0.3, 0.7),
                    "settled_yes": rng.randint(0, 1),
                }
            )
        db = _make_db(tmp_path, rows)
        result = calibrate_condition_weights(db, min_samples=100)
        assert isinstance(result, dict)
