"""
Backtesting engine — replays historical Kalshi weather markets using
Open-Meteo archive data to simulate what our model would have predicted.

Usage:
    py main.py backtest [city] [--days 30]

For each finalized weather market:
  1. Fetch historical ensemble archive data (as-of the day the market closed)
  2. Run analyze_trade with that historical data
  3. Compare our predicted probability against the actual settlement
  4. Report Brier score, win rate, and P&L vs buy-and-hold random baseline
"""

from __future__ import annotations

import hashlib
import json
import logging
import random
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

from utils import KALSHI_FEE_RATE, KALSHI_MAKER_FEE_RATE
from weather_markets import CITY_COORDS, KNOWN_WEATHER_SERIES, _parse_city_from_ticker

_log = logging.getLogger(__name__)

ARCHIVE_ENS_BASE = "https://archive-api.open-meteo.com/v1/archive"
_PREV_RUN_MODELS = ["icon_seamless", "gfs_seamless", "ecmwf_aifs025_single"]
DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)
ARCHIVE_CACHE_DIR = DATA_DIR / "archive_cache"
ARCHIVE_CACHE_DIR.mkdir(exist_ok=True)


# ── Archive ensemble fetch ────────────────────────────────────────────────────


def fetch_archive_temps(
    lat: float, lon: float, tz: str, target_date: date, var: str = "max"
) -> list[float]:
    """
    Fetch historical daily high/low temperatures from Open-Meteo archive.
    Returns a list of values (simulated 'ensemble' from historical spread).
    Results are cached to disk so repeat backtest runs don't re-fetch.
    """
    import random
    import statistics

    cache_key = f"{round(lat, 4)}_{round(lon, 4)}_{target_date.isoformat()}_{var}"
    cache_file = ARCHIVE_CACHE_DIR / f"{cache_key}.json"
    if cache_file.exists():
        try:
            return json.loads(cache_file.read_text())
        except Exception:
            pass

    # Fetch ±5 days around the target to estimate local variability
    start = (target_date - timedelta(days=5)).isoformat()
    end = (target_date + timedelta(days=5)).isoformat()
    daily_var = "temperature_2m_max" if var == "max" else "temperature_2m_min"

    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": start,
        "end_date": end,
        "daily": daily_var,
        "temperature_unit": "fahrenheit",
        "timezone": tz,
    }
    try:
        import time as _time_bt

        resp = None
        for _attempt in range(3):
            resp = requests.get(ARCHIVE_ENS_BASE, params=params, timeout=30)  # type: ignore[arg-type]
            if resp.status_code == 429:
                _time_bt.sleep(2**_attempt)
                continue
            resp.raise_for_status()
            break
        else:
            return []
        if resp is None:
            return []
        daily = resp.json().get("daily", {})
        times = daily.get("time", [])
        vals = daily.get(daily_var, [])
        target_str = target_date.isoformat()

        exact = None
        nearby = []
        nearby_excl = []  # L6-A: surrounding days EXCLUDING the target
        for t, v in zip(times, vals):
            if v is None:
                continue
            if t == target_str:
                exact = v
            else:
                nearby_excl.append(v)
            nearby.append(v)

        if exact is None:
            return []

        # L6-A fix: centre the synthetic ensemble on a *forecast* (mean of
        # surrounding days), NOT on the actual observed temperature.
        # Centering on `exact` made the ensemble "know" the answer — giving
        # an artificially good Brier score in backtest.
        # The nearby-day average is a realistic proxy for a persistence-style
        # model forecast (what you'd have predicted without seeing the outcome).
        forecast_mean = statistics.mean(nearby_excl) if nearby_excl else exact
        sigma = statistics.stdev(nearby_excl) if len(nearby_excl) >= 4 else 3.0
        # B7/B8: use a local Random instance so we don't pollute the global RNG
        # and so the seed is truly deterministic (hash() is process-randomised in 3.3+)
        _rng = random.Random(int(hashlib.md5(target_str.encode()).hexdigest()[:8], 16))
        result = [forecast_mean + _rng.gauss(0, sigma) for _ in range(50)]
        try:
            cache_file.write_text(json.dumps(result))
        except Exception:
            pass
        return result
    except Exception:
        return []


# ── Archive precipitation fetch ──────────────────────────────────────────────


