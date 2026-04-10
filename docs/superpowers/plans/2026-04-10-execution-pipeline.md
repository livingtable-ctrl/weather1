# Execution Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add real money auto-placement via Kalshi API with hard stops, GTC midpoint limit orders for STRONG signals, and cycle-aware deduplication to prevent re-trading stale forecasts.

**Architecture:** Three focused changes — a `--live` CLI flag gates real orders and loads per-session hard stops from `data/live_config.json`; `_place_live_order()` resolves GTC midpoint prices and calls `kalshi_client.place_order()`; `execution_log` gains `forecast_cycle` and `live` columns with a `was_ordered_this_cycle()` check wired into `_auto_place_trades()` before every placement.

**Tech Stack:** Python 3.11, SQLite (execution_log.py), Kalshi REST API (kalshi_client.py), pytest

---

## Files Changed

| File | Change |
|---|---|
| `execution_log.py` | Schema migration (`forecast_cycle TEXT`, `live INTEGER`); new `was_ordered_this_cycle()`; extend `log_order()` signature |
| `main.py` | Add `_LIVE_CONFIG_PATH`, `_SESSION_LOSS`, `_load_live_config()`, `_midpoint_price()`, `_count_open_live_orders()`, `_place_live_order()`, `_poll_pending_orders()`; update `_auto_place_trades()`, `cmd_watch()`, `cmd_analyze()`, CLI dispatch |
| `kalshi_client.py` | Add `get_order(order_id)` method |
| `data/live_config.json` | Create with safe defaults |
| `tests/test_execution_log.py` | Create — 4 tests |
| `tests/test_live_execution.py` | Create — 3 tests |

---

## Task 1 — `execution_log` schema migration + `was_ordered_this_cycle()` + updated `log_order()`

**TDD: write tests first, confirm red, implement, confirm green, commit.**

### Step 1.1 — Write failing tests

Create `tests/test_execution_log.py`:

```python
import shutil
import tempfile
from pathlib import Path
import pytest
import execution_log


class TestExecutionLogMigration:
    def setup_method(self):
        self._tmpdir = tempfile.mkdtemp()
        self._orig = execution_log.DB_PATH
        execution_log.DB_PATH = Path(self._tmpdir) / "test_exec.db"
        execution_log._initialized = False

    def teardown_method(self):
        execution_log.DB_PATH = self._orig
        execution_log._initialized = False
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_forecast_cycle_and_live_columns_exist(self):
        import sqlite3
        execution_log.init_log()
        with sqlite3.connect(str(execution_log.DB_PATH)) as con:
            cols = {row[1] for row in con.execute("PRAGMA table_info(orders)")}
        assert "forecast_cycle" in cols
        assert "live" in cols

    def test_was_ordered_this_cycle_true(self):
        execution_log.init_log()
        execution_log.log_order("T1", "yes", 5, 0.55, forecast_cycle="12z", live=True)
        assert execution_log.was_ordered_this_cycle("T1", "yes", "12z") is True

    def test_was_ordered_this_cycle_false_different_cycle(self):
        execution_log.init_log()
        execution_log.log_order("T1", "yes", 5, 0.55, forecast_cycle="06z", live=True)
        assert execution_log.was_ordered_this_cycle("T1", "yes", "12z") is False

    def test_log_order_stores_cycle_and_live_flag(self):
        import sqlite3
        execution_log.init_log()
        row_id = execution_log.log_order("T2", "no", 3, 0.40, forecast_cycle="00z", live=True)
        with sqlite3.connect(str(execution_log.DB_PATH)) as con:
            row = con.execute(
                "SELECT forecast_cycle, live FROM orders WHERE id=?", (row_id,)
            ).fetchone()
        assert row[0] == "00z"
        assert row[1] == 1
```

- [ ] Run: `cd "C:/Users/thesa/claude kalshi" && python -m pytest tests/test_execution_log.py -v 2>&1 | tail -15`
- [ ] Confirm all 4 tests **FAIL** (columns don't exist yet, `log_order` doesn't accept `forecast_cycle`/`live`)

