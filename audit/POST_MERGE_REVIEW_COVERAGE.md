# Post-Merge Review Coverage Manifest

Batch window: `8bdff1e5^..f4291771` (41 commits, 2026-08-18 → 2026-08-23, linear — zero merge commits, evil-merge check trivially satisfied).
Verified against `git ls-files '*.py'`: exactly the 51 modules below; batches added no new production modules.
Multi-batch collision files (≥2 batch commits) flagged `[COLLISION:n]`.
Findings referenced below live in `audit/POST_MERGE_REVIEW.md`.

## A. Money path / exchange (deepest scrutiny)
- trading_gates.py — done — clean; gate order correct, every check fail-closed
- order_executor.py [COLLISION:9] — done — CR-1 (batch-22×23 idempotency-key mismatch), H-2 micro-live gate gaps, H-3 double-exit dedup removal, M-1..M-4
- positions.py — done — clean; Position read-model consistent paper/live
- paper.py [COLLISION:8] — done — clean (contributes to documented sizing-aggressiveness note only)
- trade_cycle.py [COLLISION:4] — done — clean on money path; --sameday-only rain-arb denominator issue (with E-ops)
- execution_log.py [COLLISION:5] — done — H-1 record_live_settlement unguarded; M-4 substrate
- check_edge.py — done — clean (read-only diagnostic)
- circuit_breaker.py — done — INFO only (import-time state load); untouched in window
- kalshi_client.py [COLLISION:5] — done — clean itself; source of CR-1's violated contract + stale pagination comment
- kalshi_ws.py — done — clean; batch-23 reconnect fix correct
- market_types.py — done — clean (TypedDicts)

## B. Weather data & modeling
- weather_markets.py [COLLISION:10] (13.6k lines, 2 chunked agents) — done — merge integrity clean both halves; quarantine fail-open read, persistence-prob AUD-0016 sibling gap, prewarm cache defects, between-calibration hole (F1/F2)
- nws.py — done — M: shallow validate_nws_response defeats batch-13 fail-closed intent
- nws_afd.py — done — clean (display-only)
- metar.py — done — M: reportTime fallback raises TypeError; _extract_obs_time naive-datetime misdating
- mos.py — done — M: UTC ftime filtered by city-local date (known residual, never filed)
- acis_precip.py — done — M: mem-cache pins stale fallback; unit guard fails open
- acis_snow.py — done — same two as acis_precip (cloned)
- forecast_cache.py — done — LOW only (encoding; FIFO-not-LRU docstring)
- climatology.py — done — M: unguarded json.load reachable under _sigma_lock; 0c94b6e0 fix holds
- climate_indices.py — done — M: apply_pdo_pna_correction drops target month
- hurricane_climatology.py — done — LOW: dated HURDAT2 URL rotation degrades silently
- monte_carlo.py — done — M: side-blind correlated draws feeding VaR gate (conservative direction)
- regime.py — done — H (pre-existing): climatology-blind 1.20x Kelly boost (skeptic-verified; see report)

## C. Calibration & analytics
- calibration.py — done — M×3: missing _uncalibrated flag on gate-rejection path (live evidence in seasonal_weights.json), unconditional city/seasonal overwrite, missing shadow exclusion
- ml_bias.py [COLLISION:3] — done — H: deactivate-EMOS silent identity + t_pinned blind spot; M: contaminated METAR fit still live; batch-28 EMOS math verified correct
- feature_importance.py — done — clean
- ab_test.py — done — clean (dormant, no live consumer)
- backtest.py — done — H: _find_optimal_min_edge scores YES-settlement as win rate → PAPER_MIN_EDGE
- param_sweep.py — done — pre-existing scale mismatch still live (has audit repro)
- sigma_audit.py — done — clean
- consistency.py — done — clean

## D. State & settlement
- tracker.py [COLLISION:9] (7.9k lines, chunked) — done — all 9 commits intact; schema v61 consistent; INFO only
- settlement_monitor.py [COLLISION:4] — done — H: T-ticker settlement from instantaneous evening METAR feeds live force-close; M: restart truncates signals (120 vs 720 min windows)
- safe_io.py [COLLISION:4] — done — core correct; M: default replace budget insufficient under contention (only paper.py raised)
- schema_validator.py — done — clean itself; validate_market return still discarded at kalshi_client (tracked)
- paths.py [COLLISION:4] — done — clean; all 74 constants have importers; PEAK_BALANCE_PATH unused (INFO)
- cloud_backup.py — done — M: all_readable return discarded at only caller; LOW: UTC/local prune mismatch, nested snapshots

