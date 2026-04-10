#!/usr/bin/env python3
"""Kalshi Weather Prediction Markets — run with no arguments for interactive menu."""

import io
import json
import logging
import os
import sys
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

# Fix Windows console encoding for Unicode/emoji characters
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
elif sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from dotenv import load_dotenv
from tabulate import tabulate

from colors import (
    bold,
    cyan,
    dim,
    edge_color,
    green,
    liquidity_color,
    prob_color,
    red,
    signal_color,
    yellow,
)
from consistency import find_violations
from kalshi_client import KalshiClient
from notify import alert_strong_signal
from tracker import (
    brier_score,
    export_predictions_csv,
    get_calibration_by_city,
    get_calibration_by_type,
    get_calibration_trend,
    get_history,
    init_db,
    log_prediction,
    sync_outcomes,
)
from weather_markets import (
    CITY_COORDS,
    analyze_trade,
    enrich_with_forecast,
    get_weather_forecast,
    get_weather_markets,
    is_liquid,
    parse_market_price,
)

load_dotenv()

REFRESH_SECS = 300  # watch mode interval
_WATCH_STATE_PATH = Path(__file__).parent / "data" / ".watch_state.json"


def _load_watch_state() -> set:
    """Load the set of previously-seen tickers from disk (survives restarts)."""
    try:
        if _WATCH_STATE_PATH.exists():
            data = json.loads(_WATCH_STATE_PATH.read_text())
            return set(data.get("tickers", []))
    except Exception:
        pass
    return set()


def _save_watch_state(tickers: set) -> None:
    """Persist the set of seen tickers so the next run knows what's new."""
    try:
        _WATCH_STATE_PATH.parent.mkdir(exist_ok=True)
        _WATCH_STATE_PATH.write_text(json.dumps({"tickers": list(tickers)}))
    except Exception:
        pass


KALSHI_ENV = os.getenv("KALSHI_ENV", "demo")
MARKET_BASE_URL = (
    "https://kalshi.com" if KALSHI_ENV == "prod" else "https://demo.kalshi.co"
)


def _header(title: str, width: int = 50) -> None:
    """Print a styled section header."""
    bar = "─" * width
    print(f"\n{bold(f'┌{bar}┐')}")
    padded = title.center(width)
    print(bold(f"│{padded}│"))
    print(f"{bold(f'└{bar}┘')}\n")


def _kv(label: str, value: str) -> None:
    """Print a key-value pair with consistent 10-char label column."""
    print(f"  {label:<10}{value}")


def _format_expiry(close_time: str) -> str:
    """Format time remaining until market close: '2h 15m', '3d 4h', red if <2h."""
    if not close_time:
        return "—"
    try:
        dt = datetime.fromisoformat(close_time.replace("Z", "+00:00"))
        delta = dt - datetime.now(UTC)
        secs = int(delta.total_seconds())
        if secs < 0:
            return dim("closed")
        hours, rem = divmod(secs, 3600)
        mins = rem // 60
        if hours < 2:
            return red(f"{hours}h {mins}m")
        elif hours < 6:
            return yellow(f"{hours}h {mins}m")
        elif hours < 24:
            return f"{hours}h {mins}m"
        else:
            days = hours // 24
            return f"{days}d {hours % 24}h"
    except Exception:
        return "—"


# ── Startup checks ────────────────────────────────────────────────────────────


def validate_env() -> bool:
    """
    Check that required .env variables are set before doing anything.
    Prints a helpful setup message and returns False if not.
    """
    key_id = os.getenv("KALSHI_KEY_ID")
    key_path = os.getenv("KALSHI_PRIVATE_KEY_PATH")

    missing = []
    if not key_id:
        missing.append("KALSHI_KEY_ID")
    if not key_path:
        missing.append("KALSHI_PRIVATE_KEY_PATH")

    if missing:
        print(red("\n  Missing environment variables: " + ", ".join(missing)))
        print(
            dim("  Copy .env.example to .env and fill in your Kalshi API credentials.")
        )
        print(dim("  Get your keys at: kalshi.com → Account → API Keys\n"))
        return False

    if key_path and not Path(key_path).exists():
        print(red(f"\n  Private key file not found: {key_path}"))
        print(dim("  Check KALSHI_PRIVATE_KEY_PATH in your .env file.\n"))
        return False

    return True


def validate_api_key(client: KalshiClient) -> bool:
    """
    Make a lightweight authenticated request to confirm credentials work.
    Returns True if valid, prints an error and returns False if not.
    """
    try:
        client.get_balance()
        print(green("  ✓ API credentials valid\n"))
        return True
    except Exception as e:
        msg = str(e)
        if "401" in msg or "403" in msg or "Unauthorized" in msg:
            print(red("  ✗ API credentials rejected by Kalshi."))
            print(
                dim("  Check your KALSHI_KEY_ID and KALSHI_PRIVATE_KEY_PATH in .env\n")
            )
        else:
            print(yellow(f"  ⚠ Could not verify credentials: {e}"))
            print(dim("  Continuing anyway — may fail on authenticated endpoints.\n"))
        return False


def cleanup_data_dir() -> None:
    """
    Delete stale cached data files to prevent unbounded growth.
    Skips climate_*.json (1-year TTL managed by climatology.py).
    Only deletes files older than 2 days to avoid removing files still
    useful for markets that cross midnight.
    """
    import time as _time

    data_dir = Path(__file__).parent / "data"
    if not data_dir.exists():
        return
    cutoff = _time.time() - 2 * 24 * 3600  # 2 days ago
    for f in data_dir.glob("*.json"):
        if f.name.startswith("climate_") or f.name.startswith("."):
            continue
        try:
            if f.stat().st_mtime < cutoff:
                f.unlink()
        except OSError:
            pass


def auto_settle(client: KalshiClient) -> None:
    """
    Silently sync settled market outcomes in a background thread.
    Runs on every startup so calibration data stays fresh automatically.
    Prints a summary only if new outcomes were found.
    """
    import threading

    def _run():
        try:
            count = sync_outcomes(client)
            if count > 0:
                from paper import auto_settle_paper_trades

                paper_settled = auto_settle_paper_trades(client)
                msg = green(
                    f"\n  [Auto-settle] Recorded {count} new outcome(s). "
                ) + dim("Brier score updated.")
                if paper_settled:
                    msg += dim(
                        f"  {paper_settled} paper trade(s) settled automatically."
                    )
                print(msg + "\n")
        except Exception:
            pass  # never crash startup due to settle failure

    t = threading.Thread(target=_run, daemon=True)
    t.start()


def cmd_settle(client: KalshiClient) -> None:
    """
    Sync settled market outcomes from Kalshi and record them in the tracker.
    Intended for scheduled nightly execution (via schtasks) as well as manual use.
    """
    count = sync_outcomes(client)
    if count > 0:
        print(
            green(f"  [Settle] Recorded {count} new outcome(s). Brier score updated.")
        )
    else:
        print(dim("  [Settle] No new outcomes to record."))


# ── Client ────────────────────────────────────────────────────────────────────


def build_client() -> KalshiClient:
    return KalshiClient(
        key_id=os.getenv("KALSHI_KEY_ID"),
        private_key_path=os.getenv("KALSHI_PRIVATE_KEY_PATH"),
        env=os.getenv("KALSHI_ENV", "demo"),
    )


# ── Markets list ──────────────────────────────────────────────────────────────


def cmd_markets(client: KalshiClient):
    _header("Open Weather Markets")
    markets = get_weather_markets(client)
    if not markets:
        print(yellow("  No weather markets found."))
        return

    rows = []
    for m in markets:
        prices = parse_market_price(m)
        enriched = enrich_with_forecast(m)
        analysis = analyze_trade(enriched)
        edge = analysis["edge"] if analysis else 0
        sig = analysis["signal"].strip() if analysis else "—"
        ticker = m.get("ticker", "")
        rows.append(
            [
                ticker,
                (m.get("title") or "")[:45],
                prob_color(prices["implied_prob"]),
                signal_color(f"{sig} ({edge:+.0%})") if analysis else dim("—"),
                m.get("volume", 0),
                cyan(f"{MARKET_BASE_URL}/markets/{ticker}"),
            ]
        )

    print(
        tabulate(
            rows,
            headers=["Ticker", "Title", "Mkt P", "Signal", "Vol", "Link"],
            tablefmt="rounded_outline",
        )
    )
    print(
        dim("\n  Tip: py main.py analyze   — shows only the strongest opportunities.")
    )


# ── Single market ─────────────────────────────────────────────────────────────


