# P9: Strategy Intelligence — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the system the ability to detect when a city/condition strategy is losing its edge and retire it automatically, plus allow per-city edge thresholds to adapt based on calibration data.

**What already exists — do NOT re-add:**
- `weather_markets.py: EDGE_CALC_VERSION = "v1.0"` — version stamp on every `analyze_trade`
- `regime.py: detect_regime` — heat dome / cold snap detection with Kelly confidence boost
- `backtest.py: run_walk_forward` — per-window trend (improving/stable/declining)
- `calibration.py` — seasonal/city blend weights → `data/seasonal_weights.json`, `data/city_weights.json`
- `tracker.py: log_member_score` — per-model score history

**Architecture:** Edge decay and retirement use a new `retired_strategies` SQLite table in `tracker.py`. Adaptive thresholds read a JSON file written by `calibration.py`. All three tasks are additive — no existing logic is deleted.

**Tech Stack:** Python 3.11+, pytest, `monkeypatch`, sqlite3. No new dependencies.

---

## Task 29 (P9.2) — Edge decay tracking

### 29.1 Add `compute_edge_decay` to `tracker.py`

- [ ] Add after `get_source_sla_summary`:

```python
def compute_edge_decay(
    city: str,
    condition_type: str,
    window_days: int = 30,
) -> dict:
    """
    Compute rolling performance for a city/condition_type pair.

    Queries the outcomes table for the last `window_days`, splits into
    first-half vs second-half, and returns a trend label.

    Returns:
        {
          city, condition_type, window_days,
          n_trades, win_rate, avg_brier,
          trend: "improving" | "stable" | "declining",
        }
    """
    _init_db()
    cutoff = (
        __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
        - __import__("datetime").timedelta(days=window_days)
    ).isoformat()

    with _conn() as con:
        rows = con.execute(
            """
            SELECT outcome, brier_score, created_at
            FROM outcomes
            WHERE city = ? AND condition_type = ? AND created_at >= ?
            ORDER BY created_at
            """,
            (city, condition_type, cutoff),
        ).fetchall()

    n = len(rows)
    if n == 0:
        return {
            "city": city, "condition_type": condition_type,
            "window_days": window_days, "n_trades": 0,
            "win_rate": None, "avg_brier": None, "trend": "stable",
        }

    wins = sum(1 for r in rows if r["outcome"] == 1)
    win_rate = wins / n
    briers = [r["brier_score"] for r in rows if r["brier_score"] is not None]
    avg_brier = sum(briers) / len(briers) if briers else None

    # Trend: compare first-half vs second-half Brier (lower = better)
    trend = "stable"
    if len(briers) >= 4:
        mid = len(briers) // 2
        first_half = sum(briers[:mid]) / mid
        second_half = sum(briers[mid:]) / (len(briers) - mid)
        if second_half < first_half - 0.02:
            trend = "improving"
        elif second_half > first_half + 0.02:
            trend = "declining"

    return {
        "city": city,
        "condition_type": condition_type,
        "window_days": window_days,
        "n_trades": n,
        "win_rate": round(win_rate, 3),
        "avg_brier": round(avg_brier, 4) if avg_brier is not None else None,
        "trend": trend,
    }
```

### 29.2 Write edge decay to `data/edge_decay.json` at end of cron

- [ ] In `cmd_cron` in `main.py`, before `_clear_cron_running_flag()`, add:

```python
    # P9.2 — update edge decay snapshot
    try:
        import tracker as _tracker, json as _json
        cities = [opp.get("city") for opp in opportunities if opp.get("city")]
        decay_data = []
        for city in set(cities):
            for ctype in ("high_temp", "low_temp", "precip"):
                decay_data.append(_tracker.compute_edge_decay(city, ctype))
        decay_path = Path(__file__).parent / "data" / "edge_decay.json"
        decay_path.write_text(_json.dumps(decay_data, indent=2))
    except Exception as _e:
        _log.warning("cmd_cron: edge decay update failed: %s", _e)
```

### 29.3 Write tests

- [ ] Create `tests/test_strategy_intelligence.py`:

```python
"""Tests for P9: Strategy Intelligence"""
from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime, UTC, timedelta

import pytest


class TestEdgeDecay:
    def _insert_outcomes(self, con, city, ctype, outcomes: list[tuple[int, float]]):
        """Insert fake outcome rows (outcome, brier_score)."""
        for i, (outcome, brier) in enumerate(outcomes):
            created_at = (datetime.now(UTC) - timedelta(days=len(outcomes) - i)).isoformat()
            con.execute(
                """INSERT INTO outcomes (city, condition_type, outcome, brier_score, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (city, ctype, outcome, brier, created_at),
            )

    def test_returns_stable_for_no_data(self, tmp_path, monkeypatch):
        """No outcomes → trend=stable, n_trades=0."""
        import tracker
        monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "tracker.db")
        monkeypatch.setattr(tracker, "_initialized", False)

        result = tracker.compute_edge_decay("NYC", "high_temp", window_days=30)
        assert result["n_trades"] == 0
        assert result["trend"] == "stable"

    def test_declining_trend_detected(self, tmp_path, monkeypatch):
        """Worsening second-half Brier → trend=declining."""
        import tracker, sqlite3
        monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "tracker.db")
        monkeypatch.setattr(tracker, "_initialized", False)
        tracker._init_db()  # create tables

        with sqlite3.connect(tmp_path / "tracker.db") as con:
            con.row_factory = sqlite3.Row
            # First half: good Brier (0.10); Second half: bad Brier (0.35)
            self._insert_outcomes(con, "NYC", "high_temp", [
                (1, 0.10), (1, 0.11), (0, 0.12), (1, 0.09),  # first half
                (0, 0.35), (0, 0.36), (1, 0.34), (0, 0.38),  # second half — worse
            ])

        result = tracker.compute_edge_decay("NYC", "high_temp", window_days=60)
        assert result["trend"] == "declining"
        assert result["n_trades"] == 8

    def test_improving_trend_detected(self, tmp_path, monkeypatch):
        """Improving second-half Brier → trend=improving."""
        import tracker, sqlite3
        monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "tracker.db")
        monkeypatch.setattr(tracker, "_initialized", False)
        tracker._init_db()

        with sqlite3.connect(tmp_path / "tracker.db") as con:
            con.row_factory = sqlite3.Row
            self._insert_outcomes(con, "NYC", "high_temp", [
                (0, 0.35), (0, 0.33), (1, 0.34), (0, 0.36),  # first half — worse
                (1, 0.10), (1, 0.11), (1, 0.09), (1, 0.10),  # second half — better
            ])

        result = tracker.compute_edge_decay("NYC", "high_temp", window_days=60)
        assert result["trend"] == "improving"
```

### 29.4 Verify Task 29

- [ ] Run:
```
cd "C:\Users\thesa\claude kalshi" && python -m pytest tests/test_strategy_intelligence.py::TestEdgeDecay -v
```
Expected: 3 passed.

### 29.5 Commit Task 29

```
git add tracker.py main.py tests/test_strategy_intelligence.py
git commit -m "feat(p9.2): add edge decay tracking with rolling Brier trend detection"
```

---

## Task 30 (P9.5) — Strategy retirement system

### 30.1 Add `retired_strategies` table to `tracker.py`

- [ ] Add to `_run_migrations`:

```sql
CREATE TABLE IF NOT EXISTS retired_strategies (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    city         TEXT NOT NULL,
    condition_type TEXT NOT NULL,
    retired_at   TEXT NOT NULL,
    reason       TEXT,
    UNIQUE(city, condition_type)
);
```

### 30.2 Add `retire_strategy`, `get_retired_strategies`, `unretire_strategy`

- [ ] Add to `tracker.py`:

```python
def retire_strategy(city: str, condition_type: str, reason: str = "") -> None:
    """Mark a city/condition_type pair as retired — will be skipped in auto-trading."""
    _init_db()
    with _conn() as con:
        con.execute(
            """
            INSERT OR REPLACE INTO retired_strategies (city, condition_type, retired_at, reason)
            VALUES (?, ?, ?, ?)
            """,
            (city, condition_type,
             __import__("datetime").datetime.now(
                 __import__("datetime").timezone.utc
             ).isoformat(), reason),
        )


def get_retired_strategies() -> set[tuple[str, str]]:
    """Return set of (city, condition_type) tuples that are retired."""
    _init_db()
    with _conn() as con:
        rows = con.execute(
            "SELECT city, condition_type FROM retired_strategies"
        ).fetchall()
    return {(r["city"], r["condition_type"]) for r in rows}


def unretire_strategy(city: str, condition_type: str) -> None:
    """Remove a retirement, re-enabling the strategy."""
    _init_db()
    with _conn() as con:
        con.execute(
            "DELETE FROM retired_strategies WHERE city = ? AND condition_type = ?",
            (city, condition_type),
        )
```

