# Batch 66: Is there edge at all — conditional Brier, fee-aware floor, edge attribution (GO/NO-GO for track D)

## Context

Repo: weather1. Written 2026-08-24 against master `a67a21a6` — **re-verify current before starting** (`git fetch` + `git log origin/master`). Live trading dormant. Items 1 and 3 are read-only analytics. **Item 2 changes a live gate** — read its warning.

Source: Weather V3 additions handoff (A1, A10) plus the open backlog entry *"MEASURE BRIER SKILL CONDITIONED ON THE SIZE OF OUR DISAGREEMENT WITH THE PRICE"*. Re-planned in **Backend Build Order** — https://claude.ai/code/artifact/dc35c571-4d3d-4771-b7f1-95518032a010. See [INDEX-PANEL-BACKENDS.md](INDEX-PANEL-BACKENDS.md).

Files owned: `tracker.py` (new query functions; **item 1 modifies the existing `get_model_vs_market_brier`**), `web_app.py` (new endpoints), `config.py` + `param_sweep.py` + `backtest.py` + wherever the edge floor is enforced (item 2 — `param_sweep.py`/`backtest.py` added 2026-08-25 with the L28655 reassignment, see item 2), `shared.jsx` is **out of scope** — no frontend in this batch.

**Run this batch before committing to batches 72-74.** A14 (`7f0acc7a`) already measured no forecast skill: model Brier 0.2596 vs the market's 0.2201 vs climatology's 0.2482 on 214 filtered settled rows, paired t = 2.59, bootstrap P(model worse) = 0.9965, and t = 0.69 against a flat 0.50 forecast. Track D is largely machinery for *collecting* edge more efficiently. This batch decides whether that machinery has anything to collect. Treat item 1's answer as a genuine go/no-go, not a formality.

## Items

### 1. Conditional Brier skill [HIGH]: the existing measurement cannot see the tail we actually trade

**Files:** `tracker.py` — `get_model_vs_market_brier()`, `_brier_series_stats()`, `_paired_advantage()` (all shipped in `7f0acc7a`).

The A14 statistic is **unconditional on the size of our disagreement with the price**. Every market where our probability broadly agreed with the mid contributes near-nothing to the model-minus-market difference and pulls the pooled figure toward zero. Trading edge, if it exists, lives specifically in the subset where the disagreement was large enough to act on — the subset the pooled number structurally cannot isolate.

So the measured −0.179 is consistent with real edge on the traded tail, and a positive pooled skill would have been consistent with none there. This is recorded as an open backlog entry and as a docstring caveat on the function itself; do not let either be dropped when editing.

**Fix direction:** add an optional `min_edge` parameter and return a second series conditioned on `abs(our_prob - market_prob) >= min_edge`, at the edge floor the scanner actually uses. Report `n` and `n_markets` beside it — the tail will be small. **Gate any conclusion on the same paired significance test the policy label already uses** (`_paired_advantage`, beat both market and leave-one-out climatology by more than `BRIER_POLICY_Z` standard errors), not on a raw threshold: a fixed threshold on a small tail is exactly the defect an opus review already caught once in this function, where an `n>=100` floor emitted "trade" on ~22% of pure-noise samples at this bot's real disagreement level (`sd(our_prob - market_prob) = 0.22`).

Two confounders stay unresolved and must remain stated rather than quietly fixed: the population is self-selected (only markets the scanner analysed; `is_shadow=0` only those it chose to trade), and Brier measures calibration, not P&L. Item 3 is the P&L half.

### 2. A10 [MEDIUM — TOUCHES A LIVE GATE]: a flat 6% edge floor is not the same threshold at 20¢ as at 80¢

**Files:** `config.py:259` (`KALSHI_FEE_RATE`, default `0.07`), `config.py:270` (`min_edge`, default `0.07`), the gate that enforces the floor, and `sideAwareEntryPrice`'s server-side counterpart.

Only a **flat rate constant** exists today. There is no per-price fee function anywhere. The handoff's own arithmetic assumes a `p(1−p)`-shaped per-contract fee and says explicitly: *"Confirm the current fee schedule and rounding against Kalshi's published rules before shipping. The shape of the argument holds regardless, the decimals must be re-derived."*

**Do the external confirmation before writing code, not during.** If Kalshi's published schedule cannot be confirmed, stop and surface that rather than shipping a plausible formula — a wrong fee function applied in the gate changes which trades are allowed.

**This is the one item in batches 64-71 that alters live behaviour.** Everything else is additive observation. Applying a price-dependent floor in the gate will reject trades the current flat floor accepts.

**Fix direction:** express the required gross edge as a function of contract price, put it beside the existing sizing helpers, and apply it in the gate **behind a setting defaulted off** until item 3 can measure its effect — the same discipline the handoff prescribes for A5's Kelly correlation adjustment. Ship the function and the display first; flipping the gate on is a separate, deliberate decision with the user.

