# Model Signal Calibration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Sharpen the edge signal and blend weights by (1) discounting edge for far-out markets, (2) storing per-source probabilities, and (3) enabling data-driven seasonal and per-city blend weight calibration.

**Architecture:** Three focused changes — a new `edge_confidence()` multiplier wired into `analyze_trade()`, a schema migration + `log_prediction()` update to capture per-source probs, and a new `calibration.py` module with offline grid-search plus a `python main.py calibrate` CLI command that updates `data/seasonal_weights.json` and `data/city_weights.json`. `_blend_weights()` gains a priority lookup: city weights → seasonal weights → hardcoded fallback.

**Tech Stack:** Python 3.11, SQLite (via tracker.py), pytest, json, itertools

---

### Task 1: `edge_confidence()` function

**Files:**
- Modify: `weather_markets.py` (add function near other Kelly/edge helpers)
- Modify: `tests/test_weather_markets.py` (append 3 tests)

- [ ] **Step 1: Write failing tests** — append to `tests/test_weather_markets.py`:

```python
# ── TestEdgeConfidence ────────────────────────────────────────────────────────


class TestEdgeConfidence:
    """Tests for edge_confidence(days_out) horizon discount factor."""

    def test_day_0_returns_one(self):
        from weather_markets import edge_confidence
        assert edge_confidence(0) == pytest.approx(1.0)

    def test_day_2_returns_one(self):
        from weather_markets import edge_confidence
        assert edge_confidence(2) == pytest.approx(1.0)

    def test_day_14_returns_0_60(self):
        from weather_markets import edge_confidence
        assert edge_confidence(14) == pytest.approx(0.60, abs=1e-6)

    def test_floor_at_day_20(self):
        from weather_markets import edge_confidence
        assert edge_confidence(20) == pytest.approx(0.60, abs=1e-6)
        assert edge_confidence(100) == pytest.approx(0.60, abs=1e-6)

    def test_day_7_in_linear_segment(self):
        """days_out=7 is at the boundary of segment 2; should be 0.80."""
        from weather_markets import edge_confidence
        assert edge_confidence(7) == pytest.approx(0.80, abs=1e-4)

    def test_monotonically_decreasing(self):
        from weather_markets import edge_confidence
        values = [edge_confidence(d) for d in range(0, 20)]
        for i in range(len(values) - 1):
            assert values[i] >= values[i + 1], (
                f"Not monotone at day {i}: {values[i]} > {values[i+1]}"
            )
```

- [ ] **Step 2: Run tests — expect FAIL**

```
cd "C:/Users/thesa/claude kalshi" && python -m pytest tests/test_weather_markets.py -k "TestEdgeConfidence" -x -v
```

Expected: `ImportError` or `AttributeError` — `edge_confidence` not defined.

- [ ] **Step 3: Implement `edge_confidence` in `weather_markets.py`**

Find the `kelly_fraction` function (around line 1397). Add this function immediately before it:

```python
def edge_confidence(days_out: int) -> float:
    """Horizon discount factor for edge signal (#63).

    Far-out markets are noisier; this multiplier reduces effective edge used
    for go/no-go decisions without touching Kelly size (which has its own
    time_kelly_scale). Floor of 0.60 so strong far-out edges still pass MIN_EDGE.

    Piecewise linear:
      days_out 0–2  : 1.00  (full confidence)
      days_out 3–7  : linear 1.00 → 0.80
      days_out 8–14 : linear 0.80 → 0.60
      days_out > 14 : 0.60  (floor)
    """
    if days_out <= 2:
        return 1.0
    if days_out <= 7:
        return 1.0 - (days_out - 2) / 5.0 * 0.20
    if days_out <= 14:
        return 0.80 - (days_out - 7) / 7.0 * 0.20
    return 0.60
```

- [ ] **Step 4: Run tests — expect PASS**

```
cd "C:/Users/thesa/claude kalshi" && python -m pytest tests/test_weather_markets.py -k "TestEdgeConfidence" -x -v
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```
cd "C:/Users/thesa/claude kalshi" && git add weather_markets.py tests/test_weather_markets.py && git commit -m "feat: add edge_confidence() horizon discount for edge signal (#63)"
```

---

### Task 2: Wire `edge_confidence` into `analyze_trade()`

**Files:**
- Modify: `weather_markets.py` (update `analyze_trade()` return dict and net_edge comparison)
- Modify: `tests/test_weather_markets.py` (append 1 test)

**Context:** `analyze_trade()` already computes `net_edge` and uses it for `net_signal`. We multiply `net_edge` by `edge_confidence(days_out)` to get `adjusted_edge`, which replaces `net_edge` in the MIN_EDGE comparison and go/no-go signal. Both values are returned so the dashboard can show both.

In `analyze_trade()`, the `net_edge` variable is computed and used around lines 2030–2070. The `days_out` variable is set earlier at line ~1815.

- [ ] **Step 1: Write failing test** — append to `tests/test_weather_markets.py`:

```python
# ── TestAdjustedEdgeInAnalyzeTrade ────────────────────────────────────────────


