# Live Order Lifecycle Design

**Date:** 2026-04-10
**Goal:** Close five gaps in the live order lifecycle — daily loss persistence, settlement tracking, automated GTC cancellation, live tax export, and live P&L in the dashboard.

---

## Problem

Five gaps exist after Group 1 (execution pipeline). Live orders are placed but have no lifecycle after placement:

1. **`_SESSION_LOSS` resets on restart (#A).** The daily $200 loss limit is tracked in a module-level float. Restarting `main.py` mid-day resets it to $0, allowing a second $200 loss.

2. **Filled orders never settle (#B).** When a market resolves, nothing checks whether filled live orders won or lost. Live P&L is permanently $0.

3. **GTC orders never auto-cancel (#C).** Stale GTC orders accumulate on Kalshi's book indefinitely. No automated cleanup exists.

4. **Tax export covers paper only (#D).** `export_tax_csv()` in `paper.py` reads `paper_trades.json`. Live orders in `execution_log.db` have no export path.

5. **Dashboard shows paper P&L only (#E).** The web dashboard has no live P&L card because settlement is never tracked.

---

## Architecture

Two files modified, one new endpoint, one JS update, no new top-level files.

| Feature | File | Change |
|---------|------|--------|
| #A Daily loss persistence | `execution_log.py` + `main.py` | `daily_live_loss` table; replace `_SESSION_LOSS` |
| #B Settlement tracking | `execution_log.py` + `main.py` | 3 new columns; extend `_poll_pending_orders()` |
| #C GTC auto-cancel | `main.py` + `live_config.json` | Age check in poll loop; `gtc_cancel_hours` config |
| #D Live tax export | `execution_log.py` + `main.py` | `export_live_tax_csv()`; wire into `cmd_export()` |
| #E Live P&L dashboard | `web_app.py` + `static/dashboard.js` | `/api/live-pnl` endpoint; new dashboard card |
| Tests | `tests/test_execution_log.py` + `tests/test_live_execution.py` | 8 new tests |

---

## Design

### 1. #A — Persistent daily loss counter

**New table in `execution_log.db`** (added via existing migration pattern):

```sql
CREATE TABLE IF NOT EXISTS daily_live_loss (
    date       TEXT PRIMARY KEY,  -- YYYY-MM-DD UTC
    total      REAL NOT NULL DEFAULT 0.0,
    updated_at TEXT NOT NULL
);
```

**New functions in `execution_log.py`:**

```python
def get_today_live_loss() -> float:
    """Return today's accumulated live loss (UTC). Returns 0.0 if no row."""

def add_live_loss(amount: float) -> float:
    """Upsert today's row, adding amount to total. Returns new total.
    amount > 0 means a loss (e.g., cost of failed trade or settled loss).
    amount < 0 means a gain (called from settlement with -pnl for winners).
    """
```

**`main.py` changes:**
- Remove `_SESSION_LOSS: float = 0.0` module-level variable
- `_place_live_order()`: replace `_SESSION_LOSS >= config["daily_loss_limit"]` with `get_today_live_loss() >= config["daily_loss_limit"]`
- `_place_live_order()`: replace `_SESSION_LOSS += cost` (in caller `_auto_place_trades`) with `add_live_loss(cost)`
- `_auto_place_trades()`: remove `global _SESSION_LOSS` declaration

**Fallback:** If the DB write fails (disk full, etc.), `add_live_loss()` logs a warning and returns the last known value — the order is not blocked by a DB write failure.

---

### 2. #B — Live order settlement tracking

**Schema migrations** (via existing try/except pattern in `execution_log.py`):

```sql
ALTER TABLE orders ADD COLUMN settled_at TEXT;
ALTER TABLE orders ADD COLUMN outcome_yes INTEGER;  -- 1=YES won, 0=NO won, NULL=unsettled
ALTER TABLE orders ADD COLUMN pnl REAL;             -- net P&L after Kalshi fee
```

**New functions in `execution_log.py`:**

```python
def get_filled_unsettled_live_orders() -> list[dict]:
    """Return live=1, status='filled', settled_at IS NULL orders."""

def record_live_settlement(order_id: int, outcome_yes: bool, pnl: float) -> None:
    """Write settled_at=now, outcome_yes, pnl to the order row."""
```

**P&L formula** (uses `KALSHI_FEE_RATE` from `utils.py`):

```
YES bet wins:  pnl = quantity × (1 − price) × (1 − KALSHI_FEE_RATE)
YES bet loses: pnl = −quantity × price
NO bet wins:   pnl = quantity × price × (1 − KALSHI_FEE_RATE)
NO bet loses:  pnl = −quantity × (1 − price)
```

Where `price` is the YES-side decimal fill price stored in the order row (0.0–1.0). For NO bets, the order row still stores the YES price (as placed); the NO formulas account for this — a NO buyer paid `(1 − price)` per contract.

**`_poll_pending_orders(client)` extension in `main.py`:**

After processing pending orders, the function also iterates `get_filled_unsettled_live_orders()`. For each, it calls `client.get_market(ticker)`. If `market.get("status") == "finalized"` and `market.get("result")` is not None, it:
1. Determines `outcome_yes` from `market["result"]` (`"yes"` → True)
2. Computes `pnl` using the formula above
3. Calls `record_live_settlement(order_id, outcome_yes, pnl)`
4. Calls `add_live_loss(-pnl)` so losses subtract from the daily counter (positive loss = negative pnl)

**Fallback:** If `client.get_market()` raises, the order remains unsettled and is retried next poll cycle.

---

### 3. #C — Automated GTC cancellation

**`live_config.json` updated default:**

```json
{
  "max_trade_dollars": 50,
  "daily_loss_limit": 200,
  "max_open_positions": 10,
  "gtc_cancel_hours": 24
}
```

`_load_live_config()` default dict also gets `"gtc_cancel_hours": 24` so existing config files without the field still work.

**`_poll_pending_orders(client)` extension:**

For each pending live order, compute age: `now_utc - placed_at`. If age exceeds `config["gtc_cancel_hours"]` hours:
1. Call `client.cancel_order(order_id)` wrapped in try/except
2. On success: update `execution_log` status to `'cancelled'`
3. On failure: log warning, leave status as `'pending'` for next cycle

The cancel check runs before the fill-status check in the same loop iteration.

---

### 4. #D — Live tax/audit export

**New function in `execution_log.py`:**

```python
def export_live_tax_csv(path: str, tax_year: int | None = None) -> int:
    """Export settled live orders to CSV for tax reporting.

    Filters to live=1, settled_at IS NOT NULL, pnl IS NOT NULL.
    If tax_year is provided, filters to settled_at starting with that year.

    CSV columns: date, ticker, side, quantity, entry_price, outcome, pnl, settled_at
    Returns count of rows written.
    """
```

**`cmd_export()` in `main.py`** currently calls `paper.export_tax_csv()` and `paper.export_trades_csv()`. It gains a parallel call:

```python
from execution_log import export_live_tax_csv
live_count = export_live_tax_csv(live_path, tax_year=year)
print(f"  Live orders: {live_count} rows → {live_path}")
```

Output path: `data/live_tax_{year}.csv` (parallel to paper's `data/tax_{year}.csv`).

---

### 5. #E — Live P&L in dashboard

**New endpoint in `web_app.py`:**

```python
@app.route("/api/live-pnl")
def api_live_pnl():
    """Return live order P&L summary for dashboard card."""
    from execution_log import get_live_pnl_summary
    return jsonify(get_live_pnl_summary())
```

**New function in `execution_log.py`:**

```python
def get_live_pnl_summary() -> dict:
    """Return {"today_pnl": float, "total_pnl": float, "open_count": int, "settled_count": int}"""
```

- `today_pnl` — sum of `pnl` for live orders where `settled_at` starts with today's UTC date
- `total_pnl` — sum of all `pnl` for settled live orders
- `open_count` — count of live orders where `status='pending'`
- `settled_count` — count of live orders where `settled_at IS NOT NULL`

**`static/dashboard.js`** gains one fetch on page load:

```javascript
fetch('/api/live-pnl').then(r => r.json()).then(data => {
    // Render Live P&L card in dashboard grid
    // today_pnl: green if > 0, red if < 0, grey if settled_count == 0
    // total_pnl: same coloring
    // open_count: shown as "N open"
});
```

The card is rendered only when `settled_count > 0` or `open_count > 0` — if no live orders have ever been placed, the card is hidden.

---

## Fallback and Safety

- **#A**: DB write failure in `add_live_loss()` logs warning, does not block order placement. Conservative: next call to `get_today_live_loss()` will return last committed value.
- **#B**: `client.get_market()` failure leaves order unsettled, retried next poll. P&L formula uses stored fill price, not live quote — immune to price movement after fill.
- **#C**: Cancel failure logs warning, does not crash poll loop. Order remains pending and age-check fires again next cycle.
- **#D**: Empty export (no settled live orders) writes a header-only CSV and returns 0. Does not error.
- **#E**: `/api/live-pnl` returns `{"today_pnl": 0, "total_pnl": 0, "open_count": 0, "settled_count": 0}` if no live orders exist. Dashboard card stays hidden.

---

## Testing

**`tests/test_execution_log.py`** — 5 new tests:

1. `test_daily_live_loss_persists_across_calls` — `add_live_loss(10)`, then `add_live_loss(5)`, `get_today_live_loss()` returns 15
2. `test_daily_live_loss_resets_next_day` — seed a row for yesterday; `get_today_live_loss()` returns 0.0
3. `test_record_live_settlement_updates_row` — seed a filled live order; call `record_live_settlement()`; verify `settled_at`, `outcome_yes`, `pnl` written
4. `test_get_filled_unsettled_live_orders_excludes_settled` — seed one settled and one unsettled; only unsettled returned
5. `test_export_live_tax_csv_filters_by_year` — seed 2024 and 2025 orders; `export_live_tax_csv(path, tax_year=2025)` writes only 2025 rows

**`tests/test_live_execution.py`** — 3 new tests:

6. `test_gtc_cancel_fires_after_threshold` — pending order older than `gtc_cancel_hours`; `_poll_pending_orders()` calls `client.cancel_order()`
7. `test_gtc_cancel_skips_fresh_orders` — order placed 1 hour ago; `cancel_order` not called
8. `test_live_pnl_summary_correct` — seed 2 settled live orders with known pnl; `get_live_pnl_summary()` returns correct totals

---

## Out of Scope

- Real-time settlement webhooks (poll-based is sufficient for weather markets with daily settlement)
- Partial fill P&L tracking (all-or-nothing fill assumption from Group 1 unchanged)
- Live order amendment (Kalshi does not support order amendments, only cancel+replace)
- Backtesting, portfolio Kelly, model drift detection — all already implemented
