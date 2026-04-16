# P8: Monitoring & Control System — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add operator controls that can stop or pause trading instantly without a code deploy. Three additions: a hard kill switch (file-based + API endpoint), a soft pause toggle, and drawdown alert integration.

**What already exists — do NOT re-add:**
- `web_app.py` — Flask dashboard with routes `/`, `/analyze`, `/api/status`, etc.
- `alerts.py: add_alert`, `check_alerts`, `mark_triggered` — price threshold alerts
- `paper.py: is_paused_drawdown`, `is_daily_loss_halted`, `is_streak_paused` — automated halts
- `circuit_breaker.py: CircuitBreaker` — per-source failure isolation

**Architecture:** Kill switch and pause are both file-based (`data/.kill_switch`, `data/.trading_paused`) — same pattern as the cron lock from P3. This keeps them durable across restarts. API endpoints in `web_app.py` create/delete the files. CLI commands in `main.py` do the same.

**Tech Stack:** Python 3.11+, pytest, Flask (already used). No new dependencies.

---

## Task 26 (P8.3) — Hard kill switch

### 26.1 Add `KILL_SWITCH_PATH` constant to `main.py`

- [ ] Near `LOCK_PATH` and `RUNNING_FLAG_PATH`:

```python
# P8.3 — hard kill switch; creates data/.kill_switch to immediately halt all trading
KILL_SWITCH_PATH: Path = Path(__file__).parent / "data" / ".kill_switch"
```

### 26.2 Add guard in `_auto_place_trades`

- [ ] As the very first guard in `_auto_place_trades` (before daily_loss_halted check):

```python
    # P8.3 — hard kill switch
    if KILL_SWITCH_PATH.exists():
        _log.warning(
            "_auto_place_trades: KILL SWITCH ACTIVE — "
            "all trading halted. Delete %s to resume.", KILL_SWITCH_PATH
        )
        return 0
```

### 26.3 Add CLI commands `cmd_halt` and `cmd_resume`

- [ ] After `cmd_shadow` in `main.py`:

```python
def cmd_halt(_client=None) -> None:
    """Activate the kill switch — immediately blocks all trade placement."""
    KILL_SWITCH_PATH.parent.mkdir(exist_ok=True)
    KILL_SWITCH_PATH.write_text(
        __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ).isoformat()
    )
    _log.warning("cmd_halt: kill switch activated at %s", KILL_SWITCH_PATH)
    print(f"KILL SWITCH ON — trading halted. Delete {KILL_SWITCH_PATH} to resume.")


def cmd_resume(_client=None) -> None:
    """Deactivate the kill switch — re-enables trade placement."""
    try:
        KILL_SWITCH_PATH.unlink(missing_ok=True)
        _log.info("cmd_resume: kill switch removed")
        print("Kill switch removed — trading re-enabled.")
    except Exception as _e:
        _log.warning("cmd_resume: could not remove kill switch: %s", _e)
```

- [ ] Wire both into the CLI argument parser.

### 26.4 Add API endpoints to `web_app.py`

- [ ] Add POST routes:

```python
@app.route("/api/halt", methods=["POST"])
def api_halt():
    """Activate kill switch — halts all trading."""
    from pathlib import Path as _Path
    import main as _main
    _main.KILL_SWITCH_PATH.parent.mkdir(exist_ok=True)
    _main.KILL_SWITCH_PATH.write_text(
        __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ).isoformat()
    )
    return {"status": "halted", "kill_switch": str(_main.KILL_SWITCH_PATH)}, 200


@app.route("/api/resume", methods=["POST"])
def api_resume():
    """Deactivate kill switch — re-enables trading."""
    import main as _main
    _main.KILL_SWITCH_PATH.unlink(missing_ok=True)
    return {"status": "resumed"}, 200
```

### 26.5 Write tests

- [ ] Create `tests/test_monitoring.py`:

```python
"""Tests for P8: Monitoring & Control System"""
from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import MagicMock
import time

import pytest


def _make_opp() -> dict:
    return {
        "ticker": "KXHIGH-25APR15-B70",
        "net_edge": 0.20,
        "ci_adjusted_kelly": 0.10,
        "data_fetched_at": time.time(),
        "recommended_side": "yes",
        "market_prob": 0.50,
        "model_consensus": True,
    }


def _patch_guards(monkeypatch) -> None:
    import paper, execution_log
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


class TestKillSwitch:
    def test_kill_switch_blocks_trades(self, tmp_path, monkeypatch):
        """_auto_place_trades returns 0 immediately when kill switch file exists."""
        import main
        ks = tmp_path / ".kill_switch"
        ks.write_text("2026-04-14T00:00:00+00:00")
        monkeypatch.setattr(main, "KILL_SWITCH_PATH", ks)
        _patch_guards(monkeypatch)
        monkeypatch.setattr(main, "_daily_paper_spend", lambda: 0.0)

        result = main._auto_place_trades([_make_opp()], client=None, live=False)
        assert result == 0, "kill switch must block all trades"

    def test_no_kill_switch_allows_trades(self, tmp_path, monkeypatch):
        """Without kill switch file, _auto_place_trades proceeds normally."""
        import main, paper
        ks = tmp_path / ".kill_switch"
        assert not ks.exists()
        monkeypatch.setattr(main, "KILL_SWITCH_PATH", ks)
        _patch_guards(monkeypatch)
        monkeypatch.setattr(main, "_daily_paper_spend", lambda: 0.0)
        monkeypatch.setattr(paper, "place_paper_order",
                            lambda ticker, side, qty, price, **kw: {
                                "id": 1, "ticker": ticker, "side": side,
                                "quantity": qty, "entry_price": price,
                            })

        result = main._auto_place_trades([_make_opp()], client=None, live=False)
        assert result >= 0  # did not short-circuit at kill switch

    def test_kill_switch_logs_warning(self, tmp_path, monkeypatch, caplog):
        """Kill switch must emit a WARNING."""
        import main
        ks = tmp_path / ".kill_switch"
        ks.write_text("active")
        monkeypatch.setattr(main, "KILL_SWITCH_PATH", ks)
        _patch_guards(monkeypatch)
        monkeypatch.setattr(main, "_daily_paper_spend", lambda: 0.0)

        with caplog.at_level(logging.WARNING, logger="main"):
            main._auto_place_trades([_make_opp()], client=None, live=False)

        assert any("kill switch" in m.lower() for m in
                   [r.message for r in caplog.records if r.levelno == logging.WARNING])
```

### 26.6 Verify Task 26

- [ ] Run:
```
cd "C:\Users\thesa\claude kalshi" && python -m pytest tests/test_monitoring.py::TestKillSwitch -v
```
Expected: 3 passed.

### 26.7 Commit Task 26

```
git add main.py web_app.py tests/test_monitoring.py
git commit -m "feat(p8.3): add hard kill switch with CLI commands and API endpoints"
```

---

## Task 27 (P8.4) — Soft trading pause

### 27.1 Add `PAUSE_TRADING_PATH` to `main.py`

- [ ] Next to `KILL_SWITCH_PATH`:

```python
# P8.4 — soft pause; less severe than kill switch; intended for scheduled maintenance
PAUSE_TRADING_PATH: Path = Path(__file__).parent / "data" / ".trading_paused"
```

### 27.2 Add guard in `_auto_place_trades`

- [ ] After the kill switch check:

```python
    # P8.4 — soft pause
    if PAUSE_TRADING_PATH.exists():
        _log.info(
            "_auto_place_trades: trading is paused. Delete %s to resume.",
            PAUSE_TRADING_PATH
        )
        return 0
```

### 27.3 Add CLI commands `cmd_pause` and `cmd_unpause`

- [ ] After `cmd_resume`:

```python
def cmd_pause(_client=None) -> None:
    """Soft-pause trading (less severe than kill switch; survives cron restart)."""
    PAUSE_TRADING_PATH.parent.mkdir(exist_ok=True)
    PAUSE_TRADING_PATH.write_text(
        __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ).isoformat()
    )
    print(f"Trading paused. Delete {PAUSE_TRADING_PATH} or run cmd_unpause to resume.")


def cmd_unpause(_client=None) -> None:
    """Remove the soft pause — re-enables trading."""
    PAUSE_TRADING_PATH.unlink(missing_ok=True)
    print("Trading resumed.")
```