def cmd_market(client: KalshiClient, ticker: str, verbose: bool = False):
    print(bold(f"\nFetching: {ticker}\n"))
    market = client.get_market(ticker)
    if not market:
        print(red(f"Market '{ticker}' not found."))
        return

    prices = parse_market_price(market)
    enriched = enrich_with_forecast(market)
    forecast = enriched.get("_forecast")
    analysis = analyze_trade(enriched)
    liquid = is_liquid(market)

    # ── Compact summary (always shown) ───────────────────────────────────────
    market_url = f"{MARKET_BASE_URL}/markets/{ticker}"
    _header(market.get("title", ticker)[:50])
    print(f"  {cyan(market_url)}")
    _kv("Closes:", (market.get("close_time") or "N/A")[:19].replace("T", " "))
    _kv("Liquid:", liquidity_color(liquid))

    if forecast:
        models = forecast.get("models_used", 1)
        hi_lo = forecast.get("high_range", (forecast["high_f"], forecast["high_f"]))
        high_str = bold(f"{forecast['high_f']:.1f}°F")
        range_str = dim(f"({hi_lo[0]:.0f}–{hi_lo[1]:.0f}° across {models} models)")
        _kv("Forecast:", f"{high_str} high  {range_str}")

    if analysis:
        edge = analysis["edge"]
        blended = analysis["forecast_prob"]
        kelly = analysis.get("kelly", 0)
        ci_lo = analysis.get("ci_low", blended)
        ci_hi = analysis.get("ci_high", blended)
        side = analysis["recommended_side"].upper()

        net_edge = analysis.get("net_edge", edge)
        fee_kelly = analysis.get("fee_adjusted_kelly", kelly)
        ci_kelly = analysis.get("ci_adjusted_kelly", fee_kelly)

        print()
        _kv(
            "Our P:",
            f"{bold(f'{blended * 100:.1f}%')}  {dim(f'[CI: {ci_lo * 100:.0f}%–{ci_hi * 100:.0f}%]')}",
        )
        _kv("Mkt P:", f"{prices['implied_prob'] * 100:.1f}%")
        _kv(
            "Edge:",
            f"{edge_color(edge)}  {dim('gross')}  →  {edge_color(net_edge)}  {dim('after ~7% fee')}",
        )
        if ci_kelly > 0.005:
            from paper import kelly_bet_dollars, kelly_quantity

            bet_dollars = kelly_bet_dollars(ci_kelly)
            bet_qty = kelly_quantity(ci_kelly, prices["implied_prob"])
            if fee_kelly > 0 and ci_kelly < fee_kelly * 0.85:
                penalty_pct = (fee_kelly - ci_kelly) / fee_kelly
                kelly_label = (
                    f"{bold(f'{fee_kelly * 100:.1f}%')} {dim('→')} "
                    f"{bold(f'{ci_kelly * 100:.1f}% of bankroll')}  "
                    f"{dim(f'(−{penalty_pct:.0%} CI penalty)')}"
                )
            else:
                kelly_label = f"{bold(f'{ci_kelly * 100:.1f}% of bankroll')}"
            _kv(
                "Kelly:",
                f"{kelly_label}  {green(f'→ ${bet_dollars:.2f}  (~{bet_qty} contracts)')}  {dim('fee-adjusted')}",
            )
        elif fee_kelly > 0.005:
            from paper import kelly_bet_dollars, kelly_quantity

            bet_dollars = kelly_bet_dollars(fee_kelly)
            bet_qty = kelly_quantity(fee_kelly, prices["implied_prob"])
            _kv(
                "Kelly:",
                f"{bold(f'{fee_kelly * 100:.1f}% of bankroll')}  {green(f'→ ${bet_dollars:.2f}  (~{bet_qty} contracts)')}  {dim('fee-adjusted')}",
            )
        elif kelly > 0.005:
            _kv(
                "Kelly:",
                dim(f"{kelly * 100:.1f}% of bankroll (negative after fees — skip)"),
            )
        print(f"\n  {signal_color(analysis['signal'].strip())}")
        _kv("Action:", f"BUY {bold(side)} on {ticker}")

        # Show assumed fee rate
        from utils import KALSHI_FEE_RATE as _fee

        print(
            dim(
                f"  [Fee: {_fee * 100:.0f}% of profit assumed (taker rate). Set KALSHI_FEE_RATE in .env to override]"
            )
        )

        # Show spread cost if notable
        spread_cost = analysis.get("spread_cost", 0.0)
        spread_scale = analysis.get("spread_scale", 1.0)
        if spread_cost >= 0.05 and spread_scale < 1.0:
            print(
                yellow(
                    f"  [Spread cost: {spread_cost:.1%} of mid — Kelly reduced {(1 - spread_scale):.0%}]"
                )
            )

        if not liquid:
            print(dim("  [No quotes yet — place a limit order to set your price]"))
        if analysis.get("ci_width", 0) > 0.30:
            print(
                yellow(
                    f"  [Wide CI ({analysis['ci_width']:.0%}) — high uncertainty, size down]"
                )
            )
        if analysis.get("forecast_anomalous"):
            print(
                yellow(
                    "  [Anomalous forecast — models disagree strongly, Kelly reduced 30%]"
                )
            )
        dq = analysis.get("data_quality", 1.0)
        if dq < 1.0:
            sources_missing = int((1.0 - dq) * 3)
            print(
                yellow(
                    f"  [Partial data — {sources_missing} source(s) unavailable, Kelly scaled down]"
                )
            )
        if abs(edge) < 0.05:
            print(dim("  [Edge too small — consider skipping]"))

        # Log to tracker
        try:
            log_prediction(
                ticker, enriched.get("_city"), enriched.get("_date"), analysis
            )
        except Exception:
            pass
    else:
        print(
            dim(
                "\n  [Trade analysis unavailable — no forecast or unrecognised ticker format]"
            )
        )

    # ── Verbose details ───────────────────────────────────────────────────────
    if verbose and analysis:
        es = analysis.get("ensemble_stats") or {}
        n = analysis.get("n_members", 0)
        method = analysis.get("method", "?").upper()
        hour = enriched.get("_hour")
        cond = analysis["condition"]
        ct = cond["type"]
        if ct == "above":
            cond_str = f">{cond['threshold']:.1f}°F"
        elif ct == "below":
            cond_str = f"<{cond['threshold']:.1f}°F"
        elif ct == "between":
            cond_str = f"{cond['lower']:.1f}–{cond['upper']:.1f}°F"
        elif ct == "precip_above":
            cond_str = f">{cond.get('threshold', 0):.2f} in"
        else:
            cond_str = "any precip"
        is_precip = ct in ("precip_any", "precip_above")
        time_lbl = f"at {hour:02d}:00 local" if hour is not None else "daily high/low"

        print(f"\n  {bold('─── Verbose breakdown ───')}")
        print(f"  Method:   {method}, {n} ensemble members")
        print(
            f"  Question: {'precip' if is_precip else 'temp'} {cond_str}  ({time_lbl})"
        )
        if es:
            print(
                f"  Spread:   {es['min']:.1f}–{es['max']:.1f}°F  "
                f"(mean {es['mean']:.1f}°F, σ={es['std']:.1f}°F)"
            )
            print(f"  P10–P90:  {es['p10']:.1f}°F – {es['p90']:.1f}°F")

        print(f"\n  {bold('Probability sources:')}")
        if analysis.get("obs_prob") is not None:
            obs = analysis["live_obs"]
            print(
                f"    Live obs:     {analysis['obs_prob'] * 100:.1f}%  "
                f"(current {obs['temp_f']:.1f}°F)"
            )
        if analysis.get("ensemble_prob") is not None:
            print(
                f"    Ensemble:     {analysis['ensemble_prob'] * 100:.1f}%  ({n} members)"
            )
        if analysis.get("nws_prob") is not None:
            print(f"    NWS official: {analysis['nws_prob'] * 100:.1f}%")
        if analysis.get("clim_prob") is not None:
            adj = analysis.get("index_adj", 0)
            adj_s = (
                f"  → {analysis['clim_adj_prob'] * 100:.1f}% after {adj:+.1f}°F index adj"
                if abs(adj) > 0.1
                else ""
            )
            print(f"    Climatology:  {analysis['clim_prob'] * 100:.1f}%{adj_s}")

        bs_dict = analysis.get("blend_sources", {})
        blend_s = "  +  ".join(
            f"{int(v * 100)}% {k}" for k, v in bs_dict.items() if v > 0.01
        )
        print(f"\n  Blend:    {blend_s}")

        bias = analysis.get("bias_correction", 0)
        if abs(bias) > 0.01:
            print(f"  Bias corr:{-bias:+.1%}  (from track record)")

    # ── Orderbook ─────────────────────────────────────────────────────────────
    print(f"\n  {bold('Orderbook:')}")
    try:
        ob = client.get_orderbook(ticker)
        yes_bids = ob.get("yes_dollars", ob.get("yes", []))
        no_bids = ob.get("no_dollars", ob.get("no", []))
        ob_rows = []
        for i in range(min(5, max(len(yes_bids), len(no_bids)))):
            y = yes_bids[-(i + 1)] if i < len(yes_bids) else ["—", "—"]
            n = no_bids[-(i + 1)] if i < len(no_bids) else ["—", "—"]
            ob_rows.append([green(f"${y[0]}"), y[1], red(f"${n[0]}"), n[1]])
        if ob_rows:
            print(
                tabulate(
                    ob_rows,
                    headers=["YES price", "YES qty", "NO price", "NO qty"],
                    tablefmt="rounded_outline",
                )
            )
        else:
            print(dim("  No orders in book."))
    except Exception as e:
        print(dim(f"  Could not load orderbook: {e}"))


# ── Analyze ───────────────────────────────────────────────────────────────────


