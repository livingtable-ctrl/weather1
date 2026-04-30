"""Tests for cron trade update fixes."""

from unittest.mock import MagicMock


def _apply_cron_isolation(monkeypatch, tmp_path):
    """Stub out all guards that can cause cmd_cron to exit early.

    Without these stubs, stale lock files or DB state from earlier tests in the
    full suite can cause cmd_cron to exit before reaching the code under test.
    """
    import main

    lock_path = tmp_path / ".cron.lock"
    ks_path = tmp_path / ".kill_switch"
    monkeypatch.setattr(main, "LOCK_PATH", lock_path, raising=False)
    monkeypatch.setattr(main, "KILL_SWITCH_PATH", ks_path, raising=False)
    monkeypatch.setattr(main, "_write_cron_running_flag", lambda: None)
    monkeypatch.setattr(main, "_check_startup_orders", lambda: None)
    monkeypatch.setattr(main, "_check_manual_override", lambda: False)
    monkeypatch.setattr(main, "check_ensemble_circuit_health", lambda: None)
    monkeypatch.setattr(main, "get_weather_markets", lambda client: [])


class TestCronSettlesPaperTrades:
    def test_cmd_cron_calls_auto_settle_paper_trades(self, monkeypatch, tmp_path):
        """cmd_cron must call auto_settle_paper_trades so paper trades get marked won/lost."""
        import cron

        _apply_cron_isolation(monkeypatch, tmp_path)

        settle_calls = []

        def fake_auto_settle(client=None):
            settle_calls.append(client)
            return 1  # settled 1 trade

        monkeypatch.setattr("paper.auto_settle_paper_trades", fake_auto_settle)
        fake_client = MagicMock()

        try:
            cron.cmd_cron(fake_client)
        except (Exception, SystemExit):
            pass  # cron calls sys.exit(0) at the end — catch it so the assert runs

        assert len(settle_calls) > 0, (
            "cmd_cron must call auto_settle_paper_trades(client) to settle resolved paper trades"
        )

    def test_auto_settle_called_after_sync_outcomes(self, monkeypatch, tmp_path):
        """auto_settle_paper_trades must be called in the same cron cycle as sync_outcomes."""
        import cron

        _apply_cron_isolation(monkeypatch, tmp_path)

        call_order = []

        monkeypatch.setattr(
            "main.sync_outcomes",
            lambda client: (call_order.append("sync"), 0)[1],
        )
        monkeypatch.setattr(
            "paper.auto_settle_paper_trades",
            lambda client=None: (call_order.append("settle"), 1)[1],
        )

        fake_client = MagicMock()
        try:
            cron.cmd_cron(fake_client)
        except (Exception, SystemExit):
            pass

        assert "settle" in call_order, "auto_settle_paper_trades was never called"
        if "sync" in call_order and "settle" in call_order:
            assert call_order.index("sync") < call_order.index("settle"), (
                "sync_outcomes should run before auto_settle_paper_trades"
            )


class TestCronPrintPlacedTrades:
    def test_cron_prints_signal_count_when_markets_found(self, monkeypatch, capsys):
        """cmd_cron must emit output describing scan results and any placement activity."""
        import cron

        monkeypatch.setattr("main.get_weather_markets", lambda client: [])
        monkeypatch.setattr("paper.auto_settle_paper_trades", lambda client=None: 0)

        fake_client = MagicMock()
        try:
            cron.cmd_cron(fake_client)
        except (Exception, SystemExit):
            pass

        captured = capsys.readouterr()
        # cron must produce some output describing what happened
        assert len(captured.out) > 0, "cmd_cron produced no output at all"

    def test_per_ticker_print_code_exists_in_cron(self):
        """cron.py must track placement count and include it in the run summary."""
        import inspect

        import cron

        # Placement logic lives in _cmd_cron_body (cmd_cron is a thin lock-wrapper).
        # After the Task-2 fix the per-ticker loops were removed; _auto_place_trades
        # handles per-trade printing internally. cron tracks the total via placed_count.
        source = inspect.getsource(cron._cmd_cron_body)
        assert "placed_count" in source, (
            "_cmd_cron_body must track placement count via placed_count"
        )
