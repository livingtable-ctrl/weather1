# Category C: Position Management — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add settlement countdown display (C5, quick win), auto-execute monotonicity violations (C6), partial exits (C1), take-profit ladders (C2), and re-entry logic (C3).

**Architecture:** C5 is pure frontend. C6 extends `consistency.py` with order placement. C1 and C2 modify `order_executor.py`'s early-exit logic. C3 is low priority post-graduation.

**Tech Stack:** Python 3.14, React/JSX (C5), SQLite, pytest.

**Implementation Order:** C5 → C6 → C1 → C2 → C3 → C4

---

## C5: Settlement Countdown on Positions Tab (Frontend)

**Problem:** The Positions tab shows open positions but not how much time remains until settlement. The `close_time` field is already stored in paper trades. Operators assessing time risk have to look up the market externally.

**Files:**
- Modify: `weather app site V_3 (3)/src/tabs/PositionsTab.jsx` — add countdown column

- [ ] **Step 1: Add `TimeToClose` component to `PositionsTab.jsx`**

Find the positions table in `PositionsTab.jsx`. Add this helper function above the component:

```jsx
function TimeToClose({ closeTime }) {
  if (!closeTime) return <span style={{ color: 'var(--text-dim)' }}>—</span>;

  const closeMs = new Date(closeTime).getTime();
  const nowMs = Date.now();
  const diffMs = closeMs - nowMs;

  if (diffMs <= 0) return <span style={{ color: 'var(--color-red)' }}>CLOSED</span>;

  const hours = Math.floor(diffMs / 3_600_000);
  const mins  = Math.floor((diffMs % 3_600_000) / 60_000);

  if (hours > 48) {
    const days = Math.floor(hours / 24);
    return <span style={{ color: 'var(--text-dim)' }}>{days}d</span>;
  }
  if (hours < 1) {
    return <span style={{ color: 'var(--color-red)', fontWeight: 600 }}>{mins}m</span>;
  }
  if (hours < 4) {
    return <span style={{ color: 'var(--color-yellow)' }}>{hours}h {mins}m</span>;
  }
  return <span>{hours}h {mins}m</span>;
}
```

- [ ] **Step 2: Add the column header to the table `<thead>`**

Find the `<thead>` row. After the existing column headers, add:

```jsx
<th style={{ textAlign: 'right', padding: '6px 8px' }}>Closes In</th>
```

- [ ] **Step 3: Add the column data to each `<tr>` in `<tbody>`**

For each position row, add after the last `<td>`:

```jsx
<td style={{ textAlign: 'right', padding: '6px 8px' }}>
  <TimeToClose closeTime={position.close_time} />
</td>
```

- [ ] **Step 4: Rebuild and verify**

```
cd "weather app site V_3 (3)"
npm run build
```

Open the dashboard at `http://localhost:5000` → Positions tab. Confirm the "Closes In" column appears with countdowns. Same-day positions should show red/yellow values; multi-day positions show days or hours.

- [ ] **Step 5: Commit**

```
git add "weather app site V_3 (3)/src/tabs/PositionsTab.jsx" static/dist/
git commit -m "feat(dashboard): add settlement countdown column to Positions tab"
```

---

## C6: Auto-Execute Monotonicity Violations

**Problem:** `consistency.py` detects cases where P(T>70) > P(T>65) — guaranteed profit after spread costs. These violations are surfaced in the dashboard but never auto-traded. The `find_violations()` function already computes `guaranteed_edge` using real bid/ask prices.

**Files:**
- Modify: `cron.py` — call `find_violations()` and auto-place when `guaranteed_edge > 0.03`
- Modify: `order_executor.py` — add `place_arbitrage_pair(violation, client)`
- Test: `tests/test_consistency.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_consistency.py — add
def test_arbitrage_placement_called_for_real_violations(monkeypatch):
    from consistency import Violation
    from order_executor import place_arbitrage_pair

    placed = []
    monkeypatch.setattr(
        "order_executor.place_paper_order",
        lambda ticker, side, qty, price, **kwargs: placed.append((ticker, side))
    )

    v = Violation(
        buy_ticker="KXHIGHNY-T65",
        sell_ticker="KXHIGHNY-T70",
        buy_prob=0.40,
        sell_prob=0.55,
        guaranteed_edge=0.08,
        description="P(>70)=55% > P(>65)=40% — impossible",
    )
    place_arbitrage_pair(v, client=None)
    # Should place: BUY lower-threshold (YES on T65) AND SELL higher-threshold (NO on T70)
    assert any(t == "KXHIGHNY-T65" and s == "yes" for t, s in placed)
    assert any(t == "KXHIGHNY-T70" and s == "no"  for t, s in placed)
```

