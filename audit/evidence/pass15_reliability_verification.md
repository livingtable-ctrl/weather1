# Pass 15 — Reliability: Independent Verification

Verifier session, read-only. Re-checked all 4 raw findings against current tree
(worktree: reverent-lumiere-f79c1f). No files edited outside audit/.

## Finding 1 — cmd_watch --auto --live missing standalone _recover_pending_orders()

CONFIRMED. Grep confirms exactly 2 real call sites (cron.py:900-904 inside
`if client is not None:` block at ~888-923, and trade_cycle.py:222-226); the two
main.py hits (4683, 4729) are comment-only. Read of main.py:3560-3800 (current
cmd_watch loop) confirms:
- `cycle_result = None` reset every loop iteration (3613)
- run_trade_cycle() (which contains the only other _recover_pending_orders call)
  only invoked when `auto_trade` AND `ctx.acquire_cron_lock()` succeeds (3615-3648)
- `if live:` block (3759-3790) is a separate top-level conditional, NOT gated on
  cycle_result being non-None — runs _poll_pending_orders,
  _reprice_or_cancel_pending_orders, _check_live_position_exits,
  _check_live_model_exits unconditionally whenever live=True.
- _get_live_open_positions() (order_executor.py:1077) calls
  execution_log.get_filled_unsettled_live_orders(), confirmed
  (execution_log.py:535-556) to filter `status = 'filled'` only — a row stuck at
  'pending' is invisible to it.
- _poll_pending_orders (order_executor.py:424-442) filters pending rows to
  `o.get("response")` truthy only — confirmed a pending row with no stored
  order_id/response (the exact crash-window case _recover_pending_orders exists
  for) is skipped by `continue` at line 456.
- cron.py:2409 acquire_cron_lock / 2466 release-in-finally, 8-min default
  watchdog (2402-2406, "CRON_WATCHDOG_SECS") — confirmed.
- main.py:8991 `schtasks /Create /F /SC HOURLY /MO 3` confirms cron's registered
  3-hour interval cited in the finding.
- LIVE_TRADING_RUNBOOK.md:102-127 confirms "cron never places live orders... only
  watch --auto --live does" — both processes by design run concurrently against
  the same lock/DB.
- Partial mitigant not fully credited in the original finding text: cron.py's
  OWN body (lines 897-916) also calls _check_live_position_exits/
  _check_live_model_exits right after its own recovery call, specifically so a
  live position opened by a prior watch session gets protected by the next cron
  run — this is the self-healing path the original finding's own
  financial_risk field already describes ("cron.py's own next scheduled run
  within 3 hours will eventually self-heal it").

Verdict: CONFIRMED, HIGH confidence, E1 (static, but every cited line read and
independently cross-checked, including two facts not in the original evidence
list: the schtasks /MO 3 interval and the RUNBOOK's concurrent-processes design
statement).

## Finding 2 — Shadow rain-blend fetch shares _ensemble_cb with live temp blend

CONFIRMED. weather_markets.py:107-112 confirms `_ensemble_cb` module-level
singleton, failure_threshold=3, recovery_timeout=300, burst_window=2.0.
weather_markets.py:8016-8137 (_fetch_ensemble_precip_multiday) confirms
per-model closure calls `_ensemble_cb.record_failure()` in its except block
(8128-8129) on the SAME global instance, triggered by an all-null response
being turned into a raised ValueError (8103-8106). weather_markets.py:2009-2014
confirms the real Tier-1 temp-blend prewarm loop shares the identical instance
and breaks the loop entirely when `_ensemble_cb.is_open()`. Notably, the
current code at weather_markets.py:8822-8828 contains a comment written by the
original author making almost this exact same observation verbatim ("records
it on the circuit breaker SHARED with every other market's ensemble fetch, not
a benign '0 members' result") — i.e. the shared-breaker risk was already known
and partially mitigated (6-day heuristic guard, 8828-8832) by the commit's own
author, but the guard is explicitly approximate, not a proof of safety.
trade_cycle.py:308-309 confirms prewarm runs once, before the per-market loop.

Verdict: CONFIRMED, HIGH confidence (raised from original MEDIUM — the
author's own comment independently corroborates the exact mechanism), E1.

## Finding 3 — Settlement-lag force-close gate mathematically unreachable

CONFIRMED. settlement_monitor.py:277-354 (_calibrate_metar_settlement_confidence)
docstring verified verbatim against current tree: hard [0.72, 0.97] bound on
metar._dynamic_lock_in_confidence(), stated ceiling ~0.766 YES / ~0.595 NO,
both below cron.py's >=0.80 gate. Traced the consumer independently (not just
trusted the docstring): cron.py:1434-1470 `read_settlement_signals` /
`_sig_conf >= 0.80` gate confirmed still present verbatim in current cron.py,
gating `paper.close_paper_early()` only (not a live-position close — worth
noting for later passes, since the original finding's language ("T-ticker
settlement-lag force-close") doesn't specify paper vs live explicitly, and it
is in fact paper-ledger-only as currently wired). Direction scope (T-ticker
above/below only, "between" path has its own separate confidence formula and
is explicitly out of scope per the docstring) confirmed matches the code split
at settlement_monitor.py ~L400 vs ~L452.

Verdict: CONFIRMED, HIGH confidence, E1. (This finding is substantially
self-disclosed by the codebase's own docstring, as the original submission
itself notes — verification here re-derived the conclusion from the cited
numbers and independently located+read the consuming gate in cron.py rather
than trusting the docstring's claim on faith.)

## Finding 4 — ml_bias.py HMAC sidecar write bypasses atomic-write convention

CONFIRMED, with one scope addition. ml_bias.py:72-75 (_write_hmac) confirmed to
use plain `_HMAC_PATH.write_text(...)`, no safe_io import/usage anywhere in the
file for this path. ml_bias.py:78-152 (_load_models) confirmed every rejection
branch (file absent, secret absent, sidecar absent, HMAC mismatch, non-dict
deserialise, any exception) returns `{}` — never loads unverified/partial data.
Additional fact not called out in the original finding: the .pkl model file
itself is ALSO written non-atomically (`_MODEL_PATH.write_bytes(pkl_bytes)`,
ml_bias.py:262, immediately before the `_write_hmac(pkl_bytes)` call at 264) —
i.e. this isn't only the HMAC sidecar bypassing the atomic-write convention,
the primary model artifact does too. This doesn't change the safety
conclusion (a torn write to either file still produces an HMAC mismatch on
next load, which is safely rejected per the confirmed rejection logic above)
but slightly broadens the "what should be migrated to safe_io" recommendation
beyond just _write_hmac.

Verdict: CONFIRMED, HIGH confidence, E1. Severity/INFO classification is
appropriate given the fail-safe HMAC design confirmed above.

## Summary

All 4 findings CONFIRMED on independent re-read of every cited file/line; none
disproven or downgraded. Finding 2 upgraded MEDIUM→HIGH confidence based on
corroborating in-code author commentary discovered independently. Finding 4
gets a minor scope broadening (pkl write is also non-atomic, not just the hmac
sidecar) that doesn't change its INFO severity or safety conclusion.
