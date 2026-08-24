# Batch 37: Calibration & analytics data integrity

## Context

Repo: weather1. Written 2026-08-23 against master `f4291771` — re-verify before starting. Source: `audit/POST_MERGE_REVIEW.md`. Files owned: `calibration.py`, `ml_bias.py`, `backtest.py`, `param_sweep.py`, `settlement_monitor.py`, `monte_carlo.py`, `tracker.py`, plus `data/` artifacts named below. One 1-line `main.py` change (item 4) — **run this batch AFTER batch 32** (which owns main.py) or hand that line to it. Parallel-safe with 33-36/38-39 otherwise.

## Items

### 1. M-20 [MEDIUM — operator quick-action + code follow-up]: `data/walk_forward_params.json` is test-fixture output in the real data dir

The file claims `n_folds: 6`, `saved_at` 2026-08-23 — but the real corpus can produce **0 folds** (3 distinct trade months < the 4 required), so a test run wrote the real `data/` (the known manual-scripts-bypass-isolation hazard) and the live `PAPER_MIN_EDGE = 0.04` gating all paper placement is fixture-sourced. Actions: (a) delete the file (PAPER_MIN_EDGE falls back to param_sweep/default — verify which via `config._compute_paper_min_edge_from_files`); (b) find the test that wrote it (grep tests for `save_walk_forward_params`/uses of the real DATA path) and fix its isolation so it can't recur; (c) note in backlog.

### 2. L-14 [LOW, fix while here]: `_find_optimal_min_edge` maximizes YES-settlement rate, not win rate

**Files:** `backtest.py:923`, `:1111-1120`.
`settled_yes = outcome=="yes"`; a win is `outcome == side` (`paper.py:2485`) and `side` is dropped from the mapped dict — 125/198 settled trades are NO-side, so the metric is inverted for the majority. Skeptic materiality check: currently harmless (all 198 edges ≥0.15 → every threshold ties → 0.04 either way, and 0 folds means it never runs via cron) — but it's a one-line class of fix: carry `side` through the mapping, score `outcome == side`. `param_sweep.py:67-69` documents the exact hazard; while in that file also fix L-17's range mismatch: `run_sweep` sweeps [0.15..0.40] but `load_swept_min_edge` accepts [0.03, 0.15] → only 0.15 can ever load (pre-existing, has repro at `audit/reproductions/repro_pass20_param_sweep_scale_mismatch.py`).

### 3. M-12 [MEDIUM]: refit the contaminated METAR lock-in calibration and re-derive its two downstream conclusions

**Files:** `data/metar_lockout_calibration.json`, `ml_bias.py:571-640`, `settlement_monitor.py:352-357`. Batch `57cd0d88`.
The on-disk fit (a=b=0.22619… bit-identical — the degenerate self-feedback shape; fitted 08-20) predates its own contamination fix (08-22) and is applied live at `weather_markets.py:13407-13430` (don't edit that file — read-only reference) and on the settlement force-close path. Actions: (a) trigger the refit now via the real path (`fit_and_save_metar_calibration` — check the min-EPV floor; if it declines to write, that's a finding to record, and the OLD file must be deleted so the fail-open path is at least honest); (b) re-derive `settlement_monitor.py:352-357`'s "≥0.80 gate is permanently below reach" claim and ml_bias's AUD-0038 ceiling model against the CLEAN fit — both currently reason from contaminated coefficients, and the "unreachable gate" claim is what caps the T-ticker finding at LOW (see item 7); (c) per the skeptic's novel residue: the calibration file is NOT git-tracked, so a fresh host (VM move) fails open to raw confidence (max 0.857 ≥ the 0.80 gate) — decide (AskUserQuestion): git-track the file, or make `_calibrate_metar_settlement_confidence` fail CLOSED (skip force-close) when no calibration is loadable. Append this to the existing backlog entry at `backlog.txt` lines ~4-70 rather than filing new.

### 4. L-15 [LOW-MEDIUM]: `deactivate_emos` discards the restore result; `t_pinned` blind post-deactivate; plus a live `temperature_scale.json` anomaly

**Files:** `ml_bias.py:1616-1660`, `:1400-1401`; `main.py:8221` (1 line — coordinate with batch 32).
Skeptic-verified structure: unlink-params-first, restore's False return discarded, unconditional green CLI print; `get_emos_status` returns early with no `t_pinned` when the params file is absent (exactly the post-deactivate state). Mitigations found (why not HIGH): the snapshot file survives failure so re-running self-heals; a WARNING does log; weekly retrain partially heals. Fix: propagate the restore bool to the CLI print (red warning + "re-run to retry" on False); make `get_emos_status` report `t_pinned`/snapshot-present even when inactive. **Separately investigate:** live `data/temperature_scale.json` has `below = {"T": 1.0, "n": 14}` with no `reset_for_emos` marker — a shape the current code cannot write (`_fit_T` can't return exactly 1.0; n=14 < 15). Below-condition probabilities are uncalibrated right now and the `_T_BELOW_PRIOR=3.0` fallback is dead (fires only on an ABSENT key). Determine provenance, then either delete the key (re-arming the prior) or backfill — user decision with evidence.

