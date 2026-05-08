"""
Simple per-source circuit breaker.

States:
  CLOSED  — normal operation
  OPEN    — source is down; calls rejected immediately
  HALF-OPEN — recovery_timeout elapsed; next call is a probe
"""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path

_log = logging.getLogger(__name__)

_CB_STATE_PATH = Path(__file__).parent / "data" / ".cb_state.json"


class CircuitOpenError(Exception):
    """Raised when a circuit breaker is open (source is down)."""

    def __init__(self, name: str):
        super().__init__(
            f"Circuit open for source '{name}' — skipping to avoid hammering"
        )
        self.source = name


class CircuitBreaker:
    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 300,
        backoff_multiplier: float = 1.0,
        burst_window: float = 0.0,
        persist: bool = True,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.backoff_multiplier = backoff_multiplier
        # Failures within burst_window seconds of the previous one count as one event.
        # Set > 0 to absorb parallel request failures that all land simultaneously.
        self.burst_window = burst_window
        self._persist = persist
        self._failure_count = 0
        self._trip_count = 0  # how many times the circuit has opened
        self._opened_at: float | None = None
        self._wall_opened_at: float | None = None
        self._current_timeout: float = recovery_timeout
        self._last_failure_at: float | None = None
        self._lock = threading.Lock()
        self._load_state()

    def _load_state(self) -> None:
        if not self._persist:
            return
        try:
            state = (
                json.loads(_CB_STATE_PATH.read_text())
                if _CB_STATE_PATH.exists()
                else {}
            )
            cb = state.get(self.name, {})
            self._failure_count = cb.get("failure_count", 0)
            self._trip_count = cb.get("trip_count", 0)
            self._current_timeout = cb.get("current_timeout", self.recovery_timeout)
            self._last_failure_at = cb.get("last_failure_at")
            wall_opened_at = cb.get("opened_at")
            if wall_opened_at is not None:
                elapsed = time.time() - wall_opened_at
                if elapsed >= self._current_timeout:
                    # Recovery window already passed — start closed
                    self._opened_at = None
                    self._wall_opened_at = None
                    self._failure_count = 0
                else:
                    # Still within open window — reconstruct monotonic equivalent
                    self._opened_at = time.monotonic() - elapsed
                    self._wall_opened_at = wall_opened_at
            else:
                self._opened_at = None
                self._wall_opened_at = None
        except Exception as exc:
            _log.debug("CB state load failed (non-critical): %s", exc)

    def _save_state(self) -> None:
        if not self._persist:
            return
        try:
            state: dict = {}
            if _CB_STATE_PATH.exists():
                try:
                    state = json.loads(_CB_STATE_PATH.read_text())
                except Exception:
                    state = {}
            state[self.name] = {
                "failure_count": self._failure_count,
                "trip_count": self._trip_count,
                "current_timeout": self._current_timeout,
                "opened_at": self._wall_opened_at,
                "last_failure_at": self._last_failure_at,
                "saved_at": time.time(),
            }
            _CB_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
            _CB_STATE_PATH.write_text(json.dumps(state))
        except Exception as exc:
            _log.debug("CB state save failed (non-critical): %s", exc)

    def is_open(self) -> bool:
        with self._lock:
            if self._opened_at is None:
                return False
            elapsed = time.monotonic() - self._opened_at
            if elapsed >= self._current_timeout:
                _log.info(
                    "Circuit '%s' half-open after %.0fs — allowing probe",
                    self.name,
                    elapsed,
                )
                self._opened_at = None
                self._wall_opened_at = None
                self._failure_count = 0
                self._save_state()
                return False
            return True

    def record_failure(self) -> None:
        with self._lock:
            now_wall = time.time()
            if (
                self.burst_window > 0.0
                and self._last_failure_at is not None
                and now_wall - self._last_failure_at < self.burst_window
            ):
                # Still within the burst window — this failure is part of the same
                # parallel request batch; don't count it as a new failure event.
                return
            self._last_failure_at = now_wall
            self._failure_count += 1
            if self._failure_count >= self.failure_threshold:
                if self._opened_at is None:
                    self._trip_count += 1
                    # Apply backoff: timeout doubles on each consecutive trip
                    if self._trip_count > 1 and self.backoff_multiplier > 1.0:
                        self._current_timeout = min(
                            self.recovery_timeout
                            * (self.backoff_multiplier ** (self._trip_count - 1)),
                            86400.0,  # cap at 24 hours
                        )
                    self._opened_at = time.monotonic()
                    self._wall_opened_at = time.time()
                    _log.warning(
                        "Circuit '%s' OPEN after %d failures — will retry in %.0fs",
                        self.name,
                        self._failure_count,
                        self._current_timeout,
                    )
            self._save_state()

    def record_success(self) -> None:
        with self._lock:
            self._failure_count = 0
            self._opened_at = None
            self._wall_opened_at = None
            # _trip_count and _current_timeout are intentionally preserved across
            # successes so backoff accumulates over repeated open/close cycles.
            self._save_state()

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

    def seconds_until_retry(self) -> float:
        """Seconds remaining before the circuit allows a probe; 0.0 if closed."""
        with self._lock:
            if self._opened_at is None:
                return 0.0
            elapsed = time.monotonic() - self._opened_at
            remaining = self._current_timeout - elapsed
            return max(0.0, remaining)


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
