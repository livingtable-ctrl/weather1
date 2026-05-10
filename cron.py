"""cron.py — Background cron runner extracted from main.py.

Contains cmd_cron and its private cron-only helpers.
Path constants (LOCK_PATH, KILL_SWITCH_PATH, RUNNING_FLAG_PATH) are defined
here; main.py re-exports them.  Tests that need to redirect paths should
patch ``cron.LOCK_PATH`` (not ``main.LOCK_PATH``).
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC
from pathlib import Path

import execution_log
from colors import bold, cyan, dim, green, red, yellow
from kalshi_client import KalshiClient
from utils import (
    CITY_MIN_PROB_EDGE,
    DRIFT_TIGHTEN_EDGE,
    MAX_MARKET_DIVERGENCE_RATIO,
    MED_EDGE,
    MIN_EDGE,
    MIN_MARKET_PROB_TO_BET_WITH,
    MIN_PROB_EDGE,
    PAPER_MIN_EDGE,
    STRONG_EDGE,
)

# Use the "main" logger name so that existing tests which capture
# logging.getLogger("main") continue to see cron log output.
_log = logging.getLogger("main")


# ---------------------------------------------------------------------------
# Path constants (owned here; main.py re-exports them)
# ---------------------------------------------------------------------------

# P3.1 — graceful shutdown flag
RUNNING_FLAG_PATH: Path = Path(__file__).parent / "data" / ".cron_running"

# P3.4 — file-based cron lock (prevents concurrent cron instances)
LOCK_PATH: Path = Path(__file__).parent / "data" / ".cron.lock"

# P8.3 — hard kill switch path
KILL_SWITCH_PATH: Path = Path(__file__).parent / "data" / ".kill_switch"


# ---------------------------------------------------------------------------
# CronContext — explicit dependency injection replacing _main_module() hack
# ---------------------------------------------------------------------------


@dataclass
class CronContext:
    """All callable dependencies that cmd_cron needs from outside cron.py.

    Constructed in main.py at call-time so test monkeypatching of
    ``main.get_weather_markets`` etc. is picked up automatically.
    """

    # Lock / flag management (defined in cron.py, re-exported via main)
    acquire_cron_lock: Callable[[], bool]
    release_cron_lock: Callable[[], None]
    write_cron_running_flag: Callable[[], None]
    clear_cron_running_flag: Callable[[], None]

    # Startup checks (defined in cron.py / main.py)
    check_manual_override: Callable[[], bool]
    check_startup_orders: Callable[[], None]

    # Weather data (from weather_markets)
    get_weather_markets: Callable
    enrich_with_forecast: Callable
    analyze_trade: Callable
    get_weather_forecast: Callable
    fetch_temperature_nbm: Callable
    fetch_temperature_ecmwf: Callable
    fetch_temperature_weatherapi: Callable
    check_ensemble_circuit_health: Callable

    # Execution (from order_executor, re-exported via main)
    auto_place_trades: Callable
    check_early_exits: Callable

    # Outcome tracking (from tracker)
    sync_outcomes: Callable


# ---------------------------------------------------------------------------
# Exported cron helpers
# ---------------------------------------------------------------------------


def _write_cron_running_flag() -> None:
    """Write UTC ISO timestamp to RUNNING_FLAG_PATH; warn if a fresh flag already exists."""
    import time as _time

    rfp = RUNNING_FLAG_PATH
    try:
        if rfp.exists():
            age = _time.time() - rfp.stat().st_mtime
            if age < 600:
                _log.warning(
                    "cmd_cron: previous cron run may not have completed cleanly "
                    "(flag age=%.0fs < 600s)",
                    age,
                )
        rfp.parent.mkdir(exist_ok=True)
        rfp.write_text(
            __import__("datetime")
            .datetime.now(__import__("datetime").timezone.utc)
            .isoformat()
        )
    except Exception as _e:
        _log.warning("cmd_cron: could not write running flag: %s", _e)


def _clear_cron_running_flag() -> None:
    """Delete RUNNING_FLAG_PATH if it exists."""
    try:
        RUNNING_FLAG_PATH.unlink(missing_ok=True)
    except Exception as _e:
        _log.warning("cmd_cron: could not clear running flag: %s", _e)


def _check_startup_orders() -> None:
    """Warn if any orders were placed in the last 5 minutes (double-execution guard)."""
    import time as _time

    try:
        recent = execution_log.get_recent_orders(limit=50)
        cutoff = _time.time() - 300  # 5 minutes
        for order in recent:
            placed_at_str = order.get("placed_at", "")
            if not placed_at_str:
                continue
            try:
                from datetime import datetime as _dt

                placed_dt = _dt.fromisoformat(placed_at_str)
                if placed_dt.tzinfo is None:
                    placed_dt = placed_dt.replace(tzinfo=UTC)
                placed_ts = placed_dt.timestamp()
            except ValueError:
                continue
            if placed_ts >= cutoff:
                _log.warning(
                    "cmd_cron: recent order detected at startup — "
                    "possible double-execution (ticker=%s side=%s placed_at=%s)",
                    order.get("ticker", "?"),
                    order.get("side", "?"),
                    placed_at_str,
                )
    except Exception as _e:
        _log.warning("cmd_cron: _check_startup_orders failed: %s", _e)


try:
    import psutil as _psutil

    _PSUTIL_AVAILABLE = True
except ImportError:
    _PSUTIL_AVAILABLE = False


def _acquire_cron_lock() -> bool:
    """
    Try to acquire the cron file lock. Fail CLOSED on every error.

    Returns True only when the lock is cleanly written by this process.
    Returns False in every other case — including I/O errors — so a
    concurrent cron run is never allowed through on an unexpected failure.

    Stale detection is PID-aware when psutil is available:
    - Live PID  → block (another instance is really running).
    - Dead PID  → override (process is gone, lock is stale).
    - No psutil → conservative 1800 s age threshold before overriding.
    """
    import time as _time

    lp = LOCK_PATH
    try:
        if lp.exists():
            try:
                existing = json.loads(lp.read_text())
                pid = existing.get("pid")
                started_at = existing.get("started_at", 0)
                heartbeat = existing.get("heartbeat", started_at)
            except Exception as parse_err:
                # Unreadable / corrupt / old-format lock — treat as stale and remove.
                # Old cron versions wrote a plain integer PID; that dict.get() call
                # raises AttributeError. Safe to override: if a real process held the
                # lock it would have written the new JSON format.
                _log.warning(
                    "cmd_cron: unreadable lock file (%s) — treating as stale, removing",
                    parse_err,
                )
                try:
                    lp.unlink()
                except OSError:
                    pass

            if pid and _PSUTIL_AVAILABLE:
                if _psutil.pid_exists(pid):
                    age = _time.time() - started_at
                    _log.warning(
                        "cmd_cron: lock held by live PID %d (started %.0fs ago) — skipping",
                        pid,
                        age,
                    )
                    return False
                # PID is gone — safe to override.
                _log.warning("cmd_cron: overriding stale lock from dead PID %d", pid)
            else:
                # psutil unavailable — use conservative heartbeat age.
                age = _time.time() - heartbeat
                if age < 1800:
                    _log.warning(
                        "cmd_cron: lock age %.0fs < 1800s; refusing to override without psutil",
                        age,
                    )
                    return False
                _log.warning(
                    "cmd_cron: overriding stale lock (%.0fs old, psutil unavailable)",
                    age,
                )

        lp.parent.mkdir(exist_ok=True)
        lock_data = {
            "pid": os.getpid(),
            "started_at": _time.time(),
            "heartbeat": _time.time(),
        }
        lp.write_text(json.dumps(lock_data))
        return True

    except Exception as exc:
        _log.error(
            "cmd_cron: lock acquisition failed: %s — aborting (fail-closed)", exc
        )
        return False  # FAIL CLOSED — never proceed on unexpected error


def _release_cron_lock() -> None:
    """Delete the cron lock file."""
    try:
        LOCK_PATH.unlink(missing_ok=True)
    except Exception as _e:
        _log.warning("cmd_cron: could not release lock: %s", _e)


def _is_cron_running() -> bool:
    """Read-only check: return True if a cron process holds the lock right now.

    Uses the same PID-aware logic as _acquire_cron_lock but never writes.
    Returns False (not running) when the lock file is absent, stale, or unreadable,
    so callers default to allowing a new run rather than blocking indefinitely.
    """
    import time as _time

    lp = LOCK_PATH
    if not lp.exists():
        return False
    try:
        existing = json.loads(lp.read_text())
        pid = existing.get("pid")
        started_at = existing.get("started_at", 0)
        heartbeat = existing.get("heartbeat", started_at)
    except Exception:
        return False  # unreadable lock — treat as not running

    if pid and _PSUTIL_AVAILABLE:
        return bool(_psutil.pid_exists(pid))
    # psutil unavailable — treat as running only if the lock is recent
    return (_time.time() - heartbeat) < 1800


def _check_graduation_gate() -> None:
    """Prevent accidental live trading before enough settled predictions exist.

    Reads ENABLE_MICRO_LIVE env var. If 'true', verifies tracker has at least
    utils.MIN_BRIER_SAMPLES settled predictions before allowing live trading to proceed.

    Raises:
        RuntimeError: when ENABLE_MICRO_LIVE='true' and count < MIN_BRIER_SAMPLES.
    """
    if os.getenv("ENABLE_MICRO_LIVE", "false").lower() != "true":
        return

    import tracker
    import utils as _utils

    count = tracker.count_settled_predictions()
    if count < _utils.MIN_BRIER_SAMPLES:
        raise RuntimeError(
            f"Graduation gate: {count} settled predictions < "
            f"MIN_BRIER_SAMPLES={_utils.MIN_BRIER_SAMPLES}. "
            f"Set ENABLE_MICRO_LIVE=false or accumulate more paper trades."
        )


def _check_spend_cap_vs_balance() -> None:
    """Warn if MAX_DAILY_SPEND exceeds the current paper balance.

    A spend cap that exceeds the available balance can never trigger and indicates
    a config mistake.
    """
    import paper as _paper

    _bal = _paper.get_balance()
    _spend_cap = float(os.getenv("MAX_DAILY_SPEND", "0"))
    if _spend_cap > 0 and _spend_cap > _bal:
        logging.getLogger(__name__).warning(
            "[cron] MAX_DAILY_SPEND=%.2f exceeds current balance=%.2f — cap will never trigger",
            _spend_cap,
            _bal,
        )


def _check_manual_override() -> bool:
    """
    Returns True if a valid (non-expired) manual override is active.
    Auto-clears expired overrides.
    """
    import time as _time

    override_path = Path(__file__).parent / "data" / ".manual_override.json"
    if not override_path.exists():
        return False
    try:
        state = json.loads(override_path.read_text())
        expires = state.get("expires_at", 0)
        if _time.time() > expires:
            override_path.unlink(missing_ok=True)
            _log.info("_check_manual_override: expired override cleared")
            return False
        remaining = (expires - _time.time()) / 60
        _log.warning(
            "Manual override active — trading paused (%.0f min remaining): %s",
            remaining,
            state.get("reason", "manual pause"),
        )
        return True
    except Exception as exc:
        _log.debug("_check_manual_override: %s", exc)
        return False


_ANOMALY_THRESHOLD = 0.12  # pp drift required to flag a market


def check_market_anomalies(signals: list[dict]) -> list[dict]:
    """Return signals where |blended_prob − market_price| > _ANOMALY_THRESHOLD."""
    return [
        s
        for s in signals
        if abs(s.get("blended_prob", 0.5) - s.get("market_price", 0.5))
        > _ANOMALY_THRESHOLD
    ]


def report_anomalies(anomalies: list[dict]) -> None:
    """Print anomaly warnings; no-op when list is empty."""
    if not anomalies:
        return
    print(f"\n  Market anomalies ({len(anomalies)}) — price drifted against model:")
    for a in anomalies:
        ticker = a.get("ticker", "?")
        our = a.get("blended_prob", 0.0)
        mkt = a.get("market_price", 0.0)
        print(f"  {ticker:<35} our={our:.0%}  market={mkt:.0%}  drift={mkt - our:+.0%}")
    _log.warning("Anomalies flagged: %s", [a.get("ticker") for a in anomalies])


def _cmd_cron_body(
    ctx: CronContext, client: KalshiClient, min_edge: float = MIN_EDGE
) -> bool | None:
    """Core scan logic — extracted from cmd_cron so it can be wrapped in try/finally."""
    # P8.3 — hard kill switch: touch data/.kill_switch to halt immediately
    if KILL_SWITCH_PATH.exists():
        _log.critical(
            "KILL SWITCH ACTIVATED — halting cron execution immediately. Remove data/.kill_switch to resume."
        )
        print(
            red(
                "\n  \u26a0  KILL SWITCH ACTIVE \u2014 trading halted. Delete data/.kill_switch to resume.\n"
            )
        )
        return None

    # P8.4 — manual override check (time-limited pause)
    if ctx.check_manual_override():
        _log.warning("cmd_cron: manual override active — skipping this run")
        return None

    from paper import get_accuracy_halt_reason as _get_accuracy_halt_reason
    from paper import is_accuracy_halted as _is_accuracy_halted

    if _is_accuracy_halted():
        _reason = _get_accuracy_halt_reason()
        _log.warning(
            "ACCURACY HALT ACTIVE: %s — skipping all trades this cycle",
            _reason or "accuracy circuit breaker active",
        )
        return None

    # Graduation gate — prevent accidental live trading before sufficient predictions exist
    try:
        _check_graduation_gate()
    except RuntimeError as _gate_err:
        _log.error("%s", _gate_err)
        return None

    # Spend cap validation — warn if MAX_DAILY_SPEND exceeds current balance
    _check_spend_cap_vs_balance()

    from datetime import UTC, datetime

    print(
        cyan(
            f"  [cron] scan starting \u2014 {datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S')} UTC"
        ),
        flush=True,
    )

    # Weekly DB retention sweep (runs on Monday only)
    from utils import utc_today as _utc_today

    if _utc_today().weekday() == 0:  # Monday UTC
        from tracker import prune_api_requests as _prune_api
        from tracker import purge_old_predictions as _purge

        _purge(retention_days=730)
        _prune_api(days_to_keep=90)

        from feature_importance import prune_feature_log as _prune_features

        _prune_features()

    ctx.write_cron_running_flag()
    ctx.check_startup_orders()

    # Phase 1 — surface prolonged Open-Meteo outages immediately
    try:
        ctx.check_ensemble_circuit_health()
    except Exception as _e:
        _log.debug("cmd_cron: check_ensemble_circuit_health failed: %s", _e)

    # Phase 9 — snapshot circuit state so we can detect newly-opened circuits after scan
    try:
        from weather_markets import (
            _ensemble_cb,
            _forecast_cb,
            _pirate_cb,
            _weatherapi_cb,
        )

        _pre_scan_cb_states = {
            "open_meteo_forecast": _forecast_cb.is_open(),
            "open_meteo_ensemble": _ensemble_cb.is_open(),
            "weatherapi": _weatherapi_cb.is_open(),
            "pirate_weather": _pirate_cb.is_open(),
        }
        _scan_cbs = {
            "open_meteo_forecast": _forecast_cb,
            "open_meteo_ensemble": _ensemble_cb,
            "weatherapi": _weatherapi_cb,
            "pirate_weather": _pirate_cb,
        }
    except Exception as _e:
        _log.debug("cmd_cron: circuit state snapshot failed: %s", _e)
        _pre_scan_cb_states = {}
        _scan_cbs = {}

    # P8.2 — anomaly detection at start of cron cycle
    try:
        from alerts import run_anomaly_check as _run_anomaly_check

        _detected_anomalies, _should_halt = _run_anomaly_check(log_results=True)
        if _should_halt:
            _log.error(
                "cmd_cron: anomaly halt triggered — stopping trade placement this cycle: %s",
                _detected_anomalies,
            )
            return None
        elif _detected_anomalies:
            _log.warning(
                "cmd_cron: soft anomaly warnings (below halt threshold), continuing: %s",
                _detected_anomalies,
            )
    except Exception as _e:
        _log.debug("cmd_cron: run_anomaly_check failed: %s", _e)

    # Black swan emergency shutdown check
    try:
        from alerts import run_black_swan_check as _run_black_swan_check

        _bs_conditions = _run_black_swan_check()
        if _bs_conditions:
            _log.critical(
                "cmd_cron: BLACK SWAN conditions triggered — halting. Conditions: %s",
                _bs_conditions,
            )
            return None
    except Exception as _e:
        _log.debug("cmd_cron: run_black_swan_check failed: %s", _e)

    # Drift detection; tighten STRONG_EDGE for this run when drifting
    _effective_strong_edge = STRONG_EDGE
    _drift_result: dict = {"drifting": False}
    try:
        from tracker import detect_brier_drift as _detect_brier_drift

        _drift_result = _detect_brier_drift()
        if _drift_result["drifting"]:
            _effective_strong_edge = STRONG_EDGE + DRIFT_TIGHTEN_EDGE
            _log.warning(
                "cmd_cron: %s — tightening STRONG_EDGE to %.2f for this run",
                _drift_result["message"],
                _effective_strong_edge,
            )
    except Exception as _e:
        _log.debug("cmd_cron: detect_brier_drift failed: %s", _e)

    # Strategy retirement check (log-only, non-blocking)
    try:
        from tracker import auto_retire_strategies as _auto_retire

        _newly_retired = _auto_retire()
        if _newly_retired:
            _log.warning("cmd_cron: auto-retired strategy methods: %s", _newly_retired)
    except Exception as _e:
        _log.debug("cmd_cron: auto_retire_strategies failed: %s", _e)

    # Config integrity check (log warning if changed)
    try:
        from utils import check_config_integrity as _check_config_integrity

        _cfg = _check_config_integrity()
        if _cfg["changed"]:
            _log.warning(
                "cmd_cron: config changed since last run — keys: %s",
                _cfg["changed_keys"],
            )
    except Exception as _e:
        _log.debug("cmd_cron: check_config_integrity failed: %s", _e)

    # Optional: start WebSocket for real-time price feeds.
    # Created here; subscribed and started after market list is fetched so the
    # subscribe() call (which must precede start()) has real tickers to use.
    _ws = None
    try:
        from kalshi_ws import KalshiWebSocket

        api_key = os.getenv("KALSHI_API_KEY", "")
        key_pem = os.getenv("KALSHI_PRIVATE_KEY_PEM", "")
        if api_key and key_pem:
            _ws = KalshiWebSocket(api_key, key_pem)
    except Exception as exc:
        _log.debug("WebSocket not available: %s", exc)

    from kalshi_ws import get_ws_health as _get_ws_health

    _ws_h = _get_ws_health()
    if _ws_h["stale"]:
        _log.warning(
            "[cron] WebSocket cache is stale (idle %.0fs) — mid-prices may be unreliable",
            _ws_h["idle_secs"],
        )

    log_path = Path(__file__).parent / "data" / "cron.log"
    log_path.parent.mkdir(exist_ok=True)
    if log_path.exists() and log_path.stat().st_size > 5 * 1024 * 1024:
        try:
            log_path.replace(log_path.with_suffix(".log.1"))
        except OSError:
            pass

    # P0.5: Log state snapshot at the start of every cron run for consistency auditing.
    try:
        from paper import get_state_snapshot

        snap = get_state_snapshot()
        _log.info(
            "cmd_cron: state snapshot balance=%.2f open_trades=%d peak=%.2f",
            snap["balance"],
            snap["open_trades_count"],
            snap["peak_balance"],
        )
    except Exception as _e:
        _log.warning("cmd_cron: could not capture state snapshot: %s", _e)

    med_opps: list = []  # edge 15–24%, LOW or MEDIUM risk
    strong_opps: list = []  # edge 25%+, any time risk
    signals_cache: list = []
    scanned = 0
    _consistency_skip = False  # P3-14: init before try so it is always bound
    try:
        from concurrent.futures import ThreadPoolExecutor
        from concurrent.futures import as_completed as _as_completed

        markets = ctx.get_weather_markets(client)
        scanned = len(markets)
        print(dim(f"  [cron] scanning {scanned} market(s)\u2026"), flush=True)

        # P3-14: consistency check \u2014 log violations; halt auto-trading if too many
        try:
            from consistency import find_violations as _find_violations

            _violations = _find_violations(markets)
            if _violations:
                _log.warning(
                    "cmd_cron: %d consistency violation(s) detected: %s",
                    len(_violations),
                    [v.description for v in _violations[:5]],
                )
                if len(_violations) > 5:
                    _consistency_skip = True
                    _log.error(
                        "cmd_cron: %d violations exceed threshold (5) \u2014 skipping auto-trading this cycle",
                        len(_violations),
                    )
        except Exception as _ce:
            _log.debug("cmd_cron: consistency check failed: %s", _ce)

        if _ws is not None:
            try:
                _ws_tickers = [m.get("ticker") for m in markets if m.get("ticker")]
                if _ws_tickers:
                    _ws.subscribe(_ws_tickers)
                _ws.start()
                _log.info(
                    "WebSocket thread started with %d ticker(s)", len(_ws_tickers)
                )
            except Exception as _ws_exc:
                _log.debug("WebSocket start failed: %s", _ws_exc)
                _ws = None

        # Pre-warm forecast/model caches for all unique city/date pairs so the
        # parallel scan hits cache instead of making redundant network requests.
        _city_dates: set[tuple[str, str]] = set()
        for _m in markets:
            _enriched_preview = ctx.enrich_with_forecast(_m)
            _city = _enriched_preview.get("_city") or ""
            _td = _enriched_preview.get("_date")
            if _city and _td:
                _city_dates.add((_city, str(_td)))
        if _city_dates:
            _n_pairs = len(_city_dates)
            print(
                dim(
                    f"  [cron] pre-warming forecasts for {_n_pairs} city/date pair(s)..."
                ),
                flush=True,
            )

            # Step 1: batch Open-Meteo (3 HTTP calls cover all cities)
            from weather_markets import batch_prewarm_forecasts

            _om_models = ["gfs_seamless", "ecmwf_ifs04", "icon_seamless"]
            _n_models = len(_om_models)

            def _om_progress(current: int, total: int, model: str, ok: bool) -> None:
                _tick = "OK" if ok else "FAIL"
                print(
                    dim(f"  [OM batch] [{current}/{total}] {model:<20} {_tick}"),
                    flush=True,
                )

            _batch_written = batch_prewarm_forecasts(
                _city_dates, progress_cb=_om_progress
            )
            print(
                dim(
                    f"  [OM batch] {_batch_written} cache entries written"
                    f" across {_n_models} models"
                ),
                flush=True,
            )

            # Step 2: per-city sources that don't support batching
            # NBM + WeatherAPI only -- no OM rate lock contention.
            def _warm_one(city_date: tuple[str, str]) -> None:
                _c, _d = city_date
                _dt = __import__("datetime").date.fromisoformat(_d)
                try:
                    ctx.fetch_temperature_nbm(_c, _dt)
                except Exception:
                    pass
                try:
                    ctx.fetch_temperature_weatherapi(_c, _dt)
                except Exception:
                    pass

            import threading as _threading

            _warm_done = 0
            _warm_lock = _threading.Lock()

            def _warm_one_tracked(city_date: tuple[str, str]) -> None:
                nonlocal _warm_done
                _warm_one(city_date)
                with _warm_lock:
                    _warm_done += 1
                    _cur = _warm_done
                # \r returns cursor to line start so the counter updates in place
                print(
                    f"  [NBM/WA]  warming city sources... ({_cur}/{_n_pairs})",
                    end="\r",
                    flush=True,
                )

            with ThreadPoolExecutor(max_workers=min(_n_pairs, 4)) as _warm_pool:
                _warm_futures = [
                    _warm_pool.submit(_warm_one_tracked, _cd) for _cd in _city_dates
                ]
                for _wf in _as_completed(_warm_futures):
                    try:
                        _wf.result()
                    except Exception:
                        pass
            print(flush=True)  # newline after in-place counter

        def _enrich_and_analyze(m: dict) -> tuple[dict, dict, dict | None]:
            enriched = ctx.enrich_with_forecast(m)
            return m, enriched, ctx.analyze_trade(enriched)

        _analysis_batch: list[dict] = []  # #perf: collect for single bulk insert
        # Dedup by ticker before analysis — same market can appear twice when the
        # Kalshi API returns it under both the old series format (KXHIGH-NYC-…)
        # and the new format (KXHIGHNY-…) in the same batch.
        _seen_analysis_tickers: set[str] = set()
        _deduped_markets: list[dict] = []
        for _dm in markets:
            _dm_ticker = _dm.get("ticker", "")
            if _dm_ticker not in _seen_analysis_tickers:
                _seen_analysis_tickers.add(_dm_ticker)
                _deduped_markets.append(_dm)
        if len(_deduped_markets) < len(markets):
            _log.debug(
                "cmd_cron: deduped %d duplicate ticker(s) before analysis",
                len(markets) - len(_deduped_markets),
            )

        with ThreadPoolExecutor(max_workers=12) as _pool:
            _futures = {
                _pool.submit(_enrich_and_analyze, m): m for m in _deduped_markets
            }
            for fut in _as_completed(_futures):
                if KILL_SWITCH_PATH.exists():
                    _log.warning(
                        "cmd_cron: kill switch activated mid-scan — stopping analysis"
                    )
                    break
                try:
                    m, enriched, analysis = fut.result()
                except Exception:
                    continue
                if not analysis:
                    continue
                net_edge = analysis.get("net_edge", analysis["edge"])
                adjusted_edge = analysis.get("adjusted_edge", net_edge)
                # Collect analysis attempt for bulk DB insert after loop.
                try:
                    import datetime as _dt

                    _td = analysis.get("target_date") or enriched.get("_target_date")
                    if isinstance(_td, str):
                        try:
                            _td = _dt.date.fromisoformat(_td)
                        except ValueError:
                            _td = None
                    _analysis_batch.append(
                        {
                            "ticker": m.get("ticker", ""),
                            "city": enriched.get("_city"),
                            "condition": str(analysis.get("condition", "")),
                            "target_date": _td,
                            "forecast_prob": analysis.get("forecast_prob", 0.0),
                            "market_prob": analysis.get("market_prob", 0.0),
                            "days_out": int(analysis.get("days_out", 0)),
                            "was_traded": False,
                        }
                    )
                except Exception:
                    pass
                # Skip same-day markets (days_out == 0): by market open the market has
                # real-time weather data our ensemble forecast cannot match.
                if int(analysis.get("days_out", 1)) == 0:
                    continue
                # Market divergence cap: skip when we disagree with the market by
                # more than 2.5× — the market is right nearly every time in that case.
                _side = analysis.get("recommended_side", "yes")
                _our_p = analysis.get("forecast_prob", 0.5)
                _mkt_p = analysis.get("market_prob", 0.5)
                if _side == "yes":
                    _mkt_dir = _mkt_p
                    _our_dir = _our_p
                else:
                    _mkt_dir = 1.0 - _mkt_p
                    _our_dir = 1.0 - _our_p
                if _mkt_dir < MIN_MARKET_PROB_TO_BET_WITH:
                    continue
                if _mkt_dir > 0 and _our_dir / _mkt_dir > MAX_MARKET_DIVERGENCE_RATIO:
                    continue
                # Use PAPER_MIN_EDGE (5%) so more signals are captured for observation.
                if abs(adjusted_edge) < PAPER_MIN_EDGE:
                    continue
                # Probability-edge gate: require ≥8pp conviction even when ROI edge passes.
                # High-variance cities (e.g. Dallas) use a stricter per-city threshold.
                _prob_edge = abs(
                    analysis.get("forecast_prob", 0.5)
                    - analysis.get("market_prob", 0.5)
                )
                _city_key = enriched.get("_city", "")
                _min_edge = CITY_MIN_PROB_EDGE.get(_city_key, MIN_PROB_EDGE)
                if _prob_edge < _min_edge:
                    continue
                signal = analysis.get("net_signal", analysis.get("signal", "")).strip()
                time_risk = analysis.get("time_risk", "\u2014")
                stars = (
                    "\u2605\u2605\u2605"
                    if "STRONG" in signal and time_risk == "LOW"
                    else "\u2605\u2605"
                    if "STRONG" in signal
                    else "\u2605"
                )
                entry = {
                    "ts": datetime.now(UTC).isoformat(),
                    "ticker": m.get("ticker", ""),
                    "signal": signal,
                    "net_edge": round(net_edge, 4),
                    "city": enriched.get("_city", ""),
                }
                with open(log_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(entry) + "\n")
                signals_cache.append(
                    {
                        "ticker": m.get("ticker", ""),
                        "city": enriched.get("_city", "\u2014"),
                        "side": analysis.get("recommended_side", "\u2014").upper(),
                        "signal": signal,
                        "stars": stars,
                        "edge_pct": round(net_edge * 100, 1),
                        "forecast_prob": round(
                            analysis.get("forecast_prob", 0) * 100, 1
                        ),
                        "market_prob": round(analysis.get("market_prob", 0) * 100, 1),
                        "time_risk": time_risk,
                        "kelly_dollars": 0.0,  # balance unknown at cron time; filled by web
                        "already_held": False,
                        "near_threshold": analysis.get("near_threshold", False),
                        "is_hedge": analysis.get("_is_hedge", False),
                    }
                )
                if abs(adjusted_edge) >= _effective_strong_edge:
                    strong_opps.append((enriched, analysis))
                elif abs(adjusted_edge) >= MED_EDGE:
                    med_opps.append((enriched, analysis))
    except Exception as _e:
        import logging as _logging

        _logging.getLogger(__name__).error(
            "cmd_cron: scan loop crashed: %s", _e, exc_info=True
        )

    # #perf: flush analysis attempts in one batch transaction (vs one INSERT per market)
    try:
        from tracker import batch_log_analysis_attempts as _batch_log

        _batch_log(_analysis_batch)
    except Exception:
        pass

    # Write rich signals cache for the web dashboard
    try:
        cache_path = Path(__file__).parent / "data" / "signals_cache.json"
        strong = [s for s in signals_cache if "STRONG" in s["signal"]]
        low_risk = [s for s in strong if s["time_risk"] == "LOW"]
        signals_cache.sort(key=lambda x: abs(x["edge_pct"]), reverse=True)
        cache_payload = {
            "signals": signals_cache[:50],
            "summary": {
                "scanned": scanned,
                "with_edge": len(signals_cache),
                "strong": len(strong),
                "low_risk": len(low_risk),
            },
            "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S"),
        }
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(cache_payload, f)
    except Exception:
        pass

    # Check for market anomalies — price drifted >12pp against our model
    _anomaly_signals = [
        {
            "ticker": s["ticker"],
            "blended_prob": s["forecast_prob"] / 100.0,
            "market_price": s["market_prob"] / 100.0,
        }
        for s in signals_cache
    ]
    _anomalies = check_market_anomalies(_anomaly_signals)
    report_anomalies(_anomalies)

    # Log any active settlement lag signals from the settlement monitor
    try:
        from settlement_monitor import read_settlement_signals

        _settlement_sigs = read_settlement_signals()
        if _settlement_sigs:
            _log.info("Settlement lag signals: %d active", len(_settlement_sigs))
            for sig in _settlement_sigs:
                _log.info(
                    "  \u2192 %s %s (conf=%.0f%%, %.1f\u00b0F vs %.1f\u00b0F threshold)",
                    sig["ticker"],
                    sig["outcome"],
                    sig.get("confidence", 0) * 100,
                    sig.get("current_temp_f", 0),
                    sig.get("threshold_f", 0),
                )
    except Exception as _e:
        _log.debug("cmd_cron: read_settlement_signals failed: %s", _e)

    # \u2500\u2500 Scan summary line \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    _n_with_edge = len(signals_cache)
    _n_strong = len(strong_opps)
    _n_med = len(med_opps)
    if _n_with_edge == 0:
        print(
            dim(
                f"  [cron] Scanned {scanned} market(s) \u2014 no actionable signals found."
            )
        )
    else:
        print(
            dim(
                f"  [cron] Scanned {scanned} market(s) \u2014 "
                f"{_n_with_edge} with edge (strong={_n_strong}, med={_n_med})"
            )
        )

    placed_count = 0
    if _consistency_skip:
        _log.warning(
            "cmd_cron: auto-trading skipped this cycle due to consistency violations"
        )
    else:
        if strong_opps:
            from paper import _dynamic_kelly_cap

            strong_cap = _dynamic_kelly_cap()
            print(
                bold(
                    f"\n  !! {len(strong_opps)} STRONG SIGNAL(S) \u2014 placing paper trades (cap=${strong_cap:.0f}) !!"
                )
            )
            placed_count += (
                ctx.auto_place_trades(strong_opps, client=client, cap=strong_cap) or 0
            )
        if med_opps:
            print(
                bold(
                    f"\n  !! {len(med_opps)} MED SIGNAL(S) \u2014 placing paper trades (cap=$20) !!"
                )
            )
            placed_count += (
                ctx.auto_place_trades(med_opps, client=client, cap=20.0) or 0
            )

    # Auto-settle any pending trades whose markets have resolved
    settled_count = 0
    try:
        settled_count = ctx.sync_outcomes(client)
        if settled_count > 0:
            print(green(f"  [Settle] Recorded {settled_count} new outcome(s)."))
    except Exception:
        pass

    # Settle resolved paper trades (marks paper.json won/lost to match tracker outcomes)
    paper_settled_count = 0
    try:
        from paper import auto_settle_paper_trades

        _settled_trades = auto_settle_paper_trades(client)
        paper_settled_count = len(_settled_trades)
        if paper_settled_count > 0:
            _net_pnl = sum(t.get("pnl") or 0.0 for t in _settled_trades)
            for _st in _settled_trades:
                _ticker = _st.get("ticker", "?")
                _side = (_st.get("side") or "?").upper()
                _pnl = _st.get("pnl") or 0.0
                _result = green("WON ") if _pnl > 0 else red("LOST")
                _pnl_str = f"+${_pnl:.2f}" if _pnl >= 0 else f"-${abs(_pnl):.2f}"
                print(f"  [PaperSettle] {_ticker}  {_side}-side  {_result}  {_pnl_str}")
            _net_str = (
                f"+${_net_pnl:.2f}" if _net_pnl >= 0 else f"-${abs(_net_pnl):.2f}"
            )
            print(
                green(
                    f"  [PaperSettle] {paper_settled_count} trade(s) settled — net P&L: {_net_str}"
                )
            )
    except Exception as _e:
        _log.warning("cmd_cron: auto_settle_paper_trades failed: %s", _e)

    # F3: Auto-trigger calibration every 25 new settled trades
    try:
        import os as _os_cal

        if not _os_cal.environ.get("PYTEST_CURRENT_TEST"):
            _cal_sentinel = Path(__file__).parent / "data" / ".last_calibration_count"
            import tracker as _tracker_cal

            _current_settled = _tracker_cal.count_settled_predictions()
            _last_cal_count = 0
            if _cal_sentinel.exists():
                try:
                    _last_cal_count = int(_cal_sentinel.read_text().strip())
                except Exception:
                    pass
            if _current_settled - _last_cal_count >= 25:
                _log.info(
                    "cmd_cron: F3 auto-calibration triggered "
                    "(%d settled since last run, threshold=25)",
                    _current_settled - _last_cal_count,
                )
                import tracker as _tk
                from calibration import (
                    calibrate_city_weights as _cal_city,
                )
                from calibration import (
                    calibrate_seasonal_weights as _cal_season,
                )

                _db = _tk.DB_PATH
                try:
                    _cal_season(_db)
                    _cal_city(_db)
                    _cal_sentinel.write_text(str(_current_settled))
                    _log.info("cmd_cron: F3 calibration complete — weights updated")
                    print(
                        dim("  [AutoCal] Calibration complete — blend weights updated.")
                    )
                except Exception as _cal_err:
                    _log.warning("cmd_cron: F3 calibration failed: %s", _cal_err)
    except Exception as _e:
        _log.debug("cmd_cron: F3 auto-calibration check failed: %s", _e)

    # Phase 7 — price-based stop-loss check before model-based early exits
    try:
        import paper as _paper_sl

        _open_for_sl = _paper_sl.get_open_trades()
        if _open_for_sl and client is not None:
            _yes_prices: dict[str, float] = {}
            from weather_markets import parse_market_price as _parse_sl_price

            for _t in _open_for_sl:
                try:
                    _mkt = client.get_market(_t["ticker"])
                    # Use parse_market_price so both cents and decimal API formats
                    # are handled correctly.  A raw "/ 100" would mis-price
                    # markets already returned in decimal (0-1) format, making
                    # every position look like a 99% instant loss and firing the
                    # stop on the same cron run the trade was placed.
                    _yes_prices[_t["ticker"]] = _parse_sl_price(_mkt)["yes_ask"]
                except Exception:
                    pass
            _sl_tickers = _paper_sl.check_stop_losses(_open_for_sl, _yes_prices)
            for _sl_ticker in _sl_tickers:
                _sl_trade = next(
                    (t for t in _open_for_sl if t["ticker"] == _sl_ticker), None
                )
                if _sl_trade:
                    _sl_exit_price = _yes_prices.get(
                        _sl_ticker, _sl_trade["entry_price"]
                    )
                    if _sl_trade.get("side") == "no":
                        _sl_exit_price = 1.0 - _sl_exit_price
                    _paper_sl.close_paper_early(_sl_trade["id"], _sl_exit_price)
                    _log.warning(
                        "[StopLoss] Closed %s \u2014 price moved against position",
                        _sl_ticker,
                    )
                    print(
                        red(
                            f"  [StopLoss] Closed {_sl_ticker} \u2014 price breached stop threshold"
                        )
                    )
    except Exception as _e:
        _log.debug("cmd_cron: stop-loss check failed: %s", _e)

    # Weekly Brier alert: notify if score > threshold two weeks running
    try:
        import os as _os_brier

        if not _os_brier.environ.get("PYTEST_CURRENT_TEST"):
            from tracker import get_brier_over_time as _get_brier_weeks
            from utils import BRIER_ALERT_THRESHOLD as _BRIER_THRESH

            _brier_weeks = _get_brier_weeks(weeks=3)
            if len(_brier_weeks) >= 2:
                _recent_two = [w["brier"] for w in _brier_weeks[-2:]]
                if all(b > _BRIER_THRESH for b in _recent_two):
                    from tracker import format_brier_alert as _fmt_brier

                    _brier_msg = (
                        f"Brier score has exceeded {_BRIER_THRESH} for two consecutive weeks "
                        f"({_recent_two[0]:.4f}, {_recent_two[1]:.4f}). "
                        "Review model quality before continuing live trades."
                    )
                    _log.warning("P10.3 Brier alert: %s", _brier_msg)
                    print(red(_fmt_brier(scores=_recent_two)))
                    try:
                        from notify import _send_discord as _brier_discord

                        _brier_discord(
                            "\u26a0\ufe0f Brier Score Alert",
                            _brier_msg,
                            color=0xE3B341,
                        )
                    except Exception:
                        pass
    except Exception as _e:
        _log.debug("cmd_cron: brier alert check failed: %s", _e)

    # Slippage alert: warn if mean fill slippage exceeds threshold
    try:
        import os as _os_slip

        if not _os_slip.environ.get("PYTEST_CURRENT_TEST"):
            from tracker import get_mean_slippage as _get_slip
            from utils import SLIPPAGE_ALERT_CENTS as _SLIP_THRESH

            _mean_slip = _get_slip(days=30)
            if _mean_slip is not None and abs(_mean_slip) > _SLIP_THRESH:
                _slip_msg = (
                    f"Mean live fill slippage over 30 days is {_mean_slip:+.2f}\u00a2 "
                    f"(threshold \u00b1{_SLIP_THRESH}\u00a2). Consider adjusting slippage model."
                )
                _log.warning("P10.4 slippage alert: %s", _slip_msg)
                print(yellow(f"  [SlippageAlert] {_slip_msg}"))
    except Exception as _e:
        _log.debug("cmd_cron: slippage alert check failed: %s", _e)

    # Check open positions for early exit opportunities
    try:
        exits = ctx.check_early_exits(client=client)
        if exits > 0:
            print(green(f"  [EarlyExit] Closed {exits} position(s) on model update."))
    except Exception as _e:
        import logging as _logging

        _logging.getLogger(__name__).warning(
            "cmd_cron: _check_early_exits failed: %s", _e
        )

    # Portfolio VaR summary after placement
    try:
        from monte_carlo import portfolio_var
        from paper import get_open_trades as _get_open

        _open = _get_open()
        if _open:
            _var = portfolio_var(_open, n_simulations=500)
            _exp = None
            try:
                from monte_carlo import simulate_portfolio as _sim

                _exp = _sim(_open, n_simulations=500)["median_pnl"]
            except Exception:
                pass
            _var_s = red(f"-${abs(_var):.2f}") if _var < 0 else green(f"+${_var:.2f}")
            _exp_s = (
                (green(f"+${_exp:.2f}") if _exp >= 0 else red(f"-${abs(_exp):.2f}"))
                if _exp is not None
                else "n/a"
            )
            print(dim(f"  [cron] Portfolio VaR (5%): {_var_s}  |  Expected: {_exp_s}"))
    except Exception:
        pass

    # Phase 9 — alert if any circuit transitioned closed→open during this scan
    try:
        import os as _os_cb

        if (
            not _os_cb.environ.get("PYTEST_CURRENT_TEST")
            and _pre_scan_cb_states
            and _scan_cbs
        ):
            from notify import _send_discord as _discord_cb

            for _cb_name, _cb_obj in _scan_cbs.items():
                if not _pre_scan_cb_states.get(_cb_name, True) and _cb_obj.is_open():
                    _log.warning(
                        "Circuit '%s' OPENED during cron scan \u2014 notifying",
                        _cb_name,
                    )
                    _discord_cb(
                        f"\u26a1 Circuit Opened: {_cb_name}",
                        f"The `{_cb_name}` data source tripped during cron scan.\n"
                        f"Failures: {_cb_obj.failure_count}  |  "
                        f"Retry in: {round(_cb_obj.seconds_until_retry())}s",
                        color=0xF85149,
                    )
    except Exception as _e:
        _log.debug("cmd_cron: circuit-open alert failed: %s", _e)

    # Windows toast notification (suppressed during test runs)
    try:
        import os as _os
        import subprocess as _sp

        if _os.environ.get("PYTEST_CURRENT_TEST"):
            raise StopIteration  # skip toast in tests

        signals = len(strong_opps) + len(med_opps)
        parts = []
        if signals > 0:
            parts.append(
                f"{placed_count} placed"
                if placed_count == signals
                else f"{signals} signal(s), {placed_count} placed"
            )
        if settled_count > 0:
            parts.append(f"{settled_count} settled")
        msg = ", ".join(parts) if parts else "No signals today"

        # Graduation alert — fires once when all criteria are first met
        _grad_flag = Path(__file__).parent / "data" / "graduated.flag"
        try:
            from paper import graduation_check as _grad_check

            if _grad_check() is not None and not _grad_flag.exists():
                _grad_flag.touch()
                msg = "READY TO GO LIVE \u2014 30 trades, +$50 P&L, Brier \u2264 0.20 met!"
        except Exception:
            pass
        _sp.run(
            [
                "powershell",
                "-WindowStyle",
                "Hidden",
                "-Command",
                f"[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType=WindowsRuntime] | Out-Null;"
                f"$template = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02);"
                f"$template.SelectSingleNode('//text[@id=1]').InnerText = 'Kalshi Bot';"
                f"$template.SelectSingleNode('//text[@id=2]').InnerText = '{msg}';"
                f"$notif = [Windows.UI.Notifications.ToastNotification]::new($template);"
                f"[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('Kalshi Bot').Show($notif);",
            ],
            timeout=10,
            capture_output=True,
        )
    except Exception:
        pass

    # D5: Weekly — retrain ML bias model as new settled trades accumulate.
    # Uses a marker file instead of exact-hour matching so scheduled runs never miss.
    _LAST_ML_RETRAIN_PATH = Path(__file__).parent / "data" / ".last_ml_retrain"
    try:
        import os as _os_tb

        if not _os_tb.environ.get("PYTEST_CURRENT_TEST"):
            _should_retrain = True
            if _LAST_ML_RETRAIN_PATH.exists():
                _days_since = (
                    datetime.now(UTC).timestamp()
                    - _LAST_ML_RETRAIN_PATH.stat().st_mtime
                ) / 86400
                _should_retrain = _days_since >= 6
            if _should_retrain:
                _log.info(
                    "cmd_cron: running weekly ML bias model retrain (>=6 days since last)"
                )
                from ml_bias import train_bias_model as _train_bias
                from ml_bias import train_temperature_scaling as _train_temp

                _trained = _train_bias()
                if _trained:
                    _LAST_ML_RETRAIN_PATH.parent.mkdir(exist_ok=True)
                    _LAST_ML_RETRAIN_PATH.touch()
                    print(
                        dim(
                            f"  [MLBias] Retrained {len(_trained)} city model(s): {', '.join(_trained.keys())}"
                        )
                    )
                _T = _train_temp()
                if _T is not None:
                    print(dim(f"  [TempScale] T={_T:.4f} fitted"))
    except Exception as _e:
        _log.debug("cmd_cron: ML bias retrain failed: %s", _e)

    # G5: Weekly — run parameter sweep after bias retrain so sweep sees fresh model.
    # Runs Sunday 03:00 UTC (one hour after train-bias).
    try:
        import os as _os_sweep

        if not _os_sweep.environ.get("PYTEST_CURRENT_TEST"):
            _sweep_dow = datetime.now(UTC).weekday()  # 6 = Sunday
            _sweep_hour = datetime.now(UTC).hour
            if _sweep_dow == 6 and _sweep_hour == 3:
                _log.info("cmd_cron: running weekly parameter sweep (Sunday 03:00 UTC)")
                from param_sweep import run_sweep as _run_sweep

                try:
                    _sweep_result = _run_sweep()
                    if _sweep_result:
                        print(
                            dim(
                                "  [Sweep] Weekly parameter sweep complete — results updated."
                            )
                        )
                except Exception as _sweep_err:
                    _log.warning("cmd_cron: weekly sweep failed: %s", _sweep_err)
    except Exception as _e:
        _log.debug("cmd_cron: weekly sweep check failed: %s", _e)

    # Sync data/ to cloud (OneDrive / Google Drive / custom path) after every cron run
    try:
        from cloud_backup import backup_data as _backup

        _backup()
    except Exception:
        pass  # never crash the scheduler over a backup failure

    print(
        cyan(
            f"  [cron] scan complete \u2014 {datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S')} UTC"
        ),
        flush=True,
    )
    return True  # signals full scan completed (early returns return None)


# ---------------------------------------------------------------------------
# Main cron command
# ---------------------------------------------------------------------------


def cmd_cron(
    ctx: CronContext, client: KalshiClient, min_edge: float = MIN_EDGE
) -> None:
    """Silent background scan — writes to data/cron.log, auto-places strong paper trades."""
    import sys as _sys

    if os.getenv("KALSHI_ENV") == "prod":
        _log.warning("=" * 60)
        _log.warning("CRON RUNNING IN PRODUCTION MODE — REAL MONEY TRADES ENABLED")
        _log.warning(
            "KALSHI_ENV=prod | STARTING_BALANCE=$%.2f",
            float(os.getenv("STARTING_BALANCE", "1000")),
        )
        _log.warning("=" * 60)

    if not ctx.acquire_cron_lock():
        _log.warning("cmd_cron: could not acquire lock — skipping this run")
        if not getattr(cmd_cron, "_called_from_loop", False):
            _sys.exit(1)
        return

    _full_scan = False
    try:
        _full_scan = bool(_cmd_cron_body(ctx, client, min_edge))
    except KeyboardInterrupt:
        print()
        _log.warning("cmd_cron: interrupted by user")
    finally:
        ctx.clear_cron_running_flag()
        try:
            _last_run_path = Path(__file__).parent / "data" / ".cron_last_run"
            _last_run_path.write_text(__import__("datetime").datetime.now().isoformat())
        except Exception:
            pass
        try:
            import sqlite3 as _sqlite3

            from tracker import DB_PATH as _TRACKER_DB

            with _sqlite3.connect(_TRACKER_DB) as _wc:
                _wc.execute("PRAGMA wal_checkpoint(PASSIVE)")
        except Exception:
            pass
        ctx.release_cron_lock()
    if _full_scan and not getattr(cmd_cron, "_called_from_loop", False):
        _sys.exit(0)
