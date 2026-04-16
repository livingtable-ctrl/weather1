"""Tests for per-market flash crash circuit breaker."""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestFlashCrashCB:
    def setup_method(self):
        from circuit_breaker import FlashCrashCB

        self.cb = FlashCrashCB(
            threshold_pct=0.20, window_seconds=300, cooldown_seconds=600
        )

    def test_no_crash_on_first_observation(self):
        assert self.cb.check("TICKER-A", 0.50) is False

    def test_no_crash_on_small_move(self):
        self.cb.check("TICKER-A", 0.50)
        assert self.cb.check("TICKER-A", 0.55) is False

    def test_crash_on_large_move(self):
        self.cb.check("TICKER-A", 0.60)
        assert self.cb.check("TICKER-A", 0.45) is True  # -25%

    def test_cooldown_prevents_trading(self):
        self.cb.check("TICKER-B", 0.60)
        self.cb.check("TICKER-B", 0.40)  # -33% → crash
        assert self.cb.is_in_cooldown("TICKER-B") is True

    def test_different_tickers_independent(self):
        self.cb.check("TICKER-C", 0.80)
        self.cb.check("TICKER-C", 0.40)
        assert self.cb.is_in_cooldown("TICKER-C") is True
        assert self.cb.is_in_cooldown("TICKER-D") is False

    def test_no_cooldown_on_clean_ticker(self):
        assert self.cb.is_in_cooldown("BRAND-NEW") is False

    def test_cooldown_expires(self):
        from circuit_breaker import FlashCrashCB

        cb = FlashCrashCB(threshold_pct=0.20, window_seconds=1, cooldown_seconds=1)
        cb.check("TICKER-E", 0.80)
        cb.check("TICKER-E", 0.40)
        assert cb.is_in_cooldown("TICKER-E") is True
        time.sleep(1.1)
        assert cb.is_in_cooldown("TICKER-E") is False

    def test_upward_spike_also_triggers(self):
        self.cb.check("TICKER-F", 0.30)
        assert self.cb.check("TICKER-F", 0.70) is True  # +133%
