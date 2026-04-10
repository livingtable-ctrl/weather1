# Live Order Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close five gaps in the live order lifecycle — persistent daily loss counter, settlement tracking, automated GTC cancellation, live tax export, and live P&L in the dashboard.

**Architecture:** Extend `execution_log.db` with two new tables/columns; replace the in-memory `_SESSION_LOSS` float with a DB-backed counter; extend `_poll_pending_orders()` to cancel stale GTC orders and record settlement outcomes; add `export_live_tax_csv()` and `get_live_pnl_summary()` to `execution_log.py`; wire a new `/api/live-pnl` endpoint into the dashboard.

**Tech Stack:** Python 3.11, SQLite (via `execution_log.py`), Flask (`web_app.py`), vanilla JS (`static/dashboard.js`), pytest

---

### Task 1: Add daily_live_loss table and functions to execution_log.py

**Files:**
- Modify: `execution_log.py`
- Test: `tests/test_execution_log.py`

**Context:** `execution_log.py` already has `init_log()` that creates the `orders` table and runs migrations via a try/except loop. The `_conn()` helper opens WAL-mode SQLite. Follow the same patterns. The `daily_live_loss` table persists today's cumulative live order cost across restarts. `amount > 0` in `add_live_loss` means a cost (loss or spend); `amount < 0` means a gain (called from settlement with `-pnl` for winners).

- [ ] **Step 1: Write two failing tests in `tests/test_execution_log.py`**

Add a new test class after `TestExecutionLogMigration`. The `setup_method` / `teardown_method` pattern is already established — copy it exactly (it handles Windows file-lock cleanup with `gc.collect()`):

```python
class TestDailyLiveLoss:
    def setup_method(self):
        import tempfile
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        execution_log.DB_PATH = Path(self._tmp.name)
        execution_log._initialized = False

    def teardown_method(self):
        import gc
        execution_log._initialized = False
        self._tmp.close()
        gc.collect()
        Path(self._tmp.name).unlink(missing_ok=True)

    def test_daily_live_loss_accumulates(self):
        execution_log.add_live_loss(10.0)
        execution_log.add_live_loss(5.0)
        assert execution_log.get_today_live_loss() == pytest.approx(15.0)

    def test_daily_live_loss_returns_zero_for_new_day(self):
        """Seeding yesterday's row should not affect today's total."""
        from datetime import UTC, datetime, timedelta
        execution_log.init_log()
        yesterday = (datetime.now(UTC) - timedelta(days=1)).strftime("%Y-%m-%d")
        with execution_log._conn() as con:
            con.execute(
                "INSERT INTO daily_live_loss (date, total, updated_at) VALUES (?, ?, ?)",
                (yesterday, 999.0, datetime.now(UTC).isoformat()),
            )
        assert execution_log.get_today_live_loss() == pytest.approx(0.0)
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/test_execution_log.py::TestDailyLiveLoss -v
```

Expected: `AttributeError: module 'execution_log' has no attribute 'add_live_loss'`

- [ ] **Step 3: Add `daily_live_loss` table to `init_log()` in `execution_log.py`**

In `init_log()`, the `con.executescript(...)` block creates the `orders` table. Add the new table to the same script:

```python
    with _conn() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS orders (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker         TEXT    NOT NULL,
            side           TEXT    NOT NULL,
            quantity       INTEGER NOT NULL,
            price          REAL    NOT NULL,
            order_type     TEXT,
            status         TEXT,
            response       TEXT,
            error          TEXT,
            placed_at      TEXT    NOT NULL,
            fill_quantity  INTEGER,
            error_code     TEXT,
            error_type     TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_orders_ticker    ON orders(ticker, placed_at);
        CREATE INDEX IF NOT EXISTS idx_orders_status    ON orders(status);
        CREATE INDEX IF NOT EXISTS idx_orders_placed_at ON orders(placed_at);

        CREATE TABLE IF NOT EXISTS daily_live_loss (
            date       TEXT PRIMARY KEY,
            total      REAL NOT NULL DEFAULT 0.0,
            updated_at TEXT NOT NULL
        );
        """)
```

- [ ] **Step 4: Add `get_today_live_loss()` and `add_live_loss()` to `execution_log.py`**

Add after the existing `was_ordered_this_cycle()` function:

```python
def get_today_live_loss() -> float:
    """Return today's accumulated live loss in dollars (UTC date). Returns 0.0 if no row."""
    init_log()
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    with _conn() as con:
        row = con.execute(
            "SELECT total FROM daily_live_loss WHERE date = ?", (today,)
        ).fetchone()
    return row["total"] if row else 0.0


def add_live_loss(amount: float) -> float:
    """Add amount to today's live loss total and return the new total.

    amount > 0 means a cost (order placed, loss settled).
    amount < 0 means a gain (winning settlement).
    Uses INSERT ... ON CONFLICT so concurrent calls are safe.
    """
    init_log()
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    now_iso = datetime.now(UTC).isoformat()
    try:
        with _conn() as con:
            con.execute(
                """
                INSERT INTO daily_live_loss (date, total, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(date) DO UPDATE SET
                    total = total + excluded.total,
                    updated_at = excluded.updated_at
                """,
                (today, amount, now_iso),
            )
            row = con.execute(
                "SELECT total FROM daily_live_loss WHERE date = ?", (today,)
            ).fetchone()
        return row["total"] if row else amount
    except Exception as exc:
        import warnings
        warnings.warn(f"add_live_loss DB write failed: {exc}")
        return get_today_live_loss()
```

- [ ] **Step 5: Run tests to verify they pass**

```
pytest tests/test_execution_log.py::TestDailyLiveLoss -v
```

Expected: 2 passed

- [ ] **Step 6: Commit**

```bash
git add execution_log.py tests/test_execution_log.py
git commit -m "feat: add daily_live_loss table and get/add functions to execution_log (#A)"
```

---

### Task 2: Replace _SESSION_LOSS with DB-backed daily loss in main.py

**Files:**
- Modify: `main.py`
- Modify: `tests/test_live_execution.py`

**Context:** `_SESSION_LOSS` is a module-level float at line ~1062. It's read in `_place_live_order()` (~line 1174) and incremented in `_auto_place_trades()` (~line 1941). Remove the variable and replace both usages. Also add `gtc_cancel_hours: 24` to `_LIVE_CONFIG_DEFAULT` (used by Task 4). The existing test `TestPlaceLiveOrder.test_daily_loss_limit_blocks_order` patches `main._SESSION_LOSS` — it must be replaced.

- [ ] **Step 1: Write the replacement test in `tests/test_live_execution.py`**

Replace the entire `test_daily_loss_limit_blocks_order` method inside `TestPlaceLiveOrder`:

```python
    def test_daily_loss_limit_blocks_after_db_loss(self, monkeypatch):
        """Daily loss limit blocks order when DB-backed loss is at or above limit."""
        import gc
        import tempfile
        from pathlib import Path
        import execution_log
        import main

        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        monkeypatch.setattr(execution_log, "DB_PATH", Path(tmp.name))
        monkeypatch.setattr(execution_log, "_initialized", False)

        # Seed today's loss at the limit
        execution_log.add_live_loss(100.0)

        config = {
            "max_trade_dollars": 50,
            "daily_loss_limit": 100,
            "max_open_positions": 10,
            "gtc_cancel_hours": 24,
        }
        placed, cost = main._place_live_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            analysis={
                "kelly_quantity": 2,
                "implied_prob": 0.55,
                "market": {"yes_bid": 50, "yes_ask": 60},
            },
            config=config,
            client=None,
            cycle="12z",
        )
        assert placed is False
        assert cost == 0.0

        execution_log._initialized = False
        gc.collect()
        tmp.close()
        Path(tmp.name).unlink(missing_ok=True)
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest tests/test_live_execution.py::TestPlaceLiveOrder::test_daily_loss_limit_blocks_after_db_loss -v
```

Expected: FAIL — `_place_live_order` still reads `_SESSION_LOSS`

- [ ] **Step 3: Update `_LIVE_CONFIG_DEFAULT` in `main.py`**

Find the block around line 1063:

```python
_LIVE_CONFIG_DEFAULT: dict = {
    "max_trade_dollars": 50,
    "daily_loss_limit": 200,
    "max_open_positions": 10,
}
```

Replace with:

```python
_LIVE_CONFIG_DEFAULT: dict = {
    "max_trade_dollars": 50,
    "daily_loss_limit": 200,
    "max_open_positions": 10,
    "gtc_cancel_hours": 24,
}
```

- [ ] **Step 4: Remove `_SESSION_LOSS` and update `_place_live_order()` in `main.py`**

Delete this line (around line 1062):

```python
_SESSION_LOSS: float = 0.0  # updated by _auto_place_trades() after each live order
```

In `_place_live_order()`, find the daily loss check (around line 1174):

```python
    if _SESSION_LOSS >= config["daily_loss_limit"]:
        print(
            f"[LIVE] Daily loss limit ${config['daily_loss_limit']} reached — skipping {ticker}"
        )
        return False, 0.0
```

Replace with:

```python
    if execution_log.get_today_live_loss() >= config["daily_loss_limit"]:
        print(
            f"[LIVE] Daily loss limit ${config['daily_loss_limit']} reached — skipping {ticker}"
        )
        return False, 0.0
```

- [ ] **Step 5: Update `_auto_place_trades()` in `main.py`**

Find the `global _SESSION_LOSS` declaration inside `_auto_place_trades()` (around line 1865):

```python
    global _SESSION_LOSS  # noqa: PLW0603
```

