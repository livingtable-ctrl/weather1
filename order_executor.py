"""order_executor.py — Automated order placement and lifecycle management.

Extracted from main.py (P3-9). Contains the financial-critical execution path:
  _auto_place_trades, _place_live_order, _poll_pending_orders, _check_early_exits
and their supporting helpers.

Importing from main.py is intentionally avoided to prevent circular imports
(main.py imports cron.py which imports from here via CronContext).
"""

from __future__ import annotations

import json
import logging
import math
import os
import time
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

import execution_log
from ab_test import ABTest as _ABTest
from colors import dim, green, red, yellow
from kalshi_client import OrderStatusUnknownError, compute_client_order_id
from positions import Position
from positions import check_breakeven_stops as check_breakeven_stops
from positions import check_stop_losses as check_stop_losses
from positions import liquidation_price as _liquidation_price
from positions import update_peak_profits as _shared_update_peak_profits
from utils import (
    EXIT_MIN_HOLD_HOURS,
    EXIT_SETTLEMENT_GATE_HOURS,
    MAX_DAILY_SPEND,
    MAX_SAME_DAY_SPEND,
    MAX_VAR_DOLLARS,
    MIN_EDGE,
    MODEL_EXIT_SHIFT_PP,
    YES_ASK_KEYS,
    YES_BID_KEYS,
    coalesce_market_price,
    get_paper_min_edge,
    is_trading_paused,
)
from weather_markets import (
    _KXRAIN_MONTHLY_CITY,
    _KXSNOW_MONTHLY_CITY,
    _KXTEMP_HOURLY_CITY,
    _hourly_gates_active,
    _hurricane_count_gates_active,
    _hurricane_next_event_gates_active,
    _rain_gates_active,
    _snow_gates_active,
    _storm_order_gates_active,
    _var_from_ticker_prefix,
    analyze_trade,
    enrich_with_forecast,
    get_weather_markets,
    is_hurricane_count_ticker,
    is_hurricane_next_event_ticker,
    is_storm_order_ticker,
    parse_market_price,
)

if TYPE_CHECKING:
    from positions import PositionStore

_log = logging.getLogger("main")

_MIN_EDGE_AB_TEST = _ABTest(
    name="min_edge_variants",
    variants={"low": 0.05, "medium": 0.07, "high": 0.09},
    max_trades_per_variant=50,
)

# Batch-22 item 2 (opus review follow-up, F1/F2): _recover_pending_orders'
# 'sent'-row promotion must not touch a row still genuinely in flight -- see
# that function's own comment at the promotion loop for the full reasoning.
_SENT_PROMOTION_MIN_AGE_MINUTES = 5

# ---------------------------------------------------------------------------
# Forecast cycle
# ---------------------------------------------------------------------------


def _current_forecast_cycle() -> str:
    """Return a string identifier for the current NWS forecast cycle.

    NWS model runs are at 00z and 12z (midnight and noon UTC).
    Returns a string like '2025-05-15_12z' so orders within the same
    forecast cycle are deduplicated.
    """
    now = datetime.now(UTC)
    cycle_hour = 12 if now.hour >= 12 else 0
    return f"{now.strftime('%Y-%m-%d')}_{cycle_hour:02d}z"


# ---------------------------------------------------------------------------
# Paper order shim (module-level so tests can patch order_executor.place_paper_order)
# ---------------------------------------------------------------------------


def place_paper_order(ticker, side, qty, entry_price, **kwargs):
    from paper import place_paper_order as _ppo

    return _ppo(ticker, side, qty, entry_price, **kwargs)


# ---------------------------------------------------------------------------
# Price helpers
# ---------------------------------------------------------------------------
#
# Price coalescing (cents-int vs dollar-string field names) lives in
# utils.coalesce_market_price -- consolidated 2026-07-19 from what used to be
# a local copy here (see backlog.txt's KALSHI CENTS/DOLLARS PRICE
# NORMALIZATION entry).


def _midpoint_price(market: dict, side: str) -> float:
    """Return midpoint of current bid/ask for the given side, rounded to 2dp.

    Handles both legacy cents fields (yes_bid/yes_ask) and current dollar fields
    (yes_bid_dollars/yes_ask_dollars) — see utils.coalesce_market_price.
    """
    yes_bid = coalesce_market_price(market, *YES_BID_KEYS)
    yes_ask = coalesce_market_price(market, *YES_ASK_KEYS)
    if yes_ask == 0.0 and "yes_ask" not in market and "yes_ask_dollars" not in market:
        yes_ask = 1.0  # preserve prior default (100¢) when ask is genuinely absent
    if side == "yes":
        bid, ask = yes_bid, yes_ask
    else:  # "no"
        bid, ask = 1.0 - yes_ask, 1.0 - yes_bid
    if bid > ask:
        bid, ask = ask, bid  # guard against inverted spread from API
    return round((bid + ask) / 2, 2)


def _get_current_book(client, ticker: str) -> dict | None:
    """Return a market-price-shaped dict ({"yes_bid": ..., "yes_ask": ...}) with
    the freshest available top-of-book for ticker, or None if unavailable.

    Tries the WS ticker-tick cache first (fast, no API call — already proven
    in production, feeds the flash-crash gate today); falls back to a fresh
    REST get_market() call (the same source _midpoint_price/_place_live_order
    already use for real order pricing) when the WS cache is missing/stale.
    Deliberately does NOT use get_orderbook() -- get_market()'s yes_bid/
    yes_ask are the authoritative top-of-book this bot already prices real
    orders from; parsing raw orderbook levels would just be reinventing that
    with more room for a sign/side error.
    """
    try:
        from kalshi_ws import get_cached_book

        cached = get_cached_book(ticker)
        # kalshi_ws.parse_message's ticker branch defaults a missing side to
        # 0.0, not None (yes_ask_str = inner.get("yes_ask") or "0") -- a
        # one-sided book (no real ask) still passes an `is not None` check.
        # Require both sides genuinely positive, matching how the rest of
        # this codebase already treats 0.0 as "no real quote" (see
        # _midpoint_price's own yes_ask==0.0 guard).
        if (
            cached
            and (cached.get("yes_bid") or 0) > 0
            and (cached.get("yes_ask") or 0) > 0
        ):
            return {"yes_bid": cached["yes_bid"], "yes_ask": cached["yes_ask"]}
    except Exception as exc:
        _log.debug("_get_current_book: WS cache lookup failed for %s: %s", ticker, exc)

    try:
        market = client.get_market(ticker)
        if parse_market_price(market)["has_quote"]:
            return market
    except Exception as exc:
        _log.debug("_get_current_book: REST get_market failed for %s: %s", ticker, exc)
    return None


def _count_open_live_orders() -> int:
    """Count open live positions — enforces max_open_positions limit.

    AUD-0009/AUD-0012: was `status == 'pending'` over a LIMIT-500 fetch, so
    (a) a filled (no longer pending) live position stopped counting the
    moment it filled, and (b) a genuinely still-pending order could fall
    outside the fixed-size window entirely once enough other orders
    accumulated afterward. Fixed as the union of both real "open" states,
    each via its own unbounded query:
      - still-resting entry orders (status='pending') -- a GTC entry order
        represents real capital that could fill at any moment, and
        test_prelog.py's F1 regression test deliberately established that a
        placed-but-unfilled order must count here.
      - filled-but-unsettled positions (get_filled_unsettled_live_orders) --
        the gap AUD-0009 found: these stopped counting once no longer
        'pending', with nothing else picking them back up.
    closes_position_id IS NULL on the pending half excludes a pending
    protective EXIT order's own row (an IOC sell placed with
    closes_position_id=<the position it's closing>, per
    _exit_live_position's own docstring) -- without this exclusion, a
    position mid-exit would be double-counted: once via
    get_filled_unsettled_live_orders (still open, not yet settled) and
    again via its own brief pending exit-order row.
    """
    # AUD-0007 follow-on: an 'unknown' row (placement outcome ambiguous, see
    # kalshi_client.OrderStatusUnknownError) could turn out to be a real fill
    # once reconciled -- excluding it here would let max_open_positions be
    # silently exceeded whenever ambiguous orders accumulate and later
    # resolve. closes_position_id exclusion mirrors the pending-entries logic
    # above for the same reason (an ambiguous protective EXIT order must not
    # be double-counted against the position it was closing).
    pending_entries = sum(
        1
        for o in execution_log.get_pending_live_orders()
        if o.get("closes_position_id") is None
    ) + sum(
        1
        for o in execution_log.get_unknown_live_orders()
        if o.get("closes_position_id") is None
    )
    return pending_entries + len(execution_log.get_filled_unsettled_live_orders())


def _resolve_micro_live_config(live_config: dict | None) -> dict:
    """Resolve the config micro-live enforces its daily-loss limit against.

    F2: micro-live only ever runs from _auto_place_trades' paper (live=False)
    branch — live_config is always None on every real call path (cron never
    passes live=True; watch --auto --live's live_config is only populated on
    the OTHER branch, which micro-live never reaches). Passing that None
    straight to (live_config or {}).get("daily_loss_limit", 0.0) silently
    resolved to 0.0, which the check treats as "no limit configured" and
    never trips. Load the real live config directly instead.
    """
    if live_config is not None:
        return live_config
    from main import _load_live_config

    return _load_live_config()


_LIVE_BALANCE_CACHE_TTL_SECS = 5.0
_LIVE_BALANCE_CACHE_ATTR = "_weather1_live_balance_cache"


def _resolve_live_balance(client) -> float:
    """Fetch the real Kalshi balance (dollars) for live Kelly sizing.

    F4: live_config never has a "balance" key (_LIVE_CONFIG_DEFAULT doesn't
    define one), so a static config-based override was always inert — Kelly
    sizing silently fell back to the paper balance for every live trade.
    Returns 0.0 (meaning "use the paper balance") on any fetch failure,
    matching the prior fallback behavior rather than blocking placement.

    2nd-round-opus-review-caught (M-A): AUD-0001's exposure-denominator fix
    made this function (via paper._live_effective_balance) get called
    several times per check_position_limits/portfolio_kelly_fraction
    invocation, and once per correlated open position inside
    covariance_kelly_scale -- a 15-candidate cron cycle with several
    correlated positions could fire 60+ uncached authenticated
    GET /portfolio/balance calls through the shared read circuit breaker,
    risking tripping it and then having get_market() price refetches on
    the SAME breaker silently degrade too. Cached for
    _LIVE_BALANCE_CACHE_TTL_SECS (5s) -- short enough that sizing/exposure
    decisions never act on a materially stale balance, long enough to
    collapse an entire candidate's worth of repeated calls (and most of a
    cron cycle's) into one real fetch.

    Cache lives as an attribute ON the client object itself (not a
    module-level dict keyed by id(client)) -- id() is a memory address
    CPython can and does reuse once an object is garbage-collected, which
    would risk one client instance silently reading a stale balance cached
    under a previous, unrelated, already-freed client that happened to
    reuse the same address (a real risk across a long-running test suite's
    many short-lived mock clients). Attaching the cache to the object
    itself ties its lifetime to the object's own lifetime -- no reuse
    possible, and neither KalshiClient nor unittest.mock.MagicMock use
    __slots__, so this is safe on both.

    Reads/writes the cache via client.__dict__ directly, NOT
    getattr(client, attr, default)/setattr -- verified empirically that
    MagicMock's own __getattr__ auto-vivifies (and returns a fresh child
    Mock for) ANY unset attribute name rather than ever raising
    AttributeError, so getattr(mock, x, default) never actually returns
    `default` for a MagicMock, silently defeating the "not cached yet"
    check and returning a Mock object in place of a real float. Explicitly
    set attributes (via normal attribute assignment, which MagicMock also
    supports for real values) DO land in __dict__, while auto-vivified
    ones don't -- so checking __dict__ directly correctly distinguishes
    "genuinely cached" from "just accessed."

    2nd-round-opus-review-caught (L-3, documented not fixed): does not
    check client.base_url. A client pointed at Kalshi's demo environment
    would have its play-money balance folded into paper._exposure_denom's
    combined denominator, silently loosening every exposure cap for that
    call. Deliberately left as-is rather than gated to PROD_BASE only --
    this function's existing pre-AUD-0001 purpose (live Kelly sizing) may
    be intentionally exercised with a demo client during testing/dry-runs,
    and restricting it here would change that established behavior too,
    not just the new exposure-cap usage. Narrow in practice (requires
    deliberately running with a demo client while relying on production-
    scale exposure caps); worth a dedicated look if it ever bites.
    """
    now = time.monotonic()
    cached = vars(client).get(_LIVE_BALANCE_CACHE_ATTR)
    if cached is not None and now - cached[1] < _LIVE_BALANCE_CACHE_TTL_SECS:
        return cached[0]
    try:
        bal_data = client.get_balance()
        api_balance_cents = bal_data.get("balance")
        if api_balance_cents is not None:
            balance = float(api_balance_cents) / 100.0
            try:
                setattr(client, _LIVE_BALANCE_CACHE_ATTR, (balance, now))
            except Exception:
                pass  # some client stand-in that rejects attribute writes -- fine, just no caching
            return balance
    except Exception as exc:
        _log.warning(
            "_resolve_live_balance: could not fetch live balance — "
            "falling back to paper balance for sizing: %s",
            exc,
        )
    # Deliberately NOT caching the 0.0 fallback -- a transient failure
    # should retry on the very next call, not pin every caller to "no live
    # balance" for the rest of the TTL window.
    return 0.0


# ---------------------------------------------------------------------------
# Startup crash recovery
# ---------------------------------------------------------------------------


def _kalshi_status_to_internal(
    api_status: str, fill_count: float | None = None
) -> str | None:
    """Translate a Kalshi order status into this bot's own execution_log
    status vocabulary, or None if it isn't a resolved terminal status.

    Kalshi's real status enum is resting/canceled/executed (there is no
    "filled" or "expired" -- confirmed against Kalshi's API docs 2026-07-09).
    execution_log.get_filled_unsettled_live_orders() hardcodes a SQL literal
    match on 'filled', so "executed" must be translated to "filled" here
    rather than passed through as Kalshi's own term -- storing "executed"
    directly would silently break that settlement-tracking query.

    F9: Kalshi has no distinct "partially filled" status -- a limit order
    that fills some contracts and then gets canceled (for the remainder)
    reports "canceled" with a nonzero fill count. Passed fill_count lets us
    promote that case to "filled" so it still reaches the settlement loop;
    otherwise a real, live exchange position is silently dropped and never
    settled or counted toward P&L.
    """
    if api_status == "executed":
        return "filled"
    if api_status == "canceled":
        return "filled" if fill_count else "canceled"
    return None


def _to_fill_count(raw: str | int | float | None) -> int | None:
    """Parse Kalshi's fill_count_fp field (a fixed-point-formatted string,
    e.g. "3.00") into an int contract count, or None if absent/unparseable.

    F9: order_executor previously read a "fill_quantity" key that Kalshi's
    API never returns -- the real field is "fill_count_fp" (confirmed
    against the same "order" shape main.py already reads fill_count_fp
    from). The old code always fell back to the full requested quantity,
    silently overstating settled P&L on any partial fill.
    """
    if raw is None:
        return None
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return None


def _settle_recovered_exit_order(
    exit_row_id: int, exit_row: dict, fill_count: int
) -> bool:
    """Settle the POSITION a recovered 'unknown' EXIT order actually closed.

    Opus review follow-up (HIGH): _recover_pending_orders' unknown-row loop
    only updated the exit order's OWN row status to 'filled' -- unlike
    _exit_live_position (the live path this mirrors), it never called
    execution_log.record_live_exit_fill on the POSITION the exit closed
    (identified via exit_row["closes_position_id"]). Without this, that
    position stays status='filled'/settled_at=NULL forever: still returned
    by get_filled_unsettled_live_orders() as open even though it was
    genuinely sold, so the exit scanner keeps placing fresh real SELL
    orders against it every cycle, and its true P&L never reaches the tax
    CSV / PnL summary.

    Returns True if it's safe for the caller to now mark the exit row's own
    status 'filled' (settlement succeeded, OR the position was already
    settled/reduced by a concurrent writer -- either way this exit fill
    genuinely happened on the exchange, so the row's own status must still
    reflect that). Returns False if settlement needs to be retried on a
    LATER recovery pass -- round 2 opus review caught that round 1 wrote
    the exit row's own status to 'filled' BEFORE calling this, unconditionally,
    making any settlement failure here permanent (get_unknown_live_orders()
    only selects status='unknown', so a row that already left that status
    was never revisited). The caller is responsible for reverting the row
    back to 'unknown' on a False return.
    reason is recorded as "recovered_exit" since the original protective
    reason (stop_loss/breakeven/model_exit) is a call-time-only parameter
    never persisted on the row itself, so it's genuinely unknown by the
    time a later recovery pass resolves this.
    """
    position_id = exit_row.get("closes_position_id")
    if position_id is None:
        _log.warning(
            "[Recovery] exit row %d: no closes_position_id on this row — cannot settle",
            exit_row_id,
        )
        return False
    position_row = execution_log.get_order_by_id(position_id)
    if not position_row:
        _log.warning(
            "[Recovery] exit row %d: referenced position %s not found — "
            "cannot settle, will retry next recovery pass",
            exit_row_id,
            position_id,
        )
        return False
    if position_row.get("settled_at"):
        # Already settled by some other path (e.g. a manual cmd_order sell
        # raced this recovery) -- nothing left to do, but this exit fill
        # genuinely happened, so the caller may still mark its own row filled.
        return True

    qty = position_row.get("fill_quantity") or position_row.get("quantity")
    entry_price = position_row.get("price")
    exit_price = exit_row.get("price")
    if not qty or entry_price is None or exit_price is None:
        _log.warning(
            "[Recovery] exit row %d: position %s missing qty/entry_price, or "
            "exit row missing its own price — cannot settle",
            exit_row_id,
            position_id,
        )
        return False
    position = {"id": position_id, "quantity": qty, "entry_price": entry_price}

    try:
        pnl, fully_closed = execution_log.record_live_exit_fill(
            position, fill_count, exit_price, reason="recovered_exit"
        )
    except RuntimeError as _race_err:
        # record_live_exit_fill's own atomic settled_at/quantity guards lost
        # this race to a concurrent writer -- the POSITION's bookkeeping is
        # someone else's now, but this exit order's own fill still happened,
        # so it's still safe (and correct) to mark this row's own status.
        _log.warning(
            "[Recovery] exit row %d: settlement lost a race (%s) — position "
            "already settled/reduced by a concurrent writer",
            exit_row_id,
            _race_err,
        )
        return True
    except Exception as _settle_exc:
        # Opus review follow-up (round 2): previously only RuntimeError was
        # caught here -- anything else (e.g. sqlite3.OperationalError from
        # a locked DB) escaped uncaught, and by the time it reached the
        # loop's outer except, the caller had ALREADY written 'filled' to
        # this row (round 1's ordering), permanently removing it from
        # get_unknown_live_orders(). Now genuinely retryable: caught here,
        # returns False, and the caller reverts this row back to 'unknown'.
        _log.warning(
            "[Recovery] exit row %d: settlement failed (%s) — will retry "
            "next recovery pass",
            exit_row_id,
            _settle_exc,
        )
        return False
    if not fully_closed:
        # Mirrors _exit_live_position's partial-fill branch: the position
        # row stays open at its reduced size (record_live_partial_exit,
        # called inside record_live_exit_fill above); THIS exit order's own
        # row separately gets its own pnl/exit_price recorded so the sold
        # lot counts toward export_live_tax_csv/get_live_pnl_summary.
        execution_log.record_live_early_exit(
            exit_row_id, exit_price, "recovered_exit", pnl
        )
    _log.info(
        "[Recovery] exit row %d: settled recovered exit for position %s "
        "(pnl=%.2f, fully_closed=%s)",
        exit_row_id,
        position_id,
        pnl,
        fully_closed,
    )
    return True


