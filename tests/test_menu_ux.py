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


class TestExitSignals:
    """Tests for the paper submenu 'Exit signals' branch (sub == '4')."""

    def _run_paper_sub4(
        self, monkeypatch, fake_recs, input_seq, close_mock, midpoint_val=0.54
    ):
        """Helper: drive cmd_menu → P(aper) → 4(exit signals), capturing stdout."""
        from unittest.mock import MagicMock

        import main

        monkeypatch.setattr("paper.check_model_exits", lambda *a: fake_recs)
        monkeypatch.setattr("paper.close_paper_early", close_mock)
        monkeypatch.setattr(main, "_midpoint_price", lambda m, s: midpoint_val)

        # "P" → paper submenu; "4" → exit signals; then per-signal inputs;
        # "" → Press Enter to return; "Q" → Quit
        inputs = iter(["P", "4"] + input_seq + ["", "Q"])
        monkeypatch.setattr("builtins.input", lambda *a: next(inputs, "Q"))

        client = MagicMock()
        try:
            main.cmd_menu(client)
        except (SystemExit, StopIteration):
            pass

    def test_exit_signals_skipped_when_user_says_no(self, monkeypatch, capsys):
        """When user says n, should print 'skipped' confirmation and NOT call close_paper_early."""
        fake_trade = {
            "id": 42,
            "ticker": "KXHIGHNY-25APR30-T65",
            "side": "yes",
            "qty": 10,
            "entry_price": 0.60,
        }
        fake_market = {"yes_ask": 55, "yes_bid": 53, "ticker": "KXHIGHNY-25APR30-T65"}
        fake_recs = [
            {
                "trade": fake_trade,
                "reason": "model_flipped",
                "current_edge": -0.12,
                "held_side": "yes",
                "market": fake_market,
            }
        ]

        close_calls = []
        self._run_paper_sub4(
            monkeypatch,
            fake_recs,
            input_seq=["n"],
            close_mock=lambda tid, ep: close_calls.append((tid, ep)),
        )
        out = capsys.readouterr().out
        assert "skipped" in out.lower(), (
            f"Expected 'skipped' in output when user says n, got:\n{out}"
        )
        assert close_calls == [], (
            "close_paper_early must NOT be called when user says n"
        )

    def test_exit_signals_closes_when_user_says_yes(self, monkeypatch, capsys):
        """When user says y, close_paper_early must be called with (trade_id, midpoint_price)."""

        fake_trade = {
            "id": 7,
            "ticker": "KXLOWCHI-25APR30-T40",
            "side": "no",
            "qty": 5,
            "entry_price": 0.45,
        }
        fake_market = {"yes_ask": 62, "yes_bid": 60, "ticker": "KXLOWCHI-25APR30-T40"}
        fake_recs = [
            {
                "trade": fake_trade,
                "reason": "edge_gone",
                "current_edge": -0.15,
                "held_side": "no",
                "market": fake_market,
            }
        ]

        close_calls = []
        self._run_paper_sub4(
            monkeypatch,
            fake_recs,
            input_seq=["y"],
            close_mock=lambda tid, ep: close_calls.append((tid, ep)) or fake_trade,
            midpoint_val=0.61,
        )
        out = capsys.readouterr().out
        assert close_calls == [(7, 0.61)], (
            f"Expected close call with (7, 0.61), got {close_calls}"
        )
        assert "closed" in out.lower(), (
            f"Expected 'closed' confirmation in output, got:\n{out}"
        )

    def test_exit_signals_keyboard_interrupt_returns_to_menu(self, monkeypatch, capsys):
        """Ctrl+C on the close prompt must not crash — menu should continue."""
        from unittest.mock import MagicMock

        import main

        fake_trade = {
            "id": 99,
            "ticker": "KXHIGHNY-25APR30-T70",
            "side": "yes",
            "qty": 3,
            "entry_price": 0.55,
        }
        fake_market = {"yes_ask": 50, "yes_bid": 48, "ticker": "KXHIGHNY-25APR30-T70"}
        fake_recs = [
            {
                "trade": fake_trade,
                "reason": "model_flipped",
                "current_edge": -0.11,
                "held_side": "yes",
                "market": fake_market,
            }
        ]

        monkeypatch.setattr("paper.check_model_exits", lambda *a: fake_recs)
        monkeypatch.setattr(main, "_midpoint_price", lambda m, s: 0.49)

        call_count = {"n": 0}

        def _input(prompt=""):
            call_count["n"] += 1
            # 1: "P" (paper), 2: "4" (exit signals), 3: close prompt → KBI, 4+: "Q"
            seq = ["P", "4"]
            if call_count["n"] <= len(seq):
                return seq[call_count["n"] - 1]
            if call_count["n"] == len(seq) + 1:
                raise KeyboardInterrupt
            return "Q"

        monkeypatch.setattr("builtins.input", _input)

        client = MagicMock()
        crashed = False
        try:
            main.cmd_menu(client)
        except KeyboardInterrupt:
            crashed = True
        except (SystemExit, StopIteration):
            pass

        assert not crashed, (
            "KeyboardInterrupt on close prompt must be caught and not escape the menu"
        )
