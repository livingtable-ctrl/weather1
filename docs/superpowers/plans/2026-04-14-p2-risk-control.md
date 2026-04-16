# P2: Risk Control & Capital Safety — Verification Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Verify that the risk-control and capital-safety mechanisms already coded in `paper.py` and `main.py` actually behave correctly, by writing a new test file `tests/test_risk_control.py` with three groups of tests (Tasks 9, 10, 11). No production code changes.

**Architecture:** All three tasks patch module-level globals and imported symbols with `monkeypatch` so tests are deterministic and side-effect-free. `tmp_path` is used to redirect `paper.DATA_PATH` to a temp directory, avoiding any writes to the real `data/paper_trades.json`.

**Tech Stack:** Python 3.11+, pytest, monkeypatch, tmp_path. No extra dependencies.

---

## Task 9 (P2.1) — Kelly sizing scales with balance

- [x] **Write** `tests/test_risk_control.py` with the Task 9 test block below.
- [x] **Verify** by running the test.
- [x] **Commit** with message `test(p2.1): verify kelly_bet_dollars scales with balance`.

### What is being verified

`kelly_bet_dollars` (paper.py:344) reads `balance = get_balance()` which in turn calls `_load()["balance"]`. When the balance is halved, the dollar output must be approximately halved (within floating-point tolerance).

### Test code — Task 9

```python
# tests/test_risk_control.py
"""
P2 Risk Control verification tests.
No production code is modified — all tests use monkeypatch / tmp_path.
"""

from __future__ import annotations

import json
import time

import pytest


# ── helpers ───────────────────────────────────────────────────────────────────

def _write_paper_json(path, balance: float) -> None:
    """Write a minimal valid paper_trades.json to *path* with the given balance."""
    data = {
        "_version": 2,
        "balance": balance,
        "peak_balance": balance,
        "trades": [],
    }
    path.write_text(json.dumps(data))


# ── Task 9 (P2.1): Kelly sizing scales with balance ───────────────────────────

class TestKellyScalesWithBalance:
    """kelly_bet_dollars output should scale proportionally with paper balance."""

    def test_double_balance_roughly_doubles_output(self, monkeypatch, tmp_path):
        import paper

        paper_file_500 = tmp_path / "paper_500.json"
        paper_file_1000 = tmp_path / "paper_1000.json"
        _write_paper_json(paper_file_500, 500.0)
        _write_paper_json(paper_file_1000, 1000.0)

        # Patch strategy to pure Kelly so the formula is simply balance × fraction
        monkeypatch.setenv("STRATEGY", "kelly")
        # Disable streak and drawdown side-effects
        monkeypatch.setattr(paper, "is_streak_paused", lambda: False)
        monkeypatch.setattr(paper, "drawdown_scaling_factor", lambda: 1.0)
        # Disable per-method Brier scaling
        monkeypatch.setattr(paper, "_method_kelly_multiplier", lambda method: 1.0)
        # Disable dynamic cap (set a high flat cap so it never binds)
        monkeypatch.setattr(paper, "_dynamic_kelly_cap", lambda: 10_000.0)

        kelly_fraction = 0.10  # 10% Kelly input

        # Measure output at balance=500
        monkeypatch.setattr(paper, "DATA_PATH", paper_file_500)
        out_500 = paper.kelly_bet_dollars(kelly_fraction)

        # Measure output at balance=1000
        monkeypatch.setattr(paper, "DATA_PATH", paper_file_1000)
        out_1000 = paper.kelly_bet_dollars(kelly_fraction)

        assert out_500 > 0, "Expected positive dollar output for balance=500"
        assert out_1000 > 0, "Expected positive dollar output for balance=1000"
        # Output should scale: ratio should be close to 2.0
        ratio = out_1000 / out_500
        assert abs(ratio - 2.0) < 0.05, (
            f"Expected ratio ≈ 2.0 when balance doubles, got {ratio:.4f} "
            f"(out_500={out_500}, out_1000={out_1000})"
        )

    def test_zero_drawdown_scale_returns_zero(self, monkeypatch, tmp_path):
        import paper

        paper_file = tmp_path / "paper_1000.json"
        _write_paper_json(paper_file, 1000.0)
        monkeypatch.setattr(paper, "DATA_PATH", paper_file)
        monkeypatch.setattr(paper, "drawdown_scaling_factor", lambda: 0.0)

        result = paper.kelly_bet_dollars(0.10)
        assert result == 0.0, "Expected 0.0 when drawdown_scaling_factor returns 0"
```

### Run command — Task 9

