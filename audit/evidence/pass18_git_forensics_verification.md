# Pass 18 — Git Forensics: Independent Verification (session 2, confirms session 1's corrections)

Verifier: skeptical re-audit, read-only. Repo root:
C:\Users\thesa\claude kalshi\.claude\worktrees\reverent-lumiere-f79c1f
HEAD at verification time: d190d09d

This file already contained a corrected verification from a prior session
(same task, re-run). This session independently re-derived every git/grep
command from scratch (not by reading that prior content first for the
load-bearing claims — the `git log -S` re-derivation for Finding 4 and the
main.py line reads for Finding 1 were run fresh) and reaches the same
conclusions. Recording as confirmation, not blind overwrite.

## Finding 1 — _quick_paper_buy() maker branch has no execution_log recording
STATUS: CONFIRMED (core bug), stated call site is WRONG.

Core defect independently re-confirmed:
- Read main.py:2170-2539 in full. Maker branch (2465-2511) calls
  `client.place_maker_order(...)` at 2494-2496 and `return`s at 2511 with
  zero execution_log/log_order/record_live_*/log_audit calls in that branch.
- `grep -n "execution_log|log_order|record_live" main.py` → only hits inside
  cmd_order (~4319-4841); nothing in 2170-2539.
- `grep -n "\.place_order\(\|\.place_maker_order\(" **/*.py` across the repo:
  order_executor.py's 6 sites and main.py:4703/4713 (cmd_order, logged via
  log_order at 4653) are all preceded by execution_log.log_order; main.py:2494
  is the sole exception.
- backlog.txt:7553-7558 independently corroborates: round-2 review previously
  found `_quick_paper_buy()` "can place a REAL LIVE maker order" and fixed
  only the ticker-family shadow-gate guards (RESOLVED header at line 7442 is
  dated **2026-07-30**, not 2026-07-31 as the finding states — one day off).

Citation error, independently re-derived:
- `grep -n "_quick_paper_buy" main.py` → exactly one call site, main.py:3243.
- Read main.py:3216-3249: `def cmd_analyze(...)` starts at 3216, ends before
  `def cmd_override` at 3249; line 3243 (`_quick_paper_buy(client)`) is
  the last line of `cmd_analyze`, NOT `cmd_today`.
- `cmd_today()` is main.py:2574-3216 (642 lines), read in full — it has its
  own separate, paper-only "[P] Place" flow (`_ppo_today` =
  `paper.place_paper_order`, main.py:2928) and never calls `_quick_paper_buy`
  or reaches the maker-order code at all.
- CLI dispatcher confirms the split: `cmd == "today"` → `cmd_today(client)`
  (main.py:9825-9826); `cmd == "analyze"` → `cmd_analyze(client, ...,
  live="--live" in args)` (main.py:9653) — only the latter reaches the bug.
  Menu dispatcher (main.py:7296/7303) shows the same "Analyze" vs "Today"
  split as two distinct entries.
- Real reproduction path: `py main.py analyze` (or interactive "Analyze") →
  `_quick_paper_buy` prompt → pick limit-maker order type → bug. `py main.py
  today` never reaches this code.

Dormancy (E1, consistent with recon): no .env in this worktree, so
`KALSHI_ENV` defaults to "demo" and `client.base_url == DEMO_BASE`; the
maker branch's own `if base_url != DEMO_BASE: pre_live_trade_check(...)`
guard is then never invoked, and there are no real credentials for
`place_maker_order` to use against even the demo API.

Verdict: underlying bug CONFIRMED, still open at HEAD. Stated reachability
("cmd_today, main.py:3243") is factually wrong — corrected to `cmd_analyze`
/ the `analyze` command. Confidence downgraded HIGH → MEDIUM for this
citation error; the core defect itself remains E1 static evidence, severity
HIGH as originally assessed (unrecorded live position risk is unchanged by
which command reaches it).

## Finding 2 — main.py's _target_date_due() still UTC-anchored
STATUS: CONFIRMED (E1), no errors found.
- `_target_date_due()` (main.py:467-483): plain `date.fromisoformat(...) <=
  today_date` compare confirmed, no per-city tz logic.
- Both call sites confirmed exactly as cited: `cmd_watch_settle`
  (main.py:865-892, `today_date = utils.utc_today()` at 886) and the
  interactive menu banner (main.py:7251/7255).
- `git log -S "target_date (compared below) is" --oneline -- main.py` →
  84571988 (2026-07-18), confirmed to predate `0100bffe` (2026-08-11,
  `git log -1 --format=%ad --date=short 0100bffe`), the commit that made
  target_date city-local (weather_markets.py:10924-10926's own comment
  independently confirms this).
- Severity-bounding claim re-verified: `auto_settle_paper_trades()`
  (paper.py:3122-3190) settles off tracker-DB outcome or a direct Kalshi
  `finalized`-status check with its own 24h `close_time` gate — it iterates
  ALL open trades, not filtered by `_target_date_due`, and is unconditional.
  Confirms the bug affects only `cmd_watch_settle`'s poll-exit condition and
  the menu's stale-count banner, not actual settlement correctness.

