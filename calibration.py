"""Offline blend-weight calibration for seasonal and per-city model optimization.

Run: python main.py calibrate
Outputs: data/seasonal_weights.json, data/city_weights.json
"""

from __future__ import annotations

import json
import logging
import math as _math
import random as _random
import sqlite3
from datetime import date as _date_type
from pathlib import Path

_log = logging.getLogger(__name__)

_SEASONAL_MIN = (
    20  # D6: lowered from 50 — calibration fires sooner as trades accumulate
)
_CITY_MIN = 50  # P3-7/P3-25: raised to 50 for statistical reliability (SE ~0.07)
_N_RANDOM_SEARCH = 200  # P3-7: random search replaces exhaustive 5,151-triple grid
_BRIER_IMPROVEMENT_GATE = 0.005  # min val-set improvement to accept calibrated weights
_RECENCY_HALFLIFE_DAYS = 90  # exponential decay: trade 90 days old gets ~37% weight


def _compute_recency_weight(date_str: str) -> float:
    """Exponential decay weight so recent settled trades count more in calibration."""
    try:
        days_ago = (
            _date_type.today() - _date_type.fromisoformat(str(date_str)[:10])
        ).days
        return _math.exp(-max(0, days_ago) / _RECENCY_HALFLIFE_DAYS)
    except Exception:
        return 1.0


_MONTH_TO_SEASON: dict[int, str] = {
    12: "winter",
    1: "winter",
    2: "winter",
    3: "spring",
    4: "spring",
    5: "spring",
    6: "summer",
    7: "summer",
    8: "summer",
    9: "fall",
    10: "fall",
    11: "fall",
}


def _brier(rows: list[tuple], we: float, wc: float, wn: float) -> float:
    """Compute weighted Brier score. Rows are (e, c, n, s[, weight]). Skips None components."""
    total = 0.0
    sum_w = 0.0
    for row in rows:
        e, c, n, s = row[0], row[1], row[2], row[3]
        if any(x is None for x in (e, c, n, s)):
            continue
        w = row[4] if len(row) > 4 else 1.0
        total += w * (we * e + wc * c + wn * n - s) ** 2
        sum_w += w
    return total / sum_w if sum_w > 0 else float("inf")


def _split_rows(
    dated_rows: list[tuple],
    cutoff_date: str | None,
) -> tuple[list[tuple], list[tuple]]:
    """Split (date_str, e, c, n, s[, weight]) rows into (train, val) tuples (date stripped).

    Uses explicit cutoff_date if given; otherwise auto-computes the 80th-percentile date.
    Weight in position 5 is passed through if present so _brier can use recency weighting.
    """
    if cutoff_date is None:
        sorted_dates = sorted(r[0] for r in dated_rows)
        idx = max(1, int(len(sorted_dates) * 0.8))
        cutoff_date = sorted_dates[min(idx, len(sorted_dates) - 1)]
    train = [r[1:] for r in dated_rows if r[0] < cutoff_date]
    val = [r[1:] for r in dated_rows if r[0] >= cutoff_date]
    return train, val


def _best_weights(
    train_rows: list[tuple[float, float, float, int]],
    val_rows: list[tuple[float, float, float, int]],
) -> dict[str, float]:
    """Random-search 200 simplex samples on train_rows; gate on val Brier improvement (P3-7)."""
    equal = (1 / 3, 1 / 3, 1 / 3)
    best_score = float("inf")
    best = equal
    rng = _random.Random(42)
    for _ in range(_N_RANDOM_SEARCH):
        a = rng.random()
        b = rng.random()
        if a > b:
            a, b = b, a
        we, wc, wn = a, b - a, 1.0 - b
        score = _brier(train_rows, we, wc, wn)
        if score < best_score:
            best_score = score
            best = (we, wc, wn)

    # M-19: refuse to return in-sample weights when validation set is too small.
    # With < 10 val rows the _BRIER_IMPROVEMENT_GATE (0.001) is noise — a single
    # lucky prediction can clear it and let overfitted weights enter production.
    _MIN_VAL_ROWS = 10
    if len(val_rows) < _MIN_VAL_ROWS:
        _log.warning(
            "calibrate_blend_weights: only %d validation rows (need %d) — "
            "returning uncalibrated so calibrate_and_save preserves existing weights",
            len(val_rows),
            _MIN_VAL_ROWS,
        )
        return {
            "ensemble": equal[0],
            "climatology": equal[1],
            "nws": equal[2],
            "_uncalibrated": True,
        }

    val_baseline = _brier(val_rows, *equal)
    val_calibrated = _brier(val_rows, *best)
    if val_baseline - val_calibrated <= _BRIER_IMPROVEMENT_GATE:
        return {"ensemble": equal[0], "climatology": equal[1], "nws": equal[2]}

    return {"ensemble": best[0], "climatology": best[1], "nws": best[2]}


