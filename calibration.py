"""Offline blend-weight calibration for seasonal and per-city model optimization.

Run: python main.py calibrate
Outputs: data/seasonal_weights.json, data/city_weights.json

Every calibrator is fitted TWICE, once per horizon (batch-82): a multi-day fit
over days_out>=1 rows and a same-day fit over days_out=0 rows.  The two
populations are disjoint by construction and are written to separate files, so
a same-day run can never overwrite any part of the multi-day fit (user
decision, 2026-08-26 -- "single day and multi day calibration should be 100%
separate").  The read side, weather_markets._blend_weights, is the only place
the two ever meet: a same-day row prefers the same-day fit and falls back to
its multi-day sibling per tier while the same-day fit is still declining.
"""

from __future__ import annotations

import json
import logging
import math as _math
import random as _random
import sqlite3
from datetime import date as _date_type
from pathlib import Path

from paths import CITY_WEIGHTS_PATH as _CITY_WEIGHTS_PATH
from paths import CITY_WEIGHTS_SAMEDAY_PATH as _CITY_WEIGHTS_SAMEDAY_PATH
from paths import CONDITION_WEIGHTS_PATH, CONDITION_WEIGHTS_SAMEDAY_PATH, DATA_DIR
from paths import SEASONAL_WEIGHTS_PATH as _SEASONAL_WEIGHTS_PATH
from paths import SEASONAL_WEIGHTS_SAMEDAY_PATH as _SEASONAL_WEIGHTS_SAMEDAY_PATH
from tracker import (
    _GATE_COUPLED_EXCLUDED_CONDITION_TYPES,
    _condition_type_not_in_sql,
)
from utils import utc_today as _utc_today

_log = logging.getLogger(__name__)

_SEASONAL_MIN = (
    20  # D6: lowered from 50 — calibration fires sooner as trades accumulate
)
_CITY_MIN = 50  # P3-7/P3-25: raised to 50 for statistical reliability (SE ~0.07)
_N_RANDOM_SEARCH = 200  # P3-7: random search replaces exhaustive 5,151-triple grid
_BRIER_IMPROVEMENT_GATE = 0.005  # min val-set improvement to accept calibrated weights
_RECENCY_HALFLIFE_DAYS = 90  # exponential decay: trade 90 days old gets ~37% weight

# M-13(c): shadow condition-type families (not real above/below/between
# temperature conditions) that must never silently accumulate a live
# blend-weight entry just by crossing a row-count floor -- single source of
# truth for the exclusion list _load_rows (seasonal/city) and
# calibrate_condition_weights both need. 'between' is a real value for
# calibrate_condition_weights (it's one of the three condition types that
# function calibrates) but not for _load_rows's multiday_predictions pool
# (seasonal/city calibration is above/below-only, 'between' has its own
# separate condition-weight model) -- callers add it to this list
# themselves where it needs excluding, rather than baking it in here.
#
# batch-57 item 2 (backlog.txt "CALIBRATION.PY/ML_BIAS.PY/MAIN.PY STILL HAVE
# THE STATIC HARDCODED BRIER CONDITION_TYPE EXCLUSION TUPLE"): now DERIVED
# from tracker's canonical registry instead of being a fourth hand-written
# copy, so a new shadow-only market family added there reaches this file
# automatically. Sourced from _GATE_COUPLED_EXCLUDED_CONDITION_TYPES (the
# gate-backed families -- 5 at batch-57, 6 since batch-54 added
# 'tornado_count') rather than _ALWAYS_EXCLUDED_CONDITION_TYPES (the same
# set plus 'between') specifically because of the 'between' carve-out
# documented above -- that difference was verified as deliberate scoping,
# not drift, before consolidating: the pre-batch-57 literal was byte-for-byte
# those same 5 names in this same order, and batch-54 arrived through the
# registry exactly as this consolidation intended.
_SHADOW_CONDITION_TYPES: tuple[str, ...] = tuple(
    ct for ct, _gate_fn_name in _GATE_COUPLED_EXCLUDED_CONDITION_TYPES
)


