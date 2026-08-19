# Pass 5 — Feature Integration (Sections 10 & Scope B), second pass

Read-only investigation session. Repo root:
`C:\Users\thesa\claude kalshi\.claude\worktrees\reverent-lumiere-f79c1f`

This audit directory already contains an earlier Pass 5 raw+verify cycle
(`pass5_verify.md`, `pass5_section10_scopeB_verify.md`) with 4 CONFIRMED
findings (VaR-gate blindness to live positions, startup-banner
misidentification, `check_position_limits` blindness to live positions,
METAR force-close gate structurally dormant). I independently re-traced
several of those load-bearing claims against current source (order_executor.py
_place_live_order/_auto_place_trades, main.py cmd_order's live-fill routing,
ml_bias.py's EMOS gate) rather than re-deriving from scratch, and they hold —
see confirmations below. This file's main contribution is one NEW finding not
present in either prior pass5 file, plus several new INFO-level integration
checks across clusters not previously exercised in depth (cmd_watch/cron
shared-engine kill-switch/override propagation, safe_io bare os.replace
migration completeness, CSRF before_request coverage, admin override
reachability).

## NEW FINDING — kill-switch override leaves an orphaned `.kill_switch.tmp`
that later crashes `cmd_cron`'s manual override with `FileExistsError`

- `main.py` `cmd_cron()` wrapper (lines ~268-360), specifically the
  interactive one-shot kill-switch override path.
- Three `Path.rename()` calls exist in the whole repo (grepped `\.rename(`
  across all non-test/non-audit `.py` files — zero other hits):
  `main.py:292` (guarded, inside try/except), `main.py:332` (UNGUARDED),
  `main.py:350` (guarded by an existence check on the destination
  immediately before it).
- `main.py:332`: `_kill_path.rename(_kill_tmp)` — moves `.kill_switch` to
  `.kill_switch.tmp` when an operator answers "y" to "Override and run this
  cycle anyway?". Not wrapped in try/except.
- Reproduced directly (E2, ran it in this environment) that
  `pathlib.Path.rename()` to an existing destination raises
  `FileExistsError [WinError 183]` on Windows, unlike `os.replace()` (which
  atomically overwrites) — this is exactly the Windows-vs-POSIX rename
  semantics gap that motivated this project's own `safe_io._replace_with_retry`
  / bare-os.replace-guard effort (cluster J, commits `94d36402`/`3a28ae33`),
  but that guard's regex (`\b_?os\.replace\(`) does not match `.rename(`, so
  these three call sites were never in scope for it.
- Race that produces the crash (documented in the code's own comments as an
  anticipated scenario, just not fully closed):
  1. Operator runs `py main.py cron` with `.kill_switch` present, answers
     "y" to override. `main.py:332` renames `.kill_switch` ->
     `.kill_switch.tmp` (succeeds, since `.tmp` doesn't exist yet).
  2. During the override cycle, a black-swan check re-creates
     `.kill_switch` (this is explicitly anticipated — the `finally` block
     at `main.py:346-350` has a branch specifically for "black swan
     re-created it during the run").
  3. `cron.py:2375`'s hard-kill watchdog (`_install_cron_watchdog`,
     720s default) fires `os._exit(...)` before the cycle finishes — this
     bypasses the `finally` block entirely (Python `finally` does not run
     under `os._exit`), so the reconciliation at `main.py:346-350` never
     executes. Result: both `.kill_switch` (from the black-swan re-creation)
     and `.kill_switch.tmp` (from step 1, never restored) now coexist on
     disk.
  4. Next manual `cmd_cron()` invocation: the stale-tmp-restore guard at
     `main.py:290` is `_kill_stale_tmp.exists() and not _kill_path.exists()`
     — this is False here because `_kill_path` (re-created by the black
     swan) exists, so the orphaned `.kill_switch.tmp` is never cleaned up.
  5. Kill switch is still active, so the interactive override prompt fires
     again; if the operator answers "y" again, `main.py:332` now tries to
     rename `.kill_switch` -> `.kill_switch.tmp`, but `.kill_switch.tmp`
     ALREADY EXISTS from step 1 — `Path.rename()` raises `FileExistsError`,
     uncaught, crashing the CLI invocation.
- The code's own comment at `main.py:286-288` explicitly acknowledges the
  watchdog-hard-kill / stale-tmp scenario exists ("If a previous override
  run was hard-killed by the cron watchdog (os._exit bypasses finally
  blocks), .kill_switch.tmp may have been left behind... Restore it now so
  the kill switch is never silently lost") — but the guard condition
  (`not _kill_path.exists()`) implicitly assumes a re-existing `.kill_switch`
  means "no stale tmp to worry about," which is exactly false in the
  black-swan-recreation sub-case the `finally` block's own comment describes
  as real ("black swan re-created it during the run").
- Impact/financial risk: LOW. The crash occurs only on a manual, interactive
  `py main.py cron` invocation with the kill switch already active (the
  automated loop path skips this whole block per `_called_from_loop`, so
  scheduled/unattended cron is unaffected) — trading remains halted
  throughout (kill switch stays present, fail-safe direction), the bug only
  breaks the operator's ability to run a one-shot override cycle cleanly,
  producing an unhandled-exception crash instead of a graceful message
  exactly when an operator is trying to investigate/recover from whatever
  triggered the black swan in the first place.
- Scope: FEATURE_DEPENDENCY — this code is a dependency the audited window
  touches (`f94a44bc`'s paths-safety migration changed `KILL_SWITCH_PATH`
  resolution at this exact line block; the watchdog/black-swan interaction
  this bug depends on is load-bearing infrastructure for cluster A's
  cron/trade_cycle unification and the safety-gate chain trading_gates.py
  relies on).
- Not already tracked: grepped `backlog.txt` for `FileExistsError`,
  `WinError 183`, `.rename(` — zero hits. Novel.
- Type: RELIABILITY (borderline TIME_ERROR — a race-condition ordering
  bug). Severity: LOW. Confidence: MEDIUM — the core mechanism (Path.rename
  raising FileExistsError on an existing destination on this Windows
  environment) is E2 (directly reproduced this session); the full
  multi-step race scenario is E1 (static reasoning from the code's own
  documented assumptions about watchdog/black-swan timing, not
  independently orchestrated end-to-end in a live process this session).
- Recommendation: wrap `main.py:332`'s rename in try/except (or better,
  route through `safe_io._replace_with_retry`-style atomic replace
  semantics, i.e. check-and-unlink-then-rename, or just use `os.replace()`
  instead of `Path.rename()` here since the desired semantics ARE
  "atomically replace" not "fail if destination exists"), and change the
  stale-tmp-restore guard at line 290 to also fire (deleting `.kill_switch.tmp`
  rather than trying to restore FROM it) when `_kill_path` already exists,
  mirroring the `finally` block's own `if _kill_tmp.exists(): if
  _kill_path.exists(): _kill_tmp.unlink()` logic.
- Reproduction: `audit/reproductions` — verified inline this session
  (`Path('a').rename(Path('b'))` where `b` exists raises `FileExistsError
  [WinError 183]` in this repo's environment); did not write a persistent
  repro script since the underlying stdlib behavior needs no repo code to
  demonstrate. Limitation: did not attempt to reproduce the full multi-step
  race (would require faking watchdog/black-swan timing and os._exit,
  intrusive for a read-only audit session).

## Independently re-confirmed items from the prior pass5 raw+verify files

Re-derived from current source, not merely trusted from the earlier
evidence files:

1. **cmd_order live-fill routing (cluster D, `e5331a8d`)** — confirmed
   `main.py:4870 if not _is_live: _trade = place_paper_order(...)` correctly
   gates paper-ledger writes off of real live fills; confirmed the live
   branch (`main.py:4768-4843`) routes exclusively through
   `execution_log.record_live_exit_fill`/`record_live_early_exit`, with an
   explicit unmatched-sell handling branch (opus-review-tagged NEW-H1) that
   immediately settles a row with unknown P&L rather than leaving it
   readable as an open long position. `order_executor._place_live_order`
   (lines 1552-1685) and `_auto_place_trades`'s live branch (lines 2980-3058)
   independently confirmed to route exclusively through `execution_log.*`,
   never `place_paper_order`, for the automated cron/watch live path. No
   additional un-migrated `client.place_order()` call site found beyond the
   ones already covered by this cluster (grepped all `.place_order(` call
   sites repo-wide: `main.py:4703/4713`, `order_executor.py:745/1249/1659/3266`
   — all accounted for).
2. **VaR-gate blindness to execution_log live positions** — re-confirmed
   `order_executor.py:2364 _open_trades_list = get_open_trades()` (paper-only)
   feeding `portfolio_var()` before the live-order branch, with a same-cycle
   partial mitigation at `order_executor.py:3042-3053` (each live order
   placed THIS cycle is appended to `_open_trades_list` so later same-cycle
   correlation/VaR checks see it) that does not cover live positions from
   PRIOR cycles. Matches prior pass5 finding exactly.
3. **EMOS activation gate (cluster K, `4557a77b`)** — read the full
   `cmd_emos_train` confirmation flow (`main.py:6580-6753`) end-to-end,
   including its rollback path: if `save_emos_params` succeeds but
   `reset_temperature_scale_for_emos` throws, the except block calls
   `deactivate_emos()` which unlinks `emos_params.json` AND calls
   `restore_temperature_scale_from_emos_snapshot()` — correctly unwinds a
   partial activation. No bug found in this chain; well-designed
   (DESIGN observation, not a finding).

## Other integration checks — no issues found (recorded per pass instructions)

- **cmd_watch / cron shared-engine kill-switch & soft-halt propagation**
  (cluster A): confirmed `trade_cycle.run_trade_cycle()` (lines 188-212)
  independently checks `cron.KILL_SWITCH_PATH.exists()`,
  `ctx.check_manual_override()`, `ctx.check_accuracy_halt()`, and
  `ctx.check_graduation_gate()` itself — so `cmd_watch`'s auto-trade branch
  (`main.py:3619-3648`, using the same `_build_cron_context()` helper
  cron.py uses) inherits the same gate chain even though it doesn't
  duplicate cron.py's own pre-check block (`cron.py:591-643`), which per
  that block's own comment exists only for black-swan-abort visibility
  logging, not as the actual blocking authority. No divergence found
  between the two callers' effective safety-gate coverage. INFO.
- **safe_io bare os.replace migration completeness** (cluster J): grepped
  `os.replace(` repo-wide outside `safe_io.py` — zero bare call sites
  remain in production code (only comments/docstrings referencing the
  pattern by name, and the guard test's own allowlist). Migration appears
  complete for `os.replace(` specifically; note the NEW finding above shows
  the equivalent `Path.rename()` failure mode was never brought into this
  migration's scope. INFO for the os.replace() portion itself.
- **web_app.py CSRF coverage** (cluster L): the `X-Requested-With` /
  GET-HEAD-OPTIONS check lives in a single `@app.before_request` hook
  (`web_app.py:166-209`) applied unconditionally ahead of all routes —
  confirmed this is not a per-route decorator that a new route could omit;
  every POST/DELETE route listed (`/api/run_cron`, `/api/cancel-cron`,
  `/api/halt`, `/api/resume`, `/api/override` POST/DELETE,
  `/api/forecast-cache/invalidate`, `/api/paper-order`,
  `/api/close-position`) is covered by construction. INFO, no issue.
- **Admin accuracy-circuit-breaker override reachability** (cluster M,
  `251e838e`): grepped all `@app.route` definitions in `web_app.py` (60
  routes enumerated) — none correspond to the accuracy-override CLI
  command; it is CLI-only, not dashboard-reachable. Answers recon's open
  question. INFO.
- **`/api/close-position` scope**: confirmed this route (and the paper
  Kelly-sizing route `/api/paper-order`) operate on `paper.close_paper_early`
  only — matches recon's description that the React dashboard Close button
  work (cluster F, `ee22c44c`) is paper-only. Already has its own
  server-side `(0,1]` exit_price validation and server-decided `reason`
  (no free-form client text) per its own WA-security comment. INFO, no
  issue.

No files modified outside `audit/`. No live credentials used or sought. No
git state mutated (only read-only `git show`/`git log`/`git blame`).
