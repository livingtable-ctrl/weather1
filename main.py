#!/usr/bin/env python3
"""Kalshi Weather Prediction Markets — run with no arguments for interactive menu."""

import io
import json
import logging
import math
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

import execution_log
from ab_test import ABTest as _ABTest
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
from config import load_and_validate as _load_config
from consistency import find_violations
from kalshi_client import KalshiClient
from notify import alert_strong_signal
from output_formatters import (
    cmd_balance,
    cmd_history,
    cmd_pnl_attribution,
    cmd_positions,
)
from tracker import (
    brier_score,
    export_predictions_csv,
    get_calibration_trend,
    get_source_reliability,
    init_db,
    log_prediction,
    sync_outcomes,
)
from utils import MIN_EDGE, PAPER_MIN_EDGE, STRONG_EDGE
from weather_markets import (
    CITY_COORDS,
    _feels_like,
    analyze_trade,
    check_ensemble_circuit_health,  # noqa: F401 — used via main.* in cron.py
    detect_hedge_opportunity,
    enrich_with_forecast,
    fetch_temperature_ecmwf,  # noqa: F401 — used via main.* in cron.py
    fetch_temperature_nbm,  # noqa: F401 — used via main.* in cron.py
    fetch_temperature_weatherapi,  # noqa: F401 — used via main.* in cron.py
    get_weather_forecast,
    get_weather_markets,
    is_liquid,
    parse_market_price,
    save_learned_weights,
)

load_dotenv()

_bot_config = _load_config()

# C6: A/B test for PAPER_MIN_EDGE — empirically finds the best edge threshold.
# Variants sampled round-robin; loser auto-disabled after 50 trades.
_MIN_EDGE_AB_TEST = _ABTest(
    name="min_edge_variants",
    variants={"low": 0.05, "medium": 0.07, "high": 0.09},
    max_trades_per_variant=50,
)

REFRESH_SECS = 300  # watch mode interval
_WATCH_STATE_PATH = Path(__file__).parent / "data" / ".watch_state.json"

# P3.1 — graceful shutdown flag
RUNNING_FLAG_PATH: Path = Path(__file__).parent / "data" / ".cron_running"

# P3.4 — file-based cron lock (prevents concurrent cron instances)
LOCK_PATH: Path = Path(__file__).parent / "data" / ".cron.lock"

# P8.3 — hard kill switch path (module-level so tests can monkeypatch it)
KILL_SWITCH_PATH: Path = Path(__file__).parent / "data" / ".kill_switch"

from cron import (  # noqa: E402  (after module-level constants)
    _acquire_cron_lock,  # noqa: F401 — re-exported for tests that patch main.*
    _check_graduation_gate,  # noqa: F401
    _check_manual_override,  # noqa: F401
    _check_spend_cap_vs_balance,  # noqa: F401
    _check_startup_orders,  # noqa: F401
    _clear_cron_running_flag,  # noqa: F401
    _release_cron_lock,  # noqa: F401
    _write_cron_running_flag,  # noqa: F401
    cmd_cron,
)


def _brier_sparkline() -> str:
    """
    Return a sparkline string showing weekly Brier trend, e.g. "▅▄▃▂▂▁"
    Uses Unicode block chars ▁▂▃▄▅▆▇█ (lower = better Brier score, i.e. lower bar = better).
    Returns empty string if insufficient data.
    """
    try:
        trend = get_calibration_trend(weeks=8)
        if len(trend) < 2:
            return ""
        blocks = "▁▂▃▄▅▆▇█"
        scores = [t["brier"] for t in trend]
        min_s = 0.0
        max_s = 0.25  # random = 0.25
        span = max_s - min_s
        result = ""
        for s in scores:
            # Map brier 0.0=▁ (good) to 0.25=█ (bad)
            normalized = max(0.0, min(1.0, (s - min_s) / span))
            idx = int(normalized * (len(blocks) - 1))
            result += blocks[idx]
        return result
    except Exception:
        return ""


def _ascii_chart(
    values: list[float], width: int = 50, height: int = 8, label: str = ""
) -> str:
    """
    Render a simple ASCII line chart. Returns a multi-line string.
    Uses block characters █ for filled areas.
    Shows min/max labels on Y axis.
    If all values are the same (flat line), shows a flat line without crashing.
    """
    if not values:
        return ""
    min_v = min(values)
    max_v = max(values)
    span = max_v - min_v
    if span == 0:
        span = 1.0  # avoid division by zero

    # Downsample or upsample to fit width columns
    n = len(values)
    cols: list[float] = []
    for col in range(width):
        idx = int(col / width * n)
        idx = min(idx, n - 1)
        cols.append(values[idx])

    # Build the grid row by row (top = high value)
    lines: list[str] = []
    for row in range(height, 0, -1):
        threshold = min_v + (row / height) * span
        row_str = ""
        for val in cols:
            row_str += "█" if val >= threshold else " "
        # Y axis label on leftmost row and bottom row
        if row == height:
            label_str = f"${max_v:.0f} "
        elif row == 1:
            label_str = f"${min_v:.0f} "
        else:
            label_str = "       " if max_v >= 1000 else "      "
        lines.append(label_str + "│" + row_str)

    bottom = "       └" + "─" * width
    lines.append(bottom)
    if label:
        lines.append(f"  {label}")
    return "\n".join(lines)


def _load_watch_state() -> set:
    """Load the set of previously-seen tickers from disk (survives restarts)."""
    try:
        if _WATCH_STATE_PATH.exists():
            data = json.loads(_WATCH_STATE_PATH.read_text())
            return set(data.get("tickers", []))
    except Exception as exc:
        _log.debug("_load_watch_state: could not read %s: %s", _WATCH_STATE_PATH, exc)
    return set()


def _save_watch_state(tickers: set) -> None:
    """Persist the set of seen tickers so the next run knows what's new."""
    try:
        _WATCH_STATE_PATH.parent.mkdir(exist_ok=True)
        _WATCH_STATE_PATH.write_text(json.dumps({"tickers": list(tickers)}))
    except Exception as exc:
        _log.warning("_save_watch_state: failed to persist watch state: %s", exc)


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
        except Exception as exc:
            _log.warning("auto_settle background thread failed: %s", exc)

    t = threading.Thread(target=_run, daemon=True)
    t.start()


def auto_backtest(client: KalshiClient) -> None:
    """
    Run a quick 7-day backtest silently in a background thread on startup.
    If recent Brier score has degraded by >0.05 vs. all-time Brier, print a warning.
    Stores result in data/.last_backtest.json for the brief/dashboard to read.
    """
    import threading

    def _run():
        try:
            from backtest import run_backtest

            summary = run_backtest(client, days_back=7, verbose=False)
            result_path = Path(__file__).parent / "data" / ".last_backtest.json"
            try:
                result_path.parent.mkdir(exist_ok=True)
                result_path.write_text(json.dumps(summary, default=str))
            except Exception:
                pass

            # Compare recent (7-day) Brier vs all-time
            recent_brier = summary.get("brier")
            all_time_brier = brier_score()
            if (
                recent_brier is not None
                and all_time_brier is not None
                and recent_brier > all_time_brier + 0.05
            ):
                print(
                    yellow(
                        f"\n  [Auto-backtest] WARNING: recent Brier {recent_brier:.4f} "
                        f"vs all-time {all_time_brier:.4f} — model may have degraded.\n"
                    )
                )
            # Overfitting guard: compare in-sample (train) vs out-of-sample (val) Brier
            val_brier = summary.get("val_brier")
            train_brier = summary.get("brier")
            if train_brier is not None and val_brier is not None:
                try:
                    from backtest import check_overfitting

                    ov = check_overfitting(train_brier, val_brier)
                    if ov["status"] in ("overfit", "severe", "warning"):
                        print(
                            yellow(
                                f"\n  [Auto-backtest] Overfitting check: {ov['status'].upper()} "
                                f"(in={train_brier:.4f} out={val_brier:.4f} "
                                f"degradation={ov['degradation']:+.4f})\n"
                                f"  {ov['recommendation']}\n"
                            )
                        )
                except Exception:
                    pass
        except Exception as exc:
            _log.warning("auto_backtest background thread failed: %s", exc)

    t = threading.Thread(target=_run, daemon=True)
    t.start()


def auto_backup() -> None:
    """
    Copy predictions.db and paper_trades.json to data/backups/ on startup.
    #103: Keeps the last 30 daily backups (was 7) for better point-in-time recovery.
    #101: Also cleans up stray temp files left by interrupted atomic writes.
    Runs silently — never blocks startup.
    """
    import shutil

    backup_dir = Path(__file__).parent / "data" / "backups"
    backup_dir.mkdir(exist_ok=True)
    today = date.today().isoformat()
    files = [
        Path(__file__).parent / "data" / "predictions.db",
        Path(__file__).parent / "data" / "paper_trades.json",
    ]
    for src in files:
        if not src.exists():
            continue
        dst = backup_dir / f"{src.stem}_{today}{src.suffix}"
        if not dst.exists():  # only once per day
            try:
                shutil.copy2(src, dst)
                # #104: Verify backup integrity after writing
                if dst.suffix == ".json":
                    try:
                        from paper import cloud_backup, verify_backup

                        verify_backup(dst)
                        cloud_backup(dst)  # #105: optional S3 upload
                    except Exception:
                        pass
            except Exception:
                pass
    # #103: Prune — keep only the 30 most recent backups per file stem
    for stem in ("predictions", "paper_trades"):
        backups = sorted(backup_dir.glob(f"{stem}_*"))
        for old in backups[:-30]:
            try:
                old.unlink()
            except Exception:
                pass

    # #101: Clean up stray atomic-write temp files
    try:
        from paper import cleanup_temp_files

        cleanup_temp_files()
    except Exception:
        pass


_log = logging.getLogger(__name__)


def verify_db_backup(path) -> int:
    """Re-open a backed-up predictions.db, count rows in predictions table. Logs result (#104)."""
    import sqlite3

    path = Path(path)
    try:
        con = sqlite3.connect(str(path))
        row = con.execute("SELECT COUNT(*) FROM predictions").fetchone()
        n = row[0] if row else 0
        con.close()
        _log.info("backup verified: %s, %d rows", path, n)
        return n
    except Exception as exc:
        _log.warning("backup verification failed for %s: %s", path, exc)
        return 0


def cmd_settle(client: KalshiClient) -> None:
    """
    Sync settled market outcomes from Kalshi and record them in the tracker.
    Intended for scheduled nightly execution (via schtasks) as well as manual use.
    """
    from paper import auto_settle_paper_trades

    count = sync_outcomes(client)
    paper = auto_settle_paper_trades(client)
    total = count + paper
    if total > 0:
        parts = []
        if count:
            parts.append(f"{count} outcome(s) recorded")
        if paper:
            parts.append(f"{paper} paper trade(s) settled")
        print(green(f"  [Settle] {', '.join(parts)}."))
    else:
        print(dim("  [Settle] No new outcomes to record."))


def cmd_settlement_monitor(client: KalshiClient, args: list[str] | None = None) -> None:
    """Run METAR settlement lag monitor (polls from 5-7 PM local time)."""
    from settlement_monitor import run_settlement_monitor

    duration = 120
    if args:
        try:
            duration = int(args[0])
        except ValueError:
            pass

    _log.info("Starting settlement monitor for %d minutes...", duration)
    run_settlement_monitor(client, duration_minutes=duration)


def cmd_watch_settle(client: KalshiClient, args: list[str] | None = None) -> None:
    """
    Poll every N minutes until all same-day (and past) open trades are settled.
    Usage: py main.py watch-settle [interval_minutes=5]
    Exits automatically when nothing remains to settle.
    """
    import time as _time
    from datetime import date

    from paper import auto_settle_paper_trades, get_open_trades

    interval = 5
    if args:
        try:
            interval = max(1, int(args[0]))
        except ValueError:
            pass

    today_str = date.today().isoformat()

    def _pending() -> list:
        return [
            t for t in get_open_trades() if (t.get("target_date") or "") <= today_str
        ]

    print(
        green(
            f"[watch-settle] Watching for same-day settlements (every {interval}m). Ctrl-C to stop."
        )
    )

    while True:
        due = _pending()
        if not due:
            print(green("[watch-settle] All due trades settled. Done."))
            break

        tickers = ", ".join(t["ticker"] for t in due)
        print(dim(f"[watch-settle] {len(due)} unsettled: {tickers}"))

        sync_outcomes(client)
        settled = auto_settle_paper_trades(client)
        if settled:
            print(green(f"[watch-settle] Settled {settled} trade(s)."))

        remaining = _pending()
        if not remaining:
            print(green("[watch-settle] All due trades settled. Done."))
            break

        print(
            dim(
                f"[watch-settle] {len(remaining)} still pending — next check in {interval}m…"
            )
        )
        try:
            _time.sleep(interval * 60)
        except KeyboardInterrupt:
            print()
            break


