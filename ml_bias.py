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
_TEMP_PATH = Path(__file__).parent / "data" / "temperature_scale.json"
_MODELS_CACHE: dict | None = None
_LOAD_ATTEMPTED: bool = False  # True only after a successful or definitive load
_TEMP_CACHE: float | None = None


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

    Uses _LOAD_ATTEMPTED to distinguish "loaded successfully, no models found" ({})
    from "never loaded yet" (None). Transient failures (missing secret at early startup)
    do NOT permanently poison the cache — the next call will retry.
    """
    global _MODELS_CACHE, _LOAD_ATTEMPTED
    if _LOAD_ATTEMPTED:
        return _MODELS_CACHE if _MODELS_CACHE is not None else {}
    if not _MODEL_PATH.exists():
        # File absent is definitive — mark attempted so we don't re-check every call.
        _LOAD_ATTEMPTED = True
        _MODELS_CACHE = {}
        return {}

    secret = _hmac_secret()
    if not secret:
        # Secret missing is likely a transient startup ordering issue — do NOT set
        # _LOAD_ATTEMPTED so the next call retries once the env is populated.
        _log.warning(
            "ml_bias: MODEL_HMAC_SECRET not set — skipping bias models (RCE risk)."
        )
        return {}

    try:
        raw = _MODEL_PATH.read_bytes()

        if not _HMAC_PATH.exists():
            _log.error(
                "ml_bias: %s missing — refusing to load pkl (RCE risk). "
                "Retrain to regenerate both files.",
                _HMAC_PATH.name,
            )
            _LOAD_ATTEMPTED = True
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
            _LOAD_ATTEMPTED = True
            _MODELS_CACHE = {}
            return {}

        # HMAC verified — safe to deserialise
        _MODELS_CACHE = pickle.loads(raw)  # noqa: S301 (verified above)
        _LOAD_ATTEMPTED = True
        return _MODELS_CACHE if isinstance(_MODELS_CACHE, dict) else {}

    except Exception as exc:
        _log.warning("ml_bias: load failed: %s — will retry on next call", exc)
        # Do NOT set _LOAD_ATTEMPTED — transient I/O errors should not permanently
        # disable correction for the process lifetime.
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
                    CAST(julianday(date(p.market_date)) - julianday(date(p.predicted_at)) AS INTEGER) AS days_out,
                    o.settled_yes
                FROM predictions p
                JOIN outcomes o ON p.ticker = o.ticker
                WHERE p.city IS NOT NULL AND p.our_prob IS NOT NULL
                ORDER BY p.predicted_at ASC
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

        # 80/20 temporal holdout — skip city if model doesn't beat zero-correction
        _split = int(len(X) * 0.80)
        X_train, X_val = X[:_split], X[_split:]
        y_train, y_val = y[:_split], y[_split:]

        try:
            model = GradientBoostingRegressor(
                n_estimators=50, max_depth=2, min_samples_leaf=10
            )
            model.fit(X_train, y_train)

            if X_val:
                _preds = model.predict(X_val)
                _model_mse = sum((p - a) ** 2 for p, a in zip(_preds, y_val)) / len(
                    y_val
                )
                _baseline_mse = sum(a**2 for a in y_val) / len(y_val)
                if _model_mse >= _baseline_mse:
                    _log.warning(
                        "ml_bias: %s holdout MSE %.4f >= baseline %.4f — skipping save",
                        city,
                        _model_mse,
                        _baseline_mse,
                    )
                    continue

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
    if not res.success:
        raise ValueError(f"Platt optimizer did not converge: {res.message}")
    a, b = float(res.x[0]), float(res.x[1])
    if a <= 0 or abs(a) > 5 or abs(b) > 5:
        raise ValueError(
            f"Platt fit produced invalid coefficients A={a:.4f}, B={b:.4f}; "
            "expected A>0, |A|<=5, |B|<=5"
        )
    return a, b


def train_platt_per_city(
    rows: list[dict],
    min_samples: int = 15,
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


def _load_temperature_scale() -> float | None:
    global _TEMP_CACHE
    if _TEMP_CACHE is not None:
        return _TEMP_CACHE
    if not _TEMP_PATH.exists():
        return None
    try:
        import json

        data = json.loads(_TEMP_PATH.read_text())
        _TEMP_CACHE = float(data["T"])
        return _TEMP_CACHE
    except Exception:
        return None


def train_temperature_scaling(min_samples: int = 50) -> float | None:
    """Fit global temperature T via log-loss minimisation on all settled predictions.

    Calibrated prob = sigmoid(logit(raw_prob) / T).  T > 1 compresses
    overconfident predictions toward 0.5.  Saves to data/temperature_scale.json.
    """
    import tracker

    tracker.init_db()
    try:
        with tracker._conn() as con:
            rows = con.execute(
                "SELECT p.our_prob, o.settled_yes FROM predictions p "
                "JOIN outcomes o ON p.ticker = o.ticker "
                "WHERE p.our_prob IS NOT NULL AND o.settled_yes IS NOT NULL"
            ).fetchall()
    except Exception as exc:
        _log.warning("train_temperature_scaling: DB query failed: %s", exc)
        return None

    if len(rows) < min_samples:
        _log.info(
            "train_temperature_scaling: only %d samples, need %d",
            len(rows),
            min_samples,
        )
        return None

    try:
        import json

        import numpy as np
        from scipy.optimize import minimize_scalar  # type: ignore[import-untyped]

        probs = np.clip([float(p) for p, _ in rows], 1e-6, 1 - 1e-6)
        labels = np.array([float(y) for _, y in rows])
        logits = np.log(probs / (1 - probs))

        def neg_log_likelihood(T: float) -> float:
            if T <= 0:
                return 1e9
            p_cal = np.clip(1.0 / (1.0 + np.exp(-logits / T)), 1e-9, 1 - 1e-9)
            return -float(
                np.sum(labels * np.log(p_cal) + (1 - labels) * np.log(1 - p_cal))
            )

        result = minimize_scalar(
            neg_log_likelihood, bounds=(0.1, 5.0), method="bounded"
        )
        T = float(result.x)

        _TEMP_PATH.parent.mkdir(exist_ok=True)
        _TEMP_PATH.write_text(json.dumps({"T": T, "n_samples": len(rows)}))
        global _TEMP_CACHE
        _TEMP_CACHE = T
        _log.info("train_temperature_scaling: T=%.4f on %d samples", T, len(rows))
        return T

    except ImportError:
        _log.warning("train_temperature_scaling: scipy/numpy not installed")
        return None
    except Exception as exc:
        _log.warning("train_temperature_scaling: fitting failed: %s", exc)
        return None


def apply_temperature_scaling(prob: float) -> float:
    """Apply global temperature calibration; returns prob unchanged if no model trained."""
    T = _load_temperature_scale()
    if T is None or abs(T - 1.0) < 0.01:
        return prob
    return _sigmoid(_logit(prob) / T)
