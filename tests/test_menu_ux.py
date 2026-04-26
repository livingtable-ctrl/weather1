"""Tests for menu UX fixes."""

import sys
from unittest.mock import MagicMock, patch


class TestCronOutputFlush:
    def test_stdout_flushed_before_cmd_cron(self, monkeypatch):
        """sys.stdout.flush() must be called before cmd_cron in the menu loop."""
        import main

        flush_calls = []
        cron_calls = []

        def fake_flush():
            flush_calls.append(len(cron_calls))  # capture flush order relative to cron

        def fake_cron(client):
            cron_calls.append(True)

        monkeypatch.setattr(sys.stdout, "flush", fake_flush)
        monkeypatch.setattr(main, "cmd_cron", fake_cron)

        fake_client = MagicMock()
        # "L" = Cron option, "Q" = Quit
        with patch("builtins.input", side_effect=["L", "Q"]):
            try:
                main.cmd_menu(fake_client)
            except (SystemExit, StopIteration, EOFError):
                pass

        assert cron_calls, "cmd_cron was never called — check menu label matches 'Cron'"
        assert flush_calls, "sys.stdout.flush() was never called"
        # At least one flush must have happened before cron (i.e. cron_calls was 0 at flush time)
        assert 0 in flush_calls, "flush must be called BEFORE cmd_cron, not after"

    def test_cron_option_actually_runs_cmd_cron(self, monkeypatch):
        """Menu 'Cron' option must call cmd_cron (was broken when label != elif check)."""
        import main

        cron_called = []

        monkeypatch.setattr(main, "cmd_cron", lambda c: cron_called.append(True))

        fake_client = MagicMock()
        with patch("builtins.input", side_effect=["L", "Q"]):
            try:
                main.cmd_menu(fake_client)
            except (SystemExit, StopIteration, EOFError):
                pass

        assert len(cron_called) == 1, (
            "Selecting 'Cron' from the menu must call cmd_cron exactly once"
        )


class TestCancelAnalyze:
    def test_keyboard_interrupt_in_analyze_returns_to_menu(self, monkeypatch):
        """KeyboardInterrupt inside cmd_analyze must not kill the menu."""
        import main

        def fake_analyze(client, **kwargs):
            raise KeyboardInterrupt

        monkeypatch.setattr(main, "cmd_analyze", fake_analyze)

        fake_client = MagicMock()
        menu_returned = False

        # "A" = Analyze, "Q" = Quit
        with patch("builtins.input", side_effect=["A", "Q"]):
            try:
                main.cmd_menu(fake_client)
                menu_returned = True
            except KeyboardInterrupt:
                pass  # This would be the bug — interrupt escaped the menu

        assert menu_returned, (
            "KeyboardInterrupt inside cmd_analyze should be caught and return to menu"
        )


class TestBriefCloseable:
    def test_brief_exception_still_shows_press_enter(self, monkeypatch, capsys):
        """If cmd_brief raises, the menu must still show the press-Enter prompt."""
        import main

        def fake_brief(client, **kwargs):
            raise RuntimeError("brief error")

        monkeypatch.setattr(main, "cmd_brief", fake_brief)
        fake_client = MagicMock()

        # "R" = Brief, "" = press Enter, "Q" = Quit
        with patch("builtins.input", side_effect=["R", "", "Q"]):
            try:
                main.cmd_menu(fake_client)
            except (Exception, SystemExit):
                pass

        captured = capsys.readouterr()
        assert "Press Enter" in captured.out, (
            "Menu must always show 'Press Enter to return' even if cmd_brief raises"
        )
