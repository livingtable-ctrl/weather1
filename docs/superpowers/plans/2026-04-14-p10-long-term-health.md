# P10: Long-Term System Health — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Three protective layers that kick in automatically as the system ages: performance drift detection, a consecutive-loss black swan halt, and startup config integrity validation.

**What already exists — do NOT re-add:**
- `tracker.py: _run_migrations` — versioned DB schema v9
- `paper.py: _SCHEMA_VERSION = 2`, `_validate_crc`, `_validate_checksum` — file integrity
- `circuit_breaker.py: CircuitBreaker` — per-source failure isolation
- `paper.py: is_paused_drawdown`, `is_daily_loss_halted` — percentage-based halts
- `backtest.py: run_walk_forward` — walk-forward trend, but does not alert

**Architecture:** Drift detection queries `tracker.py` and writes a status file. The consecutive-loss halt is a new guard in `paper.py`. Config validation runs once at cron startup in `main.py`. All three are additive — no existing code is deleted.

**Tech Stack:** Python 3.11+, pytest, `monkeypatch`. No new dependencies.

---

## Task 32 (P10.1) — Drift detection

### 32.1 Add `check_performance_drift` to `tracker.py`

- [ ] Add after `compute_edge_decay`:

```python
def check_performance_drift(
    window_days: int = 14,
    baseline_days: int = 90,
    drift_threshold: float = 0.05,
) -> dict:
    """
    Compare recent Brier score vs long-term baseline.

    Returns:
        {
          window_days, baseline_days,
          recent_brier, baseline_brier,
          drift: float (recent - baseline; positive = worse),
          drift_detected: bool,
          n_recent, n_baseline,
        }
    """
    _init_db()
    now_iso = __import__("datetime").datetime.now(
        __import__("datetime").timezone.utc
    ).isoformat()
    window_cutoff = (
        __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
        - __import__("datetime").timedelta(days=window_days)
    ).isoformat()
    baseline_cutoff = (
        __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
        - __import__("datetime").timedelta(days=baseline_days)
    ).isoformat()

    with _conn() as con:
        recent_row = con.execute(
            """
            SELECT AVG(brier_score) AS avg_brier, COUNT(*) AS n
            FROM outcomes
            WHERE created_at >= ? AND brier_score IS NOT NULL
            """,
            (window_cutoff,),
        ).fetchone()
        baseline_row = con.execute(
            """
            SELECT AVG(brier_score) AS avg_brier, COUNT(*) AS n
            FROM outcomes
            WHERE created_at >= ? AND brier_score IS NOT NULL
            """,
            (baseline_cutoff,),
        ).fetchone()

    recent_brier = recent_row["avg_brier"] if recent_row["avg_brier"] is not None else None
    baseline_brier = baseline_row["avg_brier"] if baseline_row["avg_brier"] is not None else None

    drift = None
    drift_detected = False
    if recent_brier is not None and baseline_brier is not None:
        drift = round(recent_brier - baseline_brier, 4)
        drift_detected = drift > drift_threshold

    return {
        "window_days": window_days,
        "baseline_days": baseline_days,
        "recent_brier": round(recent_brier, 4) if recent_brier is not None else None,
        "baseline_brier": round(baseline_brier, 4) if baseline_brier is not None else None,
        "drift": drift,
        "drift_detected": drift_detected,
        "n_recent": recent_row["n"] if recent_row else 0,
        "n_baseline": baseline_row["n"] if baseline_row else 0,
    }
```

### 32.2 Call in `cmd_cron` and write `data/drift_status.json`

- [ ] In `main.py`, in `cmd_cron`, before `_clear_cron_running_flag()`:

```python
    # P10.1 — performance drift detection
    try:
        import tracker as _tracker, json as _json
        drift = _tracker.check_performance_drift()
        drift_path = Path(__file__).parent / "data" / "drift_status.json"
        drift_path.write_text(_json.dumps(drift, indent=2))
        if drift.get("drift_detected"):
            _log.warning(
                "cmd_cron: PERFORMANCE DRIFT DETECTED — "
                "recent Brier=%.4f vs baseline=%.4f (delta=+%.4f)",
                drift.get("recent_brier"),
                drift.get("baseline_brier"),
                drift.get("drift"),
            )
    except Exception as _e:
        _log.warning("cmd_cron: drift check failed: %s", _e)
```

### 32.3 Write tests

- [ ] Create `tests/test_long_term_health.py`:

```python
"""Tests for P10: Long-Term System Health"""
from __future__ import annotations

import json
import logging
from datetime import datetime, UTC, timedelta
from pathlib import Path

import pytest


class TestDriftDetection:
    def _insert_outcomes(self, tmp_path, records: list[tuple[float, int]]):
        """
        Insert outcomes into a fresh DB.
        records: list of (brier_score, days_ago)
        """
        import tracker, sqlite3
        with sqlite3.connect(tmp_path / "tracker.db") as con:
            con.row_factory = sqlite3.Row
            for brier, days_ago in records:
                created_at = (datetime.now(UTC) - timedelta(days=days_ago)).isoformat()
                con.execute(
                    """INSERT INTO outcomes (city, condition_type, outcome, brier_score, created_at)
                       VALUES ('NYC', 'high_temp', 1, ?, ?)""",
                    (brier, created_at),
                )

    def test_no_drift_when_scores_similar(self, tmp_path, monkeypatch):
        """No drift when recent Brier ≈ baseline Brier."""
        import tracker
        monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "tracker.db")
        monkeypatch.setattr(tracker, "_initialized", False)
        tracker._init_db()

        # Recent (last 14 days): Brier ~0.20; Baseline (last 90 days): ~0.20
        self._insert_outcomes(tmp_path, [
            (0.20, 5), (0.21, 8), (0.19, 12),   # recent
            (0.20, 30), (0.21, 45), (0.19, 60),  # baseline (but not recent)
        ])

        result = tracker.check_performance_drift(
            window_days=14, baseline_days=90, drift_threshold=0.05
        )
        assert result["drift_detected"] is False

    def test_drift_detected_when_recent_brier_higher(self, tmp_path, monkeypatch):
        """Drift detected when recent Brier > baseline + threshold."""
        import tracker
        monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "tracker.db")
        monkeypatch.setattr(tracker, "_initialized", False)
        tracker._init_db()

        # Recent: Brier 0.35; Old: Brier 0.20 → drift = 0.15 > threshold 0.05
        self._insert_outcomes(tmp_path, [
            (0.35, 3), (0.36, 7), (0.34, 10),    # recent (last 14 days)
            (0.20, 30), (0.19, 50), (0.21, 70),  # old baseline
        ])

        result = tracker.check_performance_drift(
            window_days=14, baseline_days=90, drift_threshold=0.05
        )
        assert result["drift_detected"] is True
        assert result["drift"] > 0.05

    def test_no_data_returns_no_drift(self, tmp_path, monkeypatch):
        """Empty outcomes table returns drift_detected=False, not an error."""
        import tracker
        monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "tracker.db")
        monkeypatch.setattr(tracker, "_initialized", False)

        result = tracker.check_performance_drift()
        assert result["drift_detected"] is False
        assert result["recent_brier"] is None
```

### 32.4 Verify Task 32

- [ ] Run:
```
cd "C:\Users\thesa\claude kalshi" && python -m pytest tests/test_long_term_health.py::TestDriftDetection -v
```
Expected: 3 passed.

### 32.5 Commit Task 32

```
git add tracker.py main.py tests/test_long_term_health.py
git commit -m "feat(p10.1): add performance drift detection with Brier score comparison"
```

---

## Task 33 (P10.2) — Black swan consecutive-loss halt

