# Batch 11: README / docstring accuracy sweep

## Context

Repo: weather1 (Kalshi weather-trading bot). Branch `claude/code-max-depth-audit-5518e9`, HEAD `d190d09dd699df5266e85650a6ddf8e2d1420891` at the time these batches were written (2026-08-18) -- **re-verify this is current before starting** (workflow step 1): other batches from this same grouping may already be merged, and this project routinely runs many parallel worktree sessions. `git fetch` + `git log origin/master` before touching anything.

This batch comes from the 2026-08-18 max-depth forensic audit (`audit/AUDIT_REPORT.md` / `.json`). It groups 8 finding(s) that share **README.md, main.py, metar.py, ci.yml, pyproject.toml** -- doing them together means you only load this subsystem's context once, and avoids two different sessions independently editing the same file in parallel. Live trading is currently dormant (`LIVE_TRADING_ENABLED` unset) -- no active financial exposure today for any item below, but treat items tagged HIGH/MEDIUM as touching a real live-order/live-money surface once trading is enabled.

**Do NOT touch other batches' files while working this one** -- batches were constructed so no two share a touched file; if you find yourself needing to edit something outside this batch's file list, stop and check whether another batch already covers it (see the full batch list in `audit/handoff_prompts/batches/INDEX.md`) rather than expanding scope silently.

## Items in this batch

### 1. AUD-0061 [LOW | HIGH | E1 | CONFIRMED]: README.md's environment-variable table omits the 6 shadow-only *_TRADING_ENABLED feature flags, 3 added within this audit's commit window

**Files:** (see full record)

**Problem:** Ran `grep -n "_TRADING_ENABLED" main.py weather_markets.py order_executor.py` and found exactly the 6 flags cited (HOURLY_TRADING_ENABLED, HURRICANE_NEXT_EVENT_TRADING_ENABLED, HURRICANE_TRADING_ENABLED, RAIN_TRADING_ENABLED, SNOW_TRADING_ENABLED, STORM_ORDER_TRADING_ENABLED); grep of README.md for the same pattern returned zero matches. Confirmed via `git log --oneline --all -S` that HURRICANE_TRADING_ENABLED was introduced in 1a7c9aca and STORM_ORDER_TRADING_ENABLED in 9a7583aa, matching the cluster-G commits cited. Exact match to claim.

**Note:** this finding's structured record is missing description, root_cause, evidence, recommendation (a known JSON-completeness gap in the audit's own output -- the content exists, just not in that specific field). Full narrative from adversarial verification, which covers the missing ground: Ran `grep -n "_TRADING_ENABLED" main.py weather_markets.py order_executor.py` and found exactly the 6 flags cited (HOURLY_TRADING_ENABLED, HURRICANE_NEXT_EVENT_TRADING_ENABLED, HURRICANE_TRADING_ENABLED, RAIN_TRADING_ENABLED, SNOW_TRADING_ENABLED, STORM_ORDER_TRADING_ENABLED); grep of README.md for the same pattern returned zero matches. Confirmed via `git log --oneline --all -S` that HURRICANE_TRADING_ENABLED was introduced in 1a7c9aca and STORM_ORDER_TRADING_ENABLED in 9a7583aa, matching the cluster-G commits cited. Exact match to claim.

Full record: `audit/AUDIT_REPORT.json` (id `AUD-0061`), `audit/AUDIT_REPORT.md`.

### 2. AUD-0062 [LOW | HIGH | E1 | CONFIRMED]: README.md's 'bot only trades temperature and precipitation' claim is stale given hurricane market support added this window

**Files:** (see full record)

**Problem:** Read README.md:361 verbatim: 'The bot only trades Kalshi weather markets (temperature and precipitation). It ignores all other market types.' Confirmed via git log -S that hurricane-model commits 1a7c9aca/9a7583aa (and d4ade606 closing a related gate-bypass gap) exist and add real hurricane-market order-placement code paths gated behind env flags, contradicting the blanket claim. Exact match.

**Note:** this finding's structured record is missing description, root_cause, evidence, recommendation (a known JSON-completeness gap in the audit's own output -- the content exists, just not in that specific field). Full narrative from adversarial verification, which covers the missing ground: Read README.md:361 verbatim: 'The bot only trades Kalshi weather markets (temperature and precipitation). It ignores all other market types.' Confirmed via git log -S that hurricane-model commits 1a7c9aca/9a7583aa (and d4ade606 closing a related gate-bypass gap) exist and add real hurricane-market order-placement code paths gated behind env flags, contradicting the blanket claim. Exact match.

