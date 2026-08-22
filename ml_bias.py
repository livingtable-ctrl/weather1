"""
ML-based probability calibration — GradientBoosting per-city correction of our_prob toward true outcome frequency.
Requires 200+ settled predictions per city to outperform static bias table.
Train: python main.py train-bias
"""

from __future__ import annotations

import hashlib
import hmac as _hmac_mod
import json
import logging
import math
import os
import pickle
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np

from paths import EMOS_PARAMS_PATH as _EMOS_PARAMS_PATH
from paths import METAR_CALIBRATION_PATH as _METAR_CALIBRATION_PATH
from paths import ML_BIAS_HMAC_PATH as _HMAC_PATH
from paths import ML_BIAS_MODEL_PATH as _MODEL_PATH
from paths import TEMPERATURE_SCALE_PATH as _TEMP_PATH
from paths import TEMPERATURE_SCALE_PRE_EMOS_PATH as _TEMP_PRE_EMOS_SNAPSHOT_PATH

_log = logging.getLogger(__name__)
_EMOS_CACHE: tuple | None = None  # cached (a, b, c, d)
# mtime the cache above was loaded from -- checked on every _load_emos_params()
# call so a long-running process (loop/watch) picks up an activate/deactivate
# made by a separate CLI invocation within its next call, not just at first
# load. Without this, deactivate_emos() clearing the cache in the CLI
# process's own memory has no effect on an already-running trading loop.
_EMOS_CACHE_MTIME: float | None = None
_MODELS_CACHE: dict | None = None
_LOAD_ATTEMPTED: bool = False  # True only after a successful or definitive load
_TEMP_CACHE: dict | None = (
    None  # {condition_key: T} where condition_key is "global"|"between"|"above"|"below"
)
_TEMP_CACHE_MTIME: float | None = (
    None  # same mtime-invalidation reasoning as _EMOS_CACHE_MTIME
)
# Condition types EMOS's fit actually covers -- must stay in sync with
# weather_markets.py's _ensemble_probability_core, which calls
# emos_exceedance_prob for above/below and emos_interval_prob for between.
EMOS_COVERED_CONDITION_KEYS = ("global", "above", "below", "between")
# T priors for above/below markets.  Applied when temperature_scale.json is missing
# or lacks a condition-specific entry.  Derived empirically by reblending N=14 trades
# with current weights and grid-searching for NLL minimum (Jun 2026):
#   below optimal T ≈ 2.8  (T=6.0 prior was set before weight fix; now too aggressive)
#   above optimal T ≈ 8.0  (hits upper bound — blend is overconfident; T=6 practical)
_T_BELOW_PRIOR: float = 3.0
_T_ABOVE_PRIOR: float = 6.0


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
        return (
            _MODELS_CACHE if isinstance(_MODELS_CACHE, dict) else {}
        )  # CR-5: same guard as first-call path
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
        if not isinstance(_MODELS_CACHE, dict):
            _log.warning(
                "ml_bias: %s deserialised to %s, not dict — discarding",
                _MODEL_PATH.name,
                type(_MODELS_CACHE).__name__,
            )
            _MODELS_CACHE = {}
        return _MODELS_CACHE

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
                FROM multiday_predictions p
                JOIN outcomes_valid o ON p.ticker = o.ticker
                WHERE p.city IS NOT NULL AND p.our_prob IS NOT NULL
                  AND (p.condition_type IS NULL
                       OR p.condition_type NOT IN
                          ('between', 'precip_month_total', 'snow_month_total', 'hurricane_count', 'hurricane_next_event', 'storm_order'))
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

    global _MODELS_CACHE, _LOAD_ATTEMPTED
    # M-17: always reset so next _load_models() re-reads from disk, even if retrain
    # produced zero models (e.g. all cities failed the holdout gate).
    _MODELS_CACHE = None
    _LOAD_ATTEMPTED = False

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
        _log.info("ml_bias: saved %d city models to %s", len(models), _MODEL_PATH)

    return models


def _logit(p: float) -> float:
    import math

    p = max(1e-6, min(1 - 1e-6, p))
    return math.log(p / (1 - p))


def _sigmoid(x: float) -> float:
    """Numerically stable sigmoid -- branches on the sign of x so math.exp
    never receives an argument large enough to raise OverflowError (plain
    1/(1+exp(-x)) blows up for x <~ -745; verified this is reachable, not
    hypothetical, from apply_metar_calibration on an unvalidated/adversarial
    coefficient set)."""
    import math

    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


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
        except Exception as _exc:
            _log.warning(
                "train_platt_per_city: fit failed for %s (%d samples): %s",
                city,
                len(samples),
                _exc,
            )

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


# Minimum settled predictions in the MINORITY class (not raw row count)
# before a METAR calibration fit is trusted -- Peduzzi et al. 1996's
# events-per-variable (EPV) rule for logistic regression: >=10 events in the
# minority class per fitted predictor (not counting the intercept). Platt
# scaling (see fit_metar_calibration below) fits exactly 1 predictor
# (logit(s)), so the floor is min(n_pos, n_neg) >= 10.
#
# An earlier version of this floor used a flat n>=30 raw-row-count
# threshold, framed as "Gneiting 2005's 10-per-parameter rule" for what was
# then a 3-parameter beta-calibration fit. Two independent opus reviews
# (2026-08-16) caught this was wrong on two counts: Gneiting 2005 is a
# continuous-outcome ensemble-calibration heuristic (used correctly
# elsewhere in this file for EMOS), not a classification EPV rule; and even
# taken at face value, EPV must be counted on the minority class, not raw n
# -- this repo's real 33-row dataset has only 11 in the minority class
# (settled_yes=0), so a flat n>=30 floor would pass data that's actually
# thin by the standard it claims to cite.
METAR_CALIBRATION_MIN_EPV_PER_PREDICTOR = 10


