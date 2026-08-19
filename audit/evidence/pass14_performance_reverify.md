# Pass 14 — Performance: Independent Re-Verification

Skeptical re-check of 3 raw findings from Section 26 (Pass 14 — Performance).
All three examined by reading current source directly (not trusting the
finding's own description) and, where an original finding cited a runnable
repro, re-running it myself in this session.

## Finding 1 — `_log_shadow_predictions()` N+1 per-shadow-ticker I/O

Verified by direct read:
- order_executor.py L2214-2291: `_log_shadow_predictions()` docstring claims
  "batched onto a single connection... rather than one connection open/close
  per opp" — confirmed the function body opens exactly one `tracker._conn()`
  per call (L2252) and one `get_open_trades()` per call (L2246).
- Confirmed via grep: exactly 6 call sites in `_auto_place_trades()`
  (order_executor.py L2617,2627,2637,2644,2654,2661), each inside the
  per-ticker shadow-routing loop (L2579 `for item in opps:`), each passing
  `[item]` — a single-item list. This contradicts the docstring's batching
  claim: no call site ever passes more than one item, so the "batched
  connection" design is dead code in practice.
- Confirmed `paper._load()` (paper.py L396-405) does unconditional
  `open()+json.load()+_validate_checksum` (sha256, paper.py L86-89) on every
  call — no memoization.
- Confirmed `tracker._conn()` (tracker.py L413-419) does a fresh
  `sqlite3.connect()` + 3 `PRAGMA` statements on every call — no pooling.
- Re-ran `audit/reproductions/shadow_n_plus_1_bench.py` myself (read-only,
  against the real main-clone data files, 234KB paper_trades.json / 47MB
  predictions.db): mean 2.58ms/call for the paper-load-equivalent (n=30,
  min 2.20/max 4.26ms) and mean 1.23ms/call for the tracker-conn-equivalent
  (n=30, min 0.78/max 8.92ms) — combined ~3.9ms/shadow-ticker, i.e. same
  order of magnitude as the original run's 3.20ms/1.78ms (expected run-to-run
  variance, not a discrepancy in the underlying mechanism).

**Verdict: CONFIRMED.** Root cause, call-site count, and non-cached I/O cost
all independently verified against current code and a self-run benchmark.

## Finding 2 — `/api/trades` double-loads the paper ledger; no cross-route caching

Verified by direct read:
- web_app.py L1405 `open_trades = get_open_trades()` and L1475
  `all_trades = get_all_trades()` both present in `api_trades()`, confirmed
  both route to `paper._load()` independently (`get_open_trades`,
  paper.py L1299-1301; `get_all_trades`, paper.py L1922-1923) — no shared
  read, no caching between them.
- grep confirms 9 distinct `get_open_trades()`/`get_all_trades()` call sites
  in web_app.py (L126, 1181, 1302, 1405, 1475, 1497, 1655, 1671, 3039) — even
  more than the finding's conservative "at least 7," so the claim is not
  overstated.
- `git blame -L 1475,1475 web_app.py` → commit b26000fa1, 2026-04-10 —
  matches the finding's claim that this predates the audited commit window
  and was not introduced/worsened by 709b0043.
- Confirmed `_DATA_LOCK` (paper.py L227) is `_CrossProcessDataLock`, not an
  in-process lock — supports the cross-process-contention claim.
- Confirmed `/api/stream` SSE loop (web_app.py L358-384) re-fires
  `_build_stream_data()` every 10s via `time.sleep(10)` inside an infinite
  generator loop.
- Confirmed frontend `useData.js` `ENDPOINTS` array (L297-315) lists exactly
  17 endpoints (indices 0-16, including `/api/trades`), fetched together via
  `Promise.allSettled` (L344) on a 60s `setInterval` (L540) — matches the
  finding's claim precisely.

**Verdict: CONFIRMED.** Every specific sub-claim (line numbers, call-site
count, blame date, lock type, poll cadence, endpoint count) checked out
against current code.

## Finding 3 — SSE stream does NOT block the dev server (non-bug observation)

Verified by direct read:
- web_app.py L3323 `_app.run(host="127.0.0.1", port=port, debug=False,
  use_reloader=False)` confirmed — no explicit `threaded=`.
- web_app.py L960 comment "Flask serves requests threaded (threaded=True
  default)" confirmed present verbatim.
- Read `inspect.getsource(Flask.run)` directly (installed flask 3.1.3,
  werkzeug 3.1.8 — same as environment the original finding used) and
  confirmed the body contains `options.setdefault("threaded", True)`
  immediately before delegating to `werkzeug.serving.run_simple` — this is
  the mechanism claim, verified directly at the source level, not just by
  re-running the black-box repro.
- Re-ran `audit/reproductions/sse_blocking_repro2.py` myself. Note: the
  script as written no longer works standalone — it sets
  `utils.DASHBOARD_PASSWORD = ""` but `web_app._build_app()`'s current auth
  gate (web_app.py L152-163) reads `os.getenv("DASHBOARD_PASSWORD")`
  directly, not the `utils` module attribute, so the script now raises
  `RuntimeError: DASHBOARD_PASSWORD must be set` unless
  `DASHBOARD_UNPROTECTED=true` is also set in the environment. This is a
  minor staleness bug in the *repro script itself* (or a real auth-check
  change since the script was authored), not a flaw in the underlying
  finding. Re-ran with `DASHBOARD_UNPROTECTED=true`: SSE connection
  established, then 8x `/api/status` probes at 1s intervals returned in
  44.1-282.0ms (mean 79.9ms) — no blocking observed, consistent with the
  original run's 57-270ms/mean 90ms. Script's own verdict line printed
  "NOT CONFIRMED: ... server appears to service requests concurrently" —
  i.e. the *blocking hypothesis* is not confirmed, which is exactly the
  conclusion the finding itself reports (the finding is about ruling out a
  false lead, not reporting a live bug).

**Verdict: CONFIRMED** (as an accurate non-bug observation; INFO severity
correctly assigned, no action item generated). Flagging the repro-script
staleness (needs `DASHBOARD_UNPROTECTED=true`) as a minor note for any later
pass that tries to re-run it.

## Summary

All 3 original findings survive independent re-verification with no
downgrades. All specific factual sub-claims (line numbers, call counts,
git blame dates, library version behavior, measured timings) were checked
against current code/environment and held up. One minor staleness issue
was found in finding 3's own reproduction script (needs an added env var
to run today) — noted for future passes, does not affect the finding's
validity.