### 27.4 Add API endpoints to `web_app.py`

- [ ] Add:

```python
@app.route("/api/pause", methods=["POST"])
def api_pause():
    import main as _main
    _main.PAUSE_TRADING_PATH.parent.mkdir(exist_ok=True)
    _main.PAUSE_TRADING_PATH.write_text(
        __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ).isoformat()
    )
    return {"status": "paused"}, 200


@app.route("/api/unpause", methods=["POST"])
def api_unpause():
    import main as _main
    _main.PAUSE_TRADING_PATH.unlink(missing_ok=True)
    return {"status": "unpaused"}, 200
```

### 27.5 Write tests

- [ ] Add to `tests/test_monitoring.py`:

```python
class TestSoftPause:
    def test_pause_file_blocks_trades(self, tmp_path, monkeypatch):
        """_auto_place_trades returns 0 when pause file exists."""
        import main
        pause = tmp_path / ".trading_paused"
        pause.write_text("2026-04-14T00:00:00+00:00")
        monkeypatch.setattr(main, "PAUSE_TRADING_PATH", pause)
        monkeypatch.setattr(main, "KILL_SWITCH_PATH", tmp_path / ".no_ks")
        _patch_guards(monkeypatch)
        monkeypatch.setattr(main, "_daily_paper_spend", lambda: 0.0)

        result = main._auto_place_trades([_make_opp()], client=None, live=False)
        assert result == 0

    def test_no_pause_file_allows_trading(self, tmp_path, monkeypatch):
        """Without pause file, trading proceeds."""
        import main, paper
        monkeypatch.setattr(main, "PAUSE_TRADING_PATH", tmp_path / ".not_there")
        monkeypatch.setattr(main, "KILL_SWITCH_PATH", tmp_path / ".no_ks")
        _patch_guards(monkeypatch)
        monkeypatch.setattr(main, "_daily_paper_spend", lambda: 0.0)
        monkeypatch.setattr(paper, "place_paper_order",
                            lambda ticker, side, qty, price, **kw: {
                                "id": 1, "ticker": ticker,
                            })
        result = main._auto_place_trades([_make_opp()], client=None, live=False)
        assert result >= 0
```

### 27.6 Verify Task 27

- [ ] Run:
```
cd "C:\Users\thesa\claude kalshi" && python -m pytest tests/test_monitoring.py::TestSoftPause -v
```
Expected: 2 passed.

### 27.7 Commit Task 27

```
git add main.py web_app.py tests/test_monitoring.py
git commit -m "feat(p8.4): add soft trading pause with CLI and API controls"
```

---

## Task 28 (P8.2) — Drawdown alert integration

### 28.1 Instrument `is_paused_drawdown` in `paper.py`

The existing `is_paused_drawdown()` function checks the drawdown threshold but never calls `alerts.add_alert`. The fix: call `add_alert` when the threshold is first crossed.

- [ ] Add a module-level flag to `paper.py`:

```python
_drawdown_halt_alerted: bool = False
```

- [ ] Modify `is_paused_drawdown()`:

```python
def is_paused_drawdown() -> bool:
    global _drawdown_halt_alerted
    state = get_state_snapshot()
    peak = state.get("peak_balance", 0) or 0
    balance = state.get("balance", 0) or 0
    if peak <= 0:
        return False
    drawdown = (peak - balance) / peak
    halt = drawdown >= DRAWDOWN_HALT_PCT
    if halt and not _drawdown_halt_alerted:
        try:
            import alerts as _alerts
            _alerts.add_alert(
                ticker="SYSTEM",
                condition="drawdown_halt",
                threshold=round(drawdown * 100, 2),
                message=f"Drawdown halt triggered: {drawdown:.1%} >= {DRAWDOWN_HALT_PCT:.1%}",
            )
            _drawdown_halt_alerted = True
        except Exception:
            pass
    if not halt:
        _drawdown_halt_alerted = False  # reset when drawdown recovers
    return halt
```

- [ ] Apply the same pattern to `is_daily_loss_halted()` for the daily loss alert.

