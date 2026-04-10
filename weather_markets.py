"""
Fetch and analyze Kalshi weather prediction markets.
Compares market-implied probabilities with Open-Meteo forecast data.
"""

from __future__ import annotations

import math
import random
import re
import statistics
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, date, datetime

from climate_indices import temperature_adjustment
from climatology import climatological_prob
from kalshi_client import KalshiClient, _request_with_retry
from nws import get_live_observation, nws_prob, obs_prob
from utils import KALSHI_FEE_RATE, normal_cdf

# ── Open-Meteo (free, no API key) ────────────────────────────────────────────

CITY_COORDS = {
    # Exact settlement station coordinates (not city centre)
    "NYC": (40.7789, -73.9692, "America/New_York"),  # Central Park (WBAN 94728)
    "Chicago": (41.9803, -87.9090, "America/Chicago"),  # O'Hare Intl (WBAN 94846)
    "LA": (34.0190, -118.2910, "America/Los_Angeles"),  # USC Downtown (COOP 045114)
    "Miami": (25.8175, -80.3164, "America/New_York"),  # Miami Intl Airport (WBAN 12839)
    "Boston": (42.3606, -71.0106, "America/New_York"),  # Logan Airport (WBAN 14739)
    "Dallas": (32.8998, -97.0403, "America/Chicago"),  # DFW Airport (WBAN 03927)
    "Phoenix": (
        33.4373,
        -112.0078,
        "America/Phoenix",
    ),  # Phoenix Sky Harbor (WBAN 23183)
    "Seattle": (
        47.4502,
        -122.3088,
        "America/Los_Angeles",
    ),  # Sea-Tac Airport (WBAN 24233)
    "Denver": (
        39.8561,
        -104.6737,
        "America/Denver",
    ),  # Denver Intl Airport (WBAN 03017)
    "Atlanta": (
        33.6407,
        -84.4277,
        "America/New_York",
    ),  # Atlanta Hartsfield (WBAN 13874)
}

FORECAST_BASE = "https://api.open-meteo.com/v1/forecast"
ENSEMBLE_BASE = "https://ensemble-api.open-meteo.com/v1/ensemble"
ENSEMBLE_MODELS = ["icon_seamless", "gfs_seamless"]

# Ensemble cache: key -> (list[float], timestamp)
_ENSEMBLE_CACHE: dict = {}
_ENSEMBLE_CACHE_TTL = 90 * 60  # 90 minutes

# Forecast cache: (city, date_iso) -> (dict, timestamp)
_FORECAST_CACHE: dict = {}
_FORECAST_CACHE_TTL = 90 * 60  # 90 minutes


# ── Multi-model regular forecast ─────────────────────────────────────────────


def _forecast_model_weights(month: int) -> dict[str, float]:
    """
    Seasonal model weights for the daily forecast blend.
    ECMWF is the most accurate global model in winter (Oct–Mar) for mid-latitudes.
    GFS is competitive in summer for the US. ICON adds value year-round.
    """
    is_winter = month in (10, 11, 12, 1, 2, 3)
    ecmwf_w = 2.5 if is_winter else 1.5
    return {"gfs_seamless": 1.0, "ecmwf_ifs04": ecmwf_w, "icon_seamless": 1.0}


