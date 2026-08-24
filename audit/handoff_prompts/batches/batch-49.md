# Batch 49: Fee-change monitor + queue-position fill-quality (Track A — execution/API)

## Context

Repo: weather1. Source: Expansion Dossier B1 (score 8.2, rank 1) + B7 (6.8, rank 8), Rev 4, 2026-08-24. Assumes batches 31-48 landed — specifically batch 31 (order_executor crash-recovery/cid fixes) and batch 33 (cron task reliability); verify both actually landed before touching order_executor.py/cron.py.

Files: `kalshi_client.py`, `order_executor.py`, `execution_log.py`, `cron.py` (one daily-task registration), `notify.py` (alert wiring only). Parallel-safe with batches 50-52 (no file overlap).

Ceremony: full 29-step workflow, opus review effort=high — kalshi_client.py and order_executor.py are live-order-adjacent even though every addition here is read-only.

## Item 1 — Fee-change monitor (dossier B1)

**Resolved background (do NOT re-investigate):** the 7.7.26 fee schedule PDF was read directly on 2026-08-24 — weather series pay **$0 maker** (maker multiplier defaults to 0; no weather/climate series in the Non-Standard Fees table; the tiered-bps maker tables are perps-only; taker default = standard 7% formula). The bot's `KALSHI_MAKER_FEE_RATE=0` and `kalshi_fee_rate=0.07` are both confirmed correct. What this item builds is the standing guard: Kalshi enables a per-series maker fee by adding ONE table row, and this bot's economics rest on that default staying 0.

Build:
1. A `get_fills` (or equivalent — check what kalshi_client.py already exposes before adding) authenticated read of recent fills, and a daily cron check asserting every maker fill's fee field is $0 for tracked weather series. Nonzero fee → `notify.send_system_alert` (use the existing halt-transition edge pattern from alerts.py so it fires once, not every cycle) + a log line naming the ticker/series/fee.
2. Optionally (cheap, do it if the page is scrape-tolerant): a weekly check of https://kalshi.com/fee-schedule for scheduled upcoming changes mentioning tracked series. NOTE: kalshi.com Cloudflare-blocks non-interactive fetches (429, confirmed repeatedly 2026-08-23/24) — if the fetch 429s, log-and-skip quietly, do NOT retry-loop or alert on the 429 itself. The fills-based check in (1) is the real guard; this is best-effort.

**Go/no-go validation (run first, <1 hr):** query recent fills for the account (demo env has fills from paper-adjacent flows only — if the account has zero real fills, assert against an empty set and note it; the check still ships as a forward guard). Confirm the fee field name/shape on a real fill record before writing the assert.

Why-not honesty from the dossier: this is monitoring that may never fire. Keep it small — one cron task, one alert, no config surface.

## Item 2 — Queue-position reading for fill-quality (dossier B7)

**Existing backlog disclosure:** fill-quality instrumentation is a known-open backlog item and `price_improvement` logging already exists in predictions.db. This item is the API-capability extension: officially documented endpoints `GET /trade-api/v2/portfolio/orders/{order_id}/queue_position` and bulk `GET /trade-api/v2/portfolio/orders/queue_positions` (docs.kalshi.com API reference, verified 2026-08-24; "number of contracts that need to be matched before this order receives a partial or full match, price-time priority").

Build:
1. Client wrapper(s) in kalshi_client.py, following the existing V2-endpoint patterns (the legacy `/portfolio/orders` mutation deprecation does not apply — these are reads).
2. Log queue position at maker-order placement and (bulk endpoint) once per recovery/poll pass for resting orders, into execution_log (new column or table — follow whatever schema convention batch 31 left).
3. Do NOT wire it into reprice/chase decisions in this batch — that belongs to the open repricing backlog item; this batch only makes the data exist so that item can be informed instead of blind. Note the linkage in backlog.txt.

**Go/no-go validation (run first, <1 day):** with the demo key, place one resting demo order via the existing demo-safe path, GET its queue position, confirm response shape and the endpoint's token cost via `GET /trade-api/v2/account/endpoint_costs`. If the endpoint is tier-gated above this account's tier → file to backlog and stop item 2 (item 1 still proceeds).

## Constraints

- Read-only API additions; zero order-mutation changes. If a change wants to touch `place_order`/cancel/amend paths, it's out of scope — file it.
- Rate budget: the 2026 token-cost rate-limit system — bulk queue-position once per poll pass, not per order.
- Scoped tests: `tests/test_execution_log*.py`, `tests/test_order_executor*.py` (existing files touching the edited functions), new test files for the monitor. Grep tests/ for transitive callers of any edited function before finalizing the list. **Never the full suite.**
- backlog.txt: file the reprice-linkage note; run `python backlog_index.py`.