def fit_metar_calibration(rows: list[dict]) -> tuple[float, float, float] | None:
    """Fit Platt scaling on METAR same-day lock-in predictions, returned as
    a (a, a, c) triple -- mathematically identical to Platt scaling
    (sigmoid(a*ln(s) - a*ln(1-s) + c) == sigmoid(a*logit(s) + c) when the
    two coefficients are equal), kept in this 3-tuple shape purely so
    apply_metar_calibration's call signature and the on-disk JSON schema
    don't need to change.

    An earlier version of this function fit full 2-parameter beta
    calibration (Kull, Silva Filho & Flach, AISTATS 2017:
    sigmoid(a*ln(s) - b*ln(1-s) + c), weighting "evidence toward YES" and
    "evidence toward NO" separately -- the theoretically right shape for
    METAR lock-in's measured asymmetric miscalibration), falling back to
    Platt when the full fit degenerated. Two independent opus reviews
    (2026-08-16) found this was the wrong DESIGN, not just a buggy
    implementation of a good one:
      - ln(s) and ln(1-s) are deterministic functions of each other, and
        METAR lock-in scores cluster in two narrow bands ([0.72,0.97] for
        YES-locks, [0.03,0.28] for NO-locks) -- identifying genuine
        asymmetry needs curvature WITHIN each band, which this scoring
        distribution barely provides regardless of sample size.
        Empirically: even at n=400 with deliberately asymmetric synthetic
        miscalibration, the full 2-parameter fit degenerated to the
        Platt-equivalent a=b solution in 6 of 8 random seeds.
      - The full-fit path had no regularization, so a real, plausible
        perfect-separation sample produced unregularized coefficients that
        passed every positivity/magnitude guard and forced maximum-
        confidence (0.01/0.99) corrections from a nonexistent MLE.
      - The degenerate-case fallback went through two unsafe designs before
        landing on "fall back to Platt": pinning the offending coefficient
        at a fixed 1.0 acts as an offset term in the log-likelihood and
        distorts the other coefficient's sign too (verified on this repo's
        real data). But "fall back to Platt from a fit that degenerates
        most of the time anyway" means Platt WAS effectively the primary
        path, just reached through a lot of fragile, unregularized,
        two-optimizer machinery first.
    Fitting Platt directly reuses `_fit_platt`'s existing, already-validated
    bounds (raises if a<=0, |a|>5, or |b|>5) -- closing the separation/
    blowup risk for free -- and is what the real production data (2026-08-16:
    27 YES-locks, 6 NO-locks) already converges to.

    `rows` is [{"our_prob": float, "settled_yes": 0|1}, ...] -- same shape
    as get_emos_training_data()'s rows. Returns None if the minority class
    is below METAR_CALIBRATION_MIN_EPV_PER_PREDICTOR, if any settled_yes
    value isn't exactly 0 or 1 (a corrupted label must not silently distort
    the fit rather than being caught), if the fit produces a non-finite
    coefficient, or if _fit_platt itself rejects the result.
    """
    pairs = [
        (float(r["our_prob"]), r["settled_yes"])
        for r in rows
        if r.get("our_prob") is not None and r.get("settled_yes") is not None
    ]
    invalid = [y for _, y in pairs if y not in (0, 1)]
    if invalid:
        _log.warning(
            "fit_metar_calibration: %d row(s) with settled_yes not in {0, 1} "
            "(sample: %s) — refusing to fit on corrupted labels",
            len(invalid),
            invalid[:5],
        )
        return None

    n_pos = sum(1 for _, y in pairs if y == 1)
    n_neg = len(pairs) - n_pos
    min_class = min(n_pos, n_neg)
    if min_class < METAR_CALIBRATION_MIN_EPV_PER_PREDICTOR:
        _log.info(
            "fit_metar_calibration: minority class has %d rows (n_pos=%d "
            "n_neg=%d), need >= %d — skipping",
            min_class,
            n_pos,
            n_neg,
            METAR_CALIBRATION_MIN_EPV_PER_PREDICTOR,
        )
        return None

    logit_s = [_logit(p) for p, _ in pairs]  # _logit self-clips to [1e-6, 1-1e-6]
    labels = [int(y) for _, y in pairs]

    try:
        platt_a, platt_c = _fit_platt(logit_s, labels)
    except Exception as exc:
        _log.warning("fit_metar_calibration: Platt fit failed: %s", exc)
        return None

    if not (math.isfinite(platt_a) and math.isfinite(platt_c)):
        _log.warning(
            "fit_metar_calibration: non-finite coefficients (a=%s c=%s) — "
            "refusing to save",
            platt_a,
            platt_c,
        )
        return None

    return (platt_a, platt_a, platt_c)


def apply_metar_calibration(
    raw_prob: float, params: tuple[float, float, float]
) -> float:
    """Apply beta calibration: sigmoid(a*ln(s) - b*ln(1-s) + c). params is
    currently always (a, a, c) (see fit_metar_calibration) but the general
    2-coefficient form is kept here in case a future session revisits the
    asymmetric fit with a data source that doesn't share this one's
    two-narrow-clusters geometry."""
    a, b, c = params
    eps = 1e-6
    s = min(max(raw_prob, eps), 1 - eps)
    return _sigmoid(a * math.log(s) - b * math.log(1 - s) + c)


