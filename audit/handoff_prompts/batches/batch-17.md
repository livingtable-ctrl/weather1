# Batch 17: Public trade-flow / market microstructure signals

## Context

Repo: weather1 (Kalshi weather-trading bot). Branch `claude/code-max-depth-audit-5518e9`, HEAD `d190d09dd699df5266e85650a6ddf8e2d1420891` at the time these batches were written (2026-08-18) -- **re-verify this is current before starting** (workflow step 1): other batches from this same grouping may already be merged, and this project routinely runs many parallel worktree sessions. `git fetch` + `git log origin/master` before touching anything.

This batch groups 3 **pre-existing** backlog item(s) (not from the 2026-08-18 audit) sharing **kalshi_ws.py, tracker.py**. Each item's full existing entry is reproduced verbatim below from `backlog.txt` -- these already have their own Problem/Priority write-ups from earlier sessions; read them in full rather than treating the excerpt here as complete.

**Do NOT touch other batches' files while working this one** -- batches were constructed so no two share a touched file; if you find yourself needing to edit something outside this batch's file list, stop and check whether another batch already covers it (see the full batch list in `audit/handoff_prompts/batches/INDEX.md`) rather than expanding scope silently.

## Items in this batch

### 1. Pre-existing backlog item (`backlog.txt:11324`)

```
[RE-VERIFIED 2026-08-03, STILL OPEN -- own WS-continuity trigger re-checked
  live and confirmed NOT fired; this session's scope was redirected to the
  REST-based sibling entry instead, see the note below] PUBLIC TRADE-FLOW
  SIGNAL
Priority: Low-Medium (cheap to capture, speculative value)

Problem:
  kalshi_ws.py subscribes only to ticker + orderbook_delta (line 301);
  Kalshi's public `trade` channel (executed trades feed) is unused. Signed
  taker flow between scans would show when someone with a faster pipeline
  moved first on a model run — useful as a caution flag (widen required
  edge) or confirmation (market converging toward our stale signal).

What the fix looks like:
  Add the trade channel to the WS subscription, accumulate signed flow per
  ticker between scans, expose to analyze_trade() as a small adjustment or
  gate input. Evaluate on paper before giving it any weight.

Why not now:
  - Value unproven; WS client currently only runs during watch mode, so
    coverage between manual cron runs is zero anyway — worth more once the
    bot runs continuously.

When to revisit:
  - Once loop/watch runs continuously again post-Belgium.

UPDATE 2026-08-03 (no live-signal code shipped against this entry -- scope
  redirected, see below): picked up together with SIGNAL GRADUATION IS A
  CONVENTION, NOT A MECHANISM (below), per that entry's own "when to
  revisit" pointer naming this as the next log-only signal. Two things
  invalidated the assumed plan before any code was written, both verified
  live rather than assumed from prior session notes:
  (1) Re-read the SIGNAL GRADUATION entry's full text, not just its
  original "What it would look like" -- found parts (a) and (b) already
  shipped 2026-07-24/2026-07-25 (see that entry's own resolution notes):
  weather_markets.SIGNAL_REGISTRY (11 entries as of this note -- AST-counted
  live, not copied from the 2026-07-25 resolution note's own "9" since 2
  more (market-implied rain, rain monthly-model blend) were added since),
  get_signal_graduation_report(), and `py main.py signals` all exist today,
  already proven against real signals. There is nothing left for a new
  signal to "validate" -- only part (c) (blend-weights dict) remains open,
  deliberately out of scope until a signal actually graduates to a real
  blend weight.
  (2) Re-verified this entry's own trigger live instead of trusting the
  "post-Belgium" framing: traced cron.py's _cmd_cron_body() (cron.py:1135-
  1227, called from cmd_cron() at cron.py:2261) and found it starts a fresh
  KalshiWebSocket per cron cycle, subscribes,
  scans, then unconditionally calls _active_ws.stop() in a finally block
  (cron.py:2297-2304) at the end of *every* cycle -- including under
  `main.py loop`, which just sleeps ~4h between calling cmd_cron again. WS
  coverage between scans is still zero, identical to the gap this entry
  described when written. Cron is genuinely running again post-Belgium
  (TRADING_PAUSED unset, data/cron.log active same-day as this note) -- but
  "running" here means periodic 4h-spaced cycles that tear down their own
  WS connection, not a standing connection. This entry's trigger has NOT
  fired.
  Surfaced both findings to the user via AskUserQuestion before writing any
  code. User chose to redirect this session to the sibling PUBLIC TRADES
  REST BACKFILL entry's own deferred analysis pass instead -- fully
  unblocked today, real data already accumulated, answers the same
  underlying "is signed trade flow predictive" question this entry wants
  without needing the WS mechanism whose own gate hasn't cleared. See that
  entry's 2026-08-03 resolution note below for what shipped and the actual
  finding.
  This entry itself remains fully open and unbuilt -- "When to revisit"
  above is unchanged: still gated on genuinely continuous (not
  periodic-cron-with-teardown) WS coverage, which an always-on host (see
  the VM-move-sequencing notes elsewhere in this file) would actually
  provide.
```