def cmd_loop(client: KalshiClient, args: list[str] | None = None) -> None:
    """
    Self-scheduling run loop — run cron every N hours, auto-settle after 9 PM.
    Usage: py main.py loop [interval_hours=4]
    Leave this running in a terminal. Ctrl-C to stop.
    """
    import time as _time
    from datetime import datetime, timedelta

    from paper import auto_settle_paper_trades

    interval_h = 4
    if args:
        try:
            interval_h = max(1, int(args[0]))
        except ValueError:
            pass
    interval_s = interval_h * 3600

    _KILL_PATH = Path(__file__).parent / "data" / ".kill_switch"

    def _now() -> datetime:
        return datetime.now()

    def _run_cycle(label: str) -> None:
        print(bold(f"\n[loop] ── {label} ── {_now().strftime('%Y-%m-%d %H:%M')} ──"))
        if _KILL_PATH.exists():
            print(
                red(
                    "  Kill switch active — skipping cycle. Delete data/.kill_switch to resume."
                )
            )
            return
        try:
            cmd_cron._called_from_loop = True  # type: ignore[attr-defined]
            cmd_cron(client)
        except Exception as exc:
            print(red(f"  Cron error: {exc}"))
        finally:
            cmd_cron._called_from_loop = False  # type: ignore[attr-defined]

        # Auto-settle if it's 9 PM or later
        if _now().hour >= 21:
            print(dim("  [loop] Post-9PM — running auto-settle…"))
            try:
                sync_outcomes(client)
                n = auto_settle_paper_trades(client)
                if n:
                    print(green(f"  [loop] Settled {n} trade(s)."))
                else:
                    print(dim("  [loop] No new settlements."))
            except Exception as exc:
                print(red(f"  [loop] Settle error: {exc}"))

    print(
        bold(
            f"\n[loop] Starting — cron every {interval_h}h, auto-settle after 9 PM. Ctrl-C to stop."
        )
    )

    # Run immediately on startup
    _run_cycle("startup run")
    next_run = _now() + timedelta(seconds=interval_s)

    try:
        while True:
            remaining = (next_run - _now()).total_seconds()
            if remaining <= 0:
                _run_cycle("scheduled run")
                next_run = _now() + timedelta(seconds=interval_s)
                remaining = interval_s

            # Show countdown, update every 60s
            h, m = divmod(int(remaining), 3600)
            m //= 60
            print(
                dim(
                    f"  [loop] Next run in {h}h {m}m  ({next_run.strftime('%H:%M')})  — Ctrl-C to stop"
                ),
                end="\r",
                flush=True,
            )
            _time.sleep(min(60, remaining))

    except KeyboardInterrupt:
        print(f"\n{dim('[loop] Stopped.')}")


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
    try:
        market = client.get_market(ticker)
    except Exception as _e:
        short_msg = str(_e)[:120]
        print(
            red(
                "  Could not reach Kalshi API. Check your internet connection and try again."
            )
        )
        print(dim(f"  (Error: {short_msg})"))
        return
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
        # Feels-like temperature (wind chill / heat index)
        try:
            fl = _feels_like(forecast["high_f"])
            if abs(fl - forecast["high_f"]) >= 3.0:
                _kv("Feels like:", f"{fl:.1f}°F")
        except Exception:
            pass

    # Whale detection
    volume = market.get("volume", 0) or 0
    open_interest = market.get("open_interest", 0) or 0
    if volume > 5000 or open_interest > 2000:
        print(
            yellow(
                f"  ⚠  WHALE ALERT — volume: {volume:,}  open interest: {open_interest:,}"
            )
        )

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
            from weather_markets import EDGE_CALC_VERSION as _ECV

            log_prediction(
                ticker,
                enriched.get("_city"),
                enriched.get("_date"),
                analysis,
                ensemble_prob=analysis.get("ensemble_prob"),
                nws_prob=analysis.get("nws_prob"),
                clim_prob=analysis.get("clim_prob"),
                forecast_cycle=_current_forecast_cycle(),
                edge_calc_version=_ECV,
                signal_source=analysis.get("method"),
            )
        except Exception as _exc:
            logging.getLogger(__name__).warning(
                "cmd_analyze: log_prediction failed for %s: %s", ticker, _exc
            )
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
    min_edge: float | None = None,
    show_summary: bool = False,
):
    if min_edge is None:
        min_edge = MIN_EDGE
    """Run one analysis pass. Returns set of opportunity tickers found."""
    markets = get_weather_markets(client)
    liquid_opps: list = []
    no_quote_opps: list = []
    total = len(markets)

    # #64: load open trades once so we can flag hedge opportunities below
    try:
        from paper import get_open_trades as _got

        _open_trades = _got()
    except Exception:
        _open_trades = []

    # A4: ticker→city map built during enrichment for arb exposure checks
    _arb_ticker_city: dict[str, str] = {}

    for i, m in enumerate(markets, 1):
        if total > 5:
            print(f"\r  Scanning [{i}/{total}]...", end="", flush=True)
        try:
            enriched = enrich_with_forecast(m)
            analysis = analyze_trade(enriched)
        except Exception as exc:
            # #109: include ticker in error so failures are debuggable
            import logging as _logging

            _logging.getLogger(__name__).warning(
                "Market analysis failed for %s: %s", m.get("ticker", "?"), exc
            )
            continue
        _arb_ticker_city[m.get("ticker", "")] = enriched.get("_city", "")
        # L7-C: gate on entry_side_edge (vs actual ask price) not mid-price edge.
        # entry_side_edge = blended_prob - yes_ask (YES) or blended_prob - no_ask (NO).
        # A 7% mid-edge may shrink to 4% at ask; gating on mid lets those trades through.
        if not analysis:
            continue
        _gate_edge = analysis.get("entry_side_edge", analysis["edge"])
        if abs(_gate_edge) < min_edge:
            continue
        # #64: tag analysis as a hedge if it reduces existing open exposure
        analysis["_is_hedge"] = detect_hedge_opportunity(analysis, _open_trades)
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
        if ae >= STRONG_EDGE and risk != "HIGH":
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
            # #64: show hedge tag when this trade reduces open directional exposure
            buy_side = bold(a["recommended_side"].upper())
            if a.get("_is_hedge"):
                buy_side = buy_side + cyan(" [HEDGE]")
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

    def _plain_english(analysis: dict, market: dict) -> str:
        """
        Generate a one-sentence plain-English explanation of the trade opportunity.
        Example: "Model thinks 68% chance NYC hits 72°F. Market only prices it at 52%.
        A $10 bet would win $8.40 after fees if correct."
        """
        city = market.get("_city") or market.get("city", "")
        tdate = market.get("_date")
        date_str = tdate.isoformat() if tdate else "target date"
        forecast_prob = analysis.get("forecast_prob", 0.5)
        market_prob = analysis.get("market_prob", 0.5)
        gap = abs(forecast_prob - market_prob)
        side = analysis.get("recommended_side", "yes")
        entry_price = (
            analysis.get("market_prob", 0.5)
            if side == "yes"
            else 1 - analysis.get("market_prob", 0.5)
        )
        # Compute what a $10 bet returns
        stake = 10.0
        from utils import KALSHI_FEE_RATE as _fee

        winnings = (1 - entry_price) * (1 - _fee)
        win_amount = round(stake / entry_price * winnings, 2)

        cond = analysis.get("condition", {})
        cond_type = cond.get("type", "")
        if cond_type == "above":
            cond_desc = f"above {cond['threshold']:.0f}°F"
        elif cond_type == "below":
            cond_desc = f"below {cond['threshold']:.0f}°F"
        elif cond_type == "between":
            cond_desc = f"between {cond['lower']:.0f}–{cond['upper']:.0f}°F"
        elif cond_type == "precip_any":
            cond_desc = "any precipitation"
        elif cond_type == "precip_above":
            cond_desc = f"over {cond.get('threshold', 0):.2f} inches of rain"
        else:
            cond_desc = "the condition"

        return (
            f"Model thinks there's a {forecast_prob:.0%} chance {city} hits {cond_desc} "
            f"on {date_str}.\n"
            f"  The market only prices it at {market_prob:.0%} — a {gap:.0%} gap. "
            f"A $10 bet wins ${win_amount:.2f}\n"
            f"  after fees if you're right (and loses $10 if wrong)."
        )

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
        # Top pick plain-English explanation
        best_m, best_a = max(
            liquid_opps, key=lambda x: abs(x[1].get("net_edge", x[1]["edge"]))
        )
        explanation = _plain_english(best_a, best_m)
        print(f"\n  {bold('Top pick:')} {explanation}")
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

    # ── Arbitrage surface ────────────────────────────────────────────────────
    try:
        violations = find_violations(markets)
        if violations:
            print(bold("\n── Arbitrage Opportunities ──\n"))
            from weather_markets import MIN_SIGNAL_VOLUME as _ARB_MIN_VOL

            _arb_vol: dict[str, float] = {
                m.get("ticker", ""): float(m.get("volume_fp") or m.get("volume") or 0)
                for m in markets
            }
            # Build city→open-cost map from already-loaded open trades
            _arb_city_cost: dict[str, float] = {}
            for _ot in _open_trades:
                _oc = _ot.get("city") or ""
                _arb_city_cost[_oc] = _arb_city_cost.get(_oc, 0.0) + float(
                    _ot.get("cost", 0.0)
                )

            from paper import place_paper_order as _arb_ppo

            for v in violations:
                print(
                    green(
                        f"  Buy {v.buy_ticker} ({v.buy_prob * 100:.0f}¢)"
                        f" + Sell {v.sell_ticker} ({v.sell_prob * 100:.0f}¢)"
                        f"  → guaranteed +{v.guaranteed_edge * 100:.0f}¢ edge"
                    )
                )
                if hasattr(v, "description") and v.description:
                    print(dim(f"  {v.description}"))

                # A4: auto-place when edge, volume, and city-exposure all pass
                if v.guaranteed_edge < 0.05:
                    continue
                buy_vol = _arb_vol.get(v.buy_ticker, 0.0)
                sell_vol = _arb_vol.get(v.sell_ticker, 0.0)
                if buy_vol < _ARB_MIN_VOL or sell_vol < _ARB_MIN_VOL:
                    print(
                        dim(
                            f"  [Arb] Skipped — volume {buy_vol:.0f}/{sell_vol:.0f}"
                            f" < {_ARB_MIN_VOL}"
                        )
                    )
                    continue
                _arb_city = (
                    _arb_ticker_city.get(v.buy_ticker)
                    or _arb_ticker_city.get(v.sell_ticker)
                    or ""
                )
                _ARB_CITY_LIMIT = 25.0  # max $25 open arb exposure per city-group
                if _arb_city_cost.get(_arb_city, 0.0) >= _ARB_CITY_LIMIT:
                    print(
                        dim(
                            f"  [Arb] Skipped — {_arb_city or 'unknown'} exposure"
                            f" ${_arb_city_cost.get(_arb_city, 0):.2f}"
                            f" >= ${_ARB_CITY_LIMIT:.0f}"
                        )
                    )
                    continue
                try:
                    yes_price = max(0.01, min(0.99, v.buy_prob))
                    no_price = max(0.01, min(0.99, 1.0 - v.sell_prob))
                    _arb_ppo(
                        v.buy_ticker,
                        "yes",
                        1,
                        yes_price,
                        thesis="consistency-arb",
                        city=_arb_city or None,
                    )
                    _arb_ppo(
                        v.sell_ticker,
                        "no",
                        1,
                        no_price,
                        thesis="consistency-arb",
                        city=_arb_city or None,
                    )
                    _arb_city_cost[_arb_city] = (
                        _arb_city_cost.get(_arb_city, 0.0) + yes_price + no_price
                    )
                    print(
                        green(
                            f"  [Arb] Placed: BUY YES {v.buy_ticker} @ {yes_price:.0%}"
                            f" + BUY NO {v.sell_ticker} @ {no_price:.0%}"
                        )
                    )
                except Exception as _arb_exc:
                    print(dim(f"  [Arb] Could not place: {_arb_exc}"))
    except Exception:
        pass

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


_LIVE_CONFIG_PATH = Path(__file__).parent / "data" / "live_config.json"
_LIVE_CONFIG_DEFAULT: dict = {
    "max_trade_dollars": 50,
    "daily_loss_limit": 200,
    "max_open_positions": 10,
    "gtc_cancel_hours": 24,
}


def _current_forecast_cycle() -> str:
    """Return a string identifier for the current NWS forecast cycle.

    NWS model runs are at 00z and 12z (midnight and noon UTC).
    Returns a string like '2025-05-15_12z' so orders within the same
    forecast cycle are deduplicated.
    """
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    hour = now.hour
    cycle_hour = 12 if hour >= 12 else 0
    return f"{now.strftime('%Y-%m-%d')}_{cycle_hour:02d}z"


def place_paper_order(ticker, side, qty, entry_price, **kwargs):
    """Module-level shim so tests can patch main.place_paper_order."""
    from paper import place_paper_order as _ppo

    return _ppo(ticker, side, qty, entry_price, **kwargs)


