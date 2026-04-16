"""schema_validator.py — Lightweight schema validation for external API responses.

Validates that API responses contain required fields with correct types before
the bot uses them. Logs warnings on violations rather than crashing.
"""

from __future__ import annotations

import logging

_log = logging.getLogger(__name__)


def validate_market(data: dict, source: str = "kalshi") -> bool:
    """
    Validate a Kalshi market dict has required fields.
    Returns True if valid, False if critical fields are missing/wrong type.
    Logs a WARNING for each violation found.
    """
    required: dict[str, type | tuple[type, ...]] = {
        "ticker": str,
        "yes_bid": (int, float, type(None)),
        "yes_ask": (int, float, type(None)),
        "volume": (int, float, type(None)),
    }
    ok = True
    for field, expected_type in required.items():
        val = data.get(field)
        if field not in data:
            _log.warning(
                "schema_validator[%s]: market missing required field %r", source, field
            )
            ok = False
        elif not isinstance(val, expected_type):
            _log.warning(
                "schema_validator[%s]: market field %r has type %s, expected %s",
                source,
                field,
                type(val).__name__,
                expected_type.__name__
                if isinstance(expected_type, type)
                else str(expected_type),
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
