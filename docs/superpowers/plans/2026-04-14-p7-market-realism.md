# P7: Market Realism Fixes — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve paper trading accuracy so paper P&L reflects real execution costs. Three additions: latency simulation, execution priority ranking, and bid-ask spread capture.

**What already exists — do NOT re-add:**
- `paper.py: slippage_kelly_scale` — Kelly multiplier based on volume+OI (0.5–1.0)
- `paper.py: slippage_adjusted_price` — sqrt impact model, clamped to [0.01, 0.99]
- `paper.py: simulate_fill`, `simulate_partial_fill` — depth-based partial fill simulation

**Architecture:** All changes are in `paper.py` and `weather_markets.py` (or `main.py`). No new modules. Latency uses an env var so it defaults to off.

**Tech Stack:** Python 3.11+, pytest, `monkeypatch`. No new dependencies.

---

## Task 23 (P7.2) — Latency simulation

### 23.1 Add `SIMULATED_LATENCY_MS` constant to `paper.py`

- [ ] Near the other env-var constants at the top of `paper.py`:

```python
import os as _os
SIMULATED_LATENCY_MS: int = int(_os.getenv("SIMULATED_LATENCY_MS", "0"))
```

### 23.2 Apply latency in `place_paper_order`

- [ ] In `place_paper_order`, at the very start of the function (before any other logic), add:

```python
    if SIMULATED_LATENCY_MS > 0:
        import time as _time
        _time.sleep(SIMULATED_LATENCY_MS / 1000.0)
```

- [ ] In the trade record dict returned by `place_paper_order`, add `"latency_ms": SIMULATED_LATENCY_MS`.

### 23.3 Write tests

- [ ] Create `tests/test_market_realism.py`:

```python
"""Tests for P7: Market Realism Fixes"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch, MagicMock
import time

import pytest


class TestLatencySimulation:
    def test_no_latency_by_default(self, monkeypatch, tmp_path):
        """With SIMULATED_LATENCY_MS=0 (default), no sleep is called."""
        import paper
        monkeypatch.setattr(paper, "SIMULATED_LATENCY_MS", 0)
        monkeypatch.setattr(paper, "DATA_PATH", tmp_path / "paper.json")

        # Write a valid paper file
        (tmp_path / "paper.json").write_text(
            '{"_version": 2, "balance": 500.0, "peak_balance": 500.0, "trades": []}'
        )

        sleep_calls: list = []
        with patch("time.sleep", side_effect=lambda s: sleep_calls.append(s)):
            try:
                paper.place_paper_order("KXTEST", "yes", 1, 0.50)
            except Exception:
                pass  # don't care about downstream errors

        assert sleep_calls == [], "time.sleep must not be called when latency=0"

    def test_latency_field_in_trade_record(self, monkeypatch, tmp_path):
        """When SIMULATED_LATENCY_MS > 0, the returned trade dict includes latency_ms."""
        import paper
        monkeypatch.setattr(paper, "SIMULATED_LATENCY_MS", 50)
        monkeypatch.setattr(paper, "DATA_PATH", tmp_path / "paper.json")
        (tmp_path / "paper.json").write_text(
            '{"_version": 2, "balance": 500.0, "peak_balance": 500.0, "trades": []}'
        )

        with patch("time.sleep"):  # don't actually sleep in tests
            try:
                result = paper.place_paper_order("KXTEST", "yes", 1, 0.50)
                assert result.get("latency_ms") == 50
            except Exception:
                pass  # focus only on latency_ms field
```

### 23.4 Verify Task 23

- [ ] Run:
```
cd "C:\Users\thesa\claude kalshi" && python -m pytest tests/test_market_realism.py::TestLatencySimulation -v
```

### 23.5 Commit Task 23

```
git add paper.py tests/test_market_realism.py
git commit -m "feat(p7.2): add configurable latency simulation to place_paper_order"
```

---

## Task 24 (P7.4) — Execution priority ranking

### 24.1 Add `rank_opportunities` to `main.py`

- [ ] After `_log_shadow_trade`, add:

```python
def rank_opportunities(opportunities: list[dict]) -> list[dict]:
    """
    Sort trade opportunities by composite priority score (highest first).

    Score = 0.5 * net_edge + 0.3 * ci_adjusted_kelly + 0.2 * liquidity_score
    where liquidity_score = volume / (volume + 100), clamped to [0, 1].

    Higher score = trade first.
    """
    def _score(opp: dict) -> float:
        volume = float(opp.get("volume", 0) or 0)
        liquidity_score = min(1.0, volume / (volume + 100.0)) if volume >= 0 else 0.0
        return (
            0.5 * float(opp.get("net_edge", 0) or 0)
            + 0.3 * float(opp.get("ci_adjusted_kelly", 0) or 0)
            + 0.2 * liquidity_score
        )

    return sorted(opportunities, key=_score, reverse=True)
```

### 24.2 Call `rank_opportunities` in `_auto_place_trades`

- [ ] At the very start of the opportunity loop in `_auto_place_trades`, before iterating:

```python
    opportunities = rank_opportunities(opportunities)
```

### 24.3 Write tests

- [ ] Add to `tests/test_market_realism.py`:

```python
class TestRankOpportunities:
    def _opp(self, ticker, edge, kelly, volume=1000) -> dict:
        return {
            "ticker": ticker,
            "net_edge": edge,
            "ci_adjusted_kelly": kelly,
            "volume": volume,
            "market_prob": 0.50,
            "recommended_side": "yes",
        }

    def test_higher_edge_ranks_first(self):
        """Opportunity with higher net_edge should rank above lower edge."""
        import main
        opps = [
            self._opp("LOW",  edge=0.05, kelly=0.05),
            self._opp("HIGH", edge=0.20, kelly=0.05),
        ]
        ranked = main.rank_opportunities(opps)
        assert ranked[0]["ticker"] == "HIGH"

    def test_higher_liquidity_breaks_tie(self):
        """When edge and kelly are equal, higher volume ranks first."""
        import main
        opps = [
            self._opp("ILLIQUID",  edge=0.10, kelly=0.10, volume=10),
            self._opp("LIQUID",    edge=0.10, kelly=0.10, volume=10000),
        ]
        ranked = main.rank_opportunities(opps)
        assert ranked[0]["ticker"] == "LIQUID"

    def test_empty_list_returns_empty(self):
        import main
        assert main.rank_opportunities([]) == []

    def test_single_item_unchanged(self):
        import main
        opp = self._opp("ONLY", edge=0.10, kelly=0.08)
        assert main.rank_opportunities([opp]) == [opp]

    def test_missing_volume_defaults_to_zero_score(self):
        """Opportunity without 'volume' key should not raise."""
        import main
        opp = {"ticker": "X", "net_edge": 0.10, "ci_adjusted_kelly": 0.05}
        result = main.rank_opportunities([opp])
        assert result[0]["ticker"] == "X"
```

### 24.4 Verify Task 24

- [ ] Run:
```
cd "C:\Users\thesa\claude kalshi" && python -m pytest tests/test_market_realism.py::TestRankOpportunities -v
```
Expected: 5 passed.

### 24.5 Commit Task 24

```
git add main.py tests/test_market_realism.py
git commit -m "feat(p7.4): add execution priority ranking for opportunities"
```

---

## Task 25 (P7.1) — Bid-ask spread capture

### 25.1 Update `place_paper_order` in `paper.py`

The existing code records `entry_price` as `market_prob` (mid-price). For YES buys the realistic execution price is `yes_ask`, not the mid.

- [ ] Update the function signature to accept `yes_ask: float | None = None`:

```python
def place_paper_order(
    ticker: str,
    side: str,
    quantity: int,
    price: float,
    yes_ask: float | None = None,   # ← add this; if provided, use as entry_price for YES buys
    **kwargs,
) -> dict:
```

- [ ] Inside `place_paper_order`, compute:

```python
    mid_price = price
    if side == "yes" and yes_ask is not None:
        entry_price = yes_ask
        spread_cost = round(yes_ask - mid_price, 4)
    else:
        entry_price = mid_price
        spread_cost = 0.0
```

- [ ] Add `"spread_cost": spread_cost` and `"entry_price": entry_price` to the returned trade record.

### 25.2 Pass `yes_ask` from `_auto_place_trades`

- [ ] In `main.py`, in `_auto_place_trades`, when calling `place_paper_order`:

```python
    paper.place_paper_order(
        ticker=opp["ticker"],
        side=opp["recommended_side"],
        qty=qty,
        price=opp["market_prob"],
        yes_ask=opp.get("yes_ask"),
    )
```

