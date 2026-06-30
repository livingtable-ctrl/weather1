# Grade Audit — monte_carlo.py

**Date:** 2026-06-29
**File:** `monte_carlo.py` (518 lines)
**Auditor:** claude-sonnet-4-6 (subagent)

---

## Summary Table

| Function | Tier | Score | Verdict |
|---|---|---|---|
| `_cholesky()` | T1 | 8/10 | keep as-is |
| `_repair_psd()` | T1 | 7/10 | keep as-is |
| `load_correlations_from_backtest()` | T1 | 6/10 | fix before live |
| `save_correlations()` | T1 | 4/10 | fix before live |
| `_load_dynamic_correlations()` | T1 | 6/10 | fix before live |
| `get_city_correlation()` | T1 | 7/10 | keep as-is |
| `simulate_portfolio()` | T1 | 6/10 | fix before live |
| `portfolio_var()` | T1 | 7/10 | keep as-is |
| `run_stress_test()` | T2 | 6/10 | fix before live |

---

## TIER 1 Functions

---

### `_cholesky()` L:18–39  ★ T1

```
Score: 8/10  |  Confidence: Confirmed
AC: AC1 PASS — returns None when v <= 1e-8 (non-PD diagonal entry); also returns None
    when L[j][j] == 0.0 (division guard)
Red flag: NONE
Invariants: none directly applicable
STRENGTHS:
• Clean sentinel-return contract: None on any PD failure, no exception propagation.
• Raised threshold from 1e-12 to 1e-8 (annotated as F6) — correctly catches
  near-singular matrices before sqrt of a tiny positive causes downstream NaN.
• Zero-denominator guard at L[j][j] == 0.0 prevents division by zero even if the
  v <= 1e-8 check somehow passed on an earlier diagonal.
WEAKNESSES:
• line 23: No guard that `mat` is square or that `len(mat[i]) == n`. A ragged input
  (e.g. position_correlation_matrix returns a 3x3 but one row is length 2) would
  raise IndexError rather than returning None. This is an unguarded edge case.
• No log when returning None — the caller (simulate_portfolio) does log at WARNING,
  so the lack of a log here is acceptable.
VERDICT: keep as-is
```

---

### `_repair_psd()` L:42–53  ★ T1

```
Score: 7/10  |  Confidence: Confirmed
AC: AC1 PASS — _repair_psd is called in simulate_portfolio before a second Cholesky
    attempt (L:349–361).
Red flag: NONE
Invariants: none directly applicable
STRENGTHS:
• Iterative diagonal-shift strategy is robust: doubles eps each iteration, capped at
  60 iterations (max diagonal shift ~0.06 * original, which is acceptable for
  correlation matrices).
• Returns the best-effort result even if all 60 attempts fail; caller detects this via
  the final _cholesky() == None check.
WEAKNESSES:
• line 53: If all 60 iterations exhaust without making the matrix PD, the function
  returns the partially-shifted matrix silently — caller still gets a non-PD matrix
  and must detect it via _cholesky(). This is handled correctly in simulate_portfolio
  but the lack of any log here makes diagnosing pathological inputs harder.
• No guard that the input is square or that rows are the right length (same as
  _cholesky() concern).
FAILURE SCENARIO:
  A 10×10 correlation matrix where two positions in the same city have identical
  entries (near-zero eigenvalue after position_correlation_matrix sets diagonal 1.0).
  60 doublings adds ~0.06 total shift; this is usually enough for the
  correlation-matrix domain. In practice, nearly-identical rows would need a much
  larger shift. The 60-iteration cap could be exhausted without converging, causing
  fallback to independent draws — acceptable degradation, but operator sees no log.
VERDICT: keep as-is
```

---

### `load_correlations_from_backtest()` L:86–108  ★ T1