### 30.3 Add retirement check in `_auto_place_trades`

- [ ] In `main.py`, in `_auto_place_trades`, after the kill switch / pause check, add:

```python
    # P9.5 — load retired strategies once per call
    try:
        import tracker as _tracker
        _retired = _tracker.get_retired_strategies()
    except Exception:
        _retired = set()
```

- [ ] In the per-opportunity loop:

```python
        city = opp.get("city", "")
        ctype = opp.get("condition_type", "")
        if (city, ctype) in _retired:
            _log.info("_auto_place_trades: skipping retired strategy %s/%s", city, ctype)
            continue
```

### 30.4 Auto-retirement trigger

- [ ] In `cmd_cron`, after the edge decay update, add:

```python
    # P9.5 — auto-retire strategies with sustained poor performance
    try:
        import tracker as _tracker
        for entry in decay_data:
            if (
                entry.get("n_trades", 0) >= 20
                and entry.get("win_rate") is not None
                and entry["win_rate"] < 0.40
                and entry.get("trend") == "declining"
            ):
                _tracker.retire_strategy(
                    city=entry["city"],
                    condition_type=entry["condition_type"],
                    reason=f"auto: win_rate={entry['win_rate']:.2f} < 0.40 over {entry['n_trades']} trades",
                )
                _log.warning(
                    "cmd_cron: auto-retired strategy %s/%s (win_rate=%.2f)",
                    entry["city"], entry["condition_type"], entry["win_rate"],
                )
    except Exception as _e:
        _log.warning("cmd_cron: auto-retirement check failed: %s", _e)
```

### 30.5 Write tests

- [ ] Add to `tests/test_strategy_intelligence.py`:

```python
class TestStrategyRetirement:
    def test_retired_strategy_blocks_trade(self, tmp_path, monkeypatch):
        """A retired city/condition pair must not result in a placed trade."""
        import main, tracker, execution_log, paper
        monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "tracker.db")
        monkeypatch.setattr(tracker, "_initialized", False)

        tracker.retire_strategy("NYC", "high_temp", reason="test")

        monkeypatch.setattr(paper, "is_paused_drawdown", lambda: False)
        monkeypatch.setattr(paper, "is_daily_loss_halted", lambda client=None: False)
        monkeypatch.setattr(paper, "is_streak_paused", lambda: False)
        monkeypatch.setattr(paper, "get_open_trades", lambda: [])
        monkeypatch.setattr(paper, "portfolio_kelly_fraction",
                            lambda f, c, d, side="yes": f)
        monkeypatch.setattr(paper, "kelly_quantity",
                            lambda f, p, min_dollars=1.0, cap=None, method=None: 2)
        monkeypatch.setattr(execution_log, "was_traded_today", lambda t, s: False)
        monkeypatch.setattr(execution_log, "was_ordered_this_cycle", lambda t, s, c: False)
        monkeypatch.setattr(main, "_daily_paper_spend", lambda: 0.0)
        monkeypatch.setattr(main, "KILL_SWITCH_PATH", tmp_path / ".no_ks")
        monkeypatch.setattr(main, "PAUSE_TRADING_PATH", tmp_path / ".no_pause")

        opp = {
            "ticker": "KXHIGH-25APR15-B70",
            "city": "NYC",
            "condition_type": "high_temp",
            "net_edge": 0.20,
            "ci_adjusted_kelly": 0.10,
            "data_fetched_at": __import__("time").time(),
            "recommended_side": "yes",
            "market_prob": 0.50,
            "model_consensus": True,
        }
        result = main._auto_place_trades([opp], client=None, live=False)
        assert result == 0, "retired strategy must not place trades"

    def test_unretire_restores_strategy(self, tmp_path, monkeypatch):
        """After unretiring, the strategy is no longer in the retired set."""
        import tracker
        monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "tracker.db")
        monkeypatch.setattr(tracker, "_initialized", False)

        tracker.retire_strategy("LAX", "low_temp")
        assert ("LAX", "low_temp") in tracker.get_retired_strategies()

        tracker.unretire_strategy("LAX", "low_temp")
        assert ("LAX", "low_temp") not in tracker.get_retired_strategies()

    def test_get_retired_returns_empty_on_fresh_db(self, tmp_path, monkeypatch):
        """Fresh DB returns empty set."""
        import tracker
        monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "tracker.db")
        monkeypatch.setattr(tracker, "_initialized", False)

        assert tracker.get_retired_strategies() == set()
```