def _compute_recency_weight(date_str: str) -> float:
    """Exponential decay weight so recent settled trades count more in calibration."""
    try:
        days_ago = (_utc_today() - _date_type.fromisoformat(str(date_str)[:10])).days
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
    # With < 10 val rows the _BRIER_IMPROVEMENT_GATE (0.005) is noise — a single
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
        # M-13: this rejection is the SAME "not actually calibrated, equal
        # weights returned" case as the _MIN_VAL_ROWS path above -- must
        # carry the same _uncalibrated flag so _blend_weights falls through
        # to the hardcoded days-out schedule instead of treating these as a
        # real (if coincidentally equal) fit.
        return {
            "ensemble": equal[0],
            "climatology": equal[1],
            "nws": equal[2],
            "_uncalibrated": True,
        }

    return {"ensemble": best[0], "climatology": best[1], "nws": best[2]}


# 'between' added back here by the caller, exactly as _SHADOW_CONDITION_TYPES's
# own comment above prescribes: this pool is the seasonal/city blend-weight
# population, which is above/below-only ('between' has its own separate
# condition-weight model). Losing this line would silently let 'between' rows
# -- with their structurally larger calibration gap -- into the grid search
# that fits weights feeding live analyze_trade blending, so it is asserted in
# tests/test_calibration.py rather than left to the comment alone
# (opus-review finding L2).
_LOAD_ROWS_EXCLUDED_TYPES = ("between", *_SHADOW_CONDITION_TYPES)
# batch-57 opus-review finding L1: build the clause with tracker's shared
# parameterised helper rather than hand-writing the NULL-OR-NOT-IN wrapper and
# interpolating the values unescaped. Keeps clause SHAPE, not just the name
# list, from drifting away from the other consolidated sites.
_LOAD_ROWS_COND_CLAUSE, _LOAD_ROWS_COND_PARAMS = _condition_type_not_in_sql(
    frozenset(_LOAD_ROWS_EXCLUDED_TYPES)
)


# batch-82: the two calibration horizons. Every calibrator in this module is
# run once per horizon over a DISJOINT row population, and the results are
# written to separate files, so neither fit can contaminate the other.
#
# The boundary is days_out=0, chosen to match the two places the repo already
# draws it: tracker's multiday_predictions view ("days_out IS NULL OR >= 1")
# and ml_bias's 'sameday' temperature-scaling pool. A three-way same-day /
# next-day / multi-day split was considered and rejected on the data: of the
# rows that actually satisfy the fit's own NOT NULL requirements, 89 sit at
# D+1 and ZERO at D+2-and-up (measured 2026-08-26), so a third bucket would
# leave the multi-day fit with an empty population.
_HORIZON_MULTIDAY = "multiday"
_HORIZON_SAMEDAY = "sameday"
_CALIBRATION_HORIZONS: tuple[str, ...] = (_HORIZON_MULTIDAY, _HORIZON_SAMEDAY)

# tracker.py's multiday_predictions view gives its own reason for excluding
# days_out=0: those rows "use METAR-locked probs, not ensemble forecasts". The
# same-day fit adopts that population, so it must adopt the reason too --
# batch-75 spent a session removing exactly this kind of population mixing,
# and the batch-82 handoff was explicit that metar_lockout rows must not be
# folded in.
#
# Today they are already excluded, but only ACCIDENTALLY: all 106 settled
# metar_lockout rows have NULL ensemble/nws/clim probs, so the three NOT NULL
# predicates drop them (measured 2026-08-26: the same-day pool is 77/77
# method='ensemble'). That is a property of what currently gets logged, not of
# this query. If component probs ever start being written on locked rows, 106+
# rows whose live decision path bypassed the blend entirely would enter the fit
# silently. Stated explicitly here so it is structural (opus review finding).
#
# NOTE FOR FIXTURE AUTHORS: this makes `predictions.method` a hard requirement
# for any test DB that reaches calibrate_and_save (which runs BOTH horizons) or
# a same-day calibrator directly. tests/test_phase2_batch_p.py's _make_db
# needed the column added for exactly this reason. A multi-day-only fixture is
# unaffected -- the predicate lives on the same-day branch alone.
_SAMEDAY_METAR_EXCLUSION = "AND (p.method IS NULL OR p.method != 'metar_lockout')"
_SAMEDAY_ROW_CLAUSE = f"AND p.days_out = 0 {_SAMEDAY_METAR_EXCLUSION}"