def _recover_pending_orders(client) -> None:
    """Reconcile 'pending', 'sent', AND 'unknown' execution_log rows against
    the Kalshi API at startup (and every subsequent call site -- cron.py's
    own cycle, run_trade_cycle(), and cmd_watch's standalone call,
    AUD-0013).

    A crash in the ~50ms window between pre-logging an order and the API call
    leaves a phantom 'pending' row that permanently blacklists the ticker via
    dedup guards. 'unknown' rows (AUD-0007) are a distinct case: the create
    call itself failed AND reconciliation couldn't confirm either way, so
    there's no order_id to poll, only a client_order_id to re-check. 'sent'
    rows (batch-22 item 2) are a third case: log_order()'s own transient
    pre-placement default, left behind by a crash before ANY log_order_result
    call (main.cmd_order's own pre-log) or by this function's own pending-row
    "no order_id" fallback below -- promoted to 'unknown' (when a
    client_order_id was captured at pre-log time) so they fall into the same
    reconciliation as genuine 'unknown' rows instead of being a dead end.
    """
    # AUD-0012: dedicated unbounded query instead of a LIMIT-200-of-everything
    # fetch filtered in Python -- the fixed window could silently evict a
    # genuinely still-pending live order once enough other orders (mostly
    # paper) accumulated afterward.
    pending = execution_log.get_pending_live_orders()
    if pending:
        _log.info(
            "[Recovery] Checking %d pending live order(s) against Kalshi API",
            len(pending),
        )
    for order in pending:
        row_id = order["id"]
        ticker = order.get("ticker", "?")
        try:
            response = order.get("response")
            if response:
                if isinstance(response, str):
                    response = json.loads(response)
                # kalshi_client.place_order() now returns the flat
                # get_order()-shaped dict directly (V2 order-endpoint
                # migration -- no more {"order": {...}} wrapper).
                order_id = response.get("order_id") if response else None
            else:
                order_id = None

            if not order_id:
                # No order_id stored — crash may have happened before OR after the
                # API call (we can't tell). Use 'sent' so dedup blocks re-placement
                # for 7 days rather than risking a duplicate live order.
                # Batch-22 item 2: response=response (not omitted) preserves
                # whatever this row's pre-log already stored -- since every
                # live pre-log call site now stashes client_order_id in
                # response BEFORE calling place_order (see
                # kalshi_client.compute_client_order_id), that id survives
                # this transition instead of being wiped by
                # log_order_result's unconditional response overwrite (it
                # does not COALESCE). The 'sent'-row loop below picks this
                # row up on this same pass (it runs after this loop
                # completes) and re-checks it against Kalshi via that id,
                # instead of this being a dead end.
                execution_log.log_order_result(
                    row_id,
                    status="sent",
                    response=response,
                    error="no order_id at recovery — treated as sent to prevent duplicate",
                )
                _log.warning(
                    "[Recovery] %s row %d: no order_id — marked sent", ticker, row_id
                )
                continue

            result = client.get_order(order_id)
            api_status = result.get("status", "")
            _fill_count = _to_fill_count(result.get("fill_count_fp"))
            if api_status == "resting":
                # "pending" (not "placed") — every downstream lifecycle consumer
                # (fill polling, GTC cancel, max_open_positions, PnL summary)
                # filters on status="pending"; "placed" was invisible to all of them.
                # log_order_result() does an unconditional column UPDATE, so
                # omitting response= here would overwrite it with NULL --
                # _poll_pending_orders' own pending-row filter requires
                # o.get("response") (it's where order_id lives), so that
                # would silently re-orphan the very order this recovery
                # path exists to reattach to the lifecycle.
                execution_log.log_order_result(
                    row_id, status="pending", response=response
                )
                _log.info("[Recovery] %s row %d: resting → pending", ticker, row_id)
            elif (
                _internal_status := _kalshi_status_to_internal(api_status, _fill_count)
            ) is not None:
                execution_log.log_order_result(
                    row_id, status=_internal_status, fill_quantity=_fill_count
                )
                _log.info(
                    "[Recovery] %s row %d: resolved to %s (kalshi status=%s)",
                    ticker,
                    row_id,
                    _internal_status,
                    api_status,
                )
            else:
                _log.warning(
                    "[Recovery] %s row %d: unknown API status %r — leaving pending",
                    ticker,
                    row_id,
                    api_status,
                )
        except Exception as exc:
            _log.warning("[Recovery] %s row %d: lookup failed: %s", ticker, row_id, exc)

    # Batch-22 item 2: promote 'sent' rows that carry a recoverable
    # client_order_id (pre-computed and stored at pre-log time by every live
    # placement call site, or preserved through the pending-loop's own
    # downgrade above -- see kalshi_client.compute_client_order_id) into
    # 'unknown', so the SAME reconciliation machinery just below (client_
    # order_id lookup, retry) picks them up rather than leaving 'sent' a
    # permanent dead end.
    #
    # Opus review follow-up (F1/F2): _SENT_PROMOTION_MIN_AGE_MINUTES excludes
    # rows still genuinely in flight -- main.cmd_order/main._quick_paper_buy
    # pre-log with status='sent' BEFORE calling place_order at all (it's
    # log_order()'s own default, not just a crash artifact), so an
    # unguarded promotion here could race the ORIGINAL placing process's own
    # eventual log_order_result() call: promoting and resolving a row to
    # 'failed' (unblocking dedup on an order that hasn't actually failed --
    # a duplicate-order risk if the placer then completes and the operator
    # retries) or double-applying a partial-exit settlement neither
    # 'unknown' reconciliation's claim below nor record_live_partial_exit's
    # own guard protects against for THIS specific race (both assume the
    # row is already at rest, not actively being written by another
    # process). Comfortably longer than any realistic in-flight window (a
    # single HTTP request, DEFAULT_TIMEOUT=15s, POST is not auto-retried by
    # _build_session -- see kalshi_client.py) while still far short of the
    # 7-day dedup window a genuinely stuck row relies on.
    #
    # F3: claim_sent_order() only proceeds if the row is STILL 'sent' at
    # write time (mirrors claim_unknown_order's atomic-claim pattern) --
    # two concurrent recovery passes promoting the same row is then safe
    # (the loser's claim simply fails and it moves on), and a row a
    # concurrent process already resolved out from under this one can never
    # be silently reverted back to a bare {"client_order_id": ...} response.
    #
    # F4: wrapped per-row like the pending/unknown loops above -- one bad
    # row (a locked DB, a malformed response) must not abort the whole pass
    # and skip the 'unknown' reconciliation loop that follows.
    sent = execution_log.get_sent_live_orders(
        older_than_minutes=_SENT_PROMOTION_MIN_AGE_MINUTES
    )
    for order in sent:
        row_id = order["id"]
        ticker = order.get("ticker", "?")
        try:
            response = order.get("response")
            if isinstance(response, str):
                try:
                    response = json.loads(response)
                except json.JSONDecodeError:
                    response = None
            client_order_id = (response or {}).get("client_order_id")
            if not client_order_id:
                # No recoverable id -- either a row written before this fix, or
                # a case with genuinely nothing to re-check. Leave as 'sent',
                # matching this codebase's prior fail-safe behavior exactly
                # (dedup keeps blocking a re-placement).
                continue
            if not execution_log.claim_sent_order(row_id, client_order_id):
                _log.info(
                    "[Recovery] %s row %d: already claimed/resolved by a "
                    "concurrent recovery pass — skipping",
                    ticker,
                    row_id,
                )
                continue
            _log.info(
                "[Recovery] %s row %d: promoted 'sent' -> 'unknown' for "
                "re-check against Kalshi via stored client_order_id",
                ticker,
                row_id,
            )
        except Exception as exc:
            _log.warning(
                "[Recovery] %s row %d: 'sent' promotion failed: %s",
                ticker,
                row_id,
                exc,
            )

    # AUD-0007: also re-check 'unknown' rows -- written when place_order()'s
    # POST failed AND reconciliation itself couldn't confirm either way (see
    # kalshi_client.OrderStatusUnknownError). These have no order_id (the
    # create call never confirmed one), only the client_order_id stashed in
    # response at write time, so they need client._find_order_by_client_id
    # rather than the get_order(order_id) path the pending loop above uses.
    # Deliberately reuses this SAME function/call sites (cron.py startup,
    # trade_cycle.run_trade_cycle, and cmd_watch's own standalone call added
    # for AUD-0013) rather than a separate recovery path, so ambiguous rows
    # get periodically re-checked for free every time pending-order recovery
    # already runs -- matching AUD-0007's own recommendation.
    unknown = execution_log.get_unknown_live_orders()
    if not unknown:
        return

    _log.info(
        "[Recovery] Re-checking %d order(s) with unknown outcome against Kalshi API",
        len(unknown),
    )
    for order in unknown:
        row_id = order["id"]
        ticker = order.get("ticker", "?")
        try:
            response = order.get("response")
            if isinstance(response, str):
                response = json.loads(response)
            client_order_id = (response or {}).get("client_order_id")
            if not client_order_id:
                # Should not happen (every 'unknown' write includes it), but
                # fail safe rather than crash the recovery pass on one bad row.
                _log.warning(
                    "[Recovery] %s row %d: unknown row has no stored "
                    "client_order_id — cannot re-check, leaving as unknown",
                    ticker,
                    row_id,
                )
                continue

            found, uncertain = client._find_order_by_client_id(client_order_id)
            if found:
                # Opus review follow-up (round 2, HIGH+MEDIUM): claim this
                # row atomically before touching it. _recover_pending_orders
                # runs concurrently across processes (cron.py's own cycle
                # AND cmd_watch's standalone call, deliberately not
                # serialized behind the shared cron lock per AUD-0013) --
                # without this, two processes could both read the same
                # 'unknown' row and both attempt to resolve/settle it,
                # double-applying a partial exit's quantity reduction and
                # P&L (record_live_partial_exit's own guard only checks the
                # remaining quantity is non-negative, not whether this
                # specific delta was already applied once -- verified this
                # does NOT stop a second identical-delta call from
                # succeeding again). If another process already claimed
                # this row since get_unknown_live_orders() was read, skip
                # it entirely this pass -- it's being handled.
                if not execution_log.claim_unknown_order(row_id):
                    _log.info(
                        "[Recovery] %s row %d: already claimed by a "
                        "concurrent recovery pass — skipping",
                        ticker,
                        row_id,
                    )
                    continue

                api_status = found.get("status", "")
                _fill_count = _to_fill_count(found.get("fill_count_fp"))
                if api_status == "resting":
                    execution_log.log_order_result(
                        row_id, status="pending", response=found
                    )
                    _log.info(
                        "[Recovery] %s row %d: unknown → resting → pending",
                        ticker,
                        row_id,
                    )
                elif (
                    _internal_status := _kalshi_status_to_internal(
                        api_status, _fill_count
                    )
                ) is not None:
                    # Opus review follow-up (HIGH): this row can be a
                    # PROTECTIVE EXIT order (closes_position_id set), not
                    # just a new entry. Resolving its own status to 'filled'
                    # is not enough -- unlike a normal entry fill, an exit
                    # fill must also settle the POSITION it closed
                    # (record_live_exit_fill), or that position stays
                    # 'filled'/settled_at=NULL forever: invisible to this
                    # settlement, but still returned by
                    # get_filled_unsettled_live_orders() as if never sold --
                    # the exit scanner would keep placing fresh real SELL
                    # orders against it every cycle, and its true P&L would
                    # never reach the tax CSV/PnL summary. Mirrors
                    # _exit_live_position's own full/partial-fill branching.
                    #
                    # Round 2: settlement is now attempted BEFORE this row's
                    # own status is written as the final 'filled' -- round
                    # 1's ordering (write 'filled' first, settle after) made
                    # a settlement failure PERMANENT: get_unknown_live_
                    # orders() only selects status='unknown', so once the
                    # row left that status, nothing ever retried settlement
                    # (only a RuntimeError from record_live_exit_fill was
                    # even caught; a locked-DB-style error escaped to this
                    # loop's outer except and was silently logged, with the
                    # row already gone from the recovery queue).
                    _is_exit_order = order.get("closes_position_id") is not None
                    if _internal_status == "filled" and _is_exit_order:
                        if not _fill_count:
                            _log.warning(
                                "[Recovery] %s row %d: exit order executed "
                                "but fill count unparseable — cannot settle "
                                "safely, leaving 'unknown' for next pass",
                                ticker,
                                row_id,
                            )
                            execution_log.log_order_result(
                                row_id, status="unknown", response=response
                            )
                            continue
                        if not _settle_recovered_exit_order(row_id, order, _fill_count):
                            _log.warning(
                                "[Recovery] %s row %d: settlement failed — "
                                "leaving 'unknown' so it's retried next pass",
                                ticker,
                                row_id,
                            )
                            execution_log.log_order_result(
                                row_id, status="unknown", response=response
                            )
                            continue
                    execution_log.log_order_result(
                        row_id,
                        status=_internal_status,
                        response=found,
                        fill_quantity=_fill_count,
                    )
                    _log.info(
                        "[Recovery] %s row %d: unknown → resolved to %s (kalshi status=%s)",
                        ticker,
                        row_id,
                        _internal_status,
                        api_status,
                    )
                else:
                    _log.warning(
                        "[Recovery] %s row %d: unknown API status %r on found "
                        "order — reverting to unknown",
                        ticker,
                        row_id,
                        api_status,
                    )
                    execution_log.log_order_result(
                        row_id, status="unknown", response=response
                    )
            elif not uncertain:
                # All 3 reconciliation lookups genuinely completed this time
                # and none matched -- now safe to confirm this order never
                # landed (dedup guards will unblock a retry, correctly).
                # Opus review follow-up: preserve the original response
                # (still carrying client_order_id) rather than passing none --
                # log_order_result's UPDATE is unconditional, so omitting it
                # would wipe the one piece of data that let this row be
                # re-checked at all, permanently, even though 'failed' rows
                # aren't normally re-examined by any recovery pass.
                execution_log.log_order_result(
                    row_id,
                    status="failed",
                    error="confirmed not found on unknown-order re-check",
                    response=response,
                )
                _log.info(
                    "[Recovery] %s row %d: unknown → confirmed not found → failed",
                    ticker,
                    row_id,
                )
            else:
                _log.warning(
                    "[Recovery] %s row %d: still could not confirm outcome — "
                    "leaving unknown",
                    ticker,
                    row_id,
                )
        except Exception as exc:
            _log.warning(
                "[Recovery] %s row %d: unknown-order re-check failed: %s",
                ticker,
                row_id,
                exc,
            )


def _reconcile_live_positions(client) -> None:
    """AUD-0025: cross-check execution_log's internally-tracked live
    positions against Kalshi's own ground truth (GET /portfolio/positions).

    Every live position-lifecycle path (crash recovery above, fill polling,
    the protective-exit scanner) trusts execution_log's own ledger as if it
    were always in sync with the exchange. Nothing ever periodically
    verified that assumption — this does, log-only: no data heals itself
    here, it just makes a drift visible instead of silent. Mirrors
    _recover_pending_orders' own call-site convention (called once per
    trade cycle from run_trade_cycle) and its own fail-safe shape: never
    raises, a lookup failure just skips this cycle's check rather than
    blocking the cycle. Opus review (round 1) caught that this guarantee
    was previously only true by accident of the caller ALSO wrapping the
    call in try/except -- the function itself had no guard, so a future
    caller reading only this docstring could reasonably omit its own and
    get an unhandled exception. Guarded here directly now; the caller's own
    try/except (trade_cycle.py) is deliberately left in place too, matching
    _recover_pending_orders' belt-and-suspenders convention.

    KNOWN LIMITATION (opus review, round 1, deliberately not fixed here --
    kalshi_client.py belongs to a different batch): client.get_positions()
    is a single unpaginated GET, unlike _get_orders_by_status's cursor loop
    (hardened for the same class of gap under AUD-0007). Once the account
    holds more than one page of market positions, positions on page 2+
    would show up in missing_from_kalshi and warn every cycle -- log-only,
    so no money risk, but it degrades the signal to noise once the account
    grows. Follow-up: paginate kalshi_client.get_positions() the same way
    _get_orders_by_status already was.
    """
    try:
        tracked_tickers = {
            row["ticker"] for row in execution_log.get_filled_unsettled_live_orders()
        }
        real_tickers = {
            p.get("ticker", "") for p in client.get_positions() if p.get("position", 0)
        }
        real_tickers.discard("")
    except Exception as exc:
        _log.warning("_reconcile_live_positions: lookup failed: %s", exc)
        return

    missing_from_kalshi = tracked_tickers - real_tickers
    missing_from_tracker = real_tickers - tracked_tickers
    if missing_from_kalshi or missing_from_tracker:
        _log.warning(
            "[Reconcile] execution_log/Kalshi position drift detected — "
            "tracked here but not on the exchange: %s | "
            "on the exchange but not tracked here: %s",
            sorted(missing_from_kalshi),
            sorted(missing_from_tracker),
        )


# Cancel GTC orders this many minutes before market close — prevents leaving
# an open order on a market that is about to expire unfilled.
_GTC_PRECLOSE_CANCEL_MINUTES = 30

# ---------------------------------------------------------------------------
# Live order lifecycle
# ---------------------------------------------------------------------------


def _finalize_cancel(
    client, order_id: str, row_id: int
) -> tuple[str, int | None, str | None]:
    """Record the outcome of a cancel_order() call this bot just initiated.

    F9 followup: the pre-close and GTC-age cancel paths used to write
    status="canceled" immediately after calling cancel_order(), without
    ever checking whether the order had already partially filled. Kalshi
    has no distinct "partially filled" status -- a limit order can fill
    some contracts right before the cancel takes effect, and that fill
    count is only knowable by querying get_order() afterward. Reuses the
    exact same fill-count-aware promotion logic as the fill-polling loop
    and _recover_pending_orders() so a partial fill here isn't silently
    dropped from settlement either. Falls back to a plain "canceled" (the
    prior behavior) if the follow-up query itself fails -- the cancel
    already happened; the fill state is worth checking, not worth blocking
    the cancel record on.

    Returns (resolved_status, fill_count, raw_api_status). resolved_status
    collapses any unrecognized/in-flight Kalshi status (e.g. "resting", if
    the cancel hasn't propagated yet) to "canceled" -- fine for this
    function's original callers (pre-close/GTC-age cancel, which don't
    immediately act on the distinction), but NOT precise enough on its own
    to prove an order is genuinely off the book before placing a
    replacement. raw_api_status is Kalshi's own unmodified status string (or
    None if the verification query itself failed) so
    _cancel_and_verify_safe_to_replace can require raw_api_status ==
    "canceled" specifically, rather than trusting the collapsed default.
    """
    try:
        result = client.get_order(order_id)
        raw_api_status = result.get("status")
        fill_count = _to_fill_count(result.get("fill_count_fp"))
        status = (
            _kalshi_status_to_internal(raw_api_status or "canceled", fill_count)
            or "canceled"
        )
        execution_log.log_order_result(
            row_id=row_id, status=status, fill_quantity=fill_count
        )
        return status, fill_count, raw_api_status
    except Exception as exc:
        _log.warning(
            "[LIVE] post-cancel fill check failed for order %s, recording plain "
            "canceled: %s",
            order_id,
            exc,
        )
        execution_log.log_order_result(row_id=row_id, status="canceled")
        # Fill state genuinely unknown here (the query that would tell us
        # failed) -- treat as "don't know it's safe" rather than assuming
        # fill_count=0, so callers deciding whether to place a replacement
        # fail closed (skip replacing) instead of risking a duplicate
        # position on an order whose true fill state we couldn't confirm.
        return "canceled", -1, None


def _poll_pending_orders(client, config: dict | None = None) -> None:
    """Check fill status of all pending live orders and update execution_log.

    Also auto-cancels stale GTC orders and records settlement outcomes for
    filled orders whose markets have finalized.
    Called each iteration of cmd_watch to close the GTC order lifecycle.
    """
    # Opus review follow-up (AUD-0026): surface any row
    # record_live_early_exit_with_retry couldn't self-settle every cycle --
    # a sentinel file nobody ever reads doesn't actually alert the operator.
    # This only logs (does not block trading): the audit's own severity
    # assessment for AUD-0026 called the underlying failure "low direct
    # financial risk... a recurring, silent operational anomaly", so a
    # recurring warning matches the risk, rather than a new blocking gate
    # that would be a separate, bigger design decision.
    _unsettled_flags = execution_log.get_unsettled_exit_flags()
    if _unsettled_flags:
        _log.warning(
            "[LIVE] %d live order row(s) could not be self-settled after "
            "retrying (see execution_log_unsettled_exit_rows.json) -- still "
            "recorded as open positions, may be re-exited by mistake: %s",
            len(_unsettled_flags),
            [f.get("order_id") for f in _unsettled_flags],
        )

    # AUD-0003: fee at natural-expiry settlement depends on whether THIS
    # row's entry fill was maker (resting GTC limit, $0 fee) or taker
    # (immediate_or_cancel, real fee) -- selected per-order below from
    # order_type ("limit"=maker, "market"/anything else=taker), not a single
    # flat rate. Every entry-order call site across order_executor.py sets
    # order_type to mirror the actual time_in_force used (see
    # _replace_live_order/_amend_live_order/_place_live_order); main.cmd_order
    # was the one exception (fixed alongside this) and is now consistent too.
    # Unrecognized/missing order_type conservatively defaults to the taker
    # rate rather than assuming free maker fills -- understating P&L is the
    # safe failure direction here, not overstating it (see AUD-0003).
    from utils import kalshi_maker_fee, kalshi_taker_fee

    gtc_cancel_hours = (config or {}).get("gtc_cancel_hours", 24)
    now_utc = datetime.now(UTC)

    # ── Pending orders: GTC age check + fill status ───────────────────────────
    # AUD-0012: dedicated unbounded query, not a LIMIT-200-of-everything
    # fetch filtered in Python -- see _recover_pending_orders' identical note.
    pending = [o for o in execution_log.get_pending_live_orders() if o.get("response")]
    for order in pending:
        try:
            response = (
                json.loads(order["response"])
                if isinstance(order["response"], str)
                else order["response"]
            )
            # kalshi_client.place_order() now returns the flat get_order()-
            # shaped dict directly (V2 order-endpoint migration -- no more
            # {"order": {...}} wrapper).
            order_id = response.get("order_id") if response else None
            if not order_id:
                continue

            # Pre-close cancel — cancel before market expires rather than waiting
            # for the flat 24h GTC timer. A market closing at 08:00 UTC with an
            # order placed at 20:00 UTC would otherwise stay "pending" until 20:00
            # UTC the next day, 12h after the market already closed unfilled.
            _close_time_str = order.get("close_time")
            if _close_time_str:
                try:
                    _close_dt = datetime.fromisoformat(
                        _close_time_str.replace("Z", "+00:00")
                    )
                    _mins_to_close = (_close_dt - now_utc).total_seconds() / 60
                    if _mins_to_close <= _GTC_PRECLOSE_CANCEL_MINUTES:
                        client.cancel_order(order_id)
                        _finalize_cancel(client, order_id, order["id"])
                        if _mins_to_close <= 0:
                            _log.info(
                                "[LIVE] pre-close GTC cancel: %s market already closed %.0f min ago",
                                order.get("ticker", "?"),
                                abs(_mins_to_close),
                            )
                        else:
                            _log.info(
                                "[LIVE] pre-close GTC cancel: %s closes in %.0f min",
                                order.get("ticker", "?"),
                                _mins_to_close,
                            )
                        continue
                except Exception as _exc:
                    _log.warning(
                        "[LIVE] pre-close cancel check failed for %s: %s",
                        order.get("ticker", "?"),
                        _exc,
                    )

            # GTC age check — cancel orders older than gtc_cancel_hours
            try:
                placed_at = datetime.fromisoformat(
                    order["placed_at"].replace("Z", "+00:00")
                )
                age_hours = (now_utc - placed_at).total_seconds() / 3600
                if age_hours >= gtc_cancel_hours:
                    client.cancel_order(order_id)
                    _finalize_cancel(client, order_id, order["id"])
                    continue
            except Exception as exc:
                _log.warning(
                    "[LIVE] GTC cancel failed for order %s: %s", order.get("id"), exc
                )

            result = client.get_order(order_id)
            api_status = result.get("status", "")
            _fill_count = _to_fill_count(result.get("fill_count_fp"))
            _internal_status = _kalshi_status_to_internal(api_status, _fill_count)
            if _internal_status is not None:
                _filled_at = None
                _mid_at_fill = None
                if _internal_status == "filled":
                    # Fill-latency / adverse-selection instrumentation: capture
                    # the moment we first observe the fill and the market's
                    # price at that instant. This branch only fires once per
                    # row (the `pending` list above only contains rows still
                    # status="pending"), so this is genuinely "at fill", not a
                    # later re-observation.
                    _filled_at = now_utc.isoformat()
                    try:
                        _book = _get_current_book(client, order.get("ticker", ""))
                        if _book:
                            _mid_at_fill = parse_market_price(_book)["mid"]
                    except Exception as _mid_exc:
                        _log.debug(
                            "[LIVE] market_mid_at_fill lookup failed for %s: %s",
                            order.get("ticker", "?"),
                            _mid_exc,
                        )
                execution_log.log_order_result(
                    row_id=order["id"],
                    status=_internal_status,
                    fill_quantity=_fill_count,
                    filled_at=_filled_at,
                    market_mid_at_fill=_mid_at_fill,
                )
        except Exception as exc:
            _log.warning("[LIVE] poll order %s failed: %s", order.get("id"), exc)

    # ── Filled+unsettled orders: settlement check ─────────────────────────────
    for order in execution_log.get_filled_unsettled_live_orders():
        try:
            market = client.get_market(order["ticker"])
            status = market.get("status", "")
            result = market.get("result", "")
            if status != "finalized" or not result:
                continue
            # 1-hour buffer — Kalshi may revise outcomes shortly after finalization
            close_time_str = market.get("close_time") or market.get(
                "expiration_time", ""
            )
            if not close_time_str:
                continue  # no close_time — skip until Kalshi provides one
            try:
                close_dt = datetime.fromisoformat(close_time_str.replace("Z", "+00:00"))
                if (now_utc - close_dt).total_seconds() / 3600 < 1.0:
                    continue
            except (ValueError, TypeError):
                continue  # unparseable close_time — skip defensively
            outcome_yes = result == "yes"
            side = order["side"]
            # price is the entry-side contract price: YES price for YES orders,
            # NO price (= 1 - yes_bid) for NO orders.
            price = order["price"]
            qty = order.get("fill_quantity") or order["quantity"]
            # Batch-22 items 3+6: the fee this entry fill paid is charged at
            # the FILL (independent of how the position later settles), so
            # it must be subtracted from gross P&L unconditionally -- not
            # just on a win, which the old `(1 - _fee)` multiplier (applied
            # only inside the two win branches below) silently did. Maker
            # fills (order_type == "limit") use utils.kalshi_maker_fee --
            # genuinely $0 for every real order this bot places today
            # (KALSHI_MAKER_FEE_RATE's own documentation: M=0 for this bot's
            # weather-market series), but still respects an operator's
            # KALSHI_MAKER_FEE_RATE override rather than a hardcoded 0.0
            # (opus review follow-up: a hardcoded 0.0 silently dropped that
            # override for exactly this consumer -- the live daily-loss
            # ledger -- while every other consumer in the codebase still
            # honored it). Taker fills use kalshi_taker_fee, not
            # KALSHI_FEE_RATE's flat-percent-of-winnings approximation. See
            # kalshi_taker_fee's own docstring for the reproduced numeric
            # error this replaces.
            _fee_dollars = (
                kalshi_maker_fee(qty, price)
                if order.get("order_type") == "limit"
                else kalshi_taker_fee(qty, price)
            )
            if outcome_yes and side == "yes":
                gross_pnl = qty * (1 - price)  # won YES: profit = 1-cost
            elif not outcome_yes and side == "yes":
                gross_pnl = -qty * price  # lost YES: lose cost
            elif outcome_yes and side == "no":
                gross_pnl = -qty * price  # YES wins, NO loses: lose NO cost
            else:  # not outcome_yes, side == "no" — NO wins
                gross_pnl = qty * (1 - price)  # won NO: profit = 1-cost
            pnl = round(gross_pnl - _fee_dollars, 4)
            execution_log.record_live_settlement(order["id"], outcome_yes, pnl)
            execution_log.add_live_loss(-pnl)  # negative pnl = loss adds to counter
        except Exception as exc:
            _log.warning(
                "[LIVE] settlement check failed for order %s: %s", order.get("id"), exc
            )


