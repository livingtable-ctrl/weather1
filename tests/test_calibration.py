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
        this list must stay the 5 gate-backed families only. Verified as
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