def fetch_archive_precip(
    lat: float, lon: float, tz: str, target_date: date
) -> tuple[float | None, str]:
    """
    Fetch historical daily precipitation (inches) from Open-Meteo archive.
    #72: Returns (value, reason) where reason is one of:
      "value"          — data fetched/cached successfully
      "unsupported_date" — date outside archive range (too recent or too old)
      "api_error"      — network or HTTP error
      "no_data"        — API returned null/empty for this date
    """
    cache_key = f"{round(lat, 4)}_{round(lon, 4)}_{target_date.isoformat()}_precip"
    cache_file = ARCHIVE_CACHE_DIR / f"{cache_key}.json"
    if cache_file.exists():
        try:
            return (json.loads(cache_file.read_text()), "value")
        except Exception:
            pass

    # Dates within last 5 days are typically not in the archive yet
    from datetime import date as _date

    days_old = (_date.today() - target_date).days
    if days_old < 5:
        return (None, "unsupported_date")

    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": target_date.isoformat(),
        "end_date": target_date.isoformat(),
        "daily": "precipitation_sum",
        "precipitation_unit": "inch",
        "timezone": tz,
    }
    try:
        import time as _time_bt2

        resp = None
        for _attempt in range(3):
            resp = requests.get(ARCHIVE_ENS_BASE, params=params, timeout=30)  # type: ignore[arg-type]
            if resp.status_code == 429:
                _time_bt2.sleep(2**_attempt)
                continue
            resp.raise_for_status()
            break
        else:
            return (None, "api_error")
        if resp is None:
            return (None, "api_error")
        daily = resp.json().get("daily", {})
        vals = daily.get("precipitation_sum", [])
        if not vals or vals[0] is None:
            return (None, "no_data")
        result = float(vals[0])
        try:
            cache_file.write_text(json.dumps(result))
        except Exception:
            pass
        return (result, "value")
    except Exception:
        return (None, "api_error")


def fetch_archive_precip_prob(
    lat: float, lon: float, tz: str, target_date: date, window_days: int = 30
) -> float | None:
    """
    Estimate precipitation probability for target_date using the prior
    window_days of archive data (no lookahead — only past dates are used).

    Returns fraction of prior days with measurable precip (>0.01 inch),
    which is a legitimate persistence/climatological forecast proxy.
    Returns None if fewer than 7 prior days of data are available.
    """
    start = target_date - timedelta(days=window_days)
    end = target_date - timedelta(days=1)  # strictly before target

    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "daily": "precipitation_sum",
        "precipitation_unit": "inch",
        "timezone": tz,
    }
    try:
        import time as _time_pp

        resp = None
        for _attempt in range(3):
            resp = requests.get(ARCHIVE_ENS_BASE, params=params, timeout=30)  # type: ignore[arg-type]
            if resp.status_code == 429:
                _time_pp.sleep(2**_attempt)
                continue
            resp.raise_for_status()
            break
        else:
            return None
        if resp is None:
            return None
        vals = resp.json().get("daily", {}).get("precipitation_sum", [])
        valid = [v for v in vals if v is not None]
        if len(valid) < 7:
            return None
        return sum(1 for v in valid if v > 0.01) / len(valid)
    except Exception:
        return None


