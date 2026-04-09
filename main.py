#!/usr/bin/env python3
"""Kalshi Weather Prediction Markets — run with no arguments for interactive menu."""

import io
import os
import sys
import time
from datetime import date, timedelta
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
    get_calibration_by_city,
    get_calibration_trend,
    get_history,
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
    """Delete cached data files from previous dates to prevent unbounded growth."""
    data_dir = Path(__file__).parent / "data"
    if not data_dir.exists():
        return
    today = date.today().isoformat()
    for f in data_dir.glob("*.json"):
        # Files are named like "ensemble_NYC_2025-04-08.json"
        if today not in f.name:
            try:
                f.unlink()
            except OSError:
                pass


# ── Client ────────────────────────────────────────────────────────────────────


def build_client() -> KalshiClient:
    return KalshiClient(
        key_id=os.getenv("KALSHI_KEY_ID"),
        private_key_path=os.getenv("KALSHI_PRIVATE_KEY_PATH"),
        env=os.getenv("KALSHI_ENV", "demo"),
    )


# ── Markets list ──────────────────────────────────────────────────────────────


def cmd_markets(client: KalshiClient):
    print(bold("Fetching open weather markets...\n"))
    markets = get_weather_markets(client)
    if not markets:
        print(yellow("No weather markets found."))
        return

    rows = []
    for m in markets:
        prices = parse_market_price(m)
        enriched = enrich_with_forecast(m)
        analysis = analyze_trade(enriched)
        edge = analysis["edge"] if analysis else 0
        sig = analysis["signal"].strip() if analysis else "—"
        rows.append(
            [
                m.get("ticker", ""),
                (m.get("title") or "")[:50],
                prob_color(prices["implied_prob"]),
                signal_color(f"{sig} ({edge:+.0%})") if analysis else dim("—"),
                m.get("volume", 0),
            ]
        )

    print(
        tabulate(
            rows,
            headers=[
                bold("Ticker"),
                bold("Title"),
                bold("Mkt P"),
                bold("Signal (edge)"),
                bold("Volume"),
            ],
            tablefmt="rounded_outline",
        )
    )
    print(dim("\nRun: py main.py analyze   — to see only the strongest opportunities."))


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
    print(f"  {bold(market.get('title', ''))}")
    print(f"  Closes:   {market.get('close_time', 'N/A')[:19].replace('T', ' ')}")
    print(f"  Liquid:   {liquidity_color(liquid)}")

    if forecast:
        models = forecast.get("models_used", 1)
        hi_lo = forecast.get("high_range", (forecast["high_f"], forecast["high_f"]))
        high_str = bold(f"{forecast['high_f']:.1f}°F")
        range_str = dim(f"({hi_lo[0]:.0f}–{hi_lo[1]:.0f}° across {models} models)")
        print(f"  Forecast: {high_str} high  {range_str}")

    if analysis:
        edge = analysis["edge"]
        blended = analysis["forecast_prob"]
        kelly = analysis.get("kelly", 0)
        ci_lo = analysis.get("ci_low", blended)
        ci_hi = analysis.get("ci_high", blended)
        side = analysis["recommended_side"].upper()

        net_edge = analysis.get("net_edge", edge)
        fee_kelly = analysis.get("fee_adjusted_kelly", kelly)

        print(
            f"\n  Our P:    {bold(f'{blended * 100:.1f}%')}  "
            f"{dim(f'[CI: {ci_lo * 100:.0f}%–{ci_hi * 100:.0f}%]')}"
        )
        print(f"  Mkt P:    {prices['implied_prob'] * 100:.1f}%")
        print(
            f"  Edge:     {edge_color(edge)}  {dim('gross')}  →  {edge_color(net_edge)}  {dim('after ~7% fee')}"
        )
        if fee_kelly > 0.005:
            print(
                f"  Kelly:    {bold(f'{fee_kelly * 100:.1f}% of bankroll')}  {dim('(fee-adjusted)')}"
            )
        elif kelly > 0.005:
            print(
                f"  Kelly:    {dim(f'{kelly * 100:.1f}% of bankroll (negative after fees — skip)')}"
            )
        print(f"\n  {signal_color(analysis['signal'].strip())}")
        print(f"  Action:   BUY {bold(side)} on {ticker}")

        if not liquid:
            print(dim("  [No quotes yet — place a limit order to set your price]"))
        if analysis.get("ci_width", 0) > 0.30:
            print(
                yellow(
                    f"  [Wide CI ({analysis['ci_width']:.0%}) — high uncertainty, size down]"
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
        cond_str = (
            f">{cond['threshold']:.1f}°F"
            if cond["type"] == "above"
            else f"<{cond['threshold']:.1f}°F"
            if cond["type"] == "below"
            else f"{cond['lower']:.1f}–{cond['upper']:.1f}°F"
        )
        time_lbl = f"at {hour:02d}:00 local" if hour is not None else "daily high/low"

        print(f"\n  {bold('─── Verbose breakdown ───')}")
        print(f"  Method:   {method}, {n} ensemble members")
        print(f"  Question: temp {cond_str}  ({time_lbl})")
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
                    tablefmt="simple",
                )
            )
        else:
            print(dim("  No orders in book."))
    except Exception as e:
        print(dim(f"  Could not load orderbook: {e}"))


