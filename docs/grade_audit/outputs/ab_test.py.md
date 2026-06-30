# Grade Audit — ab_test.py
Graded: 2026-06-29
File: ab_test.py (217 lines)
All functions are TIER 2 (none on TIER 1 list) except `get_active_variant` which fires RF1 and is promoted to a full TIER 1 block.

---

## TIER 2 Functions

[ab_test.py] `_load_test_state()` L:34–43  8/10 — Reads JSON state from disk, catches all exceptions with WARNING and returns empty dict; safe fallback.  [Confidence: Confirmed]

[ab_test.py] `_save_test_state()` L:46–53  8/10 — Delegates to `safe_io.atomic_write_json`, catches exceptions with WARNING; correct delegation pattern.  [Confidence: Confirmed]

[ab_test.py] `ABTest.__init__()` L:63–101  7/10 — Initializes variant state, persists `max_trades_per_variant` and variant `value` to disk on any change; minor gap is that re-naming an existing variant (same key, different value) does NOT update the persisted `value` field since the `if v not in self._state` guard skips already-seen variants.  [Confidence: Confirmed]

[ab_test.py] `ABTest.pick_variant()` L:103–123  7/10 — Round-robin on fewest-trades with random tie-breaking (F7 fix); clean invariant that `active` variants are all guaranteed present in `self._state` because `__init__` initializes them first.  [Confidence: Confirmed]

[ab_test.py] `ABTest.record_outcome()` L:125–155  6/10 — `best_win_rate` computation at L139–143 includes all non-disabled variants with `trades > 0`, meaning a freshly-exhausted variant is compared against variants that may have far fewer trades and therefore noisier win rates; a variant could be incorrectly auto-disabled or unfairly spared based on a low-sample comparator — not a cash-at-risk bug but contaminates A/B conclusions.  [Confidence: Confirmed]
FIX: ab_test.py:139 — Add `and self._state[v]["trades"] >= self.max_trades_per_variant` to the comparator filter so only fully-exhausted variants are included in `best_win_rate`.

[ab_test.py] `ABTest.summary()` L:157–170  8/10 — Display-only; iterates state, skips `_meta`, computes win_rate and avg_edge with division-by-zero guard via `max(trades, 1)`.  [Confidence: Confirmed]

[ab_test.py] `list_all_summaries()` L:173–178  8/10 — Reads all `*.json` files under `_AB_TEST_DIR`, returns raw state dicts; display only, no trade decisions.  [Confidence: Confirmed]

---

## TIER 1 Promoted Block — RF1

[ab_test.py] `get_active_variant()` L:181–216  ★ T1 (promoted from TIER 2 via RF1)
Score: 5/10  |  Confidence: Confirmed
AC: N/A (no explicit acceptance criteria for TIER 2 files)
Red flag: RF1 — `except Exception as exc: _log.debug("get_active_variant: %s", exc)` (L214–215) — exception caught without WARNING or above.
Invariants: None of I1–I10 directly apply (no SQL, no balance, no Kelly).

STRENGTHS:
- Correctly reads `_max_trades` from persisted `_meta` rather than hardcoding, so changes to `max_trades_per_variant` propagate without code changes.
- Random tie-breaking (F7) prevents alphabetically-first variant from always being picked during tie.
- Returns `("control", None)` fallback on all failure paths — caller is informed the test is absent.
- Persisted `value` key (L4-A fix) means callers get the actual threshold value, not None, when the test is healthy.

WEAKNESSES:
- line 214–215: `_log.debug(...)` on the exception — any structural error in the state dict (missing `"trades"` key, wrong type, truncated JSON that somehow passed `_load_test_state`) causes a silent fallback to `("control", None)` with no operator-visible warning. An operator has no way to detect that A/B test selection silently failed without enabling DEBUG logging.
- line 213: `state[chosen].get("value")` returns `None` if the `"value"` key was never written (state files created before the L4-A fix). The caller receives `None` as a trading threshold value. If any caller uses this for a min-edge or Kelly parameter without a `None` check, a trade could be placed with a broken threshold. There is no guard here or in callers documented in this file.
- The function duplicates the variant-selection logic from `ABTest.pick_variant()` rather than instantiating `ABTest` and calling `pick_variant()`. Any future change to selection logic must be updated in two places.

FAILURE SCENARIO:
State file exists on disk but was written before the L4-A `"value"` key was added to `ABTest.__init__`. `_load_test_state` succeeds (valid JSON), `active` list is non-empty, `chosen` is selected, `state[chosen].get("value")` returns `None`. Caller receives `("control", None)`. If caller does e.g. `if edge >= variant_value:` it raises `TypeError: '>=' not supported between instances of 'float' and 'NoneType'` at trade-time. Because this is a TIER 2 file and A/B tests are not on the live critical path today, no trade is blocked — but the error would surface only at runtime.

FIX:
ab_test.py:214–215 — change `_log.debug(...)` to `_log.warning("get_active_variant: unexpected error for %r: %s", test_name, exc)` so operators see the failure in normal log output.
ab_test.py:213 — add a fallback: `val = state[chosen].get("value"); return (chosen, val) if val is not None else ("control", None)` — or at minimum document that callers must guard against `None`.

VERDICT: fix before live (if A/B tests are ever wired into the live trade path; currently advisory only)

---

## Module-level Note

The specific note for `ab_test.py` in `tier2.md` is: "Check whether A/B test variant assignment is stable across cron cycles for the same market. A round-robin that re-assigns on each cycle would contaminate variant data."

**Stability assessment:** Assignment IS stable across cron cycles. `pick_variant()` / `get_active_variant()` select based on fewest cumulative trades recorded in the persisted JSON state file — not on a per-call counter or random assignment. Each call to `record_outcome()` increments the trade count and saves to disk, so the variant with fewest trades advances toward the next, and the same market re-analyzed in a later cron cycle would likely pick a different variant (the one still behind). This is correct bandit behavior.

However, there is no binding between a specific market ticker and a variant. The same market could get variant A on cycle 1 and variant B on cycle 2 if `record_outcome` was called in between for another market. This is not a stability bug — it is the intended bandit design — but it means the A/B test measures "what happens when we use threshold X on N trades" not "what threshold X does on market M specifically". This is acceptable for the stated goal of parameter comparison but worth documenting.

**Verdict on stability:** No contamination from re-assignment within a single cron run. Cross-run stability is by-design bandit, not a bug.

---

## Summary Table

| Function | Score | Tier | Flag |
|---|---|---|---|
| `_load_test_state` | 8/10 | T2 | — |
| `_save_test_state` | 8/10 | T2 | — |
| `ABTest.__init__` | 7/10 | T2 | — |
| `ABTest.pick_variant` | 7/10 | T2 | — |
| `ABTest.record_outcome` | 6/10 | T2 | fix needed |
| `ABTest.summary` | 8/10 | T2 | — |
| `list_all_summaries` | 8/10 | T2 | — |
| `get_active_variant` | 5/10 | T1 (promoted) | RF1 |

**File median: 7.5/10.** No active cash-at-risk bugs; A/B tests are not wired into the live trade path today. Two fixes recommended before any live wiring.
