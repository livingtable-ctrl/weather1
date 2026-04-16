# P6: Data Engineering Hardening — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden the data layer: validate Kalshi API responses before they touch the decision engine, log per-source SLA metrics, and snapshot forecast data for trade replay.

**What already exists — do NOT re-add:**
- `nws.py`, `climatology.py` — data sources each with `CircuitBreaker`
- `circuit_breaker.py: CircuitBreaker` — CLOSED/OPEN/HALF-OPEN state machine
- `tracker.py` — versioned SQLite schema v9 with `_run_migrations`
- `paper.py: _validate_crc`, `_validate_checksum` — CRC32 + SHA-256 on paper trades
- `weather_markets.py: FORECAST_MAX_AGE_SECS` — freshness check in validation

**Architecture:** Three additive tasks, no existing code deleted. Schema validation lives in `kalshi_client.py`. SLA logging adds one new table to the tracker DB. Snapshots write flat JSON files.

**Tech Stack:** Python 3.11+, pytest, `monkeypatch`. No new dependencies.

---

## Task 20 (P6.2) — Kalshi API response schema validation

### 20.1 Add `validate_market_response` to `kalshi_client.py`

- [ ] Add after the imports:

```python
# Required fields and their expected Python types for a market response dict
_MARKET_REQUIRED_FIELDS: dict[str, type] = {
    "ticker": str,
    "status": str,
    "yes_bid": (int, float),
    "yes_ask": (int, float),
    "volume": (int, float),
    "open_interest": (int, float),
}


def validate_market_response(raw: dict) -> dict:
    """
    Validate a raw Kalshi market dict.

    Raises ValueError with a descriptive message if required fields are
    missing or have wrong types.  Returns the dict unchanged on success.
    """
    missing = [f for f in _MARKET_REQUIRED_FIELDS if f not in raw]
    if missing:
        raise ValueError(
            f"Kalshi market response missing required fields: {missing} "
            f"(ticker={raw.get('ticker', '?')})"
        )
    wrong_type = [
        f for f, t in _MARKET_REQUIRED_FIELDS.items()
        if not isinstance(raw.get(f), t)
    ]
    if wrong_type:
        raise ValueError(
            f"Kalshi market response has wrong-typed fields: {wrong_type} "
            f"(ticker={raw.get('ticker', '?')})"
        )
    return raw
```

### 20.2 Call `validate_market_response` in market fetch methods

- [ ] In `kalshi_client.py`, in the method that returns individual market dicts (e.g. `get_market`, `get_markets`), wrap each returned dict:
```python
    return validate_market_response(raw_market)
```
- [ ] Wrap the call in a try/except that logs a warning and skips the market rather than crashing the whole fetch:
```python
    try:
        yield validate_market_response(raw_market)
    except ValueError as _e:
        _log.warning("kalshi_client: skipping malformed market: %s", _e)
        continue
```

### 20.3 Write tests

- [ ] Create `tests/test_data_engineering.py`:

```python
"""Tests for P6: Data Engineering Hardening"""
from __future__ import annotations

import json
from pathlib import Path


class TestValidateMarketResponse:
    def _valid(self) -> dict:
        return {
            "ticker": "KXHIGH-25APR15-B70",
            "status": "active",
            "yes_bid": 0.48,
            "yes_ask": 0.52,
            "volume": 1000,
            "open_interest": 200,
        }

    def test_valid_dict_passes(self):
        from kalshi_client import validate_market_response
        result = validate_market_response(self._valid())
        assert result["ticker"] == "KXHIGH-25APR15-B70"

    def test_missing_field_raises(self):
        from kalshi_client import validate_market_response
        import pytest
        bad = self._valid()
        del bad["yes_bid"]
        with pytest.raises(ValueError, match="missing required fields"):
            validate_market_response(bad)

    def test_wrong_type_raises(self):
        from kalshi_client import validate_market_response
        import pytest
        bad = self._valid()
        bad["volume"] = "not-a-number"
        with pytest.raises(ValueError, match="wrong-typed fields"):
            validate_market_response(bad)

    def test_extra_fields_are_allowed(self):
        """Extra fields in the response should not cause failure."""
        from kalshi_client import validate_market_response
        extra = self._valid()
        extra["some_future_field"] = True
        result = validate_market_response(extra)
        assert result["some_future_field"] is True
```

### 20.4 Verify Task 20

