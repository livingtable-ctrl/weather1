# Pass 14 — Performance — Evidence Notes

Scope: repeated computation, N+1, excessive API calls/logging, memory growth,
resource leaks, blocking ops, unbounded queues, poor caching, excessive
retries, slow startup, unnecessary network traffic — focused on the recent
commit window (2026-08-02..08-17), with emphasis on cluster A (headless
engine), the 709b0043 batch-fetch-quotes change, 25aef473 shadow-gate
batch-hoisting, ae321905 ForecastCache migration.

## Finding 1 (MEDIUM): _log_shadow_predictions N+1 per shadow ticker per cron cycle

order_executor.py `_auto_place_trades()` correctly hoists the 6 shadow-gate
booleans ONCE per batch (L2572-2577, commit 25aef473's whole point). But the
shadow-logging call itself, `_log_shadow_predictions([item], live=live)`, is
still invoked once PER shadow-routed ticker inside the loop (call sites at
L2617, 2627, 2637, 2644, 2654, 2661 -- all pass a single-item list).

`_log_shadow_predictions` (L2214-2291) does, on every call:
  - `paper.get_open_trades()` -> `paper._load()` (paper.py L396-405): full
    `open()`+`json.load()` of data/paper_trades.json, THEN
    `_validate_checksum()` (SHA-256 over the trades body) -- no caching, no
    memoization, unconditional every call.
  - `with tracker._conn() as _con:` (tracker.py L413-419): a brand-new
    `sqlite3.connect(DB_PATH)` + 3 PRAGMA statements (journal_mode=WAL,
    synchronous=NORMAL, cache_size=10000) against predictions.db, opened and
    closed fresh every call.

The function's own docstring claims batching ("Writes are batched onto a
single connection... rather than one connection open/close per opp") but
every real call site in the loop defeats that by passing `[item]` singular,
so the batching only ever spans one item -- no actual reduction versus the
naive per-ticker-open pattern the docstring says it avoids.

Contrast: the main placement path in the SAME function fetches
`_open_trades_list = get_open_trades()` exactly ONCE at L2364, before the
per-ticker loop, and reuses/appends to that same in-memory list for the rest
of the function (including the `portfolio_var()` VaR gate, L2930) -- proving
the "fetch once, reuse" pattern is already established and deliberately used
elsewhere in this same function, just not applied to the shadow-logging path.

### Measured cost (E3 -- audit/reproductions/shadow_n_plus_1_bench.py)
Benchmarked directly against the real main-clone data files (read-only):
  - data/paper_trades.json: 234,053 bytes, 233 trades.
  - data/predictions.db: 47,280,128 bytes.
  - `_load()`-equivalent (read+parse+sha256): mean 3.20ms/call (n=30).
  - `_conn()`-equivalent (sqlite3.connect + 3 PRAGMAs): mean 1.78ms/call (n=30).
  - Combined ~10.5ms/shadow-ticker-call (includes measurement overhead of
    running both in the same iteration).
  - Projected added time per cron cycle: ~53ms @5 shadow tickers, ~158ms
    @15, ~317ms @30, ~528ms @50.

Limitation: the benchmark approximates `_validate_checksum`'s exact body
(sha256 over `json.dumps(sorted trades)`) rather than importing paper.py
directly (avoided to sidestep unrelated import-time/worktree-path
side effects) -- magnitude is representative, not an exact reproduction of
the real function's byte-for-byte checksum computation.

### Why this matters going forward
The shadow-only families this hits (hourly/rain/snow/hurricane-count/
hurricane-next-event/storm-order) each require an independent settled-sample
floor (>=20, per weather_markets.py's `_hourly_gates_active()` etc.) before
their placement gate activates -- so this N+1 pattern is not a one-time
startup cost, it recurs on every cron cycle for as long as any given family
stays below its floor (which, for low-frequency families like storm-order/
hurricane-count, could be effectively indefinite within a season). The
absolute cost today (tens to low hundreds of ms per cycle) is small against
this bot's multi-minute-to-hourly cron cadence, but it scales linearly with
both the ledger size (which only grows) and the number of shadow tickers in
a batch, and it's needless: the fix pattern (fetch `open_tickers` once,
reuse one `_con` across all items) already exists a few hundred lines away
in the same file.

## Finding 2 (LOW): /api/trades loads the paper ledger twice in one request; no cross-request caching across web_app.py routes

web_app.py `api_trades()` (L1398-1478) calls `get_open_trades()` at L1405
AND `get_all_trades()` at L1475 -- both route through `paper._load()`
independently (see Finding 1 for `_load()`'s real cost: full read+parse+
SHA-256 checksum, no memoization). That's two full ledger loads to serve
ONE HTTP request, when one `_load()` (or one `get_all_trades()` call,
filtering open trades from its own result instead of calling
`get_open_trades()` separately) would produce both `open_trades` and
`all_trades`/`closed` from a single read.

More broadly, `get_open_trades()`/`get_all_trades()` are called
independently, with zero request-scoped or short-TTL caching, from at least
7 distinct call sites across web_app.py: `_build_stream_data()` (L126, used
by the `/api/stream` SSE loop, which re-invokes this every 10s for as long
as any browser tab has the dashboard open), `/api/live_signals` (L1181),
`/api/trades` (L1405 + L1475, this finding), `/api/risk` (L1497),
`/api/status`-adjacent code (L1655/1671), and `/api/close-position`
(L3039). The frontend's `fetchAllSafe()` (useData.js L342) fires all 17
`ENDPOINTS` in parallel via `Promise.allSettled` every 60s (useData.js
L540), so several of these (`/api/trades`, `/api/risk`, `/api/live_signals`)
land in the same ~instant, each independently re-reading and re-checksumming
the same file, on top of the SSE loop's own independent 10s-interval reads.

`_DATA_LOCK` (paper.py L227) is a **cross-process** file lock
(`_CrossProcessDataLock`, Windows `msvcrt.locking` under the hood, matching
the pattern documented for `_replace_with_retry`), so this contention is not
purely an in-process/GIL matter -- a concurrent cron.py write cycle and a
web_app.py dashboard poll genuinely serialize against each other through
this lock, and every extra web_app-side read is extra time that lock is held
un-necessarily.

### Measured cost
Same benchmark as Finding 1: ~3.2ms per `_load()`-equivalent call today
(234KB/233-trade ledger). At today's scale this is a few milliseconds per
poll, not user-visible. It is architecturally the same "read on every call,
no caching" shape as Finding 1, and will scale the same way (linearly with
ledger size, which is monotonically growing) -- flagging now while the fix
is cheap (thread one `_load()`/one list through a request, or add a
short-TTL in-process cache for read-only dashboard routes) rather than after
it's a measurable page-load delay.