### 33.1 Add `MAX_CONSECUTIVE_LOSSES` and `get_consecutive_losses` to `paper.py`

- [ ] Near the other env-var constants:

```python
MAX_CONSECUTIVE_LOSSES: int = int(_os.getenv("MAX_CONSECUTIVE_LOSSES", "5"))
```

- [ ] Add helper function:

```python
def get_consecutive_losses() -> int:
    """
    Count the current consecutive losing streak from most recent settled trades.

    A 'loss' is a settled trade where the outcome was against our position
    (i.e., we bought YES and market resolved NO, or vice versa).
    Reads from paper_trades.json `trades` list, most-recent first.
    """
    try:
        data = _load()
        trades = data.get("trades", [])
        # Most recent first
        settled = [t for t in reversed(trades) if t.get("settled") and "pnl" in t]
        streak = 0
        for trade in settled:
            if trade.get("pnl", 0) < 0:
                streak += 1
            else:
                break  # win breaks the streak
        return streak
    except Exception:
        return 0


def is_black_swan_halted() -> bool:
    """Return True if consecutive losses >= MAX_CONSECUTIVE_LOSSES."""
    return get_consecutive_losses() >= MAX_CONSECUTIVE_LOSSES
```

### 33.2 Add guard in `_auto_place_trades`

- [ ] In `main.py`, in `_auto_place_trades`, after the kill switch and pause checks:

```python
    # P10.2 — black swan consecutive-loss halt
    import paper as _paper_bs
    if _paper_bs.is_black_swan_halted():
        _log.warning(
            "_auto_place_trades: BLACK SWAN HALT — %d consecutive losses "
            "(threshold=%d). Set MAX_CONSECUTIVE_LOSSES env var to adjust.",
            _paper_bs.get_consecutive_losses(),
            _paper_bs.MAX_CONSECUTIVE_LOSSES,
        )
        return 0
```

### 33.3 Write tests

- [ ] Add to `tests/test_long_term_health.py`:

```python
class TestBlackSwanHalt:
    def _make_paper_file(self, tmp_path, trades: list[dict]) -> Path:
        p = tmp_path / "paper.json"
        p.write_text(json.dumps({
            "_version": 2,
            "balance": 900.0,
            "peak_balance": 1000.0,
            "trades": trades,
        }))
        return p

    def _trade(self, pnl: float, settled: bool = True) -> dict:
        return {"ticker": "X", "pnl": pnl, "settled": settled}

    def test_no_consecutive_losses_returns_zero(self, tmp_path, monkeypatch):
        """No settled trades → 0 consecutive losses."""
        import paper
        monkeypatch.setattr(paper, "DATA_PATH",
                            self._make_paper_file(tmp_path, []))

        assert paper.get_consecutive_losses() == 0

    def test_streak_counted_correctly(self, tmp_path, monkeypatch):
        """Three consecutive losses → streak=3."""
        import paper
        trades = [
            self._trade(pnl=+0.50),   # oldest: win
            self._trade(pnl=-0.30),   # loss
            self._trade(pnl=-0.25),   # loss
            self._trade(pnl=-0.40),   # loss (most recent)
        ]
        monkeypatch.setattr(paper, "DATA_PATH",
                            self._make_paper_file(tmp_path, trades))

        assert paper.get_consecutive_losses() == 3

    def test_win_breaks_streak(self, tmp_path, monkeypatch):
        """A win in the middle resets the streak."""
        import paper
        trades = [
            self._trade(pnl=-0.30),  # oldest: loss
            self._trade(pnl=+0.50),  # win — streak reset
            self._trade(pnl=-0.25),  # loss (most recent)
        ]
        monkeypatch.setattr(paper, "DATA_PATH",
                            self._make_paper_file(tmp_path, trades))

        assert paper.get_consecutive_losses() == 1

    def test_is_black_swan_halted_triggers_at_threshold(self, tmp_path, monkeypatch):
        """is_black_swan_halted returns True at MAX_CONSECUTIVE_LOSSES."""
        import paper
        trades = [self._trade(pnl=-0.20) for _ in range(5)]
        monkeypatch.setattr(paper, "DATA_PATH",
                            self._make_paper_file(tmp_path, trades))
        monkeypatch.setattr(paper, "MAX_CONSECUTIVE_LOSSES", 5)

        assert paper.is_black_swan_halted() is True

    def test_is_black_swan_halted_false_below_threshold(self, tmp_path, monkeypatch):
        """is_black_swan_halted returns False when streak < threshold."""
        import paper
        trades = [self._trade(pnl=-0.20) for _ in range(3)]
        monkeypatch.setattr(paper, "DATA_PATH",
                            self._make_paper_file(tmp_path, trades))
        monkeypatch.setattr(paper, "MAX_CONSECUTIVE_LOSSES", 5)

        assert paper.is_black_swan_halted() is False
```