class TestAdjustedEdgeInAnalyzeTrade:
    """analyze_trade() must return both raw net_edge and adjusted_edge (#63)."""

    def test_analyze_trade_returns_adjusted_edge_key(self, monkeypatch):
        """Result dict must contain adjusted_edge and edge_confidence_factor."""
        import weather_markets as wm

        # Build a minimal enriched dict that can produce a result
        # Use a far-out market (days_out=10) to verify discount is applied
        from datetime import date, timedelta
        target = date.today() + timedelta(days=10)
        ticker = f"KXHIGHNYC-{target.strftime('%y%b%d').upper()}-T70"

        enriched = {
            "_city": "NYC",
            "_date": target,
            "_hour": 14,
            "_forecast": {"temps": [72.0] * 50, "source": "ensemble"},
            "yes_bid": 0.35,
            "yes_ask": 0.37,
            "ticker": ticker,
            "title": "NYC High above 70",
            "close_time": "",
        }

        # Patch heavy external calls so test is fast
        monkeypatch.setattr(wm, "get_nws_forecast_prob", lambda *a, **kw: None)
        monkeypatch.setattr(wm, "climatological_prob", lambda *a, **kw: 0.50)
        monkeypatch.setattr(wm, "_get_bias", lambda *a, **kw: 0.0)

        result = wm.analyze_trade(enriched)
        if result is None:
            pytest.skip("analyze_trade returned None for this enriched dict")
        assert "adjusted_edge" in result, "Missing adjusted_edge key"
        assert "edge_confidence_factor" in result, "Missing edge_confidence_factor key"
        # 10 days out → confidence = 0.80 - (10-7)/7*0.20 ≈ 0.714
        assert result["edge_confidence_factor"] == pytest.approx(
            wm.edge_confidence(10), abs=1e-6
        )
```

- [ ] **Step 2: Run test — expect FAIL**

```
cd "C:/Users/thesa/claude kalshi" && python -m pytest tests/test_weather_markets.py -k "TestAdjustedEdgeInAnalyzeTrade" -x -v
```

Expected: `AssertionError` — keys not in result.

- [ ] **Step 3: Update `analyze_trade()` return dict**

In `analyze_trade()`, find the line where `net_signal` is assigned (it uses `net_edge`). This is around line 2028. The pattern looks like:

```python
net_signal = "BUY YES" if net_edge >= MIN_EDGE else ("BUY NO" if -net_edge >= MIN_EDGE else "HOLD")
```

Replace that block with:

```python
_edge_conf = edge_confidence(days_out)
adjusted_edge = net_edge * _edge_conf
net_signal = (
    "BUY YES" if adjusted_edge >= MIN_EDGE
    else ("BUY NO" if -adjusted_edge >= MIN_EDGE else "HOLD")
)
```

Then in the return dict (around line 2089), add two new keys after `"net_edge": net_edge,`:

```python
        "net_edge": net_edge,
        "adjusted_edge": round(adjusted_edge, 6),
        "edge_confidence_factor": round(_edge_conf, 4),
```

- [ ] **Step 4: Run test — expect PASS**

```
cd "C:/Users/thesa/claude kalshi" && python -m pytest tests/test_weather_markets.py -k "TestAdjustedEdgeInAnalyzeTrade" -x -v
```

- [ ] **Step 5: Run full suite — confirm no regressions**

```
cd "C:/Users/thesa/claude kalshi" && python -m pytest --ignore=tests/test_http.py -q 2>&1 | tail -5
```

Expected: 13 pre-existing failures in test_paper.py unchanged, everything else green.

- [ ] **Step 6: Commit**

```
cd "C:/Users/thesa/claude kalshi" && git add weather_markets.py tests/test_weather_markets.py && git commit -m "feat: wire edge_confidence into analyze_trade() adjusted_edge signal (#63)"
```

---

### Task 3: Schema migration v9 — per-source probability columns

**Files:**
- Modify: `tracker.py` (add migration, increment `_SCHEMA_VERSION`, update `log_prediction`)
- Modify: `tests/test_tracker.py` (append 2 tests)

**Context:** Current `_SCHEMA_VERSION = 8`. Add v9 migration adding three REAL columns to `predictions`. Update `log_prediction()` to accept and store them.

- [ ] **Step 1: Write failing tests** — append to `tests/test_tracker.py`:

```python
# ── TestPerSourceProbColumns (#118/#122 prerequisite) ────────────────────────


