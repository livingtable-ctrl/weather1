# Batch 63: Design decisions (DESIGN BATCH — opens with AskUserQuestion, not code)

> ## ✅ LANDED 2026-08-25 as `241539d4` — do not re-implement
>
> All three items are done. **The authoritative record is the three resolution
> blocks in `backlog.txt`** (grep the titles below); this file is the frozen
> handoff that led to them, kept for history and corrected in place where it
> turned out to be wrong.
>
> | Item | Decision taken | Outcome |
> |---|---|---|
> | 1 — operator close under a halt | **(a)** new CLI | `py main.py paper close <trade_id> [exit_price]`, plus a top-level `close` alias. Bypasses both gates deliberately; `/api/close-position` unchanged, still 503. |
> | 2 — hurricane_next_event zero rows | **(c)** accept + document | **No code changed.** `config.py`, `trade_cycle.py`'s gates and `_CONDITION_CONFIDENCE` all untouched. |
> | 3 — order-action freshness | soft warn, naming the age, all four actions | `ORDER_STALE_MS = FEED_STALE_MS / 2` for the dashboard's own fetch age, **plus** `SCAN_STALE_MS = 90 min` for the scan age — see the correction under item 3. |
>
> **Two claims in this file were WRONG and are corrected inline below** (search
> for `CORRECTION`): item 1's "no operator path exists" premise, and item 2's
> Recommendation. Both corrections are marked where the original text sits, so
> the original reasoning stays readable.
>
> Three opus review rounds at `effort: high` ran on the implementation. Round 2
> caught a HIGH that round 1's own fix had introduced. Every finding is
> resolved or recorded as an explicit no-op in the backlog resolutions.


## Context

Repo: weather1. Written 2026-08-24 against master `223dedadcfd2` — re-verify current before starting. Source: backlog.txt. **Cited by title, not line number** — `L`-numbers are backlog.txt line offsets and drifted five times during this batch's authoring alone as parallel sessions appended. Grep these titles: `no operator path exists to close an open paper position`, `HURRICANE NEXT-EVENT MODEL LOGS ZERO PREDICTIONS`, `No data-freshness gate on order actions` (re-verified against live code during batch-48's backlog sweep, 2026-08-24).