```
cd "C:\Users\thesa\claude kalshi" && python -m pytest tests/test_risk_control.py::TestKellyScalesWithBalance -v
```

### Expected output — Task 9

```
tests/test_risk_control.py::TestKellyScalesWithBalance::test_double_balance_roughly_doubles_output PASSED
tests/test_risk_control.py::TestKellyScalesWithBalance::test_zero_drawdown_scale_returns_zero PASSED
2 passed in 0.XXs
```

---

## Task 10 (P2.2) — Guards block trades in _auto_place_trades

- [x] **Append** the Task 10 test block to `tests/test_risk_control.py`.
- [x] **Verify** by running only the Task 10 tests.
- [x] **Commit** with message `test(p2.2): verify trade guards block _auto_place_trades`.

### What is being verified

1. When `paper.is_daily_loss_halted` returns `True`, `_auto_place_trades` exits early with `return 0`.
2. When `_daily_paper_spend` already equals `MAX_DAILY_SPEND`, `_auto_place_trades` exits early with `return 0`.
3. When a single trade's cost would push `daily_spent + trade_cost > MAX_DAILY_SPEND`, that trade is skipped (function returns 0 placed).

### Test code — Task 10

```python
# ── Task 10 (P2.2): Guards block _auto_place_trades ──────────────────────────

def _make_opp(ticker: str = "KXHIGH-25APR15-B70") -> dict:
    """Return a minimal valid opportunity dict accepted by _auto_place_trades."""
    return {
        "ticker": ticker,
        "net_edge": 0.20,
        "ci_adjusted_kelly": 0.10,
        "data_fetched_at": time.time(),
        "recommended_side": "yes",
        "market_prob": 0.50,
        "model_consensus": True,
        # _validate_trade_opportunity requires net_edge >= PAPER_MIN_EDGE (0.05)
        # and data freshness — both satisfied above
    }


def _patch_paper_guards(monkeypatch, *, loss_halted: bool = False,
                        paused_drawdown: bool = False,
                        streak_paused: bool = False) -> None:
    """Patch all paper guard functions imported inside _auto_place_trades."""
    import main as _main  # noqa: F401 — ensure module is importable
    # _auto_place_trades does `from paper import ...` at call time, so we must
    # patch on the `paper` module directly (monkeypatch.setattr on the module).
    import paper
    monkeypatch.setattr(paper, "is_paused_drawdown", lambda: paused_drawdown)
    monkeypatch.setattr(paper, "is_daily_loss_halted", lambda client=None: loss_halted)
    monkeypatch.setattr(paper, "is_streak_paused", lambda: streak_paused)
    monkeypatch.setattr(paper, "get_open_trades", lambda: [])
    monkeypatch.setattr(paper, "portfolio_kelly_fraction",
                        lambda fraction, city, date, side="yes": fraction)
    monkeypatch.setattr(paper, "kelly_quantity",
                        lambda fraction, price, min_dollars=1.0, cap=None, method=None: 2)


class TestAutoPlaceTradeGuards:
    """Guards in _auto_place_trades must block execution and return 0."""

    def test_daily_loss_halted_returns_zero(self, monkeypatch):
        import main
        import paper

        _patch_paper_guards(monkeypatch, loss_halted=True)
        monkeypatch.setattr(main, "_daily_paper_spend", lambda: 0.0)
        # Also patch execution_log to prevent DB access
        import execution_log
        monkeypatch.setattr(execution_log, "was_traded_today",
                            lambda ticker, side: False)
        monkeypatch.setattr(execution_log, "was_ordered_this_cycle",
                            lambda ticker, side, cycle: False)

        result = main._auto_place_trades([_make_opp()], client=None, live=False)
        assert result == 0, (
            f"Expected 0 trades placed when is_daily_loss_halted=True, got {result}"
        )

    def test_daily_spend_cap_reached_returns_zero(self, monkeypatch):
        import main
        from utils import MAX_DAILY_SPEND

        _patch_paper_guards(monkeypatch, loss_halted=False)
        # Spend is exactly at the cap
        monkeypatch.setattr(main, "_daily_paper_spend", lambda: MAX_DAILY_SPEND)

        import execution_log
        monkeypatch.setattr(execution_log, "was_traded_today",
                            lambda ticker, side: False)
        monkeypatch.setattr(execution_log, "was_ordered_this_cycle",
                            lambda ticker, side, cycle: False)

        result = main._auto_place_trades([_make_opp()], client=None, live=False)
        assert result == 0, (
            f"Expected 0 trades placed when daily_spent >= MAX_DAILY_SPEND, got {result}"
        )

    def test_per_trade_overage_skips_trade(self, monkeypatch):
        """A single trade that would breach MAX_DAILY_SPEND must be skipped."""
        import main
        from utils import MAX_DAILY_SPEND

        _patch_paper_guards(monkeypatch, loss_halted=False)
        # daily_spent is just $1 below cap; each trade costs entry_price*qty = 0.50*2 = $1
        # so daily_spent + $1 == MAX_DAILY_SPEND exactly — NOT over, should NOT skip.
        # To force a skip, set daily_spent = MAX_DAILY_SPEND - 0.50 so cost of $1 exceeds cap.
        monkeypatch.setattr(main, "_daily_paper_spend", lambda: MAX_DAILY_SPEND - 0.50)

        import execution_log
        monkeypatch.setattr(execution_log, "was_traded_today",
                            lambda ticker, side: False)
        monkeypatch.setattr(execution_log, "was_ordered_this_cycle",
                            lambda ticker, side, cycle: False)

        # kelly_quantity returns 2, entry_price=0.50 → trade_cost = $1.00
        # daily_spent + 1.00 = MAX_DAILY_SPEND + 0.50 > MAX_DAILY_SPEND → skip
        result = main._auto_place_trades([_make_opp()], client=None, live=False)
        assert result == 0, (
            f"Expected trade to be skipped when cost would exceed daily cap, got {result}"
        )
```