### Step 1.2 — Implement: extend migrations list in `init_log()`

In `execution_log.py` at line 59, find the `migrations` list and extend it with two new entries. The full updated list:

```python
    migrations = [
        "ALTER TABLE orders ADD COLUMN fill_quantity INTEGER",
        "ALTER TABLE orders ADD COLUMN error_code TEXT",
        "ALTER TABLE orders ADD COLUMN error_type TEXT",
        "ALTER TABLE orders ADD COLUMN forecast_cycle TEXT",
        "ALTER TABLE orders ADD COLUMN live INTEGER DEFAULT 0",
    ]
```

### Step 1.3 — Implement: add `was_ordered_this_cycle()` after `was_recently_ordered()`

Insert after the closing of `was_recently_ordered()` (after line 164 in the current file):

```python
def was_ordered_this_cycle(ticker: str, side: str, cycle: str) -> bool:
    """Return True if an order for ticker+side was placed on this forecast cycle."""
    init_log()
    with _conn() as con:
        row = con.execute(
            """
            SELECT 1 FROM orders
            WHERE ticker = ? AND side = ? AND forecast_cycle = ? AND status != 'failed'
            LIMIT 1
            """,
            (ticker, side, cycle),
        ).fetchone()
    return row is not None
```

### Step 1.4 — Implement: extend `log_order()` signature

Replace the existing `log_order()` function (lines 73–114) with the extended version that accepts `forecast_cycle` and `live`:

```python
def log_order(
    ticker: str,
    side: str,
    quantity: int,
    price: float,
    order_type: str = "limit",
    status: str = "sent",
    response: dict | None = None,
    error: str | None = None,
    fill_quantity: int | None = None,
    error_code: str | None = None,
    error_type: str | None = None,
    forecast_cycle: str | None = None,
    live: bool = False,
) -> int:
    """Record a live order attempt. Returns the new row ID."""
    init_log()
    with _conn() as con:
        cur = con.execute(
            """
            INSERT INTO orders
              (ticker, side, quantity, price, order_type, status, response, error,
               placed_at, fill_quantity, error_code, error_type, forecast_cycle, live)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ticker, side, quantity, price, order_type, status,
                json.dumps(response) if response else None, error,
                datetime.now(UTC).isoformat(),
                fill_quantity, error_code, error_type,
                forecast_cycle, int(live),
            ),
        )
        return cur.lastrowid or 0
```

### Step 1.5 — Confirm green

- [ ] Run: `cd "C:/Users/thesa/claude kalshi" && python -m pytest tests/test_execution_log.py -v 2>&1 | tail -15`
- [ ] Expected output:
  ```
  tests/test_execution_log.py::TestExecutionLogMigration::test_forecast_cycle_and_live_columns_exist PASSED
  tests/test_execution_log.py::TestExecutionLogMigration::test_was_ordered_this_cycle_true PASSED
  tests/test_execution_log.py::TestExecutionLogMigration::test_was_ordered_this_cycle_false_different_cycle PASSED
  tests/test_execution_log.py::TestExecutionLogMigration::test_log_order_stores_cycle_and_live_flag PASSED
  4 passed
  ```

### Step 1.6 — Commit

```
git add execution_log.py tests/test_execution_log.py && git commit -m "feat: add forecast_cycle/live columns + was_ordered_this_cycle() to execution_log"
```

---

## Task 2 — `_midpoint_price()` in `main.py`

**TDD: write test first, confirm red, implement, confirm green, commit.**

### Step 2.1 — Write failing test

Create `tests/test_live_execution.py`:

```python
import sys
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).parent.parent))


class TestMidpointPrice:
    def test_yes_side_midpoint(self):
        from main import _midpoint_price
        market = {"yes_bid": 45, "yes_ask": 55}
        assert _midpoint_price(market, "yes") == pytest.approx(0.50, abs=0.01)

    def test_no_side_midpoint(self):
        from main import _midpoint_price
        market = {"yes_bid": 45, "yes_ask": 55}
        # NO bid = 1 - yes_ask = 0.45, NO ask = 1 - yes_bid = 0.55
        # midpoint = 0.50
        assert _midpoint_price(market, "no") == pytest.approx(0.50, abs=0.01)
```

