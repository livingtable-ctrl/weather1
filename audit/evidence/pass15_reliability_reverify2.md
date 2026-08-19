# Pass 15 — Reliability: Second Independent Verification

Skeptical re-verification of the 4 raw findings, done without reading the prior
verifier's conclusions until after forming my own. A prior verification file
(`pass15_reliability_verification.md`) already exists in this directory reaching
similar conclusions on findings 2-4; this file adds an independent line of
attack on finding 1 that materially changes its severity assessment, plus an
actual re-run of finding 3's reproduction script against the current on-disk
calibration file.

## Finding 1 — cmd_watch missing standalone _recover_pending_orders()

Structural facts confirmed by direct read (main.py:3558-3790, order_executor.py
:269-356, 424-541, 1077-1116, execution_log.py:535-556, cron.py:888-923):
- Exactly 2 real call sites for `_recover_pending_orders` (cron.py:900-904,
  trade_cycle.py:222-226); main.py's 2 hits are comments only.
- cmd_watch's `if live:` block (main.py:3759-3790) is NOT gated on
  cycle_result/lock success — runs every cycle live=True is set.
- `_get_live_open_positions()` requires `status='filled'` (execution_log.py:551).
- `_poll_pending_orders`'s own pending-row filter requires `o.get("response")`
  truthy (order_executor.py:442) — a response-less row is skipped.

This much matches the raw finding exactly and is CONFIRMED.

**Genuine refutation attempt — found a real gap in the finding's severity
narrative.** I traced what `_recover_pending_orders` (order_executor.py:269-356)
actually DOES for the two sub-cases of a stuck 'pending' row:

1. **Row has a stored response/order_id** (the common case — an order was
   placed normally, response was logged, but no fill-status poll has landed
   yet): `_recover_pending_orders` calls `client.get_order(order_id)` and
   updates status exactly like `_poll_pending_orders` does. BUT — cmd_watch
   already calls `_poll_pending_orders(client, config=live_cfg)`
   **unconditionally** at main.py:3760, before `_check_live_position_exits`/
   `_check_live_model_exits` at 3789-3790, regardless of lock/cycle_result
   state. So for this common sub-case, cmd_watch already self-heals every
   cycle without needing `_recover_pending_orders` at all — there is no
   exposure gap here.
2. **Row has NO stored response** (the actual crash-window case
   `_recover_pending_orders`'s docstring describes — a crash between
   pre-logging the order and capturing the API response): per
   order_executor.py:303-315, `_recover_pending_orders` cannot query Kalshi
   (no order_id known) and marks the row `status="sent"` — a dedup-blacklist
   marking, NOT a transition to `status="filled"`. A row marked "sent" is
   still excluded from `_get_live_open_positions()`'s `status='filled'`
   filter. So even when `_recover_pending_orders` DOES run (cron.py's
   standalone call, or trade_cycle.py's), it cannot make a truly orphaned
   filled position visible to live-position-exit protection in this
   sub-case either — it only prevents a duplicate re-order.

Net effect: the finding's central "financial_risk" claim — a live position
left with zero automated protection for ~10-15 minutes, later self-healed by
cron's own recovery call — does not hold up under this closer trace. The one
case `_recover_pending_orders` uniquely covers (no order_id) is a case NO
code path in this system (cron.py included) can resolve into exit-protection
visibility, since resolving it requires an order_id that was never
persisted. The one case cmd_watch's missing call WOULD have covered (order_id
present, not yet polled) is already independently covered by cmd_watch's own
unconditional `_poll_pending_orders` call. I could not find a concrete
scenario where cron.py's standalone `_recover_pending_orders` call protects a
position that cmd_watch's own per-cycle `_poll_pending_orders` call would
have missed.

What IS real and unaddressed by cmd_watch: the dedup-blacklist transition
(`pending` → `sent`) for a genuinely crashed, response-less order. Without
`_recover_pending_orders`, that row stays `status='pending'` forever in
cmd_watch's own process (never polled by `_poll_pending_orders` either, same
filter gap) — which does NOT block trading (a stuck `pending` row still
counts toward `_count_open_live_orders()`/dedup checks the way it always did)
but does mean the ticket-level ambiguity is never resolved by cmd_watch on
its own; only a cron run (or restart) clears it. This is a real gap, but it
is a dedup/bookkeeping staleness issue, not "an open live position runs with
zero stop-loss for 10-15 minutes" as characterized.

