# New-Capability Discovery Scan — 2026-08-09

**Scope.** A systematic hunt for *new capability* across the whole program — exchange/data-source surface the codebase doesn't use, infrastructure already built for one purpose that could cheaply serve a second, and market/product surface Kalshi exposes that the bot doesn't touch. Explicitly **not** a bug hunt (this project has a separate full-file correctness-review convention) and **not** incremental refinement of things already heavily tracked in `backlog.txt`.

**Baseline.** Worktree off `origin/master` @ `efd11f3`, clean. 50 root modules / 58,591 lines. Deduplicated against all 26 open `BACKLOG_OPEN.md` entries (full entry text read for every near-miss, not just the one-liner) and against `[RESOLVED]`/`[CLOSED]`/`[PARTIALLY RESOLVED]` entries near each topic. Also deduplicated against already-shipped-but-non-obvious functionality by grepping each capability under several plausible names before calling it missing.

**Method.** Seven parallel read-only subsystem scans (exchange integration, data ingestion, market analysis/pricing, execution/risk, orchestration, monitoring/ops, analysis tooling), then **every finding below re-verified personally against the source** — subagent claims alone were not treated as sufficient grounding. External claims were verified with live, read-only, unauthenticated `GET`s against `api.elections.kalshi.com/trade-api/v2` where possible; where a live probe failed or wasn't possible, that is stated explicitly. Anything that could not be confirmed was dropped rather than caveated.

**Labels.** `INTERNAL` = grounded in a file/line or an API response this codebase already receives. `EXTERNAL` = inspired by outside research; grounding is a docs page or a live probe, and the internal verification still needed is stated per finding.

---

## Section 1 — INTERNAL findings

### F1. Kalshi publishes its own settled value on every settled temperature market, and the daily-temperature path ignores it

**INTERNAL.**

`audit_settlement()` writes `outcomes.settled_temp_f` — the ground truth behind every forecast-error statistic the bot could compute — from an **IEM ASOS raw-hourly-METAR archive** proxy (`tracker.py:3855-3870`, `_fetch_asos_daily_temp`), falling back to Open-Meteo gridded reanalysis when no station is mapped. Its own docstring says this is the wrong source:

> `tracker.py:3603-3611` — *"this is NOT the same source Kalshi actually settles on. Kalshi's rules_primary text states settlement uses the NWS Daily Climatological Report (CLI product), which is compiled/rounded differently and can legitimately disagree with raw ASOS METAR extremes by ~1 degree near a threshold (confirmed 2026-07-05 on KXLOWTMIN-26JUN28-T66 …)"*

Meanwhile the **same function already reads Kalshi's own settled value** — but only on two branches: monthly rain (`tracker.py:3651-3690`, `market.get("expiration_value")`) and monthly snow (`tracker.py:3700-3733`, identical block). The daily-temperature branch never touches `expiration_value`.

Live verification (unauthenticated, one call per series, no pagination needed):

| Series | settled markets returned | distinct settlement days | `expiration_value` populated | window |
|---|---|---|---|---|
| KXHIGHNY | 462 | 77 | 461 | 2026-05-25 → 2026-08-09 |
| KXLOWTNYC | 462 | 77 | 462 | same |
| KXHIGHLAX | 462 | 77 | 462 | same |
| KXHIGHTPHX | 462 | 77 | 462 | same |
| KXLOWTMIA | 462 | 77 | 456 | same |
| KXHIGHTSEA | 462 | 77 | 462 | same |

Sample (`GET /markets?series_ticker=KXHIGHNY&status=settled`), event `KXHIGHNY-26JUL31`: every market in the ladder carries `expiration_value: "85.00"` plus `settlement_ts: 2026-08-01T12:01:10Z`. That is Kalshi's own CLI-report figure — the exact number it settled on, not a proxy.

**Why this isn't already tracked.** Open entry **L9261 `DATA-DRIVEN SIGMA FROM SETTLED HISTORY + CLI-REPORT SETTLEMENT FETCH`** is the right neighbour, and this is a **materially cheaper new angle on it, not a new entry**. That entry proposes building a CLI-report fetch via the IEM afos API with a hand-maintained city→WFO/pil table (and flags "the known per-city hardcoded-table risk"). It is blocked on data volume: re-verified 2026-07-20, *"max per-city-per-season count is 21 (Seattle, summer) … 234 settled_temp_f rows total."* Its own floor is ~30/season. Reading `expiration_value` instead (a) removes the WFO/pil table entirely, (b) is the exact field the codebase already parses twice, and (c) yields **~77 settlement days × 40 daily temperature series ≈ 3,000 (city, date, var) ground-truth points in one backfill pass** — clearing L9261's floor immediately rather than waiting months. Not covered by any other open entry; grepped `expiration_value` / `settled_temp_f` / `settlement_value` before concluding.

**Cheap vs. build.** Nearly all cheap. `expiration_value` parsing exists verbatim at `tracker.py:3662-3675`; the settled-market bulk fetch pattern exists at `weather_markets.py:9022-9024` (`get_markets(series_ticker=…, status="settled")`); `backfill_price_history` (`tracker.py:4655`) is a working precedent for a one-off historical backfill command. What's new: a daily-temperature branch in `audit_settlement` and a backfill command.

**Priority: High.** The cost of not having it is that every empirical sigma, EMOS fit, and forecast-error statistic the bot will ever compute is calibrated against a source Kalshi does not settle on, and the one feature blocked on that data (L9261) stays blocked for months on a sample floor that a single API pass would clear today.

---

### F2. Temperature market direction is inferred from free-text titles; Kalshi's own `strike_type`/`floor_strike`/`cap_strike` are never read for temperature

**INTERNAL.**

`_parse_market_condition`'s temperature branch (`weather_markets.py:5671-5735`) extracts `-T##`/`-B##.#` from the ticker, then resolves *direction* purely by substring-matching `">"`/`"above"`/`"<"`/`"below"` against `title`, then against `subtitle`+`yes_sub_title`, and **fails closed with a warning** if neither matches (`5724-5735`).

The same function already reads Kalshi's structured fields on every other market family: rain at `5488/5495`, snow at `5532/5539`, hurricane-count at `4790-4816`. `cap_strike` has **zero** references repo-wide (`grep --include=*.py`, including tests). So does `rules_primary` as a dict read — it appears only in five prose comments.

Live-verified against the real `KXHIGHNY-26AUG09` ladder:

```
KXHIGHNY-26AUG09-T90    strike_type=less      floor=None  cap=90    "89° or below"
KXHIGHNY-26AUG09-T97    strike_type=greater   floor=97    cap=None  "98° or above"
KXHIGHNY-26AUG09-B90.5  strike_type=between   floor=90    cap=91    "90° to 91°"
```

and `rules_primary` on the same markets carries the settlement source verbatim:

> *"If the highest temperature recorded in **Central Park, New York** for August 09, 2026 as reported by the **National Weather Service's Climatological Report (Daily)**, is less than 90°, then the market resolves to Yes."*

Two distinct capabilities here:

1. **Structured direction/bounds.** `strike_type` + `floor_strike`/`cap_strike` are the authoritative, machine-readable form of what the parser currently guesses from prose. Today a Kalshi copy change to subtitle wording silently drops the market (fail-closed skip, `5735`).
2. **Machine-readable settlement provenance.** `rules_primary` names the station and product per market; the event object's `settlement_sources` gives the literal URL (`[{"name": "NWS Climatological Report", "url": "https://forecast.weather.gov/product.php?site=OKX&product=CLI&issuedby=NYC"}]`). Today `metar.MARKET_STATION_MAP` (`metar.py:325-350`) and `nws_afd.CITY_WFO_OFFICE` (`nws_afd.py:85-107`) are hand-maintained tables asserting the same facts.

**Not a bug report.** The `-B` band is `val ± 1.0` (`weather_markets.py:5687`), which for `-B90.5` gives `[89.5, 91.5]` vs Kalshi's real `floor=90, cap=91` — **equivalent** for integer-reported settlement, so there is no live discrepancy. The finding is that the structured fields exist and are unused, not that the current parse is wrong.

**Why this isn't already tracked.** No open entry covers reading `strike_type`/`cap_strike`/`rules_primary` on temperature markets. `consistency.py:74-84` documents that direction *cannot* be inferred from a series prefix and that the T-suffix number is not the semantic strike — but reaches for text, not the structured fields. Grepped `strike_type`, `cap_strike`, `floor_strike`, `rules_primary`, `rules_secondary`, `settlement_sources` across the repo.

**Cheap vs. build.** Cheap — the read pattern is copy-paste from the rain branch (`5486-5517`). Item 2 (validating the station tables against `rules_primary`/`settlement_sources`) is new but small, and pairs naturally with F1.

**Priority: Medium-High.** Cost of not having it: a fragile text dependency on Kalshi's marketing copy for the single most safety-critical parse in the program (which side of the threshold we are betting), plus two hand-maintained station tables with no automated cross-check against Kalshi's own stated settlement source.

---

### F3. `consistency.py` parses between-buckets and then drops them — no between arbitrage, no above/below complementarity, no HIGH↔LOW join

**INTERNAL.**

`_parse_threshold` returns `("between", val)` for any `-B##.#` ticker (`consistency.py:97`), and `_group_markets` appends those entries to the group (`consistency.py:355-357`). But `find_violations` builds exactly two lists:

```python
consistency.py:386-395
above = [... if ct == "above" and p > 0]
below = [... if ct == "below" and p > 0]
```

**Every `between` entry falls through both comprehensions and is compared against nothing.** Concretely, three gaps:

- **No between-bucket check at all.** Between-buckets are the most numerous temperature market type (acknowledged at `weather_markets.py:11045-11046`); the real `KXHIGHNY-26AUG09` ladder is 4 between + 2 tails. There is no check that a date's between prices sum to ≈1, and no check that a between bucket is consistent with the above/below rungs bracketing it.
- **Above and below never meet.** The two loops (`consistency.py:399`, `:439`) are fully independent — no complementarity check (`P(high > 89) + P(high ≤ 89) ≈ 1`) even though a real series contains both.
- **HIGH and LOW never meet.** The group key is `(series, date_str)` where series is `ticker.split("-")[0]` (`consistency.py:349`), so `KXHIGHNY-26AUG09-*` and `KXLOWTNYC-26AUG09-*` are always in different groups.

**Why this isn't already tracked — and the correct, cheaper framing.** Open entry **L6088 `RAIN ARBITRAGE-CHECK SHADOW SIGNAL HAS NO GRADUATION DECISION YET`** is adjacent but is *not* this: read in full, it is about deciding whether to flip `is_shadow=False` for the already-shipped rain monotonicity check. Temperature arbitrage detection is already live and auto-placing (`main.py:1955-1971`, gated by `MIN_ARB_EDGE`, per-leg volume, a $25/city cap, and `LiveTradingGate`). So the real finding is **"extend the existing, already-live temperature arbitrage checker to the market shape it currently ignores"** — not "build cross-market arbitrage." That is a materially smaller scope than a from-scratch build: the grouping, the edge computation from real bid/ask (`consistency.py:421`, `:449`), the one-sided-book guard (`:418-419`), the shadow flag, the >5-violation circuit breaker (`trade_cycle.py:294-300`), the two-leg placement with leg-1 unwind (`main.py:1972-2009`), and the display path all exist.

**Cheap vs. build.** Cheap for the arithmetic (a bucket-sum and a bracket-consistency relation over an existing group). New: the relation itself, plus a decision on whether a violation across a between/above/below triple is tradeable as a 2- or 3-leg basket, which the current 2-leg placement loop does not model.

**Priority: Medium-High.** Cost of not having it: the ladder shape with the most rungs and (per the live probe) the thinnest books — `-B92.5` showed `yes_bid_size=0`, `yes_ask_size=31,706` — is completely unmonitored for the exact mispricing class the module exists to catch, and the between family is also the one this project already lost two real trades on (see the 2026-08-09 METAR lock-in entry).

---

### F4. Order-book depth: batch endpoint unused, single endpoint has one CLI caller, and top-of-book sizes arrive free on every market fetch and are discarded

**INTERNAL** (endpoint existence externally confirmed by live probe).

- `kalshi_client.get_orderbook` (`kalshi_client.py:346-350`) has **exactly one caller in the repo**: `main.py:1357`, the human-readable "Orderbook:" print in `market <ticker> --verbose`. The trading path deliberately avoids it (`order_executor.py:130-134`: *"Deliberately does NOT use get_orderbook() — get_market()'s yes_bid/yes_ask are the authoritative top-of-book"*).
- The `depth` query parameter is never sent.
- **`GET /markets/orderbooks?tickers=…` (batch, full depth) has zero references** (`grep "markets/orderbooks"` → 0). Live-probed unauthenticated: HTTP 200, returned the complete price-level ladder for `KXHIGHNY-26AUG10-T96` (28+ levels on the NO side alone) in one call.
- **`yes_bid_size_fp` / `yes_ask_size_fp` are present on every market object the bot already fetches and have zero references** (`grep` → 0 in prod and tests). Live sample: `yes_ask_size_fp: "14277.00"`, `yes_bid_size_fp: "0.00"`. `volume_24h_fp` has 1 reference (`main.py:5257`, display). Liquidity is instead synthesized as `volume(_fp) + open_interest(_fp)` (`weather_markets.py:10720-10722`).
- On the WS side, `orderbook_snapshot` builds `yes_levels`/`no_levels` (`kalshi_ws.py:87-101`) that **nothing can read** — both public accessors require `mid_price` (`kalshi_ws.py:233`, `:239`), which a snapshot entry never has. `orderbook_delta` payloads are stashed as `last_delta` with no reader (`kalshi_ws.py:155`, self-documented at `:144-146`, `:255-257`).

**Why this isn't already tracked.** Open entries L8899 (`LIQUIDITY-AWARE SIZING`, resolved) and L9064 (`is_liquid()` field names, resolved) both operate on volume/OI, not depth. The one closed WS-depth entry (L9385, `WEBSOCKET orderbook_delta get_snapshot`) was closed as *"not a simplification, no concrete use case"* — that was about a simpler book-init path, not about using depth as a signal. Grepped `orderbook`, `depth`, `levels`, `book`, `bid_size`, `ask_size`.