### 2. Pre-existing backlog item (`backlog.txt:12436`)

```
[PARTIALLY RESOLVED -- capture side (2026-07-19) and one of the two
  deferred analysis passes (2026-08-03, "did informed flow precede
  settlement-direction moves") are done; "adverse selection around our own
  fills" is still open, structurally unanswerable right now, see below]
  PUBLIC TRADES REST BACKFILL -- GET /markets/trades AT SETTLEMENT
Priority: was Medium -- closes the exact gap the PUBLIC TRADE-FLOW SIGNAL
  entry admits ("coverage between manual cron runs is zero") without
  needing the always-on host.

RESOLVED 2026-07-19 (the CAPTURE side only, matching the candlestick
  precedent's own "ship the capture early, data accumulates" pattern --
  the ANALYSIS passes this entry's own "What it would look like" describes
  are still deliberately deferred, same as candlestick's own analysis
  passes):
  Did the "storage volume check first" this entry's own "Why not now"
  called for, live, before writing any code: an unauthenticated GET
  against 5 real settled weather tickers (confirming the endpoint really
  is public -- no signing needed, though get_trades signs anyway for
  consistency with every other call in this client) returned 148-940
  trades per market, comfortably inside one page (limit=1000) for a real
  weather market. Also re-verified the entry's own field-name claims
  against Kalshi's live docs (docs.kalshi.com/api-reference/market/
  get-trades) rather than trusting the 2026-07-16 summary: the response
  fields are actually count_fp/yes_price_dollars/no_price_dollars/
  taker_outcome_side/taker_book_side (fixed-point/dollar-suffixed, matching
  the rest of the V2 API), not the plain count/yes_price/no_price/
  taker_side the entry described -- taker_side still exists but Kalshi's
  docs mark it deprecated in favor of taker_outcome_side/taker_book_side,
  so the new code was written against the current, non-deprecated shape.
  Also found min_ts/max_ts ARE real, documented query params (a first
  WebSearch summary claimed they weren't; re-fetching the actual docs page
  directly, not trusting the search summary, showed they are -- another
  instance of [[feedback_reverify_on_pushback]]'s pattern).
  Shipped kalshi_client.get_trades(ticker, min_ts, max_ts) -- cursor-
  paginated exactly like get_markets, but with one real behavioral
  difference found live-testing: Kalshi can return a non-empty cursor on
  what turns out to be the LAST page (an empty trades list on the next
  call is what actually signals "done"), so the pagination loop checks
  `not cursor or not page`, not cursor-truthiness alone like get_markets
  does -- mutation-tested this exact difference (a test using a distinct
  cursor value on the terminal empty page, specifically to isolate this
  check from the separate repeated-cursor guard, which would otherwise
  mask the mutation).
  Added tracker.py's trade_history table (migration v48/v49 -- table +
  index as 2 separate steps, matching price_history's own precedent) +
  log_trades()/get_trade_history(), reusing the existing _fp_count/
  _candle_dollars parsing helpers unchanged (both are already generic
  dict+key fail-soft parsers, not candlestick-specific, despite their
  names). trade_id (Kalshi's own globally-unique per-trade ID) is the
  dedup key -- simpler than price_history's composite-key dedup, which
  existed only because candlesticks have no natural single-field ID.
  Wired into sync_outcomes() immediately after the candlestick backfill,
  identical isolated-try/except/fires-once-per-market shape.
  27 new tests: kalshi_client.get_trades pagination (8, incl. the
  mutation-proof empty-page-with-cursor test and the pre-existing
  repeated-cursor guard reused unchanged); tracker.log_trades/
  get_trade_history (8, incl. dedup-via-unique-trade_id, unparseable-price
  fails soft); sync_outcomes wiring (3, mirroring the 3 existing
  candlestick-backfill tests: backfills-on-settlement, survives-fetch-
  failure, skips-without-open_time). Confirmed on a fresh DB that
  init_db() creates trade_history correctly and PRAGMA user_version lands
  on the new _SCHEMA_VERSION=49. Added get_trade_history to tests/
  test_dead_code_scan.py's allowlist, exact same reasoning as
  get_price_history's existing entry (a tested read accessor with no prod
  call site yet -- the deferred analysis pass is its only future consumer).
  354 tests pass across the full regression sweep; ruff + ruff format +
  mypy clean.
  Not yet wired into anything live -- this is pure capture, matching the
  candlestick precedent exactly. The ENABLEMENT TRIGGER for the deferred
  analysis passes (adverse selection, "did informed flow precede
  settlement moves") is explicitly paired with the candlestick entry's own
  trigger per this entry's original "Why not now" -- check
  `SELECT COUNT(*) FROM trade_history` / `SELECT COUNT(*) FROM
  price_history` (and distinct ticker counts) periodically; both start
  from zero as of this push and only grow from markets settling from now
  on, so there's a real multi-week wait before either analysis pass is
  worth doing.

Problem (as originally scoped, still accurate for historical context):
  The PUBLIC TRADE-FLOW SIGNAL entry (above) is scoped to the WS `trade`
  channel, which only helps while a watch session is running. Verified
  2026-07-16 via docs search: GET /markets/trades is public,
  unauthenticated, cursor-paginated (limit 1-1000), returns
  taker_side/count/yes_price/no_price/created_time per fill.
  kalshi_client.py has no trades endpoint (full method list read today:
  markets/market/orderbook/candlesticks/events/series/balance/positions/
  orders only). That means the complete signed-flow history of every
  settled market is retrievable retroactively -- the same "data
  accumulates regardless of process uptime" property that justified the
  candlestick capture, but with direction (taker_side) that OHLC candles
  lack.

What it would look like: [DONE 2026-07-19 -- capture side only, see
  resolution above; the analysis payoffs below are still deferred]
  kalshi_client.get_trades(ticker, min_ts, max_ts) + a trade_history
  table, wired into tracker.sync_outcomes() right beside the existing
  candlestick backfill (fires once per market at outcome recording,
  isolated try/except, same pattern commit ba3527e established). Analysis
  payoffs ride the already-deferred candlestick analysis passes: adverse
  selection around our fill times (joins against execution_log's
  filled_at/market_mid_at_fill), and "did informed flow precede
  settlement-direction moves" -- the caution-flag hypothesis the WS entry
  wants, testable on history before any live WS work.

Why not now (capture side resolved; analysis passes still apply):
  - Storage volume check first (DONE live 2026-07-19, see resolution --
    148-940 trades/market, well within one page); shares the enablement-
    trigger risk with the candlestick entry -- pair its analysis check-back
    with that entry's existing 2026-07-16 trigger so they're evaluated
    together (both start from zero rows as of this push).

When to revisit:
  - Capture side: N/A, closed. Analysis passes: alongside the PUBLIC
    TRADE-FLOW SIGNAL entry above and the candlestick capture entry's own
    check-back trigger, once both trade_history and price_history have a
    real multi-week window of data.

RESOLVED 2026-08-03 (one of the two deferred analysis passes -- "did
  informed flow precede settlement-direction moves"; the other, adverse
  selection around our own fill times, is still open, see below): picked
  up as part of the same session that redirected PUBLIC TRADE-FLOW SIGNAL
  here (see that entry's 2026-08-03 note above) -- both its own
  WS-continuity trigger and SIGNAL GRADUATION's registry-building scope had
  already been overtaken by events, so the user chose this fully-unblocked
  analysis pass instead, via explicit AskUserQuestion rather than either
  path being assumed.
  Checked live before designing anything: execution_log.orders (198 rows)
  has ZERO rows with filled_at or market_mid_at_fill populated -- no live
  order has ever actually filled (matches ENABLE_MICRO_LIVE being off) --
  so the "adverse selection around our own fills" half is structurally
  unanswerable right now, not just thin. Dropped from this pass per
  explicit AskUserQuestion confirmation rather than built against a 0-row
  table.
  Confirmed trade_history and price_history now have real accumulated data
  (70,362 trade rows / 43 tickers; 13,820 candle rows / 274 tickers; full
  43/43 ticker overlap between the two tables) -- comfortably past a cold
  start.
  Shipped tracker.get_trade_flow_settlement_correlation(
  min_trades_per_market=10, min_candles_per_market=4, min_markets=15,
  min_early_trades=3) -- for each ticker with both trade_history and
  price_history rows, splits the trade series at its own time midpoint
  (half the trades before, half after, using each trade's parsed
  created_time epoch) and computes early signed flow ((yes-taker volume -
  no-taker volume) / total volume in the early half, in [-1, 1], requiring
  at least min_early_trades contributing trades so a single trade at a
  timestamp tie can't swing it to +-1.0) against late price drift (the last
  candle with a real, non-NULL price_close minus the earliest candle at/
  after that same midpoint that also has a real close -- both walks skip
  past NULL closes rather than trusting the first/last candle blindly, and
  candles are filtered to the earliest candle's own period_interval first
  so two OHLC resolutions can never silently interleave), then
  Pearson-correlates across markets using the same manual formula as
  get_recent_city_correlations (matching that function's convention, not
  because scipy is otherwise unavailable in this project -- it is, see
  weather_markets.py's scipy.stats/scipy.optimize imports). Markets below
  the trade/candle/early-trade floors are counted under
  markets_skipped_thin; markets that clear those floors but have no usable
  price at either end of the drift window are counted separately under
  markets_skipped_no_price, so a "thin" report never conflates two
  unrelated failure reasons.
  Real finding, run live against the actual DB: n=42 markets cleared the
  floor (43 considered, 1 skipped thin, 0 skipped for missing price),
  r=-0.035 -- indistinguishable from zero at this sample size. Early signed
  taker flow does NOT show a detectable relationship with each market's
  subsequent price drift in the current dataset. This is informational, not
  dispositive (n=42, single fixed early/late split point per market, no
  significance test attached) -- but it does NOT support building the live
  WS mechanism PUBLIC TRADE-FLOW SIGNAL describes on urgency grounds.
  get_trade_flow_settlement_correlation is a real, callable, tested query,
  not a one-off script -- re-run it as trade_history keeps accumulating
  rather than re-deriving the analysis from scratch next time.
  14 new tests (tests/test_tracker.py TestTradeFlowSettlementCorrelation):
  no-data, perfect 3-market correlation (3 collinear points -> r==1.0
  exactly, verifying the Pearson formula), a zero-variance guardrail
  (identical flows across markets -> r stays None, not a divide-by-zero),
  below-min-markets (n reported, r=None), thin-market skips (too few
  trades / too few candles / zero early volume / below the early-trade-
  count floor), the trade_history-without-price_history join-exclusion
  case, a mixed-period_interval-candles filter case, and 3 tests directly
  targeting the NULL-price-handling fix below.
  Independent Agent(opus, effort=high) review (before push, per standing
  workflow) reproduced the live result independently (byte-identical
  reimplementation) and found 1 HIGH, 4 MEDIUM, and several LOW/informational
  issues in the first draft -- all fixed, not just the HIGH one:
  (1) HIGH -- the new function had no dead-code-scanner allowlist entry
  (tests/test_dead_code_scan.py), which would have failed CI on push exactly
  like the count_fn miss noted in an earlier session's `9eec753` fix --
  added, matching get_price_history/get_trade_history's existing entries.
  (2) HIGH-severity-in-practice correctness bug -- the first draft used
  candles[-1]["price_close"] directly for the "last" price. 24% of all
  price_history rows have a NULL price_close (a period with no trades), and
  13 of the 43 real join tickers -- among the highest-volume markets in the
  set -- had a NULL close on their literal final candle, so they were
  silently mis-counted as "thin" and dropped (n was 29, not 42, before this
  fix; r was -0.042, not -0.035). Fixed by walking backward from the end
  until a real close is found, recovering all 13 markets.
  (3) MEDIUM -- the matching fix on the other end: the first draft took the
  first candle at/after the trade-series midpoint regardless of whether
  that specific candle had a real price, silently substituting an unrelated
  index-based fallback price when it didn't. Fixed to walk forward past any
  NULL-close candles at that boundary too.
  (4) MEDIUM -- the first draft's fallback (when no candle at/after the
  midpoint existed at all) computed drift entirely from candles before the
  midpoint, which could invert the lead-lag relationship the function
  exists to test (measuring a window that precedes the "early flow" window
  rather than following it). Removed the fallback entirely -- such a market
  is now skipped and counted under the new markets_skipped_no_price
  counter instead of silently contributing a wrong-direction data point.
  (5) MEDIUM -- docstring and a single skip counter undercounted/mislabeled
  the actual skip reasons once (2)-(4) existed -- split into
  markets_skipped_thin and markets_skipped_no_price and rewrote the
  docstring to describe all three real skip paths.
  (6) LOW -- the created_time parse only caught ValueError; broadened to
  also catch AttributeError/TypeError so a future non-string created_time
  (e.g. if Kalshi ever changed format) fails soft instead of crashing the
  whole report.
  (7) LOW -- added an explicit min_early_trades=3 floor (a market could
  previously reach the volume-only floor via a single early trade at a
  timestamp tie); LOW -- added a period_interval filter so two OHLC
  resolutions for one ticker could never silently interleave (not observed
  live as of this writing, but not structurally prevented either); LOW --
  gave the function an explicit `-> dict[str, int | float | None]` return
  type instead of a bare `dict`; LOW -- reworded a docstring line that
  implied scipy was unavailable in this project (it isn't -- the manual
  Pearson formula matches get_recent_city_correlations' own convention,
  nothing else) and another that overstated "settlement" when the measured
  endpoint is the last logged candle, not necessarily literal settlement.
  Two of the new tests initially had real gaps caught only by re-verifying
  the review's own mutation-testing claims by hand, not just trusting the
  review's summary: the first version of a NULL-close-boundary mutation
  test silently passed because its candle timestamps were small toy
  integers nowhere near the trade series' real 2026 epoch values, so the
  time-aligned code path never actually executed; and the first version of
  the period_interval-filter test used only 2 markets, which is
  mathematically always exactly r=+-1 regardless of the underlying values
  (any 2 distinct points are collinear), so it could not have caught the
  filter being removed entirely -- both rebuilt (real epoch-aligned
  timestamps; a 3-market design where a wrong value measurably moves r off
  1.0) and re-confirmed against the actual mutation.
  350 tests pass across tests/test_tracker.py (was 344); ruff + ruff format
  + mypy clean on tracker.py, tests/test_tracker.py, and
  tests/test_dead_code_scan.py (one pre-existing, unrelated ruff-format nit
  elsewhere in test_tracker.py left untouched -- confirmed via diff scope,
  not introduced by this change).
  Zero live-trading-behavior change: read-only query function, no existing
  code calls it (by design -- see the dead-code-scanner allowlist entry),
  TRADING_PAUSED/ENABLE_MICRO_LIVE untouched, no order was placed or
  closed.
  Still open: the "adverse selection around our own fills" half (execution_
  log.orders has zero fills to analyze -- revisit once ENABLE_MICRO_LIVE is
  ever flipped and real live fills start accumulating).

When to revisit (adverse-selection half only -- flow-vs-settlement analysis
  above is closed):
  - Once execution_log.orders has real filled_at/market_mid_at_fill rows to
    join against -- currently 0 of 198.
```

