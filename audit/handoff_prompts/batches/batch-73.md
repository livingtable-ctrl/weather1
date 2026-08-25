# Batch 73: A8 replay harness + A17 resting orders — the only batch that can lose money if half-built

## Context

Repo: weather1. Written 2026-08-24 against master `a67a21a6` — **re-verify current before starting** (`git fetch` + `git log origin/master`). Live trading is dormant (`LIVE_TRADING_ENABLED` unset), and **item 2 must stay behind paper mode regardless.**

Source: Weather V3 additions handoff (A8, A17), re-planned in **Backend Build Order** — https://claude.ai/code/artifact/dc35c571-4d3d-4771-b7f1-95518032a010. See [INDEX-PANEL-BACKENDS.md](INDEX-PANEL-BACKENDS.md).

Files owned: `order_executor.py`, `paper.py`, `tracker.py` (scratch ledger + working-orders state), `web_app.py`.

**Prerequisites:** [batch 72](batch-72.md) (A17's counterfactuals replay stored books), [batch 67](batch-67.md) (A8 shares price reconstruction with A11), and **[batch 66](batch-66.md)'s answer** — both items here are machinery for collecting edge more efficiently, and A14 measured no forecast skill. If batch 66 finds no edge in the traded tail either, raise that with the user before starting rather than building on an assumption.

**Coordination:** `order_executor.py` is also touched by batch 64 item 1 (`_current_forecast_cycle`, ~3,000 lines from this batch's region). Rebase onto 64; it is the smaller diff.

## Items

### 1. A8 [LARGE]: no way to know what a threshold change would have done

**Files:** `order_executor.py` / `paper.py` (the existing sizing and filter code), `tracker.py` (scratch ledger), `web_app.py`.

**The single hard rule, from the handoff:** replay stored scan history through the **existing** sizing and filter code with an injected config. *"Do not fork the logic — if replay and live diverge the numbers are fiction."* A forked replay path is worse than no replay panel, because it produces confident numbers that describe code nobody runs.

**Replay must write nothing to the paper ledger.** A scratch ledger only. `paper_trades.json` also stores its own content checksum — a stray write invalidates it and the loader crashes on next load.

**Fix direction:** parameterise the existing sizing/filter path so a config can be injected without duplicating it, replay stored scan history, and write results to a scratch ledger. Report trades taken, win rate, net P&L, max drawdown, capture ratio, and Brier.

**Keep the Brier row and keep it muted.** The handoff is precise about why: Brier is a property of the forecast, not the filter, so it is the **control** — if a replay moves it, the replay is wrong. That row is the harness's own self-test; do not drop it as redundant.

Also carry the fill-assumption caveat and the date before which book depth was not snapshotted (batch 64 item 4 / batch 72 started that clock — replay before it cannot model fills honestly).

### 2. A17 [MEDIUM — SMALLER THAN THE HANDOFF CLAIMS, BUT THE MOST DANGEROUS]

**Files:** `kalshi_client.py` (read — the API is already there), `order_executor.py`, `paper.py`, `tracker.py`, `web_app.py`.

**The handoff calls this "genuinely new plumbing" and puts it last. The plumbing already exists:** `place_order`, `place_maker_order`, `cancel_order`, `get_open_orders`, `get_order_queue_position`, `amend_order` are all in `kalshi_client.py` — including queue position, which the working-orders table needs. Verify each before designing, but scope this as *use the existing API* rather than *build an order layer*.

What is genuinely missing: the **auto-cancel conditions per resting order**, partial-fill reconciliation, and the open-orders poll wired into the cycle.

**The handoff's warning is the important part and it is not boilerplate:**

> A resting order with no armed cancel condition is adverse selection: it fills precisely when someone knows more than you.

That is the failure mode. A resting order is not a cheaper entry — it is a free option written to a better-informed counterparty, and it gets exercised exactly when the market has moved against you. Every resting order must have an armed cancel condition **before** it is placed, not after.

**Fix direction:** working-orders state (ticker, resting price, best bid, queue position, P(fill), age, and its auto-cancel condition), an open-orders poll, and partial-fill reconciliation. The policy the handoff describes — rest above a high edge threshold, escalate to crossing N hours before close, **cancel everything before each model cycle publishes and repost after** — depends on batch 71's real cycle timestamps; if those are not landed, the cancel-before-cycle rule cannot be implemented correctly and should be deferred rather than approximated on the wall clock.

**Ship behind paper-trading mode and leave it there until the fill statistics match the replay.** That is the handoff's explicit instruction and this batch must not relax it.

## Process — follow the 29-step implementation workflow (`feedback-implementation-workflow`) exactly, in order

Full 29 steps, no downgrade, and treat this as the highest-ceremony batch in the set — it is the one the handoff singles out as able to lose money if half-built.

(1) Re-verify every `kalshi_client.py` method named above actually exists with the signature assumed, and re-read `paper.py`'s ledger-write path before item 1. (3) `AskUserQuestion` for: how config injection is threaded into the existing sizing path without forking it (the central design decision of item 1); the auto-cancel condition set; and whether the cancel-before-cycle rule ships at all given batch 71's state. Equal visibility. (7) Real mutation-tested tests via Edit-revert, not string-replace. For item 2 specifically: **mock only values the real Kalshi API actually returns** — its order-status vocabulary is `resting`/`canceled`/`executed`, and a previous round of work in this repo shipped a bug precisely because a test mocked a plausible-but-fictional `"filled"`. Pair every absence-assertion with a positive control. Test that an order cannot be placed without an armed cancel condition, and that partial fills reconcile to the right position size. (8) Scoped: `tests/test_order_executor.py`, `tests/test_paper.py`, `tests/test_kalshi_client.py`, `tests/test_trading_gates.py`, `tests/test_web_app.py`. **Never the full suite.** (9) Lint via the real pre-commit hook. (11) Independent opus review at `effort: high`, then a **second round reviewing the fixes to its findings** — mandatory here, not optional; this is exactly the shape of change where round-1 fixes have introduced new severe bugs in this repo before. (13) Address every finding including LOW. (14) Memory before commit. (15) Explicit confirmation before commit/push. (16) `git fetch` + rebase immediately before push.

**Acceptance for item 2:** do not consider it done because tests pass. It is done when paper-mode fill statistics match the replay's predictions over a real sample. Until then it stays behind paper mode, and that is a reporting obligation to the user, not a judgement call for the implementing session.

Full step list: `C:\Users\thesa\.claude\projects\C--Users-thesa-claude-kalshi\memory\feedback_implementation_workflow.md`.
