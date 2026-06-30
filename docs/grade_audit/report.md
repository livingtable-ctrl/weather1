# Grade Audit — Final Synthesis Report

**Date:** 2026-06-29
**Branch:** claude/jolly-chandrasekhar-7d8447
**Files graded:** 33
**Methodology:** 33 independent line-by-line grade agents; each agent graded TIER 1 functions (any function on the live trade path) and sampled TIER 2 functions. Findings below are derived solely from agent outputs — no source files were re-read during synthesis.

---

## Decision Matrix

| System area | Relevant files | Verdict | Blocking finding (if NOT YET) | Severity | Fix time estimate |
|---|---|---|---|---|---|
| Trade placement — same-day METAR path | metar.py, weather_markets.py, order_executor.py | NOT YET | `_metar_lock_in()` (weather_markets.py L4721): between markets receive METAR lock-in from current temp, not daily extreme — AC3 invariant violation | HIGH | 30 min |
| Trade placement — multi-day pipeline | weather_markets.py, ml_bias.py, nws.py, calibration.py | NOT YET | `get_ensemble_temps()` (weather_markets.py L2724): silent `except Exception: pass` swallows model fetch failures; `_get_obs_station()` (nws.py L162): silent `except Exception: return None` on station lookup | HIGH | 30 min (2 one-liners) |
| Kelly sizing and position caps | weather_markets.py, cron.py | NOT YET | `_cmd_cron_body()` (cron.py): kill switch not checked per-order inside `_auto_place_trades`; kill switch activated mid-placement cannot stop orders 2-N | HIGH | 1–2 h (order_executor.py fix) |
| Balance and drawdown accounting | paper.py, order_executor.py | NOT YET | `_dynamic_kelly_cap()` (paper.py L511) and `_method_kelly_multiplier()` (paper.py L541): silent `except Exception: return 50.0 / 1.0` with no log; RF2 lock violations in `undo_last_trade()` and `_mark_needs_manual_settle()` | HIGH | 1 h |
| Settlement and 24h gate | cron.py, tracker.py, paper.py | NOT YET | `auto_settle_paper_trades()` (paper.py): 24h close_time gate absent from auto-settle path; trades can settle minutes after market close — I4 invariant violation | HIGH | 30 min |
| Calibration and SQL separation | tracker.py, calibration.py, ml_bias.py | NOT YET | `calibrate_and_save()` (calibration.py L423): bare `except Exception: pass` silently overwrites hand-tuned condition weights; `apply_ml_prob_correction()` (ml_bias.py L373): model inference exception logged at DEBUG only | MEDIUM | 30 min (2 one-liners) |
| Atomic writes and data integrity | safe_io.py, paper.py, monte_carlo.py | NOT YET | `atomic_write_json_with_history()` (safe_io.py L126–157): history block unwrapped; failure skips the primary write entirely; `save_correlations()` (monte_carlo.py L125): non-atomic `write_text()` with no exception handling corrupts file on crash | HIGH | 1 h |
| Kill switch and circuit breaker | cron.py, circuit_breaker.py, alerts.py | NOT YET | `check_alerts()` (alerts.py L178): RF1 `except Exception: continue` silently disables price monitoring; daily loss check dead (integer timestamp vs. string prefix L413) | MEDIUM | 30 min |
| API integration and idempotency | kalshi_client.py, order_executor.py | GO | No active T1 bugs; RF1 in `_find_order_by_client_id()` requires WARNING logs but does not block order placement | LOW | 15 min |
| Graduation gate | paper.py, tracker.py | NOT YET | `brier_score()` (tracker.py L922): `except Exception: pass` in paper-trades fallback silently returns None to graduation gate — can suppress graduation trigger | HIGH | 15 min |

---

## Bottom 10 Functions Overall

All findings with score ≤5, ranked by score ascending (lowest first), TIER 1 before TIER 2 at equal scores.

