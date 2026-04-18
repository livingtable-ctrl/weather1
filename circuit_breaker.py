"""
Simple per-source circuit breaker.

States:
  CLOSED  — normal operation
  OPEN    — source is down; calls rejected immediately
  HALF-OPEN — recovery_timeout elapsed; next call is a probe
"""

from __future__ import annotations

import logging
import threading
import time

_log = logging.getLogger(__name__)


class CircuitOpenError(Exception):
    """Raised when a circuit breaker is open (source is down)."""

    def __init__(self, name: str):
        super().__init__(
            f"Circuit open for source '{name}' — skipping to avoid hammering"
        )
        self.source = name


class CircuitBreaker:
    def __init__(
        self, name: str, failure_threshold: int = 5, recovery_timeout: float = 300
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self._failure_count = 0
        self._opened_at: float | None = None
        self._wall_opened_at: float | None = None
        self._lock = threading.Lock()

    def is_open(self) -> bool:
        with self._lock:
            if self._opened_at is None:
                return False
            elapsed = time.monotonic() - self._opened_at
            if elapsed >= self.recovery_timeout:
                _log.info(
                    "Circuit '%s' half-open after %.0fs — allowing probe",
                    self.name,
                    elapsed,
                )
                self._opened_at = None
                self._wall_opened_at = None
                self._failure_count = 0
                return False
            return True

    def record_failure(self) -> None:
        with self._lock:
            self._failure_count += 1
            if self._failure_count >= self.failure_threshold:
                if self._opened_at is None:
                    self._opened_at = time.monotonic()
                    self._wall_opened_at = time.time()
                    _log.warning(
                        "Circuit '%s' OPEN after %d failures — will retry in %.0fs",
                        self.name,
                        self._failure_count,
                        self.recovery_timeout,
                    )

    def record_success(self) -> None:
        with self._lock:
            self._failure_count = 0
            self._opened_at = None
            self._wall_opened_at = None

    @property
    def failure_count(self) -> int:
        with self._lock:
            return self._failure_count

    def seconds_open(self) -> float:
        """Wall-clock seconds since the circuit opened; 0.0 if currently closed."""
        with self._lock:
            if self._wall_opened_at is None:
                return 0.0
            return time.time() - self._wall_opened_at


# ── Flash Crash Circuit Breaker ───────────────────────────────────────────────


class FlashCrashCB:
    """
    Per-market flash crash detection.
    Trips when price moves > threshold_pct within window_seconds.
    Blocks that ticker for cooldown_seconds. Resets on restart (intentional).
    """

    def __init__(
        self,
        threshold_pct: float = 0.20,
        window_seconds: int = 300,
        cooldown_seconds: int = 600,
    ) -> None:
        self.threshold_pct = threshold_pct
        self.window_seconds = window_seconds
        self.cooldown_seconds = cooldown_seconds
        self._history: dict[str, list[tuple[float, float]]] = {}
        self._cooldowns: dict[str, float] = {}

    def check(self, ticker: str, current_price: float) -> bool:
        """Record price and return True if this observation triggered a crash."""
        now = time.time()
        window_start = now - self.window_seconds
        history = self._history.setdefault(ticker, [])
        # Prune old observations
        self._history[ticker] = [(ts, p) for ts, p in history if ts >= window_start]
        self._history[ticker].append((now, current_price))
        if len(self._history[ticker]) < 2:
            return False
        oldest_price = self._history[ticker][0][1]
        if oldest_price <= 0:
            return False
        if abs(current_price - oldest_price) / oldest_price >= self.threshold_pct:
            self._cooldowns[ticker] = now + self.cooldown_seconds
            _log.warning(
                "FLASH CRASH CB: %s — %.1f%% move in %ds window. Cooldown %ds.",
                ticker,
                abs(current_price - oldest_price) / oldest_price * 100,
                self.window_seconds,
                self.cooldown_seconds,
            )
            return True
        return False

    def is_in_cooldown(self, ticker: str) -> bool:
        return time.time() < self._cooldowns.get(ticker, 0)


# Module-level singleton
flash_crash_cb = FlashCrashCB()