class TestPerSourceProbColumns(unittest.TestCase):
    """Schema v9 must add ensemble_prob, nws_prob, clim_prob to predictions."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._orig = tracker.DB_PATH
        tracker.DB_PATH = Path(self._tmpdir) / "test_v9.db"
        tracker._db_initialized = False

    def tearDown(self):
        tracker.DB_PATH = self._orig
        tracker._db_initialized = False
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_columns_exist_after_init(self):
        """After init_db(), predictions table must have ensemble_prob, nws_prob, clim_prob."""
        import sqlite3
        tracker.init_db()
        with sqlite3.connect(str(tracker.DB_PATH)) as con:
            cols = {row[1] for row in con.execute("PRAGMA table_info(predictions)")}
        self.assertIn("ensemble_prob", cols)
        self.assertIn("nws_prob", cols)
        self.assertIn("clim_prob", cols)

    def test_log_prediction_stores_source_probs(self):
        """log_prediction with source probs stores them retrievable from DB."""
        import sqlite3
        from datetime import date as _date
        tracker.init_db()
        tracker.log_prediction(
            "SRCPROB-TEST",
            "NYC",
            _date(2026, 5, 1),
            {
                "forecast_prob": 0.65,
                "market_prob": 0.50,
                "edge": 0.15,
                "method": "ensemble",
                "n_members": 50,
                "condition": {"type": "above", "threshold": 70.0},
            },
            ensemble_prob=0.68,
            nws_prob=0.60,
            clim_prob=0.55,
        )
        with sqlite3.connect(str(tracker.DB_PATH)) as con:
            row = con.execute(
                "SELECT ensemble_prob, nws_prob, clim_prob FROM predictions WHERE ticker=?",
                ("SRCPROB-TEST",),
            ).fetchone()
        self.assertIsNotNone(row)
        self.assertAlmostEqual(row[0], 0.68, places=4)
        self.assertAlmostEqual(row[1], 0.60, places=4)
        self.assertAlmostEqual(row[2], 0.55, places=4)
```

- [ ] **Step 2: Run tests — expect FAIL**

```
cd "C:/Users/thesa/claude kalshi" && python -m pytest tests/test_tracker.py -k "TestPerSourceProbColumns" -x -v
```

Expected: columns don't exist, `log_prediction` doesn't accept keyword args.

- [ ] **Step 3: Add migration and update `tracker.py`**

**3a — Increment schema version and add migration.** In `tracker.py`, change line 24:

```python
_SCHEMA_VERSION = 9  # increment when _MIGRATIONS list grows
```

Append to `_MIGRATIONS` list (after the last existing migration):

```python
    # v8 → v9: per-source probabilities for blend weight calibration (#118/#122)
    "ALTER TABLE predictions ADD COLUMN ensemble_prob REAL",
    "ALTER TABLE predictions ADD COLUMN nws_prob REAL",
    "ALTER TABLE predictions ADD COLUMN clim_prob REAL",
```

**3b — Update `log_prediction` signature.** Change the function signature from:

```python
def log_prediction(
    ticker: str,
    city: str | None,
    market_date: date | None,
    analysis: dict,
    forecast_cycle: str | None = None,
    blend_sources: dict | None = None,
) -> None:
```

to:

```python
def log_prediction(
    ticker: str,
    city: str | None,
    market_date: date | None,
    analysis: dict,
    forecast_cycle: str | None = None,
    blend_sources: dict | None = None,
    ensemble_prob: float | None = None,
    nws_prob: float | None = None,
    clim_prob: float | None = None,
) -> None:
```

**3c — Update the UPDATE branch** inside `log_prediction`. Find:

```python
            con.execute(
                """
                UPDATE predictions SET
                    our_prob=?, raw_prob=?, market_prob=?, edge=?, method=?, n_members=?,
                    days_out=?, forecast_cycle=?, blend_sources=?
                WHERE id=?
            """,
                (
                    forecast_prob,
                    raw_prob,
                    analysis.get("market_prob"),
                    analysis.get("edge"),
                    analysis.get("method"),
                    analysis.get("n_members"),
                    days_out,
                    forecast_cycle,
                    blend_sources_json,
                    existing["id"],
                ),
            )
```

Replace with:

```python
            con.execute(
                """
                UPDATE predictions SET
                    our_prob=?, raw_prob=?, market_prob=?, edge=?, method=?, n_members=?,
                    days_out=?, forecast_cycle=?, blend_sources=?,
                    ensemble_prob=?, nws_prob=?, clim_prob=?
                WHERE id=?
            """,
                (
                    forecast_prob,
                    raw_prob,
                    analysis.get("market_prob"),
                    analysis.get("edge"),
                    analysis.get("method"),
                    analysis.get("n_members"),
                    days_out,
                    forecast_cycle,
                    blend_sources_json,
                    ensemble_prob,
                    nws_prob,
                    clim_prob,
                    existing["id"],
                ),
            )
```

**3d — Update the INSERT branch** inside `log_prediction`. Find:

```python
            con.execute(
                """
                INSERT INTO predictions
                  (ticker, city, market_date, condition_type,
                   threshold_lo, threshold_hi, our_prob, raw_prob, market_prob,
                   edge, method, n_members, predicted_at, days_out, forecast_cycle,
                   blend_sources)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'),?,?,?)
            """,
                (
                    ticker,
                    city,
                    market_date.isoformat() if market_date else None,
                    cond.get("type"),
                    lo,
                    hi,
                    forecast_prob,
                    raw_prob,
                    analysis.get("market_prob"),
                    analysis.get("edge"),
                    analysis.get("method"),
                    analysis.get("n_members"),
                    days_out,
                    forecast_cycle,
                    blend_sources_json,
                ),
            )
```

Replace with:

```python
            con.execute(
                """
                INSERT INTO predictions
                  (ticker, city, market_date, condition_type,
                   threshold_lo, threshold_hi, our_prob, raw_prob, market_prob,
                   edge, method, n_members, predicted_at, days_out, forecast_cycle,
                   blend_sources, ensemble_prob, nws_prob, clim_prob)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'),?,?,?,?,?,?)
            """,
                (
                    ticker,
                    city,
                    market_date.isoformat() if market_date else None,
                    cond.get("type"),
                    lo,
                    hi,
                    forecast_prob,
                    raw_prob,
                    analysis.get("market_prob"),
                    analysis.get("edge"),
                    analysis.get("method"),
                    analysis.get("n_members"),
                    days_out,
                    forecast_cycle,
                    blend_sources_json,
                    ensemble_prob,
                    nws_prob,
                    clim_prob,
                ),
            )
```

- [ ] **Step 4: Run tests — expect PASS**

```
cd "C:/Users/thesa/claude kalshi" && python -m pytest tests/test_tracker.py -k "TestPerSourceProbColumns" -x -v
```

Expected: 2 passed.

- [ ] **Step 5: Run full suite**

```
cd "C:/Users/thesa/claude kalshi" && python -m pytest --ignore=tests/test_http.py -q 2>&1 | tail -5
```

Expected: 13 pre-existing failures unchanged, everything else green.

- [ ] **Step 6: Commit**

```
cd "C:/Users/thesa/claude kalshi" && git add tracker.py tests/test_tracker.py && git commit -m "feat: schema v9 adds ensemble_prob/nws_prob/clim_prob to predictions (#118 #122)"
```

---

### Task 4: Pass per-source probs from `analyze_trade()` through to `log_prediction()`

**Files:**
- Modify: `weather_markets.py` (update `analyze_trade()` return dict — already has the values)
- Modify: `main.py` (find where `log_prediction` is called; pass through new fields)

**Context:** `analyze_trade()` already returns `ensemble_prob`, `nws_prob`, and `clim_prob` in its result dict. They just aren't forwarded to `tracker.log_prediction()`. We need to find the call site and wire them through.

- [ ] **Step 1: Find the `log_prediction` call site**

```
cd "C:/Users/thesa/claude kalshi" && grep -rn "log_prediction" --include="*.py" | grep -v "test_\|#\|def log_prediction"
```

Note the file and line number(s) returned. There will be one or two call sites in `main.py` or a helper module.

- [ ] **Step 2: Write failing test** — append to `tests/test_tracker.py`:

```python
# ── TestSourceProbsPassthrough ────────────────────────────────────────────────


class TestSourceProbsPassthrough(unittest.TestCase):
    """log_prediction called without source probs must store NULLs (backward compat)."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._orig = tracker.DB_PATH
        tracker.DB_PATH = Path(self._tmpdir) / "test_passthrough.db"
        tracker._db_initialized = False

    def tearDown(self):
        tracker.DB_PATH = self._orig
        tracker._db_initialized = False
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_missing_source_probs_stored_as_null(self):
        """Calling log_prediction without source probs stores NULL (old callers safe)."""
        import sqlite3
        from datetime import date as _date
        tracker.init_db()
        tracker.log_prediction(
            "NULL-SRCPROB",
            "NYC",
            _date(2026, 5, 2),
            {
                "forecast_prob": 0.60,
                "market_prob": 0.50,
                "edge": 0.10,
                "method": "ensemble",
                "n_members": 30,
                "condition": {"type": "above", "threshold": 70.0},
            },
        )
        with sqlite3.connect(str(tracker.DB_PATH)) as con:
            row = con.execute(
                "SELECT ensemble_prob, nws_prob, clim_prob FROM predictions WHERE ticker=?",
                ("NULL-SRCPROB",),
            ).fetchone()
        self.assertIsNotNone(row)
        self.assertIsNone(row[0])
        self.assertIsNone(row[1])
        self.assertIsNone(row[2])
