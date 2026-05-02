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
        """10 predictions (< 20) → season omitted from output."""
        from calibration import calibrate_seasonal_weights

        _seed_db(self._db, _make_winter_rows(10))
        result = calibrate_seasonal_weights(self._db)
        assert "winter" not in result, "winter should be absent with only 10 rows"

    def test_rows_without_source_probs_not_counted(self):
        """Rows missing ensemble_prob/nws_prob/clim_prob must not count toward threshold."""
        from calibration import calibrate_seasonal_weights

        rows = _make_winter_rows(30)
        for r in rows[:15]:
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
        """16 NYC predictions (>= 15) → NYC weights present and valid."""
        from calibration import calibrate_city_weights

        rows = _make_winter_rows(16, base_ticker="NYC")
        _seed_db(self._db, rows)
        result = calibrate_city_weights(self._db)
        assert "NYC" in result
        w = result["NYC"]
        assert abs(w["ensemble"] + w["climatology"] + w["nws"] - 1.0) < 1e-6

    def test_below_threshold_omits_city(self):
        """10 predictions (< 15) → city absent."""
        from calibration import calibrate_city_weights

        rows = _make_winter_rows(10, base_ticker="SPARSE")
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
    """cmd_calibrate writes JSON files to data/ when enough data exists."""

    def setup_method(self):
        self._tmpdir = tempfile.mkdtemp()
        self._db = Path(self._tmpdir) / "test.db"
        self._data_dir = Path(self._tmpdir) / "data"
        self._data_dir.mkdir()

    def teardown_method(self):
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_calibrate_writes_seasonal_json(self, monkeypatch):
        """cmd_calibrate() writes data/seasonal_weights.json with calibrated weights."""
        import main
        import tracker

        rows = _make_winter_rows(60)
        _seed_db(self._db, rows)

        # Redirect DB_PATH to the test DB
        monkeypatch.setattr(tracker, "DB_PATH", self._db)

        # Redirect the output data directory
        monkeypatch.setattr(main, "_CALIBRATE_DATA_DIR", self._data_dir)

        main.cmd_calibrate()

        seasonal_path = self._data_dir / "seasonal_weights.json"
        assert seasonal_path.exists(), "seasonal_weights.json was not written"
        loaded = json.loads(seasonal_path.read_text())
        assert "winter" in loaded
        w = loaded["winter"]
        assert abs(w["ensemble"] + w["climatology"] + w["nws"] - 1.0) < 1e-6


# ── Phase 5.1: brier_by_condition in backtest ─────────────────────────────────

def test_run_backtest_reports_per_condition_type(monkeypatch):
    """run_backtest result includes brier_by_condition dict."""
    from datetime import date
    from unittest.mock import MagicMock

    import backtest

    markets = [
        {"ticker": "KXHIGHNY-26MAY01-T70", "result": "yes", "title": "NYC high > 70°F"},
        {"ticker": "KXHIGHNY-26MAY01-B67.5", "result": "no", "title": "NYC high 67-68°F"},
    ]
    monkeypatch.setattr("backtest._fetch_settled_markets", lambda *a, **kw: markets)
    monkeypatch.setattr(
        "weather_markets.enrich_with_forecast",
        lambda m: {
            **m,
            "_city": "NYC",
            "_date": date(2026, 5, 1),
            "_lat": 40.77,
            "_lon": -73.96,
            "_tz": "America/New_York",
        },
    )
    monkeypatch.setattr("backtest.fetch_archive_temps", lambda *a, **kw: [70.0] * 20)

    result = backtest.run_backtest(MagicMock(), days_back=30)
    assert "brier_by_condition" in result
    assert isinstance(result["brier_by_condition"], dict)


# ── Phase 5.2: calibrate_condition_weights ────────────────────────────────────

def test_calibrate_condition_weights_returns_per_type_dict():
    """calibrate_condition_weights returns dict keyed by condition type."""
    import os
    import random
    import sqlite3
    import tempfile

    from calibration import calibrate_condition_weights

    random.seed(0)
    with tempfile.TemporaryDirectory() as d:
        db = os.path.join(d, "predictions.db")
        con = sqlite3.connect(db)
        con.executescript("""
            CREATE TABLE predictions (
                ticker TEXT, condition_type TEXT,
                ensemble_prob REAL, clim_prob REAL, nws_prob REAL
            );
            CREATE TABLE outcomes (ticker TEXT, settled_yes INTEGER);
        """)
        for ctype in ("above", "below", "between"):
            for i in range(120):
                t = f"{ctype}-{i}"
                ep = random.uniform(0.3, 0.8)
                cp = random.uniform(0.3, 0.7)
                np_ = random.uniform(0.3, 0.7)
                y = random.randint(0, 1)
                con.execute(
                    "INSERT INTO predictions VALUES (?,?,?,?,?)",
                    (t, ctype, ep, cp, np_),
                )
                con.execute("INSERT INTO outcomes VALUES (?,?)", (t, y))
        con.commit()
        con.close()

        weights = calibrate_condition_weights(db, min_samples=100)

    assert "above" in weights
    assert "below" in weights
    for w in weights.values():
        assert "ensemble" in w
        assert abs(sum(w.values()) - 1.0) < 0.01, "weights must sum to 1"