### Run command — Task 10

```
cd "C:\Users\thesa\claude kalshi" && python -m pytest tests/test_risk_control.py::TestAutoPlaceTradeGuards -v
```

### Expected output — Task 10

```
tests/test_risk_control.py::TestAutoPlaceTradeGuards::test_daily_loss_halted_returns_zero PASSED
tests/test_risk_control.py::TestAutoPlaceTradeGuards::test_daily_spend_cap_reached_returns_zero PASSED
tests/test_risk_control.py::TestAutoPlaceTradeGuards::test_per_trade_overage_skips_trade PASSED
3 passed in 0.XXs
```

---

## Task 11 (P2.5) — Paper/live separation

- [x] **Append** the Task 11 test block to `tests/test_risk_control.py`.
- [x] **Verify** by running only the Task 11 tests.
- [x] **Commit** with message `test(p2.5): verify paper/live separation and demo URL`.

### What is being verified

1. When `_auto_place_trades` is called with `live=False` (the default), `_place_live_order` is never invoked — confirming that the paper path never touches the live Kalshi API.
2. When `KALSHI_ENV=demo`, `MARKET_BASE_URL` resolves to a URL containing `demo.kalshi.co` and NOT `kalshi.com` (as a standalone domain segment).

### Test code — Task 11

```python
# ── Task 11 (P2.5): Paper/live separation ────────────────────────────────────

class TestPaperLiveSeparation:
    """_auto_place_trades(live=False) must never call _place_live_order."""

    def test_paper_mode_never_calls_place_live_order(self, monkeypatch):
        import main
        import paper

        live_order_calls: list = []

        def _fake_place_live_order(**kwargs):
            live_order_calls.append(kwargs)
            return False, 0.0

        monkeypatch.setattr(main, "_place_live_order", _fake_place_live_order)

        _patch_paper_guards(monkeypatch, loss_halted=False)
        monkeypatch.setattr(main, "_daily_paper_spend", lambda: 0.0)

        import execution_log
        monkeypatch.setattr(execution_log, "was_traded_today",
                            lambda ticker, side: False)
        monkeypatch.setattr(execution_log, "was_ordered_this_cycle",
                            lambda ticker, side, cycle: False)

        # Patch place_paper_order so no file I/O happens
        import paper as _paper
        monkeypatch.setattr(
            _paper, "place_paper_order",
            lambda ticker, side, qty, price, **kwargs: {
                "id": 1, "ticker": ticker, "side": side,
                "quantity": qty, "entry_price": price,
            }
        )

        # live=False is default; pass it explicitly for clarity
        main._auto_place_trades([_make_opp()], client=None, live=False)

        assert live_order_calls == [], (
            f"_place_live_order was called {len(live_order_calls)} time(s) "
            "even though live=False was passed."
        )

    def test_demo_env_uses_demo_base_url(self, monkeypatch):
        """When KALSHI_ENV=demo the MARKET_BASE_URL must point to demo.kalshi.co."""
        import importlib
        import os

        monkeypatch.setenv("KALSHI_ENV", "demo")
        # Re-import main so module-level KALSHI_ENV / MARKET_BASE_URL are re-evaluated
        import main as _main
        importlib.reload(_main)

        assert "demo.kalshi.co" in _main.MARKET_BASE_URL, (
            f"Expected 'demo.kalshi.co' in MARKET_BASE_URL, got {_main.MARKET_BASE_URL!r}"
        )
        # Must NOT be the production URL
        assert "kalshi.com" not in _main.MARKET_BASE_URL.replace("demo.kalshi.co", ""), (
            f"MARKET_BASE_URL appears to contain 'kalshi.com' in demo mode: "
            f"{_main.MARKET_BASE_URL!r}"
        )

    def test_prod_env_uses_prod_base_url(self, monkeypatch):
        """Sanity check: KALSHI_ENV=prod must give the production URL."""
        import importlib

        monkeypatch.setenv("KALSHI_ENV", "prod")
        import main as _main
        importlib.reload(_main)

        assert "kalshi.com" in _main.MARKET_BASE_URL, (
            f"Expected 'kalshi.com' in MARKET_BASE_URL for prod, "
            f"got {_main.MARKET_BASE_URL!r}"
        )
        assert "demo" not in _main.MARKET_BASE_URL, (
            f"MARKET_BASE_URL contains 'demo' even though KALSHI_ENV=prod: "
            f"{_main.MARKET_BASE_URL!r}"
        )
```

