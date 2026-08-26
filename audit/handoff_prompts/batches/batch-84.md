# Batch 84: operator alerting and dashboard resilience — three ways a signal never reaches the operator

## Context

Repo: weather1. Written 2026-08-26 against master `0c332140` — **re-verify current before starting**. Live trading dormant.

**Files owned: `notify.py`, `watchdog.py`, `frontend/src/App.jsx`, `frontend/src/shared.jsx`, `frontend/src/tabs/AnalyticsTab.jsx`, `frontend/src/tabs/PositionsTab.jsx`, `frontend/src/tabs/SettingsTab.jsx`, `frontend/src/tabs/SignalsTab.jsx`.**

Three `backlog.txt` entries, all filed by batch-80, all about a message that does not arrive. No file here is touched by any other open batch.

### 1. [LOW] `notify.py` records the desktop channel as delivered when plyer merely started a thread

> `NOTIFY.PY RECORDS THE DESKTOP CHANNEL AS DELIVERED WHENEVER PLYER'S notify() RETURNS, BUT ON WINDOWS THAT ONLY MEANS "A THREAD WAS STARTED"`

Verified 2026-08-26 by inspecting the installed backend: `plyer.platforms.win.notification.WindowsNotification._notify` is exactly `thread(target=balloon_tip, kwargs=kwargs).start()`. Fire-and-forget, so the `try/except Exception` around `_notif.notify(...)` is decorative and `successes.append(True)` always runs.

**The consequence is not cosmetic.** `send_system_alert` returns `status != "failed"`, and its own docstring says `alerts.check_halt_transition` uses a `False` return to roll back edge-triggered state so the next cycle retries. A phantom `True` defeats exactly that. The "all N channel(s) failed" warning also cannot fire on a desktop-only failure.

~~The LOW rating rests on `NOTIFY_CHANNELS` defaulting to all five, not on anything in the code.~~

**CORRECTION 2026-08-26 — the LOW rating rests on a premise that is FALSE in this deployment, and the entry's own first-listed fix would have been a live regression.** Found by the batch-84 session; verified independently here.

`NOTIFY_CHANNELS` is unset, so all five channels are nominally enabled — but every alternate channel's credentials are unset too: `NTFY_TOPIC`, `PUSHOVER_TOKEN`, `PUSHOVER_USER`, `DISCORD_WEBHOOK_URL`, `DISCORD_WEBHOOK_URLS`, `SMTP_HOST`, `SMTP_USER` — all absent. And `_send_pushover`, `_send_ntfy`, `_send_discord` and `_send_email` each early-return `False` when unconfigured.

**So desktop's phantom `True` is the only reason `send_system_alert` ever returns `True` today.** The entry's first suggestion — stop treating desktop as a channel that can report success — would therefore have made *every* system alert `status="failed"`, rolling back the notify cooldown **and** `alerts.rollback_halt_transition` on every call, and re-firing each halt alert every cron cycle for as long as the condition lasted. The five-channel default does none of the protecting the entry credits it with.

Take the measurement to the user with both options; do not pick the cheap one on the entry's say-so. **`AskUserQuestion`:** stop appending `True` for desktop, or bypass `plyer.notification` and own the thread.

### 2. [LOW] `py watchdog.py` never calls `load_dotenv`

> `\`py watchdog.py\` NEVER CALLS load_dotenv, SO ITS ntfy PUSH ALERT CANNOT BE CONFIGURED FROM .env`

Zero impact today — `NTFY_TOPIC` is unset in this deployment — which is precisely why it can rot unnoticed on a dead-man's-switch path. The correct reference is `main.py`'s `load_dotenv()` at import; batch-79 established that **position, not presence, is what matters** (a `load_dotenv()` after the first env-reading import is a no-op that looks like a fix). Verify empirically in an isolated child process, as batch-79 did.

### 3. [LOW] Every other raw `fetch()` in the frontend still has no timeout