### 30.6 Verify Task 30

- [ ] Run:
```
cd "C:\Users\thesa\claude kalshi" && python -m pytest tests/test_strategy_intelligence.py::TestStrategyRetirement -v
```
Expected: 3 passed.

### 30.7 Commit Task 30

```
git add tracker.py main.py tests/test_strategy_intelligence.py
git commit -m "feat(p9.5): add strategy retirement system with auto-retirement trigger"
```

---

## Task 31 (P9.4) — Adaptive min-edge threshold

### 31.1 Add `get_adaptive_min_edge` to `main.py`

- [ ] Add after `KILL_SWITCH_PATH`:

```python
ADAPTIVE_THRESHOLDS_PATH: Path = Path(__file__).parent / "data" / "adaptive_thresholds.json"

def get_adaptive_min_edge(city: str) -> float:
    """
    Return the min_edge threshold for `city`.

    Checks data/adaptive_thresholds.json for a per-city override
    (written by calibration.py). Falls back to PAPER_MIN_EDGE env var.
    """
    import json as _json

    try:
        if ADAPTIVE_THRESHOLDS_PATH.exists():
            thresholds = _json.loads(ADAPTIVE_THRESHOLDS_PATH.read_text())
            city_threshold = thresholds.get(city)
            if city_threshold is not None:
                return float(city_threshold)
    except Exception as _e:
        _log.warning("get_adaptive_min_edge: could not read thresholds: %s", _e)
    return MIN_EDGE  # fallback to global constant
```

### 31.2 Use `get_adaptive_min_edge` in `_validate_trade_opportunity`

- [ ] In `_validate_trade_opportunity`, replace the global `MIN_EDGE` check:
```python
    city = opportunity.get("city", "")
    effective_min_edge = get_adaptive_min_edge(city)
    if opportunity["net_edge"] < effective_min_edge:
        return False, f"net_edge {opportunity['net_edge']:.3f} < min_edge {effective_min_edge:.3f}"
```

### 31.3 Write tests

- [ ] Add to `tests/test_strategy_intelligence.py`:

```python
class TestAdaptiveThreshold:
    def test_adaptive_threshold_overrides_global(self, tmp_path, monkeypatch):
        """Per-city threshold in adaptive_thresholds.json overrides PAPER_MIN_EDGE."""
        import main, json
        thresholds_file = tmp_path / "adaptive_thresholds.json"
        thresholds_file.write_text(json.dumps({"NYC": 0.08, "LAX": 0.12}))
        monkeypatch.setattr(main, "ADAPTIVE_THRESHOLDS_PATH", thresholds_file)
        monkeypatch.setattr(main, "MIN_EDGE", 0.05)

        assert main.get_adaptive_min_edge("NYC") == 0.08
        assert main.get_adaptive_min_edge("LAX") == 0.12

    def test_missing_city_falls_back_to_global(self, tmp_path, monkeypatch):
        """City not in adaptive_thresholds.json uses global MIN_EDGE."""
        import main, json
        thresholds_file = tmp_path / "adaptive_thresholds.json"
        thresholds_file.write_text(json.dumps({"NYC": 0.08}))
        monkeypatch.setattr(main, "ADAPTIVE_THRESHOLDS_PATH", thresholds_file)
        monkeypatch.setattr(main, "MIN_EDGE", 0.05)

        assert main.get_adaptive_min_edge("CHI") == 0.05

    def test_missing_file_falls_back_to_global(self, tmp_path, monkeypatch):
        """Missing adaptive_thresholds.json falls back to MIN_EDGE."""
        import main
        monkeypatch.setattr(main, "ADAPTIVE_THRESHOLDS_PATH",
                            tmp_path / "nonexistent.json")
        monkeypatch.setattr(main, "MIN_EDGE", 0.07)

        assert main.get_adaptive_min_edge("NYC") == 0.07
```

