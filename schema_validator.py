"""schema_validator.py — Lightweight schema validation for external API responses.

Validates that API responses contain required fields with correct types before
the bot uses them. Logs warnings on violations rather than crashing.
"""

from __future__ import annotations

import logging
import math

from utils import YES_ASK_KEYS, YES_BID_KEYS, coalesce_market_price

_log = logging.getLogger(__name__)


def _safe_price(data: dict, *keys: str) -> float | None:
    """Normalize a price value to decimal (0-1) via utils.coalesce_market_price,
    returning None if unparseable rather than raising.

    coalesce_market_price itself is deliberately unguarded for its other
    callers (order_executor.py's live reprice loop, weather_markets.
    parse_market_price), which already run inside a per-order/per-market
    try/except and are meant to raise on genuinely malformed input so it
    gets skipped, not silently treated as $0. schema_validator.py is a
    defensive layer whose whole job is to never crash the caller on bad
    API data -- this wrapper is the one place that needs fail-soft
    behavior, so it lives here rather than weakening the shared function
    for everyone.
    """
    try:
        return coalesce_market_price(data, *keys)
    except (TypeError, ValueError):
        return None


def validate_market(data: dict, source: str = "kalshi") -> bool:
    """
    Validate a Kalshi market dict has required fields and sane prices.
    Returns True if valid, False if critical fields are missing/wrong type.
    Logs a WARNING for each violation found.

    Accepts both legacy field names (yes_bid, yes_ask, volume) and the current
    API names (yes_bid_dollars, yes_ask_dollars, volume_fp).
    """
    # Fields that may appear under either a legacy or current name
    alias_fields: list[tuple[str, str, type | tuple]] = [
        ("yes_bid", "yes_bid_dollars", (int, float, str, type(None))),
        ("yes_ask", "yes_ask_dollars", (int, float, str, type(None))),
        ("volume", "volume_fp", (int, float, str, type(None))),
    ]
    ok = True

    if "ticker" not in data:
        _log.warning(
            "schema_validator[%s]: market missing required field 'ticker'", source
        )
        ok = False

    for primary, alias, expected_type in alias_fields:
        if primary in data or alias in data:
            pass  # at least one name present — type check skipped (API mixes str/float)
        else:
            _log.warning(
                "schema_validator[%s]: market missing required field %r",
                source,
                primary,
            )
            ok = False

    # Price range validation — only when both bid and ask are present
    raw_bid_present = (
        data.get("yes_bid") is not None or data.get("yes_bid_dollars") is not None
    )
    raw_ask_present = (
        data.get("yes_ask") is not None or data.get("yes_ask_dollars") is not None
    )
    if raw_bid_present and raw_ask_present:
        bid = _safe_price(data, *YES_BID_KEYS)
        ask = _safe_price(data, *YES_ASK_KEYS)
        ticker = data.get("ticker", "?")
        # $0.00 bid (no resting buy order) and $1.00 ask (no resting sell order
        # below par) are normal quotes for illiquid/extreme-strike markets, not
        # malformed data — only flag genuinely invalid values (negative, >1, NaN).
        if bid is None or not (0.0 <= bid <= 1.0):
            _log.warning(
                "schema_validator[%s]: %s yes_bid %.4f out of range [0, 1]",
                source,
                ticker,
                bid if bid is not None else float("nan"),
            )
            ok = False
        if ask is None or not (0.0 <= ask <= 1.0):
            _log.warning(
                "schema_validator[%s]: %s yes_ask %.4f out of range [0, 1]",
                source,
                ticker,
                ask if ask is not None else float("nan"),
            )
            ok = False
        # bid=0.00 AND ask=0.00 together means no resting quote at all (an
        # illiquid/dormant market, e.g. a far-future contract with zero
        # volume) -- not a crossed/inverted book. Matches weather_markets.
        # parse_market_price()'s has_quote = mid > 0 convention: this exact
        # (0.0, 0.0) pair is the one case that convention already treats as
        # "no real quote," not "malformed." A genuine inversion (bid >= ask
        # with either side actually nonzero) still gets flagged.
        if (
            bid is not None
            and ask is not None
            and bid >= ask
            and not (bid == 0.0 and ask == 0.0)
        ):
            _log.warning(
                "schema_validator[%s]: %s inverted spread bid %.4f >= ask %.4f",
                source,
                ticker,
                bid,
                ask,
            )
            ok = False

    return ok


