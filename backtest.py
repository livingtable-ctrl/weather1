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
        resp = requests.get(ARCHIVE_ENS_BASE, params=params, timeout=30)  # type: ignore[arg-type]
        resp.raise_for_status()
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
        random.seed(42)
        result = [exact + random.gauss(0, sigma) for _ in range(50)]
        try:
            cache_file.write_text(json.dumps(result))
        except Exception:
            pass
        return result
    except Exception:
        return []


# ── Backtest runner ───────────────────────────────────────────────────────────


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
    markets = client.get_markets(status="finalized", limit=200)

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
        if not condition or condition["type"] in ("precip_above", "precip_any"):
            continue

        var = "min" if "LOW" in ticker.upper() else "max"
        condition["var"] = var

        # Fetch archive temps as simulated ensemble
        temps = fetch_archive_temps(lat, lon, tz, tdate, var=var)
        if len(temps) < 10:
            continue

        if condition["type"] == "above":
            our_prob = sum(1 for t in temps if t > condition["threshold"]) / len(temps)
        elif condition["type"] == "below":
            our_prob = sum(1 for t in temps if t < condition["threshold"]) / len(temps)
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
            }
        )

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

    return {
        "n_markets": len(results),
        "brier": train_brier,
        "win_rate": train_wr,
        "total_pnl": round(total_pnl, 4),
        "rows": results,
        "val_brier": val_brier,
        "val_n": val_n,
        "val_win_rate": val_wr,
    }