def fit_and_save_metar_calibration() -> tuple[float, float, float] | None:
    """Fetch METAR-lockout calibration data, fit, and persist to disk with
    cache invalidation -- the single canonical implementation shared by both
    `py main.py calibrate` and cron.py's weekly D5 auto-retrain block, so the
    two callers can't drift (same reasoning as calibration.py's own
    calibrate_and_save(), which plays the identical shared role for seasonal/
    city blend weights).

    Writes via atomic_write_json_with_history (not the plain atomic_write_json
    an earlier version used) so a retrain that makes things worse can be
    recovered from data/.history/ -- this file has no other backup mechanism.

    Returns the fitted (a, b, c), or None if there isn't enough data yet or
    the fit failed validation (see fit_metar_calibration for why).
    """
    import tracker

    rows = tracker.get_metar_lockout_calibration_data()
    fit = fit_metar_calibration(rows)
    if fit is None:
        return None

    a, b, c = fit
    from datetime import UTC, datetime

    from safe_io import atomic_write_json_with_history

    atomic_write_json_with_history(
        {
            "a": a,
            "b": b,
            "c": c,
            "n": len(rows),
            "fitted_at": datetime.now(UTC).isoformat(timespec="seconds"),
        },
        _METAR_CALIBRATION_PATH,
    )

    try:
        import weather_markets as _wm

        _wm._METAR_CAL = None  # invalidate cache so the next call reloads
    except Exception:
        pass

    _log.info(
        "fit_and_save_metar_calibration: saved a=%.4f b=%.4f c=%.4f (n=%d)",
        a,
        b,
        c,
        len(rows),
    )

    # AUD-0038: cron.py's settlement-lag force-close gate (>=0.80) is
    # currently unreachable under typical fits (see
    # settlement_monitor.py's _calibrate_metar_settlement_confidence
    # docstring for the derivation) -- but that's a fact about a SPECIFIC
    # fit, not a durable guarantee, since this function refits weekly from
    # live data with no bound tying its output to that threshold. Warn
    # loudly (not silently) the moment a refit's output range would
    # actually reach the gate, so a dormant->active transition is visible
    # instead of only discovered after it's already force-closed a trade.
    _CRON_FORCE_CLOSE_THRESHOLD = 0.80  # must track cron.py's literal >= 0.80
    # metar._dynamic_lock_in_confidence() hard-bounds its raw
    # (direction-relative) confidence to [0.72, 0.97] -- see that
    # function's own docstring. apply_metar_calibration's derivative wrt
    # raw_p_yes is a/s + b/(1-s); fit_metar_calibration always returns
    # a==b (see its own docstring), and both are required > 0 by
    # _fit_platt, so the function is monotonic increasing in raw_p_yes for
    # every fit this codebase actually produces. (apply_metar_calibration's
    # own docstring notes the general asymmetric a!=b form is kept for a
    # possible future fit source -- if one is ever added, this
    # monotonicity assumption would need re-deriving for that case.) So
    # the YES-lock ceiling is at raw_p_yes=0.97 and the NO-lock ceiling is
    # at raw_p_yes=1-0.97=0.03.
    #
    # The EFFECTIVE confidence cron.py actually sees is NOT simply the
    # calibrated value -- settlement_monitor._calibrate_metar_settlement_
    # confidence() bypasses calibration entirely (returns the raw,
    # uncapped confidence) whenever the correction delta exceeds its own
    # _METAR_CORRECTION_LIMIT (0.60). A ceiling model that ignores this
    # bypass is inverted from the actual risk (caught by independent
    # review): a fit that pushes the calibrated value DOWN hard produces a
    # LOW computed ceiling (no warning) while being MORE likely to trip
    # the 0.60 cap and let the raw 0.97/0.97 pass through uncalibrated --
    # e.g. fit=(0.1, 0.1, 1.0) calibrates to ~0.79/~0.34 (both under 0.80,
    # no warning) but its NO-direction delta is ~0.63 > 0.60, so the
    # bypass fires and cron.py actually sees the raw 0.97. Mirror the
    # bypass here so the ceiling model matches what cron.py really gets.
    _METAR_CORRECTION_LIMIT = 0.60  # must track settlement_monitor.py's own

    def _effective_ceiling(raw_confidence: float, outcome: str) -> float:
        # Mirrors _calibrate_metar_settlement_confidence's own
        # raw_p_yes/new_confidence/delta derivation exactly.
        raw_p_yes = raw_confidence if outcome == "yes" else (1.0 - raw_confidence)
        new_p_yes = apply_metar_calibration(raw_p_yes, fit)
        new_confidence = new_p_yes if outcome == "yes" else (1.0 - new_p_yes)
        delta = abs(new_confidence - raw_confidence)
        if delta > _METAR_CORRECTION_LIMIT:
            return raw_confidence
        return max(0.01, min(0.99, new_confidence))

    _yes_ceiling = _effective_ceiling(0.97, "yes")
    _no_ceiling = _effective_ceiling(0.97, "no")
    _ceiling = max(_yes_ceiling, _no_ceiling)
    if _ceiling >= _CRON_FORCE_CLOSE_THRESHOLD:
        # "effective" not "calibrated" -- _ceiling may be the RAW,
        # uncalibrated confidence when the correction-cap bypass fired
        # (review finding: the earlier "reaches calibrated confidence"
        # wording was misleading in exactly that case, the one thing this
        # fix exists to distinguish from a genuinely well-calibrated fit).
        _log.warning(
            "fit_and_save_metar_calibration: newly fitted a=%.4f b=%.4f "
            "c=%.4f (n=%d) reaches effective confidence %.3f, crossing "
            "cron.py's >=%.2f settlement force-close gate -- this path is "
            "no longer dormant, review before it force-closes a live trade",
            a,
            b,
            c,
            len(rows),
            _ceiling,
            _CRON_FORCE_CLOSE_THRESHOLD,
        )

    return fit


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
        # H-15: cap correction magnitude to prevent signal inversion on sparse/overfitted models
        _max_corr = float(os.getenv("ML_BIAS_MAX_CORRECTION", "0.25"))
        if abs(correction) > _max_corr:
            _log.debug(
                "apply_ml_prob_correction(%s): clamping correction %.3f → ±%.3f",
                city,
                correction,
                _max_corr,
            )
            correction = max(-_max_corr, min(_max_corr, correction))
        return max(0.0, min(1.0, our_prob + correction))
    except Exception as exc:
        _log.warning("apply_ml_prob_correction(%s): %s", city, exc)
        return our_prob


def has_ml_model(city: str) -> bool:
    """Return True if a trained GBM correction model exists for this city."""
    return _load_models().get(city.upper()) is not None


