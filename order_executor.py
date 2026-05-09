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
from utils import MAX_DAILY_SPEND, MAX_VAR_DOLLARS, MIN_EDGE, PAPER_MIN_EDGE
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


def _midpoint_price(market: dict, side: str) -> float:
    """Return midpoint of current bid/ask for the given side, rounded to 2dp.

    Kalshi bid/ask are integer cents (0-100). Returns a decimal probability (0.0-1.0).
    """
    if side == "yes":
        bid = market.get("yes_bid", 0) / 100
        ask = market.get("yes_ask", 100) / 100
    else:  # "no"
        bid = (100 - market.get("yes_ask", 100)) / 100
        ask = (100 - market.get("yes_bid", 0)) / 100
    if bid > ask:
        bid, ask = ask, bid  # guard against inverted spread from API
    return round((bid + ask) / 2, 2)


def _count_open_live_orders() -> int:
    """Count live orders with status 'pending' — enforces max_open_positions limit."""
    orders = execution_log.get_recent_orders(limit=500)
    return sum(1 for o in orders if o.get("live") and o.get("status") == "pending")


# ---------------------------------------------------------------------------
# Live order lifecycle
# ---------------------------------------------------------------------------


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
            order_id = response.get("order_id") if response else None
            if not order_id:
                continue

            # GTC age check — cancel orders older than gtc_cancel_hours
            try:
                placed_at = datetime.fromisoformat(
                    order["placed_at"].replace("Z", "+00:00")
                )
                age_hours = (now_utc - placed_at).total_seconds() / 3600
                if age_hours >= gtc_cancel_hours:
                    client.cancel_order(order_id)
                    execution_log.log_order_result(
                        row_id=order["id"], status="cancelled"
                    )
                    continue
            except Exception as exc:
                print(f"[LIVE] GTC cancel failed for order {order.get('id')}: {exc}")

            result = client.get_order(order_id)
            api_status = result.get("status", "")
            if api_status in ("filled", "canceled", "expired"):
                execution_log.log_order_result(
                    row_id=order["id"],
                    status=api_status,
                    fill_quantity=result.get("fill_quantity"),
                )
        except Exception as exc:
            print(f"[LIVE] poll order {order.get('id')} failed: {exc}")

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
            print(f"[LIVE] settlement check failed for order {order.get('id')}: {exc}")


