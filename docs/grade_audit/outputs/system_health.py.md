# Grade Audit — system_health.py
_Auditor: claude-sonnet-4-6 | Date: 2026-06-29 | Tier: 2_

---

## File Summary

140 lines. Pre-trade health gate. Four items: one NamedTuple, two sub-checkers, one
orchestrator. No TIER 1 functions (no trade placement, sizing, settlement, or
balance/drawdown accounting). All functions graded at TIER 2.

No red flags fired. No TIER 1 promotions.

---

## Module-Level Constants

```
API_LATENCY_WARN_MS = float(os.getenv("HEALTH_API_LATENCY_WARN_MS", "5000"))  # L:15
```

Defined but **never used** anywhere in the file. The latency check was removed or never
implemented. This is dead configuration — the env var has no effect. LOW/INFO finding.

---

## Function Grades

```
[system_health.py] HealthStatus L:21–23  9/10 — Clean NamedTuple; `reason` typed str forces
  explicit empty-string on healthy case, preventing None propagation.  [Confidence: Confirmed]
```

---

```
[system_health.py] _check_api_failure_rate() L:26–64  7/10 — Correctly reads api_requests,
  computes error rate, fails closed on exception with ERROR log; one gap: HTTP 4xx client
  errors (e.g. 429 rate-limit) are not counted because only `status_code >= 500` or
  `error is not None` triggers — a sustained 429 storm (rate-limited by Kalshi) would
  read as "healthy" even while all trades are being rejected.  [Confidence: Confirmed]
FIX: system_health.py:44–45 — change condition to also flag 429:
  `1 for r in rows if (r[0] is not None and (r[0] >= 500 or r[0] == 429)) or r[1] is not None`
```

---

```
[system_health.py] _check_platt_sanity() L:67–82  6/10 — Checks A <= 0 for signal
  inversion, fails closed on exception; silent gap: if A is float('nan') or float('inf'),
  the comparison `a <= 0` evaluates False (NaN comparisons in Python always return False),
  so a corrupt Platt model with NaN A passes the sanity check and proceeds to trade.
  [Confidence: Confirmed]
FIX: system_health.py:73–78 — add finiteness guard before the <=0 check:
  `import math`
  `if not math.isfinite(a) or a <= 0:`
```

---

```
[system_health.py] check_system_health() L:85–139  7/10 — Well-structured orchestrator;
  fails closed on all error paths; psutil ImportError silently skips CPU/memory rather
  than halting (correct — psutil is optional per docstring); outer except catches
  unexpected errors; one minor gap: `cpu_percent(interval=None)` returns the cached value
  from psutil's last internal poll rather than a fresh measurement — could be stale by
  minutes in a long-running process, making the CPU warning unreliable.
  [Confidence: Confirmed]
```

---

## Orphan Constant

```
[system_health.py] API_LATENCY_WARN_MS L:15 — defined, env-configurable, never read by
  any function in this file. Either the latency check was removed or was never
  implemented. The env var HEALTH_API_LATENCY_WARN_MS has zero effect. Safe to remove
  the constant (and document the removal so the env var can be cleaned from .env if set).
```

---

## Summary Table

| Function | Score | Tier | Red Flag | Fix Required |
|---|---|---|---|---|
| HealthStatus | 9/10 | T2 | NONE | No |
| _check_api_failure_rate() | 7/10 | T2 | NONE | Optional (429 gap) |
| _check_platt_sanity() | 6/10 | T2 | NONE | Yes (NaN passthrough) |
| check_system_health() | 7/10 | T2 | NONE | No |

**File median: 7/10. One fix required (_check_platt_sanity NaN guard). One low/info
finding (API_LATENCY_WARN_MS orphan). No red flags. No TIER 1 promotions.**