- [ ] Run: `cd "C:/Users/thesa/claude kalshi" && python -m pytest tests/test_live_execution.py::TestMidpointPrice -v 2>&1 | tail -10`
- [ ] Confirm both tests **FAIL** (`ImportError: cannot import name '_midpoint_price' from 'main'`)

### Step 2.2 — Implement `_midpoint_price()` in `main.py`

Add immediately after `_resolve_price()` (after line 1076):

```python
def _midpoint_price(market: dict, side: str) -> float:
    """Midpoint of current bid/ask for the given side. Used for GTC limit orders.

    Kalshi prices in market dict are 0-100 integers; result is 0.0-1.0.
    """
    yes_bid = (market.get("yes_bid") or 0) / 100
    yes_ask = (market.get("yes_ask") or 100) / 100
    if side == "yes":
        return round((yes_bid + yes_ask) / 2, 2)
    # NO prices: no_bid = 1 - yes_ask, no_ask = 1 - yes_bid
    no_bid = 1.0 - yes_ask
    no_ask = 1.0 - yes_bid
    return round((no_bid + no_ask) / 2, 2)
```

### Step 2.3 — Confirm green

- [ ] Run: `cd "C:/Users/thesa/claude kalshi" && python -m pytest tests/test_live_execution.py::TestMidpointPrice -v 2>&1 | tail -10`
- [ ] Expected output:
  ```
  tests/test_live_execution.py::TestMidpointPrice::test_yes_side_midpoint PASSED
  tests/test_live_execution.py::TestMidpointPrice::test_no_side_midpoint PASSED
  2 passed
  ```

### Step 2.4 — Commit

```
git add main.py tests/test_live_execution.py && git commit -m "feat: add _midpoint_price() for GTC limit order price resolution"
```

---

## Task 3 — `_load_live_config()` + `data/live_config.json`

**TDD: write test first, confirm red, implement, confirm green, commit.**

### Step 3.1 — Write failing test

Append to `tests/test_live_execution.py`:

```python
import shutil
import tempfile


class TestLoadLiveConfig:
    def setup_method(self):
        self._tmpdir = tempfile.mkdtemp()

    def teardown_method(self):
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_creates_default_config_if_missing(self, monkeypatch):
        from pathlib import Path
        import main
        tmp_path = Path(self._tmpdir) / "live_config.json"
        monkeypatch.setattr(main, "_LIVE_CONFIG_PATH", tmp_path)
        cfg = main._load_live_config()
        assert cfg["max_trade_dollars"] == 50
        assert cfg["daily_loss_limit"] == 200
        assert cfg["max_open_positions"] == 10
        assert tmp_path.exists()
```

- [ ] Run: `cd "C:/Users/thesa/claude kalshi" && python -m pytest tests/test_live_execution.py::TestLoadLiveConfig -v 2>&1 | tail -10`
- [ ] Confirm test **FAILS** (`AttributeError: module 'main' has no attribute '_LIVE_CONFIG_PATH'`)

### Step 3.2 — Implement module-level constants and `_load_live_config()`

Add after the existing module-level constants near the top of `main.py` (after the existing `Path` imports are resolved — search for other module-level `Path(...)` constants and add nearby):

```python
_LIVE_CONFIG_PATH = Path(__file__).parent / "data" / "live_config.json"
_LIVE_CONFIG_DEFAULT = {
    "max_trade_dollars": 50,
    "daily_loss_limit": 200,
    "max_open_positions": 10,
}
_SESSION_LOSS: float = 0.0


def _load_live_config() -> dict:
    """Load live trading hard stops from data/live_config.json.
    Creates file with safe defaults if missing.
    """
    if not _LIVE_CONFIG_PATH.exists():
        _LIVE_CONFIG_PATH.parent.mkdir(exist_ok=True)
        _LIVE_CONFIG_PATH.write_text(json.dumps(_LIVE_CONFIG_DEFAULT, indent=2))
        print(f"  Created default live config: {_LIVE_CONFIG_PATH}")
    return json.loads(_LIVE_CONFIG_PATH.read_text())
```

