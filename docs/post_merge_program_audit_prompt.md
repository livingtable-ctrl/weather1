# Whole-Program Audit (Post-Merge)

## Context

This repo (weather1, a Kalshi weather-market trading bot) just had ~20 parallel Claude sessions each land a batch of audit fixes (`batch-NN` / `AUD-XXXX` commits) onto master. Each batch was tested **in isolation**. Your job is a **full audit of the entire merged program** — every production module gets reviewed, not just the files the batches touched. The batch merge is the trigger and the highest-risk area (cross-batch interactions, duplicated or contradictory fixes, dropped changes), but coverage is the whole codebase.

First, make sure you are reviewing the right tree: run `git fetch`, confirm `git rev-parse HEAD` equals `git rev-parse origin/master`, and pull if not — the local master checkout does not update itself when branches are merged remotely. Then establish the batch window: run `git log --oneline -300` and identify every commit from the batch effort (messages containing `batch-`, `AUD-`, or audit-fix language).

**Prior-audit baseline:** `audit/AUDIT_REPORT.md` / `audit/AUDIT_REPORT.json` and `backlog.txt` document a previous 21-pass audit and its findings. Use them two ways: (1) don't re-report an item already known and tracked as open; (2) spot-check ~10 items marked resolved by the batches to confirm the fix is actually present and correct in the merged tree — a "resolved" label is a claim, not evidence.

## Ground rules (non-negotiable, learned the hard way in this repo)

- **Never run bare `pytest`.** Always scope to specific test files.
- Run tests with the repo's venv: `.venv/Scripts/python -m pytest tests/test_x.py`. When running from a throwaway worktree, `.venv` won't exist there (it's gitignored) — use the main clone's absolute path: `"C:/Users/thesa/claude kalshi/.venv/Scripts/python" -m pytest ...`.
- Bare `python -c "import weather_markets"` sees empty API keys — `.env` only loads via `main.py` / explicit `load_dotenv()`.
- Never run manual `python -c` scripts that import `tracker.py` — they write to the REAL `tracker.db` (no conftest isolation outside pytest).
- `paths.py` resolves `data/` to the MAIN CLONE regardless of cwd/worktree.
- Before claiming "all call sites do X," re-run Grep with `head_limit: 0` — the default 250-line cap silently truncates.
- **Exclude `.claude/worktrees/` from every repo-wide grep/glob.** The main clone contains 60+ worktrees under that path, each a near-copy of the repo — an unscoped recursive search matches dozens of stale copies of every file. Use `git grep` (tracked files only) or an explicit path exclusion.
- `pre-commit` is NOT on PATH on this machine. Lint with the hook's real interpreter: `"C:\Users\thesa\AppData\Local\Python\pythoncore-3.14-64\python.exe" -m pre_commit run --all-files`. Don't substitute the .venv's ruff/mypy — different versions. **The ruff hook runs with `--fix` plus a formatter, so `--all-files` WILL rewrite files — never run it against the main clone's working tree.** Run it inside a throwaway detached worktree at HEAD (`git worktree add <tmpdir> HEAD`) and report any resulting diff as a finding.
- **Never temporarily edit production files in the main clone** — mutation-test edits included. The live bot's scheduled jobs run from that tree; a cron cycle firing mid-edit would execute your mutated logic. Do all mutation testing (and anything else that transiently modifies code) in a throwaway detached worktree. Create throwaway worktrees OUTSIDE the repo directory (use your scratchpad dir) so they don't pollute the main clone's `git status` or your grep sweeps.
- This is a live-adjacent trading system: `KALSHI_ENV=prod`. Do not execute anything that places orders, and do not stop, restart, or reschedule the bot's processes or scheduled tasks. Never run interactive commands (`cmd_setup` blocks on `input()`). `LIVE_TRADING_ENABLED` is unset (so `cmd_order`/`ENABLE_MICRO_LIVE` are dormant) — verify that stays true.

## Pass 0 — Coverage manifest (the thoroughness contract)

Before reviewing anything, write `audit/POST_MERGE_REVIEW_COVERAGE.md`: one line per production module (the list below, re-verified against `git ls-files '*.py'` in case the batches added files), each marked `pending`. Update it to `done — <one-line note>` as each module is reviewed. **The review is not finished while any line says pending.** No silent sampling: if you must bound effort somewhere, the bound goes in the coverage file as an explicit `SKIPPED: <reason>` line, never as an unmarked omission.

The 51 production modules, grouped by subsystem (verify grouping against actual imports; batches may have added modules):

- **A. Money path / exchange** (deepest scrutiny): `trading_gates.py`, `order_executor.py`, `positions.py`, `paper.py`, `trade_cycle.py`, `execution_log.py`, `check_edge.py`, `circuit_breaker.py`, `kalshi_client.py`, `kalshi_ws.py`, `market_types.py`
- **B. Weather data & modeling**: `weather_markets.py` (13.6k lines — review in chunks, do not skim), `nws.py`, `nws_afd.py`, `metar.py`, `mos.py`, `acis_precip.py`, `acis_snow.py`, `forecast_cache.py`, `climatology.py`, `climate_indices.py`, `hurricane_climatology.py`, `monte_carlo.py`, `regime.py`
- **C. Calibration & analytics**: `calibration.py`, `ml_bias.py`, `feature_importance.py`, `ab_test.py`, `backtest.py`, `param_sweep.py`, `sigma_audit.py`, `consistency.py`
- **D. State & settlement**: `tracker.py` (7.6k lines), `settlement_monitor.py`, `safe_io.py`, `schema_validator.py`, `paths.py`, `cloud_backup.py`
- **E. Orchestration & ops**: `main.py` (10.4k lines — chunk it), `cron.py`, `watchdog.py`, `system_health.py`, `alerts.py`, `notify.py`, `config.py`, `utils.py`, `colors.py`, `output_formatters.py`, `pdf_report.py`, `backlog_index.py`
- **F. Web & frontend**: `web_app.py`, `frontend/src/App.jsx`, `frontend/src/useData.js`, `frontend/src/main.jsx`, `frontend/src/mockData.js`
- **G. Tests** (156 files in `tests/`, plus `frontend/src/useData.test.js`): meta-review, not line-by-line — see Pass 5.

Per-module review lenses (apply all, weight by subsystem): correctness of the core logic; error handling and fail-open vs fail-closed; timezone handling; state mutation and persistence (partial-write safety, atomicity via `safe_io`); concurrency/reentrancy (cron overlap, WS callbacks); stale-data handling (cache ages, fallbacks); off-by-one and boundary conditions on thresholds/strikes; silent exception swallowing; dead or contradictory config flags; security (secrets/`kalshi_private_key.pem`/API keys leaking into logs or reports, `web_app.py` auth and CSRF, anything reachable from user-facing input — the prior audit found real defects in this class).

## Pass 1 — Merge-collision map (batch-interaction focus)

Find files touched by **2 or more** batch commits (run in the Bash tool, not PowerShell):

```
git log <first-batch-commit>^..HEAD --name-only --pretty=format: | sort | grep -v '^$' | uniq -c | sort -rn
```

**Evil-merge check (do not skip):** the command above lists only non-merge commits' files — `git log --name-only` silently omits merge-commit diffs, and this history DOES contain real merge commits. Enumerate them with `git log --merges --oneline <first-batch-commit>^..HEAD`, then run `git show --remerge-diff <sha>` on each (supported by this machine's git 2.54): any non-empty remerge diff is a human/agent conflict resolution — review those hunks line-by-line, they are the single most likely place a batch's change was silently dropped or miscombined.

