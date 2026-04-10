# Execution Pipeline Design

**Date:** 2026-04-10
**Goal:** Move from paper-only trading to real money execution with three coordinated improvements — live order placement, limit order strategy, and cycle-aware deduplication.

---

## Problem

Three gaps prevent the bot from executing real orders profitably:

1. **No real money execution.** `kalshi_client.place_order()` exists but is never called. All trades are paper only. The bot generates good signals but never acts on them with real capital.

2. **Always pays the full spread.** Current price resolution uses `yes_ask` (for YES bets) — the worst available price. On a market with a 3-cent spread, the bot gives away 1.5 cents per contract it could capture with a midpoint limit order.

3. **Re-trades stale forecasts.** The cron fires every few minutes. Without a cycle check, the same signal on the same forecast data can trigger duplicate orders across multiple cron runs until the next model update.

---

## Architecture

Three targeted changes across two files plus one new config file:

- `execution_log.py` — schema migration adding `forecast_cycle` and `live` columns; new `was_ordered_this_cycle()` function; updated `log_order()` signature
- `main.py` — `--live` flag on `cmd_watch` and `cmd_analyze`; live config loader; daily loss tracking; limit order price resolution; cycle check wired into `_auto_place_trades()`
- `data/live_config.json` — new file with per-trade and session-level hard stops
- `tests/test_execution_log.py` — 4 new tests
- `tests/test_live_execution.py` — 3 new tests

---

## Design

### 1. `data/live_config.json` — Hard Stops

Created automatically on first run if missing:

```json
{
  "max_trade_dollars": 50,
  "daily_loss_limit": 200,
  "max_open_positions": 10
}
```

Loaded once at session start by `_load_live_config() -> dict` in `main.py`. Values enforced before every live order:

- `max_trade_dollars` — Kelly-computed bet size is capped at this value regardless of signal strength
- `daily_loss_limit` — if session realized losses exceed this amount, `--live` is disabled for the remainder of the session; a clear warning is printed and subsequent trades fall back to paper
- `max_open_positions` — if count of open live orders (status `pending` or `filled`, not yet settled) reaches this limit, no new live orders are placed until one closes

### 2. `--live` Flag

Added to `cmd_watch` and `cmd_analyze` argument parsers. Default: absent (paper only).

```python
parser.add_argument("--live", action="store_true",
                    help="Place real orders via Kalshi API (requires live_config.json)")
```

When `--live` is present:
- `_load_live_config()` is called; if `data/live_config.json` is missing, the program exits with a clear message asking the user to create it
- A session-level `_session_loss: float = 0.0` accumulator is initialized
- `_auto_place_trades()` calls `_place_live_order()` instead of `place_paper_order()`

Without `--live`, behavior is identical to today.

### 3. `_place_live_order()` — Live Execution Path

New function in `main.py`:

```python
def _place_live_order(
    ticker: str,
    side: str,
    analysis: dict,
    config: dict,
    session_loss: float,
) -> tuple[bool, float]:  # (placed, cost)
```

Steps:
1. **Daily loss check** — if `session_loss >= config["daily_loss_limit"]`, log warning, return `(False, 0.0)`
2. **Open position check** — count live orders not yet settled; if >= `max_open_positions`, skip
3. **Size computation** — Kelly quantity from `paper.kelly_quantity()`; cap dollar cost at `max_trade_dollars`
4. **Price resolution** — see Section 4 (limit order strategy)
5. **Cycle check** — see Section 5; skip if already ordered this cycle
6. **Order placement** — call `kalshi_client.place_order(ticker, side, count, price, time_in_force="good_till_canceled")`
7. **Log** — `execution_log.log_order(..., live=True, forecast_cycle=cycle, status="pending")`
8. **Return** `(True, cost)` so caller can update session loss accumulator

### 4. Limit Order Strategy

Applies only to live orders. Paper trades are unchanged.

**Price resolution for STRONG signals (edge ≥ 0.20):**