```

- [ ] **Step 3: Run test — expect PASS immediately** (backward compat; NULLs are default)

```
cd "C:/Users/thesa/claude kalshi" && python -m pytest tests/test_tracker.py -k "TestSourceProbsPassthrough" -x -v
```

Expected: 1 passed (NULL default is free from Task 3).

- [ ] **Step 4: Update the `log_prediction` call site in `main.py`**

Find the call site from Step 1. It will look something like:

```python
tracker.log_prediction(ticker, city, market_date, analysis, forecast_cycle=cycle, blend_sources=blend)
```

Add the three new keyword arguments from the `analysis` dict:

```python
tracker.log_prediction(
    ticker,
    city,
    market_date,
    analysis,
    forecast_cycle=cycle,
    blend_sources=analysis.get("blend_sources"),
    ensemble_prob=analysis.get("ensemble_prob"),
    nws_prob=analysis.get("nws_prob"),
    clim_prob=analysis.get("clim_prob"),
)
```

Note: if `blend_sources` was already being pulled from `analysis.get("blend_sources")`, keep it as-is and just add the three new lines.

- [ ] **Step 5: Run full suite**

```
cd "C:/Users/thesa/claude kalshi" && python -m pytest --ignore=tests/test_http.py -q 2>&1 | tail -5
```

- [ ] **Step 6: Commit**

```
cd "C:/Users/thesa/claude kalshi" && git add main.py tests/test_tracker.py && git commit -m "feat: forward ensemble_prob/nws_prob/clim_prob from analyze_trade to log_prediction (#118 #122)"
```

---

### Task 5: `calibration.py` — grid-search and loaders

**Files:**
- Create: `calibration.py`
- Create: `tests/test_calibration.py`

**Context:** Grid-searches `(w_ensemble, w_clim, w_nws)` triples summing to 1.0 in 0.05 steps (10 values per weight × constrained = 66 unique triples) against settled predictions that have all three per-source probs populated. Minimizes Brier score per season/city.

- [ ] **Step 1: Write failing tests** — create `tests/test_calibration.py`:

```python
"""Tests for calibration.py — seasonal and per-city blend weight calibration."""
import shutil
import sqlite3
import tempfile
from datetime import date, datetime
from pathlib import Path

