# Pass 20 — Scope D & Section 33 — Independent Re-verification

Verifier session, re-examining 3 raw findings from "Pass 20 — Unrelated Discovery".
Did not trust prior analysis; re-read all cited files/lines directly and re-ran
reproductions myself.

## Finding 1 — LiveTradingGate drawdown/streak checks are paper-ledger-only

CONFIRMED, HIGH confidence, E2 (ran the repro myself this session).

- Read trading_gates.py in full (140 lines): `LiveTradingGate.check()` imports
  and calls `is_paused_drawdown`, `is_streak_paused`, `is_daily_loss_halted(client)`,
  `is_accuracy_halted`, `graduation_check` — all from `paper` module.
- Read paper.py `is_paused_drawdown` (L626-635): calls `_drawdown_snapshot()`
  which reads only `_load()` (paper.py's own JSON ledger `paper_trades.json`).
  No execution_log import/read anywhere in the function.
- Read paper.py `is_streak_paused` (L2436-2454): reads only `_load()["trades"]`.
  Same — no execution_log.
- Read paper.py `is_daily_loss_halted`/`get_daily_pnl` (L2664-2754): settled_pnl
  term sums `_load()["trades"]` only; the `client` param is used solely to call
  `get_unrealized_pnl_paper(client)`, which itself (L3383+) marks-to-market
  `get_open_trades()` — paper's own open positions, fetching only *quotes* via
  the client, never reading anything from execution_log. So even the one
  sub-check that accepts a client cannot see real live P&L.
- Confirmed `is_paused_drawdown`/`is_streak_paused` are also called directly in
  `order_executor._auto_place_trades` (L2339, L2358) — the shared batch-placement
  path used for both `live=True` and `live=False` calls (cron/watch --auto).
- Ran `audit/reproductions/verify_pass20_gate_paper_only.py` myself this session
  (uses only a `tempfile.TemporaryDirectory()`, monkeypatches `paper.DATA_PATH`
  and `execution_log.DB_PATH` at the attribute level — never touches real
  project data/). Output:
  ```
  execution_log.get_today_live_loss() after 10x $95 live losses = $950.00
  paper.is_paused_drawdown()  -> False
  paper.is_streak_paused()    -> False
  paper.get_balance()         -> 1000.0
  paper.get_peak_balance()    -> 1000.0
  ```
  Confirms the claim exactly: $950 in real recorded live losses, both gates
  report healthy.
- Also confirmed `_place_live_order` (order_executor.py L1552+) does have its
  own separate single-day check via `execution_log.get_today_live_loss()`
  (L1577) — this is a distinct, already-working control; the finding's scope
  (drawdown/streak across multiple days, or a slow bleed under the daily cap)
  is correctly distinguished from it, not overlapping/redundant.

No refutation found. Finding stands as described.

## Finding 2 — schema_validator.py return values discarded

CONFIRMED, HIGH confidence, E1 (static, matches original evidence level).

- Read schema_validator.py in full (196 lines): confirms `validate_market`,
  `validate_forecast`, `validate_nws_response` all return `bool` per docstring
  and log warnings internally.
- Grepped every call site repo-wide: exactly 4 production call sites —
  kalshi_client.py:324, kalshi_client.py:343, nws.py:236, weather_markets.py:1525
  — all bare statement calls, return value discarded, code proceeds identically
  either way.
- Read each site in context to confirm no wrapping `if not validate_x(...): skip`
  pattern exists anywhere. None do.
- Additional detail beyond the original finding: nws.py:234-237 has a comment
  ("validate BEFORE recording success so a malformed-but-HTTP-200 response
  doesn't credit the circuit breaker") that implies the *intent* was for the
  validation result to gate `_nws_cb.record_success()`, but the actual code
  calls `record_success()` unconditionally right after, regardless of
  `validate_nws_response`'s return value. This slightly strengthens the
  finding: at least one call site's own comment documents an intended gating
  behavior that isn't actually wired in, not just an ambiguous bool signature.

No refutation found. Finding stands, slightly strengthened.

## Finding 3 — param_sweep.py PAPER_MIN_EDGE sweep/accept range mismatch

CONFIRMED (bug/limitation is real and independently reproduced), but the
**root_cause narrative in the original finding is incorrect** — downgrading
that one field only; the practical finding stands.

- Read param_sweep.py L102-129 (`load_swept_min_edge`) and L132-169 (`run_sweep`)
  directly: `params_to_sweep["PAPER_MIN_EDGE"] = [0.15, 0.20, 0.25, 0.30, 0.35, 0.40]`;
  `load_swept_min_edge` clamps accepted results to `0.03 <= val <= 0.15`.
  Ranges intersect at exactly one point (0.15) — confirmed by direct read.
- Re-ran `audit/reproductions/repro_pass20_param_sweep_scale_mismatch.py` myself
  this session. Output matches the original claim exactly: value=0.15 gets 41
  trades/0.7561 win rate; values 0.20-0.40 all get trades=0/win_rate=None
  (with this repro's synthetic net_edge distribution); testing PAPER_MIN_EDGE's
  own documented range [0.03,0.15] instead populates every step (41-500 trades).
- **Root-cause correction**: the original finding calls this "an apparent
  copy-paste error" from MED_EDGE's adjacent list entry. `git log -p -L
  160,170:param_sweep.py` shows this is wrong — commit `b476092787` (2026-06-07,
  "Fix 4 bugs in edge detection, param sweep, weights TTL, and daily spend cap")
  *deliberately* changed PAPER_MIN_EDGE's swept values from
  `[0.03, 0.05, 0.06, 0.07, 0.08, 0.10, 0.12, 0.15]` to
  `[0.15, 0.20, 0.25, 0.30, 0.35, 0.40]`, with the commit message stating this
  was "to match the actual net_edge scale" (that same commit also fixed a
  real, separate, pre-existing bug: `sweep_parameter` was filtering on
  `t.get("edge")`, a field paper.py never writes, silently producing all-N/A
  results at every threshold before this commit). The commit added a comment
  (still present, param_sweep.py L162-165) explicitly acknowledging that
  `load_swept_min_edge` clamps to [0.03, 0.15] and asserting this keeps
  auto-tuned values "safe... regardless of which threshold wins here" — i.e.
  the author was aware of the clamp and treated it as a deliberate safety
  backstop, without apparently registering that it also makes the
  PAPER_MIN_EDGE sweep unable to ever surface a value above 0.15. This is a
  **stale/incomplete fix that left a companion function's range un-synced**,
  not a copy-paste mistake between two unrelated dict entries (MED_EDGE's own
  values were intentionally moved in the same commit for the analogous
  reason, not copied from one to the other).
- This correction doesn't change the practical bug: regardless of intent,
  `load_swept_min_edge()` can currently never return anything other than 0.15
  or None, so 5 of the 6 swept candidate values are structurally unusable
  output, and the finding's practical conclusion ("param_sweep-based auto-tune
  for PAPER_MIN_EDGE is silently non-functional across most of its intended
  range") is accurate and independently confirmed.
- Caveat on the reproduction's realism: the repro's synthetic net_edge is
  uniform on [0.03, 0.16] (matching PAPER_MIN_EDGE's config.py-documented
  *config-value* domain), but the June 2026 commit's own message claims real
  historical net_edge (the field actually being swept, not the config
  parameter) sits in a 0.15-0.87 range in practice. If that historical claim
  is accurate, the true population of real trades may have few/no records
  below 0.15 either, which would mean the "sub-0.15 region... never tested"
  framing in the original finding's `actual_behavior` is describing a region
  that may be nearly empty in real data anyway. This does not change the
  core structural-mismatch conclusion (only 0.15 can ever be returned), but
  the "financial_risk"/practical-severity framing should be read with that
  caveat — I did not have access to real historical `paper_trades.json` data
  to check the real net_edge distribution directly, so I cannot confirm which
  characterization (0.03-0.16 vs 0.15-0.87) better describes production data.