# ── Analyze ───────────────────────────────────────────────────────────────────


def _analyze_once(client: KalshiClient, previous_tickers: set | None = None):
    """Run one analysis pass. Returns set of opportunity tickers found."""
    markets = get_weather_markets(client)
    liquid_opps: list = []
    no_quote_opps: list = []

    for m in markets:
        enriched = enrich_with_forecast(m)
        analysis = analyze_trade(enriched)
        if not analysis or abs(analysis["edge"]) < 0.10:
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

    def make_rows(opps):
        rows = []
        for m, a in sorted(opps, key=lambda x: abs(x[1]["edge"]), reverse=True):
            cond = a["condition"]
            cond_str = (
                f">{cond['threshold']:.0f}°"
                if cond["type"] == "above"
                else f"<{cond['threshold']:.0f}°"
                if cond["type"] == "below"
                else f"{cond['lower']:.0f}–{cond['upper']:.0f}°"
            )
            es = a.get("ensemble_stats") or {}
            spread = f"{es.get('min', 0):.0f}–{es.get('max', 0):.0f}°" if es else "—"
            hour = m.get("_hour")
            is_new = (
                previous_tickers is not None and m.get("ticker") not in previous_tickers
            )
            ticker_str = f"* {m.get('ticker', '')}" if is_new else m.get("ticker", "")
            net_edge = a.get("net_edge", a["edge"])
            rows.append(
                [
                    green(ticker_str) if is_new else ticker_str,
                    m.get("_city", ""),
                    m.get("_date").isoformat() if m.get("_date") else "",
                    f"{hour:02d}:00" if hour is not None else "daily",
                    cond_str,
                    f"{a['forecast_temp']:.1f}°F",
                    spread,
                    prob_color(a["forecast_prob"]),
                    f"{a['market_prob'] * 100:.0f}%",
                    edge_color(a["edge"]),
                    edge_color(net_edge),
                    signal_color(f"BUY {a['recommended_side'].upper()}"),
                ]
            )
        return rows

    hdrs = [
        "Ticker",
        "City",
        "Date",
        "Time",
        "Condition",
        "Fcst",
        "Spread",
        "Our P",
        "Mkt P",
        "Edge",
        "Net Edge",
        "Action",
    ]

    if liquid_opps:
        print(bold(f"\n── TRADEABLE NOW ({len(liquid_opps)} markets) ──\n"))
        print(
            tabulate(make_rows(liquid_opps), headers=hdrs, tablefmt="rounded_outline")
        )
    else:
        print(dim("No liquid opportunities (markets with live quotes)."))

    if no_quote_opps:
        print(bold(f"\n── NO QUOTES YET ({len(no_quote_opps)} markets) ──\n"))
        print(
            tabulate(make_rows(no_quote_opps), headers=hdrs, tablefmt="rounded_outline")
        )

    if not liquid_opps and not no_quote_opps:
        print(yellow("No strong opportunities right now (need >10% edge)."))

    # ── Portfolio correlation warning ────────────────────────────────────────
    all_opps = liquid_opps + no_quote_opps
    from collections import Counter

    city_date_counts: Counter = Counter()
    for m, _ in all_opps:
        key = (m.get("_city", ""), str(m.get("_date", "")))
        city_date_counts[key] += 1
    for (city, dt), cnt in city_date_counts.items():
        if cnt >= 2:
            print(
                yellow(
                    f"\n  [!] Correlation warning: {cnt} opportunities for {city} on {dt}. "
                    f"These bets are highly correlated — size down or pick the highest-edge one."
                )
            )

    found = {m.get("ticker") for m, _ in all_opps}
    return found


