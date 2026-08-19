# Pass 12 (Concurrency) — Independent Verification

All 5 findings independently checked against current code. Summary:

1. cron lock TOCTOU race — CONFIRMED. Re-ran audit/reproductions/cron_lock_race_repro.py
   this session: `results: [True, True]` (both threads acquired). Cross-checked
   cron.py:205-286 (_acquire_cron_lock: `if lp.exists():` ... later `lp.write_text(...)`,
   no O_EXCL/msvcrt lock) and financial-risk citations (cron.py:900-921 live-position
   protection call, execution_log.py was_recently_ordered/was_traded_today L278-325 —
   confirmed no UNIQUE constraint on `orders` table, only CREATE TABLE at L129).
   Evidence: E2 (reproduced this session).

2. EMOS train/deactivate TOCTOU before long input() wait — CONFIRMED. Read main.py
   verbatim: cmd_emos_train's _is_cron_running() check at L6682, input() prompt afterward,
   save_emos_params()/reset_temperature_scale_for_emos() write with no re-check in between.
   cmd_emos_deactivate mirrors at L6820 -> input() -> deactivate_emos() with no re-check.
   Line numbers match the finding exactly. E1 (static only, as originally claimed).

3. paper._CrossProcessDataLock silent-open-after-10s fallback — CONFIRMED, UPGRADED TO E2.
   Read paper.py:171-199 (_acquire_file_lock: 10.0s deadline, on continued OSError closes fh
   and returns without setting self._fh, logs only a warning). Wrote and ran
   scratchpad/paper_lock_repro.py this session: held an OS-level msvcrt lock on a temp file
   from one handle, called the real _CrossProcessDataLock._acquire_file_lock from a second
   thread with the real 10.0s deadline unmodified. Result: `elapsed: 10.02s, fh_is_none: True`
   — confirms the fallback actually fires under real sustained contention, not just in theory.
   Also confirmed save_peak's re-check-under-lock comment (paper.py:1388-1405) depends on the
   same lock being effective cross-process — if the lock silently degrades, that mitigation
   degrades with it.

4. trade_cycle.py prewarm ThreadPoolExecutor not cancelled on timeout — CONFIRMED.
   trade_cycle.py:1150-1173 matches exactly (`_as_completed(warm_futures, timeout=200)`,
   TimeoutError handler logs+falls through, `warm_pool.shutdown(wait=False)` with no
   cancel_futures=True). cron.py watchdog os._exit(1) hard-kill confirmed at cron.py:2375-2377
   (verbatim comment "hard kill — no cleanup"). E1, as originally claimed (theoretical
   consequence reasoned from documented CPython atexit-join behavior of ThreadPoolExecutor
   worker threads, not independently reproduced).

5. settlement_monitor.py no application-level overlap guard — CONFIRMED. Grepped
   settlement_monitor.py for lock/PID logic: none found (only unrelated "lock-in" METAR
   domain terminology). write_settlement_signals (L126, matches cited line) does a full
   atomic_write_json overwrite of the whole signals list, no merge. main.py:9142-9179
   schtasks /Create call confirmed to have no explicit /RU or multiple-instance-policy flag.
   E1, as originally claimed (could not inspect real live Task Scheduler config, nor should
   this read-only audit create one).

6. ForecastCache last-writer-wins on disk snapshot — CONFIRMED for dump_to_disk (full
   atomic_write_json overwrite of the whole store, forecast_cache.py:185-204, matches).
   MINOR CORRECTION: load_from_disk (L206-227) does NOT "fully replace" in-memory entries
   as the finding states — it merges disk entries into self._store key-by-key (no
   `self._store.clear()` before the loop), so a load doesn't wipe purely-in-memory entries
   the caller hasn't dumped yet. This doesn't change the core claim (dump_to_disk's
   full-overwrite is what actually causes the last-writer-wins loss), so kept CONFIRMED with
   an inaccuracy note rather than downgraded. INFO severity affirmed — no trading-state caches
   are affected, confirmed by grep (only forecast/station lookup caches use this class in this
   pass's read window).
