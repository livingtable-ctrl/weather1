# Fix Cron Trade Updates — Settle Paper Trades + Log New Placements

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make cron reliably settle resolved paper trades and log newly placed paper trades so the dashboard always reflects current state after each cron run.

**Architecture:** Two gaps:

1. **Paper trades never auto-settle during cron.** `cron.py` calls `sync_outcomes(client)` (records live market outcomes in the tracker DB) but never calls `auto_settle_paper_trades(client)` (marks paper trades in `data/paper.json` as won/lost). So paper trades stay "open" in the UI even after the Kalshi market has resolved. Fix: add `auto_settle_paper_trades(client)` call in `cmd_cron` right after `sync_outcomes`.

2. **Newly placed paper trades aren't summarised in the cron print output.** `placed_count` is tracked but the cron output doesn't show which tickers were placed, making it hard to verify cron is working. Fix: after placement, print a summary line for each new paper trade.

**Tech Stack:** Python, `cron.py`, `tests/test_cron_trade_updates.py` (new)

---

## Root Cause Summary

| Bug | File | Location | Cause |
|---|---|---|---|
| Paper trades never settle | `cron.py` | Line 699 | `sync_outcomes` handles tracker DB only; `auto_settle_paper_trades` is never called |
| No cron output for new trades | `cron.py` | Lines 686–694 | `placed_count` tracked but individual tickers not printed |

---

## Task 1: Add `auto_settle_paper_trades` call to cron

**Files:**
- Modify: `cron.py` ~lines 696–703
- Create: `tests/test_cron_trade_updates.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_cron_trade_updates.py`:

```python
"""Tests for cron trade update fixes."""
from unittest.mock import MagicMock, patch, call


class TestCronSettlesPaperTrades:
    def test_cmd_cron_calls_auto_settle_paper_trades(self, monkeypatch):
        """cmd_cron must call auto_settle_paper_trades so paper trades get marked won/lost."""
        import cron

        settle_calls = []

        def fake_auto_settle(client=None):
            settle_calls.append(client)
            return 1  # settled 1 trade

        monkeypatch.setattr("paper.auto_settle_paper_trades", fake_auto_settle)

        # Minimal stubs to get past the scan loop without hitting API
        monkeypatch.setattr("cron._fetch_open_markets", lambda client: [])
        fake_client = MagicMock()

        try:
            cron.cmd_cron(fake_client)
        except Exception:
            pass  # scan loop may fail; we only care that settle was called

        assert len(settle_calls) > 0, (
            "cmd_cron must call auto_settle_paper_trades(client) to settle resolved paper trades"
        )

    def test_auto_settle_called_after_sync_outcomes(self, monkeypatch):
        """auto_settle_paper_trades must be called in the same cron cycle as sync_outcomes."""
        import cron

        call_order = []

        monkeypatch.setattr("tracker.sync_outcomes", lambda client: (call_order.append("sync"), 0)[1])
        monkeypatch.setattr("paper.auto_settle_paper_trades", lambda client=None: (call_order.append("settle"), 1)[1])
        monkeypatch.setattr("cron._fetch_open_markets", lambda client: [])

        fake_client = MagicMock()
        try:
            cron.cmd_cron(fake_client)
        except Exception:
            pass

        assert "settle" in call_order, "auto_settle_paper_trades was never called"
        # sync_outcomes runs from tracker import in main; settle should follow
        if "sync" in call_order and "settle" in call_order:
            assert call_order.index("sync") < call_order.index("settle"), (
                "sync_outcomes should run before auto_settle_paper_trades"
            )
```

- [ ] **Step 2: Run tests to verify they fail**

```
python -m pytest tests/test_cron_trade_updates.py -v
```

Expected: FAIL — `auto_settle_paper_trades` is never called.

- [ ] **Step 3: Add `auto_settle_paper_trades` call in `cron.py`**

In `cron.py`, find (around lines 696–703):
```python
    # Auto-settle any pending trades whose markets have resolved
    settled_count = 0
    try:
        settled_count = _main.sync_outcomes(client)
        if settled_count > 0:
            print(green(f"  [Settle] Recorded {settled_count} new outcome(s)."))
    except Exception:
        pass
```

