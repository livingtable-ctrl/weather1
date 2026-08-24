# Batch 33: Cron, alerting & backup reliability

## Context

Repo: weather1. Written 2026-08-23 against master `f4291771` — re-verify before starting. Source: `audit/POST_MERGE_REVIEW.md`. Files owned: `cron.py`, `alerts.py`, `notify.py`, `trade_cycle.py`, `cloud_backup.py`. Parallel-safe with batches 34-39 (file-disjoint); run after batches 31-32 land.

## Items

### 1. M-1 [MEDIUM | skeptic-corrected scope]: batch-24's two fixes defeat each other — halt-transition edge consumed on delivery failure

**Files:** `alerts.py:84-106`, `notify.py:487-491,532-551`. Both from `651bbe3f`.
`check_halt_transition` persists `state[halt_type]=active` and returns the false→true edge BEFORE any delivery; `send_system_alert`'s rollback restores only the cooldown (different file, different module) — so a total delivery failure at the instant a halt engages permanently eats that engagement's alert (early-return `alerts.py:84-85` next cycle). Skeptic scope corrections to respect: `drawdown`/`daily_loss` have a redundant second observer (cron tracks `{type}_paper`, order_executor tracks unsuffixed — same cooldown key → same-cycle second attempt); only `anomaly` (`cron.py:1356`, `:1442`) is single-observer; and this deployment currently has ZERO push channels configured (only the plyer toast can succeed), so today the impact is "drops the one toast retry". Fix anyway — it defeats batch-24's stated rollback intent and becomes real the day a webhook is configured: persist the transition flag only after ≥1 channel succeeded, or give `send_system_alert` a success return that halt call sites use to roll the flag back.

### 2. M-3 [MEDIUM]: `_release_cron_lock` fails open to `unlink()` in exactly the case batch-30's check protects against

**Files:** `cron.py:464-480`. Batches `904ea92d` × `4e1739fb`.
The release-side mutex is deliberately best-effort (acquire result discarded); batch-30's ownership read inside it defaults `owner_pid=None` on a torn/empty/PermissionError read and falls through to `lp.unlink(missing_ok=True)` — deleting a possibly-fresh lock another process just wrote (the exact H2 scenario the check exists to prevent). `cmd_watch --auto --live` holds this lock. Fix: on an unreadable/unparseable read, SKIP the unlink (fail closed); only unlink on a positive PID match.

### 3. M-5 [MEDIUM]: `last_full_scan` stamped by cycles that never scanned (batch-20 × batch-24 contradiction)

**Files:** `cron.py:3249-3252` vs `:3197` and `:3228`.
The `finally` write keys off the `sameday_only` ARGUMENT; `_full_scan = bool(_cmd_cron_body(...))` — the real "a full scan completed" outcome — is computed in scope and used only for the exit code. Kill-switch-aborted (`:943`), black-swan-aborted (`:1468`), engine-kill (`:1895`), and crashing cycles all stamp a fresh full scan → all three staleness alarms (main's banner, `cron_full_scan_gap`, `cron_gap`) stay silent while cron fails every cycle. Fix: key the write off `_full_scan`, and mirror batch-24's kill-switch freeze (`:3227-3229`) for the heartbeat file.

### 4. M-6 [MEDIUM]: `--sameday-only` inflates the rain-arb shadow-graduation denominator

**Files:** `trade_cycle.py:314-350`. Batches `cea6a002` × `1f618417`.
The sameday filter reassigns `markets` before `find_violations`; `is_sameday_market` returns False for every rain ladder by construction — so no rain ladder can be examined on a sameday cycle, yet `record_shadow_observations` still increments `cycles_observed` (the documented violation-rate denominator, `backlog.txt:8060`). Fix: skip the consistency-check/shadow-record step entirely on sameday-only cycles (or record with a distinguishing marker the future graduation query excludes).

### 5. M-21 [MEDIUM]: `cloud_backup.backup_data`'s `all_readable` return discarded at its only caller

**Files:** `cloud_backup.py:257`; `cron.py:3019`. Batch `077052ad`.
Batch-25 changed the return specifically so a failed WAL-safe `.db` copy would be visible; cron calls `_backup()` bare. A permanently failing `execution_log.db` backup = one warning per cycle, nothing else — the silent-backup-failure shape batch-25 exists to eliminate, one layer up. Fix: consume the bool; on False, `send_system_alert` (respecting item 1's fixed semantics) or at minimum escalate to ERROR with a counter. Also two LOWs in the same file: the 30-day prune compares UTC-named dirs against local `date.today()` (`:181` vs `:252`, plus rmtree OSError falling to the outer handler flips a good run to False), and `restore_data`'s pre-restore snapshot nests prior snapshots (`:304-318` — exclude `.pre_restore_*`/`.history`/`.emergency` and sidecars).

### 6. M-28 [MEDIUM]: Discord webhook URLs (bearer credentials) logged at WARNING

**Files:** `notify.py:322`.
Batch-24 rerouted all safety alerts through `_send_discord` and made failures retry every cycle — during an outage `bot.log` accumulates the full secret URL repeatedly. No redaction helper exists in the repo. Fix: log scheme+host+webhook-id prefix only; grep the file for any other URL-bearing log lines while there. Latent today (no webhook configured) — still fix before one ever is.

### 7. L-4 [LOW]: `NOTIFY_CHANNELS` parsed without strip/lower (`notify.py:41-43`) — `"discord, email"` silently drops email, defeating batch-24's all-channels guarantee. `strip().lower()` each token, warn on unknown names.

### 8. L-6 + L-5 [LOW]: cron-lock bookkeeping honesty
(a) The lock's `heartbeat` field is written once at acquire and never updated (`cron.py:412`), so the no-psutil fallback (`:394-406`, `:532`) reasons on lock age while calling it heartbeat age — either refresh it periodically or delete the field and rename the check.
(b) `started_at` default 0 (`:340`, `:519`) lets the 24h backstop override a live holder on valid-JSON-without-the-key; default to `_time.time()` (treat unknown as fresh → fail closed).
(c) `lp.write_text(json.dumps(...))` at `:426` is the one non-atomic write left on this path.
(d) `_check_prod_reminder`'s three naive `date.today()` calls (`:664,669,691` — the file's only naive sites) → `utils.utc_today()`.

### 9. L-8 [LOW, knowingly-deferred cross-batch handoff]: `cron.py:1829` log-rotation `Path.replace()`
`tests/test_bare_os_replace_guard.py` explicitly allowlists this as "a different batch's file ownership"; four cron-owning batches have since passed over it. Route through `safe_io`'s retry wrapper and remove the allowlist entry. Also decide (AskUserQuestion, tied to the VM-move plan): `_poll_pending_orders` has exactly one caller (`cmd_watch`) — on a cron-only host the GTC cancels, natural settlement, and the live daily-loss brake never run (report L-11). Wire a subset into cron now, or file it as an explicit VM-move prerequisite in backlog.txt; don't leave it undecided.

## Process

Follow the 29-step workflow in full (alerting/locking is safety-adjacent; opus review effort=high). Re-verify claims live first. Scoped tests only (`test_cron_lock`, `test_cron_integration` markers, `test_notify`/`test_alerts` if present, `test_cloud_backup`, `test_infrastructure` — **never the full suite**). Lint via the real pre-commit interpreter. Backlog entries + `backlog_index.py`. Confirm before commit. Full workflow: `memory/feedback_implementation_workflow.md`.
