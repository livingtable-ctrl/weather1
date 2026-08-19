# Pass 8 (Mathematics) — Independent Re-verification

Skeptical re-check of 3 raw findings from Pass 8 (Sections 19 & 51). Did not
trust the original analysis; re-derived/re-ran everything cited below.

## Finding 1 — METAR settlement-lag force-close gate "structurally unreachable"

- Read settlement_monitor.py in full (608 lines), metar.py's
  `_dynamic_lock_in_confidence` (L31-57, hard-bounded [0.72, 0.97]), and
  ml_bias.py's `apply_metar_calibration`/`fit_metar_calibration` (L396-505).
- Independently re-implemented the beta-calibration formula from scratch
  (not importing ml_bias) in `audit/reproductions/metar_calibration_bound_check.py`
  and swept raw confidence in [0.72,0.97] at 100,000-point resolution with
  a=b=0.2262, c=0.4001 (the coefficients cited in the commit's own docstring,
  settlement_monitor.py L304-319). Result: max YES-lock=0.7661, max
  NO-lock=0.5954 — **exactly** matches the original finding's numbers. The
  T-ticker-specific sub-claim is CONFIRMED, independently reproduced.
- BUT: found a materially disqualifying gap in the finding's overall
  conclusion. `check_city_settlement` (settlement_monitor.py L362-471) has
  TWO branches: T-ticker (above/below, calibrated via
  `_calibrate_metar_settlement_confidence`) and **B-ticker/"between"**
  (interior bucket strikes, L401-453). The between branch computes its own
  confidence directly via `_check_between_settlement` (L169-274:
  `min(0.95, 0.60+clearance*0.03)` for NO, `min(0.95, 0.70+risk_clearance*0.05)`
  for YES) and is **never passed through calibration at all** — confirmed by
  reading the code (no call to `_calibrate_metar_settlement_confidence` in
  that branch) and by the settlement_monitor.py docstring itself (L285:
  "T-ticker (above/below) only -- the `between` path has its own separate
  confidence formula and is out of scope").
- Both signal types are written into the same `settlement_signals.json` via
  `write_settlement_signals`/`run_settlement_monitor` (L493-606, `all_signals`
  mixes both), and cron.py's force-close block (L1471) reads
  `sig.get("confidence")` uniformly with `>= 0.80`, with no branch on
  signal source/type.
- Ran the repo's own existing test
  `tests/test_settlement_monitor.py::TestMetarSettlementCalibration::test_between_path_not_calibrated`
  (`py -m pytest tests/test_settlement_monitor.py -k test_between_path_not_calibrated -v`)
  — **PASSED**. It asserts a between-bucket YES-lock signal reaches
  `confidence == 0.80` (exactly at cron.py's `>=0.80` gate), uncalibrated,
  and explicitly notes that if calibration leaked into this path the value
  would instead be ~0.671. This is E2 (I ran it), not speculation.
- Conclusion: the finding's title/actual_behavior claim ("it will never
  fire, regardless of how confident the raw METAR lock-in becomes") is
  **false** — it is only true for the T-ticker sub-path. Between-bucket
  settlement signals bypass calibration entirely and can reach the 0.80
  threshold (confirmed to hit it exactly at the boundary in a real test,
  and the NO-direction formula has headroom up to 0.95 given enough
  clearance, which is realistic on days where the actual high blows past a
  narrow 2°F bucket by several degrees). Since interior/between buckets
  vastly outnumber the 2 outer T-ticker strikes per city per day, this is
  not a corner case — it's likely the dominant signal type reaching cron's
  force-close check in practice.
- Verdict: **DISPROVEN** as stated (the overall/title-level claim), while
  the narrower reproduced T-ticker-calibration-bound sub-finding is itself
  correct.

## Finding 2 — trade_cycle.py net_edge fallback mismatch vs validate()

- Read trade_cycle.py L440-680 and order_executor.py L1995-2024 in full.
  Confirmed byte-for-byte:
  - trade_cycle.py L467-471: `net_edge = analysis.get("net_edge") or
    analysis.get("edge") or 0.0` (None-safe chain).
  - order_executor.py L2011-2015 (`_validate_trade_opportunity`):
    `edge = opp.get("net_edge"); if edge is None: edge = 0.0` — no raw-edge
    fallback.
  - trade_cycle.py L658-671 already contains an inline comment documenting
    this exact divergence and arguing it can only make the mirror MORE
    permissive, never less — this is not new information the audit
    surfaced, it's already-shipped, already-reviewed code commentary.
- Ran the existing reproduction `audit/reproductions/net_edge_fallback_mismatch.py`
  (present in the repo already, presumably from the same/earlier pass) —
  verified the source snippets inside it against the real current file
  contents line-by-line before trusting its output, then executed it.
  Output confirms the mismatch: trade_cycle's mirror says
  `clears_placement_gate=True` on `{net_edge: None, edge: 0.30}` while
  order_executor's real gate says `ok=False, reason='edge=0.0000 <= 0'`.
- Went further than the original finding on reachability: grepped the
  entire weather_markets.py for every `"net_edge":` and `"edge":` dict-key
  assignment. Found exactly 10 of each (9 real call sites +
  `_price_and_size`'s own return dict) — i.e. **every** single place in
  weather_markets.py that sets either key goes through the one shared
  `_price_and_size` helper (L7797-7902), which always computes and returns
  both `net_edge` (L7843) and `edge` (L7844) as floats, never None. This
  includes the hourly-market path (L10241) and the path with an
  arb-adjacent block near L12807 — both explicitly checked and confirmed to
  route through `_price_and_size` too, closing the exact gap the original
  finding flagged as an unaudited limitation ("I did not check
  hourly-market or arbitrage-only analysis paths").
- Verdict: **CONFIRMED**, and the "unreachable in current code" claim is
  even more solidly supported than the original finding stated (100% of
  weather_markets.py's edge-setting sites covered, not just "the vast
  majority").

## Finding 3 — far-tail rain blend n_members metadata doesn't log tail-year count

- Read weather_markets.py L8830-8940 (`_analyze_monthly_rain_trade`'s
  far-tail branch) in full. Confirmed:
  - `combined_totals = [m + t for m in member_totals for t in
    tail_sums_tilted]` (L8896-8898).
  - `forecast_blend_signal` (L8918-8933) logs
    `rain_forecast_blend_tail_days` (a calendar day count, `days_in_month -
    tail_start_day + 1`) and `rain_forecast_blend_n_members` (=
    `len(member_totals)`, the near-ensemble count) — never
    `len(tail_sums_tilted)` (the tail-year sample count).
  - Grepped the whole file for `tail_sums_tilted`/`tail_years`/`len(tail_sums)`
    — the tail-year length is used only for the `>=15` gate check (L8858)
    and a debug log on the *skip* path (L8907); it is never captured
    anywhere near the success-path metadata dict.
  - Confirmed the signal is genuinely shadow/log-only: `blended_prob` is
    computed at L8941-8943 from `remaining_sums_tilted` (set independently
    at L8737, well before the far-tail block), not from `combined_totals`.
    `forecast_blend_signal` is merged into the returned analysis dict only
    as a nested `"signals"` key (L9050-9054), never read back into
    `blended_prob`/`rec_side`/Kelly sizing anywhere in this function.
  - Grepped the whole repo for `rain_forecast_blend` outside
    weather_markets.py — zero hits (no test file, no downstream consumer
    yet), confirming the original finding's MEDIUM-confidence caveat
    ("did not verify whether some other part of the codebase already
    recomputes or has access to the tail-year count via another path") —
    verified: it does not exist anywhere else in the repo.
- Verdict: **CONFIRMED**, and confidence upgraded from MEDIUM to HIGH since
  the one caveat the original author flagged was directly checked and
  found to hold (no other consumer exists).

## Reproduction scripts (this session)
- `audit/reproductions/metar_calibration_bound_check.py` (new, written this
  session) — independent re-derivation of the calibration bound.
- `audit/reproductions/net_edge_fallback_mismatch.py` (pre-existing in the
  repo; read and verified against current source before trusting, then
  executed).
- Ran `py -m pytest tests/test_settlement_monitor.py -k
  test_between_path_not_calibrated -v` — 1 passed. This is the E2 evidence
  that disproves Finding 1's blanket claim.