def get_weather_forecast(city: str, target_date: date) -> dict | None:
    """
    Fetch daily high/low/precip from three forecast models (GFS, ECMWF, ICON)
    and return the averaged values. Results are cached for 90 minutes.
    """
    cache_key = (city, target_date.isoformat())
    cached = _FORECAST_CACHE.get(cache_key)
    if cached is not None:
        data, ts = cached
        if time.monotonic() - ts < _FORECAST_CACHE_TTL:
            return data

    coords = CITY_COORDS.get(city)
    if not coords:
        return None
    lat, lon, tz = coords

    # Seasonal model weights — ECMWF more accurate in winter, GFS competitive in summer
    model_weights = _forecast_model_weights(target_date.month)
    highs: list[tuple[float, float]] = []  # (value, weight)
    lows: list[tuple[float, float]] = []
    precips: list[tuple[float, float]] = []

    def _fetch_one(model: str, weight: float) -> tuple | None:
        """Fetch one model's forecast; returns (high, low, precip, weight) or None."""
        params = {
            "latitude": lat,
            "longitude": lon,
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum",
            "temperature_unit": "fahrenheit",
            "precipitation_unit": "inch",
            "timezone": tz,
            "forecast_days": 16,
            "models": model,
        }
        resp = _request_with_retry("GET", FORECAST_BASE, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        daily = data.get("daily", {})
        dates = daily.get("time", [])
        target_str = target_date.isoformat()
        if target_str not in dates:
            return None
        idx = dates.index(target_str)
        h = daily.get("temperature_2m_max", [None])[idx]
        lo = daily.get("temperature_2m_min", [None])[idx]
        p = daily.get("precipitation_sum", [None])[idx]
        return (h, lo, p, weight)

    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {
            pool.submit(_fetch_one, model, weight): model
            for model, weight in model_weights.items()
        }
        for fut in as_completed(futures):
            try:
                model_data = fut.result()
                if model_data is None:
                    continue
                h, lo, p, weight = model_data
                if h is not None:
                    highs.append((h, weight))
                if lo is not None:
                    lows.append((lo, weight))
                if p is not None:
                    precips.append((p, weight))
            except Exception:
                continue

    if not highs:
        return None

    def _wavg(pairs: list[tuple[float, float]]) -> float:
        total_w = sum(w for _, w in pairs)
        return sum(v * w for v, w in pairs) / total_w

    high_vals = [v for v, _ in highs]
    result = {
        "date": target_date.isoformat(),
        "city": city,
        "high_f": _wavg(highs),
        "low_f": _wavg(lows) if lows else None,
        "precip_in": _wavg(precips) if precips else 0.0,
        "models_used": len(highs),
        "high_range": (min(high_vals), max(high_vals)),
    }
    _FORECAST_CACHE[cache_key] = (result, time.monotonic())
    return result


# ── Ensemble forecast ────────────────────────────────────────────────────────


def _fetch_model_ensemble(
    lat: float,
    lon: float,
    tz: str,
    target_date: date,
    model: str,
    hour: int | None,
    var: str,
) -> list[float]:
    """
    Fetch all ensemble member temps from one model for a given location/date.
    var: "max" (daily high), "min" (daily low)
    hour: if set, fetch hourly data at that local hour instead of daily.
    """
    params = {
        "latitude": lat,
        "longitude": lon,
        "models": model,
        "temperature_unit": "fahrenheit",
        "timezone": tz,
        "forecast_days": 16,
    }

    if hour is not None:
        params["hourly"] = "temperature_2m"
        resp = _request_with_retry("GET", ENSEMBLE_BASE, params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        hourly = data.get("hourly", {})
        times = hourly.get("time", [])
        target_dt = f"{target_date.isoformat()}T{hour:02d}:00"
        if target_dt not in times:
            return []
        idx = times.index(target_dt)
        return [
            hourly[k][idx]
            for k in hourly
            if k.startswith("temperature_2m_member") and hourly[k][idx] is not None
        ]
    else:
        daily_var = "temperature_2m_max" if var == "max" else "temperature_2m_min"
        params["daily"] = daily_var
        resp = _request_with_retry("GET", ENSEMBLE_BASE, params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        daily = data.get("daily", {})
        times = daily.get("time", [])
        target_str = target_date.isoformat()
        if target_str not in times:
            return []
        idx = times.index(target_str)
        prefix = f"{daily_var}_member"
        return [
            daily[k][idx]
            for k in daily
            if k.startswith(prefix) and daily[k][idx] is not None
        ]


def _model_weights(city: str) -> dict[str, float]:
    """
    Return per-model weights based on historical Brier scores from the tracker.
    Defaults to equal weighting (1.0 each) if insufficient data.
    Higher weight = duplicate members to increase influence.
    """
    try:
        from tracker import brier_score_by_method

        scores = brier_score_by_method()
        # We track blended scores, so use per-city overall accuracy as a proxy.
        # If ensemble Brier < 0.18 (good), up-weight ICON (more members, better
        # resolution); if > 0.22 (poor), reduce to equal weighting.
        overall = scores.get("ensemble")
        if overall is None:
            return {"icon_seamless": 1.0, "gfs_seamless": 1.0}
        if overall < 0.18:
            return {"icon_seamless": 1.5, "gfs_seamless": 1.0}
        elif overall < 0.22:
            return {"icon_seamless": 1.0, "gfs_seamless": 1.0}
        else:
            return {"icon_seamless": 0.8, "gfs_seamless": 1.0}
    except Exception:
        return {"icon_seamless": 1.0, "gfs_seamless": 1.0}


def get_ensemble_temps(
    city: str, target_date: date, hour: int | None = None, var: str = "max"
) -> list[float]:
    """
    Return all ensemble member temperatures for a city/date, combining
    ICON (51 members) and GFS (31 members). Results are cached.
    Model contributions are weighted by historical Brier performance.

    var: "max" for daily high, "min" for daily low (ignored if hour is set).
    hour: local hour (0-23) for hourly markets like KXTEMPNYCH.
    """
    cache_key = (city, target_date.isoformat(), hour, var)
    cached = _ENSEMBLE_CACHE.get(cache_key)
    if cached is not None:
        data, ts = cached
        if time.monotonic() - ts < _ENSEMBLE_CACHE_TTL:
            return data

    coords = CITY_COORDS.get(city)
    if not coords:
        return []
    lat, lon, tz = coords

    weights = _model_weights(city)

    # Decay model weights based on how old this cache entry is.
    # Older forecasts are less reliable — halve differentiation every 6 hours.
    cache_age_hours = (
        time.monotonic() - (cached[1] if cached else time.monotonic())
    ) / 3600
    decay = math.exp(-cache_age_hours / 6.0)  # 1.0 at fresh, ~0.5 at 6h, ~0.25 at 12h

    all_temps: list[float] = []
    for model in ENSEMBLE_MODELS:
        try:
            temps = _fetch_model_ensemble(lat, lon, tz, target_date, model, hour, var)
            base_w = weights.get(model, 1.0)
            # Decay towards equal weighting (1.0) as cache ages
            w = 1.0 + (base_w - 1.0) * decay
            # Replicate members proportionally to apply weight.
            repeats = max(1, round(w * 2))
            all_temps.extend(temps * repeats)
        except Exception:
            pass

    _ENSEMBLE_CACHE[cache_key] = (all_temps, time.monotonic())
    return all_temps


def is_forecast_anomalous(ens_stats: dict, threshold_multiplier: float = 1.5) -> bool:
    """
    Return True if the ensemble spread (p90-p10) is unusually wide — a sign the
    forecast models disagree strongly and uncertainty is high.
    Typical spread is ~8-12°F; anything beyond 1.5× that is flagged.
    """
    if not ens_stats:
        return False
    spread = ens_stats.get("p90", 0) - ens_stats.get("p10", 0)
    # Typical p10-p90 spread for US cities: ~8°F within 7 days
    return spread > 8.0 * threshold_multiplier


def ensemble_stats(temps: list[float]) -> dict:
    """Summary statistics for a list of ensemble member temperatures."""
    if not temps:
        return {}
    return {
        "n": len(temps),
        "mean": statistics.mean(temps),
        "std": statistics.stdev(temps) if len(temps) > 1 else 0.0,
        "min": min(temps),
        "max": max(temps),
        "p10": sorted(temps)[min(int(len(temps) * 0.10), len(temps) - 1)],
        "p90": sorted(temps)[min(int(len(temps) * 0.90), len(temps) - 1)],
    }


# ── Market parsing ────────────────────────────────────────────────────────────


def parse_market_price(market: dict) -> dict:
    """Extract yes/no bid prices and implied probability from a market."""
    yes_bid = market.get("yes_bid") or 0
    yes_ask = market.get("yes_ask") or 0
    no_bid = market.get("no_bid") or 0

    # Prices may be cents (int) or dollar strings depending on API version
    def to_float(v) -> float:
        if isinstance(v, str):
            return float(v)
        if isinstance(v, int | float) and v > 1:
            return v / 100.0  # legacy cents format
        return float(v)

    yes_bid_f = to_float(yes_bid)
    yes_ask_f = to_float(yes_ask)
    no_bid_f = to_float(no_bid)
    mid = (yes_bid_f + yes_ask_f) / 2 if yes_ask_f > 0 else yes_bid_f

    return {
        "yes_bid": yes_bid_f,
        "yes_ask": yes_ask_f,
        "no_bid": no_bid_f,
        "mid": mid,
        "implied_prob": mid,  # mid-price ≈ market probability
    }


# ── Weather series detection ──────────────────────────────────────────────────

WEATHER_KEYWORDS = {
    "temp",
    "high",
    "low",
    "rain",
    "snow",
    "precip",
    "storm",
    "hurricane",
    "wind",
    "frost",
    "heat",
    "cold",
    "weather",
}


def is_stale(market: dict) -> bool:
    """
    Returns True if a market has no volume AND closes within 60 minutes.
    Stale markets have meaningless edge calculations — skip them.
    """
    volume = market.get("volume") or 0
    open_interest = market.get("open_interest") or 0
    if volume > 0 or open_interest > 0:
        return False
    close_time_str = market.get("close_time", "")
    if not close_time_str:
        return False
    try:
        close_time = datetime.fromisoformat(close_time_str.replace("Z", "+00:00"))
        minutes_left = (close_time - datetime.now(UTC)).total_seconds() / 60
        return minutes_left < 60
    except (ValueError, TypeError):
        return False


def is_weather_market(market: dict) -> bool:
    title = (market.get("title") or "").lower()
    subtitle = (market.get("subtitle") or "").lower()
    ticker = (market.get("ticker") or "").lower()
    series = (market.get("series_ticker") or "").lower()
    text = f"{title} {subtitle} {ticker} {series}"
    return any(kw in text for kw in WEATHER_KEYWORDS)


def get_weather_markets(client: KalshiClient, limit: int = 200) -> list[dict]:
    """
    Fetch open markets and filter to weather-related ones.
    Also tries the series endpoint with weather tags.
    """
    results = []
    seen = set()

    # Strategy 1: fetch open markets and filter
    try:
        markets = client.get_markets(status="open", limit=limit)
        for m in markets:
            if m.get("ticker") not in seen and is_weather_market(m) and not is_stale(m):
                results.append(m)
                seen.add(m["ticker"])
    except Exception as e:
        print(f"[warn] Could not fetch markets: {e}")

    # Strategy 2: known weather series tickers
    known_series = [
        "KXHIGHNY",
        "KXHIGHCHI",
        "KXHIGHLA",
        "KXHIGHBOS",
        "KXHIGHMIA",
        "KXLOWNY",
        "KXLOWCHI",
        "KXRAIN",
    ]
    for series in known_series:
        try:
            markets = client.get_markets(series_ticker=series, status="open", limit=50)
            for m in markets:
                if m.get("ticker") not in seen:
                    results.append(m)
                    seen.add(m["ticker"])
        except Exception:
            pass

    return results


MONTH_MAP = {
    "JAN": 1,
    "FEB": 2,
    "MAR": 3,
    "APR": 4,
    "MAY": 5,
    "JUN": 6,
    "JUL": 7,
    "AUG": 8,
    "SEP": 9,
    "OCT": 10,
    "NOV": 11,
    "DEC": 12,
}


def enrich_with_forecast(market: dict) -> dict:
    """
    Attach forecast data to a market dict.
    Parses city, date, and (for hourly markets) hour from the ticker.
    """
    ticker = market.get("ticker", "")
    title = (market.get("title") or "").lower()
    ticker_up = ticker.upper()

    # Detect city
    city = None
    if "NY" in ticker_up or "new york" in title:
        city = "NYC"
    elif "CHI" in ticker_up or "chicago" in title:
        city = "Chicago"
    elif "LA" in ticker_up or "los angeles" in title:
        city = "LA"
    elif "BOS" in ticker_up or "boston" in title:
        city = "Boston"
    elif "MIA" in ticker_up or "miami" in title:
        city = "Miami"

    # Detect date + optional hour
    # Hourly tickers: KXTEMPNYCH-26APR0908-T45.99  → date=26APR09, hour=08
    # Daily tickers:  KXHIGHNY-26APR10-T68         → date=26APR10, hour=None
    target_date = None
    hour = None

    hourly_match = re.search(r"(\d{2})([A-Z]{3})(\d{2})(\d{2})", ticker_up)
    daily_match = re.search(r"(\d{2})([A-Z]{3})(\d{2})(?!\d)", ticker_up)

    if hourly_match:
        yy, mon_str, dd, hh = hourly_match.groups()
        month = MONTH_MAP.get(mon_str)
        if month:
            try:
                target_date = date(2000 + int(yy), month, int(dd))
                hour = int(hh)
            except ValueError:
                pass
    elif daily_match:
        yy, mon_str, dd = daily_match.groups()
        month = MONTH_MAP.get(mon_str)
        if month:
            try:
                target_date = date(2000 + int(yy), month, int(dd))
            except ValueError:
                pass

    forecast = None
    if city and target_date:
        forecast = get_weather_forecast(city, target_date)

    return {
        **market,
        "_city": city,
        "_date": target_date,
        "_hour": hour,
        "_forecast": forecast,
    }


# ── Trade analysis ────────────────────────────────────────────────────────────


def _forecast_uncertainty(target_date: date) -> float:
    """
    Estimated standard deviation of forecast error in °F.
    Weather forecasts get less accurate further out.
    """
    days_out = (target_date - date.today()).days
    if days_out <= 1:
        return 3.0
    elif days_out <= 3:
        return 4.0
    elif days_out <= 5:
        return 5.0
    elif days_out <= 7:
        return 6.0
    else:
        return 7.5


def _time_risk(close_time_str: str, tz: str) -> tuple[str, float]:
    """
    Determine time-of-day risk level and forecast sigma multiplier.

    Returns (risk_label, sigma_multiplier):
      "LOW" / 0.5  — within 2 hours of close (near-real-time data available)
      "LOW" / 0.7  — market closes after 8pm local (weather station already read)
      "MEDIUM" / 0.85 — closes within 12 hours
      "HIGH" / 1.0 — far-out market, no timing advantage

    sigma_multiplier < 1.0 means reduce forecast uncertainty (we know more).
    """
    if not close_time_str:
        return ("HIGH", 1.0)
    try:
        from zoneinfo import ZoneInfo

        close_dt = datetime.fromisoformat(close_time_str.replace("Z", "+00:00"))
        hours_to_close = (close_dt - datetime.now(UTC)).total_seconds() / 3600
        local_hour = close_dt.astimezone(ZoneInfo(tz)).hour
        if hours_to_close <= 2:
            return ("LOW", 0.5)
        elif local_hour >= 20:
            return ("LOW", 0.7)
        elif hours_to_close <= 12:
            return ("MEDIUM", 0.85)
        else:
            return ("HIGH", 1.0)
    except Exception:
        return ("HIGH", 1.0)


def _parse_market_condition(market: dict) -> dict | None:
    """
    Parse what outcome a market is asking about from its ticker and title.
    Returns a dict like:
      {"type": "above", "threshold": 68.0}         — temperature above X°F
      {"type": "below", "threshold": 53.0}         — temperature below X°F
      {"type": "between", "lower": 67.0, "upper": 68.0}
      {"type": "precip_above", "threshold": 0.10}  — precip > 0.10 in
      {"type": "precip_any"}                        — any measurable precip (>0.01 in)
    Returns None if unparseable.
    """
    ticker = market.get("ticker", "")
    title = (market.get("title") or "").lower()
    ticker_up = ticker.upper()

    # ── Precipitation markets ─────────────────────────────────────────────────
    # Whitelist known precipitation series to avoid false positives from
    # title-matching unrelated markets that contain words like "rain".
    PRECIP_SERIES = {"KXRAIN", "KXSNOW", "KXPRECIP"}
    series_up = (market.get("series_ticker") or "").upper()
    is_precip_series = any(s in ticker_up or s in series_up for s in PRECIP_SERIES)
    is_precip_title = (
        ("rain" in title or "precip" in title or "snow" in title)
        and "temperature" not in title
        and "high" not in title
        and "low" not in title
    )
    is_precip = is_precip_series or is_precip_title

    if is_precip:
        # Explicit threshold: e.g. KXRAIN-26APR10-P0.25 → precip > 0.25 in
        precip_match = re.search(r"-P(\d+(?:\.\d+)?)(?:-|$)", ticker)
        if precip_match:
            return {"type": "precip_above", "threshold": float(precip_match.group(1))}
        # Threshold in title: "more than 0.50 inches"
        amt_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:inch|in\b)", title)
        if amt_match:
            threshold = float(amt_match.group(1))
            if "more than" in title or "exceed" in title or ">" in title:
                return {"type": "precip_above", "threshold": threshold}
        # Binary any-precip (only if series is a known precip series)
        if is_precip_series or "measurable" in title or "any" in title:
            return {"type": "precip_any"}
        return None

    # ── Temperature markets ───────────────────────────────────────────────────
    # Extract the condition part after the date, e.g. "T68", "T53", "B67.5"
    cond_match = re.search(r"-([TB])(\d+(?:\.\d+)?)$", ticker)
    if not cond_match:
        return None

    kind, val_str = cond_match.group(1), cond_match.group(2)
    val = float(val_str)

    if kind == "B":
        # Bucket: B67.5 means range [67, 68]
        return {"type": "between", "lower": val - 0.5, "upper": val + 0.5}
    else:
        # T: determine above or below from title
        if ">" in title or "above" in title or " be >" in title:
            return {"type": "above", "threshold": val}
        elif "<" in title or "below" in title or " be <" in title:
            return {"type": "below", "threshold": val}
        else:
            return None


def _forecast_probability(condition: dict, forecast_temp: float, sigma: float) -> float:
    """Estimate probability of the market condition given a forecast temperature."""
    if condition["type"] == "above":
        return 1.0 - normal_cdf(condition["threshold"], forecast_temp, sigma)
    elif condition["type"] == "below":
        return normal_cdf(condition["threshold"], forecast_temp, sigma)
    elif condition["type"] == "between":
        p_upper = normal_cdf(condition["upper"], forecast_temp, sigma)
        p_lower = normal_cdf(condition["lower"], forecast_temp, sigma)
        return p_upper - p_lower
    return 0.0


def is_liquid(market: dict) -> bool:
    """
    True if the market has real two-sided quotes (not just 0/0).
    A market with no quotes can still be traded — you'd be the first to post —
    but the implied probability of 0% is misleading for edge calculations.
    """
    prices = parse_market_price(market)
    has_yes = prices["yes_bid"] > 0 or prices["yes_ask"] > 0
    has_no = prices["no_bid"] > 0
    volume = market.get("volume", 0) or 0
    return has_yes or has_no or volume > 0


def _edge_label(edge: float) -> str:
    """Convert a probability edge to a human-readable signal."""
    abs_edge = abs(edge)
    if abs_edge < 0.05:
        return "NEUTRAL"
    direction = "YES" if edge > 0 else "NO "
    if abs_edge >= 0.25:
        return f"STRONG BUY {direction}"
    elif abs_edge >= 0.15:
        return f"BUY {direction}      "
    else:
        return f"WEAK {direction}     "


def _blend_weights(
    days_out: int, has_nws: bool, has_clim: bool
) -> tuple[float, float, float]:
    """Return (w_ensemble, w_climatology, w_nws) based on days out."""
    if days_out <= 1:
        w_ens, w_clim, w_nws = 0.80, 0.05, 0.15
    elif days_out <= 3:
        w_ens, w_clim, w_nws = 0.70, 0.10, 0.20
    elif days_out <= 5:
        w_ens, w_clim, w_nws = 0.55, 0.20, 0.25
    elif days_out <= 7:
        w_ens, w_clim, w_nws = 0.40, 0.35, 0.25
    elif days_out <= 10:
        w_ens, w_clim, w_nws = 0.20, 0.55, 0.25
    else:
        w_ens, w_clim, w_nws = 0.10, 0.65, 0.25

    if not has_nws:
        w_ens += w_nws * 0.6
        w_clim += w_nws * 0.4
        w_nws = 0.0
    if not has_clim:
        w_ens += w_clim
        w_clim = 0.0

    total = w_ens + w_clim + w_nws
    return w_ens / total, w_clim / total, w_nws / total


def _bootstrap_ci(
    temps: list[float], condition: dict, n: int = 500
) -> tuple[float, float]:
    """
    Bootstrap 90% confidence interval on the ensemble probability estimate.
    Resamples ensemble members with replacement n times.
    """
    if len(temps) < 5:
        return (0.0, 1.0)

    def prob_from(sample):
        if condition["type"] == "above":
            return sum(1 for t in sample if t > condition["threshold"]) / len(sample)
        elif condition["type"] == "below":
            return sum(1 for t in sample if t < condition["threshold"]) / len(sample)
        else:
            lo, hi = condition["lower"], condition["upper"]
            return sum(1 for t in sample if lo <= t <= hi) / len(sample)

    k = len(temps)
    boot = sorted(prob_from(random.choices(temps, k=k)) for _ in range(n))
    p05 = boot[min(int(n * 0.05), n - 1)]
    p95 = boot[min(int(n * 0.95), n - 1)]
    return (p05, p95)


def _bootstrap_ci_precip(
    members: list[float], condition: dict, n: int = 500
) -> tuple[float, float]:
    """Bootstrap 90% CI for a precipitation ensemble probability."""
    if len(members) < 5:
        return (0.0, 1.0)

    def prob_from(sample: list[float]) -> float:
        if condition["type"] == "precip_any":
            return sum(1 for p in sample if p > 0.01) / len(sample)
        thresh = condition.get("threshold", 0.0)
        return sum(1 for p in sample if p > thresh) / len(sample)

    k = len(members)
    boot = sorted(prob_from(random.choices(members, k=k)) for _ in range(n))
    return (boot[min(int(n * 0.05), n - 1)], boot[min(int(n * 0.95), n - 1)])


def kelly_fraction(our_prob: float, price: float, fee_rate: float = 0.0) -> float:
    """
    Half-Kelly criterion for a binary prediction market.
    price    = cost per contract in dollars (e.g. 0.30 means you pay $0.30, win $0.70)
    fee_rate = fraction of winnings charged as fee (e.g. 0.07 for Kalshi's 7% fee)
    Returns recommended fraction of bankroll to bet (0–1).

    Kelly formula: f* = (b*p - q) / b  where b = net odds (win per $1 risked)
    For Kalshi: you pay `price`, win `(1-price)*(1-fee_rate)` net of fee.
    Net odds b = (1-price)*(1-fee_rate) / price
    """
    if our_prob <= 0 or our_prob >= 1 or price <= 0 or price >= 1:
        return 0.0
    winnings = (1 - price) * (1 - fee_rate)  # net winnings per contract after fee
    b = winnings / price  # net odds: win $b for every $1 staked
    q = 1 - our_prob
    full_kelly = (b * our_prob - q) / b
    return max(0.0, full_kelly / 2)  # half-Kelly for safety


def _fetch_ensemble_precip(
    lat: float, lon: float, tz: str, target_date: date
) -> list[float]:
    """
    Fetch ensemble precipitation members (inches) for a city/date.
    ECMWF is fetched separately and appended twice (2× weight) to match the
    temperature ensemble weighting in _model_weights().
    """
    results = []
    target_str = target_date.isoformat()
    prefix = "precipitation_sum_member"

    def _fetch_model(model: str) -> list[float]:
        try:
            params = {
                "latitude": lat,
                "longitude": lon,
                "models": model,
                "daily": "precipitation_sum",
                "precipitation_unit": "inch",
                "timezone": tz,
                "forecast_days": 16,
            }
            resp = _request_with_retry("GET", ENSEMBLE_BASE, params=params, timeout=20)
            resp.raise_for_status()
            daily = resp.json().get("daily", {})
            times = daily.get("time", [])
            if target_str not in times:
                return []
            idx = times.index(target_str)
            return [
                vals[idx]
                for k, vals in daily.items()
                if k.startswith(prefix) and vals[idx] is not None
            ]
        except Exception:
            return []

    for model in ENSEMBLE_MODELS:
        results.extend(_fetch_model(model))

    # ECMWF weighted 3× in winter, 2× in summer (seasonal accuracy advantage)
    ecmwf_members = _fetch_model("ecmwf_ifs04")
    ecmwf_mult = 3 if target_date.month in (10, 11, 12, 1, 2, 3) else 2
    results.extend(ecmwf_members * ecmwf_mult)

    return results


def _analyze_precip_trade(
    enriched: dict, forecast: dict, condition: dict, target_date: date, coords: tuple
) -> dict | None:
    """
    Probability analysis for precipitation markets (rain/snow).
    Uses ensemble precipitation members + climatological rain frequency.
    """
    lat, lon, tz = coords
    days_out = max(0, (target_date - date.today()).days)

    # ── Ensemble precipitation probability ───────────────────────────────────
    precip_members = _fetch_ensemble_precip(lat, lon, tz, target_date)
    ens_prob: float | None = None
    if len(precip_members) >= 10:
        if condition["type"] == "precip_any":
            ens_prob = sum(1 for p in precip_members if p > 0.01) / len(precip_members)
        else:
            thresh = condition["threshold"]
            ens_prob = sum(1 for p in precip_members if p > thresh) / len(
                precip_members
            )

    # ── Forecast precip as fallback ───────────────────────────────────────────
    forecast_precip = forecast.get("precip_in", 0.0) or 0.0
    if ens_prob is None:
        # Normal distribution around forecast precip
        sigma = max(0.2, forecast_precip * 0.5)
        if condition["type"] == "precip_any":
            ens_prob = 1.0 - normal_cdf(0.01, forecast_precip, sigma)
        else:
            ens_prob = 1.0 - normal_cdf(condition["threshold"], forecast_precip, sigma)

    # ── Same-day live precipitation observation override ─────────────────────
    obs_precip_val: float | None = None
    if days_out == 0:
        try:
            from nws import get_live_precip_obs

            obs_precip_raw = get_live_precip_obs(enriched.get("_city", ""), coords)
            if obs_precip_raw is not None:
                obs_precip_val = obs_precip_raw
        except Exception:
            pass

    # ── Dynamic blend weights (mirrors temperature path) ─────────────────────
    w_ens, w_clim, _ = _blend_weights(days_out, has_nws=False, has_clim=True)
    clim_prior = 0.30  # rough historical rain frequency as fallback prior
    blended_prob = ens_prob * w_ens + clim_prior * w_clim

    # Same-day override: observation is near-certain (precip already fell or didn't)
    if obs_precip_val is not None:
        if condition["type"] == "precip_any":
            obs_p = 1.0 if obs_precip_val > 0.01 else 0.0
        else:
            obs_p = 1.0 if obs_precip_val > condition.get("threshold", 0.0) else 0.0
        blended_prob = 0.90 * obs_p + 0.10 * blended_prob

    # ── Bias correction from tracker (same as temperature path) ──────────────
    bias = 0.0
    try:
        from tracker import get_bias

        city = enriched.get("_city")
        bias = get_bias(city, target_date.month)
        blended_prob = blended_prob - bias
    except Exception:
        pass

    blended_prob = max(0.01, min(0.99, blended_prob))

    prices = parse_market_price(enriched)
    market_prob = prices["implied_prob"]
    rec_side = "yes" if blended_prob > market_prob else "no"
    entry_price = prices["yes_ask"] if rec_side == "yes" else prices["no_bid"]
    if entry_price == 0:
        entry_price = 1 - market_prob if rec_side == "no" else market_prob

    payout = 1 - entry_price
    p_win = blended_prob if rec_side == "yes" else 1 - blended_prob
    net_ev = p_win * payout * (1 - KALSHI_FEE_RATE) - (1 - p_win) * entry_price
    net_edge = net_ev / entry_price if entry_price > 0 else 0.0
    edge = blended_prob - market_prob
    kelly = kelly_fraction(p_win, entry_price)
    fee_kel = kelly_fraction(p_win, entry_price, fee_rate=KALSHI_FEE_RATE)

    # ── Bootstrap CI on precip ensemble ──────────────────────────────────────
    ci_low, ci_high = blended_prob, blended_prob
    if len(precip_members) >= 5:
        ci_low, ci_high = _bootstrap_ci_precip(precip_members, condition)

    return {
        "forecast_prob": blended_prob,
        "market_prob": market_prob,
        "edge": edge,
        "signal": _edge_label(edge),
        "net_edge": net_edge,
        "net_signal": _edge_label(net_edge),
        "recommended_side": rec_side,
        "condition": condition,
        "forecast_temp": forecast_precip,  # precipitation in inches (reuses key for table display)
        "ensemble_prob": ens_prob,
        "nws_prob": None,
        "clim_prob": None,
        "clim_adj_prob": None,
        "obs_prob": obs_precip_val,
        "live_obs": obs_precip_val,
        "index_adj": 0.0,
        "bias_correction": bias,
        "blend_sources": {"ensemble": w_ens, "climatology": w_clim},
        "method": "precip_ensemble" if precip_members else "precip_normal",
        "ensemble_stats": None,
        "n_members": len(precip_members),
        "ci_low": ci_low,
        "ci_high": ci_high,
        "ci_width": round(ci_high - ci_low, 4),
        "kelly": kelly,
        "fee_adjusted_kelly": fee_kel,
        "ci_adjusted_kelly": round(fee_kel * max(0.25, 1.0 - (ci_high - ci_low)), 6),
        "time_risk": "HIGH",
    }


def analyze_trade(enriched: dict) -> dict | None:
    """
    Full multi-source trade analysis pipeline:
      1. Ensemble probability (80+ members, ICON + GFS)
      2. NWS official forecast probability
      3. Climatological baseline (30yr history)
      4. Climate index adjustment (AO, NAO, ENSO) on climatology
      5. Live observation override for same-day markets
      6. Weighted blend by days-out
      7. Bias correction from tracker (if data available)
      8. Bootstrap confidence interval
      9. Kelly fraction
    """
    forecast = enriched.get("_forecast")
    target_date = enriched.get("_date")
    city = enriched.get("_city")
    hour = enriched.get("_hour")
    if not forecast or not target_date or not city:
        return None

    condition = _parse_market_condition(enriched)
    if not condition:
        return None

    coords = CITY_COORDS.get(city)
    if not coords:
        return None

    # ── Time-of-day risk assessment ──────────────────────────────────────────
    _tz = coords[2] if len(coords) > 2 else "UTC"
    time_risk_label, sigma_mult = _time_risk(enriched.get("close_time", ""), _tz)

    # ── Precipitation market fast-path ───────────────────────────────────────
    if condition["type"] in ("precip_above", "precip_any"):
        result = _analyze_precip_trade(
            enriched, forecast, condition, target_date, coords
        )
        if result is not None:
            result["time_risk"] = time_risk_label
        return result

    series = (enriched.get("series_ticker") or enriched.get("ticker", "")).upper()
    var = "min" if "LOW" in series else "max"
    condition["var"] = var

    forecast_temp = forecast["low_f"] if var == "min" else forecast["high_f"]
    if forecast_temp is None:
        return None

    days_out = max(0, (target_date - date.today()).days)

    # ── 1. Ensemble probability ──────────────────────────────────────────────
    temps = get_ensemble_temps(city, target_date, hour=hour, var=var)

    # For hourly markets, use ensemble mean of the hourly temps as forecast_temp
    # (daily high is misleading for e.g. "temp at 9am" markets)
    if hour is not None and len(temps) >= 5:
        forecast_temp = statistics.mean(temps)
    ens_stats = ensemble_stats(temps) if len(temps) >= 10 else None
    method = "normal_dist"
    ens_prob: float | None = None

    if len(temps) >= 10:
        method = "ensemble"
        if condition["type"] == "above":
            ens_prob = sum(1 for t in temps if t > condition["threshold"]) / len(temps)
        elif condition["type"] == "below":
            ens_prob = sum(1 for t in temps if t < condition["threshold"]) / len(temps)
        else:
            lo, hi = condition["lower"], condition["upper"]
            ens_prob = sum(1 for t in temps if lo <= t <= hi) / len(temps)
    else:
        sigma = _forecast_uncertainty(target_date) * sigma_mult
        ens_prob = _forecast_probability(condition, forecast_temp, sigma)

    # ── 2. NWS forecast probability ──────────────────────────────────────────
    _nws_prob: float | None = None
    try:
        _nws_prob = nws_prob(city, coords, target_date, condition)
    except Exception:
        pass

    # ── 3+4. Climatological probability + climate index adjustment ───────────
    clim_prob_raw: float | None = None
    index_adj: float = 0.0
    try:
        clim_prob_raw = climatological_prob(city, coords, target_date, condition)
        index_adj = temperature_adjustment(city, target_date)
    except Exception:
        pass

    # Apply index adjustment by shifting the effective threshold
    clim_prob: float | None = None
    if clim_prob_raw is not None:
        # Shift the condition threshold by the index adjustment and recompute
        adj_condition = dict(condition)
        if condition["type"] in ("above", "below"):
            adj_condition["threshold"] = condition["threshold"] - index_adj
        elif condition["type"] == "between":
            adj_condition["lower"] = condition["lower"] - index_adj
            adj_condition["upper"] = condition["upper"] - index_adj
        clim_prob = climatological_prob(city, coords, target_date, adj_condition)
        if clim_prob is None:
            clim_prob = clim_prob_raw

    # ── 5. Live observation override (same-day markets) ──────────────────────
    live_obs: dict | None = None
    obs_override: float | None = None
    if days_out == 0:
        try:
            live_obs = get_live_observation(city, coords)
            if live_obs:
                obs_override = obs_prob(live_obs, condition)
        except Exception:
            pass

    # ── 6. Weighted blend ────────────────────────────────────────────────────
    if obs_override is not None:
        # Same-day with live obs — trust almost entirely
        blended_prob = obs_override * 0.95 + (ens_prob or 0.5) * 0.05
        blend_sources = {"obs": 0.95, "ensemble": 0.05}
    else:
        w_ens, w_clim, w_nws = _blend_weights(
            days_out, _nws_prob is not None, clim_prob is not None
        )
        blended_prob = (
            w_ens * (ens_prob or 0.5)
            + w_clim * (clim_prob or 0.5)
            + w_nws * (_nws_prob or 0.5)
        )
        blend_sources = {"ensemble": w_ens, "climatology": w_clim, "nws": w_nws}

    # ── 7. Bias correction from tracker ─────────────────────────────────────
    bias = 0.0
    try:
        from tracker import get_bias

        bias = get_bias(city, target_date.month)
        blended_prob = max(0.01, min(0.99, blended_prob - bias))
    except Exception:
        pass

    # ── 8. Confidence interval (bootstrap on ensemble members) ───────────────
    ci_low, ci_high = (blended_prob, blended_prob)
    if temps:
        ci_low, ci_high = _bootstrap_ci(temps, condition)

    # ── 9. Data quality score ────────────────────────────────────────────────
    # 1.0 = all sources available; reduced by 0.25 per missing source.
    # Used to scale down Kelly sizing when we're flying partially blind.
    sources_available = sum(
        [
            ens_prob is not None,
            _nws_prob is not None,
            clim_prob is not None,
        ]
    )
    data_quality = round(sources_available / 3, 4)

    # Flag anomalously wide ensemble spread (models disagree strongly)
    anomalous = is_forecast_anomalous(ens_stats or {})

    # Log source availability for per-city reliability tracking
    try:
        from tracker import log_source_attempt as _log_src

        _log_src(city, "ensemble", ens_prob is not None)
        _log_src(city, "nws", _nws_prob is not None)
        _log_src(city, "climatology", clim_prob is not None)
    except Exception:
        pass

    # ── 10. Kelly fraction ───────────────────────────────────────────────────
    prices = parse_market_price(enriched)
    market_prob = prices["implied_prob"]
    rec_side = "yes" if blended_prob > market_prob else "no"
    entry_price = prices["yes_ask"] if rec_side == "yes" else prices["no_bid"]
    if entry_price == 0:
        entry_price = 1 - market_prob if rec_side == "no" else market_prob
    kelly = kelly_fraction(
        blended_prob if rec_side == "yes" else 1 - blended_prob, entry_price
    )

    # ── 10a. Bid-ask spread cost ─────────────────────────────────────────────
    # Wide spreads mean real slippage beyond the Kalshi fee.
    # Use the actual spread as a fraction of mid; default 5% for illiquid markets.
    yes_ask_p, yes_bid_p = prices["yes_ask"], prices["yes_bid"]
    if yes_ask_p > 0 and yes_bid_p > 0 and yes_ask_p > yes_bid_p:
        spread_abs = yes_ask_p - yes_bid_p
        mid_p = (yes_ask_p + yes_bid_p) / 2
        spread_cost = spread_abs / mid_p if mid_p > 0 else 0.05
    else:
        spread_cost = 0.05  # conservative default for markets with no live quote
    # A 5% spread → 10% reduction; 25% spread → 50% reduction; floor at 0.50
    spread_scale = max(0.50, 1.0 - spread_cost * 2)

    edge = blended_prob - market_prob
    signal = _edge_label(edge)

    # ── 11. Fee-adjusted edge ────────────────────────────────────────────────
    if rec_side == "yes":
        payout = 1 - entry_price
        net_ev = (
            blended_prob * payout * (1 - KALSHI_FEE_RATE)
            - (1 - blended_prob) * entry_price
        )
    else:
        payout = 1 - entry_price
        p_win = 1 - blended_prob
        net_ev = p_win * payout * (1 - KALSHI_FEE_RATE) - blended_prob * entry_price

    net_edge = net_ev / entry_price if entry_price > 0 else 0.0
    net_signal = _edge_label(net_edge)
    fee_adjusted_kelly = kelly_fraction(
        blended_prob if rec_side == "yes" else 1 - blended_prob,
        entry_price,
        fee_rate=KALSHI_FEE_RATE,
    )

    # Scale Kelly down for low data quality and anomalous forecasts
    quality_scale = 0.5 + 0.5 * data_quality  # 0.5 at quality=0, 1.0 at quality=1
    anomaly_scale = 0.70 if anomalous else 1.0
    ci_scale = max(0.25, 1.0 - (ci_high - ci_low))
    ci_adjusted_kelly = round(
        fee_adjusted_kelly * ci_scale * quality_scale * anomaly_scale * spread_scale, 6
    )

    return {
        # Core
        "forecast_prob": blended_prob,
        "market_prob": market_prob,
        "edge": edge,
        "signal": signal,
        "net_edge": net_edge,
        "net_signal": net_signal,
        "recommended_side": rec_side,
        "condition": condition,
        "forecast_temp": forecast_temp,
        # Sources
        "ensemble_prob": ens_prob,
        "nws_prob": _nws_prob,
        "clim_prob": clim_prob_raw,
        "clim_adj_prob": clim_prob,
        "obs_prob": obs_override,
        "live_obs": live_obs,
        "index_adj": index_adj,
        "bias_correction": bias,
        "blend_sources": blend_sources,
        "method": method,
        # Ensemble details
        "ensemble_stats": ens_stats,
        "n_members": len(temps),
        # Confidence + sizing
        "ci_low": ci_low,
        "ci_high": ci_high,
        "ci_width": ci_high - ci_low,
        "kelly": kelly,
        "fee_adjusted_kelly": fee_adjusted_kelly,
        "ci_adjusted_kelly": ci_adjusted_kelly,
        "time_risk": time_risk_label,
        # Data quality
        "data_quality": data_quality,
        "forecast_anomalous": anomalous,
        "spread_cost": round(spread_cost, 4),
        "spread_scale": round(spread_scale, 4),
    }