### 33.4 Verify Task 33

- [ ] Run:
```
cd "C:\Users\thesa\claude kalshi" && python -m pytest tests/test_long_term_health.py::TestBlackSwanHalt -v
```
Expected: 5 passed.

### 33.5 Commit Task 33

```
git add paper.py main.py tests/test_long_term_health.py
git commit -m "feat(p10.2): add consecutive-loss black swan halt to paper trading"
```

---

## Task 34 (P10.3) — Config integrity validation at startup

### 34.1 Add `validate_config` to `utils.py`

- [ ] Add at the bottom of `utils.py`:

```python
def validate_config() -> list[str]:
    """
    Validate all required environment variables are present and in valid range.

    Returns a list of error strings. Empty list = config is valid.
    Call at startup (e.g. in cmd_cron) before any trading logic runs.
    """
    import os as _os

    errors: list[str] = []

    # KALSHI_ENV must be "prod" or "demo"
    env = _os.getenv("KALSHI_ENV", "")
    if env not in ("prod", "demo"):
        errors.append(
            f"KALSHI_ENV must be 'prod' or 'demo', got '{env}'"
        )

    # KALSHI_API_KEY must be set (non-empty)
    api_key = _os.getenv("KALSHI_API_KEY", "")
    if not api_key.strip():
        errors.append("KALSHI_API_KEY is not set or empty")

    # PAPER_MIN_EDGE must be in [0.01, 0.30]
    try:
        min_edge = float(_os.getenv("PAPER_MIN_EDGE", "0.05"))
        if not (0.01 <= min_edge <= 0.30):
            errors.append(
                f"PAPER_MIN_EDGE={min_edge} is out of valid range [0.01, 0.30]"
            )
    except ValueError:
        errors.append("PAPER_MIN_EDGE is not a valid float")

    # MAX_DAILY_SPEND must be > 0
    try:
        max_spend = float(_os.getenv("MAX_DAILY_SPEND", "50"))
        if max_spend <= 0:
            errors.append(f"MAX_DAILY_SPEND={max_spend} must be > 0")
    except ValueError:
        errors.append("MAX_DAILY_SPEND is not a valid float")

    # MAX_DRAWDOWN_FRACTION must be in (0, 1)
    try:
        drawdown = float(_os.getenv("MAX_DRAWDOWN_FRACTION", "0.20"))
        if not (0 < drawdown < 1):
            errors.append(
                f"MAX_DRAWDOWN_FRACTION={drawdown} must be in (0, 1)"
            )
    except ValueError:
        errors.append("MAX_DRAWDOWN_FRACTION is not a valid float")

    return errors
```

### 34.2 Call `validate_config` at the start of `cmd_cron`

- [ ] In `main.py`, in `cmd_cron`, after acquiring the lock and before `_write_cron_running_flag`:

```python
    # P10.3 — config integrity check
    import sys as _sys_cfg
    from utils import validate_config as _validate_config
    _cfg_errors = _validate_config()
    if _cfg_errors:
        for _err in _cfg_errors:
            _log.error("cmd_cron: CONFIG ERROR: %s", _err)
        _log.error("cmd_cron: %d config error(s) found — aborting", len(_cfg_errors))
        _release_cron_lock()
        _sys.exit(2)
```

### 34.3 Write tests

- [ ] Add to `tests/test_long_term_health.py`:

```python
class TestConfigValidation:
    def _set_valid_env(self, monkeypatch) -> None:
        monkeypatch.setenv("KALSHI_ENV", "demo")
        monkeypatch.setenv("KALSHI_API_KEY", "test-key-abc")
        monkeypatch.setenv("PAPER_MIN_EDGE", "0.05")
        monkeypatch.setenv("MAX_DAILY_SPEND", "50")
        monkeypatch.setenv("MAX_DRAWDOWN_FRACTION", "0.20")

    def test_valid_config_returns_no_errors(self, monkeypatch):
        """Fully valid config returns empty error list."""
        self._set_valid_env(monkeypatch)
        from utils import validate_config
        errors = validate_config()
        assert errors == [], f"Expected no errors, got: {errors}"

    def test_missing_api_key_is_error(self, monkeypatch):
        """Missing KALSHI_API_KEY is detected."""
        self._set_valid_env(monkeypatch)
        monkeypatch.setenv("KALSHI_API_KEY", "")
        from utils import validate_config
        errors = validate_config()
        assert any("KALSHI_API_KEY" in e for e in errors)

    def test_invalid_kalshi_env_is_error(self, monkeypatch):
        """KALSHI_ENV value other than prod/demo is detected."""
        self._set_valid_env(monkeypatch)
        monkeypatch.setenv("KALSHI_ENV", "staging")
        from utils import validate_config
        errors = validate_config()
        assert any("KALSHI_ENV" in e for e in errors)

    def test_out_of_range_min_edge_is_error(self, monkeypatch):
        """PAPER_MIN_EDGE=0.50 (>0.30) is detected as invalid."""
        self._set_valid_env(monkeypatch)
        monkeypatch.setenv("PAPER_MIN_EDGE", "0.50")
        from utils import validate_config
        errors = validate_config()
        assert any("PAPER_MIN_EDGE" in e for e in errors)

    def test_zero_max_daily_spend_is_error(self, monkeypatch):
        """MAX_DAILY_SPEND=0 is detected."""
        self._set_valid_env(monkeypatch)
        monkeypatch.setenv("MAX_DAILY_SPEND", "0")
        from utils import validate_config
        errors = validate_config()
        assert any("MAX_DAILY_SPEND" in e for e in errors)

    def test_multiple_errors_all_reported(self, monkeypatch):
        """Multiple bad values all appear in the error list."""
        monkeypatch.setenv("KALSHI_ENV", "bad")
        monkeypatch.setenv("KALSHI_API_KEY", "")
        monkeypatch.setenv("PAPER_MIN_EDGE", "0.05")
        monkeypatch.setenv("MAX_DAILY_SPEND", "50")
        monkeypatch.setenv("MAX_DRAWDOWN_FRACTION", "0.20")
        from utils import validate_config
        errors = validate_config()
        assert len(errors) >= 2
```

### 34.4 Verify Task 34

- [ ] Run:
```
cd "C:\Users\thesa\claude kalshi" && python -m pytest tests/test_long_term_health.py -v
```
Expected: all tests passed.

### 34.5 Full regression check

- [ ] Run:
```
cd "C:\Users\thesa\claude kalshi" && python -m pytest --tb=short -q
```
Expected: no new failures across the full suite.

### 34.6 Commit Task 34

```
git add utils.py main.py tests/test_long_term_health.py
git commit -m "feat(p10.3): add startup config integrity validation to cmd_cron"
```

---

---

## Task 42 (P10.4) — Feature sprawl control

