# Batch 63: Design decisions (DESIGN BATCH — opens with AskUserQuestion, not code)

## Context

Repo: weather1. Written 2026-08-24 against master `223dedadcfd2` — re-verify current before starting. Source: backlog.txt. **Cited by title, not line number** — `L`-numbers are backlog.txt line offsets and drifted five times during this batch's authoring alone as parallel sessions appended. Grep these titles: `no operator path exists to close an open paper position`, `HURRICANE NEXT-EVENT MODEL LOGS ZERO PREDICTIONS`, `No data-freshness gate on order actions` (re-verified against live code during batch-48's backlog sweep, 2026-08-24).

**Scope changed 2026-08-25:** this batch originally had a fourth item (`PAPER_MIN_EDGE`'s override scale). It has been **reassigned to batch 66**, which owns the edge floor — see the struck-through section below for the reasoning. Do not re-adopt it.

**This batch is shaped like batch 40 and batch 55: it starts with decisions, not implementation.** All three items are genuinely blocked on a judgment call the user has to make — each has at least two defensible answers with different risk profiles, and each entry's own text says so. Picking a default silently is the failure mode this batch exists to prevent.

**Run all three `AskUserQuestion` prompts up front, in one sitting**, then implement. Do not interleave question → implement → question; the user asked for these to be batched specifically so the decisions happen together.

Files touched depend on the answers. Likely: `main.py`, `web_app.py`, `trade_cycle.py`, `weather_markets.py`, `frontend/src/tabs/SignalsTab.jsx`, `frontend/src/tabs/PositionsTab.jsx`, `frontend/src/shared.jsx`. **Not** `config.py` / `param_sweep.py` / `backtest.py` any more — those went with the reassigned item.

**Sequencing update 2026-08-25:** **batch 58 has landed** (`320740aa`) and its item 4 set an explicit precedent that item 1 below must now reason from rather than re-derive — see the callout inside item 1. Batches **60, 61, 62 were still in flight** at the time of writing; item 3 wants a `fetchedAt` staleness primitive that batch 61's item 3 was likely to introduce, so **check whether 61 landed and reuse its primitive** rather than building a second one. If it did not, build one in the shape batch-48 used for `stats.hours_since_cron` and say so in the resolution.

## Items

### 1. No operator path to close a position while the kill switch or TRADING_PAUSED is engaged [backlog: grep `no operator path exists to close an open paper position`]

**Current state (verified):** `web_app.py:3251-3256` returns 503 on `_KS_PATH.exists()` or `is_trading_paused()` for `/api/close-position`. `git grep close_paper_early` shows no operator CLI command — only automated paths (`cron.py:2503`, `main.py:9434` via `check_model_exits`, `main.py:2461` arb leg). `cron.py` already aborts its whole run under either gate. `undo` only reverses a just-placed trade within a short window, not a general close.

**So right now there is NO operator-facing way to close an open position at all while either gate is engaged.** This matters specifically because closing is a **risk-reducing** action — the opposite of what a kill switch is meant to block. batch-41 correctly added the gate (mirroring `/api/paper-order`'s existing gates per its own directive); this is that fix's side effect, not a defect in it.

**The decision:**
- **(a)** New `main.py close <trade_id> [exit_price]` CLI that bypasses both gates — closing is not a live-order-placement action, so the `LiveTradingGate` reasoning that blocks new orders arguably does not apply.
- **(b)** Carve out `/api/close-position`'s gate with an explicit justification (e.g. only block when `manual=false` and a live quote exists — a kill-switch scenario is exactly when an operator may need to exit at a stale/manual price).
- **(c)** Keep current behavior; document that halting also freezes exits, and accept it.

**Original recommendation was (a)** — it restores the capability without weakening the web route's gate, and a CLI action is inherently deliberate (an operator typing a trade id is not going to fat-finger it the way a dashboard button can be misclicked). **That recommendation predates batch 58's decision — read the callout immediately below before acting on it.** It is no longer a clean recommendation; 58 landed a stance that (a) would partly contradict.

#### Batch 58 has LANDED and set a precedent — read this before deciding [updated 2026-08-25]

Batch 58's item 4 answered the live-side version of this question, merged as `320740aa`. Do not re-derive it; reason **from** it.

**What 58 decided.** It made the code match `_exit_live_position`'s docstring by adding `trading_gates.pre_live_exit_check` (`trading_gates.py:182`), a reduced gate for risk-REDUCING orders. It shares `LiveTradingGate._check_never_skippable` (`trading_gates.py:17`) with the full gate, deliberately, so the two cannot drift apart.

| | checked by the exit gate? |
|---|---|
| `TRADING_PAUSED` | **yes** |
| kill switch (`data/.kill_switch`) | **yes** |
| prod-ness (client `base_url`, else `KALSHI_ENV`) | **yes** |
| `LIVE_TRADING_ENABLED` | **yes** |
| `is_paused_drawdown`, `is_streak_paused`, `is_daily_loss_halted`, `is_accuracy_halted`, `graduation_check` | **no** |

**The stated principle:** every gate it dropped "exists to SIZE OR STOP NEW exposure. An exit removes exposure, so blocking it on a risk limit is backwards." Every gate it kept is either an operator "touch nothing" instruction or a real-money interlock — reasoning that does not depend on how much risk is already open.

**Why that does not simply settle this item, and is the crux of the decision:**

1. **58 deliberately KEPT the kill switch blocking exits.** Option (a) above — a CLI that bypasses both gates — therefore goes *further* than 58 was willing to go on the higher-stakes live path. Adopting (a) without argument would leave the codebase asserting two incompatible things about what a kill switch means.
2. **Different surface, lower stakes.** This item is about closing **paper** positions via `/api/close-position`; 58's item 4 was the **live** exchange path. The "exits reduce risk" principle transfers cleanly, but a paper close touches no real money, so two of the four gates 58 kept (prod-ness, `LIVE_TRADING_ENABLED`) are not even meaningful here. The only gates actually in question for paper are TRADING_PAUSED and the kill switch.

**Reframe the decision accordingly.** The honest question is no longer "should closing bypass the kill switch" in the abstract — it is: *given that 58 established the kill switch as a never-skippable operator instruction even for risk-reducing live orders, does the same hold for a paper position where no real money moves?* A defensible answer either way, but it must engage with 58's precedent explicitly rather than deciding in isolation.

If you land option (a) or (b), say in the resolution how it reconciles with `pre_live_exit_check`'s stance. If the answer is (c), note that it now has 58's precedent actively supporting it, which it did not when this batch was written.

### ~~REMOVED — `PAPER_MIN_EDGE`'s soft-override scale~~ — reassigned to batch 66 [backlog: grep `PAPER_MIN_EDGE's entire soft-override scale`]

**Moved 2026-08-25.** This item was originally batch 63's, but it is the same question as **batch 66 item 2 (A10, fee-aware edge floor)** approached from a different angle, and both touch `config.py` and the gate that enforces the floor:

- 63 (this item) asked whether the floor's *numeric range* is calibrated to where `net_edge` actually operates.
- 66 item 2 asks whether the floor should be a *function of contract price* rather than flat.

Answering them separately risks a direct conflict — 66 making the floor price-dependent while 63 independently rescales the flat range. **Batch 66 now owns the edge floor entirely**, including this entry's own findings, which are recorded verbatim in that batch file. Leave `config.py`, `param_sweep.py`, and `backtest.py`'s threshold ranges alone in this batch.

If you are running 63 and batch 66 has not landed, that is fine — this is a clean removal, not a blocker. Just do not re-adopt the item.

### 2. Hurricane next-event model logs zero predictions [backlog: grep `HURRICANE NEXT-EVENT MODEL LOGS ZERO PREDICTIONS`]

**Current state (verified):** live `predictions.db` shows `hurricane_next_event` = **0 rows**, while siblings `hurricane_count` = 120 and `storm_order` = 11. Gates unchanged: `trade_cycle.py:630` (`mkt_dir < MIN_MARKET_PROB_TO_BET_WITH`) and `:633` (divergence-ratio `continue`); `_CONDITION_CONFIDENCE["hurricane_next_event"] = 0.50` at `weather_markets.py:9040`.

**Confirmed not a routing/DB bug** — the generic `trade_cycle.py` gates filter every real candidate before it can be logged. The 0.50 confidence constant is doing much of the work.

**The decision** (the entry lists a/b/c and none was taken):
- **(a)** Tune the gate thresholds for this condition type so real candidates survive to shadow-logging.
- **(b)** Raise `_CONDITION_CONFIDENCE` above 0.50 for this family.
- **(c)** Accept that this family produces no signal and retire it.

**Note the tension:** the family cannot graduate without 20 settled shadow predictions, and it cannot accumulate any while the gates filter 100% of candidates — so (c) is the status quo by default. **Recommend (a)** over (b): the confidence constant is a model-quality statement, and raising it to force candidates past a gate conflates "how much do we trust this" with "do we want samples." But this is genuinely the user's call.

**Related, already fixed:** the wrong-`_date` bug for these tickers (backlog L185) was resolved in batch-51 — so the input data is now correct, which makes this a better moment to revisit than when the entry was filed.

### 3. No data-freshness gate on order actions (Approve / Close) [backlog: grep `No data-freshness gate on order actions`]

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

**Start with all three `AskUserQuestion` prompts before writing any code.** Keep each question terse — state the decision in one sentence and push the caveats into the option descriptions. Item 3 is really three sub-decisions (threshold, block-vs-warn, scope) — ask them together rather than as three separate prompts.

Ceremony after the decisions land: **items 1 and 3 get full 29-step ceremony with opus review at `effort: high`** (kill-switch semantics on a position-closing path; a gate on order submission). Item 2 gets full ceremony if the answer is (a) or (b) — it changes trade-entry gating — and is a documentation-only close if (c).

A "no change needed" outcome is a legitimate result for item 2, but it must be an explicit, reasoned, recorded decision — never a silent drop because the investigation was inconclusive.

Tests: whatever the answers require. Frontend work: `cd frontend && npm test`, extract decision logic into `frontend/src/shared.jsx` as pure functions so it is unit-testable (no jsdom/RTL in this repo), and rebuild `static/dist` in the same commit. Python: scope narrowly, grep `tests/` for changed function names. **Never run the bare full suite.**

Lint via the real pre-commit hook. Update all 4 backlog entries with the decision made and its reasoning — for this batch the *reasoning* is the durable artifact, more than the diff. Run `python backlog_index.py`, confirm before committing.
