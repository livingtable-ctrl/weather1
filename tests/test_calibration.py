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
        con.execute("""
            CREATE VIEW IF NOT EXISTS multiday_predictions AS
                SELECT * FROM predictions WHERE days_out IS NULL OR days_out >= 1
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
                    r.get("condition_type", "above"),
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
        """10 predictions (< 20) → season returned with neutral uncalibrated defaults."""
        from calibration import calibrate_seasonal_weights

        _seed_db(self._db, _make_winter_rows(10))
        result = calibrate_seasonal_weights(self._db)
        # Under-sampled seasons now return neutral defaults so callers never see
        # "missing key" warnings. The "_uncalibrated" flag tells _blend_weights to
        # fall through to the hardcoded schedule rather than using these values.
        assert "winter" in result, "under-sampled season should have neutral defaults"
        assert result["winter"].get("_uncalibrated") is True
        assert abs(result["winter"]["ensemble"] - 1 / 3) < 1e-6

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
        # 15 valid rows < _SEASONAL_MIN=20 → neutral defaults, not data-derived weights
        assert "winter" in result
        assert result["winter"].get("_uncalibrated") is True

    def test_monthly_rain_rows_not_counted(self):
        """backlog.txt "RAIN / SNOW / HURRICANE MARKETS" Step 2 (review-
        caught, defense-in-depth): condition_type='precip_month_total' rows
        must not count toward the seasonal calibration threshold even if
        (hypothetically -- the real rain model never populates these
        columns today) ensemble_prob/nws_prob/clim_prob were all set.

        60 total rows (30 real 'above' + 30 rain) rather than the smaller
        counts used elsewhere in this class: _best_weights' own internal
        80/20 validation-row floor (needs >=10 val rows) means a 30-row
        total (as in test_rows_without_source_probs_not_counted's sibling
        pattern) stays "uncalibrated" via THAT floor regardless of whether
        the condition_type exclusion works, making a 30-row version of
        this test vacuous -- confirmed by mutation-testing it first, which
        is why 60 is used here: enough real rows to clear _SEASONAL_MIN=20
        but its own 24-train/6-val split still trips the val-row floor,
        while 60-total (if the rain rows leaked in) would give a real
        48-train/12-val split that clears it and returns calibrated
        (non-neutral) weights."""
        from calibration import calibrate_seasonal_weights

        rows = _make_winter_rows(60)
        for r in rows[:30]:
            r["condition_type"] = "precip_month_total"
        _seed_db(self._db, rows)
        result = calibrate_seasonal_weights(self._db)
        # Only the 30 real "above" rows remain visible -- their own 80/20
        # split (24/6) trips the val-row floor -> neutral defaults. If the
        # 30 rain rows leaked in (60 total, 48/12 split), this would
        # instead return real calibrated (non-"_uncalibrated") weights.
        assert "winter" in result
        assert result["winter"].get("_uncalibrated") is True


class TestCalibrateCityWeights:
    def setup_method(self):
        self._tmpdir = tempfile.mkdtemp()
        self._db = Path(self._tmpdir) / "test.db"

    def teardown_method(self):
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_returns_weights_for_qualifying_city(self):
        """55 NYC predictions (>= 50) → NYC weights present and valid."""
        from calibration import calibrate_city_weights

        rows = _make_winter_rows(55, base_ticker="NYC")
        _seed_db(self._db, rows)
        result = calibrate_city_weights(self._db)
        assert "NYC" in result
        w = result["NYC"]
        assert abs(w["ensemble"] + w["climatology"] + w["nws"] - 1.0) < 1e-6

    def test_below_threshold_omits_city(self):
        """10 predictions (< 50) → city absent."""
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

    def test_load_condition_missing_file_returns_empty(self):
        from calibration import load_condition_weights

        result = load_condition_weights(Path(self._tmpdir) / "nonexistent.json")
        assert result == {}

    def test_load_condition_valid_json_returns_dict(self):
        from calibration import load_condition_weights

        p = Path(self._tmpdir) / "condition.json"
        p.write_text(
            json.dumps(
                {
                    "above": {"ensemble": 0.50, "climatology": 0.20, "nws": 0.30},
                    "below": {"ensemble": 0.45, "climatology": 0.25, "nws": 0.30},
                    "between": {"ensemble": 1 / 3, "climatology": 1 / 3, "nws": 1 / 3},
                }
            )
        )
        result = load_condition_weights(p)
        assert result == {
            "above": {"ensemble": 0.50, "climatology": 0.20, "nws": 0.30},
            "below": {"ensemble": 0.45, "climatology": 0.25, "nws": 0.30},
            "between": {"ensemble": 1 / 3, "climatology": 1 / 3, "nws": 1 / 3},
        }

    def test_load_condition_corrupt_json_returns_empty(self):
        from calibration import load_condition_weights

        p = Path(self._tmpdir) / "corrupt.json"
        p.write_text("not valid json {{")
        result = load_condition_weights(p)
        assert result == {}


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
        import ml_bias
        import tracker

        rows = _make_winter_rows(60)
        _seed_db(self._db, rows)

        # Redirect DB_PATH to the test DB
        monkeypatch.setattr(tracker, "DB_PATH", self._db)

        # Redirect the output data directory
        monkeypatch.setattr(main, "_CALIBRATE_DATA_DIR", self._data_dir)

        # Redirect temperature_scale.json so cmd_calibrate does not overwrite the real file
        monkeypatch.setattr(
            ml_bias, "_TEMP_PATH", self._data_dir / "temperature_scale.json"
        )

        main.cmd_calibrate()

        seasonal_path = self._data_dir / "seasonal_weights.json"
        assert seasonal_path.exists(), "seasonal_weights.json was not written"
        loaded = json.loads(seasonal_path.read_text())
        assert "winter" in loaded
        w = loaded["winter"]
        assert abs(w["ensemble"] + w["climatology"] + w["nws"] - 1.0) < 1e-6

    def test_calibrate_calls_update_learned_weights(self, monkeypatch):
        """P1-9: cmd_calibrate() must call update_learned_weights_from_tracker()."""
        import main
        import ml_bias
        import tracker
        import weather_markets

        rows = _make_winter_rows(60)
        _seed_db(self._db, rows)

        monkeypatch.setattr(tracker, "DB_PATH", self._db)
        monkeypatch.setattr(main, "_CALIBRATE_DATA_DIR", self._data_dir)
        monkeypatch.setattr(
            ml_bias, "_TEMP_PATH", self._data_dir / "temperature_scale.json"
        )

        called = []

        def fake_update():
            called.append(True)
            return {}

        monkeypatch.setattr(
            weather_markets, "update_learned_weights_from_tracker", fake_update
        )

        main.cmd_calibrate()

        assert called, "cmd_calibrate() must call update_learned_weights_from_tracker()"

    def test_calibrate_platt_excludes_rain_only_city(self, monkeypatch):
        """backlog.txt "RAIN / SNOW / HURRICANE MARKETS" Step 2 (review-
        caught, MEDIUM finding): cmd_calibrate()'s inline Platt-scaling
        query must exclude condition_type='precip_month_total' the same
        way the seasonal/city calibration queries do. A city with only
        rain rows (60, well above the 50 min_samples cmd_calibrate passes)
        must never be trained -- if the exclusion were missing, this city
        would clear the threshold and get a real (spurious) Platt model."""
        import main
        import ml_bias
        import tracker

        # Enough winter rows so cmd_calibrate's earlier seasonal-weights
        # step doesn't bail out before ever reaching the Platt block.
        rows = _make_winter_rows(60)
        # Randomized (not a deterministic alternating pattern) so _fit_platt
        # actually converges to a valid coefficient when this data IS
        # included -- a first version of this test used a perfectly
        # alternating 0.7/0.3 pattern, which made _fit_platt itself reject
        # the fit (A far outside the accepted range) regardless of whether
        # the condition_type exclusion worked, making the test vacuous
        # (caught by mutation-testing before landing this version).
        import random as _random

        _rng = _random.Random(42)
        rain_rows = []
        for i in range(60):
            p = _rng.uniform(0.3, 0.8)
            settled = 1 if _rng.random() < p else 0
            rain_rows.append(
                {
                    "ticker": f"RAINCITY-{i}",
                    "city": "RainOnlyCity",
                    "market_date": f"2026-01-{(i % 28) + 1:02d}",
                    "our_prob": p,
                    "ensemble_prob": 0.72,
                    "nws_prob": 0.65,
                    "clim_prob": 0.60,
                    "settled_yes": settled,
                    "condition_type": "precip_month_total",
                }
            )
        _seed_db(self._db, rows + rain_rows)

        monkeypatch.setattr(tracker, "DB_PATH", self._db)
        monkeypatch.setattr(main, "_CALIBRATE_DATA_DIR", self._data_dir)
        monkeypatch.setattr(
            ml_bias, "_TEMP_PATH", self._data_dir / "temperature_scale.json"
        )

        main.cmd_calibrate()

        platt_path = self._data_dir / "platt_models.json"
        if platt_path.exists():
            trained = json.loads(platt_path.read_text())
            assert "RainOnlyCity" not in trained, (
                "a city with only rain rows must never get a Platt model -- "
                "the 60 rain rows leaked past the condition_type exclusion"
            )


# ── Phase 5.1: brier_by_condition in backtest ─────────────────────────────────


def test_run_backtest_reports_per_condition_type(monkeypatch):
    """run_backtest result includes brier_by_condition dict."""
    from datetime import date
    from unittest.mock import MagicMock

    import backtest

    markets = [
        {"ticker": "KXHIGHNY-26MAY01-T70", "result": "yes", "title": "NYC high > 70°F"},
        {
            "ticker": "KXHIGHNY-26MAY01-B67.5",
            "result": "no",
            "title": "NYC high 67-68°F",
        },
    ]
    monkeypatch.setattr("backtest._fetch_settled_markets", lambda *a, **kw: markets)
    monkeypatch.setattr(
        "weather_markets.enrich_with_forecast",
        lambda m, **kw: {
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
                ticker TEXT, condition_type TEXT, market_date TEXT,
                ensemble_prob REAL, clim_prob REAL, nws_prob REAL,
                days_out INTEGER
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
                month = (i % 12) + 1
                date_str = f"2025-{month:02d}-{(i % 28) + 1:02d}"
                con.execute(
                    "INSERT INTO predictions VALUES (?,?,?,?,?,?,?)",
                    (t, ctype, date_str, ep, cp, np_, 1),
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