def _load_rows(db_path: Path) -> list[sqlite3.Row]:
    with sqlite3.connect(str(db_path)) as con:
        con.row_factory = sqlite3.Row
        return con.execute(
            """
            SELECT p.city, p.market_date, p.condition_type,
                   p.ensemble_prob, p.nws_prob, p.clim_prob,
                   o.settled_yes
            FROM multiday_predictions p
            JOIN outcomes o ON p.ticker = o.ticker
            WHERE p.ensemble_prob IS NOT NULL
              AND p.nws_prob IS NOT NULL
              AND p.clim_prob IS NOT NULL
              AND o.settled_yes IS NOT NULL
              AND (p.condition_type IS NULL OR p.condition_type != 'between')
            """
        ).fetchall()


def calibrate_seasonal_weights(
    db_path: str | Path,
    cutoff_date: str | None = None,
) -> dict[str, dict[str, float]]:
    """Grid-search optimal blend weights per season.

    Returns: {season: {ensemble, climatology, nws}} for seasons with >= _SEASONAL_MIN rows.
    Weights are trained on rows before cutoff_date (auto 80/20 split if omitted).
    """
    db_path = Path(db_path)
    rows = _load_rows(db_path)

    season_rows: dict[str, list[tuple]] = {}
    for row in rows:
        try:
            month = int(str(row["market_date"])[5:7])
        except (TypeError, ValueError):
            continue
        season = _MONTH_TO_SEASON.get(month)
        if season is None:
            continue
        date_str = str(row["market_date"])
        season_rows.setdefault(season, []).append(
            (
                date_str,
                row["ensemble_prob"],
                row["clim_prob"],
                row["nws_prob"],
                row["settled_yes"],
                _compute_recency_weight(date_str),
            )
        )

    _neutral = {
        "ensemble": 1 / 3,
        "climatology": 1 / 3,
        "nws": 1 / 3,
        "_uncalibrated": True,
    }
    # Always return all four seasons — use neutral defaults for any season that
    # lacks enough data. This keeps the output file complete so callers never see
    # "No seasonal weights for X" warnings during early accumulation.
    # "_uncalibrated": True is the machine-readable flag: _blend_weights checks for
    # it and falls through to the hardcoded schedule rather than calling
    # _nws_days_out_scale on these placeholder values. The "_" prefix means
    # validate_weight_files already skips it in the sum-to-1 check.
    result: dict[str, dict[str, float]] = {
        s: _neutral for s in _MONTH_TO_SEASON.values()
    }
    for season, srows in season_rows.items():
        if len(srows) < _SEASONAL_MIN:
            _log.info(
                "calibrate_seasonal_weights: %s has %d rows (need %d) — using neutral defaults",
                season,
                len(srows),
                _SEASONAL_MIN,
            )
            continue
        train, val = _split_rows(srows, cutoff_date)
        result[season] = _best_weights(train, val)
    return result