**Cheap vs. build.** Reading `yes_bid_size_fp`/`yes_ask_size_fp` is nearly free — the fields are already in the dict `is_liquid()` inspects. The batch endpoint needs one new client method (the pagination/parse shape mirrors `get_orderbook` exactly). What's genuinely new: deciding what depth *means* for sizing (fillable-size-aware Kelly, spread-vs-depth gating) — the existing `liquidity_kelly_scale` / `_liquidity_edge_scale` are the natural insertion points.

**Priority: Medium-High.** Cost of not having it: position sizing on a resting-maker strategy is blind to whether the size it wants can actually fill, on a book where a single market maker is quoting tens of thousands of contracts at a penny.

---

### F5. `_analyze_precip_trade` and `_analyze_snow_trade` (≈390 lines of working model) are unreachable from the live scan

**INTERNAL.**

Both models exist, are dispatched from `analyze_trade` (`weather_markets.py:10867` and `:10880`), and are unreachable in practice:

- `KNOWN_WEATHER_SERIES` (`weather_markets.py:3825-3957`) contains **no** daily-precip or generic-snow series. `get_weather_markets` fetches exactly the registry (`weather_markets.py:4094`) — there is no global scan.
- Every registered `KXRAIN*M` ticker returns `precip_month_total` at `weather_markets.py:5517` and every `KXDENSNOWM*` returns `snow_month_total` at `:5556` — both *before* the generic `precip_any`/`precip_above`/`precip_snow` blocks at `:5644`/`:5666`/`:5628`.
- The only other route in, `is_precip_title` (`weather_markets.py:5604-5609`), requires `"temperature"`/`"high"`/`"low"` to all be absent from the title — which real `KXHIGH*`/`KXLOW*` titles always contain.

So `_analyze_precip_trade` (`7927-8133`, 207 lines) and `_analyze_snow_trade` (`8136-8321`, 186 lines) — including the wet-bulb / snow-liquid-ratio chain at `7161-7191` — currently price nothing.

Kalshi does list the products they were written for. From the live catalog: `KXRAIND` ("Rain Daily"), `KXRAINDNYC` ("Daily Rain - NYC"), `KXRAINHOLIDAY`, and the four `*SNOWXMAS` holiday-window series. All are in `KNOWN_UNTRACKED_RAIN_SERIES` / `KNOWN_UNTRACKED_SNOW_SERIES` with a live-verified "0 open markets" note.

**Why this isn't already tracked.** L5028 (`RAIN / SNOW / HURRICANE — UNTOUCHED CATEGORY SURFACE`, partially resolved) covers *monthly* rain and snow and hurricane, all of which shipped. It does not observe that the daily-precip/generic-snow models are already written and stranded — the untracked-series comments frame those series purely as "0 open markets," not as "we have a model waiting for them."

**Cheap vs. build.** Extremely cheap *if and when* Kalshi lists a daily precip or holiday-snow market: the models, the Kelly tail, the consensus bonus, and the shadow-gate pattern all exist. The near-term actionable piece is a cheap watch (see F6) so a listing is noticed, rather than building anything now.

**Priority: Low now, Medium if a listing appears.** Cost of not having it: ~390 lines of tested model silently rot, and if Kalshi relists daily rain nobody finds out.

---

### F6. The series-drift watcher covers five families; the live Climate-and-Weather catalog has 291 series, and several high-volume temperature-adjacent ones are invisible to it

**INTERNAL** (catalog externally confirmed by live probe).

`check_series_drift()` (`weather_markets.py:4139-4246`) already does the right thing — it fetches Kalshi's live catalog daily via `get_series_list(category="Climate and Weather")` and warns on drift in both directions. Its filter (`weather_markets.py:4167-4178`) is:

```python
t.startswith(("KXHIGH", "KXLOW", "KXRAIN")) or "SNOW" in t
  | (live_tickers & (_HURRICANE_COUNT_SERIES | _HURRICANE_NEXT_EVENT_SERIES | _STORM_ORDER_SERIES))
```

`KXTEMP*H` is a documented deliberate blind spot (`:4185-4188`). Everything else outside those five families produces **no warning ever**, in either direction.

Live catalog probe (`GET /series?category=Climate and Weather&include_volume=true`, 291 series). Untracked, unwatched, and carrying real volume:

| Series | volume | open markets today | title |
|---|---|---|---|
| `KXTORNADO` | 4,043,486 | — | Number of Tornadoes (monthly) |
| `KXHMONTH` | 3,952,726 | 2 | Hottest month instance |
| `KXHURCAT` | 2,424,310 | — | Hurricane category (per-storm) |
| `KXHMONTHRANGE` | 1,118,002 | 12 | Monthly Temperature Increase (°C) |
| `KXGTEMP` | 943,293 | 2 | Hottest year ever |
| `KXHOLIDAYTMAX` | 561,537 | 0 | Max temperature holiday by city |
| `KXHOLIDAYTMIN` | 112,913 | 0 | Min temperature holidays |
| `KXHOBBYTEMP` | 27,737 | 1 | Max temperature at Houston Hobby Airport |

**Why this isn't already tracked.** `KXHURCAT` and per-city landfall are explicitly named as still-open in L5028, so treat that one as covered. The rest are not in any entry. The *watcher gap itself* — that a new temperature-adjacent family can go live with no signal — is not covered anywhere.

Two separable pieces:
1. **Widen the watcher.** Nearly free: one filter predicate plus an "untracked but real" allowlist, mirroring the three that already exist. This makes the blind spot self-reporting rather than requiring a manual catalog scan every few months.
2. **Evaluate specific families.** `KXHOLIDAYTMAX`/`KXHOLIDAYTMIN` ("Max temperature holiday by city") is the closest adjacent product to the bot's core competence — same variable, same cities, just a holiday-window framing — and it has real historical volume with zero open markets right now, i.e. it is seasonal, not dead. `KXHOBBYTEMP` is a single-station daily max, which the existing daily model prices directly.

**Priority: Medium (piece 1), Low-Medium (piece 2).** Cost of not having piece 1: the current registry was found to have 10 renamed tickers and 2 missing cities by a *manual* investigation (`weather_markets.py:4148-4151`); the watcher was built so that never recurs, and it currently guards ~55 of the ~291-series surface.

---

### F7. The bot has no exchange-status awareness, and no client method for settlements or fills

**INTERNAL** (endpoint existence externally confirmed by live probe).

Verified zero references repo-wide (`grep --include=*.py`, prod and tests):

| Endpoint | Repo hits | Live probe |
|---|---|---|
| `GET /exchange/status` | 0 | 200 — `{"exchange_active": true, "trading_active": true, "exchange_index_statuses": [{index 0 …}, {index 1, "trading_active": false}]}` |
| `GET /exchange/schedule` | 0 | 200 — `maintenance_windows` (empty now) + weekly `standard_hours`, incl. a Thursday 03:00–05:00 UTC gap |
| `GET /portfolio/settlements` | 0 | (auth required, not probed) |
| `GET /portfolio/fills` | 0 | (auth required, not probed) |
| `GET /portfolio/orders/{id}/queue_position` | 0 | (auth required, not probed) |

Consequences visible in the code:

- Nothing checks whether the exchange is open or in maintenance before a cycle. The live-order path has seven gates (`trading_gates.py:232-242`) and none of them is "is the exchange up."
- Settlement is inferred from `market["result"]` (`order_executor.py:538`) and a `status="settled"` scan; **fills are inferred by polling `get_order().fill_count_fp`** (`order_executor.py:498-500`). Kalshi's own settlement and fill records are never read. This is directly relevant to the two open partial-fill accounting entries, **L510** and **L544** — both are about reconstructing what actually filled from the bot's own ledger; `GET /portfolio/fills` is the authoritative record those entries are reconstructing.

Also verified: `taker_fill_cost_dollars` / `maker_fill_cost_dollars` / `average_fee_paid` are documented in the client's own docstrings (`kalshi_client.py:674`, `order_executor.py:3175-3186`) and never read — so **every fee in the system is modelled and none is observed**.

**Why this isn't already tracked.** No open entry covers exchange status/schedule. L510/L544 cover partial-fill accounting from the ledger side; pointing them at `GET /portfolio/fills` is a **new angle on those entries**, not a new entry. Grepped `exchange`, `maintenance`, `schedule`, `settlements`, `fills`, `queue_position`.

**Cheap vs. build.** All cheap — each is one `_get` method in the existing client shape. The scheduling/gating decision (what to do when maintenance is imminent) is the only design work.

**Priority: Medium.** Cost of not having it: orders placed into a maintenance window, and a partial-fill reconciliation problem being solved by inference when the exchange publishes the answer.

---

### F8. NBM's own mean and standard deviation are inside a bulletin the bot already fetches, parses, and caches — and are skipped

**INTERNAL.**

`_NBP_PERCENTILE_ROWS` (`mos.py:396-402`) maps exactly five rows — `TXNP1/2/5/7/9` (the 10/25/50/75/90 percentiles). `_parse_nbp_bulletin` iterates only that dict (`mos.py:489-499`).

The NBP bulletin carries two more temperature rows immediately above them. From the repo's own fixture, described as *"structurally faithful to a real fetched bulletin (KMDW, 2026-07-24)"*:

```
tests/test_mos_nbp.py:40:  TXNMN  80  63| 85  67     <- NBM's deterministic mean
tests/test_mos_nbp.py:41:  TXNSD   2   2|  2   2     <- NBM's standard deviation
```

`TXNMN` and `TXNSD` appear **nowhere else in the repo** (`grep` → those two fixture lines only). `_split_nbp_row` (`mos.py:405-424`) is row-label-agnostic and would parse either unchanged.

So a **native NBM sigma** is sitting in an already-fetched, already-parsed, already-cached product, while the bot derives sigma from a hand-rolled `_forecast_uncertainty(target_date)` and from `climatology.compute_sigma_from_climate` (30-year climate stdev × 0.60, `climatology.py:272`, `:379`).

**Why this isn't already tracked.** L10820 (`NBM PROBABILISTIC QUANTILES — ORPHANED CONVERTER, MISSING FETCHER`, resolved 2026-07-24) built exactly this fetcher — for the percentile rows. L10869 (`FORECAST-CONDITION COVARIATES FOR SIGMA — INCLUDING FIELDS ALREADY FETCHED AND NEVER READ`, partially resolved) is the closest open entry and is about `precip_sum_in`/`wind_gust`-shaped covariates for a sigma *model*, not about an already-published sigma. L9261 wants sigma from settled history — a different quantity (realised forecast error) from NBM's own forecast-time uncertainty; the two are complementary, not duplicative. Grepped `sigma`, `TXNSD`, `stdev`, `std_dev`, `uncertainty`, `spread`, `nbm_sigma`.

**Cheap vs. build.** Very cheap: two dict entries and a second return key. The design question is whether `TXNSD` beats the current sigma — which is measurable against `settled_temp_f` once F1 lands, and which the existing `SIGNAL_REGISTRY` shadow-then-graduate pattern (`weather_markets.py:6716-6875`) is built to answer.

**Priority: Medium-High.** Cost of not having it: sigma feeds `gaussian_probability()` on literally every trade, and the current estimate is a heuristic while a calibrated one is already being downloaded and thrown away every cycle.

---

### F9. The `/historical/*` family is unused, and Kalshi's live window is only ~3 months

**INTERNAL** (verified live).

Zero repo references to any `/historical` endpoint. Live probes, all unauthenticated, all HTTP 200:

- `GET /historical/cutoff` → `{"market_settled_ts": "2026-06-10T00:00:00Z", "trades_created_ts": "2026-06-10T00:00:00Z", "orders_updated_ts": …, "market_positions_last_updated_ts": …}`. Kalshi's docs state *"The target window for live data is 3 months"*; anything older moves to the historical endpoints.
- `GET /historical/markets?series_ticker=KXHIGHNY&limit=1000` → 1,000 markets across 167 events, `close_time` 2025-12-25 → 2026-06-09, `cursor` present (more pages), carrying `result`, `expiration_value`, `strike_type`, `floor_strike`, `settlement_ts`, `volume_fp`, `open_interest_fp`, `yes_bid_size_fp`, `yes_ask_size_fp`, `price_ranges`.
- `GET /historical/trades?limit=2` → full signed taker flow with `taker_outcome_side`, `taker_book_side`, `is_block_trade`.

Two consequences:

1. **A real backtest data source exists and isn't used.** `backtest.run_backtest` reconstructs probabilities from a **synthetic** 50-member ensemble (`backtest.py:128-133`, `forecast_mean + gauss(0, sigma)`); `run_walk_forward` reads only the tracker DB and reports `"pnl": 0.0` with the comment `# entry price not available in tracker DB` (`backtest.py:755`). The historical endpoints supply real per-market prices, sizes, and outcomes.
2. **The existing capture has a silent horizon.** `sync_outcomes` backfills candlesticks and trades from the *live* endpoints at settlement (`tracker.py:4563`, `:4601`). That works going forward, but any gap longer than the cutoff is unrecoverable from those endpoints — and `backfill_price_history` (`tracker.py:4655`), which exists precisely to recover lost rows, uses the live endpoint.

**Why this isn't already tracked.** L10563 (`PUBLIC TRADES REST BACKFILL`, partially resolved) built `get_trades` against `/markets/trades` — the live endpoint — and its remaining open half is an *analysis* pass over already-captured rows. Neither it nor the candlestick entry (L8099, resolved) mentions the historical family or the 3-month cutoff. Grepped `historical`, `/historical`, `cutoff`, `archive` (the `archive` hits are all Open-Meteo).

**Cheap vs. build.** The client methods are cheap (same paginated `_get` shape). Rewiring `backtest.py` onto real historical prices is a genuine build. The cheapest useful slice is a cutoff-awareness guard on the existing backfill path.

**Priority: Medium.** Cost of not having it: the backtester validates against synthetic ensembles rather than the real market, and the capture pipeline has an undocumented ~3-month recovery horizon.

---

### F10. `get_events` is a dead client method, and the whole-ladder-in-one-call shape is unused

**INTERNAL** (verified live).

`kalshi_client.get_events` (`kalshi_client.py:435-438`) has **zero callers anywhere**, including tests (`grep get_events --include=*.py` → 1 hit, the definition). It also has no cursor loop, so it would return page 1 only.

Live-verified: `GET /events?series_ticker=KXHIGHNY&status=open&with_nested_markets=true` returns each event with its complete markets array — including `cap_strike`, which the flat `/markets` response omits for non-between rungs. The bot instead issues one `get_markets(series_ticker=…)` per registry entry, 6 workers, 40s timeout (`weather_markets.py:4092-4127`).

