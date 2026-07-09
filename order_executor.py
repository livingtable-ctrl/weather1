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

import execution_log
from ab_test import ABTest as _ABTest
from colors import dim, green, red, yellow
from utils import (
    MAX_DAILY_SPEND,
    MAX_SAME_DAY_SPEND,
    MAX_VAR_DOLLARS,
    MIN_EDGE,
    get_paper_min_edge,
    is_trading_paused,
)
from weather_markets import (
    analyze_trade,
    enrich_with_forecast,
    get_weather_markets,
    parse_market_price,
)

_log = logging.getLogger("main")

_MIN_EDGE_AB_TEST = _ABTest(
    name="min_edge_variants",
    variants={"low": 0.05, "medium": 0.07, "high": 0.09},
    max_trades_per_variant=50,
)

# ---------------------------------------------------------------------------
# GFS model update window
# ---------------------------------------------------------------------------

_GFS_UPDATE_HOURS_UTC = [0, 6, 12, 18]  # GFS model initialization hours
_GFS_UPDATE_LOCKOUT_MINS = int(os.getenv("GFS_LOCKOUT_MINS", "90"))


def _in_gfs_update_window(now_utc=None) -> bool:
    """Return True if we are within LOCKOUT_MINS of a GFS model initialization.

    During this window, Open-Meteo may be serving the previous model run.
    New multi-day trades should wait for the new run to propagate (~90 min).
    Same-day trades using METAR lock-in are unaffected and skip this check.
    """
    if _GFS_UPDATE_LOCKOUT_MINS <= 0:
        return False
    if now_utc is None:
        now_utc = datetime.now(UTC)
    minute_of_day = now_utc.hour * 60 + now_utc.minute
    for update_hour in _GFS_UPDATE_HOURS_UTC:
        update_minute = update_hour * 60
        if 0 <= (minute_of_day - update_minute) < _GFS_UPDATE_LOCKOUT_MINS:
            return True
    return False


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


def _coalesce_cents_or_dollars(market: dict, *keys: str) -> float:
    """Return the first present field as a 0.0-1.0 decimal, trying each key in order.

    The Kalshi API returns either legacy integer-cents fields (yes_bid, yes_ask, 0-100)
    or current dollar-string fields (yes_bid_dollars, yes_ask_dollars, "0.00"-"1.00").
    Mirrors weather_markets.parse_market_price's coalesce so callers agree on price
    regardless of which API shape a given market dict came from.
    """
    for k in keys:
        v = market.get(k)
        if v is None:
            continue
        if isinstance(v, str):
            v_f = float(v)
            return v_f / 100.0 if v_f > 1.0 else v_f
        if isinstance(v, int) and v >= 1:
            return v / 100.0
        if isinstance(v, float) and v > 1.0:
            return v / 100.0
        return float(v)
    return 0.0


def _midpoint_price(market: dict, side: str) -> float:
    """Return midpoint of current bid/ask for the given side, rounded to 2dp.

    Handles both legacy cents fields (yes_bid/yes_ask) and current dollar fields
    (yes_bid_dollars/yes_ask_dollars) — see _coalesce_cents_or_dollars.
    """
    yes_bid = _coalesce_cents_or_dollars(market, "yes_bid", "yes_bid_dollars")
    yes_ask = _coalesce_cents_or_dollars(market, "yes_ask", "yes_ask_dollars")
    if yes_ask == 0.0 and "yes_ask" not in market and "yes_ask_dollars" not in market:
        yes_ask = 1.0  # preserve prior default (100¢) when ask is genuinely absent
    if side == "yes":
        bid, ask = yes_bid, yes_ask
    else:  # "no"
        bid, ask = 1.0 - yes_ask, 1.0 - yes_bid
    if bid > ask:
        bid, ask = ask, bid  # guard against inverted spread from API
    return round((bid + ask) / 2, 2)


def _count_open_live_orders() -> int:
    """Count live orders with status 'pending' — enforces max_open_positions limit."""
    orders = execution_log.get_recent_orders(limit=500)
    return sum(1 for o in orders if o.get("live") and o.get("status") == "pending")


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


