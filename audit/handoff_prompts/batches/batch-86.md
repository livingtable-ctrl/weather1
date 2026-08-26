# Batch 86: storage economics and a cron test that asserts nothing

## Context

Repo: weather1. Written 2026-08-26 against master `0c332140` — **re-verify current before starting**. Live trading dormant.

**Files owned: `cloud_backup.py`, `cron.py`, `tests/test_phase2_batch_h.py`.**

> **Check `cron.py` before starting.** Verified 2026-08-26: `cloud_backup.py`'s 30-day prune is at **`:262`**, and the vacuous test is `test_monday_check_uses_utc_weekday` at **`tests/test_phase2_batch_h.py:253`**. `0c332140` ("unroll the pruner loop so the dead-code scan can see both calls") landed 2026-08-26 and touched it. Rebase onto current master.

## ⚠ REVIEW FINDINGS 2026-08-26 — read before anything else

Reviewed after writing. Item 1's premise is materially wrong in three ways, and the third is more important than the item.

**1. A retention policy ALREADY EXISTS.** `cloud_backup.py:262` prunes date-named snapshot dirs older than 30 days (`if (_today_utc - dir_date).days <= 30: continue`). The "31" is not an oversight — it *is* that policy, expressed as a count. The item's `AskUserQuestion` implies none exists; ask instead whether **30 days of daily full uncompressed copies** is the right shape, versus compression, incremental, or a shorter window.

**2. "The sync folder holds 31 copies" is a PROJECTION, not a measurement.** Measured on 2026-08-26:

```
sync folder : C:\Users\thesa\OneDrive   (CLOUD_BACKUP_PATH unset; the OneDrive
                                          fallback in _find_sync_folder resolves)
snapshots   : 2 dirs, 74.2 MB total       <- not 31, and not ~1.5 GB
```

Only two days of backups have ever run, because the machine was powered off from May until 2026-08-25. The 31-copy figure is where the existing 30-day policy will *arrive* over the coming month, and that is a real forward cost worth deciding on — but do not quote it as a current state, and re-measure before sizing anything.

**3. THE FINDING THAT MATTERS: one of the two snapshots contains no database at all.**

```
2026-08-25 : 100 files, 12.8 MB   <- ZERO .db files
2026-08-26 : 108 files, 61.4 MB   <- predictions.db 47.4 MB, execution_log.db 0.1 MB
```

A retention policy that keeps 31 copies is worth nothing if some fraction of them have no database in them. `backup_data`'s copy loop has **three** distinct paths that produce exactly this shape, and they differ in how loudly they fail:

- `_sqlite_source_is_empty(src_file)` → `continue`, logged at **DEBUG** only
- `backup_sqlite_db(...)` returns False (post-copy readability check) → **WARNING**, `all_readable = False`
- the per-file `except Exception` → logged, run continues

**Determine which one happened on 2026-08-25 before touching retention.** One log check disambiguates it. If it was the silent DEBUG path, that is a more serious defect than the storage question and should be filed separately — a backup can currently report success while omitting the primary database.

Note the copy path is otherwise careful and should not be "simplified": `backup_sqlite_db` is WAL-safe deliberately, because a plain `shutil.copy2` of a `.db` silently omits anything committed but not yet checkpointed out of the `-wal` sidecar. That was reproduced live (AUD backup/pass20).


## Where this batch sits, as of 2026-08-26

The project has since been measured against the market on the unbiased `analysis_attempts` population and **found to have no edge** — 0 of 18 cities, both horizons, all three methods, both families. See `backlog.txt`'s *"PROJECT DIRECTION AFTER THE NO-EDGE RESULT"*. That does **not** cancel this batch: nothing here is an attempt to improve the forecast, and every item is a correctness or observability defect that stands regardless of whether the bot ever trades again. But it does set the bar for scope — **do not expand this batch into anything justified as improving edge.**

**And it RAISES this batch's item 1.** If the project becomes a measurement platform rather than a trading one — which is the leading option — then the accumulated data *is* the asset. A backup that silently omits the database stops being a storage-economics question and becomes the main risk to the only thing of value.

**Re-measured 2026-08-26 against master `1e06d6d3`** (supersedes the figures below):

```
2026-08-25 : 100 files   12.8 MB   db = NONE
2026-08-26 : 111 files   62.3 MB   db = execution_log.db, predictions.db
TOTAL 75.1 MB across 2 snapshot dirs
```