# ---------------------------------------------------------------------------
# Reprice / cancel / taker-cross for still-resting live orders
# ---------------------------------------------------------------------------

# An unfilled order must have rested at least this long before EITHER a
# reprice-improve or a taker-cross is considered at all. Originally this gate
# was applied only to taker-cross, on the assumption that a same-cycle
# placement is priced from the identical scan data this check also reads --
# that assumption is false: _auto_place_trades re-fetches a FRESH market
# (client.get_market()) just before pricing a new order
# (_place_live_order's entry_price comes from that fresh fetch, not the
# liquid_opps scan snapshot), while this check's fresh_mid comes from
# _get_current_book (WS-cache-first) or the older scan-time market -- a
# genuinely different snapshot. Without this gate, a just-placed order could
# be canceled and re-placed in the same cycle purely because the WS tick
# arrived a few seconds after the REST placement fetch, forfeiting queue
# priority for no real reason. Applies to both branches below.
_MIN_REST_MINUTES_BEFORE_REPRICE = 2

# Taker-crossing (guaranteed fill, real fee) gets a stricter, longer bar than
# reprice-improve (still maker, still $0 fee, fully reversible) -- paying a
# real fee to guarantee a fill deserves more patience than adjusting a price.
_MIN_REST_MINUTES_BEFORE_TAKER_CROSS = 4

# Minimum price difference (dollars) worth canceling+replacing a resting
# order over -- avoids cancel/replace churn over sub-cent noise.
_MIN_REPRICE_TICK = 0.01


def _live_min_edge(analysis: dict) -> float:
    """Replicate _validate_trade_opportunity's live min-edge threshold
    (confidence-tiered by ensemble_spread, else MIN_EDGE) -- shared here so
    the taker-cross check below uses the exact same bar a fresh live
    placement would.
    """
    from utils import get_min_edge_for_confidence

    ens_spread = analysis.get("ensemble_spread")
    if ens_spread is not None:
        try:
            return get_min_edge_for_confidence(float(ens_spread), is_live=True)
        except Exception:
            return MIN_EDGE
    return MIN_EDGE


def _clears_taker_fee(analysis: dict) -> bool:
    """True if net_edge, recomputed with the REAL taker fee instead of the
    maker fee analyze_trade() actually used, would still clear the live
    min_edge threshold -- i.e. crossing as taker (guaranteed fill, real fee)
    is worth it versus continuing to wait as an uncertain-fill $0-fee maker
    order. Recomputes from analysis's own stored forecast_prob/entry_price/
    recommended_side rather than re-deriving them, so this can never
    disagree with what analyze_trade() itself already decided about this
    specific trade.

    Only the main temperature analyze_trade() path stores entry_price (see
    weather_markets.py's return dict) -- the precip/snow paths don't, so
    this always returns False (via the missing-field guard below) for those
    markets today. Fails safe: no taker-cross for precip/snow, reprice-
    improve still works. Worth threading entry_price through those paths
    too if taker-crossing there ever matters.
    """
    from utils import KALSHI_FEE_RATE

    entry_price = analysis.get("entry_price")
    forecast_prob = analysis.get("forecast_prob")
    side = analysis.get("recommended_side")
    if not entry_price or forecast_prob is None or side not in ("yes", "no"):
        return False
    p_win = forecast_prob if side == "yes" else 1.0 - forecast_prob
    payout = 1.0 - entry_price
    net_ev_taker = p_win * payout * (1 - KALSHI_FEE_RATE) - (1 - p_win) * entry_price
    net_edge_taker = net_ev_taker / entry_price if entry_price > 0 else 0.0
    return net_edge_taker >= _live_min_edge(analysis)


def _cancel_and_verify_safe_to_replace(client, order_id: str, row_id: int) -> bool:
    """Cancel a resting order and return True only if verified both
    genuinely unfilled (fill_count == 0) AND genuinely no longer resting
    (Kalshi's own raw status == "canceled") -- i.e. safe to place a
    replacement without risking a duplicate position or having a
    taker-cross replacement silently no-op against Kalshi's
    self_trade_prevention_type="taker_at_cross" (which cancels an incoming
    order that would cross the bot's own still-resting order on the same
    ticker/side).

    Deliberately checks _finalize_cancel's raw_api_status, not its collapsed
    resolved_status -- resolved_status defaults an unrecognized/in-flight
    Kalshi status (e.g. "resting", meaning the cancel hasn't propagated yet)
    to "canceled", which is fine for _finalize_cancel's other callers but
    would make this check pass on an order that's still actually resting.

    Any other outcome (partial/full fill, still resting per raw_api_status,
    or the post-cancel verification query itself failing -- raw_api_status
    is None in that case, see _finalize_cancel's -1 sentinel) fails closed
    and returns False.
    """
    try:
        client.cancel_order(order_id)
    except Exception as exc:
        _log.warning("[Reprice] cancel_order failed for order %s: %s", order_id, exc)
        return False
    _resolved_status, fill_count, raw_api_status = _finalize_cancel(
        client, order_id, row_id
    )
    return raw_api_status == "canceled" and fill_count == 0


def _replace_live_order(
    ticker: str,
    side: str,
    quantity: int,
    price: float,
    time_in_force: str,
    client,
    cycle: str,
    replaces_order_id: int,
    close_time: str | None,
) -> bool:
    """Place a replacement order for a just-canceled resting order (reprice
    or taker-cross). Caller must have already confirmed via
    _cancel_and_verify_safe_to_replace() that the original genuinely did not
    fill before calling this.

    Re-runs the kill-switch/trading-paused safety gate (never skippable) but
    deliberately NOT the daily-loss/spend/max-open-position gates
    (_place_live_order's steps 1/1b/2) or edge/Kelly re-validation (step 3's
    sizing) -- those already approved and sized this exact position once at
    original placement; a reprice modifies an existing approved position's
    resting order, it does not create a new one, and quantity is fixed at
    the original (no resizing on reprice).
    """
    from trading_gates import pre_live_trade_check

    try:
        pre_live_trade_check(client)
    except RuntimeError as _gate_err:
        _log.warning(
            "[Reprice] Gate blocked replacement order for %s: %s", ticker, _gate_err
        )
        return False

    # Batch-22 item 2: pre-computed and stored BEFORE the API call, matching
    # place_order()'s own internal derivation exactly -- if the process
    # crashes before log_order_result records the real outcome, recovery can
    # still re-check this specific client_order_id against Kalshi. See
    # kalshi_client.compute_client_order_id's own docstring.
    _cid = compute_client_order_id(ticker, side, "buy", quantity, price, cycle)
    log_id = execution_log.log_order(
        ticker=ticker,
        side=side,
        quantity=quantity,
        price=price,
        order_type="limit" if time_in_force == "good_till_canceled" else "market",
        status="pending",
        response={"client_order_id": _cid},
        forecast_cycle=cycle,
        live=True,
        close_time=close_time,
        replaces_order_id=replaces_order_id,
    )
    try:
        response = client.place_order(
            ticker=ticker,
            side=side,
            action="buy",
            count=quantity,
            price=price,
            time_in_force=time_in_force,
            cycle=cycle,
        )
    except OrderStatusUnknownError as _unk_exc:
        # AUD-0007: see _place_live_order's matching handler.
        execution_log.log_order_result(
            log_id,
            status="unknown",
            error=str(_unk_exc),
            response={"client_order_id": _unk_exc.client_order_id},
        )
        _log.warning(
            "[Reprice] Replacement order outcome unknown for %s: %s", ticker, _unk_exc
        )
        return False
    except Exception as exc:
        execution_log.log_order_result(log_id, status="failed", error=str(exc))
        _log.warning("[Reprice] Replacement order failed for %s: %s", ticker, exc)
        return False

    # Opus review follow-up (AUD-0007, round 2): see _place_live_order's
    # matching comment -- this write must not share the try above with the
    # placement call (a bookkeeping-only failure here must not mark a REAL
    # replacement order 'failed'), but round 2 caught that an unhandled
    # exception here would now propagate uncaught instead. Currently safe
    # in practice (this function's only production caller is inside
    # cmd_watch's AUD-0008 try/except), but caught locally anyway for
    # defense-in-depth against a future caller that isn't wrapped -- same
    # reasoning as _place_live_order: the pre-logged 'pending' row with no
    # order_id is already handled safely by _recover_pending_orders.
    try:
        execution_log.log_order_result(log_id, status="pending", response=response)
    except Exception as _bk_exc:
        _log.warning(
            "[Reprice] %s: order placed on exchange but bookkeeping write "
            "failed (%s) -- row stays pre-logged 'pending', "
            "_recover_pending_orders will reconcile it",
            ticker,
            _bk_exc,
        )
    return True


def _resolve_amend_status(response: dict) -> tuple[str, int | None]:
    """Translate an amend_order() response into this bot's internal status
    vocabulary + fill_quantity.

    remaining_count/fill_count are only present in the response "if a fill
    or size change occurred" per Kalshi's docs -- absent (both None) means
    the amend was a pure price change with no immediate cross, so the order
    is still fully resting, unchanged in fill state. remaining_count<=0
    means the amend's price change immediately crossed the book and used up
    every remaining contract -- "filled". Otherwise "pending" (still
    resting, possibly with a partial fill from this amend).

    This is a best-effort immediate read of the amend response only --
    _poll_pending_orders' next-cycle get_order() re-check remains the
    decisive source of truth for the new row's final status, same as every
    other pending row (including a fresh place_order placement).
    """
    fill_count = _to_fill_count(response.get("fill_count"))
    remaining_raw = response.get("remaining_count")
    if remaining_raw is not None:
        try:
            if float(remaining_raw) <= 0:
                return "filled", fill_count
        except (TypeError, ValueError):
            pass
    return "pending", fill_count


def _amend_live_order(
    order_id: str,
    ticker: str,
    side: str,
    quantity: int,
    price: float,
    client,
    cycle: str,
    replaces_order_id: int,
    close_time: str | None,
    original_client_order_id: str | None,
) -> bool:
    """Reprice a resting live order in place via Kalshi's atomic amend
    endpoint, instead of cancel + verify + replace. The exchange-side
    order_id is unchanged by an amend (unlike cancel+replace, which creates
    a genuinely new order) -- but execution_log still gets a NEW row here,
    chained via replaces_order_id, matching the same convention already
    used for cancel+replace reprices/taker-crosses, so price-history/
    fill-latency analysis keeps working unchanged. The OLD row is marked
    status="amended" (deliberately distinct from "canceled" -- the original
    order was never actually canceled, just repriced) once the amend
    succeeds; execution_log.get_today_live_spend() excludes "amended" the
    same way it excludes "canceled", so the two rows' capital is never
    double-counted as the order gets repriced across a cycle. If the amend
    fails, the old row is left untouched (still "pending" at its prior
    price) -- next cycle's normal flow will re-evaluate and retry.

    Re-runs the kill-switch/trading-paused safety gate (never skippable,
    same as _replace_live_order) but deliberately NOT the daily-loss/spend/
    max-open-position gates or edge/Kelly re-validation -- same reasoning as
    _replace_live_order: this reprices an already-approved, already-sized
    position's resting order, it does not create a new one.
    """
    from trading_gates import pre_live_trade_check

    try:
        pre_live_trade_check(client)
    except RuntimeError as _gate_err:
        _log.warning("[Reprice] Gate blocked amend for %s: %s", ticker, _gate_err)
        return False

    # Batch-22 item 2 deliberately does NOT capture a client_order_id here
    # (unlike _replace_live_order/_exit_live_position/_place_live_order/
    # micro-live): an amend uses client.amend_order's own
    # updated_client_order_id scheme, not place_order's -- amend_order
    # doesn't create a new order matching that id the way place_order does,
    # so client._find_order_by_client_id's lookup wouldn't apply here even
    # if we stored it. If this row's own log_order_result never lands (a
    # crash before it), the exchange-side order_id is UNCHANGED by an amend
    # (see this function's own docstring) -- the original order (this
    # amend's replaces_order_id) keeps getting recovered normally through
    # the main pending-order loop above using its own, already-known
    # order_id; only "did this specific price-change land" stays ambiguous,
    # a materially smaller gap than a whole position going untracked.
    log_id = execution_log.log_order(
        ticker=ticker,
        side=side,
        quantity=quantity,
        price=price,
        order_type="limit",
        status="pending",
        forecast_cycle=cycle,
        live=True,
        close_time=close_time,
        replaces_order_id=replaces_order_id,
    )
    try:
        response = client.amend_order(
            order_id=order_id,
            ticker=ticker,
            side=side,
            action="buy",
            count=quantity,
            price=price,
            client_order_id=original_client_order_id,
            cycle=cycle,
        )
    except Exception as exc:
        # The exchange call itself failed -- nothing changed on the
        # exchange, so the original order genuinely is still resting
        # unchanged at its old price; the old row correctly stays
        # "pending" (untouched) for a future cycle to retry.
        execution_log.log_order_result(log_id, status="failed", error=str(exc))
        _log.warning("[Reprice] Amend failed for %s: %s", ticker, exc)
        return False

    # The exchange call succeeded -- the order is now genuinely repriced
    # live, regardless of what happens below. A bookkeeping failure past
    # this point (e.g. a DB lock) must NOT get this reclassified as
    # "failed" -- that would silently stop _poll_pending_orders (which
    # filters on status='pending') from ever tracking a real live order
    # again, orphaning it.
    resolved_status, fill_count = _resolve_amend_status(response)
    try:
        execution_log.log_order_result(
            log_id, status=resolved_status, response=response, fill_quantity=fill_count
        )
        # Old row: mark amended only after the amend itself is confirmed to
        # have succeeded -- if it failed, the original order genuinely is
        # still resting unchanged at its old price, so its row must stay
        # "pending", not "amended".
        execution_log.log_order_result(row_id=replaces_order_id, status="amended")
    except Exception as exc:
        _log.error(
            "[Reprice] Amend for %s succeeded on the exchange (order_id=%s) "
            "but execution_log bookkeeping failed -- this order may be "
            "under-tracked: %s",
            ticker,
            response.get("order_id"),
            exc,
        )
    return True


def _reprice_or_cancel_pending_orders(
    client, config: dict | None = None, liquid_opps: list | None = None
) -> None:
    """Reprice-or-cancel resting live orders based on this cycle's fresh
    market analysis. Must run AFTER _poll_pending_orders in the same cycle,
    so it only ever sees orders confirmed still resting (status='pending')
    this cycle -- never one that just filled.

    Policy per pending order:
      - Ticker not in this cycle's fresh scan (liquid_opps) -> leave alone.
      - _validate_trade_opportunity() no longer passes (edge decayed, gate
        failure, flash-crash, etc.) -> cancel immediately, do not replace
        (no minimum age -- a genuinely invalid order shouldn't keep resting
        just because it's young).
      - Younger than _MIN_REST_MINUTES_BEFORE_REPRICE -> leave resting
        unchanged (give it a real chance to fill before touching it; also
        avoids reprice churn from a same-cycle placement and this check
        reading two different market snapshots -- see that constant's
        comment).
      - Edge still clears the REAL taker fee AND the order has rested at
        least _MIN_REST_MINUTES_BEFORE_TAKER_CROSS -> cancel, verify no
        fill, replace as an immediate-or-cancel taker order at the current
        opposing price (guaranteed fill now).
      - The fresh midpoint price differs from the order's current resting
        price by >= _MIN_REPRICE_TICK -> cancel, verify no fill, replace as
        a new resting GTC limit order at the fresh midpoint (still $0 fee).
      - Otherwise -> leave resting unchanged.

    liquid_opps: this cycle's (market, analysis) pairs -- from
    trade_cycle.run_trade_cycle()'s own scan when auto-trading (filtered to
    threshold-passing candidates by the caller), or from _analyze_once's
    display-only scan otherwise -- reused here instead of a separate
    re-scan.
    """
    if not liquid_opps:
        return
    _by_ticker = {m.get("ticker"): (m, a) for m, a in liquid_opps if m.get("ticker")}

    cycle = _current_forecast_cycle()
    now_utc = datetime.now(UTC)

    # AUD-0012: dedicated unbounded query, not a LIMIT-200-of-everything
    # fetch filtered in Python -- see _recover_pending_orders' identical note.
    pending = [o for o in execution_log.get_pending_live_orders() if o.get("response")]
    for order in pending:
        ticker = order.get("ticker", "")
        side = order.get("side", "yes")
        try:
            response = (
                json.loads(order["response"])
                if isinstance(order["response"], str)
                else order["response"]
            )
            order_id = response.get("order_id") if response else None
            if not order_id:
                continue

            pair = _by_ticker.get(ticker)
            if pair is None:
                continue  # not in this cycle's fresh scan -- leave alone
            market, analysis = pair

            try:
                ok, reason = _validate_trade_opportunity(
                    analysis, live=True, market=market
                )
            except Exception as exc:
                _log.debug("[Reprice] validation check failed for %s: %s", ticker, exc)
                continue

            if not ok:
                client.cancel_order(order_id)
                _finalize_cancel(client, order_id, order["id"])
                _log.info(
                    "[Reprice] %s: canceled — no longer valid (%s)", ticker, reason
                )
                continue

            try:
                placed_at = datetime.fromisoformat(
                    order["placed_at"].replace("Z", "+00:00")
                )
                age_minutes = (now_utc - placed_at).total_seconds() / 60
            except (ValueError, TypeError, KeyError):
                continue  # can't determine age safely -- leave resting unchanged

            if age_minutes < _MIN_REST_MINUTES_BEFORE_REPRICE:
                continue  # too fresh to reprice/cross -- give it a real chance to fill first

            book = _get_current_book(client, ticker) or market
            fresh_mid = _midpoint_price(book, side)
            quantity = order.get("quantity")
            if not quantity:
                continue  # malformed row -- nothing safe to replace with
            close_time = order.get("close_time")

            if (
                _clears_taker_fee(analysis)
                and age_minutes >= _MIN_REST_MINUTES_BEFORE_TAKER_CROSS
            ):
                yes_bid = coalesce_market_price(book, *YES_BID_KEYS)
                yes_ask = coalesce_market_price(book, *YES_ASK_KEYS)
                taker_price = yes_ask if side == "yes" else round(1.0 - yes_bid, 2)
                if taker_price <= 0:
                    continue
                if _cancel_and_verify_safe_to_replace(client, order_id, order["id"]):
                    _replace_live_order(
                        ticker,
                        side,
                        quantity,
                        taker_price,
                        "immediate_or_cancel",
                        client,
                        cycle,
                        order["id"],
                        close_time,
                    )
                    _log.info(
                        "[Reprice] %s: canceled resting order, crossed as taker @ %.2f",
                        ticker,
                        taker_price,
                    )
                continue

            current_price = order.get("price")
            if (
                current_price is not None
                and abs(fresh_mid - current_price) >= _MIN_REPRICE_TICK
            ):
                # Same order, new price -- Kalshi's amend endpoint (a single
                # atomic exchange-side operation) instead of cancel + verify
                # + place_order, closing the client-side window where a fill
                # could land exactly as the post-cancel verification query
                # runs. The taker-cross branch above stays on cancel+replace
                # deliberately -- it changes time_in_force to
                # immediate_or_cancel, a different order type amend cannot
                # express.
                if _amend_live_order(
                    order_id,
                    ticker,
                    side,
                    quantity,
                    fresh_mid,
                    client,
                    cycle,
                    order["id"],
                    close_time,
                    response.get("client_order_id"),
                ):
                    _log.info(
                        "[Reprice] %s: amended %.2f -> %.2f",
                        ticker,
                        current_price,
                        fresh_mid,
                    )
        except Exception as exc:
            _log.warning(
                "[Reprice] reprice/cancel check failed for order %s: %s",
                order.get("id"),
                exc,
            )