### 28.2 Write tests

- [ ] Add to `tests/test_monitoring.py`:

```python
class TestDrawdownAlert:
    def test_add_alert_called_when_drawdown_triggers(self, tmp_path, monkeypatch):
        """alerts.add_alert is called the first time drawdown halt triggers."""
        import paper

        monkeypatch.setattr(paper, "DATA_PATH", tmp_path / "paper.json")
        (tmp_path / "paper.json").write_text(
            '{"_version": 2, "balance": 700.0, "peak_balance": 1000.0, "trades": []}'
        )
        monkeypatch.setattr(paper, "DRAWDOWN_HALT_PCT", 0.20)  # 20% halt
        monkeypatch.setattr(paper, "_drawdown_halt_alerted", False)

        alert_calls: list = []
        import alerts as _alerts
        monkeypatch.setattr(_alerts, "add_alert",
                            lambda **kw: alert_calls.append(kw))

        result = paper.is_paused_drawdown()  # drawdown = 30% > 20% → should halt

        assert result is True
        assert len(alert_calls) == 1, "add_alert must be called once on first trigger"
        assert alert_calls[0]["condition"] == "drawdown_halt"

    def test_add_alert_not_called_twice(self, tmp_path, monkeypatch):
        """add_alert must not spam on every check — only called on first trigger."""
        import paper

        monkeypatch.setattr(paper, "DATA_PATH", tmp_path / "paper.json")
        (tmp_path / "paper.json").write_text(
            '{"_version": 2, "balance": 700.0, "peak_balance": 1000.0, "trades": []}'
        )
        monkeypatch.setattr(paper, "DRAWDOWN_HALT_PCT", 0.20)
        monkeypatch.setattr(paper, "_drawdown_halt_alerted", False)

        alert_calls: list = []
        import alerts as _alerts
        monkeypatch.setattr(_alerts, "add_alert",
                            lambda **kw: alert_calls.append(kw))

        paper.is_paused_drawdown()
        paper.is_paused_drawdown()
        paper.is_paused_drawdown()

        assert len(alert_calls) == 1, "add_alert must only fire once per halt event"
```

### 28.3 Verify Task 28

- [ ] Run:
```
cd "C:\Users\thesa\claude kalshi" && python -m pytest tests/test_monitoring.py -v
```
Expected: all tests passed.

### 28.4 Full regression check

- [ ] Run:
```
cd "C:\Users\thesa\claude kalshi" && python -m pytest --tb=short -q
```

### 28.5 Commit Task 28

```
git add paper.py tests/test_monitoring.py
git commit -m "feat(p8.2): fire alerts.add_alert when drawdown halt activates"
```

---

---

## Task 40 (P8.1) — Dashboard metrics completeness

The PDF lists five required metrics: ROI, win rate, drawdown, **edge accuracy**, and **trade frequency**. The existing dashboard shows ROI/drawdown/win rate but lacks edge accuracy (predicted edge vs actual win rate) and trade frequency (trades/day). This task adds both.

### 40.1 Add `get_edge_accuracy` to `tracker.py`

- [ ] Add after `get_source_sla_summary`:

```python
def get_edge_accuracy(window_days: int = 30) -> dict:
    """
    Compare predicted net_edge (from predictions table) vs actual win rate.

    Edge accuracy = correlation between predicted edge and actual outcome.
    Returns Brier score and calibration error as proxy metrics.

    Returns:
        {
          n_trades, avg_predicted_edge, actual_win_rate,
          edge_accuracy_score,  # 1.0 = perfect, 0.0 = random
          calibration_error,    # abs(avg_predicted_edge - actual_win_rate)
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
            SELECT net_edge, outcome, brier_score
            FROM outcomes
            WHERE created_at >= ? AND net_edge IS NOT NULL AND outcome IS NOT NULL
            """,
            (cutoff,),
        ).fetchall()

    if not rows:
        return {
            "n_trades": 0, "avg_predicted_edge": None,
            "actual_win_rate": None, "edge_accuracy_score": None,
            "calibration_error": None,
        }

    n = len(rows)
    avg_edge = sum(r["net_edge"] for r in rows) / n
    win_rate = sum(1 for r in rows if r["outcome"] == 1) / n
    calibration_error = abs(avg_edge - win_rate)
    # Simple accuracy: 1.0 when predicted edge > 0 matches win
    correct = sum(
        1 for r in rows
        if (r["net_edge"] > 0 and r["outcome"] == 1)
        or (r["net_edge"] <= 0 and r["outcome"] == 0)
    )
    edge_accuracy_score = round(correct / n, 4)

    return {
        "n_trades": n,
        "avg_predicted_edge": round(avg_edge, 4),
        "actual_win_rate": round(win_rate, 4),
        "edge_accuracy_score": edge_accuracy_score,
        "calibration_error": round(calibration_error, 4),
    }
```

