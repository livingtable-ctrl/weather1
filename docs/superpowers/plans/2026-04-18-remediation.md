# Code Review Remediation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Address all weaknesses found in the 2026-04-18 full program review — prioritised by risk to capital and system stability.

**Architecture:** Seven phases. Phase 0 fixes a critical pre-existing bug in the drawdown logic that Phase 2 would otherwise make worse. Phases 1–4 are the original plan. Phases 5–7 add what was missing for an A grade: security hardening, risk hardening II, and architecture refactoring.

**Tech Stack:** Python 3.12, pytest, SQLite (WAL), Flask, asyncio/websockets, mypy, ruff

---

## Confirmed Non-Issues (do not write code for these)

- **SQL injection:** All production queries use `?` parameterization.
- **STOP_LOSS_MULT dead code:** Fully wired at `main.py:2628`.
- **Micro-live daily cap:** `execution_log.daily_live_loss` + `daily_loss_limit=200` enforced at `main.py:1550`.
- **Rate limiter race:** `_om_rate_limit()` reads and writes inside the lock.
- **Kelly negative edge:** `max(0.0, full_kelly/2)` at `weather_markets.py:2589`.
- **ruff not in CI:** `ci.yml` already runs `ruff check .` on every push.
- **mypy not in CI:** `ci.yml` already runs `mypy . --ignore-missing-imports`.
- **`_env_float` silent fallback:** `paper.py`'s `_env_float` logs a WARNING on bad values. `utils.py` uses `float(os.getenv())` directly — bad values raise `ValueError` at import (fail-fast, acceptable).

## Confirmed New Findings (not in original review)

- **`_DRAWDOWN_TIER_*` constants are dead code.** `drawdown_scaling_factor()` at `paper.py:317` uses hardcoded literals `0.60`, `0.80`, `0.90` — it never references the tier constants defined at lines 107–110. Phase 2 Task 5 changes the env var default but will have NO effect on actual halt behavior until the function is rewritten. **Phase 0 fixes this first.**
- **`drawdown_scaling_factor()` docstring is wrong.** It documents `≤60% → paused` but `_DRAWDOWN_TIER_1 = 0.50` says halt should be at 50%. The function wins; the constant is ignored.

---

## Quick Reference: What Was Reviewed as Wrong That Turned Out Fine

Before writing code, confirm these are NOT issues:
- **SQL injection:** All production queries use `?` parameterization. No fix needed.
- **STOP_LOSS_MULT dead code:** `check_stop_losses()` is fully wired at `main.py:2628`. No fix needed.
- **Micro-live daily cap:** `execution_log.daily_live_loss` + `daily_loss_limit=200` in `_LIVE_CONFIG_DEFAULT` is enforced at `main.py:1550`. No fix needed.
- **Rate limiter race:** `_om_rate_limit()` in `weather_markets.py` reads and writes `_OM_LAST_REQUEST_TS` inside the lock. No fix needed.
- **Kelly negative edge:** `max(0.0, full_kelly/2)` at `weather_markets.py:2589`. No fix needed.

---

## Phase 1 — Data Integrity & Safety Gates

**Acceptance criteria:** `pytest` passes in CI with 0 failures; no regressions.

---

### Task 1: Fix pre-existing failing test

**Root cause:** `mock_balance_1000` fixture in `tests/conftest.py` patches `paper.DATA_PATH` before `importlib.reload(paper)`, but the reload re-executes `DATA_PATH = _project_root() / "data" / "paper_trades.json"`, silently overwriting the patch. The test then reads the real `data/paper_trades.json` (balance ≈ $2166 from live usage), pushes pre-multiplier dollars above the $500 cap, and the proportional assertion fails.

**Files:**
- Modify: `tests/test_paper.py:896-907`

- [ ] **Step 1: Reproduce the failure**

```bash
pytest tests/test_paper.py::test_kelly_bet_dollars_method_scaling_reduces_kelly -v
```
Expected: `FAILED — assert 31.19 < 0.02`

- [ ] **Step 2: Add the two missing mocks inside the test**

In `tests/test_paper.py`, replace lines 896–907:

```python
def test_kelly_bet_dollars_method_scaling_reduces_kelly(mock_balance_1000, monkeypatch):
    """Poor-performing method (Brier > 0.20) reduces Kelly by 25%."""
    import paper

    # Patch DATA_PATH again after reload (fixture patching is overwritten by reload)
    monkeypatch.setattr(paper, "DATA_PATH", mock_balance_1000.DATA_PATH)
    monkeypatch.setattr(paper, "drawdown_scaling_factor", lambda: 1.0)
    monkeypatch.setattr(paper, "is_streak_paused", lambda: False)
    monkeypatch.setattr(paper, "_dynamic_kelly_cap", lambda: 500.0)
    monkeypatch.setattr(paper, "_method_kelly_multiplier", lambda m: 0.75 if m else 1.0)

    base = paper.kelly_bet_dollars(0.5)    # method=None  → multiplier=1.0
    scaled = paper.kelly_bet_dollars(0.5, method="normal_dist")  # multiplier=0.75

    # With balance=1000, scale=1.0: fraction=0.25, dollars=250.0 (well under $500 cap)
    assert scaled < base
    assert abs(scaled - base * 0.75) < 0.02
```

- [ ] **Step 3: Run to verify pass**

```bash
pytest tests/test_paper.py::test_kelly_bet_dollars_method_scaling_reduces_kelly -v
```
Expected: `PASSED`

- [ ] **Step 4: Run full suite to confirm no regressions**

```bash
pytest --tb=short -q
```
Expected: all previously-passing tests still pass, now 0 failing.

- [ ] **Step 5: Commit**

```bash
git add tests/test_paper.py
git commit -m "fix(tests): isolate kelly_bet_dollars test from real paper_trades balance"
```

---

### Task 2: Gate `_dynamic_kelly_cap` behind minimum settled-trade count

**Problem:** `_dynamic_kelly_cap()` in `paper.py:340` calls `brier_score()` with no minimum sample guard. With 5 "lucky" wins, `brier_score()` returns 0.006 → cap jumps to $500/trade. This is statistically meaningless and inflates bet sizes prematurely. Same problem in `_method_kelly_multiplier` which uses `min_samples=5`.

**Files:**
- Modify: `paper.py:340-374`
- Modify: `utils.py` (add constant)
- Test: `tests/test_paper.py`

- [ ] **Step 1: Add `MIN_BRIER_SAMPLES` constant to `utils.py`**

In `utils.py`, after the `BRIER_ALERT_THRESHOLD` line (~line 94), add:

```python
# Minimum settled predictions required before Brier score is used to scale bet size.
# Below this count the Brier is statistically unreliable (small-sample luck).
MIN_BRIER_SAMPLES: int = int(os.getenv("MIN_BRIER_SAMPLES", "30"))
```

- [ ] **Step 2: Write the failing tests first**

In `tests/test_paper.py`, add after the existing `_dynamic_kelly_cap` tests:

```python
class TestDynamicKellyCapMinSamples:
    def test_cap_returns_conservative_when_too_few_samples(self, monkeypatch):
        """_dynamic_kelly_cap returns $50 (conservative) when < MIN_BRIER_SAMPLES settled."""
        import paper
        import tracker

        monkeypatch.setattr(tracker, "brier_score", lambda: 0.006)
        monkeypatch.setattr(tracker, "count_settled_predictions", lambda: 5)
        assert paper._dynamic_kelly_cap() == 50.0

    def test_cap_uses_brier_when_enough_samples(self, monkeypatch):
        """_dynamic_kelly_cap uses Brier scaling when >= MIN_BRIER_SAMPLES settled."""
        import paper
        import tracker

        monkeypatch.setattr(tracker, "brier_score", lambda: 0.04)
        monkeypatch.setattr(tracker, "count_settled_predictions", lambda: 30)
        assert paper._dynamic_kelly_cap() == 500.0

    def test_method_multiplier_returns_neutral_when_too_few_samples(self, monkeypatch):
        """_method_kelly_multiplier returns 1.0 when < MIN_BRIER_SAMPLES settled."""
        import paper
        import tracker

        monkeypatch.setattr(tracker, "brier_score_by_method", lambda min_samples: {"ensemble": 0.25})
        monkeypatch.setattr(tracker, "count_settled_predictions", lambda: 5)
        assert paper._method_kelly_multiplier("ensemble") == 1.0
```

- [ ] **Step 3: Run to verify failure**

