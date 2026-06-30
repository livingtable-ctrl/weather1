# Grade Audit — regime.py
_Graded 2026-06-29 | Model: claude-sonnet-4-6_

---

## Dead-code / Import Status

**FILE STATUS: NOT dead code — imported in the live trade path.**

`regime.py` is imported inside `weather_markets.py` at line 5516 via a lazy import
inside `analyze_trade()`. The `detect_regime()` return value feeds `_regime_info`, and
`_regime_info.get("confidence_boost", 1.0)` directly multiplies `ci_adjusted_kelly`
at line 6314. This means `detect_regime()` is on the live Kelly-sizing path for every
multi-day trade. The file is **not** dead code; every function matters.

What imports it:
- `weather_markets.py:5516` — `from regime import detect_regime as _detect_regime`
  (inside `analyze_trade()`, inside a `try/except Exception: pass` block)

Whether removal is safe: Not safe to remove. The `confidence_boost` multiplier and
the `volatile` regime skip gate (`weather_markets.py:5979`) both depend on the output
of `detect_regime()`. Removal would silently disable both features (Kelly boost for
heat_dome/cold_snap/blocking_high, and the hard skip for volatile markets).

---

## Function Grades

[regime.py] detect_regime() L:10–98  ★ T2 PROMOTED TO T1 BLOCK (RF6 + live Kelly path)

Score: 5/10  |  Confidence: Confirmed

AC: N/A (TIER 2 file — no acceptance-criteria checklist)

Red flag: RF6 — zero meaningful test coverage for a function that multiplies
`ci_adjusted_kelly` at `weather_markets.py:6314`. No test file imports or calls
`detect_regime` directly. The function lives on the live Kelly-sizing path for every
non-METAR multi-day trade.

Invariants:
- I5 PARTIAL: `confidence_boost` feeds Kelly at weather_markets.py:6314 without a
  finite guard at the boundary. `detect_regime` always returns a float literal, so
  NaN/None cannot originate here — but the `_boost()` helper could in principle return
  a non-finite value if `days_out` is non-numeric (e.g. None). No guard exists; the
  risk is low given current callers but not zero.
- I7 N/A: regime.py does not inspect ensemble members directly; it receives pre-computed
  stats from `ens_stats` / `ensemble_stats`.

STRENGTHS:
• Empty-dict guard at line 35 — returns "normal" / 1.0 safely when no ensemble data.
• `_boost()` inner function cleanly separates horizon scaling from regime thresholds,
  making the logic easy to read and test in isolation.
• `horizon_scale` clamps to [0.0, 1.0] via `max/min` — no runaway multiplier.
• All five regime branches are exhaustive and mutually exclusive given the check order
  (heat_dome and cold_snap check std < 5.0 first, so blocking_high's std < 3.0 never
  fires redundantly).
• Description strings include the numeric values that triggered them — helpful for
  log-driven debugging.

WEAKNESSES:
• line 48: `days_out` is used as an arithmetic operand without a type or range guard.
  If `days_out` is `None` (caller passes `None` after a parsing failure upstream),
  the expression `1.0 - (None - 3) / 7.0` raises `TypeError`. The lazy import is
  wrapped in `try/except Exception: pass` at weather_markets.py:5515–5520, so the
  exception would be silently swallowed and `_regime_info` would remain `{}` — meaning
  no volatile-regime skip and no confidence boost/penalty. This is a silent failure
  that could allow a volatile trade through without the hard skip gate.
• line 82–84: `volatile` returns `confidence_boost = round(_boost(0.80), 4)` — a value
  less than 1.0. The caller at weather_markets.py:5979 hard-skips the trade rather than
  relying on this multiplier, which is correct. However, if the hard-skip gate is ever
  removed or refactored, the 0.80 multiplier would silently become the only protection,
  providing only 20% Kelly reduction for a 12°F+ spread scenario. No comment cross-
  references the hard-skip gate at line 5979 — the two layers are not obviously connected.
• Zero test coverage: `detect_regime()` has no unit tests. Given that it multiplies
  Kelly sizing for every multi-day non-METAR trade, this is a RF6 violation.
• The `_boost()` helper is not separately testable as a module-level function —
  it is a nested closure. This makes it harder to unit-test the horizon-scaling math.
• `ensemble_stats.get("mean", 60.0)` defaults to 60°F when key absent. This is
  reasonable but undocumented — a caller passing an incomplete dict (e.g. only `std`)
  would silently get a "normal" or "volatile" classification without any "mean" data,
  which could be surprising. Same for `std` defaulting to 5.0.

FAILURE SCENARIO:
`analyze_trade()` is called for a market where `days_out=None` (e.g. a same-day market
where `days_out` was not yet resolved). The call `_detect_regime(city, ens_stats or {},
None)` reaches line 48: `1.0 - (None - 3) / 7.0` → `TypeError`. The `except Exception:
pass` at weather_markets.py:5519 silently swallows it. `_regime_info` stays `{}`.
At line 5979, `_regime_info.get("regime") == "volatile"` is False, so a volatile market
is not skipped. At line 5974, `confidence_boost` defaults to 1.0 — no Kelly penalty.
The trade is placed at full Kelly despite 12°F+ ensemble spread.

Note: same-day trades also reach this code path before `metar_locked` is set (METAR
lock-in happens inside analyze_trade earlier). The volatile skip at line 5979 guards
only `not metar_locked`, so this specific scenario affects non-METAR markets.

FIX:
regime.py:47–48 — guard `days_out` before arithmetic:
```python
    _days = days_out if isinstance(days_out, (int, float)) and days_out >= 0 else 0
    horizon_scale = (
        max(0.0, min(1.0, 1.0 - (_days - 3) / 7.0)) if _days > 3 else 1.0
    )
```

Also add a test file `tests/test_regime.py` covering:
- heat_dome detection (mean=100, std=2, days_out=1)
- cold_snap detection (mean=20, std=2, days_out=1)
- blocking_high detection (mean=60, std=2, days_out=1)
- volatile detection (mean=60, std=15, days_out=1)
- normal detection
- empty ensemble_stats returns "normal" / 1.0
- days_out=None does not raise

VERDICT: fix before live

---

## File Summary

| Function | Score | Tier | Notes |
|---|---|---|---|
| `detect_regime()` | 5/10 | T1 (promoted) | RF6 — no tests; days_out=None TypeError silently swallowed |

**Overall file health: 5/10.**
The logic inside `detect_regime()` is clean and the regime classification rules are
reasonable. The critical gap is zero test coverage on a function that directly multiplies
Kelly sizing for every multi-day non-METAR trade. The `days_out=None` type guard issue
is a secondary concern (real risk only when caller is buggy) but worth closing. Add
`tests/test_regime.py` and the `days_out` guard as the two highest-priority fixes.