def calibrate_city_weights(
    db_path: str | Path,
    cutoff_date: str | None = None,
) -> dict[str, dict[str, float]]:
    """Grid-search optimal blend weights per city.

    Returns: {city: {ensemble, climatology, nws}} for cities with >= _CITY_MIN rows.
    Weights are trained on rows before cutoff_date (auto 80/20 split if omitted).
    """
    db_path = Path(db_path)
    rows = _load_rows(db_path)

    city_rows: dict[str, list[tuple]] = {}
    for row in rows:
        city = row["city"]
        if not city:
            continue
        date_str = str(row["market_date"])
        city_rows.setdefault(city, []).append(
            (
                date_str,
                row["ensemble_prob"],
                row["clim_prob"],
                row["nws_prob"],
                row["settled_yes"],
                _compute_recency_weight(date_str),
            )
        )

    result: dict[str, dict[str, float]] = {}
    for city, crows in city_rows.items():
        if len(crows) < _CITY_MIN:
            _log.info(
                "calibrate_city_weights: %s has %d rows (need %d) — skipping",
                city,
                len(crows),
                _CITY_MIN,
            )
            continue
        train, val = _split_rows(crows, cutoff_date)
        result[city] = _best_weights(train, val)
    return result


def load_seasonal_weights(
    path: str | Path | None = None,
) -> dict[str, dict[str, float]]:
    """Load seasonal weights from JSON. Returns {} if file missing."""
    p = Path(path) if path else Path(__file__).parent / "data" / "seasonal_weights.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except Exception as exc:
        _log.warning("load_seasonal_weights: could not read %s: %s", p, exc)
        return {}


def load_city_weights(path: str | Path | None = None) -> dict[str, dict[str, float]]:
    """Load per-city weights from JSON. Returns {} if file missing."""
    p = Path(path) if path else Path(__file__).parent / "data" / "city_weights.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except Exception as exc:
        _log.warning("load_city_weights: could not read %s: %s", p, exc)
        return {}


_CONDITION_MIN = (
    60  # 60 * 0.2 = 12 val rows — minimum for improvement gate to be meaningful
)


def calibrate_condition_weights(
    db_path: str | Path,
    min_samples: int = _CONDITION_MIN,
    cutoff_date: str | None = None,
) -> dict[str, dict[str, float]]:
    """Grid-search optimal blend weights per condition type (above/below/between).

    Returns: {condition_type: {ensemble, climatology, nws}} for types with >= min_samples rows.
    Weights are trained on rows before cutoff_date (auto 80/20 split if omitted).
    """
    db_path = Path(db_path)
    con = sqlite3.connect(str(db_path))
    try:
        con.row_factory = sqlite3.Row
        raw_rows = con.execute(
            """
            SELECT p.condition_type, p.market_date,
                   p.ensemble_prob, p.clim_prob, p.nws_prob,
                   o.settled_yes
            FROM predictions p
            JOIN outcomes o ON p.ticker = o.ticker
            WHERE p.ensemble_prob IS NOT NULL
              AND p.clim_prob IS NOT NULL
              AND p.nws_prob IS NOT NULL
              AND o.settled_yes IS NOT NULL
              AND (p.days_out IS NULL OR p.days_out >= 1)
            """
        ).fetchall()
    finally:
        con.close()

    type_rows: dict[str, list[tuple]] = {}
    for row in raw_rows:
        ctype = row["condition_type"]
        if not ctype:
            continue
        date_str = str(row["market_date"]) if row["market_date"] else ""
        type_rows.setdefault(ctype, []).append(
            (
                date_str,
                row["ensemble_prob"],
                row["clim_prob"],
                row["nws_prob"],
                row["settled_yes"],
                _compute_recency_weight(date_str),
            )
        )

    _neutral = {
        "ensemble": 1 / 3,
        "climatology": 1 / 3,
        "nws": 1 / 3,
        "_uncalibrated": True,
    }
    # Always return all three condition types — use neutral defaults for any type
    # that lacks enough data so the output file is always complete.
    # See calibrate_seasonal_weights for the "_uncalibrated" flag rationale.
    result: dict[str, dict[str, float]] = {
        c: _neutral for c in ("above", "below", "between")
    }
    for ctype, crows in type_rows.items():
        if len(crows) < min_samples:
            _log.info(
                "calibrate_condition_weights: %s has %d rows (need %d) — using neutral defaults",
                ctype,
                len(crows),
                min_samples,
            )
            continue
        train, val = _split_rows(crows, cutoff_date)
        result[ctype] = _best_weights(train, val)
    return result


