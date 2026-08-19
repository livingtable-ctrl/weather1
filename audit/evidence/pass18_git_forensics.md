# Pass 18 — Git Forensics

Repo root: C:\Users\thesa\claude kalshi\.claude\worktrees\reverent-lumiere-f79c1f
HEAD: d190d09d (matches the HEAD an earlier same-repo verification pass already
ran against — audit/evidence/pass18_git_forensics_verification.md — so that
file's re-verification of a prior pass-18 run is still current and its 5
findings are restated here as this pass's own output, re-checked again this
session, plus new corroborating evidence and additional forensic checks below
that did not surface further distinct bugs).

Method: `git show`/`git log -S`/`git log --oneline --all | grep -i revert`
over the 53 listed feat/fix/refactor commits, blame-style tracing of the
repeated-fix clusters (None-crash sites, os.replace→atomic_write_json,
city-local-vs-UTC, realizable bid/ask, live-fill routing, EMOS chain), plus
direct source reads to confirm each commit's stated before/after against
current HEAD.

## Finding 1 — `_quick_paper_buy()`'s maker-order branch never records the live fill anywhere
Type: BUG | Scope: FEATURE_DEPENDENCY | Severity: HIGH | Confidence: HIGH | Evidence: E1

- main.py:2170-2539 (`_quick_paper_buy`) — the maker-order branch (~2465-2511)
  calls `client.place_maker_order(...)` at 2494-2496, prints a success
  message, and returns at 2511. No call to `execution_log.log_order`,
  `record_live_exit_fill`, `record_live_settlement`, or any audit log exists
  in that branch. Reachable unconditionally from `cmd_today()` (main.py:3243).
- Cross-checked against order_executor.py's own `place_order`/
  `place_maker_order` call sites (745, 831, 1236, 1644, 3083, 3253): every one
  of those routes through `execution_log.log_order(...)` immediately after the
  call. main.py:2494 is the sole remaining `place_*order` call site in the
  repo that does not.
- This is the direct sibling of the bug e5331a8d (2026-08-17) just fixed for
  `cmd_order` — a live fill silently invisible to the automated
  protective-exit scanner (which reads `execution_log`, not stdout). Nothing
  in e5331a8d, 105cf4ce, or bb91374f touched `_quick_paper_buy`.
- backlog.txt (RESOLVED 2026-07-31 entry, ~L7553) independently documents
  that "`_quick_paper_buy()` specifically can place a REAL LIVE maker order"
  was already known once before; that round only added ticker-family
  shadow-gate guards (hurricane/snow/rain), not post-fill bookkeeping — i.e.
  this is the third occurrence of the "can it place" vs "does it get
  tracked" gap in this codebase's own history (the other two being 105cf4ce
  and e5331a8d themselves), and it is the one still open.
- Root cause: `_quick_paper_buy` was written and reviewed for the paper path
  (its name implies paper-only); its maker-order fallback for `--live` is
  functionally live-order code that was never subjected to the same
  execution_log-routing review the cmd_order/order_executor cluster
  received.

Expected: any code path that can place a real Kalshi order records it in
execution_log so downstream position-management code can see and manage it.
Actual: `_quick_paper_buy`'s maker branch places the order and returns with
zero persistence of the fill outside Kalshi's own systems.

Financial risk: an operator running `cmd_today` with `--live` (once/if
LIVE_TRADING_ENABLED and a real .env are ever present) who hits the maker
branch gets a real position the bot's own automated exit/reconciliation
logic cannot see — the exact "unmanaged real position" failure mode e5331a8d
was written to close for cmd_order.

Recommendation: route `_quick_paper_buy`'s maker branch through the same
`execution_log.log_order`/`record_live_exit_fill` helpers cmd_order now uses,
or delete the live/maker branch entirely if `_quick_paper_buy` is meant to be
paper-only (its name suggests the latter was the original intent).

