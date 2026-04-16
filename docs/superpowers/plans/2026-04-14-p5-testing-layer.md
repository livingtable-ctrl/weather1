# P5: Testing & Validation Layer — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add shadow mode (simulate trades without placing them) and a parameter sweep harness (auto-test edge threshold ranges). Both build on the existing backtest infrastructure rather than replacing it.

**What already exists — do NOT re-add:**
- `backtest.py: run_backtest`, `run_walk_forward`, `stratified_train_test_split` — full historical replay and walk-forward validation
- `calibration.py` — grid-search blend weight optimizer
- `tests/` — 30+ test files covering paper, tracker, backtest, risk control, execution stability
- `tests/fixtures/` — `regression_baseline.json`, `sample_forecast.json`, `sample_markets.json`

**Architecture:** Shadow mode is a flag on `_auto_place_trades` + a new `cmd_shadow` CLI command. Parameter sweep wraps `run_backtest` in a loop and writes results to `data/sweep_results.json`.

**Tech Stack:** Python 3.11+, pytest, `monkeypatch`, `tmp_path`. No new dependencies.

---

## Task 18 (P5.2) — Shadow mode

### 18.1 Add `SHADOW_LOG_PATH` constant and `_log_shadow_trade` helper to `main.py`

- [ ] After the `CRON_METRICS_PATH` constant, add:

```python
SHADOW_LOG_PATH: Path = Path(__file__).parent / "data" / "shadow_trades.jsonl"

def _log_shadow_trade(
    ticker: str,
    side: str,
    quantity: int,
    price: float,
    net_edge: float,
    kelly_fraction: float,
) -> None:
    """Write a would-be trade to data/shadow_trades.jsonl without touching paper balance."""
    import json as _json

    record = {
        "ts": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ).isoformat(),
        "ticker": ticker,
        "side": side,
        "quantity": quantity,
        "price": price,
        "net_edge": round(net_edge, 4),
        "kelly_fraction": round(kelly_fraction, 4),
        "mode": "shadow",
    }
    try:
        SHADOW_LOG_PATH.parent.mkdir(exist_ok=True)
        with SHADOW_LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(_json.dumps(record) + "\n")
    except Exception as _e:
        _log.warning("_log_shadow_trade: could not write: %s", _e)
```

### 18.2 Add `shadow` parameter to `_auto_place_trades`

- [ ] Change the signature:
```python
def _auto_place_trades(
    opportunities: list[dict],
    client: KalshiClient | None,
    live: bool = False,
    shadow: bool = False,      # ← add this
) -> int:
```

- [ ] In the trade execution branch (where `place_paper_order` or `_place_live_order` would be called), add a check at the top:
```python
if shadow:
    _log_shadow_trade(
        ticker=opp["ticker"],
        side=opp["recommended_side"],
        quantity=qty,
        price=opp["market_prob"],
        net_edge=opp["net_edge"],
        kelly_fraction=opp["ci_adjusted_kelly"],
    )
    placed += 1
    continue
```

### 18.3 Add `cmd_shadow` CLI command

- [ ] After `cmd_cron`, add:

```python
def cmd_shadow(client: KalshiClient) -> None:
    """Run a shadow cron cycle: full decision pipeline, no orders placed or paper balance changed."""
    _log.info("cmd_shadow: starting shadow scan")
    opportunities = get_weather_markets(client)
    placed = _auto_place_trades(opportunities, client=client, live=False, shadow=True)
    _log.info("cmd_shadow: %d shadow trades logged to %s", placed, SHADOW_LOG_PATH)
```

- [ ] Wire `cmd_shadow` into the CLI argument parser (same pattern as `cmd_cron`).

### 18.4 Write tests

- [ ] Create `tests/test_shadow_mode.py`:

```python
"""Tests for P5.2: Shadow mode"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock
import time

import pytest


def _make_opp(ticker: str = "KXHIGH-25APR15-B70") -> dict:
    return {
        "ticker": ticker,
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
                        lambda f, city, date, side="yes": f)
    monkeypatch.setattr(paper, "kelly_quantity",
                        lambda f, price, min_dollars=1.0, cap=None, method=None: 2)
    monkeypatch.setattr(execution_log, "was_traded_today", lambda t, s: False)
    monkeypatch.setattr(execution_log, "was_ordered_this_cycle", lambda t, s, c: False)


class TestShadowMode:
    def test_shadow_never_calls_place_paper_order(self, tmp_path, monkeypatch):
        """shadow=True must never call paper.place_paper_order."""
        import main, paper
        monkeypatch.setattr(main, "SHADOW_LOG_PATH", tmp_path / "shadow.jsonl")
        monkeypatch.setattr(main, "_daily_paper_spend", lambda: 0.0)
        _patch_guards(monkeypatch)

        paper_calls: list = []
        monkeypatch.setattr(paper, "place_paper_order",
                            lambda *a, **kw: paper_calls.append(kw) or {})

        main._auto_place_trades([_make_opp()], client=None, live=False, shadow=True)

        assert paper_calls == [], "place_paper_order must not be called in shadow mode"

    def test_shadow_writes_jsonl(self, tmp_path, monkeypatch):
        """shadow=True writes one line to SHADOW_LOG_PATH."""
        import main
        log_file = tmp_path / "shadow.jsonl"
        monkeypatch.setattr(main, "SHADOW_LOG_PATH", log_file)
        monkeypatch.setattr(main, "_daily_paper_spend", lambda: 0.0)
        _patch_guards(monkeypatch)

        main._auto_place_trades([_make_opp()], client=None, live=False, shadow=True)

        assert log_file.exists(), "shadow log file should be created"
        record = json.loads(log_file.read_text().strip())
        assert record["mode"] == "shadow"
        assert record["ticker"] == "KXHIGH-25APR15-B70"

    def test_shadow_never_calls_place_live_order(self, tmp_path, monkeypatch):
        """shadow=True must never call _place_live_order even if live=True."""
        import main
        monkeypatch.setattr(main, "SHADOW_LOG_PATH", tmp_path / "shadow.jsonl")
        monkeypatch.setattr(main, "_daily_paper_spend", lambda: 0.0)
        _patch_guards(monkeypatch)

        live_calls: list = []
        monkeypatch.setattr(main, "_place_live_order", lambda **kw: live_calls.append(kw) or (False, 0.0))

        main._auto_place_trades([_make_opp()], client=None, live=True, shadow=True)

        assert live_calls == [], "_place_live_order must not be called in shadow mode"
```

### 18.5 Verify Task 18

- [ ] Run:
```
cd "C:\Users\thesa\claude kalshi" && python -m pytest tests/test_shadow_mode.py -v
```
Expected: 3 passed.

### 18.6 Commit Task 18

```
git add main.py tests/test_shadow_mode.py
git commit -m "feat(p5.2): add shadow mode to _auto_place_trades and cmd_shadow command"
```

---

## Task 19 (P5.5) — Parameter sweep testing

### 19.1 Add `sweep_edge_thresholds` to `backtest.py`

- [ ] Add after `run_walk_forward`:

```python
def sweep_edge_thresholds(
    min_edge_range: list[float],
    output_path: str | None = None,
) -> list[dict]:
    """
    Run run_backtest for each min_edge value and return comparative results.

    Args:
        min_edge_range: list of min_edge floats to test, e.g. [0.05, 0.08, 0.10, 0.15]
        output_path: if provided, write JSON results to this path

    Returns:
        list of dicts, one per min_edge value:
          {min_edge, brier, win_rate, n_trades, roi, sharpe (if available)}
    """
    import json as _json
    from pathlib import Path as _Path

    results = []
    for edge in min_edge_range:
        try:
            result = run_backtest(min_edge_override=edge)
            results.append({
                "min_edge": edge,
                "brier": result.get("brier"),
                "win_rate": result.get("win_rate"),
                "n_trades": result.get("n_trades"),
                "roi": result.get("roi"),
            })
        except Exception as _e:
            results.append({"min_edge": edge, "error": str(_e)})

    if output_path:
        _Path(output_path).parent.mkdir(exist_ok=True)
        _Path(output_path).write_text(_json.dumps(results, indent=2))

    return results
```

- [ ] Update `run_backtest` signature to accept `min_edge_override: float | None = None` and use it in place of the env-var `PAPER_MIN_EDGE` when set.

### 19.2 Write tests

- [ ] Create `tests/test_parameter_sweep.py`:

```python
"""Tests for P5.5: Parameter sweep testing"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch


class TestSweepEdgeThresholds:
    def _fake_run_backtest(self, min_edge_override=None):
        """Simulate run_backtest: higher min_edge → fewer trades."""
        n = max(0, int(50 - (min_edge_override or 0.05) * 200))
        return {"brier": 0.20, "win_rate": 0.55, "n_trades": n, "roi": 0.10}

    def test_returns_one_result_per_edge(self, monkeypatch):
        """sweep_edge_thresholds returns one entry per input value."""
        import backtest
        monkeypatch.setattr(backtest, "run_backtest", self._fake_run_backtest)

        results = backtest.sweep_edge_thresholds([0.05, 0.10, 0.15])
        assert len(results) == 3
        assert results[0]["min_edge"] == 0.05
        assert results[2]["min_edge"] == 0.15

    def test_higher_edge_produces_fewer_trades(self, monkeypatch):
        """Higher min_edge must not produce more trades than a lower one."""
        import backtest
        monkeypatch.setattr(backtest, "run_backtest", self._fake_run_backtest)

        results = backtest.sweep_edge_thresholds([0.05, 0.10, 0.20])
        trade_counts = [r["n_trades"] for r in results if "n_trades" in r]
        assert trade_counts == sorted(trade_counts, reverse=True), (
            "trade count must be non-increasing as min_edge increases"
        )

    def test_writes_json_output(self, tmp_path, monkeypatch):
        """sweep_edge_thresholds writes results to output_path when provided."""
        import backtest
        monkeypatch.setattr(backtest, "run_backtest", self._fake_run_backtest)

        out = tmp_path / "sweep_results.json"
        backtest.sweep_edge_thresholds([0.05, 0.10], output_path=str(out))

        assert out.exists()
        data = json.loads(out.read_text())
        assert isinstance(data, list)
        assert len(data) == 2

    def test_run_backtest_error_is_captured(self, monkeypatch):
        """If run_backtest raises for one edge, the error is captured not propagated."""
        import backtest

        def _explode(min_edge_override=None):
            if min_edge_override == 0.10:
                raise RuntimeError("db locked")
            return {"brier": 0.20, "win_rate": 0.55, "n_trades": 10, "roi": 0.05}

        monkeypatch.setattr(backtest, "run_backtest", _explode)
        results = backtest.sweep_edge_thresholds([0.05, 0.10, 0.15])
        assert len(results) == 3
        error_entry = next(r for r in results if r["min_edge"] == 0.10)
        assert "error" in error_entry
```

### 19.3 Verify Task 19

- [ ] Run:
```
cd "C:\Users\thesa\claude kalshi" && python -m pytest tests/test_parameter_sweep.py -v
```
Expected: 4 passed.

### 19.4 Full regression check

- [ ] Run:
```
cd "C:\Users\thesa\claude kalshi" && python -m pytest --tb=short -q
```
Expected: no new failures.

### 19.5 Commit Task 19

```
git add backtest.py tests/test_parameter_sweep.py
git commit -m "feat(p5.5): add edge threshold parameter sweep to backtest.py"
```

---

---

## Task 36 (P5.3) — A/B testing system

### 36.1 Add `run_ab_test` to `backtest.py`

- [ ] Add after `sweep_edge_thresholds`:

```python
def run_ab_test(
    config_a: dict,
    config_b: dict,
    output_path: str | None = None,
) -> dict:
    """
    Run run_backtest with two different config dicts and compare results directly.

    Each config dict may contain keys overriding backtest parameters:
      min_edge_override, kelly_fraction, strategy_name (label only)

    Returns:
        {
          "a": {strategy_name, min_edge, brier, win_rate, n_trades, roi},
          "b": {strategy_name, min_edge, brier, win_rate, n_trades, roi},
          "winner": "a" | "b" | "tie",
          "winner_metric": "brier",  # metric used to determine winner
        }
    """
    import json as _json
    from pathlib import Path as _Path

    def _run(cfg: dict) -> dict:
        result = run_backtest(
            min_edge_override=cfg.get("min_edge_override"),
        )
        return {
            "strategy_name": cfg.get("strategy_name", "unnamed"),
            "min_edge": cfg.get("min_edge_override"),
            "brier": result.get("brier"),
            "win_rate": result.get("win_rate"),
            "n_trades": result.get("n_trades"),
            "roi": result.get("roi"),
        }

    result_a = _run(config_a)
    result_b = _run(config_b)

    # Lower Brier = better
    brier_a = result_a.get("brier") or float("inf")
    brier_b = result_b.get("brier") or float("inf")
    if abs(brier_a - brier_b) < 0.001:
        winner = "tie"
    elif brier_a < brier_b:
        winner = "a"
    else:
        winner = "b"

    output = {
        "a": result_a,
        "b": result_b,
        "winner": winner,
        "winner_metric": "brier",
    }

    if output_path:
        _Path(output_path).parent.mkdir(exist_ok=True)
        _Path(output_path).write_text(_json.dumps(output, indent=2))

    return output
```