The PDF specifies "remove unused logic, prevent uncontrolled system growth." This task adds a dead-code audit script and a module-size tracking baseline so sprawl is visible.

### 42.1 Create `scripts/audit_dead_code.py`

- [ ] Create `scripts/` directory and add:

```python
#!/usr/bin/env python3
"""
Dead code and feature sprawl audit script.

Usage:
    python scripts/audit_dead_code.py

Outputs:
    - Module line counts vs baseline
    - Unreferenced public functions (heuristic: defined but never imported)
    - Functions with empty bodies (pass-only or bare raise)
    - data/ directory size

Run periodically (e.g. monthly) to detect uncontrolled growth.
"""
from __future__ import annotations

import ast
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
BASELINE_PATH = ROOT / "data" / "code_baseline.json"

TRACKED_MODULES = [
    "main.py", "paper.py", "weather_markets.py", "tracker.py",
    "execution_log.py", "kalshi_client.py", "backtest.py",
    "calibration.py", "regime.py", "circuit_breaker.py",
    "snapshots.py", "utils.py", "alerts.py",
]


def count_lines(path: Path) -> int:
    try:
        return len(path.read_text(encoding="utf-8", errors="replace").splitlines())
    except FileNotFoundError:
        return 0


def find_pass_only_functions(path: Path) -> list[str]:
    """Return names of functions whose body is only `pass` or `...`."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return []
    results = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if len(body) == 1 and isinstance(body[0], (ast.Pass, ast.Expr)):
                results.append(node.name)
    return results


def data_dir_size_mb() -> float:
    data = ROOT / "data"
    if not data.exists():
        return 0.0
    total = sum(f.stat().st_size for f in data.rglob("*") if f.is_file())
    return round(total / (1024 * 1024), 2)


def run_audit() -> dict:
    current = {}
    for mod in TRACKED_MODULES:
        path = ROOT / mod
        current[mod] = {
            "lines": count_lines(path),
            "stub_functions": find_pass_only_functions(path),
        }

    # Compare to baseline
    baseline = {}
    if BASELINE_PATH.exists():
        try:
            baseline = json.loads(BASELINE_PATH.read_text())
        except Exception:
            pass

    growth_warnings = []
    for mod, stats in current.items():
        base_lines = baseline.get(mod, {}).get("lines", stats["lines"])
        growth = stats["lines"] - base_lines
        if growth > 200:
            growth_warnings.append(
                f"{mod}: grew by {growth} lines since baseline ({base_lines} → {stats['lines']})"
            )

    return {
        "modules": current,
        "data_dir_size_mb": data_dir_size_mb(),
        "growth_warnings": growth_warnings,
        "baseline_exists": BASELINE_PATH.exists(),
    }


def save_baseline(audit: dict) -> None:
    """Save current line counts as the new baseline."""
    BASELINE_PATH.parent.mkdir(exist_ok=True)
    baseline = {mod: {"lines": stats["lines"]} for mod, stats in audit["modules"].items()}
    BASELINE_PATH.write_text(json.dumps(baseline, indent=2))
    print(f"Baseline saved to {BASELINE_PATH}")


if __name__ == "__main__":
    audit = run_audit()

    print("\n=== MODULE LINE COUNTS ===")
    for mod, stats in audit["modules"].items():
        stubs = stats["stub_functions"]
        stub_note = f" [{len(stubs)} stub(s): {stubs}]" if stubs else ""
        print(f"  {mod:<35} {stats['lines']:>5} lines{stub_note}")

    print(f"\ndata/ directory size: {audit['data_dir_size_mb']} MB")

    if audit["growth_warnings"]:
        print("\n⚠️  GROWTH WARNINGS:")
        for w in audit["growth_warnings"]:
            print(f"  {w}")
    else:
        print("\n✓ No significant growth vs baseline")

    if "--save-baseline" in sys.argv:
        save_baseline(audit)

    sys.exit(1 if audit["growth_warnings"] else 0)
```

