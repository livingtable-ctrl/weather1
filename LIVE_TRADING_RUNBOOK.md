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
from dotenv import load_dotenv
load_dotenv()
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

**`status == 'unresolved'`**: an `unknown` ENTRY order that stayed
unresolvable for longer than `UNRESOLVED_ORDER_AGE_MINUTES` (default 1440 =
24h). The bot fires a system alert ("Live order stuck unresolved") once at
the moment of parking and then **stops re-checking the row** — this status
is terminal and only an operator clears it. It is not the same as `failed`:
`failed` means the bot positively confirmed the order never landed, while
`unresolved` means it never found out. So a parked row deliberately keeps
behaving like an open one — it still counts toward open positions and daily
live spend, and still blocks an automated re-placement for that ticker+side
— precisely because it might be a real resting order on the exchange.

A row is only parked when the reconciliation lookup itself actually
succeeded. If Kalshi's order-history endpoints are failing, rows stay
`unknown` and keep being retried however old they get.

To clear one: find its stored `client_order_id` (it is in the row's
`response` JSON, and the alert message includes it), reconcile that against
Kalshi's own order history by hand, then update the row's status to whatever
the exchange actually shows (`filled` / `pending` / `failed`). A row usually
lands here for one of two reasons — the order aged out past what Kalshi's
order-history endpoints still return, or the row never had a usable
`client_order_id` stored at all.

**Unresolvable EXIT orders are never parked.** An order row with
`closes_position_id` set is a protective SELL, and the recovery pass is what
eventually settles the POSITION it closed. Parking it would leave that
position at `live=1 / status='filled' / settled_at=NULL` — which is exactly
what the bot reads as "still open" — so the automated exit scanner would
keep placing fresh real SELL orders for contracts the account no longer
holds, every cycle, forever. Instead the bot alerts ("Live exit order stuck
unresolved", naming both the exit row and the position it was closing) and
keeps retrying. Treat that alert as urgent: reconcile the exit against
Kalshi by hand and settle the position row.

### Alert thresholds — take action if:

| Metric | Action threshold | Action |
|--------|-----------------|--------|
| Daily loss | ≥ 80% of `MAX_DAILY_LOSS_PCT` × current balance | Review positions; consider manual halt |
| Consecutive losses | ≥ 5 in a row | Review model accuracy; consider pause |
| Projected VaR | Repeatedly near `MAX_VAR_DOLLARS` | Portfolio risk is concentrating — review correlated exposure |
| Any circuit breaker opens | Any source | Check data source; review any live orders touched by bad data |
| Brier score (after 10+ trades) | > 0.25 | Pause and investigate |
| `status == 'unknown'` order row | Persists past a few cron/watch cycles | Manually check that ticker against Kalshi's own order history before assuming it's safe to ignore |
| `status == 'unresolved'` order row | Any (the bot alerts once when it parks the row) | Reconcile the row's stored `client_order_id` against Kalshi by hand and set its real status — the bot will not re-check it again |
| "Live exit order stuck unresolved" alert | Any | Urgent. A protective SELL could not be reconciled, so the position it closed is still tracked as open and the exit scanner will keep firing real SELLs at it. Reconcile the exit against Kalshi and settle the position row by hand |
| "Live exit blocked" alert | Any | A protective exit could not be placed because TRADING_PAUSED or the kill switch is engaged. The position is still open and unprotected. Note `py main.py sell` runs the FULL gate and is blocked by the same condition, so clearing the block is what re-enables any in-bot close of a LIVE position (a PAPER position can be closed during a halt — see the batch-63 note under "Immediate halt") — Kalshi's own web UI is the only path that bypasses it |

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

**Batch-41 note, SUPERSEDED by batch-63 — read the batch-63 note below.** When the dashboard's `/api/close-position` route gained the same kill-switch/`TRADING_PAUSED` gates its order-placement siblings already had (audit-M-9), engaging either gate also blocked closing a position from the dashboard, not just placing new ones. `cron.py` (the automated exit path — settlement-lag closes, model-reversal exits) also aborts its whole run under either gate. At the time this was written that appeared to leave no operator-facing way to close an open position during a halt; batch-63 found that was not quite true (the interactive paper menu's "Exit signals" close had never checked either gate) and closed the gap properly.

**Batch-63 note — how to close a position during a halt.** There IS now a deliberate operator path, and it is the CLI:

```bash
python main.py close <trade_id> [exit_price]      # alias for `paper close`
```

- **PAPER positions only.** Live positions still exit through the bot's own protective path (`order_executor._exit_live_position`), which runs `trading_gates.pre_live_exit_check` and is still blocked by the kill switch and `TRADING_PAUSED` — see the "Live exit blocked" row in the alert table above.
- **It deliberately bypasses BOTH gates.** Closing reduces exposure; freezing exits under a halt makes the account strictly riskier at the moment you reached for the halt. Every close through it is logged at WARNING with the bypassed gates named.
- Omit `exit_price` to close at the live realizable quote; supply one when there is no quote. A supplied price is cross-checked against the live quote (±0.15) when one is reachable.
- **`/api/close-position` still returns 503 under either gate, on purpose.** A dashboard button is misclickable in a way a typed trade id is not. Do not "fix" the route to match the CLI.
- It still needs a readable `.env` and Kalshi key to start (the standard preflight), even though it never touches the exchange. If the key itself is what broke, supply `exit_price` explicitly — but the preflight runs first, so fix the key or use the dashboard once the halt is cleared.

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