### 3. Pre-existing backlog item (`backlog.txt:12843`)

```
[MARKET_LIFECYCLE_V2 WS CHANNEL -- LISTING-TIME AWARENESS]
Priority: Low -- real timing edge, but structurally blocked behind the
  always-on host decision.

Problem:
  Confirmed by direct docs fetch 2026-07-16, Kalshi's WS channel list is
  orderbook_delta, ticker, trade, fill, market_positions,
  market_lifecycle_v2, multivariate_market_lifecycle, multivariate,
  communications, order_group_updates, user_orders, cfbenchmarks_value,
  pyth_value -- this bot subscribes to exactly two (kalshi_ws.py:362) and
  the backlog covers trade/fill/order_groups, but market_lifecycle_v2
  (and user_orders) appear nowhere in repo or backlog (grep: zero hits
  for market_lifecycle). New daily temperature markets are discovered
  only when the next REST scan happens (get_weather_markets + 60s
  _MARKETS_CACHE_TTL :744-745, on cron cadence) -- hours after listing.
  Freshly listed markets have the widest spreads and least-informed
  quotes; the first maker quote at model fair value gets the best prices
  of the market's life, and the deferred candlestick entry-timing
  analysis can verify this from data already being captured (candles
  cover the full open->close window, so "edge vs hours-since-open" is
  computable today for settled markets).

What it would look like:
  Subscribe market_lifecycle_v2 in the (future) always-on watcher; on a
  new KXHIGH*/KXLOW* listing, run analyze_trade for that market
  immediately and post a resting maker order if gates pass. Cheap
  precursor available now with zero new infra: use the existing candle
  history (tracker.get_price_history) to measure whether early-window
  prices were actually more mispriced vs settlement -- do that before
  building anything live.

Why not now:
  - Meaningless without the always-on host (explicitly parked in the
    MOVE OFF LOCAL CRON entry, trigger = live trading imminent); do the
    candle-based "is early entry actually better" check first -- if edge
    doesn't decay with market age, this whole candidate dies cheaply.

When to revisit:
  - Once the always-on host decision executes. Note user_orders as a
    sibling channel to fold into the already-deferred fill-channel work
    when that resumes.

======================================================
ARCHITECTURE & DESIGN-DEBT CANDIDATES -- 2026-07-16 whole-program scouting
session (architecture + refactor halves; see the section above for the
feature/signal half from the same session). Same three-Fable-pass sourcing
and verification discipline as above.
======================================================
```