Delete that line entirely.

Find the `_SESSION_LOSS += cost` line inside `_auto_place_trades()` (around line 1941):

```python
                if opp_placed:
                    _SESSION_LOSS += cost
                    open_tickers.add(ticker)
                    placed += 1
```

Replace with:

```python
                if opp_placed:
                    execution_log.add_live_loss(cost)
                    open_tickers.add(ticker)
                    placed += 1
```

- [ ] **Step 6: Run the replacement test to verify it passes**

```
pytest tests/test_live_execution.py::TestPlaceLiveOrder::test_daily_loss_limit_blocks_after_db_loss -v
```

Expected: PASS

- [ ] **Step 7: Run the full test suite to verify no regressions**

```
pytest tests/test_live_execution.py tests/test_execution_log.py -v
```

Expected: all pass (the old `test_daily_loss_limit_blocks_order` is now gone, replaced by the new test)

- [ ] **Step 8: Commit**

```bash
git add main.py tests/test_live_execution.py
git commit -m "feat: replace _SESSION_LOSS with DB-backed daily_live_loss counter (#A)"
```

---

### Task 3: Add settlement columns and functions to execution_log.py

**Files:**
- Modify: `execution_log.py`
- Test: `tests/test_execution_log.py`

**Context:** Three new columns on `orders`: `settled_at` (ISO timestamp), `outcome_yes` (INTEGER 1/0), `pnl` (REAL). Added via the existing migration try/except loop. Two new functions: `get_filled_unsettled_live_orders()` returns orders ready for settlement check; `record_live_settlement()` writes the outcome.

- [ ] **Step 1: Write two failing tests in `tests/test_execution_log.py`**

Add a new class after `TestDailyLiveLoss`:

```python
class TestLiveSettlement:
    def setup_method(self):
        import tempfile
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        execution_log.DB_PATH = Path(self._tmp.name)
        execution_log._initialized = False

    def teardown_method(self):
        import gc
        execution_log._initialized = False
        self._tmp.close()
        gc.collect()
        Path(self._tmp.name).unlink(missing_ok=True)

    def test_record_live_settlement_writes_outcome(self):
        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=2,
            price=0.55,
            status="filled",
            live=True,
        )
        execution_log.record_live_settlement(row_id, outcome_yes=True, pnl=0.837)
        with execution_log._conn() as con:
            row = con.execute(
                "SELECT settled_at, outcome_yes, pnl FROM orders WHERE id = ?",
                (row_id,),
            ).fetchone()
        assert row["outcome_yes"] == 1
        assert row["pnl"] == pytest.approx(0.837)
        assert row["settled_at"] is not None

    def test_get_filled_unsettled_excludes_settled_orders(self):
        id1 = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=1,
            price=0.55,
            status="filled",
            live=True,
        )
        id2 = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T80",
            side="yes",
            quantity=1,
            price=0.60,
            status="filled",
            live=True,
        )
        # Settle id2 only
        execution_log.record_live_settlement(id2, outcome_yes=False, pnl=-0.60)
        unsettled = execution_log.get_filled_unsettled_live_orders()
        ids = [o["id"] for o in unsettled]
        assert id1 in ids
        assert id2 not in ids
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/test_execution_log.py::TestLiveSettlement -v
```

Expected: `AttributeError: module 'execution_log' has no attribute 'record_live_settlement'`

- [ ] **Step 3: Add settlement columns to the migrations list in `execution_log.py`**

Find the `migrations = [...]` list in `init_log()`:

```python
    migrations = [
        "ALTER TABLE orders ADD COLUMN fill_quantity INTEGER",
        "ALTER TABLE orders ADD COLUMN error_code TEXT",
        "ALTER TABLE orders ADD COLUMN error_type TEXT",
        "ALTER TABLE orders ADD COLUMN forecast_cycle TEXT",
        "ALTER TABLE orders ADD COLUMN live INTEGER DEFAULT 0",
    ]
```

Replace with:

```python
    migrations = [
        "ALTER TABLE orders ADD COLUMN fill_quantity INTEGER",
        "ALTER TABLE orders ADD COLUMN error_code TEXT",
        "ALTER TABLE orders ADD COLUMN error_type TEXT",
        "ALTER TABLE orders ADD COLUMN forecast_cycle TEXT",
        "ALTER TABLE orders ADD COLUMN live INTEGER DEFAULT 0",
        "ALTER TABLE orders ADD COLUMN settled_at TEXT",
        "ALTER TABLE orders ADD COLUMN outcome_yes INTEGER",
        "ALTER TABLE orders ADD COLUMN pnl REAL",
    ]
```

- [ ] **Step 4: Add `get_filled_unsettled_live_orders()` and `record_live_settlement()` to `execution_log.py`**

Add after `add_live_loss()`:

```python
def get_filled_unsettled_live_orders() -> list[dict]:
    """Return live filled orders that have not yet had their settlement outcome recorded."""
    init_log()
    with _conn() as con:
        rows = con.execute(
            """
            SELECT * FROM orders
            WHERE live = 1 AND status = 'filled' AND settled_at IS NULL
            ORDER BY placed_at
            """,
        ).fetchall()
    return [dict(r) for r in rows]


def record_live_settlement(order_id: int, outcome_yes: bool, pnl: float) -> None:
    """Write settlement outcome to an order row.

    outcome_yes=True means the YES side won (the market resolved 'yes').
    pnl is net P&L after Kalshi fee, in dollars.
    """
    init_log()
    with _conn() as con:
        con.execute(
            """
            UPDATE orders
            SET settled_at = ?, outcome_yes = ?, pnl = ?
            WHERE id = ?
            """,
            (datetime.now(UTC).isoformat(), int(outcome_yes), pnl, order_id),
        )
```

- [ ] **Step 5: Run tests to verify they pass**

```
pytest tests/test_execution_log.py::TestLiveSettlement -v
```

Expected: 2 passed

- [ ] **Step 6: Commit**

```bash
git add execution_log.py tests/test_execution_log.py
git commit -m "feat: add settlement columns and get/record functions to execution_log (#B)"
```

---

### Task 4: Extend _poll_pending_orders for GTC cancellation and settlement

**Files:**
- Modify: `main.py`
- Test: `tests/test_live_execution.py`

**Context:** `_poll_pending_orders(client)` is at line ~1129 and is called once per watch iteration at line ~2027. It currently only checks fill status of pending orders. Three new behaviors: (1) cancel pending orders older than `gtc_cancel_hours`, (2) check filled+unsettled orders for market finalization, (3) record settlement P&L. The function signature gains `config: dict | None = None`. The call site at line ~2027 already has `live_cfg` in scope — pass it through.

The 1-hour buffer before accepting settlement matches `sync_outcomes()` in `tracker.py` — Kalshi may revise results in the first hour.

P&L formula (price is always the YES-side decimal stored in the order row):
- YES bet wins:  `qty × (1 − price) × (1 − fee)`
- YES bet loses: `−qty × price`
- NO bet wins:   `qty × price × (1 − fee)`
- NO bet loses:  `−qty × (1 − price)`

- [ ] **Step 1: Write three failing tests in `tests/test_live_execution.py`**

Add a new class `TestPollPendingOrdersExtended` after the existing `TestPollPendingOrders`:

```python
class TestPollPendingOrdersExtended:
    def setup_method(self):
        import tempfile
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        import execution_log
        execution_log.DB_PATH = Path(self._tmp.name)
        execution_log._initialized = False

    def teardown_method(self):
        import gc
        import execution_log
        execution_log._initialized = False
        self._tmp.close()
        gc.collect()
        Path(self._tmp.name).unlink(missing_ok=True)

    def test_gtc_cancel_fires_for_old_pending_order(self):
        """Orders older than gtc_cancel_hours are cancelled via the API."""
        from unittest.mock import MagicMock
        from pathlib import Path
        import execution_log
        import main

        # Log a pending live order
        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=2,
            price=0.55,
            status="pending",
            live=True,
            response={"order_id": "ord_abc"},
        )
        # Backdate placed_at to 2 hours ago
        from datetime import UTC, datetime, timedelta
        old_time = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
        with execution_log._conn() as con:
            con.execute("UPDATE orders SET placed_at = ? WHERE id = ?", (old_time, row_id))

        mock_client = MagicMock()
        mock_client.cancel_order.return_value = {}

        config = {"gtc_cancel_hours": 1}
        main._poll_pending_orders(mock_client, config=config)

        mock_client.cancel_order.assert_called_once_with("ord_abc")
        orders = execution_log.get_recent_orders(limit=10)
        assert orders[0]["status"] == "cancelled"

    def test_gtc_cancel_skips_fresh_orders(self):
        """Orders younger than gtc_cancel_hours are not cancelled."""
        from unittest.mock import MagicMock
        import execution_log
        import main

        execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=2,
            price=0.55,
            status="pending",
            live=True,
            response={"order_id": "ord_fresh"},
        )

        mock_client = MagicMock()
        mock_client.get_order.return_value = {"status": "resting"}

        config = {"gtc_cancel_hours": 999}
        main._poll_pending_orders(mock_client, config=config)

        mock_client.cancel_order.assert_not_called()

    def test_settlement_recorded_for_finalized_market(self):
        """When a filled order's market is finalized, P&L is computed and recorded."""
        from unittest.mock import MagicMock
        from datetime import UTC, datetime, timedelta
        import execution_log
        import main

        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=2,
            price=0.55,
            status="filled",
            live=True,
            fill_quantity=2,
        )

        # Market finalized more than 1 hour ago
        close_time = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
        mock_client = MagicMock()
        mock_client.get_market.return_value = {
            "status": "finalized",
            "result": "yes",
            "close_time": close_time,
        }

        main._poll_pending_orders(mock_client, config={})

        orders = execution_log.get_recent_orders(limit=10)
        order = orders[0]
        assert order["outcome_yes"] == 1
        assert order["settled_at"] is not None
        # pnl = 2 * (1 - 0.55) * (1 - 0.07) = 2 * 0.45 * 0.93 = 0.837
        assert order["pnl"] == pytest.approx(0.837, rel=1e-3)
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/test_live_execution.py::TestPollPendingOrdersExtended -v
```