### 36.2 Write tests

- [ ] Create `tests/test_ab_testing.py`:

```python
"""Tests for P5.3: A/B testing system"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch


class TestRunABTest:
    def _fake_run_backtest(self, min_edge_override=None):
        """Returns different results depending on min_edge_override."""
        if min_edge_override and min_edge_override >= 0.10:
            return {"brier": 0.18, "win_rate": 0.60, "n_trades": 20, "roi": 0.12}
        return {"brier": 0.25, "win_rate": 0.50, "n_trades": 40, "roi": 0.05}

    def test_winner_is_lower_brier(self, monkeypatch):
        """Strategy with lower Brier score wins."""
        import backtest
        monkeypatch.setattr(backtest, "run_backtest", self._fake_run_backtest)

        result = backtest.run_ab_test(
            config_a={"strategy_name": "aggressive", "min_edge_override": 0.05},
            config_b={"strategy_name": "conservative", "min_edge_override": 0.10},
        )
        assert result["winner"] == "b", (
            "config_b (brier=0.18) should beat config_a (brier=0.25)"
        )
        assert result["winner_metric"] == "brier"

    def test_tie_when_brier_similar(self, monkeypatch):
        """Returns 'tie' when Brier scores differ by < 0.001."""
        import backtest

        def _same(_min_edge_override=None):
            return {"brier": 0.20, "win_rate": 0.55, "n_trades": 30, "roi": 0.08}

        monkeypatch.setattr(backtest, "run_backtest", _same)

        result = backtest.run_ab_test(
            config_a={"strategy_name": "A"}, config_b={"strategy_name": "B"}
        )
        assert result["winner"] == "tie"

    def test_output_written_to_file(self, tmp_path, monkeypatch):
        """Results are written to output_path when provided."""
        import backtest
        monkeypatch.setattr(backtest, "run_backtest", self._fake_run_backtest)

        out = tmp_path / "ab_result.json"
        backtest.run_ab_test(
            config_a={"min_edge_override": 0.05},
            config_b={"min_edge_override": 0.10},
            output_path=str(out),
        )
        assert out.exists()
        data = json.loads(out.read_text())
        assert "a" in data and "b" in data and "winner" in data

    def test_strategy_names_preserved(self, monkeypatch):
        """strategy_name from config appears in results."""
        import backtest
        monkeypatch.setattr(backtest, "run_backtest", self._fake_run_backtest)

        result = backtest.run_ab_test(
            config_a={"strategy_name": "alpha", "min_edge_override": 0.05},
            config_b={"strategy_name": "beta", "min_edge_override": 0.10},
        )
        assert result["a"]["strategy_name"] == "alpha"
        assert result["b"]["strategy_name"] == "beta"
```

### 36.3 Verify Task 36

- [ ] Run:
```
cd "C:\Users\thesa\claude kalshi" && python -m pytest tests/test_ab_testing.py -v
```
Expected: 4 passed.

### 36.4 Commit Task 36

```
git add backtest.py tests/test_ab_testing.py
git commit -m "feat(p5.3): add A/B testing system to backtest.py"
```

---

## Task 37 (P5.4) — Overfitting detection

### 37.1 Add `detect_overfitting` to `backtest.py`

- [ ] Add after `run_ab_test`:

```python
def detect_overfitting(
    n_periods: int = 3,
    min_trades_per_period: int = 10,
) -> dict:
    """
    Split historical data into `n_periods` equal time windows and run
    run_backtest on each. A strategy is flagged as potentially overfit if:
      - Brier score variance across periods is high (std > 0.05), OR
      - Any single period has win_rate < 0.40 with >= min_trades_per_period trades

    Returns:
        {
          "periods": list of per-period result dicts,
          "brier_std": float,
          "overfit_detected": bool,
          "reason": str | None,
        }
    """
    # Run walk-forward to get per-period metrics
    wf_result = run_walk_forward(n_splits=n_periods)
    periods = wf_result.get("windows", [])

    briers = [p.get("brier") for p in periods if p.get("brier") is not None]
    brier_std = (
        (sum((b - sum(briers) / len(briers)) ** 2 for b in briers) / len(briers)) ** 0.5
        if len(briers) >= 2 else 0.0
    )

    overfit_detected = False
    reason = None

    if brier_std > 0.05:
        overfit_detected = True
        reason = f"High Brier variance across periods: std={brier_std:.4f} > 0.05"

    if not overfit_detected:
        for p in periods:
            if (
                p.get("n_trades", 0) >= min_trades_per_period
                and p.get("win_rate") is not None
                and p["win_rate"] < 0.40
            ):
                overfit_detected = True
                reason = (
                    f"Win rate {p['win_rate']:.2f} < 0.40 in period "
                    f"{p.get('period_label', '?')} ({p['n_trades']} trades)"
                )
                break

    return {
        "periods": periods,
        "brier_std": round(brier_std, 4),
        "overfit_detected": overfit_detected,
        "reason": reason,
    }
```

