# Phase E: Walk-Forward Backtesting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a proper walk-forward backtesting engine to `backtest.py`. The existing `run_backtest()` does in-sample validation only — walk-forward trains on months 1-N, tests on month N+1, rolls forward, and repeats. This is the only statistically valid approach for non-stationary weather markets.

**Architecture:** Extend the existing `backtest.py` with a `walk_forward_backtest()` function. It splits historical predictions from the tracker DB into rolling train/test windows and reports out-of-sample Brier scores per fold. Results are saved to `data/walk_forward_results.json` and accessible via `py main.py walk-forward`.

**Tech Stack:** Python 3.12, existing `backtest.py`, `tracker.py` SQLite DB, pytest

---

## Task 1: Walk-Forward Backtesting Engine

**Files:**
- Modify: `backtest.py` (add `walk_forward_backtest()` and helpers)
- Modify: `main.py` (add `cmd_walk_forward` CLI command)
- Create: `tests/test_walk_forward.py`

The existing `backtest.py` has `run_backtest()`, `check_overfitting()`, and `stratified_train_test_split()`. Read it before adding the new function to avoid duplicating logic.

- [ ] **Step 1: Read existing `backtest.py`**

```
# Read backtest.py to understand existing structure before modifying
```

Open `backtest.py` and note:
- Where `TradeRecord` / sample dict structure is defined
- What `run_backtest()` returns
- Existing import pattern

- [ ] **Step 2: Write the failing tests**

Create `tests/test_walk_forward.py`:

```python
"""Tests for walk-forward backtesting engine."""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


def _make_trade(date_str: str, our_prob: float, settled_yes: bool) -> dict:
    """Make a minimal trade record for backtesting."""
    return {
        "market_date": date_str,
        "our_prob": our_prob,
        "settled_yes": settled_yes,
        "city": "NYC",
        "method": "ensemble",
        "edge": abs(our_prob - 0.5),
    }


class TestWalkForwardSplit:
    def test_creates_correct_number_of_folds(self):
        """With 12 months of data and window=6, test_size=1 → 6 folds."""
        from backtest import walk_forward_split

        # One trade per month for 12 months
        trades = []
        start = date(2025, 1, 1)
        for i in range(12):
            d = start + timedelta(days=30 * i)
            trades.append(_make_trade(d.isoformat(), 0.65, True))

        folds = walk_forward_split(trades, train_months=6, test_months=1)
        assert len(folds) == 6  # months 7-12 each tested once

    def test_no_data_leakage(self):
        """Test period never overlaps with train period in any fold."""
        from backtest import walk_forward_split

        trades = []
        start = date(2025, 1, 1)
        for i in range(12):
            d = start + timedelta(days=30 * i)
            trades.append(_make_trade(d.isoformat(), 0.65, True))

        folds = walk_forward_split(trades, train_months=6, test_months=1)
        for train, test in folds:
            train_dates = {t["market_date"] for t in train}
            test_dates = {t["market_date"] for t in test}
            assert not train_dates.intersection(test_dates), "Data leakage: train/test overlap"

    def test_test_period_advances_each_fold(self):
        """Each fold's test period is one month later than the previous."""
        from backtest import walk_forward_split

        trades = []
        start = date(2025, 1, 1)
        for i in range(12):
            d = start + timedelta(days=30 * i)
            trades.append(_make_trade(d.isoformat(), 0.65, True))

        folds = walk_forward_split(trades, train_months=6, test_months=1)
        prev_test_end = None
        for _, test in folds:
            test_months = sorted(set(t["market_date"][:7] for t in test))
            if prev_test_end is not None:
                assert test_months[0] > prev_test_end
            prev_test_end = test_months[-1]

    def test_insufficient_data_returns_empty(self):
        """Less than train_months + test_months of data → empty list."""
        from backtest import walk_forward_split

        trades = [_make_trade("2025-01-15", 0.65, True)]
        folds = walk_forward_split(trades, train_months=6, test_months=1)
        assert folds == []


class TestWalkForwardBacktest:
    def test_returns_results_dict(self):
        """walk_forward_backtest returns a dict with 'folds' list."""
        from backtest import walk_forward_backtest

        trades = []
        start = date(2025, 1, 1)
        for i in range(12):
            d = start + timedelta(days=30 * i)
            trades.append(_make_trade(d.isoformat(), 0.70, True))

        result = walk_forward_backtest(trades, train_months=6, test_months=1)
        assert "folds" in result
        assert isinstance(result["folds"], list)

    def test_each_fold_has_brier_score(self):
        """Each fold in results has 'brier', 'n_test', 'test_period' keys."""
        from backtest import walk_forward_backtest

        trades = []
        start = date(2025, 1, 1)
        for i in range(360):
            d = start + timedelta(days=i)
            trades.append(_make_trade(d.isoformat(), 0.65, i % 2 == 0))

        result = walk_forward_backtest(trades, train_months=6, test_months=1)
        for fold in result["folds"]:
            assert "brier" in fold
            assert "n_test" in fold
            assert "test_period" in fold

    def test_brier_scores_in_valid_range(self):
        """All fold Brier scores are between 0.0 and 1.0."""
        from backtest import walk_forward_backtest

        trades = []
        start = date(2025, 1, 1)
        for i in range(360):
            d = start + timedelta(days=i)
            trades.append(_make_trade(d.isoformat(), 0.65, i % 2 == 0))

        result = walk_forward_backtest(trades, train_months=6, test_months=1)
        for fold in result["folds"]:
            if fold.get("n_test", 0) > 0:
                assert 0.0 <= fold["brier"] <= 1.0

    def test_result_includes_summary(self):
        """Result includes overall mean_brier and std_brier across folds."""
        from backtest import walk_forward_backtest

        trades = []
        start = date(2025, 1, 1)
        for i in range(360):
            d = start + timedelta(days=i)
            trades.append(_make_trade(d.isoformat(), 0.65, True))

        result = walk_forward_backtest(trades, train_months=6, test_months=1)
        assert "mean_brier" in result
        assert "std_brier" in result
        assert "n_folds" in result
```

