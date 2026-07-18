"""P0-2: LiveTradingGate must block live orders when graduation/safety gates fail."""

import os
from unittest.mock import MagicMock, patch

# Convenience context: both env vars required to pass the first two checks.
_PROD_ENV = {"KALSHI_ENV": "prod", "LIVE_TRADING_ENABLED": "true"}


class TestLiveTradingGate:
    def _gate(self):
        from trading_gates import LiveTradingGate

        return LiveTradingGate()

    def test_blocks_when_kill_switch_active(self, tmp_path, monkeypatch):
        """The kill switch must block every live-order path through this shared
        gate, not just the automated cron/watch loops that check
        KILL_SWITCH_PATH directly — before this check, cmd_order/the
        maker-order flow bypassed it entirely (found via a deep code review,
        2026-07-08)."""
        import trading_gates

        kill_path = tmp_path / ".kill_switch"
        kill_path.touch()
        monkeypatch.setattr(trading_gates, "KILL_SWITCH_PATH", kill_path)

        gate = self._gate()
        with (
            patch("main.KALSHI_ENV", "prod"),
            patch.dict(os.environ, _PROD_ENV),
            patch("paper.graduation_check", return_value={"settled": 35}),
            patch("paper.is_paused_drawdown", return_value=False),
            patch("paper.is_daily_loss_halted", return_value=False),
            patch("paper.is_accuracy_halted", return_value=False),
            patch("paper.is_streak_paused", return_value=False),
        ):
            allowed, reason = gate.check()
        assert not allowed
        assert "kill switch" in reason.lower()

    def test_blocks_when_not_prod(self, monkeypatch):
        """No-client fallback now reads os.getenv("KALSHI_ENV") directly (not
        `import main`, per this file's own documented reason for avoiding that
        pattern) -- patch the real env var, not main.KALSHI_ENV."""
        gate = self._gate()
        monkeypatch.setenv("KALSHI_ENV", "demo")
        allowed, reason = gate.check()
        assert not allowed
        assert "not prod" in reason

    def test_blocks_when_live_trading_not_enabled(self):
        """LIVE_TRADING_ENABLED must be explicitly 'true' — KALSHI_ENV=prod alone is not enough.

        No-client fallback reads os.getenv("KALSHI_ENV") directly (see
        test_blocks_when_not_prod's docstring) -- patch the real env var,
        not main.KALSHI_ENV, which this code path never reads. The prior
        `patch("main.KALSHI_ENV", "prod")` here was a no-op that happened
        to pass locally only because a real (gitignored) .env sets
        KALSHI_ENV=prod for this dev machine -- CI has no .env, so
        os.getenv("KALSHI_ENV", "demo") fell through to "demo" there and
        the gate blocked on "not prod" before ever reaching the
        LIVE_TRADING_ENABLED check this test is actually about."""
        gate = self._gate()
        with patch.dict(
            os.environ, {"KALSHI_ENV": "prod", "LIVE_TRADING_ENABLED": "false"}
        ):
            allowed, reason = gate.check()
        assert not allowed
        assert "LIVE_TRADING_ENABLED" in reason

    def test_blocks_when_live_trading_env_absent(self):
        """Gate must block when LIVE_TRADING_ENABLED is not set at all.

        See test_blocks_when_live_trading_not_enabled's docstring -- same
        real-env-var fix, needed here too since gate.check() is called
        with no client."""
        gate = self._gate()
        env_without_flag = {
            k: v for k, v in os.environ.items() if k != "LIVE_TRADING_ENABLED"
        }
        env_without_flag["KALSHI_ENV"] = "prod"
        with patch.dict(os.environ, env_without_flag, clear=True):
            allowed, reason = gate.check()
        assert not allowed
        assert "LIVE_TRADING_ENABLED" in reason

    def test_blocks_when_graduation_not_met(self):
        gate = self._gate()
        with (
            patch("main.KALSHI_ENV", "prod"),
            patch.dict(os.environ, _PROD_ENV),
            patch("paper.graduation_check", return_value=None),
            patch("paper.is_paused_drawdown", return_value=False),
            patch("paper.is_daily_loss_halted", return_value=False),
            patch("paper.is_accuracy_halted", return_value=False),
            patch("paper.is_streak_paused", return_value=False),
        ):
            allowed, reason = gate.check()
        assert not allowed
        assert "Graduation" in reason

    def test_blocks_when_drawdown_halt(self):
        gate = self._gate()
        with (
            patch("main.KALSHI_ENV", "prod"),
            patch.dict(os.environ, _PROD_ENV),
            patch("paper.graduation_check", return_value={"settled": 35}),
            patch("paper.is_paused_drawdown", return_value=True),
            patch("paper.is_daily_loss_halted", return_value=False),
            patch("paper.is_accuracy_halted", return_value=False),
            patch("paper.is_streak_paused", return_value=False),
        ):
            allowed, reason = gate.check()
        assert not allowed
        assert "Drawdown" in reason

    def test_blocks_when_daily_loss_halted(self):
        gate = self._gate()
        with (
            patch("main.KALSHI_ENV", "prod"),
            patch.dict(os.environ, _PROD_ENV),
            patch("paper.graduation_check", return_value={"settled": 35}),
            patch("paper.is_paused_drawdown", return_value=False),
            patch("paper.is_daily_loss_halted", return_value=True),
            patch("paper.is_accuracy_halted", return_value=False),
            patch("paper.is_streak_paused", return_value=False),
        ):
            allowed, reason = gate.check()
        assert not allowed
        assert "Daily loss" in reason

    def test_daily_loss_check_receives_the_client(self):
        """2026-07-09: check() previously called is_daily_loss_halted() with
        no args, so the daily-loss halt could never include unrealized MTM
        on open positions (paper.get_daily_pnl's client-optional #46
        feature) even though check() has the client in scope. Confirm the
        client is actually forwarded, not just that the check runs."""
        from kalshi_client import PROD_BASE

        gate = self._gate()
        mock_client = MagicMock()
        mock_client.base_url = PROD_BASE
        received = {}

        def _fake_halted(client=None):
            received["client"] = client
            return False

        with (
            patch.dict(os.environ, _PROD_ENV),
            patch("paper.graduation_check", return_value={"settled": 35}),
            patch("paper.is_paused_drawdown", return_value=False),
            patch("paper.is_daily_loss_halted", _fake_halted),
            patch("paper.is_accuracy_halted", return_value=False),
            patch("paper.is_streak_paused", return_value=False),
        ):
            allowed, reason = gate.check(mock_client)

        assert allowed
        assert received["client"] is mock_client

    def test_blocks_when_accuracy_halted(self):
        gate = self._gate()
        with (
            patch("main.KALSHI_ENV", "prod"),
            patch.dict(os.environ, _PROD_ENV),
            patch("paper.graduation_check", return_value={"settled": 35}),
            patch("paper.is_paused_drawdown", return_value=False),
            patch("paper.is_daily_loss_halted", return_value=False),
            patch("paper.is_accuracy_halted", return_value=True),
            patch("paper.is_streak_paused", return_value=False),
        ):
            allowed, reason = gate.check()
        assert not allowed
        assert "Accuracy" in reason

    def test_blocks_when_streak_paused(self):
        gate = self._gate()
        with (
            patch("main.KALSHI_ENV", "prod"),
            patch.dict(os.environ, _PROD_ENV),
            patch("paper.graduation_check", return_value={"settled": 35}),
            patch("paper.is_paused_drawdown", return_value=False),
            patch("paper.is_daily_loss_halted", return_value=False),
            patch("paper.is_accuracy_halted", return_value=False),
            patch("paper.is_streak_paused", return_value=True),
        ):
            allowed, reason = gate.check()
        assert not allowed
        assert "streak" in reason.lower()

    def test_allows_when_all_gates_pass(self):
        gate = self._gate()
        with (
            patch("main.KALSHI_ENV", "prod"),
            patch.dict(os.environ, _PROD_ENV),
            patch("paper.graduation_check", return_value={"settled": 35}),
            patch("paper.is_paused_drawdown", return_value=False),
            patch("paper.is_daily_loss_halted", return_value=False),
            patch("paper.is_accuracy_halted", return_value=False),
            patch("paper.is_streak_paused", return_value=False),
        ):
            allowed, reason = gate.check()
        assert allowed
        assert reason == "ok"

    def test_check_or_raise_raises_when_blocked(self):
        import pytest

        gate = self._gate()
        with patch("main.KALSHI_ENV", "demo"):
            with pytest.raises(RuntimeError, match="gate blocked"):
                gate.check_or_raise()

    def test_place_live_order_blocked_by_gate(self):
        """_place_live_order must return (False, 0.0) when gate blocks."""
        import main

        mock_client = MagicMock()
        analysis = {"market": {}, "kelly_quantity": 5, "edge": 0.10}
        config = {
            "daily_loss_limit": 100,
            "max_open_positions": 10,
            "max_trade_dollars": 50,
        }

        with patch("main.KALSHI_ENV", "demo"):
            placed, cost = main._place_live_order(
                ticker="KXTEST-25JUN01-T70",
                side="yes",
                analysis=analysis,
                config=config,
                client=mock_client,
                cycle="test-cycle",
            )

        assert not placed
        assert cost == 0.0
        mock_client.place_order.assert_not_called()

    def test_cmd_order_blocked_by_gate(self, monkeypatch, capsys):
        """cmd_order (manual CLI order) must not bypass the live trading gate."""
        import main
        from kalshi_client import PROD_BASE

        mock_client = MagicMock()
        mock_client.get_market.return_value = None  # skip analysis branch
        mock_client.base_url = PROD_BASE  # so the outer client-base_url guard
        # (which now decides whether to even call the gate) recognizes this
        # as a prod client and proceeds to the gate, which then blocks on
        # LIVE_TRADING_ENABLED as this test intends.

        monkeypatch.setattr(main, "is_trading_paused", lambda: False)
        monkeypatch.setattr(
            "execution_log.was_recently_ordered", lambda ticker, side: False
        )
        monkeypatch.setattr("builtins.input", lambda _prompt="": "y")

        with (
            patch("main.KALSHI_ENV", "prod"),
            patch.dict(os.environ, {"LIVE_TRADING_ENABLED": "false"}),
        ):
            main.cmd_order(
                mock_client, "order", ["KXTEST-25JUN01-T70", "yes", "5", "0.50"]
            )

        mock_client.place_order.assert_not_called()
        assert "gate blocked" in capsys.readouterr().out.lower()

    def test_cmd_order_gates_client_missing_base_url(self, monkeypatch, capsys):
        """2026-07-09 follow-up: the outer guard must REQUIRE the gate for a
        client it can't positively identify as demo, not skip it. Before this
        fix the outer guard was `== PROD_BASE`, so a client lacking base_url
        entirely (None) would silently skip the gate and place unguarded --
        the same fail-open shape as the bug this whole line of work started
        from. `!= DEMO_BASE` closes it: unknown base_url now requires the
        gate, which itself already fails closed on a non-prod base_url."""
        import main

        mock_client = MagicMock()
        mock_client.get_market.return_value = None
        del mock_client.base_url  # getattr(..., None) now returns None, not a Mock

        monkeypatch.setattr(main, "is_trading_paused", lambda: False)
        monkeypatch.setattr(
            "execution_log.was_recently_ordered", lambda ticker, side: False
        )
        monkeypatch.setattr("builtins.input", lambda _prompt="": "y")

        main.cmd_order(mock_client, "order", ["KXTEST-25JUN01-T70", "yes", "5", "0.50"])

        mock_client.place_order.assert_not_called()
        assert "gate blocked" in capsys.readouterr().out.lower()

    def test_micro_live_blocked_by_gate(self, monkeypatch):
        """_micro_live_gate_ok() must return False when the live trading gate blocks."""
        from order_executor import _micro_live_gate_ok

        with (
            patch("main.KALSHI_ENV", "demo"),  # any failing gate condition works here
        ):
            assert _micro_live_gate_ok() is False

    def test_micro_live_gate_ok_uses_the_client_it_is_passed(self):
        """The real call site (order_executor.py:1741) passes its own client
        through — exercise that path directly, not just the no-client env
        fallback above, so a future regression in the threading itself would
        be caught here."""
        from kalshi_client import DEMO_BASE, PROD_BASE
        from order_executor import _micro_live_gate_ok

        demo_client = MagicMock()
        demo_client.base_url = DEMO_BASE
        assert _micro_live_gate_ok(demo_client) is False

        prod_client = MagicMock()
        prod_client.base_url = PROD_BASE
        with patch.dict(os.environ, {"LIVE_TRADING_ENABLED": "false"}):
            # Still blocked (LIVE_TRADING_ENABLED false) — proves the prod
            # client actually reached the rest of the gate, not just that
            # SOME check happened to fail.
            assert _micro_live_gate_ok(prod_client) is False

    def test_quick_paper_buy_maker_order_blocked_by_gate(self, monkeypatch, capsys):
        """_quick_paper_buy's maker-order branch places a REAL order — despite the
        function's name, it must not bypass the live trading gate."""
        import main
        from kalshi_client import PROD_BASE

        mock_client = MagicMock()
        mock_client.get_market.return_value = {}
        mock_client.base_url = PROD_BASE  # so the outer client-base_url guard
        # recognizes this as a prod client and proceeds to the gate, which
        # then blocks on LIVE_TRADING_ENABLED as this test intends.

        monkeypatch.setattr(main, "is_trading_paused", lambda: False)
        monkeypatch.setattr(main, "_resolve_price", lambda client, ticker, side: 0.45)
        monkeypatch.setattr("paper.is_daily_loss_halted", lambda: False)
        monkeypatch.setattr("paper.is_streak_paused", lambda: False)
        _inputs = iter(
            [
                "KXTEST-25JUN01-T70",  # ticker
                "yes",  # side
                "2",  # order type: limit maker
                "0.45",  # limit price
                "5",  # qty
                "",  # thesis
            ]
        )
        monkeypatch.setattr("builtins.input", lambda *_a: next(_inputs))

        with (
            patch("main.KALSHI_ENV", "prod"),
            patch.dict(os.environ, {"LIVE_TRADING_ENABLED": "false"}),
        ):
            main._quick_paper_buy(mock_client)

        mock_client.place_maker_order.assert_not_called()
        assert "gate blocked" in capsys.readouterr().out.lower()

    def test_quick_paper_buy_gates_client_missing_base_url(self, monkeypatch, capsys):
        """Mirror of test_cmd_order_gates_client_missing_base_url for the
        maker-order flow's outer guard."""
        import main

        mock_client = MagicMock()
        mock_client.get_market.return_value = {}
        del mock_client.base_url

        monkeypatch.setattr(main, "is_trading_paused", lambda: False)
        monkeypatch.setattr(main, "_resolve_price", lambda client, ticker, side: 0.45)
        monkeypatch.setattr("paper.is_daily_loss_halted", lambda: False)
        monkeypatch.setattr("paper.is_streak_paused", lambda: False)
        _inputs = iter(
            [
                "KXTEST-25JUN01-T70",  # ticker
                "yes",  # side
                "2",  # order type: limit maker
                "0.45",  # limit price
                "5",  # qty
                "",  # thesis
            ]
        )
        monkeypatch.setattr("builtins.input", lambda *_a: next(_inputs))

        main._quick_paper_buy(mock_client)

        mock_client.place_maker_order.assert_not_called()
        assert "gate blocked" in capsys.readouterr().out.lower()

    def test_client_base_url_wins_over_stale_kalshi_env_demo_direction(self):
        """2026-07-09: `import main` inside check() re-executes main.py as a
        second module (main.py runs as __main__, so this is a fresh module
        object, not a frozen one) — a call site's own separately-read
        KALSHI_ENV could disagree with it. Passing `client` removes the env
        read from the decision entirely: a demo client must block even if
        some stale/mocked KALSHI_ENV elsewhere claims prod."""
        from kalshi_client import DEMO_BASE

        gate = self._gate()
        mock_client = MagicMock()
        mock_client.base_url = DEMO_BASE

        with patch("main.KALSHI_ENV", "prod"):  # deliberately disagrees with client
            allowed, reason = gate.check(mock_client)

        assert not allowed
        assert "not pointed at prod" in reason

    def test_client_base_url_wins_over_stale_kalshi_env_prod_direction(self):
        """Mirror of the above in the safety-critical direction: a prod
        client must still be fully gated even if some stale/mocked
        KALSHI_ENV elsewhere claims demo — fail-closed, not fail-open."""
        from kalshi_client import PROD_BASE

        gate = self._gate()
        mock_client = MagicMock()
        mock_client.base_url = PROD_BASE

        with (
            patch("main.KALSHI_ENV", "demo"),  # deliberately disagrees with client
            patch.dict(os.environ, {"LIVE_TRADING_ENABLED": "false"}),
        ):
            allowed, reason = gate.check(mock_client)

        assert not allowed
        # Reached the LIVE_TRADING_ENABLED check (not blocked on "not prod"),
        # proving the client's base_url — not the stale env var — governed
        # whether the rest of the gate applies.
        assert "LIVE_TRADING_ENABLED" in reason

    def test_client_prod_base_url_reaches_full_gate(self):
        """A genuine prod client with everything else passing is allowed —
        confirms the client-based path isn't just fail-closed by accident."""
        gate = self._gate()
        mock_client = MagicMock()
        from kalshi_client import PROD_BASE

        mock_client.base_url = PROD_BASE

        with (
            patch.dict(os.environ, _PROD_ENV),
            patch("paper.graduation_check", return_value={"settled": 35}),
            patch("paper.is_paused_drawdown", return_value=False),
            patch("paper.is_daily_loss_halted", return_value=False),
            patch("paper.is_accuracy_halted", return_value=False),
            patch("paper.is_streak_paused", return_value=False),
        ):
            allowed, reason = gate.check(mock_client)

        assert allowed
        assert reason == "ok"
