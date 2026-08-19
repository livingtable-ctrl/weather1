# Pass 12 — Concurrency — Evidence Notes

Scope: race conditions, duplicate execution, stale reads, lost updates,
ordering assumptions, shared mutable state, deadlocks, cancellation/timeout
handling, task leakage, retry races, duplicate scheduled jobs, concurrent
order decisions. Focus commits: cron.py scheduling, settlement_monitor daily
run, shadow-gate batch-hoisting, headless engine extraction (trade_cycle.py).

## Finding 1 — cron._acquire_cron_lock() TOCTOU race (reproduced)

`cron.py:220-286`. The lock is `if lp.exists(): ... else: lp.write_text(...)`
with no OS-level exclusive-create/lock primitive. Two callers that both see
"lock absent" can both proceed to write and both get `True`.

This lock is the ONLY thing serializing `cmd_cron` (cron.py:2409) against
`cmd_watch --auto`'s own trade cycle (main.py:3622), against `web_app.py`'s
`/api/run_cron` spawn path (gated by `_is_cron_running()`, itself built on
the same read logic — web_app.py:958-966), and against
`emos-train`/`emos-deactivate`'s "cron in flight" pre-check (main.py:6682,
6820).

### Reproduction

`audit/reproductions/cron_lock_race_repro.py` — redirects `cron.LOCK_PATH` to
a temp file, monkeypatches `pathlib.Path.exists` to rendezvous two threads at
a `threading.Barrier` the instant both have evaluated the `if lp.exists():`
check, then lets both continue into `cron._acquire_cron_lock()`'s write path.

Run:
```
python audit/reproductions/cron_lock_race_repro.py
```
Actual output this session:
```
results: [True, True]
lock file final contents: {"pid": 17716, "started_at": ..., "heartbeat": ...}
RACE CONFIRMED: both threads acquired the lock (both returned True).
```
Both callers returned `True` — the mutual-exclusion guarantee the rest of the
codebase relies on (comments at cron.py:960-963, order_executor.py
:1287-1298, main.py:6685-6688) does not actually hold under concurrent
acquisition attempts.

Confirmed downstream consequence path: `cmd_cron` (cron.py:912-919) calls
`_check_live_position_exits`/`_check_live_model_exits` on any live position
left open by a prior `watch --auto --live` session — i.e. cron.py DOES touch
live positions (exits only, never live entries — verified against
LIVE_TRADING_RUNBOOK.md:131's "cron never places live orders" claim, which is
accurate only for entries). Two racing holders of the "exclusive" lock could
both attempt a protective exit on the same live position concurrently, each
submitting its own real IOC sell order to Kalshi — `execution_log
.record_live_exit_fill`'s settled_at/expected_quantity compare-and-set
(execution_log.py:648-681, 734+) correctly prevents *double-counting the P&L
row*, but does not and cannot prevent the *second real order submission*
itself, since that gate only runs after both orders have already been placed.

Also amplifies: `execution_log.was_recently_ordered`/`was_traded_today`
(execution_log.py:278-297, 300+) are plain SELECT-then-later-INSERT checks
with no DB-level UNIQUE constraint — their only real protection against a
genuine double-place is that only one cron/watch process is ever supposed to
be mid-cycle at a time, which is exactly the invariant this lock is supposed
to (and does not) provide.

## Finding 2 — emos-train/emos-deactivate check cron-in-flight before, not after, the interactive confirmation

main.py:6682-6693 (activate) and main.py:6820-6830 (deactivate). Both check
`_cron_module._is_cron_running()` once, then print a prompt and block on
`input()` for an arbitrary human-paced amount of time, then on `'yes'`
proceed straight to `save_emos_params()`/`deactivate_emos()` with no re-check
immediately before the write. A cron cycle that starts during the
confirmation window is invisible to this gate, reopening precisely the
failure mode the check's own error message describes ("would split one scan
across two probability methods, some markets priced with the old method,
some with EMOS").

Not independently reproduced with a timed race (would require driving
`input()` from a second thread); flagged at E1 (static/code-reading
evidence) — the TOCTOU shape is unambiguous from the code structure: check →
unbounded-duration human interaction → write, no second check.

## Finding 3 — paper._CrossProcessDataLock fails OPEN after 10s of contention