def _place_live_order(
    ticker: str,
    side: str,
    analysis: dict,
    config: dict,
    client,
    cycle: str,
) -> tuple[bool, float]:
    """Place a live Kalshi order with hard-stop guards.

    Returns (placed, dollar_cost). Caller must add cost to the DB via add_live_loss().
    """
    # 0. Graduation + safety gate — must pass before any live order
    from trading_gates import pre_live_trade_check

    try:
        pre_live_trade_check()
    except RuntimeError as _gate_err:
        _log.warning("[LIVE] Gate blocked %s: %s", ticker, _gate_err)
        return False, 0.0

    # 1. Daily loss check
    if execution_log.get_today_live_loss() >= config["daily_loss_limit"]:
        print(
            f"[LIVE] Daily loss limit ${config['daily_loss_limit']} reached — skipping {ticker}"
        )
        return False, 0.0

    # 2. Open position check
    if _count_open_live_orders() >= config["max_open_positions"]:
        print(
            f"[LIVE] Max open positions {config['max_open_positions']} reached — skipping {ticker}"
        )
        return False, 0.0

    # 3. Size computation — Kelly quantity, capped by max_trade_dollars
    market = analysis.get("market", {})
    price = _midpoint_price(market, side)
    if price <= 0:
        return False, 0.0
    kelly_qty = int(analysis.get("kelly_quantity", 1))
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
        # Update the pre-logged row with the exchange response.
        execution_log.log_order_result(
            log_id,
            status="placed",
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
    """Sum of paper trade costs placed today (UTC date). Used for daily spend cap."""
    from paper import _load

    today = datetime.now(UTC).date().isoformat()
    data = _load()
    return sum(
        t.get("cost", 0.0)
        for t in data["trades"]
        if t.get("entered_at", "")[:10] == today
    )


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

            if shift > 0.15:
                exit_price = _midpoint_price(market, side)
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


def _validate_trade_opportunity(opp: dict, live: bool = False) -> tuple[bool, str]:
    """
    Pre-execution validation gate for auto-placed trades (P1.1+P1.2).
    Returns (ok, reason). All checks must pass before a trade is placed.
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

    # Flash crash check
    try:
        from circuit_breaker import flash_crash_cb

        yes_bid = opp.get("yes_bid") or 0
        yes_ask = opp.get("yes_ask") or 0
        mid = (yes_bid + yes_ask) / 2 if yes_ask > 0 else yes_bid
        if mid > 0:
            flash_crash_cb.check(opp["ticker"], float(mid))
        if flash_crash_cb.is_in_cooldown(opp["ticker"]):
            return False, "flash crash cooldown"
    except Exception:
        pass

    # "Between" bucket markets (B82.5 etc.) use a 1°F normal-distribution band with
    # σ=3–5.5°F → our probability is systematically 2–8% while the market prices at
    # 84–98% (market makers have METAR data on settlement day).  We lose nearly every
    # one of these trades and they are the primary driver of Brier score inflation.
    # Exclude them until METAR lock-in probability is wired into the "between" path.
    if opp.get("condition_type") == "between":
        return (
            False,
            "between-bucket markets excluded (insufficient 1°F-band precision)",
        )

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
            min_edge = PAPER_MIN_EDGE if not live else MIN_EDGE
    else:
        min_edge = PAPER_MIN_EDGE if not live else MIN_EDGE

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
        except Exception:
            pass

    if edge < min_edge:
        return False, f"edge {edge:.1%} < {min_edge:.1%} (spread={_ens_spread})"

    # Kelly check
    kelly = opp.get("ci_adjusted_kelly", opp.get("fee_adjusted_kelly", 0.0))
    if kelly < 0.002:
        return False, f"kelly={kelly:.4f} too small"

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
        get_open_trades,
        is_daily_loss_halted,
        is_paused_drawdown,
        is_streak_paused,
        kelly_quantity,
        portfolio_kelly_fraction,
    )

    if is_paused_drawdown():
        print(yellow("  [Auto] Drawdown guard active — no auto-trades placed."))
        return 0
    if is_daily_loss_halted(client):
        from paper import get_daily_pnl

        daily_pnl = get_daily_pnl(client)
        print(
            yellow(
                f"  [Auto] Daily loss limit reached (${daily_pnl:.2f} incl. MTM) — no auto-trades."
            )
        )
        return 0
    if is_streak_paused():
        print(
            yellow("  [Auto] Loss streak detected — Kelly halved for all auto-trades.")
        )

    _open_trades_list = get_open_trades()
    open_tickers = {t["ticker"] for t in _open_trades_list}
    placed = 0

    # Concurrent-position cap: never hold more than MAX_CONCURRENT_POSITIONS at once.
    MAX_CONCURRENT_POSITIONS = int(os.getenv("MAX_CONCURRENT_POSITIONS", "20"))
    if len(_open_trades_list) >= MAX_CONCURRENT_POSITIONS:
        print(
            yellow(
                f"  [Auto] Position cap reached ({len(_open_trades_list)}/{MAX_CONCURRENT_POSITIONS} open) — no auto-trades."
            )
        )
        return 0

    daily_spent = _daily_paper_spend()
    if daily_spent >= MAX_DAILY_SPEND:
        print(
            yellow(
                f"  [Auto] Daily spend cap reached (${daily_spent:.2f}/${MAX_DAILY_SPEND:.0f}) — no auto-trades."
            )
        )
        return 0

    # P7.4 — rank opportunities by composite priority before execution
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
        days_out = float(a_.get("days_out", a_.get("days_to_expiry", 3)) or 3)
        urgency = max(0.5, min(1.5, 2.0 / max(days_out, 0.5)))
        return edge * kelly * urgency

    opps = sorted(opps, key=_opp_sort_key, reverse=True)
    for item in opps:
        # Support both (market, analysis) tuple format and flat opp dict format
        if isinstance(item, tuple):
            m, a = item
        else:
            m, a = item, item

        ticker = m.get("ticker", "") or a.get("ticker", "")

        # Merge ticker from market dict so tuple-format callers aren't penalised.
        _ok, _reject_reason = _validate_trade_opportunity(
            {**a, "ticker": ticker}, live=live
        )
        if not _ok:
            _log.debug(
                "_auto_place_trades: skip %s — %s",
                ticker or "(no ticker)",
                _reject_reason,
            )
            continue

        if ticker in open_tickers:
            continue
        rec_side = a.get("recommended_side", a.get("side", "yes"))

        if execution_log.was_traded_today(ticker, rec_side):
            _log.debug(
                "_auto_place_trades: skip %s/%s — already traded today",
                ticker,
                rec_side,
            )
            continue
        city = m.get("_city")
        target_date_obj = m.get("_date")
        target_date_str = target_date_obj.isoformat() if target_date_obj else None
        ci_kelly = a.get("ci_adjusted_kelly", a.get("fee_adjusted_kelly", 0.0))
        adj_kelly = portfolio_kelly_fraction(
            ci_kelly, city, target_date_str, side=rec_side
        )
        adj_kelly *= corr_kelly_scale(
            {"city": city, "target_date": target_date_str}, _open_trades_list
        )
        if adj_kelly < 0.002:
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
            continue
        # Fill at ask (not mid) — YES pays yes_ask, NO pays 1 - yes_bid (no_ask).
        # Using mid understates entry cost by half the spread, making paper P&L look better.
        entry_price = (1.0 - _fill_yes_bid) if rec_side == "no" else _fill_yes_ask
        method = a.get("method")
        consensus_mult = 0.5 if not a.get("model_consensus", True) else 1.0
        adj_kelly_final = adj_kelly * consensus_mult
        qty = kelly_quantity(adj_kelly_final, entry_price, cap=cap, method=method)
        if qty < 1:
            continue

        # Pre-trade VaR gate: skip if adding this position would push 5th-percentile
        # portfolio loss beyond MAX_VAR_DOLLARS
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
                projected_var = portfolio_var(
                    _open_trades_list + [candidate], n_simulations=500
                )
                if abs(projected_var) > MAX_VAR_DOLLARS:
                    _log.warning(
                        "_auto_place_trades: skip %s — projected VaR $%.2f exceeds limit $%.2f",
                        ticker,
                        abs(projected_var),
                        MAX_VAR_DOLLARS,
                    )
                    continue
            except Exception as _var_err:
                _log.debug(
                    "_auto_place_trades: VaR check failed for %s: %s", ticker, _var_err
                )

        # Cycle-aware deduplication — skip if already ordered on this forecast cycle
        cycle = _current_forecast_cycle()
        if execution_log.was_ordered_this_cycle(ticker, rec_side, cycle):
            continue

        if live and live_config:
            opp_placed, cost = _place_live_order(
                ticker=ticker,
                side=rec_side,
                analysis=a,
                config=live_config,
                client=client,
                cycle=cycle,
            )
            if opp_placed:
                execution_log.add_live_loss(cost)
                open_tickers.add(ticker)
                placed += 1
        else:
            trade_cost = round(entry_price * qty, 2)
            if daily_spent + trade_cost > MAX_DAILY_SPEND:
                print(
                    yellow(
                        f"  [Auto] Skipping {ticker}: would exceed daily cap (${daily_spent:.2f}/${MAX_DAILY_SPEND:.0f})"
                    )
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
                    condition_threshold=a.get("condition", {}).get("threshold"),
                    ab_variant=a.get("_ab_variant"),
                )
                print(
                    green(
                        f"  [Auto] #{trade['id']} {qty}×{ticker} {rec_side.upper()}"
                        f" @ ${entry_price:.3f}  Kelly={adj_kelly * 100:.1f}%"
                    )
                )
                open_tickers.add(ticker)
                _open_trades_list.append(trade)
                placed += 1
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
                        days_out=int(a.get("days_out", 0)),
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
                    from weather_markets import EDGE_CALC_VERSION as _ECV2

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
                        ensemble_prob=a.get("ensemble_prob"),
                        nws_prob=a.get("nws_prob"),
                        clim_prob=a.get("clim_prob"),
                        forecast_cycle=_current_forecast_cycle(),
                        edge_calc_version=_ECV2,
                        signal_source=a.get("method"),
                        blend_sources=a.get("blend_sources"),
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
                    _micro_price = entry_price
                    _micro_qty = max(1, math.floor(qty * MICRO_LIVE_FRACTION))
                    _micro_cost = _micro_price * _micro_qty
                    if _micro_cost >= MICRO_LIVE_MIN_DOLLARS:
                        try:
                            _micro_resp = client.place_order(
                                ticker=ticker,
                                side=rec_side,
                                action="buy",
                                count=_micro_qty,
                                price=_micro_price,
                                time_in_force="good_till_canceled",
                            )
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
                            _log.warning(
                                "[MicroLive] order failed for %s: %s", ticker, _ml_exc
                            )
            except Exception:
                pass

    if placed == 0:
        print(dim("  [Auto] No qualifying signals this scan."))
    return placed