| Rank | File | Function | Score | Tier | Failure scenario (one line) | Fix |
|---|---|---|---|---|---|---|
| 1 | execution_log.py | `add_live_loss()` L:280–311 | 5/10 | T1 | DB lock (common on Windows with Defender) returns 0.0 and silently disables the daily loss gate | Replace `warnings.warn` with `_log.warning`; raise or re-check fallback return value |
| 2 | notify.py | `_send_discord()` L:99–126 | 5/10 | T1 | Unguarded `import requests` propagates ImportError to main.py scan loop, crashing the iteration | Wrap import in try/except ImportError at module level |
| 3 | output_formatters.py | `cmd_history()` L:36–387 | 5/10 | T1 | Silent bare except drops Model Analytics block; operator sees clean output while calibration data is corrupt | Add `logger.warning(...)` to both except blocks |
| 4 | output_formatters.py | `cmd_balance()` L:395–412 | 5/10 | T1 | Silent bare except drops paper balance failure; ledger corruption invisible to operator | Add `logger.warning(...)` to except block |
| 5 | output_formatters.py | `cmd_positions()` L:420–483 | 5/10 | T1 | Per-position except swallows forecast/ML failures; open-position exit signals masked with "—" | Add `logger.warning(...)` to per-position except |
| 6 | climatology.py | `fetch_historical()` L:52–108 | 5/10 | T1 | Silent except when cache exists; stale climatology data used as blend component with zero operator visibility | Add `_log.warning(...)` to except block |
| 7 | ab_test.py | `get_active_variant()` L:181–216 | 5/10 | T1 | DEBUG-level except swallow; A/B variant selection failures invisible at INFO; also returns None from pre-L4A state files | Raise to `_log.warning`; add None guard |
| 8 | cloud_backup.py | `_find_google_drive()` L:18–92 | 5/10 | T1 | Two bare `except Exception: pass` blocks swallow registry lookup failures; Drive path silently falls through to None | Add `_log.debug(...)` to both except blocks |
| 9 | schema_validator.py | `validate_market()` L:23–98 | 5/10 | T2 | Out-of-range bid/ask logged at DEBUG not WARNING; silent price corruption passes through to trade path | Raise log level to WARNING on out-of-range prices |
| 10 | schema_validator.py | `validate_nws_response()` L:134–157 | 5/10 | T2 | Type-mismatch branch logs warning but never sets `ok=False`; function returns True on structurally broken NWS response | Add `ok = False` before the warning branch |

---

## Red Flags Summary

Every red flag (RF1–RF6) that fired across all files.