Related, same file: `get_series_list` returns rich series objects and the single consumer reads **only** `ticker` (`weather_markets.py:4165-4166`). Verified live, every one of the 291 weather series carries `settlement_sources` (name + URL), `contract_terms_url`, `contract_url`, `frequency`, `fee_type: "quadratic"`, `fee_multiplier: 1`, and `product_metadata`. All dropped.

Also unused on `get_markets`: `min_updated_ts`, `min_close_ts`/`max_close_ts`, `tickers` (comma list), `event_ticker`, and `mve_filter` — all 0 repo hits. Note `weather_markets.py:3821-3823` carries a stale comment (*"client.get_markets() does not expose the API cursor, making reliable pagination impossible"*) that the client contradicts — it paginates internally at `kalshi_client.py:315-336`.

**Why this isn't already tracked.** No open entry covers `get_events`, `with_nested_markets`, or the dropped series metadata. Grepped `get_events`, `nested`, `event_ticker`, `settlement_sources`, `product_metadata`, `frequency`.

**Cheap vs. build.** Cheap. The `settlement_sources` half feeds F2 directly.

**Priority: Low-Medium** on its own; **Medium** as the delivery mechanism for F2's provenance check.

---

### F11. `settlement_monitor` is manual-only, so the automated early-close path it feeds has never had input

**INTERNAL.**

`run_settlement_monitor` is reachable from exactly one place: the CLI (`main.py:8930-8931` → `main.py:847-859`). Nothing schedules it — `cmd_schedule` (`main.py:8217`) registers `KalshiWeatherScan`/`KalshiWeatherEmail`/`KalshiWeatherSettle`; `cmd_schedule_cycles` (`main.py:8318`) registers the four NWP-aligned cron tasks. Neither includes it.

`cron.py:1391-1441` *reads* `data/settlement_signals.json` and, on `confidence >= 0.80` matching an open trade, calls `paper.close_paper_early(id, 0.97 or 0.03)` — a real automated exit. But the writer never runs. **`data/settlement_signals.json` does not exist in the live data directory** (verified: `ls C:/Users/thesa/claude kalshi/data/settlement_signals.json` → no such file).

Separately worth noting: `settlement_monitor.py:93-94, 328-329` (`_MONITOR_START_HOUR=17`, `_MONITOR_END_HOUR=19`, evaluated against `datetime.now(ZoneInfo(city_tz))`) is the **only per-city-local-time scheduling anywhere in the program** — `cron.py`, `trade_cycle.py`, and `watchdog.py` contain zero timezone imports.

**Why this isn't already tracked.** L4 (the 2026-08-09 `SETTLEMENT_MONITOR.PY` between-bucket AC3 entry) is about a *correctness* defect in this module's lock logic, and its framing ("it auto-closes real paper positions") presumes the module runs. Open entry L9897 (`CITY-LOCAL AFTERNOON SAME-DAY SWEEP`) wants per-city local-time scanning and its own 2026-07-20 note recommends closing it as superseded once the VM move lands — worth flagging that **the mechanism it wants already exists in this module**, unscheduled. Grepped `settlement_monitor`, `schtasks`, `schedule`, `Popen`.

**Cheap vs. build.** Cheap — a `schtasks` entry in `cmd_schedule_cycles`, or a background thread in the always-on watcher (L7584 / L12710 territory).

**Priority: Medium.** Cost of not having it: a built, tested, real automated-exit signal produces nothing, and the L4 correctness fix currently guards a code path with no live input.

---

### F12. NWS data already being paid for and thrown away

**INTERNAL.**

All verified by `grep --include=*.py` across the repo (prod and tests), 0 hits each:

- **`forecastGridData`** — the `/points/{lat},{lon}` response is fetched **twice per city** (`nws.py:160` for `gridId/gridX/gridY`, `nws.py:175` again for `observationStations`, without reusing the first cache). Both responses contain the `forecastGridData` URL — the pointer to NWS's raw gridded dataset (skyCover, quantitativePrecipitation, snowfallAmount, apparentTemperature, probabilityOfPrecipitation, maxTemperature/minTemperature grids). Fetched twice, discarded twice. The raw `/gridpoints/{id}/{x},{y}` endpoint (no `/forecast` suffix) is never called; only `/gridpoints/.../forecast` is (`nws.py:228`).
- **`maxTemperatureLast24Hours` / `minTemperatureLast24Hours`** — present on the `/stations/{id}/observations/latest` response the bot already fetches (`nws.py:443`, and again at `:495` for precip). These are the daily extremes the METAR path reconstructs by hand (`metar.py:178-204`).
- **`probabilityOfPrecipitation`** — on every `/gridpoints/.../forecast` period the bot iterates (`nws.py:241-264`, which reads only `startTime`, `temperature`, `temperatureUnit`, `isDaytime`). This is NWS's own official PoP, and the bot trades rain markets using a different source entirely.
- Also unread on the same already-fetched objects: `detailedForecast`, `shortForecast`, `relativeHumidity`, `dewpoint`, `windSpeed`, `temperatureTrend` (forecast periods); `dewpoint`, `relativeHumidity`, `windChill`, `heatIndex`, `barometricPressure`, `cloudLayers`, `presentWeather` (observations).
- `/observationStations` returns the full ordered nearby-station list; only `features[0]` is used (`nws.py:181-183`).

**Why this isn't already tracked.** L10869 (`FORECAST-CONDITION COVARIATES FOR SIGMA — INCLUDING FIELDS ALREADY FETCHED AND NEVER READ`, partially resolved) is the right home for the covariate half and its resolution note covers `precip_sum_in` + `wind_gust` from the **Open-Meteo** path. The NWS-side fields above are a different source and are not in that entry — treat these as **additions to L10869**, not a new entry. The `forecastGridData` / raw-grid endpoint and the 24-hour extremes are not covered anywhere. Grepped each field name individually.

**Cheap vs. build.** The already-in-hand fields (24h extremes, PoP, humidity/dewpoint) are nearly free — parse and thread through. The raw gridded endpoint is a new fetcher, but `ForecastCache` + `CircuitBreaker` give it the established shape.

**Priority: Medium.** Cost of not having it: the same HTTP requests are already being made and paid for; the marginal cost of the data is zero and it includes both an official PoP for the rain models and a station-reported daily extreme for the same-day path.

---

### F13. IEM's own model allowlist is in the code; three of its models are never requested

**INTERNAL.**

`mos.py:378-381` documents, from a live test, IEM's server-side model restriction: `^(AVN|GFS|ETA|NAM|NBS|NBE|ECM|LAV|MEX)$`. The bot requests exactly three: `GFS` and `NAM` (`mos.py:152`, `:216`, `:221`) and `NBS` (`mos.py:273`).

Never requested anywhere (`grep` → 0): **`LAV`** (LAMP — Localized Aviation MOS Program, the hourly-updating short-range statistical guidance), **`MEX`** (extended-range GFS MOS, ~8 days), **`ECM`** (ECMWF MOS), **`NBE`** (NBM extended).

Two specific fits:

- **`LAV` → the hourly markets.** `_analyze_hourly_trade` hardcodes `consensus = False` because *"no genuinely independent second source exists for hourly yet"* (`weather_markets.py:9843-9854`), and the hourly path deliberately skips METAR lock-in, the NBM/ECMWF blend, `get_historical_sigma()`, and the model-consensus check (`weather_markets.py:9767-9779`). LAMP is hourly station guidance from the same host, same JSON API, same `fetch_mos` code path.
- **`MEX` → the far end of the horizon.** `nws_prob` falls back to `sigma=4.0` at long lead times (`nws.py:343`); MEX covers exactly that range.

Also: MOS GFS/NAM is wired for only 6 of 20 cities (`_MOS_CITIES`, `mos.py:33`), and per-row `dpt` (dew point) and every non-`tmp` MOS column are dropped at parse (`mos.py:174`).

**Why this isn't already tracked.** L8346 (`GENERALIZED PER-MODEL ACCURACY TRACKING + NEW AI MODEL SOURCES`, resolved) and L8701 (`GRADUATE GEM/UKMO`, partially resolved) are about Open-Meteo ensemble members, not IEM MOS models. The hourly entry (L4678, resolved) shipped Step 1+2 and left the no-second-source gap open in code comments, not in an entry. Grepped `LAV`, `LAMP`, `MEX`, `ECM`, `NBE`, `mos.json`, `model=`.

**Cheap vs. build.** `MEX`/`ECM` are nearly free — `fetch_mos` already takes a `model` parameter and `MOS_SIGMA` already has per-model rows. `LAV` needs its own sigma row and an hour-indexed accessor (the NBS/NBP code is the precedent).

**Priority: Medium.** Cost of not having it: the hourly market family is permanently stuck at `consensus=False` — one of the reasons it can't graduate out of shadow — while an independent hourly source sits behind a parameter the code already sends.

---

### F14. ACIS is asked only for precipitation, never for temperature — at the exact station Kalshi settles on

**INTERNAL.**

`acis_precip.py` and `acis_snow.py` both POST to `http://data.rcc-acis.org/StnData` with `elems` set to exactly one element: `pcpn` (`acis_precip.py:135`, `:223`) or `snow` (`acis_snow.py:140`, `:236`). ACIS's `maxt`/`mint` daily elements are never requested (`grep "maxt"` → 0 outside these files' comments), nor are `MultiStnData`, `GridData`, or `StnMeta`.

The station ID is derived from `metar.MARKET_STATION_MAP` (`acis_precip.py:72-86`) — i.e. the ASOS station Kalshi's `rules_primary` names as the settlement site. Meanwhile the bot's 30-year temperature climatology comes from **Open-Meteo gridded reanalysis at a lat/lon** (`climatology.py:100-108`), and `get_historical_sigma` derives sigma from that grid's variance (`climatology.py:272`, `:379`).

So: a free, unauthenticated, already-wired NOAA endpoint can return 30 years of daily max/min **at the settlement station**, and the bot asks it only for rain.

**Why this isn't already tracked.** L9261 wants forecast-error sigma from the bot's own settled history; this is station climatology, a different quantity. L6613 (`LAS VEGAS / NEW ORLEANS MISSING FROM _HISTORICAL_SIGMA`, resolved) was solved with the Open-Meteo grid. No entry covers ACIS temperature elements. Grepped `maxt`, `mint`, `avgt`, `StnData`, `elems`, `rcc-acis`.

**Cheap vs. build.** Cheap — the fetcher, the circuit breaker, the 30-day disk cache, and the `{year: {MMDD: value}}` shape are all in `acis_precip.py` and substance-agnostic (`acis_snow.py` already reuses them wholesale).

**Priority: Medium.** Cost of not having it: every climatological prior and climatology-derived sigma is computed on a reanalysis grid cell rather than the thermometer the contract settles on.

---

### F15. Two whole tables and the entire candlestick price series are accumulating with no reader

**INTERNAL.**

Verified by repo-wide grep (prod and tests):

- **`audit_log`** (`tracker.py:480-489`, 8 columns incl. free-text `thesis`) — written by `log_audit` (`tracker.py:717-750`) from `main.py`. **There is no `SELECT ... FROM audit_log` anywhere in the repository, including tests.** The index `idx_audit_ticker` (`:490`) serves no query. A complete manual-trade audit trail is accumulating unread.
- **`near_settlement_log`** (`tracker.py:534-545`, 8 columns) — written by `cron.py:483-524`. Production SELECTs: none (only `tests/test_near_settlement_log.py:55` and `tests/test_cron_integration.py:968`). Worse, the column that makes the table's stated purpose possible — model prob vs **market price** in the 0–2h window before close (`tracker.py:123-124`) — is hardcoded `None`:
  ```python
  cron.py:515:   None,  # market_yes_price: Phase 2 — requires live market fetch
  ```
- **`price_history` OHLC/bid/ask/volume/OI** (`tracker.py:186-201`) — `price_open`, `price_high`, `price_low`, `yes_bid_close`, `yes_ask_close` are written at `tracker.py:1195-1196` and read only in `tests/test_tracker.py`. The sole reader function chain, `get_price_history` → `get_trade_flow_settlement_correlation`, has **zero production callers** — all three are on the dead-code allowlist (`tests/test_dead_code_scan.py:244`, `:252`, `:262`), and the correlation function self-describes as *"log-only research, not wired into trading"* (`tracker.py:1274-1275`). The same holds for `trade_history` (20,000+ real rows per `tracker.py:4548`).

This is the "80%-built infrastructure" pattern in its purest form: capture, schema, migrations, dedup keys, backfill commands, and tests all exist; only the consumer is missing.

**Why this isn't already tracked.** L10563's remaining open half is precisely one deferred analysis pass over `trade_history` ("adverse selection around our own fill times") — so **the trade/price-history consumer gap is partly covered there**; the honest framing is that its enablement trigger (*"a real multi-week window of data"*) has now fired, since `trade_history` has 20,000+ rows. `audit_log` and `near_settlement_log` are covered nowhere. Grepped each table name.

**Cheap vs. build.** The data is already there; this is pure read-side work. `near_settlement_log`'s stated purpose additionally needs the one-line `market_yes_price` fill.

**Priority: Low-Medium**, except the L10563 trigger note, which is **actionable now** and costs only a query.

---

### F16. Two fully unreferenced modules

**INTERNAL.** Minor, recorded for completeness.

- **`market_types.py`** (67 lines, 4 `TypedDict`s) — zero imports anywhere in the repo (`grep market_types|MarketDict|AnalysisResult|ForecastResult|MarketCondition` returns only the file itself plus three unrelated *test class names*). It is also stale: `MarketCondition["type"]` omits six condition types `_parse_market_condition` actually produces, and `AnalysisResult` declares 17 keys against `analyze_trade`'s ~60.
- **`check_edge.py`** (27 lines) — zero references repo-wide.

Not a capability finding; the actionable read is that a typed-boundary module exists and could be revived as real typing for the analysis-dict boundary, or deleted. `backlog.txt:13784-13788` records the earlier decision to put shared helpers in `utils.py` "not market_types.py, since market_types.py turned out … to be a pure TypedDict-only module with zero runtime logic today."

**Priority: Low.**

---

## Section 2 — EXTERNAL findings

