# Batch 80: four independent small defects — dashboard hang, dropped alerts, two vacuous tests

> **Date convention note (added 2026-08-25 local).** Several dates in this batch set read `2026-08-26`. That is the **UTC** date; `git log` local time for every commit referenced here is **2026-08-25**. Where a time is given as UTC (e.g. the 00:28 UTC cron run) the date is correct as written; bare dates are off by one. Verified against `git log --date=iso`.

## Context

Repo: weather1. Written 2026-08-26 against master `e8d178f1` — **re-verify current before starting**. Live trading dormant. Nothing here touches a trading decision. This is the batch that can run alongside everything else with the least coordination.

**Files owned: `frontend/src/useData.js`, `frontend/src/tabs/OverviewTab.jsx`, `frontend/src/tabs/RiskTab.jsx`, `notify.py`, `tests/test_trade_improvements.py`, `tests/test_kelly_property.py`, `order_executor.py`.** No other batch in this set touches any of them.

Source: four `backlog.txt` entries, cited by title:
- `useData.js's apiFetch has no request timeout, so a HUNG backend freezes the whole dashboard silently instead of degrading`
- `A SYSTEM ALERT LONGER THAN 256 CHARACTERS CRASHES THE DESKTOP-TOAST BACKEND`
- `tests/test_trade_improvements.py::test_trades_placed_below_cap has never exercised the 20-position cap it is named for`
- `tests/test_kelly_property.py has a hypothesis DeadlineExceeded flake under machine load`

The four are unrelated to each other. Do them in any order; they are batched only because they share no files with anything else.

## Items

### 1. [MEDIUM] A hung backend freezes the dashboard silently

**Files:** `frontend/src/useData.js` (`apiFetch`, `safe`, `fetchAllSafe`, `fetchAll`), `frontend/src/tabs/OverviewTab.jsx` and `RiskTab.jsx` (consumers of the resulting frozen state).

> **Verified:** `apiFetch` at `frontend/src/useData.js:43` is a bare `await fetch(path, { headers: authHeader() })` — no `AbortSignal`, no timeout, anywhere in the file. Note `safe()` at `:53` swallows non-auth errors to `null`, so a timeout will surface to consumers as `null`, indistinguishable from any other failure. That is exactly where this brief's "trades a hang for a crash" concern lives — decide it deliberately.

`apiFetch` has no request timeout, so a backend that hangs rather than erroring leaves the whole dashboard frozen with no indication — it does not degrade, it stalls. Filed by batch-61's opus review (F1) as out of scope there.

Two things to get right rather than just adding an `AbortSignal.timeout()`:
- **What the consumers do with a timed-out fetch.** The entry names `OverviewTab.jsx` and `RiskTab.jsx` specifically because they consume the frozen state; a timeout that produces `undefined` where they expect data trades a hang for a crash.
- **Freshness.** A dashboard that silently shows stale numbers after a failed refresh is its own hazard — related open entry `A 200 is not a freshness claim` in this repo's own memory. Decide whether a timed-out panel shows stale-with-a-marker or an explicit error state.

**Testing note:** this repo's frontend has no component-render tests — only pure functions are unit-tested, and the convention is to extract logic into `shared.jsx` to make it testable. Plan for that rather than discovering it.

### 2. [LOW] Alerts over 256 characters silently lose their desktop half — **and are recorded as delivered**

> **Verified by inspecting the installed backend.** `plyer.platforms.win.notification.WindowsNotification._notify` is, in full:
>
> ```python
> def _notify(self, **kwargs):
>     thread(target=balloon_tip, kwargs=kwargs).start()
> ```
>
> Fire-and-forget. The `ValueError` raises inside `balloon_tip` **on a different thread**, so `notify.py:636-647` never sees it:
>
> ```python
> if _ENABLED and "desktop" in _CHANNELS:
>     try:
>         _notif.notify(title=title, message=message, ...)
>         successes.append(True)        # <- ALWAYS runs
>     except Exception as exc:
>         _log.warning(...)
>         successes.append(False)       # <- unreachable for this failure
> ```
>
> The `except` is decorative here, and a failed desktop alert is recorded as **delivered**. Same shape at `:509-521` in `alert_strong_signal`. This propagates into the return contract: `send_system_alert` returns `status != "failed"`, and its own docstring (`notify.py:733-740`) says `alerts.check_halt_transition` uses a `False` return "to know THIS alert never actually reached anyone and roll that state back so the next cycle retries instead of silently treating a failed delivery as done." A phantom `True` defeats exactly that, and the "all N channel(s) failed" warning at `:672` can never fire on a desktop-only failure.
>
> **The LOW rests on a config default, not on the code.** `NOTIFY_CHANNELS` defaults to all five (`notify.py:51`), so Discord does still deliver today — but one `NOTIFY_CHANNELS=desktop` and a halt transition is marked delivered and never retried. Keep the priority if you like; the fix must include not lying about success. Truncating the string alone leaves the decorative `except` in place for everything else plyer can raise on that thread.

**Files:** `notify.py` (`send_system_alert` / the plyer desktop backend).

plyer's Windows backend packs the message into a `NOTIFYICONDATAW` struct with a hard 256-character field; a longer string raises `ValueError: string too long (333, maximum length 256)` inside the notify thread. It surfaced as a `PytestUnhandledThreadExceptionWarning` — i.e. it escapes the thread **uncaught** rather than being truncated or logged.

Discord still delivers and no caller is affected, which is why it is LOW. But it drops the desktop half specifically for the **longest** messages, which are the most detailed and usually the most serious. Truncate with an ellipsis, or split, and log that it happened — the current behaviour loses the alert with no record.

Worth knowing while here: `kalshi_weather_index.py` fires `send_system_alert` for a Miami settlement-methodology change, which is exactly the kind of long, serious message this drops.