### 40.2 Add `get_trade_frequency` to `execution_log.py`

- [ ] Add after `get_recent_orders`:

```python
def get_trade_frequency(window_days: int = 7) -> dict:
    """
    Return trades-per-day statistics over the last window_days.

    Returns:
        {total_trades, window_days, trades_per_day, active_days}
    """
    init_log()
    cutoff = (
        __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
        - __import__("datetime").timedelta(days=window_days)
    ).isoformat()
    with _conn() as con:
        total_row = con.execute(
            "SELECT COUNT(*) AS n FROM orders WHERE placed_at >= ?", (cutoff,)
        ).fetchone()
        day_row = con.execute(
            """SELECT COUNT(DISTINCT DATE(placed_at)) AS active_days
               FROM orders WHERE placed_at >= ?""",
            (cutoff,),
        ).fetchone()

    total = total_row["n"] or 0
    active_days = day_row["active_days"] or 0
    return {
        "total_trades": total,
        "window_days": window_days,
        "trades_per_day": round(total / window_days, 2),
        "active_days": active_days,
    }
```

### 40.3 Expose via `/api/dashboard-metrics` endpoint in `web_app.py`

- [ ] Add:

```python
@app.route("/api/dashboard-metrics")
def api_dashboard_metrics():
    """Return all five required dashboard metrics in one call."""
    import tracker as _tracker
    import execution_log as _el
    import paper as _paper

    state = _paper.get_state_snapshot()
    pnl = _el.get_live_pnl_summary()
    edge_acc = _tracker.get_edge_accuracy(window_days=30)
    freq = _el.get_trade_frequency(window_days=7)

    peak = state.get("peak_balance", 0) or 0
    balance = state.get("balance", 0) or 0
    drawdown = (peak - balance) / peak if peak > 0 else 0.0

    return {
        "roi": pnl.get("total_pnl"),
        "win_rate": edge_acc.get("actual_win_rate"),
        "drawdown_pct": round(drawdown * 100, 2),
        "edge_accuracy_score": edge_acc.get("edge_accuracy_score"),
        "calibration_error": edge_acc.get("calibration_error"),
        "trades_per_day": freq.get("trades_per_day"),
        "total_trades_7d": freq.get("total_trades"),
    }, 200
```

### 40.4 Write tests

- [ ] Add to `tests/test_monitoring.py`:

```python
class TestDashboardMetrics:
    def test_get_trade_frequency_no_trades(self, tmp_path, monkeypatch):
        """No orders → 0 trades_per_day."""
        import execution_log
        monkeypatch.setattr(execution_log, "DB_PATH", tmp_path / "exec.db")
        monkeypatch.setattr(execution_log, "_initialized", False)

        result = execution_log.get_trade_frequency(window_days=7)
        assert result["total_trades"] == 0
        assert result["trades_per_day"] == 0.0

    def test_get_trade_frequency_counts_correctly(self, tmp_path, monkeypatch):
        """Logs 3 orders → total_trades=3."""
        import execution_log
        monkeypatch.setattr(execution_log, "DB_PATH", tmp_path / "exec.db")
        monkeypatch.setattr(execution_log, "_initialized", False)

        for _ in range(3):
            execution_log.log_order("KXTEST", "yes", 1, 0.55)

        result = execution_log.get_trade_frequency(window_days=7)
        assert result["total_trades"] == 3

    def test_get_edge_accuracy_no_data(self, tmp_path, monkeypatch):
        """No outcomes → all None fields, no error."""
        import tracker
        monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "tracker.db")
        monkeypatch.setattr(tracker, "_initialized", False)

        result = tracker.get_edge_accuracy(window_days=30)
        assert result["n_trades"] == 0
        assert result["edge_accuracy_score"] is None
```

