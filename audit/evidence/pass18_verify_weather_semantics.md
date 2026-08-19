# Pass 18 (Weather Semantics) — Verification Notes

## Finding 1: persistence_prob min-var same-day METAR gap
- weather_markets.py:6090-6154 read in full. `if var == "max" and days_out == 0 and _live:`
  guard confirmed at L6121; `else` branch (L6142-6143) covers var=="min" (and any
  days_out==1 case) and uses `_live.get("temp_f")` unconditionally — no daily-low lookup.
- metar.py:374-423 `fetch_metar_daily_extreme` confirmed to fully support `extreme="min"`
  (`return max(temps) if extreme == "max" else min(temps)`, L423).
- tests/test_weather_markets.py:5756-5781 `test_uses_instantaneous_temp_for_min_var` read in
  full; asserts exactly the current (unfixed) behavior — confirms this is intentional/tested
  current state, not a flaky/incidental gap.
- Confirmed persistence_p is blended into real (non-shadow) `blended_prob` at a real 0.15
  weight in two places: L10214-10215 (hourly path, `0.85 * ens_prob + 0.15 * persistence_p`)
  and L12016-12024 (daily path, same 0.15 weight, gated on `persistence_p is not None and
  days_out <= 2`). Both are unconditional production code paths, not behind a shadow flag.
- Verdict: claim fully matches current code. CONFIRMED, no basis found to refute it.

## Finding 2: settlement-lag force-close gate unreachable under current calibration
- settlement_monitor.py:277-359 (`_calibrate_metar_settlement_confidence`) read in full;
  docstring's claimed bound (max ~0.766 YES-lock / ~0.595 NO-lock, coefficients
  a=b=0.2262, c=0.4001) reproduced.
- ml_bias.py:494-505 `apply_metar_calibration` formula
  (`sigmoid(a*ln(s) - b*ln(1-s) + c)`) matches settlement_monitor.py's own description
  exactly — confirmed same formula, not just claimed.
- metar.py:31-57 `_dynamic_lock_in_confidence` confirmed hard-bounded to [0.72, 0.97]
  (L47, L57 `round(min(0.97, max(0.72, conf)), 3)`).
- Live coefficients on disk (main-clone data dir, resolved via safe_io.project_root() ->
  `C:\Users\thesa\claude kalshi\data\metar_lockout_calibration.json`):
  a=0.22619580826228397, b=same, c=0.4000758536385143, fitted 2026-08-16 — matches the
  docstring's cited a=b=0.2262/c=0.4001 essentially exactly (this is not a stale/mocked
  number, it's the real fitted file this code will load at runtime).
- Independently re-implemented the calibration formula from scratch (not copy-pasted from
  ml_bias.py) in audit/reproductions/metar_calibration_bound_check.py and swept the full
  documented input range. Ran it this session:
  - max calibrated YES-lock confidence = 0.7661 (at raw=0.97)
  - max calibrated NO-lock confidence = 0.5954 (at raw confidence=0.97)
  - Global max = 0.7661, well below the 0.80 gate threshold.
  - Also checked the `_METAR_CORRECTION_LIMIT = 0.60` skip-path never trips across the
    swept range (max observed delta 0.204), so the calibrated (lower) value is always the
    one actually used — confirms the gate isn't reachable via a "calibration got skipped,
    raw value used instead" escape hatch either.
- cron.py:1434-1478 read; confirms `_sig_conf >= 0.80` (L1471) gates a `close_paper_early`
  call keyed off `settlement_monitor.read_settlement_signals()`, and that the `confidence`
  written into the signal (settlement_monitor.py:469-471) is the *calibrated* value, not
  the raw `check_metar_lockout` confidence. Also confirms this path only ever touches
  `paper.close_paper_early` (paper trades), matching the finding's "financial_risk: Low,
  paper-only" framing.
- Verdict: independently reproduced and confirmed the numeric bound claim and the full
  wiring chain. CONFIRMED.
- Not independently re-verified this session (accepted as-is, E1): the docstring's
  secondary claim that cron.log has zero "SETTLEMENT LAG signal" entries and that
  `schtasks` shows the daily task unregistered — no access to the actual production
  machine/logs from this repo snapshot, so this sub-claim remains at the original E1
  static/self-reported level, not upgraded.