# ---------------------------------------------------------------------------
# Live position protection — stop-loss / breakeven-stop / model-exit
#
# Kalshi has no stop or conditional order type (confirmed against the V2
# create-order API docs -- time_in_force is only fill_or_kill/
# good_till_canceled/immediate_or_cancel). A resting limit sell order fills
# when price RISES to meet it, which is the opposite of what protects a
# falling position -- so a triggered exit here always crosses the spread
# immediately (immediate_or_cancel) to guarantee the fill rather than resting
# passively at a price that would never be reached. See backlog.txt's
# [RESTING EXIT ORDERS + OCO ORDER GROUPS] entry for the full reasoning.
#
# Scope of this pass: checks run once per cmd_watch/cron cycle (not
# WS-tick-triggered) -- a genuinely always-on watcher that reacts between
# cycles (closing the multi-hour manual-cron-cadence gap this backlog item
# was originally about) is deliberately deferred as a separate follow-up;
# this still closes the larger gap, which is that live positions had *zero*
# automated exit management of any kind before this.
# ---------------------------------------------------------------------------


def _get_live_open_positions(include_unfilled: bool = False) -> list[dict]:
    """Build a paper-trade-shaped dict from execution_log's filled-unsettled
    live orders. Kept as the raw-dict adapter (not Position-returning) --
    _check_live_model_exits now also converts each dict to a Position via
    _live_dict_to_position() (per-item, batch-18, inside its own per-record
    try/except so one malformed dict only drops that one position), but
    still calls this function for the initial raw fetch rather than
    LivePositionStore(...).get_open(), which would re-fetch and risk seeing
    a different open-position set. LivePositionStore.get_open() layers
    _live_dict_to_position() on top of this for the shared positions.
    check_stop_losses()/check_breakeven_stops()/update_peak_profits(), the
    same pattern paper.PaperPositionStore.get_open() uses over
    paper.get_open_trades().

    Batch-22 item 4: include_unfilled=True additionally unions in still-
    resting entry orders (status='pending') and ambiguous-outcome orders
    (status='unknown'), mirroring _count_open_live_orders()'s own union
    exactly (same closes_position_id IS NULL exclusion, so a pending/unknown
    protective EXIT order's own row is never mistaken for a new entry).
    Default stays False (filled-unsettled only) for every exit-scanning
    caller (LivePositionStore.get_open(), _check_live_model_exits,
    main.cmd_order's sell-match lookup) -- those can only ever act on a
    position that has genuinely filled; a resting/ambiguous entry has no
    real contracts on the exchange yet to check stop-losses against or sell.
    paper.get_all_open_positions()/paper._exposure_denom() (every dollar-
    exposure cap) pass True: AUD-0001's fix made dollar exposure combine
    paper+live, but only ever saw the FILLED subset of live capital --
    reopening the same "silently exceed every configured exposure cap"
    failure mode _count_open_live_orders() already closed for the
    position-COUNT cap, just for the two statuses that fix didn't cover.

    Deliberately does NOT union in status='sent' rows (opus review follow-
    up, LOW #11) -- unlike 'pending'/'unknown', a 'sent' row's own outcome
    is ambiguous enough that _recover_pending_orders' promotion loop
    requires it be past _SENT_PROMOTION_MIN_AGE_MINUTES before even
    attempting to resolve it (see that function's own F1/F2 comment). Since
    every 'sent' row self-promotes to 'unknown' (and becomes visible here)
    the moment it clears that same age threshold, the real gap is bounded
    to that window (currently 5 minutes) rather than open-ended -- accepted
    as a deliberately small, self-healing blind spot rather than adding a
    fourth query here for a status whose own defining property is "we don't
    yet know if this represents anything real."
    """
    # AUD-0001/AUD-0002: city/target_date backfilled from the ticker alone
    # (weather_markets.parse_city_date needs only market["ticker"] -- title
    # is an optional disambiguator it doesn't have here) so paper.py's
    # exposure caps and _auto_place_trades' city/date concentration caps,
    # which key off these two fields, can see live positions at all. Lazy
    # import matches this file's existing convention (paper.py imports
    # weather_markets the same way inside check_position_limits).
    from weather_markets import _CITY_TZ, parse_city_date

    rows = execution_log.get_filled_unsettled_live_orders()
    if include_unfilled:
        # Same closes_position_id exclusion _count_open_live_orders() uses:
        # a pending/unknown row that's itself a protective EXIT order (not a
        # new entry) must not be double-counted as an open position on top
        # of the position it's in the middle of closing.
        rows = (
            rows
            + [
                r
                for r in execution_log.get_pending_live_orders()
                if r.get("closes_position_id") is None
            ]
            + [
                r
                for r in execution_log.get_unknown_live_orders()
                if r.get("closes_position_id") is None
            ]
        )
    positions = []
    for r in rows:
        # Opus review follow-up (LOW #10): `fill_quantity or quantity` is
        # correct for a FILLED row (fill_quantity there is the current
        # tracked open size, already reduced by any partial exit) but wrong
        # for a still-ACTIVE pending/unknown row -- a partial fill there
        # (e.g. an amend/reprice that filled some contracts while the
        # remainder keeps resting) means the position's real total exposure
        # is still the full originally-requested `quantity`, not just the
        # portion that's happened to fill SO FAR; the still-resting
        # remainder is exactly the kind of "could become a real position at
        # any moment" capital this include_unfilled union exists to catch.
        qty = (
            r.get("quantity")
            if r.get("status") in ("pending", "unknown")
            else r.get("fill_quantity") or r.get("quantity")
        )
        entry_price = r.get("price")
        if not qty or entry_price is None:
            continue
        ticker = r["ticker"]
        city, target_date = parse_city_date({"ticker": ticker})
        # Opus-review-caught: rain/snow monthly tickers carry no day-level
        # date at all (parse_city_date's own docstring: "the regex
        # naturally finds nothing"), so target_date stayed None for those
        # series even after the backfill above -- invisible to every
        # city/date-keyed cap (get_city_date_exposure, get_correlated_
        # exposure, _multiday_date_counts, get_expiry_date_clustering).
        # Fall back to close_time's date when present -- not necessarily
        # byte-identical to the month-anchor date analyze_trade() itself
        # assigns these series at signal time (paper trades store that
        # value directly via _unpack_opp), but a real date beats an
        # invisible position for every cap that keys on this field.
        # 2nd-round-opus-review-caught (L-6): close_time is NOT guaranteed
        # present on every row (main.py's cmd_order logs close_time=None
        # when the market dict it enriched from lacked one) -- when it's
        # also missing, target_date stays None here and days_out below
        # falls back to its own default of 1 (multi-day), matching this
        # function's pre-H2 behavior for that case rather than the
        # days_out=0-forever failure mode a naive fallback could produce.
        if target_date is None and r.get("close_time"):
            try:
                from zoneinfo import ZoneInfo

                # 2nd-round-opus-review-caught (H-B): close_time is a UTC
                # timestamp from the exchange; target_date must be
                # CITY-LOCAL to match parse_city_date's own contract (and
                # the entered_date conversion below) -- taking its raw UTC
                # .date() reproduces the same UTC-vs-city-local bug for the
                # ~4-8h evening window where UTC has already rolled over
                # but the city hasn't.
                target_date = (
                    datetime.fromisoformat(r["close_time"].replace("Z", "+00:00"))
                    .astimezone(ZoneInfo(_CITY_TZ.get(city or "", "America/New_York")))
                    .date()
                )
            except (ValueError, TypeError, KeyError):
                pass
        # filled_at (when the position actually opened) is the correct
        # analog of paper's entered_at for the 12h minimum-hold gates
        # below -- a GTC entry order can rest a while before filling,
        # so placed_at would understate how long the position itself
        # has actually been held. Falls back to placed_at only for
        # rows logged before filled_at existed.
        entered_at = r.get("filled_at") or r.get("placed_at")
        # AUD-0002 (opus-review-caught): _auto_place_trades' same-day/
        # multi-day concentration caps key off days_out, snapshotted at
        # placement time (order_executor.py's own comment there: using a
        # STATIC days_out, not a dynamically-recomputed one, deliberately
        # avoids reclassifying an aged position as same-day just because
        # it settles today) -- execution_log's orders table never
        # persisted this field for live orders, so reconstruct the same
        # snapshot from what IS persisted: target_date vs. the date this
        # position was actually entered. Missing target_date/entered_at
        # (parse failure, or a row logged before filled_at existed) falls
        # back to 1 (multi-day), matching this codebase's own established
        # "legacy trades with no days_out field are treated as multi-day"
        # convention exactly -- without this, a same-day live position
        # would be invisible to the same-day cap AND wrongly counted
        # against the multi-day cap for its target_date.
        # 2nd-round-opus-review-caught (H-B): target_date is CITY-LOCAL
        # (parse_city_date's own contract), but entered_at is a UTC
        # timestamp -- naively taking entered_at's UTC .date() and
        # subtracting from a city-local target_date reproduces the exact
        # UTC-vs-city-local bug this codebase already documents and fixes
        # elsewhere (main.py's _feature_importance_days_out docstring: "the
        # ~4-8h evening window where UTC's calendar date has already
        # rolled over but the city's has not"). Mirrors that function's
        # fix exactly: convert entered_at to the CITY's own local calendar
        # date via ZoneInfo before subtracting.
        days_out = 1
        if target_date and entered_at:
            try:
                from zoneinfo import ZoneInfo

                entered_dt = datetime.fromisoformat(entered_at.replace("Z", "+00:00"))
                entered_date = entered_dt.astimezone(
                    ZoneInfo(_CITY_TZ.get(city or "", "America/New_York"))
                ).date()
                days_out = max(0, (target_date - entered_date).days)
            except (ValueError, TypeError, KeyError):
                pass
        positions.append(
            {
                "id": r["id"],
                "ticker": ticker,
                "side": r.get("side", "yes"),
                "entry_price": entry_price,
                "quantity": qty,
                "cost": round(entry_price * qty, 4),
                "close_time": r.get("close_time"),
                "peak_profit_pct": r.get("peak_profit_pct"),
                "entry_prob": r.get("entry_prob"),
                "city": city,
                "target_date": target_date.isoformat() if target_date else None,
                "days_out": days_out,
                "entered_at": entered_at,
                "settled": False,
                # Opus-review-caught (L7): paper trade ids and execution_log
                # row ids are BOTH plain incrementing integers -- disjoint
                # id spaces displayed together (e.g. check_aged_positions'
                # merged list) would otherwise show two different positions
                # as the same "#5" with no way to tell which is which.
                "live": True,
            }
        )
    return positions


def _live_dict_to_position(d: dict) -> Position:
    """Adapt one _get_live_open_positions() dict into the shared Position
    shape positions.py's check_stop_losses/check_breakeven_stops/
    update_peak_profits operate on. Mirrors paper._trade_to_position."""
    return Position(
        id=d["id"],
        ticker=d["ticker"],
        side=d.get("side", "yes"),
        quantity=d["quantity"],
        entry_price=d["entry_price"],
        cost=d["cost"],
        entry_prob=d.get("entry_prob"),
        close_time=d.get("close_time"),
        entered_at=d.get("entered_at"),
        peak_profit_pct=d.get("peak_profit_pct"),
    )


class LivePositionStore:
    """PositionStore backed by execution_log's SQLite rows. See
    paper.PaperPositionStore for the paper-side sibling -- both expose
    get_open/save_peak/exit so positions.update_peak_profits' save_peak
    callback and each side's own orchestrator can drive the shared
    stop-loss/breakeven/peak logic without either knowing the other's
    storage. get_open/save_peak conform to positions.PositionStore (see
    that Protocol's docstring for why exit() is deliberately not part of
    it) -- checked below the class body.

    client/cycle are bound at construction since exit() ultimately calls
    _exit_live_position, which needs both to actually place the protective
    exit order.
    """

    def __init__(self, client, cycle: str) -> None:
        self._client = client
        self._cycle = cycle

    def get_open(self) -> list[Position]:
        return [_live_dict_to_position(d) for d in _get_live_open_positions()]

    def save_peak(self, position: Position, peak_profit_pct: float) -> None:
        execution_log.update_live_peak_profit(position.id, peak_profit_pct)

    def exit(self, position: Position, exit_price: float, reason: str = "") -> bool:
        pos_dict = {
            "id": position.id,
            "ticker": position.ticker,
            "side": position.side,
            "quantity": position.quantity,
            "entry_price": position.entry_price,
            "close_time": position.close_time,
        }
        return _exit_live_position(
            self._client, pos_dict, exit_price, reason, self._cycle
        )


if TYPE_CHECKING:
    # mypy-only structural proof that LivePositionStore's get_open/save_peak
    # actually satisfy positions.PositionStore -- never executed, no runtime
    # cost, but catches the next signature drift the way an ABC would.
    _live_store_conforms: PositionStore = LivePositionStore(None, "")


def _exit_live_position(
    client, position: dict, exit_price: float, reason: str, cycle: str
) -> bool:
    """Place an immediate taker-cross sell to close an open live position.

    Re-runs only the kill-switch/trading-paused gate -- closing an existing
    position reduces exposure, so this is deliberately NOT subject to the
    daily-loss/spend/max-open-position gates (same reasoning already applied
    to _replace_live_order: those gates size NEW exposure, and blocking an
    exit is exactly backwards when the account already holds a position that
    needs to close). Corrected 2026-08-17: this comment previously also
    claimed main.py's cmd_order applies the same reduced gate on its manual
    sell path -- re-verified false. cmd_order runs the FULL
    trading_gates.pre_live_trade_check() (main.py:4522-4528) on every order,
    buy or sell, with no exit-specific carve-out; that's a real difference,
    not just stale documentation, and is out of scope for the recording-path
    fix cmd_order picked up in the same backlog entry that caught this.

    Scope note on partial fills: an immediate_or_cancel order can legally
    partial-fill (match what's immediately available, cancel the rest). This
    function only treats the ORIGINAL POSITION as closed when the full
    requested quantity fills -- a genuine partial fill (0 < fill_count <
    quantity) reduces the original position's tracked quantity by exactly
    the filled amount (execution_log.record_live_partial_exit) and realizes
    that portion's P&L immediately (add_live_loss), same as a full exit, but
    leaves the position open at its new smaller size -- the next cycle's
    _get_live_open_positions() picks it up again and any further protective
    exit is attempted against the reduced remainder, not the original
    quantity. Separately, THIS EXIT ORDER's own row (log_id below) IS marked
    settled with its own pnl (execution_log.record_live_early_exit) so the
    sold lot gets its own export_live_tax_csv row and counts toward
    get_live_pnl_summary -- see backlog.txt's now-resolved "aggregate-only
    P&L" entry for why this matters (a partial exit's realized P&L used to
    only ever land in the daily aggregate total, with no per-lot row at all).

    Every exit order logged below passes closes_position_id=position["id"]
    -- without it, this SELL order's own row (live=1, status='filled',
    settled_at NULL on itself regardless of full/partial outcome) would be
    indistinguishable from a genuine new entry fill and misidentified as a
    brand-new open position by the next get_filled_unsettled_live_orders()
    call. See execution_log.log_order's closes_position_id docstring.
    """
    from trading_gates import pre_live_trade_check

    ticker = position["ticker"]
    side = position["side"]
    qty = position["quantity"]

    try:
        pre_live_trade_check(client)
    except RuntimeError as _gate_err:
        _log.warning("[LiveExit] Gate blocked exit for %s: %s", ticker, _gate_err)
        return False

    # Batch-22 item 2: see _replace_live_order's matching comment.
    _cid = compute_client_order_id(ticker, side, "sell", qty, exit_price, cycle)
    log_id = execution_log.log_order(
        ticker=ticker,
        side=side,
        quantity=qty,
        price=exit_price,
        order_type="market",
        status="pending",
        response={"client_order_id": _cid},
        forecast_cycle=cycle,
        live=True,
        close_time=position.get("close_time"),
        closes_position_id=position["id"],
    )
    try:
        response = client.place_order(
            ticker=ticker,
            side=side,
            action="sell",
            count=qty,
            price=exit_price,
            time_in_force="immediate_or_cancel",
            cycle=cycle,
        )
    except OrderStatusUnknownError as _unk_exc:
        # AUD-0007: see _place_live_order's matching handler -- reconciliation
        # itself couldn't confirm either way, so this exit attempt must not be
        # marked 'failed' (which dedup guards would treat as never-sent).
        execution_log.log_order_result(
            log_id,
            status="unknown",
            error=str(_unk_exc),
            response={"client_order_id": _unk_exc.client_order_id},
        )
        _log.warning("[LiveExit] Exit outcome unknown for %s: %s", ticker, _unk_exc)
        return False
    except Exception as exc:
        execution_log.log_order_result(log_id, status="failed", error=str(exc))
        _log.warning("[LiveExit] Exit order failed for %s: %s", ticker, exc)
        return False

    # place_order()'s response is already the full get_order()-shaped dict
    # (it internally calls get_order() as a follow-up -- see its docstring),
    # and an IOC order's fate is final by the time that follow-up completes
    # (it either matched immediately or the unmatched remainder was
    # auto-canceled by the exchange) -- no separate poll needed here.
    fill_count = _to_fill_count(response.get("fill_count_fp")) if response else 0

    if not fill_count:
        execution_log.log_order_result(log_id, status="canceled", response=response)
        _log.warning(
            "[LiveExit] %s: IOC exit order did not fill (illiquid market?) — "
            "position remains open, will retry next cycle",
            ticker,
        )
        return False

    if fill_count < qty:
        execution_log.log_order_result(
            log_id, status="filled", response=response, fill_quantity=fill_count
        )
        # Fee/settlement math lives in execution_log.record_live_exit_fill so
        # main.cmd_order's manual live-sell path shares the exact same
        # formula instead of re-deriving it (backlog.txt "MANUAL cmd_order
        # LIVE ORDERS..." entry). That same fix also added a settled_at-race
        # guard that RAISES RuntimeError if a concurrent writer (now
        # possible: a manual cmd_order sell can race this automated exit
        # scanner against the same position) already settled the row first
        # -- must be caught here, not left to propagate. Uncaught, this
        # exception would climb through LivePositionStore.exit() into
        # _check_live_position_exits' caller in the watch/cron loop, which
        # has no generic exception handler (only KeyboardInterrupt around
        # the main loop) -- crashing the ENTIRE process and leaving every
        # OTHER live position unprotected until manually restarted, from a
        # race on just ONE position. Losing the race here is not a bug in
        # this exit attempt; the position is already handled by whoever won
        # -- log and retry next cycle, same as an unfilled/illiquid IOC.
        try:
            partial_pnl, _ = execution_log.record_live_exit_fill(
                position, fill_count, exit_price, reason=reason
            )
        except RuntimeError as _race_err:
            _log.warning(
                "[LiveExit] %s: partial-exit bookkeeping lost a race (%s) — "
                "position already settled by a concurrent writer, skipping",
                ticker,
                _race_err,
            )
            return False
        remaining_qty = qty - fill_count
        # Settle the EXIT ORDER's own row (not the position row -- that one
        # must stay open, see the docstring above) so this sold lot gets its
        # own tax-CSV row and counts toward get_live_pnl_summary instead of
        # only ever landing in the daily aggregate total. Reuses partial_pnl
        # from record_live_exit_fill above rather than recomputing it --
        # fill_count < qty already holds in this branch, so
        # record_live_exit_fill's own clamp (min(fill_count, qty)) is a
        # no-op here and the two figures are identical by construction.
        execution_log.record_live_early_exit(log_id, exit_price, reason, partial_pnl)
        _log.warning(
            "[LiveExit] %s: IOC exit PARTIALLY filled (%d/%d) via %s — "
            "position reduced to %d remaining, will retry next cycle "
            "(partial pnl=%.2f)",
            ticker,
            fill_count,
            qty,
            reason,
            remaining_qty,
            partial_pnl,
        )
        return False

    execution_log.log_order_result(
        log_id, status="filled", response=response, fill_quantity=fill_count
    )

    # This is a direct generalization of _poll_pending_orders' natural-
    # settlement formula (settlement is just the exit_price=1 or 0 special
    # case): fee only discounts a genuine GAIN (winnings), never applied to
    # a loss -- matching the established convention verified across
    # weather_markets.py/paper.py/order_executor.py (fee applies to
    # (1-entry_price) winnings, not to gross proceeds unconditionally). A
    # stop-loss/breakeven exit realizes a loss in the overwhelming common
    # case, so this matters: a proceeds*(1-fee) formula would overcharge fee
    # on every losing exit instead of correctly charging $0 fee on it. The
    # entry side already paid $0 (always a resting maker order), so only
    # this exit fill's fee applies. See execution_log.record_live_exit_fill's
    # own docstring for the shared implementation, and the partial-fill
    # branch above for why the RuntimeError it can raise must be caught here
    # rather than left to crash the watch/cron process.
    try:
        pnl, _ = execution_log.record_live_exit_fill(
            position, fill_count, exit_price, reason=reason
        )
    except RuntimeError as _race_err:
        _log.warning(
            "[LiveExit] %s: full-exit bookkeeping lost a race (%s) — the "
            "order filled on the exchange but a concurrent writer already "
            "settled this position row first; the fill itself is not lost "
            "(Kalshi has it), only this attempt's OWN bookkeeping is",
            ticker,
            _race_err,
        )
        return True
    _log.info(
        "[LiveExit] %s: exited via %s @ %.2f (pnl=%.2f)",
        ticker,
        reason,
        exit_price,
        pnl,
    )
    return True