### 40.5 Verify Task 40

- [ ] Run:
```
cd "C:\Users\thesa\claude kalshi" && python -m pytest tests/test_monitoring.py::TestDashboardMetrics -v
```
Expected: 3 passed.

### 40.6 Full regression check

- [ ] Run:
```
cd "C:\Users\thesa\claude kalshi" && python -m pytest --tb=short -q
```

### 40.7 Commit Task 40

```
git add tracker.py execution_log.py web_app.py tests/test_monitoring.py
git commit -m "feat(p8.1): add edge accuracy and trade frequency dashboard metrics"
```

---

---

## Task 48 (P8.4) — Time-Limited Manual Overrides

- [ ] **Add** `OVERRIDE_EXPIRY_HOURS` env-var constant to `main.py`.
- [ ] **Add** `_check_override_expiry()` helper to `main.py`.
- [ ] **Call** `_check_override_expiry()` at the start of `_auto_place_trades`.
- [ ] **Append** tests to `tests/test_monitoring.py`.
- [ ] **Verify** by running the Task 48 tests.
- [ ] **Commit** with message `feat(p8.4): add auto-expiry to pause and kill-switch overrides`.

### What is being added

The PDF specifies "logged, reversible, **time-limited** overrides." Tasks 26 and 27 added kill switch and pause (reversible + logged) but no automatic expiry. This task adds: if `PAUSE_TRADING_PATH` or `KILL_SWITCH_PATH` are older than `OVERRIDE_EXPIRY_HOURS`, they are automatically removed with a logged WARNING. This prevents operators accidentally leaving the system halted indefinitely.

### Production code — main.py

```python
# main.py — add near KILL_SWITCH_PATH and PAUSE_TRADING_PATH

OVERRIDE_EXPIRY_HOURS: int = int(os.getenv("OVERRIDE_EXPIRY_HOURS", "24"))


def _check_override_expiry() -> None:
    """
    Auto-expire manual override files (kill switch, pause) after OVERRIDE_EXPIRY_HOURS.

    If an override file exists and is older than OVERRIDE_EXPIRY_HOURS, it is deleted
    and a WARNING is logged. This prevents the system from staying halted indefinitely
    due to a forgotten manual override.

    Called at the start of every _auto_place_trades invocation.
    """
    import time as _time

    expiry_secs = OVERRIDE_EXPIRY_HOURS * 3600
    for flag_path, label in (
        (KILL_SWITCH_PATH, "kill switch"),
        (PAUSE_TRADING_PATH, "trading pause"),
    ):
        if not flag_path.exists():
            continue
        try:
            age_secs = _time.time() - flag_path.stat().st_mtime
            if age_secs >= expiry_secs:
                flag_path.unlink(missing_ok=True)
                _log.warning(
                    "P8.4 override expiry: %s file auto-removed after %.1f hours "
                    "(OVERRIDE_EXPIRY_HOURS=%d). Trading resumes.",
                    label,
                    age_secs / 3600,
                    OVERRIDE_EXPIRY_HOURS,
                )
        except Exception as _e:
            _log.warning("_check_override_expiry: could not check %s: %s", label, _e)
```

### Wiring in `_auto_place_trades` (main.py)

As the very first line of `_auto_place_trades`, before the kill switch guard:

```python
# P8.4 — auto-expire stale manual overrides
_check_override_expiry()
```

### Test code — Task 48

