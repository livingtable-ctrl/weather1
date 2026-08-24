"""
Weather regime detection — identifies when a city is in a persistent anomalous
weather pattern (blocking high, cold snap, heat dome) that makes forecasts
more reliable despite wide ensemble spread.
"""

from __future__ import annotations

import logging
from datetime import date

_log = logging.getLogger(__name__)

# M-31: how many climatological standard deviations above/below a city's own
# seasonal normal the ensemble mean must clear before heat_dome/cold_snap can
# fire. Without this, the absolute mean>95/mean<25 thresholds below fire on
# ROUTINE days for hot/cold-normal cities (e.g. Phoenix/Vegas summer highs
# >95F are typical, not extreme) — this additionally requires the forecast to
# be unusual FOR THAT CITY/SEASON, not just absolutely hot/cold.
_REGIME_ANOMALY_SIGMA = 1.5


def _climatologically_confirmed(
    city: str,
    coords: tuple | None,
    target_date: date | None,
    var: str,
    mean: float,
    hot: bool,
) -> bool:
    """True when a heat_dome/cold_snap candidate is confirmed as climatologically
    unusual, or when the caller didn't supply climatology context at all.

    coords/target_date being None means the caller can't provide climatology
    context (e.g. existing tests, or a future caller without coordinates) —
    that preserves the OLD absolute-threshold-only behavior rather than
    silently disabling heat_dome/cold_snap for every such caller.

    When context IS supplied, this fails CLOSED: a lookup failure or
    insufficient historical data (climatological_normal returns None) does
    NOT confirm the regime — an unvalidated extreme-regime Kelly boost must
    not be granted just because climatology was unreachable.
    """
    if coords is None or target_date is None:
        return True
    try:
        from climatology import climatological_normal

        normal = climatological_normal(city, coords, target_date, var)
    except Exception as exc:
        _log.warning("regime: climatological_normal raised for %s: %s", city, exc)
        return False
    if normal is None:
        return False
    normal_mean, normal_std = normal
    if normal_std <= 0:
        return False
    z = (mean - normal_mean) / normal_std
    return z >= _REGIME_ANOMALY_SIGMA if hot else z <= -_REGIME_ANOMALY_SIGMA


def detect_regime(
    city: str,
    ensemble_stats: dict,
    days_out: int,
    coords: tuple | None = None,
    target_date: date | None = None,
    var: str = "max",
) -> dict:
    """
    Detect the current weather regime for a city based on ensemble statistics.

    Args:
        city: City name (e.g. "NYC")
        ensemble_stats: Dict from weather_markets.ensemble_stats()
                        {mean, std, min, max, p10, p90, n}
        days_out: How many days until the market settles
        coords: (lat, lon, tz) for the city, or None to skip the M-31
                climatological-anomaly confirmation (see _climatologically_confirmed).
        target_date: Market settlement date, or None to skip the confirmation.
        var: "max" or "min" — which climatology series (highs/lows) the
             ensemble_stats mean represents. Only used when coords/target_date
             are also supplied.

    Returns:
        {
          "regime": str,            # "heat_dome" | "cold_snap" | "blocking_high"
                                    # | "normal" | "volatile"
          "confidence_boost": float, # multiplier for ci_adjusted_kelly
          "description": str,
        }

    Detection logic:
        heat_dome:     mean > 95°F AND std < 5°F, AND (when coords/target_date
                       given) mean is >= 1.5 climatological std-devs above the
                       city's seasonal normal (hot and certain and unusual)
        cold_snap:     mean < 25°F AND std < 5°F, AND the symmetric climatological
                       confirmation (cold and certain and unusual)
        blocking_high: std < 3°F                  (very low spread = persistent pattern)
        volatile:      std > 12°F                 (high spread = chaotic atmosphere)
        normal:        everything else
    """
    if not ensemble_stats:
        return {
            "regime": "normal",
            "confidence_boost": 1.0,
            "description": "No ensemble data — standard confidence.",
        }

    if days_out is None:
        days_out = 0

    mean = ensemble_stats.get("mean", 60.0)
    std = ensemble_stats.get("std", 5.0)

    # Scale confidence boost by forecast horizon — regimes are less reliable far out.
    # Full boost within 3 days; linearly reduces to no boost (1.0) beyond 10 days.
    horizon_scale = (
        max(0.0, min(1.0, 1.0 - (days_out - 3) / 7.0)) if days_out > 3 else 1.0
    )

    def _boost(base: float) -> float:
        """Scale boost towards 1.0 based on how far out the market is."""
        return 1.0 + (base - 1.0) * horizon_scale

    if (
        mean > 95.0
        and std < 5.0
        and _climatologically_confirmed(city, coords, target_date, var, mean, hot=True)
    ):
        return {
            "regime": "heat_dome",
            "confidence_boost": round(_boost(1.20), 4),
            "description": (
                f"Heat dome detected for {city} ({mean:.1f}°F mean, "
                f"σ={std:.1f}°F) — high confidence pattern."
            ),
        }
    elif (
        mean < 25.0
        and std < 5.0
        and _climatologically_confirmed(city, coords, target_date, var, mean, hot=False)
    ):
        return {
            "regime": "cold_snap",
            "confidence_boost": round(_boost(1.20), 4),
            "description": (
                f"Cold snap detected for {city} ({mean:.1f}°F mean, "
                f"σ={std:.1f}°F) — high confidence pattern."
            ),
        }
    elif std < 3.0:
        return {
            "regime": "blocking_high",
            "confidence_boost": round(_boost(1.15), 4),
            "description": (
                f"Blocking high detected for {city} (σ={std:.1f}°F) — "
                f"very persistent pattern, elevated confidence."
            ),
        }
    elif std > 12.0:
        return {
            "regime": "volatile",
            "confidence_boost": round(_boost(0.80), 4),
            "description": (
                f"Volatile atmosphere for {city} (σ={std:.1f}°F) — "
                f"wide model spread, reduced confidence."
            ),
        }
    else:
        return {
            "regime": "normal",
            "confidence_boost": 1.0,
            "description": (
                f"Normal regime for {city} ({mean:.1f}°F mean, σ={std:.1f}°F)."
            ),
        }