def _check_live_position_exits(client, config: dict | None = None) -> None:
    """Protect open live positions with stop-loss and breakeven-stop checks,
    reusing positions.check_stop_losses()/check_breakeven_stops() unmodified
    -- the same functions paper.check_paper_position_exits uses.

    Must run AFTER _poll_pending_orders in the same cycle so a just-filled
    order is already visible via get_filled_unsettled_live_orders().
    """
    cycle = _current_forecast_cycle()
    store = LivePositionStore(client, cycle)
    positions = store.get_open()
    if not positions:
        return

    current_prices: dict[str, dict[str, float]] = {}
    for pos in positions:
        book = _get_current_book(client, pos.ticker)
        if book:
            # _get_current_book's WS-cache hit is already dollar floats, but
            # its REST fallback returns the raw client.get_market() dict
            # unchanged (integer cents, or only *_dollars keys present) --
            # coalesce_market_price normalizes either shape, matching
            # how every other _get_current_book caller in this file already
            # handles it (see _reprice_or_cancel_pending_orders below).
            current_prices[pos.ticker] = {
                "bid": coalesce_market_price(book, *YES_BID_KEYS),
                "ask": coalesce_market_price(book, *YES_ASK_KEYS),
            }

    _shared_update_peak_profits(positions, current_prices, store.save_peak)

    # Grouped by ticker (a list per ticker, not one dict slot) -- two
    # separate open live positions can legally share a ticker (two distinct
    # fills before either settles), unlike paper which is 1:1 by
    # construction via the duplicate-order guard. check_stop_losses()/
    # check_breakeven_stops() now return the triggered Position(s) directly,
    # but a triggered position's own ticker can still have OTHER same-ticker
    # positions that individually stayed under threshold -- erring toward
    # exiting every position on a flagged ticker (rather than just the one
    # that individually triggered) remains the safe direction for a
    # protective mechanism -- the failure mode being guarded against is a
    # position silently left with zero protection, not a position closing a
    # cycle earlier than its own individual threshold strictly required.
    by_ticker: dict[str, list[Position]] = {}
    for pos in positions:
        by_ticker.setdefault(pos.ticker, []).append(pos)

    sl_tickers = {pos.ticker for pos in check_stop_losses(positions, current_prices)}
    for ticker in sl_tickers:
        for target_pos in by_ticker.get(ticker, []):
            exit_price = _liquidation_price(current_prices, ticker, target_pos.side)
            if exit_price is None:
                exit_price = target_pos.entry_price
            store.exit(target_pos, exit_price, "stop_loss")

    # Reload — a stop-loss exit above must not also be considered for a
    # breakeven exit on the same cycle (already closed or exit attempted).
    remaining = [p for p in positions if p.ticker not in sl_tickers]
    be_tickers = {
        pos.ticker for pos in check_breakeven_stops(remaining, current_prices)
    }
    for ticker in be_tickers:
        # ticker-level exclusion above means a ticker can never appear in
        # both sl_tickers and be_tickers -- every position by_ticker[ticker]
        # returns here was genuinely part of `remaining`.
        for target_pos in by_ticker.get(ticker, []):
            exit_price = _liquidation_price(current_prices, ticker, target_pos.side)
            if exit_price is None:
                exit_price = target_pos.entry_price
            store.exit(target_pos, exit_price, "breakeven")


def _check_live_model_exits(client, config: dict | None = None) -> int:
    """Live equivalent of _check_early_exits (paper-only, above): re-analyze
    each open live position and close it if the model's probability has
    shifted meaningfully against the entry direction. Mirrors that
    function's exact gates (EXIT_MIN_HOLD_HOURS minimum hold,
    EXIT_SETTLEMENT_GATE_HOURS pre-settlement skip, MODEL_EXIT_SHIFT_PP shift
    threshold) for consistency. Kept as a separate function rather
    than extending _check_early_exits itself, to avoid any risk of
    regressing the existing, already-relied-on paper-only path.

    Positions with entry_prob=None (placed before that field existed, or a
    reprice/replacement row) are skipped, same as _check_early_exits does
    for paper trades missing entry_prob.

    Sources positions via LivePositionStore (positions.py's shared Position
    read-model) rather than reading _get_live_open_positions()'s raw dict
    fields directly -- built from a single fetch (not store.get_open(),
    which would re-fetch and risk seeing a different open-position set),
    mirroring _check_live_position_exits' own LivePositionStore usage.
    """
    if client is None:
        return 0

    raw_positions = _get_live_open_positions()
    if not raw_positions:
        return 0

    markets = get_weather_markets(client)
    markets_by_ticker = {m["ticker"]: m for m in markets}
    cycle = _current_forecast_cycle()
    store = LivePositionStore(client, cycle)

    from positions import _passes_exit_gates

    closed = 0
    for d in raw_positions:
        try:
            # Built inside the per-position try (not batched via a list
            # comprehension ahead of the loop, and not before this try
            # either) so a single malformed raw position dict -- e.g.
            # missing "id"/"quantity", which _live_dict_to_position
            # subscripts unguarded -- only drops that one position, not
            # every position already processed this cycle (opus review
            # finding, batch-18). The pre-refactor code's own unguarded
            # pos["ticker"] access was ALSO effectively try-protected by
            # virtue of "id"/"quantity"/etc. only being read later, deep
            # inside this same try (via _exit_live_position) -- building the
            # whole Position up front, even per-item, would have re-exposed
            # exactly that same failure mode one line earlier and outside
            # the guard.
            pos = _live_dict_to_position(d)
            ticker = pos.ticker
            entry_prob = pos.entry_prob
            side = pos.side
            if entry_prob is None:
                continue
            market = markets_by_ticker.get(ticker)
            if not market:
                continue  # market may have closed already
            enriched = enrich_with_forecast(market)
            analysis = analyze_trade(enriched)
            if not analysis:
                continue
            current_prob = analysis.get("forecast_prob", entry_prob)

            if side == "yes":
                shift = entry_prob - current_prob
            else:
                shift = current_prob - entry_prob

            if not _passes_exit_gates(
                ticker=ticker,
                log_tag="[LiveModelExit]",
                entered_at=pos.entered_at or "",
                close_time=pos.close_time,
                min_hold_hours=EXIT_MIN_HOLD_HOURS,
                settlement_gate_hours=EXIT_SETTLEMENT_GATE_HOURS,
            ):
                continue

            if shift > MODEL_EXIT_SHIFT_PP:
                book = _get_current_book(client, ticker) or market
                current_prices = {
                    ticker: {
                        "bid": coalesce_market_price(book, *YES_BID_KEYS),
                        "ask": coalesce_market_price(book, *YES_ASK_KEYS),
                    }
                }
                exit_price = _liquidation_price(current_prices, ticker, side)
                if exit_price is None or exit_price <= 0:
                    _log.debug(
                        "[LiveModelExit] skip %s — could not compute exit price",
                        ticker,
                    )
                    continue
                if store.exit(pos, exit_price, "model_exit"):
                    _log.info(
                        "[LiveModelExit] %s %s closed: entry_prob=%.2f current=%.2f",
                        ticker,
                        side.upper(),
                        entry_prob,
                        current_prob,
                    )
                    closed += 1
        except Exception as exc:
            _log.warning(
                "[LiveModelExit] Error checking %s: %s", d.get("ticker", "?"), exc
            )
            continue

    return closed


def _micro_live_gate_ok(client=None) -> bool:
    """Bool wrapper around trading_gates.pre_live_trade_check() for the
    micro-live if/elif chain, which the full-live path in _place_live_order()
    (below) enforces directly via its own try/except."""
    from trading_gates import pre_live_trade_check

    try:
        pre_live_trade_check(client)
        return True
    except RuntimeError:
        return False


def _place_live_order(
    ticker: str,
    side: str,
    analysis: dict,
    config: dict,
    client,
    cycle: str,
    kelly_qty: int = 1,
) -> tuple[bool, float]:
    """Place a live Kalshi order with hard-stop guards.

    Returns (placed, dollar_cost). F7: the daily live-loss counter
    (execution_log.add_live_loss) is now updated ONLY at settlement, not by
    the caller at placement time -- see the settlement loop below.
    """
    # 0. Graduation + safety gate — must pass before any live order
    from trading_gates import pre_live_trade_check

    try:
        pre_live_trade_check(client)
    except RuntimeError as _gate_err:
        _log.warning("[LIVE] Gate blocked %s: %s", ticker, _gate_err)
        return False, 0.0

    # 1. Daily loss check
    if execution_log.get_today_live_loss() >= config.get(
        "daily_loss_limit", float("inf")
    ):  # M-5: avoid KeyError
        # F10: the comparison above already defaults via .get() (reachable
        # with no default set when get_today_live_loss() fails closed to
        # inf); the print used a bare config['daily_loss_limit'] on the same
        # branch, which would raise an uncaught KeyError instead of skipping
        # the trade cleanly.
        print(
            f"[LIVE] Daily loss limit ${config.get('daily_loss_limit', 'inf')} "
            f"reached — skipping {ticker}"
        )
        return False, 0.0

    # 1b. Daily live spend cap — deep-review followup: F7 correctly removed
    # placement-time add_live_loss(cost) (it double-counted with
    # settlement-time add_live_loss(-pnl)), but that call had also been the
    # only thing giving a long-running `watch --auto --live` session (5-min
    # loop, cmd_watch) a cross-cycle brake on live spend: _daily_paper_spend
    # /_daily_sameday_spend in _auto_place_trades only ever read
    # paper_trades.json and are blind to live orders, so daily_spent resets
    # to 0 for live activity every single cycle with nothing else bounding
    # cumulative same-day live spend. get_today_live_spend() is a dedicated,
    # persistent spend counter (not the realized-loss counter F7 fixed), so
    # this doesn't reintroduce the double-count.
    if execution_log.get_today_live_spend() >= MAX_DAILY_SPEND:
        print(
            f"[LIVE] Daily live spend cap ${MAX_DAILY_SPEND:.0f} reached — "
            f"skipping {ticker}"
        )
        return False, 0.0

    # 2. Open position check
    _max_open = config.get("max_open_positions", 10)
    if _count_open_live_orders() >= _max_open:
        print(f"[LIVE] Max open positions {_max_open} reached — skipping {ticker}")
        return False, 0.0

    # 3. Size computation — Kelly quantity, capped by max_trade_dollars
    market = analysis.get("market", {})
    # H-5: validate that at least one real price exists before computing midpoint.
    # A missing/empty market dict produces a fabricated 50¢ price via _midpoint_price defaults.
    # Checks both legacy (yes_bid/yes_ask) and current (yes_bid_dollars/yes_ask_dollars)
    # API field names via parse_market_price's has_quote flag.
    if not parse_market_price(market)["has_quote"]:
        _log.warning(
            "[LIVE] %s: market dict has no bid or ask — cannot price order, skipping",
            ticker,
        )
        return False, 0.0
    price = _midpoint_price(market, side)
    if price <= 0:
        return False, 0.0
    max_qty = math.floor(config["max_trade_dollars"] / price)
    quantity = min(kelly_qty, max_qty)
    if quantity <= 0:
        return False, 0.0
    dollar_cost = round(quantity * price, 2)

    # 4. Cycle deduplication check
    if execution_log.was_ordered_this_cycle(ticker, side, cycle):
        return False, 0.0

    # 5. Pre-log BEFORE touching the API — crash recovery depends on this record.
    #    If the process dies between here and step 6, the "pending" row is the
    #    only evidence the order was attempted; _recover_pending_orders() at next
    #    startup will reconcile it against the Kalshi API. Batch-22 item 2:
    #    response={"client_order_id": ...} stashed here too (matches
    #    place_order()'s own internal derivation), so a crash before step 6's
    #    result is recorded can still be reconciled against Kalshi instead of
    #    marked 'sent' and never re-checked -- see
    #    kalshi_client.compute_client_order_id's own docstring.
    _cid = compute_client_order_id(ticker, side, "buy", quantity, price, cycle)
    log_id = execution_log.log_order(
        ticker=ticker,
        side=side,
        quantity=quantity,
        price=price,
        order_type="limit",
        status="pending",
        response={"client_order_id": _cid},
        forecast_cycle=cycle,
        live=True,
        close_time=market.get("close_time") or market.get("expiration_time"),
        entry_prob=analysis.get("forecast_prob"),
    )

    # 6. Place order
    try:
        response = client.place_order(
            ticker=ticker,
            side=side,
            action="buy",
            count=quantity,
            price=price,
            time_in_force="good_till_canceled",
            cycle=cycle,
        )
    except OrderStatusUnknownError as _unk_exc:
        # AUD-0007: reconciliation itself couldn't confirm either way --
        # 'unknown', not 'failed', so dedup guards keep blocking a retry and
        # _recover_pending_orders can re-check it via client_order_id once
        # the API is healthy again.
        execution_log.log_order_result(
            log_id,
            status="unknown",
            error=str(_unk_exc),
            response={"client_order_id": _unk_exc.client_order_id},
        )
        print(f"[LIVE] Order outcome unknown for {ticker}: {_unk_exc}")
        return False, 0.0
    except Exception as exc:
        execution_log.log_order_result(
            log_id,
            status="failed",
            error=str(exc),
        )
        print(f"[LIVE] Order failed for {ticker}: {exc}")
        return False, 0.0

    # Opus review follow-up (AUD-0007, round 2): this write must not share
    # the try above with the placement call (a bookkeeping-only failure
    # here must not mark a REAL live order 'failed') -- but round 2 caught
    # that moving it below the try/except ALSO means an unhandled exception
    # here now propagates straight out of _place_live_order, up through
    # _auto_place_trades (no enclosing try at that call site) and
    # run_trade_cycle, into cmd_watch's `if auto_trade:` block -- which has
    # no except clause -- killing the entire persistent watch process. The
    # exact AUD-0008 failure mode, freshly reintroduced by AUD-0007's own
    # round-1 fix. Caught here instead: the pre-logged row already stays
    # 'pending' with no order_id/response if this write never lands, and
    # _recover_pending_orders' existing no-order_id branch already handles
    # exactly that shape safely (marks it 'sent', blocking a duplicate
    # placement) -- so failing to update the row here is recoverable, not
    # silent data loss. The order genuinely IS live on the exchange
    # regardless of whether this local write succeeds, so still return
    # True/dollar_cost rather than falsely reporting the placement failed.
    try:
        # "pending", not "placed" — every downstream lifecycle consumer
        # (fill polling, GTC cancel, max_open_positions, PnL summary)
        # filters on status="pending"; "placed" was invisible to all of
        # them and never transitioned further.
        execution_log.log_order_result(
            log_id,
            status="pending",
            response=response,
        )
    except Exception as _bk_exc:
        _log.warning(
            "[LIVE] %s: order placed on exchange but bookkeeping write "
            "failed (%s) -- row stays pre-logged 'pending', "
            "_recover_pending_orders will reconcile it",
            ticker,
            _bk_exc,
        )
    return True, dollar_cost


# ---------------------------------------------------------------------------
# Paper spend helper
# ---------------------------------------------------------------------------


def _daily_paper_spend() -> float:
    """Sum of multi-day paper trade costs placed today (UTC date). Used for daily spend cap.

    Same-day trades (days_out=0) are excluded because they have their own separate
    dollar cap (MAX_SAME_DAY_SPEND) tracked by _daily_sameday_spend(). Including
    them here would drain MAX_DAILY_SPEND and block multi-day signals.
    Legacy trades with no days_out field are treated as multi-day (included).
    """
    from paper import _load

    today = datetime.now(UTC).date().isoformat()
    data = _load()
    return sum(
        t.get("cost", 0.0)
        for t in data["trades"]
        if t.get("entered_at", "")[:10] == today
        and t.get("days_out", 1)
        != 0  # exclude same-day; legacy (None) treated as multi-day
    )


def _daily_sameday_spend() -> float:
    """Sum of same-day paper trade costs placed today (UTC date). Used for same-day spend cap.

    Only counts trades with days_out=0. These are already rate-limited by
    MAX_SAME_DAY_POSITIONS (count cap); this provides a parallel dollar cap via
    MAX_SAME_DAY_SPEND so large Kelly sizes cannot exhaust the full balance in one day.
    Legacy trades with no days_out field are treated as multi-day (not counted here).
    """
    from paper import _load

    today = datetime.now(UTC).date().isoformat()
    data = _load()
    return sum(
        t.get("cost", 0.0)
        for t in data["trades"]
        if t.get("entered_at", "")[:10] == today
        and t.get("days_out") == 0  # strict equality — legacy (None) falls to multi-day
    )


# ---------------------------------------------------------------------------
# Same-day slot reservation
# ---------------------------------------------------------------------------


def _sameday_effective_cap(max_positions: int) -> int:
    """Effective same-day slot cap for the current UTC hour.

    Dynamic mode: scales cap by Bayesian-blended per-band win rate vs baseline.
    Static mode (legacy): holds back a fixed number of slots before a fixed UTC hour.
    Fails open on any error — a lookup failure never blocks trades.
    """
    from utils import (
        SAME_DAY_DYNAMIC_BAND_HOURS,
        SAME_DAY_DYNAMIC_K,
        SAME_DAY_DYNAMIC_SLOTS,
        SAME_DAY_RESERVE_AFTER_HOUR_UTC,
        SAME_DAY_RESERVE_MIN_SAMPLES,
        SAME_DAY_RESERVE_SLOTS,
    )

    # Fast path: both systems disabled — skip DB call entirely
    if not SAME_DAY_DYNAMIC_SLOTS and SAME_DAY_RESERVE_SLOTS <= 0:
        return max_positions

    # Dynamic mode: Bayesian shrinkage of per-band win rate toward baseline
    if SAME_DAY_DYNAMIC_SLOTS:
        try:
            if SAME_DAY_DYNAMIC_BAND_HOURS <= 0 or SAME_DAY_DYNAMIC_K <= 0:
                _log.warning(
                    "_sameday_effective_cap: invalid config (K=%d band_hours=%d), skipping dynamic mode",
                    SAME_DAY_DYNAMIC_K,
                    SAME_DAY_DYNAMIC_BAND_HOURS,
                )
                return max_positions

            from paper import get_sameday_band_stats

            stats = get_sameday_band_stats(SAME_DAY_DYNAMIC_BAND_HOURS)
            baseline = stats["baseline"]
            # Gate on the same above/below settled-trade pool the formula below
            # draws from. count_settled_sameday_predictions() counts a different,
            # broader pool (every days_out=0 market type in the ML tracking
            # table) — passing that check doesn't mean this pool has enough
            # samples to trust a per-band win-rate split.
            if baseline["total"] < SAME_DAY_RESERVE_MIN_SAMPLES:
                return max_positions  # not enough same-day above/below data yet
            if baseline["total"] == 0:
                return max_positions
            baseline_wr = baseline["wins"] / baseline["total"]
            if baseline_wr == 0:
                # All trades lost — strongest possible signal, cap at floor
                return 1
            hour = datetime.now(UTC).hour
            band = hour // SAME_DAY_DYNAMIC_BAND_HOURS
            b_data = stats["bands"].get(band, {"wins": 0, "total": 0})
            N = b_data["total"]
            band_wr = b_data["wins"] / N if N > 0 else baseline_wr
            K = SAME_DAY_DYNAMIC_K
            blended_wr = (N / (N + K)) * band_wr + (K / (N + K)) * baseline_wr
            scale = blended_wr / baseline_wr
            cap = max(1, min(max_positions, round(max_positions * scale)))
            if cap < max_positions:
                _log.info(
                    "_sameday_effective_cap: band=%d hour=%d cap=%d/%d "
                    "(baseline=%.0f%% band_wr=%.0f%% N=%d blended=%.0f%%)",
                    band,
                    hour,
                    cap,
                    max_positions,
                    baseline_wr * 100,
                    band_wr * 100,
                    N,
                    blended_wr * 100,
                )
            return cap
        except Exception:
            return max_positions  # fail open

    # Static mode (legacy): hold back fixed slots before a fixed UTC hour
    if SAME_DAY_RESERVE_SLOTS <= 0:
        return max_positions

    try:
        from tracker import count_settled_sameday_predictions

        settled = count_settled_sameday_predictions()
    except Exception:
        return max_positions  # fail open — never block trades on a lookup error

    if settled < SAME_DAY_RESERVE_MIN_SAMPLES:
        return max_positions  # not enough data yet
    if datetime.now(UTC).hour >= SAME_DAY_RESERVE_AFTER_HOUR_UTC:
        return max_positions  # past cutoff hour, release reserved slots
    return max(0, max_positions - SAME_DAY_RESERVE_SLOTS)


# ---------------------------------------------------------------------------
# Early exit
# ---------------------------------------------------------------------------


def _check_early_exits(client=None) -> int:
    """
    Re-analyze all open paper positions. If the updated model probability has
    shifted more than MODEL_EXIT_SHIFT_PP (default 25 percentage points) against
    the entry direction, close the position early at the realizable bid/ask
    price (see _liquidation_price) -- the same convention
    _check_live_model_exits uses for live positions.

    Returns the number of positions closed.

    Sources positions via PaperPositionStore (positions.py's shared Position
    read-model) rather than reading get_open_trades()'s raw dict fields
    directly -- built from a single fetch (not store.get_open(), which
    would re-fetch and risk seeing a different open-trades set), mirroring
    paper.check_paper_position_exits' own single-fetch + adapter pattern.
    """
    import paper as _paper
    from paper import get_open_trades
    from positions import _passes_exit_gates

    if client is None:
        return 0  # cannot fetch live market prices without a client

    open_trades = get_open_trades()
    if not open_trades:
        return 0

    markets = get_weather_markets(client)
    markets_by_ticker = {m["ticker"]: m for m in markets}
    store = _paper.PaperPositionStore()

    closed = 0
    for t in open_trades:
        try:
            # Built inside the per-trade try (not batched via a list
            # comprehension ahead of the loop, and not before this try
            # either) so a single malformed trade dict -- e.g. missing "id",
            # which _trade_to_position subscripts unguarded -- only drops
            # that one trade, not every trade already processed this cycle
            # (opus review finding, batch-18). The pre-refactor code's own
            # `.get()`-based ticker/entry_prob/side extraction never raised
            # here; "id" itself was only read later, inside this same try
            # (via close_paper_early(trade["id"], ...)) -- building the
            # whole Position up front would have moved that same failure
            # mode outside the guard.
            pos = _paper._trade_to_position(t)
            ticker = pos.ticker
            entry_prob = pos.entry_prob
            side = pos.side
            if entry_prob is None:
                continue  # cannot assess shift without entry probability
            market = markets_by_ticker.get(ticker)
            if not market:
                continue  # market may have closed already
            enriched = enrich_with_forecast(market)
            analysis = analyze_trade(enriched)
            if not analysis:
                continue
            current_prob = analysis.get("forecast_prob", entry_prob)

            # Shift direction check
            if side == "yes":
                shift = entry_prob - current_prob  # positive = prob fell against YES
            else:
                shift = current_prob - entry_prob  # positive = prob rose against NO

            # Minimum hold time, then the settlement-convergence gate — same
            # rationale as paper.py's check_stop_losses: GFS intraday updates can
            # shift forecast_prob sharply in the final hours before settlement
            # without the temperature outcome actually changing, so let the market
            # converge naturally rather than closing on a transient model revision.
            if not _passes_exit_gates(
                ticker=ticker or "?",
                log_tag="[EarlyExit]",
                entered_at=pos.entered_at or "",
                close_time=pos.close_time,
                min_hold_hours=EXIT_MIN_HOLD_HOURS,
                settlement_gate_hours=EXIT_SETTLEMENT_GATE_HOURS,
            ):
                continue

            if shift > MODEL_EXIT_SHIFT_PP:
                book = _get_current_book(client, ticker) or market
                current_prices = {
                    ticker: {
                        "bid": coalesce_market_price(book, *YES_BID_KEYS),
                        "ask": coalesce_market_price(book, *YES_ASK_KEYS),
                    }
                }
                exit_price = _liquidation_price(current_prices, ticker, side)
                # H-4: never close at zero/no-quote — a missing or invalid
                # quote must skip this cycle, not record a fabricated price.
                if exit_price is None or exit_price <= 0:
                    _log.debug(
                        "[EarlyExit] skip %s — could not compute exit price (market data missing)",
                        ticker,
                    )
                    continue
                result = store.exit(pos, exit_price)
                _log.info(
                    f"[EarlyExit] #{pos.id} {ticker} {side.upper()} closed: "
                    f"entry_prob={entry_prob:.2f} current={current_prob:.2f} "
                    f"pnl=${result['pnl']:.2f}"
                )
                closed += 1
        except Exception as exc:
            import traceback as _tb

            _log.warning(
                f"[EarlyExit] Error checking {t.get('ticker', '?')}: "
                f"{exc}\n{_tb.format_exc()}"
            )
            continue

    return closed