```python
# ── Task 48 (P8.4): Time-limited override auto-expiry ─────────────────────────

class TestOverrideExpiry:
    """_check_override_expiry removes stale override files after OVERRIDE_EXPIRY_HOURS."""

    def test_fresh_override_not_removed(self, tmp_path, monkeypatch):
        """Override file younger than expiry threshold must NOT be deleted."""
        import main

        kill = tmp_path / ".kill_switch"
        kill.write_text("active")  # mtime ≈ now (age ≈ 0s)
        monkeypatch.setattr(main, "KILL_SWITCH_PATH", kill)
        monkeypatch.setattr(main, "PAUSE_TRADING_PATH", tmp_path / ".trading_paused")
        monkeypatch.setattr(main, "OVERRIDE_EXPIRY_HOURS", 24)

        main._check_override_expiry()

        assert kill.exists(), "Fresh override file must not be removed"

    def test_stale_override_auto_removed(self, tmp_path, monkeypatch):
        """Override file older than expiry threshold must be auto-deleted."""
        import os, time, main

        kill = tmp_path / ".kill_switch"
        kill.write_text("active")
        # Back-date mtime by 25 hours
        stale_mtime = time.time() - (25 * 3600)
        os.utime(kill, (stale_mtime, stale_mtime))

        monkeypatch.setattr(main, "KILL_SWITCH_PATH", kill)
        monkeypatch.setattr(main, "PAUSE_TRADING_PATH", tmp_path / ".trading_paused")
        monkeypatch.setattr(main, "OVERRIDE_EXPIRY_HOURS", 24)

        main._check_override_expiry()

        assert not kill.exists(), "Stale override (>24h) must be auto-removed"

    def test_stale_override_logs_warning(self, tmp_path, monkeypatch, caplog):
        """Auto-removal of stale override must emit a WARNING."""
        import os, time, logging, main

        pause = tmp_path / ".trading_paused"
        pause.write_text("active")
        stale_mtime = time.time() - (25 * 3600)
        os.utime(pause, (stale_mtime, stale_mtime))

        monkeypatch.setattr(main, "KILL_SWITCH_PATH", tmp_path / ".kill_switch")
        monkeypatch.setattr(main, "PAUSE_TRADING_PATH", pause)
        monkeypatch.setattr(main, "OVERRIDE_EXPIRY_HOURS", 24)

        with caplog.at_level(logging.WARNING, logger="main"):
            main._check_override_expiry()

        assert any("auto-removed" in r.message for r in caplog.records), \
            "Must log a WARNING when auto-removing stale override"

    def test_no_override_files_is_noop(self, tmp_path, monkeypatch):
        """No override files present must not raise."""
        import main

        monkeypatch.setattr(main, "KILL_SWITCH_PATH", tmp_path / ".kill_switch")
        monkeypatch.setattr(main, "PAUSE_TRADING_PATH", tmp_path / ".trading_paused")
        monkeypatch.setattr(main, "OVERRIDE_EXPIRY_HOURS", 24)

        main._check_override_expiry()  # must not raise
```

### Run command — Task 48

```
cd "C:\Users\thesa\claude kalshi" && python -m pytest tests/test_monitoring.py::TestOverrideExpiry -v
```

### Expected output — Task 48

```
tests/test_monitoring.py::TestOverrideExpiry::test_fresh_override_not_removed PASSED
tests/test_monitoring.py::TestOverrideExpiry::test_stale_override_auto_removed PASSED
tests/test_monitoring.py::TestOverrideExpiry::test_stale_override_logs_warning PASSED
tests/test_monitoring.py::TestOverrideExpiry::test_no_override_files_is_noop PASSED
4 passed in 0.XXs
```

---

## Summary of changes

| File | What changes |
|------|-------------|
| `main.py` | +`KILL_SWITCH_PATH`, +`PAUSE_TRADING_PATH`, +`OVERRIDE_EXPIRY_HOURS`; guards in `_auto_place_trades`; +`cmd_halt`, `cmd_resume`, `cmd_pause`, `cmd_unpause`; +`_check_override_expiry` called at start of `_auto_place_trades` |
| `web_app.py` | +`/api/halt`, `/api/resume`, `/api/pause`, `/api/unpause`; +`/api/dashboard-metrics` |
| `paper.py` | `is_paused_drawdown` / `is_daily_loss_halted` call `alerts.add_alert` on first trigger |
| `tracker.py` | +`get_edge_accuracy(window_days)` |
| `execution_log.py` | +`get_trade_frequency(window_days)` |
| `tests/test_monitoring.py` | New — 14 tests across 5 classes |