```
Score: 6/10  |  Confidence: Confirmed
AC: N/A (AC4 applies to save_correlations, not this function)
Red flag: RF1 — line 106: `except Exception: pass` — silently swallows all read
    and parse errors with no log at WARNING or above.
Invariants: none directly applicable
STRENGTHS:
• Falls back to _HARDCODED_CORR on any failure — the function never crashes.
• Validates types (isinstance check for int|float) before inserting into result.
• Validates the separator format (len(parts) == 2) — rejects malformed keys.
WEAKNESSES:
• line 106: Bare `except Exception: pass` fires RF1. If correlations.json is corrupt
  or contains unexpected data, the operator has no visibility. They may trade with
  stale hardcoded correlations for days without knowing the dynamic file is broken.
FAILURE SCENARIO:
  correlations.json is partially written by a prior crash (save_correlations uses
  direct write_text with no atomicity). The partial JSON raises json.JSONDecodeError.
  load_correlations_from_backtest swallows it silently, returns hardcoded correlations.
  Operator checks logs and sees nothing. Monte Carlo runs with wrong correlations
  indefinitely.
FIX:
  monte_carlo.py:106-107 — replace:
    except Exception:
        pass
  with:
    except Exception as exc:
        _log.warning("load_correlations_from_backtest: failed to read %s: %s", _CORR_PATH, exc)
VERDICT: fix before live
```

---

### `save_correlations()` L:111–125  ★ T1

```
Score: 4/10  |  Confidence: Confirmed
AC: AC4 FAIL — line 125: uses `_CORR_PATH.write_text(...)` directly, not an atomic
    write path. A crash between open() and close() (or Windows Defender locking the
    file, or a KeyboardInterrupt) leaves correlations.json corrupt or zero-byte.
Red flag: NONE (no exception caught without log; the function simply does not handle
    any exception at all)
Invariants: I3 FAIL — does not use os.replace(); writes directly to the target path.
STRENGTHS:
• Handles both frozenset and string keys — robust key normalisation.
• Creates parent directory with parents=True, exist_ok=True before writing.
• Sorts key components so CityA|CityB and CityB|CityA produce the same canonical key.
WEAKNESSES:
• line 125: Direct write_text() violates I3 / AC4. On Windows, a crash or scan
  during the write produces a zero-byte or partially-written JSON file. On the next
  load_correlations_from_backtest() call, the bare `except Exception: pass` silently
  falls back to hardcoded values. The operator has no idea correlations were lost.
• No try/except at all — if _CORR_PATH.write_text() raises (disk full, permission
  error), the exception propagates uncaught to the caller, which may be cron.py.
FAILURE SCENARIO:
  cron.py calls save_correlations() after computing updated city-pair correlations.
  Windows Defender opens a file handle on correlations.json for scanning at the exact
  moment write_text() is writing. write_text() raises PermissionError. No catch, so
  the exception surfaces to cron.py. Cron continues but correlations are lost. On the
  next bot start, load_correlations_from_backtest() reads the zero-byte file (or the
  partial write), gets a JSONDecodeError, silently falls back to hardcoded values.
FIX:
  Use safe_io.atomic_write_json() (already used elsewhere in the codebase):
  monte_carlo.py:120-125 — replace body with:
    import json
    from safe_io import atomic_write_json
    _CORR_PATH.parent.mkdir(parents=True, exist_ok=True)
    serialisable: dict[str, float] = {}
    for k, v in city_pairs_dict.items():
        key = "|".join(sorted(k)) if isinstance(k, frozenset) else str(k)
        serialisable[key] = float(v)
    atomic_write_json(_CORR_PATH, serialisable)
VERDICT: fix before live
```

---

### `_load_dynamic_correlations()` L:128–152  ★ T1

```
Score: 6/10  |  Confidence: Confirmed
AC: N/A (AC1 covers _cholesky and _repair_psd; this is the data loader)
Red flag: RF1 — line 152: `except Exception: return None` — swallows all read/parse
    errors with no log at WARNING or above.
Invariants: none directly applicable
STRENGTHS:
• Returns None explicitly on file-absent, empty-dict, and empty-result cases — clean
  sentinel contract.
• Validates each entry (len(parts)==2, isinstance(val, int|float)) — corrupt entries
  are skipped rather than crashing.
WEAKNESSES:
• line 151-152: `except Exception: return None` is a RF1. If learned_correlations.json
  (the ML-updated file) is corrupt, the caller gets None, falls back to hardcoded, and
  the operator has no idea the live-learned correlations are unavailable.
• Redundant `from pathlib import Path` import inside the function when Path is already
  imported at the module level — minor style issue, not a correctness problem.
FAILURE SCENARIO:
  After a run that updated learned_correlations.json, a disk error corrupts the file.
  _load_dynamic_correlations() raises json.JSONDecodeError, swallows it, returns None.
  get_city_correlation() uses _HARDCODED_CORR. Monte Carlo runs with wrong
  correlations. No log entry, no alert.
FIX:
  monte_carlo.py:151-152 — replace:
    except Exception:
        return None
  with:
    except Exception as exc:
        _log.warning("_load_dynamic_correlations: failed to read learned_correlations.json: %s", exc)
        return None
VERDICT: fix before live
```

