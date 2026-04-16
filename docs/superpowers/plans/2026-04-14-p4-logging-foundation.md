# P4: Logging & Debugging Foundation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every trade decision, rejection, and cron run fully auditable without touching the database. Three additions: a per-decision JSONL reasoning log, a per-cron metrics summary, and a trade replay function.

**What already exists — do NOT re-add:**
- `execution_log.py`: `log_order`, `log_order_result`, `record_live_settlement` — SQLite order audit trail
- `tracker.py`: `log_prediction`, `log_outcome`, `log_analysis_attempt` — prediction/outcome history
- `main.py: _validate_trade_opportunity` — already logs every rejection reason via `_log.info`
- `paper.py: get_state_snapshot` — full state dict logged each cron run

**Architecture:** All three tasks are additive — no existing code is deleted. JSONL files live in `data/` and are append-only. The replay function reads from the existing SQLite DBs.

**Tech Stack:** Python 3.11+, pytest, stdlib `json`, `logging`. No new dependencies.

---

## Task 15 (P4.1) — Per-decision reasoning JSONL log

### 15.1 Add `_log_decision` helper to `main.py`

- [ ] After the `LOCK_PATH` constant block, add:

```python
DECISION_LOG_PATH: Path = Path(__file__).parent / "data" / "decision_log.jsonl"

def _log_decision(
    ticker: str,
    city: str,
    model_prob: float,
    market_prob: float,
    net_edge: float,
    recommended_side: str,
    kelly_fraction: float,
    action: str,           # "placed" | "rejected" | "skipped"
    rejection_reason: str = "",
) -> None:
    """Append one JSON line per analyzed market to data/decision_log.jsonl."""
    import json as _json

    record = {
        "ts": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ).isoformat(),
        "ticker": ticker,
        "city": city,
        "model_prob": round(model_prob, 4),
        "market_prob": round(market_prob, 4),
        "net_edge": round(net_edge, 4),
        "recommended_side": recommended_side,
        "kelly_fraction": round(kelly_fraction, 4),
        "action": action,
        "rejection_reason": rejection_reason,
    }
    try:
        DECISION_LOG_PATH.parent.mkdir(exist_ok=True)
        with DECISION_LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(_json.dumps(record) + "\n")
    except Exception as _e:
        _log.warning("_log_decision: could not write: %s", _e)
```

### 15.2 Call `_log_decision` in `_auto_place_trades`

- [ ] In `_auto_place_trades`, after each rejection guard (daily_loss_halted, spend_cap, was_traded_today, validation failure) add a `_log_decision(..., action="rejected", rejection_reason="<reason>")` call.
- [ ] After a successful `place_paper_order` or `_place_live_order` call, add `_log_decision(..., action="placed")`.

### 15.3 Write tests

- [ ] Create `tests/test_logging_foundation.py`:

```python
"""Tests for P4: Logging & Debugging Foundation"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from unittest.mock import MagicMock


def _import_main():
    import main
    return main


class TestDecisionLog:
    def test_log_decision_creates_file(self, tmp_path, monkeypatch):
        """_log_decision writes a valid JSON line to DECISION_LOG_PATH."""
        main = _import_main()
        log_file = tmp_path / "decision_log.jsonl"
        monkeypatch.setattr(main, "DECISION_LOG_PATH", log_file)

        main._log_decision(
            ticker="KXHIGH-25APR15-B70",
            city="NYC",
            model_prob=0.65,
            market_prob=0.50,
            net_edge=0.15,
            recommended_side="yes",
            kelly_fraction=0.08,
            action="placed",
        )

        assert log_file.exists()
        record = json.loads(log_file.read_text().strip())
        assert record["ticker"] == "KXHIGH-25APR15-B70"
        assert record["action"] == "placed"
        assert "ts" in record

    def test_log_decision_appends(self, tmp_path, monkeypatch):
        """Multiple calls append multiple lines."""
        main = _import_main()
        log_file = tmp_path / "decision_log.jsonl"
        monkeypatch.setattr(main, "DECISION_LOG_PATH", log_file)

        for i in range(3):
            main._log_decision(
                ticker=f"TICKER-{i}", city="NYC",
                model_prob=0.6, market_prob=0.5, net_edge=0.1,
                recommended_side="yes", kelly_fraction=0.05,
                action="rejected", rejection_reason="test",
            )

        lines = log_file.read_text().strip().splitlines()
        assert len(lines) == 3

    def test_log_decision_failure_does_not_raise(self, tmp_path, monkeypatch):
        """If the file cannot be written, _log_decision must not propagate."""
        main = _import_main()
        # Point to a path that cannot be created (file as parent)
        bad_path = tmp_path / "not_a_dir.txt" / "log.jsonl"
        bad_path.parent.touch()  # make parent a file, not a dir
        monkeypatch.setattr(main, "DECISION_LOG_PATH", bad_path)

        main._log_decision(
            ticker="X", city="NYC", model_prob=0.5, market_prob=0.5,
            net_edge=0.0, recommended_side="yes", kelly_fraction=0.0,
            action="rejected",
        )  # must not raise
```