Expected: FAIL — `_poll_pending_orders` takes 1 positional argument

- [ ] **Step 3: Replace `_poll_pending_orders()` in `main.py`**

Find the existing `_poll_pending_orders` function (line ~1129) and replace it entirely:

```python
def _poll_pending_orders(client, config: dict | None = None) -> None:
    """Check fill status of all pending live orders and update execution_log.

    Also auto-cancels stale GTC orders and records settlement outcomes for
    filled orders whose markets have finalized.
    Called each iteration of cmd_watch to close the GTC order lifecycle.
    """
    from utils import KALSHI_FEE_RATE as _fee

    gtc_cancel_hours = (config or {}).get("gtc_cancel_hours", 24)
    now_utc = datetime.now(UTC)

    # ── Pending orders: GTC age check + fill status ───────────────────────────
    pending = [
        o
        for o in execution_log.get_recent_orders(limit=200)
        if o.get("live") and o.get("status") == "pending" and o.get("response")
    ]
    for order in pending:
        try:
            response = (
                json.loads(order["response"])
                if isinstance(order["response"], str)
                else order["response"]
            )
            order_id = response.get("order_id") if response else None
            if not order_id:
                continue

            # GTC age check — cancel orders older than gtc_cancel_hours
            try:
                placed_at = datetime.fromisoformat(
                    order["placed_at"].replace("Z", "+00:00")
                )
                age_hours = (now_utc - placed_at).total_seconds() / 3600
                if age_hours >= gtc_cancel_hours:
                    client.cancel_order(order_id)
                    execution_log.log_order_result(
                        row_id=order["id"], status="cancelled"
                    )
                    continue
            except Exception as exc:
                print(f"[LIVE] GTC cancel failed for order {order.get('id')}: {exc}")

            result = client.get_order(order_id)
            api_status = result.get("status", "")
            if api_status in ("filled", "canceled", "expired"):
                execution_log.log_order_result(
                    row_id=order["id"],
                    status=api_status,
                    fill_quantity=result.get("fill_quantity"),
                )
        except Exception as exc:
            print(f"[LIVE] poll order {order.get('id')} failed: {exc}")

    # ── Filled+unsettled orders: settlement check ─────────────────────────────
    for order in execution_log.get_filled_unsettled_live_orders():
        try:
            market = client.get_market(order["ticker"])
            status = market.get("status", "")
            result = market.get("result", "")
            if status != "finalized" or not result:
                continue
            # 1-hour buffer — Kalshi may revise outcomes shortly after finalization
            close_time_str = market.get("close_time") or market.get(
                "expiration_time", ""
            )
            if close_time_str:
                try:
                    close_dt = datetime.fromisoformat(
                        close_time_str.replace("Z", "+00:00")
                    )
                    if (now_utc - close_dt).total_seconds() / 3600 < 1.0:
                        continue
                except (ValueError, TypeError):
                    pass
            outcome_yes = result == "yes"
            side = order["side"]
            price = order["price"]  # always YES-side decimal (0.0–1.0)
            qty = order.get("fill_quantity") or order["quantity"]
            if outcome_yes and side == "yes":
                pnl = qty * (1 - price) * (1 - _fee)
            elif not outcome_yes and side == "yes":
                pnl = -qty * price
            elif outcome_yes and side == "no":
                pnl = qty * price * (1 - _fee)
            else:  # not outcome_yes, side == "no"
                pnl = -qty * (1 - price)
            pnl = round(pnl, 4)
            execution_log.record_live_settlement(order["id"], outcome_yes, pnl)
            execution_log.add_live_loss(-pnl)  # negative pnl = loss
        except Exception as exc:
            print(f"[LIVE] settlement check failed for order {order.get('id')}: {exc}")
```

- [ ] **Step 4: Update the `_poll_pending_orders` call site in `main.py`**

Find the line (around ~2027):

```python
            if live:
                _poll_pending_orders(client)
```

Replace with:

```python
            if live:
                _poll_pending_orders(client, config=live_cfg)
```

- [ ] **Step 5: Run tests to verify they pass**

```
pytest tests/test_live_execution.py::TestPollPendingOrdersExtended -v
```

Expected: 3 passed

- [ ] **Step 6: Run full test suite**

