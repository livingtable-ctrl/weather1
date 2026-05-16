"""system_health.py — lightweight health checks before trade execution."""

from __future__ import annotations

import logging
import os
from typing import NamedTuple

_log = logging.getLogger(__name__)

# Thresholds — all env-configurable
CPU_WARN_PCT = float(os.getenv("HEALTH_CPU_WARN_PCT", "85"))
MEM_HALT_PCT = float(os.getenv("MEM_HALT_PCT", "95"))
MEM_WARN_PCT = float(os.getenv("HEALTH_MEM_WARN_PCT", "90"))
API_LATENCY_WARN_MS = float(os.getenv("HEALTH_API_LATENCY_WARN_MS", "5000"))
# Fail the health gate when more than this fraction of recent API calls errored
API_ERROR_RATE_HALT = float(os.getenv("HEALTH_API_ERROR_RATE_HALT", "0.50"))
API_ERROR_RATE_WINDOW = int(os.getenv("HEALTH_API_ERROR_RATE_WINDOW", "20"))


class HealthStatus(NamedTuple):
    healthy: bool
    reason: str  # empty string when healthy


def _check_api_failure_rate() -> HealthStatus:
    """Return unhealthy if recent Kalshi API calls are failing at a high rate."""
    try:
        from tracker import _conn, init_db

        init_db()
        with _conn() as con:
            rows = con.execute(
                """
                SELECT status_code, error
                FROM api_requests
                ORDER BY id DESC
                LIMIT ?
                """,
                (API_ERROR_RATE_WINDOW,),
            ).fetchall()
        if not rows:
            return HealthStatus(True, "")
        errors = sum(
            1 for r in rows if (r[0] is not None and r[0] >= 500) or r[1] is not None
        )
        rate = errors / len(rows)
        if rate >= API_ERROR_RATE_HALT:
            return HealthStatus(
                False,
                f"API error rate {rate:.0%} over last {len(rows)} calls "
                f"(threshold {API_ERROR_RATE_HALT:.0%})",
            )
        _log.debug(
            "system_health: API error rate %.0f%% over %d calls — OK",
            rate * 100,
            len(rows),
        )
    except Exception as exc:
        _log.error(
            "system_health: API failure-rate check raised: %s — blocking trade", exc
        )
        return HealthStatus(False, f"API failure-rate check error: {exc}")
    return HealthStatus(True, "")


def _check_platt_sanity() -> HealthStatus:
    """Return unhealthy if any loaded Platt model has A <= 0 (signal inversion)."""
    try:
        from weather_markets import _load_platt_models

        models = _load_platt_models()
        for city, (a, _b) in models.items():
            if a <= 0:
                return HealthStatus(
                    False,
                    f"Platt model for {city} has A={a:.4f} (<=0) — signal inversion risk",
                )
    except Exception as exc:
        _log.error("system_health: Platt sanity check raised: %s — blocking trade", exc)
        return HealthStatus(False, f"Platt sanity check error: {exc}")
    return HealthStatus(True, "")


def check_system_health() -> HealthStatus:
    """
    Check CPU, memory, API failure rate, and Platt model sanity.
    Returns HealthStatus(healthy=True, reason="") when all clear.
    Returns HealthStatus(healthy=False, reason=<why>) when a gate trips.
    Fails closed on any internal error — a broken health check must not allow trades.

    psutil is optional — if not installed the CPU/memory checks are skipped.
    """
    try:
        # --- CPU / Memory ---
        try:
            import psutil

            cpu = psutil.cpu_percent(interval=None)
            mem = psutil.virtual_memory().percent

            if cpu >= CPU_WARN_PCT:
                _log.warning(
                    "system_health: CPU usage %.1f%% >= threshold %.1f%% (warning only)",
                    cpu,
                    CPU_WARN_PCT,
                )
            if mem >= MEM_HALT_PCT:
                return HealthStatus(
                    False,
                    f"memory usage {mem:.1f}% >= halt threshold {MEM_HALT_PCT:.1f}%",
                )
            if mem >= MEM_WARN_PCT:
                _log.warning(
                    "system_health: memory usage %.1f%% >= warning threshold %.1f%%",
                    mem,
                    MEM_WARN_PCT,
                )
            _log.debug("system_health: CPU %.1f%% MEM %.1f%% — OK", cpu, mem)
        except ImportError:
            _log.debug(
                "system_health: psutil not installed — skipping CPU/memory check"
            )

        # --- API failure rate ---
        api_status = _check_api_failure_rate()
        if not api_status.healthy:
            return api_status

        # --- Platt model sanity ---
        platt_status = _check_platt_sanity()
        if not platt_status.healthy:
            return platt_status

    except Exception as exc:
        _log.error("system_health: check raised unexpectedly: %s — blocking trade", exc)
        return HealthStatus(False, f"health check error: {exc}")

    return HealthStatus(True, "")