- [ ] **Step 3: Run tests to verify they fail**

```
cd "C:/Users/thesa/claude kalshi"
python -m pytest tests/test_walk_forward.py -v
```

Expected: `ImportError: cannot import name 'walk_forward_split'`

- [ ] **Step 4: Add walk-forward functions to `backtest.py`**

Read `backtest.py` first. Then add at the end:

```python
# ── Walk-Forward Backtesting ──────────────────────────────────────────────────


def walk_forward_split(
    trades: list[dict],
    train_months: int = 6,
    test_months: int = 1,
) -> list[tuple[list[dict], list[dict]]]:
    """
    Split trades into walk-forward train/test folds.

    Each fold trains on [start, train_end] and tests on [train_end+1, test_end].
    The window rolls forward by test_months each iteration.

    Args:
        trades: List of trade dicts with 'market_date' (ISO date string), 'our_prob',
                'settled_yes' keys
        train_months: Number of months in each training window
        test_months: Number of months in each test window

    Returns:
        List of (train_trades, test_trades) tuples. Empty if insufficient data.
    """
    from datetime import date as _date
    import calendar

    if not trades:
        return []

    # Sort by date
    sorted_trades = sorted(trades, key=lambda t: t["market_date"])

    # Parse all unique months in order
    months_seen = sorted(set(t["market_date"][:7] for t in sorted_trades))
    total_months = len(months_seen)

    min_months_needed = train_months + test_months
    if total_months < min_months_needed:
        return []

    folds = []
    # First test period starts at index train_months
    test_start_idx = train_months
    while test_start_idx + test_months <= total_months:
        train_months_set = set(months_seen[:test_start_idx])
        test_months_set = set(months_seen[test_start_idx:test_start_idx + test_months])

        train = [t for t in sorted_trades if t["market_date"][:7] in train_months_set]
        test = [t for t in sorted_trades if t["market_date"][:7] in test_months_set]

        if train and test:
            folds.append((train, test))

        test_start_idx += test_months

    return folds


def _brier_score_from_trades(trades: list[dict]) -> float | None:
    """Compute Brier score from a list of trade dicts."""
    valid = [t for t in trades if t.get("our_prob") is not None and t.get("settled_yes") is not None]
    if not valid:
        return None
    return sum((t["our_prob"] - (1 if t["settled_yes"] else 0)) ** 2 for t in valid) / len(valid)


def walk_forward_backtest(
    trades: list[dict],
    train_months: int = 6,
    test_months: int = 1,
) -> dict:
    """
    Run a walk-forward backtest on historical trade data.

    The only statistically valid backtesting approach for non-stationary
    weather markets — avoids look-ahead bias and data leakage.

    Args:
        trades: Historical trade records (must have market_date, our_prob, settled_yes)
        train_months: Training window size in months
        test_months: Test window size in months

    Returns:
        dict:
          - folds: list of fold results (test_period, n_test, brier, n_train)
          - mean_brier: float, mean out-of-sample Brier across folds
          - std_brier: float, std dev of fold Brier scores
          - n_folds: int
    """
    import statistics

    folds_data = walk_forward_split(trades, train_months, test_months)
    fold_results = []

    for train, test in folds_data:
        test_brier = _brier_score_from_trades(test)
        test_months_list = sorted(set(t["market_date"][:7] for t in test))
        fold_results.append({
            "test_period": f"{test_months_list[0]} — {test_months_list[-1]}",
            "n_train": len(train),
            "n_test": len(test),
            "brier": round(test_brier, 4) if test_brier is not None else None,
        })

    valid_scores = [f["brier"] for f in fold_results if f["brier"] is not None]
    mean_brier = round(statistics.mean(valid_scores), 4) if valid_scores else None
    std_brier = round(statistics.stdev(valid_scores), 4) if len(valid_scores) > 1 else 0.0

    return {
        "folds": fold_results,
        "mean_brier": mean_brier,
        "std_brier": std_brier,
        "n_folds": len(fold_results),
    }
```