### Step 3.3 — Create `data/live_config.json`

Create the file `data/live_config.json` in the project root:

```json
{
  "max_trade_dollars": 50,
  "daily_loss_limit": 200,
  "max_open_positions": 10
}
```

### Step 3.4 — Confirm green

- [ ] Run: `cd "C:/Users/thesa/claude kalshi" && python -m pytest tests/test_live_execution.py::TestLoadLiveConfig -v 2>&1 | tail -10`
- [ ] Expected output:
  ```
  tests/test_live_execution.py::TestLoadLiveConfig::test_creates_default_config_if_missing PASSED
  1 passed
  ```

### Step 3.5 — Commit

```
git add main.py data/live_config.json tests/test_live_execution.py && git commit -m "feat: add _load_live_config() and default data/live_config.json for live trading limits"
```

---

## Task 4 — `_count_open_live_orders()` + `_place_live_order()`

**TDD: write tests first, confirm red, implement, confirm green, commit.**

### Step 4.1 — Write failing tests

Append to `tests/test_live_execution.py`:

```python
import execution_log


class TestPlaceLiveOrder:
    def setup_method(self):
        self._tmpdir = tempfile.mkdtemp()
        self._orig_db = execution_log.DB_PATH
        execution_log.DB_PATH = Path(self._tmpdir) / "test_exec.db"
        execution_log._initialized = False

    def teardown_method(self):
        execution_log.DB_PATH = self._orig_db
        execution_log._initialized = False
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_daily_loss_limit_blocks_order(self, monkeypatch):
        import main
        monkeypatch.setattr(main, "_SESSION_LOSS", 200.0)
        config = {"max_trade_dollars": 50, "daily_loss_limit": 200, "max_open_positions": 10}
        placed, cost = main._place_live_order(
            "TICKER", "yes", {}, {}, config, client=None
        )
        assert placed is False
        assert cost == 0.0

    def test_max_trade_dollars_caps_size(self, monkeypatch):
        import main
        monkeypatch.setattr(main, "_SESSION_LOSS", 0.0)

        # Patch dependencies so Kelly wants $100 but cap is $50
        monkeypatch.setattr(main, "_count_open_live_orders", lambda: 0)
        monkeypatch.setattr(main, "_midpoint_price", lambda m, s: 0.50)

        calls = []
        def fake_place_order(ticker, side, action, count, price, time_in_force):
            calls.append({"count": count, "price": price})
            return {"order": {"order_id": "abc123", "status": "resting"}}

        fake_client = type("C", (), {"place_order": fake_place_order})()

        def fake_portfolio_kelly(frac, city, date, side):
            return 0.10  # large kelly
        def fake_kelly_quantity(frac, price):
            return 200  # uncapped would be 200
        def fake_kelly_bet_dollars(frac):
            return 100.0

        monkeypatch.setattr("paper.portfolio_kelly_fraction", fake_portfolio_kelly)
        monkeypatch.setattr("paper.kelly_quantity", fake_kelly_quantity)
        monkeypatch.setattr("paper.kelly_bet_dollars", fake_kelly_bet_dollars)

        config = {"max_trade_dollars": 50, "daily_loss_limit": 200, "max_open_positions": 10}
        analysis = {"ci_adjusted_kelly": 0.10, "forecast_prob": 0.60}
        market = {"yes_bid": 45, "yes_ask": 55, "_city": "NYC", "_date": None}

        placed, cost = main._place_live_order(
            "KXHIGHNY-26APR10-T72", "yes", analysis, market, config, client=fake_client
        )
        assert placed is True
        assert cost <= 50.0 + 0.01  # within max_trade_dollars + rounding
```

