# Batch 63: Design decisions (DESIGN BATCH — opens with AskUserQuestion, not code)

## Context

Repo: weather1. Written 2026-08-24 against master `223dedadcfd2` — re-verify current before starting. Source: backlog.txt L30045, L28655, L30612, L30876 (re-verified against live code during batch-48's backlog sweep, 2026-08-24).

**This batch is shaped like batch 40 and batch 55: it starts with decisions, not implementation.** All four items are genuinely blocked on a judgment call the user has to make — each has at least two defensible answers with different risk profiles, and each entry's own text says so. Picking a default silently is the failure mode this batch exists to prevent.

**Run all four `AskUserQuestion` prompts up front, in one sitting**, then implement. Do not interleave question → implement → question; the user asked for these to be batched specifically so the decisions happen together.

Files touched depend on the answers. Likely: `main.py`, `web_app.py`, `config.py`, `param_sweep.py`, `backtest.py`, `trade_cycle.py`, `frontend/src/tabs/SignalsTab.jsx`, `frontend/src/tabs/PositionsTab.jsx`, `frontend/src/shared.jsx`.

**Sequencing:** run **after** batches 58, 60, 61 where possible — item 1 shares design ground with batch 58's item 4, and item 4 wants a `fetchedAt` primitive that batch 61's item 3 is likely to introduce. If those have not landed, this batch has to build the primitive itself; say which happened.

## Items

### 1. No operator path to close a position while the kill switch or TRADING_PAUSED is engaged [L30045]

**Current state (verified):** `web_app.py:3251-3256` returns 503 on `_KS_PATH.exists()` or `is_trading_paused()` for `/api/close-position`. `git grep close_paper_early` shows no operator CLI command — only automated paths (`cron.py:2503`, `main.py:9434` via `check_model_exits`, `main.py:2461` arb leg). `cron.py` already aborts its whole run under either gate. `undo` only reverses a just-placed trade within a short window, not a general close.

**So right now there is NO operator-facing way to close an open position at all while either gate is engaged.** This matters specifically because closing is a **risk-reducing** action — the opposite of what a kill switch is meant to block. batch-41 correctly added the gate (mirroring `/api/paper-order`'s existing gates per its own directive); this is that fix's side effect, not a defect in it.

**The decision:**
- **(a)** New `main.py close <trade_id> [exit_price]` CLI that bypasses both gates — closing is not a live-order-placement action, so the `LiveTradingGate` reasoning that blocks new orders arguably does not apply.
- **(b)** Carve out `/api/close-position`'s gate with an explicit justification (e.g. only block when `manual=false` and a live quote exists — a kill-switch scenario is exactly when an operator may need to exit at a stale/manual price).
- **(c)** Keep current behavior; document that halting also freezes exits, and accept it.

**Recommend (a)** — it restores the capability without weakening the web route's gate, and a CLI action is inherently deliberate (an operator typing a trade id is not going to fat-finger it the way a dashboard button can be misclicked). But (b) is defensible if dashboard-only operation matters more.

**Coordinate with batch 58 item 4**, which is the same question one layer down (`_exit_live_position`'s gate contradicts its own docstring). Whichever batch runs first sets the precedent; the second should inherit it, not re-decide.

### 2. `PAPER_MIN_EDGE`'s soft-override scale may sit below `net_edge`'s real operating floor [L28655]

**Current state (verified):** `config.py:224` validates `0.03 <= float(opt) <= 0.15`; `param_sweep.py:123` validates the same `0.03..0.15` — but `run_sweep`'s own candidate list at `param_sweep.py:167` is `[0.15…0.40]`; `backtest.py:931` uses `THRESHOLDS = [0.04…0.10]`. The live gate reads `opp.get("net_edge")` at `order_executor.py:3317`.

**The concern:** if the whole 0.03-0.15 scale sits below where `net_edge` actually operates, the edge gate is a near no-op — it would pass essentially everything, and the sweep/backtest tooling would be exploring a range disconnected from the live threshold.

**This needs an investigation before it needs a decision.** Query the real distribution of `net_edge` on settled predictions and report: median, quartiles, and what fraction of real candidates clear 0.03 / 0.10 / 0.15. **Bring that data to the AskUserQuestion, not a guess** — the entry is phrased as "may be," and the honest first output of this item is either "confirmed, the gate is inert" or "disproven, the range is fine." A disproof is a perfectly good result; record it and close the entry.

**If confirmed**, the decision is where the floor should actually sit, and whether `param_sweep`'s validation range (0.03-0.15) or its candidate list (0.15-0.40) is the one that is wrong — they currently disagree with each other, which is its own bug regardless of the answer.

### 3. Hurricane next-event model logs zero predictions [L30612]

**Current state (verified):** live `predictions.db` shows `hurricane_next_event` = **0 rows**, while siblings `hurricane_count` = 120 and `storm_order` = 11. Gates unchanged: `trade_cycle.py:630` (`mkt_dir < MIN_MARKET_PROB_TO_BET_WITH`) and `:633` (divergence-ratio `continue`); `_CONDITION_CONFIDENCE["hurricane_next_event"] = 0.50` at `weather_markets.py:9040`.

**Confirmed not a routing/DB bug** — the generic `trade_cycle.py` gates filter every real candidate before it can be logged. The 0.50 confidence constant is doing much of the work.

**The decision** (the entry lists a/b/c and none was taken):
- **(a)** Tune the gate thresholds for this condition type so real candidates survive to shadow-logging.
- **(b)** Raise `_CONDITION_CONFIDENCE` above 0.50 for this family.
- **(c)** Accept that this family produces no signal and retire it.

**Note the tension:** the family cannot graduate without 20 settled shadow predictions, and it cannot accumulate any while the gates filter 100% of candidates — so (c) is the status quo by default. **Recommend (a)** over (b): the confidence constant is a model-quality statement, and raising it to force candidates past a gate conflates "how much do we trust this" with "do we want samples." But this is genuinely the user's call.

**Related, already fixed:** the wrong-`_date` bug for these tickers (backlog L185) was resolved in batch-51 — so the input data is now correct, which makes this a better moment to revisit than when the entry was filed.

### 4. No data-freshness gate on order actions (Approve / Close) [L30876]

**Current state (verified):** `SignalsTab.jsx`'s `handleConfirm` (~`:200-207`) POSTs `buildPaperOrderBody(opp, qty)` with no timestamp check. The only staleness code is a display-only "Last scan" badge (`isStale`, ~`:577`) off `signalsMeta.generatedAt` — not a gate. `PositionsTab.jsx:153-156` and `:233` submit `exit_price: p.mark` with no freshness check either.

**batch-47's visibility-gated polling made a pre-existing gap materially wider:** polling now pauses entirely while the tab is backgrounded, so an operator returning to a long-backgrounded tab can click Approve/Close against arbitrarily old quotes, before the catch-up fetch (itself ~22 concurrent requests, not instant) resolves.

**Partially mitigated already, do not double-count:** batch-48 made `SignalsTab`'s confirm modal re-derive its opportunity from live data every render (`resolveByKey`), so a poll landing while the modal is open now updates the quoted price. That closes the *stale-modal* half. It does **not** close this one — the underlying `M.opportunities` can itself be minutes old, and `PositionsTab`'s close path was not touched.

**The decisions (three, ask together):**
- **Threshold:** what age counts as stale? The 60s main-poll interval suggests ~90s, but that is an inference, not a measurement.
- **Block vs. warn:** hard-disable the button with a "refreshing…" state, or allow submission behind an explicit confirm naming the age?
- **Scope:** which actions — Approve (SignalsTab), Close (PositionsTab), bulk variants of both, and does RiskTab have any order-adjacent control that qualifies?

**Recommend: soft-warn with the age named, ~90s, covering Approve + Close + both bulk paths.** A hard block on a paper-trading dashboard risks trapping an operator who *needs* to act on a stale quote (the same trap item 1 is about), while an explicit "this quote is 4 minutes old" confirm gives them the information without removing the capability. Revisit toward hard-block if/when live trading is enabled.

**Reuse, don't reinvent:** if batch 61 item 3 landed a `fetchedAt` staleness primitive in `useData.js`, build on it. If not, build one here in the same shape batch-48 used for `stats.hours_since_cron`, and say so in the resolution so batch 61 can adopt it.

## Process

**Start with all four `AskUserQuestion` prompts before writing any code.** Keep each question terse — state the decision in one sentence and push the caveats into the option descriptions. Item 2's question must carry the real `net_edge` distribution data with it (see that item).

Ceremony after the decisions land: **items 1 and 4 get full 29-step ceremony with opus review at `effort: high`** (kill-switch semantics on a position-closing path; a gate on order submission). Item 3 gets full ceremony if the answer is (a) or (b) — it changes trade-entry gating — and is a documentation-only close if (c). Item 2 is investigation-first; ceremony depends entirely on whether the investigation confirms a real problem.

A "no change needed" outcome is a legitimate result for items 2 and 3, but it must be an explicit, reasoned, recorded decision per item — never a silent drop because the investigation was inconclusive.

Tests: whatever the answers require. Frontend work: `cd frontend && npm test`, extract decision logic into `frontend/src/shared.jsx` as pure functions so it is unit-testable (no jsdom/RTL in this repo), and rebuild `static/dist` in the same commit. Python: scope narrowly, grep `tests/` for changed function names. **Never run the bare full suite.**

Lint via the real pre-commit hook. Update all 4 backlog entries with the decision made and its reasoning — for this batch the *reasoning* is the durable artifact, more than the diff. Run `python backlog_index.py`, confirm before committing.