## Process -- follow the 29-step implementation workflow from memory (`feedback-implementation-workflow`) exactly, in order

This batch is documentation/test/low-risk-code only. If every item you actually touch turns out to be a small, mechanically-verifiable diff with no live-order/live-money/safety-gate surface and no multi-file span, steps 11-12 may collapse to the LOW tier (a single self-review pass + one Agent check instead of a dedicated opus effort:high spawn). Re-assess per item -- don't downgrade the whole batch by default if one item in it turns out bigger than expected.

Non-negotiable highlights regardless of tier: (1) re-verify every item's claims against live state before trusting this prompt's transcription -- re-read the actual current code/docs at the cited locations. (2) Research the real code structure before designing a fix. (3) Surface genuine design decisions via `AskUserQuestion`, don't guess. (7) Write real, mutation-tested tests for anything code-level (via the Edit tool for mutation reverts, never a string-replace script). (8-9) Scoped test run, then lint/mypy. (11) Independent opus review at `effort: high` before push for anything live-money-adjacent -- and if that review's findings get fixed, the fix itself needs its own independent review too. (13) Address every review finding regardless of severity. (14-16) Compressed-pointer memory update before commit; explicit confirmation before commit/push; `git fetch` + rebase-if-diverged immediately before the actual push -- this matters more than usual here since other batches may be pushing to the same branch/master concurrently. (19) If `backlog.txt` gets edited, run `python backlog_index.py` afterward and confirm the entry landed correctly in `BACKLOG_OPEN.md`. (29) Refresh `graphify-out/` (AST always; semantic `--update` too if any item is non-LOW-tier) before committing, if it exists -- scope the refresh to just the files this batch actually changed, not a full incremental sweep (a full sweep pulls in every other in-flight batch's uncommitted work too).

Full step list and tiering rules live in memory under `feedback-implementation-workflow` -- apply all 29 steps in order. **If this memory entry isn't loaded in your session**, its full text is preserved at `C:\Users\thesa\.claude\projects\C--Users-thesa-claude-kalshi\memory\feedback_implementation_workflow.md` -- read it directly rather than proceeding without it.