### 37.2 Write tests

- [ ] Create `tests/test_overfitting.py`:

```python
"""Tests for P5.4: Overfitting detection"""
from __future__ import annotations


class TestDetectOverfitting:
    def _fake_walk_forward_stable(self, n_splits=3):
        return {"windows": [
            {"brier": 0.20, "win_rate": 0.58, "n_trades": 15, "period_label": "P1"},
            {"brier": 0.21, "win_rate": 0.55, "n_trades": 18, "period_label": "P2"},
            {"brier": 0.19, "win_rate": 0.60, "n_trades": 14, "period_label": "P3"},
        ]}

    def _fake_walk_forward_volatile(self, n_splits=3):
        return {"windows": [
            {"brier": 0.10, "win_rate": 0.70, "n_trades": 20, "period_label": "P1"},
            {"brier": 0.30, "win_rate": 0.40, "n_trades": 20, "period_label": "P2"},
            {"brier": 0.40, "win_rate": 0.35, "n_trades": 20, "period_label": "P3"},
        ]}

    def test_stable_periods_no_overfit(self, monkeypatch):
        """Low Brier variance → no overfitting detected."""
        import backtest
        monkeypatch.setattr(backtest, "run_walk_forward", self._fake_walk_forward_stable)

        result = backtest.detect_overfitting()
        assert result["overfit_detected"] is False
        assert result["brier_std"] < 0.05

    def test_volatile_periods_overfit_detected(self, monkeypatch):
        """High Brier variance → overfitting detected."""
        import backtest
        monkeypatch.setattr(backtest, "run_walk_forward", self._fake_walk_forward_volatile)

        result = backtest.detect_overfitting(min_trades_per_period=10)
        assert result["overfit_detected"] is True
        assert result["reason"] is not None

    def test_poor_period_triggers_detection(self, monkeypatch):
        """Single period with win_rate < 0.40 triggers detection."""
        import backtest

        def _bad_period(n_splits=3):
            return {"windows": [
                {"brier": 0.20, "win_rate": 0.60, "n_trades": 15, "period_label": "P1"},
                {"brier": 0.20, "win_rate": 0.35, "n_trades": 15, "period_label": "P2"},
                {"brier": 0.21, "win_rate": 0.58, "n_trades": 15, "period_label": "P3"},
            ]}

        monkeypatch.setattr(backtest, "run_walk_forward", _bad_period)
        result = backtest.detect_overfitting(min_trades_per_period=10)
        assert result["overfit_detected"] is True

    def test_returns_expected_keys(self, monkeypatch):
        """Return dict always has required keys."""
        import backtest
        monkeypatch.setattr(backtest, "run_walk_forward", self._fake_walk_forward_stable)

        result = backtest.detect_overfitting()
        assert all(k in result for k in ("periods", "brier_std", "overfit_detected", "reason"))
```

### 37.3 Verify Task 37

- [ ] Run:
```
cd "C:\Users\thesa\claude kalshi" && python -m pytest tests/test_overfitting.py -v
```
Expected: 4 passed.

### 37.4 Full regression check

- [ ] Run:
```
cd "C:\Users\thesa\claude kalshi" && python -m pytest --tb=short -q
```

### 37.5 Commit Task 37

```
git add backtest.py tests/test_overfitting.py
git commit -m "feat(p5.4): add overfitting detection via cross-period Brier variance"
```

---

## Summary of changes

| File | What changes |
|------|-------------|
| `main.py` | +`SHADOW_LOG_PATH` constant; +`_log_shadow_trade` helper; `shadow: bool` param on `_auto_place_trades`; +`cmd_shadow` command |
| `backtest.py` | +`sweep_edge_thresholds`; `min_edge_override` on `run_backtest`; +`run_ab_test`; +`detect_overfitting` |
| `tests/test_shadow_mode.py` | New — 3 tests |
| `tests/test_parameter_sweep.py` | New — 4 tests |
| `tests/test_ab_testing.py` | New — 4 tests |
| `tests/test_overfitting.py` | New — 4 tests |
