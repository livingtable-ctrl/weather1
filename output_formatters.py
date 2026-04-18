"""Output formatting functions extracted from main.py.

All functions in this module are pure display helpers: they only call
print() and formatting utilities — no side-effects beyond I/O.
"""

from __future__ import annotations

from tabulate import tabulate

from colors import bold, dim, edge_color, green, prob_color, red, yellow
from kalshi_client import KalshiClient
from tracker import (
    brier_score,
    brier_score_by_method,
    get_calibration_by_city,
    get_calibration_by_type,
    get_calibration_trend,
    get_confusion_matrix,
    get_edge_decay_curve,
    get_history,
    get_market_calibration,
    get_pnl_by_signal_source,
    get_roc_auc,
    get_source_reliability,
    sync_outcomes,
)
from weather_markets import analyze_trade, enrich_with_forecast

# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------


def cmd_history(client: KalshiClient) -> None:  # noqa: PLR0912, PLR0915
    from main import _brier_sparkline  # lazy to avoid circular at import time

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
        sparkline = _brier_sparkline()
        sparkline_str = f"  {dim(sparkline)}" if sparkline else ""
        print(
            f"\n  Brier score: {bold(f'{bs:.4f}')}  {grade}  "
            f"{dim('(0.00=perfect, 0.25=random)')}{sparkline_str}"
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

    # ── Market Calibration ────────────────────────────────────────────────────
    try:
        calib = get_market_calibration()
        buckets = calib.get("buckets", [])
        if buckets:
            print(bold("\n  ── Market Calibration ──"))
            print(
                dim(
                    "  (Are market prices well-calibrated? diff > ±5% = potential edge)"
                )
            )
            cal_rows = []
            for b in buckets:
                diff = b["diff"]
                diff_str = (
                    red(f"{diff:+.0%}  *** edge ***")
                    if abs(diff) > 0.05
                    else dim(f"{diff:+.0%}")
                )
                cal_rows.append(
                    [
                        b["range"],
                        f"{b['market_prob_avg']:.0%}",
                        f"{b['actual_rate']:.0%}",
                        diff_str,
                        b["n"],
                    ]
                )
            print(
                tabulate(
                    cal_rows,
                    headers=["Mkt says", "Actually", "Diff", "Note", "Count"],
                    tablefmt="rounded_outline",
                )
            )
    except Exception:
        pass

    # ── Source reliability ────────────────────────────────────────────────────
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

    # ── Source leaderboard (last 30 days) ─────────────────────────────────────
    method_brier = brier_score_by_method(min_samples=1)
    rel_all = get_source_reliability()
    source_data = []
    for src_key, brier_key in [
        ("nws", "nws"),
        ("ensemble", "ensemble"),
        ("climatology", "climatology"),
    ]:
        src_brier = method_brier.get(brier_key)
        # aggregate reliability across all cities
        total_success, total_all = 0, 0
        for city_name in rel_all:
            s = rel_all[city_name].get(src_key)
            if s:
                total_success += s.get("successes", 0)
                total_all += s.get("total", 0)
        rel_rate = total_success / total_all if total_all else None
        source_data.append((src_key, src_brier, rel_rate))
    # sort by brier (lower is better), None last
    source_data.sort(key=lambda x: x[1] if x[1] is not None else 9999)
    if any(b is not None for _, b, _ in source_data):
        print(bold("\n  ── Source Leaderboard (last 30 days) ──"))
        lb_rows = []
        for rank, (src, src_brier, rel_rate) in enumerate(source_data, 1):
            brier_s = f"{src_brier:.3f}" if src_brier is not None else "—"
            rel_s = f"{rel_rate:.0%}" if rel_rate is not None else "—"
            lb_rows.append([rank, src.capitalize(), brier_s, rel_s])
        print(
            tabulate(
                lb_rows,
                headers=["Rank", "Source", "Brier", "Reliability"],
                tablefmt="rounded_outline",
            )
        )

    # ── Model Analytics ───────────────────────────────────────────────────────
    try:
        print(bold("\n  ── Model Analytics ──"))
        # Confusion matrix
        cm = get_confusion_matrix()
        if cm:
            tp = cm.get("tp", 0)
            fp = cm.get("fp", 0)
            tn = cm.get("tn", 0)
            fn = cm.get("fn", 0)
            precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
            recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
            f1 = (
                2 * precision * recall / (precision + recall)
                if (precision + recall) > 0
                else 0.0
            )
            cm_rows = [
                ["Actual YES", tp, fp],
                ["Actual NO", fn, tn],
            ]
            print(
                tabulate(
                    cm_rows,
                    headers=["", "Pred YES", "Pred NO"],
                    tablefmt="rounded_outline",
                )
            )
            print(
                f"  Precision: {precision:.2%}  |  Recall: {recall:.2%}  |  F1: {f1:.2%}"
            )
        # ROC-AUC
        roc = get_roc_auc()
        if roc and roc.get("auc") is not None:
            auc = roc["auc"]
            auc_color = green if auc >= 0.7 else yellow if auc >= 0.6 else red
            print(f"  ROC-AUC: {auc_color(f'{auc:.3f}')}")
        # Edge decay curve
        decay = get_edge_decay_curve()
        if decay:
            print(bold("\n  Edge decay by days-to-expiry:"))
            decay_rows = []
            for bucket in decay:
                avg_edge = bucket.get("avg_edge", 0.0)
                edge_s = (
                    green(f"{avg_edge:+.1%}")
                    if avg_edge > 0
                    else red(f"{avg_edge:+.1%}")
                    if avg_edge < 0
                    else dim(f"{avg_edge:+.1%}")
                )
                decay_rows.append(
                    [
                        bucket.get("days_label", "?"),
                        edge_s,
                        bucket.get("n", 0),
                    ]
                )
            print(
                tabulate(
                    decay_rows,
                    headers=["Days out", "Avg edge", "N"],
                    tablefmt="rounded_outline",
                )
            )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Balance
# ---------------------------------------------------------------------------


def cmd_balance(client: KalshiClient) -> None:
    from main import validate_api_key  # lazy to avoid circular at import time

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


# ---------------------------------------------------------------------------
# Positions
# ---------------------------------------------------------------------------


def cmd_positions(client: KalshiClient) -> None:
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


# ---------------------------------------------------------------------------
# P&L Attribution
# ---------------------------------------------------------------------------


def cmd_pnl_attribution() -> None:
    """Show P&L attribution by signal source."""
    data = get_pnl_by_signal_source(min_samples=5)
    if not data:
        print("Not enough data per signal source (need 5+ settled per source).")
        return

    print(f"\n{'Signal Source':<20} {'Brier':>8} {'Win%':>8} {'N':>6}")
    print("-" * 46)
    for src, d in sorted(data.items(), key=lambda x: x[1]["brier"]):
        brier = d["brier"]
        color_fn = green if brier < 0.20 else (yellow if brier < 0.25 else red)
        print(
            f"{src:<20} {color_fn(f'{brier:>8.4f}')} {d['win_rate']:>8.1%} {d['n']:>6}"
        )