def _resolve_live_balance(client) -> float:
    """Fetch the real Kalshi balance (dollars) for live Kelly sizing.

    F4: live_config never has a "balance" key (_LIVE_CONFIG_DEFAULT doesn't
    define one), so a static config-based override was always inert — Kelly
    sizing silently fell back to the paper balance for every live trade.
    Returns 0.0 (meaning "use the paper balance") on any fetch failure,
    matching the prior fallback behavior rather than blocking placement.
    """
    try:
        bal_data = client.get_balance()
        api_balance_cents = bal_data.get("balance")
        if api_balance_cents is not None:
            return float(api_balance_cents) / 100.0
    except Exception as exc:
        _log.warning(
            "_resolve_live_balance: could not fetch live balance — "
            "falling back to paper balance for sizing: %s",
            exc,
        )
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


def _recover_pending_orders(client) -> None:
    """Reconcile 'pending' execution_log rows against the Kalshi API at startup.

    A crash in the ~50ms window between pre-logging an order and the API call
    leaves a phantom 'pending' row that permanently blacklists the ticker via
    dedup guards. This function resolves those rows on startup so the dedup
    state is accurate.
    """
    pending = [
        o
        for o in execution_log.get_recent_orders(limit=200)
        if o.get("live") and o.get("status") == "pending"
    ]
    if not pending:
        return

    _log.info(
        "[Recovery] Checking %d pending live order(s) against Kalshi API", len(pending)
    )
    for order in pending:
        row_id = order["id"]
        ticker = order.get("ticker", "?")
        try:
            response = order.get("response")
            if response:
                if isinstance(response, str):
                    response = json.loads(response)
                order_id = (
                    response.get("order", {}).get("order_id") if response else None
                )
            else:
                order_id = None

            if not order_id:
                # No order_id stored — crash may have happened before OR after the
                # API call (we can't tell). Use 'sent' so dedup blocks re-placement
                # for 7 days rather than risking a duplicate live order.
                execution_log.log_order_result(
                    row_id,
                    status="sent",
                    error="no order_id at recovery — treated as sent to prevent duplicate",
                )
                _log.warning(
                    "[Recovery] %s row %d: no order_id — marked failed", ticker, row_id
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


# Cancel GTC orders this many minutes before market close — prevents leaving
# an open order on a market that is about to expire unfilled.
_GTC_PRECLOSE_CANCEL_MINUTES = 30

# ---------------------------------------------------------------------------
# Live order lifecycle
# ---------------------------------------------------------------------------


def _finalize_cancel(client, order_id: str, row_id: int) -> None:
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
    """
    try:
        result = client.get_order(order_id)
        fill_count = _to_fill_count(result.get("fill_count_fp"))
        status = (
            _kalshi_status_to_internal(result.get("status", "canceled"), fill_count)
            or "canceled"
        )
        execution_log.log_order_result(
            row_id=row_id, status=status, fill_quantity=fill_count
        )
    except Exception as exc:
        _log.warning(
            "[LIVE] post-cancel fill check failed for order %s, recording plain "
            "canceled: %s",
            order_id,
            exc,
        )
        execution_log.log_order_result(row_id=row_id, status="canceled")


def _poll_pending_orders(client, config: dict | None = None) -> None:
    """Check fill status of all pending live orders and update execution_log.

    Also auto-cancels stale GTC orders and records settlement outcomes for
    filled orders whose markets have finalized.
    Called each iteration of cmd_watch to close the GTC order lifecycle.
    """
    from utils import KALSHI_FEE_RATE as _fee

    gtc_cancel_hours = (config or {}).get("gtc_cancel_hours", 24)
    now_utc = datetime.now(UTC)

    # ── Pending orders: GTC age check + fill status ───────────────────────────
    pending = [
        o
        for o in execution_log.get_recent_orders(limit=200)
        if o.get("live") and o.get("status") == "pending" and o.get("response")
    ]
    for order in pending:
        try:
            response = (
                json.loads(order["response"])
                if isinstance(order["response"], str)
                else order["response"]
            )
            order_id = response.get("order", {}).get("order_id") if response else None
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
                execution_log.log_order_result(
                    row_id=order["id"],
                    status=_internal_status,
                    fill_quantity=_fill_count,
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
            if outcome_yes and side == "yes":
                pnl = (
                    qty * (1 - price) * (1 - _fee)
                )  # won YES: profit = (1-cost)*(1-fee)
            elif not outcome_yes and side == "yes":
                pnl = -qty * price  # lost YES: lose cost
            elif outcome_yes and side == "no":
                pnl = -qty * price  # YES wins, NO loses: lose NO cost
            else:  # not outcome_yes, side == "no" — NO wins
                pnl = (
                    qty * (1 - price) * (1 - _fee)
                )  # won NO: profit = (1-cost)*(1-fee)
            pnl = round(pnl, 4)
            execution_log.record_live_settlement(order["id"], outcome_yes, pnl)
            execution_log.add_live_loss(-pnl)  # negative pnl = loss adds to counter
        except Exception as exc:
            _log.warning(
                "[LIVE] settlement check failed for order %s: %s", order.get("id"), exc
            )


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
    #    startup will reconcile it against the Kalshi API.
    log_id = execution_log.log_order(
        ticker=ticker,
        side=side,
        quantity=quantity,
        price=price,
        order_type="limit",
        status="pending",
        forecast_cycle=cycle,
        live=True,
        close_time=market.get("close_time") or market.get("expiration_time"),
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
        # Update the pre-logged row with the exchange response. "pending", not
        # "placed" — every downstream lifecycle consumer (fill polling, GTC
        # cancel, max_open_positions, PnL summary) filters on status="pending";
        # "placed" was invisible to all of them and never transitioned further.
        execution_log.log_order_result(
            log_id,
            status="pending",
            response=response,
        )
        return True, dollar_cost
    except Exception as exc:
        execution_log.log_order_result(
            log_id,
            status="failed",
            error=str(exc),
        )
        print(f"[LIVE] Order failed for {ticker}: {exc}")
        return False, 0.0


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

    try:
        from tracker import count_settled_sameday_predictions

        settled = count_settled_sameday_predictions()
    except Exception:
        return max_positions  # fail open — never block trades on a lookup error

    if settled < SAME_DAY_RESERVE_MIN_SAMPLES:
        return max_positions  # not enough data yet

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
    if datetime.now(UTC).hour >= SAME_DAY_RESERVE_AFTER_HOUR_UTC:
        return max_positions  # past cutoff hour, release reserved slots
    return max(0, max_positions - SAME_DAY_RESERVE_SLOTS)


# ---------------------------------------------------------------------------
# Early exit
# ---------------------------------------------------------------------------


def _check_early_exits(client=None) -> int:
    """
    Re-analyze all open paper positions. If the updated model probability has
    shifted >15 percentage points against the entry direction, close the position
    early at the current market mid-price.

    Returns the number of positions closed.
    """
    import paper as _paper
    from paper import get_open_trades

    if client is None:
        return 0  # cannot fetch live market prices without a client

    open_trades = get_open_trades()
    if not open_trades:
        return 0

    markets = get_weather_markets(client)
    markets_by_ticker = {m["ticker"]: m for m in markets}

    closed = 0
    for trade in open_trades:
        ticker = trade.get("ticker", "")
        entry_prob = trade.get("entry_prob")
        side = trade.get("side", "yes")
        if entry_prob is None:
            continue  # cannot assess shift without entry probability

        try:
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

            # Minimum hold time — skip exits for trades placed within 12 hours
            entered_at_str = trade.get("entered_at", "")
            if entered_at_str:
                try:
                    entered_dt = datetime.fromisoformat(
                        entered_at_str.replace("Z", "+00:00")
                    )
                    if entered_dt.tzinfo is None:
                        entered_dt = entered_dt.replace(tzinfo=UTC)
                    hours_held = (datetime.now(UTC) - entered_dt).total_seconds() / 3600
                    if hours_held < 12:
                        continue
                except (ValueError, TypeError):
                    pass

            # Settlement gate — same rationale as the stop-loss 24h gate in paper.py.
            # GFS intraday updates can shift forecast_prob by >25pp in the final hours
            # before settlement without the temperature outcome actually changing.
            # Let the market converge naturally rather than closing a winning position
            # on a transient model revision.
            # Hard-skip trades with no close_time — same reasoning as paper.py
            # check_stop_losses: silently bypassing the 24h gate risks closing
            # positions at settlement-convergence prices.
            close_time_str = trade.get("close_time") or trade.get("expires_at")
            if not close_time_str:
                _log.warning(
                    "[EarlyExit] skipping exit for %s — close_time missing, cannot apply 24h gate",
                    trade.get("ticker", "?"),
                )
                continue
            try:
                close_dt = datetime.fromisoformat(close_time_str.replace("Z", "+00:00"))
                hours_to_settlement = (
                    close_dt - datetime.now(UTC)
                ).total_seconds() / 3600
                if hours_to_settlement < 24:
                    continue
            except (ValueError, TypeError):
                _log.warning(
                    "[EarlyExit] skipping exit for %s — close_time unparseable: %s",
                    trade.get("ticker", "?"),
                    close_time_str,
                )
                continue

            if shift > 0.25:
                exit_price = _midpoint_price(market, side)
                # H-4: never close at zero — missing market data returns 0.0 which
                # records maximum loss even if the trade was profitable.
                if exit_price <= 0:
                    _log.debug(
                        "[EarlyExit] skip %s — could not compute exit price (market data missing)",
                        ticker,
                    )
                    continue
                result = _paper.close_paper_early(trade["id"], exit_price)
                _log.info(
                    f"[EarlyExit] #{trade['id']} {ticker} {side.upper()} closed: "
                    f"entry_prob={entry_prob:.2f} current={current_prob:.2f} "
                    f"pnl=${result['pnl']:.2f}"
                )
                closed += 1
        except Exception as exc:
            import traceback as _tb

            _log.warning(
                f"[EarlyExit] Error checking {ticker}: {exc}\n{_tb.format_exc()}"
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

    edge = opp.get("net_edge", 0.0)
    if edge <= 0:
        return False, f"edge={edge:.4f} <= 0"
    if "edge" in opp:
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
    kelly = opp.get("ci_adjusted_kelly", opp.get("fee_adjusted_kelly", 0.0))
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
                target_date_obj = None
        elif hasattr(_raw_date, "isoformat"):
            target_date_obj = _raw_date
    return ticker, city, target_date_obj, a, m


def _prediction_kwargs_from_analysis(a: dict) -> dict:
    """Build the tracker.log_prediction() keyword args shared by the real
    post-placement call and shadow logging, so both derive ens_mean/ens_var
    and the other blend metadata identically."""
    from weather_markets import EDGE_CALC_VERSION as _ECV

    _es = a.get("ensemble_stats") or {}
    _std = _es.get("std")
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
    )


def _log_shadow_predictions(opps: list, live: bool = False) -> int:
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

    Returns the number of predictions actually written (excludes opps that
    failed validation/dedup, or that log_prediction itself skipped, e.g. for
    a missing city).
    """
    from paper import get_open_trades
    from tracker import _conn as _tracker_conn
    from tracker import log_prediction as _log_pred

    try:
        open_tickers = {t["ticker"] for t in get_open_trades()}
    except Exception as _e:
        _log.warning("_log_shadow_predictions: get_open_trades failed: %s", _e)
        open_tickers = set()

    logged = 0
    with _tracker_conn() as _con:
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
                if _log_pred(
                    ticker,
                    city,
                    target_date_obj,
                    a,
                    is_shadow=True,
                    conn=_con,
                    **_prediction_kwargs_from_analysis(a),
                ):
                    logged += 1
            except Exception as _e:
                _log.warning(
                    "_log_shadow_predictions: log_prediction failed for %s: %s",
                    ticker,
                    _e,
                )
    return logged


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
        corr_kelly_scale,
        drawdown_scaling_factor,
        get_open_trades,
        is_daily_loss_halted,
        is_paused_drawdown,
        is_streak_paused,
        kelly_quantity,
        portfolio_kelly_fraction,
        spread_kelly_multiplier,
    )

    def _shadow_suffix() -> str:
        """Shadow-log opps blocked by a whole-batch guard below and return a
        suffix describing how many were logged (empty if none)."""
        _n = _log_shadow_predictions(opps, live=live)
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
    if is_paused_drawdown():
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
    _streak_paused = is_streak_paused()
    if _streak_paused:
        print(
            yellow("  [Auto] Loss streak detected — Kelly halved for all auto-trades.")
        )

    _open_trades_list = get_open_trades()
    open_tickers = {t["ticker"] for t in _open_trades_list}
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
    _skip_reasons: list[str] = []

    from paths import KILL_SWITCH_PATH as _KILL_SWITCH_PATH

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
                    pass
            elif hasattr(_raw_date, "isoformat"):
                target_date_obj = _raw_date
        target_date_str = target_date_obj.isoformat() if target_date_obj else None

        # Per-date concentration cap: same-day and multi-day use separate limits.
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

        ci_kelly = a.get("ci_adjusted_kelly", a.get("fee_adjusted_kelly", 0.0))
        adj_kelly = portfolio_kelly_fraction(
            ci_kelly, city, target_date_str, side=rec_side
        )
        adj_kelly *= corr_kelly_scale(
            {"city": city, "target_date": target_date_str}, _open_trades_list
        )
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
        _net_edge_val = float(a.get("net_edge") or a.get("edge") or 0)
        _spread_mult = spread_kelly_multiplier(
            _fill_yes_bid, _fill_yes_ask, _net_edge_val
        )
        adj_kelly_final = adj_kelly * consensus_mult * _spread_mult
        if _spread_mult < 0.95:
            _log.info(
                "_auto_place_trades: %s spread=%.3f eats %.0f%% of edge → Kelly×%.2f",
                ticker,
                _fill_yes_ask - _fill_yes_bid,
                (1 - _spread_mult) * 100,
                _spread_mult,
            )
        if drawdown_scaling_factor() == 0.0:
            _skip_reasons.append(f"{ticker}: drawdown_halt")
            continue
        qty = kelly_quantity(adj_kelly_final, entry_price, cap=cap, method=method)
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

        if _is_paused_now():
            _log.warning(
                "auto_place_trades: HALT — drawdown floor breached mid-cycle, "
                "stopping after %d placements",
                placed,
            )
            break

        # Skip multi-day trades during GFS model update window
        if int(a.get("days_out", 1)) >= 1 and _in_gfs_update_window():
            _log.info(
                "auto_place_trades: skipping %s — GFS update window active "
                "(set GFS_LOCKOUT_MINS=0 to disable)",
                a.get("ticker", ticker),
            )
            continue

        if live and live_config:
            _live_balance = _resolve_live_balance(client)

            # CR-4: pass live balance so Kelly sizing uses the live account denominator,
            # not paper_trades.json balance (which diverges as live and paper accounts differ).
            _live_kelly_qty = kelly_quantity(
                adj_kelly_final,
                entry_price,
                cap=cap,
                method=method,
                balance_override=_live_balance if _live_balance > 0 else None,
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
                    icon_forecast_mean=a.get("icon_forecast_mean"),
                    gfs_forecast_mean=a.get("gfs_forecast_mean"),
                    forecast_temp=a.get("forecast_temp"),
                    condition_threshold=a.get("condition", {}).get("threshold"),
                    ab_variant=a.get("_ab_variant"),
                    close_time=m.get(
                        "close_time"
                    ),  # needed for 24h settlement gate in stop loss checks
                    days_out=int(a.get("days_out", 1)),
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
                            _micro_log_id = execution_log.log_order(
                                ticker=ticker,
                                side=rec_side,
                                quantity=_micro_qty,
                                price=_micro_price,
                                order_type="limit",
                                status="pending",
                                forecast_cycle=cycle,
                                live=True,
                                close_time=_micro_mkt.get("close_time")
                                or _micro_mkt.get("expiration_time"),
                            )
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
                                # "pending", not "placed" — see the matching
                                # comment in _place_live_order above.
                                execution_log.log_order_result(
                                    _micro_log_id,
                                    status="pending",
                                    response=_micro_resp,
                                )
                                # F7: do NOT add_live_loss(_micro_cost) here — see the
                                # matching comment on the main live path above; settlement
                                # already accounts for this order's realized pnl, and
                                # adding cost here too double-counted every loss.
                                _micro_fill = (
                                    _micro_resp.get("order", {}).get("avg_price")
                                    or _micro_price
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
                            except Exception as _ml_exc:
                                execution_log.log_order_result(
                                    _micro_log_id, status="failed", error=str(_ml_exc)
                                )
                                _log.warning(
                                    "[MicroLive] order failed for %s: %s",
                                    ticker,
                                    _ml_exc,
                                )
            except Exception as _ml_outer_exc:
                _log.warning(
                    "[MicroLive] unexpected error for %s: %s", ticker, _ml_outer_exc
                )

    if placed == 0:
        print(dim("  [Auto] No qualifying signals this scan."))
    if _skip_reasons:
        from colors import dim as _dim

        print(_dim(f"  [Auto] Skipped {len(_skip_reasons)} signal(s):"))
        for _r in _skip_reasons:
            print(_dim(f"    • {_r}"))
    return placed