# ---------------------------------------------------------------------------
# Trade validation
# ---------------------------------------------------------------------------


def _validate_trade_opportunity(
    opp: dict, live: bool = False, market: dict | None = None
) -> tuple[bool, str]:
    """
    Pre-execution validation gate for auto-placed trades (P1.1+P1.2).
    Returns (ok, reason). All checks must pass before a trade is placed.

    market: the raw market dict (bid/ask quotes), separate from opp (the
    analysis dict) — used for the flash-crash price feed. F3: opp itself
    never carries yes_bid/yes_ask (it's analyze_trade's result, which has
    no price keys), so the flash-crash circuit breaker never received a
    single real price until this parameter was added.
    """
    import time as _t

    # P1.2 / P3.3 — system health gate
    from system_health import check_system_health

    health = check_system_health()
    if not health.healthy:
        _log.warning(
            "_validate_trade_opportunity: system health gate blocked trade: %s",
            health.reason,
        )
        return False, health.reason

    # Try WebSocket cache for fresher price first
    try:
        from kalshi_ws import get_cached_mid_price

        cached_mid = get_cached_mid_price(opp["ticker"])
        if cached_mid and cached_mid > 0:
            # Use cached price — it's more recent than REST poll
            opp["_ws_mid_price"] = cached_mid
    except Exception as _exc:
        _log.debug("WS cache lookup skipped: %s", _exc)

    # Flash crash check — fail closed on any internal error. Prefer the
    # fresher WebSocket-cached mid-price; otherwise derive it from the real
    # market quote via the canonical parser. opp (analyze_trade's result) has
    # no yes_bid/yes_ask of its own — reading opp.get("yes_bid") directly here
    # (the old code) always returned 0, so this check never once fired.
    try:
        from circuit_breaker import flash_crash_cb

        _ws_mid = opp.get("_ws_mid_price")
        if _ws_mid and _ws_mid > 0:
            mid = float(_ws_mid)
        elif market is not None:
            mid = parse_market_price(market)["mid"]
        else:
            mid = 0.0
        if mid > 0:
            flash_crash_cb.check(opp["ticker"], float(mid))
        if flash_crash_cb.is_in_cooldown(opp["ticker"]):
            return False, "flash crash cooldown"
    except Exception as _fc_exc:
        _log.error(
            "flash crash check raised unexpectedly: %s — blocking trade", _fc_exc
        )
        return False, f"flash crash check error: {_fc_exc}"

    # Between-bucket markets are gated upstream in weather_markets.analyze_trade:
    # only signals with METAR lock-in AND (for YES bets) ≥1.5°F clearance from the
    # band edge reach this point.  The old gate here used the wrong key name and
    # never fired — logic moved to the correct location.

    # Edge check — net_edge must be positive, raw edge must agree with side, and
    # raw edge must clear MIN_EDGE so near-zero-price contracts don't slip through
    from utils import MIN_EDGE as _MIN_EDGE

    edge = opp.get("net_edge")
    if edge is None:
        edge = 0.0
    if edge <= 0:
        return False, f"edge={edge:.4f} <= 0"
    if opp.get("edge") is not None:
        raw_edge = opp["edge"]
        side = opp.get("recommended_side", "yes")
        if side == "yes" and raw_edge <= 0:
            return False, f"raw_edge={raw_edge:.4f} <= 0 for YES recommendation"
        if side == "no" and raw_edge >= 0:
            return False, f"raw_edge={raw_edge:.4f} >= 0 for NO recommendation"
        if abs(raw_edge) < _MIN_EDGE:
            return False, f"raw_edge={raw_edge:.4f} below MIN_EDGE={_MIN_EDGE:.4f}"

    # Confidence-tiered edge threshold (backward compatible)
    _ens_spread = opp.get("ensemble_spread")
    if _ens_spread is not None:
        try:
            from utils import get_min_edge_for_confidence

            min_edge = get_min_edge_for_confidence(
                float(_ens_spread), is_live=bool(live)
            )
        except Exception:
            min_edge = get_paper_min_edge() if not live else MIN_EDGE
    else:
        min_edge = get_paper_min_edge() if not live else MIN_EDGE

    # For paper mode, pick the A/B test variant and use its threshold.
    # Only override when no ensemble-spread confidence tiering was applied —
    # confidence tiering already raises the bar; the AB test owns the base case.
    if not live:
        try:
            _ab_variant_name, _ab_variant_val = _MIN_EDGE_AB_TEST.pick_variant()
            if _ab_variant_val is not None:
                opp["_ab_variant"] = (
                    _ab_variant_name  # carry forward to place_paper_order
                )
                if _ens_spread is None:  # tiering inactive — AB test owns min_edge
                    min_edge = float(_ab_variant_val)
        except Exception as _ab_exc:
            _log.debug("_auto_place_trades: A/B variant pick failed: %s", _ab_exc)

    if edge < min_edge:
        return False, f"edge {edge:.1%} < {min_edge:.1%} (spread={_ens_spread})"

    # Kelly check
    kelly = opp.get("ci_adjusted_kelly")
    if kelly is None:
        kelly = opp.get("fee_adjusted_kelly")
    if kelly is None:
        kelly = 0.0
    if kelly < 0.002:
        _ep = opp.get("entry_price", "?")
        _fp = opp.get("forecast_prob", "?")
        _side = opp.get("recommended_side", "?")
        return (
            False,
            f"kelly={kelly:.4f} too small (forecast={_fp} entry={_ep} side={_side})",
        )

    # Ticker check
    ticker = opp.get("ticker", "")
    if not ticker:
        return False, "missing ticker"

    # Data freshness check — absent timestamp means caller doesn't track age, allow it
    from weather_markets import FORECAST_MAX_AGE_SECS

    fetched_at = opp.get("data_fetched_at")
    if fetched_at is not None:
        age = _t.time() - fetched_at
        if age > FORECAST_MAX_AGE_SECS:
            return False, f"stale data (age={age:.0f}s > {FORECAST_MAX_AGE_SECS}s)"

    return True, "ok"


# ---------------------------------------------------------------------------
# Auto trade placement
# ---------------------------------------------------------------------------


def _unpack_opp(item) -> tuple[str, str | None, date | None, dict, dict]:
    """Extract (ticker, city, target_date, analysis_dict, market_dict) from an
    opp item.

    Handles both (market_dict, analysis_dict) tuple format (legacy watch mode)
    and flat opportunity dicts (new live path / tests) — the same two shapes
    _auto_place_trades' main loop accepts. market_dict is returned so callers
    can pass real bid/ask quotes into _validate_trade_opportunity's flash-crash
    check (F3) — the analysis_dict alone never carries price fields.
    """
    if isinstance(item, tuple):
        m, a = item
    else:
        m, a = item, item
    ticker = m.get("ticker", "") or a.get("ticker", "")
    city = m.get("_city") or a.get("city")
    target_date_obj = m.get("_date")
    if target_date_obj is None:
        _raw_date = a.get("target_date")
        if isinstance(_raw_date, str):
            try:
                target_date_obj = date.fromisoformat(_raw_date)
            except ValueError:
                _log.warning(
                    "_unpack_opp: unparseable target_date %r for ticker %s — "
                    "treating as None (grouping/cap keys will miss this trade)",
                    _raw_date,
                    ticker,
                )
                target_date_obj = None
        elif hasattr(_raw_date, "isoformat"):
            target_date_obj = _raw_date
    return ticker, city, target_date_obj, a, m


def _prediction_kwargs_from_analysis(a: dict) -> dict:
    """Build the tracker.log_prediction() keyword args shared by the real
    post-placement call and shadow logging, so both derive ens_mean/ens_var,
    run_trend, and the other blend metadata identically.

    run_trend is fetched HERE (log time) rather than read from `a`, since
    analyze_trade() deliberately doesn't compute it -- see
    tracker.get_forecast_run_trend_from_analysis's docstring for why (keeps
    the up-to-3-HTTP-call fetch off the order-placement critical path). For
    the real post-placement call this runs after the order is already
    placed; for shadow logging there was never an order to delay.

    market_implied (implied_mean/implied_sigma/fit_residual), by contrast,
    IS read from `a` rather than computed here: it's a per-EVENT fit over
    the full sibling bracket ladder (weather_markets.
    fit_market_implied_distribution), not derivable from this one market's
    analysis dict alone. cron.py's/main.py's scan loops compute it once per
    scan (CPU-only, no network calls, cheap) and attach it onto each
    market's own `analysis["market_implied"]` before this function ever
    runs -- see backlog.txt "MARKET-IMPLIED TEMPERATURE DISTRIBUTION FROM
    THE FULL LADDER". Deliberately scan-paths-only: cmd_market/cmd_order's
    single-market analysis dicts never have this key set, so those calls
    naturally log NULL for these 3 columns rather than triggering an extra
    live get_weather_markets() fetch just to service a manual lookup.

    liquidity_edge_scale/gated_edge (backlog.txt "LIQUIDITY-AWARE SIZING +
    DYNAMIC EDGE THRESHOLD") are also read from `a`, same reasoning as
    market_implied -- attached by cron.py's/main.py's scan loops, scan-
    paths-only. gated_edge is LOG-ONLY: it is never used anywhere to
    reclassify a signal's STRONG/MED/MIN tier -- only the real-time Kelly-
    size scale half of that backlog item (paper.liquidity_kelly_scale,
    wired directly into this function's own caller's sizing math) has a
    live effect today."""
    from tracker import get_forecast_run_trend_from_analysis as _get_run_trend
    from weather_markets import EDGE_CALC_VERSION as _ECV

    _es = a.get("ensemble_stats") or {}
    _std = _es.get("std")
    _mi = a.get("market_implied") or {}
    return dict(
        ensemble_prob=a.get("ensemble_prob"),
        nws_prob=a.get("nws_prob"),
        clim_prob=a.get("clim_prob"),
        forecast_cycle=_current_forecast_cycle(),
        edge_calc_version=_ECV,
        signal_source=a.get("method"),
        blend_sources=a.get("blend_sources"),
        model_consensus=a.get("model_consensus"),
        ens_mean=_es.get("mean"),
        ens_var=(_std * _std if _std is not None else None),
        run_trend=_get_run_trend(a),
        implied_mean=_mi.get("implied_mean"),
        implied_sigma=_mi.get("implied_sigma"),
        fit_residual=_mi.get("fit_residual"),
        liquidity_edge_scale=a.get("liquidity_edge_scale"),
        gated_edge=a.get("gated_edge"),
        # backlog.txt "RICHER ML CALIBRATION FEATURES" + "FORECAST-CONDITION
        # COVARIATES FOR SIGMA" -- log-only, both already computed onto `a`
        # by analyze_trade(), not derived here.
        ensemble_spread_f=a.get("ensemble_spread_f"),
        model_disagreement_f=a.get("model_disagreement_f"),
        precip_sum_in=a.get("precip_sum_in"),
        # backlog.txt "NBM PROBABILISTIC QUANTILES" -- log-only, already
        # computed onto `a` by analyze_trade(), not derived here.
        nbm_quantile_prob=a.get("nbm_quantile_prob"),
        # backlog.txt "3-WAY MODEL_CONSENSUS CHECK" -- log-only, already
        # computed onto `a` by analyze_trade(), not derived here.
        ecmwf_consensus_gap_prob=a.get("ecmwf_consensus_gap_prob"),
        # backlog.txt "SIGNAL GRADUATION IS A CONVENTION, NOT A MECHANISM" --
        # the generic path for any FUTURE log-only signal: analyze_trade()
        # sets `a["signals"]` (a dict[str, float]) and it flows through here
        # with zero further wiring, unlike every named field above. No
        # signal uses this yet -- a.get() naturally gives None until one
        # does. NOTE: "signals" here means this dict specifically -- unlike
        # this codebase's other, unrelated use of "signal(s)" for a scanned
        # trade candidate (cron.py's signals_cache, "no qualifying signals"
        # elsewhere in this file) -- don't confuse the two. `a` is untyped
        # (a plain dict), so nothing stops a future caller from accidentally
        # attaching that other kind of "signals" here; tracker.log_prediction
        # would silently json.dumps whatever it is into signal_values.
        signals=a.get("signals"),
    )


def _log_shadow_predictions(opps: list, live: bool = False) -> set[str]:
    """Log predictions for signals that passed analysis but were never placed
    (TRADING_PAUSED, drawdown halt, daily-loss halt, or position/spend caps —
    see the early-return branches below).

    _auto_place_trades normally calls tracker.log_prediction() only after a
    trade is actually placed, so brier_score_by_method() — and the strategy
    auto-retirement logic that reads it — goes stale for as long as no trades
    are placed. This mirrors that same log_prediction() call for opps that
    would have been traded, so scoring keeps reflecting current forecast
    quality instead of freezing.

    Applies the same quality/dedup gates the real placement loop applies
    (_validate_trade_opportunity, already-open, was_ordered_recently,
    was_traded_today) before logging — otherwise a stale/negative-edge/
    already-held signal that the real loop would silently reject gets written
    into the same table that drives auto-retirement decisions, corrupting the
    exact scoring this function exists to keep honest.

    Writes are batched onto a single connection (mirrors
    tracker.batch_log_analysis_attempts' approach to the same "log every
    candidate" problem) rather than one connection open/close per opp.
    AUD-0021: this batching only actually helps if callers pass the full set
    of candidate opps in ONE call -- _auto_place_trades does that for every
    caller now (see its per-family shadow-routing loop, which accumulates
    across the whole batch instead of calling this once per ticker).

    Opus review (round 1): gate/validate/kwargs-building runs as its own
    pass BEFORE the connection ever opens, specifically because
    _prediction_kwargs_from_analysis's run_trend fetch can make up to 3
    sequential HTTP calls (its own docstring: "up to ~60s worst case on a
    cache miss") per opp. tracker.db has no configured connect() timeout
    (tracker._conn uses sqlite3's 5s default), so holding the write lock
    open across N opps' worth of that -- taken at this loop's first INSERT,
    released only at the very end -- risked starving any concurrent writer
    (web_app, another cron step, log_api_request from any Kalshi call on
    another thread) with `database is locked` well before this loop
    finished. The actual DB writes below are now pure local INSERTs with no
    I/O in between, so the connection's held duration no longer scales with
    batch size.

    Returns the set of tickers actually written (excludes opps that failed
    validation/dedup, or that log_prediction itself skipped, e.g. for a
    missing city) -- a set, not a count, so a caller that shadow-routed
    several distinct families in one batched call can still tell exactly
    which of ITS tickers landed.
    """
    from paper import get_all_open_positions
    from tracker import _conn as _tracker_conn
    from tracker import log_prediction as _log_pred

    try:
        # Opus-review-caught (L8): get_all_open_positions() (paper + live),
        # matching the real placement loop's own open_tickers below --
        # otherwise a ticker held LIVE gets shadow-logged here as if it
        # were a genuine candidate the real loop would have traded, when
        # the real loop would actually skip it as already-open, mildly
        # polluting the auto-retirement scoring this function exists to
        # keep honest.
        open_tickers = {t["ticker"] for t in get_all_open_positions()}
    except Exception as _e:
        _log.warning("_log_shadow_predictions: get_all_open_positions failed: %s", _e)
        open_tickers = set()

    # Pass 1: unpack/gate/validate every opp and build its log_prediction
    # kwargs (including the potentially-slow run_trend HTTP fetch) -- all
    # BEFORE the tracker connection opens. Only opps that clear every gate
    # reach pass 2.
    _to_write: list[tuple[str, str | None, date | None, dict, dict]] = []
    for item in opps:
        try:
            ticker, city, target_date_obj, a, m = _unpack_opp(item)
        except Exception as _e:
            _log.warning(
                "_log_shadow_predictions: failed to unpack opp %r: %s", item, _e
            )
            continue
        if not ticker or ticker in open_tickers:
            continue
        rec_side = a.get("recommended_side", a.get("side", "yes"))
        if execution_log.was_ordered_recently(
            ticker, days=7
        ) or execution_log.was_traded_today(ticker, rec_side):
            continue
        _ok, _reason = _validate_trade_opportunity(
            {**a, "ticker": ticker}, live=live, market=m
        )
        if not _ok:
            _log.debug("_log_shadow_predictions: skip %s — %s", ticker, _reason)
            continue
        try:
            _kwargs = _prediction_kwargs_from_analysis(a)
        except Exception as _e:
            _log.warning(
                "_log_shadow_predictions: building log_prediction kwargs "
                "failed for %s: %s",
                ticker,
                _e,
            )
            continue
        _to_write.append((ticker, city, target_date_obj, a, _kwargs))

    # Pass 2: one connection, pure local writes -- no I/O between opps.
    logged_tickers: set[str] = set()
    if _to_write:
        with _tracker_conn() as _con:
            for ticker, city, target_date_obj, a, _kwargs in _to_write:
                try:
                    if _log_pred(
                        ticker,
                        city,
                        target_date_obj,
                        a,
                        is_shadow=True,
                        conn=_con,
                        **_kwargs,
                    ):
                        logged_tickers.add(ticker)
                except Exception as _e:
                    _log.warning(
                        "_log_shadow_predictions: log_prediction failed for %s: %s",
                        ticker,
                        _e,
                    )
    return logged_tickers


