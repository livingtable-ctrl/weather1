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
| A6 | needs channels, rules, delivery log | `notify.py` already has five channels + cooldown state; only rules/eval/deliveries are missing |
| A15 | the only new persistence in the eighteen | `ensemble_member_scores` exists, but per-**model**, not per-**member** — the rank histogram still needs member-level data |
| A18 | three of four timestamps already in logs | `forecast_cycle` is stored but `order_executor._current_forecast_cycle()` derives it from the wall clock (`12 if now.hour >= 12 else 0`), not the run's real time. The panel's core input does not exist |
| A4 | needs order-book depth | `get_orderbook()` exists; `kalshi_ws` stores `orderbook_delta` without ever applying it to a depth structure |
| A10 | fee assumed `p(1-p)`-shaped, decimals to re-derive | only a flat `KALSHI_FEE_RATE=0.07` in `config.py`; the whole premise needs confirming against Kalshi's published schedule |

**Commit prerequisite:** these batch files must be committed to master before parallel worktree sessions start — worktrees can't see the main clone's uncommitted files.

## Batch 64 comes first, and the reason is calendar not dependency

Batch 64 lands four **forward-only writers**. They collect data that cannot be backfilled — A15's rank histogram in particular starts its sample clock the day member values first persist. Every day 64 is not running is a day permanently missing from batches 70 and 71.

64 is small, pure backend, and conflicts with nothing in the frontend. **Run it first even if nothing else starts.**

## Parallel structure

| Track | Batches | Files owned | Parallel-safe with |
|---|---|---|---|
| **W — Writers** | [64](batch-64.md) | `order_executor.py`, `kalshi_ws.py`, `paper.py`, `tracker.py` **(migrations + writers only)**, forecast-fetch call sites in `weather_markets.py` | A, B (see tracker.py note) |
| **A — Analytics on existing data** | [65](batch-65.md), [66](batch-66.md), [67](batch-67.md) | `tracker.py` **(new query functions only)**, `web_app.py` **(new endpoints only)**, `config.py` (66 only), `weather_markets.py` gate-count + CDF regions (65/67) | each other, W, B |
| **B — Audits & independent** | [68](batch-68.md), [69](batch-69.md) | `settlement_monitor.py`, `metar.py` (68); `notify.py`, `cron.py`, `alerts.py` (69) | everything |
| **C — Blocked on track W** | [70](batch-70.md), [71](batch-71.md) | `tracker.py` query functions, `web_app.py` endpoints | each other |
| **D — New pipelines** | [72](batch-72.md), [73](batch-73.md), [74](batch-74.md) | `kalshi_client.py`, `kalshi_ws.py` (72); `order_executor.py`, `paper.py` (73); new module + `metar.py` (74) | see collisions below |

### tracker.py and web_app.py are shared by almost everything

Batches 64-67 and 70-71 all append to `tracker.py` and `web_app.py`. They are declared parallel-safe anyway, on the same basis as batches 49-52's `weather_markets.py` note: the work is **purely additive** — new functions appended near their subject-matter siblings, new routes appended to the `/api/analytics` reflection tuple — so textual conflicts should be zero and whichever lands second rebases.

**Two exceptions where that is not true and coordination is required:**

1. **`tracker.py`'s `_MIGRATIONS` list is a single ordered array.** Batch 64 adds migrations (member values, forecast history). Batch 72 adds one (depth snapshots). If both are in flight, the second to land **must** rebase and re-number rather than hand-merging conflict markers, and must re-run `init_db()` against a scratch DB to confirm the migration chain still applies cleanly from an empty file. `_SCHEMA_VERSION` must be bumped to match the list length.
2. **`web_app.py`'s `/api/analytics` reflection tuple** is one literal. Several batches add a name to it. Same rule: rebase, don't hand-merge.

### Collision notes

- **72 and 64 both touch `kalshi_ws.py`.** 64 does not — it only reads the cache. If 72's depth work starts before 64 lands, no conflict; they are separate concerns in the same file. Declared safe, rebase if `git diff` shows anything unexpected.
- **73 (A17) and 64 both touch `order_executor.py`.** 64 changes `_current_forecast_cycle()` only; 73 works in the order-placement path. Different regions, ~3,000 lines apart. Safe, but 73 should rebase onto 64 rather than the reverse — 64 is the smaller diff.
- **74 (A9) and 68 (A13) both touch `metar.py`.** 68 is a read-only audit that should end in a report and, at most, a comment change; 74 adds intraday polling. Run 68 first — its findings may change what 74's "high so far" is allowed to trust.

## Sequencing

1. **[64](batch-64.md) immediately.** Sample clocks. Nothing else has a decaying value.
2. **[66](batch-66.md) next, then [65](batch-65.md).** See the finding below — 66 answers whether the rest is worth building.
3. **[68](batch-68.md)** any time; it is half a day and either confirms every calibration number above it or invalidates them.
4. **[65](batch-65.md), [67](batch-67.md), [69](batch-69.md)** in parallel, any order.
5. **[70](batch-70.md), [71](batch-71.md)** once 64 has been writing long enough to have rows. 71's A15b half needs months, not days — check row counts before starting rather than assuming.
6. **[72](batch-72.md), [73](batch-73.md), [74](batch-74.md)** last, and only after step 2's answer. See below.

## The A14 finding should reorder your priorities

A14 exists to say whether there is edge to harvest before more is built. It returned **no measurable skill**: model Brier 0.2596 against the market's 0.2201 and climatology's 0.2482 on 214 filtered settled rows; paired t = 2.59, bootstrap P(model worse) = 0.9965; and t = 0.69 against a flat 0.50 forecast, i.e. indistinguishable from a coin flip.

Batches 72-74 (A4, A8, A17, A9) are largely machinery for **collecting** edge more efficiently. Funding them before knowing whether edge exists in the tail actually traded is expensive.

Batch 66 is the cheap answer: it adds `min_edge` conditioning to the already-shipped `get_model_vs_market_brier()` and builds A1's P&L-side read. **Run 66 before committing to track D**, and treat its result as a go/no-go on batches 72-74 rather than a formality.

The open backlog entry *"MEASURE BRIER SKILL CONDITIONED ON THE SIZE OF OUR DISAGREEMENT WITH THE PRICE"* (`BACKLOG_OPEN.md`) is batch 66's item 1.

## Not batched

- **A14** — built, `7f0acc7a`.
- **Frontend for all eighteen panels** — separate work stream. Note the handoff's rule that semantic colours stay literal hex is now **wrong**: batch-46 promoted them to theme tokens (`--pos`/`--neg`/`--warn`/`--accent`), and following the handoff literally would regress dark mode.
- **Kalshi fee-schedule confirmation** — an external lookup, not code. It gates batch 66's item 2; do it before that batch starts, not during.