Each of these is grounded in Kalshi's published docs plus, where possible, a live probe. Their epistemic status is weaker than Section 1: none is a gap I can point at in this codebase, and each carries a stated internal verification step.

### E1. `forecast_percentile_history` — a market-implied distribution time series, straight from the exchange

**EXTERNAL.** Source: <https://docs.kalshi.com/api-reference/events/get-event-forecast-percentile-history.md>

Documented path: `GET /series/{series_ticker}/events/{ticker}/forecast_percentile_history`, params `percentiles` (up to 10, range 0-9999), `start_ts`, `end_ts`, `period_interval` (0 = 5-second, or 1/60/1440 minutes). Response: `percentile_points[]` with `percentile`, `raw_numerical_forecast`, `numerical_forecast`, `formatted_forecast`. The docs describe it as *"the historical raw and formatted forecast numbers for an event at specific percentiles."*

If it applies to weather events, that is the market-implied temperature distribution over time, published by the exchange — the same object `weather_markets.fit_market_implied_distribution` reconstructs from the ladder (`weather_markets.py:6008-6162`, currently log-only per its own docstring at `:6075-6077`), except historical and at up to 5-second resolution.

**Status: unverified.** I probed it against real KXHIGHNY events (both open `26AUG10` and prior `26AUG09`) with repeated-param and comma-separated `percentiles`, across `period_interval` 0/1/60/1440. Comma form returns `strconv.ParseInt` errors (so repeated params are correct); the repeated-param form returns a bare `{"error":{"code":"bad_request"}}` with no detail. Either the endpoint doesn't apply to weather events, or a param constraint I didn't find is being violated.

**What must be verified before acting:** does this endpoint return non-empty data for any `KXHIGH*`/`KXLOW*` event at all? That is a single successful `GET` away and kills or confirms the whole idea. Existing infrastructure if it works: `market_implied` is already a `SIGNAL_REGISTRY` entry with a sample floor and a stated graduation condition (`weather_markets.py:6730-6741`), so there is a ready-made evaluation harness.

**Priority: Medium if it works, zero if not.** Cheap to falsify — do that first.

### E2. Kalshi's fee formula is quadratic; the bot uses a flat-fraction-of-winnings approximation

**EXTERNAL + INTERNAL.** Source: Kalshi fee schedule (referenced in-repo at `utils.py:78-94`); live probe of `GET /series?category=Climate and Weather`.

The code is candid about this (`utils.py:79-82`): *"7% is the coefficient in that formula, not a flat 7% of winnings — KALSHI_FEE_RATE is used here as a flat-fraction-of-winnings approximation."* Real formula: `fee = round_up(0.07 · C · P · (1−P))` per contract.

Live-verified: **all 291 Climate-and-Weather series carry `fee_type: "quadratic"` and `fee_multiplier: 1`** — so the quadratic form applies uniformly and the multiplier is not a per-series complication for this bot. Neither field is read anywhere (`grep fee_type|fee_multiplier` → 0).