Every multi-batch file gets a second, targeted look on top of its Pass 0 review — read the full current version, not just diffs:
- Two fixes to the same function that individually made sense but interact wrong (double-applied guards; a validation added by one batch that defeats a bypass/exemption another batch relies on).
- The same `AUD-XXXX` finding fixed twice in different ways.
- A conflict resolution that silently dropped one batch's change (compare each batch commit's stated intent against what's actually in the file now).
- A batch fix that contradicts a pre-existing `backlog.txt` investigation: for each function a batch changed, grep `backlog.txt` for that function name.

## Pass 2 — Safety-gate integrity (highest severity class)

For every trading gate — `LIVE_TRADING_ENABLED`, `TRADING_PAUSED`, kill switch, `PAPER_MIN_EDGE`, `ENABLE_MICRO_LIVE`, and the live-exit/cancel path in `order_executor.py` (the `settled_at` guards) — trace **every** caller of the shared gate functions (`trading_gates.py` and anything it feeds). This class has recurred 5+ times: a fix at one call site while another caller bypasses the gate. Also check the inverse: a fail-closed fix (e.g., a None-crash gate) can newly expose the same unguarded pattern **downstream** of the gate — check consumers past the gate, not just parallel callers.

Confirm nothing in the merged tree makes an order path more aggressive: order-placement, side/price mapping, exposure limits, position sizing. Remember: a SELL limit at a LOW price is aggressive (fills instantly), not safe.

## Pass 3 — Cross-cutting convention sweeps (whole tree, not just batch diffs)

