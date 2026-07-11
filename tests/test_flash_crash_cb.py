"""Tests for per-market flash crash circuit breaker."""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestFlashCrashCB:
    def setup_method(self):
        # Isolation of circuit_breaker._FLASH_CRASH_HISTORY_PATH/
        # _FLASH_CRASH_COOLDOWN_PATH (and the flash_crash_cb singleton's
        # in-memory state) is handled by the autouse isolate_flash_crash_cb_state
        # fixture in conftest.py -- verified empirically that it takes effect
        # before setup_method runs, so FlashCrashCB() built here picks up the
        # redirected paths with no per-file isolation code needed.
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


class TestFlashCrashCBHistoryPersistence:
    """Proves the actual point of persisting _history to disk: two SEPARATE
    FlashCrashCB instances sharing the same disk path (simulating two
    separate process invocations, e.g. two `python main.py cron` runs close
    together) must be able to detect a crash across that boundary -- before
    this fix, _history was in-memory only, so a fresh instance/process could
    never see a prior instance's observations and detection was impossible.
    Every other test in this file uses one long-lived `self.cb`, which would
    still pass even if _save_history()/_load_history() were silently
    reverted -- this is the one test that would actually catch that."""

    def test_second_instance_on_same_path_detects_crash_from_first(self):
        from circuit_breaker import FlashCrashCB

        # Both instances share the same (test-isolated) disk path via the
        # autouse fixture's redirected circuit_breaker._FLASH_CRASH_HISTORY_PATH.
        first = FlashCrashCB(threshold_pct=0.20, window_seconds=300)
        assert first.check("TICKER-CROSS", 0.60) is False

        second = FlashCrashCB(threshold_pct=0.20, window_seconds=300)
        assert second.check("TICKER-CROSS", 0.45) is True  # -25%, seen via disk

    def test_second_instance_does_not_false_positive_on_small_move(self):
        from circuit_breaker import FlashCrashCB

        first = FlashCrashCB(threshold_pct=0.20, window_seconds=300)
        assert first.check("TICKER-CROSS-2", 0.60) is False

        second = FlashCrashCB(threshold_pct=0.20, window_seconds=300)
        assert second.check("TICKER-CROSS-2", 0.62) is False  # +3%, no crash