def _load_live_config() -> dict:
    """Load live trading hard stops from data/live_config.json.

    Creates the file with safe defaults if it does not exist.
    Returns the config dict.
    """
    try:
        with open(_LIVE_CONFIG_PATH, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        _LIVE_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        _LIVE_CONFIG_PATH.write_text(
            json.dumps(_LIVE_CONFIG_DEFAULT, indent=2), encoding="utf-8"
        )
        return dict(_LIVE_CONFIG_DEFAULT)


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
            price = order["price"]  # always YES-side decimal (0.0–1.0)
            qty = order.get("fill_quantity") or order["quantity"]
            if outcome_yes and side == "yes":
                pnl = qty * (1 - price) * (1 - _fee)
            elif not outcome_yes and side == "yes":
                pnl = -qty * price
            elif outcome_yes and side == "no":
                pnl = -qty * (
                    1 - price
                )  # YES wins, NO loses: lost (1-price) per contract
            else:  # not outcome_yes, side == "no" — NO wins
                pnl = qty * price * (1 - _fee)  # won price per contract minus fee
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

    # 5. Place order
    try:
        response = client.place_order(
            ticker=ticker,
            side=side,
            action="buy",
            count=quantity,
            price=price,
            time_in_force="good_till_canceled",
        )
        execution_log.log_order(
            ticker=ticker,
            side=side,
            quantity=quantity,
            price=price,
            order_type="limit",
            status="pending",
            response=response,
            forecast_cycle=cycle,
            live=True,
        )
        return True, dollar_cost
    except Exception as exc:
        execution_log.log_order(
            ticker=ticker,
            side=side,
            quantity=quantity,
            price=price,
            order_type="limit",
            status="failed",
            error=str(exc),
            forecast_cycle=cycle,
            live=True,
        )
        print(f"[LIVE] Order failed for {ticker}: {exc}")
        return False, 0.0


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
    except Exception as _e:
        logging.getLogger(__name__).debug(
            "_resolve_price: failed for %s/%s: %s", ticker, side, _e
        )
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
        # Order type prompt: market taker vs limit maker
        print(
            dim(
                "  Order type: (1) Market taker [7% fee]  "
                "(2) Limit maker [0% fee, may not fill]"
            )
        )
        order_type_raw = input(dim("  Choose (1/2, default 1): ")).strip()
        use_maker = order_type_raw == "2"
        maker_price: float | None = None
        if use_maker:
            # Suggest mid as limit price
            try:
                mkt = client.get_market(ticker)
                prices_mk = parse_market_price(mkt)
                suggested = prices_mk["mid"]
                if suggested <= 0:
                    suggested = price
            except Exception:
                suggested = price
            maker_raw = input(
                dim(f"  Limit price (Enter for mid {suggested:.3f}): ")
            ).strip()
            if maker_raw:
                try:
                    maker_price = float(maker_raw)
                    if not 0 < maker_price < 1:
                        print(red("  Invalid price — using market order."))
                        use_maker = False
                except ValueError:
                    print(red("  Invalid price — using market order."))
                    use_maker = False
            else:
                maker_price = suggested

        raw_qty = input(dim("  Qty (Enter for Kelly auto-size): ")).strip()
        qty_arg = [raw_qty] if raw_qty.isdigit() and int(raw_qty) > 0 else []
        thesis_raw = input(dim("  Why? (optional thesis, Enter to skip): ")).strip()
        thesis = thesis_raw if thesis_raw else None
        # Check streak/daily loss halt before proceeding
        try:
            from paper import is_daily_loss_halted, is_streak_paused

            if is_daily_loss_halted():
                from paper import get_daily_pnl

                daily_pnl = get_daily_pnl()
                print(
                    red(
                        f"  Daily loss limit reached (${daily_pnl:.2f} today). Trading halted."
                    )
                )
                return
            if is_streak_paused():
                print(yellow("  Warning: on a 3+ loss streak — Kelly is halved."))
        except Exception:
            pass
        # Place order directly with thesis
        try:
            qty = int(qty_arg[0]) if qty_arg else None
            if qty is None:
                from paper import (
                    kelly_quantity,
                    portfolio_kelly_fraction,
                )
                from weather_markets import analyze_trade, enrich_with_forecast

                try:
                    market = client.get_market(ticker)
                    enriched = enrich_with_forecast(market)
                    analysis = analyze_trade(enriched)
                    fee_kelly = (
                        analysis.get("ci_adjusted_kelly", 0.0) if analysis else 0.0
                    )
                    city = enriched.get("_city")
                    tdate = enriched.get("_date")
                    tdate_str = tdate.isoformat() if tdate else None
                    adj_kelly = portfolio_kelly_fraction(
                        fee_kelly, city, tdate_str, side=side
                    )
                    qty = kelly_quantity(adj_kelly, price)
                except Exception:
                    qty = 0

            # Maker order (real order, not paper) — only if qty is specified
            if use_maker and maker_price is not None and qty and qty > 0:
                try:
                    result = client.place_maker_order(ticker, side, maker_price, qty)
                    order = result.get("order", result)
                    print(
                        green(
                            f"  Maker limit order placed: {order.get('order_id', '')}  "
                            f"@ ${maker_price:.3f}  ({qty} contracts)"
                        )
                    )
                    print(
                        dim(
                            "  Order rests in book — will fill only if market moves to your price."
                        )
                    )
                except Exception as e:
                    print(red(f"  Maker order failed: {e}"))
                return

            if qty and qty > 0:
                # Check position limits before placing
                try:
                    from paper import check_position_limits as _cpl

                    _limit_check = _cpl(ticker, qty, price)
                    if not _limit_check.get("allowed", True):
                        print(
                            red(
                                f"  Position limit check failed: {_limit_check.get('reason', 'limit exceeded')}"
                            )
                        )
                        return
                except Exception:
                    pass

                from paper import get_balance as _gb_qpb
                from paper import place_paper_order

                _cost_qpb = qty * price
                _balance_qpb = _gb_qpb()
                if _cost_qpb > _balance_qpb * 0.03:
                    _pct_qpb = _cost_qpb / _balance_qpb * 100
                    _confirm_large = (
                        input(
                            yellow(
                                f"  Heads up: this bet is ${_cost_qpb:.2f} ({_pct_qpb:.1f}% of your ${_balance_qpb:.2f} balance). "
                                f"Continue? (y/N): "
                            )
                        )
                        .strip()
                        .lower()
                    )
                    if _confirm_large != "y":
                        print(dim("  Cancelled."))
                        return
                trade = place_paper_order(ticker, side, qty, price, thesis=thesis)
                print(green(f"  Paper trade #{trade['id']} placed."))
                # #110: audit trail — record every manual paper buy
                try:
                    from tracker import log_audit

                    log_audit(
                        "manual_buy",
                        ticker=ticker,
                        side=side,
                        price=price,
                        qty=qty,
                        thesis=thesis,
                    )
                except Exception:
                    pass
            else:
                cmd_paper(["buy", ticker, side, f"{price:.3f}"] + qty_arg, client)
        except ValueError as e:
            print(red(f"  Error: {e}"))
    except (KeyboardInterrupt, EOFError):
        print()


def cmd_today(client: KalshiClient) -> None:
    """Show a plain-English 'what should I do today?' recommendation."""
    from paper import get_balance, kelly_bet_dollars
    from utils import KALSHI_FEE_RATE as _fee

    print(bold("\n  ── Today's Recommendation ──\n"))
    print(dim("  Scanning markets for the best opportunity...\n"))

    try:
        markets = get_weather_markets(client)
    except Exception as e:
        print(red(f"  Could not load markets: {e}"))
        return

    best_m = None
    best_a = None
    best_abs_edge = 0.0

    for m in markets:
        enriched = enrich_with_forecast(m)
        analysis = analyze_trade(enriched)
        if not analysis:
            continue
        net_edge = analysis.get("net_edge", analysis["edge"])
        if abs(net_edge) < MIN_EDGE:
            continue
        if not is_liquid(m):
            continue
        if analysis.get("time_risk") == "HIGH":
            continue
        if abs(net_edge) > best_abs_edge:
            best_abs_edge = abs(net_edge)
            best_m = enriched
            best_a = analysis

    if best_m is None or best_a is None:
        print(yellow("  No strong opportunities today. Consider waiting."))
        return

    ticker = best_m.get("ticker", "")
    title = best_m.get("title") or ticker
    net_edge = best_a.get("net_edge", best_a["edge"])
    forecast_prob = best_a["forecast_prob"]
    market_prob = best_a["market_prob"]
    side = best_a["recommended_side"]
    time_risk = best_a.get("time_risk", "—")
    consensus = best_a.get("consensus", "")
    regime_desc = best_a.get("regime_description", "")
    n_members = best_a.get("n_members", 0)
    ci_kelly = best_a.get("ci_adjusted_kelly", best_a.get("fee_adjusted_kelly", 0.0))
    entry_price = market_prob if side == "yes" else 1 - market_prob

    balance = get_balance()
    bet_dollars = kelly_bet_dollars(ci_kelly)
    win_per_dollar = (1 - entry_price) * (1 - _fee)
    if entry_price > 0 and bet_dollars > 0:
        if_correct = round(bet_dollars / entry_price * win_per_dollar, 2)
    else:
        if_correct = 0.0

    # Build "Why" explanation
    why_parts = []
    if n_members > 0:
        why_parts.append(f"Our ensemble of {n_members} weather models")
    if regime_desc:
        why_parts.append(regime_desc)
    if consensus:
        why_parts.append(consensus)
    if not why_parts:
        why_parts.append("Our weather forecast models")
    why = ". ".join(why_parts)

    # Confidence label
    if abs(net_edge) >= 0.25 and time_risk == "LOW":
        confidence = green("HIGH (all sources agree — consensus signal)")
    elif abs(net_edge) >= 0.15:
        confidence = yellow("MEDIUM")
    else:
        confidence = dim("MODERATE")

    risk_label = (
        green("LOW")
        if time_risk == "LOW"
        else (yellow("MEDIUM") if time_risk != "HIGH" else red("HIGH"))
    )

    print(f"  Market:  {bold(ticker)}")
    print(f"  Question: {title}")
    print()
    print(f"  Our model:   {bold(f'{forecast_prob:.0%}')} chance of YES")
    print(f"  Market says: {bold(f'{market_prob:.0%}')} chance of YES")
    edge_str = green(f"+{net_edge:.0%}") if net_edge > 0 else red(f"{net_edge:.0%}")
    print(f"  Your edge:   {edge_str} (after fees)")
    print()
    print(
        f"  Recommendation: BUY {bold(side.upper())} at {bold(f'{entry_price:.0%}')} per contract"
    )
    print()
    print(f"  Why: {why}")
    print()
    if bet_dollars > 0:
        pct_bal = bet_dollars / balance * 100 if balance > 0 else 0
        print(
            f"  Suggested bet: {green(f'${bet_dollars:.2f}')} (Kelly sizing, {pct_bal:.1f}% of your ${balance:.0f} balance)"
        )
        print(f"  If correct: win {green(f'${if_correct:.2f}')} after fees")
        print(f"  If wrong:   lose {red(f'${bet_dollars:.2f}')}")
    else:
        print(
            dim(
                "  Suggested bet: Kelly sizing unavailable — drawdown guard may be active"
            )
        )
    print()
    print(f"  Risk level:  {risk_label}")
    print(f"  Confidence:  {confidence}")
    print()

    # ── Inline placement ─────────────────────────────────────────────────────
    from paper import kelly_quantity, place_paper_order
    from utils import MAX_DAILY_SPEND

    qty = kelly_quantity(ci_kelly, entry_price) if entry_price > 0 else 0

    try:
        raw = (
            input(
                dim(
                    f"  [P] Place {side.upper()} x{qty} ${bet_dollars:.2f}  [Enter] Back: "
                )
            )
            .strip()
            .upper()
        )
    except (KeyboardInterrupt, EOFError):
        print()
        return

    if raw != "P":
        return

    if qty < 1 or bet_dollars <= 0:
        print(yellow("  Kelly sizing produced 0 contracts — trade not placed."))
        return

    if _daily_paper_spend() + bet_dollars > MAX_DAILY_SPEND:
        print(
            yellow(
                f"  Daily spend cap would be exceeded (${_daily_paper_spend():.2f}/${MAX_DAILY_SPEND:.0f}). Trade not placed."
            )
        )
        return

    try:
        trade = place_paper_order(
            ticker,
            side,
            qty,
            entry_price,
            entry_prob=forecast_prob,
            net_edge=best_a.get("net_edge"),
            city=best_m.get("_city"),
            target_date=best_a.get("target_date"),
            method=best_a.get("method"),
        )
        cost = round(entry_price * qty, 2)
        print(
            green(
                f"\n  ✓ Placed: BUY {side.upper()} x{qty} @ {entry_price:.0%} — cost ${cost:.2f}"
            )
        )
        print(
            dim(f"  Trade ID: {trade.get('id', '?')}  |  Balance: ${get_balance():.2f}")
        )
        # A2: Record feature contributions so feature_importance analytics can learn
        # which signals (ensemble spread, model agreement, etc.) predict wins.
        try:
            from feature_importance import record_feature_contribution

            _days_out_fi = (
                (best_a.get("target_date") - __import__("datetime").date.today()).days
                if best_a.get("target_date")
                else 0
            )
            record_feature_contribution(
                ticker,
                {
                    "ensemble_spread": best_a.get("ensemble_spread", 0) or 0,
                    "model_agreement": 1.0 if best_a.get("model_consensus") else 0.0,
                    "days_out": _days_out_fi,
                    "edge": best_a.get("edge", 0) or 0,
                    "kelly_fraction": best_a.get("ci_adjusted_kelly", 0) or 0,
                    "data_quality": best_a.get("data_quality", 0) or 0,
                    "near_threshold": 1.0 if best_a.get("near_threshold") else 0.0,
                    "regime": 1.0
                    if best_a.get("regime")
                    in ("heat_dome", "cold_snap", "blocking_high")
                    else 0.0,
                },
            )
        except Exception:
            pass
    except Exception as e:
        print(red(f"  Failed to place trade: {e}"))


def cmd_brief(client: KalshiClient, send_email: bool = False) -> None:
    """Daily briefing — fast single-screen summary."""
    from paper import (
        check_aged_positions,
        check_expiring_trades,
        check_model_exits,
        get_balance,
        get_current_streak,
        get_daily_pnl,
        get_open_trades,
        graduation_check,
    )

    now = datetime.now(UTC)
    _header(f"Daily Briefing — {now.strftime('%Y-%m-%d %H:%M')} UTC")

    # Balance + daily P&L + streak
    bal = get_balance()
    daily_pnl = get_daily_pnl()
    pnl_s = (
        green(f"+${daily_pnl:.2f}")
        if daily_pnl >= 0
        else red(f"-${abs(daily_pnl):.2f}")
    )
    streak_kind, streak_n = get_current_streak()
    streak_s = (
        green(f"{streak_n} win streak")
        if streak_kind == "win"
        else red(f"{streak_n} loss streak")
        if streak_kind == "loss"
        else dim("no streak")
    )
    print(
        f"  Balance: {bold(f'${bal:.2f}')}  |  Today P&L: {pnl_s}  |  Streak: {streak_s}"
    )

    # ASCII balance history chart
    try:
        from paper import get_balance_history as _gbh_brief

        history = _gbh_brief()
        if len(history) >= 3:
            balances = [h["balance"] for h in history]
            print(_ascii_chart(balances, width=52, height=6, label="Balance"))
    except Exception:
        pass

    # Open positions + expiring
    open_trades = get_open_trades()
    expiring = check_expiring_trades()
    expiring_soon = [e for e in expiring if e["hours_left"] <= 24]
    print(f"\n  Open positions: {cyan(str(len(open_trades)))}", end="")
    if expiring_soon:
        print(f"  |  {yellow(f'{len(expiring_soon)} expiring within 24h')}", end="")
    print()

    # Top 3 opportunities
    print(bold("\n  ── Top Opportunities ──"))
    try:
        markets = get_weather_markets(client)
        analyzed = []
        for m in markets:
            enriched = enrich_with_forecast(m)
            analysis = analyze_trade(enriched)
            if analysis and abs(analysis.get("net_edge", analysis["edge"])) >= MIN_EDGE:
                analyzed.append((enriched, analysis))
        top3 = sorted(
            analyzed,
            key=lambda x: abs(x[1].get("net_edge", x[1]["edge"])),
            reverse=True,
        )[:3]
        if top3:
            for m, a in top3:
                net_edge = a.get("net_edge", a["edge"])
                edge_s = (
                    green(f"+{net_edge:.0%}")
                    if net_edge > 0
                    else red(f"{net_edge:.0%}")
                )
                ticker = m.get("ticker", "")
                side = a["recommended_side"].upper()
                print(
                    f"  {ticker:<32} {side:<4} {edge_s}  {dim(a.get('signal', '').strip())}"
                )
        else:
            print(dim("  No opportunities above threshold."))
    except Exception as e:
        print(dim(f"  (Could not scan markets: {e})"))

    # Exit signals
    try:
        exits = check_model_exits(client)
        if exits:
            print(bold(f"\n  ── Exit Signals ({len(exits)}) ──"))
            for rec in exits:
                t = rec["trade"]
                reason = (
                    "MODEL FLIPPED" if rec["reason"] == "model_flipped" else "EDGE GONE"
                )
                print(yellow(f"  #{t['id']} {t['ticker']} — {reason}"))
    except Exception:
        pass

    # Graduation check
    grad = graduation_check()
    if grad:
        print(bold(f"\n  {green('GRADUATION CHECK PASSED')} — Ready for live trading!"))
        print(
            f"  {grad['settled']} trades  |  Win rate: {grad['win_rate']:.0%}  |  P&L: +${grad['total_pnl']:.2f}"
        )

    # Aged positions
    aged = check_aged_positions()
    if aged:
        print(bold(f"\n  ── Aged Positions ({len(aged)}) ──"))
        for entry in aged:
            t = entry["trade"]
            print(yellow(f"  #{t['id']} {t['ticker']} — {entry['age_days']} days old"))

    # Correlated event exposure warning
    try:
        from paper import check_correlated_event_exposure

        corr_warnings = check_correlated_event_exposure()
        if corr_warnings:
            print(bold(f"\n  ── Correlation Warnings ({len(corr_warnings)}) ──"))
            for w in corr_warnings:
                n = len(w["trades"])
                print(
                    yellow(
                        f"  [Warning] {n} {w['city']} positions within 3 days "
                        f"(${w['total_cost']:.2f} at risk) — these are correlated bets"
                    )
                )
    except Exception:
        pass

    # Brier sparkline
    try:
        sparkline = _brier_sparkline()
        if sparkline:
            print(f"\n  Brier trend (recent weeks): {dim(sparkline)}")
    except Exception:
        pass

    print(
        dim(
            "\n  Run 'A' to analyze, 'P' for paper trades, 'T' for today's recommendation"
        )
    )

    # Email briefing if requested
    if send_email:
        try:
            from notify import _send_email
            from paper import get_balance, get_performance

            bal = get_balance()
            perf = get_performance()
            pnl = perf.get("total_pnl", 0.0)
            wr = perf.get("win_rate")
            bs = brier_score()
            lines = [
                f"Balance: ${bal:.2f}",
                f"P&L: {'+' if pnl >= 0 else ''}${pnl:.2f}",
                f"Win rate: {wr:.0%}" if wr else "Win rate: —",
                f"Brier: {bs:.4f}" if bs else "Brier: —",
            ]
            sent = _send_email(
                f"Kalshi Morning Briefing — {datetime.now(UTC).strftime('%Y-%m-%d')}",
                "\n".join(lines),
            )
            if sent:
                print(green("  Morning briefing emailed."))
            else:
                print(
                    dim("  Email not sent (SMTP not configured — set SMTP_* env vars).")
                )
        except Exception as e:
            print(dim(f"  Email failed: {e}"))


def cmd_analyze(
    client: KalshiClient,
    min_edge: float | None = None,
    live: bool = False,  # --live reserved; analyze is display-only
):
    if min_edge is None:
        min_edge = MIN_EDGE
    _header("Trade Opportunity Scanner")
    if min_edge != MIN_EDGE:
        print(dim(f"  Edge threshold: {min_edge:.0%}  (default {MIN_EDGE:.0%})\n"))
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

    closed = 0
    for trade in open_trades:
        ticker = trade.get("ticker", "")
        entry_prob = trade.get("entry_prob")
        side = trade.get("side", "yes")
        if entry_prob is None:
            continue  # cannot assess shift without entry probability

        try:
            markets = get_weather_markets(client)
            market = next((m for m in markets if m.get("ticker") == ticker), None)
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
            _log.warning(f"[EarlyExit] Error checking {ticker}: {exc}")
            continue

    return closed


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

    # C6: for paper mode, pick the A/B test variant and use its threshold.
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


def _rank_opportunities(opportunities: list[dict]) -> list[dict]:
    """
    Rank trade opportunities by composite priority score before execution.
    Score = edge * kelly_fraction * urgency_multiplier
    Ensures highest-value, most-urgent trades execute first in each cron cycle.
    """

    def _score(opp: dict) -> float:
        edge = float(
            opp.get("edge", opp.get("net_edge", opp.get("expected_value", 0))) or 0
        )
        kelly = float(
            opp.get("kelly_fraction", opp.get("ci_adjusted_kelly", opp.get("kelly", 0)))
            or 0
        )
        # Urgency: trades closer to expiry get a small boost (max 1.5x)
        days_out = float(opp.get("days_out", opp.get("days_to_expiry", 3)) or 3)
        urgency = max(0.5, min(1.5, 2.0 / max(days_out, 0.5)))
        return edge * kelly * urgency

    return sorted(opportunities, key=_score, reverse=True)


def cmd_override(action: str, duration_minutes: int = 60) -> None:
    """
    Create a time-limited manual override.
    Overrides expire automatically after duration_minutes.

    Actions:
      pause <minutes>  — pause automated trading for N minutes
      unpause          — remove pause override immediately
      status           — show current override status
    """
    override_path = Path(__file__).parent / "data" / ".manual_override.json"

    if action == "unpause" or action == "status":
        if not override_path.exists():
            print(dim("  No active manual override."))
            return
        try:
            state = json.loads(override_path.read_text())
            expires = state.get("expires_at", 0)
            import time as _time

            remaining = expires - _time.time()
            if remaining <= 0 or action == "unpause":
                override_path.unlink(missing_ok=True)
                print(green("  Manual override cleared."))
            else:
                print(
                    bold(f"\n  Active override: {state.get('reason', 'manual pause')}")
                )
                print(f"  Expires in: {remaining / 60:.0f} minutes")
        except Exception as exc:
            _log.warning("cmd_override: %s", exc)
        return

    if action == "pause":
        import time as _time

        state = {
            "reason": "manual pause",
            "created_at": _time.time(),
            "expires_at": _time.time() + duration_minutes * 60,
            "duration_minutes": duration_minutes,
        }
        override_path.parent.mkdir(exist_ok=True)
        override_path.write_text(json.dumps(state, indent=2))
        print(yellow(f"  Trading paused for {duration_minutes} minutes."))
        print(dim("  Run `py main.py override unpause` to clear early."))
        return

    print(red(f"  Unknown override action: {action!r}"))
    print(dim("  Usage: py main.py override pause [minutes]  |  unpause  |  status"))


def cmd_admin(action: str, reason: str = "manual admin override") -> None:
    """
    Admin commands for paper trading system.

    Actions:
      reset-loss  — waive today's daily loss limit (e.g. after a bug caused
                    phantom losses).  Expires automatically at midnight UTC.
    """
    if action == "reset-loss":
        from paper import reset_daily_loss_limit

        reset_daily_loss_limit(reason=reason)
        print(
            green(
                "  Daily loss limit waived for the rest of today (UTC).\n"
                "  Run cron now — trading will resume normally.\n"
                "  The override expires automatically at midnight UTC."
            )
        )
        return

    print(red(f"  Unknown admin action: {action!r}"))
    print(dim("  Usage: py main.py admin reset-loss"))


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
    from utils import MAX_DAILY_SPEND

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

        # P1.2: Pre-trade validation gate — log every rejection reason.
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

        # P1.5: Daily dedup — don't re-trade same market+side on the same calendar day
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
        # L7-B: initialize ask prices from the stale enriched market dict so we
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
                # L7-B: update ask prices from fresh market when available
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
        # L7-B: fill at ask (not mid) — YES pays yes_ask, NO pays 1 - yes_bid (= no_ask).
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
        from utils import MAX_VAR_DOLLARS

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
                    ab_variant=a.get("_ab_variant"),  # C6: propagate A/B variant tag
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
                # L3-C: log paper order so was_traded_today() blocks same-day re-entry
                # after a position is settled and the process restarts.
                execution_log.log_order(
                    ticker=ticker,
                    side=rec_side,
                    quantity=qty,
                    price=entry_price,
                    order_type="market",
                    status="filled",
                    live=False,
                )
                # #55: update analysis attempt to mark this market as traded
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
                    logging.getLogger(__name__).warning(
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
                    )
                except Exception as _e2:
                    logging.getLogger(__name__).warning(
                        "_auto_place_trades: log_prediction failed for %s: %s",
                        ticker,
                        _e2,
                    )
            except Exception as e:
                # L1-D: surface every placement failure visibly — logging alone is
                # silent when the operator is watching the console.
                _err_msg = (
                    f"  [Auto] PAPER ORDER FAILED {ticker} {rec_side.upper()}: {e}"
                )
                print(red(_err_msg))
                logging.getLogger(__name__).warning(
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

                            _log_live_fill_fn = _log_fill
                            _log_live_fill_fn(
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


def cmd_watch(
    client: KalshiClient,
    auto_trade: bool = False,
    min_edge: float = 0.10,
    live: bool = False,
):
    mode = "AUTO-TRADE" if auto_trade else "Watch"
    print(bold(f"{mode} mode — refreshing every 5 minutes. Press Ctrl+C to stop.\n"))
    if auto_trade:
        print(
            yellow(
                "  Auto-trade: STRONG BUY + LOW risk signals → paper orders placed automatically.\n"
            )
        )
    previous: set = _load_watch_state()
    _price_history: dict[str, float] = {}
    try:
        while True:
            os.system("cls" if sys.platform == "win32" else "clear")
            now = time.strftime("%H:%M:%S")
            print(bold(f"Kalshi Weather Markets — {now}"))
            print(dim("─" * 52))
            print(dim("* = new since last scan   Ctrl+C to exit\n"))
            # Price drift detection — check all liquid markets
            try:
                _drift_markets = get_weather_markets(client)
                for _dm in _drift_markets:
                    _dt = _dm.get("ticker", "")
                    _dp = parse_market_price(_dm).get("yes_ask", 0.0) or 0.0
                    if _dt in _price_history and _dp > 0:
                        _delta = _dp - _price_history[_dt]
                        if abs(_delta) >= 0.03:
                            _dir = "▲" if _delta > 0 else "▼"
                            print(
                                yellow(
                                    f"  [Price drift] {_dt}  YES ask {_dir} {abs(_delta):.2f}  ({_price_history[_dt]:.2f} → {_dp:.2f})"
                                )
                            )
                    if _dp > 0:
                        _price_history[_dt] = _dp
            except Exception:
                pass
            liquid_opps: list = []
            previous = _analyze_once(
                client,
                previous,
                _liquid_opps_out=liquid_opps,
                min_edge=min_edge,
                show_summary=True,
            )
            _save_watch_state(previous)
            live_cfg = _load_live_config() if live else None
            if auto_trade and liquid_opps:
                _auto_place_trades(
                    liquid_opps, client=client, live=live, live_config=live_cfg
                )
            if live:
                _poll_pending_orders(client, config=live_cfg)
            # Check price alerts
            try:
                from alerts import check_alerts, mark_triggered

                triggered = check_alerts(client)
                for item in triggered:
                    a = item["alert"]
                    cp = item["current_price"]
                    print(
                        yellow(
                            f"  [Price alert] {a['ticker']} YES hit {cp:.2f}"
                            f" (target: {a['target_price']:.2f} {a['direction']})"
                        )
                    )
                    mark_triggered(a["id"])
            except Exception:
                pass

            # Check take-profit exit targets
            try:
                from paper import check_exit_targets

                n_exited = check_exit_targets(client)
                if n_exited:
                    print(
                        green(
                            f"  [Auto-exit] {n_exited} position(s) reached take-profit target and were settled."
                        )
                    )
            except Exception:
                pass

            # Check open paper positions for exit signals
            try:
                from paper import check_expiring_trades, check_model_exits

                exit_recs = check_model_exits(client)
                for rec in exit_recs:
                    import paper as _paper_exit

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
                    try:
                        exit_price = _midpoint_price(rec["market"], rec["held_side"])
                        result = _paper_exit.close_paper_early(t["id"], exit_price)
                        print(
                            red(
                                f"  [Closed] #{t['id']} {t['ticker']} "
                                f"@ {exit_price:.0%}  pnl=${result['pnl']:.2f}"
                            )
                        )
                        _log.info(
                            "[ModelExit] #%s %s %s closed: reason=%s edge=%+.3f pnl=$%.2f",
                            t["id"],
                            t["ticker"],
                            rec["held_side"],
                            rec["reason"],
                            rec["current_edge"],
                            result["pnl"],
                        )
                    except Exception as _exc:
                        _log.warning(
                            "[ModelExit] Failed to close #%s: %s", t["id"], _exc
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

    # Show active model weights for this city
    try:
        from tracker import get_model_weights

        weights = get_model_weights(city, window_days=30)
        if weights:
            weight_parts = "  ".join(
                f"{m}: {w:.0%}" for m, w in sorted(weights.items(), key=lambda x: -x[1])
            )
            print(dim(f"\n  Active model weights (30-day MAE): {weight_parts}"))
        else:
            print(
                dim(
                    f"\n  Active model weights: equal (insufficient history for {city})"
                )
            )
    except Exception:
        pass


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

    # ── Rolling Sharpe ───────────────────────────────────────────────────────
    try:
        from paper import get_rolling_sharpe

        sharpe = get_rolling_sharpe(window_days=30)
        if sharpe is not None:
            sharpe_s = (
                green(f"{sharpe:.2f}")
                if sharpe > 1.0
                else yellow(f"{sharpe:.2f}")
                if sharpe > 0
                else red(f"{sharpe:.2f}")
            )
            print(f"  Sharpe (30d): {sharpe_s}  {dim('(annualised, >1.0 = strong)')}")
    except Exception:
        pass

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
        # Unrealized P&L (mark-to-market)
        try:
            from paper import get_unrealized_pnl_paper

            unreal = get_unrealized_pnl_paper(None)  # None = use cached prices
            total_unreal = unreal.get("total_unrealized", 0.0)
            if unreal.get("n", 0) > 0:
                unreal_s = (
                    green(f"+${total_unreal:.2f}")
                    if total_unreal >= 0
                    else red(f"-${abs(total_unreal):.2f}")
                )
                print(f"\n  Unrealized P&L (mark-to-market): {unreal_s}")
        except Exception:
            pass
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


# ── Trade journal ─────────────────────────────────────────────────────────────


def cmd_journal() -> None:
    """Print all paper trades that have a thesis note."""
    from paper import get_all_trades

    all_trades = get_all_trades()
    with_thesis = [t for t in all_trades if t.get("thesis")]
    if not with_thesis:
        print(dim("  No journal entries yet. Add a thesis when placing a trade."))
        return

    _header(f"Trade Journal  ({len(with_thesis)} entries)")
    for t in with_thesis:
        pnl = t.get("pnl")
        settled = t.get("settled", False)
        if settled and pnl is not None:
            outcome_s = (
                green(f"  WIN  +${pnl:.2f}")
                if pnl >= 0
                else red(f"  LOSS -${abs(pnl):.2f}")
            )
        elif settled:
            outcome_s = dim("  settled")
        else:
            outcome_s = yellow("  open")
        date_s = (t.get("entered_at") or "")[:10]
        print(
            f"\n  #{t['id']}  {bold(t['ticker'])}  {t['side'].upper()}"
            f"  @${t.get('entry_price', 0):.3f}  {dim(date_s)}{outcome_s}"
        )
        print(f"  {dim('▸')} {t['thesis']}")
    print()


# ── CSV Export ────────────────────────────────────────────────────────────────


def cmd_export() -> None:
    """Export prediction history and paper trades to CSV in data/exports/."""
    from paper import export_tax_csv, export_trades_csv

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

    # Tax export — paper trades
    tax_year = datetime.now(UTC).year
    tax_path = str(out_dir / f"paper_tax_{tax_year}.csv")
    n3 = export_tax_csv(tax_path, tax_year=tax_year)
    if n3:
        print(
            green(
                f"  Exported {n3} settled paper trades (tax year {tax_year}) → {tax_path}"
            )
        )
        print(
            dim("  Note: This file is for informational purposes only, not tax advice.")
        )
    else:
        print(dim(f"  No settled paper trades for tax year {tax_year} to export."))

    # Tax export — live orders
    from execution_log import export_live_tax_csv

    live_tax_path = str(out_dir / f"live_tax_{tax_year}.csv")
    n4 = export_live_tax_csv(live_tax_path, tax_year=tax_year)
    if n4:
        print(
            green(
                f"  Exported {n4} settled live orders (tax year {tax_year}) → {live_tax_path}"
            )
        )
    else:
        print(dim(f"  No settled live orders for tax year {tax_year} to export."))


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
    from paper import auto_settle_paper_trades

    print("Syncing settled markets...")
    count = sync_outcomes(client)
    paper = auto_settle_paper_trades(client)
    print(green(f"Done — {count} outcome(s) recorded, {paper} paper trade(s) settled."))


# ── Onboarding wizard ─────────────────────────────────────────────────────────

_ONBOARDED_MARKER = Path(__file__).parent / "data" / ".onboarded"


def _needs_onboarding() -> bool:
    """Return True if this looks like a first run (no .env or no trades ever placed)."""
    if _ONBOARDED_MARKER.exists():
        return False
    env_path = Path(__file__).parent / ".env"
    if not env_path.exists():
        return True
    from paper import get_all_trades

    return len(get_all_trades()) == 0


def cmd_onboard() -> None:
    """5-step interactive onboarding guide for first-time users."""
    print(bold("\n  ══════════════════════════════════════════"))
    print(bold("   Welcome to Kalshi Weather Trader!"))
    print(bold("  ══════════════════════════════════════════"))
    print()
    print("  This tool helps you find and bet on weather")
    print("  prediction markets on Kalshi.com.")
    print()
    print("  Let's get you set up in 5 steps.")
    print(dim("  Press Enter to continue at each step."))

    try:
        # Step 1
        print(bold("\n  ── Step 1: What is this? ─────────────────"))
        print("  Kalshi lets you bet YES or NO on questions")
        print('  like "Will NYC hit 72°F on April 12?"')
        print()
        print("  If you bet YES at 52¢ and you're right,")
        print("  you win 48¢ per contract (minus a 7% fee).")
        print("  If wrong, you lose your 52¢.")
        print()
        print("  This tool uses weather forecast models to")
        print("  find markets where the price seems wrong.")
        input(dim("  [Press Enter]"))

        # Step 2
        print(bold("\n  ── Step 2: API Keys ──────────────────────"))
        print("  To fetch market data, you need a free")
        print("  Kalshi API key.")
        print()
        print("  1. Go to kalshi.com → Account → API Keys")
        print("  2. Create a new key, download the .pem file")
        print("  3. Copy .env.example to .env")
        print("  4. Fill in KALSHI_KEY_ID and path to .pem")
        print()
        input(dim("  Have you done this? (y/skip): "))

        # Step 3
        print(bold("\n  ── Step 3: Reading the Analyze table ─────"))
        print("  Press A from the main menu to see markets.")
        print()
        print("  The table shows:")
        print(f"  {green('★★★')} = Strong opportunity (>25% edge)")
        print(f"  {yellow('★★')}  = Good opportunity (>15% edge)")
        print(f"  {dim('★')}   = Weak opportunity (>10% edge)")
        print()
        print('  "Edge" = how much better our model thinks')
        print("  the odds are vs. what the market charges.")
        input(dim("  [Press Enter]"))

        # Step 4
        print(bold("\n  ── Step 4: Your first paper trade ────────"))
        print("  Paper trading uses fake money ($1,000 to")
        print("  start) so you can practice risk-free.")
        print()
        print("  To place your first trade:")
        print("  1. Press A to Analyze")
        print("  2. Find a ★★★ signal")
        print("  3. Press P → 2 → Buy")
        print("  4. Follow the prompts")
        print()
        print(dim("  Tip: Start with small bets (1-2 contracts)"))
        print(dim("  until you understand how it works."))
        input(dim("  [Press Enter]"))

        # Step 5
        print(bold("\n  ── Step 5: Tracking your performance ─────"))
        print("  After 10+ trades, press K (Backtest) to")
        print("  see how accurate the model has been.")
        print()
        print("  Press R (Brief) each morning for a quick")
        print("  summary of your positions and opportunities.")
        print()
        print("  Press ? anytime for the help guide.")
        input(dim("  [Press Enter]"))

        print(bold("\n  ══════════════════════════════════════════"))
        print(bold("   You're all set! Press Enter for the menu."))
        print(bold("  ══════════════════════════════════════════"))
        input()

    except (KeyboardInterrupt, EOFError):
        print()

    # Write marker so onboarding only runs once
    try:
        _ONBOARDED_MARKER.parent.mkdir(exist_ok=True)
        _ONBOARDED_MARKER.write_text("onboarded")
    except Exception:
        pass


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


# ── Help screen ───────────────────────────────────────────────────────────────


def cmd_kill() -> None:
    """Activate the kill switch — stops all automated trading immediately."""
    kill_path = Path(__file__).parent / "data" / ".kill_switch"
    kill_path.parent.mkdir(exist_ok=True)
    kill_path.touch()
    print(
        red("  Kill switch ACTIVATED. Automated trading will stop at next cron cycle.")
    )
    print(dim("  Run `py main.py resume` to re-enable trading."))


def cmd_resume() -> None:
    """Remove the kill switch — re-enables automated trading. Also clears black swan state."""
    kill_path = Path(__file__).parent / "data" / ".kill_switch"
    if kill_path.exists():
        kill_path.unlink()
        print(green("  Kill switch removed. Trading re-enabled."))
    else:
        print(dim("  No kill switch active."))

    # P10.2: also clear black swan state file if present
    try:
        from alerts import clear_black_swan_state as _clear_bs
        from alerts import get_black_swan_status as _bs_status

        bs = _bs_status()
        if bs:
            _clear_bs()
            print(
                yellow(
                    f"  Black swan state cleared (was: {bs.get('reason', 'unknown')[:60]})"
                )
            )
    except Exception:
        pass


def cmd_drift() -> None:
    """P10.1: Show Brier score drift analysis — detects slow performance degradation."""
    from tracker import detect_brier_drift

    result = detect_brier_drift()
    _header("Brier Drift Analysis", width=58)
    print(f"  Weeks analyzed : {result['weeks_analyzed']}")
    if result["early_brier"] is not None:
        status = red("DRIFT DETECTED") if result["drifting"] else green("OK")
        print(f"  Early Brier    : {result['early_brier']:.4f}")
        print(f"  Recent Brier   : {result['recent_brier']:.4f}")
        delta = result["delta"]
        delta_str = f"{delta:+.4f}"
        print(
            f"  Delta          : {red(delta_str) if result['drifting'] else dim(delta_str)}"
        )
        print(f"  Status         : {status}")
    print(f"\n  {result['message']}\n")


def cmd_version_compare() -> None:
    """P9.1: Compare Brier scores across strategy versions (edge_calc_version)."""
    from tracker import get_brier_by_version

    versions = get_brier_by_version()
    _header("Strategy Version Performance", width=50)
    if not versions:
        print(dim("  No version-stamped predictions settled yet."))
        print(dim("  Predictions will be stamped once trading resumes.\n"))
        return
    print(f"  {'Version':<12} {'Brier':>8} {'Samples':>9}")
    print("  " + "─" * 32)
    for v, info in sorted(versions.items()):
        brier_str = f"{info['brier']:.4f}"
        color_fn = (
            green if info["brier"] < 0.20 else (yellow if info["brier"] < 0.25 else red)
        )
        print(f"  {v:<12} {color_fn(brier_str):>8} {info['n']:>9}")
    print()


def cmd_train_bias() -> None:
    """Train ML bias correction models from tracker DB data."""
    from ml_bias import train_bias_model

    print("Training ML bias models (requires 200+ settled trades per city)...")
    models = train_bias_model(min_samples=200)
    if not models:
        print("Not enough data yet. Keep trading — retrain after 6 months.")
    else:
        print(f"Trained models for: {', '.join(sorted(models.keys()))}")


def cmd_retire_strategies(run: bool = False) -> None:
    """P9.5: Show retired strategy methods; with --run auto-retires failing ones."""
    from tracker import auto_retire_strategies, get_retired_strategies

    if run:
        newly = auto_retire_strategies()
        if newly:
            print(
                red(
                    f"\n  Retired {len(newly)} strategy method(s): {', '.join(newly)}\n"
                )
            )
        else:
            print(
                green("\n  No new strategies retired — all methods within threshold.\n")
            )

    retired = get_retired_strategies()
    _header("Retired Strategies", width=58)
    if not retired:
        print(dim("  No strategies retired yet.\n"))
        return
    print(f"  {'Method':<30} {'Brier':>8} {'Retired At'}")
    print("  " + "─" * 62)
    for method, info in retired.items():
        brier_str = f"{info.get('brier', 0):.4f}"
        retired_at = info.get("retired_at", "")[:19]
        print(f"  {method:<30} {red(brier_str):>8}  {dim(retired_at)}")
    print()


def cmd_config_check() -> None:
    """P10.3: Show current config fingerprint and detect cross-run changes."""
    from utils import check_config_integrity, get_config_fingerprint

    result = check_config_integrity()
    fp = get_config_fingerprint()

    _header("Config Integrity", width=58)
    status = red("CHANGED") if result["changed"] else green("UNCHANGED")
    print(f"  Status         : {status}")
    print(f"  Current hash   : {result['current_hash']}")
    if result["previous_hash"]:
        print(f"  Previous hash  : {result['previous_hash']}")
    if result["changed_keys"]:
        print(f"  Changed keys   : {', '.join(result['changed_keys'])}")
    print()
    print(f"  {'Parameter':<28} {'Value'}")
    print("  " + "─" * 48)
    for k, v in fp.items():
        highlight = bold if k in result.get("changed_keys", []) else dim
        print(f"  {k:<28} {highlight(str(v))}")
    print()


def cmd_code_audit() -> None:
    """P10.4: Feature sprawl audit — list file sizes and orphan cmd_ functions."""
    import ast

    base = Path(__file__).parent
    py_files = sorted(base.glob("*.py"))

    _header("Code Audit", width=62)
    print(f"  {'File':<35} {'Lines':>7} {'Functions':>10}")
    print("  " + "─" * 56)

    total_lines = 0
    all_defined: dict[str, str] = {}  # name → file

    for fp in py_files:
        try:
            src = fp.read_text(encoding="utf-8")
            lines = src.count("\n")
            total_lines += lines
            try:
                tree = ast.parse(src)
                fns = [
                    n.name
                    for n in ast.walk(tree)
                    if isinstance(n, ast.FunctionDef) and not n.name.startswith("_")
                ]
                for fn in fns:
                    all_defined[fn] = fp.name
                fn_count = len(fns)
            except SyntaxError:
                fn_count = 0
            flag = (
                red(" !!!") if lines > 3000 else (yellow(" !") if lines > 1000 else "")
            )
            print(f"  {fp.name:<35} {lines:>7}{flag}  {fn_count:>8}")
        except Exception:
            pass

    print(f"\n  Total: {total_lines:,} lines across {len(py_files)} files")

    # Find cmd_ functions defined but not referenced in the dispatch block
    try:
        main_src = (base / "main.py").read_text(encoding="utf-8")
        dispatch_src = main_src[main_src.find("def main(") :]
        defined_cmds = [n for n in all_defined if n.startswith("cmd_")]
        orphans = [c for c in defined_cmds if c not in dispatch_src]
        if orphans:
            print(f"\n  {yellow('Orphan cmd_ functions (not in dispatch):')}")
            for fn in sorted(orphans):
                print(f"    {dim(fn)}  [{all_defined[fn]}]")
        else:
            print(f"\n  {green('All cmd_ functions are referenced in dispatch.')}")
    except Exception:
        pass
    print()


def cmd_features() -> None:
    """Show feature importance summary from historical trades."""
    from feature_importance import get_feature_summary

    summary = get_feature_summary()
    if not summary:
        print(dim("  No feature data yet. Features are recorded as trades are placed."))
        return
    print(bold("\n  Feature Importance Summary"))
    print(f"  {'Feature':<30} {'Win Avg':>10} {'Loss Avg':>10} {'Trades':>8}")
    print("  " + "─" * 62)
    for feat, stats in summary.items():
        win_avg = f"{stats['win_avg']:.4f}" if stats["win_avg"] is not None else "N/A"
        loss_avg = (
            f"{stats['loss_avg']:.4f}" if stats["loss_avg"] is not None else "N/A"
        )
        print(f"  {feat:<30} {win_avg:>10} {loss_avg:>10} {stats['total']:>8}")
    print()


def cmd_help() -> None:
    """Print compact quick-reference guide."""
    _header("Quick Reference", width=58)
    lines = [
        ("A", "Analyze ", "Best opportunities right now, sorted by edge"),
        ("T", "Today   ", "What should I do today? Plain-English recommendation"),
        ("W", "Watch   ", "Auto-refreshes every 5 min, alerts on new signals"),
        ("P", "Paper   ", "Simulate trades, track P&L, set price alerts"),
        ("K", "Backtest", "How well has the model done on past markets?"),
        ("R", "Brief   ", "Morning summary: balance, top picks, warnings"),
        ("B", "Browse  ", "See all open markets for a city"),
        ("S", "Settings", "Change edge thresholds, loss limits, fees"),
        ("?", "Help    ", "This screen"),
    ]
    for key, name, desc in lines:
        print(f"  {bold(key)}  {cyan(name)}  {dim(desc)}")

    print(bold("\n  In analyze table:"))
    print(
        f"    {green('★★★')} = strong edge (>25%)   {yellow('★★')} = good (>15%)"
        f"   {dim('★')} = weak (>10%)"
    )
    print("    Edge = how much better our model is vs market price")
    print("    Risk = LOW (market closes soon, data reliable) / HIGH (far out)")

    print(bold("\n  Tips for beginners:"))
    print(
        f"    {dim('-')} Only bet {green('★★★')} signals until you have 20+ settled trades"
    )
    print(f"    {dim('-')} Never bet more than 5% of your balance on one trade")
    print(f"    {dim('-')} Run K Backtest monthly to check the model is still working")


# ── Browse markets ────────────────────────────────────────────────────────────

_BROWSE_CITIES = [
    "NYC",
    "Chicago",
    "LA",
    "Boston",
    "Miami",
    "Dallas",
    "Phoenix",
    "Seattle",
    "Denver",
    "Atlanta",
]


def cmd_browse(client: KalshiClient) -> None:
    """Browse open markets by city."""
    _header("Browse Markets by City")

    # City picker
    for i, city in enumerate(_BROWSE_CITIES, 1):
        print(f"  {cyan(str(i)):<5} {city}")
    print()
    raw = input(dim("  Pick a city (1–10, or Enter for all): ")).strip()

    city_filter: str | None = None
    if raw.isdigit() and 1 <= int(raw) <= len(_BROWSE_CITIES):
        city_filter = _BROWSE_CITIES[int(raw) - 1]

    # Fetch markets
    try:
        all_markets = get_weather_markets(client)
    except Exception as _e:
        short_msg = str(_e)[:120]
        print(
            red(
                "  Could not reach Kalshi API. Check your internet connection and try again."
            )
        )
        print(dim(f"  (Error: {short_msg})"))
        return

    if city_filter:
        # Match city name case-insensitively against the _city field
        cf_lower = city_filter.lower()
        markets = [
            m
            for m in all_markets
            if (m.get("_city") or "").lower() == cf_lower
            or cf_lower in (m.get("title") or "").lower()
        ]
        if not markets:
            # Fall back to substring match on ticker
            markets = [
                m for m in all_markets if cf_lower in (m.get("ticker") or "").lower()
            ]
    else:
        markets = all_markets

    if not markets:
        city_label = city_filter or "all cities"
        print(yellow(f"  No open weather markets found for {city_label}."))
        return

    def _market_price_row(i: int, m: dict, analysis: dict | None = None) -> list:
        """Build a single browse table row, optionally with signal columns."""
        from weather_markets import parse_market_price as _pmp

        prices = _pmp(m)
        yes_bid = prices.get("yes_bid") or 0
        yes_ask = prices.get("yes_ask") or 0
        mid = prices.get("mid") or 0

        bid_s = f"${yes_bid:.2f}" if yes_bid > 0 else dim("—")
        ask_s = f"${yes_ask:.2f}" if yes_ask > 0 else dim("—")
        spread = yes_ask - yes_bid if yes_ask > 0 and yes_bid > 0 else None
        spread_s = f"${round(spread, 2):.2f}" if spread is not None else dim("—")
        mid_s = f"${mid:.2f}" if mid > 0 else dim("—")

        raw_last = m.get("last_price_dollars") or m.get("last_price") or 0
        try:
            last_f = float(raw_last)
            if last_f > 1:
                last_f /= 100.0
        except (TypeError, ValueError):
            last_f = 0.0
        last_s = f"${last_f:.2f}" if last_f > 0 else dim("—")

        raw_vol = m.get("volume_fp") or m.get("volume") or m.get("volume_24h_fp") or 0
        try:
            vol_f = float(raw_vol)
        except (TypeError, ValueError):
            vol_f = 0.0
        raw_oi = m.get("open_interest_fp") or m.get("open_interest") or 0
        try:
            oi_f = float(raw_oi)
        except (TypeError, ValueError):
            oi_f = 0.0
        activity = vol_f + oi_f
        vol_s = f"{activity:,.0f}" if activity > 0 else dim("—")

        closes = _format_expiry(m.get("close_time", ""))
        title = (m.get("title") or m.get("ticker", ""))[:36]
        ticker = m.get("ticker", "")

        row = [
            cyan(str(i)),
            ticker,
            title,
            bid_s,
            ask_s,
            spread_s,
            mid_s,
            last_s,
            vol_s,
            closes,
        ]

        if analysis is not None:
            prob = analysis.get("forecast_prob")
            edge = analysis.get("net_edge") or analysis.get("edge") or 0
            side = analysis.get("recommended_side", "")
            prob_s = f"{prob * 100:.0f}%" if prob is not None else dim("—")
            if edge >= 0.10:
                edge_s = green(f"+{edge * 100:.0f}%")
                signal_s = green(f"BUY {side.upper()}" if side else "BUY")
            elif edge >= 0.05:
                edge_s = yellow(f"+{edge * 100:.0f}%")
                signal_s = yellow("MAYBE")
            elif edge <= -0.05:
                edge_s = red(f"{edge * 100:.0f}%")
                signal_s = red("SKIP")
            else:
                edge_s = dim(f"{edge * 100:.0f}%")
                signal_s = dim("SKIP")
            row += [prob_s, edge_s, signal_s]
        return row

    # Build display table
    ticker_list = [m.get("ticker", "") for m in markets]
    rows = [_market_price_row(i, m) for i, m in enumerate(markets, 1)]

    base_headers = [
        "#",
        "Ticker",
        "Title",
        "Bid",
        "Ask",
        "Spread",
        "Mid",
        "Last",
        "Vol+OI",
        "Closes",
    ]

    def _print_table(rows: list, with_signals: bool = False) -> None:
        headers = base_headers + (["Prob", "Edge", "Signal"] if with_signals else [])
        print(tabulate(rows, headers=headers, tablefmt="rounded_outline"))

    _print_table(rows)
    city_label = city_filter or "all cities"
    print(dim(f"\n  {len(markets)} markets — {city_label}"))

    # Action prompt
    analysis_cache: dict[str, dict] = {}

    while True:
        raw2 = input(
            dim(
                "  # for details  A analyze signals  F forecast  C arbitrage  Enter back: "
            )
        ).strip()
        if not raw2:
            return
        if raw2.upper() == "A":
            from concurrent.futures import ThreadPoolExecutor
            from concurrent.futures import as_completed as _as_completed

            print(dim(f"  Scanning {len(markets)} markets…"))

            def _do_analyze(m: dict) -> tuple[str, dict | None]:
                try:
                    enriched = enrich_with_forecast(m)
                    return m.get("ticker", ""), analyze_trade(enriched)
                except Exception:
                    return m.get("ticker", ""), None

            with ThreadPoolExecutor(max_workers=20) as pool:
                futures = {pool.submit(_do_analyze, m): m for m in markets}
                for fut in _as_completed(futures):
                    ticker_key, result = fut.result()
                    if result:
                        analysis_cache[ticker_key] = result

            signal_rows = [
                _market_price_row(i, m, analysis_cache.get(m.get("ticker", "")))
                for i, m in enumerate(markets, 1)
            ]
            _print_table(signal_rows, with_signals=True)
            buys = sum(
                1
                for m in markets
                if (analysis_cache.get(m.get("ticker", "")) or {}).get("net_edge", 0)
                >= 0.10
            )
            print(
                dim(f"\n  {len(markets)} markets — {buys} strong signals (edge ≥10%)")
            )
        elif raw2.upper() == "F":
            if city_filter:
                cmd_forecast(city_filter)
            else:
                city_in = input(
                    dim(f"  City ({'/'.join(CITY_COORDS.keys())}): ")
                ).strip()
                if city_in:
                    cmd_forecast(city_in)
        elif raw2.upper() == "C":
            cmd_consistency(client)
        elif raw2.isdigit() and 1 <= int(raw2) <= len(ticker_list):
            ticker = ticker_list[int(raw2) - 1]
            verbose = input(dim("  Verbose detail? (y/N): ")).strip().lower() == "y"
            cmd_market(client, ticker, verbose=verbose)
        else:
            print(red("  Invalid choice."))


# ── Settings screen ───────────────────────────────────────────────────────────


def cmd_settings(client: KalshiClient | None = None) -> None:  # noqa: ARG001
    """View and edit configurable settings."""
    import importlib

    import utils as _utils_mod

    # Reload to get latest values
    importlib.reload(_utils_mod)

    env_path = Path(__file__).parent / ".env"
    if not env_path.exists():
        # also check cwd
        env_path_cwd = Path(".env")
        if env_path_cwd.exists():
            env_path = env_path_cwd

    def _read_env() -> dict[str, str]:
        lines: dict[str, str] = {}
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if "=" in line and not line.strip().startswith("#"):
                    k, _, v = line.partition("=")
                    lines[k.strip()] = v.strip()
        return lines

    def _write_env(key: str, value: str) -> None:
        existing = {}
        existing_lines: list[str] = []
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                existing_lines.append(line)
                if "=" in line and not line.strip().startswith("#"):
                    k, _, _ = line.partition("=")
                    existing[k.strip()] = len(existing_lines) - 1

        if key in existing:
            existing_lines[existing[key]] = f"{key}={value}"
        else:
            existing_lines.append(f"{key}={value}")

        env_path.write_text("\n".join(existing_lines) + "\n")

    while True:
        importlib.reload(_utils_mod)
        env_vals = _read_env()
        _header("Settings")

        setting_keys = [
            ("MIN_EDGE", "minimum edge to show in analyze", "0-1"),
            ("STRONG_EDGE", "threshold for STRONG BUY signal", "0-1"),
            ("MAX_DAILY_LOSS_PCT", "halt trading if down this % today", "0-1"),
            ("MAX_POSITION_AGE_DAYS", "warn on positions older than N days", "int"),
            ("KALSHI_FEE_RATE", "fee on winnings", "0-1"),
            ("KALSHI_ENV", "demo or prod", "demo/prod"),
        ]

        for i, (key, desc, _fmt) in enumerate(setting_keys, 1):
            cur = env_vals.get(key) or str(getattr(_utils_mod, key, "—"))
            print(f"  {cyan(str(i)):<5} {bold(key):<26} {green(cur):<12} {dim(desc)}")

        print()
        print(f"  {cyan('H')}    History        — past predictions + Brier score")
        print(f"  {cyan('E')}    Export data    — save predictions + trades to CSV")
        print(f"  {cyan('W')}    Web dashboard  — local web dashboard (localhost:5000)")
        print(f"  {cyan('X')}    Simulate       — replay historical markets (sandbox)")
        print(f"  {cyan('Y')}    Weekly summary — generate weekly recap")
        print()

        raw = input(dim("  Number to edit, or letter, or Enter to go back: ")).strip()
        if not raw:
            return

        # Letter shortcuts
        if raw.upper() == "H":
            _c = client if client else build_client()
            cmd_history(_c)
            input(dim("\n  Press Enter to return to settings..."))
            continue
        if raw.upper() == "E":
            cmd_export()
            input(dim("\n  Press Enter to return to settings..."))
            continue
        if raw.upper() == "W":
            _c2 = client if client else build_client()
            cmd_web(_c2)
            continue
        if raw.upper() == "X":
            _c3 = client if client else build_client()
            cmd_simulate(_c3)
            input(dim("\n  Press Enter to return to settings..."))
            continue
        if raw.upper() == "Y":
            cmd_weekly_summary()
            input(dim("\n  Press Enter to return to settings..."))
            continue
        if not raw.isdigit() or not (1 <= int(raw) <= len(setting_keys)):
            print(red("  Invalid choice."))
            continue

        idx = int(raw) - 1
        key, desc, fmt = setting_keys[idx]
        cur = env_vals.get(key) or str(getattr(_utils_mod, key, ""))
        new_val = input(dim(f"  {key} [{cur}] ({fmt}): ")).strip()
        if not new_val:
            continue

        # Validate
        valid = True
        if fmt == "0-1":
            try:
                fv = float(new_val)
                if not 0 <= fv <= 1:
                    valid = False
            except ValueError:
                valid = False
        elif fmt == "int":
            try:
                int(new_val)
            except ValueError:
                valid = False
        elif fmt == "demo/prod":
            if new_val not in ("demo", "prod"):
                valid = False

        if not valid:
            print(red(f"  Invalid value for {key} (expected {fmt})."))
            continue

        # Try python-dotenv first
        try:
            from dotenv import set_key as _set_key

            _set_key(str(env_path), key, new_val)
        except Exception:
            _write_env(key, new_val)

        # Reload env + modules
        load_dotenv(override=True)
        try:
            importlib.reload(_utils_mod)
            import paper as _paper_mod

            importlib.reload(_paper_mod)
        except Exception:
            pass

        print(green(f"  Updated {key} → {new_val}"))


# ── Alerts manager ────────────────────────────────────────────────────────────


def _cmd_alerts() -> None:
    """Price alert manager — used in the Paper submenu."""
    from alerts import add_alert, get_alerts, remove_alert

    while True:
        _header("Price Alerts")
        active = get_alerts()
        if active:
            print("  Active alerts:")
            for a in active:
                created = (a.get("created_at") or "")[:10]
                direction_sym = "<" if a["direction"] == "below" else ">"
                print(
                    f"  #{a['id']}  {bold(a['ticker']):<35} YES {direction_sym}"
                    f" {a['target_price']:.2f}  {dim(f'(set {created})')}"
                )
        else:
            print(dim("  No active alerts."))

        print()
        print(f"  {cyan('1')}  Add alert")
        print(f"  {cyan('2')}  Remove alert")
        print(dim("  Enter  Back"))
        print()

        sub = input(dim("  Choose (1/2 or Enter): ")).strip()
        if not sub:
            return

        if sub == "1":
            # Add alert flow
            try:
                ticker_in = input(dim("  Ticker: ")).strip().upper()
                if not ticker_in:
                    continue
                dir_in = (
                    input(dim("  Direction (below/above, default below): "))
                    .strip()
                    .lower()
                    or "below"
                )
                if dir_in not in ("below", "above"):
                    print(red("  Direction must be 'below' or 'above'."))
                    continue
                price_raw = input(dim("  Target YES price (0-1): ")).strip()
                if not price_raw:
                    continue
                try:
                    target = float(price_raw)
                    if not 0 < target < 1:
                        print(red("  Price must be between 0 and 1."))
                        continue
                except ValueError:
                    print(red("  Enter a decimal like 0.35"))
                    continue
                a = add_alert(ticker_in, target, dir_in)
                direction_sym = "<" if dir_in == "below" else ">"
                print(
                    green(
                        f"  Alert set: {a['ticker']} YES {direction_sym} {target:.2f}"
                    )
                )
            except (KeyboardInterrupt, EOFError):
                print()

        elif sub == "2":
            if not active:
                print(dim("  No active alerts to remove."))
                continue
            try:
                id_raw = input(dim("  Alert # to remove (q to cancel): ")).strip()
                if id_raw.lower() == "q":
                    continue
                try:
                    aid = int(id_raw)
                except ValueError:
                    print(red("  Enter an alert number."))
                    continue
                removed = remove_alert(aid)
                if removed:
                    print(green(f"  Alert #{aid} removed."))
                else:
                    print(red(f"  Alert #{aid} not found."))
            except (KeyboardInterrupt, EOFError):
                print()


# ── Walk-forward test ─────────────────────────────────────────────────────────


def cmd_walkforward(client: KalshiClient) -> None:
    """Run a walk-forward validation and display stability metrics."""
    from backtest import run_walk_forward

    _header("Walk-Forward Validation")
    print(dim("  Running walk-forward test (this may take a moment)...\n"))
    try:
        result = run_walk_forward(client)
    except Exception as e:
        print(red(f"  Walk-forward test failed: {e}"))
        return

    avg_brier = result.get("avg_brier")
    avg_win_rate = result.get("avg_win_rate")
    stability_score = result.get("stability_score")
    trend = result.get("trend", "")

    brier_s = (
        green(f"{avg_brier:.4f}")
        if avg_brier is not None and avg_brier < 0.18
        else yellow(f"{avg_brier:.4f}")
        if avg_brier is not None and avg_brier < 0.25
        else red(f"{avg_brier:.4f}")
        if avg_brier is not None
        else dim("—")
    )
    wr_s = (
        green(f"{avg_win_rate:.1%}")
        if avg_win_rate is not None and avg_win_rate > 0.55
        else f"{avg_win_rate:.1%}"
        if avg_win_rate is not None
        else dim("—")
    )
    stab_s = (
        green(f"{stability_score:.3f}")
        if stability_score is not None and stability_score > 0.7
        else yellow(f"{stability_score:.3f}")
        if stability_score is not None and stability_score > 0.5
        else red(f"{stability_score:.3f}")
        if stability_score is not None
        else dim("—")
    )
    trend_s = (
        (
            green(trend)
            if "improv" in trend.lower()
            else red(trend)
            if "degrad" in trend.lower()
            else dim(trend)
        )
        if trend
        else dim("—")
    )

    wf_rows = [
        ["Avg Brier", brier_s],
        ["Avg Win Rate", wr_s],
        ["Stability Score", stab_s],
        ["Trend", trend_s],
    ]
    print(tabulate(wf_rows, headers=["Metric", "Value"], tablefmt="rounded_outline"))

    # Offer to save learned weights if city_win_rates is populated
    city_win_rates = result.get("city_win_rates", {})
    if city_win_rates:
        print(
            f"\n  Walk-forward learned win rates for {len(city_win_rates)} city/type(s)."
        )
        try:
            save_choice = (
                input(dim("  Save as learned weights? (y/N): ")).strip().lower()
            )
            if save_choice == "y":
                save_learned_weights(city_win_rates)
                # #25/#118: also update weights from tracker MAE data
                try:
                    from weather_markets import update_learned_weights_from_tracker

                    tracker_weights = update_learned_weights_from_tracker()
                    if tracker_weights:
                        print(
                            green(
                                f"  MAE-derived weights updated for {len(tracker_weights)} cities."
                            )
                        )
                except Exception:
                    pass
                print(green("  Learned weights saved."))
        except (KeyboardInterrupt, EOFError):
            print()


# ── Walk-Forward Backtesting (paper trade history) ───────────────────────────


def cmd_walk_forward() -> None:
    """Run walk-forward backtest on historical paper trades."""
    import json
    from pathlib import Path

    from backtest import walk_forward_backtest
    from paper import load_paper_trades

    trades_raw = load_paper_trades()
    trades = [
        {
            "market_date": t.get("date", t.get("placed_at", ""))[:10],
            "our_prob": t.get("our_prob", t.get("forecast_prob")),
            "settled_yes": t.get("outcome") == "yes",
            "city": t.get("city", ""),
            "method": t.get("method", ""),
            "edge": t.get("edge", 0),
        }
        for t in trades_raw
        if t.get("outcome") in ("yes", "no")
        and (t.get("our_prob") is not None or t.get("forecast_prob") is not None)
    ]
    # Drop trades with no parseable date — empty strings corrupt fold boundaries.
    trades = [t for t in trades if len(t.get("market_date", "")) == 10]

    if len(trades) < 50:
        print(
            f"Not enough settled trades for walk-forward (have {len(trades)}, need 50+)."
        )
        return

    # train_months=3: paper-trade history is short, so 3 months is more practical
    # than the 6-month default.
    result = walk_forward_backtest(trades, train_months=3, test_months=1)

    std_str = f"{result['std_brier']}" if result["std_brier"] is not None else "\u2014"
    print(f"\nWalk-Forward Backtest ({result['n_folds']} folds)")
    print(f"Mean out-of-sample Brier: {result['mean_brier']} \u00b1 {std_str}")
    print()
    print(f"{'Test Period':<25} {'N Train':>8} {'N Test':>8} {'Brier':>8}")
    print("-" * 55)
    for fold in result["folds"]:
        brier_str = f"{fold['brier']:.4f}" if fold["brier"] is not None else "\u2014"
        print(
            f"{fold['test_period']:<25} {fold['n_train']:>8} {fold['n_test']:>8} {brier_str:>8}"
        )

    out_path = Path(__file__).parent / "data" / "walk_forward_results.json"
    out_path.write_text(json.dumps(result, indent=2))
    print(f"\nSaved to {out_path}")


# ── Weekly PDF report ─────────────────────────────────────────────────────────


def cmd_report() -> None:
    """Generate a weekly PDF/text report and print the output path."""
    from pdf_report import generate_weekly_report

    _header("Weekly Report")
    print(dim("  Generating weekly report...\n"))
    try:
        out_path = generate_weekly_report()
        print(green(f"  Report saved → {out_path}"))
    except Exception as e:
        print(red(f"  Failed to generate report: {e}"))


# ── Blend-weight calibration ──────────────────────────────────────────────────


_CALIBRATE_DATA_DIR: "Path | None" = None  # overridable in tests


def cmd_calibrate() -> None:
    """Recompute seasonal and per-city blend weights from settled predictions."""
    import json

    from calibration import calibrate_city_weights, calibrate_seasonal_weights
    from tracker import DB_PATH

    data_dir = (
        _CALIBRATE_DATA_DIR
        if _CALIBRATE_DATA_DIR is not None
        else Path(__file__).parent / "data"
    )
    data_dir.mkdir(exist_ok=True)

    print("Running blend-weight calibration from settled predictions…")
    print(f"  Database: {DB_PATH}")

    try:
        seasonal = calibrate_seasonal_weights(DB_PATH)
        city = calibrate_city_weights(DB_PATH)
    except Exception as exc:  # noqa: BLE001
        print(f"\nCalibration skipped — could not read DB: {exc}")
        print(
            "(The predictions table may be missing ensemble_prob/nws_prob/clim_prob columns.)"
        )
        print("Run the app normally to populate predictions, then re-run calibrate.")
        return

    seasonal_path = data_dir / "seasonal_weights.json"
    city_path = data_dir / "city_weights.json"

    seasonal_path.write_text(json.dumps(seasonal, indent=2))
    city_path.write_text(json.dumps(city, indent=2))

    if seasonal:
        print(f"\nSeasonal weights ({len(seasonal)} seasons calibrated):")
        for season, w in sorted(seasonal.items()):
            print(
                f"  {season:8s}: ensemble={w['ensemble']:.2f}  clim={w['climatology']:.2f}  nws={w['nws']:.2f}"
            )
    else:
        print(
            "\nSeasonal weights: insufficient data for all seasons — using hardcoded defaults."
        )

    if city:
        print(f"\nCity weights ({len(city)} cities calibrated):")
        for c, w in sorted(city.items()):
            print(
                f"  {c:12s}: ensemble={w['ensemble']:.2f}  clim={w['climatology']:.2f}  nws={w['nws']:.2f}"
            )
    else:
        print("\nCity weights: insufficient data for any city — using defaults.")

    print(f"\nWritten to: {seasonal_path}")
    print(f"           {city_path}")
    print("Restart the app (or re-import weather_markets) to pick up new weights.")


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
        # ── Post-mortem ───────────────────────────────────────────────────────
        try:
            from tracker import get_history

            outcome_yes = outcome_raw == "yes"
            entry_prob = t.get("entry_prob")
            print(bold("\n  ── Post-mortem ──"))
            pred_str = f"{entry_prob * 100:.0f}% YES" if entry_prob is not None else "?"
            actual_str = ("YES " + green("✓")) if outcome_yes else ("NO  " + red("✗"))
            was_right = (entry_prob is not None and entry_prob > 0.5) == outcome_yes
            result_mark = green("✓") if was_right else red("✗")
            print(f"  You predicted: {pred_str}   Actual: {actual_str}   {result_mark}")
            # Find closest source from tracker prediction record
            ticker = t.get("ticker", "")
            hist = get_history(100)
            pred_rec = next((r for r in hist if r["ticker"] == ticker), None)
            if pred_rec:
                sources = {
                    "Ensemble": pred_rec.get("our_prob"),
                    "NWS": None,
                    "Climatology": None,
                }
                actual_val = 1 if outcome_yes else 0
                best_src = min(
                    (
                        (src, abs(p - actual_val))
                        for src, p in sources.items()
                        if p is not None
                    ),
                    key=lambda x: x[1],
                    default=(None, None),
                )
                if best_src[0]:
                    print(f"  Closest source: {best_src[0]}")
            print(f"  P&L: {pnl_s}")
        except Exception:
            pass
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

    # Top-level options: (shortcut_key, label, description)
    top_options = [
        ("A", "Analyze ", "find best trades right now"),
        ("T", "Today   ", "what should I do today?"),
        ("L", "Cron    ", "scan markets and place trades now"),
        ("W", "Watch   ", "live auto-refresh dashboard"),
        ("P", "Paper   ", "trades, alerts, results, settle"),
        ("K", "Backtest", "score model on history"),
        ("V", "Validate", "walk-forward model validation"),
        ("X", "Report  ", "generate weekly PDF/HTML report"),
        ("R", "Brief   ", "daily morning summary"),
        ("B", "Browse  ", "explore markets by city"),
        ("S", "Settings", "view & edit thresholds"),
        ("?", "Help    ", "show command guide"),
        ("Q", "Quit    ", ""),
    ]
    key_map = {opt[0].lower(): str(i) for i, opt in enumerate(top_options, 1)}

    while True:
        env_text = f"[{KALSHI_ENV.upper()}]"
        title_visible = f"   Kalshi Weather Prediction Markets   {env_text}"

        # Build status line
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

        try:
            from paper import fear_greed_index

            fg_score, fg_label = fear_greed_index()
            fg_color = (
                red
                if fg_label == "Fearful"
                else yellow
                if fg_label == "Cautious"
                else (lambda s: s)
                if fg_label == "Neutral"
                else green
                if fg_label == "Confident"
                else bold
            )
            status_visible += f"  ·  Mood: {fg_label} ({fg_score})"
            status_colored += (
                f"  {dim('·')}  Mood: {fg_color(f'{fg_label} ({fg_score})')}"
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

        # ── Reminder banners ──────────────────────────────────────────────────
        try:
            import time as _t
            from datetime import date as _date

            _last_run_path = Path(__file__).parent / "data" / ".cron_last_run"
            if not _last_run_path.exists():
                print(
                    yellow(
                        "  ⚠  Loop hasn't run yet — press L to start the auto-run loop.\n"
                    )
                )
            else:
                _hours_since = (_t.time() - _last_run_path.stat().st_mtime) / 3600
                if _hours_since > 5:
                    print(
                        yellow(
                            f"  ⚠  Cron last ran {_hours_since:.0f}h ago — press L to start the loop.\n"
                        )
                    )

            # Unsettled due trades
            from paper import get_open_trades as _got

            _today = _date.today().isoformat()
            _due = [t for t in _got() if (t.get("target_date") or "") <= _today]
            if _due:
                print(
                    yellow(
                        f"  ⚠  {len(_due)} trade(s) due today — go to P → 3 → 1 to settle.\n"
                    )
                )
        except Exception:
            pass

        for i, (key, name, desc) in enumerate(top_options, 1):
            num = cyan(f"  {i:>2}")
            key_str = dim(f"[{key}]")
            if desc:
                print(f"{num} {key_str} {bold(name)}  {dim('·')}  {desc}")
            else:
                print(f"{num} {key_str} {name.strip()}")

        print(
            dim(
                "\n  Tip: press A to scan for trades · run 'py main.py settle' or 'py main.py backtest' when off a game to sync data."
            )
        )
        choice = input(bold(f"\n  Choose (1–{len(top_options)} or letter): ")).strip()
        if not choice.isdigit():
            choice = key_map.get(choice.lower(), choice)
        if not choice.isdigit() or not (1 <= int(choice) <= len(top_options)):
            print(red("  Invalid choice."))
            continue

        idx = int(choice) - 1
        key, _name, _desc = top_options[idx]
        name_stripped = _name.strip()

        if name_stripped == "Quit":
            print(dim("Goodbye."))
            break

        elif name_stripped == "Analyze":
            cmd_analyze(client)

        elif name_stripped == "Today":
            cmd_today(client)

        elif name_stripped == "Loop":
            print(bold("\n  ── Run Cron ──\n"))
            print(dim("  Running a cron cycle now (uses cached data if fresh)…\n"))
            try:
                cmd_cron._called_from_loop = True  # type: ignore[attr-defined]
                cmd_cron(client)
            except Exception as exc:
                print(red(f"  Cron error: {exc}"))
            finally:
                cmd_cron._called_from_loop = False  # type: ignore[attr-defined]
            print(
                dim(
                    "\n  Tip: run  py main.py loop  in a separate terminal to auto-run every 4h."
                )
            )

        elif name_stripped == "Watch":
            _menu_watch(client)

        elif name_stripped == "Paper":
            # ── Paper submenu ─────────────────────────────────────────────────
            print(bold("\n  ── Paper Trading ──\n"))
            print(
                f"  {cyan('1')}  {bold('Results    ')}  {dim('·')}  balance, open positions, P&L"
            )
            print(
                f"  {cyan('2')}  {bold('Buy        ')}  {dim('·')}  place a paper trade"
            )
            print(
                f"  {cyan('3')}  {bold('Settle     ')}  {dim('·')}  settle an open trade"
            )
            print(
                f"  {cyan('4')}  {bold('Exit signals')} {dim('·')}  check if model has flipped"
            )
            print(
                f"  {cyan('5')}  {bold('Monte Carlo')}  {dim('·')}  simulate outcomes"
            )
            print(
                f"  {cyan('6')}  {bold('Alerts     ')}  {dim('·')}  price alert manager"
            )
            print(
                f"  {cyan('7')}  {bold('Graduation ')}  {dim('·')}  am I ready to go live?"
            )
            print(
                f"  {cyan('8')}  {bold('Journal    ')}  {dim('·')}  view trade thesis notes"
            )
            print(dim("  Enter/Q  Back"))
            sub = input(dim("\n  Choose (1–8): ")).strip()

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
                        # Check position limits before submenu buy
                        if raw_qty.isdigit() and int(raw_qty) > 0:
                            try:
                                from paper import check_position_limits as _cpl_sub

                                _limit_sub = _cpl_sub(ticker, int(raw_qty), price)
                                if not _limit_sub.get("allowed", True):
                                    print(
                                        red(
                                            f"  Position limit check failed: {_limit_sub.get('reason', 'limit exceeded')}"
                                        )
                                    )
                                    break
                            except Exception:
                                pass

                        # Large bet confirmation for the submenu buy path
                        if raw_qty.isdigit() and int(raw_qty) > 0:
                            from paper import get_balance as _gb_sub

                            _qty_sub = int(raw_qty)
                            _cost_sub = _qty_sub * price
                            _bal_sub = _gb_sub()
                            if _cost_sub > _bal_sub * 0.03:
                                _pct_sub = _cost_sub / _bal_sub * 100
                                _confirm_sub = (
                                    input(
                                        yellow(
                                            f"  Heads up: this bet is ${_cost_sub:.2f} ({_pct_sub:.1f}% of your ${_bal_sub:.2f} balance). "
                                            f"Continue? (y/N): "
                                        )
                                    )
                                    .strip()
                                    .lower()
                                )
                                if _confirm_sub != "y":
                                    print(dim("  Cancelled."))
                                    break
                        cmd_paper(
                            ["buy", ticker, side, f"{price:.3f}"] + qty_arg, client
                        )
                    break
            elif sub == "3":
                # ── Settle submenu ────────────────────────────────────────────
                print(bold("\n  ── Settle Trades ──\n"))
                print(
                    f"  {cyan('1')}  {bold('Auto-settle ')}  {dim('·')}  check Kalshi now and settle all due trades"
                )
                print(
                    f"  {cyan('2')}  {bold('Manual      ')}  {dim('·')}  pick a trade and enter outcome yourself"
                )
                print(dim("  Enter/Q  Back"))
                settle_sub = input(dim("\n  Choose (1–2): ")).strip()
                if settle_sub == "1":
                    from paper import auto_settle_paper_trades

                    print(dim("  Checking Kalshi for finalized markets…"))
                    sync_outcomes(client)
                    n = auto_settle_paper_trades(client)
                    if n:
                        print(green(f"  Settled {n} trade(s) automatically."))
                    else:
                        print(
                            dim(
                                "  No markets finalized yet — try again later or use Manual."
                            )
                        )
                elif settle_sub == "2":
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
            elif sub == "5":
                cmd_montecarlo(client)
            elif sub == "6":
                _cmd_alerts()
            elif sub == "7":
                from paper import graduation_check

                grad = graduation_check()
                if grad:
                    print(
                        bold(
                            f"\n  {green('GRADUATION CHECK PASSED')} — Ready for live trading!"
                        )
                    )
                    print(
                        green(
                            f"  {grad['settled']} trades  |  Win rate: {grad['win_rate']:.0%}"
                            f"  |  P&L: +${grad['total_pnl']:.2f}"
                        )
                    )
                else:
                    print(
                        yellow(
                            "  Not yet — need 20+ settled trades with >55% win rate and positive P&L."
                        )
                    )
            elif sub == "8":
                cmd_journal()

        elif name_stripped == "Backtest":
            cmd_backtest(client, [])

        elif name_stripped == "Validate":
            cmd_walkforward(client)

        elif name_stripped == "Report":
            cmd_report()

        elif name_stripped == "Brief":
            cmd_brief(client)

        elif name_stripped == "Browse":
            cmd_browse(client)

        elif name_stripped == "Settings":
            cmd_settings(client)

        elif name_stripped == "Help":
            cmd_help()

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
        pct = i / n if n > 0 else 0
        filled = int(pct * 20)
        bar = "█" * filled + "░" * (20 - filled)
        print(f"\r  [{bar}] {pct:.0%}  ({i}/{n})", end="", flush=True)

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

    # ── Benchmark Comparison ─────────────────────────────────────────────────
    bench_yes = summary.get("bench_yes_pnl", 0.0)
    bench_mkt = summary.get("bench_market_pnl", 0.0)
    bench_rand = summary.get("bench_random_pnl", 0.0)

    def _wr_from_rows(rows_list: list[dict], side_key: str) -> str:
        if not rows_list:
            return "—"
        wins = sum(1 for r in rows_list if r.get(side_key + "_won", False))
        return f"{wins / len(rows_list):.0%}"

    # Compute benchmark win rates
    def _bench_wr(rows_list: list[dict], bench: str) -> str:
        if not rows_list:
            return "—"
        if bench == "yes":
            wins = sum(1 for r in rows_list if r.get("actual") == 1)
        elif bench == "market":
            wins = sum(
                1
                for r in rows_list
                if (r.get("market_prob", 0.5) > 0.5 and r.get("actual") == 1)
                or (r.get("market_prob", 0.5) <= 0.5 and r.get("actual") == 0)
            )
        else:
            import random as _rand

            rng = _rand.Random(42)
            wins = sum(
                1
                for r in rows_list
                if (rng.random() > 0.5 and r.get("actual") == 1)
                or (rng.random() <= 0.5 and r.get("actual") == 0)
            )
        return f"{wins / len(rows_list):.0%}"

    our_wr_str = f"{win_rate:.0%}" if win_rate else "—"
    bench_rows_table = [
        [
            "Our model",
            (green(f"+${pnl:.2f}") if pnl >= 0 else red(f"-${abs(pnl):.2f}")),
            our_wr_str,
        ],
        [
            "Always YES",
            (
                green(f"+${bench_yes:.2f}")
                if bench_yes >= 0
                else red(f"-${abs(bench_yes):.2f}")
            ),
            _bench_wr(rows, "yes"),
        ],
        [
            "Follow market",
            (
                green(f"+${bench_mkt:.2f}")
                if bench_mkt >= 0
                else red(f"-${abs(bench_mkt):.2f}")
            ),
            _bench_wr(rows, "market"),
        ],
        [
            "Random",
            (
                green(f"+${bench_rand:.2f}")
                if bench_rand >= 0
                else red(f"-${abs(bench_rand):.2f}")
            ),
            _bench_wr(rows, "random"),
        ],
    ]
    print(bold("\n  ── Benchmark Comparison ──"))
    print(
        tabulate(
            bench_rows_table,
            headers=["Strategy", "P&L", "Win%"],
            tablefmt="rounded_outline",
        )
    )

    # ── Breakdown by condition type ──────────────────────────────────────────
    import re as _re
    from collections import defaultdict

    def _ticker_type(ticker: str) -> str:
        t = ticker.upper()
        if "RAIN" in t or "SNOW" in t or "PRECIP" in t:
            return "precip"
        m = _re.search(r"-([TB])\d", t)
        if m:
            return {"T": "above/below", "B": "between"}.get(m.group(1), "unknown")
        if "HIGH" in t:
            return "above"
        if "LOW" in t:
            return "below"
        return "unknown"

    by_type: dict = defaultdict(list)
    for r in rows:
        ct = _ticker_type(r.get("ticker", ""))
        by_type[ct].append(r)
    if by_type:
        print(bold("\n  ── Breakdown by condition type ──"))
        ctype_rows = []
        for ct, ct_rows in sorted(by_type.items()):
            wins = sum(1 for r in ct_rows if r.get("won"))
            brier_avg = sum(r["brier_sq"] for r in ct_rows) / len(ct_rows)
            win_pct = wins / len(ct_rows) if ct_rows else 0
            ctype_rows.append([ct, len(ct_rows), f"{win_pct:.0%}", f"{brier_avg:.3f}"])
        print(
            tabulate(
                ctype_rows,
                headers=["Type", "Trades", "Win%", "Brier"],
                tablefmt="rounded_outline",
            )
        )

    # ── Breakdown by city (when no city filter applied) ────────────��──────────
    if not city_filter:
        by_city_bt: dict = defaultdict(list)
        for r in rows:
            city_key = r.get("city") or "unknown"
            by_city_bt[city_key].append(r)
        if by_city_bt:
            print(bold("\n  ── Breakdown by city ──"))
            city_bt_rows = []
            for city_key, city_rows in sorted(by_city_bt.items()):
                wins = sum(1 for r in city_rows if r.get("won"))
                win_pct = wins / len(city_rows) if city_rows else 0
                total_pnl_city = sum(r.get("pnl", 0.0) or 0.0 for r in city_rows)
                pnl_s = (
                    green(f"+${total_pnl_city:.2f}")
                    if total_pnl_city >= 0
                    else red(f"-${abs(total_pnl_city):.2f}")
                )
                city_bt_rows.append([city_key, len(city_rows), f"{win_pct:.0%}", pnl_s])
            print(
                tabulate(
                    city_bt_rows,
                    headers=["City", "Trades", "Win%", "P&L"],
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

        # ASCII balance history chart
        try:
            from paper import get_balance_history as _gbh

            history = _gbh()
            if len(history) >= 3:
                balances = [h["balance"] for h in history]
                print(_ascii_chart(balances, width=52, height=6, label="Balance"))
        except Exception:
            pass
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
                    (t.get("thesis") or "")[:30],
                ]
                for t in open_
            ]
            print(
                tabulate(
                    rows,
                    headers=[
                        "#",
                        "Ticker",
                        "Side",
                        "Qty",
                        "Entry",
                        "Cost",
                        "Date",
                        "Thesis",
                    ],
                    tablefmt="rounded_outline",
                )
            )

        if not all_:
            print(
                dim(
                    "\n  No trades yet.  Try: py main.py paper buy <ticker> yes 10 0.45"
                )
            )

        # ── Factor exposure, expiry clustering, unrealized P&L ───────────────
        if open_ and client:
            try:
                from paper import (
                    get_expiry_date_clustering,
                    get_factor_exposure,
                    get_unrealized_pnl_paper,
                )

                factor_exp = get_factor_exposure()
                if factor_exp:
                    print(bold("\n  Factor exposure:"))
                    fe_rows = []
                    for factor, val in sorted(factor_exp.items()):
                        val_s = (
                            green(f"${val:.2f}")
                            if val >= 0
                            else red(f"-${abs(val):.2f}")
                        )
                        fe_rows.append([factor, val_s])
                    print(
                        tabulate(
                            fe_rows,
                            headers=["Factor", "Exposure"],
                            tablefmt="rounded_outline",
                        )
                    )

                clustering = get_expiry_date_clustering()
                if clustering:
                    print(bold("\n  Expiry date clustering:"))
                    cl_rows = []
                    for item in clustering:
                        cl_rows.append(
                            [
                                item.get("date", "?"),
                                item.get("count", 0),
                                f"${item.get('total_cost', 0):.2f}",
                            ]
                        )
                    print(
                        tabulate(
                            cl_rows,
                            headers=["Expiry date", "Positions", "At risk"],
                            tablefmt="rounded_outline",
                        )
                    )

                upnl = get_unrealized_pnl_paper(client)
                total_upnl = upnl.get("total_unrealized_pnl", 0.0)
                upnl_s = (
                    green(f"+${total_upnl:.2f}")
                    if total_upnl >= 0
                    else red(f"-${abs(total_upnl):.2f}")
                )
                print(f"\n  Unrealized P&L (mark-to-market): {bold(upnl_s)}")
                by_trade = upnl.get("by_trade", [])
                if by_trade:
                    upnl_rows = []
                    for entry in by_trade:
                        pnl_v = entry.get("unrealized_pnl", 0.0)
                        pnl_s = (
                            green(f"+${pnl_v:.2f}")
                            if pnl_v >= 0
                            else red(f"-${abs(pnl_v):.2f}")
                        )
                        upnl_rows.append(
                            [
                                entry.get("trade_id", "?"),
                                entry.get("ticker", "?"),
                                pnl_s,
                            ]
                        )
                    print(
                        tabulate(
                            upnl_rows,
                            headers=["#", "Ticker", "Unrealized P&L"],
                            tablefmt="rounded_outline",
                        )
                    )
            except Exception:
                pass

        # ── Graduation check ─────────────────────────────────────────────────
        from paper import graduation_check as _grad_check

        grad = _grad_check()
        if grad:
            print(
                bold(f"\n  {green('GRADUATION CHECK PASSED')} — Consider going live!")
            )
            print(
                green(
                    f"  {grad['settled']} trades  |  Win rate: {grad['win_rate']:.0%}  "
                    f"|  Total P&L: +${grad['total_pnl']:.2f}"
                )
            )


# ── Monte Carlo simulation ────────────────────────────────────────────────────


def cmd_montecarlo(client: KalshiClient) -> None:  # noqa: ARG001
    """Run 1000 Monte Carlo simulations on the current open paper positions."""
    from monte_carlo import simulate_portfolio
    from paper import get_open_trades

    open_trades = get_open_trades()
    if not open_trades:
        print(dim("  No open paper trades to simulate."))
        return

    _header("Monte Carlo Portfolio Simulation")
    print(
        dim(f"  Simulating 1000 outcomes for {len(open_trades)} open position(s)...\n")
    )

    result = simulate_portfolio(open_trades, n_simulations=1000)

    med = result["median_pnl"]
    p10 = result["p10_pnl"]
    p90 = result["p90_pnl"]
    pp = result["prob_positive"]
    pr = result["prob_ruin"]
    bal = result["current_balance"]

    med_s = green(f"+${med:.2f}") if med >= 0 else red(f"-${abs(med):.2f}")
    p10_s = red(f"-${abs(p10):.2f}") if p10 < 0 else green(f"+${p10:.2f}")
    p90_s = green(f"+${p90:.2f}") if p90 >= 0 else red(f"-${abs(p90):.2f}")

    print(f"  Balance:    ${bal:.2f}")
    print(
        f"  Best case:  {p90_s}  |  Median: {med_s}  |  Worst case: {p10_s}  |  Ruin risk: {pr:.0%}"
    )
    print(f"  Prob of profit: {pp:.0%}")

    # ASCII histogram — built from the same 1000-run distribution already computed
    sim_pnls2 = result["pnl_distribution"]  # sorted list of 1000 outcomes
    n_sims = result["n_simulations"]

    min_pnl = sim_pnls2[0]
    max_pnl = sim_pnls2[-1]
    span = max_pnl - min_pnl if max_pnl != min_pnl else 1.0
    n_bins = 10
    bins = [0] * n_bins
    for pnl in sim_pnls2:
        idx = min(n_bins - 1, int((pnl - min_pnl) / span * n_bins))
        bins[idx] += 1

    print(bold(f"\n  Outcome distribution ({n_sims} simulations):"))
    max_bin = max(bins) if bins else 1
    for i, count in enumerate(bins):
        lo = min_pnl + (i / n_bins) * span
        hi = min_pnl + ((i + 1) / n_bins) * span
        bar_len = int(count / max_bin * 30)
        bar = "█" * bar_len
        label = f"${lo:+.1f}–${hi:+.1f}"
        color = green if lo >= 0 else red
        print(f"  {label:>16}  {color(bar)}  {count}")
    print()


# ── Web dashboard ─────────────────────────────────────────────────────────────


def cmd_web(client: KalshiClient) -> None:
    """Start local web dashboard on http://localhost:5000"""
    try:
        import flask  # noqa: F401
    except ImportError:
        print("Install Flask first: pip install flask")
        return
    from web_app import start_web

    start_web(client, port=5000, open_browser=True)


# ── Simulation sandbox ────────────────────────────────────────────────────────


def cmd_simulate(client: KalshiClient) -> None:
    """Interactive replay of historical markets — test your instincts."""
    _header("Simulation Sandbox")
    print(dim("  Loading last 20 finalized weather markets...\n"))

    try:
        markets = client.get_markets(status="finalized", limit=50)
    except Exception as e:
        print(red(f"  Could not load markets: {e}"))
        return

    from weather_markets import (
        enrich_with_forecast,
        is_weather_market,
        parse_market_price,
    )

    markets = [m for m in markets if is_weather_market(m)]
    weather = [
        m for m in markets if is_weather_market(m) and m.get("result") in ("yes", "no")
    ][:20]
    if not weather:
        print(yellow("  No finalized weather markets found."))
        return

    user_pnl = 0.0
    model_pnl = 0.0
    user_wins = 0
    model_wins = 0
    total = 0

    from utils import KALSHI_FEE_RATE as _fee

    print(
        dim(
            "  For each market, decide YES / NO / Skip. The outcome will be revealed.\n"
        )
    )
    try:
        for m in weather:
            ticker = m.get("ticker", "")
            title = (m.get("title") or ticker)[:60]
            result = m.get("result", "")
            prices = parse_market_price(m)
            yes_price = prices["mid"] if prices["mid"] > 0 else 0.5
            close_date = (m.get("close_time") or "")[:10]

            print(f"\n  {bold(ticker)}")
            print(f"  {title}")
            print(f"  Closes: {close_date}   YES price: {yes_price:.2%}")
            print(dim("  (y=YES  n=NO  s=skip)"))

            while True:
                choice = input("  Your bet: ").strip().lower()
                if choice in ("y", "n", "s"):
                    break

            if choice == "s":
                print(dim(f"  Skipped. Outcome was: {result.upper()}"))
                continue

            # Get amount
            while True:
                amt_raw = input("  Amount $: ").strip()
                try:
                    amt = float(amt_raw)
                    if amt > 0:
                        break
                except ValueError:
                    pass
                print(red("  Enter a positive dollar amount."))

            total += 1
            actual_yes = result == "yes"
            user_side = "yes" if choice == "y" else "no"
            user_entry = yes_price if user_side == "yes" else 1 - yes_price
            if user_entry <= 0:
                user_entry = 0.5
            user_won = (user_side == "yes" and actual_yes) or (
                user_side == "no" and not actual_yes
            )
            if user_won:
                winnings = (1 - user_entry) * (1 - _fee)
                pnl = amt / user_entry * winnings
                user_pnl += pnl
                user_wins += 1
                print(green(f"  CORRECT! Outcome: {result.upper()}  P&L: +${pnl:.2f}"))
            else:
                user_pnl -= amt
                print(red(f"  WRONG.  Outcome: {result.upper()}  P&L: -${amt:.2f}"))

            # Show what model would have done
            try:
                enriched = enrich_with_forecast(m)
                from weather_markets import analyze_trade

                analysis = analyze_trade(enriched)
                if analysis:
                    model_side = analysis["recommended_side"]
                    model_prob = analysis["forecast_prob"]
                    model_entry = yes_price if model_side == "yes" else 1 - yes_price
                    if model_entry <= 0:
                        model_entry = 0.5
                    model_won = (model_side == "yes" and actual_yes) or (
                        model_side == "no" and not actual_yes
                    )
                    model_stake = 10.0
                    if model_won:
                        mw = (1 - model_entry) * (1 - _fee)
                        mpnl = model_stake / model_entry * mw
                        model_pnl += mpnl
                        model_wins += 1
                        print(
                            dim(
                                f"  Model: BUY {model_side.upper()} ({model_prob:.0%})  → RIGHT (+${mpnl:.2f})"
                            )
                        )
                    else:
                        model_pnl -= model_stake
                        print(
                            dim(
                                f"  Model: BUY {model_side.upper()} ({model_prob:.0%})  → WRONG (-${model_stake:.2f})"
                            )
                        )
            except Exception:
                pass

    except (KeyboardInterrupt, EOFError):
        print()

    # Final score
    if total == 0:
        print(dim("\n  No markets played."))
        return

    print(bold(f"\n  ── Final Score ({total} markets) ──"))
    pnl_s = (
        green(f"+${user_pnl:.2f}") if user_pnl >= 0 else red(f"-${abs(user_pnl):.2f}")
    )
    mpnl_s = (
        green(f"+${model_pnl:.2f}")
        if model_pnl >= 0
        else red(f"-${abs(model_pnl):.2f}")
    )
    print(f"  You:   {pnl_s}  Win rate: {user_wins / total:.0%}")
    print(f"  Model: {mpnl_s}  Win rate: {model_wins / total:.0%}  (on $10/trade)")


# ── Weekly summary ────────────────────────────────────────────────────────────


def cmd_weekly_summary() -> None:
    """
    Generate a plain-text weekly recap saved to data/weekly_summary_{date}.txt.
    Covers: trades made this week, settled this week, P&L, Brier score trend,
    best/worst trades, which model sources were most accurate.
    Also prints to terminal.
    """
    from datetime import timedelta

    from paper import get_all_trades, get_balance
    from tracker import brier_score, get_calibration_trend

    now = datetime.now(UTC)
    week_start = now - timedelta(days=7)
    week_start_str = week_start.strftime("%Y-%m-%d")

    all_trades = get_all_trades()
    entered_this_week = [
        t for t in all_trades if (t.get("entered_at") or "") >= week_start_str
    ]
    settled_this_week = [
        t
        for t in all_trades
        if t.get("settled") and (t.get("entered_at") or "") >= week_start_str
    ]

    week_pnl = sum(t.get("pnl") or 0.0 for t in settled_this_week)
    week_wins = sum(1 for t in settled_this_week if (t.get("pnl") or 0) > 0)

    bs = brier_score()
    trend = get_calibration_trend(weeks=4)
    rel = get_source_reliability()
    balance = get_balance()

    # Best and worst settled trades this week
    best = (
        max(settled_this_week, key=lambda t: t.get("pnl") or 0.0)
        if settled_this_week
        else None
    )
    worst = (
        min(settled_this_week, key=lambda t: t.get("pnl") or 0.0)
        if settled_this_week
        else None
    )

    lines = [
        f"Weekly Summary — {now.strftime('%Y-%m-%d')} (last 7 days)",
        "=" * 55,
        "",
        f"Paper balance:  ${balance:.2f}",
        f"Trades entered: {len(entered_this_week)}",
        f"Trades settled: {len(settled_this_week)}",
        f"Week P&L:       {'+' if week_pnl >= 0 else ''}${week_pnl:.2f}",
        f"Week win rate:  {week_wins / len(settled_this_week):.0%}"
        if settled_this_week
        else "Week win rate:  —",
        f"All-time Brier: {bs:.4f}" if bs else "All-time Brier: —",
        "",
    ]

    if trend:
        lines.append("Brier trend (recent weeks):")
        for t in trend[-4:]:
            lines.append(f"  {t['week']}  {t['brier']:.4f}  (n={t['n']})")
        lines.append("")

    if best:
        lines.append(
            f"Best trade:  #{best['id']} {best['ticker']} P&L +${best.get('pnl', 0):.2f}"
        )
    if worst:
        lines.append(
            f"Worst trade: #{worst['id']} {worst['ticker']} P&L ${worst.get('pnl', 0):.2f}"
        )
    if best or worst:
        lines.append("")

    if rel:
        lines.append("Source reliability (last 30 days):")
        for city_name in sorted(rel.keys()):
            for src in ["ensemble", "nws", "climatology"]:
                stats = rel[city_name].get(src)
                if stats and stats["total"] >= 3:
                    lines.append(
                        f"  {city_name:<10} {src:<12} {stats['rate']:.0%} ({stats['total']} days)"
                    )
        lines.append("")

    lines.append("Note: This is an informational summary. Not financial advice.")

    summary_text = "\n".join(lines)

    # Save to file
    out_dir = Path(__file__).parent / "data"
    out_dir.mkdir(exist_ok=True)
    fname = f"weekly_summary_{now.strftime('%Y-%m-%d')}.txt"
    out_path = out_dir / fname
    try:
        out_path.write_text(summary_text, encoding="utf-8")
        print(green(f"  Saved → {out_path}"))
    except Exception as e:
        print(yellow(f"  Could not save file: {e}"))

    # Print to terminal
    print()
    for line in lines:
        print(f"  {line}")


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
        f'schtasks /Create /F /SC HOURLY /MO 3 /TN "{task_name}" '
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
        print(green(f"\nTask '{task_name}' registered — runs every 3 hours."))
        print(dim("To remove: schtasks /Delete /TN KalshiWeatherScan /F"))
    else:
        print(red(f"Failed: {result.stderr.strip() or result.stdout.strip()}"))
        print(dim("Try running this terminal as Administrator."))

    # ── Daily morning email ──────────────────────────────────────────────────
    email_task = "KalshiWeatherEmail"
    email_cmd = f'"{py_exe}" "{script_path}" brief --email'
    email_create = (
        f'schtasks /Create /F /SC DAILY /ST 07:00 /TN "{email_task}" '
        f'/TR "{email_cmd}" /RL HIGHEST'
    )

    print(bold(f"\nRegistering daily email task: {email_task}"))
    print(dim("  Sends a morning briefing email at 07:00 (requires SMTP_* env vars)."))
    confirm_email = input("  Register now? (Y/n): ").strip().lower()
    if confirm_email != "n":
        result_email = subprocess.run(
            email_create, shell=True, capture_output=True, text=True
        )
        if result_email.returncode == 0:
            print(green(f"\nTask '{email_task}' registered — emails at 7am daily."))
            print(dim("To remove: schtasks /Delete /TN KalshiWeatherEmail /F"))
        else:
            print(
                red(
                    f"Failed: {result_email.stderr.strip() or result_email.stdout.strip()}"
                )
            )

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


def cmd_schedule_cycles() -> None:
    """
    Print Windows Task Scheduler commands to run the cron scan at NWP model
    cycle availability times: 02:15, 08:15, 14:15, 20:15 UTC.

    NWP models initialize at 00/06/12/18 UTC; data becomes available ~2h later.
    Scanning immediately after availability captures maximum market inefficiency.

    Run each printed command once in an elevated PowerShell to register the tasks.
    """
    python_exe = sys.executable
    script_path = Path(__file__).resolve()

    utc_times = [2, 8, 14, 20]
    try:
        local_tz = datetime.now().astimezone().tzinfo
    except Exception:
        local_tz = UTC

    print(bold("\nNWP Cycle-Aligned Scan Schedule"))
    print(dim("Run these commands once in an elevated PowerShell:\n"))

    for utc_hour in utc_times:
        utc_dt = datetime.now(UTC).replace(
            hour=utc_hour, minute=15, second=0, microsecond=0
        )
        local_dt = utc_dt.astimezone(local_tz)
        local_time_str = local_dt.strftime("%H:%M")
        task_name = f"KalshiCron_{utc_hour:02d}UTC"
        cmd = (
            f'schtasks /Create /TN "{task_name}" /TR '
            f'"{python_exe} {script_path} cron" '
            f"/SC DAILY /ST {local_time_str} /F /RL HIGHEST"
        )
        print(f"# {utc_hour:02d}:15 UTC ({local_time_str} local)")
        print(cmd)
        print()

    print(dim("To verify tasks were created:"))
    print("schtasks /Query /FO LIST /V | findstr Kalshi")


def cmd_replay(trade_id: str) -> None:
    """
    Replay a single trade decision from stored inputs.
    Shows: inputs at time of trade, edge calculation, validation result, execution details.
    Usage: py main.py replay <trade_id>
    """
    from paper import load_paper_trades

    _log.info("cmd_replay: replaying trade %s", trade_id)

    trades = load_paper_trades()
    trade = next((t for t in trades if str(t.get("id")) == str(trade_id)), None)

    if trade is None:
        try:
            from execution_log import get_order_by_id

            trade = get_order_by_id(trade_id)
        except Exception:
            pass

    if trade is None:
        print(red(f"  Trade {trade_id!r} not found in paper trades or execution log."))
        return

    print(bold(f"\n  Trade Replay — ID {trade_id}"))
    print("  " + "─" * 48)

    for key, value in trade.items():
        print(f"  {dim(key + ':')} {value}")

    print(
        "\n  " + dim("Note: Re-running live edge calculation is not possible without")
    )
    print("  " + dim("historical forecast data. Above shows stored decision inputs."))
    print()


def cmd_shadow_compare(client: KalshiClient) -> None:
    """
    Shadow mode: show what the bot would trade right now without executing.
    Does NOT execute any trades. Pure read-only analysis.
    """
    print(bold("\n  Shadow Mode — Would-Trade Analysis"))
    print("  " + dim("Shows what the bot would trade now vs last actual cron run"))
    print("  " + "─" * 48)

    markets = get_weather_markets(client)
    signals = []
    for m in markets:
        try:
            enriched = enrich_with_forecast(m)
            analysis = analyze_trade(enriched)
            if analysis:
                signals.append(
                    {
                        "ticker": m.get("ticker", ""),
                        "edge": analysis.get("net_edge", analysis.get("edge", 0)),
                        "side": analysis.get("recommended_side", "yes"),
                        "kelly_fraction": analysis.get(
                            "ci_adjusted_kelly",
                            analysis.get(
                                "fee_adjusted_kelly", analysis.get("kelly", 0)
                            ),
                        ),
                    }
                )
        except Exception:
            continue

    if not signals:
        print(dim("  No signals found."))
        return

    would_trade = [
        sig
        for sig in signals
        if sig.get("edge", 0) >= float(os.getenv("PAPER_MIN_EDGE", "0.05"))
        and sig.get("kelly_fraction", 0) >= 0.002
    ]

    if not would_trade:
        print(dim(f"  {len(signals)} signals scanned, none meet edge threshold."))
        return

    print(f"\n  {bold(str(len(would_trade)))} trade(s) would be placed:\n")
    for sig in would_trade:
        ticker = sig.get("ticker", "?")
        edge = sig.get("edge", 0)
        side = sig.get("side", "?")
        kelly = sig.get("kelly_fraction", 0)
        print(
            f"    {green(ticker)}  {side.upper()}  edge={edge:.1%}  kelly={kelly:.3f}"
        )

    print()


def cmd_ab_summary() -> None:
    """Show A/B test results for all active tests."""
    from ab_test import list_all_summaries

    summaries = list_all_summaries()
    if not summaries:
        print(
            dim(
                "  No A/B tests found. Tests are created programmatically via ABTest()."
            )
        )
        return
    print(bold("\n  A/B Test Results"))
    print("  " + "─" * 48)
    for test_name, state in summaries.items():
        print(f"\n  {bold(test_name)}")
        for variant, stats in state.items():
            trades = stats.get("trades", 0)
            win_rate = stats.get("wins", 0) / max(trades, 1)
            avg_edge = stats.get("total_edge", 0.0) / max(trades, 1)
            disabled = " [DISABLED]" if stats.get("disabled") else ""
            print(
                f"    {variant}{dim(disabled)}: {trades} trades, "
                f"{win_rate:.0%} win rate, {avg_edge:.3f} avg edge"
            )
    print()


def cmd_sweep() -> None:
    """Run a parameter sweep against historical paper trades."""
    from param_sweep import run_sweep

    print(bold("\n  Parameter Sweep"))
    print("  " + dim("Testing threshold ranges against historical settled trades"))
    run_sweep()


# ── Router ────────────────────────────────────────────────────────────────────


def main():
    args = sys.argv[1:]

    # Skip env check for setup command so new users can run it without creds
    if args and args[0].lower() == "setup":
        cmd_setup()
        return

    # calibrate only needs the local DB — no API credentials required
    if args and args[0].lower() == "calibrate":
        cmd_calibrate()
        return

    # schedule-cycles only prints commands — no API credentials required
    if args and args[0].lower() == "schedule-cycles":
        cmd_schedule_cycles()
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
        logging.disable(logging.DEBUG)

    init_db()
    cleanup_data_dir()

    # No arguments → interactive menu
    if not args:
        client = build_client()
        auto_backup()
        # Show onboarding wizard on first run
        if _needs_onboarding():
            cmd_onboard()
        cmd_menu(client)
        return

    cmd = args[0].lower()
    verbose = "--verbose" in args or "-v" in args
    client = build_client()
    auto_backup()

    if cmd == "menu":
        cmd_menu(client)
    elif cmd in ("today", "t"):
        cmd_today(client)
    elif cmd == "brief":
        cmd_brief(client, send_email="--email" in args)
    elif cmd == "cron":
        _cron_edge = MIN_EDGE
        if "--edge" in args:
            try:
                _cron_edge = float(args[args.index("--edge") + 1]) / 100
            except (IndexError, ValueError):
                pass
        cmd_cron(client, min_edge=_cron_edge)
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
        cmd_analyze(client, min_edge=min_edge, live="--live" in args)
    elif cmd == "watch":
        min_edge = 0.10
        if "--edge" in args:
            try:
                min_edge = float(args[args.index("--edge") + 1]) / 100
            except (IndexError, ValueError):
                pass
        cmd_watch(
            client,
            auto_trade="--auto" in args,
            min_edge=min_edge,
            live="--live" in args,
        )
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
    elif cmd == "settle":
        cmd_settle(client)
    elif cmd in ("watch-settle", "watch_settle"):
        cmd_watch_settle(client, args[1:])
    elif cmd == "loop":
        cmd_loop(client, args[1:])
    elif cmd == "paper":
        cmd_paper(args[1:], client)
    elif cmd == "backtest":
        cmd_backtest(client, args[1:])
    elif cmd == "dashboard":
        cmd_dashboard(client)
    elif cmd == "export":
        cmd_export()
    elif cmd in ("montecarlo", "simulate-portfolio", "n"):
        cmd_montecarlo(client)
    elif cmd == "web":
        cmd_web(client)
    elif cmd == "restore":
        from cloud_backup import restore_data as _restore

        _restore()
    elif cmd in ("simulate", "sandbox", "x"):
        cmd_simulate(client)
    elif cmd in ("weekly", "y"):
        cmd_weekly_summary()
    elif cmd == "journal":
        cmd_journal()
    elif cmd in ("walkforward", "wf"):
        cmd_walkforward(client)
    elif cmd in ("walk-forward", "wfbt"):
        cmd_walk_forward()
    elif cmd == "report":
        cmd_report()
    elif cmd == "kill":
        cmd_kill()
    elif cmd == "resume":
        cmd_resume()
    elif cmd == "features":
        cmd_features()
    elif cmd == "override":
        action = sys.argv[2] if len(sys.argv) > 2 else "status"
        mins = int(sys.argv[3]) if len(sys.argv) > 3 else 60
        cmd_override(action, mins)
    elif cmd == "admin":
        action = sys.argv[2] if len(sys.argv) > 2 else ""
        reason = (
            " ".join(sys.argv[3:]) if len(sys.argv) > 3 else "manual admin override"
        )
        cmd_admin(action, reason)
    elif cmd == "replay":
        trade_id = sys.argv[2] if len(sys.argv) > 2 else ""
        if not trade_id:
            print("Usage: py main.py replay <trade_id>")
        else:
            cmd_replay(trade_id)
    elif cmd == "shadow":
        cmd_shadow_compare(client)
    elif cmd == "ab-summary":
        cmd_ab_summary()
    elif cmd == "sweep":
        cmd_sweep()
    elif cmd == "drift":
        cmd_drift()
    elif cmd in ("version-compare", "versions"):
        cmd_version_compare()
    elif cmd in ("pnl-attribution", "pnl"):
        cmd_pnl_attribution()
    elif cmd == "train-bias":
        cmd_train_bias()
    elif cmd in ("retire", "retire-strategies"):
        do_run = "--run" in sys.argv[2:]
        cmd_retire_strategies(run=do_run)
    elif cmd in ("config-check", "config"):
        cmd_config_check()
    elif cmd in ("code-audit", "audit"):
        cmd_code_audit()
    elif cmd in ("settlement-monitor", "settle-monitor"):
        cmd_settlement_monitor(client, args[1:])
    else:
        print(red(f"Unknown command: {cmd}"))
        print(dim("Run  py main.py  for the interactive menu."))


if __name__ == "__main__":
    main()