## E. Orchestration & ops
- main.py [COLLISION:21] (11.3k lines, 2 chunked agents) — done — H: batch-29 import-time validate can brick CLI via Settings menu; M×6 (cleanup deletes AUD-0026 sentinel + rain-arb history, _load_live_config OSError, kill-switch .tmp restore race, settings env desync, weekly summary entered_at); cmd_order/_quick_paper_buy merged cleanly
- cron.py [COLLISION:8] — done — M: last_full_scan stamped by aborted cycles; M: _release_cron_lock fails open to unlink on unreadable read
- watchdog.py — done — clean
- system_health.py — done — clean (fails closed)
- alerts.py — done — H (half): halt-transition edge consumed before delivery
- notify.py — done — H (half): rollback restores cooldown only; M: webhook URL logged
- config.py — done — H/M: batch-29 validation vs sentinels and menu bounds (see main.py)
- utils.py [COLLISION:2] — done — clean (batch-22/24 additions verified)
- colors.py — done — clean
- output_formatters.py — done — LOW: confusion matrix transposed (pre-existing)
- pdf_report.py — done — INFO only in module; M (Pass 5): zero tests + coverage-omit despite web reachability
- backlog_index.py — done — clean (regen byte-identical verified)

## F. Web & frontend
- web_app.py [COLLISION:7] — done — no CSRF/auth/secret gap (all 67 routes enumerated); M×4: resume/override-clear unlink races, order price cross-check silently disabled on parse failure, close-position missing gates
- frontend/src/App.jsx — done — H: kill-switch/halt/resume buttons discard response (silent emergency-stop failure); M: stale-object order submission; hardcoded Demo badge
- frontend/src/useData.js — done — M: mock opportunities/brier survive real empty responses (.length vs != null)
- frontend/src/main.jsx — done — clean
- frontend/src/mockData.js — done — clean itself (payload of the useData merges)

## G. Tests (meta-review, Pass 5)
- tests/ (162 files) + frontend tests — done — no weakened/deleted-to-pass tests (all 24 removed defs legitimate); zero-coverage list produced; two guard tests RED at HEAD from .venv scan (pre-existing)

## Cross-cutting passes
- Pass 1 evil-merge check — done — zero merge commits in window
- Pass 1 collision map + per-file second pass — done — no dropped/miscombined batch change found anywhere (mechanical added-line sweeps in A, B, D, E-main)
- Pass 2 safety-gate integrity — done — all 6 place_order sites behind pre_live_trade_check; LIVE_TRADING_ENABLED dormant everywhere; exceptions: micro-live gate gaps (H-2), record_live_settlement (H-1)
- Pass 3 timezone sweep — done — global census 211 sites/5 naive (all cosmetic); per-site verification by subsystem agents; stragglers filed as findings
- Pass 3 config validation vs sentinels — done — batch-29 findings (EM1-H1/M2/M3); SAME_DAY_RESERVE_AFTER_HOUR_UTC=24 verified correct
- Pass 3 reduced-scope flags (--sameday-only) — done — 2 incorrectly-scoped writes (last_full_scan, rain-arb denominator); all others verified correctly scoped
- Pass 3 stale-cache combines — done — _metar_lock_in verified correct (membership authoritative / clearance combined); gap found in sibling _compute_persistence_prob
- Pass 3 end-to-end data flow trace — done — units/conventions verified at every handoff by A (edge→gate→order→settle) and B (forecast→sigma→edge); °F/°C, cents/dollars, prob 0-1, YES-space wire convention all consistent
- Pass 4 test-suite run — done (bounded) — batches 1-5 of 6 run: 1,761+2,247 tests; failures: 2 pre-existing (.venv-scan guard), 22 environment (properscoring missing from venv). Batch 6 (≈last 22 files alphabetically) STOPPED EARLY by user instruction mid-run; partial batch-6 coverage exists via agent/baseline scoped runs (test_settlement_monitor 45P, test_trading_gates+test_execution_log 122P, test_web_app+test_web_auth 70P, test_weather_markets+test_metar 341P, test_trade_validation 16P clean)
- Pass 4 frontend tests — done — 29/29 pass (vitest, throwaway worktree; live-tree node_modules lacks vitest — see findings)
- Pass 4 mutation tests — done — 7 safety-critical behaviors in throwaway worktree: 6 killed (LIVE_TRADING_ENABLED gate 37F, side/price mapping 8F, settlement membership 1F targeted, METAR lock-in combine 3F, min-edge gate 2F via test_trade_validation, mid-batch kill-switch 9F); 1 SURVIVED (removing `settled_at IS NULL` guard from record_live_early_exit's unconditional branch — 281 tests pass; coverage gap filed)
- Pass 5 test quality/hygiene — done — see G
- Pass 5 lint via pre-commit interpreter — done — ruff, ruff-format, mypy all pass in throwaway worktree; zero files rewritten
- Pass 5 docs vs behavior — done — H: runbook Part 5 wrong lock filename (verified directly); M: runbook Part 2 gate check can't work as documented; M: README nonexistent `order` command; 9-gate appendix verified accurate
- Pass 5 tracked data/*.json — done — all 4 parse, weights sum to 1.0; note schema_validator.py does not cover these files (validates API responses only)
- Prior-audit baseline spot-check — done — 15/15 sampled resolved items VERIFIED-FIXED; zero clobbered fixes
- LIVE_TRADING_ENABLED dormancy — done — absent from .env and environment; enforced solely at trading_gates.py:69 on every order path
- Adversarial re-verification of CRITICAL/HIGH — done — 4 skeptic agents over all 13 candidates; verdicts folded into report
