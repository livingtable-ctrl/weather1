# Batch 69: A6 alerts that leave the browser tab + A5 correlated exposure

## Context

Repo: weather1. Written 2026-08-24 against master `a67a21a6` — **re-verify current before starting** (`git fetch` + `git log origin/master`). Live trading dormant. Item 1 sends real notifications; item 2 must not change sizing in this batch.

Source: Weather V3 additions handoff (A6, A5), re-planned in **Backend Build Order** — https://claude.ai/code/artifact/dc35c571-4d3d-4771-b7f1-95518032a010. See [INDEX-PANEL-BACKENDS.md](INDEX-PANEL-BACKENDS.md).

Files owned: `notify.py`, `alerts.py`, `cron.py` (evaluation hook), `tracker.py` (rules + deliveries tables, and a correlation table for item 2), `web_app.py`.

**Coordination:** `cron.py` is also touched by batch-33 (per the roadmap index) and by batch 71's scan-trigger change. Item 1 adds one evaluation call at the end of the cycle — a small, well-isolated hook. Rebase behind whoever lands first.

Independent of every other batch in this set. Can run at any time.

## Items

### 1. A6 [MEDIUM]: nobody finds out when the kill switch fires at 3am

**Files:** `notify.py`, `alerts.py`, `cron.py`, `tracker.py` (two new tables), `web_app.py`.

**Half of this is already built, contrary to the handoff.** `notify.py` already has five delivery channels (`desktop`, `pushover`, `ntfy`, `discord`, `email`, selected via `NOTIFY_CHANNELS`) plus cooldown state with reserve/rollback (`_system_cooldown_reserve`, `_system_cooldown_rollback`). The handoff's "webhook URL and email inputs" framing understates what exists — **read `notify.py` before designing anything and build on its channels rather than adding a sixth mechanism beside them.**

What is missing: a rules table, an evaluation pass, and a deliveries log. The panel replaces the localStorage position alerts entirely, which are never evaluated when the tab is closed — that is the actual problem.

**Baseline rules to ship with, from the handoff:** kill switch engages; cron has not run in 12h; Brier above threshold two weeks running; signal edge ≥ X with ≥ Y fillable; drawdown tier changes; position unsettled 2h past close (**ships disabled**).

**Fix direction:** rules table; an evaluation pass at the end of each cron cycle **plus** on kill-switch and drawdown-tier transitions (a tier change between cycles must not wait for the next cycle); a deliveries table recording status, what fired, and when. **A failed delivery must itself be alertable** — the handoff says so and it is the difference between an alerting system and a decoration.

Two traps: the "cron has not run in 12h" rule cannot be evaluated *by* the cron cycle it is watching — it needs a different trigger or an external check, and getting that wrong ships a rule that structurally can never fire. And reuse `notify.py`'s existing cooldown rather than inventing per-rule throttling, or a flapping condition will send hundreds of messages.

### 2. A5 [MEDIUM]: no idea how many independent bets are actually running

**Files:** `tracker.py` (offline correlation table + query), `web_app.py`, and the Kelly sizing path (**read-only in this batch**).

Five cities' daily highs are not independent — a regional heat event moves several at once. Positions are grouped by nothing today, so five "separate" positions can be one bet.

Grouping open positions by `target_date` uses a field that already exists. The correlation table itself is genuinely new: computed offline from historical observed highs, and it moves seasonally rather than daily, so recompute monthly at most.

**Fix direction:** exposure by settlement date against a percent-of-balance cap, plus a city correlation matrix from the offline table, plus the worst pair named.

**The Kelly correlation-adjustment factor is the one piece of new sizing logic and it must NOT go live in this batch.** The handoff is explicit: put it behind a setting and default it off until A1 (batch 66) can measure its effect. Ship the measurement and the display; leave the sizing path reading exactly what it reads today.

## Process — follow the 29-step implementation workflow (`feedback-implementation-workflow`) exactly, in order

Full 29 steps. Item 1 sends real messages to real channels; item 2 sits next to sizing.

(1) Re-verify: read `notify.py`'s channel and cooldown implementation before designing item 1 — scope the item down to the genuine gap rather than duplicating what exists. (3) `AskUserQuestion` for: where the "cron hasn't run" rule is evaluated from (its trigger is the whole design); whether rules are user-editable rows or code-declared with per-rule enable flags; and the correlation table's lookback window. Equal visibility for all three. (7) Real mutation-tested tests via Edit-revert. For item 1, **every absence-assertion needs a positive control** — "no alert fired" passes vacuously if the candidate never reached the evaluator, which is precisely the failure mode here. Test that a failed delivery is itself recorded and alertable. Mock the channel transports; do not send real messages from tests. (8) Scoped: `tests/test_notify.py`, `tests/test_alerts.py`, `tests/test_cron*.py`, `tests/test_tracker.py`, `tests/test_web_app.py`. **Never the full suite.** (9) Lint via the real pre-commit hook. (11) Independent opus review at `effort: high`. (13) Address every finding including LOW. (14) Memory before commit. (15) Explicit confirmation before commit/push. (16) `git fetch` + rebase immediately before push.

**Before declaring item 1 done:** trigger each baseline rule for real (in a scratch environment) and confirm the message arrives and the delivery row is written. An alerting system that passes its unit tests and delivers nothing is the exact failure this panel exists to fix.

Full step list: `C:\Users\thesa\.claude\projects\C--Users-thesa-claude-kalshi\memory\feedback_implementation_workflow.md`.