- [ ] Run: `cd "C:/Users/thesa/claude kalshi" && python -m pytest tests/test_live_execution.py::TestPlaceLiveOrder -v 2>&1 | tail -15`
- [ ] Confirm both tests **FAIL** (`ImportError: cannot import name '_place_live_order' from 'main'`)

### Step 4.2 — Implement `_count_open_live_orders()` in `main.py`

Add after `_load_live_config()`:

```python
def _count_open_live_orders() -> int:
    """Count live orders with status 'pending' (GTC not yet filled/expired)."""
    from execution_log import _conn, init_log
    init_log()
    with _conn() as con:
        row = con.execute(
            "SELECT COUNT(*) FROM orders WHERE live=1 AND status='pending'"
        ).fetchone()
    return row[0] if row else 0
```

### Step 4.3 — Implement `_place_live_order()` in `main.py`

Add after `_count_open_live_orders()`:

```python
def _place_live_order(
    ticker: str,
    side: str,
    analysis: dict,
    market: dict,
    config: dict,
    client,
) -> tuple[bool, float]:
    """Place a real GTC limit order via Kalshi API.

    Returns (placed, cost). Enforces daily_loss_limit, max_open_positions,
    max_trade_dollars. Logs to execution_log before and after placement.
    """
    global _SESSION_LOSS
    from execution_log import log_order, log_order_result
    from paper import kelly_quantity, portfolio_kelly_fraction
    from weather_markets import _current_forecast_cycle

    # 1. Daily loss guard
    if _SESSION_LOSS >= config["daily_loss_limit"]:
        print(yellow(
            f"  [Live] Daily loss limit ${config['daily_loss_limit']:.0f} reached"
            " — live trading halted."
        ))
        return False, 0.0

    # 2. Open position limit
    if _count_open_live_orders() >= config["max_open_positions"]:
        print(yellow(
            f"  [Live] Max open positions ({config['max_open_positions']}) reached"
            f" — skipping {ticker}."
        ))
        return False, 0.0

    # 3. Compute size
    city = market.get("_city")
    target_date = market.get("_date")
    target_date_str = target_date.isoformat() if target_date else None
    ci_kelly = analysis.get("ci_adjusted_kelly", analysis.get("fee_adjusted_kelly", 0.0))
    adj_kelly = portfolio_kelly_fraction(ci_kelly, city, target_date_str, side=side)

    entry_price = _midpoint_price(market, side)
    if entry_price <= 0:
        return False, 0.0

    qty = kelly_quantity(adj_kelly, entry_price)
    cost = round(qty * entry_price, 2)

    # 4. Cap at max_trade_dollars
    if cost > config["max_trade_dollars"]:
        qty = max(1, int(config["max_trade_dollars"] / entry_price))
        cost = round(qty * entry_price, 2)

    if qty < 1:
        return False, 0.0

    cycle = _current_forecast_cycle()

    # 5. Log + place
    row_id = log_order(
        ticker, side, qty, entry_price,
        order_type="limit", status="pending",
        forecast_cycle=cycle, live=True,
    )
    try:
        response = client.place_order(
            ticker, side, "buy", qty, entry_price,
            time_in_force="good_till_canceled",
        )
        log_order_result(row_id, status="pending", response=response)
        print(green(
            f"  [Live] #{row_id} {qty}×{ticker} {side.upper()}"
            f" @ ${entry_price:.2f}  GTC limit placed"
        ))
        return True, cost
    except Exception as exc:
        log_order_result(
            row_id, status="failed", error=str(exc),
            error_type=type(exc).__name__,
        )
        print(red(f"  [Live] Order failed for {ticker}: {exc}"))
        return False, 0.0
```

### Step 4.4 — Confirm green