Also verified independently: cron.py's watchdog default is
`timeout_secs: int = 720` (12 minutes) at cron.py:2346, not "8 min" as the
finding's evidence field states — the docstring at cron.py:2351 itself
says "default 8 min" which is stale/wrong against the actual `720` default;
the finding inherited the docstring's error. Minor, doesn't affect the core
claim.

**Verdict: CONFIRMED** (the code-level asymmetry — cmd_watch never calls
`_recover_pending_orders` directly, only conditionally via run_trade_cycle —
is real and accurately described), but **confidence downgraded to MEDIUM**:
the finding's own financial-risk narrative (an unprotected live position for
10-15 minutes, later self-healed by cron) does not survive tracing what
`_recover_pending_orders` can and cannot actually resolve. The real, narrower
consequence is a dedup-state staleness gap in the crash-before-response-
persisted case, which is not itself resolvable by any code path in the
current system (not a cmd_watch-specific deficiency). Evidence level E1
(static read only).

## Finding 2 — Shadow rain-blend fetch shares `_ensemble_cb` with live temp blend

Confirmed all cited mechanics: weather_markets.py:108-113 (`_ensemble_cb`,
failure_threshold=3, recovery_timeout=300, burst_window=2.0),
weather_markets.py:8016-8149 (`_fetch_ensemble_precip_multiday`,
`record_failure()` at 8129 inside its own internal except block, independent
of `_analyze_monthly_rain_trade`'s outer try at 8779), weather_markets.py:
2009-2014 (real Tier-1 temp-blend prewarm loop shares the identical instance,
`break`s the loop when `is_open()`). The code's own comment at
weather_markets.py:8818-8829 independently states almost this exact same
concern verbatim ("records it on the circuit breaker SHARED with every other
market's ensemble fetch... 6 days is a conservative... heuristic, not a
precise constant") — the original author was aware of this exact risk class
and only partially mitigated it.

**Materially strengthened the finding with one fact neither the raw finding
nor the prior verification file established**: `CircuitBreaker` is NOT
purely in-process/in-memory. `circuit_breaker.py:42-102` shows
`persist: bool = True` by default, with `_load_state()`/`_save_state()`
reading/writing a shared JSON file (`paths.CB_STATE_PATH`,
circuit_breaker.py:18,83-144) via `_atomic_write_json`. This means a trip
recorded by one OS process (e.g. cron.py) is visible to a completely
separate process (e.g. a concurrently or subsequently running `watch --auto
--live`) via this shared state file — the risk is genuinely cross-process,
not just intra-cycle-of-one-process as a naive reading of "module-level
singleton" might suggest.

**Verdict: CONFIRMED, HIGH confidence** (upgraded from the original MEDIUM —
both the author's own corroborating comment and the confirmed cross-process
persistence make this a stronger, better-evidenced finding than originally
scored). Evidence level E1 (static only; did not force a live all-null
response or observe an actual trip).

## Finding 3 — Settlement-lag force-close gate mathematically unreachable

Confirmed the docstring's cited formula and bounds verbatim against current
code: `settlement_monitor.py:277-359` unchanged, `ml_bias.py:494-505`
`apply_metar_calibration` formula (`sigmoid(a*ln(s) - b*ln(1-s) + c)`) matches
exactly what the finding's evidence describes. Confirmed the consuming gate
independently: `cron.py:1471` `if _sig_conf >= 0.80 and _sig_ticker in
_open_by_ticker:` — gate value and comparison confirmed current and
unchanged.

**Re-ran the actual math this session** (not just trusted the docstring):
found and executed `audit/reproductions/metar_calibration_bound_check.py`
(a pre-existing reproduction script from an earlier pass), which reproduces
`apply_metar_calibration` exactly and sweeps the full `[0.72, 0.97]` input
domain. Output:
```
max calibrated YES-lock confidence = 0.7661 at raw=0.9700
max calibrated NO-lock confidence  = 0.5954 at raw=0.9700
global max = 0.7661
gate threshold = 0.80
gate reachable? False
```
This exactly matches the docstring's claimed ~0.766/~0.595 ceiling and
confirms the gate is unreachable under this fit.

Went one step further: read the ACTUAL on-disk calibration file this
session (not just the coefficients quoted in the docstring, which could in
principle have drifted since 2026-08-16 given cluster K's weekly
auto-retrain):
```
C:\Users\thesa\claude kalshi\data\metar_lockout_calibration.json
{
  "a": 0.22619580826228397,
  "b": 0.22619580826228397,
  "c": 0.4000758536385143,
  "n": 33,
  "fitted_at": "2026-08-16T16:12:48+00:00"
}
```
This is the real, currently-active file (resolved via `safe_io.project_root()`,
the main clone, per paths.py's convention) and matches the docstring's cited
values to 4 decimal places. So this is not merely a stale docstring claim —
the CURRENT production calibration file, as of this verification session,
genuinely produces a gate that cannot reach 0.80.

Also confirmed: `read_settlement_signals` (cron.py:1437, 1452) is consumed
only by `paper.close_paper_early()` (cron.py:1455, 1482) — this force-close
mechanism only ever closes a PAPER trade, never a live Kalshi position. The
raw finding's language ("T-ticker settlement-lag force-close signal") and
its financial_risk field don't make this explicit; worth noting since it
means the actual dollar exposure of this dormant safety net is zero (no real
money is ever gated by this specific mechanism as currently wired) — the
finding's own "Low-to-moderate" financial_risk framing should really read
"paper-only, no live capital exposure."

**Verdict: CONFIRMED, VERY HIGH confidence, evidence level E2** (upgraded
from E1 — I independently re-ran the exact calibration math this session
against the current, real on-disk production coefficients, not just the
docstring's stated numbers).

## Finding 4 — ml_bias.py HMAC sidecar write bypasses atomic-write convention

Confirmed `_write_hmac` (ml_bias.py:72-75) uses plain
`_HMAC_PATH.write_text(...)`, no safe_io import anywhere in the file for this
write path. Confirmed `_load_models` (ml_bias.py:78-155) rejects on every
failure branch (file absent, secret absent, sidecar absent, HMAC mismatch,
non-dict deserialize, any exception) by returning `{}` — never loading
unverified/partial data.

Independently traced one level further than the raw finding: the primary
`.pkl` model artifact is ALSO written non-atomically
(`_MODEL_PATH.write_bytes(pkl_bytes)`, ml_bias.py:263, immediately before
`_write_hmac(pkl_bytes)` at 265) — this wasn't called out in the raw finding,
which only mentions the HMAC sidecar. Traced the fail-safe logic through
both possible torn-write orderings (torn pkl / intact-but-stale hmac; intact
pkl / torn hmac) — in both cases the HMAC comparison at load time (`expected
!= actual`) correctly rejects the mismatch, so the "fails safe" conclusion
holds even more broadly than the original finding states (both artifacts
bypass the convention, and the design remains safe against either being
torn, not just the hmac file).

**Verdict: CONFIRMED, HIGH confidence, evidence level E1.** Severity/INFO
classification is appropriate.

## Summary

All 4 findings CONFIRMED at the code-mechanism level on independent re-read.
Finding 1's confidence downgraded HIGH→MEDIUM after tracing exactly what
`_recover_pending_orders` can and cannot resolve — the claimed "10-15 min
unprotected live position, later self-healed by cron" scenario does not
survive that trace; the real, narrower gap is dedup-state staleness in a
sub-case no code path in this system currently resolves anyway. Finding 2
upgraded MEDIUM→HIGH confidence (author's own corroborating comment +
confirmed cross-process persistence of the circuit breaker via
`CB_STATE_PATH`). Finding 3 upgraded to E2 evidence by actually re-running
the calibration math against the current real on-disk coefficients (not just
the docstring's claim), and clarified as paper-only (no live capital
exposure) — not stated explicitly in the raw finding. Finding 4 confirmed
with a minor scope broadening (the .pkl write is also non-atomic, not just
the .hmac sidecar) that reinforces rather than weakens its fail-safe
conclusion.