```
pytest tests/test_live_execution.py tests/test_execution_log.py -v
```

Expected: all pass

- [ ] **Step 7: Commit**

```bash
git add main.py tests/test_live_execution.py
git commit -m "feat: extend _poll_pending_orders with GTC cancel and settlement tracking (#B #C)"
```

---

### Task 5: Live tax/audit export

**Files:**
- Modify: `execution_log.py`
- Modify: `main.py`
- Test: `tests/test_execution_log.py`

**Context:** `paper.export_tax_csv()` in `paper.py` exports paper trades from `paper_trades.json`. The parallel function exports settled live orders from `execution_log.db`. `cmd_export()` in `main.py` at line ~2706 already calls `paper.export_tax_csv()` — add a parallel call after it. Output goes to `data/exports/live_tax_{year}.csv`.

- [ ] **Step 1: Write a failing test in `tests/test_execution_log.py`**

Add to the `TestLiveSettlement` class:

```python
    def test_export_live_tax_csv_filters_by_year(self, tmp_path):
        import csv
        # Seed two orders settled in different years
        id1 = execution_log.log_order(
            ticker="KXHIGH-24JAN15-T75",
            side="yes",
            quantity=1,
            price=0.55,
            status="filled",
            live=True,
        )
        id2 = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=2,
            price=0.60,
            status="filled",
            live=True,
        )
        # Manually set settled_at to different years
        with execution_log._conn() as con:
            con.execute(
                "UPDATE orders SET settled_at = ?, outcome_yes = 1, pnl = 0.42 WHERE id = ?",
                ("2024-01-15T12:00:00+00:00", id1),
            )
            con.execute(
                "UPDATE orders SET settled_at = ?, outcome_yes = 0, pnl = -0.60 WHERE id = ?",
                ("2025-05-15T12:00:00+00:00", id2),
            )
        out_path = str(tmp_path / "live_tax_2025.csv")
        count = execution_log.export_live_tax_csv(out_path, tax_year=2025)
        assert count == 1
        with open(out_path, newline="") as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 1
        assert rows[0]["ticker"] == "KXHIGH-25MAY15-T75"
        assert rows[0]["outcome"] == "no"
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest tests/test_execution_log.py::TestLiveSettlement::test_export_live_tax_csv_filters_by_year -v
```

Expected: `AttributeError: module 'execution_log' has no attribute 'export_live_tax_csv'`

- [ ] **Step 3: Add `export_live_tax_csv()` to `execution_log.py`**

Add after `record_live_settlement()`:

```python
def export_live_tax_csv(path: str, tax_year: int | None = None) -> int:
    """Export settled live orders to CSV for tax reporting.

    Filters to live=1, settled_at IS NOT NULL, pnl IS NOT NULL.
    If tax_year is provided, filters to rows where settled_at starts with that year.

    CSV columns: date, ticker, side, quantity, entry_price, outcome, pnl, settled_at
    Returns count of rows written.
    """
    import csv

    init_log()
    with _conn() as con:
        if tax_year is not None:
            rows = con.execute(
                """
                SELECT placed_at, ticker, side, quantity, price,
                       outcome_yes, pnl, settled_at
                FROM orders
                WHERE live = 1 AND settled_at IS NOT NULL AND pnl IS NOT NULL
                  AND settled_at LIKE ?
                ORDER BY settled_at
                """,
                (f"{tax_year}%",),
            ).fetchall()
        else:
            rows = con.execute(
                """
                SELECT placed_at, ticker, side, quantity, price,
                       outcome_yes, pnl, settled_at
                FROM orders
                WHERE live = 1 AND settled_at IS NOT NULL AND pnl IS NOT NULL
                ORDER BY settled_at
                """,
            ).fetchall()

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            ["date", "ticker", "side", "quantity", "entry_price", "outcome", "pnl", "settled_at"]
        )
        for row in rows:
            writer.writerow([
                row["placed_at"][:10],
                row["ticker"],
                row["side"],
                row["quantity"],
                row["price"],
                "yes" if row["outcome_yes"] else "no",
                row["pnl"],
                row["settled_at"],
            ])
    return len(rows)
```

- [ ] **Step 4: Run test to verify it passes**

```
pytest tests/test_execution_log.py::TestLiveSettlement::test_export_live_tax_csv_filters_by_year -v
```

Expected: PASS

- [ ] **Step 5: Wire `export_live_tax_csv()` into `cmd_export()` in `main.py`**

Find `cmd_export()` (line ~2706). The function ends with the tax export block:

```python
    # Tax export
    tax_year = datetime.now(UTC).year
    tax_path = str(out_dir / f"paper_tax_{tax_year}.csv")
    n3 = export_tax_csv(tax_path, tax_year=tax_year)
    if n3:
        print(
            green(f"  Exported {n3} settled trades (tax year {tax_year}) → {tax_path}")
        )
        print(
            dim("  Note: This file is for informational purposes only, not tax advice.")
        )
    else:
        print(dim(f"  No settled trades for tax year {tax_year} to export."))
```

