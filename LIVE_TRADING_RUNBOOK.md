# Live Trading Runbook

> **Purpose**: Step-by-step guide for enabling real-money trading, monitoring the first week, and rolling back safely if anything goes wrong.

---

## Part 1 — Pre-Flight Checklist

Complete every item before setting `LIVE_TRADING_ENABLED=true`. Do **not** proceed if any item is blocked.

### 1.1 Paper-Mode Graduation

| Check | Command | Pass condition |
|-------|---------|---------------|
| Graduation gate | `python -c "import paper; print(paper.graduation_check())"` | Returns a summary dict (not `None`) |
| No active drawdown halt | `python -c "import paper; print(paper.is_paused_drawdown())"` | `False` |
| No active loss-streak halt | `python -c "import paper; print(paper.is_streak_paused())"` | `False` |
| No active daily-loss halt | `python -c "import paper; print(paper.is_daily_loss_halted())"` | `False` |
| No accuracy halt | `python -c "import paper; print(paper.is_accuracy_halted())"` | `False` |

`graduation_check()` requires all three of: `settled >= 30`, `total_pnl >= $50`, `brier(last 50) <= 0.23`. Returns `None` if any criterion isn't met — **stop here** if so. (Win rate is intentionally not a gate — see `paper.graduation_check()`'s own docstring: a bot buying NO at $0.03 can have a 97% win rate and still lose money on the rare adverse move; P&L + calibration is the real signal.)

### 1.2 Environment Variables

```bash
# Verify both variables are present in the production .env (or shell)
grep KALSHI_ENV      .env   # must be: KALSHI_ENV=prod
grep LIVE_TRADING    .env   # must be: LIVE_TRADING_ENABLED=true
```

- `KALSHI_ENV=prod` — connects to the real Kalshi exchange (not demo)
- `LIVE_TRADING_ENABLED=true` — secondary interlock; gate checks this explicitly

Both **must** be present. The gate blocks if either is missing or wrong.

### 1.3 API Credentials

```bash
# Confirm the prod private key file exists and is non-empty
grep KALSHI_PRIVATE_KEY_PATH .env   # default: ./kalshi_private_key.pem
ls -la kalshi_private_key.pem       # or whatever KALSHI_PRIVATE_KEY_PATH points to

python -c "
from dotenv import load_dotenv
load_dotenv()
import main
c = main.build_client()
print('Balance:', c.get_balance())
"
```

- Balance should be > 0 and match your Kalshi account.
- If an auth error is raised, the key is wrong — **stop here**.

### 1.4 Risk Limits

Confirm conservative values are set for the first live week. Unlike a flat-dollar model, this bot's real risk controls scale with current balance:

| Env var | Default | What it controls |
|---------|---------|-------------------|
| `MAX_DAILY_LOSS_PCT` | 0.03 (3% of current balance) | Drives `is_daily_loss_halted()` |
| `MAX_VAR_DOLLARS` | 200.0 (flat dollars) | Pre-trade VaR gate — skips a candidate trade if it would push 5th-percentile portfolio loss past this |
| `MAX_SINGLE_TICKER_EXPOSURE` | 0.10 (fraction of balance) | Per-ticker exposure cap |
| `MAX_CORRELATED_EXPOSURE` | 0.35 (hardcoded, not env-configurable) | Combined cap across a correlated city group |
| `KELLY_CAP` | 0.25 (fraction of balance) | Max Kelly fraction per position |

There is **no hard cap on the number of open positions** — risk is controlled via the VaR/Kelly/exposure limits above, not a position count. For the first live week, consider tightening `MAX_DAILY_LOSS_PCT` and `MAX_VAR_DOLLARS` below their defaults rather than raising them.

Do **not** loosen these during the first week.

### 1.5 Circuit Breaker State

```bash
python -c "
import json, pathlib
p = pathlib.Path('data/.cb_state.json')
if p.exists():
    state = json.loads(p.read_text())
    for name, cb in state.items():
        if cb.get('opened_at'):
            print(f'OPEN: {name} — opened at {cb[\"opened_at\"]}')
else:
    print('No CB state file (all closed)')
"
```