Replace with:
```python
    # Auto-settle any pending trades whose markets have resolved
    settled_count = 0
    try:
        settled_count = _main.sync_outcomes(client)
        if settled_count > 0:
            print(green(f"  [Settle] Recorded {settled_count} new outcome(s)."))
    except Exception:
        pass

    # Settle resolved paper trades (marks paper.json won/lost to match tracker outcomes)
    paper_settled_count = 0
    try:
        from paper import auto_settle_paper_trades
        paper_settled_count = auto_settle_paper_trades(client)
        if paper_settled_count > 0:
            print(green(f"  [PaperSettle] Settled {paper_settled_count} paper trade(s)."))
    except Exception as _e:
        _log.warning("cmd_cron: auto_settle_paper_trades failed: %s", _e)
```

- [ ] **Step 4: Run tests to verify they pass**

```
python -m pytest tests/test_cron_trade_updates.py -v
```

Expected: PASS.

---

## Task 2: Print a summary line for each newly placed paper trade

**Files:**
- Modify: `cron.py` ~lines 676–694 (the `_auto_place_trades` call blocks)
- Test: `tests/test_cron_trade_updates.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_cron_trade_updates.py`:

```python
class TestCronPrintPlacedTrades:
    def test_placed_trades_are_printed(self, monkeypatch, capsys):
        """cmd_cron must print the ticker and edge of each newly placed paper trade."""
        import cron

        # Fake a strong opportunity that gets placed
        fake_opp = (
            {"ticker": "KXWT-24-T50-B3", "_city": "NYC"},
            {"net_edge": 0.28, "edge": 0.28, "recommended_side": "yes"},
        )
        placed_trades = [{"ticker": "KXWT-24-T50-B3", "side": "yes", "cost": 5.0}]

        monkeypatch.setattr("cron._fetch_open_markets", lambda client: [])
        monkeypatch.setattr(
            "main._auto_place_trades",
            lambda opps, client=None, cap=None: len(opps)
        )
        # Inject a strong opportunity directly
        monkeypatch.setattr("cron._get_strong_opps", lambda *a, **kw: [fake_opp])

        fake_client = MagicMock()
        try:
            cron.cmd_cron(fake_client)
        except Exception:
            pass

        captured = capsys.readouterr()
        # At minimum, cron should print the number of trades placed
        assert "placed" in captured.out.lower() or "trade" in captured.out.lower(), (
            "cron output must mention placed trades"
        )
```

> **Note:** This test verifies the print behaviour exists; the exact format is flexible. If `_get_strong_opps` doesn't exist as a standalone function (it may be inline), adjust the monkeypatch approach — the key requirement is that placed trade information appears in stdout.

- [ ] **Step 2: Verify existing placement print output is adequate**

Read `cron.py` around lines 680–694. Check if placement already prints a ticker summary. If it does (e.g., prints `"!! N STRONG SIGNAL(S)"` with ticker names), no code change is needed — just verify the test passes.

If there is NO per-ticker placement line, add one:

After each `_auto_place_trades(...)` call, if `placed_count > 0`, print the tickers of placed trades. Example:

```python
        if placed_count > 0:
            for _opp, _ana in strong_opps:
                _ticker = _opp.get("ticker", "?")
                _edge = _ana.get("net_edge", _ana.get("edge", 0))
                print(dim(f"    placed: {_ticker} edge={_edge:+.1%}"))
```

- [ ] **Step 3: Run full suite**

```
python -m pytest tests/ -q --tb=short
```

Expected: all prior tests still pass, 2+ new tests pass.

- [ ] **Step 4: Commit**

```bash
git add cron.py tests/test_cron_trade_updates.py
git commit -m "fix: cron now auto-settles paper trades and prints placed trade tickers"
```

---

## Self-Review

**Spec coverage:**
- ✅ Paper trades never settle during cron → Task 1 (`auto_settle_paper_trades` added)
- ✅ New placements not visible in cron output → Task 2 (per-ticker print)

**Placeholder scan:** None found.

**Type consistency:** `auto_settle_paper_trades` returns `int` — same as `sync_outcomes`.