The approximation `p_win · payout · fee_rate` equals the true fee exactly when `p_win == price`, and diverges by the ratio `p_win / price` otherwise — i.e. **precisely when there is edge, which is the only time an order is placed.** It over-states the fee when `p_win > price` (conservative, so not a safety issue), and it omits the per-fill round-up-to-the-cent entirely (which under-states fees on small orders — the bot's quantity floor is 1 contract, `paper.py:842`).

**What must be verified before acting:** the magnitude. Recomputing realised P&L both ways over settled trades is a few lines and would say whether this is worth a change at all. Note the deeper point from F7: `average_fee_paid` / `taker_fill_cost_dollars` / `maker_fill_cost_dollars` are never read, so **no observed fee has ever been compared against the model**.

**Priority: Low-Medium.** Cost of not having it: EV and Kelly are computed against a fee model that has never been checked against a real invoice.

### E3. Multivariate event collections (combo markets)

**EXTERNAL.** Sources: <https://docs.kalshi.com/api-reference/multivariate/get-multivariate-event-collections.md>, <https://docs.kalshi.com/api-reference/multivariate/create-market-in-multivariate-event-collection.md>; live probe.

`POST /multivariate_event_collections/{collection_ticker}` creates or resolves a combo market from selected legs; markets carry `mve_collection_ticker` and `mve_selected_legs`, and `GET /markets` accepts `mve_filter=only|exclude`. Zero repo references to any of these (`grep multivariate|mve_` → 0).

**Live probe result: no weather collections found.** `GET /multivariate_event_collections?limit=200` returned NFL game/spread/total parlays across the pages I sampled. So today this is a sports product.

**What must be verified before acting:** whether Kalshi ever exposes a weather collection (e.g. joint temperature across two cities). Until then this is a watch item, not work. One concrete, low-cost consequence *is* actionable now: since the bot never sends `mve_filter`, if a weather-adjacent collection ever appears under a tracked series it would enter the scan silently and be priced by a model that assumes a single-city marginal.

**Priority: Low (watch).**

### E4. Liquidity-incentive programs

**EXTERNAL.** Live probe: `GET /incentive_programs` → HTTP 200 unauthenticated, returning entries with `incentive_type: "liquidity"`, `incentive_description: "series_lip"`, `market_ticker`, `target_size_fp`, `period_reward`, `discount_factor_bps`, `start_date`/`end_date`. The sample I pulled listed `KXSILVER15M` and `KXWTI15M`. Zero repo references (`grep incentive` → 3 hits, all `backlog.txt` prose).

`backlog.txt:7887-7916` already records research into Kalshi's Volume Incentive Program / Liquidity Provider Program and leaves "identify which Kalshi incentive program actually applies" open — so **this is a concrete new mechanism for answering a question that entry already asked**: the endpoint is machine-readable and free to poll.

**What must be verified before acting:** whether any `KXHIGH*`/`KXLOW*` market ever appears in the feed. That needs sampling over days, not one call.

**Priority: Low.** Relevant only to a resting-maker strategy, which is what the bot already runs (`kalshi_client.py:727`, GTC limit at midpoint).

### E5. Order queue position

**EXTERNAL.** Sources: <https://docs.kalshi.com/api-reference/orders/get-order-queue-position.md>, `get-queue-positions-for-orders`. Zero repo references.

The bot places resting GTC maker orders and reprices them via `amend_order` — whose own docstring notes that a price-only amend **forfeits queue position** (`kalshi_client.py:666-669`). The reprice decision (`order_executor.py:882-1032`) is therefore made without knowing what is being given up.

**What must be verified before acting:** requires authentication, so unprobed. Also note the reprice loop is reachable only from `watch --auto --live` (`main.py:3594-3595`) — `cron.py` never calls `_reprice_or_cancel_pending_orders`, so this only matters on the live path.

**Priority: Low.** Genuinely useful only once live maker trading is running continuously.

---

## Section 3 — What I checked and found already covered or already shipped

Recorded so a future session doesn't re-derive these.

| Hypothesis | Verdict |
|---|---|
| Correlation-aware sizing is missing | **Already shipped, extensively.** Five live mechanisms: `covariance_kelly_scale` (`paper.py:1845-1900`, marginal-portfolio-variance, clamped [0.3,1.0]), `corr_kelly_scale` (`paper.py:1949-1966`, max-pairwise, [0.25,1.0]), a continuous group-exposure Kelly penalty (`paper.py:1816-1820`), a hard `MAX_CORRELATED_EXPOSURE` cap (`paper.py:3640-3649`), and a Gaussian copula over Bernoulli marginals with a hand-rolled Cholesky + nearest-PSD ridge repair (`monte_carlo.py:21-70`, `:445-468`) feeding the pre-trade VaR gate. Empirical Pearson city correlations are estimated from settled outcomes (`tracker.py:6211-6270`). Do not propose this. |
| Real-time P&L / risk dashboard is missing | **Already shipped.** A 9-tab React SPA with VaR 95/99, drawdown tiers, Fear/Greed, circuit-breaker health, anomaly window, scan-filter breakdown, calibration curves, equity curve, and a kill switch (`web_app.py`, ~60 routes). SSE at 10s, polling at 60s. |
| Cross-market arbitrage is missing | **Partly shipped** — see F3. Detection + auto-placement exist for above/below ladders. |
| Market-implied temperature distribution is missing | **Already shipped** (`weather_markets.fit_market_implied_distribution`, `weather_markets.py:6008-6162`), log-only with a registered graduation condition. |
| Signal graduation is unstructured | **Already shipped** — `SIGNAL_REGISTRY` (11 entries), `get_signal_graduation_report()`, `py main.py signals`. Only part (c) of L12297 remains. |
| WS `trade` / `fill` / `market_lifecycle_v2` channels unused | **Already tracked** — L9451, L10970, and `backlog.txt:7885-7908`. L10970 also lists Kalshi's full channel inventory from a 2026-07-16 docs fetch. Not re-filed. |
| AFD text is fetched but never scored | **Already closed** — L9521, LLM scoring half declined by the user 2026-08-07. |
| Maker/taker fees modelled separately | **Already shipped and well-researched** (`utils.py:77-99`); maker rate is genuinely $0 for this bot's series. Only the quadratic-vs-flat shape is open (E2). |
| Kalshi order-write endpoints migrating to `/portfolio/events/orders` | **Already done** — L4339 closed; the client uses V2 (`kalshi_client.py:518`, `:626`, `:697`). |
| Sub-penny / fractional pricing needs handling | **Not applicable today.** Live-verified: temperature markets return `price_level_structure: "linear_cent"` and `price_ranges: [{start: 0, end: 1, step: 0.01}]`. Dropped rather than reported. |
| `no_ask` never read is a gap | **Not a gap.** NO-side prices are synthesized as `1 − yes_bid`/`1 − yes_ask`, which the live data confirms is exactly Kalshi's own relation. Dropped. |
| Between-bucket band is wrong (`val ± 1.0` vs real `floor`/`cap`) | **Not a discrepancy.** `-B90.5` → `[89.5, 91.5]` vs Kalshi `floor=90, cap=91`; equivalent for integer-reported settlement. Stated in F2 so nobody re-derives it. |

---

## Section 4 — Ranked shortlist

Ordered by (leverage from existing infrastructure) × (trading edge or operational value). INTERNAL findings dominate deliberately — each is grounded in code you can open right now, whereas every EXTERNAL item still needs a verification step first.

| # | Finding | Type | Why it ranks here |
|---|---|---|---|
| **1** | **F1 — read `expiration_value` on the daily-temperature settlement path** | INTERNAL | Highest leverage in the scan. The parsing code exists (used twice, for rain and snow); the field is live-verified populated on ~100% of settled markets across 6 series; a single backfill pass turns L9261's 234 rows / max-21-per-cell into ~3,000 and unblocks a Medium-priority entry that has been waiting on data since July. It also replaces a ground-truth source the code's own docstring says is the wrong one. |
| **2** | **F2 — read `strike_type`/`floor_strike`/`cap_strike` (and `rules_primary`) on temperature markets** | INTERNAL | Removes a free-text dependency from the most safety-critical parse in the program, using a pattern already implemented three times in the same function. Pairs with #1: both are about trusting Kalshi's structured fields over hand-rolled inference. |
| **3** | **F3 — extend the live arbitrage checker to between-buckets and above/below complementarity** | INTERNAL | The whole pipeline (grouping, edge-from-real-bid/ask, one-sided-book guard, shadow flag, circuit breaker, two-leg placement with unwind) already exists and already auto-places. The most numerous and thinnest-booked ladder rung is simply excluded by a list comprehension. Materially cheaper than the "build cross-market arbitrage" framing. |
| **4** | **F8 — map `TXNMN`/`TXNSD` in the NBP bulletin** | INTERNAL | Two dict entries. A calibrated NBM sigma is already being downloaded, parsed, and cached every cycle and dropped, while sigma — which feeds every probability the bot emits — comes from a heuristic. Evaluate via the existing `SIGNAL_REGISTRY` shadow-then-graduate harness. |
| **5** | **F11 — schedule `settlement_monitor`** | INTERNAL | One `schtasks` entry. A built, tested automated-exit path (`cron.py:1417-1426`) currently has no input at all — `data/settlement_signals.json` does not exist. It is also the only per-city-local-time mechanism in the program, which is exactly what open entry L9897 wants. |
| **6** | **F4 — read `yes_bid_size_fp`/`yes_ask_size_fp`; add the batch orderbook** | INTERNAL | The size fields are already inside the dict `is_liquid()` inspects — free. Batch depth is one client method. Directly relevant to a resting-maker strategy sizing into books quoted tens of thousands deep at a penny. |
| **7** | **F7 — `/exchange/status` + `/exchange/schedule`; point L510/L544 at `/portfolio/fills`** | INTERNAL | Two trivial client methods close a real operational hole (orders into maintenance), and the fills endpoint is the authoritative record that two open partial-fill entries are currently reconstructing by inference. |
| **8** | **F6 (piece 1) — widen `check_series_drift`'s filter** | INTERNAL | One predicate plus an allowlist. The watcher exists precisely so a manual catalog audit never has to happen again, and it currently guards ~55 of ~291 series. |
| **9** | **F12 — NWS fields already in hand (24h station extremes, official PoP)** | INTERNAL | Zero marginal request cost — the responses are already fetched (`/points` twice per city). Best filed as additions to L10869 rather than as new work. |
| **10** | **E1 — falsify or confirm `forecast_percentile_history` on a weather event** | EXTERNAL | Ranked last deliberately: unverified, and my probes all returned `bad_request`. But it is one successful `GET` away from either dying cheaply or handing over an exchange-published market-implied distribution time series at up to 5-second resolution. Do the probe before anything else here. |

---

## Notes for whoever picks this up

- **Nothing here has been filed in `backlog.txt`.** These are first-pass discovery findings; they have not earned the Problem/Priority/What-it-would-look-like rigour of the between-bucket and settlement-monitor entries from 2026-08-09. Promote per-finding, after review.
- **Three findings are refinements of existing open entries, not new entries** — say so when filing: F1 → L9261, F7 (fills half) → L510/L544, F12 (covariates half) → L10869. F15's trade-history half → L10563, whose "multi-week window" trigger has now fired.
- **F5 and E3 are watch items,** not work: they become valuable only if Kalshi lists a product that doesn't currently exist.
- Live API probes in this scan were unauthenticated read-only `GET`s against `api.elections.kalshi.com/trade-api/v2`. Every table of live results above is reproducible with no credentials.
