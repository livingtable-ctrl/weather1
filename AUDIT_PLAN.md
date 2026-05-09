# Kalshi Bot — Production Readiness Remediation Plan

**Generated:** 2026-05-07 · **Updated:** 2026-05-07 (5-agent deep pass)  
**Source:** Full 8-agent system audit + 5-agent deep pass (Pass Aâ€“E, 79 additional findings)  
**System Status:** Paper trading / observe-only (ensemble retired, Brier 0.2641 > 0.25 threshold)  
**Verdict:** Not ready for live trading. 16 P0 blockers must be resolved first.

---

## Table of Contents

1. [Current System State](#current-system-state)
2. [Phase 0 — Pre-Live Blockers](#phase-0--pre-live-blockers)
3. [Phase 1 — Paper Safety Hardening](#phase-1--paper-safety-hardening)
4. [Phase 2 — Correctness & Observability](#phase-2--correctness--observability)
5. [Phase 3 — Architecture Cleanup](#phase-3--architecture-cleanup)
6. [Phase 4 — Low Priority](#phase-4--low-priority)
7. [Quick Wins](#quick-wins)
8. [Testing Strategy](#testing-strategy)
9. [Graduation Readiness Criteria](#graduation-readiness-criteria)
10. [Cross-Module Interaction Chains](#cross-module-interaction-chains)

---

## Current System State

| Metric | Value | Notes |
|--------|-------|-------|
| Paper balance | ~$3,158 (nominal) | $41.79 inflated by P&L bug; true balance ~$3,116 |
| Open trades | 15 | 9 in uncalibrated cities |
| Settled trades | 272 | All NO-side P&L incorrect |
| Strategy status | RETIRED | Brier 0.2641 > 0.25 threshold |
| Live trading | Disabled | Not graduated |
| known_weights.json | ABSENT | Stopped generating post-corruption fix |
| learned_correlations.json | ABSENT | Monte Carlo using hardcoded fallback |
| bias_models.pkl | ABSENT | ML bias correction non-functional |
| Seasonal weights | spring only | Summer/fall/winter use hardcoded defaults |
| Condition weights | "below" only | "above"/"between" use defaults |
| City-specific weights | 8 of 15 cities | 7 cities (Dallas, Denver, Miami, NYC, Philly, SF, DC) use defaults |

---

## Phase 0 — Pre-Live Blockers

**All 16 issues must be fully resolved and verified before the first live trade is placed.**  
Resolving these in order minimizes interdependencies.

---

### ✅ P0-1 · Fix NO-side Settlement P&L Formula
**File:** `main.py:_poll_pending_orders` (~line 1532)  
**Severity:** Critical — corrupts every live NO trade, all financial safety limits  
**Effort:** 2 hours (fix) + 1 hour (data migration)

**Root cause:** `side == "no"` orders store the NO contract price in `price`, but the settlement formula treats it as a YES price. For a NO at price `p`, if YES wins the loss should be `-p` (what was paid), but the code records `-(1-p)`. If NO wins the payout should be `(1-p)` but the code records `p`.

**Fix:**

```python
# main.py:_poll_pending_orders — replace settlement block
if outcome_yes:
    if side == "yes":
        pnl = qty * price * (1 - _fee)   # won YES
    else:  # side == "no"
        pnl = -qty * price                # lost NO (lose cost)
else:
    if side == "yes":
        pnl = -qty * price                # lost YES (lose cost)
    else:  # side == "no"
        pnl = qty * (1 - price) * (1 - _fee)  # won NO
```

**Data migration — run once after deploying the fix:**
```python
# migration/fix_no_side_pnl.py
# Load paper_trades.json, find all settled trades with side='no',
# recompute pnl using corrected formula, update balance accordingly,
# save with new checksum. Log every changed trade.
```

**Verification:** After migration, assert:
```python
assert abs(sum(t["pnl"] for t in settled) + STARTING_BALANCE - sum(t["cost"] for t in open_trades) - balance) < 0.01
```

---

### ✅ P0-2 · Enforce Graduation Gate in `_place_live_order`
**File:** `main.py:_place_live_order` (~line 1545), new `trading_gates.py`  
**Severity:** Critical — zero-paper-trade user can place real money orders  
**Effort:** 3 hours

**Root cause:** `graduation_check()` exists in `paper.py` but is never called from the live execution path.

**Best fix — create a centralized `trading_gates.py` module:**

```python
# trading_gates.py
from paper import (
    get_settled_count, get_cumulative_pnl, get_brier_score,
    is_paused_drawdown, is_daily_loss_halted, is_accuracy_halted,
    is_streak_paused,
)
from utils import KALSHI_ENV, ENABLE_MICRO_LIVE
import logging

_log = logging.getLogger(__name__)

class LiveTradingGate:
    """Single call point for all pre-trade live safety checks."""

    def check(self) -> tuple[bool, str]:
        """Returns (allowed, reason). Call before every live order."""
        if KALSHI_ENV != "prod":
            return False, f"KALSHI_ENV={KALSHI_ENV}, not prod"

        settled = get_settled_count()
        if settled < 30:
            return False, f"Graduation: only {settled}/30 settled paper trades"

        pnl = get_cumulative_pnl()
        if pnl < 50.0:
            return False, f"Graduation: P&L ${pnl:.2f} < $50"

        brier = get_brier_score()
        if brier is None or brier > 0.20:
            return False, f"Graduation: Brier {brier} > 0.20"

        if is_paused_drawdown():
            return False, "Drawdown halt active"

        if is_daily_loss_halted():
            return False, "Daily loss limit reached"

        if is_accuracy_halted():
            return False, "Accuracy halt (SPRT) active"

        return True, "ok"

    def check_or_raise(self):
        allowed, reason = self.check()
        if not allowed:
            raise RuntimeError(f"Live trading gate blocked: {reason}")

_GATE = LiveTradingGate()

def pre_live_trade_check():
    _GATE.check_or_raise()
```

Then in `main.py:_place_live_order`, add as the very first line:
```python
from trading_gates import pre_live_trade_check
pre_live_trade_check()  # raises if any gate fails
```

---

### ✅ P0-3 · Disable Micro-Live Until Properly Implemented
**File:** `main.py` (~lines 2991â€“3044), `utils.py`  
**Severity:** Critical — bypasses all gates, writes no audit logs, untraceable real money  
**Effort:** 30 minutes

**Root cause:** `ENABLE_MICRO_LIVE=true` places real Kalshi orders through a code path that has no drawdown check, no graduation check, no dedup, and no `execution_log` write.

**Best fix — disable until a safe implementation replaces it:**

```python
# utils.py
ENABLE_MICRO_LIVE: bool = False  # hard-disabled; remove when re-implemented safely
```

Document the correct future implementation requirements:
- Must call `pre_live_trade_check()` (P0-2)
- Must write `execution_log.log_order(status="pending")` before API call
- Must update to `status="placed"` with returned order_id after
- Must call `execution_log.add_live_loss(cost)` to maintain daily loss accounting
- Must run the same idempotency check as full live orders (P0-4)

---

### ✅ P0-4 · Add Idempotency Key to All Order Placements
**File:** `kalshi_client.py:place_order`, `main.py:_place_live_order`  
**Severity:** Critical — duplicate positions on any API timeout or retry  
**Effort:** 4 hours

**Root cause:** `urllib3.Retry` is configured with `allowed_methods={"GET","POST","DELETE"}`, auto-retrying POST orders. There is no `client_order_id` in the request body and no post-placement dedup check.

**Best fix:**

```python
# kalshi_client.py:_build_session — change allowed_methods
retry = Retry(
    total=3,
    status_forcelist={429, 500, 502, 503},
    allowed_methods={"GET", "DELETE"},  # POST explicitly excluded
    respect_retry_after_header=True,
    backoff_factor=0.5,
)
```

```python
# kalshi_client.py:place_order — add client_order_id
def place_order(self, ticker, side, qty, price_cents, cron_cycle_id=None):
    import hashlib, uuid
    # Deterministic ID: same inputs in same cycle = same ID
    # Kalshi will dedup server-side if this ID was already processed
    idempotency_input = f"{ticker}:{side}:{qty}:{price_cents}:{cron_cycle_id or uuid.uuid4()}"
    client_order_id = hashlib.sha256(idempotency_input.encode()).hexdigest()[:32]

    body = {
        "ticker": ticker,
        "action": "buy",
        "side": side,
        "count": qty,
        f"{side}_price": price_cents,
        "type": "limit",
        "client_order_id": client_order_id,
    }
    try:
        resp = self._request_with_retry("POST", "/portfolio/orders", json=body)
        return resp
    except Exception as exc:
        # On any failure, check if the order landed anyway
        existing = self._find_order_by_client_id(client_order_id)
        if existing:
            _log.warning("Order landed despite exception; returning existing: %s", existing)
            return existing
        raise

def _find_order_by_client_id(self, client_order_id: str):
    """Query open orders and return any matching client_order_id."""
    try:
        orders = self.get_orders(status="open")
        for o in orders:
            if o.get("client_order_id") == client_order_id:
                return o
    except Exception:
        pass
    return None
```

---

### ✅ P0-5 · Fix Cron Lock to Fail Closed with PID-Aware Stale Detection
**File:** `cron.py:_acquire_cron_lock` (~line 122)  
**Severity:** Critical — fails open on any I/O error; simultaneous processes = duplicate trades  
**Effort:** 2 hours

**Root cause:** Exception handler returns `True` (lock acquired). Stale detection uses a 600s age threshold that a 429 storm can exceed.

**Best fix — PID-aware lock with OS-level exclusivity:**

```python
# cron.py
import os, sys, time, json
try:
    import psutil
    _PSUTIL_AVAILABLE = True
except ImportError:
    _PSUTIL_AVAILABLE = False

def _acquire_cron_lock() -> bool:
    """
    Returns True only if lock was cleanly acquired.
    Fails CLOSED on any error (returns False, never True).
    Uses PID verification for stale detection — never overrides a live process.
    """
    lp = LOCK_PATH
    try:
        # Write our PID and a heartbeat timestamp
        lock_data = {"pid": os.getpid(), "started_at": time.time(), "heartbeat": time.time()}

        if lp.exists():
            try:
                existing = json.loads(lp.read_text())
                pid = existing.get("pid")
                heartbeat = existing.get("heartbeat", 0)
                started_at = existing.get("started_at", 0)

                # Check if the locking process is still alive
                if pid and _PSUTIL_AVAILABLE:
                    if psutil.pid_exists(pid):
                        age = time.time() - started_at
                        _log.warning("Cron already running (PID %d, started %.0fs ago)", pid, age)
                        return False
                    # PID dead — safe to override
                    _log.warning("Stale lock from dead PID %d; overriding", pid)
                else:
                    # No psutil — fall back to conservative 1800s age check
                    age = time.time() - heartbeat
                    if age < 1800:
                        _log.warning("Lock age %.0fs < 1800s; refusing to override without psutil", age)
                        return False
                    _log.warning("Stale lock (%.0fs old, no psutil); overriding", age)
            except Exception as parse_err:
                _log.warning("Unreadable lock file (%s); refusing to override (fail-closed)", parse_err)
                return False  # FAIL CLOSED — never override unreadable lock

        lp.write_text(json.dumps(lock_data))
        return True

    except Exception as exc:
        _log.error("Lock acquisition failed: %s — aborting cron (fail-closed)", exc)
        return False  # FAIL CLOSED — never proceed on unexpected error

def _heartbeat_cron_lock():
    """Call periodically during long cron runs to prevent stale detection."""
    try:
        if LOCK_PATH.exists():
            data = json.loads(LOCK_PATH.read_text())
            data["heartbeat"] = time.time()
            LOCK_PATH.write_text(json.dumps(data))
    except Exception:
        pass  # heartbeat failure is not fatal
```

Call `_heartbeat_cron_lock()` after every city processed in the scan loop.

---

### ✅ P0-6 · Write Execution Log BEFORE Placing Live Order
**File:** `main.py:_place_live_order` (~line 1588)  
**Severity:** Critical — crash between API call and log write = untracked real order = duplicate  
**Effort:** 2 hours

**Root cause:** `client.place_order()` is called before `execution_log.log_order()`. A crash in the window between them leaves a real Kalshi order invisible to all dedup and accounting.

**Best fix — pre-log pattern with crash recovery:**

```python
# main.py:_place_live_order
def _place_live_order(market, side, qty, price, cron_cycle_id=None):
    ticker = market["ticker"]
    
    # 1. Pre-log with status="pending" BEFORE touching the API
    log_id = execution_log.log_order(
        ticker=ticker, side=side, qty=qty, price=price,
        status="pending", live=True, cycle_id=cron_cycle_id
    )

    try:
        # 2. Place the order
        resp = client.place_order(
            ticker, side, qty,
            round(price * 100),
            cron_cycle_id=cron_cycle_id
        )
        order_id = resp.get("order", {}).get("order_id")

        # 3. Update log to "placed" with returned order_id
        execution_log.log_order_result(log_id, status="placed", order_id=order_id)
        execution_log.add_live_loss(qty * price)  # track cost against daily limit
        return True, price

    except Exception as exc:
        execution_log.log_order_result(log_id, status="failed", notes=str(exc))
        _log.error("Live order failed for %s: %s", ticker, exc)
        return False, 0.0

# At startup / cron start — scan for "pending" orders older than 60s
def _recover_pending_orders():
    """Check Kalshi API for any orders that were placed but not confirmed."""
    pending = execution_log.get_orders_by_status("pending", older_than_seconds=60)
    for row in pending:
        kalshi_order = client._find_order_by_client_id(row["client_order_id"])
        if kalshi_order:
            _log.warning("Recovered pending order %s from Kalshi", row["ticker"])
            execution_log.log_order_result(row["id"], status="placed",
                                            order_id=kalshi_order["order_id"])
        else:
            execution_log.log_order_result(row["id"], status="unconfirmed",
                                            notes="Not found on Kalshi after recovery scan")
```

---

### ✅ P0-7 · Make STARTING_BALANCE Configurable
**File:** `utils.py`, `paper.py`, `config.py`  
**Severity:** Critical — all safety limits miscalibrated if funded â‰  $1,000  
**Effort:** 1 hour

**Root cause:** `STARTING_BALANCE = 1000.0` hardcoded. Drawdown tiers, daily loss floor, exposure cap, and Kelly sizing all reference this constant.

**Best fix:**

```python
# utils.py
STARTING_BALANCE: float = float(os.getenv("STARTING_BALANCE", "1000"))
```

```python
# config.py:load_and_validate() — add validation
if STARTING_BALANCE <= 0:
    raise ValueError(f"STARTING_BALANCE must be positive, got {STARTING_BALANCE}")
if KALSHI_ENV == "prod" and STARTING_BALANCE != paper.get_seeded_balance():
    _log.warning(
        "STARTING_BALANCE env var ($%.2f) differs from ledger seeded balance ($%.2f). "
        "Using env var. Verify this is correct.",
        STARTING_BALANCE, paper.get_seeded_balance()
    )
```

Add `get_seeded_balance()` to `paper.py` — reads the balance from the first entry in the ledger audit trail, or returns `STARTING_BALANCE` if no history exists.

---

### ✅ P0-8 · Require Authentication on Mutation Endpoints
**File:** `web_app.py`  
**Severity:** Critical (Security) — kill switch, resume, cron spawn all unauthenticated  
**Effort:** 1 hour

**Root cause:** `@_require_auth` decorator is implemented but applied to zero routes. `before_request` hook allows everything when `DASHBOARD_PASSWORD` is empty.

**Best fix:**

```python
# web_app.py — apply decorator to all mutation routes
@_app.route("/api/halt", methods=["POST"])
@_require_auth
def api_halt():
    ...

@_app.route("/api/resume", methods=["POST"])
@_require_auth
def api_resume():
    ...

@_app.route("/api/run_cron", methods=["POST"])
@_require_auth
def api_run_cron():
    ...

# Also add rate limiting to /api/run_cron
_cron_spawns: dict[float] = {}  # track last spawn per IP

@_app.route("/api/run_cron", methods=["POST"])
@_require_auth
def api_run_cron():
    import time
    ip = request.remote_addr
    if time.time() - _cron_spawns.get(ip, 0) < 300:
        return jsonify({"error": "rate limited: 1 cron per 5 minutes"}), 429
    _cron_spawns[ip] = time.time()
    # ... rest of spawn logic
```

```python
# config.py:load_and_validate() — enforce password in prod
if KALSHI_ENV == "prod" and not os.getenv("DASHBOARD_PASSWORD"):
    raise RuntimeError(
        "DASHBOARD_PASSWORD must be set when KALSHI_ENV=prod. "
        "The dashboard exposes kill switch and trade control endpoints."
    )
```

---

### ✅ P0-9 · Replace Unsafe pickle.load on bias_models.pkl
**File:** `ml_bias.py:_load_models`  
**Severity:** Critical (RCE) — any write to data/ = arbitrary code execution  
**Effort:** 3 hours

**Root cause:** `pickle.load(f)` on `data/bias_models.pkl` with no integrity verification. Python pickle executes `__reduce__` during deserialization.

**Best fix — HMAC verification before any deserialization:**

```python
# ml_bias.py
import hashlib, hmac, os, json

_HMAC_KEY_PATH = Path(__file__).parent / "data" / ".bias_models.hmac"
_HMAC_SECRET = os.getenv("MODEL_HMAC_SECRET", "").encode()  # set in .env

def _compute_hmac(data: bytes) -> str:
    if not _HMAC_SECRET:
        raise RuntimeError("MODEL_HMAC_SECRET must be set in .env")
    return hmac.new(_HMAC_SECRET, data, hashlib.sha256).hexdigest()

def _load_models() -> dict:
    global _MODELS_CACHE
    if _MODELS_CACHE is not None:
        return _MODELS_CACHE

    pkl_path = _MODELS_PATH
    hmac_path = _HMAC_KEY_PATH

    if not pkl_path.exists():
        _MODELS_CACHE = {}
        return {}

    try:
        raw = pkl_path.read_bytes()

        # Verify HMAC before ANY deserialization
        if not hmac_path.exists():
            _log.error("bias_models.hmac missing — refusing to load pkl (RCE risk). "
                      "Retrain to regenerate both files.")
            _MODELS_CACHE = {}
            return {}

        expected_hmac = hmac_path.read_text().strip()
        actual_hmac = _compute_hmac(raw)

        if not hmac.compare_digest(expected_hmac, actual_hmac):
            _log.error("bias_models.pkl HMAC mismatch — file may have been tampered. "
                      "Skipping bias correction.")
            _MODELS_CACHE = {}
            return {}

        # Safe to load
        import pickle
        _MODELS_CACHE = pickle.loads(raw)
        return _MODELS_CACHE

    except Exception as exc:
        _log.warning("Failed to load bias models: %s — using no correction", exc)
        _MODELS_CACHE = {}
        return {}

def _save_models(models: dict):
    """Call this from train_bias_model() to write pkl + hmac atomically."""
    import pickle
    from safe_io import atomic_write_bytes  # add this to safe_io
    
    raw = pickle.dumps(models)
    mac = _compute_hmac(raw)
    
    atomic_write_bytes(raw, _MODELS_PATH)
    _HMAC_KEY_PATH.write_text(mac)
```

Long-term migration path: Replace pickle entirely with per-model JSON serialization of `GradientBoostingRegressor` parameters (coefficients, thresholds, estimator structure) — fully eliminates the attack surface.

---

### ✅ P0-10 · Fix Execution Log Write Ordering for Paper Trades
**File:** `main.py:_auto_place_trades` (~line 2877)  
**Severity:** High — crash between paper write and log write = duplicate position + dedup blind spot  
**Effort:** 1 hour

**Root cause:** `place_paper_order()` writes to `paper_trades.json`, then `execution_log.log_order()` is called. Crash between them = paper trade exists, execution_log says nothing happened, next run re-places.

**Fix — mirror the live order pre-log pattern:**

```python
# main.py:_auto_place_trades — for each paper trade
# 1. Pre-log to execution_log with status="pending"
log_id = execution_log.log_order(ticker=ticker, side=side, qty=qty,
                                   price=price, status="pending", live=False,
                                   cycle_id=_current_cycle_id)
try:
    # 2. Write paper trade
    trade = paper.place_paper_order(ticker=ticker, side=side, qty=qty, price=price, ...)
    # 3. Update log to "filled"
    execution_log.log_order_result(log_id, status="filled",
                                    order_id=trade["id"])
except Exception as exc:
    execution_log.log_order_result(log_id, status="failed", notes=str(exc))
    raise
```

---

### ✅ P0-11 · Enforce Retired Strategy Suppression in analyze_trade
**File:** `weather_markets.py:analyze_trade` (~line 3575)  
**Severity:** Critical — system continues trading on a method it flagged as failing (Brier 0.2641); retirement is cosmetic only  
**Effort:** 1 hour

**Root cause:** `get_retired_strategies()` is only called by the CLI display command and never by the forecast or trade execution pipeline. `weather_markets.py` sets `method = "ensemble"` whenever 10+ ensemble members are available, regardless of whether that method is retired. The `kelly_dollars=0.0` in `retired_strategies.json` is metadata written at display time — it has no runtime effect.

**Fix — add a retired-method gate in `analyze_trade` before Kelly sizing:**

```python
# weather_markets.py:analyze_trade — add near top after method is determined
from tracker import get_retired_strategies

def analyze_trade(market: dict, ...) -> dict | None:
    ...
    # After method is assigned (post-METAR lock, post-ensemble check):
    _retired = get_retired_strategies()
    if method in _retired:
        _log.info(
            "analyze_trade: skipping %s — method '%s' is retired (Brier %.4f)",
            market.get("ticker"), method, _retired[method].get("brier", 0)
        )
        return None
    ...
```

Cache the retired set at module load and refresh once per cron cycle to avoid a DB read on every market scan:

```python
# weather_markets.py — module-level cache
_retired_methods_cache: dict = {}
_retired_cache_ts: float = 0.0
_RETIRED_CACHE_TTL = 300  # 5 minutes

def _get_retired_methods() -> dict:
    global _retired_methods_cache, _retired_cache_ts
    if time.time() - _retired_cache_ts > _RETIRED_CACHE_TTL:
        from tracker import get_retired_strategies
        _retired_methods_cache = get_retired_strategies()
        _retired_cache_ts = time.time()
    return _retired_methods_cache
```

**Also fix the fallback behavior** — when `ensemble` is retired and `normal_dist` has enough data, use `normal_dist` rather than returning `None`, so cities still get priced. Only return `None` if no valid method remains:

```python
_retired = _get_retired_methods()
if method in _retired:
    if method == "ensemble" and gauss_prob is not None:
        # Degrade gracefully to Gaussian rather than going dark
        method = "normal_dist"
        ens_prob = None  # exclude ensemble from blend
        _log.info("analyze_trade: ensemble retired — falling back to normal_dist for %s",
                  market.get("ticker"))
    else:
        return None
```

**Add test:**

```python
# tests/test_retirement.py
def test_retired_method_suppresses_trade(monkeypatch, mock_market):
    monkeypatch.setattr("weather_markets._retired_methods_cache",
                        {"ensemble": {"brier": 0.30, "retired_at": "..."}})
    monkeypatch.setattr("weather_markets._retired_cache_ts", time.time())
    result = analyze_trade(mock_market)
    # Should fall back to normal_dist, not return None, if gauss_prob available
    assert result is None or result["method"] == "normal_dist"

def test_unretired_method_trades_normally(monkeypatch, mock_market):
    monkeypatch.setattr("weather_markets._retired_methods_cache", {})
    monkeypatch.setattr("weather_markets._retired_cache_ts", time.time())
    result = analyze_trade(mock_market)
    assert result is not None
```

---

## Phase 1 — Paper Safety Hardening

**Fix within 2 weeks. These affect paper P&L accuracy and data integrity now.**

---

### ✅ P1-1 · Fix data_fetched_at to Reflect Cache Entry's Original Fetch Time
**File:** `weather_markets.py:enrich_with_forecast` (~line 2102)  
**Root cause:** `data_fetched_at` is set to `time.time()` at enrichment, not the underlying cache entry's fetch timestamp. A 4-hour-old cached forecast appears fresh.

**Fix:** `ForecastCache.get()` should return the original `stored_at` timestamp alongside the value. `enrich_with_forecast` should use that timestamp as `data_fetched_at`.

```python
# forecast_cache.py:ForecastCache.get — return 3-tuple
def get(self, key) -> tuple[Any, bool, float]:
    """Returns (value, hit, original_stored_at). stored_at=0 on miss."""
    with self._lock:
        entry = self._store.get(key)
        if entry is None:
            return None, False, 0.0
        value, stored_at, ttl = entry if len(entry) == 3 else (*entry, self._default_ttl)
        if time.time() - stored_at > ttl:
            del self._store[key]
            return None, False, 0.0
        return value, True, stored_at
```

```python
# weather_markets.py:enrich_with_forecast
forecast, hit, fetch_ts = _forecast_cache.get(cache_key)
market["data_fetched_at"] = fetch_ts if hit else time.time()
```

---

### ✅ P1-2 · Add METAR Staleness Gate and Ensemble Sanity Check
**File:** `metar.py:fetch_metar`, `weather_markets.py:_metar_lock_in`  
**Root cause:** No staleness check on `obs_time`; no comparison against ensemble before committing to lock-in; missing `obsTime` replaced with `now()`.

**Fix:**

```python
# metar.py:fetch_metar — after parsing temp_f
# 1. Reject missing timestamp
if obs_time is None:
    _log.warning("%s: METAR obs_time missing — refusing lock-in", station)
    return None

# 2. Staleness check — reject observations older than 90 minutes
age_minutes = (datetime.now(UTC) - obs_time).total_seconds() / 60
if age_minutes > 90:
    _log.warning("%s: METAR %d min old — too stale for lock-in", station, age_minutes)
    return None

# 3. Temperature plausibility check
if not (-80.0 <= temp_f <= 140.0):
    _log.error("%s: METAR temp %.1fÂ°F outside plausible range — rejecting", station, temp_f)
    return None
```

```python
# weather_markets.py:_metar_lock_in — add ensemble sanity check
def _metar_lock_in(market, current_temp_f, ensemble_mean_f):
    ...
    # Before committing to lock-in, check ensemble agreement
    if ensemble_mean_f is not None:
        disagreement = abs(current_temp_f - ensemble_mean_f)
        if disagreement > 15.0:
            _log.warning(
                "%s: METAR %.1fÂ°F disagrees with ensemble mean %.1fÂ°F by %.1fÂ°F "
                "— refusing lock-in (possible sensor fault)",
                ticker, current_temp_f, ensemble_mean_f, disagreement
            )
            return locked=False, ...
    ...
```

---

### ✅ P1-3 · Wire is_accuracy_halted() into the Trading Path
**File:** `main.py:_auto_place_trades`, `trading_gates.py` (new, from P0-2)  
**Root cause:** `is_accuracy_halted()` exists in `paper.py` and works correctly, but is never called from any production trading path.

**Fix:** This is already handled by P0-2's `trading_gates.py`. Additionally, add the check in `_cmd_cron_body`:

```python
# cron.py:_cmd_cron_body — add to halt checks
from paper import is_accuracy_halted

if is_accuracy_halted():
    reason = paper.get_accuracy_halt_reason()
    _log.warning("ACCURACY HALT ACTIVE: %s — skipping all trades this cycle", reason)
    _notify_if_possible(f"Accuracy halt active: {reason}")
    return  # skip entire scan
```

---

### ✅ P1-4 · Fix ML Backtest Look-Ahead in _find_optimal_min_edge
**File:** `backtest.py:_find_optimal_min_edge` (~line 878)  
**Root cause:** Scans the full dataset including test folds to pick `optimal_min_edge`, persists to `walk_forward_params.json`, which `config.py` uses for live `PAPER_MIN_EDGE`.

**Fix:**

```python
# backtest.py:walk_forward_backtest — pass only training data
def walk_forward_backtest(trades, folds=6, ...):
    results = []
    for train_trades, test_trades in _temporal_folds(trades, folds):
        # Find optimal threshold on TRAINING data only
        optimal_edge = _find_optimal_min_edge(train_trades)  # NOT full dataset
        
        # Evaluate on TEST data using the training-derived threshold
        test_results = _evaluate_fold(test_trades, min_edge=optimal_edge)
        results.append(test_results)
    
    # Aggregate: use median optimal_edge across training folds
    agg_optimal_edge = statistics.median([r["optimal_edge"] for r in results])
    # Persist this out-of-sample-safe threshold
    _persist_optimal_edge(agg_optimal_edge)
    return results
```

After deploying this fix, regenerate `walk_forward_params.json` and verify `PAPER_MIN_EDGE` is not artificially low.

---

### ✅ P1-5 · Fix SHA-256 Checksum to Use Full-Length Constant-Time Comparison
**File:** `paper.py:_validate_checksum` (~line 55)  
**Root cause:** `if not expected.startswith(stored)` — empty string passes; 1-char prefix passes 1/16 of all corruptions.

**Fix:**

```python
# paper.py:_validate_checksum
import hmac as _hmac

def _validate_checksum(data: dict) -> None:
    stored = data.get("_checksum") or data.get("_crc32")
    if not stored:
        return  # legacy file with no checksum — allow but log

    # Strip checksum fields before computing expected
    payload = {k: v for k, v in data.items() if k not in ("_checksum", "_crc32")}
    expected = _compute_sha256(payload)  # full 64-char hex

    # Constant-time comparison on the overlap length
    # For legacy 8-char: compare only first 8 chars of expected
    compare_len = len(stored)
    if compare_len not in (8, 16, 64):
        raise CorruptionError(f"Unexpected checksum length {compare_len}")

    if not _hmac.compare_digest(expected[:compare_len], stored):
        raise CorruptionError(
            f"Checksum mismatch (stored={stored[:8]}..., expected={expected[:compare_len]})"
        )
```

Migrate: on next `_save()`, always write the full 64-char checksum. Remove 8-char legacy support after one month.

---

### ✅ P1-6 · Fix atomic_write_json to Raise on %TEMP% Fallback
**File:** `safe_io.py:atomic_write_json` (~line 93)  
**Root cause:** Fallback to `tempfile.gettempdir()` returns success silently; next read gets old data.

**Fix:**

```python
# safe_io.py:atomic_write_json — remove silent fallback
# After all retries exhausted:
raise AtomicWriteError(
    f"Failed to write {path} after {max_retries} attempts. "
    f"Disk full, permissions error, or path unavailable. "
    f"Emergency copy written to {emergency_path} for manual recovery."
)
# Write to emergency path ONLY for manual operator recovery, not as a transparent fallback
```

---

### ✅ P1-7 · Persist Circuit Breaker State Between Process Invocations
**File:** `circuit_breaker.py`, `config.py`  
**Root cause:** All circuit breaker state is in-process memory. Scheduler calls `py main.py cron` as a new process — all state resets to zero every invocation.

**Fix:**

```python
# circuit_breaker.py — add persistence
import json
from safe_io import atomic_write_json

_CB_STATE_PATH = Path(__file__).parent / "data" / ".cb_state.json"

class CircuitBreaker:
    def __init__(self, name: str, failure_threshold=5, recovery_timeout=60, 
                 burst_window=0, persist=True):
        self._name = name
        self._persist = persist
        self._state_path = _CB_STATE_PATH
        self._load_state()

    def _load_state(self):
        if not self._persist:
            self._reset()
            return
        try:
            state = json.loads(self._state_path.read_text()) if self._state_path.exists() else {}
            cb = state.get(self._name, {})
            self._failure_count = cb.get("failure_count", 0)
            self._opened_at = cb.get("opened_at")  # None or float timestamp
            self._last_failure_at = cb.get("last_failure_at")
            self._trip_count = cb.get("trip_count", 0)
        except Exception:
            self._reset()

    def _save_state(self):
        if not self._persist:
            return
        try:
            state = {}
            if self._state_path.exists():
                state = json.loads(self._state_path.read_text())
            state[self._name] = {
                "failure_count": self._failure_count,
                "opened_at": self._opened_at,
                "last_failure_at": self._last_failure_at,
                "trip_count": self._trip_count,
                "saved_at": time.time(),
            }
            atomic_write_json(state, self._state_path)
        except Exception as exc:
            _log.debug("CB state save failed (non-critical): %s", exc)

    def record_failure(self):
        ...  # existing logic
        self._save_state()

    def record_success(self):
        ...  # existing logic
        self._save_state()
```

---

### ✅ P1-8 · Fix Balance Discrepancy in Settlement Path
**File:** `paper.py:settle_paper_trade`  
**Root cause:** `settle_paper_trade` uses `actual_fill_price × qty` as cost basis but entry deducted `entry_price × qty`.

**Fix:**

```python
# paper.py:settle_paper_trade — use entry_price as cost basis, not actual_fill_price
trade = data["trades"][idx]
entry_price = trade["entry_price"]   # what was actually paid at entry
qty = trade["quantity"]
outcome = "yes" if trade["side"] == "yes" else "no"
won = (outcome == result)

if won:
    winnings_per_contract = 1.0 - entry_price
    fee = winnings_per_contract * KALSHI_FEE_RATE
    payout = qty * (winnings_per_contract - fee)
    pnl = payout  # cost already deducted at entry
else:
    pnl = -entry_price * qty  # lose only what was paid

data["balance"] += (pnl + entry_price * qty)  # refund cost + add pnl
```

Run migration to recompute all historical settled trades (same script as P0-1 data migration, different formula for paper trades).

---

### ✅ P1-9 · Restore learned_weights.json Generation
**File:** `weather_markets.py` (blend weight loading), `main.py:cmd_calibrate`  
**Root cause:** Corruption fix (bd6c0ef) appears to have stopped generating this file.

**Fix:**
1. Audit the `cmd_calibrate` path to find where `learned_weights.json` was previously written.
2. Re-enable the write, but add a validation gate:
```python
# Before writing learned_weights.json
if any(v < 0.001 for v in weights.values()):
    _log.error("Learned weights contain near-zero values — not persisting (corruption risk)")
    return
if abs(sum(weights.values()) - 1.0) > 0.01:
    _log.error("Learned weights don't sum to 1.0 (%f) — not persisting", sum(weights.values()))
    return
```
3. Add a startup check: if `learned_weights.json` exists but any value is 0 or negative, delete it and log a warning rather than loading corrupt values.

---

### ✅ P1-10 · Fix Regression Test Baselines
**File:** `tests/test_regression.py`, `tests/conftest.py`  
**Root cause:** `test_brier_score_not_degraded` and `test_roc_auc_not_degraded` silently skip when the baseline file doesn't exist.

**Fix:**

```python
# tests/conftest.py or tests/generate_baseline.py — generate baseline as part of test setup
@pytest.fixture(scope="session", autouse=True)
def ensure_regression_baseline(tmp_path_factory):
    baseline_path = Path("tests/fixtures/regression_baseline.json")
    if not baseline_path.exists():
        pytest.fail(
            "Regression baseline file missing. "
            "Run: python tests/generate_baseline.py to create it. "
            "This is not optional — model quality regression cannot be detected without it."
        )
```

```python
# tests/test_regression.py — fail loudly instead of skipping
def test_brier_score_not_degraded():
    baseline = load_baseline()
    if baseline.get("brier_score") is None:
        pytest.fail("Baseline brier_score is None — baseline file incomplete or corrupted")
    # ... rest of test
```

---

### ✅ P1-11 · Fix conftest.py Past Date
**File:** `tests/conftest.py`  
**Root cause:** `target_date = date(2025, 4, 9)` is permanently in the past.

**Fix:**
```python
# tests/conftest.py
from datetime import date, timedelta, timezone

@pytest.fixture
def mock_market():
    target = date.today() + timedelta(days=3)  # always future
    return {
        "ticker": f"KXHIGHNYC-{target.strftime('%y%b%d').upper()}-B72",
        "target_date": target,
        ...
    }
```

---

### ✅ P1-12 · Add Kill Switch Check Inside Per-City Analysis Loop
**File:** `cron.py:_cmd_cron_body`  
**Root cause:** Kill switch checked once at scan start; activating mid-scan doesn't prevent placement of already-analyzed trades.

**Fix:**
```python
# cron.py:_cmd_cron_body — inside the per-city analysis loop
for market in markets:
    if KILL_SWITCH_PATH.exists():
        _log.warning("Kill switch activated mid-scan at %s — stopping analysis", market["ticker"])
        break
    # also before each placement in _auto_place_trades:
    if KILL_SWITCH_PATH.exists():
        _log.warning("Kill switch activated before placement of %s — skipping", ticker)
        return placed
```

---

## ✅ Phase 2 — Correctness & Observability (COMPLETE)

**Fix within 1 month. These affect forecast accuracy, risk math, and operational visibility.**

---

### ✅ P2-1 · Regenerate learned_correlations.json and Fix MC Fallback Flag
**Files:** `monte_carlo.py`, correlation generation script  
**Root cause:** File absent â†’ Cholesky fails â†’ silent fallback to independent draws â†’ `correlation_applied=True` (wrong).

**Fix:**
1. Implement `scripts/compute_correlations.py` that computes city-pair correlation matrix from historical paper trade outcomes in `predictions.db` and writes to `data/learned_correlations.json`.
2. Validate on write: all values in [-1, 1], matrix symmetric, diagonal = 1.0, matrix is PSD (check via eigenvalues).
3. Fix the fallback flag: `correlation_applied = False` when Cholesky fails.
4. Add nearest-PSD repair (Higham's algorithm or eigenvalue flooring) so correlated simulation can proceed even with near-PSD matrices.
5. Add startup check: refuse live trading if file absent (`KALSHI_ENV=prod`).

---

### ✅ P2-2 · Fix Drawdown Tier Boundaries for Non-Default DRAWDOWN_HALT_PCT
**File:** `paper.py:drawdown_scaling_factor` (~line 330)  
**Root cause:** Tiers relative to `DRAWDOWN_HALT_PCT`; any non-0.20 value shifts all boundaries.

**Fix — use absolute tier boundaries independent of halt threshold:**
```python
# paper.py:drawdown_scaling_factor
TIER_4 = 0.95  # absolute, not relative to halt %
TIER_3 = 0.90
TIER_2 = 0.85
TIER_1 = 0.80  # = halt threshold, always

def drawdown_scaling_factor(balance: float, peak: float) -> float:
    if peak <= 0:
        return 1.0
    recovery = balance / peak
    if recovery <= TIER_1:   return 0.0   # HALT
    if recovery <= TIER_2:   return 0.10
    if recovery <= TIER_3:   return 0.30
    if recovery <= TIER_4:   return 0.70
    return 1.0
```

Add startup assertion:
```python
assert TIER_1 < TIER_2 < TIER_3 < TIER_4 <= 1.0, "Tier ordering invariant violated"
```

---

### ✅ P2-3 · Fix is_streak_paused Sort Field
**File:** `paper.py:is_streak_paused` (~line 1434)  
**Root cause:** Sorts by `entered_at` not `settled_at`; wrong streak window.

**Fix:**
```python
settled.sort(key=lambda t: t.get("settled_at") or t.get("entered_at", ""))
```

---

### ✅ P2-4 · Fix Exposure Cap Denominator Consistency
**Files:** `paper.py:place_paper_order:526`, `paper.py:get_ticker_exposure`  
**Root cause:** `get_ticker_exposure` uses `_exposure_denom()` but `place_paper_order` uses raw `STARTING_BALANCE` for the new cost fraction.

**Fix:**
```python
# paper.py:place_paper_order
denom = _exposure_denom()
existing_exposure = get_ticker_exposure(ticker)   # already uses denom
new_cost_fraction = cost / denom                  # same denom
if existing_exposure + new_cost_fraction > MAX_TICKER_EXPOSURE:
    _log.info("Ticker exposure cap: %s (%.1f%% + %.1f%% > %.1f%%)",
              ticker, existing_exposure*100, new_cost_fraction*100, MAX_TICKER_EXPOSURE*100)
    return None
```

Also review `_exposure_denom()` ratchet behavior: decide whether caps should grow with profits (current behavior) or stay fixed at STARTING_BALANCE. Document the decision.

---

### ✅ P2-5 · Restore WebSocket Price Subscription
**File:** `cron.py` (~line 422)  
**Root cause:** `.subscribe(active_tickers)` call is commented out.

**Fix:**
```python
# cron.py — after market scan, before _auto_place_trades
_ws = KalshiWebSocket(api_key, key_pem)
_ws.start()
_ws.subscribe(active_tickers)   # uncomment this line
```

If the WS is not ready to be used properly, remove it entirely rather than starting a connection that consumes quota for nothing. There should be no code that creates a network connection to Kalshi for zero benefit.

---

### ✅ P2-6 · Fix "between" Market Lock-In Confidence
**File:** `weather_markets.py:_metar_lock_in` (~line 3330)  
**Root cause:** Hardcoded `confidence=0.95` regardless of proximity to bucket edge.

**Fix:**
```python
# weather_markets.py — dynamic confidence for "between" markets
def _between_lock_confidence(temp_f, lower_f, upper_f):
    bucket_width = upper_f - lower_f
    if bucket_width <= 0:
        return 0.50
    center = (lower_f + upper_f) / 2
    # Distance from nearest edge as fraction of half-bucket-width
    edge_dist = min(temp_f - lower_f, upper_f - temp_f)
    # confidence scales from 0.50 (at edge) to 0.95 (at center)
    confidence = 0.50 + 0.45 * min(1.0, edge_dist / (bucket_width * 0.3))
    return round(confidence, 3)
```

Minimum clearance requirement: if `edge_dist < 1.5Â°F`, refuse to lock in entirely.

---

### ✅ P2-7 · Populate Seasonal, Condition, and City Weight Files
**Files:** `data/seasonal_weights.json`, `data/condition_weights.json`, `data/city_weights.json`  

**Seasonal weights:** Add summer/fall/winter entries. Until calibrated from real data, use the spring entry as a neutral starting point with a WARNING log indicating the weights are uncalibrated for those seasons.

**Condition weights:** Add "above" and "between" entries. The "below" entry currently has `nws=0.36` — use similar proportions for above/between until calibrated.

**City weights:** Fix Minneapolis (0.97 climatology is almost certainly a calibration artifact — reset to equal weights 0.33/0.33/0.33 and recalibrate). For all 7 uncalibrated cities (Dallas, Denver, Miami, NYC, Philadelphia, SF, Washington), add entries with equal starting weights.

Add startup validation:
```python
def validate_weight_files():
    for season in ["spring", "summer", "fall", "winter"]:
        w = seasonal_weights.get(season)
        if w is None:
            _log.warning("No seasonal weights for %s — using hardcoded defaults", season)
        elif abs(sum(w.values()) - 1.0) > 0.005:
            _log.error("Seasonal weights for %s don't sum to 1.0", season)
```

---

### ✅ P2-8 · Add Explicit fee_rate to All kelly_fraction() Call Sites
**File:** `weather_markets.py`, `paper.py`  

**Fix — change the default:**
```python
# weather_markets.py:kelly_fraction
from utils import KALSHI_FEE_RATE

def kelly_fraction(our_prob: float, price: float, 
                   fee_rate: float = KALSHI_FEE_RATE) -> float:
    # Now safe: forgetting the argument uses the correct default
```

Also audit all call sites and add explicit `fee_rate=KALSHI_FEE_RATE` arguments everywhere for clarity. Add a test:
```python
def test_production_kelly_uses_fee_rate():
    """Verify that production trade sizing uses the real fee rate, not 0."""
    # Call analyze_trade and check that kelly_dollars reflects ~7% fee discount
    result = analyze_trade(mock_market_with_strong_edge)
    no_fee_kelly = kelly_fraction(result["our_prob"], result["market_price"], fee_rate=0.0)
    assert result["kelly_fraction"] < no_fee_kelly, "Production Kelly must include fee discount"
```

---

### ✅ P2-9 · Add Startup Warning When PAPER_MIN_EDGE Loaded from File
**File:** `config.py:_paper_min_edge_default`  

**Fix:**
```python
def _paper_min_edge_default() -> float:
    env_val = os.getenv("PAPER_MIN_EDGE")
    if env_val:
        return float(env_val)
    
    for source_path, source_name in [
        (WALK_FORWARD_PARAMS_PATH, "walk_forward_params.json"),
        (PARAM_SWEEP_PATH, "param_sweep_results.json"),
    ]:
        if source_path.exists():
            val = _read_min_edge_from_file(source_path)
            if val is not None:
                _log.warning(
                    "PAPER_MIN_EDGE loaded from %s: %.4f "
                    "(override with PAPER_MIN_EDGE env var to pin a value)",
                    source_name, val
                )
                return max(0.03, min(0.15, val))  # clamp to safety bounds
    
    return 0.05  # hardcoded fallback
```

---

### ✅ P2-10 · Fix Minneapolis City Weights
**File:** `data/city_weights.json`  

Immediate fix:
```json
"Minneapolis": {"ensemble": 0.34, "climatology": 0.33, "nws": 0.33}
```

Root cause investigation: determine why calibration produced 97% climatology for Minneapolis. Likely cause: NWS endpoint for Minneapolis was returning errors during calibration, so all NWS weight was absent, and climatology weight was inflated to compensate. If NWS is genuinely unavailable for Minneapolis, the correct fix is:
```json
"Minneapolis": {"ensemble": 0.55, "climatology": 0.45, "nws": 0.00}
```

---

### ✅ P2-11 · Fix MOS Non-Numeric Temperature Values
**File:** `mos.py:fetch_mos`  

**Fix:**
```python
def _parse_temp(value) -> float | None:
    """Parse MOS temperature field, handling ASOS special codes."""
    if value is None:
        return None
    s = str(value).strip()
    if s in ("M", "m", "T", "t", "", "N/A"):  # ASOS missing/trace/unavailable
        return None
    try:
        return float(s)
    except (ValueError, TypeError):
        _log.debug("Unparseable MOS temp value: %r", value)
        return None

# In fetch_mos:
temps = [_parse_temp(r.get("tmp")) for r in day_rows]
temps = [t for t in temps if t is not None]
```

---

### ✅ P2-12 · Add TTL to Climate Indices Cache
**File:** `climate_indices.py`  

**Fix:**
```python
_indices_cache: dict = {}
_indices_loaded_at: float = 0.0
_INDICES_TTL_SECS = 86400  # 24 hours
_indices_lock = threading.Lock()

def get_indices() -> dict:
    global _indices_cache, _indices_loaded_at
    with _indices_lock:
        if _indices_cache and (time.time() - _indices_loaded_at) < _INDICES_TTL_SECS:
            return _indices_cache
        # Fetch fresh data...
        result = _fetch_all_indices()
        _indices_cache = result
        _indices_loaded_at = time.time()
        return result
```

---

### ✅ P2-13 · Add api_requests Table Pruning
**File:** `tracker.py`  

**Fix — add retention policy to schema migration or cron:**
```python
# tracker.py:_apply_migrations or a new cmd_cleanup
def prune_api_requests(days_to_keep=90):
    cutoff = (datetime.now(UTC) - timedelta(days=days_to_keep)).isoformat()
    with _get_conn() as conn:
        deleted = conn.execute(
            "DELETE FROM api_requests WHERE logged_at < ?", (cutoff,)
        ).rowcount
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    if deleted > 0:
        _log.info("Pruned %d api_request rows older than %d days", deleted, days_to_keep)
```

Call from `cron.py` weekly (not every run) by checking day-of-week.

---

### ✅ P2-14 · Add Proper Checksum to safe_io Writes
**File:** `safe_io.py:atomic_write_json`, `paper.py:_save`  
**Root cause:** `safe_io` has no checksum; the checksum logic lives entirely in `paper.py` and is bypassed by direct `atomic_write_json` calls.

**Fix — embed checksum in paper.py before calling safe_io:**
```python
# paper.py:_save — embed checksum before atomic write
def _save(data: dict):
    payload = {k: v for k, v in data.items() if k not in ("_checksum", "_crc32")}
    checksum = _compute_sha256(payload)  # full 64-char
    payload["_checksum"] = checksum
    atomic_write_json(payload, DATA_PATH)
```

This keeps checksum logic in `paper.py` where it belongs (since it's paper-specific), while `safe_io` handles the atomic write.

---

### ✅ P2-15 · Fix NWS Thread Safety and Circuit Breaker Coverage
**Files:** `nws.py`  
**Root cause:** `_forecast_cache`, `_gridpoint_cache` are unprotected plain dicts. `get_live_precip_obs` bypasses circuit breaker.

**Fix:**
```python
# nws.py — replace module-level dicts with thread-safe versions
from forecast_cache import ForecastCache

_forecast_cache = ForecastCache(default_ttl=3600)
_gridpoint_cache = ForecastCache(default_ttl=86400)

# get_live_precip_obs — add circuit breaker integration
def get_live_precip_obs(station_id):
    if _nws_cb.is_open():
        return None
    try:
        result = _get(f"{_NWS_BASE}/stations/{station_id}/observations/latest")
        _nws_cb.record_success()
        ...
        return result
    except Exception as exc:
        _nws_cb.record_failure()
        _log.debug("get_live_precip_obs failed for %s: %s", station_id, exc)
        return None
```

---

### ✅ P2-16 · No Startup Warning When KALSHI_ENV=prod
**File:** `main.py`, `cron.py`  

**Fix:**
```python
# main.py:main() and cron.py:cmd_cron() — add at very top
if os.getenv("KALSHI_ENV") == "prod":
    _log.warning("=" * 60)
    _log.warning("RUNNING IN PRODUCTION MODE — REAL MONEY TRADES ENABLED")
    _log.warning("KALSHI_ENV=prod | STARTING_BALANCE=$%.2f", STARTING_BALANCE)
    _log.warning("=" * 60)
```

---

### ✅ P2-17 · Validate Market Prices in Schema Validator
**File:** `schema_validator.py:validate_market`  

**Fix:**
```python
def validate_market(market: dict) -> bool:
    required = ["ticker", "yes_bid", "yes_ask"]
    for field in required:
        if field not in market:
            _log.warning("Market missing field: %s", field)
            return False
    
    # Price range validation
    bid = market.get("yes_bid", -1)
    ask = market.get("yes_ask", -1)
    if not (0.0 < bid < 1.0):
        _log.warning("Market %s: yes_bid %.4f out of range (0,1)", market.get("ticker"), bid)
        return False
    if not (0.0 < ask < 1.0):
        _log.warning("Market %s: yes_ask %.4f out of range (0,1)", market.get("ticker"), ask)
        return False
    if bid >= ask:
        _log.warning("Market %s: bid %.4f >= ask %.4f (inverted spread)", market.get("ticker"), bid, ask)
        return False
    
    return True
```

Call `validate_market()` at entry to `analyze_trade()` as a pre-condition guard.

---

### ✅ P2-18 · Fix UTC/Local Date Inconsistencies
**Files:** `nws.py:nws_prob`, `mos.py:fetch_mos`, `cron.py:_check_startup_orders`  
**Root cause:** Several places use `date.today()` (system local) where `datetime.now(UTC).date()` should be used.

**Fix:**
```python
# Add this to utils.py as a canonical helper
from datetime import datetime, timezone

def utc_today() -> date:
    """Canonical UTC date. Use everywhere instead of date.today()."""
    return datetime.now(timezone.utc).date()
```

Then grep for `date.today()` in all production files and replace with `utc_today()`.

For `cron.py:_check_startup_orders` placed_at parsing:
```python
# Force UTC interpretation of naive datetimes from DB
placed_dt = datetime.fromisoformat(placed_at)
if placed_dt.tzinfo is None:
    placed_dt = placed_dt.replace(tzinfo=timezone.utc)
```

---

### ✅ P2-19 · Make Anomaly Detection Block Trading (Not Just Log)
**File:** `alerts.py:run_anomaly_check`, `cron.py:_cmd_cron_body`  

**Fix — tiered response:**
```python
# alerts.py:run_anomaly_check — return severity
ALERT_HALT_THRESHOLDS = {
    "WIN_RATE_COLLAPSE": 0.25,    # win rate below 25% â†’ halt
    "CONSECUTIVE_LOSSES": 6,      # 6+ consecutive â†’ halt
    "EDGE_DECAY": -0.10,          # edge below -10% â†’ halt
}

def run_anomaly_check() -> tuple[list[str], bool]:
    """Returns (alert_messages, should_halt)."""
    alerts = check_anomalies()
    should_halt = any(_is_halt_level(a) for a in alerts)
    if should_halt:
        _log.error("ANOMALY HALT: %s", alerts)
        # Write halt state (same mechanism as black swan)
        _write_anomaly_halt_flag(alerts)
    return alerts, should_halt
```

```python
# cron.py:_cmd_cron_body
alerts, should_halt = run_anomaly_check(log_results=True)
if should_halt:
    _log.warning("Anomaly halt active — skipping all trades this cycle")
    return
```

---

### ✅ P2-20 · Add Timestamped Cloud Backup Rotation
**File:** `cloud_backup.py:backup_data`  

**Fix:**
```python
def backup_data(sync_folder: Path):
    today_dir = sync_folder / "KalshiBot" / "data" / datetime.now(UTC).strftime("%Y-%m-%d")
    today_dir.mkdir(parents=True, exist_ok=True)
    
    for src_file in DATA_PATH.glob("*.json"):
        shutil.copy2(src_file, today_dir / src_file.name)
    for src_file in DATA_PATH.glob("*.db"):
        shutil.copy2(src_file, today_dir / src_file.name)
    
    # Prune directories older than 30 days
    for old_dir in (sync_folder / "KalshiBot" / "data").iterdir():
        if old_dir.is_dir():
            try:
                dir_date = date.fromisoformat(old_dir.name)
                if (date.today() - dir_date).days > 30:
                    shutil.rmtree(old_dir)
            except ValueError:
                pass  # not a date-named directory
```

---

## Phase 3 — Architecture Cleanup

**Fix when capacity allows. These reduce maintenance burden and future risk.**

---

### P3-1 · Calibration Train/Test Isolation
**File:** `calibration.py`  
Add `cutoff_date` parameter to all `calibrate_*` functions. Train on data before cutoff, evaluate on data after. Default to 80/20 temporal split. Never evaluate on the same data used for weight optimization.

### P3-2 · Replace A/B Test Fixed Sample with Sequential Design
**File:** `ab_test.py`  
50 trades per variant gives ~40-50% power for a 20pp effect. Options:
- Increase `max_trades_per_variant` to 200+ (simple, immediate improvement)
- Implement a proper SPRT sequential test (stop early only if significance reached)
- Use Thompson sampling (Bayesian bandit) for exploration/exploitation balance

Also fix: `get_active_variant` must read `max_trades_per_variant` from the persisted test state, not a hardcoded module constant.

### P3-3 · Fix Monte Carlo VaR Gate Sample Count
**File:** `monte_carlo.py:simulate_portfolio`  
Increase `n_simulations` from 1000 to 5000 for the `portfolio_var` call used as a hard trade gate. At 1000, the p5 estimator has Â±$5-10 noise on a $200 gate. Add nearest-PSD repair (eigenvalue flooring) so the Cholesky path completes even with near-singular matrices.

### P3-4 · Implement CircuitBreaker.execute() Wrapper
**File:** `circuit_breaker.py`  
Add an `execute(fn, *args, **kwargs)` method that enforces the circuit check automatically. Make it the recommended API. This turns protection from opt-in to opt-out.

### P3-5 · Split Kalshi Circuit Breakers by Operation Type
**File:** `kalshi_client.py`  
Create separate circuit breakers for read operations (`get_market`, `get_markets`, `get_orders`) and write operations (`place_order`, `cancel_order`). 5 read failures should not block order placement.

### P3-6 · Add True HALF-OPEN State to CircuitBreaker
**File:** `circuit_breaker.py`  
After `recovery_timeout`, allow exactly one probe request. If it succeeds â†’ CLOSED. If it fails â†’ re-open with exponential backoff multiplier. This prevents the current behavior where recovery allows up to `failure_threshold - 1` additional failures.

### P3-7 · Fix Calibration Overfitting at Low Sample Counts
**File:** `calibration.py`  
Raise `_CITY_MIN` from 15 to 50. Use random search (200 samples) instead of exhaustive grid (5,151 candidates). Only replace equal weights with calibrated weights if held-out Brier improvement exceeds 0.005.

### P3-8 · Remove _main_module() Runtime Coupling
**File:** `cron.py`, `main.py`  
Create a `CronContext` dataclass containing the required function references. Construct it in `main.py` and pass it to `cmd_cron`. This makes the dependency explicit, enables static analysis, and eliminates the `sys.modules` lookup hack.

```python
# cron.py
@dataclass
class CronContext:
    auto_place_trades: Callable
    get_weather_markets: Callable
    sync_outcomes: Callable
    # ... etc.

def cmd_cron(ctx: CronContext, ...):
    ctx.auto_place_trades(...)
```

### P3-9 · Extract _auto_place_trades and Order Executor from main.py
**File:** `main.py` (7,047 lines)  
Extract the following into `order_executor.py`:
- `_auto_place_trades` (~450 lines)
- `_place_live_order`
- `_poll_pending_orders`
- `_check_early_exits`

This is the highest-value extraction from the God file. These are the financial-critical functions with the most test coverage requirements and the most bug history.

### ✅ P3-10 · Persist SQLite with FULL Synchronous for execution_log
**File:** `execution_log.py`  
Change `PRAGMA synchronous=NORMAL` to `PRAGMA synchronous=FULL` for `execution_log.db`. This is the financial audit trail. The write volume is low enough that the performance cost is negligible. `tracker.db` and `predictions.db` can remain at NORMAL.

### ✅ P3-11 · Fix Backtest Brier Key Naming
**File:** `backtest.py`  
Rename `"brier"` key in the return dict to `"train_brier"`. Rename `"val_brier"` to remain `"val_brier"`. Add a guard: if `val_n < 10`, add a `"val_brier_unreliable": True` flag. This prevents callers from treating in-sample Brier as a generalization metric.

### P3-12 · Fix bias_models.pkl Training — Add Held-Out Evaluation
**File:** `ml_bias.py:train_bias_model`  
Before persisting the model, split the last 20% of data as hold-out. Train on first 80%. Only persist if hold-out Brier improves vs. uncorrected baseline by >0.005. Log the comparison.

### ✅ P3-13 · Consolidate Kelly Cap Constants
**Files:** `weather_markets.py`, `paper.py`  
Kelly cap is 0.33 in `weather_markets.py` and 0.25 in `paper.py`. The operative cap in production is 0.25. Decide one value, move it to `utils.py` as `KELLY_CAP: float = 0.25`, and use it in both places.

### P3-14 · Add Consistency Checks to Cron Path
**File:** `cron.py:_cmd_cron_body`, `consistency.py`  
Call `find_violations(markets)` after the market scan. Log all violations at WARNING level. Optionally add a threshold: if more than N violations exist, skip auto-trading for that cycle.

### ✅ P3-15 · SQLite WAL Checkpoint and Cleanup Strategy
**File:** `cron.py` (end of cron run)  
At the end of each cron run, checkpoint the WAL:
```python
with tracker_conn() as conn:
    conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
```
This prevents the WAL from growing unboundedly between runs.

---

## Phase 4 — Low Priority

### P4-1 · Remove Dead Code: _require_auth Decorator
**File:** `web_app.py` — delete the decorator definition (now replaced by actual usage per P0-8)

### P4-2 · Remove Orphaned test_nbm.py
**File:** `tests/test_nbm.py` — `nbm.py` does not exist; this test is testing `nws.py:fetch_nbm_forecast`. Rename to `test_nbm_via_nws.py` or update imports.

### P4-3 · Fix MarketDict TypedDict total=False
**File:** `market_types.py` — split into required base + optional enriched fields

### P4-4 · Fix _confidence_boost Dead Assignment
**File:** `weather_markets.py:analyze_trade:4074` — remove the first `_confidence_boost = 1.0` assignment that is immediately overwritten

### P4-5 · Fix METAR station_bias Placeholder
**File:** `metar.py:get_station_bias` — either implement or delete; document clearly as stub

### P4-6 · Fix Dead get_recent_api_latency_ms Stub
**File:** `execution_log.py:get_recent_api_latency_ms` — either add `latency_ms` column to schema and populate, or delete the stub

### P4-7 · Fix test_trade_improvements.py Source-Text Search
**File:** `tests/test_trade_improvements.py` — replace text-search test with a behavioral test:
```python
def test_ensemble_member_threshold():
    """Verify that â‰¥2 ensemble members are required for high confidence."""
    # Feed analyze_trade a forecast with 1 member — verify confidence is lowered
    # Feed with 2+ members — verify confidence can be full
```

### P4-8 · Fix Anomaly Notification Dead Letter
**File:** `notify.py:alert_strong_signal` — on all-channels-failed, write to `data/.undelivered_alerts.jsonl` for operator review

### P4-9 · Fix Signals Cache Atomic Write
**File:** `cron.py:_cmd_cron_body:675` — replace `open(w)` with `atomic_write_json()`

### P4-10 · Document and Test KALSHI_ENV Safety
Add a startup log banner and env-validation test that asserts `KALSHI_ENV` is one of `{"demo", "prod"}` and that the `--live` flag can only be used when `KALSHI_ENV=prod`.

---

## Quick Wins

Issues that can be fully fixed in under 2 hours, ordered by financial impact:

| # | Issue | File | Time | Impact |
|---|-------|------|------|--------|
| 1 | Cron lock fail-open â†’ fail-closed | `cron.py:122` | 10 min | Eliminates simultaneous process risk |
| 2 | Wire `is_accuracy_halted()` | `main.py` + `trading_gates.py` | 20 min | SPRT halt finally works |
| 3 | Fix conftest past date | `tests/conftest.py` | 5 min | Tests stop lying |
| 4 | Add `fee_rate=KALSHI_FEE_RATE` to all call sites | `weather_markets.py` | 30 min | Correct kelly sizing |
| 5 | `atomic_write_json` raise on %TEMP% fallback | `safe_io.py:93` | 10 min | No more silent write failures |
| 6 | Kill switch check inside analysis loop | `cron.py` | 15 min | Emergency halt actually halts |
| 7 | Require DASHBOARD_PASSWORD in prod | `config.py` | 10 min | Dashboard not open by default |
| 8 | Log warning when PAPER_MIN_EDGE from file | `config.py` | 5 min | Operator knows threshold source |
| 9 | Fix `is_streak_paused` sort field | `paper.py:1434` | 5 min | Correct streak detection |
| 10 | Fix WebSocket: subscribe or remove | `cron.py:422` | 15 min | No phantom connections |
| 11 | Add UTC startup banner for prod | `main.py`, `cron.py` | 10 min | Visible when trading live |
| 12 | Fix Minneapolis weights to equal | `data/city_weights.json` | 5 min | Stops inverted signal |

---

## Testing Strategy

### Immediately Required

1. **Fix regression baseline generation:** Create `tests/generate_baseline.py` that runs on a known-good commit and writes `tests/fixtures/regression_baseline.json`. Make `pytest.fail()` (not skip) when baseline is absent.

2. **Add NO-side P&L test:**
```python
def test_no_side_pnl_settlement():
    """Regression test for the formula inversion bug."""
    trade = place_paper_order("XTEST", "no", 100, 0.40)
    settle_paper_trade(trade["id"], "yes")  # YES wins, NO loses
    settled = get_settled_trades()[-1]
    expected_pnl = -100 * 0.40  # lose what was paid
    assert abs(settled["pnl"] - expected_pnl) < 0.01
```

3. **Add graduation gate enforcement test:**
```python
def test_live_order_blocked_without_graduation(mock_kalshi_client):
    """_place_live_order must raise when graduation criteria not met."""
    # 0 settled trades, 0 profit, Brier=None
    with pytest.raises(RuntimeError, match="Graduation"):
        _place_live_order(mock_market, "yes", 1, 0.50)
```

4. **Add circuit breaker persistence test:**
```python
def test_circuit_breaker_persists_across_invocations(tmp_path):
    """CB state must survive process restart."""
    cb = CircuitBreaker("test", failure_threshold=3, persist=True, state_path=tmp_path)
    cb.record_failure()
    cb.record_failure()
    # Simulate new process
    cb2 = CircuitBreaker("test", failure_threshold=3, persist=True, state_path=tmp_path)
    assert cb2._failure_count == 2  # state loaded from disk
```

5. **Add METAR staleness test:**
```python
def test_metar_stale_obs_not_locked_in():
    """METAR observations older than 90 minutes must not trigger lock-in."""
    old_obs_time = datetime.now(UTC) - timedelta(minutes=95)
    result = fetch_metar("KORD", force_obs_time=old_obs_time)
    assert result is None  # must be rejected
```

### Coverage Gaps to Close

- Fee rate wiring at production call sites
- Cron lock stale-override recovery path
- `CorruptionError` halt behavior (does it halt all trades or just return None?)
- Drawdown halt blocks live path AND paper path independently
- Graduation gate re-checked on every cron run (not only at startup)
- `atomic_write_json` raises (not silently falls back) on all-retries-exhausted
- `is_accuracy_halted` integration into `_auto_place_trades`

---

## Graduation Readiness Criteria

**The system is NOT ready for live trading as of 2026-05-07.**

### Gate 1 — P0 Issues (all 10 must be resolved and deployed)
- [ ] P0-1: NO-side P&L formula corrected, historical data migrated
- [ ] P0-2: Graduation gate enforced in `_place_live_order` via `trading_gates.py`
- [ ] P0-3: Micro-live disabled or fully gated
- [ ] P0-4: Idempotency key implemented, POST removed from auto-retry
- [ ] P0-5: Cron lock fails closed, PID-aware stale detection
- [ ] P0-6: Execution log written before live order placement
- [ ] P0-7: `STARTING_BALANCE` configurable, set to actual funded amount
- [ ] P0-8: Dashboard API endpoints authenticated
- [ ] P0-9: `bias_models.pkl` loads with HMAC verification
- [ ] P0-10: Paper trade execution log write-ordering fixed

### Gate 2 — Performance Criteria (computed from corrected P&L data)
- [ ] â‰¥ 30 settled paper trades (does not count until P0-1 migration complete)
- [ ] Cumulative paper P&L â‰¥ $50.00 (on corrected history)
- [ ] Brier score â‰¤ 0.20 on corrected history
- [ ] Win rate â‰¥ 52% over last 30 settled trades

### Gate 3 — Calibration (P1 issues required before scaling live)
- [ ] All 15 traded cities have city-specific calibration weights
- [ ] All 4 seasons present in `seasonal_weights.json`
- [ ] All 3 condition types present in `condition_weights.json`
- [ ] `learned_correlations.json` regenerated and PSD-validated
- [ ] Circuit breakers persisting state between runs

### Gate 4 — Safety Architecture (minimum architecture for live)
- [ ] `is_accuracy_halted()` wired into trading path
- [ ] STARTING_BALANCE set to actual funded amount in .env
- [ ] `data_fetched_at` uses original cache fetch timestamp
- [ ] METAR staleness gate active (reject obs > 90 min old)

### Recommended First Live Trade Parameters
After all 4 gates pass:
- Start with `MICRO_LIVE_FRACTION=0.1` on a single city you have highest confidence in (not Minneapolis)
- Set `MAX_TRADE_DOLLARS=10` for the first 10 live trades
- Review daily P&L vs paper P&L for consistency before scaling
- Do not increase position size until 10 live trades settle without incident

---

## Cross-Module Interaction Chains

These are the most dangerous failure combinations — fixing any single component does not fully resolve the risk:

| Chain | Components | Combined Risk |
|-------|-----------|---------------|
| Duplicate Order Cascade | A1+A2+B6+IO2 | 4× position on any I/O hiccup; undetectable by dedup |
| VaR Gate Permanent Failure | ML4+DATA3+IO2 | VaR estimates wrong since correlations file missing; gate passes trades it should block |
| Accuracy Halt Unwired | B8+DATA1 | SPRT halt does nothing; only the separate Brier retirement mechanism fires |
| Stale Forecast Appearing Fresh | A6+FS1+FS7 | 4-hour-old METAR with fabricated timestamp appears current to every freshness check |
| P&L Inversion Corrupts All Limits | B1+B9 | NO-side P&L wrong × STARTING_BALANCE hardcoded = all safety limits miscalibrated |
| Triple Weight Default | FS3+DATA8+FS11 | Most markets in most seasons use entirely uncalibrated defaults simultaneously |
| Circuit Breaker Illusion | IO2+IO3+A4+A8+A9 | Five independent flaws; circuit breakers are decorative in production deployment |
| DB Graduation Impossibility | FIND-1+FIND-2 | Schema version mismatch â†’ no predictions logged; sync_outcomes crash â†’ no outcomes recorded; Brier denominator is always 0; graduation can never be reached regardless of trading performance |
| NO Trade Total Suppression | ISSUE-4+P0-1 | entry_side_edge sign inverted â†’ valid NO trades blocked at gate; even if placed, settlement P&L formula also inverted; NO-side is effectively disabled end-to-end |
| Calibration File Self-Destruct | N-01+P1-1 | cleanup_data_dir deletes calibration files after 2 days; data_fetched_at bug makes rebuilding forecasts use stale data; system regresses to hardcoded defaults silently every 48 hours |
| Anomaly Halt Phantom | E-ISSUE-3+E-ISSUE-4+E-ISSUE-5 | anomaly check return value discarded; even if not discarded, win/loss checks use wrong side; alerts fire on the wrong signal direction and halt on good performance |

---

## Phase 0 — New P0 Blockers (Deep Pass)

**These 5 issues were found by the second audit pass and must be resolved alongside P0-1 through P0-11.**

---

### ✅ P0-12 · Fix `_SCHEMA_VERSION` Mismatch — No Predictions Ever Written to DB
**File:** `tracker.py:25`  
**Severity:** Critical — graduation is impossible; Brier score denominator is always 0  
**Effort:** 5 minutes (code change) + migration verification

**Root cause:** `_SCHEMA_VERSION = 18` but `_MIGRATIONS` contains 19 entries. Migration index 18 (v19: `ADD COLUMN local_hour`) is never applied because the version guard checks `version <= current` where `current=18`. Every `log_prediction()` call raises `sqlite3.OperationalError: table predictions has no column named local_hour`, which is swallowed silently. **No prediction records have accumulated since this column was added.** The system appears to be trading but the DB that drives Brier scores, Kelly multipliers, and the graduation gate is empty.

**Fix:**
```python
# tracker.py line 25
_SCHEMA_VERSION = 19  # was 18 — must match len(_MIGRATIONS)
```

After deploying: run `python -c "from tracker import init_db; init_db()"` and verify `PRAGMA user_version` returns 19, then verify `SELECT COUNT(*) FROM predictions` is non-zero after the next cron cycle.

---

### ✅ P0-13 · Fix `sync_outcomes` Aware/Naive Datetime Crash — No Outcomes Ever Auto-Settled
**File:** `tracker.py:~line 1305`  
**Severity:** Critical — all trades permanently stuck as "open"; settlement never auto-processes  
**Effort:** 15 minutes

**Root cause:** `now_utc = datetime.now(UTC)` is timezone-aware. `close_dt` is parsed then stripped: `.replace(tzinfo=None)`. Line 1308 computes `now_utc - close_dt` — subtracting naive from aware raises `TypeError`. The `except Exception` swallows it. **No outcomes have ever been written automatically.** All 272 "settled" trades in `paper_trades.json` were manually settled or settled via a different code path; the auto-settlement monitor has never functioned.

**Fix:**
```python
# tracker.py ~line 1305 — remove .replace(tzinfo=None)
close_dt = datetime.fromisoformat(
    close_time_str.replace("Z", "+00:00")
)
# Both close_dt and now_utc are now timezone-aware — subtraction works
hours_since = (now_utc - close_dt).total_seconds() / 3600
```

**Verification:** After fix, run `sync_outcomes()` manually and confirm `SELECT COUNT(*) FROM outcomes` increases.

---

### ✅ P0-14 · Fix NO-side `entry_side_edge` Sign Inversion — All Valid NO Trades Blocked at Gate
**File:** `weather_markets.py:analyze_trade` (~line 4231), `_analyze_precip_trade` (~line 3047), `_analyze_snow_trade` (~line 3202)  
**Severity:** Critical — valid NO trades compute negative edge and are blocked by `>= PAPER_MIN_EDGE` gate  
**Effort:** 1 hour

**Root cause:** For a NO recommendation with `blended_prob=0.35` and `yes_bid=0.55`:
- NO entry price = `1 - yes_bid = 0.45`
- Correct NO edge = `(1 - 0.35) - 0.45 = +0.20`
- Code computes: `entry_side_edge = blended_prob - entry_side_market_prob = 0.35 - 0.45 = -0.10`

The sign is inverted. Every NO trade with real positive edge appears to have negative edge and is blocked. This is **distinct from P0-1** (which is the settlement formula bug) — this bug affects trade *placement*, not settlement.

**Fix:**
```python
# weather_markets.py:analyze_trade — replace entry_side_edge calculation
if rec_side == "yes":
    entry_side_edge = (blended_prob - entry_side_market_prob) * _time_decay_factor
else:  # "no"
    # NO edge = P(NO wins) - cost_of_NO = (1 - blended_prob) - (1 - yes_bid)
    entry_side_edge = (1.0 - blended_prob - entry_side_market_prob) * _time_decay_factor
```

Apply the same fix to `_analyze_precip_trade` and `_analyze_snow_trade` — both have `entry_side_edge = blended_prob - _esmp` which has the same sign inversion for NO recommendations.

---

### ✅ P0-15 · Fix `cleanup_data_dir` — Calibration Files Deleted After 2 Days
**File:** `main.py:cleanup_data_dir` (~line 304)  
**Severity:** Critical — all calibration weight files silently deleted every 48 hours; system regresses to hardcoded defaults with no alert  
**Effort:** 15 minutes

**Root cause:** `cleanup_data_dir()` deletes every `data/*.json` older than 2 days, protecting only files starting with `"climate_"` or `"."`. It does not protect `seasonal_weights.json`, `city_weights.json`, `condition_weights.json`, `walk_forward_params.json`, `platt_models.json`, or `live_config.json`. These are updated only when explicit calibration commands run — not every cycle. On day 3 after calibration they are silently deleted.

**Fix:**
```python
# main.py:cleanup_data_dir
_PERMANENT_DATA_FILES = {
    "paper_trades.json",
    "seasonal_weights.json",
    "city_weights.json",
    "condition_weights.json",
    "walk_forward_params.json",
    "platt_models.json",
    "live_config.json",
    "retired_strategies.json",
    "learned_weights.json",
    "learned_correlations.json",
}

def cleanup_data_dir() -> None:
    data_dir = Path(__file__).parent / "data"
    if not data_dir.exists():
        return
    cutoff = _time.time() - 2 * 24 * 3600
    for f in data_dir.glob("*.json"):
        if f.name.startswith("climate_") or f.name.startswith("."):
            continue
        if f.name in _PERMANENT_DATA_FILES:   # â† NEW GUARD
            continue
        if f.stat().st_mtime < cutoff:
            _log.info("cleanup_data_dir: removing %s", f.name)
            f.unlink()
```

---

### ✅ P0-16 · Fix `api_run_cron` Web Endpoint — Unauthenticated + No Concurrent Guard = Duplicate Orders
**File:** `web_app.py:api_run_cron` (~line 654)  
**Severity:** Critical — any HTTP request to `/api/run_cron` triggers a full trading cycle; no auth, no lock check  
**Effort:** 1 hour

**Root cause:** The `/api/run_cron` endpoint requires no authentication (P0-8 covers dashboard auth but `_require_auth` is applied to zero routes). More critically, it has no concurrent-run guard — if cron is already running (from the scheduler), a second call starts a parallel cron cycle. Both cycles scan and analyze the same markets, and both can place orders for the same ticker in the same cycle window, bypassing the `was_traded_today` dedup (which checks the DB, but the first cycle may not have written yet).

**Fix:**
```python
# web_app.py:api_run_cron
@_app.route("/api/run_cron", methods=["POST"])
@_require_auth   # apply auth decorator (requires P0-8 auth fix)
def api_run_cron():
    from cron import _acquire_cron_lock, _release_cron_lock   # after P0-5 fix
    if not _acquire_cron_lock():
        return jsonify({"error": "cron already running"}), 409
    try:
        result = _run_cron_cycle(_client)
    finally:
        _release_cron_lock()
    return jsonify(result)
```

---

## Phase 1 — New P1 Issues (Deep Pass)

---

### ✅ P1-13 · Fix `sync_outcomes` Date Handling — `was_traded_today` Includes Failed Orders
**File:** `execution_log.py:was_traded_today` (~line 191)  
**Severity:** High — API timeout permanently blacklists a ticker for the rest of the calendar day  
**Effort:** 5 minutes

**Root cause:** `was_traded_today` has no `AND status != 'failed'` filter. `was_recently_ordered` (line 178) correctly excludes failures. A single API timeout logs a `status='failed'` order, after which `was_traded_today` returns `True` and the market is never retried — even though no position was established.

**Fix:**
```python
# execution_log.py:was_traded_today
row = con.execute(
    "SELECT 1 FROM orders WHERE ticker=? AND side=? AND placed_at LIKE ? "
    "AND status != 'failed' LIMIT 1",
    (ticker, side, f"{today}%"),
).fetchone()
```

---

### ✅ P1-14 · Fix Alerts Win/Loss Side Confusion — All Alert Thresholds Wrong for NO Trades
**File:** `alerts.py:~line 222, 246`  
**Severity:** High — win-rate and consecutive-loss alerts fire on wrong signal direction for NO-side trades  
**Effort:** 1 hour

**Root cause:** The win-rate check counts `outcome == "yes"` as a win regardless of trade side. For a NO trade that wins (outcome=NO, i.e., settled_yes=False), this registers as a loss. The consecutive-loss check has the same inversion. Every alert threshold is meaningless for a portfolio with NO-side positions — and this system places significant NO-side volume.

**Fix:**
```python
# alerts.py — correct win determination
def _trade_won(trade: dict) -> bool:
    """Returns True if the trade was profitable regardless of side."""
    side = trade.get("side", "yes")
    outcome = trade.get("outcome", "")  # "yes" or "no" (which side won)
    if side == "yes":
        return outcome == "yes"
    else:  # side == "no"
        return outcome == "no"
```

Apply `_trade_won(t)` in both the win-rate check and consecutive-loss check throughout `alerts.py`.

---

### ✅ P1-15 · Fix `run_anomaly_check` Return Value Discarded in `cron.py`
**File:** `cron.py:~line 354`  
**Severity:** High — anomaly detection fires but trading is never halted; return value silently dropped  
**Effort:** 30 minutes

**Root cause:** `cron.py` calls `run_anomaly_check()` but discards the return value. Even if `run_anomaly_check` returns a list of anomalies that should halt trading, nothing downstream uses that result. Anomaly detection is purely cosmetic — it logs and returns, but trading continues.

**Fix:**
```python
# cron.py — handle anomaly check result
_anomalies = run_anomaly_check(log_results=True)
if _anomalies:
    _blocking = [a for a in _anomalies if a.get("severity") == "critical"]
    if _blocking:
        _log.error("cmd_cron: critical anomalies detected — halting trade placement: %s",
                   [a.get("type") for a in _blocking])
        return  # abort this cron cycle before trade placement
```

---

### ✅ P1-16 · Fix Kill Switch File Write — Non-Atomic, Empty File on Crash Ignored
**File:** `web_app.py:~line 978`  
**Severity:** High — kill switch activation can result in empty file that is silently ignored  
**Effort:** 30 minutes

**Root cause:** The kill switch is activated by writing to a `.kill_switch` file. The write uses a plain `open(..., "w")` — not atomic. If the process crashes between file open and write, the file exists but is empty. The kill switch check reads the file and may treat an empty file as "not activated" depending on the check logic.

**Fix:** Use `safe_io.atomic_write_json` for the kill switch file, or use `Path.write_text` which is atomic on POSIX and sufficiently safe on Windows for a single-byte file:
```python
# web_app.py:activate_kill_switch
_KS_PATH.parent.mkdir(parents=True, exist_ok=True)
tmp = _KS_PATH.with_suffix(".tmp")
tmp.write_text(datetime.now(UTC).isoformat())
tmp.replace(_KS_PATH)  # atomic on Windows (os.replace semantics)
```

---

### ✅ P1-17 · Fix SPRT Hypothesis Gap — Halt Never Fires on Moderate Degradation
**File:** `tracker.py:sprt_model_health` (and `utils.py` constants)  
**Severity:** High — model degrading from 55% to 45% win rate never triggers SPRT halt  
**Effort:** 15 minutes

**Root cause:** `SPRT_P0=0.55`, `SPRT_P1=0.35`. The 20pp gap is so wide that the test only fires when win rate crashes to ~35% — by which time substantial losses have already accumulated. Additionally, the lower boundary (accept H0) is never checked, so the LLR accumulates forever and can fire spuriously on a healthy model given enough trades.

**Fix:**
```python
# utils.py
SPRT_P0: float = float(os.getenv("SPRT_P0", "0.55"))
SPRT_P1: float = float(os.getenv("SPRT_P1", "0.45"))   # was 0.35
SPRT_MIN_TRADES: int = int(os.getenv("SPRT_MIN_TRADES", "20"))  # was 5
```

```python
# tracker.py:sprt_model_health — add lower boundary check
lower = math.log(beta / (1 - alpha))
upper = math.log((1 - beta) / alpha)
if llr >= upper:
    return {"status": "degraded", ...}
elif llr <= lower:
    return {"status": "ok", "cleared": True, ...}
else:
    return {"status": "continue", ...}
```

---

### ✅ P1-18 · Fix `consistency.py` Arb Path — Bypasses All Halt Guards
**File:** `consistency.py` (arb/corrective trade path)  
**Severity:** High — corrective trades placed during drawdown halt, daily loss halt, or kill switch  
**Effort:** 1 hour

**Root cause:** The consistency check's arb/corrective trade path does not check `is_kill_switch_active()`, `is_drawdown_halted()`, `is_daily_loss_halted()`, or `is_accuracy_halted()` before placing corrective orders. A corrective trade placed during a drawdown halt contradicts the entire purpose of the halt.

**Fix:** Before any corrective order placement in `consistency.py`:
```python
from trading_gates import LiveTradingGate  # after P0-2 is implemented
gate = LiveTradingGate()
allowed, reason = gate.check()
if not allowed:
    _log.warning("consistency: skipping corrective trade — gate blocked: %s", reason)
    return
```

---

### ✅ P1-19 · Fix `get_markets` Pagination — Markets Beyond Page 1 Never Analyzed
**File:** `kalshi_client.py:get_markets` (~line 201)  
**Severity:** High — any Kalshi weather markets on page 2+ are permanently invisible  
**Effort:** 1 hour

**Root cause:** `get_markets()` makes one HTTP call and returns `data.get("markets", [])`. No cursor pagination loop. If Kalshi returns more markets than fit on a single page (default ~100), subsequent pages are silently dropped.

**Fix:**
```python
def get_markets(self, **params) -> list[dict]:
    all_markets: list[dict] = []
    cursor: str | None = None
    while True:
        p = dict(params)
        if cursor:
            p["cursor"] = cursor
        data = self._get("/markets", params=p or None, auth=True)
        self._validate(data, "markets", "/markets")
        page = data.get("markets", [])
        all_markets.extend(page)
        cursor = data.get("cursor")
        if not cursor:
            break
    return all_markets
```

---

### ✅ P1-20 · Fix `_check_early_exits` N×API Calls — Market Fetch Inside Per-Trade Loop
**File:** `main.py:_check_early_exits` (~line 2324)  
**Severity:** High — N open positions = N full API market fetches per cron cycle; triggers rate-limiting  
**Effort:** 30 minutes

**Root cause:** `get_weather_markets(client)` is called once per open position inside the loop. With 15 open positions, every cron run makes 15 unnecessary API calls, amplifying circuit breaker trip risk.

**Fix:**
```python
def _check_early_exits(client, open_trades, paper_mode):
    if not open_trades:
        return
    markets = get_weather_markets(client)          # fetch once before the loop
    markets_by_ticker = {m["ticker"]: m for m in markets}
    for trade in open_trades:
        market = markets_by_ticker.get(trade["ticker"])
        if market is None:
            continue
        # use `market` directly
```

---

## Phase 2 — New P2 Issues (Deep Pass)

### ✅ P2-21 · Fix METAR 0Â°F Threshold Bug — `condition.get("threshold")` Falsy for Zero
**File:** `weather_markets.py:_metar_lock_in` (~line 3303)  
**Root cause:** `if _cond_type in ("above", "below") and condition.get("threshold"):` — the truthiness check is False when `threshold == 0.0`. Freeze markets (above/below 0Â°F) silently skip METAR lock-in.  
**Fix:** `condition.get("threshold") is not None`

### ✅ P2-22 · Fix METAR Missing `obsTime` — Fabricated Timestamp Bypasses Staleness Gate
**File:** `metar.py:fetch_metar` (~line 99)  
**Root cause:** Missing or malformed `obsTime` replaced with `datetime.now(UTC)`, making stale observations appear fresh. The P1-2 staleness gate checks age from `obs_time` — but the fabricated timestamp always gives age=0.  
**Fix:** Return `None` when `obsTime` is absent or unparseable; never fabricate a timestamp.

### ✅ P2-23 · Fix METAR Lock-In Missing for 12 of 18 Cities
**File:** `weather_markets.py:_metar_station_for_city` (~line 200)  
**Root cause:** The internal `_MAP` in `weather_markets.py` only has 6 cities; `metar.py:MARKET_STATION_MAP` has 18. Merge them and populate `_CITY_TZ` for all 18.

### ✅ P2-24 · Fix `_confidence_scaled_blend_weights` — Negative Weights Possible Under High-Confidence Scaling
**File:** `weather_markets.py:_confidence_scaled_blend_weights` (~line 2451)  
**Root cause:** When `scale > 1` (tight ensemble spread), redistributing delta to `w_clim`/`w_nws` can make them go below zero.  
**Fix:** `w_clim_new = max(0.0, w_clim_new); w_nws_new = max(0.0, w_nws_new)` after redistribution.

### ✅ P2-25 · Fix `date.today()` in `nws.py`, `mos.py`, `tracker.py:log_prediction`
**File:** `nws.py:253`, `mos.py:111,144`, `tracker.py:430,441`  
**Root cause:** Local-clock date used where UTC date is required. Between midnight UTC and local midnight, `days_out` and predicted_date UPSERT key are off by 1.  
**Fix:** Replace all `date.today()` with `datetime.now(timezone.utc).date()` in these locations.

### ✅ P2-26 · Fix `clim_prior=0.30` Hardcoded in Precip/Snow Blend
**File:** `weather_markets.py:_analyze_precip_trade` (~line 2995), `_analyze_snow_trade` (~line 3165)  
**Root cause:** The hardcoded 30% prior ignores city/season — Miami summer is 60%+, Denver winter is 10%.  
**Fix:** Call `climatological_prob(city, coords, target_date, condition)` and fall back to 0.30 only on failure.

### ✅ P2-27 · Fix `sync_outcomes` and `log_prediction` UTC Date Inconsistency
**Covered by P2-25 above** — `log_prediction` uses `date.today()` for `predicted_date` UPSERT key.

### ✅ P2-28 · Fix `get_balance_history` — Settlement Events at Entry Timestamp, Not `settled_at`
**File:** `paper.py:get_balance_history` (~line 1804)  
**Root cause:** Settlement events are keyed to `entered_at` in the sort, so the P&L chart shows payouts at trade-entry time rather than settlement time. Drawdown curves appear shallower than reality.  
**Fix:** Emit settlement events using `settled_at` as the timestamp; re-sort history by `ts` after construction.

### ✅ P2-29 · Fix `export_tax_csv` — Filters by Entry Year Instead of Settlement Year
**File:** `paper.py:export_tax_csv` (~line 1762)  
**Root cause:** `date_str = t.get("entered_at")[:4]` — a December 2025 trade settling January 2026 appears in the wrong tax year.  
**Fix:** Use `t.get("settled_at") or t.get("entered_at")` for both the tax year filter and the "Date Sold" field.

### ✅ P2-30 · Fix `append_entry` Overwrites Instead of Appending
**File:** `execution_log.py:append_entry` (~line 433)  
**Root cause:** `atomic_write_json(entry, target)` replaces the file entirely. Every call loses all prior entries.  
**Fix:** Rename to `write_entry` to match behavior, or switch to JSONL append format.

### ✅ P2-31 · Fix Tier-4 Drawdown Boundary — Exactly 95% Recovery Gets 70% Kelly
**File:** `paper.py:drawdown_scaling_factor` (~line 352)  
**Root cause:** `if recovery <= _DRAWDOWN_TIER_4: return 0.70` — at exactly 0.95, returns 70% instead of 100%. Docstring says `> TIER_4 â†’ full sizing`.  
**Fix:** Change `<=` to `<` for the TIER_4 boundary check.

### ✅ P2-32 · Fix `covariance_kelly_scale` Uses `STARTING_BALANCE` Not `_exposure_denom()`
**File:** `paper.py:covariance_kelly_scale` (~line 1073)  
**Root cause:** Position weight `w_i = cost / STARTING_BALANCE` overstates weights when account grows above $1,000, making correlated Kelly reduction more aggressive than intended.  
**Fix:** `w_i = cost / max(_exposure_denom(), 1.0)`

### ✅ P2-33 · Fix `check_position_limits` and Ticker-Exposure Mixed-Denominator Bug
**File:** `paper.py:check_position_limits` (~line 2160), `paper.py:place_paper_order` (~line 526)  
**Root cause:** Two additional exposure checks (beyond P2-4) use `STARTING_BALANCE` as denominator instead of `_exposure_denom()`, causing premature limit triggers or bypasses as the account grows.  
**Fix:** Replace `STARTING_BALANCE` with `_exposure_denom()` in both locations.

### ✅ P2-34 · Fix HTTP 200 Error Body Treated as Success in `kalshi_client.py`
**File:** `kalshi_client.py:_get/_post/_delete` (~line 166)  
**Root cause:** `raise_for_status()` only raises on 4xx/5xx. Kalshi can return 200 with `{"error": "market_closed"}`. `place_order()` doesn't inspect for an error field.  
**Fix:** After `resp.json()`, check `if isinstance(data, dict) and "error" in data: raise ValueError(...)`.

### ✅ P2-35 · Fix ML Retrain Gate Checks Exact UTC Hour — Scheduled Runs Never Match
**File:** `cron.py:~line 1031`  
**Root cause:** Retrain fires only when `_now_dow == 6 and _now_hour == 2`. Cron runs at 08:15, 14:15, 20:15 UTC — never matches. Models are never retrained automatically.  
**Fix:** Use a `.last_ml_retrain` marker file and check if â‰¥6 days have elapsed since last retrain.

### ✅ P2-36 · Fix Degenerate Ensemble Detection — All-Identical Members Pass at Max Confidence
**File:** `weather_markets.py:ensemble_stats` (~line 1694)  
**Root cause:** `std=0.0` from all-identical ensemble members is treated as maximum confidence (same as `std=None`). A broken API returning 82 identical values goes undetected.  
**Fix:** Add `"degenerate": std == 0.0 and len(temps) > 5` to `ensemble_stats()` return; skip trade if degenerate.

### ✅ P2-37 · Fix `param_sweep.py` In-Sample Optimization Overwrites Live `PAPER_MIN_EDGE`
**File:** `param_sweep.py:run_sweep`  
**Root cause:** Sweep uses all historical data with no train/test split. Best threshold found is 100% in-sample. Result overwrites `walk_forward_params.json` which sets live `PAPER_MIN_EDGE`.  
**Fix:** Add 70/30 temporal split; only save result if validation win rate improves over holdout baseline.

### ✅ P2-38 · Fix `ForecastCache` Unbounded Growth
**File:** `forecast_cache.py:ForecastCache`  
**Root cause:** No size limit or proactive expiry sweep. All module-level caches (`_CONSENSUS_CACHE`, `_MAE_WEIGHTS_CACHE`, etc.) also grow without bound. Long-running process will eventually OOM.  
**Fix:** Add `max_size=500` LRU eviction and a `prune_expired()` method called from cron.

### ✅ P2-39 · Fix `_blend_probabilities` Bypasses Calibration System
**File:** `weather_markets.py:_blend_probabilities` (~line 2501)  
**Root cause:** Standalone function uses hardcoded weights instead of calling `_blend_weights()`. Any caller routing through here ignores all calibration.  
**Fix:** Delete the function or refactor it to delegate to `_blend_weights()`.

### ✅ P2-40 · Fix SPRT — Add Lower Boundary and Minimum Sample Check
**Covered by P1-17 above.**

### ✅ P2-41 · Fix `_SCHEMA_VERSION` Migration Comment Numbering Off by 2
**File:** `tracker.py:~line 70`  
**Root cause:** Three `ALTER TABLE` statements labeled `# v8 â†’ v9` but occupy three separate version slots. All migration comments from index 9 onward are mislabeled.  
**Fix:** Renumber all migration comments to match their actual `index + 1` version numbers.

### ✅ P2-42 · Fix `zip()` Truncation in `climatology.py` — Mismatched Archive List Lengths
**File:** `climatology.py:_climatological_prob_inner` (~line 140)  
**Root cause:** `zip(dates, highs, lows)` silently truncates to shortest list if API returns mismatched lengths. Years of data silently discarded.  
**Fix:** Check lengths before zip; log warning and use minimum if mismatched.

### ✅ P2-43 · Fix `KALSHI_ENV` Stale After `cmd_settings` Change
**File:** `main.py:204`  
**Root cause:** `KALSHI_ENV` read at import time; `cmd_settings` reloads `.env` but doesn't refresh the module-level constant. Client built after settings change still uses old env.  
**Fix:** Read `os.getenv("KALSHI_ENV", "demo")` at `build_client()` call time, not at import.

### ✅ P2-44 · Fix GBM Bias Model — No Holdout Validation Before Persisting
**File:** `ml_bias.py:train_bias_model`  
**Root cause:** 100 trees / depth-3 GBM on 200 samples, no holdout. Guaranteed overfit. Corrections can be in wrong direction.  
**Fix:** Reduce to 50 trees / depth-2 / `min_samples_leaf=10`. Add 80/20 holdout; skip save if holdout MSE â‰¥ no-correction baseline.

### ✅ P2-45 · Fix GBM + Platt Sequential Application — Compounding Corrections
**File:** `weather_markets.py:analyze_trade` (~line 4111)  
**Root cause:** Both GBM and Platt corrections applied sequentially with no guard. Compounding pushes probabilities to extremes.  
**Fix:** Apply only one correction per city; add post-correction clamp `max(0.01, min(0.99, blended_prob))`.

### ✅ P2-46 · Fix `A/B Test` — Exhaustion Uses Hardcoded 50 Ignoring Configured `max_trades`
**Covered by P3 recommendation to redesign A/B test — promote to P2:**  
**File:** `ab_test.py:get_active_variant` (~line 188)  
**Root cause:** `_DEFAULT_MAX_TRADES=50` used regardless of configured max. A 200-trade experiment stops at 50.  
**Fix:** Persist `max_trades_per_variant` in state `_meta` key; read it back in `get_active_variant`.

### ✅ P2-47 · Fix `restore_data()` — Silently Overwrites All Live Files Without Confirmation
**File:** `cloud_backup.py:restore_data` (~line 159)  
**Root cause:** `restore_data()` overwrites `paper_trades.json` and other live files with no pre-backup, no confirmation prompt, no dry-run mode.  
**Fix:** Require explicit `confirm=True` parameter; back up current files to a timestamped snapshot before restore.

---

## Phase 3 — New P3 Issues (Deep Pass)

### P3-16 · Fix `calibrate_condition_weights` Look-Ahead Bias (Separate from P3-1)
Same temporal isolation fix as P3-1 must be applied to `calibrate_condition_weights` — it uses full dataset, not covered by the existing P3-1 fix.

### P3-17 · Fix Calibration `None` Components — Silent Equal-Weight Fallback Corrupts Grid Search
**File:** `calibration.py:_brier`  
`None` forecast components during calibration trigger `TypeError`, which the grid search catches and ignores, silently returning the equal-weight fallback as the "best" result.  
**Fix:** Filter out rows with any `None` component before computing Brier.

### P3-18 · Fix `stratified_train_test_split` Dead Code in `backtest.py`
Defined but never called. Either use it in `run_backtest` for holdout stratification by city/condition, or remove it.

### ✅ P3-19 · Fix `hash(bytes)` Non-Deterministic in `backtest.py`
**File:** `backtest.py:fetch_archive_temps`  
`hash(target_str[:8].encode())` is PYTHONHASHSEED-randomised. Two runs of the same backtest produce different results.  
**Fix:** `int(hashlib.md5(target_str.encode()).hexdigest()[:8], 16)`

### ✅ P3-20 · Fix `correlation_applied` Flag Misleading When Cholesky Fails
**File:** `monte_carlo.py:simulate_portfolio`  
`correlation_applied = any(tp["city"] for tp in trade_params)` is set regardless of Cholesky success.  
**Fix:** `correlation_applied = chol is not None`

### ✅ P3-21 · Fix `_validate()` Warn-Only — Schema Change Returns Empty Market List
**File:** `kalshi_client.py:_validate`  
Silent `warnings.warn()` invisible in cron log. Schema change causes bot to see 0 markets with no alert.  
**Fix:** Replace `warnings.warn()` with `_log.error()` to ensure it appears in the log file.

### P3-22 · Fix `feature_importance.py` Log Unbounded Growth
Full-file read on every `get_feature_summary()` call will degrade performance and risk OOM after 1 year.  
**Fix:** Add `_MAX_LOG_LINES=50_000` pruning; call weekly from cron.

### P3-23 · Fix `pnl_distribution` Serialized Into Every Monte Carlo API Response
**File:** `monte_carlo.py:simulate_portfolio`  
1000-float list (~40KB) returned in every response. Gate behind a flag.

### P3-24 · Fix `backtest.py` Survivorship Bias — Only Traded+Settled Markets in Brier
Include all analyzed (not just traded) markets in Brier calculation by logging predictions regardless of trading decision.

### P3-25 · Fix `_calibration_CITY_MIN=15` — Statistically Meaningless Sample Size
SE at 15 samples â‰ˆ 0.13. Any weight triple within noise is "optimal." Raise to 50.

---

## Phase 4 — New P4 Issues (Deep Pass)

### P4-11 · Fix `safe_io.py` Fallback Write Non-Atomic
Fallback path uses plain `open(..., "w")` instead of temp-then-replace.

### P4-12 · Fix `AtomicWriteError` Defined But `RuntimeError` Raised
Callers catching `AtomicWriteError` will never catch the actual raised exception.

### P4-13 · Fix Predictable Temp File Names — Cross-Process Collision Risk
`{path.name}_{attempt}.tmp` is deterministic. Add `os.getpid()` + UUID fragment.

### P4-14 · Fix Private Key Not Refreshed on Key Rotation
Add `client.reload_key()` method and call it from `cmd_settings` after key update.

### P4-15 · Add Log Rotation With 7 Backups
Current rotation keeps only 1 backup file. Use `RotatingFileHandler(backupCount=7)`.

### P4-16 · Fix `basicConfig` Not Called in Production Mode
Without `--debug`, log records are unformatted and INFO is silently dropped.

### P4-17 · Fix `.cron_last_run` Written With Local Time, Not UTC
`datetime.now()` â†’ `datetime.now(UTC)`.

### P4-18 · Fix `auto_backup` Uses `date.today()` (local) for Filename
DST transition can cause double-backup or missed-backup for the same UTC date.

### P4-19 · Fix `is_open()` Side Effect in `circuit_breaker.py`
OPENâ†’HALF-OPEN transition inside a read-only query method; two concurrent callers both get `False`.

### P4-20 · Fix `FlashCrashCB` Uses `time.time()` Not `time.monotonic()`
NTP clock adjustment can create false flash-crash triggers or extend detection window.

---

## Updated Graduation Readiness Criteria

**Gate 1 — P0 Issues (all 16 must be resolved)**
- [ ] P0-1 through P0-11 (original)
- [ ] P0-12: `_SCHEMA_VERSION=19`, predictions logging confirmed
- [ ] P0-13: `sync_outcomes` datetime fix, auto-settlement confirmed
- [ ] P0-14: NO-side `entry_side_edge` sign fixed in all 3 analysis functions
- [ ] P0-15: `cleanup_data_dir` permanent-file whitelist added
- [ ] P0-16: `api_run_cron` authenticated and concurrent-run guarded

**Gate 2 — Performance Criteria** (unchanged — but note: Gate 2 was unreachable before P0-12/P0-13 fixes)

**Gate 3 — Calibration** (unchanged)

**Gate 4 — Safety Architecture**
- [ ] All original Gate 4 items
- [ ] `run_anomaly_check` return value handled in `cron.py` (P1-15)
- [ ] `consistency.py` corrective trades check halt guards (P1-18)
- [ ] Alerts win/loss side logic corrected (P1-14)
- [ ] `calibration_condition_weights` temporal isolation (P3-16)

