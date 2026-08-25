# Batch 71: A18 latency race + A15b rank histogram — BLOCKED on batch 64, and on the calendar

## Context

Repo: weather1. Written 2026-08-24 against master `a67a21a6` — **re-verify current before starting** (`git fetch` + `git log origin/master`). Live trading dormant. Item 1 includes a **change to when scans run** — read its warning.

Source: Weather V3 additions handoff (A18, A15), re-planned in **Backend Build Order** — https://claude.ai/code/artifact/dc35c571-4d3d-4771-b7f1-95518032a010. See [INDEX-PANEL-BACKENDS.md](INDEX-PANEL-BACKENDS.md).

Files owned: `tracker.py` (new query functions), `web_app.py`, `cron.py` (schedule/trigger, item 1 only).

**Blocked on [batch 64](batch-64.md):** item 1 needs W1 (real model-cycle timestamps), item 2 needs W2 (per-member values) **and months of accumulation**. Check actual row counts before starting — this is the batch most likely to be started too early. A15b in particular cannot be rushed; if members have been persisting for two weeks, the rank histogram has two weeks of data and will say nothing.

**Coordination:** `cron.py` is also touched by batch 69's alert hook and by batch-33. Item 1's change is to the scan trigger itself — a larger and more disruptive edit. Land 69 first if both are in flight.

## Items

### 1. A18 [MEDIUM — CHANGES SCAN SCHEDULING]: are we actually faster than the market at pricing a new cycle

**Files:** `tracker.py` (new query function), `web_app.py`, `cron.py` (trigger), and batch 64's model-cycle timestamp field.

**The handoff understates this one.** It says "three of its four timestamps are already in the logs". They are not, in the sense that matters: `order_executor._current_forecast_cycle()` derives the stored `forecast_cycle` from the wall clock (`12 if now.hour >= 12 else 0`), not from the run the data came from. Batch 64 item 1 adds the real timestamp; without it this panel has no x-axis.

The panel's own conclusion is worth stating up front because it is uncomfortable: if the market has already absorbed a model cycle by the time we scan, the disagreements that survive are the ones the market **chose** not to remove — a selection effect pointing the same way as A14's finding of no measurable skill. Build the panel expecting that answer rather than the flattering one.

**Fix direction:** per-cycle timing — cycle name, real output time, the window in which the market completes most of its repricing (detectable from `price_history`), and the dead time before the next scan. Two summary figures: how fast the market reprices, versus median scan lag.

**Look up the real publication times** for the products actually being pulled. The handoff's 03:35 / 09:35 / 15:35 / 21:35 ET are explicitly invented, like every number in that document. Do not hardcode them.

**The recommendation half — triggering scans on output availability instead of a wall clock — changes operational behaviour and must be a separate, explicit decision with the user.** Ship the measurement first. An availability-triggered scan that misfires stops the bot scanning at all, which is a strictly worse failure than scanning slightly late. If it is implemented, it needs a wall-clock fallback that fires if availability is not detected within a bounded window.

### 2. A15b [MEDIUM — needs months of data]: is the ±1.2 we size off actually the spread

**Files:** `tracker.py` (new query function over batch 64's member values), `web_app.py`.

Batch 68 shipped the station-bias half from `ensemble_member_scores`. This is the half that genuinely needed new persistence: the rank histogram needs where the observed value fell among the **sorted members**, and CRPS needs the member distribution. Neither is reconstructable from mean and σ.

**Fix direction:** rank histogram across bins with the expected flat height and the observed outside-range rate against the expected one, yielding the implied over-confidence factor; claimed σ versus realized RMSE by lead with the ratio; and CRPS now versus CRPS after a backtested bias + σ correction (closed form exists for the truncated-normal case).

The inflation readout is the argument: mean claimed edge versus the corrected value. **If the corrected number lands near A1's realized return (batch 66), say so** — that is the whole point of the panel, and it is the cleanest available explanation for A14's no-skill finding.

**Keep the caveat card.** The handoff is explicit and it is a real statistical point, not a hedge: rank-based and spread-error diagnostics can misdiagnose reliability, and recent literature argues "underdispersion" is ill-defined when the ensemble mean sits far from climatology. Show all three readings and treat **agreement between them** as the signal, not any one alone. Batch 68 was asked to carry this caveat into its payload definitions; inherit it rather than re-deriving it.

## Process — follow the 29-step implementation workflow (`feedback-implementation-workflow`) exactly, in order

Full 29 steps, no downgrade. Item 1 can change when the bot scans.

(1) Re-verify **row counts first** — this batch's premise is that batch 64 has been writing long enough. Report the counts to the user before building; if item 2's sample is too thin, say so and defer that half rather than shipping a panel that renders noise. (3) `AskUserQuestion` for: whether item 1's availability-trigger ships at all in this batch (**recommend measurement only**); the rank histogram's bin count; and the σ-correction's backtest window. (7) Real mutation-tested tests via Edit-revert with hand-computed expected values. A rank histogram over synthetic members whose ranks you control is easy to pin exactly — do that rather than asserting shape. Pair absence-assertions with positive controls. (8) Scoped: `tests/test_tracker.py`, `tests/test_cron*.py`, `tests/test_web_app.py`, plus the forecasting tests. **Never the full suite.** (9) Lint via the real pre-commit hook. (11) Independent opus review at `effort: high`; if the availability-trigger ships, review the fixes to its findings in a second round too — a scan-scheduling bug is silent and expensive. (13) Address every finding including LOW. (14) Memory before commit. (15) Explicit confirmation before commit/push. (16) `git fetch` + rebase immediately before push.

Full step list: `C:\Users\thesa\.claude\projects\C--Users-thesa-claude-kalshi\memory\feedback_implementation_workflow.md`.