- [ ] Run:
```
cd "C:\Users\thesa\claude kalshi" && python -m pytest tests/test_data_engineering.py::TestValidateMarketResponse -v
```
Expected: 4 passed.

### 20.5 Commit Task 20

```
git add kalshi_client.py tests/test_data_engineering.py
git commit -m "feat(p6.2): add Kalshi API response schema validation"
```

---

## Task 21 (P6.1) — Source SLA logging

### 21.1 Add `source_sla` table to `tracker.py`

- [ ] In `tracker.py`, add the migration:
```sql
CREATE TABLE IF NOT EXISTS source_sla (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    source     TEXT    NOT NULL,   -- "nws", "climatology", "ensemble"
    success    INTEGER NOT NULL,   -- 1 = success, 0 = failure
    latency_ms REAL,               -- round-trip ms
    logged_at  TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_source_sla_source ON source_sla(source, logged_at);
```
- [ ] Add the migration to `_run_migrations` in `tracker.py`.

### 21.2 Add `log_source_sla` and `get_source_sla_summary` to `tracker.py`

- [ ] Add:

```python
def log_source_sla(source: str, success: bool, latency_ms: float) -> None:
    """Record one data-source call result."""
    _init_db()
    with _conn() as con:
        con.execute(
            """
            INSERT INTO source_sla (source, success, latency_ms, logged_at)
            VALUES (?, ?, ?, ?)
            """,
            (source, int(success), latency_ms,
             __import__("datetime").datetime.now(
                 __import__("datetime").timezone.utc
             ).isoformat()),
        )


def get_source_sla_summary(since_hours: int = 24) -> dict:
    """
    Return per-source SLA summary for the last `since_hours` hours.

    Returns:
        {source: {calls, success_rate, avg_latency_ms, last_failure}}
    """
    _init_db()
    cutoff = (
        __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
        - __import__("datetime").timedelta(hours=since_hours)
    ).isoformat()
    with _conn() as con:
        rows = con.execute(
            """
            SELECT source,
                   COUNT(*) AS calls,
                   AVG(success) AS success_rate,
                   AVG(latency_ms) AS avg_latency_ms,
                   MAX(CASE WHEN success=0 THEN logged_at END) AS last_failure
            FROM source_sla
            WHERE logged_at >= ?
            GROUP BY source
            """,
            (cutoff,),
        ).fetchall()
    return {
        r["source"]: {
            "calls": r["calls"],
            "success_rate": round(r["success_rate"] or 0.0, 3),
            "avg_latency_ms": round(r["avg_latency_ms"] or 0.0, 1),
            "last_failure": r["last_failure"],
        }
        for r in rows
    }
```

### 21.3 Instrument source calls in `weather_markets.py`

- [ ] In the function(s) that call `nws.get_forecast` / `climatology.get_forecast`, wrap with timing:

```python
import time as _time
import tracker as _tracker

_t0 = _time.monotonic()
try:
    forecast = nws.get_forecast(city, date)
    _tracker.log_source_sla("nws", success=True,
                             latency_ms=(_time.monotonic() - _t0) * 1000)
except Exception as _e:
    _tracker.log_source_sla("nws", success=False,
                             latency_ms=(_time.monotonic() - _t0) * 1000)
    raise
```

### 21.4 Write tests

- [ ] Add to `tests/test_data_engineering.py`:

```python
class TestSourceSLA:
    def test_log_and_retrieve_sla(self, tmp_path, monkeypatch):
        """log_source_sla writes a row; get_source_sla_summary reads it back."""
        import tracker
        monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "tracker.db")
        monkeypatch.setattr(tracker, "_initialized", False)

        tracker.log_source_sla("nws", success=True, latency_ms=45.2)
        tracker.log_source_sla("nws", success=False, latency_ms=1200.0)
        tracker.log_source_sla("climatology", success=True, latency_ms=12.0)

        summary = tracker.get_source_sla_summary(since_hours=1)

        assert "nws" in summary
        assert summary["nws"]["calls"] == 2
        assert summary["nws"]["success_rate"] == 0.5
        assert summary["climatology"]["calls"] == 1
        assert summary["climatology"]["success_rate"] == 1.0

    def test_last_failure_is_recorded(self, tmp_path, monkeypatch):
        """last_failure is populated when a failure exists."""
        import tracker
        monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "tracker2.db")
        monkeypatch.setattr(tracker, "_initialized", False)

        tracker.log_source_sla("nws", success=False, latency_ms=999.0)
        summary = tracker.get_source_sla_summary(since_hours=1)
        assert summary["nws"]["last_failure"] is not None
```

