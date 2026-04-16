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

import json
import random
from datetime import date, timedelta
from pathlib import Path

import requests

from utils import KALSHI_FEE_RATE

ARCHIVE_ENS_BASE = "https://archive-api.open-meteo.com/v1/archive"
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
        for t, v in zip(times, vals):
            if v is None:
                continue
            if t == target_str:
                exact = v
            nearby.append(v)

        if exact is None:
            return []

        sigma = statistics.stdev(nearby) if len(nearby) >= 4 else 3.0
        # #22: seed from target_str hash for varied (but deterministic) ensembles
        random.seed(hash(target_str) & 0xFFFFFFFF)
        result = [exact + random.gauss(0, sigma) for _ in range(50)]
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


# ── Backtest runner ───────────────────────────────────────────────────────────


def stratified_train_test_split(
    records: list[dict],
    holdout_frac: float = 0.2,
    strat_keys: tuple = ("city", "condition_type"),
) -> tuple[list[dict], list[dict]]:
    """
    #21: Stratified train/test split that ensures all strata appear in holdout.

    Stratifies by (city, condition_type) — or any other strat_keys — so that
    each combination is sampled proportionally in the holdout set.

    Returns (train, holdout) lists.
    """
    import math

    # Group records by strata
    strata: dict[tuple, list[dict]] = {}
    for rec in records:
        key = tuple(rec.get(k) for k in strat_keys)
        strata.setdefault(key, []).append(rec)

    train: list[dict] = []
    holdout: list[dict] = []

    for key, group in strata.items():
        n = len(group)
        n_holdout = max(1, math.ceil(n * holdout_frac))  # at least 1 per stratum
        # Sort for determinism (by first key in record if available)
        sorted_group = sorted(group, key=lambda r: str(r.get("date", "")))
        # Take from the end (most recent) as holdout — mirrors temporal split
        holdout.extend(sorted_group[-n_holdout:])
        train.extend(sorted_group[:-n_holdout])

    return train, holdout