- [ ] Run: `cd "C:/Users/thesa/claude kalshi" && python -m pytest tests/test_live_execution.py::TestPlaceLiveOrder -v 2>&1 | tail -15`
- [ ] Expected output:
  ```
  tests/test_live_execution.py::TestPlaceLiveOrder::test_daily_loss_limit_blocks_order PASSED
  tests/test_live_execution.py::TestPlaceLiveOrder::test_max_trade_dollars_caps_size PASSED
  2 passed
  ```

### Step 4.5 — Commit

```
git add main.py tests/test_live_execution.py && git commit -m "feat: add _place_live_order() with daily loss + position + size hard stops"
```

---

## Task 5 — Cycle check + `--live` flag wired into `_auto_place_trades()` and CLI dispatch

No new tests needed — `was_ordered_this_cycle()` is fully tested in Task 1.

### Step 5.1 — Update `_auto_place_trades()` signature

Change the signature (currently line 1665) from:

```python
def _auto_place_trades(opps: list, client: KalshiClient) -> None:
```

to:

```python
def _auto_place_trades(
    opps: list,
    client: KalshiClient,
    live: bool = False,
    live_config: dict | None = None,
) -> None:
```

Also update the docstring to reflect live mode:

```python
    """
    Auto-place trades for STRONG BUY + LOW risk signals not already held.
    Called from watch --auto mode. In live mode, calls _place_live_order()
    instead of place_paper_order(). Respects drawdown guard and portfolio Kelly.
    """
```

### Step 5.2 — Add cycle check and live branch inside the `_auto_place_trades()` loop

Inside the for loop, after `if a.get("time_risk") == "HIGH": continue` (after line 1707), add:

```python
        from execution_log import was_ordered_this_cycle
        from weather_markets import _current_forecast_cycle
        cycle = _current_forecast_cycle()

        # Cycle-aware deduplication — skip if already traded this forecast cycle
        if was_ordered_this_cycle(ticker, rec_side, cycle):
            continue

        # Live order placement
        if live and live_config is not None:
            placed_ok, cost = _place_live_order(
                ticker, rec_side, a, m, live_config, client
            )
            if placed_ok:
                global _SESSION_LOSS
                _SESSION_LOSS += cost
                open_tickers.add(ticker)
                placed += 1
            continue
```

The existing `try: place_paper_order(...)` block that follows is the non-live (paper) path — it remains unchanged and is now only reached when `live` is False.

### Step 5.3 — Update `cmd_watch()` signature and body

Change the signature (line 1749) from:

```python
def cmd_watch(client: KalshiClient, auto_trade: bool = False, min_edge: float = 0.10):
```

to:

```python
def cmd_watch(
    client: KalshiClient,
    auto_trade: bool = False,
    min_edge: float = 0.10,
    live: bool = False,
    live_config: dict | None = None,
):
```

Update the banner print to reflect live mode. Find the existing auto_trade banner:

```python
    if auto_trade:
        print(
            yellow(
                "  Auto-trade: STRONG BUY + LOW risk signals → paper orders placed automatically.\n"
            )
        )
```

Replace with:

```python
    if auto_trade:
        if live:
            print(
                yellow(
                    "  Auto-trade: STRONG BUY + LOW risk signals → LIVE orders placed via Kalshi API.\n"
                )
            )
        else:
            print(
                yellow(
                    "  Auto-trade: STRONG BUY + LOW risk signals → paper orders placed automatically.\n"
                )
            )
```

Update the call to `_auto_place_trades` in the watch loop (currently line 1796):

```python
            if auto_trade and liquid_opps:
                _auto_place_trades(liquid_opps, client, live=live, live_config=live_config)
```

### Step 5.4 — Update `cmd_analyze()` signature and body

Change the signature (line 1632) from:

```python
def cmd_analyze(client: KalshiClient, min_edge: float | None = None):
```

to:

```python
def cmd_analyze(
    client: KalshiClient,
    min_edge: float | None = None,
    live: bool = False,
    live_config: dict | None = None,
):
```

The body of `cmd_analyze` does not currently call `_auto_place_trades` — it calls `_analyze_once` which does not auto-trade. No further changes are needed inside `cmd_analyze` for this iteration; the `live`/`live_config` params are accepted for future use and to match the CLI dispatch.