Any OPEN circuit means a data source is down. Investigate and resolve before enabling live trading.

### 1.6 Test Suite (Smoke)

```bash
cd "path/to/project"
python -m pytest tests/test_trading_gates.py tests/test_live_execution.py tests/test_kelly_property.py -v
```

All tests must pass. A failure in `test_trading_gates.py` means the safety gate itself is broken — **do not proceed**.

### 1.7 Dry Run

```bash
# Run one real cron cycle to confirm no import errors, DB connectivity, API reachability.
# cron never OPENS a new live position (buy) regardless of LIVE_TRADING_ENABLED
# — only `watch --auto --live`, `buy`/`sell`, and `analyze`'s quick-buy prompt
# do that. cron CAN still place a real live SELL to protect an already-open
# position (stop-loss/breakeven/model exit) if one exists from a prior
# `watch --live` session — this dry run is only "safe by design" when no live
# position is currently open; check first if unsure.
python main.py cron 2>&1 | tail -30
```

Confirm no `ERROR` or `CRITICAL` log lines.

---

## Part 2 — Enabling Live Trading

Once all pre-flight checks pass:

```bash
# 1. Set the flag (add to .env or export in shell)
echo "LIVE_TRADING_ENABLED=true" >> .env

# 2. Verify the gate passes programmatically
python -c "
from trading_gates import LiveTradingGate
allowed, reason = LiveTradingGate().check()
print('Gate:', 'PASS' if allowed else 'BLOCKED', '—', reason)
"
# Expected: Gate: PASS — ok

# 3. Start the live-order path
python main.py watch --auto --live
```

`python main.py cron` never opens a new live position (buys) — `watch --auto --live` (the automated loop), `buy`/`sell` (manual `cmd_order`), and `analyze`'s interactive quick-buy prompt are the only paths that open new live exposure. Watch the first cycle's output carefully. If the gate blocks, the bot logs `Live trading gate blocked: <reason>` (in red) and raises `RuntimeError` rather than placing anything — confirm you see neither an unexpected block nor a silent placement with no log trace.

Note: `cron` (and `loop`, which dispatches to it) can still place a real live SELL order to protect an already-open position (stop-loss/breakeven/model exit) even though it never originates new live exposure — see its `_check_live_position_exits`/`_check_live_model_exits` calls. `watch --live` alone (without `--auto`) can do the same. "Never places live orders" understates this; the accurate claim is "never opens a new one."

---

## Part 3 — First-Week Monitoring

### Daily checks (takes ~5 minutes)

```bash
# P&L / graduation summary
python -c "import paper; print(paper.graduation_check())"

# Open positions — real broker positions, not the paper ledger
python -c "
from dotenv import load_dotenv
load_dotenv()
import main
c = main.build_client()
positions = c.get_positions()
print(f'{len(positions)} open position(s)')
for p in positions: print(' ', p)
"

# Recent real (non-paper) orders
python -c "
import execution_log
orders = [o for o in execution_log.get_recent_orders(limit=50) if o.get('live')]
print(f'{len(orders)} live order(s) in the last 50 log entries')
for o in orders: print(' ', o['ticker'], o['side'], o['status'], o['placed_at'])
"
```

**`status == 'unknown'`**: the create-order call failed AND the bot's own
follow-up check (querying Kalshi to see if the order landed anyway) also
couldn't get a definite answer -- so whether this order is real or not is
genuinely unresolved right now. It's not stuck: `_recover_pending_orders`
re-checks every 'unknown' row automatically at cron/watch startup and every
cycle, and will resolve it to `filled`/`pending`/`failed` once the API is
reachable again. While unresolved, the same ticker+side is blocked from a
new automated retry (by design, to avoid a duplicate real order). If a row
stays `unknown` for more than a few cycles, check the order manually against
Kalshi's own order history (`c.get_open_orders()` / the Kalshi web UI) for
the ticker in question before assuming it's safe to ignore.

