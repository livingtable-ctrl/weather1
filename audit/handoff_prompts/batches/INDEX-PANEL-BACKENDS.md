# Panel-backend batches — batches 64-74

> **See also [INDEX-BACKLOG-CLEANUP.md](INDEX-BACKLOG-CLEANUP.md) (57-63) and [INDEX-ROADMAP.md](INDEX-ROADMAP.md) (49-56).** No overlap: 57-63 fix existing code, 49-56 add new market families, 64-74 build the backends for the eighteen proposed console panels.

Source: the **Weather V3 additions design handoff** (`design_handoff_weather_v3_additions/README.md`, panels A1-A18), re-planned as **Backend Build Order** — https://claude.ai/code/artifact/dc35c571-4d3d-4771-b7f1-95518032a010. Written against `master @ a67a21a6` — **re-verify current before starting** (`git fetch` + `git log origin/master`).

**A14 is already built** (`7f0acc7a`): `tracker.get_model_vs_market_brier()` + `_brier_series_stats()` + `_paired_advantage()`, served in `/api/analytics` as `model_vs_market_brier`. These eleven batches cover the remaining seventeen panels plus four data writers.

**These batches are backend only.** No frontend work is included — none of the eighteen panels has any UI yet, and the frontend is a separate work stream. Every batch ends at a tested endpoint or query function.

## Read this before planning any of it

**The design handoff's effort estimates are stale in both directions.** It was written against tree `923ebe5c`, 31 commits back, and nine of its claims are wrong. Each batch below states what was verified present in master; do not re-derive scope from the handoff's own text without checking:

| Panel | Handoff claimed | Verified in master |
|---|---|---|
| A17 | "genuinely new plumbing", build last | `place_order`, `place_maker_order`, `cancel_order`, `get_open_orders`, `get_order_queue_position`, `amend_order` all exist in `kalshi_client.py` |
| A13 | ⚠ BUILD FIRST, blocks six panels | `tracker.audit_settlement` already reads Kalshi's settled CLI figure once `status="finalized"`, explicitly replacing the METAR proxy. Remaining work is an audit, not a pipeline |
| A11 | needs the price series A4 introduces | `price_history` (schema v37) already stores per-ticker 1-minute OHLC with `yes_bid_close`/`yes_ask_close` across each market's full life |
| A3 | the only genuinely new forecast pipeline | `get_forecast_run_trend()` exists; `run_trend_points` and `blend_sources` already persisted per prediction |
| A6 | needs channels, rules, delivery log | `notify.py` already has five channels + cooldown state; only rules/eval/deliveries are missing. **Shipped in batch 69.** Also found: of the six "baseline rules to ship with", `kill_switch` and `brier_two_weeks` were ALREADY alerting from `cron.py`, so batch 69's versions share those cooldown keys rather than double-sending |
| A5 | "positions are grouped by nothing today" | **Wrong** — `paper._CORRELATED_CITY_GROUPS`, `get_correlated_exposure()`, `MAX_CORRELATED_EXPOSURE`, `_CITY_PAIR_CORR`, `covariance_kelly_scale()` and `corr_kelly_scale()` all exist and are live in Kelly sizing. The real gaps, shipped in batch 69, were (a) no cap on exposure aggregated across all cities settling on ONE date, and (b) the correlation matrix being 32 hand-typed guesses covering 32 of 190 pairs. Measured against 30y ACIS: `Atlanta-NewOrleans` is +0.63 but unlisted (sizing sees 0.10), `Atlanta-Miami` is hardcoded 0.50 but measures +0.18, and nearly every pair is far more correlated in January than July — a single year-round number cannot represent it |
| A15 | the only new persistence in the eighteen | `ensemble_member_scores` exists, but per-**model**, not per-**member** — the rank histogram still needs member-level data |
| A18 | three of four timestamps already in logs | `forecast_cycle` is stored but `order_executor._current_forecast_cycle()` derives it from the wall clock (`12 if now.hour >= 12 else 0`), not the run's real time. The panel's core input does not exist |
| A4 | needs order-book depth | `get_orderbook()` exists; `kalshi_ws` stores `orderbook_delta` without ever applying it to a depth structure |
| A10 | fee assumed `p(1-p)`-shaped, decimals to re-derive | only a flat `KALSHI_FEE_RATE=0.07` in `config.py`; the whole premise needs confirming against Kalshi's published schedule |

