"""
Local web dashboard — run with: py main.py web
Opens a browser tab showing the analyze table, open positions, and P&L chart.
"""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime

_app = None  # module-level Flask app
_client = None  # module-level Kalshi client reference

_RANGE_DAYS = {"1mo": 30, "3mo": 90, "1yr": 365}
_DEFAULT_HISTORY_POINTS = 50


def _now_utc():
    """Mockable UTC timestamp for tests."""
    from datetime import UTC, datetime

    return datetime.now(UTC)


def _get_live_market_snapshot(max_markets: int = 5) -> list[dict]:
    """Return cached top market snapshot for SSE. Populated by analyze route."""
    try:
        return list(getattr(_get_live_market_snapshot, "_cache", []))[:max_markets]
    except Exception:
        return []


def _build_stream_data() -> dict:
    """Build SSE payload. Extracted for testability."""
    from datetime import UTC, datetime

    from paper import get_balance, get_open_trades
    from tracker import brier_score

    return {
        "balance": round(get_balance(), 2),
        "open_count": len(get_open_trades()),
        "brier": brier_score(),
        "markets": _get_live_market_snapshot(),
        "ts": datetime.now(UTC).isoformat(),
    }


def _build_app(client):
    """Build and return the Flask app."""
    try:
        from flask import (
            Flask,
            Response,
            jsonify,
            render_template,
            render_template_string,
            stream_with_context,
        )
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
      .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; margin-bottom: 20px; }
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
      .live-dot { display: inline-block; width: 7px; height: 7px; border-radius: 50%; background: #3fb950; margin-right: 5px; animation: blink 1.5s infinite; }
      .live-dot.stale { background: #e3b341; }
      @keyframes blink { 0%,100%{opacity:1} 50%{opacity:0.3} }
      #last-updated { color: #8b949e; font-size: 0.78em; margin-left: 6px; }
      /* Responsive */
      @media (max-width: 768px) {
        body { padding: 12px; }
        table { font-size: 0.78em; }
        th, td { padding: 5px 6px; }
        .stats { grid-template-columns: repeat(2, 1fr); }
        h1 { font-size: 1.2em; }
        nav a { margin-right: 10px; font-size: 0.9em; }
      }
      @media (max-width: 480px) {
        /* #88: single-column on very small screens */
        .stats { grid-template-columns: 1fr; }
        table { display: block; overflow-x: auto; -webkit-overflow-scrolling: touch; }
        nav a { display: inline-block; margin: 2px 6px; }
      }
      /* #87: light mode support */
      @media (prefers-color-scheme: light) {
        body { background: #ffffff; color: #1a1a1a; }
        h1 { color: #0969da; }
        h2 { color: #57606a; border-bottom-color: #d0d7de; }
        th { background: #f6f8fa; color: #57606a; border-bottom-color: #d0d7de; }
        td { border-bottom-color: #eaeef2; }
        tr:hover { background: #f6f8fa; }
        .stat-card { background: #f6f8fa; border-color: #d0d7de; }
        .stat-label { color: #57606a; }
        nav a { color: #57606a; }
        .refreshing { color: #57606a; }
      }
      /* Light mode toggle button */
      #theme-toggle { position: fixed; top: 14px; right: 16px; background: #21262d;
        border: 1px solid #30363d; color: #8b949e; border-radius: 6px;
        padding: 4px 10px; cursor: pointer; font-size: 0.8em; }
    </style>
    <script>
    // #87: persist user theme preference
    (function() {
      const saved = localStorage.getItem('theme');
      if (saved) document.documentElement.setAttribute('data-theme', saved);
    })();
    </script>
    """

    VIEWPORT = '<meta name="viewport" content="width=device-width, initial-scale=1.0">'

    NAV = """
    <nav>
      <a href="/">Dashboard</a>
      <a href="/analyze">Analyze</a>
      <a href="/analytics">Analytics</a>
      <a href="/history">History</a>
      <a href="/api/export" download>Export CSV</a>
    </nav>
    <button id="theme-toggle" onclick="(function(){
      const cur = localStorage.getItem('theme');
      const next = cur === 'light' ? 'dark' : 'light';
      localStorage.setItem('theme', next);
      location.reload();
    })()">&#9680; Theme</button>
    """

    @app.route("/health")
    def health():
        return jsonify({"status": "ok", "timestamp": datetime.now(UTC).isoformat()})

    @app.route("/api/stream")
    def stream():
        """Server-Sent Events endpoint — pushes portfolio status every 10s."""
        import time

        def generate():
            while True:
                try:
                    data = _build_stream_data()
                    yield f"data: {json.dumps(data)}\n\n"
                except Exception:
                    yield "data: {}\n\n"
                time.sleep(10)

        return Response(
            stream_with_context(generate()),
            content_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.route("/api/stream/markets")
    def stream_markets():
        """#85 — SSE endpoint that yields open-market snapshots every 10 s."""
        import time

        def generate():
            while True:
                try:
                    payload = {
                        "markets": _get_live_market_snapshot(),
                        "ts": datetime.now(UTC).isoformat(),
                    }
                    yield f"data: {json.dumps(payload)}\n\n"
                except Exception:
                    yield "data: {}\n\n"
                time.sleep(10)

        return Response(
            stream_with_context(generate()),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.route("/api/balance_history")
    def balance_history():
        from datetime import timedelta

        from flask import request

        from paper import get_balance_history

        history = get_balance_history()
        range_param = request.args.get("range", "")

        if range_param == "all":
            points = history
        elif range_param in _RANGE_DAYS:
            cutoff = _now_utc() - timedelta(days=_RANGE_DAYS[range_param])
            filtered = []
            for p in history:
                ts = p.get("ts", "")
                if not ts:  # "Start" sentinel — always include
                    filtered.append(p)
                    continue
                try:
                    from datetime import UTC, datetime

                    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=UTC)
                    if dt >= cutoff:
                        filtered.append(p)
                except (ValueError, TypeError):
                    filtered.append(p)
            points = filtered
        else:
            # default (empty or invalid range): last N points
            points = history[-_DEFAULT_HISTORY_POINTS:]

        return jsonify(
            {
                "labels": [(p.get("ts") or "")[:16] or "Start" for p in points],
                "values": [p["balance"] for p in points],
            }
        )

    @app.route("/api/analytics")
    def api_analytics():
        try:
            from tracker import (
                brier_score,
                get_brier_by_days_out,
                get_calibration_by_city,
                get_component_attribution,
            )

            result: dict = {
                "brier": brier_score(),
                "brier_by_days": get_brier_by_days_out(),
                "city_calibration": get_calibration_by_city(),
                "component_attribution": get_component_attribution(),
            }
            for fn_name in (
                "get_confusion_matrix",
                "get_roc_auc",
                "get_edge_decay_curve",
                "get_model_calibration_buckets",
            ):
                try:
                    import tracker as _t

                    fn = getattr(_t, fn_name, None)
                    if fn:
                        result[fn_name.replace("get_", "")] = fn()
                except Exception:
                    pass
            for fn_name in (
                "get_rolling_sharpe",
                "get_attribution",
                "get_factor_exposure",
            ):
                try:
                    import paper as _p

                    fn = getattr(_p, fn_name, None)
                    if fn:
                        result[fn_name.replace("get_", "")] = fn()
                except Exception:
                    pass
        except Exception as e:
            result = {"error": str(e)}
        return jsonify(result)

    @app.route("/api/model-attribution")
    def model_attribution():
        """#84 — per-city average model blend weights."""
        try:
            from tracker import get_model_attribution_by_city

            data = get_model_attribution_by_city()
            return jsonify(data)
        except Exception as exc:  # noqa: BLE001
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/live-pnl")
    def api_live_pnl():
        try:
            from execution_log import get_live_pnl_summary

            return jsonify(get_live_pnl_summary())
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/api/graduation")
    def api_graduation():
        try:
            from paper import fear_greed_index, get_performance, graduation_check
        except ImportError as e:
            return jsonify({"error": str(e)}), 500
        perf = get_performance()
        gc = graduation_check()
        fg_score, fg_label = fear_greed_index()
        return jsonify(
            {
                "trades_done": perf.get("settled", 0),
                "win_rate": perf.get("win_rate"),
                "ready": gc is not None,
                "fear_greed_score": fg_score,
                "fear_greed_label": fg_label,
            }
        )

    @app.route("/api/brier_history")
    def api_brier_history():
        try:
            from tracker import get_brier_over_time

            return jsonify(get_brier_over_time(weeks=12))
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/")
    def index():
        return render_template("dashboard.html")

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
                f"<!DOCTYPE html><html><head>{VIEWPORT}{DARK_STYLE}</head><body>"
                f"<h1>Analyze</h1>{NAV}"
                f"<p class='neg'>Could not fetch markets: {e}</p></body></html>"
            )

        rows_html = ""
        opps = []
        from utils import MIN_EDGE

        for m in markets:
            try:
                enriched = enrich_with_forecast(m)
                analysis = analyze_trade(enriched)
                if (
                    analysis
                    and abs(analysis.get("net_edge", analysis["edge"])) >= MIN_EDGE
                ):
                    opps.append((enriched, analysis))
            except Exception:
                continue

        opps.sort(key=lambda x: abs(x[1].get("net_edge", x[1]["edge"])), reverse=True)

        # NOTE: This is read by _get_live_market_snapshot() for SSE. Under multi-process WSGI,
        # each process has its own cache — only the most recently analyzed process updates live data.
        _get_live_market_snapshot._cache = [  # type: ignore[attr-defined]
            {
                "ticker": m.get("ticker", ""),
                "yes_ask": m.get("yes_ask", 0),
                "edge": a.get("net_edge", a.get("edge", 0)),
            }
            for m, a in sorted(
                opps,
                key=lambda x: x[1].get("net_edge", x[1].get("edge", 0)),
                reverse=True,
            )
            if a.get("net_edge", a.get("edge", 0)) > 0
        ][:10]

        from paper import get_balance as _get_balance

        _balance = _get_balance()

        for m, a in opps:
            net_edge = a.get("net_edge", a["edge"])
            edge_cls = "pos" if net_edge > 0 else "neg"
            edge_str = f"+{net_edge:.0%}" if net_edge > 0 else f"{net_edge:.0%}"
            ticker = m.get("ticker", "")
            kelly = a.get(
                "ci_adjusted_kelly", a.get("fee_adjusted_kelly", a.get("kelly", 0))
            )
            bet_amount = kelly * _balance
            bet_cell = f"${bet_amount:.2f}" if bet_amount >= 0.05 else "—"
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
              <td>{bet_cell}</td>
              <td>{side_badge}</td>
            </tr>"""

        top_bets_card = """<div id="top-bets-card" style="background:#161b22;border:1px solid #21262d;border-radius:8px;padding:16px;margin-bottom:20px">
  <h2 style="margin:0 0 12px 0;font-size:1.1em">Today&rsquo;s Top Bets</h2>
  <div id="top-bets-body" style="font-size:0.9em;color:#8b949e">Loading&hellip;</div>
</div>
<script>
function esc(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
fetch('/api/suggested_bets?n=3')
  .then(r => r.json())
  .then(data => {
    const el = document.getElementById('top-bets-body');
    if (!data.bets || data.bets.length === 0) {
      el.textContent = 'No strong bets today.';
      return;
    }
    const rows = data.bets.map((b, i) => {
      const badge = b.recommended_side === 'YES'
        ? '<span class="badge badge-green">YES</span>'
        : '<span class="badge badge-red">NO</span>';
      return '<div style="display:flex;gap:16px;align-items:center;padding:6px 0;border-bottom:1px solid #21262d">'
        + '<span style="font-weight:bold;color:#8b949e;min-width:24px">#' + (i+1) + '</span>'
        + '<span style="flex:1;font-family:monospace">' + esc(b.ticker) + '</span>'
        + '<span style="flex:2;color:#c9d1d9">' + esc(b.title) + '</span>'
        + badge
        + '<span class="pos">+' + b.edge_pct + '%</span>'
        + '<span style="font-weight:bold;color:#4ade80">Bet $' + b.suggested_dollars.toFixed(2) + '</span>'
        + '</div>';
    }).join('');
    el.innerHTML = rows + '<p style="margin-top:8px;font-size:0.82em;color:#8b949e">Balance: $'
      + data.balance.toFixed(2) + ' &mdash; Min edge: ' + (data.min_edge*100).toFixed(0) + '%</p>';
  })
  .catch(() => {
    document.getElementById('top-bets-body').textContent = 'Could not load suggestions.';
  });
</script>"""

        html = f"""<!DOCTYPE html>
<html><head><title>Analyze — Kalshi</title>{VIEWPORT}{DARK_STYLE}</head>
<body>
<h1>Kalshi Weather — Opportunities</h1>
{NAV}
{top_bets_card}
<p class="refreshing" id="analyze-status">
  {
            len(opps)
        } opportunities found &mdash; refreshing in <span id="analyze-countdown">60</span>s
</p>
<script>
// #90: auto-refresh analyze table every 60 seconds
let _analyzeCountdown = 60;
const _cdEl = document.getElementById('analyze-countdown');
setInterval(() => {{
  _analyzeCountdown--;
  if (_cdEl) _cdEl.textContent = _analyzeCountdown;
  if (_analyzeCountdown <= 0) {{
    fetch('/analyze?fragment=1').then(r => r.text()).then(html => {{
      const parser = new DOMParser();
      const doc = parser.parseFromString(html, 'text/html');
      const newTable = doc.querySelector('table');
      const oldTable = document.querySelector('table');
      if (newTable && oldTable) oldTable.replaceWith(newTable);
      _analyzeCountdown = 60;
    }}).catch(() => {{ _analyzeCountdown = 60; }});
  }}
}}, 1000);
</script>
{
            "<p class='neu' style='margin-top:16px'>No opportunities above threshold right now.</p>"
            if not opps
            else f'''
<table style="margin-top:16px">
  <tr><th>Ticker</th><th>Question</th><th>City</th><th>We Think</th><th>Mkt Says</th>
      <th>Edge</th><th>Risk</th><th>Bet</th><th>Buy</th></tr>
  {rows_html}
</table>'''
        }
<p class="refreshing" style="margin-top:12px">Generated at {
            datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
        } UTC &mdash; <a href="/analyze">Refresh</a></p>
</body></html>"""
        return render_template_string(html)

    @app.route("/api/suggested_bets")
    def api_suggested_bets():
        """Return top-N trade opportunities ranked by expected value (edge × kelly $)."""

        from flask import request as freq

        from paper import get_balance
        from utils import MIN_EDGE
        from weather_markets import (
            analyze_trade,
            enrich_with_forecast,
            get_weather_markets,
        )

        n = int(freq.args.get("n", 3))

        try:
            markets = get_weather_markets(client)
        except Exception as e:
            return jsonify({"error": str(e), "bets": []}), 500

        balance = get_balance()
        candidates = []

        for m in markets:
            try:
                enriched = enrich_with_forecast(m)
                analysis = analyze_trade(enriched)
                if not analysis:
                    continue
                net_edge = abs(analysis.get("net_edge", analysis.get("edge", 0)))
                if net_edge < MIN_EDGE:
                    continue
                kelly = analysis.get(
                    "ci_adjusted_kelly",
                    analysis.get("fee_adjusted_kelly", analysis.get("kelly", 0)),
                )
                kelly_dollars = round(kelly * balance, 2)
                ev_score = net_edge * kelly_dollars
                candidates.append(
                    {
                        "ticker": m.get("ticker", ""),
                        "title": (m.get("title") or m.get("ticker", ""))[:60],
                        "city": m.get("_city", "—"),
                        "recommended_side": analysis.get(
                            "recommended_side", "—"
                        ).upper(),
                        "edge_pct": round(net_edge * 100, 1),
                        "kelly_fraction": round(kelly, 4),
                        "suggested_dollars": kelly_dollars,
                        "signal": analysis.get("signal", "—"),
                        "ev_score": round(ev_score, 4),
                    }
                )
            except Exception:
                continue

        candidates.sort(key=lambda x: x["ev_score"], reverse=True)
        top = candidates[:n]
        for bet in top:
            del bet["ev_score"]

        return jsonify(
            {
                "bets": top,
                "balance": round(balance, 2),
                "min_edge": MIN_EDGE,
                "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S"),
            }
        )

    @app.route("/analytics")
    def analytics_page():
        """Analytics page — model calibration, confusion matrix, edge decay."""
        return render_template("analytics.html")

    @app.route("/history")
    def history_page():
        """#89: Paginated settled trade history."""
        try:
            from flask import request as freq

            page = max(1, int(freq.args.get("page", 1)))
        except Exception:
            page = 1

        try:
            from paper import get_all_trades

            all_settled = [t for t in get_all_trades() if t.get("settled")]
            all_settled.sort(key=lambda t: t.get("entered_at", ""), reverse=True)
        except Exception:
            all_settled = []

        per_page = 25
        total = len(all_settled)
        total_pages = max(1, (total + per_page - 1) // per_page)
        page = min(page, total_pages)
        start = (page - 1) * per_page
        page_trades = all_settled[start : start + per_page]

        rows_html = ""
        for t in page_trades:
            p = t.get("pnl", 0.0) or 0.0
            p_cls = "pos" if p >= 0 else "neg"
            p_str = f"+${p:.2f}" if p >= 0 else f"-${abs(p):.2f}"
            rows_html += f"""<tr>
              <td>{t["id"]}</td>
              <td>{t["ticker"][:28]}</td>
              <td>{"YES" if t["side"] == "yes" else "NO"}</td>
              <td>{t["quantity"]}</td>
              <td>${t["entry_price"]:.3f}</td>
              <td>${t["cost"]:.2f}</td>
              <td class="{p_cls}">{p_str}</td>
              <td class="neu">{t.get("entered_at", "")[:10]}</td>
            </tr>"""

        prev_link = (
            f'<a href="/history?page={page - 1}">&laquo; Prev</a>' if page > 1 else ""
        )
        next_link = (
            f'<a href="/history?page={page + 1}">Next &raquo;</a>'
            if page < total_pages
            else ""
        )

        html = f"""<!DOCTYPE html>
<html><head><title>Trade History</title>{VIEWPORT}{DARK_STYLE}</head>
<body>{NAV}
<h1>Settled Trade History</h1>
<p class="refreshing">{total} trades &mdash; Page {page} of {total_pages}</p>
<table>
  <tr><th>#</th><th>Ticker</th><th>Side</th><th>Qty</th><th>Entry</th><th>Cost</th><th>P&amp;L</th><th>Date</th></tr>
  {rows_html}
</table>
<p style="margin-top:12px">{prev_link} &nbsp; {next_link}</p>
</body></html>"""
        return render_template_string(html)

    @app.route("/api/export")
    def api_export():
        """#83: Download CSV of prediction history with outcomes."""
        import io

        buf = io.StringIO()
        try:
            from tracker import get_history

            rows = get_history(limit=10_000)
            if not rows:
                return Response("No data", status=204)
            import csv as _csv

            writer = _csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        except Exception as exc:
            return Response(f"Error: {exc}", status=500)

        return Response(
            buf.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": 'attachment; filename="predictions.csv"'},
        )

    @app.route("/trades")
    def trades_page():
        return render_template("trades.html")

    @app.route("/api/trades")
    def api_trades():
        try:
            from paper import get_all_trades, get_open_trades
        except ImportError as e:
            return jsonify({"error": str(e)}), 500

        open_trades = get_open_trades()

        # Enrich open trades with current implied prob from SSE snapshot
        snapshot = {m["ticker"]: m for m in _get_live_market_snapshot()}
        for t in open_trades:
            snap = snapshot.get(t.get("ticker", ""), {})
            t["current_yes_ask"] = snap.get("yes_ask")

        all_trades = get_all_trades()
        closed = [t for t in all_trades if t.get("settled")]

        return jsonify({"open": open_trades, "closed": closed})

    @app.route("/risk")
    def risk_page():
        return render_template("risk.html")

    @app.route("/api/risk")
    def api_risk():
        try:
            from paper import (
                check_aged_positions,
                check_correlated_event_exposure,
                get_expiry_date_clustering,
                get_open_trades,
                get_total_exposure,
            )
        except ImportError as e:
            return jsonify({"error": str(e)}), 500

        trades = get_open_trades()

        # Aggregate city exposure and directional bias from open trades
        city_exp: dict[str, float] = {}
        yes_exp = 0.0
        no_exp = 0.0
        for t in trades:
            city = t.get("city") or "Unknown"
            cost = float(t.get("cost") or 0.0)
            city_exp[city] = city_exp.get(city, 0.0) + cost
            if t.get("side") == "yes":
                yes_exp += cost
            else:
                no_exp += cost

        city_exposure = sorted(
            [{"city": c, "exposure": round(v, 4)} for c, v in city_exp.items()],
            key=lambda x: float(x["exposure"]),  # type: ignore[arg-type]
            reverse=True,
        )

        return jsonify(
            {
                "city_exposure": city_exposure,
                "directional": {"yes": round(yes_exp, 4), "no": round(no_exp, 4)},
                "expiry_clustering": get_expiry_date_clustering(),
                "total_exposure": round(get_total_exposure(), 4),
                "aged_positions": check_aged_positions(),
                "correlated_events": check_correlated_event_exposure(),
            }
        )

    @app.route("/api/price-improvement")
    def price_improvement():
        """#65 — aggregate price improvement stats."""
        try:
            from tracker import get_price_improvement_stats

            stats = get_price_improvement_stats()
            if stats is None:
                return jsonify(
                    {
                        "avg_improvement_cents": None,
                        "total_trades": 0,
                        "note": "insufficient data (< 5 trades)",
                    }
                )
            avg_cents = round(stats["mean"] * 100, 4)
            return jsonify(
                {
                    "avg_improvement_cents": avg_cents,
                    "total_trades": stats["count"],
                    "median_improvement_cents": round(stats["median"] * 100, 4),
                    "positive_pct": stats["positive_pct"],
                }
            )
        except Exception as exc:  # noqa: BLE001
            return jsonify({"error": str(exc)}), 500

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

    @app.route("/signals")
    def signals_page():
        return render_template("signals.html")

    @app.route("/api/signals")
    def api_signals():
        import pathlib

        cron_log = pathlib.Path("data/cron.log")
        entries = []
        if cron_log.exists():
            try:
                with open(cron_log, encoding="utf-8") as f:
                    lines = f.readlines()
                for line in lines[-200:]:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entries.append(json.loads(line))
                    except Exception:
                        pass
            except Exception:
                pass

        alerts = [
            e
            for e in entries
            if e.get("signal") == "ALERT" or e.get("level") in ("WARNING", "ERROR")
        ]

        return jsonify({"log": entries, "alerts": alerts[-50:]})

    @app.route("/forecast")
    def forecast_page():
        return render_template("forecast.html")

    @app.route("/api/forecast_quality")
    def api_forecast_quality():
        city_cal = {}
        try:
            from tracker import get_calibration_by_city

            city_cal = get_calibration_by_city() or {}
        except Exception:
            pass

        ensemble_accuracy = {}
        try:
            from tracker import get_ensemble_member_accuracy

            acc = get_ensemble_member_accuracy()
            if acc:
                ensemble_accuracy = acc
        except Exception:
            pass

        return jsonify(
            {
                "city_heatmap": city_cal,
                "source_reliability": ensemble_accuracy,
            }
        )

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