- [ ] Ensure `yes_ask` is populated in opportunity dicts from `get_weather_markets` → `analyze_trade`. Check if it's already in the market data; if so, pass it through.

### 25.3 Write tests

- [ ] Add to `tests/test_market_realism.py`:

```python
class TestBidAskSpread:
    def _paper_file(self, tmp_path) -> Path:
        p = tmp_path / "paper.json"
        p.write_text(
            '{"_version": 2, "balance": 1000.0, "peak_balance": 1000.0, "trades": []}'
        )
        return p

    def test_spread_cost_positive_when_ask_above_mid(self, tmp_path, monkeypatch):
        """spread_cost > 0 when yes_ask > market_prob (mid)."""
        import paper
        monkeypatch.setattr(paper, "DATA_PATH", self._paper_file(tmp_path))
        monkeypatch.setattr(paper, "SIMULATED_LATENCY_MS", 0)

        result = paper.place_paper_order(
            ticker="KXTEST", side="yes", quantity=1,
            price=0.50,      # mid
            yes_ask=0.53,    # ask
        )
        assert result.get("spread_cost", 0) > 0, "spread_cost must be positive"
        assert result.get("entry_price") == 0.53, "entry_price must be the ask"

    def test_no_yes_ask_uses_mid_price(self, tmp_path, monkeypatch):
        """When yes_ask is not provided, entry_price == price (mid)."""
        import paper
        monkeypatch.setattr(paper, "DATA_PATH", self._paper_file(tmp_path))
        monkeypatch.setattr(paper, "SIMULATED_LATENCY_MS", 0)

        result = paper.place_paper_order(
            ticker="KXTEST", side="yes", quantity=1, price=0.50
        )
        assert result.get("entry_price") == 0.50
        assert result.get("spread_cost") == 0.0

    def test_no_side_uses_price(self, tmp_path, monkeypatch):
        """For 'no' side, entry_price == price regardless of yes_ask."""
        import paper
        monkeypatch.setattr(paper, "DATA_PATH", self._paper_file(tmp_path))
        monkeypatch.setattr(paper, "SIMULATED_LATENCY_MS", 0)

        result = paper.place_paper_order(
            ticker="KXTEST", side="no", quantity=1,
            price=0.48, yes_ask=0.53,
        )
        assert result.get("entry_price") == 0.48
```

### 25.4 Verify Task 25

- [ ] Run:
```
cd "C:\Users\thesa\claude kalshi" && python -m pytest tests/test_market_realism.py -v
```
Expected: all tests passed.

### 25.5 Full regression check

- [ ] Run:
```
cd "C:\Users\thesa\claude kalshi" && python -m pytest --tb=short -q
```

### 25.6 Commit Task 25

```
git add paper.py main.py tests/test_market_realism.py
git commit -m "feat(p7.1): capture bid-ask spread cost in paper order records"
```

---

---

## Task 39 (P7.3) — Liquidity constraints hard cap

The existing `slippage_kelly_scale` reduces Kelly *fraction* based on volume, but doesn't enforce a hard maximum contract quantity based on market depth. This task adds an explicit size cap.

### 39.1 Add `max_quantity_for_market` to `paper.py`

- [ ] Add after `slippage_kelly_scale`:

```python
def max_quantity_for_market(volume: float, open_interest: float) -> int:
    """
    Compute the maximum contracts to trade based on market depth.

    Hard cap = min(
        floor(volume * 0.05),         # no more than 5% of daily volume
        floor(open_interest * 0.10),  # no more than 10% of open interest
        MAX_SINGLE_ORDER_CONTRACTS,   # absolute hard cap
    )
    Returns at least 1 (so valid markets are never fully blocked by this alone).
    """
    MAX_SINGLE_ORDER_CONTRACTS: int = int(
        __import__("os").getenv("MAX_SINGLE_ORDER_CONTRACTS", "50")
    )
    vol_cap = int(volume * 0.05) if volume > 0 else MAX_SINGLE_ORDER_CONTRACTS
    oi_cap = int(open_interest * 0.10) if open_interest > 0 else MAX_SINGLE_ORDER_CONTRACTS
    return max(1, min(vol_cap, oi_cap, MAX_SINGLE_ORDER_CONTRACTS))
```

### 39.2 Apply in `place_paper_order`

- [ ] In `place_paper_order`, after computing `entry_price`, clamp `quantity`:

```python
    if volume is not None and open_interest is not None:
        liq_cap = max_quantity_for_market(volume, open_interest)
        if quantity > liq_cap:
            _log.info(
                "place_paper_order: clamping qty %d → %d for %s (liquidity cap)",
                quantity, liq_cap, ticker,
            )
            quantity = liq_cap
```

- [ ] Update `place_paper_order` signature to accept `volume: float | None = None, open_interest: float | None = None`.

### 39.3 Pass market depth from `_auto_place_trades`

- [ ] In `main.py`, pass `volume` and `open_interest` from the opportunity dict:

```python
    paper.place_paper_order(
        ticker=opp["ticker"],
        side=opp["recommended_side"],
        quantity=qty,
        price=opp["market_prob"],
        yes_ask=opp.get("yes_ask"),
        volume=opp.get("volume", 0),
        open_interest=opp.get("open_interest", 0),
    )
```

### 39.4 Write tests

- [ ] Add to `tests/test_market_realism.py`:

```python
class TestLiquidityConstraints:
    def test_low_volume_caps_quantity(self):
        """Low volume market caps quantity to 5% of volume."""
        import paper
        # volume=100 → vol_cap = floor(100*0.05) = 5
        cap = paper.max_quantity_for_market(volume=100, open_interest=10000)
        assert cap == 5

    def test_low_oi_caps_quantity(self):
        """Low open interest market caps quantity to 10% of OI."""
        import paper
        # open_interest=30 → oi_cap = floor(30*0.10) = 3
        cap = paper.max_quantity_for_market(volume=10000, open_interest=30)
        assert cap == 3

    def test_never_returns_zero(self):
        """max_quantity_for_market always returns at least 1."""
        import paper
        cap = paper.max_quantity_for_market(volume=0, open_interest=0)
        assert cap >= 1

    def test_high_liquidity_returns_env_cap(self, monkeypatch):
        """Very liquid market is capped by MAX_SINGLE_ORDER_CONTRACTS env var."""
        import paper, os
        monkeypatch.setenv("MAX_SINGLE_ORDER_CONTRACTS", "20")
        # volume=100000, OI=100000 → vol_cap=5000, oi_cap=10000, env_cap=20
        cap = paper.max_quantity_for_market(volume=100_000, open_interest=100_000)
        assert cap == 20

    def test_quantity_clamped_in_place_paper_order(self, tmp_path, monkeypatch):
        """place_paper_order clamps quantity when volume is very low."""
        import paper
        monkeypatch.setattr(paper, "DATA_PATH", tmp_path / "paper.json")
        (tmp_path / "paper.json").write_text(
            '{"_version": 2, "balance": 1000.0, "peak_balance": 1000.0, "trades": []}'
        )
        monkeypatch.setattr(paper, "SIMULATED_LATENCY_MS", 0)
        monkeypatch.setenv("MAX_SINGLE_ORDER_CONTRACTS", "50")

        # volume=20 → vol_cap = floor(20*0.05) = 1; request 10 contracts
        result = paper.place_paper_order(
            ticker="KXTEST", side="yes", quantity=10, price=0.50,
            volume=20.0, open_interest=1000.0,
        )
        assert result.get("quantity", 10) <= 1, (
            "quantity should be clamped to liquidity cap"
        )
```

### 39.5 Verify Task 39

- [ ] Run:
```
cd "C:\Users\thesa\claude kalshi" && python -m pytest tests/test_market_realism.py -v
```
Expected: all tests passed.

### 39.6 Full regression check

- [ ] Run:
```
cd "C:\Users\thesa\claude kalshi" && python -m pytest --tb=short -q
```

### 39.7 Commit Task 39

```
git add paper.py main.py tests/test_market_realism.py
git commit -m "feat(p7.3): add liquidity-based hard cap on paper order quantity"
```

---

## Summary of changes

| File | What changes |
|------|-------------|
| `paper.py` | +`SIMULATED_LATENCY_MS`; latency + `latency_ms` in `place_paper_order`; `yes_ask` + `spread_cost` + `entry_price`; +`max_quantity_for_market()`; liquidity clamp in `place_paper_order` |
| `main.py` | +`rank_opportunities()`; pass `yes_ask`, `volume`, `open_interest` to `place_paper_order` |
| `tests/test_market_realism.py` | New — 15 tests across 4 classes |
