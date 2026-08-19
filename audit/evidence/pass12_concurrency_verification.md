# Pass 12 (Concurrency) — Independent Verification Notes

Re-verified all 7 raw findings against current source this session (did not trust the
original pass's own descriptions — read every cited file/line directly, and re-ran the
one existing reproduction script myself). Result: 7/7 CONFIRMED, 0 disproven, 0 downgraded.

1. **cron._acquire_cron_lock TOCTOU** — CONFIRMED, E2 (self-reproduced).
   Read cron.py:205-286 directly: `if lp.exists():` (line 222) followed, with no
   intervening OS-level exclusive-create/lock, by `lp.write_text(...)` (line 279).
   Ran `python audit/reproductions/cron_lock_race_repro.py` myself (not just trusted
   the prior claim) — output: `results: [True, True]`, `RACE CONFIRMED`. Verified all
   cited call sites exist as described: main.py:3622 (`cmd_watch` auto-trade →
   `ctx.acquire_cron_lock()`), web_app.py:958-966/1027-1042 (`_is_cron_running`),
   cron.py:912-919 (`_check_live_position_exits`/`_check_live_model_exits` called
   inside `cmd_cron` on any live position left open by a prior `watch --auto --live`
   session — confirms cron.py does place live protective EXIT orders, supporting the
   financial-risk claim). execution_log.record_live_exit_fill's `expected_quantity`
   compare-and-set (execution_log.py:649-681, def at 734) verified to exist and to
   guard only against double-counting P&L on the row, not against a second real order
   reaching Kalshi — matches the finding's own caveat.

2. **execution_log dedup SELECT-then-INSERT, no UNIQUE constraint** — CONFIRMED, E1.
   Read the `orders` table schema (execution_log.py:129-140): only an AUTOINCREMENT
   PK and three plain indexes, no UNIQUE/CHECK constraint. `was_recently_ordered`
   (278-297) and `was_traded_today` (300-325) are both plain `SELECT ... LIMIT 1`
   with no surrounding transaction linking the check to `log_order`'s later INSERT
   (157-233). Matches claim exactly.

3. **EMOS train/deactivate check-before-input()-before-write** — CONFIRMED, E1.
   Read main.py:6663-6753 (activation) and 6788-6849+ (deactivation) directly: both
   paths call `_cron_module._is_cron_running()` once, then block on `input()`, then
   write (`save_emos_params`/`reset_temperature_scale_for_emos` or `deactivate_emos`)
   with no repeated check after `input()` returns. Identical shape in both paths as
   claimed.

4. **paper._CrossProcessDataLock fails open after 10s** — CONFIRMED, E1.
   Read paper.py:171-199 directly: `_acquire_file_lock`'s retry loop has a 10.0s
   `deadline` (line 180); on continued `OSError` past the deadline it logs a warning,
   closes the file handle, and returns without ever setting `self._fh` (lines
   187-193) — so `_release_file_lock` becomes a no-op and the OS lock was never held
   for that call. Verified the `positions.update_peak_profits`/fc8e3555-era caller
   comment cited by the finding actually exists at paper.py:1396-1405 and matches the
   quoted risk ("could silently LOWER an already-higher peak ... or write a peak onto
   a trade the other process closed").

5. **Prewarm ThreadPoolExecutor not cancelled on timeout** — CONFIRMED, E1.
   Read trade_cycle.py:1136-1173 directly: `as_completed(warm_futures, timeout=200)`
   (line 1157), `except TimeoutError` only logs and falls through (1164-1170), and the
   `finally: warm_pool.shutdown(wait=False)` (1172) does not pass `cancel_futures=True`
   (default False in Python 3.9+) and cannot stop already-running worker threads
   regardless. Verified the cron.py:2375-2377 watchdog `os._exit(1)` hard-kill (no
   cleanup) also exists as cited.

6. **settlement_monitor.py no app-level lock** — CONFIRMED, E1.
   Grepped settlement_monitor.py for lock/PID logic — none found (only unrelated
   METAR "lock-in" domain terminology). `write_settlement_signals` (126-133) does a
   full `atomic_write_json({"signals": signals, ...}, _SIGNALS_PATH)` — a wholesale
   overwrite, not a merge, exactly as claimed. Verified main.py:9142-9179's
   `schtasks /Create /F /SC DAILY ...` registration has no explicit instance-policy
   flag (`/IT`, `/RI`-with-policy, etc.), so correctness depends on Task Scheduler's
   unstated/unverified default "do not start a new instance" behavior.

7. **ForecastCache dump/load last-writer-wins** — CONFIRMED, E1.
   Read forecast_cache.py:16-227 directly: `PersistentForecastCache.dump_to_disk`
   (185-204) builds `serializable` purely from this instance's own in-memory
   `self._store` and calls `atomic_write_json` — a full overwrite with no
   read-merge-write against the current disk state. `load_from_disk` (206-227)
   likewise just replaces in-memory entries from whatever the file currently
   contains. The lost-update mechanism is real and matches the claim; atomicity
   (via `safe_io.atomic_write_json`) prevents file corruption but not the
   cross-process merge/lost-update problem described.

No files modified outside `audit/`. No repo state changed. The only command executed
against real code was the read-only reproduction script (redirects `cron.LOCK_PATH`
to a tempdir; touches no real repo data).

---

## Re-verification (independent second pass, same session type, 2026-08-17)

Re-ran this verification from scratch against the 6-item raw-findings JSON (cron TOCTOU,
EMOS check-then-input, paper cross-process lock fail-open, trade_cycle prewarm pool,
settlement_monitor no overlap guard, ForecastCache last-writer-wins) without reading this
file's prior conclusions first. Independently re-read every cited file/line and re-ran
`audit/reproductions/cron_lock_race_repro.py` myself (`results: [True, True]`, race
confirmed again). All 6 findings independently CONFIRMED as accurate descriptions of
current code, matching the prior pass's conclusions above.

One nuance worth recording for finding 6 (ForecastCache): `load_from_disk` (forecast_cache.py:206-227)
does not literally clear `self._store` before merging — it iterates the loaded dict and
sets each key into the existing in-memory store, so strictly it is a key-wise merge-on-load,
not a full replace. This only matches the finding's "fully replaces in-memory entries"
description in practice because the sole caller (`nws.py:100`, `_load_station_cache()`)
runs once at module import when `_station_cache` is still empty. Does not change the
finding's core claim (dump-side is last-writer-wins with no cross-process merge) or its
INFO severity/financial-risk-none conclusion — noted as a minor descriptive imprecision,
not a substantive error.