**Commit prerequisite:** these batch files must be committed to master before parallel worktree sessions start — worktrees can't see the main clone's uncommitted files.

## Batch 64 is DONE — the sample clocks are running

Landed 2026-08-25 (schema **v67**). The four writers and where their data goes:

| Item | Where it lands | Notes for the consuming batch |
|---|---|---|
| W1 run init | `predictions.forecast_run_inits` | JSON `{model: iso8601}`, **not** a scalar — the models genuinely disagree (verified live: two blend models on 00z while `ecmwf_aifs025_ensemble` was on the previous day's 18z). Collapse it however A18 needs. `forecast_cycle` is untouched and still the wall-clock order-dedup key. |
| W2 members | `ensemble_member_values` | One row per (city, model, target_date, var, cycle), members as a JSON array. Values are **raw** — pre-bias-correction and pre-weight-replication. |
| W3 exclusions | `predictions.blend_exclusions` | JSON `{source: reason}`; reasons are `unavailable`, `zero_weight`, `circuit_open`. The complement of `blend_sources`. |
| W4 depth | `orderbook_depth_snapshots` | Throttled per ticker via `DEPTH_SNAPSHOT_INTERVAL_SECS` (default 60s). New accessor `kalshi_ws.get_cached_depth()`; `get_cached_book()` is unchanged. |

**Three corrections batches 70/71 must not re-inherit from the design handoff:**

1. **Open-Meteo does NOT return a model-run timestamp in its forecast response.** Batch-64's own text said it did and told the implementer to "thread it through rather than re-requesting" — that is not possible. Probed live against both `api.open-meteo.com/v1/forecast` and `ensemble-api.open-meteo.com/v1/ensemble`: the only top-level time field is `generationtime_ms`, which is server processing time. The real value lives at `/data/<dataset>/static/meta.json` as `last_run_initialisation_time`, on a **separate** endpoint keyed by dataset name — and the bot's model aliases are not dataset names (`icon_seamless` and `gfs_seamless` both 500; they map to `dwd_icon_eps` and `ncep_gefs025`). See `weather_markets._MODEL_RUN_META_NAMES`.
2. **`n_members` is not a member count.** `get_ensemble_temps()`/`batch_prewarm_ensemble()` replicate each model's members `repeats` times to express blend weights, so stored values read 138/238/258. A rank histogram built on it would be weight-distorted. Use `ensemble_member_values` instead.
3. **`forecast_run_inits` is only populated when a fetch was actually observed.** An all-cache-hit scan records nothing rather than guessing a run time — that is deliberate, and 71 should filter on presence rather than assume every row has it.

**Check real row counts before starting 70/71** rather than assuming a rate — A15b's half needs months, not days.

## Parallel structure

| Track | Batches | Files owned | Parallel-safe with |
|---|---|---|---|
| **W — Writers** ✅ done | [64](batch-64.md) | `order_executor.py`, `kalshi_ws.py`, `paper.py`, `tracker.py` **(migrations + writers only)**, forecast-fetch call sites in `weather_markets.py` | A, B (see tracker.py note) |
| **A — Analytics on existing data** | [65](batch-65.md), [66](batch-66.md), [67](batch-67.md) | `tracker.py` **(new query functions only)**, `web_app.py` **(new endpoints only)**, `config.py` (66 only), `weather_markets.py` gate-count + CDF regions (65/67) | each other, W, B |
| **B — Audits & independent** | [68](batch-68.md), ~~[69](batch-69.md)~~ ✅ | `settlement_monitor.py`, `metar.py` (68); `notify.py`, `cron.py`, `alerts.py`, plus `tracker.py` (3 migrations, v61→v64), `web_app.py` (5 routes), 2 `main.py` dispatch lines and a new `acis_temps.py` (69, landed) | everything |
| **C — Blocked on track W** | [70](batch-70.md), [71](batch-71.md) | `tracker.py` query functions, `web_app.py` endpoints | each other |
| **D — New pipelines** | [72](batch-72.md), [73](batch-73.md), [74](batch-74.md) | `kalshi_client.py`, `kalshi_ws.py` (72); `order_executor.py`, `paper.py` (73); new module + `metar.py` (74) | see collisions below |

### tracker.py and web_app.py are shared by almost everything

Batches 64-67 and 70-71 all append to `tracker.py` and `web_app.py`. They are declared parallel-safe anyway, on the same basis as batches 49-52's `weather_markets.py` note: the work is **purely additive** — new functions appended near their subject-matter siblings, new routes appended to the `/api/analytics` reflection tuple — so textual conflicts should be zero and whichever lands second rebases.

**Two exceptions where that is not true and coordination is required:**

1. **`tracker.py`'s `_MIGRATIONS` list is a single ordered array.** Batch 64 has landed and grew it from 61 to **67** entries (`_SCHEMA_VERSION = 67`). Batch 72 adds one (depth snapshots) — note 64 already created `orderbook_depth_snapshots`, so check whether 72's migration is still needed at all before adding a duplicate. If both are in flight, the second to land **must** rebase and re-number rather than hand-merging conflict markers, and must re-run `init_db()` against a scratch DB to confirm the migration chain still applies cleanly from an empty file. `_SCHEMA_VERSION` must be bumped to match the list length.
2. **`web_app.py`'s `/api/analytics` reflection tuple** is one literal. Several batches add a name to it. Same rule: rebase, don't hand-merge.

### Collision notes

- **72 and 64 both touch `kalshi_ws.py`.** 64 does not — it only reads the cache. If 72's depth work starts before 64 lands, no conflict; they are separate concerns in the same file. Declared safe, rebase if `git diff` shows anything unexpected.
- **73 (A17) and 64 both touch `order_executor.py`.** 64 changes `_current_forecast_cycle()` only; 73 works in the order-placement path. Different regions, ~3,000 lines apart. Safe, but 73 should rebase onto 64 rather than the reverse — 64 is the smaller diff.
- **74 (A9) and 68 (A13) both touch `metar.py`.** 68 is a read-only audit that should end in a report and, at most, a comment change; 74 adds intraday polling. Run 68 first — its findings may change what 74's "high so far" is allowed to trust.

## Sequencing

1. ~~**[64](batch-64.md) immediately.**~~ ✅ **Done 2026-08-25** — schema v67. Sample clocks are running.
2. **[66](batch-66.md) next, then [65](batch-65.md).** See the finding below — 66 answers whether the rest is worth building.
3. ~~**[68](batch-68.md)** any time; it is half a day and either confirms every calibration number above it or invalidates them.~~ ✅ **DONE 2026-08-25.** It confirmed them: every calibration number is scored against `outcomes.settled_yes`, which is Kalshi's own `result` read only at `status="finalized"` and no earlier than 1h past close. **No regrade.** It did find two derived-path defects and fixed both — see the `A13 SETTLEMENT-SOURCE AUDIT` entry in `backlog.txt`. **Batch 74 (A9) inherits one rule from it:** METAR is a legitimate pre-settlement *trading signal* (that is all `settlement_monitor.py` and `_metar_lock_in` ever use it for) but is NOT a settlement source for any market family this bot trades — not even the hourly ones, which settle on The Weather Company and the Kalshi Weather Index. A9's "high so far" may gate an exit; it may never be written anywhere a grading consumer reads.
4. **[65](batch-65.md), [67](batch-67.md)** in parallel, any order. ~~69~~ ✅ landed 2026-08-25 — see the completion table in [INDEX.md](INDEX.md); its alert engine and `cron_gap` scheduler entry are both deliberately dormant pending an operator action.
5. **[70](batch-70.md), [71](batch-71.md)** once 64 has been writing long enough to have rows. 71's A15b half needs months, not days — check row counts before starting rather than assuming.
6. **[72](batch-72.md), [73](batch-73.md), [74](batch-74.md)** last, and only after step 2's answer. See below.

## The A14 finding should reorder your priorities

A14 exists to say whether there is edge to harvest before more is built. It returned **no measurable skill**: model Brier 0.2596 against the market's 0.2201 and climatology's 0.2482 on 214 filtered settled rows; paired t = 2.59, bootstrap P(model worse) = 0.9965; and t = 0.69 against a flat 0.50 forecast, i.e. indistinguishable from a coin flip.

Batches 72-74 (A4, A8, A17, A9) are largely machinery for **collecting** edge more efficiently. Funding them before knowing whether edge exists in the tail actually traded is expensive.

Batch 66 is the cheap answer: it adds `min_edge` conditioning to the already-shipped `get_model_vs_market_brier()` and builds A1's P&L-side read. **Run 66 before committing to track D**, and treat its result as a go/no-go on batches 72-74 rather than a formality.

> ### ⛔ 66 has now run. The verdict is NO-GO for 72-74 (2026-08-25).
>
> Conditioning did not rescue the pooled number — it made it worse, monotonically.
> On the same 214 filtered settled rows (the pooled figures reproduce A14 exactly):
> skill −0.179 pooled, −0.233 at |disagreement| ≥ 0.20, −0.349 at ≥ 0.25, −0.431 at
> ≥ 0.30. Model Brier *rises* with disagreement (0.2596 → 0.2864 → 0.3105) while the
> market's stays flat near 0.220 — we are most wrong exactly where we disagree most.
> The paired advantage never turns positive at any rung.
>
> A second finding makes the exercise nearly moot: **the population is already the
> tail.** 100% of settled rows clear the 0.07 live floor and 96.3% clear 0.15 (p10 of
> disagreement = 0.1556). The scanner only logs candidates that already passed its own
> edge bar, so the low-disagreement rows this section assumed were diluting the
> statistic largely do not exist in the table.
>
> Item 3's P&L-side read agrees rather than rescuing it, and is worse: capture ratio
> **0.378**, intercept −0.197, over **243** settled trades, with a mean realized return
> of **−0.040** per dollar of cost and three of four claimed-edge buckets negative.
> What positive return exists comes overwhelmingly from post-entry market drift
> (+0.0668 per dollar of cost) rather than settlement surprise (+0.0162). (A first
> pass reported 0.519/203 — that filter dropped all 40 `early_exit` rows, the
> stop-lossed losers; opus review caught it.)
>
> **Do not start 72-74 without an explicit user decision to override this.** 64-65 and
> 67-71 are unaffected — they observe existing data and several are prerequisites for
> ever re-measuring this.
>
> Also corrected while running 66: this file's A11 row calls `price_history`
> "1-minute OHLC". It is **60-minute** candles (`period_interval = 60`, rows 3600s
> apart). A10's row is also wrong that "only a flat `KALSHI_FEE_RATE=0.07`" exists —
> `utils._kalshi_fee`/`kalshi_taker_fee`/`kalshi_maker_fee` have implemented the
> curved `P(1-P)` form since batch-22, verified against Kalshi's published schedule
> on 2026-07-12 and re-confirmed against the exchange's own `/series` metadata on
> 2026-08-25 (`fee_type: "quadratic"`, `fee_multiplier: 1` for KXHIGH*).

The open backlog entry *"MEASURE BRIER SKILL CONDITIONED ON THE SIZE OF OUR DISAGREEMENT WITH THE PRICE"* (`BACKLOG_OPEN.md`) is batch 66's item 1.

## Not batched

- **A14** — built, `7f0acc7a`.
- **Frontend for all eighteen panels** — separate work stream. Note the handoff's rule that semantic colours stay literal hex is now **wrong**: batch-46 promoted them to theme tokens (`--pos`/`--neg`/`--warn`/`--accent`), and following the handoff literally would regress dark mode.
- **Kalshi fee-schedule confirmation** — an external lookup, not code. It gates batch 66's item 2; do it before that batch starts, not during.
