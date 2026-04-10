"""
Local web dashboard — run with: py main.py web
Opens a browser tab showing the analyze table, open positions, and P&L chart.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime

_app = None  # module-level Flask app
_client = None  # module-level Kalshi client reference


def _build_app(client):
    """Build and return the Flask app."""
    try:
        from flask import Flask, jsonify, render_template_string
    except ImportError:
        return None

    app = Flask(__name__)

    DARK_STYLE = """
    <style>
      * { box-sizing: border-box; margin: 0; padding: 0; }
      body { background: #0d1117; color: #c9d1d9; font-family: 'Consolas', monospace; padding: 20px; }
      h1 { color: #58a6ff; margin-bottom: 10px; font-size: 1.4em; }
      h2 { color: #8b949e; font-size: 1.1em; margin: 20px 0 8px; border-bottom: 1px solid #21262d; padding-bottom: 6px; }
      table { width: 100%; border-collapse: collapse; margin-bottom: 20px; font-size: 0.88em; }
      th { background: #161b22; color: #8b949e; padding: 8px 12px; text-align: left; border-bottom: 2px solid #21262d; }
      td { padding: 7px 12px; border-bottom: 1px solid #21262d; }
      tr:hover { background: #161b22; }
      .pos { color: #3fb950; }
      .neg { color: #f85149; }
      .neu { color: #8b949e; }
      .badge { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 0.8em; }
      .badge-green { background: #1a3a1f; color: #3fb950; }
      .badge-red { background: #3a1a1a; color: #f85149; }
      .badge-yellow { background: #3a3a1a; color: #e3b341; }
      .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin-bottom: 20px; }
      .stat-card { background: #161b22; border: 1px solid #21262d; border-radius: 8px; padding: 14px; }
      .stat-label { color: #8b949e; font-size: 0.78em; text-transform: uppercase; letter-spacing: 0.05em; }
      .stat-value { font-size: 1.5em; font-weight: bold; margin-top: 4px; }
      a { color: #58a6ff; text-decoration: none; }
      a:hover { text-decoration: underline; }
      nav { margin-bottom: 20px; }
      nav a { margin-right: 16px; color: #8b949e; }
      nav a:hover, nav a.active { color: #58a6ff; }
      .warning { background: #3a3a1a; border: 1px solid #e3b341; border-radius: 6px; padding: 10px 14px; margin-bottom: 16px; color: #e3b341; }
      .refreshing { color: #8b949e; font-size: 0.8em; }
    </style>
    """

    NAV = """
    <nav>
      <a href="/">Dashboard</a>
      <a href="/analyze">Analyze</a>
      <a href="/api/status">API Status</a>
    </nav>
    """

    @app.route("/")
    def index():
        from paper import get_all_trades, get_balance, get_open_trades, get_performance
        from tracker import brier_score

        balance = get_balance()
        perf = get_performance()
        open_trades = get_open_trades()
        all_trades = get_all_trades()
        bs = brier_score()
        settled = [t for t in all_trades if t.get("settled")][-10:]

        pnl = perf.get("total_pnl", 0.0)
        wr = perf.get("win_rate")
        pnl_cls = "pos" if pnl >= 0 else "neg"
        pnl_str = f"+${pnl:.2f}" if pnl >= 0 else f"-${abs(pnl):.2f}"
        wr_str = f"{wr:.0%}" if wr is not None else "—"
        bs_str = f"{bs:.4f}" if bs is not None else "—"

        open_rows = ""
        for t in open_trades:
            ep = f"${t['entry_price']:.3f}"
            cost = f"${t['cost']:.2f}"
            side_badge = (
                '<span class="badge badge-green">YES</span>'
                if t["side"] == "yes"
                else '<span class="badge badge-red">NO</span>'
            )
            open_rows += f"""
            <tr>
              <td>{t["id"]}</td>
              <td>{t["ticker"][:30]}</td>
              <td>{side_badge}</td>
              <td>{t["quantity"]}</td>
              <td>{ep}</td>
              <td>{cost}</td>
              <td class="neu">{t.get("city", "—")}</td>
              <td class="neu">{t.get("target_date", "—")}</td>
            </tr>"""

        settled_rows = ""
        for t in reversed(settled):
            p = t.get("pnl", 0.0) or 0.0
            p_cls = "pos" if p >= 0 else "neg"
            p_str = f"+${p:.2f}" if p >= 0 else f"-${abs(p):.2f}"
            outcome_badge = (
                '<span class="badge badge-green">YES</span>'
                if t.get("outcome") == "yes"
                else '<span class="badge badge-red">NO</span>'
                if t.get("outcome") == "no"
                else "—"
            )
            settled_rows += f"""
            <tr>
              <td>{t["id"]}</td>
              <td>{t["ticker"][:28]}</td>
              <td>{t["side"].upper()}</td>
              <td>{outcome_badge}</td>
              <td class="{p_cls}">{p_str}</td>
            </tr>"""

        html = f"""<!DOCTYPE html>
<html><head><title>Kalshi Dashboard</title>{DARK_STYLE}</head>
<body>
<h1>Kalshi Weather — Dashboard</h1>
{NAV}
<div class="stats">
  <div class="stat-card"><div class="stat-label">Paper Balance</div>
    <div class="stat-value pos">${balance:.2f}</div></div>
  <div class="stat-card"><div class="stat-label">Open Trades</div>
    <div class="stat-value">{len(open_trades)}</div></div>
  <div class="stat-card"><div class="stat-label">Total P&amp;L</div>
    <div class="stat-value {pnl_cls}">{pnl_str}</div></div>
  <div class="stat-card"><div class="stat-label">Win Rate</div>
    <div class="stat-value">{wr_str}</div></div>
  <div class="stat-card"><div class="stat-label">Brier Score</div>
    <div class="stat-value">{bs_str}</div></div>
</div>

<h2>Open Positions ({len(open_trades)})</h2>
{
            "<p class='neu'>No open positions.</p>"
            if not open_trades
            else f'''
<table>
  <tr><th>#</th><th>Ticker</th><th>Side</th><th>Qty</th><th>Entry</th><th>Cost</th><th>City</th><th>Date</th></tr>
  {open_rows}
</table>'''
        }

<h2>Recent Settled Trades (last 10)</h2>
{
            "<p class='neu'>No settled trades yet.</p>"
            if not settled
            else f'''
<table>
  <tr><th>#</th><th>Ticker</th><th>Side</th><th>Outcome</th><th>P&amp;L</th></tr>
  {settled_rows}
</table>'''
        }

<p class="refreshing">Generated at {
            datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
        } UTC</p>
</body></html>"""
        return render_template_string(html)

    @app.route("/analyze")
    def analyze():
        from weather_markets import (
            analyze_trade,
            enrich_with_forecast,
            get_weather_markets,
        )

        try:
            markets = get_weather_markets(client)
        except Exception as e:
            return render_template_string(
                f"<!DOCTYPE html><html><head>{DARK_STYLE}</head><body>"
                f"<h1>Analyze</h1>{NAV}"
                f"<p class='neg'>Could not fetch markets: {e}</p></body></html>"
            )

        rows_html = ""
        opps = []
        for m in markets:
            try:
                enriched = enrich_with_forecast(m)
                analysis = analyze_trade(enriched)
                if analysis and abs(analysis.get("net_edge", analysis["edge"])) >= 0.08:
                    opps.append((enriched, analysis))
            except Exception:
                continue

        opps.sort(key=lambda x: abs(x[1].get("net_edge", x[1]["edge"])), reverse=True)

        for m, a in opps:
            net_edge = a.get("net_edge", a["edge"])
            edge_cls = "pos" if net_edge > 0 else "neg"
            edge_str = f"+{net_edge:.0%}" if net_edge > 0 else f"{net_edge:.0%}"
            ticker = m.get("ticker", "")
            side_badge = (
                '<span class="badge badge-green">YES</span>'
                if a["recommended_side"] == "yes"
                else '<span class="badge badge-red">NO</span>'
            )
            rows_html += f"""
            <tr>
              <td>{ticker}</td>
              <td>{(m.get("title") or ticker)[:38]}</td>
              <td>{m.get("_city", "—")}</td>
              <td>{a["forecast_prob"]:.0%}</td>
              <td>{a["market_prob"]:.0%}</td>
              <td class="{edge_cls}">{edge_str}</td>
              <td>{a.get("time_risk", "—")}</td>
              <td>{side_badge}</td>
            </tr>"""

        refresh_meta = '<meta http-equiv="refresh" content="60">'
        html = f"""<!DOCTYPE html>
<html><head><title>Analyze — Kalshi</title>{DARK_STYLE}{refresh_meta}</head>
<body>
<h1>Kalshi Weather — Opportunities</h1>
{NAV}
<p class="refreshing">Auto-refreshes every 60s &mdash; {
            len(opps)
        } opportunities found</p>
{
            "<p class='neu' style='margin-top:16px'>No opportunities above 8% edge threshold right now.</p>"
            if not opps
            else f'''
<table style="margin-top:16px">
  <tr><th>Ticker</th><th>Question</th><th>City</th><th>We Think</th><th>Mkt Says</th>
      <th>Edge</th><th>Risk</th><th>Buy</th></tr>
  {rows_html}
</table>'''
        }
<p class="refreshing" style="margin-top:12px">Generated at {
            datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
        } UTC</p>
</body></html>"""
        return render_template_string(html)

    @app.route("/api/status")
    def api_status():
        try:
            from paper import get_balance, get_open_trades
            from tracker import brier_score

            try:
                from paper import fear_greed_index

                fg_score, fg_label = fear_greed_index()
            except Exception:
                fg_score, fg_label = None, None

            data = {
                "balance": round(get_balance(), 2),
                "open_count": len(get_open_trades()),
                "brier": brier_score(),
                "fear_greed_score": fg_score,
                "fear_greed_label": fg_label,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        except Exception as e:
            data = {"error": str(e)}
        return jsonify(data)

    return app


def start_web(client, port: int = 5000, open_browser: bool = True) -> None:
    """Start the Flask web dashboard."""
    try:
        import flask  # noqa: F401
    except ImportError:
        print("Install Flask first:  pip install flask")
        return

    global _app, _client
    _client = client
    _app = _build_app(client)
    if _app is None:
        print("Could not build Flask app.")
        return

    if open_browser:
        import webbrowser

        def _open():
            import time

            time.sleep(1.0)
            webbrowser.open(f"http://localhost:{port}")

        threading.Thread(target=_open, daemon=True).start()

    print(f"  Web dashboard running at http://localhost:{port}")
    print("  Press Ctrl+C to stop.\n")
    # Suppress Flask startup banner
    import logging

    log = logging.getLogger("werkzeug")
    log.setLevel(logging.ERROR)
    _app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False)