### 5. M-13 [MEDIUM]: `calibration.py` trio (untouched by the merge window; live evidence on disk)

(a) `:131-134` — the improvement-gate rejection path returns equal weights WITHOUT the `_uncalibrated` flag (the `_MIN_VAL_ROWS` path has it); `data/seasonal_weights.json`'s `summer` is exactly ⅓/⅓/⅓ with no flag right now, suppressing the hardcoded days-out schedule in August. Add the flag on that path AND repair the on-disk summer entry.
(b) `:384-436` — hand-tune preservation exists only for condition weights; `calibrate_city_weights`' `{}` (file is literally `{}` on disk now) and seasonal `_neutral` placeholders overwrite unconditionally — extend the same preservation.
(c) `:310-323` — `calibrate_condition_weights` lacks `_load_rows`' shadow-condition-type exclusion; a shadow family reaching 60 settled rows silently gains a live blend-weight entry with no graduation gate. Add the same exclusion list (single source of truth).
Plus LOWs in the same file: `:32-40` `date.today()` → `utils.utc_today()`; `:112` comment says 0.001, gate is 0.005; `validate_weight_files` never validates city + condition loop missing the negative-weight check (`:448-480`).

### 6. M-22 [MEDIUM]: settlement-monitor restart truncates still-valid signals

**Files:** `settlement_monitor.py:638` vs `:739-740`; consumer `cron.py:2068` (do not edit cron.py — batch 33 owns it; the fix is local).
The loop re-seeds from disk with `max_age_minutes=120` then full-file-overwrites, while cron reads with 720; a restart >2h into the ~310-min scheduled window drops signals cron would still act on. Fix: seed with 720 (match the consumer), or merge-don't-overwrite.

### 7. L-13 [LOW — record-keeping only, no code]: T-ticker settlement uses the instantaneous evening METAR reading

`settlement_monitor.py:551-584`. Real asymmetry (the between branch got the daily-extreme fix, this branch didn't) but skeptic-verified unreachable today: current calibration caps confidence at 0.766/0.595 < the 0.80 gate, the monitor has never been scheduled or run, and it's already OPEN at `backlog.txt:4-70` (Priority Low) with the same numbers. Do NOT re-file. Your job: after item 3's refit, re-check whether the calibrated ceiling still stays under 0.80 — if not, escalate the existing entry; and add item 3c's fresh-host fail-open note to it.

### 8. M-30 [MEDIUM, documentation]: `simulate_portfolio`'s correlated draws are side-blind

`monte_carlo.py:487` correlates win indicators, not weather — mixed YES/NO cross-city positions model as positively correlated when truly anti-correlated (conservative for that pairing). `run_stress_test` documents this exact limitation (`:574-588`); the function feeding the live pre-trade VaR gate does not. Add the equivalent docstring note at `simulate_portfolio`/`portfolio_var`; a real side-aware fix is out of scope (file to backlog if the user wants it). Plus L-9 nits: module-level `_DEFAULT_CORRELATIONS` mutated cross-call (`:265-266`); `n_simulations=0` IndexError at `:500`; inconsistent `prob_positive` defaults (0.0 vs 0.5).

### 9. L-6(tracker) [LOW]: `audit_settlement`'s hourly branch returns True without a rowcount check

`tracker.py:716-721` — rain/snow/daily branches all verify `cur.rowcount >= 1`; the KXTEMPxxxH branch doesn't, inflating backfill counters. Mirror the siblings. Plus INFO: `get_member_accuracy` docstring says population stdev, code computes sample (`:6099-6139`) — fix the docstring.

## Process

Full 29-step workflow (calibration feeds live gating; opus review effort=high). Re-verify claims live — especially every `data/*.json` observation, which can change under you (cron writes weekly). NEVER run manual `python -c` scripts importing tracker.py (real-DB writes) — use pytest fixtures or read-only sqlite copies in the scratchpad. Scoped tests only: `tests/test_ml_bias.py`, `tests/test_calibration*.py` (find exact names), `tests/test_settlement_monitor.py`, `tests/test_tracker.py`, `tests/test_paper_metrics.py` — **never the full suite**. Note `tests/test_ml_bias.py`'s EMOS tests need `properscoring` installed (see INDEX-POSTMERGE quick-action 2). Lint via the real pre-commit interpreter. Backlog entries + `backlog_index.py`. Confirm before commit. Full workflow: `memory/feedback_implementation_workflow.md`.
