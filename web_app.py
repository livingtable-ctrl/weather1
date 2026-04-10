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

    @app.route("/api/balance_history")
    def balance_history():
        from datetime import timedelta

        from flask import request

        from paper import get_balance_history

        history = get_balance_history()
        range_param = request.args.get("range", "")
        _RANGE_DAYS = {"1mo": 30, "3mo": 90, "1yr": 365}

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
            # default (empty or invalid range): last 50 points
            points = history[-50:]

        return jsonify(
            {
                "labels": [p["ts"][:16] or "Start" for p in points],
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

        sse_js = """
<script>
// #86: track SSE connection health and show "last updated X seconds ago"
let _lastSseTs = null;
const _dot = document.querySelector('.live-dot');
setInterval(() => {
  if (_lastSseTs === null) return;
  const secs = Math.round((Date.now() - _lastSseTs) / 1000);
  const el = document.getElementById('last-updated');
  if (el) {
    el.textContent = secs < 5 ? 'just now' : secs + 's ago';
  }
  if (_dot) {
    _dot.classList.toggle('stale', secs > 30);
  }
}, 1000);

const es = new EventSource('/api/stream');
es.onmessage = (e) => {
  try {
    _lastSseTs = Date.now();
    const d = JSON.parse(e.data);
    if (d.balance !== undefined) {
      const el = document.getElementById('stat-balance');
      if (el) el.textContent = '$' + d.balance.toFixed(2);
    }
    if (d.open_count !== undefined) {
      const el = document.getElementById('stat-open');
      if (el) el.textContent = d.open_count;
    }
    if (d.brier !== null && d.brier !== undefined) {
      const el = document.getElementById('stat-brier');
      if (el) el.textContent = d.brier.toFixed(4);
    }
    const upd = document.getElementById('stat-updated');
    if (upd) upd.textContent = 'Live \u2014 ' + new Date().toLocaleTimeString();
  } catch(err) {}
};
</script>"""

        chart_js = """
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<script>
var _balanceChart = null;
function loadBalanceChart(range) {
  var url = '/api/balance_history' + (range ? '?range=' + range : '');
  fetch(url).then(r=>r.json()).then(data => {
    const ctx = document.getElementById('balanceChart');
    if (!ctx) return;
    if (_balanceChart) { _balanceChart.destroy(); _balanceChart = null; }
    _balanceChart = new Chart(ctx, {
      type: 'line',
      data: {
        labels: data.labels,
        datasets: [{
          label: 'Balance ($)',
          data: data.values,
          borderColor: '#58a6ff',
          backgroundColor: 'rgba(88,166,255,0.08)',
          fill: true,
          tension: 0.3,
          pointRadius: 0,
          borderWidth: 2,
        }]
      },
      options: {
        responsive: true,
        plugins: { legend: { display: false } },
        scales: {
          x: { display: false },
          y: {
            ticks: { color: '#8b949e', callback: v => '$'+v },
            grid: { color: '#21262d' }
          }
        }
      }
    });
    // Highlight active button
    document.querySelectorAll('.range-btn').forEach(b => {
      b.style.opacity = b.dataset.range === (range||'') ? '1' : '0.5';
    });
  }).catch(()=>{});
}
loadBalanceChart('');
</script>"""

        html = f"""<!DOCTYPE html>
<html><head><title>Kalshi Dashboard</title>{VIEWPORT}{DARK_STYLE}</head>
<body>
<h1>Kalshi Weather — Dashboard</h1>
{NAV}
<div class="stats">
  <div class="stat-card"><div class="stat-label">Paper Balance</div>
    <div class="stat-value pos" id="stat-balance">${balance:.2f}</div></div>
  <div class="stat-card"><div class="stat-label">Open Trades</div>
    <div class="stat-value" id="stat-open">{len(open_trades)}</div></div>
  <div class="stat-card"><div class="stat-label">Total P&amp;L</div>
    <div class="stat-value {pnl_cls}">{pnl_str}</div></div>
  <div class="stat-card"><div class="stat-label">Win Rate</div>
    <div class="stat-value">{wr_str}</div></div>
  <div class="stat-card"><div class="stat-label">Brier Score</div>
    <div class="stat-value" id="stat-brier">{bs_str}</div></div>
</div>
<p class="refreshing"><span class="live-dot"></span><span id="stat-updated">Connecting…</span><span id="last-updated"></span></p>

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

<h2>Balance History</h2>
<div style="max-width:800px; margin-bottom:8px">
  <button class="range-btn" data-range="" onclick="loadBalanceChart('')" style="background:#21262d;border:1px solid #30363d;color:#8b949e;border-radius:4px;padding:3px 10px;cursor:pointer;margin-right:4px;font-size:0.8em">Default</button>
  <button class="range-btn" data-range="1mo" onclick="loadBalanceChart('1mo')" style="background:#21262d;border:1px solid #30363d;color:#8b949e;border-radius:4px;padding:3px 10px;cursor:pointer;margin-right:4px;font-size:0.8em">1mo</button>
  <button class="range-btn" data-range="3mo" onclick="loadBalanceChart('3mo')" style="background:#21262d;border:1px solid #30363d;color:#8b949e;border-radius:4px;padding:3px 10px;cursor:pointer;margin-right:4px;font-size:0.8em">3mo</button>
  <button class="range-btn" data-range="1yr" onclick="loadBalanceChart('1yr')" style="background:#21262d;border:1px solid #30363d;color:#8b949e;border-radius:4px;padding:3px 10px;cursor:pointer;margin-right:4px;font-size:0.8em">1yr</button>
  <button class="range-btn" data-range="all" onclick="loadBalanceChart('all')" style="background:#21262d;border:1px solid #30363d;color:#8b949e;border-radius:4px;padding:3px 10px;cursor:pointer;font-size:0.8em">All</button>
</div>
<div style="max-width:800px; margin-bottom:30px">
  <canvas id="balanceChart" height="100"></canvas>
</div>

<p class="refreshing">Generated at {
            datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
        } UTC</p>
{sse_js}
{chart_js}
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

        html = f"""<!DOCTYPE html>
<html><head><title>Analyze — Kalshi</title>{VIEWPORT}{DARK_STYLE}</head>
<body>
<h1>Kalshi Weather — Opportunities</h1>
{NAV}
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
      <th>Edge</th><th>Risk</th><th>Buy</th></tr>
  {rows_html}
</table>'''
        }
<p class="refreshing" style="margin-top:12px">Generated at {
            datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
        } UTC &mdash; <a href="/analyze">Refresh</a></p>
</body></html>"""
        return render_template_string(html)

    @app.route("/analytics")
    def analytics_page():
        """Analytics page — model calibration, confusion matrix, edge decay."""
        try:
            from tracker import (
                brier_score,
                get_brier_by_days_out,
                get_calibration_by_city,
            )

            bs = brier_score()
            brier_by_days = get_brier_by_days_out()
            city_cal = get_calibration_by_city()

            # Optional analytics
            confusion = None
            roc = None
            edge_decay = None
            model_cal = None
            sharpe = None
            attribution = None
            factor = None
            season_cal = None  # #59

            try:
                from tracker import get_confusion_matrix

                confusion = get_confusion_matrix()
            except Exception:
                pass
            try:
                from tracker import get_edge_decay_curve

                edge_decay = get_edge_decay_curve()
            except Exception:
                pass
            try:
                from tracker import get_model_calibration_buckets

                model_cal = get_model_calibration_buckets()
            except Exception:
                pass
            try:
                from tracker import get_roc_auc

                roc = get_roc_auc()
            except Exception:
                pass
            try:
                from paper import (
                    get_attribution,
                    get_factor_exposure,
                    get_rolling_sharpe,
                )

                sharpe = get_rolling_sharpe()
                attribution = get_attribution()
                factor = get_factor_exposure()
            except Exception:
                pass
            # #59: seasonal calibration breakdown
            try:
                from tracker import get_calibration_by_season

                season_cal = get_calibration_by_season()
            except Exception:
                pass

        except Exception as e:
            return render_template_string(
                f"<!DOCTYPE html><html><head>{VIEWPORT}{DARK_STYLE}</head><body>"
                f"<h1>Analytics</h1>{NAV}"
                f"<p class='neg'>Error loading analytics: {e}</p></body></html>"
            )

        # Build sections
        sections = ""

        # Summary row
        bs_str = f"{bs:.4f}" if bs is not None else "—"
        sharpe_str = f"{sharpe:.2f}" if sharpe is not None else "—"
        auc_str = f"{roc['auc']:.3f}" if roc and roc.get("auc") is not None else "—"
        sections += f"""
<div class="stats">
  <div class="stat-card"><div class="stat-label">Brier Score</div><div class="stat-value">{bs_str}</div></div>
  <div class="stat-card"><div class="stat-label">Sharpe (30d)</div><div class="stat-value">{sharpe_str}</div></div>
  <div class="stat-card"><div class="stat-label">ROC AUC</div><div class="stat-value">{auc_str}</div></div>
</div>"""

        # Attribution
        if attribution and attribution.get("n", 0) > 0:
            e_str = (
                f"+${attribution['pnl_from_edge']:.2f}"
                if attribution["pnl_from_edge"] >= 0
                else f"-${abs(attribution['pnl_from_edge']):.2f}"
            )
            l_str = (
                f"+${attribution['pnl_from_luck']:.2f}"
                if attribution["pnl_from_luck"] >= 0
                else f"-${abs(attribution['pnl_from_luck']):.2f}"
            )
            sections += f"""
<h2>P&amp;L Attribution ({attribution["n"]} trades)</h2>
<table><tr><th>Source</th><th>P&amp;L</th></tr>
<tr><td>From Edge (model EV)</td><td class="{"pos" if attribution["pnl_from_edge"] >= 0 else "neg"}">{e_str}</td></tr>
<tr><td>From Luck (residual)</td><td class="{"pos" if attribution["pnl_from_luck"] >= 0 else "neg"}">{l_str}</td></tr>
</table>"""

        # Factor exposure
        if factor:
            sections += f"""
<h2>Factor Exposure</h2>
<table><tr><th>Direction</th><th>Count</th><th>Cost</th><th>Cities</th></tr>
<tr><td><span class="badge badge-green">YES</span></td><td>{factor["yes_count"]}</td><td>${factor["yes_cost"]:.2f}</td><td>{", ".join(factor["cities_long_yes"]) or "—"}</td></tr>
<tr><td><span class="badge badge-red">NO</span></td><td>{factor["no_count"]}</td><td>${factor["no_cost"]:.2f}</td><td>{", ".join(factor["cities_long_no"]) or "—"}</td></tr>
<tr><td colspan="4">Net bias: <strong>{factor["net_bias"]}</strong></td></tr>
</table>"""

        # Confusion matrix
        if confusion and confusion.get("n", 0) > 0:
            c = confusion
            sections += f"""
<h2>Confusion Matrix (threshold=50%)</h2>
<table>
<tr><th></th><th>Predicted YES</th><th>Predicted NO</th></tr>
<tr><td><strong>Actual YES</strong></td><td class="pos">{c["tp"]} TP</td><td class="neg">{c["fn"]} FN</td></tr>
<tr><td><strong>Actual NO</strong></td><td class="neg">{c["fp"]} FP</td><td class="pos">{c["tn"]} TN</td></tr>
</table>
<p class="neu" style="margin-top:8px">
  Precision: {f"{c['precision']:.1%}" if c["precision"] is not None else "—"} &nbsp;
  Recall: {f"{c['recall']:.1%}" if c["recall"] is not None else "—"} &nbsp;
  F1: {f"{c['f1']:.3f}" if c["f1"] is not None else "—"} &nbsp;
  Accuracy: {f"{c['accuracy']:.1%}" if c["accuracy"] is not None else "—"}
</p>"""

        # Edge decay
        if edge_decay:
            rows_ed = "".join(
                f"<tr><td>{r['bucket']}d</td><td>{r['avg_edge']:.1%}</td>"
                f"<td>{r['avg_brier']:.4f}</td><td>{r['n']}</td></tr>"
                for r in edge_decay
            )
            sections += f"""
<h2>Edge Decay by Forecast Horizon</h2>
<table><tr><th>Horizon</th><th>Avg Edge</th><th>Brier</th><th>N</th></tr>
{rows_ed}</table>"""

        # Brier by days out
        if brier_by_days:
            rows_bd = "".join(
                f"<tr><td>{k}</td><td>{v:.4f}</td></tr>"
                for k, v in brier_by_days.items()
            )
            sections += f"""
<h2>Brier Score by Horizon</h2>
<table><tr><th>Horizon</th><th>Brier</th></tr>{rows_bd}</table>"""

        # City calibration
        if city_cal:
            rows_cc = "".join(
                f"<tr><td>{city}</td><td>{d['brier']:.4f}</td>"
                f'<td class="{"neg" if d["bias"] > 0 else "pos"}">{d["bias"]:+.3f}</td>'
                f"<td>{d['n']}</td></tr>"
                for city, d in sorted(city_cal.items(), key=lambda x: x[1]["brier"])
            )
            sections += f"""
<h2>City-Level Calibration</h2>
<table><tr><th>City</th><th>Brier</th><th>Bias</th><th>N</th></tr>
{rows_cc}</table>
<p class="neu" style="font-size:0.82em">Bias: positive = over-predicts YES; negative = under-predicts.</p>"""

        # #59: Seasonal calibration
        if season_cal:
            season_order = ["Spring", "Summer", "Fall", "Winter"]
            rows_sc = "".join(
                f"<tr><td>{s}</td><td>{season_cal[s]['brier']:.4f}</td>"
                f'<td class="{"neg" if season_cal[s]["bias"] > 0 else "pos"}">'
                f"{season_cal[s]['bias']:+.3f}</td><td>{season_cal[s]['n']}</td></tr>"
                for s in season_order
                if s in season_cal
            )
            sections += f"""
<h2>Seasonal Calibration</h2>
<table><tr><th>Season</th><th>Brier</th><th>Bias</th><th>N</th></tr>
{rows_sc}</table>"""

        # Model calibration buckets
        if model_cal and model_cal.get("buckets"):
            rows_mc = "".join(
                f"<tr><td>{b['range']}</td><td>{b['our_prob_avg']:.1%}</td>"
                f"<td>{b['actual_rate']:.1%}</td>"
                f'<td class="{"neg" if b["deviation"] > 0.05 else "pos" if b["deviation"] < -0.05 else "neu"}">{b["deviation"]:+.1%}</td>'
                f"<td>{b['n']}</td></tr>"
                for b in model_cal["buckets"]
            )
            sections += f"""
<h2>Model Calibration (Our Probabilities vs Outcomes)</h2>
<table><tr><th>Prob Range</th><th>Predicted</th><th>Actual</th><th>Deviation</th><th>N</th></tr>
{rows_mc}</table>"""

        html = f"""<!DOCTYPE html>
<html><head><title>Analytics — Kalshi</title>{VIEWPORT}{DARK_STYLE}</head>
<body>
<h1>Kalshi Weather — Analytics</h1>
{NAV}
{sections if sections else "<p class='neu'>No data yet — run backtest or make predictions first.</p>"}
<p class="refreshing" style="margin-top:20px">Generated at {datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")} UTC</p>
</body></html>"""
        return render_template_string(html)

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