### 3. [LOW] A cap test that has never exercised its cap — **the root cause is already written in the test**

> **DO NOT TRUST THE ROOT CAUSE WRITTEN IN THE TEST.** `tests/test_trade_improvements.py:158-177` says the synthetic ticker `"KXHIGH-CHI-0"` "does not parse to a real city/target-date, so one of those factors zeroes it." An earlier revision of this file repeated that as authoritative. **It is wrong, traced 2026-08-25 by the batch-80 session:** with `city` and `target_date` both absent, `portfolio_kelly_fraction` takes its `if not city or not target_date_str` branch and *passes the value through* as `min(base_fraction, remaining)`; `liquidity_kelly_scale` returns 1.00 for this fixture (volume 500 + OI 1000 = 1500 > 500). Nothing zeroes it.
>
> The two real causes:
> 1. **A missing dict key.** The code sizes from `ci_adjusted_kelly` / `fee_adjusted_kelly` (`order_executor.py:4761-4765`) and never reads the `kelly_fraction` the fixture sets.
> 2. **Impossible open positions, hiding behind it.** The fixture's `{"cost": 10.0, "qty": 1}` rows are not a position `monte_carlo` can read — it wants `quantity` / `entry_price` — so 18 rows projected $174 of VaR and the candidate pushed it to $217 against the $200 limit. Everything then died at `var_limit`, not at the cap.
>
> **And the cap is not a per-placement counter.** `MAX_CONCURRENT_POSITIONS` is a single **pre-loop entry gate**: below the cap it places everything that qualifies. So "the test places 2" was never the code's behaviour — with 18 open it places 5, ending at 23. The correct assertion is `== 5`, and the overshoot is its own defect (filed separately). Tightening to `== 2` would have produced a red test.
>
> Both tests in `TestMaxConcurrentPositions` were vacuous, not only the named one — measured by running the originals against cap mutations 99/21/18 in a throwaway worktree: all green.
>
> Do not reorder `:111-118` — `importlib.reload(paper)` must precede `repatch_paper_paths(paper)`, or the reload discards the patch and Kelly sizes against the real balance and peak. It is already correct.

**Files:** `tests/test_trade_improvements.py` (`TestMaxConcurrentPositions`), `order_executor.py` (`_auto_place_trades` sizing gates).

`test_trades_placed_below_cap` has never exercised the 20-position cap it is named for — permanently vacuous, found by an opus review during batch-62 while tightening a nearby assertion.

Fix the fixture so the cap is actually reached, then **mutation-test it**: raise or remove the cap in `order_executor.py` and confirm the test fails for the right reason. A vacuous test that has been "passing" for months is exactly the case where a fix can look correct and still prove nothing. `order_executor.py` is owned by this batch precisely so you can perform that mutation.

### 4. [LOW] A hypothesis deadline flake — **only the two named tests are genuinely exposed**

> Confirmed no `deadline=` anywhere in `tests/test_kelly_property.py`, and there are seven `@settings(max_examples=...)` decorators (`:16, :29, :43, :65, :79, :93, :109`) all on the 200 ms default. An earlier revision of this file inferred from that count that all seven were exposed. **They are not** — traced 2026-08-25 by the batch-80 session: the other five do no I/O (0.04–0.21 s for 100–200 examples), while only the two named ones create a `TemporaryDirectory` **per example**, which is exactly why only they flaked. Leave the other five on the default deadline so they keep their regression signal, and record that reasoning rather than blanket-disabling.
>
> The conftest guards were ruled out as the cause, as this brief asks: timing the file at `95b0df4c` (pre-guard) vs now gives 0.57–0.58 s vs 0.57–0.59 s.

**Files:** `tests/test_kelly_property.py` (`test_kelly_quantity_cost_never_exceeds_balance`, `test_kelly_bet_dollars_never_exceeds_balance`).

Reproduced on unmodified master while regression-testing the `isolate_tracker_db` change. A timing-sensitive property test, not a logic defect: it fails intermittently under local machine load and would also fail on a loaded CI runner.

Raise or disable the deadline for these two rather than making the code faster — the property under test is a financial invariant (cost never exceeds balance) and is worth keeping strict on *values* while being lenient on *time*.

## Process — follow the 29-step implementation workflow

**This batch is the one legitimate candidate for the LOW-tier downgrade on steps 11–12** — items 2, 3 and 4 are small, mechanically verifiable, touch no live-order/live-money/safety-gate path, and do not span subsystems. Item 1 does **not** qualify: it spans three frontend files and changes what an operator-facing dashboard displays during a failure. Assess per item and state the tier you took; do not apply one blanket downgrade to the batch.

(1) Re-verify each entry against live code. (7) Mutation-test via **Edit**-revert, not string-replace scripts — item 3 is specifically a test whose whole defect is that it proves nothing, so its mutation is the deliverable. Pair absence-assertions with positive controls. (8) Scoped: `tests/test_trade_improvements.py`, `tests/test_kelly_property.py`, `tests/test_notify.py`, plus any frontend unit tests. **Never the bare full suite.** (9) Lint via the real pre-commit hook. (13) Address every review finding including LOW. (14) Memory before commit. (15) Explicit confirmation before commit/push. (16) `git fetch` + rebase immediately before push. (19) `python backlog_index.py` and confirm all four entries moved.

**Note for item 4:** `tests/conftest.py` gained a default-deny network guard (`3cca1e8e`) and a real-`data/`-write blocker (`27949ffa`) on **2026-08-25** (git log local time; an earlier revision said 08-26, which was the UTC date read as local — see the note at the top of this file). If a flake's timing changed recently, those fixtures are a plausible cause worth ruling in or out before retuning a deadline.