**Scope changed 2026-08-25:** this batch originally had a fourth item (`PAPER_MIN_EDGE`'s override scale). It has been **reassigned to batch 66**, which owns the edge floor — see the struck-through section below for the reasoning. Do not re-adopt it.

**This batch is shaped like batch 40 and batch 55: it starts with decisions, not implementation.** All three items are genuinely blocked on a judgment call the user has to make — each has at least two defensible answers with different risk profiles, and each entry's own text says so. Picking a default silently is the failure mode this batch exists to prevent.

**Run all three `AskUserQuestion` prompts up front, in one sitting**, then implement. Do not interleave question → implement → question; the user asked for these to be batched specifically so the decisions happen together.

Files touched depend on the answers. Likely: `main.py`, `web_app.py`, `trade_cycle.py`, `weather_markets.py`, `frontend/src/tabs/SignalsTab.jsx`, `frontend/src/tabs/PositionsTab.jsx`, `frontend/src/shared.jsx`. **Not** `config.py` / `param_sweep.py` / `backtest.py` any more — those went with the reassigned item.

**Sequencing update 2026-08-25 — two dependencies are now RESOLVED:**

- **Batch 58 landed** (`320740aa`). Its item 4 set an explicit precedent that item 1 below must reason from rather than re-derive — see the callout inside item 1.
- **Batch 61 landed** (`ebb92599`) and **already built the staleness layer item 3 needs.** Do not build a second one. Reuse:
  - `useData.js` — `mergeFetchedAt(prev, succeeded, now)` (`:490`), which maintains a per-endpoint `next.fetchedAt` map (`:856`).
  - `shared.jsx` — `feedFreshness(fetchedAt, { now, maxAgeMs, since, hardMaxAgeMs })`, `formatFeedAge(ageMs)`, `alarmSafeFlag(value, stale)`, and the `useFeedClock(tickMs)` hook, plus the constants `FEED_STALE_MS` (180 000) and `FEED_HARD_STALE_MS` (4×).

  Note `FEED_STALE_MS` is **180 s**, not the ~90 s item 3 speculates about below. 61 picked that for a *display* banner; item 3 is an *order-submission gate*, which may justify a tighter bound. Treat 180 s as the established precedent to argue against, not as the answer — and if you diverge, say why in the resolution so the two do not silently disagree about what "stale" means.

- Batches **60 and 62 were still in flight** at the time of writing. 60 touches `main.py`'s `cmd_order`/`cmd_today`; neither should collide with this batch, but re-check before starting.

## Items

### 1. No operator path to close a position while the kill switch or TRADING_PAUSED is engaged [backlog: grep `no operator path exists to close an open paper position`]

**Current state (as written, 2026-08-24):** `web_app.py` returns 503 on `_KS_PATH.exists()` or `is_trading_paused()` for `/api/close-position` (still true — that route was deliberately left alone). `git grep close_paper_early` shows no operator CLI command — only automated paths (`cron.py`, `main.py` via `check_model_exits`, `main.py` arb leg). `cron.py` already aborts its whole run under either gate. `undo` only reverses a just-placed trade within a short window, not a general close.

**So right now there is NO operator-facing way to close an open position at all while either gate is engaged.** This matters specifically because closing is a **risk-reducing** action — the opposite of what a kill switch is meant to block. batch-41 correctly added the gate (mirroring `/api/paper-order`'s existing gates per its own directive); this is that fix's side effect, not a defect in it.

> ### ⚠️ CORRECTION (2026-08-25, during implementation) — the premise above is FALSE
>
> **An ungated operator close already existed, and this file misclassifies it as automated.** The `main.py` call site listed above as "via `check_model_exits`" is inside **`cmd_menu`** — the interactive paper submenu, `P` → `4` ("Exit signals"), which prompts *"Close this position now? (y/N)"* per flagged position and calls `close_paper_early` with **no kill-switch and no `TRADING_PAUSED` check**. It is the operator, not an automated loop. Verify with:
> ```
> awk -v L=<line> 'NR<=L && /^def /{l=$0} END{print l}' main.py
> ```
> which prints `def cmd_menu(...)`, not a cron/loop function. (The third site, the arb leg in `_render_analysis_results`, IS automatic — it unwinds a failed second leg — though note it too is only ever reached from an interactive command.) `_cmd_settle_open` (`P` → `3` → `2`) is a second ungated operator path; it settles at an outcome rather than closing at market, but it also removes an open position during a halt.
>
> **So the real starting state was not "no path" but an undesigned, SILENT, partial bypass.** Partial, because the menu prompt only ever offers positions `check_model_exits` flags (model reversed ≥10pp or edge gone, and past `EXIT_MIN_HOLD_HOURS`) and refuses outright without a live realizable quote — so an arbitrary position, or any position during a quote outage, genuinely had no path. Silent, because nothing told the operator a halt was engaged and nothing recorded that one had been bypassed.
>
> That reframes the decision from "should we add a bypass" to "there is already an accidental one — make it deliberate and general, gate it, or bless it". Option (a) was chosen and both halves were done: the new CLI covers any position, and the menu path now announces the bypass and logs it at WARNING. See [[feedback_no_path_exists_check_the_menu]] in project memory for the general lesson.

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

> **DECIDED: (a).** The reconciliation with 58, in short: 58 gates the **bot** — its only caller is `order_executor._exit_live_position`, i.e. automated exit logic deciding on its own to sell, and the kill switch is precisely the instruction "stop deciding things on your own". An operator typing a trade id is not the bot deciding anything, and `pre_live_exit_check`'s own docstring hands this question here by name, saying the answer "must be an explicit operator action, not this gate quietly deciding on their behalf". Two of the four checks 58 kept (prod-ness, `LIVE_TRADING_ENABLED`) are real-money interlocks with no meaning on a paper close anyway. (b) was rejected because a dashboard button is misclickable in a way a typed trade id is not — the deliberateness has to come from the interface. Full reasoning in the backlog resolution.

### ~~REMOVED — `PAPER_MIN_EDGE`'s soft-override scale~~ — reassigned to batch 66 [backlog: grep `PAPER_MIN_EDGE's entire soft-override scale`]

**Moved 2026-08-25.** This item was originally batch 63's, but it is the same question as **batch 66 item 2 (A10, fee-aware edge floor)** approached from a different angle, and both touch `config.py` and the gate that enforces the floor:

- 63 (this item) asked whether the floor's *numeric range* is calibrated to where `net_edge` actually operates.
- 66 item 2 asks whether the floor should be a *function of contract price* rather than flat.

Answering them separately risks a direct conflict — 66 making the floor price-dependent while 63 independently rescales the flat range. **Batch 66 now owns the edge floor entirely**, including this entry's own findings, which are recorded verbatim in that batch file. Leave `config.py`, `param_sweep.py`, and `backtest.py`'s threshold ranges alone in this batch.

If you are running 63 and batch 66 has not landed, that is fine — this is a clean removal, not a blocker. Just do not re-adopt the item.

### 2. Hurricane next-event model logs zero predictions [backlog: grep `HURRICANE NEXT-EVENT MODEL LOGS ZERO PREDICTIONS`]

**Current state (verified):** live `predictions.db` shows `hurricane_next_event` = **0 rows**, while siblings `hurricane_count` = 120 and `storm_order` = 11. Gates unchanged: `trade_cycle.py`'s `mkt_dir < MIN_MARKET_PROB_TO_BET_WITH` gate and the divergence-ratio `continue` immediately after it (both still at ~`:630` as of 2026-08-25); `_CONDITION_CONFIDENCE["hurricane_next_event"] = 0.50` in `weather_markets.py` (drifted from `:9040` to `:9154` — grep the key, not the line).

**Confirmed not a routing/DB bug** — the generic `trade_cycle.py` gates filter every real candidate before it can be logged. The 0.50 confidence constant is doing much of the work.

**The decision** (the entry lists a/b/c and none was taken):
- **(a)** Tune the gate thresholds for this condition type so real candidates survive to shadow-logging.
- **(b)** Raise `_CONDITION_CONFIDENCE` above 0.50 for this family.
- **(c)** Accept that this family produces no signal and retire it.

**Note the tension:** the family cannot graduate without 20 settled shadow predictions, and it cannot accumulate any while the gates filter 100% of candidates — so (c) is the status quo by default. ~~**Recommend (a)** over (b)~~: the confidence constant is a model-quality statement, and raising it to force candidates past a gate conflates "how much do we trust this" with "do we want samples." But this is genuinely the user's call.

> ### ⚠️ CORRECTION (2026-08-25) — this file's Recommendation contradicted the backlog entry, and the backlog won
>
> **DECIDED: (c), accept and document. No code changed.** The recommendation of (a) above was made without weighing the live-traced diagnosis already sitting in the backlog entry itself, which recommends (c) and says outright: *"do NOT change the generic gates to accommodate one model family."* That diagnosis is the more careful document.
>
> The substance: shadow logging exists to score **would-have-traded** candidates, so loosening the gates for one family logs candidates the real placement path would never have taken — contaminating the very calibration sample the 20-settled graduation floor exists to validate against. Buying rows at the cost of the rows meaning anything is a bad trade.
>
> (b) was also confirmed unable to fix this even mechanically: of the two real candidates traced live, only ONE died at the edge floor (where `_CONDITION_CONFIDENCE` applies). The other died at the divergence-ratio gate, which runs **before** tier logic and never consults confidence at all.
>
> The zero-row state is the correct output of gates working as designed on a model whose climatology-only probabilities (0.80–0.99) structurally diverge from Kalshi's pricing of the same contracts (0.25–0.81). The entry's existing "When to revisit" triggers stand unchanged. General lesson: [[feedback_batch_recommendation_vs_backlog_precedent]].

**Related, already fixed:** the wrong-`_date` bug for these tickers (backlog L185) was resolved in batch-51 — so the input data is now correct, which makes this a better moment to revisit than when the entry was filed.

### 3. No data-freshness gate on order actions (Approve / Close) [backlog: grep `No data-freshness gate on order actions`]

**Current state (verified):** `SignalsTab.jsx`'s `handleConfirm` POSTs `buildPaperOrderBody(opp, qty)` with no timestamp check. The only staleness code is a display-only "Last scan" badge (`isStale`) off `signalsMeta.generatedAt` — not a gate. `PositionsTab.jsx`'s `handleBulkClose` and `handleCloseConfirm` submit `exit_price: p.mark` with no freshness check either. (Line numbers removed 2026-08-25: all four drifted during implementation — grep the function names.)

**batch-47's visibility-gated polling made a pre-existing gap materially wider:** polling now pauses entirely while the tab is backgrounded, so an operator returning to a long-backgrounded tab can click Approve/Close against arbitrarily old quotes, before the catch-up fetch (itself ~22 concurrent requests, not instant) resolves.

**Partially mitigated already, do not double-count:** batch-48 made `SignalsTab`'s confirm modal re-derive its opportunity from live data every render (`resolveByKey`), so a poll landing while the modal is open now updates the quoted price. That closes the *stale-modal* half. It does **not** close this one — the underlying `M.opportunities` can itself be minutes old, and `PositionsTab`'s close path was not touched.

**The decisions (three, ask together):**
- **Threshold:** what age counts as stale? Batch 61 already established `FEED_STALE_MS = 180_000` for display; the question is whether an order gate should be tighter, and if so, why.
- **Block vs. warn:** hard-disable the button with a "refreshing…" state, or allow submission behind an explicit confirm naming the age?
- **Scope:** which actions — Approve (SignalsTab), Close (PositionsTab), bulk variants of both, and does RiskTab have any order-adjacent control that qualifies?

**Recommend: soft-warn with the age named, covering Approve + Close + both bulk paths** (threshold per the note above). A hard block on a paper-trading dashboard risks trapping an operator who *needs* to act on a stale quote (the same trap item 1 is about), while an explicit "this quote is 4 minutes old" confirm gives them the information without removing the capability. Revisit toward hard-block if/when live trading is enabled.

**Reuse, don't reinvent — batch 61 already built this.** It landed in `ebb92599`; see the Sequencing note at the top of this file for the full API (`mergeFetchedAt`, `feedFreshness`, `formatFeedAge`, `alarmSafeFlag`, `useFeedClock`, `FEED_STALE_MS`). Building a second staleness path would give the dashboard two disagreeing definitions of "stale."

**One real tension to resolve:** 61 set `FEED_STALE_MS = 180_000` (3 minutes) for a *display* banner. The ~90 s floated above was an inference from the 60 s poll interval, made before 61 existed. An order-submission gate may warrant tighter than a banner — but if you pick a different number, make it a deliberate, stated divergence rather than an accidental second constant.

> ### ✅ DECIDED — and the framing above was incomplete in one important way
>
> **Threshold:** `ORDER_STALE_MS = FEED_STALE_MS / 2` (90 s), written as a division rather than as `90_000` so the divergence is structural and the two constants cannot drift apart. Rationale: the cost profile inverts between the two surfaces — a spurious *banner* alarm is expensive and being 30 s late to say "feed down" costs nothing, whereas a spurious "95 s old" line on a confirm dialog costs one glance and a **missed** stale quote books a mispriced trade.
>
> **Block vs warn:** soft warn, naming the age. A hard block would trap an operator who needs to act on a stale quote — the same trap item 1 exists to undo.
>
> **Scope:** all four — Approve, bulk Approve, Close, bulk Close. Verified complete: RiskTab has no POST at all, and SettingsTab's only POST is configuration.
>
> **What this section did not anticipate: ONE threshold is not enough.** The framing above treats "staleness" as a single quantity, but a fresh *poll* is not a fresh *price* — `/api/live_signals` serves `signals_cache.json` for up to **four hours** with a normal 200, and `/api/trades` serves SSE-snapshot fallback quotes that look live whenever the Kalshi batch-fetch fails. So the gate ended up combining independent ages and warning on the worst, and it needed a **second, scan-appropriate constant**: `SCAN_STALE_MS = 90 min` (the threshold SignalsTab's "Last scan" header chip already used, now read from one shared constant).
>
> That second constant is not a nicety. Gating the scan age at the 90-second order threshold — which is what the first implementation did, reading this section literally — would have made the Approve warning fire on **every click forever**, because cron runs every three hours. An opus review caught it as a HIGH before it shipped. If you are reading this section for a similar feature elsewhere: match each threshold to the cadence of the thing it measures, and ask what fraction of *normal* operation trips your warning.
>
> Also fixed while here, both pre-dating this batch: batch-61's `useFeedClock` singleton froze once its last subscriber unmounted (so RiskTab's kill-switch checklist read a dead feed as fresh after a tab switch), and `/api/trades` gained a `quote_is_live` field so the frontend can tell a live book price from the snapshot fallback.

## Process (as instructed; this is what was followed — see the LANDED banner at the top)

**Start with all three `AskUserQuestion` prompts before writing any code.** Keep each question terse — state the decision in one sentence and push the caveats into the option descriptions. Item 3 is really three sub-decisions (threshold, block-vs-warn, scope) — ask them together rather than as three separate prompts.

Ceremony after the decisions land: **items 1 and 3 get full 29-step ceremony with opus review at `effort: high`** (kill-switch semantics on a position-closing path; a gate on order submission). Item 2 gets full ceremony if the answer is (a) or (b) — it changes trade-entry gating — and is a documentation-only close if (c).

A "no change needed" outcome is a legitimate result for item 2, but it must be an explicit, reasoned, recorded decision — never a silent drop because the investigation was inconclusive.

Tests: whatever the answers require. Frontend work: `cd frontend && npm test`, extract decision logic into `frontend/src/shared.jsx` as pure functions so it is unit-testable (no jsdom/RTL in this repo), and rebuild `static/dist` in the same commit. Python: scope narrowly, grep `tests/` for changed function names. **Never run the bare full suite.**

Lint via the real pre-commit hook. Update ~~all 4~~ **all 3** backlog entries with the decision made and its reasoning — for this batch the *reasoning* is the durable artifact, more than the diff. Run `python backlog_index.py`, confirm before committing. ("4" was left over from before the `PAPER_MIN_EDGE` item was reassigned to batch 66; this batch owns three entries.)

**What actually happened, 2026-08-25.** All five decisions (item 1, item 2, and item 3's three sub-decisions) were taken up front in one sitting across two `AskUserQuestion` calls, then implemented. Items 1 and 3 got the full ceremony; item 2 was a documentation-only close, so its "no change needed" outcome is recorded as an explicit reasoned decision in its backlog entry rather than dropped. Three opus review rounds ran, not one — the second reviewed the first round's fixes and found a HIGH they had introduced, and the third reviewed those. Two deviations from the instructions above, both deliberate and stated in the resolutions: item 3 needed one additive line in `web_app.py` (`quote_is_live`) despite being scoped frontend-only, because that was the only honest way to distinguish a live book price from the snapshot fallback; and the `graphify-out/` refresh (step 29) was skipped after a scoped merge lost 620 edges net — the graph is stale for this change by design.