def _analyze_once(
    client: KalshiClient,
    previous_tickers: set | None = None,
    _liquid_opps_out: list | None = None,
    min_edge: float = 0.10,
    show_summary: bool = False,
):
    """Run one analysis pass. Returns set of opportunity tickers found."""
    markets = get_weather_markets(client)
    liquid_opps: list = []
    no_quote_opps: list = []
    total = len(markets)

    for i, m in enumerate(markets, 1):
        if total > 5:
            print(f"\r  Scanning [{i}/{total}]...", end="", flush=True)
        enriched = enrich_with_forecast(m)
        analysis = analyze_trade(enriched)
        if not analysis or abs(analysis["edge"]) < min_edge:
            continue
        liquid = is_liquid(m)
        (liquid_opps if liquid else no_quote_opps).append((enriched, analysis))
        # Fire desktop alert for new strong liquid opportunities
        if (
            liquid
            and "STRONG" in analysis.get("net_signal", "")
            and previous_tickers is not None
            and m.get("ticker") not in previous_tickers
        ):
            alert_strong_signal(
                ticker=m.get("ticker", ""),
                city=enriched.get("_city", ""),
                side=analysis["recommended_side"],
                net_edge=analysis.get("net_edge", analysis["edge"]),
                kelly=analysis.get("fee_adjusted_kelly", analysis.get("kelly", 0)),
            )

    if total > 5:
        print(f"\r  Scanned {total} markets.          ")  # clear progress line

    def _rating(net_edge: float, risk: str) -> str:
        """★★★ = strong edge + low risk, ★★ = good edge, ★ = fair edge."""
        ae = abs(net_edge)
        if ae >= 0.20 and risk != "HIGH":
            return green("★★★")
        elif ae >= 0.12:
            return yellow("★★ ")
        else:
            return dim("★  ")

    def make_rows(opps):
        rows = []
        urls = []
        # Sort best opportunity (highest net edge) first
        for m, a in sorted(
            opps, key=lambda x: abs(x[1].get("net_edge", x[1]["edge"])), reverse=True
        ):
            is_new = (
                previous_tickers is not None and m.get("ticker") not in previous_tickers
            )
            ticker = m.get("ticker", "")
            net_edge = a.get("net_edge", a["edge"])
            risk = a.get("time_risk", "—")
            title = (m.get("title") or ticker)[:38]
            url = f"{MARKET_BASE_URL}/markets/{ticker}"
            urls.append((ticker, url))
            ticker_str = green(f"* {ticker}") if is_new else ticker
            our_pct = f"{a['forecast_prob'] * 100:.0f}%"
            mkt_pct = f"{a['market_prob'] * 100:.0f}%"
            edge_pct = (
                green(f"+{net_edge * 100:.0f}%")
                if net_edge > 0
                else red(f"{net_edge * 100:.0f}%")
            )
            buy_side = bold(a["recommended_side"].upper())
            rows.append(
                [
                    _rating(net_edge, risk),
                    ticker_str,
                    title,
                    m.get("_city", ""),
                    m.get("_date").isoformat() if m.get("_date") else "",
                    prob_color(a["forecast_prob"]) + f" {our_pct}",
                    f"{mkt_pct}",
                    edge_pct,
                    risk,
                    _format_expiry(m.get("close_time", "")),
                    buy_side,
                ]
            )
        return rows, urls

    hdrs = [
        "Rating",
        "ID",
        "Bet Question",
        "City",
        "Date",
        "We Think",
        "Mkt Says",
        "Your Edge",
        "Risk",
        "Closes In",
        "Buy",
    ]

    if liquid_opps:
        rows, urls = make_rows(liquid_opps)
        print(
            bold(f"\n── Best Opportunities — Ready to Trade ({len(liquid_opps)}) ──\n")
        )
        print(tabulate(rows, headers=hdrs, tablefmt="rounded_outline"))
        if urls:
            print(dim("\n  Market links:"))
            for ticker, url in urls:
                print(f"    {ticker:<32} {cyan(url)}")
    else:
        print(dim("  No tradeable opportunities right now (none with live quotes)."))

    if no_quote_opps:
        rows, urls = make_rows(no_quote_opps)
        print(
            bold(
                f"\n── More Opportunities — No Price Set Yet ({len(no_quote_opps)}) ──\n"
            )
        )
        print(tabulate(rows, headers=hdrs, tablefmt="rounded_outline"))
        print(
            dim(
                "  These markets have no buyers/sellers yet."
                " You can still place a limit order to set your own price."
            )
        )
        if urls:
            print(dim("\n  Market links:"))
            for ticker, url in urls:
                print(f"    {ticker:<32} {cyan(url)}")

    if not liquid_opps and not no_quote_opps:
        print(yellow(f"  No opportunities right now (need >{min_edge:.0%} edge)."))

    # ── Portfolio correlation warning ────────────────────────────────────────
    all_opps = liquid_opps + no_quote_opps
    from collections import Counter

    city_date_counts: Counter = Counter()
    for m, _ in all_opps:
        key = (m.get("_city", ""), str(m.get("_date", "")))
        city_date_counts[key] += 1
    for (city, dt), cnt in city_date_counts.items():
        if cnt >= 2:
            msg = f"⚠  Correlation: {cnt} opportunities for {city} on {dt}"
            detail = (
                "Size down or pick the highest-edge one — these bets move together."
            )
            inner = max(len(msg), len(detail))
            bar = "─" * (inner + 2)
            print(yellow(f"\n  ┌{bar}┐"))
            print(yellow(f"  │ {msg:<{inner}} │"))
            print(yellow(f"  │ {detail:<{inner}} │"))
            print(yellow(f"  └{bar}┘"))

    if show_summary:
        n_total = len(liquid_opps) + len(no_quote_opps)
        n_scanned = len(markets)
        if all_opps:
            best_m, best_a = max(all_opps, key=lambda x: abs(x[1]["edge"]))
            best_edge = best_a["edge"]
            best_ticker = best_m.get("ticker", "")
            opp_word = "opp" if n_total == 1 else "opps"
            print(
                dim(
                    f"\n  {n_scanned} markets scanned · {n_total} {opp_word}"
                    f" ({len(liquid_opps)} liquid)"
                    f" · best edge {best_edge:+.1%} {best_ticker}"
                )
            )
        else:
            print(
                dim(
                    f"\n  {n_scanned} markets scanned"
                    f" · no opportunities above {min_edge:.0%} threshold"
                )
            )

    found = {m.get("ticker") for m, _ in all_opps}
    # Expose liquid_opps to callers (e.g., auto-trade watch mode)
    if _liquid_opps_out is not None:
        _liquid_opps_out.extend(liquid_opps)
    return found


def _resolve_price(client: KalshiClient, ticker: str, side: str) -> float | None:
    """
    Fetch the best available price for a ticker+side.
    Returns None if no live quote exists — caller should prompt the user.
    """
    try:
        market = client.get_market(ticker)
        prices = parse_market_price(market)
        p = prices["yes_ask"] if side == "yes" else prices["no_bid"]
        if p and p > 0:
            return p
        # Fall back to mid-price when no ask/bid is present
        mid = prices["implied_prob"]
        if mid and mid > 0:
            return mid if side == "yes" else 1 - mid
    except Exception:
        pass
    return None


def _prompt_price() -> float | None:
    """Prompt for a price; loops on empty/invalid input, 'q' to cancel."""
    while True:
        raw = input(dim("  No live quote — enter price 0–1 (q to cancel): ")).strip()
        if raw.lower() == "q":
            return None
        if not raw:
            continue
        try:
            p = float(raw)
            if 0 < p < 1:
                return p
            print(red("  Price must be strictly between 0 and 1."))
        except ValueError:
            print(red("  Enter a decimal like 0.45"))


def _quick_paper_buy(client: KalshiClient) -> None:
    """Prompt to paper-buy a ticker directly after seeing analyze output."""
    try:
        while True:
            raw = input(dim("\n  Quick paper buy — ticker (q to skip): ")).strip()
            if raw.lower() == "q":
                return
            if raw:
                ticker = raw.upper()
                break
        while True:
            side = (
                input(dim(f"  Side for {ticker} (yes/no, q to cancel): "))
                .strip()
                .lower()
            )
            if side == "q":
                return
            if side in ("yes", "no"):
                break
        price = _resolve_price(client, ticker, side)
        if price is None:
            price = _prompt_price()
        if price is None:
            return
        raw_qty = input(dim("  Qty (Enter for Kelly auto-size): ")).strip()
        qty_arg = [raw_qty] if raw_qty.isdigit() and int(raw_qty) > 0 else []
        cmd_paper(["buy", ticker, side, f"{price:.3f}"] + qty_arg, client)
    except (KeyboardInterrupt, EOFError):
        print()


def cmd_analyze(client: KalshiClient, min_edge: float = 0.10):
    _header("Trade Opportunity Scanner")
    if min_edge != 0.10:
        print(dim(f"  Edge threshold: {min_edge:.0%}  (default 10%)\n"))
    else:
        print(dim("  Scanning weather markets... (cached after first run)\n"))
    _analyze_once(client, min_edge=min_edge)
    print(bold("\n  How to read this table:"))
    print(dim("  Rating     ★★★ = strong edge, low risk  ★★ = good  ★ = fair"))
    print(dim("  We Think   what our weather models predict the probability is"))
    print(
        dim(
            "  Mkt Says   what you'd pay to buy YES (e.g. 42% = pay $0.42 to win $1.00)"
        )
    )
    print(
        dim(
            "  Your Edge  how much better our odds are vs the market, after Kalshi's ~7% fee"
        )
    )
    print(
        dim("  Risk       LOW = confident data  HIGH = market closes soon or thin data")
    )
    print(dim("  Buy        YES = bet it happens  NO = bet it doesn't happen"))
    print(dim("  ID         enter this when asked for a ticker to place a paper trade"))
    _quick_paper_buy(client)


# ── Watch mode ────────────────────────────────────────────────────────────────


def _auto_place_trades(opps: list, client: KalshiClient) -> None:
    """
    Auto-place paper trades for STRONG BUY + LOW risk signals not already held.
    Called from watch --auto mode. Respects drawdown guard and portfolio Kelly.
    """
    from paper import (
        get_open_trades,
        is_paused_drawdown,
        kelly_quantity,
        place_paper_order,
        portfolio_kelly_fraction,
    )

    if is_paused_drawdown():
        print(yellow("  [Auto] Drawdown guard active — no auto-trades placed."))
        return

    open_tickers = {t["ticker"] for t in get_open_trades()}
    placed = 0
    for m, a in opps:
        ticker = m.get("ticker", "")
        if ticker in open_tickers:
            continue
        if "STRONG" not in a.get("net_signal", ""):
            continue
        if a.get("time_risk") == "HIGH":
            continue
        rec_side = a.get("recommended_side", "yes")
        city = m.get("_city")
        target_date_obj = m.get("_date")
        target_date_str = target_date_obj.isoformat() if target_date_obj else None
        ci_kelly = a.get("ci_adjusted_kelly", a.get("fee_adjusted_kelly", 0.0))
        adj_kelly = portfolio_kelly_fraction(
            ci_kelly, city, target_date_str, side=rec_side
        )
        if adj_kelly < 0.005:
            continue
        # Use market implied prob as entry price when no live quote
        prices = a.get("market_prob", 0.50)
        entry_price = float(prices) if isinstance(prices, int | float) else 0.50
        qty = kelly_quantity(adj_kelly, entry_price)
        if qty < 1:
            continue
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
            )
            print(
                green(
                    f"  [Auto] #{trade['id']} {qty}×{ticker} {rec_side.upper()}"
                    f" @ ${entry_price:.3f}  Kelly={adj_kelly * 100:.1f}%"
                )
            )
            open_tickers.add(ticker)
            placed += 1
        except ValueError as e:
            print(yellow(f"  [Auto] Skipped {ticker}: {e}"))
    if placed == 0:
        print(dim("  [Auto] No qualifying signals this scan."))


