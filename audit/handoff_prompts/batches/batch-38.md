# Batch 38: Test & environment hygiene

## Context

Repo: weather1. Written 2026-08-23 against master `f4291771` — re-verify before starting. Source: `audit/POST_MERGE_REVIEW.md` (M-23 umbrella). Files owned: `tests/*` (except tests added by batches 31-37 for their own code), `safe_io.py`, `.github/workflows/ci.yml`, `pyproject.toml`, `pdf_report.py`, `output_formatters.py`. Parallel-safe with 33-37/39.

## Items

### 1. M-23b [MEDIUM]: two repo-guard tests are RED on the deployment checkout — they walk `.venv`

**Files:** `tests/test_disputed_row_guard.py:70-100,212`, `tests/test_isoformat_cutoff_guard.py:85-98`. Pre-existing (`e0fd1cc0`/`39c6593f`).
`_EXCLUDED_DIR_NAMES` lacks `.venv` and has no dot-prefix rule (unlike `test_paths_bypass_guard.py:88` / `test_bare_os_replace_guard.py:191`), so `_production_py_files()` walks the whole virtualenv and `read_text(encoding="utf-8")` crashes on `.venv/Lib/site-packages/joblib/test/test_func_inspect_special_encoding.py` (big5, deliberately). Both disputed-row guard tests — the guard protecting calibration/Brier data — fail on any checkout with a venv (i.e., the main clone) while passing in worktrees/CI, which is why nobody saw it. The scan is also the reason those runs take 9 minutes. Fix: adopt the dot-prefix skip both sibling guards use, in both files; verify the guards then actually run their assertions (3 passed each, in seconds).

### 2. M-23c [MEDIUM — operator quick-action + test fix]: `properscoring` missing from `.venv`

`requirements.txt:16` declares it; 22 EMOS tests (`test_ml_bias.py` TestEmos, `test_main_cron_smoke.py` TestEmos*) currently ERROR with ModuleNotFoundError instead of skipping. Production is graceful (`main.py:7633` guards the import). Actions: `.venv\Scripts\pip install properscoring` (if not already done per INDEX-POSTMERGE), AND make the tests honest about the dependency: `pytest.importorskip("properscoring")` at module/class level so a future env gap skips loudly rather than erroring.

### 3. M-23d [MEDIUM]: default atomic-write replace budget is insufficient under contention — batch-30 raised it for `paper.py` only

**Files:** `safe_io.py:122-172,355`; evidence `tests/test_safe_io.py:572` fails under load (3 attempts × 0.5s exhausted, WinError 5), passes isolated.
Other irreplaceable-state callers (tracker's `strategy_pins`/`retired_strategies`, `learned_weights.json`, `live_config.json`, `alerts.json`) still ride the 0.5s default and will raise `AtomicWriteError` under the same pressure (emergency copy saves the data, but the caller's fail-open path is what then runs). Fix: raise the DEFAULT `replace_deadline_secs` (batch-30's paper.py analysis: 11s worst case fit under the 30s lock — pick a default with the same reasoning for the general case, no per-call-site edits in other batches' files), and de-flake the concurrent-writers test accordingly.

### 4. M-23e [MEDIUM — decision]: CI never exercises the Windows-only concurrency guards, which guard the production platform

**Files:** `.github/workflows/ci.yml` (ubuntu-latest).
The cross-process mutual-exclusion tests (cron lock, `CrossProcessLock`, settlement overlap) are all `skipif(sys.platform != "win32")` — correct locally, silently skipped where master is gated. AskUserQuestion: add a `windows-latest` job running just the concurrency-marked test files (cheap, scoped — do NOT run the whole suite in CI either), or explicitly document the gap in ci.yml with a comment. Recommend the scoped windows job.

### 5. M-23f [MEDIUM]: `pdf_report.py` — zero tests, web-reachable, excluded from the coverage gate

**Files:** `pdf_report.py` (277 lines), `pyproject.toml [tool.coverage.run] omit`, callers `web_app.py:1085` / `main.py:7338` (read-only references).
Add a minimal test file (renders with representative data, asserts no exception + key fields present; cover the HTML-fallback path), remove it from the coverage omit list, and `html.escape` the interpolations in `_generate_html` (`:170-192` — INFO-tier hardening while there).

### 6. L-7 [LOW]: `cmd_history`'s confusion matrix is transposed

**Files:** `output_formatters.py:342-345` — off-diagonal cells swapped vs `tracker.get_confusion_matrix`'s definitions (`fp` = pred YES ∧ actual NO): rows should be `[tp, fn]` / `[fp, tn]`. Display-only (P/R/F1 below are computed from the raw dict, correct). Fix + a test locking the orientation. Also L-2: `cmd_history` and `cmd_pnl_attribution` have zero test references — add smoke tests while here.

### 7. L-10 [LOW]: widened safety-gate stubs can't catch signature drift

Four test files stub gates as `lambda *_a, **_k` (`test_kelly_property`, `test_phase2_batch_i`, `test_trade_improvements`, `test_risk_control`). Add one signature-pinning test (inspect.signature assertions on `is_paused_drawdown`/`is_streak_paused`/`pre_live_trade_check`) so a future param change fails loudly somewhere.

### 8. L-6(schema) [LOW — decision]: no schema validation exists for the tracked `data/*.json` weight files

`schema_validator.py` validates API responses only — the audit doc's assumption that it covers `city_weights`/`condition_weights`/`seasonal_weights`/`temperature_scale.json` is false. They currently parse and sum correctly, and consumers `.get()`-guard the `_uncalibrated` sentinel. AskUserQuestion: add a small `validate_weight_file()` + a test asserting the live files pass (recommended — cheap, catches the M-13-class on-disk anomalies), or explicitly decline and note it in backlog. If added, keep it in schema_validator.py + tests only — calibration.py belongs to batch 37.

## Process

LOW-tier downgrade applies to most items (self-review + 1 review agent) EXCEPT items 3 and 8's code halves — safe_io feeds the paper ledger path; give those the full opus review. Mutation-test new tests via Edit-revert. Scoped pytest per touched file — **never the full suite** (and don't "verify" item 1 by running everything; run the two guard files). Lint via the real pre-commit interpreter. Backlog entries + `backlog_index.py`. Confirm before commit. Full workflow: `memory/feedback_implementation_workflow.md`.