def fetch_previous_run_ensemble(
    city: str,
    target_date: date,
    days_out: int,
    var: str = "max",
) -> list[float]:
    """Fetch actual model output at forecast time using the Previous Runs API.

    Returns temperatures in °F as a list (one per model). Empty list if unavailable.
    This gives a true point-in-time ensemble unlike the archive ±5-day spread.
    """
    coords = CITY_COORDS.get(city)
    if not coords:
        return []
    lat, lon, tz = coords  # CITY_COORDS values are (lat, lon, tz) tuples — NOT dicts

    daily_var_suffix = "max" if var == "max" else "min"
    daily_vars = [
        f"temperature_2m_{daily_var_suffix}_previous_day{days_out}_{m}"
        for m in _PREV_RUN_MODELS
    ]

    try:
        resp = requests.get(
            "https://previous-runs-api.open-meteo.com/v1/forecast",
            params={
                "latitude": lat,
                "longitude": lon,
                "daily": ",".join(daily_vars),
                "temperature_unit": "fahrenheit",
                "timezone": tz,
                "past_days": max(41, days_out + 2),
                "forecast_days": 0,
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json().get("daily", {})
        times = data.get("time", [])
        target_str = target_date.isoformat()
        if target_str not in times:
            return []
        idx = times.index(target_str)
        temps = []
        for v in daily_vars:
            val_list = data.get(v, [])
            val = val_list[idx] if idx < len(val_list) else None
            if val is not None:
                temps.append(float(val))
        return temps
    except Exception as exc:
        _log.debug(
            "fetch_previous_run_ensemble: %s %s failed: %s", city, target_date, exc
        )
        return []


# ── Backtest runner ───────────────────────────────────────────────────────────


# Derived from weather_markets.KNOWN_WEATHER_SERIES (single source of truth)
# instead of a second hand-typed copy — that copy went stale once already
# (KXLOWLAX -> KXLOWTLAX, confirmed live 2026-07-05) with no test catching it
# until a live audit found LA markets silently missing from every backtest run.
_WEATHER_SERIES = KNOWN_WEATHER_SERIES

# Fail loudly at import time (not a cryptic downstream "0 settled markets"
# silence) if KNOWN_WEATHER_SERIES itself ever drops a city's HIGH or LOW
# ticker again — mirrors settlement_monitor.py's per-city assertion pattern
# for the identical bug class, since aliasing to KNOWN_WEATHER_SERIES above
# only fixed the one already-known LA incident, not future drift for a
# different city (found via a deep code review, 2026-07-08).
for _city in CITY_COORDS:
    for _prefix in ("KXHIGH", "KXLOW"):
        _matches = [
            t
            for t in _WEATHER_SERIES
            if t.startswith(_prefix) and _parse_city_from_ticker(t) == _city
        ]
        assert len(_matches) == 1, (
            f"backtest: expected exactly one {_prefix}* ticker for {_city!r} "
            f"in KNOWN_WEATHER_SERIES, found {_matches!r} — Kalshi may have "
            f"renamed/retired the series again"
        )
del _city, _prefix, _matches


def _fetch_settled_markets(
    client, max_pages: int = 20, min_close_time: str | None = None
) -> list[dict]:
    """
    Fetch settled Kalshi weather markets by iterating known weather series.

    Querying all markets globally (status=settled) returns thousands of
    non-weather markets and buries the weather series beyond the page limit.
    Instead we query each known series directly, exactly as get_weather_markets
    does for live markets.

    max_pages is applied per series to bound total API calls.
    min_close_time (ISO-8601) is passed to the API so only markets settled on
    or after that timestamp are returned.  Without it the API may return markets
    from years ago — which all fall outside the backtest window and score 0.
    """
    seen: set[str] = set()
    markets: list[dict] = []

    for series in _WEATHER_SERIES:
        cursor: str | None = None
        for _ in range(max_pages):
            params: dict = {"series_ticker": series, "status": "settled", "limit": 200}
            if cursor:
                params["cursor"] = cursor
            if min_close_time:
                params["min_close_time"] = min_close_time
            try:
                data = client._get("/markets", params=params, auth=True)
            except Exception:
                break
            page = data.get("markets", [])
            for m in page:
                t = m.get("ticker", "")
                if t and t not in seen:
                    seen.add(t)
                    markets.append(m)
            cursor = data.get("cursor") or data.get("next_cursor")
            if not cursor or not page:
                break

    return markets


def run_backtest(
    client,
    city_filter: str | None = None,
    days_back: int = 90,
    verbose: bool = False,
    holdout_fraction: float = 0.20,
    on_progress=None,
    use_previous_runs: bool = False,
) -> dict:
    """
    Fetch finalized weather markets from Kalshi, then simulate our
    model's prediction for each and score against the actual outcome.

    holdout_fraction: fraction of the window held out as validation (default 20%).

    Returns summary dict: {brier, win_rate, total_pnl, n_markets, rows,
                           val_brier, val_n, val_win_rate}
    """
    from weather_markets import (
        CITY_COORDS,
        _parse_market_condition,
        enrich_with_forecast,
        kelly_fraction,
        parse_market_price,
    )

    cutoff = date.today() - timedelta(days=days_back)
    holdout_days_count = (
        max(1, int(days_back * holdout_fraction)) if holdout_fraction > 0 else 0
    )
    holdout_cutoff = (
        date.today() - timedelta(days=holdout_days_count)
        if holdout_days_count > 0
        else None
    )
    # Pass min_close_time so the API only returns markets settled within the
    # window.  This avoids fetching thousands of old markets that are all
    # outside the window and score zero (root cause: API returns oldest-first
    # when authenticated, so max_pages=20 only surfaces 2022-2024 markets).
    _cutoff_ts = (
        __import__("datetime")
        .datetime(
            cutoff.year,
            cutoff.month,
            cutoff.day,
            tzinfo=__import__("datetime").timezone.utc,
        )
        .isoformat()
    )
    markets = _fetch_settled_markets(client, max_pages=20, min_close_time=_cutoff_ts)

    diag = {
        "n_fetched": len(markets),
        "n_result_ok": 0,
        "n_parsed": 0,
        "n_in_window": 0,
        "n_archive": 0,
    }

    results = []
    _cond_acc: dict[str, list[float]] = {}
    for _prog_i, m in enumerate(markets, 1):
        if on_progress:
            on_progress(_prog_i, len(markets))
        ticker = m.get("ticker", "")
        result = m.get("result", "")
        if result not in ("yes", "no"):
            continue
        diag["n_result_ok"] += 1

        # fetch_forecast=False: backtest scores probability from archive data
        # (fetch_archive_temps/fetch_archive_precip_prob below), never reads
        # _forecast/_forecast_uncertain — the live forecast fetch would just
        # burn ~5s+ per market falling through to Pirate Weather for nothing
        # (Open-Meteo/NBM/weatherapi can't serve months-old historical dates).
        enriched = enrich_with_forecast(m, fetch_forecast=False)
        city = enriched.get("_city")
        tdate = enriched.get("_date")

        # Compute actual days_out for Previous Runs backtest using market open time.
        # Kalshi market dict has open_time (ISO-8601). Using open date as proxy for
        # when the forecast was issued; clamped to [1,5] (API supports up to 5).
        _open_time_str = m.get("open_time", "")
        days_out_bt = 1  # fallback
        if _open_time_str:
            try:
                _open_dt = datetime.fromisoformat(_open_time_str.replace("Z", "+00:00"))
                _open_date = _open_dt.date()
                if tdate and _open_date:
                    days_out_bt = max(1, min(5, (tdate - _open_date).days))
            except Exception:
                pass

        # Backtest uses archive data (fetch_archive_temps / fetch_archive_precip) for
        # probability, NOT the live forecast.  Forecast is None for past dates, so do
        # NOT gate on it here — only require city and tdate.
        if not city or not tdate:
            continue
        diag["n_parsed"] += 1
        if city_filter and city.lower() != city_filter.lower():
            continue
        if tdate < cutoff:
            continue
        diag["n_in_window"] += 1

        coords = CITY_COORDS.get(city)
        if not coords:
            continue
        lat, lon, tz = coords

        condition = _parse_market_condition(enriched)
        if not condition:
            continue

        # ── Precipitation markets ─────────────────────────────────────────────
        if condition["type"] in ("precip_above", "precip_any"):
            # B2: use prior-30-day precip frequency as forecast probability.
            # The old code set our_prob from the realized obs (1.0 or 0.0),
            # which was lookahead leakage — we'd never know the outcome at
            # trade time. The rolling rainy-day fraction uses only past data.
            our_prob = fetch_archive_precip_prob(lat, lon, tz, tdate)
            if our_prob is None:
                continue
        else:
            # ── Temperature markets ───────────────────────────────────────────
            var = "min" if "LOW" in ticker.upper() else "max"
            condition["var"] = var

            if use_previous_runs:
                temps = fetch_previous_run_ensemble(
                    city, tdate, days_out=days_out_bt, var=var
                )
            else:
                temps = fetch_archive_temps(lat, lon, tz, tdate, var=var)
            if len(temps) < 1:
                continue

            if condition["type"] == "above":
                our_prob = sum(1 for t in temps if t > condition["threshold"]) / len(
                    temps
                )
            elif condition["type"] == "below":
                our_prob = sum(1 for t in temps if t < condition["threshold"]) / len(
                    temps
                )
            else:
                lo, hi = condition["lower"], condition["upper"]
                our_prob = sum(1 for t in temps if lo <= t <= hi) / len(temps)

        # Clamp once, here, before Brier scoring or Kelly sizing use it — matching
        # analyze_trade()'s live convention (weather_markets.py clamps blended_prob
        # to [0.01, 0.99] before both logging and Kelly). Narrow "between" brackets
        # scored against only ~50 discrete archive samples very often produce an
        # exact 0.0 or 1.0 (zero samples landing in a 2°F window is common, not a
        # bug in the counting itself) — kelly_fraction() explicitly zeroes the stake
        # whenever probability is exactly at 0 or 1, so without this clamp roughly
        # two-thirds of trades (the "between" markets) silently sized to $0, making
        # win rate look real while P&L stayed ~$0.00 regardless of whether calls
        # were right or wrong. Clamping once here (not just before Kelly) keeps
        # Brier/win-rate/P&L computed from the same value, consistent with each
        # other and with what live's own Brier tracking would log for the same call.
        our_prob = max(0.01, min(0.99, our_prob))

        diag["n_archive"] += 1
        prices = parse_market_price(m)
        market_prob = prices["implied_prob"]
        actual = 1 if result == "yes" else 0
        brier_sq = (our_prob - actual) ** 2
        _cond_acc.setdefault(condition["type"], []).append(brier_sq)

        rec_side = "yes" if our_prob > market_prob else "no"
        # B1: NO entry is no_ask = 1 - yes_bid (matches live pricing in weather_markets.py)
        entry_price = (
            prices["yes_ask"] if rec_side == "yes" else 1.0 - prices["yes_bid"]
        )
        if entry_price <= 0:
            entry_price = market_prob if rec_side == "yes" else 1 - market_prob

        # L2-B: always pass fee_rate so backtest Kelly matches live sizing.
        # Maker fee (not taker): this bot's own live/paper entries are always
        # resting midpoint GTC limit orders, which pay $0 on this bot's
        # markets (see KALSHI_MAKER_FEE_RATE) -- unlike the 3 comparison
        # benchmarks below, which intentionally model a naive taker-style
        # "just take the market price" strategy and correctly keep the
        # taker rate.
        kelly = kelly_fraction(
            our_prob if rec_side == "yes" else 1 - our_prob,
            entry_price,
            fee_rate=KALSHI_MAKER_FEE_RATE,
        )
        stake = min(kelly, 0.05)  # cap at 5% per trade for backtest
        won = (rec_side == "yes" and actual == 1) or (rec_side == "no" and actual == 0)
        # P&L: win case = net gain after maker fee on winnings; lose case = lose the stake
        if won:
            pnl = stake * (1 - entry_price) / entry_price * (1 - KALSHI_MAKER_FEE_RATE)
        else:
            pnl = -stake

        is_holdout = holdout_cutoff is not None and tdate >= holdout_cutoff

        # ── Benchmark P&L calculations ────────────────────────────────────────
        # Always-YES benchmark
        yes_stake = min(0.05, 0.05)  # same 5% cap
        yes_won = actual == 1
        yes_entry = market_prob
        if yes_entry <= 0:
            yes_entry = 0.5
        if yes_won:
            bench_yes = yes_stake * (1 - yes_entry) / yes_entry * (1 - KALSHI_FEE_RATE)
        else:
            bench_yes = -yes_stake

        # Follow-market benchmark (bet whichever side market prices >50%)
        mkt_side = "yes" if market_prob > 0.5 else "no"
        mkt_won = (mkt_side == "yes" and actual == 1) or (
            mkt_side == "no" and actual == 0
        )
        mkt_entry = market_prob if mkt_side == "yes" else 1 - market_prob
        if mkt_entry <= 0:
            mkt_entry = 0.5
        if mkt_won:
            bench_mkt = yes_stake * (1 - mkt_entry) / mkt_entry * (1 - KALSHI_FEE_RATE)
        else:
            bench_mkt = -yes_stake

        # Random benchmark (reproducible with seed based on ticker)
        rng_local = random.Random(hash(ticker) & 0xFFFFFF)
        rand_side = "yes" if rng_local.random() > 0.5 else "no"
        rand_won = (rand_side == "yes" and actual == 1) or (
            rand_side == "no" and actual == 0
        )
        rand_entry = market_prob if rand_side == "yes" else 1 - market_prob
        if rand_entry <= 0:
            rand_entry = 0.5
        if rand_won:
            bench_rand = (
                yes_stake * (1 - rand_entry) / rand_entry * (1 - KALSHI_FEE_RATE)
            )
        else:
            bench_rand = -yes_stake

        results.append(
            {
                "ticker": ticker,
                "city": city,
                "date": tdate.isoformat(),
                "our_prob": round(our_prob, 4),
                "market_prob": round(market_prob, 4),
                "actual": actual,
                "brier_sq": round(brier_sq, 4),
                "rec_side": rec_side,
                "won": won,
                "pnl": round(pnl, 4),
                "holdout": is_holdout,
                "bench_yes_pnl": round(bench_yes, 4),
                "bench_market_pnl": round(bench_mkt, 4),
                "bench_random_pnl": round(bench_rand, 4),
            }
        )

        # Small polite delay between markets to avoid hammering the API
        import time as _time_loop

        _time_loop.sleep(0.05)

    if not results:
        return {
            "n_markets": 0,
            "train_brier": None,
            "win_rate": None,
            "total_pnl": 0.0,
            "rows": [],
            "val_brier": None,
            "val_n": 0,
            "val_brier_unreliable": True,
            "val_win_rate": None,
            "bench_yes_pnl": 0.0,
            "bench_market_pnl": 0.0,
            "bench_random_pnl": 0.0,
            "brier_by_condition": {},
            "diagnostic": diag,
        }

    train = [r for r in results if not r["holdout"]]
    val = [r for r in results if r["holdout"]]

    def _summarise(rows: list[dict]) -> tuple:
        if not rows:
            return None, 0, None
        b = sum(r["brier_sq"] for r in rows) / len(rows)
        w = sum(1 for r in rows if r["won"])
        return round(b, 4), len(rows), round(w / len(rows), 3)

    train_brier, train_n, train_wr = _summarise(train or results)
    val_brier, val_n, val_wr = _summarise(val)

    total_pnl = sum(r["pnl"] for r in results)
    bench_yes_pnl = sum(r.get("bench_yes_pnl", 0.0) for r in results)
    bench_market_pnl = sum(r.get("bench_market_pnl", 0.0) for r in results)
    bench_random_pnl = sum(r.get("bench_random_pnl", 0.0) for r in results)

    return {
        "n_markets": len(results),
        "train_brier": train_brier,
        "win_rate": train_wr,
        "total_pnl": round(total_pnl, 4),
        "rows": results,
        "val_brier": val_brier,
        "val_n": val_n,
        "val_brier_unreliable": val_n < 10,
        "val_win_rate": val_wr,
        "bench_yes_pnl": round(bench_yes_pnl, 4),
        "bench_market_pnl": round(bench_market_pnl, 4),
        "bench_random_pnl": round(bench_random_pnl, 4),
        "brier_by_condition": {
            ctype: {"brier": round(sum(errs) / len(errs), 4), "n": len(errs)}
            for ctype, errs in _cond_acc.items()
        },
    }


# ── Walk-forward optimization ─────────────────────────────────────────────────


def run_walk_forward(
    client,
    days_total: int = 180,
    window_size: int = 60,
    step_size: int = 30,
    city_filter: str | None = None,
    on_progress=None,
) -> dict:
    """
    Walk-forward validation: slide a fixed-size window across the history,
    scoring the model in each window independently.

    Detects whether performance is improving, stable, or degrading over time.
    Also computes per-city win rates to populate learned_weights.

    Returns {
      windows: [{start_date, end_date, brier, win_rate, pnl, n}],
      avg_brier, avg_win_rate, stability_score, trend,
      city_win_rates: {city: win_rate},
    }
    """
    import sqlite3
    import statistics

    # #20: validate that window parameters don't create gaps or excessive overlap
    if step_size > window_size:
        import warnings

        warnings.warn(
            f"walk_forward: step_size ({step_size}) > window_size ({window_size}); "
            "some history will be skipped (gap between windows)."
        )

    from datetime import date, timedelta

    # Read directly from the tracker DB — all the data we need is already logged
    # (forecast_prob + outcome + city + market_date). Zero API calls required.
    # client and on_progress are kept as parameters for API compatibility but unused.
    from tracker import DB_PATH as _TRACKER_DB

    _empty: dict = {
        "windows": [],
        "avg_brier": None,
        "avg_win_rate": None,
        "stability_score": None,
        "trend": "unknown",
        "city_win_rates": {},
    }

    cutoff = (date.today() - timedelta(days=days_total)).isoformat()
    try:
        _con = sqlite3.connect(_TRACKER_DB)
        _con.row_factory = sqlite3.Row
        _cur = _con.cursor()
        _q = """
            SELECT p.our_prob, p.city, p.market_date, o.settled_yes
            FROM multiday_predictions p
            JOIN outcomes o ON p.ticker = o.ticker
            WHERE p.market_date >= ?
              AND p.our_prob IS NOT NULL
              AND o.settled_yes IS NOT NULL
        """
        _params: list = [cutoff]
        if city_filter:
            _q += " AND p.city = ?"
            _params.append(city_filter)
        _cur.execute(_q, _params)
        _db_rows = _cur.fetchall()
        _con.close()
    except Exception as _e:
        import logging as _logging

        _logging.getLogger(__name__).warning(
            "run_walk_forward: DB query failed: %s", _e
        )
        return _empty

    if not _db_rows:
        return _empty

    all_rows = []
    for _r in _db_rows:
        _prob = float(_r["our_prob"])
        _outcome = int(_r["settled_yes"])
        all_rows.append(
            {
                "date": _r["market_date"],
                "city": _r["city"] or "",
                "brier_sq": (_prob - _outcome) ** 2,
                "won": (_prob >= 0.5) == bool(_outcome),
                "pnl": 0.0,  # entry price not available in tracker DB
            }
        )

    today = date.today()
    windows = []
    for offset in range(0, days_total - window_size + 1, step_size):
        start_days = days_total - offset
        end_days = start_days - window_size
        if end_days < 0:
            end_days = 0

        window_start = today - timedelta(days=start_days)
        window_end = today - timedelta(days=end_days)
        rows = [
            r
            for r in all_rows
            if window_start <= date.fromisoformat(r["date"]) <= window_end
        ]
        if not rows:
            continue
        brier_w = sum(r["brier_sq"] for r in rows) / len(rows)
        wins_w = sum(1 for r in rows if r["won"])
        windows.append(
            {
                "start_date": window_start.isoformat(),
                "end_date": window_end.isoformat(),
                "brier": round(brier_w, 4),
                "win_rate": round(wins_w / len(rows), 3),
                "pnl": round(sum(r["pnl"] for r in rows), 4),
                "n": len(rows),
            }
        )

    if not windows:
        return {
            "windows": [],
            "avg_brier": None,
            "avg_win_rate": None,
            "stability_score": None,
            "trend": "unknown",
            "city_win_rates": {},
        }

    avg_brier = sum(w["brier"] for w in windows) / len(windows)
    avg_win_rate = sum(w["win_rate"] for w in windows) / len(windows)

    # Stability: lower std of win rates = more stable
    if len(windows) >= 2:
        wr_std = statistics.stdev(w["win_rate"] for w in windows)
        stability_score = round(max(0.0, 1.0 - wr_std / max(avg_win_rate, 0.01)), 4)
    else:
        stability_score = None

    # Trend: compare first-half vs second-half brier scores
    mid = len(windows) // 2
    if mid > 0:
        first_half_brier = sum(w["brier"] for w in windows[:mid]) / mid
        second_half_brier = sum(w["brier"] for w in windows[mid:]) / max(
            len(windows) - mid, 1
        )
        if second_half_brier < first_half_brier - 0.02:
            trend = "improving"
        elif second_half_brier > first_half_brier + 0.02:
            trend = "declining"
        else:
            trend = "stable"
    else:
        trend = "stable"

    # City win rates from the already-fetched rows — no extra API call
    city_rows: dict[str, list] = {}
    for r in all_rows:
        city_rows.setdefault(r.get("city", ""), []).append(r["won"])
    city_win_rates = {
        city: round(sum(ws) / len(ws), 3)
        for city, ws in city_rows.items()
        if city and len(ws) >= 5
    }

    return {
        "windows": windows,
        "avg_brier": round(avg_brier, 4),
        "avg_win_rate": round(avg_win_rate, 3),
        "stability_score": stability_score,
        "trend": trend,
        "city_win_rates": city_win_rates,
    }


# ── Overfitting guard ─────────────────────────────────────────────────────────


def check_overfitting(in_sample_brier: float, out_of_sample_brier: float) -> dict:
    """
    Formal overfitting guard: compare in-sample vs out-of-sample Brier scores.
    Returns a dict with assessment and recommendation.

    Thresholds (empirical):
    - Degradation > 0.05: likely overfitting, reduce complexity
    - Degradation > 0.10: severe overfitting, revert to simpler model
    """
    degradation = out_of_sample_brier - in_sample_brier

    if degradation <= 0.0:
        status = "healthy"
        recommendation = "Out-of-sample better than in-sample — model generalizes well."
    elif degradation <= 0.03:
        status = "acceptable"
        recommendation = "Minor degradation — within acceptable range."
    elif degradation <= 0.05:
        status = "warning"
        recommendation = "Moderate overfitting detected. Consider reducing feature count or regularizing."
    elif degradation <= 0.10:
        status = "overfit"
        recommendation = "Significant overfitting. Revert recent parameter changes or simplify model."
    else:
        status = "severe"
        recommendation = "Severe overfitting. Immediate model review required."

    return {
        "in_sample_brier": in_sample_brier,
        "out_of_sample_brier": out_of_sample_brier,
        "degradation": degradation,
        "status": status,
        "recommendation": recommendation,
    }


# ── Walk-Forward Backtesting ──────────────────────────────────────────────────


def _find_optimal_min_edge(trades: list[dict]) -> float | None:
    """D4: Find the edge threshold that maximises win rate for trades above it.
    Returns the best threshold among [0.04..0.10] with >=10 qualifying trades,
    or None if there is insufficient data.
    """
    THRESHOLDS = [0.04, 0.05, 0.06, 0.07, 0.08, 0.09, 0.10]
    best_threshold: float | None = None
    best_wr = -1.0
    for thr in THRESHOLDS:
        subset = [t for t in trades if abs(t.get("edge", 0) or 0) >= thr]
        if len(subset) < 10:
            continue
        wr = sum(1 for t in subset if t.get("settled_yes")) / len(subset)
        if wr > best_wr:
            best_wr = wr
            best_threshold = thr
    return best_threshold


def save_walk_forward_params(results: dict, path: Path | None = None) -> None:
    """D4: Persist walk-forward results so config.py can use optimal_min_edge
    as a soft override for PAPER_MIN_EDGE (env var still takes precedence).
    """
    import time

    p = path or DATA_DIR / "walk_forward_params.json"
    out = {
        "mean_brier": results.get("mean_brier"),
        "std_brier": results.get("std_brier"),
        "n_folds": results.get("n_folds"),
        "optimal_min_edge": results.get("optimal_min_edge"),
        "saved_at": time.time(),
    }
    try:
        import safe_io

        safe_io.atomic_write_json(out, p)
    except Exception as _e:
        _log.warning("save_walk_forward_params: could not save results: %s", _e)


def walk_forward_split(
    trades: list[dict],
    train_months: int = 6,
    test_months: int = 1,
) -> list[tuple[list[dict], list[dict]]]:
    """
    Split trades into walk-forward train/test folds.

    Each fold trains on [start, train_end] and tests on [train_end+1, test_end].
    The window rolls forward by test_months each iteration.

    Args:
        trades: List of trade dicts with 'market_date' (ISO date string), 'our_prob',
                'settled_yes' keys
        train_months: Number of months in each training window
        test_months: Number of months in each test window

    Returns:
        List of (train_trades, test_trades) tuples. Empty if insufficient data.
    """
    if not trades:
        return []

    sorted_trades = sorted(trades, key=lambda t: t["market_date"])
    months_seen = sorted(set(t["market_date"][:7] for t in sorted_trades))
    total_months = len(months_seen)

    if total_months < train_months + test_months:
        return []

    folds = []
    test_start_idx = train_months
    while test_start_idx + test_months <= total_months:
        train_months_set = set(months_seen[:test_start_idx])
        test_months_set = set(
            months_seen[test_start_idx : test_start_idx + test_months]
        )

        train = [t for t in sorted_trades if t["market_date"][:7] in train_months_set]
        test = [t for t in sorted_trades if t["market_date"][:7] in test_months_set]

        if train and test:
            folds.append((train, test))

        test_start_idx += test_months

    return folds


def _brier_score_from_trades(trades: list[dict]) -> float | None:
    """Compute Brier score from a list of trade dicts."""
    valid = [
        t
        for t in trades
        if t.get("our_prob") is not None and t.get("settled_yes") is not None
    ]
    if not valid:
        return None
    return sum(
        (t["our_prob"] - (1 if t["settled_yes"] else 0)) ** 2 for t in valid
    ) / len(valid)


def walk_forward_backtest(
    trades: list[dict],
    train_months: int = 6,
    test_months: int = 1,
) -> dict:
    """
    Run a walk-forward (rolling out-of-sample) backtest on historical trade data.

    Evaluates historically recorded probabilities against settled outcomes using
    an expanding-window split (see walk_forward_split): each fold trains on all
    data up to a cutoff and tests on the next test_months window.  No model
    retraining occurs — the function measures how well the probabilities that
    were recorded at trade time predict outcomes, fold by fold.

    Args:
        trades: Historical trade records (must have market_date, our_prob, settled_yes)
        train_months: Minimum training window size in months
        test_months: Test window size in months

    Returns:
        dict with folds, mean_brier, std_brier, n_folds
    """
    import statistics

    folds_data = walk_forward_split(trades, train_months, test_months)
    fold_results = []
    _per_fold_edges: list[tuple[int, float | None]] = []

    for fold_idx, (train, test) in enumerate(folds_data):
        test_brier = _brier_score_from_trades(test)
        test_months_list = sorted(set(t["market_date"][:7] for t in test))
        # Derive threshold from training data only \u2014 no look-ahead into test fold.
        fold_edge = _find_optimal_min_edge(train)
        _per_fold_edges.append((fold_idx, fold_edge))
        fold_results.append(
            {
                "test_period": f"{test_months_list[0]} \u2014 {test_months_list[-1]}",
                "n_train": len(train),
                "n_test": len(test),
                "brier": round(test_brier, 4) if test_brier is not None else None,
                "optimal_min_edge": fold_edge,
            }
        )

    valid_scores: list[float] = [
        f["brier"]  # type: ignore[misc]
        for f in fold_results
        if f["brier"] is not None
    ]
    mean_brier = round(statistics.mean(valid_scores), 4) if valid_scores else None
    std_brier = (
        round(statistics.stdev(valid_scores), 4) if len(valid_scores) > 1 else None
    )

    # D4: derive optimal min_edge from TRAINING folds only (no look-ahead bias).
    # Each fold contributes a threshold tuned on its own training window; we
    # take the median across folds so no single fold dominates.
    train_edges = [e for _, e in _per_fold_edges if e is not None]
    if train_edges:
        optimal_min_edge: float | None = statistics.median(train_edges)
    else:
        optimal_min_edge = None
    result_out = {
        "folds": fold_results,
        "mean_brier": mean_brier,
        "std_brier": std_brier,
        "n_folds": len(fold_results),
        "optimal_min_edge": optimal_min_edge,
    }
    if len(fold_results) >= 2:
        save_walk_forward_params(result_out)
    return result_out


def run_paper_walk_forward() -> dict | None:
    """Load paper-trade history and run walk_forward_backtest against it.

    Shared core of `py main.py walk-forward`/`wfbt` (which prints a full report
    from the returned dict) and cron's automatic weekly re-run — needs no live
    Kalshi client, only local paper-trade history, so it's safe/cheap to call
    from cron. Returns None (no print, no side effect) if there aren't enough
    settled trades yet; walk_forward_backtest itself only persists to
    walk_forward_params.json (via save_walk_forward_params) once it has >=2
    folds, so a too-small history is already a no-op beyond this point.
    """
    from paper import load_paper_trades

    trades_raw = load_paper_trades()
    # Paper trade records store the model's entry-time probability as
    # "entry_prob" (confirmed 2026-07-05 against every current paper trade —
    # none use "our_prob"/"forecast_prob", the field names this mapping
    # actually checked). That silently zeroed out every walk-forward run
    # through this path: the <50-trade gate below always saw 0 trades
    # regardless of real history size, so walk_forward_params.json was never
    # updated by this route. "our_prob"/"forecast_prob" kept as a fallback in
    # case an older or differently-sourced trade record ever used them.
    trades = [
        {
            "market_date": t.get("date", t.get("placed_at", ""))[:10],
            "our_prob": t.get("entry_prob", t.get("our_prob", t.get("forecast_prob"))),
            "settled_yes": t.get("outcome") == "yes",
            "city": t.get("city", ""),
            "method": t.get("method", ""),
            "edge": t.get("net_edge", t.get("edge", 0)),
        }
        for t in trades_raw
        if t.get("outcome") in ("yes", "no")
        and (
            t.get("entry_prob") is not None
            or t.get("our_prob") is not None
            or t.get("forecast_prob") is not None
        )
    ]
    # Drop trades with no parseable date — empty strings corrupt fold boundaries.
    trades = [t for t in trades if len(t.get("market_date", "")) == 10]

    if len(trades) < 50:
        return None

    # train_months=3: paper-trade history is short, so 3 months is more practical
    # than the 6-month default.
    return walk_forward_backtest(trades, train_months=3, test_months=1)