def validate_forecast(data: dict, source: str = "open_meteo") -> bool:
    """
    Validate a forecast/weather API response dict.
    Returns True if valid, False if critical fields missing.
    """
    required: dict[str, type | tuple[type, ...]] = {
        "temperature_2m_max": (list, type(None)),
        "time": list,
    }
    ok = True
    for field, expected_type in required.items():
        val = data.get(field)
        if field not in data:
            _log.warning(
                "schema_validator[%s]: forecast missing required field %r",
                source,
                field,
            )
            ok = False
        elif not isinstance(val, expected_type):
            _log.warning(
                "schema_validator[%s]: forecast field %r has type %s, expected %s",
                source,
                field,
                type(val).__name__,
                expected_type.__name__
                if isinstance(expected_type, type)
                else str(expected_type),
            )
            ok = False
    return ok


def is_all_null(values: list | None) -> bool:
    """True if values is a non-empty list where every element is None.

    This is the signature of a dead/retired Open-Meteo model: the API
    returns HTTP 200 with a well-formed but entirely null payload, which
    passes validate_forecast() (it only checks type, not content) and looks
    identical to success to raise_for_status(). An empty list or None input
    returns False — those mean "no data for this range yet", a normal and
    distinct condition from "the model returned nothing but nulls".
    """
    if not values:
        return False
    return all(v is None for v in values)


def validate_nws_response(data: dict) -> bool:
    """Validate NWS API point forecast response.

    M-18a: checking only that `properties` is a dict let a well-formed-but-
    empty response (`{"properties": {}}`) pass -- the real payload's daily
    high/low periods live at `properties.periods`, so a response missing
    that key (or shipping an empty list) has no usable forecast data at all
    despite structurally validating. Require `periods` to be a non-empty
    list too, so a malformed/empty response is treated as a real fetch
    failure (record_failure(), no cache write) rather than a silent
    hour-long cache of {}.
    """
    required: dict[str, type | tuple[type, ...]] = {
        "properties": dict,
    }
    ok = True
    for field, expected_type in required.items():
        val = data.get(field)
        if field not in data:
            _log.warning(
                "schema_validator[nws]: response missing required field %r", field
            )
            ok = False
        elif not isinstance(val, expected_type):
            _log.warning(
                "schema_validator[nws]: field %r has type %s, expected %s",
                field,
                type(val).__name__,
                expected_type.__name__
                if isinstance(expected_type, type)
                else str(expected_type),
            )
            ok = False
    if ok:
        periods = data["properties"].get("periods")
        if not isinstance(periods, list) or not periods:
            _log.warning(
                "schema_validator[nws]: properties.periods missing or empty "
                "(got %r) -- treating as a malformed response",
                type(periods).__name__ if periods is not None else None,
            )
            ok = False
    return ok


_WEIGHT_SUM_TOLERANCE = 1e-6


def validate_weight_file(data: dict, source: str = "weights") -> bool:
    """
    Validate a source-blend weight file (city_weights.json,
    condition_weights.json, seasonal_weights.json): a dict mapping a
    category name (city, condition, or season) to a dict of source-name ->
    fractional weight, optionally with an `_uncalibrated` bool sentinel
    (already `.get()`-guarded by every real consumer of these files).

    An empty top-level dict is valid -- city_weights.json ships empty
    until calibration.py has enough per-city data to populate it, which is
    a legitimate "not yet calibrated" state, not corruption.

    Returns True if valid, False if any category's weights fail to parse
    as non-negative numbers summing to ~1.0. Logs a WARNING per violation.
    """
    if not isinstance(data, dict):
        _log.warning(
            "schema_validator[%s]: expected a dict at top level, got %s",
            source,
            type(data).__name__,
        )
        return False

    ok = True
    for category, entry in data.items():
        if not isinstance(entry, dict):
            _log.warning(
                "schema_validator[%s]: category %r value has type %s, expected dict",
                source,
                category,
                type(entry).__name__,
            )
            ok = False
            continue

        uncalibrated = entry.get("_uncalibrated")
        if uncalibrated is not None and not isinstance(uncalibrated, bool):
            _log.warning(
                "schema_validator[%s]: category %r _uncalibrated has type %s, "
                "expected bool",
                source,
                category,
                type(uncalibrated).__name__,
            )
            ok = False

        weight_keys = [k for k in entry if not k.startswith("_")]
        if not weight_keys:
            _log.warning(
                "schema_validator[%s]: category %r has no weight keys", source, category
            )
            ok = False
            continue

        total = 0.0
        for key in weight_keys:
            val = entry[key]
            if isinstance(val, bool) or not isinstance(val, int | float):
                _log.warning(
                    "schema_validator[%s]: category %r weight %r has type %s, "
                    "expected a number",
                    source,
                    category,
                    key,
                    type(val).__name__,
                )
                ok = False
                continue
            if not math.isfinite(val):
                # NaN/inf both satisfy isinstance(val, (int, float)) and
                # neither `< 0` nor a later `abs(total - 1.0) > tolerance`
                # sum check catches them -- NaN compares False against
                # everything (including itself), and inf added into a
                # running sum makes every subsequent comparison involving
                # it also NaN/inf-poisoned, silently passing as "valid"
                # without this explicit check.
                _log.warning(
                    "schema_validator[%s]: category %r weight %r is %s, "
                    "expected a finite number",
                    source,
                    category,
                    key,
                    val,
                )
                ok = False
                continue
            if val < 0:
                _log.warning(
                    "schema_validator[%s]: category %r weight %r is negative (%s)",
                    source,
                    category,
                    key,
                    val,
                )
                ok = False
                continue
            total += val

        if abs(total - 1.0) > _WEIGHT_SUM_TOLERANCE:
            _log.warning(
                "schema_validator[%s]: category %r weights sum to %s, expected ~1.0",
                source,
                category,
                total,
            )
            ok = False

    return ok


