# Grade Audit — alerts.py
Generated: 2026-06-29

---

## TIER 1 Functions

---

### [alerts.py] check_black_swan_conditions() L:374–458  ★ T1
Score: 7/10  |  Confidence: Confirmed
AC: FAIL AC1 (partial) — `bs = _brier_score()` — called without explicit `min_days_out=1`; relies on the default `min_days_out=1` in `tracker.brier_score`. Functionally correct today but fragile: if the default changes, this silently starts mixing same-day trades into the black-swan Brier check.
Red flag: NONE (exception is caught; exception path logs nothing — see WEAKNESSES)
Invariants: I1 — PASS (consecutive loss check uses `t.get("days_out", 1) >= 1`; Brier uses `brier_score()` default=1; `count_settled_predictions()` uses multiday_predictions view)

STRENGTHS:
• Multi-day filter on consecutive losses is explicit: `t.get("days_out", 1) >= 1` (line 395) — same-day METAR trades cannot trigger black swan.
• `_trade_won()` used for consecutive-loss detection — side-aware, no confusion between outcome and profitability.
• `count_settled_predictions()` already queries `multiday_predictions` view — sample gate uses correct denominator.
• Daily loss pct correctly normalises against `peak_balance` not current balance — right denominator.
• Non-None guards on balance/peak_balance before computing daily loss.

WEAKNESSES:
• line 443: `bs = _brier_score()` — no explicit `min_days_out=1` argument. Relies on the current default. If `tracker.brier_score` default ever changes to 0, same-day METAR trades contaminate the black-swan Brier check. Low risk today, but should be explicit.
• lines 455–457: `except Exception: pass` — if tracker DB is corrupt or raises, the Brier check is silently skipped with zero log output. An operator watching logs would not know the Brier check was suppressed. Should log at WARNING or DEBUG.
• lines 413–432: daily loss computation uses `str(placed_at).startswith(today_str)` — `placed_at` is an int UNIX timestamp in most trades, not an ISO string. `str(1719619200).startswith("2026-06-29")` is always False. The daily loss check effectively never fires.

FAILURE SCENARIO:
A day of heavy losses: 5 trades placed on 2026-06-29, each losing $30 (total -$150 on a $800 peak). `placed_at` values are UNIX timestamps like `1719619200`. `str(1719619200)` = `"1719619200"` which does not start with `"2026-06-29"`. `today_trades` is always empty. The daily loss BLACK SWAN condition never triggers regardless of actual daily P&L magnitude.

FIX:
alerts.py:413–419 — replace `str(t.get("placed_at", t.get("ts", ""))).startswith(today_str)` with a proper timestamp comparison:
```python
ts = t.get("placed_at", t.get("ts", 0))
try:
    trade_date = datetime.fromtimestamp(float(ts), tz=UTC).date().isoformat() if isinstance(ts, (int, float)) else str(ts)[:10]
except Exception:
    trade_date = str(ts)[:10]
```
Then filter `trade_date == today_str`.

alerts.py:443 — replace `bs = _brier_score()` with `bs = _brier_score(min_days_out=1)` to make the same-day filter explicit and resilient to future default changes.

alerts.py:456 — replace `except Exception: pass` with `except Exception as _bs_exc: _log.warning("black_swan: Brier check skipped — %s", _bs_exc)`

VERDICT: fix before live — the daily loss check is a dead letter on integer timestamps.

---

### [alerts.py] activate_black_swan_halt() L:461–514  ★ T1
Score: 8/10  |  Confidence: Confirmed
AC: ALL PASS — halt (kill switch creation) is attempted unconditionally; notification block is inside its own try/except and cannot prevent the halt from executing.
Red flag: NONE
Invariants: N/A (no balance, no SQL, no Kelly)

STRENGTHS:
• Kill switch creation at lines 477–496 is fully decoupled from notification at lines 498–514 — AC2 satisfied.
• Post-creation existence check (line 480) is an excellent operational safety net — logs CRITICAL if the file was not actually created.
• Failure to write the reason file (lines 472–474) logs ERROR but does not abort the kill-switch attempt — correct priority ordering.
• Individual notification channel failures are swallowed silently and do not propagate — notification channel is best-effort.
• `_log.critical(...)` used for both success and failure paths — operator will see the halt in logs even if notifications are down.