def _load_temperature_scale() -> dict | None:
    """Load the temperature scaling table from disk.

    Supports two file formats:
    - New: {"global": {"T": 5.06, "n": 40}, "between": {"T": 6.8, "n": 23}, ...}
    - Old (backward-compat): {"T": 5.06, "n_samples": 60}  → promoted to {"global": {"T": ...}}

    Returns a dict keyed by condition type (including "global"), or None when the file
    is absent or unreadable.
    """
    global _TEMP_CACHE, _TEMP_CACHE_MTIME
    if not _TEMP_PATH.exists():
        if _TEMP_CACHE is not None:
            _TEMP_CACHE = None
            _TEMP_CACHE_MTIME = None
        return None
    try:
        mtime = _TEMP_PATH.stat().st_mtime
    except OSError:
        return _TEMP_CACHE
    if _TEMP_CACHE is not None and _TEMP_CACHE_MTIME == mtime:
        return _TEMP_CACHE
    try:
        import json

        raw = json.loads(_TEMP_PATH.read_text())
        if "T" in raw:
            # Old single-value format — promote to new multi-condition dict
            _TEMP_CACHE = {"global": float(raw["T"])}
        else:
            # New format: extract T value from each condition dict
            _TEMP_CACHE = {
                k: float(v["T"])
                for k, v in raw.items()
                if isinstance(v, dict) and "T" in v
            }
        _TEMP_CACHE_MTIME = mtime
        return _TEMP_CACHE
    except Exception as exc:
        _log.warning("ml_bias: failed to parse temperature_scale.json: %s", exc)
        return None


def apply_temperature_scaling(
    prob: float,
    condition_type: str | None = None,
    days_out: int | None = None,
    pool: str | None = None,
) -> float:
    """Apply temperature calibration; returns prob unchanged if no model is trained.

    Same-day trades (days_out=0) use a dedicated 'sameday' T fitted only on
    METAR-derived probabilities.  Their distribution (sharp, near 0/1) is
    fundamentally different from ensemble forecasts — applying multi-day T=3+
    would wrongly compress METAR probs toward 0.5 and under-size same-day bets.
    If T_sameday is not yet trained (gate: 20 settled same-day trades), prob is
    returned unchanged rather than applying the wrong multi-day T.

    pool: explicit pool override for callers that are days_out=0 but NOT
    ordinary same-day daily trades (backlog.txt "HOURLY-DIRECTIONAL
    TEMPERATURE MARKETS" Step 2 handoff item 4). Pass pool="hourly" for
    KXTEMPxxxH predictions — days_out=0 alone can't distinguish an hourly
    trade from an ordinary sameday one, since hourly trades are inherently
    days_out=0 too. Existing callers (no pool arg) are completely unaffected.
    Same "no fallback to global/multi-day T" shape as 'sameday'.

    Multi-day lookup order: per-condition T → global T → no-op.
    """
    table = _load_temperature_scale()
    T = None
    if pool == "hourly":
        # Hourly path: hourly T only — no fallback to sameday/global/condition
        # (its calibration pool and target distribution are both distinct
        # from ordinary sameday trades; see train_all_temperature_scaling's
        # own hourly query for what feeds this pool).
        if table is None:
            return prob
        T = table.get("hourly")
        if T is None:
            return prob
    elif days_out is not None and days_out == 0:
        # Same-day path: sameday T only — no fallback to global/condition.
        if table is None:
            return prob
        T = table.get("sameday")
        if T is None:
            return prob
    else:
        if table is not None:
            if condition_type is not None:
                T = table.get(condition_type)
            if T is None:
                T = table.get("global")
        # Above/below use prior Ts when neither the scale file nor a
        # condition-specific entry is available.  Prevents unscaled extreme
        # outputs on thin data; overwritten once calibration has enough samples.
        if T is None and condition_type == "below":
            T = _T_BELOW_PRIOR
        elif T is None and condition_type == "above":
            T = _T_ABOVE_PRIOR
    if T is None or abs(T - 1.0) < 0.01:
        return prob
    return _sigmoid(_logit(prob) / T)