def load_condition_weights(
    path: str | Path | None = None,
) -> dict[str, dict[str, float]]:
    """Load per-condition-type weights from JSON. Returns {} if file missing."""
    p = (
        Path(path)
        if path
        else Path(__file__).parent / "data" / "condition_weights.json"
    )
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except Exception as exc:
        _log.warning("load_condition_weights: could not read %s: %s", p, exc)
        return {}


def calibrate_and_save(
    db_path: str | Path | None = None,
    data_dir: str | Path | None = None,
) -> tuple[dict, dict, dict]:
    """Run all three blend-weight calibrations and write results atomically to disk.

    This is the single canonical implementation used by both ``py main.py calibrate``
    and the F3 cron auto-calibration block.  Keeping the disk-write logic here means
    changes to output paths or format only need to happen in one place.

    Returns (seasonal, city, condition) dicts — same as calling each function
    individually.  Cache invalidation (e.g. weather_markets._CONDITION_WEIGHTS) is
    the caller's responsibility to avoid a circular import dependency.

    Raises on DB read failure so callers can handle the error message appropriately.
    """
    from tracker import DB_PATH as _DB_PATH

    _db = Path(db_path) if db_path else _DB_PATH
    _dir = Path(data_dir) if data_dir else Path(__file__).parent / "data"
    _dir.mkdir(exist_ok=True)

    seasonal = calibrate_seasonal_weights(_db)
    city = calibrate_city_weights(_db)
    condition = calibrate_condition_weights(_db)

    # Preserve any manually-set condition weights that auto-calibration left as
    # neutral (insufficient samples).  Without this, a weekly retrain on N<20
    # above/below trades would overwrite hand-tuned weights with equal 1/3.
    _cond_path = _dir / "condition_weights.json"
    if _cond_path.exists():
        try:
            _existing = json.loads(_cond_path.read_text())
            for _ctype, _entry in _existing.items():
                if (
                    _ctype in condition
                    and condition[_ctype].get("_uncalibrated")
                    and isinstance(_entry, dict)
                    and not _entry.get("_uncalibrated")
                ):
                    condition[_ctype] = _entry
        except Exception as exc:
            _log.warning(
                "calibrate_and_save: failed to preserve condition weights: %s "
                "— freshly-calibrated values will overwrite hand-tuned weights",
                exc,
            )

    from safe_io import atomic_write_json_with_history

    atomic_write_json_with_history(seasonal, _dir / "seasonal_weights.json")
    atomic_write_json_with_history(city, _dir / "city_weights.json")
    atomic_write_json_with_history(condition, _dir / "condition_weights.json")

    _log.info(
        "calibrate_and_save: wrote seasonal(%d) city(%d) condition(%d) to %s",
        len(seasonal),
        len(city),
        len(condition),
        _dir,
    )
    return seasonal, city, condition


def validate_weight_files(
    seasonal: dict | None = None,
    city: dict | None = None,
    condition: dict | None = None,
) -> None:
    """P2-7: Warn on missing or malformed weight file entries at startup."""
    if seasonal is None:
        seasonal = load_seasonal_weights()
    if city is None:
        city = load_city_weights()
    if condition is None:
        condition = load_condition_weights()

    for season in ("spring", "summer", "fall", "winter"):
        w = seasonal.get(season)
        if w is None:
            _log.warning(
                "No seasonal weights for %s — using hardcoded defaults", season
            )
        elif abs(sum(v for k, v in w.items() if not k.startswith("_")) - 1.0) > 0.005:
            _log.error("Seasonal weights for %s don't sum to 1.0: %s", season, w)
        # L-9: reject negative individual weights — they produce probabilities outside [0,1]
        elif any(v < 0 for k, v in w.items() if not k.startswith("_")):
            _log.error("Seasonal weights for %s contain negative values: %s", season, w)

    for ctype in ("above", "below", "between"):
        w = condition.get(ctype)
        if w is None:
            _log.warning(
                "No condition weights for %s — using hardcoded defaults", ctype
            )
        elif abs(sum(v for k, v in w.items() if not k.startswith("_")) - 1.0) > 0.005:
            _log.error("Condition weights for %s don't sum to 1.0: %s", ctype, w)
