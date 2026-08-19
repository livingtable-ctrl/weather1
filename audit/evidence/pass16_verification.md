# Pass 16 (Test Quality) — Independent Verification Notes

All 4 findings independently re-verified this session by reading current code and
(where applicable) re-running the cited/an equivalent reproduction. All 4 CONFIRMED,
none disproven or downgraded.

## Finding 1 — CSRF X-Requested-With rejection path untested
- Read web_app.py:166-209 (`_check_auth`): confirmed the exact logic — Basic-auth
  password match then `method in (GET,HEAD,OPTIONS) or header == "XMLHttpRequest"`.
- `grep -n X-Requested-With tests/test_web_auth.py tests/test_p0_16_cron_endpoint.py`:
  both files' shared header-builder helpers unconditionally set the header (lines 21-24
  and 25-28 respectively). No other test file constructs Basic-auth headers without it
  (checked test_web_app.py's kill-switch tests too — those bypass auth entirely via
  `monkeypatch.setattr(utils, "DASHBOARD_PASSWORD", "")`, so they don't exercise the
  CSRF branch either).
- Ran `python -m pytest audit/reproductions/test_csrf_header_gap_repro.py -q` myself:
  **1 passed** — confirms production code correctly 401s on correct-password/no-CSRF-header
  today, and independently confirms this exact case is absent from the real suite.
- Verdict: CONFIRMED, E2 (self-executed).

## Finding 2 — V_3 frontend tree has zero test coverage
- `find "weather app site V_3 (3)" -iname "*.test.*" -o -iname "*.spec.*"` → empty.
- `find "weather app site V_3 (3)" -maxdepth 2 -iname package.json` → empty (no build/test infra).
- `find frontend -iname "*.test.*"` → `frontend/src/useData.test.js` only.
- `git show d47b59d3 --stat`: touches only `weather app site V_3 (3)/src/tabs/PositionsTab.jsx`
  (84 lines changed), no test file anywhere in the diff.
- `git show 0edf818b --stat`: touches `frontend/src/useData.js` (+108), `frontend/src/useData.test.js`
  (+169), and 4 files under `weather app site V_3 (3)/src/` (useData.js +178, PositionsTab.jsx +70,
  AnalyticsTab.jsx, OverviewTab.jsx) — zero V_3-tree test files in that diff. Commit body itself
  says "18 vitest tests (12 pre-existing + 6 new)" — all in the tracked `frontend/` copy.
- `wc -l frontend/src/useData.test.js` → 276, matches finding.
- Verdict: CONFIRMED, E1 (static/absence evidence, as originally claimed).

## Finding 3 — Bare MagicMock() for KalshiClient in live-trading test files
- `grep -c "MagicMock()" tests/test_live_execution.py tests/test_trading_gates.py` → 83, 20 (exact match).
- `grep -c "MagicMock(spec" ...` → 0, 0.
- `grep -rln "MagicMock(spec" tests/` → only `tests/test_phase2_batch_e.py` (2 occurrences, unrelated file).
- Spot-checked variable names at MagicMock() call sites in test_trading_gates.py (lines 145, 223,
  250, 284, 316/320, 334, 370, 405, 421...) — all named `mock_client`/`demo_client`/`prod_client`,
  confirming these stand in for KalshiClient specifically.
- Confirmed `kalshi_client.KalshiClient` defines real `place_order`, `get_order`, `get_market`
  methods (grepped defs at lines 460, 610, 339).
- Ran my own repro: bare `MagicMock().nonexistent_method()` succeeds silently; 
  `MagicMock(spec=kalshi_client.KalshiClient).nonexistent_method()` raises `AttributeError`
  — reproduces the claimed contrast exactly.
- Verdict: CONFIRMED, E2 (self-executed).

## Finding 4 — No structural gate-parity test between validate() and trade_cycle tiering
- Read order_executor.py:1940-2058 (`_validate_trade_opportunity`): confirmed gate chain —
  system health, flash crash, edge sign/MIN_EDGE, confidence-tiered min_edge, Kelly floor
  (`ci_adjusted_kelly`/`fee_adjusted_kelly`/0.0 fallback, >= 0.002) — matches description.
- Read tests/test_trade_cycle_engine.py around 1481-1567 (`TestPlacementKellyFloorGateTierClassification`):
  confirmed these are individually-added regression tests, each docstring explicitly citing a
  specific prior backlog fix (resolved 2026-08-08), not a structural/enumerated check.
- Read trade_cycle.py:660-715: the Kelly-floor mirror is hand-written inline with a comment
  "Mirrors validate()'s Kelly floor exactly, including its None-safe ... fallback chain" —
  confirms hand-maintained parallel logic, not a shared/derived source of truth.
- `grep -rln "gate_parity|parity_test|GATE_NAMES|gate.*manifest" tests/` → no matches anywhere
  in the 155-file suite. No structural/enumeration-style test exists.
- Verdict: CONFIRMED (as a design/test-gap observation — the original finding itself flagged this
  as lower-certainty/design-level, appropriately kept at MEDIUM confidence), E1.

## Summary
4/4 findings survive verification unchanged in substance. No downgrades, no disproven claims.
Confidence/evidence levels affirmed or upgraded where I personally executed reproductions
(Findings 1 and 3 now have E2 evidence I generated myself, not just inherited from the original pass).