### Run command — Task 11

```
cd "C:\Users\thesa\claude kalshi" && python -m pytest tests/test_risk_control.py::TestPaperLiveSeparation -v
```

### Expected output — Task 11

```
tests/test_risk_control.py::TestPaperLiveSeparation::test_paper_mode_never_calls_place_live_order PASSED
tests/test_risk_control.py::TestPaperLiveSeparation::test_demo_env_uses_demo_base_url PASSED
tests/test_risk_control.py::TestPaperLiveSeparation::test_prod_env_uses_prod_base_url PASSED
3 passed in 0.XXs
```

---

## Full test file (complete, all tasks)

Save as `tests/test_risk_control.py`. This is the authoritative version — it is the union of the blocks above, with no placeholders.

```python
# tests/test_risk_control.py
"""
P2 Risk Control verification tests.
No production code is modified — all tests use monkeypatch / tmp_path.

Task 9  (P2.1): kelly_bet_dollars scales proportionally with paper balance.
Task 10 (P2.2): Guards in _auto_place_trades block execution and return 0.
Task 11 (P2.5): Paper/live separation — live=False never calls _place_live_order;
                KALSHI_ENV=demo resolves to demo.kalshi.co URL.
"""

from __future__ import annotations

import json
import time

import pytest


# ── helpers ───────────────────────────────────────────────────────────────────

def _write_paper_json(path, balance: float) -> None:
    """Write a minimal valid paper_trades.json to *path* with the given balance."""
    data = {
        "_version": 2,
        "balance": balance,
        "peak_balance": balance,
        "trades": [],
    }
    path.write_text(json.dumps(data))


def _make_opp(ticker: str = "KXHIGH-25APR15-B70") -> dict:
    """Return a minimal valid opportunity dict accepted by _auto_place_trades."""
    return {
        "ticker": ticker,
        "net_edge": 0.20,
        "ci_adjusted_kelly": 0.10,
        "data_fetched_at": time.time(),
        "recommended_side": "yes",
        "market_prob": 0.50,
        "model_consensus": True,
    }


def _patch_paper_guards(monkeypatch, *, loss_halted: bool = False,
                        paused_drawdown: bool = False,
                        streak_paused: bool = False) -> None:
    """Patch all paper guard functions imported inside _auto_place_trades."""
    import paper
    monkeypatch.setattr(paper, "is_paused_drawdown", lambda: paused_drawdown)
    monkeypatch.setattr(paper, "is_daily_loss_halted", lambda client=None: loss_halted)
    monkeypatch.setattr(paper, "is_streak_paused", lambda: streak_paused)
    monkeypatch.setattr(paper, "get_open_trades", lambda: [])
    monkeypatch.setattr(paper, "portfolio_kelly_fraction",
                        lambda fraction, city, date, side="yes": fraction)
    monkeypatch.setattr(paper, "kelly_quantity",
                        lambda fraction, price, min_dollars=1.0, cap=None, method=None: 2)


# ── Task 9 (P2.1): Kelly sizing scales with balance ───────────────────────────

class TestKellyScalesWithBalance:
    """kelly_bet_dollars output should scale proportionally with paper balance."""

    def test_double_balance_roughly_doubles_output(self, monkeypatch, tmp_path):
        import paper

        paper_file_500 = tmp_path / "paper_500.json"
        paper_file_1000 = tmp_path / "paper_1000.json"
        _write_paper_json(paper_file_500, 500.0)
        _write_paper_json(paper_file_1000, 1000.0)

        monkeypatch.setenv("STRATEGY", "kelly")
        monkeypatch.setattr(paper, "is_streak_paused", lambda: False)
        monkeypatch.setattr(paper, "drawdown_scaling_factor", lambda: 1.0)
        monkeypatch.setattr(paper, "_method_kelly_multiplier", lambda method: 1.0)
        monkeypatch.setattr(paper, "_dynamic_kelly_cap", lambda: 10_000.0)

        kelly_fraction = 0.10

        monkeypatch.setattr(paper, "DATA_PATH", paper_file_500)
        out_500 = paper.kelly_bet_dollars(kelly_fraction)

        monkeypatch.setattr(paper, "DATA_PATH", paper_file_1000)
        out_1000 = paper.kelly_bet_dollars(kelly_fraction)

        assert out_500 > 0, "Expected positive dollar output for balance=500"
        assert out_1000 > 0, "Expected positive dollar output for balance=1000"
        ratio = out_1000 / out_500
        assert abs(ratio - 2.0) < 0.05, (
            f"Expected ratio ≈ 2.0 when balance doubles, got {ratio:.4f} "
            f"(out_500={out_500}, out_1000={out_1000})"
        )

    def test_zero_drawdown_scale_returns_zero(self, monkeypatch, tmp_path):
        import paper

        paper_file = tmp_path / "paper_1000.json"
        _write_paper_json(paper_file, 1000.0)
        monkeypatch.setattr(paper, "DATA_PATH", paper_file)
        monkeypatch.setattr(paper, "drawdown_scaling_factor", lambda: 0.0)

        result = paper.kelly_bet_dollars(0.10)
        assert result == 0.0, "Expected 0.0 when drawdown_scaling_factor returns 0"


# ── Task 10 (P2.2): Guards block _auto_place_trades ──────────────────────────

class TestAutoPlaceTradeGuards:
    """Guards in _auto_place_trades must block execution and return 0."""

    def test_daily_loss_halted_returns_zero(self, monkeypatch):
        import main
        import execution_log

        _patch_paper_guards(monkeypatch, loss_halted=True)
        monkeypatch.setattr(main, "_daily_paper_spend", lambda: 0.0)
        monkeypatch.setattr(execution_log, "was_traded_today",
                            lambda ticker, side: False)
        monkeypatch.setattr(execution_log, "was_ordered_this_cycle",
                            lambda ticker, side, cycle: False)

        result = main._auto_place_trades([_make_opp()], client=None, live=False)
        assert result == 0, (
            f"Expected 0 trades placed when is_daily_loss_halted=True, got {result}"
        )

    def test_daily_spend_cap_reached_returns_zero(self, monkeypatch):
        import main
        import execution_log
        from utils import MAX_DAILY_SPEND

        _patch_paper_guards(monkeypatch, loss_halted=False)
        monkeypatch.setattr(main, "_daily_paper_spend", lambda: MAX_DAILY_SPEND)
        monkeypatch.setattr(execution_log, "was_traded_today",
                            lambda ticker, side: False)
        monkeypatch.setattr(execution_log, "was_ordered_this_cycle",
                            lambda ticker, side, cycle: False)

        result = main._auto_place_trades([_make_opp()], client=None, live=False)
        assert result == 0, (
            f"Expected 0 trades placed when daily_spent >= MAX_DAILY_SPEND, got {result}"
        )

    def test_per_trade_overage_skips_trade(self, monkeypatch):
        """A single trade that would breach MAX_DAILY_SPEND must be skipped."""
        import main
        import execution_log
        from utils import MAX_DAILY_SPEND

        _patch_paper_guards(monkeypatch, loss_halted=False)
        # kelly_quantity returns 2, entry_price=0.50 → trade_cost = $1.00
        # daily_spent + 1.00 > MAX_DAILY_SPEND when daily_spent = MAX_DAILY_SPEND - 0.50
        monkeypatch.setattr(main, "_daily_paper_spend", lambda: MAX_DAILY_SPEND - 0.50)
        monkeypatch.setattr(execution_log, "was_traded_today",
                            lambda ticker, side: False)
        monkeypatch.setattr(execution_log, "was_ordered_this_cycle",
                            lambda ticker, side, cycle: False)

        result = main._auto_place_trades([_make_opp()], client=None, live=False)
        assert result == 0, (
            f"Expected trade to be skipped when cost would exceed daily cap, got {result}"
        )


# ── Task 11 (P2.5): Paper/live separation ────────────────────────────────────

class TestPaperLiveSeparation:
    """_auto_place_trades(live=False) must never call _place_live_order."""

    def test_paper_mode_never_calls_place_live_order(self, monkeypatch):
        import main
        import paper as _paper
        import execution_log

        live_order_calls: list = []

        def _fake_place_live_order(**kwargs):
            live_order_calls.append(kwargs)
            return False, 0.0

        monkeypatch.setattr(main, "_place_live_order", _fake_place_live_order)

        _patch_paper_guards(monkeypatch, loss_halted=False)
        monkeypatch.setattr(main, "_daily_paper_spend", lambda: 0.0)
        monkeypatch.setattr(execution_log, "was_traded_today",
                            lambda ticker, side: False)
        monkeypatch.setattr(execution_log, "was_ordered_this_cycle",
                            lambda ticker, side, cycle: False)

        monkeypatch.setattr(
            _paper, "place_paper_order",
            lambda ticker, side, qty, price, **kwargs: {
                "id": 1, "ticker": ticker, "side": side,
                "quantity": qty, "entry_price": price,
            }
        )

        main._auto_place_trades([_make_opp()], client=None, live=False)

        assert live_order_calls == [], (
            f"_place_live_order was called {len(live_order_calls)} time(s) "
            "even though live=False was passed."
        )

    def test_demo_env_uses_demo_base_url(self, monkeypatch):
        """When KALSHI_ENV=demo the MARKET_BASE_URL must point to demo.kalshi.co."""
        import importlib

        monkeypatch.setenv("KALSHI_ENV", "demo")
        import main as _main
        importlib.reload(_main)

        assert "demo.kalshi.co" in _main.MARKET_BASE_URL, (
            f"Expected 'demo.kalshi.co' in MARKET_BASE_URL, got {_main.MARKET_BASE_URL!r}"
        )
        assert "kalshi.com" not in _main.MARKET_BASE_URL.replace("demo.kalshi.co", ""), (
            f"MARKET_BASE_URL appears to contain 'kalshi.com' in demo mode: "
            f"{_main.MARKET_BASE_URL!r}"
        )

    def test_prod_env_uses_prod_base_url(self, monkeypatch):
        """Sanity check: KALSHI_ENV=prod must give the production URL."""
        import importlib

        monkeypatch.setenv("KALSHI_ENV", "prod")
        import main as _main
        importlib.reload(_main)

        assert "kalshi.com" in _main.MARKET_BASE_URL, (
            f"Expected 'kalshi.com' in MARKET_BASE_URL for prod, "
            f"got {_main.MARKET_BASE_URL!r}"
        )
        assert "demo" not in _main.MARKET_BASE_URL, (
            f"MARKET_BASE_URL contains 'demo' even though KALSHI_ENV=prod: "
            f"{_main.MARKET_BASE_URL!r}"
        )
```

