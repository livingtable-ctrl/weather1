# Batch 80: four independent small defects — dashboard hang, dropped alerts, two vacuous tests

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

`apiFetch` has no request timeout, so a backend that hangs rather than erroring leaves the whole dashboard frozen with no indication — it does not degrade, it stalls. Filed by batch-61's opus review (F1) as out of scope there.

Two things to get right rather than just adding an `AbortSignal.timeout()`:
- **What the consumers do with a timed-out fetch.** The entry names `OverviewTab.jsx` and `RiskTab.jsx` specifically because they consume the frozen state; a timeout that produces `undefined` where they expect data trades a hang for a crash.
- **Freshness.** A dashboard that silently shows stale numbers after a failed refresh is its own hazard — related open entry `A 200 is not a freshness claim` in this repo's own memory. Decide whether a timed-out panel shows stale-with-a-marker or an explicit error state.

**Testing note:** this repo's frontend has no component-render tests — only pure functions are unit-tested, and the convention is to extract logic into `shared.jsx` to make it testable. Plan for that rather than discovering it.

### 2. [LOW] Alerts over 256 characters silently lose their desktop half

**Files:** `notify.py` (`send_system_alert` / the plyer desktop backend).

plyer's Windows backend packs the message into a `NOTIFYICONDATAW` struct with a hard 256-character field; a longer string raises `ValueError: string too long (333, maximum length 256)` inside the notify thread. It surfaced as a `PytestUnhandledThreadExceptionWarning` — i.e. it escapes the thread **uncaught** rather than being truncated or logged.

Discord still delivers and no caller is affected, which is why it is LOW. But it drops the desktop half specifically for the **longest** messages, which are the most detailed and usually the most serious. Truncate with an ellipsis, or split, and log that it happened — the current behaviour loses the alert with no record.

Worth knowing while here: `kalshi_weather_index.py` fires `send_system_alert` for a Miami settlement-methodology change, which is exactly the kind of long, serious message this drops.

### 3. [LOW] A cap test that has never exercised its cap

**Files:** `tests/test_trade_improvements.py` (`TestMaxConcurrentPositions`), `order_executor.py` (`_auto_place_trades` sizing gates).

`test_trades_placed_below_cap` has never exercised the 20-position cap it is named for — permanently vacuous, found by an opus review during batch-62 while tightening a nearby assertion.

Fix the fixture so the cap is actually reached, then **mutation-test it**: raise or remove the cap in `order_executor.py` and confirm the test fails for the right reason. A vacuous test that has been "passing" for months is exactly the case where a fix can look correct and still prove nothing. `order_executor.py` is owned by this batch precisely so you can perform that mutation.

### 4. [LOW] A hypothesis deadline flake

**Files:** `tests/test_kelly_property.py` (`test_kelly_quantity_cost_never_exceeds_balance`, `test_kelly_bet_dollars_never_exceeds_balance`).

Reproduced on unmodified master while regression-testing the `isolate_tracker_db` change. A timing-sensitive property test, not a logic defect: it fails intermittently under local machine load and would also fail on a loaded CI runner.

Raise or disable the deadline for these two rather than making the code faster — the property under test is a financial invariant (cost never exceeds balance) and is worth keeping strict on *values* while being lenient on *time*.

## Process — follow the 29-step implementation workflow

**This batch is the one legitimate candidate for the LOW-tier downgrade on steps 11–12** — items 2, 3 and 4 are small, mechanically verifiable, touch no live-order/live-money/safety-gate path, and do not span subsystems. Item 1 does **not** qualify: it spans three frontend files and changes what an operator-facing dashboard displays during a failure. Assess per item and state the tier you took; do not apply one blanket downgrade to the batch.

(1) Re-verify each entry against live code. (7) Mutation-test via **Edit**-revert, not string-replace scripts — item 3 is specifically a test whose whole defect is that it proves nothing, so its mutation is the deliverable. Pair absence-assertions with positive controls. (8) Scoped: `tests/test_trade_improvements.py`, `tests/test_kelly_property.py`, `tests/test_notify.py`, plus any frontend unit tests. **Never the bare full suite.** (9) Lint via the real pre-commit hook. (13) Address every review finding including LOW. (14) Memory before commit. (15) Explicit confirmation before commit/push. (16) `git fetch` + rebase immediately before push. (19) `python backlog_index.py` and confirm all four entries moved.

**Note for item 4:** `tests/conftest.py` gained a default-deny network guard (`3cca1e8e`) and a real-`data/`-write blocker (`27949ffa`) on 2026-08-26. If a flake's timing changed recently, those fixtures are a plausible cause worth ruling in or out before retuning a deadline.