### Alert thresholds — take action if:

| Metric | Action threshold | Action |
|--------|-----------------|--------|
| Daily loss | ≥ 80% of `MAX_DAILY_LOSS_PCT` × current balance | Review positions; consider manual halt |
| Consecutive losses | ≥ 5 in a row | Review model accuracy; consider pause |
| Projected VaR | Repeatedly near `MAX_VAR_DOLLARS` | Portfolio risk is concentrating — review correlated exposure |
| Any circuit breaker opens | Any source | Check data source; review any live orders touched by bad data |
| Brier score (after 10+ trades) | > 0.25 | Pause and investigate |
| `status == 'unknown'` order row | Persists past a few cron/watch cycles | Manually check that ticker against Kalshi's own order history before assuming it's safe to ignore |

### Weekly review

- Compare live Brier score to paper Brier score — they should be within ±0.05.
- Check Kelly fractions being assigned: confirm no single order is > 25% of liquid balance (`KELLY_CAP`).
- Review the settlement log for any unexpected outcomes on between-bucket markets.

---

## Part 4 — Rollback Procedure

### Immediate halt (emergency)

```bash
# Option A: kill switch (fastest — no restart needed)
python main.py kill

# Option B: remove the env var
# In .env: comment out or delete LIVE_TRADING_ENABLED=true
# Then restart the bot process
```

`python main.py kill` writes `data/.kill_switch`, which is checked at the start of every cycle (`cron.py`, `order_executor.py`). The bot will log `KILL SWITCH ACTIVE` and exit without placing orders. Re-enable with `python main.py resume` (this also clears black-swan halt state, which manually deleting the file would not).

### Canceling open orders

```bash
python -c "
from dotenv import load_dotenv
load_dotenv()
import main
c = main.build_client()
for o in c.get_open_orders():
    print(f'Canceling {o[\"order_id\"]} — {o[\"ticker\"]}')
    c.cancel_order(o['order_id'])
print('Done')
"
```

### Resetting circuit breakers

```bash
# Remove the persisted state so all circuits start closed on next run
rm data/.cb_state.json
```

### Returning to paper mode

```bash
# Remove LIVE_TRADING_ENABLED from .env
sed -i '/LIVE_TRADING_ENABLED/d' .env
# Or set KALSHI_ENV=demo
```

`LiveTradingGate.check()` blocks the live-order path whenever `KALSHI_ENV != "prod"` or `LIVE_TRADING_ENABLED != "true"` — with either unset, `watch --auto --live` falls back to paper trades.

---

## Appendix — Gate Logic Reference

The `LiveTradingGate.check()` method (in `trading_gates.py`) blocks live orders if **any** of the following are true:

1. `utils.is_trading_paused()` returns `True` (`TRADING_PAUSED` env var set)
2. The kill switch file (`data/.kill_switch`) exists
3. The prod check: when a client is passed (every real live-order call site), its own `base_url` isn't pointed at prod; only when no client is passed (a fallback for callers/tests not yet updated) does this fall back to a plain `KALSHI_ENV != "prod"` read instead
4. `LIVE_TRADING_ENABLED != "true"` (env var)
5. `paper.is_paused_drawdown()` returns `True`
6. `paper.is_streak_paused()` returns `True`
7. `paper.is_daily_loss_halted()` returns `True`
8. `paper.is_accuracy_halted()` returns `True`
9. `paper.graduation_check()` returns `None`

All nine gates must pass simultaneously, roughly cheapest-first though not exactly — `trading_gates.py` itself notes gates 5-6 now also do an execution_log table scan, ahead of some of the plain file/env reads above them; the DB/Brier check (gate 9) still runs last regardless. Most gates require either changing the underlying condition (settling more trades, waiting out a halt) or modifying source code; a couple have their own dedicated operator override — `python main.py resume` clears gate 2 (the kill switch), and `python main.py admin accuracy-override` can temporarily lift gate 8 (the accuracy halt). There is no single override that lifts the whole gate chain at once.