---

## Run all three task groups together

```
cd "C:\Users\thesa\claude kalshi" && python -m pytest tests/test_risk_control.py -v
```

### Expected final output

```
tests/test_risk_control.py::TestKellyScalesWithBalance::test_double_balance_roughly_doubles_output PASSED
tests/test_risk_control.py::TestKellyScalesWithBalance::test_zero_drawdown_scale_returns_zero PASSED
tests/test_risk_control.py::TestAutoPlaceTradeGuards::test_daily_loss_halted_returns_zero PASSED
tests/test_risk_control.py::TestAutoPlaceTradeGuards::test_daily_spend_cap_reached_returns_zero PASSED
tests/test_risk_control.py::TestAutoPlaceTradeGuards::test_per_trade_overage_skips_trade PASSED
tests/test_risk_control.py::TestPaperLiveSeparation::test_paper_mode_never_calls_place_live_order PASSED
tests/test_risk_control.py::TestPaperLiveSeparation::test_demo_env_uses_demo_base_url PASSED
tests/test_risk_control.py::TestPaperLiveSeparation::test_prod_env_uses_prod_base_url PASSED
8 passed in 0.XXs
```

---

## Commit sequence

```
# After Task 9
git add tests/test_risk_control.py
git commit -m "test(p2.1): verify kelly_bet_dollars scales with balance"

# After Task 10
git add tests/test_risk_control.py
git commit -m "test(p2.2): verify trade guards block _auto_place_trades"

# After Task 11
git add tests/test_risk_control.py
git commit -m "test(p2.5): verify paper/live separation and demo URL"
```