- [ ] **Step 2: Run to confirm failure**

```
pytest tests/test_consistency.py::test_arbitrage_placement_called_for_real_violations -v
```
Expected: `ImportError: cannot import 'place_arbitrage_pair'`

- [ ] **Step 3: Add `place_arbitrage_pair()` to `order_executor.py`**

```python
_MIN_ARB_EDGE = float(os.getenv("MIN_ARB_EDGE", "0.03"))  # minimum real edge after spread


def place_arbitrage_pair(violation, client=None) -> tuple[dict | None, dict | None]:
    """Place the two legs of a monotonicity arbitrage.

    BUY the lower-threshold contract (YES on buy_ticker) and
    SELL the higher-threshold contract (NO on sell_ticker).
    Uses paper trading unless client is provided and KALSHI_ENV=prod.

    Returns (buy_result, sell_result); either may be None on failure.
    """
    if violation.guaranteed_edge < _MIN_ARB_EDGE:
        _log.debug(
            "arb skipped: edge=%.3f < MIN_ARB_EDGE=%.3f for %s/%s",
            violation.guaranteed_edge, _MIN_ARB_EDGE,
            violation.buy_ticker, violation.sell_ticker,
        )
        return None, None

    _log.info(
        "ARB opportunity: BUY %s (YES) + SELL %s (NO) — edge=%.3f",
        violation.buy_ticker, violation.sell_ticker, violation.guaranteed_edge,
    )

    buy_result = place_paper_order(
        violation.buy_ticker,
        "yes",
        qty=1,
        entry_price=violation.buy_prob,
        source="arb_consistency",
        net_edge=violation.guaranteed_edge,
    )
    sell_result = place_paper_order(
        violation.sell_ticker,
        "no",
        qty=1,
        entry_price=1.0 - violation.sell_prob,
        source="arb_consistency",
        net_edge=violation.guaranteed_edge,
    )
    return buy_result, sell_result
```

- [ ] **Step 4: Wire into `cron.py`**

After the main signal scan in `_cron_scan_inner`, add:

```python
# Arbitrage: check monotonicity violations and auto-place when edge > MIN_ARB_EDGE
try:
    from consistency import find_violations
    from order_executor import place_arbitrage_pair
    _markets = ctx.get_weather_markets()
    _violations = find_violations(_markets)
    for v in _violations:
        buy_r, sell_r = place_arbitrage_pair(v)
        if buy_r:
            _log.info("arb placed: %s/%s edge=%.3f", v.buy_ticker, v.sell_ticker, v.guaranteed_edge)
except Exception as _arb_exc:
    _log.warning("arb check failed: %s", _arb_exc)
```

- [ ] **Step 5: Run the test**

```
pytest tests/test_consistency.py -v
```
Expected: all PASS

- [ ] **Step 6: Commit**

```
git add order_executor.py cron.py tests/test_consistency.py
git commit -m "feat(trading): auto-execute monotonicity arbitrage pairs when guaranteed_edge > 3%"
```

---

## C1: Partial Exit (50% Close)

**Problem:** When the early-exit logic fires (model reverses), it closes 100% of the position. A partial close (50%) keeps upside if the reversal is noise.