Replace with:

```python
    # Tax export — paper trades
    tax_year = datetime.now(UTC).year
    tax_path = str(out_dir / f"paper_tax_{tax_year}.csv")
    n3 = export_tax_csv(tax_path, tax_year=tax_year)
    if n3:
        print(
            green(f"  Exported {n3} settled paper trades (tax year {tax_year}) → {tax_path}")
        )
        print(
            dim("  Note: This file is for informational purposes only, not tax advice.")
        )
    else:
        print(dim(f"  No settled paper trades for tax year {tax_year} to export."))

    # Tax export — live orders
    from execution_log import export_live_tax_csv
    live_tax_path = str(out_dir / f"live_tax_{tax_year}.csv")
    n4 = export_live_tax_csv(live_tax_path, tax_year=tax_year)
    if n4:
        print(green(f"  Exported {n4} settled live orders (tax year {tax_year}) → {live_tax_path}"))
    else:
        print(dim(f"  No settled live orders for tax year {tax_year} to export."))
```

- [ ] **Step 6: Run all tests**

```
pytest tests/test_execution_log.py -v
```

Expected: all pass

- [ ] **Step 7: Commit**

```bash
git add execution_log.py main.py tests/test_execution_log.py
git commit -m "feat: add export_live_tax_csv and wire into cmd_export (#D)"
```

---

### Task 6: Live P&L dashboard

**Files:**
- Modify: `execution_log.py`
- Modify: `web_app.py`
- Modify: `templates/dashboard.html`
- Modify: `static/dashboard.js`
- Test: `tests/test_execution_log.py`

**Context:** The dashboard at `templates/dashboard.html` has a `<div class="stats">` block with four stat cards populated by SSE and `/api/graduation`. Add a fifth card (hidden by default) that shows live P&L. The card reveals itself only when at least one live order exists (`settled_count > 0` or `open_count > 0`). `dashboard.js` has `loadGraduation()` and `loadBalanceChart('')` called at the bottom — add `loadLivePnl()` alongside them.

The `/api/graduation` route in `web_app.py` (line ~306) is the model for the new endpoint.

- [ ] **Step 1: Write a failing test in `tests/test_execution_log.py`**

Add to the `TestLiveSettlement` class:

```python
    def test_get_live_pnl_summary_correct(self):
        from datetime import UTC, datetime
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        # Settled today: +$0.50
        id1 = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=1,
            price=0.55,
            status="filled",
            live=True,
        )
        # Settled yesterday: -$0.30 (should not appear in today_pnl)
        id2 = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T80",
            side="yes",
            quantity=1,
            price=0.60,
            status="filled",
            live=True,
        )
        # One pending
        execution_log.log_order(
            ticker="KXHIGH-25MAY15-T85",
            side="yes",
            quantity=1,
            price=0.45,
            status="pending",
            live=True,
        )
        with execution_log._conn() as con:
            con.execute(
                "UPDATE orders SET settled_at = ?, outcome_yes = 1, pnl = 0.50 WHERE id = ?",
                (f"{today}T10:00:00+00:00", id1),
            )
            con.execute(
                "UPDATE orders SET settled_at = ?, outcome_yes = 0, pnl = -0.30 WHERE id = ?",
                ("2024-01-01T10:00:00+00:00", id2),
            )
        summary = execution_log.get_live_pnl_summary()
        assert summary["today_pnl"] == pytest.approx(0.50)
        assert summary["total_pnl"] == pytest.approx(0.20)  # 0.50 - 0.30
        assert summary["open_count"] == 1
        assert summary["settled_count"] == 2
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest tests/test_execution_log.py::TestLiveSettlement::test_get_live_pnl_summary_correct -v
```

Expected: `AttributeError: module 'execution_log' has no attribute 'get_live_pnl_summary'`

- [ ] **Step 3: Add `get_live_pnl_summary()` to `execution_log.py`**

Add after `export_live_tax_csv()`:

```python
def get_live_pnl_summary() -> dict:
    """Return live order P&L summary for the dashboard.

    Returns:
        today_pnl:     sum of pnl for live orders settled today (UTC)
        total_pnl:     sum of all settled live order pnl
        open_count:    count of live orders with status='pending'
        settled_count: count of live orders with settled_at IS NOT NULL
    """
    init_log()
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    with _conn() as con:
        today_row = con.execute(
            """
            SELECT COALESCE(SUM(pnl), 0.0) AS today_pnl
            FROM orders
            WHERE live = 1 AND settled_at LIKE ?
            """,
            (f"{today}%",),
        ).fetchone()
        totals_row = con.execute(
            """
            SELECT COALESCE(SUM(pnl), 0.0) AS total_pnl,
                   COUNT(*) AS settled_count
            FROM orders
            WHERE live = 1 AND settled_at IS NOT NULL AND pnl IS NOT NULL
            """,
        ).fetchone()
        open_row = con.execute(
            """
            SELECT COUNT(*) AS open_count
            FROM orders
            WHERE live = 1 AND status = 'pending'
            """,
        ).fetchone()
    return {
        "today_pnl": round(today_row["today_pnl"] or 0.0, 4),
        "total_pnl": round(totals_row["total_pnl"] or 0.0, 4),
        "open_count": open_row["open_count"] or 0,
        "settled_count": totals_row["settled_count"] or 0,
    }
```