### 21.5 Verify Task 21

- [ ] Run:
```
cd "C:\Users\thesa\claude kalshi" && python -m pytest tests/test_data_engineering.py::TestSourceSLA -v
```
Expected: 2 passed.

### 21.6 Add auto-pause when source reliability drops

The PDF specifies *"pause trading if data reliability drops"* — SLA logging alone is not enough.

- [ ] Add `is_data_source_degraded() -> bool` to `tracker.py`:

```python
def is_data_source_degraded(
    source: str = "nws",
    window_hours: int = 1,
    min_success_rate: float = 0.50,
    min_calls: int = 3,
) -> bool:
    """
    Return True if `source` success_rate < min_success_rate in the last window_hours.
    Requires at least min_calls to make a judgement (returns False if not enough data).
    """
    summary = get_source_sla_summary(since_hours=window_hours)
    entry = summary.get(source)
    if entry is None or entry["calls"] < min_calls:
        return False
    return entry["success_rate"] < min_success_rate
```

- [ ] In `_auto_place_trades` in `main.py`, add a guard after the kill switch check:

```python
    # P6.1 — pause if primary data source is degraded
    try:
        import tracker as _tracker_sla
        if _tracker_sla.is_data_source_degraded("nws"):
            _log.warning(
                "_auto_place_trades: NWS data source degraded — "
                "skipping trades to avoid stale-data decisions"
            )
            return 0
    except Exception:
        pass  # fail-open: don't block trading if SLA check itself fails
```

### 21.7 Write additional tests

- [ ] Add to `tests/test_data_engineering.py`:

```python
class TestDataSourceDegradation:
    def test_degraded_returns_true_when_low_success(self, tmp_path, monkeypatch):
        """Returns True when success_rate < threshold with enough calls."""
        import tracker
        monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "tracker.db")
        monkeypatch.setattr(tracker, "_initialized", False)

        # Log 4 failures, 1 success → 20% success rate
        for _ in range(4):
            tracker.log_source_sla("nws", success=False, latency_ms=999.0)
        tracker.log_source_sla("nws", success=True, latency_ms=50.0)

        result = tracker.is_data_source_degraded("nws", min_success_rate=0.50, min_calls=3)
        assert result is True

    def test_not_degraded_with_high_success(self, tmp_path, monkeypatch):
        """Returns False when success_rate > threshold."""
        import tracker
        monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "tracker.db")
        monkeypatch.setattr(tracker, "_initialized", False)

        for _ in range(5):
            tracker.log_source_sla("nws", success=True, latency_ms=45.0)

        result = tracker.is_data_source_degraded("nws", min_success_rate=0.50, min_calls=3)
        assert result is False

    def test_insufficient_calls_returns_false(self, tmp_path, monkeypatch):
        """Returns False when fewer than min_calls logged (avoids false positives at startup)."""
        import tracker
        monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "tracker.db")
        monkeypatch.setattr(tracker, "_initialized", False)

        tracker.log_source_sla("nws", success=False, latency_ms=999.0)  # only 1 call

        result = tracker.is_data_source_degraded("nws", min_success_rate=0.50, min_calls=3)
        assert result is False
```

### 21.8 Commit Task 21

```
git add tracker.py weather_markets.py main.py tests/test_data_engineering.py
git commit -m "feat(p6.1): add source SLA logging, degradation detection, and auto-pause"
```

---

## Task 22 (P6.3) — Forecast snapshot for replay

### 22.1 Create `snapshots.py`

- [ ] Create new file `snapshots.py`:

```python
"""
Forecast snapshot writer — persists input data at trade time for replay.

Usage:
    from snapshots import save_forecast_snapshot, load_forecast_snapshot
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

SNAPSHOT_DIR: Path = Path(__file__).parent / "data" / "snapshots"


def save_forecast_snapshot(ticker: str, forecast: dict) -> Path:
    """
    Write forecast dict to data/snapshots/{date}/{ticker}.json.

    Returns the path written.
    """
    date_str = datetime.now(UTC).strftime("%Y-%m-%d")
    out_dir = SNAPSHOT_DIR / date_str
    out_dir.mkdir(parents=True, exist_ok=True)

    safe_ticker = ticker.replace("/", "_")
    out_path = out_dir / f"{safe_ticker}.json"

    payload = {
        "ticker": ticker,
        "snapshot_at": datetime.now(UTC).isoformat(),
        "forecast": forecast,
    }
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return out_path


def load_forecast_snapshot(ticker: str, date: str) -> dict | None:
    """
    Load a snapshot for ticker on the given date (YYYY-MM-DD).

    Returns the payload dict or None if not found.
    """
    safe_ticker = ticker.replace("/", "_")
    path = SNAPSHOT_DIR / date / f"{safe_ticker}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
```

### 22.2 Call `save_forecast_snapshot` in `_auto_place_trades`

- [ ] In `main.py`, when a trade is successfully placed, add:
```python
    try:
        from snapshots import save_forecast_snapshot as _snap
        _snap(ticker=opp["ticker"], forecast=opp)
    except Exception:
        pass  # never block a trade on snapshot failure
```

### 22.3 Write tests

- [ ] Add to `tests/test_data_engineering.py`:

```python
class TestForecastSnapshot:
    def test_save_creates_file(self, tmp_path, monkeypatch):
        """save_forecast_snapshot writes a JSON file."""
        import snapshots
        monkeypatch.setattr(snapshots, "SNAPSHOT_DIR", tmp_path / "snapshots")

        path = snapshots.save_forecast_snapshot(
            ticker="KXHIGH-25APR15-B70",
            forecast={"temperature_max": 75.0, "model_prob": 0.65},
        )

        assert path.exists()
        data = json.loads(path.read_text())
        assert data["ticker"] == "KXHIGH-25APR15-B70"
        assert data["forecast"]["temperature_max"] == 75.0

    def test_load_returns_none_for_missing(self, tmp_path, monkeypatch):
        """load_forecast_snapshot returns None when snapshot does not exist."""
        import snapshots
        monkeypatch.setattr(snapshots, "SNAPSHOT_DIR", tmp_path / "snapshots")

        result = snapshots.load_forecast_snapshot("UNKNOWN-TICKER", "2026-01-01")
        assert result is None

    def test_save_and_load_roundtrip(self, tmp_path, monkeypatch):
        """save then load returns the original data."""
        import snapshots
        from datetime import datetime, UTC
        monkeypatch.setattr(snapshots, "SNAPSHOT_DIR", tmp_path / "snapshots")

        forecast = {"temperature_max": 82.0, "city": "NYC"}
        snapshots.save_forecast_snapshot("KXHIGH-26APR14-T80", forecast)

        date_str = datetime.now(UTC).strftime("%Y-%m-%d")
        loaded = snapshots.load_forecast_snapshot("KXHIGH-26APR14-T80", date_str)
        assert loaded is not None
        assert loaded["forecast"]["city"] == "NYC"
```

### 22.4 Verify Task 22

- [ ] Run:
```
cd "C:\Users\thesa\claude kalshi" && python -m pytest tests/test_data_engineering.py -v
```
Expected: all 9 tests passed.

### 22.5 Full regression check

- [ ] Run:
```
cd "C:\Users\thesa\claude kalshi" && python -m pytest --tb=short -q
```

### 22.6 Commit Task 22

```
git add snapshots.py main.py tests/test_data_engineering.py
git commit -m "feat(p6.3): add forecast snapshot writer for trade replay"
```

---

---

## Task 38 (P6.4) — Feature importance tracking

### 38.1 Add `log_feature_importance` and `get_feature_importance_summary` to `tracker.py`

- [ ] Add `feature_importance` table to `_run_migrations`:

```sql
CREATE TABLE IF NOT EXISTS feature_importance (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    feature     TEXT    NOT NULL,   -- e.g. "nws_temp", "climatology_blend", "regime"
    model_type  TEXT,               -- e.g. "ensemble", "bayesian"
    importance  REAL    NOT NULL,   -- normalized importance score [0, 1]
    logged_at   TEXT    NOT NULL
);
```

- [ ] Add functions:

```python
def log_feature_importance(
    feature: str,
    importance: float,
    model_type: str = "ensemble",
) -> None:
    """Record a feature importance score. Called after each calibration run."""
    _init_db()
    with _conn() as con:
        con.execute(
            """INSERT INTO feature_importance (feature, model_type, importance, logged_at)
               VALUES (?, ?, ?, ?)""",
            (feature, model_type, importance,
             __import__("datetime").datetime.now(
                 __import__("datetime").timezone.utc
             ).isoformat()),
        )


def get_feature_importance_summary(top_n: int = 10) -> list[dict]:
    """
    Return average importance per feature over all recorded runs, sorted descending.
    Identifies which inputs are actually driving predictions.
    """
    _init_db()
    with _conn() as con:
        rows = con.execute(
            """
            SELECT feature, model_type,
                   AVG(importance) AS avg_importance,
                   COUNT(*) AS n_runs
            FROM feature_importance
            GROUP BY feature, model_type
            ORDER BY avg_importance DESC
            LIMIT ?
            """,
            (top_n,),
        ).fetchall()
    return [
        {
            "feature": r["feature"],
            "model_type": r["model_type"],
            "avg_importance": round(r["avg_importance"], 4),
            "n_runs": r["n_runs"],
        }
        for r in rows
    ]
```

### 38.2 Call from `calibration.py` after optimization

- [ ] In `calibration.py`, after the grid-search finds optimal blend weights, log feature importances:

```python
try:
    import tracker as _tracker
    for feature, weight in optimal_weights.items():
        _tracker.log_feature_importance(feature=feature, importance=float(weight))
except Exception:
    pass
```

### 38.3 Write tests

- [ ] Add to `tests/test_data_engineering.py`:

```python
class TestFeatureImportance:
    def test_log_and_retrieve(self, tmp_path, monkeypatch):
        """log_feature_importance writes; get_feature_importance_summary reads back."""
        import tracker
        monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "tracker.db")
        monkeypatch.setattr(tracker, "_initialized", False)

        tracker.log_feature_importance("nws_temp", 0.65)
        tracker.log_feature_importance("climatology_blend", 0.25)
        tracker.log_feature_importance("regime_boost", 0.10)

        summary = tracker.get_feature_importance_summary()
        assert len(summary) == 3
        assert summary[0]["feature"] == "nws_temp"  # highest importance first
        assert summary[0]["avg_importance"] == 0.65

    def test_average_across_runs(self, tmp_path, monkeypatch):
        """Multiple runs are averaged correctly."""
        import tracker
        monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "tracker.db")
        monkeypatch.setattr(tracker, "_initialized", False)

        tracker.log_feature_importance("nws_temp", 0.60)
        tracker.log_feature_importance("nws_temp", 0.80)

        summary = tracker.get_feature_importance_summary()
        nws_entry = next(s for s in summary if s["feature"] == "nws_temp")
        assert abs(nws_entry["avg_importance"] - 0.70) < 0.001
        assert nws_entry["n_runs"] == 2

    def test_empty_returns_empty_list(self, tmp_path, monkeypatch):
        """No data returns empty list."""
        import tracker
        monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "tracker.db")
        monkeypatch.setattr(tracker, "_initialized", False)

        assert tracker.get_feature_importance_summary() == []
```

### 38.4 Verify Task 38

- [ ] Run:
```
cd "C:\Users\thesa\claude kalshi" && python -m pytest tests/test_data_engineering.py -v
```
Expected: all tests passed.

### 38.5 Full regression check

- [ ] Run:
```
cd "C:\Users\thesa\claude kalshi" && python -m pytest --tb=short -q
```

### 38.6 Commit Task 38

```
git add tracker.py calibration.py tests/test_data_engineering.py
git commit -m "feat(p6.4): add feature importance tracking to tracker and calibration"
```

---

## Summary of changes

| File | What changes |
|------|-------------|
| `kalshi_client.py` | +`_MARKET_REQUIRED_FIELDS`, +`validate_market_response(raw)` |
| `tracker.py` | +`source_sla` table; +`log_source_sla`, +`get_source_sla_summary`, +`is_data_source_degraded`; +`feature_importance` table; +`log_feature_importance`, +`get_feature_importance_summary` |
| `weather_markets.py` | Wrap NWS/climatology calls with SLA timing |
| `main.py` | Data-source degradation guard in `_auto_place_trades`; `save_forecast_snapshot` after trade placement |
| `snapshots.py` | New module — `save_forecast_snapshot`, `load_forecast_snapshot` |
| `calibration.py` | Log feature importances after blend weight optimization |
| `tests/test_data_engineering.py` | New — 15 tests across 5 classes |