Full record: `audit/AUDIT_REPORT.json` (id `AUD-0062`), `audit/AUDIT_REPORT.md`.

### 3. AUD-0063 [LOW | HIGH | E1 | CONFIRMED]: README.md's EMOS activation row count ('~25 rows') contradicts the actual 40-row floor added this window and contradicts COMMANDS.md

**Files:** (see full record)

**Problem:** Read README.md:203 — 'Once ~25 rows are accumulated, an `emos-train` command will fit...'. Read main.py:6663-6668 — `_EMOS_VAR_FLOOR = 40` with a hard refusal below that unless --force. Read COMMANDS.md:62 — correctly states 'refuses below 40 ens_var rows'. Confirmed via `git log --oneline -S"_EMOS_VAR_FLOOR"` a single introducing commit 4557a77b, and via `git show 4557a77b^:main.py` that the prior threshold was a softer `n_var >= 10` check (line 6333 pre-commit) used only to choose default vs fitted c/d values, not a hard activation floor — so README's '25' never matched any actual threshold. Exact match to claim.

**Note:** this finding's structured record is missing description, root_cause, evidence, recommendation (a known JSON-completeness gap in the audit's own output -- the content exists, just not in that specific field). Full narrative from adversarial verification, which covers the missing ground: Read README.md:203 — 'Once ~25 rows are accumulated, an `emos-train` command will fit...'. Read main.py:6663-6668 — `_EMOS_VAR_FLOOR = 40` with a hard refusal below that unless --force. Read COMMANDS.md:62 — correctly states 'refuses below 40 ens_var rows'. Confirmed via `git log --oneline -S"_EMOS_VAR_FLOOR"` a single introducing commit 4557a77b, and via `git show 4557a77b^:main.py` that the prior threshold was a softer `n_var >= 10` check (line 6333 pre-commit) used only to choose default vs fitted c/d values, not a hard activation floor — so README's '25' never matched any actual threshold. Exact match to claim.

Full record: `audit/AUDIT_REPORT.json` (id `AUD-0063`), `audit/AUDIT_REPORT.md`.

### 4. AUD-0064 [LOW | VERY HIGH | E1 | CONFIRMED]: cmd_schedule()'s docstring claims 'auto-scan every hour' but registers a 3-hourly task

**Files:** (see full record)

**Problem:** Grepped and read main.py — docstring at line 8963 reads exactly 'Register a Windows Task Scheduler job to auto-scan every hour.'; line 8991 builds `schtasks /Create /F /SC HOURLY /MO 3 ...`; line 9008 prints 'Task ... registered — runs every 3 hours.' All three line numbers match the citation exactly. Independently ran `git blame` on both lines and confirmed the docstring (line 8963) was authored by commit d7b2ad7e on 2026-04-09 while the /MO 3 interval (line 8991) was authored by a separate commit c189f2821 on 2026-04-16, exactly matching the finding's git-blame claim.

**Note:** this finding's structured record is missing description, root_cause, evidence, recommendation (a known JSON-completeness gap in the audit's own output -- the content exists, just not in that specific field). Full narrative from adversarial verification, which covers the missing ground: Grepped and read main.py — docstring at line 8963 reads exactly 'Register a Windows Task Scheduler job to auto-scan every hour.'; line 8991 builds `schtasks /Create /F /SC HOURLY /MO 3 ...`; line 9008 prints 'Task ... registered — runs every 3 hours.' All three line numbers match the citation exactly. Independently ran `git blame` on both lines and confirmed the docstring (line 8963) was authored by commit d7b2ad7e on 2026-04-09 while the /MO 3 interval (line 8991) was authored by a separate commit c189f2821 on 2026-04-16, exactly matching the finding's git-blame claim.

Full record: `audit/AUDIT_REPORT.json` (id `AUD-0064`), `audit/AUDIT_REPORT.md`.

### 5. AUD-0065 [LOW | HIGH | E1 | CONFIRMED]: README.md's NOTIFY_CHANNELS default ('desktop,discord') doesn't match the actual code default