def cmd_watch(client: KalshiClient, auto_trade: bool = False, min_edge: float = 0.10):
    mode = "AUTO-TRADE" if auto_trade else "Watch"
    print(bold(f"{mode} mode — refreshing every 5 minutes. Press Ctrl+C to stop.\n"))
    if auto_trade:
        print(
            yellow(
                "  Auto-trade: STRONG BUY + LOW risk signals → paper orders placed automatically.\n"
            )
        )
    previous: set = _load_watch_state()
    try:
        while True:
            os.system("cls" if sys.platform == "win32" else "clear")
            now = time.strftime("%H:%M:%S")
            print(bold(f"Kalshi Weather Markets — {now}"))
            print(dim("─" * 52))
            print(dim("* = new since last scan   Ctrl+C to exit\n"))
            liquid_opps: list = []
            previous = _analyze_once(
                client,
                previous,
                _liquid_opps_out=liquid_opps,
                min_edge=min_edge,
                show_summary=True,
            )
            _save_watch_state(previous)
            if auto_trade and liquid_opps:
                _auto_place_trades(liquid_opps, client)
            # Check open paper positions for exit signals
            try:
                from paper import check_expiring_trades, check_model_exits

                exit_recs = check_model_exits(client)
                for rec in exit_recs:
                    t = rec["trade"]
                    reason = (
                        "MODEL FLIPPED"
                        if rec["reason"] == "model_flipped"
                        else "EDGE GONE"
                    )
                    print(
                        yellow(
                            f"  [Exit signal] #{t['id']} {t['ticker']} "
                            f"{t['side'].upper()} — {reason} "
                            f"(edge now {rec['current_edge']:+.1%})"
                        )
                    )
                for exp in check_expiring_trades():
                    t = exp["trade"]
                    hrs = exp["hours_left"]
                    label = (
                        red(f"{hrs}h left") if exp["urgent"] else yellow(f"{hrs}h left")
                    )
                    print(
                        f"  [Expiring] #{t['id']} {t['ticker']} "
                        f"{t['side'].upper()} — {label}"
                    )
            except Exception:
                pass
            opp_count = len(previous)
            opp_word = "opportunity" if opp_count == 1 else "opportunities"
            print(
                dim(
                    f"\nLast scan: {time.strftime('%H:%M:%S')} · {opp_count} {opp_word} found"
                )
            )
            print(
                dim(
                    f"Next refresh in {REFRESH_SECS // 60} min — {time.strftime('%H:%M:%S', time.localtime(time.time() + REFRESH_SECS))}"
                )
            )
            time.sleep(REFRESH_SECS)
    except KeyboardInterrupt:
        print(f"\n{dim('Watch mode stopped.')}")


# ── Forecast ──────────────────────────────────────────────────────────────────


def cmd_forecast(city: str):
    if city not in CITY_COORDS:
        print(
            red(f"Unknown city '{city}'.  Available: {', '.join(CITY_COORDS.keys())}")
        )
        return
    print(bold(f"\n7-day forecast for {city}:\n"))
    rows, today = [], date.today()
    for i in range(7):
        d = today + timedelta(days=i)
        f = get_weather_forecast(city, d)
        if f:
            models = f.get("models_used", 1)
            hi_r = f.get("high_range", (f["high_f"], f["high_f"]))
            rows.append(
                [
                    bold(f["date"]) if i == 0 else f["date"],
                    bold(f"{f['high_f']:.1f}°F"),
                    f"{f['low_f']:.1f}°F",
                    f"{f['precip_in']:.2f} in",
                    dim(f"{hi_r[0]:.0f}–{hi_r[1]:.0f}°  ({models} models)"),
                ]
            )
    print(
        tabulate(
            rows,
            headers=["Date", "High", "Low", "Precip", "Model range"],
            tablefmt="rounded_outline",
        )
    )


# ── Consistency ───────────────────────────────────────────────────────────────


def cmd_consistency(client: KalshiClient):
    _header("Arbitrage Scanner")
    print(dim("  Scanning for consistency violations across related markets...\n"))
    markets = get_weather_markets(client)
    violations = find_violations(markets)
    if not violations:
        print(green("No violations — all prices are internally consistent."))
        return
    print(yellow(f"Found {len(violations)} arbitrage opportunity/ies:\n"))
    rows = []
    for v in violations:
        rows.append(
            [
                green(v.buy_ticker),
                f"{v.buy_prob * 100:.1f}%",
                red(v.sell_ticker),
                f"{v.sell_prob * 100:.1f}%",
                bold(f"{v.guaranteed_edge * 100:.1f}%"),
            ]
        )
    print(
        tabulate(
            rows,
            headers=["BUY this", "Price", "SELL this", "Price", "Free edge"],
            tablefmt="rounded_outline",
        )
    )
    print(
        dim(
            "\nBuy the cheaper contract and sell the pricier one — profit is guaranteed."
        )
    )


# ── History ───────────────────────────────────────────────────────────────────


def cmd_history(client: KalshiClient):
    settled = sync_outcomes(client)
    if settled:
        print(green(f"  Synced {settled} new settled outcome(s).\n"))

    rows_data = get_history(50)
    if not rows_data:
        print(
            yellow(
                "No history yet. Run 'analyze' or look up a market to start logging."
            )
        )
        return

    rows = []
    for r in rows_data:
        outcome = (
            "YES"
            if r["settled_yes"] == 1
            else "NO"
            if r["settled_yes"] == 0
            else dim("pending")
        )
        correct = ""
        if r["settled_yes"] is not None and r["our_prob"] is not None:
            correct = (
                green("✓")
                if (r["our_prob"] > 0.5) == bool(r["settled_yes"])
                else red("✗")
            )
        rows.append(
            [
                r["ticker"][:38],
                (r["predicted_at"] or "")[:10],
                prob_color(r["our_prob"]) if r["our_prob"] is not None else "—",
                f"{r['market_prob'] * 100:.0f}%"
                if r["market_prob"] is not None
                else "—",
                edge_color(r["edge"]) if r["edge"] is not None else "—",
                outcome,
                correct,
            ]
        )

    print(
        tabulate(
            rows,
            headers=["Ticker", "Date", "Our P", "Mkt P", "Edge", "Outcome", "✓"],
            tablefmt="rounded_outline",
        )
    )
    limit = 50
    if len(rows_data) == limit:
        print(dim(f"  Showing most recent {limit} predictions."))
    else:
        print(dim(f"  {len(rows_data)} prediction(s) total."))

    bs = brier_score()
    if bs is not None:
        grade = (
            green("Excellent")
            if bs < 0.10
            else green("Good")
            if bs < 0.18
            else yellow("Fair")
            if bs < 0.25
            else red("Poor")
        )
        print(
            f"\n  Brier score: {bold(f'{bs:.4f}')}  {grade}  "
            f"{dim('(0.00=perfect, 0.25=random)')}"
        )

        # ── Weekly calibration trend ─────────────────────────────────────────
        trend = get_calibration_trend(weeks=8)
        if len(trend) >= 2:
            print(bold("\n  Weekly Brier trend (lower = improving):"))
            for t in trend:
                bar_len = int(t["brier"] * 40)
                bar = "█" * bar_len
                color = (
                    green if t["brier"] < 0.18 else yellow if t["brier"] < 0.25 else red
                )
                print(f"    {t['week']}  {color(bar)}  {t['brier']:.4f}  (n={t['n']})")

        # ── Per-city calibration ─────────────────────────────────────────────
        city_cal = get_calibration_by_city()
        if city_cal:
            print(bold("\n  Calibration by city:"))
            city_rows = []
            for city, stats in sorted(city_cal.items()):
                bias_str = (
                    red(f"+{stats['bias']:.3f} (over)")
                    if stats["bias"] > 0.03
                    else green(f"{stats['bias']:+.3f} (under)")
                    if stats["bias"] < -0.03
                    else dim(f"{stats['bias']:+.3f}")
                )
                city_rows.append([city, f"{stats['brier']:.4f}", bias_str, stats["n"]])
            print(
                tabulate(
                    city_rows,
                    headers=["City", "Brier", "Bias", "N"],
                    tablefmt="rounded_outline",
                )
            )
        # ── Per-type calibration ─────────────────────────────────────────────
        type_cal = get_calibration_by_type()
        if type_cal:
            print(bold("\n  Calibration by market type:"))
            type_rows = []
            for ctype, stats in sorted(type_cal.items()):
                bias_str = (
                    red(f"+{stats['bias']:.3f}")
                    if stats["bias"] > 0.03
                    else green(f"{stats['bias']:+.3f}")
                    if stats["bias"] < -0.03
                    else dim(f"{stats['bias']:+.3f}")
                )
                type_rows.append([ctype, f"{stats['brier']:.4f}", bias_str, stats["n"]])
            print(
                tabulate(
                    type_rows,
                    headers=["Type", "Brier", "Bias", "N"],
                    tablefmt="rounded_outline",
                )
            )
    else:
        print(dim("\n  Brier score will appear once markets settle."))

    # ── Source reliability ────────────────────────────────────────────────────
    from tracker import get_source_reliability

    rel = get_source_reliability()
    if rel:
        print(bold("\n  Forecast source reliability (last 30 days):"))
        rel_rows = []
        for city_name in sorted(rel.keys()):
            for src in ["ensemble", "nws", "climatology"]:
                stats = rel[city_name].get(src)
                if stats and stats["total"] >= 3:
                    rate = stats["rate"]
                    rate_str = (
                        green(f"{rate:.0%}")
                        if rate >= 0.80
                        else yellow(f"{rate:.0%}")
                        if rate >= 0.50
                        else red(f"{rate:.0%}")
                    )
                    rel_rows.append([city_name, src, rate_str, stats["total"]])
        if rel_rows:
            print(
                tabulate(
                    rel_rows,
                    headers=["City", "Source", "Success Rate", "Days"],
                    tablefmt="rounded_outline",
                )
            )


# ── Dashboard ────────────────────────────────────────────────────────────────