import pytest


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
                    r["ticker"], r["city"], r["market_date"], "above",
                    r["our_prob"], 0.5, 0.1, "ensemble", 50,
                    datetime.now().isoformat(), 3,
                    r["ensemble_prob"], r["nws_prob"], r["clim_prob"],
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
        rows.append({
            "ticker": f"{base_ticker}-{i}",
            "city": "NYC",
            "market_date": f"2026-01-{(i % 28) + 1:02d}",
            "our_prob": 0.7 if settled else 0.3,
            "ensemble_prob": 0.72,
            "nws_prob": 0.65,
            "clim_prob": 0.60,
            "settled_yes": settled,
        })
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
        # Null out source probs for half
        for r in rows[:35]:
            r["ensemble_prob"] = None
            r["nws_prob"] = None
            r["clim_prob"] = None
        _seed_db(self._db, rows)
        result = calibrate_seasonal_weights(self._db)
        # Only 25 rows have source probs, below threshold of 50
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
```

- [ ] **Step 2: Run tests — expect FAIL**

```
cd "C:/Users/thesa/claude kalshi" && python -m pytest tests/test_calibration.py -x -v
```

Expected: `ModuleNotFoundError: No module named 'calibration'`.

- [ ] **Step 3: Create `calibration.py`**

Create `C:/Users/thesa/claude kalshi/calibration.py`:

```python
"""Offline blend-weight calibration for seasonal and per-city model optimization.

Run: python main.py calibrate
Outputs: data/seasonal_weights.json, data/city_weights.json
"""
from __future__ import annotations

import itertools
import json
import logging
import sqlite3
from pathlib import Path

_log = logging.getLogger(__name__)

_SEASONAL_MIN = 50   # minimum settled predictions with source probs per season
_CITY_MIN = 30       # minimum settled predictions with source probs per city
_WEIGHT_STEP = 0.05  # grid resolution; 0.05 → 66 unique (w_e, w_c, w_n) triples

# Month → season mapping
_MONTH_TO_SEASON: dict[int, str] = {
    12: "winter", 1: "winter", 2: "winter",
    3: "spring", 4: "spring", 5: "spring",
    6: "summer", 7: "summer", 8: "summer",
    9: "fall", 10: "fall", 11: "fall",
}

_WEIGHT_VALUES = [round(i * _WEIGHT_STEP, 10) for i in range(int(1 / _WEIGHT_STEP) + 1)]
_WEIGHT_TRIPLES = [
    (e, c, n)
    for e, c, n in itertools.product(_WEIGHT_VALUES, repeat=3)
    if abs(e + c + n - 1.0) < 1e-9
]


def _brier(rows: list[tuple[float, float, float, int]], we: float, wc: float, wn: float) -> float:
    """Compute Brier score for a weight combo against a list of (ens, clim, nws, settled)."""
    total = 0.0
    for ens, clim, nws, settled in rows:
        p = we * ens + wc * clim + wn * nws
        total += (p - settled) ** 2
    return total / len(rows)


def _best_weights(rows: list[tuple[float, float, float, int]]) -> dict[str, float]:
    """Grid-search weight triples; return the one minimizing Brier score."""
    best_score = float("inf")
    best = (1 / 3, 1 / 3, 1 / 3)
    for we, wc, wn in _WEIGHT_TRIPLES:
        score = _brier(rows, we, wc, wn)
        if score < best_score:
            best_score = score
            best = (we, wc, wn)
    return {"ensemble": best[0], "climatology": best[1], "nws": best[2]}


def _load_rows(db_path: Path) -> list[dict]:
    """Load settled predictions that have all three per-source probs populated."""
    with sqlite3.connect(str(db_path)) as con:
        con.row_factory = sqlite3.Row
        return con.execute(
            """
            SELECT p.city, p.market_date,
                   p.ensemble_prob, p.nws_prob, p.clim_prob,
                   o.settled_yes
            FROM predictions p
            JOIN outcomes o ON p.ticker = o.ticker
            WHERE p.ensemble_prob IS NOT NULL
              AND p.nws_prob IS NOT NULL
              AND p.clim_prob IS NOT NULL
              AND o.settled_yes IS NOT NULL
            """
        ).fetchall()


def calibrate_seasonal_weights(db_path: str | Path) -> dict[str, dict[str, float]]:
    """Grid-search optimal blend weights per season from settled predictions.

    Returns: {season: {ensemble, climatology, nws}} for seasons with >= _SEASONAL_MIN rows.
    Seasons below threshold are omitted (caller falls back to hardcoded defaults).
    """
    db_path = Path(db_path)
    rows = _load_rows(db_path)

    season_rows: dict[str, list[tuple[float, float, float, int]]] = {}
    for row in rows:
        try:
            month = int(str(row["market_date"])[5:7])
        except (TypeError, ValueError):
            continue
        season = _MONTH_TO_SEASON.get(month)
        if season is None:
            continue
        season_rows.setdefault(season, []).append(
            (row["ensemble_prob"], row["clim_prob"], row["nws_prob"], row["settled_yes"])
        )

    result: dict[str, dict[str, float]] = {}
    for season, srows in season_rows.items():
        if len(srows) < _SEASONAL_MIN:
            _log.info(
                "calibrate_seasonal_weights: %s has %d rows (need %d) — skipping",
                season, len(srows), _SEASONAL_MIN,
            )
            continue
        result[season] = _best_weights(srows)
        _log.info("calibrate_seasonal_weights: %s → %s (n=%d)", season, result[season], len(srows))
    return result


