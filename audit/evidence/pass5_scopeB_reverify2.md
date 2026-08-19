# Pass 5 Section 10 / Scope B — independent re-verification (round 2)

## 1. Kill-switch rename race (main.py cmd_cron wrapper)
- Read main.py:270-360 in full. Confirmed 3 `.rename(` call sites at
  main.py:292, 332, 350; only 332 (`_kill_path.rename(_kill_tmp)`) is
  unguarded by try/except.
- Reproduced core mechanism this session: `pathlib.Path.rename()` to an
  existing destination on this Windows machine raises
  `FileExistsError [WinError 183]` (verified directly, see transcript).
- Confirmed cron.py:2346-2382 `_install_cron_watchdog(720)` is a real
  daemon-thread watchdog that calls `os._exit(1)` (bypasses `finally`)
  on hang; confirmed cron.py:2385-2407 `cmd_cron` (aliased
  `_cron_cmd_cron` in main.py) arms this watchdog, and this is the same
  function main.py's override branch calls at line 342 — so the
  watchdog IS armed during override runs.
- Confirmed cron.py:1034-1039 comment and code: black-swan check
  "Always runs — even during a user override" and, if triggered, calls
  `alerts.activate_black_swan_halt()` (alerts.py:564-599) which
  `_KILL_SWITCH_PATH.touch()`s — i.e. genuinely recreates
  `.kill_switch` mid-override-cycle, exactly as the finding assumes.
  Confirmed the *normal* (non-hard-killed) recreate case is already
  handled cleanly by main.py:346-350's finally block
  (`if _kill_tmp.exists(): if _kill_path.exists(): _kill_tmp.unlink()`).
- The crash requires the watchdog to hard-kill *after* black swan has
  already recreated `.kill_switch` in the same cycle (e.g. black swan's
  own `client.get_balance()` call succeeds/returns quickly, then some
  later network call in the same cycle hangs past 720s) — this
  specific ordering is plausible from the code but not independently
  reproduced end-to-end (would require orchestrating a real hang +
  process kill against a live-adjacent process, out of scope for a
  read-only audit).
- Verdict: core defect confirmed directly (E2 for the unguarded
  rename + FileExistsError mechanism); full trigger chain is E1
  (documented/plausible, not executed). Financial risk is low as
  claimed (kill switch stays engaged either way).

## 2. portfolio_var() blind to live positions
- order_executor.py:2364 `_open_trades_list = get_open_trades()`,
  :2930 `portfolio_var(_open_trades_list + [candidate])`, :3042-3053
  append-only-same-cycle-live-trades block (comment "F6") all confirmed
  verbatim.
- paper.py:1299-1301 `get_open_trades()` confirmed to read exclusively
  from the JSON ledger (`_load()["trades"]`), no execution_log
  involvement.
- backlog.txt:~1994-2057 confirmed to already contain this exact
  finding, including the "confirmed EMPIRICALLY MOOT today: zero
  live=1 rows have ever existed in execution_log" line (grepped
  directly, line 2002 region). Also cross-referenced in this audit's
  own prior evidence files (pass5_verify.md, pass5_section10_scopeB_verify.md,
  pass11_state*.md, pass13_security*.md, pass14_performance*.md,
  pass17_ai_code_failure_patterns.md) — consistent re-derivation, not
  a single-source claim.

## 3. cmd_watch / cron shared gate chain
- trade_cycle.py:188-217 confirmed: `run_trade_cycle()` independently
  checks kill switch, manual override, accuracy halt, and graduation
  gate (`ctx.check_graduation_gate()` raising RuntimeError converts to
  halted_reason).
- main.py:3619-3632 confirmed `cmd_watch`'s auto-trade branch builds
  `ctx = _build_cron_context()` and calls `run_trade_cycle(ctx, ...)` —
  same context-builder cron.py uses.

## 4. os.replace() migration completeness
- `grep -rn "os\.replace(" --include=*.py .` (excluding tests/audit)
  returns only safe_io.py's own implementation (line 60) and a comment
  in circuit_breaker.py (line 76) referencing it. Zero other bare call
  sites. Confirmed complete for this specific pattern.

## 5. web_app.py CSRF before_request coverage
- web_app.py:166-209 confirmed: single `@app.before_request def
  _check_auth()` hook, single `Flask(__name__)` instance (no
  blueprints found — `grep -n "Blueprint\|register_blueprint"` empty),
  so the hook applies unconditionally to every route.
- Route count discrepancy found: actual `grep -c "@app.route"
  web_app.py` = 68, not the 60 claimed in the original finding. This
  is a minor inaccuracy in the original evidence (miscount or drift
  since it was written), but doesn't change the substance — coverage
  here is structural (one global before_request on one Flask app), not
  contingent on the exact route count. All 10 methods=[POST/DELETE/...]
  routes independently re-enumerated (run_cron, cancel-cron, halt,
  resume, override GET/POST/DELETE, forecast-cache/invalidate,
  paper-order, close-position) and confirmed present.

## 6. Admin accuracy-override CLI-only
- Confirmed via `git show 251e838e --stat`: adds `py main.py admin
  accuracy-override / accuracy-clear / accuracy-status`, a CLI-only
  subcommand family (commit message itself describes it as CLI,
  modeled on `admin reset-loss`).
- `grep -in "accuracy.override" web_app.py` returns zero matches —
  confirmed no dashboard route exists for it.