- **Timezones:** grep every `datetime.now(` / `date.today(` / `datetime.utcnow` in the whole tree and verify each call site's tz argument individually — one file can legitimately mix conventions, so verify per call site, not per file. City-local vs UTC vs naive is this codebase's most recurrent bug class.
- **Config validation vs sentinels:** for each validation/range check in `config.py` AND `_validate_config()` in `main.py` (validation lives in both places), grep the field's real consumer for the exact comparison operator — a "sane range" bound can reject a legitimate sentinel (a real past bug here: an hour field where 24 meant "never"). Check each validation's **timing** relative to deliberate bypass logic — e.g., `cmd_setup` in `main.py` must stay reachable with a broken or incomplete `.env` (it exists to fix one).
- **Reduced-scope flags** (`--sameday-only` if it merged, and any similar flag): audit every unconditional write along the shared pipeline (caches, heartbeats, alerts, tracker writes) — did each side effect also see the filtered subset?
- **Stale-cache combines** (e.g., `_metar_lock_in`): membership decisions must use the authoritative source alone; magnitude/clearance may use the combined `max()`.
- **End-to-end data flow:** trace one full cycle — forecast fetch → sigma/probability → edge calc → gate checks → (paper) order → tracking → settlement → calibration feedback — and verify unit/convention agreement at every handoff (°F vs °C, cents vs dollars, probability vs percentage, YES/NO side semantics, ticker date vs city-local date).

## Pass 4 — Test-suite verification

- Run the test files for every production module (scoped, batched — never bare `pytest`). All must pass on the merged tree.
- Frontend: run `npm test` in `frontend/` (vitest; `node_modules` is already installed there).
- If a test fails, check whether it also fails at `<first-batch-commit>^` before blaming a batch — use a throwaway detached worktree (`git worktree add <tmpdir> <commit>`; remove after), never touch the main clone's checkout. A pre-existing failure is still a finding, but a different one.
- For the 5–8 most safety-critical behaviors (gate checks, settlement correctness, METAR lock-in, order-side mapping), mutation-test: flip the logic via a temporary Edit and confirm a test actually fails. Do this **only in a throwaway detached worktree** (see ground rules — never mutate the main clone), and revert each edit precisely (never `git checkout -- <file>`).

## Pass 5 — Test quality and hygiene

- Look for tests **weakened to pass**: assertions loosened, mocks that can't fail (a plain `Mock()` for `datetime.now(tz)` can't prove tz resolution; `getattr(mock, x, default)` never returns the default — MagicMock auto-vivifies), tests deleted or skipped by a batch, tests asserting only "doesn't crash".
- Identify production modules with **no** meaningful test coverage at all — list them as findings.
- `backlog.txt` vs `BACKLOG_OPEN.md`: regenerated and consistent? Entry titles go stale relative to their resolution notes — judge by full entry text.
- Any batch that cited a validation number to justify a signal after fixing data contamination: re-run that validation against the fixed code; don't trust the pre-fix number.
- Lint the full tree via the pre-commit interpreter (exact command in ground rules).
- Docs vs behavior: spot-check `README.md`, `COMMANDS.md`, and `LIVE_TRADING_RUNBOOK.md` against the merged code — commands, flags, and safety-procedure claims they document must still be true (the runbook especially: a stale safety procedure is a HIGH finding, not a docs nit).
- Tracked `data/*.json` files (`city_weights`, `condition_weights`, `seasonal_weights`, `temperature_scale`): confirm they still parse and pass `schema_validator.py`'s expectations.
- Check no batch committed stray scratch/repro files outside `audit/`. (Do NOT expect `git status` to be fully clean — the main clone legitimately carries uncommitted live-operation files like `bot.log` and `data/`; leave those alone.)

## Output

Write findings to `audit/POST_MERGE_REVIEW.md`, severity-tiered (CRITICAL: money/order-path or safety-gate defects; HIGH: wrong trading decisions or data corruption; MEDIUM: logic bugs off the money path; LOW/INFO). For each finding: file:line, subsystem, the batches involved (if any), a concrete failure scenario (inputs/state → wrong behavior), and a minimal repro or failing test where feasible. Verify each CRITICAL/HIGH finding by actually executing a repro before reporting it — no plausible-but-unconfirmed claims at those tiers. The coverage manifest must show every module `done` (or explicitly `SKIPPED` with reason). End with an explicit verdict: safe to resume normal operation, or which specific items must be fixed first.

Restate every CRITICAL and HIGH finding in your final chat message — do not rely on the file alone (or on a subagent's structured output, which the orchestrator can't see) to carry them.

Do not fix anything — report only. Fixes get triaged and batched separately.

## Scale

This is a full-codebase audit — do not attempt it as one sequential read. Orchestrate: run the Pass 1 collision map yourself first, then launch one review subagent (opus, effort=high) per subsystem group A–F from Pass 0, each given: its module list, the ground rules, the Pass 0 lenses, the Pass 2–3 checks scoped to its files, and the list of multi-batch collision files that fall in its scope (flagged for the deeper Pass 1 treatment). Group A (money path) warrants the most careful agent; groups B and E each contain a 10k+-line file — split those files across chunked prompts rather than trusting one agent to hold them whole. Run Passes 4–5 yourself (or as a final agent) after the subsystem reviews return. Require each subagent to list its full findings in its final text reply, then merge and dedup into the report yourself. If any subagent touches the filesystem, verify `git log`/`git status` afterward — subagents have committed on their own initiative before. Adversarially re-verify every CRITICAL/HIGH candidate with a fresh skeptic agent before it goes in the report.