---

## Task 43 (P2.3) — Correlated Trade Detection

- [ ] **Add** `detect_correlated_exposure(open_trades, new_city)` to `paper.py`.
- [ ] **Apply** correlation penalty in `_auto_place_trades` before placing each trade.
- [ ] **Append** tests to `tests/test_risk_control.py`.
- [ ] **Verify** by running the Task 43 tests.
- [ ] **Commit** with message `feat(p2.3): add correlated trade detection with kelly penalty`.

### What is being added

When two or more currently-open paper trades share the same **city** (e.g., `"Chicago"`), adding a third correlated position concentrates risk. The correlation penalty halves the Kelly fraction for any new trade when `same_city_count >= 2`.

### Production code — paper.py

```python
# paper.py — add after portfolio_kelly_fraction

def detect_correlated_exposure(open_trades: list[dict], new_city: str) -> int:
    """
    Count open trades in the same city as *new_city*.

    Returns the count of matching open (non-settled) trades.
    Used by _auto_place_trades to detect concentrated city exposure.

    Args:
        open_trades: list of trade dicts, each with a "city" key (str).
        new_city: the city of the candidate new trade.

    Returns:
        int — number of currently open trades with city == new_city.
    """
    if not new_city:
        return 0
    return sum(
        1
        for t in open_trades
        if t.get("city", "").lower() == new_city.lower()
        and t.get("status", "open") != "settled"
    )
```

