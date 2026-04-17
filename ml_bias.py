"""
ML-based probability calibration — GradientBoosting per-city correction of our_prob toward true outcome frequency.
Requires 200+ settled predictions per city to outperform static bias table.
Train: python main.py train-bias
"""

from __future__ import annotations

import logging
import pickle
from pathlib import Path

_log = logging.getLogger(__name__)
_MODEL_PATH = Path(__file__).parent / "data" / "bias_models.pkl"
_MODELS_CACHE: dict | None = None


def _load_models() -> dict:
    global _MODELS_CACHE
    if _MODELS_CACHE is not None:
        return _MODELS_CACHE
    if not _MODEL_PATH.exists():
        return {}
    try:
        with open(_MODEL_PATH, "rb") as f:
            _MODELS_CACHE = pickle.load(f)
            return _MODELS_CACHE
    except Exception as exc:
        _log.debug("ml_bias: load failed: %s", exc)
        return {}


def train_bias_model(min_samples: int = 200) -> dict:
    """
    Train a bias correction model per city from tracker DB data.
    Saves models to data/bias_models.pkl.
    Returns dict of {city: model} for cities with enough data.
    """
    try:
        from sklearn.ensemble import GradientBoostingRegressor
    except ImportError:
        _log.warning(
            "ml_bias: scikit-learn not installed. Run: pip install scikit-learn"
        )
        return {}

    import tracker

    tracker.init_db()

    city_data: dict[str, list] = {}
    try:
        with tracker._conn() as con:
            rows = con.execute(
                """
                SELECT
                    p.city, p.our_prob,
                    CAST(strftime('%m', p.market_date) AS INTEGER) AS month,
                    CAST(julianday(p.market_date) - julianday(p.predicted_at) AS INTEGER) AS days_out,
                    o.settled_yes
                FROM predictions p
                JOIN outcomes o ON p.ticker = o.ticker
                WHERE p.city IS NOT NULL AND p.our_prob IS NOT NULL
                """
            ).fetchall()
    except Exception as exc:
        _log.warning("ml_bias: DB query failed: %s", exc)
        return {}

    for city, our_prob, month, days_out, settled_yes in rows:
        if city not in city_data:
            city_data[city] = []
        actual = 1.0 if settled_yes else 0.0
        city_data[city].append(
            {
                "our_prob": float(our_prob or 0),
                "month": int(month or 1),
                "days_out": max(0, int(days_out or 1)),
                "actual": actual,
            }
        )

    models = {}
    for city, samples in city_data.items():
        if len(samples) < min_samples:
            _log.debug(
                "ml_bias: %s has %d samples, need %d", city, len(samples), min_samples
            )
            continue

        X = [[s["our_prob"], s["month"], s["days_out"], 0.0] for s in samples]
        y = [s["actual"] - s["our_prob"] for s in samples]

        try:
            model = GradientBoostingRegressor(n_estimators=100, max_depth=3)
            model.fit(X, y)
            models[city.upper()] = model
            _log.info("ml_bias: trained model for %s on %d samples", city, len(samples))
        except Exception as exc:
            _log.warning("ml_bias: training failed for %s: %s", city, exc)

    if models:
        _MODEL_PATH.parent.mkdir(exist_ok=True)
        with open(_MODEL_PATH, "wb") as f:
            pickle.dump(models, f)
        global _MODELS_CACHE
        _MODELS_CACHE = models
        _log.info("ml_bias: saved %d city models to %s", len(models), _MODEL_PATH)

    return models


def apply_ml_prob_correction(
    city: str,
    our_prob: float,
    month: int,
    days_out: int,
) -> float:
    """
    Apply ML-based probability calibration correction.
    The model predicts (actual - our_prob) residuals; we add that correction
    and clamp to [0.0, 1.0].
    Falls back to our_prob unchanged if no model exists for the city.
    """
    models = _load_models()
    model = models.get(city.upper())
    if model is None:
        return our_prob

    try:
        correction = float(model.predict([[our_prob, month, days_out, 0.0]])[0])
        return max(0.0, min(1.0, our_prob + correction))
    except Exception as exc:
        _log.debug("apply_ml_prob_correction(%s): %s", city, exc)
        return our_prob