**Files:**
- Modify: `order_executor.py` — add `partial_close_pct` parameter to `_check_early_exits()`
- Modify: `paper.py` — add `partial_close_position(ticker, close_pct)` function
- Test: `tests/test_early_exits.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_early_exits.py — add
def test_partial_close_reduces_qty_by_half(monkeypatch, tmp_path):
    import paper

    trades = [
        {
            "ticker": "KXHIGH-T70",
            "side": "yes",
            "entry_price": 0.55,
            "qty": 10,
            "settled": False,
            "won": None,
            "exit_target": 0.45,  # triggers early exit
        }
    ]
    saved = {}
    def mock_save(all_trades):
        saved["trades"] = all_trades
    monkeypatch.setattr(paper, "load_paper_trades", lambda: [t.copy() for t in trades])
    monkeypatch.setattr(paper, "save_paper_trades", mock_save)

    paper.partial_close_position("KXHIGH-T70", close_pct=0.50)

    remaining = [t for t in saved["trades"] if t["ticker"] == "KXHIGH-T70" and not t.get("closed")]
    closed    = [t for t in saved["trades"] if t["ticker"] == "KXHIGH-T70" and t.get("closed")]
    assert len(remaining) == 1
    assert remaining[0]["qty"] == 5   # half remaining
    assert len(closed) == 1
    assert closed[0]["qty"] == 5      # half closed
```

- [ ] **Step 2: Add `partial_close_position()` to `paper.py`**

```python
def partial_close_position(ticker: str, close_pct: float = 0.50) -> dict | None:
    """Close a fraction of an open position, leaving the rest open.

    close_pct: 0.0–1.0 fraction to close. Default 0.50 (half).
    Splits the trade record into (closed_portion) + (remaining_portion).
    The closed portion gets marked with closed=True and a realized_pnl field.
    Returns the closed portion dict or None if trade not found.
    """
    if not 0.0 < close_pct <= 1.0:
        raise ValueError(f"close_pct must be 0 < pct <= 1.0, got {close_pct}")

    with _DATA_LOCK:
        trades = load_paper_trades()
        target = next(
            (t for t in trades if t.get("ticker") == ticker
             and not t.get("settled") and not t.get("closed")),
            None,
        )
        if target is None:
            return None

        total_qty = int(target.get("qty", 1))
        close_qty = max(1, round(total_qty * close_pct))
        remain_qty = total_qty - close_qty

        import copy
        closed_portion = copy.deepcopy(target)
        closed_portion["qty"] = close_qty
        closed_portion["closed"] = True
        closed_portion["closed_at"] = datetime.now(UTC).isoformat(timespec="seconds")
        closed_portion["close_reason"] = "partial_exit"

        if remain_qty > 0:
            target["qty"] = remain_qty
        else:
            target["settled"] = True

        # Rebuild the trade list
        new_trades = []
        for t in trades:
            if t.get("ticker") == ticker and not t.get("settled") and not t.get("closed"):
                if remain_qty > 0:
                    t["qty"] = remain_qty
                new_trades.append(t)
            else:
                new_trades.append(t)
        new_trades.append(closed_portion)

        save_paper_trades(new_trades)
        _log.info("partial close: %s qty=%d/%d (%.0f%%)", ticker, close_qty, total_qty, close_pct * 100)
        return closed_portion
```

- [ ] **Step 3: Wire into early exit logic in `order_executor.py`**

In `check_early_exits()`, when an exit signal fires, replace:
```python
# old: close_paper_early(trade["ticker"])
```
with:
```python
# Close 50% now; leave 50% to run
from paper import partial_close_position
partial_close_position(trade["ticker"], close_pct=0.50)
_log.info("partial exit (50%%) triggered for %s", trade["ticker"])
```

Add env config: `PARTIAL_EXIT_PCT = float(os.getenv("PARTIAL_EXIT_PCT", "0.50"))` — set to 1.0 to restore full-close behavior.

- [ ] **Step 4: Run the test**

```
pytest tests/test_early_exits.py -v
```
Expected: all PASS

- [ ] **Step 5: Commit**

```
git add paper.py order_executor.py tests/test_early_exits.py
git commit -m "feat(trading): partial exit — close 50% of position on model reversal (configurable via PARTIAL_EXIT_PCT)"
```

---

## C2: Take-Profit Ladder

**Problem:** The current exit logic uses a single `exit_target` price. A ladder (close 33% at +25%, 33% at +45%, let the rest run) locks in gains progressively.

**Files:**
- Modify: `paper.py` — add `get_take_profit_targets(entry_price, side)` returning a list of (price, pct_to_close) pairs
- Modify: `order_executor.py` — check ladder levels in `check_early_exits()`
- Test: `tests/test_early_exits.py`