### Step 5.5 — Update CLI dispatch for `watch`

Find the `elif cmd == "watch":` block (around line 5082). Replace:

```python
        cmd_watch(client, auto_trade="--auto" in args, min_edge=min_edge)
```

with:

```python
        live_mode = "--live" in args
        live_cfg = _load_live_config() if live_mode else None
        cmd_watch(
            client,
            auto_trade="--auto" in args,
            min_edge=min_edge,
            live=live_mode,
            live_config=live_cfg,
        )
```

### Step 5.6 — Update CLI dispatch for `analyze`

Find the `elif cmd == "analyze":` block (around line 5072). Replace:

```python
        cmd_analyze(client, min_edge=min_edge)
```

with:

```python
        live_mode = "--live" in args
        live_cfg = _load_live_config() if live_mode else None
        cmd_analyze(client, min_edge=min_edge, live=live_mode, live_config=live_cfg)
```

### Step 5.7 — Smoke test

- [ ] Run: `cd "C:/Users/thesa/claude kalshi" && python -m pytest tests/test_execution_log.py tests/test_live_execution.py -v 2>&1 | tail -20`
- [ ] All 7 tests should pass

### Step 5.8 — Commit

```
git add main.py && git commit -m "feat: wire --live flag and cycle dedup into _auto_place_trades()"
```

---

## Task 6 — `get_order()` in `kalshi_client.py` + `_poll_pending_orders()` in `main.py`

**TDD: write test first, confirm red, implement, confirm green, commit.**

### Step 6.1 — Write failing test

Append to `tests/test_live_execution.py`:

```python
class TestPollPendingOrders:
    def setup_method(self):
        self._tmpdir = tempfile.mkdtemp()
        self._orig_db = execution_log.DB_PATH
        execution_log.DB_PATH = Path(self._tmpdir) / "test_exec.db"
        execution_log._initialized = False

    def teardown_method(self):
        execution_log.DB_PATH = self._orig_db
        execution_log._initialized = False
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_filled_order_status_updated(self, monkeypatch):
        import json
        import main
        execution_log.init_log()

        # Seed a pending live order with an order_id in response
        row_id = execution_log.log_order(
            "TICKER", "yes", 5, 0.55,
            status="pending", live=True,
            response={"order": {"order_id": "ord-abc"}},
        )
        # Ensure the response is stored as JSON string
        import sqlite3
        with sqlite3.connect(str(execution_log.DB_PATH)) as con:
            con.execute(
                "UPDATE orders SET response=? WHERE id=?",
                (json.dumps({"order": {"order_id": "ord-abc"}}), row_id),
            )

        def fake_get_order(order_id):
            return {"order": {"order_id": order_id, "status": "filled"}}

        fake_client = type("C", (), {"get_order": fake_get_order})()
        main._poll_pending_orders(fake_client)

        with sqlite3.connect(str(execution_log.DB_PATH)) as con:
            row = con.execute(
                "SELECT status FROM orders WHERE id=?", (row_id,)
            ).fetchone()
        assert row[0] == "filled"
```

- [ ] Run: `cd "C:/Users/thesa/claude kalshi" && python -m pytest tests/test_live_execution.py::TestPollPendingOrders -v 2>&1 | tail -10`
- [ ] Confirm test **FAILS** (`ImportError: cannot import name '_poll_pending_orders' from 'main'`)

### Step 6.2 — Add `get_order()` to `kalshi_client.py`

In `kalshi_client.py`, add after `get_open_orders()` (after line 197):

```python
    def get_order(self, order_id: str) -> dict:
        """Fetch a single order by ID.

        Returns:
            dict with "order" key containing order details including status.
            Status values: "resting", "filled", "canceled", "expired".
        """
        data = self._get(f"/portfolio/orders/{order_id}", auth=True)
        return data
```

### Step 6.3 — Implement `_poll_pending_orders()` in `main.py`

Add after `_place_live_order()`:

```python
def _poll_pending_orders(client) -> None:
    """Query Kalshi for status of all pending GTC live orders and update execution_log."""
    import json as _json
    from execution_log import _conn, init_log, log_order_result
    init_log()
    with _conn() as con:
        rows = con.execute(
            "SELECT id, response FROM orders WHERE status='pending' AND live=1"
        ).fetchall()
    for row in rows:
        try:
            resp = _json.loads(row["response"]) if row["response"] else {}
            order_id = (resp.get("order") or {}).get("order_id") or resp.get("order_id")
            if not order_id:
                continue
            result = client.get_order(order_id)
            remote_status = (result.get("order") or {}).get("status", "")
            if remote_status in ("filled", "canceled", "expired"):
                log_order_result(row["id"], status=remote_status, response=result)
        except Exception:
            pass
```

### Step 6.4 — Wire `_poll_pending_orders()` into `cmd_watch()`

In the `cmd_watch()` main loop body, after the `_save_watch_state(previous)` call (and before or after the `_auto_place_trades` call), add:

```python
            if live:
                _poll_pending_orders(client)
```

### Step 6.5 — Confirm green

- [ ] Run: `cd "C:/Users/thesa/claude kalshi" && python -m pytest tests/test_live_execution.py::TestPollPendingOrders -v 2>&1 | tail -10`
- [ ] Expected output:
  ```
  tests/test_live_execution.py::TestPollPendingOrders::test_filled_order_status_updated PASSED
  1 passed
  ```

### Step 6.6 — Run full suite

- [ ] Run: `cd "C:/Users/thesa/claude kalshi" && python -m pytest --ignore=tests/test_http.py -q 2>&1 | tail -5`
- [ ] Confirm no regressions — expected output shows all execution_log and live_execution tests passing alongside existing suite

### Step 6.7 — Commit

```
git add kalshi_client.py main.py tests/test_live_execution.py && git commit -m "feat: add _poll_pending_orders() to track GTC live order fills"
```

---

## Self-Review Checklist

- [x] **Every spec requirement has a task:**
  - Real money auto-placement via `kalshi_client.place_order()` with `--live` flag → Tasks 3, 4, 5
  - Config-based hard stops (`daily_loss_limit`, `max_open_positions`, `max_trade_dollars`) → Tasks 3, 4
  - GTC midpoint limit orders instead of taking full spread → Tasks 2, 4
  - Cycle-aware deduplication via `was_ordered_this_cycle()` → Tasks 1, 5
  - `execution_log` schema migration (`forecast_cycle`, `live` columns) → Task 1
  - `data/live_config.json` → Task 3
  - `_poll_pending_orders()` for GTC fill tracking → Task 6
  - `get_order()` in `kalshi_client.py` (missing from current codebase, required by poller) → Task 6
  - `tests/test_execution_log.py` (4 tests) → Task 1
  - `tests/test_live_execution.py` (3 tests + poller test) → Tasks 2, 3, 4, 6

- [x] **No placeholders:** All code blocks are complete with no `...` or "similar to above" shortcuts.

- [x] **Function signatures consistent across tasks:**
  - `_place_live_order(ticker, side, analysis, market, config, client) -> tuple[bool, float]` — defined in Task 4, tested in Task 4, called in Task 5
  - `_auto_place_trades(opps, client, live=False, live_config=None)` — updated in Task 5, called from `cmd_watch` in Task 5
  - `cmd_watch(client, auto_trade, min_edge, live=False, live_config=None)` — updated in Task 5, dispatched from CLI in Task 5
  - `log_order(..., forecast_cycle=None, live=False) -> int` — defined in Task 1, used in Task 4
  - `was_ordered_this_cycle(ticker, side, cycle) -> bool` — defined in Task 1, used in Task 5
  - `_poll_pending_orders(client)` — defined in Task 6, wired into `cmd_watch` in Task 6
  - `KalshiClient.get_order(order_id) -> dict` — added in Task 6, used by `_poll_pending_orders` in Task 6