def train_all_temperature_scaling(
    min_samples_global: int = 20,
    min_samples_condition: int = 15,
) -> dict[str, float]:
    """Train T for the global pool and for each condition type that has enough data.

    Condition-specific T values capture the fact that 'between' markets have a
    much larger calibration gap than 'above'/'below' markets and need a different
    compression factor.

    Saves a unified JSON to data/temperature_scale.json:
        {"global": {"T": 5.06, "n": 40}, "between": {"T": 6.8, "n": 23}, ...}

    Returns {condition_key: T} for every key that was trained and saved.
    """
    import tracker

    tracker.init_db()

    try:
        import json

        import numpy as np
        from scipy.optimize import minimize_scalar  # type: ignore[import-untyped]
    except ImportError:
        _log.warning("train_all_temperature_scaling: scipy/numpy not installed")
        return {}

    _T_UPPER_BOUND = 8.0

    def _fit_T(
        probs_raw: list[float], labels_raw: list[float], label: str
    ) -> float | None:
        """Fit T via NLL minimisation; return T or None if fit fails / doesn't improve.

        `label` identifies the condition bucket (e.g. "global", "above", "sameday")
        for logging only. Every skip reason is logged here, with the label, so
        callers don't need their own generic "fit no better than T=1.0" fallback —
        which previously fired even when the real reason was hitting the T upper
        bound (directional bias), misattributing the skip reason in the logs.

        If T hits the upper bound, that signals directional bias (mean_pred != mean_actual)
        rather than a confidence-calibration problem.  T-scaling can't fix directional bias —
        it only pushes probabilities toward 0.50.  In that case we return None so the caller
        keeps whatever T is already stored, and logs a warning so the issue is visible.
        """
        if len(probs_raw) < 1:
            return None
        probs = np.clip(probs_raw, 1e-6, 1 - 1e-6)
        labels = np.array(labels_raw)
        logits = np.log(probs / (1 - probs))

        def nll(T: float) -> float:
            if T <= 0:
                return 1e9
            p_cal = np.clip(1.0 / (1.0 + np.exp(-logits / T)), 1e-9, 1 - 1e-9)
            return -float(
                np.sum(labels * np.log(p_cal) + (1 - labels) * np.log(1 - p_cal))
            )

        result = minimize_scalar(nll, bounds=(0.5, _T_UPPER_BOUND), method="bounded")
        T = float(result.x)

        # T at the boundary means NLL still improving past the limit — directional bias, not a
        # confidence problem.  Skip the update so the existing T stays in place.
        if T >= _T_UPPER_BOUND * 0.99:
            mean_pred = float(np.mean(probs_raw))
            mean_actual = float(np.mean(labels_raw))
            _log.warning(
                "train_all_temperature_scaling: %s T=%.4f hit upper bound (%.1f) on %d samples "
                "— directional bias suspected (mean_pred=%.3f vs mean_actual=%.3f); "
                "T-scaling cannot fix this; keeping existing T",
                label,
                T,
                _T_UPPER_BOUND,
                len(probs_raw),
                mean_pred,
                mean_actual,
            )
            return None

        if nll(T) >= nll(1.0):
            _log.info(
                "train_all_temperature_scaling: %s T fit no better than T=1.0 — skipping",
                label,
            )
            return None
        return T

    # Hourly trades (backlog.txt "HOURLY-DIRECTIONAL TEMPERATURE MARKETS" Step
    # 2 handoff item 4) are ALSO days_out=0, so the sameday query above can't
    # be used to isolate them -- must exclude by ticker prefix instead. The
    # prefix set is imported from weather_markets (the same single-source-of-
    # truth dict Step 1 established) rather than hardcoded here, so this
    # query can't independently drift from the one place that actually knows
    # which series are hourly.
    try:
        from weather_markets import _KXTEMP_HOURLY_CITY

        _hourly_prefixes = list(_KXTEMP_HOURLY_CITY)
    except Exception:
        _hourly_prefixes = []
    # Parens around the OR group are load-bearing: SQL's AND binds tighter
    # than OR, so "days_out=0 AND ticker LIKE a OR ticker LIKE b OR ..."
    # would silently match ticker LIKE b regardless of days_out.
    _hourly_exclude_sql = (
        " AND NOT (" + " OR ".join(["p.ticker LIKE ?"] * len(_hourly_prefixes)) + ")"
        if _hourly_prefixes
        else ""
    )
    _hourly_exclude_params = tuple(f"{p}%" for p in _hourly_prefixes)

    # Fetch settled rows split by days_out:
    # - Multi-day (days_out >= 1 or NULL) are ensemble-derived — use for global + per-condition T
    # - Same-day (days_out = 0) are METAR-derived — different distribution, need their own T
    #   (hourly trades explicitly excluded -- they get their own pool below)
    try:
        with tracker._conn() as con:
            rows = con.execute(
                """
                SELECT p.our_prob, o.settled_yes, p.condition_type
                FROM predictions p
                JOIN outcomes_valid o ON p.ticker = o.ticker
                WHERE p.our_prob IS NOT NULL AND o.settled_yes IS NOT NULL
                  AND (p.days_out IS NULL OR p.days_out >= 1)
                  AND (p.condition_type IS NULL
                       OR p.condition_type NOT IN
                          ('between', 'precip_month_total', 'snow_month_total', 'hurricane_count', 'hurricane_next_event', 'storm_order'))
                """
                # backlog.txt "RAIN / SNOW / HURRICANE MARKETS" Step 2: monthly
                # rain trades log with a real (large, ~0-31) days_out once
                # placed, so they'd otherwise land in this multi-day pool and
                # get pooled into a temperature-scaling calibration tuned for
                # °F-shaped probabilities. condition_type is already the exact
                # mechanism this query uses to exclude 'between' rows -- rain's
                # condition_type ("precip_month_total") is a new, unique
                # string, unlike hourly's ("above"/"below", indistinguishable
                # from ordinary daily rows by string alone, which is why
                # hourly needs ticker-prefix exclusion instead, below).
            ).fetchall()
            # metar_lockout rows excluded: analyze_trade's METAR-locked branch
            # never calls apply_temperature_scaling (bypasses section 7b
            # entirely -- see weather_markets.py's `else:` at the metar_locked
            # split), so a sameday T fit on a population that includes them
            # was training on data the transform is never actually applied
            # to. metar_lockout now gets its own dedicated beta-calibration
            # fit (fit_metar_calibration above) instead.
            sameday_rows = con.execute(
                """
                SELECT p.our_prob, o.settled_yes
                FROM predictions p
                JOIN outcomes_valid o ON p.ticker = o.ticker
                WHERE p.our_prob IS NOT NULL AND o.settled_yes IS NOT NULL
                  AND p.days_out = 0
                  AND (p.method IS NULL OR p.method != 'metar_lockout')
                  AND (p.condition_type IS NULL
                       OR p.condition_type NOT IN
                          ('between', 'precip_month_total', 'snow_month_total', 'hurricane_count', 'hurricane_next_event', 'storm_order'))
                """
                + _hourly_exclude_sql,
                _hourly_exclude_params,
            ).fetchall()
            hourly_rows = (
                con.execute(
                    """
                    SELECT p.our_prob, o.settled_yes
                    FROM predictions p
                    JOIN outcomes_valid o ON p.ticker = o.ticker
                    WHERE p.our_prob IS NOT NULL AND o.settled_yes IS NOT NULL
                      AND p.days_out = 0
                      AND ("""
                    + " OR ".join(["p.ticker LIKE ?"] * len(_hourly_prefixes))
                    + ")",
                    _hourly_exclude_params,
                ).fetchall()
                if _hourly_prefixes
                else []
            )
    except Exception as exc:
        _log.warning("train_all_temperature_scaling: DB query failed: %s", exc)
        return {}

    all_probs = [float(r["our_prob"]) for r in rows]
    all_labels = [float(r["settled_yes"]) for r in rows]

    # Read existing file so we only overwrite keys we actually retrain
    existing: dict = {}
    if _TEMP_PATH.exists():
        try:
            existing = json.loads(_TEMP_PATH.read_text())
            if "T" in existing:
                # Old format — wrap in new structure
                existing = {
                    "global": {"T": existing["T"], "n": existing.get("n_samples", 0)}
                }
        except Exception as _e:
            _log.warning(
                "train_all_temperature_scaling: failed to read temperature_scale.json: %s",
                _e,
            )
            existing = {}

    trained: dict[str, float] = {}

    # While EMOS is active, global/above/below/between are its keys, pinned
    # to 1.0 by reset_temperature_scale_for_emos() -- refitting them here
    # would silently overwrite that placeholder with a real T, so this
    # process (or any other reading temperature_scale.json) would start
    # double-calibrating on top of EMOS's own fit within one retrain cycle.
    # sameday/hourly are unaffected -- EMOS never covers those pools.
    _emos_active = _EMOS_PARAMS_PATH.exists()

    # Global fit
    if _emos_active:
        _log.info(
            "train_all_temperature_scaling: EMOS is active — skipping global T "
            "refit (would double-calibrate on top of EMOS's own fit)"
        )
    elif len(all_probs) >= min_samples_global:
        T_global = _fit_T(all_probs, all_labels, "global")
        if T_global is not None:
            existing["global"] = {"T": T_global, "n": len(all_probs)}
            trained["global"] = T_global
            _log.info(
                "train_all_temperature_scaling: global T=%.4f on %d samples",
                T_global,
                len(all_probs),
            )
    else:
        _log.info(
            "train_all_temperature_scaling: only %d global samples, need %d",
            len(all_probs),
            min_samples_global,
        )

    # Per-condition fits
    by_type: dict[str, tuple[list[float], list[float]]] = {}
    for r in rows:
        ct = r["condition_type"]
        if ct:
            if ct not in by_type:
                by_type[ct] = ([], [])
            by_type[ct][0].append(float(r["our_prob"]))
            by_type[ct][1].append(float(r["settled_yes"]))

    for ctype, (cprobs, clabels) in by_type.items():
        if _emos_active and ctype in EMOS_COVERED_CONDITION_KEYS:
            _log.info(
                "train_all_temperature_scaling: EMOS is active — skipping %s T "
                "refit (would double-calibrate on top of EMOS's own fit)",
                ctype,
            )
            continue
        if len(cprobs) < min_samples_condition:
            _log.info(
                "train_all_temperature_scaling: %s has %d samples, need %d — skipping",
                ctype,
                len(cprobs),
                min_samples_condition,
            )
            continue
        T_cond = _fit_T(cprobs, clabels, ctype)
        if T_cond is not None:
            existing[ctype] = {"T": T_cond, "n": len(cprobs)}
            trained[ctype] = T_cond
            _log.info(
                "train_all_temperature_scaling: %s T=%.4f on %d samples",
                ctype,
                T_cond,
                len(cprobs),
            )

    # Same-day T — fit on METAR-derived probabilities only.
    # These cluster near 0/1 (current obs is close to the threshold or far from it),
    # so multi-day T values (typically 3–4) would wrongly compress them toward 0.5.
    # 20-sample gate keeps variance manageable; fewer would overfit a single T parameter.
    _SAMEDAY_MIN = 20
    sd_probs = [float(r[0]) for r in sameday_rows]
    sd_labels = [float(r[1]) for r in sameday_rows]
    if len(sd_probs) >= _SAMEDAY_MIN:
        T_sameday = _fit_T(sd_probs, sd_labels, "sameday")
        if T_sameday is not None:
            existing["sameday"] = {"T": T_sameday, "n": len(sd_probs)}
            trained["sameday"] = T_sameday
            _log.info(
                "train_all_temperature_scaling: sameday T=%.4f on %d samples",
                T_sameday,
                len(sd_probs),
            )
    else:
        _log.info(
            "train_all_temperature_scaling: only %d same-day settled samples, need %d — skipping",
            len(sd_probs),
            _SAMEDAY_MIN,
        )

    # Hourly T — a third, fully separate pool (backlog.txt "HOURLY-
    # DIRECTIONAL TEMPERATURE MARKETS" Step 2 handoff item 4), never folded
    # into 'sameday' or the multi-day pools. Mirrors the sameday block above
    # exactly (own gate, own fit, own existing[] write) since 'sameday' isn't
    # a generic loop either -- it's a hardcoded pool, same as this one.
    _HOURLY_MIN = 20
    hr_probs = [float(r[0]) for r in hourly_rows]
    hr_labels = [float(r[1]) for r in hourly_rows]
    if len(hr_probs) >= _HOURLY_MIN:
        T_hourly = _fit_T(hr_probs, hr_labels, "hourly")
        if T_hourly is not None:
            existing["hourly"] = {"T": T_hourly, "n": len(hr_probs)}
            trained["hourly"] = T_hourly
            _log.info(
                "train_all_temperature_scaling: hourly T=%.4f on %d samples",
                T_hourly,
                len(hr_probs),
            )
    else:
        _log.info(
            "train_all_temperature_scaling: only %d hourly settled samples, need %d — skipping",
            len(hr_probs),
            _HOURLY_MIN,
        )

    if existing:
        from safe_io import atomic_write_json_with_history

        atomic_write_json_with_history(existing, _TEMP_PATH)
        # Invalidate the in-memory cache so the next call reads the new file
        global _TEMP_CACHE
        _TEMP_CACHE = None
        _log.info(
            "train_all_temperature_scaling: saved %d keys to %s",
            len(existing),
            _TEMP_PATH,
        )

    return trained