Verdict: accurate as stated, including severity. No corrections.

## Finding 3 — e5331a8d's two disclosed follow-ups still open; banner wrong on a 3rd path
STATUS: CONFIRMED (E2) for the core claims; inherits Finding 1's citation error.
- `git show -s --format=%B e5331a8d` verbatim confirms both disclosed gaps
  ("the KALSHI_ENV=prod startup banner also wrongly claims only `watch
  --auto --live` can place live orders, and `paper.check_position_limits`'
  exposure caps never read execution_log for real live positions").
- Banner logic unchanged at HEAD: main.py ~9566 computes `_live_orders_
  possible = cmd == "watch" and "--auto" in args and "--live" in args`.
- `paper.check_position_limits()` (paper.py:3447-3698) confirmed to have
  zero references to `execution_log` (checked the function body directly).

Inherited error: the finding's "third command path" is stated as
`cmd_today`, repeating Finding 1's mistake. The banner genuinely is wrong
about a third live-capable path, but that path is `analyze`
(`cmd_analyze` → `_quick_paper_buy`), not `today`. Does not change the
finding's core verdict.

Verdict: core claims CONFIRMED; enumeration of the third path corrected.
Severity MEDIUM as stated remains appropriate.

## Finding 4 — ee22c44c frontend-only vs 0edf818b computeMark provenance
STATUS: DISPROVEN — the finding's central forensic claim runs backwards.

Independently re-derived this session (fresh commands, not read from any
prior file first):
```
git log -S "export function computeMark" --oneline -- frontend/src/useData.js
  -> ee22c44c   (2026-08-14 16:02:22 -0400)
git log -S "export function computeMark" --oneline -- "weather app site V_3 (3)/src/useData.js"
  -> 0edf818b   (2026-08-14 20:53:26 -0400, ~4h51m LATER, same day)
git show ee22c44c -- frontend/src/useData.js | grep computeMark
  -> "+export function computeMark(t) {" is added as new code directly in
     ee22c44c's diff to the REAL, served frontend file.
```
So `computeMark` is introduced first in the real, served `frontend/src/
useData.js` by `ee22c44c` — not "not touched" by that commit as the finding
claims (also: `git show --stat ee22c44c` shows it touches more than "only"
App.jsx/useData.js — also web_app.py, package.json, useData.test.js,
static/dist assets, backlog.txt). `0edf818b`, nearly five hours later,
brings the separate dead-prototype-directory copy up to parity with logic
that already existed in the real, served file; its own commit message
(read in full) describes this explicitly as porting "~130 uncommitted
lines already sitting in the main clone's working copy" — a catch-up sync,
not an origin. `git log -S` against the real served file alone finds the
true origin trivially; there is no need to consult the dead prototype
directory, contrary to the finding's stated method and its conclusion that
plain git history over the real frontend/ "would not show" the origin.

Verdict: DISPROVEN. The only salvageable, non-actionable fact is that both
directories currently contain a `computeMark` copy and the dead directory
is not a served path (per recon) — true but trivial, not the provenance
mystery described.

## Finding 5 — METAR calibration production-file write isolation is per-test, not structural
STATUS: CONFIRMED (E1), no errors found.
- `ml_bias.py:22`: `from paths import METAR_CALIBRATION_PATH as
  _METAR_CALIBRATION_PATH` — confirmed import-time binding.
- `grep -n -i metar tests/conftest.py`: only autouse fixtures for
  `metar._METAR_CACHE`/`_DAILY_OBS_CACHE` (in-memory caches); nothing
  redirects `ml_bias._METAR_CALIBRATION_PATH`.
- `git show -s --format=%B 5d9b6c56` verbatim confirms the described prior
  incident (monkeypatch on `weather_markets.METAR_CALIBRATION_PATH` didn't
  reach `ml_bias`'s own imported copy; silently wrote synthetic coefficients
  to the real production file).
- `tests/test_ml_bias.py`: `TestFitAndSaveMetarCalibration` (1863-1958) and
  `TestCmdCalibrateMetarBlock` (1960+) both patch
  `ml_bias._METAR_CALIBRATION_PATH` directly at lines 1907/1950/2010/2049 —
  confirmed exact line numbers.

Verdict: accurate as stated. No corrections.

## Summary
5 findings independently re-verified against current code/git history.
3 CONFIRMED exactly as stated (Findings 2, 5, and the core disclosed-gap
claims of 3). 1 CONFIRMED-with-correction (Finding 1: real, still-open bug;
wrong caller cited — `cmd_analyze`, not `cmd_today`; the same error
propagates into Finding 3's "third path" enumeration). 1 DISPROVEN
(Finding 4: its provenance claim is backwards — `computeMark` originates in
the real served `frontend/src/useData.js` via `ee22c44c`, ~5 hours before
the dead-prototype-directory commit `0edf818b` the finding names as the
origin).

No file modifications made outside audit/. No git state changed (log/show/
grep/diff/awk only).
