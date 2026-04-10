"""
Weather regime detection — identifies when a city is in a persistent anomalous
weather pattern (blocking high, cold snap, heat dome) that makes forecasts
more reliable despite wide ensemble spread.
"""

from __future__ import annotations


def detect_regime(city: str, ensemble_stats: dict, days_out: int) -> dict:
    """
    Detect the current weather regime for a city based on ensemble statistics.

    Args:
        city: City name (e.g. "NYC")
        ensemble_stats: Dict from weather_markets.ensemble_stats()
                        {mean, std, min, max, p10, p90, n}
        days_out: How many days until the market settles

    Returns:
        {
          "regime": str,            # "heat_dome" | "cold_snap" | "blocking_high"
                                    # | "normal" | "volatile"
          "confidence_boost": float, # multiplier for ci_adjusted_kelly
          "description": str,
        }

    Detection logic:
        heat_dome:     mean > 95°F AND std < 5°F  (hot and certain)
        cold_snap:     mean < 25°F AND std < 5°F  (cold and certain)
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

    if mean > 95.0 and std < 5.0:
        return {
            "regime": "heat_dome",
            "confidence_boost": round(_boost(1.20), 4),
            "description": (
                f"Heat dome detected for {city} ({mean:.1f}°F mean, "
                f"σ={std:.1f}°F) — high confidence pattern."
            ),
        }
    elif mean < 25.0 and std < 5.0:
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
