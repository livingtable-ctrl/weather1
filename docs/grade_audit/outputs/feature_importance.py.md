# Grade Audit — feature_importance.py

## File-Level Assessment: ACTIVE (not dead code)

`feature_importance.py` is imported in the live trade path:
- `main.py:2159` — `record_feature_contribution` called inside trade placement
- `tracker.py:2412` — `update_outcome` called inside `sync_outcomes()` settlement loop
- `cron.py:649` — `prune_feature_log` called in Monday weekly sweep
- `web_app.py:2018` — `get_feature_summary` called for dashboard display
- `main.py:3848` — `get_feature_summary` called by `cmd_features()`

All imports are deferred (inside `try` blocks or function bodies), so a crash in this
module will not halt the trade process. The module is a **logging/analytics side-car**,
not on the critical execution path. It does not gate trades, write to the DB, or affect
Kelly sizing. Classified TIER 2 throughout.

---

## Function Grades

[feature_importance.py] record_feature_contribution() L:20–46  6/10 — Exceptions caught
and logged at DEBUG only (RF1 threshold not met for TIER 2; this is analytics-only and
trade-path callers wrap in their own try/except, but the silent DEBUG swallow means the
operator cannot diagnose a broken data/ directory without enabling debug logging).
[Confidence: Confirmed]
FIX: feature_importance.py:46 — change `_log.debug(` to `_log.warning(` so failures
surface in normal log output.

[feature_importance.py] update_outcome() L:49–68  6/10 — Same DEBUG-only exception
suppression as record_feature_contribution; a filesystem error (permissions, disk full)
will silently drop every settlement outcome record with no operator visibility.
[Confidence: Confirmed]
FIX: feature_importance.py:68 — change `_log.debug(` to `_log.warning(`.

[feature_importance.py] prune_feature_log() L:71–89  6/10 — Exception swallowed at
DEBUG; if the prune fails (e.g., disk full, encoding error) the log will grow without
bound and the operator will not know — exact same pattern as above. The happy-path logic
(keep last N lines, write atomically with write_text) is functionally correct. Note:
write_text is not atomic (no os.replace), so a crash mid-write could corrupt the file,
but this is an analytics log not a trading record; low severity.  [Confidence: Confirmed]
FIX: feature_importance.py:88 — change `_log.debug(` to `_log.warning(`.

[feature_importance.py] get_feature_summary() L:92–160  7/10 — Solid design: two-pass
parse (outcome records then feature entries), de-duplicates by ticker keeping latest
timestamp, falls back to inline outcome for legacy records, skips non-numeric feature
values, filters by min_trades. One gap: the outer except at L:142 swallows any parsing
failure at DEBUG, so a corrupted jsonl silently returns empty dict to the dashboard.
Not a trading risk (caller in web_app.py and main.py are display-only), but the DEBUG
swallow is a pattern that should be WARNING.  [Confidence: Confirmed]
FIX: feature_importance.py:142 — change `_log.debug(` to `_log.warning(`.

---

## Cross-Cutting Note

All four functions share the identical pattern: `except Exception as exc: _log.debug(...)`.
This is a copy-paste suppression style. For a pure analytics side-car it is defensible
(trade execution is never blocked), but DEBUG means the operator cannot distinguish
"feature log is silently broken" from "working fine" without enabling debug logging.
A single WARNING log line on failure for each function is the minimum fix.

The module has meaningful test coverage (test_phase3_batch_d.py TestFeatureImportancePruning)
for prune_feature_log — 4 tests covering trim, no-op, missing file, and cron wiring.
record_feature_contribution, update_outcome, and get_feature_summary have no dedicated
tests but are analytics-only with no trading impact.

---

## Summary

| Function | Score | Key Issue |
|---|---|---|
| record_feature_contribution | 6/10 | DEBUG-only exception suppression |
| update_outcome | 6/10 | DEBUG-only exception suppression |
| prune_feature_log | 6/10 | DEBUG-only exception suppression; non-atomic write |
| get_feature_summary | 7/10 | DEBUG-only exception suppression; no test for parse path |

No red flags (RF1–RF6) fired: exceptions are caught and logged (at DEBUG rather than
WARNING, but the functions are not on the trading decision path and do not gate trades).
No TIER 1 promotions required.
