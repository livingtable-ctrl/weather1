# Pass 3 — Requirements: Second-pass independent re-verification

(A prior verification file, audit/evidence/pass3_requirements_verification.md, already
exists in this worktree from an earlier session. This is a fresh, independent re-check
performed this session against current code, not a re-read of that file's conclusions.)

## Finding 1 — check_position_limits() exposure caps blind to live cmd_order positions
- Read paper.py:3447-3686 (full check_position_limits body) directly this session.
  Confirmed per-market cap (L3629-3633), global cap (get_total_exposure, L3645), and
  city/date/directional/correlated caps (L3653-3685) all derive solely from
  get_open_trades() (paper.py:1299-1301 = `_load()["trades"]`, i.e. paper_trades.json).
- Read get_city_date_exposure/get_directional_exposure/get_total_exposure/
  get_correlated_exposure (paper.py:1598-1673) directly — all call get_open_trades(),
  zero reference to execution_log anywhere in paper.py (grepped, only comments mention it).
- Confirmed main.py:4528 `_is_live = getattr(client, "base_url", None) != DEMO_BASE` and
  main.py:4546-4569 cmd_order buy path calling `check_position_limits()` as a real gate.
- Grepped `_get_live_open_positions` repo-wide: used only in cmd_order's live-sell
  matching, order_executor exit-gate logic, and positions.py — never fed into
  check_position_limits or any exposure getter.
- Re-ran audit/scratch/repro_exposure_blind.py this session: output matches claim exactly
  — `{'ok': True, 'reason': None, 'existing_cost': 0, 'limit': 250.0}` for a second live
  buy that should breach the 15% directional cap.
- Verdict: CONFIRMED. E2 (reproduced this session).

## Finding 2 — startup banner wrongly claims only `watch --auto --live` can place live orders
- Read main.py:9550-9587 directly. `_live_orders_possible = cmd == "watch" and "--auto"
  in args and "--live" in args` (L9567) and the false-claim print (L9578) match exactly.
- Confirmed `cmd = args[0].lower()` (L9537/9603) and cmd_order's live path (main.py
  ~L4528-4569) is reached independently of `_live_orders_possible`.