- [ ] **Step 4: Run test to verify it passes**

```
pytest tests/test_execution_log.py::TestLiveSettlement::test_get_live_pnl_summary_correct -v
```

Expected: PASS

- [ ] **Step 5: Add `/api/live-pnl` endpoint to `web_app.py`**

Find the `api_graduation` route (line ~306):

```python
    @app.route("/api/graduation")
    def api_graduation():
```

Insert the new route immediately before it:

```python
    @app.route("/api/live-pnl")
    def api_live_pnl():
        try:
            from execution_log import get_live_pnl_summary
            return jsonify(get_live_pnl_summary())
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/api/graduation")
    def api_graduation():
```

- [ ] **Step 6: Add Live P&L stat card to `templates/dashboard.html`**

Find the stats block:

```html
<div class="stats">
  <div class="stat-card">
    <div class="stat-label">Paper Balance</div>
    <div class="stat-value pos" id="stat-balance">—</div>
  </div>
  <div class="stat-card">
    <div class="stat-label">Open Positions</div>
    <div class="stat-value" id="stat-open">—</div>
  </div>
  <div class="stat-card">
    <div class="stat-label">Win Rate</div>
    <div class="stat-value" id="stat-winrate">—</div>
  </div>
  <div class="stat-card">
    <div class="stat-label">Brier Score</div>
    <div class="stat-value" id="stat-brier">—</div>
  </div>
</div>
```

Replace with (adds the live P&L card, hidden until live orders exist):

```html
<div class="stats">
  <div class="stat-card">
    <div class="stat-label">Paper Balance</div>
    <div class="stat-value pos" id="stat-balance">—</div>
  </div>
  <div class="stat-card">
    <div class="stat-label">Open Positions</div>
    <div class="stat-value" id="stat-open">—</div>
  </div>
  <div class="stat-card">
    <div class="stat-label">Win Rate</div>
    <div class="stat-value" id="stat-winrate">—</div>
  </div>
  <div class="stat-card">
    <div class="stat-label">Brier Score</div>
    <div class="stat-value" id="stat-brier">—</div>
  </div>
  <div class="stat-card" id="live-pnl-card" style="display:none">
    <div class="stat-label">Live P&amp;L (today)</div>
    <div class="stat-value" id="stat-live-pnl">—</div>
    <div style="font-size:0.78em;color:var(--text-muted);margin-top:4px" id="stat-live-open"></div>
  </div>
</div>
```

- [ ] **Step 7: Add `loadLivePnl()` to `static/dashboard.js`**

Find the Init section at the bottom of `dashboard.js`:

```javascript
  // Init
  loadGraduation();
  loadBalanceChart('');
```

Replace with:

```javascript
  // Fetch and render Live P&L card
  function loadLivePnl() {
    fetch('/api/live-pnl').then(function (r) { return r.json(); }).then(function (d) {
      var card = document.getElementById('live-pnl-card');
      var el = document.getElementById('stat-live-pnl');
      var openEl = document.getElementById('stat-live-open');
      if (!card || !el) return;
      if (d.settled_count === 0 && d.open_count === 0) return;
      card.style.display = '';
      var pnl = d.today_pnl || 0;
      el.textContent = (pnl >= 0 ? '+' : '') + '$' + pnl.toFixed(2);
      el.className = 'stat-value ' + (pnl > 0 ? 'pos' : pnl < 0 ? 'neg' : '');
      if (openEl) openEl.textContent = d.open_count > 0 ? d.open_count + ' open' : '';
    }).catch(function (err) { console.error('live-pnl fetch failed:', err); });
  }

  // Init
  loadGraduation();
  loadBalanceChart('');
  loadLivePnl();
```

- [ ] **Step 8: Run full test suite**

```
pytest tests/ -v --ignore=tests/test_paper.py -x
```

Expected: all pass (test_paper.py has 13 pre-existing failures unrelated to this work)

- [ ] **Step 9: Commit**

```bash
git add execution_log.py web_app.py templates/dashboard.html static/dashboard.js tests/test_execution_log.py
git commit -m "feat: add live P&L dashboard card and /api/live-pnl endpoint (#E)"
```