def cmd_dashboard(client: KalshiClient) -> None:  # noqa: ARG001
    """Single-screen portfolio health view: balance, positions, calibration."""
    from paper import (
        get_all_trades,
        get_balance,
        get_max_drawdown_pct,
        get_open_trades,
        get_peak_balance,
        get_performance,
    )

    _header("Portfolio Dashboard")

    # ── Account health ────────────────────────────────────────────────────────
    bal = get_balance()
    peak = get_peak_balance()
    dd = get_max_drawdown_pct()
    dd_str = (
        red(f"{dd:.1%}")
        if dd > 0.15
        else yellow(f"{dd:.1%}")
        if dd > 0.05
        else green(f"{dd:.1%}")
    )
    print(
        f"  Balance: {bold(f'${bal:.2f}')}  |  Peak: ${peak:.2f}  |  Drawdown from peak: {dd_str}"
    )

    from paper import drawdown_scaling_factor

    scale = drawdown_scaling_factor()
    if scale < 1.0:
        if scale == 0.0:
            sizing_str = red("PAUSED  (>50% drawdown from peak)")
        else:
            sizing_str = yellow(f"{scale:.0%} of normal  (recovering from drawdown)")
        print(f"  Sizing:  {sizing_str}")

    perf = get_performance()
    if perf["settled"]:
        wr = perf.get("win_rate")
        pnl = perf.get("total_pnl", 0.0)
        roi = perf.get("roi")
        wr_str = f"{wr:.1%}" if wr is not None else "—"
        pnl_str = green(f"+${pnl:.2f}") if pnl >= 0 else red(f"-${abs(pnl):.2f}")
        roi_str = f"{roi:+.1%}" if roi is not None else "—"
        print(
            f"  Settled: {perf['settled']}  |  Win rate: {wr_str}  |  P&L: {pnl_str}  |  ROI: {roi_str}"
        )

    # ── Calibration ──────────────────────────────────────────────────────────
    bs = brier_score()
    if bs is not None:
        grade = (
            green("Excellent")
            if bs < 0.10
            else green("Good")
            if bs < 0.18
            else yellow("Fair")
            if bs < 0.25
            else red("Poor")
        )
        print(f"  Brier score: {bold(f'{bs:.4f}')}  {grade}")

    # ── Open positions ────────────────────────────────────────────────────────
    open_trades = get_open_trades()
    print(bold("\n  ── Open Positions ──\n"))
    if open_trades:
        pos_rows = []
        exposure_by_city: dict[str, float] = {}
        for t in open_trades:
            pos_rows.append(
                [
                    t["id"],
                    t["ticker"][:30],
                    bold(t["side"].upper()),
                    t["quantity"],
                    f"${t['entry_price']:.3f}",
                    f"${t['cost']:.2f}",
                    t.get("city", "—"),
                    t.get("target_date", "—"),
                ]
            )
            city_key = f"{t.get('city', '?')}/{t.get('target_date', '?')}"
            exposure_by_city[city_key] = exposure_by_city.get(city_key, 0.0) + t["cost"]
        print(
            tabulate(
                pos_rows,
                headers=["#", "Ticker", "Side", "Qty", "Price", "Cost", "City", "Date"],
                tablefmt="rounded_outline",
            )
        )
        print(bold("\n  Exposure by city/date:"))
        for k, amt in sorted(exposure_by_city.items(), key=lambda x: -x[1]):
            pct = amt / bal * 100 if bal > 0 else 0
            bar = "█" * min(20, int(pct / 2))
            print(f"    {k:<30} ${amt:.2f}  ({pct:.1f}%)  {cyan(bar)}")
    else:
        print(dim("  No open positions."))

    # ── Expiry warnings ───────────────────────────────────────────────────────
    try:
        from paper import check_expiring_trades

        expiring = check_expiring_trades()
        if expiring:
            print(bold("\n  ── Expiring Soon ──\n"))
            for exp in expiring:
                t = exp["trade"]
                hrs = exp["hours_left"]
                label = red(f"{hrs}h left") if exp["urgent"] else yellow(f"{hrs}h left")
                print(f"  #{t['id']} {t['ticker']} {t['side'].upper()} — {label}")
            print()
    except Exception:
        pass

    # ── All trades summary ────────────────────────────────────────────────────
    all_t = get_all_trades()
    print(bold("\n  ── Recent Settled Trades ──\n"))
    settled = [t for t in all_t if t["settled"]][-5:]
    if settled:
        s_rows = []
        for t in settled:
            pnl = t.get("pnl", 0.0) or 0.0
            pnl_s = green(f"+${pnl:.2f}") if pnl >= 0 else red(f"-${abs(pnl):.2f}")
            s_rows.append(
                [
                    t["id"],
                    t["ticker"][:28],
                    t["side"].upper(),
                    t["outcome"].upper() if t["outcome"] else "—",
                    pnl_s,
                ]
            )
        print(
            tabulate(
                s_rows,
                headers=["#", "Ticker", "Side", "Result", "P&L"],
                tablefmt="rounded_outline",
            )
        )
    else:
        print(dim("  No settled trades yet."))

    print()


# ── CSV Export ────────────────────────────────────────────────────────────────


def cmd_export() -> None:
    """Export prediction history and paper trades to CSV in data/exports/."""
    from paper import export_trades_csv

    out_dir = Path(__file__).parent / "data" / "exports"
    out_dir.mkdir(parents=True, exist_ok=True)

    pred_path = str(out_dir / "predictions.csv")
    paper_path = str(out_dir / "paper_trades.csv")

    n1 = export_predictions_csv(pred_path)
    n2 = export_trades_csv(paper_path)

    if n1:
        print(green(f"  Exported {n1} predictions → {pred_path}"))
    else:
        print(dim("  No predictions to export yet."))
    if n2:
        print(green(f"  Exported {n2} paper trades → {paper_path}"))
    else:
        print(dim("  No paper trades to export yet."))


# ── Portfolio ─────────────────────────────────────────────────────────────────


def cmd_balance(client: KalshiClient):
    if not validate_api_key(client):
        return
    from paper import get_balance as paper_balance

    data = client.get_balance()
    balance = data.get("balance", data)
    val = float(balance) / 100 if isinstance(balance, int) else float(balance)
    try:
        paper_val = paper_balance()
        paper_str = f"  {dim('Paper:')}  {bold(f'${paper_val:.2f}')}"
    except Exception:
        paper_str = ""
    print(f"\n  {dim('Kalshi:')} {bold(f'${val:.2f}')}")
    if paper_str:
        print(paper_str)


def cmd_positions(client: KalshiClient):
    positions = client.get_positions()
    if not positions:
        print(yellow("No open positions."))
        return

    print(bold("\nOpen positions — checking current model probabilities...\n"))
    rows = []
    for p in positions:
        ticker = p.get("ticker", "")
        position = p.get("position", 0)  # positive = long YES, negative = long NO
        exposure = p.get("market_exposure", "")
        rpnl = p.get("realized_pnl", "")
        upnl = p.get("unrealized_pnl", "")

        # Determine which side we hold
        held_side = (
            "YES" if (isinstance(position, int | float) and position > 0) else "NO"
        )

        # Try to get current model probability
        exit_signal = ""
        try:
            market = client.get_market(ticker)
            enriched = enrich_with_forecast(market)
            analysis = analyze_trade(enriched)
            if analysis:
                cur_prob = analysis["forecast_prob"]
                mkt_prob = analysis["market_prob"]
                net_edge = analysis.get("net_edge", analysis["edge"])
                # If we're long YES but model now says NO (or vice versa), flag exit
                if held_side == "YES" and net_edge < -0.05:
                    exit_signal = red("EXIT — model flipped vs entry")
                elif held_side == "NO" and net_edge > 0.05:
                    exit_signal = red("EXIT — model flipped vs entry")
                elif abs(net_edge) < 0.02:
                    exit_signal = yellow("HOLD — edge thin, watch")
                else:
                    exit_signal = green("HOLD — edge intact")
                cur_prob_str = f"{cur_prob * 100:.0f}% / mkt {mkt_prob * 100:.0f}%"
            else:
                cur_prob_str = dim("—")
        except Exception:
            cur_prob_str = dim("—")

        rows.append(
            [ticker, held_side, exposure, rpnl, upnl, cur_prob_str, exit_signal]
        )

    print(
        tabulate(
            rows,
            headers=[
                "Ticker",
                "Side",
                "Exposure",
                "Realized",
                "Unrealized",
                "Cur P / Mkt P",
                "Exit?",
            ],
            tablefmt="rounded_outline",
        )
    )


def cmd_order(client: KalshiClient, action: str, args: list):
    if len(args) < 4:
        print(f"Usage: py main.py {action} <ticker> <yes/no> <count> <price>")
        return
    ticker, side, count_str, price_str = args[0], args[1], args[2], args[3]
    if side not in ("yes", "no"):
        print(red("side must be 'yes' or 'no'"))
        return
    try:
        count, price = float(count_str), float(price_str)
    except ValueError:
        print(red("count and price must be numbers"))
        return

    from execution_log import log_order, log_order_result, was_recently_ordered

    if was_recently_ordered(ticker, side):
        print(
            yellow(
                f"  [Warning] A {side.upper()} order for {ticker} was placed in the last 10 minutes."
            )
        )
        confirm2 = input(yellow("  Place another anyway? (y/N): ")).strip().lower()
        if confirm2 != "y":
            print(dim("  Cancelled to avoid duplicate."))
            return

    print(
        f"\n  {bold(action.upper())}  {count} × {ticker}  {bold(side.upper())}  @ ${price:.4f}"
    )
    confirm = input(yellow("  Confirm? (y/N): ")).strip().lower()
    if confirm != "y":
        print(dim("  Cancelled."))
        return

    row_id = log_order(ticker, side, int(count), price, order_type=action)
    try:
        result = client.place_order(ticker, side, action, count, price)
        order = result.get("order", result)
        log_order_result(row_id, status=order.get("status", "sent"), response=order)
        print(green(f"  Order placed: {order.get('order_id', '')}"))
        print(
            f"  Status: {order.get('status')}  Filled: {order.get('fill_count_fp', 0)}"
        )
    except Exception as e:
        log_order_result(row_id, status="failed", error=str(e))
        print(red(f"  Order failed: {e}"))
        raise


def cmd_cancel(client: KalshiClient, order_id: str):
    result = client.cancel_order(order_id)
    print(green(f"Cancelled: {result}"))


def cmd_sync(client: KalshiClient):
    print("Syncing settled markets...")
    count = sync_outcomes(client)
    print(green(f"Done — recorded {count} new outcome(s)."))


# ── Setup wizard ──────────────────────────────────────────────────────────────