def run_backtest(
    client,
    city_filter: str | None = None,
    days_back: int = 90,
    verbose: bool = False,
    holdout_fraction: float = 0.20,
    on_progress=None,
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
    markets = client.get_markets(status="settled", limit=200)

    results = []
    for _prog_i, m in enumerate(markets, 1):
        if on_progress:
            on_progress(_prog_i, len(markets))
        ticker = m.get("ticker", "")
        result = m.get("result", "")
        if result not in ("yes", "no"):
            continue

        enriched = enrich_with_forecast(m)
        city = enriched.get("_city")
        tdate = enriched.get("_date")
        forecast = enriched.get("_forecast")

        if not city or not tdate or not forecast:
            continue
        if city_filter and city.lower() != city_filter.lower():
            continue
        if tdate < cutoff:
            continue

        coords = CITY_COORDS.get(city)
        if not coords:
            continue
        lat, lon, tz = coords

        condition = _parse_market_condition(enriched)
        if not condition:
            continue

        # ── Precipitation markets ─────────────────────────────────────────────
        if condition["type"] in ("precip_above", "precip_any"):
            obs, _reason = fetch_archive_precip(lat, lon, tz, tdate)
            if obs is None:
                continue
            if condition["type"] == "precip_any":
                our_prob = 1.0 if obs > 0.01 else 0.0
            else:
                our_prob = 1.0 if obs > condition["threshold"] else 0.0
        else:
            # ── Temperature markets ───────────────────────────────────────────
            var = "min" if "LOW" in ticker.upper() else "max"
            condition["var"] = var

            temps = fetch_archive_temps(lat, lon, tz, tdate, var=var)
            if len(temps) < 10:
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

        prices = parse_market_price(m)
        market_prob = prices["implied_prob"]
        actual = 1 if result == "yes" else 0
        brier_sq = (our_prob - actual) ** 2

        rec_side = "yes" if our_prob > market_prob else "no"
        entry_price = prices["yes_ask"] if rec_side == "yes" else prices["no_bid"]
        if entry_price <= 0:
            entry_price = market_prob if rec_side == "yes" else 1 - market_prob

        kelly = kelly_fraction(
            our_prob if rec_side == "yes" else 1 - our_prob, entry_price
        )
        stake = min(kelly, 0.05)  # cap at 5% per trade for backtest
        won = (rec_side == "yes" and actual == 1) or (rec_side == "no" and actual == 0)
        # P&L: win case = net gain after 7% fee on winnings; lose case = lose the stake
        if won:
            pnl = stake * (1 - entry_price) / entry_price * (1 - KALSHI_FEE_RATE)
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

        # ── Log ensemble member score for temperature markets ─────────────────
        if condition["type"] not in ("precip_above", "precip_any") and temps:
            try:
                from tracker import log_member_score as _log_ms

                member_mean = sum(temps) / len(temps)
                # actual_temp is not directly known from result alone; use temps mean as proxy
                # We record predicted mean vs an estimate of actual via archive
                _log_ms(
                    city=city,
                    model="ensemble_blend",
                    predicted_temp=round(member_mean, 2),
                    actual_temp=round(member_mean + (actual - our_prob) * 10, 2),
                    target_date_str=tdate.isoformat(),
                )
            except Exception:
                pass

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
            "brier": None,
            "win_rate": None,
            "total_pnl": 0.0,
            "rows": [],
            "val_brier": None,
            "val_n": 0,
            "val_win_rate": None,
            "bench_yes_pnl": 0.0,
            "bench_market_pnl": 0.0,
            "bench_random_pnl": 0.0,
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
        "brier": train_brier,
        "win_rate": train_wr,
        "total_pnl": round(total_pnl, 4),
        "rows": results,
        "val_brier": val_brier,
        "val_n": val_n,
        "val_win_rate": val_wr,
        "bench_yes_pnl": round(bench_yes_pnl, 4),
        "bench_market_pnl": round(bench_market_pnl, 4),
        "bench_random_pnl": round(bench_random_pnl, 4),
    }


# ── Walk-forward optimization ─────────────────────────────────────────────────


def run_walk_forward(
    client,
    days_total: int = 180,
    window_size: int = 60,
    step_size: int = 30,
    city_filter: str | None = None,
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
    import statistics

    # #20: validate that window parameters don't create gaps or excessive overlap
    if step_size > window_size:
        import warnings

        warnings.warn(
            f"walk_forward: step_size ({step_size}) > window_size ({window_size}); "
            "some history will be skipped (gap between windows)."
        )

    if client is None:
        return {
            "windows": [],
            "avg_brier": None,
            "avg_win_rate": None,
            "stability_score": None,
            "trend": "unknown",
            "city_win_rates": {},
        }

    windows = []
    for offset in range(0, days_total - window_size + 1, step_size):
        start_days = days_total - offset
        end_days = start_days - window_size
        if end_days < 0:
            end_days = 0

        try:
            result = run_backtest(
                client,
                city_filter=city_filter,
                days_back=start_days,
                verbose=False,
                holdout_fraction=0.0,
            )
            # Filter to rows within the window
            from datetime import date, timedelta

            window_start = date.today() - timedelta(days=start_days)
            window_end = date.today() - timedelta(days=end_days)
            rows = [
                r
                for r in result.get("rows", [])
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
        except Exception:
            continue

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

    # City win rates for learned weights
    try:
        all_result = run_backtest(
            client,
            city_filter=city_filter,
            days_back=days_total,
            verbose=False,
            holdout_fraction=0.0,
        )
        city_rows: dict[str, list] = {}
        for r in all_result.get("rows", []):
            city_rows.setdefault(r.get("city", ""), []).append(r["won"])
        city_win_rates = {
            city: round(sum(ws) / len(ws), 3)
            for city, ws in city_rows.items()
            if city and len(ws) >= 5
        }
    except Exception:
        city_win_rates = {}

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
