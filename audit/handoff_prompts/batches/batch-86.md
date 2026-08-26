# Batch 86: storage economics and a cron test that asserts nothing

## Context

Repo: weather1. Written 2026-08-26 against master `0c332140` — **re-verify current before starting**. Live trading dormant.

**Files owned: `cloud_backup.py`, `cron.py`, `tests/test_phase2_batch_h.py`.**

> **Check `cron.py` before starting.** `0c332140` ("unroll the pruner loop so the dead-code scan can see both calls") landed 2026-08-26 and touched it. Rebase onto current master.

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

(1) Re-verify every claim below against live code first — these were measured 2026-08-26 and the repo moved fast that day. (3) `AskUserQuestion` for any item marked as needing a decision. (7) Mutation-test via the **Edit** tool, never a string-replace script — a scripted revert has left a silent third state in this repo before. Pair every absence-assertion with a positive control. (8) Scoped tests only — **never the bare full suite**. (9) Lint via the real pre-commit hook, not the repo `.venv`'s mypy; the versions disagree. (11) Independent opus review at `effort: high`. (13) Address every finding including LOW. (14) Memory before commit. (15) Explicit user confirmation before commit/push. (16) `git fetch` + rebase immediately before push. (19) `python backlog_index.py`.

**Two standing hazards.** Scripts run outside pytest bypass conftest's real-`data/`-write blocker and its default-deny network guard — redirect `safe_io.project_root()` or the specific `paths.py` constant before running any scratch script. And do not run `git restore .` or `git checkout -- data/`.
