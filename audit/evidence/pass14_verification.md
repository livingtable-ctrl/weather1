# Pass 14 (Performance) — Verification Notes

Independent re-verification of the 3 raw findings from Pass 14. All three CONFIRMED.

## Finding 1: _log_shadow_predictions N+1 per shadow ticker

- Confirmed function body order_executor.py:2213-2291 (`def _log_shadow_predictions` at
  L2213, docstring claims "batched onto a single connection").
- Confirmed 7 total call sites via grep: L2326 (`_log_shadow_predictions(opps, live=live)`
  — the one genuinely-batched call, used only for the whole-batch-guard early-return paths
  inside `_shadow_suffix()`), and 6 per-ticker call sites at L2617/2627/2637/2644/2654/2661,
  each inside `for item in opps:` (L2579) passing `[item]` — confirmed each is followed by
  `continue`, i.e. genuinely one call per shadow-routed ticker, not batched, contradicting
  the function's own docstring for this call pattern.
- Confirmed `paper._load()` (paper.py:396) does unconditional `open()+json.load()` +
  `_validate_crc`/`_validate_checksum` (SHA-256) on every call, no caching.
- Confirmed `tracker._conn()` (tracker.py:413) does `sqlite3.connect()` + 3 PRAGMA
  statements on every call, no pooling/caching.
- Ran audit/reproductions/shadow_n_plus_1_bench.py myself (read-only against real main-clone
  data/paper_trades.json [234,053 bytes] and data/predictions.db [47,280,128 bytes]):
  - get_open_trades()-equivalent: mean 2.510ms/call (n=30, min 2.172, max 3.998)
  - tracker._conn()-equivalent: mean 0.897ms/call (n=30, min 0.781, max 1.573)
  - Combined ~3.3ms/call, in the same order of magnitude as the original finding's
    measured 3.20ms/1.78ms (my numbers came out a bit lower, plausibly due to OS file-cache
    state, but the conclusion — real, non-trivial, avoidable per-call I/O cost — holds).
- Status: CONFIRMED. E3 (reproduced this session against real data).

## Finding 2: web_app.py double-load in /api/trades + no caching across routes

- Confirmed web_app.py api_trades() (L1398) calls `get_open_trades()` at L1405 and
  `get_all_trades()` at L1475 — both route through paper._load() independently, no shared
  read.
- Confirmed both `paper.get_open_trades()` (paper.py:1299) and `paper.get_all_trades()`
  (paper.py:1922) call `_load()` unconditionally, no caching/memoization.
- Confirmed additional call sites via grep: L126 (`_build_stream_data`, used by the
  `/api/stream` SSE loop's `generate()` at L364-366, sleeping 10s per iteration), L1181
  (`api_live_signals`), L1302 (`history_page`), L1497, L1655, L1671, L3039 — 9 total call
  sites across distinct routes/functions, consistent with "at least 7 distinct call sites
  ... plus the SSE loop".
- Confirmed `paper._DATA_LOCK` (paper.py:227) is `_CrossProcessDataLock(...)`
  (class defined paper.py:128) — a real cross-process file lock, not a plain in-process
  `threading.Lock`, supporting the contention claim against cron.py's concurrent writes.
- Confirmed via `git blame -L 1475,1475 web_app.py` → commit b26000fa1, 2026-04-10,
  predating the audited 2026-08-02..08-17 commit window, and confirmed commit 709b0043's
  actual diff (`git show --stat`) is scoped to adding the new batch live-quote fetch, not
  touching the pre-existing `get_all_trades()` line — matches the finding's claim that
  709b0043 added a call but didn't introduce/worsen this pre-existing double-load.
- Status: CONFIRMED. E3 (direct code read + git blame this session; did not re-run the
  original benchmark for this finding specifically since it reuses Finding 1's _load()
  timing, which I independently reproduced above).

## Finding 3: Flask dev server does not block behind open SSE stream (OBSERVATION, not a bug)

- Confirmed web_app.py:3323 `_app.run(host="127.0.0.1", port=port, debug=False,
  use_reloader=False)` — no explicit `threaded=`.
- Confirmed installed Flask version 3.1.3, Werkzeug 3.1.8.
- Confirmed via `inspect.getsource(Flask.run)` that Flask.run() contains
  `options.setdefault("threaded", True)` before delegating to `werkzeug.serving.run_simple`,
  i.e. Flask overrides Werkzeug's own `threaded=False` default — matches the finding's root
  cause explanation.
- Confirmed web_app.py:960 comment ("Flask serves requests threaded (threaded=True
  default)") is accurate for this reason.
- Re-ran audit/reproductions/sse_blocking_repro2.py myself this session (had to set
  `DASHBOARD_UNPROTECTED=true` env var — not set by the repro script itself — because this
  worktree's `_build_app(None)` now raises `RuntimeError: DASHBOARD_PASSWORD must be set`
  when no password/env override is present; this is an environment difference from when the
  finding was originally produced, not a flaw in the finding itself). With that flag set,
  reproduced the same result: 8x /api/status requests fired at 1s intervals while a
  persistent /api/stream SSE connection stayed open, all completed in 45.8-227.2ms (mean
  78.1ms), no blocking observed — consistent with the original finding's 57-270ms/mean 90ms.
- Status: CONFIRMED (as an accurate non-bug observation). E3 (reproduced this session).
  Minor note added to verification_notes: repro script has an undocumented environment
  dependency (DASHBOARD_UNPROTECTED=true) not mentioned in its own docstring/limitations —
  worth the author adding for future re-runs, but doesn't affect the finding's validity.
