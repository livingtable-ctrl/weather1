"""
Local web dashboard — run with: py main.py web
Opens a browser tab showing the analyze table, open positions, and P&L chart.
"""

from __future__ import annotations

import base64 as _base64
import functools
import hmac as _hmac
import json
import logging
import os
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

from flask import Response
from flask import request as _flask_request
from markupsafe import escape as _html_escape

_log = logging.getLogger(__name__)


def _require_auth(f):
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        import utils as _utils

        pwd = _utils.DASHBOARD_PASSWORD
        if not pwd:
            return f(*args, **kwargs)
        auth = _flask_request.headers.get("Authorization", "")
        if auth.startswith("Basic "):
            try:
                decoded = _base64.b64decode(auth[6:]).decode("utf-8")
                _, password = decoded.split(":", 1)
                # WA-auth: compare_digest raises TypeError on non-ASCII str
                # arguments; encoding to bytes first (its documented-safe usage)
                # avoids a silent permanent lockout if DASHBOARD_PASSWORD ever
                # contains a non-ASCII character — the bare except below would
                # otherwise swallow the TypeError and always 401, even for the
                # exactly-correct password, with no diagnostic anywhere.
                if _hmac.compare_digest(password.encode(), pwd.encode()):
                    return f(*args, **kwargs)
            except Exception:
                pass
        return Response(
            "Authentication required",
            401,
            {"WWW-Authenticate": 'Basic realm="Kalshi Dashboard"'},
        )

    return decorated


_app = None  # module-level Flask app
_client = None  # module-level Kalshi client reference

