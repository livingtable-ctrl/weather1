"""cron.py — Background cron runner extracted from main.py.

Contains cmd_cron and its private cron-only helpers.
Paths (LOCK_PATH, KILL_SWITCH_PATH, RUNNING_FLAG_PATH) are read from the
``main`` module at call-time so that test monkeypatching via
``monkeypatch.setattr(main, "LOCK_PATH", ...)`` is respected.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

import execution_log
from colors import bold, cyan, dim, green, red, yellow
from kalshi_client import KalshiClient
from utils import DRIFT_TIGHTEN_EDGE, MED_EDGE, MIN_EDGE, PAPER_MIN_EDGE, STRONG_EDGE

# Use the "main" logger name so that existing tests which capture
# logging.getLogger("main") continue to see cron log output.
_log = logging.getLogger("main")


# ---------------------------------------------------------------------------
# Internal helpers — path accessors that respect main-module monkeypatching
# ---------------------------------------------------------------------------


def _main_module():  # type: ignore[return]
    """Return the live ``main`` module object (never cache at import time)."""
    return sys.modules.get("main") or sys.modules["__main__"]


def _lock_path() -> Path:
    return _main_module().LOCK_PATH  # type: ignore[attr-defined]


def _kill_switch_path() -> Path:
    return _main_module().KILL_SWITCH_PATH  # type: ignore[attr-defined]


def _running_flag_path() -> Path:
    return _main_module().RUNNING_FLAG_PATH  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Exported cron helpers
# ---------------------------------------------------------------------------


def _write_cron_running_flag() -> None:
    """Write UTC ISO timestamp to RUNNING_FLAG_PATH; warn if a fresh flag already exists."""
    import time as _time

    rfp = _running_flag_path()
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
        _running_flag_path().unlink(missing_ok=True)
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

                placed_ts = _dt.fromisoformat(placed_at_str).timestamp()
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


def _acquire_cron_lock() -> bool:
    """
    Try to acquire the cron file lock.

    Returns True if the lock was acquired (caller may proceed).
    Returns False if a fresh lock file exists (another instance is running).
    A stale lock (>600 s) is overridden and True is returned.
    """
    import os as _os
    import time as _time

    lp = _lock_path()
    try:
        if lp.exists():
            age = _time.time() - lp.stat().st_mtime
            if age < 600:
                _log.warning(
                    "cmd_cron: lock file exists and is fresh (age=%.0fs) — "
                    "another instance may be running; skipping this run",
                    age,
                )
                return False
            # Stale — fall through to overwrite
            _log.warning("cmd_cron: overriding stale lock file (age=%.0fs)", age)
        lp.parent.mkdir(exist_ok=True)
        lp.write_text(str(_os.getpid()))
        return True
    except Exception as _e:
        _log.warning("cmd_cron: could not acquire lock: %s — proceeding anyway", _e)
        return True  # fail-open: don't block cron on unexpected I/O errors


def _release_cron_lock() -> None:
    """Delete the cron lock file."""
    try:
        _lock_path().unlink(missing_ok=True)
    except Exception as _e:
        _log.warning("cmd_cron: could not release lock: %s", _e)


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


# ---------------------------------------------------------------------------
# Main cron command
# ---------------------------------------------------------------------------


def cmd_cron(client: KalshiClient, min_edge: float = MIN_EDGE) -> None:
    """Silent background scan — writes to data/cron.log, auto-places strong paper trades."""
    import sys as _sys

    # Resolve the live main module so monkeypatched attributes are used
    _main = _main_module()

    # P3.4 — acquire file lock; exit immediately if another instance is running
    # Use _main lookup so monkeypatch.setattr(main, "_acquire_cron_lock", ...) is respected.
    if not _main._acquire_cron_lock():
        _log.warning("cmd_cron: could not acquire lock — skipping this run")
        if not getattr(cmd_cron, "_called_from_loop", False):
            _sys.exit(1)
        return

    # P8.3 — hard kill switch: touch data/.kill_switch to halt immediately
    if _kill_switch_path().exists():
        _log.critical(
            "KILL SWITCH ACTIVATED — halting cron execution immediately. Remove data/.kill_switch to resume."
        )
        print(
            red(
                "\n  \u26a0  KILL SWITCH ACTIVE \u2014 trading halted. Delete data/.kill_switch to resume.\n"
            )
        )
        _main._release_cron_lock()
        return

    # P8.4 — manual override check (time-limited pause)
    # Use main-module lookup so test monkeypatching of main._check_manual_override works.
    if _main._check_manual_override():
        _log.warning("cmd_cron: manual override active — skipping this run")
        _main._release_cron_lock()
        return

    from paper import is_accuracy_halted as _is_accuracy_halted

    if _is_accuracy_halted():
        _log.warning("[cron] accuracy circuit breaker active — skipping market scan")
        _main._release_cron_lock()
        return

    # Graduation gate — prevent accidental live trading before sufficient predictions exist
    try:
        _check_graduation_gate()
    except RuntimeError as _gate_err:
        _log.error("%s", _gate_err)
        _main._release_cron_lock()
        return

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
    from datetime import date as _date

    if _date.today().weekday() == 0:  # Monday
        from tracker import purge_old_predictions as _purge

        _purge(retention_days=730)

    # P3.1 — graceful shutdown flag
    # Use main-module lookup so test monkeypatching works.
    _main._write_cron_running_flag()
    # P3.2 — detect orders placed in the last 5 minutes at startup
    _main._check_startup_orders()

    # Phase 1 — surface prolonged Open-Meteo outages immediately
    try:
        _main.check_ensemble_circuit_health()
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

        _run_anomaly_check(log_results=True)
    except Exception as _e:
        _log.debug("cmd_cron: run_anomaly_check failed: %s", _e)

    # P10.2 — black swan emergency shutdown check
    try:
        from alerts import run_black_swan_check as _run_black_swan_check

        _bs_conditions = _run_black_swan_check()
        if _bs_conditions:
            _log.critical(
                "cmd_cron: BLACK SWAN conditions triggered — halting. Conditions: %s",
                _bs_conditions,
            )
            _main._release_cron_lock()
            _main._clear_cron_running_flag()
            return
    except Exception as _e:
        _log.debug("cmd_cron: run_black_swan_check failed: %s", _e)

    # P10.1 — drift detection; tighten STRONG_EDGE for this run when drifting
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

    # P9.5 — strategy retirement check (log-only, non-blocking)
    try:
        from tracker import auto_retire_strategies as _auto_retire

        _newly_retired = _auto_retire()
        if _newly_retired:
            _log.warning("cmd_cron: auto-retired strategy methods: %s", _newly_retired)
    except Exception as _e:
        _log.debug("cmd_cron: auto_retire_strategies failed: %s", _e)

    # P10.3 — config integrity check (log warning if changed)
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

    # Optional: start WebSocket for real-time price feeds
    _ws = None
    try:
        from kalshi_ws import KalshiWebSocket

        api_key = os.getenv("KALSHI_API_KEY", "")
        key_pem = os.getenv("KALSHI_PRIVATE_KEY_PEM", "")
        if api_key and key_pem:
            _ws = KalshiWebSocket(api_key, key_pem)
            # Subscribe to all active weather market tickers
            # _ws.subscribe(active_tickers)  # add after market scan
            _ws.start()
            _log.info("WebSocket thread started")
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
    try:
        from concurrent.futures import ThreadPoolExecutor
        from concurrent.futures import as_completed as _as_completed

        markets = _main.get_weather_markets(client)
        scanned = len(markets)
        print(dim(f"  [cron] scanning {scanned} market(s)\u2026"), flush=True)

        # Pre-warm forecast/model caches for all unique city/date pairs so the
        # parallel scan hits cache instead of making redundant network requests.
        _city_dates: set[tuple[str, str]] = set()
        for _m in markets:
            _enriched_preview = _main.enrich_with_forecast(_m)
            _city = _enriched_preview.get("_city") or ""
            _td = _enriched_preview.get("_date")
            if _city and _td:
                _city_dates.add((_city, str(_td)))
        if _city_dates:
            print(
                dim(
                    f"  [cron] pre-warming forecasts for {len(_city_dates)} city/date pair(s)\u2026"
                ),
                flush=True,
            )

            def _warm_one(city_date: tuple[str, str]) -> None:
                from weather_markets import _get_consensus_probs, get_ensemble_temps

                _c, _d = city_date
                _dt = __import__("datetime").date.fromisoformat(_d)
                try:
                    _main.get_weather_forecast(_c, _dt)
                except Exception:
                    pass
                try:
                    _main.fetch_temperature_nbm(_c, _dt)
                except Exception:
                    pass
                try:
                    _main.fetch_temperature_ecmwf(_c, _dt)
                except Exception:
                    pass
                try:
                    _main.fetch_temperature_weatherapi(_c, _dt)
                except Exception:
                    pass
                for _v in ("max", "min"):
                    try:
                        get_ensemble_temps(_c, _dt, var=_v)
                    except Exception:
                        pass
                # Warm inner ICON/GFS daily cache used by consensus check
                try:
                    _get_consensus_probs(
                        _c, _dt, {"type": "above", "threshold": 68.0}, var="max"
                    )
                except Exception:
                    pass

            with ThreadPoolExecutor(max_workers=min(len(_city_dates), 8)) as _warm_pool:
                _warm_futures = [
                    _warm_pool.submit(_warm_one, _cd) for _cd in _city_dates
                ]
                for _wf in _as_completed(_warm_futures):
                    try:
                        _wf.result()
                    except Exception:
                        pass

        def _enrich_and_analyze(m: dict) -> tuple[dict, dict, dict | None]:
            enriched = _main.enrich_with_forecast(m)
            return m, enriched, _main.analyze_trade(enriched)

        _analysis_batch: list[dict] = []  # #perf: collect for single bulk insert
        with ThreadPoolExecutor(max_workers=12) as _pool:
            _futures = {_pool.submit(_enrich_and_analyze, m): m for m in markets}
            for fut in _as_completed(_futures):
                try:
                    m, enriched, analysis = fut.result()
                except Exception:
                    continue
                if not analysis:
                    continue
                net_edge = analysis.get("net_edge", analysis["edge"])
                # #55: collect analysis attempt for bulk DB insert after loop
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
                # P1.3: Use PAPER_MIN_EDGE (5%) so more signals are captured for observation.
                if abs(net_edge) < PAPER_MIN_EDGE:
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
                if abs(net_edge) >= _effective_strong_edge:
                    strong_opps.append((enriched, analysis))
                elif abs(net_edge) >= MED_EDGE:
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

    placed_count = 0
    if strong_opps:
        from paper import _dynamic_kelly_cap

        strong_cap = _dynamic_kelly_cap()
        print(
            bold(
                f"\n  !! {len(strong_opps)} STRONG SIGNAL(S) \u2014 placing paper trades (cap=${strong_cap:.0f}) !!"
            )
        )
        placed_count += (
            _main._auto_place_trades(strong_opps, client=client, cap=strong_cap) or 0
        )
    if med_opps:
        print(
            bold(
                f"\n  !! {len(med_opps)} MED SIGNAL(S) \u2014 placing paper trades (cap=$20) !!"
            )
        )
        placed_count += _main._auto_place_trades(med_opps, client=client, cap=20.0) or 0

    # Auto-settle any pending trades whose markets have resolved
    settled_count = 0
    try:
        settled_count = _main.sync_outcomes(client)
        if settled_count > 0:
            print(green(f"  [Settle] Recorded {settled_count} new outcome(s)."))
    except Exception:
        pass

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
            for _t in _open_for_sl:
                try:
                    _mkt = client.get_market(_t["ticker"])
                    _yes_prices[_t["ticker"]] = (_mkt.get("yes_ask", 0) or 0) / 100
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

    # P10.3 — weekly Brier alert: notify if score > threshold two weeks running
    try:
        import os as _os_brier

        if not _os_brier.environ.get("PYTEST_CURRENT_TEST"):
            from tracker import get_brier_over_time as _get_brier_weeks
            from utils import BRIER_ALERT_THRESHOLD as _BRIER_THRESH

            _brier_weeks = _get_brier_weeks(weeks=3)
            if len(_brier_weeks) >= 2:
                _recent_two = [w["brier"] for w in _brier_weeks[-2:]]
                if all(b > _BRIER_THRESH for b in _recent_two):
                    _brier_msg = (
                        f"Brier score has exceeded {_BRIER_THRESH} for two consecutive weeks "
                        f"({_recent_two[0]:.4f}, {_recent_two[1]:.4f}). "
                        "Review model quality before continuing live trades."
                    )
                    _log.warning("P10.3 Brier alert: %s", _brier_msg)
                    print(red(f"  [BrierAlert] {_brier_msg}"))
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

    # P10.4 — slippage alert: warn if mean fill slippage exceeds threshold
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
        exits = _main._check_early_exits(client=client)
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
    # Runs on Sunday early morning. Falls back silently if sklearn isn't installed
    # or fewer than 200 trades exist per city (threshold enforced inside train_bias_model).
    try:
        import os as _os_tb

        if not _os_tb.environ.get("PYTEST_CURRENT_TEST"):
            _now_dow = datetime.now(UTC).weekday()  # 6 = Sunday
            _now_hour = datetime.now(UTC).hour
            if _now_dow == 6 and _now_hour == 2:
                _log.info(
                    "cmd_cron: running weekly ML bias model retrain (Sunday 02:00 UTC)"
                )
                from ml_bias import train_bias_model as _train_bias

                _trained = _train_bias()
                if _trained:
                    print(
                        dim(
                            f"  [MLBias] Retrained {len(_trained)} city model(s): {', '.join(_trained.keys())}"
                        )
                    )
    except Exception as _e:
        _log.debug("cmd_cron: ML bias retrain failed: %s", _e)

    # Sync data/ to cloud (OneDrive / Google Drive / custom path) after every cron run
    try:
        from cloud_backup import backup_data as _backup

        _backup()
    except Exception:
        pass  # never crash the scheduler over a backup failure

    _main._clear_cron_running_flag()
    try:
        _last_run_path = Path(__file__).parent / "data" / ".cron_last_run"
        _last_run_path.write_text(__import__("datetime").datetime.now().isoformat())
    except Exception:
        pass
    _main._release_cron_lock()
    print(
        cyan(
            f"  [cron] scan complete \u2014 {datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S')} UTC"
        ),
        flush=True,
    )
    if not getattr(cmd_cron, "_called_from_loop", False):
        _sys.exit(0)