# ── EMOS (Ensemble Model Output Statistics) ───────────────────────────────────


def fit_emos(
    ens_mean: np.ndarray,
    ens_var: np.ndarray,
    obs: np.ndarray,
) -> tuple[float, float, float, float]:
    """Fit EMOS parameters (a, b, c, d) minimising mean CRPS.

    Model: T ~ N(mu, sigma^2) where
        mu    = a + b * ens_mean
        sigma = sqrt(max(c + d * ens_var, 1e-6))

    Optimizer works in sqrt-space (c_sq, d_sq) to keep sigma positive.
    Returned (c, d) are c_sq**2 and d_sq**2 — non-negative by construction.

    CRITICAL: pass ens_var (variance = std**2), NOT std directly.
    Requires: pip install properscoring numpy scipy
    """
    import numpy as _np
    import properscoring as _ps
    from scipy.optimize import minimize as _minimize

    ens_mean = _np.asarray(ens_mean, dtype=float)
    ens_var = _np.asarray(ens_var, dtype=float)
    obs = _np.asarray(obs, dtype=float)

    def objective(params: list) -> float:
        a_, b_, c_sq, d_sq = params
        mu = a_ + b_ * ens_mean
        sigma = _np.sqrt(_np.maximum(c_sq**2 + d_sq**2 * ens_var, 1e-6))
        return float(_np.mean(_ps.crps_gaussian(obs, mu=mu, sig=sigma)))

    res = _minimize(
        objective,
        x0=[0.0, 1.0, 1.0, 0.1],
        method="Nelder-Mead",
        options={"maxiter": 20_000, "xatol": 1e-7, "fatol": 1e-7},
    )
    a, b, c_sq, d_sq = res.x
    return float(a), float(b), float(c_sq**2), float(d_sq**2)