def validate_temperature_scale_file(
    data: dict, source: str = "temperature_scale"
) -> bool:
    """
    Validate temperature_scale.json: either the legacy single-value format
    ({"T": <float>}) or the current per-condition format ({condition:
    {"T": <float>, "n": <int>}, ...}) that ml_bias.py's own loader (see
    `_load_temperature_scale`) already parses -- this mirrors that loader's exact
    tolerance (any top-level key whose value is a dict with a numeric "T"
    is treated as a condition entry; other keys are ignored, matching the
    loader's own `if isinstance(v, dict) and "T" in v` filter) rather than
    inventing a stricter shape the loader doesn't actually require.

    Returns True if valid, False if a "T" value is present but not a
    positive number, or a present "n" isn't a non-negative int. Logs a
    WARNING per violation.
    """
    if not isinstance(data, dict):
        _log.warning(
            "schema_validator[%s]: expected a dict at top level, got %s",
            source,
            type(data).__name__,
        )
        return False

    ok = True

    def _check_t(label: str, t_val: object) -> bool:
        if isinstance(t_val, bool) or not isinstance(t_val, int | float):
            _log.warning(
                "schema_validator[%s]: %s T has type %s, expected a number",
                source,
                label,
                type(t_val).__name__,
            )
            return False
        # NaN/inf both satisfy isinstance(t_val, (int, float)) and NaN
        # compares False against everything including `<= 0` -- without
        # this explicit check a NaN or infinite T silently passes.
        if not math.isfinite(t_val):
            _log.warning(
                "schema_validator[%s]: %s T is %s, expected a finite number",
                source,
                label,
                t_val,
            )
            return False
        if t_val <= 0:
            _log.warning(
                "schema_validator[%s]: %s T is %s, expected > 0", source, label, t_val
            )
            return False
        return True

    if "T" in data:
        # Legacy single-value format -- matches the real loader's own
        # `if "T" in raw:` check exactly (no type guard): a top-level "T"
        # key of ANY shape takes this branch there too, and a non-numeric
        # value (e.g. a dict) crashes the loader's `float(raw["T"])`
        # (caught by its own try/except, degrading to "file unreadable").
        # _check_t below reports that same shape mismatch as a validator
        # warning instead of a swallowed exception.
        ok = _check_t("legacy top-level", data["T"])
        return ok

    for condition, entry in data.items():
        if not isinstance(entry, dict) or "T" not in entry:
            continue  # matches ml_bias.py's own loader tolerance for stray keys
        if not _check_t(f"condition {condition!r}", entry["T"]):
            ok = False
        n_val = entry.get("n")
        if n_val is not None and (
            isinstance(n_val, bool) or not isinstance(n_val, int) or n_val < 0
        ):
            _log.warning(
                "schema_validator[%s]: condition %r n is %r, expected a non-negative int",
                source,
                condition,
                n_val,
            )
            ok = False

    return ok