### Rolling back code without rolling back calibration

`git restore .` and `git checkout -- .` are safe for calibration state again,
and this was not always true. Until batch-79, five learned-calibration files
were force-tracked inside the gitignored `data/` directory, so either command
silently reverted them to whatever was last committed — no warning, no error,
and nothing downstream noticing the bot was now running on a stale snapshot.
Nothing under `data/` is tracked any more, so no git command can reach it.
Fresh-clone copies live in `seeds/` and are applied by
`paths.materialize_missing_seeds()` only when `data/` does not already have
the file, so they can never overwrite learned values.

**One-time step when the untracking commit first lands in a clone.** Git
removes the five files from the working tree as part of that checkout,
because they were tracked in the parent commit. Two cases:

- A file identical to its committed version is removed and then recreated
  byte-identically from `seeds/` by the next process that imports `paths.py`.
  Nothing is lost and no action is needed.
- A file that has diverged (i.e. real learned calibration) makes git **refuse
  the merge outright** — `error: Your local changes to the following files
  would be overwritten by merge`. It fails loudly rather than deleting
  anything, so nothing is at risk until you act.

Back up **the whole directory** first, and do not delete anything until you
have confirmed the backup exists. Git's abort message lists *every* diverged
file, which may be more than one — copying the directory means you do not
have to get that list right:

```cmd
xcopy /E /I /Y data "%TEMP%\data-backup-before-untrack"
dir "%TEMP%\data-backup-before-untrack"
```

**Confirm that listing shows your files before continuing.** (Run this in
`cmd`, not PowerShell — PowerShell does not expand `%TEMP%`, so step 1 would
fail while a later step still ran.) Then let git discard its copies, merge,
and put the learned values back:

```cmd
git checkout -- data
git merge --ff-only <branch>
xcopy /E /I /Y "%TEMP%\data-backup-before-untrack" data
```

Verifying afterwards: `git ls-files data/` must print nothing. Do **not**
treat "all five files are present" as confirmation — it is not. If you skip
the copy-back, `paths.materialize_missing_seeds()` recreates all five from
`seeds/` on the next run and both of those checks still pass, while the
learned values are gone. That is exactly the silent reversion this change
exists to prevent, so check the **contents**:

```cmd
fc data\seasonal_weights.json "%TEMP%\data-backup-before-untrack\seasonal_weights.json"
```

A seeded `seasonal_weights.json` has every season at `0.3333…` with
`"_uncalibrated": true`; a learned one does not. Note the files only reappear
once some process imports `paths.py` — run `python -c "import paths"` from the
clone if `data/` looks empty immediately after the merge.

---

## Part 5 — Reboot / Power-Loss Recovery

**Current operating mode (as of 2026-08): fully manual.** The operator runs
`python main.py cron` (or `watch --auto --live`) by hand — nothing restarts
the bot automatically after a reboot, crash, or power loss. Verify this is
still true on this machine before relying on it:
```cmd
schtasks /Query /FO LIST /V | findstr Kalshi
```
`main.py`'s `cmd_schedule_cycles` command makes registering a real cron
Scheduled Task a one-command operation, so don't assume none exists just
because this section describes the manual default — confirm on the actual
machine. This section documents the manual recovery procedure for the
fully-manual case; actually registering an ONSTART-triggered task (and
having `cmd_cron` assert that task still exists) is deliberately deferred
to when the VM move picks a real scheduling mechanism, so both can be
designed against that mechanism once instead of twice.

### After any reboot, crash, or power loss, before resuming

1. **Check for a stale `data/.cron.lock`.** A clean shutdown always deletes
   it (`_release_cron_lock`); a crash or forced reboot can leave it behind.
   `_acquire_cron_lock` verifies the recorded PID's own `create_time` (not
   just `pid_exists()`) before trusting an existing lock, so the next `cron`
   invocation self-heals automatically in both ordinary crash cases: the
   PID is confirmed dead, or the PID was reassigned to an unrelated process
   (a `create_time` mismatch proves the reuse) — no operator intervention
   needed either way. The only case that can't self-heal on the spot is a
   live PID whose `create_time` can't be positively confirmed (e.g. Windows
   `AccessDenied` querying a protected process that reused the PID) — even
   that case is capped by a 24h backstop (`_STUCK_RUNNING_BACKSTOP_SECS`),
   not held indefinitely. To confirm/clear it manually anyway:
   ```cmd
   type data\.cron.lock   # inspect; if present, cron.py will validate it on next run
   del data\.cron.lock    # only if you want to force-clear it before running cron
   ```
2. **Let `_recover_pending_orders` run.** It's already invoked automatically
   near the start of every `cron` cycle (`cron.py`, `_cmd_cron_body`, gated
   on `if client is not None:`) — no separate step needed, just don't skip
   straight to `watch --auto --live` without having run a `cron` cycle (or
   an explicit recovery step) since the crash.
3. **Manually reconcile open positions before resuming live trading.**
   Compare `python main.py positions` (or the dashboard) against Kalshi's
   own portfolio view for the account. A crash mid-order can leave an
   `unknown`-status row in the execution log (see the "Weekly review" table
   above) — resolve it against Kalshi's order history before trusting it.
4. **Restart the bot process manually.** There is no automated restart —
   re-run whichever of `cron`, `watch --auto --live`, or the dashboard
   backend (`start.bat`) was running before the interruption.

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
