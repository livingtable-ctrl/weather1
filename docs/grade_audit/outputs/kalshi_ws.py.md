# Grade Audit — kalshi_ws.py

**File status:** ACTIVE — imported in live trade path (`order_executor.py:736`, `cron.py:919`).
NOT dead code. `order_executor.py` uses `get_cached_mid_price` to enrich order opportunities
with a fresher mid-price before trade placement. `cron.py` starts `KalshiWebSocket` and polls
`get_ws_health`. The module is a supporting utility for trade placement and is therefore graded
as TIER 2 (no direct Kelly/balance/sizing logic lives here).

---

## Module-Level State

`_orderbook`, `_cache_lock`, `_ws_alive`, `_ws_last_message_ts`, `_ws_state_lock` are
module-level globals. This is correct for a background-thread singleton cache. No deduction.

---

## Function Grades

[kalshi_ws.py] `_set_ws_alive()` L:38–41  8/10 — Minimal threadsafe setter; correct lock
usage; no observable gap. [Confidence: Confirmed]

[kalshi_ws.py] `_record_ws_message()` L:44–47  7/10 — Correct lock usage; `__import__("time")`
inside the lock is unusual style (the module-level `import time` is already present at L:19)
and slightly inefficient, but not a correctness issue. [Confidence: Confirmed]
FIX: kalshi_ws.py:47 — replace `__import__("time").monotonic()` with `time.monotonic()`
(the stdlib `time` module is already imported at the top of the file).

[kalshi_ws.py] `get_ws_health()` L:50–64  8/10 — Reads both state variables under the same
lock in one block, computes derived `idle_secs` outside the lock (safe — local copy), returns
clean dict. Minor: deferred `import time` and `from utils import WS_CACHE_TTL_SECS` on every
call; could be top-level. No correctness issue. [Confidence: Confirmed]

[kalshi_ws.py] `parse_message()` L:70–130  7/10 — Handles all three known message types
(`orderbook_snapshot`, `orderbook_delta`, `ticker`) and returns None for unknowns. Float
coercion of `yes_bid_str` / `yes_ask_str` at L:113–114 is guarded by a try/except that
returns 0.0 on failure. One gap: when `yes_levels` is non-empty but `yes_levels[0]` is
missing an element (e.g. `[[]]`), `yes_levels[0][0]` at L:89 raises `IndexError` which is
not caught here — it would propagate to the caller in `_ws_listener`. In `_ws_listener` the
per-message exception at L:304 is caught at DEBUG level (RF1 candidate — see note below).
The inner try/except does catch it, so no data loss, but at DEBUG the operator is blind.
[Confidence: Confirmed]

[kalshi_ws.py] `update_orderbook_cache()` L:136–161  6/10 — Correct lock usage for the
in-memory dict. However, the on-disk write reads the existing JSON file _inside_ the lock
(`_cache_lock`) which is correct for consistency. The exception handler at L:160–161 logs at
DEBUG only — this fires RF1 (exception caught without WARNING-or-above log) because a failing
`atomic_write_json` (disk full, permissions error, etc.) would be silently swallowed with
only a DEBUG entry. Operators would not know the disk cache is diverging from in-memory state.
Promoted to full TIER 1 block below for RF1.

[kalshi_ws.py] `read_orderbook_cache()` L:164–169  7/10 — Silent empty-dict fallback on any
exception (including permissions errors, corrupt JSON). The bare `except Exception` at L:167
has no log at all — RF1. Promoted to full TIER 1 block below for RF1.

[kalshi_ws.py] `get_cached_mid_price()` L:172–198  8/10 — Checks in-memory first then falls
back to disk, correctly validates freshness. Nested function `_is_fresh` is clean. Lock
acquired for in-memory read only (not holding it during disk I/O — correct). Minor: disk
fallback calls `read_orderbook_cache()` which itself swallows exceptions silently, so stale
disk data would just return None rather than propagating. [Confidence: Confirmed]

[kalshi_ws.py] `build_subscribe_message()` L:204–217  9/10 — Pure function, no side effects,
correct structure, test coverage confirmed. [Confidence: Confirmed]

[kalshi_ws.py] `KalshiWebSocket.__init__()` L:328–334  8/10 — Simple data init, correct.
[Confidence: Confirmed]

[kalshi_ws.py] `KalshiWebSocket.subscribe()` L:336–340  7/10 — Guards against calling after
start via RuntimeError. Deduplicates via `set()`. Minor: no log when tickers are added.
[Confidence: Confirmed]

[kalshi_ws.py] `KalshiWebSocket.start()` L:342–349  8/10 — Idempotent guard. Daemon thread
means it will be killed if the main process exits without calling stop(). Correct for this
use case. [Confidence: Confirmed]