```python
def _midpoint_price(market: dict, side: str) -> float:
    """Return midpoint of current bid/ask for the given side, rounded to 2dp."""
    if side == "yes":
        bid = market.get("yes_bid", 0) / 100
        ask = market.get("yes_ask", 100) / 100
    else:  # "no"
        bid = (100 - market.get("yes_ask", 100)) / 100
        ask = (100 - market.get("yes_bid", 0)) / 100
    return round((bid + ask) / 2, 2)
```

Order placed with `time_in_force="good_till_canceled"`.

**GTC order lifecycle:**
- Logged with `status="pending"` at placement
- Each iteration of `cmd_watch` calls `_poll_pending_orders()`, which queries `client.get_order(order_id)` for all pending live orders and updates `execution_log` to `"filled"` or `"expired"`
- Spread capture is computed and logged when an order fills: `improvement = ask_at_placement - fill_price`

**Borderline signals (edge 0.10–0.19)** are not auto-placed (existing STRONG threshold unchanged) so no limit order logic applies to them.

### 5. Cycle-Aware Deduplication

**Schema migration** — two new columns added to `execution_log.orders` via the existing try/except migration pattern:

```sql
ALTER TABLE orders ADD COLUMN forecast_cycle TEXT;
ALTER TABLE orders ADD COLUMN live INTEGER DEFAULT 0;
```

**New function:**

```python
def was_ordered_this_cycle(ticker: str, side: str, cycle: str) -> bool:
    """Return True if an order for ticker+side was placed on this forecast cycle."""
```

Queries `orders` where `ticker=?`, `side=?`, `forecast_cycle=?`, `status != 'failed'`.

**Wired into `_auto_place_trades()`:**

```python
cycle = _current_forecast_cycle()  # already exists in weather_markets.py
if was_ordered_this_cycle(ticker, side, cycle):
    continue
```

This check runs for both paper and live orders — prevents paper spam too.

**`log_order()` signature extended** with two new optional keyword args:

```python
def log_order(
    ...,
    forecast_cycle: str | None = None,
    live: bool = False,
) -> int:
```

---

## Fallback and Safety

- If `kalshi_client.place_order()` raises any exception, the error is logged to `execution_log` with `status="failed"` and the session continues — no crash
- If `daily_loss_limit` is hit mid-session, a prominent warning is printed: `"Daily loss limit reached — live trading disabled for this session"`. Paper trading continues normally
- If `data/live_config.json` is missing and `--live` is passed, the program exits with a helpful message before any orders are attempted
- `was_ordered_this_cycle()` is a read-only DB query — no risk of side effects in the deduplication check itself

---

## Testing

**`tests/test_execution_log.py`** — 4 new tests:
1. `test_forecast_cycle_column_exists` — schema migration adds `forecast_cycle` and `live` columns
2. `test_was_ordered_this_cycle_true` — seed order with cycle "12z", verify returns True for same cycle
3. `test_was_ordered_this_cycle_false_different_cycle` — seed with "06z", check "12z" returns False
4. `test_log_order_stores_cycle_and_live` — log_order with cycle + live=True; verify retrieved row has correct values

**`tests/test_live_execution.py`** — 3 new tests:
1. `test_daily_loss_limit_blocks_order` — session_loss >= daily_loss_limit → `_place_live_order` returns (False, 0.0)
2. `test_max_trade_dollars_caps_size` — Kelly wants $100 bet, max_trade_dollars=50 → order size capped at $50
3. `test_midpoint_price_yes_side` — market with yes_bid=45, yes_ask=55 → midpoint = 0.50

---

## Out of Scope

- Real settlement tracking for live positions (live trades are placed; outcome tracking remains manual via `log_outcome()` as today)
- Partial fill handling — assumes all-or-nothing fills for now
- Order cancellation UI — GTC orders can be canceled manually via Kalshi interface; no cancel-from-bot for this iteration