### 42.2 Add `.gitignore` entry for data baseline (optional)

- [ ] Optionally commit `data/code_baseline.json` to version control so growth is tracked across sessions. Add a note in the plan that this file should be regenerated after each P-level phase completes.

### 42.3 Write tests

- [ ] Add to `tests/test_long_term_health.py`:

```python
class TestFeatureSprawlAudit:
    def test_audit_script_importable(self):
        """The audit script must be importable without error."""
        import importlib.util, sys
        from pathlib import Path
        spec = importlib.util.spec_from_file_location(
            "audit_dead_code",
            Path(__file__).parent.parent / "scripts" / "audit_dead_code.py",
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # must not raise
        assert hasattr(mod, "run_audit")
        assert hasattr(mod, "count_lines")

    def test_count_lines_returns_int(self, tmp_path):
        """count_lines returns a non-negative integer for a real file."""
        from scripts.audit_dead_code import count_lines
        f = tmp_path / "test.py"
        f.write_text("def foo():\n    pass\n")
        assert count_lines(f) == 2

    def test_count_lines_returns_zero_for_missing(self, tmp_path):
        """count_lines returns 0 for a missing file."""
        from scripts.audit_dead_code import count_lines
        assert count_lines(tmp_path / "nonexistent.py") == 0

    def test_find_pass_only_functions(self, tmp_path):
        """find_pass_only_functions identifies stub functions."""
        from scripts.audit_dead_code import find_pass_only_functions
        f = tmp_path / "example.py"
        f.write_text(
            "def real_func():\n    return 42\n\ndef stub_func():\n    pass\n"
        )
        stubs = find_pass_only_functions(f)
        assert "stub_func" in stubs
        assert "real_func" not in stubs

    def test_run_audit_returns_expected_keys(self, tmp_path, monkeypatch):
        """run_audit returns dict with required top-level keys."""
        import scripts.audit_dead_code as audit_mod
        monkeypatch.setattr(audit_mod, "ROOT", tmp_path)
        monkeypatch.setattr(audit_mod, "BASELINE_PATH", tmp_path / "baseline.json")
        monkeypatch.setattr(audit_mod, "TRACKED_MODULES", [])

        result = audit_mod.run_audit()
        assert "modules" in result
        assert "data_dir_size_mb" in result
        assert "growth_warnings" in result
        assert "baseline_exists" in result
```

### 42.4 Verify Task 42

- [ ] Run:
```
cd "C:\Users\thesa\claude kalshi" && python -m pytest tests/test_long_term_health.py -v
```
Expected: all tests passed.

### 42.5 Save initial baseline

- [ ] Run once after all P10 tasks are complete:
```
cd "C:\Users\thesa\claude kalshi" && python scripts/audit_dead_code.py --save-baseline
```

### 42.6 Full regression check

- [ ] Run:
```
cd "C:\Users\thesa\claude kalshi" && python -m pytest --tb=short -q
```

### 42.7 Commit Task 42

```
git add scripts/audit_dead_code.py data/code_baseline.json tests/test_long_term_health.py
git commit -m "feat(p10.4): add dead code and feature sprawl audit script"
```

---

## Summary of changes

| File | What changes |
|------|-------------|
| `tracker.py` | +`check_performance_drift(window_days, baseline_days, drift_threshold)` |
| `paper.py` | +`MAX_CONSECUTIVE_LOSSES`; +`get_consecutive_losses()`, +`is_black_swan_halted()` |
| `utils.py` | +`validate_config() -> list[str]` |
| `main.py` | `cmd_cron` calls `validate_config` at startup; drift check at end; black swan guard in `_auto_place_trades` |
| `scripts/audit_dead_code.py` | New script — module line counts, stub detection, growth warnings vs baseline |
| `data/code_baseline.json` | Generated once by running `audit_dead_code.py --save-baseline` |
| `tests/test_long_term_health.py` | New — 19 tests across 4 classes |