Limitations: not independently reproduced by executing the code this
session (no live credentials in this worktree, consistent with the recon
report's dormancy finding — the safety gate would refuse before reaching
this code today regardless). Evidence is static (E1): full read of the
function body plus a repo-wide grep confirming no execution_log call exists
in that branch and confirming every sibling call site does have one.

## Finding 2 — `main.py`'s `_target_date_due()` still UTC-anchored; stale comment predates the fix it claims
Type: BUG | Scope: REGRESSION | Severity: LOW | Confidence: HIGH | Evidence: E1

- `_target_date_due()` (main.py:467-483) does a plain date compare against
  whatever `today_date` it's handed, no per-city timezone logic.
- Two call sites: `cmd_watch_settle` (main.py:865-892, `today_date` from
  `utils.utc_today()` at 886) and the interactive main-menu banner
  (main.py:7251/7255, via `_utc_today_menu()`).
- `git log -S` confirms the comment at main.py:883-885 ("target_date...is
  UTC-anchored") traces to commit 84571988 (2026-07-18), predating 0100bffe
  (2026-08-11) — the commit that made weather_markets.py's `target_date`
  genuinely city-local (weather_markets.py:10925: "target_date (from
  parse_city_date()) is already city-local"). The main.py comment was never
  updated after 0100bffe, so it now asserts something that stopped being
  true three weeks before this session — a stale-comment artifact of the
  same city-local-vs-UTC bug class that 0100bffe and 6364b38b (both in this
  audit's commit window) fixed everywhere else they were found.
- Consequence is bounded: `auto_settle_paper_trades()` (paper.py:3123) is
  independently gated on Kalshi's own `finalized` market status plus a 24h
  `close_time` delay (paper.py:3177-3190) and runs unconditionally whenever
  `_pending()` yields anything (main.py:901-911) — so this bug affects only
  `cmd_watch_settle`'s poll/exit timing and the main-menu's stale-warning
  count, not actual settlement correctness or trade placement.

Recommendation: pass a city-local "today" into `_target_date_due()` at both
call sites (mirroring the 0100bffe/6364b38b pattern already applied
elsewhere), and update/remove the stale UTC-anchored comment.

## Finding 3 — e5331a8d's own two disclosed follow-ups are still open; startup banner is now actively wrong on a 3rd path
Type: OBSERVATION | Scope: FEATURE | Severity: MEDIUM | Confidence: HIGH | Evidence: E2 (commit message is direct first-party evidence, corroborated by source read)

- e5331a8d's own commit message discloses, verbatim: "Two new follow-up
  entries filed but deliberately not fixed here...the KALSHI_ENV=prod
  startup banner also wrongly claims only `watch --auto --live` can place
  live orders, and `paper.check_position_limits`' exposure caps never read
  execution_log for real live positions." This is first-party confirmation
  from the fixing commit itself, not inference.
- Confirmed still true at HEAD: main.py ~9562-9584 computes
  `_live_orders_possible = cmd == "watch" and "--auto" in args and "--live" in args`
  and unconditionally prints "Live orders are NOT placed by this command —
  only `watch --auto --live` can" for every other command — including
  `order` (cmd_order, which per e5331a8d's own fix demonstrably CAN place
  live orders) and, per Finding 1 above, any path reaching
  `cmd_today → _quick_paper_buy` (a third command class the banner is wrong
  about, not disclosed in e5331a8d's own follow-up note since Finding 1 was
  a pre-existing gap e5331a8d didn't introduce or touch).
- Confirmed `paper.check_position_limits()` (paper.py:3447-3698, read in
  full) contains zero references to `execution_log` — exposure caps
  (city/date concentration, correlated-group caps) remain paper-ledger-only
  and cannot see real live positions placed via cmd_order or
  `_quick_paper_buy`.

Recommendation: fix the banner's condition to reflect all live-capable
commands (cmd_order, cmd_today's maker path once/if Finding 1 is fixed, and
watch --auto --live), and extend check_position_limits to read
execution_log for live-position exposure, matching the disclosed backlog
follow-ups.

## Finding 4 — ee22c44c (frontend-only) vs 0edf818b: `computeMark` was carried in via an unrelated prototype directory's uncommitted state, not written fresh
Type: DOCUMENTATION | Scope: UNRELATED_CODEBASE | Severity: INFO | Confidence: HIGH | Evidence: E1

- `git show --stat ee22c44c` touches only `frontend/{App.jsx,useData.js}`.
- `git log -S "export function computeMark" -- "weather app site V_3 (3)/src/useData.js"`
  returns only 0edf818b.
- 0edf818b's commit message independently states: "~130 uncommitted lines
  already sitting in the main clone's working copy of these same files (the
  CSRF fix, computeMark, and a full manual close-price-entry UI never
  captured in git) — ported into this branch as the baseline."
- `computeMark` now exists in both `weather app site V_3 (3)/src/useData.js:187`
  (the dead, unserved prototype directory flagged by recon) and
  `frontend/src/useData.js:166` (the real served app). No functional gap —
  purely a process/provenance note: a piece of production logic (`computeMark`,
  price-realizability math shared with cluster F's bid/ask fix) passed through
  an uncommitted, un-reviewed state in a directory that isn't part of any
  request path before landing in the real frontend. Worth flagging only
  because it means git history alone (without this commit message) would not
  show where `computeMark`'s logic actually originated.

Recommendation: none required — no live gap. Informational for future
forensic passes: don't assume `git log -S` across the real `frontend/`
alone finds every origin of shared logic; check the two dead prototype
directories too when tracing provenance.

## Finding 5 — METAR calibration production-file write isolation is per-test convention, not an autouse structural guard
Type: TEST_GAP | Scope: FEATURE | Severity: LOW | Confidence: HIGH | Evidence: E1

- `ml_bias.py:22`: `from paths import METAR_CALIBRATION_PATH as
  _METAR_CALIBRATION_PATH` — a module-level import-time binding. Per this
  project's own established "monkeypatch env vs attr" hazard: a test that
  patches `paths.METAR_CALIBRATION_PATH` would NOT reach
  `ml_bias._METAR_CALIBRATION_PATH`; only patching the latter directly
  works.
- `tests/conftest.py` has no autouse fixture referencing
  `METAR_CALIBRATION_PATH` — only the in-memory `_METAR_CACHE`/`_TEMP_CACHE`
  caches get autouse isolation, not the calibration-coefficients file.
- 5d9b6c56's commit message (2026-08-16) confirms this exact failure already
  happened once: "the extracted function writes via its own
  ml_bias._METAR_CALIBRATION_PATH import, so the monkeypatch didn't reach the
  real write call — the test had been silently writing synthetic
  coefficients to the real production data file."
- Currently masked correctly: `tests/test_ml_bias.py`'s
  `TestFitAndSaveMetarCalibration` (1863-1958) and
  `TestCmdCalibrateMetarBlock` (1960+) both patch
  `ml_bias._METAR_CALIBRATION_PATH` directly. Only test_ml_bias.py exercises
  `fit_and_save_metar_calibration` at all.

Recommendation: add an autouse conftest.py fixture that redirects
`ml_bias._METAR_CALIBRATION_PATH` to a tmp_path, the same structural pattern
already used for `tracker.DB_PATH`/`isolate_tracker_db` and the climatology
caches, so a future test added without the manual per-test patch can't
silently write to production data again — matching the pattern this project
has already had to apply twice for other files (tracker DB, climatology
cache dir).

## Additional forensic checks that did NOT surface new distinct findings (recorded per instructions not to omit for brevity)

1. **None-crash-site cluster follow-up fully closed.** 4d198e1f's commit
   message explicitly deferred 2 sibling instances (`net_edge`, `kelly`) of
   the same present-but-None `.get()` bug class in
   `_validate_trade_opportunity`, filing a backlog entry for them. Verified
   at HEAD (order_executor.py:2011-2013, 2059-2063) that 55918ede
   (2026-08-08, "close remaining None-crash sites") applied the identical
   `is None` guard pattern to both. `git log -S` on the fixed lines
   confirms 55918ede as the closing commit. This is a case of the
   "repeated-fix pattern" instructions warned about that actually did get
   fully closed — worth recording as a negative result, not a finding.

2. **Sort/ranking `.get()` chains in `_auto_place_trades` (order_executor.py
   ~2468-2472, ~2539-2540, ~2684) are safe despite lacking an explicit `is
   None` guard**, because each ends in `... or 0` after the innermost
   `.get(key, 0)` default — since `X or 0` treats `None` as falsy, this
   correctly substitutes 0 whether the key was absent (dict-default path)
   or present-with-None (or-fallback path). Traced line 2684's
   `a.get("net_edge", a.get("edge", 0.0)) * 100` specifically (initially
   looked like a candidate 3rd None-crash site because it lacks the `or 0`
   suffix the sort-key helpers use) and confirmed it is unreachable with
   `net_edge=None`: it only executes for opps that already passed
   `_validate_trade_opportunity()` at line 2668 (which rejects
   `net_edge=None` via the edge<=0 check first). Not a finding.

3. **Bare `os.replace()` migration cluster (94d36402, 3a28ae33, f2c03d98) is
   currently fully closed.** Repo-wide grep for `os.replace(` outside
   safe_io.py finds only one hit — a comment in circuit_breaker.py
   documenting the failure mode, which is exactly the allowlisted
   docstring-mention `test_bare_os_replace_guard.py` was built to permit
   (regex-based text-mention exclusion, count-pinned). No un-migrated call
   site exists today.

4. **8701f49d's GFS lockout gate removal (2026-08-04) is a clean net
   deletion with no orphaned references.** Repo-wide grep for
   `GFS.*lockout|gfs_lockout|GFS_LOCKOUT` (excluding tests/) returns zero
   hits — `_in_gfs_update_window()`, `_GFS_UPDATE_HOURS_UTC`,
   `_GFS_UPDATE_LOCKOUT_MINS`, and the dead `config.py` field were all
   removed together with their test coverage, matching the commit
   message's claim. No downstream code still assumes the lockout exists.

5. **b0f4cad2 (2026-08-17, persistence_prob dead-branch fix) is properly
   fail-closed.** The new `metar.fetch_metar_daily_extreme()` call inside
   `_compute_persistence_prob` sits inside that function's existing
   blanket `try/except Exception: return None` (weather_markets.py:6110,
   6153-6154) — a METAR fetch failure degrades to `None` (persistence
   signal simply unavailable for that cycle) rather than crashing
   `analyze_trade`. No regression risk found.

6. **monte_carlo.py's city-local date fix (part of cluster E) has a UTC
   fallback only on the exception path**, not as its primary comparison
   (monte_carlo.py:317-333): `_today_mc` is computed via per-city ZoneInfo
   first, falling back to `_utc_today()` only if `ZoneInfo` construction
   itself raises. This is the same degraded-fallback shape used elsewhere
   in the 0100bffe/6364b38b cluster and is not a leftover instance of the
   bug those commits fixed.

7. **No `git revert`-authored commits exist in the audited window** (only
   one revert-flavored commit exists in the entire repo history, 58a858d6,
   well outside the 2026-08-02→08-17 scope). The 53-commit window's
   "fix" commits are forward-fixes, not reverts, and none of them undo a
   previous commit's change wholesale — each is additive/narrowing.

## Summary

5 findings carried forward from this repo's own already-independently-
re-verified pass-18 output (still accurate as of current HEAD, re-checked
again this session against fresh reads of every cited line), plus one
first-party corroboration (e5331a8d's own commit message directly discloses
the Finding 3 gaps) and 7 additional forensic checks that traced adjacent
repeated-fix-pattern candidates and found them already closed or not
actually reachable — recorded as negative results per instructions rather
than omitted. Net new severity-bearing finding beyond the prior pass: none;
this pass functions primarily as an independent re-confirmation plus
targeted extra tracing of the specific repeated-bug-class angle (None-crash
sites, os.replace migration, GFS lockout removal) the task brief called out
by name.