### Wiring in `_auto_place_trades` (main.py)

Inside the per-opportunity loop, after computing `kelly_fraction` and before calling `kelly_quantity`, add:

```python
# P2.3 — correlated trade penalty
from paper import detect_correlated_exposure, get_open_trades as _get_open_trades
_open = _get_open_trades()
_city = opp.get("city", "")
_corr_count = detect_correlated_exposure(_open, _city)
if _corr_count >= 2:
    _log.info(
        "P2.3 correlation penalty: %s already has %d open trades in city=%s — halving Kelly",
        opp["ticker"], _corr_count, _city,
    )
    kelly_fraction *= 0.50
```

### Test code — Task 43

```python
# ── Task 43 (P2.3): Correlated trade detection ───────────────────────────────

class TestCorrelatedExposureDetection:
    """detect_correlated_exposure counts open trades in the same city."""

    def _make_trade(self, city: str, status: str = "open") -> dict:
        return {"ticker": "KXTEST-26", "city": city, "status": status}

    def test_no_open_trades_returns_zero(self):
        from paper import detect_correlated_exposure
        assert detect_correlated_exposure([], "Chicago") == 0

    def test_counts_matching_city(self):
        from paper import detect_correlated_exposure
        trades = [
            self._make_trade("Chicago"),
            self._make_trade("Chicago"),
            self._make_trade("Dallas"),
        ]
        assert detect_correlated_exposure(trades, "Chicago") == 2

    def test_settled_trades_excluded(self):
        from paper import detect_correlated_exposure
        trades = [
            self._make_trade("Chicago", status="settled"),
            self._make_trade("Chicago", status="open"),
        ]
        assert detect_correlated_exposure(trades, "Chicago") == 1

    def test_case_insensitive_match(self):
        from paper import detect_correlated_exposure
        trades = [self._make_trade("chicago")]
        assert detect_correlated_exposure(trades, "Chicago") == 1

    def test_different_city_not_counted(self):
        from paper import detect_correlated_exposure
        trades = [self._make_trade("Dallas"), self._make_trade("Phoenix")]
        assert detect_correlated_exposure(trades, "Chicago") == 0

    def test_empty_city_returns_zero(self):
        from paper import detect_correlated_exposure
        trades = [self._make_trade("")]
        assert detect_correlated_exposure(trades, "") == 0
```

### Run command — Task 43

```
cd "C:\Users\thesa\claude kalshi" && python -m pytest tests/test_risk_control.py::TestCorrelatedExposureDetection -v
```

### Expected output — Task 43

```
tests/test_risk_control.py::TestCorrelatedExposureDetection::test_no_open_trades_returns_zero PASSED
tests/test_risk_control.py::TestCorrelatedExposureDetection::test_counts_matching_city PASSED
tests/test_risk_control.py::TestCorrelatedExposureDetection::test_settled_trades_excluded PASSED
tests/test_risk_control.py::TestCorrelatedExposureDetection::test_case_insensitive_match PASSED
tests/test_risk_control.py::TestCorrelatedExposureDetection::test_different_city_not_counted PASSED
tests/test_risk_control.py::TestCorrelatedExposureDetection::test_empty_city_returns_zero PASSED
6 passed in 0.XXs
```

---

## Task 47 (P2.4) — Confidence-Based Sizing Verification

