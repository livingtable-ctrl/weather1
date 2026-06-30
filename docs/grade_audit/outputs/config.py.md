# Grade Audit — config.py
Audited: 2026-06-29 | Auditor: claude-sonnet-4-6 | Branch: claude/jolly-chandrasekhar-7d8447

## Summary

| Function | Score | Tier | Red Flags |
|---|---|---|---|
| `_env_float` | 8/10 | T2 | none |
| `_env_int` | 8/10 | T2 | none |
| `_paper_min_edge_default` | 4/10 | T1 (promoted) | RF1 ×2 |
| `BotConfig` (dataclass fields) | 7/10 | T2 | none |
| `BotConfig.from_env` | 8/10 | T2 | none |
| `BotConfig.validate` | 5/10 | T2 | none |
| `load_and_validate` | 6/10 | T2 | none |
| `get_config` | 6/10 | T2 | none |
| `reset_config` | 9/10 | T2 | none |

---

## TIER 1 Promoted Function

### RF1 PROMOTION — `_paper_min_edge_default`

```
[config.py] _paper_min_edge_default() L:43–84  ★ T2→T1 (RF1 promotion)
Score: 4/10  |  Confidence: Confirmed
AC: N/A (no acceptance criteria defined for config helpers)
Red flag: RF1 — line 68: bare `except Exception: pass` with no log; line 83: bare `except Exception: pass` with no log
Invariants: N/A (not a trade-execution function)
STRENGTHS:
• @functools.cache prevents repeated file reads and ensures the warning about overrides
  is logged exactly once per process — good operator UX.
• Env var takes highest precedence; hard-coded default is last resort. Priority chain is clear.
• Range guard (0.03 ≤ opt ≤ 0.15) prevents walk_forward_params.json from supplying a
  ludicrous min_edge value.
WEAKNESSES:
• line 68: `except Exception: pass` — if walk_forward_params.json is present but
  corrupted, the failure is silently swallowed. Operator has no idea the file is being
  skipped. The function falls through to the param_sweep path and then to 0.05 with
  zero indication of a data problem. RF1 fires.
• line 83: `except Exception: pass` — if param_sweep import fails for any reason
  (missing module, bad return type, network error), silently falls through to the
  hardcoded 0.05 default. Again no log. RF1 fires.
• The `from param_sweep import load_swept_min_edge` inside the function body means
  every call (pre-cache) triggers a module import. After caching this is harmless, but
  it couples this config helper to a dead-code-candidate module (param_sweep.py).
• The function is frozen by @functools.cache. If walk_forward_params.json is written
  mid-process (e.g., a backtest writes new params), the cached value never updates.
  No comment warns of this. Fine for the current single-process architecture but fragile.
FAILURE SCENARIO:
  walk_forward_params.json exists on disk but was written with a float key ("optimal_min_edge": null)
  or the JSON is truncated by a crash mid-write. json.loads() raises JSONDecodeError.
  The bare except swallows it. BotConfig gets paper_min_edge=0.05 (hardcoded default),
  not the operator-intended walk-forward optimum. No log line. Operator sets up the file,
  runs the bot, sees unexpected paper trade behaviour, has no way to diagnose from logs.
FIX:
  config.py:68 — replace `except Exception: pass` with:
      except Exception as exc:
          _log.warning("walk_forward_params.json read failed, skipping: %s", exc)
  config.py:83 — replace `except Exception: pass` with:
      except Exception as exc:
          _log.warning("param_sweep.load_swept_min_edge failed, skipping: %s", exc)
VERDICT: fix before live (RF1 — silent exception swallows are unacceptable in a live system)
```

---

## TIER 2 Functions

```
[config.py] _env_float() L:19–28  8/10 — Raises clear ValueError on bad input with env var
name and value in the message; re-raises with `from None` to suppress noisy chain. One gap:
does not log the error before raising — caller might catch the ValueError silently and the
operator would never see which variable was bad. Minor, since the raise propagates to startup.
[Confidence: Confirmed]
```

```
[config.py] _env_int() L:31–40  8/10 — Identical structure to _env_float; same strengths and
same minor gap (no log before raise). Correct for all realistic inputs.  [Confidence: Confirmed]
```

```
[config.py] BotConfig (dataclass fields) L:87–165  7/10 — All 27 fields correctly delegate
to typed _env_float/_env_int helpers or direct os.getenv(). Defaults are reasonable and
commented where non-obvious. One gap: `kelly_cap` has no upper-bound validation anywhere in
validate() — a misconfigured KELLY_CAP=2.0 would silently allow double-Kelly overbetting.
`max_positions_per_date` and `max_same_day_positions` have no positivity check (KELLY_CAP
and MAX_SAME_DAY_POSITIONS=0 would be catastrophic). The dataclass itself is correct; the
gap is in validate().  [Confidence: Confirmed]
```