| RF# | File | Function | Line | Exact code quote |
|---|---|---|---|---|
| RF1 | safe_io.py | `project_root()` | L:41 | `except Exception: pass` |
| RF1 | safe_io.py | `atomic_write_json_with_history()` | L:148,153 | history_file.write_text and prune loop unguarded — no try/except, no WARNING |
| RF1 | tracker.py | `brier_score()` | L:1022 | `except Exception:\n        pass` |
| RF1 | paper.py | `place_paper_order()` | L:864 | `except Exception: pass` (A/B test update block) |
| RF2 | paper.py | `undo_last_trade()` | L:2557 | `_load()` and `_save()` called without `_DATA_LOCK` |
| RF2 | paper.py | `_mark_needs_manual_settle()` | L:2593 | `_load()` and `_save()` called without `_DATA_LOCK` |
| RF1 | paper.py | `check_exit_targets()` | L:1351 | `except Exception: continue` (no log) |
| RF1 | paper.py | `check_model_exits()` | L:2001 | `except Exception: continue` (no log) |
| RF1 | paper.py | `is_accuracy_halted()` | L:2127,2142 | `except Exception: pass` (no log; halt could fail to fire) |
| RF1 | paper.py | `get_unrealized_pnl_paper()` | L:2891 | `except Exception: continue` (no log; partial MTM silently returned) |
| RF1 | paper.py | `_dynamic_kelly_cap()` | L:511 | `except Exception: return 50.0` (no log) |
| RF1 | paper.py | `_method_kelly_multiplier()` | L:541 | `except Exception: return 1.0` (no log) |
| RF1 | ml_bias.py | `apply_ml_prob_correction()` | L:373 | `_log.debug("apply_ml_prob_correction(%s): %s", city, exc)` |
| RF1 | ml_bias.py | `_load_temperature_scale()` | L:413 | `except Exception: return None` (no log at any level) |
| RF1 | calibration.py | `calibrate_and_save()` | L:423 | `except Exception:\n            pass  # corrupt / missing` |
| RF1 | nws.py | `_get_obs_station()` | L:162 | `except Exception: return None` |
| RF1 | monte_carlo.py | `load_correlations_from_backtest()` | L:106 | `except Exception: pass` |
| RF1 | monte_carlo.py | `_load_dynamic_correlations()` | L:151–152 | `except Exception: return None` |
| RF1 | alerts.py | `check_alerts()` | L:178 | `except Exception: continue` |
| RF1 | execution_log.py | `add_live_loss()` | L:307 | `warnings.warn(f"add_live_loss DB write failed: {exc}")` |
| RF1 | execution_log.py | `get_order_by_id()` | L:477 | `_log.debug("get_order_by_id: %s", exc)` |
| RF1 | config.py | `_paper_min_edge_default()` | L:68 | `except Exception: pass` |
| RF1 | config.py | `_paper_min_edge_default()` | L:83 | `except Exception: pass` |
| RF1 | climatology.py | `fetch_historical()` | L:94 | `except Exception:` (no `_log.warning`, exception never surfaced) |
| RF1 | notify.py | `_send_discord()` | L:124–125 | `except Exception: pass` |
| RF1 | notify.py | `alert_strong_signal()` | L:221–222 | `except Exception: successes.append(False)` |
| RF1 | notify.py | `send_system_alert()` | L:285–286 | `except Exception: successes.append(False)` |
| RF1 | output_formatters.py | `cmd_history()` | L:255–256 | `except Exception: pass` |
| RF1 | output_formatters.py | `cmd_history()` | L:386–387 | `except Exception: pass` |
| RF1 | output_formatters.py | `cmd_balance()` | L:408–409 | `except Exception: paper_str = ""` |
| RF1 | output_formatters.py | `cmd_positions()` | L:462–463 | `except Exception: cur_prob_str = dim("—")` |
| RF1 | ab_test.py | `get_active_variant()` | L:214–215 | `except Exception as exc: _log.debug("get_active_variant: %s", exc)` |
| RF1 | cloud_backup.py | `_find_google_drive()` | L:48 | `except Exception: pass` |
| RF1 | cloud_backup.py | `_find_google_drive()` | L:68 | `except Exception: pass` |
| RF5 | main.py | `build_client()` | L:923 | `env=os.getenv("KALSHI_ENV", "demo")` duplicates default already at L400 and L405 |
| RF5 | main.py | `_analyze_once()` | L:1576 | `_ARB_CITY_LIMIT = 25.0` hardcoded in display/paper path |
| RF1 | weather_markets.py | `get_ensemble_temps()` | L:2724 | `except Exception: pass` (no log at any level) |
| RF1 | weather_markets.py | `_metar_lock_in()` | L:4721 | outer handler logs at `_log.debug(...)` not WARNING |
| RF1 | kalshi_client.py | `_find_order_by_client_id()` | L:392 | `except Exception: pass` (resting lookup) |
| RF1 | kalshi_client.py | `_find_order_by_client_id()` | L:403 | `except Exception: pass` (filled lookup) |
| RF1 | param_sweep.py | `load_swept_min_edge()` | L:124–125 | `except Exception: pass` |
| RF1 | kalshi_ws.py | `update_orderbook_cache()` | L:160–161 | `except Exception as exc: _log.debug("update_orderbook_cache: %s", exc)` |
| RF1 | kalshi_ws.py | `read_orderbook_cache()` | L:167–168 | bare `except Exception:` with no log at any level |
| RF1 | kalshi_ws.py | `_ws_listener()` | L:304–305 | `_log.debug("kalshi_ws: parse error: %s", exc)` |
| RF6 | regime.py | `detect_regime()` | L:10–98 | No test file imports or calls `detect_regime()` directly; function multiplies `ci_adjusted_kelly` at weather_markets.py:6314 |

**Total: RF1 fires = 42 | RF2 = 2 | RF5 = 2 | RF6 = 1**

---

## Systemic Weaknesses

### 1. Silent Exception Swallowing (RF1)

Bare `except Exception: pass/continue/return <default>` with no log at WARNING or above appears in **42 locations across 20 of 33 files**.

