"""Offline blend-weight calibration for seasonal and per-city model optimization.

Run: python main.py calibrate
Outputs: data/seasonal_weights.json, data/city_weights.json
"""

from __future__ import annotations

import itertools
import json
import logging
import sqlite3
from pathlib import Path

_log = logging.getLogger(__name__)

_SEASONAL_MIN = (
    20  # D6: lowered from 50 — calibration fires sooner as trades accumulate
)
_CITY_MIN = 15  # D6: lowered from 30 — same rationale
_WEIGHT_STEP = 0.01  # C5: finer grid; 0.01 → 5,151 triples (still <1s); finds weights like (0.71, 0.12, 0.17)

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

_WEIGHT_VALUES = [round(i * _WEIGHT_STEP, 10) for i in range(int(1 / _WEIGHT_STEP) + 1)]
_WEIGHT_TRIPLES = [
    (e, c, n)
    for e, c, n in itertools.product(_WEIGHT_VALUES, repeat=3)
    if abs(e + c + n - 1.0) < 1e-9
]


def _brier(
    rows: list[tuple[float, float, float, int]], we: float, wc: float, wn: float
) -> float:
    """Compute Brier score for a weight combo against a list of (ens, clim, nws, settled)."""
    if not rows:
        return float("inf")
    total = 0.0
    for ens, clim, nws, settled in rows:
        p = we * ens + wc * clim + wn * nws
        total += (p - settled) ** 2
    return total / len(rows)


def _best_weights(rows: list[tuple[float, float, float, int]]) -> dict[str, float]:
    """Grid-search weight triples; return the one minimizing Brier score."""
    if not _WEIGHT_TRIPLES:
        _log.warning(
            "_best_weights: _WEIGHT_TRIPLES is empty — returning equal weights"
        )
        return {"ensemble": 1 / 3, "climatology": 1 / 3, "nws": 1 / 3}
    best_score = float("inf")
    best = (1 / 3, 1 / 3, 1 / 3)
    for we, wc, wn in _WEIGHT_TRIPLES:
        score = _brier(rows, we, wc, wn)
        if score < best_score:
            best_score = score
            best = (we, wc, wn)
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


def calibrate_seasonal_weights(db_path: str | Path) -> dict[str, dict[str, float]]:
    """Grid-search optimal blend weights per season.

    Returns: {season: {ensemble, climatology, nws}} for seasons with >= _SEASONAL_MIN rows.
    """
    db_path = Path(db_path)
    rows = _load_rows(db_path)

    season_rows: dict[str, list[tuple[float, float, float, int]]] = {}
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
        result[season] = _best_weights(srows)
    return result


def calibrate_city_weights(db_path: str | Path) -> dict[str, dict[str, float]]:
    """Grid-search optimal blend weights per city.

    Returns: {city: {ensemble, climatology, nws}} for cities with >= _CITY_MIN rows.
    """
    db_path = Path(db_path)
    rows = _load_rows(db_path)

    city_rows: dict[str, list[tuple[float, float, float, int]]] = {}
    for row in rows:
        city = row["city"]
        if not city:
            continue
        city_rows.setdefault(city, []).append(
            (
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
        result[city] = _best_weights(crows)
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
) -> dict[str, dict[str, float]]:
    """Grid-search optimal blend weights per condition type (above/below/between).

    Returns: {condition_type: {ensemble, climatology, nws}} for types with >= min_samples rows.
    """
    db_path = Path(db_path)
    con = sqlite3.connect(str(db_path))
    try:
        con.row_factory = sqlite3.Row
        raw_rows = con.execute(
            """
            SELECT p.condition_type,
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

    type_rows: dict[str, list[tuple[float, float, float, int]]] = {}
    for row in raw_rows:
        ctype = row["condition_type"]
        if not ctype:
            continue
        type_rows.setdefault(ctype, []).append(
            (
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
        result[ctype] = _best_weights(crows)
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