```
[config.py] BotConfig.from_env() L:168–176  8/10 — Clears lru_cache before constructing so
monkeypatched env vars in tests propagate correctly. Single responsibility, no side effects.
Gap: load_and_validate() (L207) calls BotConfig() directly, not BotConfig.from_env(), so the
cache-clear is bypassed when load_and_validate() is used in tests.  [Confidence: Confirmed]
```

```
[config.py] BotConfig.validate() L:178–202  5/10 — Catches the most dangerous combination
(min_edge > strong_edge), and validates fee_rate and drawdown_halt_pct ranges. However
multiple critical trading thresholds are NOT validated:
  • kelly_cap — no check for 0 < kelly_cap ≤ 1.0; KELLY_CAP=2.0 silently overbets
  • max_positions_per_date / max_same_day_positions — no positivity check; 0 disables caps entirely
  • breakeven_trigger_pct — no range check; >1.0 means the trigger never fires
  • partial_exit_pct — no 0 < x < 1 check
  • min_kelly_fraction — no check against kelly_cap (min_kelly_fraction > kelly_cap is nonsensical)
Also: the check `paper_min_edge > min_edge` raises an error, but paper_min_edge > min_edge is
operationally valid (paper trading can be set more conservatively). This check may false-alarm.
[Confidence: Confirmed]
FIX: config.py:199 — before `if errors: raise`, add guards:
    if not (0.0 < self.kelly_cap <= 1.0):
        errors.append(f"KELLY_CAP ({self.kelly_cap}) must be between 0 and 1 (exclusive/inclusive)")
    if self.max_positions_per_date < 1:
        errors.append(f"MAX_POSITIONS_PER_DATE ({self.max_positions_per_date}) must be >= 1")
    if self.max_same_day_positions < 1:
        errors.append(f"MAX_SAME_DAY_POSITIONS ({self.max_same_day_positions}) must be >= 1")
    if not (0.0 < self.breakeven_trigger_pct < 1.0):
        errors.append(f"BREAKEVEN_TRIGGER_PCT ({self.breakeven_trigger_pct}) must be between 0 and 1")
    if not (0.0 < self.partial_exit_pct < 1.0):
        errors.append(f"PARTIAL_EXIT_PCT ({self.partial_exit_pct}) must be between 0 and 1")
```

```
[config.py] load_and_validate() L:205–209  6/10 — Convenience startup function that creates
and validates config. Gap: uses BotConfig() directly instead of BotConfig.from_env(), so
the _paper_min_edge_default lru_cache is NOT cleared. If called in tests after monkeypatching
PAPER_MIN_EDGE env var but after a prior BotConfig() call, the cached value is returned.
This is inconsistent with the doc comment on from_env() which explicitly describes the
cache-clear. Minor but a latent test reliability hazard.  [Confidence: Confirmed]
FIX: config.py:207 — replace `cfg = BotConfig()` with `cfg = BotConfig.from_env()`
```

```
[config.py] get_config() L:216–221  6/10 — Lazy singleton initialised on first call. No log
when first constructed — operator cannot see from logs whether config was loaded from env
or stale. More importantly: if called before dotenv is loaded (e.g., an import-time call in
another module), the singleton is frozen with defaults rather than .env values, and subsequent
dotenv loading has no effect. No guard or warning for this. In the current single-process
startup (which loads dotenv before any trading logic), this is not an active bug, but the
function provides no safety net if startup order changes.  [Confidence: Possible]
```

```
[config.py] reset_config() L:224–228  9/10 — Clears both the module singleton and the
lru_cache. Simple, correct, side-effect-free. Used in tests to restore clean state between
runs. No weaknesses.  [Confidence: Confirmed]
```

---

## File-Level Notes

**Missing validation for key trading thresholds (Confirmed):** `validate()` is the only
startup gate for misconfigured env vars. As noted above, `kelly_cap`, `max_positions_per_date`,
`max_same_day_positions`, `breakeven_trigger_pct`, and `partial_exit_pct` have no range checks.
A typo in .env (e.g., `KELLY_CAP=2` instead of `0.25`) would pass validation silently and
allow double-Kelly bets for the entire session. This is the highest-priority fix in the file.

**param_sweep coupling (Possible):** `_paper_min_edge_default` imports from `param_sweep.py`
at runtime. The tier2.md module flags `param_sweep.py` as a dead-code candidate. If it is
removed, this import silently fails (bare except) and falls through to the hardcoded default.
The fix to RF1 above (logging the exception) would at least make this visible in logs.

**Startup order fragility (Possible):** `get_config()` is a lazy singleton. If any module
calls `get_config()` at import time (before dotenv loads), the singleton is frozen with
defaults. No comment in the function warns of this constraint. Not an active bug in the
current codebase, but worth a one-line comment.