Complete occurrence list:
- safe_io.py: `project_root()`, `atomic_write_json_with_history()`
- tracker.py: `brier_score()`
- paper.py: `place_paper_order()`, `check_exit_targets()`, `check_model_exits()`, `is_accuracy_halted()`, `get_unrealized_pnl_paper()`, `_dynamic_kelly_cap()`, `_method_kelly_multiplier()`
- ml_bias.py: `apply_ml_prob_correction()`, `_load_temperature_scale()`
- calibration.py: `calibrate_and_save()`
- nws.py: `_get_obs_station()`
- monte_carlo.py: `load_correlations_from_backtest()`, `_load_dynamic_correlations()`
- alerts.py: `check_alerts()`
- execution_log.py: `add_live_loss()`, `get_order_by_id()`
- config.py: `_paper_min_edge_default()` (x2)
- climatology.py: `fetch_historical()`
- notify.py: `_send_discord()`, `alert_strong_signal()`, `send_system_alert()`
- output_formatters.py: `cmd_history()` (x2), `cmd_balance()`, `cmd_positions()`
- ab_test.py: `get_active_variant()`
- cloud_backup.py: `_find_google_drive()` (x2)
- weather_markets.py: `get_ensemble_temps()`, `_metar_lock_in()`
- kalshi_client.py: `_find_order_by_client_id()` (x2)
- param_sweep.py: `load_swept_min_edge()`
- kalshi_ws.py: `update_orderbook_cache()`, `read_orderbook_cache()`, `_ws_listener()`

**Compound risk:** Silent swallows are individually ignorable; collectively they create an environment where the system degrades silently across multiple trade cycles. A corrupt correlation file (monte_carlo.py), a failed ensemble fetch (weather_markets.py), and a failed daily-loss write (execution_log.py) can co-occur without a single WARNING log line appearing. The fix is a single repo-wide pass (estimated 2 hours) replacing each bare except with `except Exception as exc: _log.warning("...: %s", exc)`.

---

### 2. Silent Swallowing in Safety-Critical Gate Functions

A subset of the RF1 fires directly disables a safety mechanism rather than merely hiding an operational issue:

- paper.py `is_accuracy_halted()` — halt gate can silently fail to fire
- paper.py `_dynamic_kelly_cap()` — returns full Kelly (50.0) on error with no log
- paper.py `_method_kelly_multiplier()` — returns no-penalty (1.0) on error with no log
- execution_log.py `add_live_loss()` — daily loss gate silently disabled on DB lock
- tracker.py `brier_score()` — graduation gate receives None silently
- alerts.py `check_alerts()` — price monitoring disabled silently
- cron.py `_cmd_cron_body()` — dead outer `except TimeoutError` block; inner handler consumes without re-raise

**Compound risk:** Each of these is independently reachable by the same Windows Defender DB lock that is already documented as occurring in production (WinError 32). A single Defender scan during a cron run can simultaneously disable the daily loss gate, return uncapped Kelly sizing, and suppress the accuracy halt — all without any log entry above DEBUG.

---

### 3. Lock Discipline Gaps in Admin Write Paths (RF2)

- paper.py `undo_last_trade()` L:2557 — `_load()` + `_save()` without `_DATA_LOCK`
- paper.py `_mark_needs_manual_settle()` L:2593 — `_load()` + `_save()` without `_DATA_LOCK`

**Compound risk:** The rest of paper.py applies `_DATA_LOCK` consistently, making these omissions pattern-invisible to reviewers. A concurrent cron cycle and an admin command can both write `paper_trades.json` simultaneously. Windows Defender's known WinError 32 retry behavior makes torn writes on this specific file a realistic production scenario, not a theoretical one.

---

### 4. Missing Test Coverage on Live Kelly-Sizing Paths

- regime.py `detect_regime()` — RF6: zero test coverage; function multiplies `ci_adjusted_kelly` at weather_markets.py:6314
- monte_carlo.py `simulate_portfolio()` — `days_out` never read; same-day VaR overstated; not caught by any test
- schema_validator.py — no test coverage exists for any function in the file

**Compound risk:** These three functions participate in live Kelly sizing and market validation but have no unit test protection. Regressions introduced during emos-train or the deferred G2/G3 splits would not surface as test failures.

---

## Systemic Strengths

Patterns consistently done well across 3+ functions in 3+ files:

1. **Lock discipline in core write paths:** `_DATA_LOCK` / `_lock` acquire-pattern applied correctly on every high-frequency write path in paper.py and forecast_cache.py (10+ methods). The two RF2 violations are admin-only outliers against a consistent baseline.

2. **Migration discipline and schema versioning (tracker.py):** Consistent `_SCHEMA_VERSION` bumps, per-migration `ALTER TABLE` guards, and `multiday_predictions` view usage throughout. All 10 T1 functions in tracker.py scored 7+ with no active bugs.

3. **Circuit-breaker integration:** circuit_breaker.py passed all 6 T1 and 11 T2 checks with no red flags. The check-before-place pattern is applied consistently across cron.py and order_executor.py.

4. **Atomic write discipline via safe_io:** The majority of write-path code routes through `atomic_write_json`, providing crash-safe file replacement. The history-block gap in safe_io.py is a targeted omission, not a systemic failure of the pattern.

5. **Pre-log-before-API design (execution_log.py):** All live-order logging paths write to the database before the API call, ensuring order records survive crashes. This pattern is structurally correct and applied consistently.

6. **Defensive fallback in weather_markets.py T1 functions (20 graded):** EMOS Gaussian path has correct fallback when `emos_params.json` is absent. Degenerate ensemble gate (L4802) is applied. Blend weight locks are respected. 18 of 20 T1 functions scored 7+ with only 2 confirmed bugs.

---

## Dead Code Report

No file was flagged as entirely dead (unreachable from any live path). Three dormant features were noted:

| Feature | File | Live path status | Notes |
|---|---|---|---|
| Same-day slot reservation | order_executor.py `_sameday_effective_cap()` | DORMANT — not activated | Gated on 150 same-day settled (~99 current); do not activate early |
| Below-market extreme gate + NWS trim skip | weather_markets.py | DORMANT — `BELOW_GATE_ENABLED` not set | Gated on 30 settled below-predictions (~16 current) |
| A/B test variant selection | ab_test.py | OFF LIVE PATH — no active test configured | RF1 in `get_active_variant()` is a pre-live-wiring concern only |

No files are safe to delete. All are imported by live-path modules.

---

## Overall Verdict

**NOT YET ready to trade live money.**

The system has strong architectural bones — migration discipline, lock patterns, pre-log-before-API ordering, circuit-breaker integration, and EMOS fallback are all implemented correctly. However, nine of ten decision-matrix areas contain confirmed blockers.

The single highest-risk unfixed finding is the **silent exception swallow in `paper.py:is_accuracy_halted()` (L:2127, L:2142)**. A single upstream failure — specifically a Windows Defender DB lock, which is already documented as occurring in production — can cause this function to return without firing the accuracy halt, allowing the bot to continue placing trades after its Brier score exceeds the black-swan threshold. This is compounded by `execution_log.py:add_live_loss()` (RF1 L:307), which is disabled by the identical DB lock condition, silently neutralising the daily loss gate at the same moment the accuracy halt fails.

Clearing these two findings alone is not sufficient. The following must also be resolved before live escalation:

1. `atomic_write_json_with_history()` history-block gap (safe_io.py) — any exception skips the primary write entirely
2. Non-atomic `save_correlations()` (monte_carlo.py) — non-atomic write_text corrupts correlation file on crash
3. 24h close_time gate absent from `auto_settle_paper_trades()` (paper.py) — I4 invariant violation
4. Kill-switch not checked per-order in `_auto_place_trades` (cron.py) — mid-batch activation cannot stop orders 2-N
5. Between-market METAR lock-in using current temp not daily extreme (weather_markets.py L4721) — AC3 violation

The entire fix surface is approximately 2–4 hours of targeted patches concentrated in one commit, with no architectural changes required. Recommended sequencing: (1) repo-wide RF1 WARNING-log pass for all 42 fire sites (~2 h), (2) safe_io history-block wrap in try/except (~30 min), (3) monte_carlo atomic write via os.replace (~30 min), (4) paper.py 24h close_time gate in auto-settle path (~30 min), (5) cron.py per-order kill-switch check (~1 h), (6) weather_markets.py METAR lock-in AC3 fix (~30 min). After those six steps, re-run the affected test suites and the system is clear for live escalation.
