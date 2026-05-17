# Live Trading Runbook

> **Purpose**: Step-by-step guide for enabling real-money trading, monitoring the first week, and rolling back safely if anything goes wrong.

---

## Part 1 — Pre-Flight Checklist

Complete every item before setting `LIVE_TRADING_ENABLED=true`. Do **not** proceed if any item is blocked.

### 1.1 Paper-Mode Graduation

| Check | Command | Pass condition |
|-------|---------|---------------|
| Minimum settled trades | `python -c "import paper; print(paper.graduation_check())"` | `settled >= 30` |
| Brier score valid | same output | `brier` key present and `brier <= 0.20` |
| Win rate | same output | `win_rate >= 0.52` |
| No active drawdown halt | `python -c "import paper; print(paper.is_paused_drawdown())"` | `False` |
| No active daily-loss halt | `python -c "import paper; print(paper.is_daily_loss_halted())"` | `False` |
| No accuracy halt | `python -c "import paper; print(paper.is_accuracy_halted())"` | `False` |

If `graduation_check()` returns `None`, paper mode has not graduated. **Stop here.**

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
# Confirm the prod key file exists and is non-empty
ls -la kalshi_prod.key   # or whatever KALSHI_KEY_PATH points to
python -c "
import kalshi_api_client as k
c = k.KalshiClient()
print('Balance:', c.get_balance())
"
```

- Balance should be > 0 and match your Kalshi account.
- If an `AuthenticationError` is raised, the key is wrong — **stop here**.

### 1.4 Risk Limits (`.env`)

Confirm conservative values are set for the first live week:

```
DAILY_LOSS_LIMIT=25          # dollars — recommend ≤ $25 to start
MAX_OPEN_POSITIONS=5         # total contracts — recommend ≤ 5
MAX_TRADE_DOLLARS=10         # per-order cap — recommend ≤ $10
MAX_POSITION_DOLLARS=20      # per-ticker cap
```

Do **not** raise these during the first week.

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
# Run one cycle in dry-run mode to confirm no import errors, DB connectivity, API reachability
LIVE_TRADING_ENABLED=false python main.py --once 2>&1 | tail -30
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

# 3. Start the bot (first cycle under observation)
python main.py --once
```

Watch the first cycle output carefully. Confirm:
- "Live trading gate: PASS" appears in logs
- An order is attempted (or "no edge found" — both are acceptable)
- No `RuntimeError: gate blocked` exception

---

## Part 3 — First-Week Monitoring

### Daily checks (takes ~5 minutes)

```bash
# P&L summary
python -c "import paper; print(paper.graduation_check())"

# Open positions
python -c "
import json, pathlib
p = pathlib.Path('data/positions.json')
if p.exists():
    pos = json.loads(p.read_text())
    print(f'{len(pos)} open positions')
    for t, v in pos.items(): print(f'  {t}: {v}')
"

# Today's orders
python -c "
import order_executor
log = order_executor.execution_log
print('Orders today:', len(log.today_orders()))
"
```

### Alert thresholds — take action if:

| Metric | Action threshold | Action |
|--------|-----------------|--------|
| Daily loss | ≥ 80% of `DAILY_LOSS_LIMIT` | Review positions; consider manual halt |
| Consecutive losses | ≥ 5 in a row | Review model accuracy; consider pause |
| Open positions | ≥ `MAX_OPEN_POSITIONS` | Wait for settlements; do not raise limit |
| Any circuit breaker opens | Any source | Check data source; review any live orders touched by bad data |
| Brier score (after 10+ trades) | > 0.25 | Pause and investigate |

### Weekly review

- Compare live Brier score to paper Brier score — they should be within ±0.05.
- Check Kelly fractions being assigned: confirm no single order is > 25% of liquid balance.
- Review the settlement log for any unexpected outcomes on between-bucket markets.

---

## Part 4 — Rollback Procedure

### Immediate halt (emergency)

```bash
# Option A: kill switch (fastest — no restart needed)
touch data/kill_switch.flag

# Option B: remove the env var
# In .env: comment out or delete LIVE_TRADING_ENABLED=true
# Then restart the bot process
```

`kill_switch.flag` is checked at the start of every cycle. The bot will log `KILL SWITCH ACTIVE` and exit without placing orders.

### Canceling open orders

```bash
python -c "
import kalshi_api_client as k
c = k.KalshiClient()
orders = c.get_orders(status='resting')
for o in orders:
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

The paper trading loop runs automatically when `KALSHI_ENV != prod` or `LIVE_TRADING_ENABLED != true`.

---

## Appendix — Gate Logic Reference

The `LiveTradingGate.check()` method (in `trading_gates.py`) blocks live orders if **any** of the following are true:

1. `KALSHI_ENV != "prod"`
2. `LIVE_TRADING_ENABLED != "true"` (env var)
3. `paper.graduation_check()` returns `None`
4. `paper.is_paused_drawdown()` returns `True`
5. `paper.is_daily_loss_halted()` returns `True`
6. `paper.is_accuracy_halted()` returns `True`
7. `paper.is_streak_paused()` returns `True`

All seven gates must pass simultaneously. There is no override short of modifying source code.