def calibrate_city_weights(db_path: str | Path) -> dict[str, dict[str, float]]:
    """Grid-search optimal blend weights per city from settled predictions.

    Returns: {city: {ensemble, climatology, nws}} for cities with >= _CITY_MIN rows.
    """
    db_path = Path(db_path)
    rows = _load_rows(db_path)

    city_rows: dict[str, list[tuple[float, float, float, int]]] = {}
    for row in rows:
        city = row["city"]
        if not city:
            continue
        city_rows.setdefault(city, []).append(
            (row["ensemble_prob"], row["clim_prob"], row["nws_prob"], row["settled_yes"])
        )

    result: dict[str, dict[str, float]] = {}
    for city, crows in city_rows.items():
        if len(crows) < _CITY_MIN:
            _log.info(
                "calibrate_city_weights: %s has %d rows (need %d) — skipping",
                city, len(crows), _CITY_MIN,
            )
            continue
        result[city] = _best_weights(crows)
        _log.info("calibrate_city_weights: %s → %s (n=%d)", city, result[city], len(crows))
    return result


def load_seasonal_weights(path: str | Path | None = None) -> dict[str, dict[str, float]]:
    """Load seasonal weights from JSON. Returns {} if file missing."""
    p = Path(path) if path else Path(__file__).parent / "data" / "seasonal_weights.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except Exception as exc:
        _log.debug("load_seasonal_weights: could not read %s: %s", p, exc)
        return {}


def load_city_weights(path: str | Path | None = None) -> dict[str, dict[str, float]]:
    """Load per-city weights from JSON. Returns {} if file missing."""
    p = Path(path) if path else Path(__file__).parent / "data" / "city_weights.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except Exception as exc:
        _log.debug("load_city_weights: could not read %s: %s", p, exc)
        return {}
```

- [ ] **Step 4: Run tests — expect PASS**

```
cd "C:/Users/thesa/claude kalshi" && python -m pytest tests/test_calibration.py -x -v
```

Expected: 5 passed.

- [ ] **Step 5: Run full suite**

```
cd "C:/Users/thesa/claude kalshi" && python -m pytest --ignore=tests/test_http.py -q 2>&1 | tail -5
```

- [ ] **Step 6: Commit**

```
cd "C:/Users/thesa/claude kalshi" && git add calibration.py tests/test_calibration.py && git commit -m "feat: add calibration.py with grid-search seasonal and city blend weights (#118 #122)"
```

---

### Task 6: Wire calibration into `_blend_weights()`

**Files:**
- Modify: `weather_markets.py` (module-level calibration load, updated `_blend_weights()`)

**Context:** Load calibration data once at module level. Update `_blend_weights()` to accept `city` and `season` params and consult the loaded dicts before falling back to the hardcoded schedule. The existing `_confidence_scaled_blend_weights()` caller passes `days_out, has_nws, has_clim` — extend that to also pass `city` and `season`.

- [ ] **Step 1: Write failing test** — append to `tests/test_weather_markets.py`:

```python
# ── TestBlendWeightCalibrationPriority ───────────────────────────────────────


class TestBlendWeightCalibrationPriority:
    """_blend_weights() must use city weights > seasonal weights > hardcoded."""

    def test_city_weights_override_hardcoded(self, monkeypatch):
        """If city weights loaded, _blend_weights returns them regardless of days_out."""
        import weather_markets as wm

        city_weights = {"NYC": {"ensemble": 0.50, "climatology": 0.10, "nws": 0.40}}
        monkeypatch.setattr(wm, "_CITY_WEIGHTS", city_weights)
        monkeypatch.setattr(wm, "_SEASONAL_WEIGHTS", {})

        w_ens, w_clim, w_nws = wm._blend_weights(
            days_out=5, has_nws=True, has_clim=True, city="NYC", season="spring"
        )
        assert w_ens == pytest.approx(0.50, abs=1e-6)
        assert w_nws == pytest.approx(0.40, abs=1e-6)

    def test_seasonal_weights_used_when_no_city_weights(self, monkeypatch):
        """If no city weights but seasonal weights loaded, use seasonal."""
        import weather_markets as wm

        monkeypatch.setattr(wm, "_CITY_WEIGHTS", {})
        monkeypatch.setattr(wm, "_SEASONAL_WEIGHTS", {
            "spring": {"ensemble": 0.45, "climatology": 0.20, "nws": 0.35}
        })

        w_ens, w_clim, w_nws = wm._blend_weights(
            days_out=5, has_nws=True, has_clim=True, city="NYC", season="spring"
        )
        assert w_ens == pytest.approx(0.45, abs=1e-6)
        assert w_nws == pytest.approx(0.35, abs=1e-6)

    def test_fallback_to_hardcoded_when_no_calibration(self, monkeypatch):
        """With empty dicts, result should match original hardcoded schedule."""
        import weather_markets as wm

        monkeypatch.setattr(wm, "_CITY_WEIGHTS", {})
        monkeypatch.setattr(wm, "_SEASONAL_WEIGHTS", {})

        # days_out=5, hardcoded: w_nws=0.25, remainder split ensemble/clim
        w_ens, w_clim, w_nws = wm._blend_weights(
            days_out=5, has_nws=True, has_clim=True, city="NYC", season="spring"
        )
        assert abs(w_ens + w_clim + w_nws - 1.0) < 1e-6
        assert w_nws == pytest.approx(0.25, abs=1e-6)