def _auto_place_trades(
    opps: list,
    client=None,
    live: bool = False,
    live_config: dict | None = None,
    cap: float | None = None,  # per-trade dollar cap (None = dynamic Brier cap)
) -> int:
    """
    Auto-place paper or live trades for signals not already held.
    Called from cmd_cron (tiered) and watch --auto mode. Respects drawdown guard and portfolio Kelly.

    opps may be a list of (market_dict, analysis_dict) tuples (legacy watch mode)
    or a list of flat opportunity dicts (new live path / tests).
    Pass live=True with a live_config dict to route orders to the real Kalshi API.
    cap: per-trade dollar cap; if None, uses dynamic Brier cap.
    """
    from paper import (
        consensus_fraction_cap,
        corr_kelly_scale,
        drawdown_scaling_factor,
        get_open_trades,
        is_daily_loss_halted,
        is_paused_drawdown,
        is_streak_paused,
        kelly_quantity,
        liquidity_kelly_scale,
        portfolio_kelly_fraction,
    )

    def _shadow_suffix() -> str:
        """Shadow-log opps blocked by a whole-batch guard below and return a
        suffix describing how many were logged (empty if none)."""
        _n = len(_log_shadow_predictions(opps, live=live))
        return (
            f" Logged {_n} shadow prediction(s) for scoring continuity." if _n else ""
        )

    if is_trading_paused():
        print(
            yellow(
                "  [Auto] TRADING_PAUSED is set — no auto-trades placed (paper or live)."
                + _shadow_suffix()
            )
        )
        return 0
    # AUD-0005: pass client through unconditionally so the drawdown/streak
    # checks also see real live losses via execution_log, not just
    # paper_trades.json. client may be None on a pure-paper caller with
    # none provided -- is_paused_drawdown handles that. Opus-review-caught:
    # "same as is_daily_loss_halted below" (the original wording here) is a
    # misleading analogy -- that function's client is used only for PAPER
    # unrealized MTM pricing (get_unrealized_pnl_paper), not live-loss
    # awareness; is_daily_loss_halted itself remains blind to live losses
    # (mitigated, not eliminated, by _place_live_order's own separate
    # execution_log.get_today_live_loss() check).
    if is_paused_drawdown(client):
        print(
            yellow(
                "  [Auto] Drawdown guard active — no auto-trades placed."
                + _shadow_suffix()
            )
        )
        return 0
    if is_daily_loss_halted(client):
        from paper import get_daily_pnl

        daily_pnl = get_daily_pnl(client)
        print(
            yellow(
                f"  [Auto] Daily loss limit reached (${daily_pnl:.2f} incl. MTM) — no auto-trades."
                + _shadow_suffix()
            )
        )
        return 0
    _streak_paused = is_streak_paused(client)
    if _streak_paused:
        print(
            yellow("  [Auto] Loss streak detected — Kelly halved for all auto-trades.")
        )

    # AUD-0002: seed with prior-cycle live positions too, not just the paper
    # ledger -- previously MAX_CONCURRENT_POSITIONS, the per-date/same-day
    # concentration caps, and the VaR gate below were all blind to any live
    # position opened in an earlier watch/cron cycle (only F6's own
    # same-cycle append, further down, covered live orders placed THIS
    # cycle). Unconditional, not gated on `live` -- the finding is explicit
    # that this was blind "regardless of live=True/False": a PAPER cycle
    # placing trades should still see real live exposure, not just a live
    # cycle. _get_live_open_positions() is called fresh here, before any
    # live order this cycle is placed, so there's no overlap with F6's
    # later append of this cycle's own fills.
    #
    # Opus review follow-up (batch-22 item 4, MEDIUM #3): include_unfilled=
    # True -- this list feeds the dollar-denominated VaR gate
    # (portfolio_var(...) vs MAX_VAR_DOLLARS below) in addition to the
    # count/concentration caps, so it needed the same pending+unknown
    # widening as paper.get_all_open_positions()/paper._live_effective_
    # balance() for the identical reason: a resting live GTC entry or an
    # ambiguous-outcome order is real committed capital that was invisible
    # to this dollar gate until this fix.
    _open_trades_list = get_open_trades() + _get_live_open_positions(
        include_unfilled=True
    )
    open_tickers = {t["ticker"] for t in _open_trades_list}
    # Opus-review-caught (L9, deliberately not changed further): if the same
    # ticker were somehow held on BOTH ledgers with opposite sides at once,
    # the live entry (concatenated after paper) silently wins this dict,
    # which could report the wrong "existing side" in the FLIP WARNING
    # message below. Left as-is -- `ticker in open_tickers` (checked further
    # down) already unconditionally skips placement for an already-open
    # ticker regardless of which side wins here, so this can only ever
    # affect a warning MESSAGE's wording, never a trading decision. The
    # precondition itself (the same ticker open on both ledgers
    # simultaneously with opposite sides) is also an unusual state this bot
    # doesn't otherwise put itself into.
    _open_trade_sides: dict[str, str] = {
        t["ticker"]: t.get("side", "yes") for t in _open_trades_list
    }
    placed = 0

    # Per-date concentration cap: track how many open positions settle on each date.
    # Prevents correlated single-day exposure (e.g. 9 positions all expiring May 14).
    from collections import Counter as _Counter

    MAX_POSITIONS_PER_DATE = int(os.getenv("MAX_POSITIONS_PER_DATE", "4"))
    # Same-day (days_out==0) METAR trades use a higher separate cap — they settle
    # quickly and don't consume the multi-day concentration budget. Set via
    # MAX_SAME_DAY_POSITIONS env var (default 8).
    MAX_SAME_DAY_POSITIONS = int(os.getenv("MAX_SAME_DAY_POSITIONS", "8"))
    # Count open same-day positions using days_out stored at placement time.
    # Using stored days_out (not target_date == today) avoids misclassifying a
    # days_out=1 trade placed yesterday as same-day just because it settles today.
    # Trades placed before this field existed default to 1 (multi-day) so they
    # fall into the normal date-cap path rather than consuming same-day slots.
    #
    # Only count same-day trades whose market has not yet expired. A Jun9 same-day
    # trade that closed at 23:59 UTC is no longer a live risk position — it's
    # awaiting settlement bookkeeping. Counting it against today's cap blocks all
    # Jun10 slots until settlement detection runs (which happens after trading in
    # the cron cycle). Trades missing close_time are assumed still live (safe default).
    _now_utc = datetime.now(UTC)

    def _is_still_live(t: dict) -> bool:
        ct = t.get("close_time")
        if not ct:
            return True
        try:
            return datetime.fromisoformat(ct.replace("Z", "+00:00")) > _now_utc
        except (ValueError, TypeError):
            return True

    _same_day_open = sum(
        1 for t in _open_trades_list if t.get("days_out", 1) == 0 and _is_still_live(t)
    )
    # Compute reservation-adjusted cap once per scan, not inside the signal loop.
    # Calling inside the loop would fire a DB query per signal (20+ per scan).
    # Cap is stable within a scan; it only needs to update between cron cycles.
    _eff_sameday_cap = _sameday_effective_cap(MAX_SAME_DAY_POSITIONS)
    if _eff_sameday_cap < MAX_SAME_DAY_POSITIONS:
        from utils import SAME_DAY_DYNAMIC_SLOTS as _dyn

        if _dyn:
            _log.info(
                "_auto_place_trades: same-day cap reduced to %d/%d (dynamic band scaling)",
                _eff_sameday_cap,
                MAX_SAME_DAY_POSITIONS,
            )
        else:
            _log.info(
                "_auto_place_trades: same-day cap reduced to %d/%d "
                "(holding %d slots until %d:00 UTC)",
                _eff_sameday_cap,
                MAX_SAME_DAY_POSITIONS,
                MAX_SAME_DAY_POSITIONS - _eff_sameday_cap,
                int(os.getenv("SAME_DAY_RESERVE_AFTER_HOUR_UTC", "12")),
            )
    # Multi-day cap tracks all positions placed as days_out >= 1, grouped by date.
    _multiday_date_counts = _Counter(
        t.get("target_date")
        for t in _open_trades_list
        if t.get("target_date") and t.get("days_out", 1) != 0
    )

    # Concurrent-position cap: never hold more than MAX_CONCURRENT_POSITIONS at once.
    MAX_CONCURRENT_POSITIONS = int(os.getenv("MAX_CONCURRENT_POSITIONS", "20"))
    if len(_open_trades_list) >= MAX_CONCURRENT_POSITIONS:
        print(
            yellow(
                f"  [Auto] Position cap reached ({len(_open_trades_list)}/{MAX_CONCURRENT_POSITIONS} open) — no auto-trades."
                + _shadow_suffix()
            )
        )
        return 0

    daily_spent = _daily_paper_spend()
    sameday_spent = _daily_sameday_spend()
    # Only abort entirely when BOTH caps are exhausted. If only the multi-day cap
    # is full, same-day signals can still be placed (and vice versa). Per-signal
    # checks below enforce each cap independently.
    if daily_spent >= MAX_DAILY_SPEND and sameday_spent >= MAX_SAME_DAY_SPEND:
        print(
            yellow(
                f"  [Auto] All spend caps reached (multi-day ${daily_spent:.2f}/${MAX_DAILY_SPEND:.0f},"
                f" same-day ${sameday_spent:.2f}/${MAX_SAME_DAY_SPEND:.0f}) — no auto-trades."
                + _shadow_suffix()
            )
        )
        return 0

    # P7.4 — rank opportunities by edge × Kelly descending. Same-day and
    # multi-day signals draw from separate caps so they don't compete for the
    # same slots — an urgency multiplier would only displace higher-Kelly
    # signals in favour of lower-Kelly ones without improving placement rate.
    def _opp_sort_key(item: object) -> float:
        a_ = item[1] if isinstance(item, tuple) else item
        if not isinstance(a_, dict):
            return 0.0
        edge = float(
            a_.get("edge", a_.get("net_edge", a_.get("expected_value", 0))) or 0
        )
        kelly = float(
            a_.get("kelly_fraction", a_.get("ci_adjusted_kelly", a_.get("kelly", 0)))
            or 0
        )
        return edge * kelly

    opps = sorted(opps, key=_opp_sort_key, reverse=True)

    def _opp_event_key(item: object) -> tuple[str, str, str] | None:
        """Return (city, target_date_str, var) identifying which event this
        opportunity's bracket belongs to, or None if city/date can't be
        determined. var mirrors _score_ensemble_members' HIGH->max /
        LOW(T)->min ticker convention — HIGH and LOW markets settle
        independently (not mutually exclusive) and must not be grouped
        together.
        """
        m_ = item[0] if isinstance(item, tuple) else item
        a_ = item[1] if isinstance(item, tuple) else item
        if not isinstance(m_, dict) or not isinstance(a_, dict):
            return None
        city_ = m_.get("_city") or a_.get("city")
        date_obj = m_.get("_date")
        if date_obj is None:
            raw_date = a_.get("target_date")
            if isinstance(raw_date, str):
                try:
                    import datetime as _dt_ek

                    date_obj = _dt_ek.date.fromisoformat(raw_date)
                except ValueError:
                    _log.warning(
                        "_opp_event_key: unparseable target_date %r for ticker %s — "
                        "treating as None (opportunity won't be joint-bracket-grouped)",
                        raw_date,
                        m_.get("ticker", "") or a_.get("ticker", ""),
                    )
                    date_obj = None
            elif hasattr(raw_date, "isoformat"):
                date_obj = raw_date
        date_str = date_obj.isoformat() if date_obj else None
        if not city_ or not date_str:
            return None
        ticker_upper = (m_.get("ticker", "") or a_.get("ticker", "")).upper()
        var_ = _var_from_ticker_prefix(ticker_upper) or "max"
        return (city_, date_str, var_)

    # JOINT FULL-LADDER BRACKET SELECTION (backlog.txt, smallest useful
    # version): pre-partition each event's exposure room by relative edge
    # across same-cycle sibling brackets, before the greedy sort above lets
    # whichever sibling happens to sort first claim the whole room. Singleton
    # events (the common case) are unaffected (no entry -> scale 1.0).
    _event_groups: dict[tuple[str, str, str], list] = {}
    for _item in opps:
        _key = _opp_event_key(_item)
        if _key is not None:
            _event_groups.setdefault(_key, []).append(_item)

    _ticker_edge_share: dict[str, float] = {}
    for _members in _event_groups.values():
        if len(_members) < 2:
            continue
        _edges = []
        for _mem in _members:
            _mm = _mem[0] if isinstance(_mem, tuple) else _mem
            _aa = _mem[1] if isinstance(_mem, tuple) else _mem
            _edges.append(
                abs(
                    float(
                        _aa.get(
                            "edge", _aa.get("net_edge", _aa.get("expected_value", 0))
                        )
                        or 0
                    )
                )
            )
        _total_edge = sum(_edges)
        for _mem, _e in zip(_members, _edges):
            _mm = _mem[0] if isinstance(_mem, tuple) else _mem
            _aa = _mem[1] if isinstance(_mem, tuple) else _mem
            _t = _mm.get("ticker", "") or _aa.get("ticker", "")
            if _t:
                _ticker_edge_share[_t] = (
                    (_e / _total_edge) if _total_edge > 0 else (1.0 / len(_members))
                )

    _skip_reasons: list[str] = []
    # AUD-0021: accumulate every shadow-routed (ticker, family-label) pair
    # across the WHOLE per-ticker loop below instead of calling
    # _log_shadow_predictions once per ticker -- each call independently
    # re-opens a tracker connection and re-reads+re-checksums the paper
    # ledger, so 6 per-ticker call sites meant up to 6x that cost per cycle
    # for no benefit. One batched call after the loop (see below) lets
    # _log_shadow_predictions' own single-connection/single-open-positions-
    # fetch design actually apply across the whole batch, as its docstring
    # already claims.
    #
    # Opus review (round 1), reviewed and accepted: deferring every shadow-
    # routed ticker's write to ONE call after this whole loop means an
    # uncaught exception later in the loop (in a non-shadow item's real
    # placement path, which this loop does not wrap in a blanket try/
    # except) now loses the ENTIRE accumulated shadow batch, where
    # previously each ticker's shadow write had already landed on disk
    # before the loop moved on. Both existing early-exit paths (kill switch,
    # drawdown halt) already reach the batched call correctly -- verified.
    # The residual risk is scoring-data completeness (brier_score_by_method
    # staleness for the lost tickers), not order placement or money;
    # wrapping this ~800-line loop in a top-level try/finally to guarantee
    # the flush always fires was judged higher-risk (of masking an
    # unrelated bug or altering existing break/continue control flow) than
    # the data-completeness gap it would close. Left as-is.
    _shadow_batch: list = []
    _shadow_batch_labels: list[tuple[str, str]] = []

    from paths import KILL_SWITCH_PATH as _KILL_SWITCH_PATH

    # Shadow-only gate booleans are evaluated ONCE per batch here, not
    # per-ticker inside the loop below. Each gate is a pure function of env
    # config + a settled-sample DB count; nothing in this loop can change
    # either mid-batch, so the per-ticker calls this replaces were already
    # returning the same value every time for the same family within one
    # scan -- but recomputing per-ticker still meant the value COULD legally
    # diverge across two calls to this function in the same cron cycle (the
    # strong-tier and med-tier calls in trade_cycle.py) or under concurrent
    # settlement writes, which contradicts each gate's own docstring
    # guarantee ("no real order is ever placed... before this is True").
    # Hoisting makes that guarantee airtight for a single call and cuts 5
    # redundant lookups down to 5 total instead of 5-per-ticker.
    _hourly_gate_active = _hourly_gates_active()
    _rain_gate_active = _rain_gates_active()
    _snow_gate_active = _snow_gates_active()
    _hurricane_count_gate_active = _hurricane_count_gates_active()
    _hurricane_next_event_gate_active = _hurricane_next_event_gates_active()
    _storm_order_gate_active = _storm_order_gates_active()

    for item in opps:
        # Per-signal kill switch check — a mid-batch activation (user writes the file
        # while orders 1-N are executing) stops remaining signals immediately.
        if _KILL_SWITCH_PATH.exists():
            _log.warning(
                "_auto_place_trades: kill switch active — aborting %d remaining signal(s)",
                len(opps) - placed,
            )
            break
        # Support both (market, analysis) tuple format and flat opp dict format
        if isinstance(item, tuple):
            m, a = item
        else:
            m, a = item, item

        ticker = m.get("ticker", "") or a.get("ticker", "")

        # Shadow-only families are routed here, BEFORE any of the
        # placement-only checks below (validate/dedup/caps/Kelly/price/VaR).
        # _log_shadow_predictions re-applies its own validate/already-open/
        # was_ordered_recently/was_traded_today gates internally (see its
        # docstring), so correctness isn't lost by skipping this loop's
        # copies of those checks -- but running this loop's placement-only
        # checks (date caps, VaR, cycle dedup) first would wrongly suppress
        # shadow logging for a family that's simply over this cycle's
        # capacity, silently biasing the settled-sample floor these gates
        # wait on toward only tickers that would've traded anyway, and would
        # waste a live market refetch + a 5000-sim portfolio_var call on a
        # ticker that was never going to place. backlog.txt "HOURLY-
        # DIRECTIONAL TEMPERATURE MARKETS" Step 2 / "RAIN / SNOW / HURRICANE
        # MARKETS" Step 2 / Snow Step 2 / hurricane season-count (2026-08-03)
        # / hurricane time-to-next-event (2026-08-07). Per-ticker-family, not
        # per-batch: other opportunities in the same batch continue through
        # the normal placement path below.
        if (
            any(ticker.upper().startswith(p) for p in _KXTEMP_HOURLY_CITY)
            and not _hourly_gate_active
        ):
            _shadow_batch.append(item)
            _shadow_batch_labels.append((ticker, "hourly_shadow_only"))
            continue

        if (
            any(ticker.upper().startswith(p) for p in _KXRAIN_MONTHLY_CITY)
            and not _rain_gate_active
        ):
            _shadow_batch.append(item)
            _shadow_batch_labels.append((ticker, "rain_shadow_only"))
            continue

        if (
            any(ticker.upper().startswith(p) for p in _KXSNOW_MONTHLY_CITY)
            and not _snow_gate_active
        ):
            _shadow_batch.append(item)
            _shadow_batch_labels.append((ticker, "snow_shadow_only"))
            continue

        if is_hurricane_count_ticker(ticker) and not _hurricane_count_gate_active:
            _shadow_batch.append(item)
            _shadow_batch_labels.append((ticker, "hurricane_count_shadow_only"))
            continue

        if (
            is_hurricane_next_event_ticker(ticker)
            and not _hurricane_next_event_gate_active
        ):
            _shadow_batch.append(item)
            _shadow_batch_labels.append((ticker, "hurricane_next_event_shadow_only"))
            continue

        if is_storm_order_ticker(ticker) and not _storm_order_gate_active:
            _shadow_batch.append(item)
            _shadow_batch_labels.append((ticker, "storm_order_shadow_only"))
            continue

        # Merge ticker from market dict so tuple-format callers aren't penalised.
        _ok, _reject_reason = _validate_trade_opportunity(
            {**a, "ticker": ticker}, live=live, market=m
        )
        if not _ok:
            _log.debug(
                "_auto_place_trades: skip %s — %s",
                ticker or "(no ticker)",
                _reject_reason,
            )
            _skip_reasons.append(f"{ticker}: validate({_reject_reason})")
            continue

        if ticker in open_tickers:
            _new_side = a.get("recommended_side", a.get("side", "yes"))
            _existing_side = _open_trade_sides.get(ticker, "yes")
            if _new_side != _existing_side:
                _edge_pct = a.get("net_edge", a.get("edge", 0.0)) * 100
                _log.warning(
                    "[FlipWarning] %s — open %s, model now signals %s (edge=%.1f%%) — consider manual exit on Kalshi",
                    ticker,
                    _existing_side.upper(),
                    _new_side.upper(),
                    _edge_pct,
                )
                print(
                    f"\n  !! [FLIP WARNING] {ticker} — open {_existing_side.upper()},"
                    f" model now signals {_new_side.upper()}"
                    f" (edge={_edge_pct:.1f}%) — consider manual exit on Kalshi !!\n"
                )
            _skip_reasons.append(f"{ticker}: already_open")
            continue
        # Belt-and-suspenders: catch cross-run duplicates when open_tickers is stale
        # (e.g. position incorrectly marked settled between runs). Ticker encodes date
        # so a match within 7 days is always a re-entry bug, never a new opportunity.
        if execution_log.was_ordered_recently(ticker, days=7):
            _log.debug(
                "_auto_place_trades: skip %s — filled order exists in last 7 days",
                ticker,
            )
            _skip_reasons.append(f"{ticker}: ordered_recently")
            continue
        rec_side = a.get("recommended_side", a.get("side", "yes"))

        if execution_log.was_traded_today(ticker, rec_side):
            _log.debug(
                "_auto_place_trades: skip %s/%s — already traded today",
                ticker,
                rec_side,
            )
            _skip_reasons.append(f"{ticker}: traded_today")
            continue
        city = m.get("_city") or a.get(
            "city"
        )  # M-6: flat-dict opps lack underscore fields
        target_date_obj = m.get("_date")
        if target_date_obj is None:
            # M-6: flat-dict format — fall back to analysis dict
            _raw_date = a.get("target_date")
            if isinstance(_raw_date, str):
                try:
                    import datetime as _dt_m6

                    target_date_obj = _dt_m6.date.fromisoformat(_raw_date)
                except ValueError:
                    _log.warning(
                        "_auto_place_trades: unparseable target_date %r for "
                        "ticker %s — treating as None (cap/portfolio-Kelly/"
                        "correlation checks will miss this trade)",
                        _raw_date,
                        ticker,
                    )
            elif hasattr(_raw_date, "isoformat"):
                target_date_obj = _raw_date
        target_date_str = target_date_obj.isoformat() if target_date_obj else None

        # Per-date concentration cap: same-day and multi-day use separate limits.
        # backlog.txt "RAIN / SNOW / HURRICANE MARKETS" Step 2: monthly rain
        # trades now group under their close_time-derived date here, same as
        # any other multi-day market (days_out is essentially never 0 for
        # this ticker family, so this always routes to the multi-day branch,
        # not the same-day one). 9 of the 10 rain cities (all but Seattle)
        # already sit in existing _CORRELATED_CITY_GROUPS entries, so two
        # sibling brackets for the same city+month correctly count against
        # the same per-date cap and correlated-group exposure -- see
        # portfolio_kelly_fraction()'s matching comment in paper.py.
        _is_same_day = int(a.get("days_out", 1)) == 0
        if _is_same_day:
            if _same_day_open >= _eff_sameday_cap:
                _skip_reasons.append(
                    f"{ticker}: sameday_cap({_same_day_open}/{_eff_sameday_cap})"
                )
                continue
        elif (
            target_date_str
            and _multiday_date_counts[target_date_str] >= MAX_POSITIONS_PER_DATE
        ):
            _skip_reasons.append(
                f"{ticker}: date_cap({target_date_str} {_multiday_date_counts[target_date_str]}/{MAX_POSITIONS_PER_DATE})"
            )
            continue

        ci_kelly = a.get("ci_adjusted_kelly")
        if ci_kelly is None:
            ci_kelly = a.get("fee_adjusted_kelly")
        if ci_kelly is None:
            ci_kelly = 0.0
        # Redistributes room WITHIN the existing MAX_CITY_DATE_EXPOSURE cap
        # (still enforced below, unchanged) -- never raises it. Share is
        # always <=1.0, so this only ever shrinks or holds ci_kelly.
        ci_kelly *= _ticker_edge_share.get(ticker, 1.0)
        adj_kelly = portfolio_kelly_fraction(
            ci_kelly, city, target_date_str, side=rec_side, client=client
        )
        adj_kelly *= corr_kelly_scale(
            {"city": city, "target_date": target_date_str}, _open_trades_list
        )
        adj_kelly *= liquidity_kelly_scale(m)
        if adj_kelly < 0.002:
            _skip_reasons.append(f"{ticker}: kelly_too_small({adj_kelly:.4f})")
            continue
        # L1-B: Re-fetch live price before placement — the analysis price may be
        # several minutes stale by the time execution runs.  If a client is available
        # (live mode or paper+client), fetch the current orderbook and use the
        # fresh implied probability instead of the cached value.
        # Falls back to the analysis price in pure paper mode (no client).
        _stale_mkt_prob = float(a.get("market_prob", 0.50) or 0.50)
        _mkt_prob = _stale_mkt_prob
        # Initialize ask prices from the stale enriched market dict so we
        # have real bid/ask even when no live client is present.
        # YES fill = yes_ask (what you actually pay); NO fill = 1 - yes_bid (= no_ask).
        _stale_prices = parse_market_price(m)
        _fill_yes_ask: float = (
            float(_stale_prices.get("yes_ask") or 0) or _stale_mkt_prob
        )
        _fill_yes_bid: float = float(_stale_prices.get("yes_bid") or 0) or (
            1.0 - _stale_mkt_prob
        )
        if client is not None:
            try:
                _fresh_market = client.get_market(ticker)
                _fresh_prices = parse_market_price(_fresh_market)
                _fresh_implied = _fresh_prices.get("implied_prob")
                if isinstance(_fresh_implied, float) and 0.0 < _fresh_implied < 1.0:
                    if abs(_fresh_implied - _stale_mkt_prob) > 0.01:
                        _fetch_age = time.time() - (
                            a.get("data_fetched_at") or time.time()
                        )
                        _log.info(
                            "_auto_place_trades: %s price updated %.3f→%.3f "
                            "(was %.0fs stale)",
                            ticker,
                            _stale_mkt_prob,
                            _fresh_implied,
                            _fetch_age,
                        )
                    _mkt_prob = _fresh_implied
                    # Carry fresh market dict into _place_live_order so it uses
                    # the current price, not the one from the analysis batch.
                    a = {**a, "market": _fresh_market, "market_prob": _fresh_implied}
                _fya = float(_fresh_prices.get("yes_ask") or 0)
                _fyb = float(_fresh_prices.get("yes_bid") or 0)
                if _fya > 0:
                    _fill_yes_ask = _fya
                if _fyb > 0:
                    _fill_yes_bid = _fyb
            except Exception as _pf_err:
                _log.debug(
                    "_auto_place_trades: price re-fetch failed for %s: %s",
                    ticker,
                    _pf_err,
                )
        # Use market implied prob as entry price — flip for NO side
        # Skip if market_prob is near 0 or 1 (degenerate markets — no real two-sided market)
        if _mkt_prob < 0.02 or _mkt_prob > 0.98:
            _skip_reasons.append(f"{ticker}: degenerate_price({_mkt_prob:.2f})")
            continue
        # L1-B: if the fresh price shows the edge has reversed (market moved against
        # us between analysis and now), skip rather than placing a losing trade.
        _forecast_prob = float(a.get("forecast_prob", _mkt_prob) or _mkt_prob)
        _fresh_edge = (
            _forecast_prob - _mkt_prob
            if rec_side == "yes"
            else _mkt_prob - _forecast_prob
        )
        if _fresh_edge <= 0:
            _log.info(
                "_auto_place_trades: skip %s — edge gone after price refresh "
                "(forecast=%.3f market=%.3f side=%s)",
                ticker,
                _forecast_prob,
                _mkt_prob,
                rec_side,
            )
            _skip_reasons.append(
                f"{ticker}: edge_gone(fcst={_forecast_prob:.2f} mkt={_mkt_prob:.2f})"
            )
            continue
        # Fill at ask (not mid) — YES pays yes_ask, NO pays 1 - yes_bid (no_ask).
        # Using mid understates entry cost by half the spread, making paper P&L look better.
        entry_price = (1.0 - _fill_yes_bid) if rec_side == "no" else _fill_yes_ask
        # H-3: skip if entry price is impossible — happens when yes_bid=0 with no fresh data.
        # A NO trade with yes_bid=0 gives entry_price=1.0 (wrong); a YES trade with
        # yes_ask=0 gives entry_price=0.0 (wrong).  Either indicates missing market data.
        if entry_price <= 0 or entry_price >= 1.0:
            _log.warning(
                "_auto_place_trades: skip %s — no valid entry price "
                "(yes_bid=%.3f yes_ask=%.3f mkt_prob=%.3f side=%s)",
                ticker,
                _fill_yes_bid,
                _fill_yes_ask,
                _mkt_prob,
                rec_side,
            )
            _skip_reasons.append(f"{ticker}: no_valid_price")
            continue
        method = a.get("method")
        consensus_mult = 0.5 if not a.get("model_consensus", True) else 1.0
        # batch-26 item 4: spread_kelly_multiplier (a second spread/2
        # deduction from net_edge) removed -- _price_and_size already prices
        # net_ev/net_edge off the ask-side entry_price (yes_ask for YES,
        # 1-yes_bid for NO, not the mid), so the spread cost is already
        # priced in and a second deduction double-counted it. It was also
        # unit-wrong: net_edge is EV-per-dollar-of-cost (dimensionless)
        # while spread/2 is a raw price-unit quantity -- not comparable as
        # constructed. See paper.py's removed spread_kelly_multiplier for
        # the full removal rationale. Note (opus-round-2-review-caught): the
        # removed multiplier was also the only sizing input that used the
        # FRESH (re-fetched, just above) _fill_yes_bid/_fill_yes_ask rather
        # than the analysis-time book adj_kelly is derived from -- a spread
        # that widened after analysis no longer shrinks the dollar stake,
        # only the resulting contract count (via the fresh entry_price
        # below). Not a defect (the double-counting rationale above still
        # holds at analysis time), but a real, deliberate loosening of that
        # one refresh signal, not just a no-op cleanup.
        adj_kelly_final = adj_kelly * consensus_mult
        if drawdown_scaling_factor() == 0.0:
            _skip_reasons.append(f"{ticker}: drawdown_halt")
            continue
        _frac_cap = consensus_fraction_cap(a)
        qty = kelly_quantity(
            adj_kelly_final,
            entry_price,
            cap=cap,
            method=method,
            client=client,
            fraction_cap=_frac_cap,
        )
        if qty < 1:
            _skip_reasons.append(
                f"{ticker}: qty_zero(kelly={adj_kelly_final:.4f} price={entry_price:.2f})"
            )
            continue

        # Pre-trade VaR gate: skip if adding this position would push 5th-percentile
        # portfolio loss beyond MAX_VAR_DOLLARS. Runs at portfolio_var()'s real
        # default (5000 sims, not a cheaper override) since 1000 sims was
        # confirmed too noisy against this gate — see monte_carlo.py's
        # portfolio_var docstring. Benchmarked cost: ~2.5s cumulative across a
        # realistic 15-candidate cron cycle (portfolio growing 5->20 positions)
        # — negligible against this bot's multi-hour cron cadence, but real;
        # don't assume this call is free if adding more per-candidate work here.
        if MAX_VAR_DOLLARS > 0:
            try:
                from monte_carlo import portfolio_var

                candidate = {
                    "ticker": ticker,
                    "side": rec_side,
                    "entry_price": entry_price,
                    "cost": round(entry_price * qty, 2),
                    "quantity": qty,
                    "city": city,
                    "target_date": target_date_str,
                    "entry_prob": a.get("forecast_prob"),
                }
                projected_var = portfolio_var(_open_trades_list + [candidate])
                if abs(projected_var) > MAX_VAR_DOLLARS:
                    _log.warning(
                        "_auto_place_trades: skip %s — projected VaR $%.2f exceeds limit $%.2f",
                        ticker,
                        abs(projected_var),
                        MAX_VAR_DOLLARS,
                    )
                    _skip_reasons.append(
                        f"{ticker}: var_limit(${abs(projected_var):.0f}>${MAX_VAR_DOLLARS:.0f})"
                    )
                    continue
            except Exception as _var_err:
                # F5: was a bare debug-log-and-continue (fail open) — the
                # flash-crash check earlier in this same function explicitly
                # fails closed on any internal error; an operator who set
                # MAX_VAR_DOLLARS clearly wants portfolio tail-risk enforced,
                # so a computation failure should skip the trade, not
                # silently place it as if the check had passed.
                _log.warning(
                    "_auto_place_trades: VaR check failed for %s — skipping "
                    "(fail closed): %s",
                    ticker,
                    _var_err,
                )
                _skip_reasons.append(f"{ticker}: var_check_error({_var_err})")
                continue

        # Cycle-aware deduplication — skip if already ordered on this forecast cycle
        cycle = _current_forecast_cycle()
        if execution_log.was_ordered_this_cycle(ticker, rec_side, cycle):
            _skip_reasons.append(f"{ticker}: already_this_cycle")
            continue

        # Per-trade drawdown gate — re-evaluated before each individual placement.
        # The cycle-level check at the top of this function runs once; if several
        # trades collectively push the balance below the HALT floor within a single
        # cron cycle, this guard catches the breach before the next order goes out.
        # Re-import on each iteration so tests (and real placement callbacks) that
        # update paper.is_paused_drawdown mid-cycle are observed immediately.
        from paper import is_paused_drawdown as _is_paused_now

        # Opus-review-caught: client only passed when this cycle can
        # actually place a live order. The cycle-level check at the top of
        # this function already covers the live-aware branch once per
        # cycle (cheap: one API call, now further TTL-cached -- see
        # _resolve_live_balance's own docstring); re-fetching live
        # balance/loss data here on EVERY candidate would fire a
        # per-candidate portfolio-balance check even on a PURE PAPER cycle
        # (client is non-None there too, for MTM pricing) even though
        # nothing about live account state can have changed between paper
        # placements -- pure overhead with no correctness benefit, and
        # against trading_gates.py's own "cheapest checks first" ordering.
        # Only a live cycle can plausibly move live state between
        # candidates.
        # 2nd-round-opus-review-caught (L-5): scoped on `live and
        # live_config`, matching the ACTUAL live-placement branch's own
        # condition a few lines below (`if live and live_config:`) --
        # `live=True` alone with live_config=None still routes through
        # the paper branch, so gating on `live` alone would have fired
        # this live-balance check for a candidate that was never going to
        # place a real order.
        if _is_paused_now(client if (live and live_config) else None):
            _log.warning(
                "auto_place_trades: HALT — drawdown floor breached mid-cycle, "
                "stopping after %d placements",
                placed,
            )
            break

        if live and live_config:
            _live_balance = _resolve_live_balance(client)

            # CR-4: pass live balance so Kelly sizing uses the live account denominator,
            # not paper_trades.json balance (which diverges as live and paper accounts differ).
            _live_kelly_qty = kelly_quantity(
                adj_kelly_final,
                entry_price,
                cap=cap,
                method=method,
                client=client,
                balance_override=_live_balance if _live_balance > 0 else None,
                fraction_cap=_frac_cap,
            )

            # Per-iteration daily cap check for live path — the initial check at the top
            # of this function is a single read and is never updated, so multiple live
            # trades in one cycle can exceed MAX_DAILY_SPEND without this guard. F4:
            # priced off _live_kelly_qty (the quantity actually ordered below), not the
            # paper-Kelly `qty` computed earlier in the loop — those can differ, letting
            # a single trade blow through the cap undetected by the old precheck.
            _live_cost_estimate = round(entry_price * _live_kelly_qty, 2)
            if _is_same_day:
                if sameday_spent + _live_cost_estimate > MAX_SAME_DAY_SPEND:
                    _skip_reasons.append(
                        f"{ticker}: sameday_cap(${sameday_spent:.0f}/${MAX_SAME_DAY_SPEND:.0f})"
                    )
                    continue
            elif daily_spent + _live_cost_estimate > MAX_DAILY_SPEND:
                _skip_reasons.append(
                    f"{ticker}: daily_cap(${daily_spent:.0f}/${MAX_DAILY_SPEND:.0f})"
                )
                continue
            opp_placed, cost = _place_live_order(
                ticker=ticker,
                side=rec_side,
                analysis=a,
                config=live_config,
                client=client,
                cycle=cycle,
                kelly_qty=_live_kelly_qty,
            )
            if opp_placed:
                # F7: do NOT also add_live_loss(cost) here — settlement
                # (order_executor.py's settlement loop) already calls
                # add_live_loss(-pnl), and pnl for a losing order is -cost, so
                # calling both double-counted every loss and never properly
                # credited a win (cost was added here but never refunded).
                # get_today_live_loss() is a REALIZED-loss counter (matching
                # its name) — spend-based pre-commit protection within a
                # cycle is already handled by the separate, dedicated
                # MAX_DAILY_SPEND/MAX_SAME_DAY_SPEND/max_trade_dollars/
                # max_open_positions caps.
                if _is_same_day:
                    sameday_spent += cost
                else:
                    daily_spent += cost
                open_tickers.add(ticker)
                _open_trade_sides[ticker] = rec_side
                # F6: mirror the paper branch's _open_trades_list.append(trade) —
                # without this, later iterations in the SAME cycle compute VaR/
                # correlation scaling against a list blind to live orders just
                # placed, so several correlated live orders in one cycle each
                # get checked as if they were the first.
                _open_trades_list.append(
                    {
                        "ticker": ticker,
                        "side": rec_side,
                        "entry_price": entry_price,
                        "cost": cost,
                        "quantity": _live_kelly_qty,
                        "city": city,
                        "target_date": target_date_str,
                        "entry_prob": a.get("forecast_prob"),
                    }
                )
                if _is_same_day:
                    _same_day_open += 1
                elif target_date_str:
                    _multiday_date_counts[target_date_str] += 1
                placed += 1
        else:
            trade_cost = round(entry_price * qty, 2)
            if _is_same_day:
                if sameday_spent + trade_cost > MAX_SAME_DAY_SPEND:
                    print(
                        yellow(
                            f"  [Auto] Skipping {ticker}: would exceed same-day cap (${sameday_spent:.2f}/${MAX_SAME_DAY_SPEND:.0f})"
                        )
                    )
                    _skip_reasons.append(
                        f"{ticker}: sameday_cap(${sameday_spent:.0f}/${MAX_SAME_DAY_SPEND:.0f})"
                    )
                    continue
            elif daily_spent + trade_cost > MAX_DAILY_SPEND:
                print(
                    yellow(
                        f"  [Auto] Skipping {ticker}: would exceed daily cap (${daily_spent:.2f}/${MAX_DAILY_SPEND:.0f})"
                    )
                )
                _skip_reasons.append(
                    f"{ticker}: daily_cap(${daily_spent:.0f}/${MAX_DAILY_SPEND:.0f})"
                )
                continue
            # Pre-log before touching paper_trades.json so a crash between the two writes leaves a detectable record.
            log_id = execution_log.log_order(
                ticker=ticker,
                side=rec_side,
                quantity=qty,
                price=entry_price,
                order_type="market",
                status="pending",
                forecast_cycle=cycle,
                live=False,
            )
            try:
                trade = place_paper_order(
                    ticker,
                    rec_side,
                    qty,
                    entry_price,
                    entry_prob=a.get("forecast_prob"),
                    net_edge=a.get("net_edge"),
                    city=city,
                    target_date=target_date_str,
                    method=a.get("method"),
                    model_forecast_means=a.get("model_forecast_means"),
                    forecast_temp=a.get("forecast_temp"),
                    condition_threshold=a.get("condition", {}).get("threshold"),
                    ab_variant=a.get("_ab_variant"),
                    close_time=m.get(
                        "close_time"
                    ),  # needed for 24h settlement gate in stop loss checks
                    days_out=int(a.get("days_out", 1)),
                    var=a.get("condition", {}).get("var"),
                )
                print(
                    green(
                        f"  [Auto] #{trade['id']} {qty}×{ticker} {rec_side.upper()}"
                        f" @ ${entry_price:.3f}  Kelly={adj_kelly * 100:.1f}%"
                    )
                )
                open_tickers.add(ticker)
                _open_trade_sides[ticker] = rec_side
                _open_trades_list.append(trade)
                if _is_same_day:
                    _same_day_open += 1
                elif target_date_str:
                    _multiday_date_counts[target_date_str] += 1
                placed += 1
                if _is_same_day:
                    sameday_spent += trade.get("cost", 0.0)
                else:
                    daily_spent += trade.get("cost", 0.0)
                # Update pre-logged entry to "filled" so was_traded_today() blocks same-day re-entry.
                execution_log.log_order_result(
                    log_id,
                    status="filled",
                    response={"id": str(trade.get("id", ""))},
                )
                try:
                    import datetime as _dt2

                    from tracker import log_analysis_attempt as _log_attempt2

                    _td2 = trade.get("target_date")
                    if isinstance(_td2, str):
                        try:
                            _td2 = _dt2.date.fromisoformat(_td2)
                        except ValueError:
                            _td2 = None
                    _log_attempt2(
                        ticker=ticker,
                        city=city,
                        condition=str(a.get("condition", "")),
                        target_date=_td2,
                        forecast_prob=a.get("forecast_prob", 0.0),
                        market_prob=a.get("market_prob", 0.0),
                        days_out=int(a.get("days_out", 1)),
                        was_traded=True,
                    )
                except Exception as _e:
                    _log.warning(
                        "_auto_place_trades: log_analysis_attempt failed for %s: %s",
                        ticker,
                        _e,
                    )
                # Wire into predictions table so pnl-attribution sees cron trades
                try:
                    import datetime as _dt3

                    from tracker import log_prediction as _log_pred

                    _pred_date_raw = trade.get("target_date")
                    _pred_date: date | None = None
                    if isinstance(_pred_date_raw, str):
                        try:
                            _pred_date = _dt3.date.fromisoformat(_pred_date_raw)
                        except ValueError:
                            pass
                    elif hasattr(_pred_date_raw, "isoformat"):
                        _pred_date = _pred_date_raw
                    _log_pred(
                        ticker,
                        city,
                        _pred_date,
                        a,
                        **_prediction_kwargs_from_analysis(a),
                    )
                except Exception as _e2:
                    _log.warning(
                        "_auto_place_trades: log_prediction failed for %s: %s",
                        ticker,
                        _e2,
                    )
            except Exception as e:
                # Mark pre-logged entry as failed so dedup treats this as a known failure.
                execution_log.log_order_result(log_id, status="failed", error=str(e))
                # Surface placement failures visibly — a WARNING log is silent when watching console output.
                _err_msg = (
                    f"  [Auto] PAPER ORDER FAILED {ticker} {rec_side.upper()}: {e}"
                )
                print(red(_err_msg))
                _log.warning(
                    "_auto_place_trades: paper order FAILED ticker=%s side=%s: %s",
                    ticker,
                    rec_side,
                    e,
                )

            # P10.1 — micro live trade alongside paper (if ENABLE_MICRO_LIVE=true)
            try:
                from utils import (
                    ENABLE_MICRO_LIVE,
                    MICRO_LIVE_FRACTION,
                    MICRO_LIVE_MIN_DOLLARS,
                )

                if (
                    ENABLE_MICRO_LIVE
                    and client is not None
                    and not os.getenv("PYTEST_CURRENT_TEST")
                ):
                    # Safety guards — micro-live must respect the same limits as full live.
                    _micro_daily_loss = execution_log.get_today_live_loss()
                    _micro_daily_limit = _resolve_micro_live_config(live_config).get(
                        "daily_loss_limit", 0.0
                    )
                    if (
                        _micro_daily_limit > 0
                        and _micro_daily_loss >= _micro_daily_limit
                    ):
                        _log.warning(
                            "[MicroLive] daily loss limit reached — skipping %s", ticker
                        )
                    elif execution_log.was_traded_today(ticker, rec_side, live=True):
                        # H-6: filter to live=True so the paper order just logged doesn't
                        # self-block the micro-live placement (paper orders have live=0).
                        _log.warning(
                            "[MicroLive] dedup blocked %s/%s — already traded today (live)",
                            ticker,
                            rec_side,
                        )
                    elif not _micro_live_gate_ok(client):
                        _log.warning(
                            "[MicroLive] live trading gate blocked %s/%s",
                            ticker,
                            rec_side,
                        )
                    else:
                        _micro_price = entry_price
                        _micro_qty = max(1, math.floor(qty * MICRO_LIVE_FRACTION))
                        _micro_cost = _micro_price * _micro_qty
                        if _micro_cost >= MICRO_LIVE_MIN_DOLLARS:
                            _micro_mkt = a.get("market", {})
                            # Batch-22 item 2: see _place_live_order's matching comment.
                            _micro_cid = compute_client_order_id(
                                ticker, rec_side, "buy", _micro_qty, _micro_price, cycle
                            )
                            _micro_log_id = execution_log.log_order(
                                ticker=ticker,
                                side=rec_side,
                                quantity=_micro_qty,
                                price=_micro_price,
                                order_type="limit",
                                status="pending",
                                response={"client_order_id": _micro_cid},
                                forecast_cycle=cycle,
                                live=True,
                                close_time=_micro_mkt.get("close_time")
                                or _micro_mkt.get("expiration_time"),
                            )
                            _micro_placed = False
                            try:
                                _micro_resp = client.place_order(
                                    ticker=ticker,
                                    side=rec_side,
                                    action="buy",
                                    count=_micro_qty,
                                    price=_micro_price,
                                    time_in_force="good_till_canceled",
                                    cycle=cycle,
                                )
                            except OrderStatusUnknownError as _unk_exc:
                                # AUD-0007: see _place_live_order's matching handler.
                                execution_log.log_order_result(
                                    _micro_log_id,
                                    status="unknown",
                                    error=str(_unk_exc),
                                    response={
                                        "client_order_id": _unk_exc.client_order_id
                                    },
                                )
                                _log.warning(
                                    "[MicroLive] order outcome unknown for %s: %s",
                                    ticker,
                                    _unk_exc,
                                )
                            except Exception as _ml_exc:
                                execution_log.log_order_result(
                                    _micro_log_id, status="failed", error=str(_ml_exc)
                                )
                                _log.warning(
                                    "[MicroLive] order failed for %s: %s",
                                    ticker,
                                    _ml_exc,
                                )
                            else:
                                # Opus review follow-up (AUD-0007): moved out
                                # of the try above -- if this write itself
                                # raised (e.g. a locked DB) after a genuinely
                                # successful placement, the except block
                                # would have wrongly marked a REAL live order
                                # 'failed'. "pending", not "placed" — see the
                                # matching comment in _place_live_order above.
                                execution_log.log_order_result(
                                    _micro_log_id,
                                    status="pending",
                                    response=_micro_resp,
                                )
                                _micro_placed = True

                            # Adjacent-scope fix (found while researching
                            # AUD-0007): this block used to sit inside the
                            # same try/except as the place_order() call above,
                            # so if log_live_fill raised AFTER a genuinely
                            # successful placement, the except clobbered the
                            # just-recorded 'pending' status back to 'failed'
                            # -- hiding a real live position from the
                            # protective-exit scanner the exact same way
                            # AUD-0007 does. A failure here is cosmetic
                            # (slippage tracking only) and must never touch
                            # the order's own status.
                            if _micro_placed:
                                try:
                                    # F7: do NOT add_live_loss(_micro_cost) here — see
                                    # the matching comment on the main live path
                                    # above; settlement already accounts for this
                                    # order's realized pnl, and adding cost here too
                                    # double-counted every loss.
                                    # KNOWN GAP (pre-existing, not introduced by the
                                    # V2 order-endpoint migration): "avg_price" has
                                    # never been a real field on either the legacy or
                                    # V2 Order schema (real fields are
                                    # yes_price_dollars/no_price_dollars, the resting
                                    # limit price, plus taker_fill_cost_dollars/
                                    # maker_fill_cost_dollars, the total $ cost of
                                    # fills) -- this has always silently fallen
                                    # through to _micro_price for slippage-tracking
                                    # purposes. A real average fill price would need
                                    # fill-cost / fill_count_fp, split by maker vs
                                    # taker fills; not implemented here to avoid
                                    # guessing at unverified field semantics.
                                    _micro_fill = (
                                        _micro_resp.get("avg_price") or _micro_price
                                    )
                                    from tracker import log_live_fill as _log_fill

                                    _log_fill(
                                        ticker=ticker,
                                        side=rec_side,
                                        paper_price=_micro_price,
                                        fill_price=_micro_fill,
                                        quantity=_micro_qty,
                                    )
                                    _log.info(
                                        "[MicroLive] %s %s×%s @ %.3f (fill %.3f)",
                                        ticker,
                                        _micro_qty,
                                        rec_side,
                                        _micro_price,
                                        _micro_fill,
                                    )
                                except Exception as _fill_log_exc:
                                    _log.warning(
                                        "[MicroLive] slippage-tracking log_live_fill "
                                        "failed for %s (order itself is unaffected): %s",
                                        ticker,
                                        _fill_log_exc,
                                    )
            except Exception as _ml_outer_exc:
                _log.warning(
                    "[MicroLive] unexpected error for %s: %s", ticker, _ml_outer_exc
                )

    # AUD-0021: one batched _log_shadow_predictions call for every
    # shadow-routed ticker accumulated across the loop above, instead of one
    # call per ticker -- see _shadow_batch's own comment for why.
    if _shadow_batch:
        _shadow_logged = _log_shadow_predictions(_shadow_batch, live=live)
        for _st, _slabel in _shadow_batch_labels:
            _skip_reasons.append(f"{_st}: {_slabel}(logged={_st in _shadow_logged})")

    if placed == 0:
        print(dim("  [Auto] No qualifying signals this scan."))
    if _skip_reasons:
        from colors import dim as _dim

        print(_dim(f"  [Auto] Skipped {len(_skip_reasons)} signal(s):"))
        for _r in _skip_reasons:
            print(_dim(f"    • {_r}"))
    return placed