def emos_exceedance_prob(
    params: tuple[float, float, float, float],
    ens_mean: float,
    ens_var: float,
    threshold: float,
) -> float:
    """P(T > threshold) from a fitted EMOS Gaussian distribution.

    CRITICAL: pass ens_var (variance = std**2), NOT std.
    If ens_stats provides 'std', square it: ens_var = ens_stats['std'] ** 2
    """
    from scipy.special import ndtr

    a, b, c, d = params
    mu = a + b * ens_mean
    sigma = math.sqrt(max(c + d * ens_var, 1e-6))
    return float(1.0 - ndtr((threshold - mu) / sigma))


def emos_interval_prob(
    params: tuple[float, float, float, float],
    ens_mean: float,
    ens_var: float,
    low: float,
    high: float,
) -> float:
    """P(low < T < high) from a fitted EMOS Gaussian — for 'between' markets.

    CRITICAL: pass ens_var (variance), NOT std.
    """
    from scipy.special import ndtr

    a, b, c, d = params
    mu = a + b * ens_mean
    sigma = math.sqrt(max(c + d * ens_var, 1e-6))
    return float(ndtr((high - mu) / sigma) - ndtr((low - mu) / sigma))


def _load_emos_params() -> tuple[float, float, float, float] | None:
    """Return cached (a, b, c, d) from emos_params.json, or None if not trained.

    Re-checks the file's mtime on every call (a cheap stat, not a re-read
    unless it actually changed) so a long-running loop/watch process picks
    up an emos-train --activate or emos-deactivate made by a separate CLI
    invocation on its very next call, rather than only at process start.
    """
    global _EMOS_CACHE, _EMOS_CACHE_MTIME
    if not _EMOS_PARAMS_PATH.exists():
        if _EMOS_CACHE is not None:
            _EMOS_CACHE = None
            _EMOS_CACHE_MTIME = None
        return None
    try:
        mtime = _EMOS_PARAMS_PATH.stat().st_mtime
    except OSError:
        return _EMOS_CACHE
    if _EMOS_CACHE is not None and _EMOS_CACHE_MTIME == mtime:
        return _EMOS_CACHE
    try:
        data = json.loads(_EMOS_PARAMS_PATH.read_text())
        _EMOS_CACHE = (
            float(data["a"]),
            float(data["b"]),
            float(data["c"]),
            float(data["d"]),
        )
        _EMOS_CACHE_MTIME = mtime
        _log.info(
            "EMOS params loaded: a=%.4f b=%.4f c=%.4f d=%.4f n=%s crps=%s",
            *_EMOS_CACHE,
            data.get("n", "?"),
            data.get("mean_crps", "?"),
        )
        return _EMOS_CACHE
    except Exception as exc:
        _log.error("ml_bias: failed to load emos_params.json: %s", exc)
        return None


