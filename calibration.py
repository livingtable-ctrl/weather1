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

_SEASONAL_MIN = 50  # minimum settled predictions with source probs per season
_CITY_MIN = 30  # minimum settled predictions with source probs per city
_WEIGHT_STEP = 0.05  # grid resolution; 0.05 → 66 unique (w_e, w_c, w_n) triples

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
    total = 0.0
    for ens, clim, nws, settled in rows:
        p = we * ens + wc * clim + wn * nws
        total += (p - settled) ** 2
    return total / len(rows)


def _best_weights(rows: list[tuple[float, float, float, int]]) -> dict[str, float]:
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
            SELECT p.city, p.market_date,
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