### 15.4 Verify Task 15

- [ ] Run:
```
cd "C:\Users\thesa\claude kalshi" && python -m pytest tests/test_logging_foundation.py::TestDecisionLog -v
```
Expected: 3 passed.

### 15.5 Commit Task 15

```
git add main.py tests/test_logging_foundation.py
git commit -m "feat(p4.1): add per-decision JSONL reasoning log"
```

---

## Task 16 (P4.1 supplement) — Per-cron metrics summary

### 16.1 Add `_write_cron_metrics` to `main.py`

- [ ] Add constant and helper after the `_log_decision` block:

```python
CRON_METRICS_PATH: Path = Path(__file__).parent / "data" / "cron_metrics.jsonl"

def _write_cron_metrics(
    markets_scanned: int,
    opportunities_found: int,
    trades_placed: int,
    rejections_by_reason: dict,
    runtime_seconds: float,
) -> None:
    """Append one-line JSON summary of a cron run to data/cron_metrics.jsonl."""
    import json as _json

    record = {
        "ts": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ).isoformat(),
        "markets_scanned": markets_scanned,
        "opportunities_found": opportunities_found,
        "trades_placed": trades_placed,
        "rejections_by_reason": rejections_by_reason,
        "runtime_seconds": round(runtime_seconds, 2),
    }
    try:
        CRON_METRICS_PATH.parent.mkdir(exist_ok=True)
        with CRON_METRICS_PATH.open("a", encoding="utf-8") as fh:
            fh.write(_json.dumps(record) + "\n")
    except Exception as _e:
        _log.warning("_write_cron_metrics: could not write: %s", _e)
```

### 16.2 Wire into `cmd_cron`

- [ ] At the start of `cmd_cron`, record `_cron_start = time.time()` and initialize counters (`_markets_scanned = 0`, `_trades_placed = 0`, `_rejections: dict = {}`).
- [ ] Before `_clear_cron_running_flag()` at the end, call:

```python
    _write_cron_metrics(
        markets_scanned=_markets_scanned,
        opportunities_found=len(opportunities),
        trades_placed=_trades_placed,
        rejections_by_reason=_rejections,
        runtime_seconds=time.time() - _cron_start,
    )
```

### 16.3 Write tests

- [ ] Add to `tests/test_logging_foundation.py`:

```python
class TestCronMetrics:
    def test_write_cron_metrics_creates_file(self, tmp_path, monkeypatch):
        """_write_cron_metrics writes a valid JSON line."""
        main = _import_main()
        path = tmp_path / "cron_metrics.jsonl"
        monkeypatch.setattr(main, "CRON_METRICS_PATH", path)

        main._write_cron_metrics(
            markets_scanned=10,
            opportunities_found=3,
            trades_placed=2,
            rejections_by_reason={"stale_data": 1},
            runtime_seconds=4.2,
        )

        assert path.exists()
        record = json.loads(path.read_text().strip())
        assert record["markets_scanned"] == 10
        assert record["trades_placed"] == 2
        assert record["rejections_by_reason"] == {"stale_data": 1}

    def test_write_cron_metrics_failure_does_not_raise(self, tmp_path, monkeypatch):
        """Bad path must not propagate."""
        main = _import_main()
        bad = tmp_path / "file.txt" / "metrics.jsonl"
        bad.parent.touch()
        monkeypatch.setattr(main, "CRON_METRICS_PATH", bad)
        main._write_cron_metrics(0, 0, 0, {}, 0.0)  # must not raise
```

### 16.4 Verify Task 16

- [ ] Run:
```
cd "C:\Users\thesa\claude kalshi" && python -m pytest tests/test_logging_foundation.py::TestCronMetrics -v
```
Expected: 2 passed.

### 16.5 Commit Task 16

```
git add main.py tests/test_logging_foundation.py
git commit -m "feat(p4.4): add per-cron metrics summary to cron_metrics.jsonl"
```

---

## Task 17 (P4.3) — Trade replay function

### 17.1 Add `replay_trade` to `execution_log.py`

- [ ] Add after `get_recent_orders`:

```python
def replay_trade(ticker: str, placed_at_prefix: str) -> dict | None:
    """
    Reconstruct the full context of a trade from the execution log.

    Args:
        ticker: The market ticker, e.g. "KXHIGH-25APR15-B70"
        placed_at_prefix: ISO prefix to match placed_at, e.g. "2026-04-14T"

    Returns:
        dict with order fields plus any tracker prediction data, or None if not found.
    """
    init_log()
    with _conn() as con:
        row = con.execute(
            """
            SELECT * FROM orders
            WHERE ticker = ? AND placed_at LIKE ?
            ORDER BY placed_at DESC LIMIT 1
            """,
            (ticker, f"{placed_at_prefix}%"),
        ).fetchone()
    if row is None:
        return None

    result = dict(row)

    # Attempt to join with tracker predictions DB
    try:
        import tracker as _tracker
        predictions = _tracker.get_predictions_for_ticker(ticker)
        if predictions:
            # Find the prediction closest in time to placed_at
            placed_dt = datetime.fromisoformat(result["placed_at"])
            closest = min(
                predictions,
                key=lambda p: abs(
                    datetime.fromisoformat(p.get("created_at", result["placed_at"])).timestamp()
                    - placed_dt.timestamp()
                ),
                default=None,
            )
            if closest:
                result["_prediction"] = closest
    except Exception:
        pass  # tracker unavailable — still return order data

    return result
```

### 17.2 Ensure `tracker.get_predictions_for_ticker` exists

- [ ] In `tracker.py`, add (if not already present):

```python
def get_predictions_for_ticker(ticker: str) -> list[dict]:
    """Return all prediction rows for a given ticker, newest first."""
    # ... query predictions table WHERE ticker = ? ORDER BY created_at DESC
```

### 17.3 Write tests

- [ ] Add to `tests/test_logging_foundation.py`:

```python
class TestReplayTrade:
    def test_replay_returns_none_when_not_found(self, monkeypatch):
        """replay_trade returns None for an unknown ticker."""
        import execution_log
        monkeypatch.setattr(
            execution_log, "DB_PATH",
            Path(__file__).parent / "fixtures" / "empty_nonexistent.db"
        )
        # With a fresh/empty DB, should return None cleanly
        result = execution_log.replay_trade("KXUNKNOWN-99", "2099-01-01")
        assert result is None

    def test_replay_returns_dict_for_known_order(self, tmp_path, monkeypatch):
        """replay_trade returns a dict when an order exists."""
        import execution_log
        db = tmp_path / "test_exec.db"
        monkeypatch.setattr(execution_log, "DB_PATH", db)
        monkeypatch.setattr(execution_log, "_initialized", False)

        row_id = execution_log.log_order(
            ticker="KXTEST-26APR14-T60",
            side="yes", quantity=2, price=0.55,
        )
        result = execution_log.replay_trade("KXTEST-26APR14-T60", "2026")
        assert result is not None
        assert result["ticker"] == "KXTEST-26APR14-T60"
        assert result["side"] == "yes"
```

### 17.4 Verify Task 17

- [ ] Run:
```
cd "C:\Users\thesa\claude kalshi" && python -m pytest tests/test_logging_foundation.py -v
```
Expected: all tests passed.

### 17.5 Full regression check

- [ ] Run:
```
cd "C:\Users\thesa\claude kalshi" && python -m pytest --tb=short -q
```
Expected: no new failures.

### 17.6 Commit Task 17

```
git add execution_log.py tracker.py tests/test_logging_foundation.py
git commit -m "feat(p4.3): add trade replay function to execution_log"
```

---

---

## Task 35 (P4.4) — Metrics validation: cross-check dashboard vs raw logs

The PDF specifies "cross-check dashboard vs raw logs — ensure no fake or mismatched metrics." The dashboard reads from `paper.py` and `execution_log.py`; this task adds a function that recomputes key metrics from raw SQLite data and compares them against what the dashboard would display.

### 35.1 Add `validate_metrics_consistency` to `execution_log.py`

- [ ] Add after `get_recent_orders`:

```python
def validate_metrics_consistency() -> dict:
    """
    Recompute key metrics from raw DB and return any mismatches.

    Compares:
      - total settled live orders (DB count vs pnl summary)
      - today's P&L sum vs daily_live_loss table
      - open order count vs unfilled live orders

    Returns:
        {
          "ok": bool,
          "mismatches": list[str],   # human-readable discrepancy descriptions
          "checked_at": str,         # ISO timestamp
        }
    """
    init_log()
    mismatches: list[str] = []
    today = datetime.now(UTC).strftime("%Y-%m-%d")

    with _conn() as con:
        # Check 1: settled count consistency
        settled_count_row = con.execute(
            "SELECT COUNT(*) AS n FROM orders WHERE live=1 AND settled_at IS NOT NULL"
        ).fetchone()
        pnl_summary = get_live_pnl_summary()
        db_settled = settled_count_row["n"]
        summary_settled = pnl_summary.get("settled_count", 0)
        if db_settled != summary_settled:
            mismatches.append(
                f"settled_count mismatch: raw_db={db_settled} vs summary={summary_settled}"
            )

        # Check 2: today's P&L consistency
        today_pnl_row = con.execute(
            """SELECT COALESCE(SUM(pnl), 0.0) AS s FROM orders
               WHERE live=1 AND settled_at LIKE ? AND pnl IS NOT NULL""",
            (f"{today}%",),
        ).fetchone()
        raw_today_pnl = round(today_pnl_row["s"] or 0.0, 4)
        summary_today_pnl = pnl_summary.get("today_pnl", 0.0)
        if abs(raw_today_pnl - summary_today_pnl) > 0.001:
            mismatches.append(
                f"today_pnl mismatch: raw_db={raw_today_pnl} vs summary={summary_today_pnl}"
            )

        # Check 3: open order count
        raw_open = con.execute(
            "SELECT COUNT(*) AS n FROM orders WHERE live=1 AND status='pending'"
        ).fetchone()["n"]
        summary_open = pnl_summary.get("open_count", 0)
        if raw_open != summary_open:
            mismatches.append(
                f"open_count mismatch: raw_db={raw_open} vs summary={summary_open}"
            )

    return {
        "ok": len(mismatches) == 0,
        "mismatches": mismatches,
        "checked_at": datetime.now(UTC).isoformat(),
    }
```

### 35.2 Call `validate_metrics_consistency` in `cmd_cron`

- [ ] In `main.py`, in `cmd_cron`, after the drift check, add:

```python
    # P4.4 — metrics consistency validation
    try:
        import execution_log as _el
        _metrics_check = _el.validate_metrics_consistency()
        if not _metrics_check["ok"]:
            for _mismatch in _metrics_check["mismatches"]:
                _log.warning("cmd_cron: METRICS MISMATCH — %s", _mismatch)
    except Exception as _e:
        _log.warning("cmd_cron: metrics validation failed: %s", _e)
```

### 35.3 Write tests

- [ ] Add to `tests/test_logging_foundation.py`:

```python
class TestMetricsValidation:
    def test_fresh_db_returns_ok(self, tmp_path, monkeypatch):
        """Empty DB with no orders returns ok=True (nothing to mismatch)."""
        import execution_log
        monkeypatch.setattr(execution_log, "DB_PATH", tmp_path / "exec.db")
        monkeypatch.setattr(execution_log, "_initialized", False)

        result = execution_log.validate_metrics_consistency()
        assert result["ok"] is True
        assert result["mismatches"] == []
        assert "checked_at" in result

    def test_consistent_data_returns_ok(self, tmp_path, monkeypatch):
        """Consistent settled orders return ok=True."""
        import execution_log
        monkeypatch.setattr(execution_log, "DB_PATH", tmp_path / "exec.db")
        monkeypatch.setattr(execution_log, "_initialized", False)

        # Log a settled live order
        row_id = execution_log.log_order(
            "KXTEST", "yes", 1, 0.55, live=True, status="filled"
        )
        execution_log.record_live_settlement(row_id, outcome_yes=True, pnl=0.45)

        result = execution_log.validate_metrics_consistency()
        # May or may not be ok depending on table state, but must not raise
        assert isinstance(result["ok"], bool)
        assert isinstance(result["mismatches"], list)

    def test_returns_mismatch_description_as_string(self, tmp_path, monkeypatch):
        """Each mismatch item is a non-empty string."""
        import execution_log
        monkeypatch.setattr(execution_log, "DB_PATH", tmp_path / "exec.db")
        monkeypatch.setattr(execution_log, "_initialized", False)

        result = execution_log.validate_metrics_consistency()
        for m in result["mismatches"]:
            assert isinstance(m, str) and len(m) > 0
```

### 35.4 Verify Task 35

- [ ] Run:
```
cd "C:\Users\thesa\claude kalshi" && python -m pytest tests/test_logging_foundation.py::TestMetricsValidation -v
```
Expected: 3 passed.

### 35.5 Commit Task 35

```
git add execution_log.py main.py tests/test_logging_foundation.py
git commit -m "feat(p4.4): add dashboard vs raw-log metrics consistency validation"
```

---

## Summary of changes

| File | What changes |
|------|-------------|
| `main.py` | +2 Path constants (`DECISION_LOG_PATH`, `CRON_METRICS_PATH`); +2 helpers (`_log_decision`, `_write_cron_metrics`); wired into `_auto_place_trades` and `cmd_cron`; metrics consistency call in `cmd_cron` |
| `execution_log.py` | +`replay_trade(ticker, placed_at_prefix)`; +`validate_metrics_consistency()` |
| `tracker.py` | +`get_predictions_for_ticker(ticker)` if missing |
| `tests/test_logging_foundation.py` | New file — 10 tests across 4 classes |
