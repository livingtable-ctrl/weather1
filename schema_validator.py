"""schema_validator.py — Lightweight schema validation for external API responses.

Validates that API responses contain required fields with correct types before
the bot uses them. Logs warnings on violations rather than crashing.
"""

from __future__ import annotations

import logging

_log = logging.getLogger(__name__)


def _price_to_decimal(v: object) -> float | None:
    """Normalize a price value to decimal (0–1). Returns None if unparseable."""
    try:
        f = float(v)  # type: ignore[arg-type]
        return f / 100.0 if f > 1.0 else f
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
    raw_bid = (
        data.get("yes_bid")
        if data.get("yes_bid") is not None
        else data.get("yes_bid_dollars")
    )
    raw_ask = (
        data.get("yes_ask")
        if data.get("yes_ask") is not None
        else data.get("yes_ask_dollars")
    )
    if raw_bid is not None and raw_ask is not None:
        bid = _price_to_decimal(raw_bid)
        ask = _price_to_decimal(raw_ask)
        ticker = data.get("ticker", "?")
        if bid is None or not (0.0 < bid < 1.0):
            _log.debug(
                "schema_validator[%s]: %s yes_bid %.4f out of range (0, 1)",
                source,
                ticker,
                bid if bid is not None else float("nan"),
            )
            ok = False
        if ask is None or not (0.0 < ask < 1.0):
            _log.debug(
                "schema_validator[%s]: %s yes_ask %.4f out of range (0, 1)",
                source,
                ticker,
                ask if ask is not None else float("nan"),
            )
            ok = False
        if bid is not None and ask is not None and bid >= ask:
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


def validate_nws_response(data: dict) -> bool:
    """Validate NWS API point forecast response."""
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
    return ok