---

### `get_city_correlation()` L:155–174  ★ T1

```
Score: 7/10  |  Confidence: Confirmed
AC: N/A
Red flag: NONE
Invariants: none directly applicable
STRENGTHS:
• Module-level cache (_dynamic_corr_loaded / _dynamic_corr_cache) prevents repeated
  disk I/O on every call — correctly lazy-loaded once per process.
• Layered fallback: dynamic file → hardcoded → 0.0. Safe at every level.
• Handles symmetric lookup correctly via frozenset.
WEAKNESSES:
• line 164-166: The cache is loaded exactly once per process lifetime. If
  learned_correlations.json is written by a concurrent cron job after the cache has
  already been populated (loaded=True, cache=old), the in-memory cache is never
  refreshed. Stale correlations persist for the entire process lifetime.
  This is a known trade-off (acceptable given cron frequency), but there is no comment
  explaining the intentional staleness — a cold reader might treat this as a bug.
• Tests reset `_dynamic_corr_loaded = False` directly, which confirms the cache
  invalidation is done by test setup rather than the production code — consistent with
  intentional behavior.
VERDICT: keep as-is
```

---

### `simulate_portfolio()` L:177–422  ★ T1

```
Score: 6/10  |  Confidence: Confirmed
AC: AC2 PASS — empty open_trades returns early with valid zero-VaR dict (L:203-213);
    all-past-date trades returns early with a different valid dict (L:305-318).
AC: AC3 FAIL — days_out is never read from any trade dict. Same-day trades (days_out=0)
    are modelled with the identical Monte Carlo horizon as multi-day trades. The comment
    on L:239 acknowledges same-day vs multi-day but takes no action.
Red flag: NONE
Invariants: none directly applicable
STRENGTHS:
• Robust close_time-first then target_date fallback for past-date exclusion —
  correctly handles trades before 2026-05-28 that have NULL close_time.
• win_prob clamped to [0.05, 0.9] with debug log (L:277-287) — stale/bad entry_prob
  never drives extreme sim outcomes.
• Cholesky fallback to independent draws with WARNING log (L:352-360) — correlation
  matrix failure degrades gracefully without crashing.
• _repair_psd called before second Cholesky attempt (L:349-350) — AC1 satisfied.
• probit threshold approach for correlated normals is mathematically correct.
• The inner simulation loop uses precomputed thresholds and trade_params list for
  efficiency — avoids repeated dict lookups in the hot path.
WEAKNESSES:
• line 239 (AC3 FAIL): days_out is not read; same-day positions are modelled with
  the same infinite horizon as 3-day positions. A 99-cent same-day position that
  resolves in 4 hours is modelled as if it could still swing widely. This overstates
  VaR for same-day-heavy portfolios and could trigger incorrect risk halts.
• line 221: `_DEFAULT_CORRELATIONS[(c1, c2)] = corr` mutates the module-level
  _DEFAULT_CORRELATIONS dict at call time. If get_recent_city_correlations() returns
  bad data (e.g. correlation > 1.0), it is written into _DEFAULT_CORRELATIONS
  permanently for the process lifetime, affecting all subsequent simulations.
  No validation of correlation range is performed here.
• line 291: `net_payout_per = 1.0 - winnings_per * KALSHI_FEE_RATE` computes the
  net payout correctly for YES-side wins but does not distinguish YES vs NO side for
  payout calculation. For a NO trade at entry_price=0.20, winnings_per = 0.80
  (correct per contract) — the formula uses entry_price regardless of side, which is
  correct because entry_price on a NO trade already reflects the NO cost.
  This is correct but non-obvious to a cold reader.
• No test covers the same-day horizon modelling gap (AC3 FAIL).
FAILURE SCENARIO (AC3):
  Portfolio has 6 same-day trades at cost $10 each ($60 total), all close in 2 hours.
  All have win_prob=0.85 (METAR lock-in — sharp probability). simulate_portfolio runs
  them through the full Monte Carlo as if they were long-horizon positions. The 5th
  percentile outcome overstates loss potential. If portfolio_var() is used as a risk
  gate, it could block new multi-day trade entry when none is warranted.
FIX (AC3 guidance):
  At L:258, after extracting the trade, read days_out:
    days_out = t.get("days_out", 1)
  For days_out == 0, set win_prob to a sharper value (0.90+ if METAR locked)
  OR exclude from VaR computation with a note in the output dict.
VERDICT: fix before live
```