def cmd_setup():
    from climatology import preload_all

    print(bold("\n╔══════════════════════════════════╗"))
    print(bold("║   Kalshi Weather Setup Wizard    ║"))
    print(bold("╚══════════════════════════════════╝\n"))

    env_path = Path(".env")

    # ── Step 1: Credentials ───────────────────────────────────────────────────
    print(bold("Step 1 of 3 — Kalshi API credentials"))
    print(dim("Get these at: kalshi.com → Account → Settings → API Keys\n"))

    existing_key = os.getenv("KALSHI_KEY_ID", "")
    existing_pem = os.getenv("KALSHI_PRIVATE_KEY_PATH", "")
    existing_env = os.getenv("KALSHI_ENV", "demo")

    key_id = (
        input(f"  Key ID       [{existing_key or 'required'}]: ").strip()
        or existing_key
    )
    pem_path = (
        input(
            f"  Private key  [{existing_pem or './kalshi_private_key.pem'}]: "
        ).strip()
        or existing_pem
        or "./kalshi_private_key.pem"
    )
    env_mode = (
        input(f"  Environment  [demo/prod, default={existing_env}]: ").strip()
        or existing_env
    )

    if not key_id:
        print(yellow("\n  No Key ID entered — skipping credential setup."))
        print(dim("  You can still use market data without credentials."))
    else:
        env_contents = (
            f"KALSHI_KEY_ID={key_id}\n"
            f"KALSHI_PRIVATE_KEY_PATH={pem_path}\n"
            f"KALSHI_ENV={env_mode}\n"
        )
        env_path.write_text(env_contents)
        load_dotenv(override=True)
        print(green("  .env saved.\n"))

        # Test connection
        print(bold("  Testing Kalshi connection..."), end=" ", flush=True)
        try:
            client = build_client()
            client.get_balance()
            print(green("OK"))
        except Exception as e:
            print(red(f"FAILED — {e}"))
            print(
                dim("  Check your Key ID and that the .pem file is in the right place.")
            )

    # ── Step 2: Climate history ───────────────────────────────────────────────
    print(bold("\nStep 2 of 3 — Download 30-year climate history"))
    print(
        dim("  This is a one-time download (~10 seconds per city). Cached forever.\n")
    )

    from pathlib import Path as P

    data_dir = P("data")
    data_dir.mkdir(exist_ok=True)
    missing = [c for c in CITY_COORDS if not (data_dir / f"climate_{c}.json").exists()]

    if not missing:
        print(green("  All climate data already cached — nothing to download."))
    else:
        print(f"  Need to download: {', '.join(missing)}")
        go = input("  Download now? (Y/n): ").strip().lower()
        if go != "n":
            for i, city in enumerate(missing, 1):
                print(f"  [{i}/{len(missing)}] {city}...", end=" ", flush=True)
                try:
                    preload_all({city: CITY_COORDS[city]})
                    print(green("done"))
                except Exception as e:
                    print(red(f"failed — {e}"))
        else:
            print(dim("  Skipped — first 'analyze' run will be slower."))

    # ── Step 3: Done ──────────────────────────────────────────────────────────
    print(bold("\nStep 3 of 3 — You're ready!\n"))
    print("  Try these commands:")
    print(f"    {cyan('py main.py')}              — interactive menu")
    print(f"    {cyan('py main.py analyze')}      — find the best trades right now")
    print(f"    {cyan('py main.py watch')}        — live auto-refreshing dashboard")
    print(f"    {cyan('py main.py forecast NYC')} — 7-day weather forecast")
    print()


# ── Interactive menu ──────────────────────────────────────────────────────────


def _cmd_settle_open(client: KalshiClient | None = None) -> None:  # noqa: ARG001
    """Interactively settle an open paper trade by choosing from a list."""
    from paper import get_balance, get_open_trades, settle_paper_trade

    open_trades = get_open_trades()
    if not open_trades:
        print(dim("  No open paper trades to settle."))
        return

    rows = [
        [
            t["id"],
            t["ticker"][:32],
            bold(t["side"].upper()),
            t["quantity"],
            f"${t['entry_price']:.3f}",
            f"${t['cost']:.2f}",
            t.get("target_date", "—"),
        ]
        for t in open_trades
    ]
    print(
        tabulate(
            rows,
            headers=["#", "Ticker", "Side", "Qty", "Price", "Cost", "Date"],
            tablefmt="rounded_outline",
        )
    )
    try:
        while True:
            raw = input(dim("\n  Trade # to settle (q to cancel): ")).strip()
            if raw.lower() == "q":
                return
            if not raw:
                continue
            try:
                trade_id = int(raw)
                break
            except ValueError:
                print(red("  Enter a trade number."))
        while True:
            outcome_raw = (
                input(dim("  Outcome (yes/no, q to cancel): ")).strip().lower()
            )
            if outcome_raw == "q":
                return
            if outcome_raw in ("yes", "no"):
                break
        t = settle_paper_trade(trade_id, outcome_raw == "yes")
        pnl = t.get("pnl", 0.0) or 0.0
        pnl_s = green(f"+${pnl:.2f}") if pnl >= 0 else red(f"-${abs(pnl):.2f}")
        print(
            green(
                f"  Trade #{trade_id} settled {t['outcome'].upper()}  "
                f"P&L: {pnl_s}  Balance: ${get_balance():.2f}"
            )
        )
    except (KeyboardInterrupt, EOFError):
        print()


def _menu_watch(client: KalshiClient) -> None:
    """Prompt for edge threshold before entering watch mode."""
    try:
        raw = input("  Edge threshold % (default 10): ").strip()
        min_edge = float(raw) / 100 if raw else 0.10
    except (ValueError, EOFError):
        min_edge = 0.10
    cmd_watch(client, min_edge=min_edge)


def cmd_menu(client: KalshiClient):
    from paper import get_balance as paper_balance

    # (shortcut_key, name, description, fn)  — description="" for Quit
    # fn=None means special handling below
    options = [
        ("A", "Analyze", "find best trades now", lambda: cmd_analyze(client)),
        ("W", "Watch", "live auto-refresh dashboard", lambda: _menu_watch(client)),
        ("M", "Market", "look up a specific ticker", None),
        ("C", "Consistency", "find free arbitrage", lambda: cmd_consistency(client)),
        ("F", "Forecast", "7-day weather forecast", None),
        ("H", "History", "past predictions + Brier score", lambda: cmd_history(client)),
        ("B", "Balance", "Kalshi account balance", lambda: cmd_balance(client)),
        (
            "O",
            "Positions",
            "open positions + exit signals",
            lambda: cmd_positions(client),
        ),
        ("P", "Paper", "buy / settle / view paper trades", None),
        ("L", "Settle", "settle an open paper trade", lambda: _cmd_settle_open(client)),
        ("K", "Backtest", "score model on history", lambda: cmd_backtest(client, [])),
        ("D", "Dashboard", "portfolio overview", lambda: cmd_dashboard(client)),
        ("E", "Export", "save predictions + trades to CSV", lambda: cmd_export()),
        ("S", "Schedule", "hourly auto-scan", lambda: cmd_schedule()),
        ("U", "Setup", "setup wizard", lambda: cmd_setup()),
        ("Q", "Quit", "", None),
    ]
    name_w = max(len(name) for _, name, _, _ in options)
    key_map = {key.lower(): str(i) for i, (key, _, _, _) in enumerate(options, 1)}

    while True:
        env_text = f"[{KALSHI_ENV.upper()}]"
        title_visible = f"   Kalshi Weather Prediction Markets   {env_text}"

        # Build status line: balance + open trades + Brier
        try:
            raw_bal = paper_balance()
            status_visible = f"  Paper: ${raw_bal:.2f}"
            status_colored = f"  Paper: {green(f'${raw_bal:.2f}')}"
        except Exception:
            raw_bal = None
            status_visible = ""
            status_colored = ""

        try:
            from paper import get_open_trades as _pot

            n_open = len(_pot())
            if n_open:
                status_visible += f"  ·  {n_open} open"
                status_colored += f"  {dim('·')}  {cyan(f'{n_open} open')}"
        except Exception:
            pass

        try:
            bs = brier_score()
            if bs is not None:
                grade = (
                    "Excellent"
                    if bs < 0.10
                    else "Good"
                    if bs < 0.18
                    else "Fair"
                    if bs < 0.25
                    else "Poor"
                )
                grade_color = (
                    green
                    if grade in ("Excellent", "Good")
                    else yellow
                    if grade == "Fair"
                    else red
                )
                status_visible += f"  ·  Brier: {bs:.3f} {grade}"
                status_colored += (
                    f"  {dim('·')}  Brier: {grade_color(f'{bs:.3f} {grade}')}"
                )
        except Exception:
            pass

        menu_w = max(50, len(title_visible), len(status_visible))
        bar = "─" * menu_w
        title_pad = " " * max(0, menu_w - len(title_visible))
        title_line = (
            f"   Kalshi Weather Prediction Markets   {dim(env_text)}{title_pad}"
        )
        status_pad = " " * max(0, menu_w - len(status_visible))
        status_line = f"{status_colored}{status_pad}"

        print(bold(f"\n  ┌{bar}┐"))
        print(f"  {bold('│')}{title_line}{bold('│')}")
        print(f"  {bold('│')}{status_line}{bold('│')}")
        print(bold(f"  └{bar}┘\n"))

        for i, (key, name, desc, _) in enumerate(options, 1):
            num = cyan(f"  {i:>2}")
            key_str = dim(f"[{key}]")
            spacing = " " * (name_w - len(name))
            if desc:
                print(f"{num} {key_str} {bold(name)}{spacing}  {dim('·')}  {desc}")
            else:
                print(f"{num} {key_str} {name}")

        choice = input(bold(f"\n  Choose (1–{len(options)} or letter): ")).strip()
        if not choice.isdigit():
            choice = key_map.get(choice.lower(), choice)
        if not choice.isdigit() or not (1 <= int(choice) <= len(options)):
            print(red("  Invalid choice."))
            continue

        idx = int(choice) - 1
        _key, name, desc, fn = options[idx]

        if name == "Quit":
            print(dim("Goodbye."))
            break
        elif name == "Market":
            while True:
                raw = input("  Ticker (q to cancel): ").strip()
                if raw.lower() == "q":
                    break
                if raw:
                    verbose = input("  Verbose detail? (y/N): ").strip().lower() == "y"
                    cmd_market(client, raw.upper(), verbose=verbose)
                    break
        elif name == "Forecast":
            while True:
                city = input(
                    f"  City ({'/'.join(CITY_COORDS.keys())}, q to cancel): "
                ).strip()
                if city.lower() == "q":
                    break
                if city:
                    cmd_forecast(city)
                    break
        elif name == "Paper":
            print(bold("\n  Paper trading:\n"))
            print(
                f"  {cyan('1')}  {bold('Results')}  {dim('·')}  performance summary & open positions"
            )
            print(
                f"  {cyan('2')}  {bold('Buy')}      {dim('·')}  open a new paper position"
            )
            print(
                f"  {cyan('3')}  {bold('Settle')}   {dim('·')}  close an open trade manually"
            )
            print(
                f"  {cyan('4')}  {bold('Review')}   {dim('·')}  check open trades for exit signals"
            )
            sub = input(dim("  Choose (1–4): ")).strip()
            if sub == "1":
                cmd_paper(["results"], client)
            elif sub == "2":
                while True:
                    raw = input(dim("  Ticker (q to cancel): ")).strip()
                    if raw.lower() == "q":
                        break
                    if not raw:
                        continue
                    ticker = raw.upper()
                    while True:
                        side = (
                            input(dim("  Side (yes/no, q to cancel): ")).strip().lower()
                        )
                        if side == "q":
                            ticker = ""
                            break
                        if side in ("yes", "no"):
                            break
                    if not ticker:
                        break
                    price = _resolve_price(client, ticker, side)
                    if price is None:
                        price = _prompt_price()
                    if price is not None:
                        raw_qty = input(
                            dim("  Qty (Enter for Kelly auto-size): ")
                        ).strip()
                        qty_arg = (
                            [raw_qty] if raw_qty.isdigit() and int(raw_qty) > 0 else []
                        )
                        cmd_paper(
                            ["buy", ticker, side, f"{price:.3f}"] + qty_arg, client
                        )
                    break
            elif sub == "3":
                _cmd_settle_open(client)
            elif sub == "4":
                from paper import check_model_exits

                recs = check_model_exits(client)
                if not recs:
                    print(green("  All open positions look fine — no exit signals."))
                else:
                    print(bold(f"\n  {len(recs)} exit signal(s):\n"))
                    for rec in recs:
                        t = rec["trade"]
                        reason = (
                            "Model flipped direction"
                            if rec["reason"] == "model_flipped"
                            else "Edge evaporated (<3%)"
                        )
                        print(
                            yellow(
                                f"  #{t['id']}  {t['ticker']}  {t['side'].upper()}"
                                f"  —  {reason}  (edge now {rec['current_edge']:+.1%})"
                            )
                        )
        elif fn is not None:
            fn()

        input(dim("\n  Press Enter to return to menu..."))