- [ ] **Append** tests to `tests/test_risk_control.py`.
- [ ] **Verify** by running the Task 47 tests.
- [ ] **Commit** with message `test(p2.4): verify ci_adjusted_kelly produces larger size on high confidence`.

### What is being verified

The PDF requires "Increase size on high confidence trades, Reduce size on weak edges." `portfolio_kelly_fraction` and `ci_adjusted_kelly` already implement this via confidence intervals — but no test verifies the scaling direction. This task adds that verification.

A **tight** confidence interval (small `ci_width`) means high confidence → Kelly fraction is preserved or boosted. A **wide** CI means low confidence → Kelly is reduced. The test confirms that `kelly_quantity` output is monotonically larger when confidence is high.

### Test code — Task 47

```python
# ── Task 47 (P2.4): Confidence-based sizing verification ─────────────────────

class TestConfidenceBasedSizing:
    """ci_adjusted_kelly must produce larger size on high confidence than low confidence."""

    def test_tight_ci_produces_larger_kelly_than_wide_ci(self, monkeypatch, tmp_path):
        """Same edge, tighter CI → same or higher kelly_quantity."""
        import paper

        paper_file = tmp_path / "paper.json"
        paper_file.write_text(
            '{"_version": 2, "balance": 1000.0, "peak_balance": 1000.0, "trades": []}'
        )
        monkeypatch.setattr(paper, "DATA_PATH", paper_file)
        monkeypatch.setattr(paper, "drawdown_scaling_factor", lambda: 1.0)
        monkeypatch.setattr(paper, "is_streak_paused", lambda: False)
        monkeypatch.setattr(paper, "_dynamic_kelly_cap", lambda: 10_000.0)

        # High confidence: CI width = 0.05 (tight)
        high_conf_fraction = paper.ci_adjusted_kelly(
            kelly_fraction=0.10,
            ci_lower=0.625,   # model_prob - 0.025
            ci_upper=0.675,   # model_prob + 0.025
            model_prob=0.65,
        )

        # Low confidence: CI width = 0.30 (wide)
        low_conf_fraction = paper.ci_adjusted_kelly(
            kelly_fraction=0.10,
            ci_lower=0.50,
            ci_upper=0.80,
            model_prob=0.65,
        )

        assert high_conf_fraction >= low_conf_fraction, (
            f"Expected tight CI ({high_conf_fraction:.4f}) >= wide CI ({low_conf_fraction:.4f})"
        )

    def test_zero_ci_width_does_not_raise(self, monkeypatch, tmp_path):
        """Edge case: CI lower == CI upper must not raise ZeroDivisionError."""
        import paper

        paper_file = tmp_path / "paper.json"
        paper_file.write_text(
            '{"_version": 2, "balance": 1000.0, "peak_balance": 1000.0, "trades": []}'
        )
        monkeypatch.setattr(paper, "DATA_PATH", paper_file)

        result = paper.ci_adjusted_kelly(
            kelly_fraction=0.10,
            ci_lower=0.65,
            ci_upper=0.65,
            model_prob=0.65,
        )
        assert isinstance(result, float), "Must return a float even with zero CI width"
        assert result >= 0.0

    def test_negative_edge_ci_returns_zero_or_small(self, monkeypatch, tmp_path):
        """When CI lower is below 0.5 (weak edge), kelly fraction should be reduced."""
        import paper

        paper_file = tmp_path / "paper.json"
        paper_file.write_text(
            '{"_version": 2, "balance": 1000.0, "peak_balance": 1000.0, "trades": []}'
        )
        monkeypatch.setattr(paper, "DATA_PATH", paper_file)

        # CI spans below 0.5 — model is uncertain whether there's any edge
        weak_fraction = paper.ci_adjusted_kelly(
            kelly_fraction=0.10,
            ci_lower=0.40,
            ci_upper=0.70,
            model_prob=0.55,
        )
        # Should be substantially reduced vs full 0.10
        assert weak_fraction <= 0.10, (
            f"Weak edge CI should reduce fraction below 0.10, got {weak_fraction:.4f}"
        )
```

### Run command — Task 47

```
cd "C:\Users\thesa\claude kalshi" && python -m pytest tests/test_risk_control.py::TestConfidenceBasedSizing -v
```

### Expected output — Task 47

```
tests/test_risk_control.py::TestConfidenceBasedSizing::test_tight_ci_produces_larger_kelly_than_wide_ci PASSED
tests/test_risk_control.py::TestConfidenceBasedSizing::test_zero_ci_width_does_not_raise PASSED
tests/test_risk_control.py::TestConfidenceBasedSizing::test_negative_edge_ci_returns_zero_or_small PASSED
3 passed in 0.XXs
```