- [ ] **Step 5: Run tests to verify they pass**

```
python -m pytest tests/test_walk_forward.py -v
```

Expected: 7 tests PASSED

- [ ] **Step 6: Add `cmd_walk_forward` to `main.py`**

```python
def cmd_walk_forward() -> None:
    """Run walk-forward backtest on historical paper trades."""
    import json
    from backtest import walk_forward_backtest
    from paper import load_paper_trades

    trades_raw = load_paper_trades()
    # Build backtest-compatible records
    trades = [
        {
            "market_date": t.get("date", t.get("placed_at", ""))[:10],
            "our_prob": t.get("our_prob", t.get("forecast_prob")),
            "settled_yes": t.get("outcome") == "yes",
            "city": t.get("city", ""),
            "method": t.get("method", ""),
            "edge": t.get("edge", 0),
        }
        for t in trades_raw
        if t.get("outcome") in ("yes", "no") and t.get("our_prob") or t.get("forecast_prob")
    ]

    if len(trades) < 50:
        print(f"Not enough settled trades for walk-forward (have {len(trades)}, need 50+).")
        return

    result = walk_forward_backtest(trades, train_months=3, test_months=1)

    print(f"\nWalk-Forward Backtest ({result['n_folds']} folds)")
    print(f"Mean out-of-sample Brier: {result['mean_brier']} ± {result['std_brier']}")
    print()
    print(f"{'Test Period':<25} {'N Train':>8} {'N Test':>8} {'Brier':>8}")
    print("-" * 55)
    for fold in result["folds"]:
        brier_str = f"{fold['brier']:.4f}" if fold["brier"] is not None else "—"
        print(f"{fold['test_period']:<25} {fold['n_train']:>8} {fold['n_test']:>8} {brier_str:>8}")

    # Save results
    import json
    from pathlib import Path
    out_path = Path(__file__).parent / "data" / "walk_forward_results.json"
    out_path.write_text(json.dumps(result, indent=2))
    print(f"\nSaved to {out_path}")
```

Wire into dispatch:
```python
"walk-forward": lambda _a: cmd_walk_forward(),
"walkforward": lambda _a: cmd_walk_forward(),
```

- [ ] **Step 7: Run full test suite**

```
python -m pytest -x -q
```

Expected: all pass

- [ ] **Step 8: Commit**

```bash
git add backtest.py tests/test_walk_forward.py main.py
git commit -m "feat(phase-e): add walk-forward backtesting engine; py main.py walk-forward"
```
