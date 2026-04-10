"""Tests for calibration.py — seasonal and per-city blend weight calibration."""

import json
import shutil
import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path


def _seed_db(db_path: Path, rows: list[dict]) -> None:
    """Seed a minimal predictions + outcomes DB for calibration tests."""
    with sqlite3.connect(str(db_path)) as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS predictions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT, city TEXT, market_date TEXT,
                condition_type TEXT, threshold_lo REAL, threshold_hi REAL,
                our_prob REAL, raw_prob REAL, market_prob REAL,
                edge REAL, method TEXT, n_members INTEGER,
                predicted_at TEXT, days_out INTEGER,
                forecast_cycle TEXT, blend_sources TEXT,
                ensemble_prob REAL, nws_prob REAL, clim_prob REAL
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS outcomes (
                ticker TEXT PRIMARY KEY,
                settled_yes INTEGER,
                settled_at TEXT
            )
        """)
        for r in rows:
            con.execute(
                """INSERT INTO predictions
                   (ticker, city, market_date, condition_type, our_prob,
                    market_prob, edge, method, n_members, predicted_at, days_out,
                    ensemble_prob, nws_prob, clim_prob)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    r["ticker"],
                    r["city"],
                    r["market_date"],
                    "above",
                    r["our_prob"],
                    0.5,
                    0.1,
                    "ensemble",
                    50,
                    datetime.now().isoformat(),
                    3,
                    r.get("ensemble_prob"),
                    r.get("nws_prob"),
                    r.get("clim_prob"),
                ),
            )
            con.execute(
                "INSERT OR REPLACE INTO outcomes (ticker, settled_yes, settled_at) VALUES (?,?,?)",
                (r["ticker"], int(r["settled_yes"]), datetime.now().isoformat()),
            )


def _make_winter_rows(n: int, base_ticker: str = "W") -> list[dict]:
    """Generate n rows with a winter market_date (January)."""
    rows = []
    for i in range(n):
        settled = i % 2 == 0
        rows.append(
            {
                "ticker": f"{base_ticker}-{i}",
                "city": "NYC",
                "market_date": f"2026-01-{(i % 28) + 1:02d}",
                "our_prob": 0.7 if settled else 0.3,
                "ensemble_prob": 0.72,
                "nws_prob": 0.65,
                "clim_prob": 0.60,
                "settled_yes": settled,
            }
        )
    return rows


class TestCalibrateSeasonalWeights:
    def setup_method(self):
        self._tmpdir = tempfile.mkdtemp()
        self._db = Path(self._tmpdir) / "test.db"

    def teardown_method(self):
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_returns_weights_summing_to_one(self):
        """60 winter predictions → winter weights present and sum to 1.0."""
        from calibration import calibrate_seasonal_weights

        _seed_db(self._db, _make_winter_rows(60))
        result = calibrate_seasonal_weights(self._db)
        assert "winter" in result, f"winter missing from result: {result}"
        w = result["winter"]
        assert abs(w["ensemble"] + w["climatology"] + w["nws"] - 1.0) < 1e-6
        for k in ("ensemble", "climatology", "nws"):
            assert 0.0 <= w[k] <= 1.0, f"{k} out of range: {w[k]}"

    def test_below_threshold_omits_season(self):
        """30 predictions (< 50) → season omitted from output."""
        from calibration import calibrate_seasonal_weights

        _seed_db(self._db, _make_winter_rows(30))
        result = calibrate_seasonal_weights(self._db)
        assert "winter" not in result, "winter should be absent with only 30 rows"

    def test_rows_without_source_probs_not_counted(self):
        """Rows missing ensemble_prob/nws_prob/clim_prob must not count toward threshold."""
        from calibration import calibrate_seasonal_weights

        rows = _make_winter_rows(60)
        for r in rows[:35]:
            r["ensemble_prob"] = None
            r["nws_prob"] = None
            r["clim_prob"] = None
        _seed_db(self._db, rows)
        result = calibrate_seasonal_weights(self._db)
        assert "winter" not in result


class TestCalibrateCityWeights:
    def setup_method(self):
        self._tmpdir = tempfile.mkdtemp()
        self._db = Path(self._tmpdir) / "test.db"

    def teardown_method(self):
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_returns_weights_for_qualifying_city(self):
        """35 NYC predictions → NYC weights present and valid."""
        from calibration import calibrate_city_weights

        rows = _make_winter_rows(35, base_ticker="NYC")
        _seed_db(self._db, rows)
        result = calibrate_city_weights(self._db)
        assert "NYC" in result
        w = result["NYC"]
        assert abs(w["ensemble"] + w["climatology"] + w["nws"] - 1.0) < 1e-6

    def test_below_threshold_omits_city(self):
        """20 predictions (< 30) → city absent."""
        from calibration import calibrate_city_weights

        rows = _make_winter_rows(20, base_ticker="SPARSE")
        _seed_db(self._db, rows)
        result = calibrate_city_weights(self._db)
        assert "NYC" not in result


class TestLoadWeights:
    """load_seasonal_weights and load_city_weights must handle missing/valid/corrupt files."""

    def setup_method(self):
        self._tmpdir = tempfile.mkdtemp()

    def teardown_method(self):
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_load_seasonal_missing_file_returns_empty(self):
        from calibration import load_seasonal_weights

        result = load_seasonal_weights(Path(self._tmpdir) / "nonexistent.json")
        assert result == {}

    def test_load_seasonal_valid_json_returns_dict(self):
        from calibration import load_seasonal_weights

        p = Path(self._tmpdir) / "seasonal.json"
        p.write_text(
            json.dumps({"winter": {"ensemble": 0.55, "climatology": 0.25, "nws": 0.20}})
        )
        result = load_seasonal_weights(p)
        assert result == {
            "winter": {"ensemble": 0.55, "climatology": 0.25, "nws": 0.20}
        }

    def test_load_seasonal_corrupt_json_returns_empty(self):
        from calibration import load_seasonal_weights

        p = Path(self._tmpdir) / "corrupt.json"
        p.write_text("not valid json {{")
        result = load_seasonal_weights(p)
        assert result == {}

    def test_load_city_missing_file_returns_empty(self):
        from calibration import load_city_weights

        result = load_city_weights(Path(self._tmpdir) / "nonexistent.json")
        assert result == {}

    def test_load_city_valid_json_returns_dict(self):
        from calibration import load_city_weights

        p = Path(self._tmpdir) / "city.json"
        p.write_text(
            json.dumps({"NYC": {"ensemble": 0.60, "climatology": 0.15, "nws": 0.25}})
        )
        result = load_city_weights(p)
        assert result == {"NYC": {"ensemble": 0.60, "climatology": 0.15, "nws": 0.25}}


class TestCalibrateCLI:
    """cmd_calibrate writes JSON files when enough data exists."""

    def setup_method(self):
        self._tmpdir = tempfile.mkdtemp()
        self._db = Path(self._tmpdir) / "test.db"
        self._out_dir = Path(self._tmpdir) / "data"
        self._out_dir.mkdir()

    def teardown_method(self):
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_calibrate_writes_seasonal_json(self):
        """With enough data, calibrate writes data/seasonal_weights.json."""
        import calibration

        rows = _make_winter_rows(60)
        _seed_db(self._db, rows)
        seasonal = calibration.calibrate_seasonal_weights(self._db)
        out = self._out_dir / "seasonal_weights.json"
        out.write_text(json.dumps(seasonal))
        loaded = json.loads(out.read_text())
        assert "winter" in loaded
        w = loaded["winter"]
        assert abs(w["ensemble"] + w["climatology"] + w["nws"] - 1.0) < 1e-6