**The 2026-08-25 snapshot still contains no database, a full day later.** That is not a transient race — it is a permanent hole. Snapshot dirs are date-named and only rewritten within their own day, so **2026-08-25 has no database backup and never will**. A restore to that day is impossible. Establish which of `backup_data`'s three paths produced it (`_sqlite_source_is_empty` skip at DEBUG, `backup_sqlite_db` readability-check failure at WARNING, or the per-file `except`) **before touching retention** — a 30-day policy that keeps some snapshots with no database in them is worse than a shorter one that keeps whole snapshots. If it was the silent DEBUG path, file it separately: a backup reporting success while omitting the primary database is a bigger defect than anything else in this batch.

### 1. [MEDIUM] Every byte kept in `predictions.db` is paid 31 times over in the backup folder

> `EVERY BYTE KEPT IN predictions.db IS PAID 31 TIMES OVER IN THE BACKUP FOLDER`

Found by batch-78 while sizing a retention window — the window decision could not be made honestly without it, but `cloud_backup.py` was outside that batch's scope.

Nothing is broken and local disk is cheap (155 GB free as of 2026-08-26). It matters because **it silently multiplies the cost of every future retention decision by 31**, and batch-78 has just made two such decisions (730 days for `ensemble_member_values`, 30 for `orderbook_depth_snapshots`) without that multiplier in view. `predictions.db` is ~47 MB and `cloud_backup.backup_data` pushes it after every cron run.

**`AskUserQuestion`:** the retention/rotation policy for the backup folder itself. Do not pick a number unilaterally — it trades recoverability against disk, and the destination matters as much as the count.

### 2. [LOW] A test named for the UTC-Monday fix asserts nothing at all

> `A TEST NAMED FOR THE UTC-MONDAY FIX ASSERTS NOTHING AT ALL`

Found by batch-78 looking for existing coverage of cron's Monday sweep. The behaviour it is named for is believed correct; the problem is that nothing would notice if it stopped being. **A test that cannot fail is worse than a missing one, because the suite reports it as coverage.**

Same shape as batch-83's `pytest.skip` trapdoor and batch-80's vacuous cap test — **its mutation is the deliverable.** Repair it, then break the UTC-Monday logic deliberately and confirm the repaired test goes red for the right reason.


## Process — follow the 29-step implementation workflow

Read `C:\Users\thesa\.claude\projects\C--Users-thesa-claude-kalshi\memory\feedback_implementation_workflow.md` and follow it.

(1) Re-verify every claim below against live code first — these were measured 2026-08-26 and the repo moved fast that day. (3) `AskUserQuestion` for any item marked as needing a decision. (7) Mutation-test via the **Edit** tool, never a string-replace script — a scripted revert has left a silent third state in this repo before. Pair every absence-assertion with a positive control. (8) Scoped tests only — **never the bare full suite**. This file originally named none; use:

> `tests/test_cloud_backup.py` (the dedicated suite for item 1), `tests/test_phase2_batch_h.py` (item 2 — the test is `test_monday_check_uses_utc_weekday` at `:253`), `tests/test_cron_integration.py`, `tests/test_cron_group_c.py`, `tests/test_cron_lock.py`, `tests/test_cron_watchdog.py`, `tests/test_batch33_reliability.py`.
>
> Confirm with `grep -rln "<symbol>" tests/*.py` for whatever you actually change rather than trusting this list. (9) Lint via the real pre-commit hook, not the repo `.venv`'s mypy; the versions disagree. (11) Independent opus review at `effort: high`. (13) Address every finding including LOW. (14) Memory before commit. (15) Explicit user confirmation before commit/push. (16) `git fetch` + rebase immediately before push. (19) `python backlog_index.py`.

**Standing hazards — the first was INVERTED by batch 83 and is corrected here.**

- ~~Scripts run outside pytest bypass conftest's real-`data/`-write blocker~~ — **no longer true.** Batch 83 (`c8bb4a1c`, *"arm the prod-data guard outside pytest"*) armed it, so a scratch script that writes under the real `data/` now **raises**, it does not silently succeed. Redirect `safe_io.project_root()` or the specific `paths.py` constant before running one. The default-deny network guard is still pytest-only.
- Do not run `git restore .` or `git checkout -- data/`.

**Lint — `git commit` does NOT lint anything in this repo.** There is no `.git/hooks/pre-commit`, no `.githooks/` directory, and `core.hooksPath` is unset, so a clean `git commit` is indistinguishable from a passing hook. Run `python -m pre_commit run --files <paths>` explicitly. And if you add or edit anything under `audit/`, run CI's own two commands as well — `ruff check .` and `mypy . --ignore-missing-imports --implicit-optional --no-error-summary` — because `.pre-commit-config.yaml` sets `exclude: ^audit/` on ruff, ruff-format and mypy while `.github/workflows/ci.yml` applies no exclusion at all. A green hook is not a green CI.