- CORRECTION to the finding: its reproduction text says `py main.py order buy <ticker>
  ...` and its recommendation suggests checking `cmd == "order"`. Neither is accurate —
  there is no `"order"` command in main.py's dispatcher (grepped `cmd == "order"`: zero
  matches). The real dispatch is `elif cmd in ("buy", "sell"): cmd_order(client, cmd,
  args[1:])` (main.py:9696-9697), i.e. the actual invocation is `py main.py buy <ticker>
  ...` / `py main.py sell <ticker> ...`, with cmd equal to "buy"/"sell", not "order". The
  underlying defect claim (the banner is misleading for a real live-order-capable command
  that isn't `watch --auto --live`) is still correct, but literally implementing the
  finding's own recommendation (`cmd == "order"`) would NOT fix the bug, since cmd is
  never "order". The fix needs `cmd in ("buy", "sell")` instead.
- Verdict: CONFIRMED (core defect real and reproducible from static read), but confidence
  reduced from VERY HIGH to HIGH because the finding's own reproduction command and its
  recommended fix condition are factually wrong about the CLI's actual command name.

## Finding 3 — METAR settlement-lag force-close gate structurally unreachable
- Read cron.py:1440-1485: confirmed `_sig_conf >= 0.80` gate at L1471 exactly.
- Read settlement_monitor.py:277-345 (_calibrate_metar_settlement_confidence) and
  ml_bias.py:494-505 (apply_metar_calibration): formula is
  `sigmoid(a*ln(s) - b*ln(1-s) + c)`, matches the finding's re-derivation.
- Read metar.py:31-57 (_dynamic_lock_in_confidence): confirmed hard bound
  `round(min(0.97, max(0.72, conf)), 3)` → domain [0.72, 0.97].
- Went one step further than the prior verification pass: read the REAL currently-fitted
  calibration file directly (not just the docstring's cited numbers). Since paths.py
  resolves data/ to the main clone, read
  `C:\Users\thesa\claude kalshi\data\metar_lockout_calibration.json` directly:
  `{"a": 0.22619580826228397, "b": 0.22619580826228397, "c": 0.4000758536385143, "n": 33,
  "fitted_at": "2026-08-16T16:12:48+00:00"}` — confirms the docstring's cited
  a=b=0.2262, c=0.4001 are in fact the live, currently-active fitted values (fitted only
  2 days before this audit), not stale or hypothetical numbers.
- Re-ran audit/reproductions/metar_calibration_bound_check.py this session: output
  matches exactly — max YES-lock 0.7661 at raw=0.97, max NO-lock 0.5954 at raw=0.97,
  gate reachable: False.
- Verdict: CONFIRMED. E2 (reproduced this session + cross-checked against the live data
  file, strictly stronger evidence than a docstring citation alone). Note: this is
  substantially a re-statement of an already-self-documented in-code finding
  (settlement_monitor.py's own docstring states the same 0.7661/0.5954 figures) — real
  and correctly LOW severity given the mechanism has reportedly never fired against real
  trades (not independently re-verified this session: no access to cron.log/schtasks
  state for the reference deployment machine from this worktree).

## Finding 4 — live cmd_order sell only closes oldest of N>1 tracked positions
- Read main.py:4577-4666 directly. Confirmed the code, the "Opus review (2026-08-17),
  NEW-M1" comment (near-verbatim to the finding's quote), and the yellow warning print
  exactly as described.
- Went further than prior pass: verified the "oldest" claim against the actual ordering.
  order_executor._get_live_open_positions() (order_executor.py:1077-1115) calls
  execution_log.get_filled_unsettled_live_orders() (execution_log.py:535-556), whose SQL
  is `ORDER BY placed_at` (ascending, no DESC) — so `_live_open_matches[0]` genuinely is
  the oldest by placed_at. Claim confirmed at the SQL level, not just assumed from the
  variable name.
- Verdict: CONFIRMED. E1 (static read, code path not executable without live credentials).

## Finding 5 — AMBIGUITY: no spec for N>1 live-sell-match behavior
- Grepped tests/test_live_execution.py, tests/test_trading_gates.py, and all of tests/
  for `_live_open_matches`/"NEW-M1"/"multiple...live...position": zero matches anywhere,
  confirming no automated test asserts a specific behavior for the N>1 scenario.
- However, unlike the finding's own search (which only checked tests + a commit message
  per its own "limitations" field), I grepped backlog.txt and found the design decision
  IS documented there. backlog.txt:1858-1871 has a section literally titled "ACCEPTED,
  EXPLICITLY REASONED LIMITATIONS (not fixed, per-finding reasoning stated rather than
  silently dropped)" with an entry "NEW-M1 (multiple open live positions can legally
  share a ticker+side ...)" that states: "a cmd_order sell only closes the OLDEST
  matching position -- closes_position_id is a single column, not a list, matching every
  other exit mechanism in this codebase (_exit_live_position also only ever closes one
  position per call). A full fix needs either schema support for closing multiple
  positions with one order or preventing the duplicate-entry root cause in the first
  place. Mitigated with an explicit operator-facing warning..."
- This directly contradicts the finding's central evidentiary claim ("No test, docstring,
  or backlog entry found that states what SHOULD happen ... framed as an unresolved
  design question"). backlog.txt does state what should happen (currently): close the
  oldest, by deliberate choice, for stated architectural reasons (single-column
  closes_position_id matching every other exit mechanism in the codebase), pending a
  larger schema change. This is a documented, reasoned, already-made design decision, not
  an open ambiguity awaiting an AskUserQuestion-style choice between interpretations (A)
  and (B) as the finding frames it.
- Verdict: DISPROVEN as framed. The narrower observation that no *automated test* pins
  this behavior down is true (and mildly interesting as a test-coverage gap), but the
  finding's actual claim — that the intended behavior is unspecified/ambiguous and needs
  a human decision — is false; the decision was already made and documented with
  reasoning in backlog.txt, in the same commit-adjacent entry that Finding 4 itself
  quotes from (main.py's own comment references this exact backlog entry by name).

## Summary
4 of 5 findings CONFIRMED (1, 2, 3, 4); 1 DISPROVEN as framed (5), because backlog.txt
already contains an explicit, reasoned specification of the current intended behavior
that the finding claimed did not exist. Finding 2's confidence was reduced from VERY HIGH
to HIGH because its own reproduction command (`py main.py order buy ...`) and recommended
fix condition (`cmd == "order"`) don't match the actual CLI dispatch (`cmd in ("buy",
"sell")`), though its core defect claim survives. Finding 3 was independently
strengthened this session by reading the live (main-clone) calibration data file directly
rather than trusting the docstring's cited coefficients.