#### Reassigned in 2026-08-25: this item now also owns backlog entry L28655

Batch 63 originally carried L28655 (*"`PAPER_MIN_EDGE`'s entire soft-override scale may be set below `net_edge`'s real operating floor, making the edge gate a near no-op"*). It was moved here because it is the same question from a different angle — 63 asked whether the floor's *numeric range* is calibrated, this item asks whether the floor should be *price-dependent* — and answering them in separate batches risked a direct conflict in `config.py` and the gate.

**Two concrete findings from that entry, verified 2026-08-24, to fold into this item:**

1. **The three declared ranges disagree with each other today.** `config.py:224` validates `0.03 <= opt <= 0.15`; `param_sweep.py:123` validates the same `0.03..0.15` — but `run_sweep`'s own candidate list at `param_sweep.py:167` is `[0.15…0.40]`, and `backtest.py:931` uses `THRESHOLDS = [0.04…0.10]`. So the sweep validates a range it then never explores, and the backtest explores a third. That is a bug independent of whatever fee-shaped floor you land on, and it means any historical sweep/backtest conclusion about the floor was drawn over a range disconnected from the live gate.

2. **The premise needs testing before the fix.** The live gate reads `opp.get("net_edge")` at `order_executor.py:3317`. Query the real distribution of `net_edge` on settled predictions — median, quartiles, and what fraction of real candidates clear 0.03 / 0.10 / 0.15 — before assuming the floor binds at all. "Disproven, the range is fine" is a perfectly good result; record it and close L28655.

That distribution is worth having regardless: it is the same population this batch's item 1 conditions on, so pull it once and use it for both.

**Also update `backlog.txt` L28655's resolution when this item lands** — it is currently tagged OPEN with no note that batch 66 owns it.

### 3. A1 [MEDIUM]: nothing measures whether the claimed edge is the edge collected

**Files:** `tracker.py` (new query function), `web_app.py`.

*Have:* `net_edge`, `entry_price`, `pnl`, `cost` on every settled trade. *Also have, contrary to the handoff:* mid-price at entry is recoverable from `price_history` (schema v37 — per-ticker 1-minute OHLC with `yes_bid_close`/`yes_ask_close`, backfilled across each market's whole life at settlement), so the drift-versus-spread split does **not** require A4's new series. *Genuinely need:* the fee charged per fill, which is item 2's function.

Capture ratio is the OLS slope of realized return regressed on claimed edge. Suppress the whole panel below roughly 30 settled trades and always report `n`.

**Fix direction:** capture ratio plus the waterfall components (gross forecast edge → market drift → spread paid → exchange fees → realized P&L), bucketed by claimed edge. Acceptance, from the handoff: **a slope near 1.0 must be as legible as a slope of 0.37** — do not build a payload that only makes sense when the answer is bad. Same rule as A14's: if the result is unflattering, say so plainly rather than burying it.

## Process — follow the 29-step implementation workflow (`feedback-implementation-workflow`) exactly, in order

Full 29 steps, no downgrade. Item 2 touches a gate that decides which trades are permitted.

(1) Re-verify: read `get_model_vs_market_brier()` as it actually stands before editing — it has been through two opus review rounds and its docstring caveats are load-bearing. (3) `AskUserQuestion` for: which `min_edge` value(s) to condition on; whether item 2's fee function ships gate-applied or display-only (**recommend display-only + setting-defaulted-off**); and item 3's suppression floor. Equal visibility for all three. (7) Real, mutation-tested tests via Edit-revert, not string-replace. `tests/test_model_vs_market_brier.py` is the pattern — hand-computed expected values in comments, positive controls paired with every absence-assertion, and a test that pins any sign convention (a sign inversion in `_paired_advantage` shipped once and survived the whole suite until pinned directly). For item 2, mock values the real fee schedule actually produces, not internally-plausible ones. (8) Scoped: `tests/test_model_vs_market_brier.py`, `tests/test_tracker.py`, `tests/test_trading_gates.py`, `tests/test_web_app.py`, plus whatever covers the edge floor. **Never the full suite.** (9) Lint via the real pre-commit hook. (11) Independent opus review at `effort: high` — and because item 2 touches a gate, review the fixes to its findings too, in a second round. (13) Address every finding including LOW. (14) Memory before commit. (15) Explicit confirmation before commit/push. (16) `git fetch` + rebase immediately before push.

**Report item 1's result to the user explicitly before starting track D.** That is this batch's actual deliverable; the code is how you get it.

Full step list: `C:\Users\thesa\.claude\projects\C--Users-thesa-claude-kalshi\memory\feedback_implementation_workflow.md`.