> `EVERY OTHER RAW fetch() IN THE FRONTEND STILL HAS NO REQUEST TIMEOUT`

Batch-80 fixed `useData.js`'s `apiFetch` but did not own these files. Operator-initiated actions and per-tab loads, so a hang stalls one button rather than the whole dashboard — hence LOW.

**Count them yourself: it is 14 call sites, and both numbers already in circulation are wrong.** `grep "fetch(" <the six files> | grep -v apiFetch` returns 15 *lines*, but `frontend/src/shared.jsx:709` is a comment inside `haltOrResume` quoting the code it replaced. The backlog entry's own prose says "Thirteen other call sites" while its `Files:` list enumerates 14 — so one circulating number is high and the other low. Verified breakdown: `App.jsx` 4, `shared.jsx` 1, `AnalyticsTab` 2, `PositionsTab` 2, `SettingsTab` 3, `SignalsTab` 2 = **14**.

**Build step, easy to miss:** `static/dist/` is **tracked** (11 content-hashed files), so a frontend change needs `npm run build` committed alongside it — every prior frontend commit did. `frontend/node_modules` does not exist in a fresh worktree; run `npm install` first.

**Reuse batch-80's shape, don't invent a second one.** Read what it did to `apiFetch` first. This repo's frontend has no component-render tests; only pure functions are unit-tested and the convention is to extract logic into `shared.jsx`. Plan for that rather than discovering it.


## Process — follow the 29-step implementation workflow

Read `C:\Users\thesa\.claude\projects\C--Users-thesa-claude-kalshi\memory\feedback_implementation_workflow.md` and follow it.

(1) Re-verify every claim below against live code first — these were measured 2026-08-26 and the repo moved fast that day. (3) `AskUserQuestion` for any item marked as needing a decision. (7) Mutation-test via the **Edit** tool, never a string-replace script — a scripted revert has left a silent third state in this repo before. Pair every absence-assertion with a positive control. (8) Scoped tests only — **never the bare full suite**.

> **CORRECTED SCOPE for this batch.** An earlier revision listed only `tests/test_notify.py` plus frontend unit tests. All four of these reference `send_system_alert` / `check_halt_transition`, which is precisely the contract item 1 changes:
>
> `tests/test_notify.py`, `tests/test_batch24_alerting.py`, `tests/test_batch33_reliability.py`, `tests/test_batch69_alerting_correlation.py`
>
> Frontend: `frontend/src/shared.test.js` **and `frontend/src/useData.test.js`** — the latter covers the `apiFetch` timeout batch-80 added, whose shape item 3 reuses.
>
> Re-run `grep -rln "<symbol>" tests/*.py` for each symbol you touch rather than trusting a hand-written list.

> **CORRECTED LINE NUMBERS.** An earlier revision cited `notify.py` positions that predate batch-80's truncation fix and are ~145 lines stale. Verified against master:
>
> | What | Actual |
> |---|---|
> | `alert_strong_signal` | `def` at **`:594`**, its `successes.append(True)` at **`:654`** |
> | `send_system_alert_detailed` | `def` at **`:692`**, its `successes.append(True)` at **`:789`** |
> | "all N channel(s) failed" warnings | **`:683`** and **`:830`** |
> | `NOTIFY_CHANNELS` default | `:51` |
>
> Re-locate by symbol regardless — batch-80 changed this file recently and these will move again. (9) Lint via the real pre-commit hook, not the repo `.venv`'s mypy; the versions disagree. (11) Independent opus review at `effort: high`. (13) Address every finding including LOW. (14) Memory before commit. (15) Explicit user confirmation before commit/push. (16) `git fetch` + rebase immediately before push. (19) `python backlog_index.py`.

**Two standing hazards.** Scripts run outside pytest bypass conftest's real-`data/`-write blocker and its default-deny network guard — redirect `safe_io.project_root()` or the specific `paths.py` constant before running any scratch script. And do not run `git restore .` or `git checkout -- data/`.
