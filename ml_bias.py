"""
ML-based probability calibration — GradientBoosting per-city correction of our_prob toward true outcome frequency.
Requires 200+ settled predictions per city to outperform static bias table.
Train: python main.py train-bias
"""

from __future__ import annotations

import hashlib
import hmac as _hmac_mod
import logging
import os
import pickle
from pathlib import Path

_log = logging.getLogger(__name__)
_MODEL_PATH = Path(__file__).parent / "data" / "bias_models.pkl"
_HMAC_PATH = Path(__file__).parent / "data" / ".bias_models.hmac"
_MODELS_CACHE: dict | None = None


def _hmac_secret() -> bytes:
    """Return the HMAC secret from env. Empty string disables verification (dev only)."""
    return os.getenv("MODEL_HMAC_SECRET", "").encode()


def _compute_hmac(data: bytes) -> str:
    """Compute HMAC-SHA256 of data using MODEL_HMAC_SECRET."""
    secret = _hmac_secret()
    if not secret:
        raise RuntimeError(
            "MODEL_HMAC_SECRET must be set in .env before loading bias models."
        )
    return _hmac_mod.new(secret, data, hashlib.sha256).hexdigest()


def _write_hmac(pkl_bytes: bytes) -> None:
    """Write HMAC sidecar for a freshly serialised pickle."""
    _HMAC_PATH.parent.mkdir(exist_ok=True)
    _HMAC_PATH.write_text(_compute_hmac(pkl_bytes))


def _load_models() -> dict:
    """Load bias models from disk after HMAC verification.

    Refuses to deserialise if:
    - MODEL_HMAC_SECRET is not set (would skip verification)
    - The .hmac sidecar is missing
    - The HMAC does not match (file may be tampered)

    In all rejection cases returns {} so the caller falls back to no
    bias correction rather than loading a potentially malicious payload.
    """
    global _MODELS_CACHE
    if _MODELS_CACHE is not None:
        return _MODELS_CACHE
    if not _MODEL_PATH.exists():
        return {}

    secret = _hmac_secret()
    if not secret:
        _log.warning(
            "ml_bias: MODEL_HMAC_SECRET not set — skipping bias models (RCE risk)."
        )
        _MODELS_CACHE = {}
        return {}

    try:
        raw = _MODEL_PATH.read_bytes()

        if not _HMAC_PATH.exists():
            _log.error(
                "ml_bias: %s missing — refusing to load pkl (RCE risk). "
                "Retrain to regenerate both files.",
                _HMAC_PATH.name,
            )
            _MODELS_CACHE = {}
            return {}

        expected = _HMAC_PATH.read_text().strip()
        actual = _compute_hmac(raw)

        if not _hmac_mod.compare_digest(expected, actual):
            _log.error(
                "ml_bias: HMAC mismatch on %s — file may be tampered. "
                "Skipping bias correction.",
                _MODEL_PATH.name,
            )
            _MODELS_CACHE = {}
            return {}

        # HMAC verified — safe to deserialise
        _MODELS_CACHE = pickle.loads(raw)  # noqa: S301 (verified above)
        return _MODELS_CACHE

    except Exception as exc:
        _log.warning("ml_bias: load failed: %s — using no correction", exc)
        _MODELS_CACHE = {}
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
        pkl_bytes = pickle.dumps(models)
        _MODEL_PATH.write_bytes(pkl_bytes)
        try:
            _write_hmac(pkl_bytes)
            _log.info("ml_bias: wrote HMAC sidecar to %s", _HMAC_PATH.name)
        except RuntimeError as hmac_err:
            _log.warning(
                "ml_bias: could not write HMAC (%s) — set MODEL_HMAC_SECRET in .env",
                hmac_err,
            )
        global _MODELS_CACHE
        _MODELS_CACHE = models
        _log.info("ml_bias: saved %d city models to %s", len(models), _MODEL_PATH)

    return models


def _logit(p: float) -> float:
    import math

    p = max(1e-6, min(1 - 1e-6, p))
    return math.log(p / (1 - p))


def _sigmoid(x: float) -> float:
    import math

    return 1.0 / (1.0 + math.exp(-x))


def _fit_platt(xs: list[float], ys: list[int]) -> tuple[float, float]:
    """Fit Platt scaling (A, B) via cross-entropy minimisation with scipy."""
    import numpy as np
    from scipy.optimize import minimize  # type: ignore[import-untyped]

    xa = np.array(xs, dtype=float)
    ya = np.array(ys, dtype=float)

    def neg_log_likelihood(params: np.ndarray) -> float:
        a, b = params
        p = 1.0 / (1.0 + np.exp(-(a * xa + b)))
        p = np.clip(p, 1e-9, 1 - 1e-9)
        return -float(np.sum(ya * np.log(p) + (1 - ya) * np.log(1 - p)))

    res = minimize(neg_log_likelihood, x0=[1.0, 0.0], method="L-BFGS-B")
    return float(res.x[0]), float(res.x[1])


def train_platt_per_city(
    rows: list[dict],
    min_samples: int = 200,
) -> dict[str, tuple[float, float]]:
    """
    Train per-city Platt scaling: fits (A, B) via cross-entropy on logit(p).
    Returns {city: (A, B)} where calibrated_prob = sigmoid(A * logit(p) + B).
    Skips cities with fewer than min_samples settled predictions.
    """
    from collections import defaultdict

    by_city: dict[str, list] = defaultdict(list)
    for r in rows:
        city, p, y = r.get("city"), r.get("our_prob"), r.get("settled_yes")
        if city and p is not None and y is not None:
            try:
                by_city[city].append((_logit(float(p)), int(y)))
            except (ValueError, TypeError):
                pass

    result: dict[str, tuple[float, float]] = {}
    for city, samples in by_city.items():
        if len(samples) < min_samples:
            continue
        try:
            xs = [x for x, _ in samples]
            ys = [label for _, label in samples]
            result[city] = _fit_platt(xs, ys)
        except Exception:
            pass

    return result


def apply_platt_per_city(
    city: str,
    raw_prob: float,
    models: dict[str, tuple[float, float]],
) -> float:
    """Apply per-city Platt calibration; returns raw_prob unchanged if no model."""
    if city not in models:
        return raw_prob
    a, b = models[city]
    return _sigmoid(a * _logit(raw_prob) + b)


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


def has_ml_model(city: str) -> bool:
    """Return True if a trained GBM correction model exists for this city."""
    return _load_models().get(city.upper()) is not None