# ── Backtest ─────────────────────────────────────────────────────────────────


def cmd_backtest(client: KalshiClient, args: list):
    """
    Run a backtest on finalized Kalshi markets.
    Usage: py main.py backtest [city] [--days N]
    """
    from backtest import run_backtest

    city_filter = None
    days_back = 90
    for i, a in enumerate(args):
        if a == "--days" and i + 1 < len(args):
            try:
                days_back = int(args[i + 1])
            except ValueError:
                pass
        elif not a.startswith("--"):
            city_filter = a

    print(
        bold(
            f"\nRunning backtest (last {days_back} days"
            + (f", {city_filter}" if city_filter else ", all cities")
            + ")...\n"
        )
    )
    print(dim("Fetching finalized markets and archive weather data..."))

    def _bt_progress(i: int, n: int) -> None:
        print(f"\r  Scoring [{i}/{n}]...", end="", flush=True)

    summary = run_backtest(
        client,
        city_filter=city_filter,
        days_back=days_back,
        on_progress=_bt_progress,
    )
    n_scored = summary["n_markets"]
    print(f"\r  Scored {n_scored} weather market(s).              ")
    if n_scored < 30:
        print(
            yellow(
                f"  ⚠  Only {n_scored} markets found — scores may not be reliable."
                f" Try a longer window: py main.py backtest --days 180"
            )
        )

    n = summary["n_markets"]
    if n == 0:
        print(yellow("No finalized weather markets found in this window."))
        return

    brier = summary["brier"]
    win_rate = summary["win_rate"]
    pnl = summary["total_pnl"]
    val_brier = summary.get("val_brier")
    val_n = summary.get("val_n", 0)
    val_wr = summary.get("val_win_rate")

    print(bold(f"\n── Backtest Results ({n} markets) ──\n"))

    def _brier_str(b: float | None) -> str:
        if b is None:
            return "—"
        if b < 0.20:
            return green(f"{b:.4f}")
        elif b < 0.25:
            return yellow(f"{b:.4f}")
        return red(f"{b:.4f}")

    wr_str = (
        green(f"{win_rate:.0%}")
        if win_rate and win_rate > 0.55
        else f"{win_rate:.0%}"
        if win_rate
        else "—"
    )
    pnl_str = green(f"+{pnl:.2%}") if pnl > 0 else red(f"{pnl:.2%}")

    train_n = n - val_n
    print(
        f"  Brier score:  {_brier_str(brier)}   (train, {train_n} markets — 0.25=random, 0.0=perfect)"
    )
    if val_n > 0:
        overfit_warn = ""
        if brier and val_brier and val_brier > brier + 0.03:
            overfit_warn = f"  {yellow('⚠ possible overfit')}"
        val_wr_str = (
            green(f"{val_wr:.0%}")
            if val_wr and val_wr > 0.55
            else f"{val_wr:.0%}"
            if val_wr
            else "—"
        )
        print(
            f"  Val Brier:    {_brier_str(val_brier)}   (holdout, {val_n} markets){overfit_warn}"
        )
        print(f"  Val win rate: {val_wr_str}")
    print(f"  Win rate:     {wr_str}   (picking better side vs market)")
    print(f"  Sim P&L:      {pnl_str}   (half-Kelly sizing, 5% cap, 7% fees)")

    # Show worst 5 and best 5
    rows = summary["rows"]
    rows_sorted = sorted(rows, key=lambda r: r["brier_sq"], reverse=True)
    worst = rows_sorted[:5]
    best = sorted(rows, key=lambda r: r["brier_sq"])[:5]

    print(bold("\n  Worst calls (highest Brier error):"))
    w_rows = [
        [
            r["ticker"],
            r["city"],
            r["date"],
            f"{r['our_prob'] * 100:.0f}%",
            f"{r['market_prob'] * 100:.0f}%",
            "YES" if r["actual"] else "NO",
            red("WRONG") if not r["won"] else green("RIGHT"),
        ]
        for r in worst
    ]
    print(
        tabulate(
            w_rows,
            headers=["Ticker", "City", "Date", "Our P", "Mkt P", "Actual", "Call"],
            tablefmt="rounded_outline",
        )
    )

    print(bold("\n  Best calls (lowest Brier error):"))
    b_rows = [
        [
            r["ticker"],
            r["city"],
            r["date"],
            f"{r['our_prob'] * 100:.0f}%",
            f"{r['market_prob'] * 100:.0f}%",
            "YES" if r["actual"] else "NO",
            green("RIGHT") if r["won"] else red("WRONG"),
        ]
        for r in best
    ]
    print(
        tabulate(
            b_rows,
            headers=["Ticker", "City", "Date", "Our P", "Mkt P", "Actual", "Call"],
            tablefmt="rounded_outline",
        )
    )


# ── Paper trading ────────────────────────────────────────────────────────────