def _check_horizon(horizon: str) -> None:
    """Reject an unknown horizon loudly.

    Deliberately raises rather than falling back to a default: a typo'd
    horizon that silently fitted the multi-day population and then got
    written to the same-day file would produce exactly the cross-horizon
    contamination this split exists to prevent, and nothing downstream could
    detect it -- the file would be well-formed and its weights plausible.
    """
    if horizon not in _CALIBRATION_HORIZONS:
        raise ValueError(
            f"unknown calibration horizon {horizon!r} "
            f"(expected one of {_CALIBRATION_HORIZONS})"
        )


def _load_rows(db_path: Path, *, horizon: str = _HORIZON_MULTIDAY) -> list[sqlite3.Row]:
    """Load the seasonal/city blend-weight population for one horizon.

    Shared by calibrate_seasonal_weights and calibrate_city_weights -- the
    horizon is a parameter rather than a forked copy of this query so the
    'between'/shadow condition-type exclusion below can only ever be written
    once.

    The multi-day branch keeps reading tracker's multiday_predictions view
    verbatim, so this parameterisation is provably a no-op for the existing
    (default) callers.
    """
    _check_horizon(horizon)
    source = "predictions" if horizon == _HORIZON_SAMEDAY else "multiday_predictions"
    horizon_clause = _SAMEDAY_ROW_CLAUSE if horizon == _HORIZON_SAMEDAY else ""
    with sqlite3.connect(str(db_path)) as con:
        con.row_factory = sqlite3.Row
        return con.execute(
            f"""
            SELECT p.city, p.market_date, p.condition_type,
                   p.ensemble_prob, p.nws_prob, p.clim_prob,
                   o.settled_yes
            FROM {source} p
            JOIN outcomes_valid o ON p.ticker = o.ticker
            WHERE p.ensemble_prob IS NOT NULL
              AND p.nws_prob IS NOT NULL
              AND p.clim_prob IS NOT NULL
              AND o.settled_yes IS NOT NULL
              AND {_LOAD_ROWS_COND_CLAUSE}
              {horizon_clause}
            """,
            _LOAD_ROWS_COND_PARAMS,
        ).fetchall()


def calibrate_seasonal_weights(
    db_path: str | Path,
    cutoff_date: str | None = None,
    *,
    horizon: str = _HORIZON_MULTIDAY,
) -> dict[str, dict[str, float]]:
    """Grid-search optimal blend weights per season.

    Returns: {season: {ensemble, climatology, nws}} for seasons with >= _SEASONAL_MIN rows.
    Weights are trained on rows before cutoff_date (auto 80/20 split if omitted).
    horizon selects the row population; see _load_rows.
    """
    db_path = Path(db_path)
    rows = _load_rows(db_path, horizon=horizon)

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
                "calibrate_seasonal_weights[%s]: %s has %d rows (need %d) — "
                "using neutral defaults",
                horizon,
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
    *,
    horizon: str = _HORIZON_MULTIDAY,
) -> dict[str, dict[str, float]]:
    """Grid-search optimal blend weights per city.

    Returns: {city: {ensemble, climatology, nws}} for cities with >= _CITY_MIN rows.
    Weights are trained on rows before cutoff_date (auto 80/20 split if omitted).
    horizon selects the row population; see _load_rows.
    """
    db_path = Path(db_path)
    rows = _load_rows(db_path, horizon=horizon)

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
                "calibrate_city_weights[%s]: %s has %d rows (need %d) — skipping",
                horizon,
                city,
                len(crows),
                _CITY_MIN,
            )
            continue
        train, val = _split_rows(crows, cutoff_date)
        result[city] = _best_weights(train, val)
    return result