def save_emos_params(
    a: float,
    b: float,
    c: float,
    d: float,
    n: int,
    mean_crps: float | None = None,
) -> None:
    """Persist EMOS parameters and clear the in-process cache."""
    global _EMOS_CACHE
    from datetime import UTC, datetime

    payload = {
        "a": float(a),
        "b": float(b),
        "c": float(c),
        "d": float(d),
        "n": int(n),
        "mean_crps": float(mean_crps) if mean_crps is not None else None,
        "fitted_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    from safe_io import atomic_write_json_with_history

    atomic_write_json_with_history(payload, _EMOS_PARAMS_PATH)
    _EMOS_CACHE = (float(a), float(b), float(c), float(d))
    _log.info("EMOS params saved: a=%.4f b=%.4f c=%.4f d=%.4f (n=%d)", a, b, c, d, n)


def get_emos_status() -> dict:
    """Return {"active": bool, "a"/"b"/"c"/"d"/"n"/"mean_crps"/"fitted_at": ...}
    describing whether EMOS is currently the live probability method for
    multi-day above/below/between predictions.

    Returns {"active": False} when emos_params.json doesn't exist, or
    {"active": False, "corrupt": True, "error": ...} when it exists but
    fails to parse -- distinct from "doesn't exist" so a caller (e.g.
    cmd_emos_deactivate) can still offer to remove a corrupt file instead
    of reporting nothing to do.
    """
    if not _EMOS_PARAMS_PATH.exists():
        return {"active": False}
    try:
        data = json.loads(_EMOS_PARAMS_PATH.read_text())
        return {
            "active": True,
            "a": float(data["a"]),
            "b": float(data["b"]),
            "c": float(data["c"]),
            "d": float(data["d"]),
            "n": data.get("n"),
            "mean_crps": data.get("mean_crps"),
            "fitted_at": data.get("fitted_at"),
        }
    except Exception as exc:
        return {"active": False, "corrupt": True, "error": str(exc)}


def reset_temperature_scale_for_emos() -> None:
    """Reset T_global/T_above/T_below/T_between to 1.0 (identity/no-op) in
    temperature_scale.json, as the coupled step of activating EMOS.

    EMOS's own fitted Gaussian (a,b,c,d) replaces T-scaling's role for
    multi-day above/below/global/between predictions once live -- 'between'
    IS covered (weather_markets.py calls emos_interval_prob for it), unlike
    sameday/hourly which are METAR-derived and EMOS never touches. Leaving
    T at a previously-fit non-identity value would double-calibrate on top
    of EMOS.

    Snapshots the pre-reset values for these 4 keys to
    temperature_scale_pre_emos.json first, so deactivate_emos() can restore
    them immediately rather than leaving this process's T pinned at the 1.0
    placeholder for up to a week until the next scheduled retrain -- which
    would also permanently disable apply_temperature_scaling's
    _T_ABOVE_PRIOR/_T_BELOW_PRIOR fallback (it only fires when a key is
    fully absent, never once a 1.0 placeholder key exists) and reproduce
    the exact zero-calibration incident recorded in backlog.txt's EMOS
    entry. Each reset key is also tagged reset_for_emos/reset_at so it's
    inspectable-by-eye as a placeholder, not a real fit.
    """
    global _TEMP_CACHE, _TEMP_CACHE_MTIME
    from datetime import UTC, datetime

    from safe_io import atomic_write_json_with_history

    existing: dict = {}
    if _TEMP_PATH.exists():
        try:
            existing = json.loads(_TEMP_PATH.read_text())
            if not isinstance(existing, dict):
                existing = {}
            elif "T" in existing:
                # Old single-value format -- mirror train_all_temperature_
                # scaling's own migration (ml_bias.py ~line 674): the old
                # sample-count key is "n_samples", not "n".
                existing = {
                    "global": {
                        "T": float(existing["T"]),
                        "n": existing.get("n_samples", 0),
                    }
                }
        except Exception:
            existing = {}

    snapshot = {
        key: existing[key]
        for key in EMOS_COVERED_CONDITION_KEYS
        if isinstance(existing.get(key), dict)
    }
    if snapshot:
        atomic_write_json_with_history(snapshot, _TEMP_PRE_EMOS_SNAPSHOT_PATH)

    reset_at = datetime.now(UTC).isoformat(timespec="seconds")
    for key in EMOS_COVERED_CONDITION_KEYS:
        prior = existing.get(key)
        prior_n = prior.get("n", 0) if isinstance(prior, dict) else 0
        existing[key] = {
            "T": 1.0,
            "n": prior_n,
            "reset_for_emos": True,
            "reset_at": reset_at,
        }

    atomic_write_json_with_history(existing, _TEMP_PATH)
    _TEMP_CACHE = None
    _TEMP_CACHE_MTIME = None
    _log.info(
        "reset_temperature_scale_for_emos: %s reset to 1.0 (pre-reset snapshot saved for restore on deactivate)",
        ", ".join(EMOS_COVERED_CONDITION_KEYS),
    )


def restore_temperature_scale_from_emos_snapshot() -> bool:
    """Restore global/above/below/between to their pre-EMOS-activation T
    values from the snapshot reset_temperature_scale_for_emos() saved, as
    part of deactivate_emos(). Safe no-op (returns False) if no snapshot
    exists -- e.g. EMOS was never actually activated through the confirm
    gate, or a previous deactivate already consumed it.

    Restoring immediately (rather than waiting for the next scheduled
    retrain) closes the double-calibration/zero-calibration gap described
    in reset_temperature_scale_for_emos()'s own docstring.
    """
    global _TEMP_CACHE, _TEMP_CACHE_MTIME

    if not _TEMP_PRE_EMOS_SNAPSHOT_PATH.exists():
        return False
    try:
        snapshot = json.loads(_TEMP_PRE_EMOS_SNAPSHOT_PATH.read_text())
        if not isinstance(snapshot, dict) or not snapshot:
            _TEMP_PRE_EMOS_SNAPSHOT_PATH.unlink(missing_ok=True)
            return False

        existing: dict = {}
        if _TEMP_PATH.exists():
            try:
                existing = json.loads(_TEMP_PATH.read_text())
                if not isinstance(existing, dict):
                    existing = {}
            except Exception:
                existing = {}

        for key, value in snapshot.items():
            existing[key] = value

        from safe_io import atomic_write_json_with_history

        atomic_write_json_with_history(existing, _TEMP_PATH)
        _TEMP_CACHE = None
        _TEMP_CACHE_MTIME = None
        _TEMP_PRE_EMOS_SNAPSHOT_PATH.unlink(missing_ok=True)
        _log.info(
            "restore_temperature_scale_from_emos_snapshot: restored %s",
            ", ".join(sorted(snapshot)),
        )
        return True
    except Exception as exc:
        _log.warning(
            "restore_temperature_scale_from_emos_snapshot: failed, pre-EMOS "
            "values NOT restored -- T remains at the 1.0 placeholder: %s",
            exc,
        )
        return False


def deactivate_emos() -> bool:
    """Remove emos_params.json, reverting multi-day above/below/between
    predictions to the ensemble/climatology blend + temperature scaling,
    and immediately restore temperature_scale.json's pre-activation T
    values (see restore_temperature_scale_from_emos_snapshot). Safe to call
    whether or not EMOS is currently active. Returns True only if it was
    actually active (a file existed), matching
    paper.clear_accuracy_halt_override()'s same-shape return convention.

    Archives the current emos_params.json content to data/.history/ before
    removing it, even on a corrupt/unparseable file (raw text copy, no JSON
    round-trip) -- atomic_write_json_with_history only snapshots on
    OVERWRITE, so a bare unlink on the very first activation's file would
    otherwise make those exact fitted parameters unrecoverable.
    """
    global _EMOS_CACHE, _EMOS_CACHE_MTIME
    was_active = _EMOS_PARAMS_PATH.exists()

    if was_active:
        try:
            import time as _time
            from datetime import UTC, datetime

            history_dir = _EMOS_PARAMS_PATH.parent / ".history"
            history_dir.mkdir(exist_ok=True)
            stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
            history_file = history_dir / f"{_EMOS_PARAMS_PATH.stem}_{stamp}.json"
            if history_file.exists():
                history_file = (
                    history_dir
                    / f"{_EMOS_PARAMS_PATH.stem}_{stamp}_{int(_time.monotonic() * 1000) % 1000}.json"
                )
            history_file.write_text(
                _EMOS_PARAMS_PATH.read_text(encoding="utf-8"), encoding="utf-8"
            )
        except Exception as exc:
            _log.warning("deactivate_emos: history backup failed: %s", exc)

    _EMOS_PARAMS_PATH.unlink(missing_ok=True)
    _EMOS_CACHE = None
    _EMOS_CACHE_MTIME = None
    restore_temperature_scale_from_emos_snapshot()
    if was_active:
        _log.info("deactivate_emos: emos_params.json removed, EMOS no longer live")
    return was_active