WEAKNESSES:
• lines 471–474: `_BLACK_SWAN_PATH` write uses a plain `open()` rather than the safe atomic write pattern used elsewhere in the codebase (`safe_io.atomic_write_json`). A crash mid-write produces a corrupt reason file. Low severity (it is informational only — the kill switch file is the actual gate), but inconsistent.
• lines 504–512: notification exception handlers `except Exception: pass` — silent swallow is intentional here (best-effort) but the outer `except Exception as _n_exc` at line 513 does log at WARNING, providing a fallback if the whole notification block fails. Acceptable.

VERDICT: keep as-is — minor consistency gap with atomic write; AC2 fully satisfied; test coverage confirmed.

---

### [alerts.py] run_black_swan_check() L:539–595  ★ T1
Score: 7/10  |  Confidence: Confirmed
AC: ALL PASS
Red flag: NONE
Invariants: N/A

STRENGTHS:
• Graceful defaults: loads trades and balance from paper state when not passed by caller.
• Prefers real Kalshi API balance over paper state when client is provided — comment explains the divergence risk (fees, fills).
• Exception from `get_state_snapshot()` is caught and falls back to caller-supplied values — non-fatal.
• Exception in the whole function activates the halt anyway (lines 589–595) — fail-safe posture.
• Kalshi balance failure falls back to paper state with DEBUG log — correct.

WEAKNESSES:
• lines 562–564: `except Exception: pass` inside the `get_state_snapshot()` call — no log. If paper state is corrupt, the function continues with `balance=None` / `peak_balance=None`, and `check_black_swan_conditions` will silently skip the daily loss check. Should log at WARNING.
• Test at `test_p9_p10.py:391` passes `trades` with `{"outcome": "no"}` dicts that lack a `days_out` field — the multi-day filter in `check_black_swan_conditions` uses `t.get("days_out", 1) >= 1` so these 12 no-outcome trades are treated as multi-day losses and trigger the halt. Test verifies halt fires, but does not verify the Brier skip path or the balance fetch path.
• No test for the case where `client.get_balance()` fails and falls back to paper balance for daily loss check.

FAILURE SCENARIO:
`get_state_snapshot()` raises (e.g., file lock contention). Exception is silently swallowed. `balance` and `peak_balance` remain `None`. `check_black_swan_conditions` skips the daily loss check entirely (which is already broken for int timestamps anyway — see check_black_swan_conditions notes). An extreme daily loss goes undetected.

VERDICT: fix before live — `except Exception: pass` at line 562 should log at WARNING; daily loss check dead letter confirmed by timestamp bug in called function.

---

### [alerts.py] check_anomalies() L:225–288  ★ T1
Score: 8/10  |  Confidence: Confirmed
AC: ALL PASS — AC3: check_anomalies itself is side-agnostic; multi-day filter is applied by run_anomaly_check before calling this function. Direct callers in tests pass pre-filtered lists. The function uses _trade_won() for side-aware win/loss determination.
Red flag: NONE
Invariants: N/A (pure computation on passed-in list)

STRENGTHS:
• Uses `_trade_won()` for side-aware win/loss counting — no outcome/side confusion.
• Edge decay check handles both `edge` and `net_edge` field names with legacy fallback — defensively handles older trade records.
• Consecutive loss detection correctly breaks on first win — proper streak detection.
• Consistent threshold: requires >= 5 settled trades before computing win rate — avoids false positives on small samples.
• Strong test coverage in `test_alerts_side.py` — both sides, mixed trades, consecutive patterns, all tested.