## Checked and found NOT to be a problem (recorded for later passes' benefit)

**web_app.py's dev server is NOT single-threaded despite Werkzeug's own
`run_simple(threaded=...)` defaulting to False.** `start_web()` calls
`_app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False)`
(web_app.py L3323) without an explicit `threaded=True`. Static reading of
`werkzeug.serving.run_simple`'s signature (installed version 3.1.8) shows
`threaded: bool = False` as its own default, which looked at first like it
would make the two `time.sleep(10)`-looping SSE endpoints (`/api/stream`,
`/api/stream/markets`) block all other dashboard requests for as long as
any browser tab stayed connected. Verified this empirically instead of
just reporting the static-analysis read (E3, audit/reproductions/
sse_blocking_repro2.py): built the real `web_app._build_app(None)` app,
ran it via the exact production `app.run(...)` call, opened a persistent
`/api/stream` connection, and fired 8x `/api/status` requests at 1s
intervals while it stayed open. All 8 requests completed in 57-270ms
(mean 90ms), no delay. Root cause of the false alarm: Flask's own
`Flask.run()` (flask/app.py, confirmed via `inspect.getsource`) does
`options.setdefault("threaded", True)` before calling Werkzeug's
`run_simple` -- i.e. Flask overrides Werkzeug's own default, and the
in-code comment at web_app.py L960 ("Flask serves requests threaded
(threaded=True default)") is correct. No finding here; recording so a
later pass doesn't re-spend time on the same dead end.

## Areas checked, no issues found

- `ForecastCache`/`PersistentForecastCache` (forecast_cache.py, migration
  commit ae321905): thread-safe, bounded (max_size=500, O(max_size) linear
  eviction scan only when full), TTL-correct. No issues.
- `d190d09d` (far-tail rain climatology blend): the new far-case cross
  product (`combined_totals = [m + t for m in member_totals for t in
  tail_sums_tilted]`) is bounded (~30 near members x <=~30 historical tail
  years => low hundreds to ~1000 terms), and the commit's own review
  explicitly replaced a per-member `random.choice()` resample with this
  deterministic cross product specifically to remove sampling noise --
  already analyzed for cost in the commit message itself. The underlying
  `_fetch_ensemble_precip_multiday` call is cached via `_ensemble_cache`
  (ForecastCache, ttl=8h), so this doesn't add a new network call per scan
  cycle. No issues.
- `c9b0fc02` (STRONG/MED tier mirrors validate()'s edge gates): pure
  arithmetic sign/magnitude comparisons, no new I/O or expensive calls
  added to the per-candidate hot path.
- `709b0043` (batch-fetch live quotes): confirmed genuinely ONE
  `client.get_markets(tickers=...)` REST call per `/api/trades` request
  (kalshi_client.py's `get_markets` pagination loop runs once per call
  given `limit=min(len(_tickers), 1000)` comfortably covers realistic
  open-position counts), reuses the route's closure-captured `client`
  instead of constructing a fresh one (avoids repeated private-key
  ACL/PEM re-validation) -- this is a real, already-landed performance fix,
  not a regression.
- `portfolio_var()`'s 5000-sim Monte Carlo call in `_auto_place_trades`
  (order_executor.py ~L2916-2930): pre-existing, not introduced by any
  commit in the audited window; already self-documented in-code
  ("Benchmarked cost: ~2.5s cumulative across a realistic 15-candidate
  cron cycle... negligible against this bot's multi-hour cron cadence, but
  real") -- not re-reported as a new finding.
- `safe_io._replace_with_retry`/`atomic_write_json_with_history`: retry/
  backoff costs (worst case ~3.5s) and `.history/` backup growth
  (max_history=10, pruned) are both already bounded and self-documented
  in-code; `atomic_write_json`'s `emergency_copy` only fires after all
  retries are exhausted (failure path only), not on every write.

## Reproductions written (audit/reproductions/, read-only, no writes to repo data)
- shadow_n_plus_1_bench.py -- timing benchmark for Finding 1/2's shared
  root cause (_load()-equivalent and _conn()-equivalent per-call cost).
- sse_blocking_repro.py / sse_blocking_repro2.py -- empirical check of
  web_app.py's dev-server threading model (see "Checked and found NOT to
  be a problem" above). repro2 is the clean version; repro.py's first run
  is left as-is (hit an auth-state artifact from environment reuse across
  Bash calls, resolved in repro2 by explicitly zeroing
  `utils.DASHBOARD_PASSWORD` before building the app).