**Files:** (see full record)

**Problem:** Grepped NOTIFY_CHANNELS across README.md/notify.py/.env.example. README.md:278 reads default `desktop,discord`. notify.py:42 reads `os.getenv("NOTIFY_CHANNELS", "desktop,pushover,ntfy,discord,email")`. .env.example:43 sets `NOTIFY_CHANNELS=desktop,pushover,ntfy,discord,email`. Code and .env.example agree with each other and disagree with README exactly as claimed.

**Note:** this finding's structured record is missing description, root_cause, evidence, recommendation (a known JSON-completeness gap in the audit's own output -- the content exists, just not in that specific field). Full narrative from adversarial verification, which covers the missing ground: Grepped NOTIFY_CHANNELS across README.md/notify.py/.env.example. README.md:278 reads default `desktop,discord`. notify.py:42 reads `os.getenv("NOTIFY_CHANNELS", "desktop,pushover,ntfy,discord,email")`. .env.example:43 sets `NOTIFY_CHANNELS=desktop,pushover,ntfy,discord,email`. Code and .env.example agree with each other and disagree with README exactly as claimed.

Full record: `audit/AUDIT_REPORT.json` (id `AUD-0065`), `audit/AUDIT_REPORT.md`.

### 6. AUD-0081 [INFO | HIGH | E1 | CONFIRMED]: metar.fetch_metar_daily_extreme docstring's caller list is stale after b0f4cad2 added a third caller

**Files:** (see full record)

**Problem:** metar.py's fetch_metar_daily_extreme docstring states 'Both current callers (settlement_monitor.py, weather_markets.py's _metar_lock_in) only ever pass today's date; this function does not enforce that itself.' b0f4cad2 (2026-08-17) added a third call site in weather_markets.py's _compute_persistence_prob (weather_markets.py:6137) that also calls this function, but the docstring's caller enumeration was not updated.

**Root cause:** b0f4cad2 reused an existing function without revisiting its docstring's caller inventory.

**Evidence:** metar.py lines 396-404 docstring text verified verbatim. grep of `fetch_metar_daily_extreme(` shows 3 call sites: weather_markets.py:6137 (new, from b0f4cad2), weather_markets.py:10368 and 10433 (pre-existing _metar_lock_in), settlement_monitor.py:416. `git show b0f4cad2 --stat` confirms this commit ('fix(weather_markets): source real daily-high for persistence_prob's dead branch', 2026-08-17) added the new call site.

**Financial risk:** None -- purely cosmetic/documentation.

**Recommendation:** Update the docstring to mention the third caller, or phrase it generically ('every current caller') rather than naming call sites individually so future additions don't require a docstring update to stay accurate.

**Limitations noted by the audit:** None; straightforward E1 static finding, fully reproduced.

Full record: `audit/AUDIT_REPORT.json` (id `AUD-0081`), `audit/AUDIT_REPORT.md`.

### 7. AUD-0083 [INFO | HIGH | E1 | CONFIRMED]: CI workflow runs the full pytest suite twice per run (coverage report + coverage gate as separate full runs)

**Files:** (see full record)

**Problem:** Read .github/workflows/ci.yml in full. Lines 40-41: 'Run tests with coverage' step runs `pytest -v --cov=. --cov-report=term-missing`. Lines 43-44: 'Fail if coverage drops below 40%' step runs `pytest --cov=. --cov-fail-under=40 -q`. Both are independent full pytest invocations over the same testpaths with no test-selection narrowing between them, exactly as claimed. Recommendation (merge into one invocation or use `coverage report --fail-under`) is technically sound.

**Note:** this finding's structured record is missing description, root_cause, evidence, recommendation (a known JSON-completeness gap in the audit's own output -- the content exists, just not in that specific field). Full narrative from adversarial verification, which covers the missing ground: Read .github/workflows/ci.yml in full. Lines 40-41: 'Run tests with coverage' step runs `pytest -v --cov=. --cov-report=term-missing`. Lines 43-44: 'Fail if coverage drops below 40%' step runs `pytest --cov=. --cov-fail-under=40 -q`. Both are independent full pytest invocations over the same testpaths with no test-selection narrowing between them, exactly as claimed. Recommendation (merge into one invocation or use `coverage report --fail-under`) is technically sound.

Full record: `audit/AUDIT_REPORT.json` (id `AUD-0083`), `audit/AUDIT_REPORT.md`.

### 8. AUD-0084 [INFO | MEDIUM | E1 | CONFIRMED]: pyproject.toml's `integration` marker relies entirely on tests self-skipping, not on pytest configuration excluding the marker

**Files:** (see full record)

**Problem:** Read pyproject.toml's [tool.pytest.ini_options] block in full — confirmed no `addopts` key exists at all, so nothing at config level excludes the `integration` marker by default. Read tests/test_integration_live.py — `pytestmark = pytest.mark.integration` (module-level) plus a per-client-construction self-skip (`if os.getenv("KALSHI_ENV") != "demo": pytest.skip(...)`) is the only mechanism preventing these tests from attempting real calls; note the file's own docstring additionally claims (also inaccurately) that these tests 'are excluded from normal pytest runs' by default, which reinforces the finding's point that the exclusion is not actually configured anywhere. Confirmed ci.yml:41 passes no `-m` filter. Exact match to claim; reasonable INFO-level defense-in-depth observation.

**Note:** this finding's structured record is missing description, root_cause, evidence, recommendation (a known JSON-completeness gap in the audit's own output -- the content exists, just not in that specific field). Full narrative from adversarial verification, which covers the missing ground: Read pyproject.toml's [tool.pytest.ini_options] block in full — confirmed no `addopts` key exists at all, so nothing at config level excludes the `integration` marker by default. Read tests/test_integration_live.py — `pytestmark = pytest.mark.integration` (module-level) plus a per-client-construction self-skip (`if os.getenv("KALSHI_ENV") != "demo": pytest.skip(...)`) is the only mechanism preventing these tests from attempting real calls; note the file's own docstring additionally claims (also inaccurately) that these tests 'are excluded from normal pytest runs' by default, which reinforces the finding's point that the exclusion is not actually configured anywhere. Confirmed ci.yml:41 passes no `-m` filter. Exact match to claim; reasonable INFO-level defense-in-depth observation.