def cmd_paper(args: list, client: KalshiClient | None = None):
    """
    Paper trading commands:
      paper buy <ticker> <yes/no> <qty> <price>
      paper results
      paper settle <trade_id> <yes/no>
      paper reset
    """
    from paper import (
        get_all_trades,
        get_balance,
        get_open_trades,
        get_performance,
        is_paused_drawdown,
        kelly_bet_dollars,
        kelly_quantity,
        place_paper_order,
        portfolio_kelly_fraction,
        reset_paper_account,
        settle_paper_trade,
    )

    sub = args[0].lower() if args else "results"

    if sub == "buy":
        # qty is optional — omit to auto-size via Kelly compounding
        if len(args) < 4:
            print("Usage: py main.py paper buy <ticker> <yes/no> <price> [qty]")
            print("       Omit qty to auto-size using Kelly × current balance")
            return
        ticker = args[1]
        side = args[2].lower()
        if side not in ("yes", "no"):
            print(red("side must be 'yes' or 'no'"))
            return
        try:
            price = float(args[3])
            qty_s = args[4] if len(args) > 4 else None
            qty = int(qty_s) if qty_s is not None else None
        except ValueError:
            print(red("price must be a decimal; qty (optional) must be an integer"))
            return

        # Drawdown guard: block auto-sizing when balance < 50% of starting bankroll
        if is_paused_drawdown() and qty is None:
            from paper import MAX_DRAWDOWN_FRACTION, STARTING_BALANCE

            floor = STARTING_BALANCE * MAX_DRAWDOWN_FRACTION
            print(
                red(
                    f"\n  [Drawdown] Auto-sizing paused — balance is below "
                    f"${floor:.0f} (50% of ${STARTING_BALANCE:.0f} starting bankroll)."
                )
            )
            print(
                dim("  Specify qty manually: paper buy <ticker> <side> <price> <qty>")
            )
            return

        # Get current analysis for Kelly sizing and context
        entry_prob, net_edge, fee_kelly = None, None, 0.0
        enriched: dict | None = None
        if client:
            try:
                market = client.get_market(ticker)
                enriched = enrich_with_forecast(market)
                analysis = analyze_trade(enriched)
                if analysis:
                    entry_prob = analysis["forecast_prob"]
                    net_edge = analysis.get("net_edge")
                    # ci_adjusted_kelly already factors in forecast confidence width
                    fee_kelly = analysis.get(
                        "ci_adjusted_kelly", analysis.get("fee_adjusted_kelly", 0.0)
                    )
            except Exception:
                pass

        # Extract city/date for portfolio Kelly check
        city = enriched.get("_city") if enriched else None
        target_date_obj = enriched.get("_date") if enriched else None
        target_date_str = target_date_obj.isoformat() if target_date_obj else None

        # Auto-size if qty not provided
        if qty is None:
            if fee_kelly and fee_kelly > 0.005:
                adj_kelly = portfolio_kelly_fraction(
                    fee_kelly, city, target_date_str, side=side
                )
                if adj_kelly < fee_kelly:
                    print(
                        yellow(
                            f"  [Portfolio] Kelly reduced {fee_kelly * 100:.1f}% → "
                            f"{adj_kelly * 100:.1f}% (existing {city}/{target_date_str} exposure)"
                        )
                    )
                qty = kelly_quantity(adj_kelly, price)
                bet_amt = kelly_bet_dollars(adj_kelly)
                print(
                    f"\n  {bold('Kelly auto-size:')} {adj_kelly * 100:.1f}% of balance "
                    f"= {green(f'${bet_amt:.2f}')} → {bold(str(qty))} contracts"
                )
            else:
                print(
                    yellow(
                        "  No Kelly fraction available — please specify qty manually."
                    )
                )
                print("  Usage: py main.py paper buy <ticker> <yes/no> <price> <qty>")
                return

        balance = get_balance()
        cost = qty * price
        print(
            f"\n  Paper BUY  {bold(str(qty))} × {ticker}  {bold(side.upper())}  @ ${price:.4f}"
        )
        print(f"  Cost: {bold(f'${cost:.2f}')}  |  Paper balance: ${balance:.2f}")
        if entry_prob is not None:
            print(
                f"  Model P: {entry_prob * 100:.1f}%"
                + (f"  Net edge: {net_edge:+.1%}" if net_edge is not None else "")
            )
        confirm = input(yellow("  Confirm paper trade? (y/N): ")).strip().lower()
        if confirm != "y":
            print(dim("  Cancelled."))
            return
        try:
            trade = place_paper_order(
                ticker,
                side,
                qty,
                price,
                entry_prob,
                net_edge,
                city=city,
                target_date=target_date_str,
            )
            print(
                green(
                    f"  Paper trade #{trade['id']} placed. "
                    f"Remaining balance: ${get_balance():.2f}"
                )
            )
        except ValueError as e:
            print(red(f"  Error: {e}"))

    elif sub == "settle":
        if len(args) < 3:
            print("Usage: py main.py paper settle <trade_id> <yes/no>")
            return
        try:
            trade_id = int(args[1])
            outcome_yes = args[2].lower() == "yes"
        except (ValueError, IndexError):
            print(red("trade_id must be integer; outcome must be 'yes' or 'no'"))
            return
        try:
            t = settle_paper_trade(trade_id, outcome_yes)
            pnl_str = (
                green(f"+${t['pnl']:.2f}") if t["pnl"] >= 0 else red(f"${t['pnl']:.2f}")
            )
            print(
                f"  Trade #{trade_id} settled {t['outcome'].upper()}  P&L: {pnl_str}  "
                f"Balance: ${get_balance():.2f}"
            )
        except ValueError as e:
            print(red(f"  {e}"))

    elif sub == "reset":
        confirm = (
            input(yellow("  Reset all paper trades and balance? (y/N): "))
            .strip()
            .lower()
        )
        if confirm == "y":
            reset_paper_account()
            print(green("  Paper account reset to $1,000."))
        else:
            print(dim("  Cancelled."))

    else:  # "results"
        perf = get_performance()
        open_ = get_open_trades()
        all_ = get_all_trades()

        _header("Paper Trading Results")
        _kv("Balance:", bold(f"${perf['balance']:.2f}"))
        if perf["settled"]:
            wr = (
                f"{perf['win_rate'] * 100:.0f}%"
                if perf["win_rate"] is not None
                else "—"
            )
            roi_ = f"{perf['roi'] * 100:+.1f}%" if perf["roi"] is not None else "—"
            pnl_ = (
                green(f"+${perf['total_pnl']:.2f}")
                if perf["total_pnl"] >= 0
                else red(f"${perf['total_pnl']:.2f}")
            )
            _kv("Settled:", str(perf["settled"]))
            _kv("Win rate:", wr)
            _kv("ROI:", roi_)
            _kv("P&L:", pnl_)

        if open_:
            print(bold(f"\n  Open trades ({len(open_)}):"))
            rows = [
                [
                    t["id"],
                    t["ticker"],
                    t["side"].upper(),
                    t["quantity"],
                    f"${t['entry_price']:.4f}",
                    f"${t['cost']:.2f}",
                    t["entered_at"][:10],
                ]
                for t in open_
            ]
            print(
                tabulate(
                    rows,
                    headers=["#", "Ticker", "Side", "Qty", "Entry", "Cost", "Date"],
                    tablefmt="rounded_outline",
                )
            )

        if not all_:
            print(
                dim(
                    "\n  No trades yet.  Try: py main.py paper buy <ticker> yes 10 0.45"
                )
            )


# ── Scheduled auto-scan ──────────────────────────────────────────────────────


def cmd_schedule():
    """Register a Windows Task Scheduler job to auto-scan every hour."""
    if sys.platform != "win32":
        print(yellow("Scheduled tasks are only supported on Windows."))
        return

    import shutil

    schtasks = shutil.which("schtasks")
    if not schtasks:
        print(red("schtasks.exe not found — cannot register scheduled task."))
        return

    script_path = Path(__file__).resolve()
    py_exe = sys.executable

    task_name = "KalshiWeatherScan"
    task_cmd = f'"{py_exe}" "{script_path}" analyze'

    # Build the schtasks command
    create_cmd = (
        f'schtasks /Create /F /SC HOURLY /MO 1 /TN "{task_name}" '
        f'/TR "{task_cmd}" /RL HIGHEST'
    )

    print(bold(f"Registering scheduled task: {task_name}"))
    print(dim(f"Command: {task_cmd}"))
    confirm = input("  Register now? (Y/n): ").strip().lower()
    if confirm == "n":
        print(dim("Cancelled."))
        return

    import subprocess

    result = subprocess.run(create_cmd, shell=True, capture_output=True, text=True)
    if result.returncode == 0:
        print(green(f"\nTask '{task_name}' registered — runs every hour."))
        print(dim("To remove: schtasks /Delete /TN KalshiWeatherScan /F"))
    else:
        print(red(f"Failed: {result.stderr.strip() or result.stdout.strip()}"))
        print(dim("Try running this terminal as Administrator."))

    # ── Daily settle task ────────────────────────────────────────────────────
    settle_task = "KalshiWeatherSettle"
    settle_cmd = f'"{py_exe}" "{script_path}" settle'
    settle_create = (
        f'schtasks /Create /F /SC DAILY /ST 21:00 /TN "{settle_task}" '
        f'/TR "{settle_cmd}" /RL HIGHEST'
    )

    print(bold(f"\nRegistering daily settle task: {settle_task}"))
    print(dim(f"Command: {settle_cmd}"))
    print(
        dim(
            "  Runs at 21:00 local machine time — adjust if not in your target timezone."
        )
    )
    confirm2 = input("  Register now? (Y/n): ").strip().lower()
    if confirm2 != "n":
        result2 = subprocess.run(
            settle_create, shell=True, capture_output=True, text=True
        )
        if result2.returncode == 0:
            print(green(f"\nTask '{settle_task}' registered — runs daily at 9pm."))
            print(dim("To remove: schtasks /Delete /TN KalshiWeatherSettle /F"))
        else:
            print(red(f"Failed: {result2.stderr.strip() or result2.stdout.strip()}"))


# ── Router ────────────────────────────────────────────────────────────────────


def main():
    args = sys.argv[1:]

    # Skip env check for setup command so new users can run it without creds
    if args and args[0].lower() == "setup":
        cmd_setup()
        return

    if not validate_env():
        if not Path(".env").exists():
            print(
                yellow(
                    "  Tip: run  py main.py setup  to configure your Kalshi API credentials."
                )
            )
            go = input("  Run setup wizard now? (Y/n): ").strip().lower()
            if go != "n":
                cmd_setup()
                return
        sys.exit(1)

    # --debug enables verbose logging of API errors and silent exceptions
    if "--debug" in args:
        logging.basicConfig(
            level=logging.DEBUG,
            format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        )
        args = [a for a in args if a != "--debug"]
    else:
        logging.disable(logging.CRITICAL)

    init_db()
    cleanup_data_dir()

    # No arguments → interactive menu
    if not args:
        client = build_client()
        auto_settle(client)
        cmd_menu(client)
        return

    cmd = args[0].lower()
    verbose = "--verbose" in args or "-v" in args
    client = build_client()
    auto_settle(client)

    if cmd == "menu":
        cmd_menu(client)
    elif cmd == "setup":
        cmd_setup()
    elif cmd == "markets":
        cmd_markets(client)
    elif cmd == "analyze":
        min_edge = 0.10
        if "--edge" in args:
            try:
                min_edge = float(args[args.index("--edge") + 1]) / 100
            except (IndexError, ValueError):
                print(
                    red("  --edge expects a number, e.g.: py main.py analyze --edge 5")
                )
        cmd_analyze(client, min_edge=min_edge)
    elif cmd == "watch":
        min_edge = 0.10
        if "--edge" in args:
            try:
                min_edge = float(args[args.index("--edge") + 1]) / 100
            except (IndexError, ValueError):
                pass
        cmd_watch(client, auto_trade="--auto" in args, min_edge=min_edge)
    elif cmd == "market":
        if len(args) < 2:
            print("Usage: py main.py market <ticker> [--verbose]")
        else:
            cmd_market(client, args[1].upper(), verbose=verbose)
    elif cmd == "consistency":
        cmd_consistency(client)
    elif cmd == "history":
        cmd_history(client)
    elif cmd == "sync":
        cmd_sync(client)
    elif cmd == "forecast":
        if len(args) < 2:
            print(
                f"Usage: py main.py forecast <city>  ({'/'.join(CITY_COORDS.keys())})"
            )
        else:
            cmd_forecast(args[1])
    elif cmd == "balance":
        cmd_balance(client)
    elif cmd == "positions":
        cmd_positions(client)
    elif cmd in ("buy", "sell"):
        cmd_order(client, cmd, args[1:])
    elif cmd == "cancel":
        if len(args) < 2:
            print("Usage: py main.py cancel <order_id>")
        else:
            cmd_cancel(client, args[1])
    elif cmd == "schedule":
        cmd_schedule()
    elif cmd == "settle":
        cmd_settle(client)
    elif cmd == "paper":
        cmd_paper(args[1:], client)
    elif cmd == "backtest":
        cmd_backtest(client, args[1:])
    elif cmd == "dashboard":
        cmd_dashboard(client)
    elif cmd == "export":
        cmd_export()
    else:
        print(red(f"Unknown command: {cmd}"))
        print(dim("Run  py main.py  for the interactive menu."))


if __name__ == "__main__":
    main()
