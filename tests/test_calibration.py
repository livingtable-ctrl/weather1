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
                settled_at TEXT,
                disputed INTEGER DEFAULT 0
            )
        """)
        con.execute("""
            CREATE VIEW IF NOT EXISTS multiday_predictions AS
                SELECT * FROM predictions WHERE days_out IS NULL OR days_out >= 1
        """)
        con.execute("""
            CREATE VIEW IF NOT EXISTS outcomes_valid AS
                SELECT * FROM outcomes WHERE disputed IS NULL OR disputed = 0
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
                    # batch-82: per-row so a fixture can place a row on the
                    # metar_lockout path. Defaults to 'ensemble'.
                    r.get("method", "ensemble"),
                    50,
                    datetime.now().isoformat(),
                    # batch-82: per-row so a fixture can span both calibration
                    # horizons. Defaults to 3 -- every pre-batch-82 caller
                    # relies on these rows being multi-day.
                    # NULL days_out is meaningful ("predates the column",
                    # treated as multi-day), and .get already preserves an
                    # explicit None -- a round-2 review caught the earlier
                    # comment here claiming otherwise, which was simply wrong
                    # about dict.get. Reverted to the plain form.
                    r.get("days_out", 3),
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

    def test_monthly_snow_rows_not_counted(self):
        """backlog.txt Snow Step 2: the identical defense-in-depth check,
        mirrored for 'snow_month_total' -- mirrors
        test_monthly_rain_rows_not_counted's exact row-count reasoning."""
        from calibration import calibrate_seasonal_weights

        rows = _make_winter_rows(60)
        for r in rows[:30]:
            r["condition_type"] = "snow_month_total"
        _seed_db(self._db, rows)
        result = calibrate_seasonal_weights(self._db)
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

    def test_calibrate_writes_and_invalidates_the_sameday_tables(
        self, monkeypatch, capsys
    ):
        """batch-82: the same-day half of cmd_calibrate, end to end.

        Covers the three things the CLI path is responsible for beyond
        calibrate_and_save itself: the files land in data_dir, the summary is
        printed, and weather_markets' in-process same-day condition cache is
        invalidated rather than being left stale until the next mtime sweep.
        """
        import main
        import ml_bias
        import tracker
        import weather_markets as wm

        _seed_db(self._db, _mixed_horizon_rows())
        monkeypatch.setattr(tracker, "DB_PATH", self._db)
        monkeypatch.setattr(main, "_CALIBRATE_DATA_DIR", self._data_dir)
        monkeypatch.setattr(
            ml_bias, "_TEMP_PATH", self._data_dir / "temperature_scale.json"
        )
        # A stale value the run must replace. conftest's
        # isolate_condition_weights snapshots this table, so mutating it here
        # cannot leak into another test.
        wm._CONDITION_WEIGHTS_SAMEDAY.clear()
        wm._CONDITION_WEIGHTS_SAMEDAY["stale"] = {"ensemble": 1.0}

        main.cmd_calibrate()

        for name in (
            "seasonal_weights_sameday.json",
            "city_weights_sameday.json",
            "condition_weights_sameday.json",
        ):
            assert (self._data_dir / name).exists(), name
        sd_disk = json.loads(
            (self._data_dir / "condition_weights_sameday.json").read_text()
        )
        assert wm._CONDITION_WEIGHTS_SAMEDAY == sd_disk
        assert "stale" not in wm._CONDITION_WEIGHTS_SAMEDAY
        assert "Same-day (days_out=0) weights" in capsys.readouterr().out

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

    def test_calibrate_platt_excludes_snow_only_city(self, monkeypatch):
        """backlog.txt "RAIN / SNOW / HURRICANE MARKETS" Snow Step 2: the
        identical landmine rain's Step 2 closed for 'precip_month_total'
        also had to be closed for 'snow_month_total' -- mirrors
        test_calibrate_platt_excludes_rain_only_city exactly."""
        import main
        import ml_bias
        import tracker

        rows = _make_winter_rows(60)
        import random as _random

        _rng = _random.Random(43)
        snow_rows = []
        for i in range(60):
            p = _rng.uniform(0.3, 0.8)
            settled = 1 if _rng.random() < p else 0
            snow_rows.append(
                {
                    "ticker": f"SNOWCITY-{i}",
                    "city": "SnowOnlyCity",
                    "market_date": f"2026-01-{(i % 28) + 1:02d}",
                    "our_prob": p,
                    "ensemble_prob": 0.72,
                    "nws_prob": 0.65,
                    "clim_prob": 0.60,
                    "settled_yes": settled,
                    "condition_type": "snow_month_total",
                }
            )
        _seed_db(self._db, rows + snow_rows)

        monkeypatch.setattr(tracker, "DB_PATH", self._db)
        monkeypatch.setattr(main, "_CALIBRATE_DATA_DIR", self._data_dir)
        monkeypatch.setattr(
            ml_bias, "_TEMP_PATH", self._data_dir / "temperature_scale.json"
        )

        main.cmd_calibrate()

        platt_path = self._data_dir / "platt_models.json"
        if platt_path.exists():
            trained = json.loads(platt_path.read_text())
            assert "SnowOnlyCity" not in trained, (
                "a city with only snow rows must never get a Platt model -- "
                "the 60 snow rows leaked past the condition_type exclusion"
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
            CREATE TABLE outcomes (
                ticker TEXT, settled_yes INTEGER, disputed INTEGER DEFAULT 0
            );
            CREATE VIEW outcomes_valid AS
                SELECT * FROM outcomes WHERE disputed IS NULL OR disputed = 0;
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
                con.execute(
                    "INSERT INTO outcomes (ticker, settled_yes) VALUES (?,?)", (t, y)
                )
        con.commit()
        con.close()

        weights = calibrate_condition_weights(db, min_samples=100)

    assert "above" in weights
    assert "below" in weights
    for w in weights.values():
        assert "ensemble" in w
        # M-13(a): random/uncorrelated ep/cp/np vs y means this data never
        # clears the brier-improvement gate, so these come back _uncalibrated
        # (equal weights) -- exclude the "_"-prefixed flag from the sum,
        # same convention validate_weight_files already uses.
        _weight_sum = sum(v for k, v in w.items() if not k.startswith("_"))
        assert abs(_weight_sum - 1.0) < 0.01, "weights must sum to 1"


def test_calibrate_condition_weights_excludes_shadow_condition_types():
    """M-13(c): calibrate_condition_weights must exclude the same shadow
    condition-type families (_load_rows' exclusion list, e.g.
    hurricane_count) as calibrate_seasonal_weights/calibrate_city_weights
    already do via _load_rows -- a shadow family reaching min_samples rows
    must NOT silently gain a live blend-weight entry.

    Mutation-tested: removing the shadow-type filter from
    calibrate_condition_weights' SQL query makes this fail (hurricane_count
    appears in the result) -- confirmed via Edit revert.
    """
    import os
    import random
    import sqlite3
    import tempfile

    from calibration import calibrate_condition_weights

    random.seed(2)
    with tempfile.TemporaryDirectory() as d:
        db = os.path.join(d, "predictions.db")
        con = sqlite3.connect(db)
        con.executescript(
            """
            CREATE TABLE predictions (
                ticker TEXT, condition_type TEXT, market_date TEXT,
                ensemble_prob REAL, clim_prob REAL, nws_prob REAL,
                days_out INTEGER
            );
            CREATE TABLE outcomes (
                ticker TEXT, settled_yes INTEGER, disputed INTEGER DEFAULT 0
            );
            CREATE VIEW outcomes_valid AS
                SELECT * FROM outcomes WHERE disputed IS NULL OR disputed = 0;
        """
        )
        # "hurricane_count" is a shadow family, not a real above/below/between
        # condition -- 80 rows comfortably clears the default min_samples=60.
        for i in range(80):
            t = f"hurricane_count-{i}"
            month = (i % 12) + 1
            date_str = f"2025-{month:02d}-{(i % 28) + 1:02d}"
            con.execute(
                "INSERT INTO predictions VALUES (?,?,?,?,?,?,?)",
                (
                    t,
                    "hurricane_count",
                    date_str,
                    random.uniform(0.3, 0.8),
                    random.uniform(0.3, 0.7),
                    random.uniform(0.3, 0.7),
                    1,
                ),
            )
            con.execute(
                "INSERT INTO outcomes (ticker, settled_yes) VALUES (?,?)",
                (t, random.randint(0, 1)),
            )
        con.commit()
        con.close()

        weights = calibrate_condition_weights(db)

    assert "hurricane_count" not in weights, (
        "shadow condition-type family must never gain a live blend-weight entry"
    )


# ── batch-57 item 2: shared condition_type exclusion registry ────────────────


class TestSharedConditionTypeExclusion:
    """calibration.py / ml_bias.py / main.py all source the exclusion from tracker.

    batch-57 item 2 replaced five independently hand-written copies of the
    exclusion tuple with derivations from tracker's two canonical
    definitions. These tests pin that wiring so a site can't silently drift
    back to a local literal -- the exact failure mode the entry
    "CALIBRATION.PY/ML_BIAS.PY/MAIN.PY STILL HAVE THE STATIC HARDCODED BRIER
    CONDITION_TYPE EXCLUSION TUPLE" was filed about.
    """

    def test_calibration_shadow_list_is_derived_from_tracker(self):
        """_SHADOW_CONDITION_TYPES tracks the gate-coupled registry exactly."""
        import calibration
        import tracker

        assert calibration._SHADOW_CONDITION_TYPES == tuple(
            ct for ct, _ in tracker._GATE_COUPLED_EXCLUDED_CONDITION_TYPES
        )

    def test_calibration_list_excludes_between_by_design(self):
        """The one deliberate difference from _ALWAYS_EXCLUDED is preserved.

        'between' is a REAL value calibrate_condition_weights calibrates, so
        this list must stay the gate-backed families only. Verified as
        deliberate scoping (not drift) before consolidating; asserted here so
        a later "just use the longer list" cleanup fails loudly.
        """
        import calibration
        import tracker

        assert "between" not in calibration._SHADOW_CONDITION_TYPES
        assert "between" in tracker._ALWAYS_EXCLUDED_CONDITION_TYPES
        assert set(calibration._SHADOW_CONDITION_TYPES) | {"between"} == set(
            tracker._ALWAYS_EXCLUDED_CONDITION_TYPES
        )
        # The OTHER half of the carve-out (opus-review finding L2): the
        # omission is only correct because _load_rows's caller adds 'between'
        # back. Pinning only the omission would let a "simplification" to
        # _LOAD_ROWS_EXCLUDED_TYPES = _SHADOW_CONDITION_TYPES pass silently,
        # letting 'between' rows into the seasonal/city blend-weight grid
        # search whose weights feed live analyze_trade blending.
        assert "between" in calibration._LOAD_ROWS_EXCLUDED_TYPES
        assert set(calibration._LOAD_ROWS_EXCLUDED_TYPES) == set(
            tracker._ALWAYS_EXCLUDED_CONDITION_TYPES
        )
        # And the clause actually built from it carries 'between' too, so the
        # constant and the SQL cannot drift apart.
        assert "between" in calibration._LOAD_ROWS_COND_PARAMS
        assert "between" not in calibration._COND_WEIGHTS_COND_PARAMS

    def test_new_family_reaches_calibration_via_registry(self, monkeypatch, request):
        """Adding a family to tracker's registry propagates on reimport.

        The behavioural half of the first test: proves the value is DERIVED
        at import rather than a literal that merely happens to match today.

        Restore discipline (opus-review finding L7): the registry is patched
        via monkeypatch and the restoring reload is registered as a finalizer,
        so pytest guarantees it even if this test body raises AND even if the
        restoring reload itself would have been skipped. A bare
        try/finally with the reload inside the finally could leave calibration
        holding the mutated 6-family list for the whole session if that reload
        raised -- which is a live hazard, since a concurrent editor can make
        tracker.py briefly unparseable.

        Note tracker._ALWAYS_EXCLUDED_CONDITION_TYPES is computed once at
        tracker import and is deliberately NOT updated by this patch, so
        tracker is briefly self-inconsistent inside the window. Harmless here
        (nothing in the window reads it); don't extend this test to assert on
        it without also patching it.
        """
        import importlib

        import calibration
        import tracker

        original = tracker._GATE_COUPLED_EXCLUDED_CONDITION_TYPES

        # Registered BEFORE anything is mutated, so pytest runs it however
        # this test exits. It restores the registry ITSELF rather than relying
        # on monkeypatch's undo having already run: an earlier draft assumed
        # that ordering and was wrong -- this finalizer fires BEFORE
        # monkeypatch's teardown, so the reload rebuilt calibration from the
        # still-mutated registry and leaked a 6-family list into the rest of
        # the session. test_registry_mutation_did_not_leak below caught it.
        # Self-sufficient restore + reload is order-independent; monkeypatch's
        # own undo afterwards is then a harmless no-op.
        def _restore():
            tracker._GATE_COUPLED_EXCLUDED_CONDITION_TYPES = original
            importlib.reload(calibration)

        request.addfinalizer(_restore)

        monkeypatch.setattr(
            tracker,
            "_GATE_COUPLED_EXCLUDED_CONDITION_TYPES",
            (*original, ("locust_swarm_count", "_locust_gates_active")),
        )
        importlib.reload(calibration)
        assert "locust_swarm_count" in calibration._SHADOW_CONDITION_TYPES

    def test_registry_mutation_did_not_leak(self):
        """Positive control for the finalizer in the test above.

        Deliberately a SEPARATE test rather than a trailing assertion inside
        the mutating one: an assertion in the same test body runs before
        teardown, so it can only prove an inline restore, never that pytest's
        finalizer actually fired. Ordering is safe -- this file runs without
        pytest-randomly and unittest-style declaration order holds.
        """
        import calibration
        import tracker

        assert "locust_swarm_count" not in calibration._SHADOW_CONDITION_TYPES
        assert calibration._SHADOW_CONDITION_TYPES == tuple(
            ct for ct, _ in tracker._GATE_COUPLED_EXCLUDED_CONDITION_TYPES
        )

    @staticmethod
    def _max_inlined_family_names(source: str) -> int:
        """Largest count of exclusion-family names appearing in one literal group.

        AST-based rather than a substring scan (opus-review finding M1). The
        original scan looked for "'hurricane_next_event', 'storm_order'" --
        single-quoted, comma-space, same line -- which NEVER matched
        calibration.py, whose literal was a double-quoted tuple with one name
        per line. That made the test vacuous for the very file it headlined.
        This counts family names per *container* (tuple/list/set literal) and
        per *string constant*, so it is quote-, order-, and whitespace-
        agnostic.
        """
        import ast

        import tracker

        families = set(tracker._ALWAYS_EXCLUDED_CONDITION_TYPES)
        best = 0
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                best = max(best, sum(1 for f in families if f in node.value))
            elif isinstance(node, ast.Tuple | ast.List | ast.Set):
                names = {
                    e.value
                    for e in node.elts
                    if isinstance(e, ast.Constant) and isinstance(e.value, str)
                }
                best = max(best, len(names & families))
        return best

    def test_no_hardcoded_family_list_remains_in_consumer_files(self):
        """No consumer inlines the exclusion family list, in any quoting style."""
        from pathlib import Path

        root = Path(__file__).parent.parent
        for name in ("calibration.py", "ml_bias.py", "main.py"):
            src = (root / name).read_text(encoding="utf-8")
            assert self._max_inlined_family_names(src) < 4, (
                f"{name} appears to inline the exclusion family list again -- "
                "derive it from tracker's registry instead"
            )

    def test_inlined_family_detector_actually_detects(self):
        """Positive control for the detector above.

        Without this, the previous version of the scan silently passed on an
        unfixed file. Both the pre-batch-57 literal SHAPES must trip it: the
        double-quoted multi-line tuple calibration.py used, and the
        single-quoted single-line SQL string ml_bias.py/main.py used.
        """
        tuple_form = (
            "X = (\n"
            '    "precip_month_total",\n'
            '    "snow_month_total",\n'
            '    "hurricane_count",\n'
            '    "hurricane_next_event",\n'
            '    "storm_order",\n'
            ")\n"
        )
        sql_form = (
            'Q = """WHERE (p.condition_type IS NULL OR p.condition_type NOT IN '
            "('between', 'precip_month_total', 'snow_month_total', "
            "'hurricane_count', 'hurricane_next_event', 'storm_order'))\"\"\"\n"
        )
        assert self._max_inlined_family_names(tuple_form) >= 4
        assert self._max_inlined_family_names(sql_form) >= 4
        # Negative control: a derivation from the registry must NOT trip it.
        derived = "X = tuple(ct for ct, _ in tracker._GATE_COUPLED_EXCLUDED_CONDITION_TYPES)\n"
        assert self._max_inlined_family_names(derived) == 0

    def test_ml_bias_and_main_use_the_permanent_constant(self):
        """Both take _ALWAYS_EXCLUDED, not the gate-coupled function (M5 test).

        Their exclusion reason is scale mismatch (they fit temperature-shaped
        calibration curves), so a family graduating to live capital must NOT
        start feeding them.

        Scoped to the specific FUNCTIONS, not whole files (opus-review finding
        M2). A whole-file ban was wrong in both directions: main.py is the
        CLI entry point for the entire system, so a future diagnostic command
        that legitimately wants the dynamic gate-coupled set would have failed
        this test with a misleading message; and `in src` only proved the
        permanent constant appeared *somewhere* in a 7,900-line file, so a
        revert inside cmd_calibrate could still have passed.
        """
        import ast
        from pathlib import Path

        root = Path(__file__).parent.parent
        targets = {
            "ml_bias.py": ("train_bias_model", "train_all_temperature_scaling"),
            "main.py": ("cmd_calibrate",),
        }
        for name, fn_names in targets.items():
            tree = ast.parse((root / name).read_text(encoding="utf-8"))
            found = {
                n.name: n
                for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.name in fn_names
            }
            for fn_name in fn_names:
                assert fn_name in found, f"{name}: {fn_name} not found"
                # ast.unparse drops comments, so the rationale prose that
                # mentions the gate-coupled function can't false-positive.
                body = ast.unparse(found[fn_name])
                assert "_ALWAYS_EXCLUDED_CONDITION_TYPES" in body, (
                    f"{name}:{fn_name} must use the permanent constant"
                )
                assert "_excluded_brier_condition_types(" not in body, (
                    f"{name}:{fn_name} must not gate-couple a calibration-curve fit"
                )


# ── batch-82: same-day (days_out=0) calibration horizon ───────────────────────


def _mixed_horizon_rows() -> list[dict]:
    """Rows at both horizons, with a DIFFERENT signal structure in each.

    Same-day rows are built so climatology alone predicts the outcome
    perfectly and ensemble/NWS are anti-correlated with it; multi-day rows are
    built the opposite way round. That makes the two fits land far apart, which
    is what lets the horizon tests assert *which* population produced a given
    weight file rather than merely that both files exist.
    """
    rows: list[dict] = []
    for i in range(80):
        settled = i % 2 == 0
        rows.append(
            {
                "ticker": f"SD-{i}",
                "city": "Denver",
                "market_date": f"2026-01-{(i % 28) + 1:02d}",
                "our_prob": 0.5,
                "days_out": 0,
                "clim_prob": 0.97 if settled else 0.03,
                "ensemble_prob": 0.05 if settled else 0.95,
                "nws_prob": 0.05 if settled else 0.95,
                "settled_yes": settled,
            }
        )
    for i in range(80):
        settled = i % 2 == 0
        rows.append(
            {
                "ticker": f"MD-{i}",
                "city": "Denver",
                "market_date": f"2026-01-{(i % 28) + 1:02d}",
                "our_prob": 0.5,
                "days_out": 2,
                "ensemble_prob": 0.97 if settled else 0.03,
                "clim_prob": 0.05 if settled else 0.95,
                "nws_prob": 0.05 if settled else 0.95,
                "settled_yes": settled,
            }
        )
    return rows


class TestHorizonSplit:
    """_load_rows partitions the population; neither horizon sees the other."""

    def setup_method(self):
        self._tmpdir = tempfile.mkdtemp()
        self._db = Path(self._tmpdir) / "test.db"
        _seed_db(self._db, _mixed_horizon_rows())

    def teardown_method(self):
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_sameday_loads_only_days_out_zero(self):
        from calibration import _HORIZON_SAMEDAY, _load_rows

        rows = _load_rows(self._db, horizon=_HORIZON_SAMEDAY)
        assert len(rows) == 80
        assert all(r["city"] == "Denver" for r in rows)
        # Positive control on the discriminating column: the same-day rows are
        # the ones whose clim_prob is the extreme value, so this proves the
        # SAME-DAY population arrived and not merely "80 rows of something".
        assert {round(r["clim_prob"], 2) for r in rows} == {0.97, 0.03}

    def test_multiday_loads_only_days_out_ge_one(self):
        from calibration import _HORIZON_MULTIDAY, _load_rows

        rows = _load_rows(self._db, horizon=_HORIZON_MULTIDAY)
        assert len(rows) == 80
        assert {round(r["ensemble_prob"], 2) for r in rows} == {0.97, 0.03}

    def test_default_horizon_is_multiday(self):
        """Every pre-batch-82 caller passes no horizon and must be unaffected."""
        from calibration import _HORIZON_MULTIDAY, _load_rows

        assert [tuple(r) for r in _load_rows(self._db)] == [
            tuple(r) for r in _load_rows(self._db, horizon=_HORIZON_MULTIDAY)
        ]

    def test_the_two_horizons_partition_the_population(self):
        """No row is in both, and together they are the whole fittable set."""
        import sqlite3 as _sq

        from calibration import _HORIZON_MULTIDAY, _HORIZON_SAMEDAY, _load_rows

        sd = _load_rows(self._db, horizon=_HORIZON_SAMEDAY)
        md = _load_rows(self._db, horizon=_HORIZON_MULTIDAY)
        with _sq.connect(str(self._db)) as con:
            total = con.execute(
                "SELECT COUNT(*) FROM predictions p JOIN outcomes_valid o "
                "ON p.ticker = o.ticker WHERE p.ensemble_prob IS NOT NULL "
                "AND p.nws_prob IS NOT NULL AND p.clim_prob IS NOT NULL "
                "AND o.settled_yes IS NOT NULL"
            ).fetchone()[0]
        assert len(sd) + len(md) == total
        assert not ({tuple(r) for r in sd} & {tuple(r) for r in md})

    def test_unknown_horizon_raises_rather_than_defaulting(self):
        """A typo must not silently fit the wrong population."""
        import pytest

        from calibration import (
            _load_rows,
            calibrate_city_weights,
            calibrate_condition_weights,
            calibrate_seasonal_weights,
        )

        for fn in (
            _load_rows,
            calibrate_seasonal_weights,
            calibrate_city_weights,
            calibrate_condition_weights,
        ):
            with pytest.raises(ValueError, match="unknown calibration horizon"):
                fn(self._db, horizon="same-day")  # correct spelling is "sameday"

    def test_horizon_is_keyword_only(self):
        """horizon must not be passable positionally.

        calibrate_*'s second positional is cutoff_date, so a positional
        horizon would silently be read as a cutoff DATE -- the call would
        succeed, fit the wrong (default multi-day) population, and the result
        would be written to a same-day file. Caught while writing the test
        above, which is why it is pinned rather than left to review.
        """
        import inspect

        import pytest

        from calibration import (
            _load_rows,
            calibrate_city_weights,
            calibrate_condition_weights,
            calibrate_seasonal_weights,
        )

        for fn in (
            _load_rows,
            calibrate_seasonal_weights,
            calibrate_city_weights,
            calibrate_condition_weights,
        ):
            kind = inspect.signature(fn).parameters["horizon"].kind
            assert kind is inspect.Parameter.KEYWORD_ONLY, f"{fn.__name__}: {kind}"
        # Behavioural half: a THIRD positional -- the shape someone reaching
        # for the new parameter would most naturally write -- is now a
        # TypeError rather than being bound to something else.
        with pytest.raises(TypeError):
            calibrate_seasonal_weights(self._db, None, "sameday")
        # Honest limitation: a SECOND positional still binds to cutoff_date,
        # which no keyword-only marker can prevent. It degrades safely rather
        # than fitting the wrong population -- "sameday" sorts after every ISO
        # date, so the 80/20 split puts every row in train and none in val,
        # and _best_weights' val-row floor returns _uncalibrated.
        assert calibrate_seasonal_weights(self._db, "sameday")["winter"][
            "_uncalibrated"
        ]

    def test_sameday_path_keeps_the_between_and_shadow_exclusion(self):
        """_LOAD_ROWS_COND_CLAUSE must survive on the new horizon too."""
        from calibration import _HORIZON_SAMEDAY, _load_rows

        extra = [
            {
                "ticker": f"BTW-{i}",
                "city": "Denver",
                "market_date": "2026-01-05",
                "condition_type": "between",
                "our_prob": 0.5,
                "days_out": 0,
                "ensemble_prob": 0.5,
                "nws_prob": 0.5,
                "clim_prob": 0.5,
                "settled_yes": True,
            }
            for i in range(30)
        ]
        extra += [
            {**r, "ticker": f"HUR-{i}", "condition_type": "hurricane_count"}
            for i, r in enumerate(extra[:30])
        ]
        _seed_db(self._db, extra)
        rows = _load_rows(self._db, horizon=_HORIZON_SAMEDAY)
        assert {r["condition_type"] for r in rows} == {"above"}
        assert len(rows) == 80  # the 60 excluded rows did not leak in


class TestSamedayFitIsSeparateFromMultiday:
    """The user's constraint: the two fits must stay 100% separate on disk."""

    def setup_method(self):
        self._tmpdir = tempfile.mkdtemp()
        self._db = Path(self._tmpdir) / "test.db"
        self._out = Path(self._tmpdir) / "out"
        self._out.mkdir()
        _seed_db(self._db, _mixed_horizon_rows())

    def teardown_method(self):
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _fits(self):
        from calibration import (
            _HORIZON_MULTIDAY,
            _HORIZON_SAMEDAY,
            calibrate_seasonal_weights,
        )

        sd = calibrate_seasonal_weights(self._db, horizon=_HORIZON_SAMEDAY)["winter"]
        md = calibrate_seasonal_weights(self._db, horizon=_HORIZON_MULTIDAY)["winter"]
        return sd, md

    def test_the_two_horizons_produce_different_weights(self):
        """Guards every other test here: if these coincided they'd be vacuous."""
        sd, md = self._fits()
        assert not sd.get("_uncalibrated"), sd
        assert not md.get("_uncalibrated"), md
        # Same-day rows are climatology-driven, multi-day rows ensemble-driven.
        assert sd["climatology"] > 0.5, sd
        assert md["ensemble"] > 0.5, md

    def test_calibrate_and_save_writes_each_fit_to_its_own_file(self):
        import json as _json

        from calibration import calibrate_and_save

        calibrate_and_save(self._db, self._out)
        md_disk = _json.loads((self._out / "seasonal_weights.json").read_text())
        sd_disk = _json.loads((self._out / "seasonal_weights_sameday.json").read_text())
        sd_fit, md_fit = self._fits()

        # Positive control: each file holds its OWN horizon's fit...
        assert md_disk["winter"]["ensemble"] == md_fit["ensemble"]
        assert sd_disk["winter"]["climatology"] == sd_fit["climatology"]
        # ...and the absence half -- neither file carries the other's values.
        assert md_disk["winter"]["ensemble"] != sd_fit["ensemble"]
        assert sd_disk["winter"]["ensemble"] != md_fit["ensemble"]

    def test_every_table_keeps_its_own_horizon_content(self):
        """Content separation for ALL THREE tables, not just seasonal.

        Four contamination mutations survived the seasonal-only version
        (opus review, HIGH): preserving a same-day fit FROM the multi-day
        file (seasonal/condition), and writing a multi-day fit INTO a
        same-day file (condition/city). Condition is the consequential one --
        _blend_weights resolves it before seasonal, and the live
        condition_weights.json holds real fitted values, so contamination
        there would pin every same-day trade to multi-day numbers with no
        _uncalibrated flag and nothing would notice.
        """
        import json as _json

        from calibration import (
            _HORIZON_MULTIDAY,
            _HORIZON_SAMEDAY,
            calibrate_city_weights,
            calibrate_condition_weights,
            calibrate_seasonal_weights,
        )

        calibrate_and_save_ = __import__("calibration").calibrate_and_save
        calibrate_and_save_(self._db, self._out)

        # City included (round-2 opus review): the earlier version's docstring
        # claimed all three tables but looped over two, and city_weights_
        # sameday.json's CONTENT was asserted nowhere in the suite -- only its
        # existence. So writing the multi-day city fit into the same-day city
        # file survived the entire scoped test set.
        for name, fn, key in (
            ("seasonal_weights", calibrate_seasonal_weights, "winter"),
            ("condition_weights", calibrate_condition_weights, "above"),
            ("city_weights", calibrate_city_weights, "Denver"),
        ):
            md_disk = _json.loads((self._out / f"{name}.json").read_text())
            sd_disk = _json.loads((self._out / f"{name}_sameday.json").read_text())
            md_fit = fn(self._db, horizon=_HORIZON_MULTIDAY)[key]
            sd_fit = fn(self._db, horizon=_HORIZON_SAMEDAY)[key]
            # Whatever each horizon produced, that is what its own file holds.
            assert md_disk[key] == md_fit, (name, "multiday file")
            assert sd_disk[key] == sd_fit, (name, "sameday file")
            # And the two are distinguishable, so the above is not vacuous.
            assert md_fit != sd_fit, (name, "fits coincided -- test is vacuous")

    def test_preservation_reads_each_file_s_own_history_not_its_sibling_s(self):
        """_preserve_hand_tuned_weights must never cross horizons.

        It restores an on-disk calibrated entry whenever the fresh fit
        declines. Pointed at the WRONG file it would make a declining
        same-day tier silently adopt multi-day numbers -- and "declining" is
        the normal state for every same-day tier on real data, so this is the
        likeliest contamination direction of all (opus review, HIGH).

        TWO runs, because preservation reads the target file BEFORE this run
        writes it: on a first run into an empty dir there is nothing on disk
        to preserve from, so the contamination is invisible. Run 1 populates
        both horizons' files; run 2 removes the same-day rows so every
        same-day fit declines and preservation is forced to fire.
        """
        import json as _json
        import sqlite3 as _sq

        from calibration import calibrate_and_save

        calibrate_and_save(self._db, self._out)
        after_run_1 = {
            name: _json.loads((self._out / f"{name}.json").read_text())
            for name in (
                "seasonal_weights",
                "seasonal_weights_sameday",
                "condition_weights",
                "condition_weights_sameday",
            )
        }
        with _sq.connect(str(self._db)) as con:
            con.execute("DELETE FROM predictions WHERE days_out = 0")
        calibrate_and_save(self._db, self._out)

        for name, key in (
            ("seasonal_weights", "winter"),
            ("condition_weights", "above"),
        ):
            md_1 = after_run_1[name][key]
            sd_1 = after_run_1[f"{name}_sameday"][key]
            sd_2 = _json.loads((self._out / f"{name}_sameday.json").read_text())[key]
            # Positive controls: run 1 really did fit BOTH horizons to
            # DIFFERENT values, so there is something to confuse and the
            # assertions below can actually discriminate.
            assert not md_1.get("_uncalibrated"), (name, md_1)
            assert not sd_1.get("_uncalibrated"), (name, sd_1)
            assert md_1["ensemble"] != sd_1["ensemble"], (name, "fits coincided")
            # Run 2's same-day fit declined, so preservation fired. It must
            # have restored the SAME-DAY file's own earlier value...
            assert sd_2 == sd_1, (name, "same-day lost its own history", sd_2)
            # ...and must not have reached across to the multi-day file.
            assert sd_2["ensemble"] != md_1["ensemble"], (name, "CONTAMINATED", sd_2)

    def test_all_six_files_are_written(self):
        from calibration import calibrate_and_save

        calibrate_and_save(self._db, self._out)
        for name in (
            "seasonal_weights.json",
            "city_weights.json",
            "condition_weights.json",
            "seasonal_weights_sameday.json",
            "city_weights_sameday.json",
            "condition_weights_sameday.json",
        ):
            assert (self._out / name).exists(), name

    def test_return_tuple_stays_three_wide_for_cron(self):
        """cron.py unpacks exactly three values at two call sites."""
        from calibration import calibrate_and_save

        assert len(calibrate_and_save(self._db, self._out)) == 3

    def test_returned_dicts_are_the_multiday_fit(self):
        from calibration import calibrate_and_save

        seasonal, _city, _cond = calibrate_and_save(self._db, self._out)
        _sd_fit, md_fit = self._fits()
        assert seasonal["winter"]["ensemble"] == md_fit["ensemble"]

    def test_a_sameday_rerun_cannot_overwrite_the_multiday_file(self):
        """Re-running with ONLY same-day rows present leaves multi-day intact."""
        import json as _json
        import sqlite3 as _sq

        from calibration import calibrate_and_save

        calibrate_and_save(self._db, self._out)
        before = (self._out / "seasonal_weights.json").read_text()
        # Delete every multi-day row, then recalibrate. The multi-day fit now
        # declines (no rows), and _preserve_hand_tuned_weights must keep the
        # previously-written multi-day values rather than letting the run
        # blank them -- and the same-day file must be the only thing that can
        # carry same-day numbers.
        with _sq.connect(str(self._db)) as con:
            con.execute("DELETE FROM predictions WHERE days_out >= 1")
        calibrate_and_save(self._db, self._out)
        assert (self._out / "seasonal_weights.json").read_text() == before
        sd_disk = _json.loads((self._out / "seasonal_weights_sameday.json").read_text())
        assert sd_disk["winter"]["climatology"] > 0.5


def _repo_seeds_dir() -> Path:
    """seeds/ of THIS checkout, not paths.SEEDS_DIR.

    Same reasoning as tests/test_paths.py's _REPO_ROOT: paths.SEEDS_DIR
    resolves through safe_io.project_root(), which returns the MAIN CLONE even
    when the tests are running from a worktree -- so it would review the wrong
    checkout's seeds (and fail outright on a worktree that has just added
    one). The two coincide in the main clone and on CI.
    """
    import paths as _paths

    return Path(_paths.__file__).resolve().parent / "seeds"


class TestSamedaySeedFlag:
    """batch-79's hazard: an unflagged uniform dict reads as a real fit."""

    def test_every_sameday_seed_entry_is_flagged_uncalibrated(self):
        import json as _json

        seeds = _repo_seeds_dir()
        checked = 0
        for name in (
            "seasonal_weights_sameday.json",
            "condition_weights_sameday.json",
            "city_weights_sameday.json",
        ):
            data = _json.loads((seeds / name).read_text())
            assert isinstance(data, dict), name
            for key, entry in data.items():
                assert entry.get("_uncalibrated") is True, f"{name}:{key} lost the flag"
                checked += 1
        # Positive control (opus review): city_weights_sameday.json is {}, so
        # its loop body never runs. Without this the test reads as covering
        # three files while covering two -- and an empty seasonal/condition
        # seed would pass silently.
        assert checked == 7, f"expected 4 seasons + 3 conditions, checked {checked}"

    def test_sameday_seed_key_sets_match_their_calibrators(self):
        import json as _json

        seeds = _repo_seeds_dir()
        assert set(
            _json.loads((seeds / "seasonal_weights_sameday.json").read_text())
        ) == {"winter", "spring", "summer", "fall"}
        assert set(
            _json.loads((seeds / "condition_weights_sameday.json").read_text())
        ) == {"above", "below", "between"}
        # city mirrors its multi-day sibling: below-floor cities are omitted
        # outright rather than given a placeholder, so an empty dict is correct.
        assert _json.loads((seeds / "city_weights_sameday.json").read_text()) == {}


class TestSamedayValidationAndWiring:
    """Gaps the opus review found in batch-82's own first pass."""

    def test_validate_weight_files_flags_a_malformed_sameday_entry(self, caplog):
        """_validate_present_entries had zero coverage (opus review, LOW)."""
        import logging

        from calibration import validate_weight_files

        bad = {"above": {"ensemble": 0.9, "climatology": 0.9, "nws": 0.9}}
        with caplog.at_level(logging.ERROR):
            validate_weight_files(
                seasonal={},
                city={},
                condition={},
                seasonal_sameday={},
                city_sameday={},
                condition_sameday=bad,
            )
        assert any(
            "Same-day condition" in r.message and "sum to 1.0" in r.message
            for r in caplog.records
        ), [r.message for r in caplog.records]

    def test_validate_weight_files_flags_a_negative_sameday_weight(self, caplog):
        import logging

        from calibration import validate_weight_files

        bad = {"winter": {"ensemble": 1.4, "climatology": -0.4, "nws": 0.0}}
        with caplog.at_level(logging.ERROR):
            validate_weight_files(
                seasonal={},
                city={},
                condition={},
                seasonal_sameday=bad,
                city_sameday={},
                condition_sameday={},
            )
        assert any("negative" in r.message for r in caplog.records), [
            r.message for r in caplog.records
        ]

    def test_validate_weight_files_does_not_warn_about_an_absent_sameday_key(
        self, caplog
    ):
        """Absence is the NORMAL same-day state and must stay silent.

        Unlike the multi-day seasonal/condition loops, a missing same-day
        entry means "this tier has not graduated", which _blend_weights
        handles by falling through. Warning on it would fire on every startup.
        """
        import logging

        from calibration import validate_weight_files

        with caplog.at_level(logging.WARNING):
            validate_weight_files(
                seasonal={
                    s: {"ensemble": 1 / 3, "climatology": 1 / 3, "nws": 1 / 3}
                    for s in ("spring", "summer", "fall", "winter")
                },
                city={},
                condition={
                    c: {"ensemble": 1 / 3, "climatology": 1 / 3, "nws": 1 / 3}
                    for c in ("above", "below", "between")
                },
                seasonal_sameday={},
                city_sameday={},
                condition_sameday={},
            )
        assert not [r for r in caplog.records if "Same-day" in r.message], [
            r.message for r in caplog.records
        ]
        # Positive control: the same call DOES speak up for a malformed entry,
        # so the silence above is about absence, not about the code being inert.
        caplog.clear()
        with caplog.at_level(logging.ERROR):
            validate_weight_files(
                seasonal={},
                city={},
                condition={},
                seasonal_sameday={"winter": {"ensemble": 5.0}},
                city_sameday={},
                condition_sameday={},
            )
        assert any("Same-day seasonal" in r.message for r in caplog.records)

    def test_calibrate_and_save_writes_exactly_the_paths_py_filenames(self):
        """Binds calibrate_and_save's write literals to the path constants.

        The writer uses six hardcoded strings; every loader resolves
        paths.*_PATH. Nothing bound them, so a rename done consistently in
        paths.py + _SEEDED_FILENAMES + seeds/ would leave calibrate_and_save
        writing the old names with a green suite (opus review, LOW).
        """
        import shutil
        import tempfile
        from pathlib import Path as _P

        import paths
        from calibration import calibrate_and_save

        tmp = _P(tempfile.mkdtemp())
        try:
            db = tmp / "t.db"
            out = tmp / "out"
            out.mkdir()
            _seed_db(db, _mixed_horizon_rows())
            calibrate_and_save(db, out)
            written = {p.name for p in out.glob("*.json")}
            expected = {
                paths.SEASONAL_WEIGHTS_PATH.name,
                paths.CITY_WEIGHTS_PATH.name,
                paths.CONDITION_WEIGHTS_PATH.name,
                paths.SEASONAL_WEIGHTS_SAMEDAY_PATH.name,
                paths.CITY_WEIGHTS_SAMEDAY_PATH.name,
                paths.CONDITION_WEIGHTS_SAMEDAY_PATH.name,
            }
            assert written == expected, written ^ expected
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_sameday_pool_excludes_metar_lockout_rows_structurally(self):
        """batch-75's population-mixing lesson, made structural.

        The three NOT NULL predicates already drop today's metar_lockout rows
        because none of them carry component probs. This pins the property
        against the day that changes (opus review, MEDIUM-LOW).
        """
        import shutil
        import tempfile
        from pathlib import Path as _P

        from calibration import _HORIZON_SAMEDAY, _load_rows

        tmp = _P(tempfile.mkdtemp())
        try:
            db = tmp / "t.db"
            rows = [
                {
                    "ticker": f"LOCK-{i}",
                    "city": "Denver",
                    "market_date": "2026-01-07",
                    "our_prob": 0.5,
                    "days_out": 0,
                    # The case the NOT NULL predicates would NOT catch: a
                    # locked row that does carry all three component probs.
                    "ensemble_prob": 0.5,
                    "nws_prob": 0.5,
                    "clim_prob": 0.5,
                    "settled_yes": True,
                    "method": "metar_lockout",
                }
                for i in range(20)
            ]
            _seed_db(db, rows + _mixed_horizon_rows())
            loaded = _load_rows(db, horizon=_HORIZON_SAMEDAY)
            assert len(loaded) == 80, len(loaded)  # the 20 locked rows dropped
            # Positive control: the same 20 rows DO arrive once the method is
            # anything else, so the count above is the exclusion working and
            # not some unrelated filter.
            db2 = tmp / "t2.db"
            _seed_db(
                db2,
                [{**r, "method": "ensemble"} for r in rows] + _mixed_horizon_rows(),
            )
            assert len(_load_rows(db2, horizon=_HORIZON_SAMEDAY)) == 100
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_null_days_out_counts_as_multiday_not_sameday(self):
        """tracker.py: NULL days_out "predates the column, treated as
        multi-day". The horizon fixture only had {0, 2} rows, so this branch
        -- the likeliest real-world edge -- was uncovered (opus review, LOW).
        """
        import shutil
        import tempfile
        from pathlib import Path as _P

        from calibration import _HORIZON_MULTIDAY, _HORIZON_SAMEDAY, _load_rows

        tmp = _P(tempfile.mkdtemp())
        try:
            db = tmp / "t.db"
            nulls = [
                {
                    "ticker": f"OLD-{i}",
                    "city": "Denver",
                    "market_date": "2026-01-09",
                    "our_prob": 0.5,
                    "days_out": None,
                    "ensemble_prob": 0.6,
                    "nws_prob": 0.6,
                    "clim_prob": 0.6,
                    "settled_yes": True,
                }
                for i in range(15)
            ]
            _seed_db(db, nulls + _mixed_horizon_rows())
            assert len(_load_rows(db, horizon=_HORIZON_SAMEDAY)) == 80
            assert len(_load_rows(db, horizon=_HORIZON_MULTIDAY)) == 95
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