paper.py:171-199. `_acquire_file_lock()` retries `msvcrt.locking` for up to
10s, then on continued contention logs a warning and returns *without*
`self._fh` set — `_release_file_lock` then no-ops, and the caller's
read-modify-write on `paper_trades.json` proceeds with **no cross-process
lock held at all**, silently reverting to the pre-fix in-process-only
`threading.RLock` protection the class's own docstring says was
insufficient (paper.py:132-136: "a load in one could straddle a save in the
other and silently revert a settlement or drop a manually-placed trade").
This is a deliberate liveness-over-safety tradeoff (comment: "Never let the
locking mechanism itself take down trading"), but it means the exact
class of bug this lock exists to close can still occur under sustained
contention (e.g. web dashboard polling + cron + watch all touching the
ledger around the same moment).

## Finding 4 — prewarm ThreadPoolExecutor task leakage on timeout

trade_cycle.py:1153-1172. `_run_batch_prewarm_for_pairs` submits up to 8
per-city-date prewarm tasks, waits on `as_completed(..., timeout=200)`, and
on `TimeoutError` logs a warning and falls through; `finally: warm_pool
.shutdown(wait=False)` does not cancel in-flight tasks — already-submitted
`_warm_one_tracked` calls keep running on background threads while
`run_trade_cycle` proceeds into the next (analysis) phase. Internal state
these threads touch (ForecastCache, circuit breakers) is properly locked, so
this is not a correctness bug in that data, but it is genuine unbounded
task/phase overlap: the "prewarm phase" is not actually over when the code
that follows it assumes it is, and CPython's `concurrent.futures` atexit
hook (`_python_exit`) will still block interpreter shutdown on these threads
regardless of `wait=False`, so a `cron`-one-shot invocation may hang at exit
past its own `_install_cron_watchdog` timeout, whose `os._exit(1)` hard-kill
is explicitly "no cleanup" — see cron.py:2375-2377.

## Finding 5 (LOW/INFO) — settlement_monitor.py has no application-level overlap guard

settlement_monitor.py + main.py:9142-9179. The daily Task Scheduler entry
(`schtasks /Create /SC DAILY ...`) has no analogue of cron.py's LOCK_PATH;
protection against two overlapping runs relies entirely on Windows Task
Scheduler's default "don't start a new instance" policy, which is not
explicitly set by the `schtasks /Create` call shown and could be silently
changed by an operator editing the task's Settings tab. If two instances did
overlap, `write_settlement_signals()` (settlement_monitor.py:126-133)
overwrites the *entire* signals file with the calling process's own
in-memory `all_signals` list every poll — last-writer-wins for the whole
batch, so a losing process's newly-detected settlement-lag signal(s) are
silently dropped, not merged.

## Finding 6 (INFO) — ForecastCache disk snapshot is last-writer-wins across processes

forecast_cache.py's `ForecastCache`/`PersistentForecastCache` store is
strictly in-process (`self._store: dict`), so separate cron/watch/web_app
processes each hold an independent copy; `dump_to_disk`/`load_from_disk`
(e.g. nws.py's station-ID cache) round-trip through a single shared JSON
file with no cross-process merge — the last process to `dump_to_disk()` wins
and silently discards any newly-learned entries the losing process added.
Low impact: the caches this applies to are documented as permanent/idempotent
facts (station lookups) that get re-derived next time they're needed, not
lost trading state.

## Areas checked and found adequately hardened (not reported as findings)

- `execution_log.record_live_exit_fill`/`record_live_early_exit`/
  `record_live_partial_exit`: real SQL-level compare-and-set (`WHERE ... AND
  settled_at IS NULL [AND COALESCE(fill_quantity, quantity) = ?]`), correctly
  atomic, with callers (`order_executor._exit_live_position`) that catch and
  handle the race-loss `RuntimeError` rather than letting it crash the
  watch/cron loop.
- `circuit_breaker.py`: per-instance `threading.Lock` for state transitions
  and a separate module-level `_CB_STATE_FILE_LOCK` for the shared JSON file
  — correctly prevents the half-open/probe race and file corruption under
  the prewarm ThreadPoolExecutor's parallel fetches.
- `weather_markets._load_metar_calibration`/`_load_platt_models`: mtime-gated
  re-read with carefully distinguished transient-vs-permanent failure
  handling — a long-running watch/loop process picks up a fresh calibration
  file without restart and without misreading a torn/in-progress write.
- `positions.py`: pure functions over caller-supplied lists, no shared
  mutable module state — no race surface.
- `execution_log.init_log()` / `_initialized`: proper double-checked locking
  via `_init_lock`.
- `_check_live_position_exits` → `_check_live_model_exits` ordering within a
  single cycle: sequential, and the latter re-reads open positions fresh, so
  no double-exit-attempt within one process/cycle.
- `_recover_pending_orders`: idempotent (polls Kalshi's own order status and
  writes what it observes); safe to run redundantly.

No files were modified outside `audit/`. Reproduction script is read-only
against the real repo (redirects LOCK_PATH to a tempdir); no repo data was
touched.