def _load_weights_file(
    path: str | Path | None, default_path: Path, label: str
) -> dict[str, dict[str, float]]:
    """Shared body of the six load_*_weights loaders.

    Extracted in batch-82 rather than copy-pasting the existing three a second
    time for the same-day horizon. The behaviour is unchanged and is relied on
    by weather_markets._maybe_refresh_calibration_weights, which specifically
    documents that these loaders swallow their own JSON errors and return {}
    instead of raising -- so an absent OR corrupt same-day file degrades to
    "no same-day fit", which _blend_weights already handles by falling through
    to the multi-day tier.
    """
    p = Path(path) if path else default_path
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except Exception as exc:
        _log.warning("%s: could not read %s: %s", label, p, exc)
        return {}


def load_seasonal_weights(
    path: str | Path | None = None,
) -> dict[str, dict[str, float]]:
    """Load multi-day seasonal weights from JSON. Returns {} if file missing."""
    return _load_weights_file(path, _SEASONAL_WEIGHTS_PATH, "load_seasonal_weights")


def load_city_weights(path: str | Path | None = None) -> dict[str, dict[str, float]]:
    """Load multi-day per-city weights from JSON. Returns {} if file missing."""
    return _load_weights_file(path, _CITY_WEIGHTS_PATH, "load_city_weights")


def load_seasonal_weights_sameday(
    path: str | Path | None = None,
) -> dict[str, dict[str, float]]:
    """Load same-day (days_out=0) seasonal weights. Returns {} if file missing."""
    return _load_weights_file(
        path, _SEASONAL_WEIGHTS_SAMEDAY_PATH, "load_seasonal_weights_sameday"
    )


def load_city_weights_sameday(
    path: str | Path | None = None,
) -> dict[str, dict[str, float]]:
    """Load same-day (days_out=0) per-city weights. Returns {} if file missing."""
    return _load_weights_file(
        path, _CITY_WEIGHTS_SAMEDAY_PATH, "load_city_weights_sameday"
    )


_CONDITION_MIN = (
    60  # 60 * 0.2 = 12 val rows — minimum for improvement gate to be meaningful
)

# Same shared-helper treatment as _LOAD_ROWS_COND_CLAUSE (opus-review finding
# L1), but WITHOUT 'between': this function calibrates above/below/between, so
# 'between' is one of the three types it is here to fit and must stay in the
# population. That asymmetry with _LOAD_ROWS_EXCLUDED_TYPES is the whole reason
# _SHADOW_CONDITION_TYPES omits 'between' and leaves it to callers.
_COND_WEIGHTS_COND_CLAUSE, _COND_WEIGHTS_COND_PARAMS = _condition_type_not_in_sql(
    frozenset(_SHADOW_CONDITION_TYPES)
)