_KS_PATH: Path = Path(__file__).parent / "data" / ".kill_switch"

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
    from tracker import brier_score_rolling_with_n

    _brier, _brier_n = brier_score_rolling_with_n()
    return {
        "balance": round(get_balance(), 2),
        "open_count": len(get_open_trades()),
        "brier": _brier,
        "brier_n": _brier_n,
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
            stream_with_context,
        )
    except ImportError:
        return None

    app = Flask(__name__)
    app.config["TEMPLATES_AUTO_RELOAD"] = True

    # Enforce password requirement in prod — the dashboard exposes kill switch
    # and trade control endpoints that must never be unauthenticated in production.

    if not os.getenv("DASHBOARD_PASSWORD"):
        if os.getenv("DASHBOARD_UNPROTECTED", "").lower() == "true":
            _log.warning(
                "DASHBOARD_UNPROTECTED=true — dashboard running without password protection. "
                "Do NOT use in production."
            )
        else:
            raise RuntimeError(
                "DASHBOARD_PASSWORD must be set. "
                "The dashboard exposes kill switch and trade control endpoints. "
                "Set DASHBOARD_UNPROTECTED=true to run without a password (dev/test only)."
            )

    @app.before_request
    def _check_auth():
        # Single auth layer for ALL routes — including kill switch, halt/resume,
        # paper-order, close-position, and override endpoints.
        # Route-level @_require_auth decorators were removed (WA-16): before_request
        # runs unconditionally on every request, making per-route decoration redundant
        # and creating a confusing dual-layer with no added security.
        import utils as _utils

        pwd = _utils.DASHBOARD_PASSWORD
        if not pwd:
            return None  # open access (dev/test only mode — CSRF check below N/A)
        auth = _flask_request.headers.get("Authorization", "")
        if auth.startswith("Basic "):
            try:
                decoded = _base64.b64decode(auth[6:]).decode("utf-8")
                _, password = decoded.split(":", 1)
                # WA-auth: see _require_auth's identical fix above — encode to
                # bytes so a non-ASCII DASHBOARD_PASSWORD can't silently lock out
                # every request (including correct ones) via an unlogged TypeError.
                if _hmac.compare_digest(password.encode(), pwd.encode()):
                    # WA-csrf: Basic Auth alone doesn't stop CSRF — browsers
                    # re-attach cached Basic credentials to same-origin requests
                    # regardless of which page initiated them, so a malicious
                    # cross-site page can drive a plain <form> POST at
                    # /api/run_cron, /api/halt, /api/override, /api/paper-order,
                    # etc. while the operator has the dashboard open elsewhere.
                    # Require a header a bare <form> can't set (and that a
                    # cross-origin fetch/XHR trying to set would trigger a CORS
                    # preflight this server doesn't answer, so the browser blocks
                    # it). The bundled frontend's authHeader() helper already
                    # sends this on every state-changing request.
                    if _flask_request.method in ("GET", "HEAD", "OPTIONS") or (
                        _flask_request.headers.get("X-Requested-With")
                        == "XMLHttpRequest"
                    ):
                        return None  # authenticated (+ CSRF check passed)
            except Exception:
                pass
        return Response(
            "Authentication required",
            401,
            {"WWW-Authenticate": 'Basic realm="Kalshi Dashboard"'},
        )

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
        """Health check endpoint. Includes last cron run timing so external monitors
        (e.g. UptimeRobot) can detect a stale bot without watching terminal output."""
        _last_run_path = Path(__file__).parent / "data" / ".cron_last_run"
        _stale_threshold = float(os.environ.get("CRON_STALE_HOURS", "6.0"))
        _last_cron: str | None = None
        _hours_since: float | None = None
        _cron_stale = False
        if _last_run_path.exists():
            try:
                _hours_since = round(
                    (datetime.now(UTC).timestamp() - _last_run_path.stat().st_mtime)
                    / 3600,
                    2,
                )
                _last_cron = _last_run_path.read_text().strip() or None
                _cron_stale = _hours_since > _stale_threshold
            except Exception:
                pass
        _cron_age_minutes: float | None = None
        _cycle_count: int | None = None
        _hb_path = Path(__file__).parent / "data" / "cron_heartbeat.json"
        if _hb_path.exists():
            try:
                _hb = json.loads(_hb_path.read_text())
                _hb_last = datetime.fromisoformat(_hb["last_run"])
                _cron_age_minutes = round(
                    (datetime.now(UTC) - _hb_last).total_seconds() / 60, 1
                )
                _cycle_count = _hb.get("cycle_count")
            except Exception:
                pass
        if _cron_age_minutes is None and _hours_since is not None:
            _cron_age_minutes = round(_hours_since * 60, 1)
        try:
            from paper import get_open_trades as _got

            _open_count = len(_got())
        except Exception:
            _open_count = None
        return jsonify(
            {
                "status": "ok",
                "timestamp": datetime.now(UTC).isoformat(),
                "last_cron_run": _last_cron,
                "hours_since_cron": _hours_since,
                "cron_stale": _cron_stale,
                "cron_age_minutes": _cron_age_minutes,
                "cycle_count": _cycle_count,
                "kill_switch_active": _KS_PATH.exists(),
                "open_trade_count": _open_count,
            }
        )

    @app.route("/api/stream")
    def stream():
        """Server-Sent Events endpoint — pushes portfolio status every 10s."""
        import time

        def generate():
            while True:
                try:
                    data = _build_stream_data()
                    yield f"data: {json.dumps(data)}\n\n"
                except Exception as _stream_exc:
                    # WA-observability: log and flag the payload instead of silently
                    # emitting {} forever — a persistently broken data layer (corrupt
                    # trades JSON, locked SQLite DB) was previously invisible to both
                    # the operator and the frontend, which treats ANY message
                    # (including {}) as "connection alive."
                    _log.warning(
                        "api/stream: _build_stream_data failed: %s", _stream_exc
                    )
                    yield f"data: {json.dumps({'error': str(_stream_exc)})}\n\n"
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
                except Exception as _stream_exc:
                    # WA-observability: see /api/stream's identical fix above.
                    _log.warning(
                        "api/stream/markets: snapshot build failed: %s", _stream_exc
                    )
                    yield f"data: {json.dumps({'error': str(_stream_exc)})}\n\n"
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

        # Always append a synthetic "now" point at the real current balance so
        # the chart endpoint reflects open-trade cost deductions, not just the
        # last settlement.  Only added when the balance actually differs (i.e.
        # trades have been placed since the most recent settlement event).
        from paper import get_balance as _get_balance

        current_balance = _get_balance()
        if points and abs(points[-1]["balance"] - current_balance) > 0.005:
            now_ts = _now_utc().isoformat()
            points = list(points) + [
                {"ts": now_ts, "balance": current_balance, "event": ""}
            ]

        return jsonify(
            {
                "labels": [(p.get("ts") or "")[:16] or "Start" for p in points],
                "values": [p["balance"] for p in points],
                "points": [
                    {
                        "ts": p.get("ts", ""),
                        "balance": p["balance"],
                        "event": p.get("event", ""),
                    }
                    for p in points
                ],
            }
        )

    @app.route("/api/analytics")
    def api_analytics():
        try:
            from tracker import (
                brier_score_rolling_with_n,
                get_brier_by_days_out,
                get_calibration_by_city,
                get_component_attribution,
            )

            _brier, _brier_n = brier_score_rolling_with_n()
            result: dict = {
                "brier": _brier,
                "brier_n": _brier_n,
                "brier_by_days": get_brier_by_days_out(),
                "city_calibration": get_calibration_by_city(),
                "component_attribution": get_component_attribution(),
            }
            for fn_name in (
                "get_confusion_matrix",
                "get_roc_auc",
                "get_edge_decay_curve",
                "get_model_calibration_buckets",
                "get_calibration_by_season",
                "get_brier_by_tier",
                "brier_skill_score",
                "get_model_brier_scores",
                "get_optimal_threshold",
                "get_analysis_bias",
                "get_rolling_win_rate_ci",
                "get_disputed_count",
            ):
                try:
                    import tracker as _t

                    fn = getattr(_t, fn_name, None)
                    if fn:
                        result[fn_name.replace("get_", "")] = fn()
                except Exception as _optional_exc:
                    # WA-observability: was a bare except: pass with no logging —
                    # a function that exists but raises (e.g. a corrupt/locked DB)
                    # silently dropped its panel from the analytics page with no
                    # trace anywhere.
                    _log.warning(
                        "api/analytics: optional metric %s failed: %s",
                        fn_name,
                        _optional_exc,
                    )
            for fn_name in (
                "get_rolling_sharpe",
                "get_attribution",
                "get_factor_exposure",
                "get_stop_loss_accuracy",
            ):
                try:
                    import paper as _p

                    fn = getattr(_p, fn_name, None)
                    if fn:
                        result[fn_name.replace("get_", "")] = fn()
                except Exception as _optional_exc:
                    _log.warning(
                        "api/analytics: optional metric %s failed: %s",
                        fn_name,
                        _optional_exc,
                    )
        except Exception as e:
            # WA-status-code: was returning 200 with {"error": ...} on total
            # failure, unlike every sibling endpoint in this chunk (e.g.
            # /api/sameday-calibration, /api/model-attribution, /api/live-pnl,
            # /api/brier_history all return 500 for the same condition) — a
            # response.ok-based frontend check would treat this as success.
            return jsonify({"error": str(e)}), 500
        return jsonify(result)

    @app.route("/api/sameday-calibration")
    def api_sameday_calibration():
        """Same-day METAR-locked trade calibration — completely separate from multi-day.

        Returns calibration curve buckets, time-of-day bias breakdown, and
        current T_sameday from temperature_scale.json.  Gate is 20 settled
        same-day trades; returns n=0 and empty buckets until then.
        """
        try:
            from tracker import get_sameday_calibration

            return jsonify(get_sameday_calibration())
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

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
        import inspect

        try:
            from paper import fear_greed_index, get_performance, graduation_check
        except ImportError as e:
            return jsonify({"error": str(e)}), 500
        from tracker import brier_score as _brier_score

        # Extract graduation thresholds from the function signature so the frontend
        # always displays the values actually used — not hardcoded JS fallbacks (WA-8).
        # Fallback to defaults when graduation_check is mocked (no real signature).
        try:
            _gc_params = inspect.signature(graduation_check).parameters
            _min_trades = _gc_params["min_trades"].default
            _min_pnl = _gc_params["min_pnl"].default
            _max_brier = _gc_params["max_brier"].default
        except (KeyError, ValueError):
            _min_trades = 30
            _min_pnl = 50.0
            _max_brier = 0.23  # must match graduation_check() default

        perf = get_performance()
        gc = graduation_check()
        fg_score, fg_label = fear_greed_index()
        # Use the Brier from graduation_check() when it ran (avoids a second DB hit).
        # When gc is None the check may have been blocked by the sample guard, so call
        # directly with the same window so the progress bar shows a meaningful value.
        _displayed_brier = gc["brier"] if gc is not None else _brier_score(last_n=50)
        return jsonify(
            {
                "trades_done": perf.get("settled", 0),
                "win_rate": perf.get("win_rate"),
                "total_pnl": perf.get("total_pnl", 0.0),
                "profit_factor": perf.get("profit_factor"),
                "brier": _displayed_brier,
                "ready": gc is not None,
                "fear_greed_score": fg_score,
                "fear_greed_label": fg_label,
                "trades_target": _min_trades,
                "pnl_target": _min_pnl,
                "brier_target": _max_brier,
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
        from flask import send_from_directory as _sfd

        dist = Path(__file__).parent / "static" / "dist"
        if (dist / "index.html").exists():
            return _sfd(str(dist), "index.html")
        # Fallback: old Jinja template while frontend build hasn't run yet
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
            # WA-security: return the pre-rendered string directly rather than via
            # render_template_string — the string is not a Jinja template, and passing
            # it through render_template_string re-parses external data (exception text)
            # as template source, which is an SSTI/TemplateSyntaxError risk since
            # _html_escape() only neutralizes HTML metacharacters, not Jinja delimiters.
            return (
                f"<!DOCTYPE html><html><head>{VIEWPORT}{DARK_STYLE}</head><body>"
                f"<h1>Analyze</h1>{NAV}"
                f"<p class='neg'>Could not fetch markets: {_html_escape(str(e))}</p></body></html>"
            )

        rows_html = ""
        opps = []
        _skipped = 0
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
                elif not analysis:
                    # WA-observability: analyze_trade() itself returns None (rather
                    # than raising) on a total forecast-provider outage, so this
                    # counts toward the same "couldn't actually analyze" signal as
                    # the except below — without it, a total outage rendered as the
                    # exact same calm "No opportunities above threshold" message as
                    # a genuine no-edge scan, with no way to tell them apart.
                    _skipped += 1
            except Exception:
                _skipped += 1
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
              <td>{_html_escape(ticker)}</td>
              <td>{_html_escape((m.get("title") or ticker)[:38])}</td>
              <td>{_html_escape(m.get("_city", "—"))}</td>
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
<div id="analyze-content">
<p class="refreshing" id="analyze-status">
  {
            len(opps)
        } opportunities found &mdash; refreshing in <span id="analyze-countdown">60</span>s
</p>
{
            (
                f"<p class='neg' style='margin-top:16px'>"
                f"&#9888; Could not analyze any of {len(markets)} market(s) — "
                f"forecast/analysis pipeline may be down. Check logs.</p>"
                if markets and _skipped == len(markets)
                else "<p class='neu' style='margin-top:16px'>No opportunities above threshold right now.</p>"
            )
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
</div>
<script>
// #90 / WA-regression-fix: auto-refresh analyze table every 60 seconds.
// Swaps the whole #analyze-content wrapper (status line, table-or-empty-message,
// and the "Generated at" timestamp together) instead of just <table> — swapping
// only the table left stale opportunities on screen forever once opps went to
// zero (no <table> in the fetched page to swap in), and never inserted a table
// when the page first loaded with zero opportunities (no <table> to replace).
// The countdown element is re-queried fresh each tick rather than cached, since
// the cached node would otherwise be detached from the DOM after a swap.
let _analyzeCountdown = 60;
setInterval(() => {{
  _analyzeCountdown--;
  const _cdEl = document.getElementById('analyze-countdown');
  if (_cdEl) _cdEl.textContent = _analyzeCountdown;
  if (_analyzeCountdown <= 0) {{
    fetch('/analyze?fragment=1').then(r => r.text()).then(html => {{
      const parser = new DOMParser();
      const doc = parser.parseFromString(html, 'text/html');
      const newContent = doc.querySelector('#analyze-content');
      const oldContent = document.querySelector('#analyze-content');
      if (newContent && oldContent) oldContent.replaceWith(newContent);
      _analyzeCountdown = 60;
    }}).catch(() => {{ _analyzeCountdown = 60; }});
  }}
}}, 1000);
</script>
</body></html>"""
        # WA-security: return the string directly instead of render_template_string —
        # html embeds Kalshi-controlled ticker/title/city (lines above); _html_escape()
        # neutralizes HTML metacharacters but not Jinja delimiters ({{, {%, {#), so passing
        # this through render_template_string re-parses external data as template source
        # (SSTI/TemplateSyntaxError risk). No Jinja features are used, so this is a safe drop-in.
        return html

    @app.route("/api/suggested_bets")
    def api_suggested_bets():
        """Return top-N trade opportunities ranked by expected value (edge × kelly $)."""

        from flask import request as freq

        from paper import get_balance
        from paper import kelly_bet_dollars as _kbd_sb
        from utils import MIN_EDGE
        from weather_markets import (
            analyze_trade,
            enrich_with_forecast,
            get_weather_markets,
        )

        try:
            n = max(1, min(int(freq.args.get("n", 3)), 20))
        except (TypeError, ValueError):
            # WA-input-validation: was outside any try — ?n=abc raised an
            # unhandled ValueError, returning Flask's raw HTML 500 page instead
            # of this route's usual JSON error shape (matching /history's
            # existing try/except around the identical coercion).
            n = 3

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
                # WA-drift: use the canonical paper.kelly_bet_dollars instead of a
                # bare kelly*balance. The raw multiplication ignored the drawdown-
                # scaling gate (including its 0.0 HALTED tier), half-Kelly/strategy
                # scaling, streak pause, per-method Brier scaling, and the dynamic/
                # tier Brier cap — so this endpoint could show a nonzero suggested
                # bet (and roughly double a healthy-state bot's real sizing, since
                # the raw kelly figure has no half-Kelly applied) while the bot's
                # actual sizing chain would place $0 or far less on the same trade.
                kelly_dollars = _kbd_sb(kelly)
                ev_score = net_edge * kelly_dollars
                candidates.append(
                    {
                        "ticker": m.get("ticker", ""),
                        "title": (m.get("title") or m.get("ticker", ""))[:60],
                        # WA-drift: enrich_with_forecast() returns a NEW dict rather
                        # than mutating `m` in place, so `_city` only ever lands on
                        # `enriched`, never on `m` — reading it from `m` always fell
                        # back to "—".
                        "city": enriched.get("_city") or "—",
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
                "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            }
        )

    _cron_proc: subprocess.Popen | None = None
    _CRON_WEB_LOG = Path(__file__).parent / "data" / "cron_web.log"

    _CRON_RATE_LIMIT_S = 60.0  # minimum seconds between spawns
    _run_cron_lock = threading.Lock()

    @app.route("/api/run_cron", methods=["POST"])
    def api_run_cron():
        """Spawn a cron scan subprocess, capturing output to cron_web.log."""
        import time as _time

        from cron import _is_cron_running

        # Flask serves requests threaded (threaded=True default) — without this lock,
        # two near-simultaneous POSTs (e.g. a double-click) can both pass the
        # _is_cron_running()/rate-limit checks before either writes _last_spawn,
        # spawning two concurrent cron cycles (duplicate order placement once live).
        with _run_cron_lock:
            if _is_cron_running():
                return jsonify({"error": "cron already running"}), 409

            now = _time.monotonic()
            if (
                now - api_run_cron._last_spawn  # type: ignore[attr-defined]
                < _CRON_RATE_LIMIT_S
            ):
                return jsonify(
                    {"error": "rate limited — wait before spawning again"}
                ), 429

            _prior_last_spawn = api_run_cron._last_spawn  # type: ignore[attr-defined]
            api_run_cron._last_spawn = _time.monotonic()  # type: ignore[attr-defined]

        try:
            _CRON_WEB_LOG.parent.mkdir(exist_ok=True)
            _CRON_WEB_LOG.write_text("")  # truncate log for fresh run
            # Open stdout/stderr log. Binary mode avoids Windows line-buffering
            # quirks; the child writes via its own duplicated handle so we close
            # our copy immediately after Popen returns.
            log_f = open(_CRON_WEB_LOG, "wb")
            # On Windows: CREATE_NO_WINDOW prevents the child from attaching to
            # (or blocking on) the parent's console window, which can cause the
            # child to hang on stdout/stderr writes if the console is detached.
            _cflags = (
                getattr(subprocess, "CREATE_NO_WINDOW", 0)
                if sys.platform == "win32"
                else 0
            )
            proc = subprocess.Popen(
                [sys.executable, "-u", str(Path(__file__).parent / "main.py"), "cron"],
                cwd=str(Path(__file__).parent),
                stdin=subprocess.DEVNULL,  # never inherit Flask's stdin
                stdout=log_f,
                stderr=log_f,
                env={**__import__("os").environ, "PYTHONUNBUFFERED": "1"},
                creationflags=_cflags,
            )
            log_f.close()  # child holds its own duplicated handle
            # store on the function object so it survives across requests
            # (_last_spawn was already reserved inside the lock above)
            api_run_cron._proc = proc  # type: ignore[attr-defined]
            return jsonify({"status": "started", "pid": proc.pid})
        except Exception as e:
            # WA-regression: roll back the rate-limit reservation on a failed spawn —
            # nothing actually started, so a transient failure (e.g. cron_web.log
            # briefly locked by an AV scan) shouldn't cost the operator a 60s lockout
            # on retry. Safe to write without re-acquiring the lock: the reservation
            # above already excludes any concurrent spawner for this window.
            with _run_cron_lock:
                api_run_cron._last_spawn = _prior_last_spawn  # type: ignore[attr-defined]
            return jsonify({"status": "error", "message": str(e)}), 500

    api_run_cron._proc = None  # type: ignore[attr-defined]
    api_run_cron._last_spawn = 0.0  # type: ignore[attr-defined]

    @app.route("/api/cron-status")
    def api_cron_status():
        """Return running state and last N lines of cron_web.log."""
        import re as _re

        from cron import _is_cron_running

        proc = api_run_cron._proc  # type: ignore[attr-defined]
        running = False
        exit_code = None
        if proc is not None:
            exit_code = proc.poll()
            running = exit_code is None
        # WA-drift: previously only fell back to _is_cron_running() when _proc was
        # None. _proc is set once by /api/run_cron and never reset — once the
        # first dashboard-spawned cron exits, this stayed on the stale exit_code
        # forever, misreporting running=False for any LATER externally-launched
        # (e.g. Windows Task Scheduler) cron cycle. Always fall back to the
        # lock-file-based check when the dashboard-tracked process isn't running.
        if not running:
            running = _is_cron_running()

        lines: list[str] = []
        if _CRON_WEB_LOG.exists():
            try:
                raw = _CRON_WEB_LOG.read_text(
                    encoding="utf-8", errors="replace"
                ).splitlines()
                ansi = _re.compile(r"\x1b\[[0-9;]*[mK]")
                lines = [ansi.sub("", ln) for ln in raw[-200:] if ln.strip()]
            except Exception:
                pass

        return jsonify({"running": running, "exit_code": exit_code, "log": lines})

    @app.route("/api/cancel-cron", methods=["POST"])
    def api_cancel_cron():
        """Terminate the running cron subprocess."""
        proc = api_run_cron._proc  # type: ignore[attr-defined]
        if proc is None or proc.poll() is not None:
            return jsonify({"error": "no cron running"}), 404
        proc.terminate()
        return jsonify({"ok": True})

    @app.route("/api/weekly-report")
    def api_weekly_report():
        """Generate and serve the weekly PDF/HTML report as a download."""
        import tempfile as _tmp

        from pdf_report import generate_weekly_report

        try:
            with _tmp.TemporaryDirectory() as td:
                out = generate_weekly_report(str(Path(td) / "report"))
                out_path = Path(out)
                mime = "application/pdf" if out_path.suffix == ".pdf" else "text/html"
                data = out_path.read_bytes()
            from flask import Response as _Resp

            return _Resp(
                data,
                mimetype=mime,
                headers={
                    "Content-Disposition": f"attachment; filename=weekly_report{out_path.suffix}"
                },
            )
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

    MAX_SIGNALS_CACHE_AGE_SECS = 4 * 60 * 60  # 4 hours — one full cron cycle

    @app.route("/api/scan-version")
    def api_scan_version():
        """Lightweight endpoint: returns the mtime of signals_cache.json.
        Frontend polls this every 5 s to detect new cron completions and
        trigger an immediate fetchAll() instead of waiting for the 60 s timer.
        """
        cache_path = Path(__file__).parent / "data" / "signals_cache.json"
        if not cache_path.exists():
            return jsonify({"version": None})
        return jsonify({"version": int(os.path.getmtime(cache_path))})

    @app.route("/api/live_signals")
    def api_live_signals():
        """Serve the signals cache written by the last cron run."""
        from paper import get_open_trades

        cache_path = Path(__file__).parent / "data" / "signals_cache.json"
        if not cache_path.exists():
            return jsonify(
                {
                    "signals": [],
                    "summary": {
                        "scanned": 0,
                        "with_edge": 0,
                        "strong": 0,
                        "low_risk": 0,
                    },
                    "generated_at": None,
                    "stale": True,
                    "message": "No scan data yet — run the cron job or wait for the next scheduled scan.",
                }
            )

        # Age validation: reject stale signals_cache.json (>4 h old)
        signals_mtime = os.path.getmtime(cache_path)
        signals_age = time.time() - signals_mtime
        _last_scan_at = datetime.fromtimestamp(signals_mtime, UTC).isoformat()
        if signals_age > MAX_SIGNALS_CACHE_AGE_SECS:
            _log.warning(
                "signals_cache.json is %.0f minutes old — serving empty signals",
                signals_age / 60,
            )
            return jsonify(
                {
                    "signals": [],
                    "summary": {
                        "scanned": 0,
                        "with_edge": 0,
                        "strong": 0,
                        "low_risk": 0,
                    },
                    "generated_at": _last_scan_at,  # preserve last-scan time even when stale
                    "stale": True,
                    "message": f"Signals cache is stale ({signals_age / 60:.0f} min old) — waiting for next cron scan.",
                }
            )

        try:
            with open(cache_path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            return jsonify({"error": str(e), "signals": []}), 500

        # Annotate already-held tickers and fill kelly_dollars + kelly_qty.
        # WA-observability: this used to be one big try/except around the whole
        # block (imports, get_open_trades(), and the entire per-signal loop) with
        # a bare `except: pass` — an early failure (e.g. a corrupt paper_trades.json)
        # or a single malformed signal raising mid-loop silently left ALL signals
        # (not just the failing one) at the cron defaults (already_held=False,
        # kelly_dollars=0.0), with no log anywhere. On a live-trading dashboard that
        # can read as "not held" for a position that is actually open. Now:
        # get_open_trades() failures are logged and fail safe to "nothing held";
        # each signal's Kelly computation is wrapped individually so one bad
        # signal can't blank out annotation for the rest.
        from paper import corr_kelly_scale as _cks
        from paper import kelly_bet_dollars as _kbd
        from paper import kelly_quantity as _kq
        from paper import portfolio_kelly_fraction as _pkf
        from paper import spread_kelly_multiplier as _skm

        # Maker fee (not taker): live/paper entries are always resting midpoint
        # GTC limit orders, which pay $0 on this bot's markets (see
        # KALSHI_MAKER_FEE_RATE) -- this dashboard display must match what
        # analyze_trade() actually computes for live sizing.
        from utils import KALSHI_MAKER_FEE_RATE as _fee_rate
        from weather_markets import kelly_fraction as _kf_wm

        try:
            _open_trades = get_open_trades()
            open_tickers = {t["ticker"] for t in _open_trades}
        except Exception as _open_trades_exc:
            _log.warning(
                "api/live_signals: get_open_trades() failed, already_held will "
                "default to False for all signals: %s",
                _open_trades_exc,
            )
            _open_trades = []
            open_tickers = set()

        for s in data.get("signals", []):
            s["already_held"] = s.get("ticker", "") in open_tickers
            try:
                # Mirror the bot's full Kelly sizing chain:
                # kelly_fraction → portfolio_kelly_fraction → corr_kelly_scale
                # → consensus_mult → spread_kelly_multiplier
                # → kelly_bet_dollars (drawdown + streak + Brier cap) → kelly_quantity.
                fp = (s.get("forecast_prob") or 0) / 100
                mp = (s.get("market_prob") or 0) / 100
                side = (s.get("side") or "yes").lower()
                if fp > 0 and 0 < mp < 1:
                    # WA-drift: the bot fills at the ask (yes_ask for YES,
                    # 1-yes_bid for NO — order_executor.py's own fill convention),
                    # not the bid/ask mid that market_prob represents. Using the
                    # mid here understated entry cost by ~half the spread, which
                    # on a wide-spread market overstated the displayed kelly_qty
                    # vs. what the bot would actually place. yes_bid/yes_ask are
                    # already in the signals cache (cron.py), so prefer them and
                    # only fall back to the mid-derived price when a real quote
                    # isn't present.
                    _yes_bid_raw = s.get("yes_bid")
                    _yes_ask_raw = s.get("yes_ask")
                    if _yes_bid_raw and _yes_ask_raw:
                        _ask_side_price = (
                            (1.0 - float(_yes_bid_raw))
                            if side == "no"
                            else float(_yes_ask_raw)
                        )
                    else:
                        _ask_side_price = None
                    if side == "no":
                        _our_prob = max(0.01, min(0.99, 1.0 - fp))
                        side_price = max(
                            0.01,
                            min(0.99, _ask_side_price if _ask_side_price else 1.0 - mp),
                        )
                    else:
                        _our_prob = max(0.01, min(0.99, fp))
                        side_price = max(
                            0.01,
                            min(0.99, _ask_side_price if _ask_side_price else mp),
                        )
                    city = s.get("city") or None
                    target_date = s.get("target_date") or None
                    kf = _kf_wm(_our_prob, side_price, _fee_rate)
                    kf = _pkf(kf, city, target_date, side=side)
                    kf *= _cks({"city": city, "target_date": target_date}, _open_trades)
                    if not s.get("model_consensus", True):
                        kf *= 0.5
                    kf *= _skm(
                        s.get("yes_bid", 0), s.get("yes_ask", 0), s.get("net_edge", 0)
                    )
                    s["kelly_dollars"] = _kbd(kf)
                    s["kelly_qty"] = _kq(kf, side_price)
                else:
                    # WA-wrong-default: kelly_quantity() itself returns 0 (never 1)
                    # for an unsizeable trade, so a signal with missing/invalid
                    # probabilities should match that convention instead of
                    # displaying a phantom "1 contract" suggestion alongside $0.
                    s["kelly_dollars"] = 0.0
                    s["kelly_qty"] = 0
            except Exception as _annotate_exc:
                _log.warning(
                    "api/live_signals: Kelly annotation failed for %s, "
                    "leaving kelly_dollars=0.0: %s",
                    s.get("ticker", "?"),
                    _annotate_exc,
                )
                s["kelly_dollars"] = 0.0
                # WA-wrong-default: match the unsizeable-signal branch's fix just
                # above -- kelly_quantity() itself returns 0 (never 1), so this
                # exception fallback shouldn't reintroduce the same phantom
                # "1 contract for $0" display that fix was meant to eliminate.
                s["kelly_qty"] = 0

        # Annotate brier state and cache age so the frontend can surface them
        try:
            from tracker import brier_score_rolling as _bs
            from tracker import count_settled_predictions_rolling as _csp_r

            _n_rolling = _csp_r()
            _brier_val = _bs() if _n_rolling >= 5 else None
            data["brier_score"] = _brier_val
            data["brier_score_n"] = _n_rolling
            data["brier_cap_active"] = _n_rolling < 5
            data["cache_age_secs"] = round(signals_age)
        except Exception:
            pass

        return jsonify(data)

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

        _history_load_error: str | None = None
        try:
            from paper import get_all_trades

            all_settled = [t for t in get_all_trades() if t.get("settled")]
            all_settled.sort(key=lambda t: t.get("entered_at", ""), reverse=True)
        except Exception as _hist_exc:
            # WA-observability: was a bare except setting all_settled=[] with no
            # logging — a corrupt/checksum-mismatched paper_trades.json rendered
            # as "0 trades", indistinguishable from a genuinely empty history. An
            # operator checking settled history after an incident would wrongly
            # conclude nothing settled rather than that the data store is broken.
            _log.warning("history_page: get_all_trades() failed: %s", _hist_exc)
            _history_load_error = str(_hist_exc)
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
              <td>{_html_escape(t["ticker"][:28])}</td>
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
{
            f"<p class='neg' style='margin-bottom:12px'>&#9888; Could not load trade "
            f"history: {_html_escape(_history_load_error)}</p>"
            if _history_load_error
            else ""
        }
<p class="refreshing">{total} trades &mdash; Page {page} of {total_pages}</p>
<table>
  <tr><th>#</th><th>Ticker</th><th>Side</th><th>Qty</th><th>Entry</th><th>Cost</th><th>P&amp;L</th><th>Date</th></tr>
  {rows_html}
</table>
<p style="margin-top:12px">{prev_link} &nbsp; {next_link}</p>
</body></html>"""
        # WA-security: return the string directly instead of render_template_string —
        # see the /analyze route for why (SSTI/TemplateSyntaxError risk from re-parsing
        # already-rendered HTML containing ticker/entered_at as a Jinja template).
        return html

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
            # Pass through needs_manual_settle flag so the UI can badge it
            t.setdefault("needs_manual_settle", bool(t.get("needs_manual_settle")))

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
            from tracker import brier_score_rolling_with_n

            try:
                from paper import fear_greed_index

                fg_score, fg_label = fear_greed_index()
            except Exception:
                fg_score, fg_label = None, None

            try:
                from tracker import get_mean_slippage

                mean_slippage = get_mean_slippage(days=30)
            except Exception:
                mean_slippage = None

            try:
                from tracker import detect_brier_drift

                _drift = detect_brier_drift()
            except Exception:
                _drift = {"drifting": False}

            try:
                from paper import get_daily_pnl

                today_pnl = round(get_daily_pnl(), 2)
            except Exception:
                today_pnl = None

            try:
                import paper as _paper

                starting_balance = float(_paper.STARTING_BALANCE)
            except Exception:
                starting_balance = None

            try:
                from order_executor import _daily_paper_spend

                daily_spend = round(_daily_paper_spend(), 2)
            except Exception:
                daily_spend = None

            # Drawdown tier fields for the dashboard risk row
            peak_balance: float | None = None
            halt_floor: float | None = None
            kelly_factor: float | None = None
            drawdown_pct: float | None = None
            drawdown_tier: str | None = None
            try:
                from paper import (
                    MAX_DRAWDOWN_FRACTION as _max_dd_frac,
                )
                from paper import (
                    drawdown_scaling_factor as _dsf,
                )
                from paper import (
                    get_max_drawdown_pct as _dmax,
                )
                from paper import (
                    get_peak_balance as _gpeak,
                )

                _peak = _gpeak()
                _kf = _dsf()
                _kf_rounded = round(_kf, 2)
                if _kf_rounded >= 1.0:
                    _tier = "TIER_1"
                elif _kf_rounded >= 0.70:
                    _tier = "TIER_2"
                elif _kf_rounded >= 0.30:
                    _tier = "TIER_3"
                elif _kf_rounded > 0.0:
                    _tier = "TIER_4"
                else:
                    _tier = "HALTED"
                peak_balance = round(_peak, 2)
                # WA-drift: was hardcoded to peak*0.80, baking in the DEFAULT 20%
                # drawdown halt. The real halt gate (paper.is_paused_drawdown) uses
                # MAX_DRAWDOWN_FRACTION, configurable via DRAWDOWN_HALT_PCT — if an
                # operator ever tightens/loosens it, this display drifts from where
                # trading actually halts, overstating or understating headroom.
                halt_floor = round(_peak * (1.0 - _max_dd_frac), 2)
                kelly_factor = round(_kf, 4)
                drawdown_pct = round(_dmax() * 100, 2)
                drawdown_tier = _tier
            except Exception:
                pass  # defaults already set above

            var_95: float | None = None
            var_99: float | None = None
            try:
                from monte_carlo import simulate_portfolio as _sim_portfolio

                _mc_open = get_open_trades()
                if _mc_open:
                    _mc_result = _sim_portfolio(
                        _mc_open, n_simulations=1000, include_distribution=True
                    )
                    _mc_dist = _mc_result.get("pnl_distribution", [])
                    _mc_n = len(_mc_dist)
                    if _mc_n > 0:
                        var_95 = round(_mc_dist[max(0, int(_mc_n * 0.05))], 2)
                        var_99 = round(_mc_dist[max(0, int(_mc_n * 0.01))], 2)
            except Exception:
                pass

            _brier_r, _brier_n = brier_score_rolling_with_n()
            data = {
                "balance": round(get_balance(), 2),
                "open_count": len(get_open_trades()),
                "brier": _brier_r,
                "brier_n": _brier_n,
                "fear_greed_score": fg_score,
                "fear_greed_label": fg_label,
                "mean_slippage_cents": mean_slippage,
                "kill_switch_active": _KS_PATH.exists(),
                "brier_drift": _drift,
                "today_pnl": today_pnl,
                "starting_balance": starting_balance,
                "daily_spend": daily_spend,
                "peak_balance": peak_balance,
                "halt_floor": halt_floor,
                "kelly_factor": kelly_factor,
                "drawdown_pct": drawdown_pct,
                "drawdown_tier": drawdown_tier,
                "var_95": var_95,
                "var_99": var_99,
                "timestamp": datetime.now(UTC).isoformat(),
                "kalshi_env": os.getenv("KALSHI_ENV", "demo"),
                "is_live": os.getenv("KALSHI_ENV", "demo").lower() == "prod",
            }
            try:
                from paper import get_portfolio_expected_value

                _ev = get_portfolio_expected_value()
                data["portfolio_ev"] = _ev["expected_profit_dollars"]
                data["portfolio_ev_roi_pct"] = _ev["expected_roi_pct"]
                data["portfolio_cost"] = _ev["total_cost_dollars"]
            except Exception:
                pass

            try:
                from weather_markets import _FEATURE_ACTIVATIONS_PATH

                _activations = (
                    json.loads(_FEATURE_ACTIVATIONS_PATH.read_text())
                    if _FEATURE_ACTIVATIONS_PATH.exists()
                    else {}
                )
            except Exception:
                _activations = {}
            data["feature_activations"] = _activations
        except Exception as e:
            # WA-status-code: was returning 200 with only an error key on total
            # failure — the frontend status poller and any uptime monitoring
            # treating 2xx as healthy would read undefined for balance,
            # kill_switch_active, drawdown_tier, etc. with no signal that this
            # dashboard's primary status endpoint is broken.
            return jsonify({"error": str(e)}), 500
        return jsonify(data)

    @app.route("/api/anomaly-status")
    def api_anomaly_status():
        """Current state of the win-rate anomaly detection window.

        Exposes the exact same window run_anomaly_check() -> check_anomalies()'s
        WIN RATE COLLAPSE gate evaluates, so the dashboard can show the
        current W/L list and how far the win rate is from the halt
        threshold.

        Deep-review followup: this endpoint used to independently rebuild
        the window with its own (stale) algorithm -- sorted by placed_at
        instead of settled_at, and filtered to outcome in ("yes","no"),
        which silently excludes early_exit trades that check_anomalies
        (via _recent_settled/_trade_won) does count -- so the dashboard
        could show a healthy window while a real halt fired on a genuinely
        different set of trades, or vice versa. get_win_rate_window() is
        the shared single source of truth both readers now call; the
        multi-day filter below matches run_anomaly_check's own filter
        (same-day METAR losses must not count toward this gate).
        """
        try:
            from alerts import (
                ALERT_HALT_THRESHOLDS,
                get_win_rate_window,
                run_anomaly_check,
            )
            from paper import load_paper_trades

            _multiday_trades = [
                t
                for t in load_paper_trades()
                if t.get("days_out") is None or t.get("days_out", 1) >= 1
            ]
            _wr = get_win_rate_window(_multiday_trades)

            halt_threshold = ALERT_HALT_THRESHOLDS["WIN_RATE_COLLAPSE"]  # 0.25
            min_samples = 5  # matches check_anomalies gate

            anomalies, should_halt = run_anomaly_check(log_results=False)

            return jsonify(
                {
                    "window_trades": _wr["window_trades"],
                    "n": _wr["n"],
                    "wins": _wr["wins"],
                    "losses": _wr["losses"],
                    "win_rate": _wr["win_rate"],
                    "halt_threshold": halt_threshold,
                    "min_samples": min_samples,
                    "anomaly_detected": bool(anomalies),
                    "should_halt": should_halt,
                    "anomaly_messages": anomalies,
                    "active": _wr["n"] >= min_samples,
                }
            )
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/calibration-status")
    def api_calibration_status():
        """Multi-day calibration gate status.

        Shows the F3 blend-weight auto-calibration gate (seasonal/city/condition
        weights — eligible at 50 settled trades, then every +25 thereafter) and,
        separately, the weekly temperature-scaling retrain timer. These are two
        distinct mechanisms on two distinct schedules (trade-count-gated vs a
        >=6-day marker-file timer) — WA-drift: this endpoint previously computed
        "next eligible" from temperature_scale.json's `global.n` (the temp-scaling
        fit's training-row count) as if it were the F3 gate's own state, but F3
        actually reads a different sentinel (data/.last_calibration_count) and
        temperature_scale.json isn't even written by the F3 code path — so the
        old eligibility figure matched neither real gate.
        """
        try:
            from tracker import count_settled_predictions

            current_n = count_settled_predictions()

            # F3 blend-weight gate — mirrors cron.py's real check exactly:
            # current_n >= 50 and current_n - last_cal_count >= 25.
            _cal_sentinel = Path(__file__).parent / "data" / ".last_calibration_count"
            last_calibration_n: int | None = None
            if _cal_sentinel.exists():
                try:
                    last_calibration_n = int(_cal_sentinel.read_text().strip())
                except Exception:
                    last_calibration_n = None
            next_eligible_n = (
                max(50, last_calibration_n + 25)
                if last_calibration_n is not None
                else 50
            )
            eligible = current_n >= next_eligible_n

            # Weekly temperature-scaling retrain — its own >=6-day marker-file
            # timer, independent of settled-trade count.
            _ml_retrain_path = Path(__file__).parent / "data" / ".last_ml_retrain"
            temp_scale_age_days: float | None = None
            temp_scale_eligible = True
            if _ml_retrain_path.exists():
                temp_scale_age_days = round(
                    (datetime.now(UTC).timestamp() - _ml_retrain_path.stat().st_mtime)
                    / 86400,
                    2,
                )
                temp_scale_eligible = temp_scale_age_days >= 6

            ts_path = Path(__file__).parent / "data" / "temperature_scale.json"
            T_global: float | None = None
            T_between: float | None = None
            T_above: float | None = None
            T_below: float | None = None

            if ts_path.exists():
                try:
                    _ts = json.loads(ts_path.read_text())
                    _global = _ts.get("global", {})
                    _between = _ts.get("between", {})
                    _above = _ts.get("above", {})
                    _below = _ts.get("below", {})
                    if isinstance(_global, dict):
                        T_global = _global.get("T")
                    if isinstance(_between, dict):
                        T_between = _between.get("T")
                    if isinstance(_above, dict):
                        T_above = _above.get("T")
                    if isinstance(_below, dict):
                        T_below = _below.get("T")
                except Exception:
                    pass

            return jsonify(
                {
                    "last_calibration_n": last_calibration_n,
                    "current_n": current_n,
                    "next_eligible_n": next_eligible_n,
                    "eligible": eligible,
                    "temp_scale_age_days": temp_scale_age_days,
                    "temp_scale_eligible": temp_scale_eligible,
                    "T_global": round(T_global, 4) if T_global is not None else None,
                    "T_between": round(T_between, 4) if T_between is not None else None,
                    "T_above": round(T_above, 4) if T_above is not None else None,
                    "T_below": round(T_below, 4) if T_below is not None else None,
                }
            )
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/scan-stats")
    def api_scan_stats():
        """Filter rejection counts from the most recent cron scan.

        Reads the filter_stats block written to signals_cache.json by cron.
        Returns an empty object if no scan has run yet.
        """
        cache_path = Path(__file__).parent / "data" / "signals_cache.json"
        if not cache_path.exists():
            return jsonify({"filters": {}, "gate_counts": {}, "total_scanned": 0})
        try:
            with open(cache_path, encoding="utf-8") as _f:
                _cache = json.load(_f)
            stats = _cache.get("filter_stats", {})
            return jsonify(
                {
                    "filters": stats.get("filters", {}),
                    "gate_counts": stats.get("gate_counts", {}),
                    "total_scanned": stats.get("total_scanned", 0),
                }
            )
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/emos-status")
    @_require_auth
    def api_emos_status():
        """Return EMOS parameter status — whether trained, params, and training date."""
        from paths import EMOS_PARAMS_PATH

        if not EMOS_PARAMS_PATH.exists():
            return jsonify(
                {
                    "trained": False,
                    "params": None,
                    "message": "Not trained. Run: py main.py emos-train",
                }
            )
        try:
            _emos = json.loads(EMOS_PARAMS_PATH.read_text())
            return jsonify(
                {
                    "trained": True,
                    "params": {
                        "a": round(_emos.get("a", 0), 4),
                        "b": round(_emos.get("b", 0), 4),
                        "c": round(_emos.get("c", 0), 4),
                        "d": round(_emos.get("d", 0), 4),
                        "n": _emos.get("n", 0),
                        "mean_crps": _emos.get("mean_crps"),
                    },
                    "fitted_at": _emos.get("fitted_at"),
                    "message": f"EMOS active (n={_emos.get('n', 0)} training rows)",
                }
            )
        except Exception as _exc:
            return jsonify(
                {
                    "trained": False,
                    "error": str(_exc),
                    "message": "Error reading emos_params.json",
                }
            )

    @app.route("/api/weather-alerts")
    @_require_auth
    def api_weather_alerts():
        """Fetch NWS active weather alerts for cities with open positions.

        Calls the free NWS Alerts API (no API key required).
        Returns list of {event, headline, city, severity} for Moderate+/Severe/Extreme alerts.
        Swallows per-city errors so one bad city never blocks the others.
        """
        import requests

        from paper import load_paper_trades
        from weather_markets import CITY_COORDS

        open_trades = [
            t
            for t in load_paper_trades()
            if not t.get("settled") and t.get("won") is None
        ]
        cities = list({t.get("city", "") for t in open_trades if t.get("city")})
        if not cities:
            return jsonify({"alerts": []})

        from concurrent.futures import ThreadPoolExecutor

        def _fetch_city_alerts(city: str) -> list[dict]:
            coords = CITY_COORDS.get(city)
            if not coords:
                return []
            lat, lon = coords[0], coords[1]
            try:
                resp = requests.get(
                    "https://api.weather.gov/alerts/active",
                    params={"point": f"{lat},{lon}"},
                    headers={
                        "User-Agent": "KalshiWeatherBot/1.0 (thesadcup@gmail.com)"
                    },
                    timeout=5,
                )
                resp.raise_for_status()
                out: list[dict] = []
                # WA-filter-order: NWS orders /alerts/active by sent time, not
                # severity, so slicing to the first 2 BEFORE filtering out
                # Minor/Unknown could drop a real Severe/Extreme alert sitting
                # behind two minor advisories — defeating the whole point of this
                # endpoint (surfacing weather risk to open positions). Filter first,
                # then cap.
                for feat in resp.json().get("features", []):
                    props = feat.get("properties", {})
                    severity = props.get("severity", "Unknown")
                    if severity in ("Minor", "Unknown"):
                        continue
                    if len(out) >= 2:
                        break
                    out.append(
                        {
                            "city": city,
                            "event": props.get("event", ""),
                            "headline": props.get("headline", ""),
                            "severity": severity,
                            "expires": props.get("expires", ""),
                        }
                    )
                return out
            except Exception:
                return []

        # WA-silent-truncation: cities is built from a set (unordered), so a [:8]
        # slice here would drop cities nondeterministically rather than by any
        # meaningful priority, silently never fetching alerts for open positions
        # in those cities. ThreadPoolExecutor(max_workers=8) already bounds
        # concurrency, so the slice added nothing but data loss — removed.
        with ThreadPoolExecutor(max_workers=8) as _pool:
            _city_results = list(_pool.map(_fetch_city_alerts, cities))
        alerts = [_a for _cr in _city_results for _a in _cr]

        return jsonify({"alerts": alerts})

    @app.route("/api/halt", methods=["POST"])
    def api_halt():
        """Write kill-switch file to stop cron from placing new trades."""
        from flask import request as _req

        body = _req.get_json(silent=True) or {}
        reason = body.get("reason", "manual halt via API")
        _KS_PATH.parent.mkdir(parents=True, exist_ok=True)
        _tmp = _KS_PATH.with_suffix(".tmp")
        _tmp.write_text(
            json.dumps({"reason": reason, "halted_at": datetime.now(UTC).isoformat()})
        )
        _tmp.replace(_KS_PATH)
        return jsonify({"halted": True, "reason": reason})

    @app.route("/api/resume", methods=["POST"])
    def api_resume():
        """Remove kill-switch file to allow cron to resume."""
        existed = _KS_PATH.exists()
        if existed:
            _KS_PATH.unlink()
        return jsonify({"resumed": True, "was_halted": existed})

    @app.route("/signals")
    def signals_page():
        return render_template("signals.html")

    @app.route("/api/signals")
    def api_signals():
        cron_log = Path(__file__).parent / "data" / "cron.log"
        entries = []
        if cron_log.exists():
            try:
                with open(cron_log, encoding="utf-8") as f:
                    lines = f.readlines()
                for line in lines[-500:]:
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

        # Deduplicate signal log by ticker — keep the most recent entry per ticker.
        # The cron appends on every run, so the same ticker accumulates across scans.
        # Showing the latest reading per market avoids confusing duplicate rows.
        _seen: dict[str, dict] = {}
        for e in entries:
            ticker = e.get("ticker", "")
            # Always replace — later entries are more recent (log is chronological)
            _seen[ticker] = e
        deduped = sorted(_seen.values(), key=lambda e: e.get("ts", ""), reverse=True)

        return jsonify({"log": deduped, "alerts": alerts[-50:]})

    @app.route("/forecast")
    def forecast_page():
        return render_template("forecast.html")

    @app.route("/api/today_forecasts")
    def api_today_forecasts():
        from datetime import date, timedelta

        from weather_markets import CITY_COORDS, get_weather_forecast

        today = date.today()
        tomorrow = today + timedelta(days=1)
        results: dict[str, dict] = {"today": {}, "tomorrow": {}}
        for city in sorted(CITY_COORDS):
            for label, dt in (("today", today), ("tomorrow", tomorrow)):
                try:
                    f = get_weather_forecast(city, dt)
                    if f:
                        results[label][city] = {
                            "high_f": round(f["high_f"], 1),
                            # WA-falsy-zero: `if f.get("low_f")` maps a legitimate
                            # 0.0F low (routine for Chicago/Denver/Minneapolis winter
                            # lows) to None, indistinguishable from "no forecast".
                            "low_f": round(f["low_f"], 1)
                            if f.get("low_f") is not None
                            else None,
                            "precip_in": round(f.get("precip_in", 0), 2),
                            "models_used": f.get("models_used", 1),
                            "high_range": list(
                                f.get("high_range", [f["high_f"], f["high_f"]])
                            ),
                        }
                except Exception:
                    pass
        return jsonify(results)

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

    @app.route("/api/ensemble-accuracy")
    def api_ensemble_accuracy():
        """ICON vs GFS per-model MAE from settled trades."""
        try:
            from tracker import get_ensemble_member_accuracy

            acc = get_ensemble_member_accuracy()
            return jsonify(acc or {})
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/source-reliability")
    def api_source_reliability():
        """Per-source forecast data success rate over last 30 days."""
        try:
            from tracker import get_source_reliability

            data = get_source_reliability()
            return jsonify(data or {})
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/circuit-status")
    def api_circuit_status():
        """Live circuit breaker state for all weather data sources."""
        try:
            from weather_markets import (
                _ecmwf_om_cb,
                _ensemble_cb,
                _forecast_cb,
                _nbm_om_cb,
                _pirate_cb,
                _weatherapi_cb,
            )

            def _cb_dict(cb):
                is_open = cb.is_open()
                return {
                    "state": "open" if is_open else "closed",
                    "failures": cb.failure_count,
                    "retry_in_s": round(cb.seconds_until_retry()) if is_open else 0,
                    "open_for_s": round(cb.seconds_open()),
                }

            return jsonify(
                {
                    "open_meteo_forecast": _cb_dict(_forecast_cb),
                    "open_meteo_ensemble": _cb_dict(_ensemble_cb),
                    "ecmwf_openmeteo": _cb_dict(_ecmwf_om_cb),
                    "nbm_openmeteo": _cb_dict(_nbm_om_cb),
                    "weatherapi": _cb_dict(_weatherapi_cb),
                    "pirate_weather": _cb_dict(_pirate_cb),
                }
            )
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/health/data-consistency")
    def api_data_consistency():
        """Cross-check dashboard data sources vs raw storage."""
        import os
        import time as _time

        checks: dict[str, object] = {}

        # Paper trade file count
        try:
            from paper import load_paper_trades

            trades = load_paper_trades()
            checks["paper_trades_count"] = len(trades)
        except Exception as exc:
            checks["paper_trades_count_error"] = str(exc)

        # paper_trades.json structural integrity
        try:
            from paper import validate_paper_trades_integrity as _vpt

            _integrity_errors = _vpt()
            checks["paper_trades_integrity"] = (
                "ok" if not _integrity_errors else _integrity_errors
            )
        except Exception as exc:
            checks["paper_trades_integrity_error"] = str(exc)

        # signals_cache.json age
        try:
            signals_path = Path(__file__).parent / "data" / "signals_cache.json"
            if signals_path.exists():
                age_secs = _time.time() - os.path.getmtime(signals_path)
                checks["signals_cache_age_secs"] = round(age_secs)
                checks["signals_cache_stale"] = age_secs > MAX_SIGNALS_CACHE_AGE_SECS
            else:
                checks["signals_cache_exists"] = False
        except Exception as exc:
            checks["signals_cache_error"] = str(exc)

        # Last cron run
        try:
            lock_path = Path(__file__).parent / "data" / ".cron.lock"
            if lock_path.exists():
                age_secs = _time.time() - os.path.getmtime(lock_path)
                checks["cron_lock_age_secs"] = round(age_secs)
            running_path = Path(__file__).parent / "data" / ".cron_running"
            checks["cron_currently_running"] = running_path.exists()
        except Exception as exc:
            checks["cron_lock_error"] = str(exc)

        # WA-misleading-success: was unconditionally {"ok": True}, even when a
        # check recorded a *_error key or a non-empty paper_trades_integrity
        # error list — the one route whose entire job is consistency checking
        # could report green during detected data corruption.
        _ok = not any(k.endswith("_error") for k in checks) and checks.get(
            "paper_trades_integrity"
        ) in ("ok", None)
        return jsonify({"ok": _ok, "checks": checks, "timestamp": _time.time()})

    # ------------------------------------------------------------------ #
    #  NEW DASHBOARD ENDPOINTS  (wired in React frontend v2)              #
    # ------------------------------------------------------------------ #

    @app.route("/api/config")
    def api_config():
        """BotConfig fields for the Settings tab."""
        try:
            import os as _os

            import utils as _utils
            from config import BotConfig

            cfg = BotConfig()
            return jsonify(
                {
                    "min_edge": cfg.min_edge,
                    "paper_min_edge": cfg.paper_min_edge,
                    "strong_edge": cfg.strong_edge,
                    "med_edge": cfg.med_edge,
                    "max_daily_spend": cfg.max_daily_spend,
                    "max_days_out": cfg.max_days_out,
                    "drawdown_halt_pct": cfg.drawdown_halt_pct,
                    "enable_micro_live": cfg.enable_micro_live,
                    "min_brier_samples": cfg.min_brier_samples,
                    "kalshi_fee_rate": cfg.kalshi_fee_rate,
                    # The rate this bot's own trades actually pay — see
                    # BotConfig.kalshi_maker_fee_rate's docstring.
                    "kalshi_maker_fee_rate": cfg.kalshi_maker_fee_rate,
                    # Env-var-only settings (not in BotConfig dataclass)
                    "env": _os.getenv("KALSHI_ENV", "demo"),
                    "strategy": _os.getenv("SIZING_STRATEGY", "kelly"),
                    # Same-day spend cap lives in utils, not BotConfig — read
                    # utils.py's live value directly rather than re-parsing the
                    # env var with a third, independently-drifting default.
                    "max_same_day_spend": _utils.MAX_SAME_DAY_SPEND,
                }
            )
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/ab-tests")
    def api_ab_tests():
        """A/B test summaries for the Settings tab."""
        try:
            from ab_test import list_all_summaries

            summaries = list_all_summaries()
            tests = [
                {
                    "name": name,
                    "variant": s.get("current_variant"),
                    "trades": s.get("total_trades", 0),
                    "edge_realized": s.get("edge_realized"),
                    "description": s.get("description", ""),
                }
                for name, s in summaries.items()
            ]
            return jsonify(tests)
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/override", methods=["GET"])
    def api_override_get():
        """Return current manual override state (or {active: false})."""
        from paths import MANUAL_OVERRIDE_PATH as _ov_path

        if not _ov_path.exists():
            return jsonify({"active": False, "override_until": None})
        try:
            state = json.loads(_ov_path.read_text())
            # WA-stale-state: was reporting active:true from file existence alone,
            # never checking expires_at against now — the real consumer
            # (cron._check_manual_override) treats an expired override as
            # inactive and auto-clears the file, so between expiry and the next
            # cron cycle (unbounded if cron is stopped) this endpoint showed
            # "Override active" for a pause that no longer takes effect.
            _expires = state.get("expires_at")
            _active = True
            if isinstance(_expires, int | float):
                _active = time.time() <= _expires
            # else: legacy ISO-string format (pre-fix web-set override) — can't
            # compare without parsing ambiguity, so fall back to file-existence.
            return jsonify({"active": _active, "override_until": _expires, **state})
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/override", methods=["POST"])
    def api_override_set():
        """Set a time-limited manual override. Body: {reason, duration_minutes}."""
        from flask import request as _req

        body = _req.get_json(silent=True) or {}
        reason = body.get("reason", "manual override via dashboard")
        # WA-input-validation: was outside any try (unlike the sibling
        # GET/POST/DELETE handlers in this route, which all return a JSON error
        # shape) — a non-numeric duration_minutes raised an unhandled
        # ValueError/TypeError, returning Flask's raw HTML 500 page. Also reject
        # non-positive durations: previously accepted and silently produced an
        # already-expired override while still responding {"set": True, ...}.
        try:
            minutes = int(body.get("duration_minutes", 60))
        except (TypeError, ValueError):
            return jsonify({"error": "duration_minutes must be an integer"}), 400
        if minutes <= 0:
            return jsonify({"error": "duration_minutes must be positive"}), 400
        minutes = min(minutes, 24 * 60)  # sanity cap: 24h
        # WA-format: created_at/expires_at must be Unix epoch floats, matching the
        # canonical writer (main.py cmd_override) and both numeric-comparison readers
        # (cron.py _check_manual_override, main.py cmd_override unpause/status). An
        # ISO string here previously made those comparisons raise TypeError, which
        # cron's fail-closed except treated as a permanently-active corrupted override
        # (never auto-expires) and made `py main.py override unpause` unable to clear it.
        now_epoch = time.time()
        state = {
            "reason": reason,
            "created_at": now_epoch,
            "expires_at": now_epoch + minutes * 60,
            "duration_minutes": minutes,
        }
        from paths import MANUAL_OVERRIDE_PATH as _ov_path

        _ov_path.parent.mkdir(parents=True, exist_ok=True)
        _tmp = _ov_path.with_suffix(".tmp")
        _tmp.write_text(json.dumps(state, indent=2))
        _tmp.replace(_ov_path)
        return jsonify({"set": True, **state})

    @app.route("/api/override", methods=["DELETE"])
    def api_override_clear():
        """Remove the manual override file."""
        from paths import MANUAL_OVERRIDE_PATH as _ov_path

        existed = _ov_path.exists()
        if existed:
            _ov_path.unlink()
        return jsonify({"cleared": True, "was_active": existed})

    @app.route("/api/backup-status")
    def api_backup_status():
        """Last backup time inferred from data/backups/ directory."""
        from datetime import UTC, datetime

        data_dir = Path(__file__).parent / "data"
        backup_dir = data_dir / "backups"
        result: dict = {
            "last_backup_at": None,
            "backup_size_mb": None,
            "backup_count": 0,
        }
        if backup_dir.exists():
            files = sorted(
                backup_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True
            )
            result["backup_count"] = len([f for f in files if f.is_file()])
            live_files = [f for f in files if f.is_file()]
            if live_files:
                latest = live_files[0]
                result["last_backup_at"] = datetime.fromtimestamp(
                    latest.stat().st_mtime, tz=UTC
                ).isoformat()
                result["backup_size_mb"] = round(latest.stat().st_size / 1_048_576, 3)
        # Also expose paper_trades.json mtime as a data-freshness proxy
        pt = data_dir / "paper_trades.json"
        if pt.exists():
            from datetime import UTC, datetime

            result["data_mtime"] = datetime.fromtimestamp(
                pt.stat().st_mtime, tz=UTC
            ).isoformat()
        return jsonify(result)

    @app.route("/api/feature-importance")
    def api_feature_importance():
        """Feature importance summary from the last cron run."""
        try:
            from feature_importance import get_feature_summary

            summary = get_feature_summary(min_trades=5)
            return jsonify(summary or {})
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/system-events")
    def api_system_events():
        """Synthesised event feed: recent orders + CB trips + override + kill switch."""
        events: list[dict] = []

        # Recent orders from execution_log.db
        try:
            from execution_log import get_recent_orders

            for o in get_recent_orders(limit=20):
                events.append(
                    {
                        "ts": o.get("placed_at", ""),
                        "level": "info" if o.get("status") == "filled" else "warn",
                        "text": (
                            f"Order: {o.get('ticker')} {(o.get('side') or '').upper()} "
                            f"x{o.get('quantity')} @ {float(o.get('price') or 0):.2f} "
                            f"[{o.get('status', '')}]"
                        ),
                        "source": "order",
                    }
                )
        except Exception:
            pass

        # Kill switch
        if _KS_PATH.exists():
            # WA-observability: /api/halt writes JSON, but the automatic black-swan
            # halt (alerts.py) and the CLI `py main.py kill` both create the kill
            # switch via a bare touch() — a zero-byte file. json.loads("") raised
            # here and the bare except below silently dropped the event, so exactly
            # the moment this feed matters most (an automatic emergency halt) it
            # showed nothing. Fall back to an mtime-derived event instead of
            # dropping it when the file can't be parsed as JSON.
            try:
                ks = json.loads(_KS_PATH.read_text())
                events.append(
                    {
                        "ts": ks.get("halted_at", ""),
                        "level": "warn",
                        "text": f"⛔ Kill switch active: {ks.get('reason', 'manual halt')}",
                        "source": "kill_switch",
                    }
                )
            except Exception:
                try:
                    _ks_mtime = datetime.fromtimestamp(
                        _KS_PATH.stat().st_mtime, tz=UTC
                    ).isoformat()
                except Exception:
                    _ks_mtime = ""
                events.append(
                    {
                        "ts": _ks_mtime,
                        "level": "warn",
                        "text": "⛔ Kill switch active (no reason recorded)",
                        "source": "kill_switch",
                    }
                )

        # Manual override
        from paths import MANUAL_OVERRIDE_PATH as _ov_path

        if _ov_path.exists():
            try:
                ov = json.loads(_ov_path.read_text())
                # WA-format-regression: created_at/expires_at are now Unix epoch
                # floats (matching the canonical writer, see the /api/override POST
                # handler) rather than the ISO strings this feed used to assume.
                # Format both to ISO here: (a) so "ts" stays comparable against the
                # kill-switch event's ISO "halted_at" in the sort below (a raw float
                # vs. str comparison there raises TypeError and 500s the whole
                # endpoint), and (b) so the displayed expiry doesn't crash on
                # str-slicing a float (previously silently dropped this event
                # entirely via the bare except below).
                _ov_created = ov.get("created_at", "")
                _ov_expires = ov.get("expires_at", "")
                _ov_created_iso = (
                    datetime.fromtimestamp(_ov_created, tz=UTC).isoformat()
                    if isinstance(_ov_created, int | float)
                    else str(_ov_created)
                )
                _ov_expires_iso = (
                    datetime.fromtimestamp(_ov_expires, tz=UTC).isoformat()
                    if isinstance(_ov_expires, int | float)
                    else str(_ov_expires)
                )
                events.append(
                    {
                        "ts": _ov_created_iso,
                        "level": "info",
                        "text": (
                            f"Override active until {_ov_expires_iso[:16]}: "
                            f"{ov.get('reason', '')}"
                        ),
                        "source": "override",
                    }
                )
            except Exception:
                pass

        events.sort(key=lambda e: e.get("ts", ""), reverse=True)
        return jsonify(events[:30])

    @app.route("/api/forecast-cache")
    def api_forecast_cache_info():
        """Forecast cache metadata (size, age, staleness)."""
        import time as _time
        from datetime import UTC, datetime

        cache_file = Path(__file__).parent / "data" / "forecast_cache.json"
        if not cache_file.exists():
            return jsonify(
                {"entries": 0, "age_seconds": None, "stale": True, "last_updated": None}
            )
        try:
            age = _time.time() - cache_file.stat().st_mtime
            data = json.loads(cache_file.read_text())
            return jsonify(
                {
                    "entries": len(data),
                    "age_seconds": round(age),
                    "stale": age > 3600,
                    "last_updated": datetime.fromtimestamp(
                        cache_file.stat().st_mtime, tz=UTC
                    ).isoformat(),
                }
            )
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/forecast-cache/invalidate", methods=["POST"])
    def api_forecast_cache_invalidate():
        """Delete the on-disk forecast cache so the next cron run rebuilds it."""
        cache_file = Path(__file__).parent / "data" / "forecast_cache.json"
        if cache_file.exists():
            cache_file.unlink()
            return jsonify({"cleared": True})
        return jsonify({"cleared": False, "note": "cache file not present"})

    @app.route("/api/execution-log")
    def api_execution_log():
        """Recent orders from execution_log.db (last 50)."""
        try:
            from execution_log import get_recent_orders

            return jsonify(get_recent_orders(limit=50))
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/settlement-signals")
    def api_settlement_signals():
        """Active settlement signals from the monitor (last 4 h)."""
        try:
            from settlement_monitor import read_settlement_signals

            return jsonify(read_settlement_signals(max_age_minutes=240))
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/city-brier")
    def api_city_brier():
        """Simple {city: brier_score} map for the Forecast tab heatmap."""
        try:
            from tracker import get_calibration_by_city

            cal = get_calibration_by_city() or {}
            result = {
                city: d.get("brier")
                for city, d in cal.items()
                if d.get("brier") is not None
            }
            return jsonify(result)
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/ml-models")
    def api_ml_models():
        """Which cities have trained ML bias-correction models."""
        try:
            from ml_bias import has_ml_model
            from weather_markets import CITY_COORDS

            return jsonify({city: has_ml_model(city) for city in sorted(CITY_COORDS)})
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/stress-test")
    def api_stress_test():
        """Tail-risk stress test scenarios: heat wave, cold snap, total model failure."""
        from monte_carlo import run_stress_test

        return jsonify(
            {
                "heat_wave": run_stress_test("heat_wave_failure"),
                "cold_snap": run_stress_test("cold_snap_failure"),
                "total": run_stress_test("total_model_failure"),
            }
        )

    @app.route("/api/paper-order", methods=["POST"])
    def api_paper_order():
        """Manually place a paper trade from the Signals tab Approve button.

        Body (JSON):
          ticker       str   required
          side         str   "yes" | "no"
          quantity     int   default 1
          entry_price  float (0, 1]  required
          entry_prob   float optional
          net_edge     float optional

        city/target_date are derived server-side from the ticker (not read
        from the request body) so the exposure caps and the saved trade
        record can't be bypassed or corrupted by a client-supplied value.
        """
        from cron import KILL_SWITCH_PATH as _ksp

        if _ksp.exists():
            return jsonify({"error": "kill switch active — trading paused"}), 503
        from utils import is_trading_paused as _is_trading_paused

        if _is_trading_paused():
            return jsonify({"error": "TRADING_PAUSED is set — trading disabled"}), 503

        from paper import place_paper_order

        body = _flask_request.get_json(force=True, silent=True) or {}
        ticker = body.get("ticker", "").strip()
        side = body.get("side", "yes").strip().lower()
        if not ticker:
            return jsonify({"error": "ticker required"}), 400
        if side not in ("yes", "no"):
            return jsonify({"error": "side must be yes or no"}), 400
        try:
            entry_price = float(body["entry_price"])
        except (KeyError, TypeError, ValueError):
            return jsonify({"error": "entry_price required"}), 400
        quantity = int(body.get("quantity", 1)) or 1
        # Cap quantity at Kelly limit so the dashboard cannot oversize a trade
        try:
            from paper import kelly_quantity as _kq_cap

            # Maker fee (not taker): manual quick-buy orders route through the
            # same maker (resting midpoint GTC limit) execution as everything
            # else -- see KALSHI_MAKER_FEE_RATE.
            from utils import KALSHI_MAKER_FEE_RATE as _fee_cap
            from weather_markets import kelly_fraction as _kf_cap

            _ep_raw = body.get("entry_prob")
            if _ep_raw is not None:
                _our_prob = max(0.01, min(0.99, float(_ep_raw)))
                _kf_val = _kf_cap(_our_prob, entry_price, _fee_cap)
                _max_qty = _kq_cap(_kf_val, entry_price)
                # WA-cap-skip: previously `if _max_qty > 0` skipped the clamp
                # entirely when Kelly says stake should be ~0 (no/negative edge) —
                # exactly the case the cap most needs to apply, since the raw
                # client-submitted quantity then passed through completely
                # unbounded. Always clamp, and reject outright when Kelly sizing
                # says there's no edge to size at all (a 0-quantity trade record
                # would be meaningless to place anyway).
                quantity = min(quantity, _max_qty)
                if quantity <= 0:
                    # kelly_bet_dollars can return 0 for reasons besides "no edge"
                    # (a drawdown-scaling halt, streak pause, or tiny balance), so
                    # the message doesn't claim a specific cause.
                    return jsonify(
                        {
                            "error": (
                                "sizing at this price and quantity rounds to 0 "
                                "contracts (no edge, drawdown halt, streak pause, "
                                "or balance too low) — refusing to place the order"
                            )
                        }
                    ), 400
            else:
                # WA-inversion: entry_price alone can't stand in for our
                # probability estimate. entry_price is the price PAID for the
                # requested side (the NO price for side="no", not a YES
                # probability) — the previous fallback set our_prob = entry_price
                # (or 1-entry_price for "no", inverting the side convention), which
                # for side="yes" makes our_prob == price and mathematically
                # guarantees ~zero modeled edge for ANY entry_prob-less request,
                # not because the trade has no real edge but purely as an artifact
                # of the fallback. Skip the Kelly cap in this case (matching the
                # bot's own log_prediction fallback for the same missing field)
                # rather than either computing a meaningless capped quantity or
                # forcing a spurious reject — the per-market/portfolio caps in
                # place_paper_order and check_position_limits below still bound
                # the trade regardless.
                _log.info(
                    "api/paper-order: entry_prob omitted for %s, skipping Kelly "
                    "cap (entry_price alone can't estimate edge)",
                    ticker,
                )
        except Exception as _kelly_cap_exc:
            # Was a bare except: pass — a failure here silently let the raw,
            # unclamped user-submitted quantity through with no trace.
            _log.warning(
                "api/paper-order: Kelly cap computation failed for %s, "
                "quantity unclamped: %s",
                ticker,
                _kelly_cap_exc,
            )
        entry_prob = body.get("entry_prob")
        net_edge = body.get("net_edge")

        # Deep-review followup: city/target_date used to come straight from
        # the client-supplied JSON body -- a request that simply omitted
        # them (or a buggy/malicious client) bypassed the city/date,
        # directional, and correlated exposure caps entirely, AND the saved
        # trade record itself got a client-controlled (possibly wrong or
        # missing) city/date, corrupting future exposure sums that key off
        # it too. Derive both server-side from the ticker via the market
        # lookup, matching main.py's quick-buy fix, instead of trusting the
        # request body. Reuses this same market fetch for close_time below
        # rather than hitting the API twice.
        city: str | None = None
        target_date: str | None = None
        _market_for_order: dict | None = None
        _mkt_prices_dash: dict | None = None
        try:
            from kalshi_client import KalshiClient as _KC
            from weather_markets import enrich_with_forecast as _ewf_dash
            from weather_markets import parse_market_price as _pmp_dash

            _kc = _KC(
                key_id=os.getenv("KALSHI_KEY_ID"),
                private_key_path=os.getenv("KALSHI_PRIVATE_KEY_PATH"),
                env=os.getenv("KALSHI_ENV", "demo"),
            )
            _market_for_order = _kc.get_market(ticker)
            _enriched_dash = _ewf_dash(_market_for_order, fetch_forecast=False)
            city = _enriched_dash.get("_city")
            _tdate_dash = _enriched_dash.get("_date")
            target_date = _tdate_dash.isoformat() if _tdate_dash else None
            _mkt_prices_dash = _pmp_dash(_market_for_order)
        except Exception as _enrich_exc:
            _log.warning(
                "api/paper-order: could not derive city/date for %s: %s",
                ticker,
                _enrich_exc,
            )

        # WA-security: fail CLOSED, not open, when server-side city/date derivation
        # didn't succeed. This used to log a warning and place the order anyway:
        # (a) exposure caps (city/date, directional, correlated) got skipped
        # entirely, (b) the saved trade record got city=None/target_date=None,
        # permanently invisible to all FUTURE exposure sums keyed on them, (c)
        # close_time=None disabled the 24h settlement gate and stop-loss/breakeven
        # exits, and (d) log_prediction (below) skips city=None rows so the trade
        # never registers in tracker — the exact "stuck open forever" failure that
        # call exists to prevent. A Kalshi API blip, a typo'd ticker, or (standalone
        # `py web.py` runs, which never call load_dotenv) unloaded env keys would
        # otherwise silently sail every order through this path.
        if not (city and target_date):
            return jsonify(
                {
                    "error": (
                        f"could not verify market data for {ticker} — "
                        "refusing to place order without exposure-cap checks"
                    )
                }
            ), 503

        # WA-security: entry_price is otherwise taken entirely from the client body.
        # The real frontend Approve flow sends market_prob/100 (the YES-side implied
        # probability) regardless of side, so approving a NO-side signal previously
        # booked entry_price at the YES price — e.g. a fairly-priced NO at ~0.20 got
        # recorded (and paid for) at ~0.80, a ~4x cost/exposure overstatement. Reject
        # rather than silently accept when the client price deviates too far from the
        # real market's side-appropriate price, computed from the same market dict
        # already fetched above (mirrors order_executor.py's own fill convention:
        # yes_ask for YES, 1 - yes_bid for NO).
        if _mkt_prices_dash and _mkt_prices_dash.get("has_quote"):
            _expected_side_price = (
                _mkt_prices_dash["yes_ask"]
                if side == "yes"
                else max(0.0, round(1.0 - _mkt_prices_dash["yes_bid"], 4))
            )
            if (
                _expected_side_price > 0
                and abs(entry_price - _expected_side_price) > 0.15
            ):
                return jsonify(
                    {
                        "error": (
                            f"entry_price {entry_price:.2f} deviates from the "
                            f"current {side}-side market price "
                            f"{_expected_side_price:.2f} by more than 0.15 — "
                            "refusing to place (stale price or wrong-side price?)"
                        )
                    }
                ), 400

        # #2: enforce the same city/date, directional, and correlated-group
        # exposure caps the auto-sizing path already respects — this dashboard
        # order path previously only capped Kelly quantity and per-market/
        # total-portfolio exposure (via place_paper_order's own internal
        # checks), never these three.
        try:
            from paper import check_position_limits as _cpl_dash

            _limit_dash = _cpl_dash(
                ticker,
                quantity,
                entry_price,
                city=city,
                target_date_str=target_date,
                side=side,
            )
            if not _limit_dash.get("ok", True):
                return jsonify(
                    {"error": _limit_dash.get("reason", "position limit exceeded")}
                ), 400
        except Exception as _limit_exc:
            # WA-security: fail closed here too — this used to silently skip the
            # limit check and let the order through unchecked on any
            # check_position_limits error (e.g. a DB read failure), the same
            # fail-open failure mode as the city/date derivation above.
            _log.warning(
                "api/paper-order: check_position_limits failed for %s: %s",
                ticker,
                _limit_exc,
            )
            return jsonify(
                {"error": f"could not verify exposure limits for {ticker}"}
            ), 503
        # WA-trusted-client: days_out (0 = same-day METAR, 1+ = multi-day forecast)
        # used to be read from the client body even though target_date is already
        # derived server-side just above — the real frontend Approve payload never
        # sends days_out at all, so every dashboard trade stored days_out=None,
        # which order_executor's multi-day slot cap (`!= 0`) reads as multi-day,
        # incorrectly consuming a MAX_POSITIONS_PER_DATE slot for same-day trades.
        # A client that DID send it could also lie (days_out=0 on a multi-day
        # trade) to dodge multi-day-slot accounting entirely. Derive it server-side
        # from target_date instead, matching tracker.py's own convention.
        from utils import utc_today as _utc_today_dash

        _days_out = (
            max(0, (_tdate_dash - _utc_today_dash()).days)
            if _tdate_dash is not None
            else None
        )
        # close_time so the 24h settlement gate works on manually placed
        # trades the same way it does on bot-placed trades — reuses the
        # market dict already fetched above for city/date derivation.
        _close_time: str | None = (
            _market_for_order.get("close_time") if _market_for_order else None
        )
        try:
            trade = place_paper_order(
                ticker=ticker,
                side=side,
                quantity=quantity,
                entry_price=entry_price,
                entry_prob=float(entry_prob) if entry_prob is not None else None,
                net_edge=float(net_edge) if net_edge is not None else None,
                city=city,
                target_date=target_date,
                thesis="manual approval via dashboard",
                days_out=_days_out,
                close_time=_close_time,
            )
            # Register in tracker predictions so sync_outcomes / auto_settle
            # can find the Kalshi outcome automatically when the market resolves.
            # Without this, only trades placed by cron end up in predictions and
            # web-placed trades were silently stuck open forever.
            try:
                import datetime as _dt_wa

                from tracker import log_prediction as _log_pred_wa

                # WA-inversion: forecast_prob/market_prob are scored against
                # settled_yes as YES-side probabilities (tracker.py Brier/
                # calibration), but entry_price is the price PAID for the
                # requested SIDE (the NO price for side="no", per paper.py's
                # convention — same as order_executor.py's own fill price).
                # Storing entry_price verbatim as both fields previously recorded
                # an inverted "forecast" for every NO-side trade (and a fake
                # market_prob), silently polluting the rolling-Brier/calibration
                # guards that gate live trading. Convert to YES-side for both.
                _yes_side_price = (1.0 - entry_price) if side == "no" else entry_price
                _ep = float(entry_prob) if entry_prob is not None else _yes_side_price
                _td_wa: _dt_wa.date | None = None
                if target_date:
                    try:
                        _td_wa = _dt_wa.date.fromisoformat(target_date)
                    except ValueError:
                        pass
                _log_pred_wa(
                    ticker,
                    city,  # None is handled inside log_prediction (skips if None)
                    _td_wa,
                    {
                        "forecast_prob": _ep,
                        "market_prob": _yes_side_price,
                        "edge": float(net_edge) if net_edge is not None else 0.0,
                        "recommended_side": side,
                        "condition": {},
                    },
                    signal_source="dashboard",
                )
            except Exception as _pe:
                _log.debug("api_paper_order: tracker log_prediction failed: %s", _pe)
            return jsonify({"ok": True, "trade_id": trade.get("id")}), 201
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/close-position", methods=["POST"])
    def api_close_position():
        """Close an open paper trade early at the current mark price.

        Body (JSON):
          trade_id    int    required
          exit_price  float  (0, 1] required — current mark price
        """
        from paper import close_paper_early

        body = _flask_request.get_json(force=True, silent=True) or {}
        try:
            trade_id = int(body["trade_id"])
        except (KeyError, TypeError, ValueError):
            return jsonify({"error": "trade_id required"}), 400
        try:
            exit_price = float(body["exit_price"])
        except (KeyError, TypeError, ValueError):
            return jsonify({"error": "exit_price required"}), 400
        # WA-security: exit_price is client-supplied with no market cross-check.
        # close_paper_early() does no validation of its own (unlike place_paper_order's
        # entry_price, which enforces the same (0, 1] range), so an out-of-range value —
        # including the real frontend's `pos.mark || 0` fallback when quote data is
        # missing — would otherwise silently book a bogus/100%-loss P&L. Enforce the
        # same (0, 1] contract this route's own docstring already promises.
        if not (0.0 < exit_price <= 1.0):
            return jsonify({"error": "exit_price must be in (0, 1]"}), 400
        try:
            trade = close_paper_early(trade_id, exit_price)
            return jsonify({"ok": True, "pnl": trade.get("pnl")}), 200
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 404
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

    # ------------------------------------------------------------------ #
    #  ADAPTER ROUTES  (React dashboard — clean JSON, no Jinja2 shape)   #
    # ------------------------------------------------------------------ #

    @app.route("/api/opportunities")
    def api_opportunities():
        """Enriched alias of /api/suggested_bets with star ratings and flag fields."""
        from flask import request as _freq

        from paper import get_balance, get_open_trades
        from paper import kelly_bet_dollars as _kbd_opp
        from utils import MIN_EDGE
        from weather_markets import (
            analyze_trade,
            detect_hedge_opportunity,
            enrich_with_forecast,
            get_weather_markets,
        )

        try:
            n = max(1, min(int(_freq.args.get("n", 10)), 50))
        except (TypeError, ValueError):
            n = 10

        try:
            markets = get_weather_markets(client)
        except Exception as exc:  # noqa: BLE001
            return jsonify({"error": str(exc), "opportunities": []}), 500

        balance = get_balance()
        open_trades = get_open_trades()
        results: list[dict] = []

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
                # WA-drift: same fix as /api/suggested_bets — use the canonical
                # paper.kelly_bet_dollars instead of a bare kelly*balance, which
                # ignored the drawdown-scaling gate (incl. its 0.0 HALTED tier),
                # half-Kelly/strategy scaling, streak pause, per-method Brier
                # scaling, and the dynamic/tier Brier cap.
                kelly_dollars = _kbd_opp(float(kelly))
                edge_pct = round(net_edge * 100, 1)
                if edge_pct >= 15:
                    stars = "★★★"
                elif edge_pct >= 10:
                    stars = "★★"
                else:
                    stars = "★"
                results.append(
                    {
                        "ticker": m.get("ticker", ""),
                        "title": (m.get("title") or m.get("ticker", ""))[:60],
                        # WA-drift: enrich_with_forecast() returns a NEW dict
                        # rather than mutating `m` in place — `_city` only ever
                        # lands on `enriched`, so reading it from `m` always fell
                        # back to "—" for every opportunity.
                        "city": enriched.get("_city") or "—",
                        "recommended_side": analysis.get("recommended_side", "yes"),
                        "edge_pct": edge_pct,
                        "kelly_fraction": round(float(kelly), 4),
                        "kelly_dollars": kelly_dollars,
                        "suggested_dollars": kelly_dollars,
                        "forecast_prob": round(
                            float(analysis.get("forecast_prob", 0)) * 100, 1
                        ),
                        "market_prob": round(
                            float(analysis.get("market_prob", 0)) * 100, 1
                        ),
                        "signal": analysis.get("signal", "—"),
                        "stars": stars,
                        "near_threshold": bool(analysis.get("near_threshold", False)),
                        "is_hedge": detect_hedge_opportunity(analysis, open_trades),
                        "time_risk": analysis.get("time_risk", "—"),
                        "model_agreement": None,
                    }
                )
            except Exception:  # noqa: BLE001
                continue

        results.sort(key=lambda x: x["edge_pct"], reverse=True)
        return jsonify(
            {
                "opportunities": results[:n],
                "balance": round(balance, 2),
                "min_edge": MIN_EDGE,
                "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            }
        )

    @app.route("/api/alerts")
    def api_alerts():
        """Alias of /api/system-events — recent system events for the React dashboard."""
        return api_system_events()

    @app.route("/api/execution-quality")
    def api_execution_quality():
        """Reshape of /api/price-improvement — execution quality stats for the React UI."""
        try:
            from tracker import get_price_improvement_stats

            stats = get_price_improvement_stats()
            if stats is None:
                return jsonify(
                    {
                        "avg_improvement_cents": None,
                        "median_improvement_cents": None,
                        "positive_pct": None,
                        "total_trades": 0,
                        "note": "insufficient data (< 5 trades)",
                    }
                )
            return jsonify(
                {
                    "avg_improvement_cents": round(stats["mean"] * 100, 4),
                    "median_improvement_cents": round(stats["median"] * 100, 4),
                    "positive_pct": stats["positive_pct"],
                    "total_trades": stats["count"],
                }
            )
        except Exception as exc:  # noqa: BLE001
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/model-accuracy")
    def api_model_accuracy():
        """Combine /api/model-attribution + /api/city-brier into one response."""
        per_model: list[dict] = []
        try:
            from tracker import get_component_attribution

            for src, data in get_component_attribution().items():
                per_model.append(
                    {
                        "model": src,
                        "trades": data.get("n", 0),
                        "brier": round(float(data.get("brier", 0)), 4),
                        "win_rate": None,
                        "edge_realized": None,
                    }
                )
            per_model.sort(key=lambda x: x["brier"])
        except Exception as _pm_exc:  # noqa: BLE001
            # WA-observability: was a bare pass with no logging — a broken
            # tracker DB (locked/corrupt/schema mismatch) returned 200 with
            # per_model=[], indistinguishable from "no settled trades yet".
            # Matches the precedent already set in this same route's Kelly-cap
            # fix elsewhere in this file: log rather than silently swallow.
            _log.warning(
                "api/model-accuracy: get_component_attribution failed: %s", _pm_exc
            )

        city_brier: dict = {}
        try:
            from tracker import get_calibration_by_city

            for city, d in (get_calibration_by_city() or {}).items():
                if d.get("brier") is not None:
                    city_brier[city] = d["brier"]
        except Exception as _cb_exc:  # noqa: BLE001
            _log.warning(
                "api/model-accuracy: get_calibration_by_city failed: %s", _cb_exc
            )

        return jsonify({"per_model": per_model, "city_brier": city_brier})

    @app.route("/api/forecast")
    def api_forecast():
        """Per-city ensemble forecast for day=0 (today) or day=1 (tomorrow)."""
        from datetime import timedelta

        from flask import request as _freq

        from utils import utc_today as _utc_today_fc
        from weather_markets import CITY_COORDS, get_weather_forecast

        try:
            day = int(_freq.args.get("day", 0))
        except (TypeError, ValueError):
            day = 0

        if day not in (0, 1):
            return jsonify({"error": "day must be 0 or 1"}), 400

        # WA-timezone: was date.today() (server-local calendar), while the
        # tracker/analytics side of this codebase standardizes on
        # utils.utc_today() — around local midnight this dashboard's day=0
        # forecast could label a different date than what the trading logic
        # considers "today".
        target = _utc_today_fc() + timedelta(days=day)
        cities: dict[str, dict] = {}

        for city in sorted(CITY_COORDS):
            try:
                f = get_weather_forecast(city, target)
                if f:
                    cities[city] = {
                        "high_f": round(f["high_f"], 1),
                        # WA-falsy-zero: see /api/today_forecasts' identical fix —
                        # a legitimate 0.0F low must not be treated as missing.
                        "low_f": round(f["low_f"], 1)
                        if f.get("low_f") is not None
                        else None,
                        "precip_in": round(f.get("precip_in", 0), 2),
                        "models_used": f.get("models_used", 1),
                        "high_range": list(
                            f.get("high_range", [f["high_f"], f["high_f"]])
                        ),
                    }
            except Exception as _fc_exc:  # noqa: BLE001
                # WA-observability: was a bare pass with no logging — an upstream
                # forecast-provider outage rendered as silently-missing cities
                # with no way to tell "no data yet" from "the fetch is broken".
                _log.warning(
                    "api/forecast: get_weather_forecast(%s) failed: %s",
                    city,
                    _fc_exc,
                )

        return jsonify({"day": day, "date": target.isoformat(), "cities": cities})

    # ------------------------------------------------------------------ #

    @app.route("/api/reliability/<city>")
    def api_reliability(city: str):
        # WA-drift: was reimplementing 5-bin calibration bucketing with raw SQL
        # instead of calling tracker._calibration_curve, the canonical helper
        # that (per its own docstring) exists precisely so the bucket-edge
        # convention lives in one place. The reimplementation's edges
        # (0.0,0.2)...(0.8,1.0) with `lo <= p < hi` silently excluded
        # our_prob==1.0 from every bin (while still counting it in the
        # top-level n), unlike the canonical [0.0,...,1.001] edges.
        from tracker import _calibration_curve, _conn, init_db

        init_db()
        with _conn() as con:
            rows = con.execute(
                """
                SELECT p.our_prob, o.settled_yes
                FROM   multiday_predictions p
                JOIN   outcomes o ON o.ticker = p.ticker
                WHERE  p.city = ? AND p.our_prob IS NOT NULL
                ORDER  BY p.our_prob
                """,
                (city,),
            ).fetchall()

        if not rows:
            return jsonify({"bins": [], "city": city, "n": 0})

        curve = _calibration_curve([(p, o) for p, o in rows])
        result = [
            {
                "bin_lo": b["bucket_low"],
                "bin_hi": b["bucket_high"],
                "mean_pred": b["predicted_mean"],
                "actual_rate": b["actual_rate"],
                "n": b["n"],
            }
            for b in curve["calibration_buckets"]
        ]
        return jsonify({"bins": result, "city": city, "n": len(rows)})

    @app.route("/api/edge-realization")
    def api_edge_realization():
        from tracker import get_edge_realization_by_city

        return jsonify(get_edge_realization_by_city())

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


if __name__ == "__main__":
    # Run the dashboard standalone (no live Kalshi client — read-only paper mode)
    from kalshi_client import KalshiClient

    try:
        _standalone_client = KalshiClient()
    except Exception:
        _standalone_client = None  # type: ignore[assignment]

    start_web(_standalone_client, port=5000, open_browser=False)
