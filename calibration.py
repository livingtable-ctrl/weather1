"""Offline blend-weight calibration for seasonal and per-city model optimization.

Run: python main.py calibrate
Outputs: data/seasonal_weights.json, data/city_weights.json
"""

from __future__ import annotations

import json
import logging
import random as _random
import sqlite3
from pathlib import Path

_log = logging.getLogger(__name__)

_SEASONAL_MIN = (
    20  # D6: lowered from 50 — calibration fires sooner as trades accumulate
)
_CITY_MIN = 50  # P3-7/P3-25: raised to 50 for statistical reliability (SE ~0.07)
_N_RANDOM_SEARCH = 200  # P3-7: random search replaces exhaustive 5,151-triple grid
_BRIER_IMPROVEMENT_GATE = (
    0.005  # P3-7: min val-set improvement to accept calibrated weights
)

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


def _brier(
    rows: list[tuple[float, float, float, int]], we: float, wc: float, wn: float
) -> float:
    """Compute Brier score for a weight combo. Skips rows with any None component (P3-17)."""
    valid = [
        (e, c, n, s)
        for e, c, n, s in rows
        if e is not None and c is not None and n is not None and s is not None
    ]
    if not valid:
        return float("inf")
    total = sum((we * e + wc * c + wn * n - s) ** 2 for e, c, n, s in valid)
    return total / len(valid)


def _split_rows(
    dated_rows: list[tuple],
    cutoff_date: str | None,
) -> tuple[
    list[tuple[float, float, float, int]], list[tuple[float, float, float, int]]
]:
    """Split (date_str, ens, clim, nws, settled) rows into (train, val) plain tuples.

    Uses explicit cutoff_date if given; otherwise auto-computes the 80th-percentile date.
    """
    if cutoff_date is None:
        sorted_dates = sorted(r[0] for r in dated_rows)
        idx = max(1, int(len(sorted_dates) * 0.8))
        cutoff_date = sorted_dates[min(idx, len(sorted_dates) - 1)]
    train = [(e, c, n, s) for d, e, c, n, s in dated_rows if d < cutoff_date]
    val = [(e, c, n, s) for d, e, c, n, s in dated_rows if d >= cutoff_date]
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

    if val_rows:
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
            FROM predictions p
            JOIN outcomes o ON p.ticker = o.ticker
            WHERE p.ensemble_prob IS NOT NULL
              AND p.nws_prob IS NOT NULL
              AND p.clim_prob IS NOT NULL
              AND o.settled_yes IS NOT NULL
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
        season_rows.setdefault(season, []).append(
            (
                str(row["market_date"]),
                row["ensemble_prob"],
                row["clim_prob"],
                row["nws_prob"],
                row["settled_yes"],
            )
        )

    result: dict[str, dict[str, float]] = {}
    for season, srows in season_rows.items():
        if len(srows) < _SEASONAL_MIN:
            _log.info(
                "calibrate_seasonal_weights: %s has %d rows (need %d) — skipping",
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
        city_rows.setdefault(city, []).append(
            (
                str(row["market_date"]),
                row["ensemble_prob"],
                row["clim_prob"],
                row["nws_prob"],
                row["settled_yes"],
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
        _log.debug("load_seasonal_weights: could not read %s: %s", p, exc)
        return {}


def load_city_weights(path: str | Path | None = None) -> dict[str, dict[str, float]]:
    """Load per-city weights from JSON. Returns {} if file missing."""
    p = Path(path) if path else Path(__file__).parent / "data" / "city_weights.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except Exception as exc:
        _log.debug("load_city_weights: could not read %s: %s", p, exc)
        return {}


_CONDITION_MIN = 100


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
            """
        ).fetchall()
    finally:
        con.close()

    type_rows: dict[str, list[tuple]] = {}
    for row in raw_rows:
        ctype = row["condition_type"]
        if not ctype:
            continue
        type_rows.setdefault(ctype, []).append(
            (
                str(row["market_date"]) if row["market_date"] else "",
                row["ensemble_prob"],
                row["clim_prob"],
                row["nws_prob"],
                row["settled_yes"],
            )
        )

    result: dict[str, dict[str, float]] = {}
    for ctype, crows in type_rows.items():
        if len(crows) < min_samples:
            _log.info(
                "calibrate_condition_weights: %s has %d rows (need %d) — skipping",
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
        _log.debug("load_condition_weights: could not read %s: %s", p, exc)
        return {}


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

    for ctype in ("above", "below", "between"):
        w = condition.get(ctype)
        if w is None:
            _log.warning(
                "No condition weights for %s — using hardcoded defaults", ctype
            )
        elif abs(sum(v for k, v in w.items() if not k.startswith("_")) - 1.0) > 0.005:
            _log.error("Condition weights for %s don't sum to 1.0: %s", ctype, w)