```

- [ ] **Step 2: Run tests — expect FAIL**

```
cd "C:/Users/thesa/claude kalshi" && python -m pytest tests/test_weather_markets.py -k "TestBlendWeightCalibrationPriority" -x -v
```

Expected: `AttributeError` — `_CITY_WEIGHTS` not defined, `_blend_weights` doesn't accept `city`/`season`.

- [ ] **Step 3: Update `weather_markets.py`**

**3a — Add module-level calibration load** near the top of the file (after other module-level constants, before the first function definition):

```python
# ── Calibration data (loaded once at import; empty dicts = use hardcoded weights) ──
from calibration import load_city_weights as _load_city_weights
from calibration import load_seasonal_weights as _load_seasonal_weights

_CITY_WEIGHTS: dict[str, dict[str, float]] = _load_city_weights()
_SEASONAL_WEIGHTS: dict[str, dict[str, float]] = _load_seasonal_weights()
```

**3b — Update `_blend_weights()` signature and body**. Find the current function:

```python
def _blend_weights(
    days_out: int, has_nws: bool, has_clim: bool
) -> tuple[float, float, float]:
```

Replace the entire function with:

```python
def _blend_weights(
    days_out: int,
    has_nws: bool,
    has_clim: bool,
    city: str | None = None,
    season: str | None = None,
) -> tuple[float, float, float]:
    """Return (w_ensemble, w_climatology, w_nws).

    Priority: city-specific calibration > seasonal calibration > hardcoded schedule.
    """
    # 1. City-specific calibration weights
    if city and city in _CITY_WEIGHTS:
        cal = _CITY_WEIGHTS[city]
        w_ens = cal["ensemble"]
        w_clim = cal["climatology"]
        w_nws = cal["nws"]
        if not has_nws:
            w_ens += w_nws * 0.6
            w_clim += w_nws * 0.4
            w_nws = 0.0
        if not has_clim:
            w_ens += w_clim
            w_clim = 0.0
        total = w_ens + w_clim + w_nws
        return w_ens / total, w_clim / total, w_nws / total

    # 2. Seasonal calibration weights
    if season and season in _SEASONAL_WEIGHTS:
        cal = _SEASONAL_WEIGHTS[season]
        w_ens = cal["ensemble"]
        w_clim = cal["climatology"]
        w_nws = cal["nws"]
        if not has_nws:
            w_ens += w_nws * 0.6
            w_clim += w_nws * 0.4
            w_nws = 0.0
        if not has_clim:
            w_ens += w_clim
            w_clim = 0.0
        total = w_ens + w_clim + w_nws
        return w_ens / total, w_clim / total, w_nws / total

    # 3. Hardcoded schedule (original logic)
    if days_out <= 3:
        w_nws = 0.35
    elif days_out <= 7:
        w_nws = 0.25
    else:
        w_nws = 0.10

    w_rem = 1.0 - w_nws
    if days_out <= 1:
        w_ens = w_rem * 0.94
        w_clim = w_rem * 0.06
    elif days_out <= 3:
        w_ens = w_rem * 0.87
        w_clim = w_rem * 0.13
    elif days_out <= 5:
        w_ens = w_rem * 0.69
        w_clim = w_rem * 0.31
    elif days_out <= 7:
        w_ens = w_rem * 0.53
        w_clim = w_rem * 0.47
    elif days_out <= 10:
        w_ens = w_rem * 0.26
        w_clim = w_rem * 0.74
    else:
        w_ens = w_rem * 0.13
        w_clim = w_rem * 0.87

    if not has_nws:
        w_ens += w_nws * 0.6
        w_clim += w_nws * 0.4
        w_nws = 0.0
    if not has_clim:
        w_ens += w_clim
        w_clim = 0.0

    total = w_ens + w_clim + w_nws
    return w_ens / total, w_clim / total, w_nws / total
```

**3c — Update the call to `_blend_weights`** inside `_confidence_scaled_blend_weights` (or wherever `_blend_weights` is called). Find:

```python
w_ens, w_clim, w_nws = _blend_weights(days_out, has_nws, has_clim)
```

The `analyze_trade()` function has `city` and `target_date` in scope. Compute season from target_date and pass both:

```python
import calendar as _cal
_month = target_date.month if target_date else datetime.now().month
_season = {12: "winter", 1: "winter", 2: "winter",
           3: "spring", 4: "spring", 5: "spring",
           6: "summer", 7: "summer", 8: "summer",
           9: "fall", 10: "fall", 11: "fall"}.get(_month, "spring")
