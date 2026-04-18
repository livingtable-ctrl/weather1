"""
Smoke tests for cmd_cron — the main production execution path.
Tests the guards (kill switch, accuracy halt) at the entry point level.
All external I/O is mocked.
"""

from unittest.mock import MagicMock

import pytest


@pytest.fixture()
def minimal_mocks(tmp_path, monkeypatch):
    """Patch every external call cmd_cron makes so it can run without network."""
    import main

    # Redirect lock and kill-switch paths to tmp_path so they don't interfere with production
    lock_path = tmp_path / ".cron.lock"
    ks_path = tmp_path / ".kill_switch"
    monkeypatch.setattr(main, "LOCK_PATH", lock_path, raising=False)
    monkeypatch.setattr(main, "KILL_SWITCH_PATH", ks_path, raising=False)

    # No markets returned by default
    monkeypatch.setattr(main, "get_weather_markets", lambda client: [])

    # Suppress manual-override file check
    monkeypatch.setattr(main, "_check_manual_override", lambda: False)

    # Suppress startup-orders file check
    monkeypatch.setattr(main, "_check_startup_orders", lambda: None)

    # Suppress write of the running flag
    monkeypatch.setattr(main, "_write_cron_running_flag", lambda: None)

    # Suppress circuit-health check (avoids hitting weather APIs)
    monkeypatch.setattr(main, "check_ensemble_circuit_health", lambda: None)

    return tmp_path


class TestCmdCronGuards:
    def test_kill_switch_blocks_market_scan(self, minimal_mocks, monkeypatch):
        """cmd_cron exits early when the kill switch file is present."""
        import main

        ks_path = minimal_mocks / ".kill_switch"
        ks_path.write_text('{"reason": "test"}')
        monkeypatch.setattr(main, "KILL_SWITCH_PATH", ks_path, raising=False)

        scan_called = []
        monkeypatch.setattr(
            main, "get_weather_markets", lambda c: scan_called.append(1) or []
        )
        client = MagicMock()
        main.cmd_cron(client)
        assert scan_called == [], (
            "market scan should be skipped when kill switch is active"
        )

    def test_accuracy_halt_blocks_market_scan(self, minimal_mocks, monkeypatch):
        """cmd_cron exits early when the accuracy circuit breaker is active."""
        import main
        import paper

        monkeypatch.setattr(paper, "is_accuracy_halted", lambda: True)

        scan_called = []
        monkeypatch.setattr(
            main, "get_weather_markets", lambda c: scan_called.append(1) or []
        )
        client = MagicMock()
        main.cmd_cron(client)
        assert scan_called == [], "market scan should be skipped on accuracy halt"

    def test_empty_market_list_runs_cleanly(self, minimal_mocks):
        """cmd_cron with no markets returned completes without error."""
        import main

        # Set _called_from_loop to prevent sys.exit(0) at end of cron
        main.cmd_cron._called_from_loop = True
        try:
            client = MagicMock()
            main.cmd_cron(client)  # should not raise
        finally:
            main.cmd_cron._called_from_loop = False
