"""system_health.py — lightweight health checks before trade execution."""

from __future__ import annotations

import logging
import os
from typing import NamedTuple

_log = logging.getLogger(__name__)

# Thresholds — all env-configurable
CPU_WARN_PCT = float(os.getenv("HEALTH_CPU_WARN_PCT", "85"))
MEM_WARN_PCT = float(os.getenv("HEALTH_MEM_WARN_PCT", "90"))
API_LATENCY_WARN_MS = float(os.getenv("HEALTH_API_LATENCY_WARN_MS", "5000"))


class HealthStatus(NamedTuple):
    healthy: bool
    reason: str  # empty string when healthy


def check_system_health() -> HealthStatus:
    """
    Check CPU, memory, and recent API latency.
    Returns HealthStatus(healthy=True, reason="") when all clear.
    Returns HealthStatus(healthy=False, reason=<why>) when a gate trips.

    psutil is optional — if not installed the CPU/memory checks are skipped
    and only API latency is evaluated.
    """
    # --- CPU / Memory ---
    try:
        import psutil

        # Use interval=None (non-blocking) — compares CPU usage since last call.
        # First call ever returns 0.0; all subsequent calls return a real reading.
        cpu = psutil.cpu_percent(interval=None)
        mem = psutil.virtual_memory().percent

        if cpu >= CPU_WARN_PCT:
            _log.warning(
                "system_health: CPU usage %.1f%% >= threshold %.1f%%", cpu, CPU_WARN_PCT
            )
            return HealthStatus(
                False, f"CPU usage too high: {cpu:.1f}% (threshold {CPU_WARN_PCT}%)"
            )

        if mem >= MEM_WARN_PCT:
            _log.warning(
                "system_health: memory usage %.1f%% >= threshold %.1f%%",
                mem,
                MEM_WARN_PCT,
            )
            return HealthStatus(
                False, f"Memory usage too high: {mem:.1f}% (threshold {MEM_WARN_PCT}%)"
            )

        _log.debug("system_health: CPU %.1f%% MEM %.1f%% — OK", cpu, mem)
    except ImportError:
        _log.debug("system_health: psutil not installed — skipping CPU/memory check")

    # --- API latency (read from execution_log if available) ---
    try:
        from execution_log import get_recent_api_latency_ms

        latency = get_recent_api_latency_ms()
        if latency is not None and latency >= API_LATENCY_WARN_MS:
            _log.warning(
                "system_health: recent API latency %.0fms >= threshold %.0fms",
                latency,
                API_LATENCY_WARN_MS,
            )
            return HealthStatus(
                False,
                f"API latency too high: {latency:.0f}ms (threshold {API_LATENCY_WARN_MS:.0f}ms)",
            )
        if latency is not None:
            _log.debug("system_health: API latency %.0fms — OK", latency)
    except Exception as exc:
        _log.debug("system_health: could not read API latency: %s", exc)

    return HealthStatus(True, "")