Full record: `audit/AUDIT_REPORT.json` (id `AUD-0084`), `audit/AUDIT_REPORT.md`.

## Process -- follow the 29-step implementation workflow from memory (`feedback-implementation-workflow`) exactly, in order

This batch is documentation/test/low-risk-code only. If every item you actually touch turns out to be a small, mechanically-verifiable diff with no live-order/live-money/safety-gate surface and no multi-file span, steps 11-12 may collapse to the LOW tier (a single self-review pass + one Agent check instead of a dedicated opus effort:high spawn). Re-assess per item -- don't downgrade the whole batch by default if one item in it turns out bigger than expected.

Non-negotiable highlights regardless of tier: (1) re-verify every item's claims against live state before trusting this prompt's transcription -- re-read the actual current code/docs at the cited locations. (2) Research the real code structure before designing a fix. (3) Surface genuine design decisions via `AskUserQuestion`, don't guess. (7) Write real, mutation-tested tests for anything code-level (via the Edit tool for mutation reverts, never a string-replace script). (8-9) Scoped test run, then lint/mypy. (11) Independent opus review at `effort: high` before push for anything live-money-adjacent -- and if that review's findings get fixed, the fix itself needs its own independent review too. (13) Address every review finding regardless of severity. (14-16) Compressed-pointer memory update before commit; explicit confirmation before commit/push; `git fetch` + rebase-if-diverged immediately before the actual push -- this matters more than usual here since other batches may be pushing to the same branch/master concurrently. (19) If `backlog.txt` gets edited, run `python backlog_index.py` afterward and confirm the entry landed correctly in `BACKLOG_OPEN.md`. (29) Refresh `graphify-out/` (AST always; semantic `--update` too if any item is non-LOW-tier) before committing, if it exists -- scope the refresh to just the files this batch actually changed, not a full incremental sweep (a full sweep pulls in every other in-flight batch's uncommitted work too).

Full step list and tiering rules live in memory under `feedback-implementation-workflow` -- apply all 29 steps in order. **If this memory entry isn't loaded in your session**, its full text is preserved at `C:\Users\thesa\.claude\projects\C--Users-thesa-claude-kalshi\memory\feedback_implementation_workflow.md` -- read it directly rather than proceeding without it.
