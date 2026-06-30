# Grade Audit — param_sweep.py

## File Status

`param_sweep.py` is **NOT dead code**. It is imported in the live path:

- `config.py:72` — `load_swept_min_edge()` is called inside `_paper_min_edge_default()`,
  which is the `default_factory` for `BotConfig.paper_min_edge`. This means every cron
  cycle that constructs a `BotConfig` (or calls the config singleton) will call this
  function. The returned value silently overrides `PAPER_MIN_EDGE` when no env var is set.
- `cron.py:2234` — `run_sweep()` is called weekly from `cmd_cron`, guarded by a
  marker-file gate (`_LAST_SWEEP_PATH`). The weekly sweep writes results that
  `load_swept_min_edge()` will pick up on the next cron cycle.
- `main.py:6999` — `run_sweep()` exposed as `py main.py sweep` for manual runs.

The file has meaningful test coverage: `tests/test_param_sweep_load.py` (8 tests for
`load_swept_min_edge`) and `tests/test_phase2_batch_m.py::TestParamSweepTemporalSplit`
(5 tests for `run_sweep` / `sweep_parameter`).

---

## Function Grades

[param_sweep.py] sweep_parameter() L:17–98  7/10 — Core sweep logic is correct; edge-field priority chain handles legacy fixtures cleanly; `won` flag used correctly (not `outcome=='yes'`); zero-total guard present; sort is stable. One gap: unknown `param_name` values silently pass all trades through unfiltered (no `else` branch and no warning), so a typo in the caller produces a misleading 100%-pass result with no indication anything went wrong.  [Confidence: Confirmed]

[param_sweep.py] load_swept_min_edge() L:101–126  — RF1 PROMOTED — see TIER 1 block below.

[param_sweep.py] run_sweep() L:129–225  7/10 — 70/30 temporal split is correct; holdout-beats-baseline gate before saving is a solid overfit guard; uses `atomic_write_json` via `safe_io` (I3 satisfied); `should_save` flag is shared across params (if either param fails holdout, nothing is saved — conservative and correct); `load_paper_trades` failure is caught and logged at WARNING. One gap: the `settled` filter at L:149 accepts trades with `"won" in t` regardless of `outcome` — a trade dict with `won=True` but no outcome field is treated as settled; this is edge-case-only but the comment says "we know outcomes" which the filter does not enforce. Second gap: `should_save` starts as `True` and only becomes `False` when a holdout comparison is possible — if `val_trades` is empty (all 100% of settled trades happen to fall in train due to rounding), `should_save` stays `True` and results are written with no holdout validation; `int(len(settled)*0.70)` on 20 trades gives `split_idx=14`, leaving 6 in holdout, so this is unlikely in practice but not guarded.  [Confidence: Confirmed]

---

## TIER 1 Promotion — load_swept_min_edge() RF1

[param_sweep.py] load_swept_min_edge() L:101–126  ★ T1 (promoted from T2 via RF1)
Score: 5/10  |  Confidence: Confirmed
AC: N/A (utility function, no formal acceptance criteria)
Red flag: RF1 — bare `except Exception: pass` at L:124–125 silently swallows every
  error — JSON decode errors, permission errors, type errors on `float(best["value"])` —
  with no log at WARNING or above. The caller in config.py also has a bare
  `except Exception: pass` at L:82–83, so a corrupt `param_sweep_results.json` will
  silently fall through to the default `PAPER_MIN_EDGE=0.05` with zero operator
  visibility.
Invariants: I8 N/A (reporting/config function, not a trade gate itself); I5 N/A.
STRENGTHS:
• `[0.03, 0.15]` clamp on the returned value is a solid safety net — prevents a
  sweep artefact from setting PAPER_MIN_EDGE to an extreme value.
• `min_trades` floor prevents low-sample overfitting from propagating to live config.
• Returns `None` cleanly when file is absent — caller handles the None case.
• Good test coverage (7 meaningful tests in test_param_sweep_load.py).
WEAKNESSES:
• line 124–125: `except Exception: pass` — a corrupt JSON file, a missing `"value"`
  key, or a float-conversion failure produces NO log. The operator sees PAPER_MIN_EDGE
  silently revert to 0.05 with no indication that the sweep results file is corrupt.
• line 122: the `[0.03, 0.15]` range check falls inside the try block; if it raises
  (it won't with current types, but with a future refactor) it would also be silently
  swallowed.
• The function returns `None` both when the file is absent (expected) and when parsing
  fails (unexpected) — callers cannot distinguish the two cases.
FAILURE SCENARIO:
  `data/param_sweep_results.json` is written with a partial flush (e.g., a cron kill
  mid-write — though `atomic_write_json` prevents this in the happy path, a manual edit
  or a direct file write from a test could produce corrupt JSON). `json.loads()` raises
  `json.JSONDecodeError`. The bare `except Exception: pass` swallows it. `config.py`'s
  `_paper_min_edge_default()` also catches and passes. The bot starts with
  `PAPER_MIN_EDGE=0.05` instead of the intended value. No log entry anywhere. The
  operator has no way to know the sweep results were discarded.
FIX:
  param_sweep.py:124–126 — replace:
    ```python
    except Exception:
        pass
    return None
    ```
  with:
    ```python
    except Exception as exc:
        _log.warning("load_swept_min_edge: failed to read sweep results: %s", exc)
    return None
    ```
VERDICT: fix before live (the RF1 silent-failure is the only change needed; the rest is
  solid)

---

## Summary

| Function | Score | Tier | Action |
|---|---|---|---|
| `sweep_parameter()` | 7/10 | T2 | Keep as-is; consider adding unknown-param warning |
| `load_swept_min_edge()` | 5/10 | T2→T1 (RF1) | Fix: add `except Exception as exc: _log.warning(...)` |
| `run_sweep()` | 7/10 | T2 | Keep as-is; minor `settled` filter pedantry only |

**File-level note:** `load_swept_min_edge()` feeds directly into `BotConfig.paper_min_edge`
via `config.py:_paper_min_edge_default()`. A corrupt results file silently reverts the
bot to `PAPER_MIN_EDGE=0.05` with zero log output across two catch-and-pass boundaries.
Adding a single `_log.warning(...)` in this function is the minimum viable fix.