WEAKNESSES:
• line 285: consecutive loss threshold is hardcoded `>= 5` — soft warning threshold. The halt threshold is separate (6+, in `_is_halt_level`). This is fine architecturally, but there is no comment clarifying the two thresholds are intentionally different, which could confuse a future editor.
• The "trade frequency spike > 5 in last hour" check listed in the docstring (item 3) is NOT implemented — the actual item 3 in code is "consecutive losses". This docstring vs code mismatch is a clarity issue but not a functional bug.
• check_anomalies called directly by tests with no days_out field in trades — this is correct (function is days_out-agnostic, filtering is caller's responsibility). But a caller who forgets the filter in run_anomaly_check would pass same-day trades. Low risk since run_anomaly_check currently filters correctly.

VERDICT: keep as-is — well-covered, correct logic; fix docstring mismatch (item 3 description).

---

### [alerts.py] run_anomaly_check() L:330–360  ★ T1
Score: 8/10  |  Confidence: Confirmed
AC: ALL PASS — AC3: filter at lines 341–346 explicitly restricts to `days_out >= 1 or days_out is None`. Same-day METAR trades excluded.
Red flag: NONE
Invariants: N/A

STRENGTHS:
• Multi-day filter comment is explicit: "same-day METAR losses must not trigger WIN_RATE_COLLAPSE or CONSECUTIVE_LOSSES halts when the multi-day model is healthy."
• Filter logic `t.get("days_out") is None or t.get("days_out", 1) >= 1` correctly treats NULL days_out as multi-day (consistent with I1 pattern).
• Error path returns `(["anomaly check error: ..."], True)` — fail-safe: exception causes halt not silence.
• Error logged at ERROR level — operator will see it.
• `_is_halt_level` called twice (once for should_halt, once for log level) — minor inefficiency but not a bug.

WEAKNESSES:
• If `load_paper_trades()` succeeds but returns an empty list (no trades yet), `check_anomalies([])` returns [] and `should_halt=False`. Correct — but worth noting no alerting is possible until trades accumulate.
• No test for the exception path `except Exception as exc` in run_anomaly_check itself — but this is a difficult test to write (would need paper.py to throw).

VERDICT: keep as-is — filter is correct, fail-safe error path, good logging.

---

### [alerts.py] _is_halt_level() L:299–327  ★ T1
Score: 7/10  |  Confidence: Confirmed
AC: N/A (not directly an AC function, but gating halt decisions)
Red flag: NONE
Invariants: N/A

STRENGTHS:
• Conservative: `return True` (halt) when message cannot be parsed — correct fail-safe for edge cases.
• Handles both "WIN_RATE_COLLAPSE" and "WIN RATE COLLAPSE" variants.
• Strong test coverage in `test_phase2_batch_l.py` — all three branches tested with boundary values.
• Threshold constants are in `ALERT_HALT_THRESHOLDS` dict — not duplicated in the parser.

WEAKNESSES:
• line 302: `msg = alert_msg.upper()` — the EDGE DECAY regex `r"AVERAGE EDGE ([-\d.]+)%"` is applied to the uppercased message. A negative edge like "-5.2%" becomes "-5.2%" uppercase, which the regex handles. But if the message format ever changes (e.g., adds a space), the fallback `return True` fires — which is the safe default. Acceptable.
• `import re as _re` is executed inside each branch on every call — minor inefficiency; module-level import would be cleaner.
• EDGE_DECAY halt threshold is -0.10 (negative 10%). The regex extracts the float from the percentage string. A message "EDGE DECAY: average edge -5.2%" gives rate = -0.052, which is > -0.10, so returns False (no halt). Correct — but sign convention is not commented. A future editor could easily invert this.
• No test for the "can't parse" fallback path (`return True` when regex fails to match).

FAILURE SCENARIO (score ≤7 required):
Message format changes slightly — e.g., "EDGE DECAY: avg edge -15.0% over 8 trades" (uses "avg" not "average"). Regex `AVERAGE EDGE` fails to match. Fallback `return True` fires and triggers a halt even though the message might not warrant one. Low severity (fail-safe direction), but could cause spurious halts during monitoring.

VERDICT: fix before live — add `import re` at module level; add comment on EDGE_DECAY sign convention; add test for unparseable message fallback.

---

## TIER 2 Functions

---

[alerts.py] _load() L:23–30  6/10 — Silent exception swallow: corrupt `alerts.json` returns empty state with no log; operator cannot detect file corruption without grepping.  [Confidence: Confirmed]
FIX: alerts.py:28 — replace `except Exception: pass` with `except Exception as exc: _log.warning("alerts: failed to load %s, starting fresh: %s", _DATA_PATH, exc)`

[alerts.py] _save() L:32–45  9/10 — Atomic write using `os.replace()` with temp file and cleanup on exception; correct pattern.  [Confidence: Confirmed]

[alerts.py] add_alert() L:47–83  7/10 — Input validation present; atomic save; no lock (acceptable — file-level atomicity from `_save`). Correct.  [Confidence: Confirmed]

[alerts.py] remove_alert() L:86–94  7/10 — Simple, correct; only saves if something was removed.  [Confidence: Confirmed]

[alerts.py] get_alerts() L:97–130  7/10 — Cooldown re-arm logic is correct; mutates in-place and saves on change; ISO parsing handles Z suffix. Minor: exception in `datetime.fromisoformat` silently drops re-arm without log.  [Confidence: Confirmed]

[alerts.py] check_alerts() L:133–181  5/10 — RF1: `except Exception: continue` at line 178 swallows all API errors (network failure, auth error, bad response) with no log at WARNING or above. Also no test coverage exists.  [Confidence: Confirmed]
FIX: alerts.py:178 — replace `except Exception: continue` with `except Exception as exc: _log.warning("check_alerts: failed to fetch %s: %s", ticker, exc); continue`

[alerts.py] mark_triggered() L:184–192  7/10 — Correct; records triggered_at for cooldown; no lock needed (file-level atomicity from _save).  [Confidence: Confirmed]

[alerts.py] save_alerts() L:195–213  8/10 — Preserves `next_id`; handles missing file; uses `safe_io.atomic_write_json`. Correct and resilient.  [Confidence: Confirmed]

[alerts.py] _trade_won() L:216–222  9/10 — Minimal, correct, fully tested in test_alerts_side.py. Side-aware win/loss determination. No edge cases missed.  [Confidence: Confirmed]

[alerts.py] get_black_swan_status() L:517–527  8/10 — Correct; returns None when absent; fallback dict on corrupt file. Silent on corrupt file read error — acceptable for a status display function.  [Confidence: Confirmed]

[alerts.py] clear_black_swan_state() L:530–536  8/10 — Simple, correct; logs INFO on clear; returns bool; no side effects.  [Confidence: Confirmed]

---

## Red Flag Promotions

**check_alerts() — RF1 promotion to full block:**

[alerts.py] check_alerts() L:133–181  ★ RF1 PROMOTION
Score: 5/10  |  Confidence: Confirmed
AC: N/A (not a TIER 1 function in module definition, but RF1 requires full block)
Red flag: RF1 — `except Exception: continue` at line 178 — all API errors (network, auth, bad format) silently swallowed with no log.
Invariants: N/A

STRENGTHS:
• Groups by ticker to avoid duplicate API calls — efficient.
• Cent-to-dollar conversion with explicit `> 1` guard — handles both cent and dollar representations.
• Falls back to `last_price` when bid/ask are zero.

WEAKNESSES:
• line 178: `except Exception: continue` — a transient network error, a bad API response, or an auth failure causes all alerts for that ticker to be silently skipped. The caller receives an empty triggered list with no indication that checking was suppressed.
• Zero test coverage — `check_alerts` does not appear in any test file.

FAILURE SCENARIO:
Kalshi API returns a 401 auth error during alert checking. `except Exception: continue` fires. All price alerts are silently skipped. The operator's price alert fires in reality but is never reported. The monitoring layer is effectively disabled with no indication.

FIX: alerts.py:178 — replace `except Exception: continue` with:
`except Exception as exc: _log.warning("check_alerts: failed to fetch ticker %s: %s", ticker, exc); continue`

VERDICT: fix before live — silent exception swallow disables monitoring without operator knowledge.

---

## Summary Table

| Function | Tier | Score | Verdict |
|---|---|---|---|
| check_black_swan_conditions | T1 | 7/10 | fix before live |
| activate_black_swan_halt | T1 | 8/10 | keep as-is |
| run_black_swan_check | T1 | 7/10 | fix before live |
| check_anomalies | T1 | 8/10 | keep as-is |
| run_anomaly_check | T1 | 8/10 | keep as-is |
| _is_halt_level | T1 | 7/10 | fix before live |
| check_alerts (RF1) | T2→RF1 | 5/10 | fix before live |
| _load | T2 | 6/10 | fix |
| _save | T2 | 9/10 | keep as-is |
| add_alert | T2 | 7/10 | keep as-is |
| remove_alert | T2 | 7/10 | keep as-is |
| get_alerts | T2 | 7/10 | keep as-is |
| mark_triggered | T2 | 7/10 | keep as-is |
| save_alerts | T2 | 8/10 | keep as-is |
| _trade_won | T2 | 9/10 | keep as-is |
| get_black_swan_status | T2 | 8/10 | keep as-is |
| clear_black_swan_state | T2 | 8/10 | keep as-is |

**File median: 7.5/10. Three functions require fixes before live; one requires rework (check_alerts RF1).**

---

## Critical Finding Summary

**Finding 1 — CONFIRMED — Daily loss check is a dead letter (check_black_swan_conditions L:413–419)**
`placed_at` is a UNIX integer timestamp. `str(1719619200).startswith("2026-06-29")` is always False. `today_trades` is always empty. The daily loss BLACK SWAN condition (check 2) has never fired and will not fire. The threshold `BLACK_SWAN_DAILY_LOSS_PCT` is effectively disabled.

**Finding 2 — CONFIRMED — RF1 in check_alerts (L:178)**
`except Exception: continue` with no log. Entire ticker alert check silently suppressed on any API error.

**Finding 3 — LIKELY — Implicit brier_score default (check_black_swan_conditions L:443)**
`_brier_score()` called without `min_days_out=1` argument. Currently safe because the default is 1. Fragile against future signature changes.
