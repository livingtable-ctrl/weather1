"""P0-2: LiveTradingGate must block live orders when graduation/safety gates fail."""

import os
from unittest.mock import MagicMock, patch

# Convenience context: both env vars required to pass the first two checks.
_PROD_ENV = {"KALSHI_ENV": "prod", "LIVE_TRADING_ENABLED": "true"}


class TestLiveTradingGate:
    def _gate(self):
        from trading_gates import LiveTradingGate

        return LiveTradingGate()

    def test_blocks_when_not_prod(self):
        gate = self._gate()
        with patch("main.KALSHI_ENV", "demo"):
            allowed, reason = gate.check()
        assert not allowed
        assert "not prod" in reason

    def test_blocks_when_live_trading_not_enabled(self):
        """LIVE_TRADING_ENABLED must be explicitly 'true' — KALSHI_ENV=prod alone is not enough."""
        gate = self._gate()
        with (
            patch("main.KALSHI_ENV", "prod"),
            patch.dict(os.environ, {"LIVE_TRADING_ENABLED": "false"}),
        ):
            allowed, reason = gate.check()
        assert not allowed
        assert "LIVE_TRADING_ENABLED" in reason

    def test_blocks_when_live_trading_env_absent(self):
        """Gate must block when LIVE_TRADING_ENABLED is not set at all."""
        gate = self._gate()
        env_without_flag = {
            k: v for k, v in os.environ.items() if k != "LIVE_TRADING_ENABLED"
        }
        with (
            patch("main.KALSHI_ENV", "prod"),
            patch.dict(os.environ, env_without_flag, clear=True),
        ):
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

        mock_client = MagicMock()
        mock_client.get_market.return_value = None  # skip analysis branch

        monkeypatch.setattr(main, "is_trading_paused", lambda: False)
        monkeypatch.setattr(
            "execution_log.was_recently_ordered", lambda ticker, side: False
        )
        monkeypatch.setattr("builtins.input", lambda _prompt="": "y")

        with (
            patch("main._kalshi_env", return_value="prod"),
            patch.dict(os.environ, {"LIVE_TRADING_ENABLED": "false"}),
        ):
            main.cmd_order(
                mock_client, "order", ["KXTEST-25JUN01-T70", "yes", "5", "0.50"]
            )

        mock_client.place_order.assert_not_called()
        assert "gate blocked" in capsys.readouterr().out.lower()

    def test_micro_live_blocked_by_gate(self, monkeypatch):
        """_micro_live_gate_ok() must return False when the live trading gate blocks."""
        from order_executor import _micro_live_gate_ok

        with (
            patch("main.KALSHI_ENV", "demo"),  # any failing gate condition works here
        ):
            assert _micro_live_gate_ok() is False