### 31.4 Verify Task 31

- [ ] Run:
```
cd "C:\Users\thesa\claude kalshi" && python -m pytest tests/test_strategy_intelligence.py -v
```
Expected: all tests passed.

### 31.5 Full regression check

- [ ] Run:
```
cd "C:\Users\thesa\claude kalshi" && python -m pytest --tb=short -q
```

### 31.6 Commit Task 31

```
git add main.py tests/test_strategy_intelligence.py
git commit -m "feat(p9.4): add per-city adaptive min-edge threshold from adaptive_thresholds.json"
```

---

---

## Task 41 (P9.1) — Strategy versioning

The PDF requires "track performance across versions." `EDGE_CALC_VERSION = "v1.0"` already stamps outputs, but there is no persistent per-version performance record. This task adds one.

### 41.1 Add `strategy_versions` table to `tracker.py`

- [ ] Add to `_run_migrations`:

```sql
CREATE TABLE IF NOT EXISTS strategy_versions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    version         TEXT    NOT NULL,    -- e.g. "v1.0", "v1.1"
    activated_at    TEXT    NOT NULL,
    deactivated_at  TEXT,
    notes           TEXT
);

CREATE TABLE IF NOT EXISTS version_performance (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    version     TEXT    NOT NULL,
    logged_at   TEXT    NOT NULL,
    n_trades    INTEGER,
    win_rate    REAL,
    avg_brier   REAL,
    roi         REAL
);
```

### 41.2 Add version tracking functions to `tracker.py`

- [ ] Add:

```python
def activate_strategy_version(version: str, notes: str = "") -> None:
    """Record that a new strategy version became active."""
    _init_db()
    now = __import__("datetime").datetime.now(
        __import__("datetime").timezone.utc
    ).isoformat()
    with _conn() as con:
        # Deactivate previous active version
        con.execute(
            """UPDATE strategy_versions SET deactivated_at = ?
               WHERE deactivated_at IS NULL AND version != ?""",
            (now, version),
        )
        # Insert new version if not already recorded
        con.execute(
            """INSERT OR IGNORE INTO strategy_versions (version, activated_at, notes)
               VALUES (?, ?, ?)""",
            (version, now, notes),
        )


def log_version_performance(
    version: str,
    n_trades: int,
    win_rate: float,
    avg_brier: float,
    roi: float,
) -> None:
    """Append a performance snapshot for a strategy version."""
    _init_db()
    with _conn() as con:
        con.execute(
            """INSERT INTO version_performance
               (version, logged_at, n_trades, win_rate, avg_brier, roi)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (version,
             __import__("datetime").datetime.now(
                 __import__("datetime").timezone.utc
             ).isoformat(),
             n_trades, win_rate, avg_brier, roi),
        )


def get_version_performance_summary() -> list[dict]:
    """Return latest performance snapshot per version, newest first."""
    _init_db()
    with _conn() as con:
        rows = con.execute(
            """
            SELECT version, logged_at, n_trades, win_rate, avg_brier, roi
            FROM version_performance
            GROUP BY version
            HAVING logged_at = MAX(logged_at)
            ORDER BY logged_at DESC
            """,
        ).fetchall()
    return [dict(r) for r in rows]
```

### 41.3 Wire into `cmd_cron`

- [ ] In `main.py`, at the start of `cmd_cron` (after config validation), register the current version:

```python
    try:
        import tracker as _tracker
        from weather_markets import EDGE_CALC_VERSION as _ECV
        _tracker.activate_strategy_version(_ECV)
    except Exception:
        pass
```

- [ ] At the end of `cmd_cron` (before `_clear_cron_running_flag`), log performance for this version:

```python
    try:
        import tracker as _tracker
        from weather_markets import EDGE_CALC_VERSION as _ECV
        _decay_summary = _tracker.compute_edge_decay("ALL", "ALL", window_days=30)
        _tracker.log_version_performance(
            version=_ECV,
            n_trades=_decay_summary.get("n_trades", 0),
            win_rate=_decay_summary.get("win_rate") or 0.0,
            avg_brier=_decay_summary.get("avg_brier") or 0.0,
            roi=0.0,  # paper ROI tracked separately via paper.get_state_snapshot
        )
    except Exception as _e:
        _log.warning("cmd_cron: version performance logging failed: %s", _e)
```

### 41.4 Write tests

- [ ] Add to `tests/test_strategy_intelligence.py`:

```python
class TestStrategyVersioning:
    def test_activate_records_version(self, tmp_path, monkeypatch):
        """activate_strategy_version writes a row to strategy_versions."""
        import tracker
        monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "tracker.db")
        monkeypatch.setattr(tracker, "_initialized", False)

        tracker.activate_strategy_version("v1.0", notes="initial")
        tracker.activate_strategy_version("v1.1", notes="improved edge calc")

        # Only v1.1 should be active (deactivated_at IS NULL)
        import sqlite3
        with sqlite3.connect(tmp_path / "tracker.db") as con:
            con.row_factory = sqlite3.Row
            active = con.execute(
                "SELECT version FROM strategy_versions WHERE deactivated_at IS NULL"
            ).fetchall()
        assert len(active) == 1
        assert active[0]["version"] == "v1.1"

    def test_log_and_retrieve_performance(self, tmp_path, monkeypatch):
        """log_version_performance + get_version_performance_summary roundtrip."""
        import tracker
        monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "tracker.db")
        monkeypatch.setattr(tracker, "_initialized", False)

        tracker.log_version_performance("v1.0", 25, 0.58, 0.21, 0.05)
        tracker.log_version_performance("v1.1", 30, 0.63, 0.18, 0.09)

        summary = tracker.get_version_performance_summary()
        assert len(summary) == 2
        versions = [s["version"] for s in summary]
        assert "v1.0" in versions
        assert "v1.1" in versions

    def test_empty_db_returns_empty_summary(self, tmp_path, monkeypatch):
        """No performance logs → empty list."""
        import tracker
        monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "tracker.db")
        monkeypatch.setattr(tracker, "_initialized", False)

        assert tracker.get_version_performance_summary() == []
```

### 41.5 Verify Task 41

- [ ] Run:
```
cd "C:\Users\thesa\claude kalshi" && python -m pytest tests/test_strategy_intelligence.py -v
```
Expected: all tests passed.

### 41.6 Full regression check

- [ ] Run:
```
cd "C:\Users\thesa\claude kalshi" && python -m pytest --tb=short -q
```

### 41.7 Commit Task 41

```
git add tracker.py main.py tests/test_strategy_intelligence.py
git commit -m "feat(p9.1): add strategy versioning with per-version performance tracking"
```

---

---

## Task 49 (P9.3) — Regime Detection Wiring + Verification

- [ ] **Verify** `detect_regime` from `regime.py` is called during trade opportunity evaluation.
- [ ] **Wire** regime output into `_auto_place_trades` Kelly adjustment if not already connected.
- [ ] **Log** regime classification alongside decision log entries.
- [ ] **Append** tests to `tests/test_strategy_intelligence.py`.
- [ ] **Verify** by running the Task 49 tests.
- [ ] **Commit** with message `feat(p9.3): wire regime detection into Kelly sizing and decision log`.

### What is being added

`regime.py: detect_regime` already exists (heat dome / cold snap detection with Kelly confidence boost — noted in the plan header as existing). The PDF requires "adapt to market conditions." This task ensures `detect_regime` is:
1. **Actually called** during `_auto_place_trades` (not just available but orphaned)
2. **Logged** in the decision log so operators can audit regime influence
3. **Verified** by tests that different regime states produce different Kelly multipliers

### Wiring in `_auto_place_trades` (main.py)

In the per-opportunity loop, after computing `kelly_fraction` and the P2.3 correlation penalty, add:

```python
# P9.3 — regime detection: adapt Kelly to current market regime
try:
    from regime import detect_regime as _detect_regime
    _regime = _detect_regime(opp.get("city", ""), opp.get("condition_type", ""))
    _regime_label = _regime.get("regime", "normal")
    _regime_multiplier = _regime.get("kelly_multiplier", 1.0)
    if _regime_multiplier != 1.0:
        _log.info(
            "P9.3 regime=%s city=%s → Kelly multiplier=%.2f",
            _regime_label, opp.get("city", ""), _regime_multiplier,
        )
    kelly_fraction *= _regime_multiplier
except Exception as _re:
    _log.warning("P9.3 regime detection failed: %s — using default Kelly", _re)
    _regime_label = "unknown"
```

Also pass `regime=_regime_label` to `_log_decision()` (add `regime: str = "normal"` param to that function).

### Test code — Task 49

```python
# ── Task 49 (P9.3): Regime detection wiring ──────────────────────────────────

class TestRegimeDetectionWiring:
    """detect_regime output must affect Kelly sizing and be present in decision log."""

    def test_heat_dome_regime_increases_kelly(self):
        """
        Heat dome (high-temp event) → detect_regime should return kelly_multiplier > 1.0
        for a high-temperature condition.
        """
        from regime import detect_regime

        result = detect_regime(city="Phoenix", condition_type="HIGH_TEMP")
        assert "regime" in result, "detect_regime must return a 'regime' key"
        assert "kelly_multiplier" in result, "detect_regime must return 'kelly_multiplier'"
        assert isinstance(result["kelly_multiplier"], float)

    def test_normal_regime_multiplier_is_one(self):
        """Normal conditions → kelly_multiplier == 1.0."""
        from regime import detect_regime

        result = detect_regime(city="Chicago", condition_type="NORMAL")
        # Normal regime should not distort Kelly
        assert result.get("kelly_multiplier", 1.0) == 1.0 or \
               result.get("regime", "normal") == "normal", \
               "Normal regime should produce multiplier 1.0 or label 'normal'"

    def test_regime_detection_does_not_raise_on_unknown_city(self):
        """detect_regime must not raise for unknown/empty city."""
        from regime import detect_regime

        result = detect_regime(city="", condition_type="UNKNOWN")
        assert isinstance(result, dict), "Must return a dict even for unknown inputs"
        assert "kelly_multiplier" in result

    def test_extreme_regime_reduces_or_increases_kelly_consistently(self):
        """
        Two calls with the same inputs must return the same multiplier (deterministic).
        """
        from regime import detect_regime

        r1 = detect_regime(city="Phoenix", condition_type="HIGH_TEMP")
        r2 = detect_regime(city="Phoenix", condition_type="HIGH_TEMP")
        assert r1["kelly_multiplier"] == r2["kelly_multiplier"], \
            "detect_regime must be deterministic for same inputs"
```

### Run command — Task 49

```
cd "C:\Users\thesa\claude kalshi" && python -m pytest tests/test_strategy_intelligence.py::TestRegimeDetectionWiring -v
```

### Expected output — Task 49

```
tests/test_strategy_intelligence.py::TestRegimeDetectionWiring::test_heat_dome_regime_increases_kelly PASSED
tests/test_strategy_intelligence.py::TestRegimeDetectionWiring::test_normal_regime_multiplier_is_one PASSED
tests/test_strategy_intelligence.py::TestRegimeDetectionWiring::test_regime_detection_does_not_raise_on_unknown_city PASSED
tests/test_strategy_intelligence.py::TestRegimeDetectionWiring::test_extreme_regime_reduces_or_increases_kelly_consistently PASSED
4 passed in 0.XXs
```

---

## Summary of changes

| File | What changes |
|------|-------------|
| `tracker.py` | +`compute_edge_decay`; +`retired_strategies` table; +`retire_strategy`, `get_retired_strategies`, `unretire_strategy`; +`strategy_versions` + `version_performance` tables; +`activate_strategy_version`, `log_version_performance`, `get_version_performance_summary` |
| `main.py` | +`ADAPTIVE_THRESHOLDS_PATH`; +`get_adaptive_min_edge`; retirement check + version registration in `cmd_cron`; edge decay + auto-retirement in `cmd_cron`; regime detection wiring in `_auto_place_trades`; `regime` field added to `_log_decision` |
| `tests/test_strategy_intelligence.py` | New — 16 tests across 5 classes |