[kalshi_ws.py] `KalshiWebSocket.stop()` L:351–358  7/10 — Calls `loop.call_soon_threadsafe`
to stop the loop, then joins thread. Minor gap: if `_loop` is not yet set (start() called
but thread hasn't had time to set `self._loop`), the `if self._loop` check at L:354 is False
and the loop is never stopped; thread join would then block for `timeout` seconds then return
with the thread still running. Rare race but possible in fast-stop scenarios.
[Confidence: Likely]

[kalshi_ws.py] `KalshiWebSocket._run()` L:360–370  7/10 — Creates a new event loop and runs
the async listener. Catches top-level exceptions and logs at ERROR. Loop closed in `finally`.
Minor: `_set_ws_alive(False)` is in the `finally` of `_ws_listener`, not here — if
`run_until_complete` itself raises before `_ws_listener` reaches its `finally`, `_ws_alive`
might remain True. In practice `_ws_listener` sets alive=True only after successful connect,
so this is unlikely. [Confidence: Possible]

---

## RF1 Promoted Functions (Full TIER 1 Blocks)

---

[kalshi_ws.py] `update_orderbook_cache()` L:136–161  ★ T1 (promoted from T2 for RF1)
Score: 5/10  |  Confidence: Confirmed
AC: N/A (TIER 2 file, no explicit ACs)
Red flag: RF1 — `except Exception as exc: _log.debug("update_orderbook_cache: %s", exc)` (L:160–161)
Invariants: I3 — PASS (uses `safe_io.atomic_write_json`); I2 — N/A (not balance data)
STRENGTHS:
• In-memory update is fully lock-protected.
• Delegates to `safe_io.atomic_write_json` for crash-safe disk writes.
• Delta merge preserves existing mid_price data rather than clobbering it.
WEAKNESSES:
• line 160–161: Exception caught at DEBUG. A disk-full, permission error, or WinError
  that cannot self-heal would permanently diverge in-memory from on-disk cache with no
  operator-visible log entry. `order_executor.py` reads the disk cache as fallback; silent
  divergence means stale prices are served from disk after process restart.
• line 152–155: Reads the existing JSON file from disk inside `_cache_lock`. If the file
  is large (many tickers), this adds latency to the lock, blocking `get_cached_mid_price`.
  Not a correctness bug but an unbounded-growth concern.
FAILURE SCENARIO:
Disk is full. `atomic_write_json` raises OSError. `_log.debug(...)` fires but nobody sees
it (default log level is INFO). Next process restart reads stale on-disk cache. Operator has
no indication the write failed — no WARNING in logs, no metric.
FIX:
kalshi_ws.py:161 — replace `_log.debug("update_orderbook_cache: %s", exc)` with
`_log.warning("update_orderbook_cache: disk write failed: %s", exc)`
VERDICT: fix before live (RF1 — silent disk failure)

---

[kalshi_ws.py] `read_orderbook_cache()` L:164–169  ★ T1 (promoted from T2 for RF1)
Score: 5/10  |  Confidence: Confirmed
AC: N/A
Red flag: RF1 — bare `except Exception:` at L:167 with zero log at any level
Invariants: N/A
STRENGTHS:
• Returns safe empty dict on failure — callers degrade gracefully.
• Simple, single responsibility.
WEAKNESSES:
• line 167–168: The exception is caught and completely silenced — no log whatsoever.
  Corrupt JSON (truncated atomic write), permissions error, or wrong encoding would
  return `{}` silently. `get_cached_mid_price` then falls through to return None, and
  `order_executor` proceeds without a cached mid-price. No operator visibility.
FAILURE SCENARIO:
`orderbook_cache.json` becomes corrupt (power loss during write, though `atomic_write_json`
should prevent this). `read_orderbook_cache()` returns `{}` silently. All mid-price lookups
from disk return None. `order_executor` proceeds without WS price enrichment with no log
entry to explain why.
FIX:
kalshi_ws.py:167–168 — change to:
```python
    except Exception as exc:
        _log.warning("read_orderbook_cache: failed to read cache: %s", exc)
        return {}
```
VERDICT: fix before live (RF1 — completely silent failure)

---

## `_ws_listener()` — Inner Exception Logging Note

[kalshi_ws.py] `_ws_listener()` L:220–313  6/10 — The per-message exception handler at
L:304–305 (`_log.debug("kalshi_ws: parse error: %s", exc)`) fires RF1 for the same reason:
a malformed message causes a silent DEBUG log that operators cannot see at default log level.
This is lower severity than the cache functions (data loss vs. bad message) but should be
WARNING for observability. The outer reconnect handler at L:307–311 correctly logs at WARNING.
[Confidence: Confirmed]
FIX: kalshi_ws.py:305 — change `_log.debug("kalshi_ws: parse error: %s", exc)` to
`_log.warning("kalshi_ws: parse error on message: %s", exc)` — or at minimum INFO so
operators know malformed messages are arriving.

---

## Summary

| Function | Score | Notes |
|---|---|---|
| `_set_ws_alive` | 8 | Clean threadsafe setter |
| `_record_ws_message` | 7 | Redundant `__import__("time")` — use top-level import |
| `get_ws_health` | 8 | Good; deferred imports minor style issue |
| `parse_message` | 7 | `yes_levels[0][0]` uncaught IndexError; rescued by caller's try/except at DEBUG |
| `update_orderbook_cache` | 5 | **RF1** — disk write failure silent at DEBUG |
| `read_orderbook_cache` | 5 | **RF1** — no log at all on exception |
| `get_cached_mid_price` | 8 | Correct two-layer lookup with freshness check |
| `build_subscribe_message` | 9 | Pure, correct, tested |
| `KalshiWebSocket.__init__` | 8 | Clean init |
| `KalshiWebSocket.subscribe` | 7 | RuntimeError guard good; no log on add |
| `KalshiWebSocket.start` | 8 | Idempotent, daemon thread correct |
| `KalshiWebSocket.stop` | 7 | Race if stop() called before `_loop` is assigned |
| `KalshiWebSocket._run` | 7 | Top-level exception caught; minor alive-state edge case |
| `_ws_listener` (inner) | 6 | Per-message RF1 at DEBUG; reconnect correctly at WARNING |

**File median: 7.** Three RF1 violations in `update_orderbook_cache`, `read_orderbook_cache`,
and `_ws_listener` inner handler. All are fixable with one-line log-level changes. No
fundamental design flaws. The module is well-structured for a background WS cache.