---

### `portfolio_var()` L:425–445  ★ T1

```
Score: 7/10  |  Confidence: Confirmed
AC: AC2 PASS (empty list → simulate_portfolio returns 0.0 via pnl_distribution absent
    → portfolio_var returns 0.0 at L:441).
Red flag: NONE
Invariants: none directly applicable
STRENGTHS:
• Clean single-responsibility wrapper — only responsibility is confidence-level
  indexing into the distribution.
• Returns 0.0 on absent distribution (not NaN, not crash).
• Default confidence=0.05 matches the preamble's 95% VaR convention.
• Default n_simulations=5000 — appropriate resolution for tail estimation.
WEAKNESSES:
• line 444: `idx = max(0, min(len(dist) - 1, int(len(dist) * confidence)))` rounds
  down via int(). For n=5000, confidence=0.05: idx = int(250) = 250, which is the
  251st-lowest outcome — the 5th percentile is slightly overestimated (less negative
  than true 5th percentile). This is a minor numerical imprecision, not a material
  risk error.
• No guard that `0 < confidence < 1`. Passing confidence=1.5 would index beyond
  len(dist)-1 (clamped by min, so no crash) but the result is meaningless and silent.
• Tests in test_signal_quality.py cover: returns float, empty=0.0, negative for
  loss scenario, higher win_prob gives less-negative VaR. Good coverage breadth.
  No test for confidence parameter edge cases.
VERDICT: keep as-is
```

---

## TIER 2 Functions

---

```
[monte_carlo.py] run_stress_test() L:467–517  6/10 — Correctly computes worst-case
  P&L but calls get_balance() directly rather than _drawdown_snapshot(), violating
  I8 reporting vs trading-gate semantics; however, this function is only used for
  display/reporting, so I8 technically does not apply (intentional per preamble).
  Real issue: balance=0.0 guard at L:514 avoids division by zero, but if trades list
  is empty after city-filter the function returns 0 loss with below_halt=False, which
  is correct and informative. No silent failure paths. Missing guard: if cfg is None
  (unknown scenario name) the function returns an error dict correctly. No RF fired.
  [Confidence: Confirmed]
```

---

## File-Level Observations

1. **AC3 (same-day horizon modelling) is the most impactful unresolved issue.** With
   ~99 same-day settled trades, same-day positions may be a significant fraction of the
   open portfolio. VaR overstating their risk could cause the risk gate to incorrectly
   block multi-day entries.

2. **save_correlations() non-atomic write (AC4 FAIL, score 4/10)** is the most urgent
   fix. A crash during write corrupts the correlation file, which load_ then silently
   ignores. The system trades with stale hardcoded correlations indefinitely.

3. **RF1 fires in two functions** (load_correlations_from_backtest, _load_dynamic_correlations).
   Both catch broad exceptions without logging. This is a maintainability hazard: a
   corrupt correlation file produces no operator-visible signal.

4. **Test coverage is broad** across _cholesky, simulate_portfolio, portfolio_var, and
   get_city_correlation. The main gap is AC3 (no test distinguishes same-day vs
   multi-day trade modelling).