def cmd_analyze(client: KalshiClient):
    print(bold("Scanning weather markets for trade opportunities..."))
    print(
        dim("(Ensemble forecasts cached after first run — subsequent scans are fast)\n")
    )
    _analyze_once(client)
    print(dim("\nFcst=3-model avg  Spread=ensemble range  Our P=blended probability"))
    print(dim("To see full detail:  py main.py market <ticker> --verbose"))


# ── Watch mode ────────────────────────────────────────────────────────────────


def cmd_watch(client: KalshiClient):
    print(bold("Watch mode — refreshing every 5 minutes. Press Ctrl+C to stop.\n"))
    previous: set = set()
    try:
        while True:
            os.system("cls" if sys.platform == "win32" else "clear")
            now = time.strftime("%H:%M:%S")
            print(bold(f"Kalshi Weather Markets — {now}"))
            print(dim("(* = new since last scan   Ctrl+C to exit)\n"))
            previous = _analyze_once(client, previous)
            print(
                dim(
                    f"\nNext refresh in {REFRESH_SECS // 60} min — {time.strftime('%H:%M:%S', time.localtime(time.time() + REFRESH_SECS))}"
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
    print(bold("Scanning for arbitrage (consistency violations)...\n"))
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
            headers=["Ticker", "Date", "Our P", "Mkt P", "Edge", "Outcome", ""],
            tablefmt="rounded_outline",
        )
    )

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
                    tablefmt="simple",
                )
            )
    else:
        print(dim("\n  Brier score will appear once markets settle."))


# ── Portfolio ─────────────────────────────────────────────────────────────────


def cmd_balance(client: KalshiClient):
    if not validate_api_key(client):
        return
    data = client.get_balance()
    balance = data.get("balance", data)
    val = float(balance) / 100 if isinstance(balance, int) else float(balance)
    print(f"\n  Balance: {bold(f'${val:.2f}')}")


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

    print(
        f"\n  {bold(action.upper())}  {count} × {ticker}  {bold(side.upper())}  @ ${price:.4f}"
    )
    confirm = input(yellow("  Confirm? (y/N): ")).strip().lower()
    if confirm != "y":
        print(dim("  Cancelled."))
        return
    result = client.place_order(ticker, side, action, count, price)
    order = result.get("order", result)
    print(green(f"  Order placed: {order.get('order_id', '')}"))
    print(f"  Status: {order.get('status')}  Filled: {order.get('fill_count_fp', 0)}")


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


