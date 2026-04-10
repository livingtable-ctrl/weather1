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
                self._failure_count = 0
                return False
            return True

    def record_failure(self) -> None:
        with self._lock:
            self._failure_count += 1
            if self._failure_count >= self.failure_threshold:
                if self._opened_at is None:
                    self._opened_at = time.monotonic()
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