- [ ] **Step 1: Write failing test**

```python
def test_take_profit_targets_for_yes_bet():
    from paper import get_take_profit_targets

    # Entry at 0.50, YES bet
    targets = get_take_profit_targets(entry_price=0.50, side="yes")
    # Should have two ladder levels: +25% and +45%
    assert len(targets) == 2
    # First rung: close 33% at entry * 1.25 = 0.625
    assert abs(targets[0]["price"] - 0.625) < 0.001
    assert targets[0]["close_pct"] == pytest.approx(0.333, abs=0.01)
    # Second rung: close 33% at entry * 1.45 = 0.725
    assert abs(targets[1]["price"] - 0.725) < 0.001
    assert targets[1]["close_pct"] == pytest.approx(0.333, abs=0.01)
```

- [ ] **Step 2: Add `get_take_profit_targets()` to `paper.py`**

```python
_TP_RUNGS = [
    (float(os.getenv("TP_LEVEL_1_PCT", "0.25")), float(os.getenv("TP_LEVEL_1_CLOSE", "0.333"))),
    (float(os.getenv("TP_LEVEL_2_PCT", "0.45")), float(os.getenv("TP_LEVEL_2_CLOSE", "0.333"))),
]


def get_take_profit_targets(entry_price: float, side: str) -> list[dict]:
    """Return a list of take-profit targets for a position.

    Each target: {"price": float, "close_pct": float}
    Price is the YES price at which to take profit.
    For NO bets, price thresholds are converted to NO-equivalent prices.
    """
    targets = []
    for gain_pct, close_pct in _TP_RUNGS:
        if side == "yes":
            tp_price = min(0.95, entry_price * (1.0 + gain_pct))
        else:
            no_entry = 1.0 - entry_price
            no_tp = no_entry * (1.0 + gain_pct)
            tp_price = max(0.05, 1.0 - no_tp)
        targets.append({"price": round(tp_price, 3), "close_pct": close_pct})
    return targets
```

- [ ] **Step 3: Wire into early exit check**

In `check_early_exits()` in `order_executor.py`, before the normal early-exit logic:

```python
from paper import get_take_profit_targets, partial_close_position
tp_targets = get_take_profit_targets(
    float(trade.get("entry_price", 0.5)),
    trade.get("side", "yes"),
)
rung_hit = trade.get("tp_rung_index", 0)
for i, rung in enumerate(tp_targets[rung_hit:], start=rung_hit):
    should_close = (
        (trade.get("side") == "yes" and current_yes_price >= rung["price"])
        or (trade.get("side") == "no"  and current_yes_price <= rung["price"])
    )
    if should_close:
        partial_close_position(trade["ticker"], close_pct=rung["close_pct"])
        trade["tp_rung_index"] = i + 1
        _log.info("take-profit rung %d hit for %s at %.2f", i + 1, trade["ticker"], current_yes_price)
        break
```

- [ ] **Step 4: Run tests**

```
pytest tests/test_early_exits.py -v
```
Expected: all PASS

- [ ] **Step 5: Commit**

```
git add paper.py order_executor.py tests/test_early_exits.py
git commit -m "feat(trading): take-profit ladder — 33% at +25%, 33% at +45%, rest runs (configurable via TP_LEVEL_* env)"
```

---

## C3: Re-entry After Early Exit

*Lower priority — implement post-graduation when position management patterns are clearer.*

**Concept:** If the model remains bullish (edge still positive) after an early exit, re-enter the same market at the new price. Gate: only re-enter if (a) net_edge of new entry > PAPER_MIN_EDGE, (b) less than 2h remain until settlement, (c) no duplicate prevention flag on the ticker.

**When ready:** Add `re_entry_eligible(ticker, original_entry_at)` to `paper.py` and call from `_cron_scan_inner` after settlement check.

---

## C4: Position Building

*Post-graduation.* If a market moves in the model's favor after entry (e.g., model says 0.70 YES, we entered at 0.50, market now shows 0.55 YES with edge widening), consider adding to the position. Gate: total exposure per ticker can't exceed `MAX_CITY_DATE_EXPOSURE`. Implement as a separate signal type ("build" vs "open") in `order_executor.py`.