def calibrate_condition_weights(
    db_path: str | Path,
    min_samples: int = _CONDITION_MIN,
    cutoff_date: str | None = None,
    *,
    horizon: str = _HORIZON_MULTIDAY,
) -> dict[str, dict[str, float]]:
    """Grid-search optimal blend weights per condition type (above/below/between).

    Returns: {condition_type: {ensemble, climatology, nws}} for types with >= min_samples rows.
    Weights are trained on rows before cutoff_date (auto 80/20 split if omitted).
    horizon selects the row population (batch-82).

    Unlike _load_rows this reads `predictions` with an inline days_out
    predicate rather than the multiday_predictions view. That asymmetry is
    pre-existing and deliberately left alone here: pointing the MULTI-DAY
    branch at the view would be a provable behavioural no-op, but it breaks
    the `_make_db` fixture in tests/test_phase2_batch_p.py, which creates
    `outcomes_valid` but no multiday_predictions view -- and that file is not
    in this change's scoped test set. (tests/test_phase3_batch_c.py DOES
    create the view, at :31, so it would be unaffected; an earlier draft of
    this comment named both files and was wrong.) The SAME-DAY branch could
    never use the view regardless: the view excludes days_out = 0 by
    construction. Filed in backlog.txt as "THE MULTI-DAY HORIZON PREDICATE IS
    DEFINED IN TWO PLACES".
    """
    _check_horizon(horizon)
    horizon_predicate = (
        f"p.days_out = 0 {_SAMEDAY_METAR_EXCLUSION}"
        if horizon == _HORIZON_SAMEDAY
        else "(p.days_out IS NULL OR p.days_out >= 1)"
    )
    db_path = Path(db_path)
    con = sqlite3.connect(str(db_path))
    try:
        con.row_factory = sqlite3.Row
        raw_rows = con.execute(
            f"""
            SELECT p.condition_type, p.market_date,
                   p.ensemble_prob, p.clim_prob, p.nws_prob,
                   o.settled_yes
            FROM predictions p
            JOIN outcomes_valid o ON p.ticker = o.ticker
            WHERE p.ensemble_prob IS NOT NULL
              AND p.clim_prob IS NOT NULL
              AND p.nws_prob IS NOT NULL
              AND o.settled_yes IS NOT NULL
              AND {horizon_predicate}
              AND {_COND_WEIGHTS_COND_CLAUSE}
            """,
            _COND_WEIGHTS_COND_PARAMS,
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
                "calibrate_condition_weights[%s]: %s has %d rows (need %d) — "
                "using neutral defaults",
                horizon,
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
    """Load multi-day per-condition-type weights. Returns {} if file missing."""
    return _load_weights_file(path, CONDITION_WEIGHTS_PATH, "load_condition_weights")


def load_condition_weights_sameday(
    path: str | Path | None = None,
) -> dict[str, dict[str, float]]:
    """Load same-day (days_out=0) per-condition-type weights. {} if missing."""
    return _load_weights_file(
        path, CONDITION_WEIGHTS_SAMEDAY_PATH, "load_condition_weights_sameday"
    )


def _preserve_hand_tuned_weights(
    fresh: dict, disk_path: Path, label: str, *, allow_missing: bool = False
) -> None:
    """Preserve manually-set weights auto-calibration would otherwise drop
    or overwrite with a neutral/uncalibrated placeholder (M-13b).

    Two cases: a key present in `fresh` but flagged _uncalibrated
    (insufficient val rows, or no brier improvement — _best_weights'
    fallback), and (only when allow_missing=True) a key ABSENT from `fresh`
    entirely. The absent case is City-only: calibrate_city_weights (unlike
    calibrate_seasonal_weights/calibrate_condition_weights, which always
    emit every season/condition-type key with a _neutral placeholder) omits
    the key outright for a city that doesn't clear _CITY_MIN — without this,
    a hand-tuned city below that floor would be silently dropped from the
    file entirely, not just overwritten.

    allow_missing defaults to False for seasonal/condition specifically so a
    key that's ABSENT from a complete, canonical result (e.g. a shadow
    condition type deliberately excluded by calibrate_condition_weights'
    own query, or any other on-disk key that no longer belongs) never gets
    silently resurrected — those callers' result dicts are meant to be the
    full canonical key set, so a key missing from them is a deliberate
    exclusion, not an under-sampled placeholder. Mutates `fresh` in place.
    """
    if not disk_path.exists():
        return
    try:
        existing = json.loads(disk_path.read_text())
    except Exception as exc:
        _log.warning(
            "calibrate_and_save: failed to preserve %s weights: %s "
            "— freshly-calibrated values will overwrite hand-tuned weights",
            label,
            exc,
        )
        return
    for key, entry in existing.items():
        if not isinstance(entry, dict) or entry.get("_uncalibrated"):
            continue
        fresh_entry = fresh.get(key)
        if key not in fresh:
            if allow_missing:
                fresh[key] = entry
            continue
        if isinstance(fresh_entry, dict) and fresh_entry.get("_uncalibrated"):
            fresh[key] = entry


def calibrate_and_save(
    db_path: str | Path | None = None,
    data_dir: str | Path | None = None,
) -> tuple[dict, dict, dict]:
    """Run all three blend-weight calibrations and write results atomically to disk.

    This is the single canonical implementation used by both ``py main.py calibrate``
    and the F3 cron auto-calibration block.  Keeping the disk-write logic here means
    changes to output paths or format only need to happen in one place.

    Returns (seasonal, city, condition) dicts for the MULTI-DAY horizon — same
    as calling each function individually.  Cache invalidation (e.g.
    weather_markets._CONDITION_WEIGHTS) is the caller's responsibility to avoid
    a circular import dependency.

    batch-82: this also fits and writes the three same-day (days_out=0) weight
    files as a side effect, so cron.py's weekly auto-calibration picks the
    same-day horizon up with no change on its side.  The return stays a
    3-tuple deliberately — cron.py unpacks exactly three values at two call
    sites and is not in this change's owned file set; the same-day dicts are
    read back from disk by callers that want to display them (main.cmd_calibrate)
    and refreshed in-process by weather_markets._maybe_refresh_calibration_weights,
    which is mtime-driven and therefore already covers every writer.

    Raises on DB read failure so callers can handle the error message appropriately.
    """
    from tracker import DB_PATH as _DB_PATH

    _db = Path(db_path) if db_path else _DB_PATH
    _dir = Path(data_dir) if data_dir else DATA_DIR
    _dir.mkdir(exist_ok=True)

    seasonal = calibrate_seasonal_weights(_db)
    city = calibrate_city_weights(_db)
    condition = calibrate_condition_weights(_db)

    # batch-82: the same-day fits. Separate calibrator invocations over a
    # disjoint (days_out=0) population, preserved against and written to
    # their OWN files -- nothing below ever reads or writes a multi-day file
    # with a same-day value, or vice versa.
    seasonal_sd = calibrate_seasonal_weights(_db, horizon=_HORIZON_SAMEDAY)
    city_sd = calibrate_city_weights(_db, horizon=_HORIZON_SAMEDAY)
    condition_sd = calibrate_condition_weights(_db, horizon=_HORIZON_SAMEDAY)

    # M-13b: preserve any manually-set weights auto-calibration left as
    # neutral/uncalibrated (insufficient samples) or dropped outright
    # (city). Without this, a weekly retrain on thin data would overwrite
    # (or, for city, silently drop) hand-tuned weights.
    _preserve_hand_tuned_weights(seasonal, _dir / "seasonal_weights.json", "seasonal")
    _preserve_hand_tuned_weights(
        city, _dir / "city_weights.json", "city", allow_missing=True
    )
    _preserve_hand_tuned_weights(
        condition, _dir / "condition_weights.json", "condition"
    )
    # Same preservation for the same-day files, each against its own file.
    # This is what stops a same-day fit that has already graduated from being
    # thrown away by a later run that happens to decline (e.g. a thin recent
    # validation split), exactly as for the multi-day files.
    _preserve_hand_tuned_weights(
        seasonal_sd, _dir / "seasonal_weights_sameday.json", "seasonal_sameday"
    )
    _preserve_hand_tuned_weights(
        city_sd, _dir / "city_weights_sameday.json", "city_sameday", allow_missing=True
    )
    _preserve_hand_tuned_weights(
        condition_sd, _dir / "condition_weights_sameday.json", "condition_sameday"
    )

    from safe_io import atomic_write_json_with_history

    atomic_write_json_with_history(seasonal, _dir / "seasonal_weights.json")
    atomic_write_json_with_history(city, _dir / "city_weights.json")
    atomic_write_json_with_history(condition, _dir / "condition_weights.json")
    atomic_write_json_with_history(seasonal_sd, _dir / "seasonal_weights_sameday.json")
    atomic_write_json_with_history(city_sd, _dir / "city_weights_sameday.json")
    atomic_write_json_with_history(
        condition_sd, _dir / "condition_weights_sameday.json"
    )

    _log.info(
        "calibrate_and_save: wrote multiday seasonal(%d) city(%d) condition(%d) "
        "and sameday seasonal(%d) city(%d) condition(%d) to %s",
        len(seasonal),
        len(city),
        len(condition),
        len(seasonal_sd),
        len(city_sd),
        len(condition_sd),
        _dir,
    )
    return seasonal, city, condition


def _validate_present_entries(table: dict, label: str) -> None:
    """Sum-to-1 / non-negative checks over whatever entries a table HAS.

    batch-82: used for the three same-day tables. Deliberately does not warn
    about an ABSENT key, unlike the multi-day seasonal/condition loops below:
    a missing same-day entry is the normal, correct state (the tier has not
    graduated yet) and _blend_weights handles it by falling through to the
    multi-day sibling, so warning on it would be pure noise on every startup.
    Same shape as the existing city loop, which has always worked this way
    because its key set is not fixed.
    """
    for key, w in table.items():
        if not isinstance(w, dict):
            continue
        if abs(sum(v for k, v in w.items() if not k.startswith("_")) - 1.0) > 0.005:
            _log.error("%s weights for %s don't sum to 1.0: %s", label, key, w)
        elif any(v < 0 for k, v in w.items() if not k.startswith("_")):
            _log.error("%s weights for %s contain negative values: %s", label, key, w)


def validate_weight_files(
    seasonal: dict | None = None,
    city: dict | None = None,
    condition: dict | None = None,
    seasonal_sameday: dict | None = None,
    city_sameday: dict | None = None,
    condition_sameday: dict | None = None,
) -> None:
    """P2-7: Warn on missing or malformed weight file entries at startup."""
    if seasonal is None:
        seasonal = load_seasonal_weights()
    if city is None:
        city = load_city_weights()
    if condition is None:
        condition = load_condition_weights()
    if seasonal_sameday is None:
        seasonal_sameday = load_seasonal_weights_sameday()
    if city_sameday is None:
        city_sameday = load_city_weights_sameday()
    if condition_sameday is None:
        condition_sameday = load_condition_weights_sameday()

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
        # L-9: reject negative individual weights — they produce probabilities outside [0,1]
        elif any(v < 0 for k, v in w.items() if not k.startswith("_")):
            _log.error("Condition weights for %s contain negative values: %s", ctype, w)

    # M-13: city weights were never validated at all — unlike season/condition,
    # there's no fixed expected-key list to check for absence (cities vary), so
    # this only validates whatever entries ARE present.
    for city_name, w in city.items():
        if not isinstance(w, dict):
            continue
        if abs(sum(v for k, v in w.items() if not k.startswith("_")) - 1.0) > 0.005:
            _log.error("City weights for %s don't sum to 1.0: %s", city_name, w)
        elif any(v < 0 for k, v in w.items() if not k.startswith("_")):
            _log.error("City weights for %s contain negative values: %s", city_name, w)

    # batch-82: the same-day tables get the malformed-value checks but not the
    # absent-key warning -- see _validate_present_entries.
    _validate_present_entries(seasonal_sameday, "Same-day seasonal")
    _validate_present_entries(city_sameday, "Same-day city")
    _validate_present_entries(condition_sameday, "Same-day condition")