```bash
pytest tests/test_paper.py::TestDynamicKellyCapMinSamples -v
```
Expected: `FAILED` (functions don't check count yet)

- [ ] **Step 4: Add `count_settled_predictions` to `tracker.py`**

In `tracker.py`, after the `brier_score` function, add:

```python
def count_settled_predictions() -> int:
    """Return the number of predictions with a known outcome."""
    init_db()
    with _conn() as con:
        row = con.execute(
            "SELECT COUNT(*) FROM predictions p "
            "JOIN outcomes o ON p.ticker = o.ticker"
        ).fetchone()
    return row[0] if row else 0
```

- [ ] **Step 5: Update `_dynamic_kelly_cap` in `paper.py:340`**

Replace the existing function:

```python
def _dynamic_kelly_cap() -> float:
    """Determine STRONG-tier per-trade cap from current Brier score.

    Returns a conservative $50 cap when fewer than MIN_BRIER_SAMPLES predictions
    have settled — Brier is unreliable on small samples.
    """
    from utils import MIN_BRIER_SAMPLES

    try:
        from tracker import brier_score as _brier
        from tracker import count_settled_predictions as _count

        if _count() < MIN_BRIER_SAMPLES:
            return 50.0  # conservative until we have real data
        score = _brier()
        if score is None:
            return 200.0
        if score <= 0.05:
            return 500.0
        if score <= 0.10:
            return 400.0
        if score <= 0.15:
            return 300.0
        return 200.0
    except Exception:
        return 50.0
```

- [ ] **Step 6: Update `_method_kelly_multiplier` in `paper.py:359`**

Replace the existing function:

```python
def _method_kelly_multiplier(method: str | None) -> float:
    """Scale Kelly by per-method Brier. Poor method (Brier > 0.20) → 0.75×.

    Returns 1.0 (neutral) when fewer than MIN_BRIER_SAMPLES predictions have settled.
    """
    if not method:
        return 1.0
    from utils import MIN_BRIER_SAMPLES

    try:
        from tracker import brier_score_by_method as _by_method
        from tracker import count_settled_predictions as _count

        if _count() < MIN_BRIER_SAMPLES:
            return 1.0
        scores = _by_method(min_samples=5)
        if method not in scores:
            return 1.0
        brier = scores[method]
        if brier > 0.20:
            return 0.75
        return 1.0
    except Exception:
        return 1.0
```

- [ ] **Step 7: Run tests to verify pass**

```bash
pytest tests/test_paper.py::TestDynamicKellyCapMinSamples -v
```
Expected: `3 passed`

- [ ] **Step 8: Run full suite**

```bash
pytest --tb=short -q
```

- [ ] **Step 9: Commit**

```bash
git add paper.py tracker.py utils.py tests/test_paper.py
git commit -m "feat: gate Brier-based Kelly scaling behind MIN_BRIER_SAMPLES=30 threshold"
```

---

### Task 3: Add staleness TTL to WebSocket orderbook cache

**Problem:** `get_cached_mid_price()` in `kalshi_ws.py:140` returns a price with no TTL check. If the WebSocket thread disconnects, stale prices sit indefinitely in `_orderbook` and `data/orderbook_cache.json`. The `ts` field is already written by every update — it just isn't checked on read.

**Files:**
- Modify: `kalshi_ws.py:140-152`
- Modify: `utils.py` (add constant)
- Test: `tests/test_kalshi_ws.py`

- [ ] **Step 1: Add `WS_CACHE_TTL_SECS` to `utils.py`**

After the `SLIPPAGE_ALERT_CENTS` line in `utils.py`:

```python
# Orderbook cache TTL — entries older than this are treated as stale and ignored.
# Default: 15 minutes. If the WS is silent for 15+ minutes the cache is worthless.
WS_CACHE_TTL_SECS: float = float(os.getenv("WS_CACHE_TTL_SECS", "900"))
```

- [ ] **Step 2: Write the failing tests**

In `tests/test_kalshi_ws.py`, add:

```python
import time
from unittest.mock import patch
from datetime import UTC, datetime, timedelta
import kalshi_ws


class TestCacheStaleness:
    def test_fresh_entry_returns_price(self, monkeypatch):
        """An entry timestamped <15 min ago is returned normally."""
        monkeypatch.setattr(kalshi_ws, "_orderbook", {
            "KXTEMP-25": {
                "mid_price": 0.65,
                "ts": datetime.now(UTC).isoformat(),
            }
        })
        assert kalshi_ws.get_cached_mid_price("KXTEMP-25") == 0.65

    def test_stale_entry_returns_none(self, monkeypatch):
        """An entry timestamped >WS_CACHE_TTL_SECS ago returns None."""
        old_ts = (datetime.now(UTC) - timedelta(seconds=1000)).isoformat()
        monkeypatch.setattr(kalshi_ws, "_orderbook", {
            "KXTEMP-25": {
                "mid_price": 0.65,
                "ts": old_ts,
            }
        })
        monkeypatch.setenv("WS_CACHE_TTL_SECS", "900")
        import importlib
        import utils
        importlib.reload(utils)
        assert kalshi_ws.get_cached_mid_price("KXTEMP-25") is None

    def test_missing_ts_returns_none(self, monkeypatch):
        """An entry with no ts field is treated as stale."""
        monkeypatch.setattr(kalshi_ws, "_orderbook", {
            "KXTEMP-25": {"mid_price": 0.65}  # no "ts"
        })
        assert kalshi_ws.get_cached_mid_price("KXTEMP-25") is None
```

- [ ] **Step 3: Run to verify failure**

```bash
pytest tests/test_kalshi_ws.py::TestCacheStaleness -v
```
Expected: `FAILED` — stale entry currently returns 0.65 not None.

- [ ] **Step 4: Implement TTL check in `kalshi_ws.py`**

Replace `get_cached_mid_price` (lines 140–152):

```python
def get_cached_mid_price(ticker: str) -> float | None:
    """Return the cached mid-price for a ticker, or None if not cached or stale."""
    from utils import WS_CACHE_TTL_SECS

    def _is_fresh(entry: dict) -> bool:
        ts_str = entry.get("ts")
        if not ts_str:
            return False
        try:
            ts = datetime.fromisoformat(ts_str)
            age = (datetime.now(UTC) - ts).total_seconds()
            return age < WS_CACHE_TTL_SECS
        except (ValueError, TypeError):
            return False

    # Try in-memory first (faster than disk read)
    with _cache_lock:
        entry = _orderbook.get(ticker)
    if entry and _is_fresh(entry) and entry.get("mid_price") is not None:
        return entry["mid_price"]

    # Fall back to disk cache
    cache = read_orderbook_cache()
    entry = cache.get(ticker)
    if entry and _is_fresh(entry):
        return entry.get("mid_price")
    return None
```

- [ ] **Step 5: Run tests**

```bash
pytest tests/test_kalshi_ws.py::TestCacheStaleness -v
```
Expected: `3 passed`

- [ ] **Step 6: Run full suite**

```bash
pytest --tb=short -q
```

- [ ] **Step 7: Commit**

```bash
git add kalshi_ws.py utils.py tests/test_kalshi_ws.py
git commit -m "feat: add WS_CACHE_TTL_SECS staleness gate to get_cached_mid_price"
```

---

### Task 4: Expand SHA-256 checksum from 8 to 16 hex chars

**Problem:** `paper.py:52` truncates SHA-256 to 8 hex chars (32-bit effective entropy). A production file read millions of times has non-trivial collision probability. 16 chars (64-bit) is standard for data integrity.

**Files:**
- Modify: `paper.py:45,52`
- Modify: `tests/test_infrastructure.py:375` (test hardcodes `== 8`)

- [ ] **Step 1: Update the docstring and truncation in `paper.py`**

In `paper.py`, change lines 45 and 52:

```python
def _compute_checksum(payload: dict) -> str:
    """Compute SHA-256 checksum (first 16 hex chars) of payload excluding '_checksum' key."""
    body = json.dumps(
        {k: v for k, v in payload.items() if k != "_checksum"},
        indent=2,
        sort_keys=True,
        default=str,
    ).encode()
    return hashlib.sha256(body).hexdigest()[:16]
```

- [ ] **Step 2: Update the test assertion in `test_infrastructure.py`**

In `tests/test_infrastructure.py`, change line 375:

```python
    assert len(raw["_checksum"]) == 16
```

- [ ] **Step 3: Run the infrastructure tests**

```bash
pytest tests/test_infrastructure.py -k "checksum" -v
```
Expected: both checksum tests pass.

- [ ] **Step 4: Run full suite**

```bash
pytest --tb=short -q
```

- [ ] **Step 5: Commit**

```bash
git add paper.py tests/test_infrastructure.py
git commit -m "fix: expand paper_trades checksum from 8 to 16 hex chars (32→64 bit entropy)"
```

---

## Phase 2 — Risk Hardening

**Acceptance criteria:** All new risk controls are exercised by tests; `DRAWDOWN_HALT_PCT` default change is documented in `.env.example`.

---

### Task 5: Tighten default drawdown halt threshold from 50% to 20%

**Problem:** `DRAWDOWN_HALT_PCT` defaults to `0.50` in `utils.py:74` and `paper.py:100`. This means trading continues until half the account is gone. 20% is the industry standard for automated strategies.

**Files:**
- Modify: `utils.py:74`
- Modify: `paper.py:100` (env default string)
- Modify: `.env.example`
- Test: `tests/test_risk_control.py`

- [ ] **Step 1: Write the failing test**

In `tests/test_risk_control.py`, add:

```python
class TestDrawdownHaltDefault:
    def test_drawdown_halt_default_is_20pct(self, monkeypatch):
        """DRAWDOWN_HALT_PCT default must be 0.20, not 0.50."""
        monkeypatch.delenv("DRAWDOWN_HALT_PCT", raising=False)
        import importlib
        import utils
        importlib.reload(utils)
        assert utils.DRAWDOWN_HALT_PCT == pytest.approx(0.20)
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/test_risk_control.py::TestDrawdownHaltDefault -v
```
Expected: `FAILED — 0.5 != 0.2`

- [ ] **Step 3: Update defaults in `utils.py` and `paper.py`**

In `utils.py`, change line 74:

```python
DRAWDOWN_HALT_PCT = float(os.getenv("DRAWDOWN_HALT_PCT", "0.20"))
```

In `paper.py`, change line 100:

```python
MAX_DRAWDOWN_FRACTION = _env_float("DRAWDOWN_HALT_PCT", "0.20")
```

- [ ] **Step 4: Update `.env.example`**

Find the `DRAWDOWN_HALT_PCT` line in `.env.example` and change the comment + default:

```
# Halt trading when balance drops to this fraction of peak. Default 0.20 (20%).
# Previous default was 0.50 — changed 2026-04-18 per code review.
DRAWDOWN_HALT_PCT=0.20
```

- [ ] **Step 5: Run tests**

```bash
pytest tests/test_risk_control.py::TestDrawdownHaltDefault -v
pytest tests/test_drawdown_tiers.py -v
```
Expected: all pass.

- [ ] **Step 6: Run full suite**

```bash
pytest --tb=short -q
```

- [ ] **Step 7: Commit**

```bash
git add utils.py paper.py .env.example tests/test_risk_control.py
git commit -m "fix(risk): tighten DRAWDOWN_HALT_PCT default from 0.50 to 0.20"
```

---

### Task 6: Add rolling-win-rate accuracy circuit breaker

**Problem:** The consecutive-loss streak pause in `paper.py:is_streak_paused` fires after 3+ losses. But a 40% win rate across 20 trades (losing money steadily) would never trigger it. There's no rolling accuracy check that halts when the model is consistently wrong.

**Files:**
- Modify: `tracker.py` (add `get_rolling_win_rate`)
- Modify: `paper.py` (add `is_accuracy_halted`)
- Modify: `main.py` (gate `cmd_cron` on accuracy halt)
- Modify: `utils.py` (add constants)
- Test: `tests/test_risk_control.py`

- [ ] **Step 1: Add constants to `utils.py`**

After `BRIER_ALERT_THRESHOLD` in `utils.py`:

```python
# Rolling accuracy circuit breaker: halt new trades if win rate over last
# ACCURACY_WINDOW_TRADES falls below ACCURACY_MIN_WIN_RATE.
# Requires at least ACCURACY_MIN_SAMPLE settled trades in the window before firing.
ACCURACY_WINDOW_TRADES: int = int(os.getenv("ACCURACY_WINDOW_TRADES", "20"))
ACCURACY_MIN_WIN_RATE: float = float(os.getenv("ACCURACY_MIN_WIN_RATE", "0.40"))
ACCURACY_MIN_SAMPLE: int = int(os.getenv("ACCURACY_MIN_SAMPLE", "20"))
```

- [ ] **Step 2: Add `get_rolling_win_rate` to `tracker.py`**

After `brier_score` in `tracker.py`:

```python
def get_rolling_win_rate(window: int = 20) -> tuple[float | None, int]:
    """
    Win rate over the last `window` settled predictions.

    Returns (win_rate, count). Returns (None, count) if count < window
    (not enough data to be statistically meaningful).
    """
    init_db()
    with _conn() as con:
        rows = con.execute(
            """
            SELECT o.settled_yes, p.side
            FROM predictions p
            JOIN outcomes o ON p.ticker = o.ticker
            ORDER BY o.settled_at DESC
            LIMIT ?
            """,
            (window,),
        ).fetchall()
    count = len(rows)
    if count < window:
        return None, count
    wins = sum(
        1 for r in rows
        if (r["side"] == "yes" and r["settled_yes"] == 1)
        or (r["side"] == "no" and r["settled_yes"] == 0)
    )
    return wins / count, count
```

- [ ] **Step 3: Add `is_accuracy_halted` to `paper.py`**

After `is_streak_paused` in `paper.py`:

```python
def is_accuracy_halted() -> bool:
    """
    Return True if rolling win rate over the last ACCURACY_WINDOW_TRADES is below
    ACCURACY_MIN_WIN_RATE. Requires ACCURACY_MIN_SAMPLE settled trades in window.
    Only fires when there are enough samples to avoid over-reacting to early variance.
    """
    from utils import ACCURACY_MIN_SAMPLE, ACCURACY_MIN_WIN_RATE, ACCURACY_WINDOW_TRADES

    try:
        from tracker import get_rolling_win_rate

        win_rate, count = get_rolling_win_rate(window=ACCURACY_WINDOW_TRADES)
        if count < ACCURACY_MIN_SAMPLE:
            return False  # not enough data to draw conclusions
        if win_rate is None:
            return False
        if win_rate < ACCURACY_MIN_WIN_RATE:
            _log.warning(
                "Accuracy circuit breaker: win rate %.1f%% over last %d trades "
                "is below %.0f%% threshold — halting new trades",
                win_rate * 100,
                count,
                ACCURACY_MIN_WIN_RATE * 100,
            )
            return True
        return False
    except Exception:
        return False
```

- [ ] **Step 4: Write the failing tests**

In `tests/test_risk_control.py`, add:

```python
class TestAccuracyCircuitBreaker:
    def test_halted_when_win_rate_below_threshold(self, monkeypatch):
        """is_accuracy_halted returns True when win rate is 30% over 20 trades."""
        import paper
        from tracker import get_rolling_win_rate

        monkeypatch.setattr("tracker.get_rolling_win_rate", lambda window: (0.30, 20))
        assert paper.is_accuracy_halted() is True

    def test_not_halted_when_win_rate_acceptable(self, monkeypatch):
        """is_accuracy_halted returns False when win rate is 55% over 20 trades."""
        import paper

        monkeypatch.setattr("tracker.get_rolling_win_rate", lambda window: (0.55, 20))
        assert paper.is_accuracy_halted() is False

    def test_not_halted_when_sample_too_small(self, monkeypatch):
        """is_accuracy_halted returns False when fewer than ACCURACY_MIN_SAMPLE trades settled."""
        import paper

        monkeypatch.setattr("tracker.get_rolling_win_rate", lambda window: (0.20, 5))
        assert paper.is_accuracy_halted() is False

    def test_not_halted_when_tracker_raises(self, monkeypatch):
        """is_accuracy_halted is safe — returns False on any tracker exception."""
        import paper

        def _raise(window):
            raise RuntimeError("db gone")

        monkeypatch.setattr("tracker.get_rolling_win_rate", _raise)
        assert paper.is_accuracy_halted() is False
```

- [ ] **Step 5: Run to verify failure**

```bash
pytest tests/test_risk_control.py::TestAccuracyCircuitBreaker -v
```
Expected: `FAILED` — `is_accuracy_halted` doesn't exist yet.

- [ ] **Step 6: Implement (already written above in Step 3) and run tests**

```bash
pytest tests/test_risk_control.py::TestAccuracyCircuitBreaker -v
```
Expected: `4 passed`

- [ ] **Step 7: Gate cron on accuracy halt in `main.py`**

In `main.py`, find the kill-switch check in `cmd_cron` (search for `_KS_PATH` or `kill_switch`). Immediately after that check, add:

```python
from paper import is_accuracy_halted as _is_accuracy_halted
if _is_accuracy_halted():
    _log.warning("[cron] accuracy circuit breaker active — skipping market scan")
    return
```

- [ ] **Step 8: Run full suite**

```bash
pytest --tb=short -q
```

- [ ] **Step 9: Commit**

```bash
git add tracker.py paper.py utils.py main.py tests/test_risk_control.py
git commit -m "feat: add rolling win-rate accuracy circuit breaker (ACCURACY_MIN_WIN_RATE=40%)"
```

---

### Task 7: WebSocket thread health monitoring

**Problem:** The WS background thread (`_ws_listener`) runs inside `asyncio.run()` inside a daemon thread. If it crashes, the exception is silently swallowed — main loop sees no signal and keeps reading the now-stale cache (mitigated by Task 3's TTL, but detection is still missing).

**Files:**
- Modify: `kalshi_ws.py`
- Test: `tests/test_kalshi_ws.py`

- [ ] **Step 1: Add a thread-safe health flag to `kalshi_ws.py`**

After `_cache_lock = threading.Lock()` near the top of `kalshi_ws.py`:

```python
import threading as _threading

_ws_alive: bool = False
_ws_last_message_ts: float = 0.0
_ws_state_lock = _threading.Lock()


def _set_ws_alive(alive: bool) -> None:
    global _ws_alive
    with _ws_state_lock:
        _ws_alive = alive


def _record_ws_message() -> None:
    global _ws_last_message_ts
    with _ws_state_lock:
        _ws_last_message_ts = __import__("time").monotonic()


def get_ws_health() -> dict:
    """Return WS thread health info for monitoring."""
    from utils import WS_CACHE_TTL_SECS

    import time

    with _ws_state_lock:
        alive = _ws_alive
        last_msg = _ws_last_message_ts
    idle_secs = time.monotonic() - last_msg if last_msg > 0 else None
    return {
        "alive": alive,
        "idle_secs": round(idle_secs, 1) if idle_secs is not None else None,
        "stale": idle_secs is not None and idle_secs > WS_CACHE_TTL_SECS,
    }
```

- [ ] **Step 2: Call `_set_ws_alive` and `_record_ws_message` inside the async listener**

In `_ws_listener` in `kalshi_ws.py`, at the start of the `try:` block after authentication succeeds, add `_set_ws_alive(True)`. In the message-processing loop, after each valid `parsed` result, call `_record_ws_message()`. In the `finally:` block of `_ws_listener`, add `_set_ws_alive(False)`.

- [ ] **Step 3: Write tests**

In `tests/test_kalshi_ws.py`, add:

```python
class TestWsHealth:
    def test_get_ws_health_initially_not_alive(self):
        """Fresh import: ws not alive, no messages recorded."""
        import importlib
        import kalshi_ws
        importlib.reload(kalshi_ws)
        h = kalshi_ws.get_ws_health()
        assert h["alive"] is False
        assert h["idle_secs"] is None

    def test_get_ws_health_stale_flag(self, monkeypatch):
        """stale=True when idle > WS_CACHE_TTL_SECS."""
        import time
        import kalshi_ws

        kalshi_ws._ws_last_message_ts = time.monotonic() - 1000
        kalshi_ws._ws_alive = True
        monkeypatch.setenv("WS_CACHE_TTL_SECS", "900")
        h = kalshi_ws.get_ws_health()
        assert h["stale"] is True
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_kalshi_ws.py::TestWsHealth -v
```
Expected: `2 passed`

- [ ] **Step 5: Log health in `cmd_cron` in `main.py`**

In `cmd_cron`, after the existing WS start-up section, add a health log:

```python
from kalshi_ws import get_ws_health as _get_ws_health
_ws_h = _get_ws_health()
if _ws_h["stale"]:
    _log.warning("[cron] WebSocket cache is stale (idle %.0fs) — mid-prices may be unreliable",
                 _ws_h["idle_secs"])
```

- [ ] **Step 6: Run full suite**

```bash
pytest --tb=short -q
```

- [ ] **Step 7: Commit**

```bash
git add kalshi_ws.py main.py tests/test_kalshi_ws.py
git commit -m "feat: add WS thread health monitoring with stale-cache warning in cron"
```

---

## Phase 3 — Code Quality

**Acceptance criteria:** `mypy --strict` runs in CI with 0 errors on the files touched in this phase; `pytest --cov` reports non-zero coverage on `main.py`.

---

### Task 8: Fix web_app.py XSS surface

**Problem:** Exception objects are interpolated directly into HTML f-strings (e.g., `f"<p>Could not fetch markets: {e}</p>"`). While these are internal error strings, the pattern is dangerous if user-controlled data ever flows through the same path.

**Files:**
- Modify: `web_app.py`

- [ ] **Step 1: Find all unsafe interpolations**

```bash
grep -n "f\".*{e}" web_app.py
grep -n 'f'"'"'.*{e}' web_app.py
```

- [ ] **Step 2: Add escape import at top of `web_app.py`**

After the existing imports in `web_app.py`:

```python
from markupsafe import escape as _html_escape
```

- [ ] **Step 3: Replace each unsafe interpolation**

For every pattern like:
```python
f"<p class='neg'>Could not fetch markets: {e}</p>"
```
Replace with:
```python
f"<p class='neg'>Could not fetch markets: {_html_escape(str(e))}</p>"
```

Run the grep from Step 1 after each replacement to confirm all instances are fixed.

- [ ] **Step 4: Verify markupsafe is in requirements**

```bash
grep markupsafe requirements.txt
```
If missing, add it:
```bash
echo "markupsafe>=2.1" >> requirements.txt
pip install markupsafe
```
(Flask already depends on markupsafe, so it is almost certainly already installed.)

- [ ] **Step 5: Run web_app tests**

```bash
pytest tests/test_web_app.py -v
```

- [ ] **Step 6: Commit**

```bash
git add web_app.py requirements.txt
git commit -m "fix(security): escape exception messages in web_app HTML responses"
```

---

### Task 9: Add `main.py` to pytest coverage and write smoke tests

**Problem:** `main.py` (7,662 lines) is explicitly omitted from pytest coverage in `pyproject.toml`. The cron runner — the sole production execution path — has zero coverage. Add targeted smoke tests for `cmd_cron` and fix the omit list.

**Files:**
- Modify: `pyproject.toml`
- Create: `tests/test_main_cron_smoke.py`

- [ ] **Step 1: Remove `main.py` from the coverage omit list in `pyproject.toml`**

In `pyproject.toml`, remove `"main.py",` from `[tool.coverage.run] omit`:

```toml
[tool.coverage.run]
omit = [
    "paper.py",
    "backtest.py",
    "param_sweep.py",
    "feature_importance.py",
    "pdf_report.py",
    "tests/*",
]
```

- [ ] **Step 2: Create `tests/test_main_cron_smoke.py`**

```python
"""
Smoke tests for cmd_cron — the main production execution path.
These test the guards (kill switch, accuracy halt, drawdown) at the entry point level.
All external I/O (Kalshi API, NWS, tracker) is mocked.
"""
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch


@pytest.fixture()
def minimal_mocks(tmp_path, monkeypatch):
    """Patch every external call cmd_cron makes so it can run without network."""
    import main

    monkeypatch.setattr(main, "get_weather_markets", lambda client: [])
    monkeypatch.setattr(main, "_load_live_config", lambda: {
        "max_trade_dollars": 50,
        "daily_loss_limit": 200,
        "max_open_positions": 10,
        "gtc_cancel_hours": 24,
    })
    # Point kill-switch to a temp path (no active kill switch)
    ks_path = tmp_path / ".kill_switch"
    monkeypatch.setattr(main, "_KS_PATH", ks_path, raising=False)
    return tmp_path


class TestCmdCronGuards:
    def test_kill_switch_blocks_market_scan(self, minimal_mocks, monkeypatch):
        """cmd_cron exits early when the kill switch file is present."""
        import main

        ks_path = minimal_mocks / ".kill_switch"
        ks_path.write_text('{"reason": "test"}')
        monkeypatch.setattr(main, "_KS_PATH", ks_path, raising=False)

        scan_called = []
        monkeypatch.setattr(main, "get_weather_markets", lambda c: scan_called.append(1) or [])
        client = MagicMock()
        main.cmd_cron(client)
        assert scan_called == [], "market scan should be skipped when kill switch is active"

    def test_accuracy_halt_blocks_market_scan(self, minimal_mocks, monkeypatch):
        """cmd_cron exits early when the accuracy circuit breaker is active."""
        import main
        import paper

        monkeypatch.setattr(paper, "is_accuracy_halted", lambda: True)

        scan_called = []
        monkeypatch.setattr(main, "get_weather_markets", lambda c: scan_called.append(1) or [])
        client = MagicMock()
        main.cmd_cron(client)
        assert scan_called == [], "market scan should be skipped on accuracy halt"

    def test_empty_market_list_runs_cleanly(self, minimal_mocks):
        """cmd_cron with no markets returned completes without error."""
        import main

        client = MagicMock()
        main.cmd_cron(client)  # should not raise
```

- [ ] **Step 3: Run the new tests**

```bash
pytest tests/test_main_cron_smoke.py -v
```

Note: some tests may need adjustment based on the exact signature of `cmd_cron`. Look at `main.py` around line 3400–3500 to find the exact entry point and adjust imports in the test accordingly.

- [ ] **Step 4: Run coverage report**

```bash
pytest --cov=main --cov-report=term-missing -q tests/test_main_cron_smoke.py
```
Expected: `main.py` appears in coverage output with non-zero line coverage.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml tests/test_main_cron_smoke.py
git commit -m "test: add main.py to coverage and smoke test cmd_cron guards"
```

---

### Task 10: Add type hints to core functions and enforce mypy in CI

**Problem:** `analyze_trade()`, `get_weather_forecast()`, and most public functions in `weather_markets.py` lack return type annotations. `mypy` is configured in `pyproject.toml` but not run in CI.

**Files:**
- Modify: `weather_markets.py` (type hints on public functions)
- Modify: `pyproject.toml` (add mypy to CI checks)

- [ ] **Step 1: Add return type to `analyze_trade` in `weather_markets.py:2970`**

Change signature:
```python
def analyze_trade(enriched: dict) -> dict | None:
```
It already has a return type — confirm this is correct and that mypy accepts it.

- [ ] **Step 2: Add return types to the other major public functions**

For each of these in `weather_markets.py`, add/verify return type annotations:
- `get_weather_markets(client) -> list[dict]:`
- `get_weather_forecast(city: str, forecast_date: date) -> dict | None:`
- `enrich_with_forecast(market: dict) -> dict:`
- `parse_market_price(market: dict) -> dict:`
- `time_decay_edge(raw_edge: float, close_time: datetime, reference_hours: float) -> float:` (already annotated)

- [ ] **Step 3: Run mypy on the changed files**

```bash
python -m mypy weather_markets.py --ignore-missing-imports --no-strict-optional
```

Fix any errors mypy reports. Common: `dict` should be `dict[str, Any]` from `typing`. Add `from typing import Any` at top of file if needed.

- [ ] **Step 4: Add mypy check to CI**

Check if there's a `.github/workflows/` or `Makefile`. If using `pyproject.toml` scripts, add:

```toml
[tool.mypy]
python_version = "3.12"
ignore_missing_imports = true
warn_return_any = true
```

Then in your CI command (GitHub Actions or equivalent):
```yaml
- name: Type check
  run: python -m mypy weather_markets.py paper.py tracker.py kalshi_ws.py --ignore-missing-imports
```

- [ ] **Step 5: Commit**

```bash
git add weather_markets.py pyproject.toml
git commit -m "feat(types): add type annotations to core public functions; add mypy CI check"
```

---

### Task 11: Add tracker DB retention policy

**Problem:** `tracker.py` only appends. With years of 4-hour cron runs, `predictions` grows unbounded (millions of rows). There are no DELETE statements and no archiving logic.

**Files:**
- Modify: `tracker.py`
- Modify: `main.py` (call retention on startup or weekly)
- Test: `tests/test_tracker.py`

- [ ] **Step 1: Write the failing test**

In `tests/test_tracker.py`, add:

```python
class TestRetentionPolicy:
    def test_purge_old_predictions_removes_settled(self, tmp_path, monkeypatch):
        """purge_old_predictions removes settled predictions older than retention_days."""
        import tracker
        import sqlite3
        from datetime import date, timedelta

        db = tmp_path / "test.db"
        monkeypatch.setattr(tracker, "_DB_PATH", db)
        tracker.init_db()

        # Insert an old settled prediction (2 years ago)
        old_date = (date.today() - timedelta(days=800)).isoformat()
        with tracker._conn() as con:
            con.execute(
                "INSERT INTO predictions (ticker, city, forecast_prob, market_prob, "
                "predicted_date, logged_at, side) VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("OLD-TICKER", "NYC", 0.7, 0.5, old_date, old_date + " 00:00:00", "yes")
            )
            con.execute(
                "INSERT INTO outcomes (ticker, settled_yes, settled_at) VALUES (?, ?, ?)",
                ("OLD-TICKER", 1, old_date + " 12:00:00")
            )

        tracker.purge_old_predictions(retention_days=365)

        with tracker._conn() as con:
            count = con.execute(
                "SELECT COUNT(*) FROM predictions WHERE ticker = 'OLD-TICKER'"
            ).fetchone()[0]
        assert count == 0

    def test_purge_old_predictions_keeps_recent(self, tmp_path, monkeypatch):
        """purge_old_predictions keeps predictions within retention_days."""
        import tracker
        from datetime import date, timedelta

        db = tmp_path / "test.db"
        monkeypatch.setattr(tracker, "_DB_PATH", db)
        tracker.init_db()

        recent_date = date.today().isoformat()
        with tracker._conn() as con:
            con.execute(
                "INSERT INTO predictions (ticker, city, forecast_prob, market_prob, "
                "predicted_date, logged_at, side) VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("NEW-TICKER", "NYC", 0.7, 0.5, recent_date, recent_date + " 00:00:00", "yes")
            )

        tracker.purge_old_predictions(retention_days=365)

        with tracker._conn() as con:
            count = con.execute(
                "SELECT COUNT(*) FROM predictions WHERE ticker = 'NEW-TICKER'"
            ).fetchone()[0]
        assert count == 1
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/test_tracker.py::TestRetentionPolicy -v
```
Expected: `FAILED` — `purge_old_predictions` doesn't exist.

- [ ] **Step 3: Implement `purge_old_predictions` in `tracker.py`**

Add after `init_db`:

```python
def purge_old_predictions(retention_days: int = 730) -> int:
    """
    Delete settled predictions older than `retention_days` and their outcomes.
    Unsettled (open) predictions are never deleted.
    Returns the number of rows deleted from `predictions`.

    Safe to call from cron; uses a single transaction.
    """
    cutoff = f"-{retention_days}"
    init_db()
    with _conn() as con:
        # Delete outcomes for old settled predictions first (foreign-key order)
        con.execute(
            """
            DELETE FROM outcomes
            WHERE ticker IN (
                SELECT p.ticker FROM predictions p
                JOIN outcomes o ON p.ticker = o.ticker
                WHERE o.settled_at < datetime('now', ?)
            )
            """,
            (cutoff,),
        )
        result = con.execute(
            """
            DELETE FROM predictions
            WHERE ticker NOT IN (SELECT ticker FROM outcomes)
              AND logged_at < datetime('now', ?)
            """,
            (cutoff,),
        )
    deleted = result.rowcount
    if deleted > 0:
        _log.info("purge_old_predictions: removed %d old prediction rows", deleted)
    return deleted
```

- [ ] **Step 4: Call `purge_old_predictions` weekly from `cmd_cron` in `main.py`**

In `cmd_cron`, at the top after logging setup, add:

```python
# Weekly retention purge (only fires on Monday cron runs)
from datetime import date as _date
if _date.today().weekday() == 0:  # Monday
    from tracker import purge_old_predictions as _purge
    _purge(retention_days=730)
```

- [ ] **Step 5: Run tests**

```bash
pytest tests/test_tracker.py::TestRetentionPolicy -v
```
Expected: `2 passed`

- [ ] **Step 6: Run full suite**

```bash
pytest --tb=short -q
```

- [ ] **Step 7: Commit**

```bash
git add tracker.py main.py tests/test_tracker.py
git commit -m "feat: add 2-year retention policy for settled predictions (purge_old_predictions)"
```

---

### Task 12: Tune time-decay edge to preserve near-close signals

**Problem:** `time_decay_edge` in `weather_markets.py:2593` uses `reference_hours=48.0`. At 2h before close, decay = 2/48 = 4.2% of edge. A genuine 30% edge at close becomes 1.3% — well below any MIN_EDGE threshold. This kills legitimate last-minute opportunities when the METAR lock already confirms the outcome.

**Files:**
- Modify: `weather_markets.py:2596`
- Test: `tests/test_forecasting.py` or similar

- [ ] **Step 1: Write tests to document the behavior change**

In `tests/test_forecasting.py` (or equivalent test file for weather_markets), add:

```python
class TestTimeDecayEdge:
    def test_full_edge_beyond_reference_hours(self):
        """At 10h before close with 8h reference: full edge returned."""
        from datetime import UTC, datetime, timedelta
        from weather_markets import time_decay_edge

        close = datetime.now(UTC) + timedelta(hours=10)
        result = time_decay_edge(0.30, close, reference_hours=8.0)
        assert result == pytest.approx(0.30)

    def test_half_edge_at_half_reference_hours(self):
        """At 4h before close with 8h reference: 50% of edge returned."""
        from datetime import UTC, datetime, timedelta
        from weather_markets import time_decay_edge

        close = datetime.now(UTC) + timedelta(hours=4)
        result = time_decay_edge(0.30, close, reference_hours=8.0)
        assert result == pytest.approx(0.15, abs=0.01)

    def test_near_close_retains_meaningful_edge(self):
        """At 2h before close with 8h reference: 25% of edge retained (vs 4% with 48h)."""
        from datetime import UTC, datetime, timedelta
        from weather_markets import time_decay_edge

        close = datetime.now(UTC) + timedelta(hours=2)
        result = time_decay_edge(0.30, close, reference_hours=8.0)
        assert result > 0.05  # at least 5% edge — tradeable
```

- [ ] **Step 2: Change the default `reference_hours` from 48 to 8**

In `weather_markets.py:2596`, change:

```python
def time_decay_edge(
    raw_edge: float,
    close_time: datetime,
    reference_hours: float = 8.0,
) -> float:
```

Also update the docstring to reflect the new default and rationale:

```python
    """
    #63: Scale edge linearly to zero as the market approaches close.

    At reference_hours (8h) or more before close: full edge returned.
    At close_time or past: 0.0 returned.

    Default changed from 48h to 8h: METAR lock-in makes near-close signals more
    reliable (not less), so preserving edge in the final 8h is correct.
    """
```

- [ ] **Step 3: Run tests**

```bash
pytest tests/ -k "TimeDecayEdge or time_decay" -v
```
Expected: all pass.

- [ ] **Step 4: Run full suite**

```bash
pytest --tb=short -q
```

- [ ] **Step 5: Commit**

```bash
git add weather_markets.py tests/test_forecasting.py
git commit -m "fix: reduce time_decay_edge reference_hours from 48h to 8h to preserve near-close signals"
```

---

### Task 13: Add API schema drift test for conftest mocks

**Problem:** Mock market data in `tests/conftest.py` is hardcoded. If Kalshi adds or renames a field (e.g., `volume_fp` replacing `volume`), tests stay green while production breaks.

**Files:**
- Create: `tests/test_schema_drift.py`

- [ ] **Step 1: Create the drift test**

```python
"""
Schema drift detection: ensure mock market data used in conftest matches the
fields that production code actually reads from a market dict.
"""

FIELDS_PRODUCTION_CODE_READS = [
    # From analyze_trade / enrich_with_forecast in weather_markets.py
    "ticker",
    "volume_fp",
    "volume",
    "open_interest_fp",
    "open_interest",
    "yes_ask",
    "yes_bid",
    "close_time",
    "_forecast",
    "_date",
    "_city",
    "_hour",
    "data_fetched_at",
]


def test_conftest_mock_market_has_all_required_fields(mock_market):
    """Mock market in conftest must include every field production code reads."""
    missing = [f for f in FIELDS_PRODUCTION_CODE_READS if f not in mock_market]
    assert not missing, f"Mock market is missing fields: {missing}"
```

Note: `mock_market` must be a fixture in `conftest.py` that returns the standard mock market dict. If it doesn't exist as a standalone fixture, extract it from wherever it's currently inlined.

- [ ] **Step 2: Run the new test**

```bash
pytest tests/test_schema_drift.py -v
```

If it fails because `mock_market` isn't a fixture, add it to `conftest.py`:

```python
@pytest.fixture()
def mock_market():
    """Standard mock Kalshi market dict — must stay in sync with production field names."""
    return {
        "ticker": "KXTEMP-25-NYC-B70-T",
        "volume_fp": 500,
        "volume": 500,
        "open_interest_fp": 1000,
        "open_interest": 1000,
        "yes_bid": "0.60",
        "yes_ask": "0.65",
        "close_time": "2026-04-20T20:00:00Z",
        "_forecast": None,
        "_date": None,
        "_city": None,
        "_hour": None,
        "data_fetched_at": None,
    }
```

- [ ] **Step 3: Commit**

```bash
git add tests/test_schema_drift.py tests/conftest.py
git commit -m "test: add schema drift detection for conftest mock market fields"
```

---

## Phase 4 — main.py Decomposition

**Acceptance criteria:** `main.py` loses at least 2,000 lines. All existing behavior is preserved. Full test suite still passes. `cmd_cron` is importable from a new module for targeted testing.

**Note:** This is the riskiest phase by LOC changed. Do it on a dedicated branch. Extract one component at a time and run the full test suite after each extraction.

---

### Task 14: Extract cron runner to `cron.py`

**Goal:** Move `cmd_cron` and its private helpers (`_place_paper_order_cron`, `_scan_markets`, etc.) to `cron.py`. Keep `main.py` calling `from cron import cmd_cron`.

**Files:**
- Create: `cron.py`
- Modify: `main.py`

- [ ] **Step 1: Identify the cron-related functions to extract**

```bash
grep -n "^def cmd_cron\|^def _place_paper\|^def _scan_markets\|^def _cron_\|^def _live_trade" main.py
```

Record every function name and line range.

- [ ] **Step 2: Create `cron.py` with the extracted functions**

Copy each identified function (and their module-level state: `_LIVE_CONFIG_PATH`, `_LIVE_CONFIG_DEFAULT`, `_current_forecast_cycle`, etc.) into `cron.py`. Add the necessary imports at the top. Do not change function signatures.

- [ ] **Step 3: Replace in `main.py`**

Remove the copied functions from `main.py`. At the top of `main.py`, add:

```python
from cron import cmd_cron, _load_live_config  # and any other exported names
```

- [ ] **Step 4: Run full suite**

```bash
pytest --tb=short -q
```
Expected: zero regressions.

- [ ] **Step 5: Commit**

```bash
git add cron.py main.py
git commit -m "refactor: extract cmd_cron and live trade helpers to cron.py"
```

---

### Task 15: Extract output formatters to `output_formatters.py`

**Goal:** Move all `print()`-heavy functions that format human-readable output (balance display, position tables, P&L summaries, color-coded signal output) to `output_formatters.py`.

**Files:**
- Create: `output_formatters.py`
- Modify: `main.py`

- [ ] **Step 1: Identify output-formatting functions**

```bash
grep -n "^def print_\|^def display_\|^def show_\|^def format_\|^def _render_" main.py
```

Also grep for functions that only call `print()` and `colors.*`:

```bash
grep -n "def cmd_balance\|def cmd_positions\|def cmd_history\|def cmd_pnl" main.py
```

- [ ] **Step 2: Move identified functions to `output_formatters.py`**

Create `output_formatters.py` with appropriate imports (`from colors import *`, `from paper import *`, etc.). Copy functions there.

- [ ] **Step 3: Update `main.py`**

Remove copied functions, add at top:

```python
from output_formatters import cmd_balance, cmd_positions, cmd_history, cmd_pnl
```

- [ ] **Step 4: Run full suite**

```bash
pytest --tb=short -q
```

- [ ] **Step 5: Commit**

```bash
git add output_formatters.py main.py
git commit -m "refactor: extract output formatting functions to output_formatters.py"
```

---

---

## Phase 0 — Drawdown Logic Correctness (run BEFORE Phase 2)

**This phase must execute before Phase 2 Task 5.** Task 5 changes `DRAWDOWN_HALT_PCT` to 0.20, but `drawdown_scaling_factor()` uses hardcoded literals — not the constants — so the env var change has no effect. Fix the function first, then change the default.

---

### Task 0: Wire `drawdown_scaling_factor()` to use configurable thresholds

**Root cause:** `paper.py:107–110` defines `_DRAWDOWN_TIER_*` constants derived from `MAX_DRAWDOWN_FRACTION`, but `drawdown_scaling_factor()` at line 317 ignores them entirely and uses hardcoded `0.60`, `0.80`, `0.90`. The constants are dead code. Additionally, with halt at 20% (`_TIER_1 = 0.80`), the hardcoded `0.60` and `0.75` thresholds for lower tiers fall below the halt, making the gradual cascade unreachable.

**Fix:** Replace the four constants with a single configurable halt threshold, then derive all tier thresholds relative to it, and update the function to use them.

**Files:**
- Modify: `paper.py:107–337`
- Test: `tests/test_drawdown_tiers.py`

- [ ] **Step 1: Write failing tests for the new tier behavior**

In `tests/test_drawdown_tiers.py`, add a new class:

```python
class TestDrawdownTiersRelativeToHalt:
    """Tiers must be relative to halt threshold, not hardcoded absolutes."""

    def test_tiers_scale_with_halt_threshold(self, monkeypatch):
        """With 20% halt, tier thresholds should shift proportionally."""
        import importlib
        import paper

        monkeypatch.setenv("DRAWDOWN_HALT_PCT", "0.20")
        importlib.reload(paper)
        # Halt is at 80% of peak. Tier 2 (conservative) must be above halt (>80%)
        assert paper._DRAWDOWN_TIER_2 > paper._DRAWDOWN_TIER_1
        assert paper._DRAWDOWN_TIER_3 > paper._DRAWDOWN_TIER_2
        assert paper._DRAWDOWN_TIER_4 > paper._DRAWDOWN_TIER_3

    def test_halt_at_20pct_drawdown(self, mock_balance_1000, monkeypatch):
        """At 20% drawdown, scaling factor should be 0.0."""
        import paper

        monkeypatch.setattr(paper, "MAX_DRAWDOWN_FRACTION", 0.20)
        monkeypatch.setattr(paper, "_DRAWDOWN_TIER_1", 0.80)
        monkeypatch.setattr(paper, "_DRAWDOWN_TIER_2", 0.85)
        monkeypatch.setattr(paper, "_DRAWDOWN_TIER_3", 0.90)
        monkeypatch.setattr(paper, "_DRAWDOWN_TIER_4", 0.95)
        monkeypatch.setattr(paper, "get_peak_balance", lambda: 1000.0)
        monkeypatch.setattr(paper, "get_balance", lambda: 790.0)  # 21% drawdown
        assert paper.drawdown_scaling_factor() == 0.0

    def test_full_sizing_near_peak(self, mock_balance_1000, monkeypatch):
        """Above TIER_4, full sizing (1.0) is returned."""
        import paper

        monkeypatch.setattr(paper, "MAX_DRAWDOWN_FRACTION", 0.20)
        monkeypatch.setattr(paper, "_DRAWDOWN_TIER_1", 0.80)
        monkeypatch.setattr(paper, "_DRAWDOWN_TIER_2", 0.85)
        monkeypatch.setattr(paper, "_DRAWDOWN_TIER_3", 0.90)
        monkeypatch.setattr(paper, "_DRAWDOWN_TIER_4", 0.95)
        monkeypatch.setattr(paper, "get_peak_balance", lambda: 1000.0)
        monkeypatch.setattr(paper, "get_balance", lambda: 970.0)  # 3% drawdown
        assert paper.drawdown_scaling_factor() == 1.0
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/test_drawdown_tiers.py::TestDrawdownTiersRelativeToHalt -v
```
Expected: `FAILED` — tiers are currently hardcoded constants, not relative.

- [ ] **Step 3: Replace the tier constants in `paper.py:107–110`**

Replace lines 107–110 with relative calculations:

```python
# Drawdown tier thresholds as fractions of peak balance.
# All tiers are derived relative to MAX_DRAWDOWN_FRACTION so they remain
# reachable regardless of what halt threshold is configured.
_DRAWDOWN_TIER_1 = 1.0 - MAX_DRAWDOWN_FRACTION          # halt below this (e.g. 0.80 at 20% halt)
_DRAWDOWN_TIER_2 = _DRAWDOWN_TIER_1 + 0.05              # 10% sizing  (e.g. 0.85)
_DRAWDOWN_TIER_3 = _DRAWDOWN_TIER_1 + 0.10              # 30% sizing  (e.g. 0.90)
_DRAWDOWN_TIER_4 = _DRAWDOWN_TIER_1 + 0.15              # 70% sizing  (e.g. 0.95)
```

- [ ] **Step 4: Rewrite `drawdown_scaling_factor()` to use the constants**

Replace `paper.py:317–337`:

```python
def drawdown_scaling_factor() -> float:
    """
    Return a 0.0–1.0 Kelly multiplier based on drawdown from peak (high-water mark).

    All thresholds are relative to MAX_DRAWDOWN_FRACTION (DRAWDOWN_HALT_PCT env var).
    With the default 20% halt:
      < 5% drawdown  (> TIER_4 = 0.95) → 1.00  full sizing
      5–10% drawdown (TIER_3–TIER_4)   → 0.70  reduced
      10–15% drawdown (TIER_2–TIER_3)  → 0.30  conservative
      15–20% drawdown (TIER_1–TIER_2)  → 0.10  survival
      >= 20% drawdown (≤ TIER_1 = 0.80) → 0.00  halted
    """
    peak = get_peak_balance()
    if peak <= 0:
        return 1.0
    recovery = get_balance() / peak
    if recovery <= _DRAWDOWN_TIER_1:
        return 0.0
    if recovery <= _DRAWDOWN_TIER_2:
        return 0.10
    if recovery <= _DRAWDOWN_TIER_3:
        return 0.30
    if recovery <= _DRAWDOWN_TIER_4:
        return 0.70
    return 1.0
```

- [ ] **Step 5: Run tests**

```bash
pytest tests/test_drawdown_tiers.py -v
```
Expected: all pass. If existing tier tests break, update their expected values to match the new relative thresholds.

- [ ] **Step 6: Run full suite**

```bash
pytest --tb=short -q
```

- [ ] **Step 7: Commit**

```bash
git add paper.py tests/test_drawdown_tiers.py
git commit -m "fix: wire drawdown_scaling_factor to use configurable tier constants (was hardcoded)"
```

---

## Phase 5 — Security Hardening

**Acceptance criteria:** Dashboard requires a password when `DASHBOARD_PASSWORD` is set; private key permissions are validated at startup; fsync failures surface as warnings not silently pass.

---

### Task 16: Flask dashboard HTTP Basic Auth

**Problem:** `web_app.py` has no authentication. Anyone with network access to port 5000 can view positions, P&L, and trigger halt/resume. Adding opt-in Basic Auth behind `DASHBOARD_PASSWORD` costs 20 lines.

**Files:**
- Modify: `web_app.py`
- Modify: `utils.py` (add constant)
- Test: `tests/test_web_app.py`

- [ ] **Step 1: Add `DASHBOARD_PASSWORD` to `utils.py`**

After `SLIPPAGE_ALERT_CENTS` in `utils.py`:

```python
# Optional HTTP Basic Auth password for the web dashboard.
# If empty (default), the dashboard is open. Set to protect the port.
DASHBOARD_PASSWORD: str = os.getenv("DASHBOARD_PASSWORD", "")
```

- [ ] **Step 2: Write failing tests**

In `tests/test_web_app.py`, add:

```python
class TestDashboardAuth:
    def test_no_auth_required_when_password_unset(self, client, monkeypatch):
        """Dashboard is open when DASHBOARD_PASSWORD is empty."""
        import utils
        monkeypatch.setattr(utils, "DASHBOARD_PASSWORD", "")
        resp = client.get("/")
        assert resp.status_code != 401

    def test_401_when_password_set_and_no_credentials(self, client, monkeypatch):
        """Dashboard returns 401 when password is set and no Authorization header sent."""
        import utils
        monkeypatch.setattr(utils, "DASHBOARD_PASSWORD", "secret")
        resp = client.get("/")
        assert resp.status_code == 401

    def test_200_with_correct_credentials(self, client, monkeypatch):
        """Dashboard returns 200 with correct Basic Auth credentials."""
        import base64
        import utils
        monkeypatch.setattr(utils, "DASHBOARD_PASSWORD", "secret")
        creds = base64.b64encode(b"kalshi:secret").decode()
        resp = client.get("/", headers={"Authorization": f"Basic {creds}"})
        assert resp.status_code == 200
```

- [ ] **Step 3: Implement auth decorator in `web_app.py`**

Near the top of `web_app.py`, after imports:

```python
import base64
import functools
from utils import DASHBOARD_PASSWORD


def _require_auth(f):
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        if not DASHBOARD_PASSWORD:
            return f(*args, **kwargs)
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Basic "):
            try:
                decoded = base64.b64decode(auth[6:]).decode("utf-8")
                _, password = decoded.split(":", 1)
                if password == DASHBOARD_PASSWORD:
                    return f(*args, **kwargs)
            except Exception:
                pass
        return Response(
            "Authentication required",
            401,
            {"WWW-Authenticate": 'Basic realm="Kalshi Dashboard"'},
        )
    return decorated
```

- [ ] **Step 4: Apply `@_require_auth` to all routes**

Add `@_require_auth` to every `@app.route(...)` decorated view function in `web_app.py`. The SSE endpoint (`/stream`) should also be protected.

- [ ] **Step 5: Update `.env.example`**

```
# Optional: protect the web dashboard with HTTP Basic Auth
# Leave empty to disable auth (default for local use)
DASHBOARD_PASSWORD=
```

- [ ] **Step 6: Run tests**

```bash
pytest tests/test_web_app.py::TestDashboardAuth -v
```
Expected: `3 passed`

- [ ] **Step 7: Commit**

```bash
git add web_app.py utils.py .env.example tests/test_web_app.py
git commit -m "feat(security): add optional HTTP Basic Auth to dashboard (DASHBOARD_PASSWORD)"
```

---

### Task 17: Private key file permission check at startup

**Problem:** The Kalshi RSA private key is loaded from a file path. If that file is world-readable (permissions 0644), any user on the machine can read the trading credentials. A one-time permission check at startup catches this immediately.

**Files:**
- Modify: `kalshi_client.py`
- Test: `tests/test_kalshi_client.py`

- [ ] **Step 1: Write failing test**

In `tests/test_kalshi_client.py`, add:

```python
class TestKeyPermissions:
    def test_warns_on_world_readable_key(self, tmp_path, monkeypatch, caplog):
        """Loading a key file with group/other read bits set emits a warning."""
        import stat
        import kalshi_client

        key_file = tmp_path / "private.pem"
        key_file.write_text("fake-key")
        key_file.chmod(0o644)  # world-readable

        import logging
        with caplog.at_level(logging.WARNING, logger="kalshi_client"):
            kalshi_client._check_key_permissions(key_file)
        assert "permission" in caplog.text.lower() or "readable" in caplog.text.lower()

    def test_no_warning_on_private_key(self, tmp_path, caplog):
        """Loading a key file with 0600 permissions emits no warning."""
        import stat
        import kalshi_client

        key_file = tmp_path / "private.pem"
        key_file.write_text("fake-key")
        key_file.chmod(0o600)

        import logging
        with caplog.at_level(logging.WARNING, logger="kalshi_client"):
            kalshi_client._check_key_permissions(key_file)
        assert caplog.text == ""
```

- [ ] **Step 2: Implement `_check_key_permissions` in `kalshi_client.py`**

```python
def _check_key_permissions(key_path: Path) -> None:
    """Warn if the private key file is readable by group or others."""
    import stat as _stat
    try:
        mode = key_path.stat().st_mode
        if mode & (_stat.S_IRGRP | _stat.S_IROTH):
            _log.warning(
                "Private key %s is readable by group/others (mode %o). "
                "Run: chmod 600 %s",
                key_path, mode & 0o777, key_path,
            )
    except OSError:
        pass  # file missing — let the key-load step report that
```

Call this inside the `KalshiClient.__init__` after the key path is resolved, before loading the key.

- [ ] **Step 3: Run tests**

```bash
pytest tests/test_kalshi_client.py::TestKeyPermissions -v
```

Note: On Windows, `st_mode` doesn't reflect Unix permissions. The check should be gated:
```python
import platform
if platform.system() != "Windows":
    _check_key_permissions(key_path)
```

- [ ] **Step 4: Commit**

```bash
git add kalshi_client.py tests/test_kalshi_client.py
git commit -m "feat(security): warn on world-readable private key file at startup"
```

---

### Task 18: Add secrets scanning to CI

**Problem:** An accidentally committed `.env` file containing live Kalshi credentials would not be caught by CI.

**Files:**
- Modify: `.github/workflows/ci.yml`

- [ ] **Step 1: Add `trufflehog` or `gitleaks` scan to `ci.yml`**

In `.github/workflows/ci.yml`, add a step before the test step:

```yaml
      - name: Scan for secrets
        uses: trufflesecurity/trufflehog@v3
        with:
          path: ./
          base: ${{ github.event.repository.default_branch }}
          extra_args: --only-verified
```

Alternatively, if you prefer a local tool:

```yaml
      - name: Install gitleaks
        run: |
          curl -sSL https://github.com/gitleaks/gitleaks/releases/latest/download/gitleaks_linux_x64.tar.gz | tar -xz
          chmod +x gitleaks

      - name: Scan for secrets
        run: ./gitleaks detect --source . --no-git --exit-code 1
```

- [ ] **Step 2: Add `.gitleaks.toml` allowlist for test fixtures**

```toml
[allowlist]
  description = "Test fixture keys and known-safe patterns"
  regexes = [
    "fake-key",
    "deadbeef",
    "test.*private.*key",
  ]
  paths = [
    "tests/",
  ]
```

- [ ] **Step 3: Verify CI passes on a clean branch**

Push to a dev branch and confirm the new CI step passes without false positives.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/ci.yml .gitleaks.toml
git commit -m "ci: add secrets scanning via gitleaks/trufflehog"
```

---

### Task 19: Fix fsync silent failure in `safe_io.py`

**Problem:** `safe_io.py:67–69` wraps `os.fsync()` in `except OSError: pass`. A failed fsync means data may not be durable, but the caller is told the write succeeded. This is intentional for Windows compatibility but should at minimum log a debug message so failures are visible.

**Files:**
- Modify: `safe_io.py:66–69`

- [ ] **Step 1: Change silent pass to debug log**

In `safe_io.py`, replace:

```python
                try:
                    os.fsync(f.fileno())
                except OSError:
                    pass
```

With:

```python
                try:
                    os.fsync(f.fileno())
                except OSError as _fsync_err:
                    _log.debug(
                        "fsync failed for %s (non-fatal on some filesystems): %s",
                        tmp_path_str, _fsync_err,
                    )
```

- [ ] **Step 2: Run existing safe_io tests**

```bash
pytest tests/ -k "safe_io or atomic" -v
```

- [ ] **Step 3: Commit**

```bash
git add safe_io.py
git commit -m "fix: log fsync failures at DEBUG instead of silently passing"
```

---

## Phase 6 — Risk Hardening II

**Acceptance criteria:** Live trading cannot be enabled before 30 settled trades; `MAX_DAILY_SPEND` is validated against balance; SPRT detects model degradation faster than rolling win rate alone.

---

### Task 20: Programmatic graduation gate

**Problem:** `ENABLE_MICRO_LIVE=true` can be set in `.env` at any time. Nothing enforces the 30-trade minimum at the code level — only convention. A misconfigured deploy could start placing real orders immediately.

**Files:**
- Modify: `utils.py`
- Modify: `main.py` (startup check)
- Test: `tests/test_risk_control.py`

- [ ] **Step 1: Write the failing test**

In `tests/test_risk_control.py`, add:

```python
class TestGraduationGate:
    def test_raises_when_micro_live_enabled_with_too_few_trades(self, monkeypatch):
        """Startup must raise if ENABLE_MICRO_LIVE=true and < MIN_BRIER_SAMPLES settled."""
        import utils
        import main

        monkeypatch.setattr(utils, "ENABLE_MICRO_LIVE", True)
        monkeypatch.setattr("tracker.count_settled_predictions", lambda: 5)
        with pytest.raises(RuntimeError, match="settled trades"):
            main._check_graduation_gate()

    def test_passes_when_enough_trades(self, monkeypatch):
        """Startup passes when ENABLE_MICRO_LIVE=true and >= MIN_BRIER_SAMPLES settled."""
        import utils
        import main

        monkeypatch.setattr(utils, "ENABLE_MICRO_LIVE", True)
        monkeypatch.setattr("tracker.count_settled_predictions", lambda: 30)
        main._check_graduation_gate()  # should not raise

    def test_passes_when_micro_live_disabled(self, monkeypatch):
        """Startup passes when ENABLE_MICRO_LIVE=false regardless of trade count."""
        import utils
        import main

        monkeypatch.setattr(utils, "ENABLE_MICRO_LIVE", False)
        monkeypatch.setattr("tracker.count_settled_predictions", lambda: 0)
        main._check_graduation_gate()  # should not raise
```

- [ ] **Step 2: Implement `_check_graduation_gate` in `main.py`**

Add near the top of `main.py` (after imports, before CLI entry):

```python
def _check_graduation_gate() -> None:
    """Raise RuntimeError if ENABLE_MICRO_LIVE is set before graduation criteria are met."""
    from utils import ENABLE_MICRO_LIVE, MIN_BRIER_SAMPLES

    if not ENABLE_MICRO_LIVE:
        return
    from tracker import count_settled_predictions
    count = count_settled_predictions()
    if count < MIN_BRIER_SAMPLES:
        raise RuntimeError(
            f"ENABLE_MICRO_LIVE requires {MIN_BRIER_SAMPLES} settled trades "
            f"for statistical validity. Only {count} found. "
            f"Disable ENABLE_MICRO_LIVE or wait for more settled predictions."
        )
```

- [ ] **Step 3: Call `_check_graduation_gate()` at CLI entry**

In `main.py`, find the `if __name__ == "__main__":` block or the `main()` function and add:

```python
_check_graduation_gate()
```

as the first substantive line after argument parsing.

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_risk_control.py::TestGraduationGate -v
```
Expected: `3 passed`

- [ ] **Step 5: Run full suite**

```bash
pytest --tb=short -q
```

- [ ] **Step 6: Commit**

```bash
git add main.py tests/test_risk_control.py
git commit -m "feat(risk): enforce graduation gate — block ENABLE_MICRO_LIVE before 30 settled trades"
```

---

### Task 21: Validate `MAX_DAILY_SPEND` against current balance

**Problem:** `MAX_DAILY_SPEND` defaults to $500 and is never compared to the current balance. If the paper balance is $300, the daily spend cap permits the bot to lose more than the whole account in a single day.

**Files:**
- Modify: `main.py` (add to `cmd_cron` startup checks)
- Test: `tests/test_main_cron_smoke.py`

- [ ] **Step 1: Write the test**

In `tests/test_main_cron_smoke.py`, add:

```python
def test_cron_logs_warning_when_daily_spend_exceeds_balance(minimal_mocks, monkeypatch, caplog):
    """cmd_cron warns when MAX_DAILY_SPEND > current balance."""
    import utils
    import paper
    import main
    import logging

    monkeypatch.setattr(utils, "MAX_DAILY_SPEND", 5000.0)
    monkeypatch.setattr(paper, "get_balance", lambda: 300.0)

    with caplog.at_level(logging.WARNING):
        client = MagicMock()
        main.cmd_cron(client)

    assert any("MAX_DAILY_SPEND" in r.message for r in caplog.records)
```

- [ ] **Step 2: Add the balance validation in `cmd_cron`**

In `main.py`, at the start of `cmd_cron` (after the kill switch check), add:

```python
from utils import MAX_DAILY_SPEND as _mds
from paper import get_balance as _get_bal
_bal = _get_bal()
if _bal > 0 and _mds > _bal:
    _log.warning(
        "MAX_DAILY_SPEND ($%.0f) exceeds current balance ($%.0f) — "
        "consider lowering MAX_DAILY_SPEND in your .env",
        _mds, _bal,
    )
```

- [ ] **Step 3: Run tests**

```bash
pytest tests/test_main_cron_smoke.py -v
```

- [ ] **Step 4: Commit**

```bash
git add main.py tests/test_main_cron_smoke.py
git commit -m "fix(risk): warn when MAX_DAILY_SPEND exceeds current balance"
```

---

### Task 22: Sequential Probability Ratio Test (SPRT) for model degradation

**Problem:** The rolling win-rate check (Task 6) detects chronic failure but needs 20 trades to fire. A SPRT can detect a regime shift from expected 55% win rate to 35% in approximately 8 trades with controlled false-alarm rate — catching model failure before more capital is lost.

**Files:**
- Modify: `tracker.py` (add `sprt_model_health`)
- Modify: `paper.py` (expose SPRT result in `is_accuracy_halted`)
- Modify: `utils.py` (add SPRT constants)
- Test: `tests/test_risk_control.py`

- [ ] **Step 1: Add SPRT constants to `utils.py`**

```python
# Sequential Probability Ratio Test for model degradation detection.
# H0: win rate = SPRT_P0 (expected — model is working)
# H1: win rate = SPRT_P1 (degraded — model is failing)
# alpha = false alarm rate (fire halt when model is fine)
# beta  = miss rate (miss a real degradation)
SPRT_P0: float = float(os.getenv("SPRT_P0", "0.55"))   # expected win rate
SPRT_P1: float = float(os.getenv("SPRT_P1", "0.35"))   # degraded win rate
SPRT_ALPHA: float = float(os.getenv("SPRT_ALPHA", "0.05"))  # 5% false alarm
SPRT_BETA: float = float(os.getenv("SPRT_BETA", "0.20"))    # 20% miss rate
SPRT_MIN_TRADES: int = int(os.getenv("SPRT_MIN_TRADES", "5"))  # min before test applies
```

- [ ] **Step 2: Implement `sprt_model_health` in `tracker.py`**

```python
def sprt_model_health(
    window: int = 50,
    p0: float = 0.55,
    p1: float = 0.35,
    alpha: float = 0.05,
    beta: float = 0.20,
    min_trades: int = 5,
) -> dict:
    """
    Sequential Probability Ratio Test on recent settled predictions.

    Returns:
      {"status": "ok" | "degraded" | "insufficient_data",
       "lambda": float,           # log-likelihood ratio
       "trades_tested": int,
       "threshold_upper": float,  # log(A) — halt if lambda exceeds this
       "threshold_lower": float,  # log(B) — continue if lambda below this
      }

    "degraded" fires much faster than a rolling win-rate check (typically
    8–12 trades vs 20) because it accumulates evidence from each result.
    """
    import math

    init_db()
    with _conn() as con:
        rows = con.execute(
            """
            SELECT o.settled_yes, p.side
            FROM predictions p
            JOIN outcomes o ON p.ticker = o.ticker
            ORDER BY o.settled_at DESC
            LIMIT ?
            """,
            (window,),
        ).fetchall()

    n = len(rows)
    if n < min_trades:
        return {"status": "insufficient_data", "lambda": 0.0, "trades_tested": n,
                "threshold_upper": 0.0, "threshold_lower": 0.0}

    # Wald's SPRT: accumulate log-likelihood ratio
    log_A = math.log((1 - beta) / alpha)   # upper threshold (reject H0 → degraded)
    log_B = math.log(beta / (1 - alpha))   # lower threshold (accept H0 → ok)

    llr = 0.0
    for r in rows:
        win = (r["side"] == "yes" and r["settled_yes"] == 1) or \
              (r["side"] == "no" and r["settled_yes"] == 0)
        if win:
            llr += math.log(p0 / p1)
        else:
            llr += math.log((1 - p0) / (1 - p1))

    if llr >= log_A:
        status = "ok"          # strong evidence model is working (H0 accepted)
    elif llr <= log_B:
        status = "degraded"    # strong evidence model is failing (H1 accepted)
    else:
        status = "ok"          # no decision yet — default to ok (continue trading)

    return {
        "status": status,
        "lambda": round(llr, 4),
        "trades_tested": n,
        "threshold_upper": round(log_A, 4),
        "threshold_lower": round(log_B, 4),
    }
```

- [ ] **Step 3: Wire SPRT into `is_accuracy_halted` in `paper.py`**

Update `is_accuracy_halted` to check SPRT result in addition to rolling win rate:

```python
def is_accuracy_halted() -> bool:
    """
    Return True if rolling win rate OR SPRT indicates model degradation.
    SPRT fires faster (8–12 trades); rolling win rate is the backstop (20 trades).
    """
    from utils import (ACCURACY_MIN_SAMPLE, ACCURACY_MIN_WIN_RATE,
                       ACCURACY_WINDOW_TRADES, SPRT_ALPHA, SPRT_BETA,
                       SPRT_MIN_TRADES, SPRT_P0, SPRT_P1)
    try:
        from tracker import get_rolling_win_rate, sprt_model_health

        # SPRT check (fast)
        sprt = sprt_model_health(p0=SPRT_P0, p1=SPRT_P1, alpha=SPRT_ALPHA,
                                 beta=SPRT_BETA, min_trades=SPRT_MIN_TRADES)
        if sprt["status"] == "degraded":
            _log.warning(
                "SPRT model degradation detected: lambda=%.3f <= threshold=%.3f "
                "over %d trades — halting new trades",
                sprt["lambda"], sprt["threshold_lower"], sprt["trades_tested"],
            )
            return True

        # Rolling win rate check (slower backstop)
        win_rate, count = get_rolling_win_rate(window=ACCURACY_WINDOW_TRADES)
        if count < ACCURACY_MIN_SAMPLE:
            return False
        if win_rate is not None and win_rate < ACCURACY_MIN_WIN_RATE:
            _log.warning(
                "Rolling win rate %.1f%% over %d trades below %.0f%% — halting",
                win_rate * 100, count, ACCURACY_MIN_WIN_RATE * 100,
            )
            return True
        return False
    except Exception:
        return False
```

- [ ] **Step 4: Write tests**

In `tests/test_risk_control.py`, add:

```python
class TestSPRT:
    def test_degraded_on_losing_streak(self, monkeypatch):
        """SPRT returns 'degraded' when win rate is far below expected."""
        from tracker import sprt_model_health

        # Simulate 10 consecutive losses via monkeypatched DB
        losing_rows = [{"side": "yes", "settled_yes": 0}] * 10
        monkeypatch.setattr("tracker._conn", lambda: _make_fake_conn(losing_rows))
        result = sprt_model_health(p0=0.55, p1=0.35, min_trades=5)
        assert result["status"] == "degraded"

    def test_ok_on_winning_streak(self, monkeypatch):
        """SPRT returns 'ok' when win rate matches expected."""
        from tracker import sprt_model_health

        winning_rows = [{"side": "yes", "settled_yes": 1}] * 10
        monkeypatch.setattr("tracker._conn", lambda: _make_fake_conn(winning_rows))
        result = sprt_model_health(p0=0.55, p1=0.35, min_trades=5)
        assert result["status"] == "ok"

    def test_insufficient_data_below_min_trades(self, monkeypatch):
        from tracker import sprt_model_health

        few_rows = [{"side": "yes", "settled_yes": 1}] * 3
        monkeypatch.setattr("tracker._conn", lambda: _make_fake_conn(few_rows))
        result = sprt_model_health(p0=0.55, p1=0.35, min_trades=5)
        assert result["status"] == "insufficient_data"
```

Note: `_make_fake_conn` is a helper you'll write in the test file that returns a mock connection yielding the given rows. Pattern: use `unittest.mock.MagicMock`.

- [ ] **Step 5: Run tests**

```bash
pytest tests/test_risk_control.py::TestSPRT -v
```

- [ ] **Step 6: Run full suite**

```bash
pytest --tb=short -q
```

- [ ] **Step 7: Commit**

```bash
git add tracker.py paper.py utils.py tests/test_risk_control.py
git commit -m "feat(risk): add SPRT model degradation detection (fires in ~8 trades vs 20)"
```

---

## Phase 7 — Architecture

**Acceptance criteria:** `weather_markets.py` is split into focused modules; a `BotConfig` dataclass centralises all env vars with startup validation; no global mutable cache state in module scope.

**Note on cost:** Phase 7 is the most expensive phase — each task reads files totalling 30k–60k tokens. Run tasks sequentially, not as parallel subagents. Use inline execution mode to preserve context across tasks.

---

### Task 23: Extract `ForecastCache` class from module-level globals

**Problem:** `weather_markets.py` uses five module-level mutable dicts and floats as cache storage (`_ENSEMBLE_CACHE`, `_ECMWF_CACHE`, `_FORECAST_CACHE`, `_OM_LAST_REQUEST_TS`, etc.). Tests that import the module share this state, making test order matter. Dependency injection via a class is the fix.

**Files:**
- Create: `forecast_cache.py`
- Modify: `weather_markets.py`
- Test: `tests/test_forecast_cache.py`

- [ ] **Step 1: Create `forecast_cache.py`**

```python
"""
Thread-safe in-memory forecast cache with TTL expiry.
Replaces the module-level globals in weather_markets.py.
"""
from __future__ import annotations
import threading
import time


class ForecastCache:
    """
    Thread-safe dict-based cache with per-entry TTL.
    Keys are arbitrary hashable objects; values are (data, timestamp) tuples internally.
    """

    def __init__(self, ttl_secs: float = 4 * 3600) -> None:
        self._ttl = ttl_secs
        self._store: dict = {}
        self._lock = threading.Lock()

    def get(self, key) -> object | None:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            value, ts = entry
            if time.monotonic() - ts > self._ttl:
                del self._store[key]
                return None
            return value

    def set(self, key, value) -> None:
        with self._lock:
            self._store[key] = (value, time.monotonic())

    def clear(self) -> None:
        with self._lock:
            self._store.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._store)
```

- [ ] **Step 2: Write tests for `ForecastCache`**

Create `tests/test_forecast_cache.py`:

```python
import time
from forecast_cache import ForecastCache


def test_get_returns_none_for_missing_key():
    c = ForecastCache(ttl_secs=60)
    assert c.get("missing") is None


def test_get_returns_value_within_ttl():
    c = ForecastCache(ttl_secs=60)
    c.set("k", "v")
    assert c.get("k") == "v"


def test_get_returns_none_after_ttl(monkeypatch):
    c = ForecastCache(ttl_secs=1)
    c.set("k", "v")
    # Advance monotonic clock by patching time.monotonic
    original = time.monotonic
    monkeypatch.setattr(time, "monotonic", lambda: original() + 2)
    assert c.get("k") is None


def test_clear_empties_cache():
    c = ForecastCache(ttl_secs=60)
    c.set("a", 1)
    c.set("b", 2)
    c.clear()
    assert len(c) == 0
```

- [ ] **Step 3: Replace globals in `weather_markets.py`**

At the top of `weather_markets.py`, replace:

```python
_ENSEMBLE_CACHE: dict = {}
_ENSEMBLE_CACHE_TTL = 4 * 60 * 60
_FORECAST_CACHE: dict = {}
_FORECAST_CACHE_TTL = 4 * 60 * 60
```

With:

```python
from forecast_cache import ForecastCache
_ensemble_cache = ForecastCache(ttl_secs=4 * 3600)
_forecast_cache = ForecastCache(ttl_secs=4 * 3600)
```

Update all usages throughout `weather_markets.py` to call `.get(key)` and `.set(key, value)` instead of the raw dict operations.

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_forecast_cache.py -v
pytest tests/ -k "forecast" -v
```

- [ ] **Step 5: Run full suite**

```bash
pytest --tb=short -q
```

- [ ] **Step 6: Commit**

```bash
git add forecast_cache.py weather_markets.py tests/test_forecast_cache.py
git commit -m "refactor: extract ForecastCache class from weather_markets module-level globals"
```

---

### Task 24: `BotConfig` dataclass for centralised env-var validation

**Problem:** 50+ env vars are parsed individually across `utils.py`, `paper.py`, `tracker.py`, and `main.py` with no cross-validation. Invalid combinations (e.g. `MIN_EDGE > STRONG_EDGE`) are silently accepted.

**Files:**
- Create: `config.py`
- Modify: `utils.py` (import from config.py), `main.py` (call `BotConfig.validate()` at startup)
- Test: `tests/test_config.py`

- [ ] **Step 1: Create `config.py`**

```python
"""
Central configuration dataclass. Parses and validates all environment variables.
Import individual constants from here rather than from utils.py for new code.
"""
from __future__ import annotations
import os
from dataclasses import dataclass, field


@dataclass
class BotConfig:
    kalshi_fee_rate: float = field(default_factory=lambda: float(os.getenv("KALSHI_FEE_RATE", "0.07")))
    min_edge: float = field(default_factory=lambda: float(os.getenv("MIN_EDGE", "0.07")))
    paper_min_edge: float = field(default_factory=lambda: float(os.getenv("PAPER_MIN_EDGE", "0.05")))
    strong_edge: float = field(default_factory=lambda: float(os.getenv("STRONG_EDGE", "0.30")))
    med_edge: float = field(default_factory=lambda: float(os.getenv("MED_EDGE", "0.15")))
    max_daily_spend: float = field(default_factory=lambda: float(os.getenv("MAX_DAILY_SPEND", "500.0")))
    max_days_out: int = field(default_factory=lambda: int(os.getenv("MAX_DAYS_OUT", "5")))
    drawdown_halt_pct: float = field(default_factory=lambda: float(os.getenv("DRAWDOWN_HALT_PCT", "0.20")))
    enable_micro_live: bool = field(default_factory=lambda: os.getenv("ENABLE_MICRO_LIVE", "").lower() == "true")
    min_brier_samples: int = field(default_factory=lambda: int(os.getenv("MIN_BRIER_SAMPLES", "30")))
    dashboard_password: str = field(default_factory=lambda: os.getenv("DASHBOARD_PASSWORD", ""))

    def validate(self) -> None:
        """Raise ValueError for any invalid configuration combination."""
        errors = []
        if self.min_edge > self.strong_edge:
            errors.append(f"MIN_EDGE ({self.min_edge}) > STRONG_EDGE ({self.strong_edge}) — no trades would ever qualify")
        if self.paper_min_edge > self.min_edge:
            errors.append(f"PAPER_MIN_EDGE ({self.paper_min_edge}) > MIN_EDGE ({self.min_edge})")
        if not (0.0 < self.kalshi_fee_rate < 1.0):
            errors.append(f"KALSHI_FEE_RATE ({self.kalshi_fee_rate}) must be between 0 and 1")
        if not (0.0 < self.drawdown_halt_pct < 1.0):
            errors.append(f"DRAWDOWN_HALT_PCT ({self.drawdown_halt_pct}) must be between 0 and 1")
        if self.max_days_out < 1 or self.max_days_out > 14:
            errors.append(f"MAX_DAYS_OUT ({self.max_days_out}) should be 1–14")
        if errors:
            raise ValueError("Invalid configuration:\n" + "\n".join(f"  - {e}" for e in errors))


# Module-level singleton — call BotConfig().validate() at startup
def load_and_validate() -> BotConfig:
    cfg = BotConfig()
    cfg.validate()
    return cfg
```

- [ ] **Step 2: Write tests**

Create `tests/test_config.py`:

```python
import pytest
from config import BotConfig


def test_valid_config_passes():
    cfg = BotConfig()
    cfg.validate()  # should not raise with defaults


def test_min_edge_above_strong_edge_raises():
    cfg = BotConfig()
    cfg.min_edge = 0.40
    cfg.strong_edge = 0.30
    with pytest.raises(ValueError, match="MIN_EDGE"):
        cfg.validate()


def test_fee_rate_out_of_range_raises():
    cfg = BotConfig()
    cfg.kalshi_fee_rate = 1.5
    with pytest.raises(ValueError, match="KALSHI_FEE_RATE"):
        cfg.validate()


def test_drawdown_halt_out_of_range_raises():
    cfg = BotConfig()
    cfg.drawdown_halt_pct = 0.0
    with pytest.raises(ValueError, match="DRAWDOWN_HALT_PCT"):
        cfg.validate()
```

- [ ] **Step 3: Call `load_and_validate()` at startup in `main.py`**

Near the top of `main.py`, add:

```python
from config import load_and_validate as _load_config
_bot_config = _load_config()
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_config.py -v
```

- [ ] **Step 5: Run full suite**

```bash
pytest --tb=short -q
```

- [ ] **Step 6: Commit**

```bash
git add config.py main.py tests/test_config.py
git commit -m "feat: add BotConfig dataclass with startup validation for all env vars"
```

---

### Task 25: Add `paper.py` to test coverage measurement

**Problem:** `paper.py` is in `pyproject.toml`'s coverage omit list alongside `main.py`. It contains the Kelly formula, position sizing, stop-loss, and drawdown logic — the most financially critical code — with zero coverage measurement.

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Remove `paper.py` from the omit list**

In `pyproject.toml`, change:

```toml
[tool.coverage.run]
omit = [
    "paper.py",
    "backtest.py",
    ...
]
```

To:

```toml
[tool.coverage.run]
omit = [
    "backtest.py",
    "param_sweep.py",
    "feature_importance.py",
    "pdf_report.py",
    "tests/*",
]
```

- [ ] **Step 2: Run coverage and record the baseline**

```bash
pytest --cov=paper --cov-report=term-missing -q
```

Note the current line coverage percentage. It should be nonzero since many paper.py functions are already exercised transitively through other tests.

- [ ] **Step 3: Raise the coverage floor if CI allows**

If `pytest --cov-fail-under=40` now fails due to uncovered paper.py lines, identify the gaps and add targeted tests OR lower the floor temporarily and file follow-up tasks for the gaps.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "chore: add paper.py to coverage measurement (was omitted)"
```

---

## Updated Self-Review Checklist

**Phase 0:**
- [x] Drawdown tier constants wired into `drawdown_scaling_factor()` → Task 0

**Phase 1:**
- [x] Fix pre-existing failing test → Task 1
- [x] Gate Brier scaling on MIN_BRIER_SAMPLES → Task 2
- [x] WS cache staleness TTL → Task 3
- [x] SHA-256 checksum 8→16 chars → Task 4

**Phase 2:**
- [x] Drawdown halt 50%→20% (safe now that Task 0 is done) → Task 5
- [x] Accuracy circuit breaker (rolling win rate) → Task 6
- [x] WS thread health monitoring → Task 7

**Phase 3:**
- [x] web_app.py XSS → Task 8
- [x] main.py coverage + smoke tests → Task 9
- [x] Type hints + mypy → Task 10
- [x] Tracker DB retention → Task 11
- [x] Time-decay edge 48h→8h → Task 12
- [x] Schema drift test → Task 13

**Phase 4:**
- [x] Extract cron.py → Task 14
- [x] Extract output_formatters.py → Task 15

**Phase 5 (Security):**
- [x] Dashboard HTTP Basic Auth → Task 16
- [x] Private key permission check → Task 17
- [x] Secrets scanning in CI → Task 18
- [x] fsync silent failure → Task 19

**Phase 6 (Risk Hardening II):**
- [x] Graduation gate (block ENABLE_MICRO_LIVE pre-30 trades) → Task 20
- [x] MAX_DAILY_SPEND vs balance validation → Task 21
- [x] SPRT model degradation detection → Task 22

**Phase 7 (Architecture):**
- [x] ForecastCache class (remove module globals) → Task 23
- [x] BotConfig dataclass with startup validation → Task 24
- [x] paper.py added to coverage measurement → Task 25

**Confirmed not to need fixes:** SQL injection, STOP_LOSS_MULT, micro-live daily cap, rate limiter, Kelly negative edge, ruff/mypy CI enforcement (already there).

**Trading logic ceiling:** Cannot reach A until 30+ settled trades exist. No code task addresses this — it is a data problem. When count crosses 30, run `tracker.get_edge_decay_curve()` and review `STRONG_EDGE` empirically.

## Grade Projection After All 25 Tasks

| Area | Before | After |
|------|--------|-------|
| Code Quality | B | A− |
| Architecture | B− | B+ |
| Risk Management | C+ | A− |
| Trading Logic | C | C+ (data ceiling) |
| Testing | B+ | A |
| Security | C+ | A− |
| **Overall** | **B−** | **A−** |

Trading Logic is the only category with a hard ceiling. The A− overall is achievable with the full plan. A true A requires 30+ settled trades and empirical validation of edge thresholds, station biases, and blend weights — work that cannot be done in code today.