w_ens, w_clim, w_nws = _blend_weights(days_out, has_nws, has_clim, city=city, season=_season)
```

Note: if `_blend_weights` is called from within `_confidence_scaled_blend_weights`, look at that function too and pass the city/season through its own signature if needed.

- [ ] **Step 4: Run tests — expect PASS**

```
cd "C:/Users/thesa/claude kalshi" && python -m pytest tests/test_weather_markets.py -k "TestBlendWeightCalibrationPriority" -x -v
```

Expected: 3 passed.

- [ ] **Step 5: Run full suite**

```
cd "C:/Users/thesa/claude kalshi" && python -m pytest --ignore=tests/test_http.py -q 2>&1 | tail -5
```

Expected: 13 pre-existing failures unchanged.

- [ ] **Step 6: Commit**

```
cd "C:/Users/thesa/claude kalshi" && git add weather_markets.py tests/test_weather_markets.py && git commit -m "feat: wire calibrated blend weights into _blend_weights() with city/seasonal priority (#118 #122)"
```

---

### Task 7: `calibrate` CLI command in `main.py`

**Files:**
- Modify: `main.py` (add `cmd_calibrate()` function and `elif cmd == "calibrate":` dispatch)

- [ ] **Step 1: Write test** — append to `tests/test_calibration.py`:

```python
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
```

- [ ] **Step 2: Run test — expect PASS immediately** (just exercises existing calibration.py)

```
cd "C:/Users/thesa/claude kalshi" && python -m pytest tests/test_calibration.py -k "TestCalibrateCLI" -x -v
```

- [ ] **Step 3: Add `cmd_calibrate()` to `main.py`**

Find a good location in `main.py` (near `cmd_backtest` or `cmd_report`). Add:

```python
def cmd_calibrate() -> None:
    """Recompute seasonal and per-city blend weights from settled predictions."""
    import json
    from pathlib import Path

    from calibration import calibrate_city_weights, calibrate_seasonal_weights
    from tracker import DB_PATH

    data_dir = Path(__file__).parent / "data"
    data_dir.mkdir(exist_ok=True)

    print("Running blend-weight calibration from settled predictions…")
    print(f"  Database: {DB_PATH}")

    seasonal = calibrate_seasonal_weights(DB_PATH)
    city = calibrate_city_weights(DB_PATH)

    seasonal_path = data_dir / "seasonal_weights.json"
    city_path = data_dir / "city_weights.json"

    seasonal_path.write_text(json.dumps(seasonal, indent=2))
    city_path.write_text(json.dumps(city, indent=2))

    if seasonal:
        print(f"\nSeasonal weights ({len(seasonal)} seasons calibrated):")
        for season, w in sorted(seasonal.items()):
            print(f"  {season:8s}: ensemble={w['ensemble']:.2f}  clim={w['climatology']:.2f}  nws={w['nws']:.2f}")
    else:
        print("\nSeasonal weights: insufficient data for all seasons — using hardcoded defaults.")

    if city:
        print(f"\nCity weights ({len(city)} cities calibrated):")
        for c, w in sorted(city.items()):
            print(f"  {c:12s}: ensemble={w['ensemble']:.2f}  clim={w['climatology']:.2f}  nws={w['nws']:.2f}")
    else:
        print("\nCity weights: insufficient data for any city — using defaults.")

    print(f"\nWritten to: {seasonal_path}")
    print(f"           {city_path}")
    print("Restart the app (or re-import weather_markets) to pick up new weights.")
```

- [ ] **Step 4: Add dispatch branch** in `main()`. Find the elif chain and add after `elif cmd == "backtest":`:

```python
    elif cmd == "calibrate":
        cmd_calibrate()
```

- [ ] **Step 5: Smoke-test the command**

```
cd "C:/Users/thesa/claude kalshi" && python main.py calibrate
```

Expected output: "Running blend-weight calibration…" followed by either calibrated weights or "insufficient data" messages. No crash.

- [ ] **Step 6: Run full suite**

```
cd "C:/Users/thesa/claude kalshi" && python -m pytest --ignore=tests/test_http.py -q 2>&1 | tail -5
```

Expected: 13 pre-existing failures unchanged.

- [ ] **Step 7: Commit**

```
cd "C:/Users/thesa/claude kalshi" && git add main.py tests/test_calibration.py && git commit -m "feat: add 'python main.py calibrate' CLI command for blend weight calibration (#118 #122)"
```

---

## Self-Review

**Spec coverage:**
- ✅ #63 edge_confidence: Tasks 1–2
- ✅ #118 seasonal weights: Tasks 3 (schema prereq), 5 (grid search), 6 (wire in), 7 (CLI)
- ✅ #122 city weights: Tasks 3 (schema prereq), 5 (grid search), 6 (wire in), 7 (CLI)
- ✅ Schema migration v9: Task 3
- ✅ Fallback to hardcoded: Task 6 (Step 3 hardcoded block preserved)
- ✅ `python main.py calibrate`: Task 7
- ✅ Data stored in `data/seasonal_weights.json` and `data/city_weights.json`: Task 7

**Placeholder scan:** None found.

**Type consistency:**
- `_blend_weights()` signature extended with `city: str | None = None, season: str | None = None` — all call sites pass these or leave them at default (backward-safe).
- `log_prediction()` new params `ensemble_prob`, `nws_prob`, `clim_prob` all `float | None = None` — all existing callers work unchanged.
- `calibrate_seasonal_weights()` / `calibrate_city_weights()` return `dict[str, dict[str, float]]` — consistent with `load_seasonal_weights()` / `load_city_weights()` return types and `_SEASONAL_WEIGHTS` / `_CITY_WEIGHTS` module-level dicts.
