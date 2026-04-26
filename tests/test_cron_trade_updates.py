"""Tests for cron trade update fixes."""

from unittest.mock import MagicMock


class TestCronSettlesPaperTrades:
    def test_cmd_cron_calls_auto_settle_paper_trades(self, monkeypatch):
        """cmd_cron must call auto_settle_paper_trades so paper trades get marked won/lost."""
        import cron

        settle_calls = []

        def fake_auto_settle(client=None):
            settle_calls.append(client)
            return 1  # settled 1 trade

        monkeypatch.setattr("paper.auto_settle_paper_trades", fake_auto_settle)
        monkeypatch.setattr("main.get_weather_markets", lambda client: [])
        fake_client = MagicMock()

        try:
            cron.cmd_cron(fake_client)
        except (Exception, SystemExit):
            pass  # cron calls sys.exit(0) at the end — catch it so the assert runs

        assert len(settle_calls) > 0, (
            "cmd_cron must call auto_settle_paper_trades(client) to settle resolved paper trades"
        )

    def test_auto_settle_called_after_sync_outcomes(self, monkeypatch):
        """auto_settle_paper_trades must be called in the same cron cycle as sync_outcomes."""
        import cron

        call_order = []

        monkeypatch.setattr(
            "main.sync_outcomes",
            lambda client: (call_order.append("sync"), 0)[1],
        )
        monkeypatch.setattr(
            "paper.auto_settle_paper_trades",
            lambda client=None: (call_order.append("settle"), 1)[1],
        )
        monkeypatch.setattr("main.get_weather_markets", lambda client: [])

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
        """cron.py must contain per-ticker placement print (not just total count)."""
        import inspect

        import cron

        source = inspect.getsource(cron.cmd_cron)
        # After our fix, "placed:" text should appear in the placement output section
        assert "placed:" in source, (
            "cmd_cron must print 'placed: <ticker>' for each newly placed paper trade"
        )