def cmd_menu(client: KalshiClient):
    options = [
        ("Analyze — find best trades", lambda: cmd_analyze(client)),
        ("Watch  — live auto-refresh", lambda: cmd_watch(client)),
        ("Market — look up a specific ticker", None),
        ("Consistency — find free arbitrage", lambda: cmd_consistency(client)),
        ("Forecast — 7-day weather forecast", None),
        ("History — past predictions + score", lambda: cmd_history(client)),
        ("Balance", lambda: cmd_balance(client)),
        ("Positions", lambda: cmd_positions(client)),
        ("Paper trading results", lambda: cmd_paper(["results"], client)),
        ("Backtest — score model on history", lambda: cmd_backtest(client, [])),
        ("Schedule — hourly auto-scan", lambda: cmd_schedule()),
        ("Setup wizard", lambda: cmd_setup()),
        ("Quit", None),
    ]

    while True:
        print(bold("\n╔═══════════════════════════════════════╗"))
        print(bold("║   Kalshi Weather Prediction Markets   ║"))
        print(bold("╚═══════════════════════════════════════╝\n"))
        for i, (label, _) in enumerate(options, 1):
            print(f"  {cyan(str(i))}  {label}")

        choice = input(bold("\nChoose (1–13): ")).strip()
        if not choice.isdigit() or not (1 <= int(choice) <= len(options)):  # noqa: E501
            print(red("  Invalid choice."))
            continue

        idx = int(choice) - 1
        label, fn = options[idx]

        if label == "Quit":
            print(dim("Goodbye."))
            break
        elif label == "Market — look up a specific ticker":
            ticker = input("  Ticker: ").strip().upper()
            verbose = input("  Verbose detail? (y/N): ").strip().lower() == "y"
            if ticker:
                cmd_market(client, ticker, verbose=verbose)
        elif label == "Forecast — 7-day weather forecast":
            city = input(f"  City ({'/'.join(CITY_COORDS.keys())}): ").strip()
            cmd_forecast(city)
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
    days_back = 30
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

    summary = run_backtest(client, city_filter=city_filter, days_back=days_back)

    n = summary["n_markets"]
    if n == 0:
        print(yellow("No finalized weather markets found in this window."))
        return

    brier = summary["brier"]
    win_rate = summary["win_rate"]
    pnl = summary["total_pnl"]

    print(bold(f"\n── Backtest Results ({n} markets) ──\n"))
    brier_str = (
        (
            green(f"{brier:.4f}")
            if brier and brier < 0.20
            else yellow(f"{brier:.4f}")
            if brier and brier < 0.25
            else red(f"{brier:.4f}")
        )
        if brier
        else "—"
    )
    wr_str = (
        green(f"{win_rate:.0%}") if win_rate and win_rate > 0.55 else f"{win_rate:.0%}"
    )
    pnl_str = green(f"+{pnl:.2%}") if pnl > 0 else red(f"{pnl:.2%}")

    print(f"  Brier score:  {brier_str}   (0.25=random, 0.0=perfect)")
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
            tablefmt="simple",
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
            tablefmt="simple",
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
        place_paper_order,
        reset_paper_account,
        settle_paper_trade,
    )

    sub = args[0].lower() if args else "results"

    if sub == "buy":
        if len(args) < 5:
            print("Usage: py main.py paper buy <ticker> <yes/no> <qty> <price>")
            return
        ticker, side, qty_s, price_s = args[1], args[2].lower(), args[3], args[4]
        if side not in ("yes", "no"):
            print(red("side must be 'yes' or 'no'"))
            return
        try:
            qty = int(qty_s)
            price = float(price_s)
        except ValueError:
            print(red("qty must be integer, price must be a decimal"))
            return

        # Try to get current analysis for context
        entry_prob, net_edge = None, None
        if client:
            try:
                market = client.get_market(ticker)
                enriched = enrich_with_forecast(market)
                analysis = analyze_trade(enriched)
                if analysis:
                    entry_prob = analysis["forecast_prob"]
                    net_edge = analysis.get("net_edge")
            except Exception:
                pass

        balance = get_balance()
        cost = qty * price
        print(f"\n  Paper BUY  {qty} × {ticker}  {bold(side.upper())}  @ ${price:.4f}")
        print(f"  Cost: ${cost:.2f}  |  Paper balance: ${balance:.2f}")
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
            trade = place_paper_order(ticker, side, qty, price, entry_prob, net_edge)
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

        print(bold("\n── Paper Trading Results ──\n"))
        balance_str = bold(f"${perf['balance']:.2f}")
        print(f"  Balance:  {balance_str}")
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
            print(
                f"  Settled:  {perf['settled']}  |  Win rate: {wr}  |  ROI: {roi_}  |  P&L: {pnl_}"
            )

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
                    tablefmt="simple",
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


# ── Router ────────────────────────────────────────────────────────────────────


def main():
    args = sys.argv[1:]

    # Skip env check for setup command so new users can run it without creds
    if args and args[0].lower() == "setup":
        cmd_setup()
        return

    if not validate_env():
        sys.exit(1)

    cleanup_data_dir()

    # No arguments → interactive menu
    if not args:
        client = build_client()
        cmd_menu(client)
        return

    cmd = args[0].lower()
    verbose = "--verbose" in args or "-v" in args
    client = build_client()

    if cmd == "menu":
        cmd_menu(client)
    elif cmd == "setup":
        cmd_setup()
    elif cmd == "markets":
        cmd_markets(client)
    elif cmd == "analyze":
        cmd_analyze(client)
    elif cmd == "watch":
        cmd_watch(client)
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
    elif cmd == "paper":
        cmd_paper(args[1:], client)
    elif cmd == "backtest":
        cmd_backtest(client, args[1:])
    else:
        print(red(f"Unknown command: {cmd}"))
        print(dim("Run  py main.py  for the interactive menu."))


if __name__ == "__main__":
    main()
